"""Labels for look A: inside a region when the name fits, else close by in the oxide with a leader, else in a
column beside the figure with a leader. A label never crosses a region edge or another label.

Placement works in millimetres on the page, so a stretched z does not fool the fit test.
"""

from __future__ import annotations

import shapely
from shapely.geometry import LineString, Point, box
from shapely.ops import unary_union

from optodraw.core.markup import plain
from optodraw.gds.palette import canonical, doping_label
from optodraw.gds.xsection.schematic import _INK, _label_text, _polygons

_PAD = 0.3                                     # mm between a label and a region edge


def _to_page(geometry, frame):
    def page(coords):
        out = coords.copy()
        out[:, 0] = frame.left + (coords[:, 0] - frame.s0) * frame.scale
        out[:, 1] = frame.ys(coords[:, 1])
        return out

    return shapely.transform(geometry, page)


def oxide_rooms(xs, frame, clip) -> list:
    """The oxide regions on the page (mm): the room where a label or a dimension text may sit. A break in the
    height scale can fold a region's outline on the page; the folded room is mended, so GEOS takes it."""

    rooms = []
    for name, geometry in xs.regions.items():
        if canonical(xs.materials.get(name, name)) != "sio2":
            continue
        for polygon in _polygons(geometry.intersection(clip)):
            room = _to_page(polygon, frame)
            rooms += [room] if room.is_valid else _polygons(shapely.make_valid(room).buffer(0))
    return rooms


def fits(box_mm, rooms, placed) -> bool:
    """True when the page box lies in one room, a pad clear of its edges, and clear of the placed boxes."""

    return _free(box_mm, placed) and _inside(box_mm, rooms)


def text_box(x: float, y: float, text: str, font: float, anchor: str = "middle") -> tuple[float, float, float, float]:
    """The box a label takes on the page: ``x``, ``y`` is the anchor point of the baseline. The markup of a script
    takes no room."""

    width = len(plain(text)) * font * 0.6
    left = x - width / 2 if anchor == "middle" else (x - width if anchor == "end" else x)
    return (left, y - font * 0.8, left + width, y + font * 0.2)


def _pole(piece) -> Point:
    """The point deepest inside ``piece``, and of the points about as deep, the one nearest its middle. It samples a
    grid with shapely's exact contains and distance: polylabel approximates, and its answer moved from one shapely
    release to the next (a long flat slab has a whole line of deepest points, and its label jumped to an end)."""

    import numpy as np

    x0, y0, x1, y1 = piece.bounds
    xs, ys = np.meshgrid(np.linspace(x0, x1, 121), np.linspace(y0, y1, 61))
    xs, ys = xs.ravel(), ys.ravel()
    inside = shapely.contains_xy(piece, xs, ys)
    if not inside.any():                         # a sliver thinner than the grid
        return piece.representative_point()
    depth = np.where(inside, shapely.distance(piece.boundary, shapely.points(xs, ys)), -1.0)
    deep = depth >= depth.max() * 0.97
    middle = piece.centroid
    far = np.where(deep, np.hypot(xs - middle.x, ys - middle.y), np.inf)
    best = int(np.argmin(far))
    return Point(float(xs[best]), float(ys[best]))


def _free(box_mm, placed, across: float = 1.5, up: float = 0.6) -> bool:
    """True when the page box keeps ``across`` mm sideways or ``up`` mm up and down from every placed box,
    so two texts never read as one."""

    x0, y0, x1, y1 = box_mm
    return all(x1 + across <= a or b + across <= x0 or y1 + up <= c or d + up <= y0 for a, c, b, d in placed)


def _inside(box_mm, containers) -> bool:
    shape = box(*box_mm).buffer(_PAD, join_style="mitre")
    return any(container.contains(shape) for container in containers)


def _tip(anchor: Point, box_mm) -> Point:
    """Where a leader from ``anchor`` meets the padded label box."""

    end = box(*box_mm).buffer(_PAD, join_style="mitre").exterior
    return end.interpolate(end.project(anchor))


