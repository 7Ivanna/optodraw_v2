"""GdsView draws a GDS crop as vector, and Inset.cut makes a section from the same file and stack, with marks A and A'
that stay on the cut ends whatever moves."""

from __future__ import annotations

import json
import math
import re
import shutil
import xml.etree.ElementTree as ET

import pytest

from optodraw import CutLink, GdsView, Inset, check_export
from optodraw.figure.fragment import PT_MM
from optodraw.figure.page import Page
from optodraw.figure.sources import from_record, record_of
from optodraw.gds.palette import material_fill

gdstk = pytest.importorskip("gdstk")
pytest.importorskip("shapely")

# The ridge and slab layers of lnoi400 (LN_RIDGE 2/0 on LN_SLAB 3/0, lnoi400/tech.py), written here so the test does
# not wait for the bundled stack.
LN_STACK = """name: lnoi400 ridge and slab (test copy)
units: um
layers:
  "2/0": {name: LN_RIDGE, role: core, zmin: 0.2, thickness: 0.2, material: lithium_niobate}
  "3/0": {name: LN_SLAB, role: slab, zmin: 0.0, thickness: 0.2, material: lithium_niobate}
"""
SHADED_LN = "#b699c3"           # the LN fill, 20 % toward the section ink: one level over the slab


def _gds(path, *shapes):
    lib = gdstk.Library()
    lib.new_cell("TOP").add(*shapes)
    lib.write_gds(path)
    return path


def _paths(svg):
    return {layer: (d, fill) for layer, d, fill in
            re.findall(r'<path data-layer="([^"]+)" d="([^"]+)" fill="([^"]+)"', svg)}


def test_gds_view_clips_unions_and_draws_one_path_per_layer(tmp_path):
    stack = tmp_path / "ln.yaml"
    stack.write_text(LN_STACK, encoding="utf-8")
    gds = _gds(tmp_path / "t.gds", gdstk.rectangle((2, 2), (6, 6), layer=2), gdstk.rectangle((4, 4), (8, 8), layer=2),
               gdstk.rectangle((-5, 3), (5, 7), layer=3), gdstk.rectangle((20, 20), (30, 30), layer=2))
    view = GdsView(gds, stack, region=(0, 0, 10, 10))
    fragment = view.fragment(50, font_pt=7)
    svg = fragment.svg
    assert re.findall(r'data-layer="([^"]+)"', svg) == ["3/0", "2/0"]       # mutant: no union gives two 2/0 paths
    paths = _paths(svg)
    assert paths["2/0"][0].count("M") == 1                                  # the two rectangles are one ring
    numbers = [float(v) for v in re.findall(r"-?\d+\.?\d*", paths["3/0"][0])]
    assert numbers and all(0.0 <= v <= 50.0 for v in numbers)              # mutant: no clip runs past 50 mm
    assert paths["3/0"][1] == material_fill("lithium_niobate")
    assert paths["2/0"][1] == SHADED_LN                                     # mutant: no shade gives both one fill
    assert fragment.place(0, 10) == pytest.approx((0, 0))
    assert fragment.place(10, 0) == pytest.approx((50, 50))
    one = GdsView(gds, stack, region=(0, 0, 10, 10), layers=[(3, 0)]).fragment(50, font_pt=7).svg
    assert re.findall(r'data-layer="([^"]+)"', one) == ["3/0"]
    record, frozen = record_of(view, fragment, 50.0, 7.0)
    assert not frozen and record == view.to_record()
    again = from_record(json.loads(json.dumps(record)), tmp_path)
    assert again.fragment(50, font_pt=7).svg == svg


