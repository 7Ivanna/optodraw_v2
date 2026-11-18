"""Checks an agent or an author runs before calling a part done.

``check_part_3d`` finds what reviews of the 3D parts kept finding: a solid that touches nothing (a knob
behind a ring, a wheel with no shaft) and a post that meets a round rim or the inside of its boss instead
of a flat face. Each finding is one sentence; an empty list means the checks passed, not that the part is
right: look at it too.
"""

from __future__ import annotations

import base64
import copy
import io
import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from optodraw.core.component import ANNOTATION_TYPES
from optodraw.core.transform import Vec3


def solid_boxes(node: dict[str, Any], offset=(0.0, 0.0, 0.0)) -> Iterator[tuple[dict, list[tuple[float, float]]]]:
    """``(solid, [(x0, x1), (y0, y1), (z0, z1)])`` for every solid of a 3D geometry tree, its corners turned
    by its Euler rotation. Boxes round turned solids are generous."""

    def turn(v, r):
        (x, y, z), (rx, ry, rz) = v, r
        x, y = x * math.cos(rz) - y * math.sin(rz), x * math.sin(rz) + y * math.cos(rz)
        x, z = x * math.cos(ry) + z * math.sin(ry), -x * math.sin(ry) + z * math.cos(ry)
        y, z = y * math.cos(rx) - z * math.sin(rx), y * math.sin(rx) + z * math.cos(rx)
        return x, y, z

    p = node.get("position") or [0.0, 0.0, 0.0]
    if node.get("shape") == "group":
        for child in node.get("children", []):
            yield from solid_boxes(child, tuple(o + q for o, q in zip(offset, p)))
        return
    s, kind = node, node.get("shape")
    if kind == "box":
        box = [(-s["width"] / 2, s["width"] / 2), (-s["height"] / 2, s["height"] / 2), (-s["depth"] / 2, s["depth"] / 2)]
    elif kind == "cylinder":
        box = [(-s["radius"], s["radius"]), (-s["height"] / 2, s["height"] / 2), (-s["radius"], s["radius"])]
    elif kind == "sphere":
        scale = s.get("scale", [1.0, 1.0, 1.0])
        box = [(-s["radius"] * k, s["radius"] * k) for k in scale]
    elif kind == "torus":
        r = s["radius"] + s["tube"]
        box = [(-r, r), (-r, r), (-s["tube"], s["tube"])]
    elif kind == "lathe_profile":
        r = max(q[0] for q in s["points"])
        box = [(-r, r), (min(q[1] for q in s["points"]), max(q[1] for q in s["points"])), (-r, r)]
    elif kind == "extruded_polygon":
        u, v = [q[0] for q in s["points"]], [q[1] for q in s["points"]]
        box = [(min(u), max(u)), (0.0, s["height"]), (-max(v), -min(v))]
    else:
        return
    corners = [turn((x, y, z), s.get("rotation") or [0.0, 0.0, 0.0]) for x in box[0] for y in box[1] for z in box[2]]
    yield s, [(min(c[i] for c in corners) + offset[i] + p[i], max(c[i] for c in corners) + offset[i] + p[i])
              for i in range(3)]


def _name(solid: dict) -> str:
    where = [round(v, 2) for v in (solid.get("position") or [0, 0, 0])]
    role = f" ({solid['role']})" if solid.get("role") else ""
    return f"{solid.get('shape')}{role} at {where}"


def check_part_3d(part: Any) -> list[str]:
    """Return one sentence per 3D fault of ``part``: solids that touch nothing, and a post that meets no
    flat face. A part with ``base_mount="none"`` (or ``lies_on_table``) may rest loose groups on the table.
    The post rule holds only for a part the 3D viewer stands on a post: an instrument, a stage or a periscope
    stands on the table. A chip part is not checked: its films sit in a layer stack with cladding between
    them, on the die."""

    from optodraw.components.onchip.base import ChipComponent
    from optodraw.registry import component_registry
    from optodraw.renderers.threejs_renderer import is_beam_plane_optic

    if isinstance(part, ChipComponent):
        return []
    geo = part.geometry_3d()
    solids = list(solid_boxes(geo))
    if not solids:
        return []
    findings: list[str] = []
    size = max(max(b[i][1] for _, b in solids) - min(b[i][0] for _, b in solids) for i in range(3)) or 1.0
    tol = 1e-3 * size
    on_table = getattr(part, "lies_on_table", False) or getattr(part, "base_mount", "post") == "none"

    def touching(p, q):
        return all(p[k][0] <= q[k][1] + tol and q[k][0] <= p[k][1] + tol for k in range(3))

    groups, left = [], set(range(len(solids)))
    while left:
        group, grew = {left.pop()}, True
        while grew:
            grew = False
            for j in list(left):
                if any(touching(solids[i][1], solids[j][1]) for i in group):
                    group.add(j)
                    left.discard(j)
                    grew = True
        groups.append(group)
    main = max(groups, key=len)
    floor = min(b[1][0] for _, b in solids)
    for group in groups:
        if group is main or (on_table and abs(min(solids[j][1][1][0] for j in group) - floor) <= tol):
            continue
        findings += [f"{_name(solids[j][0])} touches nothing: it hangs in the air" for j in sorted(group)]

    spec = component_registry().get(getattr(part, "component_type", ""))
    if (getattr(part, "base_mount", "post") == "post" and not on_table
            and is_beam_plane_optic(part, spec.category if spec else "")):
        if "post_at" in geo:
            x, top, z = (float(v) for v in geo["post_at"])
        else:
            x = (min(b[0][0] for _, b in solids) + max(b[0][1] for _, b in solids)) / 2.0
            z = (min(b[2][0] for _, b in solids) + max(b[2][1] for _, b in solids)) / 2.0
            top = floor
        near = 1e-6 + 1e-3 * max(abs(top), 1.0)
        flat = [s for s, b in solids
                if (s["shape"] in ("box", "extruded_polygon") or (s["shape"] == "cylinder" and not any(s.get("rotation") or [])))
                and abs(b[1][0] - top) <= near and b[0][0] - near <= x <= b[0][1] + near and b[2][0] - near <= z <= b[2][1] + near]
        if not flat:
            findings.append(f"the post top at ({x:.2f}, {top:.2f}, {z:.2f}) meets no flat face: put post_at on the "
                            "bottom face of a box or boss (its y = boss centre y - boss height / 2)")
    return findings


# ---------------------------------------------------------------- the figure gate

_ORIGIN = Vec3(0.0, 0.0, 0.0)

