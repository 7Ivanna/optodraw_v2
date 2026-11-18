"""Port-aware routing primitives.

The routing API borrows the right ideas from PHIDL and gdsfactory:

- ports are first-class
- routing is expressed between ports, not raw points
- steps support relative ``dx``/``dy`` and absolute ``x``/``y`` guidance
- bundle routing sorts ports to reduce crossings
"""

from __future__ import annotations

import logging
import math
from dataclasses import field
from typing import Any, Iterable, Sequence

from optodraw.core.component import Component
from optodraw.core.ports import Port
from optodraw.core.transform import Transform, Vec3, as_vec3 as _as_vec3

logger = logging.getLogger(__name__)


def _route_color(kind: str) -> str:
    return {
        "optical": "#2b6cb0",     # the silicon the parts draw (components.onchip.base.SILICON): a route
        "waveguide": "#2b6cb0",   # reads as the same waveguide as the part it leaves
        "fiber": "#f59e0b",       # amber: the jacket of a patch fibre, as the parts draw their leads
        "electrical": "#b24b4b",
        "free_space": "#e79d1a",
    }.get(kind, "#666666")


# A cable on a bench: one width for every cable, and slate, so it reads as hardware and not as red light.
CABLE_WIDTH = 0.5
CABLE_COLOR = "#475569"


CABLE_CLEAR = 2.0     # a cable keeps this far off a part
CABLE_LEAD = 3.0      # and runs this far straight out of its port before it turns
CABLE_ROOM = 25.0     # its grid reaches this far past the parts


def _on_chip(part) -> bool:
    """A part on a die, as the 3D view judges it: a wire with such an end is chip metal, drawn at its port widths."""

    if getattr(part, "chip_thickness", None) is not None or getattr(part, "component_type", "") == "GDSModel":
        return True
    from optodraw.registry import component_registry

    spec = component_registry().get(getattr(part, "component_type", ""))
    return spec is not None and spec.platform == "on_chip"


def bench_cable(kind: str, start_component, end_component) -> bool:
    """An electrical route between parts of a bench, with no end on a chip: a cable, not chip metal."""

    ends = (start_component, end_component)
    return kind == "electrical" and any(part is not None for part in ends) and not any(map(_on_chip, ends))


def _on_bench(part) -> bool:
    """A part of the bench (an instrument, a laser, a modulator): a cable that reaches one runs round the parts. A wire
    between circuit parts keeps the compact route of a circuit drawing."""

    from optodraw.registry import component_registry

    spec = component_registry().get(getattr(part, "component_type", ""))
    return spec is not None and spec.platform == "free_space"


def _root_of(*components):
    """The scene group that holds the first of ``components`` that is in one."""

    for node in components:
        while node is not None and getattr(node, "_parent", None) is not None:
            node = node._parent
        if node is not None and hasattr(node, "walk"):
            return node
    return None


def _cable_path(start: Port, end: Port, start_component, end_component) -> list[Vec3] | None:
    """A bench cable round every part, as the 1D view routes its wires: it leaves each port square for a lead,
    then the 1D router's A* finds the path with the fewest turns on a grid whose cells inside a part are closed,
    off the tracks of the cables already drawn. None when the parts are in no scene or no path exists."""

    from optodraw.check import _label_box
    from optodraw.core.component import ANNOTATION_TYPES
    from optodraw.symbols.router import _astar, _cells_between, _simplify, _unjog

    root = _root_of(start_component, end_component)
    if root is None:
        return None
    boxes: dict[int, tuple[float, float, float, float]] = {}
    labels = []
    cables = []
    for node in root.walk():
        kind = getattr(node, "component_type", "")
        if isinstance(node, Route):
            if bench_cable(node.kind, node.start_component, node.end_component) and len(node.points) >= 2:
                cables.append([(float(p.x), float(p.y)) for p in node.points])
            continue
        if not kind or kind in _TRANSPARENT_TO_ROUTES or not hasattr(node, "drawn_box"):
            continue
        try:
            x0, y0, x1, y1 = node.drawn_box()
        except Exception:  # pragma: no cover - exotic geometry: not an obstacle
            continue
        if x1 > x0 and y1 > y0:
            boxes[id(node)] = (x0, y0, x1, y1)
        if getattr(node, "label", "") and kind not in ANNOTATION_TYPES:
            labels.append((node, _label_box(node, 8.0)))    # a scene's labels print at 8 pt

    def normal(port: Port) -> tuple[int, int]:
        turn = math.radians(float(port.orientation_deg))
        c, s = math.cos(turn), math.sin(turn)
        return (int(math.copysign(1, c)), 0) if abs(c) >= abs(s) else (0, int(math.copysign(1, s)))

    s, e = (float(start.center.x), float(start.center.y)), (float(end.center.x), float(end.center.y))
    n1, n2 = normal(start), normal(end)
    span = max([abs(v) for box in boxes.values() for v in box] + [abs(v) for v in (*s, *e)] + [1.0])
    pitch = max(1.0, span / 150.0)

    def lead(point, n, own):
        """LEAD out of the port along its facing, and on until it is clear of its own part."""

        x, y = point[0] + n[0] * CABLE_LEAD, point[1] + n[1] * CABLE_LEAD
        box = boxes.get(id(own))
        while box and box[0] - CABLE_CLEAR < x < box[2] + CABLE_CLEAR and box[1] - CABLE_CLEAR < y < box[3] + CABLE_CLEAR:
            x, y = x + n[0] * pitch, y + n[1] * pitch
        return x, y

    a_at, b_at = lead(s, n1, start_component), lead(e, n2, end_component)

    def blocks(owner, box) -> bool:
        """A label is in the way, unless it is the end part's own label on the side its port faces: the cable
        must pass it to reach the port (check_figure asks for the label on another side)."""

        x0, y0, x1, y1 = box
        return not any(owner is part and x0 - CABLE_CLEAR < at[0] < x1 + CABLE_CLEAR and y0 - CABLE_CLEAR < at[1] < y1 + CABLE_CLEAR
                       for part, at in ((start_component, a_at), (end_component, b_at)))

    labels = [box for owner, box in labels if blocks(owner, box)]
    xs = [v for box in boxes.values() for v in (box[0], box[2])] + [s[0], e[0], a_at[0], b_at[0]]
    ys = [v for box in boxes.values() for v in (box[1], box[3])] + [s[1], e[1], a_at[1], b_at[1]]
    origin = (min(xs) - CABLE_ROOM, min(ys) - CABLE_ROOM)
    width = int(math.ceil((max(xs) + CABLE_ROOM - origin[0]) / pitch)) + 2
    height = int(math.ceil((max(ys) + CABLE_ROOM - origin[1]) / pitch)) + 2

    def cell(x: float, y: float) -> tuple[int, int]:
        return int(round((x - origin[0]) / pitch)), int(round((y - origin[1]) / pitch))

    def closing(obstacles) -> bytearray:
        closed = bytearray(width * height)
        for x0, y0, x1, y1 in obstacles:
            lo, hi = cell(x0 - CABLE_CLEAR, y0 - CABLE_CLEAR), cell(x1 + CABLE_CLEAR, y1 + CABLE_CLEAR)
            for cy in range(max(lo[1], 0), min(hi[1], height - 1) + 1):
                closed[cy * width + max(lo[0], 0): cy * width + min(hi[0], width - 1) + 1] = b"\x01" * (
                    min(hi[0], width - 1) + 1 - max(lo[0], 0))
        return closed

    used_h, used_v = bytearray(width * height), bytearray(width * height)
    mine = (s, e)
    for points in cables:                                   # two cables never share a track, unless they share a
        if any(math.dist(end, own) < 1e-6 for end in (points[0], points[-1]) for own in mine):
            continue                                        # port: two wires on one port are one node, as in 1D
        for (x0, y0), (x1, y1) in zip(points, points[1:]):
            a, b = cell(x0, y0), cell(x1, y1)
            horizontal = abs(y1 - y0) < abs(x1 - x0)
            b = (b[0], a[1]) if horizontal else (a[0], b[1])
            used = used_h if horizontal else used_v
            for cx, cy in _cells_between(*a, *b):
                for side in (-1, 0, 1):                     # and keep a free track between them
                    x, y = (cx, cy + side) if horizontal else (cx + side, cy)
                    if 0 <= x < width and 0 <= y < height:
                        used[y * width + x] = 1
    path = _astar(cell(*a_at), cell(*b_at), n1, (-n2[0], -n2[1]), width, height, closing([*boxes.values(), *labels]),
                  used_h, used_v)
    if path is None and labels:                             # over a label beats through an instrument: check_figure
        labels = []                                         # reports the label, and the author moves it
        path = _astar(cell(*a_at), cell(*b_at), n1, (-n2[0], -n2[1]), width, height, closing(boxes.values()),
                      used_h, used_v)
    if path is None:
        return None
    corners = [[origin[0] + cx * pitch, origin[1] + cy * pitch] for cx, cy in path[1:-1]]
    if corners:                                             # the grid's first and last legs onto the leads' lines
        first = 1 if path[1][0] == path[0][0] else 0       # 1: the first leg runs along y, so its corner takes x
        corners[0][1 - first] = a_at[1 - first]
        last = 1 if path[-1][0] == path[-2][0] else 0
        corners[-1][1 - last] = b_at[1 - last]
        inner = _simplify([a_at, *map(tuple, corners), b_at])
    else:                                                   # one straight run: a dogleg takes up the grid's offset
        along = 0 if path[0][1] == path[-1][1] else 1
        mid = (a_at[along] + b_at[along]) / 2.0
        bend = [(mid, a_at[1]), (mid, b_at[1])] if along == 0 else [(a_at[0], mid), (b_at[0], mid)]
        inner = _simplify([a_at, *bend, b_at])

    keep_off = [*boxes.values(), *labels]
    reach = (math.dist(s, a_at) + pitch, math.dist(e, b_at) + pitch)       # the leads and their ends may sit tight

    def clear(run) -> bool:
        """Half the clearance off every part and label, and off every earlier cable's track, past the two leads:
        the grid has no line in a gap narrower than its pitch, and a straight run there beats a jog."""

        margin = CABLE_CLEAR / 2.0
        for (x0, y0), (x1, y1) in zip(run, run[1:]):
            used = used_h if abs(y1 - y0) < abs(x1 - x0) else used_v
            n = max(1, int(math.dist((x0, y0), (x1, y1)) / (pitch / 2.0)))
            for k in range(n + 1):
                x, y = x0 + (x1 - x0) * k / n, y0 + (y1 - y0) * k / n
                if math.dist((x, y), s) < reach[0] or math.dist((x, y), e) < reach[1]:
                    continue
                cx, cy = cell(x, y)
                if 0 <= cx < width and 0 <= cy < height and used[cy * width + cx]:
                    return False
                if any(b[0] - margin < x < b[2] + margin and b[1] - margin < y < b[3] + margin for b in keep_off):
                    return False
        return True

    def square(run) -> bool:
        """Each lead still leaves its port along the port's facing."""

        return all((b[0] - a[0]) * n[0] + (b[1] - a[1]) * n[1] > 0 and abs((b[0] - a[0]) * n[1] - (b[1] - a[1]) * n[0]) < 1e-9
                   for a, b, n in ((run[0], run[1], n1), (run[-1], run[-2], n2)))

    points = _simplify([s, *inner, e])
    for _ in range(4):                                      # a jog of a cell or two reads as a mistake
        better = _unjog(points)
        if better is None or not square(better) or not clear(better):
            break
        points = better
    z = float(start.center.z)
    return [Vec3(x, y, z) for x, y in points]


