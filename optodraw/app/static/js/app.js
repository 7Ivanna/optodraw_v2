// Editor bootstrap: wires palette, canvas, properties, toolbar, history, 3D view.

import { api, changeHeaders, setLevel, setWorkspace } from "./api.js";
import { FIGURE_ENTRIES, HIDDEN_CATEGORIES, HIDDEN_COMPONENTS, createPalette, fitSvgToContent, humanizeName } from "./palette.js";
import { installPartsControls } from "./parts.js";
import { createCommandPalette } from "./cmdk.js";
import { createCanvas } from "./canvas.js";
import { createCodeTab } from "./code_tab.js";
import { createLayoutView } from "./layout_view.js";
import { createProperties, numbers, points } from "./properties.js";
import { createWavelengthPicker, wavelengthHex } from "./wavelength.js";
import { initTooltips } from "./tooltip.js";
import { dialogPrompt, dialogConfirm, dialogForm, openModal } from "./dialog.js";

initTooltips();

// Wavelength (nm) applied to new free-space beams; drives their color.
let activeWavelength = 633;

const DEFAULT_GRID = 10; // scene units — the snap + visible grid spacing
const SNAP_ANGLE = 15; // degrees

// Routing types exposed in the Route dropdown — these map to optodraw's
// beam (free-space) and route (on-chip) primitives + path styles.
const ROUTING_TYPES = [
  { id: "beam", label: "Beam (free-space)", mode: "beam" },
  { id: "wg", label: "Waveguide (smooth S-bend)", mode: "route", kind: "waveguide", path_type: "smooth", smooth: true },
  { id: "wg_manhattan", label: "Waveguide (manhattan, rounded)", mode: "route", kind: "waveguide", path_type: "manhattan", smooth: true },
  { id: "wg_direct", label: "Waveguide (direct)", mode: "route", kind: "waveguide", path_type: "straight", smooth: true },
  { id: "fiber", label: "Fiber", mode: "route", kind: "fiber", path_type: "smooth", smooth: true },
  { id: "electrical", label: "Electrical", mode: "route", kind: "electrical", path_type: "manhattan" },
];

// Metal electrical traces are drawn much wider than optical waveguides.
const ELECTRICAL_TRACE_WIDTH = 5.0;

const els = {
  paletteList: document.getElementById("palette-list"),
  paletteSearch: document.getElementById("palette-search"),
  canvas: document.getElementById("canvas"),
  view3d: document.getElementById("view3d"),
  viewLayout: document.getElementById("view-layout"),
  propsForm: document.getElementById("props-form"),
  propsEmpty: document.getElementById("props-empty"),
  tabInspector: document.getElementById("tab-inspector"),
  tabOutline: document.getElementById("tab-outline"),
  tabCode: document.getElementById("tab-code"),
  paneInspector: document.getElementById("pane-inspector"),
  paneOutline: document.getElementById("pane-outline"),
  paneCode: document.getElementById("pane-code"),
  insetPath: document.getElementById("inset-path"),
  outlineList: document.getElementById("outline-list"),
  outlineSearch: document.getElementById("outline-search"),
  outlineCount: document.getElementById("outline-count"),
  status: document.getElementById("status"),
  undo: document.getElementById("btn-undo"),
  redo: document.getElementById("btn-redo"),
  contextActions: document.getElementById("context-actions"),
  snap: document.getElementById("btn-snap"),
  grid: document.getElementById("btn-grid"),
  gridSize: document.getElementById("grid-size"),
  connect: document.getElementById("btn-connect"),
  routeMenuBtn: document.getElementById("btn-route-menu"),
  routeMenu: document.getElementById("route-menu"),
  exportBtn: document.getElementById("btn-export"),
  exportMenu: document.getElementById("export-menu"),
  helpBtn: document.getElementById("btn-help"),
  helpMenu: document.getElementById("help-menu"),
  routeLabel: document.getElementById("route-label"),
  selInfo: document.getElementById("sel-info"),
  zoomLevel: document.getElementById("zoom-level"),
  workspaceBtn: document.getElementById("btn-workspace"),
  workspaceMenu: document.getElementById("ws-menu"),
  wsName: document.getElementById("ws-name"),
  wsSaved: document.getElementById("ws-saved"),
};

const describeCache = new Map();
let currentSpec = null;
let snapOn = true;          // snap-to-grid on by default (KiCad-style alignment)
let gridSize = DEFAULT_GRID; // scene units; drives both the visible grid and snapping
let gridVisible = true;
const snapStep = () => (snapOn ? gridSize : 0);
let materials = [];
let connectMode = false;
let connectAnchor = null;
let freePts = []; // free click-to-click route in progress (no ports)
let routingType = ROUTING_TYPES[0];
let routingTypePicked = false;  // true once the user chooses from Route ▾
let waypoints = [];

// Port families that may be wired together: optical light paths vs electrical/RF.
function portFamily(kind) {
  return (kind === "electrical" || kind === "thermal") ? "electrical" : "optical";
}

const routingTypeById = (id) => ROUTING_TYPES.find((t) => t.id === id) || ROUTING_TYPES[0];

// What kind of link belongs between these two ports. Light in a waveguide is not
// a free-space beam, and the Route tool used to draw a beam between two chip
// ports because "Beam" happened to be first in the list. The ports know which
// they are: free_space on a bench optic, optical on a chip.
function linkTypeFor(...kinds) {
  if (routingTypePicked) return routingType;
  const known = kinds.filter(Boolean);
  if (!known.length) return routingType;
  if (known.every((k) => k === "free_space")) return routingTypeById("beam");
  if (known.every((k) => k === "optical")) return routingTypeById("wg_manhattan");
  return routingTypeById("fiber");  // bench to chip: that hop is a fibre
}

// scene-spec history (undo/redo): the spec is the single source of truth.
const history = [];
let historyIndex = -1;
const clone = (obj) => JSON.parse(JSON.stringify(obj));

function setStatus(msg, isError = false) {
  els.status.textContent = msg;
  els.status.style.color = isError ? "var(--danger)" : "var(--text-3)";
  if (msg && !isError) {
    setTimeout(() => { if (els.status.textContent === msg) els.status.textContent = ""; }, 2500);
  }
}

async function withStatus(label, fn) {
  try {
    setStatus(`${label}…`);
    const result = await fn();
    setStatus("");
    return result;
  } catch (err) {
    setStatus(err.message || String(err), true);
    throw err;
  }
}

// -- modules ---------------------------------------------------------------

let pdkList = []; // built-in PDK names, loaded once at boot
let stackList = []; // bundled foundry stacks (z + thickness), loaded at boot

const properties = createProperties({
  formEl: els.propsForm,
  emptyEl: els.propsEmpty,
  onChange: (id, params) => withStatus("Updating", async () => {
    // Re-render the scene but DON'T rebuild the inspector form (keeps focus/cursor
    // while editing live). selInfo/buttons don't change for a property edit.
    commit(await api.update(id, params));
  }),
  onDelete: () => deleteSelected(),
  onAlign: (how) => alignSelected(how),
  onDistribute: (axis) => distributeSelected(axis),
  onRotate: (deg) => rotateSelected(deg),
  onFlip: (axis) => flipSelected(axis),
  onDuplicate: () => duplicateSelected(),
  onCrossSection: (id, opts) => renderCrossSection(id, opts),
  onAttachTech: (id, kind) => { techTargetId = id; document.getElementById(kind === "folder" ? "folder-tech" : "file-tech").click(); },
  onApplyPdk: (id, name) => withStatus(`Applying ${name} PDK`, async () => {
    const payload = await api.applyPdk(id, name);
    commit(payload);
    canvas.select(id); // refresh inspector with PDK colors/stack
    setStatus(`Applied ${payload.applied} PDK layer(s)`);
  }),
  getPdks: () => pdkList,
  onApplyStack: (id, name) => withStatus("Applying stack", async () => {
    const payload = await api.applyStack(id, name);
    commit(payload);
    canvas.select(id); // refresh inspector with z + thickness
    setStatus(`Applied ${payload.applied} stack layer(s)`);
  }),
  getStacks: () => stackList,
  onResetLayers: (id) => withStatus("Resetting layers", async () => {
    commit(await api.resetGdsLayers(id));
    canvas.select(id);
    setStatus("Layer overrides cleared");
  }),
  onInsetSource: (id, change, refresh) => setInsetSource(id, change, refresh),
  onInsetFile: (id, key) => pickFigureFile(FIGURE_ENTRIES.find((f) => f.accept && f.kind === entryFor(id)?.source?.kind)?.accept)
    .then((path) => setInsetSource(id, { [key]: path }, true)).catch(() => {}),
  onInsetSize: (id, size) => resizeInset(id, size),
});

// Status-bar cursor telemetry (rAF-throttled so hover never floods layout).
let cursorXY = null;
let cursorRaf = 0;
function paintCursorPos() {
  cursorRaf = 0;
  const el = document.getElementById("sb-cursor");
  if (!el) return;
  if (!cursorXY) { el.textContent = ""; return; }
  const fmt = (v) => {
    const s = Math.abs(v) >= 1000 ? v.toFixed(0) : v.toFixed(1);
    return s === "-0.0" || s === "-0" ? s.slice(1) : s;
  };
  el.textContent = `x ${fmt(cursorXY[0])}  y ${fmt(cursorXY[1])}`;
}
function syncSnapChip() {
  const chip = document.getElementById("sb-snap");
  if (!chip) return;
  chip.textContent = snapOn ? `Snap ${gridSize}` : "Snap off";
  chip.classList.toggle("on", snapOn);
}

const canvas = createCanvas({
  el: els.canvas,
  getSnap: () => (snapOn ? { grid: gridSize, angle: SNAP_ANGLE } : { grid: 0, angle: 0 }),
  onView: (pct) => { els.zoomLevel.dataset.pct = pct; if (els.view3d.hidden) els.zoomLevel.textContent = `${pct}%`; },
  onCursor: (x, y) => {
    cursorXY = x == null ? null : [x, y];
    if (!cursorRaf) cursorRaf = requestAnimationFrame(paintCursorPos);
  },
  onSelect: (ids) => onSelectionChange(ids),
  onOpen: (id) => { if (entryFor(id)?.type === "Inset") openInset(id); },
  onResize: (id, size) => resizeInset(id, size).then(() => canvas.select(id), () => {}),
  onCommit: (changes) => applySpec("Move", (next) => applyMoveChanges(next, changes),
    { reselect: canvas.selectedIds }),
  // Traced rays follow the optic WHILE it is dragged, not just on drop. Only
  // worth a round trip when the scene actually has live rays; one request at a
  // time, and no undo entry (the commit on pointerup is the undoable step).
  onLiveMove: async (changes, replayDrag) => {
    if (liveMoveBusy || !(currentSpec?.beams || []).some((b) => b.traced_from)) return;
    liveMoveBusy = true;
    try {
      const next = clone(currentSpec);
      applyMoveChanges(next, changes);
      applyPayload(await api.setScene(next, true));  // no history entry: pointerup commits
      replayDrag();  // the SVG was swapped under the drag — put the drag back
    } catch { /* a dropped live tick is harmless — pointerup re-syncs */ }
    finally { liveMoveBusy = false; }
  },
  onConnectPick: (pick, worldPoint, finish) => {
    if (!pick) {
      // empty click: waypoint if a port route is in progress; otherwise it
      // starts/extends a FREE route (how port-less parts get wired)
      if (connectAnchor && worldPoint) {
        waypoints.push([worldPoint.x, worldPoint.y]);
        canvas.setWaypoints(waypoints);
        setStatus(`Waypoint added (${waypoints.length})`);
        return;
      }
      if (!worldPoint) return;
      const freeType = linkTypeFor(connectAnchor && connectAnchor.kind);
      if (freeType.mode === "beam") {
        setStatus("Free routes need a waveguide / fiber / electrical type (pick one from Route ▾)", true);
        return;
      }
      if (finish) {
        const pts = [...freePts, [worldPoint.x, worldPoint.y]]
          .filter((p, i, a) => !i || Math.hypot(p[0] - a[i - 1][0], p[1] - a[i - 1][1]) > 1e-6);
        freePts = [];
        canvas.showFreePreview(null);
        if (pts.length < 2) { setStatus("Free route needs at least two points", true); return; }
        withStatus("Routing", async () => {
          commit(await api.addFreeRoute(pts, {
            kind: freeType.kind,
            path_type: "manual",
            smooth: !!freeType.smooth,
          }));
        });
        return;
      }
      freePts.push([worldPoint.x, worldPoint.y]);
      canvas.showFreePreview(freePts);
      setStatus(`Free route: ${freePts.length} point${freePts.length > 1 ? "s" : ""} — double-click to finish, Esc to cancel`);
      return;
    }
    const key = `${pick.component}|${pick.port}`;
    if (!connectAnchor) {
      connectAnchor = pick;
      waypoints = [];
      canvas.setConnectAnchor(key, portFamily(pick.kind));
      canvas.setWaypoints(waypoints);
      const fam = portFamily(pick.kind);
      const article = /^[aeiou]/i.test(fam) ? "an" : "a";
      setStatus(`Route from ${pick.component}.${pick.port} (${fam}) — click waypoints or ${article} ${fam} target port`);
      return;
    }
    if (key === `${connectAnchor.component}|${connectAnchor.port}`) return;
    const a = connectAnchor;
    const b = pick;
    // Optical and electrical ports are different physical domains — never wire one to
    // the other (the source of the "random connections" on the MZM electrodes).
    if (portFamily(a.kind) !== portFamily(b.kind)) {
      setStatus(`Can't connect a ${portFamily(a.kind)} port to a ${portFamily(b.kind)} port`, true);
      return;
    }
    const electrical = portFamily(a.kind) === "electrical";
    const linkType = linkTypeFor(a.kind, b.kind);
    const wpts = waypoints.slice();
    withStatus("Routing", async () => {
      let payload;
      if (linkType.mode === "beam" && !electrical) {
        const path = [[a.component, a.port], ...wpts, [b.component, b.port]];
        payload = await api.addBeam(path, activeWavelength);
      } else {
        payload = await api.addRoute([a.component, a.port], [b.component, b.port], {
          kind: electrical ? "electrical" : (linkType.kind === "electrical" ? "waveguide" : linkType.kind),
          path_type: linkType.path_type,
          smooth: electrical ? false : !!linkType.smooth,
          // electrical traces are metal — draw them as a chunky trace, not a hairline
          width: electrical ? ELECTRICAL_TRACE_WIDTH : undefined,
          waypoints: wpts,
        });
      }
      commit(payload);
      connectAnchor = null;
      waypoints = [];
      canvas.setConnectAnchor(null);
      canvas.setWaypoints([]);
      await refreshPorts(); // positions may shift after re-render
      setStatus(`Routed ${a.component}.${a.port} → ${b.component}.${b.port}`);
    });
  },
  // drag-to-reroute: a route was grabbed and dragged to a new shape
  onRouteEdit: (id, body) => {
    withStatus("Rerouting", async () => {
      const payload = await api.updateRoute(id, body);
      commit(payload);
      await refreshPorts();
      setStatus("Waveguide reshaped");
    });
  },
});

window.__odCanvas = canvas; // dev/test handle

// One-time nudge: placing on-chip parts without a substrate leaves the 3D die
// auto-fitted; recommend an explicit ChipSubstrate before designing.
let substrateHintShown = false;
function maybeSubstrateHint(name) {
  if (substrateHintShown || name === "ChipSubstrate") return;
  if ((catalogCache?.[name]?.category) !== "on_chip") return;
  if ((currentSpec?.components || []).some((c) => c.type === "ChipSubstrate")) return;
  substrateHintShown = true;
  setStatus("Tip: place a Chip Substrate first to define the die — otherwise the 3D die auto-fits around your components");
}

// Shared by the palette cards and the ⌘K command palette.
function paletteAdd(name) {
  // Models need a source file, so adding one opens a file picker instead of
  // dropping an empty component.
  if (name === "GDSModel") { document.getElementById("file-gds").click(); return; }
  if (name === "CustomModel") { document.getElementById("file-model").click(); return; }
  withStatus(`Adding ${name}`, async () => {
    // the backend puts it where you look, in a free spot: in 3D, the point the camera orbits (its x, -z on the table)
    const target3d = !els.view3d.hidden && cameraState && Array.isArray(cameraState.target) ? cameraState.target : null;
    const middle = target3d ? [target3d[0], -target3d[2]] : canvas.viewCenter();
    // the snap grid goes too, so the free spot is already on it and the snap below cannot move it onto a part
    const where = middle ? { near: middle } : {};
    if (snapOn) where.grid = gridSize;
    const payload = await api.create(name, where);
    commit(payload);
    // snap the freshly-placed component onto the grid so it lands aligned
    if (snapOn && payload.id) {
      await applySpec("Place", (next) => {
        const e = next.components.find((c) => c.id === payload.id);
        if (e) { const c = ctr(e); e.center = [Math.round(c[0] / gridSize) * gridSize, Math.round(c[1] / gridSize) * gridSize]; }
      }, { reselect: [payload.id] });
    } else {
      canvas.select(payload.id); // triggers onSelectionChange -> inspector
    }
    maybeSubstrateHint(name);
  });
}

