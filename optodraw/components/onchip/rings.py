"""Microring and racetrack resonator components."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

from optodraw.core.ports import Port
from optodraw.core.transform import Vec3

from optodraw.components.onchip.base import ChipComponent, _generic_pdk_defaults, SILICON_EDGE
from optodraw.core.schematic_geometry import PhysicalSpec
from optodraw.components.onchip.geometry import (
    GOLD,
    GOLD_EDGE,
    N_DOPED,
    N_EDGE,
    P_DOPED,
    P_EDGE,
    TIN,
    TIN_EDGE,
    VIA,
    VIA_EDGE,
    _pad_children,
    _arc_band_points,
    _arc_band_polygons,
    _arc_points,
    _chip_box,
    _chip_circle,
    _chip_extruded_polygon,
    _chip_path_slab,
    _chip_polygon,
    _chip_polyline,
    _chip_segment_slab,
    _chip_slab,
    _cut_footprints,
    _pad_on_via,
    _polyline_outline,
    _polyline_outline_closed,
    _segment_outline,
    _translate_points,
    _vias,
)

HEATER_OVER_GUIDE = 0.55          # a heater drawn on its ring lets the guide under it show in 2D

@dataclass
class MicroringResonator(ChipComponent):
    component_type = "MicroringResonator"
    schematic_family = "microring"
    ring_radius: float = 10.0
    waveguide_width: float = 0.5
    gap: float = 0.2
    length_x: float = 4.0
    length_y: float = 0.6
    add_drop: bool = False
    with_heater: bool = False
    heater_width: float = 1.1
    heater_gap: float = 2.0
    heater_length: float | None = None
    heater_pad_size: float = 1.8

    def __init__(
        self,
        center=(0, 0),
        angle=0,
        ring_radius: float | None = None,
        waveguide_width: float | None = None,
        gap: float | None = None,
        length_x: float | None = None,
        length_y: float | None = None,
        add_drop: bool = False,
        with_heater: bool = False,
        heater_width: float = 1.1,
        heater_gap: float = 2.0,
        heater_length: float | None = None,
        heater_pad_size: float = 1.8,
        heater_resistance_ohm: float | None = None,
        **kwargs,
    ):
        self.heater_resistance_ohm = heater_resistance_ohm   # for the signal chain; None is its model default
        defaults = _generic_pdk_defaults()
        ring = defaults["ring"]
        strip = defaults["strip"]
        raw_ring_radius = float(ring["radius"] if ring_radius is None else ring_radius)
        raw_gap = float(ring["gap"] if gap is None else gap)
        self.waveguide_width = float(strip["width"] if waveguide_width is None else waveguide_width)
        self.length_x = float(ring["length_x"] if length_x is None else length_x)
        self.length_y = float(ring["length_y"] if length_y is None else length_y)
        self.add_drop = add_drop
        self.with_heater = with_heater
        self.heater_width = float(heater_width)
        self.heater_gap = float(heater_gap)
        self.heater_length = heater_length
        self.heater_pad_size = float(heater_pad_size)
        self._init_chip(center=center, angle=angle, **kwargs)
        self.ring_radius = raw_ring_radius
        self.gap = raw_gap

    def physical_spec(self) -> PhysicalSpec:
        return PhysicalSpec(
            device_family=self.schematic_family,
            values={
                "ring_radius": self.ring_radius,
                "gap": self.gap,
                "waveguide_width": self.waveguide_width,
                "length_x": self.length_x,
                "length_y": self.length_y,
                "thickness": self.chip_thickness,
            },
        )

    def symbol_1d(self) -> tuple[str, dict[str, Any]] | None:
        if self.component_type not in {"MicroringResonator", "PNMicroringModulator"}:
            return None
        params = {}
        if self.add_drop:
            params["drop"] = True
        if self.with_heater:
            params["heater"] = True
        if self.component_type == "PNMicroringModulator":
            params.update(radius=0.5, pn=True)              # the prebuilt modulator rings are drawn at half radius
        return "ring", params

    def _geom_ring_radius(self) -> float:
        return self._draw("ring_radius", self.ring_radius)

    def _geom_waveguide_width(self) -> float:
        return self._draw("waveguide_width", self.waveguide_width)

    def _geom_gap(self) -> float:
        # Drawn ring–bus coupling gap (schematic floor keeps it visible next to the
        # fattened ring track); physical gap stays in physical_spec/metadata.
        return self._draw("gap", self.gap)

    @property
    def bus_length(self) -> float:
        margin = max(self.length_x + self.waveguide_width * 4.0, self.length_y * 8.0, self.waveguide_width * 8.0)
        return 2.0 * (self.ring_radius + margin)

    @property
    def ring_center_y(self) -> float:
        return 0.0

    def _anchor_points(self) -> dict[str, tuple[float, float]]:
        """The ring's centre and the middle of each coupling gap, between the ring's outer edge and its bus."""

        reach = self.ring_radius + self._geom_waveguide_width() / 2.0 + self._geom_gap() / 2.0
        places = {"ring": (0.0, self.ring_center_y), "gap": (0.0, self.ring_center_y - reach)}
        if self.add_drop:
            places["drop_gap"] = (0.0, self.ring_center_y + reach)
        return places

    @property
    def bus_offset_y(self) -> float:
        # Drawn cross-section (fat track + visible gap) on a physical ring radius, so
        # the bus + ports sit just outside the (now-thick) ring band.
        return self.ring_radius + self._geom_gap() + self._geom_waveguide_width()

    @property
    def through_bus_y(self) -> float:
        return -self.bus_offset_y

    @property
    def drop_bus_y(self) -> float:
        return self.bus_offset_y

    def _heater_port_names(self) -> tuple[str, str]:
        return ("e1", "e2")

    @property
    def heater_radius(self) -> float:
        return self.ring_radius                           # the heater lies on the ring itself

    @property
    def _heater_opening_deg(self) -> float:
        """Where the heater arc opens and its leads leave: east, between the buses, on an add-drop ring; north,
        away from the bus, on an all-pass ring. No heater metal runs along or across a bus."""

        return 0.0 if self.add_drop else 90.0

    @property
    def heater_arc_span_deg(self) -> float:
        if self.heater_length is None:
            return 302.0
        circumference = 2.0 * math.pi * self.heater_radius
        return min(330.0, max(150.0, 360.0 * self.heater_length / max(circumference, 1e-6)))

    @property
    def heater_arc_angles(self) -> tuple[float, float]:
        gap_deg = 360.0 - self.heater_arc_span_deg
        start_deg = self._heater_opening_deg + gap_deg / 2.0
        return (start_deg, start_deg + self.heater_arc_span_deg)

    # heater_pad_x and heater_pad_y place the pads with the opening drawn DOWN (at 270 degrees);
    # _turn_from_opening_down turns that drawing to the real opening.
    @property
    def heater_pad_y(self) -> float:
        # heater_gap clear of the ring's outer edge
        return -(self.ring_radius + self._geom_waveguide_width() / 2.0 + self.heater_gap + self.heater_pad_size / 2.0)

    @property
    def heater_pad_x(self) -> float:
        # pads sit in line with the heater-arc ends (the leads run straight out)
        gap_half = math.radians((360.0 - self.heater_arc_span_deg) / 2.0)
        return max(self.heater_radius * math.sin(gap_half), self.heater_pad_size * 0.85)

    def _turn_from_opening_down(self, points: list[tuple[float, float]]) -> list[tuple[float, float]]:
        turn = math.radians(self._heater_opening_deg - 270.0)
        c, s = math.cos(turn), math.sin(turn)
        return [(x * c - y * s, x * s + y * c) for x, y in points]

    @property
    def cladding_size(self) -> float:
        return max(self.bus_length * 0.68, 2.0 * (self.heater_radius + self.heater_pad_size * 1.35))

    @property
    def heater_via_size(self) -> float:
        return max(self.heater_width * 0.7, 0.32)

    def _bus_polygon(self, y: float = 0.0) -> list[tuple[float, float]]:
        half = self.bus_length / 2.0
        wg = self._geom_waveguide_width()
        return _segment_outline((-half, y), (half, y), wg, wg)


    def loop_centerline(self) -> list[tuple[float, float]]:
        """The DRAWN ring loop centerline (the circle the light circulates on)."""

        draw = self._draw_variant() if hasattr(self, "_draw_variant") else self
        if draw is not self:
            return draw.loop_centerline()
        return _arc_points(0.0, self.ring_center_y, self.ring_radius, 0.0, 360.0, segments=64)

    def anim_behaviors(self) -> list[dict]:
        behaviors = [
            {"key": "state", "label": "Resonance", "options": [
                ["auto", "On resonance"], ["off", "Off resonance (light passes)"]]},
            {"key": "ring_coupling", "label": "Coupling regime", "options": [
                ["auto", "Physics default"], ["under", "Under-coupled"],
                ["critical", "Critically coupled"], ["over", "Over-coupled"]]},
            {"key": "channel", "label": "Channel", "options": [
                ["auto", "From geometry"], ["0.0", "Ch1 (red)"], ["0.2", "Ch2 (orange)"],
                ["0.4", "Ch3 (yellow-green)"], ["0.6", "Ch4 (green-blue)"],
                ["0.8", "Ch5 (blue)"], ["1.0", "Ch6 (violet)"]]},
        ]
        if getattr(self, "with_heater", False):
            behaviors.append({"key": "heater", "label": "Heater", "options": [
                ["auto", "On (thermo-optic tuning)"], ["off", "Off"]]})
        return behaviors


    def optical_paths(self, in_port: str) -> list[dict[str, Any]]:
        """Port-to-port system animation: bus -> coupling gap -> drawn loop ->
        through / drop ports (see _resonator_bus_loop_paths)."""

        draw = self._draw_variant() if hasattr(self, "_draw_variant") else self
        if draw is not self:
            draw.anim_params = self.anim_params  # behaviours ride along
            return draw.optical_paths(in_port)
        return _resonator_bus_loop_paths(self, in_port)


    def _ring_polygon(self) -> list[tuple[float, float]]:
        return _arc_band_points(
            0.0,
            self.ring_center_y,
            self.ring_radius - self._geom_waveguide_width() / 2.0,
            self.ring_radius + self._geom_waveguide_width() / 2.0,
            0.0,
            360.0,
            segments=96,
        )

    def _arc_anchor(self, radius: float, deg: float) -> tuple[float, float]:
        rad = math.radians(deg)
        return (radius * math.cos(rad), radius * math.sin(rad))

    def _heater_polygon(self) -> list[tuple[float, float]]:
        """The WHOLE heater as one closed outline: the arc around the ring, two
        straight leads that keep the FULL heater width until they reach the
        pads, and both pads (wider squares) — a single metal polygon."""

        start_deg, end_deg = (deg + 270.0 - self._heater_opening_deg for deg in self.heater_arc_angles)
        w2 = self.heater_width / 2.0
        r_in = self.heater_radius - w2
        r_out = self.heater_radius + w2
        s = self.heater_pad_size / 2.0
        px, py = self.heater_pad_x, self.heater_pad_y
        y_j = py + s  # pad top edge — where the leads land
        # arc-end corner heights (the leads join the arc with a tiny chamfer step)
        y_out = r_out * math.sin(math.radians(end_deg))
        y_in = r_in * math.sin(math.radians(end_deg))
        outer = _arc_points(0.0, 0.0, r_out, start_deg, end_deg, segments=84)
        inner = _arc_points(0.0, 0.0, r_in, end_deg, start_deg, segments=84)
        return self._turn_from_opening_down([
            *outer,                                          # around the ring, gap → gap
            (-px - w2, y_out), (-px - w2, y_j),              # left lead, outer edge down
            (-px - s, y_j), (-px - s, py - s),               # left pad, out + around
            (-px + s, py - s), (-px + s, y_j),
            (-px + w2, y_j), (-px + w2, y_in),               # left lead, inner edge up
            *inner,                                          # back along the inside
            (px - w2, y_in), (px - w2, y_j),                 # right lead, inner edge down
            (px - s, y_j), (px - s, py - s),                 # right pad, out + around
            (px + s, py - s), (px + s, y_j),
            (px + w2, y_j), (px + w2, y_out),                # right lead, outer edge up
        ])

    def heater_centerline(self) -> list[tuple[float, float]]:
        """The heater metal's SPINE — what the animation engine warms.

        Derived from the same numbers as :meth:`_heater_polygon`, so heat can
        never drift away from the metal that is drawn."""

        start_deg, end_deg = self.heater_arc_angles
        return _arc_points(0.0, 0.0, self.heater_radius, start_deg, end_deg, segments=48)

    def _heater_via_centers(self) -> list[tuple[float, float]]:
        # a via sits in the MIDDLE of each pad; e1's first: the upper pad of an add-drop ring, the west pad of an
        # all-pass ring, as in the 1D symbol
        return self._turn_from_opening_down([(self.heater_pad_x, self.heater_pad_y), (-self.heater_pad_x, self.heater_pad_y)])

    def _heater_children_2d(self) -> list[dict[str, Any]]:
        return [
            _chip_box(0.0, 0.0, self.cladding_size, self.cladding_size * 0.72, "#d8eef7", self.opacity * 0.12, stroke="#a7ccd9", stroke_width=0.05),
            _chip_polygon(self._heater_polygon(), fill="#d4af37", opacity=self.opacity * HEATER_OVER_GUIDE,
                          stroke="#8e7611", stroke_width=0.08),
            *[
                _chip_box(via_x, via_y, self.heater_via_size, self.heater_via_size, "#f08c6d", self.opacity, stroke="#8b5038", stroke_width=0.08)
                for via_x, via_y in self._heater_via_centers()
            ],
        ]

    def _heater_children_3d(self) -> dict[str, Any] | list[dict[str, Any]]:
        stack = self._draw_layer_stack()
        children = [
            _chip_extruded_polygon(self._heater_polygon(), stack["heater_height"], color="#d4af37",
                                   preset="gold", z_offset=stack["heater_z"]),
        ]
        # Heater terminals connect upward to pads, never downward into undoped silicon.
        lower_top = stack["heater_z"] + stack["heater_height"]
        for x, y in self._heater_via_centers():
            children += _pad_on_via(self.heater_pad_size, self.heater_pad_size, x, y, stack, below=lower_top,
                                    color=GOLD, via_color=VIA)
        return children


    def _optical_children_2d(self) -> list[dict[str, Any]]:
        # the ring's edges are two circles: a stroke round the annulus polygon drew a seam where it closes
        w2 = self._geom_waveguide_width() / 2.0
        children = [
            _chip_polygon(self._bus_polygon(self.through_bus_y), fill=self.color, opacity=self.opacity, stroke=SILICON_EDGE, stroke_width=0.08),
            _chip_polygon(self._ring_polygon(), fill=self.color, opacity=self.opacity, stroke="none", stroke_width=0.0),
            *[_chip_circle(0.0, self.ring_center_y, self.ring_radius + sign * w2, stroke=SILICON_EDGE, stroke_width=0.08,
                           fill="none", opacity=self.opacity) for sign in (1.0, -1.0)],
        ]
        if self.add_drop:
            children.append(
                _chip_polygon(self._bus_polygon(self.drop_bus_y), fill=self.color, opacity=self.opacity, stroke=SILICON_EDGE, stroke_width=0.08)
            )
        return children

    def _optical_children_3d(self) -> list[dict[str, Any]]:
        children = [
            _chip_slab(self.bus_length, self._geom_waveguide_width(), self._draw_thickness(), y=self.through_bus_y, **self._core()),
            _chip_extruded_polygon(self._ring_polygon(), self._draw_thickness(), **self._core()),
        ]
        if self.add_drop:
            children.append(
                _chip_slab(self.bus_length, self._geom_waveguide_width(), self._draw_thickness(), y=self.drop_bus_y, **self._core())
            )
        return children

    def ports(self) -> dict[str, Port]:
        half = self.bus_length / 2.0
        ports = {
            "o1": Port("o1", Vec3(-half, self.through_bus_y, 0), orientation_deg=180, width=self._draw("waveguide_width", self.waveguide_width)),
            "o2": Port("o2", Vec3(half, self.through_bus_y, 0), orientation_deg=0, width=self._draw("waveguide_width", self.waveguide_width)),
        }
        if self.add_drop:
            ports.update(
                {
                    "o3": Port("o3", Vec3(-half, self.drop_bus_y, 0), orientation_deg=180, width=self._draw("waveguide_width", self.waveguide_width)),
                    "o4": Port("o4", Vec3(half, self.drop_bus_y, 0), orientation_deg=0, width=self._draw("waveguide_width", self.waveguide_width)),
                }
            )
        if self.with_heater:
            for name, (x, y) in zip(self._heater_port_names(), self._heater_via_centers()):
                ports[name] = Port(name, Vec3(x, y, 0), orientation_deg=self._heater_opening_deg, width=self.heater_pad_size,
                                   kind="electrical")
        return ports

    def geometry_2d(self) -> dict[str, Any]:
        children = self._optical_children_2d()
        if self.with_heater:
            children.extend(self._heater_children_2d())
        return {"type": "group", "children": children}

    def geometry_3d(self) -> dict[str, Any]:
        children = self._optical_children_3d()
        if self.with_heater:
            children.extend(self._heater_children_3d())
        return self._on_the_stack(children)

    def physics_metadata(self) -> dict[str, Any]:
        from optodraw.core.guided import SILICON_STRIP_NEFF_STUB

        circumference = 2.0 * math.pi * self.ring_radius
        neff = SILICON_STRIP_NEFF_STUB
        wavelength_um = 1.55
        fsr_nm = (wavelength_um**2) / (neff * circumference) * 1000.0 if circumference > 0 else None
        return {
            "domain": "on_chip",
            "component": "microring",
            "ring_radius": self.ring_radius,
            "gap": self.gap,
            "fsr_nm": fsr_nm,
            "Q": None,
        }


@dataclass
class PNMicroringModulator(MicroringResonator):
    component_type = "PNMicroringModulator"
    contact_pad_size: float = 2.2

    def anim_behaviors(self) -> list[dict]:
        behaviors = super().anim_behaviors()
        behaviors.append({"key": "junction", "label": "PN junction", "options": [
            ["auto", "PN depletion drive"], ["pin", "PIN injection"], ["off", "Off"]]})
        return behaviors

    def __init__(
        self,
        center=(0, 0),
        angle=0,
        contact_pad_size: float = 2.2,
        add_drop: bool = False,
        with_heater: bool = True,
        heater_width: float = 1.1,
        heater_gap: float = 2.0,
        heater_length: float | None = None,
        heater_pad_size: float = 1.8,
        **kwargs,
    ):
        self.contact_pad_size = float(contact_pad_size)
        super().__init__(
            center=center,
            angle=angle,
            add_drop=add_drop,
            with_heater=with_heater,
            heater_width=heater_width,
            heater_gap=heater_gap,
            heater_length=heater_length,
            heater_pad_size=heater_pad_size,
            **kwargs,
        )

    # As in the 1D symbol: p inside and n outside the ring on one sector, the heater on its own
    # sector across the ring, every band cut clean, the bus coupling regions left free.
    _HEATER_SECTOR = (145.0, 215.0)

    def _pn_sectors(self) -> list[tuple[float, float]]:
        main = (-35.0, 35.0) if self.add_drop else (-35.0, 125.0)
        return [main] if self.with_heater else [main, self._HEATER_SECTOR]

    def _active_arc_ranges(self) -> list[tuple[float, float]]:
        return self._pn_sectors()

    @property
    def _w(self) -> float:
        return self._geom_waveguide_width()

    @property
    def _band(self) -> float:
        return max(self._w * 1.1, 2.4)                    # the width of each doped band

    @property
    def p_inner_radius(self) -> float:
        return self.ring_radius - self._w / 2.0 - self._band

    @property
    def p_outer_radius(self) -> float:
        return self.ring_radius - self._w / 2.0 + 0.25   # under the edge of the guide: the junction

    @property
    def n_inner_radius(self) -> float:
        return self.ring_radius + self._w / 2.0 - 0.25

    @property
    def n_outer_radius(self) -> float:
        return self.ring_radius + self._w / 2.0 + self._band

    @property
    def _p_contact_radius(self) -> float:
        return self.p_inner_radius + 0.45

    @property
    def _n_contact_radius(self) -> float:
        return self.n_outer_radius - 0.45

    @property
    def heater_radius(self) -> float:
        return self.ring_radius                           # the heater band lies across the ring, centred on it

    @property
    def _heater_radii(self) -> tuple[float, float]:
        return self.ring_radius - self._w / 2.0 - 0.8, self.ring_radius + self._w / 2.0 + 0.8

    def _doping_polygons(self) -> tuple[list[list[tuple[float, float]]], list[list[tuple[float, float]]]]:
        sectors = self._pn_sectors()
        return (
            _arc_band_polygons(0.0, 0.0, self.p_inner_radius, self.p_outer_radius, sectors, segments=72),
            _arc_band_polygons(0.0, 0.0, self.n_inner_radius, self.n_outer_radius, sectors, segments=72),
        )

    def _heavy_polygons(self) -> tuple[list[list[tuple[float, float]]], list[list[tuple[float, float]]]]:
        sectors = self._pn_sectors()                      # p++ and n++ at the band edges, under the contacts
        return (
            _arc_band_polygons(0.0, 0.0, self.p_inner_radius, self.p_inner_radius + 0.9, sectors, segments=72),
            _arc_band_polygons(0.0, 0.0, self.n_outer_radius - 0.9, self.n_outer_radius, sectors, segments=72),
        )

    def _contact_polygons(self) -> list[list[tuple[float, float]]]:
        trimmed = [(a + 6.0, b - 6.0) for a, b in self._pn_sectors()]
        return [*_arc_band_polygons(0.0, 0.0, self._p_contact_radius - 0.22, self._p_contact_radius + 0.22, trimmed, segments=60),
                *_arc_band_polygons(0.0, 0.0, self._n_contact_radius - 0.22, self._n_contact_radius + 0.22, trimmed, segments=60)]

    def _contact_via_centers(self) -> list[tuple[float, float]]:
        centers = []
        for a, b in self._pn_sectors():
            count = max(int((b - a) / 25.0), 2)
            for i in range(count):
                deg = a + 10.0 + (b - a - 20.0) * i / max(count - 1, 1)
                centers += [self._arc_anchor(self._p_contact_radius, deg), self._arc_anchor(self._n_contact_radius, deg)]
        return centers

    def _heater_band(self) -> list[tuple[float, float]]:
        r_in, r_out = self._heater_radii
        return _arc_band_points(0.0, 0.0, r_in, r_out, *self._HEATER_SECTOR, segments=36)

    def heater_centerline(self) -> list[tuple[float, float]]:
        return _arc_points(0.0, 0.0, self.ring_radius, *self._HEATER_SECTOR, segments=24)

    def _lead_paths(self) -> dict[str, list[tuple[float, float]]]:
        """Contact to pad. The p lead crosses the ring in the gap next to the pn sector."""

        a, b = self._pn_sectors()[0]
        out = self.n_outer_radius + 1.2
        ports = self._pad_positions()
        if self.add_drop:
            p_start = self._arc_anchor(self._p_contact_radius, 20.0)
            n_start = self._arc_anchor(self._n_contact_radius, -20.0)
            paths = {"e1": [p_start, (ports["e1"][0], p_start[1])], "e2": [n_start, (ports["e2"][0], n_start[1])]}
        else:
            cross = self._arc_anchor(out, b + 10.0)
            n_turn = self._arc_anchor(out, 45.0)
            paths = {
                "e1": [self._arc_anchor(self._p_contact_radius, b - 8.0), cross, (cross[0], ports["e1"][1])],
                "e2": [self._arc_anchor(self._n_contact_radius, 45.0), n_turn, (n_turn[0], ports["e2"][1])],
            }
        r_out = self._heater_radii[1]
        for name, deg in (("h2", self._HEATER_SECTOR[0]), ("h1", self._HEATER_SECTOR[1])):
            start = self._arc_anchor(r_out - 0.4, deg)
            paths[name] = [start, (ports[name][0], start[1])]
        return paths

    def _pad_positions(self) -> dict[str, tuple[float, float]]:
        pad, out = self.contact_pad_size, self.n_outer_radius + 1.2
        r_out = self._heater_radii[1]
        h_x = -(max(r_out, self.n_outer_radius if not self.with_heater else r_out) + self.heater_pad_size * 1.6 + 1.5)
        h_y = r_out * math.sin(math.radians(self._HEATER_SECTOR[0]))
        positions = {"h2": (h_x, h_y), "h1": (h_x, -h_y)}
        if self.add_drop:
            e_x = self.n_outer_radius + pad * 1.8
            positions["e1"] = (e_x, self._p_contact_radius * math.sin(math.radians(20.0)))
            positions["e2"] = (e_x, -self._n_contact_radius * math.sin(math.radians(20.0)))
        else:
            a, b = self._pn_sectors()[0]
            e_y = max(self.n_outer_radius, out * math.sin(math.radians(b + 10.0))) + pad * 1.2
            positions["e1"] = (self._arc_anchor(out, b + 10.0)[0], e_y)
            positions["e2"] = (self._arc_anchor(out, 45.0)[0], e_y)
        return positions

    @property
    def contact_pad_x(self) -> float:
        return abs(self._pad_positions()["e2"][0])

    @property
    def contact_pad_y(self) -> float:
        return self._pad_positions()["e2"][1]

    def ports(self) -> dict[str, Port]:
        half = self.bus_length / 2.0
        w = self._draw("waveguide_width", self.waveguide_width)
        ports = {
            "o1": Port("o1", Vec3(-half, self.through_bus_y, 0), orientation_deg=180, width=w),
            "o2": Port("o2", Vec3(half, self.through_bus_y, 0), orientation_deg=0, width=w),
        }
        if self.add_drop:
            ports["o3"] = Port("o3", Vec3(-half, self.drop_bus_y, 0), orientation_deg=180, width=w)
            ports["o4"] = Port("o4", Vec3(half, self.drop_bus_y, 0), orientation_deg=0, width=w)
        pads = self._pad_positions()
        facing = 0.0 if self.add_drop else 90.0
        for name in ("e1", "e2"):
            ports[name] = Port(name, Vec3(*pads[name], 0), orientation_deg=facing, width=self.contact_pad_size, kind="electrical")
        if self.with_heater:
            for name in ("h1", "h2"):
                ports[name] = Port(name, Vec3(*pads[name], 0), orientation_deg=180, width=self.heater_pad_size, kind="electrical")
        return ports

    def _electrode_children_2d(self) -> tuple[list[dict[str, Any]], float, float]:
        p_bands, n_bands = self._doping_polygons()
        pp, nn = self._heavy_polygons()
        lead_w = max(self._w * 0.3, 0.5)
        via = 0.55
        children = [
            *[_chip_polygon(band, fill=P_DOPED, opacity=self.opacity, stroke=P_EDGE, stroke_width=0.06) for band in p_bands],
            *[_chip_polygon(band, fill=N_DOPED, opacity=self.opacity, stroke=N_EDGE, stroke_width=0.06) for band in n_bands],
            *[_chip_polygon(band, fill="#e89a9a", opacity=self.opacity, stroke=P_EDGE, stroke_width=0.05) for band in pp],
            *[_chip_polygon(band, fill="#9dbbe8", opacity=self.opacity, stroke=N_EDGE, stroke_width=0.05) for band in nn],
        ]
        return children, lead_w, via

    def geometry_2d(self) -> dict[str, Any]:
        children, lead_w, via = self._electrode_children_2d()
        if self.with_heater:                                     # under the ring line, as in the 1D symbol
            children.append(_chip_polygon(self._heater_band(), fill=TIN, opacity=self.opacity, stroke=TIN_EDGE, stroke_width=0.06))
        children += self._optical_children_2d()                  # the ring over the doped bands and the heater
        children += [_chip_polygon(points, fill=GOLD, opacity=self.opacity, stroke=GOLD_EDGE, stroke_width=0.05)
                     for points in self._contact_polygons()]
        children += [_chip_box(x, y, via, via, VIA, self.opacity, stroke=VIA_EDGE, stroke_width=0.04)
                     for x, y in self._contact_via_centers()]
        paths, pads = self._lead_paths(), self._pad_positions()
        for name in ("e1", "e2"):
            children.append(_chip_polygon(_polyline_outline(paths[name], lead_w), fill=GOLD, opacity=self.opacity,
                                          stroke=GOLD_EDGE, stroke_width=0.05))
            children += _pad_children(*pads[name], self.contact_pad_size, self.contact_pad_size, self.opacity)
        if self.with_heater:
            for name in ("h1", "h2"):
                children.append(_chip_polygon(_polyline_outline(paths[name], self.heater_width), fill=TIN, opacity=self.opacity,
                                              stroke=TIN_EDGE, stroke_width=0.06))
                children += _pad_children(*pads[name], self.heater_pad_size, self.heater_pad_size, self.opacity)
                children.append(_chip_box(*pads[name], via, via, VIA, self.opacity, stroke=VIA_EDGE, stroke_width=0.04))
        return {"type": "group", "children": children}

    def geometry_3d(self) -> dict[str, Any]:
        stack = self._draw_layer_stack()
        p_bands, n_bands = self._doping_polygons()
        pp_bands, nn_bands = self._heavy_polygons()
        # Ordinary and heavy implants occupy adjacent regions of the same slab.
        p_bands = _arc_band_polygons(0.0, 0.0, self.p_inner_radius + 0.9,
                                    self.p_outer_radius, self._pn_sectors(), segments=72)
        n_bands = _arc_band_polygons(0.0, 0.0, self.n_inner_radius,
                                    self.n_outer_radius - 0.9, self._pn_sectors(), segments=72)
        # Replace the neutral ring with disjoint P/N core sectors; keep the buses.
        children = [part for part in self._optical_children_3d() if part.get("shape") != "extruded_polygon"]
        sectors = self._pn_sectors()
        angles = sorted({0.0, 360.0, *(angle % 360.0 for sector in sectors for angle in sector)})
        inner, outer = self.ring_radius - self._w / 2, self.ring_radius + self._w / 2
        for start, end in zip(angles, angles[1:]):
            middle = (start + end) / 2
            doped = any((middle - a) % 360.0 < b - a for a, b in sectors)
            regions = [(inner, self.ring_radius, P_DOPED), (self.ring_radius, outer, N_DOPED)] if doped else [(inner, outer, self.color)]
            for r0, r1, color in regions:
                look = self._core() if color == self.color else {"color": color, "preset": "silicon", "z_offset": stack["core_z"]}
                children.extend(_chip_extruded_polygon(points, self._draw_thickness(), **look)
                                for points in _arc_band_polygons(0.0, 0.0, r0, r1, [(start, end)], segments=72))
        children += [_chip_extruded_polygon(b, stack["implant_height"], color=P_DOPED, preset="silicon", z_offset=stack["implant_z"]) for b in p_bands]
        children += [_chip_extruded_polygon(b, stack["implant_height"], color=N_DOPED, preset="silicon", z_offset=stack["implant_z"]) for b in n_bands]
        children += [_chip_extruded_polygon(b, stack["metal_height"], color=GOLD, preset="gold", z_offset=stack["metal_z"]) for b in self._contact_polygons()]
        children += [_chip_extruded_polygon(b, stack["implant_height"], color="#e89a9a", preset="silicon",
                                            z_offset=stack["implant_z"]) for b in pp_bands]
        children += [_chip_extruded_polygon(b, stack["implant_height"], color="#9dbbe8", preset="silicon",
                                            z_offset=stack["implant_z"]) for b in nn_bands]
        overlap = min(stack["metal_height"] * 0.02, 0.005)
        if stack["metal_z"] - stack["via_z"] + overlap <= 0:
            raise ValueError("Ring modulator via must start below its routing metal")
        for x, y in self._contact_via_centers():
            # Fit the square landing inside the narrow curved metal strip.
            children.append(_chip_slab(0.25, 0.25, stack["contact_height"], x=x, y=y,
                                       color="#777b82", preset="tungsten", z_offset=stack["contact_z"]))
        children += _vias(0.25, self._contact_via_centers(), stack, into=overlap)
        paths, pads = self._lead_paths(), self._pad_positions()
        lead_w = max(self._w * 0.3, 0.5)
        for name in ("e1", "e2"):
            children.append(_chip_extruded_polygon(_polyline_outline(paths[name], lead_w), stack["metal_height"], color=GOLD, preset="gold", z_offset=stack["metal_z"]))
            children += _pad_on_via(self.contact_pad_size, self.contact_pad_size, pads[name][0], pads[name][1], stack,
                                    below=stack["metal_z"] + stack["metal_height"], color=GOLD, via_color=VIA)
        if self.with_heater:
            heater = [_chip_extruded_polygon(self._heater_band(), stack["heater_height"], color=TIN, preset="titanium_nitride", z_offset=stack["heater_z"])]
            landings: list[dict[str, Any]] = []
            for name in ("h1", "h2"):
                heater.append(_chip_extruded_polygon(_polyline_outline(paths[name], self.heater_width), stack["heater_height"], color=TIN, preset="titanium_nitride", z_offset=stack["heater_z"]))
                landings += _pad_on_via(self.heater_pad_size, self.heater_pad_size, pads[name][0], pads[name][1], stack,
                                        below=stack["heater_z"] + stack["heater_height"], color=GOLD, via_color=VIA,
                                        landing=(TIN, "titanium_nitride"))
            gold = [solid for solid in landings if solid["material"].get("preset") == "gold"]
            children += [*_cut_footprints(heater, gold), *landings]     # a pad on the heater's own level owns its patch
        return self._on_the_stack(children)

    def physics_metadata(self) -> dict[str, Any]:
        metadata = super().physics_metadata()
        metadata.update(
            {
                "component": "pn_microring_modulator",
                "modulation_mechanism": "pn_depletion",
                "bias_voltage_v": None,
            }
        )
        return metadata


@dataclass
class RacetrackResonator(ChipComponent):
    component_type = "RacetrackResonator"
    schematic_family = "racetrack"
    bend_radius: float = 10.0
    coupling_length: float = 18.0
    waveguide_width: float = 0.5
    gap: float = 0.2
    length_y: float = 0.0
    add_drop: bool = False
    with_heater: bool = False
    heater_width: float = 1.0
    heater_pad_size: float = 1.6

    def __init__(
        self,
        center=(0, 0),
        angle=0,
        bend_radius: float | None = None,
        coupling_length=18.0,
        waveguide_width: float | None = None,
        gap: float | None = None,
        length_y=0.0,
        add_drop: bool = False,
        with_heater: bool = False,
        heater_width: float = 1.0,
        heater_pad_size: float = 1.6,
        **kwargs,
    ):
        defaults = _generic_pdk_defaults()
        strip = defaults["strip"]
        raw_bend_radius = float(strip["radius"] if bend_radius is None else bend_radius)
        raw_gap = float(defaults["ring"]["gap"] if gap is None else gap)
        self.coupling_length = float(coupling_length)
        self.waveguide_width = float(strip["width"] if waveguide_width is None else waveguide_width)
        self.length_y = float(length_y)
        self.add_drop = add_drop
        self.with_heater = with_heater
        self.heater_width = float(heater_width)
        self.heater_pad_size = float(heater_pad_size)
        self._init_chip(center=center, angle=angle, **kwargs)
        self.bend_radius = raw_bend_radius
        self.gap = raw_gap

    def physical_spec(self) -> PhysicalSpec:
        return PhysicalSpec(
            device_family=self.schematic_family,
            values={
                "bend_radius": self.bend_radius,
                "coupling_length": self.coupling_length,
                "bus_length": self.bus_length,
                "waveguide_width": self.waveguide_width,
                "gap": self.gap,
                "length_y": self.length_y,
                "heater_width": self.heater_width,
                "heater_pad_size": self.heater_pad_size,
                "add_drop": self.add_drop,
                "with_heater": self.with_heater,
                "thickness": self.chip_thickness,
            },
        )

    def _draw_variant(self) -> RacetrackResonator:
        if self.render_physical:
            return self
        return RacetrackResonator(
            bend_radius=self._draw("bend_radius", self.bend_radius),
            coupling_length=self._draw("coupling_length", self.coupling_length),
            waveguide_width=self._draw("waveguide_width", self.waveguide_width),
            gap=self._draw("gap", self.gap),
            length_y=self._draw("length_y", self.length_y),
            add_drop=self.add_drop,
            with_heater=self.with_heater,
            heater_width=self.heater_width,
            heater_pad_size=self.heater_pad_size,
            **self._draw_variant_kwargs(),
        )

    @property
    def bus_length(self) -> float:
        return self.coupling_length + 2 * self.bend_radius + 6.0

    @property
    def ring_bottom_y(self) -> float:
        return self.gap + self.waveguide_width

    @property
    def ring_top_y(self) -> float:
        return self.ring_bottom_y + 2.0 * self.bend_radius + self.length_y

    @property
    def drop_bus_y(self) -> float:
        return self.ring_top_y + self.gap + self.waveguide_width

    def _heater_port_names(self) -> tuple[str, str]:
        return ("e1", "e2")

    def symbol_1d(self) -> tuple[str, dict[str, Any]]:
        """The racetrack pic with the buses and the strips this part draws, so its 1D ports are its ports."""

        return "racetrack", {key: True for key, on in (("drop", self.add_drop), ("heater", self.with_heater)) if on}

    #: the heater opens on the east bends, this far each side of east; its leads run east from the opening,
    #: between the buses, so no heater metal runs along or across a bus
    _HEATER_OPENING_DEG = 42.0

    def _heater_pads(self) -> list[tuple[float, float]]:
        """The pad centres, e1 (upper) then e2 (lower): east of the racetrack, level with the heater's ends."""

        x = self.side_straight_x + self.waveguide_width / 2.0 + 0.6 + self.heater_pad_size / 2.0
        rise = self.bend_radius * math.sin(math.radians(self._HEATER_OPENING_DEG))
        return [(x, self.ring_top_y - self.bend_radius + rise), (x, self.ring_bottom_y + self.bend_radius - rise)]

    @property
    def left_bend_center_x(self) -> float:
        return -(self.coupling_length / 2.0)

    @property
    def right_bend_center_x(self) -> float:
        return self.coupling_length / 2.0

    @property
    def vertical_center_y(self) -> float:
        return self.ring_bottom_y + self.bend_radius + self.length_y / 2.0

    @property
    def side_straight_x(self) -> float:
        return self.coupling_length / 2.0 + self.bend_radius

    def _ring_arc_polygons(self) -> list[list[tuple[float, float]]]:
        inner_radius = self.bend_radius - self.waveguide_width / 2.0
        outer_radius = self.bend_radius + self.waveguide_width / 2.0
        return [
            _arc_band_points(self.left_bend_center_x, self.ring_bottom_y + self.bend_radius, inner_radius, outer_radius, 180.0, 270.0, segments=36),
            _arc_band_points(self.left_bend_center_x, self.ring_top_y - self.bend_radius, inner_radius, outer_radius, 90.0, 180.0, segments=36),
            _arc_band_points(self.right_bend_center_x, self.ring_bottom_y + self.bend_radius, inner_radius, outer_radius, -90.0, 0.0, segments=36),
            _arc_band_points(self.right_bend_center_x, self.ring_top_y - self.bend_radius, inner_radius, outer_radius, 0.0, 90.0, segments=36),
        ]

    def _ring_children_2d(self) -> list[dict[str, Any]]:
        return [
            _chip_polyline(
                self._ring_path_points(),
                stroke=self.color,
                stroke_width=self.waveguide_width,
                opacity=self.opacity,
                closed=True,
            )
        ]

    def _ring_children_3d(self) -> list[dict[str, Any]]:
        points = self._ring_path_points()
        children: list[dict[str, Any]] = []
        for index, start in enumerate(points):
            end = points[(index + 1) % len(points)]
            children.append(
                _chip_segment_slab(
                    start,
                    end,
                    self.waveguide_width,
                    self.waveguide_width,
                    self._draw_thickness(),
                    **self._core(),
                )
            )
        return children

    def heater_centerline(self) -> list[tuple[float, float]]:
        """The heater's spine: on the racetrack itself, round the whole loop but the east opening."""

        r, g, cx = self.bend_radius, self._HEATER_OPENING_DEG, self.coupling_length / 2.0
        cy_top, cy_bot = self.ring_top_y - r, self.ring_bottom_y + r
        return _dedupe_points([
            *_arc_points(cx, cy_top, r, g, 90.0, segments=20),
            *_arc_points(-cx, cy_top, r, 90.0, 180.0, segments=26),
            *_arc_points(-cx, cy_bot, r, 180.0, 270.0, segments=26),
            *_arc_points(cx, cy_bot, r, 270.0, 360.0 - g, segments=20),
        ])

    def _heater_polygon(self) -> list[tuple[float, float]]:
        """The heater and its two leads as one outline: from each end of the heater a lead runs east to its pad."""

        (x, y1), (_, y2) = self._heater_pads()
        edge = x - self.heater_pad_size / 2.0
        return _polyline_outline([(edge, y1), *self.heater_centerline(), (edge, y2)], self.heater_width)

    def _heater_pad_polygons(self) -> list[list[tuple[float, float]]]:
        s = self.heater_pad_size / 2.0
        return [[(x - s, y - s), (x + s, y - s), (x + s, y + s), (x - s, y + s)] for x, y in self._heater_pads()]

    def ports(self) -> dict[str, Port]:
        draw = self._draw_variant()
        if draw is not self:
            return draw.ports()
        half = self.bus_length / 2.0
        ports = {
            "o1": Port("o1", Vec3(-half, 0, 0), orientation_deg=180, width=self._draw("waveguide_width", self.waveguide_width)),
            "o2": Port("o2", Vec3(half, 0, 0), orientation_deg=0, width=self._draw("waveguide_width", self.waveguide_width)),
        }
        if self.add_drop:
            ports.update(
                {
                    "o3": Port("o3", Vec3(-half, self.drop_bus_y, 0), orientation_deg=180, width=self._draw("waveguide_width", self.waveguide_width)),
                    "o4": Port("o4", Vec3(half, self.drop_bus_y, 0), orientation_deg=0, width=self._draw("waveguide_width", self.waveguide_width)),
                }
            )
        if self.with_heater:
            for name, (x, y) in zip(self._heater_port_names(), self._heater_pads()):
                ports[name] = Port(name, Vec3(x, y, 0), orientation_deg=0, width=self.heater_pad_size, kind="electrical")
        return ports

    def _ring_path_points(self) -> list[tuple[float, float]]:
        half = self.coupling_length / 2.0
        right_lower_arc = _arc_points(self.right_bend_center_x, self.ring_bottom_y + self.bend_radius, self.bend_radius, -90.0, 0.0, segments=14)
        right_upper_arc = _arc_points(self.right_bend_center_x, self.ring_top_y - self.bend_radius, self.bend_radius, 0.0, 90.0, segments=14)
        left_upper_arc = _arc_points(self.left_bend_center_x, self.ring_top_y - self.bend_radius, self.bend_radius, 90.0, 180.0, segments=14)
        left_lower_arc = _arc_points(self.left_bend_center_x, self.ring_bottom_y + self.bend_radius, self.bend_radius, 180.0, 270.0, segments=14)

        points: list[tuple[float, float]] = [(-half, self.ring_bottom_y), (half, self.ring_bottom_y)]
        points.extend(right_lower_arc[1:])
        if self.length_y > 1e-9:
            points.append((self.side_straight_x, self.ring_top_y - self.bend_radius))
        points.extend(right_upper_arc[1:])
        points.append((-half, self.ring_top_y))
        points.extend(left_upper_arc[1:])
        if self.length_y > 1e-9:
            points.append((-self.side_straight_x, self.ring_bottom_y + self.bend_radius))
        points.extend(left_lower_arc[1:])

        if points and math.hypot(points[-1][0] - points[0][0], points[-1][1] - points[0][1]) <= 1e-9:
            points.pop()
        return points

    def _ring_polygon(self) -> list[tuple[float, float]]:
        return _polyline_outline_closed(self._ring_path_points(), self.waveguide_width)

    def loop_centerline(self) -> list[tuple[float, float]]:
        """The DRAWN racetrack loop centerline — straights + bends, not a circle."""

        draw = self._draw_variant() if hasattr(self, "_draw_variant") else self
        if draw is not self:
            return draw.loop_centerline()
        points = list(self._ring_path_points())
        if points:
            points.append(points[0])  # close the loop
        return points

    def anim_behaviors(self) -> list[dict]:
        behaviors = [
            {"key": "state", "label": "Resonance", "options": [
                ["auto", "On resonance"], ["off", "Off resonance (light passes)"]]},
            {"key": "ring_coupling", "label": "Coupling regime", "options": [
                ["auto", "Physics default"], ["under", "Under-coupled"],
                ["critical", "Critically coupled"], ["over", "Over-coupled"]]},
            {"key": "channel", "label": "Channel", "options": [
                ["auto", "From geometry"], ["0.0", "Ch1 (red)"], ["0.2", "Ch2 (orange)"],
                ["0.4", "Ch3 (yellow-green)"], ["0.6", "Ch4 (green-blue)"],
                ["0.8", "Ch5 (blue)"], ["1.0", "Ch6 (violet)"]]},
        ]
        if getattr(self, "with_heater", False):
            behaviors.append({"key": "heater", "label": "Heater", "options": [
                ["auto", "On (thermo-optic tuning)"], ["off", "Off"]]})
        return behaviors


    def optical_paths(self, in_port: str) -> list[dict[str, Any]]:
        """Port-to-port system animation: bus -> coupling gap -> drawn loop ->
        through / drop ports (see _resonator_bus_loop_paths)."""

        draw = self._draw_variant() if hasattr(self, "_draw_variant") else self
        if draw is not self:
            draw.anim_params = self.anim_params  # behaviours ride along
            return draw.optical_paths(in_port)
        return _resonator_bus_loop_paths(self, in_port)



    def geometry_2d(self) -> dict[str, Any]:
        draw = self._draw_variant()
        if draw is not self:
            return draw.geometry_2d()

        children = [
            _chip_polygon(_segment_outline((-self.bus_length / 2.0, 0.0), (self.bus_length / 2.0, 0.0), self.waveguide_width, self.waveguide_width), fill=self.color, opacity=self.opacity, stroke=SILICON_EDGE, stroke_width=0.08),
            *self._ring_children_2d(),
        ]
        if self.add_drop:
            children.append(
                _chip_polygon(_segment_outline((-self.bus_length / 2.0, self.drop_bus_y), (self.bus_length / 2.0, self.drop_bus_y), self.waveguide_width, self.waveguide_width), fill=self.color, opacity=self.opacity, stroke=SILICON_EDGE, stroke_width=0.08)
            )
        if self.with_heater:
            via_size = max(self.heater_width * 0.76, 0.3)
            children += [_chip_polygon(points, fill="#d4af37", opacity=self.opacity * (HEATER_OVER_GUIDE if k == 0 else 1.0),
                                       stroke="#8e7611", stroke_width=0.08)
                         for k, points in enumerate((self._heater_polygon(), *self._heater_pad_polygons()))]
            children += [_chip_box(x, y, via_size, via_size, "#f08c6d", self.opacity, stroke="#8b5038", stroke_width=0.08)
                         for x, y in self._heater_pads()]
        return {"type": "group", "children": children}

    def geometry_3d(self) -> dict[str, Any]:
        draw = self._draw_variant()
        if draw is not self:
            return draw.geometry_3d()

        children = [
            _chip_slab(self.bus_length, self.waveguide_width, self._draw_thickness(), **self._core()),
            *self._ring_children_3d(),
        ]
        if self.add_drop:
            children.append(
                _chip_slab(self.bus_length, self.waveguide_width, self._draw_thickness(), y=self.drop_bus_y, **self._core())
            )
        if self.with_heater:
            stack = self._draw_layer_stack()
            children += [_chip_extruded_polygon(points, stack["heater_height"], color="#d4af37", preset="gold", z_offset=stack["heater_z"])
                         for points in (self._heater_polygon(), *self._heater_pad_polygons())]
        return self._on_the_stack(children)


