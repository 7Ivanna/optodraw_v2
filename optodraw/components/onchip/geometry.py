"""Low-level geometry helpers for on-chip component rendering."""

from __future__ import annotations

import math
from copy import deepcopy
from typing import Any

from optodraw.core.ports import Port
from optodraw.core.transform import Vec3

def _chip_box(
    cx: float,
    cy: float,
    width: float,
    height: float,
    color: str,
    opacity: float,
    *,
    stroke: str | None = None,
    stroke_width: float = 0.0,
    layer: str | None = None,
) -> dict[str, Any]:
    data = {
        "type": "rect",
        "cx": cx,
        "cy": cy,
        "w": width,
        "h": height,
        "fill": color,
        "opacity": opacity,
        "stroke": stroke or "none",
        "stroke_width": stroke_width,
    }
    if layer is not None:
        data["chip_layer"] = layer
    return data


# Materials in 2D; silicon is SILICON in base.py (the AWGR blue). Light tints, so no part reads as a dark block.
GERMANIUM, GERMANIUM_EDGE = "#a8b4c4", "#5b6b82"
P_DOPED, P_EDGE = "#f4b4b4", "#c06a6a"
N_DOPED, N_EDGE = "#b7cdf2", "#5f82bf"
CHARGE, CHARGE_EDGE = "#d6c6ee", "#7d5fa8"            # the charge layer of an avalanche diode
GOLD, GOLD_EDGE = "#d4af37", "#8e7611"
VIA, VIA_EDGE = "#f08c6d", "#8b5038"
INP, INP_EDGE = "#f6c9d3", "#b5677d"                  # the III-V mesa of a laser
MQW, MQW_EDGE = "#e893a8", "#a8506a"                  # its active quantum wells
TIN, TIN_EDGE = "#c8964a", "#8a6326"                  # a TiN heater


def _pad_children(cx: float, cy: float, width: float, height: float, opacity: float) -> list[dict[str, Any]]:
    """A gold pad; the inner square gives it depth."""

    return [_chip_box(cx, cy, width, height, GOLD, opacity, stroke=GOLD_EDGE, stroke_width=0.1, layer="pad"),
            _chip_box(cx, cy, width * 0.72, height * 0.72, "#e7c069", opacity,
                      stroke="#fff1bd", stroke_width=0.06, layer="pad_finish")]


def _contact_children(cx: float, cy: float, length: float, height: float, opacity: float, vias: int = 4) -> list[dict[str, Any]]:
    """A gold contact strip on doped silicon, with its vias."""

    children = [_chip_box(cx, cy, length, height, GOLD, opacity, stroke=GOLD_EDGE, stroke_width=0.05, layer="metal")]
    side = height * 0.62
    for index in range(vias):
        x = cx - length / 2.0 + length * (index + 0.5) / vias
        children.append(_chip_box(x, cy, side, side, VIA, opacity, stroke=VIA_EDGE, stroke_width=0.04, layer="via"))
    return children


def _chip_polygon(
    points: list[tuple[float, float]],
    *,
    fill: str,
    opacity: float,
    stroke: str | None = None,
    stroke_width: float = 0.0,
    layer: str | None = None,
) -> dict[str, Any]:
    data = {
        "type": "polygon",
        "points": [(x, y, 0.0) for x, y in points],
        "fill": fill,
        "opacity": opacity,
        "stroke": stroke or "none",
        "stroke_width": stroke_width,
    }
    if layer is not None:
        data["chip_layer"] = layer
    return data


def _chip_circle(
    cx: float,
    cy: float,
    radius: float,
    *,
    stroke: str,
    stroke_width: float,
    opacity: float,
    fill: str = "none",
) -> dict[str, Any]:
    return {
        "type": "circle",
        "cx": cx,
        "cy": cy,
        "r": radius,
        "stroke": stroke,
        "stroke_width": stroke_width,
        "fill": fill,
        "opacity": opacity,
    }


def _chip_line(
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    *,
    stroke: str,
    stroke_width: float,
    opacity: float,
) -> dict[str, Any]:
    return {
        "type": "line",
        "x1": x1,
        "y1": y1,
        "x2": x2,
        "y2": y2,
        "stroke": stroke,
        "stroke_width": stroke_width,
        "opacity": opacity,
    }


def _chip_polyline(
    points: list[tuple[float, float]],
    stroke: str,
    stroke_width: float,
    opacity: float,
    *,
    closed: bool = False,
) -> dict[str, Any]:
    return {
        "type": "polyline",
        "points": [(x, y, 0.0) for x, y in points],
        "stroke": stroke,
        "stroke_width": stroke_width,
        "fill": "none",
        "opacity": opacity,
        "linecap": "round",
        "linejoin": "round",
        "closed": closed,
    }


def _chip_slab(
    length: float,
    width: float,
    thickness: float,
    *,
    x: float = 0.0,
    y: float = 0.0,
    color: str,
    preset: str | None = None,
    z_offset: float = 0.0,
    rotation_y: float = 0.0,
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "shape": "box",
        "width": length,
        "height": thickness,
        "depth": width,
        "position": [x, thickness / 2.0 + z_offset, -y],
        "material": {"color": color, **({"preset": preset} if preset else {})},
    }
    if rotation_y:
        data["rotation"] = [0.0, rotation_y, 0.0]
    return data


