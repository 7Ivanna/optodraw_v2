"""The 1D schematic of a scene: its symbols, where they sit, and what joins them.

One model for the notebook, the SVG export and the TikZ export. Positions are
SVG points (y down) of each symbol's top left corner. They live in the scene
metadata under ``one_d_layout`` and never touch the 2D layout.
"""

from __future__ import annotations

import math
from collections import defaultdict, deque
from dataclasses import dataclass, field, replace
from typing import Any

from optodraw.core.component import ANNOTATION_TYPES
from optodraw.core.markup import plain

from . import Symbol, lookup

MARGIN = 5.0                     # SVG points around the figure: a paper has no room to waste
MIN_GAP_X = 12.0                 # between columns whose links run straight
RISE_RATIO = 0.45                # extra column gap per point of vertical travel of a link
PAD_GAP_X = 3.0                  # between bare pads in a row under the part they serve
GAP_Y = 5.0                      # between a label and the next symbol in a column
DRIVER_GAP = 7.0                 # between a part and a driver above or below it
CABLE_RISE = 12.0                # a connector on a bottom edge sits this far above the port it joins
INSIDE_MARGIN = 6.0              # a port nearer than this to the left or right edge is an edge port
LOOSE_ROW_WIDTH = 240.0          # a row of unlinked parts wraps here: one text column (8.5 cm)
LINE_UP = 25.0                   # the longest step a part takes to put its wires in line
JUNCTION = 1.2                   # the radius of the dot where wires of one node join
LABEL_SIZE = 7.0                 # label font size, SVG points
LABEL_HEIGHT = LABEL_SIZE * 1.5  # the room a label takes under (or over) its symbol
_ROUTE_TYPES = {"Route", "WaveguideRoute", "FiberRoute", "MetalRoute"}
# Containers, and the surfaces that parts stand on: a schematic shows the signal chain.
_NOT_IN_A_SCHEMATIC = {"Scene", "Group", "Grid", "ChipSubstrate", "OpticalTable", "Breadboard", "Baseplate"} | ANNOTATION_TYPES
# A 2D annotation: the schematic places parts by their links, so it keeps one only when a link reaches it.
_ANNOTATIONS = {"SignalArrow"}
_PADS = {"ElectricalPad", "HeaterPad"}      # square: a pad may turn to face the contact it serves
_NORMAL = {"left": (-1.0, 0.0), "right": (1.0, 0.0), "top": (0.0, -1.0), "bottom": (0.0, 1.0)}


_Edge = tuple[int, str, int, str, str]      # start part, its port, end part, its port, kind


@dataclass(frozen=True)
class Placed:
    key: str                     # the component's id in the scene file, or node-<n>
    label: str
    component: Any
    symbol: Symbol
    x: float
    y: float
    label_at: tuple[float, float, str] = (0.0, 0.0, "middle")   # x, baseline, text anchor (middle, start, end)
    label_over: bool = False     # the layout wants the label over the symbol (a part slid into line under it)

    def port(self, name: str) -> tuple[float, float, str] | None:
        port = self.symbol.ports.get(name)
        return None if port is None else (self.x + port.x, self.y + port.y, port.side)

    @property
    def label_above(self) -> bool:
        return _label_above(self.symbol, self.label)


@dataclass(frozen=True)
class Link:
    start: int                   # index into Schematic.items
    start_port: str
    end: int
    end_port: str
    kind: str                    # waveguide | fiber | electrical | free_space | ...

    @property
    def electrical(self) -> bool:
        return "elect" in self.kind.lower()


_Line = tuple[tuple[float, float], ...]


@dataclass(frozen=True)
class Mark:
    """A mark of the 2D figure on the 1D page, in page points: a Region's dashed box, a Bracket, or the motion mark
    of a part on a stage. ``kind`` is the mark's component type, or the stage's mount."""

    kind: str
    lines: tuple[_Line, ...]                 # open polylines
    heads: tuple[_Line, ...] = ()            # filled polygons: arrow heads
    dashed: bool = False
    color: str = "#333333"
    label: str = ""
    label_at: tuple[float, float, str] = (0.0, 0.0, "start")   # x, baseline, text anchor, as a part's label


@dataclass(frozen=True)
class Schematic:
    items: list[Placed]
    links: list[Link]
    unresolved: int              # connections whose end is not a part of the scene
    width: float
    height: float
    routes: dict[int, list[tuple[float, float]]] = field(default_factory=dict)   # link index -> square route
    marks: list[Mark] = field(default_factory=list)


def _is_part(node: Any) -> bool:
    from optodraw.core.beam import Beam, FocusingBeam

    kind = getattr(node, "component_type", None)
    if kind is None or isinstance(node, (Beam, FocusingBeam)):
        return False
    return kind not in _ROUTE_TYPES and kind not in _NOT_IN_A_SCHEMATIC


def _named_port(part: Any, *, leaving: bool, toward: Any = None) -> str:
    """The port of a part that a beam names without one: ``out`` where it leaves, ``in`` where it arrives, the
    part's only port, or else the port that lies nearest the other end of the beam (``toward``)."""

    try:
        names = list(part.ports())
    except Exception:
        return ""
    wanted = "out" if leaving else "in"
    if wanted in names:
        return wanted
    if len(names) == 1:
        return names[0]
    if toward is None or not names:
        return ""
    try:
        target = toward.world_position
        ports = part.world_ports()
        return min(names, key=lambda n: math.hypot(ports[n].center.x - target.x, ports[n].center.y - target.y))
    except Exception:
        return ""


def _edges(scene: Any, parts: list[Any]) -> tuple[list[_Edge], int]:
    from optodraw.core.beam import Beam, FocusingBeam
    from optodraw.core.component import Component

    index = {id(node): position for position, node in enumerate(parts)}
    edges, unresolved = [], 0
    runs: list[list[tuple[int | None, str]]] = []   # the stops of each beam, in the order the light meets them
    foci: dict[tuple[float, float], list[Any]] = {}   # a focus in the air: the cone that ends there, the one that starts
    for node in scene.walk():
        if getattr(node, "component_type", "") in _ROUTE_TYPES:
            start = index.get(id(getattr(node, "start_component", None)))
            end = index.get(id(getattr(node, "end_component", None)))
            if start is None or end is None:
                if getattr(node, "start_component", None) is not None or getattr(node, "end_component", None) is not None:
                    unresolved += 1
                continue
            edges.append((start, str(getattr(node, "start_port", "")), end,
                          str(getattr(node, "end_port", "")), str(getattr(node, "kind", "waveguide"))))
        elif isinstance(node, (Beam, FocusingBeam)):
            anchors = node.anchors if isinstance(node, Beam) else (node.anchor1, node.anchor2)
            stops = []
            for anchor in anchors:
                if isinstance(anchor, (tuple, list)) and len(anchor) == 2 and isinstance(anchor[0], Component):
                    stops.append((index.get(id(anchor[0])), str(anchor[1])))
                elif isinstance(anchor, Component):
                    stops.append((index.get(id(anchor)), ""))
            if not stops and anchors and all(_is_point(anchor) for anchor in anchors):
                stops = [(part, "") for part in _crossed(anchors, parts)]      # a traced ray: plain points
            if isinstance(node, FocusingBeam) and len(stops) == 1 and any(_is_point(a) for a in anchors):
                ends_there = _is_point(anchors[1])
                point = anchors[1] if ends_there else anchors[0]
                key = (round(float(point[0]), 6), round(float(point[1]), 6))
                foci.setdefault(key, [None, None])[0 if ends_there else 1] = stops[0]
                continue
            runs.append(stops)
    runs += [pair for pair in foci.values() if None not in pair]
    for stops in runs:
        for (start, start_port), (end, end_port) in zip(stops, stops[1:]):
            if start is None or end is None:
                unresolved += 1
            elif start != end:
                edges.append((start, start_port or _named_port(parts[start], leaving=True, toward=parts[end]), end,
                              end_port or _named_port(parts[end], leaving=False, toward=parts[start]), "free_space"))
    seen: set[frozenset[tuple[int, str]]] = set()
    unique = []
    for edge in edges:          # light that a mirror sends back, or two beams on one path: one line
        key = frozenset({(edge[0], edge[1]), (edge[2], edge[3])})
        if key not in seen:
            seen.add(key)
            unique.append(edge)
    return unique, unresolved


def _is_point(anchor: Any) -> bool:
    return isinstance(anchor, (tuple, list)) and len(anchor) in (2, 3) and all(isinstance(v, (int, float)) for v in anchor)


def _crossed(points: list, parts: list[Any]) -> list[int]:
    """The parts whose drawing a traced path crosses, in the order the light meets them."""

    import numpy as np

    from optodraw.layout import estimate_component_bounds

    hits = []
    for position, part in enumerate(parts):
        try:
            x0, y0, x1, y1 = estimate_component_bounds(part)
            inverse = np.linalg.inv(part.world_transform.to_matrix_4x4())
        except Exception:  # pragma: no cover - a part with no drawn size
            continue
        local = [(inverse @ np.array([p[0], p[1], 0.0, 1.0]))[:2] for p in points]
        for step, (a, b) in enumerate(zip(local, local[1:])):
            enter = _enters_box(a, b, (x0 - 0.5, y0 - 0.5, x1 + 0.5, y1 + 0.5))
            if enter is not None:
                hits.append((step + enter, position))
                break
    return [position for _, position in sorted(hits)]


def _enters_box(a: Any, b: Any, box: tuple[float, float, float, float]) -> float | None:
    """Where segment ``a``-``b`` enters ``box``, as a fraction of its length (Liang-Barsky), or None."""

    low, high = 0.0, 1.0
    for delta, start, lo, hi in ((b[0] - a[0], a[0], box[0], box[2]), (b[1] - a[1], a[1], box[1], box[3])):
        if abs(delta) < 1e-12:
            if start < lo or start > hi:
                return None
            continue
        t0, t1 = (lo - start) / delta, (hi - start) / delta
        low, high = max(low, min(t0, t1)), min(high, max(t0, t1))
        if low > high:
            return None
    return low


def _columns(count: int, edges: list[_Edge]) -> list[int]:
    """A column for each part: one past its deepest source. A loop goes after everything else."""

    outgoing: dict[int, list[int]] = defaultdict(list)
    waiting = [0] * count
    for start, _, end, _, _ in edges:
        if start != end:
            outgoing[start].append(end)
            waiting[end] += 1
    column = [0] * count
    queue = deque(position for position in range(count) if waiting[position] == 0)
    while queue:
        position = queue.popleft()
        for end in outgoing[position]:
            column[end] = max(column[end], column[position] + 1)
            waiting[end] -= 1
            if waiting[end] == 0:
                queue.append(end)
    looped = [position for position in range(count) if waiting[position] > 0]
    first = max(column) + 1
    for offset, position in enumerate(looped):
        column[position] = first + offset
    return column


