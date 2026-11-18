"""Insets made in the editor: each palette kind is made from plain values, its source changes and builds once, it
resizes, saves, loads and undoes through the API. A record that names a file outside the workspace stays unbuilt and
reads nothing, and a page with a large picture keeps its scene payload small."""

from __future__ import annotations

import builtins
import importlib.util
import io
import json
import re
import shutil
import subprocess

import pytest

pytest.importorskip("fastapi")

from optodraw.figure.page import Page
from optodraw.schema import scene_from_spec

SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 20"><rect width="40" height="20" fill="#cccccc"/>'
       '<text x="2" y="10">drop me</text></svg>')
needs_gds = pytest.mark.skipif(not all(importlib.util.find_spec(name) for name in ("gdstk", "shapely")),
                               reason="needs gdstk and shapely")
needs_poppler = pytest.mark.skipif(shutil.which("pdftocairo") is None, reason="needs pdftocairo")


@pytest.fixture()
def client(tmp_path):
    from fastapi.testclient import TestClient

    from optodraw.app.server import create_app

    client = TestClient(create_app())
    assert client.post("/api/workspaces", json={"name": tmp_path.name}).status_code == 200
    page = json.loads(json.dumps(Page(width_mm=183, height_mm=120, font_pt=7.0).to_spec()))
    assert client.post("/api/scene", json={"spec": page}).status_code == 200
    return client


def _png(color: str, size=(40, 20)) -> bytes:
    from PIL import Image

    out = io.BytesIO()
    Image.new("RGB", size, color).save(out, format="PNG")
    return out.getvalue()


def _upload(client, name: str, data: bytes) -> str:
    response = client.post("/api/files", params={"filename": name}, content=data)
    assert response.status_code == 200, response.text
    return response.json()["path"]


def _entry(spec: dict, item_id: str) -> dict:
    return next(e for e in spec["components"] if e.get("id") == item_id)


def _held(client, item_id: str) -> dict:
    """The entry as the session holds it: every drawing inline."""

    return _entry(client.get("/api/scene").json(), item_id)


def _gds(client, tmp_path) -> str:
    import gdstk

    lib = gdstk.Library()
    lib.new_cell("TOP").add(gdstk.rectangle((-10, -0.25), (10, 0.25), layer=1),
                            gdstk.rectangle((-10, -3), (10, 3), layer=3))
    lib.write_gds(tmp_path / "wg.gds")
    return _upload(client, "wg.gds", (tmp_path / "wg.gds").read_bytes())


def _gds_view(client, tmp_path) -> str:
    source = {"path": _gds(client, tmp_path), "stack": "gdsfactory_generic", "region": [-10, -10, 10, 10]}
    response = client.post("/api/inset", json={"kind": "GdsView", "source": source, "center": [40, 60]})
    assert response.status_code == 200, response.text
    return response.json()["id"]


def _bench() -> dict:
    from optodraw import Laser, Mirror, Scene

    scene = Scene(title="Bench", width=120, height=40)
    scene.add(Laser(center=(-40, 0), label="Laser"))
    scene.add(Mirror(center=(20, 0), angle=45, label="M1"))
    return json.loads(json.dumps(scene.to_spec()))


def _pdf(client, tmp_path) -> str:
    from matplotlib.backends.backend_pdf import PdfPages
    from matplotlib.figure import Figure

    with PdfPages(tmp_path / "two.pdf") as pdf:
        for page in (1, 2):
            figure = Figure(figsize=(2, 1 + page))
            figure.text(0.5, 0.5, f"page {page}")
            pdf.savefig(figure)
    return _upload(client, "two.pdf", (tmp_path / "two.pdf").read_bytes())


