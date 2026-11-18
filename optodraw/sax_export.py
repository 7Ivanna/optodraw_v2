"""Export a scene to SAX: the same circuit, so SAX computes the spectrum that optodraw computes.

``to_sax`` writes a SAX netlist (instances, connections, ports) and one model per part. Each optical link is a
``straight`` instance with the solver's phase, exp(+i 2 pi n_g L / lambda). A part with an imported table
(``part.model``) gives its table. Any other part gives its behaviour's transfers, sampled at the given wavelengths
with its internal loops summed. Sources and detectors are not instances: the link ends at them are the circuit ports.

SAX keys run (in, out); optodraw tables run (out, in). SAX wavelengths are in um; optodraw wavelengths are in nm.
The models are numpy, not JAX: ``sax.circuit`` runs them, but ``jax.jit`` and ``jax.grad`` over the circuit do not.
JAX computes in float32 by default. For optodraw's float64, call ``jax.config.update("jax_enable_x64", True)`` first.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import numpy as np

from optodraw.animation_engine.errors import NotModelledYet
from optodraw.animation_engine.graph import build_graph
from optodraw.animation_engine.solver import Network, _part_outputs
from optodraw.provenance import Source
from optodraw.sparameters import SParameters, check

_TE = np.array([1, 0], dtype=complex)               # the input polarisation; the output's first entry is Jones xx


@dataclass(frozen=True)
class SaxCircuit:
    """``sax.circuit(netlist, models)`` runs the scene. ``ports`` gives the part port behind each circuit port, as
    ``"<sid>:<port>"``: ``in<k>`` is at a source, ``out<k>`` is at a detector."""

    netlist: dict
    models: dict[str, Callable]
    ports: dict[str, str]


def straight(wl: Any = 1.55, length: Any = 0.0, group_index: Any = 1.0) -> dict:
    """A link, both ways: exp(+i 2 pi n_g L / lambda), the solver's ``phase_factor``. ``wl`` and ``length`` are in um."""

    t = np.exp(2j * np.pi * np.asarray(group_index, dtype=float) * np.asarray(length, dtype=float)
               / np.asarray(wl, dtype=float))
    return {("o1", "o2"): t, ("o2", "o1"): t}


def to_sax(scene: Any, *, wavelengths_nm) -> SaxCircuit:
    """The scene as a SAX circuit. Run ``circuit, _ = sax.circuit(c.netlist, c.models)``, then ``circuit(wl=...)``
    with ``wl`` in um. ``|S[("in0", "out0")]|^2`` is the power that ``spectrum`` gives at the detector behind ``out0``,
    for a power of 1 at the source behind ``in0``.

    A part with no imported table is sampled at ``wavelengths_nm`` and interpolated as ``SParameters.at`` does: it is
    exact at those wavelengths, and SAX gets an error outside them. TE only: each model is the Jones xx component.
    Light that a part absorbs inside (an isolator's back port, for example) is a loss in SAX, not a port.
    """

    graph = build_graph(scene)
    net = Network(graph, {})
    sources = {sid for sid, _ in net.emissions()}
    links = [link for link in graph.links if link.medium != "electrical"]
    models: dict[str, Callable] = {"straight": straight}
    instances: dict[str, dict] = {}
    for sid in dict.fromkeys(sid for link in links for sid, _ in (link.a, link.b)):
        if sid in sources:
            continue
        part = graph.parts[sid]
        table = getattr(part, "model", None)
        if isinstance(table, SParameters):
            check(table, part, sid)
        else:
            table = _sampled(net, sid, wavelengths_nm)
            if table is None:
                continue                                    # no light leaves the part: a detector
        models[sid] = _table_model(table)
        instances[sid] = {"component": sid}
    connections: dict[str, str] = {}
    circuit_ports: dict[str, str] = {}
    ports: dict[str, str] = {}
    for link in links:
        name = link.id.split(":", 1)[1].replace(":", "_")     # route:route1 -> route1, beam:beam1:0 -> beam1_0
        instances[name] = {"component": "straight",
                           "settings": {"length": float(link.length), "group_index": float(link.group_index)}}
        for (sid, port), end in ((link.a, "o1"), (link.b, "o2")):
            if sid in models:                               # a part with a model is an instance
                if f"{sid},{port}" in connections.values():
                    raise NotModelledYet(f"{sid}: port {port} has more than one link (a fold); a SAX port takes one")
                connections[f"{name},{end}"] = f"{sid},{port}"
                continue
            kind = "in" if sid in sources else "out"
            external = f"{kind}{sum(key.startswith(kind) for key in ports)}"
            circuit_ports[external] = f"{name},{end}"
            ports[external] = f"{sid}:{port}"
    return SaxCircuit({"instances": instances, "connections": connections, "ports": circuit_ports}, models, ports)


def _sampled(net: Network, sid: str, wavelengths_nm) -> SParameters | None:
    """The part's transfers as a table: from each optical port to each, Jones xx, with its internal loops summed as
    the solver sums them. None when no light leaves the part (a detector)."""

    part = net.graph.parts[sid]
    behaviour = net.behaviour(sid)
    wavelengths = np.asarray(wavelengths_nm, dtype=float)
    ports = [name for name, spec in part.ports().items() if spec.kind not in ("electrical", "thermal")]
    s: dict[tuple[str, str], np.ndarray] = {}
    for k, wl in enumerate(wavelengths):
        for into in ports:
            if behaviour.sinks(part, into):
                continue                                    # light that arrives here ends here
            for out, amplitude in _part_outputs(net, sid, into, _TE, float(wl)).items():
                if not out.startswith("_"):                 # an absorber inside the part: a loss
                    s.setdefault((out, into), np.zeros(wavelengths.size, dtype=complex))[k] = amplitude[0]
    if not any(np.any(values) for values in s.values()):
        return None
    return SParameters(wavelengths, s, Source("model", note=f"{sid}: its optodraw transfers at "
                                                             f"{wavelengths.size} wavelengths"))


def _table_model(table: SParameters) -> Callable:
    """A SAX model of a table, ``wl`` in um. SAX calls it once with no arguments, so the default is in the table."""

    middle = float(table.wavelengths_nm[table.wavelengths_nm.size // 2]) / 1000.0

    def model(wl: Any = middle) -> dict:
        nm = np.asarray(wl, dtype=float) * 1000.0
        rows = [table.at(w) for w in nm.ravel()]
        return {(into, out): np.array([row[(out, into)] for row in rows]).reshape(nm.shape) for out, into in table.s}

    return model
