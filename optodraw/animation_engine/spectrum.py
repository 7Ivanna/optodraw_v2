"""Spectra: the steady power at every port where the light ends, against wavelength.

Each point is one steady-state solve (``solver.steady_state``) with the sources at that wavelength: no new physics.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from optodraw.provenance import model_numbers

from .behaviours import behaviour_for
from .errors import AnimationError
from .graph import build_graph
from .solver import steady_state

PHASE_NOTE = ("the propagation phase uses the group index: the free spectral range is right, and the absolute "
              "resonance position is a model value")


@dataclass(frozen=True, eq=False)
class Spectrum:
    """``power["<sid>:<port>"]``, one value per wavelength, for every port where light is absorbed or leaves the
    drawing; an absorber inside a part has the name of the port the light entered by. ``notes`` say what is model."""

    wavelengths_nm: np.ndarray
    power: dict[str, np.ndarray]
    notes: tuple[str, ...]
    sids: dict[int, str] = field(default_factory=dict, repr=False)     # id(part) -> its sid in ``power``

    def of(self, part: Any, port: str) -> np.ndarray:
        """The power at ``part``'s ``port``: the same values as ``power["<sid>:<port>"]``, found by the part."""

        key = f"{self.sids.get(id(part), '?')}:{port}"
        if key not in self.power:
            raise KeyError(f"no light ends at {key}; the spectrum has {', '.join(sorted(self.power))}")
        return self.power[key]

    def show(self, osa: Any, port: str = "in") -> None:
        """Puts the power at ``osa``'s ``port`` on its screen (``osa.trace``): ``10 log10`` of the power in mW (dBm),
        with a floor at -60 dB, against wavelength."""

        from optodraw.components.instruments import screen_points

        osa.trace = screen_points(self.wavelengths_nm, 10.0 * np.log10(np.maximum(self.of(osa, port), 1e-6)))


def ended_power(result: Any) -> dict[str, float]:
    """The power at every port where light ends in one steady state, keyed ``"<sid>:<port>"``; an absorber inside a
    part has the name of the port the light entered by. The spectrum and the signal chain key their power by it."""

    entered = {edge.end: edge.start[1] for edge in result.steady       # an inner absorber: the port it is fed by
               if edge.end[1].startswith("_") and edge.start[0] == edge.end[0] and not edge.start[1].startswith("_")}
    power: dict[str, float] = {}
    for record in result.absorbed + result.exits:
        sid, port = record["part"], record["port"]
        key = f"{sid}:{entered.get((sid, port), port)}"
        power[key] = power.get(key, 0.0) + record["power"]
    return power


def spectrum(scene: Any, *, start_nm: float, stop_nm: float, points: int, params: dict | None = None) -> Spectrum:
    """The steady power at every output at ``points`` wavelengths from ``start_nm`` to ``stop_nm``, evenly spaced.
    ``params`` are the solver's params; ``"wavelength"`` is set at each point."""

    if points < 1:
        raise AnimationError(f"a spectrum needs one point or more, not {points}")
    graph = build_graph(scene)
    wavelengths = np.linspace(float(start_nm), float(stop_nm), int(points))
    power: dict[str, np.ndarray] = {}
    reached: set[str] = set()
    for k, wl in enumerate(wavelengths):
        # floor 0: every output keeps its record at every point, however dark, so each key has every value
        result = steady_state(graph, {**(params or {}), "wavelength": float(wl)}, floor=0.0)
        for key, value in ended_power(result).items():
            power.setdefault(key, np.zeros(len(wavelengths)))[k] += value
            reached.add(key.split(":", 1)[0])
        reached |= {edge.end[0] for edge in result.steady}
    parts = [(sid, part) for sid, part in graph.parts.items() if sid in reached]
    notes = [PHASE_NOTE, *model_numbers(scene, reached)]
    notes += [note for sid, part in parts for note in behaviour_for(part, sid).notes(part, sid)]
    return Spectrum(wavelengths, power, tuple(dict.fromkeys(notes)), {id(part): sid for sid, part in graph.parts.items()})
