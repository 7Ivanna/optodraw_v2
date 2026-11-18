"""Tests for Tier 2 grating diffraction stub and on-chip physics metadata."""

from __future__ import annotations


import pytest

from optodraw import Grating, trace_ray


class TestGratingDiffractionStub:


    def test_trace_ray_grating_without_pitch_is_pass_through(self):
        grating = Grating(center=(0, 0), angle=0, pitch=1.0)
        grating.pitch = 0.0  # type: ignore[assignment]

        result = trace_ray(
            start=(-10, 0),
            direction_deg=0.0,
            optics=[grating],
            exit_length=5.0,
            wavelength_nm=633.0,
        )

        assert result.direction_deg == pytest.approx(0.0)


