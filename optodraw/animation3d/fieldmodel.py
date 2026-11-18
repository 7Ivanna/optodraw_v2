"""Models for the Field look of the 3D light player: where an MMI forms its images."""

from __future__ import annotations

import cmath
import math
from typing import Any

import numpy as np

MMI_N_EFF = 2.85                    # effective index of the multimode body
MMI_WAVELENGTH_NM = 1550.0
MMI_LENGTH_TOLERANCE = 0.05         # a drawn length this far from the self-imaging length gets a notice
MMI_TYPES = ("MMI1x2", "MMI1x4", "MMI2x2", "MMI2x2PowerSplitter")


def mmi_self_imaging_length_um(width_um: float, n_eff: float, wavelength_nm: float, images: int,
                               symmetric: bool) -> float:
    """Length of a multimode body that forms ``images`` images of its input.

    The beat length is ``L_pi = 4 * n_eff * W**2 / (3 * wavelength)``. General interference gives
    ``L = 3 * L_pi / images``. A centre-fed input (symmetric interference) gives ``L = 3 * L_pi / (4 * images)``.
    """

    l_pi = 4.0 * n_eff * width_um ** 2 / (3.0 * wavelength_nm * 1e-3)
    return 3.0 * l_pi / (4.0 * images if symmetric else images)


def mmi_length_check(part: Any) -> tuple[float, float] | None:
    """``(drawn length, self-imaging length)`` in um for a drawn MMI, else None.

    The width and the length are the part's own ``body_width`` and ``body_length``: the schematic drawing
    stretches both, so only these numbers say what device the part stands for. One input is centre-fed
    (symmetric); the images are the outputs.
    """

    if getattr(part, "component_type", "") not in MMI_TYPES:
        return None
    ideal = mmi_self_imaging_length_um(float(part.body_width), MMI_N_EFF, MMI_WAVELENGTH_NM,
                                       int(part.output_port_count), int(part.input_port_count) == 1)
    return float(part.body_length), ideal


def mmi_length_notice(sid: str, part: Any) -> str | None:
    """The payload notice for an MMI whose length is off its self-imaging length by more than 5 percent.

    Only for a part whose user set ``body_length`` or ``body_width``: a default MMI is schematic."""

    found = mmi_length_check(part)
    cls = type(part)
    if found is None or (part.body_length == cls.body_length and part.body_width == cls.body_width) or abs(found[0] - found[1]) <= MMI_LENGTH_TOLERANCE * found[1]:
        return None
    return f"{sid}: MMI length is not its self-imaging length; the split shown is the engine's"


# ---- the steady state: the field the Field look draws -------------------------------------------------------------

CRESTS_ACROSS_DRAWING = 40          # about this many crests span the lit drawing (its largest side) on screen


def crest_spacing_um(wavelength_nm: float, n_eff: float, scale: float) -> float:
    """The drawn distance between two crests: the guide wavelength ``wavelength / n_eff``, times the display scale."""

    return wavelength_nm * 1e-3 / n_eff * scale


def lambda_scale(scene_extent_um: float, wavelength_nm: float = MMI_WAVELENGTH_NM, n_eff: float = 2.4) -> float:
    """The factor that makes about 40 crests span ``scene_extent_um`` (the lit drawing's largest side): a whole number,
    at least 1."""

    one = crest_spacing_um(wavelength_nm, n_eff, 1.0)
    return float(max(1, round(scene_extent_um / (CRESTS_ACROSS_DRAWING * one)))) if scene_extent_um > 0 else 1.0


def lambda_caption(scale: float) -> str:
    return f"Wavelength shown x{scale:.0f}"


def _jones(values: list[float]) -> np.ndarray:
    return np.array([complex(values[0], values[1]), complex(values[2], values[3])])


def _k_per_um(wavelength_nm: float, n_eff: float, scale: float = 1.0) -> float:
    return 2.0 * math.pi * n_eff / (wavelength_nm * 1e-3 * scale)


def end_field(edge: dict[str, Any], record: dict[str, Any]) -> np.ndarray:
    """The engine's field at the end of the edge (its Jones vector): the CW amplitude and phase the next part gets.

    A record on a link holds the field at its entry (``jones_reference`` "entry"): the engine's propagation phase
    ``2 pi n L / lambda`` is still to be added. A record on a path through a part holds the field at its exit."""

    jones = _jones(record["jones"])
    if record.get("jones_reference", "exit") == "entry":
        return jones * cmath.exp(1j * _k_per_um(record["wavelength_nm"], edge["group_index"]) * edge["length_um"])
    return jones


