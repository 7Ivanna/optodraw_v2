"""Reusable electronics, probing, packaging, and mixed-signal primitives.

This module keeps each electronics device as a single editable component class.
The small helper functions at the top only build common renderer dictionaries,
normalize common options, or share small geometry calculations. Public users
should usually instantiate the component classes below; contributors changing
visuals can start in the relevant component and follow its local helper methods.

Coordinate convention
---------------------
2D geometry uses ``x``/``y`` values in the component-local plane. Three.js-style
3D geometry uses ``x`` for horizontal placement, ``y`` for height above the
layout plane, and ``z`` as the negated 2D ``y`` coordinate. The conversion is
handled by the ``_box3d``, ``_cylinder3d``, and ``_offset_geometry_3d`` helpers.
"""

from __future__ import annotations

import math
from typing import Any, Iterable, Literal

from optodraw.core.component import Component
from optodraw.core.ports import Port
from optodraw.core.transform import Transform, Vec3


GOLD = "#d6a43a"
GOLD_DARK = "#8f6a18"
INK = "#1f2937"
BOARD_GREEN = "#2f6f57"
BOARD_DARK = "#1f4f3b"
BOARD_THICKNESS = 1.2       # the PCB in 3D; an edge-launch connector's pin lies on its top
COPPER = "#c8892b"
CERAMIC = "#d7dde6"
MEMS_SILICON = "#6f8494"
SOLDER = "#c6d0d8"
SIGNAL_COLORS = {
    "voltage": "#b24b4b",
    "current": "#2a9d6f",
    "rf": "#5b5fc7",
    "clock": "#e79d1a",
    "digital": "#546a7b",
}
CHIP_BODY = "#222a36"
CHIP_FACE = "#313b49"
CHIP_EDGE = "#111827"
PIN_METAL = "#c9c4b8"
PIN_SHADOW = "#8d8a82"
ANALOG_BLUE = "#6aa0b8"
DIGITAL_BLUE = "#7288a4"
TIA_PURPLE = "#8b789b"
CONVERTER_TEAL = "#5b9596"
IC_BODY_THICKNESS = 1.7

# Legible diagram defaults for packaging primitives (µm). Physical truth lives in
# ``PhysicalSpec`` / ports; schematic entries act as visibility floors.
ELECTRONICS_SCHEMATIC_TABLES: dict[str, dict[str, float]] = {
    "_shared": {
        "thickness": 0.24,
    },
    "electrical_pad": {
        "width": 32.0,
        "height": 32.0,
        "thickness": 0.28,
    },
    "pad_opening": {
        "width": 30.0,
        "height": 30.0,
        "clearance": 4.0,
        "thickness": 0.16,
    },
    "gsg_probe_pad": {
        "pad_width": 32.0,
        "pad_height": 32.0,
        "gap": 8.0,
    },
    "rf_launch": {
        "length": 58.0,
        "pad_width": 26.0,
        "pad_height": 9.0,
        "signal_width": 3.2,
        "ground_width": 5.0,
        "gap": 6.0,
        "thickness": 0.22,
    },
    "wirebond": {
        "width": 1.4,
        "sag_min": 6.0,
    },
    "metal_route": {
        "width": 1.6,
        "thickness": 0.18,
    },
    "via_stack": {
        "pad_radius": 2.4,
        "via_radius": 0.85,
        "pitch": 2.4,
        "thickness": 0.8,
    },
    "heater_pad": {
        "heater_length": 36.0,
        "heater_width": 4.0,
        "contact_width": 8.0,
        "contact_height": 13.0,
        "thickness": 0.22,
    },
    "thermal_phase_shifter": {
        "length": 72.0,
        "waveguide_width": 1.1,
        "heater_length": 42.0,
        "heater_width": 4.0,
        "contact_width": 8.0,
        "contact_height": 13.0,
        "heater_offset": 5.0,
        "thickness": 0.22,
    },
    "interposer": {
        "length": 78.0,
        "width": 42.0,
        "bump_radius": 2.2,
    },
    "solder_bump_grid": {
        "pitch_x": 8.0,
        "pitch_y": 8.0,
        "bump_radius": 1.6,
    },
}




def _init_component(component: Component, center, angle: float, *, color: str, opacity: float, label: str) -> None:
    """Initialize the common Component fields used by all electronics classes.

    Parameters
    ----------
    component : Component
        Component instance being initialized.
    center : tuple[float, float] | Vec3
        Component center in layout coordinates.
    angle : float
        Rotation angle in degrees.
    color : str
        Primary component color used by 2D and 3D renderers.
    opacity : float
        Visual opacity passed through to geometry dictionaries.
    label : str
        Optional display label stored on the component.
    """

    component.color = color
    component.opacity = opacity
    component.label = label
    component.transform = Transform.from_2d(*component._parse_center(center).as_2d(), angle)
    component._parent = None
    component._id = ""




def _rect(cx: float, cy: float, width: float, height: float, *, fill: str, opacity: float = 1.0, stroke: str = "none", stroke_width: float = 0.0) -> dict[str, Any]:
    """Return a renderer dictionary for a 2D rectangle.

    The rectangle is centered at ``(cx, cy)`` and sized with ``width`` and
    ``height`` in local layout units.
    """

    return {
        "type": "rect",
        "cx": cx,
        "cy": cy,
        "w": width,
        "h": height,
        "fill": fill,
        "opacity": opacity,
        "stroke": stroke,
        "stroke_width": stroke_width,
    }




