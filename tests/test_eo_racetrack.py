"""An electro-optic racetrack with G-S-G electrodes (Zhang et al., Nature 568, 373 (2019), Fig. 2a): grounds outside
both straights, the signal inside, a bus past the west bend, and the probe pads on one line through the centre."""

from __future__ import annotations

import pytest

from optodraw import EdgeCoupler, EORacetrackModulator, Scene, check_figure, check_part_3d
from optodraw.symbols import lookup


def _metal(part: EORacetrackModulator) -> list[tuple[float, float]]:
    """The y extent of every electrode box."""

    return [(n["cy"] - n["h"] / 2.0, n["cy"] + n["h"] / 2.0)
            for n in part.geometry_2d()["children"] if n.get("chip_layer") == "metal"]


def test_each_straight_runs_between_a_ground_outside_and_the_signal_inside_at_the_electrode_gap():
    ring = EORacetrackModulator(bend_radius=100.0, waveguide_width=1.4, electrode_gap=3.3, render_physical=True)
    edges = [y for box in _metal(ring) for y in box]
    for straight in (100.0, -100.0):                           # the two straights, at plus and minus the radius
        outer, inner = (straight + 0.7 + 3.3, straight - 0.7 - 3.3) if straight > 0 else \
                       (straight - 0.7 - 3.3, straight + 0.7 + 3.3)
        assert any(y == pytest.approx(outer) for y in edges), "a ground 3.3 um outside the guide"
        assert any(y == pytest.approx(inner) for y in edges), "the signal 3.3 um inside the guide"
    assert not any(lo < 100.0 < hi or lo < -100.0 < hi for lo, hi in _metal(ring)), "no metal on a straight"


def test_the_bus_passes_the_west_bend_and_the_probe_pads_lie_on_one_line():
    ports = EORacetrackModulator().ports()
    o1, o2 = ports["o1"], ports["o2"]
    assert o1.center.x == o2.center.x < -EORacetrackModulator()._draw("straight_length") / 2.0
    assert (o1.orientation_deg, o2.orientation_deg) == (90, 270) and o1.center.y > 0 > o2.center.y
    pads = [ports[name] for name in ("gnd1", "sig", "gnd2")]
    assert {p.center.x for p in pads} == {0.0} and pads[0].center.y > pads[1].center.y > pads[2].center.y
    assert {p.kind for p in pads} == {"electrical"}


def test_the_electrodes_lie_on_the_metal_level_of_the_stack():
    ring = EORacetrackModulator()
    stack = ring._draw_layer_stack()
    gold = [s for s in ring.geometry_3d()["children"] if s["material"].get("preset") == "gold"]
    assert gold and {round(s["position"][1] - s["height"] / 2.0, 9) for s in gold} == {round(stack["metal_z"], 9)}
    assert check_part_3d(ring) == []


def test_a_bend_too_tight_for_the_signal_electrodes_is_refused():
    with pytest.raises(ValueError, match="bend_radius"):
        EORacetrackModulator(bend_radius=3.0, render_physical=True)


def test_a_racetrack_between_two_edge_couplers_passes_the_figure_checks_in_2d_and_1d():
    route = {"kind": "waveguide", "path_type": "smooth"}
    chip = Scene(title="EO ring", platform="on_chip")
    ring = chip.add(EORacetrackModulator(center=(0, 0), label="EO racetrack", label_side="right"))
    o1, o2 = ring.world_ports()["o1"].center, ring.world_ports()["o2"].center
    a = chip.add(EdgeCoupler(center=(o1.x - 45, o1.y + 10), label="In", label_side="top"))
    b = chip.add(EdgeCoupler(center=(o2.x + 140, o2.y - 10), angle=180, label="Out", label_side="bottom"))
    chip.route((a, "o1"), (ring, "o1"), **route)
    chip.route((ring, "o2"), (b, "o1"), **route)
    chip.fit_frame(margin=8)
    assert check_figure(chip, view="both") == []               # the G-S-G pads may stay open: a probe lands there
    symbol = lookup(ring)
    assert symbol.exact and sorted(symbol.ports) == sorted(ring.ports())
