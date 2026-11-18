"""The payload of the 3D light player: the engine's packets, a host item per edge, the profiles and the coupling
sections' rails (where and how bright the light inside parts is drawn), colours and a pulse spacing, the tour (its
stops, its time warp and the names it shows); on request, drive tables (how the light changes as a heater or a
modulator swings)."""

from __future__ import annotations

import dataclasses
import json
import math
import warnings
from typing import Any

from optodraw.animation_engine import compile_signal_state
from optodraw.animation_engine.behaviours import find_behaviour
from optodraw.animation_engine.graph import build_graph
from optodraw.animation_engine.inputs import InputSignal
from optodraw.animation_engine.signals import from_json, power
from optodraw.animation_engine.solver import resonance_phases
from optodraw.animation_engine.tables import compile_table, first_arrivals, front_times

from .colours import CHANNEL_PALETTE, channel_colors
from .effects import (build_heat, build_rf, drive_keys, heat_captions, heat_notices, nice_ceiling, rf_captions,
                      shown_name)
from .fieldmodel import (FIELD_CYCLE_S, build_regions, crest_spacing_um, cycle_caption, display_numbers, lambda_caption,
                         lambda_scale, mmi_length_notice, overlap_profiles)
from .inputs import default_inputs, emitter_ids, input_wavelength
from .profiles import build_profiles
from .rails import build_cw_rails, build_rails, display_part, section_cw, section_drawings
from .tour import Tour, arrivals, driven_passes, scene_tour, time_warp

VERSION = 1
CREST_CAPTION = "Crest spacing from the group index"
PACKETS_IN_FLIGHT = 3
CROSSING_SECONDS = 3.0          # the first light crosses the circuit in this many seconds on screen
PULSE_FRACTION = 8              # the display pulse is an eighth of the crossing: its streak an eighth of the path
RING_CAPTION = "Rings tuned to resonance (illustrative)"
BUILD_UP_CAPTION = "Pulses are shorter than the rings' build-up, so they drop little light. The Field look shows the steady state."
DRIVE_SAMPLES = 24              # samples of a drive table, from 0 to the top of the swing
PAGE_LIMIT_BYTES = 15_000_000   # a page with the tour's drive tables (compact JSON, as embedded) stays under this
BASE_LIMIT_BYTES = 5_000_000    # a page whose light without drive tables passes this loads slowly: a notice says so
FRAME_RADII = 6.0               # a stop's camera frame in plan: a disc this many device half-diagonals round its centre
LEFT_OUT_NOTICE = "Tour drives left out to keep the page under 15 MB: "


def _host(edge_id: str) -> dict[str, Any]:
    kind, sid, *rest = edge_id.split(":")
    if kind == "route":
        return {"kind": "route", "sid": sid, "segment": None}
    if kind == "beam":
        return {"kind": "beam", "sid": sid, "segment": int(rest[0])}
    return {"kind": "part", "sid": sid, "segment": None}


def _empty_pulse() -> dict[str, Any]:
    return {"version": 1, "mode": "pulse", "duration_ps": 0.0, "edges": {}, "exits": [], "absorbed": [],
            "warnings": []}


def _field_parts(scale: float = 1.0) -> dict[str, Any]:
    """The keys the Field look adds to the steady state, empty."""

    return {"rails": [], "lambda_scale": scale, "cycle_s": FIELD_CYCLE_S, "profiles": {}, "regions": [], "cuts": {}}


def _empty_cw() -> dict[str, Any]:
    return {"version": 1, "mode": "cw", "duration_ps": 0.0, "edges": {}, "exits": [], "absorbed": [], "warnings": [],
            "params": {}, "inputs": [], **_field_parts()}


def _rail_fronts(cw_rails: list, rails: list, table: dict[str, Any], scale: float) -> None:
    """Give each CW rail ``t``: the arrival front at its first and its last point. It is the earliest packet of the
    pulse drawing of the same rail (the engine's first arrival there); without one, the first arrivals at the ends of
    the part's edges. Each of its fields gets ``crest_um`` and ``fade_ps``, the time the front takes for one crest."""

    drawn = {(r["host"], r["section"], r["rail"]): r for r in rails}
    for rail in cw_rails:
        found = drawn.get((rail["host"], rail["section"], rail["rail"]))
        if found and found["packets"]:
            first = min(found["packets"], key=lambda packet: packet["t0"])
            rail["t"] = [first["t0"], first["t1"]]
        else:
            records = [r for eid, e in table["edges"].items() if eid.startswith(f"path:{rail['host']}:") for r in e["cw"]]
            rail["t"] = [min((r["t0"] for r in records), default=0.0), min((r["t1"] for r in records), default=0.0)]
        span = max(rail["arcs"][-1] - rail["arcs"][0], 1e-12)
        for entry in rail["fields"]:
            entry["crest_um"] = round(crest_spacing_um(entry["wavelength_nm"], entry["n_eff"], scale), 6)
            entry["fade_ps"] = round(entry["crest_um"] * (rail["t"][1] - rail["t"][0]) / span, 6)


def _cw_table(scene: Any, params: dict | None, inputs: list, heater_delay_scale: float = 1.0) -> dict[str, Any]:
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message=".*light leaves unconnected port", category=RuntimeWarning)
        return compile_table(scene, mode="cw", params=params, inputs=inputs, heater_delay_scale=heater_delay_scale)


