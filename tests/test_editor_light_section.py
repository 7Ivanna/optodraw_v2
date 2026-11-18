"""The inspector's Light section in a real editor page (headless Chrome): the knob sits where its number says, a
click on the slider reaches the server and rebuilds the 3D view, a value off the range is said and pinned, the
controls are fetched again after a scene change, and Undo brings the previous value back. With the light on, an edit
moves the 3D view first and then builds the light; a scene saved with a look opens in it."""

from __future__ import annotations

import json
import socket
import threading
import time
import urllib.request

import pytest

pytest.importorskip("fastapi")
uvicorn = pytest.importorskip("uvicorn")

from optodraw.renderers.capture3d import _Pipe, find_chrome  # noqa: E402

pytestmark = pytest.mark.skipif(not find_chrome(required=False), reason="needs Chrome, Chromium or Edge")
FILTER = "5th-order filter"
RING1 = "coupledringfilter1:ring1"


class Editor:
    """A scratch editor server and a headless page on it."""

    def __init__(self, base: str, pipe: _Pipe):
        self.base, self.pipe = base, pipe
        target = pipe.call("Target.createTarget", {"url": "about:blank"})["targetId"]
        self.session = pipe.call("Target.attachToTarget", {"targetId": target, "flatten": True})["sessionId"]
        pipe.call("Page.enable", session=self.session)

    def api(self, method: str, path: str, body: dict | None = None):
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(self.base + path, data=data, method=method,
                                         headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=120) as reply:
            return json.loads(reply.read())

    def js(self, expression: str):
        result = self.pipe.call("Runtime.evaluate", {"expression": expression, "returnByValue": True,
                                                     "awaitPromise": True}, self.session)
        if "exceptionDetails" in result:
            raise AssertionError(result["exceptionDetails"])
        return result.get("result", {}).get("value")

    def wait(self, expression: str, seconds: float = 40.0):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            value = self.js(expression)
            if value:
                return value
            time.sleep(0.3)
        raise AssertionError(f"timed out waiting for {expression}")

    def click(self, x: float, y: float) -> None:
        for kind in ("mousePressed", "mouseReleased"):
            self.pipe.call("Input.dispatchMouseEvent", {"type": kind, "x": x, "y": y, "button": "left", "clickCount": 1},
                           self.session)

    def open_filter(self) -> None:
        self.pipe.call("Page.navigate", {"url": self.base + "/"}, self.session)
        self.wait(f"!!document.querySelector('[data-component-id=\"{FILTER}\"]')")
        self.js("document.querySelectorAll('.welcome, #welcome').forEach(e => e.hidden = true)")
        rect = self.js(f"(() => {{ const r = document.querySelector('[data-component-id=\"{FILTER}\"]')"
                       ".getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2]; })()")
        self.click(*rect)
        self.wait("!!document.querySelector('.light-row')")

    def row(self, key: str) -> str:
        return f"document.querySelector('.light-row[data-key=\"{key}\"]')"

    def knob(self, key: str) -> dict:
        return self.js(f"(() => {{ const e = {self.row(key)}.querySelector('input'); const r = e.getBoundingClientRect();"
                       "return {value: Number(e.value), min: Number(e.min), max: Number(e.max), left: r.left, width: r.width,"
                       f"y: r.top + r.height / 2, text: {self.row(key)}.querySelector('.light-val').textContent}}; }})()")

    def click_at_fraction(self, key: str, fraction: float) -> None:
        """A real mouse click where the knob of a native slider (16 px wide) is at ``fraction`` of the range."""

        k = self.knob(key)
        self.click(k["left"] + 8 + fraction * (k["width"] - 16), k["y"])


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
    base = f"http://127.0.0.1:{port}"
    folder = tmp_path_factory.mktemp("chrome")
    pipe = _Pipe(find_chrome(), folder / "profile", 1500, 1000)
    try:
        yield Editor(base, pipe)
    finally:
        pipe.close()
        server.should_exit = True
        thread.join(timeout=10)
        os.environ.pop("OPTODRAW_WORKSPACE_DIR", None)


@pytest.fixture()
def page(editor):
    editor.api("POST", "/api/scene/new", {})
    editor.api("POST", "/api/scene/preset", {"name": "ring_resonator_chip"})
    editor.open_filter()
    return editor


def test_undo_brings_the_previous_light_value_back(page):
    page.click_at_fraction(f"heater:{RING1}", 0.25)
    page.wait("!document.getElementById('btn-undo').disabled")
    assert page.api("GET", "/api/scene/download")["metadata"]["animation"]["params"]
    page.js("document.getElementById('btn-undo').click()")
    page.wait("document.getElementById('btn-undo').disabled")
    animation = page.api("GET", "/api/scene/download").get("metadata", {}).get("animation", {})
    assert not animation.get("params")
    assert page.knob(f"heater:{RING1}")["value"] == 0.0         # the inspector shows the restored value