def _chip_segment_polygon(
    start: tuple[float, float],
    end: tuple[float, float],
    width_start: float,
    width_end: float,
    *,
    fill: str,
    opacity: float,
    stroke: str | None = None,
    stroke_width: float = 0.0,
    segments: int = 1,
) -> dict[str, Any]:
    return _chip_polygon(
        _segment_outline(start, end, width_start, width_end, segments=segments),
        fill=fill,
        opacity=opacity,
        stroke=stroke,
        stroke_width=stroke_width,
    )


def _chip_segment_slab(
    start: tuple[float, float],
    end: tuple[float, float],
    width_start: float,
    width_end: float,
    thickness: float,
    *,
    color: str,
    preset: str | None = None,
    segments: int = 1,
    z_offset: float = 0.0,
) -> dict[str, Any]:
    return _chip_extruded_polygon(
        _segment_outline(start, end, width_start, width_end, segments=segments),
        thickness,
        color=color,
        preset=preset,
        z_offset=z_offset,
    )


def _chip_path_slab(
    points: list[tuple[float, float]],
    width: float,
    thickness: float,
    *,
    color: str,
    preset: str | None = None,
    z_offset: float = 0.0,
    closed: bool = False,
) -> dict[str, Any]:
    if len(points) < 2:
        return {"shape": "group", "children": []}
    outline = _polyline_outline_closed(points, width) if closed else _polyline_outline(points, width)
    return _chip_extruded_polygon(
        outline,
        thickness,
        color=color,
        preset=preset,
        z_offset=z_offset,
    )


def _chip_extruded_polygon(
    points: list[tuple[float, float]],
    thickness: float,
    *,
    color: str,
    preset: str | None = None,
    opacity: float = 1.0,
    z_offset: float = 0.0,
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "shape": "extruded_polygon",
        "points": [(x, y, 0.0) for x, y in points],
        "height": thickness,
        "material": {
            "color": color,
            "opacity": opacity,
            **({"preset": preset} if preset else {}),
        },
    }
    if abs(z_offset) > 1e-12:
        data["position"] = [0.0, z_offset, 0.0]
    return data


def _plan(node: dict[str, Any]):
    """The plan (chip x, y) of a box or an extruded polygon of a chip tree, and its bottom and top."""

    import shapely
    from shapely import affinity

    position = node.get("position") or [0.0, 0.0, 0.0]
    turn = node.get("rotation") or [0.0, 0.0, 0.0]
    height = float(node["height"])
    if turn[0] or turn[2]:
        raise ValueError(f"a chip solid tilted out of the plane has no plan: {node.get('shape')}")
    if node.get("shape") == "box":
        w, d = float(node["width"]) / 2.0, float(node["depth"]) / 2.0
        plan, bottom = shapely.box(-w, -d, w, d), float(position[1]) - height / 2.0
    elif node.get("shape") == "extruded_polygon":
        plan = shapely.make_valid(shapely.Polygon([p[:2] for p in node["points"]],
                                                  [[p[:2] for p in hole] for hole in node.get("holes") or []]))
        bottom = float(position[1])
    else:
        raise ValueError(f"a chip solid of shape {node.get('shape')} has no plan")
    plan = affinity.rotate(plan, float(turn[1]), origin=(0.0, 0.0), use_radians=True)    # rotation.y turns the plan CCW
    return affinity.translate(plan, float(position[0]), -float(position[2])), bottom, bottom + height


