"""A default optical chopper is about as tall as the optics beside it: a 26 unit wheel drew 2 to 5 times larger."""

from __future__ import annotations

from optodraw import HalfWavePlate, Lens, Mirror, OpticalChopper


def _tall(part):
    x0, y0, x1, y1 = part.drawn_box()
    return y1 - y0


def test_a_default_chopper_is_near_the_size_of_its_neighbours():
    neighbours = max(_tall(part) for part in (Lens(), Mirror(), HalfWavePlate()))
    assert _tall(OpticalChopper()) <= 1.5 * neighbours


def test_a_chopper_takes_the_wheel_it_is_given():
    assert _tall(OpticalChopper(wheel_diameter=26.0)) > 2.0 * _tall(OpticalChopper())
