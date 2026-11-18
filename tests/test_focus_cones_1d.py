"""A beam that focuses between two lenses stays one line in the 1D view, with no gap at the focus."""

from __future__ import annotations

from optodraw import Laser, Lens, Photodiode, Scene
from optodraw.symbols.schematic import build_schematic


def _telescope():
    scene = Scene(title="", platform="free_space")
    laser = scene.add(Laser(center=(0, 0), label="Laser"))
    first = scene.add(Lens(center=(20, 0), focal_length=5, label="L1"))
    second = scene.add(Lens(center=(35, 0), focal_length=10, label="L2"))
    pd = scene.add(Photodiode(center=(55, 0), label="PD"))
    pieces = scene.lens_beam(laser, first, second, pd, width=1)
    return scene, pieces


def _joined(scene):
    one_d = build_schematic(scene)
    labels = [item.label for item in one_d.items]
    return {(labels[link.start], labels[link.end]) for link in one_d.links}, one_d.unresolved


def test_the_two_cones_of_a_focus_join_the_lenses_in_1d():
    scene, pieces = _telescope()
    assert sum(type(piece).__name__ == "FocusingBeam" for piece in pieces) == 2     # the focus lies between L1 and L2
    links, unresolved = _joined(scene)
    assert ("L1", "L2") in links and unresolved == 0


def test_every_part_of_the_telescope_is_on_one_line():
    scene, _ = _telescope()
    links, _ = _joined(scene)
    assert links == {("Laser", "L1"), ("L1", "L2"), ("L2", "PD")}
