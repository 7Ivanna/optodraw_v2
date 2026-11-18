"""A chip's 1D view routes its links as on a chip: square turns round the symbols, never two on one track."""

from __future__ import annotations

import re

import pytest

from optodraw import presets
from optodraw.notebook_1d import schematic_body
from optodraw.symbols.router import CLEAR, IN_LINE, PITCH, route_links
from optodraw.symbols.schematic import build_schematic, link_path

CHIPS = ["coherent_receiver_chip", "wdm_delay_weight_bank_chip", "ring_resonator_chip", "mzm_mesh_chip"]


def _schematic(name):
    return build_schematic(getattr(presets, name)())


def _segments(route):
    return list(zip(route, route[1:]))


@pytest.mark.parametrize("name", CHIPS)
def test_every_chip_link_is_routed(name):
    schematic = _schematic(name)
    routed = [i for i, link in enumerate(schematic.links) if link.kind != "free_space"]
    assert set(schematic.routes) == set(routed)


@pytest.mark.parametrize("name", CHIPS)
def test_a_route_turns_square_and_ends_on_its_ports(name):
    schematic = _schematic(name)
    for index, route in schematic.routes.items():
        link = schematic.links[index]
        start = schematic.items[link.start].port(link.start_port)
        end = schematic.items[link.end].port(link.end_port)
        if start:
            assert route[0] == pytest.approx(start[:2])
        if end:
            assert route[-1] == pytest.approx(end[:2])
        for a, b in _segments(route):
            assert abs(a[0] - b[0]) <= IN_LINE or abs(a[1] - b[1]) <= IN_LINE, (name, index, a, b)


@pytest.mark.parametrize("name", CHIPS)
def test_a_route_keeps_off_the_other_symbols(name):
    schematic = _schematic(name)
    boxes = [(i.x, i.y, i.x + i.symbol.width, i.y + i.symbol.height) for i in schematic.items]
    for index, route in schematic.routes.items():
        link = schematic.links[index]
        for k, (x0, y0, x1, y1) in enumerate(boxes):
            if k in (link.start, link.end):
                continue
            for a, b in _segments(route):
                inside = (min(a[0], b[0]) < x1 - CLEAR / 2 and max(a[0], b[0]) > x0 + CLEAR / 2
                          and min(a[1], b[1]) < y1 - CLEAR / 2 and max(a[1], b[1]) > y0 + CLEAR / 2)
                assert not inside, (name, schematic.items[k].label, index)


@pytest.mark.parametrize("name", CHIPS)
def test_two_routes_never_share_a_track(name):
    schematic = _schematic(name)
    routes = list(schematic.routes.items())
    for i, (ia, a) in enumerate(routes):
        for ib, b in routes[i + 1:]:
            la, lb = schematic.links[ia], schematic.links[ib]
            if {(la.start, la.start_port), (la.end, la.end_port)} & {(lb.start, lb.start_port), (lb.end, lb.end_port)}:
                continue                                        # one port, two links: they meet there
            for p, q in _segments(a):
                for r, s in _segments(b):
                    if abs(p[1] - q[1]) < 1e-6 and abs(r[1] - s[1]) < 1e-6 and abs(p[1] - r[1]) < 0.5:
                        overlap = min(max(p[0], q[0]), max(r[0], s[0])) - max(min(p[0], q[0]), min(r[0], s[0]))
                        assert overlap <= PITCH, (name, ia, ib)
                    if abs(p[0] - q[0]) < 1e-6 and abs(r[0] - s[0]) < 1e-6 and abs(p[0] - r[0]) < 0.5:
                        overlap = min(max(p[1], q[1]), max(r[1], s[1])) - max(min(p[1], q[1]), min(r[1], s[1]))
                        assert overlap <= PITCH, (name, ia, ib)


def test_ports_that_face_each_other_in_line_get_a_straight_route():
    schematic = _schematic("ring_resonator_chip")
    straight = [route for route in schematic.routes.values() if len(route) == 2]
    assert straight


def test_a_bench_keeps_its_straight_beams():
    schematic = build_schematic(presets.confocal_pl_setup())
    assert not any(link.kind == "free_space" and i in schematic.routes for i, link in enumerate(schematic.links))


def test_the_chip_svg_draws_the_routes_not_curves():
    body = schematic_body(_schematic("coherent_receiver_chip"))
    links = body.split("<g ")[0]                                 # the links come before the symbols
    assert re.findall(r'<path d="M[^"]*Q', links)               # rounded corners
    assert not re.findall(r'<path d="M[^"]*C', links)           # no cubic curve


