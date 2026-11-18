"""The vector 3D renderer's solids copy the three.js geometry of the viewer: closed, wound outward, vertex for vertex,
with the viewer's boxes and materials."""

from __future__ import annotations

import math

import numpy as np
import pytest

pytest.importorskip("shapely")

from optodraw.registry import build_component  # noqa: E402
from optodraw.renderers.threejs_renderer import PageConstants  # noqa: E402
from optodraw.renderers.vector3d_solids import (  # noqa: E402
    SolidSet, box, cylinder, extruded_polygon, lathe_profile, look_of, solids_from_tree, sphere, three_box,
    torus, trs)

BUMP = [(0.0, 0.0), (1.0, 0.0), (1.0, 0.5), (0.5, 1.0), (0.0, 1.2)]       # from the axis to the axis
WASHER = [(1.0, -0.5), (2.0, -0.5), (2.0, 0.5), (1.0, 0.5), (1.0, -0.5)]  # a loop, counter-clockwise
GEOS = {
    "box": {"shape": "box", "width": 2.0, "height": 3.0, "depth": 4.0},
    "cylinder": {"shape": "cylinder", "radius": 1.5, "height": 2.0},
    "sphere": {"shape": "sphere", "radius": 2.0},
    # clockwise, with a closing repeat; an L with a 2 x 1 hole wound the same way
    "extruded_polygon": {"shape": "extruded_polygon", "height": 0.5,
                         "points": [(0, 0), (0, 5), (2, 5), (2, 2), (6, 2), (6, 0), (0, 0)],
                         "holes": [[(3, 0.5), (3, 1.5), (5, 1.5), (5, 0.5)]]},
    "torus": {"shape": "torus", "radius": 3.0, "tube": 0.5},
    "lathe_profile": {"shape": "lathe_profile", "points": BUMP},
    # given clockwise: the lathe still faces out
    "lathe_loop": {"shape": "lathe_profile", "points": WASHER[::-1], "segments": 24},
}
KIND = {"box": box, "cylinder": cylinder, "sphere": sphere, "extruded_polygon": extruded_polygon, "torus": torus,
        "lathe_profile": lathe_profile, "lathe_loop": lathe_profile}


def _gon(r: float) -> float:
    """The area of a regular 32-gon with circumradius r."""

    return 16 * r * r * math.sin(2 * math.pi / 32)


def _revolved_volume(profile, sides: int) -> float:
    """A counter-clockwise profile (radius, height) turned in flat sides: a frustum of n-gons under each edge."""

    p = np.asarray(profile, float)
    unit = sides / 2 * math.sin(2 * math.pi / sides)          # the n-gon of circumradius 1
    return float(sum((p[j + 1, 1] - p[j, 1]) / 3 * unit * (p[j, 0] ** 2 + p[j, 0] * p[j + 1, 0] + p[j + 1, 0] ** 2)
                     for j in range(len(p) - 1)))


_V = 2 * math.pi * np.arange(19) / 18
TORUS_PROFILE = np.column_stack((3.0 + 0.5 * np.cos(_V), 0.5 * np.sin(_V)))   # the tube's 18-gon, about z


def _sphere_volume(r: float) -> float:
    """The 32 x 32 polyhedron: a frustum of 32-gons between each two rings of latitude."""

    theta = math.pi * np.arange(33) / 32
    rho, y = r * np.sin(theta), r * np.cos(theta)
    return float(sum((y[i] - y[i + 1]) / 3 * _gon(1.0) * (rho[i] ** 2 + rho[i] * rho[i + 1] + rho[i + 1] ** 2)
                     for i in range(32)))


VOLUME = {"box": 24.0, "cylinder": _gon(1.5) * 2.0, "sphere": _sphere_volume(2.0),
          "extruded_polygon": (6 * 2 + 2 * 3 - 2 * 1) * 0.5, "torus": _revolved_volume(TORUS_PROFILE, 96),
          "lathe_profile": _revolved_volume(BUMP, 24), "lathe_loop": _revolved_volume(WASHER, 24)}


def _vector_area(ring: np.ndarray) -> np.ndarray:
    return 0.5 * np.cross(ring, np.roll(ring, -1, axis=0)).sum(axis=0)


def _constants() -> PageConstants:
    return PageConstants(beam_plane=30.0, board_top=0.0, chip_z=2.5, chip_lift=0.0, mixed=False, on_chip=True,
                         lift_meshes=False, show_grid=True, show_chip_base=True, has_user_die=False, lead_height=2.2)


def _assert_closed(faces, volume: float, name: str) -> None:
    total, enclosed = np.zeros(3), 0.0
    for face in faces:
        area = _vector_area(face.ring) + sum((_vector_area(h) for h in face.holes), np.zeros(3))
        assert area @ face.normal == pytest.approx(np.linalg.norm(area), rel=1e-9), f"{name}: a face winds inward"
        total += area
        enclosed += float(face.ring[0] @ area) / 3
    assert np.abs(total).max() < 1e-9, f"{name}: open, the vector areas sum to {total}"
    assert enclosed == pytest.approx(volume, rel=1e-9), name


