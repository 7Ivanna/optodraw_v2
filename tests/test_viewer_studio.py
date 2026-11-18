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


def test_the_viewer_quality_is_high_or_fast():
    assert ThreeJsRenderer(_bench()).quality == "high"
    assert ThreeJsRenderer(_bench(), quality="fast").quality == "fast"
    with pytest.raises(ValueError, match="quality must be one of: high, fast"):
        ThreeJsRenderer(_bench(), quality="ultra")


def _chip():
    scene = optodraw.Scene(title="chip", width=200, height=80, platform="on_chip")
    laser = scene.add(optodraw.OnChipLaser(center=(-60, 0)))
    pd = scene.add(optodraw.OnChipPhotodetector(center=(60, 0)))
    scene.route((laser, "o1"), (pd, "o1"), kind="waveguide")
    return scene


