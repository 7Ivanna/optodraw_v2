"""Beam and FocusingBeam — light paths between components."""

from __future__ import annotations

import math
import warnings
from dataclasses import dataclass, field
from typing import Any

from optodraw.core.component import Component
from optodraw.core.transform import Transform, Vec3

BEAM_OPACITY = 0.5          # a lower beam shows at opacity * (1 - opacity) of its colour, the most it can at 0.5
REFLECTION_COS = 0.5        # light that turns by more than 60 degrees has met a mirror, not a lens or a prism face
MIN_WIDTH_FACTOR = 0.1      # a wide spread still leaves a blue beam some width
THIN_LENSES = ("Lens", "AsphericLens")      # lenses that act in the plane of the drawing


@dataclass(frozen=True)
class BeamStyle:
    """The look all the light of a scene shares. Set it once, ``Scene(beam_style=BeamStyle(opacity=0.4))``, and a
    beam's own value still wins.

    Parameters
    ----------
    opacity : float
        The opacity of every beam and cone that names none.
    scale : float
        Multiplies every drawn width, of beams and of cones.
    by_wavelength : float
        How far the drawn width follows the wavelength: 1 the default, in which infrared is the widest band and
        other colours nest inside it, 0 every colour alike, 2 twice the spread.
    """

    opacity: float = BEAM_OPACITY
    scale: float = 1.0
    by_wavelength: float = 1.0

    def __post_init__(self) -> None:
        if not 0.0 < self.opacity <= 1.0:
            raise ValueError(f"beam opacity must be above 0 and at most 1, got {self.opacity!r}")
        if self.scale <= 0.0:
            raise ValueError(f"beam scale must be > 0, got {self.scale!r}")
        if self.by_wavelength < 0.0:
            raise ValueError(f"by_wavelength must be >= 0, got {self.by_wavelength!r}")

    def width_factor(self, nm: float) -> float:
        """What a beam's ``width`` is multiplied by to draw it at wavelength ``nm``."""

        spread = 1.0 + self.by_wavelength * (wavelength_to_width_factor(nm) - 1.0)
        return self.scale * max(spread, MIN_WIDTH_FACTOR)


DEFAULT_BEAM_STYLE = BeamStyle()


def beam_style(node: Any) -> BeamStyle:
    """The style of the scene ``node`` sits in: its nearest parent that holds one, else the default."""

    while node is not None:
        style = getattr(node, "beam_style", None)
        if style is not None:
            return style
        node = getattr(node, "_parent", None)
    return DEFAULT_BEAM_STYLE


class _SceneOpacity:
    """Light that names no opacity takes the scene's, so one setting changes every beam of a figure."""

    @property
    def opacity(self) -> float:
        return beam_style(self).opacity if self._opacity is None else self._opacity

    @opacity.setter
    def opacity(self, value: float | None) -> None:
        self._opacity = None if value is None else float(value)


def _facing_port(part: Component, other: Any) -> str:
    """The light port of ``part`` nearest a part centre, named port, or coordinate: light never enters or leaves by
    an electrical or thermal port. A part with no light port offers all its ports."""

    if isinstance(other, Component):
        target = other.world_position
        tx, ty = target.x, target.y
    elif isinstance(other, (tuple, list)) and len(other) == 2 and isinstance(other[0], Component):
        target = other[0].world_port(str(other[1])).center
        tx, ty = target.x, target.y
    elif isinstance(other, Vec3):
        tx, ty = other.x, other.y
    else:
        tx, ty = float(other[0]), float(other[1])
    ports = part.world_ports()
    light = {name: port for name, port in ports.items() if port.kind not in ("electrical", "thermal")} or ports
    return min(light, key=lambda name: math.hypot(light[name].center.x - tx, light[name].center.y - ty))


def beam_point(part: Component, port: str) -> Vec3:
    """Where a drawn beam meets ``part`` at ``port``, in the world: the part's own ``beam_point`` when it has one
    (a thin plate meets the beam at its centre), the middle of a lens (it is drawn over the beam, and its faces curve
    away from a port at their tip, so a band cut at the port shows a gap at each corner), else the port's centre."""

    if getattr(part, "component_type", "") in THIN_LENSES:
        return part.world_position
    hook = getattr(part, "beam_point", None)
    local = hook(port) if callable(hook) else None
    if local is None:
        return part.world_port(port).center
    return part.world_transform.apply_to_point(local)


