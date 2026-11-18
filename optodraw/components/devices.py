"""Optoelectronic sources, detectors, and instrument-style devices.

The simple source/detector classes provide compact 3D stand-ins for free-space
diagrams. ``FiberLaser`` is more detailed: it models a laser controller/head,
fiber pigtail, output probe, and emission anchor so the beam can start at the
probe tip instead of the component origin.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from optodraw.core.component import Component
from optodraw.core.ports import Port
from optodraw.core.transform import Transform, Vec3
from optodraw.core.beam import wavelength_to_hex
from optodraw.components.optics._shared import (
    _MOUNT_ALU,
    _MOUNT_BLACK,
    _post_boss,
    _ring_along_x,
    _set_common_free_space_fields,
    _tube_clamp,
)
from optodraw.components.optics.fibers import LEAD_HEIGHT
from optodraw.components.optics.optomech import BEAM_HEIGHT
from optodraw.components.optics.sensors import _camera_housing


def _cylinder_along_x(radius: float, height: float, material: dict[str, Any], **extra: Any) -> dict[str, Any]:
    """Create a cylinder whose long axis follows local ``x``."""

    return {"shape": "cylinder", "radius": radius, "height": height, "rotation": [0.0, 0.0, math.pi / 2.0], "material": material, **extra}


def _flat_torus(radius: float, tube: float, material: dict[str, Any], **extra: Any) -> dict[str, Any]:
    """Create a torus lying in the local ``x-y`` plane."""

    return {"shape": "torus", "radius": radius, "tube": tube, "rotation": [math.pi / 2.0, 0.0, 0.0], "material": material, **extra}


def _sample_cubic_bezier(
    p0: tuple[float, float],
    p1: tuple[float, float],
    p2: tuple[float, float],
    p3: tuple[float, float],
    *,
    steps: int = 18,
) -> list[tuple[float, float]]:
    """Sample a cubic Bezier curve into 2D points for SVG-style polylines."""

    points: list[tuple[float, float]] = []
    for index in range(max(steps, 2)):
        t = index / (max(steps, 2) - 1)
        omt = 1.0 - t
        x = omt**3 * p0[0] + 3.0 * omt**2 * t * p1[0] + 3.0 * omt * t**2 * p2[0] + t**3 * p3[0]
        y = omt**3 * p0[1] + 3.0 * omt**2 * t * p1[1] + 3.0 * omt * t**2 * p2[1] + t**3 * p3[1]
        points.append((x, y))
    return points


def _sample_cubic_bezier_3d(
    p0: tuple[float, float, float],
    p1: tuple[float, float, float],
    p2: tuple[float, float, float],
    p3: tuple[float, float, float],
    *,
    steps: int = 18,
) -> list[list[float]]:
    """Sample a cubic Bezier curve into renderer-friendly 3D point lists."""

    points: list[list[float]] = []
    for index in range(max(steps, 2)):
        t = index / (max(steps, 2) - 1)
        omt = 1.0 - t
        x = omt**3 * p0[0] + 3.0 * omt**2 * t * p1[0] + 3.0 * omt * t**2 * p2[0] + t**3 * p3[0]
        y = omt**3 * p0[1] + 3.0 * omt**2 * t * p1[1] + 3.0 * omt * t**2 * p2[1] + t**3 * p3[1]
        z = omt**3 * p0[2] + 3.0 * omt**2 * t * p1[2] + 3.0 * omt * t**2 * p2[2] + t**3 * p3[2]
        points.append([x, y, z])
    return points


@dataclass
class Laser(Component):
    """A laser source.

    Parameters
    ----------
    wavelength : float
        Emission wavelength in nm. Default 532 (green).
    power_label : str
        Optional power annotation (e.g. "5 mW").
    """

    component_type = "Laser"
    wavelength: float = 532.0
    box_size: float = 5.0
    beam_width: float = 1.6
    rays: int = 13
    ray_width: float = 0.45
    beam_color: str | None = None
    divergence_deg: float = 0.0
    show_envelope: bool = False

    def __init__(self, center=(0, 0), angle=0, wavelength=532.0, beam_width=1.6,
                 rays=13, ray_width=0.45, beam_color=None, divergence_deg=0.0,
                 show_envelope=False, sync=False, power_mw: float | None = None,
                 threshold_a: float | None = None, slope_w_per_a: float | None = None, **kwargs):
        """Create a compact laser source.

        Parameters
        ----------
        center, angle
            Component placement and rotation.
        wavelength : float
            Emission wavelength in nanometers. It is converted to the visible
            beam/source color with ``wavelength_to_hex``.
        sync : bool
            A sync output (an electrical port ``sync`` under the head), for a pulsed laser that triggers a
            counter or a scope.
        power_mw, threshold_a, slope_w_per_a : float
            Datasheet numbers: the optical power when nothing drives ``e1`` (None: 1 mW), and the threshold
            current and slope efficiency (W/A) the signal chain reads when a driver does (None: its model default).
        **kwargs
            Supports ``box_size``, ``material_preset``, ``opacity``, and
            ``label``.
        """

        self.wavelength = wavelength
        self.sync = bool(sync)
        self.power_mw, self.threshold_a, self.slope_w_per_a = power_mw, threshold_a, slope_w_per_a
        # Traced-bundle controls: diameter (matches the 3D aperture barrel),
        # ray count (chief + rim), per-ray line width, optional color override
        # (None = the wavelength's color).
        self.beam_width = float(beam_width)
        self.rays = max(1, int(rays))
        self.ray_width = float(ray_width)
        self.beam_color = str(beam_color) if beam_color else None
        # edge-ray half-angle: 0 = collimated, above 0 fans out (lamp / fiber tip)
        self.divergence_deg = max(0.0, float(divergence_deg))
        # fill the cone between the marginal rays (2D figures) as well as the rays
        self.show_envelope = bool(show_envelope)
        self.box_size = kwargs.get("box_size", 5.0)
        self.material_preset = kwargs.get("material_preset", "ceramic")
        self.color = wavelength_to_hex(wavelength)
        self.opacity = kwargs.get("opacity", 1.0)
        self.label = kwargs.get("label", "Laser")
        self.transform = Transform.from_2d(*self._parse_center(center).as_2d(), angle)
        self._parent = None
        self._id = ""

    def symbol_1d(self) -> tuple[str, dict[str, Any]] | None:
        return ("lasersource", {"sync": "yes"}) if self.sync else None

    def symbol_2d(self) -> tuple[str, dict[str, Any]]:
        top = {"view": "top", **({"sync": "yes"} if self.sync else {})}
        return "lasersource", top                   # in 2D a laser head is a long box seen from above

    def ports(self) -> dict[str, Port]:
        """Output port at the emission aperture (+x), the drive input ``e1`` on the rear face (-x); with ``sync``,
        the sync output under the rear of the head."""

        ports = {
            "out": Port("out", Vec3(self.box_size * 1.2, 0.0, 0.0), orientation_deg=0.0,
                        width=self.box_size * 0.4, kind="free_space"),
            # the jack of the 2D art: 2.12 cm of the symbol behind the aperture, at its scale of 1.3155 box per cm
            "e1": Port("e1", Vec3(-self.box_size * 1.589, 0.0, 0.0), orientation_deg=180.0,
                       width=self.box_size * 0.1, kind="electrical"),
        }
        if self.sync:
            ports["sync"] = Port("sync", Vec3(-self.box_size * 0.5, -self.box_size * 0.67, 0.0), orientation_deg=270.0,
                                 width=self.box_size * 0.1, kind="electrical")
        return ports

    def geometry_2d(self) -> dict[str, Any]:
        """A laser head whose aperture reaches the emission port (x = 1.2·box_size),
        so traced rays leave straight from the barrel with no gap. Mirrors the 3D
        head: dark body, steel faceplate, aperture barrel, emissive output dot."""

        sz = self.box_size
        wide = sz * 1.41                 # the head in plan: the proportions of the 3D body, at the size a bench reads
        return {
            "type": "group",
            "children": [
                # main housing
                {"type": "rect", "cx": -sz * 0.4, "cy": 0.0, "w": sz * 2.4, "h": wide,
                 "fill": "#2b3240", "stroke": "#171c26", "stroke_width": sz * 0.04, "opacity": 1.0},
                # steel front faceplate
                {"type": "rect", "cx": sz * 0.88, "cy": 0.0, "w": sz * 0.16, "h": wide,
                 "fill": "#b8bdc3", "stroke": "#8b9299", "stroke_width": sz * 0.02, "opacity": 1.0},
                # aperture barrel, out to the port
                {"type": "rect", "cx": sz * 1.08, "cy": 0.0, "w": sz * 0.24, "h": sz * 0.34,
                 "fill": "#14161c", "stroke": "#0b0d12", "stroke_width": sz * 0.02, "opacity": 1.0},
                # emissive output dot exactly at the port
                {"type": "circle", "cx": sz * 1.2, "cy": 0.0, "r": sz * 0.1,
                 "fill": self.color, "stroke": "none", "opacity": 1.0},
                # warning decal
                {"type": "rect", "cx": -sz * 0.35, "cy": sz * 0.28, "w": sz * 0.4, "h": sz * 0.16,
                 "fill": "#eab308", "stroke": "none", "opacity": 0.95},
                # emission burst at the port — in geometry so EVERY renderer
                # (SVG, TikZ, GLB) draws it and it can never drift off the barrel
                *[
                    {"type": "line",
                     "x1": sz * 1.2 + math.cos(math.pi * k / 3.0) * sz * 0.12,
                     "y1": math.sin(math.pi * k / 3.0) * sz * 0.12,
                     "x2": sz * 1.2 + math.cos(math.pi * k / 3.0) * sz * 0.34,
                     "y2": math.sin(math.pi * k / 3.0) * sz * 0.34,
                     "stroke": self.color, "stroke_width": sz / 14.0, "opacity": 0.9}
                    for k in range(6)
                ],
            ],
        }

    def geometry_3d(self) -> dict[str, Any]:
        """Return a highly detailed, premium solid-state laser head block in 3D."""

        ln, h, d = self.box_size * 2.0, self.box_size, self.box_size
        mat_housing = {"color": "#121b24", "preset": "steel", "metalness": 0.65, "roughness": 0.3}
        mat_silver = {"color": "#b8bdc3", "preset": "steel", "metalness": 0.72, "roughness": 0.22}
        mat_aperture = {"color": "#0d0e12", "preset": "steel", "metalness": 0.8, "roughness": 0.18}
        mat_warning = {"color": "#eab308", "preset": "matte", "roughness": 0.7}
        mat_led = {"color": "#ef4444", "emissive": "#ef4444", "emissiveIntensity": 1.8, "roughness": 0.1}

        # Main housing group
        children = [
            # Main black anodized body
            {"shape": "box", "width": ln * 0.9, "height": h, "depth": d, "position": [-ln * 0.05, 0.0, 0.0], "material": mat_housing},
            # Premium steel front faceplate
            {"shape": "box", "width": ln * 0.1, "height": h, "depth": d, "position": [ln * 0.45, 0.0, 0.0], "material": mat_silver},
            # Aperture barrel
            {"shape": "cylinder", "radius": h * 0.22, "height": ln * 0.12, "rotation": [0.0, 0.0, math.pi / 2.0], "position": [ln * 0.53, 0.0, 0.0], "material": mat_aperture},
            # Emissive laser output dot
            {"shape": "cylinder", "radius": h * 0.08, "height": ln * 0.02, "rotation": [0.0, 0.0, math.pi / 2.0], "position": [ln * 0.59, 0.0, 0.0], "material": {"color": self.color, "emissive": self.color, "emissiveIntensity": 2.2}},
            # Warning Decal (yellow caution plate on side)
            {"shape": "box", "width": ln * 0.25, "height": h * 0.4, "depth": d * 0.02, "position": [-ln * 0.1, h * 0.1, d * 0.505], "material": mat_warning},
            # Status Indicator LED on the back top
            {"shape": "sphere", "radius": h * 0.06, "position": [-ln * 0.4, h * 0.4, d * 0.35], "material": mat_led},
        ]

        # Cooling fins (heatsink blades on top)
        fin_count = 6
        fin_thickness = ln * 0.03
        fin_spacing = ln * 0.12
        fin_height = h * 0.14
        start_x = -ln * 0.38
        for i in range(fin_count):
            children.append({
                "shape": "box",
                "width": fin_thickness,
                "height": fin_height,
                "depth": d * 0.94,
                "position": [start_x + i * fin_spacing, h * 0.54, 0.0],
                "material": mat_housing
            })

        return {
            "shape": "group",
            "children": children,
        }


@dataclass
class Lamp(Component):
    """A broadband light source (white light, LED, etc.)."""

    component_type = "Lamp"
    box_size: float = 5.0

    def __init__(self, center=(0, 0), angle=0, **kwargs):
        """Create a broadband lamp source visual."""

        self.box_size = kwargs.get("box_size", 5.0)
        self.material_preset = kwargs.get("material_preset", "ceramic")
        self.color = kwargs.get("color", "#edbd2d")
        self.opacity = kwargs.get("opacity", 1.0)
        self.label = kwargs.get("label", "Lamp")
        self.transform = Transform.from_2d(*self._parse_center(center).as_2d(), angle)
        self._parent = None
        self._id = ""

    def ports(self) -> dict[str, Port]:
        """Output port at the emission aperture (+x)."""

        return {
            "out": Port("out", Vec3(self.box_size, 0.0, 0.0), orientation_deg=0.0,
                        width=self.box_size * 0.5, kind="free_space"),
        }

    def geometry_2d(self) -> dict[str, Any]:
        """Lamp housing + condenser output barrel with a glowing aperture (+x)."""

        b = self.box_size
        return {
            "type": "group",
            "children": [
                {"type": "rect", "cx": -b * 0.2, "cy": 0.0, "w": b * 1.5, "h": b, "fill": "#2b2b30", "stroke": "#000000", "stroke_width": 0.08},
                # cooling vents
                *[{"type": "line", "x1": b * (-0.7 + i * 0.18), "y1": -b * 0.5, "x2": b * (-0.7 + i * 0.18), "y2": -b * 0.33, "stroke": "#45454d", "stroke_width": 0.07} for i in range(5)],
                # condenser output housing (+x)
                {"type": "rect", "cx": b * 0.62, "cy": 0.0, "w": b * 0.34, "h": b * 0.62, "fill": "#3a3a40", "stroke": "#000000", "stroke_width": 0.06},
                # glowing emission aperture + halo
                {"type": "circle", "cx": b * 0.8, "cy": 0.0, "r": b * 0.34, "fill": self.color, "opacity": 0.22},
                {"type": "circle", "cx": b * 0.8, "cy": 0.0, "r": b * 0.2, "fill": self.color, "opacity": 0.95},
                # power indicator
                {"type": "circle", "cx": -b * 0.55, "cy": b * 0.34, "r": b * 0.06, "fill": "#2ecc71"},
            ],
        }

    def geometry_3d(self) -> dict[str, Any]:
        """A research lamp housing: an upright brushed-aluminium lamp house with a finned heat sink on top, the
        bulb at the beam height, and a condenser tube out to the output port (+x) with the lens glowing in it.
        The lamp was the laser's black finned block."""

        b = self.box_size
        alu = {"color": "#b4bac1", "metalness": 0.75, "roughness": 0.3, "preset": "aluminum"}
        black = {"color": "#22262c", "metalness": 0.45, "roughness": 0.5}
        house_x, r, half = -b * 0.45, b * 0.75, b * 0.7
        tube_from = house_x + r * 0.9
        return {
            "shape": "group",
            "children": [
                {"shape": "cylinder", "role": "house", "radius": r, "height": 2.0 * half, "position": [house_x, 0.0, 0.0], "material": alu},
                # the house top: a cap plate and a finned heat sink across it
                {"shape": "cylinder", "radius": r * 1.04, "height": b * 0.1, "position": [house_x, half + b * 0.05, 0.0], "material": black},
                *[{"shape": "box", "role": "fin", "width": r * 1.5, "height": b * 0.36, "depth": b * 0.05,
                   "position": [house_x, half + b * 0.1 + b * 0.18, z * r * 0.3], "material": black} for z in (-2, -1, 0, 1, 2)],
                {**_cylinder_along_x(b * 0.28, b - tube_from - b * 0.06, alu, position=[(tube_from + b - b * 0.06) / 2.0, 0.0, 0.0]), "role": "condenser"},
                _ring_along_x(b * 0.22, b * 0.31, b * 0.06, black, x=b - b * 0.03),
                _cylinder_along_x(b * 0.22, b * 0.03, {"color": self.color, "emissive": self.color, "emissiveIntensity": 1.6}, position=[b - b * 0.04, 0.0, 0.0]),
                _cylinder_along_x(b * 0.08, b * 0.5, black, position=[house_x - r - b * 0.2, -half * 0.6, 0.0]),
            ],
        }


