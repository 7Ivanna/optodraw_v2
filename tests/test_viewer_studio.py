"""The live viewer lit by the studio renderer's softboxes: the same light as the saved studio image."""

from __future__ import annotations

import json

import pytest

import optodraw
from optodraw.renderers.capture3d import find_chrome, run_page
from optodraw.renderers.threejs_renderer import ThreeJsRenderer

needs_chrome = pytest.mark.skipif(find_chrome(required=False) is None, reason="needs Chrome, Chromium or Edge")


def _bench():
    scene = optodraw.Scene(title="bench", width=120, height=80, platform="free_space")
    laser = scene.add(optodraw.Laser(center=(-30, 0)))
    lens = scene.add(optodraw.Lens(center=(0, 0)))
    pd = scene.add(optodraw.Photodiode(center=(30, 0)))
    scene.add(optodraw.Beam(laser, lens, pd))
    return scene


def _probe(renderer: ThreeJsRenderer, script: str):
    html = renderer.render()
    probe = ("<textarea id='od-probe'></textarea><script type='module'>"
             "while (!window.__odView) await new Promise(r => setTimeout(r, 100));"
             "await new Promise(r => setTimeout(r, 300));"
             "const V = window.__odView, out = document.getElementById('od-probe');"
             "try { out.value = JSON.stringify((function (V) {" + script + "})(V)); }"
             "catch (e) { out.value = JSON.stringify({error: String(e && e.stack || e)}); }</script>")
    data = json.loads(run_page(html.replace("</body>", probe + "</body>"), width=400, height=260, timeout=120,
                               element="od-probe"))
    assert not (isinstance(data, dict) and "error" in data), data
    return data


LIGHTS = """
  const lights = {}, metalsWithOwnMap = [];
  V.scene.traverse(o => {
    if (o.isLight) lights[o.type + (o.castShadow ? ':key' : '')] = (lights[o.type + (o.castShadow ? ':key' : '')] || 0) + o.intensity;
    if (o.isMesh && !Array.isArray(o.material) && o.material.metalness >= 0.6 && o.material.envMap) metalsWithOwnMap.push(1);
  });
  return {studio: !!V.scene.userData.studioLight, env: !!V.scene.environment, envIntensity: V.scene.environmentIntensity,
          lights, metalsWithOwnMap: metalsWithOwnMap.length};
"""


@needs_chrome
def test_the_viewer_takes_its_light_from_the_studio():
    capture = {"width": 400, "height": 260, "scale": 1, "background": "light"}
    data = _probe(ThreeJsRenderer(_bench(), capture=capture), LIGHTS)
    assert data["studio"] and data["env"] and data["envIntensity"] == pytest.approx(1.0), data
    assert data["lights"].get("DirectionalLight:key", 0) > 0.5, data             # the key softbox casts the shadow
    others = {k: v for k, v in data["lights"].items() if k != "DirectionalLight:key"}
    assert all(v == 0 for v in others.values()), data                              # the rest is in the environment
    assert data["metalsWithOwnMap"] == 0, data                                    # metals reflect the studio


@needs_chrome
def test_another_lighting_preset_keeps_its_own_lights():
    capture = {"width": 400, "height": 260, "scale": 1, "background": "light"}
    data = _probe(ThreeJsRenderer(_bench(), capture=capture, lighting_preset="publication"), LIGHTS)
    assert not data["studio"] and sum(data["lights"].values()) > data["lights"].get("DirectionalLight:key", 0), data


def test_the_viewer_quality_is_high_or_fast():
    assert ThreeJsRenderer(_bench()).quality == "high"
    assert ThreeJsRenderer(_bench(), quality="fast").quality == "fast"
    with pytest.raises(ValueError, match="quality must be one of: high, fast"):
        ThreeJsRenderer(_bench(), quality="ultra")