def _raised(point: tuple[float, float, float], lift: float) -> tuple[float, float, float]:
    return (point[0], point[1], point[2] + lift) if lift else point


def _in_lane(points: list[tuple[float, ...]], offset: float) -> list[tuple[float, ...]]:
    """``points`` moved ``offset`` to the left of the way the light runs: see :func:`_lane_walk`."""

    return _lane_walk(points, offset)[0]


def _lane_walk(points: list[tuple[float, ...]], offset: float) -> tuple[list[tuple[float, ...]], list[float]]:
    """``points`` moved ``offset`` to the left of the way the light runs, and the signed offset that leaves each
    point. A hard turn is a reflection: the ray meets the surface where its lane crosses it and leaves on the
    other side of the light, as real light does, so no lane turns behind a mirror. A gentle bend keeps its side."""

    def direction(a: tuple[float, ...], b: tuple[float, ...]) -> tuple[float, float] | None:
        dx, dy = b[0] - a[0], b[1] - a[1]
        span = math.hypot(dx, dy)
        return (dx / span, dy / span) if span > 1e-9 else None    # two points on one spot have no direction

    headings = [direction(a, b) for a, b in zip(points, points[1:])]
    side, moved, sides = float(offset), [], []
    for index, point in enumerate(points):
        if moved and headings[index - 1] is None:                 # the same spot in plan: the same corner
            moved.append((moved[-1][0], moved[-1][1], *point[2:]))
            sides.append(side)
            continue
        arriving = next(filter(None, reversed(headings[:index])), None)
        leaving = next(filter(None, headings[index:]), None)
        one, two = arriving or leaving, leaving or arriving
        if one is None:
            moved.append(point)
            sides.append(side)
            continue
        left = (-one[1], one[0])
        turn = one[0] * two[0] + one[1] * two[1]                  # 1 straight on, -1 straight back
        if turn < REFLECTION_COS:
            surface = (one[0] + two[0], one[1] + two[1])          # the mirror lies along the sum of the two headings
            reach = surface[0] * left[0] + surface[1] * left[1]
            step = (surface[0] / reach, surface[1] / reach) if abs(reach) > 1e-6 else left
            moved.append((point[0] + side * step[0], point[1] + side * step[1], *point[2:]))
            side = -side
            sides.append(side)
            continue
        bisector = (left[0] - two[1], left[1] + two[0])
        moved.append((point[0] + side * bisector[0] / (1.0 + turn), point[1] + side * bisector[1] / (1.0 + turn),
                      *point[2:]))
        sides.append(side)
    return moved, sides


def band_quads(points: list[tuple[float, ...]], width: float) -> list[list[tuple[float, ...]]]:
    """The band of ``width`` along a path that folds at a mirror, one quad to a span, all turning the same way, so
    that drawn as one path a fold is not darker. Empty when nothing folds, and a stroke does the job.

    Each edge of the band is a ray: it stops on the mirror line and leaves on the other side of the light. So the
    band keeps its footprint on the mirror, where a stroke mitres across the other diagonal and turns behind it."""

    one, sides = _lane_walk(points, width / 2.0)
    if len({side > 0.0 for side in sides}) < 2:
        return []
    two = _lane_walk(points, -width / 2.0)[0]

    def turned(quad: list[tuple[float, ...]]) -> list[tuple[float, ...]]:
        area = sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(quad, quad[1:] + quad[:1]))
        return quad if area > 0.0 else quad[::-1]

    spans = [[one[i], one[i + 1], two[i + 1], two[i]] for i in range(len(points) - 1)
             if math.hypot(points[i + 1][0] - points[i][0], points[i + 1][1] - points[i][1]) > 1e-9]
    return [turned(quad) for quad in spans]


HIDDEN_SHARE = 0.4          # a lower beam that shows less than this share of its width reads as gone
HIDDEN_LENGTH = 3.0         # over more than this many of its widths
NESTED_RATIO = 1.05 / (1.0 - HIDDEN_SHARE)      # a band this many times as wide shows round the other


