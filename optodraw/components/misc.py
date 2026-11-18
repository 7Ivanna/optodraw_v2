"""Small utility components for alignment, blocking, and beam profiling."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from optodraw.core.component import Component
from optodraw.core.markup import plain
from optodraw.core.ports import Port
from optodraw.core.transform import Transform, Vec3


@dataclass
class Grid(Component):
    """A reference grid for alignment."""

    component_type = "Grid"
    pitch: float = 10.0
    grid_width: float = 100.0
    grid_height: float = 100.0

    def __init__(self, pitch=10.0, width=100.0, height=100.0, **kwargs):
        """Create a scene-aligned reference grid.

        Parameters
        ----------
        pitch : float
            Spacing between grid lines.
        width, height : float
            Total grid extents.
        **kwargs
            Supports ``color``, ``opacity``, and ``label``.
        """

        self.pitch = pitch
        self.grid_width = width
        self.grid_height = height
        self.color = kwargs.get("color", "#000000")
        self.opacity = kwargs.get("opacity", 0.15)
        self.label = kwargs.get("label", "")
        self.transform = Transform()
        self._parent = None
        self._id = ""


NOTE_ANCHORS = ("start", "middle", "end")
NOTE_HEIGHT = 3.0           # scene units at 8 pt: the size of a part label
NOTE_GAP = 1.0              # the room between a line and the text beside it
LETTER_SHARE = 0.62         # a letter's width over the text's height, as the figure gate counts it
MARK_LINE = 0.25            # scene units at 8 pt: the line of a callout, a bracket or a link
LEADER_GAP = 0.8            # the room between the text and the start of a leader
DOT_RADIUS = 0.45
DASH = (1.2, 1.0)
ARROW_LENGTH = 1.6
PLACED_ENDS = ((-10.0, -4.0), (10.0, -4.0))     # a span dropped in the editor, measured from its note
PLACED_TARGET = (10.0, -10.0)                   # and a callout's target
PLACED_REGION = (40.0, 24.0)                    # and a region's box, under its name
GLYPH_KINDS = ("pulse", "train", "spectrum", "wave", "spot")
GLYPH_SHAPE = 0.6           # a glyph's height over its width
GLYPH_FILL = 0.3


def _place(target: Any) -> tuple[float, float]:
    """A world point from a part, a ``(part, "port")`` pair or ``(x, y)``. An ``Anchor`` comes back as it is."""

    from optodraw.figure.inset import Anchor

    if isinstance(target, Anchor):
        return target
    if isinstance(target, Component):
        return float(target.world_position.x), float(target.world_position.y)
    first, second = target
    if isinstance(first, Component):
        center = first.world_port(str(second)).center
        return float(center.x), float(center.y)
    return float(first), float(second)


def _held(*values: Any) -> list[Any]:
    """The anchors among ``values``."""

    from optodraw.figure.inset import Anchor

    return [v for v in values if isinstance(v, Anchor)]


def _normal(start: tuple[float, float], end: tuple[float, float], side: str) -> tuple[float, float]:
    """The unit normal on ``side`` of the line, looking from ``start`` to ``end``."""

    if side not in ("left", "right"):
        raise ValueError(f'side must be "left" or "right", got {side!r}')
    length = math.dist(start, end)
    if length == 0.0:
        raise ValueError("the two ends are in the same place")
    turn = 1.0 if side == "left" else -1.0
    return -turn * (end[1] - start[1]) / length, turn * (end[0] - start[0]) / length


def _beside(x: float, y: float, normal: tuple[float, float], reach: float, wide: float = 0.0
            ) -> tuple[tuple[float, float], str]:
    """Where text ``wide`` across stands ``reach`` from a line, and its anchor. Beside a steep line it starts at the
    line; over a flat one it is centred, half its height clear, and a slant takes its corner further off."""

    nx, ny = normal
    anchor = "start" if nx > 0.0 else "end"
    if abs(nx) <= abs(ny):
        anchor, reach = "middle", reach + NOTE_HEIGHT / 2.0 + abs(nx) * wide / 2.0
    return (x + nx * reach, y + ny * reach), anchor


@dataclass
class Note(Component):
    """Free text on a figure: a power on a beam, a spot size, a key. It has no ports and draws in 2D only.

    Parameters
    ----------
    text : str
        What the note says. It prints at the size of the part labels.
    center : tuple
        Where the note stands, y up. ``anchor`` says which point of the text stands there.
    anchor : str
        ``"start"``, ``"middle"`` or ``"end"`` of the text.
    """

    component_type = "Note"
    color: str = "#333333"
    anchor: str = "middle"
    bold: bool = False

    def __init__(self, text="Note", center=(0, 0), angle=0.0, *, color="#333333", anchor="middle", bold=False,
                 label=None):
        if anchor not in NOTE_ANCHORS:
            raise ValueError(f"Note: anchor must be one of {', '.join(NOTE_ANCHORS)}, got {anchor!r}")
        self.label = str(text if label is None else label)        # the editor's name field is the text
        self._center_anchor = center if _held(center) else None
        self.color = color
        self.anchor = anchor
        self.bold = bool(bold)
        self.transform = Transform.from_2d(*self._parse_center(center).as_2d(), angle)
        self._parent = None
        self._id = ""

    def _anchors(self) -> list[Any]:
        """The anchors this mark holds: ``Inset.move_to`` moves the mark with them."""

        return _held(getattr(self, "_center_anchor", None))

    def _saved_params(self) -> dict[str, Any]:
        """The parameters a saved page writes as anchors, so the mark is live after a load: a center given as an
        anchor, with the note's own offset from that place (a note moved by hand keeps where it stands)."""

        anchor = getattr(self, "_center_anchor", None)
        if anchor is None:
            return {}
        (ax, ay), at = anchor.xy(), self.transform.position
        offset = [float(at.x) - ax, float(at.y) - ay]
        return {"center": anchor, **({"center_offset": offset} if any(offset) else {})}

    def annotation_2d(self, scale: float = 1.0) -> dict[str, Any]:
        """What the mark draws beside its text, in its own frame. ``scale`` is the text's size over 8 pt: a line keeps
        its share of the text at any font size."""

        return {"type": "group", "children": []}

    def geometry_2d(self) -> dict[str, Any]:
        return self.annotation_2d()

    def drawn_points(self) -> list[tuple[float, float]]:
        """The world points the drawing reaches: the frame holds them. The text has its own place in the frame."""

        points: list[tuple[float, float]] = []
        for part in self.annotation_2d()["children"]:
            if "points" in part:
                points += part["points"]
            elif part["type"] == "line":
                points += [(part["x1"], part["y1"]), (part["x2"], part["y2"])]
            elif part["type"] == "text":                   # a letter of a mark: its box, as the label gate counts it
                half, tall = len(plain(part["text"])) * LETTER_SHARE * part["size"] / 2.0, part["size"] / 2.0
                points += [(part["x"] - half, part["y"] - tall), (part["x"] + half, part["y"] + tall)]
            else:
                x, y, r = part["cx"], part["cy"], part["r"]
                points += [(x - r, y - r), (x + r, y + r)]
        x0, y0 = float(self.world_position.x), float(self.world_position.y)
        return [(x + x0, y + y0) for x, y in points]

    @property
    def text(self) -> str:
        return self.label

    @text.setter
    def text(self, value: str) -> None:
        self.label = str(value)

    @classmethod
    def on(cls, beam: Any, text: str, *, leg: int = 0, at: float = 0.5, side: str = "left", gap: float = 1.0,
           **kwargs: Any) -> "Note":
        """A note beside one leg of ``beam`` (a beam or a route), in its colour unless ``color`` says otherwise.

        ``leg`` counts the straight spans the beam draws, from 0, and ``at`` is the share of that leg the note
        stands at. ``side`` is ``"left"`` or ``"right"``, looking along the light, and ``gap`` is the room between
        the beam and the text. The place is worked out now: make the note after the parts are in place."""

        legs = beam.legs()
        if not -len(legs) <= leg < len(legs):
            raise ValueError(f"the beam has {len(legs)} straight leg(s), so leg {leg} does not exist")
        (x0, y0), (x1, y1) = legs[leg]
        center, anchor = _beside(x0 + at * (x1 - x0), y0 + at * (y1 - y0), _normal((x0, y0), (x1, y1), side),
                                 float(beam.display_width) / 2.0 + gap)
        kwargs.setdefault("anchor", anchor)
        kwargs.setdefault("color", beam.color)
        return cls(text, center=center, **kwargs)