def _unique_points(points: Sequence[Vec3], tol: float = 1e-9) -> list[Vec3]:
    out: list[Vec3] = []
    for point in points:
        if not out:
            out.append(point)
            continue
        prev = out[-1]
        if (point - prev).length() > tol:
            out.append(point)
    return out


def _no_reversals(points: Sequence[Vec3], keep: Sequence[Vec3] = (), tol: float = 1e-9) -> list[Vec3]:
    """The points without a step back along the line just run: a lead that overshoots a step and then returns.
    A point in ``keep`` (a step the user gave) stays, even where the route then runs back over it."""

    out: list[Vec3] = []
    for point in _unique_points(points, tol):
        while len(out) >= 2 and not any((out[-1] - kept).length() <= tol for kept in keep):
            ab, bc = out[-1] - out[-2], point - out[-1]
            if abs(ab.x * bc.y - ab.y * bc.x) > tol * max(ab.length() * bc.length(), 1.0) or ab.x * bc.x + ab.y * bc.y >= 0.0:
                break
            out.pop()
        if not out or (point - out[-1]).length() > tol:
            out.append(point)
    return out


def _right_angle_corner(port1: Port, port2: Port, tolerance: float = 0.01) -> Vec3 | None:
    """The one corner two ports at a right angle meet at, when it lies in front of both."""

    d1, d2 = port1.outward(1.0) - port1.center, port2.outward(1.0) - port2.center
    if abs(d1.x * d2.x + d1.y * d2.y) > 1e-6:
        return None
    gap = port2.center - port1.center
    along = gap.x * d1.x + gap.y * d1.y
    corner = port1.center + d1 * along
    ahead = (corner - port2.center).x * d2.x + (corner - port2.center).y * d2.y
    return corner if along > tolerance and ahead > tolerance else None


def _resolve_port_ref(ref) -> Port:
    port, _, _ = _resolve_port_endpoint(ref)
    return port


def _resolve_port_endpoint(ref) -> tuple[Port, Component | None, str | None]:
    if isinstance(ref, Port):
        return ref, None, ref.name
    if isinstance(ref, tuple) and len(ref) == 2 and isinstance(ref[0], Component):
        component, port_name = ref
        if not isinstance(port_name, str):
            raise TypeError("Port tuple must use a string port name")
        return component.world_port(port_name), component, port_name
    if isinstance(ref, Component):
        component_ports = ref.world_ports()
        if len(component_ports) != 1:
            raise ValueError(
                f"Component {ref.component_type} has {len(component_ports)} ports; "
                "pass a (component, port_name) tuple instead"
            )
        port_name, port = next(iter(component_ports.items()))
        return port, ref, port_name
    raise TypeError(f"Unsupported port reference: {type(ref)}")


def _component_ref_name(component: Component | None) -> str | None:
    if component is None:
        return None
    component_type = getattr(component, "component_type", component.__class__.__name__)
    label = getattr(component, "label", "")
    if label:
        return f"{component_type}:{label}"
    return component_type


def _sample_quadratic_bezier(start: Vec3, control: Vec3, end: Vec3, samples: int = 8) -> list[Vec3]:
    points: list[Vec3] = []
    for index in range(1, samples + 1):
        t = index / samples
        u = 1.0 - t
        points.append(
            Vec3(
                u * u * start.x + 2.0 * u * t * control.x + t * t * end.x,
                u * u * start.y + 2.0 * u * t * control.y + t * t * end.y,
                u * u * start.z + 2.0 * u * t * control.z + t * t * end.z,
            )
        )
    return points


def _rounded_path_points(points: Sequence[Vec3], bend_radius: float, samples_per_corner: int = 8) -> list[Vec3]:
    if len(points) < 3 or bend_radius <= 0:
        return list(points)

    rounded: list[Vec3] = [points[0]]
    for index in range(1, len(points) - 1):
        prev_point = points[index - 1]
        point = points[index]
        next_point = points[index + 1]

        vec_in = point - prev_point
        vec_out = next_point - point
        len_in = vec_in.length()
        len_out = vec_out.length()
        if len_in <= 1e-9 or len_out <= 1e-9:
            continue

        dir_in = vec_in.normalized()
        dir_out = vec_out.normalized()
        if abs(dir_in.x - dir_out.x) < 1e-9 and abs(dir_in.y - dir_out.y) < 1e-9:
            rounded.append(point)
            continue

        trim = min(bend_radius, len_in / 2.0, len_out / 2.0)
        corner_start = point - dir_in * trim
        corner_end = point + dir_out * trim
        if (corner_start - rounded[-1]).length() > 1e-9:
            rounded.append(corner_start)
        rounded.extend(_sample_quadratic_bezier(corner_start, point, corner_end, samples=samples_per_corner))

    if (points[-1] - rounded[-1]).length() > 1e-9:
        rounded.append(points[-1])
    return _unique_points(rounded)


def _gf_layer_for_kind(kind: str):
    if kind in {"waveguide", "optical"}:
        return "WG"
    return "M1"


def _gf_port_type_for_kind(kind: str) -> str:
    if kind in {"waveguide", "optical", "fiber"}:
        return "optical"
    if kind == "electrical":
        return "electrical"
    return kind


def _ensure_gdsfactory_pdk(gf) -> None:
    try:
        gf.get_active_pdk()
        return
    except Exception:
        pass

    gpdk = getattr(gf, "gpdk", None)
    pdk = getattr(gpdk, "PDK", None)
    activate = getattr(pdk, "activate", None)
    if callable(activate):
        try:
            activate()
            return
        except Exception:
            pass

    try:
        from gdsfactory.gpdk import get_generic_pdk as _get_generic_pdk
    except Exception:
        try:
            from gdsfactory.generic_tech import get_generic_pdk as _get_generic_pdk
        except ImportError:
            return

    try:
        _get_generic_pdk().activate()
    except Exception:
        pass


