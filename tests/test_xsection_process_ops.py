"""Process operations on the (s, z) plane: deposit, etch, CMP, implant, fill."""

from __future__ import annotations

import math

import pytest
from shapely.geometry import LineString, box

from optodraw.gds.xsection.masks import IntervalSet, LayoutCut
from optodraw.gds.xsection.operations import (
    apply_deposit,
    apply_etch,
    apply_fill,
    apply_implant,
    apply_planarize,
)
from optodraw.gds.xsection.regions import RegionStack, rectangle, repair


def _cut() -> LayoutCut:
    return LayoutCut.from_strips({}, y_min=-2.0, y_max=2.0, label="test")


def _ridge() -> RegionStack:
    stack = RegionStack()
    stack.add("box", rectangle(-2, 2, -1, 0), "sio2")
    stack.add("device", repair(box(-0.25, 0, 0.25, 0.22)), "silicon")    # a ridge on the oxide
    return stack


def test_a_region_keeps_its_material_and_copies_keep_it():
    stack = _ridge()
    assert stack.materials == {"box": "sio2", "device": "silicon"}
    assert stack.copy().materials == stack.materials
    assert stack.solid().bounds == pytest.approx((-2, -1, 2, 0.22))


def test_a_conformal_deposit_coats_the_top_and_the_walls_alike():
    stack = _ridge()
    apply_deposit(stack, _cut(), None, {"material": "oxide", "thickness": 0.1, "conformality": 1.0})
    oxide = stack.get("oxide")
    assert oxide.intersection(LineString([(0, 0.0), (0, 2)])).length == pytest.approx(0.1, abs=1e-3)
    assert oxide.intersection(LineString([(-1, 0.11), (-0.25, 0.11)])).length == pytest.approx(0.1, abs=1e-3)
    assert stack.materials["oxide"] == "oxide"


def test_a_directional_deposit_leaves_the_walls_almost_bare():
    stack = _ridge()
    apply_deposit(stack, _cut(), None, {"material": "metal", "thickness": 0.1, "conformality": 0.0})
    metal = stack.get("metal")
    assert metal.intersection(LineString([(0, 0.0), (0, 2)])).length == pytest.approx(0.1, abs=1e-3)
    assert metal.intersection(LineString([(-1, 0.11), (-0.25, 0.11)])).length < 0.002


def test_a_masked_deposit_stays_in_its_columns():
    stack = _ridge()
    apply_deposit(stack, _cut(), IntervalSet.from_intervals([(1.0, 1.5)]),
                  {"material": "metal", "thickness": 0.2, "conformality": 0.0})
    x0, _, x1, _ = stack.get("metal").bounds
    assert (x0, x1) == pytest.approx((1.0, 1.5), abs=1e-3)


def test_selective_growth_grows_only_on_the_named_region():
    stack = _ridge()
    apply_deposit(stack, _cut(), None, {"material": "ge", "thickness": 0.3, "conformality": 0.0, "on": ["device"],
                                        "material_key": "germanium"})
    ge = stack.get("ge")
    assert ge.intersection(LineString([(0, 0.0), (0, 2)])).length == pytest.approx(0.3, abs=1e-3)
    x0, _, x1, _ = ge.bounds                                   # a directional film: only a sliver on the walls
    assert x0 >= -0.25 - 1e-3 and x1 <= 0.25 + 1e-3
    assert ge.area == pytest.approx(0.5 * 0.3, rel=0.02)
    assert stack.materials["ge"] == "germanium"


def _slab() -> RegionStack:
    stack = RegionStack()
    stack.add("box", rectangle(-2, 2, -1, 0), "sio2")
    stack.add("device", rectangle(-2, 2, 0, 0.22), "silicon")
    return stack


def _thickness_at(region, s):
    return region.intersection(LineString([(s, -5), (s, 5)])).length


def test_a_partial_etch_leaves_the_slab_under_the_mask():
    stack = _slab()
    apply_etch(stack, _cut(), IntervalSet.from_intervals([(0.5, 2.0)]), {"depth": 0.13, "into": ["device"]})
    assert _thickness_at(stack.get("device"), 1.0) == pytest.approx(0.09, abs=1e-6)
    assert _thickness_at(stack.get("device"), 0.0) == pytest.approx(0.22, abs=1e-6)


def test_an_etch_that_stops_on_silicon_opens_the_oxide_down_to_it():
    stack = _slab()
    apply_fill(stack, _cut(), {"material": "oxide", "to_z": 1.0, "material_key": "sio2"})
    apply_etch(stack, _cut(), IntervalSet.from_intervals([(-0.2, 0.2)]), {"stop_on": ["device"], "into": ["oxide"]})
    assert _thickness_at(stack.get("oxide"), 0.0) == pytest.approx(0.0, abs=1e-6)
    assert _thickness_at(stack.get("device"), 0.0) == pytest.approx(0.22, abs=1e-6)
    assert _thickness_at(stack.get("oxide"), 1.0) == pytest.approx(0.78, abs=1e-6)


def test_a_sloped_sidewall_narrows_the_trench_with_depth():
    stack = _slab()
    apply_etch(stack, _cut(), IntervalSet.from_intervals([(-0.5, 0.5)]),
               {"depth": 0.22, "into": ["device"], "sidewall_deg": 80.0})
    floor = stack.get("device").intersection(LineString([(-2, 0.001), (2, 0.001)]))
    inset = 0.22 / math.tan(math.radians(80.0))
    assert 4.0 - floor.length == pytest.approx(1.0 - 2 * inset, abs=2e-3)


def test_cmp_removes_material_above_its_height_and_adds_none():
    stack = _slab()
    apply_deposit(stack, _cut(), None, {"material": "oxide", "thickness": 0.7, "conformality": 1.0})
    area = stack.get("oxide").area
    apply_planarize(stack, _cut(), {"to_z": 2.0})
    assert stack.get("oxide").area == pytest.approx(area)                  # nothing above 2.0: nothing changes
    apply_planarize(stack, _cut(), {"to_z": 0.5})
    assert stack.get("oxide").bounds[3] == pytest.approx(0.5)


def test_an_implant_dopes_the_silicon_under_the_mask_and_keeps_its_material():
    stack = _slab()
    apply_implant(stack, _cut(), IntervalSet.from_intervals([(-1.0, 0.0)]), {"species": "N"})
    dose = stack.doping["N"]
    assert dose.bounds == pytest.approx((-1.0, 0.0, 0.0, 0.22))
    assert dose.difference(stack.get("device")).area == pytest.approx(0.0, abs=1e-12)
    assert stack.materials["device"] == "silicon"


def test_an_implant_where_the_silicon_is_etched_away_dopes_nothing():
    stack = _slab()
    apply_etch(stack, _cut(), IntervalSet.from_intervals([(1.0, 2.0)]), {"depth": 0.22, "into": ["device"]})
    apply_implant(stack, _cut(), IntervalSet.from_intervals([(1.2, 1.8)]), {"species": "P"})
    assert stack.doping.get("P") is None or stack.doping["P"].is_empty


def test_a_fill_closes_every_gap_to_a_flat_top():
    stack = _slab()
    apply_etch(stack, _cut(), IntervalSet.from_intervals([(-2.0, -0.25), (0.25, 2.0)]), {"depth": 0.22, "into": ["device"]})
    apply_fill(stack, _cut(), {"material": "oxide", "to_z": 1.0, "material_key": "sio2"})
    assert stack.solid().area == pytest.approx(rectangle(-2, 2, -1, 1.0).area, rel=1e-6)
    assert stack.get("oxide").bounds[3] == pytest.approx(1.0)