@dataclass
class Callout(Note):
    """Text joined by a thin line to what it names, with a dot on the place.

    Parameters
    ----------
    text : str
        What the callout says.
    center : tuple
        Where the text stands.
    target : tuple or Component
        What it names: ``(x, y)``, a part, or ``(part, "port")``. The place is worked out now: make the callout after
        the parts are in place. The line stays on that place when the text moves. Left out, it stands beside the text.
    anchor : str
        Which point of the text stands at ``center``. By default the end near the target, so the line leaves there.
    """

    component_type = "Callout"
    target: tuple[float, float] = (10.0, -10.0)

    def __init__(self, text="Callout", center=(0, 0), target=None, angle=0.0, *, color="#333333", anchor=None,
                 bold=False, label=None):
        x, y = self._parse_center(center).as_2d()
        self.target = (x + PLACED_TARGET[0], y + PLACED_TARGET[1]) if target is None else _place(target)
        if anchor is None:
            anchor = "start" if self.target[0] <= x else "end"
        super().__init__(text, center, angle, color=color, anchor=anchor, bold=bold, label=label)

    def _anchors(self) -> list[Any]:
        return super()._anchors() + _held(self.target)

    def annotation_2d(self, scale: float = 1.0) -> dict[str, Any]:
        turn = math.radians(float(self.world_transform.rotation_deg.z))
        c, s = math.cos(turn), math.sin(turn)
        dx, dy = self.target[0] - float(self.world_position.x), self.target[1] - float(self.world_position.y)
        x, y = c * dx + s * dy, c * dy - s * dx
        gap = LEADER_GAP * scale
        if self.anchor == "middle":
            start = (0.0, math.copysign(NOTE_HEIGHT * scale / 2.0 + gap, y))
        else:
            start = (-gap if self.anchor == "start" else gap, 0.0)
        return {"type": "group", "children": [
            {"type": "line", "x1": start[0], "y1": start[1], "x2": x, "y2": y, "stroke": self.color,
             "stroke_width": MARK_LINE * scale},
            {"type": "circle", "cx": x, "cy": y, "r": DOT_RADIUS * scale, "fill": self.color}]}


