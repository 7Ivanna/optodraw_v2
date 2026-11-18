"""The engine's light stays inside the guides a part draws.

``inside_drawn_guides`` takes its reference from the part's drawing, never from the engine's transfers:
the centrelines of ``optical_paths`` for every in-port, and the guide strips in ``geometry_2d`` (shapes
in the part's guide colour; a body wider than three guide widths is a multimode region, not a guide).
"""

from __future__ import annotations

import math
import warnings

import numpy as np
import pytest
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import unary_union

from optodraw.animation3d.rails import layout
from optodraw.animation_engine.behaviours import find_behaviour
from optodraw.animation_engine.behaviours.geometry import cut, local_to_world, port_xy
from optodraw.animation_engine.ids import path_id
from optodraw.components.electronics._shared import ANALOG_BLUE
from optodraw.registry import build_component

from sweep import sweep

DRAWN_TYPES = frozenset({
    "DirectionalCoupler", "MZI", "MZM", "MicroringResonator", "MicroringWeightBank", "PNMicroringModulator",
    "RacetrackResonator", "RingAssistedMZI", "Spiral", "StarCoupler", "TapCoupler", "WaveguideBend", "YBranch"})
SINGLE_MODE_TYPES = frozenset({
    "PhaseShifter", "Taper", "WaveguideCrossing", "EdgeCoupler", "VerticalGratingCoupler",
    "FocusedApodizedGratingCoupler", "TwoDGratingCoupler", "OnChipLaser", "DBRLaser", "SOA",
    "OnChipPhotodetector", "OnChipBalancedPhotodetector", "PolarizationSplitterRotator", "PolarizationRotator",
    "CoherentReceiver", "CoupledRingFilter"})
# Single-mode types whose paths come from their own optical_paths: the strip check holds them to the drawing too.
DRAWN_SINGLE_MODE_TYPES = frozenset({
    "WaveguideCrossing", "PolarizationRotator", "PolarizationSplitterRotator", "CoherentReceiver", "CoupledRingFilter"})
MULTIMODE_TYPES = frozenset({"MMI1x2", "MMI1x4", "MMI2x2", "MMI2x2PowerSplitter", "AWG"})
CHIP_BODY_TYPES = DRAWN_TYPES | SINGLE_MODE_TYPES | MULTIMODE_TYPES

STEP_UM = 0.25
CASES = [(0, False), (90, False), (180, True)]
WAVELENGTH_NM = 1550.0

def _optical_ports(part) -> list[str]:
    return [name for name, port in part.ports().items() if port.kind != "electrical"]


def all_transfers(part) -> list:
    """The engine's transfers at every optical in-port, 1550 nm, default parameters."""

    behaviour = find_behaviour(part)
    assert behaviour is not None, f"no behaviour for {part.component_type}"
    # At 1550 nm only AWG channel o4 lights. The other channels are covered by
    # test_every_drawn_path_stays_on_the_strips_or_in_its_region.
    found = []
    for port in _optical_ports(part):
        found.extend(behaviour.transfers(part, "part", port, WAVELENGTH_NM, {}))
    for emission in behaviour.emissions(part, "part", {}):
        if emission.port.startswith("_"):                  # a source that starts light inside the part
            found.extend(behaviour.transfers(part, "part", emission.port, WAVELENGTH_NM, {}))
    return found


def every_transfer(part) -> list:
    """``all_transfers`` and the transfers at every internal port the light reaches from them (ring loops and the
    couplers between rings), so a coupling inside a part is checked too."""

    behaviour = find_behaviour(part)
    found = all_transfers(part)
    todo, seen = [t.out_port for t in found], set()
    while todo:
        port = todo.pop(0)
        if not port.startswith("_") or port in seen or behaviour.sinks(part, port):
            continue
        seen.add(port)
        more = behaviour.transfers(part, "part", port, WAVELENGTH_NM, {})
        found.extend(more)
        todo.extend(t.out_port for t in more)
    return found


def sections(part) -> list:
    """The part's coupling sections (both directions of travel), default parameters."""

    return find_behaviour(part).sections(part, "part", {})


def drawn_by_sections(part) -> set[str]:
    """The ids of the transfers that the part's sections draw on their rails."""

    return set().union(set(), *(section.replaces for section in sections(part)))