def _cw(scene: Any, params: dict | None, inputs: list, pulse: dict[str, Any], graph: Any, rails: list,
        hidden: list, heater_delay_scale: float = 1.0) -> tuple[dict, list[str], list[str]]:
    """The engine's steady state (``compile_table`` in cw mode) with what the Field look draws: each record's crest
    spacing, amplitude and display phase, the wavelength scale, the CW fields of the coupling sections' rails and their
    arrival fronts, the field where part edges share a guide, the multimode regions' grids; the captions; and
    ``hidden`` with the transfers that the CW rails draw added."""

    table = _cw_table(scene, params, inputs, heater_delay_scale)
    lit = [(e["length_um"], r["wavelength_nm"], e["group_index"]) for e in table["edges"].values() for r in e["cw"]]
    if not lit:
        return {**table, **_field_parts()}, [], list(hidden)
    _, nm, index = max(lit)
    # the crests are drawn so that about 40 span the lit drawing (the largest side of the box round its lit edges):
    # readable in a view of the whole circuit, however short its single edges are
    corners = [point for e in table["edges"].values() if e["cw"] for point in e["points"]]
    extent = max(max(p[k] for p in corners) - min(p[k] for p in corners) for k in (0, 1))
    scale = lambda_scale(extent, nm, index)
    for edge in table["edges"].values():
        for record in edge["cw"]:
            record["crest_um"] = round(crest_spacing_um(record["wavelength_nm"], edge["group_index"], scale), 6)
            # the time the front takes for one crest: it fades in over that time
            record["fade_ps"] = round(record["crest_um"] * (record["t1"] - record["t0"]) / max(edge["length_um"], 1e-12), 6)
    display_numbers(table, scale)
    drawn = {(r["host"], r["section"], r["rail"]) for r in rails}
    cw_rails, hidden = build_cw_rails(scene, params, pulse, graph, table, scale, hidden)
    _rail_fronts(cw_rails, rails, table, scale)
    for rail in cw_rails:                               # a rail the pulse drawing has keeps its points there
        if (rail["host"], rail["section"], rail["rail"]) in drawn:
            rail["points"] = None
    regions, cuts = build_regions(graph, table, hidden)
    return ({**table, **_field_parts(scale), "rails": cw_rails, "profiles": overlap_profiles(table, hidden),
             "regions": regions, "cuts": cuts},
            [lambda_caption(scale), CREST_CAPTION, cycle_caption(FIELD_CYCLE_S)], hidden)


def disabled_payload(notices: list[str], *, look: str = "light") -> dict[str, Any]:
    """A payload with no light: the page still renders, and its notices say why."""

    return {"version": VERSION, "look": look, "enabled": False, "pulse": _empty_pulse(), "hosts": {}, "profiles": {},
            "rails": [], "hidden": [], "cw": _empty_cw(), "heat": [], "rf": [], "drives": [], "heat_scale_k": 0.0, "rf_scale_v_per_um": 0.0, "caption_split": 0, "caption_folded": [], "caption_light_only": [], "colors": {}, "train_period_ps": 0.0, "seconds_per_ps": 0.0, "pulse_ps": 0.0,
            "source_power": 0.0, "notices": list(notices), "captions": [], "tour": Tour([]).to_json(), "tour_warp": [],
            "tour_names": {}}


def _source_power(graph: Any, params: dict | None, inputs: list, emitters: list[str]) -> float:
    """The power all sources put in: each input's and each emitter's (the player's brightness reference)."""

    parts = graph.parts
    emitted = sum(power(e.jones) for sid in emitters for e in find_behaviour(parts[sid]).emissions(parts[sid], sid, params or {}))
    return float(emitted + sum(power(i.emission().jones) for i in inputs if isinstance(i, InputSignal)))


def _crossing_ps(graph: Any, params: dict | None, inputs: list, emitters: list[str]) -> float:
    """How long the first light takes to reach the last end it reaches (an exit or an absorber); 0 if none.

    Each end counts at its first arrival over all wavelengths. One pass over the engine's arrival fronts, which do
    not depend on the pulse width."""

    first: dict[tuple[str, str], float] = {}
    for (_, sid, port, _), t in first_arrivals(graph, params, inputs=inputs).items():
        first[(sid, port)] = min(first.get((sid, port), t), t)
    start = min([float(i.t0_ps) for i in inputs] + ([0.0] if emitters else []), default=0.0)
    return max(first.values(), default=start) - start


def _pulse(scene: Any, params: dict | None, inputs: list, heater_delay_scale: float = 1.0) -> dict[str, Any]:
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message=".*light leaves unconnected port", category=RuntimeWarning)
        return compile_signal_state(scene, mode="pulse", params=params, inputs=inputs,
                                    heater_delay_scale=heater_delay_scale).to_json()


def _ring_defaults(graph: Any, inputs: list, params: dict | None) -> dict[str, float]:
    given = params or {}
    rings = [(sid, part) for sid, part in graph.parts.items() if f"phase:{sid}" not in given
             and (behaviour := find_behaviour(part)) is not None and behaviour.rings(part, sid)]
    if rings:                                           # only rings the light reaches (the engine's arrival fronts)
        reached = {edge.split(":")[1] for edge, *_ in front_times(graph, given, inputs=inputs) if edge.startswith("path:")}
        rings = [(sid, part) for sid, part in rings if sid in reached]
    nm = input_wavelength(graph, inputs, given) if rings else None
    if nm is None:
        return {}
    return {key: value for sid, part in rings for key, value in resonance_phases(part, sid, nm, given).items()
            if key not in given}


def default_params(scene: Any, inputs: list, params: dict | None = None) -> dict[str, float]:
    """For every ring the light reaches whose ``phase`` key the caller (``params``) does not give: the phase that puts
    the input wavelength on the ring's nearest resonance (illustrative), from the engine's own transfers round the ring
    (``resonance_phases``). The input wavelength is the first input's, else the first emitter's. A ring's heater
    adds to this phase: it detunes the ring from it."""

    return _ring_defaults(build_graph(scene), list(inputs), params)


def _packets(pulse: dict[str, Any]) -> list[dict[str, Any]]:
    return [p for edge in pulse["edges"].values() for p in edge["packets"]]


