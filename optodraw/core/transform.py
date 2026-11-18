"""Transform: position + rotation for components in 2D and 3D.

The optional ``optodraw._core`` Rust extension can accelerate some geometry
paths, but this module is pure Python and works without it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np


@dataclass
class Vec3:
    """A lightweight 3-component vector."""

    x: float = 0.0
    y: float = 0.0
    z: float = 0.0

    # -- convenience constructors ------------------------------------------
    @classmethod
    def from_2d(cls, x: float, y: float) -> Vec3:
        return cls(x, y, 0.0)

    def as_tuple(self) -> tuple[float, float, float]:
        return (self.x, self.y, self.z)

    def as_2d(self) -> tuple[float, float]:
        return (self.x, self.y)

    # -- math --------------------------------------------------------------
    def __add__(self, other: Vec3) -> Vec3:
        return Vec3(self.x + other.x, self.y + other.y, self.z + other.z)

    def __sub__(self, other: Vec3) -> Vec3:
        return Vec3(self.x - other.x, self.y - other.y, self.z - other.z)

    def __mul__(self, scalar: float) -> Vec3:
        return Vec3(self.x * scalar, self.y * scalar, self.z * scalar)

    def __rmul__(self, scalar: float) -> Vec3:
        return self.__mul__(scalar)

    def length(self) -> float:
        return math.sqrt(self.x**2 + self.y**2 + self.z**2)

    def normalized(self) -> Vec3:
        L = self.length()
        if L < 1e-15:
            return Vec3(self.x, self.y, self.z)
        return Vec3(self.x / L, self.y / L, self.z / L)

    def dot(self, other: Vec3) -> float:
        return self.x * other.x + self.y * other.y + self.z * other.z

    def cross(self, other: Vec3) -> Vec3:
        return Vec3(
            self.y * other.z - self.z * other.y,
            self.z * other.x - self.x * other.z,
            self.x * other.y - self.y * other.x,
        )


def as_vec3(point) -> "Vec3":
    """Coerce a 2D or 3D point into a :class:`Vec3`.

    Four modules carried their own copy of this, three identical and one that
    rejected junk input instead of failing later with a confusing IndexError.
    The strict one is the one worth keeping.
    """

    if isinstance(point, Vec3):
        return point
    if isinstance(point, (tuple, list)):
        if len(point) == 2:
            return Vec3(point[0], point[1], 0.0)
        if len(point) >= 3:
            return Vec3(point[0], point[1], point[2])
    raise TypeError(f"Unsupported point type: {type(point)}")


@dataclass
class Transform:
    """Describes position and rotation of a component.

    All components live in a scene graph. A component's *world* transform is
    computed by composing all parent transforms down to the root.
    """

    position: Vec3 = field(default_factory=Vec3)
    rotation_deg: Vec3 = field(default_factory=Vec3)  # Euler angles (x, y, z) in degrees

    # -- convenience constructors ------------------------------------------
    @classmethod
    def from_2d(cls, x: float = 0, y: float = 0, angle: float = 0) -> Transform:
        """Create a transform from 2D parameters (legacy compatibility)."""
        return cls(position=Vec3(x, y, 0), rotation_deg=Vec3(0, 0, angle))

    @property
    def center(self) -> tuple[float, float]:
        """Legacy 2D center."""
        return (self.position.x, self.position.y)

    @property
    def angle(self) -> float:
        """Legacy 2D angle (rotation about Z)."""
        return self.rotation_deg.z

    # -- matrix computation ------------------------------------------------
    def to_matrix_4x4(self) -> np.ndarray:
        """Return a 4×4 homogeneous transform matrix (row-major)."""
        rx = math.radians(self.rotation_deg.x)
        ry = math.radians(self.rotation_deg.y)
        rz = math.radians(self.rotation_deg.z)

        # Rotation order: Rz * Ry * Rx
        cx, sx = math.cos(rx), math.sin(rx)
        cy, sy = math.cos(ry), math.sin(ry)
        cz, sz = math.cos(rz), math.sin(rz)

        m = np.eye(4)
        m[0, 0] = cz * cy
        m[0, 1] = cz * sy * sx - sz * cx
        m[0, 2] = cz * sy * cx + sz * sx
        m[1, 0] = sz * cy
        m[1, 1] = sz * sy * sx + cz * cx
        m[1, 2] = sz * sy * cx - cz * sx
        m[2, 0] = -sy
        m[2, 1] = cy * sx
        m[2, 2] = cy * cx

        m[0, 3] = self.position.x
        m[1, 3] = self.position.y
        m[2, 3] = self.position.z
        return m

    def apply_to_point(self, point: Vec3) -> Vec3:
        """Apply this transform to a point in local coordinates."""
        vec = np.array([point.x, point.y, point.z, 1.0])
        out = self.to_matrix_4x4() @ vec
        return Vec3(out[0], out[1], out[2])

    def rotate_vector(self, vector: Vec3) -> Vec3:
        """Apply only the rotational part of this transform to a vector."""
        rot = self.to_matrix_4x4()[:3, :3]
        out = rot @ np.array([vector.x, vector.y, vector.z])
        return Vec3(out[0], out[1], out[2])

    def compose(self, child: Transform) -> Transform:
        """Compute the world transform: self @ child."""
        parent_mat = self.to_matrix_4x4()
        child_mat = child.to_matrix_4x4()
        world = parent_mat @ child_mat

        pos = Vec3(world[0, 3], world[1, 3], world[2, 3])
        # Extract Euler from rotation sub-matrix (Rz * Ry * Rx)
        sy = -world[2, 0]
        cy = math.sqrt(world[0, 0] ** 2 + world[1, 0] ** 2)
        if cy > 1e-6:
            rx = math.atan2(world[2, 1], world[2, 2])
            ry = math.atan2(sy, cy)
            rz = math.atan2(world[1, 0], world[0, 0])
        else:
            rx = math.atan2(-world[1, 2], world[1, 1])
            ry = math.atan2(sy, cy)
            rz = 0.0

        rot = Vec3(math.degrees(rx), math.degrees(ry), math.degrees(rz))
        return Transform(position=pos, rotation_deg=rot)
