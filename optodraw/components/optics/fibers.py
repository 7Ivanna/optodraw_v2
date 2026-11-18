"""Fibers free-space optics."""

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
    _knurl_teeth,
    _optical_metadata,
    _post_boss,
    _ring_along_x,
    _set_common_free_space_fields,
    _rim_along_x,
    _transparent_material,
)


@dataclass
class FiberPort(Component):
    """Bare fiber endpoint or ferrule visual for coupling diagrams."""

    component_type = "FiberPort"
    core_diameter: float = 0.9
    cladding_diameter: float = 6.0
    length: float = 10.0

    def __init__(self, center=(0, 0), angle=0, core_diameter=0.9, cladding_diameter=6.0, length=10.0, **kwargs):
        self.core_diameter = core_diameter
        self.cladding_diameter = cladding_diameter
        self.length = length
        _set_common_free_space_fields(self, center, angle, kwargs, color="#d7eef7", opacity=0.8, material_preset="sio2")

    def ports(self) -> dict[str, Port]:
        """Expose the free-space ferrule tip and the fiber-side connector."""

        return {
            "in": Port("in", Vec3(-self.length * 0.5, 0.0, 0.0),
                       orientation_deg=180.0, width=self.core_diameter, kind="free_space"),
            "out": Port("out", Vec3(self.length * 0.45, 0.0, 0.0),
                        orientation_deg=0.0, width=self.core_diameter, kind="fiber"),
        }

    def beam_anchor_point(self) -> Vec3:
        """Anchor a default free-space beam at the exposed fiber tip."""

        return self.world_port("in").center

    def geometry_2d(self) -> dict[str, Any]:
        L, cd = self.length, self.cladding_diameter
        return {
            "type": "group",
            "children": [
                # FC connector body (knurled grip)
                {"type": "rect", "cx": L * 0.2, "cy": 0, "w": L * 0.5, "h": cd, "fill": "#3a3f47", "stroke": "#1b1f24", "stroke_width": 0.08},
                *[{"type": "line", "x1": L * (-0.02 + i * 0.07), "y1": -cd * 0.5, "x2": L * (-0.02 + i * 0.07), "y2": cd * 0.5, "stroke": "#22262c", "stroke_width": 0.04} for i in range(6)],
                # connector key
                {"type": "rect", "cx": L * 0.08, "cy": -cd * 0.55, "w": L * 0.1, "h": cd * 0.2, "fill": "#1b1f24"},
                # protruding zirconia ceramic ferrule (toward free space, −x)
                {"type": "rect", "cx": -L * 0.3, "cy": 0, "w": L * 0.4, "h": cd * 0.34, "fill": "#eef2f7", "stroke": "#b8c2cc", "stroke_width": 0.05},
                # glowing fiber core through the ferrule tip
                {"type": "line", "x1": -L * 0.5, "y1": 0.0, "x2": L * 0.1, "y2": 0.0, "stroke": "#9be7ff", "stroke_width": max(self.core_diameter, 0.35), "opacity": 0.92},
            ],
        }

    def geometry_3d(self) -> dict[str, Any]:
        # A fibre connector in a fixed ring holder: an FC adapter plate in the holder, the ceramic ferrule
        # through the plate toward the beam (-x), and behind the plate the receptacle, the FC nut, the boot and
        # the fibre jacket out to the fibre port; a stem carries the holder to the post.
        L, cd = self.length, self.cladding_diameter
        plate_x = -L * 0.1
        ferrule = L * 0.375
        ferrule_x = plate_x - L * 0.025 - ferrule / 2.0
        dark = {"color": "#3a3f47", "metalness": 0.6, "roughness": 0.3, "preset": "steel"}
        return {
            "shape": "group",
            "children": [
                {**_ring_along_x(cd * 0.56, cd * 0.85, L * 0.12, _MOUNT_BLACK, x=plate_x), "role": "holder"},
                _cylinder_along_x(cd * 0.56, L * 0.05, _MOUNT_ALU, position=[plate_x, 0.0, 0.0]),
                {**_cylinder_along_x(cd * 0.17, ferrule, {"color": "#eef2f7", "metalness": 0.1, "roughness": 0.2, "preset": "ceramic"}, position=[ferrule_x, 0.0, 0.0]), "role": "ferrule"},
                _cylinder_along_x(max(self.core_diameter / 2.0, cd * 0.025), ferrule + 0.02, {"color": "#9be7ff", "emissive": "#3aa0d0", "emissiveIntensity": 0.6}, position=[ferrule_x, 0.0, 0.0]),
                _cylinder_along_x(cd * 0.24, L * 0.08, _MOUNT_ALU, position=[plate_x + L * 0.065, 0.0, 0.0]),
                {**_cylinder_along_x(cd * 0.32, L * 0.16, dark, position=[plate_x + L * 0.185, 0.0, 0.0]), "role": "nut"},
                {"shape": "box", "width": L * 0.06, "height": cd * 0.1, "depth": cd * 0.1, "position": [plate_x + L * 0.13, cd * 0.34, 0.0], "material": dark},
                _cylinder_along_x(cd * 0.16, L * 0.175, {"color": "#1b1f24", "roughness": 0.6}, position=[plate_x + L * 0.3525, 0.0, 0.0]),
                _cylinder_along_x(cd * 0.07, L * 0.11, {"color": "#e8b100", "roughness": 0.6}, position=[L * 0.395, 0.0, 0.0]),
                {"shape": "cylinder", "radius": cd * 0.04, "height": cd * 0.1, "position": [plate_x, cd * 0.88, 0.0], "material": _KNOB_STEEL},
                {"shape": "box", "width": L * 0.1, "height": cd * 0.2, "depth": cd * 0.3, "position": [plate_x, -cd * 0.93, 0.0], "material": _MOUNT_BLACK},
            ],
            "post_at": [plate_x, -cd * 1.03, 0.0],
        }

    def physics_metadata(self) -> dict[str, Any]:
        return _optical_metadata("fiber_port", core_diameter=self.core_diameter, cladding_diameter=self.cladding_diameter)


