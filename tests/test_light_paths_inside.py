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

from optodraw.animation3d.rails import layout, rail_powers
from optodraw.animation_engine.behaviours import find_behaviour
from optodraw.animation_engine.behaviours.geometry import cut, local_to_world, port_xy
from optodraw.animation_engine.ids import path_id
from optodraw.components.electronics._shared import ANALOG_BLUE
from optodraw.registry import build_component

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


@pytest.mark.parametrize("ctype,angle,flip", _params())
def test_every_lit_path_stays_inside_its_guide(ctype, angle, flip):
    """Every transfer the light takes, internal ones included; the transfers of a coupling section are drawn on its
    rails, so the rails are what must stay inside."""

    part = _build(ctype, angle, flip)
    assert part.flip_horizontal == flip
    for label, points in shown_points(part):
        assert inside_drawn_guides(part, points), f"{ctype} {label} leaves its drawn guide"


def _drawn_params():
    return [pytest.param(ctype, angle, flip, id=f"{ctype}-{angle}-{'flip' if flip else 'noflip'}")
            for ctype in sorted(DRAWN_TYPES | DRAWN_SINGLE_MODE_TYPES | MULTIMODE_TYPES | set(VARIANTS))
            for angle, flip in CASES]


@pytest.mark.parametrize("ctype,angle,flip", _drawn_params())
def test_drawn_paths_follow_the_drawn_strips(ctype, angle, flip):
    """A part's own paths must lie on the guides it draws, not only on its own centrelines (they would
    pass the test above by definition). The largest real
    curve error on the passing drawn types is 0.100 um (the RingAssistedMZI ring polygon against its
    loop); 0.12 um sits just above it."""

    part = _build(ctype, angle, flip)
    for label, points in shown_points(part):
        assert inside_drawn_guides(part, points, tolerance=0.12, with_paths=False), f"{ctype} {label} leaves the drawn strips"


ADD_DROP_TYPES = ("MicroringResonator", "PNMicroringModulator", "RacetrackResonator")


@pytest.mark.parametrize("ctype", ADD_DROP_TYPES)
@pytest.mark.parametrize("angle,flip", CASES)
def test_an_add_drop_ring_draws_its_light_on_its_rails(ctype, angle, flip):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        part = build_component(ctype, angle=angle, add_drop=True)
    part.flip_horizontal = flip
    transfers = every_transfer(part)
    assert {t.out_port for t in transfers} >= {"o2", "o3", "_ring_top", "_ring_bottom"}
    assert {path_id("part", t.in_port, t.out_port, t.name) for t in transfers} <= drawn_by_sections(part)
    for label, points in shown_points(part):
        assert inside_drawn_guides(part, points), f"{ctype} {label}"
        assert inside_drawn_guides(part, points, tolerance=0.12, with_paths=False), f"{ctype} {label}"


GAP_TYPES = ("DirectionalCoupler", "TapCoupler", "MicroringResonator", "PNMicroringModulator", "RacetrackResonator",
             "CoupledRingFilter", "MicroringWeightBank", "RingAssistedMZI", "MZI", "MZM", "MZM:coupler",
             "MZM:branch_coupler")


@pytest.mark.parametrize("ctype", GAP_TYPES)
def test_a_part_with_coupler_gaps_draws_every_coupling_on_section_rails(ctype):
    """Every transfer whose path jumps a coupler gap is drawn by a section; the two windows of a coupling section are
    sampled alike, so the transfer done ``F`` runs from 0 to 1 at the same samples on both rails."""

    part = _build(ctype, 0, False)
    found = sections(part)
    assert found, f"{ctype} has no coupling section"
    hidden = drawn_by_sections(part)
    plain = [t for t in every_transfer(part) if path_id("part", t.in_port, t.out_port, t.name) not in hidden]
    # what no section draws is a plain guide (the weight bank's bus leads and its return guide): inside its strips
    assert all(inside_drawn_guides(part, t.points, tolerance=0.12, with_paths=False) for t in plain)
    for index, section in enumerate(found):
        shape = layout(section)
        assert len(shape) == len(section.rails) == len(section.inputs)
        if section.kappa is None:
            continue
        assert len(shape) == 2 and 0.0 <= section.kappa <= 1.0
        (a0, a1), (b0, b1) = shape[0]["window"], shape[1]["window"]
        assert a1 - a0 == b1 - b0 >= 1, (ctype, index)
        assert shape[0]["done"][a0:a1 + 1] == shape[1]["done"][b0:b1 + 1], (ctype, index)
        assert shape[0]["done"][a0] == pytest.approx(0.0, abs=1e-12) and shape[0]["done"][a1] == pytest.approx(1.0)


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


