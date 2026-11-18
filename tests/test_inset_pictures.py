"""Picture sources for insets: real photos stay pixels, optodraw's own SEM render says it is a render."""

from __future__ import annotations

import base64
import io
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from optodraw import Inset
from optodraw.check import _read_page
from optodraw.figure.page import Page
from optodraw.figure.sources import Image, SemView, to_source
from optodraw.gds.layout import GDSLayerRecord, GDSLayout
from optodraw.gds.xsection.model import cross_section
from optodraw.gds.xsection.top import top_view

np = pytest.importorskip("numpy")
PIL = pytest.importorskip("PIL")
from PIL import Image as PilImage  # noqa: E402


def _picture(tmp_path, suffix, size=(1000, 500), mode="L"):
    path = tmp_path / f"p{suffix}"
    pixels = (np.arange(size[0] * size[1]) % 251).astype(np.uint8).reshape(size[1], size[0])
    PilImage.fromarray(pixels, mode="L").convert(mode).save(path)
    return path


def _embedded(svg):
    """The (format, PIL image) of every picture embedded in ``svg``."""

    found = re.findall(r'href="data:image/(\w+);base64,([^"]+)"', svg)
    return [(kind, PilImage.open(io.BytesIO(base64.b64decode(data)))) for kind, data in found]


def _page(source, width=40.0, **options):
    page = Page(width_mm=100, height_mm=60, letters=False)
    return page, page.add(Inset(source, center=(50, 30), width=width, **options))


def test_a_png_goes_in_as_a_picture(tmp_path):
    path = _picture(tmp_path, ".png")
    page, inset = _page(str(path))
    svg = page.svg()
    ET.fromstring(svg)
    assert svg.count("<image") == 1 and 'data-inset="measured"' in svg
    assert 'preserveAspectRatio="none"' in svg
    assert inset.fragment().kind == "measured" and inset.fragment().size_mm == (40.0, 20.0)
    (kind, image), = _embedded(svg)
    assert kind == "png" and image.size == (1000, 500)


def test_jpeg_and_tiff_load(tmp_path):
    jpeg = _picture(tmp_path, ".jpg", mode="RGB")
    page, _ = _page(Image(jpeg))
    assert _embedded(page.svg())[0][0] == "jpeg"
    tiff = _picture(tmp_path, ".tiff")
    page, inset = _page(str(tiff))
    (kind, image), = _embedded(page.svg())
    assert kind == "png" and image.size == (1000, 500)                  # a TIFF becomes a PNG in the file
    assert inset.fragment().size_mm == (40.0, 20.0)


def test_an_array_loads():
    grey = (np.arange(200) % 256).astype(np.uint8).reshape(10, 20)
    colour = np.linspace(0.0, 1.0, 10 * 20 * 3).reshape(10, 20, 3)
    for data in (grey, colour):
        page, inset = _page(data)
        (kind, image), = _embedded(page.svg())
        assert kind == "png" and image.size == (20, 10) and inset.fragment().size_mm == (40.0, 20.0)
    with pytest.raises(ValueError, match="2D or 3D"):
        Image(np.zeros(5)).fragment(10.0, font_pt=7.0)
    with pytest.raises(ValueError, match="height"):
        Inset(grey, height=10.0)                                        # a picture keeps its own shape


def test_a_real_sem_marks_a_point_in_um(tmp_path):
    path = _picture(tmp_path, ".png")
    page, inset = _page(Image(path, scale_um_per_px=0.02))
    x, y = inset.at(10, 0).xy()                                         # 10 um is pixel 500: the middle of the top edge
    assert (x, y) == pytest.approx((50.0, 30.0 + 10.0))
    x, y = inset.at(20, 10).xy()                                        # the far corner of 1000 x 500 px
    assert (x, y) == pytest.approx((70.0, 20.0))
    bare = Inset(Image(path), center=(50, 30), width=40.0)
    assert bare.at(500, 0).xy() == pytest.approx((50.0, 40.0))          # no scale: pixels


