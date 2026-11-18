"""On-chip routes for a 1D chip schematic: each link leaves its port square, runs on a grid round the symbols,
turns as little as it can, and keeps off the tracks of the links routed before it.

A link is routed by A* on a coarse grid whose cells inside a symbol are closed. A step costs its length, a turn
costs more, a cell another link already runs along costs much more (two links never share a track), and
crossing another link costs a little (crossings are allowed where the topology needs them). The result is a
polyline per link; the drawing rounds its corners.
"""

from __future__ import annotations

import heapq
import math
from typing import Any

from optodraw.check import _crosses

from .schematic import link_ends

PITCH = 2.5          # grid cell, SVG points
CLEAR = 1.5          # a route keeps this far off a symbol
LEAD = 5.0           # straight out of a port before the first turn
TURN = 6.0           # the cost of a turn, in cells
SHARE = 60.0         # the cost of running along another link's track
CROSS = 8.0          # the cost of crossing another link
CORNER = 3.0         # the radius of a drawn bend, SVG points
IN_LINE = 0.01       # two ports this close to one line are joined by a straight route
SEARCH = 200000      # grid steps a search may take, plus 40 per cell between its ends
NEAR = 4             # a guided route keeps within this many cells of its guide
TAIL = 12.0          # but not this close to its ports, where the 2D port sits elsewhere than the symbol's
AWAY = 3.0           # the cost of a step outside that corridor
OFF_GUIDE = 1.0      # and of a step inside it, per cell off the guide
JOG = 8.0            # a step this short between two runs that go the same way is taken out
REPAIRS = 12         # rounds of taking up a crossing pair and routing it again the other way round
ROOM = 30.0          # the grid reaches this far past the right and bottom of the schematic

_STEPS = ((1, 0), (-1, 0), (0, 1), (0, -1))


def _out_of(boxes: list, point: tuple[float, float], normal: tuple[int, int]) -> tuple[float, float]:
    """The point a lead along ``normal`` reaches: LEAD past the port, and clear of its own symbol and label."""

    x, y = point[0] + normal[0] * LEAD, point[1] + normal[1] * LEAD
    for _ in range(400):
        if not any(box and box[0] - CLEAR < x < box[2] + CLEAR and box[1] - CLEAR < y < box[3] + CLEAR for box in boxes):
            break
        x, y = x + normal[0] * PITCH, y + normal[1] * PITCH
    return x, y


