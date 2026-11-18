"""The editor routes behind the layout view: the part's GDS bytes, its .lyp, the vendored viewer and its host,
and cuts posted in the GDS file's frame (what the layout view's ruler gives)."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from optodraw.app.server import create_app

from gds_layout_fixtures import docs_device_gds


@pytest.fixture()
def client() -> TestClient:
    test_client = TestClient(create_app())
    test_client.post("/api/scene/new", json={})
    return test_client


def _import(client, tmp_path) -> tuple[str, bytes]:
    data = docs_device_gds(tmp_path).read_bytes()
    gid = client.post("/api/gds/import", params={"filename": "straight_pn.gds"}, content=data).json()["id"]
    return gid, data


def test_the_file_route_returns_the_imported_bytes(client, tmp_path):
    gid, data = _import(client, tmp_path)
    res = client.get(f"/api/gds/{gid}/file")
    assert res.status_code == 200 and res.content == data
    assert res.headers["content-type"] == "application/octet-stream"


def test_a_part_whose_file_is_gone_gets_a_404_that_says_so(client, tmp_path):
    from optodraw.app.api import _find_gds_node

    gid, _ = _import(client, tmp_path)
    Path(_find_gds_node(gid).source).unlink()
    res = client.get(f"/api/gds/{gid}/file")
    assert res.status_code == 404 and res.json()["detail"].startswith(f"no file for '{gid}'")


def test_the_lyp_route_carries_the_colour_a_technology_file_set(client, tmp_path):
    gid, _ = _import(client, tmp_path)
    lyp = ('<?xml version="1.0" encoding="utf-8"?><layer-properties><properties><fill-color>#123456</fill-color>'
           '<frame-color>#123456</frame-color><name>Pad metal</name><source>49/0@1</source></properties></layer-properties>')
    assert client.post(f"/api/gds/{gid}/technology", params={"filename": "t.lyp"}, content=lyp).status_code == 200
    res = client.get(f"/api/gds/{gid}/lyp")
    assert res.status_code == 200 and "application/xml" in res.headers["content-type"]
    assert "#123456" in res.text and "Pad metal" in res.text


def test_the_viewer_and_its_host_are_served_as_utf8_scripts(client):
    from optodraw.renderers.gds_lens import GDS_LENS_SHA256

    res = client.get("/vendor/gds-lens.js")
    assert res.status_code == 200 and hashlib.sha256(res.content).hexdigest() == GDS_LENS_SHA256
    assert res.headers["content-type"] == "text/javascript; charset=utf-8"
    assert "immutable" in res.headers["cache-control"]
    host = client.get("/vendor/gds-lens-host.js")
    assert host.status_code == 200 and "window.gdsLensHost" in host.text


def _cut(client, gid, **body):
    res = client.post(f"/api/gds/{gid}/cross_section", json={"label": "A-A'", **body})
    assert res.status_code == 200, res.text
    return res.json()


def test_a_cut_in_file_coordinates_is_the_same_cut(client, tmp_path):
    gid, _ = _import(client, tmp_path)
    # x = 11 um in the file: read as the part's frame instead it would land at 21 um, off the cell (0..20)
    local = _cut(client, gid, line=[1.0, 11.0, 1.0, -11.0])
    file_line = local["line_file"]
    assert file_line == pytest.approx([11.0, 11.0, 11.0, -11.0])        # the cell spans 0..20 by -11..11
    again = _cut(client, gid, line=file_line, frame="file")
    assert again["cross_section"] == local["cross_section"] and again["line_file"] == pytest.approx(file_line)


def test_a_cut_in_file_coordinates_follows_a_crop(client, tmp_path):
    from optodraw.app.api import _find_gds_node, _session

    gid, _ = _import(client, tmp_path)
    _session().update(gid, {"crop_region": [0.0, -11.0, 12.0, 11.0]})
    node = _find_gds_node(gid)
    a, b = node.file_to_local(11.0, 11.0), node.file_to_local(11.0, -11.0)     # read as local: 17 um, off the crop
    local = _cut(client, gid, line=[*a, *b])
    again = _cut(client, gid, line=[11.0, 11.0, 11.0, -11.0], frame="file")
    assert again["cross_section"] == local["cross_section"]


def test_an_unknown_frame_is_refused(client, tmp_path):
    gid, _ = _import(client, tmp_path)
    res = client.post(f"/api/gds/{gid}/cross_section", json={"line": [0, 1, 0, -1], "frame": "world"})
    assert res.status_code == 400 and "frame" in res.json()["detail"]


def test_the_editor_client_asks_both_routes():
    src = (Path(__file__).resolve().parents[1] / "optodraw" / "app" / "static" / "js" / "api.js").read_text(encoding="utf-8")
    assert "gdsFile:" in src and "/file`" in src and "arrayBuffer()" in src
    assert "gdsLyp:" in src and "/lyp`" in src


def test_the_file_route_names_the_top_cell_the_part_uses(client, tmp_path):
    from gds_layout_fixtures import two_tops_gds

    data = two_tops_gds(tmp_path).read_bytes()
    gid = client.post("/api/gds/import", params={"filename": "two_tops.gds"}, content=data).json()["id"]
    assert client.get(f"/api/gds/{gid}/file").headers["x-gds-cell"] == "B"
