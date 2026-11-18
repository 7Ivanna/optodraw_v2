"""Tests for electronics I/O banks and receiver/transmitter macros."""

from __future__ import annotations

import pytest

from optodraw import (
    BalancedPhotodetector,
    CoherentReceiver,
    ElectricalIOBank,
    ReceiverMacro,
    TransmitterMacro,
)
from optodraw.catalog import describe_component
from optodraw.registry import build_component, component_registry, describe_physics_support


def test_electrical_io_bank_ports_and_metadata():
    bank = ElectricalIOBank(count=4, pitch=6.0, side="right", signal_kinds=("dc", "rf", "clock", "digital"))
    ports = bank.ports()
    assert list(ports) == ["e1", "e2", "e3", "e4"]
    assert ports["e1"].kind == "electrical"
    assert ports["e4"].orientation_deg == pytest.approx(0.0)
    assert bank.physics_metadata()["signal_kinds"] == ["dc", "rf", "clock", "digital"]
    rects = [child for child in bank.geometry_2d()["children"] if child.get("type") == "rect"]
    assert len(rects) >= 5


def test_electrical_io_bank_top_side_orientation():
    bank = ElectricalIOBank(count=3, side="top")
    ports = bank.ports()
    assert ports["e1"].orientation_deg == pytest.approx(90.0)
    assert ports["e1"].center.y == pytest.approx(bank.width / 2.0)


def test_balanced_photodetector_ports_and_metadata():
    detector = BalancedPhotodetector(responsivity_a_per_w=0.72, bandwidth_ghz=32.0, cmrr_db=31.0)
    assert detector.ports()["opt_p"].kind == "optical"
    assert detector.ports()["out"].kind == "electrical"
    metadata = detector.physics_metadata()
    assert metadata["responsivity_a_per_w"] == pytest.approx(0.72)
    assert metadata["bandwidth_ghz"] == pytest.approx(32.0)
    assert metadata["cmrr_db"] == pytest.approx(31.0)
    assert detector.geometry_3d()["shape"] == "group"


def test_coherent_receiver_exposes_iq_and_optical_ports():
    receiver = CoherentReceiver(polarization_diverse=True)
    ports = receiver.ports()
    assert {"signal", "lo", "i_p", "i_n", "q_p", "q_n", "clk", "vdd", "gnd"} <= set(ports)
    assert ports["signal"].kind == "optical"
    assert ports["q_n"].kind == "electrical"
    assert receiver.physics_metadata()["polarization_diverse"] is True
    assert any(child.get("type") == "polygon" for child in receiver.geometry_2d()["children"])


def test_transmitter_macro_ports_and_metadata():
    transmitter = TransmitterMacro(data_rate_gbps=100.0, wavelength_nm=1310.0, extinction_ratio_db=7.5)
    assert transmitter.ports()["data"].kind == "electrical"
    assert transmitter.ports()["opt_out"].kind == "optical"
    metadata = transmitter.physics_metadata()
    assert metadata["data_rate_gbps"] == pytest.approx(100.0)
    assert metadata["wavelength_nm"] == pytest.approx(1310.0)
    assert metadata["extinction_ratio_db"] == pytest.approx(7.5)


def test_receiver_macro_ports_and_metadata():
    receiver = ReceiverMacro(adc_bits=10, bandwidth_ghz=18.0)
    assert receiver.ports()["opt_in"].kind == "optical"
    assert receiver.ports()["digital_out"].kind == "electrical"
    assert receiver.physics_metadata()["adc_bits"] == 10
    assert receiver.physics_metadata()["bandwidth_ghz"] == pytest.approx(18.0)


@pytest.mark.parametrize(
    "name",
    ["ElectricalIOBank", "BalancedPhotodetector", "CoherentReceiver", "TransmitterMacro", "ReceiverMacro"],
)
def test_system_macros_are_registry_creatable(name: str):
    component = build_component(name)
    assert component.component_type == name
    assert component.geometry_2d()
    assert component.geometry_3d()["shape"] == "group"
    assert name in component_registry()


@pytest.mark.parametrize("name", ["BalancedPhotodetector", "CoherentReceiver", "ReceiverMacro"])
def test_readout_components_advertise_readout_mode(name: str):
    info = describe_physics_support(name)
    assert "readout" in info["physics_modes"]
    catalog_info = describe_component(name)
    assert catalog_info["category"] == "electronics"


def test_transmitter_macro_advertises_modulation_mode():
    info = describe_physics_support("TransmitterMacro")
    assert "modulation" in info["physics_modes"]

class TestGeneratedLayoutsFitTheirFrame:
    """A generated layout must fit the figure it will be exported as.

    The readout chain put a 42-wide ADC at x=180 in a 360-wide scene, so 21
    units of it fell off the right edge of every SVG, PNG and TikZ it produced.
    Nothing said so, because the canvas is unbounded and only the export is not.
    """

    def test_no_generator_places_a_part_outside_the_frame(self):
        from optodraw.app.generators import build, list_generators

        clipped = []
        for generator in list_generators():
            params = {field["key"]: field.get("value") for field in generator["fields"]}
            scene = build(generator["name"], params)
            min_x, min_y, max_x, max_y = scene.content_bounds()
            cx, cy = scene.frame_center
            over_x = max(max_x - cx - scene.width / 2.0, cx - scene.width / 2.0 - min_x)
            over_y = max(max_y - cy - scene.height / 2.0, cy - scene.height / 2.0 - min_y)
            if over_x > 0.5 or over_y > 0.5:
                clipped.append(f"{generator['name']} (x by {over_x:.1f}, y by {over_y:.1f})")
        assert not clipped, "generated layouts that will be cut off: " + ", ".join(clipped)