@dataclass
class FiberCollimator(Component):
    """Fiber collimator with ferrule, barrel, and lens metadata."""

    component_type = "FiberCollimator"
    aperture: float = 6.0
    length: float = 14.0
    focal_length: float | None = None

    def __init__(self, center=(0, 0), angle=0, aperture=6.0, length=14.0, focal_length=None, **kwargs):
        self.aperture = aperture
        self.length = length
        self.focal_length = focal_length
        _set_common_free_space_fields(self, center, angle, kwargs, color="#59636e", opacity=1.0, material_preset="steel")

    def geometry_2d(self) -> dict[str, Any]:
        L, a = self.length, self.aperture
        return {
            "type": "group",
            "children": [
                # collimator barrel
                {"type": "rect", "cx": -L * 0.05, "cy": 0, "w": L * 0.62, "h": a, "fill": self.color, "stroke": "#232931", "stroke_width": 0.08},
                # knurled focus / lock ring
                {"type": "rect", "cx": -L * 0.05, "cy": 0, "w": L * 0.14, "h": a * 1.06, "fill": "#39424c", "stroke": "#232931", "stroke_width": 0.06},
                # FC connector receptacle at the back (−x)
                {"type": "rect", "cx": -L * 0.45, "cy": 0, "w": L * 0.2, "h": a * 0.66, "fill": "#2f363f", "stroke": "#1b1f24", "stroke_width": 0.06},
                {"type": "line", "x1": -L * 0.5, "y1": 0.0, "x2": -L * 0.3, "y2": 0.0, "stroke": "#9be7ff", "stroke_width": 0.22, "opacity": 0.85},
                # recessed output lens behind the front aperture (+x) + retaining ring
                {"type": "circle", "cx": L * 0.24, "cy": 0, "r": a * 0.34, "fill": "#9fd3ff", "opacity": 0.5, "stroke": "#5d8fb2", "stroke_width": 0.06},
                {"type": "circle", "cx": L * 0.26, "cy": 0, "r": a * 0.42, "fill": "none", "stroke": "#cbd5df", "stroke_width": 0.1},
                # collimated output ray
                {"type": "line", "x1": L * 0.26, "y1": 0.0, "x2": L * 0.6, "y2": 0.0, "stroke": "#e9f6ff", "stroke_width": 0.18, "opacity": 0.6},
            ],
        }

    def geometry_3d(self) -> dict[str, Any]:
        L, a = self.length, self.aperture
        return {
            "shape": "group",
            "children": [
                # collimator barrel (front edge at ~+L*0.27)
                _ring_along_x(a * 0.42, a * 0.5, L * 0.66, {"color": self.color, "metalness": 0.32, "roughness": 0.48, "preset": self.material_preset}, x=-L * 0.06),
                # knurled focus / lock ring: the ring, its teeth on it
                _ring_along_x(a * 0.5, a * 0.535, L * 0.14, {"color": "#2a3038", "metalness": 0.5, "roughness": 0.3, "preset": "steel"}, x=-L * 0.06),
                *_knurl_teeth(a * 0.54, 22, x=-L * 0.06, width=L * 0.14, color="#2a3038"),
                # FC connector receptacle at the back
                _ring_along_x(a * 0.06, a * 0.33, L * 0.22, {"color": "#2f363f", "metalness": 0.5, "roughness": 0.35, "preset": "steel"}, x=-L * 0.46),
                # collimating lens RECESSED in the front aperture (not protruding)
                {"shape": "sphere", "radius": a * 0.42, "scale": [0.16, 1.0, 1.0], "position": [L * 0.2, 0.0, 0.0], "material": {**_transparent_material("#9fd3ff", 0.5, "glass"), "transmission": 0.5, "ior": 1.52, "clearcoat": 0.7}},
                # retaining ring flush with the barrel front edge
                _rim_along_x(a * 0.48, max(a * 0.05, 0.1), {"color": "#cbd5df", "metalness": 0.3, "roughness": 0.32}, position=[L * 0.27, 0.0, 0.0]),
                # FiberPort-style (PAF2) wide mounting flange + three tip/tilt adjusters
                _ring_along_x(a * 0.426, a * 0.92, L * 0.09, _MOUNT_BLACK, x=L * 0.1),
                _post_boss(a * 0.92, L * 0.09, x=L * 0.1),
                *[_cylinder_along_x(a * 0.08, L * 0.12, _KNOB_STEEL, position=[L * 0.06, math.sin(t) * a * 0.66, math.cos(t) * a * 0.66]) for t in (math.pi / 2.0, math.pi / 2.0 + 2.0 * math.pi / 3.0, math.pi / 2.0 + 4.0 * math.pi / 3.0)],
            ],
            "post_at": [L * 0.1, -a * 0.92 * 1.12, 0.0],
        }

    def ports(self) -> dict[str, Port]:
        # back FC input, collimated output at the front aperture (matches the geometry)
        return {
            "in": Port("in", Vec3(-self.length * 0.5, 0.0, 0.0), orientation_deg=180.0, width=self.aperture * 0.5, kind="fiber"),
            "out": Port("out", Vec3(self.length * 0.3, 0.0, 0.0), orientation_deg=0.0, width=self.aperture, kind="free_space"),
        }

    def beam_anchor_point(self) -> Vec3:
        """Start a default free-space beam at the collimator output."""

        return self.world_port("out").center

    def physics_metadata(self) -> dict[str, Any]:
        return _optical_metadata("fiber_collimator", aperture=self.aperture, focal_length=self.focal_length)