// The Figure palette: an inset of each kind the editor makes, built once on the server. A kind with a file asks for
// it first; a GDS view asks for its stack and region; a section or a 3D view is made from the selected inset, beside it.
async function addFigure(f) {
  const source = f.copy ? { scene: currentSpec } : {};
  const middle = canvas.viewCenter();
  const body = { kind: f.kind, source, ...(middle ? { center: middle } : {}) };   // where the person looks
  if (f.of) {
    const parent = canvas.selectedIds.length === 1 ? entryFor(canvas.selectedIds[0]) : null;
    if (parent?.type !== "Inset" || !f.of.includes(parent.source?.kind)) {
      const from = f.of.map((kind) => FIGURE_ENTRIES.find((e) => e.kind === kind).label).join(" or a ");
      setStatus(`Select a ${from} first: the ${f.label} is made from it`, true);
      return;
    }
    const [x, y] = ctr(parent);
    Object.assign(body, { of: parent.id, center: [x + (Number(parent.width) || 50) / 2 + 30, y] });
    if (f.kind === "SectionView") {
      const [x0, y0, x1, y1] = parent.source.region;           // a cut across the middle of the view, 10% in
      const cut = [(x0 + x1) / 2, y0 + (y1 - y0) / 10, (x0 + x1) / 2, y1 - (y1 - y0) / 10];
      const asked = await dialogForm({ title: "Section of the GDS view", confirmText: "Cut", fields: [{
        key: "cut", label: "Cut from x1, y1 to x2, y2 (µm in the GDS file)", type: "text", required: true,
        value: cut.map((v) => Math.round(v * 1000) / 1000).join(", ") }] });
      if (!asked) return;
      source.cut = points(asked.cut);
    }
  }
  if (f.accept) source.path = await pickFigureFile(f.accept);
  if (f.kind === "GdsView") {
    const asked = await dialogForm({ title: "GDS view", confirmText: "Make", fields: [
      { key: "stack", label: "Layer stack", type: "select", value: "gdsfactory_generic",
        options: stackList.map((stack) => ({ value: stack.id, label: stack.label })) },
      { key: "region", label: "Region x0, y0, x1, y1 (µm in the GDS file)", type: "text", required: true,
        placeholder: "-10, -10, 10, 10" }] });
    if (!asked) return;
    Object.assign(source, { stack: asked.stack, region: numbers(asked.region) });
  }
  await withStatus(`Adding ${f.label}`, async () => {
    const payload = await api.makeInset(body);
    commit(payload);
    canvas.select(payload.id);
  });
}

// A file for an inset: picked, then kept in the workspace's files folder; it resolves to its path there. A picker
// closed with no file leaves it pending, so nothing is made.
const figureFile = document.getElementById("file-figure");
function pickFigureFile(accept = "") {
  return new Promise((resolve) => {
    figureFile.accept = accept;
    figureFile.onchange = () => {
      const file = figureFile.files[0];
      figureFile.value = "";
      if (file) resolve(withStatus(`Keeping ${file.name}`, async () => (await api.keepFile(file)).path));
    };
    figureFile.click();
  });
}

// A change of an inset's source builds it once; Rebuild sends none. `refresh` draws the Inspector again, for its notes.
function setInsetSource(id, change, refresh = false) {
  return withStatus("Building the inset", async () => {
    commit(await api.insetSource(id, change));
    if (refresh) canvas.select(id);
  });
}

// A corner drag or the Inspector's size builds the inset again at that size, in one undo step. An inset the editor
// does not build (no source, a plot, a file outside the workspace) scales its saved drawing instead, and says why.
async function resizeInset(id, size) {
  let note = "";
  await withStatus("Resizing", async () => {
    const built = entryFor(id)?.source && await api.insetSize(id, size).catch((error) => {
      if (error.status !== 400) throw error;
      note = `Scaled its saved drawing: ${error.message}`;
      return null;
    });
    commit(built || await api.update(id, size));
  });
  if (note) setStatus(note);
}

const palette = createPalette({
  listEl: els.paletteList,
  searchEl: els.paletteSearch,
  onAdd: paletteAdd,
  onFigure: (f) => addFigure(f).catch(() => {}),   // withStatus has shown the error
});
for (const [id, view] of [["btn-view-1d", "1d"], ["btn-view-2d", "2d"], ["btn-view-3d", "2d"], ["btn-view-layout", "2d"]]) {
  document.getElementById(id)?.addEventListener("click", () => palette.setView(view));
}

// -- state / history -------------------------------------------------------

function threejsSrc() {
  return `${api.threejsUrl()}?editable=1&t=${Date.now()}`;
}

let cameraState = null; // last 3D camera pose, restored across re-renders

function postHighlight() {
  if (els.view3d.hidden) return;
  const win = els.view3d.contentWindow;
  // the whole selection, the primary first: the 3D view highlights every part and puts its gizmo on the primary
  if (win) win.postMessage({ type: "optodraw-highlight", id: canvas.selectedId || null, ids: canvas.selectedIds }, "*");
}

function postCamera() {
  if (els.view3d.hidden || !cameraState) return;
  const win = els.view3d.contentWindow;
  if (win) win.postMessage({ type: "optodraw-set-camera", pos: cameraState.pos, target: cameraState.target }, "*");
}

let refreshSeq = 0;      // a slow response of an older edit must not draw over a newer one
const BUILDING_LIGHT = "Building the light…";
async function refresh3D(withTour = false) {
  // Rebuild the 3D view's content in place (no iframe reload -> camera preserved).
  if (els.view3d.hidden) return;
  const win = els.view3d.contentWindow;
  if (!win) return;
  const seq = ++refreshSeq;
  // The light payload is slow to build on a large chip. After an edit the items go first, so the view follows at
  // once, and the light (asked for only while it is on) follows; until it comes, the page keeps the light on but
  // draws none (pending). Play tour changes no item: the items and the light with the tour's drive tables come in
  // one response, so a failure leaves the page and its light as they are.
  const withLight = animState.enabled || withTour;
  if (!withTour) {
    try {
      const { items } = await api.scene3d(false);
      if (seq !== refreshSeq) return;
      win.postMessage({ type: "optodraw-rebuild", items, light: null, pending: withLight }, "*");
      if (!withLight) return true;
    } catch (_) {
      return; // the iframe may still be loading; the next edit re-syncs
    }
    els.status.textContent = BUILDING_LIGHT;    // stays until the light comes (setStatus clears its text itself)
    els.status.style.color = "var(--text-3)";
  }
  try {
    const { items, light } = await api.scene3d(true, withTour);
    if (seq !== refreshSeq) return;
    if (withTour) win.postMessage({ type: "optodraw-rebuild", items, light }, "*");
    else win.postMessage({ type: "optodraw-light", light }, "*");
    if (els.status.textContent === BUILDING_LIGHT) setStatus("");
    return true;
  } catch (error) {
    if (seq !== refreshSeq) return;
    if (withTour) {                   // no tour: the page and the light stay as they are
      setStatus(`No tour: ${error.message}`, true);
      return false;
    }
    animState.enabled = false;        // no light came: the button must not show it on
    syncAnimButton();
    setStatus(`No light: ${error.message}`, true);
    win.postMessage({ type: "optodraw-light", light: null }, "*");
  }
}

let savedTimer = null;
function flashSaved() {
  els.wsSaved.classList.add("on");
  clearTimeout(savedTimer);
  savedTimer = setTimeout(() => els.wsSaved.classList.remove("on"), 1200);
}

function applyPayload(payload) {
  properties.refreshLight();       // a change of the scene (a new source wavelength, an undo) moves the tuning values
  setInsetPath(payload.path);      // first: a way back out restores that level's undo history
  if (payload.spec) currentSpec = payload.spec;
  canvas.setSpec(currentSpec);
  if (payload.svg !== undefined) canvas.setSvg(payload.svg);
  applySceneStyle(currentSpec);
  if (payload.workspace) { setWorkspace(payload.workspace); els.wsName.textContent = payload.workspace; flashSaved(); }
  portsPromise = null; // ports move with the spec — refetch lazily on next use
  renderOutline(); // keep the Outline tree + count badge in sync with the spec
  syncTraceButton(); // Trace toggle reflects whether any source is emitting
  refresh3D(); // in-place 3D update when the 3D view is open
  syncLayout(); // the Layout button follows the GDS parts; an open Layout view follows its part
  codeTab.sceneChanged(); // the Code tab's text follows, unless it holds typing
}

// Apply scene-level view settings to the DOM. The whole stage IS the scene
// (unbounded plane), so the scene background paints the stage itself.
function applySceneStyle(spec) {
  if (!spec) return;
  const stage = document.getElementById("stage");
  if (stage) stage.style.backgroundColor = /^#[0-9a-f]{3,8}$/i.test(spec.background || "") ? spec.background : "#ffffff";
}

