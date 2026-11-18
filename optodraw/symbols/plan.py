"""A chip's 1D view drawn as its 2D plan: the same arrangement, closed up, with each 2D route as the guide of
its 1D route.

Each axis is mapped on its own by a rising piecewise-linear function. A part's 2D span grows or shrinks to its
symbol, an empty band shrinks to a few points, and two parts side by side keep a small gap. A rising map keeps
the order of every part and every route vertex, so a route that runs round the parts in 2D runs round them in
1D.
"""

from __future__ import annotations

import math
from bisect import bisect_right
from statistics import median
from typing import Any

GAP_MIN = 4.0        # an empty band in 1D: room for one track
GAP_MAX = 10.0       # never wider than this
SQUEEZE = 0.05       # a part's span starts this short, then grows to fit its symbol
SIDE_GAP = 6.0       # two parts side by side stay this far apart
TRACK = 5.0          # the room one route needs to run through a band (two grid cells)
LINE_GAP = 2.0       # parts that slide into line keep this far from the others
NEAR_COLUMN = 40.0   # two columns closer than this keep their parts' 2D order when the 1D closes up
LINE_SHIFT = 40.0    # and slide no further than this
LEAF_SHIFT = 80.0    # a part with one link (a detector, a coupler, a pad) slides up to this
HAIR = 0.01          # the band left between two parts that touch in 2D
IN_LINE_2D = 2.0     # two ports this close to one line in 2D (um) line up in 1D


class AxisMap:
    """A rising piecewise-linear map from a 2D coordinate to a 1D one."""

    def __init__(self, xs: list[float], ys: list[float]):
        self.xs, self.ys = xs, ys

    def __call__(self, x: float) -> float:
        xs, ys = self.xs, self.ys
        if x <= xs[0]:
            return ys[0] - min(xs[0] - x, GAP_MAX)
        if x >= xs[-1]:
            return ys[-1] + min(x - xs[-1], GAP_MAX)
        i = bisect_right(xs, x) - 1
        span = xs[i + 1] - xs[i]
        return ys[i] + (ys[i + 1] - ys[i]) * ((x - xs[i]) / span if span else 0.0)


def axis_map(spans: list[tuple[float, float, float]], gaps: list[tuple[float, float, float]],
             lanes: list[float], ends: list[float], start: float) -> AxisMap:
    """``spans``: (low, high, length it needs) per part; ``gaps``: (low, high, length it needs) between parts
    side by side; ``lanes``: where routes run across this axis, each needing a track in the band it is in;
    ``ends``: the outermost route points, so a route round the outside keeps its band. The map starts at
    ``start``."""

    lane_set = {round(lane, 3) for lane in lanes}
    xs = sorted({value for low, high, _ in spans for value in (low, high)} | set(ends) | lane_set)
    if len(xs) < 2:
        xs = [xs[0] if xs else 0.0, (xs[0] if xs else 0.0) + 1.0]
    covered = [any(low <= a and b <= high for low, high, _ in spans) for a, b in zip(xs, xs[1:])]
    lengths = [0.0] * len(covered)
    i = 0
    while i < len(covered):                  # an empty band: short, with its lanes evenly spaced a track apart
        if covered[i]:
            a, b = xs[i], xs[i + 1]
            lengths[i] = (b - a) * SQUEEZE
            if round(a, 3) in lane_set and round(b, 3) in lane_set:
                lengths[i] = max(lengths[i], TRACK)          # two lanes across a part keep a track between them
            i += 1
            continue
        j = i
        while j < len(covered) and not covered[j]:
            j += 1
        span = xs[j] - xs[i]
        band = max(min(max(span, GAP_MIN), GAP_MAX), (j - i) * TRACK)
        for k in range(i, j):
            lengths[k] = band / (j - i)
        i = j
    # each a lower bound on a sum: one pass holds when the inner ones come first (a pad's band before the band of
    # the part round it), so the part round it counts the room the inner ones took
    for low, high, need in sorted(list(spans) + list(gaps), key=lambda item: item[1] - item[0]):
        inside = [i for i, (a, b) in enumerate(zip(xs, xs[1:])) if low <= a and b <= high]
        if not inside:
            continue
        have = sum(lengths[i] for i in inside)
        if have < need:
            weight = sum(xs[i + 1] - xs[i] for i in inside)
            for i in inside:
                share = (xs[i + 1] - xs[i]) / weight if weight else 1.0 / len(inside)
                lengths[i] += (need - have) * share
    ys = [start]
    for length in lengths:
        ys.append(ys[-1] + length)
    return AxisMap(xs, ys)


