"""The editor carries the 3D view's controls outside the view: a View menu (camera, world, table colour, labels,
fullscreen, photoreal) next to Animate, and the 3D exports in the Export menu. The page inside the editor draws
no controls; 3D labels have their own setting, off by default, apart from the 2D labels."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

ROOT = Path(__file__).resolve().parents[1] / "optodraw"
STATIC = ROOT / "app" / "static"


def _script() -> str:
    return (STATIC / "js" / "app.js").read_text(encoding="utf-8")


def test_the_toolbar_has_a_view_menu_next_to_animate():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    button = re.search(r'<button[^>]*id="btn-view3d-menu"[^>]*>.*?</button>', html, re.S)
    assert button and 'aria-haspopup="true"' in button.group(0)
    assert html.index('id="btn-animate-menu"') < html.index('id="btn-view3d-menu"') < html.index('id="view3d-menu"')


def test_the_view_menu_drives_the_page_and_survives_a_reload():
    source = _script()
    menu = re.search(r"function buildView3dMenu\(\).*?\n}\n", source, re.S)
    assert menu, "no buildView3dMenu"
    for name in ("isometric", "top", "front", "side", "cross_section", "free_space_table", "light", "dark", "none"):
        assert f'"{name}"' in source, name
    for action in ("camera", "world", "table", "labels", "fullscreen", "photoreal"):
        assert f'"{action}"' in menu.group(0), action
    assert '"optodraw-view"' in source
    assert "syncViewTo3d();" in source                    # world and table colour come back after a reload


def test_the_export_menu_has_the_3d_exports():
    source = _script()
    for label in ("3D image (PNG)", "3D image, transparent", "3D model (GLB)", "3D page (HTML)"):
        assert label in source, label


def test_the_bridge_runs_every_view_action():
    bridge = (ROOT / "renderers" / "js" / "editor_bridge.js").read_text(encoding="utf-8")
    assert "'optodraw-view'" in bridge
    for action, call in (("camera", "applyCameraPreset"), ("world", "applyWorld"), ("labels", "setLabels"),
                         ("fullscreen", "odToggleFullscreen"), ("photoreal", "odStartRender"),
                         ("png", "downloadPngScreenshot"), ("json", "downloadSceneJson"), ("table", "tableMat")):
        assert f"'{action}'" in bridge and call in bridge, action


@pytest.fixture()
def client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("OPTODRAW_WORKSPACE_DIR", str(tmp_path))
    from optodraw.app.server import create_app

    return TestClient(create_app())


def test_the_editor_page_has_no_controls_and_the_export_page_has_the_bar(client):
    client.post("/api/component", json={"name": "Laser", "params": {"center": [0, 0]}})
    editable = client.get("/api/render/threejs", params={"editable": 1}).text
    assert 'id="od-bar"' not in editable and 'id="info"' not in editable
    standalone = client.get("/api/render/threejs").text
    assert 'id="od-bar"' in standalone


def test_3d_labels_start_off_and_have_their_own_setting(client):
    client.post("/api/component", json={"name": "Laser", "params": {"center": [0, 0], "label": "Pump"}})
    pressed = r'<button[^>]*id="btn-labels"[^>]*aria-pressed="(\w+)"'
    assert re.search(pressed, client.get("/api/render/threejs").text).group(1) == "false"
    assert client.patch("/api/scene/meta", json={"show_labels_3d": True}).status_code == 200
    assert re.search(pressed, client.get("/api/render/threejs").text).group(1) == "true"
    scene = client.get("/api/scene").json()
    assert scene.get("spec", scene).get("show_labels", True) is not False      # 2D labels untouched


def test_a_click_in_the_3d_view_closes_the_open_menus():
    # a click inside the frame never reaches the editor's document; the editor's window loses focus instead
    source = _script()
    assert re.search(r'window\.addEventListener\("blur", \(\) => \{[^}]*toggleView3dMenu\(false\)[^}]*toggleAnimMenu\(false\)', source)


def test_every_export_entry_is_a_full_action():
    # an extra comma left a hole in the array; the menu then failed in the browser, not in a text check
    import json
    import shutil
    import subprocess

    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    source = _script()
    start = source.index("const EXPORT_ACTIONS = [")
    end = source.index("\n];\n", start) + 3
    body = source[start:end].replace("const EXPORT_ACTIONS =", "const actions =")
    probe = ("const withStatus = () => {}, in3dThen = () => {}, post3d = () => {}, openFigure = () => {};\n" + body +
             "\nconsole.log(JSON.stringify(Array.from(actions, (a) => a ? [a.label, typeof a.run] : null)));")
    out = subprocess.run([node, "-e", probe], capture_output=True, text=True, check=True).stdout
    entries = json.loads(out)
    assert None not in entries
    assert all(kind == "function" for _, kind in entries)


def test_the_inspector_has_a_light_section_in_place_of_the_animation_section():
    props = (STATIC / "js" / "properties.js").read_text(encoding="utf-8")
    assert 'addSection(formEl, "Light")' in props
    assert 'addSection(formEl, "Animation")' not in props and "anim_params" not in props
    assert "/light`" in props and "{ light:" in props                 # the controls come from, and go to, the server
    assert "Math.PI" not in props                                     # no physics in JavaScript
