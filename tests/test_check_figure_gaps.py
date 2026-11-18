"""Faults the figure checks let through: a 1D beam across a part it does not join, light that goes on in a fibre
read as a dead end, a flip mirror's label on its own dashed outline, and the cones of lens_beam listed as parts."""

from __future__ import annotations

from optodraw import (Beam, Camera, FlipMirror, Laser, Photodiode, Scene,
                      check_figure)
from optodraw.layout import face
from optodraw.symbols.schematic import build_schematic


def _line():
    scene = Scene(width=120, height=60)
    laser = scene.add(Laser(center=(-40, 0), label="Laser"))
    det = scene.add(Photodiode(center=(40, 0), label="PD"))
    scene.add(Beam.through(laser, det))
    return scene, laser, det


def test_a_1d_beam_drawn_across_a_part_it_does_not_join_is_found():
    scene, laser, det = _line()
    camera = scene.add(Camera(center=(0, -30), label="Cam"))
    scene.add(Beam.through(scene.add(Laser(center=(-40, -30), label="Probe")), camera))
    items = {item.label: item for item in build_schematic(scene).items}
    a, b, cam = items["Laser"].port("out"), items["PD"].port("in"), items["Cam"]
    middle = ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)
    scene.metadata["one_d_layout"] = {cam.key: [middle[0] - cam.symbol.width / 2.0,
                                                middle[1] - cam.symbol.height / 2.0]}    # dragged onto the beam
    assert any("Laser" in f and "PD" in f and "runs across Cam" in f for f in check_figure(scene, view="1d"))


def _flip(label_side):
    scene = Scene(width=100, height=60)
    laser = scene.add(Laser(center=(-35, 0), label="Laser"))
    flip = scene.add(FlipMirror(center=(0, 0), angle=45, state="both", label="Flip mirror", label_side=label_side))
    up = scene.add(Photodiode(center=(0, 25), angle=-90, label="PD", label_side="right"))
    on = scene.add(Photodiode(center=(30, 0), label="PD2", label_side="top"))
    face(up, flip)
    scene.add(Beam.through(laser, (flip, "io"), up))
    scene.add(Beam.through(laser, (flip, "pass"), on))
    return scene


def test_a_flip_mirror_label_on_its_own_dashed_outline_is_found():
    found = check_figure(_flip("top-left"), view="2d")
    assert any('"Flip mirror"' in f and "outline" in f for f in found), found


