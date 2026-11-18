"""Hidden surfaces of the vector 3D renderer: the near face wins, crossing faces split on their line, clear faces hide
nothing, slivers go, perspective depth is a plane on the page, and covered() answers for any point."""

from __future__ import annotations

import math

import numpy as np
import pytest

pytest.importorskip("shapely")

from optodraw.renderers.threejs_renderer import PageConstants  # noqa: E402
from optodraw.renderers.vector3d_hidden import Camera, camera_for, clip_lines, covered, visible  # noqa: E402
from optodraw.renderers.vector3d_solids import Face, Look, Solid, SolidSet, solids_from_tree  # noqa: E402

# looking down -z from z = 50: a world point (x, y, z) lands at (x, -y) mm on the page
TOP = Camera(eye=np.array([0.0, 0.0, 50.0]), target=np.zeros(3), perspective=False)
CLOSE_MM = 6e-4


def _solid(sid: int, opacity: float = 1.0) -> Solid:
    return Solid(id=sid, part=f"p{sid}", kind="box", look=Look("#888888", opacity=opacity), closed=True, chip=False)


def _quad(x0, y0, x1, y1, solid: int, z=0.0, slope=0.0) -> Face:
    """A rectangle in the plane z = z + slope * (x - 5), facing +z."""

    ring = np.array([(x, y, z + slope * (x - 5)) for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))], float)
    normal = np.array([-slope, 0.0, 1.0]) / math.hypot(slope, 1.0)
    return Face(ring, (), normal, solid, (solid,), "flat")


def _areas(shown) -> dict[int, float]:
    out: dict[int, float] = {}
    for face, geom in shown:
        out[face] = out.get(face, 0.0) + geom.area
    return out


def test_the_far_square_loses_exactly_the_near_ones_projection():
    faces = [_quad(2, 2, 6, 6, 0, z=1.0), _quad(0, 0, 10, 10, 1)]
    shown = visible(faces, [_solid(0), _solid(1)], TOP)
    areas = _areas(shown.pieces)
    assert areas[0] == pytest.approx(16.0, abs=1e-6)
    assert areas[1] == pytest.approx(100.0 - (4 + 2 * CLOSE_MM) ** 2, abs=1e-3)


def test_two_crossing_faces_each_keep_the_half_where_they_are_nearer():
    # the first is nearer where x > 5, the second where x < 5
    faces = [_quad(0, 0, 10, 10, 0, slope=0.1), _quad(0, 0, 10, 10, 1, slope=-0.1)]
    shown = visible(faces, [_solid(0), _solid(1)], TOP)
    pieces = dict(shown.pieces)
    for face, centre in ((0, 7.5), (1, 2.5)):
        assert pieces[face].area == pytest.approx(50.0, abs=0.02)
        assert pieces[face].centroid.x == pytest.approx(centre, abs=0.01)


def test_on_one_plane_the_later_face_wins():
    faces = [_quad(0, 0, 6, 4, 0), _quad(4, 0, 10, 4, 1)]
    areas = _areas(visible(faces, [_solid(0), _solid(1)], TOP).pieces)
    assert areas[1] == pytest.approx(24.0, abs=1e-6)
    assert areas[0] == pytest.approx(16.0, abs=0.01)


def test_a_clear_face_hides_nothing_and_is_cut_where_an_opaque_face_lies_in_front():
    # the opaque face is nearer where x < 5, the clear one where x > 5
    faces = [_quad(0, 0, 10, 10, 0, slope=-0.1), _quad(0, 0, 10, 10, 1, slope=0.1)]
    shown = visible(faces, [_solid(0), _solid(1, opacity=0.4)], TOP)
    assert _areas(shown.pieces) == pytest.approx({0: 100.0}, abs=1e-6)
    (face, piece), = shown.clear
    assert face == 1
    assert piece.area == pytest.approx(50.0, abs=0.02)
    assert piece.centroid.x == pytest.approx(7.5, abs=0.01)


def test_a_hairline_closes_a_thin_piece_goes_and_a_10_um_piece_stays():
    # near strips over a far band leave gaps of 0.4 um, 2 um and 10 um
    near = [(0.0, 40.0), (40.0004, 60.0), (60.002, 80.0), (80.010, 100.0)]
    faces = [_quad(0, 0, 100, 20, 0)] + [_quad(x0, 0, x1, 20, 1, z=1.0) for x0, x1 in near]
    shown = visible(faces, [_solid(0), _solid(1)], TOP)
    left = [geom for face, geom in shown.pieces if face == 0]
    assert len(left) == 1 and left[0].geom_type == "Polygon", left
    x0, _, x1, _ = left[0].bounds
    assert (x0, x1) == (pytest.approx(80.0006, abs=2e-4), pytest.approx(80.0094, abs=2e-4))
    assert left[0].area == pytest.approx(0.0088 * 20, rel=0.03)


