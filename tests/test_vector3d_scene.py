"""The page JS copies in vector3d_scene: mounts, the lift rules, strips, cables and the chip base. Each expected value
comes from the viewer page's own formula (ThreeJsRenderer's page JS), written out here. The viewer comparison in
tests/test_vector3d_viewer.py checks the same copies against the real viewer, pixel by pixel."""

from __future__ import annotations


import numpy as np
import pytest

pytest.importorskip("shapely")

from optodraw import Breadboard, Laser, Scene  # noqa: E402
from optodraw.components.optics.fibers import LEAD_HEIGHT  # noqa: E402
from optodraw.renderers.threejs_renderer import PageConstants  # noqa: E402
from optodraw.renderers.vector3d_scene import cable_solids, scene_solids, strip_solids  # noqa: E402
from optodraw.renderers.vector3d_solids import SolidSet  # noqa: E402

BOARD = 2.4                 # Breadboard().thickness: BOARD_TOP on its page
BEAM = 30.0                 # the default beam height


def _constants(**changes) -> PageConstants:
    base = dict(beam_plane=BEAM, board_top=0.0, chip_z=2.5, chip_lift=0.0, mixed=False, on_chip=True,
                lift_meshes=False, show_grid=True, show_chip_base=True, has_user_die=False, lead_height=LEAD_HEIGHT)
    return PageConstants(**{**base, **changes})


def _points(out: SolidSet, part: str) -> np.ndarray:
    return np.vstack([f.ring for f in out.faces if out.solids[f.solid].part == part])


def _sid(out: SolidSet, prefix: str) -> str:
    return next(s.part for s in out.solids if s.part.startswith(prefix))


def test_a_post_stands_on_the_board_and_ends_0_15_under_the_part():
    # mutant: drop the 0.15 from the post top in vector3d_scene._mount_for
    scene = Scene()
    scene.add(Breadboard(center=(0, 0)))
    scene.add(Laser(center=(-34, 0)))
    out = scene_solids(scene)
    mount = _sid(out, "mount:")
    post, laser = _points(out, mount), _points(out, mount.removeprefix("mount:"))
    # at angle 0 every turn inside the Laser is a quarter turn, so its three.js box is the box of its vertices
    assert post[:, 1].min() == pytest.approx(BOARD)
    assert post[:, 1].max() == pytest.approx(laser[:, 1].min() + 0.15)


# the meshes of each odAdd* function: base, holder, collar, post; base, top, barrel, thimble and the riser (holder,
# collar, post); the x, y and z stages, three micrometers and the riser; base, dial, 24 ticks, screw and the riser
MOUNT_MESHES = {"post": 4, "post_beam": 4, "stage": 7, "xyz_stage": 9, "rotation_stage": 30, "none": 0}


def test_a_strip_has_a_box_per_segment_and_a_filler_only_at_a_real_corner():
    # mutant: add a filler at every inner point in vector3d_scene.strip_solids (drop the 0.26 rad test)
    out = SolidSet(constants=_constants())
    item = {"sid": "r", "type": "route", "kind": "electrical", "width": 1.0,
            "points": [[0, 0, 0], [10, 0, 0], [20, 0, 0], [20, 0, -10]]}     # straight on, then a right angle
    strip_solids(item, out.constants, {}, out)
    assert [s.kind for s in out.solids] == ["strip"] * 4
    filler = _points(out, "r")[-4 * 6:]                                         # the last box: 6 faces of 4 corners
    assert filler.min(axis=0) == pytest.approx([19.5, 0.0, -0.5])
    assert filler.max(axis=0) == pytest.approx([20.5, 0.35, 0.5])               # 0.35: the metal thickness


def test_a_cable_drop_climbs_at_the_die_edge_and_never_runs_through_the_die():
    # mutant: skip the climb (footprint_entry returns None) in vector3d_scene.cable_solids
    k = _constants(on_chip=False, mixed=True, chip_lift=8.2, lift_meshes=True)
    die = (np.array([-10.0, 0.0, -10.0]), np.array([10.0, 1.0, 10.0]))
    half = 10 + 5                                            # odDieFootprint: half size plus max(5 %, 5)
    out = SolidSet(constants=k)
    cable_solids({"sid": "c", "type": "route", "kind": "fiber", "cable": True, "cableDrop": "end",
                  "points": [[-60, 0, 0], [0, 0, 0]]}, k, die, {}, out)
    tube = _points(out, "c")
    pad = 0.4 * k.chip_z + k.chip_lift                       # the drop lands just over the lifted metal
    radius = 0.4                                             # 0.22 of the default width 1, at least 0.4
    # the centripetal curve swings about 0.5 past the climb at the edge, as in the viewer: look 2 units inside
    over = (np.abs(tube[:, 0]) < half - 2) & (np.abs(tube[:, 2]) < half - 2)
    assert over.any() and tube[over, 1].min() > k.chip_lift  # over the die it rides above the die top
    assert np.linalg.norm(tube - [0.0, pad, 0.0], axis=1).min() == pytest.approx(radius)   # its open end on the pad