def _beside(s: Any, t: Any) -> tuple[float, float]:
    """How far two straight spans run together, and how far ``t`` lies beside ``s``; (0, 0) when they do not."""

    (ax, ay), (bx, by) = s
    length = math.hypot(bx - ax, by - ay)
    if length < 1e-9:
        return 0.0, 0.0
    ux, uy = (bx - ax) / length, (by - ay) / length
    along = [(x - ax) * ux + (y - ay) * uy for x, y in t]
    across = [(y - ay) * ux - (x - ax) * uy for x, y in t]
    together = min(length, max(along)) - max(0.0, min(along))
    return (together, across[0]) if together > 0.0 and abs(across[0] - across[1]) < 1e-6 else (0.0, 0.0)


def drawn_widths(beams: list[Any]) -> dict[int, float]:
    """The width each of ``beams`` draws at in plan, by ``id``: its ``display_width``, unless a beam of another
    colour runs on its path and would hide it. Then the lower beam widens until it shows round the other, so beams
    on one path nest on the axis. The lower beam is the one with the wider ``display_width``, the first one on a
    tie, so the longer wavelength stays the outer band. A beam in a lane of its own, or already wide enough, keeps
    its width."""

    width = {id(beam): beam.display_width for beam in beams}
    drawn = [beam for beam in beams if not getattr(beam, "envelope", False)]
    legs = {id(beam): beam.legs() for beam in drawn}
    shared = []
    for i, first in enumerate(drawn):
        for second in drawn[i + 1:]:
            if first.color != second.color:
                runs = [run for s in legs[id(first)] for t in legs[id(second)] if (run := _beside(s, t))[0] > 0.0]
                if runs:
                    under, top = (first, second) if first.display_width >= second.display_width else (second, first)
                    shared.append((under, top, runs))
    for _ in range(len(drawn)):          # a beam that widens can come to hide a third: widen until none hides
        grown = False
        for under, top, runs in shared:
            wide, thin = width[id(under)], width[id(top)]
            hidden = sum(together for together, gap in runs
                         if wide - (min(wide / 2.0, abs(gap) + thin / 2.0) - max(-wide / 2.0, abs(gap) - thin / 2.0))
                         < HIDDEN_SHARE * wide)
            if hidden > HIDDEN_LENGTH * wide:
                width[id(under)] = thin * NESTED_RATIO
                grown = True
        if not grown:
            break
    return width


