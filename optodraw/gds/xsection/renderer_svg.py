"""drawsvg renderer for cross-section output stacks."""

from __future__ import annotations

from pathlib import Path
import re
import xml.etree.ElementTree as ET

import drawsvg as draw
from shapely.geometry import MultiPolygon, Polygon

from optodraw.gds.xsection.engine import OutputLayer, OutputStack
from optodraw.gds.xsection.schema import ProcessDefinition, RenderSpec


HATCH_PATTERNS = {
    "none": None,
    "I4": ("diagonal", 4, 4, "#1f2937"),
    "cross": ("cross", 6, 6, "#1f2937"),
    "dots": ("dots", 5, 5, "#1f2937"),
}


def render_output_stack_to_svg(
    stack: OutputStack,
    process: ProcessDefinition,
    output_path: Path,
    *,
    include_legend: bool = True,
    view_bounds: tuple[float, float, float, float] | None = None,
) -> Path:
    svg_text = render_output_stack_svg(stack, process, include_legend=include_legend, view_bounds=view_bounds)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(svg_text, encoding="utf-8")
    return output_path


def render_output_stack_svg(
    stack: OutputStack,
    process: ProcessDefinition,
    *,
    include_legend: bool = True,
    view_bounds: tuple[float, float, float, float] | None = None,
) -> str:
    render = process.render
    y0, y1, z0, z1 = view_bounds if view_bounds is not None else _view_bounds(stack, render)
    width = render.width_px
    height = render.height_px
    if width <= 0 or height <= 0:
        raise ValueError("Cross-section SVG width_px and height_px must be positive")
    legend_width = 180 if include_legend and render.legend == "right" else 0
    layers = sorted(stack.layers, key=lambda item: item.z_order)
    for layer in layers:
        if layer.hatch not in HATCH_PATTERNS:
            raise ValueError(f"Unsupported cross-section hatch {layer.hatch!r} on layer {layer.name!r}")
    canvas_height = max(height, 30 + 22 * len(layers)) if legend_width else height

    drawing = draw.Drawing(width + legend_width, canvas_height, origin="top-left")
    drawing.append(draw.Rectangle(0, 0, width + legend_width, canvas_height, fill="#ffffff"))

    scale_y, scale_z, offset_y, offset_z = _fit_transform(y0, y1, z0, z1, width, height, render.z_exaggeration)

    defs = draw.Group(id="xsection-defs")
    for hatch_name, spec in HATCH_PATTERNS.items():
        if spec is None:
            continue
        pattern = _make_hatch_pattern(hatch_name, spec)
        defs.append(pattern)
    drawing.append(defs)

    used_layer_ids: set[str] = set()
    for layer in layers:
        base_id = re.sub(r"[^A-Za-z0-9_-]+", "_", f"layer-{layer.name}").strip("_")
        group_id = base_id
        suffix = 2
        while group_id in used_layer_ids:
            group_id = f"{base_id}-{suffix}"
            suffix += 1
        used_layer_ids.add(group_id)
        group = draw.Group(id=group_id)
        for element in _geometry_to_elements(
            layer.geometry,
            fill=layer.color,
            opacity=layer.opacity,
            stroke=layer.stroke,
            hatch=layer.hatch,
            scale_y=scale_y,
            scale_z=scale_z,
            offset_y=offset_y,
            offset_z=offset_z,
        ):
            group.append(element)
        drawing.append(group)

    if render.show_box_line:
        drawing.append(
            draw.Line(
                offset_y + scale_y * y0,
                offset_z + scale_z * 0.0,
                offset_y + scale_y * y1,
                offset_z + scale_z * 0.0,
                stroke="#1f2937",
                stroke_width=0.7,
                stroke_dasharray="4,3",
            )
        )

    if include_legend and render.legend == "right":
        _append_legend(drawing, layers, x=width + 16, y=24)

    return drawing.as_svg()


def render_layer_svgs(
    stack: OutputStack,
    process: ProcessDefinition,
    output_dir: Path,
) -> dict[str, Path]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    view_bounds = _view_bounds(stack, process.render)
    for index, layer in enumerate(stack.layers, start=1):
        single = OutputStack(
            process_name=stack.process_name,
            cut_label=stack.cut_label,
            layers=[layer],
            internal_regions=stack.internal_regions,
        )
        safe_name = re.sub(r"[^A-Za-z0-9_-]+", "_", layer.name).strip("_") or "unnamed"
        path = output_dir / f"layer_{index}_{safe_name}.svg"
        render_output_stack_to_svg(single, process, path, include_legend=False, view_bounds=view_bounds)
        key = layer.name if layer.name not in paths else f"{layer.name} ({index})"
        paths[key] = path
    return paths


