"""Propagate light through the signal graph: pulses as packets in time; continuous light as a steady state."""

from __future__ import annotations

import cmath
import heapq
import itertools
import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from .behaviours import Behaviour, Transfer, behaviour_for, find_behaviour
from .errors import AnimationError, NotModelledYet
from .graph import Link, SignalGraph
from .ids import path_id
from .signals import C_UM_PER_PS, power, to_json

End = tuple[str, str]


@dataclass(frozen=True)
class Packet:
    edge: str
    start: End
    end: End
    t0_ps: float
    t1_ps: float
    jones: np.ndarray
    wavelength_nm: float
    width_ps: float
    source: str


@dataclass(frozen=True)
class SteadyEdge:
    edge: str
    start: End
    end: End
    wavelength_nm: float
    jones: np.ndarray


@dataclass
class Propagation:
    packets: list[Packet] = field(default_factory=list)
    steady: list[SteadyEdge] = field(default_factory=list)
    exits: list[dict] = field(default_factory=list)
    absorbed: list[dict] = field(default_factory=list)
    edges: dict[str, dict] = field(default_factory=dict)
    bucket_of: dict[int, int] = field(default_factory=dict)    # part packet index -> the bucket its light left in

    def note_edge(self, edge: str, points, length: float, group_index: float) -> None:
        self.edges.setdefault(edge, {"points": tuple(points), "length_um": float(length), "group_index": float(group_index)})


def delay_ps(length_um: float, group_index: float) -> float:
    return length_um * group_index / C_UM_PER_PS


def phase_factor(length_um: float, group_index: float, wavelength_nm: float) -> complex:
    return cmath.exp(1j * 2.0 * math.pi * group_index * length_um / (wavelength_nm / 1000.0))


def _carried(tr: Transfer, wavelength_nm: float) -> complex:
    """The propagation phase the solver adds to a transfer: none when its matrix holds the whole phase."""

    return 1.0 if tr.phase_included else phase_factor(tr.length, tr.group_index, wavelength_nm)


class Network:
    """Behaviours, transfers and links of one graph, cached. ``heater_delay_scale`` multiplies each transfer's heater
    delay (a display exaggeration; 1 is the true delay); it never changes a phase."""

    def __init__(self, graph: SignalGraph, params: dict[str, Any], inputs=(), heater_delay_scale: float = 1.0):
        self.graph, self.params = graph, params
        self.heater_delay_scale = float(heater_delay_scale)
        self.inputs = tuple(inputs)
        for source in self.inputs:
            source.validate(graph)
        self._behaviours: dict[str, Behaviour] = {}
        self._transfers: dict[tuple[str, str, float], list[Transfer]] = {}

    def behaviour(self, sid: str) -> Behaviour:
        if sid not in self._behaviours:
            self._behaviours[sid] = behaviour_for(self.graph.parts[sid], sid)
        return self._behaviours[sid]

    def transfers(self, sid: str, port: str, wavelength_nm: float) -> list[Transfer]:
        key = (sid, port, wavelength_nm)
        if key not in self._transfers:
            self._transfers[key] = self.behaviour(sid).transfers(self.graph.parts[sid], sid, port, wavelength_nm, self.params)
        return self._transfers[key]

    def emissions(self):
        found = []
        for sid, part in self.graph.parts.items():
            behaviour = find_behaviour(part)
            if behaviour is not None:
                found += [(sid, e) for e in behaviour.emissions(part, sid, self.params)]
        found += [(source.endpoint[0], source.emission()) for source in self.inputs if source.direction == "out"]
        if not found and not self.inputs:
            raise AnimationError("the scene has no light source")
        return found

    def injections(self):
        return [(source.endpoint[0], source.emission()) for source in self.inputs if source.direction == "in"]

    def link_out(self, sid: str, port: str, arrived_on: str | None) -> tuple[Link, End] | None:
        attached = [(link, far) for link, far in self.graph.links_at(sid, port) if link.medium != "electrical"]
        if arrived_on is not None and len(attached) > 1:
            attached = [(link, far) for link, far in attached if link.id != arrived_on]
        if len(attached) > 1:
            raise NotModelledYet(f"{sid}: port {port} has {len(attached)} connections; light cannot choose one")
        return attached[0] if attached else None


