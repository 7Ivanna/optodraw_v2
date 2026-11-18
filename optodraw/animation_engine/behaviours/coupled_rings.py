"""Series-coupled ring filters: N rings in a column between a bottom bus and a top bus.

Model. Every coupler is a lossless co-directional coupler with power coupling kappa:
``[[t, c], [c, t]]`` with ``t = sqrt(1 - kappa)`` and ``c = -j sqrt(kappa)``. This is the coupler of
Bogaerts et al., "Silicon microring resonators", Laser & Photonics Reviews 6(1), 47-73 (2012), and of
Little et al., "Microring resonator channel dropping filters", J. Lightwave Technol. 15(6), 998-1005
(1997); both take it from Haus, Waves and Fields in Optoelectronics (Prentice-Hall, 1984). The rings are
joined in series as in Madsen and Zhao, Optical Filter Design and Analysis (Wiley, 1999), chapter 5:
each ring has two couplers, so a round trip is two half trips of amplitude ``sqrt(a)`` and phase ``phi / 2``.

For ring k, ``U_k`` is the field that arrives at its upper coupler and ``L_k`` the field that arrives at its
lower coupler. Coupler j sits between ring j and ring j + 1 (coupler 0 is the bottom bus, coupler N the top
bus). With the half-trip factor ``h_k = sqrt(a) exp(j phi_k / 2)`` of ring k:

    U_1 = h_1 (c_0 s + t_0 L_1)                       s = field in the bottom bus
    L_k = h_k (t_k U_k + c_k L_(k+1))
    U_(k+1) = h_(k+1) (c_k U_k + t_k L_(k+1))
    L_N = h_N (t_N U_N + c_N s_top)                   s_top = field in the top bus
    through = t_0 s + c_0 L_1,   drop = c_N U_N + t_N s_top

The solver adds the geometric phase of each path. Neighbouring rings turn in opposite senses, so light
from the bottom bus west end circulates counter-clockwise in ring 1 (chain "a"). Light from the bottom bus
east end circulates the other way (chain "b"). The two chains do not mix, because the model has no
back-reflection. The drop port is the top bus west end for an odd order and the east end for an even order.

The default couplings of a ``CoupledRingFilter`` give a maximally flat passband (see
``butterworth_power_couplings``). Round-trip amplitude and couplings are illustrative defaults,
not measured values.
"""

from __future__ import annotations

import cmath
import math

from ..errors import AnimationError
from ..signals import scalar
from . import Behaviour, Transfer, polyline_length, register
from ..ids import path_id
from .geometry import Rail, Section, cut, drawn_points, index_of, reads
from .interferometers import heater_delay_ps, heater_phase


def _unit(sid: str, name: str, value: float) -> float:
    if not math.isfinite(value) or not 0.0 <= value <= 1.0:
        raise AnimationError(f"{sid}: {name} must be between 0 and 1")
    return value


def ring_phase(sid: str, k: int, params) -> float:
    """The extra round-trip phase of ring k: its own ``phase`` key, else the common ``phase`` key; plus its heater's
    phase (``heater:<sid>:ring<k>``)."""

    ring = f"{sid}:ring{k}"
    return float(params.get(f"phase:{ring}", params.get(f"phase:{sid}", 0.0))) + heater_phase(ring, params)


