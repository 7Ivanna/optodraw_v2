"""Phase and interference: a phase shifter; Mach-Zehnder interferometers and modulators.

An MZI is given as transfers: each arm to each output. The arms meet at an output port, where the
solver adds them coherently, so the output follows from the arm phases with no special case.
"""

from __future__ import annotations

import cmath
import math

from ..errors import NotModelledYet
from ..signals import C_UM_PER_PS, scalar
from . import Behaviour, Transfer, polyline_length, register
from ..ids import path_id
from .passive import Guide
from .geometry import (Rail, Read, Section, arc_at, cut, distances, drawn_points, index_of, local_to_world, optical_path_points,
                       port_xy, reads, splice, straight, to_local)

P_PI_MW = 20.0                       # heater power for a phase of pi


def heater_phase(sid: str, params) -> float:
    return math.pi * float(params.get(f"heater:{sid}", 0.0)) / P_PI_MW


def heater_delay_ps(phase: float, wavelength_nm: float) -> float:
    """The delay of a heater's phase: the index change that gives ``phase`` over the heated section also slows the
    light there, by ``phase * wavelength / (2 pi c)``. One index change gives both."""

    return phase * wavelength_nm * 1e-3 / (2.0 * math.pi * C_UM_PER_PS)


def mzm_v_pi(part) -> float:
    """The drive (V) that gives a modulator's arms a phase difference of pi."""

    return float(getattr(part, "v_pi", 2.0))


@register("PhaseShifter")
class PhaseShifter(Behaviour):
    def transfers(self, part, sid, in_port, wavelength_nm, params):
        if in_port not in ("o1", "o2"):
            return []
        out = "o2" if in_port == "o1" else "o1"
        heat = 0.0 if f"phase:{sid}" in params else heater_phase(sid, params)
        phase = float(params.get(f"phase:{sid}", heat))
        return [Transfer(in_port, out, scalar(cmath.exp(1j * phase)),
                         drawn_points(part, in_port, out, straight(part, in_port, out)), index_of(part, in_port),
                         extra_delay_ps=heater_delay_ps(heat, wavelength_nm))]


