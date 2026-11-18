"""A ninety-degree hybrid preserves power and gives balanced I/Q currents."""
import math

import numpy as np
import pytest

from optodraw import CoherentReceiver
from optodraw.animation_engine.behaviours import behaviour_for
from optodraw.animation_engine.graph import SignalGraph
from optodraw.animation_engine.inputs import InputSignal
from optodraw.animation_engine.solver import steady_state, propagate_pulses


@pytest.mark.parametrize("phase", [0, math.pi/2, math.pi, -math.pi/2, 0.7])
def test_receiver_phase_power_and_currents(phase):
    part = CoherentReceiver(responsivity_a_per_w=0.85)
    amplitude = np.exp(1j*phase)
    inputs = [InputSignal("port:rx:signal", jones=(amplitude.real, amplitude.imag, 0, 0)),
              InputSignal("port:rx:lo")]
    result = steady_state(SignalGraph({"rx": part}, []), inputs=inputs)
    assert sum(item["power"] for item in result.absorbed) == pytest.approx(2)
    currents = behaviour_for(part, "rx").currents(part, result.absorbed)
    assert currents["i_a"] == pytest.approx(0.85*math.cos(phase), abs=1e-9)
    assert currents["q_a"] == pytest.approx(0.85*math.sin(phase), abs=1e-9)
    assert result.exits == []


def test_receiver_pulse_is_absorbed_after_internal_transit():
    part = CoherentReceiver()
    result = propagate_pulses(SignalGraph({"rx": part}, []), inputs=[InputSignal("port:rx:signal")])
    assert len(result.absorbed) == 4
    assert sum(item["power"] for item in result.absorbed) == pytest.approx(1)
    assert all(item["t_ps"] > 0 for item in result.absorbed)
    assert len({round(item["t_ps"], 10) for item in result.absorbed}) == 1
