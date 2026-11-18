"""Acceptance of the vector 3D renderer on on-chip catalog parts.

Depth (Acceptance 3): at 6,000 random page points (seed 7) the nearest front opaque face by plain plane depth owns a
shown piece within 0.02 mm of the point. Ties within 1e-3 world units are skipped. With the depth negated inside
visible(), the far faces win and the same check fails. The bench, the spike chip and the Objective join these parts
when the renderer draws mounts and GDS chips.

The spike chip (tests/fixtures/spike_ring.gds) as a View3D.chip inset, drawn once per module: Acceptance 4 (a figure
is vector), 6 (a page saves, loses its GDS, loads and exports the same bytes) and 7 (the chip SVG under 1 MB)."""

from __future__ import annotations

import numpy as np
import pytest

shapely = pytest.importorskip("shapely")

from optodraw import CustomModel, Scene  # noqa: E402
from optodraw.registry import build_component  # noqa: E402
from optodraw.renderers import vector3d_hidden  # noqa: E402
from optodraw.renderers.vector3d import Vector3DError, render_3d_svg  # noqa: E402
from optodraw.renderers.vector3d_hidden import Camera, camera_for, visible  # noqa: E402
from optodraw.renderers.vector3d_scene import scene_solids  # noqa: E402

PARTS = ("MicroringResonator", "MZI", "PhaseShifter", "OnChipPhotodetector", "YBranch")
OCCLUDED = ("MZI", "OnChipPhotodetector", "YBranch")      # parts where one solid hides another over a large area
PROJECTIONS = ("parallel", "perspective")


def _scene(name: str) -> Scene:
    scene = Scene()
    scene.add(build_component(name))
    return scene


def _wrong_share(name: str, projection: str, *, far_faces_win: bool = False) -> float:
    solids = scene_solids(_scene(name))
    camera, _ = camera_for(solids, "isometric", projection, 120.0)
    if far_faces_win:
        real_depth = Camera.depth
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(vector3d_hidden.Camera, "depth", lambda self, pts: -real_depth(self, pts))
            shown = visible(solids.faces, solids.solids, camera)
    else:
        shown = visible(solids.faces, solids.solids, camera)
    faces = solids.faces
    front = [i for i, f in enumerate(faces) if camera.facing(f) and not solids.solids[f.solid].look.clear]
    polys, planes = [], []
    for i in front:
        ring, depth = camera.page(faces[i].ring), camera.depth(faces[i].ring)
        poly = shapely.Polygon(ring, [camera.page(h) for h in faces[i].holes])
        polys.append(poly if poly.is_valid else shapely.make_valid(poly))
        planes.append(np.linalg.lstsq(np.column_stack((ring, np.ones(len(ring)))), depth, rcond=None)[0])
    polys, planes = np.array(polys, dtype=object), np.array(planes)
    owned: dict[int, list] = {}
    for i, geom in shown.pieces:
        owned.setdefault(i, []).append(geom)
    region = {i: shapely.union_all(g) for i, g in owned.items()}
    tree = shapely.STRtree(polys)
    rng = np.random.default_rng(7)
    x0, y0, x1, y1 = shapely.total_bounds(polys)
    tested = wrong = 0
    while tested < 6000:
        point = shapely.Point(rng.uniform(x0, x1), rng.uniform(y0, y1))
        hits = tree.query(point, predicate="intersects")
        if not len(hits):
            continue
        tested += 1
        depth = planes[hits, 0] * point.x + planes[hits, 1] * point.y + planes[hits, 2]
        order = np.argsort(depth)[::-1]
        if len(hits) > 1 and abs(camera.distance(depth[order[0]]) - camera.distance(depth[order[1]])) < 1e-3:
            continue
        shown_part = region.get(front[hits[order[0]]])
        if shown_part is None or shown_part.distance(point) > 0.02:
            wrong += 1
    return wrong / tested


@pytest.mark.parametrize("projection", PROJECTIONS)
@pytest.mark.parametrize("name", PARTS)
def test_depth_matches_plane_depth(name, projection):
    assert _wrong_share(name, projection) == 0.0


@pytest.mark.parametrize("projection", PROJECTIONS)
@pytest.mark.parametrize("name", OCCLUDED)
def test_depth_check_fails_on_far_faces(name, projection):
    assert _wrong_share(name, projection, far_faces_win=True) > 0.05


@pytest.mark.parametrize("projection", PROJECTIONS)
def test_render_3d_svg_draws_an_on_chip_part_the_same_each_time(tmp_path, projection):
    scene = _scene("MZI")
    first = render_3d_svg(scene, projection=projection)
    assert first.startswith("<svg") and 'data-art="3d"' in first and "<image" not in first
    assert render_3d_svg(scene, tmp_path / "mzi.svg", projection=projection).read_text(encoding="utf-8") == first


def test_a_kind_the_renderer_does_not_draw_yet_raises_with_the_part():
    scene = Scene()
    scene.add(CustomModel("arm.glb"))                     # its label comes from its file: the error names the part
    with pytest.raises(Vector3DError, match=r"CustomModel 'arm': .*external_model.*render_3d_image"):
        render_3d_svg(scene)


