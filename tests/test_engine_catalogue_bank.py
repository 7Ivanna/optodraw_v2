"""The bank uses its rings and return bus, not a fixed split ratio."""

from optodraw import MicroringWeightBank
from optodraw.animation_engine.graph import SignalGraph
from optodraw.animation_engine.signals import linear
from optodraw.animation_engine.solver import Network, _part_outputs


def output(part, params=None):
    net = Network(SignalGraph({"bank": part}, []), params or {})
    return _part_outputs(net, "bank", "o1", linear(0), 1550)


def test_bank_pulse_ringdown_uses_the_return_loop():
    from optodraw.animation_engine.inputs import InputSignal
    from optodraw.animation_engine.solver import propagate_pulses
    part = MicroringWeightBank(ring_count=2)
    result = propagate_pulses(SignalGraph({"bank": part}, []), inputs=[InputSignal("port:bank:o1")])
    through = [item for item in result.exits if item["port"] == "o2"]
    drop = [item for item in result.exits if item["port"] == "drop"]
    assert through and drop
    assert min(item["t_ps"] for item in drop) > min(item["t_ps"] for item in through)
    assert any("_return_f" in key for key in result.edges)
    assert sum(item["power"] for item in result.exits + result.absorbed) <= 1 + 1e-8
