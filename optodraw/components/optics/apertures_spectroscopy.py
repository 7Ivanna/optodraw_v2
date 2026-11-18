"""Apertures spectroscopy free-space optics."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from optodraw.core.component import Component
from optodraw.core.ports import Port
from optodraw.core.transform import Vec3

from ._shared import (
    _KNOB_STEEL,
    _MOUNT_BLACK,
    _optical_metadata,
    _ring_along_x,
    _set_common_free_space_fields,
    _through_ports,
    _rim_along_x,
)


def _plate_in_holder(od: float, hole_r: float, plate_t: float, plate: dict[str, Any],
                     edge: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """A thin plate with a hole in a fixed ring holder on a post stem, as a stop or a pinhole sits on a bench:
    the holder ring, its front lip, the plate behind the lip, a retaining ring behind the plate and a set
    screw on top. ``edge`` draws the machined rim of the hole in its own colour, so the hole reads."""

    R = od / 2.0
    depth = od * 0.16
    lip_t = od * 0.025
    front = -depth / 2.0 + lip_t
    hole_r = min(hole_r, R * 0.8 * 0.9)                  # a hole as wide as the holder bore leaves no plate
    rim = min(hole_r * 1.35, (hole_r + R * 0.8) / 2.0) if edge else hole_r
    plate_x = front + plate_t / 2.0
    parts = [
        {**_ring_along_x(R * 0.8, R, depth, _MOUNT_BLACK), "role": "holder"},
        _ring_along_x(R * 0.72, R * 0.8, lip_t, _MOUNT_BLACK, x=-depth / 2.0 + lip_t / 2.0),
        {**_ring_along_x(rim, R * 0.8, plate_t, plate, x=plate_x), "role": "plate"},
        _ring_along_x(R * 0.68, R * 0.8, od * 0.03, _MOUNT_BLACK, x=front + plate_t + od * 0.015),
        {"shape": "cylinder", "radius": od * 0.03, "height": od * 0.08, "position": [0.0, R + od * 0.03, 0.0],
         "material": _KNOB_STEEL},
        {"shape": "box", "width": depth * 0.8, "height": od * 0.16, "depth": od * 0.22,
         "position": [0.0, -R - od * 0.06, 0.0], "material": _MOUNT_BLACK},
    ]
    if edge:
        parts.append({**_ring_along_x(hole_r, rim, plate_t, edge, x=plate_x), "role": "plate"})
    return parts


@dataclass
class Iris(Component):
    """Adjustable iris aperture with blade metadata."""

    component_type = "Iris"
    beam_passes = True        # light crosses its open aperture: a beam through it is drawn, not hidden
    outer_diameter: float = 12.0
    aperture_diameter: float = 5.0
    blade_count: int = 12

    def __init__(self, center=(0, 0), angle=0, outer_diameter=12.0, aperture_diameter=5.0, blade_count=12, **kwargs):
        self.outer_diameter = outer_diameter
        self.aperture_diameter = aperture_diameter
        self.blade_count = blade_count
        _set_common_free_space_fields(self, center, angle, kwargs, color="#2f3439", opacity=1.0, material_preset="steel")

    def geometry_2d(self) -> dict[str, Any]:
        R = self.outer_diameter / 2.0
        ring_in = self.outer_diameter * 0.37  # inner edge of the SM1 housing (leaf cavity)
        ap = max(self.aperture_diameter / 2.0, self.outer_diameter * 0.04)
        children: list[dict[str, Any]] = [
            # SM1-threaded anodized housing
            {"type": "circle", "cx": 0, "cy": 0, "r": R, "fill": self.color, "stroke": "#0b0f14", "stroke_width": 0.1, "opacity": self.opacity},
            {"type": "circle", "cx": 0, "cy": 0, "r": self.outer_diameter * 0.46, "fill": "none", "stroke": "#697585", "stroke_width": 0.05, "opacity": 0.7},
            # dark leaf cavity
            {"type": "circle", "cx": 0, "cy": 0, "r": ring_in, "fill": "#0b1018", "stroke": "#3a4654", "stroke_width": 0.06},
        ]
        # overlapping black spring-steel leaves forming the aperture
        n = min(max(self.blade_count, 3), 14)
        for i in range(n):
            a = 2.0 * math.pi * i / n
            a2 = a + 2.0 * math.pi / n
            pin = a + math.pi / n + 0.55  # spiral offset -> leaves overlap
            pts = [
                (math.cos(a) * ring_in, math.sin(a) * ring_in),
                (math.cos(a2) * ring_in, math.sin(a2) * ring_in),
                (math.cos(pin) * ap, math.sin(pin) * ap),
            ]
            children.append({"type": "polygon", "points": pts, "fill": "#1c2632", "stroke": "#0b1120", "stroke_width": 0.04, "opacity": 0.97})
        # the open aperture
        children.append({"type": "circle", "cx": 0, "cy": 0, "r": ap, "fill": "#f8fafc", "stroke": "#94a3b8", "stroke_width": 0.06, "opacity": 1.0})
        # setscrews around the ring
        for s in range(6):
            a = 2.0 * math.pi * s / 6.0 + math.pi / 6.0
            children.append({"type": "circle", "cx": math.cos(a) * self.outer_diameter * 0.42, "cy": math.sin(a) * self.outer_diameter * 0.42, "r": self.outer_diameter * 0.03, "fill": "#cbd5e1", "stroke": "#475569", "stroke_width": 0.03, "opacity": 0.95})
        # actuation lever + knob (the defining feature) and close-direction arrow
        la = -math.pi * 0.28
        children.append({"type": "line", "x1": math.cos(la) * R * 0.96, "y1": math.sin(la) * R * 0.96, "x2": math.cos(la) * R * 1.5, "y2": math.sin(la) * R * 1.5, "stroke": "#9aa4b1", "stroke_width": max(self.outer_diameter * 0.05, 0.2), "linecap": "round"})
        children.append({"type": "circle", "cx": math.cos(la) * R * 1.5, "cy": math.sin(la) * R * 1.5, "r": self.outer_diameter * 0.06, "fill": "#cbd5e1", "stroke": "#475569", "stroke_width": 0.04})
        return {"type": "group", "children": children}

    def geometry_3d(self) -> dict[str, Any]:
        # Proper iris leaf mechanism: MANY thin flat leaves, each oriented tangentially
        # and rotated slightly off-radial (spiral), tightly overlapping in two stacked
        # layers — they close down to the real aperture like the mechanical original.
        blade_children: list[dict[str, Any]] = []
        active_blades = min(max(self.blade_count, 0), 16)
        if active_blades > 0:
            n = max(active_blades, 10)
            od = self.outer_diameter
            ap_r = max(self.aperture_diameter / 2.0, od * 0.02)
            r_out = od * 0.34
            mid = (ap_r + r_out) / 2.0
            radial = (r_out - ap_r) * 1.25
            chord = (2.0 * math.pi * mid / n) * 1.9   # wide enough to overlap the neighbours
            leaf_mat = {"color": "#171b20", "metalness": 0.45, "roughness": 0.4, "preset": "steel"}
            for k in range(n):
                theta = 2.0 * math.pi * k / n
                blade_children.append({
                    "shape": "box", "width": 0.05, "height": radial, "depth": chord,
                    "position": [-0.18 - (k % 2) * 0.06, math.sin(theta) * mid, math.cos(theta) * mid],
                    # align the leaf's long axis radially, then tip it off-radial for the spiral overlap
                    "rotation": [math.pi / 2.0 - theta + 0.38, 0.0, 0.0],
                    "material": leaf_mat,
                })
        # Clean mounted-iris (IDA12 silhouette) with a REAL through-hole: the outer body
        # and the blade disc are true annuli, so light (and the eye) passes through the
        # open aperture. The body is BLACK PLASTIC like the real part — not silvery metal.
        od = self.outer_diameter
        ap_r = max(self.aperture_diameter / 2.0, od * 0.02)
        lever_a = -math.pi * 0.28
        plastic = {"color": "#17191d", "metalness": 0.12, "roughness": 0.72, "preset": "matte"}
        return {
            "shape": "group",
            "children": [
                # outer body ring (real bore), matte black plastic
                _ring_along_x(od * 0.33, od / 2.0, 1.0, plastic),
                # front face lip
                _ring_along_x(od * 0.35, od * 0.485, 0.14, plastic, x=-0.56),
                # blade disc: an annulus from the body bore down to the OPEN aperture
                _ring_along_x(ap_r, od * 0.345, 0.5, {"color": "#14171b", "metalness": 0.35, "roughness": 0.5}),
                # subtle dark aperture rim (the blade edges)
                _rim_along_x(ap_r, max(od * 0.015, 0.05), {"color": "#5d646c", "metalness": 0.3, "roughness": 0.4}, position=[-0.26, 0.0, 0.0]),
                *blade_children,
                # single flat actuation lever + pin, black plastic like the body
                {"shape": "box", "width": 0.24, "height": od * 0.34, "depth": od * 0.07,
                 "position": [-0.2, math.sin(lever_a) * od * 0.62, math.cos(lever_a) * od * 0.62],
                 "rotation": [lever_a, 0.0, 0.0], "material": plastic},
                {"shape": "cylinder", "radius": od * 0.045, "height": 0.5,
                 "position": [-0.4, math.sin(lever_a) * od * 0.76, math.cos(lever_a) * od * 0.76],
                 "rotation": [0.0, 0.0, math.pi / 2.0], "material": plastic},
                # mounting tab at the bottom (post attaches here)
                {"shape": "box", "width": 0.9, "height": od * 0.18, "depth": od * 0.24, "position": [0.0, -od * 0.57, 0.0], "material": _MOUNT_BLACK},
            ],
        }

    def physics_metadata(self) -> dict[str, Any]:
        return _optical_metadata("iris", aperture_diameter=self.aperture_diameter, blade_count=self.blade_count)


@dataclass
class Pinhole(Iris):
    """Fixed pinhole aperture."""

    component_type = "Pinhole"

    def __init__(self, center=(0, 0), angle=0, outer_diameter=8.0, aperture_diameter=1.0, **kwargs):
        kwargs.setdefault("label", "Pinhole")
        super().__init__(center=center, angle=angle, outer_diameter=outer_diameter, aperture_diameter=aperture_diameter, blade_count=0, **kwargs)

    def ports(self) -> dict[str, Port]:
        # The faces of the foil the 2D art draws: 0.04 cm thick in the 0.68 cm of the pic od iris (kind=pinhole).
        return _through_ports(self.outer_diameter * 0.04 / 0.68, self.outer_diameter)

    def geometry_2d(self) -> dict[str, Any]:
        R = self.outer_diameter / 2.0
        ap = max(self.aperture_diameter / 2.0, self.outer_diameter * 0.012)
        return {
            "type": "group",
            "children": [
                # black anodized SM1 ring mount
                {"type": "circle", "cx": 0, "cy": 0, "r": R, "fill": "#15191e", "stroke": "#05070a", "stroke_width": 0.1},
                {"type": "circle", "cx": 0, "cy": 0, "r": self.outer_diameter * 0.46, "fill": "none", "stroke": "#3a4654", "stroke_width": 0.05, "opacity": 0.7},
                # stainless precision foil
                {"type": "circle", "cx": 0, "cy": 0, "r": self.outer_diameter * 0.34, "fill": "#2b323b", "stroke": "#5b6675", "stroke_width": 0.05},
                # laser-drilled pinhole + faint halo
                {"type": "circle", "cx": 0, "cy": 0, "r": ap * 2.4, "fill": "none", "stroke": "#9aa4b1", "stroke_width": 0.03, "opacity": 0.5},
                {"type": "circle", "cx": 0, "cy": 0, "r": ap, "fill": "#f8fafc", "stroke": "#cbd5e1", "stroke_width": 0.03},
                # retaining-ring spanner slots
                *[{"type": "circle", "cx": math.cos(s * math.pi) * self.outer_diameter * 0.4, "cy": math.sin(s * math.pi) * self.outer_diameter * 0.4, "r": self.outer_diameter * 0.03, "fill": "#0b0f14"} for s in (0.0, 1.0)],
            ],
        }

    def geometry_3d(self) -> dict[str, Any]:
        od = self.outer_diameter
        foil = {"color": "#9aa1a9", "metalness": 0.75, "roughness": 0.3, "preset": "steel"}
        return {"shape": "group", "children": _plate_in_holder(od, max(self.aperture_diameter / 2.0, od * 0.0125), od * 0.012, foil)}

    def physics_metadata(self) -> dict[str, Any]:
        return _optical_metadata("pinhole", aperture_diameter=self.aperture_diameter)


@dataclass
class ApertureStop(Iris):
    """Fixed aperture stop for paraxial and publication diagrams."""

    component_type = "ApertureStop"

    def __init__(self, center=(0, 0), angle=0, outer_diameter=12.0, aperture_diameter=4.0, **kwargs):
        kwargs.setdefault("label", "Stop")
        kwargs.setdefault("color", "#111827")
        super().__init__(center=center, angle=angle, outer_diameter=outer_diameter, aperture_diameter=aperture_diameter, blade_count=0, **kwargs)

    def ports(self) -> dict[str, Port]:
        # The faces of the plate the 2D art draws: 0.07 cm thick in the 0.72 cm of the pic od iris (kind=stop).
        return _through_ports(self.outer_diameter * 0.07 / 0.72, self.outer_diameter)

    def geometry_2d(self) -> dict[str, Any]:
        R = self.outer_diameter / 2.0
        ap = self.aperture_diameter / 2.0
        return {
            "type": "group",
            "children": [
                # opaque matte stop plate
                {"type": "circle", "cx": 0, "cy": 0, "r": R, "fill": "#16181c", "stroke": "#05070a", "stroke_width": 0.1},
                {"type": "circle", "cx": 0, "cy": 0, "r": R * 0.9, "fill": "none", "stroke": "#2a3038", "stroke_width": 0.05, "opacity": 0.7},
                # clean circular aperture + machined bevel
                {"type": "circle", "cx": 0, "cy": 0, "r": ap * 1.16, "fill": "#2b323b", "stroke": "#5b6675", "stroke_width": 0.04},
                {"type": "circle", "cx": 0, "cy": 0, "r": ap, "fill": "#f8fafc", "stroke": "#94a3b8", "stroke_width": 0.06},
            ],
        }

    def geometry_3d(self) -> dict[str, Any]:
        od = self.outer_diameter
        plate = {"color": "#3b4149", "metalness": 0.5, "roughness": 0.5, "preset": "steel"}
        edge = {"color": "#8d949c", "metalness": 0.7, "roughness": 0.3, "preset": "steel"}
        return {"shape": "group", "children": _plate_in_holder(od, max(self.aperture_diameter / 2.0, od * 0.0125), od * 0.03, plate, edge)}

    def physics_metadata(self) -> dict[str, Any]:
        return _optical_metadata("aperture_stop", aperture_diameter=self.aperture_diameter)


@dataclass
class SpectrometerSlit(Component):
    """Entrance slit for spectrometer and monochromator setups."""

    component_type = "SpectrometerSlit"
    slit_width_um: float = 25.0
    slit_height: float = 8.0
    body_width: float = 10.0

    def __init__(self, center=(0, 0), angle=0, slit_width_um=25.0, slit_height=8.0, body_width=10.0, **kwargs):
        self.slit_width_um = slit_width_um
        self.slit_height = slit_height
        self.body_width = body_width
        _set_common_free_space_fields(self, center, angle, kwargs, color="#111827", opacity=1.0, material_preset="steel", label=kwargs.get("label", "Slit"))

    def geometry_2d(self) -> dict[str, Any]:
        visual_slit = max(min(self.slit_width_um / 200.0, self.body_width * 0.12), 0.08)
        return {
            "type": "group",
            "children": [
                {"type": "rect", "cx": 0.0, "cy": 0.0, "w": self.body_width, "h": self.slit_height, "fill": self.color, "stroke": "#020617", "stroke_width": 0.08},
                {"type": "rect", "cx": 0.0, "cy": 0.0, "w": self.body_width * 0.9, "h": visual_slit, "fill": "#f8fafc", "stroke": "#cbd5e1", "stroke_width": 0.03},
            ],
        }

    def geometry_3d(self) -> dict[str, Any]:
        # An adjustable slit: a plate across the beam with a window, two knife-edge jaws over the window that
        # leave a vertical slit, and a micrometer at the side that drives one jaw across the beam (z).
        bw, h = self.body_width, self.slit_height
        gap = max(min(self.slit_width_um / 200.0, bw * 0.12), bw * 0.03)
        t, tall = bw * 0.14, h * 1.3
        win_z, win_y = bw * 0.44, h * 0.8
        body = {"color": self.color, "metalness": 0.42, "roughness": 0.45, "preset": self.material_preset}
        blade = {"color": "#aab1b9", "metalness": 0.85, "roughness": 0.22, "preset": "steel"}
        side = (bw - win_z) / 2.0
        bar = (tall - win_y) / 2.0
        jaw_z = (win_z + bw * 0.06) / 2.0 - gap / 2.0        # each jaw reaches from under the frame to the slit
        jaw_x = -t / 2.0 - bw * 0.02
        children = [
            {"shape": "box", "role": "body", "width": t, "height": tall, "depth": side, "position": [0.0, 0.0, (win_z + side) / 2.0], "material": body},
            {"shape": "box", "role": "body", "width": t, "height": tall, "depth": side, "position": [0.0, 0.0, -(win_z + side) / 2.0], "material": body},
            {"shape": "box", "role": "body", "width": t, "height": bar, "depth": win_z, "position": [0.0, (win_y + bar) / 2.0, 0.0], "material": body},
            {"shape": "box", "role": "body", "width": t, "height": bar, "depth": win_z, "position": [0.0, -(win_y + bar) / 2.0, 0.0], "material": body},
        ]
        for sign in (-1.0, 1.0):
            children.append({"shape": "box", "role": "jaw", "width": bw * 0.04, "height": win_y + bw * 0.06, "depth": jaw_z,
                             "position": [jaw_x, 0.0, sign * (gap / 2.0 + jaw_z / 2.0)], "material": blade})
        z = bw / 2.0
        for radius, length, material in ((bw * 0.075, bw * 0.06, body), (bw * 0.055, bw * 0.3, _KNOB_STEEL),
                                         (bw * 0.085, bw * 0.22, _MOUNT_BLACK), (bw * 0.05, bw * 0.08, _KNOB_STEEL)):
            children.append({"shape": "cylinder", "role": "micrometer", "radius": radius, "height": length,
                             "position": [0.0, 0.0, z + length / 2.0], "rotation": [math.pi / 2.0, 0.0, 0.0], "material": material})
            z += length
        stem_bottom = -tall / 2.0 - h * 0.18
        children.append({"shape": "box", "width": t * 0.8, "height": h * 0.2, "depth": bw * 0.3,
                         "position": [0.0, stem_bottom + h * 0.1, 0.0], "material": _MOUNT_BLACK})
        return {"shape": "group", "children": children, "post_at": [0.0, stem_bottom, 0.0]}

    def ports(self) -> dict[str, Port]:
        # The jaws, not the body's width: 0.18 cm deep in the 0.72 cm of the pic od iris (kind=slit).
        return _through_ports(self.slit_height * 0.18 / 0.72, self.slit_height)

    def physics_metadata(self) -> dict[str, Any]:
        return _optical_metadata("spectrometer_slit", slit_width_um=self.slit_width_um, slit_height=self.slit_height)


@dataclass
class Monochromator(Component):
    """Monochromator block with grating and slit metadata."""

    component_type = "Monochromator"
    length: float = 34.0
    width: float = 20.0
    groove_density_l_mm: float = 1200.0
    focal_length_mm: float = 300.0

    def __init__(self, center=(0, 0), angle=0, length=34.0, width=20.0, groove_density_l_mm=1200.0, focal_length_mm=300.0, **kwargs):
        self.length = length
        self.width = width
        self.groove_density_l_mm = groove_density_l_mm
        self.focal_length_mm = focal_length_mm
        self.center_wavelength_nm = kwargs.get("center_wavelength_nm", 633.0)
        _set_common_free_space_fields(self, center, angle, kwargs, color="#1f2937", opacity=1.0, material_preset="steel", label=kwargs.get("label", "Monochromator"))
        self.base_mount = str(kwargs.get("base_mount", "none"))      # it sits on the table, its slits at the beam

    def geometry_2d(self) -> dict[str, Any]:
        grating_w = self.length * 0.16
        return {
            "type": "group",
            "children": [
                {"type": "rect", "cx": 0.0, "cy": 0.0, "w": self.length, "h": self.width, "fill": self.color, "stroke": "#020617", "stroke_width": 0.08},
                {"type": "rect", "cx": -self.length * 0.28, "cy": 0.0, "w": grating_w, "h": self.width * 0.74, "fill": "#334155", "stroke": "#64748b", "stroke_width": 0.06},
                {"type": "rect", "cx": self.length * 0.34, "cy": 0.0, "w": self.length * 0.1, "h": self.width * 0.58, "fill": "#f8fafc", "stroke": "#cbd5e1", "stroke_width": 0.05, "opacity": 0.75},
                {"type": "line", "x1": -self.length * 0.14, "y1": 0.0, "x2": self.length * 0.24, "y2": -self.width * 0.24, "stroke": "#38bdf8", "stroke_width": 0.09, "opacity": 0.75},
            ],
        }

    def geometry_3d(self) -> dict[str, Any]:
        # A monochromator on the table: a light grey housing tall enough that its slits sit at the beam height,
        # a dark cover over the grating turret, an entrance slit assembly on the input face and an exit slit
        # assembly at the output port, each with its width micrometer on top, and four feet. It stood on a post
        # as a small box with a drum on top.
        from .optomech import BEAM_HEIGHT

        L, W = self.length, self.width
        top, foot = W * 0.35, 1.0
        depth = W * 1.5
        body = {"color": "#d3d7dc", "metalness": 0.35, "roughness": 0.5, "preset": "aluminum"}
        cover = {"color": "#46566e", "metalness": 0.4, "roughness": 0.45, "preset": "aluminum"}
        tall = BEAM_HEIGHT + top - foot
        children: list[dict[str, Any]] = [
            {"shape": "box", "role": "housing", "width": L, "height": tall, "depth": depth, "position": [0.0, top - tall / 2.0, 0.0], "material": body},
            {"shape": "box", "width": L * 0.9, "height": W * 0.05, "depth": depth * 0.86, "position": [0.0, top + W * 0.025, 0.0], "material": cover},
            {"shape": "box", "width": L * 0.6, "height": W * 0.12, "depth": 0.08, "position": [0.0, top - W * 0.2, depth / 2.0 + 0.04], "material": cover},   # nameplate
            *[{"shape": "cylinder", "radius": W * 0.06, "height": foot, "position": [sx * L * 0.42, -BEAM_HEIGHT + foot / 2.0, sz * depth * 0.38],
               "material": {"color": "#1d2126", "roughness": 0.7}} for sx in (-1, 1) for sz in (-1, 1)],
        ]
        out = self.ports()["out"].center
        for face, z in ((-1.0, 0.0), (1.0, -out.y)):
            x = face * (L / 2.0 + W * 0.04)
            children += [
                {"shape": "box", "width": W * 0.08, "height": W * 0.55, "depth": W * 0.24, "position": [x, 0.0, z], "material": _MOUNT_BLACK},
                {"shape": "box", "role": "slit", "width": W * 0.012, "height": W * 0.3, "depth": W * 0.02, "position": [x + face * W * 0.042, 0.0, z], "material": {"color": "#05070a", "roughness": 0.9}},
                {"shape": "cylinder", "radius": W * 0.04, "height": W * 0.2, "position": [x, W * 0.375, z], "material": _KNOB_STEEL},
                {"shape": "cylinder", "radius": W * 0.07, "height": W * 0.1, "position": [x, W * 0.525, z], "material": _MOUNT_BLACK},
            ]
        return {"shape": "group", "children": children}

    def ports(self) -> dict[str, Port]:
        return {
            "in": Port("in", Vec3(-self.length / 2.0, 0.0, 0.0), orientation_deg=180.0, width=self.width * 0.58, kind="free_space"),
            "out": Port("out", Vec3(self.length / 2.0, -self.width * 0.24, 0.0), orientation_deg=-18.0, width=self.width * 0.5, kind="free_space"),
        }

    def physics_metadata(self) -> dict[str, Any]:
        return _optical_metadata(
            "monochromator",
            groove_density_l_mm=self.groove_density_l_mm,
            focal_length_mm=self.focal_length_mm,
            center_wavelength_nm=self.center_wavelength_nm,
        )