function openSceneSettings() {
  const s = currentSpec || {};
  const light = s.beam_style || {};
  dialogForm({
    title: "Scene settings",
    confirmText: "Apply",
    fields: [
      { key: "title", label: "Title", type: "text", value: s.title || "Untitled Setup" },
      { key: "width", label: "Export frame width (units)", type: "number", value: s.width || 220, step: "1" },
      { key: "height", label: "Export frame height (units)", type: "number", value: s.height || 140, step: "1" },
      { key: "background", label: "Workspace background (2D)", type: "color", value: /^#[0-9a-f]{6}$/i.test(s.background || "") ? s.background : "#ffffff" },
      { key: "show_labels", label: "Show component labels in 2D (the 3D labels are in View)", type: "checkbox", value: s.show_labels !== false },
      { key: "beam_opacity", label: "Beam opacity (2D)", type: "number", value: light.opacity ?? 0.5, step: "0.05", min: "0.05", max: "1" },
      { key: "beam_scale", label: "Beam width scale (2D)", type: "number", value: light.scale ?? 1, step: "0.1", min: "0.1", max: "5" },
      { key: "beam_by_wavelength", label: "Beam width follows wavelength: 0 none, 1 usual, 2 infrared wider (2D)", type: "number", value: light.by_wavelength ?? 1, step: "0.1", min: "0", max: "3" },
      { key: "show_grid_3d", label: "Show ground grid / table (3D)", type: "checkbox", value: s.show_grid_3d !== false },
      { key: "beam_height", label: "Optical / beam height (3D, units)", type: "number", value: s.beam_height || 30, step: "1", min: "4", max: "60" },
      { key: "trace_physical", label: "Physical ray tracing — real hits, misses & apertures (Trace tool)", type: "checkbox", value: s.trace_mode === "physical" },
      { key: "on_chip_scene", label: "On-chip scene — chip mode in 3D (auto-detected for pure chip scenes)", type: "checkbox", value: s.platform === "on_chip" },
      { key: "chip_base", label: "Auto chip base — generated die + carrier under chip scenes (3D)", type: "checkbox", value: s.chip_base !== false },
    ],
  }).then((vals) => {
    if (!vals) return;
    vals.trace_mode = vals.trace_physical ? "physical" : "schematic";
    delete vals.trace_physical;
    vals.platform = vals.on_chip_scene ? "on_chip" : "free_space";
    delete vals.on_chip_scene;
    vals.beam_style = { opacity: Number(vals.beam_opacity), scale: Number(vals.beam_scale), by_wavelength: Number(vals.beam_by_wavelength) };
    delete vals.beam_opacity;
    delete vals.beam_scale;
    delete vals.beam_by_wavelength;
    withStatus("Updating scene", async () => {
      commit(await api.setMeta(vals));
      if (!els.view3d.hidden) els.view3d.src = threejsSrc(); // reload 3D so label/grid/height take effect
    });
  });
}

// A scene saved with a look (metadata.animation.look) opens in that look; a scene without one opens in Light.
function takeSavedLook(spec) {
  animState.look = spec?.metadata?.animation?.look === "field" ? "field" : "light";
  postAnim("look", animState.look);
}

// A page over 16 MB (large pictures) loads and saves slowly: the status bar names it when it loads.
function noteLargePage(size) {
  if (size > 16 * 2 ** 20) {
    setStatus(`This page is ${Math.round(size / 2 ** 20)} MB, more than 16 MB: it loads and saves slowly. ` +
      "Make its largest pictures smaller.", true);
  }
}

// Load a different workspace: apply it and start a fresh undo history.
function loadWorkspace(payload) {
  takeSavedLook(payload.spec);
  applyPayload(payload);
  history.length = 0;
  historyIndex = -1;
  pushHistory(currentSpec);
  canvas.select(null);
  properties.clear();
}

function commit(payload) {
  applyPayload(payload);
  pushHistory(currentSpec);
}

window.addEventListener("optodraw:scene-committed", (event) => {
  if (event.detail?.payload?.spec) commit(event.detail.payload);
});
window.addEventListener("optodraw:query-wavelength", (event) => {
  if (event.detail) event.detail.wavelength = activeWavelength;
});

function pushHistory(spec) {
  history.splice(historyIndex + 1); // drop redo tail
  history.push(clone(spec));
  historyIndex = history.length - 1;
  updateButtons();
}

async function undo() {
  if (historyIndex <= 0) return;
  historyIndex -= 1;
  await withStatus("Undo", async () => applyPayload(await api.setScene(history[historyIndex])));
  syncSelection();
}

async function redo() {
  if (historyIndex >= history.length - 1) return;
  historyIndex += 1;
  await withStatus("Redo", async () => applyPayload(await api.setScene(history[historyIndex])));
  syncSelection();
}

function syncSelection() {
  // drop ids that no longer exist after undo/redo, re-render the selection UI
  canvas.selectMany(canvas.selectedIds.filter((id) => entryFor(id)));
  updateButtons();
}

function updateButtons() {
  els.undo.disabled = historyIndex <= 0;
  els.redo.disabled = historyIndex >= history.length - 1;
}

// Contextual toolbar (bottom row): selection-dependent quick actions.
function renderContextActions(ids) {
  const host = els.contextActions;
  host.innerHTML = "";
  if (!ids.length) return;
  const mk = (label, title, onClick, cls = "tb-btn tb-text") => {
    const b = document.createElement("button");
    b.className = cls; b.textContent = label; b.title = title;
    b.addEventListener("click", onClick);
    host.appendChild(b);
  };
  const tag = document.createElement("span");
  tag.className = "ctx-count";
  tag.textContent = ids.length === 1 ? selLabel(ids[0]) : `${ids.length} selected`;
  tag.title = tag.textContent;                      // one line in the toolbar; the whole name on hover
  host.appendChild(tag);
  const mkIcon = (iconId, title, onClick) => {
    const b = document.createElement("button");
    b.className = "tb-btn"; b.title = title;
    b.innerHTML = `<svg class="ic"><use href="#${iconId}"/></svg>`;
    b.addEventListener("click", onClick);
    host.appendChild(b);
  };
  mkIcon("i-rot-ccw", "Rotate 90° counter-clockwise (selection rotates about its center)", () => rotateSelected(90));
  mkIcon("i-rot-cw", "Rotate 90° clockwise", () => rotateSelected(-90));
  mkIcon("i-flip-h", "Flip horizontally (mirror left ↔ right)", () => flipSelected("h"));
  mkIcon("i-flip-v", "Flip vertically (mirror up ↕ down)", () => flipSelected("v"));
  if (ids.length >= 2) {
    mk("Align", "Align to the first-selected component (left edges)", () => alignSelected("left"));
    mk("Distribute", "Distribute selected horizontally (equal center spacing)", () => distributeSelected("x"));
  }
  const scene = ids.length === 1 ? entryFor(ids[0])?.source : null;
  if (scene && scene.kind === "SceneView" && scene.scene) {
    mk("Open scene", "Edit the scene inside this inset (or double-click it)", () => openInset(ids[0]));
  }
  for (const f of FIGURE_ENTRIES.filter((e) => e.of?.includes(scene?.kind))) {
    mk(f.label, `Make a ${f.label} of this inset, beside it`, () => addFigure(f).catch(() => {}));
  }
  mk("Duplicate", "Duplicate (Ctrl+D)", () => duplicateSelected());
  mk("Delete", "Delete (Del)", () => deleteSelected(), "tb-btn tb-text ctx-danger");
}

// -- shared helpers --------------------------------------------------------

function entryFor(id) {
  const lists = [currentSpec?.components, currentSpec?.beams, currentSpec?.routes];
  for (const list of lists) {
    const hit = (list || []).find((x) => x.id === id);
    if (hit) return hit;
  }
  return null;
}

function selLabel(id) {
  const e = entryFor(id);
  return e ? `${e.type || "Beam"} · ${e.id}` : "No selection";
}

function onSelectionChange(ids) {
  updateButtons();
  renderContextActions(ids);
  syncOutlineSelection(); // highlight the matching Outline rows
  codeTab.selectionChanged(); // and the part's lines in the Code tab
  postHighlight(); // keep the 3D view's selection highlight in sync (primary)
  if (ids.length === 0) { showSeq++; els.selInfo.textContent = "No selection"; properties.clear(); return; }
  if (ids.length === 1) { els.selInfo.textContent = selLabel(ids[0]); showSingle(ids[0]); return; }
  showSeq++; // invalidate any in-flight single-component fetch
  els.selInfo.textContent = `${ids.length} selected`;
  properties.showMulti(ids);
}

function refreshSelectionUI() { onSelectionChange(canvas.selectedIds); }

// -- right panel: Inspector | Outline | Code tabs ----------------------------

const RIGHT_TABS = {
  inspector: [els.tabInspector, els.paneInspector],
  outline: [els.tabOutline, els.paneOutline],
  code: [els.tabCode, els.paneCode],
};
function setRightTab(name) {
  for (const [key, [tab, pane]] of Object.entries(RIGHT_TABS)) {
    tab.classList.toggle("active", key === name);
    tab.setAttribute("aria-selected", String(key === name));
    pane.hidden = key !== name;
  }
  if (name === "outline") renderOutline();
  if (name === "code") codeTab.show();
}
els.tabInspector.addEventListener("click", () => setRightTab("inspector"));
els.tabOutline.addEventListener("click", () => setRightTab("outline"));
els.tabCode.addEventListener("click", () => setRightTab("code"));

// The scene as YAML text, edited here or on the canvas: an apply is one undo step, like a drag.
const codeTab = createCodeTab({
  pane: els.paneCode,
  api,
  selection: () => canvas.selectedIds,
  select: (id) => canvas.select(id),
  level: () => Math.max(0, insetPath.length - 1),
  onApplied: (payload) => { commit(payload); syncSelection(); },
  setStatus,
});

// -- open insets: the path bar, and an undo history for each level ----------

let insetPath = [];        // the page and each open inset, outermost first, as the server names them
const outerHistory = [];   // the undo history of each level around the open inset, outermost first

function setInsetPath(path) {
  if (!Array.isArray(path)) return;
  const depth = Math.max(0, path.length - 1);
  if (depth < Math.max(0, insetPath.length - 1)) {    // the server went back out: Back, File > Open, a workspace
    const saved = outerHistory.splice(depth)[0];
    history.length = 0;
    historyIndex = -1;
    if (saved) { history.push(...saved.entries); historyIndex = saved.index; }
    updateButtons();
  }
  insetPath = path;
  setLevel(depth);
  renderInsetPath();
}

// Back to the page before anything that replaces it (New, File > Open): the inset draws again, and the
// page with it is one undo step. It throws, and the action stops, when the inset cannot go back.
async function leaveInsets() {
  if (insetPath.length > 1) await closeInsetTo(0);
}

function renderInsetPath() {
  const bar = els.insetPath;
  bar.replaceChildren();
  bar.hidden = insetPath.length < 2;
  if (bar.hidden) return;
  const button = (label, title, onClick, cls = "") => {
    const b = document.createElement("button");
    b.type = "button"; b.textContent = label; b.title = title; if (cls) b.className = cls;
    b.addEventListener("click", onClick);
    bar.appendChild(b);
  };
  button("‹ Back", "Back out of this inset: it draws again from the changed scene", () => closeInsetTo(insetPath.length - 2), "ip-back");
  insetPath.forEach((level, k) => {
    if (k) {
      const sep = document.createElement("span");
      sep.className = "ip-sep"; sep.textContent = "›";
      bar.appendChild(sep);
    }
    if (k < insetPath.length - 1) { button(level.name, `Back to ${level.name}`, () => closeInsetTo(k)); return; }
    const here = document.createElement("span");
    here.className = "ip-here"; here.textContent = level.name; here.title = "The scene you are editing";
    bar.appendChild(here);
  });
}

async function openInset(id) {
  await withStatus("Opening the inset", async () => {
    const payload = await api.openInset(id);
    outerHistory.push({ entries: history.slice(), index: historyIndex });
    history.length = 0;
    historyIndex = -1;
    canvas.select(null);
    properties.clear();
    commit(payload); // the scene inside starts its own undo history
    canvas.fit();
  });
}

async function closeInsetTo(depth) {
  await withStatus("Going back", async () => {
    const payload = await api.closeInset(depth);
    canvas.select(null);
    properties.clear();
    applyPayload(payload); // restores that level's undo history
    if (JSON.stringify(currentSpec) !== JSON.stringify(history[historyIndex])) pushHistory(currentSpec);
    canvas.fit();
  });
}
els.outlineSearch.addEventListener("input", () => renderOutline());

const OUTLINE_GROUPS = [
  { key: "components", title: "Components", icon: "i-cube" },
  { key: "routes", title: "Routes", icon: "i-route" },
  { key: "beams", title: "Beams", icon: "i-trace" },
];

const escHtml = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

function outlineRowMeta(kind, e) {
  if (kind === "components") return { name: e.label || e.id, sub: e.type || "" };
  if (kind === "routes") return { name: e.id, sub: e.kind || "route" };
  const fan = e.traced_from ? " · fan" : "";
  return { name: e.id, sub: (e.wavelength ? `${e.wavelength} nm` : "beam") + fan };
}

// Marginal rays of a traced bundle are visual detail — the Outline lists only
// each bundle's chief ray (ray 0) alongside manual beams.
function outlineVisible(kind, e) {
  return kind !== "beams" || !e.traced_from || !e.ray;
}

// Scene tree (Outline tab): grouped, filterable, click = select on canvas,
// shift/⌘-click = add to selection, double-click = jump to the Inspector.
function renderOutline() {
  const host = els.outlineList;
  const total = OUTLINE_GROUPS.reduce(
    (n, g) => n + ((currentSpec && currentSpec[g.key]) || []).filter((e) => outlineVisible(g.key, e)).length, 0);
  els.outlineCount.textContent = String(total);
  els.outlineCount.hidden = total === 0;
  if (els.paneOutline.hidden) return; // badge stays fresh; rows render on open
  const q = (els.outlineSearch.value || "").trim().toLowerCase();
  const scroll = host.scrollTop;
  host.innerHTML = "";
  const selected = new Set(canvas.selectedIds);
  for (const g of OUTLINE_GROUPS) {
    const items = ((currentSpec && currentSpec[g.key]) || []).filter((e) => {
      if (!outlineVisible(g.key, e)) return false;
      if (!q) return true;
      const m = outlineRowMeta(g.key, e);
      return `${e.id} ${m.name} ${m.sub}`.toLowerCase().includes(q);
    });
    if (!items.length) continue;
    const head = document.createElement("div");
    head.className = "ol-group";
    head.innerHTML = `<span>${g.title}</span><span class="pg-count">${items.length}</span>`;
    host.appendChild(head);
    for (const e of items) {
      const m = outlineRowMeta(g.key, e);
      const row = document.createElement("button");
      row.type = "button";
      row.className = "ol-row" + (selected.has(e.id) ? " active" : "");
      row.dataset.id = e.id;
      const dot = g.key === "beams"
        ? `<span class="ol-dot" style="background:${wavelengthHex(Number(e.wavelength) || 633)}"></span>`
        : `<svg class="ic ic-sm ol-glyph"><use href="#${g.icon}"/></svg>`;
      row.innerHTML = `${dot}<span class="ol-name">${escHtml(m.name)}</span><span class="ol-sub">${escHtml(m.sub)}</span>`;
      row.addEventListener("click", (evt) => canvas.select(e.id, evt.shiftKey || evt.metaKey || evt.ctrlKey));
      row.addEventListener("dblclick", () => setRightTab("inspector"));
      host.appendChild(row);
    }
  }
  if (!host.children.length) {
    const empty = document.createElement("div");
    empty.className = "ol-empty";
    empty.textContent = q ? "No objects match the filter." : "Empty scene — add components from the palette.";
    host.appendChild(empty);
  }
  host.scrollTop = scroll;
}

function syncOutlineSelection() {
  if (els.paneOutline.hidden) return;
  const selected = new Set(canvas.selectedIds);
  let first = null;
  for (const row of els.outlineList.querySelectorAll(".ol-row")) {
    const on = selected.has(row.dataset.id);
    row.classList.toggle("active", on);
    if (on && !first) first = row;
  }
  if (first) first.scrollIntoView({ block: "nearest" });
}

// Guards the async fetches below: a newer selection invalidates in-flight shows,
// so a slow describe/ports response can't overwrite the current form.
let showSeq = 0;
let portsPromise = null; // ports map cache, invalidated on every spec commit

async function showSingle(id) {
  const seq = ++showSeq;
  const entry = entryFor(id);
  if (!entry) { properties.clear(); return; }
  if (entry.path !== undefined || entry.points !== undefined || entry.from !== undefined) { properties.show(entry); return; } // beam/route link
  const descriptionKey = `${entry.type}:${entry.part_definition || ""}`;
  if (!describeCache.has(descriptionKey)) {
    try { describeCache.set(descriptionKey, await api.describe(entry.type, entry.part_definition)); }
    catch (_) { describeCache.set(descriptionKey, { parameters: [] }); }
  }
  let gdsLayers = null;
  if (entry.type === "GDSModel") {
    gdsLayers = await api.gdsLayers(entry.id).then((r) => r.layers).catch(() => null);
  }
  portsPromise = portsPromise || api.ports().catch(() => ({ ports: {} }));
  const ports = await portsPromise.then((r) => (r.ports || {})[entry.id] || null).catch(() => null);
  if (seq !== showSeq) return; // selection changed while fetching
  properties.show(entry, describeCache.get(descriptionKey), materials, gdsLayers, ports);
}

// -- spec-level multi operations (computed client-side, committed once) -----

const newId = (type) =>
  `${String(type).toLowerCase()}_d${Date.now().toString(36)}${Math.floor(Math.random() * 1000)}`;
let clipboard = [];
let liveMoveBusy = false;  // one live re-trace in flight at a time

function applyMoveChanges(next, changes) {
  let delta = null;
  for (const ch of changes) {
    const e = next.components.find((c) => c.id === ch.id);
    if (!e) continue;
    if (ch.center) {
      if (!delta) { const c = ctr(e); delta = [ch.center[0] - c[0], ch.center[1] - c[1]]; }
      e.center = ch.center;
    }
    if (ch.angle !== undefined) e.angle = ch.angle;
  }
  if (delta && (delta[0] || delta[1])) {
    // dragging a system moves its wiring too (route shapes, beam waypoints)
    transformAttachedLinks(next, changes.map((c) => c.id), (x, y) => [x + delta[0], y + delta[1]]);
  }
}

function selComponentIds() {
  return canvas.selectedIds.filter((id) => (currentSpec?.components || []).some((c) => c.id === id));
}
function ctr(e) { const c = e.center || [0, 0]; return [Number(c[0]) || 0, Number(c[1]) || 0]; }

async function applySpec(label, mutate, opts = {}) {
  return withStatus(label, async () => {
    const next = clone(currentSpec);
    mutate(next);
    commit(await api.setScene(next, true));  // an edit: a moved inset brings its marks
    if (opts.reselect !== undefined) canvas.selectMany(opts.reselect);
    else refreshSelectionUI();
  });
}

function deleteSelected() {
  const ids = canvas.selectedIds;
  if (!ids.length) return;
  // Deleting any ray of a traced bundle turns that source's trace OFF entirely —
  // partial bundles would just be regrown by the live re-trace.
  const offSources = new Set(
    (currentSpec?.beams || []).filter((b) => ids.includes(b.id) && b.traced_from).map((b) => b.traced_from),
  );
  return applySpec("Delete", (next) => {
    // the names a deleted part goes by (its id, its label, and those of the parts inside it): a beam or route that
    // still named one would stop the scene loading
    const gone = new Set();
    const collect = (c) => {
      if (!c || typeof c !== "object") return;
      if (c.id) gone.add(c.id);
      if (c.label) gone.add(c.label);
      (c.children || []).forEach(collect);
    };
    (next.components || []).filter((c) => ids.includes(c.id)).forEach(collect);
    for (const key of ["components", "beams", "routes"]) {
      next[key] = (next[key] || []).filter(
        (x) => !ids.includes(x.id) && !(key === "beams" && x.traced_from && offSources.has(x.traced_from)),
      );
    }
    // a part some light went through: the beam skips it (straight on from the stop before to the stop after) and
    // goes only when fewer than two stops are left; a route that started or ended on it goes with it
    next.beams = next.beams.flatMap((b) => {
      if (b.traced_from && gone.has(b.traced_from)) return [];
      if (!Array.isArray(b.path)) return [b];
      const path = b.path.filter((p) => !refersTo(p, gone));
      if (path.length === b.path.length) return [b];
      return path.length >= 2 ? [{ ...b, path }] : [];
    });
    next.routes = next.routes.filter((r) => !refersTo(r.from, gone) && !refersTo(r.to, gone));
  }, { reselect: [] });
}

// whether a beam stop or route end names one of the parts in `names`: "M", ["M", "out"], or {component: "M", ...}
function refersTo(end, names) {
  if (typeof end === "string") return names.has(end);
  if (Array.isArray(end)) return typeof end[0] === "string" && names.has(end[0]);
  if (end && typeof end === "object") return ["id", "component", "component_id"].some((f) => names.has(end[f]));
  return false;
}

function duplicateSelected() {
  const ids = selComponentIds();
  if (!ids.length) return;
  const created = [];
  return applySpec("Duplicate", (next) => {
    for (const id of ids) {
      const copy = clone(next.components.find((c) => c.id === id));
      copy.id = newId(copy.type);
      const c = ctr(copy); copy.center = [c[0] + gridSize, c[1] + gridSize];
      next.components.push(copy); created.push(copy.id);
    }
  }, { reselect: created });
}

function copySelected() {
  clipboard = selComponentIds().map((id) => clone(currentSpec.components.find((c) => c.id === id)));
  if (clipboard.length) setStatus(`Copied ${clipboard.length}`);
}
function paste() {
  if (!clipboard.length) return;
  const created = [];
  return applySpec("Paste", (next) => {
    for (const src of clipboard) {
      const copy = clone(src);
      copy.id = newId(copy.type);
      const c = ctr(copy); copy.center = [c[0] + 2 * gridSize, c[1] + 2 * gridSize];
      next.components.push(copy); created.push(copy.id);
    }
  }, { reselect: created });
}

// Apply fn(x, y) -> [x', y'] to the shape of every route/beam whose endpoint
// components are ALL inside the moved set — so moving/rotating a whole system
// carries its wiring along instead of leaving route shapes behind.
function transformAttachedLinks(next, movedIds, fn) {
  const moved = new Set(movedIds);
  for (const r of next.routes || []) {
    const src = Array.isArray(r.from) ? r.from[0] : r.from;
    const dst = Array.isArray(r.to) ? r.to[0] : r.to;
    if (!moved.has(src) || !moved.has(dst)) continue;
    for (const s of r.steps || []) { const [x, y] = fn(s.x, s.y); s.x = x; s.y = y; }
    if (Array.isArray(r.points)) {
      r.points = r.points.map((p) => { const [x, y] = fn(p[0], p[1]); return p.length > 2 ? [x, y, p[2]] : [x, y]; });
    }
  }
  for (const b of next.beams || []) {
    if (b.traced_from) continue; // derived — the live re-trace regrows them
    const path = b.path || [];
    const refs = path
      .map((p) => (typeof p === "string" ? p : Array.isArray(p) && typeof p[0] === "string" ? p[0] : null))
      .filter(Boolean);
    if (!refs.length || !refs.every((id) => moved.has(id))) continue;
    b.path = path.map((p) => {
      if (!Array.isArray(p) || typeof p[0] !== "number") return p;
      const [x, y] = fn(p[0], p[1]);
      return p.length > 2 ? [x, y, p[2]] : [x, y];
    });
  }
}

function nudge(dx, dy) {
  const ids = selComponentIds();
  if (!ids.length) return;
  return applySpec("Move", (next) => {
    for (const id of ids) {
      const e = next.components.find((c) => c.id === id);
      const c = ctr(e); e.center = [c[0] + dx, c[1] + dy];
    }
    transformAttachedLinks(next, ids, (x, y) => [x + dx, y + dy]);
  }, { reselect: ids });
}

// Rotate the selection about its collective center; a single component simply
// rotates in place. Attached routes/beams rotate along with the system.
function rotateSelected(deg) {
  const ids = selComponentIds();
  if (!ids.length) return;
  if (ids.length === 1) {
    return applySpec("Rotate", (next) => {
      const e = next.components.find((c) => c.id === ids[0]);
      e.angle = (((Number(e.angle) || 0) + deg) % 360 + 360) % 360;
    }, { reselect: ids });
  }
  const centers = ids.map((id) => ctr(currentSpec.components.find((c) => c.id === id)));
  const xs = centers.map((c) => c[0]), ys = centers.map((c) => c[1]);
  const px = (Math.min(...xs) + Math.max(...xs)) / 2;
  const py = (Math.min(...ys) + Math.max(...ys)) / 2;
  const rad = (deg * Math.PI) / 180, cos = Math.cos(rad), sin = Math.sin(rad);
  const rot = (x, y) => [px + (x - px) * cos - (y - py) * sin, py + (x - px) * sin + (y - py) * cos];
  return applySpec("Rotate", (next) => {
    for (const id of ids) {
      const e = next.components.find((c) => c.id === id);
      const c = ctr(e);
      e.center = rot(c[0], c[1]).map((v) => Math.round(v * 100) / 100);
      e.angle = (((Number(e.angle) || 0) + deg) % 360 + 360) % 360;
    }
    transformAttachedLinks(next, ids, rot);
  }, { reselect: ids });
}

// Mirror the selection across the vertical ("h") or horizontal ("v") axis
// through its center; a single component mirrors its facing angle in place.
function flipSelected(axis) {
  const ids = selComponentIds();
  if (!ids.length) return;
  const mapAngle = (a) => {
    const angle = Number(a) || 0;
    const flipped = axis === "h" ? 180 - angle : -angle;
    return ((flipped % 360) + 360) % 360;
  };
  if (ids.length === 1) {
    return applySpec("Flip", (next) => {
      const e = next.components.find((c) => c.id === ids[0]);
      e.angle = mapAngle(e.angle);
    }, { reselect: ids });
  }
  const centers = ids.map((id) => ctr(currentSpec.components.find((c) => c.id === id)));
  const xs = centers.map((c) => c[0]), ys = centers.map((c) => c[1]);
  const px = (Math.min(...xs) + Math.max(...xs)) / 2;
  const py = (Math.min(...ys) + Math.max(...ys)) / 2;
  const mirror = axis === "h" ? (x, y) => [2 * px - x, y] : (x, y) => [x, 2 * py - y];
  return applySpec("Flip", (next) => {
    for (const id of ids) {
      const e = next.components.find((c) => c.id === id);
      const c = ctr(e);
      e.center = mirror(c[0], c[1]).map((v) => Math.round(v * 100) / 100);
      e.angle = mapAngle(e.angle);
    }
    transformAttachedLinks(next, ids, mirror);
  }, { reselect: ids });
}

// Align to the FIRST-selected component (the reference stays put): edges align
// to its real drawn edges, centers to its center. World y-up; drawn boxes come
// from the canvas in svg y-down coords, so vertical edges are negated.
function alignSelected(how) {
  const ids = selComponentIds();
  if (ids.length < 2) return;
  const metrics = (id) => {
    const c = ctr(currentSpec.components.find((x) => x.id === id));
    const b = canvas.worldBoxFor ? canvas.worldBoxFor(id) : null;
    if (!b) return { left: c[0], right: c[0], cx: c[0], top: c[1], bottom: c[1], cy: c[1] };
    return { left: b.x0, right: b.x1, cx: (b.x0 + b.x1) / 2, top: -b.y0, bottom: -b.y1, cy: -(b.y0 + b.y1) / 2 };
  };
  const ref = metrics(ids[0]);
  return applySpec("Align", (next) => {
    for (const id of ids.slice(1)) {
      const m = metrics(id);
      const e = next.components.find((c) => c.id === id);
      const c = ctr(e);
      if (how === "left") e.center = [c[0] + (ref.left - m.left), c[1]];
      else if (how === "right") e.center = [c[0] + (ref.right - m.right), c[1]];
      else if (how === "centerx") e.center = [c[0] + (ref.cx - m.cx), c[1]];
      else if (how === "top") e.center = [c[0], c[1] + (ref.top - m.top)];
      else if (how === "bottom") e.center = [c[0], c[1] + (ref.bottom - m.bottom)];
      else e.center = [c[0], c[1] + (ref.cy - m.cy)]; // centery ("middle")
    }
  }, { reselect: ids });
}

function distributeSelected(axis) {
  const ids = selComponentIds();
  if (ids.length < 3) return;
  const i = axis === "x" ? 0 : 1;
  const es = ids.map((id) => currentSpec.components.find((c) => c.id === id)).sort((a, b) => ctr(a)[i] - ctr(b)[i]);
  const lo = ctr(es[0])[i]; const hi = ctr(es[es.length - 1])[i];
  const step = (hi - lo) / (es.length - 1);
  return applySpec("Distribute", (next) => {
    es.forEach((e, k) => {
      const t = next.components.find((c) => c.id === e.id); const c = ctr(t);
      t.center = i === 0 ? [lo + step * k, c[1]] : [c[0], lo + step * k];
    });
  }, { reselect: ids });
}

// -- toolbar ---------------------------------------------------------------

function download(filename, text, type = "application/json") {
  const blob = new Blob([text], { type });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = filename; a.click();
  URL.revokeObjectURL(url);
}

function sceneName() {
  return String(currentSpec?.title || "scene").replace(/\s+/g, "_");
}

document.getElementById("btn-new").addEventListener("click", () =>
  withStatus("New scene", async () => {
    await leaveInsets();
    const payload = await api.newScene({});
    takeSavedLook(payload.spec);       // a new scene has no saved look: Light
    commit(payload);
    canvas.select(null);
    properties.clear();
  }));

document.getElementById("file-open").addEventListener("change", (e) => {
  const file = e.target.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = () => withStatus("Opening", async () => {
    const spec = JSON.parse(reader.result); // a file that is not JSON stops here, before the inset closes
    await leaveInsets();
    const payload = await api.setScene(spec, false, true); // a whole page: open insets close
    takeSavedLook(payload.spec);
    commit(payload);
    canvas.select(null);
    properties.clear();
  }).then(() => noteLargePage(file.size), () => {});
  reader.readAsText(file);
  e.target.value = "";
});

document.getElementById("btn-save").addEventListener("click", () =>
  withStatus("Saving", async () => {
    const page = await api.getWholeScene(); // the page, each open inset drawn again
    download(`${String(page.title || "scene").replace(/\s+/g, "_")}.json`, JSON.stringify(page, null, 2));
  }));

const exportView = () => document.getElementById("btn-view-1d")?.classList.contains("active") ? "1d" : "2d";

// One Export menu covers every output format (was four separate toolbar buttons).
const EXPORT_ACTIONS = [
  {
    icon: "i-image", label: "SVG image", sub: "Vector drawing of the active 1D or 2D view",
    run: () => withStatus("Exporting SVG", async () => {
      if (exportView() === "1d") {
        const response = await fetch(api.render1dUrl());
        if (!response.ok) throw new Error("1D SVG export failed");
        download(`${sceneName()}.svg`, await response.text(), "image/svg+xml");
      } else {
        download(`${sceneName()}.svg`, (await api.renderSvg()).svg, "image/svg+xml");
      }
    }),
  },
  {
    icon: "i-doc", label: "TikZ (LaTeX)", sub: "Standalone .tex picture",
    run: () => withStatus("Exporting TikZ", async () => {
      const response = await fetch(api.tikzUrl(exportView()));
      if (!response.ok) throw new Error("TikZ export failed");
      download(`${sceneName()}.tex`, await response.text(), "text/plain");
    }),
  },
  {
    icon: "i-export", label: "Publication figure…", sub: "SVG + TikZ + PNG bundle with caption (zip)",
    run: () => openFigure(),
  },
  {
    icon: "i-cube", label: "Blender bundle", sub: "GLB model + headless render script",
    run: () => withStatus("Exporting GLB + Blender script", async () => {
      const base = sceneName();
      const res = await fetch(api.glbUrl());
      if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || "GLB export failed");
      download(`${base}.glb`, await res.blob(), "model/gltf-binary");
      const script = await fetch(api.blenderScriptUrl(`${base}.glb`)).then((r) => r.text());
      download(`${base}.blender.py`, script, "text/x-python");
      setStatus(`Exported ${base}.glb + ${base}.blender.py — run: blender --background --python ${base}.blender.py`);
    }),
  },
  // the 3D view's exports: the image from the view as it stands, the model and the page from the server
  {
    icon: "i-image", label: "3D image (PNG)", sub: "The 3D view as it stands, at three times its size", divider: true,
    run: () => in3dThen(() => post3d({ type: "optodraw-view", action: "png" })),
  },
  {
    icon: "i-image", label: "3D image, transparent", sub: "The parts only, on a transparent background",
    run: () => in3dThen(() => post3d({ type: "optodraw-view", action: "png-clear" })),
  },
  {
    icon: "i-cube", label: "3D model (GLB)", sub: "Meshes and materials for Blender or any glTF viewer",
    run: () => withStatus("Exporting GLB", async () => {
      const res = await fetch(api.glbUrl());
      if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || "GLB export failed");
      download(`${sceneName()}.glb`, await res.blob(), "model/gltf-binary");
    }),
  },
  {
    icon: "i-doc", label: "3D page (HTML)", sub: "One interactive page with its bar, as on the site",
    run: () => withStatus("Exporting the 3D page", async () => {
      const res = await fetch(api.threejsUrl());
      if (!res.ok) throw new Error("3D page export failed");
      download(`${sceneName()}_3d.html`, await res.text(), "text/html");
    }),
  }
];

