"""Simple layout helpers for setup building."""

from __future__ import annotations

import re
from typing import Iterable

from optodraw.core.transform import Vec3
from optodraw.layout.chip_builder import build_microring_weight_mesh, build_mzm_coupler_mesh, build_mzm_mesh, build_ring_filter


def _bounds_from_path(data: str) -> tuple[float, float, float, float] | None:
    """Bound path endpoints and controls; enlarge arcs conservatively."""

    tokens = re.findall(r"[A-Za-z]|[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?", data)
    arity = {"M": 2, "L": 2, "H": 1, "V": 1, "Q": 4, "C": 6, "A": 7}
    points: list[tuple[float, float]] = []
    x = y = 0.0
    start = (0.0, 0.0)
    command = ""
    index = 0
    while index < len(tokens):
        if tokens[index].isalpha():
            command = tokens[index]
            index += 1
            if command.upper() == "Z":
                x, y = start
                points.append(start)
                command = ""
                continue
        kind = command.upper()
        if kind not in arity:
            return None
        count = arity[kind]
        chunk = tokens[index:index + count]
        if len(chunk) < count or any(token.isalpha() for token in chunk):
            return None
        values = [float(token) for token in chunk]
        index += count
        base_x, base_y = x, y
        relative = command.islower()
        if kind in {"M", "L"}:
            x = values[0] + (base_x if relative else 0.0)
            y = values[1] + (base_y if relative else 0.0)
            points.append((x, y))
            if kind == "M":
                start = (x, y)
                command = "l" if relative else "L"
        elif kind == "H":
            x = values[0] + (base_x if relative else 0.0)
            points.append((x, y))
        elif kind == "V":
            y = values[0] + (base_y if relative else 0.0)
            points.append((x, y))
        elif kind in {"Q", "C"}:
            for offset in range(0, count, 2):
                px = values[offset] + (base_x if relative else 0.0)
                py = values[offset + 1] + (base_y if relative else 0.0)
                points.append((px, py))
            x, y = points[-1]
        elif kind == "A":
            radius = 2.0 * max(abs(values[0]), abs(values[1]))
            x = values[5] + (base_x if relative else 0.0)
            y = values[6] + (base_y if relative else 0.0)
            points.extend([
                (base_x - radius, base_y - radius), (base_x + radius, base_y + radius),
                (x - radius, y - radius), (x + radius, y + radius),
            ])
    if not points:
        return None
    xs, ys = zip(*points)
    return min(xs), min(ys), max(xs), max(ys)


def _bounds_from_geometry(geometry: dict | None) -> tuple[float, float, float, float] | None:
    """Estimate local 2D bounds from an OptoDraw geometry dictionary."""

    if not geometry:
        return None
    gtype = geometry.get("type")
    if gtype == "art" and "bounds" in geometry:
        return tuple(geometry["bounds"])
    if gtype == "group":
        child_bounds = [_bounds_from_geometry(child) for child in geometry.get("children", [])]
        child_bounds = [bounds for bounds in child_bounds if bounds is not None]
        if not child_bounds:
            return None
        return (
            min(bounds[0] for bounds in child_bounds),
            min(bounds[1] for bounds in child_bounds),
            max(bounds[2] for bounds in child_bounds),
            max(bounds[3] for bounds in child_bounds),
        )
    if gtype == "rect":
        cx, cy, width, height = geometry.get("cx", 0.0), geometry.get("cy", 0.0), geometry["w"], geometry["h"]
        return (cx - width / 2.0, cy - height / 2.0, cx + width / 2.0, cy + height / 2.0)
    if gtype == "circle":
        cx, cy, radius = geometry.get("cx", 0.0), geometry.get("cy", 0.0), geometry["r"]
        return (cx - radius, cy - radius, cx + radius, cy + radius)
    if gtype == "ellipse":
        cx, cy = geometry.get("cx", 0.0), geometry.get("cy", 0.0)
        rx, ry = geometry.get("rx", 0.0), geometry.get("ry", 0.0)
        return (cx - rx, cy - ry, cx + rx, cy + ry)
    if gtype == "path":
        return _bounds_from_path(str(geometry.get("d", "")))
    if gtype == "line":
        return (
            min(geometry["x1"], geometry["x2"]),
            min(geometry["y1"], geometry["y2"]),
            max(geometry["x1"], geometry["x2"]),
            max(geometry["y1"], geometry["y2"]),
        )
    if gtype == "polyline":
        points = geometry.get("points", [])
        if not points:
            return None
        xs = [point[0] for point in points]
        ys = [point[1] for point in points]
        return (min(xs), min(ys), max(xs), max(ys))
    if gtype == "polygon":
        points = geometry.get("points", [])
        if not points:
            return None
        xs = [point[0] for point in points]
        ys = [point[1] for point in points]
        return (min(xs), min(ys), max(xs), max(ys))
    return None