def _dead_ends(beams: list[Any], cones: list[Any] = (), routes: list[Any] = ()) -> list[str]:
    """A beam that ends in a part light leaves again (a splitter, a lens, a plate): the figure stops short.

    A part is a turning point, not a dead end, when another beam or a focusing beam leaves it (light back from
    a sample, a cone after a lens). A port a route joins is in use: the light goes on in a fibre. A detector has
    no other face, so a beam that ends on it is finished.
    """

    from optodraw.core.component import Component

    def stops(beam: Any) -> list[tuple[Any, str]]:
        out = []
        for anchor in beam.anchors:
            if isinstance(anchor, (tuple, list)) and len(anchor) == 2 and isinstance(anchor[0], Component):
                out.append((anchor[0], str(anchor[1])))
            elif isinstance(anchor, Component):
                out.append((anchor, ""))
        return out

    named = [stops(beam) for beam in beams]
    leaves = {id(part) for chain in named for part, _ in chain[:-1]}
    for cone in cones:                                          # a cone starts at a part, or at a port of one
        start = cone.anchor1[0] if isinstance(cone.anchor1, (tuple, list)) else cone.anchor1
        if isinstance(start, Component):
            leaves.add(id(start))
    used: dict[int, set[str]] = {}
    ends = [(route.start_component, route.start_port) for route in routes]
    ends += [(route.end_component, route.end_port) for route in routes]
    for part, port in [pair for chain in named for pair in chain] + ends:
        used.setdefault(id(part), set()).add(str(port))
    findings, seen = [], set()
    for chain in named:
        if not chain:
            continue
        part, port = chain[-1]
        name = getattr(part, "label", "") or part.component_type
        if len(chain) > 1 and chain[-2][0] is part and port:
            findings.append(f"the beam leaves {name} by {port} and ends in the air: end it on a detector or a "
                            "beam block")
            continue
        if id(part) in leaves or id(part) in seen or _ends_beams(part):
            continue
        seen.add(id(part))
        arrived = port or _nearest_port(part, chain[-2][0] if len(chain) > 1 else None)
        faces = part.ports()
        reach = max((math.hypot(float(p.center.x), float(p.center.y)) for p in faces.values()), default=0.0)
        free = [name for name, p in faces.items()                   # a port at the centre is a reference point
                if getattr(p, "kind", "") == "free_space" and name not in used[id(part)] and name != arrived
                and math.hypot(float(p.center.x), float(p.center.y)) > 0.05 * reach]
        if free:
            findings.append(f"the beam stops at {name}: light leaves it by {', '.join(free)}; draw those beams, "
                            "or end them on a detector or a beam block")
    return findings


_BEAM_ENDS = ("Meter", "Detector", "Photodiode", "Camera", "Sensor", "Dump", "Block", "Counter", "Spectrometer",
              "Screen", "SNSPD", "CCD", "Sample")


def _ends_beams(part: Any) -> bool:
    """A detector, a beam dump or a sample ends a beam by nature, even with a pass-through port."""

    from optodraw.registry import component_registry

    kind = str(getattr(part, "component_type", ""))
    spec = component_registry().get(kind)
    return any(word in kind for word in _BEAM_ENDS) or (spec is not None and spec.category in ("samples", "devices"))


def _drawn_box(node: Any) -> tuple[float, float, float, float]:
    """The part's box in its own frame: its own shapes are tighter than its art frame, which is the fallback."""

    from optodraw.layout import _bounds_from_geometry, estimate_component_bounds

    try:
        drawn = _bounds_from_geometry(node.geometry_2d())
    except Exception:
        drawn = None
    if getattr(node, "_art_scale_from_ports", False):      # the ports size the art, not the shapes: the art counts
        from optodraw.symbols.art import art_bounds, union

        drawn = union(drawn, art_bounds(node))
    x0, y0, x1, y1 = (float(v) for v in (drawn or estimate_component_bounds(node)))
    return x0, y0, x1, y1


def _holds(outer: Any, inner: Any) -> bool:
    """True when ``inner`` sits inside ``outer`` (an objective in a cryostat): its label may lie on it."""

    centre, origin = inner.world_position, outer.world_position
    turn = math.radians(-float(outer.world_transform.rotation_deg.z))
    dx, dy = float(centre.x - origin.x), float(centre.y - origin.y)
    x, y = dx * math.cos(turn) - dy * math.sin(turn), dx * math.sin(turn) + dy * math.cos(turn)
    x0, y0, x1, y1 = _drawn_box(outer)
    ix0, iy0, ix1, iy1 = _drawn_box(inner)
    return x0 < x < x1 and y0 < y < y1 and (x1 - x0) * (y1 - y0) > 4.0 * (ix1 - ix0) * (iy1 - iy0)


def _off_focus(beams: list[Any]) -> list[str]:
    """A detector after a lens sits at its focus: the lens is there to put the light on it. A flat mirror between
    them folds the path and keeps its length, so the gap is measured along the folds."""

    from optodraw.core.component import Component

    findings = []
    for beam in beams:
        chain = [a for a in beam.anchors
                 if isinstance(a, (tuple, list)) and len(a) == 2 and isinstance(a[0], Component)]
        for index, ((lens, _), (detector, port)) in enumerate(zip(chain, chain[1:])):
            focal = getattr(lens, "focal_length", None)
            if lens is detector or not focal or lens.component_type != "Lens":
                continue
            point = lens.world_transform.apply_to_point(_ORIGIN)
            gap = 0.0
            for detector, port in chain[index + 1:]:
                face = detector.world_port(str(port)).center
                gap += math.hypot(face.x - point.x, face.y - point.y)
                point = face
                if getattr(detector, "surface_type", None) != "flat" or str(port) != "io":
                    break
            else:
                continue                                  # the beam ends on a fold: no detector here
            faces = [p for p in detector.ports().values() if getattr(p, "kind", "") == "free_space"]
            if len(faces) != 1:
                continue
            if abs(gap - float(focal)) > 0.25 * abs(float(focal)):
                name = getattr(detector, "label", "") or detector.component_type
                lens_name = getattr(lens, "label", "") or "the lens"
                findings.append(f"{name} sits {gap:.0f} after {lens_name} of focal length {float(focal):g}, off its "
                                f"focus: put it at {float(focal):g}, or take the lens out")
    return findings


MIN_FILL = 0.2              # a chip figure whose parts fill less of its box is spread out
MAX_ROUTE_PARTS = 3.0       # a route longer than this many times the larger part it joins, and longer than
LONG_ROUTE_SHARE = 0.5      # this share of the figure's diagonal, crosses the figure
OUTSIDE_SHARE = 0.3         # unless at most this share of it lies among the other parts: a loop round them


def _spread(parts: list[Any], routes: list[Any]) -> list[str]:
    """A chip figure is compact: its parts fill a fair share of the box round them, and no wire runs far."""

    boxes = [part.drawn_box() for part in parts]
    if len(boxes) < 2:
        return []
    area = sum((x1 - x0) * (y1 - y0) for x0, y0, x1, y1 in boxes)
    x0, y0 = min(b[0] for b in boxes), min(b[1] for b in boxes)
    x1, y1 = max(b[2] for b in boxes), max(b[3] for b in boxes)
    findings = []
    fill = area / max((x1 - x0) * (y1 - y0), 1e-9)
    if fill < MIN_FILL:
        findings.append(f"the parts fill {fill:.0%} of the figure: move them closer (a figure is compact, not to "
                        "scale: keep schematic sizes, small pads beside their parts, short wires)")
    diagonal = math.hypot(x1 - x0, y1 - y0)
    for route in routes:
        points = route.resolve_points()
        length = sum(math.dist(a[:2], b[:2]) for a, b in zip(points, points[1:]))
        joined = [part for part in (route.start_component, route.end_component) if part is not None]
        larger = max((max(b[2] - b[0], b[3] - b[1]) for b in (part.drawn_box() for part in joined)), default=0.0)
        if length > MAX_ROUTE_PARTS * larger and length > LONG_ROUTE_SHARE * diagonal and not _round_the_rest(
                points, [box for part, box in zip(parts, boxes) if part not in joined]):
            ends = [getattr(part, "label", "") or getattr(part, "component_type", "part") for part in joined]
            findings.append(f"the route from {' to '.join(ends)} runs {length / max(larger, 1e-9):.0f} times the size "
                            "of the parts it joins, across the figure: put them, or the pad, closer")
    return findings


