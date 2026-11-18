"""Process operations on the (s, z) plane: deposit, etch, CMP, implant, fill."""

from __future__ import annotations


import pytest
from shapely.geometry import box

from optodraw.gds.xsection.masks import IntervalSet, LayoutCut
from optodraw.gds.xsection.operations import (
    apply_deposit,
    apply_etch,
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


def _slab() -> RegionStack:
    stack = RegionStack()
    stack.add("box", rectangle(-2, 2, -1, 0), "sio2")
    stack.add("device", rectangle(-2, 2, 0, 0.22), "silicon")
    return stack


def test_cmp_removes_material_above_its_height_and_adds_none():
    stack = _slab()
    apply_deposit(stack, _cut(), None, {"material": "oxide", "thickness": 0.7, "conformality": 1.0})
    area = stack.get("oxide").area
    apply_planarize(stack, _cut(), {"to_z": 2.0})
    assert stack.get("oxide").area == pytest.approx(area)                  # nothing above 2.0: nothing changes
    apply_planarize(stack, _cut(), {"to_z": 0.5})
    assert stack.get("oxide").bounds[3] == pytest.approx(0.5)


def test_an_implant_where_the_silicon_is_etched_away_dopes_nothing():
    stack = _slab()
    apply_etch(stack, _cut(), IntervalSet.from_intervals([(1.0, 2.0)]), {"depth": 0.22, "into": ["device"]})
    apply_implant(stack, _cut(), IntervalSet.from_intervals([(1.2, 1.8)]), {"species": "P"})
    assert stack.doping.get("P") is None or stack.doping["P"].is_empty


