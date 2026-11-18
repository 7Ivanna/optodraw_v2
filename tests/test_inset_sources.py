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
from optodraw.publication import export_figure

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


def test_scene_view_maps_scene_points():
    page = Page(width_mm=120, height_mm=60, letters=False)
    inset = page.add(Inset(SceneView(_bench()), center=(60, 30), width=60))
    place = inset.fragment().place
    x0, y0, x1, y1 = (float(v) for v in _alone(Laser(center=(10, 5))))
    (ax, ay), (bx, by) = place(x0, y1), place(x1, y0)              # the laser's own box: top left, bottom right
    cx, cy = place(10, 5)
    assert ax < cx < bx and ay < cy < by                            # y up in the scene, down in the fragment
    lx, ly = place(30, -5)
    assert lx > bx and ly > cy                                      # the lens is right of the laser box and lower
    wide, tall = inset.fragment().size_mm
    assert 0 < ax and bx < wide and 0 < ay and by < tall
    assert (wide, tall) == (60.0, pytest.approx(60.0 * (tall / wide)))
    px, py = inset.at(10, 5).xy()                                   # the anchor is the same point on the page
    assert px == pytest.approx(60 + (cx - wide / 2)) and py == pytest.approx(30 + (tall / 2 - cy))


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


def _drawn(svg, region):
    """The corners of the first path of ``region`` in the drawn SVG, in mm on the fragment. A beam moves the figure down
    by a ``translate`` on a group, which the path does not hold."""

    path = re.search(rf'data-region="{region}"[^>]*\sd="([^"]+)"', svg).group(1)
    shift = re.search(r'<g transform="translate\(0 ([\d.]+)\)">', svg)
    down = float(shift.group(1)) if shift else 0.0
    pairs = (pair.split(",") for pair in re.findall(r"-?[\d.]+,-?[\d.]+", path))
    return [(float(x), float(y) + down) for x, y in pairs]


@pytest.mark.parametrize("beam", [False, True])
def test_section_view_maps_cut_points(tmp_path, beam):
    xs = _section_xs(tmp_path)
    if beam:
        xs.beam(wavelength=450)                                     # the beam band moves the drawing down
    page = Page(width_mm=120, height_mm=120, letters=False)
    inset = page.add(Inset(SectionView(xs), center=(60, 60), width=60))
    fragment = inset.fragment()
    device = xs.regions["device"]
    ring = list((device.geoms[0] if hasattr(device, "geoms") else device).exterior.coords)
    placed = [fragment.place(s, z) for s, z in ring]
    drawn = _drawn(fragment.svg, "device")
    assert len(drawn) == len(placed)
    for dx, dy in drawn:                                            # the path starts at another corner: match by point
        assert any(abs(px - dx) < 2e-3 and abs(py - dy) < 2e-3 for px, py in placed), (dx, dy)
    assert fragment.size_mm[0] == 60.0
    px, py = inset.at(1.0, 0.11).xy()                               # on the page: the inset's middle plus the offset
    wide, tall = fragment.size_mm
    mx, my = fragment.place(1.0, 0.11)
    assert (px, py) == pytest.approx((60 + mx - wide / 2, 60 + tall / 2 - my))


def test_section_place_follows_the_width_and_the_text_size(tmp_path):
    xs = _section_xs(tmp_path)
    fragment = SectionView(xs, z_scale=1).fragment(80.0, font_pt=6.0)
    place = section_place(xs, width_mm=80.0, font_pt=6.0, z_scale=1)
    assert place(1.5, 0.1) == pytest.approx(fragment.place(1.5, 0.1))
    assert place(1.5, 0.1) != section_place(xs, width_mm=40.0, font_pt=6.0, z_scale=1)(1.5, 0.1)


def _sizes(svg_text):
    """The printed size of each text, in pt. The dimension values print at 7/8 of the label size by design."""

    return {t.words: t.pt for t in _read_page(ET.fromstring(svg_text), "page.svg").texts}


