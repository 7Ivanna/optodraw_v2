"""Page is a Scene in mm: it prints at its exact size, letters its insets and lays them in rows."""

import subprocess
import sys
import xml.etree.ElementTree as ET

import pytest

from optodraw import Callout, Inset, Scene
from optodraw.check import _read_page
from optodraw.figure.fragment import Fragment
from optodraw.figure.page import Page
from optodraw.publication import export_figure

SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 20">'
       '<rect width="40" height="20" fill="#cccccc"/></svg>')


def _file(tmp_path, name="a.svg"):
    path = tmp_path / name
    path.write_text(SVG)
    return str(path)


def _read(paths):
    return _read_page(ET.parse(paths["svg"]).getroot(), "page.svg")


def test_the_page_prints_at_its_exact_size(tmp_path):
    page = Page(width_mm=120, height_mm=60)
    page.add(Inset(_file(tmp_path), center=(60, 30), width=40))
    paths = page.export(tmp_path / "fig", formats=("svg",))
    root = ET.parse(paths["svg"]).getroot()
    assert root.get("width") == "120mm" and root.get("height") == "60.00mm"
    assert root.get("font-family") == "Helvetica, Arial, sans-serif"


def test_a_label_prints_at_the_page_font(tmp_path):
    page = Page(width_mm=120, height_mm=60, font_pt=7.0, letters=False)
    page.add(Callout("power", center=(60, 30)))
    texts = _read(page.export(tmp_path / "fig", formats=("svg",))).texts
    assert [t.words for t in texts] == ["power"] and texts[0].pt == pytest.approx(7.0, abs=0.05)


def test_the_height_follows_the_content_when_not_given(tmp_path):
    page = Page(width_mm=120, letters=False)
    page.add(Inset(_file(tmp_path), center=(60, 30), width=40))      # 40 by 20, top edge at 40
    root = ET.parse(page.export(tmp_path / "fig", formats=("svg",))["svg"]).getroot()
    assert root.get("height") == "40.00mm"


def test_letters_run_in_reading_order(tmp_path):
    page = Page(width_mm=120, height_mm=80)
    path = _file(tmp_path)
    page.add(Inset(path, center=(90, 60), width=40))      # right of the top row
    page.add(Inset(path, center=(30, 20), width=40))      # the bottom row
    page.add(Inset(path, center=(30, 60), width=40))      # left of the top row
    texts = _read(page.export(tmp_path / "fig", formats=("svg",))).texts
    letters = sorted((t for t in texts if t.bold), key=lambda t: (t.box[1], t.box[0]))
    assert [t.words for t in letters] == ["a", "b", "c"]
    assert all(t.pt == pytest.approx(8.0, abs=0.05) for t in letters)
    assert [t.box[0] < 60 for t in letters] == [True, False, True]


def test_a_letter_can_be_set_or_left_out(tmp_path):
    page = Page(width_mm=120, height_mm=80)
    path = _file(tmp_path)
    page.add(Inset(path, center=(30, 60), width=40, letter="A"))
    page.add(Inset(path, center=(90, 60), width=40, letter=""))
    page.add(Inset(path, center=(30, 20), width=40, over=page))
    words = [t.words for t in _read(page.export(tmp_path / "fig", formats=("svg",))).texts if t.bold]
    assert words == ["A"]


def test_an_unlettered_inset_takes_no_letter_slot(tmp_path):
    page = Page(width_mm=120, height_mm=80)
    path = _file(tmp_path)
    page.add(Inset(path, center=(30, 60), width=40))
    page.add(Inset(path, center=(90, 60), width=40, letter=""))
    page.add(Inset(path, center=(30, 20), width=40))
    words = [t.words for t in sorted(_read(page.export(tmp_path / "fig", formats=("svg",))).texts,
                                     key=lambda t: (t.box[1], t.box[0])) if t.bold]
    assert words == ["a", "b"]


