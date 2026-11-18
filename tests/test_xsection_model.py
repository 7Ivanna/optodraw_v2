"""cross_section(): a GDS, a stack and a cut give regions, labels and findings."""

from __future__ import annotations

from pathlib import Path

import pytest
from shapely.geometry import box

from optodraw.gds.layout import GDSLayerRecord, GDSLayout
from optodraw.gds.xsection.model import cross_section

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


def test_a_cut_that_misses_everything_still_gives_the_substrate_and_says_so():
    xs = cross_section(_rib(), "gdsfactory_generic", ((40, 30), (40, 40)))
    assert not xs.regions["box"].is_empty
    assert any("crosses no drawn layer" in f for f in xs.check())


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


