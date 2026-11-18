"""A one-file layout page: GDS Lens and the GDS bytes inside one HTML file. It needs no network and no web server:
opened from disk (file://), where Chrome starts no worker from a blob URL, the page's host starts GDS Lens's parse
worker from a data: URL."""

from __future__ import annotations

import json

import pytest

from optodraw.gds import layout_html
from optodraw.renderers.capture3d import find_chrome

from gds_layout_fixtures import capture_over_http, docs_device_gds

def _rgb(css: str) -> tuple[int, int, int]:
    if css.startswith("#"):
        return int(css[1:3], 16), int(css[3:5], 16), int(css[5:7], 16)
    r, g, b = (int(float(v)) for v in css[css.index("(") + 1:css.index(")")].split(",")[:3])
    return r, g, b


needs_chrome = pytest.mark.skipif(not find_chrome(required=False), reason="needs Chrome, Chromium or Edge")


def test_the_page_is_one_file_and_fetches_nothing(tmp_path):
    html = layout_html(docs_device_gds(tmp_path), title='Pads & "rib" λ')
    assert html.count('<script type="module">') == 1 and "<gds-lens" in html
    assert "<link" not in html and ' src="http' not in html          # nothing fetched from the network
    assert "<title>Pads &amp; &quot;rib&quot; λ</title>" in html


def test_the_page_is_written_when_a_filename_is_given(tmp_path):
    out = tmp_path / "page.html"
    html = layout_html(docs_device_gds(tmp_path), filename=out)
    assert out.read_text(encoding="utf-8") == html


@needs_chrome
def test_the_page_loads_from_a_local_server_with_no_network(tmp_path):
    out = json.loads(capture_over_http(layout_html(docs_device_gds(tmp_path), stack="gdsfactory_generic"), tmp_path))
    assert out["ok"] and out["layers"] >= 10 and out["polygons"] > 0
    assert _rgb(out["colors"]["49/0"]) == (0x7D, 0x66, 0x08)          # M3's colour from the stack (GDS Lens adds alpha)