def test_an_explicit_letter_wins_over_letters_false(tmp_path):
    page = Page(width_mm=120, height_mm=80, letters=False)
    path = _file(tmp_path)
    page.add(Inset(path, center=(30, 60), width=40, letter="A"))
    page.add(Inset(path, center=(90, 60), width=40))
    words = [t.words for t in _read(page.export(tmp_path / "fig", formats=("svg",))).texts if t.bold]
    assert words == ["A"]


def test_rows_leave_room_for_their_letters(tmp_path):
    page = Page(width_mm=120)
    one = page.row([_file(tmp_path, "a.svg"), _file(tmp_path, "b.svg")], top=100, gap_mm=2.0)
    low = one[0].box()[1]
    two = page.row([_file(tmp_path, "c.svg")], top=low - 2.0, gap_mm=2.0)
    root = ET.parse(page.export(tmp_path / "fig", formats=("svg",))["svg"]).getroot()
    height = float(root.get("height")[:-2])
    sheet = _read_page(root, "page.svg")
    letters = [t for t in sheet.texts if t.bold]
    assert len(letters) == 3
    boxes = [(i.box()[0], height - i.box()[3], i.box()[2], height - i.box()[1]) for i in one + two]
    for t in letters:
        x0, y0, x1, y1 = (v * 25.4 / 72 for v in t.box)
        for bx0, by0, bx1, by1 in boxes:
            assert x1 <= bx0 + 1e-6 or x0 >= bx1 - 1e-6 or y1 <= by0 + 1e-6 or y0 >= by1 - 1e-6
    assert height == pytest.approx(100.0, abs=0.02)      # top is the top of the first band


def test_row_fills_the_width_at_one_height(tmp_path):
    page = Page(width_mm=120, height_mm=60)
    items = page.row([_file(tmp_path, "a.svg"), _file(tmp_path, "b.svg")], top=50, gap_mm=2.0)
    assert [round(i.w_mm, 6) for i in items] == [59.0, 59.0]
    assert [round(i.h_mm, 6) for i in items] == [29.5, 29.5]
    assert all(i in list(page.walk()) for i in items)
    boxes = [i.box() for i in items]
    assert boxes[0][0] == pytest.approx(0.0) and boxes[1][0] == pytest.approx(61.0)
    band = 1.2 * 8.0 * 0.3528                    # the letters take a band above the row
    assert boxes[0][3] == pytest.approx(50.0 - band) and boxes[1][3] == pytest.approx(50.0 - band)


def test_row_with_shares(tmp_path):
    page = Page(width_mm=120, height_mm=60)
    items = page.row([_file(tmp_path, "a.svg"), _file(tmp_path, "b.svg")], top=50, shares=(0.7, None), x=0.0)
    assert [round(i.w_mm, 1) for i in items] == [82.6, 35.4]


def test_a_plain_scene_gets_its_print_scale(tmp_path):
    seen = []

    class Source:
        free_shape = False

        def fragment(self, width_mm, *, font_pt):
            seen.append((width_mm, font_pt))
            svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width_mm:g}mm" height="{width_mm / 2:g}mm" '
                   f'viewBox="0 0 {width_mm:g} {width_mm / 2:g}">'
                   f'<rect width="{width_mm:g}" height="{width_mm / 2:g}"/></svg>')
            return Fragment(svg=svg, size_mm=(width_mm, width_mm / 2), place=lambda x, y: (x, y))

    scene = Scene(width=100, height=60)
    scene.add(Inset(Source(), center=(0, 0), width=40.0))
    scene.add(Callout("power", center=(0, 30)))
    paths = export_figure(scene, tmp_path / "fig", width_mm=80, font_size_pt=7.0, formats=("svg",))
    # the inset is 40 units and the frame holds little more, so 40 units print near 75 mm of the 80 mm
    width_mm, font_pt = seen[-1]
    assert font_pt == 7.0 and 70.0 < width_mm < 80.0
    assert f'data-panel="{width_mm:g}"' in paths["svg"].read_text()
    page = _read(paths)
    assert page.width_pt > 0 and [t.words for t in page.texts] == ["power"]
    assert page.texts[0].pt == pytest.approx(7.0, abs=0.1)