def _display_pulse(params: dict | None, inputs: list, default: bool, emitters: list[str], width: float):
    """``(params, inputs)`` with a pulse long enough to see: a real pulse ``width`` long on each source the caller
    left at its default (the default input, and each emitter with no ``width:<id>`` parameter)."""

    if width <= 0:
        return params, inputs
    shown = dict(params or {})
    for sid in emitters:
        shown.setdefault(f"width:{sid}", width)
    return (shown if shown != (params or {}) else params,
            [dataclasses.replace(i, width_ps=width) for i in inputs] if default else inputs)


def _pulse_caption(widths: list[float], seconds_per_ps: float) -> str:
    """The pulse widths shown and the time scale, from the numbers the page uses."""

    names = [f"{w:.2g}" for w in sorted(set(widths))]
    said = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
    return f"{'Pulse' if len(names) == 1 else 'Pulses'} {said} ps long, shown at {seconds_per_ps:.2g} s per ps"


def _drive_list(graph: Any, drives) -> list[tuple[str, str, float]]:
    """``(parameter, part id, top of the swing)`` for the drives asked for: None (none), "all", or a list of part
    ids."""

    if drives is None:
        return []
    if isinstance(drives, str) and drives != "all":
        raise ValueError("drives must be None, 'all', 'tour' or a list of part ids")
    found = []
    for sid in (list(graph.parts) if drives == "all" else list(drives)):
        keys = drive_keys(graph.parts[sid], sid) if sid in graph.parts else []
        if not keys and drives != "all":
            raise ValueError(f"{sid}: no heater or drive")
        found += [(param, sid, top) for param, top in keys]
    return found


def _edge_packets(edge: dict[str, Any]) -> list[tuple]:
    return [(p["from"], p["wavelength_nm"], power(from_json(p["jones"])), p["t0"], p["t1"]) for p in edge["packets"]]


def _edge_records(edge: dict[str, Any]) -> list[tuple]:
    return [(r["from"], r["to"], r["wavelength_nm"], r["amp0"], r["amp"], *r["phase"]) for r in edge["cw"]]


def _changed(base: dict[str, Any], edges: dict[str, Any], read, names: int, tolerance: float = 1e-9) -> dict[str, list]:
    """``{edge id: its entries}`` for each edge whose entries (``read``: ``names`` identifying fields, then numbers)
    differ from the base state's; an edge that goes dark has none."""

    def same(a, b):
        return len(a) == len(b) and all(x[:names] == y[:names] and all(abs(u - v) <= tolerance for u, v in
                                                                      zip(x[names:], y[names:])) for x, y in zip(a, b))

    out = {}
    for eid in sorted(base.keys() | edges.keys()):
        a, b = read(base[eid]) if eid in base else [], read(edges[eid]) if eid in edges else []
        if not same(a, b):
            out[eid] = b
    return out


def _drive_caption(parts: dict[str, Any], param: str, top: float) -> str:
    unit = "mW" if param.startswith("heater:") else "V"
    return f"Drive on {shown_name(parts, param.split(':', 1)[1])}: 0 to {top:.3g} {unit}"


def _same(a: Any, b: Any, tolerance: float = 1e-9) -> bool:
    """Whether two JSON values are equal, numbers within ``tolerance``."""

    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_same(a[k], b[k], tolerance) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_same(x, y, tolerance) for x, y in zip(a, b))
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool):
        return abs(a - b) <= tolerance
    return a == b


def _rail_id(rail: dict[str, Any]) -> str:
    return f"rail:{rail['host']}:{rail['section']}:{rail['rail']}"


def _packet_scales(was: list, now: list) -> tuple[list[float], list] | None:
    """``(scales, extra)``: per base packet ``k`` the factor ``s`` with the sample's packet of the same wavelength and
    times having ``s * was[k]["power"]`` (0 where the sample has no such packet: it fell under the engine's floor), and
    the sample's packets that match no base packet (a bucket that starts later once its first trip fell under the
    floor); None when a matching packet is not such a multiple."""

    def key(packet):
        return (packet["wavelength_nm"], round(packet["t0"], 6), round(packet["t1"], 6), round(packet["width"], 9))

    found, known = {key(b): b for b in now}, {key(a) for a in was}
    if len(found) != len(now):
        return None
    extra = [b for b in now if key(b) not in known]
    scales = []
    for a in was:
        b = found.get(key(a))
        if b is None:
            scales.append(0.0)
            continue
        if len(a["power"]) != len(b["power"]):
            return None
        norm = sum(x * x for x in a["power"])
        scale = sum(x * y for x, y in zip(a["power"], b["power"])) / norm if norm > 0 else 0.0
        if any(abs(y - scale * x) > 1e-6 for x, y in zip(a["power"], b["power"])):
            return None
        scales.append(round(scale, 9))
    return scales, extra


def _field_factors(was: list, now: list) -> list[list[float]] | None:
    """Per base field (one per wavelength), the complex factor ``c`` with the sample's field at that wavelength
    ``c * was`` at every point, all else equal ([0, 0] where the sample has none), when the sample has no other
    wavelength; else None."""

    found = {b["wavelength_nm"]: b for b in now}
    if len(found) != len(now) or not found.keys() <= {a["wavelength_nm"] for a in was}:
        return None
    factors = []
    for a in was:
        b = found.get(a["wavelength_nm"])
        if b is None:
            factors.append([0.0, 0.0])
            continue
        if not (_same({k: v for k, v in a.items() if k != "field"}, {k: v for k, v in b.items() if k != "field"}, 1e-6)
                and len(a["field"]) == len(b["field"])):
            return None
        za = [complex(row[i], row[i + 1]) for row in a["field"] for i in range(0, len(row), 2)]
        zb = [complex(row[i], row[i + 1]) for row in b["field"] for i in range(0, len(row), 2)]
        norm = sum(abs(z) ** 2 for z in za)
        c = sum(x.conjugate() * y for x, y in zip(za, zb)) / norm if norm > 0 else 0j
        if len(za) != len(zb) or any(abs(y - c * x) > 2e-6 for x, y in zip(za, zb)):
            return None
        factors.append([round(c.real, 9), round(c.imag, 9)])
    return factors