def estimate_component_size(component) -> tuple[float, float]:
    """Return a conservative ``(width, height)`` estimate for layout spacing."""

    left, bottom, right, top = estimate_component_bounds(component)
    return max(right - left, 8.0), max(top - bottom, 8.0)


def estimate_component_bounds(component) -> tuple[float, float, float, float]:
    """Return local drawing bounds, including an off-center footprint."""

    from optodraw.layout._cache import _component_state

    state = _component_state(component)
    cached = getattr(component, "_layout_bounds_cache", None)
    if state is not None and cached is not None and cached[0] == state:
        return cached[1]
    bounds = _estimate_component_bounds(component)
    if state is not None:
        component._layout_bounds_cache = (_component_state(component), bounds)
    return bounds


def _estimate_component_bounds(component) -> tuple[float, float, float, float]:
    """Compute drawing bounds using the original geometry and art rules."""

    from optodraw.symbols.art import art_bounds, union

    art = art_bounds(component)
    if art is not None:                     # a painted part: what is drawn, and the ports where beams attach
        try:
            ports = component.ports() if callable(getattr(component, "ports", None)) else {}
        except Exception:
            ports = {}
        points = [(float(p.center.x), float(p.center.y)) for p in ports.values()]
        return (min([art[0]] + [x for x, _ in points]), min([art[1]] + [y for _, y in points]),
                max([art[2]] + [x for x, _ in points]), max([art[3]] + [y for _, y in points]))
    bounds = union(_bounds_from_geometry(component.geometry_2d()), art)
    if bounds is not None:
        return bounds

    geometry = component.geometry_3d()
    shape = geometry.get("shape") if geometry else None
    if shape == "box":
        width = max(geometry.get("width", 10.0), 8.0)
        height = max(geometry.get("depth", geometry.get("height", 10.0)), 8.0)
        return -width / 2.0, -height / 2.0, width / 2.0, height / 2.0
    if shape == "cylinder":
        radius = geometry.get("radius", 5.0)
        extent = max(radius, 4.0)
        return -extent, -extent, extent, extent
    if shape == "torus":
        radius = geometry.get("radius", 5.0)
        tube = geometry.get("tube", 1.0)
        extent = max(radius + tube, 4.0)
        return -extent, -extent, extent, extent
    return -12.0, -12.0, 12.0, 12.0


def arrange_line(
    components: Iterable,
    *,
    axis: str = "x",
    spacing: float = 20.0,
    origin: tuple[float, float] = (0.0, 0.0),
    grid: float = 1.0,
) -> list:
    """Place components in a horizontal or vertical line with fixed spacing.

    Positions land on ``grid`` (whole units by default) so they read as round
    numbers in the editor; pass ``grid=0`` to keep the raw footprint arithmetic."""

    arranged = list(components)
    cursor = origin[0] if axis == "x" else origin[1]
    previous_size = 0.0
    for index, component in enumerate(arranged):
        width, height = estimate_component_size(component)
        size = width if axis == "x" else height
        if index == 0:
            center = cursor
        else:
            center = cursor + previous_size / 2.0 + spacing + size / 2.0
        placed = round(center / grid) * grid if grid else center
        if axis == "x":
            component.transform.position = Vec3(placed, origin[1], component.transform.position.z)
        else:
            component.transform.position = Vec3(origin[0], placed, component.transform.position.z)
        cursor = center
        previous_size = size
    return arranged


def arrange_grid(
    components: Iterable,
    *,
    columns: int = 3,
    spacing: tuple[float, float] = (35.0, 35.0),
    origin: tuple[float, float] = (0.0, 0.0),
) -> list:
    """Place components into a simple row-major grid."""

    arranged = list(components)
    for index, component in enumerate(arranged):
        row = index // columns
        col = index % columns
        component.transform.position = Vec3(
            origin[0] + col * spacing[0],
            origin[1] - row * spacing[1],
            component.transform.position.z,
        )
    return arranged


def align_ports(source, source_port: str, target, target_port: str, *, gap: float = 12.0, grid: float = 1.0):
    """Move ``target`` so ``target_port`` sits ``gap`` in front of ``source_port``.

    This is the placement you get by clicking one port and then the next: the two
    ports end up collinear, facing each other, ``gap`` apart — so the route
    between them is a straight hop instead of a detour around the component.
    Only ``target`` moves, and only its position; rotation is left alone, since
    which way a part faces is a design decision, not a layout one.

    The result lands on a ``grid`` (whole units by default) so positions read as
    round numbers in the editor. The leftover misalignment is a fraction of a
    waveguide width, which the router treats as collinear -- the link stays a
    straight run. Pass ``grid=0`` for exact, unrounded alignment.
    """

    import math
    import numpy as np

    src = source.world_port(source_port)
    heading = math.radians(float(src.orientation_deg))
    tip_x = float(src.center.x) + math.cos(heading) * float(gap)
    tip_y = float(src.center.y) + math.sin(heading) * float(gap)
    target_port_world = target.world_port(target_port).center
    origin = target.world_transform.position
    x = float(origin.x) + tip_x - float(target_port_world.x)
    y = float(origin.y) + tip_y - float(target_port_world.y)
    if grid:
        x, y = round(x / grid) * grid, round(y / grid) * grid
    parent = getattr(target, "_parent", None)
    if parent is None:
        target.transform.position = Vec3(x, y, target.transform.position.z)
    else:
        world_origin = np.array([x, y, float(origin.z), 1.0])
        local_origin = np.linalg.solve(parent.world_transform.to_matrix_4x4(), world_origin)
        target.transform.position = Vec3(*map(float, local_origin[:3]))
    return target


