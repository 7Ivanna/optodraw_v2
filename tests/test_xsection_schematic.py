"""Look A: the cross-section as a textbook process figure."""

from __future__ import annotations

import re
from pathlib import Path


from optodraw.gds.layout import GDSLayerRecord, GDSLayout
from optodraw.gds.xsection.model import cross_section


def _record(spec, polygons):
    return GDSLayerRecord(spec=spec, name=f"L{spec[0]}", description="", color="#000000", opacity=1.0,
                          thickness=0.22, zmin=0.0, material_preset="silicon", polygons=polygons, matched_pdk=False)


def _rect(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def _modulator():
    layout = GDSLayout(source_path=Path("t.gds"), cell_name="T", bounds=(-50, -50, 50, 50), layer_records=[
        _record((1, 0), [_rect(-20, -0.25, 20, 0.25)]), _record((3, 0), [_rect(-20, -3, 20, 3)]),
        _record((20, 0), [_rect(-20, -3, 20, 0)]), _record((21, 0), [_rect(-20, 0, 20, 3)]),
        _record((40, 0), [_rect(-20, -2.8, 20, -2.2)]), _record((41, 0), [_rect(-20, -3.2, 20, -1.8)])])
    return cross_section(layout, "gdsfactory_generic", ((0, -6), (0, 6)))


def _root(svg):
    return dict(re.findall(r'(\w[\w-]*)="([^"]*)"', re.search(r"<svg\b[^>]*>", svg).group(0)))


def test_auto_dimensions_give_the_rib_and_slab_sizes():
    svg = _modulator().svg(labels=False)
    texts = re.findall(r'<g class="dim">.*?<text[^>]*>([^<]+)</text>', svg, re.S)
    assert "500 nm" in texts and "220 nm" in texts and "90 nm" in texts


def _heavy_modulator():
    layout = GDSLayout(source_path=Path("t.gds"), cell_name="T", bounds=(-50, -50, 50, 50), layer_records=[
        _record((1, 0), [_rect(-20, -0.25, 20, 0.25)]), _record((3, 0), [_rect(-20, -5, 20, 5)]),
        _record((24, 0), [_rect(-20, -5, 20, -3.5)]), _record((25, 0), [_rect(-20, 3.5, 20, 5)])])
    return cross_section(layout, "gdsfactory_generic", ((0, -7), (0, 7)))


def test_the_strip_names_the_heavy_implants_as_the_figure_does():
    xs = _heavy_modulator()
    captions = [caption for _, caption, _ in xs.steps]
    assert "N++ implant" in captions and "P++ implant" in captions
    assert not any("NPP" in caption or "PPP" in caption for caption in captions)
    svg = xs.steps_svg()
    first = captions.index("N++ implant")
    panels = re.findall(r'<svg class="step".*?</svg>', svg, re.S)
    assert ['data-species="NPP"' in panel for panel in panels] == [index >= first for index in range(len(panels))]


def _rib_only():
    layout = GDSLayout(source_path=Path("t.gds"), cell_name="T", bounds=(-50, -50, 50, 50), layer_records=[
        _record((1, 0), [_rect(-20, -0.25, 20, 0.25)]), _record((3, 0), [_rect(-20, -3, 20, 3)])])
    return cross_section(layout, "gdsfactory_generic", ((0, -5), (0, 5)))


def test_a_deep_substrate_under_a_thin_box_is_a_stub_under_a_break():
    """The InP section drew its 2 um model substrate in full under a thin 0.5 um buffer: stretched five times, the
    figure stood twice as tall as it was wide and its labels read at a third of their size on a page. A substrate
    under a BOX too thin to cut is the stub under the break, as on silicon."""

    layout = GDSLayout(source_path=Path("t.gds"), cell_name="T", bounds=(-50, -50, 50, 50), layer_records=[
        _record((1, 0), [_rect(-20, 0.75, 20, 3.75)]), _record((1, 0), [_rect(-20, -3.75, 20, -0.75)])])
    xs = cross_section(layout, "inp_generic", ((0, -5), (0, 5)), window=(1.0, 9.0))
    svg = xs.svg()
    assert not re.search(r'data-region="handle"', svg), "the substrate is drawn in full, not as a stub"
    assert svg.count("InP substrate") == 1                          # named once, in its stub