# The check API: field_at, display_field, arrival_front_ps and port_intensity. The payload does not use them; the
# tests use them to check the field model against the engine. They stay next to the model they check.
def field_at(edge: dict[str, Any], record: dict[str, Any], s_um: float) -> np.ndarray:
    """The complex field (Jones vector) at distance ``s_um`` along the drawn edge: the engine's CW amplitude times
    ``exp(i (phase + 2 pi n s / lambda))``, with ``phase`` the engine's phase at the edge's entry and ``n`` the
    edge's index. The engine's phase uses the group index (``group_index`` of the edge): the model uses the same
    number, so at ``s = L`` the field is the engine's own. This is the true wavelength (scale 1)."""

    length = max(float(edge["length_um"]), 1e-12)
    s = min(max(s_um, 0.0), length)
    k = _k_per_um(record["wavelength_nm"], edge["group_index"])
    return end_field(edge, record) * cmath.exp(-1j * k * (length - s))


def phase_of(field: np.ndarray) -> float:
    """The phase of a Jones vector: the angle of its strongest component."""

    k = int(np.argmax(np.abs(field)))
    return float(cmath.phase(field[k])) if abs(field[k]) > 0 else 0.0


def wrap(angle: float) -> float:
    """``angle`` wrapped into (-pi, pi]."""

    w = (angle + math.pi) % (2.0 * math.pi) - math.pi
    return math.pi if w <= -math.pi else w


def arriving_fields(table: dict[str, Any]) -> dict[tuple[str, float], np.ndarray]:
    """The engine's field that arrives at each port, per wavelength: ``{(port, nm): Jones vector}``, the sum of the
    field at the end of every edge that ends there."""

    total: dict[tuple[str, float], np.ndarray] = {}
    for edge in table["edges"].values():
        for record in edge["cw"]:
            key = (record["to"], record["wavelength_nm"])
            total[key] = total.get(key, np.zeros(2, complex)) + end_field(edge, record)
    return total


def feeding_end_phase(table: dict[str, Any], edge_id: str, record: dict[str, Any],
                      arrivals: dict[tuple[str, float], np.ndarray] | None = None) -> float | None:
    """For a path through a part: the engine's phase of the light that arrives at the path's input port, the sum of
    the field at the end of every edge that ends there (the feeding link, or the paths of a ring that meet at an
    internal port); None for a link, or a path nothing feeds (a source's first edge). ``arrivals`` (from
    ``arriving_fields``) saves the search over the table."""

    if not edge_id.startswith("path:"):
        return None
    if arrivals is None:
        arrivals = arriving_fields(table)
    total = arrivals.get((record["from"], record["wavelength_nm"]), np.zeros(2, complex))
    return phase_of(total) if np.any(total) else None


def display_phase(table: dict[str, Any], edge_id: str, record: dict[str, Any], s_um: float, scale: float,
                  arrivals: dict[tuple[str, float], np.ndarray] | None = None) -> float:
    """The phase drawn at distance ``s_um`` along an edge, for a wavelength shown ``scale`` times longer.

    It starts at the phase of the light that feeds the edge (the end of the feeding edge; for a link, the engine's
    entry phase; for a source's first edge, the source phase), runs at the scaled wave number
    ``2 pi n / (lambda scale)``, and takes the engine's phase at the edge's end: the shortfall ``delta`` (wrapped into
    (-pi, pi]) is spread evenly along the edge. So the field is continuous at every joint, equals the engine's phase
    at every edge end, and paths meet with the engine's interference. The crest spacing differs from
    ``crest_spacing_um`` by at most half a crest over one edge. The crests follow the group index, not a phase
    index: the engine gives only the group index."""

    edge = table["edges"][edge_id]
    length = max(float(edge["length_um"]), 1e-12)
    k_true = _k_per_um(record["wavelength_nm"], edge["group_index"])
    end = phase_of(end_field(edge, record))
    start = feeding_end_phase(table, edge_id, record, arrivals)
    if start is None:
        start = end - k_true * length
    k_shown = k_true / scale
    delta = wrap(end - (start + k_shown * length))
    s = min(max(s_um, 0.0), length)
    return start + k_shown * s + delta * s / length


# check API (see field_at)
def display_field(table: dict[str, Any], edge_id: str, record: dict[str, Any], s_um: float, scale: float) -> np.ndarray:
    """The field drawn at ``s_um`` along an edge: the engine's amplitude with ``display_phase`` (see there)."""

    edge = table["edges"][edge_id]
    end = end_field(edge, record)
    return end * cmath.exp(1j * (display_phase(table, edge_id, record, s_um, scale) - phase_of(end)))


def intensity(field: np.ndarray) -> float:
    return float(np.sum(np.abs(field) ** 2))


# check API (see field_at)
def arrival_front_ps(table: dict[str, Any], edge_id: str) -> tuple[float, float] | None:
    """``(t0, t1)``, the engine's first arrival at the edge's two ends, over its wavelengths; None if no light."""

    records = table["edges"].get(edge_id, {"cw": []})["cw"]
    return (min(r["t0"] for r in records), min(r["t1"] for r in records)) if records else None


