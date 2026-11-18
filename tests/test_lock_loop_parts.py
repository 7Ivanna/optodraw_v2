"""The parts of a lock loop and an RF chain: a PID controller (servo), a signal source (local oscillator), a summing
junction, an RF (electrical) spectrum analyser, an RF power splitter, an RF directional coupler and an RF phase
shifter.

Each part draws its symbol in 1D and in 2D with a port at the end of each lead, a module or a bench case in 3D, and
saves and loads with its settings. A lock loop built from them passes the figure checks in both views.
"""

from __future__ import annotations

import pytest

import optodraw
from optodraw import Scene, check_figure, check_part_3d
from optodraw.catalog import describe_component, list_components
from optodraw.registry import build_component
from optodraw.symbols import lookup
from optodraw.symbols.art import PORT_TOLERANCE, art_2d, port_gaps

PARTS = {
    "PIDController": ("electronics", {"in", "out"}),
    "SignalSource": ("electronics", {"out"}),
    "SummingJunction": ("electronics", {"in1", "in2", "out"}),
    "RFSpectrumAnalyzer": ("instruments", {"in"}),
    "RFSplitter": ("electronics", {"in", "out1", "out2"}),
    "RFCoupler": ("electronics", {"in", "out", "cpl"}),
    "RFPhaseShifter": ("electronics", {"in", "out"}),
}


@pytest.mark.parametrize("name", PARTS)
def test_the_part_is_in_the_catalog_with_electrical_ports(name):
    # mutant: register PIDController with "category": "misc" in _BUILTIN_METADATA (optodraw/registry.py)
    category, ports = PARTS[name]
    assert name in list_components(category=category)
    part = build_component(name)
    assert set(part.ports()) == ports
    assert {port.kind for port in part.ports().values()} == {"electrical"}


@pytest.mark.parametrize("name", PARTS)
def test_the_1d_symbol_is_exact_and_carries_the_ports(name):
    # mutant: delete the PIDController row from optodraw/symbols/variants.toml and rebuild: a labelled block stands in
    symbol = lookup(build_component(name))
    assert symbol.exact and symbol.source == "prebuilt", name
    assert {port: mark.kind for port, mark in symbol.ports.items()} == dict.fromkeys(PARTS[name][1], "electrical")


@pytest.mark.parametrize("signs", ["++", "+-"])
@pytest.mark.parametrize("name", PARTS)
def test_the_2d_art_draws_every_lead_to_its_port(name, signs):
    """A wire to a port meets the drawn lead: the class plan and the pic hold the same numbers."""

    # mutant: \odport[electrical]{in}{-0.4,0} in pics/od pid (od-circuit.tex), rebuild: the input misses by 1.2
    part = build_component(name, signs=signs) if name == "SummingJunction" else build_component(name)
    assert art_2d(part) is not None
    gaps = port_gaps(part)
    assert set(gaps) == PARTS[name][1]
    assert max(gaps.values()) < 0.1 * PORT_TOLERANCE, gaps


def test_a_circuit_part_is_drawn_at_the_scale_of_its_plan():
    # mutant: SignalSource.PORTS out at (0.45, 0.0, 0.0): the one-port art keeps the plan's size, the lead misses
    for part in (optodraw.SignalSource(), optodraw.SignalSource(length=20.0), optodraw.PIDController(length=30.0)):
        assert art_2d(part)["pic"]["scale"] == pytest.approx(part.unit * 2.54 / 72.0, rel=1e-3)
        assert max(port_gaps(part).values()) < 0.1 * PORT_TOLERANCE


@pytest.mark.parametrize("name", PARTS)
def test_the_3d_body_has_no_loose_solid_and_rests_flat(name):
    # mutant: put the knobs of PIDController at height + 0.5 * u (above the case): a knob hangs in the air
    part = build_component(name)
    assert part.geometry_3d()["children"]
    assert check_part_3d(part) == []


def test_the_servo_has_a_jack_at_each_port_and_two_knobs_on_top():
    # mutant: drop the knob loop in PIDController.geometry_3d: no knob
    solids = optodraw.PIDController().geometry_3d()["children"]
    assert [solid["role"] for solid in solids].count("sma jack") == 2
    knobs = [solid for solid in solids if solid["role"] == "knob"]
    case = next(solid for solid in solids if solid["role"] == "case")
    assert len(knobs) == 2 and all(knob["position"][1] > case["height"] for knob in knobs)


