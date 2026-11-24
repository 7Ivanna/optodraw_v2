// 1D schematic: each part is its looked-up symbol, at its own 1D position.
// The server sends the symbol (SVG and ports), the links and every position.
// Positions belong to this view, not the 2D/3D stage. They are in symbol points.
import { api } from "./api.js?v=1795495279636150780";

const host = document.getElementById("view1d");
const one = document.getElementById("btn-view-1d");
const two = document.getElementById("btn-view-2d");
const three = document.getElementById("btn-view-3d");
const canvas = document.getElementById("canvas");
const view3d = document.getElementById("view3d");
const NS = "http://www.w3.org/2000/svg";
const ZOOM = 1.6;       // screen pixels per symbol point
const LABEL_H = 16;     // pixels under a symbol for its label
const NORMAL = { left: [-1, 0], right: [1, 0], top: [0, -1], bottom: [0, 1] };

let components = [];
let links = [];
let junctions = [];  // the server's dots where wires of one node join
let marks = [];      // the server's regions, brackets and stage motion marks, in symbol points
let positions = {};
let note = "";
let surface = null;
let wires = null;
let connectAnchor = null;
let routePending = false;
let statusTimer = null;
let moved = new Set();  // parts dragged since the server last routed the links

// The same path as optodraw/symbols/router.py rounded_path(): a square route with rounded bends (radius 0: square).
function roundedPath(points, radius) {
  let d = `M${points[0][0]} ${points[0][1]}`;
  for (let i = 1; i < points.length - 1; i += 1) {
    const [a, b, c] = [points[i - 1], points[i], points[i + 1]];
    const la = Math.hypot(a[0] - b[0], a[1] - b[1]);
    const lb = Math.hypot(c[0] - b[0], c[1] - b[1]);
    const r = Math.min(radius, la / 2, lb / 2);
    if (r <= 0) { d += ` L${b[0]} ${b[1]}`; continue; }
    d += ` L${b[0] + (a[0] - b[0]) * r / la} ${b[1] + (a[1] - b[1]) * r / la}`;
    d += ` Q${b[0]} ${b[1]} ${b[0] + (c[0] - b[0]) * r / lb} ${b[1] + (c[1] - b[1]) * r / lb}`;
  }
  const last = points[points.length - 1];
  return `${d} L${last[0]} ${last[1]}`;
}

function portPoint(componentId, portName, fallback) {
  const component = components.find((c) => c.id === componentId);
  const pos = positions[componentId];
  if (!component || !pos) return null;
  const symbol = component.symbol;
  const port = symbol.ports.find((p) => p.name === portName);
  if (port) {
    // An electrode, not an edge port: the same rule as _inside() in optodraw/symbols/schematic.py.
    const inside = Math.min(port.x, symbol.width - port.x) > Math.max(0.15 * symbol.width, 6);
    return { x: (pos[0] + port.x) * ZOOM, y: (pos[1] + port.y) * ZOOM, side: port.side, inside };
  }
  const x = fallback === "left" ? pos[0] : pos[0] + symbol.width;
  return { x: x * ZOOM, y: (pos[1] + symbol.height / 2) * ZOOM, side: fallback };
}

function resize() {
  let width = Math.max(host.clientWidth, 400);
  let height = Math.max(host.clientHeight, 280);
  for (const component of components) {
    const pos = positions[component.id];
    if (!pos) continue;
    width = Math.max(width, (pos[0] + component.symbol.width) * ZOOM + 40);
    height = Math.max(height, (pos[1] + component.symbol.height) * ZOOM + LABEL_H + 40);
  }
  for (const [x, y] of marks.flatMap((mark) => mark.lines.flat())) {
    width = Math.max(width, x * ZOOM + 40);
    height = Math.max(height, y * ZOOM + LABEL_H + 40);
  }
  surface.style.width = `${width}px`;
  surface.style.height = `${height}px`;
  wires.setAttribute("width", String(width));
  wires.setAttribute("height", String(height));
}