function buildExportMenu() {
  els.exportMenu.innerHTML = "";
  for (const a of EXPORT_ACTIONS) {
    const item = document.createElement("div");
    if (a.divider) {
      const line = document.createElement("div");
      line.className = "ws-menu-divider";
      els.exportMenu.appendChild(line);
    }
    item.className = "route-menu-item export-menu-item";
    item.innerHTML = `<svg class="ic ic-sm"><use href="#${a.icon}"/></svg><span class="emi-text"><b>${a.label}</b><i>${a.sub}</i></span>`;
    item.addEventListener("click", () => { toggleExportMenu(false); a.run(); });
    els.exportMenu.appendChild(item);
  }
}
function toggleExportMenu(open) {
  const show = open === undefined ? els.exportMenu.hidden : open;
  if (show) buildExportMenu();
  els.exportMenu.hidden = !show;
  els.exportBtn.setAttribute("aria-expanded", String(show));
}
els.exportBtn.addEventListener("click", (e) => { e.stopPropagation(); toggleExportMenu(); });
document.addEventListener("click", (e) => {
  if (!els.exportMenu.hidden && !e.target.closest("#export-control")) toggleExportMenu(false);
});

// -- help, feedback, and requests -------------------------------------------
// The two things a user arrives with are "this drew wrong" and "you can't draw
// my part yet". Both open a prefilled issue: the version, the platform, and a
// summary of the scene are filled in here, because nobody types those by hand
// and a report without them costs a round trip. The scene JSON itself is too
// large for a URL, so the form asks the user to drop the file in.

const REPO_URL = "https://github.com/Acceluma/optodraw";
const DOCS_URL = "https://acceluma.github.io/optodraw/";
let appVersion = "";
api.health().then((h) => { appVersion = h.version || ""; }).catch(() => {});

function sceneSummary() {
  const spec = currentSpec || {};
  const counts = {};
  for (const c of spec.components || []) counts[c.type] = (counts[c.type] || 0) + 1;
  const parts = Object.entries(counts).sort((a, b) => b[1] - a[1]).slice(0, 12)
    .map(([type, n]) => (n > 1 ? `${type} x${n}` : type));
  const rest = Object.keys(counts).length - parts.length;
  if (rest > 0) parts.push(`+${rest} more types`);
  return [
    `platform: ${spec.platform || "free_space"}`,
    `trace mode: ${spec.trace_mode || "physical"}`,
    `components: ${(spec.components || []).length} — ${parts.join(", ") || "none"}`,
    `beams: ${(spec.beams || []).length}, routes: ${(spec.routes || []).length}`,
  ].join("\n");
}

function issueUrl(template, fields) {
  const query = new URLSearchParams({ template, ...fields });
  return `${REPO_URL}/issues/new?${query}`;
}

function openIssue(template, fields) {
  window.open(issueUrl(template, fields), "_blank", "noopener");
}

const HELP_ACTIONS = [
  {
    icon: "i-bulb", label: "Request a component…", sub: "A part optodraw cannot draw yet",
    run: () => openIssue("component_request.yml", {
      use: `Drawing a ${(currentSpec || {}).platform || "free_space"} setup.\n\nScene so far:\n${sceneSummary()}`,
    }),
  },
  {
    icon: "i-alert", label: "Report a problem…", sub: "Something rendered wrong or crashed",
    run: () => openIssue("bug_report.yml", {
      version: appVersion,
      platform: navigator.platform || navigator.userAgent,
      evidence: `Scene summary (attach the JSON with Export → Save):\n${sceneSummary()}`,
    }),
  },
  {
    icon: "i-book", label: "Documentation", sub: "Guides, the API, and known limits",
    run: () => window.open(DOCS_URL, "_blank", "noopener"),
  },
  {
    icon: "i-sparkles", label: "Quick start", sub: "Reopen the welcome screen",
    run: () => showWelcome(),
  },
];

function buildHelpMenu() {
  els.helpMenu.innerHTML = "";
  for (const a of HELP_ACTIONS) {
    const item = document.createElement("div");
    item.className = "route-menu-item export-menu-item";
    item.innerHTML = `<svg class="ic ic-sm"><use href="#${a.icon}"/></svg><span class="emi-text"><b>${a.label}</b><i>${a.sub}</i></span>`;
    item.addEventListener("click", () => { toggleHelpMenu(false); a.run(); });
    els.helpMenu.appendChild(item);
  }
  const foot = document.createElement("div");
  foot.className = "help-foot";
  foot.innerHTML = `<span>optodraw ${appVersion || ""}</span><span>⌘K for the command palette</span>`;
  els.helpMenu.appendChild(foot);
}
function toggleHelpMenu(open) {
  const show = open === undefined ? els.helpMenu.hidden : open;
  if (show) buildHelpMenu();
  els.helpMenu.hidden = !show;
  els.helpBtn.setAttribute("aria-expanded", String(show));
}
els.helpBtn.addEventListener("click", (e) => { e.stopPropagation(); toggleHelpMenu(); });
document.addEventListener("click", (e) => {
  if (!els.helpMenu.hidden && !e.target.closest("#help-control")) toggleHelpMenu(false);
});

// Import a GDS layout as a GDSModel component (visible in 2D + 3D).
document.getElementById("file-gds").addEventListener("change", (e) => {
  const file = e.target.files[0];
  e.target.value = "";
  if (!file) return;
  withStatus(`Importing ${file.name}`, async () => {
    const payload = await api.importGds(file);
    commit(payload);
    canvas.select(payload.id);
    requestAnimationFrame(() => canvas.fit()); // large GDS may exceed the scene bounds
  });
});

// Import a 3D model (GLB/GLTF/OBJ/STL) as a CustomModel component.
document.getElementById("file-model").addEventListener("change", (e) => {
  const file = e.target.files[0];
  e.target.value = "";
  if (!file) return;
  withStatus(`Importing ${file.name}`, async () => {
    const payload = await api.importModel(file);
    commit(payload);
    canvas.select(payload.id);
  });
});

// Attach a KLayout .lyp, .lyd25, technology .zip or folder, or a GDS3D techfile, to the selected GDSModel
// (recolor + 3D z).
let techTargetId = null;
function attachTech(label, send) {
  const id = techTargetId;
  withStatus(label, async () => {
    const payload = await send(id);
    commit(payload);
    canvas.select(id); // refresh the inspector with the new layer colors
    return payload;
  }).then((payload) => {
    // after withStatus, which clears the line; a KLayout folder without d25/*.lyd25 gives colours only, say so
    const noHeights = (payload.stack_warnings || []).some((w) => w.startsWith("no heights"));
    setStatus(`Applied ${payload.applied} tech layer(s)${noHeights ? "; colours only, no d25/*.lyd25 for heights" : ""}`);
  });
}
document.getElementById("file-tech").addEventListener("change", (e) => {
  const file = e.target.files[0];
  e.target.value = "";
  if (!file || !techTargetId) return;
  attachTech(`Attaching ${file.name}`, (id) => api.attachTechnology(id, file));
});
// A folder sends only its KLayout files, as text with their paths in it; the rest (GDS libraries) stays on disk.
document.getElementById("folder-tech").addEventListener("change", (e) => {
  const picked = [...e.target.files].filter((file) => /\.(lyt|lyp|lyd25)$/i.test(file.name));
  e.target.value = "";
  if (!techTargetId) return;
  attachTech("Attaching the technology folder", async (id) => api.attachTechnologyFolder(id, await Promise.all(
    picked.map(async (file) => ({ path: file.webkitRelativePath || file.name, text: await file.text() })))));
});

// Foldable side panels: the Components palette on the left, the Inspector and Outline on the right. Each collapses
// to a thin edge tab; the choice persists.
function panelFold(collapseId, revealId, layoutClass, key) {
  const layout = document.querySelector(".layout");
  const collapseBtn = document.getElementById(collapseId);
  const revealBtn = document.getElementById(revealId);
  if (!layout || !collapseBtn || !revealBtn) return;
  const setOpen = (open) => {
    layout.classList.toggle(layoutClass, !open);
    try { localStorage.setItem(key, open ? "0" : "1"); } catch (_) {}
  };
  collapseBtn.addEventListener("click", () => setOpen(false));
  revealBtn.addEventListener("click", () => setOpen(true));
  let stored = null;
  try { stored = localStorage.getItem(key); } catch (_) {}
  setOpen(stored !== "1");
}
panelFold("palette-collapse", "palette-reveal", "palette-collapsed", "od-palette-collapsed");
panelFold("inspector-collapse", "inspector-reveal", "inspector-collapsed", "od-inspector-collapsed");

// Resizable inspector: drag the divider; width persists in localStorage.
(function inspectorResize() {
  const resizer = document.getElementById("insp-resizer");
  const root = document.documentElement;
  const saved = Number(localStorage.getItem("od-insp-w"));
  if (saved >= 220) root.style.setProperty("--insp-w", `${saved}px`);
  let dragging = false;
  const setW = (px) => {
    const w = Math.max(220, Math.min(640, px));
    root.style.setProperty("--insp-w", `${w}px`);
    return w;
  };
  resizer.addEventListener("mousedown", (e) => {
    dragging = true; resizer.classList.add("active");
    document.body.style.cursor = "col-resize"; document.body.style.userSelect = "none";
    e.preventDefault();
  });
  window.addEventListener("mousemove", (e) => { if (dragging) setW(window.innerWidth - e.clientX); });
  window.addEventListener("mouseup", () => {
    if (!dragging) return;
    dragging = false; resizer.classList.remove("active");
    document.body.style.cursor = ""; document.body.style.userSelect = "";
    const cur = getComputedStyle(root).getPropertyValue("--insp-w").trim();
    localStorage.setItem("od-insp-w", parseInt(cur, 10) || 292);
  });
})();

els.undo.addEventListener("click", undo);
els.redo.addEventListener("click", redo);
document.getElementById("btn-fit").addEventListener("click", () => { if (in3d()) post3d({ type: "optodraw-fit" }); else canvas.fit(); });
document.getElementById("btn-save-as").addEventListener("click", newWs);
document.getElementById("btn-scene").addEventListener("click", openSceneSettings);
document.getElementById("btn-presets").addEventListener("click", openPresets);

// zoom cluster drives whichever view is active: 2D canvas or the 3D iframe camera
function in3d() { return !els.view3d.hidden; }
function post3d(msg) {
  const win = els.view3d.contentWindow;
  if (win) win.postMessage(msg, "*");
}
document.getElementById("btn-zoom-in").addEventListener("click", () => {
  if (in3d()) post3d({ type: "optodraw-zoom", factor: 1 / 1.3 });
  else canvas.zoomIn();
});
document.getElementById("btn-zoom-out").addEventListener("click", () => {
  if (in3d()) post3d({ type: "optodraw-zoom", factor: 1.3 });
  else canvas.zoomOut();
});
document.getElementById("btn-zoom-reset").addEventListener("click", () => {
  if (in3d()) post3d({ type: "optodraw-fit" });
  else canvas.fit();
});