def _untangle(boxes: list[tuple[float, float, float, float]]) -> list[tuple[float, float, float, float]]:
    """Two boxes that overlap a little (a coupler's taper over the part it feeds), or touch, meet at the middle
    of the overlap with a hair between them, along the axis where they overlap less: then they are side by side
    and keep a gap."""

    boxes = [list(box) for box in boxes]
    for i, a in enumerate(boxes):
        for b in boxes[i + 1:]:
            w = min(a[2], b[2]) - max(a[0], b[0])
            h = min(a[3], b[3]) - max(a[1], b[1])
            if w < 0 or h < 0 or (w == 0 and h == 0):
                continue
            axis = 0 if w <= h else 1
            first, second = (a, b) if a[axis] + a[axis + 2] <= b[axis] + b[axis + 2] else (b, a)
            middle = (second[axis] + first[axis + 2]) / 2.0
            if first[axis] < middle < second[axis + 2]:           # touching parts too: a band between them
                first[axis + 2] = middle - HAIR
                second[axis] = middle + HAIR
    return [tuple(box) for box in boxes]


def _side_gaps(boxes: list[tuple[float, float, float, float]], axis: int) -> list[tuple[float, float, float]]:
    """For each part, the gap to its nearest neighbour beside it along ``axis`` (0: x, 1: y)."""

    other = 1 - axis
    gaps = []
    for i, a in enumerate(boxes):
        nearest = None
        for j, b in enumerate(boxes):
            if i == j or b[axis] < a[axis + 2]:
                continue
            if a[other] < b[other + 2] and b[other] < a[other + 2]:     # beside each other, not one over the other
                if nearest is None or b[axis] < nearest:
                    nearest = b[axis]
        if nearest is not None and nearest > a[axis + 2]:
            gaps.append((a[axis + 2], nearest, SIDE_GAP))
    return gaps


