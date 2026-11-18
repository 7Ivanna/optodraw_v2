"""Display spacing per view: the 3D bench spreads out, the 1D and 2D drawings stay compact."""

from __future__ import annotations

import math

import pytest

import optodraw
from optodraw.core.view_layout import display_scene, validate_layout
from optodraw.symbols.schematic import build_schematic


def _bench():
    scene = optodraw.Scene(platform="free_space")
    laser = scene.add(optodraw.Laser(center=(-30, 0), label="Laser"))
    lens = scene.add(optodraw.Lens(center=(-18, 0), label="Lens"))
    pd = scene.add(optodraw.Photodiode(center=(-6, 0), label="Detector"))
    scene.add(optodraw.Beam.through(laser, lens, pd))
    return scene, laser, lens, pd


def test_automatic_spacing_is_only_for_3d():
    assert validate_layout({"3d": {"spacing": "auto"}})["3d"]["spacing"] == "auto"
    with pytest.raises(ValueError):
        validate_layout({"2d": {"spacing": "auto"}})


def test_3d_spacing_moves_parts_apart_on_a_copy_and_keeps_their_size():
    scene, laser, lens, _ = _bench()
    scene.set_view_layout({"3d": {"spacing": 2.0}})
    spaced = display_scene(scene, "3d")
    moved = {part.label: part for part in spaced.walk() if getattr(part, "label", "")}
    assert math.isclose(moved["Lens"].world_position.x - moved["Laser"].world_position.x, 24.0)
    assert laser.world_position.x == -30 and lens.world_position.x == -18          # the source scene stays
    assert moved["Lens"].aperture == lens.aperture


def test_a_route_follows_its_ports_when_the_3d_bench_spreads():
    scene, _, _, pd = _bench()
    scope = scene.add(optodraw.Oscilloscope(center=(20, -30), label="Scope"))
    scene.route((pd, "in"), (scope, "ch1"), kind="electrical", steps=[{"y": -12}])
    scene.set_view_layout({"3d": {"spacing": 2.0}})
    spaced = display_scene(scene, "3d")
    route = next(node for node in spaced.walk() if node.component_type == "Route")
    start = route.start_component.world_ports()[route.start_port].center
    end = route.end_component.world_ports()[route.end_port].center
    first, last = route.resolve_points()[0], route.resolve_points()[-1]
    assert math.hypot(first[0] - start.x, first[1] - start.y) < 1e-6
    assert math.hypot(last[0] - end.x, last[1] - end.y) < 1e-6
    assert any(math.isclose(point[1], -24.0) for point in route.resolve_points())   # its lane spreads too


def test_a_3d_setting_leaves_the_1d_schematic_as_it_was():
    scene, *_ = _bench()
    before = [(item.x, item.y) for item in build_schematic(scene).items]
    scene.set_view_layout({"3d": {"spacing": "auto"}})
    assert [(item.x, item.y) for item in build_schematic(scene).items] == before


def test_a_3d_setting_leaves_the_2d_drawing_as_it_was():
    scene, *_ = _bench()
    before = scene.render_svg().as_svg()
    scene.set_view_layout({"3d": {"spacing": "auto"}})
    assert scene.render_svg().as_svg() == before
