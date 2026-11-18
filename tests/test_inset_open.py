"""A scene inset opens in the editor: the session holds its scene, autosave keeps the page, and on the way back the
inset draws again from the changed scene."""

from __future__ import annotations

import json

import pytest

pytest.importorskip("fastapi")

from optodraw import Inset, Laser, Mirror, Scene
from optodraw.app.session import EditorSession
from optodraw.figure.page import Page

SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 20">'
       '<rect width="40" height="20" fill="#cccccc"/></svg>')


def _bench(title: str = "Bench") -> Scene:
    scene = Scene(title=title, width=120, height=40)
    scene.add(Laser(center=(-40, 0), label="Laser"))
    scene.add(Mirror(center=(20, 0), angle=45, label="M1"))
    return scene


def _page(tmp_path, *, inner: bool = False) -> dict:
    (tmp_path / "a.svg").write_text(SVG, encoding="utf-8")
    page = Page(width_mm=183, height_mm=120, font_pt=7.0)
    bench = _bench()
    if inner:                                       # the bench holds a scene inset of its own
        bench.add(Inset(_bench("Detail"), center=(0, 30), width=40, label="detail"))
    page.add(Inset(bench, center=(60, 60), width=100, label="bench"))
    page.add(Inset(str(tmp_path / "a.svg"), center=(150, 60), width=40, label="picture"))
    page.save(tmp_path / "page.json")
    return json.loads((tmp_path / "page.json").read_text(encoding="utf-8"))


def _of(spec, **match):
    return next(e for e in spec["components"] if all(e.get(k) == v for k, v in match.items()))


class _Store:
    """A workspace store that keeps the last spec saved."""

    def __init__(self):
        self.saved = None

    def save(self, name, spec):
        self.saved = json.loads(json.dumps(spec))


def test_a_scene_inset_opens_as_its_scene(tmp_path):
    session = EditorSession(_page(tmp_path))
    bench = _of(session.spec, label="bench")
    session.open_inset(bench["id"])
    assert sorted(e["type"] for e in session.spec["components"]) == ["Laser", "Mirror"]
    assert [level.get("id") for level in session.path] == [None, bench["id"]]
    assert session.path[1]["name"] == "bench"


def test_only_a_scene_inset_opens(tmp_path):
    session = EditorSession(_page(tmp_path))
    with pytest.raises(ValueError, match="SVG file"):
        session.open_inset(_of(session.spec, label="picture")["id"])
    with pytest.raises(KeyError):
        session.open_inset("nothing_here")
    assert len(session.path) == 1


def test_a_scene_kept_as_a_drawing_only_does_not_open(tmp_path):
    spec = _page(tmp_path)
    _of(spec, label="bench")["source"] = {"kind": "SceneView"}                  # frozen: the record kept no scene
    session = EditorSession(spec)
    with pytest.raises(ValueError, match="drawing only"):
        session.open_inset(_of(spec, label="bench")["id"])


def test_a_part_is_not_an_inset(tmp_path):
    session = EditorSession(_page(tmp_path))
    session.open_inset(_of(session.spec, label="bench")["id"])
    with pytest.raises(ValueError, match="only an inset opens"):
        session.open_inset(_of(session.spec, type="Mirror")["id"])


# -- the routes -------------------------------------------------------------- #


@pytest.fixture()
def client(tmp_path):
    from fastapi.testclient import TestClient

    from optodraw.app.server import create_app

    client = TestClient(create_app())
    assert client.post("/api/workspaces", json={"name": tmp_path.name}).status_code == 200
    return client


def _saved():
    from optodraw.app import api

    return api._store.workspaces.load(api._store.current)


def test_the_routes_open_and_go_back(client, tmp_path):
    client.post("/api/scene", json={"spec": _page(tmp_path)})
    bench = _of(client.get("/api/scene").json(), label="bench")
    opened = client.post("/api/scene/inset/open", json={"id": bench["id"]}).json()
    assert [level.get("id") for level in opened["path"]] == [None, bench["id"]]
    assert sorted(e["type"] for e in opened["spec"]["components"]) == ["Laser", "Mirror"]
    assert client.get("/api/render/svg").json()["path"] == opened["path"]
    back = client.post("/api/scene/inset/close", json={"depth": 0}).json()
    assert len(back["path"]) == 1 and _of(back["spec"], label="picture")


def test_a_refused_open_says_why(client, tmp_path):
    client.post("/api/scene", json={"spec": _page(tmp_path)})
    picture = _of(client.get("/api/scene").json(), label="picture")
    response = client.post("/api/scene/inset/open", json={"id": picture["id"]})
    assert response.status_code == 400 and "SVG file" in response.text
    assert client.post("/api/scene/inset/open", json={"id": "nothing"}).status_code == 404
    assert client.post("/api/scene/inset/close", json={}).status_code == 400                # no inset is open