@pytest.mark.parametrize("name", sorted(GEOS))
def test_each_kind_is_closed_and_wound_outward(name):
    # mutants: flip one facet's winding; for the torus and the lathes, take the profile normal as (-dh, dr)
    _assert_closed(KIND[name](GEOS[name]), VOLUME[name], name)
    # a turned and mirrored part (a flipped anchor) keeps its faces wound outward
    out = SolidSet(constants=_constants())
    matrix = trs((1.0, 2.0, 3.0), (0.3, -0.7, 1.1), (-1.0, 1.0, 1.0))
    solids_from_tree(GEOS[name], matrix, part="p", chip=False, catalog={}, out=out)
    _assert_closed(out.faces, VOLUME[name], f"{name}, mirrored")


def _vertices(points) -> np.ndarray:
    return np.unique(np.round(np.asarray(points, float), 9) + 0.0, axis=0)


def test_three_box_of_a_turned_cylinder_takes_the_eight_corners_not_the_vertices():
    faces = cylinder({"shape": "cylinder", "radius": 1.0, "height": 4.0})
    lo, hi = three_box(faces, trs(rotation=(0.0, math.pi / 4, 0.0)))
    # the local box [-1, 1] x [-2, 2] x [-1, 1] turned 45 degrees about y reaches sqrt(2); its vertices reach only 1
    np.testing.assert_allclose(hi, (math.sqrt(2), 2.0, math.sqrt(2)), atol=1e-12)
    np.testing.assert_allclose(lo, (-math.sqrt(2), -2.0, -math.sqrt(2)), atol=1e-12)


def test_look_of_merges_the_preset_under_the_record():
    catalog = {"gold": {"color": "#d4af37", "metalness": 1.0, "roughness": 0.22, "physical": "#ffe29b"},
               "glass": {"color": "#d8eef7", "opacity": 0.42, "transmission": 0.9, "clearcoat": 0.3}}
    gold = look_of({"preset": "gold", "color": "#AA0000", "roughness": 0.5}, catalog)
    assert (gold.color, gold.metalness, gold.roughness) == ("#ffe29b", 1.0, 0.5)   # physical at metalness >= 0.9
    painted = look_of({"preset": "gold", "color": "#AA0000", "metalness": 0.5}, catalog)
    assert (painted.color, painted.metalness, painted.roughness) == ("#aa0000", 0.5, 0.22)
    glass = look_of({"preset": "glass"}, catalog)
    assert (glass.opacity, glass.transmission, glass.clearcoat, glass.clear) == (0.42, 0.9, 0.3, True)
    plain = look_of({}, catalog)
    assert (plain.color, plain.opacity, plain.metalness, plain.roughness, plain.clear) == ("#ffffff", 1.0, 0.0, 1.0, False)
    assert look_of({"preset": "unknown", "color": "#123"}, catalog).color == "#112233"


def test_lathe_and_torus_vertices_follow_the_three_js_formulas():
    # mutant: start phi or u at a half step
    # LatheGeometry: phi = 2 pi i / segments from 0, vertex (x sin phi, y, x cos phi)
    want = [(x * math.sin(2 * math.pi * i / 24), y, x * math.cos(2 * math.pi * i / 24)) for i in range(24) for x, y in BUMP]
    got = np.vstack([f.ring for f in lathe_profile(GEOS["lathe_profile"])])
    np.testing.assert_allclose(_vertices(got), _vertices(want), atol=1e-9)
    # TorusGeometry(R, r, 18, 96): u = 2 pi i / 96, v = 2 pi j / 18, vertex ((R + r cos v) cos u, (R + r cos v) sin u, r sin v)
    want = [((3.0 + 0.5 * math.cos(v)) * math.cos(u), (3.0 + 0.5 * math.cos(v)) * math.sin(u), 0.5 * math.sin(v))
            for u in 2 * math.pi * np.arange(96) / 96 for v in 2 * math.pi * np.arange(18) / 18]
    got = np.vstack([f.ring for f in torus(GEOS["torus"])])
    np.testing.assert_allclose(_vertices(got), _vertices(want), atol=1e-9)


def _paired(faces) -> bool:
    """Each facet has a twin with the same corners and the opposite normal."""

    keys = {}
    for f in faces:
        keys.setdefault(tuple(map(tuple, _vertices(f.ring))), []).append(f.normal)
    return all(len(n) == 2 and np.allclose(n[0], -n[1]) for n in keys.values())


