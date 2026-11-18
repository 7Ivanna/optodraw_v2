"""Look C: the cut 3D slab. The face is the cross-section; the block behind it is the same process, cut again."""

from __future__ import annotations

from pathlib import Path

import pytest
from shapely.affinity import scale
from shapely.ops import unary_union

from optodraw.gds.layout import GDSLayerRecord, GDSLayout
from optodraw.gds.xsection.model import cross_section
from optodraw.gds.xsection.slab import slab_model


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
