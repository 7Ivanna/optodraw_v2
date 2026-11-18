"""View3D: a vector 3D view as an inset source, with marks on true 3D points (Part B, plan section 6).

Each test names the mutant that must fail it. The tests here draw small scenes; the spike chip lives in
test_vector3d_acceptance.py."""

from __future__ import annotations

import json
import re
import warnings

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("shapely")
gdstk = pytest.importorskip("gdstk")

from optodraw import Callout, GDSModel, GdsView, Inset, Scene, View3D, check_export, check_figure  # noqa: E402
from optodraw.core.transform import Vec3  # noqa: E402
from optodraw.figure.fragment import place_from  # noqa: E402
from optodraw.figure.inset import CutLink  # noqa: E402
from optodraw.figure.page import Page  # noqa: E402
from optodraw.figure.sources import cut_section  # noqa: E402
from optodraw.figure.sources import from_record  # noqa: E402
from optodraw.registry import build_component  # noqa: E402
from optodraw.renderers import vector3d, vector3d_hidden  # noqa: E402
from optodraw.renderers.vector3d import SHADOW_INK, Vector3DError  # noqa: E402
from optodraw.renderers.vector3d_hidden import Camera  # noqa: E402
from optodraw.renderers.vector3d_scene import home_pose, scene_solids  # noqa: E402

STACK = "gdsfactory_generic"
BLOCK_Z = 2.0                        # the block's height in scene units
BLOCK_CORNERS = [(x, y) for x in (-5.0, 25.0) for y in (15.0, 25.0)]     # its top corners: 30 by 10 at (10, 20)


def _vertices(svg: str) -> np.ndarray:
    return np.array([(float(a), float(b)) for a, b in re.findall(r"[ML](-?[\d.]+) (-?[\d.]+)", svg)])


def _block_scene(tmp_path) -> Scene:
    """One 30 by 10 GDS block, 2 high, centred on (10, 20) of an on-chip scene: its top corners are known."""

    library = gdstk.Library()
    library.new_cell("TOP").add(gdstk.rectangle((0, 0), (30, 10), layer=1))
    library.write_gds(str(tmp_path / "block.gds"))
    scene = Scene(width=100, height=60, platform="on_chip")
    scene.add(GDSModel(str(tmp_path / "block.gds"), cell_name="TOP", center=(10, 20),
                       layer_stack={(1, 0): {"thickness": BLOCK_Z, "zmin": 0.0, "material_preset": "silicon",
                                             "opacity": 1.0}}))
    return scene


def _soi(tmp_path):
    """A waveguide and a pad on gdsfactory_generic: the pad's top is M3, z = 3.2 + 2.0 um."""

    library = gdstk.Library()
    cell = library.new_cell("TOP")
    cell.add(gdstk.rectangle((0, -0.25), (30, 0.25), layer=1))
    cell.add(gdstk.rectangle((5, 5), (15, 15), layer=49))
    path = tmp_path / "soi.gds"
    library.write_gds(str(path))
    return path


def _ring_scene():
    scene = Scene(width=100, height=60, platform="on_chip")
    return scene, scene.add(build_component("MicroringResonator"))


def _chip_solids(view: View3D):
    return [s for s in scene_solids(view.scene).solids if s.chip]


# ---------------------------------------------------------------- fragment: the camera map


@pytest.mark.parametrize("projection", ["perspective", "parallel"])
def test_the_camera_map_is_the_cameras_page(tmp_path, projection):
    # mutant: swap right and up in place_from's camera form (or in the map View3D writes); the points move off
    shape = View3D(_block_scene(tmp_path), projection=projection).fragment(80.0, font_pt=7).map
    assert shape["form"] == "camera"
    back = np.array(shape["back"])
    camera = Camera(eye=np.array(shape["eye"]), target=np.array(shape["eye"]) - back,
                    perspective=shape["perspective"], k=shape["k"], origin=tuple(shape["origin"]))
    world = np.array(shape["world"]).reshape(3, 4)
    place = place_from(json.loads(json.dumps(shape)))                    # the map as a page file keeps it
    for point in np.random.default_rng(7).uniform(-30, 40, size=(50, 3)):
        want = camera.page(world @ np.append(point, 1.0))[0]
        assert place(*point) == pytest.approx(tuple(want), abs=1e-9)


