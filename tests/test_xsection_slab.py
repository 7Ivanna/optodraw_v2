"""Look C: the cut 3D slab. The face is the cross-section; the block behind it is the same process, cut again."""

from __future__ import annotations

from pathlib import Path

import pytest
from shapely.affinity import scale
from shapely.ops import unary_union

from optodraw.gds.layout import GDSLayerRecord, GDSLayout
from optodraw.gds.xsection.model import cross_section
from optodraw.gds.xsection.slab import INK, slab_model


def _record(spec, polygons):
    return GDSLayerRecord(spec=spec, name=f"L{spec[0]}", description="", color="#000000", opacity=1.0,
                          thickness=0.22, zmin=0.0, material_preset="silicon", polygons=polygons, matched_pdk=False)


def _rect(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def _modulator() -> GDSLayout:
    """A rib along y on its slab, N left and P right, M1 on the left and one contact under it at y 2..3."""

    return GDSLayout(source_path=Path("t.gds"), cell_name="T", bounds=(-4, -10, 4, 10), layer_records=[
        _record((1, 0), [_rect(-0.25, -10, 0.25, 10)]),
        _record((3, 0), [_rect(-3, -10, 3, 10)]),
        _record((20, 0), [_rect(-3, -10, 0, 10)]),
        _record((21, 0), [_rect(0, -10, 3, 10)]),
        _record((40, 0), [_rect(-2.4, 2, -1.6, 3)]),
        _record((41, 0), [_rect(-2.8, -10, -1.2, 10)]),
    ])


@pytest.fixture(scope="module")
def xs():
    return cross_section(_modulator(), "gdsfactory_generic", ((-4, 0), (4, 0)))


def _face(model, region):
    return unary_union([p.polygon for p in model.pieces if p.region == region and p.t0 == 0.0])


def test_the_face_of_the_block_is_the_cross_section(xs):
    model = slab_model(xs, depth=6.0)
    for name, region in xs.regions.items():
        if region.is_empty:
            continue
        assert _face(model, name).symmetric_difference(region).area == pytest.approx(0.0, abs=1e-9), name


def test_the_doped_silicon_on_the_face_carries_its_species(xs):
    model = slab_model(xs, depth=6.0)
    for species in ("N", "P"):
        doped = unary_union([p.polygon for p in model.pieces if species in p.species and p.t0 == 0.0])
        assert doped.symmetric_difference(xs.doping[species]).area == pytest.approx(0.0, abs=1e-9)
        assert {p.material for p in model.pieces if species in p.species} == {"silicon"}


def test_a_contact_behind_the_face_shows_only_at_its_depth(xs):
    model = slab_model(xs, depth=6.0, cutaway=False)
    contact = [p for p in model.pieces if p.region == "VIAC"]
    assert contact and min(p.t0 for p in contact) == pytest.approx(2.0) and max(p.t1 for p in contact) == pytest.approx(3.0)
    assert unary_union([p.polygon for p in contact]).bounds[1] == pytest.approx(0.09, abs=1e-6)   # on the slab


def test_the_block_reaches_its_depth_and_the_default_depth_is_its_width(xs):
    assert max(p.t1 for p in slab_model(xs, depth=6.0).pieces) == pytest.approx(6.0)
    model = slab_model(xs)
    assert model.depth == pytest.approx(xs.window[1] - xs.window[0])


def test_the_cutaway_lowers_the_cladding_in_steps(xs):
    model = slab_model(xs, depth=8.0)
    (f0, f1, front), (m0, m1, middle), (r0, r1, rear) = model.strips
    assert front is None and middle == pytest.approx(1.1) and rear == pytest.approx(0.0)
    assert (f0, r1) == (0.0, 8.0) and f1 == m0 and m1 == r0
    oxide = [p for p in model.pieces if p.region == "oxide"]
    assert max(p.polygon.bounds[3] for p in oxide if p.t1 <= f1 + 1e-9) > 3.0           # the full stack in front
    assert max(p.polygon.bounds[3] for p in oxide if m0 - 1e-9 <= p.t0 < m1) <= 1.1 + 1e-9
    assert not [p for p in oxide if p.t0 >= r0 - 1e-9]                                 # none left over the BOX
    metal = [p for p in model.pieces if p.region == "M1"]
    assert [p for p in metal if m0 - 1e-9 <= p.t0 < m1]                  # the metal shows in the middle step
    assert not [p for p in metal if p.t0 >= r0 - 1e-9]
    rib = [p for p in model.pieces if p.region == "device" and p.t0 >= r0 - 1e-9]
    assert max(p.polygon.bounds[3] for p in rib) == pytest.approx(0.22)    # and the rib bare at the back


def test_each_step_also_removes_the_metal_that_starts_above_it():
    layout = _modulator()
    layout.layer_records += [_record((44, 0), [_rect(-2.4, -1, -1.6, 1)]), _record((45, 0), [_rect(-2.8, -10, -1.2, 10)])]
    xs = cross_section(layout, "gdsfactory_generic", ((-4, 0), (4, 0)))
    model = slab_model(xs, depth=8.0)
    (_, f1, _), (m0, m1, _), _ = model.strips
    m2 = [p for p in model.pieces if p.region == "M2"]
    assert m2 and max(p.t1 for p in m2) <= f1 + 1e-9                        # M2 only in the full front step
    assert [p for p in model.pieces if p.region == "M1" and m0 - 1e-9 <= p.t0 < m1]


def test_no_cutaway_keeps_the_full_stack_everywhere(xs):
    model = slab_model(xs, depth=8.0, cutaway=False)
    assert [level for _, _, level in model.strips] == [None]
    oxide = [p for p in model.pieces if p.region == "oxide"]
    assert min(p.polygon.bounds[3] for p in oxide) > 3.0


def test_z_scale_stretches_the_heights_only(xs):
    model = slab_model(xs, depth=6.0, z_scale=2.0)
    stretched = scale(xs.regions["M1"], 1.0, 2.0, origin=(0, 0))
    assert _face(model, "M1").symmetric_difference(stretched).area == pytest.approx(0.0, abs=1e-9)
    assert model.depth == pytest.approx(6.0)


def test_a_cross_section_made_by_hand_has_no_source_for_a_slab(xs):
    from dataclasses import replace

    with pytest.raises(ValueError, match="cross_section"):
        slab_model(replace(xs, source={}))


def _glb_meshes(data: bytes):
    import io

    import trimesh

    return trimesh.load(io.BytesIO(data), file_type="glb").geometry


def test_the_glb_face_is_the_cross_section(xs):
    """glTF is y up: a point (s, t, z) of the block is (s, z, -t), so the face lies at z = 0 facing +z."""

    import numpy as np
    from shapely.geometry import Polygon

    from optodraw.gds.xsection.slab import slab_glb

    faces: dict[str, list] = {}
    for name, mesh in _glb_meshes(slab_glb(slab_model(xs, depth=6.0))).items():
        triangles = mesh.triangles
        front = (np.abs(triangles[:, :, 2]).max(axis=1) < 1e-9) & (mesh.face_normals[:, 2] > 0.5)
        faces.setdefault(name.split(" ")[0], []).extend(Polygon(t[:, :2]) for t in triangles[front])
    for name, region in xs.regions.items():
        if region.is_empty:
            continue
        # glTF keeps float32 coordinates: the edge error is ~1e-8 um, so the area error grows with the outline
        tolerance = max(1e-6, 1e-7 * region.length)
        assert unary_union(faces[name]).symmetric_difference(region).area == pytest.approx(0.0, abs=tolerance), name


def test_the_glb_names_its_materials(xs):
    from optodraw.gds.xsection.slab import slab_glb

    meshes = _glb_meshes(slab_glb(slab_model(xs, depth=6.0)))
    materials = {mesh.visual.material.name for mesh in meshes.values()}
    assert {"silicon", "sio2", "aluminum", "silicon N", "silicon P"} <= materials
    assert {"device N", "device P", "oxide", "box", "handle", "M1", "VIAC"} <= set(meshes)


def test_the_slab_scene_holds_one_extruded_polygon_per_piece(xs):
    from optodraw.gds.xsection.slab import slab_scene

    model = slab_model(xs, depth=6.0)
    scene = slab_scene(model)
    [part] = [node for node in scene.walk() if node.component_type == "CrossSectionSlab"]
    children = part.geometry_3d()["children"]
    solids = [c for c in children if c["material"]["color"] != INK]
    assert len(solids) == len(model.pieces)
    assert {child["shape"] for child in children} == {"extruded_polygon"}
    assert part.lies_on_table                                               # no post under it
    assert "CrossSectionSlab" in scene.render_threejs(show_labels=False)


def test_the_face_carries_outlines_like_look_a_just_in_front_of_it(xs):
    from optodraw.gds.xsection.slab import face_outline, slab_scene

    model = slab_model(xs, depth=6.0)
    lines = face_outline(model)
    width = (xs.window[1] - xs.window[0]) / 800.0
    assert lines.buffer(1e-9).covers(xs.regions["M1"].boundary)
    assert lines.buffer(-width).is_empty and 0.0 < lines.area <= width * lines.length / 2.0   # thin strips

    def ink(scene):
        [part] = [n for n in scene.walk() if n.component_type == "CrossSectionSlab"]
        return [c for c in part.geometry_3d()["children"] if c["material"]["color"] == INK]

    shown = ink(slab_scene(model))
    front = model.depth / 2.0                                                  # the face, the block centred
    assert shown and all(0.0 < c["height"] <= width and c["position"][2] == front for c in shown)
    assert {c.get("edges") for c in shown} == {INK}                         # a line a pixel wide when small
    assert ink(slab_scene(model, outline=False)) == []


def _chrome():
    from optodraw.renderers.capture3d import find_chrome

    return find_chrome(required=False)


@pytest.mark.skipif(not _chrome(), reason="needs Chrome, Chromium or Edge")
def test_the_slab_renders_headless_and_shows_the_implants(xs, tmp_path):
    import numpy as np
    from PIL import Image

    out = xs.slab(tmp_path / "slab.png", width=600, height=400, scale=1)
    image = np.asarray(Image.open(out).convert("RGBA")).astype(int)
    assert image.shape[:2] == (400, 600)
    filled = image[:, :, 3] > 0
    columns, rows = np.nonzero(filled.any(axis=0))[0], np.nonzero(filled.any(axis=1))[0]
    assert columns.max() - columns.min() > 0.6 * 600 or rows.max() - rows.min() > 0.6 * 400   # framed tight
    r, g, b = image[:, :, 0], image[:, :, 1], image[:, :, 2]
    assert ((r > b + 25) & (r > g + 25) & filled).sum() > 200              # N-doped silicon behind the cut


def test_slab_writes_by_suffix_and_gives_the_scene_with_no_path(xs, tmp_path):
    glb = xs.slab(tmp_path / "s.glb", depth=4.0)
    assert glb == tmp_path / "s.glb" and glb.read_bytes()[:4] == b"glTF"
    assert "CrossSectionSlab" in xs.slab(tmp_path / "s.html", depth=4.0).read_text(encoding="utf-8")
    assert any(node.component_type == "CrossSectionSlab" for node in xs.slab(depth=4.0).walk())
    with pytest.raises(ValueError, match=r"\.glb"):
        xs.slab(tmp_path / "s.obj")