def route_links(schematic: Any, guides: dict[int, list[tuple[float, float]]] | None = None,
                ) -> dict[int, list[tuple[float, float]]]:
    """A polyline for every link of a schematic, routed round the symbols and off each other's tracks.

    ``guides`` maps a link to a path it should follow (its 2D route on the 1D page): the route keeps within a
    few tracks of it unless the symbols force it out.
    """

    guides = guides or {}

    from .schematic import _inside, _label_box

    items = schematic.items
    boxes = [(i.x, i.y, i.x + i.symbol.width, i.y + i.symbol.height) for i in items]
    labels = [_label_box(*i.label_at, i.label) if i.label else None for i in items]   # a route keeps off the text
    # routes stay on the page, which grows right and down; a guide that runs left of or above the page (a 2D
    # cable round the outside) takes the grid with it, and the page moves later to hold the route
    reach = [point for guide in guides.values() for point in guide]
    origin = (min([0.0] + [x - ROOM for x, _ in reach]), min([0.0] + [y - ROOM for _, y in reach]))
    width = int(math.ceil((schematic.width + ROOM - origin[0]) / PITCH)) + 2
    height = int(math.ceil((schematic.height + ROOM - origin[1]) / PITCH)) + 2

    def cell(x: float, y: float) -> tuple[int, int]:
        return (int(round((x - origin[0]) / PITCH)), int(round((y - origin[1]) / PITCH)))

    def point(c: tuple[int, int]) -> tuple[float, float]:
        return (origin[0] + c[0] * PITCH, origin[1] + c[1] * PITCH)

    closed = bytearray(width * height)
    for x0, y0, x1, y1 in boxes + [box for box in labels if box]:
        a, b = cell(x0 - CLEAR, y0 - CLEAR), cell(x1 + CLEAR, y1 + CLEAR)
        for cx in range(max(a[0], 0), min(b[0], width - 1) + 1):
            for cy in range(max(a[1], 0), min(b[1], height - 1) + 1):
                closed[cy * width + cx] = 1
    used_h = bytearray(width * height)   # a link runs along this cell horizontally
    used_v = bytearray(width * height)   # or vertically

    plans = []
    for index, link in enumerate(schematic.links):
        if link.kind == "free_space":
            continue                                            # light in air runs straight
        s, n, e, m = link_ends(schematic, link)
        n1, n2 = (int(round(n[0])), int(round(n[1]))), (int(round(m[0])), int(round(m[1])))
        if index in guides:                     # an electrode inside a part is met the way its 2D route meets it
            n1, n2 = (_met_from(guides[index], s, e, items[link.start].symbol.ports.get(link.start_port),
                                items[link.start].symbol, link, n1, first=True),
                      _met_from(guides[index], s, e, items[link.end].symbol.ports.get(link.end_port),
                                items[link.end].symbol, link, n2, first=False))
        start = _out_of([boxes[link.start], labels[link.start]], s, n1)
        end = _out_of([boxes[link.end], labels[link.end]], e, n2)
        opened: set[int] = set()
        inside = [False, False]
        for part, name, at, normal, lead in ((link.start, link.start_port, s, n1, "start"),
                                             (link.end, link.end_port, e, n2, "end")):
            port = items[part].symbol.ports.get(name)
            if link.electrical and port is not None and _inside(items[part].symbol, port):
                # a cable to an electrode inside a part may cross that part, as metal crosses its waveguides in 2D
                stub = (at[0] + normal[0] * LEAD, at[1] + normal[1] * LEAD)
                start, end = (stub, end) if lead == "start" else (start, stub)
                inside[0 if lead == "start" else 1] = True
                a, b = cell(boxes[part][0] - CLEAR, boxes[part][1] - CLEAR), cell(boxes[part][2] + CLEAR, boxes[part][3] + CLEAR)
                opened |= {cy * width + cx for cx in range(max(a[0], 0), min(b[0], width - 1) + 1)
                           for cy in range(max(a[1], 0), min(b[1], height - 1) + 1)}
        plans.append((index, link, s, start, e, end, n1, n2, opened, tuple(inside)))
    # the optical links first, the short ones first: the long ones then route round what is there
    plans.sort(key=lambda p: (p[1].electrical, abs(p[3][0] - p[5][0]) + abs(p[3][1] - p[5][1])))

    def mark(points: list[tuple[float, float]], step: int = 1) -> None:
        """Count the route on its tracks (``step`` -1 takes it off again)."""

        for (x0, y0), (x1, y1) in zip(points, points[1:]):
            a, b = cell(x0, y0), cell(x1, y1)
            horizontal = abs(y1 - y0) < abs(x1 - x0)
            b = (b[0], a[1]) if horizontal else (a[0], b[1])
            used = used_h if horizontal else used_v
            for cx, cy in _cells_between(*a, *b):
                if 0 <= cx < width and 0 <= cy < height:
                    k = cy * width + cx
                    used[k] = min(255, max(0, used[k] + step))

    def corridor(guide: list[tuple[float, float]]) -> dict[int, int]:
        near: dict[int, int] = {}                               # cell -> how many cells it lies off the guide
        for (x0, y0), (x1, y1) in zip(guide, guide[1:]):
            steps = max(1, int(math.dist((x0, y0), (x1, y1)) / (PITCH / 2.0)))
            for k in range(steps + 1):
                cx, cy = cell(x0 + (x1 - x0) * k / steps, y0 + (y1 - y0) * k / steps)
                for dx in range(-NEAR, NEAR + 1):
                    for dy in range(-NEAR, NEAR + 1):
                        if 0 <= cx + dx < width and 0 <= cy + dy < height:
                            key, off = (cy + dy) * width + cx + dx, max(abs(dx), abs(dy))
                            if off < near.get(key, NEAR + 1):
                                near[key] = off
        return near

    routes: dict[int, list[tuple[float, float]]] = {}
    ends = {index: {(link.start, link.start_port), (link.end, link.end_port)} for index, link in enumerate(schematic.links)}

    def crossed(index: int, points: list[tuple[float, float]]) -> int:
        """How many of the routes drawn so far ``points`` crosses (routes that share a port with it do not count)."""

        mine = list(zip(points, points[1:]))
        return sum(1 for other, route in routes.items() if other != index and not ends[index] & ends[other]
                   and any(_crosses(p, q) for p in mine for q in zip(route, route[1:])))

    def route_one(plan, guided: bool = True) -> list[tuple[float, float]]:
        index, link, s, start, e, end, n1, n2, opened, inside = plan
        near, reach, onto = None, None, None
        if guided and index in guides:
            onto = _onto_ports(guides[index], s, e, n1, n2, inside)
            inner = _trim(onto, TAIL)                           # the ends route freely
            if len(inner) >= 2:
                near = corridor(inner)
                reach = (min(x for x, _ in inner) - PITCH, min(y for _, y in inner) - PITCH,
                         max(x for x, _ in inner) + PITCH, max(y for _, y in inner) + PITCH)
        others = [box for k, box in enumerate(boxes) if k not in (link.start, link.end)] + [box for box in labels if box]
        drawn = [route for k, route in routes.items() if k != index]
        # two wires on one port are one node, as in a circuit drawing: a straight wire may run onto the other
        apart = [route for k, route in routes.items() if k != index and not ends[index] & ends[k]]
        points = _direct(s, n1, e, n2, others, apart)
        if points is not None and near is not None and not _keeps_near(points, near, cell, width, reach):
            points = None                                       # a short cut its 2D route does not take
        if points is None:
            a, b = cell(*start), cell(*end)
            path = _astar(a, b, n1, (-n2[0], -n2[1]), width, height, closed, used_h, used_v, near, opened)
            for _ in range(3):          # a lead clear of its part and label can round into a cell of their margin
                if path is not None:
                    break
                start = (start[0] + n1[0] * PITCH, start[1] + n1[1] * PITCH)
                end = (end[0] + n2[0] * PITCH, end[1] + n2[1] * PITCH)
                a, b = cell(*start), cell(*end)
                path = _astar(a, b, n1, (-n2[0], -n2[1]), width, height, closed, used_h, used_v, near, opened)
            if path is None:                                    # boxed in: square, straight over what is there
                corner = (end[0], start[1]) if n1[0] else (start[0], end[1])
                points = _simplify([s, start, corner, end, e])
            else:
                points = _simplify(_snap_ends([s, start] + [point(c) for c in path[1:-1]] + [end, e]))
        if onto is not None:
            # the 2D route's first turn, then straight on to the port: the steps the guide picks up later on the
            # 1D page (a slanted 2D run squared into a staircase) do not carry over when they buy nothing. Or the
            # guide itself, its lane where the 2D route has it, when that is square and clear: the lane moved to
            # keep its gap to an electrode can land on another part, and the route then steps round it
            own = [boxes[link.start], boxes[link.end]]
            for better in (_guided(s, n1, e, n2, onto, others, own, drawn),
                           _as_drawn(s, n1, e, n2, _onto_ports(guides[index], s, e, n1, n2), others, own, drawn)):
                if (better is not None and _corner_count(better) < _corner_count(points)
                        and crossed(index, better) <= crossed(index, points)):
                    points = better
        return points

    for plan in plans:
        routes[plan[0]] = route_one(plan)
        mark(routes[plan[0]])

    # A pair that crosses because of the order it was routed in: take both up and route them the other way round;
    # keep the new pair only when it crosses less.
    by_index = {plan[0]: plan for plan in plans}

    def crossings(index: int, skip: int | None = None) -> int:
        mine = list(zip(routes[index], routes[index][1:]))
        return sum(1 for other, route in routes.items()
                   if other not in (index, skip) and not ends[index] & ends[other]
                   and any(_crosses(p, q) for p in mine for q in zip(route, route[1:])))

    def fan(a: int, b: int) -> bool:
        """Two links that leave one side of one part."""

        for part_a, port_a in ((schematic.links[a].start, schematic.links[a].start_port),
                               (schematic.links[a].end, schematic.links[a].end_port)):
            for part_b, port_b in ((schematic.links[b].start, schematic.links[b].start_port),
                                   (schematic.links[b].end, schematic.links[b].end_port)):
                ports = items[part_a].symbol.ports
                if part_a == part_b and port_a in ports and port_b in ports and ports[port_a].side == ports[port_b].side:
                    return True
        return False

    for _ in range(REPAIRS):
        pairs = [(a, b) for a in routes for b in routes if a < b and not ends[a] & ends[b]
                 and any(_crosses(p, q) for p in zip(routes[a], routes[a][1:]) for q in zip(routes[b], routes[b][1:]))]
        mended = False
        for a, b in pairs:
            before = crossings(a) + crossings(b, skip=a)
            old = {a: routes[a], b: routes[b]}
            order = [b, a] if plans.index(by_index[a]) < plans.index(by_index[b]) else [a, b]
            # the other way round; then, for a fan, without their 2D guides: squared one by one, the guides of a
            # fan that leaves a part at an angle can turn in the wrong order, though their 2D routes never cross
            for guided in ((True, False) if fan(a, b) else (True,)):
                for k in old:
                    mark(routes[k], -1)
                for k in order:
                    routes[k] = route_one(by_index[k], guided=guided)
                    mark(routes[k])
                if crossings(a) + crossings(b, skip=a) < before:
                    mended = True
                    break
                for k in old:                                   # no better: as it was
                    mark(routes[k], -1)
                    routes[k] = old[k]
                    mark(routes[k])
            if mended:
                break
        if not mended:
            break

    # A jog of a few cells between two runs that go the same way reads as a mistake: straighten it where the
    # straight route stays clear of the symbols and the other routes and crosses nothing new.
    obstacles = boxes + [box for box in labels if box]
    for index, plan in by_index.items():
        link = plan[1]
        others = [box for k, box in enumerate(obstacles) if k not in (link.start, link.end)]
        before = crossings(index)
        for _ in range(4):
            better = _unjog(routes[index])
            if better is None:
                break
            segments = list(zip(better, better[1:]))
            if (any(_through(a, b, box) for a, b in segments[1:-1] for box in others)
                    or any(_along(a, b, c, d) for a, b in segments for k, route in routes.items() if k != index
                           and not ends[index] & ends[k] for c, d in zip(route, route[1:]))):
                break
            old = routes[index]
            mark(old, -1)
            routes[index] = better
            mark(better)
            if crossings(index) > before:
                mark(better, -1)
                routes[index] = old
                mark(old)
                break
    return routes