def plan_layout(parts: list[Any], symbols: list[Any], labels: list[str], edges: list[tuple],
                guides: dict[int, list[tuple[float, float]]], margin: float,
                footprint, room) -> tuple[list[tuple[float, float]], dict[int, list[tuple[float, float]]]]:
    """Each part's place in 1D, and each 2D route mapped to 1D, from the parts' 2D boxes and ports.

    ``footprint(symbol, label)`` and ``room(symbol, label)`` give the width a part needs and the label room over
    and under it. A 2D y grows upward; a 1D y grows downward.
    """

    world = [part.drawn_box() for part in parts]
    boxes = _untangle([(x0, -y1, x1, -y0) for x0, y0, x1, y1 in world])   # 1D sense: y down
    widths = [footprint(symbol, label) for symbol, label in zip(symbols, labels)]
    heights = [sum(room(symbol, label)) + symbol.height for symbol, label in zip(symbols, labels)]
    paths = [[(x, -y) for x, y in square(points)] for points in guides.values()]
    lanes_x = [a[0] for path in paths for a, b in zip(path, path[1:]) if abs(a[0] - b[0]) < 1e-6]   # vertical runs
    lanes_y = [a[1] for path in paths for a, b in zip(path, path[1:]) if abs(a[1] - b[1]) < 1e-6]
    ends_x = [f(x for path in paths for x, _ in path) for f in (min, max)] if paths else []
    ends_y = [f(y for path in paths for _, y in path) for f in (min, max)] if paths else []
    map_x = axis_map([(b[0], b[2], w) for b, w in zip(boxes, widths)], _side_gaps(boxes, 0), lanes_x, ends_x, margin)
    map_y = axis_map([(b[1], b[3], h) for b, h in zip(boxes, heights)], _side_gaps(boxes, 1), lanes_y, ends_y, margin)

    linked: dict[int, set[str]] = {}
    partners: dict[int, list[tuple[str, int, str]]] = {}
    for start, start_port, end, end_port, _ in edges:
        linked.setdefault(start, set()).add(start_port)
        linked.setdefault(end, set()).add(end_port)
        partners.setdefault(start, []).append((start_port, end, end_port))
        partners.setdefault(end, []).append((end_port, start, start_port))
    world_ports = [part.world_ports() for part in parts]

    def runs_straight(index: int, name: str, axis: int) -> bool:
        """A link from this port runs straight in 2D: level with its partner (axis 1) or plumb (axis 0)."""

        mine = world_ports[index][name].center
        for own, other, theirs in partners.get(index, ()):
            far = world_ports[other].get(theirs)
            if own == name and far is not None:
                a, b = (float(mine.x), float(mine.y)), (float(far.center.x), float(far.center.y))
                if abs(a[axis] - b[axis]) <= IN_LINE_2D < abs(a[1 - axis] - b[1 - axis]):
                    return True
        return False

    spots = []
    for index, (part, symbol, label, box) in enumerate(zip(parts, symbols, labels, boxes)):
        x0, x1 = map_x(box[0]), map_x(box[2])
        y0, y1 = map_y(box[1]), map_y(box[3])
        side = (widths[index] - symbol.width) / 2.0
        above, below = room(symbol, label)
        ports = part.world_ports()
        names = [name for name in linked.get(index, ()) if name in ports and name in symbol.ports]
        if names:                                   # the symbol's ports where the 2D ports land
            # a straight 2D link sets the place first: both its ends map to one level, so it stays straight
            plumb = [n for n in names if runs_straight(index, n, 0)] or names
            level = [n for n in names if runs_straight(index, n, 1)] or names
            want_x = median(map_x(float(ports[n].center.x)) - symbol.ports[n].x for n in plumb)
            want_y = median(map_y(-float(ports[n].center.y)) - symbol.ports[n].y for n in level)
        else:
            want_x = (x0 + x1 - symbol.width) / 2.0
            want_y = (y0 + y1 - symbol.height) / 2.0
        x = min(max(want_x, x0 + side), max(x0 + side, x1 - side - symbol.width))
        y = min(max(want_y, y0 + above), max(y0 + above, y1 - below - symbol.height))
        spots.append((x, y))
    mapped = {index: [(map_x(x), map_y(-y)) for x, y in square(points)] for index, points in guides.items()}
    spots, over = _line_up(parts, symbols, labels, edges, spots, footprint, room)
    spots, mapped = _compact_up(symbols, labels, edges, spots, over, mapped, footprint, room)
    left = min([x - (w - symbol.width) / 2.0 for (x, _), w, symbol in zip(spots, widths, symbols)]
               + [x for path in mapped.values() for x, _ in path])
    top = min([y - (sum(room(symbol, label)) if i in over else room(symbol, label)[0])
               for i, ((_, y), symbol, label) in enumerate(zip(spots, symbols, labels))]
              + [y for path in mapped.values() for _, y in path])
    dx, dy = margin - left, margin - top          # the page starts at the margin, whatever slid into line
    spots = [(x + dx, y + dy) for x, y in spots]
    mapped = {index: [(x + dx, y + dy) for x, y in path] for index, path in mapped.items()}
    return spots, mapped, over


