"""A page in the editor: a click anywhere in an inset's box picks it, the 1D and 3D views name the insets they leave
out, the 1D view has no export button of its own (the Export menu has it), the right panel folds, the Code tab edits
the scene as text, and a double-click opens a scene inset. The last group drives a real editor page in headless
Chrome, as a person does."""

from __future__ import annotations

import json
import re
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


def _scene_page(tmp_path) -> dict:
    """A page with a scene inset ("bench") beside the corner picture ("spectrum")."""

    from optodraw import Laser, Mirror, Scene

    (tmp_path / "corner.svg").write_text(CORNER, encoding="utf-8")
    bench = Scene(title="Bench", width=120, height=40)
    bench.add(Laser(center=(-40, 0), label="Laser"))
    bench.add(Mirror(center=(20, 0), angle=45, label="M1"))
    page = Page(width_mm=183, height_mm=120, font_pt=7.0)
    page.add(Inset(bench, center=(60, 60), width=100, label="bench"))
    page.add(Inset(str(tmp_path / "corner.svg"), center=(60, 20), width=40, label="spectrum"))   # in view, below
    page.save(tmp_path / "page.json")
    return json.loads((tmp_path / "page.json").read_text(encoding="utf-8"))


def _editor_svg(spec: dict) -> str:
    session = EditorSession(spec)
    scene = session.scene()
    return scene.render_svg(editable=True, component_ids=session.component_id_map(scene)).as_svg()


def test_an_inset_on_the_canvas_has_a_pick_area_over_its_whole_box(tmp_path):
    svg = _editor_svg(_saved_page(tmp_path))
    picks = re.findall(r'<rect class="od-pick" x="([-\d.]+)" y="([-\d.]+)" width="([\d.]+)" height="([\d.]+)"'
                       r' fill="none" pointer-events="all"', svg)
    assert sorted((float(w), float(h)) for _, _, w, h in picks) == [(40.0, 20.0), (80.0, 40.0)]
    assert all((float(x), float(y)) == (-float(w) / 2, -float(h) / 2) for x, y, w, h in picks)


def test_an_exported_page_has_no_pick_area(tmp_path):
    page = Page(width_mm=183, height_mm=120, font_pt=7.0)
    (tmp_path / "corner.svg").write_text(CORNER, encoding="utf-8")
    page.add(Inset(str(tmp_path / "corner.svg"), center=(60, 60), width=80))
    assert "od-pick" not in page.svg()


def test_the_views_name_the_insets_they_leave_out(tmp_path):
    from optodraw.figure.inset import views_note

    scene = EditorSession(_saved_page(tmp_path)).scene()
    assert views_note(scene, "3D") == ("Not in 3D: 2 insets (spectrum, SVG file). An inset draws in the 2D view "
                                       "only.")


def test_a_scene_with_no_inset_has_no_note():
    from optodraw import Laser, Scene
    from optodraw.figure.inset import views_note

    scene = Scene(width=50, height=20)
    scene.add(Laser(center=(0, 0)))
    assert views_note(scene, "1D") == ""


def test_the_1d_model_carries_the_note(tmp_path):
    from fastapi.testclient import TestClient

    from optodraw.app.server import create_app

    client = TestClient(create_app())
    assert client.post("/api/workspaces", json={"name": tmp_path.name}).status_code == 200
    client.post("/api/scene", json={"spec": _saved_page(tmp_path)})
    model = client.get("/api/scene/1d/model").json()
    assert model["components"] == [] and model["note"].startswith("Not in 1D: 2 insets (spectrum, SVG file).")


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
def test_a_click_on_the_blank_middle_of_an_inset_selects_it(editor, tmp_path):
    spec = _saved_page(tmp_path)
    editor.open(spec)
    inset = next(e["id"] for e in spec["components"] if e.get("label") == "spectrum")
    # the inset's own centre on the screen (its group's origin), not the middle of its ink, which Chrome measures
    middle = editor.js(f"(() => {{ const m = document.querySelector('[data-component-id=\"{inset}\"]')"
                       ".getScreenCTM(); return [m.e, m.f]; })()")
    editor.click(*middle)
    assert editor.wait(f"document.getElementById('sel-info').textContent.includes('{inset}')", 10)


@needs_chrome
def test_the_1d_view_of_a_page_shows_the_note(editor, tmp_path):
    editor.open(_saved_page(tmp_path))
    editor.js("document.getElementById('btn-view-1d').click()")
    note = editor.wait("document.querySelector('#view1d .od1-note')?.textContent")
    assert note.startswith("Not in 1D: 2 insets (spectrum, SVG file).")