def _unjog(points):
    """The polyline with its first short jog (a few cells between two runs that go the same way) taken out:
    the run after the jog moves onto the line of the run before it. None when it has no such jog."""

    for i in range(len(points) - 3):
        a, b, c, d = points[i], points[i + 1], points[i + 2], points[i + 3]
        if math.dist(b, c) > JOG or math.dist(b, c) < 1e-6:
            continue
        level = abs(a[1] - b[1]) < 1e-6 and abs(c[1] - d[1]) < 1e-6           # two level runs, an upright jog
        upright = abs(a[0] - b[0]) < 1e-6 and abs(c[0] - d[0]) < 1e-6
        if not (level or upright):
            continue
        if level and (b[0] - a[0]) * (d[0] - c[0]) <= 0 or upright and (b[1] - a[1]) * (d[1] - c[1]) <= 0:
            continue                                            # a U, not a jog
        if i + 3 == len(points) - 1:
            continue                                            # the run after it ends on a port: it cannot move
        moved = (d[0], a[1]) if level else (a[0], d[1])
        return _simplify(points[:i + 1] + [moved] + points[i + 4:])
    return None


def _direct(s, n1, e, n2, boxes, routes):
    """A straight line, one dogleg or one corner between two ports that face the right way, when it runs clear
    of the other symbols and off the routes already drawn; otherwise None."""

    dx, dy = e[0] - s[0], e[1] - s[1]
    if n1 == (-n2[0], -n2[1]) and dx * n1[0] + dy * n1[1] > 0:          # the ports face each other
        if n1[0]:
            if abs(dy) < IN_LINE:
                points = [s, e]
            else:
                mid = s[0] + dx / 2.0
                points = [s, (mid, s[1]), (mid, e[1]), e]
        elif abs(dx) < IN_LINE:
            points = [s, e]
        else:
            mid = s[1] + dy / 2.0
            points = [s, (s[0], mid), (e[0], mid), e]
    elif n1[0] * n2[0] + n1[1] * n2[1] == 0:                            # square to each other: one corner
        corner = (e[0], s[1]) if n1[0] else (s[0], e[1])
        if ((corner[0] - s[0]) * n1[0] + (corner[1] - s[1]) * n1[1] <= 0
                or (corner[0] - e[0]) * n2[0] + (corner[1] - e[1]) * n2[1] <= 0):
            return None
        points = [s, corner, e]
    else:
        return None
    segments = list(zip(points, points[1:]))
    if any(_through(a, b, box) for a, b in segments for box in boxes):
        return None
    if any(_along(a, b, c, d) for a, b in segments for route in routes for c, d in zip(route, route[1:])):
        return None
    return points


