"""Tests for Tier 3 polarization visualization overlays and QWP lab preset."""

from __future__ import annotations

import math

import pytest

from optodraw import (
    QuarterWavePlate,
    StokesVector,
    build_qwp_circular_lab,
    list_presets,
    stokes_to_ellipse,
    stokes_to_poincare_2d,
    trace_stokes_through,
)
from optodraw.core.polarization import wave_plate_mueller


class TestStokesToEllipse:
    def test_linear_horizontal_ellipse(self):
        stokes = StokesVector.linear_horizontal()
        ellipse = stokes_to_ellipse(stokes)

        assert ellipse["rx"] > ellipse["ry"]
        assert abs(float(ellipse["s3"])) < 0.05
        assert ellipse["label"] == "linear 0°"

    def test_circular_stokes_has_equal_axes(self):
        stokes = StokesVector(1.0, 0.0, 0.0, 1.0)
        ellipse = stokes_to_ellipse(stokes)

        assert float(ellipse["s3"]) == pytest.approx(1.0, abs=1e-6)
        assert ellipse["rx"] == pytest.approx(ellipse["ry"], rel=1e-3)
        assert ellipse["label"] == "circular"

    def test_poincare_projection(self):
        stokes = StokesVector(1.0, 0.6, 0.2, 0.7)
        s1, s2 = stokes_to_poincare_2d(stokes)
        assert s1 == pytest.approx(0.6, rel=1e-6)
        assert s2 == pytest.approx(0.2, rel=1e-6)


class TestSvgPolarizationOverlay:
    def test_render_with_overlay_smoke(self, tmp_path):
        scene = build_qwp_circular_lab()
        out = tmp_path / "qwp_overlay.svg"
        scene.render_svg(out.as_posix(), show_polarization_overlay=True)
        svg = out.read_text()
        assert "<ellipse" in svg.lower() or "ellipse" in svg.lower()
        assert "QWP" in svg or "633" in svg


class TestQWPCircularLabPreset:
    def test_preset_registered(self):
        assert "qwp_circular_lab" in list_presets()

    def test_preset_builds_scene(self):
        scene = build_qwp_circular_lab()
        types = {node.component_type for node in scene.walk()}
        assert {"Laser", "Polarizer", "QuarterWavePlate", "Photodiode"}.issubset(types)   # Schaefer 2007, Fig. 3

    def test_qwp_produces_circular_state(self):
        pol = StokesVector.linear_horizontal()
        qwp = QuarterWavePlate(fast_axis_angle=45.0, design_wavelength_nm=633.0)
        result = trace_stokes_through([qwp], pol, wavelength_nm=633.0)
        assert abs(result.stokes.S3) == pytest.approx(result.stokes.S0, rel=1e-3)
        assert abs(result.stokes.S1) < 0.05 * result.stokes.S0
        assert abs(result.stokes.S2) < 0.05 * result.stokes.S0


class TestWavelengthRetardanceScaling:
    def test_off_design_wavelength_changes_qwp_stokes(self):
        incoming = StokesVector.linear_horizontal()
        qwp = QuarterWavePlate(fast_axis_angle=45.0, design_wavelength_nm=633.0)

        at_design = trace_stokes_through([qwp], incoming, wavelength_nm=633.0).stokes
        off_design = trace_stokes_through([qwp], incoming, wavelength_nm=800.0).stokes

        assert abs(at_design.S3) > 0.8 * at_design.S0
        assert abs(off_design.S3) < abs(at_design.S3)
        assert off_design.S3 != pytest.approx(at_design.S3, rel=1e-3)

    def test_wave_plate_mueller_wavelength_scaling(self):
        m_design = wave_plate_mueller(45.0, math.pi / 2.0, wavelength_nm=633.0, design_wavelength_nm=633.0)
        m_off = wave_plate_mueller(45.0, math.pi / 2.0, wavelength_nm=800.0, design_wavelength_nm=633.0)
        stokes = StokesVector.linear_horizontal()
        assert (m_off @ stokes).S3 != pytest.approx((m_design @ stokes).S3, rel=1e-3)
