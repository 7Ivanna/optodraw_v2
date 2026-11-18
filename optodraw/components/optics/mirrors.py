"""Mirrors free-space optics."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from optodraw.core.component import Component
from optodraw.core.ports import Port
from optodraw.core.transform import Vec3

from .beamsplitters import BeamSplitter
from ._shared import (
    _pass_band,
    _kinematic_mount,
    _cylinder_along_x,
    _mirror_face_material,
    _optical_metadata,
    _set_common_free_space_fields,
    _through_ports,
    _rim_along_x,
    _ring_along_x,
    _MOUNT_BLACK,
)

PIEZO_MOUNTS = ("stack", "3axis")
_CERAMIC = {"color": "#e9e6df", "metalness": 0.05, "roughness": 0.7}     # a piezo ceramic: matte off-white


def _piezo_mount(value: Any) -> str | None:
    """None (no piezo), ``"stack"`` or ``"3axis"``; True means a stack."""

    if value is None or value is False:
        return None
    if value is True:
        return "stack"
    if value not in PIEZO_MOUNTS:
        raise ValueError(f"piezo is 'stack' or '3axis', not {value!r}")
    return str(value)


@dataclass
class Mirror(Component):
    """A mirror.

    The reflective (coated) face points toward the component's input / ``-x``
    side, so at the default ``angle=0`` the shiny face looks toward a beam
    arriving from the left. Rotate with ``angle`` to aim the face at the source
    (e.g. ``angle=45`` folds a left→right beam upward with the coating facing the
    beam). The substrate and mount sit behind the face on the ``+x`` side.

    ``piezo="stack"`` (or True) glues the mirror to a piezo stack that moves it along its normal, as on a cavity
    mirror or the phase mirror of an interferometer arm; ``piezo="3axis"`` puts it in a mount whose three piezo
    actuators tip, tilt and push it. Either adds the electrical port ``pzt`` at the back for the drive.
    """

    component_type = "Mirror"
    aperture: float = 10.0
    thickness: float = 1.0
    surface_type: str = "flat"
    # The pic `od mirror` in od-freespace.tex, in cm, a mirror 0.68 tall: the x of its back and of io for each kind.
    # A piezo starts at the back and ends 0.13 behind it, at pzt; the art is fitted to io and pzt, so pzt sits as far
    # behind io as the pic puts it, in units of the aperture.
    PIEZO_REACH = {kind: (back + 0.13 - io) / 0.68 for kind, (back, io) in {
        "flat": (0.13, 0.0), "concave": (0.19, 0.0675), "convex": (0.2, 0.0025),
        "biconcave": (0.27, 0.0675), "biconvex": (0.2375, 0.0025)}.items()}
    PIEZO_LENGTH = 0.13 / 0.68

    def __init__(self, center=(0, 0), angle=0, aperture=10.0, thickness=1.0, surface_type: str | None = None, curvature_depth: float | None = None, focal_length: float | None = None, piezo: str | bool | None = None, **kwargs):
        self.piezo = _piezo_mount(piezo)
        self.aperture = aperture
        self.thickness = thickness
        # Explicit focal length for ray tracing (f > 0 focuses). When unset,
        # curved mirrors derive f = R/2 from the drawn sagitta (curvature_depth).
        self.focal_length = focal_length
        self.surface_type = self._normalize_surface_type(surface_type or kwargs.get("curvature") or kwargs.get("profile") or "flat")
        self.curvature_depth = max(float(curvature_depth if curvature_depth is not None else kwargs.get("sagitta", self.aperture * (0.11 if self.surface_type != "flat" else 0.0))), 0.0)
        _set_common_free_space_fields(self, center, angle, kwargs, color="#f1f8fc", opacity=0.9, material_preset="titanium")

    @staticmethod
    def _normalize_surface_type(surface_type: str) -> str:
        aliases = {
            "plane": "flat",
            "plano": "flat",
            "planar": "flat",
            "spherical_concave": "concave",
            "spherical_convex": "convex",
            "double_concave": "biconcave",
            "di_concave": "biconcave",
            "diconcave": "biconcave",
            "bi_concave": "biconcave",
            "double_convex": "biconvex",
            "di_convex": "biconvex",
            "diconvex": "biconvex",
            "bi_convex": "biconvex",
        }
        normalized = surface_type.lower().replace("-", "_").replace(" ", "_")
        return aliases.get(normalized, normalized)

    def symbol_1d(self) -> tuple[str, dict[str, Any]] | None:
        params = {"kind": self.surface_type} if self.surface_type in {"concave", "convex", "biconcave", "biconvex"} else {}
        if self.piezo:
            params["pzt"] = self.piezo
        return ("mirror", params) if params else None

    def physics_metadata(self) -> dict[str, Any]:
        return _optical_metadata(
            "mirror",
            aperture=self.aperture,
            thickness=self.thickness,
            surface_type=self.surface_type,
            curvature_depth=self.curvature_depth,
            angle=self.transform.angle,
            reflective=True,
        )

    def ports(self) -> dict[str, Port]:
        """A single optical port on the reflective face (the interaction point).

        Both the incoming and reflected beams attach here; the face points toward
        the incoming beam (-x / 180 deg)."""

        ports = {
            "io": Port(
                "io",
                Vec3(-self.thickness * 0.48, 0.0, 0.0),
                orientation_deg=180.0,
                width=self.aperture,
                kind="free_space",
            )
        }
        if self.piezo:
            ports["pzt"] = Port("pzt", Vec3(self._pzt_x(), 0.0, 0.0), orientation_deg=0.0, width=self.aperture * 0.2,
                                kind="electrical")
        return ports

    def _pzt_x(self) -> float:
        reach = self.PIEZO_REACH.get(self.surface_type, self.PIEZO_REACH["flat"])
        return -self.thickness * 0.48 + reach * self.aperture

    def _profile_polyline(self, side: int = 1, mode: str | None = None) -> list[tuple[float, float]]:
        surface_mode = mode or self.surface_type
        face_x = side * self.thickness * 0.48
        depth = self.curvature_depth or self.aperture * 0.26  # drawn fallback only (physics reads curvature_depth directly)
        points: list[tuple[float, float]] = []
        for index in range(17):
            y = -self.aperture / 2.0 + self.aperture * index / 16.0
            normalized_y = abs(2.0 * y / max(self.aperture, 1e-9))
            sag = depth * (1.0 - normalized_y**2)
            if surface_mode in {"convex", "biconvex"}:
                x = face_x + side * sag
            elif surface_mode in {"concave", "biconcave"}:
                x = face_x - side * sag
            else:
                x = face_x
            points.append((x, y))
        return points

    def geometry_2d(self) -> dict[str, Any]:
        """Classic mirror language: the substrate silhouette SHOWS the curvature
        (flat bar / crescent / bulge), the bright stroke is the reflective face,
        and diagonal hatching marks the back — so every mirror type reads at a
        glance (like the legacy drawings did)."""

        w = self.aperture
        front_mode = "flat" if self.surface_type == "flat" else ("convex" if "convex" in self.surface_type else "concave")
        front = self._profile_polyline(-1, front_mode)
        if self.surface_type in {"biconcave", "biconvex"}:
            back = self._profile_polyline(1, front_mode)
        else:
            back = [(self.thickness * 0.48, -w / 2.0), (self.thickness * 0.48, w / 2.0)]
        substrate = [*front, *reversed(back)]
        children: list[dict[str, Any]] = [
            {"type": "polyline", "points": substrate, "closed": True, "fill": "#cfd6dd", "stroke": "#5d6570", "stroke_width": 0.1, "opacity": self.opacity},
            {"type": "polyline", "points": front, "closed": False, "stroke": "#f4fbff", "stroke_width": max(self.thickness * 0.4, 0.28), "opacity": 1.0},
        ]
        if self.surface_type in {"biconcave", "biconvex"}:
            children.append({"type": "polyline", "points": back, "closed": False, "stroke": "#dff3ff", "stroke_width": max(self.thickness * 0.3, 0.2), "opacity": 0.95})
        # back hatching — the universal "mirror" mark
        hx = self.thickness * 0.54
        for i in range(6):
            y = -w / 2.0 + w * (i + 0.5) / 6.0
            children.append({"type": "line", "x1": hx, "y1": y, "x2": hx + w * 0.11, "y2": y + w * 0.09, "stroke": "#4a5058", "stroke_width": 0.12, "opacity": 0.9})
        if self.piezo:
            stack, high = self.PIEZO_LENGTH * w, (1.0 if self.piezo == "3axis" else 0.4 / 0.68) * w
            children.append({"type": "rect", "cx": self._pzt_x() - stack / 2.0, "cy": 0.0, "w": stack, "h": high,
                             "fill": "#e9e6df", "stroke": "#64748b", "stroke_width": 0.08})
        return {"type": "group", "children": children}

    def _mirror_surface_3d(self, side: int = 1, mode: str | None = None, face_x: float | None = None) -> list[dict[str, Any]]:
        surface_mode = mode or self.surface_type
        face_x = side * self.thickness * 0.52 if face_x is None else face_x
        material = _mirror_face_material(self.color, min(max(self.opacity, 0.75), 1.0))
        if surface_mode == "flat":
            return [
                _cylinder_along_x(self.aperture * 0.48, self.thickness * 0.08, material, position=[face_x, 0.0, 0.0]),
                _rim_along_x(self.aperture * 0.48, max(self.aperture * 0.018, 0.06), {"color": "#ffffff", "metalness": 0.7, "roughness": 0.05, "envMapIntensity": 2.0}, position=[face_x + side * self.thickness * 0.055, 0.0, 0.0]),
            ]

        x_scale = max((self.curvature_depth or self.aperture * 0.11) / max(self.aperture, 1e-9), 0.08)
        inset = -side * self.curvature_depth * 0.25 if surface_mode == "concave" else side * self.curvature_depth * 0.25
        return [
            {
                "shape": "sphere",
                "radius": self.aperture * 0.49,
                "scale": [x_scale, 1.0, 1.0],
                "position": [face_x + inset, 0.0, 0.0],
                "material": material,
            },
            _rim_along_x(self.aperture * 0.49, max(self.aperture * 0.025, 0.08), {"color": "#e2ebf1", "metalness": 0.65, "roughness": 0.12, "preset": "steel"}, position=[face_x + side * self.thickness * 0.035, 0.0, 0.0]),
        ]

    def geometry_3d(self) -> dict[str, Any]:
        front_mode = "flat" if self.surface_type == "flat" else ("convex" if "convex" in self.surface_type else "concave")
        ap, th = self.aperture, self.thickness
        # A round mirror in a kinematic mount: the reflective face on the input (-x) side at the io port, the
        # substrate behind it in the bore of the front plate, then the L back plate and its two adjusters.
        face, side = -th * 0.52, ap * 1.4
        depth = side / 7.0
        # a stack holds the mirror out of the mount on a piezo ring; a 3-axis mount has piezo actuators for knobs
        stack = self.PIEZO_LENGTH * ap if self.piezo == "stack" else 0.0
        mount = _kinematic_mount(face + depth + stack if stack else face + ap * 0.02, side, ap * 0.5)
        if self.piezo == "3axis":
            knobs = [s for s in mount if s.get("role") == "knob"]
            pivot = next(s for s in mount if s.get("role") == "pivot")
            rear = knobs[0]["position"][0] - side * 0.113          # the back face of the L plate (_kinematic_mount)
            mount = [s for s in mount if s.get("role") not in ("knob", "screw")]
            for y, z in [k["position"][1:] for k in knobs] + [pivot["position"][1:]]:
                mount += [{**_cylinder_along_x(side * 0.06, side * 0.2, _CERAMIC, position=[rear + side * 0.1, y, z]), "role": "piezo"},
                          {**_cylinder_along_x(side * 0.065, side * 0.05, _MOUNT_BLACK, position=[rear + side * 0.225, y, z]), "role": "piezo cap"}]
        children = [
            _cylinder_along_x(ap * 0.5, depth, {"color": "#dbe4ec", "metalness": 0.25, "roughness": 0.25, "preset": "glass"}, position=[face + depth / 2.0, 0.0, 0.0]),
            *self._mirror_surface_3d(-1, front_mode),
            *mount,
        ]
        if stack:
            children.append({**_ring_along_x(ap * 0.18, ap * 0.4, stack, _CERAMIC, x=face + depth + stack / 2.0), "role": "piezo"})
        if self.surface_type in {"biconcave", "biconvex"}:
            children.extend(self._mirror_surface_3d(1, front_mode, face_x=face + depth))
        return {
            "shape": "group",
            "children": children,
            "surface_profile": {"type": self.surface_type, "curvature_depth": self.curvature_depth},
        }


class ConcaveMirror(Mirror):
    """Spherical concave mirror visual."""

    component_type = "ConcaveMirror"

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("surface_type", "concave")
        super().__init__(*args, **kwargs)


class ConvexMirror(Mirror):
    """Spherical convex mirror visual."""

    component_type = "ConvexMirror"

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("surface_type", "convex")
        super().__init__(*args, **kwargs)


class BiconcaveMirror(Mirror):
    """Double-sided concave mirror visual for curved reference optics."""

    component_type = "BiconcaveMirror"

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("surface_type", "biconcave")
        super().__init__(*args, **kwargs)


class BiconvexMirror(Mirror):
    """Double-sided convex mirror visual for curved reference optics."""

    component_type = "BiconvexMirror"

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("surface_type", "biconvex")
        super().__init__(*args, **kwargs)


FLIP_STATES = ("up", "down", "both")


class FlipMirror(Mirror):
    """A mirror on a flip mount: in the beam or out of it.

    ``state="up"`` stands it in the beam: light folds at ``io``. ``state="down"`` takes it out: light runs straight
    on through ``pass``. ``state="both"`` is a figure of the two routes at once: the mirror is drawn up, and a beam
    may take either port. The 2D view paints the mirror where it is and a dashed outline where it is not,
    ``out_offset`` along its face; a negative ``out_offset`` takes the other side.
    """

    component_type = "FlipMirror"

    def symbol_2d(self) -> tuple[str, dict[str, Any]]:
        return "flipmirror", {"view": "top"}                # the 2D view draws the outline at out_offset itself

    def __init__(self, center=(0, 0), angle=0, aperture=10.0, thickness=1.0, state="up", out_offset=None, **kwargs):
        if state not in FLIP_STATES:
            raise ValueError(f"A flip mirror is up, down or both, not {state!r}")
        self.state = state
        self.out_offset = 1.25 * aperture if out_offset is None else float(out_offset)
        super().__init__(center, angle, aperture, thickness, **kwargs)

    @property
    def out_of_beam(self) -> bool:
        return self.state == "down"

    def ports(self) -> dict[str, Port]:
        """The mirror's ``io``, and ``pass``: the spot a beam crosses when the mirror is out of its way."""

        through = Port("pass", Vec3(0.0, 0.0, 0.0), orientation_deg=0.0, width=self.aperture, kind="free_space")
        return {**super().ports(), "pass": through}

    def beam_point(self, port: str) -> Vec3:
        """The straight route crosses where the fold does: a bench lined up on ``io`` stays straight with the mirror down."""

        return super().ports()["io"].center

    def physics_metadata(self) -> dict[str, Any]:
        return {**super().physics_metadata(), "reflective": not self.out_of_beam, "state": self.state}

    def art_place(self) -> tuple[float, float]:
        """Along the face: where the painted mirror sits, and where its dashed outline sits."""

        return (self.out_offset, 0.0) if self.out_of_beam else (0.0, self.out_offset)

    def geometry_3d(self) -> dict[str, Any]:
        geometry = super().geometry_3d()
        if self.out_of_beam:                                # down: the mirror and its mount drop below the beam
            geometry["position"] = [0.0, -1.2 * self.aperture, 0.0]
        return geometry

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data.update(state=self.state, out_offset=self.out_offset)
        return data


