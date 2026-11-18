"""Interactive scene HTML export — sidebar, selection, and dimension overlays.

Wraps :class:`~optodraw.renderers.threejs_renderer.ThreeJsRenderer` so mesh
generation stays in one place while the exported page gains authoring UI:
component inventory, click-to-highlight, optional dimension markers, and scene
JSON download (via the existing Three.js export toolbar).
"""

from __future__ import annotations

import html
import json
import math
import re
from pathlib import Path
from typing import Any

from optodraw.core.beam import Beam, FocusingBeam
from optodraw.core.component import Component, Group
from optodraw.core.routing import Route
from optodraw.renderers.dimension_overlay import markers_from_physical_spec
from optodraw.renderers.threejs_renderer import ThreeJsRenderer
from optodraw.schema import _assign_component_ids, _physical_spec_payload


def _threejs_visible_nodes(scene) -> list[Component]:
    """Return scene nodes emitted by :meth:`ThreeJsRenderer._walk` (same order)."""

    nodes: list[Component] = []

    def walk(node: Component) -> None:
        if isinstance(node, Group):
            for child in node.children:
                walk(child)
            return

        if isinstance(node, FocusingBeam):
            return
        if isinstance(node, (Beam, Route)):
            nodes.append(node)
            return

        geo = node.geometry_3d()
        if not geo:
            return
        nodes.append(node)

    walk(scene.root)
    return nodes


