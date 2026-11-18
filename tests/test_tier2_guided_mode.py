"""Tests for Tier 2 guided-mode propagation stub and on-chip metadata."""

from __future__ import annotations



from optodraw import (
    Scene,
    validate_coupler_transition,
)
from optodraw.components.onchip.couplers import VerticalGratingCoupler


class TestCouplerTransitionValidation:


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
