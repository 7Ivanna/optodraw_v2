// Portable parts use the existing local editor, palette and modal styles.
import { api } from "./api.js";
import { openModal, dialogForm } from "./dialog.js";

const element = (tag, text, cls) => {
  const node = document.createElement(tag);
  if (text) node.textContent = text;
  if (cls) node.className = cls;
  return node;
};

export function newPartDialog() {
  return openModal((card, close) => {
    card.parentElement.style.cssText = "width:100vw;height:100dvh;right:auto;bottom:auto";
    card.style.cssText = "width:min(900px,94vw);max-height:calc(100dvh - 32px);display:flex;flex-direction:column";
    card.setAttribute("aria-label", "New part");
    card.append(element("div", "New part", "od-modal-head"));
    const body = element("div", null, "od-modal-body");
    body.style.cssText = "display:grid;grid-template-columns:repeat(auto-fit,minmax(min(260px,100%),1fr));gap:18px;min-height:0;overflow:auto";
    const fields = element("div"), drawing = element("div");
    fields.style.minWidth = "0"; drawing.style.minWidth = "0";
    body.append(fields, drawing); card.append(body);
    function field(label, type = "text", value = "", parent = fields) {
      const wrap = element("label", label, "od-field");
      const input = element(type === "textarea" ? "textarea" : "input", null, "od-modal-input");
      if (type !== "textarea") input.type = type;
      input.value = value; wrap.append(input); parent.append(wrap); return input;
    }
    const name = field("Qualified name", "text", "user:my/Part");
    const platform = element("select", null, "od-modal-input");
    for (const value of ["on_chip", "free_space", "electronics"]) {
      const option = element("option", value.replaceAll("_", " ")); option.value = value; platform.append(option);
    }
    const platformLabel = element("label", "Platform", "od-field");
    platformLabel.append(platform); fields.append(platformLabel);
    const upload = field("2D SVG", "file"); upload.accept = ".svg";
    const upload1d = field("Optional 1D SVG", "file"); upload1d.accept = ".svg";
    const params = field("Typed parameters (JSON)", "textarea", "{}");
    params.rows = 4;
    params.placeholder = '{"weight":{"type":"float","default":0.5,"min":0,"max":1}}';
    fields.append(element("p", "Parameters store values. They do not stretch the SVG."));
    const tabs = element("div", null, "od-modal-foot"); drawing.append(tabs);
    const preview = element("div"); preview.style.cssText = "height:240px;border:1px solid #cbd5e1;overflow:hidden;background:white";
    drawing.append(preview);
    drawing.append(element("p", "Click the 2D drawing to move the selected port. Coordinates use y up."));
    const portList = element("div"), portFields = element("div"); drawing.append(portList, portFields);
    const message = element("p"); message.setAttribute("role", "status"); card.append(message);
    let svg = "", symbol1d = null, ports = [], active = -1, view = "2d", requestId = 0;
    const buttons = [];
    function button(text, action, parent = tabs) {
      const node = element("button", text, "od-btn od-ghost"); node.type = "button";
      node.addEventListener("click", action); parent.append(node); return node;
    }
    function payload(autoMarks = false) {
      return { name: name.value.trim(), platform: platform.value, svg, symbol_1d: symbol1d,
        ports: autoMarks ? null : ports, parameters: JSON.parse(params.value || "{}") };
    }
    function error(reason) { message.textContent = reason.message || String(reason); }
    function overlay() {
      const root = preview.querySelector("svg"); if (!root || view !== "2d") return;
      root.querySelectorAll("[data-part-port]").forEach(node => node.remove());
      const vb = root.viewBox.baseVal, radius = Math.max(Math.min(vb.width, vb.height)/45, 0.1);
      ports.forEach((port, index) => {
        const node = document.createElementNS("http://www.w3.org/2000/svg", "circle");
        node.setAttribute("cx", port.center[0]); node.setAttribute("cy", -port.center[1]);
        node.setAttribute("r", radius); node.setAttribute("fill", index === active ? "#111" : "white");
        node.setAttribute("stroke", "#111"); node.setAttribute("stroke-width", radius/3);
        node.setAttribute("data-part-port", "1");
        const title = document.createElementNS(node.namespaceURI, "title"); title.textContent = port.name; node.append(title);
        node.addEventListener("click", event => { event.stopPropagation(); active = index; editPorts(); }); root.append(node);
      });
    }
    function editPorts() {
      portList.replaceChildren(); portFields.replaceChildren();
      ports.forEach((port, i) => button(port.name, () => { active = i; editPorts(); }, portList));
      const port = ports[active]; overlay(); if (!port) return;
      const pname = field("Port name", "text", port.name, portFields);
      pname.addEventListener("change", () => { port.name = pname.value.trim(); editPorts(); });
      for (const [label, key, index] of [["X", "center", 0], ["Y", "center", 1], ["Direction (degrees)", "orientation_deg"], ["Width", "width"]]) {
        const input = field(label, "number", index === undefined ? port[key] : port[key][index], portFields);
        input.step = "any";
        input.addEventListener("change", () => {
          if (!input.checkValidity() || !Number.isFinite(Number(input.value))) return;
          if (index === undefined) port[key] = Number(input.value); else port[key][index] = Number(input.value);
          overlay();
        });
      }
      const kinds = element("select", null, "od-modal-input"); kinds.setAttribute("aria-label", "Port kind");
      for (const kind of ["optical", "waveguide", "fiber", "free_space", "electrical", "thermal"]) {
        const option = element("option", kind); option.value = kind; kinds.append(option);
      }
      kinds.value = port.kind; kinds.addEventListener("change", () => { port.kind = kinds.value; }); portFields.append(kinds);
      button("Remove port", () => { ports.splice(active, 1); active = ports.length-1; editPorts(); }, portFields);
    }
    async function refresh(autoMarks = false) {
      if (!svg) return;
      const sequence = ++requestId;
      try {
        const data = payload(autoMarks);
        if (view === "3d") {
          const html = await api.partThreejs(data); if (sequence !== requestId) return;
          const frame = element("iframe"); frame.title = "Schematic 3D part preview";
          frame.style.cssText = "width:100%;height:100%;border:0"; frame.srcdoc = html; preview.replaceChildren(frame);
          message.textContent = "3D is a shallow schematic extrusion, not a physical device model."; return;
        }
        let result;
        try { result = await api.inspectPart(data, view); }
        catch (reason) {
          if (!autoMarks || !reason.message.includes("SVG needs port marks")) throw reason;
          result = await api.inspectPart(payload(), view);
        }
        if (sequence !== requestId) return;
        if (autoMarks) { ports = result.ports; active = ports.length ? 0 : -1; }
        preview.innerHTML = result.svg;
        const root = preview.querySelector("svg");
        root.style.width = "100%"; root.style.height = "100%";
        if (view === "2d") root.addEventListener("click", event => {
          const point = root.createSVGPoint(); point.x = event.clientX; point.y = event.clientY;
          const local = point.matrixTransform(root.getScreenCTM().inverse());
          if (active < 0) { ports.push({name:"p1",center:[0,0],orientation_deg:0,width:0.5,kind:"optical"}); active = 0; }
          ports[active].center = [local.x, -local.y]; editPorts();
        });
        editPorts(); message.textContent = "Review the ports before you save.";
      } catch (reason) { if (sequence === requestId) error(reason); }
    }
    for (const [label, mode] of [["1D", "1d"], ["2D", "2d"], ["3D", "3d"]]) {
      buttons.push(button(label, () => { view = mode; refresh(); }));
    }
    button("Add port", () => {
      let number = ports.length+1; while (ports.some(port => port.name === `p${number}`)) number++;
      ports.push({name:`p${number}`,center:[0,0],orientation_deg:0,width:0.5,kind:"optical"});
      active = ports.length-1; editPorts();
    }, drawing);
    upload.addEventListener("change", async () => {
      try {
        const file = upload.files[0]; if (!file) return;
        if (file.size > 10*1024*1024) throw Error("SVG exceeds the 10 MiB limit.");
        svg = await file.text(); ports = []; active = -1; view = "2d"; await refresh(true);
      } catch (reason) { error(reason); }
    });
    upload1d.addEventListener("change", async () => {
      const file = upload1d.files[0]; symbol1d = file ? await file.text() : null; refresh();
    });
    const footer = element("div", null, "od-modal-foot"); card.append(footer);
    button("Cancel", () => close(null), footer);
    const save = button("Save to My parts", async () => {
      save.disabled = true;
      try { if (!svg) throw Error("Choose a 2D SVG first."); close(await api.savePart(payload())); }
      catch (reason) { error(reason); save.disabled = false; }
    }, footer);
    save.className = "od-btn od-primary";
  });
}

export function installPartsControls({ onChanged, onError, getCatalog }) {
  document.getElementById("btn-new-part").addEventListener("click", async () => {
    const saved = await newPartDialog(); if (saved) await onChanged();
  });
  const file = document.getElementById("file-part");
  document.getElementById("btn-import-part").addEventListener("click", () => file.click());
  file.addEventListener("change", async () => {
    try { if (file.files[0]) { await api.importPart(file.files[0]); await onChanged(); } }
    catch (reason) { onError(reason); } finally { file.value = ""; }
  });
  document.getElementById("btn-export-part").addEventListener("click", async () => {
    const names = Object.keys(getCatalog() || {}).filter(name => name.startsWith("user:"));
    if (!names.length) { onError(Error("My parts is empty. Create or import a part first.")); return; }
    const values = await dialogForm({ title:"Export part", confirmText:"Download", fields:[
      {key:"name",label:"Part",type:"select",options:names,value:names[0]}] });
    if (values) { const link = element("a"); link.href = api.partExportUrl(values.name); link.download = ""; link.click(); }
  });
}