# check API (see field_at)
def port_intensity(table: dict[str, Any], port: str, wavelength_nm: float, scale: float = 1.0) -> float:
    """The intensity at the end of every edge that ends at ``port`` (``"port:<sid>:<name>"``), by the field model:
    the fields of the edges add coherently (two arms of an interferometer meet here)."""

    total = np.zeros(2, complex)
    for edge_id, edge in table["edges"].items():
        for record in edge["cw"]:
            if record["to"] == port and record["wavelength_nm"] == wavelength_nm:
                total = total + display_field(table, edge_id, record, edge["length_um"], scale)
    return intensity(total)


# ---- what the Field look draws ------------------------------------------------------------------------------------
# The player draws E = amp cos(phase - omega t) along each guide, times a mode shape across it, from the numbers here:
# it only interpolates them along the drawn guide and adds the time term (omega: one cycle per FIELD_CYCLE_S).

FIELD_CYCLE_S = 1.0                 # one optical cycle is drawn in this many seconds: a display frequency
C_UM_PER_PS = 299.792458
REGION_SAMPLES = (16, 64)           # samples along each side of a region's grid: at least, at most


def cycle_caption(cycle_s: float = FIELD_CYCLE_S) -> str:
    return f"Field cycle shown as {cycle_s:g} s, not to the time scale"


def display_numbers(table: dict[str, Any], scale: float) -> None:
    """Give every record of ``table`` what the Field look draws it with: ``amp``, the length of the engine's Jones
    vector at the edge's end; ``amp0``, the amplitude at its start (for a path through a part, the light that arrives
    at its input port: a part's loss shows along its path, not as a step at its input); and ``phase``, the display
    phase at the edge's start and at its end (``display_phase``). The drawn amplitude and phase run linearly between
    the two: the phase holds the crests (``2 pi s / crest_um``) and the joint correction."""

    arrivals = arriving_fields(table)
    for edge_id, edge in table["edges"].items():
        for record in edge["cw"]:
            record["amp"] = round(float(np.linalg.norm(end_field(edge, record))), 7)
            arriving = arrivals.get((record["from"], record["wavelength_nm"])) if edge_id.startswith("path:") else None
            record["amp0"] = round(float(np.linalg.norm(arriving)), 7) if arriving is not None and np.any(arriving) \
                else record["amp"]
            record["phase"] = [round(display_phase(table, edge_id, record, s, scale, arrivals), 5)
                               for s in (0.0, float(edge["length_um"]))]


def _field(record: dict[str, Any], fraction: float, amplitude: float) -> complex:
    p0, p1 = record["phase"]
    return amplitude * cmath.exp(1j * (p0 + (p1 - p0) * fraction))


def drawn_amp(record: dict[str, Any], fraction: float) -> float:
    """The amplitude the Field look draws at ``fraction`` of a record's edge: from ``amp0`` to ``amp``."""

    return record["amp0"] + (record["amp"] - record["amp0"]) * fraction


def drawn_field(record: dict[str, Any], fraction: float) -> complex:
    """The field the Field look draws at ``fraction`` of a record's edge, from its ``amp0``, ``amp`` and ``phase``."""

    return _field(record, fraction, drawn_amp(record, fraction))


def _owner(group: list[str], records: dict[str, dict[str, Any]]) -> str:
    """The strongest edge of a group (the first by id among equals): it draws the group's shared stretch."""

    best = max(records[g]["amp"] for g in group)
    return min(g for g in group if records[g]["amp"] >= best - 1e-12)


