"""Coupler settings reach the engine, and cw mode copes with a fully dark output."""

import pytest

import optodraw
from optodraw.animation3d import fieldmodel
from optodraw.animation3d.inputs import default_inputs
from optodraw.animation_engine.behaviours.splitters import Coupler2x2
from optodraw.animation_engine.ids import scene_ids
from optodraw.animation_engine.tables import compile_table


def _cross_and_bar_power(part_cls, bar_port, cross_port, **kwargs):
    """Light enters o1 (upper left) and leaves at the bar port (same side) and the cross port."""

    scene = optodraw.Scene(width=300, height=120, platform="on_chip")
    laser = scene.add(optodraw.OnChipLaser(center=(-80, 0)))
    part = scene.add(part_cls(center=(0, 0), **kwargs))
    bar = scene.add(optodraw.OnChipPhotodetector(center=(80, 10)))
    cross = scene.add(optodraw.OnChipPhotodetector(center=(80, -10)))
    scene.route((laser, "o1"), (part, "o1"), kind="waveguide")
    scene.route((part, bar_port), (bar, "o1"), kind="waveguide")
    scene.route((part, cross_port), (cross, "o1"), kind="waveguide")
    inputs, _ = default_inputs(scene)
    table = compile_table(scene, mode="cw", inputs=inputs)
    nm = next(r["wavelength_nm"] for e in table["edges"].values() for r in e["cw"])
    sid = scene_ids(scene)[id(part)]
    return (fieldmodel.port_intensity(table, f"port:{sid}:{cross_port}", nm),
            fieldmodel.port_intensity(table, f"port:{sid}:{bar_port}", nm))


def test_cw_mode_at_full_coupling_puts_all_power_on_the_cross_port():
    cross, bar = _cross_and_bar_power(optodraw.DirectionalCoupler, "o3", "o4", coupling_ratio=1.0)
    assert cross == pytest.approx(1.0, abs=1e-9)
    assert bar == pytest.approx(0.0, abs=1e-9)


def test_a_directional_coupler_passes_its_coupling_ratio_to_the_engine():
    cross, bar = _cross_and_bar_power(optodraw.DirectionalCoupler, "o3", "o4", coupling_ratio=0.3)
    assert cross == pytest.approx(0.3, abs=1e-6)
    assert bar == pytest.approx(0.7, abs=1e-6)


def test_a_tap_coupler_passes_its_tap_ratio_to_the_engine():
    cross, bar = _cross_and_bar_power(optodraw.TapCoupler, "o2", "o3", tap_ratio=0.2)
    assert cross == pytest.approx(0.2, abs=1e-6)
    assert bar == pytest.approx(0.8, abs=1e-6)


def test_the_engine_reads_a_fibre_coupler_ratio():
    assert Coupler2x2().kappa(optodraw.FiberCoupler(ratio=0.25)) == pytest.approx(0.25)


def test_a_directional_coupler_rejects_a_ratio_outside_zero_to_one():
    with pytest.raises(ValueError):
        optodraw.DirectionalCoupler(coupling_ratio=1.2)


def test_the_drawing_copy_of_a_directional_coupler_keeps_its_coupling_ratio():
    part = optodraw.DirectionalCoupler(coupling_ratio=0.3)
    assert part._draw_variant().coupling_ratio == 0.3
    assert part.physics_metadata()["coupling_ratio"] == 0.3