def shown_points(part) -> list:
    """Where the player draws the part's light, as ``(label, polyline)``: each rail of each coupling section, sampled
    as the payload samples it, and each transfer that no section draws, on its own path."""

    rails = [(f"section {i} rail {r}", drawn["points"]) for i, section in enumerate(sections(part))
             for r, drawn in enumerate(layout(section)) if len(drawn["points"]) >= 2]
    hidden = drawn_by_sections(part)
    plain = [(f"{t.in_port}->{t.out_port} {t.name!r}", t.points) for t in every_transfer(part)
             if path_id("part", t.in_port, t.out_port, t.name) not in hidden]
    return rails + plain


def _guide_width(part) -> float:
    return max(float(part.ports()[name].width) for name in _optical_ports(part))


def _weight_bank_colours(part) -> set[str]:
    """The bus colour and each ring's channel colour: the weight bank draws ring k in its resonance colour."""

    from optodraw.components.onchip.rings import _resonance_channel_color

    count = part.ring_count
    return {part.color} | {_resonance_channel_color(part, k / max(count - 1, 1)) for k in range(count)}


# A part that draws its guides in colours other than ``part.color`` (the receiver's body colour is a die tint).
GUIDE_COLOURS_BY_TYPE = {"CoherentReceiver": lambda part: {ANALOG_BLUE}, "MicroringWeightBank": _weight_bank_colours}


def _guide_colours(part) -> set[str]:
    return GUIDE_COLOURS_BY_TYPE.get(part.component_type, lambda part: {part.color})(part)


def _strip_shapes(part, node, out) -> None:
    """World-frame guide strips drawn in the guide colour under ``node`` (a ``geometry_2d`` tree)."""

    kind, colours = node.get("type"), _guide_colours(part)
    if kind == "group":
        for child in node.get("children", []):
            _strip_shapes(part, child, out)
    elif kind == "polygon" and node.get("fill") in colours:
        points = local_to_world(part, [(p[0], p[1]) for p in node["points"]])
        if len(points) >= 3:
            out.append(Polygon(points).buffer(0))
    elif kind == "rect" and node.get("fill") in colours:
        cx, cy, w, h = node["cx"], node["cy"], node["w"], node["h"]
        corners = [(cx - w / 2, cy - h / 2), (cx + w / 2, cy - h / 2), (cx + w / 2, cy + h / 2), (cx - w / 2, cy + h / 2)]
        out.append(Polygon(local_to_world(part, corners)).buffer(0))
    elif kind == "circle" and node.get("stroke") in colours and node.get("fill") in (None, "none"):
        circle = Point(local_to_world(part, [(node["cx"], node["cy"])])[0]).buffer(float(node["r"]), 64)
        out.append(circle.boundary.buffer(float(node["stroke_width"]) / 2.0))
    elif kind in ("polyline", "line") and node.get("stroke") in colours:
        if kind == "line":
            points = [(node["x1"], node["y1"]), (node["x2"], node["y2"])]
        else:
            points = [(p[0], p[1]) for p in node["points"]]
            if node.get("closed"):
                points.append(points[0])
        if len(points) >= 2:
            out.append(LineString(local_to_world(part, points)).buffer(float(node["stroke_width"]) / 2.0))


def region_outlines(part) -> list:
    """World-frame polygons of the multimode regions that the part's own paths name.

    A path entry carries ``"region": {"kind": "mmi" | "slab", "outline": [[x, y], ...]}`` in local
    coordinates. A path that crosses two bodies (the AWG slabs) gives a list of such dicts."""

    found = []
    for port in _optical_ports(part):
        for path in part.optical_paths(port) if hasattr(part, "optical_paths") else []:
            region = path.get("region")
            for one in ([] if region is None else region if isinstance(region, list) else [region]):
                assert one["kind"] in ("mmi", "slab")
                found.append(Polygon(local_to_world(part, one["outline"])).buffer(0))
    return found


def drawn_guide_area(part, with_paths: bool = True):
    """Where the part draws light-carrying guide: optical-path centrelines, thin drawn strips and the
    outline of each multimode region (the light fans across a region, so a point inside it is inside)."""

    half = _guide_width(part) / 2.0
    pieces = []
    for port in _optical_ports(part) if with_paths else []:
        for path in part.optical_paths(port) if hasattr(part, "optical_paths") else []:
            world = local_to_world(part, path["pts"])
            if len(world) >= 2:
                pieces.append(LineString(world).buffer(half))
    strips: list = []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")                    # the AWG layout warns about its arm spread
        _strip_shapes(part, part.geometry_2d(), strips)
    radius = 1.5 * _guide_width(part)                      # wider than three guide widths: a multimode body
    # A body wider than three guide widths is a multimode region, unless it is a small junction: no longer
    # than five guide widths (the crossing's centre square is 4.4), which light crosses straight through.
    junction = 5.0 * _guide_width(part)
    pieces += region_outlines(part)
    pieces += [strip if max(strip.bounds[2] - strip.bounds[0], strip.bounds[3] - strip.bounds[1]) <= junction
               else strip.difference(strip.buffer(-radius).buffer(radius)) for strip in strips]
    return unary_union(pieces) if pieces else Polygon()