els.snap.addEventListener("click", () => {
  snapOn = !snapOn;
  els.snap.classList.toggle("active", snapOn);
  els.snap.setAttribute("aria-pressed", String(snapOn));
  syncSnapChip();
});

// Grid visibility toggle + spacing control (scene units), shared with snapping.
function syncGridUI() {
  els.snap.classList.toggle("active", snapOn);
  els.snap.setAttribute("aria-pressed", String(snapOn));
  if (els.grid) {
    els.grid.classList.toggle("active", gridVisible);
    els.grid.setAttribute("aria-pressed", String(gridVisible));
  }
  if (els.gridSize) els.gridSize.value = String(gridSize);
  canvas.setGrid({ size: gridSize, visible: gridVisible });
  syncSnapChip();
}
if (els.grid) {
  els.grid.addEventListener("click", () => {
    gridVisible = !gridVisible;
    syncGridUI();
  });
}
if (els.gridSize) {
  els.gridSize.addEventListener("change", () => {
    const v = Number(els.gridSize.value);
    if (v > 0) gridSize = v;
    syncGridUI();
  });
}
syncGridUI();

async function refreshPorts() {
  try {
    const { ports } = await api.ports();
    canvas.setPorts(ports);
  } catch (_) { canvas.setPorts({}); }
}

async function setConnectMode(on) {
  connectMode = on;
  connectAnchor = null;
  waypoints = [];
  freePts = [];
  canvas.showFreePreview(null);
  els.connect.classList.toggle("active", on);
  els.connect.setAttribute("aria-pressed", String(on));
  if (on) {
    await refreshPorts();
    canvas.setMode("connect");
    setStatus(`${routingType.label}: click a port, then waypoints / a target port (Esc to exit)`);
  } else {
    canvas.setMode("select");
    setStatus("");
  }
}
els.connect.addEventListener("click", () => setConnectMode(!connectMode));

// Trace a physical ray from a source (reflects at mirrors, refracts at lenses).
let sourceTypes = null; // Set of component types flagged source:true in the catalog
let catalogCache = null; // raw catalog dict, reused by the command palette
function isSource(entry) {
  if (!entry) return false;
  if (sourceTypes) return sourceTypes.has(entry.type);
  return /Laser|Lamp|FiberLaser/i.test(entry.type || ""); // pre-boot fallback
}
// Trace is a MODE, like Route: on = every source emits a live ray bundle that
// keeps re-tracing as you move optics into the light; off = all traces removed.
const traceBtn = document.getElementById("btn-trace");
const tracedBeams = (spec) => ((spec && spec.beams) || []).filter((b) => b.traced_from);
function syncTraceButton() {
  const on = tracedBeams(currentSpec).length > 0;
  traceBtn.classList.toggle("active", on);
  traceBtn.setAttribute("aria-pressed", String(on));
}
traceBtn.addEventListener("click", () => {
  if (tracedBeams(currentSpec).length) {
    applySpec("Light off", (next) => { next.beams = (next.beams || []).filter((b) => !b.traced_from); });
    return;
  }
  const sources = (currentSpec?.components || []).filter(isSource);
  if (!sources.length) { setStatus("Add a light source (laser / lamp) first", true); return; }
  withStatus("Switching the light on", async () => {
    let payload = null;
    for (const source of sources) {
      try { payload = await api.traceBeam(source.id); } catch (_) { /* portless source */ }
    }
    if (!payload) { setStatus("No source could emit (missing ports?)", true); return; }
    commit(payload);
    setStatus(`Light on — ${sources.length} source${sources.length > 1 ? "s" : ""} emitting; move optics into the beam`);
  });
});

// Make a floating stage panel draggable by its header (shared by Links + xsection).
function makePanelDraggable(panel, head) {
  let sx, sy, ox, oy, dragging = false;
  head.addEventListener("mousedown", (e) => {
    if (e.target.closest(".rp-iconbtn")) return; // let header buttons click
    dragging = true;
    sx = e.clientX; sy = e.clientY;
    const r = panel.getBoundingClientRect();
    const stage = panel.parentElement.getBoundingClientRect();
    ox = r.left - stage.left; oy = r.top - stage.top;
    e.preventDefault();
  });
  window.addEventListener("mousemove", (e) => {
    if (!dragging) return;
    panel.style.left = `${Math.max(0, ox + e.clientX - sx)}px`;
    panel.style.right = "auto";
    panel.style.top = `${Math.max(0, oy + e.clientY - sy)}px`;
  });
  window.addEventListener("mouseup", () => { dragging = false; });
}

// -- text routing panel: define connections by typing port links -----------
const routePanel = document.getElementById("route-panel");
const routeTextEl = document.getElementById("route-text");
const routeErrorsEl = document.getElementById("route-errors");
const routeRefEl = document.getElementById("route-ref");
const btnTextRoute = document.getElementById("btn-text-route");

function setRoutePanel(show) {
  routePanel.hidden = !show;
  btnTextRoute.classList.toggle("active", show);
  btnTextRoute.setAttribute("aria-pressed", String(show));
}
btnTextRoute.addEventListener("click", () => setRoutePanel(routePanel.hidden));
document.getElementById("route-close").addEventListener("click", () => setRoutePanel(false));
document.getElementById("route-collapse").addEventListener("click", () =>
  routePanel.classList.toggle("collapsed"));

// GUI wavelength picker — sets the color for new beams (Connect + Links + DSL default).
const routeWl = createWavelengthPicker(activeWavelength, (nm) => { activeWavelength = nm; });
document.getElementById("route-wl").appendChild(routeWl.el);

// Drag the panel by its header so it can be moved out of the way.
makePanelDraggable(routePanel, document.getElementById("route-head"));

document.getElementById("route-apply").addEventListener("click", () =>
  withStatus("Routing", async () => {
    const payload = await api.routeText(routeTextEl.value, activeWavelength);
    commit(payload);
    routeErrorsEl.textContent = (payload.errors || []).join("\n");
    setStatus(`Linked ${payload.created} connection(s)`);
  }));

document.getElementById("route-ref-toggle").addEventListener("click", async () => {
  if (!routeRefEl.hidden) { routeRefEl.hidden = true; return; }
  try {
    const { ports } = await api.ports();
    const lines = [];
    for (const c of currentSpec?.components || []) {
      const names = (ports[c.id] || []).map((p) => p.name);
      if (names.length) lines.push(`<div class="rp-comp">${c.id}</div>${names.map((n) => `&nbsp;&nbsp;.${n}`).join("")}`);
    }
    routeRefEl.innerHTML = lines.join("") || "(no ports in scene)";
  } catch (_) { routeRefEl.innerHTML = "(failed to load ports)"; }
  routeRefEl.hidden = false;
});

// -- GDS cross-section panel: cut the selected GDSModel and show the cut in one of four looks -------
const xsPanel = document.getElementById("xs-panel");
const xsTop = document.getElementById("xs-top");
const xsCross = document.getElementById("xs-cross");
const xsFigure = document.getElementById("xs-figure");
const xsLooks = document.getElementById("xs-looks");
const xsFindings = document.getElementById("xs-findings");
const xsBusy = document.getElementById("xs-busy");
const xsScan = document.getElementById("xs-scan");
const xsExpand = document.getElementById("xs-expand");
const XS_NAMES = { schematic: "schematic", sem: "SEM image", slab: "3D slab", top: "top view" };
let xsCrossData = "", xsTopSvg = ""; // what Save writes: the figure (SVG, PNG data URL or page) and the layout
let xsLook = "schematic", xsFormat = "svg", xsLast = null, xsComponent = null;
let xsLineFile = null; // the newest cut in the GDS file's frame, {id, line}, for the Layout view's ruler
const xsOpts = { // each look's options, as the server takes them
  schematic: { z_scale: null },
  sem: { mark: true, seed: 0 },
  slab: { depth: null, cutaway: true },
  top: { stage: "chip", tilt: 40, rotation: 0, mark: true, seed: 0 },
};

// The request options of a look. An image is rendered at the figure's size on screen; Save asks for the full size.
function xsLookOptions(look, full = false) {
  const opts = { ...xsOpts[look] };
  if (look === "sem" || look === "top") {
    const onScreen = Math.round((xsFigure.clientWidth || 600) * (window.devicePixelRatio || 1));
    opts.width_px = full ? 2000 : Math.max(400, Math.min(1600, onScreen));
  }
  for (const key of Object.keys(opts)) if (opts[key] === null) delete opts[key];
  return opts;
}
function markXsLook() {
  xsLooks.querySelectorAll("button").forEach((b) => b.classList.toggle("active", b.dataset.look === xsLook));
  document.querySelectorAll("#xs-options .xs-opt").forEach((row) => { row.hidden = row.dataset.for !== xsLook; });
}
function xsRerender() { if (xsLast) renderCrossSection(xsLast.id, { ...xsLast.opts, live: false }); }
xsLooks.querySelectorAll("button").forEach((b) => b.addEventListener("click", () => {
  xsLook = b.dataset.look; markXsLook(); xsRerender();
}));

// each look's option row
document.getElementById("xs-zscale").addEventListener("change", (e) => {
  xsOpts.schematic.z_scale = Number(e.target.value) || null; xsRerender();
});
document.getElementById("xs-sem-mark").addEventListener("change", (e) => { xsOpts.sem.mark = e.target.checked; xsRerender(); });
document.getElementById("xs-sem-noise").addEventListener("click", () => { xsOpts.sem.seed += 1; xsRerender(); });
document.getElementById("xs-depth").addEventListener("change", (e) => {
  xsOpts.slab.depth = Number(e.target.value) || null; xsRerender();
});
document.getElementById("xs-cutaway").addEventListener("change", (e) => { xsOpts.slab.cutaway = e.target.checked; xsRerender(); });
document.getElementById("xs-top-mark").addEventListener("change", (e) => { xsOpts.top.mark = e.target.checked; xsRerender(); });
document.querySelectorAll("#xs-stage button").forEach((b) => b.addEventListener("click", () => {
  xsOpts.top.stage = b.dataset.stage;
  document.querySelectorAll("#xs-stage button").forEach((other) => other.classList.toggle("active", other === b));
  xsRerender();
}));
for (const [id, key] of [["xs-tilt", "tilt"], ["xs-rot", "rotation"]]) {
  const input = document.getElementById(id), shown = document.getElementById(`${id}-val`);
  input.addEventListener("input", () => { shown.textContent = `${input.value}°`; });
  input.addEventListener("change", () => { xsOpts.top[key] = Number(input.value); xsRerender(); }); // a tilt reuses the cuts
}

// the cut: along the Layout view's ruler, or a vertical cut scanned across the part
document.getElementById("xs-cut-ruler").addEventListener("click", async () => {
  const id = layoutView.shown();
  const line = id ? await layoutView.cutLine() : null;
  if (!line) { setStatus("Draw a ruler first (M, then two clicks)"); return; }
  renderCrossSection(id, { line, frame: "file", label: "Ruler" });
});
let xsScanTimer = null;
xsScan.addEventListener("input", () => { // drag: silent updates of the schematic; release: the look asked for
  clearTimeout(xsScanTimer);
  xsScanTimer = setTimeout(() => {
    if (xsComponent) renderCrossSection(xsComponent, { pct: Number(xsScan.value), label: "A-A'", live: true });
  }, 70);
});
xsScan.addEventListener("change", () => {
  if (xsComponent) renderCrossSection(xsComponent, { pct: Number(xsScan.value), label: "A-A'" });
});

// the header: drag, show large, minimize, close
makePanelDraggable(xsPanel, document.getElementById("xs-head"));
let xsPlace = null; // where the panel stood before it was shown large
function setXsExpanded(on) {
  if (on === xsPanel.classList.contains("expanded")) return;
  if (on) {
    xsPlace = { left: xsPanel.style.left, top: xsPanel.style.top, right: xsPanel.style.right, width: xsPanel.style.width };
    Object.assign(xsPanel.style, { left: "", top: "", right: "", width: "" });
  } else if (xsPlace) Object.assign(xsPanel.style, xsPlace);
  xsPanel.classList.toggle("expanded");
  xsExpand.setAttribute("aria-pressed", String(on));
  if (xsLook === "sem" || xsLook === "top") xsRerender(); // the image at its new size
}
xsExpand.addEventListener("click", () => setXsExpanded(!xsPanel.classList.contains("expanded")));
window.addEventListener("keydown", (e) => { if (e.key === "Escape") setXsExpanded(false); });
document.getElementById("xs-close").addEventListener("click", () => { setXsExpanded(false); xsPanel.hidden = true; });
document.getElementById("xs-collapse").addEventListener("click", () => xsPanel.classList.toggle("collapsed"));

// save: the full-size image (not the one sized to the panel), the SVG or the slab page; and the layout
document.getElementById("xs-download-cross").addEventListener("click", () => withStatus("Saving the figure", async () => {
  if (!xsLast) return;
  const name = `${sceneName()}_cross_section`;
  if (xsFormat === "png") {
    const res = await api.gdsCrossSection(xsLast.id, { ...xsLast.opts, live: false, look: xsLook, ...xsLookOptions(xsLook, true) });
    const bytes = Uint8Array.from(atob(res.cross_section.split(",")[1]), (c) => c.charCodeAt(0));
    download(`${name}_${xsLook}.png`, bytes, "image/png");
  } else if (xsFormat === "html") download(`${name}_slab.html`, new TextEncoder().encode(xsCrossData), "text/html");
  else download(`${name}.svg`, new TextEncoder().encode(xsCrossData), "image/svg+xml");
}));
document.getElementById("xs-download-top").addEventListener("click", () =>
  xsTopSvg && download(`${sceneName()}_layout.svg`, new TextEncoder().encode(xsTopSvg), "image/svg+xml"));

// progress: a line under the figure counts the seconds; the last figure stays, dimmed, until the new one comes
let xsBusyTimer = null;
function xsSetBusy(text) {
  clearInterval(xsBusyTimer);
  xsFigure.classList.toggle("loading", Boolean(text));
  xsBusy.hidden = !text;
  if (!text) return;
  const started = performance.now();
  const tick = () => { xsBusy.textContent = `${text} ${Math.round((performance.now() - started) / 1000)} s`; };
  tick();
  xsBusyTimer = setInterval(tick, 1000);
}

let xsSeq = 0; // guards against out-of-order responses while dragging or scanning
async function applyCrossSection(id, opts) {
  xsLast = { id, opts };
  xsComponent = id;
  // the images and the 3D slab take a moment: a drag updates only the schematic, the release renders
  if (opts && opts.live && xsLook !== "schematic") return;
  const seq = ++xsSeq;
  xsPanel.hidden = false;
  if (!(opts && opts.live)) xsSetBusy(`Rendering the ${XS_NAMES[xsLook]}...`);
  let res;
  try {
    res = await api.gdsCrossSection(id, { ...opts, look: xsLook, ...xsLookOptions(xsLook) });
  } finally {
    if (seq === xsSeq) xsSetBusy("");
  }
  if (seq !== xsSeq) return; // a newer request already landed
  xsLooks.querySelector('[data-look="sem"]').hidden = !res.looks.includes("sem");
  xsLooks.querySelector('[data-look="top"]').hidden = !res.looks.includes("top");
  xsTopSvg = res.top_view; xsCrossData = res.cross_section; xsFormat = res.format;
  xsTop.innerHTML = res.top_view;
  xsCross.innerHTML = "";
  if (res.format === "png") {
    const img = new Image();
    img.alt = res.look === "top" ? "SEM-like top view (a render, not a measurement)"
      : "SEM-like cross-section (a render, not a measurement)";
    img.src = res.cross_section;
    xsCross.appendChild(img);
  } else if (res.format === "html") {
    const frame = document.createElement("iframe");
    frame.className = "xs-frame"; frame.title = "Cut 3D slab";
    frame.sandbox = "allow-scripts";
    frame.srcdoc = res.cross_section;
    xsCross.appendChild(frame);
  } else xsCross.innerHTML = res.cross_section;
  xsFindings.textContent = (res.findings || []).join("\n");
  const part = gdsParts().find((p) => p.id === id);
  if (res.line_file && part) {
    xsLineFile = { file: part.file, line: res.line_file };
    if (inLayout() && layoutView.wanted().file === part.file) layoutView.showCut(res.line_file);
  }
  const cut = `${res.cut.label}, ${res.cut.length.toFixed(1)} µm at ${res.cut.angle.toFixed(0)}°`;
  document.getElementById("xs-sub").textContent = opts && opts.line ? cut : `${cut}, x = ${res.cut.x.toFixed(1)}`;
  return res;
}

function renderCrossSection(id, opts) {
  // live updates (an end dragged, the scan) run silently; a release shows the status line
  if (opts && opts.live) { applyCrossSection(id, opts).catch(() => {}); return; }
  if (opts && opts.pct !== undefined) xsScan.value = String(opts.pct);
  withStatus(`Rendering the ${XS_NAMES[xsLook]}`, async () => {
    const res = await applyCrossSection(id, opts);
    if (res) setStatus(`Cross-section ${res.cut.label} rendered in ${res.elapsed} s`);
  });
}

// -- Simulate panel (analytical physics: resonance / transfer / guided / polarization) --
const simPanel = document.getElementById("sim-panel");
const simPlot = document.getElementById("sim-plot");
const simControls = document.getElementById("sim-controls");
const simKindsEl = document.getElementById("sim-kinds");
makePanelDraggable(simPanel, document.getElementById("sim-head"));
document.getElementById("sim-close").addEventListener("click", () => { simPanel.hidden = true; });
document.getElementById("sim-collapse").addEventListener("click", () => simPanel.classList.toggle("collapsed"));