@register("MZI", "MZM")
class MachZehnder(Behaviour):
    """A splitter, two balanced arms and a combiner.

    An end with one port is a Y junction (1/sqrt 2 into each arm). An end with two ports is a 50:50
    coupler whose bar arm is the arm on the port's side. Arm 1 is the upper arm. A port in the middle
    (an arm tap) carries no light. Input on o1 of a coupler MZI: o4 gets cos^2(delta/2) and o3 gets
    sin^2(delta/2). Y-branch MZM: o3 gets cos^2(delta/2); the rest radiates at the output junction.
    """

    def parameter_names(self, part):
        return ("v_pi",) if part.component_type == "MZM" else ()     # its drive swings pi V / v_pi

    def arm_phases(self, part, sid, params) -> tuple[float, float]:
        if part.component_type == "MZM":
            swing = math.pi * float(params.get(f"drive:{sid}", 0.0)) / mzm_v_pi(part)
            return swing / 2.0, -swing / 2.0
        return (float(params.get(f"phase:{sid}:arm1", heater_phase(sid, params))),
                float(params.get(f"phase:{sid}:arm2", 0.0)))

    def arm_heat(self, part, sid, params) -> tuple[float, float]:
        """The share of each arm's phase that its heater gives (arm 1 has the heater; a phase key takes its place). A
        modulator's drive is not a heater: it adds no delay."""

        if part.component_type == "MZM" or f"phase:{sid}:arm1" in params:
            return 0.0, 0.0
        return heater_phase(sid, params), 0.0

    def ends(self, part):
        """The optical ports at the left and right ends, and every optical port in the part's own frame."""

        names = [n for n, p in part.ports().items() if p.kind != "electrical"]
        local = dict(zip(names, to_local(part, [port_xy(part, n) for n in names])))
        return [n for n in names if local[n][0] < -1e-6], [n for n in names if local[n][0] > 1e-6], local

    @staticmethod
    def coupling(end, local, port, arm) -> complex:
        a = 1.0 / math.sqrt(2.0)
        if len(end) == 1:
            return a
        upper = local[port][1] >= max(local[n][1] for n in end)
        return a if upper == (arm == 0) else 1j * a

    def split(self, end, local) -> tuple[float, complex]:
        """A coupler end's power coupling and the phase of its cross coefficient, from ``coupling``: the light from its
        upper port into the upper arm (bar) and into the lower arm (cross)."""

        upper = max(end, key=lambda n: local[n][1])
        bar, cross = self.coupling(end, local, upper, 0), self.coupling(end, local, upper, 1)
        return abs(cross) ** 2 / (abs(bar) ** 2 + abs(cross) ** 2), (cross / bar) / abs(cross / bar)

    def paths(self, part, sid, left, right):
        """{(input, output, arm): path}: the input's drawn arm up to the middle, then the output's drawn arm."""

        def middle(path):                                  # where the path crosses the part's centre line: point, height
            local = to_local(part, path)
            k = min(range(len(path)), key=lambda k: abs(local[k][0]))
            return path[k], local[k][1]

        arms = {}
        for port in left + right:
            drawn = [path for paths in optical_path_points(part, port).values() for path in paths]
            if len(drawn) < 2:
                raise NotModelledYet(f"{sid}: no internal path from {port}")
            drawn.sort(key=lambda path: middle(path)[1], reverse=True)
            arms[port] = (drawn[0], drawn[-1])             # upper arm first
        return {(i, o, arm): splice(arms[i][arm], arms[o][arm][::-1], middle(arms[i][arm])[0])
                for ins, outs in ((left, right), (right, left)) for i in ins for o in outs for arm in (0, 1)}

    def transfers(self, part, sid, in_port, wavelength_nm, params):
        left, right, local = self.ends(part)
        if in_port not in left + right:
            return []
        ins, outs = (left, right) if in_port in left else (right, left)
        phases, heat = self.arm_phases(part, sid, params), self.arm_heat(part, sid, params)
        paths = self.paths(part, sid, left, right)
        mean = sum(polyline_length(path) for path in paths.values()) / len(paths)
        return [Transfer(in_port, out,
                         scalar(self.coupling(ins, local, in_port, arm) * cmath.exp(1j * phases[arm])
                                * self.coupling(outs, local, out, arm)),
                         paths[(in_port, out, arm)], index_of(part, in_port), name=f"arm{arm + 1}", physical_length=mean,
                         extra_delay_ps=heater_delay_ps(heat[arm], wavelength_nm))
                for out in outs for arm in (0, 1)]

    @staticmethod
    def guides(part):
        """The two drawn guides of an MZI, as ``{sign: (world points left to right, arc length of the left end, arc
        length of the right end)}``, and which ends are Y-branches ``{-1: bool, 1: bool}``. A coupler end is a
        directional coupler's drawn centre line; a Y-branch end is the drawn stem and branch."""

        draw = part._draw_variant()
        ports = {n: p for n, p in draw.ports().items() if p.kind != "electrical"}
        y_end = {side: sum(side * p.center.x > 1e-6 for p in ports.values()) == 1 for side in (-1, 1)}   # mid ports: neither end

        def end(side, sign):
            if y_end[side]:
                half = [tuple(q) for q in draw._y_branch_half(sign)]
                return half if side < 0 else [(-x, y) for x, y in half][::-1]
            cx = draw.left_coupler_center_x if side < 0 else draw.right_coupler_center_x
            return [(x + cx, y) for x, y in draw._directional_coupler()._draw_variant()._centerline(sign)]

        found = {}
        for sign in (1.0, -1.0):
            a, b = end(-1, sign), end(1, sign)
            found[sign] = (local_to_world(part, a + b), polyline_length(a), polyline_length(b))
        return found, y_end

    @staticmethod
    def midpoint(points):
        return cut(points, polyline_length(points) / 2.0, polyline_length(points) / 2.0)[0]

    def sections(self, part, sid, params):
        """An MZI or MZM, per direction of travel: its sections in order. A coupler end is a section of the engine's 50 : 50 (its two rails from the ports through the coupler, the input coupler's rails
        on along the arms to the output end); a Y-branch end is a stage: its stem carries the whole input (or the
        output, the coherent sum of the arms) and its arms the arms' fields. Every field is read from the engine's
        packets: an input over its transfer's whole factor, an arm over the output coupling after it."""

        guides, y_end = self.guides(part)
        left, right, local = self.ends(part)
        sections = []
        for ins, outs in ((left, right), (right, left)):
            transfers = {(t.in_port, t.out_port, t.name): t for port in ins
                         for t in self.transfers(part, sid, port, 1550.0, params)}
            start = port_xy(part, ins[0])
            rightward = math.dist(start, guides[1.0][0][0]) <= math.dist(start, guides[1.0][0][-1])
            rails = {s: (pts if rightward else tuple(reversed(pts))) for s, (pts, _, _) in guides.items()}
            reach_in, reach_out = (guides[1.0][1], guides[1.0][2]) if rightward else (guides[1.0][2], guides[1.0][1])
            y_in, y_out = (y_end[-1], y_end[1]) if rightward else (y_end[1], y_end[-1])
            length, out_ref = polyline_length(rails[1.0]), outs[0]
            arm_rail = {m: min((1.0, -1.0), key=lambda s: float(distances([self.midpoint(rails[s])],
                                                                         transfers[(ins[0], out_ref, f"arm{m + 1}")].points)[0]))
                        for m in (0, 1)}
            out_rail = arm_rail[0] if y_out else min((1.0, -1.0), key=lambda s: math.dist(rails[s][-1], port_xy(part, out_ref)))
            arms_end = length - (polyline_length(rails[1.0][-4:]) if y_out else reach_out)
            replaced = frozenset(path_id(sid, a, b, name) for a, b, name in transfers)

            def edge(src, m, dst=out_ref):
                return path_id(sid, src, dst, f"arm{m + 1}")

            def whole(src, m):                         # the transfer's own factor: an input's field from its packet
                return complex(transfers[(src, out_ref, f"arm{m + 1}")].matrix[0, 0])

            def after(m):                              # the output coupling that follows arm m's field
                return self.coupling(outs, local, out_ref, m)

            # every read starts at an input port (arc 0) and ends at out_ref (arc ``length``)
            if y_in:
                stem = polyline_length(rails[1.0][:4])
                stage = (Rail(rails[arm_rail[0]], (0.0, stem)), Rail(rails[arm_rail[0]], (stem, arms_end)),
                         Rail(rails[arm_rail[1]], (stem, arms_end)))
                end = (1 if arm_rail[0] == out_rail else 2, length)
                fields = ((edge(ins[0], 0), whole(ins[0], 0)), (edge(ins[0], 0), after(0)), (edge(ins[0], 1), after(1)))
                sections.append(Section(stage, tuple((Read(((eid, factor, (0, 0.0)),), end),) for eid, factor in fields), replaced))
            else:
                pair = tuple(min((1.0, -1.0), key=lambda s, p=p: math.dist(rails[s][0], port_xy(part, p))) for p in ins)
                end = (pair.index(out_rail), length)
                kappa, cross = self.split(ins, local)
                sections.append(Section(tuple(Rail(rails[s], (0.0, arms_end), (0.0, reach_in)) for s in pair),
                                        tuple((Read(((edge(p, 0), whole(p, 0), (k, 0.0)),), end),) for k, p in enumerate(ins)),
                                        replaced, kappa=kappa, cross=cross))
            if y_out:
                stem = polyline_length(rails[1.0][-4:])
                sections.append(Section((Rail(rails[out_rail], (length - stem, length)),),
                                        ((Read(tuple((edge(p, m), 1.0, (0, 0.0)) for p in ins for m in (0, 1)), (0, length)),),),
                                        replaced))
            else:
                pair = (arm_rail[0], arm_rail[1])
                end = (pair.index(out_rail), length)
                kappa, cross = self.split(outs, local)
                sections.append(Section(tuple(Rail(rails[s], (length - reach_out, length), (length - reach_out, length)) for s in pair),
                                        tuple((Read(tuple((edge(p, m), after(m), (m, 0.0)) for p in ins), end),) for m in (0, 1)),
                                        replaced, kappa=kappa, cross=cross))
        return sections