def _circle(cx: float, cy: float, radius: float, *, fill: str, opacity: float = 1.0, stroke: str = "none", stroke_width: float = 0.0) -> dict[str, Any]:
    """Return a renderer dictionary for a 2D circle centered at ``(cx, cy)``."""

    return {
        "type": "circle",
        "cx": cx,
        "cy": cy,
        "r": radius,
        "fill": fill,
        "opacity": opacity,
        "stroke": stroke,
        "stroke_width": stroke_width,
    }




def _line(
    x1: float, y1: float, x2: float, y2: float, *, stroke: str, stroke_width: float, opacity: float = 1.0, stroke_dasharray: str | None = None
) -> dict[str, Any]:
    """Return a renderer dictionary for a straight 2D line segment."""

    data: dict[str, Any] = {
        "type": "line",
        "x1": x1,
        "y1": y1,
        "x2": x2,
        "y2": y2,
        "stroke": stroke,
        "stroke_width": stroke_width,
        "opacity": opacity,
    }
    if stroke_dasharray:
        data["stroke_dasharray"] = stroke_dasharray
    return data




def _polyline(
    points: Iterable[tuple[float, float]], *, stroke: str, stroke_width: float, opacity: float = 1.0, stroke_dasharray: str | None = None
) -> dict[str, Any]:
    """Return a rounded, open 2D polyline renderer dictionary."""

    data: dict[str, Any] = {
        "type": "polyline",
        "points": [(x, y, 0.0) for x, y in points],
        "stroke": stroke,
        "stroke_width": stroke_width,
        "fill": "none",
        "opacity": opacity,
        "linecap": "round",
        "linejoin": "round",
        "closed": False,
    }
    if stroke_dasharray:
        data["stroke_dasharray"] = stroke_dasharray
    return data




def _polygon(points: Iterable[tuple[float, float]], *, fill: str, opacity: float = 1.0, stroke: str = "none", stroke_width: float = 0.0) -> dict[str, Any]:
    """Return a 2D polygon renderer dictionary from local ``(x, y)`` points."""

    return {
        "type": "polygon",
        "points": [(x, y, 0.0) for x, y in points],
        "fill": fill,
        "opacity": opacity,
        "stroke": stroke,
        "stroke_width": stroke_width,
    }




def _text(
    text: str,
    x: float,
    y: float,
    *,
    size: float,
    fill: str,
    opacity: float = 1.0,
    text_anchor: str = "middle",
    font_weight: str = "bold",
) -> dict[str, Any]:
    """Return a 2D text renderer dictionary.

    Parameters mirror the SVG-style text fields consumed by OptoDraw renderers:
    ``text_anchor`` controls horizontal alignment, and ``font_weight`` allows
    symbols such as DAC/ADC/TIA labels to stay legible in dense diagrams.
    """

    return {
        "type": "text",
        "text": text,
        "x": x,
        "y": y,
        "size": size,
        "fill": fill,
        "opacity": opacity,
        "text_anchor": text_anchor,
        "font_weight": font_weight,
    }




def _box3d(
    length: float,
    width: float,
    thickness: float,
    *,
    x: float,
    y: float,
    color: str,
    z_offset: float = 0.0,
    rotation_y: float = 0.0,
    metalness: float = 0.65,
    roughness: float = 0.34,
) -> dict[str, Any]:
    """Return a Three.js box dictionary for a 2D footprint extruded into 3D.

    Parameters
    ----------
    length, width : float
        Footprint dimensions in local 2D layout units.
    thickness : float
        Vertical box thickness in 3D units.
    x, y : float
        Local 2D center position. ``y`` is negated into the 3D ``z`` axis.
    color : str
        Material color.
    z_offset : float
        Extra height offset above the layout plane.
    rotation_y : float
        Optional rotation around the 3D ``y`` axis, useful for wirebond bars. A bar along the layout direction
        (dx, dy) takes ``atan2(dy, dx)``: the turn carries 3D +x to (cos, 0, -sin), and layout y is 3D -z.
    metalness, roughness : float
        Three.js material controls.
    """

    data: dict[str, Any] = {
        "shape": "box",
        "width": length,
        "height": thickness,
        "depth": width,
        "position": [x, thickness / 2.0 + z_offset, -y],
        "material": {"color": color, "metalness": metalness, "roughness": roughness},
    }
    if rotation_y:
        data["rotation"] = [0.0, rotation_y, 0.0]
    return data




def _cylinder3d(radius: float, height: float, *, x: float, y: float, color: str, z_offset: float = 0.0, metalness: float = 0.55, roughness: float = 0.36) -> dict[str, Any]:
    """Return a vertical 3D cylinder at a local 2D footprint position."""

    return {
        "shape": "cylinder",
        "radius": radius,
        "height": height,
        "position": [x, height / 2.0 + z_offset, -y],
        "material": {"color": color, "metalness": metalness, "roughness": roughness},
    }




def _solder_bump_3d(x: float, y: float, *, radius: float) -> dict[str, Any]:
    """Return a rounded solder bump using a lathed side profile.

    The bump is intentionally freestanding: it does not include a substrate, so
    it can be placed on dies, interposers, or package drawings without forcing a
    backing layer into the component.
    """

    return {
        "shape": "lathe_profile",
        "points": [
            [0.0, 0.0],
            [radius * 0.82, 0.0],
            [radius * 0.82, radius * 0.52],
            [radius * 0.7, radius * 0.9],
            [radius * 0.38, radius * 1.26],
            [0.0, radius * 1.42],
        ],
        "segments": 24,
        "position": [x, 0.0, -y],
        "material": {"color": SOLDER, "metalness": 0.62, "roughness": 0.28},
    }




