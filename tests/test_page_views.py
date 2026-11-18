"""A page in the editor: a click anywhere in an inset's box picks it, the 1D and 3D views name the insets they leave
out, the 1D view has no export button of its own (the Export menu has it), the right panel folds, the Code tab edits
the scene as text, and a double-click opens a scene inset. The last group drives a real editor page in headless
Chrome, as a person does."""

from __future__ import annotations

import json
import socket
import threading
import time
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from optodraw.app.session import EditorSession
from optodraw.figure import Inset, Page

STATIC = Path(__file__).resolve().parents[1] / "optodraw" / "app" / "static"
CORNER = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 20">'
          '<rect width="4" height="4" fill="#cccccc"/></svg>')      # ink in one corner: the middle of the box is blank


def _saved_page(tmp_path) -> dict:
    (tmp_path / "corner.svg").write_text(CORNER, encoding="utf-8")
    page = Page(width_mm=183, height_mm=120, font_pt=7.0)
    page.add(Inset(str(tmp_path / "corner.svg"), center=(60, 60), width=80, label="spectrum"))
    page.add(Inset(str(tmp_path / "corner.svg"), center=(150, 60), width=40))
    page.save(tmp_path / "page.json")
    return json.loads((tmp_path / "page.json").read_text(encoding="utf-8"))


def test_the_3d_page_carries_the_note(tmp_path):
    html = EditorSession(_saved_page(tmp_path)).scene().render_threejs(editable=True)
    assert json.dumps("Not in 3D: 2 insets (spectrum, SVG file). An inset draws in the 2D view only.") in html


def test_the_1d_view_has_no_export_button_of_its_own():
    assert "od1-export" not in (STATIC / "js" / "view1d.js").read_text(encoding="utf-8")


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

    def open(self, spec: dict) -> None:
        import urllib.request

        body = json.dumps({"spec": spec, "whole": True}).encode()             # from the page, if a test left an inset open
        request = urllib.request.Request(self.base + "/api/scene", data=body, method="POST",
                                         headers={"Content-Type": "application/json"})
        urllib.request.urlopen(request, timeout=120).read()
        self.pipe.call("Page.navigate", {"url": self.base + "/"}, self.session)
        self.wait("document.querySelectorAll('[data-component-id]').length >= 2")
        self.js("document.querySelectorAll('.welcome, #welcome').forEach(e => e.hidden = true)")

    def click(self, x: float, y: float, count: int = 1) -> None:
        for n in range(1, count + 1):
            for kind in ("mouseMoved", "mousePressed", "mouseReleased"):
                self.pipe.call("Input.dispatchMouseEvent", {"type": kind, "x": x, "y": y, "button": "left",
                                                            "clickCount": n, "buttons": int(kind == "mousePressed")},
                               self.session)

    def middle_of(self, component_id: str) -> list[float]:
        """The part's own centre on the screen (its group's origin), not the middle of its ink."""

        return self.js(f"(() => {{ const m = document.querySelector('[data-component-id=\"{component_id}\"]')"
                       ".getScreenCTM(); return [m.e, m.f]; })()")

    def server_spec(self) -> dict:
        return self.js("fetch('/api/scene').then((r) => r.json())")


@pytest.fixture(scope="module")
def editor(tmp_path_factory):
    from optodraw.app.server import create_app

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
    pipe = _Pipe(find_chrome(), tmp_path_factory.mktemp("chrome") / "profile", 1500, 950)
    try:
        yield Editor(f"http://127.0.0.1:{port}", pipe)
    finally:
        pipe.close()
        server.should_exit = True
        thread.join(timeout=10)


@needs_chrome
def test_the_2d_light_never_shows_the_click_area_of_a_beam(editor):
    from optodraw import Beam, Laser, Mirror, Photodiode, Scene

    scene = Scene(width=120, height=60)
    laser, mirror = scene.add(Laser(center=(-40, 0))), scene.add(Mirror(center=(20, 0), angle=45))
    scene.add(Beam.through(laser, mirror, scene.add(Photodiode(center=(20, 30), angle=-90)), wavelength=633))
    editor.open(scene.to_spec())
    editor.wait("!!document.querySelector('#canvas [data-component-id] [style*=\"dasharray\"]')")     # the light runs
    shown = editor.js("[...document.querySelectorAll('#canvas [data-component-id] [opacity]')]"
                      ".filter((el) => Number(el.getAttribute('opacity')) === 0 && el.getAttribute('style')).length")
    assert shown == 0                     # the wide click area of a beam (opacity 0) keeps its own look: no black dashes


@needs_chrome
def test_the_editor_1d_view_turns_wires_sharp_and_bends_waveguides(editor):
    import runpy

    # the homodyne receiver: wires to pads and waveguides, and a 1D view that builds at once on a loaded machine
    scene = runpy.run_path(str(Path(__file__).resolve().parents[1] / "docs/examples/electronics/01-homodyne.py"))["scene"]
    editor.open(json.loads(json.dumps(scene.to_spec())))
    editor.js("document.getElementById('btn-view-1d').click()")
    editor.wait("document.querySelectorAll('#view1d path.od1-wire').length > 5")
    paths = editor.js("[...document.querySelectorAll('#view1d path.od1-wire')]"
                      ".map(p => [p.classList.contains('electrical'), p.getAttribute('d')])")
    wires = [d for electrical, d in paths if electrical]
    guides = [d for electrical, d in paths if not electrical]
    assert any(d.count("L") >= 2 for d in wires)                 # wires with corners exist
    assert not any("Q" in d for d in wires)
    assert any("Q" in d for d in guides)


@needs_chrome
def test_the_editor_1d_view_dots_each_join_of_a_node(editor):
    import runpy

    scene = runpy.run_path(str(Path(__file__).resolve().parents[1] / "docs/examples/electronics/02-tia.py"))["scene"]
    editor.open(json.loads(json.dumps(scene.to_spec())))
    editor.js("document.getElementById('btn-view-1d').click()")
    editor.wait("document.querySelectorAll('#view1d path.od1-wire').length > 5")
    model = editor.js("fetch('/api/scene/1d/model').then((r) => r.json())")
    dots = editor.js("[...document.querySelectorAll('#view1d circle.od1-junction')].map(c => [c.getAttribute('cx'), c.getAttribute('cy')])")
    assert len(model["junctions"]) == 4 and len(dots) == 4