def _made(kind: str, client, tmp_path) -> tuple[dict, dict]:
    """The body that makes an inset of ``kind``, and a change of its source."""

    if kind == "Text":
        return {"source": {"text": "one"}}, {"text": "one two three"}
    if kind == "Equation":
        return {"source": {"latex": "a^2"}}, {"latex": "a^2 + b^2"}
    if kind == "EmptyBox":
        return {}, {"height": 12.0}
    if kind == "Timing":
        return {}, {"span": [0.0, 8.0]}
    if kind == "SceneView":
        return {}, {"scene": _bench()}
    if kind == "Image":
        return ({"source": {"path": _upload(client, "a.png", _png("red"))}},
                {"path": _upload(client, "b.png", _png("blue", (30, 30)))})
    if kind == "SvgFile":
        return {"source": {"path": _upload(client, "a.svg", SVG.encode())}}, {"drop_text": ["drop me"]}
    if kind == "PdfFile":
        return {"source": {"path": _pdf(client, tmp_path)}}, {"page": 2}
    if kind == "GdsView":
        source = {"path": _gds(client, tmp_path), "stack": "gdsfactory_generic", "region": [-10, -10, 10, 10]}
        return {"source": source}, {"region": [-5, -5, 5, 5]}
    if kind == "SectionView":
        return {"of": _gds_view(client, tmp_path), "source": {"cut": [[0, -8], [0, 8]]}}, {"z_scale": 2.0}
    assert kind == "View3D"
    return {"of": _gds_view(client, tmp_path)}, {"projection": "parallel"}


KINDS = ["Text", "Equation", "EmptyBox", "Timing", "SceneView", "Image", "SvgFile",
         pytest.param("PdfFile", marks=needs_poppler), pytest.param("GdsView", marks=needs_gds),
         pytest.param("SectionView", marks=needs_gds), pytest.param("View3D", marks=needs_gds)]


@pytest.mark.parametrize("kind", KINDS)
def test_each_kind_is_made_edited_resized_saved_reloaded_and_undone(client, tmp_path, kind):
    from optodraw.app import api

    body, change = _made(kind, client, tmp_path)
    made = client.post("/api/inset", json={"kind": kind, "center": [90, 60], **body})
    assert made.status_code == 200, made.text
    inset_id = made.json()["id"]
    first = _held(client, inset_id)
    assert first["source"]["kind"] == kind and first["fragment"]["svg"]       # mutant: no build keeps no drawing
    assert first["fragment"]["font_pt"] == 7.0                                 # the page's font, not the default 8
    for key in ("path", "gds"):                                               # a picked file, named in the workspace
        if key in first["source"]:
            assert first["source"][key].startswith(f"files/{api._store.current}/")

    edited = client.post(f"/api/inset/{inset_id}/source", json={"source": change})
    assert edited.status_code == 200, edited.text
    second = _held(client, inset_id)
    assert {key: second["source"][key] for key in change} == change
    assert second["fragment"]["svg"] != first["fragment"]["svg"]             # mutant: a merge with no build

    tall = {"height": 30.0} if kind == "EmptyBox" else {}
    resized = client.post(f"/api/inset/{inset_id}/size", json={"width": 80.0, **tall})
    assert resized.status_code == 200, resized.text
    third = _held(client, inset_id)
    assert third["width"] == 80.0 and third["fragment"]["width_mm"] == 80.0   # mutant: a width with no build
    assert "scaled from the saved drawing" not in " ".join(third["fragment"]["notes"])
    if kind == "EmptyBox":
        assert third["fragment"]["size_mm"] == [80.0, 30.0]                   # mutant: the height is dropped

    saved = api._store.workspaces.load(api._store.current)
    assert _entry(saved, inset_id)["fragment"] == third["fragment"]           # autosave kept the new drawing
    assert client.post(f"/api/workspaces/{api._store.current}/open").status_code == 200
    assert _held(client, inset_id) == third                                   # it loads as it was saved

    undone = client.post("/api/scene", json={"spec": made.json()["spec"]})   # the client's undo sends the old payload
    assert undone.status_code == 200, undone.text
    assert _held(client, inset_id)["fragment"] == first["fragment"]


