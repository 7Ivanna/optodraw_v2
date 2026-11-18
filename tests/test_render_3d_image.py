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


def test_the_viewer_draws_no_tile_grid_by_default():
    """The endless grid of tile lines dated the look; the floor stays, the lines go."""

    html = ThreeJsRenderer(_bench()).render()
    assert "const FLOOR_GRID = false;" in html
    assert "const FLOOR_GRID = true;" in ThreeJsRenderer(_bench(), floor_grid=True).render()


def test_world_none_gives_a_transparent_canvas():
    html = ThreeJsRenderer(_bench(), world="none").render()
    assert "alpha: true" in html and "WORLDS.none" not in html
    assert "const TRANSPARENT_WORLD = true;" in html


def test_capture_mode_has_no_panels_and_no_animation_loop():
    html = ThreeJsRenderer(_bench(), capture={"width": 800, "height": 500, "scale": 1, "background": "none"}).render()
    assert 'id="export-toolbar"' not in html and 'id="info"' not in html
    assert 'id="od-capture"' in html and "const OD_CAPTURE = {" in html


def _chip_stack(hx: float, hz: float) -> dict:
    """Run the viewer's odChipStack in node for a die of half sizes hx, hz."""

    import json
    import re
    import shutil
    import subprocess

    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    scene = optodraw.Scene(title="chip", width=60, height=40, platform="on_chip")
    scene.add(optodraw.Waveguide(center=(0, 0), label=""))
    html = ThreeJsRenderer(scene).render().replace("{{", "{").replace("}}", "}")
    source = re.search(r"function odChipStack\(hx, hz\) \{.*?\n\}", html, re.S).group(0)
    script = f"{source}\nconsole.log(JSON.stringify(odChipStack({hx}, {hz})));"
    return json.loads(subprocess.run([node, "-e", script], capture_output=True, text=True, check=True).stdout)


def test_a_small_part_sits_on_a_thin_die():
    """A 5-unit die under a 16-unit part was a brick; the part was the small thing in its own picture."""

    small = _chip_stack(15.0, 8.0)
    assert small["dieT"] <= 0.1 * 16.0 and small["carT"] < small["dieT"]
    assert small["rim"] <= 0.15 * 16.0                                        # a carrier rim, not a plate


def test_a_large_chip_keeps_its_die_thickness():
    assert _chip_stack(200.0, 80.0)["dieT"] == pytest.approx(5.0)


def test_a_missing_browser_gives_a_clear_error(monkeypatch, tmp_path):
    monkeypatch.setenv("OPTODRAW_CHROME", str(tmp_path / "no-such-browser"))
    with pytest.raises(RuntimeError, match="OPTODRAW_CHROME"):
        find_chrome()


needs_chrome = pytest.mark.skipif(not find_chrome(required=False), reason="needs Chrome, Chromium or Edge")


def _image(path):
    from PIL import Image

    return Image.open(io.BytesIO(path.read_bytes())).convert("RGBA")


@needs_chrome
def test_a_3d_image_with_no_background_is_transparent_and_framed_tight(tmp_path):
    out = optodraw.Scene.render_3d_image(_bench(), tmp_path / "bench.png", width=800, height=500, scale=1,
                                         engine="viewer")
    image = _image(out)
    assert image.size == (800, 500)
    assert image.getpixel((2, 2))[3] == 0                                   # no background
    box = image.getchannel("A").getbbox()
    assert box is not None and (box[2] - box[0]) > 0.55 * image.width     # the parts fill the frame


@needs_chrome
def test_an_l_shaped_bench_fills_the_frame(tmp_path):
    """One box round an L-shaped bench frames its empty corner: the parts came out small, off to one side."""

    scene = optodraw.Scene(title="L", width=160, height=120, platform="free_space")
    laser = scene.add(optodraw.Laser(center=(-60, 40), label=""))
    lens = scene.add(optodraw.Lens(center=(0, 40), label=""))
    detector = scene.add(optodraw.Photodiode(center=(0, -50), label=""))
    scene.add(optodraw.Beam(laser, lens, detector, label=""))
    image = _image(scene.render_3d_image(tmp_path / "l.png", width=800, height=500, scale=1, engine="viewer"))
    box = image.getchannel("A").getbbox()
    assert max((box[2] - box[0]) / image.width, (box[3] - box[1]) / image.height) > 0.82