class PolarizationController(Component):
    """Fibre polarization controller: a fibre wound on paddles that turn about the fibre.

    Three paddles is the usual form: a quarter-wave loop, a half-wave loop and a
    quarter-wave loop. The light stays in the fibre, so both ports are fibre ports.
    """

    component_type = "PolarizationController"
    lies_on_table = True
    _PADDLE_TILTS = (-0.5, 0.35, -0.2, 0.5)          # radians about the fibre: paddles sit at different angles
    _FIBRE = "#f59e0b"                               # amber, as the fibre in its symbol and the fibre routes

    def __init__(self, center=(0, 0), angle=0, length=60.0, paddle_diameter=14.0, paddles=3, **kwargs):
        if int(paddles) < 1:
            raise ValueError("paddles must be 1 or more")
        self.length = float(length)
        self.paddle_diameter = float(paddle_diameter)
        self.paddles = int(paddles)
        _set_common_free_space_fields(self, center, angle, kwargs, color="#2f363f", opacity=1.0, material_preset="steel")

    def _paddle_positions(self) -> list[float]:
        pitch = self.length * 0.72 / self.paddles
        return [(index - (self.paddles - 1) / 2.0) * pitch for index in range(self.paddles)]

    def ports(self) -> dict[str, Port]:
        half = self.length / 2.0
        return {
            "in": Port("in", Vec3(-half, 0.0, 0.0), orientation_deg=180.0, width=0.9, kind="fiber"),
            "out": Port("out", Vec3(half, 0.0, 0.0), orientation_deg=0.0, width=0.9, kind="fiber"),
        }

    def symbol_1d(self) -> tuple[str, dict[str, Any]]:
        return "polcontroller", {"count": self.paddles}

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data.update(length=self.length, paddle_diameter=self.paddle_diameter, paddles=self.paddles)
        return data

    def geometry_2d(self) -> dict[str, Any]:
        length, radius = self.length, self.paddle_diameter / 2.0
        children: list[dict[str, Any]] = [
            # the base that holds the paddles
            {"type": "rect", "cx": 0.0, "cy": -radius * 0.2, "w": length * 0.86, "h": radius * 0.4,
             "fill": self.color, "stroke": "#1b1f24", "stroke_width": 0.08, "opacity": self.opacity},
        ]
        for x in self._paddle_positions():
            children.extend([
                # the paddle, then the loop of fibre wound on it
                {"type": "circle", "cx": x, "cy": radius, "r": radius, "fill": "#59636e", "stroke": "#1b1f24",
                 "stroke_width": 0.08, "opacity": self.opacity},
                {"type": "circle", "cx": x, "cy": radius, "r": radius * 0.78, "fill": "none",
                 "stroke": self._FIBRE, "stroke_width": 0.3},
            ])
        children.append({"type": "line", "x1": -length / 2.0, "y1": 0.0, "x2": length / 2.0, "y2": 0.0,
                         "stroke": self._FIBRE, "stroke_width": 0.3})
        return {"type": "group", "children": children}

    def geometry_3d(self) -> dict[str, Any]:
        """On the table: the base, a clamp at each end, the fibre at the cable height, the paddles round it."""

        length, radius = self.length, self.paddle_diameter / 2.0
        fibre = {"color": self._FIBRE, "roughness": 0.6}
        base = LEAD_HEIGHT - 0.9
        clamp_x = length * 0.43 - 1.5
        children: list[dict[str, Any]] = [
            _box_3d(length * 0.86, radius * 1.1, base,
                    {"color": self.color, "metalness": 0.4, "roughness": 0.5, "preset": self.material_preset}),
            *[_box_3d(2.0, radius * 0.6, 1.8, _SLATE_3D, x=sign * clamp_x, y=base) for sign in (-1.0, 1.0)],
            _cylinder_along_x(_LEAD_R, length, fibre, position=[0.0, LEAD_HEIGHT, 0.0]),
        ]
        for index, x in enumerate(self._paddle_positions()):
            tilt = self._PADDLE_TILTS[index % len(self._PADDLE_TILTS)]
            centre = [x, LEAD_HEIGHT + radius * math.cos(tilt), radius * math.sin(tilt)]   # the loop stays tangent to the fibre
            children.extend([
                {"shape": "cylinder", "radius": radius, "height": radius * 0.12,
                 "rotation": [math.pi / 2.0 + tilt, 0.0, 0.0], "position": centre,
                 "material": {"color": "#59636e", "metalness": 0.3, "roughness": 0.55}},
                {"shape": "torus", "radius": radius * 0.78, "tube": 0.45, "rotation": [tilt, 0.0, 0.0],
                 "position": centre, "material": fibre},
            ])
        return {"shape": "group", "children": children}

    def physics_metadata(self) -> dict[str, Any]:
        return _optical_metadata("polarization_controller", paddles=self.paddles, paddle_diameter=self.paddle_diameter)