@dataclass
class RacetrackModulator(RacetrackResonator):
    component_type = "RacetrackModulator"
    schematic_family = "racetrack_modulator"
    electrode_length: float | None = None
    contact_pad_size: float = 1.9

    def __init__(
        self,
        center=(0, 0),
        angle=0,
        electrode_length: float | None = None,
        contact_pad_size: float = 1.9,
        add_drop: bool = True,
        **kwargs,
    ):
        self.electrode_length = electrode_length
        self.contact_pad_size = float(contact_pad_size)
        kwargs.setdefault("with_heater", True)
        super().__init__(center=center, angle=angle, add_drop=add_drop, **kwargs)

    def _heater_port_names(self) -> tuple[str, str]:
        return ("h1", "h2")  # the PN contact pads own e1/e2

    def symbol_1d(self) -> tuple[str, dict[str, Any]]:
        name, params = super().symbol_1d()
        return name, {**params, "pn": True}

    def physical_spec(self) -> PhysicalSpec:
        values = dict(super().physical_spec().values)
        values.update(
            {
                "electrode_length": self.electrode_length or 0.0,
                "active_length": self.active_length,
                "junction_length": self.junction_length,
                "active_rib_width": self.active_rib_width,
                "doping_width": self.doping_width,
                "contact_pad_size": self.contact_pad_size,
            }
        )
        return PhysicalSpec(device_family=self.schematic_family, values=values)

    def _draw_variant(self) -> RacetrackModulator:
        if self.render_physical:
            return self
        return RacetrackModulator(
            bend_radius=self._draw("bend_radius", self.bend_radius),
            coupling_length=self._draw("coupling_length", self.coupling_length),
            waveguide_width=self._draw("waveguide_width", self.waveguide_width),
            gap=self._draw("gap", self.gap),
            length_y=self._draw("length_y", self.length_y),
            add_drop=self.add_drop,
            with_heater=self.with_heater,
            heater_width=self.heater_width,
            heater_pad_size=self.heater_pad_size,
            electrode_length=self._draw("active_length", self.active_length),
            contact_pad_size=self.contact_pad_size,
            **self._draw_variant_kwargs(),
        )

    @property
    def coupler_clearance(self) -> float:
        return max(self.waveguide_width * 6.0, 2.5) if self.add_drop else max(self.waveguide_width * 3.0, 1.2)

    @property
    def active_length(self) -> float:
        if self.add_drop:
            return 0.0
        available_length = self.coupling_length
        if self.electrode_length is not None:
            return max(min(available_length, float(self.electrode_length)), self.waveguide_width * 6.0)
        return available_length

    @property
    def junction_length(self) -> float:
        """Length of the PN regions drawn on bends, sides, and the active top arm."""

        return 2.0 * math.pi * self.bend_radius + 2.0 * max(self.length_y, 0.0) + self.active_length

    @property
    def active_rib_width(self) -> float:
        return max(self.waveguide_width * 3.4, 1.6)

    @property
    def doping_width(self) -> float:
        return max(self.waveguide_width * 0.54, 0.24)

    # As in the 1D symbol: p inside and n outside on the left bend, the heater across the guide on
    # the right bend, each band cut clean so the bus coupling straights stay free.
    _PN_SECTOR = (125.0, 235.0)
    _HEATER_SECTOR = (-55.0, 55.0)

    @property
    def _band(self) -> float:
        return max(self.waveguide_width * 1.8, 2.0)

    def _end_path(self, radius: float, start: float, end: float) -> list[tuple[float, float]]:
        """Points at ``radius`` round one end of the racetrack (left for angles past 90 degrees)."""

        cx = (-1.0 if math.cos(math.radians((start + end) / 2.0)) < 0 else 1.0) * self.coupling_length / 2.0
        cy_top, cy_bot = self.ring_top_y - self.bend_radius, self.ring_bottom_y + self.bend_radius
        points = []
        for i in range(41):
            a = math.radians(start + (end - start) * i / 40.0)
            cy = cy_top if math.sin(a) >= 0.0 else cy_bot
            points.append((cx + radius * math.cos(a), cy + radius * math.sin(a)))
        return points

    def _end_band(self, sector: tuple[float, float], r0: float, r1: float) -> list[tuple[float, float]]:
        radius = self.bend_radius
        return self._end_path(radius + r1, *sector) + self._end_path(radius + r0, sector[1], sector[0])

    def _offsets(self) -> dict[str, tuple[float, float]]:
        w2, b = self.waveguide_width / 2.0, self._band
        return {"p": (-w2 - b, -w2 + 0.2), "n": (w2 - 0.2, w2 + b), "pp": (-w2 - b, -w2 - b + 0.7),
                "nn": (w2 + b - 0.7, w2 + b), "heater": (-w2 - 0.6, w2 + 0.6),
                "p_contact": (-w2 - b + 0.17, -w2 - b + 0.53), "n_contact": (w2 + b - 0.53, w2 + b - 0.17)}

    def _doping_polygons(self) -> tuple[list[list[tuple[float, float]]], list[list[tuple[float, float]]]]:
        o = self._offsets()
        return [self._end_band(self._PN_SECTOR, *o["p"])], [self._end_band(self._PN_SECTOR, *o["n"])]

    def _heater_band(self) -> list[tuple[float, float]]:
        return self._end_band(self._HEATER_SECTOR, *self._offsets()["heater"])

    def heater_centerline(self) -> list[tuple[float, float]]:
        draw = self._draw_variant()
        if draw is not self:
            return draw.heater_centerline()
        return self._end_path(self.bend_radius, *self._HEATER_SECTOR)

    def _anchor(self, offset: float, deg: float) -> tuple[float, float]:
        return self._end_path(self.bend_radius + offset, deg, deg)[0]

    def _pads(self) -> dict[str, tuple[float, float]]:
        o, pad = self._offsets(), self.contact_pad_size
        e_x = -(self.coupling_length / 2.0 + self.bend_radius + o["n"][1] + pad * 1.8)
        h_x = self.coupling_length / 2.0 + self.bend_radius + o["heater"][1] + self.heater_pad_size * 1.8 + 1.0
        return {
            "e1": (e_x, self._anchor(sum(o["p_contact"]) / 2.0, 205.0)[1]),
            "e2": (e_x, self._anchor(sum(o["n_contact"]) / 2.0, 160.0)[1]),
            "h1": (h_x, self._anchor(o["heater"][1] - 0.3, -55.0)[1]),
            "h2": (h_x, self._anchor(o["heater"][1] - 0.3, 55.0)[1]),
        }

    def _lead_paths(self) -> dict[str, list[tuple[float, float]]]:
        o, pads = self._offsets(), self._pads()
        starts = {"e1": self._anchor(sum(o["p_contact"]) / 2.0, 205.0), "e2": self._anchor(sum(o["n_contact"]) / 2.0, 160.0),
                  "h1": self._anchor(o["heater"][1] - 0.3, -55.0), "h2": self._anchor(o["heater"][1] - 0.3, 55.0)}
        return {name: [start, (pads[name][0], start[1])] for name, start in starts.items()}

    def _via_centers(self) -> list[tuple[float, float]]:
        o = self._offsets()
        return [self._anchor(sum(o[key]) / 2.0, deg) for key in ("p_contact", "n_contact") for deg in (140.0, 165.0, 195.0, 220.0)]

    def ports(self) -> dict[str, Port]:
        draw = self._draw_variant()
        if draw is not self:
            return draw.ports()
        half, w = self.bus_length / 2.0, self.waveguide_width
        ports = {"o1": Port("o1", Vec3(-half, 0, 0), orientation_deg=180, width=w),
                 "o2": Port("o2", Vec3(half, 0, 0), orientation_deg=0, width=w)}
        if self.add_drop:
            ports["o3"] = Port("o3", Vec3(-half, self.drop_bus_y, 0), orientation_deg=180, width=w)
            ports["o4"] = Port("o4", Vec3(half, self.drop_bus_y, 0), orientation_deg=0, width=w)
        pads = self._pads()
        for name in ("e1", "e2"):
            ports[name] = Port(name, Vec3(*pads[name], 0), orientation_deg=180, width=self.contact_pad_size, kind="electrical")
        if self.with_heater:
            for name in ("h1", "h2"):
                ports[name] = Port(name, Vec3(*pads[name], 0), orientation_deg=0, width=self.heater_pad_size, kind="electrical")
        return ports

    def _optical_children_2d(self) -> list[dict[str, Any]]:
        children = [
            _chip_polygon(_segment_outline((-self.bus_length / 2.0, 0.0), (self.bus_length / 2.0, 0.0), self.waveguide_width, self.waveguide_width),
                          fill=self.color, opacity=self.opacity, stroke=SILICON_EDGE, stroke_width=0.08),
            *self._ring_children_2d(),
        ]
        if self.add_drop:
            children.append(_chip_polygon(_segment_outline((-self.bus_length / 2.0, self.drop_bus_y), (self.bus_length / 2.0, self.drop_bus_y),
                                                           self.waveguide_width, self.waveguide_width),
                                          fill=self.color, opacity=self.opacity, stroke=SILICON_EDGE, stroke_width=0.08))
        return children

    def geometry_2d(self) -> dict[str, Any]:
        draw = self._draw_variant()
        if draw is not self:
            return draw.geometry_2d()
        o, op = self._offsets(), self.opacity
        trimmed = (self._PN_SECTOR[0] + 6.0, self._PN_SECTOR[1] - 6.0)
        (p_band,), (n_band,) = self._doping_polygons()
        children = [
            _chip_polygon(p_band, fill=P_DOPED, opacity=op, stroke=P_EDGE, stroke_width=0.06),
            _chip_polygon(n_band, fill=N_DOPED, opacity=op, stroke=N_EDGE, stroke_width=0.06),
            _chip_polygon(self._end_band(self._PN_SECTOR, *o["pp"]), fill="#e89a9a", opacity=op, stroke=P_EDGE, stroke_width=0.05),
            _chip_polygon(self._end_band(self._PN_SECTOR, *o["nn"]), fill="#9dbbe8", opacity=op, stroke=N_EDGE, stroke_width=0.05),
        ]
        if self.with_heater:                                     # under the ring line, as in the 1D symbol
            children.append(_chip_polygon(self._heater_band(), fill=TIN, opacity=op, stroke=TIN_EDGE, stroke_width=0.06))
        children += self._optical_children_2d()
        children += [_chip_polygon(self._end_band(trimmed, *o[key]), fill=GOLD, opacity=op, stroke=GOLD_EDGE, stroke_width=0.05)
                     for key in ("p_contact", "n_contact")]
        children += [_chip_box(x, y, 0.5, 0.5, VIA, op, stroke=VIA_EDGE, stroke_width=0.04) for x, y in self._via_centers()]
        paths, pads = self._lead_paths(), self._pads()
        lead_w = max(self.waveguide_width * 0.45, 0.5)
        for name in ("e1", "e2"):
            children.append(_chip_polygon(_polyline_outline(paths[name], lead_w), fill=GOLD, opacity=op, stroke=GOLD_EDGE, stroke_width=0.05))
            children += _pad_children(*pads[name], self.contact_pad_size, self.contact_pad_size, op)
        if self.with_heater:
            for name in ("h1", "h2"):
                children.append(_chip_polygon(_polyline_outline(paths[name], self.heater_width), fill=TIN, opacity=op, stroke=TIN_EDGE, stroke_width=0.06))
                children += _pad_children(*pads[name], self.heater_pad_size, self.heater_pad_size, op)
        return {"type": "group", "children": children}

    def _ring_children_3d(self) -> list[dict[str, Any]]:
        points = self._ring_path_points()
        children, doped = [], []
        cx = -self.coupling_length / 2.0
        for index, a in enumerate(points):
            b = points[(index + 1) % len(points)]
            mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
            cy = self.ring_top_y - self.bend_radius if my >= (self.ring_top_y + self.ring_bottom_y) / 2 else self.ring_bottom_y + self.bend_radius
            angle = math.degrees(math.atan2(my - cy, mx - cx)) % 360
            active = mx < cx and self._PN_SECTOR[0] <= angle <= self._PN_SECTOR[1]
            dx, dy = b[0] - a[0], b[1] - a[1]
            length = math.hypot(dx, dy)
            if length <= 1e-12:
                continue
            if not active:
                children.append(_chip_segment_slab(a, b, self.waveguide_width, self.waveguide_width,
                                                   self._draw_thickness(), **self._core()))
                continue
            nx, ny = -dy / length, dx / length
            if nx * (mx - cx) + ny * (my - cy) < 0:
                nx, ny = -nx, -ny
            for direction, color in ((-1, P_DOPED), (1, N_DOPED)):
                shift = direction * self.waveguide_width / 4
                aa, bb = (a[0] + nx * shift, a[1] + ny * shift), (b[0] + nx * shift, b[1] + ny * shift)
                doped.append(_chip_segment_slab(aa, bb, self.waveguide_width / 2, self.waveguide_width / 2,
                                                self._draw_thickness(), color=color, preset="silicon"))
        return [*_cut_footprints(children, doped), *doped]       # where the segments meet, the doped one owns the joint

    def geometry_3d(self) -> dict[str, Any]:
        draw = self._draw_variant()
        if draw is not self:
            return draw.geometry_3d()
        stack = self._draw_layer_stack()
        offsets = self._offsets()
        p_band = self._end_band(self._PN_SECTOR, offsets["pp"][1], offsets["p"][1])
        n_band = self._end_band(self._PN_SECTOR, offsets["n"][0], offsets["nn"][0])
        children = [_chip_slab(self.bus_length, self.waveguide_width, self._draw_thickness(), **self._core()),
                    *self._ring_children_3d()]
        if self.add_drop:
            children.append(_chip_slab(self.bus_length, self.waveguide_width, self._draw_thickness(), y=self.drop_bus_y, **self._core()))
        children += [_chip_extruded_polygon(p_band, stack["implant_height"], color=P_DOPED, preset="silicon", z_offset=stack["implant_z"]),
                     _chip_extruded_polygon(n_band, stack["implant_height"], color=N_DOPED, preset="silicon", z_offset=stack["implant_z"])]
        offsets = self._offsets()
        for key, color in (("pp", "#e89a9a"), ("nn", "#9dbbe8")):
            children.append(_chip_extruded_polygon(self._end_band(self._PN_SECTOR, *offsets[key]),
                                                   stack["implant_height"], color=color, preset="silicon",
                                                   z_offset=stack["implant_z"]))
        trimmed = (self._PN_SECTOR[0] + 6.0, self._PN_SECTOR[1] - 6.0)
        for key in ("p_contact", "n_contact"):
            children.append(_chip_extruded_polygon(self._end_band(trimmed, *offsets[key]),
                                                   stack["metal_height"], color=GOLD, preset="gold",
                                                   z_offset=stack["metal_z"]))
        overlap = min(stack["metal_height"] * 0.02, 0.005)
        if stack["metal_z"] - stack["via_z"] + overlap <= 0:
            raise ValueError("Racetrack via must start below its routing metal")
        for x, y in self._via_centers():
            children.append(_chip_slab(0.2, 0.2, stack["contact_height"], x=x, y=y,
                                       color="#777b82", preset="tungsten", z_offset=stack["contact_z"]))
        children += _vias(0.2, self._via_centers(), stack, into=overlap)
        paths, pads = self._lead_paths(), self._pads()
        lead_w = max(self.waveguide_width * 0.45, 0.5)
        for name in ("e1", "e2"):
            children.append(_chip_extruded_polygon(_polyline_outline(paths[name], lead_w), stack["metal_height"], color=GOLD, preset="gold", z_offset=stack["metal_z"]))
            children += _pad_on_via(self.contact_pad_size, self.contact_pad_size, pads[name][0], pads[name][1], stack,
                                    below=stack["metal_z"] + stack["metal_height"], color=GOLD, via_color=VIA)
        if self.with_heater:
            heater = [_chip_extruded_polygon(self._heater_band(), stack["heater_height"], color=TIN, preset="titanium_nitride", z_offset=stack["heater_z"])]
            landings: list[dict[str, Any]] = []
            for name in ("h1", "h2"):
                heater.append(_chip_extruded_polygon(_polyline_outline(paths[name], self.heater_width), stack["heater_height"], color=TIN, preset="titanium_nitride", z_offset=stack["heater_z"]))
                landings += _pad_on_via(self.heater_pad_size, self.heater_pad_size, pads[name][0], pads[name][1], stack,
                                        below=stack["heater_z"] + stack["heater_height"], color=GOLD, via_color=VIA,
                                        landing=(TIN, "titanium_nitride"))
            gold = [solid for solid in landings if solid["material"].get("preset") == "gold"]
            children += [*_cut_footprints(heater, gold), *landings]     # a pad on the heater's own level owns its patch
        return self._on_the_stack(children)

    def physics_metadata(self) -> dict[str, Any]:
        return {
            "domain": "on_chip",
            "component": "racetrack_modulator",
            "bend_radius": self.bend_radius,
            "coupling_length": self.coupling_length,
            "gap": self.gap,
            "modulation_mechanism": "pn_depletion",
            "bias_voltage_v": None,
            "electrode_length": self.active_length,
            "junction_length": self.junction_length,
        }


