// Auto-generated properties form for the selected component.
//
// Parameter names come from /api/catalog/<name> (the registry's declared
// parameters); types are inferred from the component's current spec values, with
// smart coercion on edit (numbers, booleans, strings). `center` and `angle` get
// dedicated controls.

import { FREE_SHAPES } from "./palette.js";
import { createWavelengthPicker } from "./wavelength.js";

// Escape text that can carry user or uploaded-file content before it goes
// through innerHTML. Property ids, layer names and workspace names all do.
const esc = (s) =>
  String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

function coerce(raw) {
  const v = String(raw).trim();
  if (v === "") return "";
  if (v === "true") return true;
  if (v === "false") return false;
  if (/^-?\d*\.?\d+(e-?\d+)?$/i.test(v)) return Number(v);
  return v;
}

// Numbers typed with commas or spaces between them: a region, a span, a cut.
export const numbers = (text) => String(text).split(/[\s,]+/).filter(Boolean).map(Number);
// Two points typed as "x1, y1, x2, y2": a section's cut.
export const points = (text) => { const v = numbers(text); return [v.slice(0, 2), v.slice(2, 4)]; };

// The source fields of each inset kind the editor makes, as [record key, label, how it is typed]: a list is a select,
// "file" picks another file, "stack" a bundled stack; "numbers", "points" and "words" take commas between. A field
// shows only when the record holds its key (a 3D view of a scene has no z_scale).
const INSET_FIELDS = {
  Text: [["text", "Text", "lines"], ["size_pt", "Size (pt)", "number"], ["align", "Align", ["left", "center", "right"]]],
  Equation: [["latex", "Formula (mathtext)", "text"]],
  Image: [["path", "Picture", "file"], ["scale_um_per_px", "µm per pixel", "number"],
          ["image_kind", "Kind", ["measured", "drawn", "render"]]],
  SvgFile: [["path", "SVG file", "file"], ["drop_text", "Drop text", "words"]],
  PdfFile: [["path", "PDF file", "file"], ["page", "Page", "number"]],
  SceneView: [["view", "View", ["2d", "1d"]]],
  Timing: [["span", "Span (start, end)", "numbers"], ["unit", "Unit", "text"]],
  GdsView: [["path", "GDS file", "file"], ["stack", "Stack", "stack"], ["region", "Region x0, y0, x1, y1 (µm)", "numbers"]],
  SectionView: [["cut", "Cut x1, y1, x2, y2 (µm)", "points"], ["z_scale", "Height scale (auto or a number)", "value"]],
  View3D: [["direction", "View", ["isometric", "top", "front", "side"]],
           ["projection", "Projection", ["perspective", "parallel"]], ["z_scale", "Height scale", "number"]],
};
// A typed field as the record holds it; the other kinds keep the text.
const READ = {
  number: (text) => (text.trim() === "" ? null : Number(text)),
  numbers,
  points,
  words: (text) => text.split(",").map((word) => word.trim()).filter(Boolean),
  value: coerce,
};