@needs_gds
def test_a_section_from_a_gds_view_gets_its_cut_marks(client, tmp_path):
    gds = _gds_view(client, tmp_path)
    made = client.post("/api/inset", json={"kind": "SectionView", "of": gds, "source": {"cut": [[0, -8], [0, 8]]}})
    assert made.status_code == 200, made.text
    links = [e for e in made.json()["spec"]["components"] if e["type"] == "CutLink"]
    assert [(link["source"], link["section"], link["a"], link["b"], link["name"]) for link in links] == \
        [(gds, made.json()["id"], [0, -8], [0, 8], "A")]                       # mutant: no CutLink, as Inset.cut adds
    again = client.post("/api/inset", json={"kind": "SectionView", "of": gds, "source": {"cut": [[2, -8], [2, 8]]}})
    assert [e["name"] for e in again.json()["spec"]["components"] if e["type"] == "CutLink"] == ["A", "B"]
    outside = client.post("/api/inset", json={"kind": "SectionView", "of": gds, "source": {"cut": [[0, -8], [0, 30]]}})
    assert outside.status_code == 400 and "region" in outside.text              # mutant: no check of the cut ends


def test_a_resize_moves_the_marks_with_the_new_drawing(client):
    made = client.post("/api/inset", json={"kind": "EmptyBox", "center": [90, 60], "width": 50, "height": 30})
    inset_id = made.json()["id"]
    spec = client.get("/api/scene").json()
    spec["components"].append({"type": "Callout", "id": "call", "text": "edge", "center": [150, 100],
                               "target": {"anchor": inset_id, "point": [10, 5], "options": {}}})
    assert client.post("/api/scene", json={"spec": spec, "edit": True}).status_code == 200

    def target() -> tuple[float, float]:
        scene = scene_from_spec(client.get("/api/scene").json())
        return tuple(next(n for n in scene.walk() if getattr(n, "_id", "") == "call").target)

    assert target() == pytest.approx((90 - 25 + 10, 60 + 15 - 5))             # 10 right of the left edge, 5 down
    assert client.post(f"/api/inset/{inset_id}/size", json={"width": 80, "height": 40}).status_code == 200
    assert target() == pytest.approx((90 - 40 + 10, 60 + 20 - 5))             # mutant: the old drawing scaled


def test_a_record_outside_the_workspace_stays_unbuilt_and_reads_no_file(client, tmp_path, monkeypatch):
    secret = tmp_path / "secret.png"
    secret.write_bytes(_png("green"))
    page = json.loads(json.dumps(Page(width_mm=120, height_mm=80, letters=False).to_spec()))
    page["components"] = [
        {"type": "Inset", "id": "far", "center": [30, 40], "width": 40,
         "source": {"kind": "Image", "path": str(secret), "scale_um_per_px": None, "image_kind": "measured"}},
        {"type": "Inset", "id": "up", "center": [80, 40], "width": 40,
         "source": {"kind": "SvgFile", "path": f"../{secret.name}", "drop_text": []}}]
    opened = []
    real_open, real_io_open = builtins.open, io.open
    monkeypatch.setattr(builtins, "open", lambda file, *a, **k: opened.append(str(file)) or real_open(file, *a, **k))
    monkeypatch.setattr(io, "open", lambda file, *a, **k: opened.append(str(file)) or real_io_open(file, *a, **k))
    assert client.post("/api/scene", json={"spec": page, "whole": True}).status_code == 200
    assert client.get("/api/render/svg").status_code == 200
    for inset_id in ("far", "up"):
        rebuilt = client.post(f"/api/inset/{inset_id}/source", json={})
        assert rebuilt.status_code == 400 and "files folder" in rebuilt.json()["detail"]
        assert client.post(f"/api/inset/{inset_id}/size", json={"width": 60}).status_code == 400
        assert "fragment" not in _held(client, inset_id)                       # still an empty box
    assert not [path for path in opened if "secret" in path]                  # mutant: no outside check reads it
    picked = _upload(client, "picked.png", _png("green"))
    opened.clear()
    assert client.post("/api/inset", json={"kind": "Image", "source": {"path": picked}}).status_code == 200
    assert any(path.endswith("picked.png") for path in opened)                # the watch sees a read it allows