def _guided(s, n1, e, n2, guide, boxes, own, routes):
    """One dogleg between two ports that face each other, its cross run where the guide makes its first turn
    toward the far port, when it runs clear of the other symbols and of its own two parts (see _through_own) and
    off the routes already drawn; otherwise None. A guide that runs away from the far port makes a detour the
    dogleg would drop, and gets none."""

    dx, dy = e[0] - s[0], e[1] - s[1]
    if n1 != (-n2[0], -n2[1]) or dx * n1[0] + dy * n1[1] <= 0:
        return None
    axis = 0 if n1[0] else 1                                    # the coordinate the cross run sits at
    other = 1 - axis
    if abs(e[other] - s[other]) < IN_LINE:
        return None                                             # in line: _direct draws it straight
    # the first run across, longer than a jog and toward the far port; a 2D bend squared onto the page can lean
    # a little
    across = [(a, b) for a, b in zip(guide, guide[1:]) if abs(a[axis] - b[axis]) < PITCH and abs(b[other] - a[other]) > JOG]
    if any((b[other] - a[other]) * (e[other] - s[other]) < 0 for a, b in across):
        return None
    at = next(((a[axis] + b[axis]) / 2.0 for a, b in across if (b[other] - a[other]) * (e[other] - s[other]) > 0), None)
    if at is None or (at - s[axis]) * n1[axis] < LEAD or (e[axis] - at) * n1[axis] < LEAD:
        return None
    if axis == 0:
        points = [s, (at, s[1]), (at, e[1]), e]
    else:
        points = [s, (s[0], at), (e[0], at), e]
    segments = list(zip(points, points[1:]))
    if any(_through(a, b, box) for a, b in segments for box in boxes) or _through_own(segments, own):
        return None
    if any(_along(a, b, c, d) for a, b in segments for route in routes for c, d in zip(route, route[1:])):
        return None
    return points


