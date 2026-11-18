"""Where the light runs inside a part, in world coordinates, and how fast it goes."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np

from optodraw.core.transform import Vec3

from ..ids import path_id

N_FREE_SPACE, N_FIBRE, N_SILICON = 1.0, 1.468, 4.2
_INDEX_BY_KIND = {"free_space": N_FREE_SPACE, "fiber": N_FIBRE, "optical": N_SILICON}


def port_xy(part: Any, port: str) -> tuple[float, float]:
    centre = part.world_port(port).center
    return (float(centre.x), float(centre.y))


def anchor_xy(part: Any) -> tuple[float, float]:
    point = part.beam_anchor_point()
    return (float(point.x), float(point.y))


def local_to_world(part: Any, points) -> tuple[tuple[float, float], ...]:
    flip = getattr(part, "_flip_local_point", None)
    matrix = part.world_transform.to_matrix_4x4()       # one matrix for every point (``apply_to_point`` builds it each time)
    out = []
    for point in points:
        local = Vec3(float(point[0]), float(point[1]), 0.0)
        if flip is not None:
            local = flip(local)
        world = matrix @ np.array([local.x, local.y, local.z, 1.0])
        out.append((float(world[0]), float(world[1])))
    return tuple(out)


def to_local(part: Any, points) -> tuple[tuple[float, float], ...]:
    """World (x, y) points in the part's own frame: its position and rotation undone (a flip stays)."""

    t = part.world_transform
    o, ex, ey = (t.apply_to_point(Vec3(x, y, 0.0)) for x, y in ((0.0, 0.0), (1.0, 0.0), (0.0, 1.0)))
    ux, uy = (ex.x - o.x, ex.y - o.y), (ey.x - o.x, ey.y - o.y)
    out = []
    for px, py in points:
        dx, dy = px - o.x, py - o.y
        out.append(((dx * ux[0] + dy * ux[1]) / (ux[0] ** 2 + ux[1] ** 2),
                    (dx * uy[0] + dy * uy[1]) / (uy[0] ** 2 + uy[1] ** 2)))
    return tuple(out)


def splice(first, second, at) -> tuple[tuple[float, float], ...]:
    """``first`` up to its point nearest ``at``, then ``second`` from its point nearest ``at``."""

    i = min(range(len(first)), key=lambda k: math.dist(first[k], at))
    j = min(range(len(second)), key=lambda k: math.dist(second[k], at))
    head, tail = tuple(first[:i + 1]), tuple(second[j:])
    return head + tail[1:] if math.dist(head[-1], tail[0]) < 1e-9 else head + tail


def straight(part: Any, in_port: str, out_port: str) -> tuple[tuple[float, float], ...]:
    return (port_xy(part, in_port), port_xy(part, out_port))


def through_anchor(part: Any, in_port: str, out_port: str) -> tuple[tuple[float, float], ...]:
    """A thin free-space optic: the light meets it at its anchor point."""

    return (port_xy(part, in_port), anchor_xy(part), port_xy(part, out_port))


def index_of(part: Any, port: str) -> float:
    own = getattr(part, "group_index", None)
    if own is not None:
        return float(own)
    return _INDEX_BY_KIND.get(part.ports()[port].kind, N_FREE_SPACE)


def optical_path_points(part: Any, in_port: str) -> dict[str, list[tuple[tuple[float, float], ...]]]:
    """``{out port: [world polyline, ...]}`` from the part's own ``optical_paths``, in their order."""

    found: dict[str, list[tuple[tuple[float, float], ...]]] = {}
    for path in part.optical_paths(in_port):
        found.setdefault(path.get("port", ""), []).append(local_to_world(part, path["pts"]))
    return found


def drawn_points(part: Any, in_port: str, out_port: str, fallback) -> tuple[tuple[float, float], ...]:
    """The part's own drawn path from ``in_port`` to ``out_port`` in world coordinates, else ``fallback``."""

    if hasattr(part, "optical_paths"):
        found = optical_path_points(part, in_port).get(out_port)
        if found:
            return found[0]
    return tuple(fallback)