@pytest.mark.parametrize("first", ["optodraw.publication", "optodraw.figure"])
def test_either_package_imports_first(first):
    code = f"import {first}; import optodraw.figure.page, optodraw.publication; print('ok')"
    run = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert run.stdout.strip() == "ok", run.stderr


def _view(path):
    root = ET.parse(path).getroot()
    x, y, w, h = (float(v) for v in root.get("viewBox").split())
    return root, (x, y, w, h)


def test_a_page_with_no_height_reaches_down_to_its_content(tmp_path):
    page = Page(width_mm=120)
    one = page.row([_file(tmp_path, "a.svg"), _file(tmp_path, "b.svg")], top=0, gap_mm=2.0)
    two = page.row([_file(tmp_path, "c.svg")], top=min(i.box()[1] for i in one) - 2.0, gap_mm=2.0)
    root, (vx, vy, vw, vh) = _view(page.export(tmp_path / "fig", formats=("svg",))["svg"])
    assert float(root.get("height")[:-2]) == pytest.approx(vh, abs=0.01) and vy + vh == pytest.approx(
        -min(i.box()[1] for i in two), abs=0.01)
    sheet = _read_page(root, "page.svg")
    for inset in one + two:                       # svg y runs down, the viewBox top is vy
        x0, y0, x1, y1 = inset.box()
        assert vx <= x0 and x1 <= vx + vw and vy <= -y1 and -y0 <= vy + vh + 1e-6
    for letter in (t for t in sheet.texts if t.bold):
        assert letter.box[1] >= -1e-6 and letter.box[3] <= sheet.height_pt + 1e-6


def test_a_page_with_a_height_keeps_its_bytes(tmp_path):
    page = Page(width_mm=120, height_mm=60)
    page.add(Inset(_file(tmp_path), center=(60, 30), width=40))
    root, view = _view(page.export(tmp_path / "fig", formats=("svg",))["svg"])
    assert root.get("viewBox") == "0 -60.0000 120.0000 60.0000" and root.get("height") == "60.00mm"


def test_a_page_with_content_above_zero_keeps_its_bottom_at_zero(tmp_path):
    page = Page(width_mm=120, letters=False)
    page.add(Inset(_file(tmp_path), center=(60, 30), width=40))
    root, (vx, vy, vw, vh) = _view(page.export(tmp_path / "fig", formats=("svg",))["svg"])
    assert vy + vh == pytest.approx(0.0, abs=1e-6) and vh == pytest.approx(40.0, abs=0.01)


def test_a_row_with_no_top_stacks_under_the_last_row(tmp_path):
    page = Page(width_mm=120)
    one = page.row([_file(tmp_path, "a.svg"), _file(tmp_path, "b.svg")], top=0, gap_mm=2.0)
    two = page.row([_file(tmp_path, "c.svg")], gap_mm=2.0)
    band = 1.2 * 8.0 * 0.3528
    low = min(i.box()[1] for i in one)
    assert two[0].box()[3] == pytest.approx(low - 2.0 - band)
    root = ET.parse(page.export(tmp_path / "fig", formats=("svg",))["svg"]).getroot()
    vy, vh = (float(v) for v in root.get("viewBox").split()[1::2])
    sheet = _read_page(root, "page.svg")
    boxes = [(i.box()[0], i.box()[1], i.box()[2], i.box()[3]) for i in one + two]
    for t in (t for t in sheet.texts if t.bold):
        x0, y0, x1, y1 = (v * 25.4 / 72 for v in t.box)
        y0, y1 = -(y1 + vy), -(y0 + vy)                      # to y up
        for bx0, by0, bx1, by1 in boxes:
            assert x1 <= bx0 + 1e-6 or x0 >= bx1 - 1e-6 or y1 <= by0 + 1e-6 or y0 >= by1 - 1e-6


def test_a_row_with_no_top_on_an_empty_page_starts_at_zero(tmp_path):
    path = _file(tmp_path)
    a, b = Page(width_mm=120), Page(width_mm=120)
    assert a.row([path])[0].box() == pytest.approx(b.row([path], top=0.0)[0].box())