@needs_chrome
def test_silicon_keeps_its_2d_colour_in_3d(tmp_path):
    """Five lights, a bright room map and ACES turned #2b6cb0 into a pale sky blue (S 0.34, V 0.90)."""

    import colorsys

    scene = optodraw.Scene(title="", width=200, height=120, platform="on_chip")
    scene.add(optodraw.MMI1x2(center=(0, 0), label=""))
    image = _image(scene.render_3d_image(tmp_path / "mmi.png", background="light", width=600, height=375, scale=1, engine="viewer"))
    blue = sorted((p[:3] for p in image.getdata() if p[3] == 255 and p[2] > p[0] + 40 and p[2] > p[1] + 15), key=sum)
    _, saturation, value = colorsys.rgb_to_hsv(*(c / 255 for c in blue[len(blue) // 2]))
    assert saturation > 0.6 and value < 0.85                                # #2b6cb0 is S 0.76, V 0.69


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


@needs_chrome
def test_a_long_column_of_pads_is_not_cut_off(tmp_path):
    """A part long in the view direction comes near the camera; five framing passes left its near end cut."""

    scene = optodraw.Scene(title="", width=200, height=200, platform="on_chip")
    scene.add(optodraw.OpticalIOBank(center=(0, 0), label=""))
    image = _image(scene.render_3d_image(tmp_path / "bank.png", width=600, height=375, scale=1, engine="viewer"))
    box = image.getchannel("A").getbbox()
    assert box[0] > 0 and box[1] > 0 and box[2] < image.width and box[3] < image.height


@needs_chrome
def test_a_part_away_from_the_origin_casts_a_shadow(tmp_path):
    """The key light's shadow box was 10 units round the origin: nothing else cast a shadow.

    Seen from the top, so the shadow cannot hide behind its part (the studio key comes from the camera's
    side), and looked for on every side of the part (its direction follows the studio key).
    """

    import numpy as np
    from PIL import Image, ImageFilter

    scene = optodraw.Scene(title="", width=400, height=100, platform="free_space")
    scene.add(optodraw.Laser(center=(-150, 0), label=""))
    scene.add(optodraw.Laser(center=(150, 0), label=""))
    rgb = np.asarray(_image(scene.render_3d_image(tmp_path / "two.png", background="light", width=800, height=500,
                                                  scale=1, engine="viewer", camera="top")).convert("RGB")).astype(float)
    lum = rgb.mean(axis=2)
    greyish = (rgb.max(axis=2) - rgb.min(axis=2)) < 40                     # the floor, not the parts
    parts = (~greyish) | (lum < 150)
    near = np.asarray(Image.fromarray((parts * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(9))) > 0
    ys, xs = np.nonzero(parts[:, 400:])                                      # the laser in the right half
    x0, x1, y0, y1 = xs.min() + 400, xs.max() + 400, ys.min(), ys.max()
    window = np.zeros_like(parts)
    window[max(y0 - 80, 0):y1 + 80, max(x0 - 120, 0):x1 + 120] = True
    floor = lum[greyish & ~near & window]
    assert np.median(floor) - np.percentile(floor, 1) > 5.0                 # its shadow darkens the floor


@needs_chrome
def test_a_3d_image_with_a_light_world_is_opaque_and_scaled(tmp_path):
    out = _bench().render_3d_image(tmp_path / "bench_light.png", background="light", width=400, height=250, scale=2, engine="viewer")
    image = _image(out)
    assert image.size == (800, 500)
    assert image.getpixel((2, 2))[3] == 255


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


def test_a_large_chip_is_drawn_taller_than_a_single_part_up_to_a_limit():
    """At 2.5 the guides of a 400-unit chip still read as lines; 4.5 gives relief without fences."""

    def factor(scene, **kwargs) -> float:
        import re

        html = ThreeJsRenderer(scene, **kwargs).render()
        return float(re.search(r"const CHIP_Z = ([0-9.]+);", html).group(1))

    small = optodraw.Scene(width=100, height=60, platform="on_chip")
    small.add(optodraw.MMI1x2(center=(0, 0), label=""))
    large = optodraw.Scene(width=600, height=100, platform="on_chip")
    for x in (-250, 0, 250):
        large.add(optodraw.MMI1x2(center=(x, 0), label=""))
    assert factor(small) == pytest.approx(2.5)
    assert factor(large) == pytest.approx(4.5)
    assert factor(large, chip_height_scale=3.0) == pytest.approx(3.0)       # a number given wins


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
