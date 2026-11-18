"""Electrical signals: sampled waveforms on one uniform time grid in ns, and the blocks that map one to the next.

The optical table runs in ps; these run in ns. Units: optical power mW, current A, voltage V, converter values
integer codes. A bandwidth is a first-order pole; there is no noise (model).
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

import numpy as np

UNITS = ("mW", "A", "V", "code")


@dataclass(frozen=True, eq=False)
class Waveform:
    """``values[k]`` at ``t_ns[k]``, in ``unit`` (one of ``UNITS``)."""

    t_ns: np.ndarray
    values: np.ndarray
    unit: str

    def __post_init__(self):
        if self.unit not in UNITS:
            raise ValueError(f"a waveform unit is one of {', '.join(UNITS)}, not {self.unit!r}")
        t = np.asarray(self.t_ns, dtype=float)
        values = np.asarray(self.values, dtype=np.int64 if self.unit == "code" else float)
        if t.ndim != 1 or values.shape != t.shape:
            raise ValueError(f"a waveform needs one value per time: {values.shape} values, {t.shape} times")
        object.__setattr__(self, "t_ns", t)
        object.__setattr__(self, "values", values)

    @property
    def step_ns(self) -> float:
        """The step of the time grid; a grid that is not uniform to 1e-9 relative is a ``ValueError``."""

        steps = np.diff(self.t_ns)
        if steps.size == 0:
            raise ValueError("a waveform with one time has no step")
        step = float((self.t_ns[-1] - self.t_ns[0]) / steps.size)
        if step <= 0 or float(np.max(np.abs(steps - step))) > 1e-9 * step:
            raise ValueError(f"the time grid is not uniform: steps from {steps.min():g} ns to {steps.max():g} ns")
        return step


def _needs(w: Waveform, unit: str, block: str) -> None:
    if w.unit != unit:
        raise ValueError(f"{block} needs {unit}, got {w.unit}")


def _latest(t_from: np.ndarray, t_at: np.ndarray) -> np.ndarray:
    """For each time of ``t_at``, the index of the latest time of ``t_from`` at or before it (the first, before the
    first). A time a billionth of a step after a grid time counts as on it: float round-off moves no code."""

    tolerance = 1e-9 * (t_from[1] - t_from[0]) if len(t_from) > 1 else 0.0
    return np.clip(np.searchsorted(t_from, np.asarray(t_at) + tolerance, side="right") - 1, 0, len(t_from) - 1)


def lowpass(w: Waveform, bandwidth_hz: float | None) -> Waveform:
    """A first-order pole at ``bandwidth_hz``; None or inf passes ``w``. Exact for an input held over each step: the
    output is settled at the first value before ``t_ns[0]``."""

    if bandwidth_hz is None or math.isinf(float(bandwidth_hz)) or len(w.t_ns) < 2:
        return w
    if not float(bandwidth_hz) > 0:
        raise ValueError(f"a bandwidth is above 0 Hz, not {bandwidth_hz}")
    a = math.exp(-2.0 * math.pi * float(bandwidth_hz) * w.step_ns * 1e-9)
    x = w.values.astype(float)
    y = np.empty_like(x)
    y[0] = x[0]
    for k in range(1, len(x)):
        y[k] = a * y[k - 1] + (1.0 - a) * x[k - 1]
    return Waveform(w.t_ns, y, w.unit)


def photocurrent(power: Waveform, responsivity_a_per_w: float, dark_current_a: float = 0.0,
                 bandwidth_hz: float | None = None) -> Waveform:
    """Optical power (mW) to current (A): ``I = R P + I_dark``, then the pole."""

    _needs(power, "mW", "photocurrent")
    current = float(responsivity_a_per_w) * power.values * 1e-3 + float(dark_current_a)
    return lowpass(Waveform(power.t_ns, current, "A"), bandwidth_hz)


def transimpedance(current: Waveform, gain_ohm: float, bandwidth_hz: float | None = None) -> Waveform:
    """Current (A) to voltage (V): ``V = gain I``, then the pole. The sign of an inverting stage is not modelled: the
    gain is the transimpedance a datasheet quotes."""

    _needs(current, "A", "transimpedance")
    return lowpass(Waveform(current.t_ns, float(gain_ohm) * current.values, "V"), bandwidth_hz)


def amplify(v: Waveform, gain: float, bandwidth_hz: float | None = None) -> Waveform:
    """Voltage (V) to voltage (V): ``gain`` times, then the pole."""

    _needs(v, "V", "amplify")
    return lowpass(Waveform(v.t_ns, float(gain) * v.values, "V"), bandwidth_hz)


def feedback_tia(rf_ohm: float, cf_farad: float | None) -> tuple[float, float | None]:
    """An op amp with ``Rf`` and ``Cf`` in its feedback: the gain ``Rf`` and the pole ``1 / (2 pi Rf Cf)`` (None with
    no capacitor)."""

    if not cf_farad:
        return float(rf_ohm), None
    return float(rf_ohm), 1.0 / (2.0 * math.pi * float(rf_ohm) * float(cf_farad))


def _instants(t_ns: np.ndarray, rate_hz: float) -> np.ndarray:
    """``t0 + k / rate`` within the span of ``t_ns``."""

    if not float(rate_hz) > 0:
        raise ValueError(f"a sample rate is above 0 Hz, not {rate_hz}")
    period = 1e9 / float(rate_hz)
    count = int(math.floor((t_ns[-1] - t_ns[0]) / period + 1e-9)) + 1
    return t_ns[0] + period * np.arange(count)


def sample(v: Waveform, bits: int, rate_hz: float, full_scale_v: float) -> Waveform:
    """An ADC: voltage (V) to codes at ``t0 + k / rate`` within the span, the voltage at each instant by linear
    interpolation. Unipolar: ``code = clip(floor(V / LSB), 0, 2^N - 1)``, ``LSB = full_scale_v / 2^N``. A voltage a
    billionth of an LSB under a code edge counts as on it (float round-off)."""

    _needs(v, "V", "sample")
    levels = 2 ** int(bits)
    at = _instants(v.t_ns, rate_hz)
    codes = np.floor(np.interp(at, v.t_ns, v.values) / (float(full_scale_v) / levels) + 1e-9)
    return Waveform(at, np.clip(codes, 0, levels - 1), "code")


def clock(codes: Waveform, rate_hz: float, t_ns: np.ndarray) -> Waveform:
    """A converter's clock: the latest code at or before each tick ``t0 + k / rate`` within the span of ``t_ns``."""

    _needs(codes, "code", "clock")
    at = _instants(np.asarray(t_ns, dtype=float), rate_hz)
    return Waveform(at, codes.values[_latest(codes.t_ns, at)], "code")


