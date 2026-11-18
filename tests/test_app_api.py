"""Tests for the optodraw editor backend (optional ``optodraw[gui]`` extra).

Guarded with ``importorskip`` so the suite stays green without FastAPI installed.
The handlers are thin adapters over registry/schema/renderers, so these tests
exercise the create -> edit -> move -> render -> round-trip loop end to end.
"""

from __future__ import annotations

import struct

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from optodraw.app.server import create_app  # noqa: E402


@pytest.fixture()
def client() -> TestClient:
    app = create_app()
    test_client = TestClient(app)
    # The session store is process-global; start each test from a clean scene.
    test_client.post("/api/scene/new", json={})
    return test_client


def test_health_reports_version(client: TestClient):
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"]


def test_catalog_lists_components_and_categories(client: TestClient):
    body = client.get("/api/catalog").json()
    assert "Lens" in body["components"]
    assert isinstance(body["categories"], list)
    assert "optics" in body["categories"]


def test_catalog_filter_by_platform(client: TestClient):
    body = client.get("/api/catalog", params={"platform": "on_chip"}).json()
    assert all(
        info.get("platform") in {"on_chip", "mixed"} for info in body["components"].values()
    )


def test_describe_component_has_parameters(client: TestClient):
    body = client.get("/api/catalog/Lens").json()
    assert "parameters" in body
    assert "focal_length" in body["parameters"]


def test_describe_unknown_component_404(client: TestClient):
    assert client.get("/api/catalog/NoSuchThing").status_code == 404


