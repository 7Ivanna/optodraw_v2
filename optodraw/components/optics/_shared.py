"""Optical components for free-space setups."""

from __future__ import annotations

import math
from typing import Any

from optodraw.core.component import Component
from optodraw.core.ports import Port
from optodraw.core.transform import Transform, Vec3



PASS_BANDS = ("longpass", "shortpass")


def _pass_band(value: Any) -> str:
    """The side of the edge that passes. Any other word is refused: read as one side it gives wrong physics."""

    band = str(value or "longpass")
    if band not in PASS_BANDS:
        raise ValueError(f"pass_band must be 'longpass' or 'shortpass', not {band!r}")
    return band


def _set_common_free_space_fields(
    component: Component,
    center,
    angle: float,
    kwargs: dict[str, Any],
    *,
    color: str,
    opacity: float,
    material_preset: str,
    label: str = "",
) -> None:
    component.material_preset = kwargs.get("material_preset", material_preset)
    component.color = kwargs.get("color", color)
    component.opacity = kwargs.get("opacity", opacity)
    component.label = kwargs.get("label", label)
    # 3D base mount the renderer draws under a beam-plane optic: "post" (Thorlabs
    # pedestal, default) or "stage" (translation stage + cylindrical riser to the optic).
    # base_mount selects the 3D pedestal that lifts the optic to the beam plane:
    # "post" (default, to device bottom → aperture-dependent height, most realistic),
    # "post_beam" (to beam axis → uniform height), "stage", "rotation_stage", "none".
    component.base_mount = str(kwargs.get("base_mount", "post"))
    # mount_height lets you pick a real post from the drawer: an absolute device-
    # bottom height above 0 (board top is BOARD_TOP). When set it overrides the
    # aperture-dependent bottom so every optic can share one beam height even with
    # mixed apertures, exactly as you swap TR1/TR2/TR3 in the lab.
    mh = kwargs.get("mount_height", kwargs.get("post_height"))
    component.mount_height = float(mh) if mh is not None else None  # type: ignore[attr-defined]
    placed = component._parse_center(center)
    component.transform = Transform.from_2d(*placed.as_2d(), angle)
    if placed.z:
        component.z = float(placed.z)                     # a height: center=(x, y, z)
    component._parent = None
    component._id = ""




def _transparent_material(color: str, opacity: float, preset: str) -> dict[str, Any]:
    return {"color": color, "opacity": opacity, "transparent": opacity < 1.0, "preset": preset}




def _optical_metadata(component: str, **values: Any) -> dict[str, Any]:
    return {"domain": "free_space", "component": component, **values}




def _signed_nonzero(value: float, fallback: float = 1e-9) -> float:
    """Preserve sign for focal-length ratios while avoiding division by zero."""

    if abs(value) >= fallback:
        return value
    return fallback if value >= 0 else -fallback




def _through_ports(span: float, width: float) -> dict[str, Port]:
    """Standard collinear free-space input/output ports along local +x."""

    half = span / 2.0
    return {
        "in": Port("in", Vec3(-half, 0.0, 0.0), orientation_deg=180.0, width=width, kind="free_space"),
        "out": Port("out", Vec3(half, 0.0, 0.0), orientation_deg=0.0, width=width, kind="free_space"),
    }




def _beam_splitter_cube_ports(aperture: float) -> dict[str, Port]:
    """Cube beam-splitter ports, one per face: input, transmitted, reflected, and the fourth face (tap), where a
    second beam enters to recombine with the first."""

    edge = aperture * 0.72
    half = edge / 2.0
    return {
        "in": Port("in", Vec3(-half, 0.0, 0.0), orientation_deg=180.0, width=edge, kind="free_space"),
        "trans": Port("trans", Vec3(half, 0.0, 0.0), orientation_deg=0.0, width=edge, kind="free_space"),
        "refl": Port("refl", Vec3(0.0, half, 0.0), orientation_deg=90.0, width=edge, kind="free_space"),
        "tap": Port("tap", Vec3(0.0, -half, 0.0), orientation_deg=270.0, width=edge, kind="free_space"),
    }