def propagate_pulses(graph: SignalGraph, params: dict[str, Any] | None = None, *, floor: float = 1e-3,
                     max_events: int = 200_000, inputs=(), heater_delay_scale: float = 1.0) -> Propagation:
    net = Network(graph, dict(params or {}), inputs, heater_delay_scale)
    result = Propagation()
    heap: list = []
    order = itertools.count()

    def push(t: float, kind: str, item: Any) -> None:
        heapq.heappush(heap, (t, next(order), kind, item))

    for sid, e in net.emissions():
        push(e.t0_ps, "depart", {"sid": sid, "port": e.port, "t": e.t0_ps, "jones": e.jones, "wl": e.wavelength_nm,
                                 "width": e.width_ps, "source": sid, "via": None, "p0": power(e.jones)})
    for sid, e in net.injections():
        push(e.t0_ps, "arrive", {"sid": sid, "port": e.port, "t": e.t0_ps, "jones": e.jones, "wl": e.wavelength_nm,
                                "width": e.width_ps, "source": f"port:{sid}:{e.port}", "via": None, "p0": power(e.jones)})
    buckets: dict[tuple, dict] = {}
    numbers = itertools.count()
    events = 0
    while heap:
        _, _, kind, item = heapq.heappop(heap)
        events += 1
        if events > max_events:
            sid = item[0] if kind == "flush" else item["sid"]
            raise AnimationError(f"{sid}: light keeps circulating; a loop near this part has a gain of 1 or more")
        if kind == "depart":
            key = (item["sid"], item["port"], item["wl"], item["source"], item["via"])
            if key in buckets:
                buckets[key]["sum"] = buckets[key]["sum"] + item["jones"]
            else:
                buckets[key] = dict(item, sum=item["jones"], bucket=next(numbers))
                push(item["t"] + item["width"], "flush", key)
            if item.get("packet") is not None:
                result.bucket_of[item["packet"]] = buckets[key]["bucket"]
        elif kind == "flush":
            _send(net, result, push, buckets.pop(item), floor)
        else:
            _arrive(net, result, push, item)
    check_causality(result)
    return result


def _send(net: Network, result: Propagation, push, bucket: dict, floor: float) -> None:
    """Coherent sum of what leaves one port within one pulse width, then along its link."""

    jones, t, sid, port = bucket["sum"], bucket["t"], bucket["sid"], bucket["port"]
    if power(jones) < floor * bucket["p0"]:
        return
    if port.startswith("_"):
        push(t, "arrive", dict(bucket, jones=jones, via=None))
        return
    found = net.link_out(sid, port, bucket["via"])
    if found is None:
        result.exits.append({"part": sid, "port": port, "t_ps": t, "power": power(jones), "wavelength_nm": bucket["wl"],
                             "jones": to_json(jones), "width": bucket["width"], "source": bucket["source"]})
        return
    link, far = found
    start = (sid, port)
    result.note_edge(link.id, link.points, link.length, link.group_index)
    arrival = t + delay_ps(link.length, link.group_index)
    shifted = jones * phase_factor(link.length, link.group_index, bucket["wl"])
    result.packets.append(Packet(link.id, start, far, t, arrival, jones, bucket["wl"], bucket["width"], bucket["source"]))
    push(arrival, "arrive", dict(bucket, sid=far[0], port=far[1], t=arrival, jones=shifted, via=link.id))


def _arrive(net: Network, result: Propagation, push, item: dict) -> None:
    sid, port, t = item["sid"], item["port"], item["t"]
    part = net.graph.parts[sid]
    behaviour = net.behaviour(sid)
    if behaviour.sinks(part, port):
        result.absorbed.append({"part": sid, "port": port, "t_ps": t, "power": power(item["jones"]),
                                "wavelength_nm": item["wl"]})
        return
    transfers = net.transfers(sid, port, item["wl"])
    if not transfers:
        raise NotModelledYet(f"{sid}: light arrives at {port} and has nowhere to go")
    for tr in transfers:
        out = (tr.matrix @ item["jones"]) * _carried(tr, item["wl"])
        leave = t + delay_ps(tr.length, tr.group_index) + tr.extra_delay_ps * net.heater_delay_scale   # the phase has no delay term
        edge = path_id(sid, tr.in_port, tr.out_port, tr.name)
        result.note_edge(edge, tr.points, tr.length, tr.group_index)
        result.packets.append(Packet(edge, (sid, tr.in_port), (sid, tr.out_port), t, leave, out, item["wl"],
                                     item["width"], item["source"]))
        via = item["via"] if tr.out_port == tr.in_port else None
        push(leave, "depart", dict(item, port=tr.out_port, t=leave, jones=out, via=via, packet=len(result.packets) - 1))