@pytest.mark.parametrize("font", [7.0, 8.0])
def test_section_text_stays_at_the_page_font(font):
    xs = stack_section(STACK, CORE, width=0.5)
    page = Page(width_mm=183, height_mm=70, font_pt=font, letters=False)
    page.add(Inset(SectionView(xs), center=(91, 35), width=90))
    sizes = _sizes(page.svg())
    for label in ("Si substrate", "BOX", "Si"):
        assert sizes[label] == pytest.approx(font, abs=0.01)
    for value in ("500 nm", "220 nm"):                              # dimension values: 7/8 of the page font (R23)
        assert sizes[value] == pytest.approx(0.875 * font, abs=0.01)


@pytest.mark.parametrize("width", [40.0, 90.0])
def test_1d_labels_print_at_the_page_font(width):
    scene = Scene(width=100, height=60)
    scene.add(Laser(center=(10, 5), label="laser"))
    scene.add(Lens(center=(30, -5), label="lens"))
    page = Page(width_mm=120, height_mm=100, font_pt=7.0, letters=False)
    page.add(Inset(SceneView(scene, view="1d"), center=(60, 50), width=width))
    sizes = _sizes(page.svg())
    assert sizes["laser"] == pytest.approx(7.0, abs=0.01) and sizes["lens"] == pytest.approx(7.0, abs=0.01)


def test_a_section_passes_through_a_plain_scene(tmp_path):
    scene = Scene(width=100, height=60)
    xs = stack_section(STACK, CORE, width=0.5)
    scene.add(Inset(xs, center=(0, 0), width=40))                   # a section is its own source by its .svg
    assert isinstance(to_source(xs), SectionView) and isinstance(to_source(_bench()), SceneView)
    paths = export_figure(scene, tmp_path / "fig", width_mm=120, font_size_pt=7.0, formats=("svg",))
    sizes = _sizes(paths["svg"].read_text())
    assert sizes["Si substrate"] == pytest.approx(7.0, rel=0.01) and max(sizes.values()) == pytest.approx(7.0, rel=0.01)
    assert 'data-region="device"' in paths["svg"].read_text()


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


def _mm_of(fig, ax, x, y, width_mm, height_mm):
    """Where ``ax.transData`` puts (x, y) with the figure at ``width_mm`` by ``height_mm``, mm, y down."""

    fig.set_size_inches(width_mm / 25.4, height_mm / 25.4)
    fig.canvas.draw()
    px, py = ax.transData.transform((x, y))
    return px / fig.dpi * 25.4, height_mm - py / fig.dpi * 25.4


def test_a_plot_prints_at_its_slot(tmp_path):
    from optodraw.figure.sources import Plot

    fig = _plot(5.0, 4.0)                                           # another size than the slot
    page = Page(width_mm=120, height_mm=80, letters=False)
    inset = page.add(Inset(fig, center=(60, 40), width=60, height=40))
    assert isinstance(inset.source, Plot)
    frag = inset.fragment()
    assert frag.size_mm == (60.0, 40.0)
    root = re.search(r"<svg\b[^>]*>", frag.svg).group(0)
    assert 'width="60mm"' in root and 'height="40mm"' in root
    view = [float(v) for v in re.search(r'viewBox="([^"]+)"', root).group(1).split()]
    assert view[2] / view[3] == pytest.approx(60 / 40, rel=1e-3)
    assert 'font-size: 10px' in frag.svg                            # the text is not scaled: 1 view unit is 1 pt
    assert view[2] * 25.4 / 72 == pytest.approx(60.0, abs=0.01)     # the view is in pt at 60 mm
    assert tuple(fig.get_size_inches()) == (5.0, 4.0)               # the caller's figure keeps its size


def test_a_plot_without_height_keeps_its_shape():
    frag = Plot_(_plot(3.0, 2.0)).fragment(60.0, font_pt=7.0)
    assert frag.size_mm == (60.0, pytest.approx(40.0))


def Plot_(fig, **kw):
    from optodraw.figure.sources import Plot

    return Plot(fig, **kw)