@needs_chrome
def test_the_3d_view_of_a_page_shows_the_note(editor, tmp_path):
    editor.open(_saved_page(tmp_path))
    editor.js("document.getElementById('btn-view-3d').click()")
    note = editor.wait("(() => { const n = document.getElementById('view3d').contentDocument"
                       "?.getElementById('od-note'); return n && !n.hidden && n.textContent; })()")
    assert note.startswith("Not in 3D: 2 insets (spectrum, SVG file).")


@needs_chrome
def test_the_right_panel_folds_and_comes_back(editor, tmp_path):
    editor.open(_saved_page(tmp_path))
    width = "document.querySelector('.properties').getBoundingClientRect().width"
    assert editor.js(width) > 200
    editor.js("document.getElementById('inspector-collapse').click()")
    assert editor.wait(f"{width} < 1", 5)
    canvas_wider = editor.js("document.getElementById('canvas').getBoundingClientRect().width")
    editor.js("document.getElementById('inspector-reveal').click()")
    assert editor.wait(f"{width} > 200", 5)
    assert editor.js("document.getElementById('canvas').getBoundingClientRect().width") < canvas_wider
    shown = "getComputedStyle(document.getElementById('{}')).display !== 'none'"
    editor.js("document.getElementById('palette-collapse').click()")              # the left panel alone folds
    assert editor.wait(shown.format("palette-reveal"), 5) and not editor.js(shown.format("inspector-reveal"))
    editor.js("document.getElementById('palette-reveal').click()")


def _code_tab(editor) -> str:
    editor.js("document.getElementById('tab-code').click()")
    return editor.wait("(() => { const t = document.getElementById('code-text'); "
                       "return t.value.includes('components:') && t.value; })()")


def _type(editor, old: str, new: str) -> None:
    editor.js(f"(() => {{ const t = document.getElementById('code-text'); t.value = t.value.replace({json.dumps(old)}, "
              f"{json.dumps(new)}); t.dispatchEvent(new Event('input')); }})()")


def _press(editor, key: str) -> None:
    editor.js(f"document.getElementById('code-text').dispatchEvent(new KeyboardEvent('keydown', "
              f"{{key: {json.dumps(key)}, ctrlKey: true, bubbles: true}}))")


@needs_chrome
def test_the_code_tab_shows_the_scene_and_the_lines_of_a_selected_part(editor, tmp_path):
    spec = _saved_page(tmp_path)
    editor.open(spec)
    text = _code_tab(editor)
    assert "label: spectrum" in text and "<svg" not in text
    inset = next(e["id"] for e in spec["components"] if e.get("label") == "spectrum")
    editor.click(*editor.middle_of(inset))
    rows = editor.wait("document.querySelectorAll('#code-gutter .sel').length")
    lines = text.splitlines()
    first = next(n for n, line in enumerate(lines, 1) if line.strip() == f"id: {inset}") - 1
    assert lines[first - 1].startswith("- type: Inset") and rows >= 4
    assert editor.js("document.querySelectorAll('#code-bands .code-band.sel').length") == 1


@needs_chrome
def test_an_apply_changes_the_scene_and_an_undo_brings_the_text_back(editor, tmp_path):
    editor.open(_saved_page(tmp_path))
    _code_tab(editor)
    _type(editor, "label: spectrum", "label: spectra")
    assert editor.js("document.getElementById('code-state').textContent") == "Not applied"
    _press(editor, "Enter")
    editor.wait("document.getElementById('code-state').textContent === 'Same as the canvas'")
    assert any(c.get("label") == "spectra" for c in editor.server_spec()["components"])
    _press(editor, "z")                                         # in the text, Ctrl+Z is the text's, not the scene's
    time.sleep(1.0)
    assert any(c.get("label") == "spectra" for c in editor.server_spec()["components"])
    editor.js("document.getElementById('btn-undo').click()")
    editor.wait("document.getElementById('code-text').value.includes('label: spectrum')")


@needs_chrome
def test_a_bad_apply_names_its_line(editor, tmp_path):
    editor.open(_saved_page(tmp_path))
    text = _code_tab(editor)
    line = next(n for n, row in enumerate(text.splitlines(), 1) if row.startswith("- type: Inset"))
    _type(editor, "- type: Inset", "- type: Insett")
    _press(editor, "Enter")
    message = editor.wait("(() => { const e = document.getElementById('code-error'); return !e.hidden && "
                          "e.textContent; })()")
    assert message.startswith(f"Line {line}:") and "Insett" in message
    assert editor.js("document.querySelector('#code-gutter .err')?.textContent") == str(line)
    assert not any(c.get("type") == "Insett" for c in editor.server_spec()["components"])


