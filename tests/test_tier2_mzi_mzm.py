"""Tests for Tier 2 MZI/MZM and active on-chip device stubs."""

from __future__ import annotations

import math

import pytest

from optodraw import (
    MZI,
    MZM,
    Scene,
    Waveguide,
    trace_active_chain,
    trace_mzi_power,
    trace_mzm_transfer,
)
from optodraw.components.onchip.couplers import VerticalGratingCoupler
from optodraw.components.onchip.io import OnChipPhotodetector, SOA
from optodraw.components.onchip.rings import PNMicroringModulator, RacetrackModulator
from optodraw.registry import component_registry


class TestMZIAndMZMPhysicsMetadata:
    def test_mzi_physics_metadata_keys(self):
        mzi = MZI(arm_length=50.0, arm_gap=14.0)
        metadata = mzi.physics_metadata()

        assert metadata["domain"] == "on_chip"
        assert metadata["component"] == "mzi"
        assert metadata["arm_length"] == pytest.approx(50.0)
        assert metadata["arm_gap"] == pytest.approx(14.0)
        assert metadata["phase_bias"] == pytest.approx(0.0)
        assert metadata["extinction_ratio_db"] is None

    def test_mzm_physics_metadata_keys(self):
        mzm = MZM(drive_style="gsg", arm_length=45.0)
        metadata = mzm.physics_metadata()

        assert metadata["component"] == "mzm"
        assert metadata["drive_style"] == "gsg"
        assert metadata["phase_bias_upper_arm"] == pytest.approx(0.0)
        assert metadata["phase_bias_lower_arm"] == pytest.approx(0.0)
        assert metadata["VpiL"] is None
        assert metadata["arm_length"] == pytest.approx(45.0)

    def test_active_device_physics_metadata_keys(self):
        pn_ring = PNMicroringModulator(ring_radius=8.0)
        pn_metadata = pn_ring.physics_metadata()
        assert pn_metadata["modulation_mechanism"] == "pn_depletion"
        assert pn_metadata["bias_voltage_v"] is None

        racetrack = RacetrackModulator(bend_radius=10.0)
        rt_metadata = racetrack.physics_metadata()
        assert rt_metadata["modulation_mechanism"] == "pn_depletion"
        assert rt_metadata["bias_voltage_v"] is None

        pd = OnChipPhotodetector()
        pd_metadata = pd.physics_metadata()
        assert pd_metadata["responsivity_a_per_w"] == pytest.approx(0.8)
        assert pd_metadata["bandwidth_ghz"] is None

        soa = SOA()
        soa_metadata = soa.physics_metadata()
        assert soa_metadata["gain_db"] == pytest.approx(20.0)
        assert soa_metadata["saturation_power_mw"] is None


class TestTraceMZIPower:
    def test_phase_zero_max_transmission(self):
        mzi = MZI()
        result = trace_mzi_power(mzi, phase_bias_rad=0.0)

        assert result["through_power"] == pytest.approx(1.0)
        assert result["drop_power"] == pytest.approx(0.0)

    def test_phase_pi_min_transmission(self):
        mzi = MZI()
        result = trace_mzi_power(mzi, phase_bias_rad=math.pi)

        assert result["through_power"] == pytest.approx(0.0, abs=1e-12)
        assert result["drop_power"] == pytest.approx(1.0)

    def test_scene_trace_interferometer_mzi(self):
        scene = Scene(platform="on_chip")
        mzi = scene.add(MZI())
        result = scene.trace_interferometer(mzi, phase_bias_rad=0.0)

        assert result["through_power"] == pytest.approx(1.0)


class TestTraceMZMTransfer:
    def test_v_zero_vs_vpi_behavior(self):
        mzm = MZM()
        at_zero = trace_mzm_transfer(mzm, drive_voltage=0.0, Vpi=4.0)
        at_vpi = trace_mzm_transfer(mzm, drive_voltage=4.0, Vpi=4.0)

        assert at_zero["transmission"] == pytest.approx(1.0)
        assert at_vpi["transmission"] == pytest.approx(0.0, abs=1e-12)
        assert at_zero["drive_style"] == "gs"

    def test_scene_trace_interferometer_mzm(self):
        scene = Scene(platform="on_chip")
        mzm = scene.add(MZM(drive_style="gs"))
        result = scene.trace_interferometer(mzm, drive_voltage=2.0, Vpi=4.0)

        assert result["transmission"] == pytest.approx(0.5)


class TestRegistryPhysicsModes:
    def test_mzi_mzm_guided_physics_modes(self):
        mzi_spec = component_registry()["MZI"]
        mzm_spec = component_registry()["MZM"]

        assert "diagram" in mzi_spec.physics_modes
        assert "guided" in mzi_spec.physics_modes
        assert "guided" in mzm_spec.physics_modes


class TestActiveChainTrace:
    def test_gc_mzi_pd_chain_smoke(self):
        scene = Scene(platform="on_chip")
        gc = scene.add(VerticalGratingCoupler(center=(-80, 0)))
        mzi = scene.add(MZI(center=(0, 0)))
        pd = scene.add(OnChipPhotodetector(center=(80, 0)))
        wg1 = scene.add(Waveguide(center=(-40, 0), length=20.0))
        wg2 = scene.add(Waveguide(center=(40, 0), length=20.0))
        route1 = scene.route((gc, "o1"), (wg1, "o1"), path_type="straight")
        route2 = scene.route((wg1, "o2"), (mzi, "o1"), path_type="straight")
        route3 = scene.route((mzi, "o3"), (wg2, "o1"), path_type="straight")
        route4 = scene.route((wg2, "o2"), (pd, "o1"), path_type="straight")

        chain = [gc, route1, wg1, route2, mzi, route3, wg2, route4, pd]
        result = trace_active_chain(chain, phase_bias_rad=0.0)

        assert result["guided"]["path_length_um"] > 0.0
        assert result["interferometer"]["through_power"] == pytest.approx(1.0)
        assert result["photodetector"]["photocurrent_a"] == pytest.approx(0.8)
        assert result["combined_path_length_um"] == pytest.approx(result["guided"]["path_length_um"])
