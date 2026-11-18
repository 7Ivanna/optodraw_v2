"""The vector 3D renderer and the three.js viewer show the same solids, part by part and scene by scene
(Acceptance 2).

Each catalog part with solids, alone in its scene, is drawn by both sides in flat id colours, one colour per solid,
through the renderer's camera, in parallel and in perspective. The viewer's mesh count must equal the solid count,
its material table must equal each solid's look, and the pictures must have no patch of wrong colour. The harness is
``tests/viewer_flat.py``. The auto die and carrier stay off for single parts (``show_chip_base=False``, as the parts
gallery shows one part); the scene tests draw them, with mounts, beams, strips and cables.

Wall time, estimated before the first run (replace it with the measured time): about 2 min for the 169 parts and
the scenes, and under 5 min without the process pool. The estimate, part by part:

- Chrome: about 6 page loads for the parts (on-chip, the user die, free space, one per board thickness) and 8 for the
  scenes and home poses, each 3.6 to 4.8 s as measured for one viewer capture: about 60 s. 174 rebuilds, each with
  two renders and two PNGs of 1000 px width, about 0.2 s each (a guess): 35 s.
- Renderer: the parts have about 137,000 faces and the five scenes about 68,000. The hidden step took 0.67 s per
  1,000 faces for both projections, measured at a load of 28.5: about 140 s serial, about 25 s on 6 workers. 348
  cairosvg rasters at about 0.1 s each (a guess): 6 s on the pool.
- Main thread: the catalog census, then 174 scenes, solid sets and page data, about 0.1 s each (a guess): 20 s.

The pool works while Chrome works, so the wall time is about the main thread plus Chrome plus the end of the pool.
The mutant tests add about 10 s."""

from __future__ import annotations

import functools
import json

import numpy as np
import pytest

pytest.importorskip("shapely")
pytest.importorskip("PIL")

import viewer_flat  # noqa: E402

from optodraw import (Beam, Breadboard, CustomModel, Laser, Lens, Objective, OnChipPhotodetector,  # noqa: E402
                      PartLibrary, Scene, VerticalGratingCoupler, define_part)
from optodraw.core.view_layout import display_scene  # noqa: E402
from optodraw.registry import build_component  # noqa: E402
from optodraw.renderers.capture3d import find_chrome  # noqa: E402
from optodraw.renderers.threejs_renderer import ThreeJsRenderer  # noqa: E402
from optodraw.renderers.vector3d_scene import home_pose, scene_solids  # noqa: E402
from optodraw.renderers.vector3d_solids import Vector3DError, box_union  # noqa: E402

needs_chrome = pytest.mark.skipif(find_chrome(required=False) is None, reason="needs Chrome, Chromium or Edge")

OPTIONS = {"show_chip_base": False}
MUTANT_PART = "Objective"
HOME_CAPTURE = {**viewer_flat.CAPTURE, "width": 160, "height": 100}     # the 1.6 aspect of render_3d_image


@functools.cache
def solid_parts() -> tuple[str, ...]:
    """The catalog parts that build with no arguments and have a 3D tree."""

    from optodraw.catalog import list_components

    solid = []
    for name in list_components():
        try:
            part = build_component(name)
            tree = part.geometry_3d()
        except Exception:
            continue
        if tree:
            solid.append(name)
    return tuple(solid)


def _scene(name: str) -> Scene:
    scene = Scene()
    scene.add(build_component(name))
    return scene


def _bench() -> Scene:
    """The spike bench: a laser, an objective on its post_at mount, the beam between them."""

    scene = Scene(title="Bench", width=120, height=50, platform="free_space")
    laser = scene.add(Laser(center=(-34, 0), wavelength=633, label="Laser"))
    objective = scene.add(Objective(center=(24, 0), label="Objective"))
    scene.add(Beam.through(laser, objective, wavelength=633))
    return scene


def _mounts() -> Scene:
    """One part per base_mount on a breadboard, each turned by its own yaw."""

    scene = Scene(title="Mounts")
    scene.add(Breadboard(center=(0, 0)))
    for i, mount in enumerate(("post", "post_beam", "stage", "xyz_stage", "rotation_stage", "none")):
        part = scene.add(build_component("Mirror" if i % 2 else "Lens", center=(-50 + 20 * i, 10 * (i % 2)),
                                         angle=30 * i))
        part.base_mount = mount
    return scene