@register("RingAssistedMZI")
class RingAssistedMachZehnder(MachZehnder):
    """Two 3 dB couplers and two arms; each arm is a phase delay times the all-pass response of its rings.

    Field response of one ring on its arm (C. K. Madsen and J. H. Zhao, Optical Filter Design and Analysis,
    Wiley 1999; the same all-pass ring as ``AllPassRing``)::

        H_ring(phi) = (t - a exp(i phi)) / (1 - t a exp(i phi)),   t = sqrt(1 - kappa),   phi = 2 pi n_g L / lambda

    ``a`` is the field kept per round trip and ``kappa`` the power coupling of the ring to its arm. With the
    coupler matrix C = (1 / sqrt 2) [[1, i], [i, 1]], the field at output port o from input port p is::

        sum over arms m of  C[o, m] exp(i theta_m) prod over rings r on arm m of H_r  C[m, p]

    Each ring is a loop between internal ports, so the solver sums its round trips (the geometric series that
    gives H_ring) and a pulse rings down trip by trip. Rings on one arm sit in series along the arm bus.
    Phases are in radians: ``phase:<id>:arm1``, ``phase:<id>:arm2`` and ``phase:<id>:ring<k>``. On a part with
    heaters, ``heater:<id>`` (arm 1, unless ``phase:<id>:arm1`` is given) and ``heater:<id>:ring<k>`` (added to the
    ring's phase) give mW with the same P_pi as the MZI. A ring is as long as its physical circumference,
    2 pi ring_radius, at any drawing size.
    """

    def arm_phases(self, part, sid, params) -> tuple[float, float]:
        arm1 = params.get(f"phase:{sid}:arm1", heater_phase(sid, params) if part.with_heaters else 0.0)
        return float(arm1), float(params.get(f"phase:{sid}:arm2", 0.0))

    def arm_heat(self, part, sid, params) -> tuple[float, float]:
        return super().arm_heat(part, sid, params) if part.with_heaters else (0.0, 0.0)

    @staticmethod
    def ring_heat(part, sid, k, params) -> float:
        return heater_phase(f"{sid}:ring{k}", params) if part.with_heaters else 0.0

    @classmethod
    def ring_phase(cls, part, sid, k, params) -> float:
        """The extra round-trip phase of ring k: its ``phase`` key, plus its heater's phase."""

        return float(params.get(f"phase:{sid}:ring{k}", 0.0)) + cls.ring_heat(part, sid, k, params)

    def rings(self, part, sid):
        return [(f"phase:{sid}:ring{r['k']}", (f"_r{r['k']}f",)) for r in part._draw_variant().ring_layout()]

    @staticmethod
    def bus(arm: int, direction: str, j: int) -> str:
        """The internal port where the arm bus meets the j-th ring the light reaches (direction f: left to right)."""

        return f"_a{arm}{direction}{j}"

    @staticmethod
    def row(rings, arm: int, from_left: bool):
        """The rings on ``arm`` in the order the light meets them."""

        found = sorted((r for r in rings if r["arm"] == arm), key=lambda r: r["x"])
        return found if from_left else found[::-1]

    @staticmethod
    def lengths(draw, from_left: bool, x: float) -> tuple[float, float]:
        """Distance along the arm from the coupler the light enters to ``x``, and from ``x`` to the other end."""

        near = x + draw.arm_span / 2.0
        return (near, draw.arm_span - near) if from_left else (draw.arm_span - near, near)

    @staticmethod
    def coupler_path(draw) -> float:
        """Path length that one coupler adds to the arm: the drawn path of the bare MZI less the straight arm, halved.

        Every path of the bare MZI has the length of the mean (the arms are balanced), as in ``MachZehnder``."""

        paths = [draw.arm_path(i, o, arm) for i in ("o1", "o2") for o in ("o3", "o4") for arm in (0, 1)]
        return max(sum(polyline_length(p) for p in paths) / len(paths) - draw.arm_span, 0.0) / 2.0

    @staticmethod
    def world(part, points):
        return local_to_world(part, points)

    def ends(self, part):
        """Ends and port heights in the drawing's own frame, the frame of ``draw.arm_path`` and the ring layout.

        ``MachZehnder.ends`` keeps a horizontal flip, which swaps left and right here while those do not swap."""

        names = [n for n, p in part.ports().items() if p.kind != "electrical"]
        local = {n: (float(part.ports()[n].center.x), float(part.ports()[n].center.y)) for n in names}
        return [n for n in names if local[n][0] < -1e-6], [n for n in names if local[n][0] > 1e-6], local

    def transfers(self, part, sid, in_port, wavelength_nm, params):
        draw = part._draw_variant()
        rings = draw.ring_layout()
        if in_port.startswith("_"):
            return self.inside(part, draw, sid, in_port, rings, wavelength_nm, params)
        left, right, local = self.ends(part)
        if in_port not in left + right:
            return []
        from_left = in_port in left
        ins, outs = (left, right) if from_left else (right, left)
        n = index_of(part, "o1")
        phases = self.arm_phases(part, sid, params)
        lag = [heater_delay_ps(heat, wavelength_nm) for heat in self.arm_heat(part, sid, params)]
        couple = self.coupler_path(draw)
        found = []
        for arm in (0, 1):
            c_in = self.coupling(ins, local, in_port, arm)
            row = self.row(rings, arm, from_left)
            if not row:                                       # a bare arm: the MZI
                for out in outs:
                    c_out = self.coupling(outs, local, out, arm)
                    found.append(Transfer(in_port, out, scalar(c_in * cmath.exp(1j * phases[arm]) * c_out),
                                          self.world(part, draw.arm_path(in_port, out, arm)), n, name=f"arm{arm + 1}",
                                          physical_length=2.0 * couple + draw.arm_span, extra_delay_ps=lag[arm]))
                continue
            x = row[0]["x"]
            path = draw.arm_path(in_port, outs[0], arm)
            head = [p for p in path if (p[0] < x if from_left else p[0] > x)]
            found.append(Transfer(in_port, self.bus(arm, "f" if from_left else "b", 0), scalar(c_in * cmath.exp(1j * phases[arm])),
                                  self.world(part, [*head, (x, row[0]["sign"] * draw.arm_gap / 2.0)]), n, name=f"arm{arm + 1}",
                                  physical_length=couple + self.lengths(draw, from_left, x)[0], extra_delay_ps=lag[arm]))
        return found

    def ring_at(self, rings, in_port):
        """``(ring, arm, j, from_left)`` for an internal port: the ring, its arm and its place in that arm's row."""

        from_left = (in_port[-1] if in_port.startswith("_r") else in_port[3]) == "f"
        if in_port.startswith("_r"):
            ring = next(r for r in rings if r["k"] == int(in_port[2:-1]))
            return ring, ring["arm"], self.row(rings, ring["arm"], from_left).index(ring), from_left
        arm, j = int(in_port[2]), int(in_port[4:])
        return self.row(rings, arm, from_left)[j], arm, j, from_left

    def loop(self, part, draw, ring, from_left):
        """The drawn loop of ``ring`` from its point at the arm, the way the light goes round."""

        start = -90.0 if ring["sign"] > 0 else 90.0
        turn = 360.0 if (ring["sign"] > 0) == from_left else -360.0
        return self.world(part, [(ring["x"] + draw.ring_radius * math.cos(math.radians(start + turn * i / 48)),
                                  ring["y"] + draw.ring_radius * math.sin(math.radians(start + turn * i / 48)))
                                 for i in range(49)])

    def sections(self, part, sid, params):
        """Per direction of travel: the input coupler, each ring on its arm in the order the light meets them, the
        output coupler. A coupler's rails are the two drawn guides through it (as the MZI); a ring section is the arm
        and the ring around the ring's point on the arm, where the engine couples them, and its ring rail goes once
        round (a trip with its loss). Arm fields at the output coupler are read over the output coupling."""

        draw = part._draw_variant()
        rings = draw.ring_layout()
        left, right, local = self.ends(part)
        ports = {n: p for n, p in draw.ports().items() if p.kind != "electrical"}

        def outer(side, top):
            names = [n for n in ports if side * ports[n].center.x > 1e-6]
            return (max if top else min)(names, key=lambda n: ports[n].center.y)

        guides = {1.0: self.world(part, draw.arm_path(outer(-1, True), outer(1, True), 0)),
                  -1.0: self.world(part, draw.arm_path(outer(-1, False), outer(1, False), 1))}
        region = 2.0 * polyline_length(draw._half_rail(1.0))       # a coupler: its two half rails
        a = float(getattr(part, "round_trip_amplitude", 0.99))
        sections = []
        for from_left in (True, False):
            ins, outs = (left, right) if from_left else (right, left)
            d, out_ref = "f" if from_left else "b", (right if from_left else left)[0]
            rails = {s: (g if from_left else tuple(reversed(g))) for s, g in guides.items()}
            length = polyline_length(rails[1.0])
            side = {n: 1.0 if ports[n].center.y > 0 else -1.0 for n in ports}
            transfers = {}
            for port in ins + [self.bus(m, d, j) for m in (0, 1) for j in range(len(self.row(rings, m, from_left)))] \
                    + [f"_r{r['k']}{d}" for r in rings]:
                for t in self.transfers(part, sid, port, 1550.0, params):
                    transfers[(t.in_port, t.out_port, t.name)] = t
            replaced = frozenset(path_id(sid, x, y, name) for x, y, name in transfers)
            row = {m: self.row(rings, m, from_left) for m in (0, 1)}
            loops = {r["k"]: self.loop(part, draw, r, from_left) for r in rings}
            h = {r["k"]: polyline_length(loops[r["k"]]) / 8.0 for r in rings}
            at = {r["k"]: arc_at(rails[1.0 if r["arm"] == 0 else -1.0],
                                 self.world(part, [(r["x"], r["sign"] * draw.arm_gap / 2.0)])[0]) for r in rings}
            starts = {m: [at[r["k"]] - h[r["k"]] for r in row[m]] + [length - region] for m in (0, 1)}

            def c_out(m):
                return self.coupling(outs, local, out_ref, m)

            end = (0 if side[out_ref] > 0 else 1, length)

            def arm_light(m):                          # arm m's light at the output coupler, read over the coupling after it
                if not row[m]:
                    return Read(tuple((path_id(sid, p, out_ref, f"arm{m + 1}"), c_out(m), (m, 0.0)) for p in ins), end)
                last = row[m][-1]                      # the light from the last ring went once round it to the arm
                return Read(((path_id(sid, self.bus(m, d, len(row[m]) - 1), out_ref, f"arm{m + 1}"), c_out(m), (m, at[last["k"]])),
                             (path_id(sid, f"_r{last['k']}{d}", out_ref, f"ring{last['k']}"), c_out(m),
                              (m, at[last["k"]] - polyline_length(loops[last["k"]])))), end)

            # the input coupler: each input over its whole transfer, along a bare arm (or to the first ring of arm 0)
            pair = tuple(side[p] for p in ins)
            bare = next((m for m in (0, 1) if not row[m]), None)
            if bare is not None:
                ends = {out_ref: (pair.index(side[out_ref]), length)}
            else:
                ends = {self.bus(0, d, 0): (pair.index(1.0), at[row[0][0]["k"]])}
            kappa, cross = self.split(ins, local)
            sections.append(Section(tuple(Rail(rails[s], (0.0, starts[0 if s > 0 else 1][0]), (0.0, region)) for s in pair),
                                    tuple(reads(self, part, sid, params, p, (k, 0.0), ends) for k, p in enumerate(ins)),
                                    replaced, kappa=kappa, cross=cross))
            for m in (0, 1):
                for j, ring in enumerate(row[m]):
                    k, s = ring["k"], 1.0 if m == 0 else -1.0
                    loop = loops[k]
                    around = cut(loop, polyline_length(loop) - h[k], polyline_length(loop)) + tuple(loop[1:])
                    port = f"_r{k}{d}"
                    onward = (self.bus(m, d, j + 1), at[row[m][j + 1]["k"]]) if j + 1 < len(row[m]) else (out_ref, length)
                    ends = {port: (1, h[k]), onward[0]: (0, onward[1])}
                    # the ring port holds the light just past the coupler: the light that arrives there is a trip later
                    trip = a * cmath.exp(1j * self.ring_phase(part, sid, k, params))
                    sections.append(Section(
                        (Rail(rails[s], (at[k] - h[k], starts[m][j + 1]), (at[k] - h[k], at[k] + h[k])),
                         Rail(around, (0.0, polyline_length(loop)), (0.0, 2.0 * h[k]), a * a)),
                        (reads(self, part, sid, params, self.bus(m, d, j), (0, at[k]), ends),
                         reads(self, part, sid, params, port, (1, h[k] - polyline_length(loop)), ends, pre=trip)),
                        replaced, kappa=part.ring_power_coupling(k), cross=-1j))
            kappa, cross = self.split(outs, local)
            sections.append(Section(tuple(Rail(rails[s], (length - region, length), (length - region, length)) for s in (1.0, -1.0)),
                                    ((arm_light(0),), (arm_light(1),)), replaced, kappa=kappa, cross=cross))
        return sections

    def inside(self, part, draw, sid, in_port, rings, wavelength_nm, params):
        """From an arm bus point (``_a<arm><f|b><j>``) or a ring loop (``_r<k><f|b>``). A trip round a ring carries the
        delay of its heater's phase."""

        loop_port = in_port.startswith("_r")
        direction = in_port[-1] if loop_port else in_port[3]
        left, right, local = self.ends(part)
        ring, arm, j, from_left = self.ring_at(rings, in_port)
        outs = right if from_left else left
        n = index_of(part, "o1")
        row = self.row(rings, arm, from_left)
        k = ring["k"]
        kappa = part.ring_power_coupling(k)
        t, cross = math.sqrt(1.0 - kappa), -1j * math.sqrt(kappa)
        y_arm = ring["sign"] * draw.arm_gap / 2.0
        onward = j + 1 < len(row)
        step = abs(row[j + 1]["x"] - ring["x"]) if onward else self.lengths(draw, from_left, ring["x"])[1] + self.coupler_path(draw)
        along = [(ring["x"], y_arm), (row[j + 1]["x"], y_arm)] if onward else None
        found = []

        def leave(gain, lead_points, extra_length, name, lag=0.0):
            """Transfers from ``source`` to the next bus point, or to the outputs when this is the last ring."""

            if onward:
                found.append(Transfer(in_port, self.bus(arm, direction, j + 1), scalar(gain), self.world(part, lead_points + along),
                                      n, name=name, physical_length=extra_length + step, extra_delay_ps=lag))
                return
            first = "o1" if from_left else "o3"
            for out in outs:
                tail = [p for p in draw.arm_path(first, out, arm) if (p[0] > ring["x"] if from_left else p[0] < ring["x"])]
                found.append(Transfer(in_port, out, scalar(gain * self.coupling(outs, local, out, arm)),
                                      self.world(part, [*lead_points, (ring["x"], y_arm), *tail]), n, name=name,
                                      physical_length=extra_length + step, extra_delay_ps=lag))

        hop = [(ring["x"], y_arm), (ring["x"], ring["y"] - ring["sign"] * draw.ring_radius)]
        if not loop_port:
            # the hop across the gap has no length: the through and the coupled light leave the same point,
            # so the all-pass response keeps its phase
            found.append(Transfer(in_port, f"_r{k}{direction}", scalar(cross), self.world(part, hop), n, name=f"ring{k}",
                                  physical_length=0.0))
            leave(t, [], 0.0, f"arm{arm + 1}")
            return found
        a = float(getattr(part, "round_trip_amplitude", 0.99))
        extra = cmath.exp(1j * self.ring_phase(part, sid, k, params))
        lag = heater_delay_ps(self.ring_heat(part, sid, k, params), wavelength_nm)
        circumference = 2.0 * math.pi * part.ring_radius
        loop = list(self.loop(part, draw, ring, from_left))
        found.append(Transfer(in_port, in_port, scalar(a * t * extra), tuple(loop), n, name=f"ring{k}", physical_length=circumference,
                              extra_delay_ps=lag))
        leave(a * cross * extra, hop[:1], circumference, f"ring{k}", lag)
        return found


@register("IQModulator")
class NestedMachZehnder(Guide):
    """Two push-pull Mach-Zehnders side by side, the Q arm 90 degrees behind the I arm: the field out is
    (cos(phi_I / 2) + i cos(phi_Q / 2)) / 2, phi = pi V / v_pi for the drives ``drive:<sid>:i`` and
    ``drive:<sid>:q`` (v_pi 2 V, as for ``MZM``). At zero drive half the power leaves: the quadrature combiner keeps
    3 dB."""

    def amplitude(self, part, sid, wavelength_nm, params):
        i, q = (math.cos(math.pi * float(params.get(f"drive:{sid}:{arm}", 0.0)) / mzm_v_pi(part) / 2.0) for arm in "iq")
        return (i + 1j * q) / 2.0