def _compact_up(symbols: list[Any], labels: list[str], edges: list[tuple], spots: list[tuple[float, float]],
                over: set[int], mapped: dict[int, list[tuple[float, float]]], footprint, room
                ) -> tuple[list[tuple[float, float]], dict[int, list[tuple[float, float]]]]:
    """Close the empty space the page-wide height map leaves in a column: a tall symbol in one column (a
    splitter, an AWG) stretches its band in every column. Each row of parts joined by straight level links
    rises until it meets the part over it in its own column, with a track for each route that runs between them;
    a part never rises past a part it links to or past a part wholly over it in a column close by (the 2D's order
    holds), and a part that overlaps the one over it moves down clear of it.
    A row with nothing over it and no link from above stays. The 2D routes on the page move with the parts."""

    count = len(symbols)
    if count < 2:
        return spots, mapped

    def port(i: int, name: str) -> tuple[float, float] | None:
        p = symbols[i].ports.get(name)
        return None if p is None else (spots[i][0] + p.x, spots[i][1] + p.y)

    group = list(range(count))                                  # union-find over straight level links

    def find(i: int) -> int:
        while group[i] != i:
            group[i] = group[group[i]]
            i = group[i]
        return i

    for start, start_port, end, end_port, _ in edges:            # a level link, or one a jog off level: one row
        a, b = port(start, start_port), port(end, end_port)
        if a and b and abs(a[1] - b[1]) < 2.0 * TRACK and abs(a[0] - b[0]) > 0.5:
            group[find(start)] = find(end)
    boxes = []
    for i, (symbol, label) in enumerate(zip(symbols, labels)):
        above, below = room(symbol, label)
        if i in over:
            above, below = below, above
        side = (footprint(symbol, label) - symbol.width) / 2.0
        x, y = spots[i]
        boxes.append((x - side, y - above, x + symbol.width + side, y + symbol.height + below))
    roots = sorted({find(i) for i in range(count)})
    members = {r: [i for i in range(count) if find(i) == r] for r in roots}
    top = {r: min(boxes[i][1] for i in members[r]) for r in roots}
    runs = [(a, b) for path in mapped.values() for a, b in zip(path, path[1:]) if abs(a[1] - b[1]) < 0.5]

    def lanes(x0: float, x1: float, y0: float, y1: float) -> int:     # level route runs between two boxes
        return sum(1 for a, b in runs if y0 < a[1] < y1 and min(a[0], b[0]) < x1 and max(a[0], b[0]) > x0)

    rules: list[tuple[int, int, float]] = []                     # (upper, lower, least drop of the lower top)
    for h in roots:
        for g in roots:
            if h == g:
                continue
            for i in members[h]:
                for j in members[g]:
                    a, b = boxes[i], boxes[j]
                    if a[3] <= b[1] + 0.5 and not (a[0] < b[2] - LINE_GAP and b[0] < a[2] - LINE_GAP):
                        # wholly over it in a column close by: it stays over it, so the 1D reads in the 2D's
                        # order (a part in a column of its own, a splitter or an AWG, stretches no row)
                        if max(a[0], b[0]) - min(a[2], b[2]) < NEAR_COLUMN:
                            rules.append((h, g, a[3] + LINE_GAP - top[h] - (b[1] - top[g])))
                        continue
                    if not (a[0] < b[2] - LINE_GAP and b[0] < a[2] - LINE_GAP):
                        continue                                 # not in one column
                    if a[1] + a[3] >= b[1] + b[3] or a[3] - b[1] > 0.5 * min(a[3] - a[1], b[3] - b[1]):
                        continue                                 # not over it
                    crossing = lanes(min(a[0], b[0]), max(a[2], b[2]), a[3], b[1])
                    # a track for each route that runs between them, and one to spare, so the router can keep them
                    # apart; a gap only closes, it never opens past what it was
                    gap = GAP_MIN + LINE_GAP + (TRACK * (crossing + 1) if crossing else 0.0)
                    if b[1] - a[3] >= 0.0:
                        gap = min(gap, b[1] - a[3])
                    rules.append((h, g, a[3] + gap - top[h] - (b[1] - top[g])))
    for start, start_port, end, end_port, _ in edges:
        h, g = find(start), find(end)
        a, b = port(start, start_port), port(end, end_port)
        if h == g or not a or not b or abs(a[0] - b[0]) < 0.5:
            continue                                             # a plumb link: the column rule keeps it
        if b[1] < a[1]:
            (h, a), (g, b) = (g, b), (h, a)
        drop = min(b[1] - a[1], 3.0 * TRACK)
        if drop > 0.5:
            rules.append((h, g, (a[1] - top[h]) + drop - (b[1] - top[g])))
    bound = {g for _, g, _ in rules}
    new = {r: (top[r] if r not in bound else -math.inf) for r in roots}
    for _ in range(2):                                           # a group held only by a loop of rules stays,
        for _ in range(len(roots) + 2):                          # and the groups under it move from there
            changed = False
            for h, g, least in rules:
                if new[h] > -math.inf and new[h] + least > new[g] + 1e-9:
                    new[g] = new[h] + least
                    changed = True
            if not changed:
                break
        else:
            return spots, mapped                                 # rules that loop: leave the page as it is
        new = {r: (top[r] if v == -math.inf else v) for r, v in new.items()}
    shift = {r: (new[r] - top[r] if new[r] > -math.inf else 0.0) for r in roots}
    if all(abs(value) < 1e-6 for value in shift.values()):
        return spots, mapped                                     # nothing closed up: the routes stay as mapped
    moved = [(x, y + shift[find(i)]) for i, (x, y) in enumerate(spots)]

    new_boxes = [(b[0], b[1] + shift[find(i)], b[2], b[3] + shift[find(i)]) for i, b in enumerate(boxes)]

    def holder(x: float, y: float) -> float | None:              # the shift of the part a route point sits in
        for i, b in enumerate(boxes):
            if b[0] - 0.5 <= x <= b[2] + 0.5 and b[1] - 0.5 <= y <= b[3] + 0.5:
                return shift[find(i)]
        return None

    def level(x0: float, x1: float, y: float) -> float:          # a level run keeps its place between its neighbours
        beside = [i for i, b in enumerate(boxes) if b[0] < x1 and b[2] > x0 and b[1] < y < b[3]]
        if beside:                                               # or, level with a part, moves with it
            return y + shift[find(min(beside, key=lambda i: min(abs(boxes[i][0] - x1), abs(boxes[i][2] - x0))))]
        over_it = [i for i, b in enumerate(boxes) if b[0] < x1 and b[2] > x0 and b[3] <= y]
        under_it = [i for i, b in enumerate(boxes) if b[0] < x1 and b[2] > x0 and b[1] >= y]
        if over_it and under_it:
            a, a2 = max(boxes[i][3] for i in over_it), max(new_boxes[i][3] for i in over_it)
            b, b2 = min(boxes[i][1] for i in under_it), min(new_boxes[i][1] for i in under_it)
            t = min(max((y - a) / (b - a), 0.0), 1.0) if b > a else 0.5
            return a2 + t * (b2 - a2)
        if over_it:
            return y + max(new_boxes[i][3] for i in over_it) - max(boxes[i][3] for i in over_it)
        if under_it:
            return y + min(new_boxes[i][1] for i in under_it) - min(boxes[i][1] for i in under_it)
        return None                                              # an empty column: the route's ends decide

    paths = {}
    for index, path in mapped.items():
        ys = [None] * len(path)
        for end in (0, len(path) - 1):                           # its ends move with the parts they meet
            s = holder(*path[end])
            ys[end] = path[end][1] + (s if s is not None else 0.0)
        steps = [0.0] + [abs(b[0] - a[0]) + abs(b[1] - a[1]) for a, b in zip(path, path[1:])]
        along = [sum(steps[:n + 1]) for n in range(len(path))]
        first, last = ys[0] - path[0][1], ys[-1] - path[-1][1]

        def between(n: int) -> float:                            # the ends' shifts, in proportion along the route
            return first + (last - first) * (along[n] / along[-1] if along[-1] else 0.0)
        k = 0
        while k < len(path) - 1:                                 # each level run, ends included, as one
            j = k
            while j + 1 < len(path) and abs(path[j + 1][1] - path[k][1]) < 0.5:
                j += 1
            if j > k:
                fixed = [ys[n] for n in (k, j) if ys[n] is not None and n in (0, len(path) - 1)]
                y = fixed[0] if fixed else level(min(p[0] for p in path[k:j + 1]), max(p[0] for p in path[k:j + 1]),
                                                 path[k][1])
                if y is None:
                    y = path[k][1] + between(k)
                for n in range(k, j + 1):
                    ys[n] = y
            k = max(j, k + 1)
        for n, y in enumerate(ys):
            if y is None:
                s = holder(*path[n])
                ys[n] = path[n][1] + (s if s is not None else between(n))
        unmoved = all(abs(y - p[1]) < 1e-6 for p, y in zip(path, ys))
        paths[index] = list(path) if unmoved else square([(x, y) for (x, _), y in zip(path, ys)])
    return moved, paths