def _as_drawn(s, n1, e, n2, guide, boxes, own, routes):
    """The guide itself, when every run of it is square, it leaves and meets its ports the way they face, it runs
    clear of the other symbols and of its own two parts (see _through_own) and off the routes already drawn;
    otherwise None."""

    points = _simplify(guide)
    segments = list(zip(points, points[1:]))
    if len(segments) < 2 or any(abs(a[0] - b[0]) > 1e-6 and abs(a[1] - b[1]) > 1e-6 for a, b in segments):
        return None
    (a, b), (c, d) = segments[0], segments[-1]
    if (b[0] - a[0]) * n1[0] + (b[1] - a[1]) * n1[1] < LEAD or (c[0] - d[0]) * n2[0] + (c[1] - d[1]) * n2[1] < LEAD:
        return None
    if any(_through(a, b, box) for a, b in segments for box in boxes) or _through_own(segments, own):
        return None
    if any(_along(a, b, c, d) for a, b in segments for route in routes for c, d in zip(route, route[1:])):
        return None
    return points


def _through_own(segments, own):
    """A run enters one of the link's own two parts (start, end) where it should not: only the first run may
    leave the start part and only the last run may enter the end part (either, for a link from a part to
    itself)."""

    start, end = own
    last = len(segments) - 1
    for k, (a, b) in enumerate(segments):
        for box, free in ((start, k == 0), (end, k == last)):
            if start == end:
                free = k in (0, last)
            if not free and _through(a, b, box):
                return True
    return False


