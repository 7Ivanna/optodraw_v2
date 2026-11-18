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


def test_a_letter_can_be_set_or_left_out(tmp_path):
    page = Page(width_mm=120, height_mm=80)
    path = _file(tmp_path)
    page.add(Inset(path, center=(30, 60), width=40, letter="A"))
    page.add(Inset(path, center=(90, 60), width=40, letter=""))
    page.add(Inset(path, center=(30, 20), width=40, over=page))
    words = [t.words for t in _read(page.export(tmp_path / "fig", formats=("svg",))).texts if t.bold]
    assert words == ["A"]


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


# ---- each export asks a live source again: a scene or a plot may have changed since the last one ----

def _bench():
    from optodraw import Laser

    scene = Scene(width=100, height=60)
    scene.add(Laser(center=(10, 0)))
    return scene


def _plot(title):
    from matplotlib.figure import Figure

    fig = Figure(figsize=(2.0, 1.5))
    ax = fig.subplots()
    ax.plot([0, 1, 2], [0, 1, 4])
    ax.set_title(title)
    return fig, ax


# ---- a scene frames its insets at the print scale they print at ----


# ---- a page with no height holds the text of its marks ----


# ---- letters read a row left to right, rows top to bottom ----


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