def _round_trips(part: Any, sid: str, wavelength_nm: float, params: dict[str, Any] | None) -> dict[str, complex]:
    """For each ring of ``part`` (``Behaviour.rings``): its round-trip amplitude at ``wavelength_nm`` with the ring's phase
    and heater at zero, the product of the part's own transfers round the ring with their propagation phase."""

    behaviour = find_behaviour(part)
    found: dict[str, complex] = {}
    for key, loop in behaviour.rings(part, sid) if behaviour is not None else ():
        cold = {name: value for name, value in (params or {}).items() if name != key.replace("phase:", "heater:", 1)}
        cold[key] = 0.0
        trip = 1.0 + 0j
        for here, there in zip(loop, loop[1:] + loop[:1]):
            (tr,) = [tr for tr in behaviour.transfers(part, sid, here, wavelength_nm, cold) if tr.out_port == there]
            trip *= complex(tr.matrix[0, 0]) * _carried(tr, wavelength_nm)
        found[key] = trip
    return found


def resonance_phases(part: Any, sid: str, wavelength_nm: float, params: dict[str, Any] | None = None) -> dict[str, float]:
    """For each ring of ``part`` (``Behaviour.rings``): the value of its ``phase`` key that closes its round trip at
    ``wavelength_nm``, so that the wavelength sits on the ring's nearest resonance. The round trip is the product of the
    part's own transfers round the ring, with their propagation phase, at the ring's phase and heater of zero; the
    value lies in [-pi, pi]."""

    return {key: -cmath.phase(trip) for key, trip in _round_trips(part, sid, wavelength_nm, params).items()}


def ring_linewidths(part: Any, sid: str, wavelength_nm: float, params: dict[str, Any] | None = None) -> dict[str, float]:
    """For each ring of ``part``: the full width at half maximum of its resonance, in the units of its ``phase`` key
    (radians of round-trip phase). With the round-trip amplitude ``r`` (the magnitude of the ring's own round trip,
    ``resonance_phases``), the ring's transfers follow a Lorentzian of this width near a resonance:
    ``2 (1 - r) / sqrt(r)``."""

    return {key: 2.0 * (1.0 - abs(trip)) / math.sqrt(abs(trip))
            for key, trip in _round_trips(part, sid, wavelength_nm, params).items()}


def check_causality(result: Propagation) -> None:
    for packet in result.packets:
        if packet.t1_ps < packet.t0_ps - 1e-12:
            raise AnimationError(f"{packet.start[0]}: light leaves {packet.edge} before it enters")


def steady_state(graph: SignalGraph, params: dict[str, Any] | None = None, *, floor: float = 1e-9, inputs=()) -> Propagation:
    """Continuous light: the steady amplitudes everywhere, one linear solve per wavelength."""

    net = Network(graph, dict(params or {}), inputs)
    result = Propagation()
    by_wavelength: dict[float, list] = {}
    for sid, e in net.emissions():
        by_wavelength.setdefault(e.wavelength_nm, []).append((sid, e, "out"))
    for sid, e in net.injections():
        by_wavelength.setdefault(e.wavelength_nm, []).append((sid, e, "in"))
    for wavelength, emissions in by_wavelength.items():
        _steady_at(net, result, wavelength, emissions, floor)
    return result


