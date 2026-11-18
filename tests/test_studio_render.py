"""The studio renderer from Python: Scene.render_3d_image(engine="studio")."""

from __future__ import annotations

import io

import pytest

import optodraw
from optodraw.renderers.capture3d import find_chrome

needs_chrome = pytest.mark.skipif(find_chrome(required=False) is None, reason="needs Chrome, Chromium or Edge")


def _bench():
    scene = optodraw.Scene(title="bench", width=120, height=80, platform="free_space")
    laser = scene.add(optodraw.Laser(center=(-30, 0), label="laser"))
    lens = scene.add(optodraw.Lens(center=(0, 0), label="lens"))
    detector = scene.add(optodraw.Photodiode(center=(30, 0), label="PD"))
    scene.add(optodraw.Beam(laser, lens, detector, label=""))
    return scene


def _image(path):
    from PIL import Image

    return Image.open(io.BytesIO(path.read_bytes())).convert("RGBA")


@pytest.mark.parametrize("engine", ["other", "blender"])
def test_an_unknown_engine_is_a_named_error(tmp_path, engine):
    """optodraw renders with its own engines only; Blender is not one."""

    with pytest.raises(ValueError, match="^engine must be one of: studio, viewer$"):
        _bench().render_3d_image(str(tmp_path / "x.png"), engine=engine)


@needs_chrome
def test_a_studio_image_has_its_size_and_is_clear_where_there_is_nothing(tmp_path):
    path = _bench().render_3d_image(str(tmp_path / "bench.png"), engine="studio", background="none", width=160,
                                    height=100, scale=1.0, samples=1, quality="draft")
    image = _image(path)
    assert image.size == (160, 100)
    alpha = image.getchannel("A")
    assert alpha.getpixel((0, 0)) == 0                                 # nothing in the corner: transparent
    assert max(alpha.getdata()) == 255                                 # the parts are solid


@needs_chrome
def test_the_same_scene_gives_the_same_studio_png(tmp_path):
    def render(name):
        return _bench().render_3d_image(str(tmp_path / name), engine="studio", background="light", width=120,
                                        height=80, scale=1.0, samples=1, quality="draft").read_bytes()

    assert render("a.png") == render("b.png")


@needs_chrome
def test_the_studio_reads_every_triangle_of_the_viewers_scene():
    """An extruded part with one material has groups 0 (caps) and 1 (sides); three.js draws both."""

    import json

    from optodraw.renderers.capture3d import run_page
    from optodraw.renderers.threejs_renderer import ThreeJsRenderer

    scene = optodraw.Scene(title="chip", width=200, height=80, platform="on_chip")
    laser = scene.add(optodraw.OnChipLaser(center=(-60, 0)))
    pd = scene.add(optodraw.OnChipPhotodetector(center=(60, 0)))
    scene.route((laser, "o1"), (pd, "o1"), kind="waveguide")
    html = ThreeJsRenderer(scene, capture={"width": 200, "height": 120, "scale": 1, "background": "light",
                                           "engine": "studio", "samples": 1, "quality": "draft"}).render()
    probe = """<script type="module">
      const wait = () => new Promise(r => setTimeout(r, 200));
      while (!window.__odView) await wait();
      const V = window.__odView;
      let drawn = 0;
      V.scene.traverseVisible(o => {
        if (!o.isMesh || !o.geometry || !o.geometry.attributes.position) return;
        if (o.userData && o.userData.odStudioFloor) return;     // the viewer's floor: the studio draws its own
        const m = Array.isArray(o.material) ? o.material : [o.material];
        if (m.some(x => x.isShaderMaterial)) return;
        const g = o.geometry, n = g.index ? g.index.count : g.attributes.position.count;
        drawn += Math.min(n, g.drawRange.count) / 3 * (o.isInstancedMesh ? o.count : 1);
      });
      const d = V.studio.extract(V.THREE, V.scene, V.camera, {width: 10, height: 10, samples: 1, world: 'light'});
      document.getElementById('od-probe').value = JSON.stringify({drawn, read: d.positions.length / 9});
    </script><textarea id="od-probe"></textarea>"""
    data = json.loads(run_page(html.replace("</body>", probe + "</body>"), width=200, height=120, timeout=300,
                               element="od-probe"))
    assert data["read"] == data["drawn"] and data["read"] > 0, data


@needs_chrome
def test_the_studio_png_is_the_same_for_any_number_of_workers(tmp_path):
    from optodraw.renderers.capture3d import render_3d_image

    def render(name, workers):
        return render_3d_image(_bench(), tmp_path / name, engine="studio", background="light", width=120, height=80,
                               scale=1.0, samples=1, quality="draft", workers=workers).read_bytes()

    assert render("one.png", 1) == render("three.png", 3)


@needs_chrome
def test_a_studio_render_that_runs_out_of_time_names_its_last_stage(tmp_path):
    from optodraw.renderers.capture3d import render_3d_image

    with pytest.raises(RuntimeError, match=r"last stage: (reading the scene|preparing|tile \d+ of \d+)"):
        render_3d_image(_bench(), tmp_path / "slow.png", engine="studio", width=1600, height=1000, scale=2.0,
                        samples=16, timeout=6.0)


@needs_chrome
def test_a_machine_with_no_webgl_still_makes_a_studio_image(tmp_path, monkeypatch):
    from optodraw.renderers import capture3d

    monkeypatch.setattr(capture3d, "CHROME_FLAGS", ["--disable-3d-apis"])
    probe = ("<textarea id='od-capture'></textarea><script>const c = document.createElement('canvas');"
             "document.getElementById('od-capture').value = String(!!(c.getContext('webgl2') || c.getContext('webgl')));"
             "</script>")
    assert capture3d.run_page(probe, timeout=60) == "false"                  # WebGL is really off here
    path = _bench().render_3d_image(str(tmp_path / "cpu.png"), engine="studio", background="none", width=120,
                                    height=80, scale=1.0, samples=1, quality="draft")
    image = _image(path)
    assert image.size == (120, 80) and max(image.getchannel("A").getdata()) == 255


@needs_chrome
def test_a_page_error_ends_a_capture_at_once_with_its_message(tmp_path, monkeypatch):
    """The viewer engine needs WebGL: with none, the capture names the error instead of waiting out its time."""

    import time

    from optodraw.renderers import capture3d

    monkeypatch.setattr(capture3d, "CHROME_FLAGS", ["--disable-3d-apis"])
    start = time.monotonic()
    with pytest.raises(RuntimeError, match="WebGL"):
        capture3d.render_3d_image(_bench(), tmp_path / "x.png", engine="viewer", width=120, height=80, scale=1.0,
                                  timeout=60.0)
    assert time.monotonic() - start < 45.0
