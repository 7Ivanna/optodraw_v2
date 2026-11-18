"""Grating and edge coupler components."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

from optodraw.core.ports import Port
from optodraw.core.schematic_geometry import PhysicalSpec
from optodraw.core.transform import Vec3

from optodraw.components.onchip.base import ChipComponent, _generic_pdk_defaults, SILICON_EDGE
from optodraw.components.onchip.geometry import (
    _arc_band_points,
    _arc_points,
    _chip_box,
    _chip_extruded_polygon,
    _chip_fiber_2d_children,
    _chip_fiber_3d_children,
    _chip_line,
    _chip_path_slab,
    _chip_polygon,
    _chip_polyline,
    _chip_segment_polygon,
    _chip_segment_slab,
    _chip_slab,
    _cut_footprints,
    _rotate_2d_node_ccw,
    _rotate_3d_node_ccw,
    _segment_outline,
    _translate_layout_geometry,
)

@dataclass
class VerticalGratingCoupler(ChipComponent):
    component_type = "VerticalGratingCoupler"
    schematic_family = "grating_coupler"
    length: float = 40.195
    width: float = 26.174
    tooth_pitch: float = 0.7865
    tooth_count: int = 30
    tooth_width: float = 0.343
    waveguide_width: float = 0.5
    taper_length: float = 16.6
    fiber_port_width: float = 10.0
    with_fiber: bool = False
    fiber_length: float = 18.0
    coupling_angle_deg: float | None = None

    def __init__(
        self,
        center=(0, 0),
        angle=0,
        length: float | None = None,
        width: float | None = None,
        tooth_pitch: float | None = None,
        tooth_count: int | None = None,
        tooth_width: float | None = None,
        waveguide_width: float | None = None,
        taper_length: float | None = None,
        fiber_port_width: float | None = None,
        with_fiber: bool = False,
        fiber_length: float = 18.0,
        coupling_angle_deg: float | None = None,
        **kwargs,
    ):
        defaults = _generic_pdk_defaults()
        gc = defaults["grating_coupler"]
        strip = defaults["strip"]
        raw_length = float(gc["footprint_length"] if length is None else length)
        raw_width = float(gc["footprint_width"] if width is None else width)
        raw_taper_length = float(gc["taper_length"] if taper_length is None else taper_length)
        self.waveguide_width = float(strip["width"] if waveguide_width is None else waveguide_width)
        self.tooth_count = int(gc["periods"] if tooth_count is None else tooth_count)
        self.tooth_width = float(gc["line_width"] if tooth_width is None else tooth_width)
        self.tooth_pitch = float(gc["pitch"] if tooth_pitch is None else tooth_pitch)
        self.fiber_port_width = float(gc["fiber_port_width"] if fiber_port_width is None else fiber_port_width)
        self.with_fiber = with_fiber
        self.fiber_length = float(fiber_length)
        self.coupling_angle_deg = None if coupling_angle_deg is None else float(coupling_angle_deg)
        self._init_chip(center=center, angle=angle, **kwargs)
        self.length = raw_length
        self.width = raw_width
        self.taper_length = raw_taper_length

    def physical_spec(self) -> PhysicalSpec:
        return PhysicalSpec(
            device_family=self.schematic_family,
            values={
                "length": self.length,
                "width": self.width,
                "taper_length": self.taper_length,
                "waveguide_width": self.waveguide_width,
                "fiber_port_width": self.fiber_port_width,
                "thickness": self.chip_thickness,
            },
        )

    @property
    def taper_target_width(self) -> float:
        return max(self.fiber_port_width, self.width * 0.45)

    @property
    def grating_center_x(self) -> float:
        half = self.length / 2.0
        return -half + self.taper_length + self.tooth_pitch * self.tooth_count / 2.0

    @property
    def fiber_cladding_diameter(self) -> float:
        return max(self.fiber_port_width * 1.18, self.taper_target_width * 0.92)

    @property
    def fiber_core_diameter(self) -> float:
        return max(self.fiber_port_width * 0.42, self.waveguide_width * 4.0)

    @property
    def grating_center_x_drawn(self) -> float:
        """Grating-region center in the DRAWN frame (matches geometry_2d/3d)."""
        length = self._draw("length", self.length)
        taper_length = self._draw("taper_length", self.taper_length)
        return -length / 2.0 + taper_length + self.tooth_pitch * self.tooth_count / 2.0

    def _anchor_points(self) -> dict[str, tuple[float, float]]:
        return {"grating": self._fiber_port_center()}          # the middle of the teeth, under the fibre

    def _fiber_port_center(self) -> tuple[float, float]:
        # A vertical coupler's fiber sits DIRECTLY OVER the grating teeth.
        return (self.grating_center_x_drawn, 0.0)

    def ports(self) -> dict[str, Port]:
        # The waveguide port, and the fibre port over the teeth: a fibre routed here lands on the grating
        half = self._draw("length", self.length) / 2.0
        fiber_x, fiber_y = self._fiber_port_center()
        return {
            "o1": Port("o1", Vec3(-half, 0, 0), orientation_deg=180, width=self._draw("waveguide_width", self.waveguide_width)),
            "f1": Port("f1", Vec3(fiber_x, fiber_y, 0.0), orientation_deg=90, width=self.fiber_port_width, kind="fiber"),
        }

    def geometry_2d(self) -> dict[str, Any]:
        length = self._draw("length", self.length)
        width = self._draw("width", self.width)
        taper_length = self._draw("taper_length", self.taper_length)
        waveguide_width = self._draw("waveguide_width", self.waveguide_width)
        half = length / 2.0
        grating_span = length - taper_length
        taper_target_width = max(self.fiber_port_width, width * 0.45)
        grating_center_x = -half + taper_length + self.tooth_pitch * self.tooth_count / 2.0
        children: list[dict[str, Any]] = [
            _chip_segment_polygon(
                (-half, 0.0),
                (-half + taper_length, 0.0),
                waveguide_width,
                taper_target_width,
                fill=self.color,
                opacity=self.opacity,
                stroke=SILICON_EDGE,
                stroke_width=0.08,
            ),
            _chip_box(
                grating_center_x,
                0.0,
                grating_span,
                taper_target_width,
                self.color,
                self.opacity * 0.42,
                stroke=SILICON_EDGE,
                stroke_width=0.08,
            ),
        ]
        for index in range(self.tooth_count):
            children.append(
                _chip_box(
                    -half + taper_length + self.tooth_pitch * (index + 0.5),
                    0.0,
                    self.tooth_width,
                    taper_target_width,
                    self.color,
                    self.opacity,
                )
            )
        if self.with_fiber:
            fiber_x, fiber_y = self._fiber_port_center()
            children.extend(
                _chip_fiber_2d_children(
                    fiber_x,
                    fiber_y,
                    self.fiber_cladding_diameter,
                    self.fiber_core_diameter,
                    opacity=self.opacity,
                )
            )
        return {"type": "group", "children": children}

    def geometry_3d(self) -> dict[str, Any]:
        length = self._draw("length", self.length)
        width = self._draw("width", self.width)
        taper_length = self._draw("taper_length", self.taper_length)
        waveguide_width = self._draw("waveguide_width", self.waveguide_width)
        thickness = self._draw_thickness()
        half = length / 2.0
        grating_span = length - taper_length
        taper_target_width = max(self.fiber_port_width, width * 0.45)
        grating_center_x = -half + taper_length + self.tooth_pitch * self.tooth_count / 2.0
        core = self._core()
        children: list[dict[str, Any]] = [
            _chip_segment_slab(
                (-half, 0.0),
                (-half + taper_length, 0.0),
                waveguide_width,
                taper_target_width,
                thickness,
                **core,
            ),
        ]
        for index in range(self.tooth_count):
            children.append(
                _chip_slab(
                    self.tooth_width,
                    taper_target_width,
                    thickness,
                    x=-half + taper_length + self.tooth_pitch * (index + 0.5),
                    **core,
                )
            )
        children.append(
            _chip_slab(
                grating_span,
                taper_target_width,
                thickness * 0.55,
                x=grating_center_x,
                **core,
            )
        )
        if self.with_fiber:
            fiber_x, fiber_y = self._fiber_port_center()
            children.extend(
                _chip_fiber_3d_children(
                    fiber_x,
                    fiber_y,
                    self.fiber_cladding_diameter,
                    self.fiber_core_diameter,
                    self.fiber_length,
                    base_height=self._draw_layer_stack()["core_z"] + thickness,
                )
            )
        return self._on_the_stack(children)

    def physics_metadata(self) -> dict[str, Any]:
        from optodraw.core.physics import grating_diffraction_angle_deg

        stub_wavelength_nm = 1550.0
        coupling_angle = self.coupling_angle_deg
        if coupling_angle is None:
            coupling_angle = grating_diffraction_angle_deg(self.tooth_pitch, stub_wavelength_nm)
        return {
            "domain": "on_chip",
            "component": "vertical_grating_coupler",
            "coupler_kind": "vertical",
            "tooth_pitch": self.tooth_pitch,
            "wavelength_range_nm": (1260, 1360),
            "coupling_angle_deg": coupling_angle,
        }


@dataclass
class FocusedApodizedGratingCoupler(ChipComponent):
    component_type = "FocusedApodizedGratingCoupler"
    schematic_family = "focused_grating_coupler"
    taper_length: float = 16.0
    taper_angle: float = 40.0
    extension_length: float = 1.0
    waveguide_stub_length: float = 4.0
    tooth_count: int = 25
    apodization: float = 0.031
    min_feature: float = 0.1
    wavelength: float = 1.55
    n_etched: float = 2.276
    n_unetched: float = 2.854
    n_clad: float = 1.44
    fiber_tilt_deg: float = 14.5
    fiber_port_width: float = 10.4
    waveguide_width: float = 0.5
    with_fiber: bool = False
    fiber_length: float = 18.0

    def __init__(
        self,
        center=(0, 0),
        angle=0,
        taper_length: float = 16.0,
        taper_angle: float = 40.0,
        extension_length: float = 1.0,
        waveguide_stub_length: float = 4.0,
        tooth_count: int = 25,
        apodization: float = 0.031,
        min_feature: float = 0.1,
        wavelength: float = 1.55,
        fiber_tilt_deg: float = 14.5,
        fiber_port_width: float = 10.4,
        waveguide_width: float | None = None,
        with_fiber: bool = False,
        fiber_length: float = 18.0,
        **kwargs,
    ):
        strip = _generic_pdk_defaults()["strip"]
        self.taper_length = float(taper_length)
        self.taper_angle = float(taper_angle)
        self.extension_length = float(extension_length)
        self.waveguide_stub_length = float(waveguide_stub_length)
        self.tooth_count = int(tooth_count)
        self.apodization = float(apodization)
        self.min_feature = float(min_feature)
        self.wavelength = float(wavelength)
        self.fiber_tilt_deg = float(fiber_tilt_deg)
        self.fiber_port_width = float(fiber_port_width)
        self.waveguide_width = float(strip["width"] if waveguide_width is None else waveguide_width)
        self.with_fiber = with_fiber
        self.fiber_length = float(fiber_length)
        self._init_chip(center=center, angle=angle, **kwargs)

    def physical_spec(self) -> PhysicalSpec:
        return PhysicalSpec(
            device_family=self.schematic_family,
            values={
                "taper_length": self.taper_length,
                "waveguide_width": self.waveguide_width,
                "fiber_port_width": self.fiber_port_width,
                "thickness": self.chip_thickness,
            },
        )

    def _layout_scale(self) -> float:
        if self.render_physical or self.taper_length <= 1e-9:
            return 1.0
        return self._draw("taper_length", self.taper_length) / self.taper_length

    @property
    def half_angle_deg(self) -> float:
        return self.taper_angle / 2.0

    @property
    def draw_waveguide_width(self) -> float:
        """The DRAWN input-waveguide width — physical 0.5 µm is invisible next to
        every other coupler drawn at the schematic 1.2."""
        return self._draw("waveguide_width", self.waveguide_width)

    @property
    def focus_x(self) -> float:
        alpha = math.radians(self.half_angle_deg)
        return -(self.waveguide_stub_length / 2.0) - (self.draw_waveguide_width / max(2.0 * math.tan(alpha), 1e-6))

    def _grating_profile(self) -> list[tuple[float, float]]:
        theta_gc = math.degrees(math.asin(math.sin(math.radians(self.fiber_tilt_deg)) / self.n_clad))
        theta_rad = math.radians(theta_gc)
        delta_0 = self.wavelength / (self.n_unetched - self.n_clad * math.sin(theta_rad))
        fill_0 = max((delta_0 - self.min_feature) / max(delta_0, 1e-9), 0.42)
        position = 0.0
        profile: list[tuple[float, float]] = []
        for _ in range(self.tooth_count):
            fill = max(fill_0 - self.apodization * position, 0.35)
            delta = self.wavelength / (
                self.n_etched - self.n_clad * math.sin(theta_rad) + fill * (self.n_unetched - self.n_etched)
            )
            if delta * (1.0 - fill) < self.min_feature:
                fill = max(1.0 - self.min_feature / max(delta, 1e-9), 0.35)
            profile.append((delta, fill))
            position += delta
        return profile

    @property
    def total_length(self) -> float:
        return self.waveguide_stub_length + self.taper_length + sum(delta for delta, _ in self._grating_profile()) + self.extension_length

    @property
    def waveguide_start_x(self) -> float:
        return self.focus_x - self.waveguide_stub_length

    @property
    def outer_radius(self) -> float:
        return self.taper_length + sum(delta for delta, _ in self._grating_profile()) + self.extension_length

    @property
    def grating_center_x(self) -> float:
        return self.focus_x + (self.taper_length + self.outer_radius) / 2.0

    @property
    def grating_top_y(self) -> float:
        return self.outer_radius * math.sin(math.radians(self.half_angle_deg))

    @property
    def fiber_cladding_diameter(self) -> float:
        return max(self.fiber_port_width * 1.18, self.waveguide_width * 8.0)

    @property
    def fiber_core_diameter(self) -> float:
        return max(self.fiber_port_width * 0.42, self.waveguide_width * 4.2)

    def _anchor_points(self) -> dict[str, tuple[float, float]]:
        return {"grating": self._fiber_port_center()}          # the middle of the teeth, under the fibre

    def _fiber_port_center(self) -> tuple[float, float]:
        # The fiber sits DIRECTLY OVER the grating fan, not off to the side.
        return (self.grating_center_x, 0.0)

    def ports(self) -> dict[str, Port]:
        fiber_x, fiber_y = self._fiber_port_center()
        return {
            "o1": Port("o1", Vec3(self.waveguide_start_x, 0.0, 0.0), orientation_deg=180, width=self.draw_waveguide_width),
            "f1": Port("f1", Vec3(fiber_x, fiber_y, 0.0), orientation_deg=90, width=self.fiber_port_width, kind="fiber"),
        }

    def _taper_polygon(self) -> list[tuple[float, float]]:
        ww = self.draw_waveguide_width
        return [
            (self.waveguide_start_x, -ww / 2.0),
            (self.focus_x, -ww / 2.0),
            *_arc_points(self.focus_x, 0.0, self.taper_length, -self.half_angle_deg, self.half_angle_deg, segments=40),
            (self.focus_x, ww / 2.0),
            (self.waveguide_start_x, ww / 2.0),
        ]

    def _tooth_polygons(self) -> list[list[tuple[float, float]]]:
        radius = self.taper_length
        polygons: list[list[tuple[float, float]]] = []
        for delta, fill in self._grating_profile():
            radius += delta
            inner_radius = radius - fill * delta
            polygons.append(
                _arc_band_points(
                    self.focus_x,
                    0.0,
                    inner_radius,
                    radius,
                    -self.half_angle_deg,
                    self.half_angle_deg,
                    segments=56,
                )
            )
        return polygons

    def geometry_2d(self) -> dict[str, Any]:
        children: list[dict[str, Any]] = [
            _chip_polygon(self._taper_polygon(), fill=self.color, opacity=self.opacity, stroke=SILICON_EDGE, stroke_width=0.08),
            _chip_line(self.waveguide_start_x, 0.0, self.focus_x, 0.0, stroke=self.color, stroke_width=self.draw_waveguide_width, opacity=self.opacity),
            # partial-etch slab under the curved teeth (the fan region)
            _chip_polygon(
                _arc_band_points(self.focus_x, 0.0, self.taper_length, self.outer_radius, -self.half_angle_deg, self.half_angle_deg, segments=56),
                fill=self.color,
                opacity=self.opacity * 0.42,
                stroke=SILICON_EDGE,
                stroke_width=0.05,
            ),
        ]
        for polygon in self._tooth_polygons():
            children.append(_chip_polygon(polygon, fill=self.color, opacity=self.opacity, stroke=SILICON_EDGE, stroke_width=0.04))
        if self.with_fiber:
            fiber_x, fiber_y = self._fiber_port_center()
            children.extend(
                _chip_fiber_2d_children(
                    fiber_x,
                    fiber_y,
                    self.fiber_cladding_diameter,
                    self.fiber_core_diameter,
                    opacity=self.opacity,
                )
            )
        return {"type": "group", "children": children}

    def geometry_3d(self) -> dict[str, Any]:
        children: list[dict[str, Any]] = [
            _chip_extruded_polygon(self._taper_polygon(), self.chip_thickness, **self._core()),
            _chip_slab(self.waveguide_stub_length, self.draw_waveguide_width, self.chip_thickness, x=(self.waveguide_start_x + self.focus_x) / 2.0, **self._core()),
            # partial-etch slab UNDER the teeth (was a thin SiO2 sheet floating mid-height)
            _chip_extruded_polygon(
                _arc_band_points(self.focus_x, 0.0, self.taper_length, self.outer_radius, -self.half_angle_deg, self.half_angle_deg, segments=56),
                self.chip_thickness * 0.55,
                **self._core(),
            ),
        ]
        for polygon in self._tooth_polygons():
            children.append(_chip_extruded_polygon(polygon, self.chip_thickness, **self._core()))
        if self.with_fiber:
            fiber_x, fiber_y = self._fiber_port_center()
            children.extend(
                _chip_fiber_3d_children(
                    fiber_x,
                    fiber_y,
                    self.fiber_cladding_diameter,
                    self.fiber_core_diameter,
                    self.fiber_length,
                    base_height=self._draw_layer_stack()["core_z"] + self.chip_thickness,
                )
            )
        return self._on_the_stack(children)


@dataclass
class EdgeCoupler(ChipComponent):
    component_type = "EdgeCoupler"
    schematic_family = "edge_coupler"
    taper_length: float = 28.0
    cladding_length: float = 16.0
    tip_width: float = 0.18
    waveguide_width: float = 0.5
    cladding_width: float = 4.6
    fiber_mode_diameter: float = 10.4
    with_fiber: bool = False
    fiber_length: float = 22.0

    def __init__(
        self,
        center=(0, 0),
        angle=0,
        taper_length: float = 28.0,
        cladding_length: float = 16.0,
        tip_width: float = 0.18,
        waveguide_width: float | None = None,
        cladding_width: float = 4.6,
        fiber_mode_diameter: float = 10.4,
        with_fiber: bool = False,
        fiber_length: float = 22.0,
        **kwargs,
    ):
        strip = _generic_pdk_defaults()["strip"]
        self.tip_width = float(tip_width)
        self.waveguide_width = float(strip["width"] if waveguide_width is None else waveguide_width)
        self.fiber_mode_diameter = float(fiber_mode_diameter)
        self.with_fiber = with_fiber
        self.fiber_length = float(fiber_length)
        self._init_chip(center=center, angle=angle, **kwargs)
        self.taper_length = float(taper_length)
        self.cladding_length = float(cladding_length)
        self.cladding_width = float(cladding_width)

    def physical_spec(self) -> PhysicalSpec:
        return PhysicalSpec(
            device_family=self.schematic_family,
            values={
                "taper_length": self.taper_length,
                "cladding_length": self.cladding_length,
                "total_length": self.total_length,
                "tip_width": self.tip_width,
                "waveguide_width": self.waveguide_width,
                "cladding_width": self.cladding_width,
                "fiber_mode_diameter": self.fiber_mode_diameter,
                "thickness": self.chip_thickness,
            },
        )

    def _draw_variant(self) -> EdgeCoupler:
        if self.render_physical:
            return self
        return EdgeCoupler(
            taper_length=self._draw("taper_length", self.taper_length),
            cladding_length=self._draw("cladding_length", self.cladding_length),
            tip_width=self.tip_width,
            waveguide_width=self._draw("waveguide_width", self.waveguide_width),
            cladding_width=self._draw("cladding_width", self.cladding_width),
            fiber_mode_diameter=self.fiber_mode_diameter,
            with_fiber=self.with_fiber,
            fiber_length=self.fiber_length,
            **self._draw_variant_kwargs(),
        )

    @property
    def total_length(self) -> float:
        return self.taper_length + self.cladding_length

    @property
    def chip_edge_x(self) -> float:
        return -self.total_length / 2.0

    @property
    def taper_tip_x(self) -> float:
        return self.chip_edge_x + self.cladding_length * 0.32

    @property
    def waveguide_end_x(self) -> float:
        return self.total_length / 2.0

    def _silicon_polygon(self) -> list[tuple[float, float]]:
        return _segment_outline(
            (self.taper_tip_x, 0.0),
            (self.waveguide_end_x, 0.0),
            self.tip_width,
            self.waveguide_width,
        )

    def _oxide_polygon(self) -> list[tuple[float, float]]:
        return [
            (self.chip_edge_x, -self.cladding_width / 2.0),
            (self.taper_tip_x + self.cladding_length * 0.85, -self.cladding_width * 0.44),
            (self.taper_tip_x + self.cladding_length * 0.85, self.cladding_width * 0.44),
            (self.chip_edge_x, self.cladding_width / 2.0),
        ]

    def ports(self) -> dict[str, Port]:
        draw = self._draw_variant()
        if draw is not self:
            return draw.ports()
        return {
            "f1": Port("f1", Vec3(self.chip_edge_x, 0.0, 0.0), orientation_deg=180, width=self.fiber_mode_diameter, kind="fiber"),
            "o1": Port("o1", Vec3(self.waveguide_end_x, 0.0, 0.0), orientation_deg=0, width=self._draw("waveguide_width", self.waveguide_width)),
        }

    def geometry_2d(self) -> dict[str, Any]:
        draw = self._draw_variant()
        if draw is not self:
            return draw.geometry_2d()

        children: list[dict[str, Any]] = [
            _chip_polygon(self._oxide_polygon(), fill="#d8eef7", opacity=self.opacity * 0.48, stroke="#8ab2d0", stroke_width=0.08),
            _chip_polygon(self._silicon_polygon(), fill=self.color, opacity=self.opacity, stroke=SILICON_EDGE, stroke_width=0.08),
            _chip_line(self.chip_edge_x, 0.0, self.taper_tip_x, 0.0, stroke=self.color, stroke_width=self.tip_width, opacity=self.opacity),
        ]
        if self.with_fiber:
            children.append(
                _chip_box(
                    self.chip_edge_x - self.fiber_length / 2.0,
                    0.0,
                    self.fiber_length,
                    self.fiber_mode_diameter * 0.86,
                    "#d8eef7",
                    self.opacity * 0.54,
                    stroke="#6f98aa",
                    stroke_width=0.08,
                )
            )
        return {"type": "group", "children": children}

    def geometry_3d(self) -> dict[str, Any]:
        draw = self._draw_variant()
        if draw is not self:
            return draw.geometry_3d()

        t = self.chip_thickness
        stack = self._draw_layer_stack()
        top = stack["core_z"] + t
        core = [
            _chip_extruded_polygon(self._silicon_polygon(), t, **self._core()),
            _chip_segment_slab((self.chip_edge_x, 0.0), (self.taper_tip_x, 0.0), self.tip_width, self.tip_width, t, **self._core()),
        ]
        # the cladding over the tip: from the buried oxide up to M1, as the stack has it. Beside the core it starts
        # on the buried oxide; over the core, on the core top. Where both end on the core top, the core owns it.
        lower = _chip_extruded_polygon(self._oxide_polygon(), top, color="#d8eef7", preset="sio2", opacity=0.42)
        children: list[dict[str, Any]] = [
            *core,
            *_cut_footprints([lower], core),
            _chip_extruded_polygon(self._oxide_polygon(), stack["metal_z"] - top, color="#d8eef7",
                                   preset="sio2", opacity=0.42, z_offset=top),
        ]
        films = self._foundry_core()
        if films is not None and films.over:              # a film stack (InP): its films over the core clad it
            children = core
        if self.with_fiber:
            # a round fibre resting on the chip, butted against the facet (it was a glass sheet 0.1 thick)
            radius, x = self.fiber_mode_diameter * 0.43, self.chip_edge_x - self.fiber_length / 2.0
            along_x = [0.0, 0.0, math.pi / 2.0]
            children += [
                {"shape": "cylinder", "radius": radius, "height": self.fiber_length, "rotation": along_x,
                 "position": [x, radius, 0.0], "material": {"color": "#c9dceb", "opacity": 0.82, "transparent": True, "preset": "glass"}},
                {"shape": "cylinder", "radius": radius * 0.3, "height": self.fiber_length, "rotation": along_x,
                 "position": [x, radius, 0.0], "material": {"color": "#eef8ff", "opacity": 0.9, "transparent": True}},
            ]
        return self._on_the_stack(children)


@dataclass
class GratingCouplerArray(ChipComponent):
    schematic_family = "grating_coupler_array"
    """A row of grating couplers at a fixed pitch in PIC-array orientation.

    Each coupler is displayed **upright** — grating opening toward +Y (fiber
    from above), optical waveguide port exiting toward −Y into the chip.  A
    straight ``stub_length`` waveguide extends down from every optical port
    before any bend is added by the router.

    When ``align_ends=True`` the leftmost and rightmost couplers are connected
    by a U-shaped waveguide loop that runs below the stub:

        ↑ f1       ↑ f2          ↑ fN   (fiber ports, top)
        ┃  ···      ┃             ┃
       [GC1]  ··· [GC2]  ···   [GCN]   (upright grating coupler bodies)
        ┃           ┃             ┃      (stubs – straight exit waveguides)
        ┗━━━━━━━━━━━━━━━━━━━━━━━━━┛      (alignment U-loop, bottom)

    Ports:
        o{i}  — optical chip port for coupler i (exits downward, orientation 270°)
        f{i}  — fiber coupling port for coupler i (points upward, orientation 90°)
    """
    component_type = "GratingCouplerArray"
    count: int = 8
    pitch: float = 127.0
    coupler_kind: str = "vertical"
    align_ends: bool = False
    stub_length: float = 10.0
    alignment_drop: float = 35.0
    alignment_waveguide_width: float | None = None
    with_fiber: bool = False

    def __init__(
        self,
        center=(0, 0),
        angle=0,
        count: int = 8,
        pitch: float = 127.0,
        coupler_kind: str = "vertical",
        align_ends: bool = False,
        stub_length: float = 10.0,
        alignment_drop: float = 35.0,
        alignment_waveguide_width: float | None = None,
        with_fiber: bool = False,
        **kwargs,
    ):
        self.count = int(count)
        self.pitch = float(pitch)
        self.coupler_kind = coupler_kind.lower().strip()
        self.align_ends = bool(align_ends)
        self.stub_length = float(stub_length)
        self.alignment_drop = float(alignment_drop)
        self.alignment_waveguide_width = alignment_waveguide_width
        self.with_fiber = bool(with_fiber)
        self._init_chip(center=center, angle=angle, **kwargs)

    def physical_spec(self) -> PhysicalSpec:
        width = self.pitch * max(self.count - 1, 0)
        return PhysicalSpec(
            device_family=self.schematic_family,
            values={
                "count": self.count,
                "pitch": self.pitch,
                "array_width": width,
                "stub_length": self.stub_length,
                "alignment_drop": self.alignment_drop,
                "alignment_waveguide_width": self.alignment_waveguide_width or 0.0,
                "align_ends": self.align_ends,
                "with_fiber": self.with_fiber,
                "thickness": self.chip_thickness,
            },
        )

    def _validate(self) -> None:
        if self.count < 1:
            raise ValueError("count must be >= 1")
        if self.pitch <= 0.0:
            raise ValueError("pitch must be > 0")
        if self.align_ends and self.count < 2:
            raise ValueError("align_ends=True requires count >= 2")
        if self.alignment_drop <= 0.0:
            raise ValueError("alignment_drop must be > 0")
        if self.coupler_kind not in {"vertical", "focused"}:
            raise ValueError("coupler_kind must be either 'vertical' or 'focused'")

    @property
    def x_positions(self) -> list[float]:
        return self._positions_for_pitch(self.pitch)

    def _positions_for_pitch(self, pitch: float) -> list[float]:
        center_index = (self.count - 1) / 2.0
        return [(index - center_index) * pitch for index in range(self.count)]

    def _draw_x_positions(self) -> list[float]:
        return self._positions_for_pitch(self._draw("pitch", self.pitch))

    def _template_coupler(self) -> ChipComponent:
        """Return one zero-rotation template coupler using our style kwargs."""
        kwargs: dict[str, Any] = {
            "color": self.color,
            "opacity": self.opacity,
            "chip_thickness": self.chip_thickness,
            "material_preset": self.material_preset,
            "render_physical": self.render_physical,
            "visual_scale": self.visual_scale,
            # Inherit the array's feature-exaggeration so couplers gain 3D height
            # together (the array's z-knob now actually lifts the couplers).
            "z_exaggeration": self.z_exaggeration,
            "width_exaggeration": self.width_exaggeration,
            "length_exaggeration": self.length_exaggeration,
            # Never draw the fiber bubble inside the array geometry – we handle
            # fiber port positions separately so they remain correctly above the
            # grating after the 90° CCW rotation.
            "with_fiber": False,
            **self._stack_kwargs(),
        }
        if self.coupler_kind == "focused":
            return FocusedApodizedGratingCoupler(center=(0, 0), angle=0, **kwargs)
        return VerticalGratingCoupler(center=(0, 0), angle=0, **kwargs)

    # ------------------------------------------------------------------
    # Geometry helpers
    # ------------------------------------------------------------------

    def _rotated_coupler_geo_2d(self, template: ChipComponent, x_offset: float) -> list[dict[str, Any]]:
        """Return 2D children for one coupler at x_offset, rotated 90° CCW.

        The rotation maps the template's horizontal orientation (grating → +X,
        waveguide → −X) to the upright array orientation (grating → +Y,
        waveguide → −Y). After rotation the template center stays at origin,
        then we translate by x_offset.
        """
        raw_geo = template.geometry_2d()
        rotated = _rotate_2d_node_ccw(raw_geo)
        translated = _translate_layout_geometry(rotated, x_offset, 0.0)
        children = translated.get("children", [])

        # If with_fiber is requested, hover the fiber DIRECTLY OVER the grating
        # teeth: the template's local grating center (gx, 0) lands at (0, gx)
        # after the 90° CCW rotation.
        if self.with_fiber and hasattr(template, "fiber_cladding_diameter"):
            clad_d = template.fiber_cladding_diameter  # type: ignore[attr-defined]
            core_d = template.fiber_core_diameter  # type: ignore[attr-defined]
            fiber_cy = self._grating_center_rotated_y(template)
            children = list(children) + _chip_fiber_2d_children(
                x_offset, fiber_cy, clad_d, core_d, opacity=self.opacity
            )

        return list(children)

    def _rotated_coupler_geo_3d(self, template: ChipComponent, x_offset: float) -> list[dict[str, Any]]:
        """Return 3D children for one coupler at x_offset, rotated 90° CCW."""
        raw_geo = template.geometry_3d()
        rotated = _rotate_3d_node_ccw(raw_geo)
        translated = _translate_layout_geometry(rotated, x_offset, 0.0)
        children = translated.get("children", [])

        if self.with_fiber and hasattr(template, "fiber_cladding_diameter"):
            clad_d = template.fiber_cladding_diameter  # type: ignore[attr-defined]
            core_d = template.fiber_core_diameter  # type: ignore[attr-defined]
            fiber_length = getattr(template, "fiber_length", 18.0)
            fiber_cy = self._grating_center_rotated_y(template)
            children = list(children) + _chip_fiber_3d_children(
                x_offset, fiber_cy, clad_d, core_d, fiber_length,
                base_height=self._draw_layer_stack()["core_z"] + self.chip_thickness,
            )

        return list(children)

    def _grating_center_rotated_y(self, template: ChipComponent) -> float:
        """Y of the template's grating center after the array's 90° CCW rotation."""
        gx = getattr(template, "grating_center_x_drawn", None)
        if gx is None:
            gx = getattr(template, "grating_center_x", 0.0)
        return float(gx)

    # After the 90° CCW rotation the template's o1 port was at (−half, 0)
    # and now sits at (0, −half).  Add a straight downward stub from there.

    def _template_half_length(self, template: ChipComponent, *, draw: bool = False) -> float:
        length = getattr(template, "length", 40.0)
        if draw and not self.render_physical:
            length = template._draw("length", length)
        return float(length) / 2.0

    def _stub_y_top(self, template: ChipComponent) -> float:
        """Y of the optical port (base of the stub) in the rotated frame.

        Anchored to the template's REAL ``o1`` port — not an assumed centered
        body length. The focused coupler has no ``length`` attribute, so the old
        40-unit fallback opened a visible gap between stub and taper when the
        array switched to ``coupler_kind="focused"``.
        """
        return float(template.ports()["o1"].center.x)

    def _draw_stub_y_top(self, template: ChipComponent) -> float:
        return self._stub_y_top(template)

    def _stub_y_bottom(self, template: ChipComponent, *, draw: bool = False) -> float:
        """Y of the stub tip — where the bend toward the rest of the chip begins."""
        if draw:
            return self._draw_stub_y_top(template) - self._draw("stub_length", self.stub_length)
        return self._stub_y_top(template) - self.stub_length

    def _waveguide_width(self, template: ChipComponent, *, draw: bool = False) -> float:
        if draw and not self.render_physical:
            return template._draw("waveguide_width", float(getattr(template, "waveguide_width", 0.5)))
        return float(getattr(template, "waveguide_width", 0.5))

    def _alignment_path(self, template: ChipComponent, *, draw: bool = False) -> tuple[list[tuple[float, float]], float]:
        """U-loop path connecting the two end couplers below the stubs."""
        if not self.align_ends or self.count < 2:
            return ([], 0.0)
        x_positions = self._draw_x_positions() if draw else self.x_positions
        left_x = x_positions[0]
        right_x = x_positions[-1]
        y_top = self._stub_y_bottom(template, draw=draw)
        y_loop = y_top - (self._draw("alignment_drop", self.alignment_drop) if draw else self.alignment_drop)
        width = (
            float(self.alignment_waveguide_width)
            if self.alignment_waveguide_width is not None
            else self._waveguide_width(template, draw=draw)
        )
        # Path: down from left stub tip → across bottom → up to right stub tip
        return ([(left_x, y_top), (left_x, y_loop), (right_x, y_loop), (right_x, y_top)], width)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def _anchor_points(self) -> dict[str, tuple[float, float]]:
        return {f"grating{name[1:]}": (float(port.center.x), float(port.center.y))   # each under its fibre
                for name, port in self.ports().items() if port.kind == "fiber"}

    def ports(self) -> dict[str, Port]:
        self._validate()
        template = self._template_coupler()
        # One optical (waveguide) port per coupler — exits downward at the stub tip.
        # Positions track the drawn (compacted) pitch; render_physical restores 127µm.
        ww = self._waveguide_width(template, draw=True)
        stub_bottom_y = self._stub_y_bottom(template, draw=True)
        fiber_y = self._grating_center_rotated_y(template)
        fiber_width = float(getattr(template, "fiber_port_width", 10.4))
        ports: dict[str, Port] = {}
        for index, x_off in enumerate(self._draw_x_positions(), start=1):
            ports[f"o{index}"] = Port(
                f"o{index}",
                Vec3(x_off, stub_bottom_y, 0.0),
                orientation_deg=270.0,
                width=ww,
            )
            ports[f"f{index}"] = Port(
                f"f{index}",
                Vec3(x_off, fiber_y, 0.0),
                orientation_deg=90.0,
                width=fiber_width,
                kind="fiber",
            )
        return ports

    def symbol_1d(self) -> tuple[str, dict[str, Any]]:
        return "gratingarray", {"count": int(self.count)}

    def geometry_2d(self) -> dict[str, Any]:
        self._validate()
        template = self._template_coupler()
        ww = self._waveguide_width(template, draw=True)
        stub_top_y = self._draw_stub_y_top(template)
        stub_bottom_y = self._stub_y_bottom(template, draw=True)

        children: list[dict[str, Any]] = []

        for x_off in self._draw_x_positions():
            # Rotated coupler body
            children.extend(self._rotated_coupler_geo_2d(template, x_off))
            # Straight stub going down from the optical port
            children.append(
                _chip_line(
                    x_off, stub_top_y,
                    x_off, stub_bottom_y,
                    stroke=self.color,
                    stroke_width=ww,
                    opacity=self.opacity,
                )
            )

        path, width = self._alignment_path(template, draw=True)
        if path:
            children.append(
                _chip_polyline(
                    path,
                    stroke=self.color,
                    stroke_width=width,
                    opacity=self.opacity,
                )
            )

        return {"type": "group", "children": children}

    def geometry_3d(self) -> dict[str, Any]:
        self._validate()
        template = self._template_coupler()
        ww = self._waveguide_width(template, draw=True)
        stub_top_y = self._draw_stub_y_top(template)
        stub_bottom_y = self._stub_y_bottom(template, draw=True)

        children: list[dict[str, Any]] = []
        couplers: list[dict[str, Any]] = []                # each on the stack already

        for x_off in self._draw_x_positions():
            couplers.extend(self._rotated_coupler_geo_3d(template, x_off))
            # Straight downward stub: ww wide (x) × stub_length tall (y), same exaggerated
            # thickness as the couplers so it reads as one connected waveguide (no tilt).
            stub_cx = x_off
            stub_cy = (stub_top_y + stub_bottom_y) / 2.0
            children.append(
                _chip_slab(
                    ww,
                    self._draw("stub_length", self.stub_length),
                    self._draw_thickness(),
                    x=stub_cx,
                    y=stub_cy,
                    **self._core(),
                )
            )

        path, width = self._alignment_path(template, draw=True)
        if path:
            children.append(
                _chip_path_slab(
                    path,
                    width,
                    self.chip_thickness,
                    **self._core(),
                )
            )

        return {"shape": "group", "children": [*couplers, *self._on_the_stack(children)["children"]]}


@dataclass
class TwoDGratingCoupler(ChipComponent):
    """Polarization-splitting 2D grating coupler — a square grating with a hole array
    that couples a fiber's two polarizations into two perpendicular waveguides."""

    component_type = "TwoDGratingCoupler"
    schematic_family = "grating_coupler_2d"
    body_size: float = 20.0
    taper_length: float = 16.0
    waveguide_width: float = 0.5
    hole_rows: int = 7
    with_fiber: bool = False
    fiber_length: float = 18.0

    _HOLE = "#0a2c34"

    def __init__(self, center=(0, 0), angle=0, body_size=20.0, taper_length=16.0, waveguide_width: float | None = None, hole_rows=7, with_fiber=False, fiber_length=18.0, **kwargs):
        strip = _generic_pdk_defaults()["strip"]
        self.body_size = float(body_size)
        self.taper_length = float(taper_length)
        self.waveguide_width = float(strip["width"] if waveguide_width is None else waveguide_width)
        self.hole_rows = int(hole_rows)
        self.with_fiber = bool(with_fiber)
        self.fiber_length = float(fiber_length)
        self._init_chip(center=center, angle=angle, **kwargs)

    def physical_spec(self) -> PhysicalSpec:
        return PhysicalSpec(
            device_family=self.schematic_family,
            values={"body_size": self.body_size, "taper_length": self.taper_length, "waveguide_width": self.waveguide_width, "thickness": self.chip_thickness},
        )

    def _anchor_points(self) -> dict[str, tuple[float, float]]:
        return {"grating": (0.0, 0.0)}                          # the hole lattice, under the fibre

    def ports(self) -> dict[str, Port]:
        reach = self.body_size / 2.0 + self.taper_length
        w = self._draw("waveguide_width", self.waveguide_width)
        return {
            "o1": Port("o1", Vec3(-reach, 0, 0), orientation_deg=180, width=w),    # TE waveguide (west)
            "o2": Port("o2", Vec3(0, -reach, 0), orientation_deg=270, width=w),    # TM waveguide (south)
            "f1": Port("f1", Vec3(0, 0, 0), orientation_deg=90, width=self.body_size * 0.62, kind="fiber"),
        }

    def _hole_centres(self) -> tuple[list[tuple[float, float]], float]:
        n = max(self.hole_rows, 2)
        b = self.body_size
        step = b / (n + 1)
        return [(-b / 2.0 + step * i, -b / 2.0 + step * j) for i in range(1, n + 1) for j in range(1, n + 1)], step * 0.42

    def _holes(self) -> list[dict[str, Any]]:
        centres, size = self._hole_centres()
        return [_chip_box(cx, cy, size, size, self._HOLE, self.opacity * 0.85) for cx, cy in centres]

    def geometry_2d(self) -> dict[str, Any]:
        b2 = self.body_size / 2.0
        edge = b2 + self.taper_length
        children = [
            _chip_segment_polygon((-edge, 0.0), (-b2, 0.0), self._draw("waveguide_width", self.waveguide_width), self.body_size, fill=self.color, opacity=self.opacity, stroke=SILICON_EDGE, stroke_width=0.08),
            _chip_segment_polygon((0.0, -edge), (0.0, -b2), self._draw("waveguide_width", self.waveguide_width), self.body_size, fill=self.color, opacity=self.opacity, stroke=SILICON_EDGE, stroke_width=0.08),
            _chip_box(0.0, 0.0, self.body_size, self.body_size, self.color, self.opacity, stroke=SILICON_EDGE, stroke_width=0.1),
            *self._holes(),
        ]
        if self.with_fiber:
            children += _chip_fiber_2d_children(0.0, 0.0, self.body_size * 0.62, self.body_size * 0.42, opacity=self.opacity)
        return {"type": "group", "children": children}

    def geometry_3d(self) -> dict[str, Any]:
        t = self._draw_thickness()
        core = self._core()
        b2 = self.body_size / 2.0
        edge = b2 + self.taper_length
        children = [
            _chip_segment_slab((-edge, 0.0), (-b2, 0.0), self._draw("waveguide_width", self.waveguide_width), self.body_size, t, **core),
            _chip_segment_slab((0.0, -edge), (0.0, -b2), self._draw("waveguide_width", self.waveguide_width), self.body_size, t, **core),
        ]
        # the body with its etched hole grid, as in 2D: the fibre stands over it
        centres, size = self._hole_centres()
        b2, h = self.body_size / 2.0, size / 2.0
        body = _chip_extruded_polygon([(-b2, -b2), (b2, -b2), (b2, b2), (-b2, b2)], t, **core)
        body["holes"] = [[(cx - h, cy - h), (cx + h, cy - h), (cx + h, cy + h), (cx - h, cy + h)] for cx, cy in centres]
        children.append(body)
        if self.with_fiber:
            children += _chip_fiber_3d_children(0.0, 0.0, self.body_size * 0.62, self.body_size * 0.42, self.fiber_length,
                                                base_height=self._draw_layer_stack()["core_z"] + t)
        return self._on_the_stack(children)

    def physics_metadata(self) -> dict[str, Any]:
        return {"domain": "on_chip", "component": "grating_coupler_2d", "mode": "polarization"}