def test_the_scale_bar_is_vector_and_sized(tmp_path):
    path = _picture(tmp_path, ".png")
    page = Page(width_mm=100, height_mm=60, font_pt=7.0, letters=False)
    page.add(Inset(Image(path, scale_um_per_px=0.02), center=(50, 30), width=40.0, bar=(5, "5 µm")))
    svg = page.svg()
    rects = re.findall(r'<rect[^>]*>', svg)
    bar = [r for r in rects
           if 'fill="#ffffff"' in r and float(re.search(r'width="([\d.]+)"', r).group(1)) == pytest.approx(10.0)]
    assert len(bar) == 1                                                # 5 um of 20 um at 40 mm: 10 mm
    texts = _read_page(ET.fromstring(svg), "page.svg").texts
    mine = [t for t in texts if t.words == "5 µm"]
    assert len(mine) == 1 and mine[0].pt == pytest.approx(7.0, abs=0.01)    # live text at the page font


def test_the_scale_bar_follows_the_inset(tmp_path):
    path = _picture(tmp_path, ".png")
    page = Page(width_mm=100, height_mm=60, letters=False)
    inset = page.add(Inset(Image(path, scale_um_per_px=0.02), center=(50, 30), width=80.0, bar=(5, "5 µm")))
    svg = page.svg()
    assert any(float(re.search(r'width="([\d.]+)"', r).group(1)) == pytest.approx(20.0)
               for r in re.findall(r'<rect[^>]*fill="#ffffff"[^>]*>', svg))
    assert inset.bar == (5, "5 µm")


def test_a_bar_needs_a_linear_x_scale():
    import matplotlib

    matplotlib.use("Agg")
    from matplotlib import pyplot as plt

    from optodraw.figure.sources import Plot

    fig, ax = plt.subplots()
    ax.set_xscale("log")
    ax.plot([1, 10, 100], [1, 2, 3])
    page, inset = _page(Plot(fig), bar=(5, "5"))
    with pytest.raises(ValueError, match="linear"):
        inset.annotation_2d()
    plt.close(fig)
    fig, ax = plt.subplots()
    ax.plot([0, 10], [0, 1])
    page, inset = _page(Plot(fig), bar=(5, "5"))
    assert inset.annotation_2d()["children"]                            # a linear plot takes a bar
    plt.close(fig)


# --- the SEM render ---------------------------------------------------------------------------------------------

def _record(spec, polygons):
    return GDSLayerRecord(spec=spec, name=f"L{spec[0]}", description="", color="#000000", opacity=1.0,
                          thickness=0.22, zmin=0.0, material_preset="silicon", polygons=polygons, matched_pdk=False)