def test_a_point_behind_the_eye_raises(tmp_path):
    # mutant: drop the behind-the-eye check; the point lands mirrored on the page
    shape = View3D(_block_scene(tmp_path)).fragment(80.0, font_pt=7).map
    wx, wy, wz = np.array(shape["eye"]) + 10.0 * np.array(shape["back"])  # behind the camera
    with pytest.raises(ValueError, match="behind the eye"):
        place_from(shape)(wx, -wz, wy)                                    # the scene point of that world point


# ---------------------------------------------------------------- View3D of a scene


def test_a_box_top_corner_lands_on_a_drawn_vertex(tmp_path):
    # mutant: drop the z axis flip in SCENE_AXES (world z = +y); the corners land 10 mm and more off the block
    fragment = View3D(_block_scene(tmp_path)).fragment(80.0, font_pt=7)
    vertices = _vertices(fragment.svg)
    for x, y in BLOCK_CORNERS:
        gap = np.linalg.norm(vertices - np.array(fragment.place(x, y, BLOCK_Z)), axis=1).min()
        assert gap < 0.01, f"the corner ({x}, {y}) lands {gap:.3f} mm from the drawing"


def test_the_fragment_is_art_and_check_export_finds_no_hairline(tmp_path):
    # mutant: drop data-art from the root group of draw(); its 0.085 pt outlines become hairline findings
    view = View3D(_block_scene(tmp_path))
    assert 'data-art="3d"' in view.fragment(80.0, font_pt=7).svg
    page = Page(width_mm=100, height_mm=80, letters=False)
    page.add(Inset(view, center=(50, 40), width=80))
    svg = page.export(tmp_path / "page", formats=("svg",))["svg"]
    assert not [finding for finding in check_export(svg) if "thinner" in finding]


def test_a_mark_at_a_hidden_point_is_a_finding(tmp_path):
    # mutant: return covered=None from View3D's fragment; the hidden target is not found
    page = Page(width_mm=120, height_mm=90, letters=False)
    view = page.add(Inset(View3D(_block_scene(tmp_path)), center=(60, 45), width=80, label="block"))
    page.add(Callout("Inside", center=(10, 85), target=view.at(10, 20, BLOCK_Z / 2)))
    page.add(Callout("Top", center=(110, 85), target=view.at(10, 20, BLOCK_Z)))
    found = check_figure(page)
    assert 'the target of "Inside" is hidden in the inset "block": point at a place that shows' in found
    assert not [finding for finding in found if '"Top"' in finding and "hidden" in finding]


def test_a_loaded_3d_inset_with_marks_is_one_finding(tmp_path):
    # mutant: drop the loaded-3D-inset finding from check_figure; the gap goes silent
    page = Page(width_mm=120, height_mm=90, letters=False)
    view = page.add(Inset(View3D(_ring_scene()[0]), center=(60, 45), width=80, label="ring"))
    page.add(Callout("a", center=(10, 85), target=view.at(0, 0, 0)))
    page.add(Callout("b", center=(110, 85), target=view.at(1, 0, 0)))
    page.save(tmp_path / "page.json")
    found = [finding for finding in check_figure(Page.load(tmp_path / "page.json")) if "3D inset" in finding]
    assert len(found) == 1 and '"ring"' in found[0] and "rebuild()" in found[0]


def test_covered_reads_the_hidden_step_of_the_drawing(tmp_path, monkeypatch):
    # mutant: covered runs visible() again on its first question; the hidden step runs twice
    calls = []
    real = vector3d.visible

    def counted(*args, **kwargs):
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(vector3d, "visible", counted)
    monkeypatch.setattr(vector3d_hidden, "visible", counted)
    fragment = View3D(_block_scene(tmp_path)).fragment(80.0, font_pt=7)
    assert fragment.covered(10, 20, BLOCK_Z / 2) and not fragment.covered(10, 20, BLOCK_Z)
    assert len(calls) == 1


