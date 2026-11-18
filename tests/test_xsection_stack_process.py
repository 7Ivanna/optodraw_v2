"""A layer stack becomes the process that makes it: device etches, implants, growth, vias, metal, cladding."""

from __future__ import annotations

import pytest
from shapely.geometry import LineString

from optodraw.gds.parsers import LayerStackSpec, load_layer_stack
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


def _run(stack_name, cut):
    stack = load_layer_stack(stack_name)
    process = process_from_stack(stack, drawn=set(cut.layer_intervals))
    return process, XSectionEngine(process).run(cut)


def test_the_generic_stack_makes_a_rib_on_its_slab_and_etches_the_rest_away():
    _, out = _run("gdsfactory_generic", _modulator())
    device = out.internal_regions["device"]
    assert _thickness(device, 0.0) == pytest.approx(0.22, abs=1e-6)
    assert _thickness(device, 1.5) == pytest.approx(0.09, abs=1e-6)
    assert _thickness(device, 3.6) == pytest.approx(0.0, abs=1e-6)
    assert out.internal_regions["box"].bounds[3] == pytest.approx(0.0)


def test_implants_dope_the_silicon_on_their_side():
    _, out = _run("gdsfactory_generic", _modulator())
    n, p = out.doping["N"], out.doping["P"]
    assert n.bounds[2] <= 0.0 + 1e-9 and p.bounds[0] >= 0.0 - 1e-9
    assert n.difference(out.internal_regions["device"]).area == pytest.approx(0.0, abs=1e-12)


def test_the_contact_lands_on_the_slab_and_m1_sits_on_its_band():
    _, out = _run("gdsfactory_generic", _modulator())
    contact, m1 = out.internal_regions["VIAC"], out.internal_regions["M1"]
    assert contact.bounds[1] == pytest.approx(0.09, abs=1e-6)
    assert contact.distance(out.internal_regions["device"]) < 1e-6
    assert (m1.bounds[1], m1.bounds[3]) == pytest.approx((1.1, 1.8), abs=1e-6)


def test_the_top_cladding_is_conformal_and_reaches_the_stack_height():
    """The generic stack's passivation is oxide: over a cladding that buries the metal it goes on as the cladding
    did, in the same oxide."""

    _, out = _run("gdsfactory_generic", _modulator())
    oxide = out.internal_regions["oxide"]
    far = oxide.intersection(LineString([(2.5, -10), (2.5, 10)]))
    assert far.bounds[3] == pytest.approx(3.0 + 0.5, abs=1e-6)            # cladding_top, then the oxide passivation
    assert oxide.bounds[3] > 3.5 + 0.5                                     # the bump over M1
    assert "passivation" not in out.internal_regions


def test_every_step_has_a_caption_and_undrawn_layers_add_no_steps():
    process, _ = _run("gdsfactory_generic", _modulator())
    captions = [step.caption or "" for step in process.process]
    assert all(captions)
    assert not any("M2" in caption or "NPP" in caption or "150 nm" in caption for caption in captions)


def test_a_nitride_stack_makes_the_nitride_the_device_layer():
    _, out = _run("cornerstone_sin300", _strips(L203_0=[(-0.6, 0.6)]))
    assert out.materials["device"] == "silicon_nitride"
    assert _thickness(out.internal_regions["device"], 0.0) == pytest.approx(0.3, abs=1e-6)
    assert _thickness(out.internal_regions["device"], 2.0) == pytest.approx(0.0, abs=1e-6)


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


def _opening_edge(region, z, x0, x1, middle):
    """The left edge of the opening in ``region`` at height ``z``: where the film west of ``middle`` ends."""

    cut = region.intersection(LineString([(x0, z), (x1, z)]))
    pieces = getattr(cut, "geoms", [cut])
    return max(piece.bounds[2] for piece in pieces if not piece.is_empty and piece.bounds[2] < middle)


def test_a_pad_opening_layer_opens_the_passivation_with_sloped_walls():
    """gdsfactory's generic process opens the passivation on PADOPEN (46/0), inside the pad, so the film still
    covers the pad's edges; published cross-sections draw that opening with sloped walls."""

    stack = LayerStackSpec(name="t", oxide={"box_depth": 2.0, "cladding_top": 1.0, "handle_thickness": 1.0,
                                            "passivation": 0.4},
                           styles={(1, 0): {"name": "WG", "zmin": 0.0, "thickness": 0.22, "material_preset": "silicon"},
                                   (9, 0): {"name": "PAD", "role": "pad", "zmin": 1.0, "thickness": 0.5,
                                            "material_preset": "aluminum"},
                                   (46, 0): {"name": "PADOPEN", "role": "pad_open", "sidewall_deg": 60.0,
                                             "visible": False}})
    cut = _strips(L1_0=[(-0.25, 0.25)], L9_0=[(0.0, 3.0)], L46_0=[(0.8, 2.2)])
    passivation = XSectionEngine(process_from_stack(stack)).run(cut).internal_regions["passivation"]
    assert _thickness(passivation, 1.5) == pytest.approx(0.0, abs=1e-6)       # open over the middle of the pad
    assert _thickness(passivation, 0.4) == pytest.approx(0.4, abs=1e-3)       # the film still covers its edge
    low, high = _opening_edge(passivation, 1.52, 0.1, 2.9, 1.5), _opening_edge(passivation, 1.88, 0.1, 2.9, 1.5)
    assert low - high > 0.15, (low, high)                                     # wider at the top: a sloped wall


