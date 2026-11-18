"""Saving a workspace must never damage the copy already on disk.

The editor autosaves on every edit and reads the same file on every reload, so
a save that writes in place has a window where a reader sees half a file. That
window is not theoretical: it took out a real workspace, and because the server
loads the default workspace at boot, the whole editor failed to start.
"""

from __future__ import annotations


import pytest

from optodraw.app.workspaces import WorkspaceStore


@pytest.fixture
def store(tmp_path):
    return WorkspaceStore(tmp_path)


class TestCreatingAWorkspaceNeverEatsAnother:
    """Save As must not be able to destroy work under a different name.

    Names are sanitized to a filesystem stem, so "My Chip!" and "My Chip" are
    the same file. Creating the first silently emptied the second.
    """

    def test_create_refuses_a_name_already_taken(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OPTODRAW_WORKSPACE_DIR", str(tmp_path))
        from optodraw.app.session import SessionStore

        store = SessionStore()
        store.create("My Chip", {"components": [{"type": "Lens", "id": "l1", "center": [0, 0]}],
                                 "beams": [], "routes": [], "title": "My Chip",
                                 "width": 100, "height": 100})
        with pytest.raises(FileExistsError):
            store.create("My Chip")
        with pytest.raises(FileExistsError):
            store.create("My Chip!")  # sanitizes to the same file
        assert len(store.workspaces.load("My Chip")["components"]) == 1

    def test_rename_refuses_to_land_on_an_existing_workspace(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OPTODRAW_WORKSPACE_DIR", str(tmp_path))
        from optodraw.app.session import SessionStore

        store = SessionStore()
        store.create("Keep", {"components": [{"type": "Lens", "id": "l1", "center": [0, 0]}],
                              "beams": [], "routes": [], "title": "Keep",
                              "width": 100, "height": 100})
        store.create("Other")
        with pytest.raises(FileExistsError):
            store.rename("Other", "Keep")
        assert len(store.workspaces.load("Keep")["components"]) == 1
        assert "Other" in store.list()


def test_the_api_says_409_instead_of_overwriting(tmp_path, monkeypatch):
    monkeypatch.setenv("OPTODRAW_WORKSPACE_DIR", str(tmp_path))
    from fastapi.testclient import TestClient

    from optodraw.app.server import create_app

    client = TestClient(create_app())
    client.post("/api/workspaces", json={"name": "My Chip"})
    client.post("/api/component", json={"name": "Lens"})
    assert client.post("/api/workspaces", json={"name": "My Chip!"}).status_code == 409
    client.post("/api/workspaces/My Chip/open")
    assert len(client.get("/api/scene").json()["components"]) == 1
