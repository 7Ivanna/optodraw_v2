"""Circuit figures: an op amp has its supply pins, a placed circuit keeps its plan in 1D on any scene, and a bench
photodiode has both of its contacts (anode and cathode) in 1D."""

from __future__ import annotations

import pytest

from optodraw import (Beam, Capacitor, ElectricalPad, Ground, Laser, OnChipPhotodetector, OpAmp, Photodiode, Resistor,
                      Scene)
from optodraw.symbols import lookup
from optodraw.symbols.schematic import build_schematic, link_crossings

SUPPLY = {"v_pos": (90.0, "top"), "v_neg": (-90.0, "bottom")}       # V+ up, V- down: the part and its 1D symbol


def test_an_op_amp_has_two_supply_pins_on_the_part_and_on_its_1d_symbol():
    # mutant: drop "v_neg" from OpAmp.PORTS (circuit.py) and from pics/od opamp (od-circuit.tex), rebuild
    amp = OpAmp()
    ports = amp.ports()
    assert set(ports) == {"in_n", "in_p", "out", *SUPPLY}
    for name, (facing, _) in SUPPLY.items():
        assert ports[name].kind == "electrical" and ports[name].orientation_deg == facing, name
    symbol = lookup(amp)
    assert symbol.exact and symbol.source == "prebuilt"
    assert {name: (symbol.ports[name].kind, symbol.ports[name].side) for name in SUPPLY} == {
        name: ("electrical", side) for name, (_, side) in SUPPLY.items()}


def _tia(platform: str) -> Scene:
    """The transimpedance amplifier of the docs, placed by hand in 2D: no two parts overlap."""

    scene = Scene(title="TIA", platform=platform)
    amp = scene.add(OpAmp(center=(0, 0), label="TIA"))
    r_f = scene.add(Resistor(center=(0, 9), label="R_f", value="10 kΩ"))
    c_f = scene.add(Capacitor(center=(0, 15), label="C_f", value="0.2 pF"))
    ground = scene.add(Ground(center=(-13, -7)))
    pd = scene.add(OnChipPhotodetector(center=(-62, 0), label="PD"))
    bias = scene.add(ElectricalPad(center=(-42.2, 19), width=6, height=6, label="V_{bias}"))
    out = scene.add(ElectricalPad(center=(28, 0), width=6, height=6, label="V_{out}"))
    for a, b in (((pd, "e1"), (bias, "e1")), ((pd, "e2"), (amp, "in_n")), ((r_f, "e1"), (amp, "in_n")),
                 ((c_f, "e1"), (r_f, "e1")), ((r_f, "e2"), (amp, "out")), ((c_f, "e2"), (r_f, "e2")),
                 ((amp, "in_p"), (ground, "e1")), ((amp, "out"), (out, "e1"))):
        scene.route(a, b, kind="electrical", width=0.5)
    scene.fit_frame(margin=4)
    return scene


@pytest.mark.parametrize("platform", ["electronics", "mixed", "free_space"])
def test_a_placed_circuit_keeps_its_wires_uncrossed_in_1d_on_any_scene(platform):
    """The 1D view kept the 2D plan of a circuit only on an on_chip scene; elsewhere it arranged the parts itself
    and the feedback wires crossed five times."""

    # mutant: in _build (schematic.py) take the automatic arrangement whenever the platform is not on_chip
    schematic = build_schematic(_tia(platform))
    assert len(schematic.links) == 8 and len(schematic.routes) == 8
    assert link_crossings(schematic) == 0


def test_a_bench_photodiode_has_both_contacts_in_1d_and_light_still_enters_by_its_window():
    # mutant: delete the second \odport[electrical] from pics/od detector (od-instruments.tex), rebuild
    pd = Photodiode()
    contacts = {name for name, port in pd.ports().items() if port.kind == "electrical"}
    assert len(contacts) == 2, contacts                                  # the anode and the cathode
    symbol = lookup(pd)
    assert symbol.exact and symbol.source == "prebuilt"
    assert {name for name, mark in symbol.ports.items() if mark.kind == "electrical"} == contacts
    assert {symbol.ports[name].side for name in contacts} == {"top", "bottom"}    # one on each lead of the diode

    bench = Scene(platform="free_space")
    laser = bench.add(Laser(center=(-60, 0)))
    pd = bench.add(Photodiode(center=(40, 0)))
    beam = bench.add(Beam.through(laser, pd))
    assert beam.anchors[-1][1] == "in"                                   # a beam never ends on a contact