@dataclass
class Beam(_SceneOpacity, Component):
    """A beam path connecting multiple anchor components or coordinates.

    Parameters
    ----------
    anchors : list
        Sequence of Component instances or (x, y[, z]) tuples.
    wavelength : float
        Wavelength in nm (used for color mapping). Default 633 (HeNe red).
    width : float
        Beam stroke width for 2D, or tube radius for 3D.
    opacity : float
        How much of what lies under the beam it covers. A lower beam shows at ``opacity * (1 - opacity)`` of its
        colour: 0.25 at the default of 0.5, the most it can, 0.13 at 0.85. None takes the scene's
        :class:`BeamStyle`.
    offset : float
        The beam's lane, how far it runs to the left of its path, in scene units, looking along the light. It
        holds for the whole path, so the beam leaves its source and meets each optic off centre. Beams of other
        colours on one path need no lane: they draw nested on the axis (:func:`drawn_widths`). A lane is for
        beams that must read apart. A mirror swaps the side, as it does for real light.
    """

    component_type = "Beam"
    anchors: list = field(default_factory=list)
    wavelength: float = 633.0
    width: float = 0.8
    offset: float = 0.0

    def __init__(self, *anchors, wavelength: float = 633.0, width: float = 0.8, opacity: float | None = None,
                 offset: float = 0.0, **kwargs):
        if float(wavelength) <= 0:
            raise ValueError(f"wavelength must be > 0, got {wavelength!r}")
        self.anchors = list(anchors)
        self.wavelength = float(wavelength)
        self.width = width
        self.label = kwargs.get("label", "")
        self.color = kwargs.get("color") or wavelength_to_hex(self.wavelength)
        # an envelope beam is the closed outline BETWEEN a bundle's marginal rays
        # — drawn as a translucent fill (the classic beam cone), not a stroke
        self.envelope = bool(kwargs.get("envelope", False))
        self.opacity = opacity
        self.offset = float(offset)
        self.transform = Transform()
        self._parent = None
        self._id = ""

    @classmethod
    def through(cls, *stops: Any, **kwargs: Any) -> "Beam":
        """A beam through ``stops`` in order, attached at each part's ports.

        Light leaves the first part by the port that faces the next stop, enters the last part by the port
        that faces the stop before, and enters and leaves each part between by its facing ports: a lens by
        its two faces, a mirror by its one. So it never starts inside a part or runs across one. A coordinate
        stop stays as it is. A named-port stop keeps its chosen port.
        Other keywords go to :class:`Beam`."""

        anchors: list[Any] = []
        for index, stop in enumerate(stops):
            if not isinstance(stop, Component) or not stop.ports():
                anchors.append(stop)
                continue
            before = stops[index - 1] if index > 0 else None
            after = stops[index + 1] if index + 1 < len(stops) else None
            names = [_facing_port(stop, other) for other in (before, after) if other is not None]
            for name in dict.fromkeys(names):                   # a mirror's one face appears once
                anchors.append((stop, name))
        return cls(*anchors, **kwargs)

    @property
    def display_width(self) -> float:
        """Rendered line width, scaled by wavelength.

        Longer wavelengths render wider (the diffraction-limited beam grows with
        λ — IR is visibly fat). This also separates overlapping beams of different
        colours: drawn widest-first, each shows as a distinct nested band instead
        of one hiding the others."""

        return self.width * beam_style(self).width_factor(self.wavelength)

    def segments(self) -> list[list[tuple[float, float, float]]]:
        """The drawable runs of this beam: the light BETWEEN parts.

        A beam threaded through a chain names each optic twice — once arriving at
        its ``in`` port, once leaving its ``out`` — and the span between those two
        lies inside the component. Drawing it lays a line across the part's own
        art, so those spans become the gaps between segments. A thin plate meets
        the beam at one point, so it makes no gap and a fold on it stays one run.
        A beam whose anchors are plain coordinates (a traced ray, a hand-drawn
        path) is one segment, unchanged."""

        resolved = self._resolve()
        points = [point for point, _ in resolved]
        owners = [owner for _, owner in resolved]
        runs: list[list[tuple[float, float, float]]] = []
        current = [points[0]] if points else []
        for index in range(1, len(points)):
            inside = (owners[index] is not None and owners[index] == owners[index - 1]
                      and math.dist(points[index], points[index - 1]) > 1e-9)
            if inside:
                if len(current) > 1:
                    runs.append(current)
                current = [points[index]]
            else:
                current.append(points[index])
        if len(current) > 1:
            runs.append(current)
        return runs

    def legs(self) -> list[tuple[tuple[float, float], tuple[float, float]]]:
        """The straight spans this beam draws, in the order the light runs them, in plan."""

        return [((float(a[0]), float(a[1])), (float(b[0]), float(b[1]))) for run in self.segments()
                for a, b in zip(run, run[1:]) if math.hypot(b[0] - a[0], b[1] - a[1]) > 1e-9]

    def resolve_points(self, heights: Any = None) -> list[tuple[float, float, float]]:
        """Resolve anchor positions in world space.

        Anchors may be a ``Component`` (its beam anchor point), a
        ``(Component, port_name)`` pair (the port's world position — the
        physically correct attachment point), a coordinate tuple, or a ``Vec3``.
        ``heights`` (a :class:`~optodraw.core.beam_heights.BeamHeights`) raises each point to the
        height its part stands at in 3D, and gives each periscope the rise its raised run asks for.
        """
        return [point for point, _ in self._resolve(heights)]

    def _resolve(self, heights: Any = None) -> list[tuple[tuple[float, float, float], int | None]]:
        """Each resolved point with the part whose port it is (None for any other anchor)."""

        out: list[tuple[tuple[float, float, float], int | None]] = []
        previous = None
        for index, a in enumerate(self.anchors):
            lift = heights.anchor_lift(self, index) if heights is not None else 0.0
            if isinstance(a, (tuple, list)) and len(a) == 2 and isinstance(a[0], Component):
                component, port_name = a
                part = heights.part(component) if heights is not None else component
                # between two ports of one part, the beam follows the part's own path (a periscope's mirrors)
                if previous is not None and previous[0] is component and hasattr(part, "beam_path_between"):
                    inside = part.beam_path_between(str(previous[1]), str(port_name)) or []
                    out.extend((_raised(part.world_transform.apply_to_point(Vec3(*p)).as_tuple(), lift),
                                id(component)) for p in inside)
                # a part the light visibly crosses (an iris) owns no span: the beam is drawn through it
                owner = None if getattr(component, "beam_passes", False) else id(component)
                out.append((_raised(beam_point(part, str(port_name)).as_tuple(), lift), owner))
                previous = (component, port_name)
                continue
            previous = None
            if isinstance(a, Component):
                out.append((_raised(a.beam_anchor_point().as_tuple(), lift), None))
            elif isinstance(a, (tuple, list)):
                if len(a) == 2:
                    out.append(((a[0], a[1], lift), None))
                elif len(a) == 3:
                    out.append((tuple(a), None))
                else:
                    raise TypeError(f"Beam coordinate anchor must have 2 or 3 values, got {len(a)}")
            elif isinstance(a, Vec3):
                out.append((a.as_tuple(), None))
            else:
                raise TypeError(f"Unsupported anchor type: {type(a)}")
        if self.offset:
            moved = _in_lane([point for point, _ in out], self.offset)
            out = [(point, owner) for point, (_, owner) in zip(moved, out)]
        return out

    def to_dict(self) -> dict[str, Any]:
        """Serialize the beam path for renderers and MCP responses."""

        return {
            "type": "Beam",
            "wavelength": self.wavelength,
            "width": self.width,
            "color": self.color,
            "points": self.resolve_points(),
        }