def _round_the_rest(points: list, boxes: list[tuple[float, float, float, float]]) -> bool:
    """A route that runs round the other parts in an outside lane (a feedback bus): at most OUTSIDE_SHARE of
    its length inside the box of the parts it does not join."""

    if not boxes:
        return False
    x0, y0 = min(b[0] for b in boxes), min(b[1] for b in boxes)
    x1, y1 = max(b[2] for b in boxes), max(b[3] for b in boxes)
    inside = total = 0.0
    for a, b in zip(points, points[1:]):
        run = math.dist(a[:2], b[:2])
        steps = max(1, int(run / max((x1 - x0 + y1 - y0) / 200.0, 1e-6)))
        for k in range(steps):
            t = (k + 0.5) / steps
            x, y = a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t
            inside += run / steps if x0 < x < x1 and y0 < y < y1 else 0.0
        total += run
    return total > 0 and inside <= OUTSIDE_SHARE * total


def _nearest_port(part: Any, came_from: Any) -> str:
    """The face a beam that names only the part arrives at: the port nearest the part it came from."""

    ports = part.world_ports() if callable(getattr(part, "world_ports", None)) else {}
    ports = {name: port for name, port in ports.items() if port.kind != "electrical"}      # light lands on no jack
    if not ports or came_from is None:
        return "in"
    origin = came_from.world_transform.apply_to_point(_ORIGIN)
    return min(ports, key=lambda n: (ports[n].center.x - origin.x) ** 2 + (ports[n].center.y - origin.y) ** 2)


ARROW_REACH = 5.0          # how near a port an arrow's tip or tail stands to show the light going in or out there
ARROW_ALIGN = 0.866        # cos 30 degrees: the arrow runs along the port's axis


def _marked_by_an_arrow(parts: list[Any]) -> set[tuple[int, str]]:
    """Optical ports where a SignalArrow shows the light: its head stands at the port pointing in, or its tail
    starts there pointing out. A figure draws its light in and out this way, as a paper does."""

    marked: set[tuple[int, str]] = set()
    arrows = [p for p in parts if p.component_type == "SignalArrow"]
    for arrow in arrows:
        ends = arrow.world_ports()
        tail, head = ends["in"].center, ends["out"].center
        length = math.hypot(float(head.x - tail.x), float(head.y - tail.y))
        if length < 1e-9:
            continue
        ax, ay = float(head.x - tail.x) / length, float(head.y - tail.y) / length
        for node in parts:
            if node is arrow:
                continue
            for name, port in node.world_ports().items():
                if port.kind != "optical":
                    continue
                ux, uy = math.cos(math.radians(port.orientation_deg)), math.sin(math.radians(port.orientation_deg))
                x, y = float(port.center.x), float(port.center.y)
                light_in = math.hypot(float(head.x) - x, float(head.y) - y) <= ARROW_REACH and -(ax * ux + ay * uy) >= ARROW_ALIGN
                light_out = math.hypot(float(tail.x) - x, float(tail.y) - y) <= ARROW_REACH and ax * ux + ay * uy >= ARROW_ALIGN
                if light_in or light_out:
                    marked.add((id(node), name))
    return marked


def _own_pads(node: Any) -> list[tuple[float, float, float, float]]:
    """The probe pads a part draws itself (rects on the ``pad`` chip layer), as (cx, cy, w, h) in its frame."""

    pads: list[tuple[float, float, float, float]] = []

    def walk(item: Any) -> None:
        if not isinstance(item, dict):
            return
        if item.get("type") == "rect" and item.get("chip_layer") == "pad":
            pads.append((float(item["cx"]), float(item["cy"]), float(item["w"]), float(item["h"])))
        for child in item.get("children", ()):
            walk(child)

    try:
        walk(node.geometry_2d())
    except (AttributeError, NotImplementedError, TypeError):
        return []
    return pads


def _on_a_pad(port: Any, pads: list[tuple[float, float, float, float]]) -> bool:
    """A probe lands on a pad the part draws: an electrical port there is not a loose end."""

    x, y = float(port.center.x), float(port.center.y)
    return any(abs(x - cx) <= w / 2.0 and abs(y - cy) <= h / 2.0 for cx, cy, w, h in pads)


_BACKGROUND = {"Grid", "Baseplate", "OpticalTable", "Breadboard", "ChipSubstrate", "OpticalPost", "Group"}
_PT = 0.3528                         # millimetres per point


def _label_box(node: Any, font_pt: float) -> tuple[float, float, float, float]:
    """The world box (x0, y0, x1, y1, y up) of a part's label, placed as the SVG renderer places it."""

    from optodraw.core.markup import plain
    from optodraw.layout import estimate_component_bounds
    from optodraw.renderers.labels import label_side, label_spot

    size = 3.0 * font_pt / 8.0
    width = len(plain(node.label)) * size * 0.62
    cx, cy = float(node.world_position.x), float(node.world_position.y)
    if node.component_type in ANNOTATION_TYPES:
        x0 = cx - (width if node.anchor == "end" else 0.0 if node.anchor == "start" else width / 2.0)
        return (x0, cy - size / 2.0, x0 + width, cy + size / 2.0)
    side = label_side(node)
    if side == "top":
        top = float(estimate_component_bounds(node)[3])
        x, baseline, anchor = cx, cy + max(top + 3.0, 8.0), "middle"
    else:
        dx, dy = label_spot(node)
        below = side.startswith("bottom")
        baseline = cy + dy - (size * 0.8 if below else 0.0 if side.startswith("top") else size * 0.35)
        x = cx + dx
        anchor = "end" if side.endswith("left") else "start" if side.endswith("right") else "middle"
    x0 = x - width if anchor == "end" else x if anchor == "start" else x - width / 2.0
    return (x0, baseline - 0.2 * size, x0 + width, baseline + 0.75 * size)


def _gap_to_part(node: Any, box: tuple[float, float, float, float], along: float = 0.0) -> float:
    """How far a world box lies from the part's own drawn box, measured in the part's frame (a turned part's
    world box is far larger than the part). ``along`` moves the drawn box up the part's own y: a flip mirror's
    dashed outline is its drawn box at another place."""

    x0, y0, x1, y1 = _drawn_box(node)
    y0, y1 = y0 + along, y1 + along
    a = -math.radians(float(node.transform.rotation_deg.z))
    c, s = math.cos(a), math.sin(a)
    cx, cy = float(node.world_position.x), float(node.world_position.y)
    corners = [((x - cx) * c - (y - cy) * s, (x - cx) * s + (y - cy) * c) for x in (box[0], box[2]) for y in (box[1], box[3])]
    lx0, lx1 = min(p[0] for p in corners), max(p[0] for p in corners)
    ly0, ly1 = min(p[1] for p in corners), max(p[1] for p in corners)
    return math.hypot(max(x0 - lx1, lx0 - x1, 0.0), max(y0 - ly1, ly0 - y1, 0.0))


def _overlap(a, b) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _hits(p, q, box) -> bool:
    """Does the segment p-q cross the box? (Liang-Barsky clipping.)"""

    (x0, y0), (x1, y1) = p, q
    dx, dy = x1 - x0, y1 - y0
    low, high = 0.0, 1.0
    for edge_p, edge_q in ((-dx, x0 - box[0]), (dx, box[2] - x0), (-dy, y0 - box[1]), (dy, box[3] - y0)):
        if edge_p == 0:
            if edge_q < 0:
                return False
            continue
        t = edge_q / edge_p
        if edge_p < 0:
            low = max(low, t)
        else:
            high = min(high, t)
        if low > high:
            return False
    return True


