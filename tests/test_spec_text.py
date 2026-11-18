"""The scene spec as YAML text for the editor's Code tab: the text has what the user sets, an apply is an edit, and
an error names its line."""

from __future__ import annotations

import json

import pytest
import yaml

pytest.importorskip("fastapi")

from optodraw import Callout, Inset
from optodraw.app.session import EditorSession
from optodraw.app.spec_text import SpecTextError, error_line, spec_from_text, spec_text
from optodraw.figure.page import Page

SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 20">'
       '<rect width="40" height="20" fill="#cccccc"/></svg>')


def _bench() -> EditorSession:
    session = EditorSession()
    laser = session.add_component("Laser", {"center": [-60, 0], "label": "Laser"})
    session.add_component("Mirror", {"center": [20, 0], "angle": 45, "label": "M1"})
    session.trace_from(laser)
    return session


def _page(tmp_path) -> dict:
    (tmp_path / "a.svg").write_text(SVG, encoding="utf-8")
    page = Page(width_mm=183, height_mm=120, font_pt=7.0)
    small = page.add(Inset(str(tmp_path / "a.svg"), center=(30, 100), width=50, label="small"))
    page.add(Callout("edge", center=(100, 70), target=small.at(10, 5)))
    page.save(tmp_path / "page.json")
    return json.loads((tmp_path / "page.json").read_text(encoding="utf-8"))


def _of(spec, **match):
    return next(e for e in spec["components"] if all(e.get(k) == v for k, v in match.items()))


def test_a_yaml_slip_names_its_line():
    held = _bench().spec
    lines = spec_text(held)["text"].splitlines()
    first, _ = spec_text(held)["blocks"][held["components"][1]["id"]]
    lines[first] = lines[first] + ": ["                                           # a broken line in the mirror
    with pytest.raises(SpecTextError) as caught:
        spec_from_text("\n".join(lines), held)
    assert caught.value.line in (first + 1, first + 2)


def test_text_that_is_not_a_mapping_is_refused():
    with pytest.raises(SpecTextError, match="mapping"):
        spec_from_text("- just a list", _bench().spec)


def test_an_inset_shows_without_its_source_and_drawing(tmp_path):
    held = EditorSession(_page(tmp_path)).spec
    text = spec_text(held)["text"]
    assert "fragment" not in text and "source:" not in text and "<svg" not in text
    spec = spec_from_text(text, held)
    assert spec == held                                                          # both come back by id


def test_a_file_source_in_the_text_is_refused_at_its_line(tmp_path):
    held = EditorSession(_page(tmp_path)).spec
    shown = spec_text(held)
    inset = _of(held, type="Inset")
    first, _ = shown["blocks"][inset["id"]]
    lines = shown["text"].splitlines()
    lines.insert(first, "  source: {kind: SvgFile, path: /etc/hosts}")                # a file: off the safe list
    with pytest.raises(SpecTextError, match="palette") as caught:                   # mutant: SvgFile on the list
        spec_from_text("\n".join(lines), held)
    assert caught.value.line == first


def test_a_new_inset_in_the_text_is_refused(tmp_path):
    held = EditorSession(_page(tmp_path)).spec
    spec = yaml.safe_load(spec_text(held)["text"])
    spec["components"].append({"type": "Inset", "id": "inset_new", "center": [10, 10], "width": 20})
    with pytest.raises(SpecTextError, match="Python"):
        spec_from_text(yaml.safe_dump(spec, sort_keys=False), held)


def test_the_line_of_a_part_that_does_not_build():
    held = _bench().spec
    text = spec_text(held)["text"].replace("type: Mirror", "type: Mirrror")
    spec = spec_from_text(text, held)
    first, _ = spec_text(spec)["blocks"][_of(held, type="Mirror")["id"]]
    assert error_line(spec, text) == first


def test_no_line_for_a_spec_that_builds():
    held = _bench().spec
    assert error_line(held, spec_text(held)["text"]) is None


