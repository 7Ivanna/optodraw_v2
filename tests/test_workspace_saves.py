"""Saving a workspace must never damage the copy already on disk.

The editor autosaves on every edit and reads the same file on every reload, so
a save that writes in place has a window where a reader sees half a file. That
window is not theoretical: it took out a real workspace, and because the server
loads the default workspace at boot, the whole editor failed to start.
"""

from __future__ import annotations

import json
import threading
import time

import pytest

from optodraw.app.workspaces import WorkspaceStore


@pytest.fixture
def store(tmp_path):
    return WorkspaceStore(tmp_path)


def _spec(count: int) -> dict:
    return {"components": [{"id": f"c{i}", "type": "Lens", "center": [i, 0]} for i in range(count)]}


def test_a_save_that_cannot_serialize_leaves_the_old_file_alone(store):
    store.save("Untitled", _spec(3))
    with pytest.raises(TypeError):
        store.save("Untitled", {"components": [{"bad": object()}]})
    assert len(store.load("Untitled")["components"]) == 3


def test_a_reader_never_sees_half_a_file(store):
    """The autosave/reload race, run for real."""

    store.save("Untitled", _spec(4000))
    stop = threading.Event()
    failures: list[str] = []

    def write():
        while not stop.is_set():
            store.save("Untitled", _spec(4000))

    def read():
        while not stop.is_set():
            try:
                store.load("Untitled")
            except json.JSONDecodeError:
                failures.append("partial read")
                stop.set()

    writer, reader = threading.Thread(target=write), threading.Thread(target=read)
    writer.start(), reader.start()
    time.sleep(1.5)
    stop.set()
    writer.join(), reader.join()
    assert not failures


def test_no_temporary_files_are_left_behind(store, tmp_path):
    for _ in range(5):
        store.save("Untitled", _spec(50))
    assert sorted(p.name for p in tmp_path.iterdir()) == ["Untitled.json"]
    assert store.list() == ["Untitled"]


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