@dataclass
class Camera(Component):
    """A CCD/CMOS camera detector."""

    component_type = "Camera"
    box_size: float = 5.0

    def __init__(self, center=(0, 0), angle=0, **kwargs):
        """Create a compact camera detector visual."""

        self.box_size = kwargs.get("box_size", 5.0)
        self.material_preset = kwargs.get("material_preset", "aluminum")
        self.color = kwargs.get("color", "#222222")
        self.opacity = kwargs.get("opacity", 1.0)
        self.label = kwargs.get("label", "Camera")
        self.transform = Transform.from_2d(*self._parse_center(center).as_2d(), angle)
        self._parent = None
        self._id = ""

    def ports(self) -> dict[str, Port]:
        """Input port at the sensor face (-x)."""

        return {
            "in": Port("in", Vec3(-self.box_size * 0.5, 0.0, 0.0), orientation_deg=180.0,
                       width=self.box_size * 0.7, kind="free_space"),
        }

    def geometry_2d(self) -> dict[str, Any]:
        """Scientific camera: body + C-mount lens barrel + sensor, facing the beam (-x)."""

        b = self.box_size
        return {
            "type": "group",
            "children": [
                {"type": "rect", "cx": b * 0.14, "cy": 0.0, "w": b * 0.82, "h": b, "fill": "#1b1b1f", "stroke": "#000000", "stroke_width": 0.08},
                # heat-sink fins on top
                *[{"type": "line", "x1": b * (-0.18 + i * 0.16), "y1": -b * 0.5, "x2": b * (-0.18 + i * 0.16), "y2": -b * 0.33, "stroke": "#42424a", "stroke_width": 0.07} for i in range(5)],
                # C-mount lens barrel on the front (-x)
                {"type": "rect", "cx": -b * 0.42, "cy": 0.0, "w": b * 0.34, "h": b * 0.6, "fill": "#26262b", "stroke": "#000000", "stroke_width": 0.07},
                {"type": "circle", "cx": -b * 0.58, "cy": 0.0, "r": b * 0.21, "fill": "#0a0a0c", "stroke": "#4a4a52", "stroke_width": 0.06},
                {"type": "circle", "cx": -b * 0.58, "cy": 0.0, "r": b * 0.1, "fill": "#16303f", "opacity": 0.92},
                # status LED
                {"type": "circle", "cx": b * 0.42, "cy": b * 0.36, "r": b * 0.05, "fill": "#2ecc71"},
            ],
        }

    def geometry_3d(self) -> dict[str, Any]:
        """A compact scientific camera: the CS-series housing the camera sensors use, its C-mount front at the
        in port (-x)."""

        H = self.box_size * 3.74
        return _camera_housing(H, H * 0.18, H * 0.135, self.ports()["in"].center.x, "#5b626b")


