"""The frame holds the light too: routes and beams that reach past the parts count in the content bounds."""

from __future__ import annotations

import optodraw


def test_a_route_that_loops_out_past_the_parts_widens_the_bounds():
    scene = optodraw.Scene(platform="on_chip")
    a = scene.add(optodraw.OnChipLaser(center=(-40, 0)))
    b = scene.add(optodraw.OnChipPhotodetector(center=(40, 30)))
    parts_only = scene.content_bounds()
    scene.route((a, "o1"), (b, "o1"), kind="waveguide", path_type="smooth", steps=[{"y": -80}, {"x": 120}, {"y": 30}])
    x0, y0, x1, y1 = scene.content_bounds()
    assert y0 <= -80.0 < parts_only[1] and x1 >= 120.0 > parts_only[2]


def test_a_beam_through_coordinates_counts_in_the_bounds():
    scene = optodraw.Scene(platform="free_space")
    laser = scene.add(optodraw.Laser(center=(0, 0)))
    scene.add(optodraw.Beam(laser, (90.0, 0.0), (90.0, -50.0)))
    x0, y0, x1, y1 = scene.content_bounds()
    assert x1 >= 90.0 and y0 <= -50.0


def test_fit_frame_keeps_a_looping_route_inside():
    scene = optodraw.Scene(platform="on_chip")
    a = scene.add(optodraw.OnChipLaser(center=(-40, 0)))
    b = scene.add(optodraw.OnChipPhotodetector(center=(40, 0)))
    scene.route((a, "o1"), (b, "o1"), kind="waveguide", path_type="smooth", steps=[{"y": 70}, {"x": 60}, {"y": 0}])
    scene.fit_frame(margin=5)
    assert scene.frame_center[1] + scene.height / 2 >= 70.0 + 5 - 1e-6