def _route_with_gdsfactory(
    port1: Port,
    port2: Port,
    *,
    kind: str,
    width: float,
    bend_radius: float,
    start_straight_length: float,
    end_straight_length: float,
    steps: Sequence[dict[str, float]] | None,
) -> tuple[list[Vec3], float]:
    try:
        import gdsfactory as gf
    except ImportError as exc:
        raise RuntimeError("gdsfactory is not installed") from exc

    component = gf.Component()
    _ensure_gdsfactory_pdk(gf)
    layer = gf.get_layer(_gf_layer_for_kind(kind))
    port_type = _gf_port_type_for_kind(kind)
    gf_port1 = component.add_port(
        "p1",
        center=(port1.center.x, port1.center.y),
        width=port1.width,
        orientation=port1.orientation_deg,
        layer=layer,
        port_type=port_type,
    )
    gf_port2 = component.add_port(
        "p2",
        center=(port2.center.x, port2.center.y),
        width=port2.width,
        orientation=port2.orientation_deg,
        layer=layer,
        port_type=port_type,
    )

    # A 90 degree bend eats `radius` in BOTH axes, and a Manhattan link needs
    # two of them, so a radius wider than half the shorter offset does not fit
    # between the ports. gdsfactory does not refuse: it loops around and comes
    # back, which is where "the waveguides are too long" came from. Ports 30 um
    # apart in x and 10 in y with the default 10 um radius drew a 120 um route
    # that dived 20 um below both ports; capped to 5 um it draws the 40 um path.
    dx = abs(port2.center.x - port1.center.x)
    dy = abs(port2.center.y - port1.center.y)
    span = min(dx, dy) if min(dx, dy) > 1e-9 else max(dx, dy)
    fitted_radius = max(min(bend_radius, span / 2.0), 0.0) or bend_radius

    route = gf.routing.route_single(
        component,
        gf_port1,
        gf_port2,
        cross_section="strip",
        start_straight_length=start_straight_length,
        end_straight_length=end_straight_length,
        steps=steps,
        radius=fitted_radius,
        route_width=width,
        allow_width_mismatch=True,
        auto_taper=False,
    )

    dbu = component.kcl.dbu
    backbone = route.backbone
    if backbone and hasattr(backbone[0], "x") and hasattr(backbone[0], "y"):
        points = [Vec3(point.x * dbu, point.y * dbu, 0.0) for point in backbone]
    else:
        points = [Vec3(backbone[index] * dbu, backbone[index + 1] * dbu, 0.0) for index in range(0, len(backbone), 2)]
    actual_radius = float(route.bend90_radius) * dbu if getattr(route, "bend90_radius", None) is not None else fitted_radius
    return points, actual_radius


def _should_use_gdsfactory_backend(kind: str, path_type: str, steps: Sequence[dict[str, float]] | None, backend: str) -> bool:
    if kind not in {"waveguide", "optical"}:
        return False
    if backend == "local":
        return False
    if backend == "gdsfactory":
        return True
    # "auto" is the default for route_ports: use gdsfactory where it is the
    # better router, which is its own speciality, the Manhattan path. Deleting
    # these lines made "auto" mean "never".
    #
    # "smooth", "L" and "manual" are excluded because each states an intent the
    # Manhattan router cannot carry out. "smooth" is the one that bit: it was
    # silently routed to right angles, drawing a path 3.3x the direct distance
    # where the local router draws a spline at 1.3x.
    if path_type in {"manual", "L", "smooth"}:
        return False
    return steps is None


def _apply_steps(start: Vec3, steps: Sequence[dict[str, float]]) -> list[Vec3]:
    current = start
    points = [current]
    for step in steps:
        x = current.x + step.get("dx", 0.0)
        y = current.y + step.get("dy", 0.0)
        z = current.z + step.get("dz", 0.0)
        if "x" in step:
            x = step["x"]
        if "y" in step:
            y = step["y"]
        if "z" in step:
            z = step["z"]
        current = Vec3(x, y, z)
        points.append(current)
    return points


def _is_horizontal(port: Port) -> bool:
    normal = port.normal()
    return abs(normal.x) >= abs(normal.y)


def _ports_face_each_other(port1: Port, port2: Port) -> bool:
    """True when each port's outward direction points toward the other — the only
    case a direct S-bend handles cleanly. For U-turns, same-facing or perpendicular
    ports it returns False so smooth routing falls back to (rounded) manhattan."""

    n1 = port1.normal()
    n2 = port2.normal()
    to2 = port2.center - port1.center
    to1 = port1.center - port2.center
    return (n1.x * to2.x + n1.y * to2.y) > 1e-9 and (n2.x * to1.x + n2.y * to1.y) > 1e-9


def _sbend_axis(port1: Port, port2: Port) -> bool | None:
    """The axis a direct S-bend should sweep, or ``None`` when one will not do.

    Two conditions. The ports must face each other roughly head on, because a
    cosine S-bend leaves and enters along one axis and cannot turn a corner. And
    the axis is taken from the line BETWEEN the ports, not from each port's own
    quadrant.

    Judging the axis per port, as this used to, splits an array of identical
    ports in half. The AWGR channel apertures sit on an arc running from -143 to
    -127 degrees; the 45 degree boundary between "horizontal" and "vertical"
    falls in the middle of it, so two of the four arms took the S-bend and the
    other two fell through to the Manhattan backbone and arrived at the same
    device through a square corner.
    """

    n1, n2 = port1.normal(), port2.normal()
    head_on = -(n1.x * n2.x + n1.y * n2.y)          # 1.0 when exactly opposed
    if head_on < math.cos(math.radians(60.0)):
        return None
    delta = port2.center - port1.center
    return abs(delta.x) >= abs(delta.y)


def _orthogonalize(points: Sequence[Vec3], *, horizontal_first: bool, tol: float = 1e-6) -> list[Vec3]:
    """Insert an L-corner between any non-axis-aligned consecutive points so every
    segment runs purely horizontally or vertically (Manhattan).

    ``horizontal_first`` picks the corner side for the first segment, then the
    direction alternates so a run of loosely-placed waypoints zig-zags cleanly
    rather than all bending the same way.
    """

    pts = list(points)
    if len(pts) < 2:
        return pts
    result = [pts[0]]
    horizontal = horizontal_first
    for nxt in pts[1:]:
        cur = result[-1]
        if abs(nxt.x - cur.x) > tol and abs(nxt.y - cur.y) > tol:
            corner = Vec3(nxt.x, cur.y, cur.z) if horizontal else Vec3(cur.x, nxt.y, cur.z)
            result.append(corner)
            horizontal = not horizontal
        result.append(nxt)
    return result


def _sbend_points(a: Vec3, b: Vec3, horizontal: bool, steps: int = 28) -> list[Vec3]:
    """Interior points of a cosine S-bend from ``a`` to ``b`` that leaves and enters
    along the port axis (zero slope at both ends) — a smooth, direct connector."""

    pts: list[Vec3] = []
    for index in range(1, steps):
        t = index / steps
        blend = 0.5 - 0.5 * math.cos(math.pi * t)
        if horizontal:
            pts.append(Vec3(a.x + (b.x - a.x) * t, a.y + (b.y - a.y) * blend, a.z))
        else:
            pts.append(Vec3(a.x + (b.x - a.x) * blend, a.y + (b.y - a.y) * t, a.z))
    return pts


def _on_axis(port: Port, horizontal: bool) -> bool:
    """True when ``port`` faces along the S-bend's axis, within a degree."""

    n = port.normal()
    return abs(n.y if horizontal else n.x) < math.sin(math.radians(1.0))


