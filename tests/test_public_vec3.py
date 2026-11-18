"""Vec3, the point type of ports and positions, is part of the public API."""

from __future__ import annotations

import optodraw


def test_vec3_is_exported():
    point = optodraw.Vec3(1, 2, 0)
    assert (point.x, point.y) == (1, 2)
