"""Physical networks for compound chip components."""
from __future__ import annotations

import cmath
import math

from ..errors import AnimationError
from ..signals import scalar
from . import Behaviour, Transfer, polyline_length, register
from ..ids import path_id
from .geometry import N_SILICON, Rail, Section, drawn_points, local_to_world, reads
from .interferometers import heater_delay_ps, heater_phase
from .resonators import ring_value


@register("MicroringWeightBank")
class SerialWeightBank(Behaviour):
    """Serial add-drop rings with the drawn upper return bus.

    Each bus defaults to power coupling 0.1. Round-trip amplitude defaults to
    0.99. These are illustrative values, not measured weights. An unmatched
    upper-bus end absorbs light. The dN marks locate couplers, not extra splits.
    Per-ring overrides use a ringN suffix, for example heater:bank:ring2. A ring's heater adds to its phase.
    """

    def sinks(self, part, port):
        return port == "_bank_termination"

    def rings(self, part, sid):
        return [(f"phase:{sid}:ring{j + 1}", (f"_ring_bottom_f{j}", f"_ring_top_f{j}"))
                for j in range(len(part._draw_variant()._ring_centers()))]

    @staticmethod
    def couplings(part, sid, params) -> list[tuple[float, float, float, float, float]]:
        """``(power coupling to the lower bus, to the upper bus, round-trip amplitude, round-trip phase, the heater's
        share of that phase)`` per ring."""

        base_k = ring_value(part, sid, params, "power_coupling", 0.1)
        base_drop = ring_value(part, sid, params, "drop_power_coupling", 0.1)
        base_loss = ring_value(part, sid, params, "round_trip_amplitude", 0.99)
        found = []
        for j in range(len(part._draw_variant()._ring_centers())):
            ring_sid = f"{sid}:ring{j+1}"
            heat = heater_phase(ring_sid, params)
            phase = float(params.get(f"phase:{ring_sid}", params.get(f"phase:{sid}", 0))) + heat
            if not math.isfinite(phase):
                raise AnimationError(f"{ring_sid}: ring phase must be finite")
            found.append((ring_value(part, ring_sid, params, "power_coupling", base_k),
                          ring_value(part, ring_sid, params, "drop_power_coupling", base_drop),
                          ring_value(part, ring_sid, params, "round_trip_amplitude", base_loss), phase, heat))
        return found

    @staticmethod
    def rails(draw, j: int, direction: str) -> dict:
        """The drawn rails at ring ``j`` for light going ``direction`` ("f" or "r"), in the drawing's frame: the lower
        and upper bus from the ring's couplers to the next element, the ring half from the bottom to the top
        (``ascending``) and back (``falling``), and the ports they lead to."""

        centers, n = draw._ring_centers(), len(draw._ring_centers())
        lower_y, upper_y, radius, cx = draw.through_bus_y, draw.drop_bus_y, draw.ring_radius, draw._ring_centers()[j]
        left, right = draw.ports()["o1"].center.x, draw.ports()["o2"].center.x
        step = 1 if direction == "f" else -1
        lower_next, upper_next = j + step, j - step
        lower_out = f"_lower_{direction}{lower_next}" if 0 <= lower_next < n else ("o2" if step == 1 else "o1")
        lower_end = (centers[lower_next], lower_y) if 0 <= lower_next < n else ((right if step == 1 else left), lower_y)
        if 0 <= upper_next < n:
            upper_out, upper_end = f"_upper_{direction}{upper_next}", (centers[upper_next], upper_y)
        elif step == 1:
            upper_out, upper_end = "_return_f", (draw.shared_bus_left_x, upper_y)
        else:
            upper_out, upper_end = "_bank_termination", (draw.shared_bus_right_x, upper_y)
        first_half = tuple((cx + radius*math.cos(a), radius*math.sin(a)) for a in (-math.pi/2 + math.pi*k/64 for k in range(65)))
        second_half = tuple((cx + radius*math.cos(a), radius*math.sin(a)) for a in (math.pi/2 + math.pi*k/64 for k in range(65)))
        return {"lower": ((cx, lower_y), lower_end), "upper": ((cx, upper_y), upper_end),
                "lower_out": lower_out, "upper_out": upper_out,
                "ascending": first_half if step == 1 else tuple(reversed(second_half)),
                "falling": second_half if step == 1 else tuple(reversed(first_half))}

    def transfers(self, part, sid, in_port, wavelength_nm, params):
        return self.table(part, sid, params, wavelength_nm).get(in_port, [])

    def table(self, part, sid, params, wavelength_nm: float = 1550.0) -> dict[str, list[Transfer]]:
        """Every transfer of the bank, by its in-port. A half trip round a ring carries half its heater's delay."""

        draw = part._draw_variant()
        centers = draw._ring_centers()
        n = len(centers)
        lower_y = draw.through_bus_y
        left, right = draw.ports()["o1"].center.x, draw.ports()["o2"].center.x
        serial_left, serial_right = draw.shared_bus_left_x, draw.shared_bus_right_x
        physical_x = dict(zip(centers, part._ring_centers()))
        physical_x.update({left: part.ports()["o1"].center.x, right: part.ports()["o2"].center.x,
                           serial_left: part.shared_bus_left_x, serial_right: part.shared_bus_right_x})
        index = float(getattr(part, "group_index", None) or N_SILICON)
        transfers = {}

        def add(source, target, gain, points, name="", length=None, delay=0.0):
            if length is None and len(points) == 2 and points[0][1] == points[1][1]:
                length = abs(physical_x[points[1][0]] - physical_x[points[0][0]])
            transfers.setdefault(source, []).append(Transfer(
                source, target, scalar(gain), local_to_world(part, points), index, name, length, delay))

        return_path = tuple(draw._left_serial_link_path()) + tuple(draw._output_bus_path()[1:])
        return_length = polyline_length(tuple(part._left_serial_link_path()) + tuple(part._output_bus_path()[1:]))
        add("_return_f", "drop", 1, return_path, "return", return_length)
        add("drop", "_upper_r0", 1, tuple(reversed(return_path)) + ((centers[0], draw.drop_bus_y),),
            "return_reverse", return_length + abs(part._ring_centers()[0] - part.shared_bus_left_x))
        add("o1", "_lower_f0", 1, ((left, lower_y), (centers[0], lower_y)))
        add("o2", f"_lower_r{n-1}", 1, ((right, lower_y), (centers[-1], lower_y)))

        for j, (k1, k2, loss, phase, heat) in enumerate(self.couplings(part, sid, params)):
            half, lag = math.sqrt(loss) * cmath.exp(0.5j * phase), heater_delay_ps(heat, wavelength_nm) / 2.0
            t1, t2 = math.sqrt(1-k1), math.sqrt(1-k2)
            c1, c2 = 1j*math.sqrt(k1), 1j*math.sqrt(k2)
            for direction in ("f", "r"):
                r = self.rails(draw, j, direction)
                (lower, lower_end), (upper, upper_end) = r["lower"], r["upper"]
                lower_out, upper_out, ascending, falling = r["lower_out"], r["upper_out"], r["ascending"], r["falling"]
                bottom, top = f"_ring_bottom_{direction}{j}", f"_ring_top_{direction}{j}"
                add(f"_lower_{direction}{j}", lower_out, t1, (lower, lower_end))
                add(f"_lower_{direction}{j}", top, c1*half, (lower,) + ascending + (upper,), length=math.pi*part.ring_radius,
                    delay=lag)
                add(f"_upper_{direction}{j}", upper_out, t2, (upper, upper_end))
                add(f"_upper_{direction}{j}", bottom, c2*half, (upper,) + falling + (lower,), length=math.pi*part.ring_radius,
                    delay=lag)
                add(bottom, lower_out, c1, (lower, lower_end))
                add(bottom, top, t1*half, (lower,) + ascending + (upper,), length=math.pi*part.ring_radius, delay=lag)
                add(top, upper_out, c2, (upper, upper_end))
                add(top, bottom, t2*half, (upper,) + falling + (lower,), length=math.pi*part.ring_radius, delay=lag)
        return transfers

    def sections(self, part, sid, params):
        """Each ring meets the lower bus at its bottom and the upper bus at its top, where the engine's coupler ports
        sit (on the bus). Per ring, coupler and direction one section, working just after the port: the bus rail runs
        on to the next ring or port, the ring rail is the half of the ring on to the other coupler (a trip of half the
        loop). The ring halves are drawn without the engine's hops between the bus point and the ring."""

        draw = part._draw_variant()
        radius = draw.ring_radius
        table = self.table(part, sid, params)
        found = []
        for j, (k1, k2, loss, *_) in enumerate(self.couplings(part, sid, params)):
            for direction in ("f", "r"):
                r = self.rails(draw, j, direction)
                for lower in (True, False):
                    name, kappa = ("lower", k1) if lower else ("upper", k2)
                    bus_port, ring_port = (f"_{name}_{direction}{j}",
                                           (f"_ring_bottom_{direction}{j}" if lower else f"_ring_top_{direction}{j}"))
                    onward = r[f"{name}_out"]
                    ring_end = f"_ring_top_{direction}{j}" if lower else f"_ring_bottom_{direction}{j}"
                    bus = local_to_world(part, r[name])
                    ring = local_to_world(part, r["ascending" if lower else "falling"])
                    reach = min(math.pi * radius / 2.0, polyline_length(bus), polyline_length(ring))
                    ends = {onward: (0, polyline_length(bus)), ring_end: (1, polyline_length(ring))}
                    found.append(Section(
                        (Rail(bus, (0.0, polyline_length(bus)), (0.0, reach)), Rail(ring, (0.0, polyline_length(ring)), (0.0, reach), loss)),
                        (reads(self, part, sid, params, bus_port, (0, 0.0), ends, transfers=table.get(bus_port, [])),
                         reads(self, part, sid, params, ring_port, (1, 0.0), ends, transfers=table.get(ring_port, []))),
                        frozenset(path_id(sid, x, y) for x, y in ((bus_port, onward), (bus_port, ring_end), (ring_port, onward),
                                                                  (ring_port, ring_end))),
                        kappa=kappa, cross=1j))
        return found