def _cables() -> Scene:
    """A fibre and an electrical cable, each rising to a connector on a post at one end."""

    scene = Scene(title="Cables", width=160, height=60)
    collimator = scene.add(build_component("FiberCollimator", center=(-50, 0), angle=180))
    spool = scene.add(build_component("FiberSpool", center=(30, 0)))
    scene.route((collimator, "in"), (spool, "in"), kind="fiber")
    detector = scene.add(build_component("Photodiode", center=(-50, 40)))
    scope = scene.add(build_component("Oscilloscope", center=(40, 40)))
    scene.route((detector, "in"), (scope, "ch1"), kind="electrical")
    return scene


def _chip() -> Scene:
    """A chip with waveguide and metal strips, on its die and carrier."""

    scene = Scene(title="Chip", platform="on_chip")
    left = scene.add(build_component("VerticalGratingCoupler", center=(-150, 0)))
    mzi = scene.add(build_component("MZI", center=(0, 0)))
    right = scene.add(build_component("VerticalGratingCoupler", center=(150, 0), angle=180))
    scene.route((left, "o1"), (mzi, "o1"), kind="waveguide")
    scene.route((mzi, "o2"), (right, "o1"), kind="waveguide")
    a = scene.add(build_component("ElectricalPad", center=(-40, 60)))
    b = scene.add(build_component("ElectricalPad", center=(40, 80)))
    scene.route((a, "e1"), (b, "e1"), kind="electrical")
    return scene


def _mixed() -> Scene:
    """A chip on a bench (MIXED, CHIP_LIFT): beams onto the chip, and cables that drop onto it, one of them rising
    from a part on a post."""

    scene = Scene(title="Chip on a bench")
    laser = scene.add(Laser(center=(-80, 0)))
    lens = scene.add(Lens(center=(-40, 0)))
    coupler = scene.add(VerticalGratingCoupler(center=(0, 0)))
    detector = scene.add(OnChipPhotodetector(center=(-10, 30)))
    scene.add(Beam((laser, "out"), (lens, "in")))
    scene.add(Beam((lens, "out"), (coupler, "f1")))
    scope = scene.add(build_component("Oscilloscope", center=(-70, 60)))
    scene.route((scope, "ch1"), (detector, "e1"), kind="electrical")
    collimator = scene.add(build_component("FiberCollimator", center=(60, 30), angle=180))
    scene.route((collimator, "in"), (coupler, "f1"), kind="fiber")
    return scene


# shortcut: the spike chip through a GDSModel waits for tests/fixtures/spike_ring.gds (Part B task 7); add it then
SCENES = {"bench": _bench, "mounts": _mounts, "cables": _cables, "chip": _chip, "mixed": _mixed}


@pytest.fixture(scope="module")
def viewer(rasteriser):
    with viewer_flat.Viewer() as session:
        yield session


@pytest.fixture(scope="module")
def mutant_base(viewer):
    """The mutant part, which must match the viewer, and its largest visible solid."""

    scene = _scene(MUTANT_PART)
    result = viewer_flat.compare(viewer, {MUTANT_PART: scene}, renderer_options=OPTIONS)[0]
    assert result.ok, result.report()
    areas = result.areas.values()
    largest = max({i for area in areas for i in area}, key=lambda i: sum(area.get(i, 0) for area in areas))
    return scene, largest


def test_frames_put_each_point_where_the_renderer_draws_it():
    solids = scene_solids(_scene(MUTANT_PART), renderer_options=OPTIONS)
    points = np.vstack([f.ring for f in solids.faces])
    for projection in viewer_flat.PROJECTIONS:
        frame = viewer_flat.frame_for(solids, projection)
        view = frame.view()
        world = np.array(view["world"]).reshape(4, 4)
        clip = (np.array(view["projection"]).reshape(4, 4) @ np.linalg.inv(world)
                @ np.column_stack((points, np.ones(len(points)))).T)
        ndc = clip[:3] / clip[3]
        page = np.column_stack(((ndc[0] + 1) / 2 * frame.width_mm, (1 - ndc[1]) / 2 * frame.height_mm))
        assert np.allclose(page, frame.camera.page(points), rtol=0, atol=1e-9), projection
        assert (np.abs(ndc[2]) < 1).all(), f"{projection}: a point outside the near and far planes"


