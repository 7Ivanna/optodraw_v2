"""Zoom and pan stay smooth: 300 frames of camera moves driven by requestAnimationFrame. Headless Chrome draws at
60 Hz, so a frame interval is never under one frame (16.7 ms); the 95th percentile must stay under 1.25 frames (no
dropped frames) for the docs device in the editor's Layout view, and under 2 frames (33.3 ms) for about a million
distinct rectangles in a one-file page. Headless Chrome on this machine, with the GPU; a software
renderer (SwiftShader) measures the renderer, not the viewer, so it skips with the numbers."""

from __future__ import annotations

import functools
import http.server
import threading
import time
from pathlib import Path

import pytest

from gds_layout_fixtures import docs_device_gds
from test_editor_layout_view import editor, needs_chrome  # noqa: F401  (the module-scoped editor fixture)

pytestmark = [pytest.mark.slow, needs_chrome]
FRAME_MS = 1000.0 / 60.0                  # headless Chrome's requestAnimationFrame rate

MEASURE = """(async () => {
  const v = window.gdsLens;
  const cam = await v.getCamera();
  const times = [];
  await new Promise((resolve) => {
    let n = 0;
    const step = (t) => {
      times.push(t);
      const zoom = cam.zoom * Math.pow(1.02, Math.min(n, 150));
      const pan = Math.max(0, n - 150) * 5 / zoom;           // 5 px a frame once the zoom is done
      v.setCamera({ zoom, panX: cam.panX + pan, panY: cam.panY });
      n += 1;
      if (n < 300) requestAnimationFrame(step); else resolve();
    };
    requestAnimationFrame(step);
  });
  const d = times.slice(1).map((t, i) => t - times[i]).sort((a, b) => a - b);
  const gl = document.createElement("canvas").getContext("webgl2");
  const info = gl && gl.getExtension("WEBGL_debug_renderer_info");
  return { p95: d[Math.floor(d.length * 0.95)], median: d[Math.floor(d.length / 2)],
           renderer: info ? gl.getParameter(info.UNMASKED_RENDERER_WEBGL) : "unknown" };
})()"""


def _check(result: dict, limit_ms: float, what: str) -> None:
    message = f"{what}: p95 {result['p95']:.1f} ms, median {result['median']:.1f} ms, renderer {result['renderer']}"
    print(message)
    if "swiftshader" in str(result["renderer"]).lower():
        pytest.skip(f"software WebGL, not the viewer: {message}")
    assert result["p95"] < limit_ms, message


def test_the_docs_device_pans_and_zooms_smoothly_in_the_editor(editor, tmp_path):
    editor.open_with(docs_device_gds(tmp_path))
    editor.js("document.getElementById('btn-view-layout').click()")
    editor.drawn()
    _check(editor.js(MEASURE), 1.25 * FRAME_MS, "docs device, editor Layout view")


def _million_rectangles(folder: Path) -> Path:
    import gdstk

    lib = gdstk.Library()
    cell = lib.new_cell("ARRAY")
    for i in range(1000):                 # 1000 x 1000 distinct rectangles, no cell instances
        for j in range(1000):
            cell.add(gdstk.rectangle((i * 2.0, j * 2.0), (i * 2.0 + 1.2, j * 2.0 + 0.8), layer=1 + (i + j) % 4))
    path = folder / "million.gds"
    lib.write_gds(str(path))
    return path


def test_a_million_rectangles_pan_and_zoom_smoothly_in_a_page(editor, tmp_path):
    from optodraw.gds import layout_html
    from optodraw.renderers.capture3d import _Pipe, find_chrome

    page = tmp_path / "page.html"
    layout_html(_million_rectangles(tmp_path), filename=page)

    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=str(tmp_path)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    pipe = _Pipe(find_chrome(), tmp_path / "profile", 1400, 900)
    try:
        target = pipe.call("Target.createTarget", {"url": "about:blank"})["targetId"]
        session = pipe.call("Target.attachToTarget", {"targetId": target, "flatten": True})["sessionId"]
        pipe.call("Page.navigate", {"url": f"http://127.0.0.1:{server.server_address[1]}/page.html"}, session)

        def js(expression: str):
            return pipe.call("Runtime.evaluate", {"expression": expression, "returnByValue": True, "awaitPromise": True},
                             session, timeout=300).get("result", {}).get("value")

        end = time.monotonic() + 300
        while time.monotonic() < end and not js("document.getElementById('od-capture').value"):
            time.sleep(1.0)
        status = js("document.getElementById('od-capture').value")
        assert status and '"ok":true' in status, status
        _check(js(MEASURE), 2.0 * FRAME_MS, "1 000 000 rectangles, one-file page")
    finally:
        pipe.close()
        server.shutdown()
        server.server_close()
