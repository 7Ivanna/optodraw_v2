"""A nonlinear crystal: a bulk block in a ring holder, or a long poled chip in an oven, on the beam."""

from __future__ import annotations

import pytest

from optodraw import Beam, Laser, NonlinearCrystal, Photodiode, Scene, check_part_3d
from optodraw.symbols.art import _symbol_box, art_2d


def _bench(**crystal):
    scene = Scene(title="", platform="free_space")
    scene.set_view_layout({"1d": {"spacing": 1}})
    laser = scene.add(Laser(center=(-30, 0), wavelength=800, label="Laser"))
    part = scene.add(NonlinearCrystal(center=(0, 0), label="BBO", **crystal))
    pd = scene.add(Photodiode(center=(24, 0), label="PD"))
    scene.add(Beam.through(laser, part, wavelength=800, width=0.8))
    scene.add(Beam.through(part, pd, wavelength=400, width=0.5))
    return scene, part


def test_a_bulk_crystal_sits_in_a_holder_and_a_poled_one_in_an_oven():
    def roles(part):
        return {child.get("role") for child in part.geometry_3d()["children"]}

    assert "holder" in roles(NonlinearCrystal()) and "oven" not in roles(NonlinearCrystal())
    assert "oven" in roles(NonlinearCrystal(poled=True))
    assert check_part_3d(NonlinearCrystal()) == [] and check_part_3d(NonlinearCrystal(poled=True)) == []


@pytest.mark.parametrize("crystal", [{}, {"poled": True}, {"poled": True, "length": 20.0}, {"length": 2.0}])
def test_its_2d_drawing_reaches_both_ports(crystal):
    part = NonlinearCrystal(**crystal)
    x0, _, x1, _ = _symbol_box(art_2d(part)["matrix"], art_2d(part)["size"])
    ports = part.ports()
    assert x0 <= ports["in"].center.x and ports["out"].center.x <= x1      # no gap between the beam and the art


