"""A saved page opens in the editor session: dragging an inset brings its marks, dragging a mark leaves the inset."""

from __future__ import annotations

import json
import re

import pytest

pytest.importorskip("fastapi")

from optodraw import Callout, DashedLink, Inset, Note, Scene
from optodraw.figure.inset import ZoomLink
from optodraw.app.session import EditorSession
from optodraw.figure.page import Page

SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 20">'
       '<rect width="40" height="20" fill="#cccccc"/></svg>')


def _session(tmp_path):
    folder = tmp_path / "data"
    folder.mkdir()
    (folder / "a.svg").write_text(SVG, encoding="utf-8")
    (folder / "b.svg").write_text(SVG, encoding="utf-8")
    page = Page(width_mm=183, height_mm=120, font_pt=7.0)
    a = page.add(Inset(str(folder / "a.svg"), center=(30, 100), width=50, label="small"))
    b = page.add(Inset(str(folder / "b.svg"), center=(30, 40), width=40, label="big"))
    page.add(Callout("edge", center=(70, 70), target=a.at(10, 5)))
    page.add(DashedLink(start=a.at(5, 5), end=(100.0, 20.0)))
    page.add(Note("anchored", center=a.at(2, 2)))
    page.zoom(a, (10, 5, 20, 15), b)
    path = tmp_path / "page.json"
    page.save(path)
    session = EditorSession(json.loads(path.read_text()))
    return session


def _entry(session, **match):
    return next(e for e in session.spec["components"] if all(e.get(k) == v for k, v in match.items()))


def test_a_saved_page_opens_in_a_session(tmp_path):
    session = _session(tmp_path)
    inset = _entry(session, label="small")
    svg = session.scene().render_svg(editable=True, component_ids=session.component_id_map(session.scene())).as_svg()
    assert f'data-component-id="{inset["id"]}"' in svg


def test_dragging_an_inset_moves_it(tmp_path):
    session = _session(tmp_path)
    inset = _entry(session, label="small")
    before = session.scene().svg()
    session.move_component(inset["id"], center=[50, 90])
    assert _entry(session, label="small")["center"] == [50.0, 90.0]
    assert session.scene().svg() != before


def test_dragging_an_inset_brings_its_marks(tmp_path):
    session = _session(tmp_path)
    inset = _entry(session, label="small")
    call, link = _entry(session, type="Callout"), _entry(session, type="DashedLink")
    session.move_component(inset["id"], center=[40, 90])                         # 10 right, 10 down
    after_call, after_link = _entry(session, type="Callout"), _entry(session, type="DashedLink")
    assert after_call["center"] == [80.0, 60.0]
    assert after_call["target"] == call["target"]                                # an anchor is never rewritten
    assert after_link["ends"][0] == link["ends"][0]
    first = after_link["center"]
    assert first == pytest.approx([link["center"][0] + 10, link["center"][1] - 10])
    plain = [after_link["ends"][1][i] + first[i] for i in (0, 1)]                # a plain end stays in the world
    assert plain == pytest.approx([100.0, 20.0])


def test_the_marks_of_another_inset_stay(tmp_path):
    session = _session(tmp_path)
    big = _entry(session, label="big")
    call = _entry(session, type="Callout")
    session.move_component(big["id"], center=[60, 40])
    assert _entry(session, type="Callout")["center"] == call["center"]


def test_an_anchored_note_is_live_and_not_shifted(tmp_path):
    session = _session(tmp_path)
    inset = _entry(session, label="small")
    center = _entry(session, type="Note")["center"]
    session.move_component(inset["id"], center=[40, 90])
    assert _entry(session, type="Note")["center"] == center


def test_a_turn_without_a_move_shifts_nothing(tmp_path):
    session = _session(tmp_path)
    inset = _entry(session, label="small")
    session.move_component(inset["id"], center=inset["center"], angle=15)
    assert _entry(session, type="Callout")["center"] == [70.0, 70.0]


def test_dragging_a_mark_leaves_the_inset(tmp_path):
    session = _session(tmp_path)
    inset = _entry(session, label="small")
    call = _entry(session, type="Callout")
    session.move_component(call["id"], center=[90, 50])
    assert _entry(session, label="small")["center"] == inset["center"] == [30.0, 100.0]
    assert _entry(session, type="Callout")["target"] == call["target"]