def _steady_at(net: Network, result: Propagation, wl: float, emissions, floor: float) -> None:
    """The unknowns are the amplitudes that leave each port, keyed (part, port, link it arrived on)."""

    index: dict[tuple, int] = {}
    order: list[tuple] = []
    feeds: list[tuple[int, int, np.ndarray, str, Transfer]] = []

    def node(key: tuple) -> int:
        if key not in index:
            index[key] = len(order)
            order.append(key)
        return index[key]

    sources = {}
    for sid, e, direction in emissions:
        key = node((sid, e.port, "@input" if direction == "in" else None))
        sources[key] = sources.get(key, np.zeros(2, dtype=complex)) + e.jones
    todo = list(sources)
    seen: set[int] = set()
    sinks: list[tuple[int, str, str, complex]] = []
    while todo:
        i = todo.pop()
        if i in seen:
            continue
        seen.add(i)
        sid, port, via = order[i]
        if port.startswith("_") or via == "@input":
            far_sid, far_port, link_id, link_phase = sid, port, None, 1.0
        else:
            found = net.link_out(sid, port, via)
            if found is None:
                continue                                           # it exits: recorded after the solve
            link, (far_sid, far_port) = found
            link_id, link_phase = link.id, phase_factor(link.length, link.group_index, wl)
        part = net.graph.parts[far_sid]
        if net.behaviour(far_sid).sinks(part, far_port):
            sinks.append((i, far_sid, far_port, link_phase))
            continue
        transfers = net.transfers(far_sid, far_port, wl)
        if not transfers:
            raise NotModelledYet(f"{far_sid}: light arrives at {far_port} and has nowhere to go")
        for tr in transfers:
            if not np.any(tr.matrix):
                continue                                           # no light goes this way (the arrival fronts skip it too)
            out_via = link_id if tr.out_port == tr.in_port else None
            j = node((far_sid, tr.out_port, out_via))
            matrix = tr.matrix * _carried(tr, wl) * link_phase
            feeds.append((j, i, matrix, far_sid, tr))
            todo.append(j)
    n = len(order)
    feedback = np.zeros((2 * n, 2 * n), dtype=complex)
    rhs = np.zeros(2 * n, dtype=complex)
    for j, i, matrix, _, _ in feeds:
        feedback[2 * j:2 * j + 2, 2 * i:2 * i + 2] += matrix
    for i, vector in sources.items():
        rhs[2 * i:2 * i + 2] += vector
    _check_loop_gain(feedback, order)
    solution = np.linalg.solve(np.eye(2 * n) - feedback, rhs)
    for key, i in index.items():
        sid, port, via = key
        leave = solution[2 * i:2 * i + 2]
        if port.startswith("_") or via == "@input" or power(leave) < floor:
            continue
        found = net.link_out(sid, port, via)
        if found is None:
            result.exits.append({"part": sid, "port": port, "t_ps": 0.0, "power": power(leave), "wavelength_nm": wl,
                                 "jones": to_json(leave)})
            continue
        link, far = found
        result.note_edge(link.id, link.points, link.length, link.group_index)
        result.steady.append(SteadyEdge(link.id, (sid, port), far, wl, leave))
    for j, i, matrix, far_sid, tr in feeds:
        carried = matrix @ solution[2 * i:2 * i + 2]
        if power(carried) < floor:
            continue
        edge = path_id(far_sid, tr.in_port, tr.out_port, tr.name)
        result.note_edge(edge, tr.points, tr.length, tr.group_index)
        result.steady.append(SteadyEdge(edge, (far_sid, tr.in_port), (far_sid, tr.out_port), wl, carried))
    for i, far_sid, far_port, link_phase in sinks:
        arrived = solution[2 * i:2 * i + 2] * link_phase
        result.absorbed.append({"part": far_sid, "port": far_port, "t_ps": 0.0, "power": power(arrived), "wavelength_nm": wl})