def test_gds_view_refuses_too_many_polygons(tmp_path):
    stack = tmp_path / "ln.yaml"
    stack.write_text(LN_STACK, encoding="utf-8")
    five = _gds(tmp_path / "five.gds", *[gdstk.rectangle((i, 1), (i + 0.5, 2), layer=2) for i in range(5)])
    with pytest.raises(ValueError) as raised:                               # mutant: the check removed
        GdsView(five, stack, region=(0, 0, 10, 10), limit=3).fragment(50, font_pt=7)
    message = str(raised.value)
    assert all(part in message for part in ("5 polygons", "limit 3", "region=", "layers="))
    far = _gds(tmp_path / "far.gds", *[gdstk.rectangle((100 + i, 1), (100.5 + i, 2), layer=2) for i in range(100)],
               gdstk.rectangle((1, 1), (2, 2), layer=2), gdstk.rectangle((4, 1), (5, 2), layer=3))
    view = GdsView(far, stack, region=(0, 0, 10, 10), limit=3)            # mutant: counting before the region filter
    assert len(_paths(view.fragment(50, font_pt=7).svg)) == 2


def test_gds_view_merges_one_layer_across_cells(tmp_path):
    stack = tmp_path / "ln.yaml"
    stack.write_text(LN_STACK, encoding="utf-8")
    lib = gdstk.Library()
    piece = lib.new_cell("PIECE")
    piece.add(gdstk.rectangle((0.2, 0), (1, 1), layer=2))
    # the placed piece starts at 0.1 + 0.2 = 0.30000000000000004 in float, the top cell's rectangle ends at 0.3
    lib.new_cell("TOP").add(gdstk.rectangle((-1, 0), (0.3, 1), layer=2), gdstk.Reference(piece, (0.1, 0)))
    lib.write_gds(tmp_path / "cells.gds")
    svg = GdsView(tmp_path / "cells.gds", stack, region=(-2, -1, 2, 2)).fragment(40, font_pt=7).svg
    assert _paths(svg)["2/0"][0].count("M") == 1                           # mutant: no grid_size: two rings, a seam


def test_a_gds_view_page_passes_the_line_weight_gate(tmp_path):
    gds = _gds(tmp_path / "wg.gds", gdstk.rectangle((-10, -0.25), (10, 0.25), layer=1))
    page = Page(width_mm=89, height_mm=60.004, letters=False)              # 60.00 at 2 decimals: it printed 0.99993x
    page.add(Inset(GdsView(gds, "gdsfactory_generic", region=(-10, -10, 10, 10)), center=(30, 30), width=50))
    path = page.export(tmp_path / "gds", formats=("svg",))["svg"]
    assert not [f for f in check_export(path) if "thinner than" in f]       # mutant: LINE_MM 0.0882 and height .2f
    root = ET.parse(path).getroot()
    assert float(root.get("height").removesuffix("mm")) == float(root.get("viewBox").split()[3])   # mutant: .2f
    outline = float(re.search(r'<path data-layer="[^"]+"[^>]*stroke-width="([\d.]+)"', path.read_text()).group(1))
    assert outline / PT_MM > 1.01 * 0.25                                    # mutant: LINE_MM 0.0882, no margin


A, B = (0.0, -8.0), (0.0, 8.0)          # longer than the section's own window around the slab: the window matters


def _cut_page(tmp_path):
    folder = tmp_path / "data"
    folder.mkdir()
    gds = _gds(folder / "wg.gds", gdstk.rectangle((-10, -0.25), (10, 0.25), layer=1),
               gdstk.rectangle((-10, -3), (10, 3), layer=3))
    page = Page(width_mm=150, height_mm=90, font_pt=7)
    b = page.add(Inset(GdsView(gds, "gdsfactory_generic", region=(-10, -10, 10, 10)), center=(35, 45), width=50,
                       label="gds"))
    c = page.add(b.cut(A, B, center=(110, 45), width=60, label="section"))
    return page, b, c


def _marks(scene):
    """The GDS inset, the section inset, the cut line's two ends and the four letters, in the world."""

    b, c = (next(n for n in scene.walk() if isinstance(n, Inset) and n.label == name) for name in ("gds", "section"))
    link = next(n for n in scene.walk() if isinstance(n, CutLink))
    drawing = link.annotation_2d()["children"]
    px, py = float(link.world_position.x), float(link.world_position.y)
    line = drawing[0]
    ends = [(line["x1"] + px, line["y1"] + py), (line["x2"] + px, line["y2"] + py)]
    letters = [(item["text"], item["x"] + px, item["y"] + py) for item in drawing[1:]]
    return b, c, ends, letters