def _corner_count(points):
    """How many times the polyline turns."""

    return sum(1 for a, b, c in zip(points, points[1:], points[2:])
               if abs((b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])) > 1e-6)


def _through(a, b, box):
    """An axis-aligned segment enters the box (grown by CLEAR)."""

    x0, y0, x1, y1 = box[0] - CLEAR, box[1] - CLEAR, box[2] + CLEAR, box[3] + CLEAR
    return min(a[0], b[0]) < x1 and max(a[0], b[0]) > x0 and min(a[1], b[1]) < y1 and max(a[1], b[1]) > y0


def _along(a, b, c, d):
    """Two axis-aligned segments run on the same track (within a grid cell) for more than a cell."""

    if abs(a[1] - b[1]) < 1e-6 and abs(c[1] - d[1]) < 1e-6 and abs(a[1] - c[1]) < PITCH:
        lo, hi = max(min(a[0], b[0]), min(c[0], d[0])), min(max(a[0], b[0]), max(c[0], d[0]))
        return hi - lo > PITCH
    if abs(a[0] - b[0]) < 1e-6 and abs(c[0] - d[0]) < 1e-6 and abs(a[0] - c[0]) < PITCH:
        lo, hi = max(min(a[1], b[1]), min(c[1], d[1])), min(max(a[1], b[1]), max(c[1], d[1]))
        return hi - lo > PITCH
    return False


def _met_from(guide, s, e, port, symbol, link, normal, *, first):
    """The direction a cable leaves an electrode inside a part: along the first run of its 2D route at that end,
    when the route leaves it level (as a cable to a bar of a modulator does); otherwise ``normal``."""

    from .schematic import _inside

    if not (link.electrical and port is not None and _inside(symbol, port)) or len(guide) < 2:
        return normal
    near_start = math.dist(guide[0], s) + math.dist(guide[-1], e) <= math.dist(guide[0], e) + math.dist(guide[-1], s)
    ordered = guide if near_start == first else guide[::-1]
    a, b = ordered[0], ordered[1]
    dx, dy = b[0] - a[0], b[1] - a[1]
    if abs(dx) > 2.0 * abs(dy) and abs(dx) > 1e-6:
        return (1 if dx > 0 else -1, 0)
    return normal


def _trim(path, length):
    """The polyline without its first and last ``length`` of run; empty when nothing is left."""

    def cut(points):
        left = length
        for i, (a, b) in enumerate(zip(points, points[1:])):
            run = math.dist(a, b)
            if run > left:
                t = left / run
                return [(a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)] + points[i + 1:]
            left -= run
        return []

    head = cut(list(path))
    return cut(head[::-1])[::-1] if head else []