def _style_key(visual_style: str) -> str:
    """Normalize visual style aliases to ``symbolic``, ``publication``, ``presentation``, or ``physical``.

    ``symbolic`` is schematic/line-art, ``publication`` is clean 2D drawing,
    ``presentation`` adds gloss/highlights for slides, and ``physical`` exposes
    package-like details such as pins, bumps, or traces.
    """

    style = (visual_style or "publication").strip().lower().replace("-", "_")
    aliases = {
        "1d": "symbolic",
        "line": "symbolic",
        "black_line": "symbolic",
        "paper": "publication",
        "schematic": "publication",
    }
    style = aliases.get(style, style)
    if style not in {"symbolic", "publication", "presentation", "physical"}:
        raise ValueError("visual_style must be one of: symbolic, publication, presentation, physical")
    return style




def _scaled(value: float, scale: float) -> float:
    """Scale a positive geometric value while enforcing a small minimum scale."""

    return float(value) * max(float(scale), 0.05)


def _ports_on_plan(plan: dict[str, tuple[float, float, float]], unit: float, width: float) -> dict[str, Port]:
    """Electrical ports at the points of a pic's plan: ``plan`` maps a name to (x, y, outward angle) in cm of the
    pic, ``unit`` is scene units per cm. The 2D art is that pic, so each wire ends on the lead the art draws."""

    return {name: Port(name, Vec3(x * unit, y * unit, 0.0), orientation_deg=facing, width=width, kind="electrical")
            for name, (x, y, facing) in plan.items()}




def _grid_positions(count: int, pitch: float) -> list[float]:
    """Return centered grid coordinates for ``count`` sites at ``pitch`` spacing."""

    count = max(int(count), 1)
    pitch = float(pitch)
    if count == 1:
        return [0.0]
    span = pitch * (count - 1)
    return [-span / 2.0 + index * pitch for index in range(count)]




def _edge_positions(count: int, span: float, margin: float) -> list[float]:
    """Return centered coordinates along an edge while respecting a margin."""

    count = max(int(count), 1)
    usable = max(span - 2.0 * margin, span * 0.25)
    if count == 1:
        return [0.0]
    start = usable / 2.0
    step = usable / (count - 1)
    return [start - index * step for index in range(count)]




def _polygon_centroid(points: list[tuple[float, float]]) -> tuple[float, float]:
    """Compute a stable centroid for polygon labels.

    Degenerate polygons fall back to the arithmetic mean so labels remain
    well-defined even when a contributor experiments with very small dimensions.
    """

    if len(points) < 3:
        if not points:
            return 0.0, 0.0
        return sum(point[0] for point in points) / len(points), sum(point[1] for point in points) / len(points)

    signed_area = 0.0
    centroid_x = 0.0
    centroid_y = 0.0
    for index, (x0, y0) in enumerate(points):
        x1, y1 = points[(index + 1) % len(points)]
        cross = x0 * y1 - x1 * y0
        signed_area += cross
        centroid_x += (x0 + x1) * cross
        centroid_y += (y0 + y1) * cross
    if abs(signed_area) <= 1e-9:
        return sum(point[0] for point in points) / len(points), sum(point[1] for point in points) / len(points)
    signed_area *= 0.5
    return centroid_x / (6.0 * signed_area), centroid_y / (6.0 * signed_area)




def _converter_kind(kind: str) -> Literal["dac", "adc"]:
    """Normalize converter kind strings for DAC/ADC symbol helpers."""

    kind_key = (kind or "dac").strip().lower()
    if kind_key not in {"dac", "adc"}:
        raise ValueError("converter kind must be one of: dac, adc")
    return "adc" if kind_key == "adc" else "dac"




def _converter_outline(kind: str, length: float, width: float) -> tuple[list[tuple[float, float]], tuple[float, float], tuple[float, float]]:
    """Return the local DAC or ADC polygon plus left/right connection points.

    DACs taper toward the analog output; ADCs taper from the analog input into a
    wider digital side. The returned connection points let the symbol draw lines
    that meet the polygon exactly.
    """

    symbol_length = length * 0.62
    symbol_width = width * 0.56
    half_length = symbol_length / 2.0
    half_width = symbol_width / 2.0
    shoulder_x = symbol_length * 0.14
    if _converter_kind(kind) == "adc":
        points = [(-half_length, 0.0), (-shoulder_x, half_width), (half_length, half_width), (half_length, -half_width), (-shoulder_x, -half_width)]
    else:
        points = [(-half_length, half_width), (shoulder_x, half_width), (half_length, 0.0), (shoulder_x, -half_width), (-half_length, -half_width)]
    return points, (-half_length, 0.0), (half_length, 0.0)




def _converter_symbol_2d(kind: str, length: float, width: float, label: str, *, fill: str = CONVERTER_TEAL, stroke: str = INK, line_width: float = 1.0, opacity: float = 1.0) -> list[dict[str, Any]]:
    """Build the 2D DAC/ADC symbol children used by converter classes."""

    points, input_end, output_start = _converter_outline(kind, length, width)
    label_x, label_y = _polygon_centroid(points)
    text_size = max(width * 0.24, 4.1)
    return [
        _line(-length / 2.0, 0.0, input_end[0], input_end[1], stroke=stroke, stroke_width=line_width, opacity=opacity),
        _polygon(points, fill=fill, opacity=opacity, stroke=stroke, stroke_width=max(line_width * 0.18, 0.45)),
        _line(output_start[0], output_start[1], length / 2.0, 0.0, stroke=stroke, stroke_width=line_width, opacity=opacity),
        _text(label, label_x, label_y, size=text_size, fill="#ffffff", opacity=1.0),
    ]