def _cut_footprints(losers: list[dict[str, Any]], keepers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Each of ``losers`` less the plan of every one of ``keepers`` that has its base or its top on the same
    plane: there the viewer z-fights, so one solid owns each patch. No solid moves off its level. A cut loser
    becomes extruded polygons (a keeper inside it leaves a hole); one cut away whole is dropped."""

    import shapely

    out = []
    planned = [(keeper, *_plan(keeper)) for keeper in keepers]
    for loser in losers:
        plan, bottom, top = _plan(loser)
        cuts = [other for keeper, other, low, high in planned
                if keeper is not loser and (abs(low - bottom) < 1e-9 or abs(high - top) < 1e-9)]
        cut = shapely.union_all(cuts) if cuts else None
        if cut is None or plan.intersection(cut).area <= 1e-12:
            out.append(loser)
            continue
        for piece in shapely.get_parts(plan.difference(cut)):
            if piece.geom_type != "Polygon" or piece.area <= 1e-12:
                continue
            solid = {key: deepcopy(value) for key, value in loser.items()
                     if key not in ("width", "depth", "rotation", "points", "holes")}
            solid.update(shape="extruded_polygon", points=[(x, y, 0.0) for x, y in piece.exterior.coords[:-1]],
                         height=top - bottom, position=[0.0, bottom, 0.0])
            if piece.interiors:
                solid["holes"] = [[(x, y) for x, y in ring.coords[:-1]] for ring in piece.interiors]
            out.append(solid)
    return out


def _vias(size: float, centres: list[tuple[float, float]], stack: dict[str, float], *,
          into: float = 0.0) -> list[dict[str, Any]]:
    """Square copper vias from the via level up to the metal (``into`` it). None where the stack has no via
    layer: in the bundled stack the contact (VIAC) ends on M1, so ``via_height`` is 0."""

    if stack["via_height"] <= 0:
        return []
    return [_chip_slab(size, size, stack["via_height"] + into, x=x, y=y, color=VIA, preset="copper", z_offset=stack["via_z"])
            for x, y in centres]


def _pad_route(size_x: float, size_y: float, x: float, y: float, stack: dict[str, float], *, below: float,
               arrive: tuple[float, float] | None = None, color: str = "#d4af37", preset: str = "gold",
               via_color: str = "#f08c6d") -> list[dict[str, Any]]:
    """The route up to a raised pad (``size_x`` by ``size_y`` at ``x``, ``y``): a small via from the layer the
    trace runs on (``below``: its top) to the pad, where the trace reaches the pad (``arrive``, on the pad's
    edge; the centre when the trace runs under the pad), on a short landing of that layer from the edge to the
    via, in the trace's material (``color``, ``preset``). A plate the pad's size with a via block under it read
    as a heavy block."""

    if stack["pad_z"] <= below + 1e-9:
        return []
    heater_top = stack["heater_z"] + stack["heater_height"]
    base = stack["heater_z"] if abs(below - heater_top) < 1e-9 else stack["metal_z"]
    side = min(size_x, size_y) * 0.25
    inside = min(stack["pad_height"] * 0.02, 0.005)
    x0, x1, y0, y1 = x - size_x / 2.0, x + size_x / 2.0, y - size_y / 2.0, y + size_y / 2.0
    if arrive is None:
        vx, vy = x, y
        landing = (side * 1.3, side * 1.3, vx, vy)
    else:
        ax, ay = min(max(arrive[0], x0), x1), min(max(arrive[1], y0), y1)
        if min(abs(ay - y0), abs(ay - y1)) <= min(abs(ax - x0), abs(ax - x1)):      # it arrives on a long edge
            inward = 1.0 if abs(ay - y0) <= abs(ay - y1) else -1.0
            vx, vy = min(max(ax, x0 + side), x1 - side), ay + inward * side
            landing = (side * 1.3, side * 1.6, vx, ay + inward * side * 0.8)
        else:
            inward = 1.0 if abs(ax - x0) <= abs(ax - x1) else -1.0
            vx, vy = ax + inward * side, min(max(ay, y0 + side), y1 - side)
            landing = (side * 1.6, side * 1.3, ax + inward * side * 0.8, vy)
    out = []
    if below > base + 1e-9:
        w, h, lx, ly = landing
        out.append(_chip_slab(w, h, below - base, x=lx, y=ly, color=color, preset=preset, z_offset=base))
    out.append(_chip_slab(side, side, stack["pad_z"] - below + inside, x=vx, y=vy, color=via_color, preset="copper",
                          z_offset=below))
    return out


def _pad_on_via(size_x: float, size_y: float, x: float, y: float, stack: dict[str, float], *, below: float,
                color: str, via_color: str = "#f08c6d", arrive: tuple[float, float] | None = None,
                landing: tuple[str, str] = ("#d4af37", "gold")) -> list[dict[str, Any]]:
    """A pad on the pad layer, the top of the stack, and the route up to it from the trace below
    (``_pad_route``); ``landing`` is the trace's colour and material preset."""

    return [_chip_slab(size_x, size_y, stack["pad_height"], x=x, y=y, color=color, preset="gold", z_offset=stack["pad_z"]),
            *_pad_route(size_x, size_y, x, y, stack, below=below, arrive=arrive, color=landing[0], preset=landing[1],
                        via_color=via_color)]


# Two process layers on one base or top share that patch of the plane. One owns it, the other is cut there: a
# doped region or a charge layer is the silicon of its region, the silicon core runs on under a bonded III-V
# mesa, and the metal is the terminal where it lands on a heater. A contact plug owns its patch where the core
# starts on the slab top (a ridge on its slab).
_DOPED = ("implant", "charge")
_CUT_BY = {"core": (*_DOPED, "via"), "mesa": ("core",), "heater": ("metal",)}


def _chip_process_3d(
    art: dict[str, Any],
    thickness: float,
    stack: dict[str, float],
    *,
    core: dict[str, Any],
    doped_preset: str,
    opacity: float,
    schematic: bool = True,
) -> list[dict[str, Any]]:
    """Extrude tagged component footprints without changing their port anchors.

    Semiconductor heights illustrate the process layers, not a foundry cross-section.
    Metal, pad, and via heights use the component's resolved layer stack. The core layer takes the level, colour
    and material of ``core`` (``ChipComponent._core``); a doped region keeps its own colour on ``doped_preset``.
    """

    detail_height = max(min(stack["contact_height"] * 0.18, stack["pad_height"] * 0.2), 1e-6)   # a finish thinner than its pad
    mesa_z = core["z_offset"]                     # a bonded III-V mesa starts on the base of the core it runs over
    mesa_height = stack["rib_height"] * 1.5
    body_height = thickness * 1.4

    def leaves(node: dict[str, Any]):
        if node.get("type") == "group":
            for child in node.get("children", []):
                yield from leaves(child)
        else:
            yield node

    footprints = list(leaves(art))
    packaged = any(node.get("chip_layer") == "package" for node in footprints)
    pad_z = max(stack["pad_z"], body_height) if packaged else stack["pad_z"]
    layers = {
        "core": (core["z_offset"], thickness, core["preset"]),
        "implant": (stack["implant_z"], stack["implant_height"], doped_preset),
        # GE on the waveguide top, as the stack has it (zmin 0.220 on a 0.220 core)
        "germanium": (stack["core_z"] + stack["core_height"], stack["rib_height"] * 1.35, "germanium"),
        "charge": (mesa_z, stack["rib_height"], doped_preset),
        "mesa": (mesa_z, mesa_height, "indium_phosphide"),
        "active": (mesa_z + mesa_height, stack["contact_height"] * 0.35, "gallium_arsenide"),
        "metal": (stack["metal_z"], stack["metal_height"], "gold"),
        "heater": (stack["heater_z"], stack["heater_height"], "titanium_nitride"),
        # a contact plug: from the silicon (the slab top) up to the metal, through the contact and via layers
        "via": (stack["contact_z"], stack["metal_z"] - stack["contact_z"], "copper"),
        "pad": (pad_z, stack["pad_height"], "gold"),
        "pad_finish": (pad_z + stack["pad_height"], detail_height, "gold"),
        "package": (0.0, body_height, "ceramic"),
        "legend": (body_height + detail_height, detail_height, "ceramic"),
    }
    def box_of(node: dict[str, Any]) -> tuple[float, float, float, float] | None:
        if node.get("type") == "rect":
            cx, cy, w, h = float(node["cx"]), float(node["cy"]), float(node["w"]), float(node["h"])
            return cx - w / 2.0, cx + w / 2.0, cy - h / 2.0, cy + h / 2.0
        points = node.get("points") or []
        if not points:
            return None
        xs, ys = [float(q[0]) for q in points], [float(q[1]) for q in points]
        return min(xs), max(xs), min(ys), max(ys)

    traces = [b for b in (box_of(n) for n in footprints if n.get("chip_layer") == "metal") if b]

    def arrival(cx: float, cy: float, w: float, h: float) -> tuple[float, float] | None:
        """Where the metal reaches a pad: the point of its edge nearest a trace that touches it; None when the
        trace runs under the pad."""

        px0, px1, py0, py1 = cx - w / 2.0, cx + w / 2.0, cy - h / 2.0, cy + h / 2.0
        for x0, x1, y0, y1 in traces:
            if x0 <= px1 + 1e-6 and x1 >= px0 - 1e-6 and y0 <= py1 + 1e-6 and y1 >= py0 - 1e-6:
                mx, my = (x0 + x1) / 2.0, (y0 + y1) / 2.0
                if px0 < mx < px1 and py0 < my < py1:
                    return None
                return min(max(mx, px0), px1), min(max(my, py0), py1)
        return None

    children: list[tuple[str, dict[str, Any]]] = []            # (layer, solid)
    for node in footprints:
        kind = node.get("type")
        layer = node.get("chip_layer", "legend" if kind in {"line", "polyline"} else "core")
        z, height, preset = layers[layer]
        color = node.get("stroke") if kind in {"line", "polyline"} else node.get("fill")
        if color in (None, "none"):
            continue
        if layer == "core":
            color = core["color"]
        if kind == "rect":
            mesh = _chip_slab(
                float(node["w"]), float(node["h"]), height,
                x=float(node["cx"]), y=float(node["cy"]),
                color=color, preset=preset, z_offset=z,
            )
            if layer == "pad":                         # the route up from the metal where it reaches the pad
                w, h, cx, cy = float(node["w"]), float(node["h"]), float(node["cx"]), float(node["cy"])
                children.extend(("metal", route) for route in _pad_route(
                    w, h, cx, cy, {**stack, "pad_z": pad_z}, below=stack["metal_z"] + stack["metal_height"],
                    arrive=arrival(cx, cy, w, h)))
            # A schematic cap makes a via visible above its contact strip.
            if layer == "via" and schematic:
                cap = _chip_slab(
                    float(node["w"]), float(node["h"]), detail_height,
                    x=float(node["cx"]), y=float(node["cy"]), color=color, preset=preset,
                    z_offset=stack["metal_z"] + stack["metal_height"],
                )
                cap["material"]["opacity"] = opacity
                children.append(("via", cap))
        elif kind == "polygon":
            mesh = _chip_extruded_polygon(
                [(float(point[0]), float(point[1])) for point in node["points"]],
                height, color=color, preset=preset, opacity=opacity, z_offset=z,
            )
        elif kind in {"line", "polyline"}:
            points = ([(float(node["x1"]), float(node["y1"])), (float(node["x2"]), float(node["y2"]))]
                      if kind == "line" else [(float(point[0]), float(point[1])) for point in node["points"]])
            mesh = _chip_path_slab(
                points, float(node["stroke_width"]), height,
                color=color, preset=preset, z_offset=z, closed=bool(node.get("closed", False)),
            )
        else:
            raise ValueError(f"Unsupported chip process footprint: {kind}")
        if mesh.get("shape") == "group":                   # a path of under two points draws nothing
            continue
        mesh.setdefault("material", {})["opacity"] = opacity
        children.append((layer, mesh))
    for layer, mesh in children:              # an implant changes the silicon in place: it fills its core to the top
        if layer in _DOPED:
            plan, bottom, top = _plan(mesh)
            # the core starts on the implant's base, or on its top where the core stands on the slab (a ridge)
            tops = [high for owner, core in children if owner == "core" for other, low, high in [_plan(core)]
                    if bottom - 1e-9 <= low <= top + 1e-9 and high > top + 1e-9 and plan.within(other.buffer(1e-9))]
            if tops:
                mesh["height"] = max(tops) - bottom
                if mesh.get("shape") == "box":
                    x, _, z = mesh["position"]
                    mesh["position"] = [x, bottom + mesh["height"] / 2.0, z]
    solids: list[dict[str, Any]] = []
    for layer, mesh in children:
        keepers = [other for owner, other in children if owner in _CUT_BY.get(layer, ())]
        solids += _cut_footprints([mesh], keepers) if keepers else [mesh]
    return solids

def _arc_points(
    cx: float,
    cy: float,
    radius: float,
    start_deg: float,
    end_deg: float,
    *,
    segments: int = 16,
) -> list[tuple[float, float]]:
    if segments <= 1:
        angles = [start_deg, end_deg]
    else:
        step = (end_deg - start_deg) / segments
        angles = [start_deg + step * index for index in range(segments + 1)]
    return [
        (cx + radius * math.cos(math.radians(angle)), cy + radius * math.sin(math.radians(angle)))
        for angle in angles
    ]


def _arc_band_points(
    cx: float,
    cy: float,
    inner_radius: float,
    outer_radius: float,
    start_deg: float,
    end_deg: float,
    *,
    segments: int = 36,
) -> list[tuple[float, float]]:
    outer = _arc_points(cx, cy, outer_radius, start_deg, end_deg, segments=segments)
    inner = _arc_points(cx, cy, inner_radius, end_deg, start_deg, segments=segments)
    return outer + inner


def _arc_length_to_degrees(radius: float, arc_length: float) -> float:
    if radius <= 1e-9:
        return 0.0
    return math.degrees(arc_length / radius)


def _arc_band_polygons(
    cx: float,
    cy: float,
    inner_radius: float,
    outer_radius: float,
    arc_ranges: list[tuple[float, float]],
    *,
    segments: int = 36,
) -> list[list[tuple[float, float]]]:
    polygons: list[list[tuple[float, float]]] = []
    for start_deg, end_deg in arc_ranges:
        if abs(end_deg - start_deg) <= 1e-6:
            continue
        polygons.append(
            _arc_band_points(
                cx,
                cy,
                inner_radius,
                outer_radius,
                start_deg,
                end_deg,
                segments=segments,
            )
        )
    return polygons


def _chip_layer_stack(core_thickness: float, *, schematic: bool = False) -> dict[str, float]:
    from optodraw.components.onchip.layer_stack import component_stack

    return component_stack(core_thickness, schematic=schematic)



def _mmi_port_offsets(count: int, gap: float) -> list[float]:
    if count <= 1:
        return [0.0]
    start = -0.5 * gap * (count - 1)
    return [start + gap * index for index in range(count)]


def _mmi_ports(
    total_length: float,
    input_offsets: list[float],
    output_offsets: list[float],
    waveguide_width: float,
) -> dict[str, Port]:
    half = total_length / 2.0
    ports: dict[str, Port] = {}
    for index, y in enumerate(input_offsets, start=1):
        ports[f"o{index}"] = Port(f"o{index}", Vec3(-half, y, 0), orientation_deg=180, width=waveguide_width)
    start_index = len(input_offsets) + 1
    for index, y in enumerate(output_offsets, start=start_index):
        ports[f"o{index}"] = Port(f"o{index}", Vec3(half, y, 0), orientation_deg=0, width=waveguide_width)
    return ports


# Smooth (raised-cosine) taper resolution for MMI/coupler-style devices.
_MMI_TAPER_SEGMENTS = 16
# Tapers run slightly INTO the body so the body covers the junction (no gap).
_MMI_TAPER_OVERLAP = 0.8


def _rounded_rect_points(cx: float, cy: float, width: float, height: float, radius: float, *, corner_segments: int = 5) -> list[tuple[float, float]]:
    """Outline of a rounded rectangle (smoothed device body corners)."""

    r = max(min(radius, width / 2.0, height / 2.0), 0.0)
    hw, hh = width / 2.0, height / 2.0
    corners = [
        (cx + hw - r, cy + hh - r, 0.0, 90.0),
        (cx - hw + r, cy + hh - r, 90.0, 180.0),
        (cx - hw + r, cy - hh + r, 180.0, 270.0),
        (cx + hw - r, cy - hh + r, 270.0, 360.0),
    ]
    points: list[tuple[float, float]] = []
    for ccx, ccy, a0, a1 in corners:
        for index in range(corner_segments + 1):
            angle = math.radians(a0 + (a1 - a0) * index / corner_segments)
            points.append((ccx + r * math.cos(angle), ccy + r * math.sin(angle)))
    return points


def _mmi_children(
    body_length: float,
    body_width: float,
    taper_length: float,
    waveguide_width: float,
    width_taper: float,
    input_offsets: list[float],
    output_offsets: list[float],
    *,
    color: str,
    opacity: float,
) -> list[dict[str, Any]]:
    half_body = body_length / 2.0
    overlap = _MMI_TAPER_OVERLAP
    # Smooth tapers first; they overlap into the body so the body rect (drawn last,
    # on top) gives a flush, gap-free junction on a clean rectangular MMI.
    children: list[dict[str, Any]] = []
    for y in input_offsets:
        children.append(
            _chip_segment_polygon(
                (-half_body - taper_length, y),
                (-half_body + overlap, y),
                waveguide_width,
                width_taper,
                fill=color,
                opacity=opacity,
                stroke="#1a4373",
                stroke_width=0.08,
                segments=_MMI_TAPER_SEGMENTS,
            )
        )
    for y in output_offsets:
        children.append(
            _chip_segment_polygon(
                (half_body - overlap, y),
                (half_body + taper_length, y),
                width_taper,
                waveguide_width,
                fill=color,
                opacity=opacity,
                stroke="#1a4373",
                stroke_width=0.08,
                segments=_MMI_TAPER_SEGMENTS,
            )
        )
    children.append(_chip_box(0.0, 0.0, body_length, body_width, color, opacity, stroke="#1a4373", stroke_width=0.08))
    return children


def _mmi_slab_children(
    body_length: float,
    body_width: float,
    taper_length: float,
    waveguide_width: float,
    width_taper: float,
    input_offsets: list[float],
    output_offsets: list[float],
    thickness: float,
    *,
    color: str,
    preset: str | None = None,
    z_offset: float = 0.0,
) -> list[dict[str, Any]]:
    half_body = body_length / 2.0
    overlap = _MMI_TAPER_OVERLAP
    children = [_chip_slab(body_length, body_width, thickness, color=color, preset=preset, z_offset=z_offset)]
    for y in input_offsets:
        children.append(
            _chip_segment_slab(
                (-half_body - taper_length, y),
                (-half_body + overlap, y),
                waveguide_width,
                width_taper,
                thickness,
                color=color,
                preset=preset,
                segments=_MMI_TAPER_SEGMENTS,
                z_offset=z_offset,
            )
        )
    for y in output_offsets:
        children.append(
            _chip_segment_slab(
                (half_body - overlap, y),
                (half_body + taper_length, y),
                width_taper,
                waveguide_width,
                thickness,
                color=color,
                preset=preset,
                segments=_MMI_TAPER_SEGMENTS,
                z_offset=z_offset,
            )
        )
    return children


def _chip_fiber_2d_children(
    cx: float,
    cy: float,
    cladding_diameter: float,
    core_diameter: float,
    *,
    opacity: float,
) -> list[dict[str, Any]]:
    cladding_radius = cladding_diameter / 2.0
    core_radius = min(core_diameter / 2.0, cladding_radius * 0.74)
    # The fiber hovers ABOVE the grating (plan view: concentric circles over the
    # teeth) — translucent fills so the grating stays readable underneath.
    return [
        _chip_circle(
            cx,
            cy,
            cladding_radius,
            stroke="#5c7d94",
            stroke_width=0.16,
            opacity=min(opacity, 1.0) * 0.55,
            fill="#c9dceb",
        ),
        _chip_circle(
            cx,
            cy,
            core_radius,
            stroke="#89b2ce",
            stroke_width=0.12,
            opacity=min(opacity, 1.0) * 0.8,
            fill="#eef8ff",
        ),
    ]


def _chip_fiber_3d_children(
    cx: float,
    cy: float,
    cladding_diameter: float,
    core_diameter: float,
    fiber_length: float,
    *,
    base_height: float,
) -> list[dict[str, Any]]:
    cladding_radius = cladding_diameter / 2.0
    core_radius = min(core_diameter / 2.0, cladding_radius * 0.74)
    # a small launch gap — the fiber must visually SIT over the grating, not float
    center_y = base_height + 1.6 + fiber_length / 2.0
    return [
        {
            "shape": "cylinder",
            "radius": cladding_radius,
            "height": fiber_length,
            "position": [cx, center_y, -cy],
            "material": {
                "color": "#c9dceb",
                "opacity": 0.82,
                "transparent": True,
                "preset": "glass",
            },
        },
        {
            "shape": "cylinder",
            "radius": core_radius,
            "height": fiber_length,
            "position": [cx, center_y, -cy],
            "material": {
                "color": "#eef8ff",
                "opacity": 0.96,
                "transparent": True,
                "preset": "glass",
            },
        },
    ]


def _normalize_xy(x: float, y: float) -> tuple[float, float]:
    length = math.hypot(x, y)
    if length <= 1e-12:
        return (0.0, 0.0)
    return (x / length, y / length)


def _polyline_outline(points: list[tuple[float, float]], width: float) -> list[tuple[float, float]]:
    if len(points) < 2:
        return points

    half_width = width / 2.0
    normals: list[tuple[float, float]] = []
    for start, end in zip(points, points[1:]):
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        nx, ny = _normalize_xy(-dy, dx)
        normals.append((nx, ny))

    left_points: list[tuple[float, float]] = []
    right_points: list[tuple[float, float]] = []
    for index, point in enumerate(points):
        if index == 0:
            nx, ny = normals[0]
        elif index == len(points) - 1:
            nx, ny = normals[-1]
        else:
            prev_nx, prev_ny = normals[index - 1]
            next_nx, next_ny = normals[index]
            nx, ny = _normalize_xy(prev_nx + next_nx, prev_ny + next_ny)
            if abs(nx) < 1e-12 and abs(ny) < 1e-12:
                nx, ny = next_nx, next_ny
            correction = max(nx * next_nx + ny * next_ny, 0.35)
            nx /= correction
            ny /= correction

        left_points.append((point[0] + nx * half_width, point[1] + ny * half_width))
        right_points.append((point[0] - nx * half_width, point[1] - ny * half_width))

    return left_points + list(reversed(right_points))


def _polyline_outline_closed(points: list[tuple[float, float]], width: float) -> list[tuple[float, float]]:
    if len(points) < 3:
        return _polyline_outline(points, width)

    half_width = width / 2.0
    normals: list[tuple[float, float]] = []
    for index, start in enumerate(points):
        end = points[(index + 1) % len(points)]
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        nx, ny = _normalize_xy(-dy, dx)
        normals.append((nx, ny))

    left_points: list[tuple[float, float]] = []
    right_points: list[tuple[float, float]] = []
    for index, point in enumerate(points):
        prev_nx, prev_ny = normals[index - 1]
        next_nx, next_ny = normals[index]
        nx, ny = _normalize_xy(prev_nx + next_nx, prev_ny + next_ny)
        if abs(nx) < 1e-12 and abs(ny) < 1e-12:
            nx, ny = next_nx, next_ny
        correction = max(nx * next_nx + ny * next_ny, 0.35)
        nx /= correction
        ny /= correction
        left_points.append((point[0] + nx * half_width, point[1] + ny * half_width))
        right_points.append((point[0] - nx * half_width, point[1] - ny * half_width))

    return left_points + list(reversed(right_points))


def _segment_outline(
    start: tuple[float, float],
    end: tuple[float, float],
    width_start: float,
    width_end: float,
    *,
    segments: int = 1,
) -> list[tuple[float, float]]:
    """Taper outline from ``width_start`` to ``width_end``.

    ``segments <= 1`` → a straight linear taper (4-point trapezoid). ``segments > 1``
    → a smooth raised-cosine (S-curve) taper with tangent-flat endpoints, used to
    curve MMI/coupler tapers instead of the blocky linear transition.
    """

    sx, sy = start
    ex, ey = end
    dx = ex - sx
    dy = ey - sy
    length = math.hypot(dx, dy)
    if length <= 1e-9:
        half = max(width_start, width_end) / 2.0
        return [
            (sx - half, sy - half),
            (sx + half, sy - half),
            (sx + half, sy + half),
            (sx - half, sy + half),
        ]

    nx = -dy / length
    ny = dx / length
    if segments <= 1:
        return [
            (sx + nx * width_start / 2.0, sy + ny * width_start / 2.0),
            (ex + nx * width_end / 2.0, ey + ny * width_end / 2.0),
            (ex - nx * width_end / 2.0, ey - ny * width_end / 2.0),
            (sx - nx * width_start / 2.0, sy - ny * width_start / 2.0),
        ]

    top: list[tuple[float, float]] = []
    bottom: list[tuple[float, float]] = []
    for index in range(segments + 1):
        t = index / segments
        # raised cosine: smooth start/end tangents (S-curve adiabatic taper)
        w = width_start + (width_end - width_start) * (1.0 - math.cos(math.pi * t)) / 2.0
        px = sx + dx * t
        py = sy + dy * t
        top.append((px + nx * w / 2.0, py + ny * w / 2.0))
        bottom.append((px - nx * w / 2.0, py - ny * w / 2.0))
    return top + bottom[::-1]


def _translate_points(points: list[tuple[float, float]], dx: float = 0.0, dy: float = 0.0) -> list[tuple[float, float]]:
    return [(x + dx, y + dy) for x, y in points]


def _rotate_2d_node_ccw(node: dict[str, Any]) -> dict[str, Any]:
    """Rotate a 2D geometry node 90° counter-clockwise: (x, y) → (−y, x).

    This transforms all coordinate-bearing fields so that a chip → component
    that was drawn in the "pointing right" convention now points "up": grating
    faces +Y, waveguide port exits via −Y.
    """
    result = deepcopy(node)
    node_type = result.get("type")

    if node_type == "group":
        result["children"] = [
            _rotate_2d_node_ccw(child)
            for child in result.get("children", [])
            if isinstance(child, dict)
        ]
        return result

    # rect: (cx, cy, w, h) — after 90° CCW, width ↔ height also swap because
    # the long axis was along X and is now along Y.
    if node_type == "rect":
        cx, cy = float(result.get("cx", 0.0)), float(result.get("cy", 0.0))
        w, h = float(result.get("w", 0.0)), float(result.get("h", 0.0))
        result["cx"] = -cy
        result["cy"] = cx
        result["w"] = h
        result["h"] = w
        return result

    if node_type in ("polygon", "polyline"):
        pts = result.get("points", [])
        rotated: list[Any] = []
        for p in pts:
            if len(p) >= 3:
                rotated.append((-float(p[1]), float(p[0]), p[2]))
            else:
                rotated.append((-float(p[1]), float(p[0])))
        result["points"] = rotated
        return result

    if node_type == "circle":
        cx, cy = float(result.get("cx", 0.0)), float(result.get("cy", 0.0))
        result["cx"] = -cy
        result["cy"] = cx
        return result

    if node_type == "line":
        x1, y1 = float(result.get("x1", 0.0)), float(result.get("y1", 0.0))
        x2, y2 = float(result.get("x2", 0.0)), float(result.get("y2", 0.0))
        result["x1"] = -y1
        result["y1"] = x1
        result["x2"] = -y2
        result["y2"] = x2
        return result

    return result


def _rotate_3d_node_ccw(node: dict[str, Any]) -> dict[str, Any]:
    """Rotate a 3D geometry node 90° CCW in the chip plane: chip(x,y) → chip(−y, x).

    3D convention used throughout the renderers:
        position = [chip_x, 3d_height, −chip_y]
    After CCW rotation:
        chip_x_new = −chip_y_old   →  position[0] = −(−position[2]) = position[2]
        chip_y_new = chip_x_old    →  −chip_y_new = −position[0]
        position_new = [position[2], position[1], −position[0]]
    For "box": width (chip-X extent) ↔ depth (chip-Y extent) also swap.
    """
    result = deepcopy(node)
    shape = result.get("shape")

    if shape == "group":
        result["children"] = [
            _rotate_3d_node_ccw(child)
            for child in result.get("children", [])
            if isinstance(child, dict)
        ]
        return result

    if shape == "box":
        pos = result.get("position", [0.0, 0.0, 0.0])
        px, py_h, pz = float(pos[0]), float(pos[1]), float(pos[2])
        result["position"] = [pz, py_h, -px]
        w = result.get("width", 0.0)
        d = result.get("depth", 0.0)
        result["width"] = d
        result["depth"] = w
        return result

    if shape == "extruded_polygon":
        pts = result.get("points", [])
        rotated: list[Any] = []
        for p in pts:
            if len(p) >= 3:
                rotated.append((-float(p[1]), float(p[0]), p[2]))
            else:
                rotated.append((-float(p[1]), float(p[0])))
        result["points"] = rotated
        if result.get("holes"):                  # the holes turn with the outline
            result["holes"] = [[type(p)((-float(p[1]), float(p[0]), *p[2:])) for p in hole] for hole in result["holes"]]
        pos = result.get("position")
        if isinstance(pos, list) and len(pos) >= 3:
            px, py_h, pz = float(pos[0]), float(pos[1]), float(pos[2])
            result["position"] = [pz, py_h, -px]
        return result

    if shape == "cylinder":
        pos = result.get("position", [0.0, 0.0, 0.0])
        px, py_h, pz = float(pos[0]), float(pos[1]), float(pos[2])
        result["position"] = [pz, py_h, -px]
        return result

    return result


def _translate_layout_geometry(node: dict[str, Any], dx: float, dy: float) -> dict[str, Any]:
    translated = deepcopy(node)

    if translated.get("type") == "group" and isinstance(translated.get("children"), list):
        translated["children"] = [
            _translate_layout_geometry(child, dx, dy)
            for child in translated["children"]
            if isinstance(child, dict)
        ]
        return translated

    if translated.get("shape") == "group" and isinstance(translated.get("children"), list):
        translated["children"] = [
            _translate_layout_geometry(child, dx, dy)
            for child in translated["children"]
            if isinstance(child, dict)
        ]
        return translated

    shape = translated.get("shape")
    if shape is not None:
        # A 3D solid moves once: an unrotated extrusion by its plan outline (and holes), a tube path by the x and
        # z of its points, anything else by its position. Moving an extrusion's points and its position both
        # moved metal (which has a position: its height) twice.
        def plan(point: Any) -> Any:
            return type(point)((float(point[0]) + dx, float(point[1]) + dy, *point[2:]))

        if shape == "extruded_polygon" and not any(translated.get("rotation") or []):
            translated["points"] = [plan(point) for point in translated.get("points", [])]
            if translated.get("holes"):
                translated["holes"] = [[plan(point) for point in hole] for hole in translated["holes"]]
        elif shape == "tube_path":
            translated["points"] = [type(point)((float(point[0]) + dx, point[1], float(point[2]) - dy))
                                    for point in translated.get("points", [])]
        else:
            position = list(translated.get("position") or [0.0, 0.0, 0.0])
            translated["position"] = [float(position[0]) + dx, position[1], float(position[2]) - dy]
        return translated

    if "cx" in translated:
        translated["cx"] = float(translated["cx"]) + dx
    if "cy" in translated:
        translated["cy"] = float(translated["cy"]) + dy
    if "x1" in translated:
        translated["x1"] = float(translated["x1"]) + dx
    if "x2" in translated:
        translated["x2"] = float(translated["x2"]) + dx
    if "y1" in translated:
        translated["y1"] = float(translated["y1"]) + dy
    if "y2" in translated:
        translated["y2"] = float(translated["y2"]) + dy

    points = translated.get("points")
    if isinstance(points, list):
        shifted_points: list[Any] = []
        for point in points:
            if isinstance(point, tuple) and len(point) >= 2:
                if len(point) >= 3:
                    shifted_points.append((float(point[0]) + dx, float(point[1]) + dy, point[2]))
                else:
                    shifted_points.append((float(point[0]) + dx, float(point[1]) + dy))
            elif isinstance(point, list) and len(point) >= 2:
                if len(point) >= 3:
                    shifted_points.append([float(point[0]) + dx, float(point[1]) + dy, point[2]])
                else:
                    shifted_points.append([float(point[0]) + dx, float(point[1]) + dy])
            else:
                shifted_points.append(point)
        translated["points"] = shifted_points

    position = translated.get("position")
    if isinstance(position, list) and len(position) >= 3:
        translated["position"] = [float(position[0]) + dx, position[1], float(position[2]) - dy]

    return translated


def _mirror_layout_geometry_y(node: dict[str, Any]) -> dict[str, Any]:
    """Mirror a 2D or 3D layout node about y = 0: the part turned top to bottom."""

    mirrored = deepcopy(node)
    children = mirrored.get("children")
    if isinstance(children, list) and (mirrored.get("type") == "group" or mirrored.get("shape") == "group"):
        mirrored["children"] = [_mirror_layout_geometry_y(child) for child in children if isinstance(child, dict)]
        return mirrored
    shape = mirrored.get("shape")
    if shape == "tube_path":                    # 3D points: z flips, the height stays
        mirrored["points"] = [type(point)((point[0], point[1], -float(point[2]))) for point in mirrored.get("points", [])]
        return mirrored
    if shape == "extruded_polygon" and mirrored.get("holes"):
        mirrored["holes"] = [[type(point)((point[0], -float(point[1]), *point[2:])) for point in reversed(hole)]
                             for hole in mirrored["holes"]]
    for key in ("cy", "y1", "y2"):
        if key in mirrored:
            mirrored[key] = -float(mirrored[key])
    points = mirrored.get("points")
    if isinstance(points, list):              # reversed, so a polygon keeps its winding
        mirrored["points"] = [type(point)((point[0], -float(point[1]), *point[2:]))
                              if isinstance(point, (tuple, list)) and len(point) >= 2 else point
                              for point in reversed(points)]
    position = mirrored.get("position")
    if isinstance(position, list) and len(position) >= 3:
        mirrored["position"] = [position[0], position[1], -float(position[2])]
    return mirrored


def _mirror_points_x(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    return [(-x, y) for x, y in reversed(points)]