def _follow(scene):
    """The line ends lie on A and B of the GDS inset, and the section letters stand over its top corners: at the
    corner, or less than a letter height right of it when a panel letter stands there."""

    b, c, ends, letters = _marks(scene)
    assert ends[0] == pytest.approx(b.at(*A).xy()) and ends[1] == pytest.approx(b.at(*B).xy())
    top = c.fragment().map["z1"]
    size = 7 * PT_MM
    assert [text for text, _, _ in letters] == ["A", "A′", "A", "A′"]
    for (_, x, y), s in zip(letters[2:], (0.0, math.dist(A, B))):
        cx, cy = c.at(s, top).xy()
        assert cx - 1e-9 <= x < cx + size and 0.0 < y - cy < 2.0 * size


def test_cut_marks_follow_both_insets(tmp_path):
    page, b, c = _cut_page(tmp_path)
    assert c.source.xs.source["cut"] == (A, B)
    assert c.source.xs.window == (0.0, math.dist(A, B))                    # mutant: cut using the auto window
    assert sum(isinstance(n, CutLink) for n in page.walk()) == 1            # mutant: Page.add not adding links
    _follow(page)
    b.move_to(40, 40)                                                       # mutant: CutLink caching its places
    _follow(page)
    c.move_to(105, 35)
    c.width = 55
    _follow(page)

    from optodraw.app.session import EditorSession

    path = tmp_path / "pages" / "page.json"
    path.parent.mkdir()
    page.save(path)
    session = EditorSession(json.loads(path.read_text(encoding="utf-8")))
    entry = next(e for e in session.spec["components"] if e.get("label") == "section")
    session.move_component(entry["id"], center=[100, 30])
    _follow(session.scene())

    before = page.export(tmp_path / "before", formats=("svg",))["svg"].read_bytes()
    shutil.rmtree(tmp_path / "data")
    loaded = Page.load(path)
    assert loaded.export(tmp_path / "after", formats=("svg",))["svg"].read_bytes() == before
    _follow(loaded)
    next(n for n in loaded.walk() if isinstance(n, Inset) and n.label == "gds").move_to(30, 50)
    _follow(loaded)


def test_cut_letters_keep_clear_of_the_panel_letters(tmp_path):
    gds = _gds(tmp_path / "wg.gds", gdstk.rectangle((-10, -0.25), (10, 0.25), layer=1),
               gdstk.rectangle((-10, -3), (10, 3), layer=3))
    a = Inset(GdsView(gds, "gdsfactory_generic", region=(-10, -10, 10, 10)), label="gds")
    page = Page(width_mm=183, font_pt=7)
    page.row([a, a.cut(A, B, label="section"), Inset(None)])                # ln_ring's row: A stood on the letter b
    path = page.export(tmp_path / "row", formats=("svg",))["svg"]
    assert not [f for f in check_export(path) if "on a panel letter" in f]  # mutant: CutLink ignoring keep_clear
    _follow(page)


def test_cut_passes_z_scale_to_the_section(tmp_path):
    gds = _gds(tmp_path / "wg.gds", gdstk.rectangle((-10, -0.25), (10, 0.25), layer=1),
               gdstk.rectangle((-10, -3), (10, 3), layer=3))
    a = Inset(GdsView(gds, "gdsfactory_generic", region=(-10, -10, 10, 10)), width=50)
    c = a.cut(A, B, z_scale=7, width=60)                                    # 7: no stretch that "auto" picks
    shape = c.fragment().map
    assert shape["zscale"] == pytest.approx(7 * shape["scale"])            # mutant: cut dropping z_scale
    record, frozen = record_of(c.source, c.fragment(), 60.0, 8.0)
    assert not frozen and record["z_scale"] == 7.0                         # mutant: z_scale freezing the record
    again = from_record(json.loads(json.dumps(record)), tmp_path).fragment(60.0, font_pt=8.0)
    assert again.map["zscale"] == pytest.approx(shape["zscale"])           # mutant: the record load dropping z_scale
    with pytest.raises(ValueError, match="z_scale"):
        a.cut(A, B, z_scale=0)
