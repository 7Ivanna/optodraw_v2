"""A periscope and the parts after it keep one beam height: change either one and the other follows."""

from __future__ import annotations

import json
import re
import warnings

import pytest

import optodraw
from optodraw import Beam, Lens, Periscope
from optodraw.renderers._scene_data import expand_scene_data
from optodraw.renderers.threejs_renderer import ThreeJsRenderer


def _bench(rise=25.0, lens_height=None, down_rise=None, laser_height=None):
    """laser -> periscope -> lens -> (falling periscope) -> photodiode, along x."""

    scene = optodraw.Scene(width=260, height=80, platform="free_space")
    laser = scene.add(optodraw.Laser(center=(-110, 0), label="laser"))
    up = scene.add(Periscope(center=(-70, 0), rise=rise, label="up"))
    lens = scene.add(Lens(center=(-20, 0), label="lens"))
    if lens_height is not None:
        lens.beam_height = lens_height
    if laser_height is not None:
        laser.beam_height = laser_height
    anchors = [(laser, "out"), (up, "in"), (up, "out"), (lens, "in"), (lens, "out")]
    if down_rise is not None:
        down = scene.add(Periscope(center=(40, 0), rise=down_rise, label="down"))
        anchors += [(down, "in"), (down, "out")]
    pd = scene.add(optodraw.Photodiode(center=(110, 0), label="pd"))
    anchors.append((pd, "in"))
    scene.add(Beam(*anchors))
    return scene


def _view(scene, **kwargs):
    renderer = ThreeJsRenderer(scene, **kwargs)
    packed = json.loads(re.search(r"const sceneData = odExpandSceneData\((\{.*?\})\);\n", renderer.render(), re.S).group(1))
    data = expand_scene_data(packed)
    return data, renderer.beam_height


def _part(data, label):
    return next(e for e in data if e.get("label") == label)


def _beam_heights(data, plane):
    return [round(p[1] + plane, 6) for e in data if e.get("type") == "beam" for p in e["points"]]


def _mirror_heights(data, label):
    return sorted(round(c["position"][1], 6) for c in _part(data, label)["geometry"]["children"]
                  if c.get("role") == "mirror")


def test_the_parts_after_a_periscope_ride_at_its_exit_height():
    data, plane = _view(_bench(rise=25.0))
    assert _part(data, "lens").get("lift") == pytest.approx(25.0)
    assert _part(data, "pd").get("lift") == pytest.approx(25.0)
    assert not _part(data, "laser").get("lift")
    heights = _beam_heights(data, plane)
    assert heights[:3] == [plane] * 3 and heights[3:] == [plane + 25.0] * (len(heights) - 3), heights


def test_a_part_given_its_own_beam_height_moves_the_periscope_mirror_and_the_parts_after_it():
    data, plane = _view(_bench(rise=25.0, lens_height=30.0 + 40.0))
    assert _mirror_heights(data, "up") == [plane, plane + 40.0]                 # the upper mirror follows the lens
    assert _part(data, "lens").get("lift") == pytest.approx(40.0)
    assert _part(data, "pd").get("lift") == pytest.approx(40.0)                 # and so does the part after it
    heights = _beam_heights(data, plane)
    assert heights[3:] == [plane + 40.0] * (len(heights) - 3), heights


def test_a_falling_periscope_meets_the_raised_beam_and_drops_it_by_its_rise():
    data, plane = _view(_bench(rise=25.0, down_rise=-10.0))
    assert _mirror_heights(data, "down") == [plane + 15.0, plane + 25.0]        # its entry mirror meets the beam
    assert _part(data, "pd").get("lift") == pytest.approx(15.0)
    heights = _beam_heights(data, plane)
    assert heights[-3:] == [plane + 15.0] * 3, heights


def test_a_falling_periscope_with_the_same_drop_takes_the_beam_back_to_the_bench():
    data, plane = _view(_bench(rise=25.0, down_rise=-25.0))
    assert _mirror_heights(data, "down") == [plane, plane + 25.0]
    assert not _part(data, "pd").get("lift")


def test_a_part_after_a_falling_periscope_moves_its_lower_mirror():
    scene = _bench(rise=25.0, down_rise=-25.0)
    pd = next(c for c in scene.walk() if c.label == "pd")
    pd.beam_height = 40.0
    data, plane = _view(scene)
    assert _mirror_heights(data, "down") == [40.0, plane + 25.0]                # the lower mirror follows the pd
    assert _part(data, "pd").get("lift") == pytest.approx(10.0)


