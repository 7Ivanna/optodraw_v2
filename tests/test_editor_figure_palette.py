"""The Figure palette in a real editor page, in headless Chrome, as a person uses it: each entry makes its inset (a
file through the picker, a GDS view's stack and region in a dialog, a section and a 3D view from the selected GDS
view), the Inspector edits its source, a corner handle resizes it, and it saves, undoes and reloads. A large drawing
loads once and goes back to the server by its key, and a page over 16 MB names its size in the status bar."""

from __future__ import annotations

import importlib.util
import io
import json
import shutil
import time
import urllib.request

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


def _reload(editor) -> None:
    editor.js("window.__old = true")
    editor.pipe.call("Page.navigate", {"url": editor.base + "/"}, editor.session)
    editor.wait("!window.__old && !!document.querySelector('#canvas svg') && "
                "!!document.querySelector('.palette-item[data-figure]')")


def _open(editor, spec: dict) -> None:
    """``spec`` as the whole page in a fresh editor page, on the Inspector tab. An empty page has no part to wait
    for, so this waits for the Figure palette."""

    body = json.dumps({"spec": spec, "whole": True}).encode()
    request = urllib.request.Request(editor.base + "/api/scene", data=body, method="POST",
                                     headers={"Content-Type": "application/json"})
    urllib.request.urlopen(request, timeout=120).read()
    _reload(editor)
    editor.js("localStorage.setItem('od-welcome-hide', '1'); "
              "document.querySelectorAll('.welcome, #welcome').forEach((e) => e.hidden = true); "
              "document.getElementById('tab-inspector').click()")


def _set_files(editor, input_id: str, path) -> None:
    """``path`` chosen in the file input ``input_id``, as Chrome's own picker sets it: the change event fires."""

    node = editor.pipe.call("Runtime.evaluate", {"expression": f"document.getElementById('{input_id}')"},
                            editor.session)["result"]["objectId"]
    editor.pipe.call("DOM.setFileInputFiles", {"files": [str(path)], "objectId": node}, editor.session)


def _entry_when(editor, inset_id: str, test: str = "true") -> dict:
    """The inset as the server holds it (every drawing inline), once the JS condition ``test`` on it (``e``) holds."""

    return editor.wait(f"fetch('/api/scene').then((r) => r.json()).then((s) => {{ const e = s.components.find("
                       f"(c) => c.id === {json.dumps(inset_id)}); return e && ({test}) ? e : null; }})")


def _settled(editor) -> None:
    editor.wait("!document.getElementById('status').textContent.endsWith('…')")


def _make(editor, label: str, tmp_path, path=None) -> dict:
    """An inset made from its Figure entry: a click on the entry (a section: the context action of the selected GDS
    view), its file picked, its dialog answered. Answers the inset as the server holds it, once the editor selects
    it."""

    before = json.dumps([c["id"] for c in editor.server_spec()["components"]])
    if label == "Section":
        editor.js("[...document.querySelectorAll('#context-actions button')].find((b) => b.textContent === 'Section')"
                  ".click()")
    else:
        editor.js(f"document.querySelector('.palette-item[data-figure={json.dumps(label)}]').click()")
    if path or label in FILES:
        _set_files(editor, "file-figure", path or FILES[label](tmp_path))
    if label in ("GDS view", "Section"):
        editor.wait("!!document.querySelector('.od-modal')")
        if label == "GDS view":
            editor.js("document.getElementById('od-modal-field-0').value = 'gdsfactory_generic'; "
                      "document.getElementById('od-modal-field-1').value = '-10, -10, 10, 10'")
        editor.js("document.querySelector('.od-modal .od-primary').click()")
    made = editor.wait(f"fetch('/api/scene').then((r) => r.json()).then((s) => s.components.find((c) => "
                       f"c.type === 'Inset' && c.source.kind === '{KINDS[label]}' && !{before}.includes(c.id)) || null)")
    editor.wait(f"document.getElementById('sel-info').textContent.includes('{made['id']}')")
    _settled(editor)
    return made


def _edit(editor, label: str, typed: str) -> None:
    """``typed`` into the Inspector's source field ``label``, then the field left (its change event)."""

    field = f"document.querySelector('#props-form [aria-label={json.dumps(label)}]')"
    editor.wait(f"!!{field}")
    editor.js(f"(() => {{ const f = {field}; f.value = {json.dumps(typed)}; f.dispatchEvent(new Event('change')); }})()")


def _drag_corner(editor, dx: float, dy: float) -> None:
    """The bottom-right resize handle of the selected inset dragged by ``(dx, dy)`` px with the mouse."""

    x, y = editor.wait("(() => { const h = document.querySelectorAll('#canvas .od-resize-handle'); if (h.length !== 4) "
                       "return null; const r = h[3].getBoundingClientRect(); return [r.x + r.width / 2, "
                       "r.y + r.height / 2]; })()")

    def mouse(kind: str, px: float, py: float, buttons: int) -> None:
        editor.pipe.call("Input.dispatchMouseEvent", {"type": kind, "x": px, "y": py, "button": "left",
                                                      "buttons": buttons, "clickCount": 1}, editor.session)

    mouse("mouseMoved", x, y, 0)
    mouse("mousePressed", x, y, 1)
    for step in range(1, 6):
        mouse("mouseMoved", x + dx * step / 5, y + dy * step / 5, 1)
    mouse("mouseReleased", x + dx, y + dy, 0)


