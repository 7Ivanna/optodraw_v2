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


def _mirror_heights(data, label):
    return sorted(round(c["position"][1], 6) for c in _part(data, label)["geometry"]["children"]
                  if c.get("role") == "mirror")


def test_the_link_holds_at_another_scene_beam_height():
    data, plane = _view(_bench(rise=20.0, lens_height=60.0), beam_height=40.0)
    assert plane == pytest.approx(40.0)
    assert _mirror_heights(data, "up") == [40.0, 60.0]
    assert _part(data, "pd").get("lift") == pytest.approx(20.0)


def test_two_parts_that_set_different_heights_in_one_run_warn():
    scene = _bench(rise=25.0, lens_height=70.0)
    next(c for c in scene.walk() if c.label == "pd").beam_height = 60.0
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        data, plane = _view(scene)
    assert any("'pd'" in str(w.message) and "beam_height" in str(w.message) for w in caught), \
        [str(w.message) for w in caught]
    assert _part(data, "pd").get("lift") == pytest.approx(30.0)                 # it still sits where it was put


def test_a_beam_height_survives_the_editor_spec():
    from optodraw.schema import component_from_spec

    lens = component_from_spec({"type": "Lens", "center": [0, 0], "beam_height": 55})
    assert lens.beam_height == pytest.approx(55.0)
    assert lens.to_dict()["beam_height"] == pytest.approx(55.0)
    periscope = component_from_spec({"type": "Periscope", "center": [0, 0], "beam_height": 40})
    assert periscope.beam_height == pytest.approx(40.0) and not periscope._scene_beam
    assert "beam_height" not in component_from_spec({"type": "Lens", "center": [0, 0]}).to_dict()


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


def test_a_traced_part_with_its_own_height_moves_the_periscope_exit():
    session, chief = _traced(rise=25.0, lens_height=70.0)
    assert [round(p[2], 6) for p in chief[2:]] == [40.0] * (len(chief) - 2), chief


def test_the_viewer_stands_parts_and_mirrors_where_a_traced_beam_runs():
    session, _ = _traced(rise=25.0, down_rise=-10.0)
    data, plane = _view(session.scene())
    assert _part(data, "lens").get("lift") == pytest.approx(25.0, abs=0.05)
    assert _mirror_heights(data, "up") == pytest.approx([plane, plane + 25.0], abs=0.05)
    assert _mirror_heights(data, "down") == pytest.approx([plane + 15.0, plane + 25.0], abs=0.05)
    assert _part(data, "pd").get("lift") == pytest.approx(15.0, abs=0.05)


