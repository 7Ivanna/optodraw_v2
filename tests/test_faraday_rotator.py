"""A Faraday rotator: a rod in a ring magnet that turns the polarization the same way in both directions."""

from __future__ import annotations

import pytest

from optodraw import PBS, Beam, FaradayRotator, HalfWavePlate, Laser, Mirror, Photodiode, Scene, check_figure, check_part_3d
from optodraw.animation_engine import Animation
from optodraw.registry import build_component
from optodraw.schema import scene_from_spec, scene_to_spec
from optodraw.symbols import lookup
from optodraw.symbols.art import _symbol_box, art_2d


def _double_pass(middle):
    """Light passes the cube, the part, a mirror, the part again and comes back to the cube."""

    scene = Scene(title="", platform="free_space")
    laser = scene.add(Laser(center=(-40, 0), wavelength=1064, label="Laser"))
    pbs = scene.add(PBS(center=(-15, 0), label="PBS"))
    part = scene.add(middle)
    mirror = scene.add(Mirror(center=(25, 0), label="M"))
    pd = scene.add(Photodiode(center=(-15, -20), angle=90, label="PD", label_side="right"))
    scene.add(Beam.through(laser, (pbs, "in"), (pbs, "trans"), part, mirror, part, (pbs, "trans"), (pbs, "tap"), pd,
                           wavelength=1064))
    absorbed = Animation(scene, mode="cw", strict=True).auto().click().to_json()["signal_state"]["absorbed"]
    return {record["part"]: record["power"] for record in absorbed}, scene


def test_its_ports_are_its_two_end_faces():
    ports = FaradayRotator(length=12.0).ports()
    assert set(ports) == {"in", "out"}
    assert ports["in"].center.x == pytest.approx(-6.0) and ports["in"].orientation_deg == pytest.approx(180.0)
    assert ports["out"].center.x == pytest.approx(6.0) and ports["out"].orientation_deg == pytest.approx(0.0)


def test_two_passes_add_up_to_90_degrees_so_the_light_comes_back_crossed():
    power, _ = _double_pass(FaradayRotator(center=(5, 0)))
    assert power["photodiode1"] == pytest.approx(0.99, abs=1e-6)        # the mirror keeps 99 %
    assert power.get("laser1", 0.0) == pytest.approx(0.0, abs=1e-9)


def test_with_no_turn_the_light_goes_back_to_the_laser():
    power, _ = _double_pass(FaradayRotator(center=(5, 0), rotation_deg=0.0))
    assert power.get("photodiode1", 0.0) == pytest.approx(0.0, abs=1e-9)


def test_it_is_in_the_catalog_and_keeps_its_values_through_a_save():
    assert build_component("FaradayRotator", rotation_deg=22.5).rotation_deg == 22.5
    _, scene = _double_pass(FaradayRotator(center=(5, 0), length=14.0, rotation_deg=40.0))
    (again,) = [n for n in scene_from_spec(scene_to_spec(scene)).walk() if n.component_type == "FaradayRotator"]
    assert (again.length, again.rotation_deg) == (14.0, 40.0)


def test_it_stands_on_its_post_with_the_rod_in_the_magnet():
    part = FaradayRotator()
    roles = {child.get("role") for child in part.geometry_3d()["children"]}
    assert {"magnet", "rod", "boss"} <= roles
    assert check_part_3d(part) == []


def test_it_has_its_own_symbol_and_its_drawing_reaches_both_ports():
    # needs the symbol library rebuilt with the rows of variants.toml (python -m optodraw.symbols.build)
    part = FaradayRotator()
    assert lookup(part).exact and lookup(part).name == "faraday"
    x0, _, x1, _ = _symbol_box(art_2d(part)["matrix"], art_2d(part)["size"])
    assert x0 <= part.ports()["in"].center.x + 1e-6 and part.ports()["out"].center.x - 1e-6 <= x1


def test_a_bench_with_it_passes_the_figure_checks():
    _, scene = _double_pass(FaradayRotator(center=(5, 0), label="FR"))
    scene.fit_frame(margin=4)
    assert check_figure(scene, preset="single_column") == []


def test_two_passes_of_a_half_wave_plate_cancel():
    """Control for the rotator: a reciprocal plate's second pass undoes its first, so the light returns to the laser."""

    power, _ = _double_pass(HalfWavePlate(center=(5, 0), fast_axis_angle=22.5))
    assert power.get("laser1", 0.0) == pytest.approx(0.99, abs=1e-6)