def _footprint(symbol: Symbol, label: str) -> float:
    """The width a part needs: its symbol, or its label when that is wider."""

    return max(symbol.width, 0.5 * LABEL_SIZE * len(plain(label)))


def _label_above(symbol: Symbol, label: str) -> bool:
    """True for a part with connectors on its bottom edge only: its label goes over it, clear of the cables."""

    sides = {port.side for port in symbol.ports.values()}
    return bool(label) and "bottom" in sides and "top" not in sides


def _room(symbol: Symbol, label: str) -> tuple[float, float]:
    """The room for the label: over the symbol, under it. No label, no room."""

    if not label:
        return (0.0, 0.0)
    return (LABEL_HEIGHT, 0.0) if _label_above(symbol, label) else (0.0, LABEL_HEIGHT)


def _inside(symbol: Symbol, port: Any) -> bool:
    """True for a contact inside the symbol (an electrode), not on its left or right edge."""

    return min(port.x, symbol.width - port.x) > max(0.15 * symbol.width, INSIDE_MARGIN)


def _driver_side(symbol: Symbol, port: Any) -> str:
    """Above or below: where a driver of this port goes. Empty for a port on the left or right edge."""

    if port is None:
        return ""
    if port.side in ("top", "bottom"):
        return port.side
    if _inside(symbol, port):
        return "top" if port.y <= symbol.height / 2.0 + 0.5 else "bottom"     # at mid height: from above
    return ""


def _backwards(symbol: Symbol, part: int, edges: list[_Edge]) -> bool:
    """True when more links meet this symbol on its far side than on its near side.

    Light runs left to right: it arrives at a left port and leaves from a right
    port. A demultiplexer used as a multiplexer is the usual case.
    """

    score = 0
    for start, start_port, end, end_port, _ in edges:
        if start == end:
            continue
        for mine, port_name, good in ((end, end_port, "left"), (start, start_port, "right")):
            port = symbol.ports.get(port_name) if mine == part else None
            if port is not None and port.side in ("left", "right"):
                score += 1 if port.side == good else -1
    return score < 0


def _leaves_on_their_side(symbols: list[Symbol], edges: list[_Edge]) -> list[_Edge]:
    """A part with one link, to a port on the left of the part it joins, sits left of that part.

    A link runs from its source to the column after it. A terminator on a ring's add port is routed from the
    ring, so it went right of the ring and its wire looped back across it; turned round, it sits where the port
    faces.
    """

    count: dict[int, int] = defaultdict(int)
    for start, _, end, _, _ in edges:
        count[start] += 1
        count[end] += 1
    turned = []
    for start, start_port, end, end_port, kind in edges:
        port = symbols[start].ports.get(start_port)
        if count[end] == 1 and count[start] > 1 and port is not None and port.side == "left":
            start, start_port, end, end_port = end, end_port, start, start_port
        turned.append((start, start_port, end, end_port, kind))
    return turned


def _drivers(symbols: list[Symbol], edges: list[_Edge]) -> dict[int, tuple[int, str]]:
    """Parts that join one other part only, through a port on its top or bottom.

    A driver, a bias source, the mirror at the end of an interferometer arm, a
    detector on a tap. Such a part sits above or below the part it serves, not
    in a column of its own. That keeps the main path on one line and the figure
    narrow.
    """

    host: dict[int, tuple[int, str]] = {}
    for part in range(len(symbols)):
        mine = [edge for edge in edges if part in (edge[0], edge[2]) and edge[0] != edge[2]]
        if not mine:
            continue
        others = {edge[2] if edge[0] == part else edge[0] for edge in mine}
        if len(others) != 1:
            continue
        target = next(iter(others))
        sides = set()
        for start, start_port, end, end_port, _ in mine:
            port = symbols[target].ports.get(end_port if end == target else start_port)
            sides.add(_driver_side(symbols[target], port))
        if sides in ({"top"}, {"bottom"}):
            host[part] = (target, next(iter(sides)))
    return {part: value for part, value in host.items() if value[0] not in host}


def _overhead(symbols: list[Symbol], edges: list[_Edge]) -> set[int]:
    """Instruments that drive two or more parts through contacts on their top.

    Such a part goes above the parts it drives, as on a bench drawing. In a
    column of its own it would send long cables across the optical path.
    """

    found: set[int] = set()
    for part in range(len(symbols)):
        mine = [edge for edge in edges if part in (edge[0], edge[2]) and edge[0] != edge[2]]
        if not mine or not all("elect" in edge[4].lower() for edge in mine):
            continue
        others = {edge[2] if edge[0] == part else edge[0] for edge in mine}
        sides = {_driver_side(symbols[end if start == part else start],
                              symbols[end if start == part else start].ports.get(end_port if start == part else start_port))
                 for start, start_port, end, end_port, _ in mine}
        if len(others) >= 2 and sides == {"top"} and not others & found:
            found.add(part)
    return found


def _cells(
    symbols: list[Symbol], labels: list[str], edges: list[_Edge], skip: set[int],
) -> tuple[list[tuple[float, float]], dict[int, tuple[int, float, float]]]:
    """Group each part with its drivers. Return each cell's size and each part's place in its cell."""

    host = _drivers(symbols, edges)
    room = [_room(symbol, label) for symbol, label in zip(symbols, labels)]
    sizes: list[tuple[float, float]] = []
    where: dict[int, tuple[int, float, float]] = {}
    for part in range(len(symbols)):
        if part in host or part in skip:
            continue
        symbol = symbols[part]
        boxes = [(part, 0.0, 0.0)]
        for side in ("top", "bottom"):
            row = []
            for driver, (target, driver_side) in host.items():
                if target != part or driver_side != side:
                    continue
                reached, leaves, own = [], set(), []
                for start, start_port, end, end_port, _ in edges:
                    if driver not in (start, end):
                        continue
                    theirs, mine = (end_port, start_port) if end == part else (start_port, end_port)
                    if theirs in symbol.ports:
                        reached.append(symbol.ports[theirs].x)
                    if mine in symbols[driver].ports:
                        leaves.add(symbols[driver].ports[mine].side)
                        own.append(symbols[driver].ports[mine].x)
                own_x = sum(own) / len(own) if own else symbols[driver].width / 2.0
                row.append((sum(reached) / len(reached), driver, leaves, own_x))
            cursor = -math.inf
            placed_row = []
            for centre, driver, leaves, own_x in sorted(row, key=lambda entry: entry[:2]):
                # its own port over the port it serves, so the link runs straight; beside it when its own port is
                # on its side, so the link turns once
                if leaves == {"right"}:
                    x = centre - symbols[driver].width - DRIVER_GAP
                elif leaves == {"left"}:
                    x = centre + DRIVER_GAP
                else:
                    x = centre - own_x
                x = max(x, cursor)
                y = (-(room[part][0] + DRIVER_GAP + room[driver][1] + symbols[driver].height) if side == "top"
                     else symbol.height + room[part][1] + DRIVER_GAP + room[driver][0])
                placed_row.append((driver, x, y, centre))
                gap = MIN_GAP_X if labels[driver] else PAD_GAP_X        # a row of bare pads stays tight
                cursor = x + _footprint(symbols[driver], labels[driver]) + gap
            if len(placed_row) > 1:                                     # the row centred under what it serves
                served = sum(c for *_, c in placed_row) / len(placed_row)
                span = (placed_row[0][1] + placed_row[-1][1] + symbols[placed_row[-1][0]].width) / 2.0
                placed_row = [(d, x + served - span, y, c) for d, x, y, c in placed_row]
            boxes.extend((d, x, y) for d, x, y, _ in placed_row)
        pad = {i: (_footprint(symbols[i], labels[i]) - symbols[i].width) / 2.0 for i, _, _ in boxes}
        left = min(x - pad[i] for i, x, _ in boxes)
        right = max(x + symbols[i].width + pad[i] for i, x, _ in boxes)
        top = min(y - room[i][0] for i, _, y in boxes)
        bottom = max(y + symbols[i].height + room[i][1] for i, _, y in boxes)
        for i, x, y in boxes:
            where[i] = (len(sizes), x - left, y - top)
        sizes.append((right - left, bottom - top))
    return sizes, where