def test_the_generic_stack_has_gdsfactorys_passivation_and_pad_opening():
    stack = load_layer_stack("gdsfactory_generic")
    assert stack.oxide["passivation"] == pytest.approx(0.5)
    assert stack.styles[(46, 0)]["role"] == "pad_open"


def test_the_generic_stack_carries_gdsfactorys_sidewalls_and_passivation_material():
    """gdsfactory's generic LayerStack: core sidewall_angle 10, via_contact -10 (wider at the top); its KLayout
    process script deposits oxide as the passivation. The bundled stack left all three out."""

    stack = load_layer_stack("gdsfactory_generic")
    assert stack.styles[(1, 0)]["sidewall_deg"] == pytest.approx(80.0)
    assert stack.styles[(40, 0)]["sidewall_deg"] == pytest.approx(80.0)
    assert stack.passivation_material == "sio2"


def test_a_sloped_contact_hole_makes_a_via_wider_at_the_top():
    _, out = _run("gdsfactory_generic", _modulator())
    via = out.internal_regions["VIAC"]
    low = via.intersection(LineString([(-4, 0.15), (4, 0.15)])).length
    high = via.intersection(LineString([(-4, 1.05), (4, 1.05)])).length
    assert high - low > 0.2, (low, high)


def test_an_oxide_passivation_joins_the_oxide_and_another_material_is_its_own_film():
    """The oxide is one body built by its deposition steps, not a film laid over it. gdsfactory's passivation is
    oxide, so it is the last oxide level, planarised over M3 as every level below. A passivation of another
    material stays a film of its own."""

    import copy

    cut = _strips(L1_0=[(-0.25, 0.25)], L49_0=[(1.0, 3.0)], L43_0=[(1.5, 2.5)])
    _, out = _run("gdsfactory_generic", cut)
    assert "passivation" not in out.internal_regions
    oxide = out.internal_regions["oxide"]
    for s in (-2.0, 2.0):                                                  # beside M3, and over it: one flat top
        assert oxide.intersection(LineString([(s, -10), (s, 10)])).bounds[3] == pytest.approx(5.2 + 0.5, abs=1e-6)
    stack = copy.deepcopy(load_layer_stack("gdsfactory_generic"))
    stack.passivation_material = "silicon_nitride"
    out = XSectionEngine(process_from_stack(stack)).run(cut)
    assert out.materials["passivation"] == "silicon_nitride"
    assert _thickness(out.internal_regions["passivation"], -2.0) == pytest.approx(0.5, abs=1e-3)


def test_a_tapered_etch_stays_vertical_where_its_mask_meets_the_window_edge():
    """With the stack's 86 degree metal etch, the metal outside the pad was etched as a trench that narrows
    with depth also at the window edge, so a thin wedge of metal stood at each edge of the figure."""

    from shapely.geometry import box as rectangle

    stack = LayerStackSpec(name="t", oxide={"box_depth": 2.0, "cladding_top": 1.0, "handle_thickness": 1.0},
                           styles={(1, 0): {"name": "WG", "zmin": 0.0, "thickness": 0.22, "material_preset": "silicon"},
                                   (41, 0): {"name": "M1", "role": "metal", "zmin": 1.0, "thickness": 0.5,
                                             "material_preset": "aluminum", "sidewall_deg": 80.0}})
    out = XSectionEngine(process_from_stack(stack)).run(_strips(L1_0=[(-0.25, 0.25)], L41_0=[(-1.0, 1.0)]))
    metal = out.internal_regions["M1"]
    assert metal.intersection(rectangle(-4.0, -10, -2.0, 10)).area == pytest.approx(0.0, abs=1e-9)
    assert metal.intersection(rectangle(2.0, -10, 4.0, 10)).area == pytest.approx(0.0, abs=1e-9)


def test_a_tapered_rib_etch_leaves_no_spike_at_the_slab_edge():
    """With the core's 80 degree sidewall, the rib etch's trench narrowed with depth at the slab's outer edge
    too, where the full etch takes everything beyond: a 220 nm wedge of silicon stood at each end of the slab."""

    from shapely.geometry import box as rectangle

    _, out = _run("gdsfactory_generic", _modulator())
    device = out.internal_regions["device"]
    for edge in (rectangle(2.8, -1, 3.2, 1), rectangle(-3.2, -1, -2.8, 1)):
        assert device.intersection(edge).bounds[3] <= 0.09 + 1e-6, device.intersection(edge).bounds


def test_a_patterned_film_over_a_bump_is_gone_outside_its_mask():
    """The generic stack's SiN (0.32-0.67 um) is deposited over the germanium (0.22-0.72 um), which pokes through
    the oxide: the film rises over it, the pattern etch took its depth from that top, and a SiN sheet was left
    across the whole cut. A film's pattern etch takes the whole film under its mask."""

    from shapely.geometry import box as rectangle

    _, out = _run("gdsfactory_generic", _strips(L1_0=[(-3.0, -1.0)], L5_0=[(-2.5, -1.5)], L34_0=[(1.5, 2.5)]))
    sin = out.internal_regions["WGN (SiN)"]
    assert sin.intersection(rectangle(-4.0, -10, 1.0, 10)).area == pytest.approx(0.0, abs=1e-9)
    assert sin.intersection(rectangle(1.6, -10, 2.4, 10)).area > 0.0


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