def overlap_profiles(table: dict[str, Any], hidden=()) -> dict[str, list[dict[str, Any]]]:
    """The field drawn along part edges that share a drawn guide with another lit edge of their part at the same
    wavelength: ``{edge id: [{"wavelength_nm", "points", "amp", "phase"}]}``, the amplitude and the (unwrapped) phase
    at each point.

    Edges of one input that start along the same guide (a splitter's stem) carry the light that arrives there: the
    strongest of them draws it (``amp0``), at its own phase, and the others draw nothing there; past the stem each
    draws its own amplitude. Edges of different inputs that end along the same guide (a combiner's stem) meet there:
    the strongest of them draws the complex sum of their fields (at their common end, the engine's output), and the
    others draw nothing there; before the stem each draws the light that arrives at its input."""

    from optodraw.animation_engine.behaviours.geometry import SAME_GUIDE_UM, arc_lengths, densify, distances, leading_run

    hidden = set(hidden)
    groups: dict[tuple[str, float], list[tuple[str, dict[str, Any]]]] = {}
    for edge_id, edge in table["edges"].items():
        if edge_id.startswith("path:") and edge_id not in hidden and len(edge["points"]) >= 2:
            for record in edge["cw"]:
                groups.setdefault((edge_id.split(":")[1], record["wavelength_nm"]), []).append((edge_id, record))
    out: dict[str, list[dict[str, Any]]] = {}
    for (_, nm), lit in sorted(groups.items()):
        if len(lit) < 2:
            continue
        records = dict(lit)
        dense = {e: densify(table["edges"][e]["points"], 0.0, arc_lengths(table["edges"][e]["points"])[-1]) for e in records}
        totals = {e: max(arc_lengths(dense[e])[-1], 1e-12) for e in records}
        lead, trail = {}, {}
        for e, a in records.items():
            for f, b in records.items():
                if e == f:
                    continue
                near = distances(dense[e], dense[f]) <= SAME_GUIDE_UM
                if a["from"] == b["from"]:
                    lead[e, f] = leading_run(near)
                elif a["to"] == b["to"]:
                    trail[e, f] = leading_run(near[::-1])
        for e in sorted(records):
            leads = [f for (a, f), n in lead.items() if a == e and n >= 2]
            trails = [f for (a, f), n in trail.items() if a == e and n >= 2]
            if not leads and not trails:
                continue
            arcs, count = arc_lengths(dense[e]), len(dense[e])
            values, own = [], []
            for i in range(count):
                fraction = arcs[i] / totals[e]
                own.append(cmath.phase(drawn_field(records[e], fraction)))
                group = [e] + [f for f in leads if lead[e, f] > i]
                if len(group) > 1:
                    values.append(_field(records[e], fraction, records[e]["amp0"]) if _owner(group, records) == e else 0j)
                    continue
                group = [e] + [f for f in trails if trail[e, f] > count - 1 - i]
                if len(group) > 1:
                    rest = totals[e] - arcs[i]                          # the drawn distance left to the common end
                    values.append(sum(_field(records[g], max(0.0, 1.0 - rest / totals[g]), records[g]["amp"]) for g in group)
                                  if _owner(group, records) == e else 0j)
                    continue
                values.append(_field(records[e], fraction, records[e]["amp"] if leads else records[e]["amp0"]))
            p0, p1 = records[e]["phase"]
            line = np.array([p0 + (p1 - p0) * arcs[i] / totals[e] for i in range(count)])
            relative = np.array([cmath.phase(v * cmath.exp(-1j * line[i])) if abs(v) > 0 else 0.0 for i, v in enumerate(values)])
            phase = line + np.unwrap(relative)
            out.setdefault(e, []).append({"wavelength_nm": nm, "points": [[round(x, 4), round(y, 4)] for x, y in dense[e]],
                                          "amp": [round(abs(v), 6) for v in values],
                                          "phase": [round(float(p), 5) for p in phase]})
    return out


# ---- multimode regions: a sampled field per region and wavelength -------------------------------------------------


def region_outlines(part: Any) -> list[tuple[str, list[list[float]]]]:
    """The multimode regions of a part's own drawn paths, in its local coordinates: ``[(kind, outline)]``, each once.
    A path's ``region`` is one dict or a list of them (an AWG crosses two slabs)."""

    found, seen = [], set()
    for port in part.ports() if hasattr(part, "optical_paths") else ():
        for path in part.optical_paths(port) or []:
            region = path.get("region")
            for item in (region if isinstance(region, list) else [region] if region else []):
                key = tuple((round(float(x), 6), round(float(y), 6)) for x, y in item["outline"])
                if key not in seen:
                    seen.add(key)
                    found.append((str(item.get("kind", "slab")), [[float(x), float(y)] for x, y in item["outline"]]))
    return found


def inside_polygon(points: np.ndarray, polygon: np.ndarray) -> np.ndarray:
    """For each point, whether it lies inside the polygon (even-odd rule)."""

    x, y = points[:, 0], points[:, 1]
    inside = np.zeros(len(points), bool)
    px, py = polygon[:, 0], polygon[:, 1]
    j = len(polygon) - 1
    for i in range(len(polygon)):
        crosses = (py[i] > y) != (py[j] > y)
        with np.errstate(divide="ignore", invalid="ignore"):
            at = (px[j] - px[i]) * (y - py[i]) / (py[j] - py[i]) + px[i]
        inside ^= crosses & (x < at)
        j = i
    return inside


def _inside_runs(points, polygon: np.ndarray) -> list[tuple[float, float]]:
    """The stretches ``(start arc, end arc)`` of a polyline that run inside the polygon."""

    from optodraw.animation_engine.behaviours.geometry import arc_lengths, densify

    total = arc_lengths(points)[-1]
    dense = np.asarray(densify(points, 0.0, total, min(0.05, total / 2000.0)), float)
    arcs = np.asarray(arc_lengths(dense))
    inside = inside_polygon(0.5 * (dense[1:] + dense[:-1]), polygon)
    runs, start = [], None
    for k, flag in enumerate(inside):
        if flag and start is None:
            start = arcs[k]
        if not flag and start is not None:
            runs.append((float(start), float(arcs[k])))
            start = None
    if start is not None:
        runs.append((float(start), float(arcs[-1])))
    return [(a, b) for a, b in runs if b - a > 1e-6]


