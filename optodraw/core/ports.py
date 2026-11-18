"""Port primitives for port-aware routing.

This module provides a lightweight port model inspired by gdsfactory and PHIDL:
components expose named local ports, ports resolve into world space, and routing
operates between ports rather than raw coordinates.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from optodraw.core.transform import Transform, Vec3


@dataclass(frozen=True)
class Port:
    """A named connection point on a component.

    Parameters
    ----------
    name : str
        Unique port name on the owning component.
    center : Vec3
        Local port center.
    orientation_deg : float
        Outward-facing angle in degrees in the XY plane.
    width : float
        Port width. For photonics this is often the waveguide width.
    kind : str
        Port family such as ``optical``, ``electrical``, ``fiber`` or
        ``free_space``.
    layer : str | None
        Optional routing layer/cross-section hint.
    """

    name: str
    center: Vec3 = field(default_factory=Vec3)
    orientation_deg: float = 0.0
    width: float = 0.5
    kind: str = "optical"
    layer: str | None = None

    @property
    def midpoint(self) -> Vec3:
        return self.center

    def normal(self) -> Vec3:
        angle_rad = math.radians(self.orientation_deg)
        return Vec3(math.cos(angle_rad), math.sin(angle_rad), 0.0).normalized()

    def outward(self, distance: float) -> Vec3:
        return self.center + self.normal() * distance

    def transformed(self, transform: Transform) -> Port:
        world_center = transform.apply_to_point(self.center)
        world_normal = transform.rotate_vector(self.normal()).normalized()
        world_orientation = math.degrees(math.atan2(world_normal.y, world_normal.x))
        return Port(
            name=self.name,
            center=world_center,
            orientation_deg=world_orientation,
            width=self.width,
            kind=self.kind,
            layer=self.layer,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "center": self.center.as_tuple(),
            "orientation_deg": self.orientation_deg,
            "width": self.width,
            "kind": self.kind,
            "layer": self.layer,
        }