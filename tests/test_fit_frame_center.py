"""fit_frame frames the content where it is: a drawing far from the origin gets a frame its own size."""

from __future__ import annotations

import re

import pytest

from optodraw import Lens, Mirror, Scene
from optodraw.schema import scene_from_spec, scene_to_spec


def _off_centre():
    scene = Scene(title="", width=50, height=50, platform="free_space")
    scene.add(Lens(center=(300, 400), label=""))
    scene.add(Mirror(center=(360, 520), label=""))
    return scene


def test_the_frame_is_the_content_and_its_margin_not_twice_the_reach_from_the_origin():
    scene = _off_centre().fit_frame(margin=10, grid=10)
    x0, y0, x1, y1 = scene.content_bounds(10)
    assert scene.width <= (x1 - x0) + 10 and scene.height <= (y1 - y0) + 10
    cx, cy = scene.frame_center
    assert x0 >= cx - scene.width / 2 - 1e-6 and x1 <= cx + scene.width / 2 + 1e-6
    assert y0 >= cy - scene.height / 2 - 1e-6 and y1 <= cy + scene.height / 2 + 1e-6


def test_the_svg_view_box_is_on_the_frame():
    scene = _off_centre().fit_frame(margin=10, grid=10)
    view = [float(v) for v in re.search(r'viewBox="([^"]+)"', scene.render_svg().as_svg()).group(1).split()]
    cx, cy = scene.frame_center
    assert view == pytest.approx([cx - scene.width / 2, -cy - scene.height / 2, scene.width, scene.height])


def test_the_frame_centre_survives_a_save_and_reload():
    scene = _off_centre().fit_frame(margin=10, grid=10)
    assert scene_from_spec(scene_to_spec(scene)).frame_center == pytest.approx(scene.frame_center)


def test_a_scene_round_the_origin_keeps_its_centred_frame():
    scene = Scene(title="", width=50, height=50, platform="free_space")
    scene.add(Lens(center=(0, 0), label=""))
    assert scene.fit_frame().frame_center == pytest.approx((0.0, 0.0))


def test_fit_frame_holds_a_long_label_at_the_edge():
    """A long label on the outer side of the last part must not run past the frame."""

    from optodraw import Lens, Scene, check_figure

    scene = Scene(title="", width=50, height=50, platform="free_space")
    scene.add(Lens(center=(0, 0), label="L1"))
    scene.add(Lens(center=(20, 0), label="A very long objective label", label_side="right"))
    scene.fit_frame(margin=4)
    assert not [f for f in check_figure(scene, view="2d") if "cut off by the frame" in f]
