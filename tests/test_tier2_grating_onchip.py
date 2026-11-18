"""Tests for Tier 2 grating diffraction stub and on-chip physics metadata."""

from __future__ import annotations

import math

import pytest

from optodraw import Block, Grating, Lens, Scene, Waveguide, grating_diffraction_angle_deg, trace_ray
from optodraw.components.onchip.couplers import VerticalGratingCoupler


class TestGratingDiffractionStub:
    def test_grating_diffraction_angle_textbook_value(self):
        pitch = 1.0
        wavelength_nm = 633.0
        expected = math.degrees(math.asin(0.633))

        angle = grating_diffraction_angle_deg(pitch, wavelength_nm)

        assert angle == pytest.approx(expected, abs=0.1)
        assert angle == pytest.approx(39.29, abs=0.1)

    def test_trace_ray_grating_applies_first_order_deflection(self):
        grating = Grating(center=(0, 0), angle=0, pitch=1.0)

        result = trace_ray(
            start=(-10, 0),
            direction_deg=0.0,
            optics=[grating],
            exit_length=5.0,
            wavelength_nm=633.0,
        )

        assert result.direction_deg == pytest.approx(39.29, abs=0.1)

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


class TestOnChipPhysicsMetadata:
    def test_waveguide_physics_metadata_keys(self):
        waveguide = Waveguide(length=10.0, width=0.5)
        metadata = waveguide.physics_metadata()

        assert metadata["domain"] == "on_chip"
        assert metadata["component"] == "waveguide"
        assert metadata["width"] == pytest.approx(0.5)
        assert metadata["length"] == pytest.approx(10.0)
        assert metadata["mode"] == "guided"
        assert "effective_index" in metadata

    def test_vertical_grating_coupler_physics_metadata_keys(self):
        coupler = VerticalGratingCoupler()
        metadata = coupler.physics_metadata()

        assert metadata["domain"] == "on_chip"
        assert metadata["component"] == "vertical_grating_coupler"
        assert metadata["coupler_kind"] == "vertical"
        assert metadata["tooth_pitch"] == pytest.approx(coupler.tooth_pitch)
        assert metadata["wavelength_range_nm"] == (1260, 1360)
        assert "coupling_angle_deg" in metadata


class TestMixedSceneValidation:
    def test_scene_validate_physics_mixed_free_space_and_on_chip(self):
        scene = Scene()
        scene.add(Waveguide(length=10.0))
        scene.add(Lens(focal_length=20.0))
        scene.add(Block(center=(0, 0)))

        warnings = scene.validate_physics(mode="mixed")

        assert any("Waveguide" in message and "paraxial" in message for message in warnings)
        assert any("Block" in message and "visual-only" in message for message in warnings)

    def test_scene_validate_physics_ray_mode_warns_visual_only(self):
        scene = Scene()
        scene.add(Block(center=(0, 0)))

        warnings = scene.validate_physics(mode="ray")

        assert len(warnings) == 1
        assert "Block" in warnings[0]
        assert "visual-only" in warnings[0]