def _dubins_points(a: Vec3, heading_a: Vec3, b: Vec3, heading_b: Vec3, radius: float) -> list[Vec3]:
    """Interior points of the shortest arc, straight, arc path (Dubins CSC) from ``a`` moving along ``heading_a`` to
    ``b`` moving along ``heading_b``, both arcs of ``radius``: a route that keeps its bend radius whatever angle its
    ports face. Empty when no such path exists."""

    def left(v):
        return -v[1], v[0]

    def sweep(c, p, q, turn):                       # angle from p to q round c: counter-clockwise for turn +1
        a0, a1 = math.atan2(p[1] - c[1], p[0] - c[0]), math.atan2(q[1] - c[1], q[0] - c[0])
        s = (a1 - a0) % math.tau if turn > 0 else -((a0 - a1) % math.tau)
        return a0, 0.0 if abs(s) > math.tau - 1e-9 else s

    def arc(c, a0, s, first):                         # the arc's samples, 4 degrees apart, with or without its start
        n = max(1, math.ceil(abs(s) / math.radians(4.0)))
        ks = range(1, n + 1) if not first else range(0, n)
        return [(c[0] + radius * math.cos(a0 + s * k / n), c[1] + radius * math.sin(a0 + s * k / n)) for k in ks]

    ha, hb = (heading_a.x, heading_a.y), (heading_b.x, heading_b.y)
    best: tuple[float, list[tuple[float, float]]] | None = None
    for turn_a, turn_b in ((1, 1), (-1, -1), (1, -1), (-1, 1)):          # LSL, RSR, LSR, RSL
        ca = (a.x + turn_a * radius * left(ha)[0], a.y + turn_a * radius * left(ha)[1])
        cb = (b.x + turn_b * radius * left(hb)[0], b.y + turn_b * radius * left(hb)[1])
        dx, dy = cb[0] - ca[0], cb[1] - ca[1]
        d = math.hypot(dx, dy)
        if d < 1e-9 or (turn_a != turn_b and d < 2.0 * radius):
            continue
        beta = 0.0 if turn_a == turn_b else turn_a * math.asin(2.0 * radius / d)
        u = ((dx * math.cos(beta) - dy * math.sin(beta)) / d, (dx * math.sin(beta) + dy * math.cos(beta)) / d)
        ta = (ca[0] - turn_a * radius * left(u)[0], ca[1] - turn_a * radius * left(u)[1])
        tb = (cb[0] - turn_b * radius * left(u)[0], cb[1] - turn_b * radius * left(u)[1])
        a0, sa = sweep(ca, (a.x, a.y), ta, turn_a)
        b0, sb = sweep(cb, tb, (b.x, b.y), turn_b)
        length = radius * (abs(sa) + abs(sb)) + math.dist(ta, tb)
        if best is None or length < best[0]:
            best = (length, arc(ca, a0, sa, first=False) + arc(cb, b0, sb, first=True))
    return [] if best is None else [Vec3(x, y, a.z) for x, y in best[1]]


def _fitted_dubins(a: Vec3, heading_a: Vec3, b: Vec3, heading_b: Vec3, radius: float) -> list[Vec3]:
    """The Dubins path at ``radius``, or at the largest of its halvings that does not loop (twice the chord at
    most): ports closer than the radius allows turn tighter, as a Manhattan route fits its radius to the gap."""

    chord = (b - a).length()
    r = radius
    while True:
        points = _dubins_points(a, heading_a, b, heading_b, r)
        path = [a, *points, b]
        if sum((q - p).length() for p, q in zip(path, path[1:])) <= 2.0 * chord or r <= radius / 16.0:
            return points
        r /= 2.0


def _port_hull_box(component, margin: float = 2.5) -> tuple[float, float, float, float] | None:
    """A keep-out box for a routed endpoint device: its world-port hull, padded.

    Routes must not run OVER the device they connect to — the port hull marks
    the guided extent of every on-chip device (bus tips, drop ports, arms)."""

    try:
        ports = component.world_ports()
    except Exception:
        return None
    xs = [float(p.center.x) for p in ports.values()]
    ys = [float(p.center.y) for p in ports.values()]
    if not xs:
        return None
    x0, x1 = min(xs) - margin, max(xs) + margin
    y0, y1 = min(ys) - margin, max(ys) + margin
    if x1 - x0 < 8.0:  # thin devices still occupy real width
        cx = (x0 + x1) / 2.0
        x0, x1 = cx - 4.0, cx + 4.0
    if y1 - y0 < 8.0:
        cy = (y0 + y1) / 2.0
        y0, y1 = cy - 4.0, cy + 4.0
    return (x0, y0, x1, y1)


def _leg_crosses_box(a, b, box) -> bool:
    x0, y0, x1, y1 = box
    if abs(a[1] - b[1]) < 1e-9:  # horizontal leg
        if not (y0 < a[1] < y1):
            return False
        return max(a[0], b[0]) > x0 and min(a[0], b[0]) < x1
    if abs(a[0] - b[0]) < 1e-9:  # vertical leg
        if not (x0 < a[0] < x1):
            return False
        return max(a[1], b[1]) > y0 and min(a[1], b[1]) < y1
    return False


def _manhattanize(points: list[Vec3], tol: float = 1e-6) -> list[Vec3]:
    """Split any diagonal leg into two axis-aligned legs.

    Sliding a corner clear of a device body can leave its neighbour off-axis, and
    a manhattan waveguide that cuts a diagonal across a chip is simply wrong. The
    elbow continues the direction the route was already travelling, so the fix
    reads as one turn rather than a zigzag."""

    if len(points) < 2:
        return points
    fixed = [points[0]]
    horizontal_run = True
    for previous, current in zip(points, points[1:]):
        dx, dy = float(current.x) - float(previous.x), float(current.y) - float(previous.y)
        if abs(dx) > tol and abs(dy) > tol:
            elbow = Vec3(current.x, previous.y, previous.z) if horizontal_run else Vec3(previous.x, current.y, previous.z)
            fixed.append(elbow)
            horizontal_run = not horizontal_run
        elif abs(dx) > tol:
            horizontal_run = True
        elif abs(dy) > tol:
            horizontal_run = False
        fixed.append(current)
    return fixed


def _nudge_backbone_clear(points: list[Vec3], boxes: list, margin: float = 2.0) -> list[Vec3]:
    """Push manhattan legs out of the endpoint devices' keep-out boxes.

    Interior legs shift sideways to the nearer box edge. A leg pinned to a port
    (first/last) cannot change its lateral coordinate — instead its interior
    CORNER slides along the leg until the crossing happens outside the box, so
    the route descends to port height clear of the device body."""

    if len(points) < 3 or not boxes:
        return points
    pts = [[float(p.x), float(p.y), float(getattr(p, "z", 0.0))] for p in points]
    last = len(pts) - 1

    def slide_corner(index: int, terminal: int, box, horizontal: bool) -> bool:
        x0, y0, x1, y1 = box
        corner = pts[index]
        buddy = pts[index - 1] if index > 0 and terminal > index else pts[index + 1] if index < last else None
        if horizontal:
            new = (x0 - margin) if pts[terminal][0] < x0 else (x1 + margin) if pts[terminal][0] > x1 else None
            if new is None:
                return False
            corner[0] = new
            if buddy is not None and abs(buddy[0] - corner[0]) > 1e-9 and abs(buddy[1] - corner[1]) > 1e-9:
                pass  # buddy no longer axis-aligned; leave (rounded later)
            elif buddy is not None:
                buddy[0] = new if abs(buddy[1] - corner[1]) > 1e-9 else buddy[0]
        else:
            new = (y0 - margin) if pts[terminal][1] < y0 else (y1 + margin) if pts[terminal][1] > y1 else None
            if new is None:
                return False
            corner[1] = new
        return True

    for _ in range(4):
        moved = False
        for i in range(len(pts) - 1):
            a, b = pts[i], pts[i + 1]
            for box in boxes:
                if not _leg_crosses_box(a, b, box):
                    continue
                x0, y0, x1, y1 = box
                horizontal = abs(a[1] - b[1]) < 1e-9
                start_fixed = i == 0
                end_fixed = i + 1 == last
                if not start_fixed and not end_fixed:
                    if horizontal:
                        y = a[1]
                        a[1] = b[1] = (y0 - margin) if (y - y0) < (y1 - y) else (y1 + margin)
                        # rejoin verticals/diagonals must come down OUTSIDE the box
                        if x0 < a[0] < x1:
                            a[0] = (x1 + margin) if pts[i - 1][0] >= (x0 + x1) / 2 else (x0 - margin)
                        if x0 < b[0] < x1:
                            b[0] = (x1 + margin) if pts[i + 2][0] >= (x0 + x1) / 2 else (x0 - margin)
                    else:
                        x = a[0]
                        a[0] = b[0] = (x0 - margin) if (x - x0) < (x1 - x) else (x1 + margin)
                        if y0 < a[1] < y1:
                            a[1] = (y1 + margin) if pts[i - 1][1] >= (y0 + y1) / 2 else (y0 - margin)
                        if y0 < b[1] < y1:
                            b[1] = (y1 + margin) if pts[i + 2][1] >= (y0 + y1) / 2 else (y0 - margin)
                    moved = True
                elif end_fixed and not start_fixed:
                    # slide the interior corner (a) toward the terminal, past the box
                    if horizontal:
                        new = (x0 - margin) if b[0] < x0 else (x1 + margin) if b[0] > x1 else None
                        if new is not None and abs(a[0] - new) > 1e-9:
                            if i >= 1 and abs(pts[i - 1][0] - a[0]) < 1e-9:
                                pts[i - 1][0] = new  # keep the feeding vertical leg aligned
                            a[0] = new
                            moved = True
                    else:
                        new = (y0 - margin) if b[1] < y0 else (y1 + margin) if b[1] > y1 else None
                        if new is not None and abs(a[1] - new) > 1e-9:
                            if i >= 1 and abs(pts[i - 1][1] - a[1]) < 1e-9:
                                pts[i - 1][1] = new
                            a[1] = new
                            moved = True
                elif start_fixed and not end_fixed:
                    if horizontal:
                        new = (x0 - margin) if a[0] < x0 else (x1 + margin) if a[0] > x1 else None
                        if new is not None and abs(b[0] - new) > 1e-9:
                            if i + 2 <= last and abs(pts[i + 2][0] - b[0]) < 1e-9:
                                pts[i + 2][0] = new
                            b[0] = new
                            moved = True
                    else:
                        new = (y0 - margin) if a[1] < y0 else (y1 + margin) if a[1] > y1 else None
                        if new is not None and abs(b[1] - new) > 1e-9:
                            if i + 2 <= last and abs(pts[i + 2][1] - b[1]) < 1e-9:
                                pts[i + 2][1] = new
                            b[1] = new
                            moved = True
        if not moved:
            break
    return [Vec3(p[0], p[1], p[2]) for p in pts]