class _Span(Note):
    """A note with a drawing between two places. The note stands beside the middle of the span. Each end takes
    ``(x, y)``, a part or ``(part, "port")``, worked out now, and the span moves with the note. A saved span gives
    ``center`` and ``ends``, each end measured from the note, so a dragged note brings its span along; an end that
    was an anchor is saved as that anchor and stays on its place."""

    def __init__(self, text, start, end, *, side, reach, color, anchor, bold, label, center, ends):
        if start is None and end is None:
            x, y = self._parse_center((0, 0) if center is None else center).as_2d()
            start, end = (own if _held(own) else (x + own[0], y + own[1]) for own in (PLACED_ENDS if ends is None
                                                                                     else ends))
        first, last = _place((-10.0, 0.0) if start is None else start), _place((10.0, 0.0) if end is None else end)
        first, last = tuple(first), tuple(last)
        wide = len(plain(str(text))) * LETTER_SHARE * NOTE_HEIGHT
        spot, beside = _beside((first[0] + last[0]) / 2.0, (first[1] + last[1]) / 2.0, _normal(first, last, side), reach,
                               wide)
        super().__init__(text, spot if center is None else center, 0.0, color=color, anchor=anchor or beside, bold=bold,
                         label=label)
        self.side = side
        self._held_ends = (start if _held(start) else None, end if _held(end) else None)
        self._span_anchors = _held(start, end)
        x, y = float(self.world_position.x), float(self.world_position.y)
        self._ends = ((first[0] - x, first[1] - y), (last[0] - x, last[1] - y))

    @property
    def ends(self) -> tuple[tuple[float, float], tuple[float, float]]:
        """The two ends as offsets from the note. An end given as an anchor is read from the anchor each time."""

        x, y = float(self.world_position.x), float(self.world_position.y)
        return tuple((a.xy()[0] - x, a.xy()[1] - y) if a is not None else own
                     for a, own in zip(self._held_ends, self._ends))

    @ends.setter
    def ends(self, value) -> None:
        self._ends = tuple(tuple(map(float, end)) for end in value)
        self._held_ends = (None, None)
        self._span_anchors = []

    def _moved(self, step: tuple[float, float]) -> None:
        """The note moved by ``step`` with an anchor: a plain end stays where it was given."""

        self._ends = tuple((own[0] - step[0], own[1] - step[1]) if a is None else own
                           for a, own in zip(self._held_ends, self._ends))

    def _anchors(self) -> list[Any]:
        return super()._anchors() + self._span_anchors

    def _saved_params(self) -> dict[str, Any]:
        out = super()._saved_params()
        if any(held is not None for held in self._held_ends):
            out["ends"] = [held if held is not None else own for held, own in zip(self._held_ends, self._ends)]
        return out

    def _world(self, end: tuple[float, float]) -> tuple[float, float]:
        return end[0] + float(self.world_position.x), end[1] + float(self.world_position.y)

    @property
    def start(self) -> tuple[float, float]:
        return self._world(self.ends[0])

    @property
    def end(self) -> tuple[float, float]:
        return self._world(self.ends[1])


