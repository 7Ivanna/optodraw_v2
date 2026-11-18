"""cross_section(): a GDS, a stack and a cut give regions, labels and findings."""

from __future__ import annotations

from pathlib import Path

import pytest
from shapely.geometry import box

from optodraw.gds.layout import GDSLayerRecord, GDSLayout
from optodraw.gds.xsection.model import CrossSection, cross_section

FIXTURE = Path(__file__).parent / "fixtures" / "xsection" / "generic_siph_minimal.yaml"


def _record(spec, polygons):
    return GDSLayerRecord(spec=spec, name=f"L{spec[0]}", description="", color="#000000", opacity=1.0,
                          thickness=0.22, zmin=0.0, material_preset="silicon", polygons=polygons, matched_pdk=False)


def _rect(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def _layout(*records) -> GDSLayout:
    return GDSLayout(source_path=Path("t.gds"), cell_name="T", bounds=(-50, -50, 50, 50), layer_records=list(records))


def _rib():
    return _layout(_record((1, 0), [_rect(-20, -0.25, 20, 0.25)]), _record((3, 0), [_rect(-20, -3, 20, 3)]))


def test_a_rib_cut_gives_named_regions_with_labels_and_materials():
    xs = cross_section(_rib(), "gdsfactory_generic", ((0, -6), (0, 6)))
    assert isinstance(xs, CrossSection)
    assert {"handle", "box", "device", "oxide"} <= set(xs.regions)
    assert xs.labels["device"] == "Si" and xs.labels["box"] == "BOX" and xs.labels["oxide"] == "SiO_2"
    assert xs.materials["device"] == "silicon"
    assert xs.window[0] < 3.0 and xs.window[1] > 9.0                     # the slab spans s 3..9
    assert xs.check() == []


def test_a_layer_drawn_on_the_cut_but_missing_from_the_stack_is_a_finding():
    layout = _layout(_record((1, 0), [_rect(-20, -0.25, 20, 0.25)]), _record((77, 0), [_rect(-1, -1, 1, 1)]))
    xs = cross_section(layout, "gdsfactory_generic", ((0, -6), (0, 6)))
    assert any("77/0" in f and "no entry" in f for f in xs.check())


def test_a_cut_that_misses_everything_still_gives_the_substrate_and_says_so():
    xs = cross_section(_rib(), "gdsfactory_generic", ((40, 30), (40, 40)))
    assert not xs.regions["box"].is_empty
    assert any("crosses no drawn layer" in f for f in xs.check())


def test_a_very_long_cut_keeps_a_readable_window_and_says_so():
    layout = _layout(_record((1, 0), [_rect(-0.25, -2000, 0.25, 2000), _rect(1999.75, -2000, 2000.25, 2000)]))
    xs = cross_section(layout, "gdsfactory_generic", ((-1000, 0), (3000, 0)))
    assert xs.window[1] - xs.window[0] <= 40.0 + 1e-9
    assert any("window" in f for f in xs.check())


def test_an_implant_over_etched_silicon_is_a_finding():
    layout = _layout(_record((1, 0), [_rect(-20, -0.25, 20, 0.25)]), _record((20, 0), [_rect(-20, 2, 20, 3)]))
    xs = cross_section(layout, "gdsfactory_generic", ((0, -6), (0, 6)))
    assert any("N" in f and "etched away" in f for f in xs.check())


def test_a_via_that_lands_on_nothing_is_a_finding():
    layout = _layout(_record((1, 0), [_rect(-20, -0.25, 20, 0.25)]), _record((40, 0), [_rect(-20, 2, 20, 3)]))
    xs = cross_section(layout, "gdsfactory_generic", ((0, -6), (0, 6)))
    assert any("VIAC" in f and "lands on nothing" in f for f in xs.check())


def test_stack_warnings_reach_the_findings(tmp_path):
    stack = tmp_path / "s.yaml"
    stack.write_text('oxide:\n  box: {thickness: 2}\n  tox: {thickness: 1}\n  handle: {thickness: 1}\n'
                     'layers:\n  "1/0": {name: WG, zmin: 0, thickness: 0.22, material: silicon}\n'
                     '  "5/0": {name: GHOST, zmin: 0.5}\n')
    xs = cross_section(_rib(), stack, ((0, -6), (0, 6)))
    assert any("5" in f and "thickness" in f for f in xs.check())


def test_a_process_file_reads_the_cut_by_its_own_layer_names():
    layout = _layout(_record((10, 0), [_rect(-20, -0.25, 20, 0.25)]), _record((12, 0), [_rect(-20, -1, 20, 1)]))
    xs = cross_section(layout, FIXTURE, ((0, -3), (0, 3)))
    device = xs.regions["device"].intersection(box(xs.window[0], -1, xs.window[1], 1))
    assert device.bounds[3] == pytest.approx(0.22)
    assert device.area == pytest.approx(0.5 * 0.22 + 1.5 * 0.09, rel=1e-6)   # the rib and its slab, nothing else


def test_a_cross_section_keeps_its_source_for_parallel_cuts():
    layout = _rib()
    xs = cross_section(layout, "gdsfactory_generic", ((0, -6), (0, 6)))
    assert xs.source["layout"] is layout
    assert xs.source["cut"] == ((0.0, -6.0), (0.0, 6.0))
    assert xs.source["stack"].name.startswith("gdsfactory generic")


def test_a_loaded_stack_gives_the_same_cross_section_as_its_name():
    from optodraw.gds.parsers import load_layer_stack

    by_name = cross_section(_rib(), "gdsfactory_generic", ((0, -6), (0, 6)))
    by_spec = cross_section(_rib(), load_layer_stack("gdsfactory_generic"), ((0, -6), (0, 6)))
    assert set(by_spec.regions) == set(by_name.regions)
    for name, region in by_name.regions.items():
        assert by_spec.regions[name].symmetric_difference(region).area == pytest.approx(0.0, abs=1e-9)
    assert by_spec.check() == []
