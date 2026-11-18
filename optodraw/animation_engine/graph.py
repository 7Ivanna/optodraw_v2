"""The signal graph: the parts, and the links between their ports (routes and free-space beams)."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from optodraw.core.beam import Beam, FocusingBeam
from optodraw.core.component import Component, Group
from optodraw.core.routing import Route

from .behaviours import polyline_length
from .behaviours.geometry import N_FIBRE, N_FREE_SPACE, N_SILICON, anchor_xy, port_xy
from .ids import route_id, scene_ids

_STRUCTURE = {"Grid", "OpticalTable", "Breadboard", "Baseplate", "SignalArrow"}
_MEDIUM = {"waveguide": ("waveguide", N_SILICON), "optical": ("waveguide", N_SILICON),
           "fiber": ("fiber", N_FIBRE), "free_space": ("free_space", N_FREE_SPACE),
           "electrical": ("electrical", 0.0)}

End = tuple[str, str]


@dataclass(frozen=True)
class Link:
    id: str
    a: End
    b: End
    points: tuple[tuple[float, float], ...]          # world (x, y) from a to b
    medium: str                                       # waveguide | fiber | free_space | electrical
    group_index: float

    @property
    def length(self) -> float:
        return polyline_length(self.points)

    def far_end(self, end: End) -> End:
        return self.b if end == self.a else self.a


@dataclass
class SignalGraph:
    parts: dict[str, Any]
    links: list[Link]
    _at: dict[End, list[Link]] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        for link in self.links:
            for end in (link.a, link.b):
                self._at.setdefault(end, []).append(link)

    def links_at(self, sid: str, port: str) -> list[tuple[Link, End]]:
        return [(link, link.far_end((sid, port))) for link in self._at.get((sid, port), [])]


def build_graph(scene: Any) -> SignalGraph:
    ids = scene_ids(scene)
    parts: dict[str, Any] = {}
    for node in scene.walk():
        if isinstance(node, (Route, Beam, FocusingBeam, Group)) or getattr(node, "component_type", "") in _STRUCTURE:
            continue
        parts[ids[id(node)]] = node
    links: list[Link] = []
    seen: set[frozenset] = set()
    for node in scene.walk():
        found = [_route_link(node, ids)] if isinstance(node, Route) else (
            _beam_links(node, ids) if isinstance(node, (Beam, FocusingBeam)) else [])
        for link in found:
            if link is None:
                continue
            key = frozenset((link.a, link.b))
            if key not in seen:
                seen.add(key)
                links.append(link)
    return SignalGraph(parts, links)


def _route_link(route: Route, ids: dict[int, str]) -> Link | None:
    start, end = route.start_component, route.end_component
    if start is None or end is None or id(start) not in ids or id(end) not in ids:
        return None
    if not route.start_port or not route.end_port:
        return None
    medium, index = _MEDIUM.get(route.kind, ("waveguide", N_SILICON))
    points = tuple((float(p[0]), float(p[1])) for p in route.resolve_points())
    return Link(route_id(ids[id(route)]), (ids[id(start)], route.start_port), (ids[id(end)], route.end_port),
                points, medium, index)


def _beam_links(beam: Beam | FocusingBeam, ids: dict[int, str]) -> list[Link]:
    """Each pair of neighbouring anchors on two different parts is a free-space link."""

    anchors = []
    for anchor in beam.anchors if isinstance(beam, Beam) else (beam.anchor1, beam.anchor2):
        if isinstance(anchor, (tuple, list)) and len(anchor) == 2 and isinstance(anchor[0], Component):
            anchors.append((anchor[0], str(anchor[1])))
        elif isinstance(anchor, Component):
            anchors.append((anchor, None))
        else:
            anchors.append((None, None))                       # a coordinate: drawn, no physics
    links = []
    for k, ((a, port_a), (b, port_b)) in enumerate(zip(anchors, anchors[1:])):
        if a is None or b is None or a is b or id(a) not in ids or id(b) not in ids:
            continue
        port_a = port_a or _nearest_port(a, anchor_xy(b))
        port_b = port_b or _nearest_port(b, anchor_xy(a))
        links.append(Link(f"beam:{ids[id(beam)]}:{k}", (ids[id(a)], port_a), (ids[id(b)], port_b),
                          (port_xy(a, port_a), port_xy(b, port_b)), "free_space", N_FREE_SPACE))
    return links


def _nearest_port(part: Component, towards: tuple[float, float]) -> str:
    candidates = [name for name, port in part.ports().items() if port.kind != "electrical"]
    return min(candidates, key=lambda name: math.dist(port_xy(part, name), towards))