def _sections(part: Any, sid: str, params: dict) -> list:
    behaviour = find_behaviour(part) if part is not None else None
    return list(enumerate(behaviour.sections(part, sid, params))) if behaviour is not None else []


def frame_of(part: Any) -> list[float]:
    """``[x, y, radius]`` (um, in plan) round what a tour stop's camera sees of ``part``: the player frames the
    device's 3D bounding sphere (the chip's heights drawn taller) with a margin of 1.25 from at least 50 degrees up. In
    a 16:9 view that reaches up to about 5.3 of the device's plan half-diagonals from its centre (measured on the mesh
    and the weight bank); ``FRAME_RADII`` covers views up to about 2:1."""

    from optodraw.animation_engine.behaviours.geometry import local_to_world
    from optodraw.layout import estimate_component_bounds

    left, bottom, right, top = estimate_component_bounds(part)
    xs, ys = zip(*local_to_world(part, [(left, bottom), (right, bottom), (right, top), (left, top)]))
    half = 0.5 * math.hypot(max(xs) - min(xs), max(ys) - min(ys))
    return [round(0.5 * (min(xs) + max(xs)), 4), round(0.5 * (min(ys) + max(ys)), 4), round(FRAME_RADII * half, 4)]


def _in_frame(points, frame) -> bool:
    """Whether a polyline (plan points) comes within the frame's disc; no frame takes everything."""

    if frame is None:
        return True
    if not points:
        return False
    cx, cy, radius = frame
    pts = [(float(q[0]), float(q[1])) for q in points]
    if len(pts) == 1:
        return math.hypot(pts[0][0] - cx, pts[0][1] - cy) <= radius
    for (ax, ay), (bx, by) in zip(pts, pts[1:]):
        dx, dy = bx - ax, by - ay
        length2 = dx * dx + dy * dy
        u = max(0.0, min(1.0, ((cx - ax) * dx + (cy - ay) * dy) / length2)) if length2 > 0 else 0.0
        if math.hypot(ax + u * dx - cx, ay + u * dy - cy) <= radius:
            return True
    return False


def _sample_rails(base: dict[str, Any], param: str, params: dict, moved: dict[str, Any],
                  table: dict[str, Any], frame=None) -> tuple[dict[str, Any], dict[str, Any]]:
    """The rails that differ from the base state at one drive value, for every part whose own edges change:
    ``(pulse rails, CW rails)``, as ``build_rails`` and ``_cw`` draw them. A rail whose packets (fields) are the base
    rail's times a factor each carries only the factors (``scales``, ``factors``: complex as [re, im]); else its
    packets (fields and front). Scaled packets may come with ``extra`` packets in full (``_packet_scales``); a
    missing packet or field has the factor 0. A rail the base state does not draw carries its points (and arcs). The
    sections of a part other than the driven one do not change with the drive:
    they are built once (``base["sections"]``). With a ``frame`` only the rails that come within it are kept."""

    pulse, cw, graph, driven = base["pulse"], base["cw"], base["graph"], param.split(":")[1]
    known = base.setdefault("sections", {})
    touched = sorted({eid.split(":")[1] for eid in pulse["edges"].keys() | moved["edges"].keys() if eid.startswith("path:")
                      and not _same((pulse["edges"].get(eid) or {}).get("packets"), (moved["edges"].get(eid) or {}).get("packets"))}
                     | {eid.split(":")[1] for eid in cw["edges"].keys() | table["edges"].keys() if eid.startswith("path:")
                        and not _same((cw["edges"].get(eid) or {}).get("cw"), (table["edges"].get(eid) or {}).get("cw"))})
    rails, cw_rails, scale = [], [], cw["lambda_scale"]
    for sid in touched:
        part = graph.parts.get(sid)
        if sid == driven:
            sections = _sections(part, sid, params)
        else:
            if sid not in known:
                known[sid] = _sections(part, sid, params)
            sections = known[sid]
        if not sections:
            continue
        drawn = [d for index, section in sections for d in section_drawings(sid, index, section, moved)]
        fields = [d for index, section in sections for d in section_cw(sid, index, section, moved, table)]
        display_part(part, sid, fields, table, scale, base["hidden"])
        _rail_fronts(fields, drawn, table, scale)
        rails += drawn
        cw_rails += fields
    for rail in rails:
        for packet in rail["packets"]:
            packet["t0"], packet["t1"] = round(packet["t0"], 6), round(packet["t1"], 6)
    hosts = set(touched)
    points = {_rail_id(r): r["points"] for r in rails + cw_rails + [r for r in base["rails"] + cw["rails"] if r["points"]]}
    seen = {key for key, found in points.items() if _in_frame(found, frame)}
    was, now = {_rail_id(r): r for r in base["rails"] if r["host"] in hosts}, {_rail_id(r): r for r in rails}
    pulse_out = {}
    for key in sorted((was.keys() | now.keys()) & seen):
        a, b = was.get(key), now.get(key)
        if a is not None and b is not None and _same(a["packets"], b["packets"], 1e-6):
            continue
        scaled = (_packet_scales(a["packets"], b["packets"]) if a is not None and b is not None
                  else ([0.0] * len(a["packets"]), []) if a is not None else None)
        pulse_out[key] = ({"scales": scaled[0], **({"extra": scaled[1]} if scaled[1] else {})} if scaled is not None else
                          {"packets": b["packets"] if b else [], **({"points": b["points"]} if a is None else {})})
    was, now = {_rail_id(r): r for r in cw["rails"] if r["host"] in hosts}, {_rail_id(r): r for r in cw_rails}
    cw_out = {}
    for key in sorted((was.keys() | now.keys()) & seen):
        a, b = was.get(key), now.get(key)
        if a is not None and b is not None and _same(a["fields"], b["fields"], 1e-6) and _same(a["t"], b["t"], 1e-6):
            continue
        factors = (_field_factors(a["fields"], b["fields"]) if a is not None and b is not None and _same(a["t"], b["t"], 1e-6)
                   else [[0.0, 0.0]] * len(a["fields"]) if a is not None and b is None else None)
        cw_out[key] = ({"factors": factors} if factors is not None else
                       {"fields": b["fields"] if b else [], "t": (b or a)["t"],
                        **({"points": b["points"], "arcs": b["arcs"]} if a is None else {})})
    return pulse_out, cw_out


