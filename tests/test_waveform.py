"""Electrical waveforms and their first-order blocks, against the closed forms."""

from __future__ import annotations

import math

import numpy as np
import pytest

from optodraw.animation_engine.waveform import (Waveform, feedback_tia, heater_power, hold, laser_power, lowpass,
                                                parse_value, photocurrent, sample, transimpedance)


def test_feedback_tia_pole():
    assert feedback_tia(1e4, 0.2e-12)[1] == pytest.approx(79.577e6, rel=1e-4)
    assert feedback_tia(1e4, None) == (1e4, None)


def test_lowpass_step_is_exact():
    t = np.arange(400) * 0.1
    x = np.where(np.arange(400) >= 1, 1.0, 0.0)
    y = lowpass(Waveform(t, x, "V"), 100e6).values
    tau = 1e9 / (2 * math.pi * 100e6)                      # ns
    assert np.max(np.abs(y[1:] - (1 - np.exp(-(t[1:] - t[1]) / tau)))) < 1e-12
    assert y[0] == 0.0


def test_lowpass_sine_at_the_corner():
    t = np.arange(200 * 1000) * 0.01                       # 200 periods of 10 ns
    y = lowpass(Waveform(t, np.sin(2 * math.pi * 0.1 * t), "V"), 100e6).values
    last = y[-50 * 1000:]
    assert (last.max() - last.min()) / 2 == pytest.approx(1 / math.sqrt(2), abs=2e-3)


def test_lowpass_none_passes_the_waveform():
    w = Waveform(np.arange(3.0), np.ones(3), "V")
    assert lowpass(w, None) is w and lowpass(w, math.inf) is w


def test_adc_quantises_and_clips():
    for volts, code in ((0.5, 2048), (0.25, 1024), (1.2, 4095), (-0.1, 0)):
        w = Waveform(np.arange(11) * 100.0, np.full(11, volts), "V")
        assert np.all(sample(w, 12, 10e6, 1.0).values == code)
    span = Waveform(np.arange(1001) * 1.0, np.zeros(1001), "V")     # 0 to 1000 ns
    assert len(sample(span, 12, 10e6, 1.0).values) == 11            # every 100 ns, both ends
    assert len(sample(span, 12, 100e6, 1.0).values) == 101          # every 10 ns, both ends


def test_dac_holds_and_round_trips():
    codes = Waveform(np.array([0.0, 1.0, 2.0]), np.array([0, 128, 255]), "code")    # 1 GS/s
    v = hold(codes, 8, 1.0, np.arange(12) * 0.25)
    assert np.array_equal(v.values, np.repeat([0.0, 0.5, 255 / 256], 4))
    back = sample(v, 8, 1e9, 1.0)
    assert np.array_equal(back.values, codes.values) and np.allclose(back.t_ns, codes.t_ns)


def test_dac_refuses_a_code_out_of_range_and_a_coarse_grid():
    with pytest.raises(ValueError, match="0 to 255"):
        hold(Waveform(np.arange(2.0), np.array([0, 256]), "code"), 8, 1.0, np.arange(4) * 0.5)
    with pytest.raises(ValueError, match="2 ns is coarser than the code period 1 ns"):
        hold(Waveform(np.arange(3.0), np.array([0, 1, 2]), "code"), 8, 1.0, np.arange(2) * 2.0)


def test_photocurrent_tia_chain():
    p = Waveform(np.arange(5.0), np.full(5, 0.094), "mW")
    v = transimpedance(photocurrent(p, 1.0), 1e4)
    assert v.unit == "V" and np.allclose(v.values, 0.94, rtol=0, atol=1e-12)


def test_laser_power_threshold():
    i = Waveform(np.arange(3.0), np.array([0.005, 0.010, 0.030]), "A")
    p = laser_power(i, 0.01, 0.3)                          # 0.3 W/A above 10 mA
    assert p.unit == "mW" and np.allclose(p.values, [0.0, 0.0, 6.0], rtol=0, atol=1e-12)


def test_heater_power():
    p = heater_power(Waveform(np.arange(2.0), np.array([0.0, 2.0]), "V"), 1000.0)
    assert p.unit == "mW" and np.allclose(p.values, [0.0, 4.0], rtol=0, atol=1e-12)


def test_parse_value():
    assert parse_value("10 kΩ", "ohm") == pytest.approx(1e4, rel=1e-12)
    assert parse_value("0.2 pF", "F") == pytest.approx(2e-13, rel=1e-12)
    assert parse_value("4.7k", "ohm") == pytest.approx(4700, rel=1e-12)
    with pytest.raises(ValueError, match="'10 kg'"):
        parse_value("10 kg", "ohm")


def test_units_and_grid_are_checked():
    with pytest.raises(ValueError, match="photocurrent needs mW, got V"):
        photocurrent(Waveform(np.arange(3.0), np.zeros(3), "V"), 1.0)
    with pytest.raises(ValueError, match="not uniform"):
        lowpass(Waveform(np.array([0.0, 1.0, 3.0]), np.zeros(3), "V"), 1e6)
    with pytest.raises(ValueError, match="unit"):
        Waveform(np.arange(3.0), np.zeros(3), "W")