@needs_chrome
def test_high_quality_darkens_the_floor_round_a_pedestal_with_ambient_occlusion():
    """GTAO reads the viewer's logarithmic depth through a patched view-position function."""

    import io

    import numpy as np
    from PIL import Image

    def floor_ring(quality):
        scene = optodraw.Scene(title="", width=60, height=60, platform="free_space")
        scene.add(optodraw.Lens(center=(0, 0), label=""))
        html = ThreeJsRenderer(scene, capture={"width": 400, "height": 400, "scale": 1, "background": "light"},
                               camera_preset="top", quality=quality).render()
        import base64
        value = run_page(html, width=400, height=400, timeout=120)
        rgb = np.asarray(Image.open(io.BytesIO(base64.b64decode(value.split(",", 1)[1]))).convert("RGB")).astype(float)
        lum = rgb.mean(axis=2)
        parts = (rgb.max(axis=2) - rgb.min(axis=2) > 40) | (lum < 150)
        ys, xs = np.nonzero(parts)
        cy, cx = ys.mean(), xs.mean()
        yy, xx = np.mgrid[0:400, 0:400]
        r = np.hypot(yy - cy, xx - cx)
        base = r[parts].max()
        ring = (~parts) & (r > base + 2) & (r < base + 14)                 # the floor just outside the pedestal
        return float(lum[ring].mean())

    assert floor_ring("fast") - floor_ring("high") > 3.0                  # a contact shadow appears


@needs_chrome
def test_the_photoreal_button_shows_a_studio_render_over_the_view():
    html = ThreeJsRenderer(_bench()).render()
    probe = ("<textarea id='od-probe'></textarea><script type='module'>"
             "const wait = (ms) => new Promise(r => setTimeout(r, ms));"
             "while (!document.getElementById('btn-pathtrace')) await wait(100);"
             "await wait(800);"
             "document.getElementById('btn-pathtrace').click();"
             "let img = null;"
             "for (let i = 0; i < 600 && !(img && img.src.startsWith('data:image/png')); i++) {"
             "  await wait(200); img = document.getElementById('render-image'); }"
             "document.getElementById('od-probe').value = JSON.stringify({"
             "  png: !!(img && img.src.startsWith('data:image/png')), shown: !!(img && img.style.display !== 'none'),"
             "  status: (document.getElementById('render-status') || {}).textContent || ''});</script>")
    data = json.loads(run_page(html.replace("</body>", probe + "</body>"), width=480, height=320, timeout=240,
                               element="od-probe"))
    assert data["png"] and data["shown"], data
    assert "complete" in data["status"].lower(), data


def _chip():
    scene = optodraw.Scene(title="chip", width=200, height=80, platform="on_chip")
    laser = scene.add(optodraw.OnChipLaser(center=(-60, 0)))
    pd = scene.add(optodraw.OnChipPhotodetector(center=(60, 0)))
    scene.route((laser, "o1"), (pd, "o1"), kind="waveguide")
    return scene


@needs_chrome
def test_a_chip_in_the_viewer_stands_on_a_studio_floor_the_studio_renderer_skips():
    capture = {"width": 400, "height": 260, "scale": 1, "background": "light"}
    data = _probe(ThreeJsRenderer(_chip(), capture=capture), """
      let floor = null;
      V.scene.traverse(o => { if (o.userData && o.userData.odStudioFloor) floor = o; });
      if (!floor) return {floor: false};
      let lowest = Infinity;
      V.scene.traverse(o => { if (o.isMesh && o !== floor) { const b = new V.THREE.Box3().setFromObject(o); lowest = Math.min(lowest, b.min.y); } });
      const d = V.studio.extract(V.THREE, V.scene, V.camera, {width: 10, height: 10, samples: 1, world: 'light'});
      let floorInStudio = false;
      const P = d.positions;
      for (let i = 1; i < P.length; i += 3) if (Math.abs(P[i] - floor.position.y) < 1e-6 && Math.abs(P[i - 1]) > 1e3) floorInStudio = true;
      return {floor: true, receives: floor.receiveShadow, faded: !!floor.material.alphaMap,
              atBottom: Math.abs(floor.position.y - lowest) < 1e-3, floorInStudio};
    """)
    assert data["floor"] and data["receives"] and data["faded"] and data["atBottom"], data
    assert not data["floorInStudio"], data                                   # the studio draws its own exact floor