@pytest.mark.parametrize("signs, minus", [("++", False), ("+-", True)])
def test_the_sign_of_the_second_input_follows_signs(signs, minus):
    """A subtractor draws a minus beside in2, an adder a plus: in 2D, and in 1D through its own variant."""

    # mutant: return "sumjunction", {} from SummingJunction.symbol_1d: the subtractor shows a plus in 1D
    part = optodraw.SummingJunction(signs=signs)
    assert lookup(part).params == ({"minus": True} if minus else {})
    x, y = part.SIGN_AT["in2"]
    upright = [line for line in part.LINES if len(line) == 2 and line[0][0] == line[1][0] == x
               and min(line[0][1], line[1][1]) < y < max(line[0][1], line[1][1])]
    assert len(upright) == (0 if minus else 1)


def test_a_summing_junction_refuses_other_signs():
    with pytest.raises(ValueError, match="signs"):
        optodraw.SummingJunction(signs="--")


def test_the_analyser_screen_shows_one_carrier_in_the_middle_of_its_screen():
    """The ESA trace is a locked beat note: its highest point is the carrier at the centre of the screen."""

    # mutant: centre = x0 in RFSpectrumAnalyzer._trace: the carrier sits at the left edge of the screen
    esa = optodraw.RFSpectrumAnalyzer()
    x0, y0, x1, y1 = esa.SCREEN
    trace = esa._trace()
    peak = max(trace, key=lambda point: point[1])
    assert peak[0] == pytest.approx((x0 + x1) / 2.0, abs=0.01)
    assert all(x0 < x < x1 and y0 < y < y1 for x, y in trace)


def test_settings_save_and_load():
    # mutant: drop "signs" from the SummingJunction row of _BUILTIN_METADATA: the loaded junction adds
    scene = Scene(width=120, height=80)
    scene.add(optodraw.SummingJunction(center=(10, 5), signs="+-", label="Error"))
    scene.add(optodraw.PIDController(center=(30, 5), angle=180, value="PI", label="Servo"))
    scene.add(optodraw.SignalSource(center=(50, 5), value="20 MHz", label="LO"))
    loaded = {type(item).__name__: item for item in Scene.from_spec(scene.to_spec()).walk()}
    assert loaded["SummingJunction"].signs == "+-"
    assert loaded["PIDController"].label == "Servo = PI"
    assert loaded["PIDController"].transform.rotation_deg.z == pytest.approx(180.0)
    assert loaded["SignalSource"].label == "LO = 20 MHz"


def _lock_loop() -> Scene:
    scene = Scene(title="Lock loop", width=120, height=60, platform="free_space")
    setpoint = scene.add(optodraw.SignalSource(center=(-36, 0), label="Setpoint"))
    signal = scene.add(optodraw.SignalSource(center=(-14, -22), angle=90, label="Signal", label_side="left"))
    total = scene.add(optodraw.SummingJunction(center=(-14, 0), signs="+-", label="Error"))
    servo = scene.add(optodraw.PIDController(center=(10, 0), value="PI", label="Servo"))
    esa = scene.add(optodraw.RFSpectrumAnalyzer(center=(40, 14), label="ESA"))
    scene.route((setpoint, "out"), (total, "in1"), kind="electrical")
    scene.route((signal, "out"), (total, "in2"), kind="electrical")
    scene.route((total, "out"), (servo, "in"), kind="electrical")
    scene.route((servo, "out"), (esa, "in"), kind="electrical", path_type="manhattan")
    scene.fit_frame(margin=6)
    return scene


