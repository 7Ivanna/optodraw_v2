"""Signal drawings for a page: a timing diagram drawn as vector, and an eye diagram as a house-style plot."""

from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np
import pytest

from optodraw.figure.sources import from_record
from optodraw.figure.timing import Bits, Bus, Clock, TimeMark, Timing, Trace


def _timing(**options) -> Timing:
    t = np.linspace(0.0, 8.0, 81)
    return Timing([Clock("Clock", period=1.0),
                   Bits("DAC", [0, 1, 1, 0, 1, 0, 0, 1], bit_time=1.0),
                   Bus("Word", ["A3", "B7", "C0", "D1"], word_time=2.0),
                   Trace("ADC in", t, np.sin(t))], span=(0.0, 8.0), unit="ns", **options)


def _points(path: str) -> list[tuple[float, float]]:
    """The points of the first waveform path in ``path`` (an M/L path)."""

    d = re.search(r'class="od-wave"[^>]*\sd="([^"]+)"|\sd="([^"]+)"[^>]*class="od-wave"', path)
    assert d, "no waveform path"
    numbers = [float(v) for v in re.findall(r"-?\d+(?:\.\d+)?(?:e-?\d+)?", d.group(1) or d.group(2))]
    return list(zip(numbers[0::2], numbers[1::2]))


def test_place_takes_time_and_row():
    timing = _timing()
    fragment = timing.fragment(100.0, font_pt=7.0)
    (x0, y0), (x1, y1) = fragment.place(0.0, 0), fragment.place(8.0, 0)
    assert 0.0 < x0 < x1 <= 100.0 and y0 == y1
    assert fragment.place(4.0, 0)[0] == pytest.approx((x0 + x1) / 2)
    assert fragment.place(0.0, 1)[1] > y0                                       # the next row is lower on the page
    assert timing.row("DAC") == 1 and timing.row("ADC in") == 3
    with pytest.raises(KeyError, match="Clock"):
        timing.row("Nothing")


def test_the_record_draws_the_same_timing():
    timing = _timing(marks=[TimeMark(2.0, label="t0")], illustrative=True)
    record = json.loads(json.dumps(timing.to_record()))
    again = from_record(record, Path("."))
    assert again.fragment(90.0, font_pt=7.0).svg == timing.fragment(90.0, font_pt=7.0).svg


@pytest.mark.parametrize("make, words", [
    (lambda: Timing([], span=(0, 1)), "row"),
    (lambda: Timing([Clock("a", period=1.0)], span=(2, 1)), "span"),
    (lambda: Timing([Clock("a", period=0.0)], span=(0, 1)), "period"),
    (lambda: Timing([Clock("a", period=1.0, duty=1.0)], span=(0, 1)), "duty"),
    (lambda: Timing([Bits("a", [0, 2], bit_time=1.0)], span=(0, 2)), "0 or 1"),
    (lambda: Timing([Trace("a", [0, 1, 2], [0, 1])], span=(0, 2)), "same length"),
    (lambda: Timing([Trace("a", [0, 1], [0, float("nan")])], span=(0, 2)), "finite"),
    (lambda: Timing([Clock("a", period=1.0), Bits("a", [0], bit_time=1.0)], span=(0, 1)), "twice"),
])
def test_a_wrong_timing_says_what_is_wrong(make, words):
    with pytest.raises(ValueError, match=words):
        make()


# -- the eye diagram ---------------------------------------------------------- #


def _nrz(bits: int = 64, spu: int = 16, seed: int = 3) -> np.ndarray:
    rng = np.random.default_rng(seed)
    levels = np.repeat(rng.integers(0, 2, bits) * 2.0 - 1.0, spu)
    kernel = np.ones(spu // 2) / (spu // 2)
    return np.convolve(levels, kernel, mode="same")


def test_an_eye_overlays_one_trace_per_unit_interval():
    from optodraw.plots import eye_diagram

    samples, spu = _nrz(), 16
    fig = eye_diagram(samples, samples_per_ui=spu)
    ax = fig.axes[0]
    windows = (len(samples) - 2 * spu) // spu + 1
    assert len(ax.lines) == windows
    assert all(len(line.get_xdata()) == 2 * spu for line in ax.lines)
    assert ax.get_xlim() == pytest.approx((0.0, 2.0))
    assert "UI" in ax.get_xlabel()


@pytest.mark.parametrize("samples, spu, words", [(np.zeros(100), 1, "samples_per_ui"), (np.zeros(10), 8, "two")])
def test_an_eye_refuses_data_it_cannot_fold(samples, spu, words):
    from optodraw.plots import eye_diagram

    with pytest.raises(ValueError, match=words):
        eye_diagram(samples, samples_per_ui=spu)


def test_a_house_figure_has_the_asked_size_and_look():
    from optodraw.plots import house_figure

    fig, ax = house_figure(60.0, 40.0)
    assert tuple(fig.get_size_inches()) == pytest.approx((60.0 / 25.4, 40.0 / 25.4))
    assert not ax.spines["top"].get_visible() and not ax.spines["right"].get_visible()
