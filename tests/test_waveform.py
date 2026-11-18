"""Electrical waveforms and their first-order blocks, against the closed forms."""

from __future__ import annotations


import numpy as np
import pytest

from optodraw.animation_engine.waveform import (Waveform, feedback_tia, heater_power, hold, laser_power, lowpass,
                                                parse_value, photocurrent)


def test_feedback_tia_pole():
    assert feedback_tia(1e4, 0.2e-12)[1] == pytest.approx(79.577e6, rel=1e-4)
    assert feedback_tia(1e4, None) == (1e4, None)


def test_dac_refuses_a_code_out_of_range_and_a_coarse_grid():
    with pytest.raises(ValueError, match="0 to 255"):
        hold(Waveform(np.arange(2.0), np.array([0, 256]), "code"), 8, 1.0, np.arange(4) * 0.5)
    with pytest.raises(ValueError, match="2 ns is coarser than the code period 1 ns"):
        hold(Waveform(np.arange(3.0), np.array([0, 1, 2]), "code"), 8, 1.0, np.arange(2) * 2.0)


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