def _annotate_scene_data_with_ids(scene, scene_data: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attach stable component ids to Three.js scene-data entries."""

    refs = _assign_component_ids(scene)
    nodes = _threejs_visible_nodes(scene)
    if len(nodes) != len(scene_data):
        return scene_data

    annotated: list[dict[str, Any]] = []
    for node, entry in zip(nodes, scene_data):
        item = dict(entry)
        component_id = refs.get(id(node))
        if component_id:
            item["id"] = component_id
        annotated.append(item)
    return annotated


def _physical_spec_summary(component: Component) -> str:
    """One-line physical metadata for the component sidebar."""

    payload = _physical_spec_payload(component)
    if not payload:
        length = getattr(component, "physical_length_um", None)
        if length is not None:
            return f"length={length:g} µm"
        return ""

    values = payload.get("values") or {}
    parts: list[str] = []
    for key in (
        "length",
        "width",
        "ring_radius",
        "gap",
        "coupling_length",
        "modulation_length",
    ):
        value = values.get(key)
        if value is None:
            continue
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
            parts.append(f"{key}={value:g} µm")
        else:
            parts.append(f"{key}={value}")
        if len(parts) >= 3:
            break
    if not parts and values:
        for key, value in list(values.items())[:3]:
            if value is not None:
                parts.append(f"{key}={value}")
    return ", ".join(parts)


def _sidebar_entries(scene) -> list[dict[str, Any]]:
    """Build sidebar rows (id, type, label, physical summary)."""

    refs = _assign_component_ids(scene)
    entries: list[dict[str, Any]] = []
    for node in _threejs_visible_nodes(scene):
        component_id = refs.get(id(node))
        if not component_id:
            continue
        entries.append(
            {
                "id": component_id,
                "type": getattr(node, "component_type", node.__class__.__name__),
                "label": (getattr(node, "label", "") or "").strip(),
                "physical_spec": _physical_spec_summary(node),
                "color": getattr(node, "color", "#2b6cb0"),
                "opacity": float(getattr(node, "opacity", 1.0)),
            }
        )
    return entries


def _dimension_marker_payload(scene) -> list[dict[str, Any]]:
    """Serialize chip-plane dimension markers for the 3D overlay toggle."""

    refs = _assign_component_ids(scene)
    payload: list[dict[str, Any]] = []
    for node in _threejs_visible_nodes(scene):
        if not hasattr(node, "physical_spec"):
            continue
        try:
            spec = node.physical_spec()
        except Exception:
            continue
        values = getattr(spec, "values", None) or {}
        length = values.get("length") or values.get("length_um")
        width = values.get("width") or values.get("width_um")
        if length is None and width is None:
            continue

        position = node.world_transform.position
        for marker in markers_from_physical_spec(
            position.x,
            position.y,
            length_um=length,
            width_um=width,
        ):
            payload.append(
                {
                    "componentId": refs.get(id(node), ""),
                    "label": marker.label,
                    "x1": marker.x1,
                    "y1": marker.y1,
                    "x2": marker.x2,
                    "y2": marker.y2,
                }
            )
    return payload


def _sidebar_html(entries: list[dict[str, Any]], *, show_authoring_panel: bool = True) -> str:
    rows: list[str] = []
    for entry in entries:
        label_class = "component-label" if entry["label"] else "component-label muted"
        label_line = f'<span class="{label_class}">{html.escape(entry["label"])}</span>'
        spec_line = (
            f'<span class="component-spec">{html.escape(entry["physical_spec"])}</span>'
            if entry["physical_spec"]
            else '<span class="component-spec muted">—</span>'
        )
        rows.append(
            "<li>"
            f'<button type="button" class="component-row" data-component-id="{html.escape(entry["id"])}" '
            f'data-component-type="{html.escape(entry["type"])}">'
            f'<span class="component-id">{html.escape(entry["id"])}</span>'
            f'<span class="component-type">{html.escape(entry["type"])}</span>'
            f"{label_line}{spec_line}"
            "</button></li>"
        )
    body = "\n".join(rows) if rows else '<li class="muted">No components</li>'
    authoring_panel = _authoring_panel_html() if show_authoring_panel else ""
    return f"""
<div id="component-sidebar" data-optodraw-component-sidebar="true">
  <div class="sidebar-title">Components</div>
  <ul id="component-list" class="component-list">
{body}
  </ul>
{authoring_panel}
</div>
"""


def _authoring_panel_html() -> str:
    return """
    <div id="component-authoring-panel" data-optodraw-authoring-panel="true">
        <div class="authoring-title">Authoring</div>
        <div id="authoring-empty" class="authoring-empty">Select a component to edit browser-side metadata.</div>
        <div id="authoring-fields" class="authoring-fields" hidden>
            <label>Label<input type="text" id="author-label" data-author-field="label" /></label>
            <label>Color<input type="color" id="author-color" data-author-field="color" /></label>
            <label>Opacity<span id="author-opacity-value">1.00</span><input type="range" id="author-opacity" data-author-field="opacity" min="0" max="1" step="0.05" /></label>
            <label class="authoring-check"><input type="checkbox" id="author-visible" data-author-field="visible" /> Visible</label>
            <button type="button" id="btn-download-authoring-patch" data-authoring-patch="true">Download patch JSON</button>
        </div>
    </div>
"""


def _sidebar_css() -> str:
    return """
      #component-sidebar { position: absolute; top: 10px; left: 10px; bottom: 14px; width: min(280px, 32vw); z-index: 11; display: flex; flex-direction: column; background: rgba(255,255,255,0.9); border: 1px solid rgba(38,50,63,0.1); border-radius: 10px; box-shadow: 0 8px 24px rgba(15,23,42,0.08); overflow: hidden; }
      #component-sidebar .sidebar-title { font-size: 11px; font-weight: 600; color: #4b5563; letter-spacing: 0.04em; text-transform: uppercase; padding: 10px 12px 8px; border-bottom: 1px solid rgba(38,50,63,0.08); }
      #component-sidebar .component-list { list-style: none; margin: 0; padding: 6px; overflow-y: auto; flex: 1; }
      #component-sidebar .component-row { width: 100%; text-align: left; border: 1px solid transparent; background: transparent; border-radius: 8px; padding: 8px 10px; cursor: pointer; font-family: inherit; color: #1f2933; display: grid; grid-template-columns: 1fr; gap: 2px; }
      #component-sidebar .component-row:hover { background: #eef2f6; border-color: rgba(38,50,63,0.08); }
      #component-sidebar .component-row.selected { background: #e0ecff; border-color: #93c5fd; }
      #component-sidebar .component-id { font-size: 12px; font-weight: 600; color: #16202a; }
      #component-sidebar .component-type { font-size: 11px; color: #64748b; }
      #component-sidebar .component-label { font-size: 11px; color: #334155; }
      #component-sidebar .component-spec { font-size: 10px; color: #475569; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
      #component-sidebar .muted { color: #94a3b8; font-size: 12px; padding: 8px 10px; }
    #component-sidebar #component-authoring-panel { border-top: 1px solid rgba(38,50,63,0.08); padding: 10px 12px 12px; background: rgba(248,250,252,0.9); }
    #component-sidebar .authoring-title { font-size: 11px; font-weight: 600; color: #4b5563; letter-spacing: 0.04em; text-transform: uppercase; margin-bottom: 8px; }
    #component-sidebar .authoring-empty { font-size: 11px; line-height: 1.35; color: #64748b; }
    #component-sidebar .authoring-fields { display: grid; gap: 8px; }
    #component-sidebar .authoring-fields[hidden] { display: none; }
    #component-sidebar .authoring-fields label { display: grid; gap: 4px; font-size: 11px; color: #334155; }
    #component-sidebar .authoring-fields input[type="text"] { width: 100%; box-sizing: border-box; border: 1px solid rgba(38,50,63,0.16); border-radius: 6px; padding: 6px 8px; font-family: inherit; font-size: 12px; }
    #component-sidebar .authoring-fields input[type="color"] { width: 42px; height: 28px; padding: 0; border: 1px solid rgba(38,50,63,0.16); border-radius: 6px; background: #fff; }
    #component-sidebar .authoring-fields input[type="range"] { width: 100%; }
    #component-sidebar .authoring-check { display: flex; align-items: center; gap: 6px; }
    #component-sidebar #author-opacity-value { float: right; color: #64748b; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
    #component-sidebar #btn-download-authoring-patch { width: 100%; font-family: inherit; font-size: 12px; padding: 6px 10px; cursor: pointer; border: 1px solid rgba(38,50,63,0.15); border-radius: 6px; background: #fff; color: #1f2933; }
    #component-sidebar #btn-download-authoring-patch:hover { background: #eef2f6; }
      body[data-optodraw-interactive-scene="true"] #info { left: calc(min(280px, 32vw) + 24px); max-width: calc(100vw - min(280px, 32vw) - 40px); }
"""


def _dimension_toggle_css() -> str:
    return ""                                # the toggle is a button of the bar and takes the bar's look


def _interactive_setup_js() -> str:
    return """
// --- Interactive scene helpers (selection registry) ---
const componentHighlightSets = {};
function registerComponentObject(componentId, object3d) {
  if (!componentId || !object3d) return;
  if (!componentHighlightSets[componentId]) componentHighlightSets[componentId] = new Set();
  componentHighlightSets[componentId].add(object3d);
}
"""


def _authoring_ui_js() -> str:
    return """
const authoringState = {};
const authoringPatch = {};
const originalMaterialColors = new WeakMap();
const originalMaterialOpacities = new WeakMap();
for (const entry of componentSidebarData) {
    const initialColor = /^#[0-9a-fA-F]{6}$/.test(entry.color || '') ? entry.color : '#2b6cb0';
    const initialOpacity = Number.isFinite(Number(entry.opacity)) ? Number(entry.opacity) : 1;
    authoringState[entry.id] = {
        component_id: entry.id,
        component_type: entry.type,
        label: entry.label || '',
        color: initialColor,
        initialColor,
        opacity: initialOpacity,
        initialOpacity,
        visible: true,
    };
}

function activeAuthoringState() {
    return selectedComponentId ? authoringState[selectedComponentId] : null;
}

function updateSidebarLabel(componentId, labelText) {
    let row = null;
    for (const candidate of document.querySelectorAll('.component-row')) {
        if (candidate.dataset.componentId === componentId) {
            row = candidate;
            break;
        }
    }
    if (!row) return;
    const labelNode = row.querySelector('.component-label');
    if (!labelNode) return;
    labelNode.textContent = labelText || '';
    labelNode.classList.toggle('muted', !labelText);
}

function setMaterialOpacity(material, opacity, wasTransparent) {
    material.opacity = opacity;
    material.transparent = wasTransparent || opacity < 1;
    material.needsUpdate = true;
}

function applyAuthoringState(componentId) {
    const state = authoringState[componentId];
    if (!state) return;
    const targets = componentHighlightSets[componentId];
    if (targets) {
        for (const obj of targets) {
            obj.visible = state.visible;
            obj.traverse((child) => {
                if (!child.isMesh || !child.material) return;
                const materials = Array.isArray(child.material) ? child.material : [child.material];
                for (const material of materials) {
                    if (material.color) {
                        if (!originalMaterialColors.has(material)) originalMaterialColors.set(material, material.color.clone());
                        if (state.color.toLowerCase() !== state.initialColor.toLowerCase()) {
                            material.color.set(state.color);
                        } else {
                            material.color.copy(originalMaterialColors.get(material));
                        }
                    }
                    if (!originalMaterialOpacities.has(material)) {
                        originalMaterialOpacities.set(material, { opacity: material.opacity, transparent: material.transparent });
                    }
                    if (state.opacity !== state.initialOpacity) {
                        const original = originalMaterialOpacities.get(material);
                        const factor = state.initialOpacity > 0 ? state.opacity / state.initialOpacity : state.opacity;
                        setMaterialOpacity(material, Math.max(0, Math.min(1, original.opacity * factor)), original.transparent);
                    } else {
                        const original = originalMaterialOpacities.get(material);
                        material.opacity = original.opacity;
                        material.transparent = original.transparent;
                        material.needsUpdate = true;
                    }
                }
            });
        }
    }
    if (componentLabelElements[componentId]) componentLabelElements[componentId].textContent = state.label;
    updateSidebarLabel(componentId, state.label);
}

function recordAuthoringPatch(componentId) {
    const state = authoringState[componentId];
    if (!state) return;
    authoringPatch[componentId] = {
        component_id: state.component_id,
        component_type: state.component_type,
        label: state.label,
        color: state.color,
        opacity: state.opacity,
        visible: state.visible,
    };
}

function syncAuthoringPanel(componentId) {
    const empty = document.getElementById('authoring-empty');
    const fields = document.getElementById('authoring-fields');
    const state = authoringState[componentId];
    if (!empty || !fields || !state) return;
    empty.hidden = true;
    fields.hidden = false;
    document.getElementById('author-label').value = state.label;
    document.getElementById('author-color').value = state.color;
    document.getElementById('author-opacity').value = String(state.opacity);
    document.getElementById('author-opacity-value').textContent = state.opacity.toFixed(2);
    document.getElementById('author-visible').checked = state.visible;
}

function updateActiveAuthoringField(field, value) {
    const state = activeAuthoringState();
    if (!state) return;
    if (field === 'label') state.label = value;
    if (field === 'color') state.color = value;
    if (field === 'opacity') state.opacity = Math.max(0, Math.min(1, Number(value)));
    if (field === 'visible') state.visible = Boolean(value);
    applyAuthoringState(state.component_id);
    recordAuthoringPatch(state.component_id);
    syncAuthoringPanel(state.component_id);
}

function authoringPatchPayload() {
    return {
        schema_version: 'optodraw.interactive_authoring_patch.v1',
        generated_by: 'optodraw interactive scene',
        patches: Object.keys(authoringPatch).sort().map((id) => authoringPatch[id]),
    };
}

function downloadAuthoringPatchJson() {
    const baseName = (document.title || 'optodraw-scene').replace(/ [|] .*$/, '');
    const blob = new Blob([JSON.stringify(authoringPatchPayload(), null, 2)], { type: 'application/json' });
    const link = document.createElement('a');
    link.download = baseName + '.authoring-patch.json';
    link.href = URL.createObjectURL(blob);
    link.click();
    URL.revokeObjectURL(link.href);
}

document.getElementById('author-label')?.addEventListener('input', (event) => updateActiveAuthoringField('label', event.target.value));
document.getElementById('author-color')?.addEventListener('input', (event) => updateActiveAuthoringField('color', event.target.value));
document.getElementById('author-opacity')?.addEventListener('input', (event) => updateActiveAuthoringField('opacity', event.target.value));
document.getElementById('author-visible')?.addEventListener('change', (event) => updateActiveAuthoringField('visible', event.target.checked));
document.getElementById('btn-download-authoring-patch')?.addEventListener('click', downloadAuthoringPatchJson);
"""


def _interactive_ui_js(
    sidebar_entries: list[dict[str, Any]],
    dimension_markers: list[dict[str, Any]],
    *,
    show_dimension_markers: bool,
    dimension_markers_default: bool,
    show_authoring_panel: bool,
) -> str:
    sidebar_json = json.dumps(sidebar_entries, indent=2)
    markers_json = json.dumps(dimension_markers, indent=2)
    default_visible = "true" if dimension_markers_default else "false"
    dim_button_block = ""
    dimension_block = ""
    dim_init_block = ""
    if show_dimension_markers:
        dim_button_block = """
const dimBtn = document.getElementById('btn-toggle-dimensions');
if (dimBtn) {
  dimBtn.addEventListener('click', () => {
    dimensionMarkersGroup.visible = !dimensionMarkersGroup.visible;
    dimBtn.setAttribute('aria-pressed', String(dimensionMarkersGroup.visible));
  });
}
"""
        dimension_block = f"""
function chipToScene(x, y, lift = 0.6) {{
  return new THREE.Vector3(x, lift, -y);
}}

const dimensionMarkersGroup = new THREE.Group();
dimensionMarkersGroup.visible = {default_visible};
scene.add(dimensionMarkersGroup);

for (const marker of dimensionMarkerData) {{
  const start = chipToScene(marker.x1, marker.y1);
  const end = chipToScene(marker.x2, marker.y2);
  const geometry = new THREE.BufferGeometry().setFromPoints([start, end]);
  const line = new THREE.Line(geometry, new THREE.LineBasicMaterial({{ color: 0x374151 }}));
  dimensionMarkersGroup.add(line);
  const div = document.createElement('div');
  div.textContent = marker.label;
  div.style.cssText = 'color:#374151;font-size:10px;background:rgba(255,255,255,0.9);padding:1px 4px;border-radius:3px;border:1px solid rgba(55,65,81,0.2);';
  const label = new CSS2DObject(div);
  label.position.copy(start.clone().add(end).multiplyScalar(0.5));
  dimensionMarkersGroup.add(label);
}}

{dim_button_block}
"""
        dim_init_block = """
const dimToggleBtn = document.getElementById('btn-toggle-dimensions');
if (dimToggleBtn) dimToggleBtn.setAttribute('aria-pressed', String(dimensionMarkersGroup.visible));
"""
    authoring_block = _authoring_ui_js() if show_authoring_panel else ""
    return f"""
// --- Interactive scene authoring UI ---
const componentSidebarData = {sidebar_json};
const dimensionMarkerData = {markers_json};
let selectedComponentId = null;
{dimension_block}
{authoring_block}

function clearSelectionHighlight() {{
  for (const id of Object.keys(componentHighlightSets)) {{
    for (const obj of componentHighlightSets[id]) {{
      obj.traverse((child) => {{
        if (!child.isMesh || !child.material) return;
        if (child.userData.__origEmissive !== undefined) {{
          if (child.material.emissive) child.material.emissive.copy(child.userData.__origEmissive);
          if (child.userData.__origEmissiveIntensity !== undefined) {{
            child.material.emissiveIntensity = child.userData.__origEmissiveIntensity;
          }}
          child.material.needsUpdate = true;
        }}
      }});
    }}
  }}
}}

function applySelectionHighlight(componentId) {{
  clearSelectionHighlight();
  selectedComponentId = componentId;
  const targets = componentHighlightSets[componentId];
  if (!targets) return;
  for (const obj of targets) {{
    obj.traverse((child) => {{
      if (!child.isMesh || !child.material) return;
      if (child.userData.__origEmissive === undefined && child.material.emissive) {{
        child.userData.__origEmissive = child.material.emissive.clone();
        child.userData.__origEmissiveIntensity = child.material.emissiveIntensity ?? 1;
      }}
      if (child.material.emissive) {{
        child.material.emissive.set('#2563eb');
        child.material.emissiveIntensity = 1.4;
        child.material.needsUpdate = true;
      }}
    }});
  }}
}}

for (const btn of document.querySelectorAll('.component-row')) {{
  btn.addEventListener('click', () => {{
    const componentId = btn.dataset.componentId;
    for (const row of document.querySelectorAll('.component-row')) {{
      row.classList.toggle('selected', row.dataset.componentId === componentId);
    }}
        applySelectionHighlight(componentId);
        if (componentAnchors[componentId]) {{
      controls.target.copy(componentAnchors[componentId].position);
      controls.update();
    }}
        if (document.getElementById('component-authoring-panel')) syncAuthoringPanel(componentId);
  }});
}}

{dim_init_block}
"""


def _inject_anchor_registration(html: str) -> str:
    """Tag Three.js objects with component ids for sidebar selection."""

    html = html.replace(
        "function addLabel(parent, text) {",
        "function addLabel(parent, text, componentId = null) {",
        1,
    )
    html = html.replace(
        "  parent.add(label);\n}",
        "  if (componentId) componentLabelElements[componentId] = div;\n  parent.add(label);\n}",
        1,
    )
    for old_call, new_call in (
        ("addLabel(anchor, item.label);", "addLabel(anchor, item.label, item.id);"),
        ("addLabel(plane, item.label);", "addLabel(plane, item.label, item.id);"),
        ("addLabel(fallback, item.label);", "addLabel(fallback, item.label, item.id);"),
        ("addLabel(object3d, item.label);", "addLabel(object3d, item.label, item.id);"),
    ):
        html = html.replace(old_call, new_call)

    replacements = [
        (
            "    scene.add(anchor);",
            "    if (item.id) { anchor.userData.componentId = item.id; componentAnchors[item.id] = anchor; registerComponentObject(item.id, anchor); }\n    scene.add(anchor);",
        ),
        (
            "      scene.add(plane);\n      if (item.label) addLabel(plane, item.label, item.id);",
            "      if (item.id) registerComponentObject(item.id, plane);\n      scene.add(plane);\n      if (item.label) addLabel(plane, item.label, item.id);",
        ),
        (
            "      scene.add(tube);",
            "      if (item.id) registerComponentObject(item.id, tube);\n      scene.add(tube);",
        ),
        (
            "      scene.add(seg);",
            "      if (item.id) registerComponentObject(item.id, seg);\n      scene.add(seg);",
        ),
        (
            "      scene.add(fallback);",
            "      if (item.id) registerComponentObject(item.id, fallback);\n      scene.add(fallback);",
        ),
        (
            "      scene.add(object3d);",
            "      if (item.id) registerComponentObject(item.id, object3d);\n      scene.add(object3d);",
        ),
    ]
    for old, new in replacements:
        html = html.replace(old, new)
    return html


def _inject_interactive_layer(
    html: str,
    *,
    sidebar_entries: list[dict[str, Any]],
    dimension_markers: list[dict[str, Any]],
    show_sidebar: bool,
    show_dimension_markers: bool,
    dimension_markers_default: bool,
    show_authoring_panel: bool,
) -> str:
    if show_sidebar:
        extra_css = _sidebar_css()
        if show_dimension_markers:
            extra_css += _dimension_toggle_css()
        html = html.replace("</style>", f"{extra_css}</style>", 1)
        html = html.replace(
            '<div id="info">',
            f"{_sidebar_html(sidebar_entries, show_authoring_panel=show_authoring_panel)}\n<div id=\"info\">",
            1,
        )
        html = re.sub(
            r"<body([^>]*)>",
            r'<body\1 data-optodraw-interactive-scene="true">',
            html,
            count=1,
        )

    if show_dimension_markers:
        # a button of the 3D page's bar, beside Labels: on or off, with the bar's own look
        ruler = ('<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 17L17 3l4 4L7 21z"/>'
                 '<path d="M7 13l2 2M10 10l2 2M13 7l2 2"/></svg>')
        pressed = "true" if dimension_markers_default else "false"
        labels_anchor = '<div class="od-item" id="anim-section">'
        html = html.replace(
            labels_anchor,
            f'<button type="button" class="od-btn" id="btn-toggle-dimensions" data-dimension-toggle="true" '
            f'aria-pressed="{pressed}" title="Dimensions on or off">{ruler}<span>Dimensions</span></button>\n  '
            + labels_anchor,
            1,
        )

    html = _inject_anchor_registration(html)

    setup_js = _interactive_setup_js()
    html = html.replace(
        "for (const item of sceneData) {",
        f"{setup_js}\nconst componentAnchors = {{}};\nconst componentLabelElements = {{}};\nfor (const item of sceneData) {{",
        1,
    )

    ui_js = _interactive_ui_js(
        sidebar_entries,
        dimension_markers,
        show_dimension_markers=show_dimension_markers,
        dimension_markers_default=dimension_markers_default,
        show_authoring_panel=show_authoring_panel,
    )
    html = html.replace("// --- Animate ---", f"{ui_js}\n// --- Animate ---", 1)
    return html


def export_interactive_html(
    scene,
    path: str | Path | None = None,
    *,
    show_component_sidebar: bool = True,
    show_dimension_markers: bool = True,
    dimension_markers_default: bool = False,
    show_authoring_panel: bool = True,
    **threejs_kwargs: Any,
) -> str:
    """Export an enhanced interactive Three.js HTML viewer for ``scene``.

    Parameters
    ----------
    scene
        Optodraw scene graph.
    path
        Optional output ``.html`` path.
    show_component_sidebar
        When True, render a component inventory with click-to-highlight.
    show_dimension_markers
        When True, add a toolbar toggle for physical dimension overlays.
    dimension_markers_default
        When True, dimension markers start visible.
    show_authoring_panel
        When True, add browser-side label/color/opacity/visibility controls and
        authoring patch JSON download. Requires the component sidebar.
    **threejs_kwargs
        Forwarded to :class:`~optodraw.renderers.threejs_renderer.ThreeJsRenderer`
        (``camera_distance``, ``camera_preset``, ``show_grid``, etc.).
    """

    threejs_kwargs.setdefault("show_export_controls", True)
    renderer = ThreeJsRenderer(scene, **threejs_kwargs)
    scene_data = _annotate_scene_data_with_ids(scene, renderer._collect_scene_data())
    html = renderer._build_html(scene_data)

    sidebar_entries = _sidebar_entries(scene) if show_component_sidebar else []
    dimension_payload = _dimension_marker_payload(scene) if show_dimension_markers else []

    html = _inject_interactive_layer(
        html,
        sidebar_entries=sidebar_entries,
        dimension_markers=dimension_payload,
        show_sidebar=show_component_sidebar,
        show_dimension_markers=show_dimension_markers and bool(dimension_payload),
        dimension_markers_default=dimension_markers_default,
        show_authoring_panel=show_component_sidebar and show_authoring_panel,
    )

    if path is not None:
        Path(path).write_text(html, encoding="utf-8")
    return html
