"""The editor's known limits. An inset's opacity, set in the Inspector, prints on the page. A large inset drawing
outlives a server restart, so an undo step from before the restart still finds its drawing, and an undo after a
restart never writes into a workspace the tab does not show: a change that names another workspace is refused. In
Chrome, the Inspector offers an inset its opacity and no colour, and a note its colour and no opacity."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import textwrap
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

import test_editor_figure_palette as palette  # noqa: E402
import test_page_views as views  # noqa: E402

from optodraw.figure.page import Page  # noqa: E402

editor = views.editor                   # the server and the headless Chrome of the page tests, one pair per module


@pytest.fixture()
def client(tmp_path):
    from fastapi.testclient import TestClient

    from optodraw.app.server import create_app

    client = TestClient(create_app())
    assert client.post("/api/workspaces", json={"name": tmp_path.name}).status_code == 200
    page = json.loads(json.dumps(Page(width_mm=120, height_mm=80, font_pt=7.0).to_spec()))
    assert client.post("/api/scene", json={"spec": page}).status_code == 200
    return client


def _opacity(node: ET.Element) -> float:
    style = re.search(r"(?:^|;)\s*opacity\s*:\s*([0-9.]+)", node.get("style", ""))
    return float(node.get("opacity", 1.0)) * (float(style.group(1)) if style else 1.0)


def _printed_opacities(svg: str, item_id: str) -> set[float]:
    """The opacity each mark of the item ``item_id`` prints at: its own times its parents'. A mark that paints
    nothing (no fill and no stroke), such as the editor's pick box, is left out."""

    root = ET.fromstring(svg)
    parent = {child: node for node in root.iter() for child in node}
    item = next(node for node in root.iter() if node.get("data-component-id") == item_id)
    found = set()
    for mark in item.iter():
        if len(mark) or (mark.get("fill") == "none" and mark.get("stroke", "none") == "none"):
            continue
        value, at = 1.0, mark
        while at is not None:
            value, at = value * _opacity(at), parent.get(at)
        found.add(round(value, 4))
    return found


def test_an_inset_opacity_from_the_inspector_prints_on_the_page(client):
    made = client.post("/api/inset", json={"kind": "Text", "source": {"text": "a faded note"}, "center": [60, 40],
                                           "frame": True})
    assert made.status_code == 200, made.text
    inset_id, workspace = made.json()["id"], made.json()["workspace"]
    assert _printed_opacities(made.json()["svg"], inset_id) == {1.0}

    changed = client.patch(f"/api/component/{inset_id}", json={"params": {"opacity": 0.4}})   # the Inspector slider
    assert changed.status_code == 200, changed.text                       # mutant: the source takes it as an option
    assert _printed_opacities(changed.json()["svg"], inset_id) == {0.4}   # backing, words and frame: the whole inset
    assert client.post(f"/api/workspaces/{workspace}/open").status_code == 200
    assert _printed_opacities(client.get("/api/render/svg").json()["svg"], inset_id) == {0.4}   # saved with the page


PRELUDE = """
import io, json, re, sys
from fastapi.testclient import TestClient
from optodraw.app.server import create_app
client = TestClient(create_app())
given = json.loads(sys.stdin.read())
"""


def _server(root: Path, script: str, **given) -> dict:
    """One run of the editor server, in its own process, over the workspace folder ``root``. ``script`` drives it
    through ``client`` and leaves what it saw in ``out``. The next call over the same folder is a restart."""

    import optodraw

    here = str(Path(optodraw.__file__).resolve().parents[1])              # this checkout, not an installed copy
    env = {**os.environ, "OPTODRAW_WORKSPACE_DIR": str(root),
           "PYTHONPATH": os.pathsep.join(filter(None, [here, os.environ.get("PYTHONPATH")]))}
    code = PRELUDE + textwrap.dedent(script) + "\nprint(json.dumps(out))\n"
    done = subprocess.run([sys.executable, "-B", "-c", code], input=json.dumps(given), env=env, capture_output=True,
                          text=True, timeout=300)
    assert done.returncode == 0, done.stderr[-3000:]
    return json.loads(done.stdout.strip().splitlines()[-1])


BENCH = """
import numpy as np
from PIL import Image
from optodraw.figure.page import Page


def png(seed):
    out = io.BytesIO()
    Image.fromarray(np.random.default_rng(seed).integers(0, 256, (120, 120, 3), dtype=np.uint8)).save(out, "PNG")
    return out.getvalue()


def entry(spec, item_id):
    return next(e for e in spec["components"] if e.get("id") == item_id)


assert client.post("/api/workspaces", json={"name": "bench"}).status_code == 200
page = json.loads(json.dumps(Page(width_mm=120, height_mm=80).to_spec()))
assert client.post("/api/scene", json={"spec": page}).status_code == 200
first, second = (client.post("/api/files", params={"filename": f"{n}.png"}, content=png(n)).json()["path"]
                 for n in (0, 1))
made = client.post("/api/inset", json={"kind": "Image", "source": {"path": first}, "center": [60, 40], "width": 60})
made = made.json()
href = re.search(r'href="(/api/fragment/[0-9a-f]{64})"', made["svg"]).group(1)
drawn = entry(client.get("/api/scene").json(), made["id"])["fragment"]["svg"]
assert client.post(f"/api/inset/{made['id']}/source", json={"source": {"path": second}}).status_code == 200
out = {"id": made["id"], "href": href, "served": client.get(href).text, "drawn": drawn, "undo": made["spec"],
       "keyed": "svg_key" in entry(made["spec"], made["id"])["fragment"]}
"""