# ---------------------------------------------------------------- fibre parts that papers show
# Each is drawn in 2D by its symbol (optodraw/symbols); geometry_2d gives the bounds and the
# plain drawing when art is off. Port positions follow the symbol, so the art fits exactly.
_FIBRE = "#f59e0b"                                   # amber: the fibre in the symbols, the 3D parts and the routes
_HOUSING = "#e2e8f0"
LEAD_HEIGHT = 2.2               # the viewer runs fibre and bench cables this high over the table (its CABLE_Y)
_LEAD_R = 0.45
_FIBRE_3D = {"color": _FIBRE, "roughness": 0.55}
_BODY_3D = {"color": _HOUSING, "metalness": 0.15, "roughness": 0.45}
_SLATE_3D = {"color": "#64748b", "metalness": 0.3, "roughness": 0.45}
_BOOT_3D = {"color": "#334155", "roughness": 0.6}
_BOOT_L = 2.4                   # a strain-relief boot where a lead leaves a body


def _fibre_line(x1: float, y1: float, x2: float, y2: float) -> dict[str, Any]:
    return {"type": "line", "x1": x1, "y1": y1, "x2": x2, "y2": y2, "stroke": _FIBRE, "stroke_width": 0.6}


def _fibre_port(name: str, x: float, y: float, orientation: float) -> Port:
    return Port(name, Vec3(x, y, 0.0), orientation_deg=orientation, width=0.9, kind="fiber")


def _box_3d(width: float, depth: float, height: float, material: dict[str, Any], *, x: float = 0.0, y: float = 0.0,
            z: float = 0.0) -> dict[str, Any]:
    """A box standing on y (its base), centred on x and z."""

    return {"shape": "box", "width": width, "height": height, "depth": depth, "position": [x, y + height / 2.0, z],
            "material": material}


