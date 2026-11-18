"""KLayout technologies in the editor: a technology folder uploaded as a .zip (the .lyt, the .lyp it names, and
d25/*.lyd25 for heights), a .lyd25 alone for heights, and a lone .lyt that says what it needs."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from optodraw.app.server import create_app

from gds_layout_fixtures import docs_device_gds

TECH = Path(pytest.importorskip("gdsfactory").__file__).parent / "generic_tech" / "klayout"


@pytest.fixture()
def client() -> TestClient:
    test_client = TestClient(create_app())
    test_client.post("/api/scene/new", json={})
    return test_client


def _part(client, tmp_path) -> str:
    data = docs_device_gds(tmp_path).read_bytes()
    return client.post("/api/gds/import", params={"filename": "straight_pn.gds"}, content=data).json()["id"]


def _zip(members: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def _layer(client, gid, key):
    return next(r for r in client.get(f"/api/gds/{gid}/layers").json()["layers"] if r["key"] == key)


def test_a_technology_folder_as_a_zip_gives_colours_and_heights(client, tmp_path):
    gid = _part(client, tmp_path)
    archive = _zip({"generic/tech.lyt": (TECH / "tech.lyt").read_bytes(),
                    "generic/layers.lyp": (TECH / "layers.lyp").read_bytes(),
                    "generic/d25/generic_tech.lyd25": (TECH / "d25" / "generic_tech.lyd25").read_bytes()})
    res = client.post(f"/api/gds/{gid}/technology", params={"filename": "generic.zip"}, content=archive)
    assert res.status_code == 200, res.text
    metal3 = _layer(client, gid, "49/0")
    assert metal3["z"] == pytest.approx(3.2) and metal3["thickness"] == pytest.approx(2.0)
    assert metal3["color"].startswith("#")


def test_a_lone_lyt_says_which_file_it_needs(client, tmp_path):
    gid = _part(client, tmp_path)
    res = client.post(f"/api/gds/{gid}/technology", params={"filename": "tech.lyt"}, content=(TECH / "tech.lyt").read_bytes())
    assert res.status_code == 400
    detail = res.json()["detail"]
    assert "layers.lyp" in detail and "Attach technology folder" in detail and ".zip" in detail


def _folder(*names: str) -> list[dict[str, str]]:
    """The files the editor sends for a picked folder: each with its path in the folder, as text."""

    return [{"path": f"klayout/{name}", "text": (TECH / name).read_text(encoding="utf-8")} for name in names]


def test_a_technology_folder_picked_in_the_browser_gives_colours_and_heights(client, tmp_path):
    gid = _part(client, tmp_path)
    res = client.post(f"/api/gds/{gid}/technology_folder",
                      json={"files": _folder("tech.lyt", "layers.lyp", "d25/generic_tech.lyd25")})
    assert res.status_code == 200, res.text
    metal3 = _layer(client, gid, "49/0")
    assert metal3["z"] == pytest.approx(3.2) and metal3["thickness"] == pytest.approx(2.0)
    assert metal3["color"].startswith("#")


def test_a_folder_file_that_climbs_out_of_the_folder_is_refused(client, tmp_path):
    gid = _part(client, tmp_path)
    res = client.post(f"/api/gds/{gid}/technology_folder", json={"files": [{"path": "../evil.lyt", "text": "<technology/>"}]})
    assert res.status_code == 400 and "unsafe" in res.json()["detail"]


def test_a_folder_without_a_lyt_or_lyd25_says_so(client, tmp_path):
    gid = _part(client, tmp_path)
    res = client.post(f"/api/gds/{gid}/technology_folder", json={"files": _folder("layers.lyp")})
    assert res.status_code == 400 and "no .lyt or .lyd25" in res.json()["detail"]


def test_a_lyd25_alone_gives_heights(client, tmp_path):
    gid = _part(client, tmp_path)
    res = client.post(f"/api/gds/{gid}/technology", params={"filename": "generic_tech.lyd25"},
                      content=(TECH / "d25" / "generic_tech.lyd25").read_bytes())
    assert res.status_code == 200, res.text
    assert _layer(client, gid, "41/0")["thickness"] == pytest.approx(0.7)


def test_a_zip_that_climbs_out_of_its_folder_is_refused(client, tmp_path):
    gid = _part(client, tmp_path)
    res = client.post(f"/api/gds/{gid}/technology", params={"filename": "evil.zip"},
                      content=_zip({"../evil.lyt": b"<technology/>"}))
    assert res.status_code == 400 and "unsafe" in res.json()["detail"]


def test_the_editor_offers_the_new_kinds_of_technology_file():
    html = (Path(__file__).resolve().parents[1] / "optodraw" / "app" / "static" / "index.html").read_text(encoding="utf-8")
    accept = html.split('id="file-tech"', 1)[1].split(">", 1)[0]
    assert ".zip" in accept and ".lyd25" in accept and ".lyt" in accept
    folder = html.split('id="folder-tech"', 1)[1].split(">", 1)[0]       # the browser's folder dialog
    assert "webkitdirectory" in folder


def test_a_layer_with_no_height_reports_none_not_a_made_up_one(client, tmp_path):
    """The docs device's implant layers (20/0, 21/0, 24/0) have no height in the generic styles or in the
    technology: their records say so, where they used to show the part's default thickness at z 0."""

    gid = _part(client, tmp_path)
    implant = _layer(client, gid, "20/0")
    assert implant["thickness"] is None and implant["z"] is None
    waveguide = _layer(client, gid, "1/0")
    assert waveguide["thickness"] == pytest.approx(0.22) and waveguide["z"] == pytest.approx(0.0)
    res = client.post(f"/api/gds/{gid}/technology_folder",
                      json={"files": _folder("tech.lyt", "layers.lyp", "d25/generic_tech.lyd25")})
    assert res.status_code == 200, res.text
    implant = _layer(client, gid, "20/0")
    assert implant["thickness"] is None and implant["z"] is None and implant["color"].startswith("#")


def test_a_part_with_layers_of_no_height_still_exports_to_glb(tmp_path):
    pytest.importorskip("trimesh")
    from optodraw import Scene
    from optodraw.components.models import GDSModel
    from optodraw.exporters import scene_to_glb_with_report

    scene = Scene(width=200, height=200)
    scene.add(GDSModel(source=str(docs_device_gds(tmp_path))))
    _, report = scene_to_glb_with_report(scene)
    assert report["meshes"] >= 1 and report["failed"] == []


def test_a_layer_with_no_material_reports_none_not_the_part_default(client, tmp_path):
    """The implant layers have no material in the generic styles: their records say so, where they showed the
    part's own material_preset ("silicon"); a layer the styles give a material keeps it."""

    gid = _part(client, tmp_path)
    assert _layer(client, gid, "20/0")["material"] is None
    assert _layer(client, gid, "1/0")["material"] == "silicon"
    assert _layer(client, gid, "41/0")["material"] == "aluminum"