class GratingAntennaArray(ChipComponent):
    """The emitters of an optical phased array: ``count`` parallel waveguides on a ``pitch``, each with a shallow
    etched grating along its top that sends the guided light up out of the chip.

    The light enters each grating at its west end (``o1`` the lowest, up to ``o{count}``) and leaves upward along
    the grating, so the array has no output ports. The teeth stand at full core height on a floor that the
    ``etch_depth`` thins (Van Acoleyen et al., Opt. Lett. 34, 1477 (2009): 16 gratings at 2 um, 630 nm period,
    70 nm etch in 220 nm silicon). In a schematic the pitch, the length and the teeth are drawn to read.
    """

    component_type = "GratingAntennaArray"
    schematic_family = "grating_antenna_array"
    _TEETH_DRAWN = 10                       # a schematic draws ten teeth; the physical period would be a grey band

    def __init__(self, center=(0, 0), angle=0, count: int = 8, pitch: float = 2.0, length: float = 31.5,
                 period: float = 0.63, etch_depth: float = 0.07, waveguide_width: float = 0.8, **kwargs):
        if int(count) < 1:
            raise ValueError("count must be at least 1")
        if not 0.0 < float(etch_depth) < float(kwargs.get("chip_thickness", 0.22)):
            raise ValueError("etch_depth must be above 0 and below the core thickness")
        self.count = int(count)
        self.pitch = float(pitch)
        self.length = float(length)
        self.period = float(period)
        self.etch_depth = float(etch_depth)
        self.waveguide_width = float(waveguide_width)
        self._init_chip(center=center, angle=angle, **kwargs)

    def physical_spec(self) -> PhysicalSpec:
        return PhysicalSpec(device_family=self.schematic_family, values={
            "count": self.count, "pitch": self.pitch, "length": self.length, "period": self.period,
            "etch_depth": self.etch_depth, "waveguide_width": self.waveguide_width, "thickness": self.chip_thickness})

    def _channel_ys(self) -> list[float]:
        pitch = self._draw("pitch", self.pitch)
        return [(index - (self.count - 1) / 2.0) * pitch for index in range(self.count)]

    def _teeth_x(self) -> tuple[list[float], float]:
        """The centre of each tooth and the tooth width: half of each period is a tooth."""

        length = self._draw("length", self.length)
        count = max(int(round(self.length / self.period)), 1) if self.render_physical else self._TEETH_DRAWN
        step = length / count
        return [-length / 2.0 + step * (index + 0.5) for index in range(count)], step / 2.0

    def ports(self) -> dict[str, Port]:
        half, width = self._draw("length", self.length) / 2.0, self._draw("waveguide_width", self.waveguide_width)
        return {f"o{index + 1}": Port(f"o{index + 1}", Vec3(-half, y, 0), orientation_deg=180, width=width)
                for index, y in enumerate(self._channel_ys())}

    def symbol_1d(self) -> tuple[str, dict[str, Any]]:
        return "antennaarray", {"count": self.count}

    def geometry_2d(self) -> dict[str, Any]:
        length, width = self._draw("length", self.length), self._draw("waveguide_width", self.waveguide_width)
        teeth, tooth = self._teeth_x()
        children: list[dict[str, Any]] = []
        for y in self._channel_ys():                      # the etched floor pale, the teeth at full strength
            children.append(_chip_box(0.0, y, length, width, self.color, self.opacity * 0.42,
                                      stroke=SILICON_EDGE, stroke_width=0.08))
            children += [_chip_box(x, y, tooth, width, self.color, self.opacity) for x in teeth]
        return {"type": "group", "children": children}

    def geometry_3d(self) -> dict[str, Any]:
        length, width = self._draw("length", self.length), self._draw("waveguide_width", self.waveguide_width)
        thickness = self._draw_thickness()
        floor = thickness * (1.0 - self.etch_depth / self.chip_thickness)
        teeth, tooth = self._teeth_x()
        children: list[dict[str, Any]] = []
        for y in self._channel_ys():                      # every solid stands on the buried oxide, as the core does
            children.append(_chip_slab(length, width, floor, y=y, **self._core()))
            children += [_chip_slab(tooth, width, thickness, x=x, y=y, **self._core()) for x in teeth]
        return self._on_the_stack(children)

    def physics_metadata(self) -> dict[str, Any]:
        return {"domain": "on_chip", "component": "grating_antenna_array", "count": self.count, "pitch": self.pitch,
                "period": self.period, "length": self.length, "etch_depth": self.etch_depth,
                "grating_lobe_deg": _grating_lobe_deg(self.pitch, 1550.0)}


def _grating_lobe_deg(pitch_um: float, wavelength_nm: float) -> float | None:
    """The first grating lobe of a uniform array, arcsin(lambda / d) (Van Acoleyen 2009: 50.8 deg at 2 um);
    None when the pitch is under one wavelength and no lobe exists."""

    ratio = wavelength_nm / 1000.0 / pitch_um
    return math.degrees(math.asin(ratio)) if ratio <= 1.0 else None
