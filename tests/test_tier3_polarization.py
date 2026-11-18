"""Tests for Tier 3 Jones-matrix polarization stubs."""

from __future__ import annotations

import math

import pytest

from optodraw import (
    HalfWavePlate,
    JonesVector,
    Polarizer,
    Scene,
)


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


