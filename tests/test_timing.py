"""Signal drawings for a page: a timing diagram drawn as vector, and an eye diagram as a house-style plot."""

from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np
import pytest

from optodraw.figure import Inset, Page
from optodraw.figure.fragment import PT_MM
from optodraw.figure.sources import from_record
from optodraw.figure.timing import Bits, Bus, Clock, TimeMark, Timing, Trace


def _timing(**options) -> Timing:
    t = np.linspace(0.0, 8.0, 81)
    return Timing([Clock("Clock", period=1.0),
                   Bits("DAC", [0, 1, 1, 0, 1, 0, 0, 1], bit_time=1.0),
                   Bus("Word", ["A3", "B7", "C0", "D1"], word_time=2.0),
                   Trace("ADC in", t, np.sin(t))], span=(0.0, 8.0), unit="ns", **options)


def _row(svg: str, name: str) -> str:
    match = re.search(rf'<g data-row="{re.escape(name)}">(.*?)</g>', svg, re.S)
    assert match, f"no row {name!r}"
    return match.group(1)


def _points(path: str) -> list[tuple[float, float]]:
    """The points of the first waveform path in ``path`` (an M/L path)."""

    d = re.search(r'class="od-wave"[^>]*\sd="([^"]+)"|\sd="([^"]+)"[^>]*class="od-wave"', path)
    assert d, "no waveform path"
    numbers = [float(v) for v in re.findall(r"-?\d+(?:\.\d+)?(?:e-?\d+)?", d.group(1) or d.group(2))]
    return list(zip(numbers[0::2], numbers[1::2]))


def _edges(points):
    """The x of each vertical step: two points in a row at one x and two heights."""

    return [round(a[0], 3) for a, b in zip(points, points[1:]) if abs(a[0] - b[0]) < 1e-6 and abs(a[1] - b[1]) > 1e-6]


def test_a_clock_steps_at_each_half_period():
    timing = Timing([Clock("Clock", period=1.0)], span=(0.0, 4.0))
    fragment = timing.fragment(80.0, font_pt=7.0)
    edges = _edges(_points(_row(fragment.svg, "Clock")))
    assert edges == [round(fragment.place(t, 0)[0], 3) for t in np.arange(0.5, 4.0, 0.5)]


def test_a_clock_takes_duty_and_phase():
    timing = Timing([Clock("Clock", period=2.0, duty=0.25, phase=0.5)], span=(0.0, 4.0))
    fragment = timing.fragment(80.0, font_pt=7.0)
    edges = _edges(_points(_row(fragment.svg, "Clock")))
    assert edges == [round(fragment.place(t, 0)[0], 3) for t in (0.5, 1.0, 2.5, 3.0)]


def test_bits_step_only_where_they_change():
    timing = Timing([Bits("DAC", [0, 1, 1, 0], bit_time=1.0)], span=(0.0, 4.0))
    fragment = timing.fragment(80.0, font_pt=7.0)
    points = _points(_row(fragment.svg, "DAC"))
    assert _edges(points) == [round(fragment.place(t, 0)[0], 3) for t in (1.0, 3.0)]
    high, low = min(y for _, y in points), max(y for _, y in points)
    top, bottom = fragment.place(0.0, -0.5)[1], fragment.place(0.0, 0.5)[1]
    assert top < high < low < bottom                                             # inside the row, high above low
    assert points[0][1] == low and points[2][1] == high                          # the first bit is 0, the next 1


def test_a_bus_writes_each_word_in_its_cell():
    timing = Timing([Bus("Word", ["A3", "B7"], word_time=2.0)], span=(0.0, 4.0))
    row = _row(timing.fragment(80.0, font_pt=7.0).svg, "Word")
    assert re.findall(r">(A3|B7)</text>", row) == ["A3", "B7"]


def test_a_trace_keeps_every_sample_inside_its_row():
    t = np.linspace(0.0, 4.0, 41)
    timing = Timing([Trace("ADC in", t, np.cos(t))], span=(0.0, 4.0))
    fragment = timing.fragment(80.0, font_pt=7.0)
    points = _points(_row(fragment.svg, "ADC in"))
    assert len(points) == 41
    assert points[0][0] == pytest.approx(fragment.place(0.0, 0)[0], abs=1e-3)
    assert points[-1][0] == pytest.approx(fragment.place(4.0, 0)[0], abs=1e-3)
    top, bottom = fragment.place(0.0, -0.5)[1], fragment.place(0.0, 0.5)[1]
    assert all(top < y < bottom for _, y in points)
    assert points[0][1] == min(y for _, y in points)                             # cos(0), the largest, is the highest


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