def _auto_positions(symbols: list[Symbol], labels: list[str], edges: list[_Edge]) -> list[tuple[float, float]]:
    """A compact first arrangement.

    Columns run left to right along the links. Each part is level with the port
    that feeds it, so links run straight, and a straight link needs only a short
    gap. A column is as far from the one before it as its steepest link needs.
    A fan-out keeps the order of its ports, so its links do not cross.
    Parts with no link at all go in rows under the figure. An instrument that
    drives several parts goes above them.
    """

    over = _overhead(symbols, edges)
    sizes, where = _cells(symbols, labels, [edge for edge in edges if not over & {edge[0], edge[2]}], over)
    between = [edge for edge in edges if not over & {edge[0], edge[2]} and where[edge[0]][0] != where[edge[2]][0]]
    column = _columns(len(sizes), [(where[start][0], "", where[end][0], "", "") for start, _, end, _, _ in between])
    linked = {where[edge[0]][0] for edge in between} | {where[edge[2]][0] for edge in between}
    members: dict[int, list[int]] = defaultdict(list)
    for cell, value in enumerate(column):
        if cell in linked:
            members[value].append(cell)
    order = sorted(members)
    top: dict[int, float] = {}
    firm: set[int] = set()                                        # cells whose level the optical path decides

    def offset(part: int, port: str) -> float:                    # a port's height inside its cell
        found = symbols[part].ports.get(port)
        return where[part][2] + (found.y if found is not None else symbols[part].height / 2.0)

    def aim(part: int, port: str) -> float:                       # where the joined port is wanted, from the cell top
        side = getattr(symbols[part].ports.get(port), "side", "")
        return offset(part, port) + {"bottom": CABLE_RISE, "top": -CABLE_RISE}.get(side, 0.0)

    def port_y(part: int, port: str) -> float:
        return top[where[part][0]] + offset(part, port)

    def stack(rows: list[int], wanted: dict[int, float]) -> None:
        """Put the cells of one column at their wanted heights, pushed apart where they would overlap."""

        rows.sort(key=lambda cell: (wanted.get(cell, math.inf), cell))
        cursor = -math.inf
        for cell in rows:
            top[cell] = max(wanted.get(cell, cursor if cursor > -math.inf else 0.0), cursor)
            cursor = top[cell] + sizes[cell][1] + GAP_Y
        held = [cell for cell in rows if cell in wanted]
        held = [cell for cell in held if cell in firm] or held    # a cell that only wires level gives way
        pushed = [wanted[cell] - top[cell] for cell in held]
        if pushed:                                                # share the push between both ends
            for cell in rows:
                top[cell] += sum(pushed) / len(pushed)

    def levels(rows: list[int], *, fed: bool, light_only: bool = False) -> dict[int, float]:
        light: dict[int, list[float]] = defaultdict(list)       # through a left or right port: the main line
        turned: dict[int, list[float]] = defaultdict(list)      # light from a top or bottom port (a tap, a reflection)
        wires: dict[int, list[float]] = defaultdict(list)
        for start, start_port, end, end_port, kind in between:
            mine, other, mine_port, other_port = (end, start, end_port, start_port) if fed else (start, end, start_port, end_port)
            if where[mine][0] in rows and where[other][0] in top:
                side = getattr(symbols[other].ports.get(other_port), "side", "right")
                group = wires if "elect" in kind.lower() else light if side in ("left", "right") else turned
                group[where[mine][0]].append(port_y(other, other_port) - aim(mine, mine_port))
        # The main optical line decides, light that turned follows, wires follow last.
        wanted = light if light_only else {**wires, **turned, **light}
        firm.update(light)
        return {cell: sum(values) / len(values) for cell, values in wanted.items()}

    for value in order:                                           # left to right: follow the feeding ports
        stack(members[value], levels(members[value], fed=True))
    if order:
        stack(members[order[0]], levels(members[order[0]], fed=False))  # the sources: level with what they feed

    # A cell that feeds one cell only, which nothing else feeds, moves level with
    # it: a weight bank and its own detector then join with straight links.
    feeds: dict[int, set[int]] = defaultdict(set)
    fed_by: dict[int, set[int]] = defaultdict(set)
    for start, _, end, _, _ in between:
        feeds[where[start][0]].add(where[end][0])
        fed_by[where[end][0]].add(where[start][0])
    for value in reversed(order[:-1]):
        rows = members[value]
        wanted = {cell: top[cell] for cell in rows}
        paired = False
        for cell in rows:
            if len(feeds[cell]) == 1 and fed_by[next(iter(feeds[cell]))] == {cell}:
                level = levels([cell], fed=False, light_only=True).get(cell)   # a cable never moves the optical line
                if level is not None and abs(level - top[cell]) > 0.5:
                    wanted[cell], paired = level, True
        if paired:
            stack(rows, wanted)

    positions: list[tuple[float, float]] = [(0.0, 0.0)] * len(symbols)
    lowest = min(top.values(), default=0.0)
    x = MARGIN
    for number, value in enumerate(order):
        rows = members[value]
        if number:
            rise = max((abs(port_y(start, start_port) - port_y(end, end_port))
                        for start, start_port, end, end_port, _ in between if where[end][0] in rows), default=0.0)
            x += max(MIN_GAP_X, RISE_RATIO * rise)
        width = max(sizes[cell][0] for cell in rows)
        for part, (cell, dx, dy) in where.items():
            if cell in rows:
                positions[part] = (x + (width - sizes[cell][0]) / 2.0 + dx, top[cell] - lowest + MARGIN + dy)
        x += width

    # Parts with no link: rows under the figure, as wide as the figure (or a text column).
    wrap = max(x, LOOSE_ROW_WIDTH)
    y = max((top[cell] - lowest + MARGIN + sizes[cell][1] + GAP_Y for cell in top), default=MARGIN)
    x, row_height = MARGIN, 0.0
    for cell in range(len(sizes)):
        if cell in linked:
            continue
        width, height = sizes[cell]
        if x > MARGIN and x + width > wrap:
            x, y, row_height = MARGIN, y + row_height + GAP_Y, 0.0
        for part, (owner, dx, dy) in where.items():
            if owner == cell:
                positions[part] = (x + dx, y + dy)
        x += width + MIN_GAP_X
        row_height = max(row_height, height)

    # An instrument that drives several parts: above them, centred over the contacts it reaches.
    room = [_room(symbol, label) for symbol, label in zip(symbols, labels)]
    pad = [(_footprint(symbol, label) - symbol.width) / 2.0 for symbol, label in zip(symbols, labels)]
    placed = [part for part in range(len(symbols)) if part not in over]
    for part in sorted(over):
        symbol, reached, own = symbols[part], [], []
        for start, start_port, end, end_port, _ in edges:
            if part in (start, end):
                other, theirs, mine = (end, end_port, start_port) if start == part else (start, start_port, end_port)
                reached.append(positions[other][0] + symbols[other].ports[theirs].x)
                if mine in symbol.ports:
                    own.append(symbol.ports[mine].x)
        x = max(MARGIN + pad[part], sum(reached) / len(reached) - (sum(own) / len(own) if own else symbol.width / 2.0))
        left, right = x - pad[part] - MIN_GAP_X, x + symbol.width + pad[part] + MIN_GAP_X
        ceiling = min((positions[i][1] - room[i][0] for i in placed
                       if positions[i][0] - pad[i] < right and left < positions[i][0] + symbols[i].width + pad[i]),
                      default=MARGIN + room[part][0] + symbol.height + room[part][1] + DRIVER_GAP)
        positions[part] = (x, ceiling - DRIVER_GAP - room[part][1] - symbol.height)
        placed.append(part)
    lift = MARGIN - min((positions[part][1] - room[part][0] for part in over), default=MARGIN)
    if lift > 0:
        positions = [(x, y + lift) for x, y in positions]
    return positions


def _label_box(x: float, baseline: float, anchor: str, label: str) -> tuple[float, float, float, float]:
    width = 0.5 * LABEL_SIZE * len(plain(label))
    left = {"middle": x - width / 2.0, "start": x, "end": x - width}[anchor]
    return (left, baseline - 0.8 * LABEL_SIZE, left + width, baseline + 0.2 * LABEL_SIZE)


def _cubic_points(curve: tuple[tuple[float, float], ...], steps: int = 24) -> list[tuple[float, float]]:
    (ax, ay), (bx, by), (cx, cy), (dx, dy) = curve
    return [((1 - t) ** 3 * ax + 3 * (1 - t) ** 2 * t * bx + 3 * (1 - t) * t * t * cx + t ** 3 * dx,
             (1 - t) ** 3 * ay + 3 * (1 - t) ** 2 * t * by + 3 * (1 - t) * t * t * cy + t ** 3 * dy)
            for t in (k / steps for k in range(steps + 1))]


def _place_labels(items: list[Placed], links: list[Link], sides: bool | str = False) -> list[Placed]:
    """Each label at the first free spot: under (or over) its symbol, then the other side, then to one side,
    one or two lines further out if it must. With ``sides`` (a bench drawn as built) the side the 2D drawing
    gives the label (``label_side``) comes first; with ``sides="set"`` (a chip's plan) only a side other than
    the default "top" does, and a default label keeps its place by the symbol's connectors.

    A spot is free when no link, no symbol and no label placed before it
    touches the text. A beam that leaves a bottom port then never runs
    through the name of its part.
    """

    from optodraw.check import _hits

    draft = Schematic(items, links, 0, 0.0, 0.0)
    paths = [_cubic_points(link_curve(draft, link)) for link in links]
    taken = [(item.x, item.y, item.x + item.symbol.width, item.y + item.symbol.height) for item in items]

    def free(box: tuple[float, float, float, float], clear: float, page: bool) -> bool:
        if page and (box[0] < 0.0 or box[1] < 0.0):         # on the page first; the page grows only when it must
            return False
        near = (box[0] - 1.0, box[1] - 1.0, box[2] + 1.0, box[3] + 1.0)     # the drawn stroke has a width
        if any(_hits(p, q, near) for path in paths for p, q in zip(path, path[1:])):
            return False
        return not any(box[0] - clear < other[2] and other[0] < box[2] + clear and box[1] - clear < other[3]
                       and other[1] < box[3] + clear for other in taken)

    result = []
    for item in items:
        if not item.label:
            result.append(item)
            continue
        middle = item.x + item.symbol.width / 2.0
        below, above = item.y + item.symbol.height + LABEL_SIZE * 1.05, item.y - LABEL_SIZE * 0.4
        first, second = (above, below) if item.label_above or item.label_over else (below, above)
        step = LABEL_HEIGHT if first == below else -LABEL_HEIGHT     # away from the symbol
        spots = [(middle, first, "middle"), (middle, second, "middle")]
        for baseline in (first, second, first + step, first + 2.0 * step):
            spots += [(middle - 1.5, baseline, "end"), (middle + 1.5, baseline, "start")]
        level = item.y + item.symbol.height / 2.0 + LABEL_SIZE * 0.35       # beside the part: a tight vertical run
        spots += [(item.x + item.symbol.width + 2.0, level, "start"), (item.x - 2.0, level, "end")]
        side = str(getattr(item.component, "label_side", "") or "")
        given = []
        if sides and not (sides == "set" and side in ("", "top")):
            spots.insert(0, {"top": (middle, above, "middle"), "bottom": (middle, below, "middle"),
                             "right": spots[-2], "left": spots[-1],
                             "top-right": (middle + 1.5, above, "start"), "top-left": (middle - 1.5, above, "end"),
                             "bottom-right": (middle + 1.5, below, "start"),
                             "bottom-left": (middle - 1.5, below, "end")}.get(side, spots[0]))
            given = spots[:1] if side else []        # the side the 2D gives may push the page out
        spot = next((spot for clear in (1.0, 0.0) for spot in given if free(_label_box(*spot, item.label), clear,
                                                                             False)), None)
        spot = spot or next((spot for page in (True, False) for clear in (1.0, 0.0) for spot in spots  # clear if it can be
                             if free(_label_box(*spot, item.label), clear, page)), spots[0])
        taken.append(_label_box(*spot, item.label))
        result.append(replace(item, label_at=spot))
    return result


# ---------------------------------------------------------------- free-space bench
# A scene whose light travels only in free space is drawn as it is built: each
# beam keeps the direction it has in the 2D scene (right, up, left or down), each
# part turns to face its beams, and a mirror turns so its reflecting face looks
# at the beam that arrives and at the beam that leaves.

BENCH_GAP = 14.0                 # clear space along a beam between two parts, SVG points
_FACING = {"right": 0.0, "top": 90.0, "left": 180.0, "bottom": 270.0}


_BENCH_KINDS = {"free_space", "fiber", "electrical"}
_LIGHT_KINDS = {"free_space", "fiber"}    # a cable turns square: it hangs an instrument on the bench, never moves it


def _is_bench(edges: list[_Edge], planned: bool = False) -> bool:
    """Light in free space, with fibres and cables to the instruments: a bench, drawn as built. With a 1D layout
    set (``planned``) light in fibres alone is a bench too, so ``set_view_layout`` places it from the 2D."""

    light = ("free_space", "fiber") if planned else ("free_space",)
    return any(edge[4] in light for edge in edges) and all(edge[4] in _BENCH_KINDS for edge in edges)


def _snap(angle: float, step: float) -> float:
    return (round(angle / step) * step) % 360.0


def _gap(a: float, b: float) -> float:
    return abs((a - b + 180.0) % 360.0 - 180.0)