# ---------------------------------------------------------------- the spike chip as an inset: Acceptance 4, 6 and 7

import json  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402
from pathlib import Path  # noqa: E402

from optodraw import Callout, Inset, View3D  # noqa: E402
from optodraw.figure.page import Page  # noqa: E402
from optodraw.figure.sources import cut_section  # noqa: E402

SPIKE = Path(__file__).parent / "fixtures" / "spike_ring.gds"   # public gdsfactory generic cells: a heated ring
CHIP_MM = 120.0
CUT = ((-29.0, 20.0), (-16.0, 20.0))          # file um: through the left arm of the ring and its heater
TARGETS = {"Heater": (-16.5, 6.5, 1.85), "Ring": (12.55, 2.93, 0.22), "Bond pad": (-45.0, 90.0, 5.2)}  # file um, true z


@pytest.fixture(scope="module")
def spike(tmp_path_factory):
    """The spike chip from a copy of the fixture, drawn once at 120 mm: the view and the path of its GDS copy."""

    pytest.importorskip("gdstk")
    gds = tmp_path_factory.mktemp("spike") / "data" / "spike_ring.gds"
    gds.parent.mkdir()
    shutil.copy(SPIKE, gds)
    view = View3D.chip(gds, "gdsfactory_generic", z_scale=4)
    view.fragment(CHIP_MM, font_pt=7.0)
    return view, gds


def _spike_page(view, gds) -> Page:
    """The chip at 120 mm (the view's own drawing), the section of the cut beside it, a callout on each target."""

    page = Page(width_mm=183, height_mm=95, font_pt=7.0, letters=False)
    chip = page.add(Inset(view, center=(60, 45), width=CHIP_MM, label="chip"))
    page.add(Inset(cut_section(gds, "gdsfactory_generic", CUT), center=(152, 45), width=58, label="section"))
    for i, (text, point) in enumerate(TARGETS.items()):
        page.add(Callout(text, center=(15 + 55 * i, 89), target=chip.at(*point)))
    return page


def test_the_spike_chip_svg_is_under_1_mb(spike):
    # Acceptance 7. Mutant: the spike's first writer, one path per facet piece (_merged returns the parts) at full
    # float precision (_rings writes repr): 2,688,408 bytes. Measured 2026-11-06: this view 284,152 bytes with its
    # shadows, 263,240 without; the merge off alone 859,326 and full precision alone 708,266, so neither alone passes
    # 1 MB
    size = len(spike[0].fragment(CHIP_MM, font_pt=7.0).svg.encode("utf-8"))
    assert size < 1_000_000, f"the spike chip SVG is {size:,} bytes, over 1 MB"


def test_a_chip_figure_is_pure_vector(spike, tmp_path):
    # Acceptance 4. Mutant: put the chip in as Image(scene.render_3d_image(...)); pdfimages lists one image
    tools = {name: shutil.which(name) for name in ("pdfimages", "pdffonts", "pdftotext")}
    if None in tools.values():
        pytest.skip("needs poppler: pdfimages, pdffonts and pdftotext")
    files = _spike_page(*spike).export(tmp_path / "figure", formats=("svg", "pdf"))

    def run(*args: str) -> str:
        return subprocess.run(args, capture_output=True, text=True, check=True).stdout

    assert "<image" not in files["svg"].read_text(encoding="utf-8")
    images = run(tools["pdfimages"], "-list", str(files["pdf"])).splitlines()
    assert len(images) == 2, images                                        # the header and its rule only
    fonts = run(tools["pdffonts"], str(files["pdf"])).splitlines()
    column = fonts[0].index("emb")
    assert len(fonts) > 2 and all(row[column:column + 3] == "yes" for row in fonts[2:]), fonts
    words = run(tools["pdftotext"], str(files["pdf"]), "-")
    assert [text for text in TARGETS if text not in words] == []


def test_a_chip_page_exports_the_same_bytes_with_its_gds_gone(spike, tmp_path):
    # Acceptance 6, and a chip record rebuilds. Mutants: fragment_record keeps no map (the callouts cannot land after
    # the load); View3D leaves _PATH_KEYS (the record keeps the GDS path as given, not relative to the page file)
    view, gds = spike
    page = _spike_page(view, gds)
    before = page.export(tmp_path / "before", formats=("svg",))["svg"].read_bytes()
    saved = gds.parent.parent / "pages" / "figure.json"
    saved.parent.mkdir(exist_ok=True)
    page.save(saved)
    record = next(c for c in json.loads(saved.read_text())["components"] if c.get("label") == "chip")["source"]
    assert (record["kind"], record["path"], record["stack"]) == ("View3D", "../data/spike_ring.gds",
                                                                 "gdsfactory_generic")
    away = gds.with_suffix(".away")
    gds.rename(away)
    try:
        loaded = Page.load(saved)
        assert loaded.export(tmp_path / "after", formats=("svg",))["svg"].read_bytes() == before
    finally:
        away.rename(gds)
    inset = next(node for node in loaded.walk() if isinstance(node, Inset) and node.label == "chip")
    inset.rebuild()                                                        # the GDS is back: the record draws again
    assert inset.fragment().svg == view.fragment(CHIP_MM, font_pt=7.0).svg
