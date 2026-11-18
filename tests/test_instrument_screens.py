"""Instruments that show computed data: a scope's traces, an OSA's spectrum, the reading of a power meter and of a
lock-in, on the 2D screen. With none of it, each part draws and saves as before."""

from __future__ import annotations

import json
import re

import numpy as np
import pytest

from optodraw import OSA, LockInAmplifier, OpticalPowerMeter, Oscilloscope, Scene
from optodraw.animation_engine import Spectrum
from optodraw.components.instruments import screen_points
from optodraw.schema import component_to_spec
from optodraw.symbols.art import art_2d

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


def test_screen_points_fill_the_screen_and_keep_400_points_of_10000_evenly():
    # mutant: keep = np.arange(_SCREEN_POINTS) in screen_points: only the start of the record is kept
    t = np.linspace(0.0, 2 * np.pi, 10_000)
    points = screen_points(t, np.sin(t))
    assert len(points) == 400
    assert points[0] == pytest.approx((-1.0, 0.0), abs=1e-3) and points[-1] == pytest.approx((1.0, 0.0), abs=1e-3)
    assert min(v for _, v in points) == -0.8 and max(v for _, v in points) == 0.8
    assert max(points, key=lambda p: p[1])[0] == pytest.approx(-0.5, abs=0.01)     # the peak at a quarter period


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


def test_the_symbol_keeps_its_screen_and_shows_the_trace_in_place_of_its_demo_wave():
    # mutant: _DEMO_TRACE matches nothing in art.py: the demo wave stays under the computed trace
    # mutant: "+ PT_PER_CM * y" in _screen_overlay: the trace leaves the screen, mirrored about the symbol origin
    from optodraw.symbols.art import fit_art

    scope = Oscilloscope(traces={"ch2": [(-1.0, 0.0), (1.0, 0.5)]})
    node = art_2d(scope)
    assert node["symbol"] == "oscilloscope" and "fb923c" not in node["svg"].lower()      # the pic, without its demo
    (line,) = node["overlay"]["children"]
    art = fit_art(scope)
    x0, y0, x1, y1 = Oscilloscope.SCREEN                     # the screen of the pic, cm, y up from the pic origin

    def local(x_cm, y_cm):
        return art.local(art.symbol.origin[0] + x_cm * 72 / 2.54, art.symbol.origin[1] - y_cm * 72 / 2.54)

    (left, bottom), (right, top) = local(x0, y0), local(x1, y1)
    centre_y = (bottom + top) / 2
    assert line["stroke"] == "#56B4E9"
    assert line["points"][0] == pytest.approx((left + 0.05 * (right - left), centre_y))
    assert line["points"][1] == pytest.approx((right - 0.05 * (right - left), centre_y + 0.5 * 0.4 * (top - bottom)))
    scene = Scene(width=60, height=40)
    scene.add(scope)
    svg = scene.render_svg().as_svg()
    assert 'data-art="oscilloscope"' in svg and "#56B4E9" in svg
    assert "trace=none" in scene.render_tikz()               # the TikZ pic hides its demo wave too


def test_an_osa_with_a_trace_draws_it_in_place_of_the_demo_peaks():
    # mutant: `if self.trace is None` -> `if True` in OSA.geometry_2d: the demo peaks stay on the screen
    trace = [(-1.0, -0.8), (0.0, 0.8), (1.0, -0.8)]
    (line,) = _children(OSA(trace=trace), "polyline")
    assert line["points"] == [(-4.6 + u * 17.6 * 0.45, 2.2 + v * 11.2 * 0.4) for u, v in trace]


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


def test_with_no_new_field_each_part_draws_and_saves_as_before():
    # mutant: `traces=None` -> `traces={}` in Oscilloscope.__init__: a plain scope loses its demo wave and its symbol
    scope, osa, meter, lockin = Oscilloscope(), OSA(), OpticalPowerMeter(), LockInAmplifier()
    assert [line["points"] for line in _children(scope, "polyline")] == [SCOPE_DEMO]
    assert [line["points"] for line in _children(osa, "polyline")] == [OSA_DEMO]
    assert _children(meter, "text") == [] and _children(lockin, "text") == []
    for part in (scope, osa, meter, lockin):
        node = art_2d(part)
        assert node is not None and "overlay" not in node     # the symbol art paints it in 2D, demo and all
        assert "trace" not in node["params"]
        assert not {"traces", "trace", "reading"} & set(component_to_spec(part))


def test_the_new_fields_save_and_load():
    # mutant: drop "traces" from the Oscilloscope row in registry.py: the traces are lost on reload
    parts = [Oscilloscope(center=(-60, 0), traces={"ch1": [(-1.0, 0.0), (1.0, 0.8)], "ch2": [(0.0, -0.8)]}),
             OSA(center=(-20, 0), trace=[(-1.0, -0.8), (0.0, 0.8), (1.0, -0.8)]),
             OpticalPowerMeter(center=(20, 0), reading="1.20 mW"), LockInAmplifier(center=(60, 0), reading="X = 3.4 mV")]
    scene = Scene(width=200, height=80)
    for part in parts:
        scene.add(part)
    again = {type(item): item for item in Scene.from_spec(json.loads(json.dumps(scene.to_spec()))).walk()}
    scope, osa, meter, lockin = parts
    assert again[Oscilloscope].traces == scope.traces          # JSON lists come back as point tuples
    assert again[OSA].trace == osa.trace
    assert again[OpticalPowerMeter].reading == "1.20 mW" and again[LockInAmplifier].reading == "X = 3.4 mV"


def test_spectrum_show_puts_the_power_in_db_on_the_osa_screen():
    # mutant: 1e-6 -> 1e-9 in Spectrum.show: the floor drops to -90 dB and squeezes the spectrum up
    osa = OSA()
    spectrum = Spectrum(np.array([1540.0, 1550.0, 1560.0]), {"o:in": np.array([1.0, 0.1, 0.0])}, (), {id(osa): "o"})
    spectrum.show(osa)
    # 0, -10 and -60 dBm (the floor, under no light) on a screen from -0.8 to 0.8
    assert [c for point in osa.trace for c in point] == pytest.approx([-1.0, 0.8, 0.0, 0.8 * (2 * 50 / 60 - 1), 1.0, -0.8])
    with pytest.raises(KeyError):
        spectrum.show(osa, port="out")