def _drive_sample(scene: Any, params: dict | None, inputs: list, param: str, value: float, base: dict[str, Any],
                  heater_delay_scale: float, frame=None) -> dict[str, Any]:
    """What one value of a drive changes from the base state (``base``: the payload's ``pulse``, ``cw``, ``rails``
    and ``hidden``, the ``graph`` and the input wavelength ``wavelength_nm``): the changed pulse and CW edges, the
    geometry of the edges only it lights, and the changed rails, as ``drive_tables`` describes. With a ``frame`` (``frame_of``) only the edges, rails and
    profiles that come within it are kept: light outside a stop's frame is not seen during its hold. The drive's own
    base value changes nothing and is not solved."""

    pulse, cw = base["pulse"], base["cw"]
    sample = {**(params or {}), param: value}
    name, parts = param.split(":", 1)[1], base["graph"].parts
    sid = name.split(":")[0]
    maps = {"heat": [h["delta_t_k"] for h in build_heat(parts, sample, base["wavelength_nm"]) if h["sid"] == name],
            "rf": [r["v"] for r in build_rf(parts, sample) if r["sid"] == sid] if param.startswith("drive:") else []}
    if value == float((params or {}).get(param, 0.0)):
        return {"pulse": {}, "cw": {}, "edges": {}, "rails": {}, "cw_rails": {}, "profiles": {}, **maps}
    moved, table = _pulse(scene, sample, inputs, heater_delay_scale), _cw_table(scene, sample, inputs, heater_delay_scale)
    display_numbers(table, cw["lambda_scale"])

    def seen(eid):
        return _in_frame((moved["edges"].get(eid) or table["edges"].get(eid) or pulse["edges"].get(eid)
                          or cw["edges"].get(eid) or {}).get("points"), frame)

    packets = {eid: v for eid, v in _changed(pulse["edges"], moved["edges"], _edge_packets, 2).items() if seen(eid)}
    records = {eid: v for eid, v in _changed(cw["edges"], table["edges"], _edge_records, 3).items() if seen(eid)}
    known = pulse["edges"].keys() | cw["edges"].keys()
    edges = {}
    for eid in sorted((packets.keys() | records.keys()) - known):
        edge = moved["edges"].get(eid) or table["edges"][eid]
        edges[eid] = {key: edge[key] for key in ("points", "length_um", "group_index")}
    rails, cw_rails = _sample_rails(base, param, sample, moved, table, frame)
    profiles = overlap_profiles(table, base["hidden"])
    changed_profiles = {eid: profiles.get(eid, []) for eid in sorted(profiles.keys() | cw["profiles"].keys())
                        if not _same(profiles.get(eid), cw["profiles"].get(eid), 1e-6) and seen(eid)}
    return {"pulse": {eid: {"from": [p[0] for p in found], "wavelength_nm": [p[1] for p in found],
                            "power": [round(p[2], 9) for p in found], "t0": [round(p[3], 6) for p in found],
                            "t1": [round(p[4], 6) for p in found]} for eid, found in packets.items()},
            "cw": {eid: [{"from": r[0], "to": r[1], "wavelength_nm": r[2], "amp0": r[3], "amp": r[4],
                          "phase": [r[5], r[6]]} for r in found] for eid, found in records.items()},
            # the Field look's maps of the driven part at this value: each heater's peak rise (K), each gap's drive (V)
            "edges": edges, "rails": rails, "cw_rails": cw_rails, "profiles": changed_profiles, **maps}


def _changes(sample: dict[str, Any]) -> bool:
    return any(sample[key] for key in ("pulse", "cw", "rails", "cw_rails"))


def _drive_entry(parts: dict[str, Any], params: dict | None, param: str, sid: str, top: float, values: list[float],
                 samples: list[dict[str, Any]], wavelength_nm: float) -> dict[str, Any]:
    """A drive table from its samples. ``heat_maps`` and ``rf_maps`` are the driven part's heat and RF maps at the
    top of the swing (where the Field look draws them); each sample's ``heat`` and ``rf`` give their values there."""

    edges: dict[str, Any] = {}
    for sample in samples:
        edges.update(sample["edges"])
    top_params, name = {**(params or {}), param: top}, param.split(":", 1)[1]
    return {"param": param, "sid": sid, "values": list(values), "pulse": [s["pulse"] for s in samples],
            "cw": [s["cw"] for s in samples], "edges": edges, "rails": [s["rails"] for s in samples],
            "cw_rails": [s["cw_rails"] for s in samples], "profiles": [s["profiles"] for s in samples],
            "heat": [s["heat"] for s in samples], "rf": [s["rf"] for s in samples],
            "heat_maps": [h for h in build_heat(parts, top_params, wavelength_nm) if h["sid"] == name],
            "rf_maps": [r for r in build_rf(parts, top_params) if r["sid"] == sid] if param.startswith("drive:") else [],
            "caption": _drive_caption(parts, param, top)}


def _no_table_notice(sid: str, param: str, params: dict | None, known) -> str:
    lit = any(eid.startswith(f"path:{sid}:") for eid in known)
    if lit and any(key == f"phase:{sid}" or key.startswith(f"phase:{sid}:") for key in params or {}):
        return f"{sid}: {param} has no effect while a phase is set"
    return f"{sid}: {param} changes no light"


