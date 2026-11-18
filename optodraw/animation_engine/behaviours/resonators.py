"""All-pass ring resonators: a bus, a coupler, and a loop the light goes round until it fades.

The loop is an internal port. Each trip round it costs the round-trip amplitude and adds the
round-trip phase; at the coupler a share ``kappa`` of the power leaves to the bus. The extra round-trip
phase is the ring's ``phase:<sid>`` plus its heater's phase (``heater:<sid>``, mW); the heater's share
also delays each trip.
"""

from __future__ import annotations

import cmath
import math

from ..signals import scalar
from ..errors import AnimationError
from . import Behaviour, Transfer, polyline_length, register
from ..ids import path_id
from .geometry import Rail, Section, cut, index_of, local_to_world, optical_path_points, reads
from .interferometers import heater_delay_ps, heater_phase


def trip_phase(sid: str, params) -> tuple[float, float]:
    """``(extra round-trip phase, the heater's share of it)``: the ring's ``phase`` key plus its heater's phase."""

    heat = heater_phase(sid, params)
    return float(params.get(f"phase:{sid}", 0.0)) + heat, heat


@register("MicroringResonator", "RacetrackResonator", "PNMicroringModulator")
class AllPassRing(Behaviour):
    """Default power coupling is 0.1 per bus; round-trip amplitude is 0.99.

    Add-drop rings use two couplers and two causal half-loop transfers.
    These generic defaults are illustrative, not measured device parameters.
    """
    parameters = ("power_coupling", "round_trip_amplitude", "group_index")

    def parameter_names(self, part):
        return self.parameters + (("drop_power_coupling",) if getattr(part, "add_drop", False) else ())

    def geometry(self, part, forward: bool):
        drawn = optical_path_points(part, "o1")
        bus = drawn["o2"][0]
        loop = drawn[""][0]
        if not forward:
            bus, loop = tuple(reversed(bus)), tuple(reversed(loop))
        join = min(range(len(bus)), key=lambda i: math.dist(bus[i], loop[0]))
        return bus, loop, join

    def rings(self, part, sid):
        return [(f"phase:{sid}", ("_ring_bottom", "_ring_top") if getattr(part, "add_drop", False) else ("_ring",))]

    def transfers(self, part, sid, in_port, wavelength_nm, params):
        if getattr(part, "add_drop", False):
            return _add_drop_transfers(self, part, sid, in_port, wavelength_nm, params)
        if in_port not in ("o1", "o2", "_ring", "_ring_r"):
            return []
        forward = in_port in ("o1", "_ring")
        inside = "_ring" if forward else "_ring_r"
        out = "o2" if forward else "o1"
        kappa = ring_value(part, sid, params, "power_coupling", 0.1)
        t, cross = math.sqrt(1.0 - kappa), -1j * math.sqrt(kappa)
        a = ring_value(part, sid, params, "round_trip_amplitude", 0.99)
        phase, heat = trip_phase(sid, params)
        extra, lag = cmath.exp(1j * phase), heater_delay_ps(heat, wavelength_nm)
        bus, loop, join = self.geometry(part, forward)
        n = index_of(part, "o1")
        # Physical lengths keep the phases consistent: the path through the ring runs the whole bus
        # (to the coupler, then from it) plus the loop, so it shares the direct path's bus phase.
        to_coupler, from_coupler = polyline_length(bus[:join + 1]), polyline_length(bus[join:])
        if in_port in ("o1", "o2"):
            return [Transfer(in_port, out, scalar(t), bus, n),
                    Transfer(in_port, inside, scalar(cross), bus[:join + 1] + (loop[0],), n,
                             physical_length=to_coupler)]
        return [Transfer(inside, inside, scalar(a * t * extra), loop, n, extra_delay_ps=lag),
                Transfer(inside, out, scalar(a * cross * extra), loop + bus[join:], n,
                         physical_length=polyline_length(loop) + from_coupler, extra_delay_ps=lag)]

    def sections(self, part, sid, params):
        """One section per direction: the bus and the ring close in on the point where they meet (the engine's
        coupling point, ``join``), and the coupling works over the stretch before it. The bus rail runs from the
        input to the output; the ring rail is that stretch of the ring and then the trip round to it again."""

        if getattr(part, "add_drop", False):
            return _add_drop_sections(self, part, sid, params)
        k = ring_value(part, sid, params, "power_coupling", 0.1)
        a = ring_value(part, sid, params, "round_trip_amplitude", 0.99)
        trip = a * cmath.exp(1j * trip_phase(sid, params)[0])
        found = []
        for forward in (True, False):
            src, dst, inside = ("o1", "o2", "_ring") if forward else ("o2", "o1", "_ring_r")
            bus, loop, join = self.geometry(part, forward)
            meet, length, bus_length = polyline_length(bus[:join + 1]), polyline_length(loop), polyline_length(bus)
            reach = min(meet, length / 2.0)
            ring = cut(loop, length - reach, length) + tuple(loop[1:])
            # the ring port holds the light just past the coupler: the light that arrives there is a trip later
            ends = {dst: (0, bus_length), inside: (1, reach)}
            inputs = (reads(self, part, sid, params, src, (0, 0.0), ends),
                      reads(self, part, sid, params, inside, (1, reach - length), ends, pre=trip))
            found.append(Section((Rail(bus, (0.0, bus_length), (meet - reach, meet)),
                                  Rail(ring, (0.0, length), (0.0, reach), a * a)),
                                 inputs,
                                 frozenset(path_id(sid, x, y) for x, y in ((src, dst), (src, inside), (inside, inside),
                                                                           (inside, dst))),
                                 kappa=k, cross=-1j))
        return found