def _lead_x(x0: float, x1: float, z: float = 0.0) -> dict[str, Any]:
    return _cylinder_along_x(_LEAD_R, abs(x1 - x0), _FIBRE_3D, position=[(x0 + x1) / 2.0, LEAD_HEIGHT, z])


def _lead_z(z0: float, z1: float, x: float = 0.0) -> dict[str, Any]:
    return {"shape": "cylinder", "radius": _LEAD_R, "height": abs(z1 - z0), "rotation": [math.pi / 2.0, 0.0, 0.0],
            "position": [x, LEAD_HEIGHT, (z0 + z1) / 2.0], "material": _FIBRE_3D}


def _boot_x(face: float, sign: float) -> dict[str, Any]:
    return _cylinder_along_x(0.9, _BOOT_L, _BOOT_3D, position=[face + sign * _BOOT_L / 2.0, LEAD_HEIGHT, 0.0])


def _boot_z(face: float, sign: float) -> dict[str, Any]:
    return {"shape": "cylinder", "radius": 0.9, "height": _BOOT_L, "rotation": [math.pi / 2.0, 0.0, 0.0],
            "position": [0.0, LEAD_HEIGHT, face + sign * _BOOT_L / 2.0], "material": _BOOT_3D}


def _inline_leads(half: float, face: float) -> list[dict[str, Any]]:
    """Boots on the two x faces of a body, and the leads from them out to the ports at +-half."""

    return [_boot_x(-face, -1.0), _lead_x(-half, -face - _BOOT_L), _boot_x(face, 1.0), _lead_x(face + _BOOT_L, half)]


class FiberAmplifier(Component):
    """Doped-fibre amplifier (an EDFA for the C band): fibre in, amplified fibre out."""

    component_type = "FiberAmplifier"
    lies_on_table = True

    def __init__(self, center=(0, 0), angle=0, length=40.0, gain_db=20.0, doping="erbium", **kwargs):
        self.length = float(length)
        self.gain_db = float(gain_db)
        self.doping = str(doping)
        _set_common_free_space_fields(self, center, angle, kwargs, color=_HOUSING, opacity=1.0, material_preset="plastic")

    def ports(self) -> dict[str, Port]:
        half = self.length / 2.0
        return {"in": _fibre_port("in", -half, 0.0, 180.0), "out": _fibre_port("out", half, 0.0, 0.0)}

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data.update(length=self.length, gain_db=self.gain_db, doping=self.doping)
        return data

    def geometry_2d(self) -> dict[str, Any]:
        s = self.length / 1.4                          # units per symbol cm
        tip, back, h = 0.35 * s, -0.3 * s, 0.3 * s
        return {"type": "group", "children": [
            _fibre_line(-self.length / 2.0, 0.0, back, 0.0), _fibre_line(tip, 0.0, self.length / 2.0, 0.0),
            {"type": "polygon", "points": [(back, -h), (back, h), (tip, 0.0)], "fill": self.color,
             "stroke": "#94a3b8", "stroke_width": 0.2},
        ]}

    def geometry_3d(self) -> dict[str, Any]:
        """A benchtop module: the amplifier triangle on its lid, the coil of doped fibre on the triangle."""

        s, half = self.length / 1.4, self.length / 2.0
        width, depth, height = 0.6 * s, 0.5 * s, 0.3 * s
        triangle = [(-0.2 * s, -0.17 * s), (0.22 * s, 0.0), (-0.2 * s, 0.17 * s)]
        coils = [{"shape": "torus", "radius": 0.05 * s, "tube": 0.22, "rotation": [math.pi / 2.0, 0.0, 0.0],
                  "position": [x * s, height + 0.52, 0.0], "material": _FIBRE_3D} for x in (-0.15, -0.08, -0.01)]
        return {"shape": "group", "children": [
            _box_3d(width, depth, height, _BODY_3D),
            {"shape": "extruded_polygon", "points": triangle, "height": 0.3, "position": [0.0, height, 0.0],
             "material": _SLATE_3D},
            *coils,
            *_inline_leads(half, width / 2.0),
        ]}

    def physics_metadata(self) -> dict[str, Any]:
        return _optical_metadata("fiber_amplifier", gain_db=self.gain_db, doping=self.doping)