# --- Where coupled light is drawn ---------------------------------------------------------------------------------
# A transfer whose path jumps a coupling gap (a coupler's cross path, a ring's coupling) keeps that path for the
# engine's bookkeeping. For display a part with gaps is drawn by its coupling sections: each section is two drawn
# rails, and each rail carries one light, the coupled-mode field that the section's two input fields give there.

COUPLING_DECAY_PER_UM = 8.0         # field decay outside a silicon wire at 1550 nm: k0 * sqrt(n_eff^2 - n_clad^2)
DISPLAY_STEP_UM = 0.5               # sample spacing inside a coupler


@dataclass(frozen=True)
class Rail:
    """One drawn guide of a section, in the direction the light runs.

    ``points`` is the guide (world); ``draw`` the arc lengths on it where the section's drawing starts and ends (the
    input lead, the coupling window and the tail on to the next section or port); ``window`` the arc lengths of the
    coupling region, None on a rail with a field of its own (a Y-branch stem or arm); ``tail_loss`` the power kept
    from the window's end (or the drawing's start) to the drawing's end, spread evenly along it (a ring's trip)."""

    points: tuple[tuple[float, float], ...]
    draw: tuple[float, float]
    window: tuple[float, float] | None = None
    tail_loss: float = 1.0


@dataclass(frozen=True)
class Read:
    """One way to read a section input from the engine's packets: the listed transfers (their packets summed), each
    as ``(path id, factor, start)``, and ``end``. The factor is what the engine applies after the input's field;
    ``start`` and ``end`` are where the light is on the section's rails (rail, arc length) when the transfer starts
    and when it ends (all end at one port). An arc length outside the drawn rail lies a trip earlier or later (a
    ring's loop)."""

    edges: tuple[tuple[str, complex, tuple[int, float]], ...]
    end: tuple[int, float]

    @property
    def port(self) -> str:
        """The engine port where the transfers end: the engine adds packets that leave one port in one bucket."""

        return self.edges[0][0].split("->", 1)[1].split("#", 1)[0]


@dataclass(frozen=True)
class Section:
    """A 2 x 2 coupling section of a part for one direction of travel, or (``kappa`` None) a stage whose rails each
    carry a field of their own (a Y-branch end: its stem and its two arms).

    ``inputs`` give, per rail, the ways to read the field that comes in on it (``Read``); ``rails.py`` picks one per
    input. ``kappa`` is the engine's power coupling and ``cross`` the phase of its cross coefficient (``i`` or
    ``-i``), so that at the window's end the rails carry the engine's own output. ``replaces`` holds the transfers
    (path ids) whose light the section draws."""

    rails: tuple[Rail, ...]
    inputs: tuple[tuple[Read, ...], ...]
    replaces: frozenset[str]
    kappa: float | None = None
    cross: complex = 1j


def reads(behaviour: Any, part: Any, sid: str, params, port: str, start: tuple[int, float],
          ends: dict[str, tuple[int, float]], pre: complex = 1.0, transfers=None) -> tuple[Read, ...]:
    """Every way to read the input that leaves the engine port ``port`` (at ``start`` on the rails): one read per
    transfer from it to a port in ``ends`` (``{port: (rail, arc length)}``), with the transfer's own matrix over
    ``pre`` as its factor. ``pre`` is the input field over the port's field: 1 where the port holds the light that
    arrives at the coupler, a ring's trip (its loss and phase) where the port holds the light just past it; a trip
    that keeps nothing leaves no way to read the input. ``transfers``: the port's transfers, when the caller has them."""

    if abs(pre) < 1e-12:
        return ()
    if transfers is None:
        transfers = behaviour.transfers(part, sid, port, 1550.0, params)
    return tuple(Read(((path_id(sid, t.in_port, t.out_port, t.name), complex(np.asarray(t.matrix)[0, 0]) / pre, start),),
                      ends[t.out_port])
                 for t in transfers if t.out_port in ends)


def power_gain(matrix) -> float:
    """The power a transfer passes, its matrix's mean over the two polarisations (|m|^2 for a scalar matrix)."""

    return float(np.sum(np.abs(np.asarray(matrix)) ** 2)) / 2.0


def arc_lengths(points) -> list[float]:
    out = [0.0]
    for a, b in zip(points, points[1:]):
        out.append(out[-1] + math.dist(a, b))
    return out


