"""The package set: wire bonds, a fibre array, an edge-launch SMA jack and a plain board.

A wire bond is a route kind: an arc from pad to pad in 2D, a gold loop from pad top to pad top in 3D, an electrical
link in 1D. The fibre array and the SMA jack are parts with ports on their 1D and 2D art, a clean 3D model and a
catalog entry that saves and loads. A plain board draws its outline in its own colour and its edge pads, no traces.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

import optodraw
from optodraw import ChipSubstrate, ElectricalPad, PCB, Scene, WireBond, check_part_3d
from optodraw.catalog import describe_component, list_components
from optodraw.check import solid_boxes
from optodraw.registry import build_component
from optodraw.symbols import lookup
from optodraw.symbols.art import _symbol_box, art_2d, symbol_for_2d
from optodraw.symbols.build import BORDER_PT, PT_TO_BP
from optodraw.symbols.schematic import build_schematic

PARTS = {"FiberArray": ({f"o{i}" for i in range(1, 9)}, "fiber"), "SMAConnector": ({"e1"}, "electrical")}
SIZES = [("FiberArray", {}), ("FiberArray", {"count": 4, "pitch": 0.5}), ("SMAConnector", {})]


def _bonded(chip: bool = False):
    """Two pads and a bond from the first to the second; on a die when ``chip``, so the 3D page lifts the pads."""

    scene = Scene(width=80, height=50, platform="mixed")
    if chip:
        scene.add(ChipSubstrate(center=(-10, 4), length=40, width=20, label="PIC"))
    a = scene.add(ElectricalPad(center=(-8, 3), width=3.2, height=3.2, label="A"))
    b = scene.add(ElectricalPad(center=(-22, 5), width=3.2, height=3.2, label="B"))
    return scene, a, b, scene.route((a, "e1"), (b, "e1"), kind="wirebond")


def _top(geometry: dict) -> float:
    return max(box[1][1] for _, box in solid_boxes(geometry))


# ---------------------------------------------------------------- wire bond
def test_a_wire_bond_is_an_arc_from_pad_port_to_pad_port():
    # mutant: return _sample_quadratic_bezier(...) without start from WireBond.arc: the arc begins off the first pad
    _, a, b, bond = _bonded()
    assert isinstance(bond, WireBond) and bond.kind == "electrical"
    assert (bond.color, bond.width) == ("#d4af37", 0.25)
    points = [(float(p[0]), float(p[1])) for p in bond.resolve_points()]
    for end, pad in ((points[0], a), (points[-1], b)):
        port = pad.world_port("e1").center
        assert end == pytest.approx((port.x, port.y), abs=1e-9)
    (x0, y0), (x1, y1) = points[0], points[-1]
    span = math.hypot(x1 - x0, y1 - y0)
    left = [((x - x0) * -(y1 - y0) + (y - y0) * (x1 - x0)) / span for x, y in points]
    assert all(d >= -1e-9 for d in left)                       # the whole arc bulges to one side
    assert max(left) == pytest.approx(WireBond.BULGE * span, rel=1e-3)


def test_the_3d_wire_runs_from_pad_top_to_pad_top_and_loops_over_them():
    # mutant: h0, h1 = 0.0, 0.0 in WireBond.geometry_3d: the wire starts on the table under the pads
    _, a, b, bond = _bonded()
    tube = bond.geometry_3d()
    assert tube["shape"] == "tube_path" and tube["material"]["metalness"] == pytest.approx(0.9)
    for point, pad in ((tube["points"][0], a), (tube["points"][-1], b)):
        port = pad.world_port("e1").center
        assert point == pytest.approx([port.x, _top(pad.geometry_3d()), -port.y], abs=1e-9)
    (x0, _, z0), (x1, _, z1) = tube["points"][0], tube["points"][-1]
    rise = max(p[1] for p in tube["points"]) - _top(a.geometry_3d())
    assert rise == pytest.approx(WireBond.LOOP * math.hypot(x1 - x0, z1 - z0), rel=1e-6)


def test_in_the_3d_page_the_wire_lands_on_the_pads_as_the_page_draws_them():
    """On a die the page lifts each pad onto the pad layer of the stack and draws it taller: the wire follows."""

    # mutant: node.geometry_3d() for node.geometry_3d(self._geometry_3d) in threejs_renderer: the wire ends under the pads
    from optodraw.renderers.threejs_renderer import ThreeJsRenderer

    scene, *_ = _bonded(chip=True)
    items = ThreeJsRenderer(scene)._collect_scene_data()
    pads = {item["label"]: item for item in items if item.get("label") in ("A", "B")}
    wire = next(item for item in items if item.get("geometry", {}).get("shape") == "tube_path")
    for point, name in ((wire["geometry"]["points"][0], "A"), (wire["geometry"]["points"][-1], "B")):
        assert point[1] == pytest.approx(_top(pads[name]["geometry"]), abs=1e-9), name
    assert wire.get("zScale") == pads["A"].get("zScale") and wire.get("chip") == pads["A"].get("chip")


def test_a_wire_bond_saves_and_loads_as_a_wire_bond():
    # mutant: return route.kind from schema._spec_kind: the bond loads as a straight electrical route
    scene, _, _, bond = _bonded()
    spec = scene.to_spec()
    assert [route["kind"] for route in spec["routes"]] == ["wirebond"]
    again = next(node for node in Scene.from_spec(spec).walk() if isinstance(node, WireBond))
    assert np.asarray(again.resolve_points(), float) == pytest.approx(np.asarray(bond.resolve_points(), float))


def test_a_wire_bond_is_an_electrical_link_in_1d():
    # mutant: kwargs["kind"] = "wirebond" in WireBond.__init__: the 1D view draws the bond as light
    scene, *_ = _bonded()
    assert [(link.kind, link.electrical) for link in build_schematic(scene).links] == [("electrical", True)]


# ---------------------------------------------------------------- fibre array, SMA jack
@pytest.mark.parametrize("name", PARTS)
def test_a_package_part_is_in_the_catalog_with_its_ports(name):
    # mutant: register FiberArray with "category": "optics" in _BUILTIN_METADATA (optodraw/registry.py)
    names, kind = PARTS[name]
    assert name in list_components(category="electronics")
    assert describe_component(name)["category"] == "electronics"
    ports = build_component(name).ports()
    assert set(ports) == names and {port.kind for port in ports.values()} == {kind}


@pytest.mark.parametrize("name", PARTS)
def test_the_1d_symbol_is_exact_and_carries_the_ports(name):
    # mutant: delete both FiberArray rows from variants.toml and rebuild: no prebuilt symbol stands for the array
    names, kind = PARTS[name]
    symbol = lookup(build_component(name))
    assert symbol.exact and symbol.source == "prebuilt", name
    assert {port: mark.kind for port, mark in symbol.ports.items()} == dict.fromkeys(names, kind)


@pytest.mark.parametrize("name", PARTS)
def test_each_port_of_the_1d_symbol_lies_on_the_edge_of_the_drawing(name):
    # mutant: \odport[fiber]{o\odi}{0.6,\ody} in pics/od fiberarray (od-package.tex), rebuild: the ports sit in the lid
    symbol = lookup(build_component(name))
    edge = BORDER_PT * PT_TO_BP + 0.6           # the frame's border, and half a line with its round cap
    for port in symbol.ports.values():
        gap = {"left": port.x, "right": symbol.width - port.x, "top": port.y, "bottom": symbol.height - port.y}
        assert gap[port.side] <= edge, (name, port.name, gap[port.side])


@pytest.mark.parametrize("name, size", SIZES)
def test_the_2d_art_draws_each_port_where_the_part_has_it(name, size):
    # mutant: delete SMAConnector.symbol_2d: the 2D draws the IEC line symbol, with no paint
    part = build_component(name, **size)
    art, symbol = art_2d(part), symbol_for_2d(part)
    assert art is not None and "Gradient" in art["svg"], name
    a, b, c, d, e, f = art["matrix"]
    for port_name, port in part.ports().items():
        mark = symbol.ports[port_name]
        drawn = (a * mark.x + c * mark.y + e, -(b * mark.x + d * mark.y + f))
        assert drawn == pytest.approx((port.center.x, port.center.y), abs=1e-3 * art["pic"]["scale"]), port_name


@pytest.mark.parametrize("name, size", SIZES)
def test_the_2d_art_and_the_3d_model_are_one_plan(name, size):
    """The drawing (its frame less the border) covers what the 3D model covers seen from above, to half a line."""

    # mutant: FiberArray.LENGTH = 10.0 in packaging.py: the block in 3D is shorter than its drawing
    part = build_component(name, **size)
    art = art_2d(part)
    scale = art["pic"]["scale"]
    x0, y0, x1, y1 = _symbol_box(art["matrix"], art["size"])
    border = BORDER_PT * PT_TO_BP * scale
    boxes = [box for _, box in solid_boxes(part.geometry_3d())]
    model = (min(b[0][0] for b in boxes), min(-b[2][1] for b in boxes), max(b[0][1] for b in boxes),
             max(-b[2][0] for b in boxes))
    assert (x0 + border, y0 + border, x1 - border, y1 - border) == pytest.approx(model, abs=0.6 * scale)


@pytest.mark.parametrize("name", PARTS)
def test_the_3d_model_has_no_loose_solid_and_rests_flat(name):
    # mutant: post_at under the middle of the SMA barrel: the post meets a round face, not the flange
    part = build_component(name)
    assert part.geometry_3d()["children"]
    assert check_part_3d(part) == []


def test_the_sma_pin_lies_on_the_top_of_the_board():
    # mutant: return BOARD_THICKNESS from SMAConnector.axis: the pin sinks half into the board
    pin = next(s for s in optodraw.SMAConnector().geometry_3d()["children"] if s["role"] == "centre pin")
    board = PCB().geometry_3d()["children"][0]
    assert pin["position"][1] - pin["radius"] == pytest.approx(board["position"][1] + board["height"] / 2.0)


@pytest.mark.parametrize("name, size", SIZES)
def test_a_part_saves_and_loads_with_its_size_and_place(name, size):
    # mutant: drop "pitch" from the FiberArray row of _BUILTIN_METADATA: the loaded array takes the default pitch
    scene = Scene(width=120, height=80, platform="mixed")
    part = scene.add(build_component(name, center=(10, 5), angle=90, label="X", **size))
    again = next(item for item in Scene.from_spec(scene.to_spec()).walk() if type(item).__name__ == name)
    assert again.label == "X"
    for port_name, port in part.world_ports().items():
        moved = again.world_ports()[port_name]
        assert (moved.center.x, moved.center.y) == pytest.approx((port.center.x, port.center.y))


# ---------------------------------------------------------------- plain board
def test_a_plain_board_draws_its_outline_in_its_colour_and_its_edge_pads_only():
    # mutant: drop the plain branch of PCB.geometry_2d: the plain board keeps its traces and vias
    board = PCB(style="plain", color="#1e5a8a", pad_count=4)
    assert art_2d(board) is None
    shapes = board.geometry_2d()["children"]
    assert [shape["type"] for shape in shapes] == ["rect"] * (1 + 2 * 4)
    assert shapes[0]["fill"] == "#1e5a8a"
    assert len(PCB(pad_count=4).geometry_2d()["children"]) > len(shapes)      # the default keeps its traces and vias


def test_a_plain_board_in_3d_has_its_pads_on_top_and_no_traces():
    # mutant: z_offset=0.64 for every pad in PCB.geometry_3d: the plain board's pads sink into it
    board, *pads = PCB(style="plain", pad_count=4).geometry_3d()["children"]
    assert len(pads) == 2 * 4
    top = board["position"][1] + board["height"] / 2.0
    assert all(pad["position"][1] - pad["height"] / 2.0 == pytest.approx(top) for pad in pads)
    assert check_part_3d(PCB(style="plain")) == []


def test_a_plain_board_has_a_plain_1d_symbol():
    # mutant: delete the pcb kind = "plain" row from variants.toml and rebuild: the board with traces stands in
    symbol = lookup(PCB(style="plain"))
    assert symbol.exact and symbol.source == "prebuilt" and symbol.params == {"kind": "plain"}
    assert lookup(PCB()).params == {}


def test_a_plain_board_saves_and_loads_with_its_style_and_colour():
    # mutant: drop "style" from the PCB row of _BUILTIN_METADATA: the board loads with its traces again
    scene = Scene(width=120, height=80, platform="mixed")
    scene.add(PCB(style="plain", color="#1e5a8a"))
    again = next(item for item in Scene.from_spec(scene.to_spec()).walk() if type(item).__name__ == "PCB")
    assert (again.style, again.color) == ("plain", "#1e5a8a")
    with pytest.raises(ValueError, match="plain"):
        PCB(style="fancy")
