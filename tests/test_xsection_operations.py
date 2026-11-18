"""Tests for Shapely deposit/etch/planarize operations."""

from __future__ import annotations

from shapely.geometry import MultiPolygon, Polygon, box

from optodraw.gds.xsection.masks import IntervalSet, LayoutCut
from optodraw.gds.xsection.operations import apply_deposit, apply_flip
from optodraw.gds.xsection.regions import RegionStack, repair


def _cut() -> LayoutCut:
    return LayoutCut.from_strips(
        {},
        y_min=-2.0,
        y_max=2.0,
        label="test",
    )


def test_deposit_adds_material_volume():
    stack = RegionStack()
    stack.set("device", repair(box(-1, 0, 1, 0.22)))
    apply_deposit(stack, _cut(), IntervalSet.from_intervals([(-0.5, 0.5)]), {"material": "oxide1", "thickness": 0.5})
    oxide = stack.get("oxide1")
    assert not oxide.is_empty
    assert oxide.bounds[1] >= 0.22 - 1e-6
    assert oxide.bounds[3] >= 0.72 - 1e-6


def _hole_count(geometry: MultiPolygon) -> int:
    return sum(len(poly.interiors) for poly in geometry.geoms)


def test_flip_preserves_holes():
    stack = RegionStack()
    holed = Polygon(shell=[(-1, 0), (1, 0), (1, 1), (-1, 1)], holes=[[(-0.5, 0.25), (0.5, 0.25), (0.5, 0.75), (-0.5, 0.75)]])
    stack.set("device", repair(holed))
    before = stack.get("device")
    assert before.area == 1.5
    assert _hole_count(before) == 1
    apply_flip(stack)
    after = stack.get("device")
    assert after.area == before.area
    assert _hole_count(after) == 1


