"""Where the light of each part edge is drawn, and how bright: the payload's profiles.

A profile is ``{"points": [[x, y], ...], "share": [...]}``: the points the player draws the edge on and the power at
each point over the edge's end power (the engine's packet power). Edges of one input that start along the same drawn
guide (a splitter's stem) get one: one of them draws the shared stretch at the power the light has there, the others
draw nothing there. Parts with coupling sections (couplers, rings, interferometers) are drawn by their rails
(``rails.py``) instead. Every number comes from the engine's transfer matrices; the player only multiplies.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from optodraw.animation_engine.behaviours import find_behaviour
from optodraw.animation_engine.behaviours.geometry import SAME_GUIDE_UM, distances, leading_run, power_gain
from optodraw.animation_engine.graph import build_graph
from optodraw.animation_engine.ids import path_id
from optodraw.animation_engine.signals import from_json, power


def _numbers(values, digits: int) -> list[float]:
    return [round(float(v), digits) for v in values]


def _profile(points, share) -> dict[str, Any]:
    return {"points": [_numbers(p, 4) for p in points], "share": _numbers(share, 6)}


def shared_stretch_shares(transfers: dict[str, Any], jones=None) -> dict[str, list[float]]:
    """``{edge id: share per point}`` for the transfers of one input whose paths start along the same guide (a
    splitter's stem); {} if none do.

    Powers are fractions of the input, ``g = |m j|^2 / |j|^2`` for each transfer matrix ``m`` and the input's Jones
    vector ``j`` (without one: ``|m|^2`` over both polarisations). Where paths have not yet parted the light is the
    input split among them in proportion to their end powers, ``sum g / total g``, and the strongest of them draws
    it; past the split each edge carries its own end power."""

    ids = sorted(transfers)
    if len(ids) < 2:
        return {}
    if jones is None or power(jones) <= 0:
        gain = {e: power_gain(transfers[e].matrix) for e in ids}
    else:
        gain = {e: power(np.asarray(transfers[e].matrix) @ jones) / power(jones) for e in ids}
    total = sum(gain.values())
    if total <= 0:
        return {}
    lead = {(e, f): leading_run(distances(transfers[e].points, transfers[f].points) <= SAME_GUIDE_UM) for e in ids for f in ids
            if e != f and len(transfers[f].points) >= 2}
    if all(n <= 1 for n in lead.values()):
        return {}
    out = {}
    for e in ids:
        others = [f for f in ids if (e, f) in lead]
        shares = []
        for i in range(len(transfers[e].points)):
            group = [e] + [f for f in others if lead[e, f] > i]
            power_here = sum(gain[f] for f in group) / total if len(group) > 1 else gain[e]
            owner = max(group, key=lambda f: (gain[f], -ids.index(f)))
            shares.append(power_here / gain[e] if owner == e and gain[e] > 0 else 0.0)
        out[e] = shares
    return out


def build_profiles(scene: Any, params: dict | None, pulse: dict[str, Any], graph: Any = None,
                   hidden=()) -> dict[str, dict[str, Any]]:
    """The profiles of the lit part edges of ``pulse`` (the engine's pulse state as JSON), leaving out ``hidden`` (the
    transfers that coupling sections draw)."""

    graph, params, hidden = graph or build_graph(scene), dict(params or {}), set(hidden)
    arriving: dict[tuple[str, str, float], Any] = {}             # the first light that reaches each port, its Jones vector
    for edge in pulse["edges"].values():
        for packet in edge["packets"]:
            key = (*packet["to"].split(":")[1:], packet["wavelength_nm"])
            if packet["to"].startswith("port:") and (key not in arriving or packet["t1"] < arriving[key][0]):
                arriving[key] = (packet["t1"], from_json(packet["jones"]))
    groups: dict[tuple[str, str], dict[float, list[str]]] = {}
    for eid, edge in pulse["edges"].items():
        if eid.startswith("path:") and eid not in hidden:
            sid, ports = eid.split(":")[1], eid.split(":", 2)[2].split("#")[0]
            for nm in {p["wavelength_nm"] for p in edge["packets"]}:
                groups.setdefault((sid, ports.split("->")[0]), {}).setdefault(nm, []).append(eid)
    profiles: dict[str, dict[str, Any]] = {}
    for (sid, in_port), by_wavelength in sorted(groups.items()):
        part = graph.parts[sid]
        behaviour = find_behaviour(part)
        for nm, lit in sorted(by_wavelength.items()):
            if all(eid in profiles for eid in lit):
                continue                                   # the same edges at another wavelength: already drawn
            transfers = {path_id(sid, t.in_port, t.out_port, t.name): t
                         for t in behaviour.transfers(part, sid, in_port, nm, params)}
            plain = {eid: transfers[eid] for eid in sorted(lit) if eid in transfers}
            jones = arriving.get((sid, in_port, nm), (None, None))[1]
            for eid, share in shared_stretch_shares(plain, jones).items():
                profiles.setdefault(eid, _profile(plain[eid].points, share))
    return profiles