# Structural furniture a link is expected to run over, plus everything that is
# not a solid part in the first place.
_TRANSPARENT_TO_ROUTES = frozenset({
    "Route", "WaveguideRoute", "FiberRoute", "MetalRoute", "Beam", "FocusingBeam",
    "Group", "Grid", "OpticalTable", "Breadboard", "Baseplate", "ChipSubstrate",
    "OpticalPost", "PlatformMount",
})


def _obstacle_boxes(start_component, end_component, margin: float = 3.0) -> list[tuple[float, float, float, float]]:
    """Keep-out boxes for the OTHER parts sharing the scene.

    A link should go around what it passes, not through it. The two components
    being joined are excluded — the route has to reach their ports — as is
    anything a route legitimately runs over, like a table or a die."""

    root = None
    for component in (start_component, end_component):
        node = component
        while node is not None and getattr(node, "_parent", None) is not None:
            node = node._parent
        if node is not None:
            root = node
            break
    if root is None or not hasattr(root, "walk"):
        return []
    from optodraw.layout import estimate_component_size
    from optodraw.layout._cache import _component_state

    nodes = []
    states = []
    contexts = {}
    for node in root.walk():
        kind = getattr(node, "component_type", "")
        if not kind or kind in _TRANSPARENT_TO_ROUTES:
            continue
        nodes.append(node)
        states.append((id(node), _component_state(node, contexts)))
    signature = tuple(states) if all(state is not None for _, state in states) else None
    cached = getattr(root, "_routing_obstacle_cache", None)
    if signature is not None and cached is not None and cached[0] == signature:
        entries = cached[1]
    else:
        entries = []
        cacheable = signature is not None
        for node in nodes:
            try:
                width, height = estimate_component_size(node)
                position = node.world_position
            except Exception:  # pragma: no cover - exotic geometry: not an obstacle
                cacheable = False
                continue
            if width <= 0 or height <= 0:
                continue
            cx, cy = float(position.x), float(position.y)
            entries.append((id(node), (cx - width / 2.0, cy - height / 2.0,
                                      cx + width / 2.0, cy + height / 2.0)))
        root._routing_obstacle_cache = (signature, entries) if cacheable else None

    skip = {id(start_component), id(end_component)}
    return [(left - margin, bottom - margin, right + margin, top + margin)
            for identity, (left, bottom, right, top) in entries if identity not in skip]


def _detour_around_boxes(backbone, boxes, margin: float = 3.0, max_ratio: float = 2.0):
    """Step a blocked link over (or under) what is in its way.

    Deliberately simple: find what the straight run hits, try passing each side
    of it, and take the shorter. It is the move a person makes with a KiCad-style
    drag, not a maze solver -- so if neither side is worth it (the detour would be
    longer than ``max_ratio`` times the direct run) the route is left alone rather
    than made worse."""

    if len(backbone) < 2 or not boxes:
        return backbone
    start, end = backbone[0], backbone[-1]
    hit = [box for box in boxes if _backbone_crosses_boxes([start, end], [box], clear_of_ends=0.0)]
    if not hit:
        return backbone
    x0 = min(box[0] for box in hit)
    y0 = min(box[1] for box in hit)
    x1 = max(box[2] for box in hit)
    y1 = max(box[3] for box in hit)
    horizontal = abs(float(end.x) - float(start.x)) >= abs(float(end.y) - float(start.y))

    def candidate(lane: float) -> list[Vec3]:
        if horizontal:
            return [start, Vec3(x0 - margin, start.y, start.z), Vec3(x0 - margin, lane, start.z),
                    Vec3(x1 + margin, lane, start.z), Vec3(x1 + margin, end.y, end.z), end]
        return [start, Vec3(start.x, y0 - margin, start.z), Vec3(lane, y0 - margin, start.z),
                Vec3(lane, y1 + margin, start.z), Vec3(end.x, y1 + margin, end.z), end]

    lanes = (y1 + margin, y0 - margin) if horizontal else (x1 + margin, x0 - margin)
    options = sorted((_polyline_length_um(candidate(lane)), lane) for lane in lanes)
    direct = _polyline_length_um([start, end])
    best_length, best_lane = options[0]
    if direct > 0 and best_length > direct * max_ratio:
        return backbone  # going around costs more than it is worth
    return candidate(best_lane)


def _backbone_crosses_boxes(backbone, boxes, clear_of_ends: float = 8.0) -> bool:
    """Sampled check: does any part of the backbone (away from its own port
    stubs) run through an endpoint device's keep-out box?"""

    if not boxes or len(backbone) < 2:
        return False
    sx, sy = float(backbone[0].x), float(backbone[0].y)
    ex, ey = float(backbone[-1].x), float(backbone[-1].y)
    for i in range(len(backbone) - 1):
        ax, ay = float(backbone[i].x), float(backbone[i].y)
        bx, by = float(backbone[i + 1].x), float(backbone[i + 1].y)
        steps = max(int(math.dist((ax, ay), (bx, by)) / 3.0), 1)
        for k in range(steps + 1):
            t = k / steps
            x, y = ax + (bx - ax) * t, ay + (by - ay) * t
            if math.dist((x, y), (sx, sy)) <= clear_of_ends or math.dist((x, y), (ex, ey)) <= clear_of_ends:
                continue
            for (x0, y0, x1, y1) in boxes:
                if x0 < x < x1 and y0 < y < y1:
                    return True
    return False


# Ports whose FACES still overlap are not offset from each other in any way the
# route can express: a bend radius of several microns cannot draw a 0.4 um step,
# and asking it to produces a full loop. Treat such a pair as collinear.
_COLLINEAR_TOL_MAX = 1.0


def _snap_near_collinear(start: Port, end: Port, tolerance: float | None = None) -> Port:
    """Pull ``end`` onto the start's axis when the two port faces still overlap.

    ``tolerance`` caps the snap distance. ``None`` uses the legacy
    ``min(width, 1.0)`` overlap rule; ``0`` disables snapping so a deliberate
    sub-micron jog stays visible in the schematic.
    """

    import dataclasses

    horizontal = _is_horizontal(start)
    if _is_horizontal(end) != horizontal:
        return end  # perpendicular ports genuinely need a corner
    offset = (end.center.y - start.center.y) if horizontal else (end.center.x - start.center.x)
    if tolerance is None:
        tolerance = min(float(start.width), float(end.width), _COLLINEAR_TOL_MAX)
    if tolerance <= 0.0 or not 0.0 < abs(offset) <= tolerance:
        return end
    center = Vec3(end.center.x, start.center.y, end.center.z) if horizontal else Vec3(start.center.x, end.center.y, end.center.z)
    return dataclasses.replace(end, center=center)


