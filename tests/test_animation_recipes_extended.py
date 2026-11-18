"""Tests for the extended teaching animation recipes (PR12 track).

Covers:

- ``animate_grating_coupler_in_out``
- ``animate_fiber_alignment``
- ``animate_directional_coupler_power_transfer``
- ``animate_mmi_split_recombine``
- ``animate_photodetector_absorption``
- ``animate_pn_modulation_phase_shift``
- 3D pulse rendering polish (pulse_width, color-by-wavelength,
  opacity envelope, trail/fade rendering hooks on ``wave_travel``)
"""

from __future__ import annotations

import pytest

from optodraw import (
    DirectionalCoupler,
    MMI1x2,
    MMI2x2,
    MZM,
    MicroringResonator,
    OnChipPhotodetector,
    Scene,
    VerticalGratingCoupler,
    animate_directional_coupler_power_transfer,
    animate_fiber_alignment,
    animate_grating_coupler_in_out,
    animate_mmi_split_recombine,
    animate_photodetector_absorption,
    animate_pn_modulation_phase_shift,
    build_detector_readout_chain,
)


def _step_kinds(tl) -> list[str]:
    return [step.kind for step in tl._steps]


# ---------------------------------------------------------------------------
# 3D pulse rendering polish — wave_travel hooks
# ---------------------------------------------------------------------------