def chain_ports(links, *, gap: float = 12.0, grid: float = 1.0) -> list:
    """Place a whole signal chain port to port.

    ``links`` is a sequence of ``(source, source_port, target, target_port)``
    tuples applied in order, so each part lands in front of the one feeding it.
    """

    return [align_ports(a, ap, b, bp, gap=gap, grid=grid) for a, ap, b, bp in links]


def optimize_layout(
    components: Iterable,
    *,
    strategy: str = "line",
    **kwargs,
) -> list:
    """Dispatch to the requested layout strategy and return the moved objects."""

    if strategy == "grid":
        return arrange_grid(components, **kwargs)
    return arrange_line(components, **kwargs)

__all__ = [
    "aim",
    "align_ports",
    "arrange_grid",
    "arrange_line",
    "chain_ports",
    "build_microring_weight_mesh",
    "build_mzm_coupler_mesh",
    "build_mzm_mesh",
    "build_ring_filter",
    "estimate_component_size",
    "estimate_component_bounds",
    "optimize_layout",
]


def face(part, toward, port=None):
    """Turn ``part`` so its input ``port`` looks at ``toward`` (a part or an ``(x, y)`` point): a detector,
    a camera or a fibre port then takes the beam on its face, not through its back. ``port`` defaults to the
    part's ``in`` port, or its only port. For a mirror or a splitter use :func:`aim`. Returns the part."""

    import math

    ports = part.ports()
    if port is None:
        faces = [name for name, p in ports.items() if p.kind != "electrical"]     # a wire's jack is never the face
        port = "in" if "in" in ports else (faces[0] if len(faces) == 1 else None)
        if port is None:
            raise ValueError(f"{getattr(part, 'label', '') or part.component_type}: name the port to face with, "
                             f"one of {', '.join(ports)}")
    if hasattr(toward, "world_position"):
        tx, ty = float(toward.world_position.x), float(toward.world_position.y)
    else:
        tx, ty = float(toward[0]), float(toward[1])
    here = part.world_position
    if math.hypot(tx - here.x, ty - here.y) < 1e-12:
        raise ValueError(f"{getattr(part, 'label', '') or part.component_type}: it cannot face its own centre")
    look = math.degrees(math.atan2(ty - here.y, tx - here.x))
    part.transform.rotation_deg.z = (look - ports[port].orientation_deg + 180.0) % 360.0 - 180.0
    return part


def aim(part, source, target):
    """Turn a mirror, splitter or dichroic so its reflecting face sends light from ``source`` to ``target``.

    The reflecting face is the part's local -x side: a mirror's ``io`` port, a splitter's front between ``in``
    and ``refl``. It is turned to look along the bisector of the two beams, and moved so the point where the
    reflected beam is drawn (a mirror's face, a plate's centre) sits on the part's given centre. ``source`` and ``target`` are parts or ``(x, y)`` points. Use it on parts placed in
    the scene's own frame. Returns the part."""

    import math

    def point(stop):
        if hasattr(stop, "world_position"):
            position = stop.world_position
            return float(position.x), float(position.y)
        return float(stop[0]), float(stop[1])

    here = part.world_position
    directions = []
    for stop in (source, target):
        x, y = point(stop)
        length = math.hypot(x - here.x, y - here.y)
        if length < 1e-12:
            raise ValueError(f"{getattr(part, 'label', '') or part.component_type}: a beam end sits on the part")
        directions.append(((x - here.x) / length, (y - here.y) / length))
    face = math.degrees(math.atan2(directions[0][1] + directions[1][1], directions[0][0] + directions[1][0]))
    part.transform.rotation_deg.z = (face - 180.0 + 180.0) % 360.0 - 180.0
    # Put the point where the reflected beam is drawn (a mirror's face, half the substrate off its centre; a
    # plate's centre) on the point the caller gave, so a part on the line of the incoming beam adds no tilt.
    from optodraw.core.beam import beam_point

    ports = part.ports()
    reflecting = "io" if "io" in ports else ("refl" if "refl" in ports and hasattr(part, "beam_point") else None)
    if reflecting is not None:
        hit = beam_point(part, reflecting)
        part.transform.position.x += here.x - hit.x
        part.transform.position.y += here.y - hit.y
    return part
