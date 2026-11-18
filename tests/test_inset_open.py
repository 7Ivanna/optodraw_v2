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


def test_an_edit_inside_is_saved_in_the_page(tmp_path):
    session, store = EditorSession(_page(tmp_path)), _Store()
    session.bind_workspace(store, "page")
    session.open_inset(_of(session.spec, label="bench")["id"])
    session.move_component(_of(session.spec, type="Mirror")["id"], center=[30, 0])
    session.autosave()
    inside = _of(store.saved, label="bench")["source"]["scene"]
    assert _of(inside, type="Mirror")["center"] == [30.0, 0.0]
    assert _of(store.saved, label="picture")                                    # the page, not the bench alone


def test_going_back_draws_the_inset_again(tmp_path):
    session = EditorSession(_page(tmp_path))
    before = _of(session.spec, label="bench")
    session.open_inset(before["id"])
    session.move_component(_of(session.spec, type="Mirror")["id"], center=[30, 0])
    session.close_inset()
    after = _of(session.spec, label="bench")
    assert session.path == [{"name": "Page"}]
    assert _of(after["source"]["scene"], type="Mirror")["center"] == [30.0, 0.0]
    assert after["fragment"]["svg"] != before["fragment"]["svg"]
    assert after["fragment"]["frozen"] is False
    assert after["fragment"]["width_mm"] == before["fragment"]["width_mm"]
    assert {k: v for k, v in after.items() if k not in ("source", "fragment")} == \
        {k: v for k, v in before.items() if k not in ("source", "fragment")}


def test_open_and_back_with_no_edit_changes_nothing(tmp_path):
    session = EditorSession(_page(tmp_path))
    before = session.spec
    session.open_inset(_of(before, label="bench")["id"])
    session.close_inset()
    assert session.spec == before


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


def test_an_inset_inside_an_inset(tmp_path):
    session = EditorSession(_page(tmp_path, inner=True))
    session.open_inset(_of(session.spec, label="bench")["id"])
    detail = _of(session.spec, label="detail")
    session.open_inset(detail["id"])
    assert [level["name"] for level in session.path[1:]] == ["bench", "detail"]
    session.move_component(_of(session.spec, type="Laser")["id"], center=[-50, 0])
    session.close_inset(0)
    bench = _of(session.spec, label="bench")
    inner = _of(bench["source"]["scene"], label="detail")
    assert _of(inner["source"]["scene"], type="Laser")["center"] == [-50.0, 0.0]
    assert inner["fragment"]["svg"] != detail["fragment"]["svg"]
    assert len(session.path) == 1


def test_whole_spec_is_the_page_drawn_again_and_the_session_stays_inside(tmp_path):
    session = EditorSession(_page(tmp_path))
    before = _of(session.spec, label="bench")
    session.open_inset(before["id"])
    session.move_component(_of(session.spec, type="Mirror")["id"], center=[30, 0])
    whole = session.whole_spec()
    assert _of(whole, label="bench")["fragment"]["svg"] != before["fragment"]["svg"]
    assert len(session.path) == 2 and _of(session.spec, type="Mirror")["center"] == [30.0, 0.0]


def test_an_undo_inside_stays_inside(tmp_path):
    session = EditorSession(_page(tmp_path))
    session.open_inset(_of(session.spec, label="bench")["id"])
    older = session.spec
    session.move_component(_of(older, type="Mirror")["id"], center=[30, 0])
    session.load(older)                                                          # the client's undo
    assert len(session.path) == 2 and _of(session.spec, type="Mirror")["center"] == [20, 0]


def test_a_new_scene_leaves_the_inset(tmp_path):
    session = EditorSession(_page(tmp_path))
    session.open_inset(_of(session.spec, label="bench")["id"])
    session.reset()
    assert len(session.path) == 1 and session.spec["components"] == []


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


def test_save_takes_the_whole_page(client, tmp_path):
    client.post("/api/scene", json={"spec": _page(tmp_path)})
    bench = _of(client.get("/api/scene").json(), label="bench")
    inside = client.post("/api/scene/inset/open", json={"id": bench["id"]}).json()["spec"]
    _of(inside, type="Mirror")["center"] = [30, 0]
    client.post("/api/scene", json={"spec": inside, "edit": True})
    whole = client.get("/api/scene", params={"whole": True}).json()
    assert _of(whole, label="bench")["fragment"]["svg"] != bench["fragment"]["svg"]
    assert _of(client.get("/api/scene").json(), type="Mirror")                    # the session stays inside
    assert _of(_saved(), label="bench")["source"]["scene"]                        # autosave kept the page