@dataclass
class Bracket(_Span):
    """A square bracket beside a span: "this stretch is the telescope".

    Parameters
    ----------
    text : str
        What the bracket says; it may stay empty.
    start, end : tuple or Component
        The ends of the span: ``(x, y)``, a part, or ``(part, "port")``.
    side : str
        ``"left"`` or ``"right"``, looking from ``start`` to ``end``.
    clear : float
        The room between each part it spans (a point: the span) and the tip of the bracket at that end.
    depth : float
        The length of the shorter tip; the back of the bracket stays parallel to the span.
    reach : tuple
        How far each end's part reaches from the span toward the bracket. By default it is worked out from the
        parts now, so the tips stand ``clear`` of their drawn edges, not of their centres.
    """

    component_type = "Bracket"
    side: str = "left"
    clear: float = 1.0
    depth: float = 1.5
    reach: tuple[float, float] = (0.0, 0.0)

    def __init__(self, text="", start=None, end=None, *, side="left", clear=1.0, depth=1.5, color="#333333",
                 anchor=None, bold=False, label=None, center=None, ends=None, reach=None):
        self.clear, self.depth = float(clear), float(depth)
        self.reach = tuple(float(v) for v in reach) if reach is not None else _reach(start, end, side)
        super().__init__(text, start, end, side=side, reach=self.clear + max(self.reach) + self.depth + NOTE_GAP,
                         color=color, anchor=anchor, bold=bold, label=label, center=center, ends=ends)

    def annotation_2d(self, scale: float = 1.0) -> dict[str, Any]:
        (x0, y0), (x1, y1) = self.ends
        nx, ny = _normal((x0, y0), (x1, y1), self.side)
        first, last = self.clear + self.reach[0], self.clear + self.reach[1]
        far = max(first, last) + self.depth
        return {"type": "group", "children": [{
            "type": "polyline", "stroke": self.color, "stroke_width": MARK_LINE * scale,
            "points": [(x0 + nx * first, y0 + ny * first), (x0 + nx * far, y0 + ny * far),
                       (x1 + nx * far, y1 + ny * far), (x1 + nx * last, y1 + ny * last)]}]}


def _reach(start: Any, end: Any, side: str) -> tuple[float, float]:
    """How far the drawn box of the part at each end reaches from the span toward ``side``; 0 for a plain place."""

    if start is None or end is None:
        return 0.0, 0.0
    first, last = _place(start), _place(end)
    if _held(first, last):
        return 0.0, 0.0
    nx, ny = _normal(first, last, side)
    out = []
    for target, (x, y) in ((start, first), (end, last)):
        part = target if isinstance(target, Component) else target[0] if isinstance(target, (tuple, list)) else None
        if not isinstance(part, Component):
            out.append(0.0)
            continue
        x0, y0, x1, y1 = part.drawn_box()
        out.append(max(0.0, max((cx - x) * nx + (cy - y) * ny for cx in (x0, x1) for cy in (y0, y1))))
    return out[0], out[1]


@dataclass
class DashedLink(_Span):
    """A thin line that ties two places together without being light or a wire: a trigger, a control, the same part.

    Parameters
    ----------
    start, end : tuple or Component
        The ends: ``(x, y)``, a part, or ``(part, "port")``.
    text : str
        Text beside the middle of the line, on ``side``, looking from ``start`` to ``end``.
    dashed : bool
        False draws a solid line.
    arrow : bool
        True ends the line in an arrow head at ``end``.
    """

    component_type = "DashedLink"
    side: str = "left"
    dashed: bool = True
    arrow: bool = False

    def __init__(self, start=None, end=None, *, text="", side="left", dashed=True, arrow=False, color="#555555",
                 anchor=None, bold=False, label=None, center=None, ends=None):
        self.dashed, self.arrow = bool(dashed), bool(arrow)
        super().__init__(text, start, end, side=side, reach=NOTE_GAP, color=color, anchor=anchor, bold=bold, label=label,
                         center=center, ends=ends)

    def annotation_2d(self, scale: float = 1.0) -> dict[str, Any]:
        (x0, y0), (x1, y1) = self.ends
        line = {"type": "polyline", "points": [(x0, y0), (x1, y1)], "stroke": self.color,
                "stroke_width": MARK_LINE * scale}
        if self.dashed:
            line["stroke_dasharray"] = f"{DASH[0] * scale:g} {DASH[1] * scale:g}"
        parts = [line]
        if self.arrow:
            length = math.dist((x0, y0), (x1, y1))
            ux, uy = (x1 - x0) / length, (y1 - y0) / length
            back, half = ARROW_LENGTH * scale, 0.4 * ARROW_LENGTH * scale
            base = (x1 - ux * back, y1 - uy * back)
            line["points"] = [(x0, y0), base]
            parts.append({"type": "polygon", "fill": self.color, "points": [
                (x1, y1), (base[0] - uy * half, base[1] + ux * half), (base[0] + uy * half, base[1] - ux * half)]})
        return {"type": "group", "children": parts}