def _point_at(points, arc: float) -> np.ndarray:
    from optodraw.animation_engine.behaviours.geometry import cut

    return np.asarray(cut(points, arc, arc)[0], float)


def _encode(z: np.ndarray, times: np.ndarray, inside: np.ndarray) -> tuple[str, float, list[float]]:
    """A region's grid as base64 bytes, four per sample (``[v][u]`` rows): the field's real and imaginary part (128 is
    zero, 127 steps to ``scale``), the arrival time between ``t[0]`` (0) and ``t[1]`` (255), and 255 inside the region
    (0 outside). Sample ``(i, j)`` lies at ``i / (nu - 1)`` along u and ``j / (nv - 1)`` along v: the first and the
    last column are the region's faces. Returns the data, ``scale`` and ``t``."""

    import base64

    scale = float(max(np.max(np.abs(z.real[inside]), initial=0.0), np.max(np.abs(z.imag[inside]), initial=0.0), 1e-12))
    lo, hi = (float(np.min(times[inside])), float(np.max(times[inside]))) if inside.any() else (0.0, 0.0)
    raw = np.zeros(z.shape + (4,), np.uint8)
    raw[..., 0] = np.clip(np.round(127 * z.real / scale) + 128, 1, 255)
    raw[..., 1] = np.clip(np.round(127 * z.imag / scale) + 128, 1, 255)
    raw[..., 2] = np.clip(np.round(255 * (times - lo) / (hi - lo)), 0, 255) if hi > lo else 0
    raw[..., 3] = np.where(inside, 255, 0)
    return base64.b64encode(raw.tobytes()).decode("ascii"), round(scale, 7), [round(lo, 6), round(hi, 6)]


def _samples(length: float, step: float) -> int:
    return int(min(max(math.ceil(length / max(step, 1e-9)), REGION_SAMPLES[0]), REGION_SAMPLES[1]))


def _port_name(port_id: str) -> str:
    return port_id.rsplit(":", 1)[-1]


