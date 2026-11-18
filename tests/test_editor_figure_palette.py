"""The Figure palette in a real editor page, in headless Chrome, as a person uses it: each entry makes its inset (a
file through the picker, a GDS view's stack and region in a dialog, a section and a 3D view from the selected GDS
view), the Inspector edits its source, a corner handle resizes it, and it saves, undoes and reloads. A large drawing
loads once and goes back to the server by its key, and a page over 16 MB names its size in the status bar."""

from __future__ import annotations

import importlib.util
import io
import json
import shutil

import pytest

pytest.importorskip("fastapi")

import test_page_views as views  # noqa: E402

from optodraw.figure.page import Page  # noqa: E402

editor = views.editor                   # the server and the headless Chrome of the page tests, one pair per module
needs_chrome = views.needs_chrome
needs_gds = pytest.mark.skipif(not all(importlib.util.find_spec(name) for name in ("gdstk", "shapely")),
                               reason="needs gdstk and shapely")
needs_poppler = pytest.mark.skipif(shutil.which("pdftocairo") is None, reason="needs pdftocairo")

SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 20"><rect width="40" height="20" fill="#cccccc"/>'
       '<text x="2" y="10">drop me</text></svg>')
KINDS = {"Text": "Text", "Equation": "Equation", "Picture": "Image", "SVG file": "SvgFile", "PDF file": "PdfFile",
         "Scene inset": "SceneView", "Copy of this scene": "SceneView", "Timing": "Timing", "GDS view": "GdsView",
         "Section": "SectionView", "3D view": "View3D"}
# The Inspector's source field of each entry, what a person types there, and the record value it gives.
EDITS = {
    "Text": ("Text", "one two three", "text", "one two three"),
    "Equation": ("Formula (mathtext)", "a^2 + b^2", "latex", "a^2 + b^2"),
    "Picture": ("Kind", "drawn", "image_kind", "drawn"),
    "SVG file": ("Drop text", "drop me", "drop_text", ["drop me"]),
    "PDF file": ("Page", "2", "page", 2),
    "Scene inset": ("View", "1d", "view", "1d"),
    "Copy of this scene": ("View", "1d", "view", "1d"),
    "Timing": ("Span (start, end)", "0, 8", "span", [0, 8]),
    "GDS view": ("Region x0, y0, x1, y1 (µm)", "-5, -5, 5, 5", "region", [-5, -5, 5, 5]),
    "Section": ("Height scale (auto or a number)", "2", "z_scale", 2),
    "3D view": ("Projection", "parallel", "projection", "parallel"),
}


def _page() -> dict:
    return json.loads(json.dumps(Page(width_mm=183, height_mm=120, font_pt=7.0).to_spec()))


def _png(tmp_path, size=(40, 20), noise=False):
    import numpy as np
    from PIL import Image

    pixels = (np.random.default_rng(0).integers(0, 256, (size[1], size[0], 3), dtype=np.uint8) if noise
              else np.full((size[1], size[0], 3), (200, 40, 40), dtype=np.uint8))
    out = io.BytesIO()
    Image.fromarray(pixels).save(out, format="PNG")
    path = tmp_path / ("noise.png" if noise else "red.png")
    path.write_bytes(out.getvalue())
    return path


def _svg(tmp_path):
    path = tmp_path / "drawing.svg"
    path.write_text(SVG, encoding="utf-8")
    return path


def _pdf(tmp_path):
    from matplotlib.backends.backend_pdf import PdfPages
    from matplotlib.figure import Figure

    with PdfPages(tmp_path / "two.pdf") as pdf:
        for page in (1, 2):
            figure = Figure(figsize=(2, 1 + page))
            figure.text(0.5, 0.5, f"page {page}")
            pdf.savefig(figure)
    return tmp_path / "two.pdf"


def _gds(tmp_path):
    import gdstk

    lib = gdstk.Library()
    lib.new_cell("TOP").add(gdstk.rectangle((-10, -0.25), (10, 0.25), layer=1),
                            gdstk.rectangle((-10, -3), (10, 3), layer=3))
    lib.write_gds(tmp_path / "wg.gds")
    return tmp_path / "wg.gds"


FILES = {"Picture": _png, "SVG file": _svg, "PDF file": _pdf, "GDS view": _gds}


ENTRIES = ["Text", "Equation", "Picture", "SVG file", pytest.param("PDF file", marks=needs_poppler), "Scene inset",
           "Copy of this scene", "Timing", pytest.param("GDS view", marks=needs_gds),
           pytest.param("Section", marks=needs_gds), pytest.param("3D view", marks=needs_gds)]