def inside_drawn_guides(part, points, tolerance: float = 1e-6, with_paths: bool = True) -> bool:
    """True when every sample of ``points`` (every 0.25 um) lies within a drawn guide."""

    area = drawn_guide_area(part, with_paths)
    if area.is_empty:
        return False
    area = area.buffer(tolerance)
    for a, b in zip(points, points[1:]):
        steps = max(1, math.ceil(math.dist(a, b) / STEP_UM))
        for i in range(steps + 1):
            t = i / steps
            if not area.covers(Point(a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)):
                return False
    return True


# Variants that draw other guides: a type name, a colon and the keyword they take.
VARIANTS = {"MZM:coupler": {"splitter": "coupler"}, "MZM:branch_coupler": {"splitter": "branch_coupler"}}


def _build(ctype: str, angle: int, flip: bool):
    options = VARIANTS.get(ctype, {})
    ctype = ctype.split(":")[0]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            return build_component(ctype, angle=angle, flip_horizontal=flip, **options)
        except TypeError:                                  # no flip keyword: set it after the build
            part = build_component(ctype, angle=angle, **options)
            part.flip_horizontal = flip
            return part


def _params():
    return [pytest.param(ctype, angle, flip, id=f"{ctype}-{angle}-{'flip' if flip else 'noflip'}")
            for ctype in sorted(CHIP_BODY_TYPES | set(VARIANTS)) for angle, flip in CASES]


ADD_DROP_TYPES = ("MicroringResonator", "PNMicroringModulator", "RacetrackResonator")


GAP_TYPES = ("DirectionalCoupler", "TapCoupler", "MicroringResonator", "PNMicroringModulator", "RacetrackResonator",
             "CoupledRingFilter", "MicroringWeightBank", "RingAssistedMZI", "MZI", "MZM", "MZM:coupler",
             "MZM:branch_coupler")


@pytest.mark.parametrize("ctype", GAP_TYPES)
def test_a_rail_starts_and_ends_where_the_light_goes_on(ctype):
    """No drawn light starts or ends in a gap: each rail end is at a port, at an end or a window edge of another rail,
    at its own window's start (a ring's rail closes on it), at an end of a transfer that no section draws or where a
    transfer ends in an absorber (the weight bank's termination)."""

    part = _build(ctype, 0, False)
    found = sections(part)
    shapes = [layout(section) for section in found]
    hidden, behaviour, transfers = drawn_by_sections(part), find_behaviour(part), every_transfer(part)
    stops = [port_xy(part, name) for name in _optical_ports(part)]
    stops += [t.points[k] for t in transfers if path_id("part", t.in_port, t.out_port, t.name) not in hidden
              for k in (0, -1)]
    stops += [t.points[-1] for t in transfers if behaviour.sinks(part, t.out_port)]
    edges = {(i, r): [cut(rail.points, s, s)[0] for s in rail.window] if rail.window else []
             for i, section in enumerate(found) for r, rail in enumerate(section.rails)}
    for i, shape in enumerate(shapes):
        for r, drawn in enumerate(shape):
            if len(drawn["points"]) < 2:
                continue
            others = [d["points"][k] for j, other in enumerate(shapes) for q, d in enumerate(other)
                      if (j, q) != (i, r) and len(d["points"]) >= 2 for k in (0, -1)]
            others += [q for key, points in edges.items() if key != (i, r) for q in points] + edges[i, r][:1]
            for k in (0, -1):
                end = drawn["points"][k]
                assert min(math.dist(end, stop) for stop in stops + others) < 1e-6, (ctype, i, r, k, end)


def test_drawn_points_gives_the_drawn_path_or_the_fallback():
    from optodraw.animation_engine.behaviours.geometry import drawn_points, port_xy

    fallback = ((0.0, 0.0), (1.0, 1.0))
    taper = _build("Taper", 0, False)                      # no drawn paths: the fallback comes back
    assert drawn_points(taper, "o1", "o2", fallback) == fallback
    ybranch = _build("YBranch", 0, False)
    drawn = drawn_points(ybranch, "o1", "o2", fallback)
    assert drawn != fallback and len(drawn) > 2
    assert math.dist(drawn[0], port_xy(ybranch, "o1")) < 1e-6
    assert math.dist(drawn[-1], port_xy(ybranch, "o2")) < 1e-6


