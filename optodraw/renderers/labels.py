"""Where a part's name goes: above it (the default), below it, or at its left or right side."""

from __future__ import annotations

import math
from typing import Any

SIDES = ("top", "bottom", "left", "right", "top-left", "top-right", "bottom-left", "bottom-right")


def label_side(node: Any) -> str:
    side = getattr(node, "label_side", "top") or "top"
    if side not in SIDES:
        name = getattr(node, "label", "") or getattr(node, "component_type", "part")
        raise ValueError(f"{name}: label_side must be one of {', '.join(SIDES)}, got {side!r}")
    return side


def _placing_bounds(node: Any) -> tuple[float, float, float, float]:
    """The local box a label is placed past. A part turned off the right angles uses its own 2D shapes: the
    square frame of its art, turned 45 degrees, reaches far past a thin plate or mirror."""

    from optodraw.layout import _bounds_from_geometry, estimate_component_bounds

    turn = float(node.transform.rotation_deg.z) % 90.0
    if 1e-6 < turn < 90.0 - 1e-6:
        try:
            drawn = _bounds_from_geometry(node.geometry_2d())
        except Exception:
            drawn = None
        if drawn is not None:
            return drawn
    return estimate_component_bounds(node)


def label_spot(node: Any, gap: float = 2.5) -> tuple[float, float]:
    """The point the label's anchor sits on, from the part's centre, in the world frame with y up: just past the
    part's world-aligned box on its ``label_side``. A turned part measures its own turned box."""

    x0, y0, x1, y1 = _placing_bounds(node)
    a = math.radians(float(node.transform.rotation_deg.z))
    c, s = math.cos(a), math.sin(a)
    xs = [x * c - y * s for x, y in ((x0, y0), (x0, y1), (x1, y0), (x1, y1))]
    ys = [x * s + y * c for x, y in ((x0, y0), (x0, y1), (x1, y0), (x1, y1))]
    side = label_side(node)
    if "-" in side:                                   # a corner: past both edges
        vertical, horizontal = side.split("-")
        return (min(xs) - gap if horizontal == "left" else max(xs) + gap,
                min(ys) - gap if vertical == "bottom" else max(ys) + gap)
    if side == "left":
        return min(xs) - gap, 0.0
    if side == "right":
        return max(xs) + gap, 0.0
    if side == "bottom":
        return 0.0, min(ys) - gap
    return 0.0, max(ys) + gap
