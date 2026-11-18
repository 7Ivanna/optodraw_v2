"""A wire meets the part it ends at: the 2D art draws each electrical port within 0.5 scene units of the port the
wire ends at, a route across a part is found on every platform, a die draws over its board, and the parts a figure
wires (a laser, a photodiode, a sample, a cryostat, an FPGA board) have the ports to wire.

Mutants (each one fails a test here):
- in ``fit_art``, let a part with only wires take the size rule, and drop ``_art_scale_from_ports`` from
  MEMSActuator: its art stops 22 units short of e2.
- put RFDriver's bias back at (0, width / 2): it misses the lead of the art by 4 units.
- raise ``PORT_TOLERANCE`` in optodraw/symbols/art.py to 5: the wire to a moved port is no longer found.
- put the "runs over" loop of check_figure back under ``platform == "on_chip"``: mixed and free_space pass silently.
- drop the ``_holds`` test in ``_runs_over``: a wire from a part on a board "runs over" the board.
- take "PCB" out of ``_CARRIERS`` in svg_renderer.py: a die added before its board draws under it.
- drop e1 from Laser.ports: the laser has no port to wire.
"""

from __future__ import annotations

import pytest

import optodraw
from optodraw import ADCBlock, ChipSubstrate, DAC, ElectricalPad, PCB, Scene, check_figure
from optodraw.core.ports import Port
from optodraw.core.routing import Route
from optodraw.core.transform import Vec3
from optodraw.renderers.svg_renderer import SvgRenderer
from optodraw.symbols.art import PORT_TOLERANCE, port_gaps

WIRED = [
    optodraw.MEMSActuator(), optodraw.RFDriver(), optodraw.DAC(), optodraw.ADCBlock(), optodraw.DAQ(),
    optodraw.RFDriver(length=60.0), optodraw.ADCBlock(visual_scale=2.0),
    optodraw.FPGABoard(), optodraw.Laser(), optodraw.Laser(sync=True), optodraw.Laser(box_size=9.0),
    optodraw.Photodiode(), optodraw.Sample(), optodraw.Sample(in_cryostat=True), optodraw.Cryostat(),
    optodraw.Cryostat(with_sample=False, radius=20.0),
]


@pytest.mark.parametrize("part", WIRED, ids=lambda part: type(part).__name__)
def test_the_art_draws_every_electrical_port_where_the_wire_ends(part):
    gaps = port_gaps(part)
    electrical = {name for name, port in part.ports().items() if port.kind == "electrical"}
    assert electrical <= set(gaps), "the 2D art lacks a port: rebuild the symbols (python -m optodraw.symbols.build)"
    assert max(gaps.values()) <= PORT_TOLERANCE, gaps


@pytest.mark.parametrize("name", ["Laser", "Photodiode", "Sample", "Cryostat"])
def test_a_source_a_detector_and_a_sample_take_a_wire(name):
    port = getattr(optodraw, name)().ports()["e1"]
    assert port.kind == "electrical"


def test_an_fpga_board_has_an_io_port_beside_each_header_pin():
    ports = optodraw.FPGABoard().ports()
    assert [f"io{i}" for i in range(1, 11)] == list(ports)
    assert {round(float(p.center.x)) for p in ports.values()} == {-10, 10}
    assert len({round(float(p.center.y), 3) for p in ports.values()}) == 5


class _MovedPort(DAC):
    """A DAC whose din moved 2 units off the lead its art draws."""

    component_type = "DAC"                           # painted with the DAC's art

    def ports(self):
        ports = super().ports()
        din = ports["din"]
        ports["din"] = Port("din", Vec3(float(din.center.x), float(din.center.y) + 2.0, 0.0),
                            orientation_deg=180.0, width=din.width, kind="electrical")
        return ports


def test_a_wire_to_a_port_the_art_misses_is_found():
    scene = Scene(title="x", width=200, height=80, platform="mixed")
    pad = scene.add(ElectricalPad(center=(-60, 0), width=9, height=9, angle=180))
    dac = scene.add(_MovedPort(center=(0, 0), label="DAC"))
    scene.route((pad, "e1"), (dac, "din"), kind="electrical", width=0.5)
    assert 1.5 < port_gaps(dac)["din"] < 2.5
    assert [f for f in check_figure(scene, view="2d") if "ends in the air" in f and "DAC:din" in f]


def test_a_wire_to_a_part_whose_art_meets_it_is_not_found():
    scene = Scene(title="x", width=200, height=80, platform="mixed")
    pad = scene.add(ElectricalPad(center=(-60, 0), width=9, height=9, angle=180))
    dac = scene.add(DAC(center=(0, 0), label="DAC"))
    scene.route((pad, "e1"), (dac, "din"), kind="electrical", width=0.5)
    assert not [f for f in check_figure(scene, view="2d") if "ends in the air" in f]


def _straight_across(scene, a, b):
    return scene.add(Route([(-55.5, 0.0), (55.5, 0.0)], kind="electrical", width=0.7, start_component=a,
                           start_port="e1", end_component=b, end_port="e1"))


@pytest.mark.parametrize("platform", ["on_chip", "mixed", "free_space"])
def test_a_route_across_a_part_is_found_on_every_platform(platform):
    scene = Scene(title="x", width=200, height=80, platform=platform)
    a = scene.add(ElectricalPad(center=(-60, 0), width=9, height=9, angle=180))
    scene.add(ADCBlock(center=(0, 0), label="ADC", label_side="bottom"))
    b = scene.add(ElectricalPad(center=(60, 0), width=9, height=9))
    _straight_across(scene, a, b)
    assert [f for f in check_figure(scene, view="2d") if "runs over ADC" in f]


def test_a_wire_from_a_part_on_a_board_does_not_run_over_the_board():
    scene = Scene(title="x", width=200, height=120, platform="mixed")
    scene.add(PCB(center=(0, 0), length=160.0, width=100.0, label="board"))
    a = scene.add(ElectricalPad(center=(-60, 0), width=9, height=9, angle=180))
    b = scene.add(ElectricalPad(center=(60, 0), width=9, height=9))
    _straight_across(scene, a, b)
    assert not [f for f in check_figure(scene, view="2d") if "runs over" in f]


def test_a_die_added_before_its_board_draws_over_it():
    scene = Scene(title="", width=120, height=80, platform="mixed")
    die = scene.add(ChipSubstrate(center=(0, 0), length=30, width=20))
    board = scene.add(PCB(center=(0, 0)))
    svg = SvgRenderer(scene, editable=True, component_ids={id(die): "die", id(board): "board"}).render().as_svg()
    assert svg.index('data-component-id="board"') < svg.index('data-component-id="die"')
