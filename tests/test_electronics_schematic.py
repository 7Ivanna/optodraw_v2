"""Tests for schematic-first electronics and packaging components."""

from __future__ import annotations

import pytest

from optodraw import HeaterPad, MetalRoute


def _first_rect(geometry: dict) -> dict:
    for child in geometry.get("children", []):
        if child.get("type") == "rect":
            return child
    raise AssertionError("expected a rect child in geometry group")


class TestPackagingSchematicDefaults:


    def test_metal_route_ports_stay_physical_draw_schematic(self):
        route = MetalRoute(points=((0.0, 0.0), (12.0, 0.0)), width=0.5, thickness=0.05)
        assert route.ports()["e2"].center.x == pytest.approx(12.0)
        assert route.geometry_2d()["stroke_width"] == pytest.approx(1.6)
        assert route.geometry_2d()["stroke_width"] > route.width
        assert route.physical_spec()["resistance_ohms"] == pytest.approx(1.92)


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

