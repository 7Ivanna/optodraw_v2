"""Picture sources for insets: real photos stay pixels, optodraw's own SEM render says it is a render."""

from __future__ import annotations

import base64
import io
import re
from pathlib import Path

import pytest

from optodraw import Inset
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


def test_a_picture_exports_as_png(tmp_path):
    path = _picture(tmp_path, ".png")
    page, _ = _page(Image(path))
    out = page.export(tmp_path / "fig", formats=("png",), dpi=100)
    assert out["png"].stat().st_size > 0


# --- fix round 1 ------------------------------------------------------------------------------------------------


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
