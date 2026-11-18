"""An exact cut along any straight line: per layer, the stretches of s the line crosses."""

from __future__ import annotations

from math import cos, radians, sin
from pathlib import Path

import pytest

from optodraw.gds.layout import GDSLayerRecord, GDSLayout
from optodraw.gds.xsection.cut import cut_layout, layer_key


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


def _turn(points, degrees):
    c, s = cos(radians(degrees)), sin(radians(degrees))
    return [(c * x - s * y, s * x + c * y) for x, y in points]


def test_the_layer_key_names_layer_and_datatype():
    assert layer_key((41, 0)) == "L41_0"


def test_a_cut_across_a_waveguide_gives_its_width_along_the_cut():
    cut = cut_layout(_layout({(1, 0): [_rect(-10, -0.25, 10, 0.25)]}), (0, -2), (0, 2))
    [interval] = cut.layer_intervals["L1_0"].intervals
    assert (interval.y0, interval.y1) == pytest.approx((1.75, 2.25))
    assert (cut.y_min, cut.y_max) == (0.0, 4.0)


def test_an_angled_cut_equals_the_same_cut_on_a_turned_layout():
    rect = _rect(-10, -0.25, 10, 0.25)
    straight = cut_layout(_layout({(1, 0): [rect]}), (0, -2), (0, 2))
    start, end = _turn([(0, -2), (0, 2)], 30)
    turned = cut_layout(_layout({(1, 0): [_turn(rect, 30)]}), start, end)
    a, b = straight.layer_intervals["L1_0"].intervals[0], turned.layer_intervals["L1_0"].intervals[0]
    assert (a.y0, a.y1) == pytest.approx((b.y0, b.y1), abs=1e-9)


def test_a_slanted_edge_is_cut_where_the_line_meets_it_not_at_its_bounding_box():
    cut = cut_layout(_layout({(2, 0): [[(0, 0), (4, 0), (0, 4)]]}), (-1, 1), (5, 1))
    [interval] = cut.layer_intervals["L2_0"].intervals
    assert (interval.y0, interval.y1) == pytest.approx((1.0, 4.0))          # x from 0 to 3, s = x + 1


def test_a_polygon_with_a_hole_gives_two_intervals():
    ring = _rect(-2, -2, 2, 2)
    hole = _rect(-1, -1, 1, 1)
    # a GDS ring polygon: the outer ring, a cut-in to the hole, and the hole the other way round
    keyhole = [*ring, ring[0], hole[0], *reversed(hole), hole[0]]
    cut = cut_layout(_layout({(1, 0): [keyhole]}), (0, -3), (0, 3))
    spans = [(item.y0, item.y1) for item in cut.layer_intervals["L1_0"].intervals]
    assert spans == pytest.approx([(1.0, 2.0), (4.0, 5.0)])


def test_a_cut_that_misses_every_shape_has_no_layers():
    cut = cut_layout(_layout({(1, 0): [_rect(-1, 5, 1, 6)]}), (0, -2), (0, 2))
    assert cut.layer_intervals == {}


def test_a_cut_that_starts_inside_a_shape_starts_its_interval_at_zero():
    cut = cut_layout(_layout({(1, 0): [_rect(-10, -0.25, 10, 0.25)]}), (0, 0), (0, 2))
    [interval] = cut.layer_intervals["L1_0"].intervals
    assert (interval.y0, interval.y1) == pytest.approx((0.0, 0.25))


def test_a_cut_needs_two_different_points():
    with pytest.raises(ValueError, match="two different points"):
        cut_layout(_layout({(1, 0): [_rect(0, 0, 1, 1)]}), (1, 1), (1, 1))
