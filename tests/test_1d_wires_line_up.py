"""A circuit's 1D view lines its parts up as an electronic drawing does: each wire runs straight, or turns once
where its two ports are square to each other, or makes one U where they face the same way. No wire steps
sideways between two runs in one direction (a dogleg)."""

import runpy
from dataclasses import replace
from pathlib import Path

from optodraw import presets
from optodraw.check import _hits
from optodraw.symbols import schematic as one_d

from optodraw import (ADCBlock, Capacitor, ChipSubstrate, DAC, ElectricalPad, FPGABoard, Ground, OnChipPhotodetector,
                      OpAmp, PNMicroringModulator, RFDriver, Resistor, Scene, SMU, TIABlock, VerticalGratingCoupler)
from optodraw.symbols.schematic import build_schematic, link_ends, link_path

DOCS_TIA = Path(__file__).resolve().parents[1] / "docs" / "examples" / "electronics" / "02-tia.py"


def _tia_circuit():
    """The TIA circuit of a two-panel figure: a photodiode on a chip, biased from a pad, read by an op amp."""

    scene = Scene(title="TIA circuit", width=120, height=80, platform="on_chip")
    amp = scene.add(OpAmp(center=(0, 0), label="TIA"))
    r_f = scene.add(Resistor(center=(0, 9), label="R_f"))
    c_f = scene.add(Capacitor(center=(0, 15), label="C_f"))
    ground = scene.add(Ground(center=(-13, -7)))
    diode = scene.add(OnChipPhotodetector(center=(-62, 0), label="PD"))
    bias = scene.add(ElectricalPad(center=(-42.2, 19), width=6, height=6, label="V_{bias}"))
    out = scene.add(ElectricalPad(center=(28, 0), width=6, height=6, label="V_{out}"))
    for a, b in (((diode, "e1"), (bias, "e1")), ((diode, "e2"), (amp, "in_n")), ((r_f, "e1"), (amp, "in_n")),
                 ((c_f, "e1"), (r_f, "e1")), ((r_f, "e2"), (amp, "out")), ((c_f, "e2"), (r_f, "e2")),
                 ((amp, "in_p"), (ground, "e1")), ((amp, "out"), (out, "e1"))):
        scene.route(a, b, kind="electrical")
    scene.fit_frame(margin=4)
    return scene


def _docs_tia():
    return runpy.run_path(str(DOCS_TIA))["scene"]


def _chain():
    """A drive and readout chain: an FPGA drives a ring through a DAC and a driver, a photodiode reads it back."""

    wire = dict(kind="electrical", path_type="L", width=0.7)
    scene = Scene(title="Drive and readout", width=400, height=130, platform="mixed")
    scene.add(ChipSubstrate(center=(40, -3), length=152, width=74, label="PIC", label_side="bottom"))
    fpga = scene.add(FPGABoard(center=(-160, 6), label="FPGA", label_side="bottom"))
    dac = scene.add(DAC(center=(-125, 6), label="DAC", label_side="bottom"))
    drv = scene.add(RFDriver(center=(-80, 9.5), label="Driver", label_side="bottom"))
    ring = scene.add(PNMicroringModulator(center=(30, 0), with_heater=False, label="Ring", label_side="right"))
    gc = scene.add(VerticalGratingCoupler(center=(-14, -12.2), angle=180, label="Fibre in", label_side="bottom"))
    pad_s = scene.add(ElectricalPad(center=(20, 28), width=9, height=9, angle=90, label="S", label_side="left"))
    pad_g = scene.add(ElectricalPad(center=(40, 28), width=9, height=9, angle=90, label="G", label_side="right"))
    pd = scene.add(OnChipPhotodetector(center=(87, -12.2), label="PD", label_side="bottom"))
    smu = scene.add(SMU(center=(135, 34), label="Bias", label_side="right"))
    tia = scene.add(TIABlock(center=(150, -30), label="TIA", label_side="bottom"))
    adc = scene.add(ADCBlock(center=(190, -30), label="ADC", label_side="bottom"))
    for a, b in (((fpga, "io2"), (dac, "din")), ((dac, "out"), (drv, "in")), ((drv, "out_p"), (pad_s, "e1")),
                 ((ring, "e1"), (pad_s, "e1")), ((ring, "e2"), (pad_g, "e1")), ((pd, "e1"), (smu, "hi")),
                 ((pd, "e2"), (tia, "in")), ((tia, "out"), (adc, "in"))):
        scene.route(a, b, **wire)
    scene.route((adc, "dout"), (fpga, "io1"), steps=[{"x": 215}, {"y": -62}, {"x": -180}], **wire)
    scene.route((gc, "o1"), (ring, "o1"), kind="waveguide", path_type="smooth")
    scene.route((ring, "o2"), (pd, "o1"), kind="waveguide", path_type="smooth")
    scene.fit_frame(margin=5)
    return scene