def test_an_open_lathe_shows_both_sides_and_the_retroreflector_its_inside():
    # mutant: close the lathe (no back facets): from its open base the cone then shows nothing
    out = SolidSet(constants=_constants())
    solids_from_tree(build_component("Retroreflector").geometry_3d(), np.eye(4), part="r", chip=False, catalog={},
                     out=out)
    (cone,) = [s for s in out.solids if not s.closed]
    assert cone.kind == "lathe_profile"
    faces = [f for f in out.faces if f.solid == cone.id]
    assert len(faces) == 6 and _paired(faces)                 # 3 sides, each from outside and from inside
    # the cone turns its axis to +x, so its open base looks along -x: from there only the inside shows
    seen = [f for f in faces if f.normal @ (-1.0, 0.0, 0.0) > 0]
    assert len(seen) == 3 and all(f.surface[-1] == "back" for f in seen)


def test_decal_glyphs_lie_on_the_plane_centred_and_turn_with_the_part():
    # mutant: skip the part's matrix (the glyphs stay flat at the origin)
    decal = {"shape": "text_decal", "text": "ADC", "width": 4.0, "height": 2.0, "position": [0.0, 0.56, 0.0],
             "rotation": [-math.pi / 2, 0.0, 0.0], "color": "#f00"}
    part = {"shape": "group", "position": [1.0, 2.0, 3.0], "rotation": [0.0, math.pi / 2, 0.0], "children": [decal]}
    out = SolidSet(constants=_constants())
    solids_from_tree(part, np.eye(4), part="p", chip=False, catalog={}, out=out)
    (solid,) = out.solids
    assert (solid.kind, solid.closed, out.faces) == ("text_decal", False, [])   # the plane is clear but for its text
    (glyphs,) = out.decals
    assert glyphs.color == "#ff0000" and glyphs.solid == solid.id
    pts = np.vstack(glyphs.rings)
    # flat on top at y = 2.56; the part's quarter turn runs the text's width along z and its height along x
    np.testing.assert_allclose(pts[:, 1], 2.56, atol=1e-12)
    lo, hi = pts.min(axis=0), pts.max(axis=0)
    assert np.all(np.abs(pts[:, 0] - 1.0) <= 1.0) and np.all(np.abs(pts[:, 2] - 3.0) <= 2.0)
    np.testing.assert_allclose(((lo + hi) / 2)[[0, 2]], (1.0, 3.0), atol=1e-9)
    assert hi[2] - lo[2] > hi[0] - lo[0]
    # the canvas clips a text wider than the plane
    out = SolidSet(constants=_constants())
    solids_from_tree({**decal, "text": "WWWWWWWWWW", "fontSize": 230}, np.eye(4), part="p", chip=False, catalog={},
                     out=out)
    pts = np.vstack(out.decals[0].rings)
    assert 1.5 < np.abs(pts[:, 0]).max() <= 2.0 + 1e-12 and np.abs(pts[:, 2]).max() <= 1.0


def test_a_hole_grid_top_gives_the_canvas_hole_layout():
    # mutant: Math.round in place of Math.floor for the columns (9 in place of 8)
    plate = {"shape": "box", "width": 20.0, "height": 1.0, "depth": 10.0, "position": [5.0, 0.0, 0.0],
             "material": {"color": "#888888", "metalness": 0.5},
             "top_texture": {"kind": "hole_grid", "length": 20.0, "width": 10.0, "pitch": 2.5, "margin": 0.5,
                             "hole_r": 0.4, "base": "#aabbcc", "side": "#112233"}}
    out = SolidSet(constants=_constants())
    solids_from_tree(plate, np.eye(4), part="b", chip=False, catalog={}, out=out)
    (grid,) = out.hole_grids
    # odHolePlateTexture: cols = floor((20 - 2 * 0.5) / 2.5) + 1 = 8, rows = floor((10 - 1) / 2.5) + 1 = 4, centred
    want = [(5.0 - 8.75 + 2.5 * c, 0.5, -3.75 + 2.5 * r) for c in range(8) for r in range(4)]
    np.testing.assert_allclose(_vertices(grid.centres), _vertices(want), atol=1e-9)
    np.testing.assert_allclose(grid.axes, [(0.4, 0.0, 0.0), (0.0, 0.0, 0.4)], atol=1e-12)
    (top,) = [f for f in out.faces if f.surface == grid.surface]
    np.testing.assert_allclose(top.normal, (0.0, 1.0, 0.0), atol=1e-12)
    look = out.solids[grid.solid].look
    assert (grid.top.color, grid.top.metalness, look.color, look.metalness) == ("#aabbcc", 0.5, "#112233", 0.5)


PART_KINDS = {"ADC": "text_decal", "DACDriver": "text_decal", "TIA": "text_decal", "Cryostat": "torus",
              "Periscope": "lathe_profile", "FiberCoupler": "tube_path"}


