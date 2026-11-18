"""Coupling sections drawn one light per rail: the payload's ``rails``.

A part with coupler gaps (a directional or tap coupler, a ring, a ring filter, a weight bank, an MZI with couplers)
gives its coupling sections (``Behaviour.sections``). Each input of a section can be read from any transfer that
carries it (on through the coupler or across it, ``choose``). For each section and each engine bucket (the light the
engine adds coherently at one port), the section's two input fields come from the engine's packets, and coupled-mode
theory gives the field on each rail along the coupler:

    A(F) = cos(theta F) a1 + s sin(theta F) a2,    B(F) = s sin(theta F) a1 + cos(theta F) a2,

with ``sin^2(theta)`` the engine's power coupling, ``s`` the phase of its cross coefficient and ``F`` the transfer done
(0 to 1 along the window). At ``F = 1`` the rails carry the engine's own output; at every ``F`` the two rail powers add
up to the two input powers. Each rail is drawn as one light per bucket, at the bucket's time and at its own drawn
speed (``Clock``); the transfers it replaces are not drawn.

A rail drawing is ``{"host", "section", "rail", "points", "window": [first, last] | None, "packets": [{"t0", "t1",
"width", "wavelength_nm", "power": [...]}]}``: ``t0`` and ``t1`` are the times at the first and the last point, and
``power`` is the power at each point.
"""

from __future__ import annotations

import cmath
import math
from typing import Any

import numpy as np

from optodraw.animation_engine.behaviours import find_behaviour
from optodraw.animation_engine.behaviours.geometry import DISPLAY_STEP_UM, arc_lengths, cut, densify, transfer_done
from optodraw.animation_engine.signals import from_json, power

from .fieldmodel import _k_per_um, end_field, phase_of, wrap


def _stretch(points, start: float, end: float):
    """``(points, arc lengths on the rail)`` of a rail between two arc lengths, sampled every ``DISPLAY_STEP_UM``."""

    if end - start <= 1e-9:
        return [], []
    pts = densify(cut(points, start, end), 0.0, end - start)
    return list(pts), [start + s for s in arc_lengths(pts)]


def layout(section) -> list[dict[str, Any]]:
    """Per rail of a section: its drawn points, the full-rail arc length of each, the transfer done ``F`` at each (a
    coupler) and the fraction of the tail behind it (for the tail's loss), and the window's first and last index.
    The two windows of a coupler are sampled at the same fractions of their lengths, so ``F`` is the same there."""

    rails = section.rails
    if section.kappa is None:
        out = []
        for rail in rails:
            pts, arcs = _stretch(rail.points, *rail.draw)
            span = max(rail.draw[1] - rail.draw[0], 1e-12)
            out.append({"points": pts, "arcs": arcs, "done": None, "tail": [(s - rail.draw[0]) / span for s in arcs],
                        "window": None})
        return out
    longest = max(rail.window[1] - rail.window[0] for rail in rails)
    count = max(2, math.ceil(longest / DISPLAY_STEP_UM) + 1)
    windows = []
    for rail in rails:
        lo, hi = rail.window
        arcs = [lo + (hi - lo) * i / (count - 1) for i in range(count)]
        windows.append(([cut(rail.points, s, s)[0] for s in arcs], arcs))
    done = transfer_done(windows[0][0], windows[1][0])
    out = []
    for rail, (window, window_arcs) in zip(rails, windows):
        lead, lead_arcs = _stretch(rail.points, rail.draw[0], rail.window[0])
        tail, tail_arcs = _stretch(rail.points, rail.window[1], rail.draw[1])
        lead, lead_arcs, tail, tail_arcs = lead[:-1], lead_arcs[:-1], tail[1:], tail_arcs[1:]
        span = max(rail.draw[1] - rail.window[1], 1e-12)
        out.append({"points": lead + list(window) + tail, "arcs": lead_arcs + window_arcs + tail_arcs,
                    "done": [0.0] * len(lead) + list(done) + [1.0] * len(tail),
                    "tail": [0.0] * (len(lead) + count) + [(s - rail.window[1]) / span for s in tail_arcs],
                    "window": [len(lead), len(lead) + count - 1]})
    return out