@register("CoupledRingFilter")
class CoupledRingFilterLight(Behaviour):
    """Parameters (all optional): ``power_coupling:<sid>:c<j>`` for coupler j = 0..N, ``round_trip_amplitude:<sid>``
    (and ``round_trip_amplitude:<sid>:ring<k>``), ``phase:<sid>:ring<k>`` for ring k or ``phase:<sid>`` for every
    ring, and ``heater:<sid>:ring<k>`` (mW), which adds to ring k's phase and delays each half trip by half its
    heater's delay."""

    def rings(self, part, sid):
        return [(f"phase:{sid}:ring{k}", (f"_a{k}u", f"_a{k}l")) for k in range(1, int(part.order) + 1)]

    @staticmethod
    def ends(part, in_port):
        """``(chain, bottom in, bottom out, top in, top out)`` for the chain ``in_port`` belongs to, else None."""

        n = int(part.order)
        top_in = {"a": "o4" if n % 2 else "o3", "b": "o3" if n % 2 else "o4"}
        top_out = {"a": top_in["b"], "b": top_in["a"]}
        bottom_in, bottom_out = {"a": "o1", "b": "o2"}, {"a": "o2", "b": "o1"}
        chain = next((c for c in "ab" if in_port in (bottom_in[c], top_in[c]) or in_port.startswith(f"_{c}")), None)
        return None if chain is None else (chain, bottom_in[chain], bottom_out[chain], top_in[chain], top_out[chain])

    @staticmethod
    def amplitude(part, sid, params, k: int) -> float:
        """The round-trip amplitude of ring k: its own key, else the common one, else the part's."""

        common = _unit(sid, "round_trip_amplitude", float(params.get(f"round_trip_amplitude:{sid}", part.round_trip_amplitude)))
        return _unit(sid, f"round_trip_amplitude of ring {k}", float(params.get(f"round_trip_amplitude:{sid}:ring{k}", common)))

    @staticmethod
    def kappas(part, sid, params) -> list[float]:
        return [_unit(sid, f"power_coupling c{j}", float(params.get(f"power_coupling:{sid}:c{j}", base)))
                for j, base in enumerate(part.effective_power_couplings)]

    def transfers(self, part, sid, in_port, wavelength_nm, params):
        n = int(part.order)
        found_ends = self.ends(part, in_port)
        if found_ends is None:
            return []
        chain, bottom_in, bottom_out, top_in, top_out = found_ends

        kappas = self.kappas(part, sid, params)
        t = [math.sqrt(1.0 - kappa) for kappa in kappas]
        c = [-1j * math.sqrt(kappa) for kappa in kappas]

        def half(k: int) -> complex:
            return math.sqrt(self.amplitude(part, sid, params, k)) * cmath.exp(0.5j * ring_phase(sid, k, params))

        def lag(k: int) -> float:                        # half a trip of ring k: half its heater's delay
            return heater_delay_ps(heater_phase(f"{sid}:ring{k}", params), wavelength_nm) / 2.0

        index = index_of(part, "o1")
        bus_length, loop_length = part.bus_length, part.half_loop_length
        found: list[Transfer] = []

        def add(target: str, amplitude: complex, length: float, delay: float = 0.0) -> None:
            """The path is the part's own drawn one (see ``CoupledRingFilter.optical_paths``)."""

            found.append(Transfer(in_port, target, scalar(amplitude), drawn_points(part, in_port, target, ()), index, "", length,
                                  delay))

        def node(k: int, where: str) -> str:
            return f"_{chain}{k}{where}"

        if in_port == bottom_in:
            add(bottom_out, t[0], bus_length)
            add(node(1, "u"), c[0] * half(1), bus_length / 2.0 + loop_length, lag(1))
        elif in_port == top_in:
            add(top_out, t[n], bus_length)
            add(node(n, "l"), c[n] * half(n), bus_length / 2.0 + loop_length, lag(n))
        else:
            k, where = int(in_port[2:-1]), in_port[-1]
            if where == "u":                             # at the upper coupler of ring k, which is coupler k
                add(node(k, "l"), t[k] * half(k), loop_length, lag(k))
                if k < n:
                    add(node(k + 1, "u"), c[k] * half(k + 1), loop_length, lag(k + 1))
                else:
                    add(top_out, c[n], bus_length / 2.0)
            else:                                        # at the lower coupler of ring k, which is coupler k - 1
                add(node(k, "u"), t[k - 1] * half(k), loop_length, lag(k))
                if k > 1:
                    add(node(k - 1, "l"), c[k - 1] * half(k - 1), loop_length, lag(k - 1))
                else:
                    add(bottom_out, c[0], bus_length / 2.0)
        return found

    def sections(self, part, sid, params):
        """Per chain: the bottom bus with ring 1, each ring with the next, the last ring with the top bus. Each coupler
        sits where two rails touch (a bus's middle, a ring's bottom or top) and works over the stretch around it; a
        ring rail is that stretch and then the half of the ring on to its next coupler (a trip of half the loop)."""

        n, kappas = int(part.order), self.kappas(part, sid, params)
        found = []
        for chain_in in ("o1", "o2"):
            chain, bottom_in, bottom_out, top_in, top_out = self.ends(part, chain_in)

            def path(a, b):
                return drawn_points(part, a, b, ())

            def node(k, where, chain=chain):
                return f"_{chain}{k}{where}"

            up = {k: path(node(k, "l"), node(k, "u")) for k in range(1, n + 1)}
            down = {k: path(node(k, "u"), node(k, "l")) for k in range(1, n + 1)}
            h = min(polyline_length(up[1]), polyline_length(down[1])) / 4.0
            loss = {k: self.amplitude(part, sid, params, k) for k in range(1, n + 1)}

            def around_bottom(k):                      # ring k round its bottom, then up its side to its top window
                arriving = down[k]
                return Rail(cut(arriving, polyline_length(arriving) - h, polyline_length(arriving)) + tuple(up[k][1:]),
                            (0.0, polyline_length(up[k])), (0.0, 2.0 * h), loss[k])

            def around_top(k):                         # ring k round its top, then down its other side
                arriving = up[k]
                return Rail(cut(arriving, polyline_length(arriving) - h, polyline_length(arriving)) + tuple(down[k][1:]),
                            (0.0, polyline_length(down[k])), (0.0, 2.0 * h), loss[k])

            def bus(src, dst):
                points = path(src, dst)
                middle = polyline_length(points) / 2.0
                reach = min(h, middle)
                return Rail(points, (0.0, 2.0 * middle), (middle - reach, middle + reach))

            replaced = frozenset(path_id(sid, x, y) for x, y in (
                [(bottom_in, bottom_out), (bottom_in, node(1, "u")), (top_in, top_out), (top_in, node(n, "l"))]
                + [(node(k, "u"), node(k, "l")) for k in range(1, n + 1)]
                + [(node(k, "u"), node(k + 1, "u") if k < n else top_out) for k in range(1, n + 1)]
                + [(node(k, "l"), node(k, "u")) for k in range(1, n + 1)]
                + [(node(k, "l"), node(k - 1, "l") if k > 1 else bottom_out) for k in range(1, n + 1)]))
            lower_bus, upper_bus = bus(bottom_in, bottom_out), bus(top_in, top_out)
            # each section: its rails, its coupler, its two input ports with where they sit on the rails (a ring port
            # holds the light that arrives at its coupler), and where each port the light leaves to sits
            couplers = [((lower_bus, around_bottom(1)), 0, (bottom_in, (0, 0.0)), (node(1, "l"), (1, h)),
                         {bottom_out: (0, polyline_length(lower_bus.points)), node(1, "u"): (1, h + polyline_length(up[1]))})]
            couplers += [((around_top(k), around_bottom(k + 1)), k, (node(k, "u"), (0, h)), (node(k + 1, "l"), (1, h)),
                          {node(k, "l"): (0, h + polyline_length(down[k])), node(k + 1, "u"): (1, h + polyline_length(up[k + 1]))})
                         for k in range(1, n)]
            couplers.append(((upper_bus, around_top(n)), n, (top_in, (0, 0.0)), (node(n, "u"), (1, h)),
                             {top_out: (0, polyline_length(upper_bus.points)), node(n, "l"): (1, h + polyline_length(down[n]))}))
            for rails, j, one, two, ends in couplers:
                inputs = (reads(self, part, sid, params, *one, ends), reads(self, part, sid, params, *two, ends))
                found.append(Section(rails, inputs, replaced, kappa=kappas[j], cross=-1j))
        return found