class FiberCirculator(Component):
    """Three-port fibre circulator: light from p1 leaves at p2, light into p2 leaves at p3."""

    component_type = "FiberCirculator"
    lies_on_table = True

    def __init__(self, center=(0, 0), angle=0, size=30.0, **kwargs):
        self.size = float(size)
        _set_common_free_space_fields(self, center, angle, kwargs, color=_HOUSING, opacity=1.0, material_preset="plastic")

    def ports(self) -> dict[str, Port]:
        half = self.size / 2.0
        return {"p1": _fibre_port("p1", -half, 0.0, 180.0), "p2": _fibre_port("p2", half, 0.0, 0.0),
                "p3": _fibre_port("p3", 0.0, -half, 270.0)}

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data.update(size=self.size)
        return data

    def geometry_2d(self) -> dict[str, Any]:
        half, r = self.size / 2.0, self.size / 4.0
        return {"type": "group", "children": [
            _fibre_line(-half, 0.0, -r, 0.0), _fibre_line(r, 0.0, half, 0.0), _fibre_line(0.0, -r, 0.0, -half),
            {"type": "circle", "cx": 0.0, "cy": 0.0, "r": r, "fill": self.color, "stroke": "#94a3b8", "stroke_width": 0.2},
        ]}

    def geometry_3d(self) -> dict[str, Any]:
        """A round body with the circulating arrow on its lid; p3 leaves towards the viewer (2D below)."""

        half, r = self.size / 2.0, self.size / 4.0
        height, ring = 0.55 * r, 0.55 * r
        angles = [math.radians(165.0 - 225.0 * k / 24) for k in range(25)]       # 165 deg round to -60 deg
        arc = [(ring * math.cos(a), height + 0.3, -ring * math.sin(a)) for a in angles]
        end = math.radians(-60.0)
        tip_x, tip_y = ring * math.cos(end), ring * math.sin(end)                 # the 2D point the arrow leaves
        dx, dy = math.sin(end), -math.cos(end)                                    # its direction of travel
        head = [(tip_x + dx * 0.32 * r, tip_y + dy * 0.32 * r),
                (tip_x - dy * 0.16 * r, tip_y + dx * 0.16 * r), (tip_x + dy * 0.16 * r, tip_y - dx * 0.16 * r)]
        return {"shape": "group", "children": [
            {"shape": "cylinder", "radius": r, "height": height, "position": [0.0, height / 2.0, 0.0],
             "material": _BODY_3D},
            {"shape": "tube_path", "points": arc, "radius": 0.3, "segments": 48, "material": _SLATE_3D},
            {"shape": "extruded_polygon", "points": head, "height": 0.6, "position": [0.0, height, 0.0],
             "material": _SLATE_3D},
            *_inline_leads(half, r),
            _boot_z(r, 1.0), _lead_z(r + _BOOT_L, half),
        ]}

    def physics_metadata(self) -> dict[str, Any]:
        return _optical_metadata("fiber_circulator", ports=3)


