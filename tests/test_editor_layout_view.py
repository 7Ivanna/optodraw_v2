"""The editor's Layout view: an imported GDS in GDS Lens beside the 1D, 2D and 3D views. Static checks of the page
and the script, and a real editor page in headless Chrome."""

from __future__ import annotations

import json
import re
import socket
import threading
import time
import urllib.request
from pathlib import Path

import pytest

from gds_layout_fixtures import docs_device_gds, two_tops_gds

STATIC = Path(__file__).resolve().parents[1] / "optodraw" / "app" / "static"


def test_the_layout_button_and_view_are_in_the_page():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    button = re.search(r'<button id="btn-view-layout"[^>]*>', html)
    assert button and "disabled" in button.group(0)
    assert html.index('id="btn-view-3d"') < html.index('id="btn-view-layout"')
    assert re.search(r'<div id="view-layout"[^>]*hidden', html)


def test_the_layout_view_loads_only_the_vendored_viewer():
    from optodraw.renderers.gds_lens import GDS_LENS_VERSION

    src = (STATIC / "js" / "layout_view.js").read_text(encoding="utf-8")
    assert "/vendor/gds-lens-host.js" in src and "/vendor/gds-lens.js?v=" in src
    assert f'const GDS_LENS_VERSION = "{GDS_LENS_VERSION}"' in src
    assert "http://" not in src and "https://" not in src


# -- a real editor page ----------------------------------------------------- #

uvicorn = pytest.importorskip("uvicorn")
from optodraw.renderers.capture3d import _Pipe, find_chrome  # noqa: E402

needs_chrome = pytest.mark.skipif(not find_chrome(required=False), reason="needs Chrome, Chromium or Edge")


class Editor:
    def __init__(self, base: str, pipe: _Pipe):
        self.base, self.pipe = base, pipe
        target = pipe.call("Target.createTarget", {"url": "about:blank"})["targetId"]
        self.session = pipe.call("Target.attachToTarget", {"targetId": target, "flatten": True})["sessionId"]
        pipe.call("Page.enable", session=self.session)

    def api(self, method: str, path: str, body: dict | None = None, raw: bytes | None = None):
        data = raw if raw is not None else (None if body is None else json.dumps(body).encode())
        kind = "application/octet-stream" if raw is not None else "application/json"
        request = urllib.request.Request(self.base + path, data=data, method=method, headers={"Content-Type": kind})
        with urllib.request.urlopen(request, timeout=120) as reply:
            return json.loads(reply.read())

    def js(self, expression: str):
        result = self.pipe.call("Runtime.evaluate", {"expression": expression, "returnByValue": True,
                                                     "awaitPromise": True}, self.session)
        if "exceptionDetails" in result:
            raise AssertionError(result["exceptionDetails"])
        return result.get("result", {}).get("value")

    def wait(self, expression: str, seconds: float = 60.0):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            value = self.js(expression)
            if value:
                return value
            time.sleep(0.3)
        raise AssertionError(f"timed out waiting for {expression}")

    def open_with(self, gds: Path) -> str:
        self.api("POST", "/api/scene/new", {})
        gid = self.api("POST", f"/api/gds/import?filename={gds.name}", raw=gds.read_bytes())["id"]
        self.pipe.call("Page.navigate", {"url": self.base + "/"}, self.session)
        self.wait("!!document.getElementById('btn-view-layout') && !document.getElementById('btn-view-layout').disabled")
        self.js("document.querySelectorAll('.welcome, #welcome').forEach(e => e.hidden = true)")
        return gid

    def drawn(self) -> dict:
        return self.wait("(async () => { const v = window.gdsLens; if (!v) return null;"
                         " const rows = await v.getLayers(); if (!rows.length) return null;"
                         " return {polygons: rows.reduce((n, r) => n + (r.polygonCount || 0), 0),"
                         " top: (await v.getTopCells()).current}; })()")

    def commit(self, payload: dict) -> None:
        self.js(f"window.dispatchEvent(new CustomEvent('optodraw:scene-committed', {{detail: {{payload: {json.dumps(payload)}}}}}))")


