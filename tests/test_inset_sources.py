"""Scene and section sources for insets: a point of the source lands on the same point of the page."""

import re
import shutil
import xml.etree.ElementTree as ET

import pytest

from optodraw import Inset, Laser, Lens, Scene
from optodraw.check import _read_page
from optodraw.figure.page import Page
from optodraw.figure.fragment import PT_MM
from optodraw.figure.sources import Equation, PdfFile, SceneView, SectionView, Text, to_source
from optodraw.gds import cross_section, stack_section
from optodraw.gds.xsection.schematic import section_place

STACK = "gdsfactory_generic"
CORE = (1, 0)


def _bench():
    scene = Scene(width=100, height=60)
    scene.add(Laser(center=(10, 5)))
    scene.add(Lens(center=(30, -5)))
    return scene


def _alone(part):
    scene = Scene(width=100, height=60)
    scene.add(part)
    return scene.content_bounds()


def test_scene_view_takes_the_1d_view():
    two, one = (SceneView(_bench(), view=view).fragment(60.0, font_pt=7.0) for view in ("2d", "1d"))
    assert one.svg != two.svg and 'aria-label="1D schematic"' in one.svg
    assert "data-art" in two.svg and "data-art" not in one.svg      # the 2D art is not in the symbol view
    assert one.size_mm[0] == 60.0
    with pytest.raises(ValueError, match="view"):
        SceneView(_bench(), view="3d")


def _section_xs(tmp_path):
    import gdsfactory as gf

    gf.gpdk.PDK.activate()
    path = tmp_path / "pn.gds"
    gf.components.straight_pn(length=40).write_gds(path)
    return cross_section(path, STACK, ((10, -3), (10, 3)))


def test_section_place_follows_the_width_and_the_text_size(tmp_path):
    xs = _section_xs(tmp_path)
    fragment = SectionView(xs, z_scale=1).fragment(80.0, font_pt=6.0)
    place = section_place(xs, width_mm=80.0, font_pt=6.0, z_scale=1)
    assert place(1.5, 0.1) == pytest.approx(fragment.place(1.5, 0.1))
    assert place(1.5, 0.1) != section_place(xs, width_mm=40.0, font_pt=6.0, z_scale=1)(1.5, 0.1)


def test_options_go_to_the_section_and_the_size_stays_with_the_inset():
    xs = stack_section(STACK, CORE, width=0.5)
    assert "<text" not in SectionView(xs, dims=None, labels=False, scale_bar=False).fragment(60.0, font_pt=7.0).svg
    assert "<text" in SectionView(xs).fragment(60.0, font_pt=7.0).svg
    with pytest.raises(ValueError, match="width_mm"):
        SectionView(xs, width_mm=40.0).fragment(60.0, font_pt=7.0)
    with pytest.raises(ValueError, match="keeps its own shape"):
        to_source(SectionView(xs), height=10.0)


# plots

def _plot(w_in=3.0, h_in=2.0):
    import matplotlib

    matplotlib.use("Agg")
    from matplotlib.figure import Figure

    fig = Figure(figsize=(w_in, h_in))
    ax = fig.subplots()
    ax.plot([1500, 1550, 1600], [-10, -3, -8])
    ax.set_xlabel("wavelength (nm)")
    ax.set_ylabel("T (dB)")
    return fig


def Plot_(fig, **kw):
    from optodraw.figure.sources import Plot

    return Plot(fig, **kw)


def test_a_plot_page_has_one_font(tmp_path):
    from optodraw.check import check_export

    page = Page(width_mm=120, height_mm=60, letters=False)
    page.add(Inset(_plot(), center=(60, 30), width=100, height=50))
    path = page.export(tmp_path / "fig", formats=("svg",))["svg"]
    assert not [f for f in check_export(path) if "font famil" in f]
    families = set(re.findall(r"font-family: '?([^',;]+)", path.read_text()))
    assert families == {"Helvetica"}


def test_3d_axes_export_and_place_refuses():
    from matplotlib.figure import Figure

    fig = Figure(figsize=(3, 3))
    fig.add_subplot(projection="3d").plot([0, 1], [0, 1], [0, 1])
    frag = Plot_(fig).fragment(60.0, font_pt=7.0)
    with pytest.raises(ValueError, match="cartesian"):
        frag.place(0.5, 0.5)


