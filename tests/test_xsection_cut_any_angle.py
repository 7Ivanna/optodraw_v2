"""An exact cut along any straight line: per layer, the stretches of s the line crosses."""

from __future__ import annotations

from pathlib import Path

import pytest

from optodraw.gds.layout import GDSLayerRecord, GDSLayout
from optodraw.gds.xsection.cut import cut_layout


def _layout(shapes: dict[tuple[int, int], list[list[tuple[float, float]]]]) -> GDSLayout:
    records = [GDSLayerRecord(spec=spec, name=f"L{spec[0]}", description="", color="#000000", opacity=1.0,
                              thickness=0.22, zmin=0.0, material_preset="silicon", polygons=polygons,
                              matched_pdk=False)
               for spec, polygons in shapes.items()]
    xs = [x for polygons in shapes.values() for polygon in polygons for x, _ in polygon]
    ys = [y for polygons in shapes.values() for polygon in polygons for _, y in polygon]
    return GDSLayout(source_path=Path("t.gds"), cell_name="T", bounds=(min(xs), min(ys), max(xs), max(ys)),
                     layer_records=records)


def _rect(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def test_a_polygon_with_a_hole_gives_two_intervals():
    ring = _rect(-2, -2, 2, 2)
    hole = _rect(-1, -1, 1, 1)
    # a GDS ring polygon: the outer ring, a cut-in to the hole, and the hole the other way round
    keyhole = [*ring, ring[0], hole[0], *reversed(hole), hole[0]]
    cut = cut_layout(_layout({(1, 0): [keyhole]}), (0, -3), (0, 3))
    spans = [(item.y0, item.y1) for item in cut.layer_intervals["L1_0"].intervals]
    assert [v for span in spans for v in span] == pytest.approx([1.0, 2.0, 4.0, 5.0])


def test_a_cut_needs_two_different_points():
    with pytest.raises(ValueError, match="two different points"):
        cut_layout(_layout({(1, 0): [_rect(0, 0, 1, 1)]}), (1, 1), (1, 1))
