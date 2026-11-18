"""The 1D SVG export, the palette preview and the Check panel use the looked-up symbols."""

from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

import optodraw  # noqa: E402
from optodraw.app.server import create_app  # noqa: E402
from optodraw.symbols import lookup  # noqa: E402


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


def test_the_1d_svg_export_is_the_schematic(client):
    mzm, _ = _chain(client)
    client.put("/api/scene/1d/layout", json={mzm: [200, 30]})
    response = client.get("/api/render/1d.svg")
    assert response.status_code == 200 and response.headers["content-type"].startswith("image/svg+xml")
    root = ET.fromstring(response.text)
    assert root.get("aria-label") == "1D schematic"
    assert 'translate(200.00 30.00)' in response.text           # the saved position is used


def test_the_palette_preview_in_1d_is_the_symbol(client):
    body = client.get("/api/preview/MicroringResonator", params={"view": "1d"}).json()
    assert body["svg"] == lookup(optodraw.MicroringResonator()).svg
    assert client.get("/api/preview/GDSModel", params={"view": "1d"}).status_code == 200    # the placeholder
    assert client.get("/api/preview/MicroringResonator", params={"view": "3d"}).status_code == 400


def test_check_names_the_parts_with_no_exact_symbol(client, monkeypatch):
    _chain(client)
    kinds = [check["kind"] for check in client.post("/api/validate").json()["checks"]]
    assert "symbol" not in kinds                                # MZM and photodetector have their symbols
    monkeypatch.setattr("optodraw.symbols._request", lambda component: None)    # as if no part had a symbol
    checks = [check for check in client.post("/api/validate").json()["checks"] if check["kind"] == "symbol"]
    assert len(checks) == 2 and all(check["level"] == "info" for check in checks)
    assert any("MZM" in check["message"] and "labeled block" in check["message"] for check in checks)


def test_render_svg_in_the_1d_view_is_the_schematic(tmp_path):
    scene = optodraw.Scene(width=300, height=100, platform="on_chip")
    a = scene.add(optodraw.MZM(center=(0, 0), label="MZM"))
    b = scene.add(optodraw.OnChipPhotodetector(center=(150, 0), label="PD"))
    scene.route((a, "o3"), (b, "o1"), kind="waveguide")
    target = tmp_path / "one_d.svg"
    drawing = scene.render_svg(str(target), onchip_view="1d")
    text = drawing.as_svg()
    ET.fromstring(text)
    assert lookup(a).inner() in text                            # the same symbol as every other 1D view
    assert target.read_text(encoding="utf-8").count("<svg") == 1
    assert lookup(a).inner() not in scene.render_svg().as_svg()  # the 2D drawing is as before
    with pytest.raises(ValueError):
        scene.render_svg(onchip_view="3d")


def test_a_publication_panel_in_the_1d_view_is_the_schematic(tmp_path):
    from optodraw import build_publication_bundle

    scene = optodraw.Scene(title="one d", width=300, height=100, platform="on_chip")
    a = scene.add(optodraw.MZM(center=(0, 0), label="MZM"))
    b = scene.add(optodraw.OnChipPhotodetector(center=(150, 0), label="PD"))
    scene.route((a, "o3"), (b, "o1"), kind="waveguide")
    bundle = build_publication_bundle(scene, tmp_path, formats=("svg",), view="1d")
    assert lookup(a).inner() in bundle.panels[0]["paths"]["svg"].read_text(encoding="utf-8")
