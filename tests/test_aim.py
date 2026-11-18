"""layout.aim: turn a mirror or splitter so its reflecting face sends light from one part to another."""

from __future__ import annotations

import math

import pytest

from optodraw import BeamSplitter, Laser, Mirror, Photodiode, Scene
from optodraw.layout import aim


def _facing(part, port):
    return part.world_port(port).orientation_deg % 360.0


def test_a_mirror_faces_its_reflecting_side_to_both_beams():
    scene = Scene(platform="free_space")
    laser = scene.add(Laser(center=(-40, 0)))
    mirror = scene.add(Mirror(center=(0, 0)))
    pd = scene.add(Photodiode(center=(0, 40)))
    aim(mirror, laser, pd)
    assert _facing(mirror, "io") == pytest.approx(135.0)                 # the face looks up-left, at both beams


def test_a_splitter_reflects_with_its_front_face():
    scene = Scene(platform="free_space")
    laser = scene.add(Laser(center=(-40, 0)))
    bs = scene.add(BeamSplitter(center=(0, 0)))
    pd = scene.add(Photodiode(center=(0, -40)))
    aim(bs, laser, pd)
    entry, out = _facing(bs, "in"), _facing(bs, "refl")
    assert entry == pytest.approx(180.0, abs=1e-6) and out == pytest.approx(270.0, abs=1e-6)


def test_aim_takes_points_too_and_returns_the_part():
    mirror = Mirror(center=(10, 10))
    assert aim(mirror, (10, -30), (50, 10)) is mirror
    assert _facing(mirror, "io") == pytest.approx(math.degrees(math.atan2(-1, 1)) % 360.0)


def test_aim_puts_the_reflecting_face_on_the_point_given():
    """The io port sat 0.34 off the mirror's centre, so a mirror on the laser's line still tilted the beam."""

    from optodraw import Beam

    scene = Scene(platform="free_space")
    laser = scene.add(Laser(center=(-40, 0)))
    mirror = scene.add(Mirror(center=(0, 0)))
    pd = scene.add(Photodiode(center=(0, 40)))
    aim(mirror, laser, pd)
    face = mirror.world_port("io").center
    assert (face.x, face.y) == pytest.approx((0.0, 0.0), abs=1e-9)
    beam = scene.add(Beam.through(laser, mirror, pd))
    (x0, y0, _), (x1, y1, _) = beam.resolve_points()[:2]
    assert y1 == pytest.approx(y0, abs=1e-9)                              # the laser's beam runs level


def test_aim_keeps_a_plate_splitter_centred_where_the_beams_meet_it():
    from optodraw.core.beam import beam_point

    scene = Scene(platform="free_space")
    laser = scene.add(Laser(center=(-40, 0)))
    bs = scene.add(BeamSplitter(center=(0, 0)))
    pd = scene.add(Photodiode(center=(0, -40)))
    aim(bs, laser, pd)
    hit = beam_point(bs, "refl")
    assert (hit.x, hit.y) == pytest.approx((0.0, 0.0), abs=1e-9)