@pytest.mark.parametrize("ctype,setting", [("DirectionalCoupler", "coupling_ratio"), ("MicroringResonator", "power_coupling")])
def test_a_coupler_that_sends_all_its_light_across_still_draws_the_input_rail(ctype, setting):
    """Power coupling 1: light at o1 alone is drawn on the input rail from the port, at the input's power, down to
    nothing at the window's end, and the other rail ends with all of it."""

    part = _build(ctype, 0, False)
    setattr(part, setting, 1.0)
    section = next(s for s in sections(part) if math.dist(s.rails[0].points[0], port_xy(part, "o1")) < 1e-6)
    assert section.kappa == pytest.approx(1.0)
    shape = layout(section)
    first, other = rail_powers(section, shape, [np.array([1.0, 0.0], complex), np.zeros(2, complex)])
    assert math.dist(shape[0]["points"][0], port_xy(part, "o1")) < 1e-6
    end = shape[0]["window"][1]
    assert first[0] == pytest.approx(1.0) and first[end] == pytest.approx(0.0, abs=1e-12)
    assert other[shape[1]["window"][1]] == pytest.approx(1.0)
    for drawn in shape:
        assert inside_drawn_guides(part, drawn["points"], tolerance=0.12, with_paths=False)


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


@pytest.mark.parametrize("ctype", sorted(CHIP_BODY_TYPES))
def test_every_chip_type_gives_a_transfer(ctype):
    assert all_transfers(_build(ctype, 0, False)), f"{ctype} gives no transfer, so the guide check tests nothing"


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
    import numpy as np

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


def test_a_flip_does_not_change_the_ring_assisted_mzi_physics():
    """Same matrices, delays and names per (in port, out port) with and without the horizontal flip."""

    import numpy as np

    def table(flip):
        part = _build("RingAssistedMZI", 0, flip)
        return {(t.in_port, t.out_port, t.name): (t.matrix, t.length, t.group_index) for t in all_transfers(part)}

    plain, flipped = table(False), table(True)
    assert plain.keys() == flipped.keys()
    for key, (matrix, length, index) in plain.items():
        other = flipped[key]
        assert np.allclose(matrix, other[0], atol=1e-12), key
        assert length == pytest.approx(other[1], abs=1e-9), key
        assert index == other[2], key


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


@pytest.mark.parametrize("ctype", REGION_TYPES)
@pytest.mark.parametrize("angle,flip", CASES)
def test_a_region_outline_is_a_body_the_part_draws(ctype, angle, flip):
    """The check trusts a region outline, so each outline must equal one shape of the drawing."""

    part = _build(ctype, angle, flip)
    outlines = region_outlines(part)
    assert outlines, f"{ctype} names no region"
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        shapes: list = []
        _shape_polygons(part, part.geometry_2d(), shapes)
    for outline in outlines:
        assert any(outline.symmetric_difference(shape).area < 1e-6 * outline.area for shape in shapes), (
            f"{ctype} region is not a drawn shape")


@pytest.mark.parametrize("ctype", REGION_TYPES)
@pytest.mark.parametrize("angle,flip", CASES)
def test_every_drawn_path_stays_on_the_strips_or_in_its_region(ctype, angle, flip):
    """Each path of each in-port, not only the ones the engine lights at 1550 nm (all AWG channels)."""

    part = _build(ctype, angle, flip)
    for port in _optical_ports(part):
        for path in part.optical_paths(port):
            assert inside_drawn_guides(part, local_to_world(part, path["pts"]), tolerance=0.12, with_paths=False), (
                f"{ctype} {port}->{path['port']} leaves the drawn strips and regions")


