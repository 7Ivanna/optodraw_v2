"""The studio drawing of the vector 3D renderer: one path per surface, a gradient across a surface of revolution,
the same bytes each time, light that reads every material key, glow bands in the hidden cut, hole grids as one
path, vector shadows on their receiver, and the scale guard."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import replace

import numpy as np
import pytest

shapely = pytest.importorskip("shapely")

from optodraw import Scene  # noqa: E402
from optodraw.registry import build_component  # noqa: E402
from optodraw.renderers.threejs_renderer import PageConstants  # noqa: E402
from optodraw.renderers.vector3d import SHADOW_INK, Vector3DError, draw, frame, render_3d_svg  # noqa: E402
from optodraw.renderers.vector3d_hidden import Camera, camera_for  # noqa: E402
from optodraw.renderers.vector3d_solids import (  # noqa: E402
    Band, Look, SolidSet, add_solid, box, solids_from_tree, trs)

CYLINDER = {"shape": "cylinder", "radius": 1.0, "height": 2.0,
            "material": {"color": "#8a9099", "metalness": 0.5, "roughness": 0.3}}
CUBE = {"shape": "box", "width": 2.0, "height": 2.0, "depth": 2.0, "material": {"color": "#8a9099"}}
# looking down -z from z = 50: a world point (x, y, z) lands at (x, -y) mm on the page
TOP = Camera(eye=np.array([0.0, 0.0, 50.0]), target=np.zeros(3), perspective=False)


def _constants() -> PageConstants:
    return PageConstants(beam_plane=30.0, board_top=0.0, chip_z=2.5, chip_lift=0.0, mixed=False, on_chip=False,
                         lift_meshes=False, show_grid=True, show_chip_base=True, has_user_die=False, lead_height=2.2)


def _solids(tree: dict) -> SolidSet:
    out = SolidSet(constants=_constants())
    solids_from_tree(tree, np.eye(4), part="p", chip=False, catalog={}, out=out)
    return out


def _isometric(solids: SolidSet, width_mm: float = 60.0) -> Camera:
    return camera_for(solids, "isometric", "parallel", width_mm)[0]


def _stops(root, fill: str) -> list:
    (gradient,) = [g for g in root.iter("linearGradient") if f"url(#{g.get('id')})" == fill]
    return list(gradient.iter("stop"))


def _region(d: str) -> shapely.Geometry:
    rings = [[tuple(float(v) for v in point.split()) for point in part.rstrip("Z").split("L")]
             for part in d.split("M")[1:]]
    return shapely.union_all([shapely.Polygon(ring) for ring in rings])


def test_two_renders_give_the_same_bytes():
    # mutant: name each gradient by id() of its stops in place of a count from 1
    scene = Scene()
    scene.add(build_component("Lens"))
    first = render_3d_svg(scene, width_mm=60.0)
    assert 'id="g1"' in first
    assert render_3d_svg(scene, width_mm=60.0) == first


def test_line_has_no_gradient_and_the_default_studio_has_gradients():
    # mutant: draw ignores style (both styles give one drawing)
    solids = _solids(CYLINDER)
    camera = _isometric(solids)
    assert "<linearGradient" not in draw(solids, camera, style="line")
    assert "<linearGradient" in draw(solids, camera, style="studio")
    assert draw(solids, camera) == draw(solids, camera, style="studio")


@pytest.mark.parametrize("key, low, high", [("metalness", 0.1, 0.8), ("roughness", 0.15, 0.85),
                                            ("clearcoat", 0.0, 1.0), ("transmission", 0.2, 0.9)])
def test_each_material_key_changes_the_colour_of_a_face(key, low, high):
    # mutant: drop one key from Studio.shade (read it as 0)
    base = Look("#7f8c99", metalness=0.3, roughness=0.5)

    def colours(value: float) -> list[str]:
        out = SolidSet(constants=_constants())
        add_solid(out, box({"width": 2.0, "height": 2.0, "depth": 2.0}), np.eye(4), part="p", kind="box",
                  look=replace(base, **{key: value}))
        text = draw(out, _isometric(out))
        return re.findall(r'(?:fill|stop-color)="(#[0-9a-f]{6})"', text)

    assert colours(low) != colours(high)


def test_a_box_between_the_camera_and_a_beam_cuts_its_band():
    # mutant: leave the bands out of the hidden cut (draw each band's whole quad)
    out = SolidSet(constants=_constants())
    add_solid(out, box({"width": 4.0, "height": 6.0, "depth": 1.0}), trs((0.0, 0.0, 5.0)), part="block", kind="box",
              look=Look("#555555"))
    out.bands.append(Band("beam1", np.array([-10.0, 0.0, 0.0]), np.array([10.0, 0.0, 0.0]), (2.0, 2.0), "#ff2000"))
    root = ET.fromstring(draw(out, TOP))
    (band,) = [p for p in root.iter("path") if (p.get("fill") or "").startswith("url(")
               and any(s.get("stop-opacity") for s in _stops(root, p.get("fill")))]
    glow = _region(band.get("d"))
    assert glow.contains(shapely.Point(6.0, 0.0))            # beside the box the band shows
    assert not glow.intersects(shapely.Point(0.0, 0.0))      # the box hides its middle
    assert glow.area == pytest.approx(2.0 * (20.0 - 4.0), rel=1e-3)


def test_a_plate_gives_cols_times_rows_holes_in_one_path():
    # mutant: one path per hole in _Studio.holes
    plate = {"shape": "box", "width": 20.0, "height": 1.0, "depth": 10.0, "material": {"color": "#888888"},
             "top_texture": {"kind": "hole_grid", "length": 20.0, "width": 10.0, "pitch": 2.5, "margin": 0.5,
                             "hole_r": 0.4, "base": "#aabbcc", "side": "#112233"}}
    solids = _solids(plate)
    root = ET.fromstring(draw(solids, _isometric(solids, 80.0)))
    holes = [p for p in root.iter("path") if p.get("fill") == solids.hole_grids[0].color]
    assert len(holes) == 1
    # odHolePlateTexture: cols = floor((20 - 2 * 0.5) / 2.5) + 1 = 8, rows = floor((10 - 2 * 0.5) / 2.5) + 1 = 4
    assert holes[0].get("d").count("M") == 8 * 4


def _shadow(root) -> shapely.Geometry:
    """The union of the shadow paths, each read even-odd."""

    out = shapely.Polygon()
    for path in root.iter("path"):
        if path.get("fill") == SHADOW_INK:
            layer = shapely.Polygon()
            for part in path.get("d").split("M")[1:]:
                ring = [tuple(float(v) for v in point.split()) for point in part.rstrip("Z").split("L")]
                layer = layer.symmetric_difference(shapely.Polygon(ring))
            out = out.union(layer)
    return out


def test_a_bench_page_holds_its_floor_shadow():
    # mutant: frame() fits the solids only (camera_for with no shadow points); the shadow runs off the right edge
    out = SolidSet(constants=_constants())
    add_solid(out, box({"width": 4.0, "height": 12.0, "depth": 4.0}), trs((0.0, 6.0, 0.0)), part="tower", kind="box",
              look=Look("#555555"))
    camera, height = frame(out, "isometric", "parallel", 60.0)
    shadow = _shadow(ET.fromstring(draw(out, camera)))
    assert shadow.area > 1.0
    x0, y0, x1, y1 = shadow.bounds
    assert x0 >= 0.0 and y0 >= 0.0 and x1 <= 60.0 and y1 <= height


def test_over_the_face_limit_raises_with_the_count_and_both_ways_out():
    # mutant: remove the guard from drawn(); the view draws with no error
    solids = _solids(CUBE)
    camera = _isometric(solids)                              # 3 of the cube's 6 faces face the camera
    with pytest.raises(Vector3DError) as error:
        draw(solids, camera, face_limit=2)
    message = str(error.value)
    assert "3 faces after culling, over the limit of 2" in message
    assert "region=(x0, y0, x1, y1)" in message and "scene.render_3d_image" in message
    assert draw(solids, camera, face_limit=3).startswith('<g data-art="3d">')
