"""A timing diagram drawn as vector inside an inset: clocks, bit rows, buses, analog traces and time marks.

``place(t, r)`` takes a time and a row index. Row 0 is the top row: its middle is at ``r = 0`` and its edges at
``r = -0.5`` and ``r = 0.5``. The next row is lower on the page. Text prints in the page's font at its ``font_pt``.
"""

from __future__ import annotations

import html
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

from optodraw.core.markup import svg_text, text_width
from optodraw.figure.fragment import PT_MM, Fragment, affine, place_from

ROW_PITCH = 2.4             # the row pitch over the text size
LEVEL = 0.3                 # high and low sit this many rows above and below the middle of their row
PAD = 1.0                   # the gap after the name column, in text sizes
BAND = 1.3                  # the band over the rows that holds the mark labels, in text sizes
TICK = 0.4                  # the tick length, in text sizes
MOST_TICKS = 6
WAVE_MM, AXIS_MM, MARK_MM = 0.25, 0.18, 0.18        # 0.71 and 0.51 pt: over the 0.25 pt line-weight gate
DASH_MM = "0.8 0.6"
BLACK, BLUE, GREY, WHITE = "#000000", "#0072B2", "#7F7F7F", "#FFFFFF"     # research-figures: Okabe-Ito
ILLUSTRATIVE = "illustrative timing, not measured"
_INKS = {"black": BLACK, "blue": BLUE}

Place = Callable[[float, float], tuple[float, float]]
Write = Callable[..., str]


