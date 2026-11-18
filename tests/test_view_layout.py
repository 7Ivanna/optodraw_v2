"""Display spacing per view: the 3D bench spreads out, the 1D and 2D drawings stay compact."""

from __future__ import annotations


import pytest

import optodraw
from optodraw.core.view_layout import validate_layout


def _bench():
    scene = optodraw.Scene(platform="free_space")
    laser = scene.add(optodraw.Laser(center=(-30, 0), label="Laser"))
    lens = scene.add(optodraw.Lens(center=(-18, 0), label="Lens"))
    pd = scene.add(optodraw.Photodiode(center=(-6, 0), label="Detector"))
    scene.add(optodraw.Beam.through(laser, lens, pd))
    return scene, laser, lens, pd


def test_automatic_spacing_is_only_for_3d():
    assert validate_layout({"3d": {"spacing": "auto"}})["3d"]["spacing"] == "auto"
    with pytest.raises(ValueError):
        validate_layout({"2d": {"spacing": "auto"}})


