"""GDSModel.layout_view(): the layout page of an imported GDS in a notebook cell, with the part's own colours."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from optodraw import GDSModel
from optodraw.gds import normalize_layer_stack
from optodraw.renderers.capture3d import find_chrome

from gds_layout_fixtures import capture_over_http, docs_device_gds

needs_chrome = pytest.mark.skipif(not find_chrome(required=False), reason="needs Chrome, Chromium or Edge")


def test_the_preview_is_one_iframe_holding_the_viewer(tmp_path):
    html = GDSModel(str(docs_device_gds(tmp_path)), cell_name="straight_pn").layout_view(width=700, height=400)._repr_html_()
    assert html.count("<iframe") == 1 and "srcdoc=" in html and "gds-lens" in html
    assert 'width="700"' in html and 'height="400"' in html


def test_the_part_colour_it_was_given_reaches_the_view(tmp_path):
    model = GDSModel(str(docs_device_gds(tmp_path)), cell_name="straight_pn")
    model.layer_stack = normalize_layer_stack({"49/0": {"name": "Pad metal", "color": "#123456"}})
    lyp = model.layout_lyp()
    assert "#123456" in lyp and "Pad metal" in lyp
    assert "#123456" in model.layout_view().html


def test_a_part_with_no_file_source_has_no_layout_view(tmp_path):
    gds = docs_device_gds(tmp_path)

    class Live:                                   # a live component: it writes a GDS, it is not one
        def write_gds(self, path):
            Path(path).write_bytes(gds.read_bytes())

    with pytest.raises(ValueError, match="needs an imported GDS file"):
        GDSModel(Live()).layout_view()


@needs_chrome
def test_a_saved_preview_loads_from_a_web_origin(tmp_path):
    out = tmp_path / "preview.html"
    GDSModel(str(docs_device_gds(tmp_path)), cell_name="straight_pn").layout_view().save(out)
    assert json.loads(capture_over_http(out.read_text(encoding="utf-8"), tmp_path))["ok"]


def test_a_file_with_several_top_cells_shows_the_cell_the_part_uses(tmp_path):
    """No cell_name: the part takes the top cell with the most geometry (B), so the view must draw B, not every
    top cell (final review, finding 3)."""

    from gds_layout_fixtures import two_tops_gds

    model = GDSModel(str(two_tops_gds(tmp_path)))
    assert model.layout_cell() == "B"
    assert '"cell": "B"' in model.layout_view().html