def test_a_preset_waits_for_the_way_back(client, tmp_path):
    spec = _page(tmp_path)
    client.post("/api/scene", json={"spec": spec})
    client.post("/api/scene/inset/open", json={"id": _of(spec, label="bench")["id"]})
    name = client.get("/api/workspaces").json()["presets"][0]
    name = name if isinstance(name, str) else name["name"]
    response = client.post("/api/scene/preset", json={"name": name})         # it would replace the whole page
    assert response.status_code == 409 and "go back" in response.text
    assert len(client.get("/api/render/svg").json()["path"]) == 2 and _of(_saved(), label="picture")


def _zoomed(tmp_path) -> dict:
    (tmp_path / "a.svg").write_text(SVG, encoding="utf-8")
    page = Page(width_mm=183, height_mm=120, font_pt=7.0)
    bench = page.add(Inset(_bench(), center=(60, 60), width=100, label="bench"))
    picture = page.add(Inset(str(tmp_path / "a.svg"), center=(150, 60), width=40, label="picture"))
    page.zoom(bench, (-45, -3, -35, 3), picture)                                 # a box on the laser
    page.save(tmp_path / "page.json")
    return json.loads((tmp_path / "page.json").read_text(encoding="utf-8"))


def test_a_save_of_a_page_that_does_not_build_keeps_the_old_drawing(tmp_path):
    from optodraw.schema import scene_from_spec

    session = EditorSession(_zoomed(tmp_path))
    before = _of(session.spec, label="bench")
    session.open_inset(before["id"])
    session.delete(_of(session.spec, type="Laser")["id"])
    whole = session.whole_spec()
    scene_from_spec(whole)                                                       # it opens again
    kept = _of(whole, label="bench")
    assert kept["fragment"] == before["fragment"] and [e["type"] for e in kept["source"]["scene"]["components"]] == \
        ["Mirror"]


def test_an_emptied_scene_goes_back_as_a_blank(tmp_path):
    session = EditorSession(_page(tmp_path))
    before = _of(session.spec, label="bench")
    session.open_inset(before["id"])
    for entry in session.spec["components"]:
        session.delete(entry["id"])
    session.close_inset()
    after = _of(session.spec, label="bench")
    assert len(session.path) == 1 and after["source"]["scene"]["components"] == []
    assert "<path" not in after["fragment"]["svg"] and after["fragment"]["size_mm"][0] == before["fragment"]["size_mm"][0]


def test_an_empty_scene_inset_draws_a_blank_of_its_frame():
    from optodraw import Scene

    inset = Inset(Scene(title="Empty", width=120, height=40), center=(0, 0), width=60)
    assert inset.fragment().size_mm == pytest.approx((60.0, 20.0))
    assert inset.at(60, 20).xy() == pytest.approx((30.0, 10.0))                 # the frame's top right corner


def test_a_scene_that_comes_to_name_a_file_does_not_go_back(tmp_path):
    session = EditorSession(_page(tmp_path))
    session.open_inset(_of(session.spec, label="bench")["id"])
    session.update(_of(session.spec, type="Mirror")["id"], {"label": str(tmp_path / "a.svg")})
    with pytest.raises(ValueError, match="names a file"):
        session.close_inset()


def test_a_scene_with_an_unknown_part_says_it_does_not_load(client, tmp_path):
    spec = _page(tmp_path)
    _of(spec, label="bench")["source"]["scene"]["components"][0]["type"] = "NoSuchPart"
    client.post("/api/scene", json={"spec": spec})
    response = client.post("/api/scene/inset/open", json={"id": _of(spec, label="bench")["id"]})
    assert response.status_code == 400 and "does not load" in response.text


def test_a_new_scene_saves_the_page_with_the_inset_drawn_first(tmp_path):
    session, store = EditorSession(_page(tmp_path)), _Store()
    session.bind_workspace(store, "page")
    before = _of(session.spec, label="bench")
    session.open_inset(before["id"])
    session.move_component(_of(session.spec, type="Mirror")["id"], center=[30, 0])
    session.reset()
    saved = _of(store.saved, label="bench")
    assert saved["fragment"]["svg"] != before["fragment"]["svg"]
    assert _of(saved["source"]["scene"], type="Mirror")["center"] == [30.0, 0.0]


def test_a_scene_sent_for_another_level_is_refused(client, tmp_path):
    spec = _page(tmp_path)
    client.post("/api/scene", json={"spec": spec})
    inside = client.post("/api/scene/inset/open", json={"id": _of(spec, label="bench")["id"]}).json()["spec"]
    refused = client.post("/api/scene", json={"spec": inside, "edit": True, "depth": 0})
    assert refused.status_code == 409 and "reload the page" in refused.text
    assert _of(_saved(), label="picture")                                        # the page is as it was
    assert client.post("/api/scene", json={"spec": inside, "edit": True, "depth": 1}).status_code == 200
    text = client.get("/api/scene/text").json()["text"]
    assert client.post("/api/scene/text", json={"text": text, "depth": 0}).status_code == 409