SPREAD = 45.0           # beams at one part that round to one axis turn apart in steps of this many degrees
SAME_ANGLE = 5.0        # beams this close in 2D are one direction


def _beam_directions(parts: list[Any], edges: list[_Edge]) -> list[float]:
    """The direction of each beam, counterclockwise from +x: from one port to the other in the 2D scene, on the
    nearest axis. Free-space beams at one part that round to one axis but leave it at different angles in 2D (two arms
    out of a crystal, a fold back under its own beam) would run on one line through each other's parts: they turn
    apart in 45 degree steps, each to the side of its 2D angle. A beam on the axis keeps it."""

    raw = []
    for start, start_port, end, end_port, _ in edges:
        angle = 0.0
        try:
            a = parts[start].world_port(start_port)
            b = parts[end].world_port(end_port)
            dx, dy = b.center.x - a.center.x, b.center.y - a.center.y
            angle = math.degrees(math.atan2(dy, dx)) if math.hypot(dx, dy) > 1e-6 else a.orientation_deg
        except (AttributeError, KeyError, TypeError):
            pass
        raw.append(angle % 360.0)
    found = [_snap(angle, 90.0) for angle in raw]
    turned: set[int] = set()
    for part in range(len(parts)):
        rays: dict[float, list[tuple[float, int, bool]]] = defaultdict(list)   # axis -> (off it, beam, leaves part)
        for index, (start, _, end, _, kind) in enumerate(edges):
            if part not in (start, end) or start == end or kind != "free_space":      # a fibre or a cable bends
                continue
            out = start == part
            ray, axis = (raw[index], found[index]) if out else ((raw[index] + 180.0) % 360.0, (found[index] + 180.0) % 360.0)
            rays[axis].append(((ray - axis + 180.0) % 360.0 - 180.0, index, out))
        for axis, group in rays.items():
            group.sort()
            if len(group) < 2 or group[-1][0] - group[0][0] < SAME_ANGLE:
                continue
            on_axis = min(range(len(group)), key=lambda i: abs(group[i][0]))
            below = sum(off < 0 for off, _, _ in group)
            for i, (_, index, out) in enumerate(group):
                if abs(group[on_axis][0]) < SAME_ANGLE:
                    step = i - on_axis
                else:                                     # none on the axis: the arms go out to either side
                    step = i - below + (i >= below)
                if step and index not in turned:
                    found[index] = (axis + SPREAD * step + (0.0 if out else 180.0)) % 360.0
                    turned.add(index)
    return found