def _at(points, arcs, s) -> tuple[float, float]:
    k = max(0, min(len(points) - 2, int(np.searchsorted(arcs, s, side="right")) - 1))
    span = arcs[k + 1] - arcs[k]
    t = 0.0 if span <= 0 else min(max((s - arcs[k]) / span, 0.0), 1.0)
    return (points[k][0] + (points[k + 1][0] - points[k][0]) * t, points[k][1] + (points[k + 1][1] - points[k][1]) * t)


def cut(points, start: float, end: float) -> tuple[tuple[float, float], ...]:
    """The stretch of a polyline between arc lengths ``start`` and ``end``, its ends interpolated."""

    arcs = arc_lengths(points)
    inner = [tuple(p) for p, s in zip(points, arcs) if start < s < end]
    return (_at(points, arcs, start), *inner, _at(points, arcs, end))


def densify(points, start: float, end: float, step: float = DISPLAY_STEP_UM) -> tuple[tuple[float, float], ...]:
    """The polyline with a point every ``step`` between arc lengths ``start`` and ``end`` (and at both)."""

    arcs = arc_lengths(points)
    extra = list(np.arange(start, end, step)) + [end] if end > start else []
    marks = sorted({round(s, 9) for s in extra if 0.0 <= s <= arcs[-1]} | {round(s, 9) for s in arcs})
    out = [_at(points, arcs, s) for s in marks]
    return tuple(p for i, p in enumerate(out) if i == 0 or math.dist(p, out[i - 1]) > 1e-9)


SAME_GUIDE_UM = 0.05                # a point this close to another path is on the same guide


def leading_run(flags) -> int:
    """How many leading flags are True."""

    return next((i for i, flag in enumerate(flags) if not flag), len(flags))


def distances(points, partner) -> np.ndarray:
    """The distance from each point to the polyline ``partner``."""

    p = np.asarray(points, float)[:, None, :]
    a, b = np.asarray(partner[:-1], float)[None], np.asarray(partner[1:], float)[None]
    ab = b - a
    t = np.clip(np.sum((p - a) * ab, axis=2) / np.maximum(np.sum(ab * ab, axis=2), 1e-18), 0.0, 1.0)
    return np.min(np.linalg.norm(p - (a + t[..., None] * ab), axis=2), axis=1)


def arc_at(points, point) -> float:
    """The arc length along ``points`` of the place nearest ``point``."""

    arcs = arc_lengths(points)
    best, where = math.inf, 0.0
    for k, (a, b) in enumerate(zip(points, points[1:])):
        ab = (b[0] - a[0], b[1] - a[1])
        span = ab[0] ** 2 + ab[1] ** 2
        t = 0.0 if span <= 0 else min(max(((point[0] - a[0]) * ab[0] + (point[1] - a[1]) * ab[1]) / span, 0.0), 1.0)
        d = math.dist(point, (a[0] + t * ab[0], a[1] + t * ab[1]))
        if d < best:
            best, where = d, arcs[k] + t * (arcs[k + 1] - arcs[k])
    return where


def transfer_done(points, partner) -> np.ndarray:
    """At each point of a coupling window (sampled finely): the fraction ``F`` of the coupler's transfer done there,
    from 0 at the first point to 1 at the last.

    With a gap ``g`` that changes along the coupler, coupled-mode theory gives a local coupling that falls as
    ``exp(-COUPLING_DECAY_PER_UM * g)``; ``F`` is its running integral, normalised to 1 (H. A. Haus, Waves and Fields
    in Optoelectronics, Prentice-Hall 1984, chapter 7, with the coupling integrated along a coupler whose gap changes,
    as for ring couplers). ``g`` is the distance to the other rail, ``partner``."""

    s = np.asarray(arc_lengths(points))
    if len(points) < 2 or s[-1] <= 0:
        return np.ones(len(points))
    gap = distances(points, partner)
    local = np.exp(-COUPLING_DECAY_PER_UM * (gap - gap.min()))
    steps = np.concatenate([[0.0], np.cumsum(0.5 * (local[1:] + local[:-1]) * np.diff(s))])
    return steps / steps[-1] if steps[-1] > 0 else s / s[-1]