class FiberCoupler(Component):
    """Fused 2x2 fibre coupler: ``ratio`` of the power goes to the cross port."""

    component_type = "FiberCoupler"
    lies_on_table = True

    def __init__(self, center=(0, 0), angle=0, length=40.0, port_gap=10.0, ratio=0.5, **kwargs):
        if not 0.0 <= float(ratio) <= 1.0:
            raise ValueError("ratio must be between 0 and 1")
        self.length = float(length)
        self.port_gap = float(port_gap)
        self.ratio = float(ratio)
        _set_common_free_space_fields(self, center, angle, kwargs, color="#bae6fd", opacity=0.9, material_preset="sio2")

    def ports(self) -> dict[str, Port]:
        x, y = self.length / 2.0, self.port_gap / 2.0
        return {"in1": _fibre_port("in1", -x, y, 180.0), "in2": _fibre_port("in2", -x, -y, 180.0),
                "out1": _fibre_port("out1", x, y, 0.0), "out2": _fibre_port("out2", x, -y, 0.0)}

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data.update(length=self.length, port_gap=self.port_gap, ratio=self.ratio)
        return data

    def geometry_2d(self) -> dict[str, Any]:
        x, y = self.length / 2.0, self.port_gap / 2.0
        tube_x, tube_y, waist = 0.35 * self.length / 0.8 * 0.5, 0.12 * self.port_gap / 0.4, 0.04 * self.port_gap / 0.4
        lines = []
        for sy in (1.0, -1.0):
            lines += [_fibre_line(-x, sy * y, -tube_x, sy * waist), _fibre_line(-tube_x, sy * waist, tube_x, sy * waist),
                      _fibre_line(tube_x, sy * waist, x, sy * y)]
        return {"type": "group", "children": [
            {"type": "rect", "cx": 0.0, "cy": 0.0, "w": 2.0 * tube_x, "h": 2.0 * tube_y, "fill": self.color,
             "opacity": self.opacity, "stroke": "#38bdf8", "stroke_width": 0.2}, *lines]}

    def _fibre_path(self, sign: float) -> list[tuple[float, float]]:
        """One fibre in 2D, as in the symbol: in from its port, close to the other fibre in the sleeve, out again."""

        xs, ys = self.length / 1.6, (self.port_gap / 2.0) / 0.2              # symbol units to scene units
        p0, p1, p2, p3 = (-0.8, 0.2 * sign), (-0.55, 0.2 * sign), (-0.45, 0.04 * sign), (-0.25, 0.04 * sign)
        left = []
        for k in range(11):
            t = k / 10.0
            x = (1 - t) ** 3 * p0[0] + 3 * (1 - t) ** 2 * t * p1[0] + 3 * (1 - t) * t ** 2 * p2[0] + t ** 3 * p3[0]
            y = (1 - t) ** 3 * p0[1] + 3 * (1 - t) ** 2 * t * p1[1] + 3 * (1 - t) * t ** 2 * p2[1] + t ** 3 * p3[1]
            left.append((x * xs, y * ys))
        return left + [(0.0, 0.04 * sign * ys)] + [(-x, y) for x, y in reversed(left)]

    def geometry_3d(self) -> dict[str, Any]:
        """The fused fibres in a glass sleeve with sealed ends; the sleeve lies on the table."""

        sleeve = 0.35 * self.length / 1.6
        fibres = [{"shape": "tube_path", "points": [(x, LEAD_HEIGHT, -y) for x, y in self._fibre_path(sign)],
                   "radius": _LEAD_R, "segments": 64, "material": _FIBRE_3D} for sign in (1.0, -1.0)]
        return {"shape": "group", "children": [
            _cylinder_along_x(LEAD_HEIGHT, 2.0 * sleeve, _transparent_material(self.color, 0.45, "glass"),
                              position=[0.0, LEAD_HEIGHT, 0.0]),
            *[_cylinder_along_x(LEAD_HEIGHT * 0.99, 0.8, _SLATE_3D, position=[x, LEAD_HEIGHT, 0.0]) for x in (-sleeve, sleeve)],
            *fibres,
        ]}

    def physics_metadata(self) -> dict[str, Any]:
        return _optical_metadata("fiber_coupler", ratio=self.ratio)


class FiberSpool(Component):
    """A spool of fibre: a delay line or a fibre link of ``fiber_length_km``."""

    component_type = "FiberSpool"
    lies_on_table = True

    def __init__(self, center=(0, 0), angle=0, diameter=20.0, fiber_length_km=1.0, **kwargs):
        self.diameter = float(diameter)
        self.fiber_length_km = float(fiber_length_km)
        _set_common_free_space_fields(self, center, angle, kwargs, color="#cbd5e1", opacity=1.0, material_preset="aluminum")

    @property
    def _span(self) -> float:
        return self.diameter * 1.8                     # the leads reach past the flange, as in the symbol

    def ports(self) -> dict[str, Port]:
        half = self._span / 2.0
        return {"in": _fibre_port("in", -half, 0.0, 180.0), "out": _fibre_port("out", half, 0.0, 0.0)}

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data.update(diameter=self.diameter, fiber_length_km=self.fiber_length_km)
        return data

    def geometry_2d(self) -> dict[str, Any]:
        half, r = self._span / 2.0, self.diameter / 2.0
        rings = [{"type": "circle", "cx": 0.0, "cy": 0.0, "r": r * k, "fill": "none", "stroke": _FIBRE,
                  "stroke_width": 0.4} for k in (0.85, 0.7, 0.55)]
        return {"type": "group", "children": [
            _fibre_line(-half, 0.0, -r, 0.0), _fibre_line(r, 0.0, half, 0.0),
            {"type": "circle", "cx": 0.0, "cy": 0.0, "r": r, "fill": self.color, "stroke": "#94a3b8", "stroke_width": 0.2},
            *rings, {"type": "circle", "cx": 0.0, "cy": 0.0, "r": r * 0.3, "fill": "#64748b"}]}

    def geometry_3d(self) -> dict[str, Any]:
        """A flanged spool lying flat, the windings seen through a clear top flange, the leads off the windings."""

        r, half = self.diameter / 2.0, self._span / 2.0
        flange, wound, core = 0.08 * r, 0.45 * r, 0.86 * r
        flange_3d = {"color": self.color, "metalness": 0.5, "roughness": 0.4}
        turns = [{"shape": "torus", "radius": core, "tube": 0.12, "rotation": [math.pi / 2.0, 0.0, 0.0],
                  "position": [0.0, flange + wound * k / 4.0, 0.0], "material": {"color": "#d97706", "roughness": 0.6}}
                 for k in (1, 2, 3)]
        return {"shape": "group", "children": [
            {"shape": "cylinder", "radius": r, "height": flange, "position": [0.0, flange / 2.0, 0.0], "material": flange_3d},
            {"shape": "cylinder", "radius": core, "height": wound, "position": [0.0, flange + wound / 2.0, 0.0],
             "material": _FIBRE_3D},
            *turns,
            {"shape": "cylinder", "radius": r, "height": flange, "position": [0.0, flange * 1.5 + wound, 0.0],
             "material": {**flange_3d, "opacity": 0.55, "transparent": True}},
            {"shape": "cylinder", "radius": 0.28 * r, "height": wound + 2.0 * flange + 0.6,
             "position": [0.0, (wound + 2.0 * flange + 0.6) * 0.51, 0.0], "material": _SLATE_3D},   # off the flange's base
            _lead_x(-half, -core), _lead_x(core, half),
        ]}

    def physics_metadata(self) -> dict[str, Any]:
        return _optical_metadata("fiber_spool", fiber_length_km=self.fiber_length_km)