def _converter_top_3d(kind: str, length: float, width: float, label: str, *, z_offset: float, fill: str = CONVERTER_TEAL) -> list[dict[str, Any]]:
    """Build the 3D top-mark (accent band + bold label) for DAC/ADC chip packages."""

    return _chip_label_3d(_ROLE_ACCENT[_converter_kind(kind)], label, length, width, z_offset)




def _normalize_tia_mode(mode: str) -> str:
    """Normalize TIA mode aliases to ``tia`` or ``integrator``."""

    mode_key = (mode or "tia").strip().lower().replace("-", "_")
    aliases = {"opamp": "tia", "integrated": "integrator", "int": "integrator"}
    mode_key = aliases.get(mode_key, mode_key)
    if mode_key not in {"tia", "integrator"}:
        raise ValueError("tia mode must be one of: tia, integrator")
    return mode_key




def _opamp_label(mode: str) -> str:
    """Return the text mark placed inside a TIA or integrator symbol."""

    return "∫" if _normalize_tia_mode(mode) == "integrator" else "TIA"




def _opamp_outline(length: float, width: float) -> tuple[list[tuple[float, float]], float, float]:
    """Return a near-equilateral op-amp triangle sized for a component footprint."""

    body_width = width * 0.74
    body_length = min(length * 0.62, body_width * 0.94)
    half_length = body_length / 2.0
    half_width = body_width / 2.0
    return [(-half_length, -half_width), (-half_length, half_width), (half_length, 0.0)], body_length, body_width




def _opamp_label_position(length: float, width: float) -> tuple[float, float]:
    """Return a readable label position inside the op-amp triangle."""

    points, _, _ = _opamp_outline(length, width)
    centroid_x, centroid_y = _polygon_centroid(points)
    base_x = min(point[0] for point in points)
    return centroid_x + (base_x - centroid_x) * 0.28, centroid_y




def _opamp_symbol_2d(length: float, width: float, mode: str, *, fill: str = "#ffffff", stroke: str = INK, text_fill: str = INK, line_width: float = 1.0, opacity: float = 1.0) -> list[dict[str, Any]]:
    """Build the 2D op-amp symbol used by ``TIABlock`` (both modes)."""

    mode_key = _normalize_tia_mode(mode)
    points, body_length, _ = _opamp_outline(length, width)
    half_length = body_length / 2.0
    label_x, label_y = _opamp_label_position(length, width)
    text_size = max(width * (0.16 if mode_key == "tia" else 0.26), 3.7)
    return [
        _line(-length / 2.0, 0.0, -half_length, 0.0, stroke=stroke, stroke_width=line_width, opacity=opacity),
        _polygon(points, fill=fill, opacity=opacity, stroke=stroke, stroke_width=max(line_width * 0.18, 0.45)),
        _line(half_length, 0.0, length / 2.0, 0.0, stroke=stroke, stroke_width=line_width, opacity=opacity),
        _text(_opamp_label(mode_key), label_x, label_y, size=text_size, fill=text_fill, opacity=1.0),
    ]




def _opamp_body_3d(length: float, width: float, mode: str, *, body_color: str = "#f2f2f0", edge_color: str = "#d7d7d2") -> list[dict[str, Any]]:
    """Build a 3D op-amp body with its TIA or integral label on top."""

    mode_key = _normalize_tia_mode(mode)
    points, body_length, body_width = _opamp_outline(length, width)
    label_x, label_y = _opamp_label_position(length, width)
    font_size = max(int(width * 6.0 * (0.92 if mode_key == "tia" else 1.02)), 82)
    return [
        {"shape": "extruded_polygon", "points": [(point[0] * 1.06, point[1] * 1.04) for point in points], "height": 0.22, "position": [0.0, -0.02, 0.0], "material": {"color": edge_color, "metalness": 0.04, "roughness": 0.72}},
        {"shape": "extruded_polygon", "points": points, "height": 1.18, "position": [0.0, 0.0, 0.0], "material": {"color": body_color, "metalness": 0.02, "roughness": 0.78}},
        {"shape": "text_decal", "text": _opamp_label(mode_key), "width": body_length * 0.3, "height": body_width * 0.24, "position": [label_x, 1.22, -label_y], "rotation": [-math.pi / 2.0, 0.0, 0.0], "fontSize": font_size, "color": "#222222", "fontWeight": "700"},
    ]


# Distinct accent color per chip function — gives the IC family a clear taxonomy.
_ROLE_ACCENT: dict[str, str] = {
    "dac": "#e6a83c",          # amber  — digital → analog
    "adc": "#3fb2d6",          # cyan   — analog → digital
    "tia": "#b890ec",          # violet — transimpedance amplifier
    "integrator": "#b890ec",
    "eic": "#8fa4e0",          # indigo — driver / logic IC
    "mcu": "#5fb389",          # green  — controller
}




def _stairs_points(x0: float, x1: float, cy: float, h: float) -> list[tuple[float, float]]:
    """A 3-step staircase polyline (the digital side of a converter glyph)."""

    w = x1 - x0
    yb = cy - h / 2.0
    pts: list[tuple[float, float]] = []
    for i in range(3):
        y0 = yb + i * h / 3.0
        y1 = yb + (i + 1) * h / 3.0
        pts += [(x0 + i * w / 3.0, y0), (x0 + (i + 1) * w / 3.0, y0), (x0 + (i + 1) * w / 3.0, y1)]
    return pts




def _wave_points(x0: float, x1: float, cy: float, h: float, n: int = 14) -> list[tuple[float, float]]:
    """A smooth sine polyline (the analog side of a converter glyph)."""

    return [(x0 + (i / n) * (x1 - x0), cy + math.sin((i / n) * 2.0 * math.pi) * h * 0.5) for i in range(n + 1)]




