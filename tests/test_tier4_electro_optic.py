"""Tests for Tier 4 electro-optic drive/readout recipes and electrical stubs."""

from __future__ import annotations

import pytest

from optodraw import (
    ElectricalIOBank,
    ElectricalPad,
    GSGProbePad,
    Scene,
    build_detector_readout_chain,
    electrical_signal_spec,
    port_signal_kind,
    route_signal_spec,
    route_ports,
    validate_electrical_chain,
)


class TestTier4RoutingMetadata:

    def test_route_ports_records_signal_assumptions(self):
        left = GSGProbePad(center=(-40, 0), impedance_ohms=50.0, bandwidth_ghz=67.0)
        right = GSGProbePad(center=(40, 0), impedance_ohms=50.0, bandwidth_ghz=40.0)

        route = route_ports(
            (left, "s"),
            (right, "s"),
            kind="electrical",
            signal="rf",
            impedance_ohms=50.0,
            bit_rate_gbps=80.0,
            rf_power_dbm=-3.0,
        )

        spec = route_signal_spec(route)
        assert spec.kind == "rf"
        assert spec.impedance_ohms == pytest.approx(50.0)
        assert spec.bit_rate_gbps == pytest.approx(80.0)
        assert spec.rf_power_dbm == pytest.approx(-3.0)
        assert route.to_dict()["route_bit_rate_gbps"] == pytest.approx(80.0)


class TestTier4ReadoutTracing:

    def test_scene_trace_readout_chain_uses_scene_wrapper(self):
        scene = build_detector_readout_chain()["scene"]

        result = scene.trace_readout_chain(
            optical_power_w=1.25,
            transimpedance_ohm=200.0,
            adc_full_scale_v=2.0,
            adc_bits=8,
        )

        assert result["photocurrent_a"] == pytest.approx(1.0)
        assert result["tia_output_voltage_v"] == pytest.approx(200.0)
        assert result["adc_code_stub"] == 255


class TestTier4ElectricalValidation:

    def test_electrical_io_bank_signal_kinds_are_per_port(self):
        bank = ElectricalIOBank(count=3, signal_kinds=("dc", "rf", "clock"))
        assert port_signal_kind(bank, "e1") == "dc"
        assert port_signal_kind(bank, "e2") == "rf"
        assert port_signal_kind(bank, "e3") == "clock"

    def test_electrical_signal_spec_lifts_component_metadata(self):
        launch = GSGProbePad(impedance_ohms=50.0, bandwidth_ghz=67.0, insertion_loss_db=0.35)
        spec = electrical_signal_spec(launch, "s")
        payload = spec.to_dict()
        assert spec.kind == "rf"
        assert spec.impedance_ohms == pytest.approx(50.0)
        assert spec.bandwidth_ghz == pytest.approx(67.0)
        assert payload["metadata"]["insertion_loss_db"] == pytest.approx(0.35)


    def test_validate_electrical_chain_warns_on_rf_impedance_mismatch(self):
        scene = Scene(platform="mixed")
        left = scene.add(GSGProbePad(center=(-40, 0), port_side="right", impedance_ohms=50.0))
        right = scene.add(GSGProbePad(center=(40, 0), impedance_ohms=75.0))
        scene.route((left, "s"), (right, "s"), kind="electrical", signal="rf", impedance_ohms=50.0)

        warnings = validate_electrical_chain(scene.walk())

        assert any("RF impedance mismatch" in warning for warning in warnings)
        assert any("75 ohm" in warning for warning in warnings)

    def test_validate_electrical_chain_warns_on_bandwidth_bottleneck(self):
        scene = Scene(platform="mixed")
        left = scene.add(GSGProbePad(center=(-40, 0), port_side="right", bandwidth_ghz=67.0))
        right = scene.add(GSGProbePad(center=(40, 0), bandwidth_ghz=25.0))
        scene.route((left, "s"), (right, "s"), kind="electrical", signal="rf", required_bandwidth_ghz=50.0)

        warnings = validate_electrical_chain(scene.walk())

        assert any("Bandwidth bottleneck" in warning for warning in warnings)
        assert any("25 GHz" in warning for warning in warnings)

    def test_scene_validate_electrical_matches_core_helper(self):
        scene = Scene(platform="on_chip")
        rf_probe = scene.add(GSGProbePad(center=(-40, 0), port_side="right"))
        pad = scene.add(ElectricalPad(center=(40, 0), port_side="left"))
        scene.route((rf_probe, "s"), (pad, "e1"), kind="electrical", signal="rf")

        assert scene.validate_electrical() == validate_electrical_chain(scene.walk())
