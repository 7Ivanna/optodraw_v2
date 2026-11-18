"""The top view: an SEM-like image of a chip region, made by the cross-section process on parallel cuts."""

from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import pytest

from optodraw.gds.layout import GDSLayerRecord, GDSLayout
from optodraw.gds.parsers import load_layer_stack

pytest.importorskip("PIL")


def _record(spec, polygons):
    return GDSLayerRecord(spec=spec, name=f"L{spec[0]}", description="", color="#000000", opacity=1.0,
                          thickness=0.22, zmin=0.0, material_preset="silicon", polygons=polygons, matched_pdk=False)


def _rect(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def _layout(*records):
    return GDSLayout(source_path=Path("t.gds"), cell_name="T", bounds=(-20, -20, 20, 20), layer_records=list(records))


def _chip():
    """A bus that runs under an M3 pad on the right; the pad has a pad opening above the bus line."""

    return _layout(_record((1, 0), [_rect(-12, -0.25, 12, 0.25)]), _record((49, 0), [_rect(2, -4, 9, 4)]),
                   _record((46, 0), [_rect(3, 1, 8, 3.5)]))


def _two_buses():
    """A horizontal bus on the left, a vertical bus on the right."""

    return _layout(_record((1, 0), [_rect(-3, -0.25, -0.5, 0.25), _rect(0.75, -3, 1.25, 3)]))


def _at(maps, region, x, y):
    """The (row, column) of the map pixel over layout point (x, y), for a view with no rotation."""

    x0, _, _, y1 = region
    return int((y1 - y) / maps.pitch), int((x - x0) / maps.pitch)


REGION = (-10.0, -10.0, 10.0, 10.0)


def _view(stage="device", layout=None, region=REGION):
    from optodraw.gds.xsection.top import top_view

    return top_view(layout or _chip(), "gdsfactory_generic", region, stage=stage)


def test_the_device_view_is_the_wafer_before_the_first_oxide():
    maps = _view("device").maps(200)
    bus, box = maps.height[_at(maps, REGION, -5, 0)], maps.height[_at(maps, REGION, -5, -3)]
    assert bus == pytest.approx(0.22, abs=1e-3)
    assert box == pytest.approx(0.0, abs=1e-3)
    assert maps.grey[_at(maps, REGION, -5, 0)] > maps.grey[_at(maps, REGION, -5, -3)] + 20   # silicon over oxide


def test_the_chip_view_is_the_finished_top_surface_from_the_stack():
    stack = load_layer_stack("gdsfactory_generic")
    m3 = stack.styles[(49, 0)]
    m3_top = float(m3["zmin"]) + float(m3["thickness"])
    passivation = float(stack.oxide["passivation"])
    maps = _view("chip").maps(200)
    # the passivation is oxide: the last oxide level, planarised over M3, so beside the pad and over it the
    # surface is one flat top
    assert maps.height[_at(maps, REGION, -5, -3)] == pytest.approx(m3_top + passivation, abs=1e-3)
    assert maps.height[_at(maps, REGION, 5.5, -3)] == pytest.approx(m3_top + passivation, abs=1e-3)
    assert maps.height[_at(maps, REGION, 5.5, 2.25)] == pytest.approx(m3_top, abs=1e-3)       # the pad opening
    opening, covered = maps.grey[_at(maps, REGION, 5.5, 2.25)], maps.grey[_at(maps, REGION, 5.5, -3)]
    assert opening > covered                                     # bare metal, no oxide over it


def test_buried_devices_show_through_the_cladding_but_not_through_metal():
    maps = _view("chip").maps(200)

    def grey(x, y):
        return maps.grey[_at(maps, REGION, x, y)]

    assert grey(-5, 0) > grey(-5, -3) + 3                         # the bus under oxide shows
    assert grey(5.5, 0) == pytest.approx(grey(5.5, -3), abs=0.5)  # under the pad it does not


def test_see_through_sets_how_deep_a_buried_device_shows():
    from optodraw.gds.xsection.top import top_view

    def contrast(depth):
        maps = top_view(_chip(), "gdsfactory_generic", REGION, stage="chip", see_through=depth).maps(200)
        return maps.grey[_at(maps, REGION, -5, 0)] - maps.grey[_at(maps, REGION, -5, -3)]

    assert contrast(5.0) > contrast(2.5) > contrast(1.0) > 0.0
    with pytest.raises(ValueError, match="see_through"):
        top_view(_chip(), "gdsfactory_generic", REGION, see_through=0.0)


def test_a_step_id_picks_the_stage_and_an_unknown_stage_names_the_steps():
    maps = _view("etch_device").maps(200)
    assert maps.height[_at(maps, REGION, -5, 0)] == pytest.approx(0.22, abs=1e-3)
    with pytest.raises(ValueError, match="etch_device"):
        _view("no_such_step")


def test_tapered_walls_show_in_both_directions():
    region = (-2.0, -2.0, 2.0, 2.0)
    maps = _view("device", _two_buses(), region).maps(400)       # 10 nm per pixel
    h = 0.22

    def slope_pixels(profile):
        return int(np.count_nonzero((profile > 0.1 * h) & (profile < 0.9 * h)))

    row, column = _at(maps, region, -1.5, 0.0)
    across_horizontal = maps.height[: row + 1, column]           # from above the bus down to its middle
    row, column = _at(maps, region, 1.0, 1.0)
    across_vertical = maps.height[row, : column + 1]             # from the left of the bus to its middle
    a, b = slope_pixels(across_horizontal), slope_pixels(across_vertical)
    assert a >= 2 and b >= 2
    assert abs(a - b) <= 1


def test_a_buried_edge_does_not_notch_the_surface_over_it():
    # M2 runs under the passivation skirt of the pad's bottom edge; its side edges must not cut the skirt
    layout = _layout(_record((49, 0), [_rect(-4, 0, 4, 4)]), _record((45, 0), [_rect(-1.03, -1, 1.03, 2)]))
    region = (-3.01, -2.01, 3.01, 2.01)
    maps = _view("chip", layout, region).maps(300)
    row, _ = _at(maps, region, 0.0, -0.2)                        # in the skirt, 0.2 um past the pad edge
    skirt = maps.height[row]
    assert skirt.max() - skirt.min() < 0.02                       # the same height all along the edge


def test_a_sliver_with_no_thickness_hides_nothing():
    from shapely.geometry import MultiPolygon, box

    from optodraw.gds.xsection.top import _profile

    regions = {"box": MultiPolygon([box(0, -3, 10, 0)]), "oxide": MultiPolygon([box(0, 0, 10, 3.7)])}
    materials = {"box": "sio2", "oxide": "sio2"}
    s = np.linspace(0.5, 9.5, 50)
    clean = _profile(regions, materials, s)
    regions["M1"], materials["M1"] = MultiPolygon([box(0, 1.8, 10, 1.8 + 1e-12)]), "aluminum"
    z, g, _ = _profile(regions, materials, s)
    assert np.allclose(z, clean[0]) and np.allclose(g, clean[1])


def test_an_outside_corner_of_a_conformal_film_is_round():
    import copy

    from optodraw.gds.xsection.top import top_view

    stack = copy.deepcopy(load_layer_stack("gdsfactory_generic"))
    stack.styles[(41, 0)]["sidewall_deg"] = 90.0                  # a vertical metal wall: distances are plain
    layout = _layout(_record((41, 0), [_rect(0, 0, 8, 8)]))      # M1, under the conformal cladding (2.4 um in all)
    region = (-3.005, -3.005, 3.005, 3.005)                       # round the metal's corner at (0, 0)
    maps = top_view(layout, stack, region, stage="chip").maps(201)
    r = 0.5
    beside = maps.height[_at(maps, region, -r, 1.5)]              # r left of the metal's left edge
    corner = maps.height[_at(maps, region, -r / 2 ** 0.5, -r / 2 ** 0.5)]   # r from the corner, diagonally
    floor = maps.height[_at(maps, region, -2.9, -2.9)]
    assert beside > floor + 0.5
    assert corner == pytest.approx(beside, abs=0.03)


def test_rotation_turns_the_view():
    region = (-2.01, -2.01, 2.01, 2.01)                         # no pixel centre on a layout edge
    view = _view("device", _two_buses(), region)
    flat, turned = view.maps(100), view.maps(100, rotation=90.0)
    assert np.allclose(turned.height, np.rot90(flat.height, -1), atol=1e-6)
    assert np.allclose(turned.grey, np.rot90(flat.grey, -1), atol=1e-6)


def test_identical_cuts_run_the_process_once(monkeypatch):
    from optodraw.gds.xsection import engine

    calls = []
    original = engine.XSectionEngine.run
    monkeypatch.setattr(engine.XSectionEngine, "run", lambda self, cut, **kw: calls.append(1) or original(self, cut, **kw))
    layout = _layout(_record((1, 0), [_rect(-3, -0.25, -0.5, 0.25)]))
    _view("device", layout, (-2.0, -2.0, 2.0, 2.0)).maps(100)
    assert len(calls) <= 6                                       # 200 cuts, a handful of different ones


def test_the_tilted_view_shows_front_walls_and_hides_what_stands_behind():
    from optodraw.gds.xsection.top import project

    height = np.zeros((100, 100))
    height[40:60, 40:60] = 1.0
    shade = np.where(height > 0, 100.0, 50.0)
    image = project(height, shade, pitch=0.1, tilt=45.0)
    cos, sin = np.cos(np.radians(45)), np.sin(np.radians(45))
    assert image.shape[0] == pytest.approx(100 * cos, abs=1)    # cut at the far edge: no empty band on top
    assert image.min() > 0                                       # every pixel shows the sample
    block = ((image[:, 50] - 50.0) / 50.0).sum()                 # pixels of block, a part pixel in part
    assert block == pytest.approx(20 * cos + 1.0 * sin / 0.1, abs=1)
    assert np.count_nonzero(image[:, 20] > 50.0) == 0
    ground_seen = image.shape[0] - block
    assert ground_seen == pytest.approx((100 - 20 - 10) * cos, abs=1)    # 10 rows behind the block hide


def test_a_tilted_far_edge_is_a_solid_line():
    from optodraw.gds.xsection.top import project

    rows, cols = np.mgrid[0:200, 0:200]
    height = np.where(np.hypot(rows - 100, cols - 100) < 60, 0.3, 0.0)   # a disc: its far rim slants
    shade = np.where(height > 0, 100.0, 50.0)
    image = project(height, shade, pitch=0.1, tilt=45.0)
    for column in range(70, 131):
        seen = image[:, column] > 75.0
        assert np.count_nonzero(np.diff(seen.astype(int))) <= 2   # one run of disc per column, no gaps


def test_top_down_is_the_map_itself():
    from optodraw.gds.xsection.top import project

    height = np.random.default_rng(1).random((30, 40))
    shade = np.random.default_rng(2).random((30, 40))
    assert np.array_equal(project(height, shade, pitch=0.1, tilt=0.0), shade)


def _png(data: bytes):
    from PIL import Image

    return Image.open(io.BytesIO(data))


def test_the_image_is_marked_as_a_render_and_seeded():
    view = _view("chip")
    a, b = view.png(width_px=200, seed=3), view.png(width_px=200, seed=3)
    assert a == b
    assert view.png(width_px=200, seed=4) != a
    plain = view.png(width_px=200, seed=3, mark=False)
    assert plain != a
    for data in (a, plain):
        assert "rendered, not measured" in _png(data).text["Description"]
    tilted = _png(view.png(width_px=200, tilt=50.0))
    assert tilted.size[0] == 200 and tilted.size[1] < _png(a).size[1]


def test_png_writes_the_file(tmp_path):
    out = tmp_path / "top.png"
    data = _view("device").png(out, width_px=120)
    assert out.read_bytes() == data


def test_findings_name_undeclared_layers_and_an_empty_region():
    from optodraw.gds.xsection.top import top_view

    layout = _layout(_record((1, 0), [_rect(-3, -0.25, 3, 0.25)]), _record((999, 0), [_rect(-1, -1, 1, 1)]))
    view = top_view(layout, "gdsfactory_generic", (-5, -5, 5, 5))
    assert any("999/0" in finding for finding in view.check())
    empty = top_view(layout, "gdsfactory_generic", (100, 100, 110, 110))
    assert any("no drawn layer" in finding for finding in empty.check())


def test_top_view_is_exported_from_the_gds_package():
    import optodraw.gds as gds

    assert gds.top_view.__name__ == "top_view"
    assert gds.TopView.__name__ == "TopView"
