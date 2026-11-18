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


def test_rename_and_delete(client: TestClient):
    client.post("/api/workspaces", json={"name": "ToRename"})
    client.put("/api/workspaces/ToRename", json={"name": "Renamed"})
    names = client.get("/api/workspaces").json()["workspaces"]
    assert "Renamed" in names and "ToRename" not in names
    client.delete("/api/workspaces/Renamed")
    assert "Renamed" not in client.get("/api/workspaces").json()["workspaces"]


def test_new_from_preset_example_alias_still_works(client: TestClient):
    # Back-compat: the deprecated ``examples`` key + ``example`` field still work.
    examples = client.get("/api/workspaces").json()["examples"]
    assert examples
    res = client.post("/api/workspaces", json={"name": "FromAlias", "example": examples[0]})
    assert res.status_code == 200
    assert len(res.json()["spec"]["components"]) > 0


def test_open_unknown_workspace_404(client: TestClient):
    assert client.post("/api/workspaces/NoSuchThing/open").status_code == 404
