"""A nonlinear crystal: a bulk block in a ring holder, or a long poled chip in an oven, on the beam."""

from __future__ import annotations

import pytest

from optodraw import Beam, Laser, NonlinearCrystal, Photodiode, Scene, check_figure, check_part_3d
from optodraw.animation_engine import Animation
from optodraw.registry import build_component
from optodraw.schema import scene_from_spec, scene_to_spec
from optodraw.symbols import lookup
from optodraw.symbols.art import _symbol_box, art_2d, symbol_for_2d


def _bench(**crystal):
    scene = Scene(title="", platform="free_space")
    scene.set_view_layout({"1d": {"spacing": 1}})
    laser = scene.add(Laser(center=(-30, 0), wavelength=800, label="Laser"))
    part = scene.add(NonlinearCrystal(center=(0, 0), label="BBO", **crystal))
    pd = scene.add(Photodiode(center=(24, 0), label="PD"))
    scene.add(Beam.through(laser, part, wavelength=800, width=0.8))
    scene.add(Beam.through(part, pd, wavelength=400, width=0.5))
    return scene, part


def test_its_ports_are_on_its_faces_along_the_beam():
    for part, length in ((NonlinearCrystal(), 5.0), (NonlinearCrystal(poled=True), 12.0),
                         (NonlinearCrystal(length=3.0), 3.0)):
        ports = part.ports()
        assert set(ports) == {"in", "out"}
        assert ports["in"].center.x == pytest.approx(-length / 2) and ports["in"].orientation_deg == pytest.approx(180)
        assert ports["out"].center.x == pytest.approx(length / 2) and ports["out"].orientation_deg == pytest.approx(0)


def test_it_is_in_the_catalog_and_keeps_its_values_through_a_save():
    assert build_component("NonlinearCrystal", material="PPLN", poled=True).material == "PPLN"
    scene, _ = _bench(material="PPKTP", process="SPDC", poled=True, length=14.0)
    (again,) = [n for n in scene_from_spec(scene_to_spec(scene)).walk() if n.component_type == "NonlinearCrystal"]
    assert (again.material, again.process, again.poled, again.length) == ("PPKTP", "SPDC", True, 14.0)


def test_a_bulk_crystal_sits_in_a_holder_and_a_poled_one_in_an_oven():
    def roles(part):
        return {child.get("role") for child in part.geometry_3d()["children"]}

    assert "holder" in roles(NonlinearCrystal()) and "oven" not in roles(NonlinearCrystal())
    assert "oven" in roles(NonlinearCrystal(poled=True))
    assert check_part_3d(NonlinearCrystal()) == [] and check_part_3d(NonlinearCrystal(poled=True)) == []


def test_the_light_passes_it():
    scene, _ = _bench()
    absorbed = Animation(scene, mode="cw", strict=True).auto().click().to_json()["signal_state"]["absorbed"]
    assert [round(record["power"], 3) for record in absorbed] == [1.0]


def test_it_has_its_own_symbol_bulk_and_poled():
    # needs the symbol library rebuilt with the rows of variants.toml (python -m optodraw.symbols.build)
    bulk, poled = NonlinearCrystal(), NonlinearCrystal(poled=True)
    assert lookup(bulk).exact and symbol_for_2d(bulk).exact and lookup(bulk).name == "crystal"
    assert lookup(poled).exact and lookup(poled).params == {"kind": "poled"}


@pytest.mark.parametrize("crystal", [{}, {"poled": True}, {"poled": True, "length": 20.0}, {"length": 2.0}])
def test_its_2d_drawing_reaches_both_ports(crystal):
    part = NonlinearCrystal(**crystal)
    x0, _, x1, _ = _symbol_box(art_2d(part)["matrix"], art_2d(part)["size"])
    ports = part.ports()
    assert x0 <= ports["in"].center.x and ports["out"].center.x <= x1      # no gap between the beam and the art


def test_a_bench_with_it_passes_the_figure_checks():
    scene, _ = _bench()
    scene.fit_frame(margin=4)
    assert check_figure(scene, preset="single_column") == []