let simState = null;

async function onSimulateClick() {
  const id = canvas.selectedId;
  if (id) {
    let opts = null;
    try { opts = await api.simulateOptions(id); } catch (_) { opts = null; }
    if (opts && opts.kinds && opts.kinds.length) { openComponentSim(id, opts); return; }
  }
  openPolarizationSim();
}

function openComponentSim(id, opts) {
  simState = { mode: "component", id, kind: opts.kinds[0], params: {} };
  document.getElementById("sim-sub").textContent = `— ${selLabel(id)}`;
  simKindsEl.innerHTML = "";
  if (opts.kinds.length > 1) {
    for (const k of opts.kinds) {
      const tab = document.createElement("button");
      tab.className = "sim-kind-tab" + (k === simState.kind ? " active" : "");
      tab.textContent = (opts.labels && opts.labels[k]) || k;
      tab.addEventListener("click", () => {
        simState.kind = k;
        simState.params = {};
        simKindsEl.querySelectorAll(".sim-kind-tab").forEach((b) => b.classList.toggle("active", b === tab));
        runSim();
      });
      simKindsEl.appendChild(tab);
    }
  }
  simPanel.hidden = false;
  runSim();
}

function openPolarizationSim() {
  simState = { mode: "polarization", params: { input: "H" } };
  document.getElementById("sim-sub").textContent = "— polarization chain";
  simKindsEl.innerHTML = "";
  simPanel.hidden = false;
  runSim();
}

function runSim() {
  if (!simState) return;
  withStatus("Simulating", async () => {
    const res = simState.mode === "polarization"
      ? await api.simulatePolarization(simState.params)
      : await api.simulate(simState.id, simState.kind, simState.params);
    simPlot.innerHTML = res.plot_svg;
    renderSimControls(res);
  });
}

function renderSimControls(res) {
  simControls.innerHTML = "";
  if (res.input_options) {
    const row = document.createElement("div");
    row.className = "sim-ctl";
    const lab = document.createElement("label");
    lab.textContent = "Input";
    const sel = document.createElement("select");
    for (const o of res.input_options) {
      const opt = document.createElement("option");
      opt.value = o;
      opt.textContent = o;
      if (o === res.input) opt.selected = true;
      sel.appendChild(opt);
    }
    sel.addEventListener("change", () => { simState.params.input = sel.value; runSim(); });
    row.append(lab, sel);
    simControls.appendChild(row);
  }
  for (const c of res.controls || []) {
    const row = document.createElement("div");
    row.className = "sim-ctl";
    const lab = document.createElement("label");
    lab.textContent = c.label;
    const slider = document.createElement("input");
    slider.type = "range";
    slider.min = c.min;
    slider.max = c.max;
    slider.step = c.step;
    slider.value = c.value;
    const val = document.createElement("span");
    val.className = "sim-val";
    val.textContent = Number(c.value).toFixed(2);
    slider.addEventListener("input", () => { val.textContent = Number(slider.value).toFixed(2); });
    slider.addEventListener("change", () => { simState.params[c.name] = Number(slider.value); runSim(); });
    row.append(lab, slider, val);
    simControls.appendChild(row);
  }
}

document.getElementById("btn-simulate").addEventListener("click", onSimulateClick);

// -- Generate dialog (parameterized meshes / arrays / chains) --
function openGenerate() {
  openModal((card, close) => {
    card.classList.add("generate-modal");
    const head = document.createElement("div");
    head.className = "od-modal-head";
    head.textContent = "Generate";
    const body = document.createElement("div");
    body.className = "od-modal-body";
    const genRow = document.createElement("div");
    genRow.className = "gen-row";
    const genLab = document.createElement("label");
    genLab.className = "od-modal-label";
    genLab.textContent = "Generator";
    const genSel = document.createElement("select");
    genSel.className = "od-modal-input";
    genRow.append(genLab, genSel);
    const fields = document.createElement("div");
    fields.className = "gen-fields";
    body.append(genRow, fields);
    const foot = document.createElement("div");
    foot.className = "od-modal-foot";
    const cancel = document.createElement("button");
    cancel.className = "od-btn od-ghost";
    cancel.textContent = "Cancel";
    const go = document.createElement("button");
    go.className = "od-btn od-primary";
    go.textContent = "Generate";
    foot.append(cancel, go);
    card.append(head, body, foot);

    let specs = [];
    cancel.addEventListener("click", () => close(null));

    function renderFields(gen) {
      fields.innerHTML = "";
      for (const f of gen.fields || []) {
        const row = document.createElement("div");
        row.className = "gen-row";
        const lab = document.createElement("label");
        lab.className = "od-modal-label";
        lab.textContent = f.label;
        let input;
        if (f.type === "checkbox") {
          input = document.createElement("input");
          input.type = "checkbox";
          input.checked = !!f.value;
        } else if (f.type === "select") {
          input = document.createElement("select");
          input.className = "od-modal-input";
          for (const o of f.options || []) {
            const opt = document.createElement("option");
            opt.value = o;
            opt.textContent = o;
            if (o === f.value) opt.selected = true;
            input.appendChild(opt);
          }
        } else {
          input = document.createElement("input");
          input.type = "number";
          input.className = "od-modal-input";
          if (f.min != null) input.min = f.min;
          if (f.max != null) input.max = f.max;
          if (f.step != null) input.step = f.step;
          input.value = f.value;
        }
        input.dataset.key = f.key;
        input.dataset.type = f.type;
        row.append(lab, input);
        fields.appendChild(row);
      }
    }

    api.generators().then(({ generators }) => {
      specs = generators || [];
      for (const g of specs) {
        const o = document.createElement("option");
        o.value = g.name;
        o.textContent = g.label;
        genSel.appendChild(o);
      }
      if (specs.length) renderFields(specs[0]);
    }).catch(() => { fields.textContent = "Couldn't load generators."; });
    genSel.addEventListener("change", () => {
      const g = specs.find((s) => s.name === genSel.value);
      if (g) renderFields(g);
    });

    go.addEventListener("click", () => {
      const name = genSel.value;
      if (!name) return;
      const params = {};
      fields.querySelectorAll("[data-key]").forEach((el) => {
        const t = el.dataset.type;
        params[el.dataset.key] = t === "checkbox" ? el.checked : t === "number" ? Number(el.value) : el.value;
      });
      close(null);
      withStatus(`Generating ${name}`, async () => {
        loadWorkspace(await api.generate(name, params));
        requestAnimationFrame(() => canvas.fit());
      });
    });
  });
}
document.getElementById("btn-generate").addEventListener("click", openGenerate);

// -- Animate dialog (selected device → animated GIF) --
async function openAnimate() {
  const id = canvas.selectedId;
  let recipes = [{ name: "__flow__", label: "Light flow (whole scene)" }];
  if (id) {
    try { recipes = recipes.concat((await api.animationRecipes(id)).recipes || []); } catch (_) { }
  }
  openModal((card, close) => {
    card.classList.add("generate-modal");
    const head = document.createElement("div");
    head.className = "od-modal-head";
    head.textContent = "Animate → GIF";
    const body = document.createElement("div");
    body.className = "od-modal-body";
    const mk = (label, control) => {
      const row = document.createElement("div");
      row.className = "gen-row";
      const lab = document.createElement("label");
      lab.className = "od-modal-label";
      lab.textContent = label;
      row.append(lab, control);
      return row;
    };
    const recipeSel = document.createElement("select");
    recipeSel.className = "od-modal-input";
    for (const rc of recipes) {
      const o = document.createElement("option");
      o.value = rc.name;
      o.textContent = rc.label;
      recipeSel.appendChild(o);
    }
    const steps = document.createElement("input");
    steps.type = "number";
    steps.className = "od-modal-input";
    steps.min = 2; steps.max = 24; steps.step = 1; steps.value = 8;
    const fps = document.createElement("input");
    fps.type = "number";
    fps.className = "od-modal-input";
    fps.min = 1; fps.max = 24; fps.step = 1; fps.value = 6;
    body.append(mk("Recipe", recipeSel), mk("Steps", steps), mk("FPS", fps));
    const foot = document.createElement("div");
    foot.className = "od-modal-foot";
    const cancel = document.createElement("button");
    cancel.className = "od-btn od-ghost";
    cancel.textContent = "Cancel";
    const go = document.createElement("button");
    go.className = "od-btn od-primary";
    go.textContent = "Export GIF";
    foot.append(cancel, go);
    card.append(head, body, foot);
    cancel.addEventListener("click", () => close(null));
    go.addEventListener("click", () => {
      const recipe = recipeSel.value;
      close(null);
      withStatus("Rendering GIF (this can take a few seconds)", async () => {
        const params = { steps: Number(steps.value), fps: Number(fps.value) };
        const blob = recipe === "__flow__" ? await api.animationFlow(params) : await api.animationGif(id, recipe, params);
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `${recipe === "__flow__" ? "light_flow" : recipe}.gif`;
        a.click();
        URL.revokeObjectURL(url);
        setStatus("GIF exported");
      });
    });
  });
}
// -- Animate: master toggle + control menu (drives the 3D light player, window.odLight) -----
// The toggle turns the light off entirely: the light, the heat and the RF maps, not only a pause.
// The menu holds the look, play, speed and time, Play tour, Record video and the GIF export.
const animBtn = document.getElementById("btn-animate");
const animMenuBtn = document.getElementById("btn-animate-menu");
const animMenu = document.getElementById("animate-menu");
const animState = { enabled: false, playing: true, speed: 1, look: "light", time: 0 }; // off until clicked
let tourOn = false; // the 3D page plays the tour: its light is on until the tour ends

function postAnim(action, value) { post3d({ type: "optodraw-anim", action, value }); }

// Push the whole state after the iframe (re)loads so a re-render can't reset it.
async function syncAnimTo3d() {
  // The page starts with no light payload: fetch it with the items first, then turn the light on.
  if (animState.enabled) await refresh3D();
  postAnim("enabled", animState.enabled);
  if (!animState.enabled) return;
  postAnim("play", animState.playing);
  postAnim("speed", animState.speed);
  postAnim("look", animState.look);
}

function syncAnimButton() {
  const on = animState.enabled || tourOn;
  animBtn.classList.toggle("active", on);
  animBtn.setAttribute("aria-pressed", String(on));
}

animBtn.addEventListener("click", () => {
  if (tourOn) { postAnim("tour", false); return; } // stop the tour: the page gives the light back as it was
  animState.enabled = !animState.enabled;
  syncAnimButton();
  if (animState.enabled && !in3d()) { setView("3d"); return; } // ready-handshake syncs state
  if (animState.enabled) syncAnimTo3d();
  else postAnim("enabled", false);
  setStatus(animState.enabled ? "Animation on" : "Animation off");
});

function buildAnimMenu() {
  animMenu.innerHTML = "";
  const item = (label, onClick, active) => {
    const el = document.createElement("div");
    el.className = "route-menu-item" + (active ? " active" : "");
    el.textContent = label;
    el.addEventListener("click", (e) => { e.stopPropagation(); onClick(); buildAnimMenu(); });
    animMenu.appendChild(el);
    return el;
  };
  const slider = (label, min, max, step, value, onInput) => {
    const row = document.createElement("label");
    row.className = "anim-menu-row";
    const span = document.createElement("span");
    span.textContent = label;
    const input = document.createElement("input");
    input.type = "range"; input.min = min; input.max = max; input.step = step; input.value = value;
    input.addEventListener("input", () => onInput(Number(input.value)));
    input.addEventListener("click", (e) => e.stopPropagation());
    row.append(span, input);
    animMenu.appendChild(row);
  };
  const lookRow = document.createElement("label");
  lookRow.className = "anim-menu-row";
  lookRow.innerHTML = "<span>Look</span>";
  const lookSel = document.createElement("select");
  for (const [v, t] of [["light", "Light"], ["field", "Field"]]) {
    const o = document.createElement("option");
    o.value = v; o.textContent = t;
    if (v === animState.look) o.selected = true;
    lookSel.appendChild(o);
  }
  lookSel.addEventListener("change", () => { animState.look = lookSel.value; postAnim("look", lookSel.value); });
  lookSel.addEventListener("click", (e) => e.stopPropagation());
  lookRow.appendChild(lookSel);
  animMenu.appendChild(lookRow);
  item(animState.playing ? "Pause" : "Play", () => {
    animState.playing = !animState.playing;
    postAnim("play", animState.playing);
  }, animState.playing);
  slider("Speed", 0.25, 4, 0.05, animState.speed, (v) => { animState.speed = v; postAnim("speed", v); });
  slider("Time", 0, 1000, 1, animState.time, (v) => { animState.time = v; postAnim("time", v); });
  const divider = document.createElement("div");
  divider.className = "ws-menu-divider";
  animMenu.appendChild(divider);
  item("Play tour", () => { toggleAnimMenu(false); in3dThen(playTour); }, false);
  item("Record video", () => { toggleAnimMenu(false); recordVideo(); }, false);
  item("Export GIF…", () => { toggleAnimMenu(false); openAnimate(); }, false);
}

// Play tour: the page plays the tour with the light on and gives the light back as it was when the tour ends.
async function playTour() {
  setStatus("Preparing the tour");
  if (!(await refresh3D(true))) return; // the light payload with the drive tables of the tour's driven stops
  postAnim("tour", true);
  setStatus("Tour: drag the view to stop it");
}

// Record video: the server renders the scene's own tour as an MP4 in a worker thread. The status line shows the
// frames done; the file downloads when the job is done.
function videoProgressText(job) {
  if (!job || !job.total) return "Recording video: starting";
  return `Recording video: ${Math.round((100 * job.done) / job.total)} %`;
}

let videoRecording = false;
async function recordVideo() {
  if (videoRecording) { setStatus("A video is already being recorded", true); return; }
  videoRecording = true;
  try {
    setStatus("Recording video: starting");
    const start = await fetch("/api/render/video", {
      method: "POST", headers: changeHeaders({ "Content-Type": "application/json" }), body: "{}",
    });
    let started = await start.json().catch(() => ({}));
    if (start.status === 409) {                  // a job runs (maybe from before a reload): follow its progress
      const running = await (await fetch("/api/render/video")).json();
      if (!running.id) throw new Error(started.detail || "a video is already being recorded");   // or another tab
      started = running;
    } else if (!start.ok) throw new Error(started.detail || `HTTP ${start.status}`);
    let job = { done: 0, total: 0 };
    for (;;) {
      const res = await fetch(`/api/render/video/${started.id}`);
      job = await res.json();
      if (!res.ok) throw new Error(job.detail || `HTTP ${res.status}`);
      if (job.state === "failed") throw new Error(job.error || "the video failed");
      if (job.state === "done") break;
      els.status.textContent = videoProgressText(job);
      els.status.style.color = "var(--text-3)";
      await new Promise((resolve) => setTimeout(resolve, 700));
    }
    const file = await fetch(job.url);
    if (!file.ok) throw new Error(`HTTP ${file.status}`);
    const blob = await file.blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `${sceneName()}-tour${job.filename.endsWith(".webm") ? ".webm" : ".mp4"}`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 4000);
    setStatus("Video saved");
  } catch (err) {
    setStatus(`Record video failed: ${err.message}`, true);
  } finally {
    videoRecording = false;
  }
}

function toggleAnimMenu(open) {
  const show = open === undefined ? animMenu.hidden : open;
  if (show) buildAnimMenu();
  animMenu.hidden = !show;
  animMenuBtn.setAttribute("aria-expanded", String(show));
}
animMenuBtn.addEventListener("click", (e) => {
  e.stopPropagation();
  if (!in3d()) { setView("3d"); }
  toggleAnimMenu();
});
document.addEventListener("click", (e) => {
  if (!animMenu.hidden && !e.target.closest("#animate-menu") && e.target !== animMenuBtn) toggleAnimMenu(false);
});
syncAnimButton();

// -- View: the 3D view's camera, world, table colour, labels, fullscreen and photoreal render ---------------
// The page draws no controls inside the editor; this menu drives it through the bridge ("optodraw-view").
const view3dBtn = document.getElementById("btn-view3d-menu");
const view3dMenu = document.getElementById("view3d-menu");
const viewState = { world: "light", table: null }; // re-sent after the 3D page reloads
const CAMERAS = [["isometric", "Isometric"], ["top", "Top"], ["front", "Front"], ["side", "Side"],
  ["cross_section", "Cross-section"], ["free_space_table", "Free-space table"]];
const WORLDS = [["light", "Light"], ["dark", "Dark"], ["none", "None (transparent)"]];

function postView(action, value) { post3d({ type: "optodraw-view", action, value }); }
function syncViewTo3d() {
  postView("world", viewState.world);
  if (viewState.table) postView("table", viewState.table);
}
function in3dThen(fn) { // the 3D page must be up before it takes an order
  if (in3d()) { fn(); return; }
  setView("3d");
  els.view3d.addEventListener("load", () => setTimeout(fn, 300), { once: true });
}

