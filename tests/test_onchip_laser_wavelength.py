"""An on-chip laser has a wavelength: it is kept, saved and emitted."""

from __future__ import annotations

import pytest

from optodraw import OnChipLaser, Scene
from optodraw.animation_engine.behaviours.sources import Source
from optodraw.schema import scene_from_spec, scene_to_spec


def test_an_on_chip_laser_keeps_its_wavelength():
    assert OnChipLaser().wavelength_nm == pytest.approx(1550.0)
    assert OnChipLaser(wavelength_nm=1310.0).wavelength_nm == pytest.approx(1310.0)


def test_the_wavelength_survives_a_save_and_reload():
    scene = Scene(title="", width=200, height=100, platform="on_chip")
    scene.add(OnChipLaser(wavelength_nm=1310.0, label="LD"))
    (laser,) = [node for node in scene_from_spec(scene_to_spec(scene)).walk() if node.component_type == "OnChipLaser"]
    assert laser.wavelength_nm == pytest.approx(1310.0)


def test_the_laser_emits_at_its_wavelength():
    (emission,) = Source().emissions(OnChipLaser(wavelength_nm=1310.0), "ld", {})
    assert emission.wavelength_nm == pytest.approx(1310.0)