def test_a_workspace_switch_goes_back_and_keeps_the_drawing(client, tmp_path):
    from optodraw.app import api

    client.post("/api/scene", json={"spec": _page(tmp_path)})
    first = api._store.current
    bench = _of(client.get("/api/scene").json(), label="bench")
    inside = client.post("/api/scene/inset/open", json={"id": bench["id"]}).json()["spec"]
    _of(inside, type="Mirror")["center"] = [30, 0]
    client.post("/api/scene", json={"spec": inside, "edit": True})
    other = client.post("/api/workspaces", json={"name": tmp_path.name + " other"}).json()
    assert len(other["path"]) == 1 and other["spec"]["components"] == []
    kept = _of(api._store.workspaces.load(first), label="bench")
    assert _of(kept["source"]["scene"], type="Mirror")["center"] == [30, 0]
    assert kept["fragment"]["svg"] != bench["fragment"]["svg"]


def test_a_whole_open_goes_back_first(client, tmp_path):
    spec = _page(tmp_path)
    client.post("/api/scene", json={"spec": spec})
    client.post("/api/scene/inset/open", json={"id": _of(spec, label="bench")["id"]})
    opened = client.post("/api/scene", json={"spec": spec, "whole": True}).json()
    assert len(opened["path"]) == 1 and _of(opened["spec"], label="picture")


def test_a_preset_waits_for_the_way_back(client, tmp_path):
    spec = _page(tmp_path)
    client.post("/api/scene", json={"spec": spec})
    client.post("/api/scene/inset/open", json={"id": _of(spec, label="bench")["id"]})
    name = client.get("/api/workspaces").json()["presets"][0]
    name = name if isinstance(name, str) else name["name"]
    response = client.post("/api/scene/preset", json={"name": name})         # it would replace the whole page
    assert response.status_code == 409 and "go back" in response.text
    assert len(client.get("/api/render/svg").json()["path"]) == 2 and _of(_saved(), label="picture")


def test_a_way_back_that_breaks_the_page_is_refused(tmp_path):
    (tmp_path / "a.svg").write_text(SVG, encoding="utf-8")
    page = Page(width_mm=183, height_mm=120, font_pt=7.0)
    bench = page.add(Inset(_bench(), center=(60, 60), width=100, label="bench"))
    picture = page.add(Inset(str(tmp_path / "a.svg"), center=(150, 60), width=40, label="picture"))
    page.zoom(bench, (-45, -3, -35, 3), picture)                                 # a box on the laser
    page.save(tmp_path / "page.json")
    session = EditorSession(json.loads((tmp_path / "page.json").read_text(encoding="utf-8")))
    session.open_inset(_of(session.spec, label="bench")["id"])
    session.delete(_of(session.spec, type="Laser")["id"])                        # the drawing fits the mirror alone
    with pytest.raises(ValueError, match="cannot draw"):
        session.close_inset()
    assert len(session.path) == 2 and [e["type"] for e in session.spec["components"]] == ["Mirror"]


def test_the_way_back_draws_a_drawing_that_autosave_left_old(tmp_path):
    session, store = EditorSession(_page(tmp_path)), _Store()
    session.bind_workspace(store, "page")
    before = _of(session.spec, label="bench")
    session.open_inset(before["id"])
    session.move_component(_of(session.spec, type="Mirror")["id"], center=[30, 0])
    session.autosave()                                                           # then the server stops
    again = EditorSession(store.saved)
    assert _of(again.spec, label="bench")["fragment"] == before["fragment"]     # the scene moved, the drawing did not
    again.open_inset(before["id"])
    again.close_inset()
    assert _of(again.spec, label="bench")["fragment"]["svg"] != before["fragment"]["svg"]


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


def test_a_scene_that_names_a_file_does_not_open(tmp_path):
    spec = _page(tmp_path)
    _of(spec, label="bench")["source"]["scene"]["components"][0]["label"] = str(tmp_path / "a.svg")   # a real file
    session = EditorSession(spec)
    with pytest.raises(ValueError, match="names a file"):
        session.open_inset(_of(spec, label="bench")["id"])


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


def test_a_whole_open_that_fails_stays_inside(client, tmp_path):
    spec = _page(tmp_path)
    client.post("/api/scene", json={"spec": spec})
    client.post("/api/scene/inset/open", json={"id": _of(spec, label="bench")["id"]})
    broken = {**spec, "components": [{"type": "NoSuchPart", "id": "x", "center": [0, 0]}]}
    assert client.post("/api/scene", json={"spec": broken, "whole": True}).status_code == 400
    assert len(client.get("/api/render/svg").json()["path"]) == 2


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


def test_opening_the_same_workspace_inside_shows_the_new_drawing(client, tmp_path):
    from optodraw.app import api

    spec = _page(tmp_path)
    client.post("/api/scene", json={"spec": spec})
    bench = _of(spec, label="bench")
    inside = client.post("/api/scene/inset/open", json={"id": bench["id"]}).json()["spec"]
    _of(inside, type="Mirror")["center"] = [30, 0]
    client.post("/api/scene", json={"spec": inside, "edit": True})
    opened = client.post(f"/api/workspaces/{api._store.current}/open").json()
    assert len(opened["path"]) == 1
    assert _of(opened["spec"], label="bench")["fragment"]["svg"] != bench["fragment"]["svg"]
