"""One beam height for each run of a beam between periscopes (3D).

A periscope's two mirror mounts slide on its post. The entry mirror sits where the arriving beam runs, and
the exit mirror sits ``rise`` above it, so every part after the periscope rides at the new height. A part in
a run given its own ``beam_height`` sets the height of that run instead, and the exit mirror before it
follows. Heights here are above the bench beam plane, except ``beam_height``, which is above the table like
the scene's own. A traced beam already carries these heights (the tracer links them the same way), so its
parts and periscopes stand where it runs."""

from __future__ import annotations

import copy
import math
import warnings
from dataclasses import dataclass, field
from typing import Any

from optodraw.core.component import Component

_TOL = 1e-6
_LOWEST = 4.0         # the lowest beam height above the table the scene allows


@dataclass
class BeamHeights:
    """Where each part of a scene stands above the bench beam plane, once its beams link them."""

    lifts: dict[int, float] = field(default_factory=dict)                      # id(part) -> height
    periscopes: dict[int, tuple[float, float]] = field(default_factory=dict)   # id -> (entry height, rise)
    anchors: dict[int, list[float]] = field(default_factory=dict)              # id(beam) -> height per anchor

    def lift(self, component: Any) -> float:
        return self.lifts.get(id(component), 0.0)

    def anchor_lift(self, beam: Any, index: int) -> float:
        lifts = self.anchors.get(id(beam))
        return lifts[index] if lifts is not None and index < len(lifts) else 0.0

    def part(self, component: Any) -> Any:
        """The part as it stands: a periscope with its mirrors where the beam meets them. A copy: the scene
        keeps its own."""

        follow = self.periscopes.get(id(component))
        if follow is None:
            return component
        moved = copy.copy(component)
        moved.entry_height, moved.rise = follow
        return moved


def link_beam_heights(beams: Any, plane: float, parts: Any = ()) -> BeamHeights:
    """Give every run of every beam one height, and each periscope the mirror heights that meet it.

    A run's height is the ``beam_height`` of the first part in it that has one; otherwise the beam keeps the
    height it left the periscope before the run at (the bench, for the first run). ``parts`` are the parts a
    traced beam can carry. Where the beam cannot stay level (two set heights in one run, two beams that
    meet one periscope at different heights), the part keeps its height and a warning names it."""

    beams = list(beams)
    heights = BeamHeights()
    meets: dict[int, dict[str, float]] = {}       # id(periscope) -> port -> the height the beam meets it at
    periscopes: dict[int, Any] = {}
    for beam in beams:
        anchors = list(getattr(beam, "anchors", []))
        lifts = [0.0] * len(anchors)
        for left, run, right in _runs(anchors):
            _link_run(heights, meets, periscopes, anchors, lifts, left, run, right, plane)
        heights.anchors[id(beam)] = lifts
    _follow_traces(heights, meets, periscopes, [b for b in beams if _traced(b)], parts, plane)
    for key, periscope in periscopes.items():
        _settle(heights, periscope, meets.get(key, {}))
    return heights


def _owner(anchor: Any) -> tuple[Any, str | None]:
    if isinstance(anchor, Component):
        return anchor, None
    if isinstance(anchor, (tuple, list)) and len(anchor) == 2 and isinstance(anchor[0], Component):
        return anchor[0], str(anchor[1])
    return None, None


def _runs(anchors: list) -> list[tuple[Any, list[int], Any]]:
    """Split a beam's anchors at its periscopes: ((periscope, port in, port out) before the run, anchor
    indices, (periscope, port in) after it)."""

    runs: list[tuple[Any, list[int], Any]] = []
    left, run, index = None, [], 0
    while index < len(anchors):
        part, port = _owner(anchors[index])
        if part is not None and getattr(part, "lifts_beam", False):
            first = port
            while index + 1 < len(anchors) and _owner(anchors[index + 1])[0] is part:
                index += 1
            runs.append((left, run, (part, first)))
            left, run = (part, first, _owner(anchors[index])[1]), []
        else:
            run.append(index)
        index += 1
    runs.append((left, run, None))
    return runs


def _own_height(part: Any) -> float | None:
    """A part's own beam height above the table, or None when it follows the beam."""

    height = getattr(part, "beam_height", None)
    if height is None or getattr(part, "_scene_beam", False):
        return None
    return float(height)


def _name(part: Any) -> str:
    return repr(part.label) if getattr(part, "label", "") else part.component_type


def _meet(meets: dict, periscope: Any, port: str | None, level: float, source: str, plane: float) -> None:
    if port is None:
        return
    known = meets.setdefault(id(periscope), {})
    if port in known and abs(known[port] - level) > _TOL:
        warnings.warn(f"{source}, but {_name(periscope)} already meets another beam at {plane + known[port]:g}: "
                      "the beam bends there", stacklevel=5)
        return
    known[port] = level


