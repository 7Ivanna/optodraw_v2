"""A hollow roof mirror: the beam comes back parallel and beside itself; on its stage it is a delay line."""

from __future__ import annotations

import pytest

from optodraw import Beam, Laser, Mirror, Photodiode, RoofMirror, Scene
from optodraw.animation_engine import Animation
from optodraw.layout import aim, face


def test_the_light_meets_each_face_at_45_degrees_and_turns_back():
    part = RoofMirror(aperture=12.0)
    start, first, second, end = part.light_path("in", "out")
    front = RoofMirror.FRONT * 12.0
    for x, y in (first, second):
        assert abs(y) == pytest.approx(front - x)                       # on a face: |y| = FRONT - x
    assert first[0] == second[0] and start[1] == first[1] and end[1] == second[1]
    assert part.light_path("out", "in") == [end, second, first, start]


def _delay_line():
    scene = Scene(title="", platform="free_space")
    laser = scene.add(Laser(center=(-34, 3), wavelength=800, label="Laser"))
    roof = scene.add(RoofMirror(center=(6, 0), label="Delay", label_side="bottom"))
    fold = scene.add(Mirror(center=(-14, -3), label="M", label_side="left"))
    pd = scene.add(Photodiode(center=(-14, -18), label="PD", label_side="right"))
    out = roof.world_port("out").center
    aim(fold, (out.x, out.y), pd)
    face(pd, (-14, -3))
    scene.add(Beam.through(laser, (roof, "in"), (roof, "out"), fold, pd, wavelength=800))
    return scene


def test_the_light_comes_back_off_both_faces():
    absorbed = Animation(_delay_line(), mode="cw", strict=True).auto().click().to_json()["signal_state"]["absorbed"]
    assert [r["power"] for r in absorbed] == pytest.approx([0.99 ** 3])      # two faces of 99 %, then the fold


