"""Instruments that show computed data: a scope's traces, an OSA's spectrum, the reading of a power meter and of a
lock-in, on the 2D screen. With none of it, each part draws and saves as before."""

from __future__ import annotations


import numpy as np
import pytest

from optodraw import OSA, LockInAmplifier, OpticalPowerMeter, Oscilloscope, Scene
from optodraw.animation_engine import Spectrum
from optodraw.components.instruments import screen_points

SCOPE_DEMO = [(-9.6, 2.0), (-7.8, 5.4), (-6.0, -1.0), (-4.2, 5.4), (-2.4, -1.0), (-0.6, 5.4), (1.2, -1.0), (3.0, 2.0),
              (4.2, 2.0)]
OSA_DEMO = [(-12.6, -2.0), (-10.8, -2.0), (-10.2, 4.6), (-9.6, -2.0), (-7.4, -2.0), (-6.9, 2.2), (-6.4, -2.0),
            (-3.6, -2.0), (-3.1, 6.2), (-2.6, -2.0), (0.4, -2.0), (0.9, 1.4), (1.4, -2.0), (3.4, -2.0)]


def _children(part, kind):
    return [child for child in part.geometry_2d()["children"] if child["type"] == kind]


def _screen(part):
    """The (x0, y0, x1, y1) of the part's dark 2D screen."""

    rect = next(child for child in _children(part, "rect") if child["fill"] == "#101720")
    return rect["cx"] - rect["w"] / 2, rect["cy"] - rect["h"] / 2, rect["cx"] + rect["w"] / 2, rect["cy"] + rect["h"] / 2


def test_a_flat_signal_sits_at_zero_and_unequal_series_are_refused():
    # mutant: np.zeros_like(values) -> np.full_like(values, -half) in screen_points: a flat signal lies on the floor
    assert screen_points([0.0, 1.0, 2.0], [5.0, 5.0, 5.0]) == [(-1.0, 0.0), (0.0, 0.0), (1.0, 0.0)]
    with pytest.raises(ValueError, match="one length"):
        screen_points([0.0, 1.0], [1.0])


def test_a_scope_with_traces_draws_each_channel_in_its_colour_on_the_screen():
    # mutant: "ch2": _DATA in Oscilloscope.CHANNEL_COLOURS: the two channels cannot be told apart
    ch1, ch2 = screen_points(range(5), [0, 1, 0, -1, 0]), screen_points(range(3), [0, 0, 1])
    scope = Oscilloscope(traces={"ch1": ch1, "ch2": ch2})
    drawn = {line["stroke"]: line["points"] for line in _children(scope, "polyline")}
    assert drawn == {"#FB923C": [(-2.8 + u * 14.8 * 0.45, 2.0 + v * 9.2 * 0.4) for u, v in ch1],
                     "#56B4E9": [(-2.8 + u * 14.8 * 0.45, 2.0 + v * 9.2 * 0.4) for u, v in ch2]}
    x0, y0, x1, y1 = _screen(scope)
    assert all(x0 < x < x1 and y0 < y < y1 for points in drawn.values() for x, y in points)
    assert scope.geometry_3d() == Oscilloscope().geometry_3d()          # the 3D screen keeps its demo wave for now
    with pytest.raises(ValueError, match="ch3"):
        Oscilloscope(traces={"ch3": ch1})


def test_a_reading_is_drawn_on_the_display_and_in_the_2d_svg():
    # mutant: "y": 1.6 -> "y": 9.6 in OpticalPowerMeter.geometry_2d: the reading leaves the display
    meter, lockin = OpticalPowerMeter(center=(-30, 0), reading="1.20 mW"), LockInAmplifier(center=(30, 0), reading="X = 3.4 mV")
    for part, reading in ((meter, "1.20 mW"), (lockin, "X = 3.4 mV")):
        (text,) = _children(part, "text")
        x0, y0, x1, y1 = _screen(part)
        assert text["text"] == reading and x0 < text["x"] < x1 and y0 < text["y"] < y1
    scene = Scene(width=120, height=60)
    scene.add(meter)
    scene.add(lockin)
    svg = scene.render_svg().as_svg()
    assert "1.20 mW" in svg and "X = 3.4 mV" in svg


def test_spectrum_show_puts_the_power_in_db_on_the_osa_screen():
    # mutant: 1e-6 -> 1e-9 in Spectrum.show: the floor drops to -90 dB and squeezes the spectrum up
    osa = OSA()
    spectrum = Spectrum(np.array([1540.0, 1550.0, 1560.0]), {"o:in": np.array([1.0, 0.1, 0.0])}, (), {id(osa): "o"})
    spectrum.show(osa)
    # 0, -10 and -60 dBm (the floor, under no light) on a screen from -0.8 to 0.8
    assert [c for point in osa.trace for c in point] == pytest.approx([-1.0, 0.8, 0.0, 0.8 * (2 * 50 / 60 - 1), 1.0, -0.8])
    with pytest.raises(KeyError):
        spectrum.show(osa, port="out")