@dataclass
class Photodiode(Component):
    """A photodiode detector."""

    component_type = "Photodiode"
    box_size: float = 5.0

    def __init__(self, center=(0, 0), angle=0, responsivity_a_per_w: float | None = None,
                 dark_current_a: float | None = None, bandwidth_hz: float | None = None, **kwargs):
        """Create a cylindrical photodiode detector visual. ``responsivity_a_per_w``, ``dark_current_a`` and
        ``bandwidth_hz`` are its datasheet numbers for the signal chain; None is the chain's model default."""

        self.responsivity_a_per_w, self.dark_current_a = responsivity_a_per_w, dark_current_a
        self.bandwidth_hz = bandwidth_hz
        self.box_size = kwargs.get("box_size", 5.0)
        self.material_preset = kwargs.get("material_preset", "silicon")
        self.color = kwargs.get("color", "#222222")
        self.opacity = kwargs.get("opacity", 1.0)
        self.label = kwargs.get("label", "Photodiode")
        self.transform = Transform.from_2d(*self._parse_center(center).as_2d(), angle)
        self._parent = None
        self._id = ""

    def symbol_2d(self) -> tuple[str, dict[str, Any]]:
        return "detector", {"view": "top"}          # on a bench: the housing seen from above, not the circuit symbol

    def ports(self) -> dict[str, Port]:
        """Input port at the active face (-x). The anode ``e1`` and the cathode ``e2`` leave at the connector at the
        back, on one coax; in 1D they are the bottom and the top lead of the diode."""

        return {
            "in": Port("in", Vec3(-self.box_size * 0.6, 0.0, 0.0), orientation_deg=180.0,
                       width=self.box_size * 0.6, kind="free_space"),
            # the connector end of the 2D art: 0.84 cm of the symbol behind the face, at 1.295 box per cm
            **{name: Port(name, Vec3(self.box_size * 0.488, 0.0, 0.0), orientation_deg=0.0,
                          width=self.box_size * 0.1, kind="electrical") for name in ("e1", "e2")},
        }

    def geometry_2d(self) -> dict[str, Any]:
        """TO-can photodiode: metal can + windowed active area (front −x) + leads (back)."""

        b = self.box_size
        return {
            "type": "group",
            "children": [
                # leads out the back (+x)
                *[{"type": "line", "x1": b * 0.42, "y1": yy * b * 0.2, "x2": b * 0.8, "y2": yy * b * 0.2, "stroke": "#8b9096", "stroke_width": 0.09} for yy in (-1, 0, 1)],
                # metal TO-can body
                {"type": "rect", "cx": b * 0.02, "cy": 0.0, "w": b * 0.86, "h": b, "fill": "#3a3f45", "stroke": "#15181b", "stroke_width": 0.08},
                # window rim + active area on the front face (−x)
                {"type": "circle", "cx": -b * 0.18, "cy": 0.0, "r": b * 0.44, "fill": "#1a1d21", "stroke": "#0c0e10", "stroke_width": 0.06},
                {"type": "circle", "cx": -b * 0.18, "cy": 0.0, "r": b * 0.24, "fill": "#2b3a52", "stroke": "#4a6c9b", "stroke_width": 0.05, "opacity": 0.95},
                {"type": "circle", "cx": -b * 0.18, "cy": 0.0, "r": b * 0.11, "fill": "#46689c", "opacity": 0.9},
            ],
        }

    def geometry_3d(self) -> dict[str, Any]:
        """A mounted photodiode, as it stands on a bench: the TO-can's window and chip in the front of a black
        housing (axis along x, the light from -x), an SMA connector at the back, and a fixed lens mount with
        a boss for the post. A bare TO-can with its leads in the air is not how a bench holds one."""

        b = self.box_size
        housing = {"color": "#23282e", "metalness": 0.42, "roughness": 0.55, "preset": "aluminum"}
        gold = {"color": "#d4af37", "metalness": 0.8, "roughness": 0.35}
        return {
            "shape": "group",
            "children": [
                _cylinder_along_x(b * 0.5, b * 0.8, housing, position=[b * 0.1, 0.0, 0.0]),
                _ring_along_x(b * 0.3, b * 0.46, b * 0.04, _MOUNT_ALU, x=-b * 0.32),
                _cylinder_along_x(b * 0.22, b * 0.04, {"color": "#2b3a52", "metalness": 0.35, "roughness": 0.2}, position=[-b * 0.32, 0.0, 0.0]),
                {"shape": "sphere", "radius": b * 0.24, "scale": [0.5, 1.0, 1.0], "position": [-b * 0.32, 0.0, 0.0], "material": {"color": "#16303f", "opacity": 0.4, "transparent": True, "clearcoat": 0.85, "roughness": 0.08}},
                _cylinder_along_x(b * 0.16, b * 0.06, gold, position=[b * 0.53, 0.0, 0.0]),
                _cylinder_along_x(b * 0.1, b * 0.22, gold, position=[b * 0.67, 0.0, 0.0]),
                _ring_along_x(b * 0.5, b * 0.68, b * 0.3, _MOUNT_BLACK, x=b * 0.1),
                _post_boss(b * 0.68, b * 0.3, x=b * 0.1),
            ],
            "post_at": [b * 0.1, -b * 0.68 * 1.12, 0.0],
        }


@dataclass
class AmplifiedPhotodetector(Component):
    """Amplified photodetector (PDA36A2 silhouette): a slim upright housing with an SM1 coupler round the
    photodiode on the optical face, the BNC output and power plug on top and the gain knob on a side."""

    component_type = "AmplifiedPhotodetector"
    box_size: float = 7.0
    gain_db: float = 20.0

    def __init__(self, center=(0, 0), angle=0, responsivity_a_per_w: float | None = None,
                 dark_current_a: float | None = None, bandwidth_hz: float | None = None,
                 gain_ohm: float | None = None, **kwargs):
        # the datasheet numbers for the signal chain; None is the chain's model default
        self.responsivity_a_per_w, self.dark_current_a = responsivity_a_per_w, dark_current_a
        self.bandwidth_hz = bandwidth_hz
        self.gain_ohm = gain_ohm
        self.box_size = kwargs.get("box_size", 7.0)
        self.gain_db = kwargs.get("gain_db", 20.0)
        self.material_preset = kwargs.get("material_preset", "steel")
        self.color = kwargs.get("color", "#16181c")
        self.opacity = kwargs.get("opacity", 1.0)
        self.label = kwargs.get("label", "Amp PD")
        self.transform = Transform.from_2d(*self._parse_center(center).as_2d(), angle)
        self._parent = None
        self._id = ""

    def ports(self) -> dict[str, Port]:
        return {
            "in": Port("in", Vec3(-self.box_size * 0.78, 0.0, 0.0), orientation_deg=180.0,
                       width=self.box_size * 0.5, kind="free_space"),
            "out": Port("out", Vec3(self.box_size * 0.7, 0.0, 0.0), orientation_deg=0.0, width=1.0,
                        kind="electrical"),                     # the BNC output, the stub at the back in 2D
        }

    def geometry_2d(self) -> dict[str, Any]:
        b = self.box_size
        return {
            "type": "group",
            "children": [
                {"type": "rect", "cx": 0.0, "cy": 0.0, "w": b, "h": b * 0.82, "fill": self.color, "stroke": "#04060a", "stroke_width": 0.1},
                # threaded input snout (−x)
                {"type": "rect", "cx": -b * 0.62, "cy": 0.0, "w": b * 0.24, "h": b * 0.46, "fill": "#3a3f45", "stroke": "#15181b", "stroke_width": 0.06},
                {"type": "circle", "cx": -b * 0.62, "cy": 0.0, "r": b * 0.14, "fill": "#2b3a52", "stroke": "#4a6c9b", "stroke_width": 0.05},
                # BNC output stub (+x)
                {"type": "rect", "cx": b * 0.6, "cy": 0.0, "w": b * 0.2, "h": b * 0.2, "fill": "#8b9096", "stroke": "#4b5259", "stroke_width": 0.05},
                {"type": "circle", "cx": b * 0.2, "cy": b * 0.26, "r": b * 0.035, "fill": "#3fae5a"},
            ],
        }

    def geometry_3d(self) -> dict[str, Any]:
        # A switchable-gain amplified detector (Thorlabs PDA36A2): an upright housing 70.9 tall, 49.8 wide and
        # 22.5 mm along the beam. On the front, an SM1 coupler round the gold TO-can photodiode, the axis 40 %
        # up the housing, and the label band above; the BNC output and the power plug on top; the power switch,
        # LED and gain knob on a side. The post screws into the flat bottom.
        b = self.box_size
        H = b * 4.0
        T, W = H * 22.5 / 70.9, H * 49.8 / 70.9
        coupler = H * 0.06
        face = self.ports()["in"].center.x + coupler
        cx, cy, top = face + T / 2.0, H * 0.1, H * 0.6
        silver = {"color": "#c9ced4", "metalness": 0.85, "roughness": 0.22, "preset": "steel"}
        gold = {"color": "#d4af37", "metalness": 0.8, "roughness": 0.35}
        return {
            "shape": "group",
            "children": [
                {"shape": "box", "role": "housing", "width": T, "height": H, "depth": W, "position": [cx, cy, 0.0], "material": {"color": self.color, "metalness": 0.45, "roughness": 0.5, "preset": self.material_preset}},
                {**_ring_along_x(H * 0.13, H * 0.21, coupler, _MOUNT_BLACK, x=face - coupler / 2.0), "role": "coupler"},
                _ring_along_x(H * 0.03, H * 0.055, H * 0.02, gold, x=face - H * 0.01),
                _cylinder_along_x(H * 0.03, H * 0.01, {"color": "#d7dde5", "metalness": 0.6, "roughness": 0.1}, position=[face - H * 0.008, 0.0, 0.0]),
                {"shape": "box", "role": "label", "width": H * 0.01, "height": H * 0.06, "depth": W * 0.8, "position": [face - H * 0.005, H * 0.47, 0.0], "material": {"color": "#e5e7eb", "roughness": 0.6}},
                {"shape": "cylinder", "role": "connector", "radius": H * 0.045, "height": H * 0.1, "position": [cx, top + H * 0.05, W * 0.2], "material": silver},
                {"shape": "cylinder", "radius": H * 0.06, "height": H * 0.03, "position": [cx, top + H * 0.015, W * 0.2], "material": silver},
                {"shape": "cylinder", "role": "connector", "radius": H * 0.05, "height": H * 0.08, "position": [cx, top + H * 0.04, -W * 0.2], "material": silver},
                {"shape": "cylinder", "role": "gain", "radius": H * 0.07, "height": H * 0.06, "rotation": [math.pi / 2.0, 0.0, 0.0], "position": [cx, -H * 0.25, W / 2.0 + H * 0.03], "material": {"color": "#202429", "metalness": 0.3, "roughness": 0.5}},
                {"shape": "box", "width": T * 0.3, "height": H * 0.07, "depth": H * 0.02, "position": [cx, H * 0.3, W / 2.0 + H * 0.01], "material": {"color": "#3a3f45", "roughness": 0.5}},
                {"shape": "sphere", "radius": H * 0.015, "position": [cx, H * 0.15, W / 2.0], "material": {"color": "#3fae5a", "emissive": "#3fae5a", "emissiveIntensity": 1.6}},
            ],
        }

    def physics_metadata(self) -> dict[str, Any]:
        return {"domain": "free_space", "component": "amplified_photodetector", "gain_db": self.gain_db}

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["box_size"] = self.box_size
        data["gain_db"] = self.gain_db
        return data