def _role_glyph_2d(role_key: str, cx: float, cy: float, w: float, h: float, color: str, line_w: float) -> list[dict[str, Any]]:
    """A clear function icon for a chip lid (distinguishes DAC / ADC / TIA / logic)."""

    x0, x1, xm = cx - w / 2.0, cx + w / 2.0, cx
    if role_key == "dac":  # digital steps in → smooth wave out
        return [_polyline(_stairs_points(x0, xm - w * 0.04, cy, h), stroke=color, stroke_width=line_w, opacity=1.0),
                _polyline(_wave_points(xm + w * 0.04, x1, cy, h), stroke=color, stroke_width=line_w, opacity=1.0)]
    if role_key == "adc":  # smooth wave in → digital steps out
        return [_polyline(_wave_points(x0, xm - w * 0.04, cy, h), stroke=color, stroke_width=line_w, opacity=1.0),
                _polyline(_stairs_points(xm + w * 0.04, x1, cy, h), stroke=color, stroke_width=line_w, opacity=1.0)]
    if role_key in {"tia", "integrator"}:  # op-amp triangle
        return [_polygon([(x0, cy - h * 0.62), (x0, cy + h * 0.62), (x1, cy)], fill="none", opacity=1.0, stroke=color, stroke_width=line_w)]
    if role_key in {"eic", "logic", "processor"}:  # digital pulse train
        seg = w / 6.0
        yb = cy - h / 2.0
        pts = [(x0, yb)]
        for i in range(3):
            bx = x0 + i * 2.0 * seg
            pts += [(bx, yb), (bx, yb + h), (bx + seg, yb + h), (bx + seg, yb), (bx + 2.0 * seg, yb)]
        return [_polyline(pts, stroke=color, stroke_width=line_w, opacity=1.0)]
    return []




def _chip_label_3d(accent: str, label: str, length: float, width: float, z: float) -> list[dict[str, Any]]:
    """Accent band + bold function label printed FLAT on a 3D chip lid (no billboard)."""

    return [
        {"shape": "box", "width": length * 0.5, "height": 0.05, "depth": width * 0.08, "position": [0.0, z + 0.02, -width * 0.22], "material": {"color": accent, "metalness": 0.12, "roughness": 0.5}},
        {"shape": "text_decal", "text": label, "width": length * 0.5, "height": width * 0.34, "position": [0.0, z + 0.06, width * 0.02], "rotation": [-math.pi / 2.0, 0.0, 0.0], "fontSize": max(int(width * 7.0), 96), "color": accent, "fontWeight": "800"},
    ]




def _converter_top_2d(kind: str, length: float, width: float, label: str, *, opacity: float = 1.0) -> list[dict[str, Any]]:
    """Clear 2D chip-lid marking for a DAC/ADC: function glyph + bold accent label."""

    role_key = _converter_kind(kind)
    accent = _ROLE_ACCENT[role_key]
    return [
        *_role_glyph_2d(role_key, 0.0, width * 0.17, length * 0.5, width * 0.2, accent, max(width * 0.04, 0.35)),
        _text(label, 0.0, -width * 0.15, size=max(width * 0.34, 5.0), fill=accent, opacity=1.0, font_weight="bold"),
    ]




def _opamp_top_2d(length: float, width: float, label: str, *, opacity: float = 1.0) -> list[dict[str, Any]]:
    """Clear 2D chip-lid marking for a TIA: op-amp triangle + bold accent label."""

    accent = _ROLE_ACCENT["tia"]
    return [
        *_role_glyph_2d("tia", 0.0, width * 0.17, length * 0.34, width * 0.22, accent, max(width * 0.045, 0.4)),
        _text(label, 0.0, -width * 0.15, size=max(width * 0.34, 5.0), fill=accent, opacity=1.0, font_weight="bold"),
    ]




def _converter_chip_2d(kind: str, length: float, width: float, opacity: float, body_color: str, label: str) -> list[dict[str, Any]]:
    """A DAC/ADC drawn with the literature PENTAGON body shape + bold label + leads."""

    role = _converter_kind(kind)
    accent = _ROLE_ACCENT[role]
    points, in_pt, out_pt = _converter_outline(kind, length * 1.4, width * 1.45)
    lx, ly = _polygon_centroid(points)
    lw = max(width * 0.05, 0.5)
    return [
        _line(-length / 2.0, in_pt[1], in_pt[0], in_pt[1], stroke=INK, stroke_width=lw, opacity=1.0),
        _line(out_pt[0], out_pt[1], length / 2.0, out_pt[1], stroke=INK, stroke_width=lw, opacity=1.0),
        _polygon(points, fill=body_color, opacity=opacity, stroke=accent, stroke_width=lw),
        _circle(min(p[0] for p in points) + width * 0.12, max(p[1] for p in points) - width * 0.12, max(width * 0.04, 0.5), fill="#d8dde6", opacity=0.85, stroke="#7d8794", stroke_width=0.06),
        _text(label, lx, ly, size=max(width * 0.3, 5.0), fill=accent, opacity=1.0, font_weight="bold"),
    ]