def _finite(value: Any, what: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{what} is a finite number, got {value!r}")
    return number


def _positive(value: Any, what: str) -> float:
    number = float(value)
    if not (math.isfinite(number) and number > 0.0):
        raise ValueError(f"{what} is a finite number above 0, got {value!r}")
    return number


def _set(row: Any, **values: Any) -> None:
    """Store checked values on a frozen row."""

    for key, value in values.items():
        object.__setattr__(row, key, value)


def _num(value: float) -> str:
    return repr(float(value))       # in full: a reader of the SVG gets back the float that place gives


def _d(points: Iterable[tuple[float, float]]) -> str:
    return "M" + "L".join(f"{_num(x)} {_num(y)}" for x, y in points)


def _wave(points: list[tuple[float, float]], color: str) -> str:
    if len(points) < 2:
        return ""
    return f'<path class="od-wave" d="{_d(points)}" fill="none" stroke="{color}" stroke-width="{WAVE_MM}"/>'


def _steps(changes: list[tuple[float, int]], t0: float, t1: float) -> list[tuple[float, int]]:
    """The corners of a step line over ``[t0, t1]``. ``changes`` are ``(time, level)`` in time order: each level holds
    to the next time, and the last time only ends the line. A level equal to the one before draws no step."""

    points: list[tuple[float, int]] = []
    for (a, level), (b, _) in zip(changes, changes[1:]):
        a, b = max(a, t0), min(b, t1)
        if b <= a:
            continue
        if points and points[-1][1] == level:
            points[-1] = (b, level)
        else:
            points += [(a, level), (b, level)]
    return points


def _digital(changes: list[tuple[float, int]], place: Place, r: int, span: tuple[float, float], color: str) -> str:
    return _wave([place(t, r - LEVEL if level else r + LEVEL) for t, level in _steps(changes, *span)], color)


@dataclass(frozen=True)
class Clock:
    """A clock row. It is high on ``[phase + k period, phase + k period + duty period)`` for every whole ``k``, and
    low between."""

    name: str
    period: float
    duty: float = 0.5
    phase: float = 0.0

    def __post_init__(self) -> None:
        duty = float(self.duty)
        if not 0.0 < duty < 1.0:
            raise ValueError(f"a clock's duty is a share between 0 and 1, got {self.duty!r}")
        _set(self, period=_positive(self.period, "a clock's period"), duty=duty,
             phase=_finite(self.phase, "a clock's phase"))

    def _svg(self, place: Place, r: int, span: tuple[float, float], text: Write) -> str:
        k0 = math.floor((span[0] - self.phase) / self.period)
        k1 = math.ceil((span[1] - self.phase) / self.period)
        changes = [(self.phase + k * self.period + share * self.period, level)
                   for k in range(k0, k1 + 1) for share, level in ((0.0, 1), (self.duty, 0))]
        return _digital(changes, place, r, span, BLACK)


@dataclass(frozen=True)
class Bits:
    """A bit row, NRZ. Bit ``i`` holds from ``start + i bit_time`` for one ``bit_time``. Each bit is 0 or 1.
    ``color`` is ``"black"`` (the default) or ``"blue"``."""

    name: str
    bits: tuple[int, ...]
    bit_time: float
    start: float = 0.0
    color: str = "black"

    def __post_init__(self) -> None:
        wrong = [bit for bit in self.bits if bit not in (0, 1)]
        if wrong:
            raise ValueError(f"a bit is 0 or 1, got {wrong[0]!r}")
        if self.color not in _INKS:
            raise ValueError(f"a bit row's color is black or blue, got {self.color!r}")
        _set(self, bits=tuple(int(bit) for bit in self.bits), bit_time=_positive(self.bit_time, "a bit row's bit_time"),
             start=_finite(self.start, "a bit row's start"))

    def _svg(self, place: Place, r: int, span: tuple[float, float], text: Write) -> str:
        changes = [(self.start + i * self.bit_time, bit) for i, bit in enumerate(self.bits + (0,))]
        return _digital(changes, place, r, span, _INKS[self.color])


@dataclass(frozen=True)
class Bus:
    """A bus row. Word ``i`` fills one cell from ``start + i word_time`` for one ``word_time``. A cell has pointed
    ends and holds its word as text."""

    name: str
    words: tuple[str, ...]
    word_time: float
    start: float = 0.0

    def __post_init__(self) -> None:
        _set(self, words=tuple(str(word) for word in self.words),
             word_time=_positive(self.word_time, "a bus row's word_time"),
             start=_finite(self.start, "a bus row's start"))

    def _svg(self, place: Place, r: int, span: tuple[float, float], text: Write) -> str:
        times = [self.start + i * self.word_time for i in range(len(self.words) + 1)]
        cells, words = [], []
        for a, b, word in zip(times, times[1:], self.words):
            a, b = max(a, span[0]), min(b, span[1])
            if b <= a:
                continue
            (xa, mid), xb = place(a, r), place(b, r)[0]
            high, low = place(a, r - LEVEL)[1], place(a, r + LEVEL)[1]
            slant = min(0.25 * (low - high), 0.5 * (xb - xa))
            cells.append(_d([(xa, mid), (xa + slant, high), (xb - slant, high), (xb, mid), (xb - slant, low),
                             (xa + slant, low)]) + "Z")
            # shortcut: a word wider than its cell runs over the cell's edges; shorten the word or widen the inset
            words.append(text(word, 0.5 * (xa + xb), mid, "middle"))
        if not cells:
            return ""
        # filled white, so a time mark stops at the cell and never runs through its word
        return (f'<path class="od-wave" d="{"".join(cells)}" fill="{WHITE}" stroke="{BLACK}" '
                f'stroke-width="{WAVE_MM}"/>' + "".join(words))


@dataclass(frozen=True)
class Trace:
    """An analog row: the author's samples ``y`` at times ``t``. They are scaled into the row from ``low`` to
    ``high``, by default the smallest and the largest sample. A sample past them is held at the row's edge. A sample
    outside the span is left out."""

    name: str
    t: tuple[float, ...]
    y: tuple[float, ...]
    low: float | None = None
    high: float | None = None

    def __post_init__(self) -> None:
        t, y = tuple(float(v) for v in self.t), tuple(float(v) for v in self.y)
        if len(t) != len(y):
            raise ValueError(f"a trace's t and y have the same length, got {len(t)} and {len(y)}")
        low = None if self.low is None else float(self.low)
        high = None if self.high is None else float(self.high)
        if not all(math.isfinite(v) for v in t + y + tuple(v for v in (low, high) if v is not None)):
            raise ValueError("a trace's t, y, low and high are finite numbers: one is nan or infinite")
        if low is not None and high is not None and not high > low:
            raise ValueError(f"a trace's high is above its low, got low {low:g} and high {high:g}")
        _set(self, t=t, y=y, low=low, high=high)

    def _svg(self, place: Place, r: int, span: tuple[float, float], text: Write) -> str:
        low = min(self.y, default=0.0) if self.low is None else self.low
        high = max(self.y, default=0.0) if self.high is None else self.high
        reach = high - low
        return _wave([place(t, r + LEVEL - 2.0 * LEVEL * ((min(max(v, low), high) - low) / reach if reach > 0 else 0.5))
                      for t, v in zip(self.t, self.y) if span[0] <= t <= span[1]], BLACK)


@dataclass(frozen=True)
class TimeMark:
    """A dashed vertical line at time ``t`` across all rows, with ``label`` above the top row."""

    t: float
    label: str = ""

    def __post_init__(self) -> None:
        _set(self, t=_finite(self.t, "a mark's time"), label=str(self.label))


Row = Clock | Bits | Bus | Trace
_ROWS: dict[str, type] = {kind.__name__: kind for kind in (Clock, Bits, Bus, Trace)}


def _ticks(t0: float, t1: float) -> list[float]:
    """Round times from ``t0`` to ``t1``, about ``MOST_TICKS`` at most: steps of 1, 2 or 5 times a power of ten."""

    raw = (t1 - t0) / MOST_TICKS
    step = 10.0 ** math.floor(math.log10(raw))
    step *= next(m for m in (1, 2, 5, 10) if m * step >= raw)
    return [k * step for k in range(math.ceil(t0 / step - 1e-9), math.floor(t1 / step + 1e-9) + 1)]


class Timing:
    """A timing diagram, drawn as vector at the inset's width. Each row is a :class:`Clock`, :class:`Bits`,
    :class:`Bus` or :class:`Trace`, its name in a left column. The time axis runs along the bottom over ``span``,
    ``(t0, t1)`` in ``unit``. Each :class:`TimeMark` is a dashed line across all rows.

    ``row_mm`` sets the row pitch (by default 2.4 text sizes). ``illustrative=True`` adds the note "illustrative timing,
    not measured". ``place(t, r)`` takes a time and a row index (see :meth:`row`)."""

    free_shape = False

    def __init__(self, rows: Iterable[Row], span: tuple[float, float], unit: str = "", marks: Iterable[TimeMark] = (),
                 row_mm: float | None = None, illustrative: bool = False):
        self.rows = tuple(rows)
        if not self.rows:
            raise ValueError("a timing needs at least one row")
        for row in self.rows:
            if not isinstance(row, (Clock, Bits, Bus, Trace)):
                raise TypeError(f"a timing row is a Clock, Bits, Bus or Trace, not {type(row).__name__}")
        names = [row.name for row in self.rows]
        twice = sorted({name for name in names if names.count(name) > 1})
        if twice:
            raise ValueError(f"each row needs its own name: {', '.join(map(repr, twice))} is used twice")
        t0, t1 = (float(value) for value in span)
        if not (math.isfinite(t0) and math.isfinite(t1) and t1 > t0):
            raise ValueError(f"the span runs from t0 to a later, finite t1, got {span!r}")
        self.span, self.unit, self.marks = (t0, t1), str(unit), tuple(marks)
        for mark in self.marks:
            if not t0 <= mark.t <= t1:
                raise ValueError(f"the mark at t = {mark.t:g} lies outside the span {t0:g} to {t1:g}")
        self.row_mm = None if row_mm is None else _positive(row_mm, "row_mm")
        self.illustrative = bool(illustrative)

    def row(self, name: str) -> int:
        """The index of the row ``name``, for ``place`` and ``inset.at``. An unknown name raises KeyError, which lists
        the names."""

        names = [row.name for row in self.rows]
        if name not in names:
            raise KeyError(f"no row {name!r}: the rows are {', '.join(map(str, names))}")
        return names.index(name)

    def fragment(self, width_mm: float, *, font_pt: float) -> Fragment:
        from optodraw.figure.page import FONT_FAMILY

        size = round(font_pt * PT_MM, 4)
        look = f'font-family="{FONT_FAMILY}" fill="{BLACK}"'

        def text(words: str, x: float, middle: float, anchor: str = "start", extra: str = "") -> str:
            return svg_text(words, size, x, round(middle + 0.35 * size, 4), anchor, look + extra)

        (t0, t1), last = self.span, len(self.rows) - 0.5          # last: the lower edge of the last row
        ticks = _ticks(t0, t1)
        labels = [f"{tick:g}" for tick in ticks]
        half = max(text_width(label, size) for label in labels) / 2.0
        axis = f"Time ({self.unit})" if self.unit else "Time"
        x0 = max(max(text_width(row.name, size) for row in self.rows), text_width(axis, size) + half) + PAD * size
        x1 = width_mm - half
        if not x1 > x0:
            raise ValueError(f"a timing {width_mm:g} mm wide leaves no room for the waveforms after the names: make "
                             "the inset wider")
        top = BAND * size if any(mark.label for mark in self.marks) else 0.0
        pitch = self.row_mm or ROW_PITCH * size
        scale = (x1 - x0) / (t1 - t0)
        shape = affine(scale, 0.0, x0 - scale * t0, 0.0, pitch, top + 0.5 * pitch)
        place = place_from(shape)
        axis_y = place(t0, last)[1]
        tick_y = axis_y + TICK * size
        label_y = tick_y + 0.6 * size                              # the middle of the tick labels

        body = []
        for mark in self.marks:                                     # first: the rows draw over them
            (x, y0), y1 = place(mark.t, -0.5), place(mark.t, last)[1]
            body.append(f'<line x1="{_num(x)}" y1="{_num(y0)}" x2="{_num(x)}" y2="{_num(y1)}" '
                        f'data-mark="{html.escape(mark.label)}" stroke="{GREY}" stroke-width="{MARK_MM}" '
                        f'stroke-dasharray="{DASH_MM}"/>')
        for r, row in enumerate(self.rows):
            body.append(f'<g data-row="{html.escape(row.name)}">{text(row.name, 0.0, place(t0, r)[1])}'
                        f'{row._svg(place, r, self.span, text)}</g>')
        lines = [(place(t0, last), place(t1, last))] + [(place(tick, last), (place(tick, last)[0], tick_y))
                                                          for tick in ticks]
        body.append(f'<path d="{"".join(_d(line) for line in lines)}" fill="none" stroke="{BLACK}" '
                    f'stroke-width="{AXIS_MM}"/>')
        body += [text(label, place(tick, last)[0], label_y, "middle", f' data-tick="{label}"')
                 for tick, label in zip(ticks, labels)]
        body.append(text(axis, 0.0, label_y))
        for mark in self.marks:
            if mark.label:
                # shortcut: two labels at close times overlap; give one of them no label
                wide = text_width(mark.label, size)
                x = min(max(place(mark.t, 0)[0], wide / 2.0), width_mm - wide / 2.0)
                body.append(text(mark.label, x, top - 0.65 * size, "middle"))
        height = label_y + 0.65 * size
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width_mm:.6g}mm" height="{height:.6g}mm" '
               f'viewBox="0 0 {width_mm:.6g} {height:.6g}">{"".join(body)}</svg>')
        notes = (ILLUSTRATIVE,) if self.illustrative else ()
        return Fragment(svg=svg, size_mm=(width_mm, height), place=place, notes=notes, map=shape)

    def to_record(self) -> dict[str, Any]:
        return {"kind": "Timing", "rows": [{"row": type(row).__name__, **asdict(row)} for row in self.rows],
                "span": list(self.span), "unit": self.unit, "marks": [asdict(mark) for mark in self.marks],
                "row_mm": self.row_mm, "illustrative": self.illustrative}

    @classmethod
    def _from_record(cls, record: dict[str, Any], base: Path) -> "Timing":
        from optodraw.figure.sources import _text, _value

        rows = record.get("rows")
        if not isinstance(rows, list) or not all(isinstance(row, dict) and row.get("row") in _ROWS for row in rows):
            raise ValueError(f"a Timing record's rows are records of {', '.join(_ROWS)}, got {rows!r}")
        try:
            built = [_ROWS[row["row"]](**{key: value for key, value in row.items() if key != "row"}) for row in rows]
            return cls(built, span=record["span"], unit=_text(record, "unit"),
                       marks=[TimeMark(**mark) for mark in record.get("marks", [])],
                       row_mm=_value(record, "row_mm", empty=True), illustrative=bool(record.get("illustrative")))
        except (KeyError, TypeError) as exc:
            raise ValueError(f"a Timing record does not fit its rows, span and marks: {exc}") from exc