def test_a_wire_turns_sharp_and_a_waveguide_bends():
    """A circuit drawing turns its wires square; a waveguide keeps its bend radius."""

    schematic = _schematic("wdm_delay_weight_bank_chip")
    body = schematic_body(schematic).split("<g ")[0]
    wires = re.findall(r'<path d="([^"]*)"[^>]*stroke="#595959"', body)
    guides = re.findall(r'<path d="([^"]*)"[^>]*stroke="#000" stroke-width="0.9"', body)
    assert any(d.count("L") >= 2 for d in wires)                 # wires with corners exist
    assert not any("Q" in d for d in wires)
    assert any("Q" in d for d in guides)


def test_link_path_gives_the_route_or_the_curve():
    schematic = _schematic("coherent_receiver_chip")
    index = next(iter(schematic.routes))
    assert link_path(schematic, index) == list(schematic.routes[index])


def test_route_links_is_fast_enough_for_a_large_chip():
    import time

    schematic = _schematic("mzm_mesh_chip")
    started = time.perf_counter()
    route_links(schematic)
    assert time.perf_counter() - started < 3.0


def _crossing_pairs(schematic):
    from optodraw.check import _crosses
    from optodraw.symbols.schematic import link_path

    paths = [list(zip(link_path(schematic, i), link_path(schematic, i)[1:])) for i in range(len(schematic.links))]
    return [(i, j) for i in range(len(paths)) for j in range(i + 1, len(paths))
            if any(_crosses(p, q) for p in paths[i] for q in paths[j])]


@pytest.mark.parametrize("name", ["gc_ring_photodetector", "bogaerts_add_drop", "reed_mzm_probe", "smit_awg_demux",
                                  "tait_weight_bank", "mzm_mesh_chip", "coherent_receiver_chip",
                                  "wdm_delay_weight_bank_chip", "ring_resonator_chip"])
def test_a_chip_1d_crosses_no_link_its_2d_does_not(name):
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "examples"))
    import tutorial_scenes

    make = getattr(tutorial_scenes, name, None) or getattr(presets, name)
    assert _crossing_pairs(build_schematic(make())) == []


def test_a_route_with_a_repeated_point_draws_no_nan():
    """A repeated point made a zero-length run; its rounded corner divided by zero and the SVG got 'nan', which a
    rasteriser draws as a line to the page corner."""

    from optodraw.symbols.router import rounded_path

    d = rounded_path([(0.0, 10.0), (0.0, 0.0), (0.0, 0.0), (10.0, 0.0)])
    assert "nan" not in d and d.startswith("M0.00 10.00") and d.endswith("L10.00 0.00")


def test_no_preset_1d_svg_holds_nan():
    from optodraw.notebook_1d import render_notebook_1d

    for name in presets.list_presets():
        assert "nan" not in render_notebook_1d(presets.build_preset(name)), name


def _corners(route):
    return sum(1 for a, b, c in zip(route, route[1:], route[2:])
               if abs((b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])) > 1e-6)


def test_a_guided_route_turns_once_where_its_2d_route_first_turns():
    """Tait's MZM to AWG waveguides: the 2D route on the 1D page picks up steps (a slanted lead squared into a
    staircase), and the route followed them. Now each turns once, at the x of the guide's first turn."""

    from optodraw.literature import tait2017_broadcast_weight

    schematic = build_schematic(tait2017_broadcast_weight.build())
    labels = [item.label for item in schematic.items]
    to_mux = [route for index, route in schematic.routes.items()
              if labels[schematic.links[index].start].startswith("MZM") and "AWG" in labels[schematic.links[index].end]]
    assert len(to_mux) == 4
    assert [_corners(route) for route in to_mux] == [2, 2, 2, 2]


def test_a_cable_keeps_its_2d_lane_when_the_moved_lane_meets_a_part():
    """Detector 2's cable to MZM 2: keeping its 2D gap to the electrode moved the lane onto MZM 1's ground pad,
    and the route stepped round the pad. The lane where the 2D route has it is clear: up, across, down."""

    from optodraw.literature import tait2017_broadcast_weight

    schematic = build_schematic(tait2017_broadcast_weight.build())
    labels = [item.label for item in schematic.items]
    cables = [route for index, route in schematic.routes.items()
              if labels[schematic.links[index].start] == "BPD" and labels[schematic.links[index].end].startswith("MZM")]
    assert len(cables) == 4
    assert max(_corners(route) for route in cables) <= 3


