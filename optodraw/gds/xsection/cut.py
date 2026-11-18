"""An exact cut of a GDS layout along any straight line.

Each layer becomes the stretches of ``s`` (the distance along the cut from its first point) where the line
runs inside one of its shapes. A slanted edge is cut where the line meets it, not at a bounding box.
"""

from __future__ import annotations

import math

from shapely.geometry import LineString, Polygon

from optodraw.gds.layout import GDSLayout
from optodraw.gds.mesh import _iter_simple_geometries
from optodraw.gds.xsection.masks import Interval, IntervalSet, LayoutCut, _normalize


def layer_key(spec) -> str:
    """The mask name of a GDS layer: ``L1_0`` for layer 1, datatype 0."""

    return f"L{int(spec[0])}_{int(spec[1])}"


def cut_layout(layout: GDSLayout, start: tuple[float, float], end: tuple[float, float], *,
               label: str = "cut") -> LayoutCut:
    """The intervals of every layer of ``layout`` along the line from ``start`` to ``end``."""

    (x0, y0), (x1, y1) = (float(start[0]), float(start[1])), (float(end[0]), float(end[1]))
    length = math.hypot(x1 - x0, y1 - y0)
    if length <= 0.0:
        raise ValueError("a cut needs two different points")
    ux, uy = (x1 - x0) / length, (y1 - y0) / length
    line = LineString([(x0, y0), (x1, y1)])
    found: dict[str, list[Interval]] = {}
    for record in layout.layer_records:
        key = layer_key(record.spec)
        for points in record.polygons:
            if len(points) < 3:
                continue
            shape = Polygon(points)
            if not shape.is_valid:
                shape = shape.buffer(0)
            for piece in _iter_simple_geometries(shape.intersection(line)):
                coords = list(getattr(piece, "coords", []))
                if len(coords) < 2:
                    continue                                    # the line only touches a corner
                s = [(px - x0) * ux + (py - y0) * uy for px, py in coords]
                if max(s) - min(s) > 1e-9:
                    found.setdefault(key, []).append(Interval(min(s), max(s)))
    return LayoutCut(y_min=0.0, y_max=length, x=0.0, window=0.0, label=label,
                     layer_intervals={key: IntervalSet(intervals=_normalize(items)) for key, items in found.items()})
