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


