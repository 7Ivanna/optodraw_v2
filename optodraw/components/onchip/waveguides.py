"""Waveguide component."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from optodraw.core.ports import Port
from optodraw.core.schematic_geometry import PhysicalSpec
from optodraw.core.transform import Vec3

from optodraw.components.onchip.base import ChipComponent, _generic_pdk_defaults, SILICON_EDGE
from optodraw.components.onchip.geometry import (
    _arc_points,
    _chip_box,
    _chip_line,
    _chip_path_slab,
    _chip_polygon,
    _chip_polyline,
    _chip_segment_polygon,
    _chip_segment_slab,
    _chip_slab,
    _pad_on_via,
    _polyline_outline,
)

@dataclass
class Waveguide(ChipComponent):
    component_type = "Waveguide"
    schematic_family = "waveguide"
    length: float = 20.0
    width: float = 0.5
    bend_radius: float = 10.0
    effective_index: float | None = None

    def __init__(
        self,
        center=(0, 0),
        angle=0,
        length=20.0,
        width: float | None = None,
        bend_radius: float | None = None,
        effective_index: float | None = None,
        **kwargs,
    ):
        strip = _generic_pdk_defaults()["strip"]
        raw_width = float(strip["width"] if width is None else width)
        self._init_chip(center=center, angle=angle, **kwargs)
        self.length = float(length)
        self.width = raw_width
        self.bend_radius = float(strip["radius"] if bend_radius is None else bend_radius)
        self.effective_index = None if effective_index is None else float(effective_index)

    def physical_spec(self) -> PhysicalSpec:
        return PhysicalSpec(
            device_family=self.schematic_family,
            values={
                "length": self.length,
                "width": self.width,
                "bend_radius": self.bend_radius,
                "thickness": self.chip_thickness,
            },
        )

    def ports(self) -> dict[str, Port]:
        half = self._draw("length", self.length) / 2.0
        width = self._draw("width", self.width)
        return {
            "o1": Port("o1", Vec3(-half, 0, 0), orientation_deg=180, width=width),
            "o2": Port("o2", Vec3(half, 0, 0), orientation_deg=0, width=width),
        }

    def _symbolic_2d(self) -> dict[str, Any]:
        ports = self.ports()
        return {"type": "group", "children": [
            _chip_line(float(ports["o1"].center.x), 0.0, float(ports["o2"].center.x), 0.0, stroke="#111111", stroke_width=0.8, opacity=1.0),
        ]}

    def geometry_2d(self) -> dict[str, Any]:
        draw_length = self._draw("length")
        draw_width = self._draw("width")
        if self.visual_style == "symbolic":
            return self._symbolic_2d()
        return _chip_box(0, 0, draw_length, draw_width, self.color, self.opacity, stroke=SILICON_EDGE, stroke_width=0.08)

    def geometry_3d(self) -> dict[str, Any]:
        draw_length = self._draw("length")
        draw_width = self._draw("width")
        thickness = self._draw_thickness()
        return self._on_the_stack([
                _chip_slab(
                    draw_length,
                    draw_width,
                    thickness,
                    **self._core(),
                ),
            ])

    def physics_metadata(self) -> dict[str, Any]:
        return {
            "domain": "on_chip",
            "component": "waveguide",
            "width": self.width,
            "length": self.length,
            "mode": "guided",
            "effective_index": self.effective_index,
            # Guided paths remain scalar-power stubs; PM waveguides are future work.
            "polarization_maintaining": False,
        }


class Spiral(ChipComponent):
    """Archimedean spiral waveguide — a compact long delay line.

    The guide winds inward, turns around at the centre, and winds back out between
    its own windings, so both optical ports (``o1`` / ``o2``) sit at the outer edge
    on the left. ``turns`` sets the number of revolutions and ``spacing`` the gap
    between adjacent windings; the physical length grows with both.
    """

    component_type = "Spiral"
    schematic_family = "spiral"

    def __init__(
        self,
        center=(0, 0),
        angle: float = 0.0,
        turns: float = 3.0,
        spacing: float = 6.0,
        inner_radius: float = 9.0,
        width: float | None = None,
        **kwargs,
    ):
        strip = _generic_pdk_defaults()["strip"]
        self.turns = max(float(turns), 0.75)
        self.spacing = float(spacing)
        self.inner_radius = float(inner_radius)
        self.width = float(strip["width"] if width is None else width)
        self._init_chip(center=center, angle=angle, **kwargs)

    @property
    def _pitch(self) -> float:
        return max(self.spacing, self.width * 3.0)

    @property
    def _outer_radius(self) -> float:
        return self.inner_radius + self._pitch * self.turns

    def _spiral_path(self) -> list[tuple[float, float]]:
        # Archimedean spiral delay (per reference figure): two interleaved circular arms
        # half a turn apart wind from the outer edge to the centre, where an S-shaped
        # connector (two semicircles — the "yin-yang" middle) joins them. Both taper
        # ports leave horizontally to the LEFT (orientation 180°).
        pitch, n, r_in = self._pitch, max(self.turns, 1.0), self.inner_radius
        k = pitch / (2.0 * math.pi)
        total = n * 2.0 * math.pi
        steps = max(140, int(n * 70))
        arm1: list[tuple[float, float]] = []
        arm2: list[tuple[float, float]] = []
        for i in range(steps + 1):
            theta = total * i / steps
            r = r_in + k * theta                    # centre → outer
            ang = -math.pi / 2.0 + theta            # arm1 starts at the bottom
            arm1.append((r * math.cos(ang), r * math.sin(ang)))
            arm2.append((r * math.cos(ang + math.pi), r * math.sin(ang + math.pi)))  # half-turn apart
        # S-connector between the two innermost ends: (0,−r_in) → (0,0) → (0,+r_in),
        # flipped (bottom bulges LEFT, top bulges RIGHT) to match the reference middle
        rs, s_steps = r_in / 2.0, 16
        s_curve: list[tuple[float, float]] = []
        for j in range(s_steps + 1):                # arc A bulges left
            a = -math.pi / 2.0 + math.pi * j / s_steps
            s_curve.append((-rs * math.cos(a), -rs + rs * math.sin(a)))
        for j in range(1, s_steps + 1):             # arc B bulges right
            a = -math.pi / 2.0 - math.pi * j / s_steps
            s_curve.append((-rs * math.cos(a), rs + rs * math.sin(a)))
        path = list(reversed(arm1)) + s_curve + arm2
        # access routing (per the reference edits):
        #   o1 (bottom end) runs straight RIGHT along the bottom;
        #   o2 (top end) CONTINUES the spiral a quarter-turn further out (so it reads as
        #   the next winding, properly spaced), goes straight DOWN, then peels away to the
        #   LEFT through a circular bend.
        r_out = r_in + pitch * n
        margin = r_out * 1.45
        by = path[0][1]
        o1_lead = [(margin, by)]
        ext = 18
        o2_lead: list[tuple[float, float]] = []
        for j in range(1, ext + 1):
            theta = total + (math.pi / 2.0) * j / ext          # extend the spiral past the outer end
            r = r_in + k * theta
            ang = math.pi / 2.0 + theta
            o2_lead.append((r * math.cos(ang), r * math.sin(ang)))
        lx = o2_lead[-1][0]                                     # leftmost point, centre height
        yd, rb = -r_out * 0.5, r_out * 0.26                     # straight-down depth + bend radius
        o2_lead.append((lx, yd))                               # straight down
        o2_lead += [(lx - rb + rb * math.cos(-(math.pi / 2.0) * j / 8.0), yd + rb * math.sin(-(math.pi / 2.0) * j / 8.0)) for j in range(1, 9)]  # circular bend out to the left
        o2_lead.append((-margin, yd - rb))                     # straight left to the port
        return [*o1_lead, *path, *o2_lead]

    def _port_endpoints(self) -> tuple[tuple[float, float], tuple[float, float]]:
        path = self._spiral_path()
        return path[0], path[-1]

    def physical_spec(self) -> PhysicalSpec:
        path = self._spiral_path()
        length = sum(math.dist(path[i], path[i + 1]) for i in range(len(path) - 1))
        return PhysicalSpec(
            device_family=self.schematic_family,
            values={
                "turns": self.turns,
                "spacing": self.spacing,
                "outer_radius": self._outer_radius,
                "delay_length": length,
                "width": self.width,
                "thickness": self.chip_thickness,
            },
        )

    def ports(self) -> dict[str, Port]:
        (ax, ay), (bx, by) = self._port_endpoints()
        w = self._draw("width", self.width)
        return {
            "o1": Port("o1", Vec3(ax, ay, 0), orientation_deg=0, width=w),    # exits right along the bottom
            "o2": Port("o2", Vec3(bx, by, 0), orientation_deg=180, width=w),   # hugs the ring, down, then exits left
        }


    def optical_paths(self, in_port: str) -> list[dict[str, Any]]:
        """Light coils through the DRAWN spiral polyline — the full delay path."""

        draw = self._draw_variant() if hasattr(self, "_draw_variant") else self
        if draw is not self:
            draw.anim_params = self.anim_params  # behaviours ride along
            return draw.optical_paths(in_port)
        if in_port not in ("o1", "o2"):
            return []
        pts = [list(p) for p in self._spiral_path()]
        if in_port == "o2":
            pts = pts[::-1]
        target = "o2" if in_port == "o1" else "o1"
        return [{"port": target, "power": 0.97, "pts": pts}]

    def geometry_2d(self) -> dict[str, Any]:
        return {
            "type": "group",
            "children": [
                _chip_polyline(self._spiral_path(), stroke=self.color, stroke_width=self._draw("width", self.width), opacity=self.opacity),
            ],
        }

    def geometry_3d(self) -> dict[str, Any]:
        return self._on_the_stack([
                _chip_path_slab(self._spiral_path(), self._draw("width", self.width), self._draw_thickness(), **self._core()),
            ])

    def physics_metadata(self) -> dict[str, Any]:
        path = self._spiral_path()
        length = sum(math.dist(path[i], path[i + 1]) for i in range(len(path) - 1))
        return {"domain": "on_chip", "component": "spiral_delay", "mode": "guided", "delay_length": length, "turns": self.turns, "width": self.width}


_GOLD = "#d4af37"
_GOLD_DARK = "#8e7611"
_TIN, _TIN_EDGE = "#c8964a", "#8a6326"          # a TiN heater: bronze, apart from the gold pads
_TRENCH, _TRENCH_EDGE = "#eef4fb", "#9fb6cc"    # an air trench
_P_RED = "#c76d6d"
_N_BLUE = "#6d8fc7"


class PhaseShifter(ChipComponent):
    """A straight waveguide carrying a tunable phase shifter.

    ``mechanism="thermo_optic"`` draws a resistive heater over the guide with two
    contact pads (``h1`` / ``h2``); ``mechanism="electro_optic"`` draws a lateral PN
    junction (red p / blue n stripes) with two electrodes (``e1`` / ``e2``). Optical
    ports ``o1`` / ``o2`` pass straight through.
    """

    component_type = "PhaseShifter"
    schematic_family = "phase_shifter"

    def __init__(
        self,
        center=(0, 0),
        angle: float = 0.0,
        length: float = 40.0,
        width: float | None = None,
        mechanism: str = "thermo_optic",
        shifter_length: float | None = None,
        **kwargs,
    ):
        strip = _generic_pdk_defaults()["strip"]
        self.length = float(length)
        self.width = float(strip["width"] if width is None else width)
        normalized = mechanism.lower().replace("-", "").replace("_", "").replace(" ", "")
        if normalized in {"thermooptic", "to", "heater", "thermal", "thermo"}:
            self.mechanism = "thermo_optic"
        elif normalized in {"electrooptic", "eo", "pn", "carrier", "depletion"}:
            self.mechanism = "electro_optic"
        else:
            raise ValueError("mechanism must be 'thermo_optic' or 'electro_optic'")
        self.shifter_length = float(shifter_length if shifter_length is not None else self.length * 0.6)
        self._init_chip(center=center, angle=angle, **kwargs)

    def _metrics(self) -> dict[str, float]:
        active, width = min(self.shifter_length, self.length), self._draw("width", self.width)   # the drawn guide
        return {
            "active": active,
            "half_active": active / 2.0,
            "pad": max(width * 4.0, 2.6),
            "stripe_w": max(width * 1.2, 0.8),
            "stripe_off": max(width * 1.1, 0.8),
            "heater_w": max(width * 1.8, 1.0),
            "pad_y": max(width * 4.5, 3.5),
        }

    def physical_spec(self) -> PhysicalSpec:
        return PhysicalSpec(
            device_family=self.schematic_family,
            values={
                "length": self.length,
                "width": self.width,
                "shifter_length": self.shifter_length,
                "electro_optic": self.mechanism == "electro_optic",
                "thickness": self.chip_thickness,
            },
        )

    def ports(self) -> dict[str, Port]:
        half = self.length / 2.0
        m = self._metrics()
        ports = {
            "o1": Port("o1", Vec3(-half, 0, 0), orientation_deg=180, width=self._draw("width", self.width)),
            "o2": Port("o2", Vec3(half, 0, 0), orientation_deg=0, width=self._draw("width", self.width)),
        }
        if self.mechanism == "thermo_optic":
            ports["h1"] = Port("h1", Vec3(-m["half_active"], m["pad_y"], 0), orientation_deg=90, width=m["pad"], kind="electrical")
            ports["h2"] = Port("h2", Vec3(m["half_active"], m["pad_y"], 0), orientation_deg=90, width=m["pad"], kind="electrical")
        else:
            ports["e1"] = Port("e1", Vec3(0.0, m["pad_y"], 0), orientation_deg=90, width=m["pad"], kind="electrical")
            ports["e2"] = Port("e2", Vec3(0.0, -m["pad_y"], 0), orientation_deg=270, width=m["pad"], kind="electrical")
        return ports

    def symbol_1d(self) -> tuple[str, dict[str, Any]] | None:
        return ("phase", {"kind": "pn"}) if self.mechanism == "electro_optic" else None

    def geometry_2d(self) -> dict[str, Any]:
        length = self._draw("length")
        width = self._draw("width")
        m = self._metrics()
        children = [_chip_box(0, 0, length, width, self.color, self.opacity, stroke=SILICON_EDGE, stroke_width=0.08)]
        ha, pad, pad_y = m["half_active"], m["pad"], m["pad_y"]
        if self.mechanism == "thermo_optic":
            # air trenches on both sides keep the heat in the guide; a TiN heater on top, vias at
            # its ends, gold leads and pads (an inner square gives the pad its depth)
            inner = max(width, m["heater_w"]) / 2.0 + 0.3
            outer = pad_y - pad / 2.0 - 0.2
            if outer - inner > 0.4:
                for sign in (1.0, -1.0):
                    children.insert(0, _chip_box(0, sign * (inner + outer) / 2.0, m["active"] * 0.86, outer - inner,
                                                 _TRENCH, self.opacity, stroke=_TRENCH_EDGE, stroke_width=0.06))
            via = max(m["heater_w"] * 0.7, 0.6)
            children += [
                _chip_box(0, 0, m["active"], m["heater_w"], _TIN, self.opacity * 0.95, stroke=_TIN_EDGE, stroke_width=0.08),
                _chip_line(-ha, pad_y, -ha, 0, stroke=_GOLD, stroke_width=m["heater_w"] * 0.6, opacity=self.opacity),
                _chip_line(ha, pad_y, ha, 0, stroke=_GOLD, stroke_width=m["heater_w"] * 0.6, opacity=self.opacity),
            ]
            for x in (-ha, ha):
                children += [
                    _chip_box(x, 0, via, via, "#f08c6d", self.opacity, stroke="#8b5038", stroke_width=0.06),
                    _chip_box(x, pad_y, pad, pad, _GOLD, self.opacity, stroke=_GOLD_DARK, stroke_width=0.1),
                    _chip_box(x, pad_y, pad * 0.7, pad * 0.7, "#e7c069", self.opacity, stroke="#fff1bd", stroke_width=0.06),
                ]
        else:
            rail_w = max(m["stripe_w"] * 0.55, 0.45)
            lead_w = rail_w * 1.3
            via = max(rail_w * 0.9, 0.4)
            p_y, n_y = m["stripe_off"], -m["stripe_off"]
            children += [
                _chip_box(0, p_y, m["active"], m["stripe_w"], _P_RED, self.opacity * 0.92, stroke="#864646", stroke_width=0.08),
                _chip_box(0, n_y, m["active"], m["stripe_w"], _N_BLUE, self.opacity * 0.92, stroke="#3f5f96", stroke_width=0.08),
                # metal contact rails running the length of the p and n regions
                _chip_box(0, p_y, m["active"] * 0.94, rail_w, _GOLD, self.opacity, stroke=_GOLD_DARK, stroke_width=0.07),
                _chip_box(0, n_y, m["active"] * 0.94, rail_w, _GOLD, self.opacity, stroke=_GOLD_DARK, stroke_width=0.07),
                # vertical leads from each rail out to its contact pad
                _chip_box(0, (pad_y + p_y) / 2.0, lead_w, pad_y - p_y, _GOLD, self.opacity, stroke=_GOLD_DARK, stroke_width=0.07),
                _chip_box(0, (-pad_y + n_y) / 2.0, lead_w, pad_y + n_y, _GOLD, self.opacity, stroke=_GOLD_DARK, stroke_width=0.07),
                _chip_box(0, pad_y, pad, pad, _GOLD, self.opacity, stroke=_GOLD_DARK, stroke_width=0.1),
                _chip_box(0, -pad_y, pad, pad, _GOLD, self.opacity, stroke=_GOLD_DARK, stroke_width=0.1),
            ]
            # ohmic-contact vias spaced along each rail
            for vx in (-ha * 0.5, 0.0, ha * 0.5):
                children.append(_chip_box(vx, p_y, via, via, "#f08c6d", self.opacity, stroke="#8b5038", stroke_width=0.06))
                children.append(_chip_box(vx, n_y, via, via, "#f08c6d", self.opacity, stroke="#8b5038", stroke_width=0.06))
        return {"type": "group", "children": children}

    def geometry_3d(self) -> dict[str, Any]:
        """On the shared stack. Thermo-optic: a TiN heater on the heater layer, its leads and pads on M1.
        Electro-optic: a doped slab stripe on each side, contact plugs from the slab top up to M1 rails, then
        leads and pads."""

        length = self._draw("length")
        width = self._draw("width")
        t = self._draw_thickness()
        m = self._metrics()
        stack = self._draw_layer_stack()
        children = [_chip_slab(length, width, t, **self._core())]

        def metal(size_x, size_y, x=0.0, y=0.0):
            return _chip_slab(size_x, size_y, stack["metal_height"], x=x, y=y, z_offset=stack["metal_z"],
                              color=_GOLD, preset="gold")

        def pad(x, y):
            return _pad_on_via(m["pad"], m["pad"], x, y, stack, below=stack["metal_z"] + stack["metal_height"], color=_GOLD)

        if self.mechanism == "thermo_optic":
            lead = m["heater_w"] * 0.6
            # the heater ends at the inner edge of each lead: M1 and the heater share a base, and M1 is the terminal
            children.append(_chip_slab(m["active"] - lead, m["heater_w"], stack["heater_height"], z_offset=stack["heater_z"],
                                       color=_TIN, preset="titanium_nitride"))
            for x in (-m["half_active"], m["half_active"]):
                children += [metal(lead, m["pad_y"], x=x, y=m["pad_y"] / 2.0), *pad(x, m["pad_y"])]
        else:
            rail_w = max(m["stripe_w"] * 0.55, 0.45)
            via = max(rail_w * 0.9, 0.4)
            plug = stack["metal_z"] - stack["contact_z"]
            for y, colour in ((m["stripe_off"], _P_RED), (-m["stripe_off"], _N_BLUE)):
                side = 1.0 if y > 0 else -1.0
                children += [
                    _chip_slab(m["active"], m["stripe_w"], stack["implant_height"], y=y, z_offset=stack["implant_z"],
                               color=colour, preset="silicon"),
                    metal(m["active"] * 0.94, rail_w, y=y),
                    metal(rail_w * 1.3, m["pad_y"] - abs(y), y=side * (m["pad_y"] + abs(y)) / 2.0),
                    *pad(0.0, side * m["pad_y"]),
                ]
                for x in (-m["half_active"] * 0.5, 0.0, m["half_active"] * 0.5):
                    children.append(_chip_slab(via, via, plug, x=x, y=y, z_offset=stack["contact_z"],
                                               color="#f08c6d", preset="copper"))
        return self._on_the_stack(children)

    def physics_metadata(self) -> dict[str, Any]:
        return {"domain": "on_chip", "component": "phase_shifter", "mechanism": self.mechanism, "mode": "guided", "length": self.length, "width": self.width}


@dataclass
class Taper(ChipComponent):
    """Linear width taper / spot-size converter between two waveguide widths."""

    component_type = "Taper"
    schematic_family = "taper"
    length: float = 12.0
    width1: float = 0.5
    width2: float = 1.8

    def __init__(self, center=(0, 0), angle=0, length=12.0, width1: float | None = None, width2=1.8, **kwargs):
        strip = _generic_pdk_defaults()["strip"]
        self.length = float(length)
        self.width1 = float(strip["width"] if width1 is None else width1)
        self.width2 = float(width2)
        self._init_chip(center=center, angle=angle, **kwargs)

    def physical_spec(self) -> PhysicalSpec:
        return PhysicalSpec(
            device_family=self.schematic_family,
            values={"length": self.length, "width1": self.width1, "width2": self.width2, "thickness": self.chip_thickness},
        )

    def ports(self) -> dict[str, Port]:
        half = self.length / 2.0
        return {
            "o1": Port("o1", Vec3(-half, 0, 0), orientation_deg=180, width=self._draw("width1", self.width1)),
            "o2": Port("o2", Vec3(half, 0, 0), orientation_deg=0, width=self._draw("width2", self.width2)),
        }

    def geometry_2d(self) -> dict[str, Any]:
        half = self.length / 2.0
        return {
            "type": "group",
            "children": [
                _chip_segment_polygon((-half, 0.0), (half, 0.0), self._draw("width1", self.width1), self._draw("width2", self.width2), fill=self.color, opacity=self.opacity, stroke=SILICON_EDGE, stroke_width=0.08),
            ],
        }

    def geometry_3d(self) -> dict[str, Any]:
        half = self.length / 2.0
        return self._on_the_stack([
                _chip_segment_slab((-half, 0.0), (half, 0.0), self._draw("width1", self.width1), self._draw("width2", self.width2), self._draw_thickness(), **self._core()),
            ])

    def physics_metadata(self) -> dict[str, Any]:
        return {"domain": "on_chip", "component": "taper", "mode": "guided", "width": self.width1}


@dataclass
class WaveguideBend(ChipComponent):
    """Circular 90° waveguide bend connecting a west port to a north port."""

    component_type = "WaveguideBend"
    schematic_family = "bend"
    radius: float = 10.0
    width: float = 0.5
    angle_deg: float = 90.0

    def __init__(self, center=(0, 0), angle=0, radius: float | None = None, width: float | None = None, angle_deg=90.0, **kwargs):
        strip = _generic_pdk_defaults()["strip"]
        self.radius = float(strip["radius"] if radius is None else radius)
        self.width = float(strip["width"] if width is None else width)
        self.angle_deg = float(angle_deg)
        self._init_chip(center=center, angle=angle, **kwargs)

    def _centerline(self) -> list[tuple[float, float]]:
        # Start tangent points east; the end tangent turns by angle_deg.
        return _arc_points(-self.radius, self.radius, self.radius, -90.0, -90.0 + self.angle_deg, segments=28)

    def physical_spec(self) -> PhysicalSpec:
        return PhysicalSpec(
            device_family=self.schematic_family,
            values={"radius": self.radius, "width": self.width, "angle_deg": self.angle_deg, "thickness": self.chip_thickness},
        )

    def ports(self) -> dict[str, Port]:
        pts = self._centerline()
        (ax, ay), (bx, by) = pts[0], pts[-1]
        return {
            "o1": Port("o1", Vec3(ax, ay, 0), orientation_deg=180, width=self._draw("width", self.width)),
            "o2": Port("o2", Vec3(bx, by, 0), orientation_deg=self.angle_deg % 360.0, width=self._draw("width", self.width)),
        }


    def optical_paths(self, in_port: str) -> list[dict[str, Any]]:
        """Light follows the DRAWN arc centerline."""

        draw = self._draw_variant() if hasattr(self, "_draw_variant") else self
        if draw is not self:
            draw.anim_params = self.anim_params  # behaviours ride along
            return draw.optical_paths(in_port)
        if in_port not in ("o1", "o2"):
            return []
        pts = [list(p) for p in self._centerline()]
        if in_port == "o2":
            pts = pts[::-1]
        target = "o2" if in_port == "o1" else "o1"
        return [{"port": target, "power": 0.97, "pts": pts}]

    def geometry_2d(self) -> dict[str, Any]:
        return {
            "type": "group",
            "children": [_chip_polygon(_polyline_outline(self._centerline(), self._draw("width", self.width)), fill=self.color, opacity=self.opacity, stroke=SILICON_EDGE, stroke_width=0.08)],
        }

    def geometry_3d(self) -> dict[str, Any]:
        return self._on_the_stack([_chip_path_slab(self._centerline(), self._draw("width", self.width), self._draw_thickness(), **self._core())])

    def physics_metadata(self) -> dict[str, Any]:
        return {"domain": "on_chip", "component": "bend", "mode": "guided", "radius": self.radius}


@dataclass
class WaveguideCrossing(ChipComponent):
    """Symmetric ``+`` waveguide crossing — four tapered arms meeting at a central
    expansion that lets two perpendicular guides cross with low crosstalk."""

    component_type = "WaveguideCrossing"
    schematic_family = "crossing"
    arm_length: float = 4.5
    waveguide_width: float = 0.5
    taper_width: float = 1.6
    center_size: float = 2.2

    def __init__(self, center=(0, 0), angle=0, arm_length=4.5, waveguide_width: float | None = None, taper_width=1.6, center_size=2.2, **kwargs):
        strip = _generic_pdk_defaults()["strip"]
        self.arm_length = float(arm_length)
        self.waveguide_width = float(strip["width"] if waveguide_width is None else waveguide_width)
        self.taper_width = float(taper_width)
        self.center_size = float(center_size)
        self._init_chip(center=center, angle=angle, **kwargs)

    def physical_spec(self) -> PhysicalSpec:
        return PhysicalSpec(
            device_family=self.schematic_family,
            values={"arm_length": self.arm_length, "waveguide_width": self.waveguide_width, "taper_width": self.taper_width, "center_size": self.center_size, "thickness": self.chip_thickness},
        )

    def ports(self) -> dict[str, Port]:
        a, w = self.arm_length, self._draw("waveguide_width", self.waveguide_width)
        return {
            "o1": Port("o1", Vec3(-a, 0, 0), orientation_deg=180, width=w),
            "o2": Port("o2", Vec3(a, 0, 0), orientation_deg=0, width=w),
            "o3": Port("o3", Vec3(0, a, 0), orientation_deg=90, width=w),
            "o4": Port("o4", Vec3(0, -a, 0), orientation_deg=270, width=w),
        }

    def _arm_segments(self) -> list[tuple[tuple[float, float], tuple[float, float]]]:
        a, c = self.arm_length, self.center_size / 2.0
        return [((-a, 0.0), (-c, 0.0)), ((a, 0.0), (c, 0.0)), ((0.0, a), (0.0, c)), ((0.0, -a), (0.0, -c))]

    def optical_paths(self, in_port: str) -> list[dict[str, Any]]:
        """Straight through the centre expansion to the opposite arm."""

        opposite = {"o1": "o2", "o2": "o1", "o3": "o4", "o4": "o3"}.get(in_port)
        if opposite is None:
            return []
        ports = self.ports()
        start, end = ports[in_port].center, ports[opposite].center
        return [{"port": opposite, "pts": [[start.x, start.y], [0.0, 0.0], [end.x, end.y]]}]

    def geometry_2d(self) -> dict[str, Any]:
        children = [
            _chip_segment_polygon(tip, mid, self._draw("waveguide_width", self.waveguide_width), self.taper_width, fill=self.color, opacity=self.opacity, stroke=SILICON_EDGE, stroke_width=0.08)
            for tip, mid in self._arm_segments()
        ]
        children.append(_chip_box(0.0, 0.0, self.center_size, self.center_size, self.color, self.opacity, stroke=SILICON_EDGE, stroke_width=0.08))
        return {"type": "group", "children": children}

    def geometry_3d(self) -> dict[str, Any]:
        t = self._draw_thickness()
        core = self._core()
        children = [
            _chip_segment_slab(tip, mid, self._draw("waveguide_width", self.waveguide_width), self.taper_width, t, **core)
            for tip, mid in self._arm_segments()
        ]
        children.append(_chip_slab(self.center_size, self.center_size, t, **core))
        return self._on_the_stack(children)

    def physics_metadata(self) -> dict[str, Any]:
        return {"domain": "on_chip", "component": "crossing", "mode": "guided"}


@dataclass
class Terminator(ChipComponent):
    """Inverse-taper waveguide terminator — narrows to a fine tip so unused light
    radiates into the cladding instead of reflecting back."""

    component_type = "Terminator"
    schematic_family = "terminator"
    length: float = 8.0
    width: float = 0.5
    tip_width: float = 0.08

    _ABSORB = "#6f5a5a"

    def __init__(self, center=(0, 0), angle=0, length=8.0, width: float | None = None, tip_width=0.08, **kwargs):
        strip = _generic_pdk_defaults()["strip"]
        self.length = float(length)
        self.width = float(strip["width"] if width is None else width)
        self.tip_width = float(tip_width)
        self._init_chip(center=center, angle=angle, **kwargs)

    def physical_spec(self) -> PhysicalSpec:
        return PhysicalSpec(
            device_family=self.schematic_family,
            values={"length": self.length, "width": self.width, "tip_width": self.tip_width, "thickness": self.chip_thickness},
        )

    def ports(self) -> dict[str, Port]:
        return {"o1": Port("o1", Vec3(-self.length / 2.0, 0, 0), orientation_deg=180, width=self._draw("width", self.width))}

    def geometry_2d(self) -> dict[str, Any]:
        half, width = self.length / 2.0, self._draw("width", self.width)
        # taper down to a fine tip + a faint radiation fan past the tip
        fan = [(half, self.tip_width / 2.0), (half + self.length * 0.35, width * 1.1), (half + self.length * 0.35, -width * 1.1), (half, -self.tip_width / 2.0)]
        return {
            "type": "group",
            "children": [
                _chip_polygon(fan, fill=self._ABSORB, opacity=self.opacity * 0.25, stroke="none", stroke_width=0.0),
                _chip_segment_polygon((-half, 0.0), (half, 0.0), width, self.tip_width, fill=self.color, opacity=self.opacity, stroke=SILICON_EDGE, stroke_width=0.08),
            ],
        }

    def geometry_3d(self) -> dict[str, Any]:
        half = self.length / 2.0
        return self._on_the_stack([
                _chip_segment_slab((-half, 0.0), (half, 0.0), self._draw("width", self.width), self.tip_width, self._draw_thickness(), **self._core()),
            ])

    def physics_metadata(self) -> dict[str, Any]:
        return {"domain": "on_chip", "component": "terminator", "mode": "guided"}


class PCMCell(ChipComponent):
    """A phase-change-material cell: a patch of GST (Ge2Sb2Te5) on top of a waveguide that absorbs part of the
    light by its state, crystalline (dark, most light absorbed) or amorphous (pale, most light passes). It keeps
    its state with no power: a non-volatile weight or switch.

    Light runs from ``o1`` (west) to ``o2`` (east). The film is sputtered through a window twice the guide's width,
    so it covers the core's top and sides and the oxide beside it (Feldmann et al., Nature 589, 52 (2021): 10 nm
    GST under 10 nm ITO on 1.2 um wide, 325 nm Si3N4 guides). A schematic draws the film thicker so it shows in 3D.
    """

    component_type = "PCMCell"
    schematic_family = "pcm_cell"
    FILLS = {"crystalline": ("#4a4458", "#2c2836"), "amorphous": ("#a59db3", "#6b6378")}   # fill, edge

    def __init__(self, center=(0, 0), angle=0, length: float = 10.0, cell_length: float = 2.0,
                 waveguide_width: float = 1.2, state: str = "crystalline", **kwargs):
        if state not in self.FILLS:
            raise ValueError(f"state must be one of {sorted(self.FILLS)}")
        if not 0.0 < float(cell_length) <= float(length):
            raise ValueError("cell_length must be above 0 and no longer than length")
        self.length = float(length)
        self.cell_length = float(cell_length)
        self.waveguide_width = float(waveguide_width)
        self.state = state
        self._init_chip(center=center, angle=angle, **kwargs)

    def physical_spec(self) -> PhysicalSpec:
        return PhysicalSpec(device_family=self.schematic_family, values={
            "length": self.length, "cell_length": self.cell_length, "waveguide_width": self.waveguide_width,
            "thickness": self.chip_thickness})

    def ports(self) -> dict[str, Port]:
        half, width = self._draw("length", self.length) / 2.0, self._draw("waveguide_width", self.waveguide_width)
        return {"o1": Port("o1", Vec3(-half, 0, 0), orientation_deg=180, width=width),
                "o2": Port("o2", Vec3(half, 0, 0), orientation_deg=0, width=width)}

    def _anchor_points(self) -> dict[str, tuple[float, float]]:
        return {"cell": (0.0, 0.0)}

    def geometry_2d(self) -> dict[str, Any]:
        length, width = self._draw("length", self.length), self._draw("waveguide_width", self.waveguide_width)
        fill, edge = self.FILLS[self.state]
        return {"type": "group", "children": [
            _chip_box(0.0, 0.0, length, width, self.color, self.opacity, stroke=SILICON_EDGE, stroke_width=0.08),
            _chip_box(0.0, 0.0, self._draw("cell_length", self.cell_length), 2.0 * width, fill, self.opacity,
                      stroke=edge, stroke_width=0.08, layer="pcm"),
        ]}

    def geometry_3d(self) -> dict[str, Any]:
        length, width = self._draw("length", self.length), self._draw("waveguide_width", self.waveguide_width)
        cell, thickness = self._draw("cell_length", self.cell_length), self._draw_thickness()
        film = self._draw_layer_stack()["rib_height"] * 0.5  # 20 nm in the paper: a schematic makes it a plate
        look = {"color": self.FILLS[self.state][0], "preset": "gst"}
        foot = width / 2.0 - film                           # the film on the oxide, out to the window's edge
        core = self._core()
        base = core["z_offset"]                             # the stack's core level: the film follows the core
        children = [_chip_slab(length, width, thickness, **core),
                    _chip_slab(cell, width + 2.0 * film, film, z_offset=base + thickness, **look)]
        for side in (1.0, -1.0):                            # the film down each side wall, and on the oxide
            children += [_chip_slab(cell, film, thickness, y=side * (width + film) / 2.0, z_offset=base, **look),
                         _chip_slab(cell, foot, film, y=side * (width / 2.0 + film + foot / 2.0), z_offset=base, **look)]
        return self._on_the_stack(children)

    def symbol_1d(self) -> tuple[str, dict[str, Any]]:
        return "pcm", {}

    def physics_metadata(self) -> dict[str, Any]:
        return {"domain": "on_chip", "component": "pcm_cell", "material": "Ge2Sb2Te5", "state": self.state,
                "cell_length": self.cell_length, "non_volatile": True}
