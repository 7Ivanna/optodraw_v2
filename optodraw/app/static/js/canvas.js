import { FREE_SHAPES } from "./palette.js";
import { createSvgAnimator } from "./svg_anim.js";

// Interactive SVG canvas: multi-select, drag-move, rotate, zoom/pan, snap, connect.
//
// Coordinate model (derived from the renderer's actual output):
//   - SVG viewBox is origin-centered, y-down. Component groups are
//     <g transform="translate(worldX, -worldY) rotate(angle)" data-component-id>
//     under an identity root <g>.  world (x, y) -> svg-user (x, -y).
// Interaction: click selects; Shift+click toggles; drag empty = marquee select;
// Space+drag or middle-drag = pan; drag a selected component = move the selection.
//
// Workspace model (KLayout-style): the plane is UNBOUNDED. The SVG element fills
// the stage and a persistent camera {cx, cy, scale px/unit} derives the viewBox
// each frame — the server-rendered viewBox is only read as the scene's nominal
// export frame (drawn as a dashed guide, never a clip). Zoom is clamped on the
// absolute px-per-unit scale, so no render/resize can unlock runaway zoom.

const HANDLE_GAP = 6;
const BOX_PAD = 1.5;
const ZOOM_STEP = 1.15;
const MAX_PX_PER_UNIT = 2400;   // deepest zoom-in: 1 scene unit spans 2400px
const MAX_VIEW_UNITS = 2e6;     // widest zoom-out: viewport spans 2M scene units
const GRID_MAX_LINES = 240;     // per axis — the grid coarsens ×5 beyond this
const NS = "http://www.w3.org/2000/svg";

