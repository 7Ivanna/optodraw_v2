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


def test_top_down_is_the_map_itself():
    from optodraw.gds.xsection.top import project

    height = np.random.default_rng(1).random((30, 40))
    shade = np.random.default_rng(2).random((30, 40))
    assert np.array_equal(project(height, shade, pitch=0.1, tilt=0.0), shade)


def _png(data: bytes):
    from PIL import Image

    return Image.open(io.BytesIO(data))


def test_findings_name_undeclared_layers_and_an_empty_region():
    from optodraw.gds.xsection.top import top_view

    layout = _layout(_record((1, 0), [_rect(-3, -0.25, 3, 0.25)]), _record((999, 0), [_rect(-1, -1, 1, 1)]))
    view = top_view(layout, "gdsfactory_generic", (-5, -5, 5, 5))
    assert any("999/0" in finding for finding in view.check())
    empty = top_view(layout, "gdsfactory_generic", (100, 100, 110, 110))
    assert any("no drawn layer" in finding for finding in empty.check())


