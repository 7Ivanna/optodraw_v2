"""Look B: the cross-section as an SEM-like image that never passes as a measured one."""

from __future__ import annotations

from pathlib import Path

import pytest

from optodraw.gds.layout import GDSLayerRecord, GDSLayout
from optodraw.gds.xsection.model import cross_section

pytest.importorskip("PIL")


def _record(spec, polygons):
    return GDSLayerRecord(spec=spec, name=f"L{spec[0]}", description="", color="#000000", opacity=1.0,
                          thickness=0.22, zmin=0.0, material_preset="silicon", polygons=polygons, matched_pdk=False)


def _rect(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def _modulator():
    layout = GDSLayout(source_path=Path("t.gds"), cell_name="T", bounds=(-50, -50, 50, 50), layer_records=[
        _record((1, 0), [_rect(-20, -0.25, 20, 0.25)]), _record((3, 0), [_rect(-20, -3, 20, 3)]),
        _record((20, 0), [_rect(-20, -3, 20, 0)]), _record((21, 0), [_rect(-20, 0, 20, 3)]),
        _record((40, 0), [_rect(-20, -2.8, 20, -2.2)]), _record((41, 0), [_rect(-20, -3.2, 20, -1.8)])])
    return cross_section(layout, "gdsfactory_generic", ((0, -6), (0, 6)))


def test_the_greys_follow_the_material_table():
    from optodraw.gds.xsection.sem import sem_grey

    order = [sem_grey(m) for m in ("vacuum", "sio2", "silicon", "silicon_nitride")]
    assert order == sorted(order) and len(set(order)) == 4
    for bright in ("germanium", "aluminum", "copper", "tungsten"):
        assert sem_grey(bright) > sem_grey("silicon_nitride")
    assert sem_grey("vacuum") == 0
    assert sem_grey("oxide") == sem_grey("sio2")                          # the palette's aliases hold here too
    assert sem_grey("silicon") < sem_grey("unobtainium") < sem_grey("germanium")


def test_the_canvas_is_true_aspect_with_vacuum_over_the_top_surface():
    from optodraw.gds.xsection.sem import sem_canvas

    xs = _modulator()
    canvas = sem_canvas(xs, 1000)
    assert canvas.width == 1000
    assert canvas.x(xs.window[1]) - canvas.x(xs.window[0]) == pytest.approx(1000, abs=1)
    top = max(g.bounds[3] for g in xs.regions.values())
    assert canvas.y(top) > 20                                              # vacuum above the surface
    assert canvas.y(0.0) - canvas.y(1.0) == pytest.approx(canvas.px_per_um, rel=1e-9)
    assert canvas.height <= 1.25 * canvas.width + 1


def _pixels(png: bytes):
    import io

    import numpy as np
    from PIL import Image

    return np.asarray(Image.open(io.BytesIO(png)).convert("L"), dtype=float)


def test_the_same_seed_gives_the_same_bytes():
    xs = _modulator()
    one = xs.png(look="sem", seed=3, width_px=500)
    assert one == xs.png(look="sem", seed=3, width_px=500)
    assert one != xs.png(look="sem", seed=4, width_px=500)
    assert one[:8] == b"\x89PNG\r\n\x1a\n"


def test_the_png_is_written_when_a_path_is_given(tmp_path):
    xs = _modulator()
    data = xs.png(tmp_path / "xs.png", width_px=400)
    assert (tmp_path / "xs.png").read_bytes() == data


def test_vacuum_is_darkest_oxide_darker_than_silicon_and_metal_brightest():
    from shapely.ops import polylabel

    from optodraw.gds.xsection.sem import sem_canvas

    xs = _modulator()
    image = _pixels(xs.png(look="sem", seed=0, width_px=800, mark=False))
    canvas = sem_canvas(xs, 800)
    middle = sum(xs.window) / 2

    def patch(s, z):
        x, y = round(canvas.x(s)), round(canvas.y(z))
        return image[y - 3:y + 4, x - 3:x + 4].mean()

    top = max(g.bounds[3] for g in xs.regions.values())
    box_bottom = xs.regions["box"].bounds[1]
    m1 = polylabel(max(xs.regions["M1"].geoms, key=lambda p: p.area))
    vacuum, oxide = patch(middle, top + 0.3), patch(middle, box_bottom / 2)
    silicon, metal = patch(middle, box_bottom - 0.2), patch(m1.x, m1.y)
    assert vacuum < oxide < silicon < metal


def test_implants_do_not_show():
    from dataclasses import replace

    xs = _modulator()
    assert xs.png(width_px=400) == replace(xs, doping={}).png(width_px=400)


def test_only_the_sem_look_draws_a_png():
    with pytest.raises(ValueError, match="svg"):
        _modulator().png(look="schematic")


def test_the_info_bar_sits_under_the_image():
    from optodraw.gds.xsection.sem import sem_canvas

    xs = _modulator()
    image = _pixels(xs.png(width_px=600, mark=False))
    canvas = sem_canvas(xs, 600)
    bar = image[canvas.height:]
    assert image.shape[1] == 600 and bar.shape[0] >= 30
    assert (bar < 40).mean() > 0.85 and bar.max() > 200                    # black, with a white scale bar


def _metadata(png: bytes) -> dict:
    import io

    from PIL import Image

    return dict(Image.open(io.BytesIO(png)).text)


def test_the_image_is_marked_as_a_render_by_default():
    from optodraw.gds.xsection.sem import sem_canvas

    xs = _modulator()
    on, off = xs.png(width_px=600, seed=2), xs.png(width_px=600, seed=2, mark=False)
    canvas = sem_canvas(xs, 600)
    marked, plain = _pixels(on), _pixels(off)
    assert marked[canvas.height:, 300:].max() > 180                       # "optodraw render" in the info bar
    assert plain[canvas.height:, 300:].max() < 60                          # mark=False: the bar's right is empty
    across = abs(marked[:canvas.height] - plain[:canvas.height])
    assert 0.2 < across.mean() < 6.0 and across.max() < 60                 # the diagonal mark: there, but faint


def test_the_metadata_says_rendered_not_measured_with_or_without_the_marks():
    xs = _modulator()
    for png in (xs.png(width_px=400), xs.png(width_px=400, mark=False)):
        text = _metadata(png)
        assert any("rendered, not measured" in value for value in text.values())
        assert text.get("Software") == "optodraw"
