"""Tests for physics bridge and enriched guided/interferometer/resonator traces."""

from __future__ import annotations

import math

import pytest

from optodraw import MZI, MZM, Scene, Waveguide, trace_mzi_transfer
from optodraw.components.onchip.io import OnChipPhotodetector
from optodraw.components.onchip.rings import MicroringResonator, PNMicroringModulator
from optodraw.core.guided import (
    SILICON_STRIP_NG_STUB,
    summarize_path,
    trace_guided_path,
)
from optodraw.core.interferometer import trace_mzi_power
from optodraw.core.physics_bridge import physics_trace_to_timeline_hints
from optodraw.core.resonator import Q_from_kappa_gamma, lorentzian_fwhm_nm, trace_ring_resonance


class TestGuidedPathEnrichment:
    def test_trace_guided_path_loss_budget_and_group_index(self):
        wg = Waveguide(length=100.0, effective_index=2.5)
        result = trace_guided_path(
            [wg],
            wavelength_nm=1550.0,
            loss_db_per_um=0.01,
            loss_budget_db=0.5,
            group_index=4.1,
        )

        assert result.path_length_um == pytest.approx(100.0)
        assert result.loss_db == pytest.approx(1.0)
        assert result.loss_budget_exceeded is True
        assert result.group_index == pytest.approx(4.1)
        # Dimensional reference: 4.1 * 100 um / 299.792458 um/ps = 1.3676 ps.
        assert result.group_delay_ps == pytest.approx(1.3676, abs=1e-3)
        assert result.group_delay_ps == pytest.approx(4.1 * 100.0 / 299.792458)
        assert result.segment_count == 1

    def test_summarize_path_from_components(self):
        wg_a = Waveguide(length=10.0, effective_index=2.4)
        wg_b = Waveguide(length=20.0, effective_index=2.6)
        summary = summarize_path([wg_a, wg_b], wavelength_nm=1550.0)

        assert summary["path_length_um"] == pytest.approx(30.0)
        assert summary["effective_index_min"] == pytest.approx(2.4)
        assert summary["effective_index_max"] == pytest.approx(2.6)
        assert summary["effective_index_spread"] == pytest.approx(0.2)
        assert summary["segment_count"] == 2

    def test_summarize_path_accepts_trace_result(self):
        trace = trace_guided_path([Waveguide(length=15.0)], group_index=SILICON_STRIP_NG_STUB)
        summary = summarize_path(trace)
        assert summary["path_length_um"] == pytest.approx(15.0)
        assert summary["group_index"] == pytest.approx(SILICON_STRIP_NG_STUB)


class TestMziTransferEnrichment:
    def test_arm_imbalance_shifts_transmission(self):
        mzi = MZI()
        balanced = trace_mzi_transfer(mzi, phase_bias_rad=0.0, arm_imbalance_um=0.0)
        imbalanced = trace_mzi_transfer(
            mzi,
            phase_bias_rad=0.0,
            arm_imbalance_um=50.0,
            effective_index=2.4,
            wavelength_nm=1550.0,
        )

        assert balanced["through_power"] == pytest.approx(1.0)
        assert imbalanced["through_power"] < 1.0
        assert imbalanced["arm_imbalance_phase_rad"] == pytest.approx(
            2.0 * math.pi * 2.4 * 50.0 / 1.55,
            rel=1e-6,
        )

    def test_phase_bias_upper_lower_arms(self):
        mzi = MZI()

        class BiasedMZI(MZI):
            def physics_metadata(self):
                base = super().physics_metadata()
                base["phase_bias_upper_arm"] = math.pi / 4
                base["phase_bias_lower_arm"] = 0.0
                return base

        result = trace_mzi_transfer(BiasedMZI(), phase_bias_rad=0.0)
        assert result["phase_bias_rad"] == pytest.approx(math.pi / 4)
        assert result["through_power"] < 1.0

    def test_trace_mzi_power_delegates_to_transfer(self):
        mzi = MZI()
        power = trace_mzi_power(mzi, phase_bias_rad=math.pi)
        transfer = trace_mzi_transfer(mzi, phase_bias_rad=math.pi)
        assert power["through_power"] == pytest.approx(transfer["through_power"])


class TestResonatorHelpers:
    def test_lorentzian_fwhm_nm(self):
        assert lorentzian_fwhm_nm(1550.0, 1e4) == pytest.approx(0.155)

    def test_q_from_kappa_gamma(self):
        q = Q_from_kappa_gamma(1550.0, kappa=1.5e11, gamma=0.5e11)
        assert q > 0.0

    def test_trace_ring_resonance_uses_kappa_gamma(self):
        ring = MicroringResonator(ring_radius=8.0)

        class KappaGammaRing(MicroringResonator):
            def physics_metadata(self):
                base = super().physics_metadata()
                base["kappa"] = 1.5e11
                base["gamma"] = 0.5e11
                return base

        result = trace_ring_resonance(KappaGammaRing(ring_radius=8.0), wavelength_nm=1550.0)
        assert result["Q_source"] == "kappa_gamma"
        assert result["fwhm_nm"] == pytest.approx(result["lambda0_nm"] / result["Q"])


class TestPhysicsBridge:
    def test_ring_mzi_scene_hints(self):
        scene = Scene(platform="on_chip")
        mzi = scene.add(MZI(center=(-20, 0)))
        ring = scene.add(MicroringResonator(center=(20, 0), ring_radius=8.0))
        wg = scene.add(Waveguide(center=(0, 0), length=30.0))
        mzi._id = "mzi"
        ring._id = "ring"
        wg._id = "wg"

        hints = physics_trace_to_timeline_hints(scene, wavelength_nm=1550.0)

        assert "mzi" in hints
        assert hints["mzi"]["recipe"] == "animate_interference"
        assert "phase_bias_rad" in hints["mzi"]["hints"]
        assert hints["mzi"]["hints"]["interference_regime"] == "constructive"

        assert "ring" in hints
        assert hints["ring"]["recipe"] == "animate_resonance_scan"
        assert hints["ring"]["hints"]["Q"] == pytest.approx(1e4)
        assert "wavelength_start_nm" in hints["ring"]["hints"]
        assert "guided_path_summary" in hints["ring"]["hints"]

    def test_mzm_modulator_hints(self):
        scene = Scene(platform="on_chip")
        mzm = scene.add(MZM(drive_style="gsg"))
        mzm._id = "mzm"

        hints = physics_trace_to_timeline_hints(scene)
        assert hints["mzm"]["recipe"] == "animate_mzm_mechanism"
        assert "animate_modulation" in hints["mzm"]["alternate_recipes"]
        assert hints["mzm"]["hints"]["Vpi"] == pytest.approx(4.0)

    def test_pn_ring_primary_recipe(self):
        scene = Scene(platform="on_chip")
        ring = scene.add(PNMicroringModulator(ring_radius=8.0))
        ring._id = "pn_ring"

        hints = physics_trace_to_timeline_hints(scene)
        assert hints["pn_ring"]["recipe"] == "animate_pn_modulation_phase_shift"
        assert "animate_resonance_scan" in hints["pn_ring"]["alternate_recipes"]

    def test_photodetector_chain_hints(self):
        scene = Scene(platform="on_chip")
        pd = scene.add(OnChipPhotodetector(center=(0, 0)))
        pd._id = "pd"

        hints = physics_trace_to_timeline_hints(scene, include_guided_paths=False)
        assert hints["pd"]["recipe"] == "animate_photodetector_absorption"
        assert hints["pd"]["hints"]["responsivity_a_per_w"] == pytest.approx(0.8)