def test_plot_text_stays_text():
    import matplotlib

    fig = _plot()
    frag = Plot_(fig).fragment(60.0, font_pt=7.0)
    assert "wavelength (nm)" in re.sub(r"<[^>]+>", "", frag.svg)    # text, not glyph paths
    assert matplotlib.rcParams["svg.fonttype"] == "path"            # the change lived only in the save


def test_plot_keeps_rcparams():
    import matplotlib

    before = dict(matplotlib.rcParams)
    Plot_(_plot()).fragment(60.0, font_pt=7.0)
    assert dict(matplotlib.rcParams) == before


def test_plot_kind():
    assert Plot_(_plot()).fragment(60.0, font_pt=7.0).kind == "drawn"
    assert Plot_(_plot(), kind="measured").fragment(60.0, font_pt=7.0).kind == "measured"


def test_at_lands_on_the_data_point():
    fig = _plot()
    ax = fig.axes[0]
    ax.plot([1550], [-3], "o")
    page = Page(width_mm=120, height_mm=80, letters=False)
    inset = page.add(Inset(fig, center=(60, 40), width=60, height=40))
    frag = inset.fragment()
    want = _mm_of(fig, ax, 1550, -3, 60.0, 40.0)
    assert frag.place(1550, -3) == pytest.approx(want, abs=0.05)
    px, py = inset.at(1550, -3).xy()
    assert (px, py) == pytest.approx((60 - 30 + want[0], 40 + 20 - want[1]), abs=0.05)


def test_at_takes_the_second_axes():
    from matplotlib.figure import Figure

    fig = Figure(figsize=(4, 2), layout="constrained")
    a, b = fig.subplots(1, 2)
    a.plot([0, 1], [0, 1])
    b.plot([100, 200], [5, 9])
    b.set_xscale("log")
    page = Page(width_mm=120, height_mm=80, letters=False)
    inset = page.add(Inset(fig, center=(60, 40), width=80, height=40))
    frag = inset.fragment()
    for axes, ax, point in ((0, a, (0.5, 0.5)), (1, b, (150, 7))):
        want = _mm_of(fig, ax, *point, 80.0, 40.0)
        assert frag.place(*point, axes=axes) == pytest.approx(want, abs=0.05)
    assert frag.place(0.5, 0.5, axes=0) != pytest.approx(frag.place(0.5, 0.5, axes=1))


def test_a_plot_page_has_one_font(tmp_path):
    from optodraw.check import check_export

    page = Page(width_mm=120, height_mm=60, letters=False)
    page.add(Inset(_plot(), center=(60, 30), width=100, height=50))
    path = page.export(tmp_path / "fig", formats=("svg",))["svg"]
    assert not [f for f in check_export(path) if "font famil" in f]
    families = set(re.findall(r"font-family: '?([^',;]+)", path.read_text()))
    assert families == {"Helvetica"}


def test_a_plot_save_is_quiet(recwarn, caplog):
    Plot_(_plot()).fragment(60.0, font_pt=7.0)
    assert not [w for w in recwarn.list if "findfont" in str(w.message)] and "findfont" not in caplog.text


def test_two_plots_on_one_page_do_not_clash():
    page = Page(width_mm=150, height_mm=60, letters=False)
    for x in (35, 110):
        page.add(Inset(_plot(), center=(x, 30), width=60, height=40))
    svg = page.svg()
    ids = re.findall(r'\sid="([^"]+)"', svg)
    assert len(ids) == len(set(ids))
    assert svg.count("<style") >= 2
    css = re.findall(r"<style[^>]*>(.*?)</style>", svg, flags=re.S)
    plot_css = [c for c in css if "stroke-linejoin" in c]
    assert len(plot_css) == 2 and plot_css[0] != plot_css[1]        # each rule set is cut to its own inset
    for c in plot_css:
        assert all(rule.startswith("#") for rule in re.findall(r"(?:^|\})([^{}]+)\{", c))   # every rule is cut to an id


def test_to_source_routes_a_figure():
    from optodraw.figure.sources import Plot

    assert isinstance(to_source(_plot()), Plot)
    assert to_source(_plot(), height=20.0).height == 20.0


