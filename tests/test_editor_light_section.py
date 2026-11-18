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


def test_each_knob_sits_where_its_number_says(page):
    """Tuning 1.0 at 75 %, tuning 0.0 at 50 %, heater 15 mW at 37.5 %: the value and the drawn knob position."""

    ring = f"tuning:{RING1}"
    heater = f"heater:{RING1}"
    assert page.knob(ring)["width"] > 100                      # a track much longer than the 16 px knob
    assert page.knob(ring)["value"] == 0.0 and page.knob(heater)["value"] == 0.0
    for key, fraction, value, shown in ((ring, 0.75, 1.0, "1.0 linewidths"), (heater, 0.375, 15.0, "15.0 mW")):
        page.click_at_fraction(key, fraction)                  # the click lands where the knob must be for this value
        page.wait(f"{page.row(key)}.querySelector('.light-val').textContent.startsWith('{shown.split()[0]}')")
        k = page.knob(key)
        assert (k["value"] - k["min"]) / (k["max"] - k["min"]) == pytest.approx(fraction, abs=0.01), (key, k)
        assert k["value"] == pytest.approx(value, abs=0.06 * (k["max"] - k["min"]) / 4) and k["text"].endswith(shown.split()[1])
    # a tuning of 0 sits in the middle of -2 to 2
    mid = page.knob("tuning:coupledringfilter1:ring2")
    assert (mid["value"] - mid["min"]) / (mid["max"] - mid["min"]) == 0.5
    # the text changes on input at once; the save goes on change and lands a little later: wait for it (10 s at most)
    deadline = time.monotonic() + 10.0
    while True:
        stored = (page.api("GET", "/api/scene/download").get("metadata") or {}).get("animation", {}).get("params") or {}
        saved = abs(float(stored.get(f"heater:{RING1}", -1.0)) - 15.0) <= 0.6 and f"phase:{RING1}" in stored
        if saved or time.monotonic() > deadline:
            break
        time.sleep(0.2)
    assert stored[f"heater:{RING1}"] == pytest.approx(15.0, abs=0.6) and f"phase:{RING1}" in stored


def test_a_slider_change_reaches_the_server_and_rebuilds_the_3d_view(page):
    page.js("performance.clearResourceTimings(); performance.setResourceTimingBufferSize(2000)")   # the palette filled it
    page.js("document.getElementById('btn-animate').click()")          # the light on opens the 3D view
    page.wait("performance.getEntriesByType('resource').some(e => e.name.includes('/api/scene3d?light=1'))", 120)
    before = page.js("performance.getEntriesByType('resource').filter(e => e.name.includes('/api/scene3d?light=1')).length")
    page.click_at_fraction(f"heater:{RING1}", 0.5)
    page.wait("performance.getEntriesByType('resource').filter(e => e.name.includes('/api/scene3d?light=1')).length"
              f" > {before}", 120)
    assert page.api("GET", "/api/scene/download")["metadata"]["animation"]["params"][f"heater:{RING1}"] == pytest.approx(20.0, abs=0.6)


def test_a_value_off_the_range_is_said_and_the_knob_is_pinned_after_a_scene_change(page):
    key = f"tuning:{RING1}"
    assert page.knob(key)["value"] == 0.0
    controls = page.api("GET", f"/api/component/{FILTER.replace(' ', '%20')}/light")["controls"]
    ring = next(c for c in controls if c["key"] == key)
    spec = page.api("GET", "/api/scene/download")
    spec.setdefault("metadata", {})["animation"] = {"params": {ring["param"]: ring["resonance_rad"] + 3.0 * ring["linewidth_rad"]}}
    payload = page.api("POST", "/api/scene", {"spec": spec})
    # the page learns of the change as it does after any edit: the scene is committed
    page.js(f"window.dispatchEvent(new CustomEvent('optodraw:scene-committed', {{detail: {{payload: {json.dumps(payload)}}}}}))")
    page.wait(f"{page.row(key)}.querySelector('.light-val').textContent.includes('off range')")
    k = page.knob(key)
    assert k["value"] == k["max"] == 2.0 and k["text"].startswith("3.0 linewidths")


def test_undo_brings_the_previous_light_value_back(page):
    page.click_at_fraction(f"heater:{RING1}", 0.25)
    page.wait("!document.getElementById('btn-undo').disabled")
    assert page.api("GET", "/api/scene/download")["metadata"]["animation"]["params"]
    page.js("document.getElementById('btn-undo').click()")
    page.wait("document.getElementById('btn-undo').disabled")
    animation = page.api("GET", "/api/scene/download").get("metadata", {}).get("animation", {})
    assert not animation.get("params")
    assert page.knob(f"heater:{RING1}")["value"] == 0.0         # the inspector shows the restored value


