"""The circuit set: resistor, capacitor, inductor, op amp, ground, bias tee, RF mixer, amplifier and filter.

Each part is its IEC 60617 symbol in 1D and 2D with a port at the end of each lead, a real package in 3D (a ground
has no solid), a catalog entry that saves and loads, and a value printed after its label.
"""

from __future__ import annotations

import pytest

import optodraw
from optodraw import Scene, check_part_3d
from optodraw.catalog import describe_component, list_components
from optodraw.core.markup import runs
from optodraw.registry import build_component
from optodraw.symbols import lookup
from optodraw.symbols.art import art_2d
from optodraw.symbols.build import BORDER_PT, PT_TO_BP

CIRCUIT = {
    "Resistor": {"e1", "e2"},
    "Capacitor": {"e1", "e2"},
    "Inductor": {"e1", "e2"},
    "OpAmp": {"in_n", "in_p", "out", "v_pos", "v_neg"},
    "Ground": {"e1"},
    "BiasTee": {"rf", "rf_dc", "dc"},
    "RFMixer": {"rf", "if", "lo"},
    "Amplifier": {"in", "out"},
    "RFFilter": {"in", "out"},
}


@pytest.mark.parametrize("name", CIRCUIT)
def test_a_circuit_part_is_in_the_catalog_with_electrical_ports(name):
    # mutant: register Resistor with "category": "misc" in _BUILTIN_METADATA (optodraw/registry.py)
    assert name in list_components(category="electronics")
    assert describe_component(name)["category"] == "electronics"
    ports = build_component(name).ports()
    assert set(ports) == CIRCUIT[name]
    assert {port.kind for port in ports.values()} == {"electrical"}


@pytest.mark.parametrize("name", CIRCUIT)
def test_the_1d_symbol_is_exact_and_carries_the_ports(name):
    # mutant: delete the Resistor row from optodraw/symbols/variants.toml and rebuild: the labelled block stands in
    symbol = lookup(build_component(name))
    assert symbol.exact and symbol.source == "prebuilt", name
    assert {port: mark.kind for port, mark in symbol.ports.items()} == dict.fromkeys(CIRCUIT[name], "electrical")


@pytest.mark.parametrize("name", CIRCUIT)
def test_each_port_of_the_1d_symbol_is_the_end_of_a_lead(name):
    """Nothing is drawn past a port: it lies on the edge of the drawing that its lead leaves through."""

    # mutant: \odport[electrical]{e2}{0.3,0} in pics/od resistor (od-circuit.tex), rebuild: e2 sits inside the box
    symbol = lookup(build_component(name))
    edge = BORDER_PT * PT_TO_BP + 0.6           # the frame's border, and half a line with its round cap
    for port in symbol.ports.values():
        gap = {"left": port.x, "right": symbol.width - port.x, "top": port.y, "bottom": symbol.height - port.y}
        assert gap[port.side] <= edge, (name, port.name, gap[port.side])


@pytest.mark.parametrize("length", [None, 30.0])
@pytest.mark.parametrize("name", CIRCUIT)
def test_the_2d_art_ends_each_lead_on_its_port_at_the_scale_of_the_plan(name, length):
    """A wire to a port meets the drawn lead. The art draws one symbol centimetre as one ``unit``, so every circuit
    part of a figure keeps the proportions of its plan."""

    # mutant: Resistor.PORTS e2 at (0.4, 0.0, 0.0) in circuit.py: the art shrinks to 0.9 of the plan
    part = build_component(name) if length is None else build_component(name, length=length)
    art, symbol = art_2d(part), lookup(part)
    assert art is not None, name
    assert art["pic"]["scale"] == pytest.approx(part.unit * 2.54 / 72.0, rel=1e-3)
    a, b, c, d, e, f = art["matrix"]
    for port_name, port in part.ports().items():
        mark = symbol.ports[port_name]
        x, y = a * mark.x + c * mark.y + e, b * mark.x + d * mark.y + f
        assert (x, -y) == pytest.approx((port.center.x, port.center.y), abs=0.01 * part.unit), port_name


@pytest.mark.parametrize("name", sorted(set(CIRCUIT) - {"Ground"}))
def test_the_3d_package_has_no_loose_solid_and_rests_flat(name):
    # mutant: put the caps of _chip_3d at side * length (off the body): a cap hangs in the air
    part = build_component(name)
    assert part.geometry_3d()["children"]
    assert check_part_3d(part) == []


def test_a_ground_is_a_symbol_with_no_solid():
    # mutant: return Resistor().geometry_3d() from Ground.geometry_3d
    ground = optodraw.Ground()
    assert ground.geometry_3d() == {}
    assert check_part_3d(ground) == []


@pytest.mark.parametrize("name", CIRCUIT)
def test_a_part_saves_and_loads_with_its_value_size_and_place(name):
    # mutant: drop "value" from the Resistor row of _BUILTIN_METADATA: the loaded part prints no value
    # mutant: delete CircuitPart._saved_params: the loaded part prints the value twice
    scene = Scene(width=120, height=80)
    part = scene.add(build_component(name, center=(10, 5), angle=90, length=20.0, value="10 kΩ", label="X_1"))
    again = next(item for item in Scene.from_spec(scene.to_spec()).walk() if type(item).__name__ == name)
    assert (again.label, again.value, again.length) == ("X_1 = 10 kΩ", "10 kΩ", 20.0)
    for port_name, port in part.world_ports().items():
        moved = again.world_ports()[port_name]
        assert (moved.center.x, moved.center.y) == pytest.approx((port.center.x, port.center.y))


def test_the_value_prints_after_the_label_with_markup():
    # mutant: return self.designator from CircuitPart.label: the value is not printed
    resistor = optodraw.Resistor(label="R_f", value="10 kΩ")
    assert [(run.text, run.script) for run in runs(resistor.label)] == [("R", ""), ("f", "sub"), (" = 10 kΩ", "")]
    scene = Scene(width=60, height=30)
    scene.add(resistor)
    assert "10 kΩ" in scene.render_svg().as_svg()
    resistor.label = "R_g"                       # the editor renames the part: the value stays
    assert resistor.label == "R_g = 10 kΩ"
    assert optodraw.Capacitor(value="1 pF").label == "1 pF"