def _rect(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def _layout(*records):
    return GDSLayout(source_path=Path("t.gds"), cell_name="T", bounds=(-20, -20, 20, 20), layer_records=list(records))


REGION = (-10.0, -10.0, 10.0, 10.0)


def _two_buses():
    return _layout(_record((1, 0), [_rect(-6, -0.25, -0.5, 0.25), _rect(2.0, -6, 2.5, 6)]))


def _view():
    return top_view(_two_buses(), "gdsfactory_generic", REGION)


def _modulator():
    layout = _layout(_record((1, 0), [_rect(-20, -0.25, 20, 0.25)]), _record((3, 0), [_rect(-20, -3, 20, 3)]),
                     _record((20, 0), [_rect(-20, -3, 20, 0)]), _record((21, 0), [_rect(-20, 0, 20, 3)]),
                     _record((40, 0), [_rect(-20, -2.8, 20, -2.2)]), _record((41, 0), [_rect(-20, -3.2, 20, -1.8)]))
    return cross_section(layout, "gdsfactory_generic", ((0, -6), (0, 6)))


def test_the_sem_render_is_marked():
    page, inset = _page(SemView(_view(), width_px=400))
    fragment = inset.fragment()
    assert fragment.kind == "render" and 'data-inset="render"' in page.svg()
    marked = _embedded(fragment.svg)[0][1]
    plain = _embedded(SemView(_view(), width_px=400, mark=False).fragment(40.0, font_pt=7.0).svg)[0][1]
    assert np.abs(np.asarray(marked, dtype=float) - np.asarray(plain, dtype=float)).max() > 0     # the mark is on
    assert to_source(_view()).__class__ is SemView                                     # a TopView goes to its render


def test_the_sem_render_prints_at_600_ppi():
    fragment = SemView(_view()).fragment(60.0, font_pt=7.0)
    assert _embedded(fragment.svg)[0][1].width == 1417                  # 60 mm at 600 ppi
    assert SemView(_view(), width_px=300).fragment(60.0, font_pt=7.0).svg.count("base64") == 1
    assert _embedded(SemView(_view(), width_px=300).fragment(60.0, font_pt=7.0).svg)[0][1].width == 300


def test_mark_off_keeps_the_record():
    fragment = SemView(_view(), width_px=300, mark=False).fragment(40.0, font_pt=7.0)
    assert fragment.kind == "render"
    assert any("render" in note for note in fragment.notes)
    assert SemView(_view(), width_px=300).fragment(40.0, font_pt=7.0).kind == "render"


def test_the_sem_render_marks_a_file_point():
    view = _view()
    width_mm, px = 40.0, 400
    fragment = SemView(view, width_px=px).fragment(width_mm, font_pt=7.0)
    maps = view.maps(px)
    nv = maps.height.shape[0]
    per_px = width_mm / px
    assert fragment.size_mm[0] == width_mm and fragment.size_mm[1] > nv * per_px        # the info strip is under it
    assert fragment.place(REGION[0], REGION[3]) == pytest.approx((0.0, 0.0))             # the top left of the view
    assert fragment.place(REGION[2], REGION[1]) == pytest.approx((width_mm, nv * per_px))
    high = view.maps(px).height

    def pixel(x, y):
        mx, my = fragment.place(x, y)
        return int(my / per_px), int(mx / per_px)

    assert high[pixel(-3.0, 0.0)] > high[pixel(-3.0, 4.0)]              # on the horizontal bus, off it
    assert high[pixel(2.25, 4.0)] > high[pixel(4.0, 4.0)]                # on the vertical bus, off it


def test_the_sem_render_follows_a_rotation():
    view = _view()
    px = 400
    fragment = SemView(view, width_px=px, rotation=90.0).fragment(40.0, font_pt=7.0)
    high, per_px = view.maps(px, 90.0).height, 40.0 / px
    for point, on in (((-3.0, 0.0), True), ((-3.0, 4.0), False), ((2.25, 4.0), True), ((4.0, 4.0), False)):
        mx, my = fragment.place(*point)
        value = high[int(my / per_px), int(mx / per_px)]
        assert (value > high.min() + 0.1) == on, (point, value)


def test_a_tilted_render_refuses_place():
    fragment = SemView(_view(), width_px=300, tilt=30.0).fragment(40.0, font_pt=7.0)
    with pytest.raises(ValueError, match="tilt"):
        fragment.place(0.0, 0.0)
    assert fragment.kind == "render" and fragment.size_mm[0] == 40.0


def test_a_section_render_marks_a_cut_point():
    xs = _modulator()
    px = 600
    fragment = SemView(xs, width_px=px, mark=False).fragment(60.0, font_pt=7.0)
    image = np.asarray(_embedded(fragment.svg)[0][1], dtype=float)
    assert image.shape[1] == px and fragment.size_mm[1] == pytest.approx(60.0 * image.shape[0] / px)
    s0, s1 = xs.window
    top = max(g.bounds[3] for g in xs.regions.values() if not g.is_empty)
    per_px = 60.0 / px

    def grey(s, z):
        mx, my = fragment.place(s, z)
        row, col = int(my / per_px), int(mx / per_px)
        return image[row - 3:row + 4, col - 3:col + 4].mean()

    assert grey(3.5, 1.5) > 150                                         # in the M1 pad: bright metal
    assert 40 < grey(8.0, 2.0) < 110                                    # in the oxide beside it
    assert grey(2.0, top + 0.7) < 15                                    # in the vacuum over the top surface
    assert fragment.place(s0, top)[0] == pytest.approx(0.0) and fragment.place(s1, top)[0] == pytest.approx(60.0)
    with pytest.raises(ValueError, match="tilt"):
        SemView(xs, tilt=20.0).fragment(60.0, font_pt=7.0)


def test_a_section_goes_to_the_section_view_unless_asked():
    from optodraw.figure.sources import SectionView

    assert isinstance(to_source(_modulator()), SectionView)
    assert isinstance(SemView(_modulator()), SemView)


def test_a_huge_picture_warns(tmp_path, monkeypatch):
    from optodraw.figure import sources

    monkeypatch.setattr(sources, "PICTURE_LIMIT", 1000)
    with pytest.warns(UserWarning, match="MB"):
        Image(np.zeros((100, 100), dtype=np.uint8))
    path = _picture(tmp_path, ".png", size=(300, 300))
    big = tmp_path / "big.tif"
    PilImage.fromarray(np.zeros((100, 100), dtype=np.uint8)).save(big)
    with pytest.warns(UserWarning, match="MB"):
        Image(big)
    monkeypatch.setattr(sources, "PICTURE_LIMIT", 16 * 1024 * 1024)
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        Image(path)


def test_a_picture_exports_as_png(tmp_path, rasteriser):
    path = _picture(tmp_path, ".png")
    page, _ = _page(Image(path))
    out = page.export(tmp_path / "fig", formats=("png",), dpi=100)
    assert out["png"].stat().st_size > 0


# --- fix round 1 ------------------------------------------------------------------------------------------------

def test_a_bare_source_is_built_once_per_export(tmp_path, monkeypatch):
    calls = []
    for cls in (SemView, Image):
        real = cls.fragment

        def counted(self, *args, _real=real, **kwargs):
            calls.append(type(self).__name__)
            return _real(self, *args, **kwargs)

        monkeypatch.setattr(cls, "fragment", counted)
    for item, name in ((_view(), "SemView"), (str(_picture(tmp_path, ".png")), "Image")):
        calls.clear()
        page = Page(width_mm=100, height_mm=60, letters=False)
        page.add(Inset(item, center=(50, 30), width=40.0))
        page.svg()
        assert calls == [name]
        page.svg()                                                  # each export asks a live source again
        assert calls == [name, name]


def test_the_bar_has_a_dark_plate(tmp_path):
    path = _picture(tmp_path, ".png")
    page, _ = _page(Image(path, scale_um_per_px=0.02), bar=(5, "5 µm"))
    svg = page.svg()
    plates = re.findall(r'<rect[^>]*fill="#000000"[^>]*>', svg)
    assert len(plates) == 1 and "fill-opacity" in plates[0]
    assert len(re.findall(r'<rect[^>]*fill="#ffffff"[^>]*>', svg)) == 1


def test_the_bar_sits_over_the_info_strip():
    px = 400
    page, inset = _page(SemView(_view(), width_px=px), width=40.0, bar=(2, "2 µm"))
    fragment = inset.fragment()
    strip = fragment.size_mm[1] - 40.0 * _view().maps(px).height.shape[0] / px
    assert strip > 0 and fragment.floor_mm == pytest.approx(strip)
    for fill in ("#ffffff", "#000000"):                                  # the bar and its plate, in mm from the top
        rect = re.findall(rf'<rect[^>]*fill="{fill}"[^>]*>', page.svg())[0]
        y, h = (float(re.search(rf'\s{k}="(-?[\d.]+)"', rect).group(1)) for k in ("y", "height"))
        assert y + h <= fragment.size_mm[1] - strip + 1e-6


@pytest.mark.parametrize("width", [60.0, 100.0])
def test_the_bar_text_reads_the_font_at_any_print_scale(tmp_path, width):
    from optodraw import Scene, Laser
    from optodraw.publication import export_figure

    scene = Scene(width=200, height=100)
    scene.add(Laser(center=(-50, 0)))
    scene.add(Inset(Image(_picture(tmp_path, ".png"), scale_um_per_px=0.02), center=(30, 0), width=60.0,
                    bar=(5, "5 µm")))
    out = export_figure(scene, tmp_path / "f", width_mm=width, font_size_pt=6.0, formats=("svg",))
    texts = _read_page(ET.parse(out["svg"]).getroot(), "f.svg").texts
    mine = [t for t in texts if t.words == "5 µm"]
    assert len(mine) == 1 and mine[0].pt == pytest.approx(6.0, abs=0.02)


def test_a_jpeg_keeps_its_orientation(tmp_path):
    path = tmp_path / "turned.jpg"
    exif = PilImage.Exif()
    exif[0x0112] = 6                                                    # stored 1000 x 500, shown turned: 500 x 1000
    PilImage.fromarray((np.arange(500000) % 251).astype(np.uint8).reshape(500, 1000)).save(path, exif=exif)
    page, inset = _page(Image(path))
    (kind, image), = _embedded(page.svg())
    assert image.size == (500, 1000) and inset.fragment().size_mm == (40.0, 80.0)
    plain = _picture(tmp_path, ".jpg")
    assert _embedded(_page(Image(plain))[0].svg())[0][0] == "jpeg"      # no tag: the bytes stay


def test_the_strip_height_holds_for_a_section_and_a_tilt():
    xs = _modulator()
    for item, extra in ((xs, {}), (_view(), {"tilt": 30.0})):
        fragment = SemView(item, width_px=500, **extra).fragment(50.0, font_pt=7.0)
        image = _embedded(fragment.svg)[0][1]
        assert image.size[1] - fragment.floor_mm * 500 / 50.0 > 0
        black = np.asarray(image, dtype=float)[-int(round(fragment.floor_mm * 10)) + 1:]
        assert black.mean() < 40                                        # that bottom strip is the black info bar



class _Unmapped:
    """A user's source: its fragment has a place but no map."""

    def fragment(self, width_mm, *, font_pt):
        from optodraw.figure.fragment import Fragment

        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width_mm}mm" height="10mm" '
               f'viewBox="0 0 {width_mm} 10"><rect width="{width_mm}" height="10"/></svg>')
        return Fragment(svg=svg, size_mm=(width_mm, 10.0), place=lambda x, y: (x, y))