@dataclass
class QuadrantPhotodiode(Component):
    """A quadrant photodiode (QPD): four photodiodes in one disc behind a window, for the position of a beam, as in
    the back-focal-plane detection of an optical trap or a beam-pointing monitor.

    The light enters at ``in`` (local -x). The housing sends the difference of the left and right halves on ``x``,
    of the top and bottom halves on ``y``, and the total on ``sum``, from three connectors on top.
    """

    component_type = "QuadrantPhotodiode"
    box_size: float = 7.0
    active_diameter_mm: float = 7.8
    # One plan in units of box_size for the 2D art, the 3D solids and the pic `od qpd` in od-instruments.tex:
    # the housing is DEPTH deep along the beam and as high as box_size, the coupler stands COUPLER in front,
    # the three connectors sit at OUTPUTS along the beam. Proportions are a schematic of a bench QPD housing.
    DEPTH = 0.56
    COUPLER = 0.14
    OUTPUTS = {"x": -0.14, "y": 0.0, "sum": 0.14}

    def __init__(self, center=(0, 0), angle=0, box_size=7.0, active_diameter_mm=7.8, **kwargs):
        self.box_size = float(box_size)
        self.active_diameter_mm = float(active_diameter_mm)
        self.material_preset = kwargs.get("material_preset", "steel")
        self.color = kwargs.get("color", "#1d2127")
        self.opacity = kwargs.get("opacity", 1.0)
        self.label = kwargs.get("label", "QPD")
        self.transform = Transform.from_2d(*self._parse_center(center).as_2d(), angle)
        self._parent = None
        self._id = ""

    def symbol_2d(self) -> tuple[str, dict[str, Any]]:
        return "qpd", {"view": "top"}               # on a bench: the housing seen from above, with its quadrant mark

    def ports(self) -> dict[str, Port]:
        b = self.box_size
        face = -b * (self.DEPTH / 2.0 + self.COUPLER)
        return {
            "in": Port("in", Vec3(face, 0.0, 0.0), orientation_deg=180.0, width=b * 0.5, kind="free_space"),
            **{name: Port(name, Vec3(b * along, b * 0.6, 0.0), orientation_deg=90.0, width=b * 0.08, kind="electrical")
               for name, along in self.OUTPUTS.items()},
        }

    def geometry_2d(self) -> dict[str, Any]:
        b = self.box_size
        d, c = b * self.DEPTH, b * self.COUPLER
        quadrant = [{"type": "line", "x1": -b * 0.14, "y1": 0.0, "x2": b * 0.14, "y2": 0.0, "stroke": "#e5e7eb", "stroke_width": 0.07},
                    {"type": "line", "x1": 0.0, "y1": -b * 0.14, "x2": 0.0, "y2": b * 0.14, "stroke": "#e5e7eb", "stroke_width": 0.07}]
        return {
            "type": "group",
            "children": [
                {"type": "rect", "cx": 0.0, "cy": 0.0, "w": d, "h": b, "fill": self.color, "stroke": "#04060a", "stroke_width": 0.1},
                {"type": "rect", "cx": -(d + c) / 2.0, "cy": 0.0, "w": c, "h": b * 0.5, "fill": "#3a3f45", "stroke": "#15181b", "stroke_width": 0.06},
                {"type": "circle", "cx": 0.0, "cy": 0.0, "r": b * 0.15, "fill": "#2b3a52", "stroke": "#e5e7eb", "stroke_width": 0.05},
                *quadrant,
                *[{"type": "rect", "cx": b * along, "cy": b * 0.55, "w": b * 0.08, "h": b * 0.1, "fill": "#8b9096", "stroke": "#4b5259", "stroke_width": 0.04}
                  for along in self.OUTPUTS.values()],
            ],
        }

    def geometry_3d(self) -> dict[str, Any]:
        b = self.box_size
        d, c = b * self.DEPTH, b * self.COUPLER
        face = -d / 2.0
        silver = {"color": "#c9ced4", "metalness": 0.85, "roughness": 0.22, "preset": "steel"}
        sensor = {"color": "#22324a", "metalness": 0.35, "roughness": 0.2}
        sector = b * 0.11                                  # each quadrant: a dark square, the gaps between them light
        children: list[dict[str, Any]] = [
            {"shape": "box", "role": "housing", "width": d, "height": b, "depth": b,
             "material": {"color": self.color, "metalness": 0.45, "roughness": 0.5, "preset": self.material_preset}},
            {**_ring_along_x(b * 0.2, b * 0.26, c, _MOUNT_BLACK, x=face - c / 2.0), "role": "coupler"},
            {**_cylinder_along_x(b * 0.19, b * 0.01, {"color": "#d7dde5", "metalness": 0.6, "roughness": 0.1}, position=[face - b * 0.005, 0.0, 0.0]), "role": "gap"},
            *[{"shape": "box", "role": "quadrant", "width": b * 0.012, "height": sector, "depth": sector,
               "position": [face - b * 0.012, sy * sector * 0.56, sz * sector * 0.56], "material": sensor}
              for sy in (-1.0, 1.0) for sz in (-1.0, 1.0)],
            *[{"shape": "cylinder", "role": "connector", "radius": b * 0.04, "height": b * 0.1,
               "position": [b * along, b * 0.55, 0.0], "material": silver} for along in self.OUTPUTS.values()],
            {"shape": "box", "role": "boss", "width": d * 0.8, "height": b * 0.08, "depth": b * 0.3,
             "position": [0.0, -b * 0.54, 0.0], "material": _MOUNT_BLACK},
        ]
        return {"shape": "group", "children": children, "post_at": [0.0, -b * 0.58, 0.0]}

    def physics_metadata(self) -> dict[str, Any]:
        return {"domain": "free_space", "component": "quadrant_photodiode", "active_diameter_mm": self.active_diameter_mm}


@dataclass
class PMT(Component):
    """Photomultiplier tube — a high-gain single-photon-sensitive detector: a photocathode
    window feeds a dynode chain in an evacuated tube, with an HV base."""

    component_type = "PMT"
    tube_diameter: float = 9.0
    length: float = 20.0
    gain: float = 1e6

    def __init__(self, center=(0, 0), angle=0, **kwargs):
        self.tube_diameter = kwargs.get("tube_diameter", 9.0)
        self.length = kwargs.get("length", 20.0)
        self.gain = kwargs.get("gain", 1e6)
        self.material_preset = kwargs.get("material_preset", "glass")
        self.color = kwargs.get("color", "#2b3138")
        self.opacity = kwargs.get("opacity", 1.0)
        self.label = kwargs.get("label", "PMT")
        self.transform = Transform.from_2d(*self._parse_center(center).as_2d(), angle)
        self._parent = None
        self._id = ""

    def ports(self) -> dict[str, Port]:
        return {"in": Port("in", Vec3(-self.length * 0.5, 0.0, 0.0), orientation_deg=180.0, width=self.tube_diameter * 0.7, kind="free_space")}

    def geometry_2d(self) -> dict[str, Any]:
        L, d = self.length, self.tube_diameter
        return {
            "type": "group",
            "children": [
                {"type": "rect", "cx": -L * 0.05, "cy": 0.0, "w": L * 0.62, "h": d, "fill": "#9fc7de", "opacity": 0.4, "stroke": "#5b8faa", "stroke_width": 0.08},
                {"type": "circle", "cx": -L * 0.36, "cy": 0.0, "r": d * 0.44, "fill": "#1b2733", "stroke": "#3a5570", "stroke_width": 0.08},
                {"type": "circle", "cx": -L * 0.36, "cy": 0.0, "r": d * 0.3, "fill": "#2e5a86", "opacity": 0.7},
                {"type": "polyline", "points": [(-L * 0.1, -d * 0.28), (0.0, d * 0.28), (L * 0.1, -d * 0.28), (L * 0.2, d * 0.28)], "closed": False, "stroke": "#8b9096", "stroke_width": 0.12, "opacity": 0.8},
                {"type": "rect", "cx": L * 0.44, "cy": 0.0, "w": L * 0.2, "h": d * 0.9, "fill": "#3a3f45", "stroke": "#15181b", "stroke_width": 0.08},
                *[{"type": "line", "x1": L * 0.54, "y1": yy * d * 0.24, "x2": L * 0.72, "y2": yy * d * 0.24, "stroke": "#8b9096", "stroke_width": 0.08} for yy in (-1, 0, 1)],
            ],
        }

    def geometry_3d(self) -> dict[str, Any]:
        # A PMT works in a light-tight housing: the photocathode shows through the front window (-x), the
        # tube's socket and voltage divider sit in the back, a connector leaves the back cap; a clamp with a
        # boss holds it on its post. A bare glass tube on a post is not how a bench holds one.
        L, r = self.length, self.tube_diameter * 0.5
        clamp, post_at = _tube_clamp(r * 1.12, L * 0.18, x=-L * 0.05)
        housing = {"color": self.color, "metalness": 0.45, "roughness": 0.5, "preset": "aluminum"}
        return {
            "shape": "group",
            "children": [
                _cylinder_along_x(r * 1.12, L * 0.72, housing, position=[-L * 0.06, 0.0, 0.0]),
                _ring_along_x(r * 0.72, r * 1.12, L * 0.03, _MOUNT_ALU, x=-L * 0.435),
                _cylinder_along_x(r * 0.72, L * 0.01, {"color": "#3a6a9c", "metalness": 0.4, "roughness": 0.2, "clearcoat": 0.8}, position=[-L * 0.42, 0.0, 0.0]),
                _cylinder_along_x(r * 1.0, L * 0.12, {"color": "#2f363f", "metalness": 0.5, "roughness": 0.4, "preset": "steel"}, position=[L * 0.36, 0.0, 0.0]),
                _cylinder_along_x(r * 0.2, L * 0.1, {"color": "#c9b56a", "metalness": 0.75, "roughness": 0.3, "preset": "brass"}, position=[L * 0.47, 0.0, 0.0]),
                *clamp,
            ],
            "post_at": post_at,
        }

    def physics_metadata(self) -> dict[str, Any]:
        return {"domain": "free_space", "component": "photomultiplier", "gain": self.gain, "tube_diameter": self.tube_diameter}

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["tube_diameter"] = self.tube_diameter
        data["length"] = self.length
        data["gain"] = self.gain
        return data