def _zoom_on_its_insets(session):
    """The zoom's lines start on the box corners on the small inset and end on the frame corners of the big one."""

    nodes = list(session.scene().walk())
    small = next(n for n in nodes if isinstance(n, Inset) and n.label == "small")
    big = next(n for n in nodes if isinstance(n, Inset) and n.label == "big")
    zoom = next(n for n in nodes if isinstance(n, ZoomLink))
    corners = [small.at(x, y).xy() for x, y in ((10, 5), (20, 5), (20, 15), (10, 15))]
    lines = zoom._lines(zoom._corners())
    assert zoom._corners() == pytest.approx(corners)
    for x1, y1, x2, y2 in lines:
        assert any((x1, y1) == pytest.approx(c) for c in corners)
        assert any((x2, y2) == pytest.approx(c) for c in big.drawn_points())
    return small


def test_a_zoom_link_follows_a_drag(tmp_path):
    session = _session(tmp_path)
    small = _entry(session, label="small")
    before = session.scene().svg()
    session.move_component(small["id"], center=[60, 100])
    assert _entry(session, type="ZoomLink")["small"] == small["id"]
    assert session.scene().svg() != before
    moved = _zoom_on_its_insets(session)
    assert (moved.world_position.x, moved.world_position.y) == pytest.approx((60, 100))


# ---- the 2D canvas sends the whole scene as an edit: a drag, a nudge, an align and a delete are one spec ----

def _set_center(session, step, *types_or_labels):
    """The spec the canvas sends after a drag of the named entries by ``step``."""

    spec = session.spec
    for entry in spec["components"]:
        if entry.get("label") in types_or_labels or entry["type"] in types_or_labels:
            entry["center"] = [entry["center"][0] + step[0], entry["center"][1] + step[1]]
    return spec


def test_a_whole_scene_drag_of_an_inset_brings_its_marks(tmp_path):
    session = _session(tmp_path)
    call, link = _entry(session, type="Callout"), _entry(session, type="DashedLink")
    note = _entry(session, type="Note")["center"]
    session.load(_set_center(session, (10, -10), "small"), edit=True)              # as the canvas sends a drag
    assert _entry(session, label="small")["center"] == [40, 90]
    after_call, after_link = _entry(session, type="Callout"), _entry(session, type="DashedLink")
    assert after_call["center"] == [80.0, 60.0] and after_call["target"] == call["target"]
    first = after_link["center"]
    assert first == pytest.approx([link["center"][0] + 10, link["center"][1] - 10])
    assert [after_link["ends"][1][i] + first[i] for i in (0, 1)] == pytest.approx([100.0, 20.0])
    nodes = list(session.scene().walk())
    inset = next(n for n in nodes if isinstance(n, Inset) and n.label == "small")
    callout = next(n for n in nodes if isinstance(n, Callout))
    assert tuple(callout.target) == pytest.approx(inset.at(10, 5).xy())
    assert _entry(session, type="Note")["center"] == note                          # an anchored center is live
    _zoom_on_its_insets(session)


def test_a_group_drag_moves_a_mark_once(tmp_path):
    session = _session(tmp_path)
    session.load(_set_center(session, (10, -10), "small", "Callout"), edit=True)    # the inset and its callout
    assert _entry(session, type="Callout")["center"] == [80.0, 60.0]


def test_a_whole_scene_update_that_moves_no_inset_moves_no_mark(tmp_path):
    session = _session(tmp_path)
    call = _entry(session, type="Callout")
    session.load(_set_center(session, (5, 5), "big"), edit=True)                   # the other inset
    session.load(session.spec, edit=True)                                          # an edit of nothing
    assert _entry(session, type="Callout")["center"] == call["center"]


# ---- deleting an inset that has marks: the marks keep their places, the zoom goes ----

def _places(session):
    """Where the marks of the inset "small" point now, in the world."""

    nodes = list(session.scene().walk())
    callout = next(n for n in nodes if isinstance(n, Callout))
    link = next(n for n in nodes if isinstance(n, DashedLink))
    note = next(n for n in nodes if isinstance(n, Note) and n.text == "anchored")
    return {"target": tuple(callout.target), "start": link.start, "end": link.end,
            "note": (note.world_position.x, note.world_position.y)}