CARRIES = 1e-9                  # a factor at or below this carries no light
SAME_INSTANT = 0.05             # buckets whose origins differ by less than this fraction of the pulse width are one instant


def _carries(read) -> bool:
    return any(abs(factor) > CARRIES for _, factor, _ in read.edges)


def _timed(read, pulse) -> bool:
    """False when every lit transfer of the read takes no time (a hop across a coupler gap)."""

    durations = [p["t1"] - p["t0"] for eid, factor, _ in read.edges if abs(factor) > CARRIES
                 for p in pulse["edges"].get(eid, {"packets": []})["packets"]]
    return not durations or max(durations) > 1e-12


def choose(section, pulse) -> tuple[list, bool]:
    """One read per input (None: nothing carries it), and whether they end at one port. All inputs of a section are
    read from transfers that carry them (a factor above 1e-9). The engine adds the packets that leave one port in one
    bucket, so a coupler's inputs are read where they end at one port when they can be: the port nearest after the
    window (where the engine has added the least other light: a ring's own port keeps its trips apart). Else each
    input is read on its own, from a transfer that takes time where it can, and its buckets pair by time
    (``_pair``)."""

    options = [[read for read in found if _carries(read)] for found in section.inputs]

    def rank(read):
        return 0 if _timed(read, pulse) else 1

    if section.kappa is not None and len(options) == 2:
        joint = [(a, b) for a in options[0] for b in options[1] if a.port == b.port]
        if joint:
            nearest = min(joint, key=lambda pair: (round(distance(section, *pair[0].end), 6), rank(pair[0]) + rank(pair[1])))
            return list(nearest), True
    chosen = [min(found, key=rank) if found else None for found in options]
    return chosen, len({read.port for read in chosen if read is not None}) <= 1


def distance(section, rail: int, arc: float) -> float:
    """The drawn distance at ``arc`` on ``rail`` from the window's start (a coupler; inside the window by its fraction
    of the windows' mean length) or from the rail's start (a stage): how far past the window a read ends."""

    if section.kappa is None:
        return arc
    lo, hi = section.rails[rail].window
    mean = sum(r.window[1] - r.window[0] for r in section.rails) / len(section.rails)
    if arc <= lo:
        return arc - lo
    if arc >= hi:
        return mean + arc - hi
    return (arc - lo) / (hi - lo) * mean


class Clock:
    """When the light is at each place of a section, from the time it reaches the clock's zero: a coupler's window start
    (on each rail: the inputs reach the window together) or a stage's start. Each rail has its own drawn speed, its
    arc length over the engine's time for a transfer along it (a ring is drawn at another scale than its bus): from a
    transfer that runs along that rail alone, else from one that crosses onto it from a rail of known speed."""

    def __init__(self, section, pulse: dict[str, Any]):
        self.section = section
        self.zero = [rail.window[0] if section.kappa is not None else 0.0 for rail in section.rails]
        timed = [(start, read.end, p["t1"] - p["t0"]) for found in section.inputs for read in found
                 for eid, _, start in read.edges for p in pulse["edges"].get(eid, {"packets": []})["packets"][:1]
                 if p["t1"] - p["t0"] > 1e-12]
        speeds: list[float | None] = [None] * len(section.rails)
        if section.kappa is None:                       # a stage: its rails lie on guides measured from one start
            v = next((((e[1] - s[1]) / d) for s, e, d in timed if e[1] > s[1] + 1e-9), None)
            speeds = [v] * len(section.rails)
        for (a, s0), (b, s1), duration in timed:        # along one rail
            if a == b and s1 > s0 + 1e-9 and speeds[a] is None:
                speeds[a] = (s1 - s0) / duration
        for (a, s0), (b, s1), duration in timed:        # onto a rail from one of known speed
            if a != b and speeds[a] and speeds[b] is None:
                rest = duration - (self.zero[a] - s0) / speeds[a]
                if rest > 1e-12 and s1 - self.zero[b] > 1e-9:
                    speeds[b] = (s1 - self.zero[b]) / rest
        known = [v for v in speeds if v]
        self.ok = bool(known)
        self.speeds = [v or (sum(known) / len(known) if known else None) for v in speeds]

    def at(self, rail: int, arc: float) -> float:
        """The time from the clock's zero to ``arc`` on ``rail``."""

        return (arc - self.zero[rail]) / self.speeds[rail]


