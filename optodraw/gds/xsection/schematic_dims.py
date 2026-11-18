"""Dimensions for look A: the rib width, the rib height, the slab height and the gap from the rib to the
nearest metal, drawn as a draughtsman would: extension lines, arrows, and the value in the oxide beside them.

A short dimension gets its arrows outside, pointing in. A dimension whose text finds no clear room in the
oxide is left out rather than drawn over something.
"""

from __future__ import annotations

import math

import shapely
from shapely.geometry import LineString, MultiPolygon

from optodraw.gds.palette import is_metal
from optodraw.gds.xsection.schematic import _polygons, _size
from optodraw.gds.xsection.schematic_labels import fits, oxide_rooms, text_box

_HEAD = 0.8                        # mm, arrowhead length
_HALF = 0.3                        # mm, arrowhead half width
_TAIL = 1.2                        # mm of line behind an arrow that points in
_LINE = 0.15                       # mm, dimension and extension lines
_GAP = 1.2                         # mm from a feature to its dimension line
NAMES = ("rib width", "rib height", "slab height", "metal gap")


def _head(tx: float, ty: float, dx: float, dy: float) -> str:
    """A filled arrowhead with its tip at ``tx``, ``ty``, pointing along the unit vector ``dx``, ``dy``."""

    bx, by = tx - dx * _HEAD, ty - dy * _HEAD
    nx, ny = -dy * _HALF, dx * _HALF
    return f'<path d="M{tx:.3f},{ty:.3f} L{bx + nx:.3f},{by + ny:.3f} L{bx - nx:.3f},{by - ny:.3f} Z" fill="#000000"/>'


def _line(x0: float, y0: float, x1: float, y1: float) -> str:
    return f'<path d="M{x0:.3f},{y0:.3f} L{x1:.3f},{y1:.3f}" stroke="#000000" stroke-width="{_LINE}" fill="none"/>'


def _arrows(x0: float, y0: float, x1: float, y1: float) -> list[str]:
    """A dimension between two points. Short ones get their heads outside, pointing in."""

    length = math.hypot(x1 - x0, y1 - y0)
    dx, dy = (x1 - x0) / length, (y1 - y0) / length
    if length >= 2.5 * _HEAD:
        return [_line(x0, y0, x1, y1), _head(x0, y0, -dx, -dy), _head(x1, y1, dx, dy)]
    reach = _HEAD + _TAIL
    return [_line(x0 - dx * reach, y0 - dy * reach, x1 + dx * reach, y1 + dy * reach),
            _head(x0, y0, dx, dy), _head(x1, y1, -dx, -dy)]


def _text(x: float, y: float, text: str, font: float, family: str, anchor: str) -> str:
    return (f'<text x="{x:.3f}" y="{y:.3f}" font-size="{font:.3f}" font-family="{family}" '
            f'text-anchor="{anchor}">{text}</text>')


def _rib(device, s0: float, s1: float):
    """The rib: the run of the device top nearest the middle of the window, and its height."""

    top = device.bounds[3]
    band = device.intersection(LineString([(s0, top - 1e-4), (s1, top - 1e-4)]))
    runs = [part for part in shapely.get_parts(band) if part.length > 0]
    if not runs:
        return None
    middle = (s0 + s1) / 2.0
    rib = min(runs, key=lambda part: abs((part.bounds[0] + part.bounds[2]) / 2.0 - middle))
    r0, r1 = rib.bounds[0], rib.bounds[2]
    column = device.intersection(LineString([((r0 + r1) / 2, top + 1.0), ((r0 + r1) / 2, device.bounds[1] - 1.0)]))
    longest = max(shapely.get_parts(column), key=lambda part: part.length)
    return r0, r1, top, top - longest.length


def _thickness(device, s: float) -> float:
    hit = device.intersection(LineString([(s, -1e3), (s, 1e3)]))
    return sum(part.length for part in shapely.get_parts(hit))


