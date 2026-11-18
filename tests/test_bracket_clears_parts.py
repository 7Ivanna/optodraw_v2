"""A bracket's clearance runs from the edge of each part it spans, not from the part's centre: a bracket beside
plates that stand across the beam sat on the plates."""

from __future__ import annotations

import pytest

from optodraw import Beam, Bracket, HalfWavePlate, Laser, Lens, OpticalChopper, Photodiode, Polarizer, \
    QuarterWavePlate, Scene
from optodraw.schema import scene_from_spec, scene_to_spec


def _plates():
    scene = Scene(width=80, height=60)
    laser = scene.add(Laser(center=(0, 25), angle=-90, label="Laser", label_side="right"))
    qwp = scene.add(QuarterWavePlate(center=(0, 10), angle=-90, label=""))
    hwp = scene.add(HalfWavePlate(center=(0, 5), angle=-90, label=""))
    pol = scene.add(Polarizer(center=(0, 0), angle=-90, label=""))
    det = scene.add(Photodiode(center=(0, -15), angle=90, label="PD", label_side="right"))
    scene.add(Beam.through(laser, qwp, hwp, pol, det))
    return scene, qwp, pol


@pytest.mark.parametrize("side, sign", [("right", -1.0), ("left", 1.0)])
def test_a_bracket_stands_clear_of_the_parts_it_spans(side, sign):
    scene, qwp, pol = _plates()
    bracket = scene.add(Bracket("P", qwp, pol, side=side, clear=1.0))
    edge = min(qwp.drawn_box()[0], pol.drawn_box()[0]) if sign < 0 else max(qwp.drawn_box()[2], pol.drawn_box()[2])
    xs = [x for x, _ in bracket.drawn_points()]
    assert all(sign * (x - edge) >= 1.0 - 1e-9 for x in xs), (edge, xs)


def test_the_label_of_a_bracket_clears_the_parts():
    from optodraw import check_figure

    scene, qwp, pol = _plates()
    scene.add(Bracket("P", qwp, pol, side="right", clear=1.0))
    assert not [f for f in check_figure(scene, view="2d") if '"P"' in f]


def test_each_end_keeps_its_own_reach():
    scene = Scene(width=120, height=60)
    chopper = scene.add(OpticalChopper(center=(-20, 0), wheel_diameter=20, label=""))
    lens = scene.add(Lens(center=(20, 0), label=""))
    bracket = Bracket("x", chopper, lens, clear=1.0, depth=1.5)
    (x0, y0), (_, y_far), (_, y_far2), (x1, y1) = [(x + bracket.world_position.x, y + bracket.world_position.y)
                                                    for x, y in bracket.annotation_2d()["children"][0]["points"]]
    assert y0 == pytest.approx(chopper.drawn_box()[3] + 1.0) and y1 == pytest.approx(lens.drawn_box()[3] + 1.0)
    assert y_far == y_far2 == pytest.approx(max(y0, y1) + 1.5)              # the back stays parallel to the span


def test_a_bracket_between_places_keeps_its_clear():
    points = Bracket("x", (-10, 0), (10, 0)).drawn_points()
    assert [round(y, 6) for _, y in points] == [1.0, 2.5, 2.5, 1.0]


def test_a_saved_bracket_keeps_its_reach():
    scene, qwp, pol = _plates()
    scene.add(Bracket("P", qwp, pol, side="right", clear=1.0))
    back = next(node for node in scene_from_spec(scene_to_spec(scene)).walk() if isinstance(node, Bracket))
    before = next(node for node in scene.walk() if isinstance(node, Bracket))
    assert back.drawn_points() == pytest.approx(before.drawn_points())
