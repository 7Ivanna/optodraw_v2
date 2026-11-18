"""The signal chain: the drawn electronics compute their signals, joined to the optics at the drivers and detectors.

Electrical signals are ``Waveform``s on one uniform time grid in ns. A net is the set of ports that electrical routes
join; it carries one signal from one output. Each part's ``Block`` maps the signals at its inputs to its outputs.
Drivers set solver params per time sample (``drive:``, ``heater:``, ``power:``); detectors read the steady power per
time sample, keyed as ``spectrum`` keys it. There is no circuit solve and no noise: a bandwidth is a first-order pole.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np

from optodraw.provenance import model_numbers, number_notes

from .behaviours import behaviour_for
from .errors import AnimationError
from .graph import build_graph
from .solver import steady_state
from .spectrum import PHASE_NOTE, ended_power
from .waveform import (Waveform, amplify, clock, feedback_tia, heater_power, hold, laser_power, parse_value,
                       photocurrent, sample, transimpedance)

End = tuple[str, str]

#: The model value of each datasheet number a part leaves at None; the notes name each one "(default, model)".
DEFAULTS: dict[str, float | None] = {
    "responsivity_a_per_w": 1.0,
    "dark_current_a": 0.0,
    "bandwidth_hz": None,               # no pole
    "gain_ohm": 1e4,
    "gain": 10.0,                       # V/V
    "sample_rate_hz": 100e6,
    "full_scale_v": 1.0,
    "bias_a": 0.03,                     # above the default threshold: a default driver lights a default laser
    "gain_a_per_v": 0.01,
    "threshold_a": 0.01,
    "slope_w_per_a": 0.3,
    "heater_resistance_ohm": 1000.0,
}
ELECTRICAL_NOTE = "electrical: first-order poles, no noise (model)"
SOLVER_PARAMS = ("heater", "drive", "power", "phase")   # a part's solver params an input may set over time
WIRES = frozenset({"Resistor", "Capacitor", "Ground", "ElectricalPad"})     # wires and terminals: no block


@dataclass(frozen=True)
class Block:
    """A part's electrical model. ``inputs``: each port it reads and the units it takes; ``outputs``: the ports it
    drives; ``parameters``: the part's numbers it reads (the notes name them); ``run(walk, sid, part, signals)``
    returns ``{port or solver key: Waveform}``. ``light``: it reads the optical power at the part, so it runs after the
    optics. A reader (a scope) has no ``run``."""

    inputs: dict[str, tuple[str, ...]]
    outputs: tuple[str, ...]
    parameters: tuple[str, ...]
    run: Callable[..., dict[str, Waveform]] | None
    light: bool = False


def _detector(walk, sid, part, got):
    live = [port for port in ("e1", "e2") if walk.feeds((sid, port))]
    if len(live) > 1:
        raise AnimationError(f"{sid}: e1 and e2 both feed an input; take one side to a bias or a ground")
    current = photocurrent(got["light"], *walk.numbers(part, "responsivity_a_per_w", "dark_current_a", "bandwidth_hz"))
    return dict.fromkeys(live, current)


def _amplified_detector(walk, sid, part, got):
    current = photocurrent(got["light"], *walk.numbers(part, "responsivity_a_per_w", "dark_current_a", "bandwidth_hz"))
    return {"out": transimpedance(current, *walk.numbers(part, "gain_ohm"))}


def _op_amp(walk, sid, part, got):
    """A transimpedance stage: ``Rf`` is the one resistor from the ``in_n`` net to the ``out`` net, ``Cf`` the sum of
    the capacitors there."""

    nets = {walk.net((sid, "in_n")), walk.net((sid, "out"))}
    feedback = [(other_sid, other) for other_sid, other in walk.parts.items()
                if other.component_type in ("Resistor", "Capacitor")
                and {walk.net((other_sid, "e1")), walk.net((other_sid, "e2"))} == nets]
    resistors = [(other_sid, other) for other_sid, other in feedback if other.component_type == "Resistor"]
    if len(resistors) != 1:
        raise AnimationError(f"{sid}: an op amp needs one resistor from in_n to out, not {len(resistors)}; the in_n "
                             f"net holds {walk.names(walk.net((sid, 'in_n')))}")
    rf = walk.value(*resistors[0], "ohm")
    cf = sum(walk.value(other_sid, other, "F") for other_sid, other in feedback if other.component_type == "Capacitor")
    return {"out": transimpedance(got["in_n"], *feedback_tia(rf, cf))}


def _tia(walk, sid, part, got):
    return {"out": transimpedance(got["in"], *walk.numbers(part, "gain_ohm", "bandwidth_hz"))}


def _amplifier(walk, sid, part, got):
    return {"out": amplify(got["in"], *walk.numbers(part, "gain", "bandwidth_hz"))}


def _adc(walk, sid, part, got):
    return {"dout": sample(got["in"], int(part.bit_count), *walk.numbers(part, "sample_rate_hz", "full_scale_v"))}


def _dac(walk, sid, part, got):
    rate, full_scale = walk.numbers(part, "sample_rate_hz", "full_scale_v")
    return {"out": hold(clock(got["din"], rate, walk.t_ns), int(part.bit_count), full_scale, walk.t_ns)}


def _driver(walk, sid, part, got):
    bias, gain = walk.numbers(part, "bias_a", "gain_a_per_v")
    return {"out": Waveform(got["mod"].t_ns, bias + gain * got["mod"].values, "A")}


def _modulator(walk, sid, part, got):
    return {f"drive:{sid}": got["sig"]}


def _laser(walk, sid, part, got):
    return {f"power:{sid}": laser_power(got["e1"], *walk.numbers(part, "threshold_a", "slope_w_per_a"))}


def _heater(walk, sid, part, got):
    return {f"heater:{sid}": heater_power(got["e1"], *walk.numbers(part, "heater_resistance_ohm"))}


_A, _V = ("A",), ("V",)
_DETECTOR = ("responsivity_a_per_w", "dark_current_a", "bandwidth_hz")
_CONVERTER = ("bit_count", "sample_rate_hz", "full_scale_v")
_LASER = ("threshold_a", "slope_w_per_a")

BLOCKS: dict[str, Block] = {
    "Photodiode": Block({}, ("e1", "e2"), _DETECTOR, _detector, light=True),
    "OnChipPhotodetector": Block({}, ("e1", "e2"), _DETECTOR, _detector, light=True),
    "AmplifiedPhotodetector": Block({}, ("out",), _DETECTOR + ("gain_ohm",), _amplified_detector, light=True),
    "OpAmp": Block({"in_n": _A}, ("out",), (), _op_amp),
    "TIABlock": Block({"in": _A}, ("out",), ("gain_ohm", "bandwidth_hz"), _tia),
    "Amplifier": Block({"in": _V}, ("out",), ("gain", "bandwidth_hz"), _amplifier),
    "ADCBlock": Block({"in": _V}, ("dout",), _CONVERTER, _adc),
    "DAC": Block({"din": ("code",)}, ("out",), _CONVERTER, _dac),
    "LaserDriver": Block({"mod": _V}, ("out",), ("bias_a", "gain_a_per_v"), _driver),
    "MZM": Block({"sig": _V}, (), (), _modulator),
    "Laser": Block({"e1": _A}, (), _LASER, _laser),
    "OnChipLaser": Block({"e1": _A}, (), _LASER, _laser),
    "MicroringResonator": Block({"e1": _V}, (), ("heater_resistance_ohm",), _heater),
    "Oscilloscope": Block({"ch1": ("V", "code"), "ch2": ("V", "code")}, (), (), None),
    "LockInAmplifier": Block({"in": _V}, (), (), None),
}


@dataclass(frozen=True, eq=False)
class Chain:
    """``waveforms["<sid>:<port>"]``: the signal at every port of every net that carries one. ``notes`` say what is
    model."""

    waveforms: dict[str, Waveform]
    notes: tuple[str, ...]
    sids: dict[int, str] = field(default_factory=dict, repr=False)     # id(part) -> its sid in ``waveforms``

    def at(self, part: Any, port: str) -> Waveform:
        """The signal at ``part``'s ``port``."""

        key = f"{self.sids.get(id(part), '?')}:{port}"
        if key not in self.waveforms:
            raise KeyError(f"no signal at {key}; the chain has {', '.join(sorted(self.waveforms))}")
        return self.waveforms[key]

    def show(self, instrument: Any) -> None:
        """Put the computed signals on an instrument's screen: an ``Oscilloscope``'s traces at ``ch1`` and ``ch2``, a
        ``LockInAmplifier``'s reading (the mean at ``in``)."""

        from optodraw.components.instruments import screen_points          # loaded only when a screen is drawn

        kind = getattr(instrument, "component_type", type(instrument).__name__)
        if kind == "Oscilloscope":
            sid = self.sids.get(id(instrument), "?")
            traces = {port: screen_points(w.t_ns, w.values) for port in ("ch1", "ch2")
                      if (w := self.waveforms.get(f"{sid}:{port}")) is not None}
            if not traces:
                raise KeyError(f"no signal at {sid}:ch1 or {sid}:ch2; the chain has "
                               f"{', '.join(sorted(self.waveforms))}")
            instrument.traces = traces
        elif kind == "LockInAmplifier":
            w = self.at(instrument, "in")
            instrument.reading = f"{float(np.mean(w.values)):.3g} {w.unit}"
        else:
            raise ValueError(f"show draws on an Oscilloscope or a LockInAmplifier, not {kind}")


