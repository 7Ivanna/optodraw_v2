"""Internal detector channels must absorb, not become unsupported ports."""
from types import SimpleNamespace

import pytest

from optodraw.animation_engine.behaviours import Behaviour, Emission, Transfer
from optodraw.animation_engine.graph import SignalGraph
from optodraw.animation_engine.signals import linear, scalar
from optodraw.animation_engine.solver import propagate_pulses, steady_state


class InternalDetector(Behaviour):
    passive = False

    def emissions(self, part, sid, params):
        return [Emission("_input", linear(0), 1550)]

    def transfers(self, part, sid, port, wavelength_nm, params):
        if port == "_input":
            return [Transfer(port, "_detector", scalar(1), ((0, 0), (10, 0)))]
        return []

    def sinks(self, part, port):
        return port == "_detector"


@pytest.mark.parametrize("solver", [steady_state, propagate_pulses])
def test_internal_detector_absorbs(solver):
    part = SimpleNamespace(animation_behaviour=lambda: InternalDetector())
    result = solver(SignalGraph({"rx": part}, []))
    assert len(result.absorbed) == 1
    assert result.absorbed[0]["port"] == "_detector"
    assert result.absorbed[0]["power"] == pytest.approx(1)
    assert result.exits == []


def test_internal_absorption_remains_in_passivity_operator():
    from optodraw.animation_engine.errors import AnimationError
    from optodraw.animation_engine.solver import check_passivity

    class AmplifyingDetector(InternalDetector):
        passive = True

        def transfers(self, part, sid, port, wavelength_nm, params):
            if port in ("in", "_input"):
                return [Transfer(port, "_detector", scalar(2), ((0, 0), (10, 0)))]
            return []

    part = SimpleNamespace(animation_behaviour=lambda: AmplifyingDetector(),
                           ports=lambda: {"in": SimpleNamespace(kind="optical")})
    graph = SignalGraph({"rx": part}, [])
    result = steady_state(graph)
    with pytest.raises(AnimationError, match="passive part"):
        check_passivity(graph, result)
