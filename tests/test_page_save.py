"""A page saves in the scene JSON: each inset keeps its source record and its last fragment inline, so the page opens
and exports with no source file, no GDS and no matplotlib."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from optodraw import Bracket, Callout, DashedLink, Inset, Laser, Lens, Note, Scene
from optodraw.core.transform import Vec3
from optodraw.figure.page import Page

np = pytest.importorskip("numpy")

SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 20">'
       '<rect width="40" height="20" fill="#cccccc"/><text x="2" y="10" font-size="4">file</text></svg>')
STACK = "gdsfactory_generic"
CORE = (1, 0)


def _data(tmp_path):
    """The source files of a page, in their own folder: an SVG file and a PNG."""

    from PIL import Image as PilImage

    folder = tmp_path / "data"
    folder.mkdir(exist_ok=True)
    (folder / "a.svg").write_text(SVG, encoding="utf-8")
    pixels = (np.arange(400 * 200) % 251).astype(np.uint8).reshape(200, 400)
    PilImage.fromarray(pixels, mode="L").save(folder / "p.png")
    return folder


def _plot():
    from matplotlib.figure import Figure

    fig = Figure(figsize=(4, 2), layout="constrained")
    a, b = fig.subplots(1, 2)
    a.plot([1500, 1550, 1600], [-10, -3, -8])
    a.set_xlabel("wavelength (nm)")
    b.plot([100, 200], [5, 9])
    b.set_xscale("log")
    return fig


def _section():
    from optodraw.gds import stack_section

    return stack_section(STACK, CORE, width=0.5)


def _bench():
    scene = Scene(width=100, height=60)
    scene.add(Laser(center=(10, 5)))
    scene.add(Lens(center=(30, -5)))
    return scene


def _page(tmp_path):
    """A page with an SVG file (with a scale bar), a section, a PNG and a matplotlib plot, two anchored callouts and
    a zoom link."""

    folder = _data(tmp_path)
    page = Page(width_mm=183, height_mm=120, font_pt=7.0)
    a = page.add(Inset(str(folder / "a.svg"), center=(30, 100), width=50, bar=(10, "10 um"), label="file"))
    page.add(Inset(_section(), center=(110, 100), width=60, label="section"))
    c = page.add(Inset(str(folder / "p.png"), center=(30, 40), width=40, label="picture"))
    d = page.add(Inset(_plot(), center=(120, 40), width=80, height=40, label="plot"))
    page.add(Callout("edge", center=(70, 70), target=a.at(10, 5)))
    page.add(Callout("peak", center=(150, 70), target=d.at(1550, -3)))
    page.add(Callout("log", center=(170, 15), target=d.at(150, 7, axes=1)))
    page.zoom(a, (10, 5, 20, 15), c)
    return page


def _saved(page, tmp_path):
    path = tmp_path / "pages" / "page.json"
    path.parent.mkdir(exist_ok=True)
    page.save(path)
    return path


def _inset(page, label):
    return next(n for n in page.walk() if isinstance(n, Inset) and n.label == label)


def _callout(page, text):
    return next(n for n in page.walk() if isinstance(n, Callout) and n.text == text)


def _export(page, path):
    return page.export(path, formats=("svg",))["svg"].read_bytes()


def test_a_page_saves_and_loads_as_a_page(tmp_path):
    page = Page(width_mm=120, height_mm=None, font_pt=6.5, letters=False, letter_pt=9.0, title="Fig 2")
    page.add(Inset(None, center=(60, 20), width=40))
    path = _saved(page, tmp_path)
    spec = json.loads(path.read_text())
    assert spec["page"] == {"width_mm": 120.0, "height_mm": None, "font_pt": 6.5, "letters": False, "letter_pt": 9.0}
    loaded = Page.load(path)
    assert isinstance(loaded, Page) and loaded.title == "Fig 2"
    assert (loaded.width_mm, loaded.height_mm, loaded.font_pt, loaded.letters, loaded.letter_pt) == (
        120.0, None, 6.5, False, 9.0)
    assert isinstance(Scene.load(path), Page)
    assert not isinstance(Scene.from_spec(_bench().to_spec()), Page)           # a plain scene stays a scene


def test_the_spec_forms(tmp_path):
    page = _page(tmp_path)
    spec = json.loads(_saved(page, tmp_path).read_text())
    inset = next(c for c in spec["components"] if c["type"] == "Inset" and c.get("label") == "file")
    assert {"type", "center", "width", "source", "fragment"} <= set(inset)
    assert inset["source"] == {"kind": "SvgFile", "path": "../data/a.svg", "drop_text": []}
    fragment = inset["fragment"]
    assert {"svg", "size_mm", "kind", "notes", "map", "frozen", "floor_mm"} <= set(fragment)
    assert fragment["size_mm"] == [50.0, 25.0] and fragment["kind"] == "drawn" and fragment["frozen"] is False
    assert fragment["map"]["form"] == "affine" and len(fragment["map"]["m"]) == 6
    section = next(c for c in spec["components"] if c.get("label") == "section")["fragment"]
    assert (section["width_mm"], section["height_mm"], section["font_pt"]) == (60.0, None, 7.0)   # the page font
    assert inset["bar"] == [10, "10 um"]
    call = next(c for c in spec["components"] if c["type"] == "Callout" and c["text"] == "edge")
    assert call["target"] == {"anchor": inset["id"], "point": [10.0, 5.0], "options": {}}
    log = next(c for c in spec["components"] if c["type"] == "Callout" and c["text"] == "log")
    assert log["target"]["options"] == {"axes": 1}


def test_the_stored_fragment_has_no_scale_bar(tmp_path):
    page = _page(tmp_path)
    spec = json.loads(_saved(page, tmp_path).read_text())
    inset = next(c for c in spec["components"] if c.get("label") == "file")
    assert "10 um" not in inset["fragment"]["svg"] and "10 um" in page.svg()
    loaded = Page.load(tmp_path / "pages" / "page.json")
    assert "10 um" in loaded.svg()                                              # laid over it again after the load


def test_the_export_is_byte_equal_after_a_load(tmp_path):
    page = _page(tmp_path)
    before = _export(page, tmp_path / "before")
    loaded = Page.load(_saved(page, tmp_path))
    assert _export(loaded, tmp_path / "after") == before
    again = tmp_path / "again.json"                                             # a loaded page saves the same file
    loaded.save(again)
    assert _export(Page.load(again), tmp_path / "third") == before


def test_it_exports_with_its_sources_gone(tmp_path):
    page = _page(tmp_path)
    before = _export(page, tmp_path / "before")
    path = _saved(page, tmp_path)
    shutil.rmtree(tmp_path / "data")
    assert _export(Page.load(path), tmp_path / "after") == before


def test_a_page_loads_and_exports_with_no_matplotlib_and_no_gds(tmp_path):
    page = _page(tmp_path)
    before = page.svg()
    path = _saved(page, tmp_path)
    shutil.rmtree(tmp_path / "data")
    out = tmp_path / "out.svg"
    code = ("import sys\n"
            "for name in ('matplotlib', 'shapely', 'gdstk', 'gdsfactory', 'PIL', 'cairosvg'):\n"
            "    sys.modules[name] = None\n"
            "from optodraw.figure.page import Page\n"
            f"svg = Page.load({str(path)!r}).svg()\n"
            f"open({str(out)!r}, 'w', encoding='utf-8').write(svg)\n"
            "assert not [m for m in sys.modules if m.split('.')[0] in ('matplotlib', 'shapely', 'gdstk') "
            "and sys.modules[m] is not None]\n")
    run = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         env={**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)})
    assert run.returncode == 0, run.stderr[-2000:]
    assert out.read_text(encoding="utf-8") == before


def test_a_mark_stays_on_its_point_after_a_load(tmp_path):
    page = _page(tmp_path)
    loaded = Page.load(_saved(page, tmp_path))
    inset, call = _inset(loaded, "file"), _callout(loaded, "edge")
    assert tuple(call.target) == pytest.approx(_inset(page, "file").at(10, 5).xy())
    start = (call.world_position.x, call.world_position.y)
    inset.move_to(40, 90)                                                       # 10 right, 10 down
    assert tuple(call.target) == pytest.approx(inset.at(10, 5).xy())          # the anchor is live again
    assert (call.world_position.x, call.world_position.y) == pytest.approx((start[0] + 10, start[1] - 10))
    peak = _callout(loaded, "peak")
    assert tuple(peak.target) == pytest.approx(_inset(page, "plot").at(1550, -3).xy())


def test_anchors_work_after_a_load_with_no_source(tmp_path):
    page = _page(tmp_path)
    page.svg()                                                                  # every inset at the page font
    want =[_inset(page, name).at(*point, **options).xy() for name, point, options in
            (("file", (10, 5), {}), ("section", (0.0, 0.1), {}), ("picture", (100, 50), {}),
             ("plot", (1550, -3), {}), ("plot", (150, 7), {"axes": 1}))]
    path = _saved(page, tmp_path)
    shutil.rmtree(tmp_path / "data")
    loaded = Page.load(path)
    got = [_inset(loaded, name).at(*point, **options).xy() for name, point, options in
           (("file", (10, 5), {}), ("section", (0.0, 0.1), {}), ("picture", (100, 50), {}),
            ("plot", (1550, -3), {}), ("plot", (150, 7), {"axes": 1}))]
    assert got == want                                                          # the stored map gives the same place


def test_a_plot_is_frozen(tmp_path):
    page = _page(tmp_path)
    path = _saved(page, tmp_path)
    spec = json.loads(path.read_text())
    plot = next(c for c in spec["components"] if c.get("label") == "plot")
    assert plot["source"] == {"kind": "Plot"} and plot["fragment"]["frozen"] is True
    assert plot["fragment"]["map"]["form"] == "plot"
    assert plot["fragment"]["map"]["axes"][1]["x"] == ["log", 10.0]
    loaded = Page.load(path)
    with pytest.raises(ValueError, match="frozen"):
        _inset(loaded, "plot").rebuild()
    live = _inset(page, "plot")                                                 # a live plot redraws from its figure
    old = live.fragment()
    live.rebuild()
    assert live.fragment() is not old and live.fragment().size_mm == old.size_mm
    plot["fragment"]["frozen"] = False                                          # a hand-edited flag: the kind decides
    edited = _inset(Scene.from_spec(spec), "plot")
    with pytest.raises(ValueError, match="frozen"):
        edited.rebuild()
    edited.width = 40.0
    assert edited.fragment().size_mm == pytest.approx((40.0, 20.0))            # scaled, as a frozen plot is


def test_a_scene_whose_spec_does_not_draw_it_again_is_frozen(tmp_path):
    from optodraw.figure.sources import SceneView

    scene = _bench()
    page = Page(width_mm=120, height_mm=80, letters=False)
    page.add(Inset(SceneView(scene), center=(60, 40), width=60, label="bench"))
    before = page.svg()
    scene.add(Lens(center=(60, 0), label="Late"))                               # the page still draws the old view
    with pytest.warns(UserWarning,
                      match=r"'bench'.*saved spec does not draw.*or its spec does not keep every detail.*rebuild"):
        path = _saved(page, tmp_path)
    stored = next(c for c in json.loads(path.read_text())["components"] if c["type"] == "Inset")
    assert stored["source"] == {"kind": "SceneView"} and stored["fragment"]["frozen"] is True
    loaded = Page.load(path)
    assert loaded.svg() == before
    with pytest.raises(ValueError, match="frozen"):
        _inset(loaded, "bench").rebuild()


def test_a_scene_inset_keeps_its_print_scale_after_a_load(tmp_path):
    from optodraw.figure.sources import Text
    from optodraw.publication import export_figure

    scene = _bench()
    inset = scene.add(Inset(Text("two lines\nof text"), center=(60, 20), width=30))   # its height follows the font
    export_figure(scene, tmp_path / "fig", width_mm=120, font_size_pt=7.0, formats=("svg",))   # 1 unit is not 1 mm
    assert inset._mm_per_unit != 1.0
    box = inset.box()
    loaded = Scene.load(_saved(scene, tmp_path))
    assert next(n for n in loaded.walk() if isinstance(n, Inset)).box() == pytest.approx(box)


def test_an_inset_over_another_keeps_it(tmp_path):
    page = Page(width_mm=120, height_mm=80)
    page.add(Inset(None, center=(40, 40), width=60, label="big"))
    page.add(Inset(None, center=(30, 35), width=10, height=6, over=_inset(page, "big"), label="key"))
    page.add(Inset(None, center=(100, 40), width=10, height=6, over=page, label="note"))
    before = page.svg()
    path = _saved(page, tmp_path)
    spec = {c.get("label"): c for c in json.loads(path.read_text())["components"]}
    assert spec["key"]["over"] == spec["big"]["id"] and spec["note"]["over"] is True
    loaded = Page.load(path)
    assert _inset(loaded, "key").over is _inset(loaded, "big") and _inset(loaded, "note").over is True
    assert loaded.svg() == before


def test_rebuild_of_a_live_scene_inset_shows_the_edits(tmp_path):
    from optodraw.figure.sources import SceneView

    scene = _bench()
    page = Page(width_mm=120, height_mm=80, letters=False)
    inset = page.add(Inset(SceneView(scene), center=(60, 40), width=60))
    page.svg()
    scene.add(Lens(center=(60, 0), label="Late"))
    assert "Late" in page.svg()                                                 # each export asks the scene again
    inset.rebuild()
    assert "Late" in inset.fragment().svg


def test_rebuild_reads_the_file_again(tmp_path):
    page = _page(tmp_path)
    loaded = Page.load(_saved(page, tmp_path))
    (tmp_path / "data" / "a.svg").write_text(SVG.replace("#cccccc", "#123456"), encoding="utf-8")
    inset = _inset(loaded, "file")
    assert "#123456" not in inset.fragment().svg                               # the stored fragment, until asked
    inset.rebuild()
    assert "#123456" in inset.fragment().svg and "#123456" in loaded.svg()


def test_rebuild_with_a_lost_file_is_a_clear_error(tmp_path):
    page = _page(tmp_path)
    loaded = Page.load(_saved(page, tmp_path))
    (tmp_path / "data" / "a.svg").unlink()
    inset = _inset(loaded, "file")
    with pytest.raises(FileNotFoundError, match="a.svg"):
        inset.rebuild()
    assert inset.fragment().size_mm == (50.0, 25.0) and "file" in loaded.svg()  # it keeps what it had


def test_paths_are_relative_to_the_page_file(tmp_path):
    page = _page(tmp_path)
    spec = json.loads(_saved(page, tmp_path).read_text())
    sources = {c["label"]: c["source"] for c in spec["components"] if c["type"] == "Inset"}
    assert sources["file"]["path"] == "../data/a.svg" and sources["picture"]["path"] == "../data/p.png"
    live = {c["label"]: c["source"] for c in page.to_spec()["components"] if c["type"] == "Inset"}
    assert live["file"]["path"] == str(tmp_path / "data" / "a.svg")           # with no file: an absolute path
    moved = tmp_path / "moved"
    shutil.copytree(tmp_path / "data", moved / "data")
    shutil.copytree(tmp_path / "pages", moved / "pages")
    shutil.rmtree(tmp_path / "data")
    loaded = Page.load(moved / "pages" / "page.json")
    (moved / "data" / "a.svg").write_text(SVG.replace("#cccccc", "#654321"), encoding="utf-8")
    inset = _inset(loaded, "file")
    inset.rebuild()                                                             # it finds the file beside the page
    assert "#654321" in inset.fragment().svg
    loaded.save(moved / "pages" / "copy.json")                                  # and saves it relative again
    copy = json.loads((moved / "pages" / "copy.json").read_text())
    assert next(c["source"]["path"] for c in copy["components"] if c.get("label") == "file") == "../data/a.svg"


def test_a_record_cannot_name_a_python_object(tmp_path):
    from optodraw.figure.sources import SOURCE_KINDS, from_record
    from optodraw.schema import scene_from_spec

    page = Page(width_mm=100, height_mm=60)
    page.add(Inset(None, center=(50, 30), width=40))
    spec = page.to_spec()
    inset = next(c for c in spec["components"] if c["type"] == "Inset")
    for kind in ("os.system", "builtins.eval", "__import__", ["SvgFile"], None):
        inset["source"] = {"kind": kind, "path": "x.svg"}
        with pytest.raises(ValueError, match="kind"):
            scene_from_spec(json.loads(json.dumps(spec)))
        with pytest.raises(ValueError, match="kind"):
            from_record({"kind": kind}, tmp_path)
    assert "os.system" not in SOURCE_KINDS and "SvgFile" in SOURCE_KINDS
    inset["source"] = {"kind": "EmptyBox", "height": None}
    inset["fragment"]["map"] = {"form": "os.system", "m": [1, 0, 0, 0, 1, 0]}
    with pytest.raises(ValueError, match="map"):
        scene_from_spec(json.loads(json.dumps(spec)))
    inset["fragment"]["map"] = {"form": "affine", "m": ["__import__('os')", 0, 0, 0, 1, 0]}
    with pytest.raises(ValueError, match="number"):
        scene_from_spec(json.loads(json.dumps(spec)))
    inset["fragment"]["map"] = {"form": "affine", "m": [1, 0, 0, 0, 1, 0]}
    inset["fragment"]["kind"] = '"><script>alert(1)</script>'                  # it goes into an SVG attribute
    with pytest.raises(ValueError, match="kind"):
        scene_from_spec(json.loads(json.dumps(spec)))
    inset["fragment"]["kind"] = "drawn"
    inset["id"] = "box"
    spec["components"].append({"type": "Callout", "text": "x", "center": [10, 10],
                               "target": {"anchor": "box", "point": ["__import__('os')", 1], "options": {}}})
    with pytest.raises(ValueError, match="numbers"):
        scene_from_spec(json.loads(json.dumps(spec)))


def test_a_zoom_link_saves_and_loads(tmp_path):
    page = _page(tmp_path)
    spec = json.loads(_saved(page, tmp_path).read_text())
    link = next(c for c in spec["components"] if c["type"] == "ZoomLink")
    ids = {c.get("label"): c["id"] for c in spec["components"] if c["type"] == "Inset"}
    assert (link["small"], link["big"], link["region"]) == (ids["file"], ids["picture"], [10.0, 5.0, 20.0, 15.0])
    loaded = Page.load(tmp_path / "pages" / "page.json")
    zoom = next(n for n in loaded.walk() if n.component_type == "ZoomLink")
    small, big = _inset(loaded, "file"), _inset(loaded, "picture")
    assert zoom.small is small and zoom.big is big and zoom.region == (10.0, 5.0, 20.0, 15.0)
    small.move_to(40, 95)
    assert zoom.drawn_points()[0] == pytest.approx(small.at(10, 5).xy())       # it follows the moved inset


def test_a_frozen_inset_scales_its_stored_fragment(tmp_path):
    page = _page(tmp_path)
    loaded = Page.load(_saved(page, tmp_path))
    loaded.svg()
    plot = _inset(loaded, "plot")
    before = plot.fragment()
    plot.width = 40.0                                                            # half the width it was saved at
    after = plot.fragment()
    assert after.size_mm == pytest.approx((40.0, 20.0)) and after.floor_mm == pytest.approx(before.floor_mm / 2)
    assert after.place(1550, -3) == pytest.approx(tuple(v / 2 for v in before.place(1550, -3)))
    assert after.place(150, 7, axes=1) == pytest.approx(tuple(v / 2 for v in before.place(150, 7, axes=1)))
    assert any("7 pt" in note for note in after.notes) and not any("7 pt" in note for note in before.notes)
    assert 'width="40mm"' in after.svg and 'height="20mm"' in after.svg
    assert loaded.svg()                                                          # it still draws
    spec = loaded.to_spec()                                                      # and saves as it is now
    stored = next(c for c in spec["components"] if c.get("label") == "plot")["fragment"]
    assert stored["size_mm"] == [40.0, 20.0] and stored["frozen"] is True and stored["map"]["form"] == "scaled"


def test_a_lost_file_scales_too(tmp_path):
    page = _page(tmp_path)
    loaded = Page.load(_saved(page, tmp_path))
    shutil.rmtree(tmp_path / "data")
    inset = _inset(loaded, "file")
    inset.width = 100.0
    fragment = inset.fragment()
    assert fragment.size_mm == pytest.approx((100.0, 50.0)) and fragment.place(10, 5) == pytest.approx((25.0, 12.5))
    assert any("7 pt" in note for note in fragment.notes)


def test_a_rebuildable_inset_draws_again_at_a_new_width_on_rebuild(tmp_path):
    from optodraw.figure.sources import SvgFile

    page = _page(tmp_path)
    loaded = Page.load(_saved(page, tmp_path))
    inset = _inset(loaded, "file")
    inset.width = 100.0
    assert any("7 pt" in note for note in inset.fragment().notes)              # scaled until asked
    inset.rebuild()
    fragment = inset.fragment()
    fresh = SvgFile(tmp_path / "data" / "a.svg").fragment(100.0, font_pt=7.0)
    assert fragment.svg == fresh.svg and fragment.notes == () and fragment.place(10, 5) == fresh.place(10, 5)


def test_a_loaded_inset_never_rebuilds_by_itself(tmp_path):
    page = _page(tmp_path)
    loaded = Page.load(_saved(page, tmp_path))
    (tmp_path / "data" / "a.svg").write_text(SVG.replace("#cccccc", "#abcdef"), encoding="utf-8")
    inset = _inset(loaded, "file")
    stored = inset.fragment()
    inset.width, loaded.font_pt = 60.0, 8.0                                     # a new width and a new font
    svg = loaded.svg()
    fragment = inset.fragment()
    assert "#abcdef" not in svg and "#cccccc" in fragment.svg                    # the file was not read again
    assert fragment.size_mm == pytest.approx((60.0, 30.0)) and fragment.svg != stored.svg
    assert any("8 pt" in note for note in fragment.notes)
    inset.rebuild()                                                             # only on purpose
    assert "#abcdef" in inset.fragment().svg and inset.fragment().notes == ()


@pytest.mark.skipif(shutil.which("latex") is None or shutil.which("dvisvgm") is None, reason="needs latex, dvisvgm")
def test_a_loaded_equation_runs_no_tool_until_rebuild(tmp_path, monkeypatch):
    from optodraw.figure.sources import Equation

    page = Page(width_mm=100, height_mm=60, letters=False)
    page.add(Inset(Equation("E = mc^2", tex=True), center=(50, 30), width=30, label="eq"))
    loaded = Page.load(_saved(page, tmp_path))
    ran = []
    real = subprocess.run
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: ran.append(a) or real(*a, **k))
    inset = _inset(loaded, "eq")
    inset.width, loaded.font_pt = 45.0, 9.0
    loaded.svg()
    assert ran == [] and any("9 pt" in note for note in inset.fragment().notes)
    inset.rebuild()
    assert ran and inset.fragment().notes == ()


def test_a_height_change_on_a_frozen_inset_keeps_the_stored_fragment(tmp_path):
    page = _page(tmp_path)
    loaded = Page.load(_saved(page, tmp_path))
    loaded.svg()
    plot = _inset(loaded, "plot")
    stored = plot.fragment()
    plot.height = 30.0                                                          # the width stays: no scale, no note
    loaded.svg()
    assert plot.source.height == 30.0                                           # the source was asked for 30 mm
    assert plot.fragment().svg == stored.svg and plot.fragment().notes == stored.notes == ()
    loaded.font_pt = 8.0                                                        # a new font at the same width
    loaded.svg()
    assert plot.fragment().svg == stored.svg and plot.fragment().notes == ("the saved drawing: its text prints at "
                                                                           "7 pt, not 8 pt",)


def test_note_and_span_anchors_stay_live_after_a_load(tmp_path):
    folder = _data(tmp_path)
    page = Page(width_mm=183, height_mm=120, font_pt=7.0, letters=False)
    a = page.add(Inset(str(folder / "a.svg"), center=(40, 60), width=40, label="file"))
    page.add(Note("n", center=a.at(10, 5)))
    off = page.add(Note("off", center=a.at(30, 15)))
    at = off.transform.position
    off.transform.position = Vec3(at.x + 3.0, at.y, at.z)                       # moved off its place by hand
    page.add(Bracket("b", a.at(0, 20), a.at(40, 20)))
    page.add(DashedLink(a.at(40, 10), (150, 100), text="x"))                    # one anchored end, one plain end
    before = page.svg()
    spec = json.loads(_saved(page, tmp_path).read_text())
    marks = {c.get("label") or c.get("text"): c for c in spec["components"]}
    assert marks["n"]["center"] == {"anchor": "file", "point": [10.0, 5.0], "options": {}}
    assert marks["off"]["center"]["anchor"] == "file" and marks["off"]["center_offset"] == pytest.approx([3.0, 0.0])
    assert [end["anchor"] for end in marks["b"]["ends"]] == ["file", "file"]
    link_ends = next(c for c in spec["components"] if c["type"] == "DashedLink")["ends"]
    assert link_ends[0]["anchor"] == "file" and isinstance(link_ends[1], list)
    loaded = Page.load(tmp_path / "pages" / "page.json")
    assert loaded.svg() == before
    inset = _inset(loaded, "file")
    note, moved = (next(n for n in loaded.walk() if isinstance(n, Note) and n.text == t) for t in ("n", "off"))
    bracket = next(n for n in loaded.walk() if isinstance(n, Bracket))
    link = next(n for n in loaded.walk() if isinstance(n, DashedLink))
    inset.move_to(80, 40)
    assert (note.world_position.x, note.world_position.y) == pytest.approx(inset.at(10, 5).xy())
    want = inset.at(30, 15).xy()
    assert (moved.world_position.x, moved.world_position.y) == pytest.approx((want[0] + 3.0, want[1]))
    assert bracket.start == pytest.approx(inset.at(0, 20).xy()) and bracket.end == pytest.approx(inset.at(40, 20).xy())
    assert link.start == pytest.approx(inset.at(40, 10).xy()) and link.end == pytest.approx((150, 100))


def test_a_mark_of_an_inset_that_left_the_page_saves_its_point(tmp_path):
    folder = _data(tmp_path)
    page = Page(width_mm=120, height_mm=80, letters=False)
    a = page.add(Inset(str(folder / "a.svg"), center=(40, 40), width=40, label="file"))
    call = page.add(Callout("c", center=(90, 60), target=a.at(10, 5)))
    note = page.add(Note("n", center=a.at(20, 5)))
    page.root.children.remove(a)
    spec = json.loads(_saved(page, tmp_path).read_text())
    marks = {c["text"]: c for c in spec["components"]}
    assert marks["c"]["target"] == pytest.approx(list(call.target)) and "center_offset" not in marks["n"]
    loaded = Page.load(tmp_path / "pages" / "page.json")                        # it loads, as plain points
    back = next(n for n in loaded.walk() if isinstance(n, Note) and n.text == "n")
    assert (back.world_position.x, back.world_position.y) == pytest.approx((note.world_position.x,
                                                                           note.world_position.y))


def test_the_editor_cache_relinks_marks_when_an_inset_changes(tmp_path):
    import copy

    from optodraw.app._scene_cache import RetainedScene

    folder = _data(tmp_path)
    page = Page(width_mm=183, height_mm=120, letters=False)
    box = page.add(Inset(str(folder / "a.svg"), center=(30, 40), width=40, label="box"))
    big = page.add(Inset(str(folder / "a.svg"), center=(130, 40), width=60, label="big"))
    page.add(Callout("c", center=(80, 90), target=box.at(10, 5)))
    page.add(Note("n", center=box.at(30, 5)))
    page.zoom(box, (10, 5, 20, 15), big)
    spec = json.loads(json.dumps(page.to_spec()))
    cache = RetainedScene()
    cache.get(spec)
    moved = copy.deepcopy(spec)
    next(c for c in moved["components"] if c.get("label") == "box")["center"] = [50, 40]
    scene = cache.get(moved)
    inset = next(n for n in scene.walk() if isinstance(n, Inset) and n.label == "box")
    call = next(n for n in scene.walk() if isinstance(n, Callout))
    note = next(n for n in scene.walk() if isinstance(n, Note) and n.text == "n")
    zoom = next(n for n in scene.walk() if n.component_type == "ZoomLink")
    assert call.target.inset is inset and tuple(call.target) == pytest.approx(inset.at(10, 5).xy())
    assert (note.world_position.x, note.world_position.y) == pytest.approx(inset.at(30, 5).xy())
    assert zoom.small is inset
    assert scene.svg() == Scene.from_spec(copy.deepcopy(moved)).svg()


def test_the_editor_cache_relinks_a_zoom_when_an_inset_changes(tmp_path):
    import copy

    from optodraw.app._scene_cache import RetainedScene

    folder = _data(tmp_path)
    page = Page(width_mm=183, height_mm=120, letters=False)
    box = page.add(Inset(str(folder / "a.svg"), center=(30, 40), width=40, label="box"))
    big = page.add(Inset(str(folder / "a.svg"), center=(130, 40), width=60, label="big"))
    page.zoom(box, (10, 5, 20, 15), big)
    spec = json.loads(json.dumps(page.to_spec()))
    cache = RetainedScene()
    cache.get(spec)
    moved = copy.deepcopy(spec)
    next(c for c in moved["components"] if c.get("label") == "big")["center"] = [120, 30]
    scene = cache.get(moved)
    zoom = next(n for n in scene.walk() if n.component_type == "ZoomLink")
    assert zoom.big is next(n for n in scene.walk() if isinstance(n, Inset) and n.label == "big")
    assert scene.svg() == Scene.from_spec(copy.deepcopy(moved)).svg()


def test_a_scene_that_reads_a_file_of_its_own_is_frozen(tmp_path):
    gdstk = pytest.importorskip("gdstk")
    from optodraw import GDSModel
    from optodraw.figure.sources import SceneView

    library = gdstk.Library()
    library.new_cell("TOP").add(gdstk.rectangle((0, 0), (30, 10), layer=1))
    (tmp_path / "data").mkdir()
    library.write_gds(str(tmp_path / "data" / "chip.gds"))
    scene = Scene(width=100, height=60, platform="on_chip")
    scene.add(GDSModel(str(tmp_path / "data" / "chip.gds"), cell_name="TOP"))
    page = Page(width_mm=120, height_mm=80, letters=False)
    page.add(Inset(SceneView(scene), center=(60, 40), width=80, label="chip"))
    with pytest.warns(UserWarning, match=r"'chip'.*a file of its own.*rebuild"):
        path = _saved(page, tmp_path)
    stored = next(c for c in json.loads(path.read_text())["components"] if c["type"] == "Inset")
    assert stored["source"] == {"kind": "SceneView"} and stored["fragment"]["frozen"] is True


def _rib_only():
    from optodraw.gds.layout import GDSLayerRecord, GDSLayout
    from optodraw.gds.xsection.model import cross_section

    def record(spec, rect):
        x0, y0, x1, y1 = rect
        return GDSLayerRecord(spec=spec, name=f"L{spec[0]}", description="", color="#000000", opacity=1.0,
                              thickness=0.22, zmin=0.0, material_preset="silicon",
                              polygons=[[(x0, y0), (x1, y0), (x1, y1), (x0, y1)]], matched_pdk=False)

    layout = GDSLayout(source_path=Path("t.gds"), cell_name="T", bounds=(-50, -50, 50, 50),
                       layer_records=[record((1, 0), (-20, -0.25, 20, 0.25)), record((3, 0), (-20, -3, 20, 3))])
    return cross_section(layout, STACK, ((0, -5), (0, 5)))


def test_a_section_map_follows_a_cut_out_top_oxide():
    from optodraw.figure.sources import SectionView
    from optodraw.gds.xsection.schematic import section_place

    xs = _rib_only()
    fragment = SectionView(xs, z_scale=1).fragment(80.0, font_pt=7.0)
    assert fragment.map["form"] == "section" and fragment.map["keep"] is not None     # the top oxide is cut out
    place = section_place(xs, width_mm=80.0, font_pt=7.0, z_scale=1)
    top = max(g.bounds[3] for g in xs.regions.values() if not g.is_empty)
    for s, z in ((4.0, 0.1), (5.0, top - 0.05), (6.0, fragment.map["keep"] - 0.01), (6.0, fragment.map["resume"])):
        assert fragment.place(s, z) == pytest.approx(place(s, z), abs=1e-12)


class _Own:
    """A source written by a user: optodraw has no record for it."""

    def fragment(self, width_mm, *, font_pt):
        from optodraw.figure.fragment import Fragment

        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width_mm}mm" height="10mm" '
               f'viewBox="0 0 {width_mm} 10"><circle cx="5" cy="5" r="4"/></svg>')
        return Fragment(svg=svg, size_mm=(width_mm, 10.0), place=lambda x, y: (x, y))


def test_a_source_with_no_record_saves_its_fragment_frozen(tmp_path):
    page = Page(width_mm=100, height_mm=60, letters=False)
    page.add(Inset(_Own(), center=(50, 30), width=40))
    before = page.svg()
    path = _saved(page, tmp_path)
    spec = json.loads(path.read_text())
    inset = next(c for c in spec["components"] if c["type"] == "Inset")
    assert inset["source"] == {"kind": "Fragment"} and inset["fragment"]["frozen"] is True
    loaded = Page.load(path)
    assert loaded.svg() == before
    with pytest.raises(ValueError, match="no map"):
        next(n for n in loaded.walk() if isinstance(n, Inset)).at(1, 1).xy()


def _pdf(tmp_path):
    from matplotlib.figure import Figure

    fig = Figure(figsize=(2.0, 1.0))
    fig.subplots().plot([0, 1, 2], [0, 1, 0])
    path = tmp_path / "data" / "p.pdf"
    path.parent.mkdir(exist_ok=True)
    fig.savefig(path, format="pdf")
    return str(path)


def _top_view():
    from optodraw.gds.layout import GDSLayerRecord, GDSLayout
    from optodraw.gds.xsection.top import top_view

    rect = [(-6, -0.25), (-0.5, -0.25), (-0.5, 0.25), (-6, 0.25)]
    layout = GDSLayout(source_path=Path("t.gds"), cell_name="T", bounds=(-20, -20, 20, 20), layer_records=[
        GDSLayerRecord(spec=(1, 0), name="L1", description="", color="#000000", opacity=1.0, thickness=0.22,
                       zmin=0.0, material_preset="silicon", polygons=[rect], matched_pdk=False)])
    return top_view(layout, STACK, (-10.0, -10.0, 10.0, 10.0))


def _sources():
    """Each source kind: how to make it, a point to place, and whether its record is frozen."""

    from optodraw.figure.sources import (Equation, GdsView, Image, PdfFile, Plot, SceneView, SectionView, SemView,
                                         Text)

    pdf = pytest.mark.skipif(shutil.which("pdftocairo") is None, reason="pdftocairo is not on PATH")
    return [
        pytest.param(lambda tmp: (None, {"height": 30}), (5, 5), {}, False, id="empty"),
        pytest.param(lambda tmp: (str(_data(tmp) / "a.svg"), {}), (10, 5), {}, False, id="svg"),
        pytest.param(lambda tmp: (PdfFile(_pdf(tmp), page=1), {}), (20, 10), {}, False, id="pdf", marks=pdf),
        pytest.param(lambda tmp: (SceneView(_bench()), {}), (10, 5), {}, False, id="scene-2d"),
        pytest.param(lambda tmp: (SceneView(_bench(), view="1d"), {}), (5, 5), {}, False, id="scene-1d"),
        pytest.param(lambda tmp: (SectionView(_section()), {}), (0.0, 0.1), {}, True, id="section"),
        pytest.param(lambda tmp: (SectionView(_rib_only()), {}), (0.0, 0.1), {}, True, id="section-cut-out"),
        pytest.param(lambda tmp: (Plot(_plot(), kind="measured"), {"height": 30}), (150, 7), {"axes": 1}, True,
                     id="plot"),
        pytest.param(lambda tmp: (Image(_data(tmp) / "p.png", scale_um_per_px=0.5), {}), (100, 50), {}, False,
                     id="png"),
        pytest.param(lambda tmp: (np.eye(20, dtype=np.uint8) * 200, {}), (10, 10), {}, True, id="array"),
        pytest.param(lambda tmp: (SemView(_top_view(), width_px=300, rotation=30.0), {}), (-3.0, 0.0), {}, True,
                     id="sem-top"),
        pytest.param(lambda tmp: (SemView(_top_view(), width_px=300, tilt=30.0), {}), (0.0, 0.0), {}, True,
                     id="sem-tilted"),
        pytest.param(lambda tmp: (SemView(_section(), width_px=300), {}), (0.0, 0.1), {}, True, id="sem-section"),
        pytest.param(lambda tmp: (Text("two words", size_pt=6.0, align="center"), {}), (1, 1), {}, False, id="text"),
        pytest.param(lambda tmp: (Equation("E = mc^2"), {}), (1, 1), {}, False, id="equation"),
        pytest.param(lambda tmp: (_timing(), {}), (2.0, 1), {}, False, id="timing"),
        pytest.param(lambda tmp: (GdsView(_gds(tmp), STACK, region=(-5, -5, 5, 5)), {}), (1.0, 2.0), {}, False,
                     id="gds"),
        pytest.param(lambda tmp: (Inset(GdsView(_gds(tmp), STACK, region=(-5, -5, 5, 5))).cut((0, -4), (0, 4)).source,
                                  {}), (1.0, 0.1), {}, False, id="section-from-cut"),
    ]


def _gds(tmp_path):
    """A strip guide on its slab, in the page's data folder."""

    import gdstk

    path = _data(tmp_path) / "wg.gds"
    lib = gdstk.Library()
    lib.new_cell("TOP").add(gdstk.rectangle((-10, -0.25), (10, 0.25), layer=1),
                            gdstk.rectangle((-10, -3), (10, 3), layer=3))
    lib.write_gds(path)
    return path