@dataclass
class MicroringWeightBank(ChipComponent):
    component_type = "MicroringWeightBank"
    schematic_family = "microring_weight_bank"
    ring_count: int = 4
    ring_pitch: float = 25.0
    ring_radius: float = 8.0
    waveguide_width: float = 0.5
    gap: float = 0.2
    drop_turn_radius: float = 4
    turn_radius_step: float = 1.1
    with_heaters: bool = True
    heater_width: float = 0.8
    heater_pad_size: float = 1.4
    left_link_vertical_length: float = 0.0

    def __init__(
        self,
        center=(0, 0),
        angle=0,
        ring_count: int = 4,
        ring_pitch: float = 22.0,
        ring_radius: float = 8.0,
        waveguide_width: float | None = None,
        gap: float | None = None,
        drop_turn_radius: float = 4.2,
        turn_radius_step: float = 1.1,
        with_heaters: bool = True,
        heater_width: float = 0.8,
        heater_pad_size: float = 1.4,
        left_link_vertical_length: float = 0.0,
        **kwargs,
    ):
        defaults = _generic_pdk_defaults()
        strip = defaults["strip"]
        self.ring_count = max(1, int(ring_count))
        self.ring_pitch = float(ring_pitch)
        self.ring_radius = float(ring_radius)
        self.waveguide_width = float(strip["width"] if waveguide_width is None else waveguide_width)
        self.gap = float(defaults["ring"]["gap"] if gap is None else gap)
        self.drop_turn_radius = float(drop_turn_radius)
        self.turn_radius_step = float(turn_radius_step)
        self.with_heaters = with_heaters
        self.heater_width = float(heater_width)
        self.heater_pad_size = float(heater_pad_size)
        self.left_link_vertical_length = max(float(left_link_vertical_length), 0.0)
        self._init_chip(center=center, angle=angle, **kwargs)

    def physical_spec(self) -> PhysicalSpec:
        return PhysicalSpec(
            device_family=self.schematic_family,
            values={
                "ring_count": self.ring_count,
                "ring_pitch": self.ring_pitch,
                "ring_radius": self.ring_radius,
                "bus_length": self.bus_length,
                "waveguide_width": self.waveguide_width,
                "gap": self.gap,
                "drop_turn_radius": self.drop_turn_radius,
                "turn_radius_step": self.turn_radius_step,
                "heater_width": self.heater_width,
                "heater_pad_size": self.heater_pad_size,
                "left_link_vertical_length": self.left_link_vertical_length,
                "with_heaters": self.with_heaters,
                "thickness": self.chip_thickness,
            },
        )

    def _draw_variant(self) -> MicroringWeightBank:
        if self.render_physical:
            return self
        return MicroringWeightBank(
            ring_count=self.ring_count,
            ring_pitch=self._draw("ring_pitch", self.ring_pitch),
            ring_radius=self._draw("ring_radius", self.ring_radius),
            waveguide_width=self._draw("waveguide_width", self.waveguide_width),
            gap=self._draw("gap", self.gap),
            drop_turn_radius=self.drop_turn_radius,
            turn_radius_step=self.turn_radius_step,
            with_heaters=self.with_heaters,
            heater_width=self.heater_width,
            heater_pad_size=self.heater_pad_size,
            left_link_vertical_length=self.left_link_vertical_length,
            **self._draw_variant_kwargs(),
        )

    @property
    def bus_offset_y(self) -> float:
        return self.ring_radius + self.gap + self.waveguide_width

    @property
    def through_bus_y(self) -> float:
        return -self.bus_offset_y

    @property
    def drop_bus_y(self) -> float:
        return self.bus_offset_y

    @property
    def bus_length(self) -> float:
        span = self.ring_pitch * max(self.ring_count - 1, 0)
        side_margin = self.ring_radius + self.bus_offset_y + 8.0
        return max(span + 2.0 * side_margin, 2.0 * side_margin)

    @property
    def output_right_x(self) -> float:
        return self.bus_length / 2.0

    @property
    def output_bus_y(self) -> float:
        return self.drop_bus_y + max(self.ring_radius * 2.0, self.drop_turn_radius * 2.0 + self.waveguide_width * 4.0)

    @property
    def drop_output_y(self) -> float:
        return self.output_bus_y

    @property
    def shared_bus_left_x(self) -> float:
        ring = self._ring_component()
        return min(cx - ring.bus_length / 2.0 for cx in self._ring_centers())

    @property
    def shared_bus_right_x(self) -> float:
        ring = self._ring_component()
        return max(cx + ring.bus_length / 2.0 for cx in self._ring_centers())

    def _ring_centers(self) -> list[float]:
        if self.ring_count == 1:
            return [0.0]
        offset = (self.ring_count - 1) / 2.0
        return [(index - offset) * self.ring_pitch for index in range(self.ring_count)]

    def _ring_component(self) -> MicroringResonator:
        return MicroringResonator(
            ring_radius=self.ring_radius,
            waveguide_width=self.waveguide_width,
            gap=self.gap,
            add_drop=True,
            with_heater=self.with_heaters,
            heater_width=self.heater_width,
            heater_pad_size=self.heater_pad_size,
            color=self.color,
            opacity=self.opacity,
            chip_thickness=self.chip_thickness,
            material_preset=self.material_preset,
        )

    def _serial_drop_bus_path(self) -> list[tuple[float, float]]:
        return [
            (self.shared_bus_left_x, self.drop_bus_y),
            (self.shared_bus_right_x, self.drop_bus_y),
        ]

    def _output_bus_path(self) -> list[tuple[float, float]]:
        return [
            (self.shared_bus_left_x, self.output_bus_y),
            (self.output_right_x, self.output_bus_y),
        ]

    def _left_serial_link_path(self) -> list[tuple[float, float]]:
        delta_y = max(self.output_bus_y - self.drop_bus_y, self.waveguide_width * 4.0)
        bend_radius = max((delta_y - self.left_link_vertical_length) / 2.0, self.waveguide_width * 2.5)
        vertical_clearance = max(delta_y - 2.0 * bend_radius, 0.0)
        entry_x = self.shared_bus_left_x
        outer_x = entry_x - bend_radius
        path: list[tuple[float, float]] = [(entry_x, self.drop_bus_y), (outer_x, self.drop_bus_y)]
        lower_arc = _arc_points(outer_x, self.drop_bus_y + bend_radius, bend_radius, -90.0, -180.0, segments=12)
        path.extend(lower_arc[1:])
        if vertical_clearance > 1e-9:
            path.append((outer_x - bend_radius, self.output_bus_y - bend_radius))
        upper_arc = _arc_points(outer_x, self.output_bus_y - bend_radius, bend_radius, 180.0, 90.0, segments=12)
        path.extend(upper_arc[1:])
        path.append((entry_x, self.output_bus_y))
        return path

    def _translated_ring_children_2d(self, cx: float, index: int) -> list[dict[str, Any]]:
        ring = self._ring_component()
        ring_color = _resonance_channel_color(self, index / max(self.ring_count - 1, 1))
        children = [
            _chip_polygon(_translate_points(ring._ring_polygon(), cx, 0.0), fill=ring_color, opacity=self.opacity, stroke=SILICON_EDGE, stroke_width=0.08)
        ]
        if self.with_heaters:
            # the ring's own unified heater polygon (arc + leads + pads in one
            # outline), translated to this ring's slot; vias ride its pad spots
            children.extend(
                [
                    _chip_polygon(_translate_points(ring._heater_polygon(), cx, 0.0), fill="#d4af37",
                                  opacity=self.opacity * HEATER_OVER_GUIDE, stroke="#8e7611", stroke_width=0.08),
                    *[
                        _chip_box(cx + via_x, via_y, ring.heater_via_size, ring.heater_via_size, "#f08c6d", self.opacity, stroke="#8b5038", stroke_width=0.08)
                        for via_x, via_y in ring._heater_via_centers()
                    ],
                ]
            )
        return children

    def _translated_ring_children_3d(self, cx: float, index: int, stack: dict[str, float]) -> list[dict[str, Any]]:
        ring = self._ring_component()
        ring_color = _resonance_channel_color(self, index / max(self.ring_count - 1, 1))
        children = [
            _chip_extruded_polygon(_translate_points(ring._ring_polygon(), cx, 0.0), self.chip_thickness, color=ring_color, preset=self.material_preset)
        ]
        if self.with_heaters:
            children.extend(
                [
                    _chip_extruded_polygon(_translate_points(ring._heater_polygon(), cx, 0.0), stack["heater_height"], color="#d4af37", preset="gold", z_offset=stack["heater_z"]),
                    *_vias(ring.heater_via_size, [(cx + via_x, via_y) for via_x, via_y in ring._heater_via_centers()], stack),
                ]
            )
        return children

    @property
    def open_ports(self) -> tuple[str, ...]:
        """The taps on the drop bus above each ring: points on the bank's own waveguide, not ends to wire. And the
        heater pads: they sit between the rings, inside the buses, where a probe lands; a wire out would cross a bus."""

        taps = tuple(f"d{index}" for index in range(1, int(self.ring_count) + 1))
        return taps + (tuple(f"e{index}" for index in range(1, 2 * int(self.ring_count) + 1)) if self.with_heaters else ())

    def ports(self) -> dict[str, Port]:
        draw = self._draw_variant()
        if draw is not self:
            return draw.ports()
        half = self.bus_length / 2.0
        ports: dict[str, Port] = {
            "o1": Port("o1", Vec3(-half, self.through_bus_y, 0), orientation_deg=180, width=self._draw("waveguide_width", self.waveguide_width)),
            "o2": Port("o2", Vec3(half, self.through_bus_y, 0), orientation_deg=0, width=self._draw("waveguide_width", self.waveguide_width)),
            # Summed drop-bus output (broadcast-and-weight), read at the bus right end.
            "drop": Port("drop", Vec3(self.output_right_x, self.output_bus_y, 0), orientation_deg=0, width=self._draw("waveguide_width", self.waveguide_width)),
        }
        electrical_index = 1
        ring = self._ring_component()
        heater_pads = ring._heater_via_centers() if self.with_heaters else []
        for index, cx in enumerate(self._ring_centers(), start=1):
            # Per-ring drop-coupling point on the drop bus above each ring (NOT stacked
            # at the shared output, which read as one floating port).
            ports[f"d{index}"] = Port(f"d{index}", Vec3(cx, self.drop_bus_y, 0), orientation_deg=90, width=self._draw("waveguide_width", self.waveguide_width))
            if self.with_heaters:
                for pad_x, pad_y in heater_pads:
                    name = f"e{electrical_index}"
                    ports[name] = Port(name, Vec3(cx + pad_x, pad_y, 0), orientation_deg=ring._heater_opening_deg,
                                       width=self.heater_pad_size, kind="electrical")
                    electrical_index += 1
        return ports


    def optical_paths(self, in_port: str) -> list[dict[str, Any]]:
        """The bank as the system it is: light runs the shared through bus, sheds
        a fraction into EACH ring's drawn loop in sequence, and the dropped light
        exits on the drop/output bus. Port in, ports out."""

        draw = self._draw_variant() if hasattr(self, "_draw_variant") else self
        if draw is not self:
            draw.anim_params = self.anim_params  # behaviours ride along
            return draw.optical_paths(in_port)
        ports = self.ports()
        if in_port not in ("o1", "o2") or in_port not in ports:
            return []
        per_ring_through = 0.85  # each ring sheds ~15% at its operating point
        entry = ports[in_port]
        from_left = float(entry.center.x) < 0
        thr_exit = "o2" if in_port == "o1" else "o1"
        bus_y = float(entry.center.y)
        e_x = float(entry.center.x)
        t_x = float(ports[thr_exit].center.x)
        samples = 64
        bus = [[e_x + (t_x - e_x) * i / samples, bus_y] for i in range(samples + 1)]
        physical_centers = self._ring_centers()
        centers = sorted(physical_centers, reverse=not from_left)

        def crossings(x: float) -> int:
            return sum(1 for cx in centers if (x >= cx) == from_left or abs(x - cx) < 1e-9) \
                if from_left else sum(1 for cx in centers if x <= cx)

        bus_powers = []
        for x, _ in bus:
            passed = sum(1 for cx in centers if (cx <= x if from_left else cx >= x))
            bus_powers.append(per_ring_through ** passed)
        through = {"port": thr_exit, "power": per_ring_through ** len(centers),
                   "pts": bus, "powers": bus_powers}
        paths = [through]

        template = self._ring_component()
        loop_local = [list(p) for p in template.loop_centerline()]
        if len(loop_local) >= 3 and math.dist(loop_local[0], loop_local[-1]) < 1e-6:
            loop_local = loop_local[:-1]
        for k, cx in enumerate(centers):
            arriving = per_ring_through ** k
            loop = [[x + cx, y] for x, y in loop_local]
            hop = min(range(len(loop)), key=lambda i: (loop[i][0] - cx) ** 2 + (loop[i][1] - bus_y) ** 2)
            turn = loop[hop:] + loop[:hop]
            turn.append(list(turn[0]))
            if not from_left:
                turn = turn[::-1]
            idx = min(range(len(bus)), key=lambda i: abs(bus[i][0] - cx))
            coupled = arriving * (1.0 - per_ring_through)
            lead = sum(math.dist(bus[i], bus[i + 1]) for i in range(idx))
            loop_path = {
                "port": "", "power": 0.0,
                "pts": turn,
                "powers": [max(coupled, 0.08)] * len(turn),
                "delay_len": round(lead, 4),
                # WDM: each ring is tuned to its own channel — its own color
                "color": _resonance_channel_color(self, physical_centers.index(cx) / max(len(physical_centers) - 1, 1)),
            }
            if getattr(self, "with_heaters", False) and str((getattr(self, "anim_params", None) or {}).get("heater", "on")) != "off":
                loop_path["mod"] = {"sign": -1, "depth": 0.7, "tau_s": 1.4}
            paths.append(loop_path)
        # dropped light follows the DRAWN drop topology: each ring pushes its
        # channel LEFT along the serial drop bus (co-propagation with the CCW
        # ring tops), around the left U-link, then RIGHT on the output bus to
        # the drop port — never straight across the wrong way.
        if "drop" in ports:
            drop_p = ports["drop"]
            first_cx = centers[0]
            loop = [[x + first_cx, y] for x, y in loop_local]
            hop = min(range(len(loop)), key=lambda i: (loop[i][0] - first_cx) ** 2 + (loop[i][1] - bus_y) ** 2)
            turn = loop[hop:] + loop[:hop]
            if not from_left:
                turn = turn[::-1]
            d_y = float(self.drop_bus_y)
            top = min(range(len(turn)), key=lambda i: abs(turn[i][0] - first_cx) + abs(turn[i][1] - d_y))
            serial = [list(p) for p in self._serial_drop_bus_path()]
            left_x = min(p[0] for p in serial)
            link = [list(p) for p in self._left_serial_link_path()]
            if link and link[0][0] < link[-1][0]:  # ensure link runs bus-end -> output-start
                pass
            out_bus = [list(p) for p in self._output_bus_path()]
            d_x, d_y2 = float(drop_p.center.x), float(drop_p.center.y)
            drop_pts = (
                turn[: top + 1]
                + [[turn[top][0], d_y], [left_x, d_y]]   # LEFT along the serial drop bus
                + link[1:]                                # the drawn left U-link
                + [[out_bus[-1][0], out_bus[-1][1]], [d_x, d_y2]]  # RIGHT on the output bus
            )
            idx = min(range(len(bus)), key=lambda i: abs(bus[i][0] - first_cx))
            lead = sum(math.dist(bus[i], bus[i + 1]) for i in range(idx))
            paths.append({
                "port": "drop", "power": 0.3,
                "pts": drop_pts,
                "powers": [0.35] * (top + 1) + [0.3] * (len(drop_pts) - top - 1),
                "delay_len": round(lead, 4),
            })
        return paths

    def anim_behaviors(self) -> list[dict]:
        if not getattr(self, "with_heaters", False):
            return []
        return [{"key": "heater", "label": "Ring heaters", "options": [
            ["auto", "On (channel tuning)"], ["off", "Off"]]}]

    def symbol_1d(self) -> tuple[str, dict[str, Any]]:
        return "weightbank", {"count": int(self.ring_count)}

    def geometry_2d(self) -> dict[str, Any]:
        draw = self._draw_variant()
        if draw is not self:
            return draw.geometry_2d()

        children: list[dict[str, Any]] = [
            _chip_polygon(_segment_outline((-self.bus_length / 2.0, self.through_bus_y), (self.bus_length / 2.0, self.through_bus_y), self.waveguide_width, self.waveguide_width), fill=self.color, opacity=self.opacity, stroke=SILICON_EDGE, stroke_width=0.08),
            _chip_polygon(_polyline_outline(self._serial_drop_bus_path(), self.waveguide_width), fill=self.color, opacity=self.opacity, stroke=SILICON_EDGE, stroke_width=0.08),
            _chip_polygon(_polyline_outline(self._output_bus_path(), self.waveguide_width), fill=self.color, opacity=self.opacity, stroke=SILICON_EDGE, stroke_width=0.08),
            _chip_polygon(_polyline_outline(self._left_serial_link_path(), self.waveguide_width), fill=self.color, opacity=self.opacity, stroke=SILICON_EDGE, stroke_width=0.08),
        ]
        for index, cx in enumerate(self._ring_centers()):
            children.extend(self._translated_ring_children_2d(cx, index))
        return {"type": "group", "children": children}

    def geometry_3d(self) -> dict[str, Any]:
        draw = self._draw_variant()
        if draw is not self:
            return draw.geometry_3d()

        children: list[dict[str, Any]] = [
            _chip_slab(self.bus_length, self.waveguide_width, self._draw_thickness(), y=self.through_bus_y, **self._core()),
            _chip_path_slab(self._serial_drop_bus_path(), self.waveguide_width, self.chip_thickness, **self._core()),
            _chip_path_slab(self._output_bus_path(), self.waveguide_width, self.chip_thickness, **self._core()),
            _chip_path_slab(self._left_serial_link_path(), self.waveguide_width, self.chip_thickness, **self._core()),
        ]
        stack = self._draw_layer_stack()
        for index, cx in enumerate(self._ring_centers()):
            children.extend(self._translated_ring_children_3d(cx, index, stack))
        return self._on_the_stack(children)