def _facing_in_line(port1: Port, port2: Port, tolerance: float = 0.01) -> bool:
    """The two ports look at each other along one line, the second in front of the first."""

    d1, d2 = port1.outward(1.0) - port1.center, port2.outward(1.0) - port2.center
    gap = port2.center - port1.center
    along = gap.x * d1.x + gap.y * d1.y
    lateral = abs(gap.x * d1.y - gap.y * d1.x)
    return along > tolerance and lateral <= tolerance and d1.x * d2.x + d1.y * d2.y < -1.0 + 1e-6


def _ahead(port: Port, point: Vec3) -> float:
    """How far ``point`` lies in front of ``port``, along its outward normal."""

    n = port.normal()
    return (point.x - port.center.x) * n.x + (point.y - port.center.y) * n.y


def _leads_pass(port1: Port, port2: Port, start_exit: Vec3, end_entry: Vec3) -> bool:
    """The two lead stubs pass each other, so a direct join between their ends runs back along one, while a join
    between the port centres leaves and enters each port face-on."""

    passed = (_ahead(port1, end_entry) < _ahead(port1, start_exit) - 1e-6
              or _ahead(port2, start_exit) < _ahead(port2, end_entry) - 1e-6)
    return passed and _ports_face_each_other(port1, port2)


def _build_route_backbone(
    port1: Port,
    port2: Port,
    path_type: str,
    start_straight_length: float,
    end_straight_length: float,
    steps: Sequence[dict[str, float]] | None,
    bend_radius: float = 10.0,
) -> list[Vec3]:
    if not steps and path_type != "manual" and _facing_in_line(port1, port2):
        return [port1.center, port2.center]     # one straight run: lead stubs longer than the gap would double back
    start_exit = port1.outward(start_straight_length) if start_straight_length > 0 else port1.center
    # Approach the destination from IN FRONT of it (along its outward axis) so the
    # route enters the port face-on, not by overshooting and backing in from behind.
    end_entry = port2.outward(end_straight_length) if end_straight_length > 0 else port2.center

    if path_type in {"straight", "all_angle", "dubins"}:
        if steps:
            guided = _apply_steps(start_exit, steps)
            return _unique_points([port1.center, start_exit, *guided, end_entry, port2.center])
        if _leads_pass(port1, port2, start_exit, end_entry):
            start_exit, end_entry = port1.center, port2.center
        return _unique_points([port1.center, start_exit, end_entry, port2.center])

    if path_type == "manual":
        if not steps:
            raise ValueError("manual routing requires a non-empty steps sequence")
        guided = _apply_steps(start_exit, steps)
        return _unique_points([port1.center, *guided, end_entry, port2.center])

    if steps:
        guided = _apply_steps(start_exit, steps)
        # Waypoint routing: the user-clicked points are the path. For every type
        # except 'manual' (exact points), insert L-corners so each segment runs
        # purely left/right or up/down instead of cutting diagonally across devices.
        chain = _orthogonalize([*guided, end_entry], horizontal_first=_is_horizontal(port1))
        return _no_reversals([port1.center, *chain, port2.center], keep=guided[1:])

    if path_type == "smooth" and _ports_face_each_other(port1, port2):
        # a direct cosine S-bend ONLY when the ports genuinely face each other,
        # head on; any other topology falls through to manhattan (rounded by smooth)
        axis = _sbend_axis(port1, port2)
        if axis is not None:
            if _leads_pass(port1, port2, start_exit, end_entry):
                start_exit, end_entry = port1.center, port2.center
            if _on_axis(port1, axis) and _on_axis(port2, axis):
                bend = _sbend_points(start_exit, end_entry, axis)
            else:                   # a port off the axis (an AWG aperture on its arc): leave and enter along each port
                bend = _fitted_dubins(start_exit, port1.normal(), end_entry, port2.normal() * -1.0, bend_radius)
            return _unique_points([port1.center, start_exit, *bend, end_entry, port2.center])

    # NOTE: every return below this line is a POLYGONAL backbone; route_ports
    # decides rounding via _backbone_is_curved (dense S-bend samples vs corners).

    corner = _right_angle_corner(port1, port2)
    if corner is not None:          # one bend (L or manhattan): lead stubs past the corner would step back and jog
        return [port1.center, corner, port2.center]

    # Two bends and a lane between them: the L's lane is its end lead (while its corner lies in front of the end
    # port), the manhattan's lies halfway. A lane behind a port it crosses runs the route back along that port's
    # lead, so take the first lane in front of each of them.
    horizontal = _is_horizontal(port1)

    def along(point: Vec3) -> float:
        return point.x if horizontal else point.y

    def on_lane(point: Vec3, lane: float) -> Vec3:
        return Vec3(lane, point.y, point.z) if horizontal else Vec3(point.x, lane, point.z)

    halfway = (along(start_exit) + along(end_entry)) / 2.0
    crossed = [(port, lead) for port, lead in ((port1, start_exit), (port2, end_entry)) if _is_horizontal(port) == horizontal]
    l_corner = on_lane(start_exit, along(end_entry))
    preferred = along(end_entry) if path_type == "L" and _ahead(port2, l_corner) > 1e-9 else halfway
    candidates = [preferred, halfway, (along(port1.center) + along(port2.center)) / 2.0, *(along(lead) for _, lead in crossed)]
    lane = next((c for c in candidates if all(_ahead(port, on_lane(port.center, c)) > 1e-9 for port, _ in crossed)), preferred)
    return _no_reversals([port1.center, start_exit, on_lane(start_exit, lane), on_lane(end_entry, lane), end_entry, port2.center])


def _polyline_length_um(points: Sequence[Vec3]) -> float:
    total = 0.0
    for index in range(len(points) - 1):
        total += (points[index + 1] - points[index]).length()
    return total


