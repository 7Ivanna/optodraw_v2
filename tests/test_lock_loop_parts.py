"""The parts of a lock loop and an RF chain: a PID controller (servo), a signal source (local oscillator), a summing
junction, an RF (electrical) spectrum analyser, an RF power splitter, an RF directional coupler and an RF phase
shifter.

Each part draws its symbol in 1D and in 2D with a port at the end of each lead, a module or a bench case in 3D, and
saves and loads with its settings. A lock loop built from them passes the figure checks in both views.
"""

from __future__ import annotations

import pytest

import optodraw
from optodraw import Scene, check_figure
from optodraw.catalog import list_components
from optodraw.registry import build_component

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


def test_a_summing_junction_refuses_other_signs():
    with pytest.raises(ValueError, match="signs"):
        optodraw.SummingJunction(signs="--")


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


INSTRUMENT_PORTS = {
    "LaserDriver": {"mod", "tec", "out"},
    "WaveformGenerator": {"sync", "out1", "out2"},
    "Oscilloscope": {"ch1", "ch2", "usb"},
}