def _right_angle_prism_ports(leg: float) -> dict[str, Port]:
    """Right-angle prism ports for a fold from +x to +y."""

    return {
        "in": Port("in", Vec3(-leg / 2.0, 0.0, 0.0), orientation_deg=180.0, width=leg, kind="free_space"),
        "out": Port("out", Vec3(0.0, leg / 2.0, 0.0), orientation_deg=90.0, width=leg, kind="free_space"),
    }




def _cylinder_along_x(radius: float, height: float, material: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return {"shape": "cylinder", "radius": radius, "height": height, "rotation": [0.0, 0.0, math.pi / 2.0], "material": material, **extra}




def _rim_along_x(radius: float, tube: float, material: dict[str, Any], **extra: Any) -> dict[str, Any]:
    """A flat rim ring round the beam axis (a retaining ring, a lip, a band): from ``radius - tube`` to
    ``radius + tube``, ``2 * tube`` along x, in a satin finish. A torus here read as a shiny chrome donut."""

    satin = {**material, "metalness": min(material.get("metalness", 0.5), 0.5),
             "roughness": max(material.get("roughness", 0.4), 0.4)}
    ring = _ring_along_x(max(radius - tube, 0.0), radius + tube, 2.0 * tube, satin)
    ring.update(extra)
    return ring


def _kinematic_mount(front: float, side: float, optic_r: float) -> list[dict[str, Any]]:
    """A kinematic mount (KM100 or KM200 silhouette) whose front plate starts at x = ``front``: a square front
    plate of ``side`` with a round bore for an optic of radius ``optic_r`` and one corner chamfered; behind a narrow gap, an
    L-shaped back plate along one side and the bottom; the two adjusters thread through the free ends of the L
    and push on the front plate; the pivot ball sits at the corner of the L. The bore and the open middle of
    the L let a beam pass. The post holds the bottom arm of the L."""

    h, arm, chamfer = side / 2.0, side / 7.0, side * 0.2
    t_front, gap, t_back = side / 7.0, side / 35.0, side * 0.114
    back = front + t_front + gap
    seat = back - gap / 2.0
    bore = optic_r * 1.015                       # a hair wider than the optic: equal walls flicker in a render
    hole = [(bore * math.cos(2.0 * math.pi * k / 40), bore * math.sin(2.0 * math.pi * k / 40)) for k in range(40)]
    ball = {"color": "#eef2f7", "metalness": 0.95, "roughness": 0.04, "preset": "steel"}

    def plate(points, x: float, thick: float, holes) -> dict[str, Any]:
        # (u, v) of the outline lands at (y, z) = (u, -v); the plate extrudes toward -x from its position
        return {"shape": "extruded_polygon", "role": "plate", "points": points, "holes": holes, "height": thick,
                "position": [x + thick, 0.0, 0.0], "rotation": [0.0, 0.0, math.pi / 2.0], "material": _MOUNT_BLACK}

    out = [
        plate([(-h, -h), (-h, h), (h, h), (h, -h + chamfer), (h - chamfer, -h)], front, t_front, [hole]),
        plate([(-h, -h), (-h, h), (h, h), (h, h - arm), (-h + arm, h - arm), (-h + arm, -h)], back, t_back, []),
        {"shape": "sphere", "role": "pivot", "radius": side * 0.025, "position": [seat, -h + arm / 2.0, -(h - arm / 2.0)], "material": ball},
    ]
    rear = back + t_back
    for y, z in ((h - arm / 2.0, -(h - arm / 2.0)), (-h + arm / 2.0, h - arm / 2.0)):
        out += [
            {"shape": "sphere", "radius": side * 0.021, "position": [seat, y, z], "material": ball},
            {**_cylinder_along_x(side * 0.025, side * 0.07, _KNOB_STEEL, position=[rear + side * 0.035, y, z]), "role": "screw"},
            {**_cylinder_along_x(side * 0.064, side * 0.086, _MOUNT_BLACK, position=[rear + side * 0.113, y, z]), "role": "knob"},
        ]
    return out


def _square_plate(x: float, half: float, bore: float, thick: float, material: dict[str, Any]) -> dict[str, Any]:
    """A square plate across the beam at ``x`` (side 2 * ``half``, ``thick`` along x) with a round bore."""

    hole = [(bore * math.cos(2.0 * math.pi * k / 32), bore * math.sin(2.0 * math.pi * k / 32)) for k in range(32)]
    return {"shape": "extruded_polygon", "points": [(-half, -half), (half, -half), (half, half), (-half, half)],
            "holes": [hole], "height": thick, "position": [x + thick / 2.0, 0.0, 0.0],
            "rotation": [0.0, 0.0, math.pi / 2.0], "material": material}


def _frame_holder(width: float, height: float, depth: float) -> list[dict[str, Any]]:
    """A rectangular holder round a square optic, as for a filter or a cylindrical lens: four bars round a
    ``width`` (across the beam, z) by ``height`` (y) window, a thumb screw on top and a stem down to the post."""

    bar = max(min(width, height) * 0.12, 0.3)
    outer = height + 2.0 * bar
    out = [
        {"shape": "box", "role": "holder", "width": depth, "height": outer, "depth": bar,
         "position": [0.0, 0.0, side * (width + bar) / 2.0], "material": _MOUNT_BLACK} for side in (-1.0, 1.0)
    ]
    out += [
        {"shape": "box", "role": "holder", "width": depth, "height": bar, "depth": width,
         "position": [0.0, side * (height + bar) / 2.0, 0.0], "material": _MOUNT_BLACK} for side in (-1.0, 1.0)
    ]
    out += [
        {"shape": "cylinder", "radius": bar * 0.3, "height": bar, "position": [0.0, outer / 2.0 + bar * 0.5, 0.0], "material": _KNOB_STEEL},
        {"shape": "cylinder", "radius": bar * 0.7, "height": bar * 0.5, "position": [0.0, outer / 2.0 + bar * 1.25, 0.0], "material": _MOUNT_BLACK},
        {"shape": "box", "width": depth * 0.8, "height": bar * 1.2, "depth": bar * 2.0, "position": [0.0, -outer / 2.0 - bar * 0.5, 0.0], "material": _MOUNT_BLACK},
    ]
    return out


def _post_boss(radius: float, width: float, x: float = 0.0) -> dict[str, Any]:
    """A flat boss under a round body of outer ``radius`` (``width`` along the beam, at ``x``) that the post
    screws into, as on a fixed lens mount; without it the post met the curved rim at one point. Its bottom is
    at y = -1.12 * radius."""

    return {"shape": "box", "role": "boss", "width": width, "height": radius * 0.16, "depth": radius * 0.3,
            "position": [x, -radius * 1.04, 0.0], "material": _MOUNT_BLACK}


def _tube_clamp(tube_r: float, width: float, x: float = 0.0) -> tuple[list[dict[str, Any]], list[float]]:
    """A clamp ring round a tube of radius ``tube_r`` at ``x``, with a boss for the post, and the point the
    post holds (for ``post_at``): a long tube is carried at one place, not at its widest end ring."""

    ring = tube_r * 1.12
    return ([_ring_along_x(tube_r, ring, width, _MOUNT_BLACK, x=x), _post_boss(ring, width * 0.8, x)],
            [x, -ring * 1.12, 0.0])


# Shared opto-mechanics material language (matches the renderer's pedestal posts):
# black-anodised mount bodies, brushed-aluminium cells/rings, bright steel knobs.


def _ring_along_x(inner_r: float, outer_r: float, width: float, material: dict[str, Any], *, x: float = 0.0, segments: int = 40, **extra: Any) -> dict[str, Any]:
    """An annulus with a REAL through-hole (lathe of a closed rectangular profile),
    axis along x — for irises, aperture stops, tubes: light genuinely passes through."""

    h = width / 2.0
    return {
        "shape": "lathe_profile",
        "points": [[inner_r, -h], [outer_r, -h], [outer_r, h], [inner_r, h], [inner_r, -h]],
        "segments": segments,
        "rotation": [0.0, 0.0, math.pi / 2.0],
        "position": [x, 0.0, 0.0],
        "material": material,
        **extra,
    }




def _round_optic_2d(aperture: float, color: str, opacity: float, *, stroke: str, label_line: str | None = None) -> list[dict[str, Any]]:
    children: list[dict[str, Any]] = [
        {"type": "circle", "cx": 0.0, "cy": 0.0, "r": aperture / 2.0, "fill": "#242a31", "stroke": "#111827", "stroke_width": OPTICS_HAIRLINE, "opacity": 0.96},
        {"type": "circle", "cx": 0.0, "cy": 0.0, "r": aperture * 0.41, "fill": color, "stroke": stroke, "stroke_width": OPTICS_HAIRLINE, "opacity": opacity},
    ]
    if label_line:
        children.append({"type": "line", "x1": -aperture * 0.28, "y1": 0.0, "x2": aperture * 0.28, "y2": 0.0, "stroke": label_line, "stroke_width": OPTICS_THIN, "opacity": 0.75})
    return children




def _round_optic_3d(aperture: float, thickness: float, color: str, opacity: float, preset: str, *, frame_color: str = "#2f3439") -> list[dict[str, Any]]:
    # Optic body + anodized ring mount only. The mounting POST is no longer baked
    # in here: the 3D renderer draws a uniform post from the table to the beam
    # plane, so every optic shares one beam height (see threejs_renderer beam plane).
    mat_mount = {"color": frame_color, "preset": "steel", "metalness": 0.45, "roughness": 0.4}
    return [
        _ring_along_x(aperture * 0.42, aperture * 0.5, thickness * 1.15, mat_mount),
        _cylinder_along_x(aperture * 0.42, thickness * 1.22, _transparent_material(color, opacity, preset), position=[thickness * 0.03, 0.0, 0.0]),
        _rim_along_x(aperture * 0.42, max(aperture * 0.035, 0.08), {"color": "#d7dde5", "metalness": 0.35, "roughness": 0.28}, position=[thickness * 0.64, 0.0, 0.0]),
        # Premium Thorlabs-style anodized outer ring mount
        _rim_along_x(aperture * 0.51, max(thickness * 0.12, 0.16), mat_mount),
    ]




def _mirror_face_material(color: str = "#eef6fb", opacity: float = 1.0) -> dict[str, Any]:
    return {"color": color, "opacity": opacity, "transparent": opacity < 1.0, "metalness": 0.96, "roughness": 0.015, "clearcoat": 1.0, "clearcoatRoughness": 0.02, "envMapIntensity": 2.4}




def _knurl_teeth(radius: float, count: int, *, x: float, width: float, color: str = "#c8ccd0") -> list[dict[str, Any]]:
    teeth: list[dict[str, Any]] = []
    for tooth_index in range(count):
        angle = 2.0 * math.pi * tooth_index / count
        teeth.append(
            {
                "shape": "box",
                "width": width,
                "height": radius * 0.18,
                "depth": radius * 0.045,
                "position": [x, math.sin(angle) * radius, math.cos(angle) * radius],
                "rotation": [angle, 0.0, 0.0],
                "material": {"color": color, "metalness": 0.5, "roughness": 0.22, "preset": "steel"},
            }
        )
    return teeth




_MOUNT_BLACK = {"color": "#23282e", "metalness": 0.42, "roughness": 0.55, "preset": "steel"}


_MOUNT_ALU = {"color": "#c6cbd1", "metalness": 0.55, "roughness": 0.42, "preset": "steel"}   # satin, not chrome


_KNOB_STEEL = {"color": "#b9bfc6", "metalness": 0.9, "roughness": 0.18, "preset": "steel"}

# 2D stroke tokens — keep hairlines consistent across all free-space optics
OPTICS_HAIRLINE = 0.08
OPTICS_THIN = 0.12
OPTICS_OUTLINE = 0.12

