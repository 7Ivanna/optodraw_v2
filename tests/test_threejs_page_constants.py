"""The page constants (BEAM_PLANE, BOARD_TOP, CHIP_Z, ...) come from one method, which the vector 3D renderer reads
too. Moving them there changed no byte of the page."""

from __future__ import annotations

import hashlib

import pytest

from optodraw import Beam, Breadboard, Laser, Lens, OnChipPhotodetector, Scene, VerticalGratingCoupler
from optodraw.registry import build_component
from optodraw.renderers.threejs_renderer import PageConstants, ThreeJsRenderer


def _bench() -> Scene:
    scene = Scene(title="Bench")
    scene.add(Breadboard(center=(0, 0)))
    laser = scene.add(Laser(center=(-40, 0)))
    lens = scene.add(Lens(center=(0, 0)))
    scene.add(Beam((laser, "out"), (lens, "in")))
    return scene


def _chip() -> Scene:
    scene = Scene(title="Chip", platform="on_chip")
    scene.add(build_component("VerticalGratingCoupler", center=(-150, 0)))
    scene.add(build_component("MZI", center=(0, 0)))
    scene.add(build_component("VerticalGratingCoupler", center=(150, 0), angle=180))
    return scene


def _mixed() -> Scene:
    scene = Scene(title="Chip on a bench")
    laser = scene.add(Laser(center=(-80, 0)))
    lens = scene.add(Lens(center=(-40, 0)))
    coupler = scene.add(VerticalGratingCoupler(center=(0, 0)))
    scene.add(OnChipPhotodetector(center=(-60, 30)))
    scene.add(Beam((laser, "out"), (lens, "in")))
    scene.add(Beam((lens, "out"), (coupler, "f1")))
    return scene


SCENES = {"bench": (_bench, {"beam_height": 27.25}), "chip": (_chip, {}), "mixed": (_mixed, {})}

# sha256 of the capture page from the code before the refactor (commit 072aa90), with the one line that holds the
# scene data left out: that line is the parts' geometry, which the refactor does not touch. A change to the page
# on purpose changes these; take the new digests from the code before that change.
# Changed on purpose twice since: a box of size 0 draws nothing (it drew 1 tall), and the material table gained
# "gst" for PCMCell; the page differs only there. Then the legacy SVG branch left the page (29 lines, nothing else).
BEFORE = {
    "bench": "a884e33294840b8583acf60c8c1223c7fdf21b5b833098874a46d24000edf8c6",
    "chip": "bac81a275749387b4036f76b84eca1d9ee1cfdb44978dd301b9cea4916d83c5f",
    "mixed": "fad5dcad6ed802a718be5009614ca1b209517aba9b036e6c86bf8f8845b3fb90",
}


def _renderer(name: str) -> ThreeJsRenderer:
    build, options = SCENES[name]
    return ThreeJsRenderer(build(), capture={"background": "none"}, world="light", **options)


@pytest.mark.parametrize("name", sorted(SCENES))
def test_the_page_bytes_did_not_change(name):
    html = _renderer(name).render()
    page = "\n".join(line for line in html.split("\n") if not line.startswith("const sceneData = "))
    assert len(page) < len(html), "the scene data line moved: the digest no longer leaves it out"
    assert hashlib.sha256(page.encode()).hexdigest() == BEFORE[name]


def test_page_constants_hold_the_values_the_page_writes():
    common = dict(beam_plane=30.0, board_top=0.0, chip_z=2.5, chip_lift=0.0, mixed=False, on_chip=False,
                  lift_meshes=True, show_grid=True, show_chip_base=True, has_user_die=False, lead_height=2.2)
    want = {
        "bench": PageConstants(**{**common, "beam_plane": 27.25, "board_top": 2.4}),
        "chip": PageConstants(**{**common, "chip_z": 4.21, "on_chip": True, "lift_meshes": False}),
        "mixed": PageConstants(**{**common, "chip_lift": 8.2, "mixed": True}),
    }
    for name in SCENES:
        renderer = _renderer(name)
        assert renderer.page_constants(renderer._collect_scene_data()) == want[name], name