def _after_delete(session, before, tmp_path):
    spec = session.spec
    assert not any(c["type"] == "ZoomLink" for c in spec["components"])
    assert '"point"' not in json.dumps(spec)                                       # every anchor is a plain point
    assert _places(session) == pytest.approx(before)
    assert "over" not in _entry(session, label="key")
    from optodraw.app.workspaces import WorkspaceStore
    from optodraw.schema import scene_from_spec

    saved = WorkspaceStore(tmp_path / "workspaces").load("page")
    assert saved is not None and scene_from_spec(saved).svg()                      # the autosave loads


def _session_with_a_key(tmp_path):
    from optodraw.app.workspaces import WorkspaceStore

    session = _session(tmp_path)
    spec = session.spec
    small = _entry(session, label="small")
    spec["components"].append({"type": "Inset", "id": "key", "label": "key", "center": [40, 100], "width": 10,
                               "height": 6, "over": small["id"], "source": {"kind": "EmptyBox", "height": 6}})
    next(c for c in spec["components"] if c["type"] == "Note")["center_offset"] = [3.0, -1.0]   # moved off by hand
    session.load(spec)
    session.bind_workspace(WorkspaceStore(tmp_path / "workspaces"), "page")
    return session, small["id"]


def test_deleting_an_inset_through_the_rest_route_keeps_its_marks(tmp_path):
    session, small = _session_with_a_key(tmp_path)
    before = _places(session)
    session.delete(small)
    session.autosave()
    _after_delete(session, before, tmp_path)


def test_deleting_an_inset_through_the_canvas_keeps_its_marks(tmp_path):
    session, small = _session_with_a_key(tmp_path)
    before = _places(session)
    spec = session.spec
    spec["components"] = [c for c in spec["components"] if c.get("id") != small]   # as deleteSelected sends it
    session.load(spec, edit=True)
    session.autosave()
    _after_delete(session, before, tmp_path)


def test_a_new_mark_on_an_inset_that_went_is_still_refused(tmp_path):
    session = _session(tmp_path)
    small = _entry(session, label="small")["id"]
    spec = session.spec
    spec["components"] = [c for c in spec["components"] if c.get("id") != small]
    spec["components"].append({"type": "Callout", "id": "late", "text": "late", "center": [10, 10],
                               "target": {"anchor": small, "point": [1, 1], "options": {}}})
    with pytest.raises(KeyError, match="Unknown component reference"):            # another file is never patched
        session.load(spec, edit=True)


# ---- an open loads a file as it is: only an edit of the held scene brings marks ----

def _page_spec(tmp_path, name, x):
    """A saved page: the inset "small" at ``(x, 100)`` and a callout on it at ``(100, 70)``. Two such pages share
    their ids, as two files often do: ids come from labels and types."""

    folder = tmp_path / name
    folder.mkdir()
    (folder / "a.svg").write_text(SVG, encoding="utf-8")
    page = Page(width_mm=183, height_mm=120, font_pt=7.0)
    small = page.add(Inset(str(folder / "a.svg"), center=(x, 100), width=50, label="small"))
    page.add(Callout("edge", center=(100, 70), target=small.at(10, 5)))
    page.save(folder / "page.json")
    return json.loads((folder / "page.json").read_text(encoding="utf-8"))


def _of(spec, **match):
    return next(e for e in spec["components"] if all(e.get(k) == v for k, v in match.items()))


@pytest.fixture()
def client(tmp_path):
    from fastapi.testclient import TestClient

    from optodraw.app.server import create_app

    client = TestClient(create_app())
    assert client.post("/api/workspaces", json={"name": tmp_path.name}).status_code == 200    # its own autosave
    return client


def _autosaved():
    from optodraw.app import api

    return api._store.workspaces.load(api._store.current)


def test_an_edit_through_the_api_brings_the_marks(client, tmp_path):
    client.post("/api/scene", json={"spec": _page_spec(tmp_path, "a", 30)})
    spec = client.get("/api/scene").json()
    _of(spec, label="small")["center"] = [40, 90]                                  # a drag, as the canvas sends it
    after = client.post("/api/scene", json={"spec": spec, "edit": True}).json()["spec"]
    assert _of(after, type="Callout")["center"] == [110.0, 60.0]


def test_the_same_change_sent_as_an_open_moves_no_mark(client, tmp_path):
    client.post("/api/scene", json={"spec": _page_spec(tmp_path, "a", 30)})
    spec = client.get("/api/scene").json()
    _of(spec, label="small")["center"] = [40, 90]
    after = client.post("/api/scene", json={"spec": spec}).json()["spec"]
    assert _of(after, type="Callout")["center"] == [100, 70]