def ring_value(part, sid, params, name, default):
    value = params.get(f"{name}:{sid}", getattr(part, name, None))
    value = default if value is None else value
    try:
        value = float(value)
    except (TypeError, ValueError) as error:
        raise AnimationError(f"{sid}: {name} must be between 0 and 1") from error
    if not math.isfinite(value) or not 0 <= value <= 1:
        raise AnimationError(f"{sid}: {name} must be between 0 and 1")
    return value


def _add_drop_geometry(behaviour, part, forward: bool) -> dict:
    """The drawn rails of an add-drop ring: the lower bus and where it meets the loop, the upper bus and where it
    meets the loop, and the loop's two halves (from the lower coupler to the upper one, and back)."""

    upper_in, upper_out = ("o4", "o3") if forward else ("o3", "o4")
    bus, loop, lower_join = behaviour.geometry(part, forward)
    ports = part.ports()
    start, end = ports[upper_in].center, ports[upper_out].center
    upper = local_to_world(part, [(start.x + (end.x-start.x)*i/32, start.y) for i in range(33)])
    upper_join = min(range(len(upper)), key=lambda i: math.dist(upper[i], loop[len(loop)//2]))
    top_join = min(range(1, len(loop)-1), key=lambda i: math.dist(loop[i], upper[upper_join]))
    return {"bus": bus, "loop": loop, "lower_join": lower_join, "upper": upper, "upper_join": upper_join,
            "first": loop[:top_join+1], "second": loop[top_join:]}


def _add_drop_transfers(behaviour, part, sid, in_port, wavelength_nm, params):
    """Each half trip carries half the ring's extra phase, and half its heater's delay."""

    forward = in_port in {"o1", "o4", "_ring_bottom", "_ring_top"}
    lower_in, lower_out = ("o1", "o2") if forward else ("o2", "o1")
    upper_in, upper_out = ("o4", "o3") if forward else ("o3", "o4")
    suffix = "" if forward else "_r"
    bottom, top = "_ring_bottom" + suffix, "_ring_top" + suffix
    if in_port not in {lower_in, upper_in, bottom, top}:
        return []
    g = _add_drop_geometry(behaviour, part, forward)
    bus, loop, lower_join, upper, upper_join = g["bus"], g["loop"], g["lower_join"], g["upper"], g["upper_join"]
    first, second = g["first"], g["second"]
    k1 = ring_value(part, sid, params, "power_coupling", 0.1)
    k2 = ring_value(part, sid, params, "drop_power_coupling", 0.1)
    a = ring_value(part, sid, params, "round_trip_amplitude", 0.99)
    t1, t2 = math.sqrt(1-k1), math.sqrt(1-k2)
    c1, c2 = -1j*math.sqrt(k1), -1j*math.sqrt(k2)
    extra, heat = trip_phase(sid, params)
    half, lag = math.sqrt(a)*cmath.exp(1j*extra/2), heater_delay_ps(heat, wavelength_nm) / 2.0
    n = index_of(part, "o1")

    def transfer(out, amplitude, points, length, delay=0.0):
        return Transfer(in_port, out, scalar(amplitude), points, n, physical_length=length, extra_delay_ps=delay)

    lower_lead, lower_tail = bus[:lower_join+1], bus[lower_join:]
    upper_lead, upper_tail = upper[:upper_join+1], upper[upper_join:]
    if in_port == lower_in:
        return [transfer(lower_out, t1, bus, polyline_length(bus)),
                transfer(top, c1*half, lower_lead + first, polyline_length(lower_lead)+polyline_length(first), lag)]
    if in_port == upper_in:
        return [transfer(upper_out, t2, upper, polyline_length(upper)),
                transfer(bottom, c2*half, upper_lead + second,
                         polyline_length(upper_lead)+polyline_length(second), lag)]
    if in_port == bottom:
        return [transfer(lower_out, c1, (loop[0],) + lower_tail, polyline_length(lower_tail)),
                transfer(top, t1*half, first, polyline_length(first), lag)]
    return [transfer(upper_out, c2, (first[-1],) + upper_tail, polyline_length(upper_tail)),
            transfer(bottom, t2*half, second, polyline_length(second), lag)]


def _add_drop_sections(behaviour, part, sid, params):
    """Two sections per direction, at the lower and the upper bus: each bus and the ring close in on the point where
    they meet, and the coupling works over the stretch around it. A ring rail is that stretch and then the half of the
    ring on to the other coupler."""

    k1 = ring_value(part, sid, params, "power_coupling", 0.1)
    k2 = ring_value(part, sid, params, "drop_power_coupling", 0.1)
    a = ring_value(part, sid, params, "round_trip_amplitude", 0.99)
    found = []
    for forward in (True, False):
        g = _add_drop_geometry(behaviour, part, forward)
        lower_in, lower_out = ("o1", "o2") if forward else ("o2", "o1")
        upper_in, upper_out = ("o4", "o3") if forward else ("o3", "o4")
        suffix = "" if forward else "_r"
        bottom, top = "_ring_bottom" + suffix, "_ring_top" + suffix
        quarter = polyline_length(g["loop"]) / 4.0
        meets = {"lower": polyline_length(g["bus"][:g["lower_join"] + 1]), "upper": polyline_length(g["upper"][:g["upper_join"] + 1])}
        reach = {name: min(meets[name], polyline_length(bus) - meets[name], quarter)
                 for name, bus in (("lower", g["bus"]), ("upper", g["upper"]))}
        replaced = frozenset(path_id(sid, x, y) for x, y in ((lower_in, lower_out), (lower_in, top), (upper_in, upper_out),
                                                              (upper_in, bottom), (bottom, lower_out), (bottom, top),
                                                              (top, upper_out), (top, bottom)))
        for name, bus, src, dst, port, kappa, stays, goes, other in (
                ("lower", g["bus"], lower_in, lower_out, bottom, k1, g["first"], g["second"], "upper"),
                ("upper", g["upper"], upper_in, upper_out, top, k2, g["second"], g["first"], "lower")):
            meet, h, bus_length, before = meets[name], reach[name], polyline_length(bus), polyline_length(goes)
            ring = cut(goes, before - h, before) + tuple(stays[1:])
            ring_end = h + polyline_length(stays) - reach[other]
            onward = top if name == "lower" else bottom
            ends = {dst: (0, bus_length), onward: (1, h + polyline_length(stays))}
            inputs = (reads(behaviour, part, sid, params, src, (0, 0.0), ends),
                      reads(behaviour, part, sid, params, port, (1, h), ends))
            found.append(Section((Rail(bus, (0.0, bus_length), (meet - h, meet + h)), Rail(ring, (0.0, ring_end), (0.0, 2.0 * h), a)),
                                 inputs, replaced, kappa=kappa, cross=-1j))
    return found


@register("RacetrackModulator")
class RacetrackModulatorRing(AllPassRing):
    """A racetrack modulator carries light as its racetrack does; its drive moves the ring's phase (``phase:<sid>``)."""
