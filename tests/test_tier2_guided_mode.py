"""Tests for Tier 2 guided-mode propagation stub and on-chip metadata."""

from __future__ import annotations

import math

import pytest

from optodraw import (
    MMI1x2,
    MicroringResonator,
    Scene,
    Waveguide,
    trace_guided_path,
    validate_coupler_transition,
)
from optodraw.components.onchip.couplers import VerticalGratingCoupler
from optodraw.components.onchip.io import OnChipPhotodetector
from optodraw.components.onchip.splitters import DirectionalCoupler
from optodraw.core.guided import SILICON_STRIP_NEFF_STUB


class TestWaveguideEffectiveIndex:
    def test_waveguide_effective_index_constructor_and_metadata(self):
        waveguide = Waveguide(length=12.0, effective_index=2.8)
        metadata = waveguide.physics_metadata()

        assert waveguide.effective_index == pytest.approx(2.8)
        assert metadata["effective_index"] == pytest.approx(2.8)

    def test_waveguide_effective_index_defaults_to_none(self):
        waveguide = Waveguide(length=10.0)
        assert waveguide.effective_index is None
        assert waveguide.physics_metadata()["effective_index"] is None


class TestTraceGuidedPath:
    def test_trace_guided_path_gc_wg_pd_chain(self):
        scene = Scene(platform="on_chip")
        gc = scene.add(VerticalGratingCoupler(center=(-60, 0)))
        wg = scene.add(Waveguide(center=(0, 0), length=40.0))
        pd = scene.add(OnChipPhotodetector(center=(60, 0)))
        route1 = scene.route((gc, "o1"), (wg, "o1"), path_type="straight")
        route2 = scene.route((wg, "o2"), (pd, "o1"), path_type="straight")

        result = scene.trace_guided_path([gc, route1, wg, route2, pd], wavelength_nm=1550.0)

        assert result.path_length_um > wg.length
        assert result.effective_index == pytest.approx(SILICON_STRIP_NEFF_STUB)
        assert result.phase_rad == pytest.approx(
            2.0 * math.pi * SILICON_STRIP_NEFF_STUB * result.path_length_um / 1.55,
            rel=1e-6,
        )
        assert result.loss_db == pytest.approx(0.0)

    def test_trace_guided_path_uses_waveguide_effective_index(self):
        wg = Waveguide(length=20.0, effective_index=2.6)
        result = trace_guided_path([wg], wavelength_nm=1550.0)
        assert result.effective_index == pytest.approx(2.6)

    def test_trace_guided_path_accumulates_phase_per_segment(self):
        wg_a = Waveguide(length=10.0, effective_index=2.0)
        wg_b = Waveguide(length=10.0, effective_index=3.0)
        result = trace_guided_path([wg_a, wg_b], wavelength_nm=1550.0)
        assert result.phase_rad == pytest.approx(
            2.0 * math.pi * (2.0 * 10.0 + 3.0 * 10.0) / 1.55, rel=1e-6
        )

    def test_trace_guided_path_phase_is_order_independent(self):
        wg_a = Waveguide(length=10.0, effective_index=2.0)
        wg_b = Waveguide(length=10.0, effective_index=3.0)
        forward = trace_guided_path([wg_a, wg_b], wavelength_nm=1550.0, group_index=4.0)
        backward = trace_guided_path([wg_b, wg_a], wavelength_nm=1550.0, group_index=4.0)
        assert forward.phase_rad == pytest.approx(backward.phase_rad)
        assert forward.group_delay_ps == pytest.approx(backward.group_delay_ps)

    def test_trace_guided_path_loss_budget_not_exceeded(self):
        wg = Waveguide(length=10.0)
        result = trace_guided_path(
            [wg],
            loss_db_per_um=0.001,
            loss_budget_db=0.05,
        )
        assert result.loss_db == pytest.approx(0.01)
        assert result.loss_budget_exceeded is False


class TestOnChipSplitterAndRingMetadata:
    def test_mmi_physics_metadata_keys(self):
        mmi = MMI1x2()
        metadata = mmi.physics_metadata()

        assert metadata["domain"] == "on_chip"
        assert metadata["component"] == "mmi"
        assert metadata["split_ratio"] == pytest.approx(0.5)
        assert metadata["input_port_count"] == 1
        assert metadata["output_port_count"] == 2
        assert metadata["port_count"] == 3

    def test_microring_physics_metadata_keys(self):
        ring = MicroringResonator(ring_radius=8.0, gap=0.2)
        metadata = ring.physics_metadata()

        assert metadata["ring_radius"] == pytest.approx(8.0)
        assert metadata["gap"] == pytest.approx(0.2)
        assert metadata["fsr_nm"] is not None
        assert metadata["Q"] is None

    def test_directional_coupler_physics_metadata_keys(self):
        dc = DirectionalCoupler(coupling_length=6.0)
        metadata = dc.physics_metadata()

        assert metadata["coupling_length"] == pytest.approx(6.0)
        assert metadata["coupling_ratio"] == pytest.approx(0.5)


class TestCouplerTransitionValidation:
    def test_default_pitch_is_radiative_at_1550(self):
        # phase matching n_clad*sin(theta) = n_eff - lambda/pitch must accept the
        # stock coupler (the free-space grating equation wrongly called it evanescent)
        coupler = VerticalGratingCoupler()
        assert validate_coupler_transition(coupler, wavelength_nm=1550.0) == []

    def test_validate_coupler_transition_warns_on_mismatch(self):
        coupler = VerticalGratingCoupler(coupling_angle_deg=90.0)
        warnings = validate_coupler_transition(coupler, wavelength_nm=1550.0)

        assert len(warnings) == 1
        assert "coupling_angle_deg" in warnings[0]

    def test_validate_coupler_transition_flags_evanescent_pitch(self):
        coupler = VerticalGratingCoupler(tooth_pitch=0.30)
        warnings = validate_coupler_transition(coupler, wavelength_nm=1550.0)

        assert len(warnings) == 1
        assert "evanescent" in warnings[0]

    def test_scene_validate_physics_coupling_mode(self):
        scene = Scene()
        scene.add(VerticalGratingCoupler(coupling_angle_deg=90.0))

        warnings = scene.validate_physics(mode="coupling", wavelength_nm=1550.0)

        assert len(warnings) == 1
        assert "coupling_angle_deg" in warnings[0]