// The same curve as optodraw/symbols/schematic.py link_curve(): a link leaves each port square to its edge.
function drawWires() {
  if (!wires) return;
  wires.replaceChildren();
  // Inside a splitter: a beam from each port in use to the point where the beams meet.
  for (const link of links) {
    for (const [id, name] of [[link.start_id, link.start_port], [link.end_id, link.end_port]]) {
      const component = components.find((c) => c.id === id);
      const pos = positions[id];
      const at = portPoint(id, name, "right");
      if (!component || !pos || !at || !component.symbol.hub) continue;
      const beam = document.createElementNS(NS, "path");
      const [hx, hy] = component.symbol.hub;
      beam.setAttribute("d", `M${at.x} ${at.y} L${(pos[0] + hx) * ZOOM} ${(pos[1] + hy) * ZOOM}`);
      beam.setAttribute("class", "od1-wire");
      wires.appendChild(beam);
    }
  }
  for (const link of links) {
    const a = portPoint(link.start_id, link.start_port, "right");
    const b = portPoint(link.end_id, link.end_port, "left");
    if (!a || !b) continue;
    const dx = Math.abs(b.x - a.x);
    const dy = Math.abs(b.y - a.y);
    const path = document.createElementNS(NS, "path");
    const wire = String(link.kind).includes("elect");
    path.setAttribute("class", "od1-wire" + (wire ? " electrical" : ""));
    if (link.route && !moved.has(link.start_id) && !moved.has(link.end_id)) {   // the server's square route
      // a waveguide bends, a wire turns sharp as in a circuit drawing
      path.setAttribute("d", roundedPath(link.route.map(([x, y]) => [x * ZOOM, y * ZOOM]), wire ? 0 : 3 * ZOOM));
      wires.appendChild(path);
      continue;
    }
    if (link.kind === "free_space") {     // light in air does not bend: a straight beam
      path.setAttribute("d", `M${a.x} ${a.y} L${b.x} ${b.y}`);
      wires.appendChild(path);
      continue;
    }
    const reach = (normal) => Math.max(6 * ZOOM, 0.5 * (normal[0] ? dx : dy));
    // A cable meets an electrode from the side it comes from.
    const side = (here, there) => (wire && here.inside && (here.side === "left" || here.side === "right")
      ? (there.y < here.y ? "top" : "bottom") : here.side);
    const na = NORMAL[side(a, b)];
    const nb = NORMAL[side(b, a)];
    path.setAttribute("d",
      `M${a.x} ${a.y} C${a.x + na[0] * reach(na)} ${a.y + na[1] * reach(na)} ` +
      `${b.x + nb[0] * reach(nb)} ${b.y + nb[1] * reach(nb)} ${b.x} ${b.y}`);
    wires.appendChild(path);
  }
  if (!moved.size) {      // the dots and marks stand with the server's layout; a drag hides them until it routes again
    drawMarks();
    for (const [x, y] of junctions) {
      const dot = document.createElementNS(NS, "circle");
      dot.setAttribute("class", "od1-junction");
      dot.setAttribute("cx", String(x * ZOOM));
      dot.setAttribute("cy", String(y * ZOOM));
      dot.setAttribute("r", String(1.2 * ZOOM));
      dot.setAttribute("fill", "#595959");
      wires.appendChild(dot);
    }
  }
  resize();
}

// The same marks as schematic_body() in optodraw/notebook_1d.py: lines, filled heads, and text set as text.
function drawMarks() {
  const scaled = (line) => line.map(([x, y]) => `${x * ZOOM} ${y * ZOOM}`).join(" L");
  for (const mark of marks) {
    for (const line of mark.lines) {
      const path = document.createElementNS(NS, "path");
      path.setAttribute("class", "od1-mark");
      path.setAttribute("d", `M${scaled(line)}`);
      path.setAttribute("fill", "none");
      path.setAttribute("stroke", mark.color);
      path.setAttribute("stroke-width", String(0.5 * ZOOM));
      if (mark.dashed) path.setAttribute("stroke-dasharray", `${2.4 * ZOOM} ${2 * ZOOM}`);
      wires.appendChild(path);
    }
    for (const head of mark.heads) {
      const path = document.createElementNS(NS, "path");
      path.setAttribute("class", "od1-mark");
      path.setAttribute("d", `M${scaled(head)} Z`);
      path.setAttribute("fill", mark.color);
      wires.appendChild(path);
    }
    if (mark.label) {
      const [x, y, anchor] = mark.label_at;
      const text = document.createElementNS(NS, "text");
      text.setAttribute("x", String(x * ZOOM));
      text.setAttribute("y", String(y * ZOOM));
      text.setAttribute("text-anchor", anchor);
      text.setAttribute("fill", mark.color);
      text.setAttribute("font-size", String(7 * ZOOM));
      text.setAttribute("font-family", "Helvetica, Arial, sans-serif");
      text.textContent = mark.label;
      wires.appendChild(text);
    }
  }
}