def test_opening_b_after_a_leaves_b_as_it_is(client, tmp_path):
    a, b = _page_spec(tmp_path, "a", 30), _page_spec(tmp_path, "b", 60)
    assert _of(a, type="Callout")["id"] == _of(b, type="Callout")["id"]          # the two files share their ids
    client.post("/api/scene", json={"spec": a})                                  # File > Open, then again
    after = client.post("/api/scene", json={"spec": b}).json()["spec"]
    assert _of(after, type="Callout")["center"] == [100, 70]
    assert _of(_autosaved(), type="Callout")["center"] == [100, 70]


def test_a_workspace_switch_leaves_the_page_as_it_is(client, tmp_path):
    from optodraw.app import api

    names = [api._store.workspaces.save(f"{tmp_path.name} {x}", _page_spec(tmp_path, str(x), x)) for x in (30, 60)]
    for name in names:
        opened = client.post(f"/api/workspaces/{name}/open").json()["spec"]
    assert _of(opened, type="Callout")["center"] == [100, 70]
    assert _of(api._store.workspaces.load(names[1]), type="Callout")["center"] == [100, 70]


def test_an_open_that_names_a_missing_inset_is_refused(client, tmp_path):
    a = _page_spec(tmp_path, "a", 30)
    client.post("/api/scene", json={"spec": a})
    broken = json.loads(json.dumps(a))
    broken["components"] = [c for c in broken["components"] if c["type"] != "Inset"]  # its callout names "small"
    response = client.post("/api/scene", json={"spec": broken})                      # never patched with A's places
    assert response.status_code == 400 and "Unknown component reference" in response.text


def test_the_canvas_sends_its_edits_as_edits_and_an_open_as_it_is():
    from collections import Counter
    from pathlib import Path

    js = Path(__file__).resolve().parents[1] / "optodraw" / "app" / "static" / "js"
    assert ('request("POST", "/api/scene", whole ? { spec, edit, whole } : { spec, edit, depth: level })' in
            (js / "api.js").read_text(encoding="utf-8"))           # an edit names its level; a whole page does not
    calls = Counter(re.findall(r"api\.setScene\([^;]*", (js / "app.js").read_text(encoding="utf-8")))
    assert calls == Counter({
        "api.setScene(next, true))": 2,                         # applySpec (move, nudge, align, delete...), live move
        "api.setScene(history[historyIndex])))": 2,             # undo and redo restore a state as it was
        "api.setScene(spec, false, true)": 1,                   # File > Open: a whole page, open insets close
    })


# ---- Arrange and the property panel's center fields move an inset: its marks come with it ----

def _two_insets(tmp_path, *marks, at=((30, 100), (140, 30))):
    """A saved page: "big" and "small" at ``at``, and the marks that ``marks`` makes of the two."""

    (tmp_path / "a.svg").write_text(SVG, encoding="utf-8")
    page = Page(width_mm=183, height_mm=120, font_pt=7.0)
    big = page.add(Inset(str(tmp_path / "a.svg"), center=at[0], width=40, label="big"))
    small = page.add(Inset(str(tmp_path / "a.svg"), center=at[1], width=50, label="small"))
    for mark in marks:
        page.add(mark(big, small))
    page.save(tmp_path / "page.json")
    return json.loads((tmp_path / "page.json").read_text(encoding="utf-8"))


def _step(before, after, **match):
    """How far the entry that ``match`` names moved from ``before`` to ``after``."""

    return [_of(after, **match)["center"][i] - _of(before, **match)["center"][i] for i in (0, 1)]


@pytest.mark.parametrize("selected", [True, False], ids=["the two insets", "no selection"])
def test_arrange_brings_the_marks_of_an_inset_it_moves(client, tmp_path, selected):
    client.post("/api/scene", json={"spec": _two_insets(
        tmp_path, lambda big, small: Callout("edge", center=(150, 70), target=small.at(10, 5)),
        lambda big, small: DashedLink(start=(120.0, 60.0), end=small.at(5, 5)),
        lambda big, small: Note("anchored", center=small.at(2, 2)))})
    spec = client.get("/api/scene").json()
    ids = [_of(spec, label=label)["id"] for label in ("big", "small")] if selected else []
    response = client.post("/api/scene/arrange", json={"ids": ids, "strategy": "grid"})
    assert response.status_code == 200, response.text
    after = response.json()["spec"]
    step = _step(spec, after, label="small")
    assert step != [0.0, 0.0]
    for kind in ("Callout", "DashedLink"):                              # the step of their inset, not a grid place
        assert _step(spec, after, type=kind) == pytest.approx(step), kind
    assert _of(after, type="Callout")["target"] == _of(spec, type="Callout")["target"]
    link = _of(after, type="DashedLink")
    assert [link["ends"][0][i] + link["center"][i] for i in (0, 1)] == pytest.approx([120.0, 60.0])  # a plain end
    assert _of(after, type="Note")["center"] == _of(spec, type="Note")["center"]       # an anchored center stays live