def test_an_inset_over_another_does_not_push_the_next_row_down(tmp_path):
    page = Page(width_mm=120, letters=False)
    one = page.row([_file(tmp_path)], top=0, gap_mm=2.0)
    page.add(Inset(_file(tmp_path, "b.svg"), center=(60, -80), width=20, over=one[0]))   # hangs far lower
    two = page.row([_file(tmp_path, "c.svg")], gap_mm=2.0)
    assert two[0].box()[3] == pytest.approx(one[0].box()[1] - 2.0)


# ---- each export asks a live source again: a scene or a plot may have changed since the last one ----

def _bench():
    from optodraw import Laser

    scene = Scene(width=100, height=60)
    scene.add(Laser(center=(10, 0)))
    return scene


def test_each_export_asks_a_live_scene_once(tmp_path, monkeypatch):
    from optodraw import Lens
    from optodraw.figure.sources import SceneView

    calls = []
    real = SceneView.fragment
    monkeypatch.setattr(SceneView, "fragment", lambda self, *a, **k: calls.append(1) or real(self, *a, **k))
    bench = _bench()
    page = Page(width_mm=120, height_mm=80, letters=False)
    page.add(Inset(SceneView(bench), center=(60, 40), width=80))
    page.svg()
    assert len(calls) == 1                                       # once in one export
    bench.add(Lens(center=(40, 0), label="Late"))                # a part added after the first export
    assert "Late" in page.svg() and len(calls) == 2


def _plot(title):
    from matplotlib.figure import Figure

    fig = Figure(figsize=(2.0, 1.5))
    ax = fig.subplots()
    ax.plot([0, 1, 2], [0, 1, 4])
    ax.set_title(title)
    return fig, ax


def test_each_export_asks_a_live_plot_again(tmp_path):
    fig, ax = _plot("first")
    page = Page(width_mm=120, height_mm=80, letters=False)
    page.add(Inset(fig, center=(60, 40), width=80))
    assert "first" in page.svg()
    ax.set_title("second")
    assert "second" in page.svg()


def test_a_scene_export_asks_its_live_insets_again(tmp_path):
    fig, ax = _plot("first")
    scene = _bench()
    scene.add(Inset(fig, center=(60, 0), width=40))
    export_figure(scene, tmp_path / "a", width_mm=89, formats=("svg",))
    ax.set_title("second")
    assert "second" in export_figure(scene, tmp_path / "b", width_mm=89, formats=("svg",))["svg"].read_text()



def test_an_equation_sets_its_formula_again_only_when_it_changes(monkeypatch):
    from optodraw.figure.sources import Equation

    calls = []
    real = Equation._mathtext_svg
    monkeypatch.setattr(Equation, "_mathtext_svg", lambda self, pt: calls.append(self.latex) or real(self, pt))
    formula = Equation("E = mc^2")
    page = Page(width_mm=120, height_mm=80, letters=False)
    page.add(Inset(formula, center=(60, 40), width=30))
    first = page.svg()
    assert page.svg() == first and calls == ["E = mc^2"]          # asked twice, set once: TeX is slow
    formula.latex = "E = h\\nu"
    assert page.svg() != first and calls == ["E = mc^2", "E = h\\nu"]

# ---- a scene frames its insets at the print scale they print at ----

def _items():
    from optodraw.figure.sources import Equation, Text

    return [pytest.param(Equation(r"\frac{a}{b} = \sum_k c_k"), (165, 0), id="equation"),
            pytest.param(Text("one two three four five six seven eight nine ten eleven twelve"), (80, -40),
                         id="text")]


@pytest.mark.parametrize("item, center", _items())
def test_a_scene_frames_a_text_inset_at_89_mm(tmp_path, item, center):
    from optodraw import Lens

    scene = _bench()
    scene.add(Lens(center=(150, 0)))                             # 150 units wide: 89 mm prints them small
    inset = scene.add(Inset(item, center=center, width=24))      # at the edge: it sets the frame
    exports = []
    for name in ("a", "b"):                                      # the second export starts where the first ended
        paths = export_figure(scene, tmp_path / name, width_mm=89, font_size_pt=7.0, formats=("svg",))
        _, (vx, vy, vw, vh) = _view(paths["svg"])
        x0, y0, x1, y1 = inset.box()
        assert vx <= x0 + 1e-6 and x1 <= vx + vw + 1e-6 and vy <= -y1 + 1e-6 and -y0 <= vy + vh + 1e-6
        exports.append(paths["svg"].read_bytes())
    assert exports[0] == exports[1]


