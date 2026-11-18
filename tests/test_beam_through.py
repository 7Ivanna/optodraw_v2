"""Beam.through: light attached at the parts' faces, never starting inside a part or running across one."""

from __future__ import annotations

import pytest

import optodraw
from optodraw import Beam, Laser, Lens, Mirror, Objective, Photodiode, Scene


def _bench():
    scene = Scene(width=200, height=80, platform="free_space")
    laser = scene.add(Laser(center=(-60, 0)))
    lens = scene.add(Lens(center=(-20, 0)))
    mirror = scene.add(Mirror(center=(20, 0), angle=135))
    pd = scene.add(Photodiode(center=(20, 40), angle=-90))
    return scene, laser, lens, mirror, pd


def test_through_leaves_and_enters_each_part_by_its_facing_ports():
    scene, laser, lens, mirror, pd = _bench()
    beam = Beam.through(laser, lens, mirror, pd, wavelength=532)
    assert beam.anchors == [(laser, "out"), (lens, "in"), (lens, "out"), (mirror, "io"), (pd, "in")]
    assert beam.wavelength == 532


def test_light_starts_at_the_laser_edge_and_skips_the_inside_of_a_part():
    scene = Scene(width=120, height=40, platform="free_space")
    laser = scene.add(Laser(center=(-40, 0)))
    objective = scene.add(Objective(center=(0, 0)))
    pd = scene.add(Photodiode(center=(40, 0)))
    beam = scene.add(Beam.through(laser, objective, pd))
    start = beam.resolve_points()[0]
    assert start[0] == pytest.approx(laser.world_port("out").center.x)            # not the laser's centre
    runs = beam.segments()
    assert len(runs) == 2                                                     # the span inside the objective is a gap
    assert runs[0][-1][0] == pytest.approx(objective.world_port("in").center.x)


def test_an_objective_pointing_down_takes_light_in_at_its_back_and_out_at_its_nose():
    scene = Scene(width=100, height=100, platform="free_space")
    laser = scene.add(Laser(center=(0, 40), angle=-90))
    objective = scene.add(Objective(center=(0, 0), angle=-90))
    sample = scene.add(optodraw.Sample(center=(0, -16), angle=-90))
    beam = Beam.through(laser, objective, sample)
    assert beam.anchors == [(laser, "out"), (objective, "in"), (objective, "out"), (sample, "in")]


def test_points_and_bare_coordinates_pass_through_unchanged():
    scene, laser, lens, mirror, pd = _bench()
    beam = Beam.through(laser, (0.0, 0.0), pd)
    assert beam.anchors[1] == (0.0, 0.0) and beam.anchors[0] == (laser, "out") and beam.anchors[-1] == (pd, "in")
