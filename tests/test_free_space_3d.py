"""Free-space parts in 3D: what stands on the table, what sits on a post, and what a figure shows."""

from __future__ import annotations

import pytest

import optodraw


def _shapes(node):
    yield node
    for child in node.get("children", []):
        yield from _shapes(child)


def test_a_sample_in_a_cryostat_stands_in_the_cryostat_not_on_a_post():
    """The sample floated at the beam height on a post, in a glass tube lying on its side."""

    sample = optodraw.Sample(in_cryostat=True)
    assert sample.base_mount == "none"
    shapes = list(_shapes(sample.geometry_3d()))
    roles = [shape.get("role") for shape in shapes]
    assert roles.count("window") == 2 and "sample" in roles                 # the in and out windows, the sample
    beam = optodraw.Cryostat().beam_height
    lowest = min(s["position"][1] - s["height"] / 2.0 for s in shapes if s.get("shape") == "cylinder"
                 and not s.get("rotation") and "position" in s)
    assert lowest == pytest.approx(-beam)                                    # the can stands on the table


def test_a_sample_without_a_cryostat_still_sits_on_its_post():
    assert getattr(optodraw.Sample(), "base_mount", "post") == "post"


def test_the_bench_beam_runs_three_inches_over_the_table_everywhere():
    """At 16 units (1.6 in) the larger optics reached down to their post holders: posts read as stubs."""

    from optodraw.components.optics.optomech import BEAM_HEIGHT
    from optodraw.renderers.threejs_renderer import ThreeJsRenderer

    scene = optodraw.Scene(width=120, height=80, platform="free_space")
    scene.add(optodraw.Lens(center=(0, 0)))
    assert BEAM_HEIGHT == pytest.approx(30.0)                                # 1 in = 10 units
    assert ThreeJsRenderer(scene).beam_height == pytest.approx(BEAM_HEIGHT)
    assert optodraw.Cryostat().beam_height == pytest.approx(BEAM_HEIGHT)


def _probe_viewer(scene, script):
    """Run ``script`` (gets V = {THREE, scene, camera}, returns a JSON value) on the viewer's built scene."""

    import json

    from optodraw.renderers.capture3d import find_chrome, run_page
    from optodraw.renderers.threejs_renderer import ThreeJsRenderer

    if find_chrome(required=False) is None:
        pytest.skip("needs Chrome, Chromium or Edge")
    html = ThreeJsRenderer(scene, capture={"width": 300, "height": 200, "scale": 1, "background": "light"}).render()
    probe = ("<textarea id='od-probe'></textarea><script type='module'>"
             "while (!window.__odView) await new Promise(r => setTimeout(r, 100));"
             "const V = window.__odView; const out = document.getElementById('od-probe');"
             "try { out.value = JSON.stringify((function (V) {" + script + "})(V)); }"
             "catch (e) { out.value = JSON.stringify({error: String(e && e.stack || e)}); }</script>")
    data = json.loads(run_page(html.replace("</body>", probe + "</body>"), width=300, height=200, timeout=120,
                               element="od-probe"))
    assert not (isinstance(data, dict) and "error" in data), data
    return data


def _bench_of_optics():
    scene = optodraw.Scene(width=200, height=80, platform="free_space")
    laser = scene.add(optodraw.Laser(center=(-80, 0)))
    lens = scene.add(optodraw.Lens(center=(-40, 0), aperture=25.0))
    mirror = scene.add(optodraw.Mirror(center=(0, 0)))
    objective = scene.add(optodraw.Objective(center=(40, 0)))
    pd = scene.add(optodraw.Photodiode(center=(80, 0)))
    scene.add(optodraw.Beam(laser, lens, mirror, objective, pd))
    return scene