def _mmi_grid(part: Any, outline, items: list[dict[str, Any]]) -> dict[str, Any]:
    """The field in a rectangular MMI body: a sum over the body's guided modes (a mode-propagation model).

    The modes of a body of width ``W`` are ``sin((m + 1) pi (eta + W / 2) / W)`` with propagation constants
    ``beta_m = beta_0 - m (m + 2) pi / (3 L_pi)``. ``L_pi`` is set so the drawn body is the self-imaging length of its
    design (``3 L_pi / (4 N)`` for a centre-fed 1 x N, ``3 L_pi / N`` for an N x N), so the images form at the drawn
    far face. ``eta`` is the ideal cross coordinate: a piecewise linear map of the drawn one, from the input face's
    ports to the output face's, puts the ideal image places on the drawn ports. The input is a Gaussian of the access
    taper's width on each lit input port, with the field the light has there.

    The engine wins: each image at the far face is given the engine's field there (the drawn field of the edges that
    end at that port). The model's images ``g_k`` are turned by one common phase (the best match), and the rest of
    the difference, ``E_k - g_k``, is added by each image's own field propagated back from the far face, weighted by
    the distance travelled (0 at the input face, 1 at the far face). Where the engine's split is the ideal one, the
    added part is zero and the picture is the mode sum alone."""

    xs, ys = [q[0] for q in outline], [q[1] for q in outline]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    length, width, xc, yc = x1 - x0, y1 - y0, 0.5 * (x0 + x1), 0.5 * (y0 + y1)
    ports = {n: p.center for n, p in part.ports().items() if getattr(p, "kind", "optical") != "electrical"}
    sides = {-1: sorted((n for n in ports if ports[n].x < xc), key=lambda n: ports[n].y),
             1: sorted((n for n in ports if ports[n].x > xc), key=lambda n: ports[n].y)}
    symmetric = int(getattr(part, "input_port_count", 2)) == 1
    design_in = -1 if len(sides[-1]) <= len(sides[1]) else 1
    images = len(sides[-design_in])
    l_pi = (4.0 * images * length / 3.0) if symmetric else (images * length / 3.0)
    taper = part._draw_geometry()[4] if hasattr(part, "_draw_geometry") else 2.0 * float(getattr(part, "waveguide_width", 0.5))
    w0 = 0.5 * float(taper)
    modes = int(min(max(round(3.0 * width / w0), 12), 64))
    m = np.arange(modes)
    shift = m * (m + 2) * math.pi / (3.0 * l_pi)                       # beta_0 - beta_m
    fine = np.linspace(-width / 2.0, width / 2.0, 801)

    def phi(eta):
        return np.sin((m + 1) * math.pi * (np.asarray(eta)[..., None] + width / 2.0) / width)

    def gauss(eta, at):
        return np.exp(-((np.asarray(eta) - at) / w0) ** 2)

    def coefficients(at):
        return (2.0 / width) * np.trapezoid(gauss(fine, at)[:, None] * phi(fine), fine, axis=0)

    def knots(side):
        drawn = [ports[n].y - yc for n in sides[side]]
        if not symmetric:
            ideal = drawn
        elif side == design_in:
            ideal = [0.0] * len(drawn)
        else:
            count = len(drawn)
            ideal = [-width / 2.0 + (2 * p - 1) * width / (2.0 * count) for p in range(1, count + 1)]
        return [-width / 2.0] + drawn + [width / 2.0], [-width / 2.0] + ideal + [width / 2.0], dict(zip(sides[side], ideal))

    first = items[0]
    crest = first["record"]["crest_um"]
    k_c = 2.0 * math.pi / crest
    groups: dict[int, list[dict[str, Any]]] = {}
    for item in items:
        side = -1 if ports[_port_name(item["record"]["from"])].x < xc else 1
        groups.setdefault(side, []).append(item)
    lead = max(groups, key=lambda side: sum(i["record"]["amp"] ** 2 for i in groups[side]))
    step = min(crest / 6.0, w0 / 4.0)                                    # six samples a crest, four an image's half width
    nu, nv = _samples(length, step), _samples(width, step)
    u = np.arange(nu) / (nu - 1)                                         # from the lead input face to the far face
    v = np.arange(nv) / (nv - 1)
    drawn_y = -width / 2.0 + v * width                                   # across, from y0
    total = np.zeros((nv, nu), complex)
    times = np.full((nv, nu), np.inf)
    for side, group in groups.items():
        travelled = (u if side == lead else 1.0 - u) * length            # from this group's input face
        in_drawn, in_ideal, in_at = knots(side)
        out_drawn, out_ideal, out_at = knots(-side)
        frac = travelled / length
        eta = ((1.0 - frac)[None, :] * np.interp(drawn_y, in_drawn, in_ideal)[:, None]
               + frac[None, :] * np.interp(drawn_y, out_drawn, out_ideal)[:, None])
        modes_here = phi(eta)                                            # (nv, nu, modes)
        sources: dict[str, list[dict[str, Any]]] = {}
        for item in group:
            sources.setdefault(_port_name(item["record"]["from"]), []).append(item)
        forward_c = np.zeros(modes, complex)
        for name, found in sources.items():
            owner = min(found, key=lambda i: (-i["record"]["amp"], i["edge"]))
            a = _field(owner["record"], owner["start"], owner["record"]["amp0"])      # the light that arrives
            forward_c = forward_c + a * coefficients(in_at[name])
        targets = {name: 0j for name in out_at}
        for item in group:
            name = _port_name(item["record"]["to"])
            if name in targets:
                targets[name] += _field(item["record"], item["end"], item["record"]["amp"]) * cmath.exp(-1j * k_c * length)
        at_far = phi(fine) @ (forward_c * np.exp(-1j * shift * length))
        norm = np.trapezoid(gauss(fine, 0.0) ** 2, fine)
        images_now = {name: np.trapezoid(at_far * gauss(fine, at), fine) / norm for name, at in out_at.items()}
        match = sum(np.conj(images_now[n]) * targets[n] for n in targets)
        theta = cmath.phase(match) if abs(match) > 1e-15 else 0.0
        field = np.einsum("vum,m,um->vu", modes_here, forward_c, np.exp(-1j * np.outer(travelled, shift)))
        field = field * np.exp(1j * theta * frac)[None, :]
        for name, at in out_at.items():
            rest = targets[name] - images_now[name] * cmath.exp(1j * theta)
            if abs(rest) < 1e-12:
                continue
            back = np.einsum("vum,m,um->vu", modes_here, coefficients(at), np.exp(1j * np.outer(length - travelled, shift)))
            field = field + rest * frac[None, :] * back
        total = total + field * np.exp(1j * k_c * travelled)[None, :]
        t_in = min(i["record"]["t0"] + i["start"] * (i["record"]["t1"] - i["record"]["t0"]) for i in group)
        t_out = min(i["record"]["t0"] + i["end"] * (i["record"]["t1"] - i["record"]["t0"]) for i in group)
        times = np.minimum(times, (t_in + frac * (t_out - t_in))[None, :].repeat(nv, axis=0))
    face = x0 if lead == -1 else x1
    corners = [(face, y0), (x0 + x1 - face, y0), (face, y1)]
    inside = np.ones((nv, nu), bool)
    return {"corners": corners, "local": True, "size": [nu, nv], "z": total, "times": times, "inside": inside}


def _guide_width(part: Any) -> float:
    draw = getattr(part, "_draw", None)
    width = float(getattr(part, "waveguide_width", 0.5) or 0.5)
    try:
        return float(draw("waveguide_width", width)) if callable(draw) else width
    except (AttributeError, TypeError, ValueError):
        return width