@needs_chrome
def test_catalog_matches_viewer(viewer):
    # mutant: drop the 0.15 above the part from the post top in vector3d_scene._mount_for; each part on a post fails
    names = solid_parts()
    results = viewer_flat.compare(viewer, {name: _scene(name) for name in names}, renderer_options=OPTIONS)
    failed = [result.report() for result in results if not result.ok]
    assert not failed, f"{len(failed)} of {len(results)} parts differ from the viewer:\n" + "\n".join(failed)


@needs_chrome
def test_scenes_match_viewer(viewer):
    # mutant: skip the climb at the die edge in vector3d_scene.cable_solids (footprint_entry returns None); the
    # cables of the mixed scene then move and the scene fails
    results = viewer_flat.compare(viewer, {name: build() for name, build in SCENES.items()})
    failed = [result.report() for result in results if not result.ok]
    assert not failed, f"{len(failed)} of {len(results)} scenes differ from the viewer:\n" + "\n".join(failed)


@needs_chrome
def test_home_pose_matches_viewer(viewer):
    # mutant: leave out centre_on in vector3d_scene.home_pose (the eye at forward * away); every scene fails
    for name in ("bench", "chip", "mixed"):
        scene = SCENES[name]()
        page = ThreeJsRenderer(display_scene(scene, "3d"), capture=HOME_CAPTURE, world="light").render()
        viewer.load(("home", name), lambda page=page: page)
        home = json.loads(viewer._evaluate(
            "JSON.stringify({pos: window.__odHome.pos.toArray(), target: window.__odHome.target.toArray()})"))
        solids = scene_solids(scene)
        eye, target = home_pose(solids, "isometric", aspect=1.6, fill=0.9)     # a capture frames at 0.9
        lo, hi = box_union(solids.boxes)
        tol = 1e-6 * float(np.linalg.norm(hi - lo))
        assert np.abs(eye - home["pos"]).max() <= tol, f"{name}: eye {eye}, viewer {home['pos']}"
        assert np.abs(target - home["target"]).max() <= tol, f"{name}: target {target}, viewer {home['target']}"


OUTLINE = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="-10 -5 20 10">'
           '<path d="M-10 0Q0 -10 10 0Q0 10 -10 0Z" fill="black"/></svg>')


def test_out_of_scope_parts_raise():
    # mutant: return None from vector3d_scene._refusal, so scene_solids skips what it cannot draw
    model = Scene()
    model.add(CustomModel("arm.glb", label="Arm"))
    user = Scene()
    user.add(define_part("user:example/Outline", platform="on_chip", ports=[], symbol_2d=OUTLINE,
                         library=PartLibrary())())
    cases = [(model, r"CustomModel 'Arm': .*external_model.*render_3d_image"),
             (user, r"UserPart .*svg_extrusion.*render_3d_image")]
    for scene, pattern in cases:
        with pytest.raises(Vector3DError, match=pattern):
            scene_solids(scene)


@needs_chrome
def test_missing_solid_fails(viewer, mutant_base):
    scene, solid = mutant_base
    result = viewer_flat.compare(viewer, {MUTANT_PART: scene}, renderer_options=OPTIONS,
                                 mutate=functools.partial(viewer_flat.without_solid, solid=solid))[0]
    for projection in viewer_flat.PROJECTIONS:
        assert solid in result.wrong[projection], f"solid {solid} removed, no patch on it:\n{result.report()}"


@needs_chrome
def test_moved_solid_fails(viewer, mutant_base):
    scene, solid = mutant_base
    result = viewer_flat.compare(viewer, {MUTANT_PART: scene}, renderer_options=OPTIONS,
                                 mutate=functools.partial(viewer_flat.moved_solid, solid=solid, offset=(1.0, 0, 0)))[0]
    for projection in viewer_flat.PROJECTIONS:
        assert solid in result.wrong[projection], f"solid {solid} moved by 1 unit, no patch on it:\n{result.report()}"