def test_camera_home_takes_the_viewers_framed_pose():
    # mutant: camera_for ignores camera="home"; the eye stays 2.2 box diagonals out along the direction
    scene, _ = _ring_scene()
    shape = View3D(scene, camera="home").fragment(80.0, font_pt=7).map
    eye, _ = home_pose(scene_solids(scene), "isometric")
    assert shape["eye"] == pytest.approx([float(v) for v in eye], abs=1e-9)
    with pytest.raises(ValueError, match="'home'"):
        View3D(scene, camera="far")


def test_shadows_and_face_limit_reach_the_renderer():
    # mutant: View3D drops shadows= or face_limit= on its way to the renderer
    scene, _ = _ring_scene()
    assert SHADOW_INK in View3D(scene).fragment(80.0, font_pt=7).svg
    assert SHADOW_INK not in View3D(scene, shadows=False).fragment(80.0, font_pt=7).svg
    with pytest.raises(Vector3DError, match=r"after culling, over the limit of 10: crop the chip with region="):
        View3D(scene, face_limit=10).fragment(80.0, font_pt=7)


def test_the_record_keeps_camera_shadows_and_face_limit(tmp_path):
    # mutant: to_record leaves shadows out; the loaded view draws its shadows again
    scene, _ = _ring_scene()
    record = json.loads(json.dumps(View3D(scene, camera="home", shadows=False, face_limit=5000).to_record()))
    loaded = from_record(record, tmp_path)
    assert (loaded.camera, loaded.shadows, loaded.face_limit) == ("home", False, 5000)


def test_a_scene_view_saves_live_and_a_changed_scene_saves_frozen(tmp_path):
    # mutant: compare the spec with the scene as it is now, not as it was drawn; the changed scene saves live
    scene, ring = _ring_scene()
    page = Page(width_mm=120, height_mm=90, letters=False)
    page.add(Inset(View3D(scene), center=(60, 45), width=80, label="ring"))
    page.svg()
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        page.save(tmp_path / "live.json")
    stored = next(c for c in json.loads((tmp_path / "live.json").read_text())["components"] if c["type"] == "Inset")
    assert stored["source"]["kind"] == "View3D" and "scene" in stored["source"]
    assert stored["fragment"]["frozen"] is False
    ring.transform.position = Vec3(30.0, 10.0, 0.0)                         # after the drawing
    with pytest.warns(UserWarning, match=r"'ring' saves its scene frozen.*rebuild"):
        page.save(tmp_path / "frozen.json")


def test_a_scene_with_a_gds_part_saves_frozen(tmp_path):
    # mutant: leave the View3D scene record out of the file check in record_of; the GDS path saves as is
    page = Page(width_mm=120, height_mm=90, letters=False)
    page.add(Inset(View3D(_block_scene(tmp_path)), center=(60, 45), width=80, label="chip"))
    with pytest.warns(UserWarning, match=r"'chip'.*a file of its own"):
        page.save(tmp_path / "page.json")
    stored = next(c for c in json.loads((tmp_path / "page.json").read_text())["components"] if c["type"] == "Inset")
    assert stored["source"] == {"kind": "View3D"} and stored["fragment"]["frozen"] is True


# ---------------------------------------------------------------- View3D.chip


def test_a_chip_pad_corner_lands_on_its_top_and_the_note_names_the_scale(tmp_path):
    # mutant: forget z_scale in the chip's world map; the corners land under the pad top
    view = View3D.chip(_soi(tmp_path), STACK)
    fragment = view.fragment(60.0, font_pt=7)
    assert fragment.notes == ("heights 4 times true",)
    vertices = _vertices(fragment.svg)
    for x, y in ((5, 5), (15, 5), (15, 15), (5, 15)):
        assert np.linalg.norm(vertices - np.array(fragment.place(x, y, 5.2)), axis=1).min() < 0.01
        assert not fragment.covered(x, y, 5.2)
    assert fragment.covered(10, 10, 3.0)                                   # under the pad
    assert not fragment.covered(20, 0, 0.22)                               # the guide under the clear cladding