def _slab_grid(part: Any, polygon: np.ndarray, items: list[dict[str, Any]]) -> dict[str, Any]:
    """The field in a slab (a star coupler's, an AWG's) or another region that is not a rectangular MMI: the slab's
    spreading. Each lit edge crosses the region from ``A`` to ``B`` as a beam: from a single guide (``A``) it spreads
    out, onto a single guide (``B``, the second slab of an AWG, where the array focuses the light) it narrows. The
    beam's phase runs from the edge's drawn phase at ``A`` to its drawn phase at ``B`` along circles round its narrow
    end, and its amplitude from the edge's at ``A`` to the edge's at ``B``, so the engine's split and phases hold at
    every guide that meets the region. Beams that leave one guide together share the light that arrives there. A beam
    is a Gaussian across its axis; its width grows from the guide's to a share of the far side's."""

    crest = items[0]["record"]["crest_um"]
    axis = sum((np.asarray(i["b"]) - np.asarray(i["a"]) for i in items), np.zeros(2))
    if np.linalg.norm(axis) < 1e-9:
        axis = np.asarray(items[0]["b"]) - np.asarray(items[0]["a"]) + np.array([1e-9, 0.0])
    axis = axis / np.linalg.norm(axis)
    across = np.array([-axis[1], axis[0]])
    along, side = polygon @ axis, polygon @ across
    extent = float(side.max() - side.min())
    o = along.min() * axis + side.min() * across
    corners = [tuple(o), tuple(along.max() * axis + side.min() * across), tuple(along.min() * axis + side.max() * across)]
    guide = 0.6 * _guide_width(part)
    length = float(along.max() - along.min())
    nu, nv = _samples(length, min(crest / 6.0, guide / 1.5)), _samples(extent, min(crest / 6.0, guide / 1.5))
    narrow = max(guide, 1.5 * max(length / (nu - 1), extent / (nv - 1)))     # a beam's narrow end: at least 1.5 samples
    uu, vv = np.meshgrid(np.arange(nu) / (nu - 1), np.arange(nv) / (nv - 1))
    p = (o[None, None, :] + uu[..., None] * (np.asarray(corners[1]) - o) + vv[..., None] * (np.asarray(corners[2]) - o))
    inside = inside_polygon(p.reshape(-1, 2), polygon).reshape(nv, nu)
    total = np.zeros((nv, nu), complex)
    times = np.full((nv, nu), np.inf)
    sharing: dict[tuple, list[dict[str, Any]]] = {}
    for item in items:
        if not item["converge"]:
            key = (item["record"]["from"], round(float(item["a"][0]), 1), round(float(item["a"][1]), 1))
            sharing.setdefault(key, []).append(item)
    for item in items:
        a, b = np.asarray(item["a"], float), np.asarray(item["b"], float)
        record = item["record"]
        span = max(float(np.linalg.norm(b - a)), 1e-9)
        e = (b - a) / span
        n = np.array([-e[1], e[0]])
        rel = p - a
        u = (rel @ e) / span
        rho = rel @ n
        p0, p1 = record["phase"]
        phase_a, phase_b = p0 + (p1 - p0) * item["start"], p0 + (p1 - p0) * item["end"]
        k = (phase_b - phase_a) / span                                   # the edge's own drawn phase per um
        start, end = drawn_amp(record, item["start"]), drawn_amp(record, item["end"])
        fellows = [] if item["converge"] else sharing[(record["from"], round(float(a[0]), 1), round(float(a[1]), 1))]
        if len(fellows) > 1:                    # beams that leave one guide share the light that arrives there
            start, end = record["amp0"] / len(fellows), record["amp"]
            ends = [np.asarray(f["b"], float) for f in fellows if f is not item]
            wide = 0.6 * min(float(np.linalg.norm(b - q)) for q in ends) if ends else 0.4 * extent
        else:
            wide = 0.4 * extent
        wide = max(wide, narrow)
        w = narrow + (wide - narrow) * np.clip(u, 0.0, 1.0) if not item["converge"] else \
            wide + (narrow - wide) * np.clip(u, 0.0, 1.0)
        beyond = np.where(u < 0.0, u * span / w, np.where(u > 1.0, (u - 1.0) * span / w, 0.0))
        amplitude = (start + (end - start) * np.clip(u, 0.0, 1.0)) * np.exp(-(rho / w) ** 2 - beyond ** 2)
        if item["converge"]:
            phase = phase_b - k * np.linalg.norm(p - b, axis=-1)
        else:
            phase = phase_a + k * np.linalg.norm(rel, axis=-1)
        total = total + amplitude * np.exp(1j * phase)
        t_a = record["t0"] + item["start"] * (record["t1"] - record["t0"])
        t_b = record["t0"] + item["end"] * (record["t1"] - record["t0"])
        times = np.minimum(times, t_a + (t_b - t_a) * np.clip(u, 0.0, 1.0))
    return {"corners": corners, "local": False, "size": [nu, nv], "z": total, "times": times, "inside": inside}