def _link_run(heights, meets, periscopes, anchors, lifts, left, run, right, plane) -> None:
    pins = [(part, own - plane) for part, own in
            ((part, _own_height(part)) for part in (_owner(anchors[i])[0] for i in run) if part is not None)
            if own is not None]
    if left is None and not run:
        return                                     # a beam that starts at a periscope: nothing before it
    level, source = 0.0, f"the bench beam runs at {plane:g}"
    if left is not None:
        periscope, enter, leave = left
        periscopes[id(periscope)] = periscope
        known = meets.get(id(periscope), {})
        sign = {("in", "out"): 1.0, ("out", "in"): -1.0}.get((enter, leave), 0.0)
        if leave in known:
            level = known[leave]
        elif sign and enter in known:
            level = known[enter] + sign * periscope.rise         # the exit mirror, rise above the entry one
        elif leave is not None:
            level = periscope.ports()[leave].center.z
        source = f"the beam leaves {_name(periscope)} at {plane + level:g}"
    raised = [part for part in (_owner(anchors[i])[0] for i in run) if part is not None and id(part) in heights.lifts]
    if pins:
        level, source = pins[0][1], f"{_name(pins[0][0])} sets beam_height {plane + pins[0][1]:g}"
    elif raised and left is None:                 # a part an earlier beam placed: this beam starts at its height
        level = heights.lifts[id(raised[0])]
        source = f"{_name(raised[0])} stands at {plane + level:g}"
    if plane + level < _LOWEST - _TOL:
        warnings.warn(f"{source}: that is below the lowest beam height, {_LOWEST:g} above the table", stacklevel=4)
    if left is not None:
        _meet(meets, left[0], left[2], level, source, plane)
    if right is not None:
        periscopes[id(right[0])] = right[0]
        _meet(meets, right[0], right[1], level, source, plane)
    for i in run:
        part = _owner(anchors[i])[0]
        own = _own_height(part) if part is not None else None
        lift = level if own is None else own - plane
        if own is not None and abs(lift - level) > _TOL:
            warnings.warn(f"{source}, but {_name(part)} sets beam_height {own:g}: the beam bends there",
                          stacklevel=4)
        lifts[i] = heights.lifts.setdefault(id(part), lift) if part is not None else level


def _settle(heights: BeamHeights, periscope: Any, known: dict[str, float]) -> None:
    """The periscope's entry mirror where the beam arrives, its exit mirror where the beam leaves."""

    if "in" in known:
        entry = known["in"]
        exit_ = known.get("out", entry + periscope.rise)
    elif "out" in known:
        exit_ = known["out"]
        entry = exit_ - periscope.rise
    else:
        return
    ports = periscope.ports()
    if abs(entry - ports["in"].center.z) > _TOL or abs(exit_ - ports["out"].center.z) > _TOL:
        heights.periscopes[id(periscope)] = (entry, exit_ - entry)


def _traced(beam: Any) -> bool:
    """A beam the ray tracer made: plain points that carry their own heights."""

    anchors = getattr(beam, "anchors", [])
    return bool(anchors) and all(isinstance(a, (tuple, list)) and len(a) == 3
                                 and not isinstance(a[0], Component) for a in anchors)


def _follow_traces(heights: BeamHeights, meets: dict, periscopes: dict, traced: list, parts: Any,
                   plane: float) -> None:
    """Parts and periscopes on a traced beam stand where it runs. A part a chained beam placed keeps that,
    and a part with its own beam height keeps it."""

    if not traced:
        return
    lines = [[tuple(float(v) for v in a) for a in beam.anchors] for beam in traced]
    for part in parts:
        if getattr(part, "lifts_beam", False):
            if id(part) not in meets:
                climb = _climb(part, lines)
                if climb is not None:
                    meets[id(part)] = {"in": climb[0], "out": climb[1]}
                    periscopes[id(part)] = part
        elif id(part) not in heights.lifts:
            z, own = _height_on(part, lines), _own_height(part)
            if own is not None:
                heights.lifts[id(part)] = own - plane
                if z is not None and abs(z - (own - plane)) > 0.05:
                    warnings.warn(f"{_name(part)} sets beam_height {own:g}, but the traced beam passes it at "
                                  f"{plane + z:g}: trace it again", stacklevel=4)
            elif z is not None:
                heights.lifts[id(part)] = z


def _climb(periscope: Any, lines: list) -> tuple[float, float] | None:
    """Mean heights where traced beams start and end the vertical climb at this periscope."""

    centre = periscope.world_position
    reach = getattr(periscope, "aperture", 10.0) / 2.0 + 1.0
    starts, ends = [], []
    for line in lines:
        for a, b in zip(line, line[1:]):
            if math.hypot(b[0] - a[0], b[1] - a[1]) < _TOL and abs(b[2] - a[2]) > _TOL \
                    and math.hypot(a[0] - centre.x, a[1] - centre.y) <= reach:
                starts.append(a[2])
                ends.append(b[2])
    return (sum(starts) / len(starts), sum(ends) / len(ends)) if starts else None


def _height_on(part: Any, lines: list) -> float | None:
    """Mean height of the traced beams where they pass the part's ports (its centre, if it has none)."""

    try:
        ports = list(part.world_ports().values())
    except Exception:
        ports = []
    marks = [(p.center.x, p.center.y, max(float(getattr(p, "width", 0.0) or 0.0) / 2.0, 1.0)) for p in ports]
    if not marks:
        centre = part.world_position
        marks = [(centre.x, centre.y, max(float(getattr(part, "aperture", 2.0) or 2.0) / 2.0, 1.0))]
    found = []
    for x, y, reach in marks:
        for line in lines:
            for a, b in zip(line, line[1:]):
                dx, dy = b[0] - a[0], b[1] - a[1]
                span = dx * dx + dy * dy
                if span < _TOL:
                    continue                       # a climb inside a periscope
                t = max(0.0, min(1.0, ((x - a[0]) * dx + (y - a[1]) * dy) / span))
                if math.hypot(a[0] + t * dx - x, a[1] + t * dy - y) <= reach:
                    found.append(a[2] + t * (b[2] - a[2]))
    return sum(found) / len(found) if found else None
