"""Tests for cross-section mask interval DSL."""

from __future__ import annotations

from optodraw.gds.xsection.masks import IntervalSet, MaskExpression


def test_interval_union_and_intersection():
    left = IntervalSet.from_intervals([(0.0, 1.0), (2.0, 3.0)])
    right = IntervalSet.from_intervals([(0.5, 2.5)])
    merged = left.union(right)
    assert [(item.y0, item.y1) for item in merged.intervals] == [(0.0, 3.0)]

    overlap = left.intersection(right)
    assert [(item.y0, item.y1) for item in overlap.intervals] == [(0.5, 1.0), (2.0, 2.5)]


def test_interval_complement():
    full = IntervalSet.from_intervals([(0.0, 1.0), (3.0, 4.0)])
    complement = full.complement(0.0, 5.0)
    assert [(item.y0, item.y1) for item in complement.intervals] == [(1.0, 3.0), (4.0, 5.0)]


def test_mask_expression_boolean_ops():
    layers = {
        "RIB": IntervalSet.from_intervals([(-0.25, 0.25)]),
        "SLAB": IntervalSet.from_intervals([(-1.0, 1.0)]),
        "GRAT": IntervalSet.from_intervals([(1.5, 2.0)]),
    }
    slab_not_rib = MaskExpression("SLAB & ~RIB").evaluate(layers, y_min=-2.0, y_max=2.0)
    assert [(item.y0, item.y1) for item in slab_not_rib.intervals] == [(-1.0, -0.25), (0.25, 1.0)]

    outside = MaskExpression("~(RIB | SLAB | GRAT)").evaluate(layers, y_min=-2.0, y_max=2.0)
    assert [(item.y0, item.y1) for item in outside.intervals] == [(-2.0, -1.0), (1.0, 1.5)]
