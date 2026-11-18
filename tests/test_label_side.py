"""A part's label beside it (left, right, below) as well as above: papers label a vertical path at its side."""

from __future__ import annotations


import pytest

from optodraw import Mirror, Scene


def _one(side=None, angle=0):
    scene = Scene(width=80, height=60, platform="free_space")
    mirror = scene.add(Mirror(center=(0, 0), angle=angle, aperture=10, label="M1"))
    if side is not None:
        mirror.label_side = side
    return scene


def test_an_unknown_label_side_names_the_part():
    with pytest.raises(ValueError, match="M1.*label_side"):
        _one("middle").render_svg()