def _same_row(a: Any, b: Any) -> bool:
    """Two parts side by side in one 2D row: their centres level, their boxes apart by less than one box."""

    (ax0, ay0, ax1, ay1), (bx0, by0, bx1, by1) = a.drawn_box(), b.drawn_box()
    level = abs((ay0 + ay1) - (by0 + by1)) / 2.0 <= IN_LINE_2D
    near = max(ax0, bx0) - min(ax1, bx1) < min(ax1 - ax0, bx1 - bx0)
    return level and near


def _line_up(parts: list[Any], symbols: list[Any], labels: list[str], edges: list[tuple],
             spots: list[tuple[float, float]], footprint, room) -> tuple[list[tuple[float, float]], set[int]]:
    """A part fed from one other part slides so its port lines up with the port that feeds it, where the two
    ports line up in 2D: the link runs straight in 1D as in 2D. It never passes another part on the way. A row
    of pads under (or over) a part goes straight under its contacts, in two staggered rows when one row does
    not fit, as on a chip. Also returns the parts whose label must go to the other side to make room."""

    from .schematic import _inside

    spots = list(spots)
    count = len(symbols)
    over: set[int] = set()

    def box(i: int, x: float, y: float, flip: bool = False) -> tuple[float, float, float, float]:
        symbol, label = symbols[i], labels[i]
        above, below = room(symbol, label)
        if flip:
            above, below = below, above
        side = (footprint(symbol, label) - symbol.width) / 2.0
        return (x - side, y - above, x + symbol.width + side, y + symbol.height + below)

    def clear(i: int, x: float, y: float, skip: set[int]) -> bool:
        """No other part within reach of the part, from where it is to where it goes; its label may go to the
        other side of the part, and is then marked to."""

        for flip in (False, True):
            start, end = box(i, *spots[i], flip), box(i, x, y, flip)
            a = (min(start[0], end[0]), min(start[1], end[1]), max(start[2], end[2]), max(start[3], end[3]))
            if not any(a[0] < b[2] + LINE_GAP and b[0] < a[2] + LINE_GAP and a[1] < b[3] + LINE_GAP
                       and b[1] < a[3] + LINE_GAP for b in (box(j, *spots[j], j in over) for j in range(count)
                                                            if j != i and j not in skip)):
                if flip and labels[i]:
                    over.add(i)
                else:
                    over.discard(i)
                return True
        return False

    def straight(i: int, own: str, host: int, theirs: str, axis: int) -> bool:
        """The two ports line up in 2D along ``axis`` (0: same x, 1: same y)."""

        mine, its = parts[i].world_ports().get(own), parts[host].world_ports().get(theirs)
        if mine is None or its is None:
            return False
        a, b = (mine.center.x, mine.center.y), (its.center.x, its.center.y)
        return abs(float(a[axis]) - float(b[axis])) <= IN_LINE_2D

    links: dict[int, list[tuple[str, int, str, bool]]] = {i: [] for i in range(count)}
    for a, a_port, b, b_port, kind in edges:
        electrical = "elect" in kind.lower()
        links[a].append((a_port, b, b_port, electrical))
        links[b].append((b_port, a, a_port, electrical))
    rows: dict[tuple[int, str], list[tuple[int, float]]] = {}
    for sweep in range(2):                                # a second sweep: a move the first one made room for
        for i in sorted(range(count), key=lambda k: len(links[k])):
            mine = [link for link in links[i] if not link[3]] or links[i]   # light first: a detector follows it
            leaves = {other for _, other, _, _ in links[i] if {o for _, o, _, _ in links[other]} == {i}}
            mine = [link for link in mine if link[1] not in leaves] or mine  # its own terminators do not feed it
            hosts = {other for _, other, _, _ in mine}
            if len(hosts) != 1:                     # a part in a chain lines up with the one link straight in 2D
                level = [link for link in mine if straight(i, link[0], link[1], link[2], 1)]
                if len({other for _, other, _, _ in level}) != 1:
                    continue
                mine, hosts = level, {level[0][1]}
            host = next(iter(hosts))
            if len(links[host]) <= len(links[i]):
                continue                                                   # the busier part stays where it is
            pairs = [(symbols[i].ports.get(own), symbols[host].ports.get(theirs), own, theirs)
                     for own, _, theirs, _ in mine]
            pairs = [(a, b, own, theirs) for a, b, own, theirs in pairs if a is not None and b is not None]
            if not pairs:
                continue
            if all(a.side in ("left", "right") and (b.side in ("left", "right") or _inside(symbols[host], b))
                   for a, b, _, _ in pairs):
                level = [(a, b) for a, b, own, theirs in pairs if straight(i, own, host, theirs, 1)]
                if not level:
                    continue                                               # the 2D route bends: so does the 1D
                y = median(spots[host][1] + b.y - a.y for a, b in level)
                reach = LEAF_SHIFT if len(links[i]) == 1 else LINE_SHIFT
                if abs(y - spots[i][1]) > reach:
                    continue
                # the parts in its 2D row that serve the same host (the other pad of a heater) come along, and
                # so do its own leaves (a terminator on a spare port)
                row = [j for j in range(count) if j != i and _same_row(parts[i], parts[j])
                       and {other for _, other, _, _ in links[j]} == {host}] + sorted(leaves)
                dy = y - spots[i][1]
                if clear(i, spots[i][0], y, set(row)) and all(clear(j, spots[j][0], spots[j][1] + dy, {i, *row})
                                                              for j in row):
                    for j in [i, *row]:
                        spots[j] = (spots[j][0], spots[j][1] + dy)
            elif (sweep == 0 and len(pairs) == 1 and pairs[0][0].side in ("top", "bottom")
                  and (pairs[0][1].side in ("top", "bottom") or _inside(symbols[host], pairs[0][1]))
                  and straight(i, pairs[0][2], host, pairs[0][3], 0)):
                a, b = pairs[0][:2]
                rows.setdefault((host, a.side), []).append((i, spots[host][0] + b.x - a.x))
    for (host, side), members in rows.items():
        members.sort(key=lambda member: member[1])
        down = side == "top"                                               # its port faces up: it hangs under
        near = (min if down else max)(spots[i][1] for i, _ in members)
        height = max(symbols[i].height for i, _ in members)
        levels = [near, near + (height + LINE_GAP) * (1 if down else -1)]
        ends = [-math.inf, -math.inf]
        placed = {}
        for i, x in members:
            row = next((r for r in (0, 1) if x >= ends[r] + LINE_GAP), None)
            if row is None:
                placed = {}
                break
            placed[i] = (x, levels[row])
            ends[row] = x + symbols[i].width
        group = {i for i, _ in members}
        if placed and all(clear(i, *spot, group | {host}) for i, spot in placed.items()):
            for i, spot in placed.items():
                spots[i] = spot
    return spots, over