def _bench_turns(parts: list[Any], symbols: list[Symbol], edges: list[_Edge], directions: list[float]) -> list[Symbol]:
    """Turn each symbol so that every port faces along its beam: out along the beam, in back against it."""

    wanted: dict[int, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for (start, start_port, end, end_port, _), angle in zip(edges, directions):
        wanted[start][start_port].append(angle)
        wanted[end][end_port].append((angle + 180.0) % 360.0)
    turned = []
    for part, symbol in enumerate(symbols):
        faces = wanted.get(part)
        if not faces:
            turned.append(symbol)
            continue
        if len(symbol.ports) == 1:                            # a mirror: its face halves the angle between the beams
            name, angles = next(iter(faces.items()))
            x = sum(math.cos(math.radians(a)) for a in angles)
            y = sum(math.sin(math.radians(a)) for a in angles)
            face = math.degrees(math.atan2(y, x)) if math.hypot(x, y) > 1e-6 else angles[0]
            turned.append(symbol.rotated(_snap(face - _FACING[symbol.ports[name].side], 45.0)))
            continue
        world = {}
        for name in symbol.ports:                             # the 2D scene settles what the beams leave open
            try:
                world[name] = parts[part].world_port(name).orientation_deg
            except (AttributeError, KeyError, TypeError):
                pass

        def cost(turn: float) -> tuple[float, float, float]:
            beams = sum(_gap(_FACING[symbol.ports[name].side] + turn, a)
                        for name, angles in faces.items() if name in symbol.ports for a in angles)
            scene = sum(_gap(_FACING[symbol.ports[name].side] + turn, a) for name, a in world.items())
            return beams, scene, _gap(turn, 0.0)

        turned.append(symbol.rotated(min((0.0, 90.0, 180.0, 270.0), key=cost)))
    return turned


def _mapped_bench_positions(parts: list[Any], symbols: list[Symbol]) -> list[tuple[float, float]]:
    """Preserve the plan-view arrangement while allowing space for schematic symbols."""
    centres = [(part.world_position.x, -part.world_position.y) for part in parts]
    scale = 1.0
    for i, (x, y) in enumerate(centres):
        for j in range(i):
            dx, dy = abs(x - centres[j][0]), abs(y - centres[j][1])
            horizontal = ((symbols[i].width + symbols[j].width) / 2 + BENCH_GAP) / dx if dx > 1e-9 else math.inf
            vertical = ((symbols[i].height + symbols[j].height) / 2 + LABEL_HEIGHT + BENCH_GAP) / dy if dy > 1e-9 else math.inf
            required = min(horizontal, vertical)
            if math.isfinite(required):
                scale = max(scale, required)
    spots = [(x * scale - symbol.width / 2, y * scale - symbol.height / 2)
             for (x, y), symbol in zip(centres, symbols)]
    left = min(x for x, _ in spots)
    top = min(y for _, y in spots)
    return [(x - left + MARGIN, y - top + MARGIN + LABEL_HEIGHT) for x, y in spots]


def _scene_bench_symbol(part):
    """Use the component rotation, not angles inferred from snapped beam directions."""
    from optodraw.symbols.art import fit_art

    symbol = lookup(part)
    if part.component_type == "Periscope":
        # Keep the approved side-view symbol. Its input sets the local reference;
        # the shared component transform supplies every user rotation.
        local_angle = part.ports()["in"].orientation_deg - _FACING[symbol.ports["in"].side]
        return symbol.rotated(local_angle + part.world_transform.rotation_deg.z)
    art = fit_art(part, symbol)
    if art is not None:
        if art.mirror:
            symbol = symbol.mirrored()
        return symbol.rotated(art.turn + part.world_transform.rotation_deg.z)
    return symbol.rotated(part.world_transform.rotation_deg.z)


def _scene_bench_layout(parts, symbols, settings):
    """Use the source plan, with symbol sizes based on each component's drawn extent."""
    from optodraw.layout import estimate_component_bounds

    units = 3.0  # SVG points per source drawing unit, independent of floor spacing
    spacing = float(settings.get("spacing", 1.0))
    scaled = []
    spots = []
    for part, symbol in zip(parts, symbols):
        symbol = _scene_bench_symbol(part)
        left, bottom, right, top = estimate_component_bounds(part)
        extent = max(right - left, top - bottom)
        if part.component_type == "GalvoMirror":
            # The scan envelope is not the size of the schematic mirror.
            extent = part.aperture * 0.7
        symbol = symbol.scaled(units * max(extent, 1.0) / max(symbol.width, symbol.height))
        scaled.append(symbol)
        point = part.world_position
        spots.append((point.x * units * spacing - symbol.origin[0],
                      -point.y * units * spacing - symbol.origin[1]))
    left = min((x for x, _ in spots), default=0)
    top = min((y for _, y in spots), default=0)

    def to_page(point: tuple[float, float]) -> tuple[float, float]:      # a 2D point on the 1D page
        return (point[0] * units * spacing - left + MARGIN, -point[1] * units * spacing - top + MARGIN + LABEL_HEIGHT)

    return scaled, [(x - left + MARGIN, y - top + MARGIN + LABEL_HEIGHT) for x, y in spots], to_page


_PLATE_BEAM_PORTS = ("in", "refl", "trans", "tap")


def _beams_meet_at_the_hub(symbol: Symbol) -> Symbol:
    """A plate splitter meets every beam at one point, its centre: put its four beam ports there, so a
    reflected beam does not seem to leave the plate from one end before it reaches the splitter. A flip mirror's
    straight route crosses where its fold does, as in 2D."""

    if symbol.name == "flipmirror" and {"io", "pass"} <= set(symbol.ports):
        io = symbol.ports["io"]
        return replace(symbol, ports={**symbol.ports, "pass": replace(symbol.ports["pass"], x=io.x, y=io.y)})
    if symbol.hub is None or not any(name in symbol.ports for name in _PLATE_BEAM_PORTS):
        return symbol
    hx, hy = symbol.hub
    ports = {name: replace(port, x=hx, y=hy) if name in _PLATE_BEAM_PORTS else port
             for name, port in symbol.ports.items()}
    return replace(symbol, ports=ports)


def _bench_positions(symbols: list[Symbol], edges: list[_Edge], directions: list[float]) -> list[tuple[float, float]]:
    """Walk along the beams from each source and put every part one gap further along its beam. A beam is
    followed back as well: a second source's arm is placed from the part where it joins, as in 2D."""

    count = len(symbols)
    position: dict[int, tuple[float, float]] = {}
    parent: dict[int, int] = {}
    via: dict[int, tuple[int, tuple[float, float]]] = {}      # part -> (the beam that placed it, its direction)
    pushed: dict[int, float] = defaultdict(float)
    order = sorted(range(count), key=lambda part: (any(edge[2] == part for edge in edges), part))

    def unit(angle: float) -> tuple[float, float]:            # y grows downward on paper
        return round(math.cos(math.radians(angle)), 9), round(-math.sin(math.radians(angle)), 9)

    def reach(part: int, port: str, d: tuple[float, float]) -> float:
        symbol, spot = symbols[part], symbols[part].ports[port]
        corners = ((0.0, 0.0), (symbol.width, 0.0), (0.0, symbol.height), (symbol.width, symbol.height))
        return max(0.0, max((x - spot.x) * d[0] + (y - spot.y) * d[1] for x, y in corners))

    def spread(queue: deque[int], kinds: set[str]) -> None:
        while queue:
            part = queue.popleft()
            for index, ((start, start_port, end, end_port, kind), angle) in enumerate(zip(edges, directions)):
                if kind not in kinds:
                    continue
                forward = unit(angle)
                if start == part and end not in position:              # along the beam
                    near, near_port, far, far_port, d = start, start_port, end, end_port, forward
                elif end == part and start not in position:            # back along it, to where it came from
                    near, near_port, far, far_port, d = end, end_port, start, start_port, (-forward[0], -forward[1])
                else:
                    continue
                a = symbols[near].ports[near_port]
                b = symbols[far].ports[far_port]
                length = BENCH_GAP + reach(near, near_port, d) + reach(far, far_port, (-d[0], -d[1])) + pushed[far]
                px, py = position[near][0] + a.x + d[0] * length, position[near][1] + a.y + d[1] * length
                position[far] = (px - b.x, py - b.y)
                parent[far] = near
                via[far] = (index, d)
                queue.append(far)

    def walk() -> None:
        """Lay the light out first, from each part that sends some; then hang on it the parts that only cables
        reach. A feedback cable (a servo back to its laser) made the instrument the root and bent the beams."""

        position.clear()
        parent.clear()
        via.clear()
        for kinds in (_LIGHT_KINDS, _BENCH_KINDS):
            spread(deque(position), kinds)
            for root in order:
                if root in position or (kinds is _LIGHT_KINDS
                                        and not any(edge[0] == root and edge[4] in kinds for edge in edges)):
                    continue
                low = max((y + symbols[part].height for part, (_, y) in position.items()), default=None)
                position[root] = (0.0, 0.0 if low is None else low + 3.0 * BENCH_GAP)
                spread(deque([root]), kinds)

    beams = [edge for edge in edges if edge[4] == "free_space"]
    lit = {end for edge in beams for end in (edge[0], edge[2])}

    def hung(part: int) -> bool:                              # an instrument on a fibre or a cable, with no beam
        return part in via and part not in lit

    def hangs_from(part: int, root: int) -> bool:
        while part in parent:
            part = parent[part]
            if part == root:
                return True
        return False

    def between_beams(box: tuple[float, float, float, float]) -> bool:
        """Beams pass ``box`` on two opposite sides: above and below it, or left and right of it."""

        sides = set()
        for start, start_port, end, end_port, _ in beams:
            if start not in position or end not in position:
                continue
            a, b = symbols[start].ports[start_port], symbols[end].ports[end_port]
            (ax, ay), (bx, by) = (position[start][0] + a.x, position[start][1] + a.y), \
                (position[end][0] + b.x, position[end][1] + b.y)
            if min(ax, bx) < box[2] and box[0] < max(ax, bx):
                if max(ay, by) <= box[1]:
                    sides.add("above")
                elif min(ay, by) >= box[3]:
                    sides.add("below")
            if min(ay, by) < box[3] and box[1] < max(ay, by):
                if max(ax, bx) <= box[0]:
                    sides.add("left")
                elif min(ax, bx) >= box[2]:
                    sides.add("right")
        return {"above", "below"} <= sides or {"left", "right"} <= sides

    def out_of(box: tuple[float, float, float, float], light: list[tuple[float, float, float, float]],
               d: tuple[float, float]) -> float | None:
        """How far ``box`` must move along ``d`` to pass every box of ``light`` in its way, with a gap to spare."""

        if abs(d[0]) > abs(d[1]):                             # moving sideways: the boxes level with it are in the way
            way = [b for b in light if b[1] < box[3] and box[1] < b[3]]
        else:
            way = [b for b in light if b[0] < box[2] and box[0] < b[2]]
        if not way:
            return None
        lx0, ly0 = min(b[0] for b in way), min(b[1] for b in way)
        lx1, ly1 = max(b[2] for b in way), max(b[3] for b in way)
        steps = [step for step in ((lx1 + BENCH_GAP - box[0]) / d[0] if d[0] > 1e-9 else None,
                                   (box[2] - lx0 + BENCH_GAP) / -d[0] if d[0] < -1e-9 else None,
                                   (ly1 + BENCH_GAP - box[1]) / d[1] if d[1] > 1e-9 else None,
                                   (box[3] - ly0 + BENCH_GAP) / -d[1] if d[1] < -1e-9 else None)
                 if step is not None and step > 0]
        return min(steps, default=None)

    walk()
    for _ in range(40):                                       # a part on another: move the later one further out
        boxes = {part: (x, y, x + symbols[part].width, y + symbols[part].height) for part, (x, y) in position.items()}
        inside = next((part for part, box in boxes.items() if hung(part) and between_beams(box)), None)
        if inside is not None:          # an instrument between the beams: its group goes out along its link
            root = inside
            while hung(parent[root]):
                root = parent[root]
            group = [boxes[part] for part in boxes if part == root or hangs_from(part, root)]
            whole = (min(b[0] for b in group), min(b[1] for b in group), max(b[2] for b in group),
                     max(b[3] for b in group))
            step = out_of(whole, [box for part, box in boxes.items() if not hung(part)], via[root][1])
            if step is not None:
                pushed[root] += step
                walk()
                continue
        clash = next(((p, q) for p in boxes for q in boxes
                      if p < q and boxes[p][0] < boxes[q][2] + 2.0 and boxes[q][0] < boxes[p][2] + 2.0
                      and boxes[p][1] < boxes[q][3] + 2.0 and boxes[q][1] < boxes[p][3] + 2.0), None)
        if clash is None:
            break
        later = max(clash, key=lambda part: list(position).index(part))
        if later not in parent:
            break
        # Move the whole arm: lengthen the beam where the later part's branch leaves the path of the other part.
        other = clash[0] if later == clash[1] else clash[1]
        line, part = {other}, other
        while part in parent:
            part = parent[part]
            line.add(part)
        arm = later
        while parent.get(arm) is not None and parent[arm] not in line:
            arm = parent[arm]
        pushed[arm] += BENCH_GAP
        walk()

    # A beam that closes a loop (the second arm of an interferometer reaching its splitter) was never
    # placed by the walk, so it ran across. Lengthen one beam on either arm, parallel to the offset, until
    # the closing beam is straight along its own direction.
    def port_point(part: int, port: str) -> tuple[float, float]:
        spot = symbols[part].ports[port]
        return position[part][0] + spot.x, position[part][1] + spot.y

    def tree_steps(part: int) -> list[tuple[int, tuple[float, float]]]:
        """The parts up the walk from ``part`` with the direction each was placed in."""

        chain = []
        while part in parent:
            chain.append((part, via[part][1]))
            part = parent[part]
        return chain

    for _ in range(20):
        moved = False
        placed_by = {index for index, _ in via.values()}
        for index, ((start, start_port, end, end_port, _), angle) in enumerate(zip(edges, directions)):
            if index in placed_by or start not in position or end not in position or edges[index][4] != "free_space":
                continue                          # a fibre or a cable that closes a loop bends: it need not run straight
            d = unit(angle)
            (ax, ay), (bx, by) = port_point(start, start_port), port_point(end, end_port)
            along = (bx - ax) * d[0] + (by - ay) * d[1]
            px, py = bx - ax - along * d[0], by - ay - along * d[1]
            off = math.hypot(px, py)
            if off < 0.5:
                continue
            for part, (ux, uy) in ((end, (-px / off, -py / off)), (start, (px / off, py / off))):
                child = next((child for child, (dx, dy) in tree_steps(part) if dx * ux + dy * uy > 0.99), None)
                if child is not None:
                    pushed[child] += off
                    moved = True
                    break
            if moved:
                walk()
                break
        if not moved:
            break
    left = min(x for x, _ in position.values())
    top = min(y for _, y in position.values())
    return [(position[part][0] - left + MARGIN, position[part][1] - top + MARGIN + LABEL_HEIGHT) for part in range(count)]


def _saved(scene: Any, positions: dict[str, Any] | None) -> dict[str, Any]:
    if positions is not None:
        return positions
    metadata = getattr(scene, "metadata", None)
    layout = metadata.get("one_d_layout") if isinstance(metadata, dict) else None
    return layout if isinstance(layout, dict) else {}


def build_schematic(scene: Any, positions: dict[str, Any] | None = None, *, arrangement: str | None = None) -> Schematic:
    """Place every part of ``scene`` as its 1D symbol. ``positions`` overrides the saved layout.

    A chip is drawn as its 2D plan, closed up: the same arrangement, each part as its symbol, each link along
    its 2D route. A chip whose parts overlap in 2D gets the compact automatic arrangement. Any other scene gets the
    automatic arrangement too, unless its links cross there and its plan fits and crosses fewer. ``arrangement`` is
    ``"auto"`` or ``"plan"`` to choose one. The marks of the 2D figure (a Region, a Bracket, a stage's motion mark)
    come with it, round the symbols of their parts.
    """

    return _on_page(_marked(scene, _build(scene, positions, arrangement)))


def _mark_points(mark: Mark) -> list[tuple[float, float]]:
    """The points a mark reaches: its lines, its heads and the corners of its text."""

    points = [point for line in mark.lines + mark.heads for point in line]
    if mark.label:
        x0, y0, x1, y1 = _label_box(*mark.label_at, mark.label)
        points += [(x0, y0), (x1, y1)]
    return points


def _page_shift(schematic: Schematic) -> tuple[float, float]:
    """How far right and down the schematic must move so that every symbol, label, route and mark starts at least
    a margin from the page edge."""

    boxes = [(item.x, item.y) for item in schematic.items]
    boxes += [_label_box(*item.label_at, item.label)[:2] for item in schematic.items if item.label]
    boxes += [point for route in schematic.routes.values() for point in route]
    boxes += [point for mark in schematic.marks for point in _mark_points(mark)]
    if not boxes:
        return 0.0, 0.0
    return max(0.0, MARGIN - min(x for x, _ in boxes)), max(0.0, MARGIN - min(y for _, y in boxes))


def _on_page(schematic: Schematic) -> Schematic:
    """The schematic moved so that every symbol, label, route and mark starts at least a margin from the page
    edge."""

    dx, dy = _page_shift(schematic)
    if dx < 1e-9 and dy < 1e-9:
        return schematic

    def move(line: _Line) -> _Line:
        return tuple((x + dx, y + dy) for x, y in line)

    items = [replace(item, x=item.x + dx, y=item.y + dy,
                     label_at=(item.label_at[0] + dx, item.label_at[1] + dy, item.label_at[2]))
             for item in schematic.items]
    routes = {index: [(x + dx, y + dy) for x, y in route] for index, route in schematic.routes.items()}
    marks = [replace(mark, lines=tuple(map(move, mark.lines)), heads=tuple(map(move, mark.heads)),
                     label_at=(mark.label_at[0] + dx, mark.label_at[1] + dy, mark.label_at[2]))
             for mark in schematic.marks]
    return replace(schematic, items=items, routes=routes, marks=marks, width=schematic.width + dx,
                   height=schematic.height + dy)


# ---------------------------------------------------------------- the marks of the 2D figure
# A Region, a Bracket and a stage's motion mark say what the figure is about (the source, the delay), so the 1D
# draws them round the symbols of the parts they name, at the 1D's own sizes.

MARK_PAD = 4.0                   # between a region's box and the symbols and labels it holds
MARK_CORNER = 3.0                # the radius of a region's corners
MARK_CLEAR = 3.0                 # between a part and the tip of a bracket
MARK_DEPTH = 4.5                 # the length of a bracket's shorter tip
MARK_GAP = 2.0                   # between a mark and its text, and between a part and its motion mark
STAGE_SIZE = 9.0                 # the length of a stage's motion arrow


def _marked(scene: Any, schematic: Schematic) -> Schematic:
    """The schematic with the marks of the 2D figure, on a page that holds them."""

    marks = _marks(scene, schematic)
    if not marks:
        return schematic
    points = [point for mark in marks for point in _mark_points(mark)]
    width = max([schematic.width] + [x + MARGIN for x, _ in points])
    height = max([schematic.height] + [y + MARGIN for _, y in points])
    return replace(schematic, marks=marks, width=width, height=height)


def _marks(scene: Any, schematic: Schematic) -> list[Mark]:
    """The stage marks first, each on a free side of its part; then each region and bracket clears the part with
    its label and its stage mark (``room``)."""

    from optodraw.renderers.svg_renderer import _STAGE_MOUNTS

    items, marks = schematic.items, []
    paths = [link_path(schematic, index) for index in range(len(schematic.links))]
    room = {id(item): _boxes(item) for item in items}
    for item in items:
        mount = getattr(item.component, "base_mount", "post")
        if mount in _STAGE_MOUNTS:
            mark = _stage_mark(item, mount, items, paths, marks)
            points = _mark_points(mark)
            room[id(item)].append((min(x for x, _ in points), min(y for _, y in points), max(x for x, _ in points),
                                   max(y for _, y in points)))
            marks.append(mark)
    for node in scene.walk():
        kind = getattr(node, "component_type", "")
        mark = _region_mark(node, items, room) if kind == "Region" else _bracket_mark(node, items, room) \
            if kind == "Bracket" else None
        if mark is not None:
            marks.append(mark)
    return marks


def _centre(item: Placed) -> tuple[float, float]:
    return item.x + item.symbol.width / 2.0, item.y + item.symbol.height / 2.0


def _region_mark(region: Any, items: list[Placed], room: dict[int, list]) -> Mark | None:
    """A dashed box round the parts whose 2D centres the region's 2D box holds: their symbols, labels and marks."""

    (cx0, cy0), (cx1, cy1) = region.corners
    wx, wy = float(region.world_position.x), float(region.world_position.y)
    held = [item for item in items
            if wx + cx0 <= float(item.component.world_position.x) <= wx + cx1
            and wy + cy0 <= float(item.component.world_position.y) <= wy + cy1]
    if not held:
        return None
    boxes = [box for item in held for box in room[id(item)]]
    x0, y0 = min(b[0] for b in boxes) - MARK_PAD, min(b[1] for b in boxes) - MARK_PAD
    x1, y1 = max(b[2] for b in boxes) + MARK_PAD, max(b[3] for b in boxes) + MARK_PAD
    r = MARK_CORNER
    outline = [(cx + r * math.cos(math.radians(turn + 22.5 * k)), cy + r * math.sin(math.radians(turn + 22.5 * k)))
               for cx, cy, turn in ((x1 - r, y1 - r, 0.0), (x0 + r, y1 - r, 90.0), (x0 + r, y0 + r, 180.0),
                                    (x1 - r, y0 + r, 270.0)) for k in range(5)]
    return Mark("Region", (tuple(outline + outline[:1]),), dashed=True, color=region.color, label=region.label,
                label_at=(x0 + r, y0 - MARK_GAP - 0.2 * LABEL_SIZE, "start"))


def _item_at(items: list[Placed], point: tuple[float, float]) -> Placed | None:
    """The part whose 2D drawing holds a 2D point (an end of a bracket), the nearest centre if several do."""

    inside = []
    for item in items:
        x0, y0, x1, y1 = item.component.drawn_box()
        if x0 <= point[0] <= x1 and y0 <= point[1] <= y1:
            centre = item.component.world_position
            inside.append((math.hypot(float(centre.x) - point[0], float(centre.y) - point[1]), item))
    return min(inside, key=lambda pair: pair[0])[1] if inside else None


def _bracket_mark(bracket: Any, items: list[Placed], room: dict[int, list]) -> Mark | None:
    """The bracket beside the 1D symbols of the parts at its ends, on the same side, each tip clear of its part,
    its label and its stage mark."""

    from optodraw.components.misc import _normal

    ends = [_item_at(items, point) for point in (bracket.start, bracket.end)]
    if ends[0] is None or ends[1] is None or ends[0] is ends[1]:
        return None
    (ax, ay), (bx, by) = _centre(ends[0]), _centre(ends[1])
    nx, ny = _normal((ax, -ay), (bx, -by), bracket.side)          # the side looking along the span, y up as in 2D
    ny = -ny
    reach = [max((x - cx) * nx + (y - cy) * ny for x0, y0, x1, y1 in room[id(item)] for x in (x0, x1) for y in (y0, y1))
             for item, (cx, cy) in zip(ends, ((ax, ay), (bx, by)))]
    first, last = MARK_CLEAR + reach[0], MARK_CLEAR + reach[1]
    far = max(first, last) + MARK_DEPTH
    line = ((ax + nx * first, ay + ny * first), (ax + nx * far, ay + ny * far), (bx + nx * far, by + ny * far),
            (bx + nx * last, by + ny * last))
    mx, my = (ax + bx) / 2.0 + nx * far, (ay + by) / 2.0 + ny * far
    if abs(nx) >= abs(ny):                                         # beside an upright bracket: the text starts at it
        at = (mx + nx * MARK_GAP, my + 0.35 * LABEL_SIZE, "start" if nx > 0 else "end")
    else:                                                          # over or under a flat one: centred, clear of it
        at = (mx, my + MARK_GAP + 0.8 * LABEL_SIZE if ny > 0 else my - MARK_GAP - 0.2 * LABEL_SIZE, "middle")
    return Mark("Bracket", (line,), color=bracket.color, label=bracket.label, label_at=at)


def _stage_mark(item: Placed, mount: str, items: list[Placed], paths: list[list[tuple[float, float]]],
                marks: list[Mark]) -> Mark:
    """The 2D motion mark of a part on a stage, beside its symbol: a double arrow along the part's own axis (a
    translation stage), a cross with a dot (x, y and z) or an arc (rotation). It takes the first side clear of
    the links, the symbols, the labels and the other marks: across the axis away from the label, then the others."""

    from optodraw.check import _hits

    cx, cy = _centre(item)
    turn = math.radians(round(float(item.component.world_transform.rotation_deg.z) / 90.0) * 90.0)
    d = (round(math.cos(turn)), -round(math.sin(turn)))           # the part's own axis on the page, y down
    p = (-d[1], d[0])
    if item.label:
        lx0, ly0, lx1, ly1 = _label_box(*item.label_at, item.label)
        if ((lx0 + lx1) / 2.0 - cx) * p[0] + ((ly0 + ly1) / 2.0 - cy) * p[1] > 0.0:
            p = (-p[0], -p[1])                                     # away from the label
    h, head = STAGE_SIZE / 2.0, 0.22 * STAGE_SIZE
    taken = [box for other in items for box in _boxes(other)]
    lines = paths + [list(line) for mark in marks for line in mark.lines]

    def free(at: tuple[float, float]) -> bool:
        box = (at[0] - h - head, at[1] - h - head, at[0] + h + head, at[1] + h + head)
        return not any(_hits(a, b, box) for line in lines for a, b in zip(line, line[1:])) and not any(
            box[0] < other[2] and other[0] < box[2] and box[1] < other[3] and other[1] < box[3] for other in taken)

    out = MARK_GAP + h + head
    sides = [(p[0] * a + d[0] * b, p[1] * a + d[1] * b) for a, b in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1),
                                                                     (1, -1), (-1, 1), (-1, -1))]
    spots = [(cx + sx * (item.symbol.width / 2.0 + out), cy + sy * (item.symbol.height / 2.0 + out)) if sx and sy
             else (cx + sx * (item.symbol.width / 2.0 + out), cy) if sx else (cx, cy + sy * (item.symbol.height / 2.0 + out))
             for sx, sy in sides]
    mx, my = next((at for at in spots if free(at)), spots[0])

    def tip(x: float, y: float, ux: float, uy: float) -> _Line:     # a head at (x, y) pointing along (ux, uy)
        return ((x, y), (x - head * ux + 0.5 * head * uy, y - head * uy - 0.5 * head * ux),
                (x - head * ux - 0.5 * head * uy, y - head * uy + 0.5 * head * ux))

    def arrow(ux: float, uy: float) -> tuple[_Line, list[_Line]]:
        a, b = (mx - h * ux, my - h * uy), (mx + h * ux, my + h * uy)
        return (a, b), [tip(*b, ux, uy), tip(*a, -ux, -uy)]

    if mount == "rotation_stage":
        r, start, end = 0.75 * h, math.radians(40.0), math.radians(320.0)
        arc = tuple((mx + r * math.cos(start + (end - start) * k / 24), my - r * math.sin(start + (end - start) * k / 24))
                    for k in range(25))
        return Mark(mount, (arc,), (tip(*arc[-1], -math.sin(end), -math.cos(end)),), color="#4a5260")
    line, heads = arrow(*d)
    lines = [line]
    if mount == "xyz_stage":
        across, more = arrow(*p)
        lines.append(across)
        heads += more
        ox, oy, r = mx + 0.62 * h * (d[0] - p[0]), my + 0.62 * h * (d[1] - p[1]), 0.2 * h
        lines.append(tuple((ox + r * math.cos(k * math.pi / 6), oy + r * math.sin(k * math.pi / 6)) for k in range(13)))
        heads.append(tuple((ox + 0.25 * r * math.cos(k * math.pi / 3), oy + 0.25 * r * math.sin(k * math.pi / 3))
                           for k in range(6)))
    return Mark(mount, tuple(lines), tuple(heads), color="#4a5260")


