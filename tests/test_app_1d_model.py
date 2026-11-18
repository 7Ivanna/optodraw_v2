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


def test_the_model_gives_each_part_its_symbol_ports_and_position(client):
    mzm, detector = _chain(client)
    model = client.get("/api/scene/1d/model").json()
    parts = {part["id"]: part for part in model["components"]}
    assert set(parts) == {mzm, detector}
    symbol = parts[mzm]["symbol"]
    assert symbol["source"] == "prebuilt" and symbol["exact"] is True
    assert symbol["svg"].startswith("<svg")
    assert {port["name"] for port in symbol["ports"]} == {"o1", "o2", "o3", "o4", "sig", "gnd"}
    assert {"x", "y", "kind", "side"} <= set(symbol["ports"][0])
    (link,) = model["links"]
    assert link.pop("route")[0] != link                         # a waveguide comes with its route
    assert link == {"start_id": mzm, "start_port": "o3", "end_id": detector, "end_port": "o1", "kind": "waveguide"}
    assert set(model["positions"]) == {mzm, detector}          # saved or automatic: every part has one
    assert model["positions"][mzm][0] < model["positions"][detector][0]


def test_a_saved_position_comes_back_and_moves_nothing_in_2d(client):
    mzm, _ = _chain(client)
    before = client.get("/api/scene").json()["components"]
    assert client.put("/api/scene/1d/layout", json={mzm: [300, 40]}).status_code == 200
    assert client.get("/api/scene/1d/model").json()["positions"][mzm] == [300.0, 40.0]
    assert client.get("/api/scene").json()["components"] == before      # no 2D position moved


def test_a_beam_between_two_parts_is_a_link(client):
    laser = _add(client, "Laser", center=[0, 80])
    lens = _add(client, "Lens", center=[80, 80])
    assert client.post("/api/beam", json={"path": [[laser, "out"], [lens, "in"]], "wavelength": 633}).status_code == 200
    links = client.get("/api/scene/1d/model").json()["links"]
    assert links == [{"start_id": laser, "start_port": "out", "end_id": lens, "end_port": "in", "kind": "free_space"}]


def test_the_model_says_which_label_goes_above_its_part(client):
    mzm = _add(client, "MZM", center=[0, 0], label="MZM")
    scope = _add(client, "Oscilloscope", center=[0, 80], label="Scope")
    assert client.post("/api/route", json={"src": [scope, "ch1"], "dst": [mzm, "sig"], "kind": "electrical"}).status_code == 200
    parts = {part["id"]: part for part in client.get("/api/scene/1d/model").json()["components"]}
    assert parts[scope]["label_above"] is True and parts[mzm]["label_above"] is False


def test_a_cable_comes_with_its_square_route(client):
    mzm = _add(client, "MZM", center=[0, 0], label="MZM")
    scope = _add(client, "Oscilloscope", center=[0, 80], label="Scope")
    assert client.post("/api/route", json={"src": [scope, "ch1"], "dst": [mzm, "sig"], "kind": "electrical"}).status_code == 200
    (link,) = client.get("/api/scene/1d/model").json()["links"]
    route = link["route"]
    assert len(route) >= 2
    assert all(abs(a[0] - b[0]) < 0.02 or abs(a[1] - b[1]) < 0.02 for a, b in zip(route, route[1:]))