class Route(Component):
    """A routed interconnect between ports.

    Routes always resolve through **physical** port coordinates (µm).  Schematic
    device art does not affect ``resolve_points()`` or ``physical_length_um``.
    GDS / gdsfactory backends consume the same physical backbone.

    Use ``kind='waveguide'`` for on-chip photonics and ``kind='fiber'`` for
    fiber patching. Free-space optical propagation remains the responsibility of
    ``Beam``.
    """

    component_type = "Route"

    points: list[Vec3] = field(default_factory=list)
    width: float = 0.5
    width2: float | None = None  # taper: width at the END (None = uniform)
    kind: str = "waveguide"
    path_type: str = "manhattan"
    smooth: bool = False
    bend_radius: float = 10.0
    backend: str = "local"
    signal: str | None = None
    voltage_v: float | None = None
    current_a: float | None = None
    impedance_ohms: float | None = None
    bandwidth_ghz: float | None = None
    required_bandwidth_ghz: float | None = None
    rf_power_dbm: float | None = None
    phase_deg: float | None = None
    bit_rate_gbps: float | None = None
    timing_ps: float | None = None
    start_component: Component | None = None
    start_port: str | None = None
    end_component: Component | None = None
    end_port: str | None = None

    def __init__(
        self,
        points: Iterable[Vec3 | tuple[float, float] | tuple[float, float, float]],
        *,
        width: float = 0.5,
        width2: float | None = None,
        kind: str = "waveguide",
        path_type: str = "manhattan",
        smooth: bool = False,
        bend_radius: float = 10.0,
        backend: str = "local",
        color: str | None = None,
        opacity: float = 1.0,
        label: str = "",
        signal: str | None = None,
        voltage_v: float | None = None,
        current_a: float | None = None,
        impedance_ohms: float | None = None,
        bandwidth_ghz: float | None = None,
        required_bandwidth_ghz: float | None = None,
        rf_power_dbm: float | None = None,
        phase_deg: float | None = None,
        bit_rate_gbps: float | None = None,
        timing_ps: float | None = None,
        start_component: Component | None = None,
        start_port: str | None = None,
        end_component: Component | None = None,
        end_port: str | None = None,
    ):
        self.points = [_as_vec3(point) for point in points]
        self.width = width
        self.width2 = None if width2 is None or abs(float(width2) - float(width)) < 1e-9 else float(width2)
        self.kind = kind
        self.path_type = path_type
        self.smooth = smooth
        self.bend_radius = bend_radius
        self.backend = backend
        self.color = color or _route_color(kind)
        self.opacity = opacity
        self.label = label
        self.signal = signal
        self.voltage_v = voltage_v
        self.current_a = current_a
        self.impedance_ohms = impedance_ohms
        self.bandwidth_ghz = bandwidth_ghz
        self.required_bandwidth_ghz = required_bandwidth_ghz
        self.rf_power_dbm = rf_power_dbm
        self.phase_deg = phase_deg
        self.bit_rate_gbps = bit_rate_gbps
        self.timing_ps = timing_ps
        self.start_component = start_component
        self.start_port = start_port
        self.end_component = end_component
        self.end_port = end_port
        self.transform = Transform()
        self._parent = None
        self._id = ""

    def resolve_points(self) -> list[tuple[float, float, float]]:
        transform = self.world_transform
        return [transform.apply_to_point(point).as_tuple() for point in self.points]

    @property
    def physical_length_um(self) -> float:
        """Centerline length in physical µm (independent of schematic draw scale)."""

        return _polyline_length_um(self.points)

    @property
    def display_width(self) -> float:
        """The width the route is drawn at: the wider end of a taper."""

        return max(float(self.width), float(self.width2 or 0.0))

    def legs(self) -> list[tuple[tuple[float, float], tuple[float, float]]]:
        """The straight spans of the route in plan, start to end, as ``Beam.legs`` gives a beam's: ``Glyph.on`` and
        ``Note.on`` place a mark on one. Points on one line make one leg."""

        legs: list[tuple[tuple[float, float], tuple[float, float]]] = []
        points = [(float(p[0]), float(p[1])) for p in self.resolve_points()]
        for a, b in zip(points, points[1:]):
            if math.dist(a, b) < 1e-9:
                continue
            if legs:
                (p, q) = legs[-1]
                ux, uy, vx, vy = q[0] - p[0], q[1] - p[1], b[0] - a[0], b[1] - a[1]
                if abs(ux * vy - uy * vx) < 1e-9 * math.hypot(ux, uy) * math.hypot(vx, vy) and ux * vx + uy * vy > 0:
                    legs[-1] = (p, b)
                    continue
            legs.append((a, b))
        if self.smooth:
            # shortcut: a rounded bend is 8 chords of about 0.2 bend radii; a straight shorter than a third of the
            # radius goes with them. Read the corners from the router if a mark must sit on so short a straight.
            legs = [leg for leg in legs if math.dist(*leg) >= self.bend_radius / 3.0]
        return legs

    def geometry_2d(self) -> dict[str, object]:
        return {
            "type": "route",
            "points": [point.as_tuple() for point in self.points],
            "width": self.width,
            "color": self.color,
            "opacity": self.opacity,
            "smooth": self.smooth,
            "kind": self.kind,
        }

    def to_dict(self) -> dict[str, object]:
        data = super().to_dict()
        data.update(
            {
                "route_points": self.resolve_points(),
                "route_width": self.width,
                "route_kind": self.kind,
                "route_path_type": self.path_type,
                "route_backend": self.backend,
                "route_signal": self.signal,
                "route_voltage_v": self.voltage_v,
                "route_current_a": self.current_a,
                "route_impedance_ohms": self.impedance_ohms,
                "route_bandwidth_ghz": self.bandwidth_ghz,
                "route_required_bandwidth_ghz": self.required_bandwidth_ghz,
                "route_rf_power_dbm": self.rf_power_dbm,
                "route_phase_deg": self.phase_deg,
                "route_bit_rate_gbps": self.bit_rate_gbps,
                "route_timing_ps": self.timing_ps,
                "route_start_component": _component_ref_name(self.start_component),
                "route_start_port": self.start_port,
                "route_end_component": _component_ref_name(self.end_component),
                "route_end_port": self.end_port,
                "physical_length_um": self.physical_length_um,
            }
        )
        return data


class WaveguideRoute(Route):
    component_type = "WaveguideRoute"

    def __init__(self, points, **kwargs):
        kwargs.setdefault("kind", "waveguide")
        kwargs.setdefault("color", _route_color("waveguide"))
        super().__init__(points, **kwargs)


class FiberRoute(Route):
    component_type = "FiberRoute"

    def __init__(self, points, **kwargs):
        kwargs.setdefault("kind", "fiber")
        kwargs.setdefault("color", _route_color("fiber"))
        super().__init__(points, **kwargs)


class WireBond(Route):
    """A gold wire bond from pad to pad: ``scene.route((pad_a, "e1"), (pad_b, "e1"), kind="wirebond")``.

    2D: an arc whose middle stands ``BULGE`` of the span to the left of the way from the first pad to the second.
    3D: a wire along the straight line between the pads that rises ``LOOP`` of the span over the line between the two
    pad tops. 1D: an electrical link. Its ``kind`` is "electrical", so the checks, the animation and the 1D view treat
    it as the wire it is; a saved scene records "wirebond".
    """

    component_type = "Route"                 # every view and the save know it as a route
    BULGE = 0.15
    LOOP = 0.30
    COLOR = "#d4af37"
    WIDTH = 0.25
    SAMPLES = 24

    def __init__(self, points, **kwargs):
        kwargs["kind"] = "electrical"
        kwargs["color"] = kwargs.get("color") or self.COLOR
        kwargs.setdefault("width", self.WIDTH)
        kwargs.setdefault("path_type", "wirebond")
        super().__init__(points, **kwargs)

    @classmethod
    def arc(cls, start: Vec3, end: Vec3) -> list[Vec3]:
        """The 2D path from ``start`` to ``end``: a quadratic curve that bulges ``BULGE`` of the span to the left."""

        dx, dy = end.x - start.x, end.y - start.y
        # the middle of a quadratic curve lies halfway from the chord to its control point
        control = Vec3((start.x + end.x) / 2.0 - 2.0 * cls.BULGE * dy, (start.y + end.y) / 2.0 + 2.0 * cls.BULGE * dx,
                       start.z)
        return [start, *_sample_quadratic_bezier(start, control, end, cls.SAMPLES)]

    def geometry_3d(self, part_geometry=None) -> dict[str, Any]:
        """The wire as a gold tube, in world coordinates (x, height, -y), from the top of the first pad to the top of
        the second. ``part_geometry(part)`` gives the 3D model of a pad as a view draws it (default: its own)."""

        (x0, y0, _), (x1, y1, _) = self.resolve_points()[0], self.resolve_points()[-1]
        h0, h1 = (_top_3d(part, part_geometry) for part in (self.start_component, self.end_component))
        rise = self.LOOP * math.hypot(x1 - x0, y1 - y0)
        steep = 2.0                  # an inverted catenary: the wire leaves each pad steeply, as a bonder loops it
        points = []
        for index in range(self.SAMPLES + 1):
            t = index / self.SAMPLES
            sag = (math.cosh(steep) - math.cosh(steep * (2.0 * t - 1.0))) / (math.cosh(steep) - 1.0)
            points.append([x0 + (x1 - x0) * t, h0 + (h1 - h0) * t + rise * sag, -(y0 + (y1 - y0) * t)])
        return {"shape": "tube_path", "points": points, "radius": self.width / 2.0, "segments": 48,
                "radialSegments": 10, "material": {"color": self.color, "metalness": 0.9, "roughness": 0.25},
                "role": "wire bond"}


def _top_3d(part: Component | None, part_geometry=None) -> float:
    """The height of the top of ``part`` in 3D, where a bond lands on it; 0 with no part."""

    if part is None:
        return 0.0
    from optodraw.check import solid_boxes

    geometry = part_geometry(part) if part_geometry is not None else part.geometry_3d()
    top = max((box[1][1] for _, box in solid_boxes(geometry or {})), default=0.0)
    return top + float(part.world_transform.position.z)


