"""The tour: the plan of a recorded camera tour that follows the light through a circuit.

A tour is a list of stops. Each stop names a part, how long the camera holds on it, and the drive that changes during
the hold. ``auto_tour`` finds the stops in the payload's own events; ``time_warp`` ties the light's time to the video
time. A tour is saved in ``metadata["animation"]["tour"]``, and ``scene_tour`` returns it, else the automatic one.

The events (read from the payload's lit edges, not from part types):

- split: a part with more than one lit public output (a Y-branch, a coupler);
- combination: a part with more than one lit public input;
- ring: a part whose lit paths contain a cycle through an internal port (the light goes round and comes back);
- drive: a part the light crosses that has a heater or a modulator drive (``effects.drive_keys``);
- detector: a part that absorbs the light.

A plain waveguide, a bend or a grating has none of these and gets no stop. A part that holds a splitter and a coupler
inside (an MZM) is one part, so its events are one stop.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from optodraw.animation_engine.graph import build_graph
from optodraw.animation_engine.signals import from_json, power

from .effects import drive_keys

MAX_STOPS = 12
MERGE_UM = 40.0          # neighbouring events (in arrival order) this close share one stop
HOLD_S = 3.0
WIDE_S = 2.0
SLOWDOWN = 0.2           # at a stop the light runs at this fraction of the normal rate (the payload's seconds_per_ps)
TRAVEL_SPEEDUP = 2.0     # between stops it runs this many times the normal rate
LEAD_PS = 0.2           # the camera arrives this long (physics ps) before a packet front reaches the part
MIN_TRAVEL_S = 0.5       # the camera needs at least this long to move between two stops
DRIVEN_RATE = 1.0        # at a driven stop the light runs at the normal rate (Ruling 46)
DRIVEN_PERIODS = 4       # ... for at least this many train periods, so several packets cross the device
DRIVEN_HOLD_MAX_S = 12.0 # ... and its hold grows for that up to this long
CAPTION = "Time slows at each stop"
RATES_CAPTION = "Scaled time: stops run at 0.2x, moves between stops at 2x, the last wide view at 1x"
DRIVEN_RATES_CAPTION = ("Scaled time: stops run at 0.2x, driven stops at 1x, moves between stops at 2x, "
                        "the last wide view at 1x")
DRIVE_CAPTION = "Time runs at normal speed while a drive changes"
# physics time per video time, as a multiple of the normal rate (the payload's seconds_per_ps); the first wide view
# runs from the start to the first stop's arrival, so its rate follows the circuit
RATES = {"stop": SLOWDOWN, "driven_stop": DRIVEN_RATE, "move": TRAVEL_SPEEDUP, "last_wide": 1.0, "first_wide": None}
_LIT = 1e-9              # an edge is lit when a packet carries more than this fraction of the source power


@dataclass
class Stop:
    sid: str
    hold_s: float = HOLD_S
    drive: str | None = None

    def __post_init__(self):
        if not self.hold_s > 0:
            raise ValueError("hold_s must be more than 0")


@dataclass
class Tour:
    stops: list[Stop] = field(default_factory=list)
    wide_s: float = WIDE_S

    def __post_init__(self):
        if not self.wide_s > 0:
            raise ValueError("wide_s must be more than 0")

    def to_json(self) -> dict[str, Any]:
        return {"stops": [{"sid": s.sid, "hold_s": s.hold_s, "drive": s.drive} for s in self.stops],
                "wide_s": self.wide_s, "caption": CAPTION, "captions": [CAPTION, RATES_CAPTION], "rates": RATES,
                "driven_rates_caption": DRIVEN_RATES_CAPTION, "drive_caption": DRIVE_CAPTION}

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Tour:
        return cls([Stop(s["sid"], float(s.get("hold_s", HOLD_S)), s.get("drive")) for s in data.get("stops", [])],
                   float(data.get("wide_s", WIDE_S)))


def _split_edge(edge_id: str) -> tuple[str, str, str, str] | None:
    """``(part id, in port, out port, tag)`` for a ``path:<sid>:<in>-><out>[#tag]`` edge id, else None."""

    if not edge_id.startswith("path:"):
        return None
    sid, _, rest = edge_id[5:].partition(":")
    body, _, tag = rest.partition("#")
    ins, arrow, outs = body.partition("->")
    return (sid, ins, outs, tag) if arrow else None


def _has_cycle(pairs: set[tuple[str, str]]) -> bool:
    ends: dict[str, list[str]] = {}
    for a, b in pairs:
        ends.setdefault(a, []).append(b)
    state: dict[str, int] = {}

    def visit(node: str) -> bool:
        state[node] = 1
        for nxt in ends.get(node, []):
            if state.get(nxt) == 1 or (nxt not in state and visit(nxt)):
                return True
        state[node] = 2
        return False

    return any(node not in state and visit(node) for node in list(ends))


def _lit_paths(payload: dict[str, Any], parts: Any):
    """``(part id, in port, out port, tag, lit packets)`` for each lit ``path:`` edge of a part (not emission)."""

    floor = _LIT * (payload.get("source_power") or 1.0)
    for edge_id, edge in payload["pulse"]["edges"].items():
        found = _split_edge(edge_id)
        if found is None or found[3] == "emission" or (parts is not None and found[0] not in parts):
            continue
        packets = [p for p in edge["packets"] if power(from_json(p["jones"])) > floor]
        if packets:
            yield (*found, packets)


def arrivals(payload: dict[str, Any], parts: Any = None) -> dict[str, float]:
    """``{part id: time of the first lit packet on its paths}``: the one arrival time ``auto_tour`` and
    ``time_warp`` both use."""

    found: dict[str, float] = {}
    for sid, _, _, _, packets in _lit_paths(payload, parts):
        found[sid] = min(found.get(sid, math.inf), *(p["t0"] for p in packets))
    return found


def _events(scene: Any, payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """``{part id: {"arrive", "kinds", "drive", "at"}}`` for every part where something happens."""

    pulse, floor = payload["pulse"], _LIT * (payload.get("source_power") or 1.0)
    parts = build_graph(scene).parts
    arrive = arrivals(payload, parts)
    lit: dict[str, dict[str, Any]] = {}
    for sid, ins, outs, _, _ in _lit_paths(payload, parts):
        info = lit.setdefault(sid, {"arrive": arrive[sid], "ins": set(), "outs": set(), "pairs": set()})
        info["pairs"].add((ins, outs))
        if not ins.startswith("_"):
            info["ins"].add(ins)
        if not outs.startswith("_"):
            info["outs"].add(outs)
    absorbing = {a["part"] for a in pulse.get("absorbed", []) if a["power"] > floor}
    events = {}
    for sid, info in lit.items():
        keys = drive_keys(parts[sid], sid)
        kinds = {"split"} if len(info["outs"]) > 1 else set()
        kinds |= {"combination"} if len(info["ins"]) > 1 else set()
        kinds |= {"ring"} if _has_cycle({p for p in info["pairs"] if p[0].startswith("_") or p[1].startswith("_")}) else set()
        kinds |= {"drive"} if keys else set()
        kinds |= {"detector"} if sid in absorbing else set()
        if kinds:
            centre = getattr(parts[sid], "world_position", None)
            events[sid] = {"arrive": info["arrive"], "kinds": kinds, "drive": keys[0][0] if keys else None,
                           "at": (centre.x, centre.y, centre.z) if centre is not None else None}
    return events


def auto_tour(scene: Any, payload: dict[str, Any]) -> Tour:
    """One stop per part where something happens, in the order the first packet arrives, at most 12.

    Neighbouring stops within 40 um merge into the first one (a drive of the merged one is kept when the first has
    none). Past 12, the stops with the most events (a drive counts three) stay."""

    if not payload.get("enabled"):
        return Tour([])
    events = _events(scene, payload)
    kept: list[str] = []
    for sid in sorted(events, key=lambda s: (events[s]["arrive"], s)):
        last = events[kept[-1]] if kept else None
        if last and last["at"] and events[sid]["at"] and math.dist(last["at"], events[sid]["at"]) <= MERGE_UM:
            last["drive"] = last["drive"] or events[sid]["drive"]
            last["kinds"] |= events[sid]["kinds"]
            continue
        kept.append(sid)
    if len(kept) > MAX_STOPS:
        rank = sorted(kept, key=lambda s: (-(len(events[s]["kinds"]) + 3 * (events[s]["drive"] is not None)),
                                           events[s]["arrive"]))
        kept = sorted(rank[:MAX_STOPS], key=lambda s: events[s]["arrive"])
    return Tour([Stop(sid, drive=events[sid]["drive"]) for sid in kept])


def scene_tour(scene: Any, payload: dict[str, Any]) -> Tour:
    """The tour saved in ``metadata["animation"]["tour"]`` when there is one, else ``auto_tour``."""

    saved = ((getattr(scene, "metadata", None) or {}).get("animation") or {}).get("tour")
    return Tour.from_json(saved) if saved else auto_tour(scene, payload)


def hold_of(stop: Stop, payload: dict[str, Any], driven: bool = True) -> tuple[float, float]:
    """``(video seconds, rate)`` of a stop's hold. A stop holds ``hold_s`` at ``SLOWDOWN`` times the normal rate; a
    driven stop (it has a ``drive``, and ``driven``: the page swings drives) runs at the normal rate for at least
    ``DRIVEN_PERIODS`` train periods, its hold grown for that up to ``DRIVEN_HOLD_MAX_S``, so each packet that crosses
    the device meets one drive level."""

    per_ps, period = payload.get("seconds_per_ps") or 0.0, payload.get("train_period_ps") or 0.0
    if not (driven and stop.drive) or per_ps <= 0:
        return stop.hold_s, SLOWDOWN
    return max(stop.hold_s, min(DRIVEN_PERIODS * period * per_ps / DRIVEN_RATE, DRIVEN_HOLD_MAX_S)), DRIVEN_RATE


def time_warp(tour: Tour, payload: dict[str, Any], driven: bool | set[int] = True) -> list[tuple[float, float]]:
    """``(video seconds, physics ps)`` knots; both never go back, the video strictly forward.

    The first and last segments are the wide views (``wide_s`` each). At a stop the video holds for ``hold_of`` the
    stop while physics time advances at its rate (``SLOWDOWN`` times the normal rate, the payload's
    ``seconds_per_ps``; the normal rate at a driven stop). Between stops it runs ``TRAVEL_SPEEDUP`` times faster,
    and the camera takes at least ``MIN_TRAVEL_S``. Between two knots the player interpolates linearly. Without
    ``driven`` (a page whose drives do not swing) every stop holds as an undriven one; a set of stop indexes names
    the stops whose drives swing."""

    pulse = payload["pulse"]
    packets = [p for edge in pulse["edges"].values() for p in edge["packets"]]
    start = min((p["t0"] for p in packets), default=0.0)
    end = max(pulse.get("duration_ps", 0.0), max((p["t1"] for p in packets), default=0.0))
    per_ps = payload.get("seconds_per_ps") or 0.0
    normal = 1.0 / per_ps if per_ps > 0 else 0.0                 # ps per video second
    if not tour.stops or normal == 0.0:
        return [(0.0, start), (max(tour.wide_s, (end - start) * per_ps), end)]
    arrive = arrivals(payload)
    knots, video, now = [(0.0, start)], tour.wide_s, start
    for i, stop in enumerate(tour.stops):
        reach = max(arrive.get(stop.sid, now), now)
        if len(knots) > 1:                  # a move runs at TRAVEL_SPEEDUP and ends just before a packet front reaches the part
            earliest, period = now + TRAVEL_SPEEDUP * normal * MIN_TRAVEL_S, payload.get("train_period_ps") or 0.0
            first = arrive.get(stop.sid)
            if first is None:
                reach = earliest
            elif period > 0:
                reach = first + max(0, math.ceil((earliest + LEAD_PS - first) / period)) * period - LEAD_PS
            move = max((reach - now) / (normal * TRAVEL_SPEEDUP), MIN_TRAVEL_S)
            video, reach = video + move, now + TRAVEL_SPEEDUP * normal * move
        knots.append((video, reach))
        hold, rate = hold_of(stop, payload, driven if isinstance(driven, bool) else i in driven)
        video += hold
        now = reach + rate * normal * hold                       # no clamp: the sources repeat, the light keeps flowing
        knots.append((video, now))
    knots.append((video + tour.wide_s, now + normal * tour.wide_s))
    return knots


def transit_ps(payload: dict[str, Any], sid: str) -> float:
    """How long the first light takes to cross part ``sid``: from its first arrival to the latest exit of its lit
    paths' packets (0 for a part with no lit path)."""

    times = [(p["t0"], p["t1"]) for found, _, _, _, packets in _lit_paths(payload, None) if found == sid for p in packets]
    return max(t1 for _, t1 in times) - min(t0 for t0, _ in times) if times else 0.0


def driven_passes(tour: Tour, payload: dict[str, Any], knots: list[tuple[float, float]] | None = None) -> dict[int, list[int]]:
    """``{stop index: [pulse numbers]}`` for each driven stop: the pulses of the sources' train (pulse n reaches the part
    at its first arrival plus n train periods) that reach the part within the stop's hold and cross it before the hold
    ends (a part whose light stays longer than a period, a ring, counts one period)."""

    knots = knots if knots is not None else time_warp(tour, payload)
    period, first, out = payload.get("train_period_ps") or 0.0, arrivals(payload), {}
    if period <= 0 or len(knots) != 2 * len(tour.stops) + 2:
        return out
    for i, stop in enumerate(tour.stops):
        if not stop.drive or stop.sid not in first:
            continue
        start, end = knots[1 + 2 * i][1], knots[2 + 2 * i][1]
        transit = min(transit_ps(payload, stop.sid), period - LEAD_PS)
        low = max(0, math.ceil((start - first[stop.sid]) / period - 1e-9))
        out[i] = [n for n in range(low, low + 1000) if first[stop.sid] + n * period + transit <= end + 1e-9]
    return out
