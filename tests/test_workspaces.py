"""Tests for persistent editor workspaces (optional ``optodraw[gui]`` extra).

The workspace dir is redirected to a temp location by ``tests/conftest.py``.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from optodraw.app.server import create_app  # noqa: E402


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app())


def test_create_edit_reopen_is_isolated(client: TestClient):
    client.post("/api/workspaces", json={"name": "WS One"})
    client.post("/api/component", json={"name": "Lens", "params": {"label": "L1"}})
    client.post("/api/workspaces", json={"name": "WS Two"})
    client.post("/api/component", json={"name": "Mirror", "params": {"label": "M1"}})

    ws = client.get("/api/workspaces").json()
    assert "WS One" in ws["workspaces"] and "WS Two" in ws["workspaces"]
    assert ws["current"] == "WS Two"

    reopened = client.post("/api/workspaces/WS One/open").json()
    assert [c.get("label") for c in reopened["spec"]["components"]] == ["L1"]


def test_autosave_persists_across_a_fresh_store(client: TestClient):
    client.post("/api/workspaces", json={"name": "Persisted"})
    client.post("/api/component", json={"name": "Lens"})
    # a fresh app instance shares the same on-disk dir -> sees the saved workspace
    fresh = TestClient(create_app())
    assert "Persisted" in fresh.get("/api/workspaces").json()["workspaces"]
    loaded = fresh.post("/api/workspaces/Persisted/open").json()
    assert len(loaded["spec"]["components"]) == 1


def test_rename_and_delete(client: TestClient):
    client.post("/api/workspaces", json={"name": "ToRename"})
    client.put("/api/workspaces/ToRename", json={"name": "Renamed"})
    names = client.get("/api/workspaces").json()["workspaces"]
    assert "Renamed" in names and "ToRename" not in names
    client.delete("/api/workspaces/Renamed")
    assert "Renamed" not in client.get("/api/workspaces").json()["workspaces"]


def test_new_from_preset(client: TestClient):
    presets = client.get("/api/workspaces").json()["presets"]
    assert presets
    res = client.post("/api/workspaces", json={"name": "FromPreset", "preset": presets[0]})
    assert res.status_code == 200
    assert len(res.json()["spec"]["components"]) > 0


def test_new_from_preset_example_alias_still_works(client: TestClient):
    # Back-compat: the deprecated ``examples`` key + ``example`` field still work.
    examples = client.get("/api/workspaces").json()["examples"]
    assert examples
    res = client.post("/api/workspaces", json={"name": "FromAlias", "example": examples[0]})
    assert res.status_code == 200
    assert len(res.json()["spec"]["components"]) > 0


def test_open_unknown_workspace_404(client: TestClient):
    assert client.post("/api/workspaces/NoSuchThing/open").status_code == 404