@dataclass
class FocusingBeam(_SceneOpacity, Component):
    """A beam envelope that converges/diverges between two anchors. ``opacity`` and ``offset`` work as on a
    :class:`Beam`."""

    component_type = "FocusingBeam"
    anchor1: Any = None
    anchor2: Any = None
    width1: float = 5.0
    width2: float = 0.0
    wavelength: float = 633.0
    offset: float = 0.0

    def __init__(self, anchor1, anchor2, width1=5.0, width2=0.0, wavelength=633.0,
                 opacity=None, offset=0.0, **kwargs):
        if float(wavelength) <= 0:
            raise ValueError(f"wavelength must be > 0, got {wavelength!r}")
        self.anchor1 = anchor1
        self.anchor2 = anchor2
        self.width1 = width1
        self.width2 = width2
        self.wavelength = float(wavelength)
        self.color = wavelength_to_hex(self.wavelength)
        self.opacity = opacity
        self.offset = float(offset)
        self.label = kwargs.get("label", "")
        self.transform = Transform()
        self._parent = None
        self._id = ""

    def endpoints(self) -> tuple[Vec3, Vec3]:
        """The two anchors in world space, whatever form they were given in."""

        def resolve(anchor) -> Vec3:
            if isinstance(anchor, Component):
                return anchor.beam_anchor_point()
            if isinstance(anchor, Vec3):
                return anchor
            if isinstance(anchor, (tuple, list)):
                if len(anchor) == 2 and isinstance(anchor[0], Component):
                    return beam_point(anchor[0], str(anchor[1]))
                if len(anchor) == 2:
                    return Vec3(anchor[0], anchor[1], 0.0)
                if len(anchor) == 3:
                    return Vec3(*anchor)
                raise TypeError(f"Focusing beam coordinate anchor must have 2 or 3 values, got {len(anchor)}")
            raise TypeError(f"Unsupported focusing beam anchor type: {type(anchor)}")

        start, end = resolve(self.anchor1), resolve(self.anchor2)
        if self.offset:
            return tuple(Vec3(*point) for point in _in_lane([start.as_tuple(), end.as_tuple()], self.offset))
        return start, end

    def _widen(self) -> float:
        """A cone's widths are drawn as given, so a style widens it by what it does to a beam of this colour."""

        return beam_style(self).width_factor(self.wavelength) / wavelength_to_width_factor(self.wavelength)

    @property
    def display_width(self) -> float:
        """The wide end as drawn: a cone nests among the beams by this, widest first, as a band does."""

        return max(self.width1, self.width2) * self._widen()

    def corners(self) -> list[tuple[float, float]]:
        """The four corners of the drawn envelope, in order, y-up.

        Every renderer draws this shape, and each used to work it out again:
        resolve the anchors, take the unit perpendicular, step out half a width
        at each end. Same trapezoid, two chances to disagree about it.
        Empty when the anchors coincide and there is no direction to be had.
        """

        start, end = self.endpoints()
        dx, dy = end.x - start.x, end.y - start.y
        length = math.hypot(dx, dy)
        if length < 1e-6:
            return []
        nx, ny = -dy / length, dx / length  # unit perpendicular
        half1, half2 = self.width1 * self._widen() / 2.0, self.width2 * self._widen() / 2.0
        return [
            (start.x + nx * half1, start.y + ny * half1),
            (start.x - nx * half1, start.y - ny * half1),
            (end.x - nx * half2, end.y - ny * half2),
            (end.x + nx * half2, end.y + ny * half2),
        ]

    def to_dict(self) -> dict[str, Any]:
        """Serialize focusing-beam metadata for downstream renderers."""

        return {
            "type": "FocusingBeam",
            "wavelength": self.wavelength,
            "width1": self.width1,
            "width2": self.width2,
            "color": self.color,
        }


