"""The fibre polarization controller: a fibre wound on paddles, fibre in and fibre out."""

from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

import optodraw
from optodraw.registry import build_component, component_registry
from optodraw.symbols import lookup


def _shapes(geometry: dict, key: str, kind: str) -> list[dict]:
    found = [geometry] if geometry.get(key) == kind else []
    for child in geometry.get("children", []):
        found.extend(_shapes(child, key, kind))
    return found


def test_it_is_a_fibre_part_with_a_fibre_port_at_each_end():
    part = optodraw.PolarizationController(length=60)
    ports = part.ports()
    assert set(ports) == {"in", "out"}
    assert ports["in"].kind == ports["out"].kind == "fiber"
    assert (ports["in"].center.x, ports["in"].orientation_deg) == (-30.0, 180.0)
    assert (ports["out"].center.x, ports["out"].orientation_deg) == (30.0, 0.0)
    assert ports["in"].center.y == ports["out"].center.y == 0.0


def test_it_is_in_the_catalog():
    spec = component_registry()["PolarizationController"]
    assert (spec.category, spec.platform) == ("optics", "free_space")
    part = build_component("PolarizationController", paddles=2, label="PC")
    assert part.paddles == 2 and part.label == "PC"


@pytest.mark.parametrize("paddles", [1, 3, 4])
def test_the_drawing_has_one_loop_for_each_paddle(paddles):
    part = optodraw.PolarizationController(paddles=paddles)
    loops = [shape for shape in _shapes(part.geometry_2d(), "type", "circle") if shape.get("fill") == "none"]
    assert len(loops) == paddles
    assert len(_shapes(part.geometry_3d(), "shape", "torus")) == paddles


def test_it_refuses_a_controller_with_no_paddle():
    with pytest.raises(ValueError, match="paddles"):
        optodraw.PolarizationController(paddles=0)


def test_it_draws_in_every_renderer_and_carries_a_fibre():
    scene = optodraw.Scene(width=260, height=120, platform="on_chip")
    controller = scene.add(optodraw.PolarizationController(center=(-60, 0), label="PC"))
    coupler = scene.add(optodraw.EdgeCoupler(center=(60, 0), label="EC"))
    scene.route((controller, "out"), (coupler, "f1"), kind="fiber")
    assert "<svg" in scene.render_svg().as_svg()
    assert "tikzpicture" in scene.render_tikz()
    assert "PolarizationController" in scene.render_threejs() or "torus" in scene.render_threejs()
    data = controller.to_dict()
    assert data["type"] == "PolarizationController" and data["paddles"] == 3


def test_its_1d_symbol_is_three_loops_on_a_fibre():
    part = optodraw.PolarizationController()
    symbol = lookup(part)
    assert (symbol.name, symbol.source, symbol.exact) == ("polcontroller", "prebuilt", True)
    assert {name: port.kind for name, port in symbol.ports.items()} == {"in": "fiber", "out": "fiber"}
    assert symbol.ports["in"].side == "left" and symbol.ports["out"].side == "right"
    assert symbol.ports["in"].y == symbol.ports["out"].y                 # the fibre runs straight through
    ET.fromstring(symbol.svg)
    assert lookup(optodraw.PolarizationController(paddles=2)).params == {"count": 2}