def _check_loop_gain(feedback: np.ndarray, order: list[tuple]) -> None:
    """Continuous light settles only when every loop loses power: the feedback's spectral radius is below 1.

    Nodes that no loop passes through (nothing feeds them, or they feed nothing that is kept) are
    dropped first; they add only zero eigenvalues. The error names the part that weighs most in the
    loop's left and right eigenvectors, which is a part on the loop.
    """

    nodes = len(order)
    linked = np.abs(feedback).reshape(nodes, 2, nodes, 2).sum(axis=(1, 3)) > 0      # [j, i]: i feeds j
    keep = np.ones(nodes, dtype=bool)
    while True:
        sub = linked & keep[:, None] & keep[None, :]
        on_loop = keep & sub.any(axis=0) & sub.any(axis=1)
        if (on_loop == keep).all():
            break
        keep = on_loop
    kept = np.flatnonzero(keep)
    if not kept.size:
        return
    rows = np.repeat(2 * kept, 2) + np.tile([0, 1], kept.size)
    block = feedback[np.ix_(rows, rows)]
    values, right = np.linalg.eig(block)
    k = int(np.argmax(np.abs(values)))
    if abs(values[k]) < 1.0 - 1e-12:
        return
    left_values, left = np.linalg.eig(block.T)
    weight = np.abs(right[:, k]) * np.abs(left[:, int(np.argmin(np.abs(left_values - values[k])))])
    sid = order[kept[int(np.argmax(weight)) // 2]][0]
    raise AnimationError(f"{sid}: the light has no steady state (a loop with a gain of 1 or more)")


def check_passivity(graph: SignalGraph, result: Propagation, params: dict[str, Any] | None = None) -> None:
    """Every passive part the light reached gives out at most the power it takes in, for any mix of inputs.

    The part's matrix maps every optical input port and polarisation to every output; its largest
    singular value squared is the largest power gain over all inputs added together.
    """

    net = Network(graph, dict(params or {}))
    reached = {p.start[0] for p in result.packets} | {s.start[0] for s in result.steady}
    wavelengths = {p.wavelength_nm for p in result.packets} | {s.wavelength_nm for s in result.steady}
    bases = (np.array([1, 0], dtype=complex), np.array([0, 1], dtype=complex))
    for sid in sorted(reached):
        part = graph.parts.get(sid)
        if part is None or not net.behaviour(sid).passive:
            continue
        ports = [name for name, spec in part.ports().items() if spec.kind != "electrical"]
        for wl in sorted(wavelengths):
            columns = [_part_outputs(net, sid, port, basis, wl) for port in ports for basis in bases]
            outs = sorted({out for column in columns for out in column})
            if not outs:
                continue
            matrix = np.array([np.concatenate([column.get(out, np.zeros(2)) for out in outs]) for column in columns]).T
            gain = float(np.linalg.svd(matrix, compute_uv=False)[0]) ** 2
            if gain > 1.0 + 1e-9:
                raise AnimationError(f"{sid}: a passive part gives out more power than it takes in ({gain:.3f})")


def _part_outputs(net: Network, sid: str, in_port: str, basis: np.ndarray, wl: float) -> dict[str, np.ndarray]:
    """Output amplitude at each port for one input at one port of one part, its internal loops summed."""

    first = net.transfers(sid, in_port, wl)
    def internal(port):
        return port.startswith("_") and not net.behaviour(sid).sinks(net.graph.parts[sid], port)
    inside_ports: list[str] = []
    feeds: list[tuple[str, str, np.ndarray]] = []
    todo = [tr.out_port for tr in first if internal(tr.out_port)]
    while todo:
        port = todo.pop()
        if port in inside_ports:
            continue
        inside_ports.append(port)
        for tr in net.transfers(sid, port, wl):
            feeds.append((tr.out_port, port, tr.matrix * _carried(tr, wl)))
            if internal(tr.out_port):
                todo.append(tr.out_port)
    index = {port: k for k, port in enumerate(inside_ports)}
    n = len(inside_ports)
    big = np.eye(2 * n, dtype=complex)
    rhs = np.zeros(2 * n, dtype=complex)
    outputs: dict[str, np.ndarray] = {}
    for tr in first:
        carried = (tr.matrix * _carried(tr, wl)) @ basis
        if internal(tr.out_port):
            rhs[2 * index[tr.out_port]:2 * index[tr.out_port] + 2] += carried
        else:
            outputs[tr.out_port] = outputs.get(tr.out_port, 0) + carried
    for out, src, matrix in feeds:
        if internal(out):
            big[2 * index[out]:2 * index[out] + 2, 2 * index[src]:2 * index[src] + 2] -= matrix
    inside = np.linalg.solve(big, rhs) if n else np.zeros(0, dtype=complex)
    for out, src, matrix in feeds:
        if not internal(out):
            outputs[out] = outputs.get(out, 0) + matrix @ inside[2 * index[src]:2 * index[src] + 2]
    return outputs
