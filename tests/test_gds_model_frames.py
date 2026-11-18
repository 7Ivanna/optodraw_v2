"""A GDSModel's own frame (the polygons re-centred on the cell's bounding box, scaled, shifted again by a crop)
against the GDS file's frame, which the layout view's ruler gives."""

from __future__ import annotations

import pytest

from optodraw import GDSModel


def _gds(tmp_path):
    import gdstk

    lib = gdstk.Library()
    cell = lib.new_cell("TOP")
    cell.add(gdstk.rectangle((100, 50), (130, 60), layer=1))
    cell.add(gdstk.rectangle((90, 40), (95, 45), layer=2))        # the bounding box: 90..130 by 40..60
    path = tmp_path / "frames.gds"
    lib.write_gds(str(path))
    return str(path)


def _corners(model, spec):
    return sorted({(round(x, 6), round(y, 6)) for polygon in model._polygons_by_spec[spec] for x, y in polygon})


def test_a_file_point_maps_to_where_the_part_drew_it(tmp_path):
    model = GDSModel(_gds(tmp_path), cell_name="TOP")
    mapped = sorted((round(x, 6), round(y, 6)) for x, y in (model.file_to_local(px, py)
                                                            for px, py in ((100, 50), (130, 50), (130, 60), (100, 60))))
    assert _corners(model, (1, 0)) == mapped
    assert model.file_to_local(110, 50) == pytest.approx((0.0, 0.0))  # the bounding box's centre


def test_the_two_frames_round_trip_with_a_scale(tmp_path):
    model = GDSModel(_gds(tmp_path), cell_name="TOP", scale=2.0)
    assert model.file_to_local(130, 60) == pytest.approx((40.0, 20.0))
    assert model.local_to_file(*model.file_to_local(101.5, 47.25)) == pytest.approx((101.5, 47.25))


def test_a_crop_moves_the_part_frame_and_the_map_follows(tmp_path):
    model = GDSModel(_gds(tmp_path), cell_name="TOP", crop_region=(98, 48, 132, 62))
    assert (round(model.file_to_local(100, 50)[0], 6), round(model.file_to_local(100, 50)[1], 6)) in _corners(model, (1, 0))
    assert model.local_to_file(0.0, 0.0) == pytest.approx((115.0, 55.0))   # the crop's centre
