"""A note is free text on a figure: a power, a beam size, a key. The figure checks read it as they read a label."""

from __future__ import annotations


import pytest

from optodraw import Beam, Laser, Mirror, Note, Photodiode, Scene
from optodraw.app.validation import run_checks
from optodraw.layout import aim, face
from optodraw.symbols.schematic import build_schematic


def _bench():
    scene = Scene(title="bench", width=100, height=40, platform="free_space")
    laser = scene.add(Laser(center=(-30, 0), label="Laser"))
    pd = scene.add(Photodiode(center=(30, 0), label="PD"))
    beam = scene.add(Beam.through(laser, pd, wavelength=450))
    return scene, beam


def _fold():
    scene = Scene(title="fold", width=120, height=90, platform="free_space")
    laser = scene.add(Laser(center=(-40, 0), label="Laser"))
    mirror = scene.add(Mirror(center=(0, 0), label="M", label_side="bottom-right"))
    pd = scene.add(Photodiode(center=(0, 35), label="PD"))
    aim(mirror, laser, pd)
    face(pd, mirror)
    return scene, scene.add(Beam.through(laser, mirror, pd, wavelength=450))


def test_a_bad_anchor_is_refused():
    with pytest.raises(ValueError, match="anchor"):
        Note("x", anchor="centre")


def test_a_note_is_no_part_of_the_bench():
    scene, _ = _bench()
    scene.add(Note("880 mW", center=(0, 8)))
    assert not any(isinstance(n, Note) for n in scene._parts())
    assert not [i for i in run_checks(scene) if "880 mW" in i["message"] or "Note" in i["message"]]
    assert len(build_schematic(scene).items) == 2
    assert Note("880 mW").geometry_3d() == {}               # the 3D page skips a node with no solid


def test_a_leg_the_beam_does_not_have_is_refused():
    scene, beam = _bench()
    with pytest.raises(ValueError, match="1 straight leg"):
        Note.on(beam, "x", leg=4)


