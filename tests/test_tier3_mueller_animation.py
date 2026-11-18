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
    animate_polarization,
    jones_to_mueller,
    jones_to_stokes,
    polarizer_mueller,
    stokes_to_jones,
    trace_stokes_through,
    wave_plate_mueller,
)
from optodraw.core.polarization import JonesVector, polarizer_matrix


class TestStokesMuellerCore:
    def test_unpolarized_through_polarizer_becomes_linear(self):
        pol = Polarizer(axis_angle=0.0, extinction_ratio=1e12)
        result = trace_stokes_through([pol], stokes_in=None, unpolarized=True)

        assert result.stokes.S0 == pytest.approx(0.5, rel=1e-6)
        assert result.stokes.S1 == pytest.approx(0.5, rel=1e-6)
        assert result.stokes.S2 == pytest.approx(0.0, abs=1e-5)
        assert result.stokes.S3 == pytest.approx(0.0, abs=1e-5)

    def test_hwp_rotates_stokes_on_poincare_sphere(self):
        incoming = StokesVector.linear_horizontal()
        hwp = HalfWavePlate(fast_axis_angle=45.0)
        result = trace_stokes_through([hwp], incoming)

        assert result.stokes.S1 == pytest.approx(-incoming.S1, rel=1e-5)
        assert abs(result.stokes.S2 - incoming.S2) > 0.1 or abs(result.stokes.S1 - incoming.S1) > 0.1

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
    def test_animate_polarization_builds_timeline(self):
        scene = Scene()
        pol = scene.add(Polarizer(axis_angle=0.0, extinction_ratio=1e12))
        hwp = scene.add(HalfWavePlate(fast_axis_angle=45.0))

        tl = animate_polarization(scene, [pol, hwp], unpolarized=True)
        pol_steps = [step for step in tl._steps if step.kind == "polarization"]
        assert len(pol_steps) >= 2
        assert all(step.stokes is not None for step in pol_steps)

    def test_scene_animate_polarization_convenience(self):
        scene = Scene()
        pol = scene.add(Polarizer())
        tl = scene.animate_polarization([pol], unpolarized=True)
        assert len(tl._steps) >= 1

    def test_polarization_timeline_frame_states(self):
        scene = Scene()
        pol = scene.add(Polarizer())
        hwp = scene.add(HalfWavePlate(fast_axis_angle=45.0))
        tl = scene.animate_polarization([pol, hwp], unpolarized=True)
        states = tl._to_frame_states()
        assert len(states) >= 3

    def test_jones_to_mueller_matches_jones_trace(self):
        jones_result = JonesVector.linear(45.0)
        j_out = polarizer_matrix(0.0, 120.0) @ jones_result
        m_out = jones_to_mueller(polarizer_matrix(0.0, 120.0)) @ jones_to_stokes(jones_result)
        assert m_out.S0 == pytest.approx(j_out.stokes()[0], rel=1e-5)
