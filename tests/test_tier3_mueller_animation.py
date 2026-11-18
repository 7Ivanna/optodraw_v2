"""Tests for Tier 3 Mueller/Stokes polarization and animation wiring."""

from __future__ import annotations

import math

import pytest

from optodraw import (
    HalfWavePlate,
    PBS,
    Polarizer,
    Scene,
    StokesVector,
    jones_to_stokes,
    polarizer_mueller,
    stokes_to_jones,
    trace_stokes_through,
    wave_plate_mueller,
)
from optodraw.core.polarization import JonesVector


class TestStokesMuellerCore:


    def test_jones_stokes_round_trip_fully_polarized(self):
        jones = JonesVector.linear(30.0)
        stokes = jones_to_stokes(jones)
        roundtrip = stokes_to_jones(stokes)
        assert roundtrip.intensity() == pytest.approx(jones.intensity(), rel=1e-5)

    def test_mueller_factories_compose(self):
        m_pol = polarizer_mueller(0.0, 120.0)
        m_hwp = wave_plate_mueller(45.0, math.pi)
        stokes = StokesVector.linear_horizontal()
        chained = m_hwp @ m_pol @ stokes
        assert chained.S1 == pytest.approx(-stokes.S1, rel=1e-3)
        assert chained.S2 == pytest.approx(0.0, abs=1e-5)


class TestPBSDualOutput:
    def test_pbs_dual_output_powers_sum_to_one(self):
        pbs = PBS(split_ratio=(0.5, 0.5))
        result = trace_stokes_through([pbs], stokes_in=None, unpolarized=True)

        assert result.dual_outputs is not None
        p_frac = result.dual_outputs["p"]["power_fraction"]
        s_frac = result.dual_outputs["s"]["power_fraction"]
        assert p_frac + s_frac == pytest.approx(1.0, rel=1e-6)

    def test_pbs_routing_keys(self):
        pbs = PBS(split_ratio=(0.5, 0.5))
        result = trace_stokes_through([pbs], StokesVector.linear_horizontal())

        assert "transmitted" in result.dual_outputs
        assert "reflected" in result.dual_outputs
        assert result.dual_outputs["transmitted"]["power_fraction"] == pytest.approx(1.0, rel=1e-6)
        assert result.dual_outputs["reflected"]["power_fraction"] == pytest.approx(0.0, abs=1e-6)


class TestAnimatePolarization:


    def test_polarization_timeline_frame_states(self):
        scene = Scene()
        pol = scene.add(Polarizer())
        hwp = scene.add(HalfWavePlate(fast_axis_angle=45.0))
        tl = scene.animate_polarization([pol, hwp], unpolarized=True)
        states = tl._to_frame_states()
        assert len(states) >= 3

