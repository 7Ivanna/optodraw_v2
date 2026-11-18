"""3D environment and image export: a clean studio, a transparent option, and a 3D image from Python."""

from __future__ import annotations

import io

import pytest

import optodraw
from optodraw.renderers.capture3d import find_chrome
from optodraw.renderers.threejs_renderer import ThreeJsRenderer


def _bench():
    scene = optodraw.Scene(title="bench", width=120, height=80, platform="free_space")
    laser = scene.add(optodraw.Laser(center=(-30, 0), label="laser"))
    lens = scene.add(optodraw.Lens(center=(0, 0), label="lens"))
    detector = scene.add(optodraw.Photodiode(center=(30, 0), label="PD"))
    scene.add(optodraw.Beam(laser, lens, detector, label=""))
    return scene


def test_a_missing_browser_gives_a_clear_error(monkeypatch, tmp_path):
    monkeypatch.setenv("OPTODRAW_CHROME", str(tmp_path / "no-such-browser"))
    with pytest.raises(RuntimeError, match="OPTODRAW_CHROME"):
        find_chrome()


needs_chrome = pytest.mark.skipif(not find_chrome(required=False), reason="needs Chrome, Chromium or Edge")


def _image(path):
    from PIL import Image

    return Image.open(io.BytesIO(path.read_bytes())).convert("RGBA")


@needs_chrome
def test_gold_stays_gold_with_a_soft_room_map(tmp_path):
    """A metal shows the room map, not its base colour: a dimmed map turned the gold pads brown."""

    import colorsys

    scene = optodraw.Scene(title="", width=200, height=120, platform="on_chip")
    scene.add(optodraw.ElectricalPad(center=(0, 0), label=""))
    image = _image(scene.render_3d_image(tmp_path / "pad.png", background="light", width=600, height=375, scale=1, engine="viewer"))
    gold = sorted((p[:3] for p in image.getdata() if p[3] == 255 and p[0] > p[2] + 50 and p[1] > p[2] + 20), key=sum)
    hue, _, value = colorsys.rgb_to_hsv(*(c / 255 for c in gold[len(gold) // 2]))
    assert value > 0.7 and 0.09 < hue < 0.16                                 # bright and yellow, not brown


def test_schematic_chip_parts_are_drawn_taller_in_3d():
    """Silicon 0.55 high under parts 20 to 400 long read flat: the designs did not show in 3D."""

    scene = optodraw.Scene(width=200, height=120, platform="on_chip")
    scene.add(optodraw.MMI1x2(center=(-40, 0), label=""))
    scene.add(optodraw.ElectricalPad(center=(40, 0), label=""))
    scene.add(optodraw.MMI1x2(center=(0, 40), render_physical=True, label=""))
    renderer = ThreeJsRenderer(scene)
    items = [i for i in renderer._collect_scene_data() if i.get("type") == "mesh"]
    assert [bool(i.get("zScale")) for i in items] == [True, True, False]     # true-size parts keep their height
    assert "const CHIP_Z = 2.5;" in renderer.render()
    assert "const CHIP_Z = 4.0;" in ThreeJsRenderer(scene, chip_height_scale=4.0).render()


def test_chip_routes_join_their_parts_without_a_step():
    """A waveguide route was 0.22 high into parts 0.55 high; chip metal lay on the die, under the leads."""

    scene = optodraw.Scene(width=200, height=120, platform="on_chip")
    left = scene.add(optodraw.MMI1x2(center=(-40, 0), label=""))
    right = scene.add(optodraw.MMI1x2(center=(40, 0), angle=180, label=""))
    scene.route((left, "o2"), (right, "o2"), kind="waveguide")
    mzm_a = scene.add(optodraw.MZM(center=(-40, 60), label=""))
    mzm_b = scene.add(optodraw.MZM(center=(60, 60), label=""))
    scene.route((mzm_a, "sig"), (mzm_b, "sig"), kind="electrical")
    routes = [i for i in ThreeJsRenderer(scene)._collect_scene_data() if i.get("type") == "route"]
    guide = next(r for r in routes if r["kind"] == "waveguide")
    metal = next(r for r in routes if r["kind"] == "electrical")
    assert guide["stripThick"] == pytest.approx(left._draw_thickness()) and guide["stripScale"]
    assert guide["stripMaterial"] == {"color": left.color, "preset": left._draw_material_preset()}  # no colour band
    assert metal["stripMaterial"]["preset"] == "gold"
    stack = mzm_a._draw_layer_stack()
    assert metal["stripThick"] == pytest.approx(stack["metal_height"])
    assert metal["stripZ"] == pytest.approx(stack["metal_z"]) and metal["stripScale"]


def test_a_camera_direction_in_world_axes_sets_the_first_view():
    html = ThreeJsRenderer(_bench(), camera_direction=(1.0, -2.0, 3.0)).render()
    assert "new THREE.Vector3(1.0, 3.0, 2.0)" in html                     # three.js is y up: (x, z, -y)
    with pytest.raises(ValueError, match="camera_direction"):
        ThreeJsRenderer(_bench(), camera_direction=(0.0, 0.0, 0.0))


def test_a_3d_image_takes_a_camera_direction(monkeypatch, tmp_path):
    import base64

    import optodraw.renderers.capture3d as capture

    seen = {}

    def page(html, **_):
        seen["html"] = html
        return "data:image/png;base64," + base64.b64encode(b"png").decode()

    monkeypatch.setattr(capture, "run_page", page)
    capture.render_3d_image(_bench(), tmp_path / "a.png", camera=(0.5, -1.0, 2.0), engine="viewer")
    assert "new THREE.Vector3(0.5, 2.0, 1.0)" in seen["html"]