@dataclass
class SectionMark(_Span):
    """Where a cross-section is cut, on a 2D scene: a line from ``start`` to ``end``, ``name`` past its start and
    ``name′`` past its end, in the colour of the cut lines of a page.

    Parameters
    ----------
    start, end : tuple or Component
        The ends of the cut: ``(x, y)``, a part, ``(part, "port")`` or a named place, ``ring.anchor("gap")``.
    name : str
        The letter of the cut: ``"A"`` draws A and A′.
    """

    component_type = "SectionMark"
    name: str = "A"

    def __init__(self, start=None, end=None, *, name="A", color=None, label=None, center=None, ends=None):
        from optodraw.publication import CUT_COLOR

        self.name = str(name)
        super().__init__("", start, end, side="left", reach=NOTE_GAP, color=color or CUT_COLOR, anchor=None,
                         bold=False, label=label, center=center, ends=ends)

    def annotation_2d(self, scale: float = 1.0) -> dict[str, Any]:
        (x0, y0), (x1, y1) = self.ends
        length = math.dist((x0, y0), (x1, y1))
        ux, uy = (x1 - x0) / length * NOTE_HEIGHT * scale, (y1 - y0) / length * NOTE_HEIGHT * scale
        letters = [(self.name, x0 - ux, y0 - uy), (f"{self.name}′", x1 + ux, y1 + uy)]       # one height past each end
        return {"type": "group", "children": [
            {"type": "polyline", "points": [(x0, y0), (x1, y1)], "stroke": self.color, "stroke_width": MARK_LINE * scale},
            *[{"type": "text", "text": text, "x": x, "y": y, "size": NOTE_HEIGHT, "fill": self.color,
               "text_anchor": "middle"} for text, x, y in letters]]}


@dataclass
class Region(Note):
    """A dashed rounded box round a group of parts, with its name over the top left corner: "transmitter".

    Parameters
    ----------
    parts : list of Component
        What the region holds. The box is the union of their ``drawn_box()``, ``pad`` wider on each side. It is
        worked out now: make the region after the parts are in place. It moves with its name.
    label : str
        The name of the region.
    pad : float
        The room between the parts and the box.
    """

    component_type = "Region"
    pad: float = 3.0
    color: str = "#555555"
    CORNER = 1.5            # the radius of the rounded corners

    def __init__(self, parts=None, label="", *, pad=3.0, color="#555555", bold=False, center=None, corners=None):
        self.pad = float(pad)
        if corners is None and not parts:                  # dropped in the editor: a box under its name
            top = -(NOTE_GAP + NOTE_HEIGHT / 2.0)
            corners = ((-self.CORNER, top - PLACED_REGION[1]), (PLACED_REGION[0] - self.CORNER, top))
        if corners is None:
            boxes = [part.drawn_box() for part in parts]
            x0, y0 = min(b[0] for b in boxes) - self.pad, min(b[1] for b in boxes) - self.pad
            x1, y1 = max(b[2] for b in boxes) + self.pad, max(b[3] for b in boxes) + self.pad
            spot = (x0 + self.CORNER, y1 + NOTE_GAP + NOTE_HEIGHT / 2.0)
            center = spot if center is None else center
            cx, cy = self._parse_center(center).as_2d()
            corners = ((x0 - cx, y0 - cy), (x1 - cx, y1 - cy))
        super().__init__(label, (0, 0) if center is None else center, 0.0, color=color, anchor="start", bold=bold)
        self.corners = tuple(tuple(float(v) for v in corner) for corner in corners)

    def annotation_2d(self, scale: float = 1.0) -> dict[str, Any]:
        (x0, y0), (x1, y1) = self.corners
        r = min(self.CORNER, (x1 - x0) / 2.0, (y1 - y0) / 2.0)
        points = [(cx + r * math.cos(math.radians(turn + 22.5 * k)), cy + r * math.sin(math.radians(turn + 22.5 * k)))
                  for cx, cy, turn in ((x1 - r, y1 - r, 0.0), (x0 + r, y1 - r, 90.0), (x0 + r, y0 + r, 180.0),
                                       (x1 - r, y0 + r, 270.0)) for k in range(5)]
        return {"type": "group", "children": [{
            "type": "polyline", "points": points + points[:1], "stroke": self.color, "stroke_width": MARK_LINE * scale,
            "stroke_dasharray": f"{DASH[0] * scale:g} {DASH[1] * scale:g}"}]}