# -- the routes -------------------------------------------------------------- #


@pytest.fixture()
def client(tmp_path):
    from fastapi.testclient import TestClient

    from optodraw.app.server import create_app

    client = TestClient(create_app())
    assert client.post("/api/workspaces", json={"name": tmp_path.name}).status_code == 200
    return client


def test_an_apply_that_does_not_build_names_the_line(client):
    client.post("/api/component", json={"name": "Laser", "params": {"center": [0, 0]}})
    client.post("/api/component", json={"name": "Mirror", "params": {"center": [30, 0]}})
    shown = client.get("/api/scene/text").json()
    mirror = next(key for key in shown["blocks"] if key.startswith("mirror"))
    response = client.post("/api/scene/text", json={"text": shown["text"].replace("type: Mirror", "type: Mirrror")})
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "Mirrror" in detail["message"] and detail["line"] == shown["blocks"][mirror][0]
    assert _of(client.get("/api/scene").json(), id=mirror)["type"] == "Mirror"          # nothing changed


def test_a_yaml_slip_through_the_route_names_the_line(client):
    response = client.post("/api/scene/text", json={"text": "title: a\nwidth: [1, 2\n"})
    assert response.status_code == 400 and response.json()["detail"]["line"] in (2, 3)


def test_a_date_stays_text_and_the_spec_stays_json():
    held = _bench().spec
    text = spec_text(held)["text"].replace("label: M1", "label: 2026-11-03")
    spec = spec_from_text(text, held)
    assert _of(spec, type="Mirror")["label"] == "2026-11-03"
    with pytest.raises(SpecTextError, match="quotes"):
        spec_from_text(spec_text(held)["text"].replace("label: M1", "label: !!binary aGVsbG8="), held)


def test_a_number_must_be_finite():
    held = _bench().spec
    for value in (".nan", ".inf", "-.inf"):
        with pytest.raises(SpecTextError, match="finite"):
            spec_from_text(spec_text(held)["text"].replace("angle: 45", f"angle: {value}"), held)


def test_an_alias_is_refused_at_its_line():
    held = _bench().spec
    text = spec_text(held)["text"].replace("label: Laser", "label: &name Laser").replace("label: M1", "label: *name")
    line = next(n for n, row in enumerate(text.splitlines(), 1) if "*name" in row)
    with pytest.raises(SpecTextError, match="alias") as caught:
        spec_from_text(text, held)
    assert caught.value.line == line


def test_an_id_used_twice_is_refused_at_its_line():
    held = _bench().spec
    laser, mirror = (_of(held, type=kind)["id"] for kind in ("Laser", "Mirror"))
    text = spec_text(held)["text"].replace(f"id: {mirror}", f"id: {laser}")
    line = next(n for n, row in enumerate(text.splitlines(), 1) if row.strip() == "- type: Mirror")
    with pytest.raises(SpecTextError, match="twice") as caught:
        spec_from_text(text, held)
    assert caught.value.line == line


def test_a_preset_with_numpy_numbers_shows_as_text():
    from optodraw.presets import build_preset

    held = EditorSession(build_preset("raman").to_spec()).spec
    text = spec_text(held)["text"]
    assert spec_from_text(text, held) == json.loads(json.dumps(held, default=float))


def test_a_label_with_a_line_break_character_reads_back():
    held = _bench().spec
    _of(held, type="Mirror")["label"] = "a\x85b SiO\u2082"
    assert _of(spec_from_text(spec_text(held)["text"], held), type="Mirror")["label"] == "a\x85b SiO\u2082"
    held2 = _bench().spec
    _of(held2, type="Mirror")["label"] = "SiO\u2082"
    assert "SiO\u2082" in spec_text(held2)["text"]                                # plain text stays readable


