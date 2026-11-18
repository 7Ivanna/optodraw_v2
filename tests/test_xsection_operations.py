"""Tests for Shapely deposit/etch/planarize operations."""

from __future__ import annotations

from shapely.geometry import MultiPolygon, Polygon, box

from optodraw.gds.xsection.masks import IntervalSet, LayoutCut
from optodraw.gds.xsection.operations import apply_deposit, apply_etch, apply_flip, apply_planarize
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


def test_deposit_empty_mask_deposits_nothing():
    stack = RegionStack()
    stack.set("device", repair(box(-1, 0, 1, 0.22)))
    apply_deposit(stack, _cut(), IntervalSet.from_intervals([]), {"material": "oxide1", "thickness": 0.5})
    assert stack.get("oxide1").is_empty


def test_etch_removes_masked_region():
    stack = RegionStack()
    stack.set("device", repair(box(-1, 0, 1, 0.22)))
    initial_area = stack.get("device").area
    mask = IntervalSet.from_intervals([(-0.2, 0.2)])
    apply_etch(stack, _cut(), mask, {"depth": 0.13, "into": ["device"]})
    etched = stack.get("device")
    assert etched.area < initial_area
    assert etched.bounds[3] >= 0.22 - 1e-6


def test_planarize_cuts_the_target_down_to_its_height():
    stack = RegionStack()
    stack.set("oxide1", repair(box(-1, 0.2, 1, 0.9)))
    apply_planarize(stack, _cut(), {"into": ["oxide1"], "to_z": 0.75})
    assert abs(stack.get("oxide1").bounds[3] - 0.75) < 1e-6


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


def test_flip_twice_recovers_original():
    stack = RegionStack()
    stack.set("device", repair(box(-1, 0, 1, 1)))
    apply_flip(stack)
    apply_flip(stack)
    recovered = stack.get("device")
    assert recovered.area == 2.0
    assert recovered.bounds == (-1.0, 0.0, 1.0, 1.0)


def test_a_through_etch_leaves_no_sliver_of_a_film_that_is_not_quite_flat():
    # a deposited film's top can rise by one float step from end to end (1.8 to 1.8000000000000003); the
    # etch must still take all of it under the mask, not leave a sheet 1e-16 thick along the top
    stack = RegionStack()
    stack.set("M1", repair(Polygon([(0.0, 1.1), (13.0, 1.1), (13.0, 1.8000000000000003), (0.0, 1.8)])))
    cut = LayoutCut.from_strips({}, y_min=0.0, y_max=13.0, label="test")
    apply_etch(stack, cut, IntervalSet.from_intervals([(0.0, 5.136483843905306)]),
               {"through": True, "into": ["M1"], "sidewall_deg": 86.0})
    left = stack.get("M1").bounds[0]
    assert left > 5.0, f"the film still reaches s = {left}"