@pytest.fixture(scope="module")
def editor(tmp_path_factory):
    import os

    from optodraw.app.server import create_app

    os.environ["OPTODRAW_WORKSPACE_DIR"] = str(tmp_path_factory.mktemp("workspaces"))
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    server = uvicorn.Server(uvicorn.Config(create_app(), host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    end = time.monotonic() + 30
    while not server.started and time.monotonic() < end:
        time.sleep(0.1)
    pipe = _Pipe(find_chrome(), tmp_path_factory.mktemp("chrome") / "profile", 1500, 1000)
    try:
        yield Editor(f"http://127.0.0.1:{port}", pipe)
    finally:
        pipe.close()
        server.should_exit = True
        thread.join(timeout=10)
        os.environ.pop("OPTODRAW_WORKSPACE_DIR", None)


@needs_chrome
def test_the_layout_view_draws_the_imported_gds(editor, tmp_path):
    editor.open_with(docs_device_gds(tmp_path))
    editor.js("document.getElementById('btn-view-layout').click()")
    assert editor.drawn()["polygons"] > 0
    assert editor.js("document.getElementById('canvas').hidden && !document.getElementById('view-layout').hidden")
    assert editor.js("document.getElementById('btn-view-layout').classList.contains('active')")
    assert editor.js("document.querySelector('.zoom-cluster').hidden")    # GDS Lens zooms on its own


@needs_chrome
def test_the_part_cell_is_the_top_drawn(editor, tmp_path):
    gid = editor.open_with(two_tops_gds(tmp_path))
    editor.commit(editor.api("PATCH", f"/api/component/{gid}", {"params": {"cell_name": "B"}}))
    editor.js("document.getElementById('btn-view-layout').click()")
    assert editor.drawn() == {"polygons": 2, "top": "B"}


@needs_chrome
def test_deleting_the_last_gds_part_returns_to_2d(editor, tmp_path):
    gid = editor.open_with(docs_device_gds(tmp_path))
    editor.js("document.getElementById('btn-view-layout').click()")
    editor.drawn()
    editor.commit(editor.api("DELETE", f"/api/component/{gid}"))
    editor.wait("document.getElementById('view-layout').hidden && !document.getElementById('canvas').hidden")
    assert editor.js("document.getElementById('btn-view-layout').disabled")
    assert editor.js("!document.querySelector('.zoom-cluster').hidden")


@needs_chrome
def test_a_part_whose_file_is_gone_shows_why(editor, tmp_path):
    gds = docs_device_gds(tmp_path)
    editor.open_with(gds)
    for stored in Path(editor.api("GET", "/api/scene")["components"][0]["source"]).parent.glob("*.gds"):
        stored.unlink()
    editor.js("document.getElementById('btn-view-layout').click()")
    text = editor.wait("(document.querySelector('#view-layout .layout-message') || {}).textContent || ''")
    assert "no file for" in text


def test_the_2d_canvas_cut_tool_is_gone_and_the_inspector_points_to_the_layout_view():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    canvas = (STATIC / "js" / "canvas.js").read_text(encoding="utf-8")
    props = (STATIC / "js" / "properties.js").read_text(encoding="utf-8")
    assert 'id="xs-draw"' not in html and 'id="xs-cut-ruler"' in html and 'id="xs-scan"' in html
    assert "placedCut" not in canvas and "beginRuler" not in canvas and "od-ruler" not in canvas
    assert "Draw cut on canvas" not in props and "Clear cut line" not in props and "Layout view" in props


@needs_chrome
def test_with_several_top_cells_and_no_cell_name_the_part_cell_is_drawn(editor, tmp_path):
    editor.open_with(two_tops_gds(tmp_path))
    editor.js("document.getElementById('btn-view-layout').click()")
    assert editor.drawn() == {"polygons": 2, "top": "B"}


def _rows(editor):
    return editor.js("(async () => (await gdsLens.getLayers()).map(r => [`${r.layer}/${r.datatype}`, r.fillColor, r.polygonCount]))()")


@needs_chrome
def test_a_new_scene_whose_part_has_the_same_id_redraws_the_view(editor, tmp_path):
    """Ids start again in each scene, so the first import of every scene is gdsmodel_1 (final review, finding 1):
    the view must follow the part's file, not only its id."""

    editor.open_with(docs_device_gds(tmp_path))
    editor.js("document.getElementById('btn-view-layout').click()")
    assert editor.drawn()["polygons"] == 232
    editor.api("POST", "/api/scene/new", {})
    gds = two_tops_gds(tmp_path)
    editor.api("POST", f"/api/gds/import?filename={gds.name}", raw=gds.read_bytes())
    editor.commit({"spec": editor.api("GET", "/api/scene")})
    editor.wait("(async () => { const r = await gdsLens.getLayers(); return r.length === 1 && r[0].polygonCount === 2; })()")


@needs_chrome
def test_a_new_layer_colour_reaches_the_open_view(editor, tmp_path):
    gid = editor.open_with(docs_device_gds(tmp_path))
    editor.js("document.getElementById('btn-view-layout').click()")
    editor.drawn()
    lyp = ('<?xml version="1.0" encoding="utf-8"?><layer-properties><properties><fill-color>#123456</fill-color>'
           '<frame-color>#123456</frame-color><name>Pad metal</name><source>49/0@1</source></properties></layer-properties>')
    request = urllib.request.Request(f"{editor.base}/api/gds/{gid}/technology?filename=t.lyp", data=lyp.encode(), method="POST")
    with urllib.request.urlopen(request, timeout=120) as reply:
        editor.commit(json.loads(reply.read()))
    editor.wait("(async () => (await gdsLens.getLayers()).some(r => r.layer === 49 && r.fillColor.startsWith('rgba(18,52,86')))()")


@needs_chrome
def test_the_old_scene_cut_is_not_drawn_on_the_new_scene_part(editor, tmp_path):
    editor.open_with(docs_device_gds(tmp_path))
    editor.js("document.getElementById('btn-view-layout').click()")
    editor.drawn()
    editor.js("[...document.querySelectorAll('#props-form button')].find(b => b.textContent.includes('Open cross-section')).click()")
    editor.wait("!document.getElementById('xs-panel').hidden && !!document.querySelector('#xs-cross svg')")
    editor.js("(async () => { await gdsLens.clearMeasurements(); await gdsLens.addMeasurement(11, 11, 11, -11); })()")
    editor.js("document.getElementById('xs-cut-ruler').click()")
    editor.wait("document.getElementById('xs-sub').textContent.startsWith('Ruler')")
    editor.api("POST", "/api/scene/new", {})
    gds = two_tops_gds(tmp_path)
    editor.api("POST", f"/api/gds/import?filename={gds.name}", raw=gds.read_bytes())
    editor.commit({"spec": editor.api("GET", "/api/scene")})
    editor.wait("(async () => { const r = await gdsLens.getLayers(); return r.length === 1; })()")
    time.sleep(1.0)
    assert editor.js("(async () => (await gdsLens.getMeasurements()).length)()") == 0


@needs_chrome
def test_keys_typed_in_the_viewer_do_not_reach_the_scene(editor, tmp_path):
    """The part is selected while the Layout view shows it; Backspace or an arrow typed in GDS Lens (its find box,
    or panning as in KLayout) deleted or moved the part (final review, finding 2)."""

    gid = editor.open_with(docs_device_gds(tmp_path))
    editor.js("document.getElementById('btn-view-layout').click()")
    editor.drawn()
    before = editor.api("GET", "/api/scene")["components"][0]["center"]
    for key in ("Backspace", "ArrowLeft", "Delete"):
        editor.js(f"document.querySelector('gds-lens').dispatchEvent(new KeyboardEvent('keydown', "
                  f"{{key: '{key}', code: '{key}', bubbles: true, composed: true}}))")
    time.sleep(2.0)
    components = editor.api("GET", "/api/scene")["components"]
    assert [c["id"] for c in components] == [gid] and components[0]["center"] == before


@needs_chrome
def test_leaving_the_layout_view_for_1d_restores_the_editor_controls(editor, tmp_path):
    editor.open_with(docs_device_gds(tmp_path))
    editor.js("document.getElementById('btn-view-layout').click()")
    editor.drawn()
    editor.js("document.getElementById('btn-view-1d').click()")
    editor.wait("!document.getElementById('view1d').hidden")
    assert editor.js("document.getElementById('view-layout').hidden && document.getElementById('xs-cut-ruler').hidden")
    assert editor.js("!document.querySelector('.zoom-cluster').hidden")
    assert editor.js("!document.getElementById('btn-view-layout').classList.contains('active')")
    assert editor.js("document.getElementById('zoom-level').textContent") != "Layout"