def test_an_inp_chip_has_no_silicon_handle_and_no_oxide(tmp_path):
    # mutant: let _WaferChip take GDSModel's own regions; a silicon handle and a clear oxide block come back
    library = gdstk.Library()
    cell = library.new_cell("TOP")
    cell.add(gdstk.rectangle((0, 1), (30, 4), layer=1), gdstk.rectangle((0, -4), (30, -1), layer=1))
    library.write_gds(str(tmp_path / "inp.gds"))
    solids = _chip_solids(View3D.chip(tmp_path / "inp.gds", "inp_generic"))
    presets = {s.look.preset for s in solids}
    assert presets - {"polyimide"} == {"indium_phosphide", "ingaasp", "ingaas"}       # the trench fill may show
    assert not [s for s in solids if s.look.clear and s.look.preset != "polyimide"]    # so may its clear cap


def test_a_crop_ends_at_the_region_edges(tmp_path):
    # mutant: pad a crop's footprint like a whole chip's; the wafer reaches past the region
    built = scene_solids(View3D.chip(_soi(tmp_path), STACK, region=(2, -3, 20, 12)).scene)
    chip = {s.id for s in built.solids if s.chip}
    points = np.vstack([f.ring for f in built.faces if f.solid in chip])
    assert np.ptp(points[:, 0]) == pytest.approx(18.0) and np.ptp(points[:, 2]) == pytest.approx(15.0)


@pytest.mark.parametrize("box", ["opaque", "clear"])
def test_the_box_is_opaque_unless_asked_clear(tmp_path, box):
    # mutant: ignore box in _WaferChip._look; one of the two cases fails
    solids = _chip_solids(View3D.chip(_soi(tmp_path), STACK, box=box))
    opaque_oxide = [s for s in solids if s.look.preset == "sio2" and not s.look.clear]
    assert bool(opaque_oxide) is (box == "opaque")
    assert [s for s in solids if s.look.preset == "silicon" and not s.look.clear]     # the handle and the guide


def test_a_missing_gds_is_an_error(tmp_path):
    # mutant: drop the file check; GDSModel draws its fallback slab with no word
    with pytest.raises(FileNotFoundError, match="gone.gds"):
        View3D.chip(tmp_path / "gone.gds", STACK)


# ---------------------------------------------------------------- show_cut


def test_show_cut_draws_the_cut_on_the_3d_view(tmp_path):
    # mutant: draw the cut at z = 0, not at the top of the chip; the ends move off the stack top
    gds = _soi(tmp_path)
    page = Page(width_mm=183, height_mm=90, letters=False)
    view = page.add(Inset(View3D.chip(gds, STACK), center=(45, 45), width=80))
    section = page.add(Inset(cut_section(gds, STACK, ((10, -3), (10, 3))), center=(140, 45), width=60))
    link = page.add(view.show_cut(section))
    top = view.source._top()
    assert top == pytest.approx(5.2 + 0.5)                                 # the pad top and the cover over it
    assert link._places()[:2] == [pytest.approx(view.at(10, -3, top).xy()), pytest.approx(view.at(10, 3, top).xy())]
    line = link.annotation_2d()["children"][0]
    assert line["type"] == "line" and "stroke_dasharray" in line
    assert [text for text, _, _ in link._letters(link._places())] == ["A", "A′", "A", "A′"]


def test_show_cut_leaves_the_section_letters_to_a_gds_cut(tmp_path):
    # mutant: drop the marked check in show_cut; the section's corners get their letters twice
    gds = _soi(tmp_path)
    page = Page(width_mm=183, height_mm=150, letters=False)
    plan = page.add(Inset(GdsView(gds, STACK, (-2, -5, 32, 20)), center=(45, 110), width=80))
    section = page.add(plan.cut((10, -3), (10, 3), center=(140, 110), width=60))
    view = page.add(Inset(View3D.chip(gds, STACK), center=(45, 40), width=80))
    link = page.add(view.show_cut(section))
    assert link.section is None and len(link._places()) == 2
    assert isinstance(section.links[0], CutLink) and section.links[0].section is section


def test_show_cut_takes_a_chip_view_only(tmp_path):
    gds = _soi(tmp_path)
    scene_view = Inset(View3D(_block_scene(tmp_path)), center=(45, 45), width=80)
    section = Inset(cut_section(gds, STACK, ((10, -3), (10, 3))), center=(140, 45), width=60)
    with pytest.raises(TypeError, match="View3D.chip"):
        scene_view.show_cut(section)
