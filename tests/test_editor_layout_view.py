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

from gds_layout_fixtures import docs_device_gds

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
def test_deleting_the_last_gds_part_returns_to_2d(editor, tmp_path):
    gid = editor.open_with(docs_device_gds(tmp_path))
    editor.js("document.getElementById('btn-view-layout').click()")
    editor.drawn()
    editor.commit(editor.api("DELETE", f"/api/component/{gid}"))
    editor.wait("document.getElementById('view-layout').hidden && !document.getElementById('canvas').hidden")
    assert editor.js("document.getElementById('btn-view-layout').disabled")
    assert editor.js("!document.querySelector('.zoom-cluster').hidden")


def test_the_2d_canvas_cut_tool_is_gone_and_the_inspector_points_to_the_layout_view():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    canvas = (STATIC / "js" / "canvas.js").read_text(encoding="utf-8")
    props = (STATIC / "js" / "properties.js").read_text(encoding="utf-8")
    assert 'id="xs-draw"' not in html and 'id="xs-cut-ruler"' in html and 'id="xs-scan"' in html
    assert "placedCut" not in canvas and "beginRuler" not in canvas and "od-ruler" not in canvas
    assert "Draw cut on canvas" not in props and "Clear cut line" not in props and "Layout view" in props