def test_every_pedestal_is_the_same_and_every_post_shows():
    data = _probe_viewer(_bench_of_optics(), """
      const holders = [], posts = [];
      V.scene.traverse(o => {
        const p = o.isMesh && o.geometry && o.geometry.type === 'CylinderGeometry' ? o.geometry.parameters : null;
        if (!p || !o.material || !o.material.color) return;
        const hex = o.material.color.getHex();
        if (hex === 0x22272d && Math.abs(p.radiusTop - 3.74) < 1e-6) holders.push(p.height);   // anodised holder
        if (hex === 0xc4c9cf && Math.abs(p.radiusTop - 2.5) < 1e-6) posts.push(p.height);      // brushed post
      });
      return {holders, posts};
    """)
    assert len(data["holders"]) >= 4 and len(data["posts"]) >= 4, data
    assert max(data["holders"]) - min(data["holders"]) < 1e-6, data              # one pedestal for every optic
    assert min(data["posts"]) >= 5.0, data                                       # the silver post shows


def test_only_the_breadboard_has_holes_and_the_white_floor_stays_plain():
    """A breadboard and a holed floor in one view clash; the white floor keeps no holes."""

    scene = _bench_of_optics()
    scene.add(optodraw.Baseplate(center=(0, 0), length=200, width=60))
    data = _probe_viewer(scene, """
      const plates = [];
      V.scene.traverse(o => {
        if (!o.isMesh || o.geometry.type !== 'BoxGeometry') return;
        const mats = Array.isArray(o.material) ? o.material : [o.material];
        plates.push({width: o.geometry.parameters.width, holes: mats.some(m => m.map)});
      });
      return plates;
    """)
    floor = max(data, key=lambda p: p["width"])
    board = [p for p in data if p["width"] == pytest.approx(200.0)]
    assert not floor["holes"], data                                              # the white floor is plain
    assert board and all(p["holes"] for p in board), data                        # the breadboard has its holes


def _periscope_chain():
    from optodraw import Beam, Periscope

    scene = optodraw.Scene(width=200, height=80, platform="free_space")
    laser = scene.add(optodraw.Laser(center=(-80, 0)))
    up = scene.add(Periscope(center=(-30, 0), rise=25.0))
    down = scene.add(Periscope(center=(30, 10), rise=-25.0, angle=20))
    pd = scene.add(optodraw.Photodiode(center=(80, 0)))
    scene.add(Beam((laser, "out"), (up, "in"), (up, "out"), (down, "in"), (down, "out"), (pd, "in")))
    return scene


def _viewer_beam_and_mirrors(scene, **kwargs):
    """The beam's vertices and every periscope mirror centre, in the viewer's 3D frame."""

    import json
    import math
    import re

    from optodraw.renderers._scene_data import expand_scene_data
    from optodraw.renderers.threejs_renderer import ThreeJsRenderer

    renderer = ThreeJsRenderer(scene, **kwargs)
    packed = json.loads(re.search(r"const sceneData = odExpandSceneData\((\{.*?\})\);\n", renderer.render(), re.S).group(1))
    data = expand_scene_data(packed)
    plane = renderer.beam_height
    beam = [(p[0], p[1] + plane, p[2]) for e in data if e.get("type") == "beam" for p in e["points"]]
    mirrors = []
    for e in data:
        children = (e.get("geometry") or {}).get("children", [])
        for c in children:
            if c.get("role") == "mirror":
                yaw = e["rotation"][1]                                       # the part turns about y only
                x, y, z = c["position"]
                mirrors.append((e["position"][0] + x * math.cos(yaw) + z * math.sin(yaw), e["position"][1] + y,
                                e["position"][2] - x * math.sin(yaw) + z * math.cos(yaw)))
    return beam, mirrors


@pytest.mark.parametrize("kwargs", [{}, {"beam_height": 40.0}], ids=["default", "beam-height-40"])
def test_the_beam_turns_on_each_periscope_mirror(kwargs):
    """The beam ran straight from a periscope's input port to its output port, past mirrors at the wrong height."""

    import math

    beam, mirrors = _viewer_beam_and_mirrors(_periscope_chain(), **kwargs)
    assert len(mirrors) == 4, mirrors
    for m in mirrors:
        assert min(math.dist(m, v) for v in beam) < 0.5, (m, beam)                 # a vertex on every mirror


def test_a_periscope_takes_the_bench_beam_height():
    from optodraw.components.optics.optomech import BEAM_HEIGHT

    assert optodraw.Periscope().beam_height == pytest.approx(BEAM_HEIGHT)