# ---- PDF, text and equations

def _pdf(tmp_path, name="p.pdf"):
    from matplotlib.figure import Figure

    fig = Figure(figsize=(2.0, 1.0))
    ax = fig.subplots()
    ax.plot([0, 1, 2], [0, 1, 0])
    ax.set_title("Peak")
    path = tmp_path / name
    fig.savefig(path, format="pdf")
    return path


needs_pdftocairo = pytest.mark.skipif(shutil.which("pdftocairo") is None, reason="pdftocairo is not on PATH")


@needs_pdftocairo
def test_two_insets_of_one_pdf_keep_their_glyphs_apart(tmp_path):
    path = _pdf(tmp_path)
    page = Page(width_mm=150, height_mm=60, letters=False)
    for x in (40, 110):
        page.add(Inset(PdfFile(path), center=(x, 30), width=60))
    svg = page.svg()
    ids = re.findall(r'\sid="([^"]+)"', svg)
    assert len(ids) == len(set(ids)) and any("glyph" in i for i in ids)
    for inset in ET.fromstring(svg).iter("{http://www.w3.org/2000/svg}svg"):
        own = {e.get("id") for e in inset.iter() if e.get("id")}
        links = [e.get("{http://www.w3.org/1999/xlink}href") or e.get("href") for e in inset.iter()
                 if e.tag.endswith("}use")]
        assert all(link[1:] in own for link in links if link)


def test_to_source_routes_a_pdf_and_names_a_missing_file(tmp_path):
    assert isinstance(to_source(str(tmp_path / "x.pdf")), PdfFile)
    with pytest.raises(FileNotFoundError, match="some words"):
        to_source("some words")


def _texts(page_obj):
    return _read_page(ET.fromstring(page_obj.svg()), "page").texts


def test_text_wraps_at_its_width():
    words = "The quick brown fox jumps over the lazy dog and runs on into the field"
    page = Page(width_mm=100, height_mm=60, letters=False, font_pt=8)
    narrow = page.add(Inset(Text(words), center=(30, 30), width=30))
    wide = Page(width_mm=100, height_mm=60, letters=False, font_pt=8).add(Inset(Text(words), center=(30, 30), width=90))
    lines = _texts(page)
    assert len(lines) > 2 and " ".join(t.words for t in lines) == words
    assert all(t.box[2] - t.box[0] <= 30 / PT_MM + 1 for t in lines)               # each line fits the inset width
    assert narrow.fragment().size_mm[1] > wide.fragment().size_mm[1] > 0           # the height follows the lines
    assert all(abs(t.pt - 8) < 0.05 for t in lines)                                # the page font_pt


def test_text_aligns_and_breaks_lines():
    from optodraw.core.markup import text_width

    wide = text_width("ab", 8 * PT_MM)                                       # a text starts at its left end
    for align, x in (("left", 0.0), ("right", 30.0 - wide), ("center", 15.0 - wide / 2)):   # in the 30 mm column
        frag = Text("ab\nab", width=30, align=align).fragment(40.0, font_pt=8)
        xs = [float(x) for x in re.findall(r"<text x=\"([\d.]+)\"", frag.svg)]
        assert xs == pytest.approx([x, x], abs=1e-3)
    with pytest.raises(ValueError, match="align"):
        Text("a", align="top")


def test_an_equation_leaves_the_callers_rcparams_and_figures():
    import matplotlib as mpl
    import matplotlib.pyplot as plt

    before, figures = dict(mpl.rcParams), plt.get_fignums()
    Equation(r"\alpha + \beta").fragment(40.0, font_pt=8)
    assert dict(mpl.rcParams) == before and plt.get_fignums() == figures


def test_tex_names_its_tool(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))
    with pytest.raises(RuntimeError, match="dvisvgm"):
        Equation(r"x^2", tex=True).fragment(40.0, font_pt=8)


def test_an_object_with_svg_that_is_not_a_section_is_refused():
    class Drawing:
        def svg(self, **options):
            return '<svg viewBox="0 0 10 10"/>'

    with pytest.raises(TypeError, match="Drawing"):
        to_source(Drawing())