def drive_tables(scene: Any, base: dict[str, Any], params: dict | None, inputs: list, drives,
                 heater_delay_scale: float = 1.0) -> tuple[list[dict[str, Any]], list[str]]:
    """One table per drive asked for (``drives``: None, "all" or part ids; a part with several heaters has one per
    heater): ``values`` from 0 to the top of the swing (heaters to 20 mW, a modulator to its v_pi), and per sample only
    what differs from the base state (``base``: the payload's ``pulse``, ``cw``, ``rails`` and ``hidden``, solved with
    ``params`` and ``inputs``, the ``graph`` and the input wavelength ``wavelength_nm``): for each changed pulse edge
    its packets' ``from``, ``wavelength_nm``, ``power``, ``t0`` and ``t1``; for each changed CW edge its records' ``from``, ``to``,
    ``wavelength_nm``, ``amp0``, ``amp`` and ``phase`` (as the Field look draws them, at the payload's wavelength
    scale); for each changed rail its packets (``rails``) and its CW fields and front (``cw_rails``), as the payload
    draws them, or only a factor per packet (field) where the rail is the base rail times a factor
    (``_sample_rails``). An edge or a rail that goes dark has empty lists. ``edges`` holds the geometry of the
    edges that only the swing lights; ``caption`` names the drive and its swing. A drive that changes nothing has no
    table, and a notice says so: returns ``(tables, notices)``.

    This is the ``drives=`` API of ``build_light_payload`` (None, "all" or part ids): full swings of chosen drives
    for a Python user. The page and the editor use ``tour_tables`` instead (``drives="tour"``)."""

    graph = base["graph"]
    known, tables, notices = base["pulse"]["edges"].keys() | base["cw"]["edges"].keys(), [], []
    for param, sid, top in _drive_list(graph, drives):
        values = [top * i / (DRIVE_SAMPLES - 1) for i in range(DRIVE_SAMPLES)]
        samples = [_drive_sample(scene, params, inputs, param, v, base, heater_delay_scale) for v in values]
        if any(_changes(sample) for sample in samples):
            tables.append(_drive_entry(graph.parts, params, param, sid, top, values, samples, base["wavelength_nm"]))
        else:
            notices.append(_no_table_notice(sid, param, params, known))
    return tables, notices


def page_bytes(payload: dict[str, Any]) -> int:
    """The bytes the page carries for ``payload``: compact JSON with ``<``, ``>`` and ``&`` escaped, as the renderer
    embeds it."""

    text = json.dumps(payload, separators=(",", ":"))
    return len(text) + 5 * (text.count("<") + text.count(">") + text.count("&"))


def pass_levels(passes: int) -> tuple[list[float], list[int]]:
    """``(levels, sequence)`` for a driven stop with ``passes`` pulses crossing its part: the drive levels as
    fractions of the top of the swing (0 up to 1, evenly), and the level of each pass in turn, up to the top and
    back (4 passes: 0, 0.5, 1, 0). One pass takes the top."""

    if passes <= 1:
        return [1.0], [0] * passes
    count = math.ceil((passes + 1) / 2)
    return [i / (count - 1) for i in range(count)], list(range(count)) + list(reversed(range(passes - count)))


def tour_tables(scene: Any, base: dict[str, Any], payload: dict[str, Any], params: dict | None, inputs: list,
                tour: Tour, size, heater_delay_scale: float = 1.0,
                stops: set[int] | None = None, cut: list[str] | None = None) -> tuple[list[dict[str, Any]], list[str]]:
    """The drive table of each driven stop of ``tour`` (its ``drive``), in the tour's order (Rulings 46 and 47): the
    drive steps once per train period through the levels of ``pass_levels``, one per pulse that crosses the part during
    the hold (``driven_passes``), so the table holds those levels only (``values``), with ``passes`` (pulse numbers),
    ``levels`` (the level of each pass), ``first_ps`` (when pulse 0 reaches the part) and ``frame`` (``frame_of``):
    each level keeps only what that frame shows. The page payload stays within ``PAGE_LIMIT_BYTES``
    (``size(tables, notices)`` gives its exact bytes): the page is measured once without tables, each table adds its own
    bytes, and past the limit the latest stops' tables go, with a notice; one exact measure at the end confirms it.
    ``stops`` (indexes) limits the tables to those stops; ``cut`` holds the stops an earlier call left out for size (the
    list grows with this call's). Returns ``(tables, notices)``."""

    graph, first = base["graph"], arrivals(payload)
    passes = driven_passes(tour, payload, [tuple(k) for k in payload["tour_warp"]])
    known = base["pulse"]["edges"].keys() | base["cw"]["edges"].keys()
    wanted = []
    for i, stop in enumerate(tour.stops):
        top = dict(drive_keys(graph.parts[stop.sid], stop.sid)).get(stop.drive) if stop.drive and stop.sid in graph.parts else None
        if top is not None and passes.get(i) and (stops is None or i in stops):
            wanted.append((stop.drive, stop.sid, top, passes[i]))
    tables, notices, left_out, empty = [], [], cut if cut is not None else [], size([], [])
    order = [stop.sid for stop in tour.stops].index
    few: dict[str, str] = {}                      # the few-pulses notice of each table, said only while its table is kept

    def said(found=None):
        kept = [few[t["sid"]] for t in (tables if found is None else found) if t["sid"] in few]
        return notices + kept + ([LEFT_OUT_NOTICE + ", ".join(sorted(left_out, key=order))] if left_out else [])

    def fits(found):
        """The page without tables, measured once, plus the tables' bytes, the hosts of the edges only they light and
        the notices."""

        hosts = sum(_json_bytes({eid: _host(eid)}) - 1 for eid in {e for t in found for e in t["edges"]})
        notes = sum(_json_bytes(note) + 1 for note in said(found))
        return empty + sum(_json_bytes(t) + 1 for t in found) + hosts + notes <= PAGE_LIMIT_BYTES

    for n, (param, sid, top, crossing) in enumerate(wanted):
        fractions, sequence = pass_levels(len(crossing))
        frame = frame_of(graph.parts[sid])
        values = [top * f for f in fractions]
        samples = [_drive_sample(scene, params, inputs, param, v, base, heater_delay_scale, frame) for v in values]
        if not any(_changes(sample) for sample in samples):
            notices.append(_no_table_notice(sid, param, params, known))
            continue
        table = {**_drive_entry(graph.parts, params, param, sid, top, values, samples, base["wavelength_nm"]),
                 "passes": crossing, "levels": sequence, "first_ps": first[sid], "frame": frame}
        if len(crossing) < 3:                      # the 12 s cap leaves few pulses (a ring's long period)
            count = f"{len(crossing)} pulse{'s' if len(crossing) != 1 else ''}"
            few[sid] = (f"{shown_name(graph.parts, param.split(':', 1)[1])}: the drive is shown on {count}; "
                        "the Field look shows it in steady state")
        if not fits(tables + [table]):
            left_out.extend(s for _, s, _, _ in wanted[n:])
            break
        tables.append(table)
    while tables and size(tables, said()) > PAGE_LIMIT_BYTES:      # the exact check: the latest table goes
        left_out.insert(0, tables.pop()["sid"])
    return tables, said()


