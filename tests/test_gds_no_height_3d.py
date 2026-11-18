"""A GDS layer with no height assigned is left out of the 3D view and the GLB, and the 3D view names it.

The docs device's implant layers (20/0, 21/0, 24/0, 25/0) and its heater (46/0) have no height in the generic
styles. They used to show as made-up slabs (the part's thickness, stacked above the others)."""

from __future__ import annotations

import warnings

import pytest

from gds_layout_fixtures import docs_device_gds

NO_HEIGHT = ["20/0", "21/0", "24/0", "25/0", "46/0"]


def _part(tmp_path, **kwargs):
    from optodraw.components.models import GDSModel

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return GDSModel(source=str(docs_device_gds(tmp_path)), **kwargs)


def _drawn_polygons(part) -> int:
    records = {r["key"]: r for r in part.layer_records()}
    return sum(len(polys) for spec, polys in part._polygons_by_spec.items()
               if records[f"{spec[0]}/{spec[1]}"]["thickness"] is not None)


def test_a_part_names_its_layers_with_no_height(tmp_path):
    part = _part(tmp_path)
    assert part.layers_without_height() == NO_HEIGHT
    part.layer_stack[(20, 0)] = {"thickness": 0.1, "z_offset": 0.0}
    part.layer_stack[(21, 0)] = {"visible": False}
    assert part.layers_without_height() == ["24/0", "25/0", "46/0"]


def test_layers_with_no_height_are_left_out_of_the_3d_view(tmp_path):
    part = _part(tmp_path)
    children = part.geometry_3d()["children"]
    assert len(children) == _drawn_polygons(part)
    made_up = 0.6 * part.thickness
    assert not any(c["height"] == pytest.approx(made_up) for c in children)


def test_a_gds_with_no_heights_at_all_draws_nothing_in_3d(tmp_path):
    import gdstk

    from optodraw.components.models import GDSModel

    lib = gdstk.Library()
    lib.new_cell("odd").add(gdstk.rectangle((0, 0), (10, 2), layer=77))
    path = tmp_path / "odd.gds"
    lib.write_gds(str(path))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        part = GDSModel(source=str(path))
    assert part.layers_without_height() == ["77/0"]
    assert part.geometry_3d()["children"] == []


def test_a_layer_with_no_height_does_not_shape_the_oxide(tmp_path):
    """The synthesized oxide fits the drawn layers: a layer that is not drawn must not widen it."""

    import gdstk

    from optodraw.components.models import GDSModel

    lib = gdstk.Library()
    cell = lib.new_cell("wide")
    cell.add(gdstk.rectangle((0, -0.25), (20, 0.25), layer=1))
    cell.add(gdstk.rectangle((-200, -200), (200, 200), layer=77))
    path = tmp_path / "wide.gds"
    lib.write_gds(str(path))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        part = GDSModel(source=str(path), process_context=True)
    widths = [poly.bounds[2] - poly.bounds[0] for poly, *_ in part.process_context_regions()]
    assert widths and max(widths) < 100


def test_layers_with_no_height_are_left_out_of_the_glb(tmp_path):
    pytest.importorskip("trimesh")
    from optodraw import Scene
    from optodraw.exporters import scene_to_glb_with_report

    scene = Scene(width=200, height=200)
    part = scene.add(_part(tmp_path))
    _, report = scene_to_glb_with_report(scene)
    assert report["meshes"] == _drawn_polygons(part)
    assert report["failed"] == []


def test_the_3d_view_names_the_layers_with_no_height(tmp_path):
    from optodraw import Scene
    from optodraw.renderers.threejs_renderer import ThreeJsRenderer

    scene = Scene(width=200, height=200)
    scene.add(_part(tmp_path, label="pn"))
    items = ThreeJsRenderer(scene)._collect_scene_data()
    assert [item.get("noHeight") for item in items if item.get("label") == "pn"] == [NO_HEIGHT]
    html = ThreeJsRenderer(scene).render()
    assert 'id="od-note"' in html and "function odNote(" in html


def test_a_part_whose_layers_all_have_heights_gets_no_note(tmp_path):
    from optodraw import Scene
    from optodraw.renderers.threejs_renderer import ThreeJsRenderer

    part = _part(tmp_path, label="pn")
    for key in NO_HEIGHT:
        layer, datatype = map(int, key.split("/"))
        part.layer_stack[(layer, datatype)] = {"visible": False}
    scene = Scene(width=200, height=200)
    scene.add(part)
    items = ThreeJsRenderer(scene)._collect_scene_data()
    assert all("noHeight" not in item for item in items)


def test_the_3d_page_shows_the_note_with_the_part_and_its_layers(tmp_path):
    import json

    from optodraw import Scene
    from optodraw.renderers.capture3d import find_chrome, run_page

    if not find_chrome(required=False):
        pytest.skip("needs Chrome, Chromium or Edge")
    scene = Scene(width=200, height=200)
    scene.add(_part(tmp_path, label="pn"))
    probe = ("(function wait(){var n=document.getElementById('od-note');"
             "if(window.odLight&&window.odLight.state.built&&n){document.getElementById('od-capture').value="
             "JSON.stringify({hidden:n.hidden,text:n.textContent});}else{setTimeout(wait,50);}})();")
    html = scene.render_threejs()
    head, tag, tail = html.rpartition("</body>")
    page = head + f'<textarea id="od-capture" style="display:none"></textarea><script>{probe}</script>' + tag + tail
    report = run_page(page, timeout=120)
    assert report and not report.startswith("error"), report
    note = json.loads(report)
    assert note["hidden"] is False
    assert "pn" in note["text"] and ", ".join(NO_HEIGHT) in note["text"] and "no height" in note["text"]