def square(points: list[tuple[float, float]], tolerance: float = 1.0) -> list[tuple[float, float]]:
    """A route as square runs: its curve samples dropped (within ``tolerance``), and each slanted run that is
    left turned into a dogleg with its jog halfway, as a waveguide S-bend reads on a chip."""

    def keep(a: int, b: int) -> list[int]:                  # Douglas-Peucker
        (x0, y0), (x1, y1) = points[a], points[b]
        length = math.hypot(x1 - x0, y1 - y0) or 1e-9
        far, worst = -1, tolerance
        for i in range(a + 1, b):
            d = abs((x1 - x0) * (y0 - points[i][1]) - (x0 - points[i][0]) * (y1 - y0)) / length
            if d > worst:
                far, worst = i, d
        return [a, b] if far < 0 else keep(a, far)[:-1] + keep(far, b)

    if len(points) < 2:
        return list(points)
    kept = [points[i] for i in keep(0, len(points) - 1)]

    def heading(a, b):                                       # the way a slanted run goes; None for a level run
        dx, dy = b[0] - a[0], b[1] - a[1]
        if abs(dx) <= tolerance or abs(dy) <= tolerance:
            return None
        return (dx > 0, dy > 0)

    merged = [kept[0]]                                       # one bend of a curve, sampled as many runs: one run
    for point in kept[1:]:
        if len(merged) >= 2 and heading(merged[-2], merged[-1]) is not None \
                and heading(merged[-2], merged[-1]) == heading(merged[-1], point):
            merged[-1] = point
        else:
            merged.append(point)
    kept = merged
    out = [kept[0]]
    for (x0, y0), (x1, y1) in zip(kept, kept[1:]):
        if abs(x1 - x0) > tolerance and abs(y1 - y0) > tolerance:
            if abs(x1 - x0) >= abs(y1 - y0):
                mid = (x0 + x1) / 2.0
                out += [(mid, y0), (mid, y1)]
            else:
                mid = (y0 + y1) / 2.0
                out += [(x0, mid), (x1, mid)]
        out.append((x1, y1))
    return out