def _leader(anchor: Point, box_mm) -> str:
    tip = _tip(anchor, box_mm)
    return (f'<path class="leader" d="M{anchor.x:.3f},{anchor.y:.3f} L{tip.x:.3f},{tip.y:.3f}" '
            f'stroke="{_INK}" stroke-width="0.15" fill="none"/>')


def _anchor(piece) -> Point:
    """Where a leader points: the middle of the region's run through the centre of its width."""

    x0, y0, x1, y1 = piece.bounds
    x = (x0 + x1) / 2.0
    hit = piece.intersection(LineString([(x, y0 - 1.0), (x, y1 + 1.0)]))
    runs = [part for part in shapely.get_parts(hit) if part.length > 0]
    if not runs:
        return _pole(piece)
    longest = max(runs, key=lambda part: part.length)
    return longest.interpolate(0.5, normalized=True)


def place_labels(xs, frame, clip, font: float, family: str, width: float,
                 obstacles: list[tuple[float, float, float, float]] | None = None,
                 column: bool = True) -> list[str] | None:
    """One label per region in the window and one per implant. ``obstacles`` are page boxes (mm) that
    labels keep clear of, such as the dimension texts. With ``column=False`` it returns None when a label
    finds no room in the figure, so the caller can make room for the column."""

    out: list[str] = []
    placed = list(obstacles or [])
    leaders: list[LineString] = []
    dopes = [g for g in xs.doping.values() if not g.is_empty]
    doped = unary_union(dopes) if dopes else None
    items = []                                              # (text, region pieces on the page, is a room)
    rooms = oxide_rooms(xs, frame, clip)                    # where a nearby label may sit
    for name, geometry in xs.regions.items():
        text = xs.labels.get(name)
        pieces = [_to_page(p, frame) for p in _polygons(geometry.intersection(clip))]
        if name == "device" and doped is not None:
            bare = geometry.difference(doped)              # the doped parts carry their own labels
            if bare.area > 0.05 * geometry.area:
                pieces = [_to_page(p, frame) for p in _polygons(bare.intersection(clip))]
        if text and pieces:
            items.append((text, pieces, canonical(xs.materials.get(name, name)) == "sio2"))
    for species, geometry in xs.doping.items():
        pieces = [_to_page(p, frame) for p in _polygons(geometry.intersection(clip))]
        if pieces:
            items.append((doping_label(species), pieces, False))

    def put(text: str, x: float, y: float, anchor: Point | None = None, align: str = "middle") -> None:
        bounds = text_box(x, y, text, font, align)
        placed.append(bounds)
        if anchor is not None:
            leaders.append(LineString([anchor, _tip(anchor, bounds)]))
            out.append(_leader(anchor, bounds))
        out.append(_label_text(x, y, text, font, family, align))

    def in_column(text: str, pieces, room: bool = False) -> None:
        edge = frame.x(frame.s1)
        right = edge + 3.0
        anchor = _anchor(max(pieces, key=lambda piece: piece.bounds[2]))    # the piece nearest the column
        if room:                     # an oxide fills round other regions: start where it meets the figure's side
            strip = [part for piece in pieces for part in _polygons(piece.intersection(box(edge - 0.6, -1e6, edge, 1e6)))]
            if strip:
                tallest = max(strip, key=lambda part: part.bounds[3] - part.bounds[1])
                anchor = Point(edge - 0.3, (tallest.bounds[1] + tallest.bounds[3]) / 2.0)
        start = anchor.y + font / 3

        def clear(y: float) -> bool:              # room for the text, and a leader that crosses no other leader
            bounds = text_box(right, y, text, font, "start")
            leader = LineString([anchor, _tip(anchor, bounds)])
            return bounds[1] >= 0.0 and _free(bounds, placed) and not any(leader.crosses(other) for other in leaders)

        # the nearest row up or down, in steps fine enough to find the slot between two other leaders
        steps = [0] + [k * sign for k in range(1, 160) for sign in (-1, 1)]
        y = next((start + k * font * 0.3 for k in steps if clear(start + k * font * 0.3)), None)
        if y is None:
            y = start
            while not _free(text_box(right, y, text, font, "start"), placed):
                y += font * 1.2
        put(text, right, y, anchor, "start")

    # the small regions first, inside when the name fits; the oxide and the BOX take what is left
    outside = []
    for text, pieces, room in items:
        if room:
            continue
        biggest = max(pieces, key=lambda p: p.area)
        spot = _pole(biggest)
        if _clear(text_box(spot.x, spot.y + font / 3, text, font), [biggest], placed, leaders):
            put(text, spot.x, spot.y + font / 3)
        else:
            outside.append((text, _anchor(biggest), biggest, pieces))
    for text, anchor, own, pieces in sorted(outside, key=lambda item: item[1].y):
        spot = _nearby(anchor, text, font, rooms, placed, leaders, own)
        if spot is not None:
            put(text, spot[0], spot[1], anchor)
            continue
        if not column:
            return None
        in_column(text, pieces)
    for text, pieces, room in items:
        if not room:
            continue
        biggest = max(pieces, key=lambda p: p.area)
        spot = _roomy_spot(biggest, text, font, placed, leaders)
        if spot is not None:
            put(text, spot[0], spot[1])
        elif not column:
            return None
        else:
            in_column(text, pieces, room=True)              # never left out: the column, with a leader
    return out