def _build(scene: Any, positions: dict[str, Any] | None, arrangement: str | None) -> Schematic:
    parts = [node for node in scene.walk() if _is_part(node)]
    edges, unresolved = _edges(scene, parts)
    linked = {end for edge in edges for end in (edge[0], edge[2])}
    if any(part.component_type in _ANNOTATIONS and index not in linked for index, part in enumerate(parts)):
        parts = [part for index, part in enumerate(parts) if part.component_type not in _ANNOTATIONS or index in linked]
        edges, unresolved = _edges(scene, parts)
    symbols = [lookup(node) for node in parts]
    used: dict[int, set[str]] = defaultdict(set)
    for start, start_port, end, end_port, _ in edges:
        used[start].add(start_port)
        used[end].add(end_port)
    for index, node in enumerate(parts):              # a plain plate met only on its faces is a partial mirror
        if (node.component_type == "BeamSplitter" and not getattr(node, "dichroic", False)
                and used[index] and used[index] <= {"front", "back"}):
            symbols[index] = lookup(node, ("partialmirror", {}))
    if not parts:
        return Schematic([], [], unresolved, 300.0, 100.0)
    labels = [str(getattr(node, "label", None) or "") for node in parts]     # no label: no text under the symbol
    if _is_bench(edges, "1d" in scene.metadata.get("view_layout", {})):     # light in free space: the bench as built
        directions = _beam_directions(parts, edges)
        symbols = [_beams_meet_at_the_hub(symbol) for symbol in _bench_turns(parts, symbols, edges, directions)]
        spots = _bench_positions(symbols, edges, directions)
        guides: dict[int, list[tuple[float, float]]] = {}
        if "1d" in scene.metadata.get("view_layout", {}):              # only a 1D setting changes the 1D
            from .plan import route_guides, square

            symbols, spots, to_page = _scene_bench_layout(parts, symbols, scene.metadata["view_layout"]["1d"])
            symbols = [_beams_meet_at_the_hub(symbol) for symbol in symbols]
            guides = {index: square([to_page(point) for point in guide])          # the cables keep their 2D path
                      for index, guide in route_guides(scene, parts, edges).items() if edges[index][4] != "free_space"}
        bench = _assemble(scene, parts, symbols, spots, labels, edges, positions, unresolved, sides=True)
        if all(edge[4] == "free_space" for edge in edges):
            return bench
        bench = _line_up_wires(bench, spots)
        moved = {index for index, item in enumerate(bench.items) if (item.x, item.y) != spots[index]}
        return _routed(bench, {index: guide for index, guide in guides.items()
                               if not {edges[index][0], edges[index][2]} & moved})
    else:
        edges = _leaves_on_their_side(symbols, edges)
        drawn = _facing_their_hosts(parts, [symbol.mirrored() if _backwards(symbol, part, edges) else symbol
                                            for part, symbol in enumerate(symbols)], edges, turn_all=False)
        from .plan import plan_fits, plan_layout, route_guides

        auto: Schematic | None = None
        crossed = 0
        if arrangement == "auto" or (arrangement is None and (getattr(scene, "platform", "") != "on_chip"
                                                              or not plan_fits(parts))):
            spots = _auto_positions(drawn, labels, edges)
            auto = _routed(_line_up_wires(_assemble(scene, parts, drawn, spots, labels, edges, positions, unresolved),
                                          spots))
            if arrangement == "auto" or not plan_fits(parts):
                return auto
            crossed = link_crossings(auto)
            if crossed == 0:              # off a chip, the plan replaces it only when the plan crosses fewer links
                return auto

        turned = _facing_their_hosts(parts, [symbol.rotated(round(part.world_transform.rotation_deg.z / 90.0) * 90.0)
                                             for part, symbol in zip(parts, symbols)], edges, turn_all=True)
        # only the linked ports: an unused port on a symbol's top edge sent the label of a part wired from below
        # (a weight bank and its heater pads) under it, onto the wires
        used_now = defaultdict(set)
        for start, start_port, end, end_port, _ in edges:
            used_now[start].add(start_port)
            used_now[end].add(end_port)
        turned = [replace(symbol, ports={n: p for n, p in symbol.ports.items() if n in used_now[i]}) if used_now[i]
                  else symbol for i, symbol in enumerate(turned)]
        spots, guides, over = plan_layout(parts, turned, labels, edges, route_guides(scene, parts, edges), MARGIN,
                                          _footprint, _room)
        plan = _line_up_wires(_assemble(scene, parts, turned, spots, labels, edges, positions, unresolved, over,
                                        sides="set"), spots)
        moved = {index for index, item in enumerate(plan.items) if (item.x, item.y) != spots[index]}
        planned = _routed(plan, {index: guide for index, guide in guides.items()
                                 if not {edges[index][0], edges[index][2]} & moved})  # a part moved by hand: no guide
        return auto if auto is not None and link_crossings(planned) >= crossed else planned


