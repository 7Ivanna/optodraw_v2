"""A wire, a fibre or a beam ends where the part's 2D art draws its port, for every part in the catalog.

The 2D art of a part is its symbol, fitted to the part's ports (optodraw/symbols/art.py). Where the ports and the
pic disagree, the drawing misses a port and the wire or the light ends in the air. On main at b3701d1 35 parts
missed: CameraSensor sync by 7.9 units, SMU lo 3.2, ReceiverMacro clk 4.8, PolarizationController out 20.5,
FourFSystem image 61.

Mutants (each one fails a test here):
- in ``fit_art``, size the art by the symbol's frame with its border again: PolarizationController, Pentaprism
  and BeamExpanderTelescope miss their last port, and a fibre that meets the controller is reported.
- drop the test in ``fit_art`` that keeps a part with only wires out of the size rule: the SMUs here miss lo.
- count the whole distance for a beam port in ``port_gaps``: every thin plate (Polarizer out 2.8) is reported.
- put back any port moved to its pic (EIC vdd at width / 2, Prism ports at size / 2, CameraSensor sync at the back
  of its frame): the catalog test names the part. SMU jacks at 6.6 and 12.2: its panel is drawn 41 units wide.
- take "FourFSystem" out of ``NO_ART``: its image port lies 57 units past its art.
- give TransmitterMacro its old width of 36: check_part_3d finds its bias and gnd tabs in the air.
"""

from __future__ import annotations

import pytest

import optodraw
from optodraw import Scene, check_figure, check_part_3d
from optodraw.core.ports import Port
from optodraw.core.transform import Vec3
from optodraw.registry import build_component, component_registry
from optodraw.symbols.art import PORT_TOLERANCE, art_2d, art_bounds, port_gaps, symbol_for_2d

NEEDS_A_SOURCE = {"CustomModel", "GDSModel"}     # built from a file, not from defaults
# The parts whose art still misses a port, each with its reason. The list only shrinks: a listed part that meets
# its ports fails the test, so it comes off the list.
STILL_MISSES: dict[str, str] = {}


def _catalog() -> list[str]:
    return sorted(set(component_registry()) - NEEDS_A_SOURCE)


@pytest.mark.parametrize("name", _catalog())
def test_every_port_ends_where_the_art_draws_it(name):
    over = {port: round(gap, 2) for port, gap in port_gaps(build_component(name)).items() if gap > PORT_TOLERANCE}
    if name in STILL_MISSES:
        assert over, f"{name} meets its ports now: take it off STILL_MISSES"
    else:
        assert not over, f"{name}: the art misses {over} (scene units)"


@pytest.mark.parametrize("part", [
    optodraw.EIC(length=50.0, width=20.0), optodraw.Microcontroller(length=30.0), optodraw.TIABlock(length=44.0, width=12.0),
    optodraw.ReceiverMacro(length=100.0, width=60.0), optodraw.TransmitterMacro(length=60.0),
    build_component("ADC", length=40.0, width=10.0), build_component("DACDriver", length=50.0),
    optodraw.SPADArray(sensor_height=4.0), optodraw.CameraSensor(sensor_width=20.0), optodraw.Prism(apex_angle=45.0),
    optodraw.Pinhole(outer_diameter=20.0), optodraw.SpectrometerSlit(slit_height=20.0, body_width=4.0),
    optodraw.TranslationStage(length=10.0, width=30.0), optodraw.KinematicMount(base_width=40.0),
    optodraw.CryostatWindow(aperture=30.0, thickness=1.0),
], ids=lambda part: type(part).__name__)
def test_a_resized_part_still_meets_its_ports(part):
    """The ports follow the plan of the pic in the size the art is drawn at, so a new size keeps them on the art."""

    assert max(port_gaps(part).values()) <= PORT_TOLERANCE, port_gaps(part)


