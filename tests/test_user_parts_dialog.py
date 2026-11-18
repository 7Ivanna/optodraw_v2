"""The dialog's 3D preview must return a usable schematic page."""
from fastapi.testclient import TestClient

from optodraw.app import api
from optodraw.app.server import create_app
from optodraw.app.session import SessionStore
from optodraw.app.workspaces import WorkspaceStore


def test_dialog_3d_preview(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "_store", SessionStore(workspace_store=WorkspaceStore(tmp_path)))
    with TestClient(create_app()) as client:
        response = client.post("/api/parts/threejs", json={
            "name": "user:my/Box", "platform": "on_chip", "ports": [],
            "svg": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 20"><rect x="5" y="5" width="30" height="10" fill="none" stroke="black"/></svg>',
        })
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/html")
    assert "svg_extrusion" in response.text
