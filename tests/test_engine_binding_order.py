"""Concurrent descriptors must not change physics through argument order."""

import pytest

from optodraw import Beam, Laser, Photodiode, Polarizer, Scene
from optodraw.animation_engine.authoring import Animation
from optodraw.animation_engine.primitives import Flow, Lagged, Plot, Quantity, Sweep


@pytest.mark.parametrize("order", ["flow-first", "sweep-first", "plot-first", "zero-lag"])
def test_parallel_flow_and_sweep_keep_the_same_paths_and_initial_state(order):
    scene = Scene(width=300, height=100, platform="free_space")
    laser = scene.add(Laser(center=(-100, 0)))
    polarizer = scene.add(Polarizer())
    detector = scene.add(Photodiode(center=(100, 0)))
    scene.add(Beam((laser, "out"), (polarizer, "in")))
    scene.add(Beam((polarizer, "out"), (detector, "in")))
    flow = Flow(mode="cw", seconds=4)
    sweep = Sweep("angle:polarizer1", 0, 90, seconds=4, samples=3)
    plot = Plot(Quantity(detector), against="angle:polarizer1")
    actions = {
        "flow-first": (flow, sweep, plot),
        "sweep-first": (sweep, flow, plot),
        "plot-first": (plot, sweep, flow),
        "zero-lag": (Lagged(sweep, flow, plot, lag=0),),
    }[order]
    animation = Animation(scene).play(*actions)
    data = animation.to_json()
    flow_track = next(track for track in data["tracks"] if track["type"] == "Flow")
    sweep_track = next(track for track in data["tracks"] if track["type"] == "Sweep")
    assert sweep_track["args"]["paths"] == flow_track["args"]["paths"]
    assert "beam:beam2:0" in sweep_track["args"]["paths"]
    ref = flow_track["args"]["state"]
    initial = data["signal_state"] if ref == "base" else data["signal_states"][ref]
    assert initial["params"] == {}
    assert data["assets"]["plot:1"]["y"] == pytest.approx([1, 0.5, 0], abs=2e-3)
    assert animation._params["angle:polarizer1"] == 90
