"""Tests for Tier 3 electro-optic drive and ring resonance stubs."""

from __future__ import annotations

import math

import pytest

from optodraw import (
    MZM,
    Scene,
    VerticalGratingCoupler,
    Waveguide,
    lorentzian_transmission,
    trace_active_chain,
    trace_mzm_transfer,
    trace_ring_resonance,
)
from optodraw.components.onchip.io import OnChipPhotodetector, SOA
from optodraw.components.onchip.rings import (
    MicroringResonator,
    PNMicroringModulator,
    RacetrackResonator,
)
from optodraw.registry import component_registry


class TestMZMDriveStyle:
    def test_gs_single_arm_at_vpi(self):
        mzm = MZM(drive_style="gs")
        at_vpi = trace_mzm_transfer(mzm, drive_voltage=4.0, Vpi=4.0)

        assert at_vpi["phase_model"] == "single_arm"
        assert at_vpi["phase_shift_rad"] == pytest.approx(math.pi)
        assert at_vpi["through_power"] == pytest.approx(0.0, abs=1e-12)
        assert at_vpi["cross_power"] == pytest.approx(1.0)

    def test_push_pull_dual_arm_gsg_at_vpi(self):
        mzm = MZM(drive_style="gsg")
        mzm.drive_style = "dual_arm_gsg"
        at_vpi = trace_mzm_transfer(mzm, drive_voltage=4.0, Vpi=4.0)

        assert at_vpi["phase_model"] == "push_pull"
        assert at_vpi["phase_shift_rad"] == pytest.approx(2.0 * math.pi)
        assert at_vpi["through_power"] == pytest.approx(1.0)
        assert at_vpi["cross_power"] == pytest.approx(0.0, abs=1e-12)

    def test_gs_vs_push_pull_phase_allocation_at_zero(self):
        gs = trace_mzm_transfer(MZM(drive_style="gs"), drive_voltage=0.0, Vpi=4.0)
        push_mzm = MZM(drive_style="gsg")
        push_mzm.drive_style = "dual_arm_gsg"
        push_pull = trace_mzm_transfer(push_mzm, drive_voltage=0.0, Vpi=4.0)

        assert gs["through_power"] == pytest.approx(1.0)
        assert push_pull["through_power"] == pytest.approx(1.0)
        assert gs["phase_shift_rad"] == pytest.approx(0.0)
        assert push_pull["phase_shift_rad"] == pytest.approx(0.0)
        assert gs["phase_model"] == "single_arm"
        assert push_pull["phase_model"] == "push_pull"

    def test_extinction_db_estimate_present(self):
        mzm = MZM()
        result = trace_mzm_transfer(mzm, drive_voltage=2.0, Vpi=4.0)
        assert result["extinction_db"] is not None
        assert result["extinction_db"] > 0.0