def _check_every_chip_type_gives_a_transfer(ctype):
    assert all_transfers(_build(ctype, 0, False)), f"{ctype} gives no transfer, so the guide check tests nothing"


def test_every_chip_type_gives_a_transfer():
    sweep(_check_every_chip_type_gives_a_transfer, sorted(CHIP_BODY_TYPES))


def _layer_area(part, layer):
    """World-frame union of the rectangles and polygons that ``geometry_2d`` draws in chip layer ``layer``."""

    shapes = []

    def walk(node):
        if node.get("type") == "group":
            for child in node.get("children", []):
                walk(child)
        elif node.get("chip_layer") == layer:
            if node["type"] == "rect":
                cx, cy, w, h = node["cx"], node["cy"], node["w"], node["h"]
                corners = [(cx - w / 2, cy - h / 2), (cx + w / 2, cy - h / 2), (cx + w / 2, cy + h / 2), (cx - w / 2, cy + h / 2)]
            else:
                corners = [(p[0], p[1]) for p in node["points"]]
            shapes.append(Polygon(local_to_world(part, corners)).buffer(0))

    walk(part.geometry_2d())
    assert shapes, f"{part.component_type} draws nothing in layer {layer}"
    return unary_union(shapes)


@pytest.mark.parametrize("ctype", ["OnChipLaser", "DBRLaser"])
@pytest.mark.parametrize("angle,flip", CASES)
def test_an_emitters_light_starts_in_its_drawn_active_region(ctype, angle, flip):
    from optodraw.animation_engine.behaviours.geometry import port_xy

    part = _build(ctype, angle, flip)
    behaviour = find_behaviour(part)
    emissions = behaviour.emissions(part, "part", {})
    assert len(emissions) == 1 and emissions[0].port.startswith("_")
    edges = behaviour.transfers(part, "part", emissions[0].port, WAVELENGTH_NM, {})
    assert [edge.out_port for edge in edges] == ["o1"]
    edge = edges[0]
    assert _layer_area(part, "active").covers(Point(edge.points[0]))
    assert math.dist(edge.points[-1], port_xy(part, "o1")) < 1e-6
    assert edge.length > 0 and edge.group_index > 1.0              # a delay: the drawn length times the group index


@pytest.mark.parametrize("ctype,ports", [("OnChipPhotodetector", ["o1"]), ("OnChipBalancedPhotodetector", ["o1", "o2"])])
@pytest.mark.parametrize("angle,flip", CASES)
def test_a_detectors_light_ends_in_its_drawn_absorber(ctype, ports, angle, flip):

    from optodraw.animation_engine.behaviours.geometry import port_xy

    part = _build(ctype, angle, flip)
    behaviour = find_behaviour(part)
    absorber = _layer_area(part, "germanium")
    for port in ports:
        edges = behaviour.transfers(part, "part", port, WAVELENGTH_NM, {})
        assert len(edges) == 1 and behaviour.sinks(part, edges[0].out_port) and edges[0].out_port.startswith("_")
        edge = edges[0]
        assert math.dist(edge.points[0], port_xy(part, port)) < 1e-6
        assert absorber.covers(Point(edge.points[-1]))
        assert np.allclose(edge.matrix, np.eye(2))                 # all the power at the port is absorbed
        assert not behaviour.sinks(part, port)
        assert behaviour.transfers(part, "part", edge.out_port, WAVELENGTH_NM, {}) == []   # nothing leaves the absorber


REGION_TYPES = ("MMI1x2", "MMI1x4", "MMI2x2", "MMI2x2PowerSplitter", "AWG", "StarCoupler", "CoherentReceiver")


def _shape_polygons(part, node, out) -> None:
    """World-frame polygons of every filled rectangle and polygon that ``geometry_2d`` draws."""

    if node.get("type") == "group":
        for child in node.get("children", []):
            _shape_polygons(part, child, out)
    elif node.get("type") == "rect":
        cx, cy, w, h = node["cx"], node["cy"], node["w"], node["h"]
        out.append(Polygon(local_to_world(part, [(cx - w / 2, cy - h / 2), (cx + w / 2, cy - h / 2),
                                                 (cx + w / 2, cy + h / 2), (cx - w / 2, cy + h / 2)])).buffer(0))
    elif node.get("type") == "polygon":
        out.append(Polygon(local_to_world(part, [(p[0], p[1]) for p in node["points"]])).buffer(0))


