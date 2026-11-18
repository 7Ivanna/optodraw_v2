"""Local editor parts persist, place, route and retain frozen scene definitions."""
from urllib.parse import quote

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402
from optodraw.app.server import create_app  # noqa: E402
from optodraw.app.session import SessionStore  # noqa: E402
from optodraw.app.workspaces import WorkspaceStore  # noqa: E402

SVG = ('<svg viewBox="-10 -5 20 10"><rect x="-10" y="-5" width="20" height="10"/>'
       '<circle id="port:in" cx="-10" cy="0" data-orientation="180"/>'
       '<circle id="port:out" cx="10" cy="0"/></svg>')
NAME = "user:demo/Tap"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from optodraw.app import api
    monkeypatch.setattr(api, "_store", SessionStore(WorkspaceStore(tmp_path)))
    return TestClient(create_app())


def create(client):
    response = client.post("/api/parts", json={"name": NAME, "svg": SVG,
        "parameters": {"weight": {"type": "float", "default": 0.5, "min": 0, "max": 1}}})
    assert response.status_code == 200, response.text
    return response.json()


def test_my_parts_persists_and_uses_hash_checked_previews(client):
    info = create(client)
    entry = client.get("/api/catalog").json()["components"][NAME]
    assert entry["category"] == "my_parts"
    assert entry["definition_hash"] == info["definition_hash"]
    for view in ("1d", "2d"):
        response = client.get("/api/preview/"+quote(NAME, safe=""), params={"view": view})
        assert response.status_code == 200 and "rect" in response.json()["svg"]
    body = client.get("/api/catalog/"+quote(NAME, safe="")).json()
    assert "weight" in body["param_meta"]
    assert client.get("/api/parts").json()["parts"][NAME]["definition_hash"] == info["definition_hash"]


def test_copies_parameters_routes_and_frozen_scene_survive_library_change(client):
    old = create(client)["definition_hash"]
    ids = []
    for x in (-30, 30):
        response = client.post("/api/component", json={"name": NAME, "params": {"center": [x, 0]}})
        assert response.status_code == 200, response.text
        ids.append(response.json()["id"])
    response = client.post("/api/route", json={"src": [ids[0], "out"], "dst": [ids[1], "in"], "kind": "waveguide"})
    assert response.status_code == 200, response.text
    updated = client.patch(f"/api/component/{ids[0]}", json={"params": {"scale": 2, "parameters": {"weight": 0.8}}})
    assert updated.status_code == 200, updated.text
    before = client.get("/api/scene").json()
    invalid = client.patch(f"/api/component/{ids[0]}", json={"params": {"parameters": {"weight": 2}}})
    assert invalid.status_code == 400
    assert client.get("/api/scene").json() == before
    changed = client.post("/api/parts", json={"name": NAME, "svg": SVG.replace('width="20"', 'width="19"')})
    assert changed.status_code == 400  # never silently replace a named definition
    description = client.get("/api/catalog/"+quote(NAME, safe=""), params={"definition_hash": old})
    assert description.status_code == 200
    assert client.post("/api/scene", json={"spec": before}).status_code == 200
    assert client.get("/api/render/threejs").status_code == 200
    assert client.get("/api/render/1d.svg").status_code == 200


def test_bundle_export_and_import_do_not_read_client_paths(client):
    create(client)
    response = client.get("/api/parts/export", params={"name": NAME})
    assert response.status_code == 200 and response.content.startswith(b"PK")
    reopened = client.post("/api/parts/import", content=response.content,
                           params={"filename": "../../ignored.odpart"})
    assert reopened.status_code == 200
    assert reopened.json()["name"] == NAME


def test_draft_preview_is_sanitized_and_does_not_install_a_part(client):
    response = client.post("/api/parts/inspect", json={"name": NAME, "svg": SVG})
    assert response.status_code == 200, response.text
    assert len(response.json()["ports"]) == 2
    assert "port:in" not in response.json()["svg"]
    assert NAME not in client.get("/api/parts").json()["parts"]
    unsafe = client.post("/api/parts/inspect", json={"name": NAME, "svg": SVG.replace('</svg>', '<script/></svg>')})
    assert unsafe.status_code == 400