def _assemble(scene: Any, parts: list[Any], symbols: list[Symbol], spots: list[tuple[float, float]],
              labels: list[str], edges: list[_Edge], positions: dict[str, Any] | None,
              unresolved: int, over: set[int] = frozenset(), sides: bool | str = False) -> Schematic:
    """The schematic of parts at their spots, with saved positions on top and labels placed."""

    saved = _saved(scene, positions)
    items = []
    for position, (node, symbol) in enumerate(zip(parts, symbols)):
        key = str(getattr(node, "_id", "") or f"node-{position}")
        x, y = spots[position]
        point = saved.get(key)
        if (isinstance(point, (list, tuple)) and len(point) == 2
                and all(isinstance(value, (int, float)) and math.isfinite(value) for value in point)):
            x, y = max(0.0, float(point[0])), max(0.0, float(point[1]))
        items.append(Placed(key, labels[position], node, symbol, x, y, label_over=position in over))
    links = [Link(*edge) for edge in edges]
    items = _place_labels(items, links, sides)
    return Schematic(items, links, unresolved, *_extent(items))


def _extent(items: list[Placed]) -> tuple[float, float]:
    """The width and height of the page that holds the symbols and their labels."""

    boxes = [_label_box(*item.label_at, item.label) for item in items if item.label]
    width = max([item.x + item.symbol.width for item in items] + [box[2] for box in boxes]) + MARGIN
    height = max([item.y + item.symbol.height + _room(item.symbol, item.label)[1] for item in items]
                 + [box[3] for box in boxes]) + MARGIN
    return width, height


def _boxes(item: Placed, dx: float = 0.0, dy: float = 0.0) -> list[tuple[float, float, float, float]]:
    """The box of a part's symbol and the box of its label, moved by ``dx``, ``dy``."""

    found = [(item.x, item.y, item.x + item.symbol.width, item.y + item.symbol.height)]
    if item.label:
        found.append(_label_box(*item.label_at, item.label))
    return [(x0 + dx, y0 + dy, x1 + dx, y1 + dy) for x0, y0, x1, y1 in found]


def _wire_step(schematic: Schematic, a: int, link: Link) -> tuple[float, float] | None:
    """How far the part at the other end of a wire from part ``a`` must move for the wire to run straight (two
    ports that face each other) or to turn once, clear of both parts and their labels (two ports square to each
    other). None where no step helps: the two ports face the same way, or the far port lies behind ``a``'s."""

    from .router import _out_of

    def lead(i: int, port: tuple[float, float], normal: tuple[float, float]) -> float:
        x, y = _out_of(_boxes(schematic.items[i]), port, normal)        # where the router lets the wire turn
        return abs(x - port[0]) + abs(y - port[1])

    s, n1, e, n2 = link_ends(schematic, link)
    b = link.end
    if link.start != a:
        s, n1, e, n2, b = e, n2, s, n1, link.start
    ahead = (e[0] - s[0]) * n1[0] + (e[1] - s[1]) * n1[1]
    if n1 == (-n2[0], -n2[1]):
        if ahead <= 0.0:
            return None
        return (0.0, s[1] - e[1]) if n1[0] else (s[0] - e[0], 0.0)
    if n1[0] * n2[0] + n1[1] * n2[1]:
        return None
    back = (s[0] - e[0]) * n2[0] + (s[1] - e[1]) * n2[1]       # from the turn into b's port
    out, into = max(0.0, lead(a, s, n1) - ahead), max(0.0, lead(b, e, n2) - back)
    return (n1[0] * out - n2[0] * into, n1[1] * out - n2[1] * into)


def _in_line(schematic: Schematic, link: Link) -> bool:
    """A wire that runs straight, or turns once, where its parts stand."""

    from .router import IN_LINE

    step = _wire_step(schematic, link.start, link) if link.electrical else None
    return step is not None and math.hypot(*step) < IN_LINE


def _line_up_wires(schematic: Schematic, spots: list[tuple[float, float]]) -> Schematic:
    """Parts moved a short step so that their wires read as on a circuit drawing: straight between two ports
    that face each other, one turn between two ports square to each other.

    The optical line stays where it is, and so does a part placed by hand (off its spot). The wires are walked
    breadth first from those parts; a circuit with neither starts from its busiest part. A part a wire reaches
    moves once (see ``_wire_step``), and the parts hung on it alone (a pad, a ground) come along. It moves at
    most ``LINE_UP``, and only where it and its label stay clear of the rest; otherwise it stays, and the next
    wire to it may try. The page grows where a part leaves it (see ``_routed``).
    """

    from .router import CLEAR, IN_LINE

    items = list(schematic.items)
    draft = replace(schematic, items=items)                     # the steps read the parts where they are now
    joined: dict[int, set[int]] = defaultdict(set)
    wires: dict[int, list[Link]] = defaultdict(list)
    for link in schematic.links:
        if link.start != link.end:
            joined[link.start].add(link.end)
            joined[link.end].add(link.start)
            if link.electrical:
                wires[link.start].append(link)
                wires[link.end].append(link)
    settled = {i for i, item in enumerate(items) if (item.x, item.y) != spots[i]}
    settled |= {i for link in schematic.links if not link.electrical for i in (link.start, link.end)}

    def clear(group: set[int], dx: float, dy: float) -> bool:
        mine = [box for i in group for box in _boxes(items[i], dx, dy)]
        rest = [box for i in range(len(items)) if i not in group for box in _boxes(items[i])]
        return not any(p[0] - CLEAR < q[2] and q[0] < p[2] + CLEAR and p[1] - CLEAR < q[3] and q[1] < p[3] + CLEAR
                       for p in mine for q in rest)

    queue = deque(sorted(i for i in settled if i in wires))
    while True:
        while queue:
            a = queue.popleft()
            for link in wires[a]:
                b = link.end if link.start == a else link.start
                if b in settled:
                    continue
                step = _wire_step(draft, a, link)
                if step is not None and math.hypot(*step) >= IN_LINE:
                    dx, dy = step
                    group = {b} | {c for c in joined[b] if joined[c] == {b} and c not in settled}
                    if math.hypot(dx, dy) > LINE_UP or not clear(group, dx, dy):
                        continue
                    for i in group:
                        x, baseline, anchor = items[i].label_at
                        items[i] = replace(items[i], x=items[i].x + dx, y=items[i].y + dy,
                                           label_at=(x + dx, baseline + dy, anchor))
                settled.add(b)
                queue.append(b)
        free = [i for i in wires if i not in settled]
        if not free:
            break
        root = max(free, key=lambda i: (len(wires[i]), -i))
        settled.add(root)
        queue.append(root)
    width, height = _extent(items)
    return replace(schematic, items=items, width=width, height=height)


def _routed(schematic: Schematic, guides: dict[int, list[tuple[float, float]]] | None = None) -> Schematic:
    """The schematic with its waveguides and cables routed as on a chip, the page grown to hold the routes.
    ``guides`` are the 2D routes on the 1D page, for the links to follow. A wire in line follows none, since the
    steps of its 2D route would only bend it, unless it then crosses a link: its 2D route went round for a reason."""

    from .router import route_links

    dx, dy = _page_shift(schematic)          # the router's grid starts at the page corner: a part lined up past it
    schematic = _on_page(schematic)          # comes onto the page first, its guides with it
    guides = {index: [(x + dx, y + dy) for x, y in guide] for index, guide in (guides or {}).items()}
    free = {index for index in guides if _in_line(schematic, schematic.links[index])}
    routes = route_links(schematic, {index: guide for index, guide in guides.items() if index not in free})
    held = {index for index in free if _crosses_a_link(replace(schematic, routes=routes), index)}
    if held:
        routes = route_links(schematic, {index: guide for index, guide in guides.items() if index not in free - held})
    points = [point for route in routes.values() for point in route]
    width = max([schematic.width] + [x + MARGIN for x, _ in points])
    height = max([schematic.height] + [y + MARGIN for _, y in points])
    return replace(schematic, routes=routes, width=width, height=height)