class DichroicMirror(BeamSplitter):
    """A dichroic mirror: the coated plate of ``BeamSplitter(dichroic=True)``, which reflects one band and
    passes the other. ``pass_band`` says which side of ``cutoff_wavelength`` passes."""

    component_type = "DichroicMirror"

    def __init__(self, center=(0, 0), angle=0, aperture=10.0, thickness=1.0, cutoff_wavelength=None, pass_band="longpass", **kwargs):
        # "longpass": wavelengths above the cutoff transmit; "shortpass": below.
        self.pass_band = _pass_band(pass_band)
        self.reflects = kwargs.pop("reflects", None)
        self.transmits = kwargs.pop("transmits", None)
        kwargs.pop("back_color", None)
        kwargs.pop("dichroic", None)
        super().__init__(center, angle, aperture=aperture, dichroic=True, thickness=thickness,
                         cutoff_wavelength=cutoff_wavelength, **kwargs)

    def physics_metadata(self) -> dict[str, Any]:
        return _optical_metadata("dichroic_mirror", cutoff_wavelength=self.cutoff_wavelength, reflects=self.reflects, transmits=self.transmits)


@dataclass
class GalvoMirror(Component):
    """Scanning galvanometer mirror with scan-range metadata."""

    component_type = "GalvoMirror"
    aperture: float = 10.0
    mirror_width: float = 4.5
    scan_range_deg: float = 20.0
    drive_frequency_khz: float = 1.0

    def symbol_1d(self):
        return "galvocompact", {}

    def symbol_2d(self):
        return "galvo", {}

    def __init__(self, center=(0, 0), angle=0, aperture=10.0, mirror_width=4.5, scan_range_deg=20.0, drive_frequency_khz=1.0, **kwargs):
        self.aperture = aperture
        self.mirror_width = mirror_width
        self.scan_range_deg = scan_range_deg
        self.drive_frequency_khz = drive_frequency_khz
        _set_common_free_space_fields(self, center, angle, kwargs, color="#d7dde5", opacity=1.0, material_preset="steel", label=kwargs.get("label", "Galvo"))

    def geometry_2d(self) -> dict[str, Any]:
        arc_radius = self.aperture * 0.58
        return {
            "type": "group",
            "children": [
                {"type": "rect", "cx": 0.0, "cy": 0.0, "w": self.mirror_width, "h": self.aperture, "fill": "#d7dde5", "stroke": "#4b5563", "stroke_width": 0.08, "opacity": 0.96},
                {"type": "rect", "cx": -self.mirror_width * 0.82, "cy": 0.0, "w": self.mirror_width * 0.55, "h": self.aperture * 0.52, "fill": "#374151", "stroke": "#1f2937", "stroke_width": 0.06},
                {"type": "line", "x1": self.mirror_width * 0.65, "y1": 0.0, "x2": self.mirror_width * 0.65 + arc_radius, "y2": 0.0, "stroke": "#93c5fd", "stroke_width": 0.12, "opacity": 0.6},
                {"type": "path", "d": f"M {self.mirror_width * 0.65} {-arc_radius} A {arc_radius} {arc_radius} 0 0 1 {self.mirror_width * 0.65} {arc_radius}", "fill": "none", "stroke": "#60a5fa", "stroke_width": 0.07, "opacity": 0.8},
            ],
        }

    def geometry_3d(self) -> dict[str, Any]:
        mw, a = self.mirror_width, self.aperture
        return {
            "shape": "group",
            "children": [
                # scanning mirror face on the galvo shaft
                {"shape": "box", "width": mw, "height": a, "depth": a * 0.16, "material": _mirror_face_material(self.color, self.opacity)},
                # short shaft to the motor
                _cylinder_along_x(a * 0.12, mw * 0.7, {"color": "#374151", "metalness": 0.45, "roughness": 0.32, "preset": "steel"}, position=[-mw * 0.85, 0.0, 0.0]),
                # galvanometer motor can
                _cylinder_along_x(a * 0.3, mw * 1.6, {"color": "#2a2f37", "metalness": 0.58, "roughness": 0.3, "preset": "steel"}, position=[-mw * 2.0, 0.0, 0.0]),
                # rear connector + mounting base
                _cylinder_along_x(a * 0.1, mw * 0.3, {"color": "#b8a24a", "metalness": 0.7, "roughness": 0.3, "preset": "brass"}, position=[-mw * 2.95, 0.0, 0.0]),
                # mounting base under the motor, below the mirror's lowest edge, where the post holds it
                {"shape": "box", "width": mw * 1.7, "height": a * 0.34, "depth": a * 0.7, "position": [-mw * 1.9, -a * 0.45, 0.0], "material": {"color": "#3f3f46", "metalness": 0.5, "roughness": 0.4, "preset": "steel"}},
            ],
        }

    def ports(self) -> dict[str, Port]:
        return _through_ports(self.mirror_width, self.aperture)

    def physics_metadata(self) -> dict[str, Any]:
        return _optical_metadata(
            "galvo_mirror",
            scan_range_deg=self.scan_range_deg,
            drive_frequency_khz=self.drive_frequency_khz,
            aperture=self.aperture,
        )

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["aperture"] = self.aperture
        data["mirror_width"] = self.mirror_width
        data["scan_range_deg"] = self.scan_range_deg
        data["drive_frequency_khz"] = self.drive_frequency_khz
        return data


