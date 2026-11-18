"""The signal graph: links from routes and beams between the ports of parts."""

import math

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


def test_a_beam_through_bare_parts_links_neighbouring_ports():
    scene, laser, lens, pd = _bench()
    graph = build_graph(scene)
    assert {(l.a, l.b) for l in graph.links} == {(("laser1", "out"), ("lens1", "in")), (("lens1", "out"), ("photodiode1", "in"))}
    link = next(l for l in graph.links if l.a == ("laser1", "out"))
    gap = math.dist((laser.world_port("out").center.x, laser.world_port("out").center.y),
                    (lens.world_port("in").center.x, lens.world_port("in").center.y))
    assert link.length == pytest.approx(gap) and link.medium == "free_space" and link.group_index == 1.0
    assert link.id == "beam:beam1:0"


def test_routes_carry_their_medium_and_index():
    scene = optodraw.Scene(width=200, height=80, platform="on_chip")
    a = scene.add(optodraw.Waveguide(center=(-60, 0)))
    b = scene.add(optodraw.Waveguide(center=(60, 0)))
    scene.route((a, "o2"), (b, "o1"), kind="waveguide")
    amp = scene.add(optodraw.FiberAmplifier(center=(-60, 40)))
    spool = scene.add(optodraw.FiberSpool(center=(60, 40)))
    scene.route((amp, "out"), (spool, "in"), kind="fiber")
    links = {l.medium: l for l in build_graph(scene).links}
    assert links["waveguide"].group_index == pytest.approx(4.2) and links["waveguide"].id == "route:route1"
    assert links["fiber"].group_index == pytest.approx(1.468)


def test_a_beam_and_a_reverse_beam_on_the_same_ports_give_one_link():
    scene, laser, lens, pd = _bench()
    scene.add(optodraw.Beam((pd, "in"), (lens, "out")))
    assert len(build_graph(scene).links) == 2


def test_a_beam_of_coordinates_only_has_no_physics_link():                     # Review Focus 2
    scene = optodraw.Scene(width=100, height=60, platform="free_space")
    scene.add(optodraw.Beam((-40, 0), (0, 10), (40, 0)))
    assert build_graph(scene).links == []


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


def test_links_at_gives_the_far_end():
    scene, laser, lens, pd = _bench()
    graph = build_graph(scene)
    (link, far), = graph.links_at("lens1", "out")
    assert far == ("photodiode1", "in")
    assert set(graph.parts) == {"laser1", "lens1", "photodiode1"}               # beams are not parts