def test_a_large_inset_drawing_outlives_a_server_restart(tmp_path):
    before = _server(tmp_path, BENCH)
    assert before["keyed"]                                                # the drawing goes by its key, not inline
    after = _server(tmp_path, """
        served = client.get(given["href"])
        assert client.post("/api/workspaces/bench/open").status_code == 200   # the tab's page
        undo = client.post("/api/scene", json={"spec": given["undo"]})
        held = next(e for e in client.get("/api/scene").json()["components"] if e.get("id") == given["id"])
        out = {"served": [served.status_code, served.text], "undo": [undo.status_code, undo.text[:300]],
               "drawn": held["fragment"].get("svg")}
    """, href=before["href"], undo=before["undo"], id=before["id"])
    assert after["served"] == [200, before["served"]]                     # mutant: a store in memory forgets it
    assert after["undo"][0] == 200, after["undo"][1]                      # the open tab's undo, from before
    assert after["drawn"] == before["drawn"]                              # the first picture, as it was drawn


def test_after_a_restart_an_undo_never_lands_in_another_workspace(tmp_path):
    before = _server(tmp_path, """
        booted = client.get("/api/workspaces").json()["current"]
        page = client.get("/api/scene").json()
        assert client.post("/api/scene", json={"spec": {**page, "title": "first page"}}).status_code == 200
        assert client.post("/api/workspaces", json={"name": "bench"}).status_code == 200
        made = client.post("/api/component", json={"name": "Mirror", "params": {"center": [5, 5]}}).json()
        assert client.post(f"/api/component/{made['id']}/move", json={"center": [30, 5]}).status_code == 200
        out = {"booted": booted, "workspace": made["workspace"], "undo": made["spec"]}
    """)
    assert before["workspace"] == "bench"                                 # the tab shows bench
    after = _server(tmp_path, """
        undo = client.post("/api/scene", json={"spec": given["undo"]})
        assert client.post(f"/api/workspaces/{given['booted']}/open").status_code == 200
        out = {"undo": undo.status_code, "workspace": undo.json().get("workspace"),
               "title": client.get("/api/scene").json().get("title")}
    """, undo=before["undo"], booted=before["booted"])
    assert after["title"] == "first page"                # mutant: the restart opens the first workspace, the undo
    assert after["undo"] == 409 or after["workspace"] == "bench"         # overwrites it with the bench page


def test_a_change_from_a_tab_of_another_workspace_is_refused_and_writes_nothing(tmp_path):
    before = _server(tmp_path, """
        assert client.post("/api/workspaces", json={"name": "bench"}).status_code == 200
        made = client.post("/api/component", json={"name": "Mirror", "params": {"center": [5, 5]}}).json()
        assert client.post(f"/api/component/{made['id']}/move", json={"center": [30, 5]}).status_code == 200
        assert client.post("/api/workspaces", json={"name": "other"}).status_code == 200   # a second tab, saved last
        out = {"workspace": made["workspace"], "undo": made["spec"]}
    """)
    assert before["workspace"] == "bench"                                 # the first tab shows bench
    kept = (tmp_path / "other.json").read_bytes()
    after = _server(tmp_path, """
        undo = client.post("/api/scene", json={"spec": given["undo"]}, headers={"X-Optodraw-Workspace": "bench"})
        out = {"open": client.get("/api/workspaces").json()["current"], "undo": undo.status_code,
               "said": undo.json().get("detail", "")}
    """, undo=before["undo"])
    assert after["open"] == "other"                       # mutant: the restart opens the default workspace, not the last
    assert after["undo"] == 409, after["said"]            # mutant: no check, the bench page lands in other
    assert "bench" in after["said"] and "other" in after["said"]          # the message names both
    assert (tmp_path / "other.json").read_bytes() == kept


APPEARANCE = ("[...document.querySelectorAll('#props-form .insp-sec')].find((s) => "
              "s.querySelector('.insp-sec-name').textContent === 'Appearance')")
OPACITY = f"{APPEARANCE}?.querySelector('.opacity-slider input[type=range]')"
COLOURS = "document.querySelectorAll('#props-form input[type=color]').length"


@views.needs_chrome
def test_the_inspector_fades_an_inset_and_offers_it_no_colour(editor, tmp_path):
    page = json.loads(json.dumps(Page(width_mm=183, height_mm=120, font_pt=7.0).to_spec()))
    page["components"].append({"type": "Note", "id": "note_1", "text": "a note", "center": [30, 30]})
    palette._open(editor, page)
    made = palette._make(editor, "Text", tmp_path)                        # selected once made
    editor.wait(f"document.querySelector('#props-form .pt-id')?.textContent === {json.dumps(made['id'])}")
    assert editor.js(f"!!{OPACITY}")                                      # mutant: an inset gets no opacity
    assert editor.js(COLOURS) == 0                                        # mutant: a colour the server refuses
    editor.js(f"(() => {{ const r = {OPACITY}; r.value = '0.4'; r.dispatchEvent(new Event('change')); }})()")
    item = f"document.querySelector('#canvas [data-component-id={json.dumps(made['id'])}]')"
    assert editor.wait(f"{item} && getComputedStyle({item}).opacity === '0.4'", 30)   # mutant: the PATCH gets 400
    palette._settled(editor)

    editor.js("document.getElementById('tab-outline').click()")
    editor.wait("!!document.querySelector('#outline-list .ol-row[data-id=\"note_1\"]')")
    editor.js("document.querySelector('#outline-list .ol-row[data-id=\"note_1\"]').click(); "
              "document.getElementById('tab-inspector').click()")
    editor.wait("document.querySelector('#props-form .pt-id')?.textContent === 'note_1'")
    assert editor.js(COLOURS) >= 1                                        # a note takes a colour
    assert editor.js(f"!{OPACITY}")                                       # mutant: an opacity the server refuses