def _timing():
    from optodraw.figure.timing import Bits, Clock, TimeMark, Timing

    return Timing([Clock("Clock", period=1.0), Bits("DAC", [0, 1, 1, 0], bit_time=1.0)], span=(0.0, 4.0), unit="ns",
                  marks=[TimeMark(1.5, label="sample")])


def _place(fragment, point, options):
    try:
        return fragment.place(*point, **options)
    except ValueError as exc:
        return str(exc)


@pytest.mark.parametrize("make, point, options, frozen", _sources())
def test_each_source_kind_saves_and_loads(tmp_path, make, point, options, frozen):
    item, extra = make(tmp_path)
    page = Page(width_mm=120, height_mm=100, letters=False)
    inset = page.add(Inset(item, center=(60, 50), width=50, **extra))
    before = page.svg()
    fragment = inset.fragment()
    path = _saved(page, tmp_path)
    stored = next(c for c in json.loads(path.read_text())["components"] if c["type"] == "Inset")
    assert stored["fragment"]["frozen"] is frozen
    loaded = Page.load(path)
    assert loaded.svg() == before
    again = next(n for n in loaded.walk() if isinstance(n, Inset))
    got = again.fragment()
    assert (got.svg, got.size_mm, got.kind, got.notes, got.floor_mm, got.map) == (
        fragment.svg, fragment.size_mm, fragment.kind, fragment.notes, fragment.floor_mm, fragment.map)
    assert _place(got, point, options) == _place(fragment, point, options)
    if frozen:
        with pytest.raises(ValueError, match="frozen"):
            again.rebuild()
    else:
        again.rebuild()
        assert again.fragment().svg == fragment.svg and loaded.svg() == before