# Power coupling of one gap, for CoupledRingFilter. Model only, not fitted to a PDK:
# the evanescent field decays as exp(-gap / decay), so the coupled power does too.
# The reference point is a 0.1 power coupling at a 0.30 um gap.
_COUPLING_REF = 0.10
_COUPLING_GAP_REF = 0.30
_COUPLING_GAP_DECAY = 0.12


def gap_power_coupling(gap: float) -> float:
    """Power coupling of one gap in um (model only, see the constants above)."""

    return min(0.999, _COUPLING_REF * math.exp(-(float(gap) - _COUPLING_GAP_REF) / _COUPLING_GAP_DECAY))


def gap_for_power_coupling(kappa: float) -> float:
    """The gap in um that gives the power coupling ``kappa``: the inverse of :func:`gap_power_coupling`."""

    return _COUPLING_GAP_REF - _COUPLING_GAP_DECAY * math.log(max(float(kappa), 1e-12) / _COUPLING_REF)


def butterworth_power_couplings(order: int, bus_coupling: float = _COUPLING_REF) -> tuple[float, ...]:
    """The ``order + 1`` power couplings of a maximally flat (Butterworth) series-coupled ring filter.

    Both bus couplers have ``bus_coupling``. The coupler between ring i and ring i+1 has
    ``(g_1 * bus_coupling)**2 / (4 * g_i * g_(i+1))``, with the Butterworth prototype values
    ``g_i = 2 sin((2i - 1) pi / (2 order))``. Source: Matthaei, Young and Jones, Microwave Filters,
    Impedance-Matching Networks, and Coupling Structures (McGraw-Hill, 1964): coupling coefficient
    ``k(i,i+1) = FBW / sqrt(g_i g_(i+1))`` and external quality factor ``Qe = g_0 g_1 / FBW``.
    A ring that loses ``kappa`` of its energy per round trip has ``Q = omega T / kappa`` and two rings
    with power coupling ``kappa`` split by ``2 sqrt(kappa) / T``. The ring-ring formula follows from those
    two relations. tests/test_coupled_ring_filter.py checks that the result has a flat top.
    """

    g = [2.0 * math.sin((2 * i - 1) * math.pi / (2 * order)) for i in range(1, order + 1)]
    inner = [(g[0] * bus_coupling) ** 2 / (4.0 * g[i] * g[i + 1]) for i in range(order - 1)]
    return (float(bus_coupling), *inner, float(bus_coupling))