def test_row_mm_sets_the_row_pitch():
    fragment = _timing(row_mm=6.0).fragment(100.0, font_pt=7.0)
    assert fragment.place(0.0, 1)[1] - fragment.place(0.0, 0)[1] == pytest.approx(6.0)
    taller = Timing([Clock("a", period=1.0), Clock("b", period=1.0), Clock("c", period=1.0)], span=(0, 4))
    shorter = Timing([Clock("a", period=1.0), Clock("b", period=1.0)], span=(0, 4))
    assert taller.fragment(80.0, font_pt=7.0).size_mm[1] > shorter.fragment(80.0, font_pt=7.0).size_mm[1]


def test_a_time_mark_crosses_every_row_and_names_itself():
    timing = Timing([Clock("Clock", period=1.0), Bits("DAC", [0, 1], bit_time=2.0)], span=(0.0, 4.0),
                    marks=[TimeMark(1.5, label="sample")])
    fragment = timing.fragment(80.0, font_pt=7.0)
    line = re.search(r'<line[^>]*data-mark="sample"[^>]*>', fragment.svg)
    assert line and "stroke-dasharray" in line.group(0)
    x = float(re.search(r'x1="([-\d.]+)"', line.group(0)).group(1))
    assert x == pytest.approx(fragment.place(1.5, 0)[0], abs=1e-3)
    y1, y2 = (float(re.search(rf'{k}="([-\d.]+)"', line.group(0)).group(1)) for k in ("y1", "y2"))
    assert min(y1, y2) <= fragment.place(1.5, -0.5)[1] and max(y1, y2) >= fragment.place(1.5, 1.5)[1]
    assert ">sample</text>" in fragment.svg


def test_the_axis_names_its_unit_and_ticks():
    svg = _timing().fragment(100.0, font_pt=7.0).svg
    assert re.search(r">[^<]*ns[^<]*</text>", svg)
    assert len(re.findall(r'<text[^>]*data-tick="', svg)) >= 3


def test_text_prints_at_the_page_font():
    for font in (6.0, 8.0):
        sizes = set(re.findall(r'font-size="([\d.]+)"', _timing().fragment(100.0, font_pt=font).svg))
        assert sizes == {f"{round(font * PT_MM, 4):g}"}


def test_an_illustrative_timing_says_so():
    assert any("illustrative" in note for note in _timing(illustrative=True).fragment(80.0, font_pt=7.0).notes)
    assert not _timing().fragment(80.0, font_pt=7.0).notes


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


def test_a_timing_inset_passes_the_export_gates(tmp_path):
    from optodraw.check import check_export

    page = Page(width_mm=120, height_mm=50, font_pt=7.0, letters=False)
    page.add(Inset(_timing(marks=[TimeMark(3.0, label="sample")]), center=(60, 25), width=100))
    assert page.svg().count("<image") == 0
    path = tmp_path / "timing.svg"
    path.write_text(page.svg(), encoding="utf-8")
    assert check_export(path) == []


def test_a_mark_lands_on_a_time_and_a_row():
    page = Page(width_mm=120, height_mm=50, letters=False)
    timing = _timing()
    inset = page.add(Inset(timing, center=(60, 25), width=100))
    x0, y0, x1, y1 = inset.box()
    x, y = inset.at(4.0, timing.row("DAC")).xy()
    assert x0 < x < x1 and y0 < y < y1
    assert inset.at(4.0, 0).xy()[1] > y                                         # page y is up: row 0 is above row 1


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


def test_an_eye_has_the_house_look():
    from optodraw.plots import eye_diagram

    ax = eye_diagram(_nrz(), samples_per_ui=16).axes[0]
    assert not ax.spines["top"].get_visible() and not ax.spines["right"].get_visible()
    assert not ax.get_title()


@pytest.mark.parametrize("samples, spu, words", [(np.zeros(100), 1, "samples_per_ui"), (np.zeros(10), 8, "two")])
def test_an_eye_refuses_data_it_cannot_fold(samples, spu, words):
    from optodraw.plots import eye_diagram

    with pytest.raises(ValueError, match=words):
        eye_diagram(samples, samples_per_ui=spu)


def test_an_eye_goes_into_an_inset_and_takes_marks_in_ui():
    from optodraw.plots import eye_diagram

    page = Page(width_mm=120, height_mm=60, letters=False)
    inset = page.add(Inset(eye_diagram(_nrz(), samples_per_ui=16), center=(60, 30), width=60, height=40))
    x0, y0, x1, y1 = inset.box()
    x, y = inset.at(1.0, 0.0).xy()
    assert x0 < x < x1 and y0 < y < y1


def test_a_house_figure_has_the_asked_size_and_look():
    from optodraw.plots import house_figure

    fig, ax = house_figure(60.0, 40.0)
    assert tuple(fig.get_size_inches()) == pytest.approx((60.0 / 25.4, 40.0 / 25.4))
    assert not ax.spines["top"].get_visible() and not ax.spines["right"].get_visible()