def test_a_caller_with_tight_bbox_keeps_the_slot():
    import matplotlib

    fig = _plot()
    ax = fig.axes[0]
    ax.plot([1550], [-3], "o")
    with matplotlib.rc_context({"savefig.bbox": "tight"}):
        frag = Plot_(fig, height=40.0).fragment(60.0, font_pt=7.0)
    view = [float(v) for v in re.search(r'viewBox="([^"]+)"', frag.svg).group(1).split()]
    assert (view[2] * 25.4 / 72, view[3] * 25.4 / 72) == pytest.approx((60.0, 40.0), abs=0.01)
    assert frag.place(1550, -3) == pytest.approx(_mm_of(fig, ax, 1550, -3, 60.0, 40.0), abs=0.05)


def test_polar_axes_export_and_place_refuses():
    from matplotlib.figure import Figure

    fig = Figure(figsize=(3, 3))
    fig.add_subplot(projection="polar").plot([0, 1], [1, 2])
    frag = Plot_(fig).fragment(60.0, font_pt=7.0)
    assert frag.size_mm[0] == 60.0 and "<text" in frag.svg
    with pytest.raises(ValueError, match="cartesian"):
        frag.place(0.5, 1.0)


def test_3d_axes_export_and_place_refuses():
    from matplotlib.figure import Figure

    fig = Figure(figsize=(3, 3))
    fig.add_subplot(projection="3d").plot([0, 1], [0, 1], [0, 1])
    frag = Plot_(fig).fragment(60.0, font_pt=7.0)
    with pytest.raises(ValueError, match="cartesian"):
        frag.place(0.5, 0.5)


def test_plot_keeps_rcparams_when_the_caller_set_fonttype():
    import matplotlib

    with matplotlib.rc_context({"svg.fonttype": "path", "svg.hashsalt": "mine"}):
        Plot_(_plot()).fragment(60.0, font_pt=7.0)
        assert matplotlib.rcParams["svg.fonttype"] == "path" and matplotlib.rcParams["svg.hashsalt"] == "mine"


def test_a_heat_map_stays_a_600_dpi_raster():
    import base64
    import struct

    import numpy as np
    from matplotlib.figure import Figure

    fig = Figure(figsize=(3, 2))
    fig.subplots().imshow(np.random.default_rng(0).random((40, 60)))
    frag = Plot_(fig).fragment(60.0, font_pt=7.0)
    images = re.findall(r"data:image/png;base64,([A-Za-z0-9+/=\s]+)", frag.svg)
    assert len(images) == 1
    png = base64.b64decode(images[0])
    wide, tall = struct.unpack(">II", png[16:24])
    axes_mm = fig.axes[0].get_position().width * 60.0
    assert wide == pytest.approx(axes_mm / 25.4 * 600, abs=4)


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
def test_a_pdf_goes_in_as_vector(tmp_path):
    page = Page(width_mm=100, height_mm=60, letters=False)
    inset = page.add(Inset(str(_pdf(tmp_path)), center=(50, 30), width=60))
    svg = page.svg()
    ET.fromstring(svg)
    assert "<path" in svg and "<image" not in svg
    assert isinstance(inset.source, PdfFile) and inset.fragment().size_mm == pytest.approx((60.0, 30.0))


def test_a_missing_tool_names_itself(tmp_path, monkeypatch):
    path = _pdf(tmp_path)
    monkeypatch.setenv("PATH", str(tmp_path))
    with pytest.raises(RuntimeError, match="pdftocairo"):
        PdfFile(path).fragment(50.0, font_pt=8)


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


def test_text_sets_scripts_and_takes_a_size():
    page = Page(width_mm=100, height_mm=60, letters=False, font_pt=8)
    page.add(Inset(Text("SiO_2 film", size_pt=10), center=(50, 30), width=40))
    (line,) = _texts(page)
    assert line.words == "SiO2 film" and abs(line.pt - 10) < 0.05
    assert line.smallest == pytest.approx(7.2, abs=0.1)                            # the subscript at 0.72 of the text


