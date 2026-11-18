"""Mach-Zehnder interferometer and modulator components."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from optodraw.core.ports import Port
from optodraw.core.schematic_geometry import PhysicalSpec
from optodraw.core.transform import Vec3

from optodraw.components.onchip.base import ChipComponent, _generic_pdk_defaults, SILICON_EDGE
from optodraw.components.onchip.geometry import (
    GERMANIUM,
    GERMANIUM_EDGE,
    GOLD,
    GOLD_EDGE,
    N_DOPED,
    N_EDGE,
    P_DOPED,
    P_EDGE,
    _contact_children,
    _pad_children,
    _arc_band_points,
    _arc_points,
    _chip_box,
    _chip_circle,
    _chip_extruded_polygon,
    _chip_polygon,
    _chip_segment_polygon,
    _chip_segment_slab,
    _chip_slab,
    _cut_footprints,
    _pad_on_via,
    _vias,
    _mirror_points_x,
    _segment_outline,
    _translate_points,
    _polyline_outline,
    _rotate_2d_node_ccw,
    _rotate_3d_node_ccw,
    _translate_layout_geometry,
    _mirror_layout_geometry_y,
)
from optodraw.components.onchip.splitters import DirectionalCoupler, YBranch, _densify

@dataclass
class MZI(ChipComponent):
    component_type = "MZI"
    schematic_family = "mzi"
    coupler_length: float = 25.5
    coupler_width: float = 2.5
    arm_length: float = 40.0
    arm_gap: float = 12.0
    waveguide_width: float = 0.5
    taper_length: float = 10.0

    def __init__(self, center=(0, 0), angle=0, coupler_length: float | None = None, coupler_width: float | None = None, arm_length=40.0, arm_gap=12.0, waveguide_width: float | None = None, taper_length: float | None = None, waveguide_gap: float | None = None, **kwargs):
        defaults = _generic_pdk_defaults()
        mmi = defaults["mmi"]
        strip = defaults["strip"]
        ring = defaults["ring"]
        self.coupler_length = float(mmi["footprint_length"] if coupler_length is None else coupler_length)
        self.coupler_width = float(mmi["width_mmi"] if coupler_width is None else coupler_width)
        self.arm_length = float(arm_length)
        self.arm_gap = float(arm_gap)
        self.waveguide_width = float(strip["width"] if waveguide_width is None else waveguide_width)
        self.taper_length = float(mmi["length_taper"] if taper_length is None else taper_length)
        self.waveguide_gap = float(ring["gap"] if waveguide_gap is None else waveguide_gap)
        self._init_chip(center=center, angle=angle, **kwargs)

    def physical_spec(self) -> PhysicalSpec:
        return PhysicalSpec(
            device_family=self.schematic_family,
            values={
                "coupler_length": self.coupler_length,
                "coupler_width": self.coupler_width,
                "arm_length": self.arm_length,
                "arm_gap": self.arm_gap,
                "waveguide_width": self.waveguide_width,
                "taper_length": self.taper_length,
                "waveguide_gap": self.waveguide_gap,
                "thickness": self.chip_thickness,
            },
        )

    def _draw_variant(self) -> MZI:
        if self.render_physical:
            return self
        return MZI(
            coupler_length=self._draw("coupler_length", self.coupler_length),
            coupler_width=self._draw("coupler_width", self.coupler_width),
            arm_length=self._draw("arm_length", self.arm_length),
            arm_gap=self._draw("arm_gap", self.arm_gap),
            waveguide_width=self._draw("waveguide_width", self.waveguide_width),
            taper_length=self._draw("taper_length", self.taper_length),
            waveguide_gap=self._draw("waveguide_gap", self.waveguide_gap),
            **self._draw_variant_kwargs(),
        )

    def _anchor_points(self) -> dict[str, tuple[float, float]]:
        """The gap of each coupler and the middle of each arm, where the drawing shows them."""

        draw = self._draw_variant()
        if draw is not self:
            return draw._anchor_points()
        return {"left_coupler": (self.left_coupler_center_x, 0.0), "right_coupler": (self.right_coupler_center_x, 0.0),
                "upper_arm": (0.0, self.arm_gap / 2.0), "lower_arm": (0.0, -self.arm_gap / 2.0)}

    @property
    def left_coupler_center_x(self) -> float:
        return -(self.arm_length / 2.0 + self.coupler_length / 2.0)

    @property
    def right_coupler_center_x(self) -> float:
        return self.arm_length / 2.0 + self.coupler_length / 2.0

    def anim_behaviors(self) -> list[dict]:
        return [
            {"key": "bias", "label": "Bias point", "options": [
                ["auto", "Peak (full transmission)"], ["quad", "Quadrature (half)"],
                ["null", "Null (destructive)"]]},
            {"key": "heater", "label": "Arm heater", "options": [
                ["auto", "On (phase tuning)"], ["off", "Off"]]},
        ]


    def _directional_coupler(self) -> DirectionalCoupler:
        minimum_coupling = max(self.waveguide_width * 4.0, 1.5)
        if self.coupler_length <= minimum_coupling:
            coupling_length = self.coupler_length
            transition_length = 0.0
            straight_length = 0.0
        else:
            # Split the coupler the same way the standalone DirectionalCoupler does
            # (coupling : transition : straight-access ≈ 20 : 8 : 4 of the total) so the
            # MZI's coupler ends — S-bends + straight access stubs — match it exactly.
            coupling_length = self.coupler_length * (20.0 / 44.0)
            transition_length = self.coupler_length * (8.0 / 44.0)
            straight_length = self.coupler_length * (4.0 / 44.0)
        return DirectionalCoupler(
            coupling_length=coupling_length,
            transition_length=transition_length,
            straight_length=straight_length,
            port_spacing=self.arm_gap,
            waveguide_gap=self.waveguide_gap,
            waveguide_width=self.waveguide_width,
            color=self.color,
            opacity=self.opacity,
            chip_thickness=self.chip_thickness,
            material_preset=self.material_preset,
            render_physical=self.render_physical,
            visual_scale=self.visual_scale,
        )

    # --- thermo-optic phase shifter on the upper arm (makes the MZI tunable) ---
    @property
    def heater_length(self) -> float:
        return self.arm_length * 0.6

    @property
    def heater_strip_width(self) -> float:
        return max(self.waveguide_width * 2.2, 1.1)  # reads at arm scale, like the ring heaters

    @property
    def heater_pad_size(self) -> float:
        return max(self.waveguide_width * 3.6, 2.0)

    @property
    def heater_pad_x(self) -> float:
        # leads rise straight off the bar ends, so the pads centre on them
        return self.heater_length / 2.0 - self.heater_strip_width / 2.0

    @property
    def heater_pad_y(self) -> float:
        return self.arm_gap / 2.0 + self.heater_pad_size * 1.9  # lead run matches the rings'

    @property
    def heater_via_size(self) -> float:
        return max(self.heater_strip_width * 0.7, 0.32)

    def _heater_polygon(self) -> list[tuple[float, float]]:
        """The WHOLE heater as one closed outline: the bar over the upper arm,
        two leads that keep the FULL bar width until they reach the pads, and
        both pads (wider squares) — a single metal polygon (as on the rings)."""

        dy = self.arm_gap / 2.0
        w2 = self.heater_strip_width / 2.0
        hl = self.heater_length / 2.0
        px, py = self.heater_pad_x, self.heater_pad_y
        s = self.heater_pad_size / 2.0
        y_j = py - s  # pad bottom edge — where the leads land
        return [
            (-hl, dy - w2), (hl, dy - w2),        # bar, along the bottom
            (hl, y_j),                            # right lead, outer edge up
            (px + s, y_j), (px + s, py + s),      # right pad, out and around
            (px - s, py + s), (px - s, y_j),
            (px - w2, y_j), (px - w2, dy + w2),   # right lead, inner edge down
            (-px + w2, dy + w2),                  # bar, back along the top
            (-px + w2, y_j),                      # left lead, inner edge up
            (-px + s, y_j), (-px + s, py + s),    # left pad, out and around
            (-px - s, py + s), (-px - s, y_j),
            (-hl, y_j),                           # left lead, outer edge down
        ]

    def _heater_via_centers(self) -> list[tuple[float, float]]:
        # a via sits in the MIDDLE of each pad
        return [(-self.heater_pad_x, self.heater_pad_y), (self.heater_pad_x, self.heater_pad_y)]

    def _heater_children_2d(self) -> list[dict[str, Any]]:
        return [
            _chip_polygon(self._heater_polygon(), fill="#d4af37", opacity=self.opacity, stroke="#8e7611", stroke_width=0.08),
            *[
                _chip_box(via_x, via_y, self.heater_via_size, self.heater_via_size, "#f08c6d", self.opacity, stroke="#8b5038", stroke_width=0.08)
                for via_x, via_y in self._heater_via_centers()
            ],
        ]

    def _heater_children_3d(self) -> list[dict[str, Any]]:
        stack = self._draw_layer_stack()
        return [
            _chip_extruded_polygon(self._heater_polygon(), stack["heater_height"], color="#d4af37", preset="gold", z_offset=stack["heater_z"]),
            *_vias(self.heater_via_size, self._heater_via_centers(), stack),
        ]

    def ports(self) -> dict[str, Port]:
        draw = self._draw_variant()
        if draw is not self:
            return draw.ports()
        dc = self._directional_coupler()
        left_ports = dc.ports()
        right_ports = dc.ports()
        return {
            "o1": Port("o1", Vec3(self.left_coupler_center_x + left_ports["o1"].center.x, left_ports["o1"].center.y, 0), orientation_deg=180, width=self.waveguide_width),
            "o2": Port("o2", Vec3(self.left_coupler_center_x + left_ports["o2"].center.x, left_ports["o2"].center.y, 0), orientation_deg=180, width=self.waveguide_width),
            "o3": Port("o3", Vec3(self.right_coupler_center_x + right_ports["o3"].center.x, right_ports["o3"].center.y, 0), orientation_deg=0, width=self.waveguide_width),
            "o4": Port("o4", Vec3(self.right_coupler_center_x + right_ports["o4"].center.x, right_ports["o4"].center.y, 0), orientation_deg=0, width=self.waveguide_width),
            "h1": Port("h1", Vec3(-self.heater_pad_x, self.heater_pad_y, 0), orientation_deg=90, width=self.heater_pad_size, kind="electrical"),
            "h2": Port("h2", Vec3(self.heater_pad_x, self.heater_pad_y, 0), orientation_deg=90, width=self.heater_pad_size, kind="electrical"),
        }

    def geometry_2d(self) -> dict[str, Any]:
        draw = self._draw_variant()
        if draw is not self:
            return draw.geometry_2d()

        dc = self._directional_coupler()
        dy = self.arm_gap / 2.0
        body_height = max(self.coupler_width, dc.body_height)
        upper_arm = _segment_outline((-self.arm_length / 2.0, dy), (self.arm_length / 2.0, dy), self.waveguide_width, self.waveguide_width)
        lower_arm = _segment_outline((-self.arm_length / 2.0, -dy), (self.arm_length / 2.0, -dy), self.waveguide_width, self.waveguide_width)
        children = [
            _chip_box(self.left_coupler_center_x, 0.0, self.coupler_length, body_height, self.color, self.opacity * 0.14, stroke=SILICON_EDGE, stroke_width=0.05),
            _chip_box(self.right_coupler_center_x, 0.0, self.coupler_length, body_height, self.color, self.opacity * 0.14, stroke=SILICON_EDGE, stroke_width=0.05),
            _chip_polygon(_translate_points(dc._polygon(1.0), self.left_coupler_center_x, 0.0), fill=self.color, opacity=self.opacity, stroke=SILICON_EDGE, stroke_width=0.08),
            _chip_polygon(_translate_points(dc._polygon(-1.0), self.left_coupler_center_x, 0.0), fill=self.color, opacity=self.opacity, stroke=SILICON_EDGE, stroke_width=0.08),
            _chip_polygon(_translate_points(dc._polygon(1.0), self.right_coupler_center_x, 0.0), fill=self.color, opacity=self.opacity, stroke=SILICON_EDGE, stroke_width=0.08),
            _chip_polygon(_translate_points(dc._polygon(-1.0), self.right_coupler_center_x, 0.0), fill=self.color, opacity=self.opacity, stroke=SILICON_EDGE, stroke_width=0.08),
            _chip_polygon(upper_arm, fill=self.color, opacity=self.opacity, stroke=SILICON_EDGE, stroke_width=0.08),
            _chip_polygon(lower_arm, fill=self.color, opacity=self.opacity, stroke=SILICON_EDGE, stroke_width=0.08),
        ]
        children.extend(self._heater_children_2d())
        return {"type": "group", "children": children}

    def geometry_3d(self) -> dict[str, Any]:
        draw = self._draw_variant()
        if draw is not self:
            return draw.geometry_3d()

        dc = self._directional_coupler()
        dy = self.arm_gap / 2.0
        upper_arm = _segment_outline((-self.arm_length / 2.0, dy), (self.arm_length / 2.0, dy), self.waveguide_width, self.waveguide_width)
        lower_arm = _segment_outline((-self.arm_length / 2.0, -dy), (self.arm_length / 2.0, -dy), self.waveguide_width, self.waveguide_width)
        children = [
            _chip_extruded_polygon(_translate_points(dc._polygon(1.0), self.left_coupler_center_x, 0.0), self._draw_thickness(), **self._core()),
            _chip_extruded_polygon(_translate_points(dc._polygon(-1.0), self.left_coupler_center_x, 0.0), self._draw_thickness(), **self._core()),
            _chip_extruded_polygon(_translate_points(dc._polygon(1.0), self.right_coupler_center_x, 0.0), self._draw_thickness(), **self._core()),
            _chip_extruded_polygon(_translate_points(dc._polygon(-1.0), self.right_coupler_center_x, 0.0), self._draw_thickness(), **self._core()),
            _chip_extruded_polygon(upper_arm, self._draw_thickness(), **self._core()),
            _chip_extruded_polygon(lower_arm, self._draw_thickness(), **self._core()),
        ]
        children.extend(self._heater_children_3d())
        return self._on_the_stack(children)

    def optical_paths(self, in_port: str) -> list[dict[str, Any]]:
        """The interferometer's waveguide paths on the SAME centerlines it draws.

        The MZI is drawn as two DirectionalCouplers (translated to the coupler
        centres) joined by straight arms at +/- arm_gap/2 — so the animation paths
        are exactly those DC raised-cosine centerlines plus the arm straights. Light
        entering splits: one path stays on the entry rail through the left coupler,
        the other hops rails at its coupling centre; both traverse their arm and
        recombine through the right coupler to the same exit port."""

        draw = self._draw_variant()
        if draw is not self:
            draw.anim_params = self.anim_params  # behaviours ride along
            return draw.optical_paths(in_port)
        ports = self.ports()
        if in_port not in ports or getattr(ports[in_port], "kind", "optical") == "electrical":
            return []
        entry = ports[in_port]
        going_right = float(entry.center.x) < 0
        exits = [
            (name, p) for name, p in ports.items()
            if name != in_port and getattr(p, "kind", "optical") != "electrical"
            and (float(p.center.x) > 0) == going_right
        ]
        if not exits:
            return []
        target = min(exits, key=lambda np: abs(float(np[1].center.y) - float(entry.center.y)))[0]
        sign_in = 1.0 if float(entry.center.y) >= 0 else -1.0
        coupler = self._directional_coupler()._draw_variant()
        x_first = self.left_coupler_center_x if going_right else self.right_coupler_center_x
        x_second = self.right_coupler_center_x if going_right else self.left_coupler_center_x

        def shifted(centerline: list, shift_x: float) -> list[list[float]]:
            pts = [[x + shift_x, y] for x, y in _densify(centerline)]
            return pts if going_right else pts[::-1]

        def rail_hop_index(pts: list[list[float]], centre_x: float) -> int:
            for index, (x, _) in enumerate(pts):
                if (x >= centre_x) if going_right else (x <= centre_x):
                    return index
            return len(pts) // 2

        paths = []
        for arm_sign in (sign_in, -sign_in):
            first_same = shifted(coupler._centerline(sign_in), x_first)
            if arm_sign == sign_in:
                first = first_same  # bar: stay on the entry rail
            else:
                first_other = shifted(coupler._centerline(arm_sign), x_first)
                hop = rail_hop_index(first_same, x_first)
                first = first_same[:hop] + first_other[rail_hop_index(first_other, x_first):]
            # the straight arm continues on the same rail into the second coupler,
            # which recombines: arm rail -> exit rail (the target port's side)
            second_same = shifted(coupler._centerline(arm_sign), x_second)
            if arm_sign == sign_in:
                second = second_same
            else:
                second_exit = shifted(coupler._centerline(sign_in), x_second)
                hop = rail_hop_index(second_same, x_second)
                second = second_same[:hop] + second_exit[rail_hop_index(second_exit, x_second):]
            pts = first + second
            params = getattr(self, "anim_params", None) or {}
            bias = {"quad": 0.5, "null": 0.05, "peak": 1.0}.get(str(params.get("bias", "auto")), 1.0)
            # the arms carry half each up to the combiner; the OUTPUT section then
            # carries the interference result set by the bias point
            k = max(int(len(pts) * 0.8), 1)
            path = {"port": target, "power": 0.5 * bias, "pts": pts,
                    "powers": [0.5] * k + [0.5 * bias] * (len(pts) - k)}
            heater_on = str(params.get("heater", "on")) != "off"
            if arm_sign > 0 and heater_on:
                # the thermo-optic phase shifter sits on the UPPER arm: as it warms
                # the interferometer detunes and the output swings (thermal switch)
                path["mod"] = {"sign": -1, "depth": 0.9, "tau_s": 1.4}
            paths.append(path)
        return paths

    def physics_metadata(self) -> dict[str, Any]:
        return {
            "domain": "on_chip",
            "component": "mzi",
            "arm_length": self.arm_length,
            "arm_gap": self.arm_gap,
            "phase_bias": 0.0,
            "extinction_ratio_db": None,
            "waveguide_width": self.waveguide_width,
        }


@dataclass
class RingAssistedMZI(MZI):
    """A ring-assisted Mach-Zehnder interferometer (RAMZI): an MZI with microrings side-coupled to its arms.

    Each ring is an all-pass resonator on its arm bus. The rings turn the cosine response of a plain MZI
    into a sharp, flat-top filter edge (C. K. Madsen and J. H. Zhao, Optical Filter Design and Analysis,
    Wiley 1999).

    ``rings_per_arm`` is ``(top, bottom)``. Rings on the top arm sit above it and rings on the bottom arm
    sit below it, so a ring never lies between the arms. Rings are numbered from 1: the top row from left to
    right, then the bottom row from left to right. Ring ``k`` has the heater ports ``rh{k}a`` and ``rh{k}b``
    (top rings face north, bottom rings face south). The arm phase shifter, ports ``h1`` and ``h2``, sits on
    the top arm beside the rings.

    ``ring_gap`` is the bus to ring gap: one value for all rings, or one per ring. ``coupler`` is ``"dc"``
    (directional couplers, as the MZI) or ``"mmi"`` (2x2 MMI couplers with S-bends to the arms).
    ``arm_length`` is the minimum straight arm length: the arms grow when the rings (and the phase
    shifter) need more room.
    """

    component_type = "RingAssistedMZI"
    schematic_family = "ramzi"
    rings_per_arm: tuple[int, int] = (1, 0)
    ring_radius: float = 10.0
    ring_gap: float | tuple[float, ...] = 0.2
    coupler: str = "dc"
    with_heaters: bool = True
    round_trip_amplitude: float = 0.99      # field kept per ring round trip (the animation uses it)

    def __init__(
        self,
        center=(0, 0),
        angle=0,
        rings_per_arm=(1, 0),
        ring_radius: float | None = None,
        ring_gap: float | list[float] | tuple[float, ...] | None = None,
        arm_length: float = 40.0,
        arm_gap: float = 12.0,
        coupler: str = "dc",
        with_heaters: bool = True,
        **kwargs,
    ):
        counts = tuple(int(n) for n in rings_per_arm)
        if len(counts) != 2 or min(counts) < 0:
            raise ValueError("rings_per_arm must be a pair of counts, (top, bottom), for example (1, 0)")
        kind = str(coupler).lower()
        if kind not in {"dc", "mmi"}:
            raise ValueError("coupler must be 'dc' or 'mmi'")
        ring_defaults = _generic_pdk_defaults()["ring"]
        gap = ring_defaults["gap"] if ring_gap is None else ring_gap
        if isinstance(gap, (list, tuple)):
            gap = tuple(float(g) for g in gap)
            if len(gap) != sum(counts):
                raise ValueError(f"ring_gap lists {len(gap)} gaps for {sum(counts)} rings")
        else:
            gap = float(gap)
        self.rings_per_arm = counts
        self.ring_radius = float(ring_defaults["radius"] if ring_radius is None else ring_radius)
        self.ring_gap = gap
        self.coupler = kind
        self.with_heaters = bool(with_heaters)
        super().__init__(center=center, angle=angle, arm_length=arm_length, arm_gap=arm_gap, **kwargs)

    # --- parameters, physical and drawn -------------------------------------------------------------
    @property
    def ring_count(self) -> int:
        return sum(self.rings_per_arm)

    def _ring_gaps(self) -> tuple[float, ...]:
        if isinstance(self.ring_gap, tuple):
            return self.ring_gap
        return (float(self.ring_gap),) * self.ring_count

    def ring_power_coupling(self, k: int) -> float:
        """Power coupling of ring ``k`` (1 based) from its gap.

        A rule of thumb for a silicon strip guide: the evanescent field falls as exp(-2 gamma gap) in power
        with 1 / (2 gamma) of about 0.064 um, and 0.1 at a gap of 0.2 um (the value the single ring uses).
        It sets the animation only, it is not a solver result."""

        gap = self._ring_gaps()[k - 1]
        return min(0.9, 0.1 * math.exp(-(gap - 0.2) / 0.064))

    def physical_spec(self) -> PhysicalSpec:
        values = dict(super().physical_spec().values)
        gaps = self._ring_gaps()
        values.update(
            {
                "ring_radius": self.ring_radius,
                "ring_gap": min(gaps) if gaps else float(_generic_pdk_defaults()["ring"]["gap"]),
                "ring_count": self.ring_count,
            }
        )
        return PhysicalSpec(device_family=self.schematic_family, values=values)

    def _draw_ring_gaps(self) -> tuple[float, ...]:
        gaps = self._ring_gaps()
        if self.render_physical:
            return gaps
        reference = float(_generic_pdk_defaults()["ring"]["gap"])
        scale = self._draw("ring_gap", reference) / reference
        return tuple(g * scale for g in gaps)

    def _draw_variant(self) -> RingAssistedMZI:
        if self.render_physical:
            return self
        return RingAssistedMZI(
            rings_per_arm=self.rings_per_arm,
            ring_radius=self._draw("ring_radius", self.ring_radius),
            ring_gap=self._draw_ring_gaps(),
            coupler=self.coupler,
            with_heaters=self.with_heaters,
            coupler_length=self._draw("coupler_length", self.coupler_length),
            coupler_width=self._draw("coupler_width", self.coupler_width),
            arm_length=self._draw("arm_length", self.arm_length),
            arm_gap=self._draw("arm_gap", self.arm_gap),
            waveguide_width=self._draw("waveguide_width", self.waveguide_width),
            taper_length=self._draw("taper_length", self.taper_length),
            waveguide_gap=self._draw("waveguide_gap", self.waveguide_gap),
            **self._draw_variant_kwargs(),
        )

    def anim_behaviors(self) -> list[dict]:
        return [{"key": "heater", "label": "Heaters", "options": [["auto", "On (phase tuning)"], ["off", "Off"]]}]

    # --- layout along the arms ----------------------------------------------------------------------
    @property
    def _ring_margin(self) -> float:
        return max(self.waveguide_width * 4.0, 3.0)

    @property
    def ring_cell(self) -> float:
        """x pitch of the rings along an arm."""

        return 2.0 * (self.ring_radius + self.waveguide_width / 2.0) + self._ring_margin

    @property
    def _arm_heater_beside_rings(self) -> bool:
        return self.with_heaters and self.ring_count > 0

    @property
    def _heater_min_length(self) -> float:
        return 3.0 * self.heater_pad_size + self.heater_strip_width

    @property
    def _heater_segment(self) -> float:
        """Arm length taken by the phase shifter when rings share the arm."""

        return self._heater_min_length + self._ring_margin if self._arm_heater_beside_rings else 0.0

    @property
    def arm_span(self) -> float:
        """The straight arm length that is drawn: ``arm_length``, or more when the rings need it."""

        need = max(self.rings_per_arm, default=0) * self.ring_cell + self._heater_segment
        return max(self.arm_length, need)

    @property
    def heater_length(self) -> float:
        if self._arm_heater_beside_rings:
            return self._heater_segment - self._ring_margin
        return self.arm_span * 0.6

    @property
    def arm_heater_x(self) -> float:
        return -self.arm_span / 2.0 + self._heater_segment / 2.0

    @property
    def _ring_zone_x(self) -> float:
        """x of the middle of the part of the arms that holds the rings."""

        return self._heater_segment / 2.0

    def ring_layout(self) -> list[dict[str, Any]]:
        """Every ring: number, arm (0 top, 1 bottom), centre x and y, gap and the side its pads face."""

        gaps = self._ring_gaps()
        rings: list[dict[str, Any]] = []
        k = 0
        for arm, count in enumerate(self.rings_per_arm):
            sign = 1.0 if arm == 0 else -1.0
            for i in range(count):
                gap = gaps[k]
                k += 1
                rings.append({
                    "k": k, "arm": arm, "sign": sign,
                    "x": self._ring_zone_x + (i - (count - 1) / 2.0) * self.ring_cell,
                    "y": sign * (self.arm_gap / 2.0 + self.ring_radius + gap + self.waveguide_width),
                    "gap": gap,
                })
        return rings

    # --- couplers -----------------------------------------------------------------------------------
    @property
    def _mmi(self) -> dict[str, float]:
        """Sizes of one MMI coupler: the footprint ``coupler_length`` (taper, body, taper) and S-bends."""

        w = self.waveguide_width
        taper = min(self.taper_length, self.coupler_length * 0.4)
        body = max(self.coupler_length - 2.0 * taper, 0.3 * self.coupler_length)
        tip_gap = 0.5 * self.coupler_width                         # between the two taper tips
        tip_width = max(min(0.4 * self.coupler_width, 0.8 * tip_gap), w)
        rise = max((self.arm_gap - tip_gap) / 2.0, 0.0)
        bend = 2.2 * rise                                          # keeps the raised cosine below about 35 degrees
        return {"taper": taper, "body": body, "tip_gap": tip_gap, "tip_width": tip_width, "bend": bend,
                "foot": body + 2.0 * taper, "span": body + 2.0 * taper + 2.0 * bend}

    @property
    def coupler_span(self) -> float:
        if self.coupler == "mmi":
            return self._mmi["span"]
        return self._directional_coupler().total_length

    @property
    def left_coupler_center_x(self) -> float:
        return -(self.arm_span / 2.0 + self.coupler_span / 2.0)

    @property
    def right_coupler_center_x(self) -> float:
        return self.arm_span / 2.0 + self.coupler_span / 2.0

    def _coupler_polygons(self) -> list[list[tuple[float, float]]]:
        """The silicon of one coupler, centred on x = 0 (both couplers are this shape)."""

        if self.coupler == "dc":
            dc = self._directional_coupler()
            return [dc._polygon(1.0), dc._polygon(-1.0)]
        m, w = self._mmi, self.waveguide_width
        polygons = [[(-m["body"] / 2.0, -self.coupler_width / 2.0), (m["body"] / 2.0, -self.coupler_width / 2.0),
                     (m["body"] / 2.0, self.coupler_width / 2.0), (-m["body"] / 2.0, self.coupler_width / 2.0)]]
        for sign in (1.0, -1.0):
            tip = sign * m["tip_gap"] / 2.0
            bend = _polyline_outline(self._bend_centerline(sign), w)
            taper = _segment_outline((-m["foot"] / 2.0, tip), (-m["body"] / 2.0, tip), w, m["tip_width"])
            polygons += [bend, taper, _mirror_points_x(bend), _mirror_points_x(taper)]
        return polygons

    def _bend_centerline(self, sign: float, steps: int = 20) -> list[tuple[float, float]]:
        """The MMI S-bend, from the arm end (the coupler's outer port) in to the taper tip."""

        m, y_arm = self._mmi, self.arm_gap / 2.0
        tip = m["tip_gap"] / 2.0
        x0 = -m["span"] / 2.0
        if m["bend"] < 1e-9:
            return [(x0, sign * y_arm), (x0 + 1e-6, sign * tip)]
        points = []
        for i in range(steps + 1):
            t = i / steps
            blend = 0.5 - 0.5 * math.cos(math.pi * t)
            points.append((x0 + m["bend"] * t, sign * (y_arm + (tip - y_arm) * blend)))
        return points

    def _half_rail(self, sign: float) -> list[tuple[float, float]]:
        """The drawn guide of one coupler rail from its outer port to the coupler centre (x = 0)."""

        if self.coupler == "dc":
            line = [p for p in self._directional_coupler()._centerline(sign) if p[0] < -1e-9]
            return [*line, (0.0, sign * self._directional_coupler().coupling_spacing / 2.0)]
        m = self._mmi
        tip = sign * m["tip_gap"] / 2.0
        return [*self._bend_centerline(sign), (-m["body"] / 2.0, tip), (0.0, tip)]

    def arm_path(self, in_port: str, out_port: str, arm: int) -> list[tuple[float, float]]:
        """The drawn light path (part frame) from ``in_port`` to ``out_port`` along arm ``arm`` (0 top)."""

        ports = self.ports()
        from_left = float(ports[in_port].center.x) < 0
        sign_in = 1.0 if float(ports[in_port].center.y) > 0 else -1.0
        sign_out = 1.0 if float(ports[out_port].center.y) > 0 else -1.0
        sign_arm = 1.0 if arm == 0 else -1.0
        first, last = (sign_in, sign_out) if from_left else (sign_out, sign_in)
        xl, xr = self.left_coupler_center_x, self.right_coupler_center_x
        in_side = [(xl + x, y) for x, y in self._half_rail(first)]
        to_arm = [(xl - x, y) for x, y in reversed(self._half_rail(sign_arm))]
        from_arm = [(xr + x, y) for x, y in self._half_rail(sign_arm)]
        out_side = [(xr - x, y) for x, y in reversed(self._half_rail(last))]
        path = in_side + to_arm + from_arm + out_side
        return path if from_left else path[::-1]

    # --- arm phase shifter --------------------------------------------------------------------------
    def _heater_polygon(self) -> list[tuple[float, float]]:
        return _translate_points(super()._heater_polygon(), self.arm_heater_x, 0.0)

    def _heater_via_centers(self) -> list[tuple[float, float]]:
        return [(x + self.arm_heater_x, y) for x, y in super()._heater_via_centers()]

    # --- ring heaters -------------------------------------------------------------------------------
    @property
    def ring_heater_width(self) -> float:
        gaps = self._ring_gaps()
        return min(self.waveguide_width * 1.4, self.waveguide_width + (min(gaps) if gaps else 0.2))

    @property
    def ring_heater_radius(self) -> float:
        """The heater runs inside the ring, so it never lies over the bus."""

        inner = self.ring_radius - self.waveguide_width / 2.0 - 0.5 * self.waveguide_width - self.ring_heater_width / 2.0
        return max(inner, self.ring_heater_width * 1.5)

    @property
    def _ring_heater_gap_deg(self) -> float:
        """Half angle of the opening where the leads leave: wide enough for two pads side by side."""

        s = min(0.9, 1.3 * self.heater_pad_size / self.ring_heater_radius)
        return math.degrees(math.asin(s))

    def _ring_pad_xy(self) -> tuple[float, float]:
        """Pad centre of the right pad, relative to the ring centre, for a ring that faces north."""

        px = self.ring_heater_radius * math.sin(math.radians(self._ring_heater_gap_deg))
        py = self.ring_radius + self.waveguide_width / 2.0 + 0.5 * self.heater_pad_size + self.heater_pad_size / 2.0
        return px, py

    def _ring_heater_polygon(self, ring: dict[str, Any]) -> list[tuple[float, float]]:
        """One closed outline: a C-shaped strip inside the ring, two leads up through the opening, two pads."""

        g = math.radians(self._ring_heater_gap_deg)
        w2 = self.ring_heater_width / 2.0
        r_in, r_out = self.ring_heater_radius - w2, self.ring_heater_radius + w2
        s = self.heater_pad_size / 2.0
        px, py = self._ring_pad_xy()
        y_j = py - s
        a0, a1 = 90.0 + math.degrees(g), 450.0 - math.degrees(g)
        outer = _arc_points(0.0, 0.0, r_out, a0, a1, segments=72)
        inner = _arc_points(0.0, 0.0, r_in, a1, a0, segments=72)
        y_out, y_in = r_out * math.cos(g), r_in * math.cos(g)
        points = [
            *outer,
            (px + w2, y_out), (px + w2, y_j),                  # right lead, outer edge up
            (px + s, y_j), (px + s, py + s), (px - s, py + s), (px - s, y_j),
            (px - w2, y_j), (px - w2, y_in),                   # right lead, inner edge down
            *inner,
            (-px + w2, y_in), (-px + w2, y_j),                 # left lead, inner edge up
            (-px + s, y_j), (-px + s, py + s), (-px - s, py + s), (-px - s, y_j),
            (-px - w2, y_j), (-px - w2, y_out),                # left lead, outer edge down
        ]
        sign = ring["sign"]
        return [(ring["x"] + x, ring["y"] + sign * y) for x, y in points]

    def _ring_heater_vias(self, ring: dict[str, Any]) -> list[tuple[float, float]]:
        px, py = self._ring_pad_xy()
        return [(ring["x"] - px, ring["y"] + ring["sign"] * py), (ring["x"] + px, ring["y"] + ring["sign"] * py)]

    def _heater_children_2d(self) -> list[dict[str, Any]]:
        if not self.with_heaters:
            return []
        polygons = [self._heater_polygon(), *[self._ring_heater_polygon(r) for r in self.ring_layout()]]
        vias = [*self._heater_via_centers(), *[v for r in self.ring_layout() for v in self._ring_heater_vias(r)]]
        return [
            *[_chip_polygon(p, fill="#d4af37", opacity=self.opacity, stroke="#8e7611", stroke_width=0.08) for p in polygons],
            *[_chip_box(x, y, self.heater_via_size, self.heater_via_size, "#f08c6d", self.opacity, stroke="#8b5038", stroke_width=0.08)
              for x, y in vias],
        ]

    def _heater_children_3d(self) -> list[dict[str, Any]]:
        if not self.with_heaters:
            return []
        stack = self._draw_layer_stack()
        polygons = [self._heater_polygon(), *[self._ring_heater_polygon(r) for r in self.ring_layout()]]
        vias = [*self._heater_via_centers(), *[v for r in self.ring_layout() for v in self._ring_heater_vias(r)]]
        return [
            *[_chip_extruded_polygon(p, stack["metal_height"], color="#d4af37", preset="gold", z_offset=stack["metal_z"]) for p in polygons],
            *_vias(self.heater_via_size, vias, stack),
        ]

    # --- ports and geometry -------------------------------------------------------------------------
    def ports(self) -> dict[str, Port]:
        draw = self._draw_variant()
        if draw is not self:
            return draw.ports()
        x_out = self.arm_span / 2.0 + self.coupler_span
        y = self.arm_gap / 2.0
        w = self.waveguide_width
        ports = {
            "o1": Port("o1", Vec3(-x_out, y, 0), orientation_deg=180, width=w),
            "o2": Port("o2", Vec3(-x_out, -y, 0), orientation_deg=180, width=w),
            "o3": Port("o3", Vec3(x_out, y, 0), orientation_deg=0, width=w),
            "o4": Port("o4", Vec3(x_out, -y, 0), orientation_deg=0, width=w),
        }
        if self.with_heaters:
            for name, x in (("h1", -self.heater_pad_x), ("h2", self.heater_pad_x)):
                ports[name] = Port(name, Vec3(x + self.arm_heater_x, self.heater_pad_y, 0), orientation_deg=90,
                                   width=self.heater_pad_size, kind="electrical")
            px, py = self._ring_pad_xy()
            for ring in self.ring_layout():
                facing = 90 if ring["sign"] > 0 else 270
                for letter, x in (("a", -px), ("b", px)):
                    name = f"rh{ring['k']}{letter}"
                    ports[name] = Port(name, Vec3(ring["x"] + x, ring["y"] + ring["sign"] * py, 0), orientation_deg=facing,
                                       width=self.heater_pad_size, kind="electrical")
        return ports

    def _arm_polygons(self) -> list[list[tuple[float, float]]]:
        half, dy, w = self.arm_span / 2.0, self.arm_gap / 2.0, self.waveguide_width
        return [_segment_outline((-half, sign * dy), (half, sign * dy), w, w) for sign in (1.0, -1.0)]

    def _ring_polygon(self, ring: dict[str, Any]) -> list[tuple[float, float]]:
        w2 = self.waveguide_width / 2.0
        return _arc_band_points(ring["x"], ring["y"], self.ring_radius - w2, self.ring_radius + w2, 0.0, 360.0, segments=96)

    def _silicon_polygons(self) -> list[list[tuple[float, float]]]:
        polygons = []
        for cx in (self.left_coupler_center_x, self.right_coupler_center_x):
            polygons += [_translate_points(p, cx, 0.0) for p in self._coupler_polygons()]
        return polygons + self._arm_polygons()

    def geometry_2d(self) -> dict[str, Any]:
        draw = self._draw_variant()
        if draw is not self:
            return draw.geometry_2d()
        edge, w2 = SILICON_EDGE, self.waveguide_width / 2.0
        children: list[dict[str, Any]] = []
        if self.coupler == "dc":      # the pale box round each directional coupler, as on the MZI
            body_height = max(self.coupler_width, self._directional_coupler().body_height)
            children += [_chip_box(cx, 0.0, self.coupler_span, body_height, self.color, self.opacity * 0.14, stroke=edge, stroke_width=0.05)
                         for cx in (self.left_coupler_center_x, self.right_coupler_center_x)]
        children += [_chip_polygon(p, fill=self.color, opacity=self.opacity, stroke=edge, stroke_width=0.08)
                     for p in self._silicon_polygons()]
        for ring in self.ring_layout():   # a ring's edges are two circles: a stroke round the annulus would show a seam
            children.append(_chip_polygon(self._ring_polygon(ring), fill=self.color, opacity=self.opacity, stroke="none", stroke_width=0.0))
            children += [_chip_circle(ring["x"], ring["y"], self.ring_radius + s * w2, stroke=edge, stroke_width=0.08, fill="none", opacity=self.opacity)
                         for s in (1.0, -1.0)]
        children.extend(self._heater_children_2d())
        return {"type": "group", "children": children}

    def geometry_3d(self) -> dict[str, Any]:
        draw = self._draw_variant()
        if draw is not self:
            return draw.geometry_3d()
        thickness, core = self._draw_thickness(), self._core()
        children = [_chip_extruded_polygon(p, thickness, **core) for p in self._silicon_polygons()]
        children += [_chip_extruded_polygon(self._ring_polygon(r), thickness, **core) for r in self.ring_layout()]
        children.extend(self._heater_children_3d())
        return self._on_the_stack(children)

    def symbol_1d(self) -> tuple[str, dict[str, Any]]:
        params: dict[str, Any] = {"top": self.rings_per_arm[0], "bottom": self.rings_per_arm[1]}
        if self.coupler == "mmi":
            params["splitter"] = "mmi2x2"
        if not self.with_heaters:
            params["bare"] = True
        return "ramzi", params

    def optical_paths(self, in_port: str) -> list[dict[str, Any]]:
        """The two arm paths of the MZI, on the drawn guides, and one loop path for each ring."""

        draw = self._draw_variant()
        if draw is not self:
            draw.anim_params = self.anim_params  # behaviours ride along
            return draw.optical_paths(in_port)
        ports = self.ports()
        if in_port not in ports or ports[in_port].kind == "electrical":
            return []
        going_right = float(ports[in_port].center.x) < 0
        exits = [n for n, p in ports.items() if n != in_port and p.kind != "electrical" and (float(p.center.x) > 0) == going_right]
        target = min(exits, key=lambda n: abs(float(ports[n].center.y) - float(ports[in_port].center.y)))
        paths = []
        for arm in (0, 1):
            pts = [list(p) for p in _densify(self.arm_path(in_port, target, arm))]
            paths.append({"port": target, "power": 0.5, "pts": pts, "powers": [0.5] * len(pts)})
        for ring in self.ring_layout():
            sign = ring["sign"]
            start = -90.0 if sign > 0 else 90.0           # the loop starts where it meets the arm
            step = 360.0 if (sign > 0) == going_right else -360.0
            loop = [list(p) for p in _arc_points(ring["x"], ring["y"], self.ring_radius, start, start + step, segments=72)]
            lead = abs(ring["x"] - (-self.arm_span / 2.0 if going_right else self.arm_span / 2.0))
            paths.append({"port": "", "power": 0.0, "pts": loop, "powers": [0.3] * len(loop), "delay_len": round(lead, 4)})
        return paths

    def physics_metadata(self) -> dict[str, Any]:
        data = super().physics_metadata()
        data.update({"component": "ramzi", "rings_per_arm": list(self.rings_per_arm), "ring_radius": self.ring_radius})
        return data


@dataclass
class MZM(MZI):
    component_type = "MZM"
    schematic_family = "mzm"
    electrode_width: float = 6.0
    electrode_length: float = 30.0
    drive_style: str = "gs"
    mechanism: str = "electro_optic"
    splitter: str = "ybranch"

    open_ports = ("o2", "o4")       # the second input and output of its couplers: spare unless used

    def __init__(
        self,
        center=(0, 0),
        angle=0,
        electrode_width: float | None = None,
        electrode_length: float | None = None,
        drive_style: str = "gs",
        mechanism: str = "electro_optic",
        splitter: str = "ybranch",
        **kwargs,
    ):
        normalized_splitter = str(splitter).lower().replace("-", "").replace("_", "").replace(" ", "")
        if normalized_splitter in {"ybranch", "y", "yjunction", "single", "1x1"}:
            self.splitter = "ybranch"
        elif normalized_splitter in {"coupler", "dc", "directionalcoupler", "2x2", "dualinput", "twoinput"}:
            self.splitter = "coupler"
        elif normalized_splitter in {"branchcoupler", "1x22x2", "ybranchcoupler", "branchtocoupler", "balanced", "differential", "1in2out"}:
            self.splitter = "branch_coupler"
        else:
            raise ValueError("splitter must be 'ybranch', 'coupler', or 'branch_coupler'")
        heater = _generic_pdk_defaults()["heater"]
        self.electrode_width = float(heater["electrode_width"] if electrode_width is None else electrode_width)
        self.electrode_length = float(0.75 * kwargs.get("arm_length", 40.0) if electrode_length is None else electrode_length)
        normalized_drive_style = drive_style.lower().replace("-", "").replace("_", "")
        if normalized_drive_style in {"gs", "single", "singlearm", "onearm"}:
            self.drive_style = "gs"
        elif normalized_drive_style in {"gsg", "dual", "dualarm", "botharms"}:
            self.drive_style = "gsg"
        else:
            raise ValueError("drive_style must be 'gs' or 'gsg'")
        normalized_mechanism = mechanism.lower().replace("-", "").replace("_", "").replace(" ", "")
        if normalized_mechanism in {"electrooptic", "eo", "pn", "rf", "depletion", "carrier"}:
            self.mechanism = "electro_optic"
        elif normalized_mechanism in {"thermooptic", "to", "heater", "thermal", "thermo"}:
            self.mechanism = "thermo_optic"
        else:
            raise ValueError("mechanism must be 'electro_optic' or 'thermo_optic'")
        super().__init__(center=center, angle=angle, **kwargs)

    def physical_spec(self) -> PhysicalSpec:
        values = dict(super().physical_spec().values)
        values.update(
            {
                "electrode_width": self.electrode_width,
                "electrode_length": self.electrode_length,
                "drive_style_gsg": self.drive_style == "gsg",
                "thermo_optic": self.mechanism == "thermo_optic",
                "coupler_io": self.splitter == "coupler",
            }
        )
        return PhysicalSpec(device_family=self.schematic_family, values=values)

    def _draw_variant(self) -> MZM:
        if self.render_physical:
            return self
        return MZM(
            coupler_length=self._draw("coupler_length", self.coupler_length),
            coupler_width=self._draw("coupler_width", self.coupler_width),
            arm_length=self._draw("arm_length", self.arm_length),
            arm_gap=self._draw("arm_gap", self.arm_gap),
            waveguide_width=self._draw("waveguide_width", self.waveguide_width),
            taper_length=self._draw("taper_length", self.taper_length),
            waveguide_gap=self._draw("waveguide_gap", self.waveguide_gap),
            electrode_width=self._draw("metal_width", self.electrode_width),
            electrode_length=self._draw("electrode_length", self.electrode_length),
            drive_style=self.drive_style,
            mechanism=self.mechanism,
            splitter=self.splitter,
            **self._draw_variant_kwargs(),
        )

    def anim_behaviors(self) -> list[dict]:
        return [
            {"key": "bias", "label": "Bias point", "options": [
                ["auto", "Quadrature (half)"], ["peak", "Peak (full transmission)"],
                ["null", "Null (destructive)"]]},
            {"key": "junction", "label": "PN junctions", "options": [
                ["auto", "PN depletion drive"], ["pin", "PIN injection"], ["off", "Off"]]},
            {"key": "heater", "label": "Bias heater", "options": [
                ["auto", "On"], ["off", "Off"]]},
        ]


    def _io_children_2d(self) -> list[dict[str, Any]]:
        """Splitter + combiner art: Y-branches (1 input) or directional couplers (2)."""
        if self.splitter == "ybranch":
            return [
                *[_chip_polygon(p, fill=self.color, opacity=self.opacity, stroke=SILICON_EDGE, stroke_width=0.08) for p in self._ybranch_polygons(self.left_splitter_center_x)],
                *[_chip_polygon(p, fill=self.color, opacity=self.opacity, stroke=SILICON_EDGE, stroke_width=0.08) for p in self._ybranch_polygons(self.right_combiner_center_x, mirror=True)],
            ]
        elif self.splitter == "branch_coupler":
            dc = self._directional_coupler()
            out = [
                *[_chip_polygon(p, fill=self.color, opacity=self.opacity, stroke=SILICON_EDGE, stroke_width=0.08) for p in self._ybranch_polygons(self.left_splitter_center_x)],
            ]
            for sign in (1.0, -1.0):
                out.append(_chip_polygon(_translate_points(dc._polygon(sign), self.right_coupler_center_x, 0.0), fill=self.color, opacity=self.opacity, stroke=SILICON_EDGE, stroke_width=0.08))
            return out
        dc = self._directional_coupler()
        out: list[dict[str, Any]] = []
        for cx in (self.left_coupler_center_x, self.right_coupler_center_x):
            for sign in (1.0, -1.0):
                out.append(_chip_polygon(_translate_points(dc._polygon(sign), cx, 0.0), fill=self.color, opacity=self.opacity, stroke=SILICON_EDGE, stroke_width=0.08))
        return out

    def _io_children_3d(self) -> list[dict[str, Any]]:
        if self.splitter == "ybranch":
            return [
                *[_chip_extruded_polygon(p, self._draw_thickness(), **self._core()) for p in self._ybranch_polygons(self.left_splitter_center_x)],
                *[_chip_extruded_polygon(p, self._draw_thickness(), **self._core()) for p in self._ybranch_polygons(self.right_combiner_center_x, mirror=True)],
            ]
        elif self.splitter == "branch_coupler":
            dc = self._directional_coupler()
            out = [
                *[_chip_extruded_polygon(p, self._draw_thickness(), **self._core()) for p in self._ybranch_polygons(self.left_splitter_center_x)],
            ]
            for sign in (1.0, -1.0):
                out.append(_chip_extruded_polygon(_translate_points(dc._polygon(sign), self.right_coupler_center_x, 0.0), self._draw_thickness(), **self._core()))
            return out
        dc = self._directional_coupler()
        out: list[dict[str, Any]] = []
        for cx in (self.left_coupler_center_x, self.right_coupler_center_x):
            for sign in (1.0, -1.0):
                out.append(_chip_extruded_polygon(_translate_points(dc._polygon(sign), cx, 0.0), self._draw_thickness(), **self._core()))
        return out

    def _splitter(self) -> YBranch:
        minimum_branch = max(self.waveguide_width * 9.0, 4.5)
        if self.coupler_length <= minimum_branch:
            stem_length = max(self.coupler_length * 0.45, 0.5)
            branch_length = max(self.coupler_length - stem_length, 0.5)
        else:
            stem_length = min(max(self.taper_length, 1.0), self.coupler_length - minimum_branch)
            branch_length = self.coupler_length - stem_length
        return YBranch(
            branch_length=branch_length,
            stem_length=stem_length,
            waveguide_width=self.waveguide_width,
            branch_gap=self.arm_gap,
            color=self.color,
            opacity=self.opacity,
            chip_thickness=self.chip_thickness,
            material_preset=self._draw_material_preset(),
        )

    @property
    def left_splitter_center_x(self) -> float:
        return -(self.arm_length / 2.0 + self.coupler_length / 2.0)

    @property
    def right_combiner_center_x(self) -> float:
        return self.arm_length / 2.0 + self.coupler_length / 2.0

    def _ybranch_polygons(self, center_x: float, *, mirror: bool = False) -> list[list[tuple[float, float]]]:
        splitter = self._splitter()
        polygons = [
            _segment_outline((splitter.input_x, 0.0), (splitter.junction_start_x, 0.0), self.waveguide_width, splitter.segment_widths[0]),
            splitter._junction_polygon(),
            splitter._branch_polygon(1.0),
            splitter._branch_polygon(-1.0),
        ]
        if mirror:
            polygons = [_mirror_points_x(points) for points in polygons]
        return [_translate_points(points, center_x, 0.0) for points in polygons]

    def _active_metrics(self) -> dict[str, float]:
        pin_length = min(self.electrode_length, max(self.arm_length - 2.0 * max(self.taper_length, 1.0), self.waveguide_width * 12.0))
        pin_length = min(pin_length, self.arm_length)
        phase_taper = min(max((self.arm_length - pin_length) / 2.0, 1.25), max(self.taper_length, 1.25))
        slab_width = max(self.waveguide_width * 4.8, min(self.arm_gap * 0.32, max(self.coupler_width * 0.42, 2.0)))
        # Prominent lateral PN junction: p fills the upper half of the rib, n the lower
        # half, meeting at the arm waveguide (matches the ring/racetrack modulators).
        stripe_width = max(slab_width * 0.34, self.waveguide_width * 1.1)
        stripe_offset = max(slab_width * 0.26, self.waveguide_width * 0.95)
        if self.drive_style == "gs":
            stripe_top_width = stripe_width
            stripe_bottom_width = stripe_width * 0.9
            stripe_top_offset = stripe_offset
            stripe_bottom_offset = stripe_offset
        else:
            stripe_top_width = stripe_width
            stripe_bottom_width = stripe_width
            stripe_top_offset = stripe_offset
            stripe_bottom_offset = stripe_offset
        rail_width = max(self.electrode_width * 0.2, 0.62)
        signal_rail_width = rail_width * (1.12 if self.drive_style == "gsg" else 1.0)
        metal_clearance = max(1.0, self.waveguide_width * 2.0)
        outer_rail_offset = slab_width / 2.0 + metal_clearance + rail_width / 2.0
        bridge_width = max(rail_width * 0.84, 0.42)
        slab_bridge_width = max(bridge_width * 1.85, self.waveguide_width * 1.5)
        via_size = min(bridge_width, stripe_top_width * 0.6, stripe_bottom_width * 0.6)
        via_dx = pin_length * 0.42
        half_contact = pin_length * 0.46
        return {
            "pin_length": pin_length,
            "phase_taper": phase_taper,
            "slab_width": slab_width,
            "stripe_top_width": stripe_top_width,
            "stripe_bottom_width": stripe_bottom_width,
            "stripe_top_offset": stripe_top_offset,
            "stripe_bottom_offset": stripe_bottom_offset,
            "rail_width": rail_width,
            "signal_rail_width": signal_rail_width,
            "outer_rail_offset": outer_rail_offset,
            "bridge_width": bridge_width,
            "slab_bridge_width": slab_bridge_width,
            "via_size": via_size,
            "via_dx": via_dx,
            "half_contact": half_contact,
        }

    def _metal_slab_polygons(self, metrics: dict[str, float]) -> list[list[tuple[float, float]]]:
        upper_y = self.arm_gap / 2.0
        lower_y = -upper_y
        polygons: list[list[tuple[float, float]]] = []
        if self.drive_style == "gs":
            signal_y = upper_y + metrics["outer_rail_offset"]
            ground_y = upper_y - metrics["outer_rail_offset"]
            polygons.extend(
                [
                    _segment_outline((-metrics["half_contact"], signal_y), (metrics["half_contact"], signal_y), metrics["slab_bridge_width"], metrics["slab_bridge_width"]),
                    _segment_outline((-metrics["half_contact"], ground_y), (metrics["half_contact"], ground_y), metrics["slab_bridge_width"], metrics["slab_bridge_width"]),
                ]
            )
            for x in (-metrics["via_dx"], metrics["via_dx"]):
                polygons.extend(
                    [
                        _segment_outline((x, upper_y + metrics["stripe_top_offset"]), (x, signal_y), metrics["slab_bridge_width"], metrics["slab_bridge_width"]),
                        _segment_outline((x, upper_y - metrics["stripe_bottom_offset"]), (x, ground_y), metrics["slab_bridge_width"], metrics["slab_bridge_width"]),
                    ]
                )
            return polygons

        top_ground_y = upper_y + metrics["outer_rail_offset"]
        signal_y = 0.0
        bottom_ground_y = lower_y - metrics["outer_rail_offset"]
        polygons.extend(
            [
                _segment_outline((-metrics["half_contact"], top_ground_y), (metrics["half_contact"], top_ground_y), metrics["slab_bridge_width"], metrics["slab_bridge_width"]),
                _segment_outline((-metrics["half_contact"], signal_y), (metrics["half_contact"], signal_y), metrics["slab_bridge_width"], metrics["slab_bridge_width"]),
                _segment_outline((-metrics["half_contact"], bottom_ground_y), (metrics["half_contact"], bottom_ground_y), metrics["slab_bridge_width"], metrics["slab_bridge_width"]),
            ]
        )
        for x in (-metrics["via_dx"], metrics["via_dx"]):
            polygons.extend(
                [
                    _segment_outline((x, upper_y + metrics["stripe_top_offset"]), (x, top_ground_y), metrics["slab_bridge_width"], metrics["slab_bridge_width"]),
                    _segment_outline((x, upper_y - metrics["stripe_bottom_offset"]), (x, signal_y), metrics["slab_bridge_width"], metrics["slab_bridge_width"]),
                    _segment_outline((x, lower_y + metrics["stripe_top_offset"]), (x, signal_y), metrics["slab_bridge_width"], metrics["slab_bridge_width"]),
                    _segment_outline((x, lower_y - metrics["stripe_bottom_offset"]), (x, bottom_ground_y), metrics["slab_bridge_width"], metrics["slab_bridge_width"]),
                ]
            )
        return polygons

    def _metal_slab_children_2d(self, metrics: dict[str, float]) -> list[dict[str, Any]]:
        return [
            _chip_polygon(points, fill="#9bc5dd", opacity=self.opacity * 0.7, stroke="#6f9ab5", stroke_width=0.08)
            for points in self._metal_slab_polygons(metrics)
        ]

    def _metal_slab_children_3d(self, metrics: dict[str, float], stack: dict[str, float]) -> list[dict[str, Any]]:
        return [
            _chip_extruded_polygon(points, stack["rib_height"], **self._slab("#9bc5dd"))
            for points in self._metal_slab_polygons(metrics)
        ]

    def _active_arm_centers(self) -> list[float]:
        upper_y = self.arm_gap / 2.0
        return [upper_y] if self.drive_style == "gs" else [upper_y, -upper_y]

    def _active_arm_children_2d(self, arm_y: float, metrics: dict[str, float]) -> list[dict[str, Any]]:
        rib_left = -metrics["pin_length"] / 2.0
        rib_right = metrics["pin_length"] / 2.0
        return [
            _chip_segment_polygon((rib_left - metrics["phase_taper"], arm_y), (rib_left, arm_y), self.waveguide_width, metrics["slab_width"], fill="#4f94c6", opacity=self.opacity * 0.84, stroke="#2c5d85", stroke_width=0.08),
            _chip_box(0.0, arm_y, metrics["pin_length"], metrics["slab_width"], "#4f94c6", self.opacity * 0.84, stroke="#2c5d85", stroke_width=0.08),
            _chip_segment_polygon((rib_right, arm_y), (rib_right + metrics["phase_taper"], arm_y), metrics["slab_width"], self.waveguide_width, fill="#4f94c6", opacity=self.opacity * 0.84, stroke="#2c5d85", stroke_width=0.08),
            _chip_box(0.0, arm_y + metrics["stripe_top_offset"], metrics["pin_length"] * 0.94, metrics["stripe_top_width"], "#c76d6d", self.opacity * 0.92, stroke="#864646", stroke_width=0.08),
            _chip_box(0.0, arm_y - metrics["stripe_bottom_offset"], metrics["pin_length"] * 0.94, metrics["stripe_bottom_width"], "#6d8fc7", self.opacity * 0.92, stroke="#3f5f96", stroke_width=0.08),
        ]

    def _active_arm_children_3d(self, arm_y: float, metrics: dict[str, float], stack: dict[str, float]) -> list[dict[str, Any]]:
        rib_left = -metrics["pin_length"] / 2.0
        rib_right = metrics["pin_length"] / 2.0
        # Partition the residual slab instead of overlaying coloured boxes on silicon.
        half_length = metrics["pin_length"] / 2.0
        half_width = metrics["slab_width"] / 2.0
        implant_end = half_length * 0.94
        bands = [(0.0, half_width, "#c76d6d"), (-half_width, 0.0, "#6d8fc7")]
        bands = [(max(-half_width, lo), min(half_width, hi), color) for lo, hi, color in bands]
        cuts = sorted({-half_width, half_width, *(v for lo, hi, _ in bands for v in (lo, hi)
                                               if -half_width < v < half_width)})
        slab = []
        for lo, hi in zip(cuts, cuts[1:]):
            middle = (lo + hi) / 2
            color = next((color for low, high, color in bands if low <= middle <= high), self.color)
            slab.append(_chip_slab(2 * implant_end, hi - lo, stack["rib_height"],
                                  y=arm_y + middle, color=color, preset="silicon", z_offset=stack["rib_z"]))
        for side in (-1, 1):
            slab.append(_chip_slab(half_length - implant_end, 2 * half_width, stack["rib_height"],
                                  x=side * (half_length + implant_end) / 2, y=arm_y,
                                  **self._slab(self.color)))
        return [
            *slab,
            _chip_segment_slab((rib_left - metrics["phase_taper"], arm_y), (rib_left, arm_y), self.waveguide_width, metrics["slab_width"], stack["rib_height"], **self._slab(self.color)),
            _chip_segment_slab((rib_right, arm_y), (rib_right + metrics["phase_taper"], arm_y), metrics["slab_width"], self.waveguide_width, stack["rib_height"], **self._slab(self.color)),
        ]

    def _rail_polygon(
        self,
        y0: float,
        half_width: float,
        half_length: float,
        *,
        down: list[tuple[float, float]],
        up: list[tuple[float, float]],
        stub_half: float,
        feed: tuple[float, float, float],
    ) -> list[tuple[float, float]]:
        """One RF terminal — rail + its via bridges + feed + probe pad — traced as
        ONE closed outline (the same "a conductor is a single part" rule the ring
        and MZI heaters follow). ``down``/``up`` are (x, y_end) bridge targets."""

        x_left, x_right = -half_length, half_length
        points: list[tuple[float, float]] = [(x_left, y0 + half_width)]
        for x, y_end in sorted(up):  # bridges hanging off the top edge
            points += [(x - stub_half, y0 + half_width), (x - stub_half, y_end),
                       (x + stub_half, y_end), (x + stub_half, y0 + half_width)]
        points += [(x_right, y0 + half_width), (x_right, y0 - half_width)]
        for x, y_end in sorted(down, reverse=True):  # ... and off the bottom edge
            points += [(x + stub_half, y0 - half_width), (x + stub_half, y_end),
                       (x - stub_half, y_end), (x - stub_half, y0 - half_width)]
        points.append((x_left, y0 - half_width))
        pad_x, pad_half, feed_half = feed
        points += [(x_left, y0 - feed_half), (pad_x + pad_half, y0 - feed_half),
                   (pad_x + pad_half, y0 - pad_half), (pad_x - pad_half, y0 - pad_half),
                   (pad_x - pad_half, y0 + pad_half), (pad_x + pad_half, y0 + pad_half),
                   (pad_x + pad_half, y0 + feed_half), (x_left, y0 + feed_half)]
        return points

    def _electrode_polygons(self, metrics: dict[str, float]) -> list[list[tuple[float, float]]]:
        """One gold outline per RF terminal — GS = signal + ground, GSG = G-S-G.
        Terminals stay SEPARATE polygons: they are different nets, and merging
        them would draw a shorted modulator."""

        upper_y = self.arm_gap / 2.0
        lower_y = -upper_y
        p_upper = upper_y + metrics["stripe_top_offset"] - metrics["via_size"] / 2
        n_upper = upper_y - metrics["stripe_bottom_offset"] + metrics["via_size"] / 2
        p_lower = lower_y + metrics["stripe_top_offset"] - metrics["via_size"] / 2
        n_lower = lower_y - metrics["stripe_bottom_offset"] + metrics["via_size"] / 2
        xs = (-metrics["via_dx"], metrics["via_dx"])
        pad_half = self._probe_pad_size() / 2.0
        stub_half = metrics["bridge_width"] / 2.0
        # (down bridges, up bridges) per terminal, in _probe_terminals order
        if self.drive_style == "gs":
            wiring = [([(x, p_upper) for x in xs], []), ([], [(x, n_upper) for x in xs])]
        else:
            wiring = [
                ([(x, p_upper) for x in xs], []),
                ([(x, p_lower) for x in xs], [(x, n_upper) for x in xs]),
                ([], [(x, n_lower) for x in xs]),
            ]
        polygons = []
        for (name, pad_x, y0), (down, up) in zip(self._probe_terminals(metrics), wiring):
            rail_width = metrics["signal_rail_width"] if name == "sig" else metrics["rail_width"]
            half_length = metrics["pin_length"] * (0.48 if name == "sig" else 0.47)
            feed_half = min(metrics["rail_width"] * 0.75, pad_half * 0.8)
            polygons.append(self._rail_polygon(
                y0, rail_width / 2.0, half_length, down=down, up=up,
                stub_half=stub_half, feed=(pad_x, pad_half, feed_half),
            ))
        return polygons

    def _electrode_via_centers(self, metrics: dict[str, float]) -> list[tuple[float, float]]:
        return [(x, y) for arm_y in self._active_arm_centers()
                for y in (arm_y + metrics["stripe_top_offset"], arm_y - metrics["stripe_bottom_offset"])
                for x in (-metrics["via_dx"], metrics["via_dx"])]

    def _metal_children_2d(self, metrics: dict[str, float]) -> list[dict[str, Any]]:
        return [
            *[
                _chip_polygon(points, fill="#d4af37", opacity=self.opacity, stroke="#8e7611", stroke_width=0.08)
                for points in self._electrode_polygons(metrics)
            ],
            *[
                _chip_box(x, y, metrics["via_size"], metrics["via_size"], "#f08c6d", self.opacity, stroke="#8b5038", stroke_width=0.08)
                for x, y in self._electrode_via_centers(metrics)
            ],
        ]

    def _metal_children_3d(self, metrics: dict[str, float], stack: dict[str, float]) -> list[dict[str, Any]]:
        # Small internal overlap removes a coplanar seam without moving the metal surface.
        landing_overlap = min(stack["metal_height"] * 0.02, 0.005)
        if stack["metal_z"] - stack["via_z"] + landing_overlap <= 0:
            raise ValueError("MZM via must start below its routing metal")
        return [
            *[
                _chip_slab(metrics["via_size"], metrics["via_size"], stack["contact_height"],
                           x=x, y=y, color="#777b82", preset="tungsten", z_offset=stack["contact_z"])
                for x, y in self._electrode_via_centers(metrics)
            ],
            *[
                _chip_extruded_polygon(points, stack["metal_height"], color="#d4af37", preset="gold", z_offset=stack["metal_z"])
                for points in self._electrode_polygons(metrics)
            ],
            *_vias(metrics["via_size"], self._electrode_via_centers(metrics), stack, into=landing_overlap),
        ]

    def _probe_pad_size(self) -> float:
        return max(self.waveguide_width * 3.0, min(self.electrode_width * 0.7, self.arm_gap * 0.7), 1.8)

    def _probe_terminals(self, metrics: dict[str, float]) -> list[tuple[str, float, float]]:
        """Reduced RF probe pads — one per terminal: GS = signal+ground, GSG = G-S-G.

        Laid out as a clean probe-landing column just off the left edge of the
        electrodes, so the electrical ports never sit on the modulator bars (which
        is what made the old e1..e6 read as random connectable points)."""

        upper_y = self.arm_gap / 2.0
        lower_y = -upper_y
        pad_x = -metrics["half_contact"] - self._probe_pad_size() * 0.85
        if self.drive_style == "gs":
            return [
                ("sig", pad_x, upper_y + metrics["outer_rail_offset"]),
                ("gnd", pad_x, upper_y - metrics["outer_rail_offset"]),
            ]
        return [
            ("gnd1", pad_x, upper_y + metrics["outer_rail_offset"]),
            ("sig", pad_x, 0.0),
            ("gnd2", pad_x, lower_y - metrics["outer_rail_offset"]),
        ]

    def ports(self) -> dict[str, Port]:
        draw = self._draw_variant()
        if draw is not self:
            return draw.ports()
        if self.splitter == "branch_coupler":
            splitter = self._splitter()
            cp = self._directional_coupler().ports()
            ports = {
                "o1": Port("o1", Vec3(self.left_splitter_center_x + splitter.input_x, 0, 0), orientation_deg=180, width=self.waveguide_width),
                "o3": Port("o3", Vec3(self.right_coupler_center_x + cp["o3"].center.x, cp["o3"].center.y, 0), orientation_deg=0, width=self.waveguide_width),
                "o4": Port("o4", Vec3(self.right_coupler_center_x + cp["o4"].center.x, cp["o4"].center.y, 0), orientation_deg=0, width=self.waveguide_width),
            }
        elif self.splitter == "coupler":
            # two-input variant: a 2×2 directional coupler at each end (o1/o2 in, o3/o4 out)
            cp = self._directional_coupler().ports()
            ports = {
                "o1": Port("o1", Vec3(self.left_coupler_center_x + cp["o1"].center.x, cp["o1"].center.y, 0), orientation_deg=180, width=self.waveguide_width),
                "o2": Port("o2", Vec3(self.left_coupler_center_x + cp["o2"].center.x, cp["o2"].center.y, 0), orientation_deg=180, width=self.waveguide_width),
                "o3": Port("o3", Vec3(self.right_coupler_center_x + cp["o3"].center.x, cp["o3"].center.y, 0), orientation_deg=0, width=self.waveguide_width),
                "o4": Port("o4", Vec3(self.right_coupler_center_x + cp["o4"].center.x, cp["o4"].center.y, 0), orientation_deg=0, width=self.waveguide_width),
            }
        else:
            splitter = self._splitter()
            ports = {
                "o1": Port("o1", Vec3(self.left_splitter_center_x + splitter.input_x, 0.0, 0), orientation_deg=180, width=self.waveguide_width),
                "o2": Port("o2", Vec3(0.0, self.arm_gap / 2.0, 0), orientation_deg=90, width=self.waveguide_width),
                "o3": Port("o3", Vec3(self.right_combiner_center_x - splitter.input_x, 0.0, 0), orientation_deg=0, width=self.waveguide_width),
                "o4": Port("o4", Vec3(0.0, -self.arm_gap / 2.0, 0), orientation_deg=270, width=self.waveguide_width),
            }
        if self.mechanism == "thermo_optic":
            # thermo-optic phase shift uses a heater + 2 pads, exactly like the MZI
            ports.update(
                {
                    "h1": Port("h1", Vec3(-self.heater_pad_x, self.heater_pad_y, 0), orientation_deg=90, width=self.heater_pad_size, kind="electrical"),
                    "h2": Port("h2", Vec3(self.heater_pad_x, self.heater_pad_y, 0), orientation_deg=90, width=self.heater_pad_size, kind="electrical"),
                }
            )
            return ports
        metrics = self._active_metrics()
        for name, x, y in self._probe_terminals(metrics):
            ports[name] = Port(name, Vec3(x, y, 0), orientation_deg=180, width=self._probe_pad_size(), kind="electrical")
        return ports

    def symbol_1d(self) -> tuple[str, dict[str, Any]]:
        drive = "heater" if self.mechanism == "thermo_optic" else self.drive_style
        params: dict[str, Any] = {"length": 2, "drive": drive}
        if self.splitter != "ybranch":
            params["splitter"] = self.splitter
        return "mzi", params

    def geometry_2d(self) -> dict[str, Any]:
        draw = self._draw_variant()
        if draw is not self:
            return draw.geometry_2d()

        upper_y = self.arm_gap / 2.0
        lower_y = -upper_y

        top_arm = _chip_polygon(_segment_outline((-self.arm_length / 2.0, upper_y), (self.arm_length / 2.0, upper_y), self.waveguide_width, self.waveguide_width), fill=self.color, opacity=self.opacity, stroke=SILICON_EDGE, stroke_width=0.08)
        bottom_arm = _chip_polygon(_segment_outline((-self.arm_length / 2.0, lower_y), (self.arm_length / 2.0, lower_y), self.waveguide_width, self.waveguide_width), fill=self.color, opacity=self.opacity, stroke=SILICON_EDGE, stroke_width=0.08)

        children = [
            *self._io_children_2d(),
            top_arm,
            bottom_arm,
        ]
        if self.mechanism == "thermo_optic":
            children.extend(self._heater_children_2d())
            return {"type": "group", "children": children}
        metrics = self._active_metrics()
        for arm_y in self._active_arm_centers():
            children.extend(self._active_arm_children_2d(arm_y, metrics))
        children.extend(self._metal_slab_children_2d(metrics))
        children.extend(self._metal_children_2d(metrics))
        return {"type": "group", "children": children}

    def geometry_3d(self) -> dict[str, Any]:
        draw = self._draw_variant()
        if draw is not self:
            return draw.geometry_3d()

        upper_y = self.arm_gap / 2.0
        lower_y = -upper_y

        children = [*self._io_children_3d()]
        for arm_y in (upper_y, lower_y):
            if self.mechanism == "thermo_optic" or arm_y not in self._active_arm_centers():
                children.append(_chip_slab(self.arm_length, self.waveguide_width, self._draw_thickness(),
                                          y=arm_y, **self._core()))
                continue
            active_length = self._active_metrics()["pin_length"] * 0.94
            for direction, color in ((1, "#c76d6d"), (-1, "#6d8fc7")):
                children.append(_chip_slab(active_length, self.waveguide_width / 2, self._draw_thickness(),
                                          y=arm_y + direction * self.waveguide_width / 4,
                                          color=color, preset="silicon"))
            end_length = (self.arm_length - active_length) / 2
            if end_length > 0:
                for direction in (-1, 1):
                    children.append(_chip_slab(end_length, self.waveguide_width, self._draw_thickness(),
                                              x=direction * (self.arm_length + active_length) / 4,
                                              y=arm_y, **self._core()))
        if self.mechanism == "thermo_optic":
            children.extend(self._heater_children_3d())
            return self._on_the_stack(children)
        metrics = self._active_metrics()
        stack = self._draw_layer_stack()
        for arm_y in self._active_arm_centers():
            children.extend(self._active_arm_children_3d(arm_y, metrics, stack))
        # Only upper metal routes to the contacts; no silicon rail copies below it.
        children.extend(self._metal_children_3d(metrics, stack))
        return self._on_the_stack(children)

    def optical_paths(self, in_port: str) -> list[dict[str, Any]]:
        """Animation paths on the geometry the MZM actually DRAWS.

        With Y-branch I/O: input stub -> the splitter's drawn stem + raised-cosine
        branch centerlines (shifted to the splitter centre) -> straight arms ->
        the mirrored combiner -> exit. With directional-coupler I/O the MZI
        composition applies unchanged (that IS what gets drawn)."""

        if self.splitter == "coupler":
            return super().optical_paths(in_port)
        draw = self._draw_variant()
        if draw is not self:
            draw.anim_params = self.anim_params  # behaviours ride along
            return draw.optical_paths(in_port)
        if self.splitter == "branch_coupler":
            return self._branch_coupler_paths(in_port)
        if in_port not in ("o1", "o3"):
            return []  # o2/o4 are mid-device monitor ports, not through-ports
        target = "o3" if in_port == "o1" else "o1"
        params = getattr(self, "anim_params", None) or {}
        bias = {"peak": 1.0, "null": 0.05, "quad": 0.5}.get(str(params.get("bias", "auto")), 0.5)
        heater_on = str(params.get("heater", "on")) != "off"
        paths = []
        for sign in (1.0, -1.0):
            # canonical o1 -> o3 traversal on the drawn Y-branch geometry
            left_half = self._y_branch_half(sign)
            # combiner = the mirrored splitter (drawn with mirror=True): reflect x
            right_half = [[-x, y] for x, y in left_half][::-1]
            pts = left_half + right_half
            if in_port == "o3":
                pts = pts[::-1]  # traverse o3 -> o1
            # the interference OUTPUT is always the exit end of the travel:
            # arms carry half each until the combiner, then bias x input leaves
            k = max(int(len(pts) * 0.8), 1)
            powers = [0.5] * k + [0.5 * bias] * (len(pts) - k)
            path = {"port": target, "power": 0.5 * bias, "pts": pts, "powers": powers}
            if sign > 0 and heater_on and str(getattr(self, "mechanism", "")) == "thermo_optic":
                path["mod"] = {"sign": -1, "depth": 0.9, "tau_s": 1.4}  # only if a heater is drawn
            paths.append(path)
        return paths

    def _y_branch_half(self, sign: float) -> list[list[float]]:
        """From o1 through the drawn input Y-branch onto the upper (sign 1) or lower (sign -1) arm."""

        splitter = self._splitter()                       # the splitter ``_ybranch_polygons`` draws
        lx = self.left_splitter_center_x
        o1 = self.ports()["o1"]
        stem = [
            [float(o1.center.x), float(o1.center.y)],
            [lx + splitter.input_x, 0.0],
            [lx + splitter.junction_start_x, 0.0],
            [lx + splitter.junction_end_x, 0.0],
        ]
        return stem + [[lx + x, y] for x, y in splitter._output_centerline(sign)]

    def _branch_coupler_paths(self, in_port: str) -> list[dict[str, Any]]:
        """Y-branch in, coupler out: the MZI composition's coupler half of each path, with the
        drawn Y-branch half of the same arm in place of the input coupler it would draw."""

        if in_port not in ("o1", "o3", "o4"):
            return []
        paths = []
        for path in MZI.optical_paths(self, "o3" if in_port == "o1" else in_port):
            pts = path["pts"][::-1] if in_port == "o1" else path["pts"]
            arm_y = min(pts, key=lambda q: abs(q[0]))[1]
            half = self._y_branch_half(1.0 if arm_y >= 0 else -1.0)
            right = [q for q in pts if q[0] >= 0.0]
            pts = half + right if in_port == "o1" else right + half[::-1]
            k = max(int(len(pts) * 0.8), 1)
            paths.append(dict(path, port="o3" if in_port == "o1" else "o1", pts=pts,
                              powers=[0.5] * k + [path["power"]] * (len(pts) - k)))
        return paths

    def physics_metadata(self) -> dict[str, Any]:
        return {
            "domain": "on_chip",
            "component": "mzm",
            "mechanism": self.mechanism,
            "arm_length": self.arm_length,
            "arm_gap": self.arm_gap,
            "drive_style": self.drive_style,
            "phase_bias_upper_arm": 0.0,
            "phase_bias_lower_arm": 0.0,
            "VpiL": None,
            "Vpi": None,
            "electrode_length": self.electrode_length,
            "waveguide_width": self.waveguide_width,
        }


_EAM_GOLD = "#d4af37"
_EAM_GOLD_DARK = "#8e7611"


@dataclass
class ElectroAbsorptionModulator(ChipComponent):
    """Electro-absorption modulator (EAM) — a short reverse-biased active waveguide
    (e.g. Ge-on-Si / QW) whose absorption is switched by an applied field. Compact and
    high-speed, with two electrical contacts."""

    component_type = "ElectroAbsorptionModulator"
    schematic_family = "eam"
    length: float = 40.0
    active_length: float = 18.0
    waveguide_width: float = 0.5
    pad_size: float = 12.0

    def __init__(self, center=(0, 0), angle=0, length=40.0, active_length=18.0, waveguide_width: float | None = None, pad_size=12.0, **kwargs):
        strip = _generic_pdk_defaults()["strip"]
        self.length = float(length)
        self.active_length = float(active_length)
        self.waveguide_width = float(strip["width"] if waveguide_width is None else waveguide_width)
        self.pad_size = float(pad_size)
        self._init_chip(center=center, angle=angle, **kwargs)

    @property
    def _active_height(self) -> float:
        return self.waveguide_width * 2.4

    def anim_behaviors(self) -> list[dict]:
        return [{"key": "junction", "label": "PIN drive", "options": [
            ["auto", "PIN injection (absorption)"], ["off", "Off"]]}]

    @property
    def _region_height(self) -> float:
        return max(self._active_height * 3.0, 4.0)       # the drawn doped region: room for p+, Ge, n+

    @property
    def _pad_y(self) -> float:
        return self._region_height / 2.0 + self.pad_size * 0.5 + 1.5

    def physical_spec(self) -> PhysicalSpec:
        return PhysicalSpec(
            device_family=self.schematic_family,
            values={"length": self.length, "active_length": self.active_length, "waveguide_width": self.waveguide_width, "thickness": self.chip_thickness},
        )

    def ports(self) -> dict[str, Port]:
        half = self.length / 2.0
        return {
            "o1": Port("o1", Vec3(-half, 0, 0), orientation_deg=180, width=self._draw("waveguide_width", self.waveguide_width)),
            "o2": Port("o2", Vec3(half, 0, 0), orientation_deg=0, width=self._draw("waveguide_width", self.waveguide_width)),
            "e1": Port("e1", Vec3(0, self._pad_y, 0), orientation_deg=90, width=self.pad_size, kind="electrical"),
            "e2": Port("e2", Vec3(0, -self._pad_y, 0), orientation_deg=270, width=self.pad_size, kind="electrical"),
        }

    def _lead(self, sign: float) -> list[tuple[float, float]]:
        return _segment_outline((0.0, sign * self._active_height / 2.0), (0.0, sign * (self._pad_y - self.pad_size / 2.0)), self.waveguide_width * 1.6, self.waveguide_width * 1.6)

    def geometry_2d(self) -> dict[str, Any]:
        """A Ge stripe in a doped silicon region (lateral PIN), fed by silicon tapers from both sides."""

        half, active, h, py = self.length / 2.0, self.active_length, self._region_height, self._pad_y
        w = self._draw("waveguide_width", self.waveguide_width)
        taper = (half - active / 2.0) * 0.6
        children = [
            _chip_box(0.0, 0.0, self.length, w, self.color, self.opacity, stroke=SILICON_EDGE, stroke_width=0.08),
            _chip_segment_polygon((-active / 2.0 - taper, 0.0), (-active / 2.0, 0.0), w, h * 0.5, fill=self.color,
                                  opacity=self.opacity, stroke=SILICON_EDGE, stroke_width=0.08),
            _chip_segment_polygon((active / 2.0, 0.0), (active / 2.0 + taper, 0.0), h * 0.5, w, fill=self.color,
                                  opacity=self.opacity, stroke=SILICON_EDGE, stroke_width=0.08),
            _chip_box(0.0, 0.0, active, h, self.color, self.opacity * 0.4, stroke=SILICON_EDGE, stroke_width=0.06),
            _chip_box(0.0, h * 0.36, active * 0.94, h * 0.24, P_DOPED, self.opacity, stroke=P_EDGE, stroke_width=0.05),
            _chip_box(0.0, -h * 0.36, active * 0.94, h * 0.24, N_DOPED, self.opacity, stroke=N_EDGE, stroke_width=0.05),
            _chip_box(0.0, 0.0, active * 0.9, h * 0.4, GERMANIUM, self.opacity, stroke=GERMANIUM_EDGE, stroke_width=0.06),
        ]
        for sign in (1.0, -1.0):
            children += _contact_children(0.0, sign * h * 0.36, active * 0.84, h * 0.1, self.opacity)
            top = sign * (py - self.pad_size / 2.0)
            children.append(_chip_box(0.0, (sign * h * 0.36 + top) / 2.0, self.pad_size * 0.2, abs(top - sign * h * 0.36),
                                      GOLD, self.opacity, stroke=GOLD_EDGE, stroke_width=0.05))
            children += _pad_children(0.0, sign * py, self.pad_size, self.pad_size, self.opacity)
        return {"type": "group", "children": children}

    def geometry_3d(self) -> dict[str, Any]:
        """The 2D drawing on the shared stack: the silicon tapers into a doped slab region, the germanium stripe
        flush with the core, contact plugs from the p and n slab up to M1, then leads and pads."""

        t = self._draw_thickness()
        preset = self._draw_material_preset()
        stack = self._draw_layer_stack()
        half, active, h, py = self.length / 2.0, self.active_length, self._region_height, self._pad_y
        w = self._draw("waveguide_width", self.waveguide_width)
        taper = (half - active / 2.0) * 0.6
        # the germanium replaces the core in the active section, and the p and n strips are the slab in theirs
        owners = [_chip_slab(active * 0.9, h * 0.4, t, color=GERMANIUM, preset="germanium", z_offset=stack["core_z"]),
                  *[_chip_slab(active * 0.94, h * 0.24, stack["implant_height"], y=sign * h * 0.36,
                               z_offset=stack["implant_z"], color=colour, preset="silicon")
                    for sign, colour in ((1.0, P_DOPED), (-1.0, N_DOPED))]]
        children = [
            *_cut_footprints([_chip_slab(self.length, w, t, **self._core()),
                              _chip_slab(active, h, stack["rib_height"], **self._slab(self.color, preset))], owners),
            _chip_segment_slab((-active / 2.0 - taper, 0.0), (-active / 2.0, 0.0), w, h * 0.5, t, **self._core()),
            _chip_segment_slab((active / 2.0, 0.0), (active / 2.0 + taper, 0.0), h * 0.5, w, t, **self._core()),
            *owners,
        ]
        for sign in (1.0, -1.0):
            top = sign * (py - self.pad_size / 2.0)
            children += [
                _chip_slab(active * 0.84, h * 0.1, stack["metal_z"] - stack["contact_z"], y=sign * h * 0.36,
                           z_offset=stack["contact_z"], color="#f08c6d", preset="copper"),
                _chip_slab(self.pad_size * 0.2, abs(top - sign * h * 0.36), stack["metal_height"],
                           y=(sign * h * 0.36 + top) / 2.0, z_offset=stack["metal_z"], color=GOLD, preset="gold"),
                *_pad_on_via(self.pad_size, self.pad_size, 0.0, sign * py, stack,
                             below=stack["metal_z"] + stack["metal_height"], color=_EAM_GOLD, arrive=(0.0, top)),
            ]
        return self._on_the_stack(children)

    def physics_metadata(self) -> dict[str, Any]:
        return {"domain": "on_chip", "component": "eam", "mode": "modulation", "active_length": self.active_length}


class IQModulator(ChipComponent):
    """Nested Mach-Zehnder IQ modulator: an I and a Q MZM in the two arms of an outer interferometer.

    A Y-branch splits the light, S-bends carry it to the two MZMs, a thermal
    phase shifter on the Q arm sets the 90 degree bias, and a Y-branch joins
    the arms. The parts are the catalog's own ``YBranch``, ``MZM`` and
    ``PhaseShifter``, so the layout is theirs. The Q modulator and the heater
    are turned top to bottom, so every electrode faces outward. Ports: ``o1`` in, ``o2`` out,
    ``i_sig``/``i_gnd`` and ``q_sig``/``q_gnd`` on the MZM electrodes, ``h1``/``h2``
    on the phase shifter.
    """

    component_type = "IQModulator"
    schematic_family = "mzm"                          # the schematic sizes of its active parts

    def __init__(self, center=(0, 0), angle=0, arm_gap=48.0, bend_length=40.0, **kwargs):
        self.arm_gap = float(arm_gap)
        self.bend_length = float(bend_length)
        self._init_chip(center=center, angle=angle, **kwargs)

    def physical_spec(self) -> PhysicalSpec:
        return PhysicalSpec(device_family=self.schematic_family,
                            values={"arm_gap": self.arm_gap, "bend_length": self.bend_length})

    def _parts(self) -> tuple[Any, Any, Any]:
        from optodraw.components.onchip.waveguides import PhaseShifter

        style = {"color": self.color, "opacity": self.opacity, "visual_style": self.visual_style,
                 "visual_scale": self.visual_scale, "render_physical": self.render_physical,
                 "z_exaggeration": self.z_exaggeration, "width_exaggeration": self.width_exaggeration,
                 "length_exaggeration": self.length_exaggeration, "material_preset": self.material_preset,
                 "chip_thickness": self.chip_thickness, **self._stack_kwargs()}
        ybranch = YBranch(**style)
        width = float(ybranch._draw_variant().waveguide_width)        # the phase shifter draws its width as given
        return ybranch, MZM(**style), PhaseShifter(width=width, **style)

    def _layout(self) -> dict[str, float]:
        """x of each part, left to right, centred on the two optical ports."""

        ybranch, mzm, shifter = self._parts()
        yp, mp, sp = ybranch.ports(), mzm.ports(), shifter.ports()
        mzm_in, mzm_out = mp["o1"].center.x, mp["o3"].center.x
        y_out = yp["o2"].center.x
        split = mzm_in - self.bend_length - y_out                       # the splitter's centre
        shifter_x = mzm_out - sp["o1"].center.x                         # the phase shifter starts at the MZM output
        arm_end = shifter_x + sp["o2"].center.x
        join = arm_end + self.bend_length + y_out                       # the joining branch, turned round
        left, right = split + yp["o1"].center.x, join - yp["o1"].center.x
        shift = -(left + right) / 2.0
        return {"split": split + shift, "join": join + shift, "mzm": shift, "shifter": shifter_x + shift,
                "mzm_in": mzm_in + shift, "arm_end": arm_end + shift, "branch": y_out, "offset": yp["o2"].center.y,
                "left": left + shift, "right": right + shift, "mzm_out": mzm_out + shift}

    def _bends(self) -> list[list[tuple[float, float]]]:
        """Centre lines of the four S-bends and the straight on the I arm (it matches the phase shifter)."""

        import math

        lay, d = self._layout(), self.arm_gap / 2.0

        def bend(x0: float, y0: float, x1: float, y1: float) -> list[tuple[float, float]]:
            return [(x0 + (x1 - x0) * t / 24.0, y0 + (y1 - y0) * (1.0 - math.cos(math.pi * t / 24.0)) / 2.0)
                    for t in range(25)]

        lines = []
        for sign in (1.0, -1.0):
            lines.append(bend(lay["split"] + lay["branch"], sign * lay["offset"], lay["mzm_in"], sign * d))
            lines.append(bend(lay["arm_end"], sign * d, lay["join"] - lay["branch"], sign * lay["offset"]))
        lines.append([(lay["mzm_out"], d), (lay["arm_end"], d)])
        return lines

    def _wire_width(self) -> float:
        ybranch = self._parts()[0]
        return float(ybranch._draw_variant().waveguide_width)

    def geometry_2d(self) -> dict[str, Any]:
        ybranch, mzm, shifter = self._parts()
        lay, d = self._layout(), self.arm_gap / 2.0
        join = _rotate_2d_node_ccw(_rotate_2d_node_ccw(ybranch.geometry_2d()))
        children = [
            _translate_layout_geometry(ybranch.geometry_2d(), lay["split"], 0.0),
            _translate_layout_geometry(join, lay["join"], 0.0),
            _translate_layout_geometry(mzm.geometry_2d(), lay["mzm"], d),
            _translate_layout_geometry(_mirror_layout_geometry_y(mzm.geometry_2d()), lay["mzm"], -d),
            _translate_layout_geometry(_mirror_layout_geometry_y(shifter.geometry_2d()), lay["shifter"], -d),
        ]
        width = self._wire_width()
        children += [_chip_polygon(_polyline_outline(line, width), fill=self.color, opacity=self.opacity,
                                   stroke=SILICON_EDGE, stroke_width=0.08) for line in self._bends()]
        return {"type": "group", "children": children}

    def geometry_3d(self) -> dict[str, Any]:
        ybranch, mzm, shifter = self._parts()
        lay, d = self._layout(), self.arm_gap / 2.0
        join = _rotate_3d_node_ccw(_rotate_3d_node_ccw(ybranch.geometry_3d()))
        children = [
            _translate_layout_geometry(ybranch.geometry_3d(), lay["split"], 0.0),
            _translate_layout_geometry(join, lay["join"], 0.0),
            _translate_layout_geometry(mzm.geometry_3d(), lay["mzm"], d),
            _translate_layout_geometry(_mirror_layout_geometry_y(mzm.geometry_3d()), lay["mzm"], -d),
            _translate_layout_geometry(_mirror_layout_geometry_y(shifter.geometry_3d()), lay["shifter"], -d),
        ]
        width = self._wire_width()
        bends = [_chip_extruded_polygon(_polyline_outline(line, width), self._draw_thickness(), **self._core()) for line in self._bends()]
        return {"shape": "group", "children": [*children, *self._on_the_stack(bends)["children"]]}   # the parts are on it

    def ports(self) -> dict[str, Port]:
        _, mzm, shifter = self._parts()
        lay, d = self._layout(), self.arm_gap / 2.0
        mp, sp = mzm.ports(), shifter.ports()

        def moved(name: str, port: Port, dx: float, dy: float, flip: bool = False) -> Port:
            y, turn = (-port.center.y, -port.orientation_deg % 360.0) if flip else (port.center.y, port.orientation_deg)
            return Port(name, Vec3(port.center.x + dx, y + dy, 0.0), orientation_deg=turn, width=port.width, kind=port.kind)

        width = self._wire_width()
        return {
            "o1": Port("o1", Vec3(lay["left"], 0.0, 0.0), orientation_deg=180, width=width),
            "o2": Port("o2", Vec3(lay["right"], 0.0, 0.0), orientation_deg=0, width=width),
            "i_sig": moved("i_sig", mp["sig"], lay["mzm"], d), "i_gnd": moved("i_gnd", mp["gnd"], lay["mzm"], d),
            "q_sig": moved("q_sig", mp["sig"], lay["mzm"], -d, True), "q_gnd": moved("q_gnd", mp["gnd"], lay["mzm"], -d, True),
            "h1": moved("h1", sp["h1"], lay["shifter"], -d, True), "h2": moved("h2", sp["h2"], lay["shifter"], -d, True),
        }

    def physics_metadata(self) -> dict[str, Any]:
        return {"domain": "on_chip", "component": "iq_modulator", "mode": "modulation", "bias_deg": 90.0,
                "arm_gap": self.arm_gap}