function buildView3dMenu() {
  view3dMenu.innerHTML = "";
  const head = (text) => {
    const el = document.createElement("div");
    el.className = "ws-menu-header";
    el.textContent = text;
    view3dMenu.appendChild(el);
  };
  const item = (label, onClick, active) => {
    const el = document.createElement("div");
    el.className = "route-menu-item" + (active ? " active" : "");
    el.textContent = label;
    el.addEventListener("click", (e) => { e.stopPropagation(); onClick(); buildView3dMenu(); });
    view3dMenu.appendChild(el);
  };
  const divider = () => {
    const el = document.createElement("div");
    el.className = "ws-menu-divider";
    view3dMenu.appendChild(el);
  };
  head("Camera");
  for (const [preset, label] of CAMERAS) item(label, () => postView("camera", preset), false);
  divider();
  head("World");
  for (const [world, label] of WORLDS) item(label, () => { viewState.world = world; postView("world", world); }, viewState.world === world);
  const row = document.createElement("label");
  row.className = "anim-menu-row";
  row.innerHTML = "<span>Table colour</span>";
  const color = document.createElement("input");
  color.type = "color"; color.value = viewState.table || "#dde3ea";
  color.addEventListener("input", () => { viewState.table = color.value; postView("table", color.value); });
  color.addEventListener("click", (e) => e.stopPropagation());
  row.appendChild(color);
  view3dMenu.appendChild(row);
  divider();
  const labelsOn = currentSpec?.show_labels_3d === true;
  item(labelsOn ? "Labels: on" : "Labels: off", async () => {
    postView("labels", !labelsOn);
    commit(await api.setMeta({ show_labels_3d: !labelsOn })); // kept with the scene; the page already shows it
  }, labelsOn);
  item("Fullscreen", () => postView("fullscreen", true), false);
  item("Photoreal render", () => { toggleView3dMenu(false); postView("photoreal", true); }, false);
}

function toggleView3dMenu(open) {
  const show = open === undefined ? view3dMenu.hidden : open;
  if (show) buildView3dMenu();
  view3dMenu.hidden = !show;
  view3dBtn.setAttribute("aria-expanded", String(show));
}
view3dBtn.addEventListener("click", (e) => {
  e.stopPropagation();
  if (!in3d()) setView("3d");
  toggleView3dMenu();
});
document.addEventListener("click", (e) => {
  if (!view3dMenu.hidden && !e.target.closest("#view3d-menu") && e.target !== view3dBtn) toggleView3dMenu(false);
});
// a click in the 3D view goes to its frame, not to this document: the window loses focus, so close the menus
window.addEventListener("blur", () => { toggleView3dMenu(false); toggleAnimMenu(false); });

// -- Check panel (design-rule / consistency checks) --
const checkPanel = document.getElementById("check-panel");
const checkList = document.getElementById("check-list");
makePanelDraggable(checkPanel, document.getElementById("check-head"));
document.getElementById("check-close").addEventListener("click", () => { checkPanel.hidden = true; });

function onCheckClick() {
  withStatus("Running checks", async () => {
    const { checks } = await api.validate();
    checkList.innerHTML = "";
    const warnCount = checks.filter((c) => c.level !== "info").length;
    document.getElementById("check-sub").textContent = checks.length
      ? (warnCount
          ? `— ${warnCount} issue${warnCount > 1 ? "s" : ""}${checks.length > warnCount ? ` + ${checks.length - warnCount} notes` : ""}`
          : `— ${checks.length} note${checks.length > 1 ? "s" : ""}`)
      : "— all clear";
    if (!checks.length) {
      const ok = document.createElement("div");
      ok.className = "check-ok";
      ok.textContent = "✓ No issues found.";
      checkList.appendChild(ok);
    }
    for (const c of checks) {
      const item = document.createElement("div");
      item.className = "check-item" + (c.level === "error" ? " is-error" : c.level === "info" ? " is-info" : "");
      const kind = document.createElement("span");
      kind.className = "check-kind";
      kind.textContent = c.kind;
      const msg = document.createElement("span");
      msg.className = "check-msg";
      msg.textContent = c.message;
      item.append(kind, msg);
      if (c.component_id) {
        const chip = document.createElement("button");
        chip.type = "button";
        chip.className = "check-chip";
        chip.textContent = c.component_id;
        chip.title = "Select this component on the canvas";
        chip.addEventListener("click", (e) => { e.stopPropagation(); canvas.select(c.component_id); });
        msg.appendChild(chip);
        item.classList.add("clickable");
        item.addEventListener("click", () => canvas.select(c.component_id));
      }
      checkList.appendChild(item);
    }
    checkPanel.hidden = false;
  });
}
document.getElementById("btn-check").addEventListener("click", onCheckClick);

// -- Export figure bundle dialog (publication zip) --
function openFigure() {
  openModal((card, close) => {
    card.classList.add("generate-modal");
    const head = document.createElement("div");
    head.className = "od-modal-head";
    head.textContent = "Export figure bundle";
    const body = document.createElement("div");
    body.className = "od-modal-body";
    const mk = (label, control) => {
      const row = document.createElement("div");
      row.className = "gen-row";
      const lab = document.createElement("label");
      lab.className = "od-modal-label";
      lab.textContent = label;
      row.append(lab, control);
      return row;
    };
    const tmplSel = document.createElement("select");
    tmplSel.className = "od-modal-input";
    const presetSel = document.createElement("select");
    presetSel.className = "od-modal-input";
    const caption = document.createElement("input");
    caption.type = "text";
    caption.className = "od-modal-input";
    caption.placeholder = "(optional)";
    const FORMATS = ["svg", "tikz", "png", "json"];
    const DEFAULT_FMT = new Set(["svg", "json"]);
    const fmtWrap = document.createElement("div");
    fmtWrap.className = "fmt-wrap";
    const fmtBoxes = {};
    for (const f of FORMATS) {
      const lab = document.createElement("label");
      lab.className = "fmt-box";
      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.checked = DEFAULT_FMT.has(f);
      fmtBoxes[f] = cb;
      lab.append(cb, document.createTextNode(" " + f));
      fmtWrap.appendChild(lab);
    }
    body.append(mk("Template", tmplSel), mk("Preset", presetSel), mk("Formats", fmtWrap), mk("Caption", caption));
    const foot = document.createElement("div");
    foot.className = "od-modal-foot";
    const cancel = document.createElement("button");
    cancel.className = "od-btn od-ghost";
    cancel.textContent = "Cancel";
    const go = document.createElement("button");
    go.className = "od-btn od-primary";
    go.textContent = "Export zip";
    foot.append(cancel, go);
    card.append(head, body, foot);
    cancel.addEventListener("click", () => close(null));
    api.publicationTemplates().then(({ templates, presets }) => {
      for (const t of templates || []) {
        const o = document.createElement("option");
        o.value = t;
        o.textContent = t.replace(/_/g, " ");
        tmplSel.appendChild(o);
      }
      tmplSel.value = "single_figure";
      const none = document.createElement("option");
      none.value = "";
      none.textContent = "(default)";
      presetSel.appendChild(none);
      for (const pr of presets || []) {
        const o = document.createElement("option");
        o.value = pr;
        o.textContent = pr.replace(/_/g, " ");
        presetSel.appendChild(o);
      }
    }).catch(() => {});
    go.addEventListener("click", () => {
      const formats = FORMATS.filter((f) => fmtBoxes[f].checked);
      close(null);
      withStatus("Building figure bundle", async () => {
        const blob = await api.exportFigure({ template: tmplSel.value, preset: presetSel.value || null, formats, caption: caption.value || null });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `${(currentSpec?.title || "figure").replace(/\s+/g, "_")}_figures.zip`;
        a.click();
        URL.revokeObjectURL(url);
        setStatus("Figure bundle exported");
      });
    });
  });
}

// routing-type dropdown
// Miniature path drawings so each routing style is recognizable at a glance.
const ROUTE_SWATCHES = {
  beam: '<path d="M1 7h20" stroke-dasharray="3.4 2.2"/>',
  wg: '<path d="M1 12C8 12 14 2 21 2"/>',
  wg_manhattan: '<path d="M1 12h9a3 3 0 0 0 3-3V2h8"/>',
  wg_direct: '<path d="M1 12L21 2"/>',
  fiber: '<path d="M1 12C6 12 6 7 11 7s5-5 10-5"/>',
  electrical: '<path d="M1 12h11V2h9"/>',
};

function buildRouteMenu() {
  els.routeMenu.innerHTML = "";
  for (const type of ROUTING_TYPES) {
    const item = document.createElement("div");
    item.className = "route-menu-item" + (type.id === routingType.id ? " active" : "");
    item.innerHTML = `<svg class="rm-swatch" viewBox="0 0 22 14" aria-hidden="true">${ROUTE_SWATCHES[type.id] || '<path d="M1 7h20"/>'}</svg><span>${type.label}</span>`;
    item.addEventListener("click", () => {
      routingType = type;
      routingTypePicked = true;  // an explicit choice wins over the port kinds
      els.routeLabel.textContent = type.mode === "beam" ? "Beam" : type.label.split(" ")[0];
      toggleRouteMenu(false);
      setConnectMode(true); // selecting a type starts routing with it
    });
    els.routeMenu.appendChild(item);
  }
}

function toggleRouteMenu(open) {
  const show = open === undefined ? els.routeMenu.hidden : open;
  if (show) buildRouteMenu();
  els.routeMenu.hidden = !show;
  els.routeMenuBtn.setAttribute("aria-expanded", String(show));
}

els.routeMenuBtn.addEventListener("click", (e) => { e.stopPropagation(); toggleRouteMenu(); });
document.addEventListener("click", (e) => {
  if (!els.routeMenu.hidden && !e.target.closest(".route-control")) toggleRouteMenu(false);
});

// -- welcome / start screen ------------------------------------------------
const PRESET_TITLES = {
  confocal_pl: "Micro-PL setup (Sahoo 2026)",
  raman: "Raman micro-spectroscopy (McNairn 2021)",
  ftir: "FTIR interferometer (Ni 2020)",
  free_space_breadboard: "Self-calibrating polarimeter (Wirthl 2021)",
  ring_resonator_chip: "Fifth-order ring filter (Mak 2015)",
  wdm_delay_weight_bank_chip: "Broadcast-and-weight network (Tait 2017)",
  mzm_mesh_chip: "MZM mesh (programmable processor)",
  coherent_receiver_chip: "Coherent receiver (Faralli 2015)",
  qwp_circular_lab: "Rotating-QWP polarimeter (Schaefer 2007)",
};
const presetTitle = (n) => PRESET_TITLES[n] || n.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

// Preset gallery card: humanized title over a live scene thumbnail.
function presetCard(name, onPick) {
  const card = document.createElement("div");
  card.className = "welcome-ex";
  card.innerHTML = `<span class="we-thumb" aria-hidden="true"></span><b>${presetTitle(name)}</b>`;
  card.addEventListener("click", onPick);
  api.presetPreview(name).then(({ svg }) => {
    const t = card.querySelector(".we-thumb");
    if (!t) return;
    t.innerHTML = svg;
    fitSvgToContent(t, 0.05);
  }).catch(() => {});
  return card;
}

function buildWelcome() {
  const exHost = document.getElementById("wc-presets");
  const recentHead = document.getElementById("wc-recent-head");
  const recentHost = document.getElementById("wc-recent");
  api.workspaces().then(({ workspaces, presets, current }) => {
    exHost.innerHTML = "";
    for (const name of presets || []) {
      exHost.appendChild(presetCard(name, () => { hideWelcome(); newFromPreset(name); }));
    }
    const others = (workspaces || []).filter((w) => w !== current);
    recentHead.hidden = others.length === 0;
    recentHost.innerHTML = "";
    for (const w of others.slice(0, 6)) {
      const it = document.createElement("div");
      it.className = "welcome-recent-item";
      it.textContent = w;
      it.addEventListener("click", () => { hideWelcome(); openWs(w); });
      recentHost.appendChild(it);
    }
  }).catch(() => {});
}
function showWelcome() { buildWelcome(); document.getElementById("welcome").hidden = false; }

// Presets gallery — a first-class picker (not buried in the workspace menu).
function openPresets() {
  openModal((card, close) => {
    card.classList.add("presets-modal");
    const head = document.createElement("div");
    head.className = "od-modal-head";
    head.textContent = "Presets";
    const sub = document.createElement("div");
    sub.className = "od-modal-body";
    sub.style.paddingBottom = "4px";
    sub.textContent = "Open a ready-made setup. It opens in its own workspace unless the scene is empty.";
    const grid = document.createElement("div");
    grid.className = "welcome-grid presets-grid";
    card.append(head, sub, grid);
    api.workspaces().then(({ presets }) => {
      grid.innerHTML = "";
      for (const name of presets || []) {
        grid.appendChild(presetCard(name, () => { close(null); newFromPreset(name); }));
      }
    }).catch(() => { grid.textContent = "Couldn't load presets."; });
  });
}
function hideWelcome() {
  if (document.getElementById("wc-hide").checked) localStorage.setItem("od-welcome-hide", "1");
  document.getElementById("welcome").hidden = true;
}
document.getElementById("wc-x").addEventListener("click", hideWelcome);
document.getElementById("wc-close").addEventListener("click", hideWelcome);
document.getElementById("wc-new").addEventListener("click", () => {
  hideWelcome();
  withStatus("New scene", async () => {
    await leaveInsets();
    commit(await api.newScene({}));
    canvas.select(null);
    properties.clear();
  });
});
document.getElementById("wc-open").addEventListener("click", () => { hideWelcome(); document.getElementById("file-open").click(); });
document.getElementById("wc-import").addEventListener("click", () => { hideWelcome(); document.getElementById("file-gds").click(); });

// -- workspace switcher ----------------------------------------------------

async function buildWorkspaceMenu() {
  const { workspaces, current } = await api.workspaces();
  els.wsName.textContent = current;
  const menu = els.workspaceMenu;
  menu.innerHTML = "";
  const header = (t) => { const h = document.createElement("div"); h.className = "ws-menu-header"; h.textContent = t; menu.appendChild(h); };
  const item = (label, onClick, cls = "") => {
    const el = document.createElement("div");
    el.className = "ws-menu-item " + cls;
    el.textContent = label;
    el.addEventListener("click", () => { toggleWorkspaceMenu(false); onClick(); });
    menu.appendChild(el);
    return el;
  };
  const divider = () => { const d = document.createElement("div"); d.className = "ws-menu-divider"; menu.appendChild(d); };

  header("Switch workspace");
  for (const w of workspaces) item(w, () => openWs(w), w === current ? "active" : "");
  divider();
  item("+ New workspace…", newWs);
  item("Rename current…", renameWs);
  item("Delete current", deleteWs, "danger");
  divider();
  item("Browse presets…", openPresets);
  item("Welcome screen", showWelcome);
}

function toggleWorkspaceMenu(open) {
  const show = open === undefined ? els.workspaceMenu.hidden : open;
  els.workspaceMenu.hidden = !show;
  els.workspaceBtn.setAttribute("aria-expanded", String(show));
  if (show) buildWorkspaceMenu();
}

// The answer names a large drawing by its key, so the page's size comes from the page as the session holds it.
const openWs = (name) => withStatus(`Opening ${name}`, async () => loadWorkspace(await api.openWorkspace(name)))
  .then(() => fetch("/api/scene")).then((res) => res.blob()).then((page) => noteLargePage(page.size));
// A workspace name becomes a filename, so "My Chip!" and "My Chip" are the same
// workspace. The server refuses to overwrite one with the other; here we come
// back with a free name already filled in rather than making the user guess.
function nextFreeName(name, taken) {
  // Same sanitizing the server does, so the name offered is the name created.
  const cleaned = String(name).replace(/[^A-Za-z0-9 _-]/g, "").trim();
  const stem = cleaned.replace(/\s+\d+$/, "").trim() || "Untitled";
  const used = new Set((taken || []).map((n) => n.toLowerCase()));
  for (let n = 2; n < 100; n++) {
    const candidate = `${stem} ${n}`;
    if (!used.has(candidate.toLowerCase())) return candidate;
  }
  return stem;
}

async function newWs() {
  let suggestion = "";
  for (;;) {
    const name = await dialogPrompt({
      title: "New workspace", label: "Name", value: suggestion,
      placeholder: "e.g. Confocal rig", confirmText: "Create",
    });
    if (!name) return;
    try {
      loadWorkspace(await api.createWorkspace(name));
      setStatus(`Created ${name}`);
      return;
    } catch (error) {
      if (!/already exists/i.test(error.message || "")) {
        setStatus(error.message, true);
        return;
      }
      const { workspaces } = await api.workspaces().catch(() => ({ workspaces: [] }));
      suggestion = nextFreeName(name, workspaces);
      setStatus(`${error.message} — try ${suggestion}`, true);
    }
  }
}
function sceneIsEmpty() {
  const spec = currentSpec || {};
  return !(spec.components || []).length && !(spec.routes || []).length && !(spec.beams || []).length;
}

function newFromPreset(name) {
  // A preset REPLACES the scene, and the replacement is autosaved over the open
  // workspace with the undo history cleared — so opening one used to destroy
  // whatever was on screen, permanently. An empty scene has nothing to lose;
  // anything else gets the preset in a workspace of its own.
  let note = "";
  withStatus(`Loading preset: ${presetTitle(name)}`, async () => {
    if (sceneIsEmpty()) { // inside an inset the server refuses: a preset replaces the page
      loadWorkspace(await api.loadPreset(name));
    } else {
      const { workspaces } = await api.workspaces().catch(() => ({ workspaces: [] }));
      const kept = els.wsName.textContent;
      const wanted = presetTitle(name);
      const target = (workspaces || []).includes(wanted) ? nextFreeName(wanted, workspaces) : wanted;
      loadWorkspace(await api.createWorkspace(target, name));
      els.wsName.textContent = target;
      note = `Opened in a new workspace "${target}" — "${kept}" is untouched.`;
    }
    requestAnimationFrame(() => canvas.fit());
  }).then(() => { if (note) setStatus(note); });
}
async function renameWs() {
  const name = await dialogPrompt({
    title: "Rename workspace", label: "Name", value: els.wsName.textContent, confirmText: "Rename",
  });
  if (name) withStatus("Renaming", async () => {
    setWorkspace((await api.renameWorkspace(els.wsName.textContent, name)).current);
    els.wsName.textContent = name.replace(/[^A-Za-z0-9 _-]/g, "").trim() || els.wsName.textContent;
  });
}
async function deleteWs() {
  const cur = els.wsName.textContent;
  const ok = await dialogConfirm({
    title: "Delete workspace", message: `Delete "${cur}"? This cannot be undone.`,
    confirmText: "Delete", danger: true,
  });
  if (ok) withStatus("Deleting", async () => loadWorkspace(await api.deleteWorkspace(cur)));
}

