"""Metals in 3D: the base colour a metal reflects with, measured, not the painted 2D fill."""

from __future__ import annotations

import json

import pytest

import optodraw
from optodraw.materials import material_catalog

PHYSICAL = {"gold": "#ffe29b", "aluminum": "#f5f6f6", "copper": "#fad0c0", "steel": "#c0bdba", "titanium": "#c2bab1"}


def test_the_metal_presets_carry_their_measured_base_colour():
    catalog = material_catalog()
    for name, colour in PHYSICAL.items():
        assert catalog[name]["physical"] == colour, name


def test_a_gold_heater_reflects_with_physical_gold_in_3d():
    from optodraw.renderers.capture3d import find_chrome, run_page
    from optodraw.renderers.threejs_renderer import ThreeJsRenderer

    if find_chrome(required=False) is None:
        pytest.skip("needs Chrome, Chromium or Edge")
    scene = optodraw.Scene(width=160, height=60, platform="on_chip")
    scene.add(optodraw.MZI(center=(0, 0)))
    html = ThreeJsRenderer(scene, capture={"width": 300, "height": 200, "scale": 1, "background": "light"}).render()
    probe = ("<textarea id='od-probe'></textarea><script type='module'>"
             "while (!window.__odView) await new Promise(r => setTimeout(r, 100));"
             "const golds = [];"
             "window.__odView.scene.traverse(o => { const m = o.isMesh && !Array.isArray(o.material) ? o.material : null;"
             "  if (m && m.metalness >= 0.9 && m.color && m.color.r > 0.5 && m.color.b < 0.45 * m.color.r)"
             "    golds.push(m.color.getHexString(window.__odView.THREE.SRGBColorSpace)); });"
             "document.getElementById('od-probe').value = JSON.stringify(golds);</script>")
    golds = json.loads(run_page(html.replace("</body>", probe + "</body>"), width=300, height=200, timeout=120,
                                element="od-probe"))
    assert "ffe29b" in golds and "d4af37" not in golds, golds                 # the heater is physical gold
