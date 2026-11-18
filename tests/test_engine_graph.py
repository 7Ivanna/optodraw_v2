"""The signal graph: links from routes and beams between the ports of parts."""


import pytest

import optodraw
from optodraw.animation_engine.graph import build_graph


def _bench(*, group=None):
    scene = optodraw.Scene(width=160, height=80, platform="free_space")
    holder = group(scene) if group else scene
    laser = holder.add(optodraw.Laser(center=(-50, 0)))
    lens = holder.add(optodraw.Lens(center=(0, 0)))
    pd = holder.add(optodraw.Photodiode(center=(50, 0)))
    scene.add(optodraw.Beam(laser, lens, pd))
    return scene, laser, lens, pd


def test_parts_in_a_translated_group_link_in_world_coordinates():              # Review Focus 4
    from optodraw.core.transform import Vec3

    scene, laser, lens, pd = _bench(group=lambda s: s.group(position=Vec3(30.0, 20.0, 0.0)))
    link = next(l for l in build_graph(scene).links if l.a == ("laser1", "out"))
    world = laser.world_port("out").center
    assert link.points[0] == pytest.approx((world.x, world.y)) and world.y == pytest.approx(20.0, abs=1e-6)


def test_a_route_with_a_missing_end_is_ignored():                             # Review Focus 5
    scene = optodraw.Scene(width=200, height=80, platform="on_chip")
    a = scene.add(optodraw.Waveguide(center=(-60, 0)))
    b = scene.add(optodraw.Waveguide(center=(60, 0)))
    route = scene.route((a, "o2"), (b, "o1"), kind="waveguide")
    route.end_component = None
    assert build_graph(scene).links == []