@dataclass
class Glyph(Note):
    """The state of the signal, drawn beside a beam, so the figure shows what the light carries at that place.

    Parameters
    ----------
    kind : str
        ``"pulse"``, ``"train"`` (a pulse train), ``"spectrum"``, ``"wave"`` (a steady carrier) or ``"spot"`` (a beam
        seen end on).
    center : tuple
        The middle of the glyph, y up.
    size : float
        Its width in scene units; it is 0.6 of that tall. It stays upright on any leg.
    color : str
        Its colour. :meth:`on` takes the beam's.
    """

    component_type = "Glyph"
    kind: str = "pulse"
    size: float = 8.0

    def __init__(self, kind="pulse", center=(0, 0), angle=0.0, *, size=8.0, color="#c0392b", label=None):
        if kind not in GLYPH_KINDS:
            raise ValueError(f"Glyph: kind must be one of {', '.join(GLYPH_KINDS)}, got {kind!r}")
        self.kind, self.size = kind, float(size)
        super().__init__("", center, angle, color=color, label=label)

    def ports(self) -> dict[str, Any]:
        return {}                                             # the default reads ``size`` as an aperture

    @classmethod
    def on(cls, beam: Any, kind: str = "pulse", *, leg: int = 0, at: float = 0.5, side: str = "left", gap: float = 1.0,
           size: float = 8.0, **kwargs: Any) -> "Glyph":
        """A glyph beside one leg of ``beam`` (a beam or a route). ``leg``, ``at``, ``side`` and ``gap`` work as in
        :meth:`Note.on`, and the place is worked out now: make the glyph after the parts are in place."""

        legs = beam.legs()
        if not -len(legs) <= leg < len(legs):
            raise ValueError(f"the beam has {len(legs)} straight leg(s), so leg {leg} does not exist")
        (x0, y0), (x1, y1) = legs[leg]
        nx, ny = _normal((x0, y0), (x1, y1), side)
        reach = float(beam.display_width) / 2.0 + gap + (abs(nx) + abs(ny) * GLYPH_SHAPE) * size / 2.0
        kwargs.setdefault("color", beam.color)
        return cls(kind, center=(x0 + at * (x1 - x0) + nx * reach, y0 + at * (y1 - y0) + ny * reach), size=size, **kwargs)

    def _curve(self) -> list[tuple[float, float]]:
        """The outline of a pulse, a train or a wave, left to right."""

        wide, tall = self.size, self.size * GLYPH_SHAPE
        if self.kind == "wave":
            return [(wide * (i / 64.0 - 0.5), tall / 2.0 * math.sin(i / 64.0 * 6.0 * math.pi)) for i in range(65)]
        crests = [wide * ((k + 0.5) / 4.0 - 0.5) for k in range(4)] if self.kind == "train" else [0.0]
        spread = wide / (2.5 * 2 * len(crests) if self.kind == "train" else 6.0)
        return [(x, -tall / 2.0 + tall * sum(math.exp(-(((x - c) / spread) ** 2)) for c in crests))
                for x in (wide * (i / 240.0 - 0.5) for i in range(241))]

    def annotation_2d(self, scale: float = 1.0) -> dict[str, Any]:
        wide, tall = self.size, self.size * GLYPH_SHAPE
        stroke = {"stroke": self.color, "stroke_width": MARK_LINE * scale}
        if self.kind == "spot":
            rings = [(1.0, 0.25), (0.7, 0.35), (0.4, 0.7)]
            parts = [{"type": "circle", "cx": 0.0, "cy": 0.0, "r": share * tall / 2.0, "fill": self.color, "opacity": look}
                     for share, look in rings]
        elif self.kind == "spectrum":
            parts = [{"type": "polyline", "points": [(-wide / 2.0, -tall / 2.0), (wide / 2.0, -tall / 2.0)], **stroke}]
            for k in range(5):
                x = wide * (k - 2) * 0.2
                top = -tall / 2.0 + tall * math.exp(-((x / (0.35 * wide)) ** 2))
                parts.append({"type": "line", "x1": x, "y1": -tall / 2.0, "x2": x, "y2": top, **stroke})
        elif self.kind == "wave":
            parts = [{"type": "polyline", "points": self._curve(), **stroke}]
        else:
            curve = self._curve()
            parts = [{"type": "polygon", "points": curve, "fill": self.color, "opacity": GLYPH_FILL},
                     {"type": "polyline", "points": curve, **stroke}]
        return {"type": "group", "children": parts}