def _crosses(s, t) -> bool:
    def side(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    (a, b), (c, d) = s, t
    return side(a, b, c) * side(a, b, d) < 0 and side(c, d, a) * side(c, d, b) < 0


def _crossed_by_a_leader(callouts: list[Any], labelled: list[tuple[Any, tuple]], solid: list[Any]) -> list[str]:
    """A leader runs clear of every label but its own and of every part but the one it names."""

    found = []
    for node in callouts:
        line = node.annotation_2d()["children"][0]
        x, y = float(node.world_position.x), float(node.world_position.y)
        start, end = (x + line["x1"], y + line["y1"]), node.target
        for other, box in labelled:
            if other is not node and _hits(start, end, box):
                found.append(f'the leader of "{node.label}" runs through the label "{other.label}": move one')
        for other in solid:
            x0, y0, x1, y1 = other.drawn_box()
            named = x0 <= end[0] <= x1 and y0 <= end[1] <= y1
            if not named and _hits(start, end, (x0, y0, x1, y1)):
                name = getattr(other, "label", "") or other.component_type
                found.append(f'the leader of "{node.label}" runs across {name}: move the text or point it another way')
    return found


def _glyphs_in_the_way(glyphs: list[Any], labelled: list[tuple[Any, tuple]], solid: list[Any]) -> list[str]:
    """A glyph stands clear of every label and every part."""

    found = []
    for node in glyphs:
        points = node.drawn_points()
        box = (min(p[0] for p in points), min(p[1] for p in points), max(p[0] for p in points), max(p[1] for p in points))
        found += [f'a {node.kind} glyph sits on the label "{other.label}": move it along the beam, or use the other side'
                  for other, label_box in labelled if _overlap(box, label_box)]
        found += [f"a {node.kind} glyph sits on {getattr(other, 'label', '') or other.component_type}: move it along the "
                  "beam, or use the other side" for other in solid if _overlap(box, other.drawn_box())]
    return found


def _runs_over(routes: list[Any], segments: list[list], solid: list[Any]) -> list[str]:
    """A route drawn across a part it does not join, on any platform. The part that holds an end (the board under
    a die, the cryostat round a sample) is not run over: the wire reaches its end through it."""

    found = []
    for route, segs in zip(routes, segments):
        ends = [part for part in (route.start_component, route.end_component) if part is not None]
        for node in solid:
            if any(node is end for end in ends):
                continue
            x0, y0, x1, y1 = node.drawn_box()
            inner = (x0 + 0.5, y0 + 0.5, x1 - 0.5, y1 - 0.5)        # touching an edge is not running over
            if (inner[0] < inner[2] and inner[1] < inner[3] and any(_hits(p, q, inner) for p, q in segs)
                    and not any(_holds(node, end) for end in ends)):
                name = getattr(node, "label", "") or node.component_type
                found.append(f"the route {route.start_port}->{route.end_port} runs over {name}: route round it or "
                             "move it")
    return found


def _backwards(routes: list[Any]) -> list[str]:
    """A waveguide that leaves or meets an optical port from behind runs back through the part: it faces away."""

    found = []
    for route in routes:
        points = [(float(p[0]), float(p[1])) for p in route.resolve_points()]
        points = [p for k, p in enumerate(points) if k == 0 or math.dist(p, points[k - 1]) > 1e-9]
        if len(points) < 2:
            continue
        for part, name, leg in ((route.start_component, route.start_port, (points[0], points[1])),
                                (route.end_component, route.end_port, (points[-1], points[-2]))):
            port = part.world_port(name) if part is not None else None
            if port is None or port.kind != "optical":
                continue
            n = port.normal()
            if (leg[1][0] - leg[0][0]) * n.x + (leg[1][1] - leg[0][1]) * n.y < -1e-6:
                label = getattr(part, "label", "") or part.component_type
                found.append(f"the route {route.start_port}->{route.end_port} meets {label}:{name} backwards, "
                             f"through {label}: turn {label} so {name} faces the route")
    return found


def _wires_in_the_air(routes: list[Any]) -> list[str]:
    """A wire that ends at an electrical port the part's 2D art draws more than ``PORT_TOLERANCE`` away."""

    from optodraw.symbols.art import PORT_TOLERANCE, port_gaps

    found = []
    for route in routes:
        for part, port in ((route.start_component, route.start_port), (route.end_component, route.end_port)):
            gap = port_gaps(part).get(str(port), 0.0) if part is not None else 0.0
            if gap > PORT_TOLERANCE:
                name = getattr(part, "label", "") or part.component_type
                found.append(f"the wire to {name}:{port} ends {gap:.1f} units from the port the drawing of {name} "
                             f"shows: the art of {part.component_type} misses its port, so the wire ends in the air")
    return found


def _inset_faults(nodes: list[Any]) -> list[str]:
    """Insets that overlap, marks whose place is hidden, outside their inset or in an inset that left the scene, a
    loaded 3D inset whose marks cannot be tested, and zooms and cuts that join an inset that left the scene. Two insets
    overlap when their axis-aligned world boxes do, so a turned inset can be reported when only the corners of its box
    touch: the check errs on the safe side."""

    from optodraw.figure.inset import LINK_ENDS, Inset

    insets = [n for n in nodes if isinstance(n, Inset)]

    def named(inset: Any) -> str:
        return inset.label or f"inset {insets.index(inset) + 1}" if inset in insets else inset.label or "inset"

    found, blind = [], []
    for inset in insets:
        if not getattr(inset.source, "built", True):        # a record a page file holds with no drawing
            found.append(f'the inset "{named(inset)}" holds a saved {inset.source.record.get("kind")} record and no '
                         "drawing, so it shows an empty box: call rebuild() on it to build it from the record")
    for i, first in enumerate(insets):
        for second in insets[i + 1:]:
            if first.over is second or second.over is first:
                continue                                       # one stands over the other on purpose
            a, b = first.box(), second.box()
            if min(a[2], b[2]) - max(a[0], b[0]) > 1e-9 and min(a[3], b[3]) - max(a[1], b[1]) > 1e-9:
                found.append(f'insets "{named(first)}" and "{named(second)}" overlap')
    for node in nodes:
        for key in LINK_ENDS.get(node.component_type, ()):
            end, word = getattr(node, key), "zoom" if node.component_type == "ZoomLink" else "cut"
            if end is not None and not any(end is inset for inset in insets):
                found.append(f'the {word} joins the inset "{named(end)}", which left the page: add it again or '
                             f"remove the {word}")
        for anchor in getattr(node, "_anchors", lambda: [])():
            mark = getattr(node, "label", "") or node.component_type
            inset = anchor.inset
            if not any(inset is other for other in insets):
                found.append(f'the mark "{mark}" points into the inset "{named(inset)}", which left the page: '
                             "add it again or remove the mark")
                continue
            fragment = inset.fragment()
            wide, tall = fragment.size_mm
            try:
                px, py = fragment.place(*anchor.point, **anchor.options)
                inside = -1e-6 <= px <= wide + 1e-6 and -1e-6 <= py <= tall + 1e-6
            except (ValueError, ArithmeticError):
                inside = False
            if not inside:
                found.append(f'the mark "{mark}" points outside the inset "{named(inset)}": move the place into '
                             "the window")
                continue
            if fragment.covered is None:
                if inset._kind() == "View3D" and inset not in blind:     # a saved drawing keeps no hidden test
                    blind.append(inset)
                    found.append(f'the 3D inset "{named(inset)}" was loaded from a page file, so check_figure cannot '
                                 "tell if the targets of its marks are hidden: call rebuild() on it, or check them "
                                 "by eye")
                continue
            try:
                hidden = bool(fragment.covered(*anchor.point, **anchor.options))
            except (ValueError, ArithmeticError):
                found.append(f'the source of "{named(inset)}" cannot tell if the target of "{mark}" is hidden: '
                             "point at another place")
                continue
            if hidden:
                found.append(f'the target of "{mark}" is hidden in the inset "{named(inset)}": point at a place that '
                             "shows")
    return found


def check_figure(scene: Any, *, preset: str | None = None, view: str = "both") -> list[str]:
    """Return one sentence per fault that makes a figure wrong or hard to read: labels that overlap, sit on a
    beam or a route or another part, float far from their part, run off the frame, read like sentences, or
    end up too small at the preset's width; on a chip, ports nothing connects and routes that cross. ``view``
    is ``"2d"``, ``"1d"`` or ``"both"``. An empty list means these checks passed; look at the figure too."""

    from optodraw.core.beam import Beam, FocusingBeam
    from optodraw.core.routing import Route

    findings: list[str] = []
    font_pt, width_mm = 8.0, None
    if preset is not None:
        from optodraw.publication import paper_figure_preset

        values = paper_figure_preset(preset)
        font_pt, width_mm = float(values.get("font_size_pt", 8.0)), float(values["width"])
    elif callable(getattr(scene, "_render_pt", None)):     # a Page: its labels print at the page's own font_pt
        font_pt = scene._render_pt()
    size = 3.0 * font_pt / 8.0
    if width_mm is not None and getattr(scene, "platform", "") == "on_chip":
        # A chip goes to the page with fit="width": its labels print at the preset's size, so check them at
        # that size in chip units, and never as too small.
        x0, _, x1, _ = scene.content_bounds()
        size = font_pt * _PT * max(x1 - x0, 1e-9) / width_mm
        width_mm = None
    nodes = list(scene.walk())
    parts = [n for n in nodes if not isinstance(n, (Beam, FocusingBeam, Route)) and callable(getattr(n, "ports", None))
             and getattr(n, "component_type", "") not in _BACKGROUND]
    paths = [[(float(x), float(y)) for x, y, *_ in n.resolve_points()] for n in nodes if isinstance(n, (Beam, Route))]
    paths += [[(float(p.x), float(p.y)) for p in n.endpoints()] for n in nodes if isinstance(n, FocusingBeam)]
    paths += [[n.start, n.end] for n in nodes if getattr(n, "component_type", "") in ("DashedLink", "SectionMark")]

    if view in ("2d", "both"):
        labelled = [(n, _label_box(n, font_pt)) for n in parts
                    if getattr(n, "label", "") and n.component_type != "Inset"]       # an inset's label is a name
        solid = [n for n in parts if n.component_type not in ANNOTATION_TYPES]
        half_w, half_h = float(scene.width) / 2.0, float(scene.height) / 2.0
        cx, cy = getattr(scene, "frame_center", (0.0, 0.0))
        if hasattr(scene, "_extent"):                      # a Page: the frame is the page extent that Page.svg uses
            bottom, top = scene._extent(scene._insets())
            half_h, cy = (top - bottom) / 2.0, (top + bottom) / 2.0
            cx = float(scene.width_mm) / 2.0
        for i, (node, box) in enumerate(labelled):
            name = node.label
            if len(name.split()) > 4 and node.component_type not in ANNOTATION_TYPES:
                findings.append(f'label "{name}" has {len(name.split())} words: name the part in 2 to 4, '
                                "and put the rest in the caption")
            if box[0] < cx - half_w or box[2] > cx + half_w or box[1] < cy - half_h or box[3] > cy + half_h:
                findings.append(f'label "{name}" is cut off by the frame: move the part or the label, or fit_frame()')
            gap = _gap_to_part(node, box)
            if gap > 2.5 * size:
                findings.append(f'label "{name}" sits {gap:.1f} units from its part, far from it: '
                                "try another label_side")
            ink = (box[0] + 0.1, box[1] + 0.1, box[2] - 0.1, box[3] - 0.1)
            if any(_hits(p, q, ink) for path in paths for p, q in zip(path, path[1:])):
                findings.append(f'label "{name}" sits on a beam or a route: put it on the side no beam leaves from')
            for other, other_box in labelled[i + 1:]:
                if _overlap(ink, other_box):
                    findings.append(f'labels "{name}" and "{other.label}" overlap')
            for other in solid:
                places = getattr(other, "art_place", tuple)() or (0.0,)
                if other is node:                          # its own label stands beside it, never on where it is not
                    if any(_gap_to_part(node, ink, y) == 0.0 for y in places[1:]):
                        findings.append(f'label "{name}" sits on the dashed outline of its part: try another '
                                        "label_side, or a negative out_offset")
                elif any(_gap_to_part(other, ink, y) == 0.0 for y in places) and not _holds(other, node):
                    findings.append(f'label "{name}" sits on {getattr(other, "label", "") or other.component_type}')
            if width_mm is not None:
                pt = size * (width_mm / float(scene.width)) / _PT
                if pt < 5.0:
                    findings.append(f'label "{name}" prints at {pt:.1f} pt at the {preset} width, too small: '
                                    "build the scene nearer the page size or raise font_size_pt")
                    width_mm = None                               # once is enough: every label shares the size

        findings += _dead_ends([n for n in nodes if isinstance(n, Beam)],
                               [n for n in nodes if isinstance(n, FocusingBeam)],
                               [n for n in nodes if isinstance(n, Route)])
        findings += _off_focus([n for n in nodes if isinstance(n, Beam)])
        findings += _crossed_by_a_leader([n for n in parts if n.component_type == "Callout"], labelled, solid)
        findings += _glyphs_in_the_way([n for n in parts if n.component_type == "Glyph"], labelled, solid)
        findings += _inset_faults(nodes)

        routes = [n for n in nodes if isinstance(n, Route)]
        segments = [[((float(a[0]), float(a[1])), (float(b[0]), float(b[1])))
                     for a, b in zip(r.resolve_points(), r.resolve_points()[1:])] for r in routes]
        if getattr(scene, "platform", "") == "on_chip":
            used = _marked_by_an_arrow(parts)
            for route in routes:
                used.add((id(route.start_component), route.start_port))
                used.add((id(route.end_component), route.end_port))
            for node in parts:
                pads = _own_pads(node)
                # ports the part says may stay open, and ports the figure leaves open on purpose (scene.leave_open)
                spare = set(getattr(node, "open_ports", ())) | set(getattr(node, "left_open", ()))
                loose = [port_name for port_name, port in node.ports().items()
                         if port.kind in ("optical", "electrical") and (id(node), port_name) not in used
                         and port_name not in spare and not (port.kind == "electrical" and _on_a_pad(port, pads))]
                if loose:
                    name = getattr(node, "label", "") or node.component_type
                    kinds = {node.ports()[p].kind for p in loose}
                    ends = [end for kind, end in (("optical", "an optical port on a coupler or a Terminator"),
                                                  ("electrical", "a contact on a pad")) if kind in kinds]
                    findings.append(f"{name}: {', '.join(f'{name}:{p}' for p in loose)} not connected: route each, "
                                    f"or end {' and '.join(ends)}; a figure that leaves them open as its source "
                                    "does says so with scene.leave_open")
            findings += _spread(parts, routes)
            for i in range(len(routes)):
                for j in range(i + 1, len(routes)):
                    if any(_crosses(s, t) for s in segments[i] for t in segments[j]):
                        a, b = routes[i], routes[j]
                        findings.append(f"the route {a.start_port}->{a.end_port} crosses the route "
                                        f"{b.start_port}->{b.end_port}")
        findings += _runs_over(routes, segments, solid)
        findings += _backwards(routes)
        findings += _wires_in_the_air(routes)

    if view in ("1d", "both"):
        findings += [f"1D: {f}" for f in _check_schematic(scene)]
    return findings


def _check_schematic(scene: Any) -> list[str]:
    from optodraw.symbols.schematic import _label_box as box_of, build_schematic, link_path

    schematic = build_schematic(scene)
    paths = [path for path in (link_path(schematic, index) for index in range(len(schematic.links))) if path]
    labelled = [(item, box_of(*item.label_at, item.label)) for item in schematic.items + schematic.marks
                if item.label and getattr(item, "label_at", None)]           # a region's or a bracket's text too
    found = []
    for i, (item, box) in enumerate(labelled):
        near = (box[0] - 1.0, box[1] - 1.0, box[2] + 1.0, box[3] + 1.0)         # the drawn stroke has a width
        if any(_hits(p, q, near) for path in paths for p, q in zip(path, path[1:])):
            found.append(f'label "{item.label}" sits on a beam')
        for other, other_box in labelled[i + 1:]:
            if _overlap(box, other_box):
                found.append(f'labels "{item.label}" and "{other.label}" overlap')
    found += _off_its_2d_path(scene, schematic, link_path)
    found += _across_a_symbol(schematic, [link_path(schematic, index) for index in range(len(schematic.links))])
    return found


SYMBOL_INK = 0.2            # a 1D symbol's box has room round its ink: a link counts as across it inside this inset


def _across_a_symbol(schematic: Any, paths: list[list[tuple[float, float]]]) -> list[str]:
    """A 1D link drawn across a part it does not join: the layout put the part on the beam. A part that holds an
    end of the link in 2D (a cryostat round its sample) is not crossed."""

    def name(item: Any) -> str:
        return item.label or item.component.component_type

    found = []
    for link, path in zip(schematic.links, paths):
        ends = [schematic.items[link.start], schematic.items[link.end]]
        for index, item in enumerate(schematic.items):
            if index in (link.start, link.end) or any(_holds(item.component, end.component) for end in ends):
                continue
            w, h = item.symbol.width, item.symbol.height
            ink = (item.x + SYMBOL_INK * w, item.y + SYMBOL_INK * h, item.x + (1.0 - SYMBOL_INK) * w,
                   item.y + (1.0 - SYMBOL_INK) * h)
            if any(_hits(p, q, ink) for p, q in zip(path, path[1:])):
                kind, fix = ("beam", f"name {name(item)} in the beam") if link.kind == "free_space" else \
                    ("link", "route the link round it")
                found.append(f"the {kind} {name(ends[0])}->{name(ends[1])} runs across {name(item)}: move "
                             f"{name(item)} off it in the 1D, or {fix}")
    return found


def _off_its_2d_path(scene: Any, schematic: Any, link_path: Any) -> list[str]:
    """A 1D route that crosses more links than its 2D route does: it left the path the 2D drawing gives it."""

    from optodraw.core.beam import Beam
    from optodraw.core.routing import Route

    def segments(points):
        return [((float(a[0]), float(a[1])), (float(b[0]), float(b[1]))) for a, b in zip(points, points[1:])]

    def crossings(mine, others):
        return sum(1 for path in others for s in mine for t in path if _crosses(s, t))

    drawn = {index: segments(link_path(schematic, index)) for index in range(len(schematic.links))}
    nodes = [n for n in scene.walk() if isinstance(n, (Beam, Route))]
    flat = [segments(n.resolve_points()) for n in nodes]
    found = []
    for index in schematic.routes:
        link = schematic.links[index]
        ends = {(id(schematic.items[link.start].component), link.start_port),
                (id(schematic.items[link.end].component), link.end_port)}
        twin = next((k for k, n in enumerate(nodes) if isinstance(n, Route) and ends ==
                     {(id(n.start_component), str(n.start_port)), (id(n.end_component), str(n.end_port))}), None)
        if twin is None:
            continue
        in_1d = crossings(drawn[index], [path for other, path in drawn.items() if other != index])
        in_2d = crossings(flat[twin], [path for k, path in enumerate(flat) if k != twin])
        if in_1d > in_2d:
            found.append(f"the route {link.start_port}->{link.end_port} crosses {in_1d} "
                         f"{'link' if in_1d == 1 else 'links'}, {in_2d} in 2D: it does not follow its 2D path")
    return found


# ---------------------------------------------------------------- the print gate: the finished file

COLUMNS_MM = (89, 120, 136, 183)     # the page widths of a journal
PAGE_DEPTH_MM = 247.0
MIN_TEXT_PT, MAX_TEXT_PT = 5.0, 8.0
MIN_SCRIPT_PT = 3.6                  # a subscript prints at 0.72 of the text
MIN_LABEL_SHARE = 0.0165             # the median label over the page width: a quarter of published first figures lie below
PUBLISHED_LABEL_SHARE = 0.022        # the median of those figures
MAX_WORDS_PER_CM2 = 0.5              # published schematics carry 0.20 to 0.45
HAIRLINE_PT = 0.25
MIN_IMAGE_PPI = 300.0
OFF_THE_PAGE_PT = 0.5
TOUCHING_PT = 0.4                    # text boxes may meet by this much: they are estimates
BUSY_SHARE = 0.06                    # a text box with more than this share of its pixels off its main colour lies over art
BUSY_COLOUR = 60                     # how far from the main colour a pixel is off it, summed over red, green and blue
PIXELS_PER_PT = 4

_STYLES = ("font-size", "font-family", "font-weight", "text-anchor", "dominant-baseline", "stroke", "stroke-width",
           "data-art", "data-part", "data-panel", "data-inset")
_NOT_DRAWN = {"defs", "clipPath", "mask", "pattern", "marker", "symbol", "style", "title", "desc", "metadata"}
_STROKED = {"path", "line", "polyline", "polygon", "rect", "circle", "ellipse"}
_GENERIC_FONTS = {"serif", "sans-serif", "monospace", "cursive", "fantasy", "system-ui"}
_PAPER_PT = {"mm": 1.0 / _PT, "cm": 10.0 / _PT, "in": 72.0, "pt": 1.0, "pc": 12.0}
_IDENTITY = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


@dataclass
class _Text:
    words: str
    pt: float                        # the size of the text on paper
    smallest: float                  # the size of its smallest run: a subscript
    family: str
    bold: bool
    box: tuple[float, float, float, float]    # on the page, in points, y down
    level: bool                      # false when it is turned: its box says little then
    panel: str = ""                  # the inset it sits in, "{mm}#{n}", or "" for text on the page


@dataclass
class _Page:
    width_pt: float
    height_pt: float
    texts: list[_Text] = field(default_factory=list)
    strokes: list[float] = field(default_factory=list)                 # each width in points
    images: list[tuple[str, float, str]] = field(default_factory=list)    # each link, printed width in points and kind
    panels: dict[str, float] = field(default_factory=dict)             # each inset's key and its width in points
    marked: bool = False             # an inset mark is in the file: it is a page, and its own text is page text
    zoom_lines: list[tuple[tuple[float, float], tuple[float, float]]] = field(default_factory=list)   # on the page


def _times(m: tuple, n: tuple) -> tuple:
    a, b, c, d, e, f = m
    p, q, r, s, t, u = n
    return (a * p + c * q, b * p + d * q, a * r + c * s, b * r + d * s, a * t + c * u + e, b * t + d * u + f)


def _matrix(text: str | None) -> tuple:
    """The matrix of an SVG ``transform`` attribute."""

    out = _IDENTITY
    for name, values in re.findall(r"(\w+)\s*\(([^)]*)\)", text or ""):
        v = [float(value) for value in re.split(r"[\s,]+", values.strip()) if value]
        if name == "translate":
            step = (1.0, 0.0, 0.0, 1.0, v[0], v[1] if len(v) > 1 else 0.0)
        elif name == "scale":
            step = (v[0], 0.0, 0.0, v[-1], 0.0, 0.0)
        elif name == "rotate":
            c, s = math.cos(math.radians(v[0])), math.sin(math.radians(v[0]))
            step = (c, s, -s, c, 0.0, 0.0)
            if len(v) == 3:
                step = _times(_times((1.0, 0.0, 0.0, 1.0, v[1], v[2]), step), (1.0, 0.0, 0.0, 1.0, -v[1], -v[2]))
        elif name == "matrix":
            step = tuple(v)
        else:
            continue
        out = _times(out, step)
    return out


def _view(width: float, height: float, box: str | None) -> tuple:
    """The matrix that fits a ``viewBox`` into ``width`` by ``height``, centred, as SVG does by default."""

    if not box:
        return _IDENTITY
    x, y, w, h = (float(value) for value in re.split(r"[\s,]+", box.strip()))
    scale = min(width / w, height / h)
    return (scale, 0.0, 0.0, scale, (width - w * scale) / 2.0 - x * scale, (height - h * scale) / 2.0 - y * scale)


def _user_units(value: str | None, default: float = 0.0) -> float:
    from optodraw.figure.fragment import _SVG_UNITS

    found = re.match(r"\s*([-+]?[\d.]+(?:e[-+]?\d+)?)\s*([a-z]*)", value or "")
    return float(found.group(1)) * _SVG_UNITS.get(found.group(2), 1.0) if found else default


def _styles(element: ET.Element, inherited: dict[str, str]) -> dict[str, str]:
    out = dict(inherited)
    out.update({key: element.get(key) for key in _STYLES if element.get(key) is not None})
    for part in (element.get("style") or "").split(";"):
        key, _, value = part.partition(":")
        if key.strip() in _STYLES:
            out[key.strip()] = value.strip()
    return out


def _tag(element: ET.Element) -> str:
    return str(element.tag).rsplit("}", 1)[-1]


def _printed_text(element: ET.Element, matrix: tuple, style: dict[str, str], panel: str = "") -> _Text | None:
    from optodraw.core.markup import text_width

    a, b, c, d, e, f = matrix
    scale = math.sqrt(abs(a * d - b * c))
    lines = [t for t in element if _tag(t) == "tspan" and t.get("x") is not None] or [element]
    words = " ".join("".join(element.itertext()).split())
    if not words:
        return None
    size = _user_units(style.get("font-size"), 16.0)
    runs = [_user_units(_styles(t, style).get("font-size"), size) for t in element.iter() if _tag(t) == "tspan"]
    wide = max(text_width(" ".join("".join(line.itertext()).split()), size) for line in lines)
    start = {"middle": -wide / 2.0, "end": -wide}.get(style.get("text-anchor"), 0.0)
    if style.get("dominant-baseline") == "central":
        top, bottom = -size / 2.0, size / 2.0
    else:
        top, bottom = -0.75 * size, 0.2 * size
    bottom += (len(lines) - 1) * 1.2 * size
    x, y = _user_units((element.get("x") or lines[0].get("x") or "0").split()[0]), _user_units(element.get("y"))
    corners = [(a * (x + u) + c * (y + v) + e, b * (x + u) + d * (y + v) + f)
               for u in (start, start + wide) for v in (top, bottom)]
    family = (style.get("font-family") or "").split(",")[0].strip().strip("'\"")
    return _Text(words, size * scale, min([size, *runs]) * scale, family,
                 style.get("font-weight") in ("bold", "bolder", "600", "700", "800", "900"),
                 (min(p[0] for p in corners), min(p[1] for p in corners),
                  max(p[0] for p in corners), max(p[1] for p in corners)),
                 abs(b) < 1e-6 and abs(c) < 1e-6, panel)


def _read_page(root: ET.Element, name: str) -> _Page:
    """What ``root`` prints, in points on paper: its text, its strokes and its images."""

    sizes = [re.fullmatch(r"\s*([\d.]+)\s*(mm|cm|in|pt|pc)\s*", root.get(key) or "") for key in ("width", "height")]
    if not all(sizes):
        raise ValueError(f"{name} gives no size on paper: write it with export_figure or export_panels, or give its "
                         'root a width and a height in mm')
    width, height = (float(found.group(1)) * _PAPER_PT[found.group(2)] for found in sizes)
    page = _Page(width, height)

    def walk(element: ET.Element, matrix: tuple, style: dict[str, str], panel: str = "") -> None:
        tag = _tag(element)
        if tag in _NOT_DRAWN:
            return
        style = _styles(element, style)
        page.marked = page.marked or element.get("data-inset") is not None
        if element.get("data-panel") is not None:                  # the nearest mark wins for the text inside
            panel = f"{element.get('data-panel')}#{len(page.panels)}"
            page.panels[panel] = _user_units(element.get("data-panel")) / _PT
        matrix = _times(matrix, _matrix(element.get("transform")))
        if tag == "text":
            text = _printed_text(element, matrix, style, panel)
            if text is not None:
                page.texts.append(text)
            return
        scale = math.sqrt(abs(matrix[0] * matrix[3] - matrix[1] * matrix[2]))
        if tag == "image":
            link = element.get("href") or element.get("{http://www.w3.org/1999/xlink}href") or ""
            page.images.append((link, _user_units(element.get("width")) * scale, style.get("data-inset", "unmarked")))
            return
        if tag in _STROKED and style.get("stroke", "none") != "none" and "data-art" not in style:
            page.strokes.append(_user_units(style.get("stroke-width"), 1.0) * scale)
        if tag == "line" and style.get("data-part") == "zoom":
            a, b, c, d, e, f = matrix
            ends = [(float(element.get(f"x{i}", 0)), float(element.get(f"y{i}", 0))) for i in "12"]
            page.zoom_lines.append(tuple((a * x + c * y + e, b * x + d * y + f) for x, y in ends))
        if tag == "svg" and element is not root:
            place = (1.0, 0.0, 0.0, 1.0, _user_units(element.get("x")), _user_units(element.get("y")))
            fit = _view(_user_units(element.get("width")), _user_units(element.get("height")), element.get("viewBox"))
            matrix = _times(_times(matrix, place), fit)
        for child in element:
            walk(child, matrix, style, panel)

    walk(root, _view(width, height, root.get("viewBox")), {})
    return page


def _quoted(texts: list[str], most: int = 8) -> str:
    more = f" and {len(texts) - most} more" if len(texts) > most else ""
    return ", ".join(texts[:most]) + more


def _over_the_drawing(root: ET.Element, page: _Page) -> list[str]:
    """Text that crosses an edge of the art: the file with its text taken out, sampled under each text box."""

    import numpy as np
    from PIL import Image

    from optodraw.raster import svg_to_png

    bare = copy.deepcopy(root)
    for parent in bare.iter():
        for child in list(parent):
            if _tag(child) == "text":
                parent.remove(child)
    drawn = svg_to_png(ET.tostring(bare, encoding="unicode"), width=round(page.width_pt * PIXELS_PER_PT),
                       height=round(page.height_pt * PIXELS_PER_PT), background="white")
    pixels = np.asarray(Image.open(io.BytesIO(drawn)).convert("RGB"), dtype=float)
    busy = []
    for text in page.texts:
        x0, y0, x1, y1 = (max(0, round(value * PIXELS_PER_PT)) for value in text.box)
        under = pixels[y0:y1, x0:x1].reshape(-1, 3)
        if text.level and len(under):
            off = np.abs(under - np.median(under, axis=0)).sum(axis=1) > BUSY_COLOUR
            if off.mean() > BUSY_SHARE:
                busy.append(f'"{text.words}"')
    return [f"text over the drawing: {_quoted(busy)}: move it clear of the art"] if busy else []


def _image_ppi(link: str, printed_pt: float, folder: Path) -> float | None:
    """The resolution an image prints at, or None when it cannot be read."""

    try:
        from PIL import Image

        if link.startswith("data:"):
            source: Any = io.BytesIO(base64.b64decode(link.split(",", 1)[1]))
        else:
            source = folder / link
        with Image.open(source) as image:
            return image.width / (printed_pt / 72.0)
    except (ImportError, OSError, ValueError):
        return None


def check_export(path: str | Path) -> list[str]:
    """Return one sentence per fault of a finished SVG at the size it prints: read after :func:`export_figure` or
    :func:`export_panels`, on the file that goes to the journal. It measures the page against the column widths,
    the text in points, the median label against the width, the fonts, text that overlaps (a panel letter too) or
    leaves the page or crosses the art, the words per square centimetre, hairlines outside the symbols, panel letters
    and image resolution. The limits come from published figures. An empty list means these checks passed; look at
    the figure too."""

    path = Path(path)
    root = ET.parse(path).getroot()
    page = _read_page(root, path.name)
    width_mm, height_mm = page.width_pt * _PT, page.height_pt * _PT
    findings: list[str] = []

    if round(width_mm, 1) not in COLUMNS_MM:
        findings.append(f"the figure is {width_mm:.0f} mm wide, no journal column ({', '.join(map(str, COLUMNS_MM))} mm)")
    if height_mm > PAGE_DEPTH_MM:
        findings.append(f"the figure is {height_mm:.0f} mm tall, over the {PAGE_DEPTH_MM:.0f} mm depth of a page")

    letters = [t for t in page.texts if t.bold and re.fullmatch("[a-z]", t.words)]
    labels = [t for t in page.texts if t not in letters]
    small = [f'"{t.words}" at {t.pt:.1f} pt' for t in labels if t.pt < MIN_TEXT_PT - 0.01]
    if small:
        findings.append(f"text prints below {MIN_TEXT_PT:g} pt: {_quoted(small)}: raise font_size_pt or print it narrower")
    scripts = [f'"{t.words}" at {t.smallest:.1f} pt' for t in labels
               if t.smallest < MIN_SCRIPT_PT - 0.01 and t.pt >= MIN_TEXT_PT - 0.01]
    if scripts:
        findings.append(f"a subscript prints below {MIN_SCRIPT_PT:g} pt: {_quoted(scripts)}")
    large = [f'"{t.words}"' for t in labels if t.pt > MAX_TEXT_PT + 0.01]
    if large:
        findings.append(f"text prints above {MAX_TEXT_PT:g} pt: {_quoted(large)}")
    if page.panels or page.marked:   # page text outside every inset does not count
        groups = {key: [t for t in labels if t.panel == key] for key in page.panels}
    else:                            # a file with no marks is one panel
        groups = {"": labels}
    for key, group in groups.items():
        if not group:
            continue
        panel_pt = page.panels.get(key, page.width_pt)
        median = sorted(t.pt for t in group)[len(group) // 2]
        floor = min(MIN_LABEL_SHARE * panel_pt, MAX_TEXT_PT)
        if median < floor - 1e-6:
            where = f"the {panel_pt * _PT:.0f} mm panel: " if key else ""
            findings.append(f"{where}the median label is {median:.1f} pt, {median / panel_pt:.2%} of the width, "
                            f"below the {floor:.1f} pt floor where published first figures read near "
                            f"{PUBLISHED_LABEL_SHARE:.1%}: print it narrower (120 or 136 mm) with the main parts "
                            "larger")

    families = sorted({t.family for t in page.texts if t.family and t.family not in _GENERIC_FONTS})
    if len(families) > 1:
        findings.append(f"the text uses {len(families)} font families ({', '.join(families)}): use one")

    def inner(t: _Text) -> tuple[float, float, float, float]:
        return t.box[0] + TOUCHING_PT, t.box[1] + TOUCHING_PT, t.box[2] - TOUCHING_PT, t.box[3] - TOUCHING_PT

    level = [t for t in labels if t.level]
    touching = [f'"{p.words}" and "{q.words}"' for i, p in enumerate(level) for q in level[i + 1:]
                if _overlap(inner(p), inner(q))]
    if touching:
        findings.append(f"text overlaps: {_quoted(touching, 6)}")
    on_letters = [f'"{t.words}" on "{p.words}"' for p in letters for t in level if _overlap(inner(t), inner(p))]
    if on_letters:
        findings.append(f"text on a panel letter: {_quoted(on_letters, 6)}: move it clear of the letter")
    off = [f'"{t.words}"' for t in page.texts if t.box[0] < -OFF_THE_PAGE_PT or t.box[1] < -OFF_THE_PAGE_PT
           or t.box[2] > page.width_pt + OFF_THE_PAGE_PT or t.box[3] > page.height_pt + OFF_THE_PAGE_PT]
    if off:
        findings.append(f"text off the page: {_quoted(off)}")
    findings += _over_the_drawing(root, page)
    crossed = [f'"{t.words}"' for t in level if any(_hits(p, q, t.box) for p, q in page.zoom_lines)]
    if crossed:
        findings.append(f"a zoom line runs through {_quoted(crossed)}: move the label, or the panel")

    words = sum(len(re.findall(r"[A-Za-z]{2,}|\d+(?:\.\d+)?", t.words)) for t in labels)
    density = words / (width_mm * height_mm / 100.0)
    if density > MAX_WORDS_PER_CM2:
        findings.append(f"the figure carries {words} words, {density:.2f} per square centimetre, over the 0.20 to 0.45 "
                        "of published schematics: move the explanation to the caption")

    thin = [w for w in page.strokes if 0.0 < w < HAIRLINE_PT - 1e-6]
    if thin:
        findings.append(f"{len(thin)} of {len(page.strokes)} strokes print thinner than {HAIRLINE_PT:g} pt (the thinnest "
                        f"is {min(thin):.2f} pt)")

    marks = [t.words for t in letters]
    if len(marks) > 1 and marks != [chr(97 + i) for i in range(len(marks))]:
        findings.append(f"the panel letters read {', '.join(marks)}: they run a, b, c in the order of the panels")

    for link, printed_pt, kind in page.images:
        ppi = _image_ppi(link, printed_pt, path.parent)
        if ppi is not None and ppi < MIN_IMAGE_PPI:
            findings.append(f"an image ({kind}) prints at {ppi:.0f} ppi, below {MIN_IMAGE_PPI:.0f}: export it larger")
        if kind == "drawn":
            findings.append("a raster has kind drawn: a drawn figure stays vector; mark real data kind=\"measured\"")
    return findings


def figure_rasters(path: str | Path) -> list[tuple[str, float]]:
    """Return the kind and the print resolution in ppi of every raster in a finished SVG, in file order. The kind is
    the ``kind`` of the inset that holds it (``measured``, ``render`` or ``drawn``), or ``unmarked`` outside an inset.
    A raster that cannot be read is left out."""

    path = Path(path)
    page = _read_page(ET.parse(path).getroot(), path.name)
    found = [(kind, _image_ppi(link, printed_pt, path.parent)) for link, printed_pt, kind in page.images]
    return [(kind, ppi) for kind, ppi in found if ppi is not None]
