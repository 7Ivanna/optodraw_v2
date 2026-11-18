"""The bank uses its rings and return bus, not a fixed split ratio."""
import numpy as np
import pytest

from optodraw import MicroringWeightBank
from optodraw.animation_engine.behaviours import behaviour_for
from optodraw.animation_engine.graph import SignalGraph
from optodraw.animation_engine.signals import linear
from optodraw.animation_engine.solver import Network, _part_outputs


def output(part, params=None):
    net = Network(SignalGraph({"bank": part}, []), params or {})
    return _part_outputs(net, "bank", "o1", linear(0), 1550)


def test_bank_zero_coupling_and_real_return_geometry():
    part = MicroringWeightBank(ring_count=3)
    behaviour = behaviour_for(part, "bank")
    values = output(part, {"power_coupling:bank": 0, "round_trip_amplitude:bank": 1})
    assert np.vdot(values["o2"], values["o2"]).real == pytest.approx(1)
    assert np.vdot(values.get("drop", [0, 0]), values.get("drop", [0, 0])).real == pytest.approx(0)
    path = behaviour.transfers(part, "bank", "_return_f", 1550, {})[0]
    assert path.out_port == "drop"
    assert len(path.points) > 10
    end = part.world_port("drop").center
    assert path.points[-1] == pytest.approx((end.x, end.y))


def test_bank_passivity_reciprocity_and_individual_heater():
    part = MicroringWeightBank(ring_count=3)
    ports = ("o1", "o2", "drop")
    net = Network(SignalGraph({"bank": part}, []), {})
    columns = [_part_outputs(net, "bank", port, linear(0), 1550) for port in ports]
    external = np.array([[column.get(port, [0, 0])[0] for column in columns] for port in ports])
    assert external == pytest.approx(external.T, abs=1e-9)
    all_outputs = sorted({key for column in columns for key in column})
    complete = np.array([[column.get(port, [0, 0])[0] for column in columns] for port in all_outputs])
    assert np.linalg.svd(complete, compute_uv=False)[0] <= 1 + 1e-9
    changed = output(part, {"heater:bank:ring2": 20})
    assert abs(changed["drop"][0] - columns[0]["drop"][0]) > 1e-5


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
