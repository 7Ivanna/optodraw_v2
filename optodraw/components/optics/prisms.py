"""Prisms free-space optics."""

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
    _optical_metadata,
    _post_boss,
    _right_angle_prism_ports,
    _ring_along_x,
    _set_common_free_space_fields,
    _rim_along_x,
    _transparent_material,
)


def _on_prism_table(points, height: float, material: dict[str, Any], edges: str) -> dict[str, Any]:
    """The glass centred on the beam axis, its facets outlined, on a round prism table under it."""

    xs, ys = [x for x, _ in points], [y for _, y in points]
    cx, cy = (min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0
    reach = max(math.hypot(x - cx, y - cy) for x, y in points)
    plate = height * 0.12
    return {
        "shape": "group",
        "children": [
            {"shape": "extruded_polygon", "role": "glass", "points": list(points), "height": height,
             "position": [0.0, -height / 2.0, 0.0], "material": material, "edges": edges, "edge_opacity": 0.95},
            {"shape": "cylinder", "role": "table", "radius": reach * 0.9, "height": plate,
             "position": [cx, -height / 2.0 - plate / 2.0, -cy], "material": _MOUNT_BLACK},
        ],
    }


@dataclass
class Prism(Component):
    """A dispersive prism with explicit apex/material metadata."""

    component_type = "Prism"
    size: float = 10.0
    apex_angle: float = 60.0
    refractive_index: float = 1.515

    def __init__(self, center=(0, 0), angle=0, size=10.0, apex_angle=60.0, refractive_index=1.515, **kwargs):
        self.size = size
        self.apex_angle = apex_angle
        self.refractive_index = refractive_index
        self.dispersion = kwargs.get("dispersion", None)
        _set_common_free_space_fields(self, center, angle, kwargs, color="#9fd3ff", opacity=0.42, material_preset="glass")

    def ports(self) -> dict[str, Port]:
        """Place beam anchors where the beam crosses the two faces of the 2D art (pic od prism: 0.418 cm apart in
        its 0.62 cm height, which is the prism's height)."""

        height = self.size * math.sin(math.radians(max(min(self.apex_angle, 120.0), 20.0)))
        half = height * 0.209 / 0.62
        width = self.size * 0.5
        return {
            "in": Port("in", Vec3(-half, 0.0, 0.0), orientation_deg=180.0,
                       width=width, kind="free_space"),
            "out": Port("out", Vec3(half, 0.0, 0.0), orientation_deg=0.0,
                        width=width, kind="free_space"),
        }

    def geometry_2d(self) -> dict[str, Any]:
        prism_height = self.size * math.sin(math.radians(max(min(self.apex_angle, 120.0), 20.0)))
        points = [(-self.size / 2.0, -prism_height / 2.0), (-self.size / 2.0, prism_height / 2.0), (self.size / 2.0, 0.0)]
        return {
            "type": "group",
            "children": [
                {"type": "polyline", "points": points, "closed": True, "fill": self.color, "stroke": "#4c8db8", "stroke_width": 0.12, "opacity": self.opacity},
                {"type": "line", "x1": -self.size * 0.32, "y1": 0, "x2": self.size * 0.28, "y2": 0, "stroke": "#ffffff", "stroke_width": 0.1, "opacity": 0.45},
            ],
        }

    def geometry_3d(self) -> dict[str, Any]:
        prism_height = self.size * math.sin(math.radians(max(min(self.apex_angle, 120.0), 20.0)))
        points = [(-self.size / 2.0, -prism_height / 2.0), (-self.size / 2.0, prism_height / 2.0), (self.size / 2.0, 0.0)]
        glass = {**_transparent_material(self.color, self.opacity, self.material_preset), "roughness": 0.03, "transmission": 0.72, "ior": self.refractive_index, "clearcoat": 0.7, "clearcoatRoughness": 0.08}
        return _on_prism_table(points, self.size * 0.75, glass, "#2f6f9f")

    def physics_metadata(self) -> dict[str, Any]:
        return _optical_metadata("prism", apex_angle=self.apex_angle, refractive_index=self.refractive_index, dispersion=self.dispersion)


@dataclass
class RightAnglePrism(Component):
    """90-degree folding prism for periscope and beam-steering teaching diagrams."""

    component_type = "RightAnglePrism"
    leg: float = 10.0
    thickness: float = 8.0
    refractive_index: float = 1.515

    def __init__(self, center=(0, 0), angle=0, leg=10.0, thickness=8.0, refractive_index=1.515, **kwargs):
        self.leg = leg
        self.thickness = thickness
        self.refractive_index = refractive_index
        _set_common_free_space_fields(self, center, angle, kwargs, color="#9fd3ff", opacity=0.44, material_preset="glass")

    def geometry_2d(self) -> dict[str, Any]:
        half = self.leg / 2.0
        points = [(-half, -half), (-half, half), (half, half)]
        return {
            "type": "group",
            "children": [
                {"type": "polyline", "points": points, "closed": True, "fill": self.color, "stroke": "#4c8db8", "stroke_width": 0.12, "opacity": self.opacity},
                {"type": "line", "x1": -half, "y1": 0.0, "x2": 0.0, "y2": half, "stroke": "#ffffff", "stroke_width": 0.1, "opacity": 0.55},
            ],
        }

    def geometry_3d(self) -> dict[str, Any]:
        half = self.leg / 2.0
        glass = {**_transparent_material(self.color, self.opacity, self.material_preset), "roughness": 0.03, "transmission": 0.72, "ior": self.refractive_index, "clearcoat": 0.7, "clearcoatRoughness": 0.08}
        return _on_prism_table([(-half, -half), (-half, half), (half, half)], self.thickness, glass, "#2f6f9f")

    def ports(self) -> dict[str, Port]:
        return _right_angle_prism_ports(self.leg)

    def physics_metadata(self) -> dict[str, Any]:
        return _optical_metadata(
            "right_angle_prism",
            leg=self.leg,
            refractive_index=self.refractive_index,
            fold_angle_deg=90.0,
            deflection_angle_deg=90.0,
        )

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["leg"] = self.leg
        data["thickness"] = self.thickness
        data["refractive_index"] = self.refractive_index
        return data


@dataclass
class Pentaprism(Component):
    """Pentaprism — deviates a beam by a constant 90° regardless of prism tilt (unlike a
    mirror). Two reflecting faces fold the path; entrance and exit faces are perpendicular."""

    component_type = "Pentaprism"
    size: float = 14.0
    refractive_index: float = 1.517

    def __init__(self, center=(0, 0), angle=0, size=14.0, refractive_index=1.517, **kwargs):
        self.size = size
        self.refractive_index = refractive_index
        _set_common_free_space_fields(self, center, angle, kwargs, color="#cfe3f2", opacity=0.5, material_preset="glass", label=kwargs.get("label", "Pentaprism"))

    def _outline(self) -> list[tuple[float, float]]:
        h = self.size / 2.0
        # entrance face on −x, exit face on −y, two reflecting faces on the upper right
        return [(-h, -h), (-h, h), (h * 0.35, h), (h, h * 0.2), (h * 0.2, -h)]

    def optical_interfaces(self):
        """A fixed 90 degree deviation, whatever the beam arrives at.

        That constancy is the reason to buy a pentaprism instead of a mirror: a
        mirror tilted by a degree swings the output by two, a pentaprism holds
        the deviation and only follows its own mount. So it hands the beam on
        along its own exit direction — the same rule a periscope follows, minus
        the change in height."""

        from optodraw.core.raytrace import OpticalInterface

        half = self.size / 2.0
        return [OpticalInterface(
            p1=(0.0, -half), p2=(0.0, half), kind="relay", turn_deg=-90.0, name="pentaprism",
        )]

    def geometry_2d(self) -> dict[str, Any]:
        return {
            "type": "group",
            "children": [
                {"type": "polygon", "points": self._outline(), "fill": self.color, "opacity": self.opacity, "stroke": "#5b8bb0", "stroke_width": 0.14},
                # coated reflecting faces (upper-right) marked
                {"type": "line", "x1": self.size * 0.175, "y1": self.size / 2.0, "x2": self.size / 2.0, "y2": self.size * 0.1, "stroke": "#c9a94a", "stroke_width": 0.22, "opacity": 0.85},
            ],
        }

    def geometry_3d(self) -> dict[str, Any]:
        glass = {**_transparent_material(self.color, self.opacity, self.material_preset), "roughness": 0.03, "transmission": 0.72, "ior": self.refractive_index, "clearcoat": 0.7, "clearcoatRoughness": 0.08}
        return _on_prism_table(self._outline(), self.size * 0.7, glass, "#3f6f94")

    def ports(self) -> dict[str, Port]:
        h = self.size / 2.0
        return {
            "in": Port("in", Vec3(-h, 0.0, 0.0), orientation_deg=180.0, width=self.size * 0.6, kind="free_space"),
            "out": Port("out", Vec3(-h * 0.2, -h, 0.0), orientation_deg=-90.0, width=self.size * 0.6, kind="free_space"),
        }

    def physics_metadata(self) -> dict[str, Any]:
        return _optical_metadata("pentaprism", size=self.size, refractive_index=self.refractive_index, deflection_angle_deg=90.0)

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["size"] = self.size
        data["refractive_index"] = self.refractive_index
        return data


@dataclass
class Retroreflector(Component):
    """Corner-cube retroreflector — returns any incoming beam back parallel to itself,
    independent of orientation. The front face shows the signature 3-sector pattern."""

    component_type = "Retroreflector"
    aperture: float = 12.0

    def __init__(self, center=(0, 0), angle=0, aperture=12.0, **kwargs):
        self.aperture = aperture
        _set_common_free_space_fields(self, center, angle, kwargs, color="#bcd4e6", opacity=0.5, material_preset="glass", label=kwargs.get("label", "Retro"))

    def optical_interfaces(self):
        """The entrance face, which sends light back the way it came.

        A corner cube does not care which way it points: whatever arrives leaves
        antiparallel, on the far side of the apex. That is a different rule from
        a mirror, whose output depends on its angle, so it gets its own kind."""

        from optodraw.core.raytrace import OpticalInterface

        half = self.aperture / 2.0
        return [OpticalInterface(p1=(0.0, -half), p2=(0.0, half), kind="retro", name="corner cube")]

    def geometry_2d(self) -> dict[str, Any]:
        r = self.aperture * 0.5
        hexpts = [(math.cos(math.radians(60 * k + 30)) * r, math.sin(math.radians(60 * k + 30)) * r) for k in range(6)]
        children: list[dict[str, Any]] = [
            {"type": "polygon", "points": hexpts, "fill": self.color, "opacity": self.opacity, "stroke": "#5b6570", "stroke_width": 0.12},
        ]
        for k in (0, 2, 4):  # 3 seams to alternating vertices = corner-cube signature
            children.append({"type": "line", "x1": 0, "y1": 0, "x2": hexpts[k][0], "y2": hexpts[k][1], "stroke": "#7c8894", "stroke_width": 0.1, "opacity": 0.7})
        return {"type": "group", "children": children}

    def geometry_3d(self) -> dict[str, Any]:
        ap = self.aperture
        glass = {**_transparent_material(self.color, self.opacity, "glass"), "transmission": 0.5, "ior": 1.52, "clearcoat": 0.6}
        return {
            "shape": "group",
            "children": [
                # black housing ring the cube sits in
                _ring_along_x(ap * 0.5, ap * 0.6, ap * 0.5, _MOUNT_BLACK, x=ap * 0.2),
                _post_boss(ap * 0.6, ap * 0.4, x=ap * 0.2),
                # glass front face
                _cylinder_along_x(ap * 0.49, ap * 0.12, glass, position=[-ap * 0.02, 0.0, 0.0]),
                # trihedral back = a cone (triangle profile revolved) meeting at the apex
                {"shape": "lathe_profile", "points": [[ap * 0.49, 0.0], [0.001, ap * 0.5]], "segments": 3, "rotation": [0.0, 0.0, -math.pi / 2.0], "position": [ap * 0.06, 0.0, 0.0], "material": glass},
                _rim_along_x(ap * 0.52, ap * 0.03, _MOUNT_ALU, position=[-ap * 0.0506, 0.0, 0.0]),
            ],
        }

    def ports(self) -> dict[str, Port]:
        return {"io": Port("io", Vec3(-self.aperture * 0.05, 0.0, 0.0), orientation_deg=180.0, width=self.aperture * 0.7, kind="free_space")}

    def physics_metadata(self) -> dict[str, Any]:
        return _optical_metadata("retroreflector", aperture=self.aperture)

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["aperture"] = self.aperture
        return data
