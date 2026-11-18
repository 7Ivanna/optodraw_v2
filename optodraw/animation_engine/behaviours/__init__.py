"""The behaviour registry: how each part acts on the light that reaches it.

A behaviour returns transfers: from an input port to an output port, a 2 x 2 Jones matrix, and the
path the light takes inside the part. Splitting is several transfers from one input; interference is
several transfers that end at one output (the solver adds them coherently). A new effect is a new
behaviour: the solver does not change.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Callable

import numpy as np

from ..errors import NotModelledYet

Params = dict[str, Any]


def polyline_length(points) -> float:
    return sum(math.dist(a, b) for a, b in zip(points, points[1:]))


@dataclass(frozen=True)
class Transfer:
    in_port: str
    out_port: str                                   # a name that starts with "_" is an internal port
    matrix: np.ndarray                              # 2 x 2 complex Jones matrix along this path
    points: tuple[tuple[float, float], ...]         # world (x, y) from the input to the output
    group_index: float = 1.0
    name: str = ""                                  # tells two paths between the same ports apart
    physical_length: float | None = None            # µm, when the drawing is not to scale
    extra_delay_ps: float = 0.0                     # a heater's delay: added to the arrival only, never to the phase
    phase_included: bool = False                    # the matrix holds the whole phase (a table): the solver adds none

    @property
    def length(self) -> float:
        if self.physical_length is not None:
            return float(self.physical_length)
        return polyline_length(self.points)


@dataclass(frozen=True)
class Emission:
    port: str
    jones: np.ndarray
    wavelength_nm: float
    width_ps: float = 0.2
    t0_ps: float = 0.0


class Behaviour:
    """Transmits nothing and absorbs nothing: a subclass says what the part does."""

    passive = True                                  # a passive part may not create power
    fold_ports: frozenset[str] = frozenset()        # a port light enters and leaves (a fold mirror)
    parameters: tuple[str, ...] = ()                # the physics numbers it reads off the part (``model_numbers``)

    def transfers(self, part: Any, sid: str, in_port: str, wavelength_nm: float, params: Params) -> list[Transfer]:
        return []

    def emissions(self, part: Any, sid: str, params: Params) -> list[Emission]:
        return []

    def sinks(self, part: Any, port: str) -> bool:
        """True when light that arrives at ``port`` ends there (a detector, a beam dump)."""

        return False

    def parameter_names(self, part: Any) -> tuple[str, ...]:
        """The physics numbers this part reads: ``parameters``, or more where a part's form reads more."""

        return self.parameters

    def notes(self, part: Any, sid: str) -> list[str]:
        """What a result that the light took through this part rests on, for the result's notes (``spectrum``)."""

        return []

    def rings(self, part: Any, sid: str) -> list[tuple[str, tuple[str, ...]]]:
        """The part's rings: per ring, its ``phase`` key and the internal ports its round trip passes, in order (each
        to the next, the last to the first); [] for a part with no ring."""

        return []

    def sections(self, part: Any, sid: str, params: Params) -> list:
        """The part's coupling sections (``geometry.Section``), one per coupler gap and direction of travel; [] for a
        part with no gap. The display draws a section's rails in place of the transfers it replaces."""

        return []


_REGISTRY: dict[str, Behaviour] = {}


def register(*component_types: str) -> Callable[[type[Behaviour]], type[Behaviour]]:
    def decorate(cls: type[Behaviour]) -> type[Behaviour]:
        behaviour = cls()
        for name in component_types:
            _REGISTRY[name] = behaviour
        return cls

    return decorate


def registered_types() -> list[str]:
    return sorted(_REGISTRY)


def find_behaviour(part: Any) -> Behaviour | None:
    model = getattr(part, "model", None)
    if model is not None:
        from optodraw.sparameters import SParameters        # imported only when a part holds a model

        if isinstance(model, SParameters):
            from .tabulated import TabulatedBehaviour

            held = getattr(part, "_tabulated", None)              # one per part and table: its checks and paths keep
            if held is None or held.sp is not model:
                held = TabulatedBehaviour(model)
                part._tabulated = held
            return held
    own = getattr(part, "animation_behaviour", None)
    if callable(own):
        return own()
    return _REGISTRY.get(getattr(part, "component_type", ""))


def behaviour_for(part: Any, sid: str) -> Behaviour:
    found = find_behaviour(part)
    if found is None:
        raise NotModelledYet(f"{sid}: no behaviour yet for {getattr(part, 'component_type', type(part).__name__)}")
    return found


from . import coupled_rings, interferometers, passive, polarisation, resonators, sources, splitters, catalogue  # noqa: E402,F401