def test_the_link_holds_at_another_scene_beam_height():
    data, plane = _view(_bench(rise=20.0, lens_height=60.0), beam_height=40.0)
    assert plane == pytest.approx(40.0)
    assert _mirror_heights(data, "up") == [40.0, 60.0]
    assert _part(data, "pd").get("lift") == pytest.approx(20.0)


def test_a_bench_without_a_periscope_keeps_every_part_on_the_bench_plane():
    scene = optodraw.Scene(width=200, height=80, platform="free_space")
    laser = scene.add(optodraw.Laser(center=(-60, 0), label="laser"))
    lens = scene.add(Lens(center=(0, 0), label="lens"))
    pd = scene.add(optodraw.Photodiode(center=(60, 0), label="pd"))
    scene.add(Beam(laser, lens, pd))
    data, plane = _view(scene)
    assert not any(e.get("lift") for e in data)
    assert set(_beam_heights(data, plane)) == {plane}


def test_a_raised_first_part_lifts_the_whole_bench_and_the_periscope_keeps_its_rise():
    data, plane = _view(_bench(rise=25.0, laser_height=50.0))
    assert _part(data, "laser").get("lift") == pytest.approx(20.0)
    assert _mirror_heights(data, "up") == [50.0, 75.0]                          # entry meets the laser's beam
    assert _part(data, "pd").get("lift") == pytest.approx(45.0)


def test_two_parts_that_set_different_heights_in_one_run_warn():
    scene = _bench(rise=25.0, lens_height=70.0)
    next(c for c in scene.walk() if c.label == "pd").beam_height = 60.0
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        data, plane = _view(scene)
    assert any("'pd'" in str(w.message) and "beam_height" in str(w.message) for w in caught), \
        [str(w.message) for w in caught]
    assert _part(data, "pd").get("lift") == pytest.approx(30.0)                 # it still sits where it was put


def test_the_followed_rise_leaves_the_periscope_itself_unchanged():
    scene = _bench(rise=25.0, lens_height=70.0)
    _view(scene)
    up = next(c for c in scene.walk() if c.label == "up")
    assert up.rise == pytest.approx(25.0)                                       # rendering does not edit the scene


def test_a_beam_height_survives_the_editor_spec():
    from optodraw.schema import component_from_spec

    lens = component_from_spec({"type": "Lens", "center": [0, 0], "beam_height": 55})
    assert lens.beam_height == pytest.approx(55.0)
    assert lens.to_dict()["beam_height"] == pytest.approx(55.0)
    periscope = component_from_spec({"type": "Periscope", "center": [0, 0], "beam_height": 40})
    assert periscope.beam_height == pytest.approx(40.0) and not periscope._scene_beam
    assert "beam_height" not in component_from_spec({"type": "Lens", "center": [0, 0]}).to_dict()


def test_a_beam_height_survives_a_scene_spec_round_trip():
    from optodraw.schema import scene_from_spec, scene_to_spec

    spec = scene_to_spec(_bench(rise=25.0, lens_height=70.0))
    lens = next(c for c in spec["components"] if c.get("label") == "lens")
    assert lens["beam_height"] == pytest.approx(70.0)
    assert "beam_height" not in next(c for c in spec["components"] if c.get("label") == "up")
    again = scene_from_spec(spec)
    assert next(c for c in again.walk() if c.label == "lens").beam_height == pytest.approx(70.0)


@pytest.mark.skipif(__import__("optodraw.renderers.capture3d", fromlist=["find_chrome"]).find_chrome(required=False)
                    is None, reason="needs Chrome, Chromium or Edge")
def test_the_viewer_stands_a_raised_part_at_its_height_on_a_taller_post():
    from optodraw.renderers.capture3d import run_page

    html = ThreeJsRenderer(_bench(rise=25.0, lens_height=70.0),
                           capture={"width": 320, "height": 200, "scale": 1, "background": "light"}).render()
    probe = ("<textarea id='od-probe'></textarea><script type='module'>"
             "while (!window.__odView) await new Promise(r => setTimeout(r, 100));"
             "const V = window.__odView, out = [];"
             "try { V.scene.updateMatrixWorld(true);"
             "V.scene.traverse(o => { if (!o.isMesh) return; const b = new V.THREE.Box3().setFromObject(o);"
             "  let p = o; while (p && !p.userData.odComponent) p = p.parent;"
             "  out.push([(b.min.x + b.max.x) / 2, b.min.y, b.max.y, !!p]); });"
             "} catch (e) { out.push(String(e && e.stack || e)); }"
             "document.getElementById('od-probe').value = JSON.stringify(out);</script>")
    meshes = json.loads(run_page(html.replace("</body>", probe + "</body>"), width=320, height=200, timeout=120,
                                 element="od-probe"))
    assert all(isinstance(m, list) for m in meshes), [m for m in meshes if not isinstance(m, list)]
    lens = [m for m in meshes if m[3] and abs(m[0] + 20.0) < 3.0]
    assert lens and min(m[1] for m in lens) < 70.0 < max(m[2] for m in lens), lens       # the lens spans the beam
    under = [m for m in meshes if not m[3] and abs(m[0] + 20.0) < 3.0 and m[2] > 40.0]
    assert under and min(m[1] for m in under) < 10.0 and max(m[2] for m in under) > 60.0, under   # board to lens