function showStatus(message, error = false) {
  host.querySelector(".od1-status")?.remove();
  const status = document.createElement("div");
  status.className = "od1-status" + (error ? " error" : "");
  status.setAttribute("role", "status");
  status.textContent = message;
  host.appendChild(status);
  clearTimeout(statusTimer);
  statusTimer = setTimeout(() => status.remove(), 3500);
}

async function connectPort(component, port, dot) {
  if (routePending) return;
  const target = { id: component.id, name: port.name, kind: port.kind || "optical", dot };
  if (!connectAnchor) {
    connectAnchor = target;
    dot.classList.add("connect-start");
    showStatus("Select a destination port to connect.");
    return;
  }
  const start = connectAnchor;
  if (start.id === target.id && start.name === target.name) {
    start.dot.classList.remove("connect-start");
    connectAnchor = null;
    showStatus("Connection cancelled.");
    return;
  }
  const isElectrical = (kind) => kind === "electrical" || kind === "thermal";
  if (isElectrical(start.kind) !== isElectrical(target.kind)) {
    showStatus("Electrical and optical ports cannot connect.", true);
    return;
  }
  routePending = true;
  try {
    let payload;
    if (start.kind === "free_space" && target.kind === "free_space") {
      const settings = { wavelength: 633 };
      window.dispatchEvent(new CustomEvent("optodraw:query-wavelength", { detail: settings }));
      payload = await api.addBeam([[start.id, start.name], [target.id, target.name]], settings.wavelength);
    } else {
      const kind = isElectrical(start.kind) ? "electrical"
        : start.kind === "optical" && target.kind === "optical" ? "waveguide" : "fiber";
      payload = await api.addRoute([start.id, start.name], [target.id, target.name], {
        kind,
        path_type: kind === "fiber" ? "smooth" : "manhattan",
        smooth: kind !== "electrical",
        width: kind === "electrical" ? 5 : undefined,
      });
    }
    window.dispatchEvent(new CustomEvent("optodraw:scene-committed", { detail: { payload } }));
    connectAnchor = null;
    if (!host.hidden) {
      await open1d();
      showStatus(`Connected ${start.id}.${start.name} to ${target.id}.${target.name}.`);
    }
  } catch (error) {
    showStatus(error.message || "Could not connect these ports.", true);
  } finally {
    routePending = false;
  }
}

// After a drag the server routes the links again round the parts where they now are.
async function reroute() {
  if (!moved.size) return;
  try {
    const response = await fetch("/api/scene/1d/model");
    if (!response.ok) return;
    const model = await response.json();
    links = model.links || links;
    junctions = model.junctions || [];
    marks = model.marks || [];
    moved = new Set();
    drawWires();
  } catch (error) {
    // the curves stay until the next load
  }
}

async function savePositions() {
  try {
    await api.save1dLayout(positions);
  } catch (error) {
    host.title = `Could not save the 1D layout: ${error.message}`;
    if (!host.hidden) showStatus(host.title, true);
  }
}