def test_an_edit_with_the_light_on_moves_the_view_first_and_then_builds_the_light(page):
    """Minor 2 of the final review: the items come first, then the light; the status line says the light is being
    built until it comes, and the light is on at the end."""

    page.js("document.getElementById('btn-animate').click()")          # the light on opens the 3D view
    frame = "document.getElementById('view3d').contentWindow"
    page.wait(f"(() => {{ const w = {frame}; return !!(w && w.odLight && w.odLight.state.enabled); }})()", 120)
    page.js("performance.clearResourceTimings(); performance.setResourceTimingBufferSize(2000);"
            "window.__seen = []; new MutationObserver(() => window.__seen.push(document.getElementById('status')"
            ".textContent)).observe(document.getElementById('status'), {childList: true, characterData: true, subtree: true})")
    page.click_at_fraction(f"heater:{RING1}", 0.5)
    page.wait("performance.getEntriesByType('resource').some(e => e.name.includes('/api/scene3d?light=1'))", 120)
    page.wait(f"(() => {{ const w = {frame}; return w.odLight.state.enabled && "
              "!document.getElementById('status').textContent.startsWith('Building'); })()", 120)
    calls = page.js("performance.getEntriesByType('resource').filter(e => e.name.includes('/api/scene3d'))"
                    ".map(e => [e.name.includes('light=1'), e.startTime, e.responseEnd])")
    items = [c for c in calls if not c[0]]
    light = [c for c in calls if c[0]]
    assert items and light, calls
    assert items[0][1] < light[0][1] and items[0][2] <= light[0][1] + 1, calls     # the light is asked for after the items
    assert "Building the light…" in page.js("window.__seen"), page.js("window.__seen")


def test_a_saved_look_opens_in_that_look(editor):
    """Minor 1 of the final review: a scene saved with metadata.animation.look = "field" opens in the Field look."""

    editor.api("POST", "/api/scene/new", {})
    editor.api("POST", "/api/scene/preset", {"name": "ring_resonator_chip"})
    spec = editor.api("GET", "/api/scene/download")
    spec.setdefault("metadata", {})["animation"] = {"look": "field"}
    editor.api("POST", "/api/scene", {"spec": spec})
    editor.pipe.call("Page.navigate", {"url": editor.base + "/"}, editor.session)
    editor.wait(f"!!document.querySelector('[data-component-id=\"{FILTER}\"]')")
    editor.js("document.querySelectorAll('.welcome, #welcome').forEach(e => e.hidden = true)")
    editor.js("document.getElementById('btn-animate').click()")
    frame = "document.getElementById('view3d').contentWindow"
    editor.wait(f"(() => {{ const w = {frame}; return !!(w && w.odLight && w.odLight.state.enabled); }})()", 120)
    assert editor.js(f"{frame}.odLight.state.look") == "field"
    editor.js("document.getElementById('btn-animate-menu').click()")
    assert editor.js("document.querySelector('#animate-menu select').value") == "field"


def test_file_open_takes_the_saved_look_and_new_goes_back_to_light(editor):
    """Ruling 52: File > Open applies the opened scene's saved look; New starts in the default look (Light)."""

    editor.api("POST", "/api/scene/new", {})
    editor.api("POST", "/api/scene/preset", {"name": "ring_resonator_chip"})
    spec = editor.api("GET", "/api/scene/download")
    spec.setdefault("metadata", {})["animation"] = {"look": "field"}
    editor.pipe.call("Page.navigate", {"url": editor.base + "/"}, editor.session)
    editor.wait(f"!!document.querySelector('[data-component-id=\"{FILTER}\"]')")
    editor.js("document.querySelectorAll('.welcome, #welcome').forEach(e => e.hidden = true)")
    menu_look = ("(() => { document.getElementById('btn-animate-menu').click(); const v = document.querySelector("
                 "'#animate-menu select').value; document.getElementById('btn-animate-menu').click(); return v; })()")
    assert editor.js(menu_look) == "light"                           # the preset has no saved look
    editor.js("(() => { const input = document.getElementById('file-open'); const dt = new DataTransfer();"
              f"dt.items.add(new File([{json.dumps(json.dumps(spec))}], 'scene.json', {{type: 'application/json'}}));"
              "input.files = dt.files; input.dispatchEvent(new Event('change')); })()")
    editor.wait(f"{menu_look} === 'field'")
    editor.js("document.getElementById('btn-new').click()")
    editor.wait(f"!document.querySelector('[data-component-id=\"{FILTER}\"]')")
    assert editor.js(menu_look) == "light"