def test_a_child_of_a_group_gets_only_its_own_lines():
    spec = {"title": "g", "components": [{"type": "Group", "id": "group", "children": [
        {"type": "Mirror", "id": "m1", "center": [0, 0], "angle": 45},
        {"type": "Mirror", "id": "m2", "center": [10, 0], "angle": 45}]}], "routes": [], "beams": []}
    shown = spec_text(spec)
    lines = shown["text"].splitlines()
    first, last = shown["blocks"]["m1"]
    assert "id: m1" in "\n".join(lines[first - 1:last]) and "m2" not in "\n".join(lines[first - 1:last])
    assert lines[last - 1].strip() == "angle: 45"


def _figure(client) -> None:
    page = json.loads(json.dumps(Page(width_mm=183, height_mm=120, font_pt=7.0).to_spec()))
    assert client.post("/api/scene", json={"spec": page}).status_code == 200


def test_the_text_makes_a_text_and_a_timing_inset(client):
    _figure(client)
    spec = yaml.safe_load(client.get("/api/scene/text").json()["text"])
    spec["components"] += [{"type": "Inset", "id": "words", "center": [40, 100], "width": 60,
                            "source": {"kind": "Text", "text": "Hello"}},
                           {"type": "Inset", "id": "clock", "center": [100, 60], "width": 60,
                            "source": {"kind": "Timing"}}]
    response = client.post("/api/scene/text", json={"text": yaml.safe_dump(spec, sort_keys=False)})
    assert response.status_code == 200, response.text
    body = response.json()
    for name, kind in (("words", "Text"), ("clock", "Timing")):
        entry = _of(body["spec"], id=name)
        assert entry["source"]["kind"] == kind and entry["fragment"]["svg"]   # mutant: the text makes no inset
        assert entry["fragment"]["font_pt"] == 7.0                             # at the page's font
    assert "text: Hello" in body["text"] and "row: Clock" in body["text"]     # the text shows what it can edit
    assert "fragment" not in body["text"]


def test_an_unchanged_source_keeps_its_drawing_and_a_changed_one_builds():
    page = json.loads(json.dumps(Page(width_mm=183, height_mm=120, font_pt=7.0).to_spec()))
    text = yaml.safe_dump({**page, "components": [{"type": "Inset", "id": "words", "center": [40, 100],
                                                   "source": {"kind": "Text", "text": "Hello"}}]}, sort_keys=False)
    held = spec_from_text(text, page)
    words = _of(held, id="words")
    words["fragment"]["svg"] += "<!-- the drawing held -->"                    # a drawing that a build would not make
    shown = spec_text(held)["text"]
    assert spec_from_text(shown, held) == held                                 # mutant: an apply builds every inset
    changed = spec_from_text(shown.replace("text: Hello", "text: Hello there"), held)
    assert "held" not in _of(changed, id="words")["fragment"]["svg"]           # mutant: a change keeps the old drawing


def test_a_tex_equation_in_the_text_is_refused_and_runs_no_tool(monkeypatch):
    import subprocess

    ran = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: ran.append(a))
    page = json.loads(json.dumps(Page(width_mm=183, height_mm=120, font_pt=7.0).to_spec()))
    text = yaml.safe_dump({**page, "components": [{"type": "Inset", "id": "eq", "source": {
        "kind": "Equation", "latex": "\\input{/etc/hosts}", "tex": True}}]}, sort_keys=False)
    with pytest.raises(SpecTextError, match="TeX") as caught:
        spec_from_text(text, page)
    assert ran == [] and text.splitlines()[caught.value.line - 1] == "- type: Inset"


def test_a_value_that_does_not_draw_is_refused_and_the_scene_stays(client):
    client.post("/api/component", json={"name": "Mirror", "params": {"center": [0, 0], "angle": 45}})
    before = client.get("/api/scene").json()
    text = client.get("/api/scene/text").json()["text"].replace("angle: 45", "angle:")
    response = client.post("/api/scene/text", json={"text": text})
    assert response.status_code == 400 and "does not draw" in response.json()["detail"]["message"]
    assert client.get("/api/scene").json() == before
    assert client.get("/api/render/svg").status_code == 200