class TestLorentzianRingResonance:
    def test_on_resonance_through_dip(self):
        through = lorentzian_transmission(1550.0, 1550.0, 1e4, port="through")
        drop = lorentzian_transmission(1550.0, 1550.0, 1e4, port="drop")

        assert through == pytest.approx(0.0, abs=1e-12)
        assert drop == pytest.approx(1.0)

    def test_off_resonance_through_near_unity(self):
        through = lorentzian_transmission(1560.0, 1550.0, 1e4, port="through")
        assert through > 0.9

    def test_trace_ring_resonance_on_vs_off(self):
        ring = MicroringResonator(ring_radius=8.0)
        on_res = trace_ring_resonance(ring, wavelength_nm=1550.0, bias_voltage_v=0.0)
        off_res = trace_ring_resonance(ring, wavelength_nm=1560.0, bias_voltage_v=0.0)

        assert on_res["through_power"] < off_res["through_power"]
        assert on_res["fsr_nm"] is not None
        assert on_res["Q"] == pytest.approx(1e4)

    def test_bias_voltage_shifts_lambda0(self):
        ring = MicroringResonator(ring_radius=8.0)
        zero_bias = trace_ring_resonance(ring, wavelength_nm=1550.1, bias_voltage_v=0.0)
        tuned = trace_ring_resonance(
            ring,
            wavelength_nm=1550.1,
            bias_voltage_v=10.0,
            tuning_efficiency_nm_per_v=0.01,
        )

        assert tuned["lambda0_nm"] == pytest.approx(1550.1)
        assert zero_bias["lambda0_nm"] == pytest.approx(1550.0)
        assert tuned["lambda0_nm"] > zero_bias["lambda0_nm"]
        assert tuned["through_power"] < zero_bias["through_power"]

    def test_pn_microring_and_racetrack_shared_helper(self):
        pn = PNMicroringModulator(ring_radius=8.0)
        racetrack = RacetrackResonator(bend_radius=10.0, coupling_length=18.0)

        pn_result = trace_ring_resonance(pn, wavelength_nm=1550.0)
        rt_result = trace_ring_resonance(racetrack, wavelength_nm=1550.0)

        assert pn_result["through_power"] == pytest.approx(0.0, abs=1e-12)
        assert rt_result["through_power"] == pytest.approx(0.0, abs=1e-12)
        # no group index, no free spectral range: the helper no longer invents one
        assert rt_result["fsr_nm"] is None
        assert rt_result["fsr_source"] is None

    def test_racetrack_fsr_needs_a_group_index(self):
        """FSR = lambda^2 / (n_g L), with L the round trip: two half circles and two straights."""

        racetrack = RacetrackResonator(bend_radius=10.0, coupling_length=18.0)
        racetrack.group_index = 4.2
        result = trace_ring_resonance(racetrack, wavelength_nm=1550.0)

        round_trip_um = 2.0 * math.pi * 10.0 + 2.0 * 18.0
        assert result["fsr_nm"] == pytest.approx(1.55**2 / (4.2 * round_trip_um) * 1000.0)
        assert result["fsr_source"] == "group_index"

    def test_scene_trace_resonator(self):
        scene = Scene(platform="on_chip")
        ring = scene.add(MicroringResonator(ring_radius=8.0))
        result = scene.trace_resonator(ring, wavelength_nm=1550.0)

        assert result["through_power"] == pytest.approx(0.0, abs=1e-12)


class TestRegistryModulationModes:
    def test_ring_and_mzm_modulation_modes(self):
        registry = component_registry()

        assert "modulation" in registry["MZM"].physics_modes
        assert "guided" in registry["MZM"].physics_modes
        assert "modulation" in registry["MicroringResonator"].physics_modes
        assert "modulation" in registry["PNMicroringModulator"].physics_modes
        assert "modulation" in registry["RacetrackResonator"].physics_modes


class TestActiveChainSOA:
    def test_soa_increases_detected_power(self):
        scene = Scene(platform="on_chip")
        gc = scene.add(VerticalGratingCoupler(center=(-80, 0)))
        mzi = scene.add(MZM(center=(0, 0)))
        soa = scene.add(SOA(center=(40, 0)))
        pd = scene.add(OnChipPhotodetector(center=(80, 0)))
        wg1 = scene.add(Waveguide(center=(-40, 0), length=20.0))
        wg2 = scene.add(Waveguide(center=(60, 0), length=20.0))
        route1 = scene.route((gc, "o1"), (wg1, "o1"), path_type="straight")
        route2 = scene.route((wg1, "o2"), (mzi, "o1"), path_type="straight")
        route3 = scene.route((mzi, "o3"), (soa, "o1"), path_type="straight")
        route4 = scene.route((soa, "o2"), (wg2, "o1"), path_type="straight")
        route_mzi_pd = scene.route((mzi, "o3"), (wg2, "o1"), path_type="straight")
        route5 = scene.route((wg2, "o2"), (pd, "o1"), path_type="straight")

        without_soa = trace_active_chain(
            [gc, route1, wg1, route2, mzi, route_mzi_pd, wg2, route5, pd],
            drive_voltage=0.0,
        )
        with_soa = trace_active_chain(
            [gc, route1, wg1, route2, mzi, route3, soa, route4, wg2, route5, pd],
            drive_voltage=0.0,
        )

        assert with_soa["soa"] is not None
        assert with_soa["soa"]["linear_gain"] == pytest.approx(100.0)
        assert with_soa["photodetector"]["photocurrent_a"] > without_soa["photodetector"]["photocurrent_a"]