def _fewest(s, n1, e, n2):
    """The corners a wire needs: none between two ports in line that face each other, two (a U) between ports
    that face the same way, one between ports square to each other."""

    if n1 == (-n2[0], -n2[1]):
        offset = abs(e[1] - s[1]) if n1[0] else abs(e[0] - s[0])
        return 0 if offset < 0.5 else 2
    return 1 if n1[0] * n2[0] + n1[1] * n2[1] == 0 else 2


def _doglegs(points):
    """Two runs in one direction joined by a step across."""

    return sum(1 for a, b, c, d in zip(points, points[1:], points[2:], points[3:])
               if abs((b[0] - a[0]) * (d[1] - c[1]) - (b[1] - a[1]) * (d[0] - c[0])) < 1e-6
               and (b[0] - a[0]) * (d[0] - c[0]) + (b[1] - a[1]) * (d[1] - c[1]) > 0)


def _bent(scene, count=8):
    """Each wire of the scene's 1D view that takes more corners than its ports need, or makes a dogleg."""

    schematic = build_schematic(scene)
    wires = [index for index, link in enumerate(schematic.links) if link.electrical]
    assert len(wires) == count
    found = []
    for index in wires:
        link = schematic.links[index]
        points = link_path(schematic, index)
        corners, need = len(points) - 2, _fewest(*link_ends(schematic, link))
        if corners > need or _doglegs(points):
            names = [schematic.items[k].label or schematic.items[k].component.component_type for k in (link.start, link.end)]
            found.append(f"{names[0]}.{link.start_port} -> {names[1]}.{link.end_port}: {corners} corners "
                         f"(fewest {need}), {_doglegs(points)} doglegs")
    return found


def test_the_docs_amplifier_draws_every_wire_straight_or_with_one_turn():
    assert _bent(_docs_tia()) == []


def test_the_two_panel_amplifier_draws_every_wire_straight_or_with_one_turn():
    """The anode wire and the feedback wire meet at the op amp's input: one node, so one may run onto the other."""

    assert _bent(_tia_circuit()) == []


def test_the_chain_runs_its_wires_straight_but_the_long_return_to_the_signal_pad():
    """Pad S joins the driver at one end of the chain and the ring 374 points away: its L needs a step of 35
    points, past the limit, so that wire keeps its jog. The bias contact sits over the photodiode's cathode."""

    assert [wire.split(":")[0] for wire in _bent(_chain(), count=9)] == ["Ring.e1 -> S.e1"]


def _overlaps(schematic):
    boxes = [(i, box) for i, item in enumerate(schematic.items) for box in one_d._boxes(item)]
    return [(p, q) for k, (i, p) in enumerate(boxes) for j, q in boxes[k + 1:]
            if i != j and p[0] < q[2] and q[0] < p[2] and p[1] < q[3] and q[1] < p[3]]


def test_lining_up_never_puts_a_part_or_a_label_on_another():
    """A step that would make a wire straight is not taken where the part or its label would land on another."""

    package = runpy.run_path(str(DOCS_TIA.with_name("03-package.py")))["scene"]
    for scene in (package, presets.ring_resonator_chip()):
        assert _overlaps(build_schematic(scene)) == []


def test_a_part_lined_up_past_the_page_top_still_keeps_the_wires_off_it():
    """The router's grid starts at the page corner: a part above it must come onto the page before the wires
    route, or they run through it."""

    schematic = build_schematic(_docs_tia())
    amp = next(i for i, item in enumerate(schematic.items) if item.component.component_type == "OpAmp")
    items = list(schematic.items)
    lift = -(items[amp].y + 40.0)
    x, baseline, anchor = items[amp].label_at
    items[amp] = replace(items[amp], y=items[amp].y + lift, label_at=(x, baseline + lift, anchor))
    routed = one_d._routed(replace(schematic, items=items, routes={}))
    for index, link in enumerate(routed.links):
        points = routed.routes[index]
        for k, item in enumerate(routed.items):
            inner = (item.x + 0.5, item.y + 0.5, item.x + item.symbol.width - 0.5, item.y + item.symbol.height - 0.5)
            assert k in (link.start, link.end) or not any(_hits(p, q, inner) for p, q in zip(points, points[1:]))