els.workspaceBtn.addEventListener("click", (e) => { e.stopPropagation(); toggleWorkspaceMenu(); });
document.addEventListener("click", (e) => {
  if (!els.workspaceMenu.hidden && !e.target.closest(".ws-control")) toggleWorkspaceMenu(false);
});

const btn2d = document.getElementById("btn-view-2d");
const btn3d = document.getElementById("btn-view-3d");
const btnLayout = document.getElementById("btn-view-layout");
btn2d.addEventListener("click", () => setView("2d"));
btn3d.addEventListener("click", () => setView("3d"));
btnLayout.addEventListener("click", () => setView("layout"));
// The 1D view (view1d.js) hides the Layout view itself; give back what the Layout view took from the editor.
document.getElementById("btn-view-1d").addEventListener("click", () => {
  layoutView.close();
  els.viewLayout.hidden = true;
  btnLayout.classList.remove("active");
  document.querySelector(".zoom-cluster").hidden = false;
  document.getElementById("xs-cut-ruler").hidden = true;
  if (els.zoomLevel.textContent === "Layout") els.zoomLevel.textContent = `${els.zoomLevel.dataset.pct || 100}%`;
});

// The imported GDS parts the Layout view can show: a GDSModel with a file source. Ids start again in each scene,
// so a part is known by its file key (id, source, cell: the geometry) and its full key (that and its layer stack).
function gdsParts() {
  return (currentSpec?.components || [])
    .filter((c) => c.type === "GDSModel" && typeof c.source === "string" && c.source)
    .map((c) => {
      const file = JSON.stringify([c.id, c.source, c.cell_name || null]);
      return { id: c.id, label: c.label || c.id, cell: c.cell_name || null, file,
               key: JSON.stringify([file, c.layer_stack || null]) };
    });
}

const layoutView = createLayoutView({
  host: els.viewLayout,
  api,
  onStatus: (text) => setStatus(text),
  onPick: (id) => { const part = gdsParts().find((p) => p.id === id); if (part) openLayout(part); },
});

function inLayout() { return !els.viewLayout.hidden; }

// Show a part in the Layout view, select it (so the inspector offers its cross-section), and draw the panel's
// cut of it as a ruler.
async function openLayout(part, { reload = false } = {}) {
  if (!reload) canvas.select(part.id);     // a reload is the same part in new colours: keep the inspector as it is
  await layoutView.open(part, { reload });
  if (xsLineFile && xsLineFile.file === part.file) layoutView.showCut(xsLineFile.line);
}

function syncLayout() {
  const parts = gdsParts();
  btnLayout.disabled = parts.length === 0;
  layoutView.setParts(parts);
  if (!inLayout()) return;
  if (!parts.length) { setView("2d"); return; }
  const { key, file } = layoutView.wanted();
  if (parts.some((p) => p.key === key)) return;          // the part on screen is unchanged
  const same = parts.find((p) => p.file === file);         // the same geometry with a new stack: re-read it
  openLayout(same || parts[0], { reload: !!same });
}

function setView(mode) {
  const is3d = mode === "3d";
  const isLayout = mode === "layout";
  btn3d.classList.toggle("active", is3d);
  btnLayout.classList.toggle("active", isLayout);
  btn2d.classList.toggle("active", !is3d && !isLayout);
  els.view3d.hidden = !is3d;
  els.viewLayout.hidden = !isLayout;
  els.canvas.hidden = is3d || isLayout;
  document.querySelector(".zoom-cluster").hidden = isLayout;   // GDS Lens zooms on its own, with its own scale bar
  els.zoomLevel.textContent = is3d ? "3D" : isLayout ? "Layout" : `${els.zoomLevel.dataset.pct || 100}%`;
  document.getElementById("xs-cut-ruler").hidden = !isLayout;   // a cut comes from the Layout view's ruler
  if (isLayout) {
    document.getElementById("view1d").hidden = true;
    document.getElementById("btn-view-1d")?.classList.remove("active");
    const parts = gdsParts();
    openLayout(parts.find((p) => canvas.selectedIds.includes(p.id)) || parts[0]);
  } else {
    layoutView.close();
  }
  if (is3d) {
    els.view3d.src = threejsSrc();
    setStatus("3D view: drag to orbit, scroll to zoom. Select a part, then M moves (and lifts) it; X, Y and Z turn it about its own x, its own y and the vertical");
  }
}

// 2D <-> 3D bridge: the editable Three.js iframe posts selections here, and we
// push highlight changes back so selection stays in sync across both views.
window.addEventListener("message", (e) => {
  const data = e.data || {};
  if (data.type === "optodraw-select") {
    // Shift-click in 3D builds a selection (primary first); a plain click selects one part
    if (Array.isArray(data.ids) && data.ids.length > 1) canvas.selectMany(data.ids);
    else canvas.select(data.id || null); // triggers refreshProperties -> postHighlight
  } else if (data.type === "optodraw-ready") {
    postHighlight();
    postCamera(); // restore orbit pose after a live re-render
    syncViewTo3d(); // the world and table colour the View menu set, before the light takes the world
    syncAnimTo3d(); // the toolbar owns animation state; re-apply after any reload
  } else if (data.type === "optodraw-tour") {
    tourOn = !!data.playing;
    syncAnimButton();
    if (!tourOn) setStatus("Tour ended");
  } else if (data.type === "optodraw-camera") {
    cameraState = { pos: data.pos, target: data.target };
  } else if (data.type === "optodraw-move" && data.id) {
    withStatus("Moving", async () => {
      commit(await api.move(data.id, data.center)); // angle unchanged
      const dz = Number(data.dz) || 0;
      if (Math.abs(dz) > 1e-3) {                     // lifted on the gizmo's up arrow: a new height
        const entry = (currentSpec?.components || []).find((c) => c.id === data.id) || {};
        const z = Math.round(((Number(entry.z) || 0) + dz) * 10) / 10;
        commit(await api.update(data.id, { z: z === 0 ? null : z }));
      }
      canvas.select(data.id); // keep selection -> 3D re-highlights + re-attaches gizmo
    });
  } else if (data.type === "optodraw-undo") {
    data.redo ? redo() : undo();                     // Ctrl/Cmd+Z pressed while the 3D view had the keyboard
  } else if (data.type === "optodraw-move-group" && Array.isArray(data.moves) && data.moves.length) {
    // the selection moved together on the 3D gizmo: one undoable step, the same shift (and lift) for every part
    const ids = data.moves.map((m) => m.id);
    applySpec("Move", (next) => {
      applyMoveChanges(next, data.moves.map((m) => ({ id: m.id, center: m.center })));
      for (const m of data.moves) {
        const dz = Number(m.dz) || 0;
        if (Math.abs(dz) <= 1e-3) continue;
        const e = next.components.find((c) => c.id === m.id);
        if (!e) continue;
        const z = Math.round(((Number(e.z) || 0) + dz) * 10) / 10;
        if (z === 0) delete e.z; else e.z = z;
      }
    }, { reselect: ids });
  } else if (data.type === "optodraw-rotate" && data.id) {
    withStatus("Rotating", async () => {
      const round = (v) => Math.round((Number(v) || 0) * 10) / 10;
      const turn = { angle: round(data.angle) };
      for (const key of ["rotation_x", "rotation_y"]) {
        const v = round(data[key]);
        turn[key] = v === 0 ? null : v;              // a flat part saves no turn
      }
      commit(await api.update(data.id, turn));
      canvas.select(data.id); // sync 2D + reattach gizmo
    });
  }
});

document.addEventListener("keydown", (e) => {
  const tag = document.activeElement?.tagName;
  const inField = tag === "INPUT" || tag === "TEXTAREA";
  const mod = e.ctrlKey || e.metaKey;

  if (mod && e.key.toLowerCase() === "k") {
    e.preventDefault();
    cmdk.toggle();
    return;
  }
  if (cmdk.isOpen()) return; // the palette owns the keyboard while open
  // keys typed in the Layout view (its find box, KLayout-style panning) are the viewer's, never the scene's:
  // focus inside its shadow root leaves document.activeElement on <gds-lens>, not on a field
  if (e.composedPath().some((node) => node.tagName === "GDS-LENS")) return;

  if (e.key === "Escape" && connectMode) {
    e.preventDefault();
    setConnectMode(false);
  } else if (e.key === "Escape" && !inField && canvas.selectedIds.length) {
    e.preventDefault();
    canvas.select(null);                             // let go of the selection, so nothing selected moves by accident
  } else if (mod && e.key.toLowerCase() === "z") {
    e.preventDefault();
    e.shiftKey ? redo() : undo();
  } else if (mod && e.key.toLowerCase() === "y") {
    e.preventDefault();
    redo();
  } else if (mod && e.key.toLowerCase() === "a" && !inField) {
    e.preventDefault();
    canvas.selectMany((currentSpec?.components || []).map((c) => c.id));
  } else if (mod && e.key.toLowerCase() === "d") {
    e.preventDefault();
    duplicateSelected();
  } else if (mod && e.key.toLowerCase() === "c" && !inField) {
    copySelected();
  } else if (mod && e.key.toLowerCase() === "v" && !inField) {
    e.preventDefault();
    paste();
  } else if ((e.key === "Delete" || e.key === "Backspace") && canvas.selectedIds.length && !inField) {
    e.preventDefault();
    deleteSelected();
  } else if (e.key.startsWith("Arrow") && canvas.selectedIds.length && !inField) {
    e.preventDefault();
    const step = e.shiftKey ? 10 : 1;
    const d = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, step], ArrowDown: [0, -step] }[e.key];
    if (d) nudge(d[0], d[1]);
  } else if (!mod && !inField && in3d() && canvas.selectedIds.length) {
    // the 3D handle keys, wherever the focus is (the 3D page hears them itself only once it has the focus):
    // X turns the part about its own x (its beam axis), Y about its own y, Z (or R) about the vertical; M/G/T moves
    // and lifts it
    const mode = { x: "roll", y: "tilt", z: "rotate", r: "rotate", m: "translate", g: "translate",
                   t: "translate" }[e.key.toLowerCase()];
    if (mode) { e.preventDefault(); post3d({ type: "optodraw-gizmo", mode }); }
  }
});

// -- command palette (⌘K) --------------------------------------------------
// Every action routes through the SAME control it mirrors (button .click() /
// shared handler), so palette behavior can never drift from the toolbar's.

const clickById = (id) => () => document.getElementById(id)?.click();

function arrangeSelection(strategy) {
  // an empty selection tidies the whole scene; the server keeps the block's corner
  const ids = selComponentIds();
  return withStatus(strategy === "grid" ? "Arrange grid" : "Arrange row", async () => {
    commit(await api.arrange({ ids, strategy }));
    canvas.selectMany(ids);
  });
}

function commandSources() {
  const items = [];
  const act = (label, sub, icon, run, kbd) => items.push({ group: "Actions", label, sub, icon, run, kbd });
  act("New scene", "Empty artboard", "i-new", clickById("btn-new"));
  act("Open scene file…", "Load a scene JSON", "i-open", () => document.getElementById("file-open")?.click());
  act("Save scene", "Download scene JSON", "i-save", clickById("btn-save"));
  act("Save As workspace…", "Create a named workspace", "i-save", clickById("btn-save-as"));
  act("Import GDS…", "Place a .gds layout", "i-chip", () => document.getElementById("file-gds")?.click());
  act("Import 3D model…", "Place a GLB / GLTF / OBJ / STL as a component", "i-cube", () => document.getElementById("file-model")?.click());
  act("Import SVG drawing…", "Place your own SVG as an inset", "i-image",
    () => addFigure(FIGURE_ENTRIES.find((e) => e.kind === "SvgFile")).catch(() => {}));   // withStatus has shown the error
  act("Browse presets", "Ready-made setups gallery", "i-layers", clickById("btn-presets"));
  act("Undo", "", "i-undo", undo, "⌘Z");
  act("Redo", "", "i-redo", redo, "⇧⌘Z");
  for (const a of EXPORT_ACTIONS) act(`Export: ${a.label}`, a.sub, a.icon, a.run);
  act("Route tool", "Draw beams / waveguides between ports", "i-route", clickById("btn-connect"));
  act("Links panel", "Type port connections as text", "i-link", clickById("btn-text-route"));
  act("Trace mode", "Sources emit live ray bundles", "i-trace", clickById("btn-trace"));
  act("Simulate", "Resonance / transfer / polarization plots", "i-wave", clickById("btn-simulate"));
  act("Generate layout…", "Mesh, weight bank, ring filter, driver chain", "i-sparkles", clickById("btn-generate"));
  act("Arrange in a grid", "Tidy the selection (or everything) onto a grid", "i-layers", () => arrangeSelection("grid"));
  act("Arrange in a row", "Space the selection (or everything) along a line", "i-layers", () => arrangeSelection("line"));
  act("Run checks", "Design-rule / consistency checks", "i-check", clickById("btn-check"));
  act("Toggle 3D animation", "Physics overlays on / off", "i-play", clickById("btn-animate"));
  act("Scene settings…", "Title, frame, background, chip options", "i-settings", clickById("btn-scene"));
  act("Fit view", "Frame the whole scene", "i-fit", clickById("btn-fit"));
  act("1D view", "Compact monochrome schematic", "i-wave", clickById("btn-view-1d"));
  act("2D view", "Planar layout", "i-grid", clickById("btn-view-2d"));
  act("3D view", "", "i-cube", clickById("btn-view-3d"));
  if (gdsParts().length) act("Layout view", "The imported GDS as in KLayout", "i-chip", clickById("btn-view-layout"));
  act("Toggle snap", "Snap to grid", "i-magnet", clickById("btn-snap"));
  act("Toggle grid", "Show / hide the grid", "i-grid", clickById("btn-grid"));
  act("Select all", "", "i-fit", () => canvas.selectMany((currentSpec?.components || []).map((c) => c.id)), "⌘A");
  if (canvas.selectedIds.length) {
    act("Duplicate selection", "", "i-duplicate", duplicateSelected, "⌘D");
    act("Delete selection", "", "i-trash", deleteSelected, "⌫");
  }
  for (const [name, info] of Object.entries(catalogCache || {})) {
    // The same two lists the palette hides. Spelling them out again here left
    // "models" off, so ⌘K offered GDS Model and Custom Model as things to add
    // and the server answered 400: those are made by the import flows above.
    if (HIDDEN_COMPONENTS.has(name)) continue;
    const cat = info.category || "other";
    if (HIDDEN_CATEGORIES.has(cat)) continue;
    items.push({
      group: "Add component",
      label: info.display_name || humanizeName(name),
      sub: cat.replace(/_/g, " "),
      icon: "i-plus",
      run: () => paletteAdd(name),
    });
  }
  return items;
}

const cmdk = createCommandPalette({
  getSources: async () => {
    const items = commandSources();
    try {
      const { workspaces, presets, current } = await api.workspaces();
      for (const name of presets || []) {
        items.push({ group: "Presets", label: escHtml(presetTitle(name)), sub: "load preset", icon: "i-layers", run: () => newFromPreset(name) });
      }
      for (const w of (workspaces || []).filter((w) => w !== current)) {
        items.push({ group: "Workspaces", label: escHtml(w), sub: "open workspace", icon: "i-open", run: () => openWs(w) });
      }
    } catch (_) { /* offline — actions + components still work */ }
    return items;
  },
});

// -- boot ------------------------------------------------------------------
installPartsControls({
  getCatalog: () => catalogCache,
  onError: (reason) => setStatus(reason.message),
  onChanged: async () => {
    const data = await api.catalog(); catalogCache = data.components;
    palette.setCatalog(catalogCache); setStatus("Part saved to My parts");
  },
});

(async function boot() {
  try {
    const [catalog, scene, svg, mats] = await Promise.all([
      api.catalog(),
      api.getScene(),
      api.renderSvg(),
      api.materials().catch(() => ({ presets: [] })),
    ]);
    materials = mats.presets || [];
    palette.setCatalog(catalog.components);
    catalogCache = catalog.components || {};
    sourceTypes = new Set(Object.entries(catalog.components || {})
      .filter(([, entry]) => entry && entry.source).map(([name]) => name));
    currentSpec = scene;
    takeSavedLook(currentSpec);
    canvas.setSpec(currentSpec);
    canvas.setSvg(svg.svg);
    setInsetPath(svg.path); // a reload inside an open inset keeps the path bar
    setWorkspace(svg.workspace);
    applySceneStyle(currentSpec);
    syncLayout(); // the Layout button, for a scene that already holds an imported GDS
    renderContextActions([]);
    pushHistory(currentSpec);
    api.workspaces().then((w) => { els.wsName.textContent = w.current; }).catch(() => {});
    api.pdks().then((r) => { pdkList = r.pdks || []; }).catch(() => {});
    api.stacks().then((r) => { stackList = r.stacks || []; }).catch(() => {});
    if (!localStorage.getItem("od-welcome-hide")) showWelcome();
    setStatus("ready");
    noteLargePage(JSON.stringify(scene).length);   // GET /api/scene holds every drawing, none by key
  } catch (err) {
    setStatus(`Failed to load: ${err.message}`, true);
  }
})();