def _json_bytes(value: Any) -> int:
    return len(json.dumps(value, separators=(",", ":")))


def _tour_keys(graph: Any, tour: Tour, payload: dict[str, Any], driven: bool | set[int]) -> dict[str, Any]:
    """The payload's tour (Ruling 4: ``scene_tour(...).to_json()``), its time warp ``[video s, physics ps]`` (a driven
    stop at the normal rate only when the page swings its drive: ``driven`` is the indexes of those stops) and the name
    each stop shows."""

    return {"tour": tour.to_json(), "tour_warp": [list(knot) for knot in time_warp(tour, payload, driven)],
            "tour_names": {stop.sid: shown_name(graph.parts, stop.sid) for stop in tour.stops}}


def _scales(parts: dict[str, Any], params: dict | None, heat: list, rf: list, tables: list,
            wavelength_nm: float) -> tuple[float, float]:
    """The colour scales of the Field look: the largest heat (K) and RF field (V per um) of the scene and of the top of
    each drive table, rounded up to 1, 2 or 5 x 10^n."""

    peaks_k = [h["delta_t_k"] for h in heat]
    fields = [abs(r["v"]) / r["gap_um"] for r in rf]
    for table in tables:
        top = {**(params or {}), table["param"]: table["values"][-1]}
        name = table["param"].split(":", 1)[1]
        peaks_k += [h["delta_t_k"] for h in build_heat(parts, top, wavelength_nm) if h["sid"] == name]
        fields += [abs(r["v"]) / r["gap_um"] for r in build_rf(parts, top) if r["sid"] == table["sid"]]
    return nice_ceiling(max(peaks_k, default=0.0)), nice_ceiling(max(fields, default=0.0))


def animation_settings(metadata: dict | None) -> tuple[str, dict | None, list | None]:
    """``(look, params, inputs)`` from ``metadata["animation"]``, for the engine: an input given as a port name becomes
    an ``InputSignal``; none given is None (the engine's default)."""

    settings = (metadata or {}).get("animation") or {}
    inputs = [InputSignal(port) if isinstance(port, str) else port for port in settings.get("inputs") or []]
    return str(settings.get("look", "light")), settings.get("params") or None, inputs or None