def buckets(section, pulse: dict[str, Any], clock: Clock | None = None) -> list[dict[str, Any]]:
    """The section's buckets: the read packets that the engine added together as they left their end port (their
    ``bucket``), and, for inputs read at different ports, the buckets of one source and wavelength that reach the
    window together. Each gives the input fields (packet amplitude over the read's factor, summed), the time at the
    clock's zero (``origin``, from the packets' exit times) and the pulse width."""

    clock = clock or Clock(section, pulse)
    if not clock.ok:
        return []
    chosen, joint = choose(section, pulse)
    groups: dict[tuple, list] = {}
    for k, read in enumerate(chosen):
        for eid, factor, _ in read.edges if read is not None else ():
            edge = pulse["edges"].get(eid)
            if edge is None or abs(factor) <= CARRIES:
                continue
            for i, packet in enumerate(edge["packets"]):
                key = (packet["source"], packet["wavelength_nm"], packet.get("bucket", (eid, i)))
                groups.setdefault(key, []).append((k, packet, complex(factor), read.end))
    found = [b for b in (_bucket(section, clock, members, key) for key, members in groups.items()) if b is not None]
    found = found if joint else _pair(found)
    return sorted(found, key=lambda b: (b["origin"], b["source"], b["nm"]))


def _bucket(section, clock, members, key) -> dict[str, Any] | None:
    fields = [np.zeros(2, complex) for _ in section.inputs]
    for k, packet, factor, _ in members:
        fields[k] = fields[k] + from_json(packet["jones"]) / factor
    if sum(power(f) for f in fields) <= 0:
        return None
    return {"fields": fields, "origin": min(packet["t1"] - clock.at(*end) for _, packet, _, end in members),
            "width": max(p["width"] for _, p, _, _ in members), "nm": key[1], "source": key[0],
            "inputs": {k for k, *_ in members}}