def _onto_ports(guide, s, e, n1=None, n2=None, inside=(False, False)):
    """The guide ending on the ports as drawn: the run that approaches each port (level for a port on a side,
    upright for one on the top or bottom) moves over to the port's line, with all of the guide past it, so a
    route turns once at the guide's corner, not again just before the port. At an electrode inside a part
    (``inside``), the lane before that run moves with the port too: the symbol puts its electrodes elsewhere
    than the 2D part does, and the lane keeps its gap to the contact."""

    guide = list(guide)
    if math.dist(guide[0], e) + math.dist(guide[-1], s) < math.dist(guide[0], s) + math.dist(guide[-1], e):
        guide.reverse()                                         # a 2D route may run the other way
    steady = [all(a[k] <= b[k] + 1e-6 for a, b in zip(guide, guide[1:]))
              or all(a[k] >= b[k] - 1e-6 for a, b in zip(guide, guide[1:])) for k in (0, 1)]

    def approach(points, port, normal, carry):
        axis = 1 if normal is None or normal[0] else 0          # the coordinate a level (or upright) run shares
        other = 1 - axis
        shift = port[other] - points[-1][other]                # how far the port sits from the guide's end
        for i in range(len(points) - 1, 0, -1):
            if abs(points[i][axis] - points[i - 1][axis]) < 1e-6:
                for k in range(i - 1, len(points)):
                    points[k] = tuple(port[axis] if j == axis else v for j, v in enumerate(points[k]))
                if carry and i >= 2:                            # the lane before it keeps its 2D gap to the port
                    for k in (i - 2, i - 1):
                        points[k] = tuple(v + shift if j == other else v for j, v in enumerate(points[k]))
                break
        points[-1] = port
        return points

    guide = approach(guide, e, n2, inside[1])
    guide = approach(guide[::-1], s, n1, inside[0])[::-1]
    for k in (0, 1):                                            # a route that only rises stays between its ends
        if steady[k]:
            low, high = sorted((s[k], e[k]))
            guide[1:-1] = [tuple(min(max(v, low), high) if j == k else v for j, v in enumerate(point))
                           for point in guide[1:-1]]
    return guide


def _keeps_near(points, near, cell, width, reach) -> bool:
    """Every point along the polyline that lies within the guide's reach is on the guide (a cell off at most);
    the leads at its ends, and the free zones near its ports, do not count."""

    ends = (points[0], points[-1])
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        steps = max(1, int(math.dist((x0, y0), (x1, y1)) / PITCH))
        for k in range(steps + 1):
            x, y = x0 + (x1 - x0) * k / steps, y0 + (y1 - y0) * k / steps
            if min(math.dist((x, y), end) for end in ends) <= LEAD + PITCH:
                continue
            if not (reach[0] <= x <= reach[2] and reach[1] <= y <= reach[3]):
                continue
            cx, cy = cell(x, y)
            if near.get(cy * width + cx, NEAR + 1) > 1:             # on its guide, within a cell
                return False
    return True


