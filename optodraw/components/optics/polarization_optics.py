"""Polarization optics free-space optics."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from optodraw.core.component import Component
from optodraw.core.ports import Port
from optodraw.core.transform import Vec3

from ._shared import (
    _KNOB_STEEL,
    _MOUNT_ALU,
    _MOUNT_BLACK,
    _cylinder_along_x,
    _frame_holder,
    _optical_metadata,
    _post_boss,
    _ring_along_x,
    _round_optic_2d,
    _round_optic_3d,
    _set_common_free_space_fields,
    _through_ports,
    _transparent_material,
)


@dataclass
class Polarizer(Component):
    """Linear polarizer with transmission axis and extinction ratio metadata."""

    component_type = "Polarizer"
    aperture: float = 10.0
    thickness: float = 0.8
    axis_angle: float = 0.0
    extinction_ratio: float = 1000.0

    def __init__(self, center=(0, 0), angle=0, aperture=10.0, thickness=0.8, axis_angle=0.0, extinction_ratio=1000.0, **kwargs):
        self.aperture = aperture
        self.thickness = thickness
        self.axis_angle = axis_angle
        self.extinction_ratio = extinction_ratio
        _set_common_free_space_fields(self, center, angle, kwargs, color="#5867dd", opacity=0.52, material_preset="glass")

    def geometry_2d(self) -> dict[str, Any]:
        stripe_count = 5
        stripe_spacing = self.aperture * 0.72 / (stripe_count + 1)
        children = _round_optic_2d(self.aperture, self.color, self.opacity, stroke="#30387e")
        for stripe_index in range(stripe_count):
            stripe_y = -self.aperture * 0.36 + stripe_spacing * (stripe_index + 1)
            children.append({"type": "line", "x1": -self.aperture * 0.28, "y1": stripe_y, "x2": self.aperture * 0.28, "y2": stripe_y, "stroke": "#eff2ff", "stroke_width": 0.08, "opacity": 0.75})
        children.append({"type": "line", "x1": 0.0, "y1": -self.aperture * 0.32, "x2": 0.0, "y2": self.aperture * 0.32, "stroke": "#111827", "stroke_width": 0.12, "opacity": 0.9})
        return {"type": "group", "children": children}

    def geometry_3d(self) -> dict[str, Any]:
        children = _round_optic_3d(self.aperture, self.thickness, self.color, self.opacity, self.material_preset, frame_color="#272d35")
        children.append(_post_boss(self.aperture * 0.51 + max(self.thickness * 0.12, 0.16), self.thickness * 1.15))
        # glass substrate carrying the polarizing film (gives the optic real body)
        children.append(_cylinder_along_x(self.aperture * 0.4, self.thickness * 1.6,
                        {"color": "#10141a", "metalness": 0.2, "roughness": 0.5, "opacity": 0.7, "transparent": True},
                        position=[-self.thickness * 0.7, 0.0, 0.0]))
        stripe_count = 5
        stripe_spacing = self.aperture * 0.72 / (stripe_count + 1)
        for stripe_index in range(stripe_count):
            stripe_y = -self.aperture * 0.36 + stripe_spacing * (stripe_index + 1)
            children.append({"shape": "box", "width": 0.06, "height": 0.035, "depth": self.aperture * 0.58, "position": [self.thickness * 0.72, stripe_y, 0.0], "material": {"color": "#eef2ff", "opacity": 0.78, "transparent": True}})
        return {
            "shape": "group",
            "children": children,
        }

    def physics_metadata(self) -> dict[str, Any]:
        return _optical_metadata("linear_polarizer", axis_angle=self.axis_angle, extinction_ratio=self.extinction_ratio)


@dataclass
class Analyzer(Polarizer):
    """Analyzer optic, represented as a linear polarizer in a measurement arm."""

    component_type = "Analyzer"

    def __init__(self, center=(0, 0), angle=0, aperture=10.0, thickness=0.8, axis_angle=90.0, extinction_ratio=1000.0, **kwargs):
        kwargs.setdefault("color", "#7c4dff")
        kwargs.setdefault("label", "Analyzer")
        super().__init__(center=center, angle=angle, aperture=aperture, thickness=thickness, axis_angle=axis_angle, extinction_ratio=extinction_ratio, **kwargs)

    def physics_metadata(self) -> dict[str, Any]:
        return _optical_metadata("analyzer", axis_angle=self.axis_angle, extinction_ratio=self.extinction_ratio)


@dataclass
class WavePlate(Component):
    """Retarder plate with fast-axis metadata."""

    component_type = "WavePlate"
    aperture: float = 10.0
    thickness: float = 0.7
    retardance: float = math.pi
    fast_axis_angle: float = 0.0
    design_wavelength_nm: float | None = None

    def __init__(self, center=(0, 0), angle=0, aperture=10.0, thickness=0.7, retardance=math.pi, fast_axis_angle=0.0, design_wavelength_nm=None, **kwargs):
        self.aperture = aperture
        self.thickness = thickness
        self.retardance = retardance
        self.fast_axis_angle = fast_axis_angle
        self.design_wavelength_nm = design_wavelength_nm
        _set_common_free_space_fields(self, center, angle, kwargs, color="#66c2a5", opacity=0.5, material_preset="glass")

    def symbol_1d(self) -> tuple[str, dict[str, Any]]:
        for kind, turn in (("half", math.pi), ("quarter", math.pi / 2.0)):
            if math.isclose(self.retardance, turn):
                return "waveplate", {"kind": kind}
        return "waveplate", {}

    def geometry_2d(self) -> dict[str, Any]:
        axis_length = self.aperture * 0.72
        return {
            "type": "group",
            "children": [
                *_round_optic_2d(self.aperture, self.color, self.opacity, stroke="#2f7567"),
                {"type": "line", "x1": -axis_length / 2.0, "y1": -axis_length / 2.0, "x2": axis_length / 2.0, "y2": axis_length / 2.0, "stroke": "#f8fffc", "stroke_width": 0.12, "opacity": 0.85},
                {"type": "line", "x1": axis_length / 2.0, "y1": -axis_length / 2.0, "x2": -axis_length / 2.0, "y2": axis_length / 2.0, "stroke": "#1f4d44", "stroke_width": 0.08, "opacity": 0.6},
            ],
        }

    def geometry_3d(self) -> dict[str, Any]:
        ap, th = self.aperture, self.thickness
        # Waveplate seated in an indexed rotation mount (RSP05 silhouette): a black
        # housing ring, a brushed rotating cell holding the glass, graduation ticks
        # around the front face, and a radial thumbscrew at the bottom.
        children: list[dict[str, Any]] = [
            *_round_optic_3d(ap, th, self.color, self.opacity, self.material_preset, frame_color="#2d3740"),
            {"shape": "box", "width": 0.06, "height": ap * 0.62, "depth": 0.04, "rotation": [0.0, 0.0, math.radians(38.0)], "position": [th * 0.7, 0.0, 0.0], "material": {"color": "#f8fffc", "opacity": 0.78, "transparent": True}},
            # rotation mount as TRUE rings: the waveplate is seated in the rotating
            # cell's bore, and the housing bore stays open so the glass shows from behind
            _ring_along_x(ap * 0.47, ap * 0.55, th * 0.9, _MOUNT_ALU, x=th * 0.4),
            _ring_along_x(ap * 0.42, ap * 0.66, th * 2.0, _MOUNT_BLACK, x=th * 1.6),
            # radial lock screw on top of the housing; the post holds a boss under it
            {"shape": "cylinder", "radius": ap * 0.055, "height": ap * 0.2, "position": [th * 1.6, ap * 0.75, 0.0], "material": _KNOB_STEEL},
            _post_boss(ap * 0.66, th * 2.0, x=th * 1.6),
        ]
        # graduation ticks around the front face of the housing
        for k in range(12):
            a = 2.0 * math.pi * k / 12.0
            children.append({
                "shape": "box", "width": 0.06, "height": ap * 0.075, "depth": 0.05,
                "rotation": [a, 0.0, 0.0],
                "position": [th * 0.55, math.sin(a) * ap * 0.62, math.cos(a) * ap * 0.62],
                "material": _MOUNT_ALU,
            })
        return {"shape": "group", "children": children}

    def physics_metadata(self) -> dict[str, Any]:
        meta = _optical_metadata("wave_plate", retardance=self.retardance, fast_axis_angle=self.fast_axis_angle)
        if self.design_wavelength_nm is not None:
            meta["design_wavelength_nm"] = self.design_wavelength_nm
        return meta


@dataclass
class HalfWavePlate(WavePlate):
    """Half-wave plate convenience component."""

    component_type = "HalfWavePlate"

    def __init__(self, center=(0, 0), angle=0, aperture=10.0, thickness=0.7, fast_axis_angle=0.0, **kwargs):
        kwargs.setdefault("label", "HWP")
        super().__init__(center=center, angle=angle, aperture=aperture, thickness=thickness, retardance=math.pi, fast_axis_angle=fast_axis_angle, **kwargs)


@dataclass
class QuarterWavePlate(WavePlate):
    """Quarter-wave plate convenience component."""

    component_type = "QuarterWavePlate"

    def __init__(self, center=(0, 0), angle=0, aperture=10.0, thickness=0.7, fast_axis_angle=0.0, design_wavelength_nm=None, **kwargs):
        kwargs.setdefault("label", "QWP")
        kwargs.setdefault("color", "#74add1")
        super().__init__(center=center, angle=angle, aperture=aperture, thickness=thickness, retardance=math.pi / 2.0, fast_axis_angle=fast_axis_angle, design_wavelength_nm=design_wavelength_nm, **kwargs)


@dataclass
class WedgePlate(Component):
    """Thin wedged window for beam deviation and interferometer teaching sketches."""

    component_type = "WedgePlate"
    aperture: float = 10.0
    wedge_angle_deg: float = 2.0
    thickness: float = 0.8
    refractive_index: float = 1.52

    def __init__(self, center=(0, 0), angle=0, aperture=10.0, wedge_angle_deg=2.0, thickness=0.8, refractive_index=1.52, **kwargs):
        self.aperture = aperture
        self.wedge_angle_deg = wedge_angle_deg
        self.thickness = thickness
        self.refractive_index = refractive_index
        _set_common_free_space_fields(self, center, angle, kwargs, color="#b8e0ff", opacity=0.46, material_preset="glass")

    def _outline(self) -> list[tuple[float, float]]:
        half_height = self.aperture / 2.0
        half_width = self.thickness / 2.0
        wedge_offset = math.tan(math.radians(self.wedge_angle_deg)) * self.aperture
        shift = wedge_offset / 4.0
        return [
            (-half_width - shift, -half_height),
            (half_width + wedge_offset - shift, -half_height),
            (half_width - shift, half_height),
            (-half_width - shift, half_height),
        ]

    def geometry_2d(self) -> dict[str, Any]:
        wedge_offset = math.tan(math.radians(self.wedge_angle_deg)) * self.aperture
        half_span = (self.thickness + wedge_offset * 0.5) / 2.0
        return {
            "type": "group",
            "children": [
                {"type": "polyline", "points": self._outline(), "closed": True, "fill": self.color, "stroke": "#4c8db8", "stroke_width": 0.1, "opacity": self.opacity},
                {"type": "line", "x1": -half_span, "y1": 0.0, "x2": half_span, "y2": 0.0, "stroke": "#ffffff", "stroke_width": 0.08, "opacity": 0.45},
            ],
        }

    def geometry_3d(self) -> dict[str, Any]:
        wedge = math.tan(math.radians(self.wedge_angle_deg)) * self.aperture
        glass = {
            "shape": "extruded_polygon",
            "role": "glass",
            "points": self._outline(),
            "height": self.aperture * 0.75,
            "position": [0.0, -self.aperture * 0.375, 0.0],
            "material": {**_transparent_material(self.color, self.opacity, self.material_preset), "roughness": 0.02, "transmission": 0.74, "ior": self.refractive_index, "clearcoat": 0.7, "clearcoatRoughness": 0.06},
        }
        return {"shape": "group", "children": [glass, *_frame_holder(self.aperture, self.aperture * 0.75, max(self.thickness + wedge, 0.6))]}

    def ports(self) -> dict[str, Port]:
        wedge_offset = math.tan(math.radians(self.wedge_angle_deg)) * self.aperture
        return _through_ports(self.thickness + wedge_offset * 0.5, self.aperture)

    def physics_metadata(self) -> dict[str, Any]:
        deflection_angle_deg = (self.refractive_index - 1.0) * self.wedge_angle_deg
        return _optical_metadata(
            "wedge_plate",
            aperture=self.aperture,
            wedge_angle_deg=self.wedge_angle_deg,
            refractive_index=self.refractive_index,
            deflection_angle_deg=deflection_angle_deg,
        )

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["aperture"] = self.aperture
        data["wedge_angle_deg"] = self.wedge_angle_deg
        data["thickness"] = self.thickness
        data["refractive_index"] = self.refractive_index
        return data


@dataclass
class BrewsterWindow(Component):
    """Brewster-angle window in a slotted mount (BW20M silhouette) — the tilted plate
    passes p-polarised light without reflection loss."""

    component_type = "BrewsterWindow"
    aperture: float = 8.0
    thickness: float = 0.5
    window_angle_deg: float = 56.0

    def __init__(self, center=(0, 0), angle=0, aperture=8.0, thickness=0.5, window_angle_deg=56.0, **kwargs):
        self.aperture = aperture
        self.thickness = thickness
        self.window_angle_deg = window_angle_deg
        _set_common_free_space_fields(self, center, angle, kwargs, color="#cfe4f2", opacity=0.5, material_preset="glass", label=kwargs.get("label", "Brewster window"))

    def geometry_2d(self) -> dict[str, Any]:
        a = self.aperture
        t = math.radians(self.window_angle_deg)
        dx, dy = math.sin(t) * a * 0.55, math.cos(t) * a * 0.55
        return {
            "type": "group",
            "children": [
                {"type": "circle", "cx": 0, "cy": 0, "r": a * 0.62, "fill": "none", "stroke": "#23282e", "stroke_width": 0.28},
                {"type": "line", "x1": -dx, "y1": -dy, "x2": dx, "y2": dy, "stroke": self.color, "stroke_width": max(self.thickness, 0.3), "opacity": 0.9},
            ],
        }

    def geometry_3d(self) -> dict[str, Any]:
        # The window and its ring holder turn together about the vertical axis, so the beam meets the plate at
        # the Brewster angle in the table plane, as the 2D drawing shows; a stem carries the holder to the post.
        a = self.aperture
        tilt = [0.0, -math.radians(self.window_angle_deg), math.pi / 2.0]
        return {
            "shape": "group",
            "children": [
                {**_ring_along_x(a * 0.5, a * 0.62, a * 0.14, _MOUNT_BLACK), "role": "holder", "rotation": tilt},
                {"shape": "cylinder", "role": "glass", "radius": a * 0.5, "height": max(self.thickness, 0.2), "rotation": tilt,
                 "material": {**_transparent_material(self.color, self.opacity, "glass"), "transmission": 0.6, "ior": 1.45}},
                {"shape": "cylinder", "radius": a * 0.03, "height": a * 0.08, "position": [0.0, a * 0.64, 0.0], "material": _MOUNT_ALU},
                {"shape": "box", "width": a * 0.16, "height": a * 0.16, "depth": a * 0.24, "position": [0.0, -a * 0.68, 0.0], "material": _MOUNT_BLACK},
            ],
        }

    def ports(self) -> dict[str, Port]:
        # Where the beam crosses the faces of the tilted plate: the plate, not its holder, ends the light.
        return _through_ports(max(self.thickness, 0.2) / math.cos(math.radians(self.window_angle_deg)), self.aperture * 0.8)

    def physics_metadata(self) -> dict[str, Any]:
        return _optical_metadata("brewster_window", window_angle_deg=self.window_angle_deg, thickness=self.thickness)

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["aperture"] = self.aperture
        data["thickness"] = self.thickness
        data["window_angle_deg"] = self.window_angle_deg
        return data


@dataclass
class GlanLaserPolarizer(Component):
    """A Glan-Laser polarizer: two prisms with an air gap between them.

    Light polarized in the plane of the drawing (p, horizontal here) passes straight from ``in`` to ``out``.
    The other polarization (s) meets the gap past its critical angle and leaves through the side window at
    ``reject``, ``reject_angle_deg`` below the beam. That angle depends on the prism: set it to the one you draw.
    """

    component_type = "GlanLaserPolarizer"
    length: float = 12.0
    aperture: float = 6.0
    reject_angle_deg: float = 60.0
    extinction_ratio: float = 1e5

    def __init__(self, center=(0, 0), angle=0, length=12.0, aperture=6.0, reject_angle_deg=60.0,
                 extinction_ratio=1e5, **kwargs):
        self.length = float(length)
        self.aperture = float(aperture)
        self.reject_angle_deg = float(reject_angle_deg)
        self.extinction_ratio = float(extinction_ratio)
        _set_common_free_space_fields(self, center, angle, kwargs, color="#8dc5ff", opacity=0.36, material_preset="glass")

    def ports(self) -> dict[str, Port]:
        half_l, half_a = self.length / 2.0, self.aperture / 2.0
        return {
            "in": Port("in", Vec3(-half_l, 0.0, 0.0), orientation_deg=180.0, width=self.aperture * 0.8, kind="free_space"),
            "out": Port("out", Vec3(half_l, 0.0, 0.0), orientation_deg=0.0, width=self.aperture * 0.8, kind="free_space"),
            # the escape window on the lower face, just past the gap
            "reject": Port("reject", Vec3(self.length / 12.0, -half_a, 0.0), orientation_deg=-self.reject_angle_deg,
                           width=self.aperture * 0.4, kind="free_space"),
        }

    def geometry_2d(self) -> dict[str, Any]:
        half_a = self.aperture / 2.0
        gap = self.length / 8.0                      # the air gap runs from upper left to lower right
        return {
            "type": "group",
            "children": [
                {"type": "rect", "cx": 0.0, "cy": 0.0, "w": self.length, "h": self.aperture, "fill": self.color,
                 "opacity": self.opacity, "stroke": "#4a7fa8", "stroke_width": 0.1},
                {"type": "line", "x1": -gap, "y1": half_a, "x2": gap, "y2": -half_a, "stroke": "#2f5f82",
                 "stroke_width": 0.12, "opacity": 0.9},
                {"type": "line", "x1": 0.0, "y1": -half_a, "x2": self.length / 6.0, "y2": -half_a, "stroke": "#14324a",
                 "stroke_width": 0.22, "opacity": 0.9},
            ],
        }

    def geometry_3d(self) -> dict[str, Any]:
        tilt = math.atan2(self.aperture, self.length / 4.0)
        return {
            "shape": "group",
            "children": [
                {"shape": "box", "width": self.length, "height": self.aperture, "depth": self.aperture,
                 "material": _transparent_material(self.color, self.opacity, self.material_preset)},
                {"shape": "box", "width": self.aperture / math.sin(tilt), "height": 0.04, "depth": self.aperture * 0.98,
                 "rotation": [0.0, 0.0, -tilt], "material": {"color": "#ffffff", "opacity": 0.35, "transparent": True}},
                {"shape": "box", "width": self.length * 1.1, "height": self.aperture * 0.12, "depth": self.aperture * 1.1,
                 "position": [0.0, -self.aperture * 0.56, 0.0], "material": _MOUNT_BLACK},
            ],
        }

    def physics_metadata(self) -> dict[str, Any]:
        return _optical_metadata("glan_laser_polarizer", extinction_ratio=self.extinction_ratio,
                                 reject_angle_deg=self.reject_angle_deg)


@dataclass
class WollastonPrism(Component):
    """A Wollaston prism: two birefringent wedges cemented on a diagonal, their optic axes crossed.

    Light enters at ``in``; the two polarizations leave the back face apart by ``separation_deg``, half above the
    axis and half below. The polarization in the plane of the drawing (H) leaves at ``o`` (above), the other (V)
    at ``e`` (below); turn the prism by 180 degrees about the beam to swap them. Real prisms split by 1 to 20
    degrees: set the angle you draw.
    """

    component_type = "WollastonPrism"
    length: float = 8.0
    aperture: float = 8.0
    separation_deg: float = 20.0
    extinction_ratio: float = 1e5

    def __init__(self, center=(0, 0), angle=0, length=8.0, aperture=8.0, separation_deg=20.0,
                 extinction_ratio=1e5, **kwargs):
        self.length = float(length)
        self.aperture = float(aperture)
        self.separation_deg = float(separation_deg)
        self.extinction_ratio = float(extinction_ratio)
        _set_common_free_space_fields(self, center, angle, kwargs, color="#8dc5ff", opacity=0.36, material_preset="glass")

    def ports(self) -> dict[str, Port]:
        half_l, half = self.length / 2.0, self.separation_deg / 2.0
        rise = half_l * math.tan(math.radians(half))       # each beam leaves the diagonal at the centre and bends away
        return {
            "in": Port("in", Vec3(-half_l, 0.0, 0.0), orientation_deg=180.0, width=self.aperture * 0.6, kind="free_space"),
            "o": Port("o", Vec3(half_l, rise, 0.0), orientation_deg=half, width=self.aperture * 0.3, kind="free_space"),
            "e": Port("e", Vec3(half_l, -rise, 0.0), orientation_deg=-half, width=self.aperture * 0.3, kind="free_space"),
        }

    def geometry_2d(self) -> dict[str, Any]:
        half_l, half_a = self.length / 2.0, self.aperture / 2.0
        mark = {"stroke": "#2f5f82", "stroke_width": 0.1, "opacity": 0.9}
        return {
            "type": "group",
            "children": [
                {"type": "rect", "cx": 0.0, "cy": 0.0, "w": self.length, "h": self.aperture, "fill": self.color,
                 "opacity": self.opacity, "stroke": "#4a7fa8", "stroke_width": 0.1},
                {"type": "line", "x1": -half_l, "y1": half_a, "x2": half_l, "y2": -half_a, **mark},
                # the optic axes: in the page in the first wedge, out of it (a dot) in the second
                {"type": "line", "x1": -half_l * 0.55, "y1": -half_a * 0.1, "x2": -half_l * 0.55, "y2": -half_a * 0.75, **mark},
                {"type": "circle", "cx": half_l * 0.55, "cy": half_a * 0.45, "r": half_a * 0.14, "fill": "none", **mark},
                {"type": "circle", "cx": half_l * 0.55, "cy": half_a * 0.45, "r": half_a * 0.04, "fill": "#2f5f82"},
            ],
        }

    def geometry_3d(self) -> dict[str, Any]:
        L, a = self.length, self.aperture
        tilt = math.atan2(a, L)
        base = a * 0.12
        return {
            "shape": "group",
            "children": [
                {"shape": "box", "role": "prism", "width": L, "height": a, "depth": a,
                 "material": _transparent_material(self.color, self.opacity, self.material_preset)},
                {"shape": "box", "role": "interface", "width": math.hypot(L, a), "height": 0.04, "depth": a * 0.98,
                 "rotation": [0.0, 0.0, -tilt], "material": {"color": "#ffffff", "opacity": 0.35, "transparent": True}},
                {"shape": "box", "role": "base", "width": L * 1.1, "height": base, "depth": a * 1.1,
                 "position": [0.0, -(a + base) / 2.0, 0.0], "material": _MOUNT_BLACK},
            ],
            "post_at": [0.0, -a / 2.0 - base, 0.0],
        }

    def physics_metadata(self) -> dict[str, Any]:
        return _optical_metadata("wollaston_prism", separation_deg=self.separation_deg,
                                 extinction_ratio=self.extinction_ratio)