def signal_chain(scene: Any, *, t_ns, inputs=None, params: dict | None = None, strict: bool = True) -> Chain:
    """Every signal the drawn electronics carry on the uniform time grid ``t_ns``.

    ``inputs``: ``(key, Waveform)`` pairs, or a dict with string keys. A key is ``(part, port)`` for an electrical
    source at a port, ``(part, "heater")`` (or another of ``SOLVER_PARAMS``) for that part's solver param over time
    (a heater in mW), or a solver key string such as ``"heater:<sid>"``. Parts cannot be dict keys, hence the pairs.
    ``params`` are the static solver params. A part the signal reaches with no electrical model is an
    ``AnimationError`` when ``strict``; otherwise a note says the chain skips it.
    """

    walk = _Walk(scene, t_ns, inputs or (), dict(params or {}), strict)
    walk.run()
    return Chain(dict(walk.waveforms), walk.result_notes(), walk.sids)


class _Walk:
    """The nets (a union of the electrical links' ends), the signals on them, and the order the blocks run in."""

    def __init__(self, scene: Any, t_ns, inputs: dict, params: dict, strict: bool):
        self.scene, self.params, self.strict = scene, params, strict
        self.graph = build_graph(scene)
        self.parts = self.graph.parts
        self.sids = {id(part): sid for sid, part in self.parts.items()}
        self.t_ns = np.asarray(t_ns, dtype=float)
        if self.t_ns.ndim != 1 or not self.t_ns.size:
            raise ValueError(f"t_ns is a list of one time or more, not an array of shape {self.t_ns.shape}")
        if self.t_ns.size > 1:
            Waveform(self.t_ns, np.zeros(self.t_ns.size), "V").step_ns    # a grid that is not uniform: ValueError
        self.parent: dict[End, End] = {}
        for link in self.graph.links:
            if link.medium == "electrical":
                self.parent[self.net(link.a)] = self.net(link.b)
        self.members: dict[End, list[End]] = {}
        for end in list(self.parent):
            self.members.setdefault(self.net(end), []).append(end)
        self.waveforms: dict[str, Waveform] = {}
        self.optical: dict[str, Waveform] = {}       # solver key -> its value over time
        self.light: dict[str, np.ndarray] | None = None
        self.reached: set[str] = set()
        self.ran: list[str] = []
        self.notes: list[str] = []
        sources = self._sources(inputs)
        self._one_output_per_net(sources)
        for end, w in sources:
            self.drive(end, w, end[0])

    def net(self, end: End) -> End:
        while self.parent.setdefault(end, end) != end:
            end = self.parent[end]
        return end

    def names(self, root: End) -> str:
        return ", ".join(sorted({sid for sid, _ in self.members.get(root, [root])}))

    def block(self, sid: str) -> Block | None:
        part = self.parts.get(sid)
        return None if part is None else BLOCKS.get(part.component_type)

    def feeds(self, end: End) -> bool:
        """True when the net at ``end`` holds an input of another part's block."""

        return any(sid != end[0] and (block := self.block(sid)) is not None and port in block.inputs
                   for sid, port in self.members.get(self.net(end), ()))

    @staticmethod
    def numbers(part: Any, *names: str) -> list[float | None]:
        return [DEFAULTS[name] if getattr(part, name, None) is None else float(getattr(part, name)) for name in names]

    @staticmethod
    def value(sid: str, part: Any, unit: str) -> float:
        try:
            return parse_value(part.value, unit)
        except ValueError as error:
            raise AnimationError(f"{sid}: {error}") from error

    def _sources(self, inputs) -> list[tuple[End, Waveform]]:
        found = []
        for key, w in (inputs.items() if isinstance(inputs, Mapping) else inputs):
            if not isinstance(w, Waveform):
                raise TypeError(f"inputs[{key!r}] is a Waveform, not {type(w).__name__}")
            if w.unit != "code":                             # codes keep their own instants
                w = Waveform(self.t_ns, np.interp(self.t_ns, w.t_ns, w.values), w.unit)
            if isinstance(key, str):
                self.optical[key] = w
                continue
            part, port = key
            sid = self.sids.get(id(part))
            if sid is None:
                who = getattr(part, "label", "") or type(part).__name__
                raise AnimationError(f"{who}: an input part is not in the scene")
            if port in SOLVER_PARAMS and port not in part.ports():
                self.optical[f"{port}:{sid}"] = w              # the part's own solver param over time
                continue
            if port not in part.ports():
                raise AnimationError(f"{sid}: no port or solver param {port}; it has {', '.join(part.ports())} "
                                     f"and {', '.join(SOLVER_PARAMS)}")
            found.append(((sid, port), w))
        return found

    def _one_output_per_net(self, sources: list[tuple[End, Waveform]]) -> None:
        outputs: dict[End, list[End]] = {}
        for sid, part in self.parts.items():
            block = BLOCKS.get(part.component_type)
            for port in block.outputs if block is not None else ():
                if port in part.ports():
                    outputs.setdefault(self.net((sid, port)), []).append((sid, port))
        for end, _ in sources:
            outputs.setdefault(self.net(end), []).append(end)
        for root, ends in outputs.items():
            if len(ends) > 1:
                raise AnimationError(f"{ends[0][0]}: a net has {len(ends)} outputs "
                                     f"({', '.join(f'{sid}:{port}' for sid, port in ends)}) and carries one signal; "
                                     f"the net holds {self.names(root)}")

    def drive(self, end: End, w: Waveform, by: str) -> None:
        """Put ``w`` on the net at ``end``: every port of the net carries it."""

        for sid, port in self.members.get(self.net(end), [end]):
            part = self.parts.get(sid)
            if part is None:
                continue
            block = BLOCKS.get(part.component_type)
            if block is None and part.component_type not in WIRES:
                message = f"{sid}: no electrical model yet for {part.component_type}"
                if self.strict:
                    raise AnimationError(message)
                self.notes.append(f"{message}; the chain skips it")
            elif block is not None and port in block.inputs and w.unit not in block.inputs[port]:
                takes = block.inputs[port]
                if w.unit == "A" and "V" in takes:
                    raise AnimationError(f"{by}: a current reaches {sid}:{port}, a voltage input; add a TIA or a load")
                raise AnimationError(f"{sid}: {port} takes {' or '.join(takes)}, but {by} gives {w.unit}")
            self.waveforms[f"{sid}:{port}"] = w

    def run(self) -> None:
        """Run every block whose inputs are ready; when none is, solve the light once and run the detectors."""

        pending = {sid: block for sid in self.parts if (block := self.block(sid)) is not None and block.run is not None}
        while True:
            ready = [sid for sid, block in pending.items() if (self.light is not None or not block.light)
                     and all(f"{sid}:{port}" in self.waveforms for port in block.inputs)]
            if ready:
                for sid in ready:
                    self._run(sid, pending.pop(sid))
            elif self.light is None and any(block.light and any(self.feeds((sid, port)) for port in block.outputs)
                                            for sid, block in pending.items()):
                self._solve_light()
            else:
                return

    def _run(self, sid: str, block: Block) -> None:
        part = self.parts[sid]
        got = {port: self.waveforms[f"{sid}:{port}"] for port in block.inputs}
        if block.light:
            got["light"] = Waveform(self.t_ns, self.light.get(sid, np.zeros(self.t_ns.size)), "mW")
        try:
            out = block.run(self, sid, part, got)
        except AnimationError:
            raise
        except ValueError as error:
            raise AnimationError(f"{sid}: {error}") from error
        if out:
            self.ran.append(sid)
        for key, w in out.items():
            if ":" not in key:
                self.drive((sid, key), w, sid)
            elif self.light is not None:
                raise AnimationError(f"{sid}: a loop: {key} follows from light that the chain has already solved; "
                                     f"the chain solves the light once, with no feedback")
            elif key in self.optical:
                raise AnimationError(f"{sid}: {key} is set twice, by inputs and by the part's own input")
            else:
                self.optical[key] = w

    def _solve_light(self) -> None:
        """One steady state per time sample with the static params and each optical input's value at that sample;
        the same values are solved once."""

        keys = sorted(self.optical)
        solved: dict[tuple[float, ...], dict[str, float]] = {}
        power: dict[str, np.ndarray] = {}
        for k in range(self.t_ns.size):
            values = tuple(float(self.optical[key].values[k]) for key in keys)
            if values not in solved:
                # floor 0: every port keeps its record, however dark, as in the spectrum
                result = steady_state(self.graph, {**self.params, **dict(zip(keys, values))}, floor=0.0)
                solved[values] = ended_power(result)
                self.reached |= {key.split(":", 1)[0] for key in solved[values]}
                self.reached |= {edge.end[0] for edge in result.steady}
            for key, value in solved[values].items():
                power.setdefault(key, np.zeros(self.t_ns.size))[k] = value
        self.light = {}
        for key, values in power.items():
            sid = key.split(":", 1)[0]
            self.light[sid] = self.light.get(sid, 0.0) + values

    def result_notes(self) -> tuple[str, ...]:
        notes = []
        if self.light is not None:
            reached = [(sid, part) for sid, part in self.parts.items() if sid in self.reached]
            notes += [PHASE_NOTE, *model_numbers(self.scene, self.reached)]
            notes += [note for sid, part in reached for note in behaviour_for(part, sid).notes(part, sid)]
            notes += [note for sid, part in reached if hasattr(part, "power_mw")           # a laser nothing drives
                      and f"power:{sid}" not in self.optical and f"power:{sid}" not in self.params
                      for note in number_notes(getattr(part, "label", "") or sid, part, ("power_mw",))]
        notes.append(ELECTRICAL_NOTE)
        for sid in self.ran:
            part = self.parts[sid]
            notes += number_notes(getattr(part, "label", "") or sid, part, BLOCKS[part.component_type].parameters)
        return tuple(dict.fromkeys(notes + self.notes))