@dataclass
class Block(Component):
    """A beam block / beam dump."""

    component_type = "Block"
    size: float = 6.0

    def __init__(self, center=(0, 0), angle=0, size=6.0, **kwargs):
        """Create a block or beam dump visual.

        ``size`` controls all three box dimensions. Common visual kwargs include
        ``material_preset``, ``color``, ``opacity``, and ``label``.
        """

        self.size = size
        self.material_preset = kwargs.get("material_preset", "steel")
        self.color = kwargs.get("color", "#222222")
        self.opacity = kwargs.get("opacity", 1.0)
        self.label = kwargs.get("label", "Block")
        self.transform = Transform.from_2d(*self._parse_center(center).as_2d(), angle)
        self._parent = None
        self._id = ""

    def geometry_2d(self) -> dict[str, Any]:
        """A beam-blocker paddle: matte black flag on a post + base, dropped into
        the beam (BeamDump is the horned cavity absorber — this is the simple
        block you park in front of a beam)."""

        s = self.size
        return {
            "type": "group",
            "children": [
                {"type": "rect", "cx": 0.0, "cy": -s * 0.62, "w": s * 0.9, "h": s * 0.18, "fill": "#3f3f46", "stroke": "#1f2937", "stroke_width": 0.08},
                {"type": "rect", "cx": 0.0, "cy": -s * 0.38, "w": s * 0.14, "h": s * 0.34, "fill": "#71717a", "stroke": "#3f3f46", "stroke_width": 0.05},
                {"type": "rect", "cx": 0.0, "cy": s * 0.2, "w": s * 0.74, "h": s * 0.85, "fill": "#0c0d10", "stroke": "#000000", "stroke_width": 0.1},
                {"type": "rect", "cx": 0.0, "cy": s * 0.2, "w": s * 0.6, "h": s * 0.7, "fill": "none", "stroke": "#22242b", "stroke_width": 0.07},
            ],
        }

    def geometry_3d(self) -> dict[str, Any]:
        """Blocker paddle: a thin matte-black flag facing the beam, on a boss. The bench adds the post and its base."""

        s = self.size
        boss = 0.16 * s
        boss_y = -0.225 * s - boss / 2.0
        return {
            "shape": "group",
            "post_at": [0.0, boss_y - boss / 2.0, 0.0],
            "children": [
                {"shape": "box", "role": "flag", "width": s * 0.1, "height": s * 0.85, "depth": s * 0.74, "position": [0.0, s * 0.2, 0.0], "material": {"color": "#0c0d10", "metalness": 0.05, "roughness": 0.96}},
                {"shape": "box", "role": "boss", "width": s * 0.1, "height": boss, "depth": s * 0.24, "position": [0.0, boss_y, 0.0], "material": {"color": "#3f3f46", "metalness": 0.55, "roughness": 0.35, "preset": self.material_preset}},
            ],
        }


