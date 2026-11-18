"""Optical cavities on the bench: the triangular ring mode cleaner."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from optodraw.core.component import Component
from optodraw.core.ports import Port
from optodraw.core.transform import Vec3

from ._shared import (
    _MOUNT_ALU,
    _MOUNT_BLACK,
    _cylinder_along_x,
    _mirror_face_material,
    _optical_metadata,
    _set_common_free_space_fields,
    _transparent_material,
)
from .mirrors import _CERAMIC


def _unit(x: float, y: float) -> tuple[float, float]:
    n = math.hypot(x, y)
    return x / n, y / n


@dataclass
class ModeCleaner(Component):
    """A triangular ring mode cleaner: two flat couplers on the beam line and a curved mirror at the apex, on one
    spacer. Light runs along local +x.

    The input passes through the first coupler (M1) and runs along the base to the second (M2); the ring closes over
    the apex mirror (M3). Locked on resonance, the cavity passes its TEM00 mode out of M2, on the input line
    (``out``), and the light it does not pass leaves M1 as ``refl``, along the leg from M3 continued past M1: that
    beam carries the error signal of a Pound-Drever-Hall lock. A ring sends nothing back to the laser.
    ``transmission`` is the percent of the input power the locked cavity passes. ``piezo=True`` puts a piezo stack
    on M3 to hold the length, with the electrical port ``pzt``.
    """

    component_type = "ModeCleaner"
    size: float = 20.0
    transmission: float = 90.0
    piezo: bool = False
    # One plan for the 2D art, the 3D solids, the ports and the pic `od modecleaner` in od-freespace.tex, in units of
    # ``size`` (the pic is 1.2 wide): the mirrors' reflecting points, the spacer outline and where the beams cross its
    # edge. A schematic: a real mode cleaner's legs are long beside its base.
    M1, M2, M3 = (-0.3, 0.0), (0.3, 0.0), (0.0, 0.6)
    OUTLINE = ((-0.5, -0.15), (0.5, -0.15), (0.5, 0.1), (0.12, 0.65), (-0.12, 0.65), (-0.5, 0.1))
    MIRROR = 0.16                       # the mirrors' diameter
    PZT_TOP = 0.82 / 1.2                # the back of the piezo on M3, where its drive enters (the pic: 0.82)

    def __init__(self, center=(0, 0), angle=0, size=20.0, transmission=90.0, piezo=False, **kwargs):
        self.size = float(size)
        self.transmission = float(transmission)
        self.piezo = bool(piezo)
        _set_common_free_space_fields(self, center, angle, kwargs, color="#c6cbd1", opacity=1.0, material_preset="steel",
                                      label=kwargs.get("label", "Mode cleaner"))

    def symbol_1d(self) -> tuple[str, dict[str, Any]] | None:
        return ("modecleaner", {"pzt": "stack"}) if self.piezo else None

    @classmethod
    def refl_direction(cls) -> tuple[float, float]:
        """The reflected beam leaves M1 along the leg from M3, continued: the law of reflection at M1 gives it."""

        return _unit(cls.M1[0] - cls.M3[0], cls.M1[1] - cls.M3[1])

    @classmethod
    def normals(cls) -> dict[str, tuple[float, float]]:
        """Each mirror's normal, into the ring: it halves the angle between the two legs that meet there."""

        out = {}
        for name, here, before, after in (("M1", cls.M1, cls.M3, cls.M2), ("M2", cls.M2, cls.M1, cls.M3),
                                          ("M3", cls.M3, cls.M2, cls.M1)):
            a = _unit(before[0] - here[0], before[1] - here[1])
            b = _unit(after[0] - here[0], after[1] - here[1])
            out[name] = _unit(a[0] + b[0], a[1] + b[1])
        return out

    def _local_points(self) -> dict[str, tuple[float, float]]:
        s = self.size
        dx, dy = self.refl_direction()
        bottom = self.OUTLINE[0][1]
        t = (bottom - self.M1[1]) / dy                     # where the reflected beam crosses the bottom edge
        return {"in": (-0.5 * s, 0.0), "out": (0.5 * s, 0.0), "refl": ((self.M1[0] + t * dx) * s, bottom * s),
                "M1": (self.M1[0] * s, 0.0), "M2": (self.M2[0] * s, 0.0), "M3": (self.M3[0] * s, self.M3[1] * s)}

    def ports(self) -> dict[str, Port]:
        p = self._local_points()
        dx, dy = self.refl_direction()
        ports = {
            "in": Port("in", Vec3(*p["in"], 0.0), orientation_deg=180.0, width=self.MIRROR * self.size, kind="free_space"),
            "out": Port("out", Vec3(*p["out"], 0.0), orientation_deg=0.0, width=self.MIRROR * self.size, kind="free_space"),
            "refl": Port("refl", Vec3(*p["refl"], 0.0), orientation_deg=math.degrees(math.atan2(dy, dx)) % 360.0,
                         width=self.MIRROR * self.size, kind="free_space"),
        }
        if self.piezo:
            ports["pzt"] = Port("pzt", Vec3(0.0, self.PZT_TOP * self.size, 0.0), orientation_deg=90.0,
                                width=0.05 * self.size, kind="electrical")
        return ports

    def light_path(self, a: str, b: str) -> list[tuple[float, float]]:
        """The local points the light runs through from port ``a`` to port ``b``."""

        p = self._local_points()
        routes = {("in", "out"): ["in", "M1", "M2", "out"], ("in", "refl"): ["in", "M1", "refl"]}
        names = routes.get((a, b)) or list(reversed(routes[(b, a)]))
        return [p[name] for name in names]

    def geometry_2d(self) -> dict[str, Any]:
        s, p = self.size, self._local_points()
        half = self.MIRROR * s / 2.0
        children: list[dict[str, Any]] = [
            {"type": "polygon", "points": [(x * s, y * s) for x, y in self.OUTLINE], "fill": "#e2e8f0",
             "stroke": "#94a3b8", "stroke_width": 0.1},
            {"type": "polyline", "points": [p["M1"], p["M2"], p["M3"]], "closed": True, "stroke": "#ef4444",
             "stroke_width": 0.12, "fill": "none"},
        ]
        for name, (nx, ny) in self.normals().items():
            x, y = p[name]
            children.append({"type": "line", "x1": x - ny * half, "y1": y + nx * half, "x2": x + ny * half,
                             "y2": y - nx * half, "stroke": "#475569", "stroke_width": 0.4})
        return {"type": "group", "children": children}

    def geometry_3d(self) -> dict[str, Any]:
        s, p = self.size, self._local_points()
        radius, thick = self.MIRROR * s / 2.0, 0.04 * s
        holder, block = 0.05 * s, 0.12 * s
        floor = -1.1 * radius                                  # the spacer's top: the holders stand on it
        glass = {**_transparent_material("#dbe4ec", 0.6, "glass"), "clearcoat": 0.6}
        children: list[dict[str, Any]] = [
            {"shape": "extruded_polygon", "role": "spacer", "points": [(x * s, y * s) for x, y in self.OUTLINE],
             "height": block, "position": [0.0, floor - block, 0.0], "material": _MOUNT_ALU},
        ]
        for name, (nx, ny) in self.normals().items():
            x, y = p[name]
            turn = math.atan2(ny, nx)                           # the 2D normal is (cos, -sin) in x and z
            nz = -ny

            def behind(depth: float) -> list[float]:
                return [x - nx * depth, 0.0, -y - nz * depth]

            face = _mirror_face_material() if name == "M3" else glass
            children += [
                {**_cylinder_along_x(radius, thick, face), "rotation": [0.0, turn, math.pi / 2.0],
                 "position": behind(thick / 2.0), "role": f"mirror {name}"},
                {"shape": "box", "role": "holder", "width": holder, "height": 2.0 * 1.1 * radius,
                 "depth": 2.6 * radius, "rotation": [0.0, turn, 0.0], "position": behind(thick + holder / 2.0),
                 "material": _MOUNT_BLACK},
            ]
            if name == "M3" and self.piezo:
                length = 0.06 * s
                children.append({**_cylinder_along_x(radius * 0.8, length, _CERAMIC), "rotation": [0.0, turn, math.pi / 2.0],
                                 "position": behind(thick + holder + length / 2.0), "role": "piezo"})
        light = {"color": "#ef4444", "opacity": 0.55, "transparent": True}
        legs = (("in", "M1"), ("M1", "M2"), ("M2", "M3"), ("M3", "M1"), ("M2", "out"))   # one tube a leg: a path bends
        children += [{"shape": "tube_path", "role": "light", "radius": 0.006 * s, "material": light,
                      "points": [[p[a][0], 0.0, -p[a][1]], [p[b][0], 0.0, -p[b][1]]]} for a, b in legs]
        z_mid = -0.25 * s
        return {"shape": "group", "children": children, "post_at": [0.0, floor - block, z_mid]}

    def physics_metadata(self) -> dict[str, Any]:
        return _optical_metadata("mode_cleaner", transmission=self.transmission, piezo=self.piezo)


__all__ = ["ModeCleaner"]