@needs_chrome
def test_a_double_click_opens_a_scene_inset_and_back_draws_it_again(editor, tmp_path):
    spec = _scene_page(tmp_path)
    editor.open(spec)
    bench = next(e for e in spec["components"] if e.get("label") == "bench")
    editor.click(*editor.middle_of(bench["id"]), count=2)
    path = editor.wait("(() => { const p = document.getElementById('inset-path'); return !p.hidden && "
                       "p.textContent; })()")
    assert "bench" in path and "Back" in path
    inside = editor.server_spec()
    assert sorted(e["type"] for e in inside["components"]) == ["Laser", "Mirror"]
    mirror = next(e for e in inside["components"] if e["type"] == "Mirror")
    assert editor.js(f"!!document.querySelector('[data-component-id=\"{mirror['id']}\"]')")
    mirror["center"] = [30, 5]                                                  # an edit inside, as the canvas sends
    editor.js(f"fetch('/api/scene', {{method: 'POST', headers: {{'Content-Type': 'application/json'}}, "
              f"body: JSON.stringify({{spec: {json.dumps(inside)}, edit: true}})}}).then((r) => r.ok)")
    editor.js("document.querySelector('#inset-path .ip-back').click()")
    editor.wait("document.getElementById('inset-path').hidden")
    after = next(e for e in editor.server_spec()["components"] if e.get("label") == "bench")
    assert after["fragment"]["svg"] != bench["fragment"]["svg"]
    assert editor.js(f"!!document.querySelector('[data-component-id=\"{bench['id']}\"]')")


@needs_chrome
def test_a_picture_inset_does_not_open_and_says_why(editor, tmp_path):
    spec = _scene_page(tmp_path)
    editor.open(spec)
    picture = next(e for e in spec["components"] if e.get("label") == "spectrum")
    editor.click(*editor.middle_of(picture["id"]), count=2)
    status = editor.wait("(() => { const s = document.getElementById('status').textContent; "
                         "return s.includes('only a scene inset opens') && s; })()")
    assert "an SVG file" in status and editor.js("document.getElementById('inset-path').hidden")


@needs_chrome
def test_the_inspector_of_an_inset_has_no_material(editor, tmp_path):
    spec = _saved_page(tmp_path)
    editor.open(spec)
    editor.js("document.getElementById('tab-inspector').click()")
    inset = next(e["id"] for e in spec["components"] if e.get("label") == "spectrum")
    editor.click(*editor.middle_of(inset))
    form = editor.wait("(() => { const f = document.getElementById('props-form'); "
                       "return !f.hidden && f.textContent.includes('Appearance') && f.textContent; })()")
    assert "Material" not in form


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


def _open_bench(editor, spec) -> dict:
    bench = next(e for e in spec["components"] if e.get("label") == "bench")
    editor.click(*editor.middle_of(bench["id"]), count=2)
    editor.wait("!document.getElementById('inset-path').hidden")
    return bench


@needs_chrome
def test_a_preset_after_emptying_an_inset_keeps_the_page(editor, tmp_path):
    from optodraw.app import api as server

    spec = _scene_page(tmp_path)
    editor.open(spec)
    page = server._store.current
    _open_bench(editor, spec)
    editor.js("document.dispatchEvent(new KeyboardEvent('keydown', {key: 'a', metaKey: true, ctrlKey: true, "
              "bubbles: true}))")
    editor.wait("document.getElementById('sel-info').textContent.includes('selected')")
    editor.js("document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Backspace', bubbles: true}))")
    editor.wait("fetch('/api/scene').then((r) => r.json()).then((s) => s.components.length === 0)")
    editor.js("document.getElementById('btn-presets').click()")
    editor.wait("!!document.querySelector('.presets-grid .welcome-ex')")
    editor.js("document.querySelector('.presets-grid .welcome-ex').click()")
    editor.wait("document.getElementById('status').textContent.includes('go back to the page first')")
    assert editor.js("document.getElementById('ws-name').textContent") == page
    kept = server._store.workspaces.load(page)                                  # the page, not the preset
    assert sorted(c.get("label") for c in kept["components"] if c["type"] == "Inset") == ["bench", "spectrum"]


@needs_chrome
def test_new_inside_an_inset_keeps_the_edit_inside_in_the_undo(editor, tmp_path):
    spec = _scene_page(tmp_path)
    editor.open(spec)
    _open_bench(editor, spec)
    _code_tab(editor)
    editor.wait("document.getElementById('code-text').value.includes('label: M1')")
    _type(editor, "label: M1", "label: M9")
    _press(editor, "Enter")
    editor.wait("document.getElementById('code-state').textContent === 'Same as the canvas'")
    editor.js("document.getElementById('btn-new').click()")
    editor.wait("fetch('/api/scene').then((r) => r.json()).then((s) => s.components.length === 0)")
    assert editor.js("document.getElementById('inset-path').hidden")
    editor.js("document.getElementById('btn-undo').click()")
    labels = editor.wait("fetch('/api/scene').then((r) => r.json()).then((s) => { const b = s.components.find("
                         "(c) => c.label === 'bench'); return b && b.source.scene.components.map((c) => c.label); })")
    assert "M9" in labels