def build_light_payload(scene: Any, *, params: dict | None = None, inputs: list | None = None,
                        look: str = "light", heater_delay_scale: float = 1.0, drives=None,
                        tour: Tour | None = None) -> dict[str, Any]:
    """Everything the page needs to animate light in ``scene``; ``enabled`` is False when there is no light.

    A ring with no ``phase`` key in ``params`` starts on resonance (``default_params``). ``heater_delay_scale`` above
    1 shows each heater's slow-down that many times larger, labelled: the pulse is solved with the heaters' delays
    scaled and the phases unchanged, so the rails and the light after them follow. ``drives`` (None, "all" or part
    ids) asks for drive tables (``drive_tables``); "tour" asks for the tables of the tour's driven stops within the
    page limit (``tour_tables``). The payload always carries the tour (``tour``, ``tour_warp``, ``tour_names``): the
    saved or automatic one, or ``tour`` when given. With "tour" a stop holds as a driven stop only when the page keeps
    its table, so the warp is built again for the stops that keep one until it settles."""

    if not (math.isfinite(heater_delay_scale) and heater_delay_scale >= 1.0):
        raise ValueError("heater_delay_scale must be 1 or more")
    notices: list[str] = []
    graph = build_graph(scene)                          # built once: the default input, the emitters and the rest
    default = inputs is None
    if default:
        inputs, notices = default_inputs(scene, graph)
    emitters = emitter_ids(scene, graph)
    if not inputs and not emitters:
        return disabled_payload(notices or ["no light source"], look=look)
    # the time scale and the display pulse come from one number: the time the first light needs to cross; the
    # pulse is an eighth of it, so its streak is about an eighth of the longest lit path
    rings = _ring_defaults(graph, inputs, params)
    params = {**rings, **(params or {})} if rings else params
    crossing = _crossing_ps(graph, params, inputs, emitters)
    params, inputs = _display_pulse(params, inputs, default, emitters, crossing / PULSE_FRACTION)
    pulse = _pulse(scene, params, inputs, heater_delay_scale)
    notices += [n for sid, part in graph.parts.items() if (n := mmi_length_notice(sid, part))]
    packets = _packets(pulse)
    colors = channel_colors([p["wavelength_nm"] for p in packets])
    if not packets:
        notices.append("no light reaches any path")
    hidden = [nm for nm in colors if not 380.0 <= nm <= 750.0]
    if len(hidden) > len(CHANNEL_PALETTE):
        notices.append(f"{len(hidden)} channels share colours: the palette has {len(CHANNEL_PALETTE)}")
    start = min((p["t0"] for p in packets), default=0.0)
    span = max((p["t1"] for p in packets), default=0.0) - start
    crossing = crossing if crossing > 0 else span          # no end reached: the whole span
    seconds_per_ps = CROSSING_SECONDS / crossing if crossing > 0 else 0.0
    widths = [p["width"] for p in packets]
    timing = [f"Time slowed so light crosses the circuit in about {crossing * seconds_per_ps:.0f} s",
              _pulse_caption(widths, seconds_per_ps)] if seconds_per_ps and widths else []
    slowdown = [f"Heater slow-down shown x{heater_delay_scale:g}"] if heater_delay_scale > 1.0 else []
    # one wavelength that is not visible is white in the Light look (the Field look draws it red, white and blue)
    white = [f"{nm:g} nm ({'infrared' if nm > 750.0 else 'ultraviolet'}) shown white" for nm in colors
             if len(colors) == 1 and nm in hidden]
    captions = timing + white + ([RING_CAPTION, BUILD_UP_CAPTION] if rings else []) + slowdown
    rails, replaced = build_rails(scene, params, pulse, graph)     # the transfers the rails draw: not drawn again
    cw, cw_captions, replaced = _cw(scene, params, inputs, pulse, graph, rails, replaced, heater_delay_scale)
    nm = input_wavelength(graph, inputs, params or {})             # the heat's rise is the one at this wavelength
    heat, rf = build_heat(graph.parts, params, nm), build_rf(graph.parts, params)    # the Field look's heat and RF
    base = {"pulse": pulse, "cw": cw, "rails": rails, "hidden": replaced, "graph": graph, "wavelength_nm": nm}
    tables, still = ([], []) if drives == "tour" else drive_tables(scene, base, params, inputs, drives, heater_delay_scale)
    out = {"version": VERSION, "look": look, "enabled": bool(packets), "pulse": pulse,
           "hosts": {edge_id: _host(edge_id) for edge_id in sorted({*pulse["edges"], *cw["edges"]})},
           "profiles": build_profiles(scene, params, pulse, graph, replaced),
           "rails": rails, "hidden": replaced, "cw": cw, "heat": heat, "rf": rf, "drives": [],
           "heat_scale_k": 0.0, "rf_scale_v_per_um": 0.0,
           "caption_split": len(captions),       # the captions before this index show in both looks, the rest in Field
           "source_power": _source_power(graph, params, inputs, emitters),
           "colors": {str(nm): hex_ for nm, hex_ in colors.items()},
           "train_period_ps": span / PACKETS_IN_FLIGHT,
           "seconds_per_ps": seconds_per_ps,
           "pulse_ps": max(widths, default=0.0),
           "notices": [],
           "captions": captions + cw_captions + heat_captions(heat, graph.parts) + rf_captions(rf, graph.parts)}
    # the short lines stay in view: the time scale, the pulse, the heater slow-down and the wavelength factor; the
    # model lines fold behind the page's Scales toggle
    short = set(timing + white + slowdown + [lambda_caption(cw["lambda_scale"])])
    out["caption_folded"] = [i for i, line in enumerate(out["captions"]) if line not in short]
    out["caption_light_only"] = [i for i, line in enumerate(out["captions"]) if line in white]     # not in Field
    tour = tour if tour is not None else scene_tour(scene, out)
    swung = {i for i, stop in enumerate(tour.stops) if stop.drive} if drives == "tour" else set()
    out.update(_tour_keys(graph, tour, out, swung))
    after = heat_notices(graph.parts, params) + [w["message"] for w in pulse["warnings"]]

    def assemble(tables: list, said: list[str]) -> dict[str, Any]:
        return {**_with_tables(out, graph, params, tables, nm), "notices": notices + said + after}

    size = page_bytes(assemble([], []))                 # the page's light without drive tables
    if size > BASE_LIMIT_BYTES:
        after.append(f"the light payload is {size / 1e6:.1f} MB (more than {BASE_LIMIT_BYTES / 1e6:g} MB): "
                     "the page loads slowly")

    if drives == "tour":
        cut: list[str] = []
        while True:                  # a stop without a table holds undriven: its hold moves the later stops, so build again
            tables, still = tour_tables(scene, base, out, params, inputs, tour,
                                        lambda found, said: page_bytes(assemble(found, said)), heater_delay_scale,
                                        swung, cut)
            kept = _kept_stops(tour, tables)
            if kept == swung:
                break
            swung = kept
            out.update(_tour_keys(graph, tour, out, swung))
    return assemble(tables, still)


def _kept_stops(tour: Tour, tables: list[dict[str, Any]]) -> set[int]:
    """The indexes of the stops whose tables are kept (the tables are in the tour's order)."""

    kept, at = set(), 0
    for i, stop in enumerate(tour.stops):
        if at < len(tables) and stop.drive and tables[at]["sid"] == stop.sid:
            kept.add(i)
            at += 1
    return kept


def _with_tables(out: dict[str, Any], graph: Any, params: dict | None, tables: list,
                 wavelength_nm: float) -> dict[str, Any]:
    """``out`` with the drive tables, the hosts of the edges only they light, and colour scales that cover their tops
    (Ruling 33)."""

    swung = {eid for table in tables for eid in table["edges"]}
    hosts = {edge_id: _host(edge_id) for edge_id in sorted({*out["hosts"], *swung})}
    heat_k, rf_v = _scales(graph.parts, params, out["heat"], out["rf"], tables, wavelength_nm)
    return {**out, "hosts": hosts, "drives": tables, "heat_scale_k": heat_k, "rf_scale_v_per_um": rf_v}