def _crosses_a_link(schematic: Schematic, index: int) -> bool:
    """Link ``index`` as drawn crosses another link that does not share a port with it."""

    from optodraw.check import _crosses

    link = schematic.links[index]
    ends = {(link.start, link.start_port), (link.end, link.end_port)}
    mine = link_path(schematic, index)
    for other, them in enumerate(schematic.links):
        if other == index or ends & {(them.start, them.start_port), (them.end, them.end_port)}:
            continue
        theirs = link_path(schematic, other)
        if any(_crosses(p, q) for p in zip(mine, mine[1:]) for q in zip(theirs, theirs[1:])):
            return True
    return False


def junctions(schematic: Schematic) -> list[tuple[float, float]]:
    """The points where three or more branches of one node meet: a T, or two wires that leave one pin apart. A dot
    marks each, as in KiCad, so a wire that only crosses another never reads as joined to it. Wires that share a
    port are one node; a pin counts as one branch."""

    wires = [i for i, link in enumerate(schematic.links) if link.electrical and len(schematic.routes.get(i, ())) > 1]
    node = {i: i for i in wires}

    def root(i: int) -> int:
        while node[i] != i:
            i = node[i]
        return i

    by_port: dict[tuple[int, str], list[int]] = defaultdict(list)
    for i in wires:
        link = schematic.links[i]
        by_port[(link.start, link.start_port)].append(i)
        by_port[(link.end, link.end_port)].append(i)
    for members in by_port.values():
        for other in members[1:]:
            node[root(other)] = root(members[0])
    nodes: dict[int, list[int]] = defaultdict(list)
    for i in wires:
        nodes[root(i)].append(i)

    def key(point: tuple[float, float]) -> tuple[float, float]:
        return (round(float(point[0]), 6), round(float(point[1]), 6))

    def away(point: tuple[float, float], to: tuple[float, float]) -> tuple[float, float] | None:
        length = math.dist(point, to)
        return None if length < 1e-6 else key(((to[0] - point[0]) / length, (to[1] - point[1]) / length))

    found = []
    for members in nodes.values():
        if len(members) < 2:
            continue
        routes = [schematic.routes[i] for i in members]
        segments = [(p, q) for route in routes for p, q in zip(route, route[1:]) if math.dist(p, q) > 1e-6]
        pins = {key(point) for route in routes for point in (route[0], route[-1])}
        for point in dict.fromkeys(key(point) for route in routes for point in route):
            branches = set()
            for p, q in segments:                               # on the segment, to a hair past either end
                length = math.dist(p, q)
                cross = (q[0] - p[0]) * (point[1] - p[1]) - (q[1] - p[1]) * (point[0] - p[0])
                along = (point[0] - p[0]) * (q[0] - p[0]) + (point[1] - p[1]) * (q[1] - p[1])
                if abs(cross) <= 1e-4 * length and -1e-4 * length <= along <= length * (length + 1e-4):
                    branches |= {d for d in (away(point, p), away(point, q)) if d is not None}
            if len(branches) + (point in pins) >= 3:
                found.append(point)
    return found


def link_path(schematic: Schematic, index: int) -> list[tuple[float, float]]:
    """The drawn path of link ``index``: its square route, or points along its curve when it has none."""

    if index in schematic.routes:
        return list(schematic.routes[index])
    curve = link_curve(schematic, schematic.links[index])
    return [] if curve is None else _cubic_points(curve)


def link_crossings(schematic: Schematic) -> int:
    """How many pairs of links cross each other as drawn (links that share a port do not count)."""

    from optodraw.check import _crosses

    paths = []
    for index in range(len(schematic.links)):
        points = link_path(schematic, index)
        if not points:
            continue
        box = (min(x for x, _ in points), min(y for _, y in points), max(x for x, _ in points), max(y for _, y in points))
        paths.append((box, list(zip(points, points[1:]))))
    count = 0
    for i, (a_box, a) in enumerate(paths):
        for b_box, b in paths[i + 1:]:
            if a_box[2] < b_box[0] or b_box[2] < a_box[0] or a_box[3] < b_box[1] or b_box[3] < a_box[1]:
                continue
            if any(_crosses(s, t) for s in a for t in b):
                count += 1
    return count


def _facing_their_hosts(parts: list[Any], symbols: list[Symbol], edges: list[_Edge], *,
                        turn_all: bool) -> list[Symbol]:
    """A pad in the row under (or over) the part it serves turns so its port faces the contact, and its wire
    runs straight to it. With ``turn_all`` (a plan turned as in 2D) any other driver facing away turns round."""

    sides = ["right", "top", "left", "bottom"]
    symbols = list(symbols)
    for driver, (host, side) in _drivers(symbols, edges).items():
        pairs = [(start_port, end_port) if start == driver else (end_port, start_port)
                 for start, start_port, end, end_port, _ in edges if {start, end} == {driver, host}]
        names = [own for own, _ in pairs]
        port = next((symbols[driver].ports[name] for name in names if name in symbols[driver].ports), None)
        want = "top" if side == "bottom" else "bottom"
        if turn_all:                                       # the plan puts it where the 2D does: over or under
            want = "bottom" if parts[driver].world_position.y > parts[host].world_position.y else "top"
            if parts[driver].component_type in _PADS and pairs:
                want = _looks_at(parts[driver], pairs[0][0], parts[host], pairs[0][1]) or want
        if port is None or port.side == want:
            continue
        if parts[driver].component_type in _PADS:
            symbols[driver] = symbols[driver].rotated((sides.index(want) - sides.index(port.side)) * 90.0)
        elif turn_all and port.side == side:
            symbols[driver] = symbols[driver].rotated(180.0)
    return symbols


def _looks_at(part: Any, own: str, host: Any, theirs: str) -> str | None:
    """The side a pad's 2D port faces, when it faces the contact it serves (its wire leaves straight that way)."""

    try:
        mine, contact = part.world_port(own), host.world_port(theirs)
    except (AttributeError, KeyError, TypeError):
        return None
    angle = math.radians(float(mine.orientation_deg))
    dx, dy = float(contact.center.x - mine.center.x), float(contact.center.y - mine.center.y)
    if math.cos(angle) * dx + math.sin(angle) * dy <= 0.0:
        return None
    return ["right", "top", "left", "bottom"][int(round(float(mine.orientation_deg) / 90.0)) % 4]


def _straight_through(component: Any) -> bool:
    """True for a part the light crosses on one straight line: its ``in`` and ``out`` ports in 2D lie on a line
    through its centre (an iris, a plate, a lens), not offset (a monochromator's exit)."""

    try:
        ports = component.world_ports()
        a, b, c = ports["in"].center, ports["out"].center, component.world_position
    except (AttributeError, KeyError, TypeError):
        return False
    length = math.hypot(float(b.x - a.x), float(b.y - a.y))
    if length < 1e-9:
        return False
    off = abs(float((b.x - a.x) * (a.y - c.y) - (a.x - c.x) * (b.y - a.y))) / length
    return off < 0.05 * length


def hub_paths(schematic: Schematic) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    """The beams inside parts, drawn under their symbols. Inside a splitter: a beam from each port that a link
    uses to the point where the beams meet. Through a part the light crosses straight, from ``in`` to ``out``:
    the beam between them, which an open part (an iris) shows and a filled one hides."""

    paths = []
    beams: dict[int, set[str]] = defaultdict(set)
    for link in schematic.links:
        for index, name in ((link.start, link.start_port), (link.end, link.end_port)):
            item = schematic.items[index]
            port = item.port(name)
            if link.kind == "free_space":
                beams[index].add(name)
            if item.symbol.hub is not None and port is not None:
                path = ((port[0], port[1]), (item.x + item.symbol.hub[0], item.y + item.symbol.hub[1]))
                if path not in paths and path[0] != path[1]:              # a port at the centre needs no path
                    paths.append(path)
    for index, names in beams.items():
        item = schematic.items[index]
        a, b = item.port("in"), item.port("out")
        if {"in", "out"} <= names and a and b and item.symbol.hub is None and _straight_through(item.component):
            paths.append(((a[0], a[1]), (b[0], b[1])))
    return paths


def link_ends(schematic: Schematic, link: Link) -> tuple[tuple[float, float], tuple[float, float],
                                                         tuple[float, float], tuple[float, float]]:
    """Where a link leaves and meets its parts, and the direction it leaves each port in."""

    start_item, end_item = schematic.items[link.start], schematic.items[link.end]
    start = start_item.port(link.start_port) or (start_item.x + start_item.symbol.width,
                                                 start_item.y + start_item.symbol.height / 2.0, "right")
    end = end_item.port(link.end_port) or (end_item.x, end_item.y + end_item.symbol.height / 2.0, "left")

    def side(item: Placed, name: str, here: tuple[float, float, str], there: tuple[float, float, str]) -> str:
        port = item.symbol.ports.get(name)
        if link.electrical and port is not None and here[2] in ("left", "right") and _inside(item.symbol, port):
            return "top" if there[1] < here[1] else "bottom"     # a cable meets an electrode from the side it comes from
        return here[2]

    n1 = _NORMAL[side(start_item, link.start_port, start, end)]
    n2 = _NORMAL[side(end_item, link.end_port, end, start)]
    return (start[0], start[1]), n1, (end[0], end[1]), n2


def link_curve(schematic: Schematic, link: Link) -> tuple[tuple[float, float], ...] | None:
    """The link as a cubic: start, two control points, end.

    A waveguide, a fibre or a cable leaves each port square to its edge and
    bends smoothly. A free-space beam is straight: light in air does not bend.
    """

    start, n1, end, n2 = link_ends(schematic, link)
    if link.kind == "free_space":                           # control points on the segment: a straight line
        return ((start[0], start[1]), (start[0] + (end[0] - start[0]) / 3.0, start[1] + (end[1] - start[1]) / 3.0),
                (start[0] + 2.0 * (end[0] - start[0]) / 3.0, start[1] + 2.0 * (end[1] - start[1]) / 3.0),
                (end[0], end[1]))
    dx, dy = abs(end[0] - start[0]), abs(end[1] - start[1])

    def reach(normal: tuple[float, float]) -> float:        # half the travel along the port's own direction
        return max(6.0, 0.5 * (dx if normal[0] else dy))

    return (
        (start[0], start[1]),
        (start[0] + n1[0] * reach(n1), start[1] + n1[1] * reach(n1)),
        (end[0] + n2[0] * reach(n2), end[1] + n2[1] * reach(n2)),
        (end[0], end[1]),
    )
