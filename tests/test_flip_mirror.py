"""A flip mirror stands in the beam or out of it, and the checks, the tracer and the animation know which."""

from __future__ import annotations

import re

import pytest

from optodraw import Beam, FlipMirror, Laser, Photodiode, Scene
from optodraw.animation_engine.behaviours import find_behaviour
from optodraw.app.validation import run_checks
from optodraw.core.beam import beam_point


def _bench(state, route="io"):
    """A laser from the left onto the mirror at 45 degrees: up it folds the beam to the top, down it runs on."""

    scene = Scene(title="flip", width=120, height=90, platform="free_space")
    flip = scene.add(FlipMirror(center=(0, 0), angle=-45, state=state, label="Flip"))
    at = beam_point(flip, route)
    laser = scene.add(Laser(center=(-40, at.y), wavelength=635, label="Laser"))
    top = scene.add(Photodiode(center=(at.x, 30), angle=270, label="Top"))
    right = scene.add(Photodiode(center=(40, at.y), angle=180, label="Right"))
    end = top if route == "io" else right
    beam = scene.add(Beam((laser, "out"), (flip, route), (end, "in"), wavelength=635))
    return scene, flip, beam


def _flip_messages(scene):
    return [issue["message"] for issue in run_checks(scene) if "Flip" in issue["message"]]


def test_a_state_it_does_not_have_is_refused():
    with pytest.raises(ValueError, match="up, down or both"):
        FlipMirror(state="sideways")


def test_it_says_when_it_reflects():
    assert FlipMirror(state="up").physics_metadata()["reflective"] is True
    assert FlipMirror(state="both").physics_metadata()["reflective"] is True
    assert FlipMirror(state="down").physics_metadata()["reflective"] is False


def test_the_svg_and_the_tikz_draw_the_outline():
    scene, _, _ = _bench("up")
    assert "stroke-dasharray" in scene.render_svg().as_svg()
    assert re.search(r"dash pattern", scene.render_tikz())


def test_a_beam_straight_through_a_mirror_that_is_up_is_blocked():
    messages = _flip_messages(_bench("up", "pass")[0])
    assert len(messages) == 1 and "blocks" in messages[0] and "state" in messages[0]


def test_a_beam_folded_by_a_mirror_that_is_down_has_nothing_to_fold_it():
    messages = _flip_messages(_bench("down", "io")[0])
    assert len(messages) == 1 and "out of the beam" in messages[0] and "state" in messages[0]


def test_light_on_the_back_of_a_mirror_that_is_up_is_still_found():
    scene = Scene(title="flip", width=120, height=90, platform="free_space")
    laser = scene.add(Laser(center=(40, 0), angle=180, wavelength=635, label="Laser"))
    flip = scene.add(FlipMirror(center=(0, 0), angle=-45, label="Flip"))
    top = scene.add(Photodiode(center=(0, 30), angle=270, label="Top"))
    scene.add(Beam((laser, "out"), (flip, "io"), (top, "in"), wavelength=635))
    assert any("from behind" in message for message in _flip_messages(scene))


def _ports(part, port):
    behaviour = find_behaviour(part)
    return sorted(t.out_port for t in behaviour.transfers(part, "p1", port, 635.0, {}) if t.matrix.any())


@pytest.mark.parametrize("state, io, through", [("up", ["io"], []), ("down", [], ["pass"]), ("both", ["io"], ["pass"])])
def test_the_animation_takes_the_route_the_state_allows(state, io, through):
    flip = FlipMirror(state=state)
    assert _ports(flip, "io") == io
    assert _ports(flip, "pass") == through


def test_down_the_3d_mirror_drops_out_of_the_beam():
    def top(part):
        from optodraw.check import solid_boxes

        return max(box[1][1] for _, box in solid_boxes(part.geometry_3d()))

    assert top(FlipMirror(state="down")) < top(FlipMirror(state="up"))