def _two_insets(tmp_path):
    """A small empty inset and a big one: an SVG file with 5000 characters of text."""

    big = tmp_path / "big.svg"
    big.write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 20"><text x="2" y="10" font-size="4">'
                   + "x" * 5000 + "</text></svg>", encoding="utf-8")
    page = Page(width_mm=100, height_mm=60)
    page.add(Inset(None, center=(20, 20), width=20, label="small"))
    page.add(Inset(str(big), center=(60, 20), width=40, label="big"))
    return page


def test_a_saved_page_over_the_limit_warns_and_still_writes(tmp_path, monkeypatch):
    monkeypatch.setattr("optodraw.figure.sources.PICTURE_LIMIT", 2000)
    path = tmp_path / "heavy.json"
    with pytest.warns(UserWarning, match=r"heavy\.json.*MB.*big") as seen:
        _two_insets(tmp_path).save(path)
    message = str(seen[0].message)
    assert path.exists() and message.index("big") < message.index("small")        # the largest inset comes first
    assert Page.load(path)


def test_a_saved_page_under_the_limit_does_not_warn(tmp_path):
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        _two_insets(tmp_path).save(tmp_path / "light.json")



def test_a_mark_before_its_inset_loads(tmp_path):
    folder = _data(tmp_path)
    page = Page(width_mm=120, height_mm=80, letters=False)
    a = page.add(Inset(str(folder / "a.svg"), center=(40, 40), width=40, label="file"))
    page.add(Callout("c", center=(90, 60), target=a.at(10, 5)))
    spec = json.loads(json.dumps(page.to_spec()))
    spec["components"].reverse()                                                # the callout comes first
    loaded = Scene.from_spec(spec)
    call, inset = _callout(loaded, "c"), _inset(loaded, "file")
    assert call.target.inset is inset and tuple(call.target) == pytest.approx(inset.at(10, 5).xy())
    assert [n.component_type for n in loaded.root.children] == ["Callout", "Inset"]      # in the spec's order