def _view_bounds(stack: OutputStack, render: RenderSpec) -> tuple[float, float, float, float]:
    y_values: list[float] = []
    z_values: list[float] = []
    for layer in stack.layers:
        if layer.geometry.is_empty:
            continue
        min_y, min_z, max_y, max_z = layer.geometry.bounds
        y_values.extend([min_y, max_y])
        z_values.extend([min_z, max_z])
    if not y_values:
        y_values = [-1.0, 1.0]
        z_values = [-1.0, 1.0]
    y0 = min(y_values) - render.y_margin_um
    y1 = max(y_values) + render.y_margin_um
    z0 = min(z_values) - 0.1
    z1 = max(z_values) + 0.1
    return y0, y1, z0, z1


def _fit_transform(
    y0: float,
    y1: float,
    z0: float,
    z1: float,
    width: float,
    height: float,
    z_exaggeration: float,
) -> tuple[float, float, float, float]:
    margin = 24.0
    plot_width = max(width - 2 * margin, 1.0)
    plot_height = max(height - 2 * margin, 1.0)
    if z_exaggeration <= 0:
        raise ValueError("z_exaggeration must be positive")
    span_y = max(y1 - y0, 1e-6)
    span_z = max((z1 - z0) * z_exaggeration, 1e-6)
    scale = min(plot_width / span_y, plot_height / span_z)
    drawn_width = span_y * scale
    drawn_height = span_z * scale
    offset_y = margin + (plot_width - drawn_width) / 2.0 - scale * y0
    offset_z = margin + (plot_height - drawn_height) / 2.0 + scale * z_exaggeration * z1
    return scale, -scale * z_exaggeration, offset_y, offset_z


def _geometry_to_elements(
    geometry: MultiPolygon,
    *,
    fill: str,
    opacity: float,
    stroke: str,
    hatch: str,
    scale_y: float,
    scale_z: float,
    offset_y: float,
    offset_z: float,
):
    if geometry.is_empty:
        return []
    elements = []
    geoms = geometry.geoms if hasattr(geometry, "geoms") else [geometry]
    for poly in geoms:
        if not isinstance(poly, Polygon):
            continue
        path_data = _polygon_path(poly, scale_y, scale_z, offset_y, offset_z)
        elements.append(
            draw.Path(
                d=path_data,
                fill=fill if hatch == "none" else f"url(#hatch-{hatch})",
                fill_rule="evenodd",
                fill_opacity=opacity,
                stroke=stroke,
                stroke_width=0.35,
            )
        )
    return elements


def _polygon_path(poly: Polygon, scale_y: float, scale_z: float, offset_y: float, offset_z: float) -> str:
    parts = []
    for ring in (poly.exterior, *poly.interiors):
        coords = list(ring.coords)
        if not coords:
            continue
        y0, z0 = coords[0]
        parts.append(f"M {offset_y + scale_y * y0} {offset_z + scale_z * z0}")
        for y, z in coords[1:]:
            parts.append(f"L {offset_y + scale_y * y} {offset_z + scale_z * z}")
        parts.append("Z")
    return " ".join(parts)


def _make_hatch_pattern(name: str, spec: tuple[str, float, float, str]):
    kind, sx, sy, color = spec
    pattern = draw.Pattern(
        id=f"hatch-{name}",
        width=sx,
        height=sy,
        patternUnits="userSpaceOnUse",
    )
    if kind == "diagonal":
        pattern.append(draw.Lines(0, sy, sx, 0, stroke=color, stroke_width=0.5))
    elif kind == "cross":
        pattern.append(draw.Lines(0, sy, sx, 0, stroke=color, stroke_width=0.4))
        pattern.append(draw.Lines(0, 0, sx, sy, stroke=color, stroke_width=0.4))
    elif kind == "dots":
        pattern.append(draw.Circle(sx / 2, sy / 2, 0.6, fill=color))
    return pattern


def _append_legend(drawing: draw.Drawing, layers: list[OutputLayer], *, x: float, y: float) -> None:
    cursor_y = y
    for layer in layers:
        fill = layer.color if layer.hatch == "none" else f"url(#hatch-{layer.hatch})"
        drawing.append(draw.Rectangle(x, cursor_y, 18, 12, fill=fill, stroke=layer.stroke, stroke_width=0.35))
        drawing.append(draw.Text(layer.name, 11, x + 26, cursor_y + 10, fill="#102a43"))
        cursor_y += 22


def svg_dom_summary(svg_text: str) -> dict[str, int | list[str]]:
    root = ET.fromstring(svg_text)

    def tag(name: str) -> str:
        return name.split("}")[-1]

    layer_ids = []
    path_count = 0
    pattern_count = 0
    for element in root.iter():
        local = tag(element.tag)
        element_id = element.attrib.get("id", "")
        if local == "g" and element_id.startswith("layer-"):
            layer_ids.append(element_id)
        if local == "path":
            path_count += 1
        if local == "pattern":
            pattern_count += 1
    return {
        "layer_count": len(layer_ids),
        "layer_ids": layer_ids,
        "path_count": path_count,
        "pattern_count": pattern_count,
    }