function makeCard(component) {
  const symbol = component.symbol;
  const pos = positions[component.id];
  const card = document.createElement("div");
  card.className = "od1-card" + (symbol.exact ? "" : " inexact");
  card.style.left = `${pos[0] * ZOOM}px`;
  card.style.top = `${pos[1] * ZOOM}px`;
  card.style.width = `${symbol.width * ZOOM}px`;
  card.style.height = `${symbol.height * ZOOM}px`;
  card.title = symbol.exact
    ? `${component.type}: drag to arrange this schematic`
    : `${component.type}: no exact 1D symbol yet (${symbol.source})`;
  const art = document.createElement("div");
  art.className = "od1-art";
  art.innerHTML = symbol.svg;          // built by the server from the symbol library; it holds no user text
  const label = document.createElement("div");
  label.className = "od1-label";
  if (component.label_at) {            // where the layout put it: x and baseline from the corner of the symbol
    const [dx, dy, anchor] = component.label_at;
    const shift = { middle: "-50%", start: "0", end: "-100%" }[anchor] || "-50%";
    label.style.left = `${dx * ZOOM}px`;
    label.style.top = `${dy * ZOOM}px`;
    label.style.transform = `translate(${shift}, -80%)`;
  }
  label.textContent = component.label;
  card.append(art, label);
  for (const port of symbol.ports) {
    const dot = document.createElement("span");
    dot.className = "od1-port" + (port.kind === "electrical" ? " electrical" : "");
    dot.tabIndex = 0;
    dot.setAttribute("role", "button");
    dot.setAttribute("aria-label", `Connect ${component.label}.${port.name}`);
    dot.style.left = `${port.x * ZOOM}px`;
    dot.style.top = `${port.y * ZOOM}px`;
    dot.title = `${component.label}.${port.name} (${port.kind})`;
    dot.addEventListener("pointerdown", (event) => event.stopPropagation());
    dot.addEventListener("click", (event) => { event.stopPropagation(); connectPort(component, port, dot); });
    dot.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        event.stopPropagation();
        connectPort(component, port, dot);
      }
    });
    card.appendChild(dot);
  }
  card.addEventListener("pointerdown", (event) => {
    if (event.button !== 0) return;
    event.preventDefault();
    card.setPointerCapture(event.pointerId);
    card.classList.add("dragging");
    const start = [event.clientX, event.clientY];
    const origin = positions[component.id].slice();
    const move = (e) => {
      positions[component.id] = [
        Math.max(0, origin[0] + (e.clientX - start[0]) / ZOOM),
        Math.max(0, origin[1] + (e.clientY - start[1]) / ZOOM),
      ];
      moved.add(component.id);
      card.style.left = `${positions[component.id][0] * ZOOM}px`;
      card.style.top = `${positions[component.id][1] * ZOOM}px`;
      drawWires();
    };
    const done = () => {
      card.classList.remove("dragging");
      card.removeEventListener("pointermove", move);
      card.removeEventListener("pointerup", done);
      card.removeEventListener("pointercancel", done);
      savePositions().then(reroute);
    };
    card.addEventListener("pointermove", move);
    card.addEventListener("pointerup", done);
    card.addEventListener("pointercancel", done);
  });
  return card;
}

function draw() {
  host.replaceChildren();
  surface = document.createElement("div");
  surface.className = "od1-surface";
  wires = document.createElementNS(NS, "svg");
  wires.setAttribute("class", "od1-wires");
  surface.appendChild(wires);
  for (const component of components) {
    if (positions[component.id]) surface.appendChild(makeCard(component));
  }
  host.appendChild(surface);
  if (note) {                       // what the view leaves out, such as the insets of a page
    const noteEl = document.createElement("div");
    noteEl.className = "od1-note";
    noteEl.setAttribute("role", "status");
    noteEl.textContent = note;
    host.appendChild(noteEl);
  }
  drawWires();
}

async function open1d() {
  connectAnchor = null;
  one.classList.add("active");
  two.classList.remove("active");
  three.classList.remove("active");
  canvas.hidden = true;
  view3d.hidden = true;
  host.hidden = false;
  const layout = document.getElementById("view-layout");      // the Layout view gives way too
  if (layout) layout.hidden = true;
  document.getElementById("btn-view-layout")?.classList.remove("active");
  host.classList.remove("od1-message");
  host.textContent = "Loading the 1D schematic...";
  try {
    const response = await fetch("/api/scene/1d/model");
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const model = await response.json();
    components = model.components || [];
    links = model.links || [];
    junctions = model.junctions || [];
    marks = model.marks || [];
    positions = model.positions || {};
    note = model.note || "";
    moved = new Set();
    draw();
  } catch (error) {
    host.textContent = `Could not load the 1D scene: ${error.message}. Open the editor through optodraw-gui.`;
    host.classList.add("od1-message");
  }
}

one.addEventListener("click", open1d);
for (const button of [two, three, document.getElementById("btn-view-layout")].filter(Boolean)) {
  button.addEventListener("click", () => {
    host.hidden = true;
    one.classList.remove("active");
    canvas.hidden = false;
  }, true);
}