def test_arrange_moves_a_mark_of_two_insets_once(client, tmp_path):
    client.post("/api/scene", json={"spec": _two_insets(                # neither inset is at the grid's corner
        tmp_path, lambda big, small: DashedLink(start=big.at(5, 5), end=small.at(5, 5), text="same"),
        at=((30, 30), (140, 100)))})
    spec = client.get("/api/scene").json()
    ids = [_of(spec, label=label)["id"] for label in ("big", "small")]
    after = client.post("/api/scene/arrange", json={"ids": ids, "strategy": "grid"}).json()["spec"]
    steps = [_step(spec, after, label=label) for label in ("big", "small")]
    assert all(step != [0.0, 0.0] for step in steps)
    moved = _step(spec, after, type="DashedLink")
    assert any(moved == pytest.approx(step) for step in steps), (moved, steps)  # with one inset, not by the sum


def test_the_center_field_brings_the_marks(client, tmp_path):
    client.post("/api/scene", json={"spec": _page_spec(tmp_path, "a", 30)})
    small = _of(client.get("/api/scene").json(), label="small")["id"]
    response = client.patch(f"/api/component/{small}", json={"params": {"center": [40, 90]}})     # 10 right, 10 down
    assert response.status_code == 200, response.text
    spec = client.get("/api/scene").json()
    assert _of(spec, label="small")["center"] == [40, 90]
    assert _of(spec, type="Callout")["center"] == [110.0, 60.0]


def test_a_refused_center_edit_moves_no_mark(client, tmp_path):
    client.post("/api/scene", json={"spec": _page_spec(tmp_path, "a", 30)})
    small = _of(client.get("/api/scene").json(), label="small")["id"]
    response = client.patch(f"/api/component/{small}", json={"params": {"center": [40, 90], "width": "wide"}})
    assert response.status_code == 400
    spec = client.get("/api/scene").json()
    assert _of(spec, label="small")["center"] == [30, 100] and _of(spec, type="Callout")["center"] == [100, 70]


def test_width_shows_as_a_property():
    from optodraw.catalog import describe_component

    described = describe_component("Inset")
    assert "width" in described["parameters"] and described["param_meta"]["width"]["type"] == "number"


def test_the_saved_page_keeps_the_marks_on_the_moved_inset(tmp_path):
    session = _session(tmp_path)
    inset = _entry(session, label="small")
    session.move_component(inset["id"], center=[40, 90])
    path = tmp_path / "moved.json"
    path.write_text(json.dumps(session.spec), encoding="utf-8")
    loaded = Scene.load(path)
    assert isinstance(loaded, Page)
    nodes = list(loaded.walk())
    small = next(n for n in nodes if isinstance(n, Inset) and n.label == "small")
    assert (small.world_position.x, small.world_position.y) == pytest.approx((40, 90))
    call = next(n for n in nodes if isinstance(n, Callout))
    link = next(n for n in nodes if isinstance(n, DashedLink))
    note = next(n for n in nodes if isinstance(n, Note) and n.text == "anchored")
    zoom = next(n for n in nodes if isinstance(n, ZoomLink))
    assert tuple(call.target) == pytest.approx(small.at(10, 5).xy())
    assert (call.world_position.x, call.world_position.y) == pytest.approx((80, 60))   # the step of the inset
    assert link.start == pytest.approx(small.at(5, 5).xy())
    assert link.end == pytest.approx((100.0, 20.0))                                    # a plain end keeps its place
    assert (note.world_position.x, note.world_position.y) == pytest.approx(small.at(2, 2).xy())
    assert zoom.small is small
    assert zoom._corners() == pytest.approx([small.at(x, y).xy() for x, y in ((10, 5), (20, 5), (20, 15), (10, 15))])