def dimension_lines(xs, frame, clip, dims, font: float, family: str) -> tuple[list[str], list]:
    """The dimension groups and the page boxes they take (for the labels to keep clear of)."""

    wanted = set(NAMES) if dims == "auto" else {str(name) for name in dims}
    font *= 0.875                                           # values a size under the labels: 7 pt at 8 pt
    device = xs.regions.get("device", MultiPolygon([])).intersection(clip)
    found = _rib(device, frame.s0, frame.s1) if not device.is_empty else None
    if found is None:
        return [], []
    r0, r1, top, bottom = found
    x0, x1, yt, yb = frame.x(r0), frame.x(r1), frame.y(top), frame.y(bottom)
    rooms = oxide_rooms(xs, frame, clip)
    out: list[str] = []
    taken: list = []

    def keep(parts: list[str], text: str, tx: float, ty: float, anchor: str, lines=()) -> bool:
        bounds = text_box(tx, ty, text, font, anchor)
        if not fits(bounds, rooms, taken):
            return False
        taken.append(bounds)
        for lx0, ly0, lx1, ly1 in lines:                    # the lines are kept clear of labels too
            taken.append((min(lx0, lx1) - 0.2, min(ly0, ly1) - 0.2, max(lx0, lx1) + 0.2, max(ly0, ly1) + 0.2))
        out.append('<g class="dim">' + "".join(parts) + _text(tx, ty, text, font, family, anchor) + "</g>")
        return True

    line_y = yt - _GAP
    rib_text = _size(r1 - r0)
    if "rib width" in wanted:
        parts = [_line(x0, yt - 0.3, x0, line_y - 0.5), _line(x1, yt - 0.3, x1, line_y - 0.5),
                 *_arrows(x0, line_y, x1, line_y)]
        keep(parts, rib_text, (x0 + x1) / 2, line_y - 0.7, "middle", [(x0, line_y - 0.5, x1, yt)])
    rib_left = (x0 + x1) / 2 - len(rib_text) * font * 0.3

    metals = [g.intersection(clip) for name, g in xs.regions.items()
              if is_metal(xs.materials.get(name)) and not g.intersection(clip).is_empty]
    gap_side = 1                                            # the metal gap goes on the side of the nearest metal
    nearest = None
    for metal in metals:
        for piece in _polygons(metal):
            m0, _, m1, _ = piece.bounds
            if m0 >= r1:
                candidate = (m0 - r1, 1, m0, piece)
            elif m1 <= r0:
                candidate = (r0 - m1, -1, m1, piece)
            else:
                continue
            if nearest is None or candidate[0] < nearest[0]:
                nearest = candidate
    if nearest is not None:
        gap_side = nearest[1]

    if "rib height" in wanted and top - bottom > 1e-6:      # on the side away from the metal
        side = -gap_side
        ax = (x0 if side < 0 else x1) + side * _GAP
        edge = x0 if side < 0 else x1
        text = _size(top - bottom)
        if side < 0:                                        # the value sits at the end of the top extension line
            tx = min(ax - 0.6, rib_left - 1.6)
            line = (edge - 0.3, yt, tx + 0.3, yt)
            anchor = "end"
        else:
            tx = max(ax + 0.6, rib_left + len(rib_text) * font * 0.6 + 1.6)
            line = (edge + 0.3, yt, tx - 0.3, yt)
            anchor = "start"
        parts = [_line(*line), *_arrows(ax, yb, ax, yt)]
        keep(parts, text, tx, yt - 0.3, anchor, [line, (ax, yb, ax, yt)])

    if "slab height" in wanted:                            # in the slab, across the rib from its height
        side = gap_side
        for reach in (2.0, 4.0, 6.0, 9.0, 12.0, 16.0):
            ax = (x0 if side < 0 else x1) + side * (_GAP + reach)
            s = frame.s0 + (ax - frame.left) / frame.scale
            slab = _thickness(device, s)
            if not 1e-6 < slab < top - bottom - 1e-6:
                continue
            ys = frame.y(bottom + slab)
            text = _size(slab)
            tx, anchor = (ax - 0.6, "end") if side < 0 else (ax + 0.6, "start")
            ty = yb + 0.6 + 0.8 * font + 0.3                # in the BOX, beside the lower arrow
            if keep(_arrows(ax, yb, ax, ys), text, tx, ty, anchor, [(ax, yb + 2.0, ax, ys - 2.0)]):
                break

    if "metal gap" in wanted and nearest is not None:
        gap, side, edge_s, piece = nearest
        xm = frame.x(edge_s)
        xr = x1 if side > 0 else x0
        parts = [*_arrows(xr, line_y, xm, line_y)]
        lines = [(xr, line_y, xm, line_y)]
        m_bottom = frame.y(piece.bounds[1])
        if m_bottom < line_y:                               # a metal above the line: an extension line down
            parts.append(_line(xm, m_bottom + 0.3, xm, line_y + 0.5))
            lines.append((xm, m_bottom, xm, line_y))
        if "rib width" not in wanted:
            parts.append(_line(xr, yt - 0.3, xr, line_y - 0.5))
        text = _size(gap)
        middle, half = (xr + xm) / 2, abs(xm - xr) / 2
        toward = 1.0 if xm > xr else -1.0
        room = half - len(text) * font * 0.3 - 0.5          # the value stays between its extension lines
        spots = [(lift, middle + toward * shift) for lift in (0.0, 1.1 * font, 2.2 * font)
                 for shift in (0.0, 2.0, 4.0, 6.0, -2.0, -4.0) if abs(shift) <= max(room, 0.0)]
        for lift, x in spots:                               # slide along the line first, then lift
            if keep(parts, text, x, line_y - 0.7 - lift, "middle", lines):
                break
    return out, taken