export function createProperties({ formEl, emptyEl, onChange, onDelete, onAlign, onDistribute, onRotate, onFlip, onDuplicate, onCrossSection, onAttachTech, onApplyPdk, getPdks, onApplyStack, getStacks, onResetLayers, onInsetSource, onInsetFile, onInsetSize }) {
  // Apply edits live without letting a stale timer overwrite a later change.
  function bindLive(input, commit) {
    let timer = null;
    input.addEventListener("input", () => {
      clearTimeout(timer);
      timer = setTimeout(() => {
        timer = null;
        if (input.isConnected) commit();
      }, 300);
    });
    input.addEventListener("change", () => {
      clearTimeout(timer);
      timer = null;
      commit();
    });
  }

  let lightRefresh = null;      // fetches the selected part's light controls again (set by show)

  function clear() {
    lightRefresh = null;
    formEl.hidden = true;
    formEl.innerHTML = "";
    emptyEl.hidden = false;
  }

  function btn(label, onClick, cls = "") {
    const b = document.createElement("button");
    b.type = "button";
    b.className = cls ? `pf-btn ${cls}` : "pf-btn";
    b.textContent = label;
    b.addEventListener("click", onClick);
    return b;
  }

  // Small icon-only action button for the title row (duplicate / delete).
  function iconBtn(iconId, title, onClick, cls = "") {
    const b = document.createElement("button");
    b.type = "button";
    b.className = `pt-iconbtn ${cls}`.trim();
    b.title = title;
    b.innerHTML = `<svg class="ic ic-sm"><use href="#${iconId}"/></svg>`;
    b.addEventListener("click", onClick);
    return b;
  }

  function showMulti(ids) {
    formEl.innerHTML = "";
    emptyEl.hidden = true;
    formEl.hidden = false;

    formEl.appendChild(titleRow(`${ids.length} components`, "multi"));

    const mkRow = (labels) => {
      const row = document.createElement("div");
      row.className = "btn-grid";
      for (const [text, fn] of labels) row.appendChild(btn(text, fn));
      formEl.appendChild(row);
    };
    formEl.appendChild(sectionTitle("Transform"));
    mkRow([["⟲ 90°", () => onRotate && onRotate(90)], ["⟳ 90°", () => onRotate && onRotate(-90)]]);
    mkRow([["Flip ↔", () => onFlip && onFlip("h")], ["Flip ↕", () => onFlip && onFlip("v")]]);
    formEl.appendChild(sectionTitle("Align — to the first selected"));
    mkRow([["Left", () => onAlign("left")], ["Center", () => onAlign("centerx")], ["Right", () => onAlign("right")]]);
    mkRow([["Top", () => onAlign("top")], ["Middle", () => onAlign("centery")], ["Bottom", () => onAlign("bottom")]]);
    formEl.appendChild(sectionTitle("Distribute — equal spacing"));
    mkRow([["Horizontally", () => onDistribute("x")], ["Vertically", () => onDistribute("y")]]);

    const actions = document.createElement("div");
    actions.className = "props-actions";
    actions.appendChild(btn("Duplicate", () => onDuplicate()));
    actions.appendChild(btn("Delete", () => onDelete(), "btn-danger"));
    formEl.appendChild(actions);
  }

  function field(labelText, input) {
    const wrap = document.createElement("div");
    wrap.className = "field";
    const label = document.createElement("label");
    label.textContent = labelText;
    wrap.append(label, input);
    return wrap;
  }

  // Compact inline row for a boolean toggle (checkbox beside its label).
  function inlineField(labelText, input) {
    const wrap = document.createElement("div");
    wrap.className = "field field-inline";
    const label = document.createElement("label");
    label.textContent = labelText;
    wrap.append(input, label);
    return wrap;
  }

  // A 0–1 opacity slider with a live readout (better than a number box).
  function opacitySlider(value, onCommit) {
    const wrap = document.createElement("div");
    wrap.className = "opacity-slider";
    const range = document.createElement("input");
    range.type = "range"; range.min = "0"; range.max = "1"; range.step = "0.05";
    range.value = isFinite(value) ? value : 1;
    const out = document.createElement("span");
    out.className = "opacity-val";
    const show = () => { out.textContent = Number(range.value).toFixed(2); };
    show();
    range.addEventListener("input", show);
    range.addEventListener("change", () => onCommit(Number(range.value)));
    wrap.append(range, out);
    return wrap;
  }

  function makeInput(value) {
    const input = document.createElement("input");
    if (typeof value === "boolean") {
      input.type = "checkbox";
      input.checked = value;
    } else if (typeof value === "number") {
      input.type = "number";
      input.step = "any";
      input.value = value;
    } else {
      input.type = "text";
      input.value = value ?? "";
    }
    return input;
  }

  function sectionTitle(text) {
    const el = document.createElement("div");
    el.className = "props-section";
    el.textContent = text;
    return el;
  }

  // snake_case -> "Sentence case" for friendly param labels
  function prettyName(s) {
    s = String(s).replace(/_/g, " ").replace(/\bopacity\b/i, "opacity").trim();
    return s.charAt(0).toUpperCase() + s.slice(1);
  }

  // A boolean toggle (a checkbox the `.field-inline` CSS renders as a switch).
  function toggleSwitch(checked, onChange) {
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.checked = !!checked;
    cb.addEventListener("change", () => onChange(cb.checked));
    return cb;
  }

  // Collapsible section (Tidy3D-style). Returns the body element to fill.
  function addSection(host, title, opts = {}) {
    const sec = document.createElement("div");
    sec.className = "insp-sec" + (opts.collapsed ? " insp-sec--collapsed" : "");
    const head = document.createElement("button");
    head.type = "button";
    head.className = "insp-sec-head";
    head.innerHTML = `<span class="insp-chevron"></span><span class="insp-sec-name">${title}</span>`;
    const body = document.createElement("div");
    body.className = "insp-sec-body";
    head.addEventListener("click", () => sec.classList.toggle("insp-sec--collapsed"));
    sec.append(head, body);
    host.appendChild(sec);
    return body;
  }

  const _isOpacity = (name) => /opacity/i.test(name);

  // Build the correct widget for a declared parameter, typed from param_meta so
  // booleans are toggles and numbers are numeric (even before a value is set).
  function controlFor(name, rawValue, meta, onCommit) {
    const type = (meta && meta.type) || (typeof rawValue === "boolean" ? "bool" : typeof rawValue === "number" ? "number" : "text");
    const fallback = meta ? meta.default : undefined;
    const value = (rawValue !== undefined && rawValue !== null) ? rawValue : fallback;

    if (meta && Array.isArray(meta.choices) && meta.choices.length) {
      const sel = document.createElement("select");
      sel.className = "props-select";
      for (const opt of meta.choices) {
        const o = document.createElement("option");
        o.value = opt;
        o.textContent = String(opt).replace(/_/g, " ");
        if (String(opt) === String(value)) o.selected = true;
        sel.appendChild(o);
      }
      sel.addEventListener("change", () => onCommit(sel.value));
      return field(prettyName(name), sel);
    }
    if (type === "bool") {
      const f = field(prettyName(name), toggleSwitch(value, (v) => onCommit(v)));
      f.classList.add("field-switch");
      return f;
    }
    if (type === "number") {
      if (_isOpacity(name)) {
        return field(prettyName(name), opacitySlider(Number(value ?? 1), (v) => onCommit(v)));
      }
      const input = document.createElement("input");
      input.type = "number"; input.step = "any";
      input.value = (value !== undefined && value !== null) ? value : "";
      bindLive(input, () => { if (input.value !== "") onCommit(Number(input.value)); });
      return field(prettyName(name), input);
    }
    const input = document.createElement("input");
    input.type = "text";
    input.value = value ?? "";
    bindLive(input, () => onCommit(input.value));
    return field(prettyName(name), input);
  }

  function deleteAction(id) {
    const actions = document.createElement("div");
    actions.className = "props-actions";
    actions.appendChild(btn("Delete", () => onDelete(id), "btn-danger"));
    return actions;
  }

  function titleRow(id, type, actions = []) {
    const title = document.createElement("div");
    title.className = "props-title";
    const name = document.createElement("div");
    name.className = "pt-name";
    name.innerHTML = `<span class="pt-id">${esc(id)}</span><span class="ptype">${esc(type)}</span>`;
    title.appendChild(name);
    if (actions.length) {
      const box = document.createElement("div");
      box.className = "pt-actions";
      for (const a of actions) box.appendChild(iconBtn(a.icon, a.title, a.onClick, a.danger ? "pt-danger" : ""));
      title.appendChild(box);
    }
    return title;
  }

  // Standard quick actions for a single selected entry.
  function entryActions(id) {
    const acts = [];
    if (onDuplicate) acts.push({ icon: "i-duplicate", title: "Duplicate (⌘D)", onClick: () => onDuplicate() });
    acts.push({ icon: "i-trash", title: "Delete (⌫)", danger: true, onClick: () => onDelete(id) });
    return acts;
  }

  // Instance port list: kind-colored rows; click copies "id.port" for Links/routing.
  function portsSection(host, entry, ports) {
    const body = addSection(host, "Ports", { collapsed: ports.length > 8 });
    const list = document.createElement("div");
    list.className = "ports-list";
    body.appendChild(list);
    for (const p of ports) {
      const kind = String(p.kind || "optical");
      const kindClass = kind.toLowerCase().replace(/[^a-z0-9_-]/g, "-");
      const row = document.createElement("button");
      row.type = "button";
      row.className = `port-row port-${kindClass}`;
      row.title = `Copy “${entry.id}.${p.name}” — paste into Links or route text`;
      row.innerHTML =
        `<span class="port-dot"></span><span class="port-name">${esc(p.name)}</span>` +
        `<span class="port-kind">${esc(kind)}</span><svg class="ic ic-sm port-copy"><use href="#i-duplicate"/></svg>`;
      let statusTimer = null;
      row.addEventListener("click", async () => {
        const ref = `${entry.id}.${p.name}`;
        const k = row.querySelector(".port-kind");
        clearTimeout(statusTimer);
        try {
          await navigator.clipboard.writeText(ref);
          row.classList.add("copied");
          if (k) k.textContent = "copied";
        } catch (_) {
          row.classList.remove("copied");
          if (k) k.textContent = "copy failed";
        }
        statusTimer = setTimeout(() => { row.classList.remove("copied"); if (k) k.textContent = kind; }, 900);
      });
      list.appendChild(row);
    }
  }

  function showBeam(entry) {
    formEl.appendChild(titleRow(entry.id, "Beam", entryActions(entry.id)));

    const picker = createWavelengthPicker(Number(entry.wavelength) || 633, (nm) =>
      onChange(entry.id, { wavelength: nm }));
    formEl.appendChild(field("wavelength (nm) — sets color", picker.el));

    const width = makeInput(Number(entry.width) || 0.8);
    width.step = "0.1";
    width.addEventListener("change", () =>
      onChange(entry.id, { width: Number(width.value) || 0.8 }));
    formEl.appendChild(field("width", width));
    if (entry.traced_from) return; // a traced ray takes its look from its source

    const opacity = makeInput(entry.opacity ?? "");
    opacity.type = "number";
    opacity.step = "0.05";
    opacity.min = "0";
    opacity.max = "1";
    opacity.placeholder = "from Scene settings";
    opacity.addEventListener("change", () =>
      onChange(entry.id, { opacity: opacity.value === "" ? null : Number(opacity.value) }));
    formEl.appendChild(field("opacity", opacity));

    const lane = makeInput(Number(entry.offset) || 0);
    lane.step = "0.1";
    lane.addEventListener("change", () =>
      onChange(entry.id, { offset: Number(lane.value) || 0 }));
    formEl.appendChild(field("lane (distance from the axis)", lane));
  }

  // Route inspector: width/taper (empty = derived from the connected ports),
  // path style, and bend radius — edits go through the generic update endpoint.
  function showRoute(entry) {
    formEl.appendChild(titleRow(entry.id, entry.kind || "route", entryActions(entry.id)));
    const body = addSection(formEl, "Waveguide");

    const numField = (label, key, placeholder) => {
      const input = document.createElement("input");
      input.type = "number"; input.step = "any";
      input.value = entry[key] ?? "";
      input.placeholder = placeholder;
      bindLive(input, () => {
        onChange(entry.id, { [key]: input.value === "" ? null : Number(input.value) });
      });
      body.appendChild(field(label, input));
    };
    numField("Width", "width", "auto — start port width");
    numField("Taper to (end width)", "width2", "auto — end port width");
    const hint = document.createElement("div");
    hint.className = "field-hint";
    hint.textContent = "Empty = derived from the connected ports; mismatched ports taper automatically.";
    body.appendChild(hint);

    const sel = document.createElement("select");
    sel.className = "props-select";
    for (const [value, text] of [["manhattan", "manhattan (right angles)"], ["smooth", "smooth S-bend"], ["straight", "direct"]]) {
      const o = document.createElement("option");
      o.value = value; o.textContent = text;
      if ((entry.path_type || "manhattan") === value) o.selected = true;
      sel.appendChild(o);
    }
    sel.addEventListener("change", () => onChange(entry.id, { path_type: sel.value }));
    body.appendChild(field("Path type", sel));
    const smoothRow = field("Rounded corners", toggleSwitch(!!entry.smooth, (v) => onChange(entry.id, { smooth: v })));
    smoothRow.classList.add("field-switch");
    body.appendChild(smoothRow);

    const bend = document.createElement("input");
    bend.type = "number"; bend.step = "any";
    bend.value = entry.bend_radius ?? "";
    bend.placeholder = "10";
    bindLive(bend, () => { if (bend.value !== "") onChange(entry.id, { bend_radius: Number(bend.value) }); });
    body.appendChild(field("Bend radius", bend));
  }

  function gdsLayerSection(host, entry, layers, materials = []) {
    // One unified "layer stack" picker — bundled open PDKs + any installed PDKs,
    // plus small actions to bring your own file or grab a template.
    const stacks = (getStacks && getStacks()) || [];
    const pdks = (getPdks && getPdks()) || [];
    if ((onApplyStack && stacks.length) || (onApplyPdk && pdks.length)) {
      const sel = document.createElement("select");
      const blank = document.createElement("option");
      blank.value = ""; blank.textContent = "Apply a layer stack…";
      sel.appendChild(blank);
      const addGroup = (label, items, prefix) => {
        if (!items.length) return;
        const g = document.createElement("optgroup");
        g.label = label;
        for (const it of items) {
          const opt = document.createElement("option");
          opt.value = `${prefix}:${it.id}`; opt.textContent = it.label;
          g.appendChild(opt);
        }
        sel.appendChild(g);
      };
      addGroup("Bundled (open PDKs)", onApplyStack ? stacks : [], "stack");
      // only show installed PDKs that aren't already bundled, to avoid duplicates
      const stackIds = new Set(stacks.map((s) => s.id));
      const extraPdks = pdks.filter((p) => !stackIds.has(p.id));
      addGroup("Installed PDKs", onApplyPdk ? extraPdks : [], "pdk");
      sel.addEventListener("change", () => {
        const [kind, id] = sel.value.split(/:(.+)/);
        if (kind === "stack") onApplyStack(entry.id, id);
        else if (kind === "pdk") onApplyPdk(entry.id, id);
      });
      host.appendChild(field("Layer stack (z + thickness)", sel));
    }

    const links = document.createElement("div");
      links.className = "gds-stack-links";
      if (onAttachTech) {
        const a = document.createElement("a");
        a.href = "#"; a.textContent = "Attach your own file";
        a.title = "Stack YAML / GDS3D techfile / .lyd25 (z), .lyp (colors), or a KLayout technology .zip (both)";
        a.addEventListener("click", (e) => { e.preventDefault(); onAttachTech(entry.id); });
        links.appendChild(a);
        const f = document.createElement("a");
        f.href = "#"; f.textContent = "Attach technology folder";
        f.title = "A KLayout technology folder: the .lyt, the .lyp it names (colors) and d25/*.lyd25 (z). Only these files are sent.";
        f.addEventListener("click", (e) => { e.preventDefault(); onAttachTech(entry.id, "folder"); });
        links.appendChild(f);
      }
      const t = document.createElement("a");
      t.href = "/api/stacks/template";
      t.setAttribute("download", "layer-stack-template.yaml");
      t.textContent = "Download template";
      t.title = "For an NDA foundry: fill this in, then ‘Attach your own file’";
      links.appendChild(t);
      if (onResetLayers) {
        const r = document.createElement("a");
        r.href = "#"; r.textContent = "Reset";
        r.title = "Clear all layer overrides (start fresh — fixes stale z from a previous file)";
        r.addEventListener("click", (e) => { e.preventDefault(); onResetLayers(entry.id); });
        links.appendChild(r);
      }
      host.appendChild(links);
    const overrides = JSON.parse(JSON.stringify(entry.layer_stack || {}));
    const layerGrid = document.createElement("div");
    layerGrid.className = "gds-layers-grid";  // responsive: 1 col narrow, 2+ when widened
    host.appendChild(layerGrid);
    for (const ly of layers) {
      const card = document.createElement("div");
      card.className = "gds-layer-card";

      // Header: visibility, color swatch, name/key, polygon count.
      const head = document.createElement("div");
      head.className = "gds-layer-head";
      const vis = document.createElement("input");
      vis.type = "checkbox"; vis.checked = ly.visible !== false; vis.title = "Visible";
      const color = document.createElement("input");
      color.type = "color"; color.title = "Layer color";
      color.value = /^#[0-9a-f]{6}$/i.test(ly.color || "") ? ly.color : "#888888";
      const label = document.createElement("span");
      label.className = "gds-layer-label";
      label.textContent = "";
      const nameEl = document.createElement("b");
      nameEl.textContent = ly.name;
      label.append(nameEl, ` · ${ly.key}`);
      const count = document.createElement("span");
      count.className = "gds-layer-count";
      count.textContent = `${ly.polygon_count} ▦`;
      count.title = `${ly.polygon_count} polygons`;
      head.append(vis, color, label, count);

      // Controls: thickness, z, per-layer material.
      const ctl = document.createElement("div");
      ctl.className = "gds-layer-ctl";
      // a layer with no height assigned shows empty fields, never a made-up default
      const assigned = ly.thickness != null && ly.z != null;
      const thick = document.createElement("input");
      thick.type = "number"; thick.step = "any"; thick.min = "0"; thick.required = assigned;
      thick.value = shown(ly.thickness); thick.className = "gds-num"; thick.placeholder = "none";
      const zoff = document.createElement("input");
      zoff.type = "number"; zoff.step = "any"; zoff.required = assigned;
      zoff.value = shown(ly.z); zoff.className = "gds-num"; zoff.placeholder = "none";
      const mat = document.createElement("select");
      mat.className = "gds-mat";
      const blankMat = document.createElement("option");
      blankMat.value = ""; blankMat.textContent = ly.material ? "material…" : "none";
      mat.appendChild(blankMat);
      // an assigned material missing from the list still shows as itself, never as "none"
      const listed = ly.material && !materials.includes(ly.material) ? [...materials, ly.material] : materials;
      for (const m of listed) {
        const opt = document.createElement("option");
        opt.value = m; opt.textContent = m;
        mat.appendChild(opt);
      }
      mat.value = ly.material || "";
      ctl.append(labeled("th", thick), labeled("z", zoff), mat);

      card.append(head, ctl);
      const missing = [!assigned && "No height assigned (type th and z).", !ly.material && "No material assigned."];
      if (missing.some(Boolean)) {
        const note = document.createElement("div");
        note.className = "gds-layer-note";
        note.textContent = missing.filter(Boolean).join(" ");
        card.append(note);
      }

      const commit = () => {
        if (!thick.checkValidity() || !zoff.checkValidity()) return;
        // a height is written once both fields hold a number; until then only the look changes
        const typed = thick.value !== "" && zoff.value !== "";
        if (!typed && (thick.value !== "" || zoff.value !== "")) return;
        const height = typed ? { thickness: Number(thick.value), z_offset: Number(zoff.value) } : {};
        if (typed && (!Number.isFinite(height.thickness) || !Number.isFinite(height.z_offset))) return;
        overrides[ly.key] = {
          ...(overrides[ly.key] || {}),
          visible: vis.checked,
          color: color.value,
          ...height,
          ...(mat.value ? { material_preset: mat.value } : {}),
        };
        onChange(entry.id, { layer_stack: overrides });
      };
      vis.addEventListener("change", commit);
      color.addEventListener("change", commit);
      mat.addEventListener("change", commit);
      bindLive(thick, commit);
      bindLive(zoff, commit);
      layerGrid.appendChild(card);
    }
  }

  // 0.20000000000000018 is float noise from the layer stack arithmetic: show six significant digits
  const shown = (v) => (v == null ? "" : Number(Number(v).toPrecision(6)));

  // A tiny inline label wrapping a control (for the GDS layer thickness/z fields).
  function labeled(text, input) {
    const wrap = document.createElement("label");
    wrap.className = "gds-inline";
    wrap.append(document.createTextNode(text), input);
    return wrap;
  }

  function gdsCrossSectionSection(host, entry) {
    // the cut, its looks and their options live in the cross-section panel; here is the way in
    host.appendChild(btn("Open cross-section", () => onCrossSection(entry.id, { pct: 0.5, label: "A-A'" }), "btn-primary-wide"));
    const hint = document.createElement("div");
    hint.className = "field-hint";
    hint.textContent = "To cut along a line, open the Layout view, press M, click two points, then Cut along ruler.";
    host.appendChild(hint);
  }

  // One source field of an inset: a change builds the inset again (onInsetSource).
  function sourceField(id, key, label, how, value) {
    let input;
    if (how === "file") {
      input = btn(value ? String(value).split("/").pop() : "Pick a file", () => onInsetFile(id, key));
      input.title = value ? `${value}: click to pick another file` : "Pick the file";
    } else if (Array.isArray(how) || how === "stack") {
      input = document.createElement("select");
      input.className = "props-select";
      const options = how === "stack" ? getStacks().map((stack) => [stack.id, stack.label]) : how.map((v) => [v, v]);
      for (const [v, text] of options) input.add(new Option(text, v));
      input.value = value ?? "";
      input.addEventListener("change", () => onInsetSource(id, { [key]: input.value }));
    } else {
      input = document.createElement(how === "lines" ? "textarea" : "input");
      if (how === "number") { input.type = "number"; input.step = "any"; }
      input.value = Array.isArray(value) ? value.flat().join(", ") : (value ?? "");
      bindLive(input, () => onInsetSource(id, { [key]: (READ[how] || String)(input.value) }));
    }
    input.setAttribute("aria-label", label);
    return field(label, input);
  }

  // An inset's source in place of part fields: the record fields that build it, a Rebuild button, its drawing's notes.
  function insetSourceSection(entry) {
    const fields = INSET_FIELDS[entry.source.kind];
    const notes = entry.fragment ? entry.fragment.notes || [] : ["Not built: pick its file, or Rebuild."];
    if (!fields && !notes.length) return;
    const body = addSection(formEl, "Source");
    for (const [key, label, how] of (fields || []).filter(([key]) => key in entry.source)) {
      body.appendChild(sourceField(entry.id, key, label, how, entry.source[key]));
    }
    for (const text of notes) {
      const hint = document.createElement("div");
      hint.className = "field-hint";
      hint.textContent = text;
      body.appendChild(hint);
    }
    if (fields) body.appendChild(btn("Rebuild", () => onInsetSource(entry.id, {}, true), "btn-primary-wide"));
  }

  function show(entry, describe, materials = [], gdsLayers = null, ports = null) {
    formEl.innerHTML = "";
    emptyEl.hidden = true;
    formEl.hidden = false;

    if (entry.path !== undefined) { // beam
      showBeam(entry);
      return;
    }
    if (entry.from !== undefined || (entry.points !== undefined && entry.kind !== undefined)) {
      showRoute(entry); // waveguide / fiber / electrical route
      return;
    }

    formEl.appendChild(titleRow(entry.id, entry.type, entryActions(entry.id)));

    const meta = (describe && describe.param_meta) || {};
    const LONG = new Set(["source", "cell_name", "name", "filename", "path"]);
    const PLACEMENT = new Set(["center", "angle", "label"]);
    const CONTEXT = new Set([
      "process_context", "oxide_opacity", "handle_opacity", "context_edge_opacity",
      "box_depth", "cladding_top", "handle_thickness",
    ]);
    const isGds = entry.type === "GDSModel";
    const inset = entry.type === "Inset";
    const free = inset && (!entry.source || FREE_SHAPES.has(entry.source.kind));
    // an inset's width (and a free shape's height) builds it again at that size, as a corner drag does
    const insetSize = (name, v) => onInsetSize(entry.id, {
      width: Number(entry.width ?? 50), ...(free && entry.height != null ? { height: Number(entry.height) } : {}),
      [name]: Number(v) });

    // -- Placement ----------------------------------------------------------
    const place = addSection(formEl, "Placement");
    const labelInput = makeInput(entry.label ?? "");
    bindLive(labelInput, () => onChange(entry.id, { label: labelInput.value }));
    place.appendChild(field("Label", labelInput));

    const center = entry.center || [0, 0];
    const cx = makeInput(Number(center[0]) || 0);
    const cy = makeInput(Number(center[1]) || 0);
    cx.title = "X"; cy.title = "Y";
    const commitCenter = () =>
      onChange(entry.id, { center: [Number(cx.value) || 0, Number(cy.value) || 0] });
    bindLive(cx, commitCenter);
    bindLive(cy, commitCenter);
    const pair = document.createElement("div");
    pair.className = "xy-pair";
    pair.append(cx, cy);
    place.appendChild(field("Position", pair));
    const angleInput = makeInput(Number(entry.angle) || 0);
    bindLive(angleInput, () => onChange(entry.id, { angle: Number(angleInput.value) || 0 }));
    place.appendChild(field("Angle °", angleInput));

    if (inset && entry.source) insetSourceSection(entry);


    // -- Parameters (typed from param_meta: toggles for bool, etc.) ---------
    const declared = (describe && describe.parameters || []).filter(
      (p) => !PLACEMENT.has(p) && !CONTEXT.has(p) && !(inset && p === "height" && !free),
    );
    if (declared.length) {
      const body = addSection(formEl, "Parameters");
      // a catalogue part saved on its default part number has no ``part`` in its entry
      const partNo = entry.part || (describe && describe.default_part);
      const drawnSizes = describe && describe.part_sizes && describe.part_sizes[partNo];
      if (drawnSizes) {
        const changed = declared.filter((n) => n.endsWith("_mm") && entry[n] != null);
        const hint = document.createElement("div");
        hint.className = "field-hint";
        hint.textContent = changed.length
          ? `Changed from the ${partNo} drawing: ${changed.map((n) => prettyName(n.slice(0, -3))).join(", ")}. Clear a size to go back to the drawing.`
          : `Sizes from the ${partNo} drawing (mm). Type a size to change it.`;
        body.appendChild(hint);
      }
      const pg = document.createElement("div");
      pg.className = "param-grid";
      body.appendChild(pg);
      for (const name of declared) {
        const customParameter = entry.part_definition && !["scale", "variant"].includes(name);
        const value = customParameter ? entry.parameters?.[name] : entry[name];
        const drawn = drawnSizes;
        if (drawn && name.endsWith("_mm")) {
          // a catalogue part's size: empty shows the drawing's value; a number sets it by hand; clearing it goes
          // back to the drawing
          if (drawn[name] === undefined && value == null) continue;      // this part number has no such size
          const input = document.createElement("input");
          input.type = "number"; input.step = "any"; input.min = "0";
          input.value = value != null ? value : "";
          input.placeholder = drawn[name] !== undefined ? String(drawn[name]) : "";
          input.title = `${partNo} drawing: ${drawn[name]} mm`;
          if (value != null) input.classList.add("is-changed");
          input.addEventListener("change", () => {
            const v = input.value.trim();
            input.classList.toggle("is-changed", v !== "");
            onChange(entry.id, { [name]: v === "" ? null : Number(v) });
          });
          pg.appendChild(field(prettyName(name.slice(0, -3)) + " (mm)", input));
          continue;
        }
        const f = controlFor(name, value, meta[name], (v) => (inset && (name === "width" || name === "height")
          ? insetSize(name, v)
          : onChange(entry.id, customParameter ? { parameters: { [name]: v } } : { [name]: v })));
        const isBool = (meta[name] && meta[name].type === "bool") || f.classList.contains("field-inline");
        const isText = (meta[name] && meta[name].type === "text") || LONG.has(name);
        if (isBool || isText) f.classList.add("field-wide");
        pg.appendChild(f);
      }
    }

    // -- Ports (structural: names + kinds; click to copy an "id.port" ref) ---
    if (ports && ports.length) portsSection(formEl, entry, ports);

    // -- 3D mount (the base drawn under a free-space optic: post or stage) ---
    const STRUCTURAL_BASE = new Set([
      "OpticalTable", "Breadboard", "Baseplate", "OpticalPost",
      "PlatformMount", "TranslationStage", "RotationStage",
    ]);
    const beamOptic = !isGds && describe
      && (describe.category === "optics" || describe.category === "devices" || describe.category === "samples")
      && describe.platform === "free_space" && !STRUCTURAL_BASE.has(entry.type);
    if (beamOptic) {
      const mountBody = addSection(formEl, "3D mount");
      const sel = document.createElement("select");
      sel.className = "props-select";
      // "none": no post, the part stays at its height (held by cage rods, a tower, or a mount of its own)
      for (const [val, txt] of [["post", "Post (pedestal)"], ["post_beam", "Post to the beam axis"], ["stage", "Stage (translation)"], ["xyz_stage", "Stage (XYZ)"], ["rotation_stage", "Stage (rotation)"], ["none", "None (no post)"]]) {
        const o = document.createElement("option");
        o.value = val; o.textContent = txt;
        if (val === (entry.base_mount || "post")) o.selected = true;
        sel.appendChild(o);
      }
      sel.addEventListener("change", () => onChange(entry.id, { base_mount: sel.value }));
      mountBody.appendChild(field("Base under optic", sel));
      // blank: the part follows the beam (the scene's height, or a periscope's exit); a number sets the
      // height of its run, and the periscopes on each side follow it
      const height = document.createElement("input");
      height.type = "number"; height.step = "1"; height.min = "4"; height.max = "120";
      height.placeholder = "follows the beam";
      if (entry.beam_height !== undefined && entry.beam_height !== null) height.value = entry.beam_height;
      height.addEventListener("change", () => {
        const v = height.value.trim();
        onChange(entry.id, { beam_height: v === "" ? null : Number(v) });
      });
      mountBody.appendChild(field("Beam height (3D)", height));
      // its height: above the beam plane on a post (the post grows), above the table otherwise
      const lift = document.createElement("input");
      lift.type = "number"; lift.step = "1";
      lift.value = entry.z !== undefined && entry.z !== null ? entry.z : 0;
      lift.addEventListener("change", () => {
        const v = lift.value.trim();
        onChange(entry.id, { z: v === "" || Number(v) === 0 ? null : Number(v) });
      });
      mountBody.appendChild(field("Height z (3D)", lift));
      // turns out of the table plane (3D; 2D draws the part from above): about the part's own beam axis (x),
      // where 90 stands a fold up off the table, and across the beam (y), where a positive tilt turns a face up
      for (const [key, label] of [["rotation_x", "Rotation about x (°)"], ["rotation_y", "Rotation about y (°)"]]) {
        const turn = document.createElement("input");
        turn.type = "number"; turn.step = "15"; turn.min = "-180"; turn.max = "180";
        turn.value = entry[key] !== undefined && entry[key] !== null ? entry[key] : 0;
        turn.addEventListener("change", () => {
          const v = turn.value.trim();
          onChange(entry.id, { [key]: v === "" || Number(v) === 0 ? null : Number(v) });
        });
        mountBody.appendChild(field(label, turn));
      }
    }

    // -- Light (the settings that drive the 3D light) --------------------------
    // The server says which controls the part has (heater power, modulator drive, ring tuning) with their range and
    // value, and turns a value into the engine's parameter. This code only draws sliders and sends the values. The
    // controls are fetched again after every scene change: a new source wavelength moves a ring's tuning.
    {
      const lightBody = addSection(formEl, "Light");
      const section = lightBody.closest(".insp-sec") || lightBody.parentElement;
      let seq = 0;
      const render = (controls) => {
        lightBody.replaceChildren();
        section.style.display = controls.length ? "" : "none";
        for (const c of controls) {
          const row = document.createElement("div");
          row.className = "light-row";
          row.dataset.key = c.key;
          const head = document.createElement("div");
          head.className = "light-head";
          const name = document.createElement("label");
          name.textContent = c.label;
          const out = document.createElement("span");
          out.className = "opacity-val light-val";
          const range = document.createElement("input");
          range.type = "range";
          range.setAttribute("min", c.min); range.setAttribute("max", c.max); range.setAttribute("step", c.step);
          range.value = c.value;                       // a value outside the range pins the knob at the end
          range.setAttribute("aria-label", c.label);
          const off = c.value < c.min || c.value > c.max;
          const show = (value, away) => {
            out.textContent = `${Number(value).toFixed(c.kind === "drive" ? 2 : 1)} ${c.unit}` + (away ? " (off range)" : "");
          };
          show(c.value, off);
          range.addEventListener("input", () => show(range.value, false));
          range.addEventListener("change", () => onChange(entry.id, { light: { [c.key]: Number(range.value) } }));
          head.append(name, out);
          row.append(head, range);
          if (c.kind === "tuning") row.title = "0 is on resonance. One step is one linewidth of this ring alone.";
          lightBody.appendChild(row);
        }
      };
      const load = () => {
        const mine = ++seq;
        return fetch(`/api/component/${encodeURIComponent(entry.id)}/light`)
          .then((r) => (r.ok ? r.json() : { controls: [] }))
          .then((data) => { if (mine === seq && lightBody.isConnected) render(data.controls || []); })
          .catch(() => { if (mine === seq && lightBody.isConnected) render([]); });
      };
      lightRefresh = load;
      load();
    }

    // -- Appearance ---------------------------------------------------------
    // An annotation takes a colour only when it names one (a note, a region), and an opacity only as an inset, which
    // fades as one layer: an inset's drawing keeps its own colours. GDS sets material per layer, not per die; an
    // annotation draws in 2D only, with no material.
    const annotation = describe?.category === "annotation";
    const tints = !annotation || (describe.parameters || []).includes("color");
    const fades = !annotation || inset;
    const material = materials.length && !isGds && !annotation;
    const app = tints || fades || material ? addSection(formEl, "Appearance") : null;
    if (tints || fades) {
      const styleRow = document.createElement("div");
      styleRow.className = "style-row";
      if (tints) {
        const color = document.createElement("input");
        color.type = "color";
        color.value = /^#[0-9a-f]{6}$/i.test(entry.color || "") ? entry.color : "#4488ff";
        color.title = "Tint color — affects beams and simple shapes (realistic optics keep their own colors)";
        color.addEventListener("change", () => onChange(entry.id, { color: color.value }));
        styleRow.appendChild(color);
      }
      if (fades) {
        styleRow.appendChild(opacitySlider(Number(entry.opacity ?? 1), (v) => onChange(entry.id, { opacity: v })));
      }
      app.appendChild(field(tints && fades ? "Color · opacity" : tints ? "Color" : "Opacity", styleRow));
    }
    if (material) {
      const sel = document.createElement("select");
      const blank = document.createElement("option");
      blank.value = ""; blank.textContent = "(default)";
      sel.appendChild(blank);
      for (const m of materials) {
        const opt = document.createElement("option");
        opt.value = m; opt.textContent = m;
        sel.appendChild(opt);
      }
      sel.value = entry.material_preset || "";
      sel.addEventListener("change", () => { if (sel.value) onChange(entry.id, { material_preset: sel.value }); });
      app.appendChild(field("Material", sel));
    }

    // -- GDS-only sections --------------------------------------------------
    if (isGds) {
      gdsLayerSection(addSection(formEl, "GDS layers"), entry, gdsLayers || [], materials);

      const ctxNames = (describe && describe.parameters || []).filter((p) => CONTEXT.has(p));
      if (ctxNames.length) {
        const body = addSection(formEl, "Process stack (SiO₂ / etch)", { collapsed: true });
        const note = document.createElement("div");
        note.className = "field-hint";
        note.textContent = "Auto BOX + top-oxide on handle Si; air layers (OX_OPEN / DT) are carved out.";
        body.appendChild(note);
        const cpg = document.createElement("div");
        cpg.className = "param-grid";
        body.appendChild(cpg);
        for (const name of ctxNames) {
          const f = controlFor(name, entry[name], meta[name], (v) => onChange(entry.id, { [name]: v }));
          if ((meta[name] && meta[name].type === "bool") || _isOpacity(name)) f.classList.add("field-wide");
          cpg.appendChild(f);
        }
      }

      if (onCrossSection) gdsCrossSectionSection(addSection(formEl, "Cross-section"), entry);
    }
  }

  return { show, showMulti, clear, refreshLight: () => (lightRefresh ? lightRefresh() : null) };
}