class VariableAttenuator(Component):
    """Variable optical attenuator (VOA) in a fibre line."""

    component_type = "VariableAttenuator"
    lies_on_table = True

    def __init__(self, center=(0, 0), angle=0, length=30.0, attenuation_db=3.0, **kwargs):
        self.length = float(length)
        self.attenuation_db = float(attenuation_db)
        _set_common_free_space_fields(self, center, angle, kwargs, color=_HOUSING, opacity=1.0, material_preset="plastic")

    def ports(self) -> dict[str, Port]:
        half = self.length / 2.0
        return {"in": _fibre_port("in", -half, 0.0, 180.0), "out": _fibre_port("out", half, 0.0, 0.0)}

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data.update(length=self.length, attenuation_db=self.attenuation_db)
        return data

    def geometry_2d(self) -> dict[str, Any]:
        s = self.length / 1.2
        half, bx, by = self.length / 2.0, 0.18 * s, 0.2 * s
        return {"type": "group", "children": [
            _fibre_line(-half, 0.0, -bx, 0.0), _fibre_line(bx, 0.0, half, 0.0),
            {"type": "rect", "cx": 0.0, "cy": 0.0, "w": 2.0 * bx, "h": 2.0 * by, "fill": self.color,
             "stroke": "#94a3b8", "stroke_width": 0.2},
            {"type": "line", "x1": -0.26 * s, "y1": -0.28 * s, "x2": 0.26 * s, "y2": 0.28 * s,
             "stroke": "#475569", "stroke_width": 0.3}]}

    def geometry_3d(self) -> dict[str, Any]:
        """A housing with the attenuating filter window on its lid and the arrow of "variable" across it."""

        s, half = self.length / 1.2, self.length / 2.0
        width, depth, height = 0.36 * s, 0.4 * s, 0.3 * s
        c, w, head = math.sqrt(0.5), 0.02 * s, 0.07 * s                         # the arrow runs at 45 degrees
        reach = 0.2 * s
        shaft_end = reach - head
        arrow = [(-reach * c + w * c, -reach * c - w * c), (shaft_end * c + w * c, shaft_end * c - w * c),
                 (shaft_end * c + 2.2 * w * c, shaft_end * c - 2.2 * w * c), (reach * c, reach * c),
                 (shaft_end * c - 2.2 * w * c, shaft_end * c + 2.2 * w * c), (shaft_end * c - w * c, shaft_end * c + w * c),
                 (-reach * c - w * c, -reach * c + w * c)]
        return {"shape": "group", "children": [
            _box_3d(width, depth, height, _BODY_3D),
            _box_3d(0.2 * s, 0.24 * s, 0.12, {"color": "#94a3b8", "metalness": 0.1, "roughness": 0.3}, y=height),
            {"shape": "extruded_polygon", "points": arrow, "height": 0.25, "position": [0.0, height + 0.12, 0.0],
             "material": {"color": "#334155", "roughness": 0.5}},
            *_inline_leads(half, width / 2.0),
        ]}

    def physics_metadata(self) -> dict[str, Any]:
        return _optical_metadata("variable_attenuator", attenuation_db=self.attenuation_db)