def test_light_runs_over_art_that_reaches_past_its_port():
    """A thin plate's 1D symbol carries its output at the end of a short beam: the light leaving the plate runs over
    that stub, so the stub is no gap."""

    plate = optodraw.Polarizer()
    a, b, c, d, e, f = art_2d(plate)["matrix"]
    mark = symbol_for_2d(plate).ports["out"]
    assert a * mark.x + c * mark.y + e - float(plate.ports()["out"].center.x) > 2.0     # the stub reaches past
    assert port_gaps(plate)["out"] <= PORT_TOLERANCE


class _HolderPinhole(optodraw.Pinhole):
    """A pinhole whose ports sit on its 3D holder, past the foil its 2D art draws (as on main)."""

    component_type = "Pinhole"

    def ports(self):
        half = self.outer_diameter * 0.09
        return {"in": Port("in", Vec3(-half, 0.0, 0.0), orientation_deg=180.0, width=8.0, kind="free_space"),
                "out": Port("out", Vec3(half, 0.0, 0.0), orientation_deg=0.0, width=8.0, kind="free_space")}


def test_light_that_ends_short_of_the_drawn_part_is_in_the_air():
    assert port_gaps(_HolderPinhole())["out"] > PORT_TOLERANCE


class _WideJacks(optodraw.SMU):
    """An SMU whose jacks lie twice as far apart as its pic draws them."""

    component_type = "SMU"
    JACKS = {"hi": 0.4, "lo": 0.88}


@pytest.mark.parametrize("part", [optodraw.SMU(), _WideJacks()], ids=["SMU", "wide jacks"])
def test_a_part_with_only_wires_takes_its_size_from_its_ports(part):
    """The size rule is for the beam stubs of a thin plate; a wire has no stub to run over, so the art reaches
    every wire."""

    assert max(port_gaps(part).values()) <= PORT_TOLERANCE


def test_an_smu_is_drawn_as_wide_as_its_case():
    """Its jacks sit on the pic's plan at the scale of the 28-unit case; at their old 5.6 spacing the panel was
    drawn 41 units wide."""

    x0, _, x1, _ = art_bounds(optodraw.SMU())
    assert 26.0 < x1 - x0 < 32.0                       # the 28-unit case and the blank border of the symbol


class _MovedFibre(optodraw.PolarizationController):
    """A polarization controller whose fibre output moved 3 units off the end its art draws."""

    component_type = "PolarizationController"

    def ports(self):
        ports = super().ports()
        out = ports["out"]
        ports["out"] = Port("out", Vec3(float(out.center.x), float(out.center.y) + 3.0, 0.0), orientation_deg=0.0,
                            width=out.width, kind=out.kind)
        return ports


@pytest.mark.parametrize("cls, found", [(optodraw.PolarizationController, False), (_MovedFibre, True)],
                         ids=["meets", "moved"])
def test_a_fibre_that_ends_off_the_drawn_port_is_found(cls, found):
    scene = Scene(title="x", width=200, height=80, platform="free_space")
    controller = scene.add(cls(center=(0, 0)))
    collimator = scene.add(optodraw.FiberCollimator(center=(60, 3)))
    scene.route((controller, "out"), (collimator, "in"), kind="fiber")
    findings = [f for f in check_figure(scene, view="2d") if "ends in the air" in f and "PolarizationController:out" in f]
    assert bool(findings) == found, findings


def test_a_4f_relay_draws_its_lenses_at_their_stations_from_end_to_end():
    """The 4f symbol has one length: it stayed a sketch at the object port, the image port 57 units past it."""

    relay = optodraw.FourFSystem(focal_length_1=10.0, focal_length_2=50.0)
    assert art_2d(relay) is None
    children = relay.geometry_2d()["children"]
    lenses = sorted(c["pic"]["origin"][0] for c in children if c["type"] == "art")
    assert lenses == pytest.approx([relay._stations()[0], relay._stations()[2]])
    rays = [c["points"] for c in children if c.get("role") == "ray"]
    assert rays and all(r[0][0] == pytest.approx(relay.ports()["object"].center.x) and
                        r[-1][0] == pytest.approx(relay.ports()["image"].center.x) for r in rays)