@dataclass
class Spectrometer(Component):
    """A Czerny-Turner spectrograph: slit, fold mirror, collimating mirror, grating, focusing mirror, cooled CCD head."""

    component_type = "Spectrometer"
    box_size: float = 10.0
    # The plan in box sizes, y up the page. The chamfered body and the ports follow the data sheet of a 328 mm instrument;
    # the sheet does not show the optics, so the W of the light is a schematic Czerny-Turner with a fold at the side input.
    # od-instruments.tex draws the same numbers in 1D and 2D.
    OUTLINE = ((-0.69, 0.5), (0.75, 0.5), (0.75, -0.5), (-0.3, -0.5), (-0.69, -0.2))
    FLOOR = ((-0.64, 0.45), (0.7, 0.45), (0.7, -0.45), (-0.28, -0.45), (-0.64, -0.18))
    LIGHT_PATH = {"slit": (-0.69, 0.0), "fold": (-0.46, 0.0), "collimator": (-0.46, 0.36), "grating": (0.02, -0.3),
                  "focuser": (0.5, 0.36), "array": (0.5, -0.42)}
    SPECTRUM = ("#8b5cf6", "#38bdf8", "#4ade80", "#facc15", "#f87171")

    @property
    def _art_unit(self) -> float:
        return self.box_size

    def __init__(self, center=(0, 0), angle=0, **kwargs):
        """Create a spectrograph. It stands on four pillars of its own; ``base_mount="post"`` puts it on one post."""

        self.box_size = kwargs.get("box_size", 10.0)
        self.material_preset = kwargs.get("material_preset", "aluminum")
        self.color = kwargs.get("color", "#333333")
        self.opacity = kwargs.get("opacity", 1.0)
        self.label = kwargs.get("label", "Spectrometer")
        self.base_mount = str(kwargs.get("base_mount", "none"))
        self.transform = Transform.from_2d(*self._parse_center(center).as_2d(), angle)
        self._parent = None
        self._id = ""

    def ports(self) -> dict[str, Port]:
        """Input port at the entrance slit (-x)."""

        return {
            "in": Port("in", Vec3(-self.box_size * 0.75, 0.0, 0.0), orientation_deg=180.0,
                       width=self.box_size * 0.5, kind="free_space"),
        }

    def geometry_2d(self) -> dict[str, Any]:
        """The body, the slit and the camera: the bounds of the part. The art paints the optics over them."""

        b = self.box_size
        return {
            "type": "group",
            "children": [
                {"type": "polygon", "points": [(x * b, y * b) for x, y in self.OUTLINE], "fill": "#2a2d31", "stroke": "#000000", "stroke_width": 0.08},
                {"type": "polygon", "points": [(x * b, y * b) for x, y in self.FLOOR], "fill": "#0f172a"},
                {"type": "rect", "cx": -b * 0.72, "cy": 0.0, "w": b * 0.06, "h": b * 0.3, "fill": "#94a3b8"},
                {"type": "rect", "cx": b * 0.5, "cy": -b * 0.66, "w": b * 0.42, "h": b * 0.24, "fill": "#cbd5e1", "stroke": "#64748b", "stroke_width": 0.06},
            ],
        }

    def geometry_3d(self) -> dict[str, Any]:
        """The same plan with the lid off: the optics at the height of the beam, the colours between them, the turret and
        the camera. The walls stand lower than the real ones, so a camera above the bench sees in. The instrument is a
        heavy one, so it stands on a plate and four pillars; a post, if one is asked for, meets the plate."""

        b = self.box_size
        anthracite = {"color": "#3a3f45", "metalness": 0.35, "roughness": 0.55}
        black = {"color": "#1b1f24", "metalness": 0.3, "roughness": 0.6}
        silver = {"color": "#e2e8f0", "metalness": 0.85, "roughness": 0.18}
        pale = {"color": "#aeb6bf", "metalness": 0.5, "roughness": 0.4}
        steel = {"color": "#9aa1a9", "metalness": 0.7, "roughness": 0.35}
        orange = {"color": "#f97316", "metalness": 0.1, "roughness": 0.5}
        floor_y, top_y, plate_y = -0.46 * b, 0.22 * b, -0.56 * b
        outline = [(x * b, y * b) for x, y in self.OUTLINE]
        room = [(x * b, y * b) for x, y in self.FLOOR]

        def at(name: str) -> tuple[float, float]:
            x, y = self.LIGHT_PATH[name]
            return x * b, -y * b                                # the plan's y runs along -z

        def sheet(points: list[tuple[float, float]], material: dict[str, Any], role: str, lift: float = 0.0) -> dict[str, Any]:
            return {"shape": "extruded_polygon", "points": [(x * b, y * b) for x, y in points], "height": b * 0.012,
                    "position": [0.0, -b * 0.006 + lift, 0.0], "material": {**material, "transparent": True, "depthWrite": False}, "role": role}

        def stand(name: str, top: float) -> dict[str, Any]:
            x, z = at(name)
            return {"shape": "box", "width": b * 0.1, "height": top - floor_y, "depth": b * 0.1,
                    "position": [x, (top + floor_y) / 2.0, z], "material": black, "role": "pedestal"}

        def mirror(name: str, normal: tuple[float, float], radius: float) -> list[dict[str, Any]]:
            x, z = at(name)
            turn = math.atan2(normal[1], normal[0])
            return [{"shape": "cylinder", "radius": radius, "height": b * 0.04, "position": [x, 0.0, z],
                     "rotation": [0.0, turn, math.pi / 2.0], "material": silver, "role": name},
                    {"shape": "cylinder", "radius": radius * 1.12, "height": b * 0.05, "material": black, "role": "cell",
                     "position": [x - normal[0] * b * 0.04, 0.0, z + normal[1] * b * 0.04], "rotation": [0.0, turn, math.pi / 2.0]},
                    stand(name, -radius)]

        def fans() -> list[dict[str, Any]]:
            (x0, y0), (x1, y1) = (0.3859, 0.3971), (0.6141, 0.3229)      # the ends of the focusing mirror, in the plan
            step = 1.0 / len(self.SPECTRUM)
            solids = []
            for i, color in enumerate(self.SPECTRUM):
                near = (x0 + (x1 - x0) * i * step, y0 + (y1 - y0) * i * step)
                far = (x0 + (x1 - x0) * (i + 1) * step, y0 + (y1 - y0) * (i + 1) * step)
                foot = -0.03 + 0.026 * i
                material = {"color": color, "emissive": color, "emissiveIntensity": 0.7, "opacity": 0.9}
                lift = b * 0.0002 * (i + 1)                             # each colour on its own plane
                solids.append(sheet([(foot, -0.302), near, far, (foot + 0.026, -0.302)], material, "spectrum", lift))  # past the input's edge
                solids.append(sheet([near, far, ((near[0] + far[0]) / 2.0, -0.42)], material, "spectrum", lift))
            return solids

        white = {"color": "#ffffff", "emissive": "#ffffff", "emissiveIntensity": 0.25, "opacity": 0.3}
        fold_x, fold_z = at("fold")
        grating_x, grating_z = at("grating")
        array_x, array_z = at("array")
        head_z = b * 0.63
        children: list[dict[str, Any]] = [
            {"shape": "extruded_polygon", "points": outline, "height": b * 0.04, "position": [0.0, floor_y, 0.0], "material": black, "role": "floor"},
            {"shape": "extruded_polygon", "points": outline, "holes": [room], "height": top_y - floor_y - b * 0.04,
             "position": [0.0, floor_y + b * 0.04, 0.0], "material": anthracite, "role": "wall"},
            *[{"shape": "cylinder", "radius": b * 0.022, "height": b * 0.03, "position": [(x + u) * b / 2.0, top_y + b * 0.015, -(y + v) * b / 2.0], "material": pale, "role": "screw"}
              for (x, y), (u, v) in zip(self.OUTLINE, self.FLOOR)],
            # the slit on the wall, its micrometer on top
            {"shape": "box", "width": b * 0.06, "height": b * 0.4, "depth": b * 0.3, "position": [-b * 0.72, 0.0, 0.0], "material": pale, "role": "slit"},
            {"shape": "box", "width": b * 0.062, "height": b * 0.3, "depth": b * 0.02, "position": [-b * 0.72, 0.0, b * 0.04], "material": black, "role": "jaw"},
            {"shape": "box", "width": b * 0.062, "height": b * 0.3, "depth": b * 0.02, "position": [-b * 0.72, 0.0, -b * 0.04], "material": black, "role": "jaw"},
            {"shape": "cylinder", "radius": b * 0.022, "height": b * 0.2, "position": [-b * 0.72, b * 0.3, 0.0], "material": steel, "role": "micrometer"},
            {"shape": "cylinder", "radius": b * 0.05, "height": b * 0.07, "position": [-b * 0.72, b * 0.42, 0.0], "material": black, "role": "micrometer"},
            # the light
            sheet([(-0.69, 0.0), (-0.4015, 0.0585), (-0.346, 0.397), (-0.574, 0.323), (-0.4988, -0.0388)], white, "input"),
            sheet([(-0.574, 0.323), (-0.346, 0.397), (0.161, -0.3), (-0.121, -0.3)], white, "input"),
            *fans(),
            # the optics at the height of the beam
            {"shape": "box", "width": b * 0.02, "height": b * 0.2, "depth": b * 0.2, "position": [fold_x, 0.0, fold_z],
             "rotation": [0.0, math.radians(135.0), 0.0], "material": silver, "role": "fold"},
            stand("fold", -b * 0.1),
            *mirror("collimator", (0.3093, -0.951), b * 0.13),
            *mirror("focuser", (-0.3093, -0.951), b * 0.13),
            {"shape": "cylinder", "radius": b * 0.155, "height": b * 0.1, "position": [grating_x, -b * 0.37, grating_z + b * 0.01], "material": anthracite, "role": "turret"},
            {"shape": "box", "width": b * 0.3, "height": b * 0.28, "depth": b * 0.02, "position": [grating_x, 0.0, grating_z], "material": silver, "role": "grating"},
            {"shape": "box", "width": b * 0.3, "height": b * 0.32, "depth": b * 0.03, "position": [grating_x, -b * 0.02, grating_z + b * 0.025], "material": black, "role": "cell"},
            stand("grating", -b * 0.14),
            # the array and the cooled head on its flange
            {"shape": "box", "width": b * 0.28, "height": b * 0.14, "depth": b * 0.02, "position": [array_x, 0.0, array_z], "material": {"color": "#2a3a55", "roughness": 0.12, "metalness": 0.3, "clearcoat": 0.8}, "role": "array"},
            {"shape": "box", "width": b * 0.3, "height": b * 0.3, "depth": b * 0.1, "position": [array_x, 0.0, b * 0.49], "material": pale, "role": "flange"},
            {"shape": "box", "width": b * 0.42, "height": b * 0.36, "depth": b * 0.18, "position": [array_x, 0.0, head_z], "material": {"color": "#c3cad2", "metalness": 0.55, "roughness": 0.4}, "role": "camera"},
            {"shape": "box", "width": b * 0.43, "height": b * 0.37, "depth": b * 0.015, "position": [array_x, 0.0, b * 0.58], "material": orange, "role": "stripe"},
            *[{"shape": "box", "width": b * 0.025, "height": b * 0.32, "depth": b * 0.06, "position": [array_x + b * dx, 0.0, b * 0.75], "material": black, "role": "fin"}
              for dx in (-0.17, -0.102, -0.034, 0.034, 0.102, 0.17)],
            # the feet and the plate they stand on
            {"shape": "extruded_polygon", "points": outline, "height": b * 0.06, "position": [0.0, plate_y, 0.0], "material": _MOUNT_BLACK, "role": "plate"},
            *[{"shape": "cylinder", "radius": b * 0.05, "height": b * 0.04, "position": [x * b, -b * 0.48, z * b], "material": black, "role": "foot"}
              for x, z in ((-0.52, -0.36), (0.6, -0.36), (0.6, 0.36), (-0.12, 0.36))],
        ]
        group: dict[str, Any] = {"shape": "group", "children": children, "post_at": [0.0, plate_y, 0.0]}
        if self.base_mount == "none":
            foot = b * 0.14
            tall = BEAM_HEIGHT + plate_y - foot          # each pillar stands on its base, which stands on the table
            for x, z in ((-0.52, -0.36), (0.6, -0.36), (0.6, 0.36), (-0.12, 0.36)):
                children.append({"shape": "cylinder", "radius": b * 0.16, "height": tall, "position": [x * b, -BEAM_HEIGHT + foot + tall / 2.0, z * b], "material": steel, "role": "pillar"})
                children.append({"shape": "cylinder", "radius": b * 0.27, "height": foot, "position": [x * b, -BEAM_HEIGHT + foot / 2.0, z * b], "material": _MOUNT_BLACK, "role": "base"})
        return group


