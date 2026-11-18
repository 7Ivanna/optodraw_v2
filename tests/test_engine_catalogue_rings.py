"""Two bus couplers preserve reciprocity, loss and causal ring circulation."""

import cmath
import math

import numpy as np
import pytest

import optodraw
from optodraw.animation_engine.behaviours.geometry import index_of
from optodraw.animation_engine.graph import build_graph
from optodraw.animation_engine.inputs import InputSignal
from optodraw.animation_engine.solver import Network, _part_outputs, propagate_pulses


@pytest.mark.parametrize("couplings,a", [((0.1, 0.1), 0.99), ((0.2, 0.35), 1.0)])
@pytest.mark.parametrize("phase", [0, 0.7, math.pi])
def test_add_drop_ring_matches_analytic_response_and_reciprocity(couplings, a, phase):
    scene = optodraw.Scene(platform="on_chip")
    ring = scene.add(optodraw.MicroringResonator(add_drop=True))
    ring.power_coupling, ring.drop_power_coupling = couplings
    ring.round_trip_amplitude = a
    loop = ring.loop_centerline()
    length = sum(math.dist(p, q) for p, q in zip(loop, loop[1:]))
    wl = 1550.0
    theta = 2 * math.pi * index_of(ring, "o1") * length / (wl / 1000)
    params = {"phase:microringresonator1": phase - theta}
    net = Network(build_graph(scene), params)
    out = _part_outputs(net, "microringresonator1", "o1", np.array([1, 0]), wl)
    k1, k2 = couplings
    t1, t2 = math.sqrt(1-k1), math.sqrt(1-k2)
    denominator = 1-a*t1*t2*cmath.exp(1j*phase)
    expected_through = abs((t1-a*t2*cmath.exp(1j*phase))/denominator)**2
    expected_drop = k1*k2*a/abs(denominator)**2
    assert abs(out["o2"][0])**2 == pytest.approx(expected_through, abs=1e-9)
    assert abs(out["o3"][0])**2 == pytest.approx(expected_drop, abs=1e-9)
    assert sum(abs(v[0])**2 for v in out.values()) <= 1+1e-9
    reciprocal = _part_outputs(net, "microringresonator1", "o3", np.array([1, 0]), wl)
    assert reciprocal["o1"][0] == pytest.approx(out["o3"][0])


def test_default_add_drop_ring_animates_and_rings_down_causally():
    scene = optodraw.Scene(platform="on_chip")
    scene.add(optodraw.MicroringResonator(add_drop=True))
    result = propagate_pulses(build_graph(scene), inputs=[
        InputSignal("port:microringresonator1:o1")])
    loops = [p for p in result.packets if p.start[1].startswith("_ring")]
    assert len(loops) > 3
    assert all(p.t1_ps >= p.t0_ps for p in loops)
    assert {item["port"] for item in result.exits} == {"o2", "o3"}


@pytest.mark.parametrize("add_drop", [False, True])
def test_absent_values_and_none_use_the_same_documented_defaults(add_drop):
    scene = optodraw.Scene(platform="on_chip")
    ring = scene.add(optodraw.MicroringResonator(add_drop=add_drop))
    graph = build_graph(scene)
    expected = _part_outputs(Network(graph, {}), "microringresonator1", "o1", np.array([1, 0]), 1550)
    ring.power_coupling = ring.drop_power_coupling = ring.round_trip_amplitude = None
    actual = _part_outputs(Network(graph, {}), "microringresonator1", "o1", np.array([1, 0]), 1550)
    assert actual.keys() == expected.keys()
    assert all(np.allclose(actual[key], expected[key]) for key in expected)