def _clear(box_mm, containers, placed, leaders, across: float = 1.5) -> bool:
    """The box fits in one container, clear of the placed boxes and of every leader."""

    if not (_free(box_mm, placed, across) and _inside(box_mm, containers)):
        return False
    shape = box(*box_mm).buffer(_PAD)
    return not any(shape.intersects(line) for line in leaders)


def _roomy_spot(piece, text: str, font: float, placed, leaders) -> tuple[float, float] | None:
    """A baseline point for the label of a big region: its pole of inaccessibility when that is clear, else
    the clear point nearest to it. It keeps two letters' height sideways from other text, so "BOX" and a
    nearby "Si" never read as one name."""

    pole = _pole(piece)
    x0, y0, x1, y1 = piece.bounds
    step, rise = font * 0.5, font * 0.2          # finer up and down: a band between two metals is barely a line high
    points = [(pole.x, pole.y)] + sorted(
        ((x0 + i * step, y0 + j * rise) for i in range(int((x1 - x0) / step) + 1)
         for j in range(int((y1 - y0) / rise) + 1)),
        key=lambda p: (p[0] - pole.x) ** 2 + (p[1] - pole.y) ** 2)
    for x, y in points:
        if _clear(text_box(x, y + font / 3, text, font), [piece], placed, leaders, across=2.0 * font):
            return x, y + font / 3
    return None


def _nearby(anchor: Point, text: str, font: float, rooms, placed, leaders, own=None) -> tuple[float, float] | None:
    """The closest baseline point near ``anchor`` where the label sits wholly in the oxide, clear of the
    other labels, its leader crossing no other leader and running only through its own region (``own``) and
    the oxide. Up the page (into the cladding) wins a tie."""

    open_ground = unary_union(list(rooms) + ([own.buffer(0.05)] if own is not None else [])).buffer(0.05)

    width = len(plain(text)) * font * 0.6
    candidates = []
    for rise in range(-24, 25):
        for side in range(-12, 13):
            dx, dy = side * 0.25 * width, rise * 0.35 * font
            candidates.append((abs(dx) + abs(dy) + (1.0 if dy > 0 else 0.0), anchor.x + dx, anchor.y + dy + font / 3))
    for _, x, y in sorted(candidates):
        bounds = text_box(x, y, text, font)
        if _clear(bounds, rooms, placed, leaders):
            leader = LineString([anchor, _tip(anchor, bounds)])
            if not any(leader.intersects(box(*other)) for other in placed) and \
                    not any(leader.intersects(other) for other in leaders) and \
                    leader.difference(open_ground).length < 1e-6:                 # not across metal or a via
                return x, y
    return None
