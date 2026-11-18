"""Adapt checked signal states for timeline playback."""

from __future__ import annotations

import copy
import heapq
import itertools
import math

import numpy as np

from .errors import AnimationError
from .graph import build_graph
from .ids import path_id, port_id
from .signals import power
from .solver import Network, delay_ps
from .state import compile_signal_state


def _front_details(graph, params=None, *, inputs=(), heater_delay_scale=1.0):
    net = Network(graph, dict(params or {}), inputs, heater_delay_scale)
    heap, visited, fronts, terminals = [], set(), {}, {}
    counter = itertools.count()

    def push(t, kind, sid, port, wavelength, via=None):
        heapq.heappush(heap, (t, next(counter), kind, sid, port, wavelength, via))

    def record(edge, a, b, wavelength, t, length, index, extra=0.0):
        delay = delay_ps(length, index) + extra
        if not math.isfinite(delay) or delay < 0:
            raise AnimationError(f"{a[0]}: invalid delay on {edge}")
        key = edge, port_id(*a), port_id(*b), wavelength
        fronts.setdefault(key, (t, t + delay))
        return t + delay

    for sid, emission in net.emissions():
        if power(emission.jones) > 0:
            push(emission.t0_ps, "depart", sid, emission.port, emission.wavelength_nm)
    for sid, emission in net.injections():
        if power(emission.jones) > 0:
            push(emission.t0_ps, "arrive", sid, emission.port, emission.wavelength_nm)
    while heap:
        t, _, kind, sid, port, wavelength, via = heapq.heappop(heap)
        key = kind, sid, port, wavelength, via
        if key in visited:
            continue
        visited.add(key)
        if kind == "depart":
            if port.startswith("_"):
                push(t, "arrive", sid, port, wavelength)
                continue
            found = net.link_out(sid, port, via)
            if found is None:
                terminals.setdefault(("exit", sid, port, wavelength), t)
                continue
            link, far = found
            end = record(link.id, (sid, port), far, wavelength, t, link.length, link.group_index)
            push(end, "arrive", *far, wavelength, link.id)
        else:
            part = graph.parts[sid]
            if net.behaviour(sid).sinks(part, port):
                terminals.setdefault(("sink", sid, port, wavelength), t)
                continue
            for transfer in net.transfers(sid, port, wavelength):
                if not np.any(transfer.matrix):
                    continue
                edge = path_id(sid, transfer.in_port, transfer.out_port, transfer.name)
                end = record(edge, (sid, port), (sid, transfer.out_port), wavelength, t,
                             transfer.length, transfer.group_index, transfer.extra_delay_ps * net.heater_delay_scale)
                push(end, "depart", sid, transfer.out_port, wavelength,
                     via if transfer.out_port == port else None)
    return fronts, terminals


def front_times(graph, params=None, *, inputs=()):
    return _front_details(graph, params, inputs=inputs)[0]


def first_arrivals(graph, params=None, *, inputs=()):
    """When the first light reaches each end: ``{(kind, part, port, wavelength): t_ps}``, kind ``exit`` or ``sink``.

    One pass over the arrival fronts: the times do not depend on the pulse width."""

    return _front_details(graph, params, inputs=inputs)[1]


def compile_table(scene, *, mode, params=None, inputs=(), floor=None, strict=False, heater_delay_scale=1.0):
    """``heater_delay_scale`` multiplies the heaters' delays in the arrival fronts (a labelled display exaggeration)."""

    inputs = tuple(inputs)
    table = copy.deepcopy(compile_signal_state(scene, mode=mode, params=params, inputs=inputs,
                                               floor=floor, strict=strict).to_json())
    graph = build_graph(scene)
    links = {link.id: link for link in graph.links}
    table.update(params=copy.deepcopy(params or {}), inputs=[source.to_json() for source in inputs])
    fronts, terminals = (_front_details(graph, params, inputs=inputs, heater_delay_scale=heater_delay_scale)
                         if mode == "cw" else ({}, {}))
    for edge_id, edge in table["edges"].items():
        link = links.get(edge_id)
        for record in edge["packets"] + edge["cw"]:
            record["reverse"] = link is not None and record["from"] != port_id(*link.a)
            record["jones_reference"] = "entry" if link is not None else "exit"
        for packet in edge["packets"]:
            packet["shape"] = "gauss"
        for record in edge["cw"]:
            key = edge_id, record["from"], record["to"], record["wavelength_nm"]
            record["t0"], record["t1"] = fronts[key]
    if mode == "cw":
        for kind, name in (("sink", "absorbed"), ("exit", "exits")):
            for record in table[name]:
                record["t_ps"] = terminals[(kind, record["part"], record["port"], record["wavelength_nm"])]
        table["duration_ps"] = extent_time_ps(table)
    return table


def terminal_time_ps(table):
    records = table["absorbed"] or table["exits"]
    return max((record["t_ps"] for record in records), default=extent_time_ps(table))


def extent_time_ps(table):
    ends = [record["t_ps"] for name in ("absorbed", "exits") for record in table[name]]
    ends += [record["t1"] for edge in table["edges"].values() for record in edge["packets"] + edge["cw"]]
    return max(ends, default=0.0)
