"""The model that the editor's 1D view draws: symbols, ports, links and positions."""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from optodraw.app.server import create_app  # noqa: E402


@pytest.fixture()
def client() -> TestClient:
    test_client = TestClient(create_app())
    test_client.post("/api/scene/new", json={})
    return test_client


def _add(client: TestClient, name: str, **params) -> str:
    response = client.post("/api/component", json={"name": name, "params": params})
    assert response.status_code == 200, response.text
    return response.json()["id"]


def _chain(client: TestClient) -> tuple[str, str]:
    mzm = _add(client, "MZM", center=[0, 0])
    detector = _add(client, "OnChipPhotodetector", center=[150, 0])
    route = client.post("/api/route", json={"src": [mzm, "o3"], "dst": [detector, "o1"], "kind": "waveguide"})
    assert route.status_code == 200, route.text
    return mzm, detector


def test_the_model_says_which_label_goes_above_its_part(client):
    mzm = _add(client, "MZM", center=[0, 0], label="MZM")
    scope = _add(client, "Oscilloscope", center=[0, 80], label="Scope")
    assert client.post("/api/route", json={"src": [scope, "ch1"], "dst": [mzm, "sig"], "kind": "electrical"}).status_code == 200
    parts = {part["id"]: part for part in client.get("/api/scene/1d/model").json()["components"]}
    assert parts[scope]["label_above"] is True and parts[mzm]["label_above"] is False