@dataclass
class FiberLaser(Component):
    """Fiber-coupled free-space laser head with pigtail and output probe."""

    component_type = "FiberLaser"
    wavelength: float = 532.0
    head_length: float = 16.0
    head_height: float = 8.2
    head_depth: float = 7.0
    probe_length: float = 8.0
    probe_diameter: float = 1.8
    fiber_diameter: float = 0.55

    def __init__(
        self,
        center=(0, 0),
        angle=0,
        wavelength=532.0,
        head_length=16.0,
        head_height=8.2,
        head_depth=7.0,
        probe_length=8.0,
        probe_diameter=1.8,
        fiber_diameter=0.55,
        **kwargs,
    ):
        """Create a fiber-coupled laser head and output probe.

        Parameters
        ----------
        wavelength : float
            Laser wavelength in nanometers; used for the emitted probe color.
        head_length, head_height, head_depth : float
            Controller/head body dimensions.
        probe_length, probe_diameter : float
            Output probe dimensions.
        fiber_diameter : float
            Cable diameter used for 2D stroke width and 3D tube radius.
        **kwargs
            Supports visual overrides such as ``housing_color``, ``face_color``,
            ``probe_color``, ``cable_color``, ``connector_color``, ``opacity``,
            ``material_preset``, and ``label``.
        """

        self.wavelength = wavelength
        self.head_length = head_length
        self.head_height = head_height
        self.head_depth = head_depth
        self.probe_length = probe_length
        self.probe_diameter = probe_diameter
        self.fiber_diameter = fiber_diameter
        self.material_preset = kwargs.get("material_preset", "aluminum")
        self.housing_color = kwargs.get("housing_color", "#b8bdc3")
        self.face_color = kwargs.get("face_color", "#d5d9de")
        self.probe_color = kwargs.get("probe_color", "#aeb4bc")
        self.cable_color = kwargs.get("cable_color", "#b34e67")
        self.connector_color = kwargs.get("connector_color", "#d9dde2")
        self.color = wavelength_to_hex(wavelength)
        self.opacity = kwargs.get("opacity", 1.0)
        self.label = kwargs.get("label", "Fiber Laser")
        self.transform = Transform.from_2d(*self._parse_center(center).as_2d(), angle)
        self._parent = None
        self._id = ""

    def ports(self) -> dict[str, Port]:
        """Output port at the probe tip (+x)."""

        return {
            "out": Port("out", Vec3(self.head_length * 0.5 + self.probe_length, 0.0, 0.0),
                        orientation_deg=0.0, width=self.probe_diameter * 2.0, kind="free_space"),
        }

    def _body_center_2d(self) -> Vec3:
        """Return the local 2D center of the laser head body."""

        return Vec3(-self.head_length * 0.22, self.head_height * 0.42, 0.0)

    def _probe_center_2d(self) -> Vec3:
        """Return the local 2D center of the output probe."""

        return Vec3(self.head_length * 0.48, -self.head_height * 0.62, 0.0)

    def _body_center_3d(self) -> Vec3:
        """Return the local 3D center of the laser head body."""

        return Vec3(-self.head_length * 0.22, self.head_height / 2.0, 0.0)

    def _probe_center_3d(self) -> Vec3:
        """Return the local 3D center of the output probe."""

        return Vec3(self.head_length * 0.62, self.probe_diameter / 2.0, -self.head_depth * 1.55)

    def _box_connector_length(self) -> float:
        """Return the connector length protruding from the laser head."""

        return self.head_length * 0.14

    def _probe_connector_length(self) -> float:
        """Return the connector length at the probe input."""

        return self.probe_length * 0.18

    def _box_output_tip_2d(self) -> tuple[float, float]:
        """Return the 2D cable exit point on the laser head."""

        body_center = self._body_center_2d()
        body_front_x = body_center.x + self.head_length / 2.0
        return (body_front_x + self.fiber_diameter * 2.0, body_center.y - self.head_height * 0.1)

    def _probe_input_tip_2d(self) -> tuple[float, float]:
        """Return the 2D cable entry point on the probe rear connector."""

        probe_center = self._probe_center_2d()
        rear_center_x = probe_center.x - self.probe_length * 0.34
        return (rear_center_x - self._probe_connector_length() / 2.0, probe_center.y)

    def _box_output_tip_3d(self) -> tuple[float, float, float]:
        """Return the 3D cable exit point on the laser head connector."""

        body_center = self._body_center_3d()
        body_front_x = body_center.x + self.head_length / 2.0
        connector_len = self._box_connector_length()
        return (body_front_x + connector_len, body_center.y - self.head_height * 0.1, 0.0)

    def _probe_input_tip_3d(self) -> tuple[float, float, float]:
        """Return the 3D cable entry point on the probe connector."""

        probe_center = self._probe_center_3d()
        rear_center_x = probe_center.x - self.probe_length * 0.34
        return (rear_center_x - self._probe_connector_length() / 2.0, probe_center.y, probe_center.z)

    def _emission_tip_local(self) -> Vec3:
        """Return the local point where emitted beams should originate."""

        probe_center = self._probe_center_2d()
        return Vec3(probe_center.x + self.probe_length * 0.52, probe_center.y, 0.0)

    def beam_anchor_point(self) -> Vec3:
        """Return the world-space beam start point at the probe tip."""

        return self.world_transform.apply_to_point(self._emission_tip_local())

    def _fiber_curve_2d(self) -> list[tuple[float, float]]:
        """Return a sagging 2D cable path from the head to the probe."""

        body_center = self._body_center_2d()
        probe_center = self._probe_center_2d()
        cable_exit = self._box_output_tip_2d()
        sag_anchor = (self.head_length * 0.06, -self.head_height * 0.98)
        loop_bottom = (self.head_length * 0.34, -self.head_height * 1.94)
        probe_rear = self._probe_input_tip_2d()

        seg1 = _sample_cubic_bezier(
            cable_exit,
            (cable_exit[0] + self.head_length * 0.24, body_center.y - self.head_height * 0.14),
            (self.head_length * 0.22, -self.head_height * 0.56),
            sag_anchor,
        )
        seg2 = _sample_cubic_bezier(
            sag_anchor,
            (-self.head_length * 0.12, -self.head_height * 1.46),
            (self.head_length * 0.04, -self.head_height * 2.14),
            loop_bottom,
        )
        seg3 = _sample_cubic_bezier(
            loop_bottom,
            (self.head_length * 0.7, -self.head_height * 1.54),
            (self.head_length * 0.56, probe_center.y - self.probe_diameter * 0.42),
            probe_rear,
        )
        return seg1[:-1] + seg2[:-1] + seg3

    def _fiber_curve_3d(self) -> list[list[float]]:
        """Return a looped 3D cable path from the head to the probe."""

        start = self._box_output_tip_3d()
        end = self._probe_input_tip_3d()
        segment_a = _sample_cubic_bezier_3d(
            start,
            (start[0] + self.head_length * 0.05, start[1] - self.head_height * 0.12, start[2] - self.head_depth * 0.18),
            (self.head_length * 0.18, self.fiber_diameter * 1.5, -self.head_depth * 0.62),
            (self.head_length * 0.08, self.fiber_diameter * 0.9, -self.head_depth * 1.18),
        )
        segment_b = _sample_cubic_bezier_3d(
            tuple(segment_a[-1]),
            (-self.head_length * 0.05, self.fiber_diameter * 0.7, -self.head_depth * 1.9),
            (self.head_length * 0.22, self.fiber_diameter * 0.52, -self.head_depth * 2.34),
            (self.head_length * 0.48, self.fiber_diameter * 0.56, -self.head_depth * 2.18),
        )
        segment_c = _sample_cubic_bezier_3d(
            tuple(segment_b[-1]),
            (self.head_length * 0.78, self.fiber_diameter * 0.64, -self.head_depth * 1.92),
            (end[0] + self.head_length * 0.08, end[1], end[2] - self.head_depth * 0.18),
            end,
        )
        return segment_a[:-1] + segment_b[:-1] + segment_c

    def geometry_2d(self) -> dict[str, Any]:
        """Return the 2D laser head, pigtail, probe, and emission marker."""

        body_center = self._body_center_2d()
        probe_center = self._probe_center_2d()
        cable_points = self._fiber_curve_2d()
        connector_points = cable_points[: max(len(cable_points) // 5, 6)]
        return {
            "type": "group",
            "children": [
                {"type": "rect", "cx": body_center.x, "cy": body_center.y, "w": self.head_length, "h": self.head_height, "fill": self.housing_color, "stroke": "#676d75", "stroke_width": 0.1, "opacity": 0.98},
                {"type": "rect", "cx": body_center.x + self.head_length * 0.46, "cy": body_center.y, "w": self.head_length * 0.08, "h": self.head_height * 0.92, "fill": self.face_color, "stroke": "#8d959f", "stroke_width": 0.06, "opacity": 0.98},
                {"type": "rect", "cx": body_center.x + self.head_length * 0.54, "cy": body_center.y - self.head_height * 0.1, "w": self.fiber_diameter * 3.2, "h": self.fiber_diameter * 1.8, "fill": self.connector_color, "stroke": "#a4acb4", "stroke_width": 0.05, "opacity": 0.94},
                {"type": "rect", "cx": body_center.x - self.head_length * 0.06, "cy": body_center.y, "w": self.head_length * 0.26, "h": self.head_height * 0.28, "fill": "#2d3740", "stroke": "#1f2933", "stroke_width": 0.05, "opacity": 0.95},
                {"type": "rect", "cx": body_center.x - self.head_length * 0.32, "cy": body_center.y - self.head_height * 0.58, "w": self.head_length * 0.16, "h": self.head_height * 0.1, "fill": "#7b838d", "stroke": "none", "opacity": 0.9},
                {"type": "rect", "cx": body_center.x + self.head_length * 0.36, "cy": body_center.y - self.head_height * 0.58, "w": self.head_length * 0.16, "h": self.head_height * 0.1, "fill": "#7b838d", "stroke": "none", "opacity": 0.9},
                {"type": "line", "x1": body_center.x - self.head_length * 0.12, "y1": body_center.y, "x2": body_center.x + self.head_length * 0.06, "y2": body_center.y, "stroke": "#f3f6f9", "stroke_width": 0.08, "opacity": 0.78},
                {"type": "line", "x1": body_center.x - self.head_length * 0.38, "y1": body_center.y - self.head_height * 0.22, "x2": body_center.x + self.head_length * 0.36, "y2": body_center.y - self.head_height * 0.22, "stroke": "#dce2e8", "stroke_width": 0.05, "opacity": 0.45},
                {"type": "polyline", "points": cable_points, "closed": False, "stroke": "#5b6169", "stroke_width": self.fiber_diameter * 2.2, "opacity": 0.34, "linecap": "round", "linejoin": "round"},
                {"type": "polyline", "points": cable_points, "closed": False, "stroke": self.cable_color, "stroke_width": self.fiber_diameter * 1.45, "opacity": 0.98, "linecap": "round", "linejoin": "round"},
                {"type": "polyline", "points": connector_points, "closed": False, "stroke": self.connector_color, "stroke_width": self.fiber_diameter * 1.8, "opacity": 0.92, "linecap": "round", "linejoin": "round"},
                {"type": "rect", "cx": probe_center.x - self.probe_length * 0.34, "cy": probe_center.y, "w": self.probe_length * 0.18, "h": self.probe_diameter * 1.35, "fill": self.connector_color, "stroke": "#8d959f", "stroke_width": 0.05, "opacity": 0.95},
                {"type": "rect", "cx": probe_center.x, "cy": probe_center.y, "w": self.probe_length * 0.76, "h": self.probe_diameter, "fill": self.probe_color, "stroke": "#68707a", "stroke_width": 0.08, "opacity": 0.98},
                {"type": "rect", "cx": probe_center.x + self.probe_length * 0.42, "cy": probe_center.y, "w": self.probe_length * 0.18, "h": self.probe_diameter * 0.68, "fill": "#6e7680", "stroke": "#555c65", "stroke_width": 0.05, "opacity": 0.95},
                {"type": "line", "x1": probe_center.x + self.probe_length * 0.51, "y1": probe_center.y - self.probe_diameter * 0.18, "x2": probe_center.x + self.probe_length * 0.51, "y2": probe_center.y + self.probe_diameter * 0.18, "stroke": self.color, "stroke_width": 0.08, "opacity": 0.78},
            ],
        }

    def geometry_3d(self) -> dict[str, Any]:
        """Return the 3D laser head, curved fiber, and output probe geometry."""

        body_center = self._body_center_3d()
        probe_center = self._probe_center_3d()
        body_front_x = body_center.x + self.head_length / 2.0
        connector_length = self._box_connector_length()
        connector_y = body_center.y - self.head_height * 0.1
        return {
            "shape": "group",
            "children": [
                {"shape": "box", "width": self.head_length, "height": self.head_height, "depth": self.head_depth, "position": [body_center.x, body_center.y, 0.0], "material": {"color": self.housing_color, "metalness": 0.55, "roughness": 0.34, "preset": self.material_preset}},
                {"shape": "box", "width": self.head_length * 0.08, "height": self.head_height * 0.94, "depth": self.head_depth * 0.86, "position": [body_center.x + self.head_length * 0.46, body_center.y, 0.0], "material": {"color": self.face_color, "metalness": 0.58, "roughness": 0.2, "preset": "steel"}},
                {"shape": "box", "width": self.head_length * 0.26, "height": self.head_height * 0.28, "depth": self.head_depth * 0.08, "position": [body_center.x - self.head_length * 0.06, body_center.y, self.head_depth * 0.47], "material": {"color": "#2d3740", "metalness": 0.15, "roughness": 0.5}},
                {"shape": "box", "width": self.head_length * 0.16, "height": self.head_height * 0.1, "depth": self.head_depth * 0.22, "position": [body_center.x - self.head_length * 0.34, body_center.y - self.head_height * 0.56, 0.0], "material": {"color": "#808892", "metalness": 0.42, "roughness": 0.44, "preset": "steel"}},
                {"shape": "box", "width": self.head_length * 0.16, "height": self.head_height * 0.1, "depth": self.head_depth * 0.22, "position": [body_center.x + self.head_length * 0.36, body_center.y - self.head_height * 0.56, 0.0], "material": {"color": "#808892", "metalness": 0.42, "roughness": 0.44, "preset": "steel"}},
                _cylinder_along_x(self.fiber_diameter * 0.78, connector_length, {"color": self.connector_color, "metalness": 0.65, "roughness": 0.18, "preset": "steel"}, position=[body_front_x + connector_length / 2.0, connector_y, 0.0]),
                {"shape": "tube_path", "points": self._fiber_curve_3d(), "radius": self.fiber_diameter * 0.64, "segments": 72, "radialSegments": 14, "material": {"color": self.cable_color, "metalness": 0.08, "roughness": 0.74}},
                _cylinder_along_x(self.probe_diameter * 0.54, self._probe_connector_length(), {"color": self.connector_color, "metalness": 0.62, "roughness": 0.18, "preset": "steel"}, position=[probe_center.x - self.probe_length * 0.34, probe_center.y, probe_center.z]),
                _cylinder_along_x(self.probe_diameter / 2.0, self.probe_length * 0.76, {"color": self.probe_color, "metalness": 0.46, "roughness": 0.28, "preset": "steel"}, position=[probe_center.x, probe_center.y, probe_center.z]),
                _cylinder_along_x(self.probe_diameter * 0.34, self.probe_length * 0.18, {"color": "#69717b", "metalness": 0.5, "roughness": 0.22, "preset": "steel"}, position=[probe_center.x + self.probe_length * 0.42, probe_center.y, probe_center.z]),
                _cylinder_along_x(self.probe_diameter * 0.12, self.probe_length * 0.04, {"color": self.color, "emissive": self.color, "emissiveIntensity": 1.7, "metalness": 0.0, "roughness": 0.14}, position=[probe_center.x + self.probe_length * 0.52, probe_center.y, probe_center.z]),
            ],
        }

    def physics_metadata(self) -> dict[str, Any]:
        """Return source metadata for fiber-coupled laser propagation tools."""

        return {"domain": "free_space", "component": "fiber_laser", "wavelength": self.wavelength, "source_type": "laser", "delivery": "fiber_coupled"}


class SNSPD(Component):
    """Superconducting nanowire single-photon detector: fibre in, an electrical pulse out.

    Drawn as its cold housing with the nanowire meander on a chip inside; the
    fibre comes in on one side and the readout coax leaves on the other.
    """

    component_type = "SNSPD"
    lies_on_table = True

    def __init__(self, center=(0, 0), angle=0, length=40.0, efficiency=0.9, dark_count_hz=100.0, temperature_k=2.5,
                 **kwargs):
        self.length = float(length)
        self.efficiency = float(efficiency)
        self.dark_count_hz = float(dark_count_hz)
        self.temperature_k = float(temperature_k)
        self.material_preset = kwargs.get("material_preset", "aluminum")
        self.color = kwargs.get("color", "#e2e8f0")
        self.opacity = kwargs.get("opacity", 1.0)
        self.label = kwargs.get("label", "SNSPD")
        self.transform = Transform.from_2d(*self._parse_center(center).as_2d(), angle)
        self._parent = None
        self._id = ""

    def ports(self) -> dict[str, Port]:
        half = self.length / 2.0
        return {
            "in": Port("in", Vec3(-half, 0.0, 0.0), orientation_deg=180.0, width=0.9, kind="fiber"),
            "out": Port("out", Vec3(half, 0.0, 0.0), orientation_deg=0.0, width=0.9, kind="electrical"),
        }

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data.update(length=self.length, efficiency=self.efficiency, dark_count_hz=self.dark_count_hz,
                    temperature_k=self.temperature_k)
        return data

    def _meander(self, s: float) -> list[tuple[float, float]]:
        points, x = [], -0.13 * s
        for index in range(7):
            y0, y1 = (-0.13 * s, 0.13 * s) if index % 2 == 0 else (0.13 * s, -0.13 * s)
            points += [(x, y0), (x, y1)]
            x += 0.26 * s / 6.0
        return points

    def geometry_2d(self) -> dict[str, Any]:
        s, half = self.length / 1.4, self.length / 2.0
        return {"type": "group", "children": [
            {"type": "line", "x1": -half, "y1": 0.0, "x2": -0.35 * s, "y2": 0.0, "stroke": "#f59e0b", "stroke_width": 0.6},
            {"type": "line", "x1": 0.35 * s, "y1": 0.0, "x2": half, "y2": 0.0, "stroke": "#475569", "stroke_width": 0.5},
            {"type": "rect", "cx": 0.0, "cy": 0.0, "w": 0.7 * s, "h": 0.6 * s, "fill": self.color,
             "stroke": "#94a3b8", "stroke_width": 0.2},
            {"type": "rect", "cx": 0.0, "cy": 0.0, "w": 0.36 * s, "h": 0.36 * s, "fill": "#cbd5e1",
             "stroke": "#64748b", "stroke_width": 0.15},
            {"type": "polyline", "points": self._meander(s), "fill": "none", "stroke": "#334155", "stroke_width": 0.25},
        ]}

    def geometry_3d(self) -> dict[str, Any]:
        """Its cryostat can on the table: a cold band, the cold head on top, fibre in low on one side, coax out."""

        s, half = self.length / 1.4, self.length / 2.0
        radius, can = 0.26 * s, 0.85 * s
        flange = {"color": "#64748b", "metalness": 0.5, "roughness": 0.35}
        boot, sma = 2.4, 1.6
        return {"shape": "group", "children": [
            {"shape": "cylinder", "radius": radius * 1.15, "height": 0.8, "position": [0.0, 0.4, 0.0], "material": flange},
            {"shape": "cylinder", "radius": radius, "height": can, "position": [0.0, 0.8 + can / 2.0, 0.0],
             "material": {"color": self.color, "metalness": 0.55, "roughness": 0.3}},
            {"shape": "cylinder", "radius": radius * 1.01, "height": 0.12 * s, "position": [0.0, 0.8 + can * 0.62, 0.0],
             "material": {"color": "#93c5fd", "metalness": 0.2, "roughness": 0.4}},           # the cold stage
            {"shape": "cylinder", "radius": radius * 1.15, "height": 1.0, "position": [0.0, 1.3 + can, 0.0], "material": flange},
            {"shape": "cylinder", "radius": radius * 0.5, "height": 0.14 * s, "position": [0.0, 1.8 + can + 0.07 * s, 0.0],
             "material": {"color": "#334155", "metalness": 0.4, "roughness": 0.4}},          # the cold head
            _cylinder_along_x(0.9, boot, {"color": "#334155", "roughness": 0.6},
                              position=[-radius - boot / 2.0, LEAD_HEIGHT, 0.0]),
            _cylinder_along_x(0.45, half - radius - boot, {"color": "#f59e0b", "roughness": 0.55},
                              position=[-(half + radius + boot) / 2.0, LEAD_HEIGHT, 0.0]),
            _cylinder_along_x(0.75, sma, {"color": "#d4af37", "metalness": 1.0, "roughness": 0.25},
                              position=[radius + sma / 2.0, LEAD_HEIGHT, 0.0]),               # SMA connector
            _cylinder_along_x(0.6, half - radius - sma, {"color": "#475569", "metalness": 0.6, "roughness": 0.3},
                              position=[(half + radius + sma) / 2.0, LEAD_HEIGHT, 0.0]),
        ]}

    def physics_metadata(self) -> dict[str, Any]:
        return {"domain": "free_space", "component": "snspd", "efficiency": self.efficiency,
                "dark_count_hz": self.dark_count_hz, "temperature_k": self.temperature_k}


def _channel_heights(channels: int, pitch: float) -> list[float]:
    """The height of each channel's ports, channel 1 at the top."""

    return [((channels + 1) / 2.0 - index) * pitch for index in range(1, channels + 1)]


def _channel_count(channels: Any) -> int:
    count = int(channels)
    if not 1 <= count <= 8:
        raise ValueError(f"channels must be 1 to 8, not {channels}")
    return count


class PhotonCounter(Component):
    """Fibre-coupled single-photon counting module: one avalanche diode for each channel.

    Each channel takes a fibre on the left and gives a pulse on the right; channel 1 is the top one. The
    module of four channels that a Bell test counts photon pairs with is the default.
    """

    component_type = "PhotonCounter"
    lies_on_table = True
    PITCH = 6.0          # between two channels
    HALF = 14.0          # the ports stand this far either side of the centre

    def __init__(self, center=(0, 0), angle=0, channels=4, **kwargs):
        self.channels = _channel_count(channels)
        self.material_preset = kwargs.get("material_preset", "aluminum")
        self.color = kwargs.get("color", "#e2e8f0")
        self.opacity = kwargs.get("opacity", 1.0)
        self.label = kwargs.get("label", "SPCM")
        self.transform = Transform.from_2d(*self._parse_center(center).as_2d(), angle)
        self._parent = None
        self._id = ""

    def ports(self) -> dict[str, Port]:
        ports = {}
        for index, y in enumerate(_channel_heights(self.channels, self.PITCH), start=1):
            ports[f"fiber{index}"] = Port(f"fiber{index}", Vec3(-self.HALF, y, 0.0), orientation_deg=180.0, width=0.9,
                                          kind="fiber")
            ports[f"pulse{index}"] = Port(f"pulse{index}", Vec3(self.HALF, y, 0.0), orientation_deg=0.0, width=0.9,
                                          kind="electrical")
        return ports

    def symbol_1d(self) -> tuple[str, dict[str, Any]]:
        return "photoncounter", {"count": self.channels}

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data.update(channels=self.channels)
        return data

    def _case(self) -> tuple[float, float]:
        """Half the width and half the height of the case: the symbol's proportions."""

        return 0.6 * self.HALF, (self.channels * 0.5 + 4.0 / 15.0) * self.PITCH

    def geometry_2d(self) -> dict[str, Any]:
        w, h = self._case()
        children = [{"type": "rect", "cx": 0.0, "cy": 0.0, "w": 2 * w, "h": 2 * h, "fill": self.color,
                     "stroke": "#94a3b8", "stroke_width": 0.2}]
        for y in _channel_heights(self.channels, self.PITCH):
            children += [
                {"type": "line", "x1": -self.HALF, "y1": y, "x2": -w, "y2": y, "stroke": "#f59e0b", "stroke_width": 0.6},
                {"type": "line", "x1": w, "y1": y, "x2": self.HALF, "y2": y, "stroke": "#475569", "stroke_width": 0.5},
                {"type": "polyline", "points": [(-4.0, y - 1.8), (-4.0, y + 1.8), (-1.0, y), (-4.0, y - 1.8)],
                 "fill": "#ffffff", "stroke": "#334155", "stroke_width": 0.25},
                {"type": "line", "x1": -1.0, "y1": y - 1.8, "x2": -1.0, "y2": y + 1.8, "stroke": "#334155", "stroke_width": 0.25},
            ]
        return {"type": "group", "children": children}

    def geometry_3d(self) -> dict[str, Any]:
        """Its case on the table, a fibre connector for each channel on one side and a BNC jack on the other."""

        w, h = self._case()
        height = 6.0
        children = [
            {"shape": "box", "width": 2 * w, "height": height, "depth": 2 * h, "position": [0.0, height / 2.0, 0.0],
             "material": {"color": self.color, "preset": "aluminum", "metalness": 0.5, "roughness": 0.35}},
            {"shape": "box", "width": 2 * w * 0.9, "height": 0.3, "depth": 2 * h * 0.9, "position": [0.0, height + 0.15, 0.0],
             "material": {"color": "#94a3b8", "metalness": 0.4, "roughness": 0.4}},
        ]
        for y in _channel_heights(self.channels, self.PITCH):
            children += [
                _cylinder_along_x(0.7, 1.6, {"color": "#334155", "roughness": 0.6}, position=[-w - 0.8, LEAD_HEIGHT, -y]),
                _cylinder_along_x(0.75, 1.6, {"color": "#d4af37", "metalness": 1.0, "roughness": 0.25},
                                  position=[w + 0.8, LEAD_HEIGHT, -y]),
            ]
        return {"shape": "group", "children": children}

    def physics_metadata(self) -> dict[str, Any]:
        return {"domain": "free_space", "component": "photon_counter", "channels": self.channels}


@dataclass
class BalancedDetector(Component):
    """A free-space balanced detector: two matched photodiodes in one housing, wired in series, so the output
    ``out`` carries the difference of the two photocurrents, amplified (the classical noise common to both beams
    cancels). Light enters ``in1`` (+) and ``in2`` (-) side by side on the front face, at local -x; the RF output
    leaves the back. A balanced homodyne detector is this part after a 50:50 splitter.
    """

    component_type = "BalancedDetector"
    box_size: float = 20.0
    # One plan for the 2D art, the 3D solids, the ports and the pic `od balanced` in od-instruments.tex, in units of
    # box_size (the pic: 1 cm): the housing DEPTH along the beams and WIDE across them, the inputs PITCH / 2 off the
    # axis on couplers COUPLER deep, the jack at the back. A schematic, near a 1-inch balanced detector housing.
    DEPTH, WIDE, PITCH, COUPLER = 0.5, 0.8, 0.4, 0.06

    def __init__(self, center=(0, 0), angle=0, box_size=20.0, **kwargs):
        self.box_size = float(box_size)
        _set_common_free_space_fields(self, center, angle, kwargs, color="#16181c", opacity=1.0, material_preset="steel",
                                      label=kwargs.get("label", "Balanced detector"))

    def ports(self) -> dict[str, Port]:
        b = self.box_size
        front = -(self.DEPTH / 2.0 + self.COUPLER) * b
        back = (self.DEPTH / 2.0 + self.COUPLER) * b
        return {
            "in1": Port("in1", Vec3(front, self.PITCH / 2.0 * b, 0.0), orientation_deg=180.0, width=0.15 * b, kind="free_space"),
            "in2": Port("in2", Vec3(front, -self.PITCH / 2.0 * b, 0.0), orientation_deg=180.0, width=0.15 * b, kind="free_space"),
            "out": Port("out", Vec3(back, 0.0, 0.0), orientation_deg=0.0, width=0.1 * b, kind="electrical"),
        }

    def geometry_2d(self) -> dict[str, Any]:
        b, d, w, c = self.box_size, self.DEPTH, self.WIDE, self.COUPLER
        children: list[dict[str, Any]] = [
            {"type": "rect", "cx": 0.0, "cy": 0.0, "w": d * b, "h": w * b, "fill": "#cbd5e1", "stroke": "#64748b", "stroke_width": 0.1},
            {"type": "rect", "cx": (d / 2.0 + c / 2.0) * b, "cy": 0.0, "w": c * b, "h": 0.12 * b, "fill": "#e2e8f0", "stroke": "#64748b", "stroke_width": 0.06},
        ]
        for side in (1.0, -1.0):
            children.append({"type": "rect", "cx": -(d / 2.0 + c / 2.0) * b, "cy": side * self.PITCH / 2.0 * b, "w": c * b,
                             "h": 0.2 * b, "fill": "#e2e8f0", "stroke": "#64748b", "stroke_width": 0.06})
        return {"type": "group", "children": children}

    def geometry_3d(self) -> dict[str, Any]:
        b = self.box_size
        d, w, c, half_pitch = self.DEPTH * b, self.WIDE * b, self.COUPLER * b, self.PITCH / 2.0 * b
        high = 0.7 * b
        bottom = -0.35 * high                               # the inputs sit above the middle of the housing
        silver = {"color": "#c9ced4", "metalness": 0.85, "roughness": 0.22, "preset": "steel"}
        gold = {"color": "#d4af37", "metalness": 0.8, "roughness": 0.35}
        children: list[dict[str, Any]] = [
            {"shape": "box", "role": "housing", "width": d, "height": high, "depth": w,
             "position": [0.0, bottom + high / 2.0, 0.0], "material": {"color": self.color, "metalness": 0.45, "roughness": 0.5}},
            {"shape": "box", "role": "label", "width": d * 0.02, "height": high * 0.12, "depth": w * 0.8,
             "position": [-d / 2.0 - d * 0.01, bottom + high * 0.85, 0.0], "material": {"color": "#e5e7eb", "roughness": 0.6}},
            {"shape": "cylinder", "role": "jack", "radius": 0.05 * b, "height": c, "rotation": [0.0, 0.0, math.pi / 2.0],
             "position": [d / 2.0 + c / 2.0, 0.0, 0.0], "material": silver},
            {"shape": "cylinder", "role": "power", "radius": 0.04 * b, "height": c * 0.8, "rotation": [0.0, 0.0, math.pi / 2.0],
             "position": [d / 2.0 + c * 0.4, bottom + high * 0.75, w * 0.3], "material": silver},
        ]
        for z in (-half_pitch, half_pitch):                 # 2D y = +pitch / 2 is 3D z = -pitch / 2
            children += [
                {**_ring_along_x(0.05 * b, 0.09 * b, c, _MOUNT_BLACK, x=-d / 2.0 - c / 2.0), "position": [-d / 2.0 - c / 2.0, 0.0, z],
                 "role": "coupler"},
                {**_ring_along_x(0.02 * b, 0.035 * b, 0.01 * b, gold, x=-d / 2.0 - 0.005 * b), "position": [-d / 2.0 - 0.005 * b, 0.0, z],
                 "role": "diode"},
            ]
        return {"shape": "group", "children": children, "post_at": [0.0, bottom, 0.0]}

    def physics_metadata(self) -> dict[str, Any]:
        return {"domain": "free_space", "component": "balanced_detector"}