def _astar(a, b, first, last, width, height, closed, used_h, used_v, near=None, opened=frozenset()):
    """The cheapest grid path from cell ``a`` (leaving along ``first``) to ``b`` (arriving along ``last``).
    Cells in ``opened`` are free although a symbol covers them."""

    def free(c):
        if not (0 <= c[0] < width and 0 <= c[1] < height):
            return False
        k = c[1] * width + c[0]
        return not closed[k] or k in opened or c in (a, b)

    if not free(a) or not free(b):
        return None
    for end in (a, b):                                          # an end boxed in on all four sides: no way out
        if not any(free((end[0] + dx, end[1] + dy)) for dx, dy in _STEPS):
            return None
    start = (a, first)
    best = {start: 0.0}
    came: dict[Any, Any] = {}
    queue = [(abs(a[0] - b[0]) + abs(a[1] - b[1]), 0.0, start)]
    limit = SEARCH + 40 * (abs(a[0] - b[0]) + abs(a[1] - b[1]))   # a boxed-in end must not search the whole page
    while queue and limit:
        limit -= 1
        _, cost, state = heapq.heappop(queue)
        here, heading = state
        if here == b:
            if heading != last:                                 # turn into the end port
                pass
            path = [here]
            while state in came:
                state = came[state]
                path.append(state[0])
            return _corners(path[::-1])
        if cost > best.get(state, math.inf):
            continue
        for step in _STEPS:
            if step == (-heading[0], -heading[1]):
                continue
            nxt = (here[0] + step[0], here[1] + step[1])
            if not free(nxt):
                continue
            k = nxt[1] * width + nxt[0]
            extra = 1.0
            if step != heading:
                extra += TURN
            along, across = (used_h, used_v) if step[1] == 0 else (used_v, used_h)
            if along[k]:
                extra += SHARE
            elif across[k]:
                extra += CROSS
            if nxt == b and step != last:
                extra += TURN
            if near is not None:
                off = near.get(k)
                extra += AWAY if off is None else OFF_GUIDE * off      # hug the guide: lanes keep their 2D order
            new = cost + extra
            state2 = (nxt, step)
            if new < best.get(state2, math.inf):
                best[state2] = new
                came[state2] = state
                heapq.heappush(queue, (new + abs(nxt[0] - b[0]) + abs(nxt[1] - b[1]), new, state2))
    return None


def _corners(cells):
    """Only the cells where the path turns, and its two ends."""

    if len(cells) <= 2:
        return cells
    out = [cells[0]]
    for prev, here, nxt in zip(cells, cells[1:], cells[2:]):
        if (here[0] - prev[0], here[1] - prev[1]) != (nxt[0] - here[0], nxt[1] - here[1]):
            out.append(here)
    out.append(cells[-1])
    return out


def _cells_between(x0, y0, x1, y1):
    if x0 == x1:
        for cy in range(min(y0, y1), max(y0, y1) + 1):
            yield x0, cy
    else:
        for cx in range(min(x0, x1), max(x0, x1) + 1):
            yield cx, y0


def _snap_ends(points):
    """Keep the leads square: the grid point next to each lead takes the lead's line."""

    if len(points) < 4:
        return points
    pts = list(points)
    for i, j in ((1, 2), (-2, -3)):
        a, b = pts[i], pts[j]
        if abs(a[0] - b[0]) < abs(a[1] - b[1]):
            pts[j] = (a[0], b[1])
        else:
            pts[j] = (b[0], a[1])
    return pts


def _simplify(points):
    out = [points[0]]
    for p in points[1:]:
        if math.dist(p, out[-1]) < 1e-6:
            continue
        if len(out) >= 2:
            (ax, ay), (bx, by) = out[-2], out[-1]
            if abs((bx - ax) * (p[1] - by) - (by - ay) * (p[0] - bx)) < 1e-6:
                out[-1] = p
                continue
        out.append(p)
    return out


def rounded_path(points: list[tuple[float, float]], radius: float = CORNER) -> str:
    """SVG path data for a polyline with its corners rounded; a radius of 0 keeps them square."""

    points = [point for k, point in enumerate(points)          # a repeated point has no run to round a corner on
              if k == 0 or math.dist(point, points[k - 1]) > 1e-9]
    if len(points) < 3 or radius <= 0:
        return "M" + " L".join(f"{x:.2f} {y:.2f}" for x, y in points)
    d = f"M{points[0][0]:.2f} {points[0][1]:.2f}"
    for a, b, c in zip(points, points[1:], points[2:]):
        la, lb = math.dist(a, b), math.dist(b, c)
        r = min(radius, la / 2.0, lb / 2.0)
        p = (b[0] + (a[0] - b[0]) * r / la, b[1] + (a[1] - b[1]) * r / la)
        q = (b[0] + (c[0] - b[0]) * r / lb, b[1] + (c[1] - b[1]) * r / lb)
        d += f" L{p[0]:.2f} {p[1]:.2f} Q{b[0]:.2f} {b[1]:.2f} {q[0]:.2f} {q[1]:.2f}"
    return d + f" L{points[-1][0]:.2f} {points[-1][1]:.2f}"