def _is_rectangle(outline) -> bool:
    xs = {round(q[0], 6) for q in outline}
    ys = {round(q[1], 6) for q in outline}
    return len(outline) == 4 and len(xs) == 2 and len(ys) == 2


def build_regions(graph: Any, table: dict[str, Any], hidden=()) -> tuple[list[dict[str, Any]], dict[str, list[list[float]]]]:
    """The Field look's multimode regions: a sampled complex field per region and wavelength, and the stretches of
    each edge that a region draws instead (``cuts``: ``{edge id: [[start fraction, end fraction], ...]}``).

    A region item is ``{"host", "region", "kind", "wavelength_nm", "outline" (world x, y), "corners": [origin, end of u,
    end of v] (world x, y), "size": [nu, nv], "scale", "t": [first, last arrival], "fade_ps", "data"}`` (``_encode``). ``u`` runs from the
    side the light enters to the far side. A rectangular MMI body uses the mode-propagation model (``_mmi_grid``);
    a slab, or any other shape, the spreading model (``_slab_grid``)."""

    from optodraw.animation_engine.behaviours.geometry import arc_lengths, local_to_world

    hidden = set(hidden)
    by_part: dict[str, list[str]] = {}
    for edge_id, edge in table["edges"].items():
        if edge_id.startswith("path:") and edge_id not in hidden and edge["cw"] and len(edge["points"]) >= 2:
            by_part.setdefault(edge_id.split(":")[1], []).append(edge_id)
    regions, cuts = [], {}
    for sid in sorted(by_part):
        part = graph.parts[sid]
        outlines = region_outlines(part)
        if not outlines:
            continue
        polygons = [np.asarray(local_to_world(part, outline), float) for _, outline in outlines]
        crossings: dict[str, list[tuple[float, int, float]]] = {}
        for edge_id in sorted(by_part[sid]):
            points = table["edges"][edge_id]["points"]
            for index, polygon in enumerate(polygons):
                for a, b in _inside_runs(points, polygon):
                    crossings.setdefault(edge_id, []).append((a, index, b))
        for edge_id, found in crossings.items():
            found.sort()
            total = arc_lengths(table["edges"][edge_id]["points"])[-1]
            cuts[edge_id] = [[round(a / total, 6), round(b / total, 6)] for a, _, b in found]
        for index, (kind, outline) in enumerate(outlines):
            wavelengths = sorted({r["wavelength_nm"] for e in crossings for r in table["edges"][e]["cw"]})
            for nm in wavelengths:
                items = []
                for edge_id, found in crossings.items():
                    edge = table["edges"][edge_id]
                    record = next((r for r in edge["cw"] if r["wavelength_nm"] == nm), None)
                    total = arc_lengths(edge["points"])[-1]
                    for order, (a, which, b) in enumerate(found):
                        if record is None or which != index:
                            continue
                        items.append({"edge": edge_id, "record": record, "group_index": edge["group_index"],
                                      "start": a / total, "end": b / total,
                                      "a": _point_at(edge["points"], a), "b": _point_at(edge["points"], b),
                                      "converge": len(found) > 1 and order == len(found) - 1})
                if not items:
                    continue
                grid = _mmi_grid(part, outline, items) if kind == "mmi" and _is_rectangle(outline) else \
                    _slab_grid(part, polygons[index], items)
                corners = local_to_world(part, grid["corners"]) if grid["local"] else grid["corners"]
                data, scale, times = _encode(grid["z"], np.where(np.isfinite(grid["times"]), grid["times"], 0.0), grid["inside"])
                crest, n_g = items[0]["record"]["crest_um"], items[0]["group_index"]
                regions.append({"host": sid, "region": index, "kind": kind, "wavelength_nm": nm,
                                "outline": [[round(float(x), 4), round(float(y), 4)] for x, y in polygons[index]],
                                "corners": [[round(float(x), 4), round(float(y), 4)] for x, y in corners],
                                "size": grid["size"], "scale": scale, "t": times,
                                "fade_ps": round(crest * n_g / C_UM_PER_PS, 6), "data": data})
    return regions, cuts


# ---- heat and RF: the closed forms behind the Field look's temperature map and electrode field -------------------

DN_DT_SILICON = 1.8e-4              # d n / d T of silicon at 1550 nm, per kelvin (literature, Komma et al. 2012)


def heater_delta_t_k(phase_rad: float, wavelength_nm: float, length_um: float, dn_dt: float = DN_DT_SILICON) -> float:
    """The rise in temperature (K) that changes the index by ``dn_dt`` per kelvin over ``length_um`` so that the light
    gains ``phase_rad``: phase = 2 pi dn_dt dT length / wavelength."""

    return phase_rad * wavelength_nm * 1e-3 / (2.0 * math.pi * length_um * dn_dt)


def rf_field_v_per_um(voltage: float, gap_um: float) -> float:
    """The field (V per um) between two electrodes ``gap_um`` apart at ``voltage``: the voltage over the gap."""

    return voltage / gap_um
