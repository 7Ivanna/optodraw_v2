"""Tests for Tier 3 Jones-matrix polarization stubs."""

from __future__ import annotations

import math

import pytest

from optodraw import (
    HalfWavePlate,
    JonesMatrix,
    JonesVector,
    Polarizer,
    Scene,
    half_wave_plate,
    pbs_matrix,
    polarizer_matrix,
    trace_jones_through,
)
from optodraw.registry import component_registry


class TestJonesFactoryMatrices:
    def test_linear_polarizer_projects_to_axis(self):
        incoming = JonesVector.linear(45.0)
        matrix = polarizer_matrix(axis_angle_deg=0.0, extinction_ratio_db=120.0)
        outgoing = matrix @ incoming

        assert abs(outgoing.Ey) < 1e-6
        assert outgoing.Ex != 0.0
        assert outgoing.intensity() == pytest.approx(incoming.intensity() * 0.5, rel=1e-6)

    def test_hwp_rotates_linear_90_deg_when_axis_45(self):
        incoming = JonesVector.linear(0.0)
        matrix = half_wave_plate(fast_axis_deg=45.0)
        outgoing = matrix @ incoming

        assert abs(outgoing.Ex) < 1e-9
        assert abs(outgoing.Ey) == pytest.approx(1.0)

    def test_pbs_splits_diagonal_power(self):
        incoming = JonesVector.linear(45.0)
        transmitted = pbs_matrix() @ incoming
        reflected = JonesMatrix(0.0, 0.0, 0.0, 1.0) @ incoming

        assert transmitted.intensity() == pytest.approx(0.5, rel=1e-6)
        assert reflected.intensity() == pytest.approx(0.5, rel=1e-6)
        assert transmitted.intensity() + reflected.intensity() == pytest.approx(
            incoming.intensity(), rel=1e-6
        )


class TestTraceJonesThrough:
    def test_polarizer_hwp_chain(self):
        pol = Polarizer(axis_angle=0.0, extinction_ratio=1e12)
        hwp = HalfWavePlate(fast_axis_angle=45.0)
        result = trace_jones_through([pol, hwp], JonesVector.linear(45.0))

        assert result.components_applied == ("Polarizer", "HalfWavePlate")
        assert abs(result.jones.Ex) < 1e-6
        assert abs(result.jones.Ey) == pytest.approx(math.sqrt(0.5), rel=1e-6)

    def test_jones_tracing_refuses_unpolarized_light(self):
        """A Jones vector is a fully polarized state; it cannot hold unpolarized light.

        The old code picked a polarized stand-in and returned a number. It now
        says so and names the function that can do the job.
        """
        pol = Polarizer(axis_angle=0.0, extinction_ratio=1e12)
        with pytest.raises(ValueError, match="trace_stokes_through"):
            trace_jones_through([pol], jones_in=None, unpolarized=True)

    def test_unpolarized_through_polarizer_becomes_linear(self):
        """Stokes tracing: an ideal polarizer passes half the power, fully polarized along its axis."""
        from optodraw.core.polarization import trace_stokes_through

        pol = Polarizer(axis_angle=0.0, extinction_ratio=1e12)
        stokes = trace_stokes_through([pol], unpolarized=True).stokes

        assert stokes.S0 == pytest.approx(0.5, abs=1e-6)
        assert stokes.S1 == pytest.approx(0.5, abs=1e-6)      # S1 = S0: linear, along the axis
        assert stokes.S2 == pytest.approx(0.0, abs=1e-6)
        assert stokes.S3 == pytest.approx(0.0, abs=1e-6)


class TestScenePolarization:
    def test_scene_trace_polarization(self):
        scene = Scene()
        pol = scene.add(Polarizer(axis_angle=0.0, extinction_ratio=1e12))
        hwp = scene.add(HalfWavePlate(fast_axis_angle=45.0))
        result = scene.trace_polarization([pol, hwp], jones_in=JonesVector.linear(45.0))

        assert abs(result.jones.Ey) == pytest.approx(math.sqrt(0.5), rel=1e-6)

    def test_validate_physics_polarization_mode(self):
        scene = Scene()
        scene.add(Polarizer())
        warnings = scene.validate_physics("polarization")
        assert warnings == []


class TestRegistryPolarizationModes:
    def test_polarization_components_declare_mode(self):
        registry = component_registry()
        for name in (
            "Polarizer",
            "Analyzer",
            "WavePlate",
            "HalfWavePlate",
            "QuarterWavePlate",
            "PBS",
        ):
            assert "polarization" in registry[name].physics_modes