def route_ports(
    port1,
    port2,
    *,
    path_type: str = "manhattan",
    kind: str = "waveguide",
    width: float | None = None,
    width2: float | None = None,
    bend_radius: float = 10.0,
    start_straight_length: float = 5.0,
    end_straight_length: float = 5.0,
    steps: Sequence[dict[str, float]] | None = None,
    smooth: bool | None = None,
    backend: str = "auto",
    snap_tolerance: float | None = None,
    color: str | None = None,
    label: str = "",
    signal: str | None = None,
    voltage_v: float | None = None,
    current_a: float | None = None,
    impedance_ohms: float | None = None,
    bandwidth_ghz: float | None = None,
    required_bandwidth_ghz: float | None = None,
    rf_power_dbm: float | None = None,
    phase_deg: float | None = None,
    bit_rate_gbps: float | None = None,
    timing_ps: float | None = None,
) -> Route:
    """Route between two ports.

    Parameters intentionally mirror common PHIDL / gdsfactory ideas while
    staying lightweight enough for a renderer-first package.
    """
    start, start_component, start_port = _resolve_port_endpoint(port1)
    end, end_component, end_port = _resolve_port_endpoint(port2)
    true_end = end.center
    end = _snap_near_collinear(start, end, tolerance=snap_tolerance)
    snapped = (end.center - true_end).length() > 1e-9
    if kind == "wirebond":                   # an arc from pad to pad: it is not routed round parts or smoothed
        path_type, smooth, width = "wirebond", False, WireBond.WIDTH if width is None else width
    cable = bench_cable(kind, start_component, end_component)
    if cable:
        width = CABLE_WIDTH if width is None and width2 is None else width
        color = color or CABLE_COLOR
    # Width defaults to the PORT widths: uniform when they match, a linear TAPER
    # when they differ (start width -> end width, like real photonic layouts).
    # An explicit ``width`` makes the route uniform unless ``width2`` is given.
    if width is not None:
        route_width = float(width)
        route_width2 = float(width2) if width2 is not None else None
    elif width2 is not None:
        route_width, route_width2 = float(start.width), float(width2)
    elif kind == "waveguide":
        # a width change along a waveguide IS a taper — draw it as one
        route_width = float(start.width)
        route_width2 = float(end.width) if abs(float(end.width) - route_width) > 1e-9 else None
    else:
        # wires and fibres keep one width: a bond pad's port describes the whole
        # landing, so tapering into it would draw a wedge, not a trace
        route_width = min(float(start.width), float(end.width))
        route_width2 = None
    route_backend = "local"
    route_bend_radius = bend_radius
    cabled = (_cable_path(start, end, start_component, end_component)
              if cable and any(map(_on_bench, (start_component, end_component))) and steps is None
              and path_type in {"manhattan", "L"} else None)
    if cabled is not None:
        backbone = cabled
    elif _should_use_gdsfactory_backend(kind, path_type, steps, backend):
        try:
            backbone, route_bend_radius = _route_with_gdsfactory(
                start,
                end,
                kind=kind,
                width=route_width,
                bend_radius=bend_radius,
                start_straight_length=start_straight_length,
                end_straight_length=end_straight_length,
                steps=steps,
            )
            route_backend = "gdsfactory"
        except Exception as error:
            logger.warning(
                "gdsfactory routing failed (%s); falling back to the built-in router",
                error,
            )
            backbone = _build_route_backbone(
                start,
                end,
                path_type,
                start_straight_length,
                end_straight_length,
                steps,
                route_bend_radius,
            )
    elif kind == "wirebond":
        backbone = WireBond.arc(start.center, true_end)
    else:
        backbone = _build_route_backbone(
            start,
            end,
            path_type,
            start_straight_length,
            end_straight_length,
            steps,
            route_bend_radius,
        )

    # Routes must not run OVER the devices they connect (their port-hull boxes).
    boxes = []
    for comp in (start_component, end_component):
        if comp is None:
            continue
        box = _port_hull_box(comp)
        if box:
            boxes.append(box)
    if cabled is None and boxes and path_type == "manhattan" and _backbone_crosses_boxes(backbone, boxes):
        if route_backend != "local":
            # the smooth backend cut across a device — reroute locally and nudge
            backbone = _build_route_backbone(
                start, end, path_type, start_straight_length, end_straight_length, steps, route_bend_radius,
            )
            route_backend = "local"
        backbone = _manhattanize(_nudge_backbone_clear(backbone, boxes))

    # ... and they must not run over the parts they merely pass either.
    if cabled is None and steps is None and path_type in {"manhattan", "straight", "L"}:
        obstacles = _obstacle_boxes(start_component, end_component)
        if obstacles and path_type != "smooth" and _backbone_crosses_boxes(backbone, obstacles, clear_of_ends=0.0):
            backbone = _manhattanize(_detour_around_boxes(backbone, obstacles))

    use_smooth = smooth if smooth is not None else (
        (route_backend == "gdsfactory" and kind in {"waveguide", "optical"})
        or path_type in {"smooth", "all_angle", "dubins"}
    )
    # An actual cosine S-bend arrives pre-curved (dense samples) and must be used
    # as-is; but when "smooth" falls back to a manhattan/L backbone (perpendicular,
    # U-turn, or waypointed ports) it is polygonal and still needs its corners
    # rounded — otherwise the S-bend route type draws SHARP 90° corners.
    pre_curved = path_type == "smooth" and len(backbone) > 8
    route_points = backbone if pre_curved else (_rounded_path_points(backbone, route_bend_radius) if (use_smooth or path_type == "smooth") else backbone)
    if snapped and route_points:
        # The snap steered the approach, but the metal must still land on the
        # actual port: terminate at the true endpoint so exports stay honest.
        # The residual sub-micron jog stays visible instead of vanishing.
        route_points = list(route_points)
        if (route_points[-1] - true_end).length() > 1e-9:
            route_points.append(true_end)
    route_cls = {"fiber": FiberRoute, "waveguide": WaveguideRoute, "wirebond": WireBond}.get(kind, Route)
    route = route_cls(
        route_points,
        width=route_width,
        width2=route_width2,
        kind=kind,
        path_type=path_type,
        smooth=use_smooth,
        bend_radius=route_bend_radius,
        backend=route_backend,
        color=color,
        label=label,
        signal=signal,
        voltage_v=voltage_v,
        current_a=current_a,
        impedance_ohms=impedance_ohms,
        bandwidth_ghz=bandwidth_ghz,
        required_bandwidth_ghz=required_bandwidth_ghz,
        rf_power_dbm=rf_power_dbm,
        phase_deg=phase_deg,
        bit_rate_gbps=bit_rate_gbps,
        timing_ps=timing_ps,
        start_component=start_component,
        start_port=start_port,
        end_component=end_component,
        end_port=end_port,
    )
    options = {}
    if steps is not None:
        options["steps"] = [dict(step) for step in steps]
    if start_straight_length != 5.0:
        options["start_straight_length"] = start_straight_length
    if end_straight_length != 5.0:
        options["end_straight_length"] = end_straight_length
    if snap_tolerance is not None:
        options["snap_tolerance"] = snap_tolerance
    route._routing_options = options
    return route


def route_bundle(
    ports1: Sequence,
    ports2: Sequence,
    *,
    separation: float = 5.0,
    sort_ports: bool = True,
    path_type: str = "manhattan",
    kind: str = "waveguide",
    width: float | None = None,
    start_straight_length: float = 5.0,
    end_straight_length: float = 5.0,
    backend: str = "auto",
) -> list[Route]:
    """Route a bundle between two port groups with simple river-style spacing."""
    start_pairs = [(_resolve_port_ref(ref), ref) for ref in ports1]
    end_pairs = [(_resolve_port_ref(ref), ref) for ref in ports2]
    if len(start_pairs) != len(end_pairs):
        raise ValueError("route_bundle requires the same number of start and end ports")
    if not start_pairs:
        return []

    dx = sum(port.center.x for port, _ in end_pairs) / len(end_pairs) - sum(port.center.x for port, _ in start_pairs) / len(start_pairs)
    dy = sum(port.center.y for port, _ in end_pairs) / len(end_pairs) - sum(port.center.y for port, _ in start_pairs) / len(start_pairs)
    horizontal_bundle = abs(dx) >= abs(dy)
    transverse_key = (lambda port: port.center.y) if horizontal_bundle else (lambda port: port.center.x)

    if sort_ports:
        start_pairs = sorted(start_pairs, key=lambda pair: transverse_key(pair[0]))
        end_pairs = sorted(end_pairs, key=lambda pair: transverse_key(pair[0]))

    routes: list[Route] = []
    if horizontal_bundle:
        corridor_x = (
            sum(port.outward(start_straight_length).x for port, _ in start_pairs)
            + sum(port.outward(end_straight_length).x for port, _ in end_pairs)
        ) / (2 * len(start_pairs))
    else:
        corridor_y = (
            sum(port.outward(start_straight_length).y for port, _ in start_pairs)
            + sum(port.outward(end_straight_length).y for port, _ in end_pairs)
        ) / (2 * len(start_pairs))

    center_index = (len(start_pairs) - 1) / 2.0
    for index, ((start, start_ref), (end, end_ref)) in enumerate(zip(start_pairs, end_pairs)):
        offset = (index - center_index) * separation
        start_exit = start.outward(start_straight_length)
        end_entry = end.outward(end_straight_length)

        if horizontal_bundle:
            steps = [
                {"y": start_exit.y + offset},
                {"x": corridor_x},
                {"y": end_entry.y + offset},
                {"x": end_entry.x},
            ]
        else:
            steps = [
                {"x": start_exit.x + offset},
                {"y": corridor_y},
                {"x": end_entry.x + offset},
                {"y": end_entry.y},
            ]

        routes.append(
            route_ports(
                start_ref,
                end_ref,
                path_type=path_type,
                kind=kind,
                width=width,
                start_straight_length=start_straight_length,
                end_straight_length=end_straight_length,
                steps=steps,
                backend=backend,
            )
        )

    return routes