def test_create_component_returns_id_and_taggable_svg(client: TestClient):
    response = client.post(
        "/api/component",
        json={"name": "Lens", "params": {"center": [0, 0], "focal_length": 50, "label": "L1"}},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["id"].startswith("lens_")
    # The editable SVG tags the component group so the front-end can select it.
    assert f'data-component-id="{body["id"]}"' in body["svg"]
    assert len(body["spec"]["components"]) == 1


def test_create_unknown_component_400(client: TestClient):
    assert client.post("/api/component", json={"name": "NotAComponent"}).status_code == 400


def test_create_tolerates_unknown_param(client: TestClient):
    # optodraw constructors accept **kwargs and ignore unknown keys; the editor
    # inherits that lenient, forward-compatible behavior.
    response = client.post(
        "/api/component", json={"name": "Lens", "params": {"nonexistent_kwarg": 1}}
    )
    assert response.status_code == 200


def test_update_component_merges_params(client: TestClient):
    cid = client.post("/api/component", json={"name": "Lens", "params": {"focal_length": 50}}).json()["id"]
    body = client.patch(f"/api/component/{cid}", json={"params": {"focal_length": 80}}).json()
    entry = next(c for c in body["spec"]["components"] if c["id"] == cid)
    assert entry["focal_length"] == 80


def test_update_unknown_component_404(client: TestClient):
    assert client.patch("/api/component/ghost", json={"params": {}}).status_code == 404


def test_move_component_sets_center_and_angle(client: TestClient):
    cid = client.post("/api/component", json={"name": "Mirror"}).json()["id"]
    body = client.post(f"/api/component/{cid}/move", json={"center": [12, -7], "angle": 45}).json()
    entry = next(c for c in body["spec"]["components"] if c["id"] == cid)
    assert entry["center"] == [12.0, -7.0]
    assert entry["angle"] == 45.0


def test_delete_component(client: TestClient):
    cid = client.post("/api/component", json={"name": "Lens"}).json()["id"]
    body = client.delete(f"/api/component/{cid}").json()
    assert all(c["id"] != cid for c in body["spec"]["components"])


def test_scene_roundtrip_load_and_get(client: TestClient):
    client.post("/api/component", json={"name": "Lens", "params": {"label": "A"}})
    client.post("/api/component", json={"name": "Mirror", "params": {"label": "B"}})
    spec = client.get("/api/scene").json()
    assert len(spec["components"]) == 2

    # Load the spec back into a fresh app and confirm it renders.
    fresh = TestClient(create_app())
    loaded = fresh.post("/api/scene", json={"spec": spec})
    assert loaded.status_code == 200
    assert len(loaded.json()["spec"]["components"]) == 2


def test_scene_meta_sets_background_and_grid(client: TestClient):
    body = client.patch(
        "/api/scene/meta", json={"title": "My Rig", "background": "#0b1020", "grid": 24}
    ).json()
    spec = body["spec"]
    assert spec["title"] == "My Rig"
    assert spec["background"] == "#0b1020"
    assert spec["grid"] == 24


def test_load_preset_seeds_scene(client: TestClient):
    body = client.post("/api/scene/preset", json={"name": "confocal_pl"}).json()
    types = {c["type"] for c in body["spec"]["components"]}
    assert "BeamSplitter" in types or "Objective" in types  # confocal parts present
    assert len(body["spec"]["beams"]) >= 1


def test_load_preset_unknown_404(client: TestClient):
    assert client.post("/api/scene/preset", json={"name": "nope"}).status_code == 404


def test_load_preset_example_endpoint_alias(client: TestClient):
    # Back-compat: the deprecated /scene/example endpoint still seeds the scene.
    body = client.post("/api/scene/example", json={"name": "confocal_pl"}).json()
    assert len(body["spec"]["components"]) > 0


def test_workspaces_lists_presets_and_examples_alias(client: TestClient):
    data = client.get("/api/workspaces").json()
    assert data["presets"]  # canonical
    assert data["examples"] == data["presets"]  # deprecated alias mirrors it


def test_load_invalid_spec_400(client: TestClient):
    bad = client.post("/api/scene", json={"spec": {"components": [{"type": "Nope"}]}})
    assert bad.status_code == 400


def test_render_svg_and_tikz(client: TestClient):
    client.post("/api/component", json={"name": "Lens"})
    svg = client.get("/api/render/svg").json()["svg"]
    assert svg.lstrip().startswith("<")
    tikz = client.get("/api/render/tikz").text
    assert "tikzpicture" in tikz or "begin" in tikz


def test_unique_ids_across_same_type(client: TestClient):
    a = client.post("/api/component", json={"name": "Lens"}).json()["id"]
    b = client.post("/api/component", json={"name": "Lens"}).json()["id"]
    assert a != b


def test_materials_endpoint_lists_presets(client: TestClient):
    presets = client.get("/api/materials").json()["presets"]
    assert isinstance(presets, list)
    assert "glass" in presets


def test_new_components_land_on_optical_axis(client: TestClient):
    a = client.post("/api/component", json={"name": "Lens"}).json()
    b = client.post("/api/component", json={"name": "Mirror"}).json()
    ea = next(c for c in a["spec"]["components"] if c["id"] == a["id"])
    eb = next(c for c in b["spec"]["components"] if c["id"] == b["id"])
    assert ea["center"][1] == 0.0 and eb["center"][1] == 0.0  # same plane
    assert ea["center"][0] != eb["center"][0]  # stepped, not stacked


def test_style_params_persist_in_session(client: TestClient):
    cid = client.post("/api/component", json={"name": "Lens"}).json()["id"]
    client.patch(f"/api/component/{cid}", json={"params": {"color": "#ff0000", "opacity": 0.3}})
    entry = next(c for c in client.get("/api/scene").json()["components"] if c["id"] == cid)
    assert entry["color"] == "#ff0000"
    assert entry["opacity"] == 0.3


# Sources auto-trace on placement (Optiverse-style live rays), so tests about
# MANUAL beams filter the traced-bundle entries out; trace tests keep chief rays.
def _manual_beams(spec):
    return [b for b in spec.get("beams", []) if not b.get("traced_from")]


def _chief_beams(spec):
    return [b for b in spec.get("beams", []) if b.get("traced_from") and not b.get("ray")]


def test_beam_connects_components_and_is_selectable(client: TestClient):
    a = client.post("/api/component", json={"name": "Laser"}).json()["id"]
    b = client.post("/api/component", json={"name": "Mirror"}).json()["id"]
    beam = client.post("/api/beam", json={"path": [a, b], "wavelength": 532}).json()
    assert beam["id"].startswith("beam_")
    assert len(_manual_beams(beam["spec"])) == 1
    # the beam is tagged in the editable SVG so the canvas can select it
    assert f'data-component-id="{beam["id"]}"' in beam["svg"]


def test_beam_requires_two_endpoints(client: TestClient):
    a = client.post("/api/component", json={"name": "Laser"}).json()["id"]
    assert client.post("/api/beam", json={"path": [a]}).status_code == 400


def test_beam_unknown_ref_400(client: TestClient):
    assert client.post("/api/beam", json={"path": ["ghost1", "ghost2"]}).status_code == 400


def test_update_and_delete_beam(client: TestClient):
    a = client.post("/api/component", json={"name": "Laser"}).json()["id"]
    b = client.post("/api/component", json={"name": "Camera"}).json()["id"]
    beam_id = client.post("/api/beam", json={"path": [a, b]}).json()["id"]
    # beams update through the same generic endpoint
    updated = client.patch(f"/api/component/{beam_id}", json={"params": {"wavelength": 405}}).json()
    entry = next(x for x in updated["spec"]["beams"] if x["id"] == beam_id)
    assert entry["wavelength"] == 405
    # and delete through the same generic endpoint
    after = client.delete(f"/api/component/{beam_id}").json()
    assert _manual_beams(after["spec"]) == []


def test_ports_endpoint_returns_world_ports(client: TestClient):
    laser = client.post("/api/component", json={"name": "Laser", "params": {"center": [-50, 0]}}).json()["id"]
    cam = client.post("/api/component", json={"name": "Camera", "params": {"center": [50, 0]}}).json()["id"]
    ports = client.get("/api/ports").json()["ports"]
    assert any(p["name"] == "out" for p in ports[laser])
    assert any(p["name"] == "in" for p in ports[cam])
    # ports sit at device faces (world), not the centers
    out = next(p for p in ports[laser] if p["name"] == "out")
    assert out["x"] != -50


def test_beam_attaches_to_ports(client: TestClient):
    laser = client.post("/api/component", json={"name": "Laser", "params": {"center": [-50, 0]}}).json()["id"]
    cam = client.post("/api/component", json={"name": "Camera", "params": {"center": [50, 0]}}).json()["id"]
    beam = client.post("/api/beam", json={"path": [[laser, "out"], [cam, "in"]], "wavelength": 532}).json()
    assert beam["id"].startswith("beam_")
    manual = _manual_beams(beam["spec"])
    assert len(manual) == 1
    # the stored path keeps the port references (so the beam follows the device)
    assert manual[0]["path"] == [[laser, "out"], [cam, "in"]]


def test_route_connects_onchip_ports(client: TestClient):
    gc = client.post("/api/component", json={"name": "VerticalGratingCoupler"}).json()["id"]
    pd = client.post("/api/component", json={"name": "OnChipPhotodetector"}).json()["id"]
    ports = client.get("/api/ports").json()["ports"]
    src_port = ports[gc][0]["name"]
    dst_port = ports[pd][0]["name"]
    route = client.post(
        "/api/route", json={"src": [gc, src_port], "dst": [pd, dst_port], "kind": "waveguide"}
    ).json()
    assert route["id"].startswith("route_")
    assert len(route["spec"]["routes"]) == 1


def test_preview_endpoint_renders_svg(client: TestClient):
    svg = client.get("/api/preview/Lens").json()["svg"]
    assert svg.lstrip().startswith("<")
    assert "<svg" in svg


def test_route_path_type_and_waypoints(client: TestClient):
    gc = client.post("/api/component", json={"name": "VerticalGratingCoupler", "params": {"center": [-40, 0]}}).json()["id"]
    pd = client.post("/api/component", json={"name": "OnChipPhotodetector", "params": {"center": [40, 20]}}).json()["id"]
    ports = client.get("/api/ports").json()["ports"]
    sp, dp = ports[gc][0]["name"], ports[pd][0]["name"]
    route = client.post(
        "/api/route",
        json={
            "src": [gc, sp], "dst": [pd, dp], "kind": "waveguide",
            "path_type": "manhattan", "smooth": True, "waypoints": [[0, -15]],
        },
    ).json()
    entry = route["spec"]["routes"][0]
    assert entry["path_type"] == "manhattan"
    assert entry["steps"] == [{"x": 0.0, "y": -15.0}]


def test_update_route_waypoints_reshapes(client: TestClient):
    gc = client.post("/api/component", json={"name": "VerticalGratingCoupler", "params": {"center": [-40, 0]}}).json()["id"]
    pd = client.post("/api/component", json={"name": "OnChipPhotodetector", "params": {"center": [40, 20]}}).json()["id"]
    ports = client.get("/api/ports").json()["ports"]
    sp, dp = ports[gc][0]["name"], ports[pd][0]["name"]
    rid = client.post("/api/route", json={"src": [gc, sp], "dst": [pd, dp], "kind": "waveguide", "path_type": "manhattan"}).json()["id"]
    # drag-to-reroute: pull the waveguide through a new interior waypoint
    res = client.patch(f"/api/route/{rid}", json={"waypoints": [[5, -25]]})
    assert res.status_code == 200
    entry = next(r for r in res.json()["spec"]["routes"] if r["id"] == rid)
    assert entry["steps"] == [{"x": 5.0, "y": -25.0}]


def test_update_route_unknown_404(client: TestClient):
    assert client.patch("/api/route/nope", json={"waypoints": [[0, 0]]}).status_code == 404


def test_route_defaults_local_backend_and_port_width(client: TestClient):
    gc = client.post("/api/component", json={"name": "VerticalGratingCoupler", "params": {"center": [-40, 0]}}).json()["id"]
    pd = client.post("/api/component", json={"name": "OnChipPhotodetector", "params": {"center": [40, 20]}}).json()["id"]
    ports = client.get("/api/ports").json()["ports"]
    sp, dp = ports[gc][0]["name"], ports[pd][0]["name"]
    entry = client.post("/api/route", json={"src": [gc, sp], "dst": [pd, dp], "kind": "waveguide", "path_type": "manhattan"}).json()["spec"]["routes"][0]
    # local backend honors path_type (gdsfactory ignores it) and matches the mesh generators
    assert entry["backend"] == "local"
    # width omitted → derived from the ports, so manual routes match auto-generated ones
    assert "width" not in entry


def test_beam_with_waypoints(client: TestClient):
    a = client.post("/api/component", json={"name": "Laser", "params": {"center": [-50, 0]}}).json()["id"]
    b = client.post("/api/component", json={"name": "Camera", "params": {"center": [50, 0]}}).json()["id"]
    beam = client.post(
        "/api/beam", json={"path": [[a, "out"], [0, 20], [b, "in"]]}
    ).json()
    assert _manual_beams(beam["spec"])[0]["path"] == [[a, "out"], [0, 20], [b, "in"]]


def test_threejs_editable_has_selection_bridge(client: TestClient):
    client.post("/api/component", json={"name": "Lens"})
    html = client.get("/api/render/threejs", params={"editable": "true"}).text
    assert "optodraw-select" in html  # the postMessage selection bridge
    assert "window.__odPickables" in html
    # default (export) render stays clean, no editor bridge
    assert "optodraw-select" not in client.get("/api/render/threejs").text


def test_gds_import_adds_model(client: TestClient):
    import pathlib

    gds = pathlib.Path("examples/assets/demo_mask.gds")
    if not gds.exists():
        pytest.skip("sample GDS not present")
    res = client.post(
        "/api/gds/import", params={"filename": "demo_mask.gds"}, content=gds.read_bytes()
    )
    assert res.status_code == 200
    body = res.json()
    assert body["id"].startswith("gdsmodel_")
    entry = next(c for c in body["spec"]["components"] if c["id"] == body["id"])
    assert entry["type"] == "GDSModel"


def test_gds_import_grows_the_frame_to_hold_the_die(client: TestClient):
    """A die is bigger than a fresh artboard, and the frame is what an export
    gets cropped to — so importing one used to hand you half a chip."""

    import pathlib

    gds = pathlib.Path("examples/assets/demo_mask.gds")
    if not gds.exists():
        pytest.skip("sample GDS not present")

    client.post("/api/scene/new", json={"width": 200, "height": 120})
    client.post("/api/gds/import", params={"filename": "demo_mask.gds"}, content=gds.read_bytes())
    assert not [c for c in client.post("/api/validate").json()["checks"] if c["kind"] == "frame"]

    # a frame somebody has already worked in is theirs: a later import leaves it
    client.post("/api/component", json={"name": "Lens", "params": {"center": [0, 0]}})
    width = client.get("/api/scene").json()["width"]
    client.post("/api/gds/import", params={"filename": "demo_mask.gds"}, content=gds.read_bytes())
    assert client.get("/api/scene").json()["width"] == width


def test_gds_import_rejects_empty(client: TestClient):
    assert client.post("/api/gds/import", content=b"").status_code == 400


def test_model_import_adds_custom_model(client: TestClient):
    obj = b"v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n"
    res = client.post("/api/model/import", params={"filename": "tri.obj"}, content=obj)
    assert res.status_code == 200
    body = res.json()
    assert body["id"].startswith("custommodel_")
    entry = next(c for c in body["spec"]["components"] if c["id"] == body["id"])
    assert entry["type"] == "CustomModel"


def test_model_import_rejects_empty(client: TestClient):
    assert client.post("/api/model/import", content=b"").status_code == 400


def test_route_text_creates_colored_beams(client: TestClient):
    laser = client.post("/api/component", json={"name": "Laser", "params": {"center": [-40, 0]}}).json()["id"]
    mirror = client.post("/api/component", json={"name": "Mirror", "params": {"center": [0, 0], "angle": 45}}).json()["id"]
    # numeric prefix sets wavelength/color; unprefixed uses the default wavelength
    text = f"532: {laser}.out -> {mirror}.io"
    res = client.post("/api/route/text", json={"text": text, "wavelength": 780})
    assert res.status_code == 200
    body = res.json()
    assert body["created"] == 1
    assert body["errors"] == []
    beam = next(b for b in body["spec"]["beams"] if b.get("from_text"))
    assert beam["wavelength"] == 532

    # re-applying reconciles (replaces text links) and the default applies when unprefixed
    res2 = client.post("/api/route/text", json={"text": f"{laser}.out -> {mirror}.io", "wavelength": 780})
    beams = [b for b in res2.json()["spec"]["beams"] if b.get("from_text")]
    assert len(beams) == 1
    assert beams[0]["wavelength"] == 780


def test_route_text_reports_errors(client: TestClient):
    client.post("/api/component", json={"name": "Laser", "params": {"center": [-40, 0]}})
    body = client.post("/api/route/text", json={"text": "ghost.out -> nowhere.in"}).json()
    assert body["created"] == 0
    assert any("unknown component" in e for e in body["errors"])


def test_gds_layers_and_visibility_override(client: TestClient):
    import pathlib

    gds = pathlib.Path("examples/assets/demo_mask.gds")
    if not gds.exists():
        pytest.skip("sample GDS not present")
    gid = client.post(
        "/api/gds/import", params={"filename": "demo_mask.gds"}, content=gds.read_bytes()
    ).json()["id"]
    layers = client.get(f"/api/gds/{gid}/layers").json()["layers"]
    assert layers and all({"key", "name", "color", "visible"} <= set(ly) for ly in layers)
    # hide one layer via a layer_stack override and confirm it persists
    key = layers[0]["key"]
    client.patch(f"/api/component/{gid}", json={"params": {"layer_stack": {key: {"visible": False}}}})
    after = {ly["key"]: ly["visible"] for ly in client.get(f"/api/gds/{gid}/layers").json()["layers"]}
    assert after[key] is False


def test_gds_cross_section_renders(client: TestClient):
    import pathlib

    gds = pathlib.Path("examples/assets/demo_mask.gds")
    if not gds.exists():
        pytest.skip("sample GDS not present")
    gid = client.post(
        "/api/gds/import", params={"filename": "demo_mask.gds"}, content=gds.read_bytes()
    ).json()["id"]
    res = client.post(f"/api/gds/{gid}/cross_section", json={"label": "A-A'"})
    assert res.status_code == 200
    body = res.json()
    assert body["format"] == "svg"
    assert body["cross_section"].lstrip().startswith("<svg")
    assert body["top_view"].lstrip().startswith("<svg")
    assert len(body["bounds"]) == 4
    # default cut sits at the GDS center in x
    xmin, ymin, xmax, ymax = body["bounds"]
    assert body["cut"]["x"] == pytest.approx((xmin + xmax) / 2)

    # a ruler (arbitrary-angle) cut is accepted and also returns SVG
    yc = (ymin + ymax) / 2
    rres = client.post(
        f"/api/gds/{gid}/cross_section",
        json={"line": [xmin + 1, yc, xmax - 1, yc], "label": "R"},
    )
    assert rres.status_code == 200
    assert rres.json()["cross_section"].lstrip().startswith("<svg")


def _demo_gds(client: TestClient) -> str:
    import pathlib

    gds = pathlib.Path("examples/assets/demo_mask.gds")
    if not gds.exists():
        pytest.skip("sample GDS not present")
    return client.post("/api/gds/import", params={"filename": "demo_mask.gds"}, content=gds.read_bytes()).json()["id"]


def test_gds_cross_section_runs_the_process_and_lists_its_looks(client: TestClient):
    from optodraw.gds.xsection.model import CrossSection

    gid = _demo_gds(client)
    body = client.post(f"/api/gds/{gid}/cross_section", json={"label": "A-A'"}).json()
    assert body["look"] == "schematic" and body["format"] == "svg"
    assert 'class="region"' in body["cross_section"]                       # look A, from the process engine
    assert body["looks"][:2] == ["schematic", "slab"]
    assert ("sem" in body["looks"]) == hasattr(CrossSection, "png")
    assert isinstance(body["findings"], list)


def test_gds_cross_section_slab_look_is_an_interactive_page(client: TestClient):
    gid = _demo_gds(client)
    body = client.post(f"/api/gds/{gid}/cross_section", json={"look": "slab"}).json()
    assert body["look"] == "slab" and body["format"] == "html"
    assert body["cross_section"].startswith("<!DOCTYPE html>") and "extruded_polygon" in body["cross_section"]
    assert body["top_view"].lstrip().startswith("<svg")


def test_gds_cross_section_sem_look_only_when_the_model_draws_it(client: TestClient):
    from optodraw.gds.xsection.model import CrossSection

    gid = _demo_gds(client)
    res = client.post(f"/api/gds/{gid}/cross_section", json={"look": "sem"})
    if hasattr(CrossSection, "png"):
        assert res.status_code == 200 and res.json()["cross_section"].startswith("data:image/png;base64,")
    else:
        assert res.status_code == 400 and "SEM" in res.json()["detail"]
    assert client.post(f"/api/gds/{gid}/cross_section", json={"look": "photo"}).status_code == 400


def test_gds_cross_section_uses_the_stack_the_part_carries(client: TestClient):
    from optodraw.app.api import _find_gds_node, _gds_layout_and_stack

    gid = _demo_gds(client)
    client.post(f"/api/gds/{gid}/stack", json={"name": "gdsfactory_generic"})
    layout, stack = _gds_layout_and_stack(_find_gds_node(gid))
    assert (stack.oxide["box_depth"], stack.oxide["cladding_top"]) == (3.0, 3.0)
    assert stack.styles[(1, 0)]["thickness"] == pytest.approx(0.22) and stack.styles[(40, 0)]["role"] == "contact"
    assert {record.spec for record in layout.layer_records} == {(1, 0), (2, 0), (3, 0)}
    body = client.post(f"/api/gds/{gid}/cross_section", json={}).json()
    assert not [f for f in body["findings"] if "no entry" in f]


def test_gds_part_keeps_the_stack_passivation_for_its_cut(client: TestClient):
    # the editor's cut must be the stack's cut: the part kept the BOX and the cladding but dropped the
    # passivation and its material, so the editor drew no passivation where Python drew one
    from optodraw.app.api import _find_gds_node, _gds_layout_and_stack
    from optodraw.gds.xsection.model import cross_section

    gid = _demo_gds(client)
    client.post(f"/api/gds/{gid}/stack", json={"name": "gdsfactory_generic"})
    layout, stack = _gds_layout_and_stack(_find_gds_node(gid))
    assert stack.oxide["passivation"] == pytest.approx(0.5) and stack.passivation_material == "sio2"
    xmin, ymin, xmax, ymax = layout.bounds
    xs = cross_section(layout, stack, (((xmin + xmax) / 2, ymin), ((xmin + xmax) / 2, ymax)))
    # the passivation is oxide, so it is one body with the cladding: the oxide rises by its thickness
    assert xs.regions["oxide"].bounds[3] >= stack.oxide["cladding_top"] + 0.5 - 1e-6


def _png_size(data_url: str) -> tuple[int, int]:
    import base64
    import io

    from PIL import Image

    return Image.open(io.BytesIO(base64.b64decode(data_url.split(",", 1)[1]))).size


def test_gds_cross_section_top_look_shows_a_square_round_the_cut(client: TestClient):
    gid = _demo_gds(client)
    client.post(f"/api/gds/{gid}/stack", json={"name": "gdsfactory_generic"})
    first = client.post(f"/api/gds/{gid}/cross_section", json={"look": "top"}).json()
    xmin, ymin, xmax, ymax = first["bounds"]
    line = [xmin + 2.0, (ymin + ymax) / 2, xmin + 12.0, (ymin + ymax) / 2]     # a 10 um cut
    body = client.post(f"/api/gds/{gid}/cross_section",
                       json={"look": "top", "line": line, "width_px": 240, "tilt": 30, "stage": "chip"}).json()
    assert "top" in body["looks"] and body["look"] == "top" and body["format"] == "png"
    assert _png_size(body["cross_section"])[0] == 240
    x0, y0, x1, y1 = body["region"]
    assert (x1 - x0, y1 - y0) == (pytest.approx(10.0), pytest.approx(10.0))
    assert ((x0 + x1) / 2, (y0 + y1) / 2) == (pytest.approx(xmin + 7.0), pytest.approx((ymin + ymax) / 2))
    assert "stroke-dasharray" in body["top_view"]                       # the square drawn on the layout


def test_gds_cross_section_top_look_reuses_its_cuts_when_only_the_tilt_changes(client: TestClient, monkeypatch):
    from optodraw.gds.xsection import top

    built = []
    original = top._build_maps
    monkeypatch.setattr(top, "_build_maps", lambda *a, **k: built.append(1) or original(*a, **k))
    gid = _demo_gds(client)
    for tilt in (0, 45):
        assert client.post(f"/api/gds/{gid}/cross_section",
                           json={"look": "top", "width_px": 200, "tilt": tilt}).status_code == 200
    assert len(built) == 1
    client.post(f"/api/gds/{gid}/cross_section", json={"look": "top", "width_px": 200, "rotation": 30})
    assert len(built) == 2                                              # a turn cuts again


def test_gds_cross_section_options_reach_each_look(client: TestClient):
    gid = _demo_gds(client)
    true = client.post(f"/api/gds/{gid}/cross_section", json={"z_scale": 1}).json()["cross_section"]
    stretched = client.post(f"/api/gds/{gid}/cross_section", json={"z_scale": 5}).json()["cross_section"]
    assert "z × 5" in stretched and "z ×" not in true
    sem = client.post(f"/api/gds/{gid}/cross_section", json={"look": "sem", "width_px": 300}).json()
    plain = client.post(f"/api/gds/{gid}/cross_section", json={"look": "sem", "width_px": 300, "mark": False}).json()
    assert _png_size(sem["cross_section"])[0] == 300 and sem["cross_section"] != plain["cross_section"]
    slab = client.post(f"/api/gds/{gid}/cross_section", json={"look": "slab", "depth": 3.0, "cutaway": False})
    assert slab.status_code == 200 and slab.json()["format"] == "html"


def test_gds_cross_section_text_has_no_dashes(client: TestClient):
    gid = _demo_gds(client)
    body = client.post(f"/api/gds/{gid}/cross_section", json={}).json()
    for text in (body["top_view"], body["cut"]["label"]):
        assert "\u2014" not in text and "\u2013" not in text


def test_gds_cross_section_unknown_404(client: TestClient):
    assert client.post("/api/gds/ghost/cross_section", json={}).status_code == 404


def test_gds_attach_technology_recolors_layers(client: TestClient):
    import pathlib

    gds = pathlib.Path("examples/assets/demo_mask.gds")
    if not gds.exists():
        pytest.skip("sample GDS not present")
    gid = client.post(
        "/api/gds/import", params={"filename": "demo_mask.gds"}, content=gds.read_bytes()
    ).json()["id"]
    lyp = (
        b'<?xml version="1.0"?><layer-properties>'
        b"<properties><name>WG</name><source>1/0@1</source><fill-color>#ff0000</fill-color></properties>"
        b"<properties><name>SLAB</name><source>2/0@1</source><fill-color>#00ccff</fill-color></properties>"
        b"</layer-properties>"
    )
    res = client.post(f"/api/gds/{gid}/technology", params={"filename": "demo.lyp"}, content=lyp)
    assert res.status_code == 200
    body = res.json()
    assert body["applied"] >= 2
    colors = {ly["key"]: ly["color"] for ly in body["layers"]}
    assert colors.get("1/0") == "#ff0000"
    assert colors.get("2/0") == "#00ccff"


def test_lyp_does_not_inject_fake_z(client: TestClient):
    import pathlib

    gds = pathlib.Path("examples/assets/demo_mask.gds")
    if not gds.exists():
        pytest.skip("sample GDS not present")
    gid = client.post(
        "/api/gds/import", params={"filename": "demo_mask.gds"}, content=gds.read_bytes()
    ).json()["id"]
    lyp = (
        b'<?xml version="1.0"?><layer-properties>'
        b"<properties><name>WG</name><source>1/0@1</source><fill-color>#ff0000</fill-color></properties>"
        b"</layer-properties>"
    )
    body = client.post(f"/api/gds/{gid}/technology", params={"filename": "x.lyp"}, content=lyp).json()
    entry = next(c for c in body["spec"]["components"] if c["id"] == gid)
    ov = entry["layer_stack"]["1/0"]
    assert ov.get("color") == "#ff0000"  # colors apply
    assert "zmin" not in ov and "thickness" not in ov and "z_offset" not in ov  # no fake z


def test_reset_gds_layers_clears_overrides(client: TestClient):
    import pathlib

    gds = pathlib.Path("examples/assets/demo_mask.gds")
    if not gds.exists():
        pytest.skip("sample GDS not present")
    gid = client.post(
        "/api/gds/import", params={"filename": "demo_mask.gds"}, content=gds.read_bytes()
    ).json()["id"]
    client.post(f"/api/gds/{gid}/stack", json={"name": "gdsfactory_generic"})
    body = client.post(f"/api/gds/{gid}/reset_layers").json()
    entry = next(c for c in body["spec"]["components"] if c["id"] == gid)
    assert entry.get("layer_stack", {}) == {}


def test_gds_attach_technology_rejects_empty(client: TestClient):
    import pathlib

    gds = pathlib.Path("examples/assets/demo_mask.gds")
    if not gds.exists():
        pytest.skip("sample GDS not present")
    gid = client.post(
        "/api/gds/import", params={"filename": "demo_mask.gds"}, content=gds.read_bytes()
    ).json()["id"]
    assert client.post(f"/api/gds/{gid}/technology", content=b"").status_code == 400


def test_export_glb_is_valid_binary_gltf(client: TestClient):
    import pathlib

    gds = pathlib.Path("examples/assets/demo_mask.gds")
    if not gds.exists():
        pytest.skip("sample GDS not present")
    client.post("/api/gds/import", params={"filename": "demo_mask.gds"}, content=gds.read_bytes())
    res = client.get("/api/export/glb")
    assert res.status_code == 200
    body = res.content
    assert body[:4] == b"glTF"  # binary glTF magic (Blender-importable)
    assert struct.unpack_from("<I", body, 4)[0] == 2  # glTF version 2


def test_export_glb_empty_scene_400(client: TestClient):
    assert client.get("/api/export/glb").status_code == 400


def test_pdks_lists_generic(client: TestClient):
    """Every PDK on offer comes from gdsfactory, including the generic one — so
    the list is empty without it, and that is the honest answer, not a bug."""

    ids = {p["id"] for p in client.get("/api/pdks").json()["pdks"]}
    try:
        import gdsfactory  # noqa: F401
    except ImportError:
        assert ids == set()
        return
    assert "generic" in ids  # others appear when their package is installed


def test_apply_pdk_to_gds(client: TestClient):
    import pathlib

    pytest.importorskip("gdsfactory")
    gds = pathlib.Path("examples/assets/demo_mask.gds")
    if not gds.exists():
        pytest.skip("sample GDS not present")
    gid = client.post(
        "/api/gds/import", params={"filename": "demo_mask.gds"}, content=gds.read_bytes()
    ).json()["id"]
    res = client.post(f"/api/gds/{gid}/pdk", json={"name": "generic"})
    assert res.status_code == 200
    assert res.json()["applied"] > 0


def test_stacks_lists_open_stacks_only(client: TestClient):
    body = client.get("/api/stacks").json()
    ids = {s["id"] for s in body["stacks"]}
    assert "gdsfactory_generic" in ids  # bundled open stack
    assert "_template" not in ids  # template is download-only, not applyable


def test_stack_template_downloads(client: TestClient):
    res = client.get("/api/stacks/template")
    assert res.status_code == 200
    assert "layers:" in res.text


def test_apply_stack_to_gds(client: TestClient):
    import pathlib

    gds = pathlib.Path("examples/assets/demo_mask.gds")
    if not gds.exists():
        pytest.skip("sample GDS not present")
    gid = client.post(
        "/api/gds/import", params={"filename": "demo_mask.gds"}, content=gds.read_bytes()
    ).json()["id"]
    res = client.post(f"/api/gds/{gid}/stack", json={"name": "gdsfactory_generic"})
    assert res.status_code == 200
    assert res.json()["applied"] > 0


def test_apply_unknown_stack_404(client: TestClient):
    import pathlib

    gds = pathlib.Path("examples/assets/demo_mask.gds")
    if not gds.exists():
        pytest.skip("sample GDS not present")
    gid = client.post(
        "/api/gds/import", params={"filename": "demo_mask.gds"}, content=gds.read_bytes()
    ).json()["id"]
    assert client.post(f"/api/gds/{gid}/stack", json={"name": "nope"}).status_code == 404


def test_apply_unknown_pdk_400(client: TestClient):
    import pathlib

    gds = pathlib.Path("examples/assets/demo_mask.gds")
    if not gds.exists():
        pytest.skip("sample GDS not present")
    gid = client.post(
        "/api/gds/import", params={"filename": "demo_mask.gds"}, content=gds.read_bytes()
    ).json()["id"]
    assert client.post(f"/api/gds/{gid}/pdk", json={"name": "definitely_not_a_pdk"}).status_code == 400


def test_gds_layers_unknown_404(client: TestClient):
    assert client.get("/api/gds/nope/layers").status_code == 404


def test_export_blender_script(client: TestClient):
    txt = client.get("/api/export/blender", params={"glb": "scene.glb"}).text
    assert "import bpy" in txt
    assert "'scene.glb'" in txt  # references the GLB by bare name
    assert "/optodraw_scene" not in txt  # absolute server path was rewritten out


def test_trace_reflects_off_mirror(client: TestClient):
    laser = client.post("/api/component", json={"name": "Laser", "params": {"center": [-80, 0]}}).json()["id"]
    client.post("/api/component", json={"name": "Mirror", "params": {"center": [40, 0], "angle": 45, "aperture": 16}})
    resp = client.post("/api/trace", json={"source_id": laser})
    assert resp.status_code == 200
    chiefs = _chief_beams(resp.json()["spec"])
    assert len(chiefs) == 1
    path = chiefs[0]["path"]
    # chief ray goes +x to the mirror at x=40, then physically reflects downward
    assert path[-2][0] == 40
    assert path[-1][1] < -5
    # re-tracing the same source replaces (not duplicates) its bundle
    count = len(client.get("/api/scene").json()["beams"])
    client.post("/api/trace", json={"source_id": laser})
    assert len(client.get("/api/scene").json()["beams"]) == count


def test_trace_bad_source_400(client: TestClient):
    assert client.post("/api/trace", json={"source_id": "nope"}).status_code == 400


def test_trace_splits_at_beamsplitter(client: TestClient):
    laser = client.post("/api/component", json={"name": "Laser", "params": {"center": [-70, 0]}}).json()["id"]
    client.post("/api/component", json={"name": "BeamSplitter", "params": {"center": [15, 0], "angle": 45, "dichroic": True}})
    beams = _chief_beams(client.post("/api/trace", json={"source_id": laser}).json()["spec"])
    # a beam splitter yields BOTH a transmitted and a reflected chief ray
    assert len(beams) == 2
    ends = sorted(tuple(b["path"][-1]) for b in beams)
    # one continues straight (+x, y≈0), one reflects off-axis (y != 0)
    assert any(abs(e[1]) < 1 for e in ends) and any(abs(e[1]) > 1 for e in ends)


def test_auth_dependency_gates_api():
    # The hosted-deployment seam: an injected auth dependency guards every /api route.
    from fastapi import HTTPException

    def deny():
        raise HTTPException(status_code=401, detail="unauthorized")

    guarded = TestClient(create_app(auth_dependency=deny))
    assert guarded.get("/api/health").status_code == 401
    # static front-end is still served (only /api is gated)
    assert guarded.get("/").status_code == 200


def test_simulate_options_and_run_for_ring(client: TestClient):
    rid = client.post("/api/component", json={"name": "MicroringResonator", "params": {"center": [0, 0]}}).json()["id"]
    opts = client.get(f"/api/simulate/{rid}/options").json()
    assert "resonance" in opts["kinds"]
    res = client.post(f"/api/simulate/{rid}", json={"kind": "resonance", "params": {"bias_voltage_v": 1.0}}).json()
    assert res["plot_svg"].lstrip().startswith(("<?xml", "<svg"))
    assert "Q" in res["data"]
    assert any(c["name"] == "bias_voltage_v" for c in res["controls"])


def test_simulate_plots_do_not_crowd_their_tick_labels():
    """A 4.7 in panel cannot carry nine six-digit wavelength ticks — they ran
    together into 1549.0(1549.2(1549.5(... in the Simulate panel."""

    from optodraw.app.sim_plots import _new_fig

    fig, ax = _new_fig()
    ax.plot([1549.0, 1549.5, 1550.0, 1550.5, 1551.0], [0.0, 0.4, 1.0, 0.4, 0.0])
    fig.canvas.draw()

    def visible(ticks, lo, hi):  # matplotlib also returns off-view edge ticks
        return [t for t in ticks if lo <= t <= hi]

    assert len(visible(ax.get_xticks(), *ax.get_xlim())) <= 6
    assert len(visible(ax.get_yticks(), *ax.get_ylim())) <= 6


def test_simulate_mzm_transfer(client: TestClient):
    mid = client.post("/api/component", json={"name": "MZM", "params": {"center": [0, 0]}}).json()["id"]
    res = client.post(f"/api/simulate/{mid}", json={"kind": "mzm_transfer", "params": {"Vpi": 3.0}}).json()
    assert res["kind"] == "mzm_transfer"
    assert res["plot_svg"].lstrip().startswith(("<?xml", "<svg"))


def test_simulate_unknown_component_404(client: TestClient):
    assert client.get("/api/simulate/nope/options").status_code == 404


def test_simulate_polarization_over_chain(client: TestClient):
    # /simulate/polarization must NOT be shadowed by /simulate/{id}.
    client.post("/api/scene/preset", json={"name": "qwp_circular_lab"})
    res = client.post("/api/simulate/polarization", json={"params": {"input": "H"}}).json()
    assert res["kind"] == "polarization"
    assert res["plot_svg"].lstrip().startswith(("<?xml", "<svg"))
    assert res["data"]["stages"] >= 3


def test_generators_list_and_generate(client: TestClient):
    gens = client.get("/api/generators").json()["generators"]
    names = {g["name"] for g in gens}
    assert {"mzm_mesh", "ring_filter", "detector_readout_chain"}.issubset(names)
    res = client.post("/api/generate", json={"name": "mzm_mesh", "params": {"modes": 3, "layers": 2}}).json()
    types = {c["type"] for c in res["spec"]["components"]}
    # a real interferometric mesh interleaves MZMs with directional couplers
    assert "MZM" in types and "DirectionalCoupler" in types
    assert "data-component-id" in res["svg"]


def test_generate_unknown_404(client: TestClient):
    assert client.post("/api/generate", json={"name": "nope", "params": {}}).status_code == 404


def test_animation_recipes_and_gif(client: TestClient):
    rid = client.post("/api/component", json={"name": "MicroringResonator", "params": {"center": [0, 0]}}).json()["id"]
    recipes = client.get(f"/api/animation/{rid}/recipes").json()["recipes"]
    assert any(r["name"] == "resonance_scan" for r in recipes)
    res = client.post(f"/api/animation/{rid}/gif", json={"recipe": "resonance_scan", "params": {"steps": 3, "fps": 6}})
    assert res.status_code == 200
    assert res.headers["content-type"] == "image/gif"
    assert res.content[:6] == b"GIF89a"


def test_animation_bad_recipe_400(client: TestClient):
    rid = client.post("/api/component", json={"name": "MicroringResonator", "params": {"center": [0, 0]}}).json()["id"]
    assert client.post(f"/api/animation/{rid}/gif", json={"recipe": "nope"}).status_code == 400


def test_animation_flow_gif_shows_motion(client: TestClient):
    client.post("/api/scene/preset", json={"name": "ring_resonator_chip"})
    res = client.post("/api/animation/flow", json={"params": {"steps": 6, "fps": 8}})
    assert res.status_code == 200
    assert res.headers["content-type"] == "image/gif"
    assert res.content[:6] == b"GIF89a"


def test_animation_flow_empty_scene_400(client: TestClient):
    client.post("/api/scene/new", json={"title": "Empty"})
    assert client.post("/api/animation/flow", json={"params": {}}).status_code == 400


def test_validate_returns_structured_checks(client: TestClient):
    client.post("/api/scene/preset", json={"name": "qwp_circular_lab"})
    checks = client.post("/api/validate").json()["checks"]
    assert isinstance(checks, list)
    # the free-space polarization lab flags the laser's missing polarization support
    assert any(c["kind"] == "polarization" for c in checks)


def test_validate_flags_a_component_that_falls_off_the_page(client: TestClient):
    """The export frame is what a figure gets cropped to, and a part outside it
    is simply missing from the PNG, the SVG and the TikZ — silently."""

    client.post("/api/scene/new", json={"width": 200, "height": 120})
    client.post("/api/component", json={"name": "Laser", "params": {"center": [0, 0]}})
    client.post("/api/component", json={"name": "Lens", "params": {"center": [140, 0], "label": "Far lens"}})

    flagged = [c for c in client.post("/api/validate").json()["checks"] if c["kind"] == "frame"]
    assert flagged and "Far lens" in flagged[0]["message"]

    # bring it back inside and the check goes quiet
    lens = next(c["id"] for c in client.get("/api/scene").json()["components"] if c["type"] == "Lens")
    client.post(f"/api/component/{lens}/move", json={"center": [60, 0]})
    assert not [c for c in client.post("/api/validate").json()["checks"] if c["kind"] == "frame"]


def test_validate_flags_a_dichroic_with_no_cutoff(client: TestClient):
    """``dichroic=True`` alone does nothing to a ray: without an edge wavelength
    the tracer has no rule to apply and splits the beam 50/50, which looks like a
    working dichroic in the drawing and is not one."""

    client.post("/api/component", json={
        "name": "BeamSplitter",
        "params": {"center": [0, 0], "angle": 45, "dichroic": True, "label": "Dichroic"},
    })
    checks = client.post("/api/validate").json()["checks"]
    flagged = [c for c in checks if c["kind"] == "dichroic"]
    assert flagged and "Dichroic" in flagged[0]["message"]

    # give it an edge and the check goes quiet
    splitter = next(c["id"] for c in client.get("/api/scene").json()["components"] if c["type"] == "BeamSplitter")
    client.patch(f"/api/component/{splitter}", json={"params": {"cutoff_wavelength": 550}})
    assert not [c for c in client.post("/api/validate").json()["checks"] if c["kind"] == "dichroic"]


def test_validate_flags_a_detector_that_receives_no_light(client: TestClient):
    """The most useful free-space check there is: the rays are traced, so the
    checker can say whether the light actually lands on the detector."""

    laser = client.post("/api/component", json={"name": "Laser", "params": {"center": [-60, 0]}}).json()["id"]
    # a mirror square-on sends the beam straight back — the detector stays dark
    client.post("/api/component", json={"name": "Mirror", "params": {"center": [-20, 0], "angle": 0}})
    client.post("/api/component", json={"name": "Photodiode", "params": {"center": [20, 0], "angle": 180}})
    client.post("/api/trace", json={"source_id": laser})

    dark = client.post("/api/validate").json()["checks"]
    hit = [c for c in dark if c["kind"] == "illumination"]
    assert hit and "Photodiode" in hit[0]["message"]

    # turn the mirror out of the way and the same check goes quiet
    mirror = next(c["id"] for c in client.get("/api/scene").json()["components"] if c["type"] == "Mirror")
    client.post(f"/api/component/{mirror}/move", json={"center": [-20, 60]})
    lit = client.post("/api/validate").json()["checks"]
    assert not [c for c in lit if c["kind"] == "illumination"]


def test_validate_is_quiet_without_a_trace(client: TestClient):
    # no rays traced yet = nothing known about illumination; don't cry wolf
    client.post("/api/component", json={"name": "Photodiode", "params": {"center": [20, 0]}})
    checks = client.post("/api/validate").json()["checks"]
    assert not [c for c in checks if c["kind"] == "illumination"]


def test_validate_on_chip_grating_coupler(client: TestClient):
    client.post("/api/scene/preset", json={"name": "ring_resonator_chip"})
    # the stock coupler pitch phase-matches at 1550 — a healthy preset must NOT
    # be flagged (the old free-space grating equation called every pitch evanescent)
    checks = client.post("/api/validate").json()["checks"]
    assert not any(c["kind"] == "coupler" for c in checks)

    # a genuinely inconsistent declared coupling angle IS flagged, with its id
    spec = client.get("/api/scene").json()
    gc_id = next(c["id"] for c in spec["components"] if c["type"] == "VerticalGratingCoupler")
    client.patch(f"/api/component/{gc_id}", json={"params": {"coupling_angle_deg": 90.0}})
    checks = client.post("/api/validate").json()["checks"]
    flagged = [c for c in checks if c["kind"] == "coupler"]
    assert flagged and flagged[0]["component_id"] == gc_id


def test_free_route_from_points(client: TestClient):
    # port-less components are wired with free polyline routes
    res = client.post("/api/route", json={"points": [[0, 0], [40, 0], [40, 30]], "kind": "electrical"})
    assert res.status_code == 200
    rid = res.json()["id"]
    spec = client.get("/api/scene").json()
    entry = next(e for e in spec["routes"] if e["id"] == rid)
    assert entry["points"] == [[0, 0], [40, 0], [40, 30]]
    assert "from" not in entry
    # neither ports nor points is a 400, not a crash
    assert client.post("/api/route", json={"kind": "waveguide"}).status_code == 400


def test_publication_templates_and_figure_zip(client: TestClient):
    client.post("/api/scene/preset", json={"name": "ring_resonator_chip"})
    info = client.get("/api/publication/templates").json()
    assert "single_figure" in info["templates"]
    assert info["presets"]
    res = client.post("/api/export/figure", json={"template": "single_figure", "formats": ["svg", "json"], "caption": "Fig 1"})
    assert res.status_code == 200
    assert res.headers["content-type"] == "application/zip"
    assert res.content[:2] == b"PK"



class TestRouteWidthsAndTapers:
    """Port widths are DRAWN widths (routes visually mate with the drawing) and
    mismatched ports taper automatically: width at the start, width2 at the end."""

    def test_onchip_ports_declare_drawn_widths(self):
        from optodraw.registry import component_registry

        registry = component_registry()
        for name in ("MicroringResonator", "PNMicroringModulator", "OnChipPhotodetector",
                     "VerticalGratingCoupler", "BalancedPhotodetector"):
            component = registry[name].cls()
            for port in component.ports().values():
                if port.kind in ("electrical", "thermal", "fiber"):
                    continue
                # no physical 0.5 µm leaking into the schematic port width
                assert port.width >= 1.0, f"{name} port {port.name} = {port.width}"

    def test_ring_port_width_matches_its_drawn_bus(self):
        from optodraw.registry import component_registry

        ring = component_registry()["MicroringResonator"].cls()
        assert ring.ports()["o1"].width == pytest.approx(ring._geom_waveguide_width())

    def test_mismatched_ports_taper_automatically(self):
        from optodraw import Scene
        from optodraw.registry import component_registry

        registry = component_registry()
        scene = Scene()
        gc = scene.add(registry["VerticalGratingCoupler"].cls(center=(-60, 0)))
        mmi = scene.add(registry["MMI1x2"].cls(center=(40, 0)))          # an MMI's access waveguide is 1.7 wide
        route = scene.route((gc, "o1"), (mmi, "o1"), kind="waveguide")
        assert route.width == pytest.approx(1.2)
        assert route.width2 == pytest.approx(1.7)

    def test_matched_ports_stay_uniform(self):
        from optodraw import Scene
        from optodraw.registry import component_registry

        registry = component_registry()
        scene = Scene()
        a = scene.add(registry["MicroringResonator"].cls(center=(-30, 0)))
        b = scene.add(registry["RacetrackResonator"].cls(center=(40, 0)))
        route = scene.route((a, "o2"), (b, "o1"), kind="waveguide")
        assert route.width == pytest.approx(1.2)                         # rings draw the common 1.2 width
        assert route.width2 is None

    def test_route_width_editable_and_nullable(self, client: TestClient):
        gc = client.post("/api/component", json={"name": "VerticalGratingCoupler", "params": {"center": [-40, 0]}}).json()["id"]
        pd = client.post("/api/component", json={"name": "OnChipPhotodetector", "params": {"center": [40, 0]}}).json()["id"]
        rid = client.post("/api/route", json={"src": [gc, "o1"], "dst": [pd, "o1"], "kind": "waveguide"}).json()["id"]
        # explicit width + taper via the inspector's generic update path
        res = client.patch(f"/api/component/{rid}", json={"params": {"width": 3.0, "width2": 1.0}})
        assert res.status_code == 200
        entry = next(r for r in res.json()["spec"]["routes"] if r["id"] == rid)
        assert entry["width"] == 3.0 and entry["width2"] == 1.0
        # back to auto: null clears the override and the scene still builds
        res = client.patch(f"/api/component/{rid}", json={"params": {"width": None, "width2": None}})
        assert res.status_code == 200
        assert "<svg" in res.json()["svg"]

    def test_tapered_route_renders_filled_outline(self, client: TestClient):
        gc = client.post("/api/component", json={"name": "VerticalGratingCoupler", "params": {"center": [-60, 0]}}).json()["id"]
        bank = client.post("/api/component", json={"name": "MicroringWeightBank", "params": {"center": [40, 0]}}).json()["id"]
        client.post("/api/route", json={"src": [gc, "o1"], "dst": [bank, "o1"], "kind": "waveguide"})
        svg = client.get("/api/render/svg").json()["svg"]
        assert "<svg" in svg  # taper polygon path renders without error


class TestOnChipBaseDetection:
    def test_chip_system_in_scratch_scene_gets_the_die_base(self, client: TestClient):
        """A pure on-chip system built in a default (free_space) workspace must
        still get the auto-generated die + carrier base in 3D."""

        client.post("/api/component", json={"name": "VerticalGratingCoupler", "params": {"center": [-60, 0]}})
        client.post("/api/component", json={"name": "MicroringResonator", "params": {"center": [0, 0]}})
        client.post("/api/component", json={"name": "OnChipPhotodetector", "params": {"center": [60, 0]}})
        html = client.get("/api/render/threejs").text
        assert "const IS_ONCHIP = true" in html
        assert "const liftMeshesToTable = false" in html  # chip parts sit flat, no posts

    def test_mixed_scene_stays_free_space(self, client: TestClient):
        client.post("/api/component", json={"name": "MicroringResonator", "params": {"center": [0, 0]}})
        client.post("/api/component", json={"name": "Laser", "params": {"center": [-60, 0]}})
        html = client.get("/api/render/threejs").text
        assert "const IS_ONCHIP = false" in html

    def test_platform_meta_forces_chip_mode(self, client: TestClient):
        client.post("/api/component", json={"name": "MicroringResonator", "params": {"center": [0, 0]}})
        client.post("/api/component", json={"name": "Laser", "params": {"center": [-60, 0]}})
        client.patch("/api/scene/meta", json={"platform": "on_chip"})
        html = client.get("/api/render/threejs").text
        assert "const IS_ONCHIP = true" in html

    def test_placed_chip_substrate_replaces_the_auto_die(self, client: TestClient):
        client.post("/api/component", json={"name": "MicroringResonator", "params": {"center": [0, 0]}})
        client.post("/api/component", json={"name": "ChipSubstrate", "params": {"center": [0, 0], "length": 120, "width": 60}})
        html = client.get("/api/render/threejs").text
        assert "const IS_ONCHIP = true" in html
        assert "const HAS_USER_DIE = true" in html  # auto die yields; carrier remains

    def test_chip_base_meta_turns_the_auto_base_off(self, client: TestClient):
        client.post("/api/component", json={"name": "MicroringResonator", "params": {"center": [0, 0]}})
        client.patch("/api/scene/meta", json={"chip_base": False})
        html = client.get("/api/render/threejs").text
        assert "const SHOW_CHIP_BASE = false" in html
        # and back on
        client.patch("/api/scene/meta", json={"chip_base": True})
        assert "const SHOW_CHIP_BASE = true" in client.get("/api/render/threejs").text


class TestArrangeLayout:
    """Grid / line placement — the layout helpers, reachable from the editor."""

    def _seed(self, client: TestClient, count: int = 4) -> list[str]:
        return [
            client.post("/api/component", json={"name": "Lens", "params": {"center": [i * 3.0, i * 7.0]}}).json()["id"]
            for i in range(count)
        ]

    def test_arrange_grid_lays_components_out_in_rows(self, client: TestClient):
        self._seed(client)
        response = client.post("/api/scene/arrange", json={"strategy": "grid", "columns": 2, "spacing": 30})
        assert response.status_code == 200
        centers = [c["center"] for c in response.json()["spec"]["components"]]
        xs = sorted({round(c[0], 3) for c in centers})
        ys = sorted({round(c[1], 3) for c in centers})
        assert len(xs) == 2 and len(ys) == 2  # 4 components -> a 2x2 grid
        assert round(xs[1] - xs[0], 3) == 30.0
        assert round(ys[1] - ys[0], 3) == 30.0

    def test_arrange_line_only_touches_the_given_ids(self, client: TestClient):
        ids = self._seed(client)
        before = {c["id"]: list(c["center"]) for c in client.get("/api/scene").json()["components"]}
        response = client.post("/api/scene/arrange", json={"ids": ids[:2], "strategy": "line", "spacing": 12})
        after = {c["id"]: c["center"] for c in response.json()["spec"]["components"]}
        assert after[ids[2]] == before[ids[2]]  # untouched
        assert after[ids[3]] == before[ids[3]]
        assert after[ids[0]][1] == after[ids[1]][1]  # the two named ones share a row

    def test_arrange_needs_two_components(self, client: TestClient):
        self._seed(client, count=1)
        assert client.post("/api/scene/arrange", json={"strategy": "grid"}).status_code == 400


def test_scene_download_returns_a_loadable_spec(client: TestClient):
    """The Save button's route. If this breaks, a user loses their work with no
    way to get it back, so it is worth a test of its own."""

    client.post("/api/scene/preset", json={"name": "confocal_pl"})
    payload = client.get("/api/scene/download").json()
    assert payload["schema_version"] >= 2
    assert payload["optodraw_version"]
    assert len(payload["components"]) > 4

    # what came out goes back in
    client.post("/api/scene/new", json={})
    assert client.post("/api/scene", json={"spec": payload}).status_code == 200
    assert len(client.get("/api/scene").json()["components"]) == len(payload["components"])


def test_scene3d_lists_the_items_the_3d_view_draws(client: TestClient):
    client.post("/api/scene/preset", json={"name": "confocal_pl"})
    items = client.get("/api/scene3d").json()["items"]
    labels = {item.get("label") for item in items}
    assert "Sample in closed-cycle cryostat" in labels and "Objective NA 0.81" in labels
    assert all("position" in item for item in items)


def test_preset_preview_renders_and_404s_on_a_bad_name(client: TestClient):
    assert client.get("/api/presets/confocal_pl/preview").json()["svg"].startswith("<?xml")
    assert client.get("/api/presets/nope/preview").status_code == 404


def _ftir(client: TestClient) -> None:
    client.post("/api/scene/preset", json={"name": "ftir"})


def test_scene3d_has_no_light_unless_asked(client: TestClient):
    _ftir(client)
    body = client.get("/api/scene3d").json()
    assert body["light"] is None and body["items"]


def test_scene3d_light_carries_the_engines_pulse(client: TestClient):
    _ftir(client)
    body = client.get("/api/scene3d", params={"light": 1}).json()
    assert body["items"] and body["light"]["enabled"]
    assert body["light"]["pulse"]["edges"]


def test_scene3d_light_follows_a_move(client: TestClient):
    _ftir(client)
    before = client.get("/api/scene3d", params={"light": 1}).json()["light"]["pulse"]["edges"]
    client.post("/api/component/L/move", json={"center": [0, -16]})
    after = client.get("/api/scene3d", params={"light": 1}).json()["light"]["pulse"]["edges"]
    edge = "path:lens1:in->out"
    assert before[edge]["points"] != after[edge]["points"]


def test_animation_metadata_round_trips_through_save_and_load(client: TestClient):
    _ftir(client)
    spec = client.get("/api/scene/download").json()
    spec.setdefault("metadata", {})["animation"] = {"look": "field", "params": {}, "inputs": [], "tour": None}
    assert client.post("/api/scene", json={"spec": spec}).status_code == 200
    again = client.get("/api/scene/download").json()
    assert again["metadata"]["animation"]["look"] == "field"
    assert client.get("/api/scene3d", params={"light": 1}).json()["light"]["look"] == "field"


def test_the_editable_page_embeds_no_light_and_the_standalone_page_does(client: TestClient):
    _ftir(client)
    editable = client.get("/api/render/threejs", params={"editable": 1}).text
    standalone = client.get("/api/render/threejs").text
    assert '"edges": {"' not in editable and "path:lens1:in-" not in editable
    assert "path:lens1:in-" in standalone


def test_an_unchanged_scene_does_not_rebuild_the_light(client: TestClient, monkeypatch):
    from optodraw.app import api

    calls = []
    real = api.build_light_payload

    def counting(*args, **kwargs):
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(api, "build_light_payload", counting)
    api._LIGHT_CACHE.clear()
    _ftir(client)
    first = client.get("/api/scene3d", params={"light": 1}).json()
    second = client.get("/api/scene3d", params={"light": 1}).json()
    assert first["light"] == second["light"] and len(calls) == 1
    client.post("/api/component/L/move", json={"center": [0, -16]})
    client.get("/api/scene3d", params={"light": 1})
    assert len(calls) == 2


# -- Light settings per part (the inspector's "Light" section) --------------------------------------------------- #


def _load_ring_filter(client: TestClient) -> str:
    """The Mak 2015 filter: five rings, each with a heater; returns the editor id of the filter."""

    client.post("/api/scene/preset", json={"name": "ring_resonator_chip"})
    return "5th-order filter"


def _single_ring_spec() -> dict:
    from optodraw import Scene
    from optodraw.components.onchip.rings import MicroringResonator
    from optodraw.registry import build_component

    scene = Scene(width=360, height=200, platform="on_chip")
    laser = scene.add(build_component("OnChipLaser", center=(-150, 0)))
    ring = scene.add(MicroringResonator(center=(0, 0), add_drop=True, with_heater=True))
    det = scene.add(build_component("OnChipPhotodetector", center=(150, 0)))
    scene.route((laser, "o1"), (ring, "o1"), kind="waveguide")
    scene.route((ring, "o2"), (det, "o1"), kind="waveguide")
    return scene.to_spec()


def test_scene3d_tour_carries_the_drive_tables_of_the_tours_driven_stops(client: TestClient):
    assert client.post("/api/scene", json={"spec": _single_ring_spec()}).status_code == 200
    plain = client.get("/api/scene3d", params={"light": 1}).json()["light"]
    driven = [s["drive"] for s in plain["tour"]["stops"] if s["drive"]]
    assert driven and plain["drives"] == []                                # turning the light on stays quick
    toured = client.get("/api/scene3d", params={"light": 1, "tour": 1}).json()["light"]
    assert [d["param"] for d in toured["drives"]] == driven and toured["tour"] == plain["tour"]
    assert client.get("/api/scene3d", params={"tour": 1}).json()["light"]["drives"] == toured["drives"]


def _ring_id(client: TestClient) -> str:
    spec = client.get("/api/scene/download").json()
    return next(c["id"] for c in spec["components"] if c["type"] == "MicroringResonator")


def test_a_ring_gets_tuning_and_heater_controls_and_a_part_without_a_heater_gets_none(client: TestClient):
    cid = _load_ring_filter(client)
    controls = client.get(f"/api/component/{cid}/light").json()["controls"]
    kinds = [c["kind"] for c in controls]
    assert kinds.count("tuning") == 5 and kinds.count("heater") == 5 and "drive" not in kinds
    tuning = next(c for c in controls if c["kind"] == "tuning")
    heater = next(c for c in controls if c["kind"] == "heater")
    assert (tuning["min"], tuning["max"], tuning["value"]) == (-2.0, 2.0, 0.0)
    assert (heater["min"], heater["max"], heater["value"], heater["unit"]) == (0.0, 40.0, 0.0, "mW")
    assert heater["param"] == "heater:coupledringfilter1:ring1" and tuning["param"] == "phase:coupledringfilter1:ring1"
    # the grating coupler has no ring, no heater and no modulator: no controls, and no heater slider
    assert client.get("/api/component/In/light").json()["controls"] == []


def test_a_modulator_gets_a_drive_control_up_to_its_v_pi(client: TestClient):
    from optodraw.animation_engine.behaviours.interferometers import mzm_v_pi

    client.post("/api/scene/preset", json={"name": "mzm_mesh_chip"})
    spec = client.get("/api/scene/download").json()
    mzm = next(c for c in spec["components"] if c["type"] == "MZM")
    controls = client.get(f"/api/component/{mzm['id']}/light").json()["controls"]
    (drive,) = [c for c in controls if c["kind"] == "drive"]
    assert drive["unit"] == "V" and drive["min"] == 0.0 and drive["max"] > 0
    assert drive["param"].startswith("drive:mzm")
    assert not [c for c in controls if c["kind"] == "heater"] or all(c["max"] == 40.0 for c in controls if c["kind"] == "heater")
    assert drive["max"] == pytest.approx(mzm_v_pi(_part(client, mzm["id"])))


def _part(client: TestClient, component_id: str):
    from optodraw.app import api

    return next(n for n in api._session().scene().walk() if getattr(n, "_id", "") == component_id)


def test_light_settings_land_in_metadata_animation_params_and_drive_the_3d_payload(client: TestClient):
    cid = _load_ring_filter(client)
    before = client.get("/api/scene3d", params={"light": 1}).json()["light"]
    res = client.patch(f"/api/component/{cid}", json={"params": {"light": {"heater:coupledringfilter1:ring2": 12.5}}})
    assert res.status_code == 200
    params = client.get("/api/scene/download").json()["metadata"]["animation"]["params"]
    assert params == {"heater:coupledringfilter1:ring2": 12.5}
    after = client.get("/api/scene3d", params={"light": 1}).json()["light"]
    assert after["cw"] != before["cw"]                                    # the payload shows the new state
    again = client.get(f"/api/component/{cid}/light").json()["controls"]
    assert next(c for c in again if c["key"] == "heater:coupledringfilter1:ring2")["value"] == 12.5


def test_a_light_value_back_at_its_default_removes_the_key(client: TestClient):
    cid = _load_ring_filter(client)
    key = "heater:coupledringfilter1:ring1"
    client.patch(f"/api/component/{cid}", json={"params": {"light": {key: 5.0, "tuning:coupledringfilter1:ring3": 0.5}}})
    params = client.get("/api/scene/download").json()["metadata"]["animation"]["params"]
    assert params[key] == 5.0 and "phase:coupledringfilter1:ring3" in params
    client.patch(f"/api/component/{cid}", json={"params": {"light": {key: 0.0, "tuning:coupledringfilter1:ring3": 0.0}}})
    assert client.get("/api/scene/download").json()["metadata"]["animation"].get("params", {}) == {}


def test_light_settings_round_trip_through_save_and_load(client: TestClient):
    cid = _load_ring_filter(client)
    client.patch(f"/api/component/{cid}", json={"params": {"light": {"heater:coupledringfilter1:ring2": 7.0,
                                                                     "tuning:coupledringfilter1:ring4": -1.5}}})
    spec = client.get("/api/scene/download").json()
    saved = dict(spec["metadata"]["animation"]["params"])
    client.post("/api/scene/new", json={})
    assert client.post("/api/scene", json={"spec": spec}).status_code == 200
    assert client.get("/api/scene/download").json()["metadata"]["animation"]["params"] == saved
    controls = client.get(f"/api/component/{cid}/light").json()["controls"]
    assert next(c for c in controls if c["key"] == "tuning:coupledringfilter1:ring4")["value"] == pytest.approx(-1.5)


def test_light_values_outside_the_range_or_without_a_control_are_refused(client: TestClient):
    cid = _load_ring_filter(client)
    for bad in ({"heater:coupledringfilter1:ring1": 41.0}, {"heater:coupledringfilter1:ring1": -1.0},
                {"tuning:coupledringfilter1:ring1": 2.5}, {"drive:coupledringfilter1": 1.0},
                {"heater:coupledringfilter1:ring1": "hot"}):
        assert client.patch(f"/api/component/{cid}", json={"params": {"light": bad}}).status_code == 400, bad
    assert client.patch("/api/component/In", json={"params": {"light": {"heater:verticalgratingcoupler1": 1.0}}}).status_code == 400
    assert "animation" not in client.get("/api/scene/download").json().get("metadata", {})


def _drop_power(client: TestClient) -> float:
    light = client.get("/api/scene3d", params={"light": 1}).json()["light"]
    return sum(e["power"] for e in light["cw"]["exits"] if e["part"] == "microringresonator1" and e["port"] == "o3")


@pytest.mark.filterwarnings("ignore:.*unconnected port:RuntimeWarning")
def test_a_ring_tuned_one_linewidth_drops_what_the_engines_lorentzian_gives(client: TestClient):
    from optodraw.animation_engine.graph import build_graph
    from optodraw.animation_engine.solver import resonance_phases, ring_linewidths
    from optodraw.animation3d.inputs import default_inputs, input_wavelength
    from optodraw.app import api

    assert client.post("/api/scene", json={"spec": _single_ring_spec()}).status_code == 200
    cid = _ring_id(client)
    on = _drop_power(client)
    assert on > 0
    # tuning 0 is the engine's own default: the key stays out of the params
    client.patch(f"/api/component/{cid}", json={"params": {"light": {"tuning:microringresonator1": 0.0}}})
    assert _drop_power(client) == pytest.approx(on)
    client.patch(f"/api/component/{cid}", json={"params": {"light": {"tuning:microringresonator1": 1.0}}})
    scene = api._session().scene()
    part = build_graph(scene).parts["microringresonator1"]
    inputs, _ = default_inputs(scene)
    wl = input_wavelength(build_graph(scene), inputs, {})
    stored = client.get("/api/scene/download").json()["metadata"]["animation"]["params"]["phase:microringresonator1"]
    (res,) = resonance_phases(part, "microringresonator1", wl).values()
    (width,) = ring_linewidths(part, "microringresonator1", wl).values()
    assert stored == pytest.approx(res + width)
    # one linewidth (FWHM) away the Lorentzian is 1 / (1 + (2 d / FWHM)^2) = 1/5 of the peak
    assert _drop_power(client) / on == pytest.approx(0.2, rel=0.03)


def test_a_light_edit_autosaves_and_its_reply_carries_the_value_the_undo_history_keeps(client: TestClient, monkeypatch):
    """Undo is the page's history of the replies' specs: the reply to a light edit must hold the new params, and the
    edit goes through the one autosave hook like every other edit."""

    from optodraw.app.session import EditorSession

    cid = _load_ring_filter(client)
    saves = []
    real = EditorSession.autosave
    monkeypatch.setattr(EditorSession, "autosave", lambda self: (saves.append(1), real(self))[1])
    key = "heater:coupledringfilter1:ring1"
    reply = client.patch(f"/api/component/{cid}", json={"params": {"light": {key: 9.0}}}).json()
    assert saves and reply["spec"]["metadata"]["animation"]["params"] == {key: 9.0}
    back = client.post("/api/scene", json={"spec": {**reply["spec"], "metadata": {k: v for k, v in reply["spec"]["metadata"].items() if k != "animation"}}})
    assert back.status_code == 200 and "animation" not in client.get("/api/scene/download").json()["metadata"]


# -- record video: one render job at a time, run in a worker thread ----------------------------------------------- #

def _chip_spec() -> dict:
    from optodraw import Scene
    from optodraw.registry import build_component

    scene = Scene(width=600, height=160, platform="on_chip")
    laser = scene.add(build_component("OnChipLaser", center=(-200, 0)))
    mzm = scene.add(build_component("MZM", center=(0, 0)))
    det = scene.add(build_component("OnChipPhotodetector", center=(200, 0)))
    scene.route((laser, "o1"), (mzm, "o1"), kind="waveguide")
    scene.route((mzm, "o3"), (det, "o1"), kind="waveguide")
    return scene.to_spec()


def _wait_job(client: TestClient, job_id: str, timeout: float = 240.0) -> dict:
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = client.get(f"/api/render/video/{job_id}").json()
        if job["state"] != "running":
            return job
        time.sleep(0.5)
    raise AssertionError("the video job did not finish")


@pytest.fixture()
def video_jobs(monkeypatch):
    from optodraw.app import api

    monkeypatch.setattr(api, "_VIDEO_JOBS", {})
    return api


def test_a_second_video_request_while_one_runs_gets_409(client: TestClient, video_jobs, monkeypatch):
    import threading

    from optodraw.core.scene import Scene

    release = threading.Event()

    def slow(self, path, **options):
        release.wait(30)
        raise RuntimeError("stopped by the test")

    monkeypatch.setattr(Scene, "render_tour_video", slow)
    try:
        first = client.post("/api/render/video", json={})
        assert first.status_code == 200 and first.json()["id"]
        second = client.post("/api/render/video", json={})
        assert second.status_code == 409 and "already" in second.json()["detail"]
        assert client.get(f"/api/render/video/{first.json()['id']}").json()["state"] == "running"
        running = client.get("/api/render/video").json()                  # a reload finds the running job again
        assert running["id"] == first.json()["id"] and running["state"] == "running"
        release.set()
        job = _wait_job(client, first.json()["id"])
        assert job["state"] == "failed" and "stopped by the test" in job["error"]
        assert client.get("/api/render/video").json() == {"id": None, "state": "idle"}
        assert client.post("/api/render/video", json={}).status_code == 200      # the failed job frees the slot
    finally:
        release.set()


def test_a_failed_job_removes_its_folder_but_keeps_its_error(client: TestClient, video_jobs, monkeypatch):
    from pathlib import Path

    from optodraw.core.scene import Scene

    def boom(self, path, **options):
        Path(path).write_bytes(b"partial")
        raise RuntimeError("no chrome")

    monkeypatch.setattr(Scene, "render_tour_video", boom)
    job_id = client.post("/api/render/video", json={}).json()["id"]
    job = _wait_job(client, job_id)
    assert job["state"] == "failed" and job["error"] == "no chrome"
    assert not Path(video_jobs._VIDEO_JOBS[job_id]["folder"]).exists()


def _fast_job(monkeypatch):
    from pathlib import Path

    from optodraw.core.scene import Scene

    def fake(self, path, **options):
        Path(path).write_bytes(b"\x00\x00\x00\x18ftypmp42")
        return Path(path)

    monkeypatch.setattr(Scene, "render_tour_video", fake)


def test_a_done_job_past_the_time_limit_is_gone_after_a_request(client: TestClient, video_jobs, monkeypatch):
    from pathlib import Path

    _fast_job(monkeypatch)
    job_id = client.post("/api/render/video", json={}).json()["id"]
    assert _wait_job(client, job_id)["state"] == "done"
    folder = Path(video_jobs._VIDEO_JOBS[job_id]["folder"])
    assert folder.exists()
    video_jobs._VIDEO_JOBS[job_id]["finished"] -= video_jobs._VIDEO_KEEP_S + 1
    assert client.get(f"/api/render/video/{job_id}").status_code == 404
    assert not folder.exists()


def test_a_timer_removes_an_undownloaded_job_without_any_request(client: TestClient, video_jobs, monkeypatch):
    import time
    from pathlib import Path

    _fast_job(monkeypatch)
    monkeypatch.setattr(video_jobs, "_VIDEO_KEEP_S", 0.3)
    job_id = client.post("/api/render/video", json={}).json()["id"]
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline and not video_jobs._VIDEO_JOBS.get(job_id, {}).get("path"):
        time.sleep(0.05)
    folder = Path(video_jobs._VIDEO_JOBS[job_id]["folder"])
    while time.monotonic() < deadline and job_id in video_jobs._VIDEO_JOBS:
        time.sleep(0.05)
    assert job_id not in video_jobs._VIDEO_JOBS and not folder.exists()


def test_the_server_start_sweeps_the_video_folders_a_stopped_server_left(tmp_path, monkeypatch):
    """Minor 18 of the final review: a job folder in the system temp that has not changed for the time limit goes
    when the app starts; a fresh one (a job that may still run) and other folders stay."""

    import os
    import tempfile
    import time

    from optodraw.app import api

    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    old, fresh, other = (tmp_path / "optodraw-video-job-old"), (tmp_path / "optodraw-video-job-new"), (tmp_path / "keep")
    for folder in (old, fresh, other):
        folder.mkdir()
        (folder / "tour.mp4").write_bytes(b"x")
    past = time.time() - api._VIDEO_KEEP_S - 60
    for path in (old, old / "tour.mp4", other, other / "tour.mp4"):
        os.utime(path, (past, past))
    create_app()
    assert not old.exists() and fresh.exists() and other.exists()


def test_an_unknown_video_job_is_404(client: TestClient, video_jobs):
    assert client.get("/api/render/video/nope").status_code == 404
    assert client.get("/api/render/video/nope/file").status_code == 404


def test_the_job_renders_the_scenes_own_animation_settings(client: TestClient, video_jobs, monkeypatch):
    from optodraw.core.scene import Scene

    seen = {}

    def fake(self, path, **options):
        seen.update(options, metadata=self.metadata.get("animation"))
        out = __import__("pathlib").Path(path)
        out.write_bytes(b"\x00\x00\x00\x18ftypmp42")
        if options.get("progress"):
            options["progress"](5, 10)
        return out

    monkeypatch.setattr(Scene, "render_tour_video", fake)
    spec = _chip_spec()
    spec.setdefault("metadata", {})["animation"] = {"look": "field", "params": {}}
    client.post("/api/scene", json={"spec": spec})
    job = client.post("/api/render/video", json={"width": 320, "height": 180, "fps": 10}).json()
    done = _wait_job(client, job["id"])
    assert done["state"] == "done" and done["done"] == 10 and done["total"] == 10
    assert (seen["width"], seen["height"], seen["fps"]) == (320, 180, 10) and seen["metadata"]["look"] == "field"
    got = client.get(f"/api/render/video/{job['id']}/file")
    assert got.status_code == 200 and got.headers["content-type"] == "video/mp4" and got.content[4:8] == b"ftyp"
    assert client.get(f"/api/render/video/{job['id']}/file").status_code == 404      # the file goes after the download


def test_the_video_request_checks_its_size(client: TestClient, video_jobs):
    assert client.post("/api/render/video", json={"width": 2, "height": 2}).status_code == 422
    assert client.post("/api/render/video", json={"fps": 0}).status_code == 422


def _can_render_mp4() -> bool:
    import shutil

    from optodraw.renderers.capture3d import find_chrome

    return bool(find_chrome(required=False) and shutil.which("ffmpeg"))


@pytest.mark.skipif(not _can_render_mp4(), reason="needs Chrome and ffmpeg")
@pytest.mark.filterwarnings("ignore:.*unconnected port:RuntimeWarning")
def test_the_api_returns_mp4_bytes_for_a_tiny_scene(client: TestClient, video_jobs):
    client.post("/api/scene", json={"spec": _chip_spec()})
    job = client.post("/api/render/video", json={"width": 320, "height": 180, "fps": 5}).json()
    done = _wait_job(client, job["id"])
    assert done["state"] == "done", done
    got = client.get(f"/api/render/video/{job['id']}/file")
    assert got.status_code == 200 and got.headers["content-type"] == "video/mp4"
    assert got.content[4:8] == b"ftyp"