@pytest.mark.parametrize("ctype", ["MMI1x2", "MMI1x4", "MMI2x2", "MMI2x2PowerSplitter"])
@pytest.mark.parametrize("angle,flip", CASES)
def test_an_mmi_fans_from_its_input_across_the_body_to_each_output(ctype, angle, flip):
    part = _build(ctype, angle, flip)
    body = region_outlines(part)[0]
    behaviour = find_behaviour(part)
    names = _optical_ports(part)
    edges = behaviour.transfers(part, "part", "o1", WAVELENGTH_NM, {})
    assert {e.out_port for e in edges} == {n for n in names if part.ports()[n].center.x > 0}
    for edge in edges:
        crossing = edge.points[1:-1]                       # between the two taper tips: the body crossing
        assert len(crossing) >= 2
        assert all(body.buffer(1e-6).covers(Point(p)) for p in crossing)
        assert math.dist(edge.points[0], tuple(float(v) for v in (part.world_port("o1").center.x, part.world_port("o1").center.y))) < 1e-6
    ends = {e.out_port: edge_end for e in edges for edge_end in [e.points[-1]]}
    assert len({tuple(round(v, 6) for v in end) for end in ends.values()}) == len(ends)   # one distinct output each


def test_the_check_rejects_a_path_through_the_body():
    """The helper itself: a path off the body fails, the drawn stub passes."""

    part = _build("MMI1x2", 0, False)
    port = part.world_port("o1").center
    stub = ((float(port.x), float(port.y)), (float(port.x) + 1.0, float(port.y)))
    assert inside_drawn_guides(part, stub)
    assert not inside_drawn_guides(part, (stub[0], (float(port.x) + 3.0, float(port.y) + 9.0)))


def test_the_check_still_rejects_a_chord_from_a_tap_across_the_gap():
    """Strict outside the regions: the receiver's input line pointing at the lane (not the hybrid) fails."""

    part = _build("CoherentReceiver", 0, False)
    start = part.world_port("signal").center
    assert not inside_drawn_guides(part, ((float(start.x), float(start.y)), (float(start.x) + 2.0, float(start.y) + 7.0)),
                                   with_paths=False)


def test_an_awg_routes_a_wavelength_midway_between_two_channels_to_the_lower_one():
    from optodraw.animation_engine.behaviours.splitters import ArrayedWaveguideGrating

    part = _build("AWG", 0, False)
    assert part.channel_count == 8 and part.channel_spacing_nm == 0.8 and part.center_wavelength_nm == 1550.0
    assert ArrayedWaveguideGrating().channel(part, 1550.0) == "o4"
    assert ArrayedWaveguideGrating().channel(part, 1550.0 + 0.4 + 2e-9) == "o5"
    assert {t.out_port for t in all_transfers(part) if t.in_port == "i1"} == {"o4"}


@pytest.mark.parametrize("angle,flip", CASES)
def test_each_receiver_path_ends_inside_a_drawn_diode(angle, flip):
    part = _build("CoherentReceiver", angle, flip)
    circles = []

    def walk(node):
        if node.get("type") == "group":
            for child in node.get("children", []):
                walk(child)
        elif node.get("type") == "circle" and node.get("fill") == "#81a9bb":
            circles.append(Point(local_to_world(part, [(node["cx"], node["cy"])])[0]).buffer(float(node["r"])))

    walk(part.geometry_2d())
    assert len(circles) == 4
    for port in ("signal", "lo"):
        ends = [Point(local_to_world(part, path["pts"])[-1]) for path in part.optical_paths(port)]
        assert all(any(c.covers(e) for c in circles) for e in ends)
        assert len({tuple(round(v, 6) for v in (e.x, e.y)) for e in ends}) == 4