def _pair(found: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Buckets of inputs read at different ports (a coupler that sends all its light across, or none): the engine
    keeps them apart, but light of one source and wavelength that reaches the window at one instant (within
    ``SAME_INSTANT`` of a pulse width) is one field there, so such buckets of different inputs are one. Light of a
    later instant (a ring's trip that returns within the pulse) stays its own bucket, drawn at its own time."""

    out, used = [], set()
    for i, a in enumerate(found):
        if i in used:
            continue
        for j in range(i + 1, len(found)):
            b = found[j]
            if (j not in used and not a["inputs"] & b["inputs"] and (a["source"], a["nm"]) == (b["source"], b["nm"])
                    and abs(a["origin"] - b["origin"]) <= SAME_INSTANT * max(a["width"], b["width"])):
                a = {**a, "fields": [x + y for x, y in zip(a["fields"], b["fields"])], "origin": min(a["origin"], b["origin"]),
                     "width": max(a["width"], b["width"]), "inputs": a["inputs"] | b["inputs"]}
                used.add(j)
                break
        out.append(a)
    return out


def rail_fields(section, shape: list[dict[str, Any]], fields) -> list[np.ndarray]:
    """The complex field (Jones vector, one row per point) at each drawn point of each rail for one bucket's input
    fields. This is the section model: the pulse powers and the CW fields both come from it."""

    out = []
    for r, (rail, drawn) in enumerate(zip(section.rails, shape)):
        loss = np.sqrt(np.asarray(rail.tail_loss) ** np.asarray(drawn["tail"]))
        if section.kappa is None:
            out.append(np.asarray(fields[r])[None, :] * loss[:, None])
            continue
        theta = math.asin(math.sqrt(min(max(section.kappa, 0.0), 1.0)))
        done = np.asarray(drawn["done"])
        stay, cross = np.cos(theta * done), section.cross * np.sin(theta * done)
        own, other = fields[r], fields[1 - r]
        out.append((stay[:, None] * own[None, :] + cross[:, None] * other[None, :]) * loss[:, None])
    return out


def rail_powers(section, shape: list[dict[str, Any]], fields) -> list[np.ndarray]:
    """The power at each drawn point of each rail for one bucket's input fields."""

    return [np.sum(np.abs(f) ** 2, axis=1) for f in rail_fields(section, shape, fields)]


def section_drawings(sid: str, index: int, section, pulse: dict[str, Any]) -> list[dict[str, Any]]:
    """The drawings of one section: one per rail, a packet per bucket."""

    shape = layout(section)
    drawings = [{"host": sid, "section": index, "rail": r, "points": [[round(float(x), 4), round(float(y), 4)]
                                                                       for x, y in drawn["points"]],
                 "window": drawn["window"], "packets": []} for r, drawn in enumerate(shape)]
    clock = Clock(section, pulse)
    for bucket in buckets(section, pulse, clock):
        powers = rail_powers(section, shape, bucket["fields"])
        for r, drawn in enumerate(shape):
            if not drawn["arcs"]:
                continue
            times = [bucket["origin"] + clock.at(r, s) for s in (drawn["arcs"][0], drawn["arcs"][-1])]
            drawings[r]["packets"].append({"t0": times[0], "t1": times[1], "width": bucket["width"],
                                           "wavelength_nm": bucket["nm"], "power": [round(float(v), 7) for v in powers[r]]})
    return [d for d in drawings if d["packets"] and len(d["points"]) >= 2]


def cw_fields(section, pulse: dict[str, Any], table: dict[str, Any]) -> list[dict[str, Any]]:
    """The section's CW inputs, one per wavelength: ``{"nm", "n_eff", "fields"}``. As for a pulse bucket, an input is
    the engine's field at the end of the read transfers over the read's factor; the engine adds all its trips
    coherently, so there is one set of inputs per wavelength. ``n_eff`` is the index of the read transfers."""

    chosen, _ = choose(section, pulse)
    found: dict[float, dict[str, Any]] = {}
    for k, read in enumerate(chosen):
        for eid, factor, _ in read.edges if read is not None else ():
            edge = table["edges"].get(eid)
            if edge is None or abs(factor) <= CARRIES:
                continue
            for record in edge["cw"]:
                entry = found.setdefault(record["wavelength_nm"], {"nm": record["wavelength_nm"], "n_eff": edge["group_index"],
                                                                    "fields": [np.zeros(2, complex) for _ in section.inputs]})
                entry["fields"][k] = entry["fields"][k] + end_field(edge, record) / factor
    return [found[nm] for nm in sorted(found) if sum(power(f) for f in found[nm]["fields"]) > 0]


def _flat(field: np.ndarray, digits: int = 7) -> list[float]:
    return [round(float(v), digits) for z in field for v in (z.real, z.imag)]


def section_cw(sid: str, index: int, section, pulse: dict[str, Any], table: dict[str, Any]) -> list[dict[str, Any]]:
    """The CW drawings of one section: one per rail, with the coupled-mode envelope at each drawn point, per
    wavelength (``envelope``, a Jones vector per point, without the display phase: ``display_part`` gives it).

    ``arcs`` are the arc lengths of the points on the rail, ``ref_arc`` the window's end for a coupler and the
    drawing's end for a stage."""

    shape = layout(section)
    out = [{"host": sid, "section": index, "rail": r, "window": drawn["window"],
            "points": [[float(x), float(y)] for x, y in drawn["points"]],
            "arcs": [round(float(a), 3) for a in drawn["arcs"]],
            "ref_arc": float(section.rails[r].window[1] if section.kappa is not None else section.rails[r].draw[1]),
            "fields": []} for r, drawn in enumerate(shape)]
    for entry in cw_fields(section, pulse, table):
        for r, field in enumerate(rail_fields(section, shape, entry["fields"])):
            if len(shape[r]["arcs"]):
                out[r]["fields"].append({"wavelength_nm": entry["nm"], "n_eff": entry["n_eff"], "envelope": field})
    return [d for d in out if d["fields"] and len(d["points"]) >= 2]


JOINT_UM = 1e-3                 # rail ends this close are one place


def display_part(part: Any, sid: str, drawings: list[dict[str, Any]], table: dict[str, Any], scale: float,
                 hidden=()) -> None:
    """Give the rails of one part their display phase, in section order, and write each field as ``field``.

    A rail's drawn field is its envelope times ``exp(i chi)``, with ``chi`` linear in the arc length: it runs at the
    scaled wave number ``2 pi n_eff / (lambda scale)`` (the crest spacing) and takes the shortfall to its end phase
    (wrapped into (-pi, pi]) spread evenly, as an edge's display phase does (``fieldmodel.display_phase``). Its start
    phase is the phase of the light that arrives at its first point: the drawn edges (``hidden`` are not drawn) and
    the rails drawn before it that end there. Its end phase is the start phase of the drawn edges that leave from its
    last point; else, at a port, the engine's phase of the light that leaves the part there; else the start of a
    rail drawn before it there (a ring closes on itself); else the phase that a rail of its section that ends at the
    same place got (arms that meet), so the arms meet with the envelopes' own phase difference. So the field is
    continuous at every joint, has the engine's phase at every port, and rails meet with the engine's interference.
    The envelope's own phase (coupled-mode theory) stays."""

    hidden = set(hidden)
    ports = {name: (float(p.center.x), float(p.center.y)) for name in part.ports() for p in [part.world_port(name)]}
    ends: list[tuple[float, tuple, complex, tuple, complex]] = []      # (nm, start point, start field, end point, end)
    for eid, edge in table["edges"].items():
        if eid in hidden or len(edge["points"]) < 2:
            continue
        for record in edge["cw"]:
            a, b = (edge["points"][0], edge["points"][-1]) if not record.get("reverse") else (edge["points"][-1], edge["points"][0])
            p0, p1 = record["phase"]
            ends.append((record["wavelength_nm"], tuple(a), record["amp0"] * cmath.exp(1j * p0), tuple(b),
                         record["amp"] * cmath.exp(1j * p1)))

    def near(a, b) -> bool:
        return math.dist(a, b) < JOINT_UM

    def leaving_engine(point, nm: float) -> np.ndarray:
        """The engine's field that leaves the part at ``point``, if it is a port: its own transfers that end there."""

        name = next((n for n, xy in ports.items() if near(xy, point)), None)
        total = np.zeros(2, complex)
        for eid, edge in table["edges"].items() if name else ():
            if eid.startswith(f"path:{sid}:"):
                for record in edge["cw"]:
                    if record["to"] == f"port:{sid}:{name}" and record["wavelength_nm"] == nm:
                        total = total + end_field(edge, record)
        return total

    done: list[dict[str, Any]] = []
    for drawing in drawings:
        points, arcs = drawing["points"], np.asarray(drawing["arcs"], float)
        first, last, span = tuple(points[0]), tuple(points[-1]), max(float(arcs[-1] - arcs[0]), 1e-12)
        for entry in drawing["fields"]:
            nm, envelope = entry["wavelength_nm"], entry.pop("envelope")
            k = _k_per_um(nm, entry["n_eff"], scale)
            start = end = None
            if np.linalg.norm(envelope[0]) > 1e-9:
                arriving = sum((e[4] for e in ends if e[0] == nm and near(e[3], first)), 0j)
                arriving += sum((cmath.exp(1j * phase_of(d["end"])) * float(np.linalg.norm(d["end"]))
                                 for d in done if d["nm"] == nm and near(d["last"], first)), 0j)
                start = cmath.phase(arriving) if abs(arriving) > 1e-12 else None
            leaving = sum((e[2] for e in ends if e[0] == nm and near(e[1], last)), 0j)
            engine = leaving_engine(last, nm)
            closing = [d for d in done if d["nm"] == nm and near(d["first"], last) and np.any(d["start"])]
            fellows = [d for d in done if d["nm"] == nm and d["section"] == drawing["section"] and near(d["last"], last)]
            if abs(leaving) > 1e-12:
                end = cmath.phase(leaving)
            elif np.any(engine):
                end = phase_of(engine)
            elif closing:
                end = phase_of(closing[0]["start"])
            elif fellows:
                end = phase_of(envelope[-1]) + fellows[0]["chi_end"]
            phi0, phi1 = phase_of(envelope[0]), phase_of(envelope[-1])
            c0 = start - phi0 if start is not None else (end - phi1 - k * span if end is not None else 0.0)
            delta = wrap(end - phi1 - (c0 + k * span)) if end is not None else 0.0
            chi = c0 + (k + delta / span) * (arcs - arcs[0])
            field = envelope * np.exp(1j * chi)[:, None]
            done.append({"nm": nm, "section": drawing["section"], "first": first, "last": last, "start": field[0],
                         "end": field[-1], "chi_end": float(chi[-1])})
            flat = [_flat(row) for row in field]
            short = all(abs(v) == 0.0 for row in flat for v in row[2:])
            entry["components"] = 2 if short else 4
            entry["field"] = [row[:2] for row in flat] if short else flat


def build_cw_rails(scene: Any, params: dict | None, pulse: dict[str, Any], graph: Any, table: dict[str, Any],
                   scale: float = 1.0, hidden=()) -> tuple[list[dict[str, Any]], list[str]]:
    """``(CW drawings, hidden)``: the CW drawings of every lit part's coupling sections (the same sections as
    ``build_rails``), with the display phase (``display_part``); and ``hidden`` with the transfers these sections draw
    added (a part that only the steady state lights has no pulse rails to hide them)."""

    params = dict(params or {})
    lit = sorted({eid.split(":")[1] for eid in table["edges"] if eid.startswith("path:") and table["edges"][eid]["cw"]})
    parts, hidden = [], set(hidden)
    for sid in lit:
        part = graph.parts[sid]
        behaviour = find_behaviour(part)
        sections = behaviour.sections(part, sid, params) if behaviour is not None else []
        hidden |= {eid for section in sections for eid in section.replaces if eid in table["edges"]}
        parts.append((sid, part, [d for index, section in enumerate(sections) for d in section_cw(sid, index, section, pulse, table)]))
    out = []
    for sid, part, drawings in parts:
        display_part(part, sid, drawings, table, scale, hidden)
        out.extend(drawings)
    return out, sorted(hidden)


def build_rails(scene: Any, params: dict | None, pulse: dict[str, Any], graph: Any) -> tuple[list[dict[str, Any]], list[str]]:
    """``(rail drawings, ids of the transfers they replace)`` for every lit part with coupling sections."""

    params = dict(params or {})
    lit = sorted({eid.split(":")[1] for eid in pulse["edges"] if eid.startswith("path:")})
    drawings, hidden = [], set()
    for sid in lit:
        part = graph.parts[sid]
        behaviour = find_behaviour(part)
        for index, section in enumerate(behaviour.sections(part, sid, params) if behaviour is not None else []):
            hidden |= {eid for eid in section.replaces if eid in pulse["edges"]}
            drawings.extend(section_drawings(sid, index, section, pulse))
    return drawings, sorted(hidden)