def hold(codes: Waveform, bits: int, full_scale_v: float, t_ns: np.ndarray) -> Waveform:
    """A DAC: codes to voltage (V) on ``t_ns``, ``V = code x LSB``: the latest code at or before each time, the first
    code before the first instant. A code outside ``0 .. 2^N - 1`` and a grid step longer than the code period are a
    ``ValueError``."""

    _needs(codes, "code", "hold")
    levels = 2 ** int(bits)
    if codes.values.size and (codes.values.min() < 0 or codes.values.max() > levels - 1):
        raise ValueError(f"{int(bits)}-bit codes run 0 to {levels - 1}; got {codes.values.min()} to {codes.values.max()}")
    t = np.asarray(t_ns, dtype=float)
    if len(t) > 1 and len(codes.t_ns) > 1:
        step, period = Waveform(t, np.zeros(len(t)), "V").step_ns, codes.step_ns
        if step > period * (1 + 1e-9):
            raise ValueError(f"the time grid step {step:g} ns is coarser than the code period {period:g} ns")
    return Waveform(t, codes.values[_latest(codes.t_ns, t)] * (float(full_scale_v) / levels), "V")


def laser_power(current: Waveform, threshold_a: float, slope_w_per_a: float) -> Waveform:
    """Drive current (A) to optical power (mW): ``1e3 slope max(I - I_th, 0)``."""

    _needs(current, "A", "laser_power")
    return Waveform(current.t_ns, 1e3 * float(slope_w_per_a) * np.maximum(current.values - float(threshold_a), 0.0), "mW")


def heater_power(v: Waveform, resistance_ohm: float) -> Waveform:
    """Heater voltage (V) to heater power (mW): ``1e3 V^2 / R``."""

    _needs(v, "V", "heater_power")
    return Waveform(v.t_ns, 1e3 * v.values ** 2 / float(resistance_ohm), "mW")


_PREFIXES = {"": 1.0, "f": 1e-15, "p": 1e-12, "n": 1e-9, "u": 1e-6, "µ": 1e-6, "μ": 1e-6, "m": 1e-3,
             "k": 1e3, "M": 1e6, "G": 1e9}                     # micro as the micro sign and as the Greek mu
_SUFFIXES = {"ohm": ("Ω", "Ω", "ohm", "R", ""), "F": ("F",)}   # omega as the Greek letter and the ohm sign
_VALUE = re.compile(r"\s*([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)\s*([fpnuµμmkMG]?)\s*(\S*)\s*")


def parse_value(text: str, unit: str) -> float:
    """A drawn part's value as a number: ``"10 kΩ"`` -> 1e4, ``"0.2 pF"`` -> 2e-13, ``"4.7k"`` -> 4700. ``unit`` is
    ``"ohm"`` (Ω, ohm, R or nothing after the number) or ``"F"``."""

    if unit not in _SUFFIXES:
        raise ValueError(f"parse_value reads ohm or F, not {unit!r}")
    found = _VALUE.fullmatch(str(text))
    if found is None or found.group(3) not in _SUFFIXES[unit]:
        raise ValueError(f"cannot read {text!r} as a value in {unit}")
    return float(found.group(1)) * _PREFIXES[found.group(2)]