def test_text_width_is_a_cap_that_never_widens_the_inset():
    words = "alpha beta gamma delta epsilon zeta eta theta " * 4
    capped = Text(words, width=20).fragment(60.0, font_pt=8)
    free = Text(words).fragment(60.0, font_pt=8)
    assert capped.size_mm[0] == free.size_mm[0] == 60.0 and capped.size_mm[1] > free.size_mm[1] > 3.4   # free wraps too
    assert Text(words, width=500).fragment(60.0, font_pt=8).size_mm == free.size_mm


def test_text_aligns_and_breaks_lines():
    from optodraw.core.markup import text_width

    wide = text_width("ab", 8 * PT_MM)                                       # a text starts at its left end
    for align, x in (("left", 0.0), ("right", 30.0 - wide), ("center", 15.0 - wide / 2)):   # in the 30 mm column
        frag = Text("ab\nab", width=30, align=align).fragment(40.0, font_pt=8)
        xs = [float(x) for x in re.findall(r"<text x=\"([\d.]+)\"", frag.svg)]
        assert xs == pytest.approx([x, x], abs=1e-3)
    with pytest.raises(ValueError, match="align"):
        Text("a", align="top")


def test_text_escapes_svg_marks():
    page = Page(width_mm=100, height_mm=60, letters=False)
    page.add(Inset(Text("a < b & c"), center=(50, 30), width=40))
    ET.fromstring(page.svg())
    assert _texts(page)[0].words == "a < b & c"


def test_an_equation_is_vector(tmp_path):
    page = Page(width_mm=100, height_mm=60, letters=False, font_pt=8)
    inset = page.add(Inset(Equation(r"E = mc^2"), center=(50, 30), width=40))
    svg = page.svg()
    ET.fromstring(svg)
    assert "<image" not in svg and "<path" in svg and not _texts(page)
    wide, tall = inset.fragment().size_mm
    assert 0.6 * 8 <= tall / PT_MM <= 2.2 * 8 and wide > tall                        # the box follows font_pt
    bigger = Equation(r"E = mc^2").fragment(40.0, font_pt=16).size_mm
    assert bigger[1] == pytest.approx(2 * tall, rel=0.1)                             # twice the size, within 10%


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


@pytest.mark.skipif(shutil.which("dvisvgm") is None or shutil.which("latex") is None, reason="no TeX")
def test_a_tex_equation_is_vector():
    frag = Equation(r"\int_0^1 x\,dx", tex=True).fragment(40.0, font_pt=8)
    assert "<path" in frag.svg and "<image" not in frag.svg and "<text" not in frag.svg
    mathtext = Equation(r"\int_0^1 x\,dx").fragment(40.0, font_pt=8)
    assert frag.size_mm[1] == pytest.approx(mathtext.size_mm[1], rel=0.6)



def test_a_page_is_a_scene_source():
    from optodraw import get_publication_template

    inner = Page(width_mm=60, height_mm=40, letters=False)
    inner.add(Inset(Text("inside"), center=(30, 20), width=40))
    assert isinstance(to_source(inner), SceneView)                   # a Page is a Scene first
    outer = Page(width_mm=120, height_mm=80, letters=False)
    outer.add(Inset(inner, center=(60, 40), width=60))
    assert "inside" in outer.svg()
    page = Page.from_template(get_publication_template("two_panel_horizontal"), [inner, _bench()], width_mm=120.0)
    assert "inside" in page.svg()


def test_an_object_with_svg_that_is_not_a_section_is_refused():
    class Drawing:
        def svg(self, **options):
            return '<svg viewBox="0 0 10 10"/>'

    with pytest.raises(TypeError, match="Drawing"):
        to_source(Drawing())


def test_a_1d_panel_places_its_own_drawing_units():
    fragment = SceneView(_bench(), view="1d").fragment(60.0, font_pt=7.0)
    x0, y0, wide, tall = (float(v) for v in re.search(r'viewBox="([^"]+)"', fragment.svg).group(1).split())
    assert fragment.place(x0 + wide / 2, y0 + tall) == pytest.approx((30.0, fragment.size_mm[1]))   # y down