def plan_fits(parts: list[Any], overlap: float = 0.15) -> bool:
    """True when no two parts overlap in 2D by more than ``overlap`` of the smaller one: a plan that can be
    drawn as it stands. (A scene whose parts sit on each other gets the automatic arrangement.)"""

    boxes = [part.drawn_box() for part in parts]
    for i, a in enumerate(boxes):
        for b in boxes[i + 1:]:
            w = min(a[2], b[2]) - max(a[0], b[0])
            h = min(a[3], b[3]) - max(a[1], b[1])
            if w > 0 and h > 0:
                smaller = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
                if w * h > overlap * max(smaller, 1e-9):
                    return False
    return True


def route_guides(scene: Any, parts: list[Any], edges: list[tuple]) -> dict[int, list[tuple[float, float]]]:
    """The 2D route of each link that has one, as world points."""

    index = {id(node): position for position, node in enumerate(parts)}
    found: dict[frozenset, list[tuple[float, float]]] = {}
    for node in scene.walk():
        if not hasattr(node, "resolve_points") or getattr(node, "start_component", None) is None:
            continue
        start, end = index.get(id(node.start_component)), index.get(id(getattr(node, "end_component", None)))
        if start is None or end is None:
            continue
        points = [(float(x), float(y)) for x, y, *_ in node.resolve_points()]
        if len(points) >= 2 and all(math.isfinite(v) for point in points for v in point):
            found[frozenset({(start, str(node.start_port)), (end, str(node.end_port))})] = points
    guides = {}
    for number, (start, start_port, end, end_port, _) in enumerate(edges):
        points = found.get(frozenset({(start, start_port), (end, end_port)}))
        if points is not None:
            guides[number] = points
    return guides