def _traced(rise=25.0, lens_height=None, down_rise=None, plane=None):
    """The same bench, but the beams come from the editor's ray tracer (plain points with heights)."""

    from optodraw.app.session import EditorSession

    scene = optodraw.Scene(width=260, height=80, platform="free_space")
    scene.add(optodraw.Laser(center=(-110, 0), label="laser"))
    scene.add(Periscope(center=(-70, 0), rise=rise, label="up"))
    lens = scene.add(Lens(center=(-20, 0), focal_length=40.0, label="lens"))
    if lens_height is not None:
        lens.beam_height = lens_height
    if down_rise is not None:
        scene.add(Periscope(center=(40, 0), rise=down_rise, label="down"))
    scene.add(optodraw.Photodiode(center=(110, 0), label="pd"))
    spec = scene.to_spec()
    if plane is not None:
        spec["beam_height"] = plane
    session = EditorSession(spec)
    session.trace_from(next(c["id"] for c in session.spec["components"] if c["type"] == "Laser"))
    chief = next(b for b in session.spec["beams"] if b.get("ray") == 0)
    return session, [tuple(p) for p in chief["path"]]


def test_a_lens_after_a_periscope_focuses_round_the_raised_axis():
    """The lens measured ray heights from the bench, so it bent the raised beam down to the table."""

    session, chief = _traced(rise=25.0)
    assert all(abs(p[2] - 25.0) < 1e-6 for p in chief[2:]), chief                # the chief ray stays on the axis
    rim = [b["path"] for b in session.spec["beams"] if b.get("ray", 0) > 0]
    end_heights = [p[-1][2] for p in rim]
    assert min(end_heights) > 15.0 and max(end_heights) < 35.0, end_heights      # the rim crosses the raised axis


def test_a_traced_part_with_its_own_height_moves_the_periscope_exit():
    session, chief = _traced(rise=25.0, lens_height=70.0)
    assert [round(p[2], 6) for p in chief[2:]] == [40.0] * (len(chief) - 2), chief


def test_the_tracer_reads_the_scene_beam_height_for_a_part_height():
    session, chief = _traced(rise=25.0, lens_height=70.0, plane=40.0)
    assert [round(p[2], 6) for p in chief[2:]] == [30.0] * (len(chief) - 2), chief


def test_the_viewer_stands_parts_and_mirrors_where_a_traced_beam_runs():
    session, _ = _traced(rise=25.0, down_rise=-10.0)
    data, plane = _view(session.scene())
    assert _part(data, "lens").get("lift") == pytest.approx(25.0, abs=0.05)
    assert _mirror_heights(data, "up") == pytest.approx([plane, plane + 25.0], abs=0.05)
    assert _mirror_heights(data, "down") == pytest.approx([plane + 15.0, plane + 25.0], abs=0.05)
    assert _part(data, "pd").get("lift") == pytest.approx(15.0, abs=0.05)


def test_a_second_beam_from_a_raised_part_rides_at_its_height():
    """A microscope's emission path starts at the scanning mirror, which the excitation path raised: it rode on
    the bench and its beam sloped up to the mirror."""

    scene = optodraw.Scene(width=260, height=120, platform="free_space")
    laser = scene.add(optodraw.Laser(center=(-110, 0), label="laser"))
    up = scene.add(Periscope(center=(-70, 0), rise=25.0, label="up"))
    galvo = scene.add(optodraw.Mirror(center=(-20, 0), label="galvo"))
    lens = scene.add(Lens(center=(-20, -40), label="lens"))
    camera = scene.add(optodraw.Photodiode(center=(-20, -80), label="camera"))
    scene.add(Beam((laser, "out"), (up, "in"), (up, "out"), galvo))
    scene.add(Beam(galvo, lens, camera))
    data, plane = _view(scene)
    assert _part(data, "lens").get("lift") == pytest.approx(25.0)
    assert _part(data, "camera").get("lift") == pytest.approx(25.0)