def test_perspective_depth_is_a_plane_on_the_page():
    rng = np.random.default_rng(11)
    camera = Camera(eye=np.array([30.0, 22.0, 41.0]), target=np.array([1.0, -2.0, 0.5]), perspective=True, k=7.5,
                    origin=(3.0, 4.0))
    for _ in range(5):
        base = rng.uniform(-3, 3, 3)
        u, v = rng.normal(size=3), rng.normal(size=3)
        points = base + rng.uniform(-4, 4, (200, 1)) * u + rng.uniform(-4, 4, (200, 1)) * v
        page, depth = camera.page(points), camera.depth(points)
        rows = np.column_stack((page, np.ones(len(page))))
        fit = np.linalg.lstsq(rows, depth, rcond=None)[0]
        assert np.abs(rows @ fit - depth).max() < 1e-9 * np.abs(depth).max()


def _chip() -> tuple[SolidSet, Camera]:
    tree = {"shape": "group", "children": [
        {"shape": "box", "width": 10, "height": 0.22, "depth": 10, "position": [0, 0.11, 0], "material": {"preset": "si"}},
        {"shape": "box", "width": 10, "height": 2.0, "depth": 10, "position": [0, 1.0, 0], "material": {"preset": "oxide"}},
        {"shape": "box", "width": 4, "height": 0.5, "depth": 4, "position": [0, 1.75, 0], "material": {"preset": "pad"}},
    ]}
    catalog = {"si": {"color": "#6f747a"}, "oxide": {"color": "#d8eef7", "opacity": 0.42}, "pad": {"color": "#d4af37"}}
    out = SolidSet(constants=PageConstants(beam_plane=30.0, board_top=0.0, chip_z=1.0, chip_lift=0.0, mixed=False,
                                           on_chip=True, lift_meshes=False, show_grid=True, show_chip_base=True,
                                           has_user_die=False, lead_height=2.2))
    solids_from_tree(tree, np.eye(4), part="chip", chip=True, catalog=catalog, out=out)
    camera, _ = camera_for(out, "isometric", "perspective", 120.0)
    return out, camera


def test_covered_hides_a_point_under_a_pad_but_not_on_its_top_nor_in_clear_cladding():
    solids, camera = _chip()
    shown = visible(solids.faces, solids.solids, camera)
    tol = 1e-4 * math.sqrt(10 ** 2 + 2 ** 2 + 10 ** 2)
    assert covered(shown, camera, (0.0, 1.0, 0.0), tol=tol)              # under the pad, inside the cladding
    assert not covered(shown, camera, (0.0, 2.0, 0.0), tol=tol)          # on the pad top
    assert not covered(shown, camera, (4.0, 1.0, 4.0), tol=tol)          # in the clear cladding, beside the pad


def test_clip_lines_cuts_a_segment_where_a_face_lies_in_front():
    faces = [_quad(2, 2, 6, 6, 0, z=1.0), _quad(0, 0, 10, 10, 1)]
    shown = visible(faces, [_solid(0), _solid(1)], TOP)
    lines = clip_lines([np.array([(0.0, 4.0, 0.5), (10.0, 4.0, 0.5)])], shown, TOP)
    assert len(lines.geoms) == 2
    assert lines.length == pytest.approx(6.0, abs=1e-6)


def test_clip_lines_cuts_a_slanted_segment_by_the_exact_span():
    # mutant: cut the line with shapely.difference(line, hidden spans); near-collinear lines then keep the whole line
    faces = [_quad(2, 2, 6, 6, 0, z=1.0), _quad(-1, -1, 11, 11, 1)]
    shown = visible(faces, [_solid(0), _solid(1)], TOP)
    lines = clip_lines([np.array([(0.0, 0.3, 0.5), (10.0, 7.3, 0.5)])], shown, TOP)
    # the near square lies over the line where x is in [2, 6] and y = 0.3 + 0.7 x is in [2, 6]: x in [17 / 7, 6]
    slant = math.hypot(1.0, 0.7)
    assert sorted(g.length for g in lines.geoms) == pytest.approx([17 / 7 * slant, 4 * slant], abs=1e-6)