ENTRIES = ["Text", "Equation", "Picture", "SVG file", pytest.param("PDF file", marks=needs_poppler), "Scene inset",
           "Copy of this scene", "Timing", pytest.param("GDS view", marks=needs_gds),
           pytest.param("Section", marks=needs_gds), pytest.param("3D view", marks=needs_gds)]


@needs_chrome
@pytest.mark.parametrize("label", ENTRIES)
def test_each_figure_entry_is_made_edited_resized_saved_undone_and_reloaded(editor, tmp_path, label):
    from optodraw.app import api as server

    _open(editor, _page())
    if label in ("Section", "3D view"):
        _make(editor, "GDS view", tmp_path)                                      # selected once made
    made = _make(editor, label, tmp_path)
    assert made["fragment"]["svg"]                                               # mutant: the entry makes no inset
    for key in ("path", "gds"):                                                  # a picked file, kept in the workspace
        if made["source"].get(key):
            assert made["source"][key].startswith(f"files/{server._store.current}/")

    field, typed, key, value = EDITS[label]
    _edit(editor, field, typed)
    edited = _entry_when(editor, made["id"], f"JSON.stringify(e.source.{key}) === JSON.stringify({json.dumps(value)})")
    assert edited["source"][key] == value                                        # mutant: the field sends PATCH
    _settled(editor)

    width = made["width"]
    _drag_corner(editor, 60, 40)
    resized = _entry_when(editor, made["id"], f"e.width !== {width}")
    assert resized["fragment"]["width_mm"] == resized["width"]                   # mutant: a PATCH scales the old drawing
    assert not any("scaled" in note for note in resized["fragment"]["notes"])
    _settled(editor)
    saved = server._store.workspaces.load(server._store.current)
    assert next(e for e in saved["components"] if e["id"] == made["id"])["width"] == resized["width"]   # autosaved

    editor.js("document.getElementById('btn-undo').click()")
    undone = _entry_when(editor, made["id"], f"e.width === {width}")            # mutant: the resize is two undo steps
    assert undone["source"][key] == value                                        # the edit stays, the resize goes
    _settled(editor)

    _reload(editor)
    assert editor.wait(f"!!document.querySelector('[data-component-id=\"{made['id']}\"]')")
    assert _entry_when(editor, made["id"])["width"] == width


@needs_chrome
def test_a_large_drawing_loads_once_and_goes_back_by_its_key(editor, tmp_path):
    _open(editor, _page())
    editor.js("performance.clearResourceTimings(); performance.setResourceTimingBufferSize(100000)")
    made = _make(editor, "Picture", tmp_path, _png(tmp_path, (200, 200), noise=True))   # 160 KB of base64
    image = "document.querySelector('#canvas image[href^=\"/api/fragment/\"]')"
    href = editor.wait(f"{image}?.getAttribute('href')")                         # mutant: the canvas inlines the drawing
    loads = (f"performance.getEntriesByName(location.origin + {json.dumps(href)})"
             ".filter((e) => e.transferSize > 0).length")
    assert editor.wait(loads) == 1

    x = made["center"][0]
    editor.js(f"(() => {{ const f = document.querySelector('#props-form .xy-pair input[title=\"X\"]'); "
              f"f.value = '{x + 10}'; f.dispatchEvent(new Event('change')); }})()")
    _entry_when(editor, made["id"], f"e.center[0] === {x + 10}")
    _settled(editor)
    assert editor.wait(f"{image}?.getAttribute('href') === {json.dumps(href)}")   # the same drawing, the same key
    time.sleep(1.0)                                                                # a second load would land by now
    assert editor.js(loads) == 1                     # mutant: a fresh query on the href per render loads it again
    answers = editor.js("performance.getEntriesByType('resource').filter((e) => e.name.includes('/api/component/'))"
                        ".map((e) => e.encodedBodySize)")
    assert answers and max(answers) < 100_000        # mutant: the payload carries the drawing inline

    editor.js("document.getElementById('btn-undo').click()")                      # the old spec goes back with its key
    back = _entry_when(editor, made["id"], f"e.center[0] === {x}")
    assert "data:image/png;base64," in back["fragment"]["svg"]   # mutant: the client drops svg_key (409, or no drawing)


@needs_chrome
def test_a_page_over_16_mb_names_its_size_when_it_loads(editor, tmp_path):
    _open(editor, _page())
    big = _page()
    big["metadata"] = {"note": "x" * (17 * 2 ** 20)}                              # as much text as a large picture
    (tmp_path / "big.json").write_text(json.dumps(big), encoding="utf-8")
    status = "document.getElementById('status').textContent"
    _set_files(editor, "file-open", tmp_path / "big.json")
    assert "17 MB" in editor.wait(f"{status}.includes(' MB') && {status}")     # mutant: File > Open checks no size
    _reload(editor)
    assert "17 MB" in editor.wait(f"{status}.includes(' MB') && {status}")     # mutant: the boot checks no size
    _open(editor, _page())                                                        # the next test starts small