# ---- a page with no height holds the text of its marks ----

@pytest.mark.parametrize("side", ["above", "below"])
def test_a_callout_beyond_the_insets_is_on_the_page(tmp_path, side):
    from optodraw.check import check_export, check_figure

    page = Page(width_mm=120, letters=False)
    inset = page.row([_file(tmp_path)], top=0)[0]
    x0, y0, x1, y1 = inset.box()
    y = y1 + 3.0 if side == "above" else y0 - 3.0
    page.add(Callout("the edge", center=(100, y), target=inset.at(30, 10)))
    paths = page.export(tmp_path / "fig", formats=("svg",))
    assert check_figure(page) == [] and check_export(paths["svg"]) == []


# ---- letters read a row left to right, rows top to bottom ----

def _letter_of(page):
    return {round(x, 6): letter for letter, x, _ in page._letters(page._insets())}


def test_a_wide_inset_left_of_a_taller_one_reads_first(tmp_path):
    page = Page(width_mm=183, height_mm=120)
    page.add(Inset(None, center=(50, 50), width=90, height=30))      # wide, left
    page.add(Inset(None, center=(140, 50), width=40, height=50))     # taller, right, on one center line
    assert _letter_of(page) == {5.0: "a", 120.0: "b"}


def test_the_spec_example_reads_left_first(tmp_path):
    page = Page(width_mm=183)
    page.add(Inset(None, center=(59, 60), width=118))
    page.add(Inset(None, center=(152, 90), width=62))
    page.add(Inset(None, center=(152, 22), width=62))                # under the right one: the same row span
    marks = sorted(page._letters(page._insets()), key=lambda m: (m[1], -m[2]))     # left to right, then down
    assert [letter for letter, _, _ in marks] == ["a", "b", "c"]


def test_a_row_holds_every_inset_its_span_reaches(tmp_path):
    page = Page(width_mm=183, height_mm=120)
    page.add(Inset(None, center=(25, 40), width=50, height=20))      # left, low: 30 to 50
    page.add(Inset(None, center=(90, 62.5), width=50, height=65))    # middle, tall: 30 to 95
    page.add(Inset(None, center=(155, 90), width=50, height=20))     # right, high: 80 to 100
    assert _letter_of(page) == {0.0: "a", 65.0: "b", 130.0: "c"}    # one band, read left to right


def test_a_lower_inset_that_reaches_into_the_top_row_stays_in_its_own_row(tmp_path):
    page = Page(width_mm=183, height_mm=120)
    page.add(Inset(None, center=(45, 90), width=80, height=40))      # top left: 70 to 110
    page.add(Inset(None, center=(135, 90), width=80, height=40))     # top right: 70 to 110
    page.add(Inset(None, center=(45, 55), width=80, height=40))      # low left: 35 to 75, 5 mm into the top row
    page.add(Inset(None, center=(135, 50), width=80, height=40))     # low right: 30 to 70
    marks = [(letter, round(x), y > 100) for letter, x, y in page._letters(page._insets())]
    assert marks == [("a", 5, True), ("b", 95, True), ("c", 5, False), ("d", 95, False)]


def test_more_than_26_letters_are_set_by_hand(tmp_path):
    page = Page(width_mm=270)
    for n in range(27):
        page.add(Inset(None, center=(5 + 10 * n, 5), width=8))
    with pytest.raises(ValueError, match="by hand"):
        page.svg()


def test_a_page_of_no_height_is_refused():
    for height in (0, -5.0):
        with pytest.raises(ValueError, match="height_mm"):
            Page(width_mm=120, height_mm=height)
