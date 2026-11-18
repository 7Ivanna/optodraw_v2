"""A layer stack becomes the process that makes it: device etches, implants, growth, vias, metal, cladding."""

from __future__ import annotations

import pytest
from shapely.geometry import LineString

from optodraw.gds.parsers import LayerStackSpec
from optodraw.gds.xsection.engine import XSectionEngine
from optodraw.gds.xsection.masks import IntervalSet, LayoutCut
from optodraw.gds.xsection.stack_process import process_from_stack


def _strips(**intervals) -> LayoutCut:
    return LayoutCut.from_strips({key: IntervalSet.from_intervals(value) for key, value in intervals.items()},
                                 y_min=-4.0, y_max=4.0, label="test")


def _thickness(region, s):
    return region.intersection(LineString([(s, -10), (s, 10)])).length


def _modulator():
    """A rib (WG 1/0) on a 90 nm slab (3/0), N left and P right, a contact (40/0) and M1 (41/0) on the left."""

    return _strips(L1_0=[(-0.25, 0.25)], L3_0=[(-3.0, 3.0)], L20_0=[(-3.0, 0.0)], L21_0=[(0.0, 3.0)],
                   L40_0=[(-2.8, -2.2)], L41_0=[(-3.2, -1.8)])


def test_a_layer_named_etch_cuts_a_trench():
    stack = LayerStackSpec(name="t", oxide={"box_depth": 2.0, "cladding_top": 1.0, "handle_thickness": 1.0},
                           styles={(1, 0): {"name": "Core", "zmin": 0.0, "thickness": 0.3, "material_preset": "silicon_nitride"},
                                   (2, 0): {"name": "Core etch", "zmin": 0.0, "thickness": 0.3, "material_preset": "silicon_nitride"}})
    out = XSectionEngine(process_from_stack(stack)).run(_strips(L1_0=[(-4.0, 4.0)], L2_0=[(-0.5, 0.5)]))
    assert _thickness(out.internal_regions["device"], 0.0) == pytest.approx(0.0, abs=1e-6)
    assert _thickness(out.internal_regions["device"], 2.0) == pytest.approx(0.3, abs=1e-6)


def test_a_passivation_opens_over_the_pads():
    stack = LayerStackSpec(name="t", oxide={"box_depth": 2.0, "cladding_top": 1.0, "handle_thickness": 1.0,
                                            "passivation": 0.4},
                           styles={(1, 0): {"name": "WG", "zmin": 0.0, "thickness": 0.22, "material_preset": "silicon"},
                                   (9, 0): {"name": "PAD", "role": "pad", "zmin": 1.0, "thickness": 0.5,
                                            "material_preset": "aluminum"}})
    out = XSectionEngine(process_from_stack(stack)).run(_strips(L1_0=[(-0.25, 0.25)], L9_0=[(1.0, 3.0)]))
    passivation = out.internal_regions["passivation"]
    assert _thickness(passivation, 2.0) == pytest.approx(0.0, abs=1e-6)  # opened over the pad
    assert _thickness(passivation, -2.0) == pytest.approx(0.4, abs=1e-3)


def test_a_stack_with_no_core_at_zero_is_refused():
    stack = LayerStackSpec(name="t", oxide={"box_depth": 2.0, "cladding_top": 1.0},
                           styles={(41, 0): {"name": "M1", "zmin": 1.0, "thickness": 0.5, "material_preset": "aluminum"}})
    with pytest.raises(ValueError, match="no core layer"):
        process_from_stack(stack)


def test_the_parser_keeps_sidewall_and_polarity(tmp_path):
    from optodraw.gds.parsers import parse_layerstack_oxide, parse_layerstack_yaml

    path = tmp_path / "s.yaml"
    path.write_text('oxide:\n  tox: {thickness: 1.0, planarized: true}\n  passivation: {thickness: 0.3}\n'
                    'layers:\n  "1/0": {name: WG, zmin: 0, thickness: 0.22, sidewall_deg: 82, polarity: keep}\n')
    style = parse_layerstack_yaml(path)[(1, 0)]
    assert style["sidewall_deg"] == 82.0 and style["polarity"] == "keep"
    oxide = parse_layerstack_oxide(path)
    assert oxide["passivation"] == pytest.approx(0.3) and oxide["tox_planarized"] == 1.0


def test_a_layer_of_air_is_an_etch_never_a_film():
    """A stack marks its etches with material: air. They were deposited as films. One that ends inside the device
    layer is etched before the oxide; one that reaches up into the oxide is cut through the finished stack, down
    to its zmin, and leaves a metal standing."""

    stack = LayerStackSpec(name="t", oxide={"box_depth": 2.0, "cladding_top": 3.0, "handle_thickness": 1.0},
                           styles={(1, 0): {"name": "WG", "zmin": 0.0, "thickness": 0.22, "material_preset": "silicon"},
                                   (41, 0): {"name": "M1", "role": "metal", "zmin": 1.0, "thickness": 0.5,
                                             "material_preset": "aluminum"},
                                   (205, 0): {"name": "Shelf", "zmin": 0.09, "thickness": 0.13, "material_preset": "air"},
                                   (6, 0): {"name": "OX_OPEN", "zmin": 0.5, "thickness": 2.5, "material_preset": "air"},
                                   (13, 0): {"name": "M_OPEN", "zmin": 1.5, "thickness": 1.5, "material_preset": "air"}})
    cut = _strips(L1_0=[(-4.0, -1.0)], L205_0=[(-3.0, -2.0)], L6_0=[(0.0, 1.0)], L41_0=[(2.0, 4.0)], L13_0=[(2.5, 3.5)])
    process = process_from_stack(stack)
    assert not any("deposit" in (step.caption or "") and "OPEN" in (step.caption or "") for step in process.process)
    out = XSectionEngine(process).run(cut)
    assert not {"Shelf", "OX_OPEN", "M_OPEN"} & set(out.internal_regions)
    assert _thickness(out.internal_regions["device"], -2.5) == pytest.approx(0.09, abs=1e-6)     # the shelf
    assert _thickness(out.internal_regions["device"], -1.5) == pytest.approx(0.22, abs=1e-6)
    oxide = out.internal_regions["oxide"]
    assert oxide.intersection(LineString([(0.5, -10), (0.5, 10)])).bounds[3] == pytest.approx(0.5, abs=1e-6)
    assert oxide.intersection(LineString([(3.0, -10), (3.0, 10)])).length == pytest.approx(1.0, abs=1e-6)  # under M1
    assert _thickness(out.internal_regions["M1"], 3.0) == pytest.approx(0.5, abs=1e-6)          # the metal stays


def test_an_air_layer_below_the_device_cuts_nothing():
    """gdsfactory's d25 script draws its undercut (6/0) as air from -8 to -3 um, under the device. The air rule took
    a layer whose top is below the device top for a device etch, and removed the silicon over it."""

    stack = LayerStackSpec(name="t", oxide={"box_depth": 3.0, "cladding_top": 1.0, "handle_thickness": 1.0},
                           styles={(1, 0): {"name": "WG", "zmin": 0.0, "thickness": 0.22, "material_preset": "silicon"},
                                   (6, 0): {"name": "undercut", "zmin": -8.0, "thickness": 5.0, "material_preset": "air"}})
    process = process_from_stack(stack)
    assert not any(step.id == "cut_L6_0" for step in process.process)
    out = XSectionEngine(process).run(_strips(L1_0=[(-1.0, 1.0)], L6_0=[(-2.0, 2.0)]))
    assert _thickness(out.internal_regions["device"], 0.0) == pytest.approx(0.22, abs=1e-6)