def _plot_spec(tmp_path):
    page = _page(tmp_path)
    page.add(Callout("third", center=(170, 40), target=_inset(page, "plot").at(150, 7, axes=1)))
    spec = json.loads(json.dumps(page.to_spec()))
    third = next(c for c in spec["components"] if c.get("text") == "third")
    return spec, third


@pytest.mark.parametrize("axes", [2, -1])
def test_an_axes_the_plot_does_not_have_is_a_finding(tmp_path, axes):
    from optodraw.check import _inset_faults

    spec, third = _plot_spec(tmp_path)
    third["target"]["options"]["axes"] = axes
    loaded = Scene.from_spec(spec)
    with pytest.raises(ValueError, match=f"no axes {axes}"):                   # not an IndexError, not axes 1
        _inset(loaded, "plot").fragment().place(150, 7, axes=axes)
    assert any('"third"' in f and "outside the inset" in f for f in _inset_faults(list(loaded.walk())))


@pytest.mark.parametrize("value", [float("nan"), float("inf")])
def test_a_stored_map_takes_finite_numbers_only(tmp_path, value):
    page = _page(tmp_path)
    spec = json.loads(json.dumps(page.to_spec()))
    stored = next(c for c in spec["components"] if c.get("label") == "file")["fragment"]
    stored["map"]["m"][0] = value
    with pytest.raises(ValueError, match="numbers"):
        Scene.from_spec(spec)


def test_the_warning_of_a_heavy_page_names_insets_in_groups(tmp_path, monkeypatch):
    from optodraw import Group

    monkeypatch.setattr("optodraw.figure.sources.PICTURE_LIMIT", 2000)
    page = _two_insets(tmp_path)
    group = Group(label="pair")
    for inset in [n for n in page.root.children if isinstance(n, Inset)]:
        page.root.children.remove(inset)
        group.add(inset)
    page.add(group)
    with pytest.warns(UserWarning) as seen:
        page.save(tmp_path / "grouped.json")
    message = str(seen[0].message)
    assert "big" in message and ": ." not in message