export function createCanvas({ el, onSelect, onCommit, onLiveMove, getSnap, onView, onConnectPick, onRouteEdit, onCursor, onOpen, onResize }) {
  let spec = null;
  let selectedIds = []; // multi-select; primary = selectedIds[0]
  let drag = null;
  let mode = "select"; // "select" | "connect"
  let spaceDown = false;
  let portsMap = {};
  let anchorKey = null;
  let anchorFamily = null;
  let waypointPts = [];
  let frameBox = null;  // the scene's nominal export frame (server viewBox) — a guide, not a bound
  let camera = null;    // { cx, cy, scale }: view center (svg-user units) + px per unit
  let cameraProvisional = false; // camera was fit while the stage had no layout
  let viewBox = null;   // derived from camera + stage size on every applyCamera()
  let animPayloads = null;
  let svgAnimator = null;

  const snap = () => (getSnap ? getSnap() : { grid: 0, angle: 0 });

  // Derived indexes rebuilt once per setSpec — event handlers do O(1) lookups.
  let beamsById = new Map();
  let bundlesBySource = new Map(); // traced_from -> member ids, chief first

  function indexSpec() {
    beamsById = new Map();
    bundlesBySource = new Map();
    for (const b of (spec && spec.beams) || []) {
      beamsById.set(b.id, b);
      if (b.traced_from) {
        const members = bundlesBySource.get(b.traced_from) || [];
        if (b.ray) members.push(b.id); else members.unshift(b.id); // chief leads
        bundlesBySource.set(b.traced_from, members);
      }
    }
  }

  function entryFor(id) {
    return spec ? (spec.components || []).find((c) => c.id === id) || null : null;
  }
  function isComponentId(id) { return !!entryFor(id); }

  // Carrier components (substrate/table/breadboard) sit under everything: a
  // click that lands on one prefers whatever is drawn ON it; carriers are only
  // selected when nothing else is under the cursor (or via the Outline).
  const BACKGROUND_TYPES = new Set(["ChipSubstrate", "OpticalTable", "Breadboard", "Baseplate"]);
  function isBackgroundId(id) {
    const entry = entryFor(id);
    return !!entry && BACKGROUND_TYPES.has(entry.type);
  }
  function pickGroup(evt) {
    const direct = evt.target.closest("[data-component-id]");
    if (!direct || !isBackgroundId(direct.getAttribute("data-component-id"))) return direct;
    for (const el of document.elementsFromPoint(evt.clientX, evt.clientY)) {
      if (!el.closest) continue;
      const g = el.closest("[data-component-id]");
      if (g && g !== direct && !isBackgroundId(g.getAttribute("data-component-id"))) return g;
    }
    return direct;
  }

  // Traced ray bundles select as ONE unit: clicking any ray resolves to the
  // bundle's chief beam, and the selection halo covers every ray of the fan.
  function beamEntry(id) { return beamsById.get(id) || null; }
  function bundleChiefOf(id) {
    const beam = beamEntry(id);
    if (!beam || !beam.traced_from) return id;
    const members = bundlesBySource.get(beam.traced_from);
    return (members && members[0]) || id;
  }
  function bundleMemberIds(id) {
    const beam = beamEntry(id);
    if (!beam || !beam.traced_from) return [id];
    return bundlesBySource.get(beam.traced_from) || [id];
  }
  function centerOf(entry) {
    const c = entry && entry.center ? entry.center : [0, 0];
    return [Number(c[0]) || 0, Number(c[1]) || 0];
  }
  function angleOf(entry) { return Number(entry && entry.angle) || 0; }

  function svgEl() { return el.querySelector("svg"); }
  // the server-rendered content group — skip our injected grid/ports overlays
  function rootG() { const s = svgEl(); return s ? s.querySelector("g:not(.od-grid):not(.od-ports)") : null; }

  // -- scene-coordinate grid (the snap target, KiCad-style) -----------------
  let gridSize = 10;      // scene units
  let gridVisible = true;
  function setGrid(opts) {
    if (opts && opts.size != null) { const v = Number(opts.size); if (v > 0) gridSize = v; }
    if (opts && opts.visible != null) gridVisible = !!opts.visible;
    drawGrid();
  }
  function drawGrid() {
    const s = svgEl();
    if (!s) return;
    s.querySelectorAll(".od-grid").forEach((n) => n.remove());
    if (!gridVisible || !viewBox || !(gridSize > 0)) return;
    const { x, y, w, h } = viewBox;
    // Adaptive spacing (KLayout-style): coarsen ×5 until the line count is sane,
    // so the grid exists at EVERY zoom instead of vanishing when zoomed out.
    let step = gridSize;
    let guard = 0;
    while (Math.max(w, h) / step > GRID_MAX_LINES && guard++ < 40) step *= 5;
    if (!isFinite(step) || step <= 0) return;
    const g = document.createElementNS(NS, "g");
    g.setAttribute("class", "od-grid");
    g.setAttribute("pointer-events", "none");
    const x1 = x + w, y1 = y + h;
    // integer-indexed loops: float `gx += step` can stall far from the origin
    const ix0 = Math.ceil(x / step), ix1 = Math.floor(x1 / step);
    const iy0 = Math.ceil(y / step), iy1 = Math.floor(y1 / step);
    if (ix1 - ix0 > GRID_MAX_LINES * 2 || iy1 - iy0 > GRID_MAX_LINES * 2) return;
    // two <path> elements instead of hundreds of <line>s — pan/zoom redraws the
    // grid at pointer-event rate, so DOM node count is the cost that matters
    const dMinor = [], dMajor = [];
    for (let i = ix0; i <= ix1; i++) {
      const gx = i * step;
      (i % 5 === 0 ? dMajor : dMinor).push(`M ${gx} ${y} V ${y1}`);
    }
    for (let i = iy0; i <= iy1; i++) {
      const gy = i * step;
      (i % 5 === 0 ? dMajor : dMinor).push(`M ${x} ${gy} H ${x1}`);
    }
    for (const [cls, d] of [["od-grid-minor", dMinor], ["od-grid-major", dMajor]]) {
      if (!d.length) continue;
      const path = document.createElementNS(NS, "path");
      path.setAttribute("class", cls);
      path.setAttribute("fill", "none");
      path.setAttribute("d", d.join(" "));
      g.appendChild(path);
    }
    s.insertBefore(g, rootG() || s.firstChild);
  }

  function parseViewBox(s) {
    const parts = String(s || "").split(/[\s,]+/).map(Number);
    if (parts.length !== 4 || parts.some((v) => !isFinite(v)) || parts[2] <= 0 || parts[3] <= 0) return null;
    const [x, y, w, h] = parts;
    return { x, y, w, h };
  }

  function stageSize() {
    return { sw: el.clientWidth || 800, sh: el.clientHeight || 600 };
  }

  // Scale (px/unit) at which `box` fits the stage with a little breathing room.
  function fitScaleFor(box) {
    const { sw, sh } = stageSize();
    return Math.min(sw / (box.w * 1.12), sh / (box.h * 1.12));
  }
  function fitCamera(box) {
    return { cx: box.x + box.w / 2, cy: box.y + box.h / 2, scale: fitScaleFor(box) };
  }

  function clampScale(scale) {
    const { sw } = stageSize();
    const min = sw / MAX_VIEW_UNITS;
    if (!isFinite(scale) || scale <= 0) return 1;
    return Math.min(Math.max(scale, min), MAX_PX_PER_UNIT);
  }

  // Derive the viewBox from the camera + stage size (aspect always matches the
  // stage, so there is never letterboxing and the grid covers everything).
  function applyCamera() {
    const s = svgEl();
    if (!s || !camera) return;
    if (cameraProvisional && el.clientWidth >= 40 && frameBox) {
      cameraProvisional = false;
      camera = fitCamera(frameBox); // the fake 800×600 fit must not stick
    }
    camera.scale = clampScale(camera.scale);
    if (!isFinite(camera.cx) || !isFinite(camera.cy)) { camera.cx = 0; camera.cy = 0; }
    const { sw, sh } = stageSize();
    const w = sw / camera.scale, h = sh / camera.scale;
    viewBox = { x: camera.cx - w / 2, y: camera.cy - h / 2, w, h };
    s.setAttribute("viewBox", `${viewBox.x} ${viewBox.y} ${viewBox.w} ${viewBox.h}`);
    drawGrid();
    if (onView && frameBox) {
      const pct = (camera.scale / fitScaleFor(frameBox)) * 100;
      onView(pct >= 10 ? Math.round(pct) : Math.max(Math.round(pct * 10) / 10, 0.1));
    }
  }

  function clientToUser(evt, inv) {
    const ctm = inv || rootG().getScreenCTM().inverse();
    const p = new DOMPoint(evt.clientX, evt.clientY).matrixTransform(ctm);
    return { ux: p.x, uy: p.y };
  }

  // Dashed guide showing the scene's nominal export frame (width × height meta).
  // Purely informational — the workspace itself is unbounded.
  function drawFrame() {
    const s = svgEl();
    if (!s || !frameBox) return;
    s.querySelectorAll(".od-frame").forEach((n) => n.remove());
    const rect = document.createElementNS(NS, "rect");
    rect.setAttribute("x", frameBox.x); rect.setAttribute("y", frameBox.y);
    rect.setAttribute("width", frameBox.w); rect.setAttribute("height", frameBox.h);
    rect.setAttribute("class", "od-frame");
    rect.setAttribute("pointer-events", "none");
    s.insertBefore(rect, rootG() || s.firstChild);
  }

  function setSvg(svgText) {
    el.innerHTML = svgText;
    const s = svgEl();
    s.removeAttribute("width");   // the stage sizes the SVG (CSS 100%); the plane is unbounded
    s.removeAttribute("height");
    s.setAttribute("preserveAspectRatio", "xMidYMid slice");
    frameBox = parseViewBox(s.getAttribute("viewBox")) || frameBox || { x: -110, y: -70, w: 220, h: 140 };
    if (!camera) {
      camera = fitCamera(frameBox);  // first render: fit the frame; afterwards the camera persists
      cameraProvisional = el.clientWidth < 40; // stage had no layout: re-fit when it does
    }
    drawFrame();
    applyCamera();
    decorate();
    renderPorts();
    _refreshAnimator();
  }

  function _refreshAnimator() {
    if (svgAnimator) { svgAnimator.destroy(); svgAnimator = null; }
    const s = svgEl();
    if (!s) return;
    if (!animPayloads || !Object.keys(animPayloads).length) {
      // Auto-fetch payloads for the current scene if not yet provided
      fetch("/api/animation/payloads").then(r=>r.json()).then(m=>{
        if (m && Object.keys(m).length) { animPayloads = m; _refreshAnimator(); }
      }).catch(()=>{});
      return;
    }
    svgAnimator = createSvgAnimator(s, animPayloads, { duration: 4.0, fps: 30 });
    svgAnimator.play();
  }

  function setAnimPayloads(map) {
    animPayloads = map || null;
    _refreshAnimator();
  }

  let _resizeRaf = 0;
  window.addEventListener("resize", () => {
    cancelAnimationFrame(_resizeRaf);
    _resizeRaf = requestAnimationFrame(applyCamera);
  });

  // -- selection -----------------------------------------------------------

  function setSpec(nextSpec) { spec = nextSpec; indexSpec(); }

  function notifySelect() { onSelect(selectedIds.slice()); }

  function select(id, additive = false) {
    if (!id) { selectedIds = []; decorate(); notifySelect(); return; }
    if (additive) {
      const i = selectedIds.indexOf(id);
      if (i >= 0) selectedIds.splice(i, 1); else selectedIds.push(id);
    } else {
      selectedIds = [id];
    }
    decorate();
    notifySelect();
  }
  function selectMany(ids, additive = false) {
    selectedIds = additive ? Array.from(new Set([...selectedIds, ...ids])) : ids.slice();
    decorate();
    notifySelect();
  }

  function groupFor(id) {
    const s = svgEl();
    return s ? s.querySelector(`[data-component-id="${CSS.escape(id)}"]`) : null;
  }

  // Does a route/beam (drawn as <path> in the same user space as the marquee)
  // pass through the marquee rect? Sample along the path so long links are only
  // hit when they actually cross the box (not just because their bbox overlaps).
  function linkInMarquee(id, r) {
    const g = groupFor(id);
    if (!g) return false;
    const path = g.querySelector("path");
    if (!path || typeof path.getTotalLength !== "function") return false;
    let len;
    try { len = path.getTotalLength(); } catch (_) { return false; }
    const inside = (x, y) => x >= r.x && x <= r.x + r.w && y >= r.y && y <= r.y + r.h;
    if (!len) {
      try { const b = path.getBBox(); return inside(b.x, b.y); } catch (_) { return false; }
    }
    const steps = Math.max(8, Math.min(80, Math.round(len / 4)));
    for (let i = 0; i <= steps; i++) {
      let pt;
      try { pt = path.getPointAtLength((len * i) / steps); } catch (_) { return false; }
      if (inside(pt.x, pt.y)) return true;
    }
    return false;
  }
  // -- route reshaping (grab a waveguide in route mode and drag it) ---------
  function isRouteId(id) { return !!(spec && (spec.routes || []).some((r) => r.id === id)); }
  function routeSpec(id) { return spec && (spec.routes || []).find((r) => r.id === id); }
  function routePathEl(id) { const g = groupFor(id); return g ? g.querySelector("path") : null; }

  // arc-length fraction (0..1) of the path point nearest to a user-space point
  function nearestFrac(pathEl, userPt) {
    const len = (pathEl && pathEl.getTotalLength) ? pathEl.getTotalLength() : 0;
    if (!len) return 0;
    let bestT = 0, bestD = Infinity;
    const N = 220;
    for (let i = 0; i <= N; i++) {
      const t = (len * i) / N;
      const p = pathEl.getPointAtLength(t);
      const d = (p.x - userPt.ux) ** 2 + (p.y - userPt.uy) ** 2;
      if (d < bestD) { bestD = d; bestT = t; }
    }
    return bestT / len;
  }

  function distToSeg2(p, a, b) {
    const vx = b[0] - a[0], vy = b[1] - a[1];
    const wx = p[0] - a[0], wy = p[1] - a[1];
    const c1 = vx * wx + vy * wy;
    if (c1 <= 0) return wx * wx + wy * wy;
    const c2 = vx * vx + vy * vy;
    if (c2 <= c1) return (p[0] - b[0]) ** 2 + (p[1] - b[1]) ** 2;
    const t = c1 / c2;
    return (p[0] - (a[0] + t * vx)) ** 2 + (p[1] - (a[1] + t * vy)) ** 2;
  }

  function startRouteDrag(id, evt) {
    const pathEl = routePathEl(id);
    if (!pathEl || !pathEl.getTotalLength) return false;
    drag = { mode: "route-edit", id, grabFrac: nearestFrac(pathEl, clientToUser(evt)), moved: false };
    beginDrag(evt);
    return true;
  }

  function showRoutePreview(pts) {
    const s = svgEl();
    if (!s || !pts) return;
    let ghost = s.querySelector(".od-route-preview");
    if (!ghost) {
      ghost = document.createElementNS(NS, "path");
      ghost.setAttribute("class", "od-route-preview od-decoration");
      rootG().appendChild(ghost);
    }
    ghost.setAttribute("d", pts.map((p, k) => `${k ? "L" : "M"} ${p[0]} ${-p[1]}`).join(" "));
  }
  function clearRoutePreview() { (svgEl() ? svgEl().querySelectorAll(".od-route-preview") : []).forEach((n) => n.remove()); }

  // The route's resolved polyline (world coords) parsed from its drawn M/L path.
  function routePolyline(id) {
    const el = routePathEl(id);
    const dstr = el ? el.getAttribute("d") : null;
    if (!dstr) return null;
    const nums = dstr.match(/-?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?/g);
    if (!nums || nums.length < 4) return null;
    const poly = [];
    for (let i = 0; i + 1 < nums.length; i += 2) poly.push([parseFloat(nums[i]), -parseFloat(nums[i + 1])]);
    return poly;
  }

  // KiCad-style trace dragging: the grabbed manhattan segment SLIDES
  // perpendicular to itself; its neighbouring segments stretch to follow;
  // pinned port ends grow a single corner; zero-length and collinear leftovers
  // merge away. The path never accumulates tiny jogs.
  function simplifyPolyline(pts) {
    const out = [];
    for (const p of pts) {
      const prev = out[out.length - 1];
      if (prev && Math.abs(p[0] - prev[0]) < 1e-6 && Math.abs(p[1] - prev[1]) < 1e-6) continue;
      out.push([p[0], p[1]]);
    }
    let merged = true;
    while (merged && out.length > 2) {
      merged = false;
      for (let k = 1; k < out.length - 1; k++) {
        const a = out[k - 1], b = out[k], c = out[k + 1];
        const abH = Math.abs(a[1] - b[1]) < 1e-6, bcH = Math.abs(b[1] - c[1]) < 1e-6;
        const abV = Math.abs(a[0] - b[0]) < 1e-6, bcV = Math.abs(b[0] - c[0]) < 1e-6;
        if ((abH && bcH) || (abV && bcV)) { out.splice(k, 1); merged = true; break; }
      }
    }
    return out;
  }

  // The LOGICAL manhattan backbone of a drawn route: merge axis-aligned runs,
  // collapse fillet-arc samples into the sharp corner where their neighbouring
  // straights intersect. This is what the user thinks of as "the route".
  function routeBackbone(id) {
    const poly = routePolyline(id);
    if (!poly || poly.length < 2) return null;
    const EPS = 1e-3;
    const runs = []; // { axis: "h"|"v", coord, endPt }
    for (let i = 0; i < poly.length - 1; i++) {
      const a = poly[i], b = poly[i + 1];
      const dx = b[0] - a[0], dy = b[1] - a[1];
      if (Math.hypot(dx, dy) < EPS) continue;
      let axis = null;
      if (Math.abs(dy) <= Math.abs(dx) * 0.02 + EPS) axis = "h";
      else if (Math.abs(dx) <= Math.abs(dy) * 0.02 + EPS) axis = "v";
      if (!axis) continue; // fillet arc sample — not a real leg
      const coord = axis === "h" ? (a[1] + b[1]) / 2 : (a[0] + b[0]) / 2;
      const last = runs[runs.length - 1];
      if (last && last.axis === axis && Math.abs(last.coord - coord) < 0.5) {
        last.endPt = b; // same straight leg continuing past an eps wiggle
        continue;
      }
      runs.push({ axis, coord, startPt: a, endPt: b });
    }
    const start = poly[0], end = poly[poly.length - 1];
    // How much of the drawn path the h/v runs actually explain. A "direct"
    // route is one long diagonal — its only runs are the tiny port stubs, and
    // building a manhattan skeleton from those invents geometry that never
    // existed. Treat mostly-unexplained paths like curved ones: the stored
    // corner list IS the logical route.
    let total = 0;
    for (let i = 0; i < poly.length - 1; i++) total += Math.hypot(poly[i + 1][0] - poly[i][0], poly[i + 1][1] - poly[i][1]);
    let covered = 0;
    for (const r of runs) covered += Math.hypot(r.endPt[0] - r.startPt[0], r.endPt[1] - r.startPt[1]);
    if (!runs.length || (total > 1e-6 && covered / total < 0.5)) {
      const rs = routeSpec(id);
      const steps = ((rs && rs.steps) || []).map((s) => [s.x, s.y]);
      return simplifyPolyline([start, ...steps, end]);
    }
    const pts = [start.slice()];
    for (let k = 0; k + 1 < runs.length; k++) {
      const a = runs[k], b = runs[k + 1];
      if (a.axis === "h" && b.axis === "v") pts.push([b.coord, a.coord]);
      else if (a.axis === "v" && b.axis === "h") pts.push([a.coord, b.coord]);
      else if (a.axis === "h") { // H..H at different y (rounded S): midpoint jog
        const xm = (a.endPt[0] + b.startPt[0]) / 2;
        pts.push([xm, a.coord], [xm, b.coord]);
      } else {
        const ym = (a.endPt[1] + b.startPt[1]) / 2;
        pts.push([a.coord, ym], [b.coord, ym]);
      }
    }
    pts.push(end.slice());
    return simplifyPolyline(pts);
  }

  function computeSlide(d, evt) {
    const pathEl = routePathEl(d.id);
    const poly = routeBackbone(d.id);
    if (!pathEl || !poly || poly.length < 2) return null;
    const u = clientToUser(evt);
    const P = [u.ux, -u.uy]; // cursor, world coords
    const len = pathEl.getTotalLength();
    const gp = pathEl.getPointAtLength((d.grabFrac || 0) * len);
    const grab = [gp.x, -gp.y];
    let seg = 0, best = Infinity;
    for (let i = 0; i < poly.length - 1; i++) {
      const dist = distToSeg2(grab, poly[i], poly[i + 1]);
      if (dist < best) { best = dist; seg = i; }
    }
    const A = poly[seg], B = poly[seg + 1];
    const horiz = Math.abs(A[1] - B[1]) < 1e-6;
    const vert = Math.abs(A[0] - B[0]) < 1e-6;
    const pts = poly.map((p) => p.slice());
    let i = seg, j = seg + 1;
    if (!horiz && !vert) {
      // diagonal segment (smooth/free routes): translate it whole, jog both ends
      const dx = P[0] - grab[0], dy = P[1] - grab[1];
      pts.splice(j, 0, [B[0] + dx, B[1] + dy]);
      pts.splice(i + 1, 0, [A[0] + dx, A[1] + dy]);
      return simplifyPolyline(pts);
    }
    if (i === 0) { pts.splice(1, 0, [pts[0][0], pts[0][1]]); i++; j++; } // start is port-pinned
    if (j === pts.length - 1) pts.splice(j, 0, [pts[j][0], pts[j][1]]); // end is port-pinned
    let target = horiz ? P[1] : P[0];
    const grid = snap().grid;
    if (grid) target = Math.round(target / grid) * grid; // slide snaps like moves do
    if (horiz) { pts[i][1] = target; pts[j][1] = target; }
    else { pts[i][0] = target; pts[j][0] = target; }
    return simplifyPolyline(pts);
  }

  function clearDecorations() { el.querySelectorAll(".od-decoration").forEach((n) => n.remove()); }

  function decorate() {
    clearDecorations();
    for (const id of selectedIds) {
      const g = groupFor(id);
      if (!g) continue;
      // Beams and routes select as a HALO hugging their path — a bbox around a
      // long ray is a giant empty rectangle, not a selection. A traced bundle
      // is one unit: the halo covers every ray of the fan.
      if (!isComponentId(id)) {
        for (const memberId of bundleMemberIds(id)) {
          const memberGroup = groupFor(memberId);
          if (!memberGroup) continue;
          const entry = beamEntry(memberId) || ((spec && spec.routes) || []).find((x) => x.id === memberId);
          const width = (entry && Number(entry.width)) || 1.0;
          for (const path of memberGroup.querySelectorAll("path")) {
            const halo = path.cloneNode(false);
            halo.setAttribute("class", "od-select-halo od-decoration");
            halo.setAttribute("stroke-width", String(width + 1.6));
            let under = path;                     // the light sits in a translucent layer: the halo goes under that
            while (under.parentNode !== memberGroup) under = under.parentNode;
            memberGroup.insertBefore(halo, under); // under the ray so its color stays crisp
          }
        }
        continue;
      }
      let box;
      try { box = g.getBBox(); } catch (_) { continue; }
      const rect = document.createElementNS(NS, "rect");
      rect.setAttribute("x", box.x - BOX_PAD);
      rect.setAttribute("y", box.y - BOX_PAD);
      rect.setAttribute("width", box.width + 2 * BOX_PAD);
      rect.setAttribute("height", box.height + 2 * BOX_PAD);
      rect.setAttribute("class", "od-select-box od-decoration");
      g.appendChild(rect);

      // rotate handle only for a single selected component
      if (selectedIds.length === 1 && isComponentId(id)) {
        const cx = box.x + box.width / 2;
        const stem = document.createElementNS(NS, "line");
        stem.setAttribute("x1", cx); stem.setAttribute("y1", box.y - BOX_PAD);
        stem.setAttribute("x2", cx); stem.setAttribute("y2", box.y - BOX_PAD - HANDLE_GAP);
        stem.setAttribute("class", "od-rotate-stem od-decoration");
        g.appendChild(stem);
        const handle = document.createElementNS(NS, "circle");
        handle.setAttribute("cx", cx);
        handle.setAttribute("cy", box.y - BOX_PAD - HANDLE_GAP);
        handle.setAttribute("r", 1.4);
        handle.setAttribute("class", "od-rotate-handle od-decoration");
        handle.dataset.handle = "rotate";
        g.appendChild(handle);

        // an inset: a square at each corner of its box resizes it about its centre
        const pick = entryFor(id).type === "Inset" ? g.querySelector(".od-pick") : null;
        if (pick) {
          const x = Number(pick.getAttribute("x")), y = Number(pick.getAttribute("y"));
          const w = Number(pick.getAttribute("width")), h = Number(pick.getAttribute("height"));
          const size = 8 / camera.scale;                       // 8 px on screen at the zoom it is drawn at
          for (const [px, py, cursor] of [[x, y, "nwse"], [x + w, y, "nesw"], [x, y + h, "nesw"], [x + w, y + h, "nwse"]]) {
            const corner = document.createElementNS(NS, "rect");
            corner.setAttribute("x", px - size / 2); corner.setAttribute("y", py - size / 2);
            corner.setAttribute("width", size); corner.setAttribute("height", size);
            corner.setAttribute("class", "od-resize-handle od-decoration");
            corner.style.cursor = `${cursor}-resize`;
            pick.parentNode.appendChild(corner);
          }
        }
      }
    }
  }

  // Debounced hand-off so traced rays re-fold WHILE an optic is being dragged
  // (same idiom as the cross-section cut: throttle, then a silent re-render).
  let liveTimer = null;
  function liveMove(changes) {
    if (!onLiveMove) return;
    clearTimeout(liveTimer);
    liveTimer = setTimeout(() => onLiveMove(changes, replayDrag), 120);
  }
  // after a live re-render swaps the SVG, put the in-flight drag back on screen
  function replayDrag() {
    if (!drag) return;
    if (drag.mode === "move") for (const m of drag.movers) liveTransform(m.id, m.center, m.angle);
    else if (drag.newAngle !== undefined) liveTransform(drag.id, drag.center, drag.newAngle);
  }

  function liveTransform(id, center, angle) {
    const g = groupFor(id);
    // y-up world -> y-down SVG: flip y AND rotation sign (matches _node_transform)
    if (g) g.setAttribute("transform", `translate(${center[0]},${-center[1]}) rotate(${-angle})`);
  }

  // Dragging snaps the MOVEMENT, not the absolute position: a part keeps
  // whatever sub-grid offset it was placed with (a ring's bus sits 13.6 off its
  // centre, and presets are aligned port to port) while still moving in whole
  // grid steps. Snapping the absolute position instead would shove every
  // carefully aligned part onto the nearest grid line the moment you touched it.
  function snapDelta(base, dx, dy) {
    const grid = snap().grid;
    if (!grid) return [base[0] + dx, base[1] + dy];
    return [base[0] + Math.round(dx / grid) * grid, base[1] + Math.round(dy / grid) * grid];
  }
  // Rotation is FINE by default (1° — beam steering needs precision); hold
  // Shift for coarse detents (the snap angle, e.g. 15° → quick 45/90 folds).
  // With snapping off entirely it's continuous (0.1°).
  function snapAngle(angle, coarse = false) {
    const step = snap().angle;
    if (!step) return Math.round(angle * 10) / 10;
    const eff = coarse ? step : 1;
    return Math.round(angle / eff) * eff;
  }

  // -- ports overlay (connect mode) ----------------------------------------

  function setPorts(map) { portsMap = map || {}; renderPorts(); }
  function setConnectAnchor(key, family) { anchorKey = key; anchorFamily = key ? (family || null) : null; renderPorts(); }
  function setWaypoints(pts) { waypointPts = pts || []; renderPorts(); }

  function renderPorts() {
    const s = svgEl();
    if (!s) return;
    s.querySelectorAll(".od-ports").forEach((n) => n.remove());
    if (mode !== "connect") return;
    const layer = document.createElementNS(NS, "g");
    layer.setAttribute("class", "od-ports");
    for (const [compId, ports] of Object.entries(portsMap)) {
      for (const p of ports) {
        const kind = p.kind || "optical";
        // Optical/fiber ports are round; electrical ports are square so the two
        // families are never confused (and never wired to each other).
        const electrical = kind === "electrical" || kind === "thermal";
        const dot = document.createElementNS(NS, electrical ? "rect" : "circle");
        if (electrical) {
          const sz = 3.0;
          dot.setAttribute("x", p.x - sz / 2);
          dot.setAttribute("y", -p.y - sz / 2);
          dot.setAttribute("width", sz);
          dot.setAttribute("height", sz);
        } else {
          dot.setAttribute("cx", p.x);
          dot.setAttribute("cy", -p.y);
          dot.setAttribute("r", 1.7);
        }
        const key = `${compId}|${p.name}`;
        const fam = electrical ? "electrical" : "optical";
        const dim = anchorFamily && fam !== anchorFamily && key !== anchorKey;
        dot.setAttribute("class", `od-port od-port-${kind}` + (key === anchorKey ? " od-port-anchor" : "") + (dim ? " od-port-dim" : ""));
        dot.dataset.comp = compId;
        dot.dataset.port = p.name;
        dot.dataset.kind = kind;
        dot.setAttribute("tabindex", "0");
        dot.setAttribute("role", "button");
        dot.setAttribute("aria-label", `${compId} ${p.name} ${kind} port`);
        dot.addEventListener("keydown", (evt) => {
          if ((evt.key === "Enter" || evt.key === " ") && onConnectPick) {
            evt.preventDefault();
            onConnectPick({ component: compId, port: p.name, kind });
          }
        });
        const title = document.createElementNS(NS, "title");
        title.textContent = `${p.name} · ${kind}`;
        dot.appendChild(title);
        layer.appendChild(dot);
      }
    }
    for (const [x, y] of waypointPts) {
      const marker = document.createElementNS(NS, "circle");
      marker.setAttribute("cx", x); marker.setAttribute("cy", -y); marker.setAttribute("r", 1.3);
      marker.setAttribute("class", "od-waypoint");
      layer.appendChild(marker);
    }
    (rootG() || s).appendChild(layer);
  }

  function onHover(evt) {
    if (!onCursor) return;
    try {
      const { ux, uy } = clientToUser(evt);
      onCursor(ux, -uy); // svg is y-down; report world coords (y-up)
    } catch { /* no CTM yet */ }
  }

  // -- pointer interaction -------------------------------------------------

  function onPointerDown(evt) {
    // Middle-drag or Space+left-drag pans even when the pointer starts on a part.
    if (evt.button === 1 || (evt.button === 0 && spaceDown)) {
      drag = { mode: "pan", startCam: { ...camera }, inv: rootG().getScreenCTM().inverse() };
      drag.u0 = clientToUser(evt, drag.inv);
      beginDrag(evt);
      return;
    }
    if (evt.button !== 0) return;
    const handle = evt.target.closest(".od-rotate-handle");
    const corner = evt.target.closest(".od-resize-handle");
    const group = pickGroup(evt);

    if (mode === "connect") {
      evt.preventDefault();
      const dot = evt.target.closest(".od-port");
      if (dot) { onConnectPick({ component: dot.dataset.comp, port: dot.dataset.port, kind: dot.dataset.kind }); return; }
      // when not mid-draw, grabbing an existing waveguide reshapes it by dragging
      if (!anchorKey && group && isRouteId(group.getAttribute("data-component-id")) && startRouteDrag(group.getAttribute("data-component-id"), evt)) return;
      const u = clientToUser(evt); onConnectPick(null, { x: u.ux, y: -u.uy });
      return;
    }

    if (corner && selectedIds.length === 1) {
      const pick = corner.parentNode.querySelector(":scope > .od-pick");
      const source = entryFor(selectedIds[0]).source;
      drag = { mode: "resize", id: selectedIds[0], pick, inv: pick.getScreenCTM().inverse(),
               ratio: Number(pick.getAttribute("height")) / Number(pick.getAttribute("width")),
               free: !source || FREE_SHAPES.has(source.kind) };
      beginDrag(evt);
      return;
    }

    if (handle && selectedIds.length === 1) {
      const entry = entryFor(selectedIds[0]);
      const center = centerOf(entry);
      drag = { mode: "rotate", id: selectedIds[0], center, angle: angleOf(entry), cux: center[0], cuy: -center[1] };
      beginDrag(evt);
      return;
    }

    if (group) {
      const id = bundleChiefOf(group.getAttribute("data-component-id")); // any ray → its bundle
      if (evt.shiftKey) { select(id, true); return; } // toggle, no drag
      if (!selectedIds.includes(id)) select(id); // click unselected -> replace selection
      // routes reshape by dragging in ANY mode (KiCad-style segment slide)
      if (isRouteId(id) && startRouteDrag(id, evt)) return;
      // drag moves the whole (movable) selection together
      const movers = selectedIds.filter(isComponentId).map((cid) => ({
        id: cid, base: centerOf(entryFor(cid)), angle: angleOf(entryFor(cid)),
      }));
      if (movers.length) { drag = { mode: "move", movers, u0: clientToUser(evt) }; beginDrag(evt); }
      return;
    }

    // empty space
    if (spaceDown) {
      drag = { mode: "pan", startCam: { ...camera }, inv: rootG().getScreenCTM().inverse() };
      drag.u0 = clientToUser(evt, drag.inv);
    } else {
      const u = clientToUser(evt);
      drag = { mode: "marquee", start: u, additive: evt.shiftKey };
    }
    beginDrag(evt);
  }

  function beginDrag(evt) {
    evt.preventDefault();
    try { el.setPointerCapture(evt.pointerId); } catch (_) { /* pointer already canceled */ }
    window.addEventListener("pointermove", onPointerMove);
    window.addEventListener("pointerup", onPointerUp, { once: true });
    window.addEventListener("pointercancel", onPointerUp, { once: true });
  }

  function marqueeRect(a, b) {
    return { x: Math.min(a.ux, b.ux), y: Math.min(a.uy, b.uy),
             w: Math.abs(a.ux - b.ux), h: Math.abs(a.uy - b.uy) };
  }

  function onPointerMove(evt) {
    if (!drag) return;
    if (drag.mode === "pan") {
      const u = clientToUser(evt, drag.inv);
      camera.cx = drag.startCam.cx - (u.ux - drag.u0.ux);
      camera.cy = drag.startCam.cy - (u.uy - drag.u0.uy);
      drag.panned = true; applyCamera();
      return;
    }
    if (drag.mode === "marquee") {
      const r = marqueeRect(drag.start, clientToUser(evt));
      let box = svgEl().querySelector(".od-marquee");
      if (!box) { box = document.createElementNS(NS, "rect"); box.setAttribute("class", "od-marquee od-decoration"); rootG().appendChild(box); }
      box.setAttribute("x", r.x); box.setAttribute("y", r.y);
      box.setAttribute("width", r.w); box.setAttribute("height", r.h);
      drag.moved = true;
      return;
    }
    if (drag.mode === "route-edit") {
      drag.moved = true;
      drag.slide = computeSlide(drag, evt);
      if (drag.slide) showRoutePreview(drag.slide); // live KiCad-style preview
      return;
    }
    const u = clientToUser(evt);
    if (drag.mode === "move") {
      const dx = u.ux - drag.u0.ux, dy = u.uy - drag.u0.uy;
      drag.moved = true;
      for (const m of drag.movers) {
        m.center = snapDelta(m.base, dx, -dy);
        liveTransform(m.id, m.center, m.angle);
      }
      liveMove(drag.movers.map((m) => ({ id: m.id, center: m.center })));
    } else if (drag.mode === "resize") {
      // the centre stays: the corner under the pointer sets the half width, and the half height of a free shape
      const p = new DOMPoint(evt.clientX, evt.clientY).matrixTransform(drag.inv);
      drag.width = Math.max(1, Math.round(Math.abs(p.x) * 20) / 10);
      drag.height = drag.free ? Math.max(1, Math.round(Math.abs(p.y) * 20) / 10) : drag.width * drag.ratio;
      let box = drag.pick.parentNode.querySelector(":scope > .od-resize-preview");
      if (!box) {
        box = document.createElementNS(NS, "rect");
        box.setAttribute("class", "od-select-box od-resize-preview od-decoration");
        drag.pick.parentNode.appendChild(box);
      }
      box.setAttribute("x", -drag.width / 2); box.setAttribute("y", -drag.height / 2);
      box.setAttribute("width", drag.width); box.setAttribute("height", drag.height);
    } else { // rotate
      // handle sits at the component's local "up"; solve for the world angle under
      // the y-down render transform translate(cx,-cy) rotate(-angle)
      const deg = (Math.atan2(drag.cux - u.ux, drag.cuy - u.uy) * 180) / Math.PI;
      drag.newAngle = snapAngle(Math.round(deg * 10) / 10, evt.shiftKey);
      liveTransform(drag.id, drag.center, drag.newAngle);
      liveMove([{ id: drag.id, angle: drag.newAngle }]);
    }
  }

  function onPointerUp(evt) {
    clearTimeout(liveTimer);  // the commit below supersedes any pending live tick
    window.removeEventListener("pointermove", onPointerMove);
    window.removeEventListener("pointerup", onPointerUp);
    window.removeEventListener("pointercancel", onPointerUp);
    if (el.hasPointerCapture?.(evt.pointerId)) el.releasePointerCapture(evt.pointerId);
    if (!drag) return;
    const d = drag;
    drag = null;
    if (d.mode === "pan") return;
    if (d.mode === "route-edit") {
      clearRoutePreview();
      if (d.moved && d.slide && onRouteEdit) {
        const rs = routeSpec(d.id);
        if (rs && rs.from && rs.to) onRouteEdit(d.id, { waypoints: d.slide.slice(1, -1) });
        else if (rs) onRouteEdit(d.id, { points: d.slide });
      }
      return;
    }
    if (d.mode === "marquee") {
      svgEl().querySelectorAll(".od-marquee").forEach((n) => n.remove());
      if (!d.moved) { if (!evt.shiftKey) select(null); return; } // clean click -> deselect
      const r = marqueeRect(d.start, clientToUser(evt));
      const compHits = (spec.components || [])
        .filter((c) => !BACKGROUND_TYPES.has(c.type)) // carriers: click or Outline only
        .filter((c) => {
          const g = groupFor(c.id);
          const box = g && groupWorldBox(g);
          if (box) {
            return box.x1 >= r.x && box.x0 <= r.x + r.w &&
                   box.y1 >= r.y && box.y0 <= r.y + r.h;
          }
          const [cx, cy] = centerOf(c); const ux = cx, uy = -cy;
          return ux >= r.x && ux <= r.x + r.w && uy >= r.y && uy <= r.y + r.h;
        })
        .map((c) => c.id);
      // routes + beams are polylines, not centered components — hit-test their
      // geometry; traced rays collapse to their bundle's chief (one unit)
      const linkHits = Array.from(new Set(
        [...(spec.routes || []), ...(spec.beams || [])]
          .filter((lk) => lk && lk.id && linkInMarquee(lk.id, r))
          .map((lk) => bundleChiefOf(lk.id)),
      ));
      selectMany([...compHits, ...linkHits], d.additive);
      return;
    }
    if (d.mode === "move") {
      if (d.moved) onCommit(d.movers.map((m) => ({ id: m.id, center: m.center })));
    } else if (d.mode === "rotate") {
      if (d.newAngle !== undefined) onCommit([{ id: d.id, angle: d.newAngle }]);
    } else if (d.mode === "resize" && d.width !== undefined) {
      decorate();                                   // the preview goes; the new drawing comes with the answer
      onResize(d.id, d.free ? { width: d.width, height: d.height } : { width: d.width });
    }
  }

  // -- zoom ----------------------------------------------------------------

  // factor > 1 zooms out (more units on screen); the anchor point stays put.
  function zoomAt(factor, ux, uy) {
    if (!camera) return;
    const next = clampScale(camera.scale / factor);
    if (next === camera.scale) return;
    camera.cx = ux - (ux - camera.cx) * (camera.scale / next);
    camera.cy = uy - (uy - camera.cy) * (camera.scale / next);
    camera.scale = next;
    applyCamera();
  }
  function onWheel(evt) {
    if (!camera) return;
    evt.preventDefault();
    const { ux, uy } = clientToUser(evt);
    zoomAt(evt.deltaY > 0 ? ZOOM_STEP : 1 / ZOOM_STEP, ux, uy);
  }
  function zoomButton(into) {
    if (!camera) return;
    zoomAt(into ? 1 / ZOOM_STEP : ZOOM_STEP, camera.cx, camera.cy);
  }
  function resetView() {
    if (!frameBox) return;
    camera = fitCamera(frameBox);
    applyCamera();
  }

  // Fit the view to the content that matters: the REAL rendered extents of
  // components and routes (transform-mapped group bboxes, so large GDS dies and
  // tables are fully visible) plus beam interaction points — excluding traced
  // exit tails, which run far past the scene toward "infinity".
  function groupWorldBox(g) {
    let bb;
    try { bb = g.getBBox(); } catch (_) { return null; }
    if (!bb || (bb.width < 1e-6 && bb.height < 1e-6)) return null;
    const consolidated = g.transform && g.transform.baseVal.consolidate();
    const corners = [
      [bb.x, bb.y], [bb.x + bb.width, bb.y],
      [bb.x, bb.y + bb.height], [bb.x + bb.width, bb.y + bb.height],
    ];
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    for (const [cx, cy] of corners) {
      const wx = consolidated ? consolidated.matrix.a * cx + consolidated.matrix.c * cy + consolidated.matrix.e : cx;
      const wy = consolidated ? consolidated.matrix.b * cx + consolidated.matrix.d * cy + consolidated.matrix.f : cy;
      x0 = Math.min(x0, wx); y0 = Math.min(y0, wy);
      x1 = Math.max(x1, wx); y1 = Math.max(y1, wy);
    }
    return { x0, y0, x1, y1 };
  }

  function contentBox() {
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    const take = (x, y) => {
      if (!isFinite(x) || !isFinite(y)) return;
      minX = Math.min(minX, x); maxX = Math.max(maxX, x);
      minY = Math.min(minY, y); maxY = Math.max(maxY, y);
    };
    for (const c of (spec && spec.components) || []) {
      const g = groupFor(c.id);
      const box = g && groupWorldBox(g);
      if (box) { take(box.x0, box.y0); take(box.x1, box.y1); continue; }
      const [x, y] = centerOf(c);
      take(x - 20, -y - 20); take(x + 20, -y + 20); // no drawn group: pad the center
    }
    for (const r of (spec && spec.routes) || []) {
      const g = groupFor(r.id);
      const box = g && groupWorldBox(g); // routes draw in root coords (identity)
      if (box) { take(box.x0, box.y0); take(box.x1, box.y1); }
    }
    for (const b of (spec && spec.beams) || []) {
      const path = b.path || [];
      const pts = b.traced_from && path.length > 1 ? path.slice(0, -1) : path; // drop the exit tail
      for (const p of pts) {
        if (Array.isArray(p) && typeof p[0] === "number" && typeof p[1] === "number") take(p[0], -p[1]);
      }
    }
    if (!isFinite(minX)) return null;
    return { x: minX, y: minY, w: Math.max(maxX - minX, 1), h: Math.max(maxY - minY, 1) };
  }

  function fit() {
    let box = spec ? contentBox() : null;
    if (!box) {
      const g = rootG(); // spec-less fallback (e.g. bare GDS render)
      try { const bb = g && g.getBBox(); if (bb && bb.width > 1e-6) box = { x: bb.x, y: bb.y, w: bb.width, h: bb.height }; } catch (_) { /* empty */ }
    }
    if (!box) { resetView(); return; }
    camera = fitCamera(box);
    applyCamera();
  }

  // space toggles pan vs marquee on empty drag
  window.addEventListener("keydown", (e) => {
    if (e.code === "Space" && !isTyping(e)) { spaceDown = true; el.style.cursor = "grab"; }
  });
  window.addEventListener("keyup", (e) => {
    if (e.code === "Space") { spaceDown = false; el.style.cursor = ""; }
  });
  function isTyping(e) {
    const t = (e.target && e.target.tagName) || "";
    return t === "INPUT" || t === "TEXTAREA" || t === "SELECT";
  }

  el.addEventListener("pointerdown", onPointerDown);
  el.addEventListener("pointermove", onHover);
  el.addEventListener("pointerleave", () => { if (onCursor) onCursor(null, null); });
  // double-click on a part opens it (a scene inset opens its scene); on empty canvas in connect mode it
  // finishes the free route here
  el.addEventListener("dblclick", (evt) => {
    if (mode !== "connect") {
      // the drag's pointer capture makes the canvas the target: take the part under the pointer
      const at = document.elementFromPoint(evt.clientX, evt.clientY);
      const group = at && pickGroup({ target: at, clientX: evt.clientX, clientY: evt.clientY });
      if (group && onOpen) onOpen(group.getAttribute("data-component-id"));
      return;
    }
    if (!onConnectPick || evt.target.closest(".od-port")) return;
    evt.preventDefault();
    const u = clientToUser(evt);
    onConnectPick(null, { x: u.ux, y: -u.uy }, true);
  });
  el.addEventListener("wheel", onWheel, { passive: false });

  return {
    setSvg,
    setSpec,
    setAnimPayloads,
    showFreePreview: (pts) => { if (pts && pts.length) showRoutePreview(pts); else clearRoutePreview(); },
    select,
    selectMany,
    setMode: (m) => { mode = m === "connect" ? "connect" : "select"; anchorKey = null; anchorFamily = null; waypointPts = []; renderPorts(); },
    setPorts,
    setConnectAnchor,
    setWaypoints,
    setGrid,
    zoomIn: () => zoomButton(true),
    zoomOut: () => zoomButton(false),
    resetView,
    fit,
    // the middle of what the canvas shows, in world units (y up): where a new inset goes
    viewCenter: () => (camera ? [camera.cx, -camera.cy] : null),
    // real drawn extents in svg-user coords (y-down) — align/fit helpers
    worldBoxFor: (id) => { const g = groupFor(id); return g ? groupWorldBox(g) : null; },
    get selectedId() { return selectedIds[0] || null; },
    get selectedIds() { return selectedIds.slice(); },
  };
}