@dataclass
class Razor(Component):
    """A razor blade / knife-edge for beam profiling.

    The blade comes up from its holder and its cutting edge stops at ``blade_pos``: the light above the edge runs on."""

    component_type = "Razor"
    beam_passes = True
    blade_pos: float = 0.0
    thickness: float = 2.0
    length: float = 10.0

    def __init__(self, center=(0, 0), angle=0, blade_pos=0.0, **kwargs):
        """Create a knife-edge component for beam profiling diagrams.

        ``blade_pos`` stores the blade position parameter, while ``thickness``
        and ``length`` can be supplied as keyword overrides.
        """

        self.blade_pos = blade_pos
        self.thickness = kwargs.get("thickness", 2.0)
        self.length = kwargs.get("length", 10.0)
        self.color = kwargs.get("color", "#aaaaaa")
        self.opacity = kwargs.get("opacity", 1.0)
        self.label = kwargs.get("label", "")
        self.material_preset = kwargs.get("material_preset", "steel")
        self.transform = Transform.from_2d(*self._parse_center(center).as_2d(), angle)
        self._parent = None
        self._id = ""

    def ports(self) -> dict[str, Port]:
        half, width = self.thickness / 2.0, self.length * 0.42
        return {
            "in": Port("in", Vec3(-half, 0.0, 0.0), orientation_deg=180.0, width=width, kind="free_space"),
            "out": Port("out", Vec3(half, 0.0, 0.0), orientation_deg=0.0, width=width, kind="free_space"),
        }

    def _lift(self, blade: float) -> float:
        """How far a post must lift a blade of this height off the holder, to bring its edge to ``blade_pos``."""

        return max(self.blade_pos - blade + self.length * 0.35, 0.0)

    def geometry_2d(self) -> dict[str, Any]:
        """Knife-edge: a classic double-edge razor blade (slot + pin holes) held
        from below, its top cutting edge sitting at ``blade_pos``."""

        t, L, bp = self.thickness, self.length, self.blade_pos
        bh = L * 0.42  # blade height (real DE blades are ~2:1)
        cy = bp - bh / 2.0
        lift = self._lift(bh)
        return {
            "type": "group",
            "children": [
                # mount: foot, stem and holder, then a post up to the blade
                {"type": "rect", "cx": 0.0, "cy": -L * 0.77, "w": L * 0.4, "h": L * 0.06, "fill": "#94a3b8", "stroke": "#64748b", "stroke_width": 0.05},
                {"type": "rect", "cx": 0.0, "cy": -L * 0.655, "w": L * 0.06, "h": L * 0.17, "fill": "#cbd5e1", "stroke": "#94a3b8", "stroke_width": 0.05},
                {"type": "rect", "cx": 0.0, "cy": -L * 0.46, "w": t * 2.4, "h": L * 0.22, "fill": "#3f3f46", "stroke": "#1f2937", "stroke_width": 0.08},
                *([{"type": "rect", "cx": 0.0, "cy": lift / 2.0 - L * 0.35, "w": t * 0.4, "h": lift, "fill": "#71717a", "stroke": "#3f3f46", "stroke_width": 0.05}] if lift else []),
                # the blade, face-on
                {"type": "rect", "cx": 0.0, "cy": cy, "w": L * 0.92, "h": bh, "fill": "#ccd2d8", "stroke": "#7c8590", "stroke_width": 0.08},
                # center slot + the two pin holes
                {"type": "rect", "cx": 0.0, "cy": cy, "w": L * 0.34, "h": bh * 0.3, "fill": "#eef1f4", "stroke": "#9aa3ad", "stroke_width": 0.05},
                {"type": "circle", "cx": -L * 0.29, "cy": cy, "r": L * 0.045, "fill": "#eef1f4", "stroke": "#9aa3ad", "stroke_width": 0.05},
                {"type": "circle", "cx": L * 0.29, "cy": cy, "r": L * 0.045, "fill": "#eef1f4", "stroke": "#9aa3ad", "stroke_width": 0.05},
                # bright cutting edge along the top (the edge doing the profiling)
                {"type": "rect", "cx": 0.0, "cy": bp - bh * 0.045, "w": L * 0.92, "h": bh * 0.09, "fill": "#f2f5f8", "opacity": 0.9},
            ],
        }

    def geometry_3d(self) -> dict[str, Any]:
        """Knife-edge: a double-edge blade facing the beam, its bright top edge at ``blade_pos``, held from below
        by the two jaws of a clamp. The bench adds the post and its base."""

        t, L, bp = self.thickness, self.length, self.blade_pos
        bh = L * 0.42
        lift = self._lift(bh)
        blade = t * 0.07
        dark = {"color": "#3f3f46", "metalness": 0.55, "roughness": 0.35, "preset": self.material_preset}
        hollow = {"color": "#20242b", "metalness": 0.2, "roughness": 0.7}
        along_x = [0.0, 0.0, math.pi / 2.0]
        cy, jaw = bp - bh / 2.0, L * 0.14
        jaw_y = bp - bh + jaw / 2.0
        return {
            "shape": "group",
            "children": [
                {"shape": "box", "width": t * 2.4, "height": L * 0.2, "depth": L * 0.5, "position": [0.0, -L * 0.45, 0.0], "material": dark},
                *([{"shape": "cylinder", "radius": t * 0.2, "height": lift, "position": [0.0, lift / 2.0 - L * 0.35, 0.0], "material": {"color": "#9aa0a6", "metalness": 0.7, "roughness": 0.22}}] if lift else []),
                # thin blade (thin along the beam axis x), its middle slot and two pin holes showing through
                {"shape": "box", "role": "blade", "width": blade, "height": bh * 0.99, "depth": L * 0.92, "position": [0.0, cy - bh * 0.005, 0.0], "material": {"color": "#ccd2d8", "metalness": 0.88, "roughness": 0.12, "clearcoat": 0.4}},
                {"shape": "box", "role": "slot", "width": blade * 1.1, "height": bh * 0.2, "depth": L * 0.34, "position": [0.0, cy + bh * 0.12, 0.0], "material": hollow},
                *[{"shape": "cylinder", "role": "hole", "radius": L * 0.045, "height": blade * 1.1, "rotation": along_x, "position": [0.0, cy + bh * 0.12, side * L * 0.29], "material": hollow} for side in (-1.0, 1.0)],
                {"shape": "box", "width": t * 0.09, "height": bh * 0.09, "depth": L * 0.9, "position": [0.0, bp - bh * 0.045, 0.0], "material": {"color": "#f2f5f8", "metalness": 0.95, "roughness": 0.05}},
                # the clamp: a jaw on each face of the blade, on top of the holder
                *[{"shape": "box", "role": "jaw", "width": t * 0.4, "height": jaw, "depth": L * 0.7, "position": [side * (blade / 2.0 + t * 0.2), jaw_y, 0.0], "material": dark} for side in (-1.0, 1.0)],
            ],
        }