# -- A beam shaped by its lenses ---------------------------------------------

def _lens_at(anchor: Any) -> Component | None:
    """The lens or objective at an anchor, else None. A lens with no focal length does nothing to the beam."""

    part = anchor[0] if isinstance(anchor, (tuple, list)) and len(anchor) == 2 else anchor
    kind = getattr(part, "component_type", "")
    return part if kind == "Objective" or (kind in THIN_LENSES and getattr(part, "focal_length", None)) else None


def _length(points: list[tuple[float, ...]]) -> float:
    return sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(points, points[1:]))


def _along(points: list[tuple[float, ...]], share: float) -> tuple[float, ...]:
    """The point ``share`` of the way along ``points``."""

    left = max(share, 0.0) * _length(points)
    for a, b in zip(points, points[1:]):
        step = math.hypot(b[0] - a[0], b[1] - a[1])
        if left <= step and step > 0.0:
            return tuple(p + (q - p) * left / step for p, q in zip(a, b))
        left -= step
    return points[-1]


def lens_beam(*stops: Any, width: float = 0.8, mm_per_unit: float = 1.0, wavelength: float = 633.0,
              opacity: float | None = None, offset: float = 0.0, label: str = "") -> list[Any]:
    """One beam whose drawn width follows the lenses on its way, as a list of :class:`Beam` and
    :class:`FocusingBeam`: a new piece at each lens and at each focus. ``stops`` are as in :meth:`Beam.through`.

    ``width`` is the drawn width at the start, so it is the display scale: each later width keeps the true ratio
    to it. A collimated beam enters, and an edge ray runs through each thin lens, so a focus has no width.
    ``mm_per_unit`` is the length of one scene unit, for focal lengths on a drawing that is not to scale: a 150 mm
    telescope drawn 24 units long takes ``mm_per_unit=6.25``. An objective focuses on its own ``focus_point()``,
    which is already in scene units.

    The pieces are made once: make them after the parts are in place. A lane (``offset``) stays beside the light
    and changes side at a mirror. Where a mirror folds a cone, the two cones meet in the light's own plane only
    with no lane.
    """

    if mm_per_unit <= 0.0:
        raise ValueError(f"mm_per_unit must be > 0, got {mm_per_unit!r}")
    plain: list[Any] = []
    for stop in stops:                                        # a lens is one stop, however its ports are named
        lens = _lens_at(stop)
        if lens is None:
            plain.append(stop)
        elif not plain or plain[-1] is not lens:
            plain.append(lens)
    anchors = Beam.through(*plain).anchors
    if len(anchors) < 2:
        raise ValueError("a beam needs at least two stops")
    spans = [[tuple(point) for point in Beam(a, b).resolve_points()] for a, b in zip(anchors, anchors[1:])]
    path, starts = list(spans[0][:1]), [0]
    for span in spans:
        path += span[1:]
        starts.append(len(path) - 1)
    sides = _lane_walk(path, 1.0)[1]
    scale = width * wavelength_to_width_factor(wavelength)    # a cone draws its width as given; a beam scales it
    shared = {"wavelength": wavelength, "opacity": opacity}
    pieces: list[Any] = []

    def beam(run: list[Any], first: int, height: float) -> None:
        pieces.append(Beam(*run, width=width * abs(height), offset=offset * sides[starts[first]], **shared))

    def cone(a: Any, b: Any, first: int, one: float, two: float) -> None:
        pieces.append(FocusingBeam(a, b, width1=scale * abs(one), width2=scale * abs(two),
                                   offset=offset * sides[starts[first]], **shared))

    def to_plane(anchor: Any, point: tuple[float, ...]) -> float:
        """How far a port lies from its lens plane: the edge ray is measured at the planes, so a cone starts as wide
        as the beam it continues, and a focus lies its focal length from the middle of the lens."""

        lens = _lens_at(anchor)
        if lens is None or lens.component_type == "Objective":
            return 0.0
        centre = lens.world_position
        return math.hypot(point[0] - centre.x, point[1] - centre.y)

    height, slope = 1.0, 0.0                                  # the edge ray: a share of the input, in scene units
    run, first = [anchors[0]], 0
    last = None                                               # the last lens: part, the way since it, flat before it
    for index, span in enumerate(spans):
        a, b = anchors[index], anchors[index + 1]
        lens = _lens_at(a)
        if lens is None or lens is not _lens_at(b):
            near, drawn = to_plane(a, span[0]), _length(span)
            reach = near + drawn + to_plane(b, span[-1])
            end = height + slope * reach
            if last is not None:
                last[1] += reach
            if slope == 0.0:
                run.append(b)
                continue
            if height * end < -1e-12:                         # the focus lies on this span
                focus = _along(span, (height / (height - end) * reach - near) / max(drawn, 1e-9))
                cone(a, focus, index, height, 0.0)
                cone(focus, b, index, 0.0, end)
            else:
                cone(a, b, index, height, end)
            height, run, first = end, [b], index + 1
            continue
        if len(run) > 1:
            beam(run, first, height)
        run, first = [b], index + 1
        if lens.component_type == "Objective":                # its focal length is the drawn way to its focus
            x, y = lens.focus_point()
            nose = lens.world_port("out").center
            slope -= height / math.hypot(x - nose.x, y - nose.y)
            last = None
            continue
        flat = slope == 0.0
        slope -= height * mm_per_unit / float(lens.focal_length)
        slope = 0.0 if abs(slope) < 1e-9 else slope
        if slope and last is not None and last[2]:
            two = float(last[0].focal_length) + float(lens.focal_length)
            names = [getattr(part, "label", "") or part.component_type for part in (last[0], lens)]
            warnings.warn(f"the beam leaves {names[1]} not collimated: {names[0]} and {names[1]} sit {last[1]:.4g} "
                          f"units apart, and a telescope needs {two:g} mm. If the drawing is not to scale, give "
                          f"mm_per_unit={two / last[1]:.4g}", UserWarning, stacklevel=3)
        last = [lens, 0.0, flat]
    if len(run) > 1:
        beam(run, first, height)
    pieces[0].label = label
    return pieces