class TestWaveTravelPulseHooks:
    def _ring_scene(self):
        chip = Scene(platform="on_chip", title="hook scene")
        gc = chip.add(VerticalGratingCoupler(center=(-80, 0), label="GC"))
        ring = chip.add(MicroringResonator(center=(0, -55), label="Ring"))
        route = chip.route((gc, "o1"), (ring, "o1"), kind="waveguide")
        return chip, route


    def test_pulse_width_must_be_in_unit_interval(self):
        chip, route = self._ring_scene()
        tl = chip.timeline()
        with pytest.raises(ValueError):
            tl.wave_travel(route, pulse_width=0.0)
        with pytest.raises(ValueError):
            tl.wave_travel(route, pulse_width=1.5)
        with pytest.raises(ValueError):
            tl.wave_travel(route, pulse_width=-0.1)


    def test_explicit_pulse_color_wins_over_wavelength(self):
        chip, route = self._ring_scene()
        tl = chip.timeline().wave_travel(
            route, steps=4, wavelength_nm=633.0, pulse_color="#abcdef"
        )
        states = [s for s in tl._to_frame_states() if s["traveling_waves"]]
        assert all(state["wave_colors"][id(route)] == "#abcdef" for state in states)


    def test_invalid_opacity_envelope_raises(self):
        chip, route = self._ring_scene()
        with pytest.raises(ValueError):
            chip.timeline().wave_travel(route, opacity_envelope="square")

    def test_fade_envelope_decreases_opacity_over_time(self):
        chip, route = self._ring_scene()
        tl = chip.timeline().wave_travel(route, steps=5, fade=True)
        opacities = [
            state["wave_opacities"][id(route)]
            for state in tl._to_frame_states()
            if state["traveling_waves"]
        ]
        assert opacities[0] > opacities[-1]
        assert opacities[-1] == pytest.approx(0.0)

    def test_trail_hook_emits_trail_window_behind_pulse(self):
        chip, route = self._ring_scene()
        tl = chip.timeline().wave_travel(
            route, steps=6, pulse_width=0.2, trail=True, trail_length=0.4
        )
        states = [s for s in tl._to_frame_states() if s["traveling_waves"]]
        # Mid-frame should have a real trail window (early frames may have head <= pulse_width)
        mid_state = states[len(states) // 2]
        assert id(route) in mid_state["trail_windows"]
        head_window = mid_state["traveling_waves"][id(route)]
        trail_window = mid_state["trail_windows"][id(route)]
        assert trail_window[1] == pytest.approx(head_window[0])
        assert trail_window[0] < trail_window[1]


# ---------------------------------------------------------------------------
# animate_grating_coupler_in_out
# ---------------------------------------------------------------------------


class TestAnimateGratingCouplerInOut:
    def _setup(self):
        scene = Scene(platform="on_chip", title="GC lesson")
        gc = scene.add(VerticalGratingCoupler(center=(-40, 0), label="GC1"))
        ring = scene.add(MicroringResonator(center=(40, 0), label="Ring"))
        route = scene.route((gc, "o1"), (ring, "o1"), kind="waveguide")
        return scene, gc, route

    def test_both_directions_produce_expected_steps(self):
        scene, gc, _route = self._setup()
        tl = animate_grating_coupler_in_out(scene, gc, direction="both", steps=4)
        kinds = _step_kinds(tl)

        # one show + at least 2 wave_travels (in + out) on the chip route + final cavity_power
        assert kinds.count("show") == 1
        assert kinds.count("wave_travel") >= 2
        assert kinds[-1] == "cavity_power"


    def test_invalid_direction_raises(self):
        scene, gc, _ = self._setup()
        with pytest.raises(ValueError):
            animate_grating_coupler_in_out(scene, gc, direction="sideways")

    def test_coupling_efficiency_caption(self):
        scene, gc, _ = self._setup()
        tl = animate_grating_coupler_in_out(
            scene, gc, coupling_efficiency=0.4, steps=3
        )
        final = tl._steps[-1]
        assert final.kind == "cavity_power"
        assert "coupling η ≈ 40" in final.caption
        assert "dB" in final.caption


# ---------------------------------------------------------------------------
# animate_fiber_alignment
# ---------------------------------------------------------------------------


class TestAnimateFiberAlignment:
    def _setup(self):
        scene = Scene(platform="on_chip", title="fiber alignment")
        gc = scene.add(VerticalGratingCoupler(center=(-40, 0), label="GC"))
        ring = scene.add(MicroringResonator(center=(40, 0), label="Ring"))
        scene.route((gc, "o1"), (ring, "o1"), kind="waveguide")
        return scene, gc


    def test_invalid_alignment_parameters_raise(self):
        scene, gc = self._setup()
        with pytest.raises(ValueError, match="alignment_steps"):
            animate_fiber_alignment(scene, gc, alignment_steps=0)
        with pytest.raises(ValueError, match="mode_field_diameter_um"):
            animate_fiber_alignment(scene, gc, mode_field_diameter_um=0.0)
        with pytest.raises(ValueError, match="start_offset_um"):
            animate_fiber_alignment(scene, gc, start_offset_um=(1.0,))

    def test_frame_state_keys(self):
        scene, gc = self._setup()
        tl = animate_fiber_alignment(scene, gc, alignment_steps=2, steps=2)
        states = tl._to_frame_states()
        assert states
        assert "highlight_levels" in states[-1]


# ---------------------------------------------------------------------------
# animate_directional_coupler_power_transfer
# ---------------------------------------------------------------------------


class TestAnimateDirectionalCouplerPowerTransfer:
    def _scene(self):
        scene = Scene(platform="on_chip", title="DC lesson")
        dc = scene.add(
            DirectionalCoupler(center=(0, 0), coupling_length=10.0, label="DC")
        )
        return scene, dc


    def test_length_steps_controls_sample_count(self):
        scene, dc = self._scene()
        for n in (1, 4, 9):
            tl = animate_directional_coupler_power_transfer(scene, dc, length_steps=n)
            assert _step_kinds(tl).count("cavity_power") == n

    def test_envelope_endpoints_label_through_and_cross(self):
        scene, dc = self._scene()
        tl = animate_directional_coupler_power_transfer(
            scene, dc, length_steps=2, full_crossover_length=4.0
        )
        captions = [s.caption for s in tl._steps if s.kind == "cavity_power"]
        # L=0 → through=1, cross=0
        assert "P_through ≈ 1.00" in captions[0]
        assert "P_cross ≈ 0.00" in captions[0]
        # L=Lc → through=0, cross=1
        assert "P_through ≈ 0.00" in captions[-1]
        assert "P_cross ≈ 1.00" in captions[-1]


# ---------------------------------------------------------------------------
# animate_mmi_split_recombine
# ---------------------------------------------------------------------------


class TestAnimateMmiSplitRecombine:
    def _scene_1x2(self):
        scene = Scene(platform="on_chip", title="MMI lesson")
        mmi = scene.add(MMI1x2(center=(0, 0), label="MMI 1x2"))
        return scene, mmi

    def _scene_2x2(self):
        scene = Scene(platform="on_chip", title="MMI 2x2 lesson")
        mmi = scene.add(MMI2x2(center=(0, 0), label="MMI 2x2"))
        return scene, mmi


    def test_imbalanced_caption(self):
        scene, mmi = self._scene_1x2()
        tl = animate_mmi_split_recombine(scene, mmi, imbalance_db=2.0, steps=4)
        captions = " ".join(s.caption for s in tl._steps)
        # 2 dB less power in output 2: 1 : 10**-0.2 gives 0.61 and 0.39 of the input
        assert "output 2 imbalance (2.0 dB)" in captions
        assert "P1 ≈ 0.61, P2 ≈ 0.39" in captions
        assert "equal split" not in captions

    def test_2x2_supported(self):
        scene, mmi = self._scene_2x2()
        tl = animate_mmi_split_recombine(scene, mmi, steps=3)
        assert "show" in _step_kinds(tl)
        assert "cavity_power" in _step_kinds(tl)


# ---------------------------------------------------------------------------
# animate_photodetector_absorption
# ---------------------------------------------------------------------------


class TestAnimatePhotodetectorAbsorption:


    def test_absorption_efficiency_in_caption(self):
        scene = Scene(platform="on_chip")
        gc = scene.add(VerticalGratingCoupler(center=(-60, 0), angle=180))
        pd = scene.add(OnChipPhotodetector(center=(60, 0), label="PD"))
        scene.route((gc, "o1"), (pd, "o1"), kind="waveguide")
        tl = animate_photodetector_absorption(
            scene, pd, absorption_efficiency=0.75, responsivity_a_per_w=1.1, steps=3
        )
        captions = " ".join(s.caption for s in tl._steps)
        assert "η_abs ≈ 0.75" in captions
        assert "R ≈ 1.10 A/W" in captions

    def test_invalid_absorption_efficiency_raises(self):
        scene = Scene(platform="on_chip")
        pd = scene.add(OnChipPhotodetector(center=(0, 0), label="PD"))
        with pytest.raises(ValueError):
            animate_photodetector_absorption(scene, pd, absorption_efficiency=2.0)

    def test_requires_scene_or_chain(self):
        with pytest.raises(ValueError):
            animate_photodetector_absorption(None, None)

    def test_frame_state_keys(self):
        chain = build_detector_readout_chain()
        tl = animate_photodetector_absorption(None, readout_chain=chain, steps=2)
        states = tl._to_frame_states()
        assert states
        for key in (
            "hidden_ids",
            "traveling_waves",
            "wave_opacities",
            "trail_windows",
        ):
            assert key in states[-1]


# ---------------------------------------------------------------------------
# animate_pn_modulation_phase_shift
# ---------------------------------------------------------------------------


class TestAnimatePnModulationPhaseShift:


    def test_invalid_inputs(self):
        scene = Scene(platform="on_chip")
        mzm = scene.add(MZM(label="MZM"))
        with pytest.raises(ValueError):
            animate_pn_modulation_phase_shift(scene, mzm, voltage_steps=0)
        with pytest.raises(ValueError):
            animate_pn_modulation_phase_shift(scene, mzm, voltage_max=0.0)


# ---------------------------------------------------------------------------
# Smoke test that all new recipes are importable from the package root
# ---------------------------------------------------------------------------


class TestExtendedRecipeExports:
    def test_recipes_exported_from_top_level(self):
        import optodraw

        for name in (
            "animate_grating_coupler_in_out",
            "animate_directional_coupler_power_transfer",
            "animate_mmi_split_recombine",
            "animate_photodetector_absorption",
            "animate_pn_modulation_phase_shift",
        ):
            assert hasattr(optodraw, name), f"missing top-level export: {name}"