@dataclass
class RoofMirror(Component):
    """A hollow roof mirror: two flat mirrors at 90 degrees, their join (the roof) upright. Light that enters at
    ``in`` meets one face, crosses to the other and leaves at ``out``, parallel to the way it came and beside it, so
    the two beams never lie on each other. On a translation stage (the default mount) it is an optical delay line:
    moving it by d along the beam lengthens the path by 2 d.
    """

    component_type = "RoofMirror"
    aperture: float = 12.0
    # One plan for the 2D art, the 3D solids, the ports and the pic `od roof` in od-freespace.tex, in units of the
    # aperture (the pic: 0.68 cm): the opening at x = -FRONT, the roof at x = +FRONT, the faces at 45 degrees, the
    # beams OFFSET above and below the axis, the plates PLATE thick.
    FRONT = 0.25
    OFFSET = 0.25
    PLATE = 0.05

    def __init__(self, center=(0, 0), angle=0, aperture=12.0, **kwargs):
        self.aperture = float(aperture)
        kwargs.setdefault("base_mount", "stage")
        _set_common_free_space_fields(self, center, angle, kwargs, color="#f1f8fc", opacity=1.0, material_preset="titanium",
                                      label=kwargs.get("label", "Delay line"))

    def light_path(self, a: str, b: str) -> list[tuple[float, float]]:
        """The local points from port ``a`` to port ``b``: the first face, straight across, the second face."""

        f, d = self.FRONT * self.aperture, self.OFFSET * self.aperture
        hit = f - d                                     # each face is the line |y| = FRONT - x
        path = [(-f, d), (hit, d), (hit, -d), (-f, -d)]
        return path if (a, b) == ("in", "out") else path[::-1]

    def ports(self) -> dict[str, Port]:
        f, d, a = self.FRONT * self.aperture, self.OFFSET * self.aperture, self.aperture
        return {"in": Port("in", Vec3(-f, d, 0.0), orientation_deg=180.0, width=a * 0.3, kind="free_space"),
                "out": Port("out", Vec3(-f, -d, 0.0), orientation_deg=180.0, width=a * 0.3, kind="free_space")}

    def geometry_2d(self) -> dict[str, Any]:
        a, f, t = self.aperture, self.FRONT * self.aperture, self.PLATE * self.aperture
        lean = t / 2 ** 0.5                                 # the plate's thickness, along x and along y
        children: list[dict[str, Any]] = []
        for side in (1.0, -1.0):
            face = [(-f, side * a / 2.0), (f, 0.0)]
            back = [(x + lean, y + side * lean) for x, y in reversed(face)]
            children.append({"type": "polygon", "points": [*face, *back], "fill": "#cfd6dd", "stroke": "#5d6570",
                             "stroke_width": 0.1})
        return {"type": "group", "children": children}

    def geometry_3d(self) -> dict[str, Any]:
        a, f, t = self.aperture, self.FRONT * self.aperture, self.PLATE * self.aperture
        high = 0.7 * a
        lean = t / 2 ** 0.5
        children: list[dict[str, Any]] = []
        for side in (1.0, -1.0):                            # 2D y = side; 3D z = -y
            cx, cy = 0.0, side * a / 4.0                    # the middle of the face
            children.append({"shape": "box", "role": "mirror", "width": t, "height": high, "depth": a / 2 ** 0.5,
                             "position": [cx + lean / 2.0, 0.0, -(cy + side * lean / 2.0)],
                             "rotation": [0.0, side * math.pi / 4.0, 0.0],
                             "material": _mirror_face_material(self.color, self.opacity)})
        # a black block with a V cut out of it holds the two plates; a boss under its back carries the mount
        back, apex = 0.42 * a, f + 2.0 * lean
        notch = [(-f + lean, a / 2.0 + lean), (back, a / 2.0 + lean), (back, -a / 2.0 - lean),
                 (-f + lean, -a / 2.0 - lean), (apex, 0.0)]
        boss = 0.1 * a
        children += [
            {"shape": "extruded_polygon", "role": "holder", "points": notch, "height": high,
             "position": [0.0, -high / 2.0, 0.0], "material": _MOUNT_BLACK},
            {"shape": "box", "role": "boss", "width": back - apex, "height": boss, "depth": 0.4 * a,
             "position": [(back + apex) / 2.0, -high / 2.0 - boss / 2.0, 0.0], "material": _MOUNT_BLACK},
        ]
        return {"shape": "group", "children": children, "post_at": [(back + apex) / 2.0, -high / 2.0 - boss, 0.0]}

    def physics_metadata(self) -> dict[str, Any]:
        return _optical_metadata("roof_mirror", aperture=self.aperture)