def _stadium_loop(cy: float, radius: float, half_l: float, segments: int = 24) -> list[tuple[float, float]]:
    """A closed loop, counter-clockwise, from the bottom centre: two straights ``2 * half_l`` long and two half circles.

    With ``half_l = 0`` it is a circle. The top centre is a point of the loop, so a half path can end there."""

    east = _arc_points(half_l, cy, radius, -90.0, 90.0, segments=segments)
    west = _arc_points(-half_l, cy, radius, 90.0, 270.0, segments=segments)
    return _dedupe_points([(0.0, cy - radius), *east, (0.0, cy + radius), *west, (0.0, cy - radius)])


def _dedupe_points(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for point in points:
        if not out or math.dist(out[-1], point) > 1e-9:
            out.append(point)
    return out


@dataclass
class CoupledRingFilter(ChipComponent):
    """A series-coupled microring filter of order ``order`` (1 to 8).

    ``order`` rings stand in a column between a bottom bus and a top bus. Each ring couples to the next
    ring through a gap. Order 1 is the add-drop ring. Order 2 is the common 2-pole filter. Order 5 is
    Fig. 1a of Mak et al., IEEE J. Quantum Electron. 51(11), 2015.

    Ports, by position: ``o1`` bottom bus west, ``o2`` bottom bus east, ``o3`` top bus west, ``o4`` top
    bus east. The rings turn in opposite senses, so light that enters ``o1`` circulates alternately
    counter-clockwise and clockwise. For an odd order it leaves the top bus at ``o3`` (west). For an even
    order it leaves at ``o4`` (east). The read-only properties :attr:`drop_port` and :attr:`add_port` return
    these names: the drop port for light that enters ``o1``, and the add port, which is the other end of the
    top bus. The through port of ``o1`` is ``o2``. The order 1 filter agrees with
    ``MicroringResonator(add_drop=True)``: light from ``o1`` drops at ``o3``.

    ``gaps`` has ``order + 1`` values in um, from bottom to top: bus to ring 1, ring 1 to ring 2, and so on,
    ring ``order`` to the top bus. One number sets every gap. When ``gaps`` is None the gaps give a maximally
    flat passband (Butterworth), see :func:`butterworth_power_couplings`. ``ring_shape`` is ``"circle"`` or
    ``"racetrack"``. A racetrack ring has straights ``coupling_length`` long on top and bottom.
    ``power_couplings`` replaces the power coupling that the animation takes from each gap.
    ``with_heaters`` adds one heater per ring, with ports ``h{k}a`` (upper end) and ``h{k}b`` (lower end),
    on the west side for odd rings and on the east side for even rings.
    """

    component_type = "CoupledRingFilter"
    schematic_family = "coupled_ring_filter"
    order: int = 2
    ring_shape: str = "circle"
    radius: float = 10.0
    coupling_length: float = 5.0
    gaps: tuple = ()
    waveguide_width: float = 0.5
    with_heaters: bool = False
    heater_width: float = 1.0
    heater_gap: float = 1.5
    heater_pad_size: float = 1.6
    power_couplings: tuple | None = None
    round_trip_amplitude: float = 0.998

    MAX_ORDER = 8
    _BUS_MARGIN = 3.0

    def __init__(
        self,
        center=(0, 0),
        angle=0,
        order: int = 2,
        ring_shape: str = "circle",
        radius: float | None = None,
        coupling_length: float = 5.0,
        gaps=None,
        waveguide_width: float | None = None,
        with_heaters: bool = False,
        heater_width: float = 1.0,
        heater_gap: float = 1.5,
        heater_pad_size: float = 1.6,
        power_couplings=None,
        round_trip_amplitude: float = 0.998,
        **kwargs,
    ):
        count = int(order)
        if not 1 <= count <= self.MAX_ORDER:
            raise ValueError(f"CoupledRingFilter order must be 1 to {self.MAX_ORDER}, got {order}")
        if ring_shape not in ("circle", "racetrack"):
            raise ValueError(f"ring_shape must be 'circle' or 'racetrack', got {ring_shape!r}")
        defaults = _generic_pdk_defaults()
        self.order = count
        self.ring_shape = ring_shape
        self.radius = float(defaults["ring"]["radius"] if radius is None else radius)
        self.coupling_length = float(coupling_length)
        self.waveguide_width = float(defaults["strip"]["width"] if waveguide_width is None else waveguide_width)
        self.gaps = self._normalise_gaps(gaps, count)
        self.with_heaters = bool(with_heaters)
        self.heater_width = float(heater_width)
        self.heater_gap = float(heater_gap)
        self.heater_pad_size = float(heater_pad_size)
        if power_couplings is None:
            self.power_couplings = None
        else:
            values = tuple(float(value) for value in power_couplings)
            if len(values) != count + 1 or any(not 0.0 <= value <= 1.0 for value in values):
                raise ValueError(f"power_couplings needs {count + 1} values between 0 and 1")
            self.power_couplings = values
        self.round_trip_amplitude = float(round_trip_amplitude)
        self._init_chip(center=center, angle=angle, **kwargs)

    @staticmethod
    def _normalise_gaps(gaps, order: int) -> tuple[float, ...]:
        if gaps is None:
            return tuple(gap_for_power_coupling(kappa) for kappa in butterworth_power_couplings(order))
        if isinstance(gaps, (int, float)):
            values = (float(gaps),) * (order + 1)
        else:
            values = tuple(float(value) for value in gaps)
        if len(values) != order + 1:
            raise ValueError(f"gaps needs {order + 1} values (bus-ring, ring-ring..., ring-bus) or one number, got {len(values)}")
        if any(value <= 0.0 for value in values):
            raise ValueError("every gap must be larger than 0")
        return values

    # ---- ports and physics ---------------------------------------------------------------------
    @property
    def drop_port(self) -> str:
        """The port where light that enters ``o1`` leaves the top bus: ``o3`` for an odd order, ``o4`` for an even one."""

        return "o3" if self.order % 2 else "o4"

    @property
    def add_port(self) -> str:
        """The other end of the top bus: ``o4`` for an odd order, ``o3`` for an even one."""

        return "o4" if self.order % 2 else "o3"

    @property
    def effective_power_couplings(self) -> tuple[float, ...]:
        """Power coupling of each coupler, bottom bus first: ``power_couplings``, else the model of each gap."""

        if self.power_couplings is not None:
            return self.power_couplings
        return tuple(gap_power_coupling(gap) for gap in self.gaps)

    @property
    def round_trip_length(self) -> float:
        """Length of one ring in um."""

        return 2.0 * math.pi * self.radius + 4.0 * self._half_straight

    @property
    def half_loop_length(self) -> float:
        """Length in um of the path from one bus coupler of a ring to the other."""

        return self.round_trip_length / 2.0

    def physical_spec(self) -> PhysicalSpec:
        return PhysicalSpec(
            device_family=self.schematic_family,
            values={
                "order": self.order,
                "radius": self.radius,
                "coupling_length": self.coupling_length,
                "gap_min": min(self.gaps),
                "gap_max": max(self.gaps),
                "waveguide_width": self.waveguide_width,
                "with_heaters": self.with_heaters,
                "thickness": self.chip_thickness,
            },
        )

    def _draw_variant(self) -> CoupledRingFilter:
        if self.render_physical:
            return self
        base = self._draw("gap", min(self.gaps))
        smallest = min(self.gaps)
        return CoupledRingFilter(
            order=self.order,
            ring_shape=self.ring_shape,
            radius=self._draw("radius", self.radius),
            coupling_length=self._draw("coupling_length", self.coupling_length),
            gaps=tuple(base * gap / smallest for gap in self.gaps),
            waveguide_width=self._draw("waveguide_width", self.waveguide_width),
            with_heaters=self.with_heaters,
            heater_width=self._draw("heater_width", self.heater_width),
            heater_gap=self._draw("heater_gap", self.heater_gap),
            heater_pad_size=self._draw("heater_pad_size", self.heater_pad_size),
            power_couplings=self.effective_power_couplings,
            round_trip_amplitude=self.round_trip_amplitude,
            **self._draw_variant_kwargs(),
        )

    # ---- layout --------------------------------------------------------------------------------
    @property
    def _half_straight(self) -> float:
        return self.coupling_length / 2.0 if self.ring_shape == "racetrack" else 0.0

    @property
    def _bus_ring_offsets(self) -> tuple[float, ...]:
        """Distance between neighbouring centre lines, bottom to top: bus-ring 1, ring-ring..., ring N-bus."""

        w, r = self.waveguide_width, self.radius
        return (r + w + self.gaps[0], *(2.0 * r + w + gap for gap in self.gaps[1:-1]), r + w + self.gaps[-1])

    @property
    def bottom_bus_y(self) -> float:
        return -sum(self._bus_ring_offsets) / 2.0

    @property
    def top_bus_y(self) -> float:
        return sum(self._bus_ring_offsets) / 2.0

    @property
    def ring_centers_y(self) -> tuple[float, ...]:
        """The y of each ring centre, bottom ring first."""

        y = self.bottom_bus_y
        out = []
        for offset in self._bus_ring_offsets[:-1]:
            y += offset
            out.append(y)
        return tuple(out)

    @property
    def heater_radius(self) -> float:
        return self.radius + self.waveguide_width / 2.0 + self.heater_gap + self.heater_width / 2.0

    @property
    def bus_length(self) -> float:
        reach = self._half_straight + self.radius + self.waveguide_width / 2.0 + self._BUS_MARGIN
        if self.with_heaters:
            reach = max(reach, self._half_straight + self.heater_radius + 1.5 * self.heater_pad_size + 2.0)
        return 2.0 * reach

    def ring_loop(self, k: int) -> list[tuple[float, float]]:
        """The centre line of ring ``k`` (1 is the bottom ring): a closed loop from its bottom centre."""

        return _stadium_loop(self.ring_centers_y[k - 1], self.radius, self._half_straight)

    def ring_half_path(self, k: int, side: str) -> list[tuple[float, float]]:
        """The half of ring ``k`` from its bottom centre to its top centre, through its east or west side."""

        cy, r, hl = self.ring_centers_y[k - 1], self.radius, self._half_straight
        if side == "east":
            arc = _arc_points(hl, cy, r, -90.0, 90.0, segments=24)
        elif side == "west":
            arc = _arc_points(-hl, cy, r, 270.0, 90.0, segments=24)
        else:
            raise ValueError("side must be 'east' or 'west'")
        return _dedupe_points([(0.0, cy - r), *arc, (0.0, cy + r)])

    def _band_polygon(self, k: int) -> list[tuple[float, float]]:
        cy, hl, w2 = self.ring_centers_y[k - 1], self._half_straight, self.waveguide_width / 2.0
        outer = _stadium_loop(cy, self.radius + w2, hl)
        inner = _stadium_loop(cy, self.radius - w2, hl)
        return outer + inner[::-1]

    def _bus_polygon(self, y: float) -> list[tuple[float, float]]:
        half, w = self.bus_length / 2.0, self.waveguide_width
        return _segment_outline((-half, y), (half, y), w, w)

    # ---- heaters -------------------------------------------------------------------------------
    def _heater_side(self, k: int) -> int:
        """-1 (west) for an odd ring, +1 (east) for an even ring: neighbouring heaters keep apart."""

        return -1 if k % 2 else 1

    def _heater_layout(self, k: int) -> dict[str, Any]:
        side = self._heater_side(k)
        cx, cy, r = side * self._half_straight, self.ring_centers_y[k - 1], self.heater_radius
        upper, lower = (140.0, 220.0) if side < 0 else (40.0, -40.0)
        arc = _arc_points(cx, cy, r, upper, lower, segments=24)
        stub = 0.12 * r
        ends = []
        for deg, point in ((upper, arc[0]), (lower, arc[-1])):
            ends.append((point[0] + stub * math.cos(math.radians(deg)), point[1] + stub * math.sin(math.radians(deg))))
        pad_x = cx + side * (r + self.heater_pad_size)
        edge_x = pad_x - side * self.heater_pad_size / 2.0          # the pad edge that faces the ring
        path = [(edge_x, ends[0][1]), ends[0], *arc, ends[1], (edge_x, ends[1][1])]
        pads = [(pad_x, ends[0][1]), (pad_x, ends[1][1])]
        return {"side": side, "path": path, "pads": pads, "arc": arc}

    def optical_paths(self, in_port: str) -> list[dict[str, Any]]:
        """The drawn buses and ring halves the light takes from ``in_port``, with the hop across each gap.

        ``in_port`` is a bus end (``o1`` to ``o4``) or an internal port ``_a1u``, ``_b2l`` and so on:
        chain, ring number, and ``u`` (upper coupler) or ``l`` (lower coupler). Chain ``a`` starts at the
        bottom west end, chain ``b`` at the bottom east end. Each path is one engine transfer.
        """

        draw = self._draw_variant()
        if draw is not self:
            return draw.optical_paths(in_port)
        n = self.order
        top_in = {"a": "o4" if n % 2 else "o3", "b": "o3" if n % 2 else "o4"}
        top_out = {"a": top_in["b"], "b": top_in["a"]}
        bottom_in, bottom_out = {"a": "o1", "b": "o2"}, {"a": "o2", "b": "o1"}
        chain = next((c for c in "ab" if in_port in (bottom_in[c], top_in[c]) or in_port.startswith(f"_{c}")), None)
        if chain is None:
            return []
        ports = self.ports()

        def xy(port: str) -> tuple[float, float]:
            return (float(ports[port].center.x), float(ports[port].center.y))

        def side(k: int) -> str:
            """The side of ring k that light crosses going up in this chain (ring 1 of chain a turns counter-clockwise)."""

            return "east" if (k % 2 == 1) == (chain == "a") else "west"

        def up(k: int) -> list:
            return self.ring_half_path(k, side(k))

        def down(k: int) -> list:
            return self.ring_half_path(k, "west" if side(k) == "east" else "east")[::-1]

        def to_coupler(port: str) -> list:
            return [xy(port), (0.0, xy(port)[1])]

        def from_coupler(port: str) -> list:
            return [(0.0, xy(port)[1]), xy(port)]

        def node(k: int, where: str) -> str:
            return f"_{chain}{k}{where}"

        routes: list[tuple[str, list]] = []
        if in_port == bottom_in[chain]:
            routes = [(bottom_out[chain], [xy(in_port), xy(bottom_out[chain])]), (node(1, "u"), to_coupler(in_port) + up(1))]
        elif in_port == top_in[chain]:
            routes = [(top_out[chain], [xy(in_port), xy(top_out[chain])]), (node(n, "l"), to_coupler(in_port) + down(n))]
        else:
            k, where = int(in_port[2:-1]), in_port[-1]
            if where == "u":                             # at the upper coupler of ring k
                routes = [(node(k, "l"), down(k))]
                routes.append((node(k + 1, "u"), up(k + 1)) if k < n else (top_out[chain], from_coupler(top_out[chain])))
            else:                                        # at the lower coupler of ring k
                routes = [(node(k, "u"), up(k))]
                routes.append((node(k - 1, "l"), down(k - 1)) if k > 1 else (bottom_out[chain], from_coupler(bottom_out[chain])))
        return [{"port": target, "pts": [list(p) for p in points]} for target, points in routes]

    def heater_centerline(self, k: int) -> list[tuple[float, float]]:
        """The heater of ring ``k`` along its spine: the arc around the ring."""

        return self._heater_layout(k)["arc"]

    def _heater_polygon(self, k: int) -> list[tuple[float, float]]:
        return _polyline_outline(self._heater_layout(k)["path"], self.heater_width)

    def _pad_polygon(self, x: float, y: float) -> list[tuple[float, float]]:
        s = self.heater_pad_size / 2.0
        return [(x - s, y - s), (x + s, y - s), (x + s, y + s), (x - s, y + s)]

    @property
    def heater_via_size(self) -> float:
        return max(self.heater_width * 0.7, 0.32)

    def _cladding_box(self) -> tuple[float, float]:
        half_x = self.bus_length / 2.0
        half_y = self.top_bus_y + self.waveguide_width + 2.0
        return 2.0 * half_x, 2.0 * half_y

    # ---- ports ---------------------------------------------------------------------------------
    def ports(self) -> dict[str, Port]:
        draw = self._draw_variant()
        if draw is not self:
            return draw.ports()
        half, w = self.bus_length / 2.0, self.waveguide_width
        ports = {
            "o1": Port("o1", Vec3(-half, self.bottom_bus_y, 0), orientation_deg=180, width=w),
            "o2": Port("o2", Vec3(half, self.bottom_bus_y, 0), orientation_deg=0, width=w),
            "o3": Port("o3", Vec3(-half, self.top_bus_y, 0), orientation_deg=180, width=w),
            "o4": Port("o4", Vec3(half, self.top_bus_y, 0), orientation_deg=0, width=w),
        }
        if self.with_heaters:
            for k in range(1, self.order + 1):
                layout = self._heater_layout(k)
                facing = 180 if layout["side"] < 0 else 0
                for name, (x, y) in zip((f"h{k}a", f"h{k}b"), layout["pads"]):
                    ports[name] = Port(name, Vec3(x, y, 0), orientation_deg=facing, width=self.heater_pad_size, kind="electrical")
        return ports

    # ---- drawing -------------------------------------------------------------------------------
    def _optical_children_2d(self) -> list[dict[str, Any]]:
        children = [
            _chip_polygon(self._bus_polygon(y), fill=self.color, opacity=self.opacity, stroke=SILICON_EDGE, stroke_width=0.08)
            for y in (self.bottom_bus_y, self.top_bus_y)
        ]
        w2 = self.waveguide_width / 2.0
        for k in range(1, self.order + 1):
            cy, hl = self.ring_centers_y[k - 1], self._half_straight
            children.append(_chip_polygon(self._band_polygon(k), fill=self.color, opacity=self.opacity, stroke="none", stroke_width=0.0))
            for sign in (1.0, -1.0):
                children.append(_chip_polyline(_stadium_loop(cy, self.radius + sign * w2, hl), stroke=SILICON_EDGE,
                                               stroke_width=0.08, opacity=self.opacity, closed=True))
        return children

    def _optical_children_3d(self) -> list[dict[str, Any]]:
        t = self._draw_thickness()
        children = [
            _chip_slab(self.bus_length, self.waveguide_width, t, y=y, **self._core())
            for y in (self.bottom_bus_y, self.top_bus_y)
        ]
        children += [
            _chip_extruded_polygon(self._band_polygon(k), t, **self._core())
            for k in range(1, self.order + 1)
        ]
        return children

    def _cladding_children_2d(self) -> list[dict[str, Any]]:
        width, height = self._cladding_box()
        return [_chip_box(0.0, 0.0, width, height, "#d8eef7", self.opacity * 0.12, stroke="#a7ccd9", stroke_width=0.05)]

    def _heater_children_2d(self) -> list[dict[str, Any]]:
        children: list[dict[str, Any]] = []
        for k in range(1, self.order + 1):
            layout = self._heater_layout(k)
            children += [_chip_polygon(self._pad_polygon(x, y), fill="#d4af37", opacity=self.opacity, stroke="#8e7611", stroke_width=0.08)
                         for x, y in layout["pads"]]
            children.append(_chip_polygon(self._heater_polygon(k), fill="#d4af37", opacity=self.opacity, stroke="#8e7611", stroke_width=0.08))
            children += [_chip_box(x, y, self.heater_via_size, self.heater_via_size, "#f08c6d", self.opacity, stroke="#8b5038", stroke_width=0.08)
                         for x, y in layout["pads"]]
        return children

    def _heater_children_3d(self) -> list[dict[str, Any]]:
        stack = self._draw_layer_stack()
        width, height = self._cladding_box()
        children = [_chip_slab(width, height, self._draw_thickness() * 0.34, color="#d8eef7", preset="sio2",
                               z_offset=stack["core_z"] + self._draw_thickness() * 0.66)]
        for k in range(1, self.order + 1):
            layout = self._heater_layout(k)
            children.append(_chip_extruded_polygon(self._heater_polygon(k), stack["metal_height"], color="#d4af37", preset="gold", z_offset=stack["metal_z"]))
            for x, y in layout["pads"]:
                children.append(_chip_extruded_polygon(self._pad_polygon(x, y), stack["metal_height"], color="#d4af37", preset="gold", z_offset=stack["metal_z"]))
                children += _vias(self.heater_via_size, [(x, y)], stack)
        return children

    def geometry_2d(self) -> dict[str, Any]:
        draw = self._draw_variant()
        if draw is not self:
            return draw.geometry_2d()
        children = self._optical_children_2d()
        if self.with_heaters:
            children = [*self._cladding_children_2d(), *children, *self._heater_children_2d()]
        return {"type": "group", "children": children}

    def geometry_3d(self) -> dict[str, Any]:
        draw = self._draw_variant()
        if draw is not self:
            return draw.geometry_3d()
        children = self._optical_children_3d()
        if self.with_heaters:
            children.extend(self._heater_children_3d())
        return self._on_the_stack(children)

    def symbol_1d(self) -> tuple[str, dict[str, Any]]:
        params: dict[str, Any] = {"order": self.order}
        if self.with_heaters:
            params["heater"] = True
        return "coupledring", params

    def physics_metadata(self) -> dict[str, Any]:
        from optodraw.core.guided import SILICON_STRIP_NEFF_STUB

        fsr_nm = (1.55**2) / (SILICON_STRIP_NEFF_STUB * self.round_trip_length) * 1000.0
        return {
            "domain": "on_chip",
            "component": "coupled_ring_filter",
            "order": self.order,
            "ring_shape": self.ring_shape,
            "radius": self.radius,
            "gaps": list(self.gaps),
            "power_couplings": list(self.effective_power_couplings),
            "drop_port": self.drop_port,
            "fsr_nm": fsr_nm,
        }


# Through-port power at resonance per coupling regime (all-pass ring:
# T = ((gamma-kappa)/(gamma+kappa))^2 for kappa/gamma = 0.4 / 1.0 / 2.5).
_REGIME_THROUGH = {"under": 0.1837, "critical": 0.0, "over": 0.1837}


def _resonance_channel_color(node: Any, override_fraction: float | None = None) -> str:
    """Display color of the ring's RESONANT channel.

    The resonance follows the device's own geometry (lambda_res = n_eff*L/m near
    1550 nm); its position within one FSR maps onto a visible spectrum so rings
    with different geometry visibly couple different colors. Banks pass an
    explicit per-ring fraction (thermally tuned channels)."""

    import colorsys

    if override_fraction is None:
        n_eff = 2.4
        try:
            loop = node.loop_centerline()
            length_um = sum(math.dist(a, b) for a, b in zip(loop, loop[1:]))
        except Exception:
            length_um = 2.0 * math.pi * float(getattr(node, "ring_radius", 10.0))
        params = getattr(node, "anim_params", None) or {}
        if "channel" in params:
            fraction = min(max(float(params["channel"]), 0.0), 1.0)
        else:
            optical_length = n_eff * length_um
            m = max(round(optical_length / 1.55), 1)
            lambda_res = optical_length / m           # um, nearest resonance to 1550nm
            fsr = lambda_res / m
            fraction = ((lambda_res - 1.55) / fsr + 0.5) % 1.0
    else:
        fraction = min(max(override_fraction, 0.0), 1.0)
    r, g, b = colorsys.hsv_to_rgb(0.83 * (1.0 - fraction), 0.85, 0.95)
    return "#%02x%02x%02x" % (int(r * 255), int(g * 255), int(b * 255))


def _resonator_bus_loop_paths(node: Any, in_port: str) -> list[dict[str, Any]]:
    """System-style resonator animation on the DRAWN geometry.

    Light enters a bus port, runs the drawn bus, couples onto the drawn loop at
    the gap (tiny rail-hop, like a directional coupler), circulates, and exits:
    the through path continues to the far bus port (power steps to T at the
    coupler), the drop path (add-drop) rides half the loop and leaves on the
    drop bus. Ports in, ports out — same FDTD flow as every other device."""

    ports = node.ports()
    if in_port not in ("o1", "o2") or in_port not in ports:
        return []
    params = getattr(node, "anim_params", None) or {}
    switched_off = str(params.get("state", "on")) == "off"
    regime = params.get("ring_coupling", "auto")
    through_power = 1.0 if switched_off else _REGIME_THROUGH.get(regime, 0.15)
    entry = ports[in_port]
    from_left = float(entry.center.x) < 0
    thr_exit = "o2" if in_port == "o1" else "o1"
    if thr_exit not in ports:
        return []
    bus_y = float(entry.center.y)
    e_x = float(entry.center.x)
    t_x = float(ports[thr_exit].center.x)
    samples = 32
    bus = [[e_x + (t_x - e_x) * i / samples, bus_y] for i in range(samples + 1)]
    cpl = min(range(len(bus)), key=lambda i: abs(bus[i][0]))

    through = {
        "port": thr_exit, "power": through_power, "pts": bus,
        "powers": [1.0 if i <= cpl else through_power for i in range(len(bus))],
    }

    loop = [list(p) for p in node.loop_centerline()]
    if len(loop) >= 3 and math.dist(loop[0], loop[-1]) < 1e-6:
        loop = loop[:-1]
    hop = min(range(len(loop)), key=lambda i: (loop[i][0]) ** 2 + (loop[i][1] - bus_y) ** 2)
    turn = loop[hop:] + loop[:hop]
    turn.append(list(turn[0]))
    if not from_left:
        turn = turn[::-1]
    coupled = 1.0 - through_power
    # coupled light appears ON the loop at the gap after the bus lead-in
    # (delay_len) — the loop path is purely the drawn loop, nothing else
    lead = sum(math.dist(bus[i], bus[i + 1]) for i in range(cpl))
    channel = _resonance_channel_color(node)
    heated = bool(getattr(node, "with_heater", False)) and str(params.get("heater", "on")) != "off"
    if switched_off:
        # ring switched off (far detuned): the bus passes light untouched
        return [through]
    loop_path = {
        "port": "", "power": 0.0,  # circulation: nothing chains onward from it
        "pts": turn,
        "powers": [coupled] * len(turn),
        "delay_len": round(lead, 4),
        "color": channel,  # the ring couples ITS resonant color
    }
    if heated:
        # thermo-optic tuning: as the heater warms (index rises) the resonance
        # walks off the channel — coupled light dims, the through port recovers
        loop_path["mod"] = {"sign": -1, "depth": 0.85, "tau_s": 1.4}
        through["mod"] = {"sign": 1, "depth": 1.2, "tau_s": 1.4}
    paths = [through, loop_path]

    if getattr(node, "add_drop", False) and "o3" in ports and "o4" in ports:
        drop_exit = "o3" if from_left else "o4"
        drop_y = float(ports[drop_exit].center.y)
        d_hop = min(range(len(turn)), key=lambda i: (turn[i][0]) ** 2 + (turn[i][1] - drop_y) ** 2)
        d_x = float(ports[drop_exit].center.x)
        d_start_x = turn[d_hop][0]
        d_samples = 16
        drop_bus = [[d_start_x + (d_x - d_start_x) * i / d_samples, drop_y] for i in range(d_samples + 1)]
        drop_power = coupled * 0.85
        drop_path = {
            "port": drop_exit, "power": drop_power,
            "pts": turn[: d_hop + 1] + drop_bus,
            "powers": [coupled] * (d_hop + 1) + [drop_power] * (d_samples + 1),
            "delay_len": round(lead, 4),
            "color": channel,  # the dropped channel keeps the ring's color
        }
        if heated:
            drop_path["mod"] = {"sign": -1, "depth": 0.85, "tau_s": 1.4}
        paths.append(drop_path)
    return paths


class EORacetrackModulator(ChipComponent):
    """An electro-optic (Pockels) racetrack with gold G-S-G electrodes along both straights and no doping: the
    ring of a thin-film lithium niobate comb generator or ring modulator.

    The grounds lie outside the straights and the signal inside, between them, so one drive gives the two
    straights opposite phase shifts, as the light runs opposite ways round them (Zhang et al., Nature 568, 373
    (2019), Fig. 2a). A straight bus passes the west bend: light enters at ``o1`` (north) and leaves at ``o2``
    (south). ``gnd1``, ``sig`` and ``gnd2`` lie on one line through the centre, where a G-S-G probe lands; they
    may stay unwired.
    """

    component_type = "EORacetrackModulator"
    schematic_family = "eo_racetrack"
    open_ports = ("gnd1", "sig", "gnd2")

    def __init__(self, center=(0, 0), angle=0, straight_length: float = 2000.0, bend_radius: float = 100.0,
                 waveguide_width: float = 1.4, gap: float = 0.6, electrode_gap: float = 3.3,
                 electrode_width: float = 10.0, **kwargs):
        self.straight_length = float(straight_length)
        self.bend_radius = float(bend_radius)
        self.waveguide_width = float(waveguide_width)
        self.gap = float(gap)
        self.electrode_gap = float(electrode_gap)
        self.electrode_width = float(electrode_width)
        self._init_chip(center=center, angle=angle, **kwargs)
        r, w, eg, ew = (self._draw(k) for k in ("bend_radius", "waveguide_width", "electrode_gap", "electrode_width"))
        if r <= w / 2.0 + eg + ew:
            raise ValueError("bend_radius is too small: the two signal electrodes inside the racetrack would meet")

    def physical_spec(self) -> PhysicalSpec:
        return PhysicalSpec(device_family=self.schematic_family, values={
            "straight_length": self.straight_length, "bend_radius": self.bend_radius,
            "waveguide_width": self.waveguide_width, "gap": self.gap, "electrode_gap": self.electrode_gap,
            "electrode_width": self.electrode_width, "thickness": self.chip_thickness})

    def _plan(self) -> dict[str, Any]:
        """The drawn plan: the loop centre line, the bus x and half length, and each electrode as a box."""

        s, r, w, g, eg, ew = (self._draw(k) for k in ("straight_length", "bend_radius", "waveguide_width", "gap",
                                                      "electrode_gap", "electrode_width"))
        half = s / 2.0
        loop = [(-half, -r), (half, -r), *_arc_points(half, 0.0, r, -90.0, 90.0, segments=24)[1:-1], (half, r),
                (-half, r), *_arc_points(-half, 0.0, r, 90.0, 270.0, segments=24)[1:-1]]
        outer, inner = r + w / 2.0 + eg, r - w / 2.0 - eg         # the electrode edges nearest each straight
        bar = 2.5 * ew                                            # the G-S-G landing column, as wide as a probe tip
        boxes = {"gnd1": [(0.0, outer + ew / 2.0, s, ew), (0.0, outer + ew + bar / 2.0, bar, bar)],
                 "sig": [(0.0, inner - ew / 2.0, s, ew), (0.0, -inner + ew / 2.0, s, ew), (0.0, 0.0, bar, 2.0 * inner)],
                 "gnd2": [(0.0, -outer - ew / 2.0, s, ew), (0.0, -outer - ew - bar / 2.0, bar, bar)]}
        return {"loop": loop, "bus_x": -(half + r + g + w), "bus_half": r + 2.0 * w, "boxes": boxes,
                "pads": {"gnd1": outer + ew + bar / 2.0, "sig": 0.0, "gnd2": -outer - ew - bar / 2.0}, "bar": bar}

    def ports(self) -> dict[str, Port]:
        plan, width = self._plan(), self._draw("waveguide_width")
        x, y = plan["bus_x"], plan["bus_half"]
        ports = {"o1": Port("o1", Vec3(x, y, 0), orientation_deg=90, width=width),
                 "o2": Port("o2", Vec3(x, -y, 0), orientation_deg=270, width=width)}
        for name, py in plan["pads"].items():
            ports[name] = Port(name, Vec3(0.0, py, 0), orientation_deg=270 if py < 0 else 90, width=plan["bar"],
                               kind="electrical")
        return ports

    def _anchor_points(self) -> dict[str, tuple[float, float]]:
        plan = self._plan()
        return {"gap": (plan["bus_x"] + self._draw("gap") / 2.0, 0.0)}      # where the bus meets the west bend

    def geometry_2d(self) -> dict[str, Any]:
        plan, width = self._plan(), self._draw("waveguide_width")
        children = [_chip_box(cx, cy, w, h, GOLD, self.opacity, stroke=GOLD_EDGE, stroke_width=0.06, layer="metal")
                    for boxes in plan["boxes"].values() for cx, cy, w, h in boxes]
        children += [_chip_polyline(plan["loop"], stroke=self.color, stroke_width=width, opacity=self.opacity,
                                    closed=True),
                     _chip_box(plan["bus_x"], 0.0, width, 2.0 * plan["bus_half"], self.color, self.opacity,
                               stroke=SILICON_EDGE, stroke_width=0.08)]
        return {"type": "group", "children": children}

    def geometry_3d(self) -> dict[str, Any]:
        plan, width = self._plan(), self._draw("waveguide_width")
        stack, thickness = self._draw_layer_stack(), self._draw_thickness()
        children = [_chip_path_slab(plan["loop"], width, thickness, **self._core(), closed=True),
                    _chip_slab(width, 2.0 * plan["bus_half"], thickness, x=plan["bus_x"], **self._core())]
        children += [_chip_slab(w, h, stack["metal_height"], x=cx, y=cy, color=GOLD, preset="gold",
                                z_offset=stack["metal_z"])
                     for boxes in plan["boxes"].values() for cx, cy, w, h in boxes]
        return self._on_the_stack(children)

    def symbol_1d(self) -> tuple[str, dict[str, Any]]:
        return "eoracetrack", {}

    def physics_metadata(self) -> dict[str, Any]:
        return {"domain": "on_chip", "component": "eo_racetrack_modulator", "modulation_mechanism": "pockels",
                "drive": "gsg", "straight_length": self.straight_length, "bend_radius": self.bend_radius,
                "electrode_gap": self.electrode_gap}