def test_a_page_with_a_5_mb_picture_keeps_its_payload_small(client):
    import numpy as np
    from PIL import Image

    out = io.BytesIO()
    Image.fromarray(np.random.default_rng(0).integers(0, 256, (1300, 1300, 3), dtype=np.uint8)).save(out, "PNG")
    assert len(out.getvalue()) > 4.5 * 2 ** 20                               # noise does not compress
    path = _upload(client, "noise.png", out.getvalue())
    made = client.post("/api/inset", json={"kind": "Image", "source": {"path": path}, "center": [60, 60], "width": 80})
    assert made.status_code == 200 and len(made.content) < 100_000          # mutant: the payload sends the spec whole
    inset_id = made.json()["id"]
    assert "svg" not in _entry(made.json()["spec"], inset_id)["fragment"]
    moved = client.post(f"/api/component/{inset_id}/move", json={"center": [70, 60]})
    assert moved.status_code == 200 and len(moved.content) < 100_000        # mutant: the canvas SVG holds the picture
    href = re.search(r'<image href="(/api/fragment/[0-9a-f]{64})"', moved.json()["svg"]).group(1)
    drawing = client.get(href)
    assert drawing.status_code == 200 and drawing.headers["content-type"].startswith("image/svg+xml")
    assert len(drawing.content) > 5 * 2 ** 20 and b"data:image/png;base64," in drawing.content

    undone = client.post("/api/scene", json={"spec": made.json()["spec"]})  # the undo sends the drawing by its key
    assert undone.status_code == 200, undone.text                           # mutant: no unkeyed: a fragment with no svg
    held = _held(client, inset_id)
    assert held["center"] == [60.0, 60.0] and len(held["fragment"]["svg"]) > 5 * 2 ** 20
    copy = client.post("/api/inset", json={"kind": "SceneView", "source": {"scene": undone.json()["spec"]}})
    assert copy.status_code == 200, copy.text                                # a copy of the open page, sent with keys
    lost = json.loads(json.dumps(undone.json()["spec"]))
    _entry(lost, inset_id)["fragment"]["svg_key"] = "0" * 64
    assert client.post("/api/scene", json={"spec": lost}).status_code == 409   # a key from another server run
    assert client.get("/api/fragment/" + "0" * 64).status_code == 404


def test_a_picked_file_is_kept_and_never_changes(client, tmp_path):
    from optodraw.app import api

    first = _upload(client, "../a b.png", _png("red"))
    assert first == f"files/{api._store.current}/a_b.png"                    # mutant: the name keeps its folder part
    assert _upload(client, "a b.png", _png("red")) == first                   # the same bytes: the same file
    other = _upload(client, "a b.png", _png("blue"))
    assert other != first and other.startswith(f"files/{api._store.current}/a_b-")   # mutant: an overwrite
    assert (api._store.workspaces.root / first).read_bytes() == _png("red")


def test_tex_and_a_plot_are_refused_and_run_no_tool(client, monkeypatch):
    ran = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: ran.append(a))
    tex = client.post("/api/inset", json={"kind": "Equation", "source": {"latex": "x", "tex": True}})
    assert tex.status_code == 400 and "TeX" in tex.text and ran == []        # mutant: no TeX check runs latex
    assert client.post("/api/inset", json={"kind": "Plot"}).status_code == 400
    text = client.post("/api/inset", json={"kind": "Text", "height": 10})
    assert text.status_code == 400 and "own shape" in text.text              # a height for a free shape only
