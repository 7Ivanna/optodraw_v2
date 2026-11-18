"""One look for the light of a figure: nested bands on the axis, cut on the mirror, and one place to change them."""

from __future__ import annotations

import re

import pytest

from optodraw import Beam, BeamStyle, Laser, Mirror, Photodiode, Scene
from optodraw.app.session import EditorSession
from optodraw.layout import aim, face
from optodraw.schema import scene_from_spec, scene_to_spec


def _fold():
    scene = Scene(title="fold", width=100, height=80, platform="free_space")
    laser = scene.add(Laser(center=(-30, 0), label="Laser"))
    mirror = scene.add(Mirror(center=(0, 0), label="M", label_side="bottom-right"))
    pd = scene.add(Photodiode(center=(0, 30), label="PD"))
    aim(mirror, laser, pd)
    face(pd, mirror)
    return scene, laser, mirror, pd


UP_AT_ORIGIN = [(-10.0, 0.0, 0.0), (0.0, 0.0, 0.0), (0.0, 10.0, 0.0)]


def _inside(quads, x, y):
    def within(quad):
        signs = [(b[0] - a[0]) * (y - a[1]) - (b[1] - a[1]) * (x - a[0]) for a, b in zip(quad, quad[1:] + quad[:1])]
        return all(sign >= 0.0 for sign in signs) or all(sign <= 0.0 for sign in signs)

    return any(within(quad) for quad in quads)


def test_a_beam_in_a_group_finds_the_scene():
    scene = Scene(title="s", beam_style=BeamStyle(opacity=0.35))
    assert scene.group("arm").add(Beam((0, 0), (10, 0))).opacity == 0.35


@pytest.mark.parametrize("kwargs", [{"opacity": 0.0}, {"opacity": 1.5}, {"scale": 0.0}, {"by_wavelength": -1.0}])
def test_a_style_out_of_range_is_refused(kwargs):
    with pytest.raises(ValueError):
        BeamStyle(**kwargs)


def test_the_style_survives_a_save():
    scene = Scene(title="s", beam_style=BeamStyle(opacity=0.4, scale=1.5, by_wavelength=0.5))
    scene.add(Beam((0, 0), (10, 0)))
    loaded = scene_from_spec(scene_to_spec(scene))
    assert loaded.beam_style == BeamStyle(opacity=0.4, scale=1.5, by_wavelength=0.5)


def test_the_editor_sets_the_opacity_and_the_lane_of_one_beam():
    session = EditorSession()
    first = session.add_component("Laser", {"center": [-30, 0]})
    second = session.add_component("Photodiode", {"center": [30, 0], "angle": 180})
    session.update(session.add_beam([first, second]), {"opacity": 0.3, "offset": 1.5})
    drawn = next(n for n in session.scene().walk() if isinstance(n, Beam))
    assert (drawn.opacity, drawn.offset) == (0.3, 1.5)


def test_the_envelope_of_a_bundle_keeps_its_strength():
    scene = Scene(title="s", width=60, height=40, platform="free_space")
    scene.add(Beam((0, 0), (20, 5), (20, -5), (0, 0), envelope=True))
    assert re.search(r'opacity="0\.15\d*"', scene.render_svg().as_svg())