# -- Wavelength to color / width utilities ---------------------------------

def wavelength_to_width_factor(nm: float) -> float:
    """Relative beam-width multiplier for a wavelength (~1.0 near 530 nm).

    Width grows with wavelength so IR beams render fat and so two/three
    overlapping beams of different colours show as distinct nested bands rather
    than hiding one another. Clamped to a sensible visual range."""

    try:
        nm = float(nm)
    except (TypeError, ValueError):
        return 1.0
    factor = 0.7 + (nm - 400.0) / 1150.0 * 1.9  # 400→0.70, 530→0.91, 700→1.20, 1064→1.80, 1550→2.60
    return min(max(factor, 0.65), 2.8)


def wavelength_to_hex(nm: float) -> str:
    """Approximate visible wavelength (380–780 nm) to hex color."""
    if nm < 380:
        return "#7700ff"
    elif nm < 440:
        r, g, b = (440 - nm) / 60, 0.0, 1.0
    elif nm < 490:
        r, g, b = 0.0, (nm - 440) / 50, 1.0
    elif nm < 510:
        r, g, b = 0.0, 1.0, (510 - nm) / 20
    elif nm < 580:
        r, g, b = (nm - 510) / 70, 1.0, 0.0
    elif nm < 645:
        r, g, b = 1.0, (645 - nm) / 65, 0.0
    elif nm <= 780:
        r, g, b = 1.0, 0.0, 0.0
    else:
        return "#aa0000"

    # Intensity dropoff at edges
    if nm < 420:
        f = 0.3 + 0.7 * (nm - 380) / 40
    elif nm > 700:
        f = 0.3 + 0.7 * (780 - nm) / 80
    else:
        f = 1.0

    r = int(255 * (r * f) ** 0.8)
    g = int(255 * (g * f) ** 0.8)
    b = int(255 * (b * f) ** 0.8)
    return f"#{r:02x}{g:02x}{b:02x}"
