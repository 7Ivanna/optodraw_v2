"""Dimension markers and leader lines for schematic 2D figures.

Markers carry **true physical sizes** from ``PhysicalSpec`` while the underlying
device art uses legible schematic geometry — they are not tied to draw scale.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Sequence

import drawsvg as draw


@dataclass(frozen=True)
class DimensionMarker:
    """A linear dimension between two chip-plane points (µm)."""

    x1: float
    y1: float
    x2: float
    y2: float
    label: str
    offset: float = 3.0
    stroke: str = "#374151"
    font_size: float = 2.8


def linear_dimension(
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    label: str,
    *,
    offset: float = 3.0,
    stroke: str = "#374151",
    font_size: float = 2.8,
) -> DimensionMarker:
    """Create a horizontal or vertical dimension marker with a text label."""

    return DimensionMarker(
        x1=float(x1),
        y1=float(y1),
        x2=float(x2),
        y2=float(y2),
        label=str(label),
        offset=float(offset),
        stroke=stroke,
        font_size=font_size,
    )


def dimension_marker_to_svg_nodes(marker: DimensionMarker) -> list[Any]:
    """Convert one marker to drawsvg elements (chip coords, Y-up)."""

    dx = marker.x2 - marker.x1
    dy = marker.y2 - marker.y1
    length = math.hypot(dx, dy)
    if not math.isfinite(length) or length <= 0:
        raise ValueError("Dimension marker endpoints must be distinct finite points")
    nx, ny = dy / length, -dx / length
    x1, y1 = marker.x1 + nx * marker.offset, marker.y1 + ny * marker.offset
    x2, y2 = marker.x2 + nx * marker.offset, marker.y2 + ny * marker.offset
    nodes: list[Any] = []
    nodes.append(draw.Line(x1, -y1, x2, -y2, stroke=marker.stroke, stroke_width=0.25))
    for x, y in ((x1, y1), (x2, y2)):
        nodes.append(draw.Line(x - nx * 0.8, -(y - ny * 0.8), x + nx * 0.8, -(y + ny * 0.8), stroke=marker.stroke, stroke_width=0.25))
    label_x = (x1 + x2) / 2.0 + nx * marker.font_size * 0.65
    label_y = (y1 + y2) / 2.0 + ny * marker.font_size * 0.65
    angle = -math.degrees(math.atan2(dy, dx))
    if angle < -90:
        angle += 180
    elif angle > 90:
        angle -= 180
    nodes.append(draw.Text(marker.label, marker.font_size, label_x, -label_y, text_anchor="middle", dominant_baseline="central", fill=marker.stroke, transform=f"rotate({angle},{label_x},{-label_y})"))

    return nodes


def append_dimension_overlay(parent: Any, markers: Sequence[DimensionMarker]) -> None:
    """Append dimension markers to an existing drawsvg group or drawing."""

    overlay = draw.Group(opacity=0.95)
    for marker in markers:
        for node in dimension_marker_to_svg_nodes(marker):
            overlay.append(node)
    parent.append(overlay)


def markers_from_physical_spec(
    origin_x: float,
    origin_y: float,
    *,
    width_um: float | None = None,
    length_um: float | None = None,
    unit: str = "µm",
) -> list[DimensionMarker]:
    """Build common width/length markers from physical metadata."""

    def positive_dimension(value: float | None) -> float | None:
        if value is None or isinstance(value, bool):
            return None
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError):
            return None
        return number if math.isfinite(number) and number > 0 else None

    markers: list[DimensionMarker] = []
    length = positive_dimension(length_um)
    width = positive_dimension(width_um)
    if length is not None:
        markers.append(
            linear_dimension(
                origin_x - length / 2.0,
                origin_y,
                origin_x + length / 2.0,
                origin_y,
                f"{length:g} {unit}",
                offset=4.0,
            )
        )
    if width is not None:
        markers.append(
            linear_dimension(
                origin_x,
                origin_y - width / 2.0,
                origin_x,
                origin_y + width / 2.0,
                f"{width:g} {unit}",
                offset=4.0,
            )
        )
    return markers
