"""Tests for physics bridge and enriched guided/interferometer/resonator traces."""

from __future__ import annotations

import math

import pytest

from optodraw import MZI, Waveguide, trace_mzi_transfer
from optodraw.components.onchip.rings import MicroringResonator
from optodraw.core.guided import (
    summarize_path,
    trace_guided_path,
)
from optodraw.core.resonator import trace_ring_resonance


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


class TestResonatorHelpers:


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