def _converter_chip_3d(kind: str, length: float, width: float, body_color: str, label: str) -> list[dict[str, Any]]:
    """A DAC/ADC as an extruded PENTAGON chip prism + flat label decal + leads."""

    role = _converter_kind(kind)
    accent = _ROLE_ACCENT[role]
    points, in_pt, out_pt = _converter_outline(kind, length * 1.4, width * 1.45)
    lx, ly = _polygon_centroid(points)
    return [
        {"shape": "extruded_polygon", "points": [(p[0] * 1.05, p[1] * 1.05) for p in points], "height": 0.24, "position": [0.0, 0.0, 0.0], "material": {"color": CHIP_EDGE, "metalness": 0.02, "roughness": 0.74}},
        {"shape": "extruded_polygon", "points": points, "height": IC_BODY_THICKNESS, "position": [0.0, IC_BODY_THICKNESS * 0.01, 0.0], "material": {"color": body_color, "metalness": 0.06, "roughness": 0.6}},
        _box3d(length * 0.16, max(width * 0.08, 0.6), 0.18, x=-length * 0.42, y=in_pt[1], color=GOLD, z_offset=0.002, metalness=0.6, roughness=0.3),
        _box3d(length * 0.16, max(width * 0.08, 0.6), 0.18, x=length * 0.42, y=out_pt[1], color=GOLD, z_offset=0.002, metalness=0.6, roughness=0.3),
        {"shape": "text_decal", "text": label, "width": length * 0.4, "height": width * 0.34, "position": [lx, IC_BODY_THICKNESS + 0.06, -ly], "rotation": [-math.pi / 2.0, 0.0, 0.0], "fontSize": max(int(width * 7.0), 96), "color": accent, "fontWeight": "800"},
    ]




def _package_style_key(package_style: str) -> str:
    """Normalize IC package aliases to ``qfp``, ``qfn``, ``bga``, or ``die``."""

    style = (package_style or "qfp").strip().lower().replace("-", "_")
    aliases = {
        "quad_flat": "qfp",
        "quad_flat_pack": "qfp",
        "quad_flat_no_lead": "qfn",
        "quad_flat_nolead": "qfn",
        "leadless": "qfn",
        "ball_grid_array": "bga",
        "bare_die": "die",
    }
    style = aliases.get(style, style)
    if style not in {"qfp", "qfn", "bga", "die"}:
        raise ValueError("package_style must be one of: qfp, qfn, bga, die")
    return style




def _package_role_key(role: str) -> str:
    """Normalize an IC role string used for package accents and top marks."""

    return (role or "logic").strip().lower()