def test_a_bar_on_a_fragment_with_no_map_is_refused_when_it_is_built():
    import json

    from optodraw.schema import scene_from_spec

    with pytest.raises(ValueError, match=r"'mine'.*scale bar.*no map"):
        Inset(_Unmapped(), width=40.0, bar=(5, "5 um"), label="mine").fragment()
    page = Page(width_mm=100, height_mm=60, letters=False)
    page.add(Inset(_Unmapped(), center=(50, 30), width=40.0, label="mine"))
    spec = json.loads(json.dumps(page.to_spec()))
    next(c for c in spec["components"] if c["type"] == "Inset")["bar"] = [5, "5 um"]      # a page file by hand
    with pytest.raises(ValueError, match=r"'mine'.*scale bar.*no map"):
        scene_from_spec(spec).svg()


def test_the_bar_error_names_the_inset():
    from matplotlib.figure import Figure

    from optodraw.figure.sources import Plot

    fig = Figure()
    ax = fig.subplots()
    ax.set_xscale("log")
    ax.plot([1, 10, 100], [1, 2, 3])
    _, inset = _page(Plot(fig), bar=(5, "5"), label="spectrum")
    with pytest.raises(ValueError, match=r"'spectrum'.*linear"):
        inset.annotation_2d()


def test_the_bar_plate_holds_its_text(tmp_path):
    from optodraw.core.markup import text_width
    from optodraw.figure.fragment import PT_MM

    text = "a long scale bar text of many words"
    page, _ = _page(Image(_picture(tmp_path, ".png"), scale_um_per_px=0.02), bar=(1, text))
    plate = next(r for r in re.findall(r"<rect[^>]*>", page.svg()) if 'fill="#000000"' in r)
    size = 7.0 * PT_MM                                                    # the page's text size
    wide = float(re.search(r'width="([\d.]+)"', plate).group(1))
    assert wide == pytest.approx(text_width(text, size) + 0.8 * size, rel=1e-3)


@pytest.mark.parametrize("mode", ["F", "CMYK"])
def test_a_tiff_with_no_fixed_scale_to_8_bit_is_refused(tmp_path, mode):
    path = tmp_path / "p.tif"
    if mode == "F":
        PilImage.fromarray(np.linspace(0.0, 4.0, 64, dtype=np.float32).reshape(8, 8)).save(path)
    else:
        PilImage.new("CMYK", (8, 8), (0, 255, 0, 0)).save(path)
    assert PilImage.open(path).mode == mode
    with pytest.raises(ValueError, match=f"mode '{mode}'"):
        Image(path).fragment(30.0, font_pt=7.0)