def test_a_4f_relay_at_its_true_length_keeps_the_look_of_its_symbol():
    """At its true length the relay drew a solid orange Fourier plane and a grey axis that its symbol does not have."""

    from optodraw.symbols.art import LINE_SCALE

    relay = optodraw.FourFSystem(focal_length_1=10.0, focal_length_2=50.0)
    children = relay.geometry_2d()["children"]
    lens = next(c for c in children if c["type"] == "art")
    line = min(lens["pic"]["scale"], LINE_SCALE)                       # scene units per point, as the lens art
    rays = [c for c in children if c.get("role") == "ray"]
    assert len(rays) == 2 and all(c["stroke"].lower() == "#ef4444" and c["stroke_width"] == pytest.approx(0.3 * line)
                                  for c in rays)
    planes = [c for c in children if c.get("role") == "plane"]
    fourier = [c for c in planes if c["x1"] == pytest.approx(relay._stations()[1])]
    assert len(fourier) == 1 and fourier[0]["stroke"].lower() == "#64748b" and fourier[0]["stroke_dasharray"]
    assert {c["type"] for c in children} <= {"art", "polyline", "line"} and len(children) == len(rays) + len(planes) + 2


@pytest.mark.parametrize("pads", [6, 5])
def test_a_circuit_board_at_its_own_size_keeps_the_look_of_its_symbol(pads):
    """At its own size the board drew a dull green with copper pads, and traces that left and met a pad on one row."""

    board = optodraw.PCB(length=60.0, width=40.0, pad_count=pads)
    children = board.geometry_2d()["children"]
    assert (children[0]["fill"].lower(), children[0]["stroke"].lower()) == ("#10b981", "#047857")
    ports = board.ports()
    left = sorted((p.center.y for k, p in ports.items() if p.center.x < 0), reverse=True)
    right = sorted((p.center.y for k, p in ports.items() if p.center.x > 0), reverse=True)
    traces = [c for c in children if c.get("role") == "trace"]
    assert len(traces) == pads // 2 and len([c for c in children if c.get("role") == "via"]) == pads // 2
    for k, trace in enumerate(traces):                       # from a left pad down one row to a right pad, in gold
        (x0, y0), (x1, y1) = trace["points"][0][:2], trace["points"][-1][:2]
        assert (y0, y1) == pytest.approx((left[2 * k], right[2 * k + 1])) and x0 < 0 < x1
        assert trace["stroke"].lower() == "#d4af37"
    pads_2d = [c for c in children if c.get("role") == "pad"]
    assert len(pads_2d) == 2 * pads and {c["stroke"].lower() for c in pads_2d} == {"#a8841f"}
    plain = optodraw.PCB(length=60.0, width=40.0, pad_count=pads, style="plain").geometry_2d()["children"]
    assert not [c for c in plain if c.get("role") in ("trace", "via")]
    assert optodraw.PCB(color="#334455").geometry_2d()["children"][0]["fill"] == "#334455"   # a chosen colour stays


@pytest.mark.parametrize("length, width", [(90.0, 52.0), (60.0, 24.0)])
def test_a_circuit_board_keeps_its_own_size(length, width):
    """The board pic has one aspect: a 60 x 24 board was drawn 60 x 39, off its edge pads."""

    from optodraw.layout import estimate_component_bounds

    board = optodraw.PCB(length=length, width=width)
    assert art_2d(board) is None
    x0, y0, x1, y1 = estimate_component_bounds(board)
    assert (x1 - x0, y1 - y0) == pytest.approx((length, width), abs=0.5)


@pytest.mark.parametrize("part", [optodraw.TransmitterMacro(), optodraw.ReceiverMacro(),
                                  optodraw.TransmitterMacro(length=120.0)], ids=["tx", "rx", "tx long"])
def test_a_macro_module_reaches_the_tabs_of_its_ports(part):
    """The bias, clock and ground ports moved onto the pic's leads; a module of the old width left their tabs in
    the air."""

    assert check_part_3d(part) == []
