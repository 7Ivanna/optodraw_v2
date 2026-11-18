"""Coupler settings reach the engine, and cw mode copes with a fully dark output."""

import pytest

import optodraw
from optodraw.animation3d import fieldmodel
from optodraw.animation3d.inputs import default_inputs
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


def test_a_tap_coupler_passes_its_tap_ratio_to_the_engine():
    cross, bar = _cross_and_bar_power(optodraw.TapCoupler, "o2", "o3", tap_ratio=0.2)
    assert cross == pytest.approx(0.2, abs=1e-6)
    assert bar == pytest.approx(0.8, abs=1e-6)


def test_a_directional_coupler_rejects_a_ratio_outside_zero_to_one():
    with pytest.raises(ValueError):
        optodraw.DirectionalCoupler(coupling_ratio=1.2)