@needs_chrome
def test_text_typed_inside_an_inset_does_not_apply_to_the_page(editor, tmp_path):
    spec = _scene_page(tmp_path)
    editor.open(spec)
    _open_bench(editor, spec)
    _code_tab(editor)
    editor.wait("document.getElementById('code-text').value.includes('label: M1')")
    _type(editor, "label: M1", "label: M9")                                     # typed, not applied
    editor.js("document.querySelector('#inset-path .ip-back').click()")
    editor.wait("document.getElementById('inset-path').hidden")
    _press(editor, "Enter")
    message = editor.wait("(() => { const e = document.getElementById('code-error'); return !e.hidden && "
                          "e.textContent; })()")
    assert "another level" in message and "Revert" in message                   # the tab's own words, before any send
    assert sorted(c.get("label") for c in editor.server_spec()["components"]) == ["bench", "spectrum"]


@needs_chrome
def test_typing_during_a_reload_of_the_text_stays(editor, tmp_path):
    editor.open(_saved_page(tmp_path))
    _code_tab(editor)
    editor.js("(() => { const plain = window.fetch; window.__plainFetch = plain; window.fetch = (url, opts) => "
              "String(url).includes('/api/scene/text') ? new Promise((done) => setTimeout(() => done(plain(url, opts)), "
              "1500)) : plain(url, opts); })()")
    editor.js("document.getElementById('code-revert').click()")                 # a slow reload starts
    _type(editor, "label: spectrum", "label: typed meanwhile")
    editor.wait("!document.getElementById('code-note').hidden")                # the slow reload has come back
    editor.js("window.fetch = window.__plainFetch")
    assert "label: typed meanwhile" in editor.js("document.getElementById('code-text').value")


@needs_chrome
def test_save_inside_an_inset_names_the_file_after_the_page(editor, tmp_path):
    spec = _scene_page(tmp_path)
    spec["title"] = "My bench page"
    editor.open(spec)
    _open_bench(editor, spec)
    editor.js("window.__saved = []; HTMLAnchorElement.prototype.click = function () { window.__saved.push(this.download); };")
    editor.js("document.getElementById('btn-save').click()")
    assert editor.wait("window.__saved.length && window.__saved[0]") == "My_bench_page.json"


@needs_chrome
def test_an_apply_that_removes_the_selected_part_clears_the_selection(editor, tmp_path):
    spec = _saved_page(tmp_path)
    editor.open(spec)
    inset = next(e["id"] for e in spec["components"] if e.get("label") == "spectrum")
    text = _code_tab(editor)
    editor.click(*editor.middle_of(inset))
    editor.wait(f"document.getElementById('sel-info').textContent.includes('{inset}')", 10)
    lines = text.splitlines()
    first = next(n for n, line in enumerate(lines) if line.strip() == f"id: {inset}") - 1
    last = next((n for n in range(first + 1, len(lines)) if lines[n].startswith("- ") or not lines[n].startswith(" ")),
                len(lines))
    block = "\n".join(lines[first:last]) + "\n"
    _type(editor, block, "")
    _press(editor, "Enter")
    editor.wait("document.getElementById('code-state').textContent === 'Same as the canvas'")
    assert editor.wait("document.getElementById('sel-info').textContent === 'No selection'", 10)


@needs_chrome
def test_the_editor_1d_view_turns_wires_sharp_and_bends_waveguides(editor):
    from optodraw import presets

    editor.open(json.loads(json.dumps(presets.wdm_delay_weight_bank_chip().to_spec())))
    editor.js("document.getElementById('btn-view-1d').click()")
    editor.wait("document.querySelectorAll('#view1d path.od1-wire').length > 10")
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


@needs_chrome
def test_the_editor_1d_view_draws_the_region_the_bracket_and_the_stage(editor):
    from test_one_d_marks import _telescope

    editor.open(json.loads(json.dumps(_telescope().to_spec())))
    editor.js("document.getElementById('btn-view-1d').click()")
    editor.wait("document.querySelectorAll('#view1d path.od1-wire').length >= 3")
    texts = editor.js("[...document.querySelectorAll('#view1d svg text')].map(t => t.textContent)")
    assert {"Telescope", "4f"} <= set(texts)
    assert editor.js("document.querySelectorAll('#view1d path.od1-mark[stroke-dasharray]').length") == 1
    assert editor.js("document.querySelectorAll('#view1d path.od1-mark').length") >= 4      # box, bracket, arrow, heads