@register("CoherentReceiver")
class NinetyDegreeReceiver(Behaviour):
    """Ideal balanced hybrid; internal photodiodes absorb all optical outputs.

    Both Jones components use the same hybrid matrix. The common physical
    length represents a balanced schematic hybrid, not a measured device.
    Currents are instantaneous sums for the supplied absorption records.
    """

    channels = ("_detector_ip", "_detector_in", "_detector_qp", "_detector_qn")

    def sinks(self, part, port):
        return port in self.channels

    def transfers(self, part, sid, in_port, wavelength_nm, params):
        if in_port not in ("signal", "lo"):
            return []
        paths = {(source, target): drawn_points(part, source, target, ()) for source in ("signal", "lo")
                 for target in self.channels}
        balanced_length = sum(polyline_length(path) for path in paths.values()) / len(paths)
        gains = (0.5, 0.5, 0.5, 0.5) if in_port == "signal" else (0.5, -0.5, 0.5j, -0.5j)
        return [Transfer(in_port, target, scalar(gain), paths[(in_port, target)], N_SILICON, "hybrid", balanced_length)
                for target, gain in zip(self.channels, gains)]

    def currents(self, part, absorbed, *, sid=None):
        response = float(part.responsivity_a_per_w)
        if not math.isfinite(response) or response < 0:
            raise AnimationError("receiver responsivity must be finite and nonnegative")
        powers = {port: 0.0 for port in self.channels}
        for record in absorbed:
            if record["port"] in powers and (sid is None or record["part"] == sid):
                powers[record["port"]] += record["power"]
        return {"i_a": response*(powers[self.channels[0]] - powers[self.channels[1]]),
                "q_a": response*(powers[self.channels[2]] - powers[self.channels[3]]),
                "absorbed_w": sum(powers.values())}