FAR = ((-90, -90, -80, -80), (300, 300, 310, 310))     # the link's own two parts, out of the way


def test_the_guided_dogleg_and_the_guide_as_drawn():
    from optodraw.symbols.router import _as_drawn, _guided

    guide = [(0, 0), (20, 0), (20, 10), (40, 10), (40, 50), (100, 50)]
    assert _guided((0, 0), (1, 0), (100, 50), (-1, 0), guide, [], FAR, []) == [(0, 0), (20, 0), (20, 50), (100, 50)]
    assert _guided((0, 0), (1, 0), (100, 50), (-1, 0), guide, [(15, 20, 25, 30)], FAR, []) is None   # a part in the way
    assert _guided((0, 0), (1, 0), (100, 50), (0, -1), guide, [], FAR, []) is None   # the ports do not face each other
    assert _guided((0, 0), (1, 0), (100, 50), (-1, 0), guide, [], FAR, [[(20, -10), (20, 60)]]) is None   # on a track
    detour = [(0, 0), (20, 0), (20, -40), (80, -40), (80, 50), (100, 50)]          # the 2D route goes away first
    assert _guided((0, 0), (1, 0), (100, 50), (-1, 0), detour, [], FAR, []) is None
    assert _as_drawn((0, 0), (1, 0), (100, 50), (-1, 0), guide, [], FAR, []) == guide
    assert _as_drawn((0, 0), (1, 0), (100, 50), (-1, 0), guide, [], (FAR[0], (30, 5, 50, 15)), []) is None
    assert _as_drawn((0, 0), (1, 0), (100, 50), (-1, 0), [(0, 0), (20, 0), (30, 50), (100, 50)], [], FAR, []) is None
    assert _as_drawn((0, 0), (1, 0), (100, 50), (-1, 0), guide, [], FAR, [[(60, 40), (60, 60)], [(-5, 50), (200, 50)]]) is None


def test_the_guide_as_drawn_never_runs_through_its_end_part():
    """The first run of a guide may leave the start part, but it may not cross the part the link ends on."""

    from optodraw.symbols.router import _as_drawn

    guide = [(20, 10), (70, 10), (70, -10), (50, -10), (50, 0)]                      # straight through B, round, in
    own = ((0, 0, 20, 20), (40, 0, 60, 20))                                           # A, then B
    assert _as_drawn((20, 10), (1, 0), (50, 0), (0, -1), guide, [], own, []) is None


def _fake_item(x, y, w, h, ports):
    from types import SimpleNamespace

    symbol = SimpleNamespace(width=w, height=h, ports={name: SimpleNamespace(x=px, y=py, side=side)
                                                       for name, (px, py, side) in ports.items()})
    item = SimpleNamespace(x=x, y=y, symbol=symbol, label="", label_at=None)
    item.port = lambda name: ((x + symbol.ports[name].x, y + symbol.ports[name].y, symbol.ports[name].side)
                              if name in symbol.ports else None)
    return item


def test_a_simpler_route_that_crosses_a_drawn_link_is_refused():
    """B sits under and to the right of A, and a short link P-Q runs across the way. The 2D route goes round Q;
    its first turn would give a dogleg straight across P-Q. The route keeps to the guide and crosses nothing."""

    from types import SimpleNamespace

    from optodraw.check import _crosses

    items = [_fake_item(0, 0, 20, 20, {"o": (20, 10, "right")}), _fake_item(100, 60, 20, 20, {"i": (0, 10, "left")}),
             _fake_item(25, 35, 7, 10, {"o": (7, 5, "right")}), _fake_item(48, 35, 7, 10, {"i": (0, 5, "left")})]
    links = [SimpleNamespace(start=0, end=1, start_port="o", end_port="i", kind="waveguide", electrical=False),
             SimpleNamespace(start=2, end=3, start_port="o", end_port="i", kind="waveguide", electrical=False)]
    schematic = SimpleNamespace(items=items, links=links, width=140, height=100)
    guide = [(20, 10), (40, 10), (40, 25), (70, 25), (70, 70), (100, 70)]
    routes = route_links(schematic, {0: guide})
    assert routes[1] == [(32, 40), (48, 40)]
    assert not any(_crosses(p, q) for p in _segments(routes[0]) for q in _segments(routes[1])), routes[0]
