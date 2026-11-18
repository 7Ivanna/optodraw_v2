"""A neutral density filter takes the same share of every wavelength, and it leaves the beam its colour."""

from __future__ import annotations

import pytest

from optodraw import Laser, NDFilter, Photodiode, Scene
from optodraw.animation_engine.behaviours import behaviour_for


def _bench(**kwargs):
    scene = Scene(title="nd", width=100, height=40, platform="free_space")
    laser = scene.add(Laser(center=(-30, 0), wavelength=450, label="Laser"))
    nd = scene.add(NDFilter(center=(0, 0), label="ND wheel", **kwargs))
    pd = scene.add(Photodiode(center=(30, 0), label="PD"))
    return scene, laser, nd, pd


def test_a_negative_density_is_refused():
    with pytest.raises(ValueError, match="optical_density"):
        NDFilter(optical_density=-1.0)


def test_light_keeps_ten_to_the_minus_od_of_its_power():
    part = NDFilter(optical_density=2.0)
    amplitude = behaviour_for(part, "s").amplitude(part, "s", 450.0, {})
    assert amplitude ** 2 == pytest.approx(0.01)