def _package_pins_2d(length: float, width: float, pin_count: int, pad_size: float, opacity: float, package_style: str, *, fill: str = PIN_METAL, stroke: str = PIN_SHADOW) -> list[dict[str, Any]]:
    """Return 2D lead or pad children for QFP/QFN packages.

    BGA balls are handled separately because they are distributed across the
    package bottom instead of sitting on the perimeter.
    """

    style = _package_style_key(package_style)
    if style == "bga":
        return []

    children: list[dict[str, Any]] = []
    # Split an approximate pin count across all four package edges. This keeps
    # package drawings compact while still scaling visually with pin_count.
    side_count = max(int(pin_count) // 2, 2)
    lead_depth = pad_size * (1.35 if style == "qfp" else 0.95)
    lead_span = pad_size * (0.86 if style == "qfp" else 1.1)
    edge_offset = lead_depth * 0.5 if style == "qfp" else -lead_depth * 0.12

    for coord_y in _edge_positions(side_count, width, pad_size * 1.9):
        children.append(_rect(-length / 2.0 - edge_offset, coord_y, lead_depth, lead_span, fill=fill, opacity=opacity, stroke=stroke, stroke_width=0.05))
        children.append(_rect(length / 2.0 + edge_offset, coord_y, lead_depth, lead_span, fill=fill, opacity=opacity, stroke=stroke, stroke_width=0.05))
    for coord_x in _edge_positions(side_count, length, pad_size * 1.9):
        children.append(_rect(coord_x, width / 2.0 + edge_offset, lead_span, lead_depth, fill=fill, opacity=opacity, stroke=stroke, stroke_width=0.05))
        children.append(_rect(coord_x, -width / 2.0 - edge_offset, lead_span, lead_depth, fill=fill, opacity=opacity, stroke=stroke, stroke_width=0.05))
    return children




def _package_bga_balls_2d(length: float, width: float, pin_count: int, pad_size: float, opacity: float) -> list[dict[str, Any]]:
    """Return a compact 2D BGA ball array derived from ``pin_count``."""

    ball_count = max(int(math.sqrt(max(pin_count, 4))), 2)
    children: list[dict[str, Any]] = []
    for coord_x in _edge_positions(ball_count, length * 0.72, pad_size):
        for coord_y in _edge_positions(ball_count, width * 0.72, pad_size):
            children.append(_circle(coord_x, coord_y, pad_size * 0.34, fill=SOLDER, opacity=opacity, stroke="#89929d", stroke_width=0.04))
    return children




def _package_wirebonds_2d(length: float, width: float, pad_size: float, opacity: float) -> list[dict[str, Any]]:
    """Return bond pads and wire segments for bare-die package drawings."""

    children: list[dict[str, Any]] = []
    die_length = length * 0.52
    die_width = width * 0.48
    for coord_y in _edge_positions(4, die_width, pad_size * 0.7):
        children.append(_circle(-die_length / 2.0, coord_y, pad_size * 0.22, fill=GOLD, opacity=opacity, stroke=GOLD_DARK, stroke_width=0.04))
        children.append(_circle(die_length / 2.0, coord_y, pad_size * 0.22, fill=GOLD, opacity=opacity, stroke=GOLD_DARK, stroke_width=0.04))
        children.append(_polyline([(-die_length / 2.0, coord_y), (-length * 0.42, coord_y * 1.18)], stroke=GOLD, stroke_width=pad_size * 0.18, opacity=0.9))
        children.append(_polyline([(die_length / 2.0, coord_y), (length * 0.42, coord_y * 1.18)], stroke=GOLD, stroke_width=pad_size * 0.18, opacity=0.9))
    return children




def _package_top_2d(length: float, width: float, pad_size: float, opacity: float, role: str) -> list[dict[str, Any]]:
    """Return the top-side package details for a given IC role."""

    role_key = _package_role_key(role)
    if role_key in {"dac", "adc"}:
        return [_circle(-length * 0.38, width * 0.31, pad_size * 0.34, fill="#d8dde6", opacity=0.86, stroke="#7d8794", stroke_width=0.05)]
    accent = {
        "processor": "#7288a4",
        "logic": "#7288a4",
        "mcu": "#7288a4",
        "dac": "#7aa36f",
        "adc": ANALOG_BLUE,
        "tia": TIA_PURPLE,
        "eic": "#8c99aa",
    }.get(role_key, "#8c99aa")
    return [
        _rect(0.0, 0.0, length * 0.54, width * 0.42, fill=CHIP_FACE, opacity=opacity, stroke=CHIP_EDGE, stroke_width=0.08),
        _rect(0.0, width * 0.18, length * 0.42, pad_size * 0.18, fill=accent, opacity=0.82, stroke="none"),
        _rect(0.0, -width * 0.18, length * 0.42, pad_size * 0.18, fill=accent, opacity=0.62, stroke="none"),
        _circle(-length * 0.38, width * 0.31, pad_size * 0.34, fill="#d8dde6", opacity=0.86, stroke="#7d8794", stroke_width=0.05),
    ]




def _ic_package_geometry_2d(length: float, width: float, pin_count: int, pad_size: float, opacity: float, package_style: str, body_color: str, role: str) -> list[dict[str, Any]]:
    """Build the full 2D IC package body shared by MCU, EIC, DAC, and ADC."""

    style = _package_style_key(package_style)
    children: list[dict[str, Any]] = []
    if style in {"qfp", "qfn"}:
        children.extend(_package_pins_2d(length, width, pin_count, pad_size, opacity, style))
    children.append(_rect(0.0, 0.0, length, width, fill=body_color, opacity=opacity, stroke=CHIP_EDGE, stroke_width=0.16))
    children.append(_rect(0.0, width * 0.36, length * 0.88, pad_size * 0.16, fill="#535d6c", opacity=0.38, stroke="none"))
    children.extend(_package_top_2d(length, width, pad_size, opacity, role))
    if style == "bga":
        children.extend(_package_bga_balls_2d(length, width, pin_count, pad_size, opacity))
    if style == "die":
        children.extend(_package_wirebonds_2d(length, width, pad_size, opacity))
    return children




def _ic_package_geometry_3d(length: float, width: float, pin_count: int, pad_size: float, package_style: str, body_color: str, role: str) -> list[dict[str, Any]]:
    """Build the full 3D IC package body shared by chip-like components."""

    style = _package_style_key(package_style)
    role_key = _package_role_key(role)
    children: list[dict[str, Any]] = [
        _box3d(length * 1.02, width * 1.02, 0.24, x=0.0, y=0.0, color=CHIP_EDGE, z_offset=0.02, metalness=0.02, roughness=0.74),
    ]
    if style in {"qfp", "qfn"}:
        # Reuse the 2D lead placement so 2D and 3D package footprints agree.
        for pin in _package_pins_2d(length, width, pin_count, pad_size, 1.0, style):
            children.append(_box3d(pin["w"], pin["h"], 0.16, x=pin["cx"], y=pin["cy"], color=PIN_METAL, z_offset=0.16, metalness=0.62, roughness=0.28))
    children.extend([
        _box3d(length, width, IC_BODY_THICKNESS, x=0.0, y=0.0, color=body_color, metalness=0.04, roughness=0.66),
        _box3d(length * 0.82, width * 0.78, 0.14, x=0.0, y=0.0, color=CHIP_FACE, z_offset=IC_BODY_THICKNESS, metalness=0.05, roughness=0.58),
    ])
    if role_key not in {"dac", "adc"}:
        accent = "#7288a4" if role_key in {"logic", "mcu", "processor", "eic"} else TIA_PURPLE
        children.append(_box3d(length * 0.49, pad_size * 0.18, 0.06, x=0.0, y=width * 0.2, color=accent, z_offset=IC_BODY_THICKNESS + 0.12, metalness=0.12, roughness=0.46))
    children.append(_cylinder3d(pad_size * 0.32, 0.05, x=-length * 0.38, y=width * 0.31, color="#d8dde6", z_offset=IC_BODY_THICKNESS + 0.16, metalness=0.28, roughness=0.32))
    if style == "bga":
        # BGA balls sit below the package body — rounded reflowed solder bumps.
        for ball in _package_bga_balls_2d(length, width, pin_count, pad_size, 1.0):
            children.append(_solder_bump_3d(ball["cx"], ball["cy"], radius=ball["r"] * 1.15))
    if style == "die":
        # Bare-die wirebonds are approximated as short rotated bars in 3D.
        for wire in _package_wirebonds_2d(length, width, pad_size, 1.0):
            if wire.get("type") != "polyline":
                continue
            points = wire.get("points", [])
            for start_point, end_point in zip(points, points[1:]):
                segment_dx = end_point[0] - start_point[0]
                segment_dy = end_point[1] - start_point[1]
                segment_length = math.hypot(segment_dx, segment_dy)
                if segment_length > 1e-9:
                    children.append(_box3d(segment_length, pad_size * 0.14, 0.1, x=(start_point[0] + end_point[0]) / 2.0, y=(start_point[1] + end_point[1]) / 2.0, color=GOLD, z_offset=IC_BODY_THICKNESS + 0.12, rotation_y=math.atan2(segment_dy, segment_dx), metalness=0.62, roughness=0.28))
    return children




def _converter_trace_children(length: float, width: float, pad_size: float, *, kind: str, opacity: float) -> list[dict[str, Any]]:
    """Return internal 2D trace marks that distinguish DAC and ADC physical views."""

    if kind == "dac":
        ladder_y = width * 0.12
        return [
            _line(-length * 0.35, ladder_y, length * 0.24, ladder_y, stroke="#dce5eb", stroke_width=pad_size * 0.18, opacity=0.85),
            _line(-length * 0.2, ladder_y, -length * 0.2, -width * 0.16, stroke="#dce5eb", stroke_width=pad_size * 0.16, opacity=0.78),
            _line(-length * 0.04, ladder_y, -length * 0.04, -width * 0.12, stroke="#dce5eb", stroke_width=pad_size * 0.16, opacity=0.78),
            _line(length * 0.12, ladder_y, length * 0.12, -width * 0.08, stroke="#dce5eb", stroke_width=pad_size * 0.16, opacity=0.78),
            _polyline([(length * 0.24, ladder_y), (length * 0.32, width * 0.02), (length * 0.38, width * 0.02)], stroke="#7aa36f", stroke_width=pad_size * 0.22, opacity=0.92),
        ]
    return [
        _polyline([(-length * 0.36, -width * 0.12), (-length * 0.22, width * 0.12), (-length * 0.08, -width * 0.12), (length * 0.08, width * 0.12), (length * 0.22, -width * 0.12)], stroke="#dce5eb", stroke_width=pad_size * 0.16, opacity=0.84),
        _line(length * 0.12, -width * 0.2, length * 0.12, width * 0.22, stroke=ANALOG_BLUE, stroke_width=pad_size * 0.2, opacity=0.88),
        _line(length * 0.22, -width * 0.2, length * 0.22, width * 0.22, stroke=ANALOG_BLUE, stroke_width=pad_size * 0.2, opacity=0.68),
        _line(length * 0.32, -width * 0.2, length * 0.32, width * 0.22, stroke=ANALOG_BLUE, stroke_width=pad_size * 0.2, opacity=0.5),
    ]




def _offset_geometry_2d(geometry: dict[str, Any], dx: float, dy: float) -> dict[str, Any]:
    """Return a copy of a 2D geometry dictionary shifted by ``dx`` and ``dy``."""

    shifted = dict(geometry)
    gtype = shifted.get("type")
    if gtype == "group":
        shifted["children"] = [_offset_geometry_2d(child, dx, dy) for child in shifted.get("children", [])]
    elif gtype == "text":
        shifted["x"] = shifted.get("x", 0.0) + dx
        shifted["y"] = shifted.get("y", 0.0) + dy
    elif gtype in {"rect", "circle"}:
        shifted["cx"] = shifted.get("cx", 0.0) + dx
        shifted["cy"] = shifted.get("cy", 0.0) + dy
    elif gtype == "line":
        shifted["x1"] = shifted["x1"] + dx
        shifted["x2"] = shifted["x2"] + dx
        shifted["y1"] = shifted["y1"] + dy
        shifted["y2"] = shifted["y2"] + dy
    elif gtype in {"polygon", "polyline"}:
        shifted["points"] = [(point[0] + dx, point[1] + dy, *(point[2:] if len(point) > 2 else ())) for point in shifted.get("points", [])]
    return shifted




def _offset_geometry_3d(geometry: dict[str, Any], dx: float, dy: float, dz: float = 0.0) -> dict[str, Any]:
    """Return a copy of a 3D geometry dictionary shifted in layout coordinates."""

    shifted = dict(geometry)
    if "position" in shifted:
        pos = list(shifted["position"])
        pos[0] += dx
        pos[1] += dz
        # Local layout y maps to negative Three.js z throughout this file.
        pos[2] -= dy
        shifted["position"] = pos
    if shifted.get("shape") == "tube_path":
        shifted["points"] = [
            [point[0] + dx, point[1] + dz, point[2] - dy]
            for point in shifted.get("points", [])
        ]
    if shifted.get("shape") == "group":
        shifted["children"] = [_offset_geometry_3d(child, dx, dy, dz) for child in shifted.get("children", [])]
    return shifted




def _side_port(side: str, width: float, height: float, port_width: float, layer: str | None, *, name: str = "e1") -> Port:
    """Create a single electrical port on a rectangle side or center point."""

    side = side.lower()
    if side == "left":
        return Port(name, Vec3(-width / 2.0, 0.0, 0.0), orientation_deg=180.0, width=port_width, kind="electrical", layer=layer)
    if side == "right":
        return Port(name, Vec3(width / 2.0, 0.0, 0.0), orientation_deg=0.0, width=port_width, kind="electrical", layer=layer)
    if side == "top":
        return Port(name, Vec3(0.0, height / 2.0, 0.0), orientation_deg=90.0, width=port_width, kind="electrical", layer=layer)
    if side == "bottom":
        return Port(name, Vec3(0.0, -height / 2.0, 0.0), orientation_deg=-90.0, width=port_width, kind="electrical", layer=layer)
    if side == "center":
        return Port(name, Vec3(0.0, 0.0, 0.0), orientation_deg=0.0, width=port_width, kind="electrical", layer=layer)
    raise ValueError("port_side must be one of: left, right, top, bottom, center")
