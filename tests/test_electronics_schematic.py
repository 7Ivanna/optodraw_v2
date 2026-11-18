"""Tests for schematic-first electronics and packaging components."""

from __future__ import annotations

import pytest

from optodraw import ElectricalPad, GSGProbePad, HeaterPad, MetalRoute
from optodraw.registry import component_registry, describe_physics_support


def _first_rect(geometry: dict) -> dict:
    for child in geometry.get("children", []):
        if child.get("type") == "rect":
            return child
    raise AssertionError("expected a rect child in geometry group")


class TestPackagingSchematicDefaults:
    def test_electrical_pad_draws_its_own_size_so_the_port_sits_on_its_edge(self):
        pad = ElectricalPad(width=18.0, height=18.0)
        assert pad.ports()["e1"].center.x == pytest.approx(-9.0)
        rect = _first_rect(pad.geometry_2d())
        assert rect["w"] == pytest.approx(18.0)
        assert rect["h"] == pytest.approx(18.0)

    def test_electrical_pad_render_physical_uses_true_sizes(self):
        pad = ElectricalPad(width=18.0, height=22.0, render_physical=True)
        rect = _first_rect(pad.geometry_2d())
        assert rect["w"] == pytest.approx(18.0)
        assert rect["h"] == pytest.approx(22.0)

    def test_electrical_pad_physical_spec_round_trip(self):
        pad = ElectricalPad(width=40.0, height=35.0, port_width=12.0)
        spec = pad.physical_spec()
        assert spec["width"] == pytest.approx(40.0)
        assert spec["height"] == pytest.approx(35.0)
        assert spec["port_width"] == pytest.approx(12.0)

    def test_gsg_probe_pad_draws_its_pads_at_their_pitch(self):
        gsg = GSGProbePad(pad_width=20.0, pad_height=5.0, gap=3.0)
        assert gsg.pitch == pytest.approx(8.0)
        rects = [c for c in gsg.geometry_2d()["children"] if c["type"] == "rect"]
        # each G/S/G pad layers a base, a bright surface and a scrub mark; the base is the pad itself
        pad_rects = [r for r in rects if r["w"] == pytest.approx(20.0) and r["h"] == pytest.approx(5.0)]
        assert len(pad_rects) == 3
        assert sorted(r["cy"] for r in pad_rects) == pytest.approx([-8.0, 0.0, 8.0])

    def test_gsg_probe_pad_render_physical(self):
        gsg = GSGProbePad(pad_width=20.0, pad_height=5.0, gap=3.0, render_physical=True)
        rect = _first_rect(gsg.geometry_2d())
        assert rect["w"] == pytest.approx(20.0)
        assert rect["h"] == pytest.approx(5.0)

    def test_metal_route_ports_stay_physical_draw_schematic(self):
        route = MetalRoute(points=((0.0, 0.0), (12.0, 0.0)), width=0.5, thickness=0.05)
        assert route.ports()["e2"].center.x == pytest.approx(12.0)
        assert route.geometry_2d()["stroke_width"] == pytest.approx(1.6)
        assert route.geometry_2d()["stroke_width"] > route.width
        assert route.physical_spec()["resistance_ohms"] == pytest.approx(1.92)

    def test_metal_route_render_physical_uses_true_width(self):
        route = MetalRoute(points=((0.0, 0.0), (12.0, 0.0)), width=0.5, render_physical=True)
        assert route.geometry_2d()["stroke_width"] == pytest.approx(0.5)

    def test_heater_pad_ports_stay_physical_draw_schematic(self):
        heater = HeaterPad(heater_length=20.0, heater_width=1.0, contact_width=4.0, contact_height=6.0)
        assert heater.ports()["e1"].center.x == pytest.approx(-14.0)
        stripe = _first_rect(heater.geometry_2d())
        assert stripe["w"] == pytest.approx(36.0)
        assert stripe["h"] == pytest.approx(4.0)
        assert heater.physical_spec()["resistance_ohms"] == pytest.approx(360.0)

    def test_heater_pad_render_physical_uses_true_sizes(self):
        heater = HeaterPad(heater_length=20.0, heater_width=1.0, contact_width=4.0, contact_height=6.0, render_physical=True)
        stripe = _first_rect(heater.geometry_2d())
        assert stripe["w"] == pytest.approx(20.0)
        assert stripe["h"] == pytest.approx(1.0)

class TestPackagingRegistryMetadata:
    @pytest.mark.parametrize(
        "name",
        ["ElectricalPad", "GSGProbePad", "MetalRoute", "HeaterPad"],
    )
    def test_packaging_components_expose_schematic_contract(self, name: str):
        spec = component_registry()[name]
        assert spec.schematic_default is True
        assert spec.supports_render_physical is True
        assert spec.supports_physical_spec is True
        info = describe_physics_support(name)
        assert info["schematic_default"] is True
        assert info["supports_render_physical"] is True