def _rf_chain() -> Scene:
    scene = Scene(title="RF chain", width=120, height=70, platform="free_space")
    beat = scene.add(optodraw.SignalSource(center=(-54, 0), label="Beat note", label_side="bottom"))
    tap = scene.add(optodraw.RFCoupler(center=(-26, 0), value="-10 dB", label="Tap", label_side="bottom"))
    mixer = scene.add(optodraw.RFMixer(center=(0, 0), label="Mixer", label_side="top"))
    lo = scene.add(optodraw.SignalSource(center=(-44, -26), label="LO"))
    split = scene.add(optodraw.RFSplitter(center=(-26, -26), label="Splitter", label_side="bottom"))
    shift = scene.add(optodraw.RFPhaseShifter(center=(-8, -22), label="Phase", label_side="bottom"))
    servo = scene.add(optodraw.PIDController(center=(20, 0), label="Servo", label_side="bottom"))
    esa = scene.add(optodraw.RFSpectrumAnalyzer(center=(-32.3, 22), label="ESA", label_side="right"))
    wire = {"kind": "electrical", "path_type": "manhattan"}
    scene.route((beat, "out"), (tap, "in"), **wire)
    scene.route((tap, "out"), (mixer, "rf"), **wire)
    scene.route((tap, "cpl"), (esa, "in"), **wire)
    scene.route((lo, "out"), (split, "in"), **wire)
    scene.route((split, "out1"), (shift, "in"), **wire)
    scene.route((shift, "out"), (mixer, "lo"), **wire)
    scene.route((mixer, "if"), (servo, "in"), **wire)
    scene.fit_frame(margin=6)
    return scene


@pytest.mark.parametrize("build", [_lock_loop, _rf_chain])
@pytest.mark.parametrize("view", ["2d", "1d"])
def test_a_loop_of_the_parts_passes_the_figure_checks(view, build):
    # mutant: label_side="top" for "Signal": its label sits on its own wire in 2D
    assert check_figure(build(), preset="single_column", view=view) == []


def test_the_coupled_port_leaves_the_coupler_on_the_side_of_its_coupled_line():
    """The sample goes up toward the instruments over the chain, from the end of the coupled line beside the main
    line, as a monitor output does."""

    # mutant: RFCoupler.PORTS cpl at (0.2, -0.5, -90.0): the sample leaves below, away from the coupled line
    coupler = optodraw.RFCoupler()
    cpl = coupler.ports()["cpl"]
    assert cpl.orientation_deg == 90.0 and cpl.center.y > 0
    coupled = coupler.LINES[1]
    assert coupled[-1] == pytest.approx((cpl.center.x / coupler.unit, cpl.center.y / coupler.unit))
    assert all(0 < y < 0.3 for _, y in coupled[:2])                 # inside the case, above the main line


def test_a_splitter_gives_two_outputs_on_the_far_side_of_its_input():
    # mutant: RFSplitter.PORTS out2 at (-0.5, -0.15, 180.0): an output beside the input
    ports = optodraw.RFSplitter().ports()
    assert ports["in"].orientation_deg == 180.0
    assert {ports["out1"].orientation_deg, ports["out2"].orientation_deg} == {0.0}
    assert ports["out1"].center.y > 0 > ports["out2"].center.y


def test_the_catalog_describes_each_part_by_its_function():
    assert "ESA" in describe_component("RFSpectrumAnalyzer")["description"]
    assert "servo" in describe_component("PIDController")["description"]
    assert "local oscillator" in describe_component("SignalSource")["description"]


INSTRUMENT_PORTS = {
    "LaserDriver": {"mod", "tec", "out"},
    "WaveformGenerator": {"sync", "out1", "out2"},
    "Oscilloscope": {"ch1", "ch2", "usb"},
}


@pytest.mark.parametrize("name", INSTRUMENT_PORTS)
def test_an_instrument_draws_each_of_its_jacks_where_its_cable_ends(name):
    """A servo drives the laser driver's modulation input, a generator's sync triggers a scope, a scope sends its
    data to a computer: each port sits on a jack of the art, and the 3D case stays whole."""

    # mutant: JACKS["mod"] = -0.3 in LaserDriver (instruments.py): the art keeps the pic's jack, the cable misses it
    part = build_component(name)
    assert set(part.ports()) == INSTRUMENT_PORTS[name]
    gaps = port_gaps(part)
    assert set(gaps) == INSTRUMENT_PORTS[name]
    assert max(gaps.values()) < 0.1 * PORT_TOLERANCE, gaps
    assert check_part_3d(part) == []


@pytest.mark.parametrize("name", INSTRUMENT_PORTS)
def test_the_3d_case_has_a_connector_under_each_port(name):
    # mutant: drop the usb box from Oscilloscope.geometry_3d: no connector under usb
    part = build_component(name)
    xs = [child["position"][0] for child in part.geometry_3d()["children"]
          if child.get("role") in ("bnc", "usb") or child.get("material", {}).get("color") == "#2b3036"]
    for port in part.ports().values():
        assert any(abs(x - port.center.x) < 0.05 for x in xs), port.name
