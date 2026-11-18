"""Tests for Tier 4 electro-optic drive/readout recipes and electrical stubs."""

from __future__ import annotations

import pytest

from optodraw import (
    ADC,
    DACDriver,
    ElectricalIOBank,
    ElectricalPad,
    GSGProbePad,
    MZM,
    OnChipPhotodetector,
    Scene,
    TIA,
    build_detector_readout_chain,
    build_modulator_drive_chain,
    electrical_signal_spec,
    port_signal_kind,
    route_signal_spec,
    route_ports,
    trace_readout_chain,
    validate_electrical_chain,
)


def _electrical_routes(scene: Scene):
    return [
        node
        for node in scene.walk()
        if getattr(node, "component_type", "") in {"Route", "WaveguideRoute", "FiberRoute"}
        and getattr(node, "kind", None) == "electrical"
    ]


class TestTier4Recipes:
    def test_build_modulator_drive_chain_adds_rf_routes_optical_stub_and_arrow(self):
        recipe = build_modulator_drive_chain(drive_style="gsg")
        scene = recipe["scene"]
        routes = recipe["routes"]

        assert isinstance(recipe["driver"], DACDriver)
        assert isinstance(recipe["mzm"], MZM)
        assert len(routes) == 2
        assert all(route.signal == "rf" for route in routes)
        assert all(route.start_component is not None for route in routes)
        assert all(route.end_component is not None for route in routes)
        assert len(recipe["annotations"]) == 1
        assert recipe["annotations"][0].signal == "rf"
        assert recipe["optical_stub"]["input_port"] == "o1"
        assert recipe["optical_stub"]["output_port"] == "o3"
        assert recipe["optical_stub"]["drive_style"] == "gsg"
        assert any(getattr(node, "component_type", "") == "DACDriver" for node in scene.walk())

    def test_build_detector_readout_chain_adds_pd_tia_adc_routes_and_annotations(self):
        recipe = build_detector_readout_chain()
        scene = recipe["scene"]
        component_types = {getattr(node, "component_type", "") for node in scene.walk()}
        routes = recipe["routes"]

        assert {"OnChipPhotodetector", "TIA", "ADC"}.issubset(component_types)
        assert len(routes) == 2
        assert {route.signal for route in routes} == {"photocurrent", "analog"}
        assert len(recipe["annotations"]) == 3
        assert {arrow.signal for arrow in recipe["annotations"]} == {
            "current",
            "voltage",
            "digital",
        }


class TestTier4RoutingMetadata:
    def test_route_ports_records_signal_and_endpoint_references(self):
        driver = DACDriver(center=(-30, 0))
        mzm = MZM(center=(30, 0), drive_style="gsg")

        route = route_ports((driver, "e3"), (mzm, "sig"), kind="electrical", signal="rf")

        assert route.signal == "rf"
        assert route.start_component is driver
        assert route.start_port == "e3"
        assert route.end_component is mzm
        assert route.end_port == "sig"

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
    def test_trace_readout_chain_computes_photocurrent_voltage_and_adc_stub(self):
        pd = OnChipPhotodetector()
        tia = TIA()
        adc = ADC()

        result = trace_readout_chain(
            [pd, tia, adc],
            optical_power_w=2.0,
            transimpedance_ohm=500.0,
            adc_full_scale_v=1.0,
            adc_bits=10,
        )

        assert result["photocurrent_a"] == pytest.approx(1.6)
        assert result["tia_output_voltage_v"] == pytest.approx(800.0)
        assert result["adc_code_stub"] == 1023

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
    def test_port_signal_kind_classifies_electrical_pad_as_dc(self):
        assert port_signal_kind(ElectricalPad(), "e1") == "dc"

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

    def test_validate_electrical_chain_warns_on_rf_route_to_dc_pad(self):
        scene = Scene(platform="on_chip")
        rf_probe = scene.add(GSGProbePad(center=(-40, 0), port_side="right"))
        pad = scene.add(ElectricalPad(center=(40, 0), port_side="left"))
        scene.route(
            (rf_probe, "s"),
            (pad, "e1"),
            kind="electrical",
            signal="rf",
            label="rf_to_pad",
        )

        warnings = validate_electrical_chain(scene.walk())

        assert len(warnings) == 1
        assert "RF electrical route" in warnings[0]
        assert "DC-only pad" in warnings[0]
        assert "ElectricalPad.e1" in warnings[0]

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
