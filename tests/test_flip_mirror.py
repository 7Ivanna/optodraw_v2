"""A flip mirror stands in the beam or out of it, and the checks, the tracer and the animation know which."""

from __future__ import annotations

import math
import re

import pytest

from optodraw import Beam, FlipMirror, Laser, Note, Photodiode, Scene, check_figure
from optodraw.animation_engine.behaviours import find_behaviour
from optodraw.app.validation import run_checks
from optodraw.check import check_part_3d
from optodraw.core.beam import beam_point
from optodraw.core.raytrace import trace_branched
from optodraw.layout import estimate_component_bounds
from optodraw.registry import build_component
from optodraw.schema import scene_from_spec, scene_to_spec
from optodraw.symbols.art import art_2d


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


def test_it_is_built_from_the_registry():
    assert build_component("FlipMirror", state="down").state == "down"


def test_a_state_it_does_not_have_is_refused():
    with pytest.raises(ValueError, match="up, down or both"):
        FlipMirror(state="sideways")


def test_it_keeps_its_state_and_its_out_place_through_a_save():
    scene, _, _ = _bench("both")
    scene.add(FlipMirror(center=(0, -30), state="down", out_offset=-9.0))
    flips = [n for n in scene_from_spec(scene_to_spec(scene)).walk() if isinstance(n, FlipMirror)]
    assert [(f.state, f.out_offset) for f in flips] == [("both", flips[0].out_offset), ("down", -9.0)]


def test_it_has_the_mirror_port_and_a_straight_route():
    flip = FlipMirror(center=(0, 0), angle=135)
    assert set(flip.ports()) == {"io", "pass"}
    assert flip.world_port("pass").center.as_tuple()[:2] == pytest.approx((0.0, 0.0))


def test_the_straight_route_crosses_where_the_fold_does():
    """A bench lined up on ``io`` stays one straight line when the mirror goes down."""

    flip = FlipMirror(center=(3, 4), angle=-45, thickness=2.0)
    assert beam_point(flip, "pass").as_tuple() == pytest.approx(beam_point(flip, "io").as_tuple())


def test_it_says_when_it_reflects():
    assert FlipMirror(state="up").physics_metadata()["reflective"] is True
    assert FlipMirror(state="both").physics_metadata()["reflective"] is True
    assert FlipMirror(state="down").physics_metadata()["reflective"] is False


def test_up_it_is_painted_as_the_mirror_beside_it():
    from optodraw import Mirror

    flip, mirror = art_2d(FlipMirror(center=(0, 0))), art_2d(Mirror(center=(0, 0)))
    assert flip["symbol"] == "flipmirror"
    assert flip["matrix"] == pytest.approx(mirror["matrix"])      # the same size in the same place


def test_down_the_painted_mirror_moves_to_its_out_place():
    up, down = art_2d(FlipMirror(state="up", out_offset=14.0)), art_2d(FlipMirror(state="down", out_offset=14.0))
    assert down["matrix"][4] == pytest.approx(up["matrix"][4])
    assert down["matrix"][5] == pytest.approx(up["matrix"][5] - 14.0)  # SVG y runs down; out is up the mirror face


@pytest.mark.parametrize("state, y", [("up", 14.0), ("both", 14.0), ("down", 0.0)])
def test_the_dashed_outline_marks_where_the_mirror_is_not(state, y):
    outline = art_2d(FlipMirror(state=state, out_offset=14.0))["outline"]
    assert outline["stroke_dasharray"]
    ys = [point[1] for point in outline["points"]]
    assert (min(ys) + max(ys)) / 2.0 == pytest.approx(y, abs=0.01)


def test_the_out_place_counts_in_the_frame():
    x0, y0, x1, y1 = estimate_component_bounds(FlipMirror(out_offset=14.0))
    assert y1 > 14.0 + 3.0                                        # the outline's far end, not only its centre
    assert y0 < -3.0                                              # and the mirror itself


def test_the_svg_and_the_tikz_draw_the_outline():
    scene, _, _ = _bench("up")
    assert "stroke-dasharray" in scene.render_svg().as_svg()
    assert re.search(r"dash pattern", scene.render_tikz())


def test_a_beam_folded_by_a_mirror_that_is_up_is_right():
    assert _flip_messages(_bench("up")[0]) == []


def test_a_beam_straight_through_a_mirror_that_is_up_is_blocked():
    messages = _flip_messages(_bench("up", "pass")[0])
    assert len(messages) == 1 and "blocks" in messages[0] and "state" in messages[0]


def test_a_beam_straight_through_a_mirror_that_is_down_is_right():
    assert _flip_messages(_bench("down", "pass")[0]) == []


def test_a_beam_folded_by_a_mirror_that_is_down_has_nothing_to_fold_it():
    messages = _flip_messages(_bench("down", "io")[0])
    assert len(messages) == 1 and "out of the beam" in messages[0] and "state" in messages[0]


@pytest.mark.parametrize("route", ["io", "pass"])
def test_both_lets_one_figure_show_the_two_routes(route):
    assert _flip_messages(_bench("both", route)[0]) == []


def test_light_on_the_back_of_a_mirror_that_is_up_is_still_found():
    scene = Scene(title="flip", width=120, height=90, platform="free_space")
    laser = scene.add(Laser(center=(40, 0), angle=180, wavelength=635, label="Laser"))
    flip = scene.add(FlipMirror(center=(0, 0), angle=-45, label="Flip"))
    top = scene.add(Photodiode(center=(0, 30), angle=270, label="Top"))
    scene.add(Beam((laser, "out"), (flip, "io"), (top, "in"), wavelength=635))
    assert any("from behind" in message for message in _flip_messages(scene))


def _traced_end(state):
    scene = Scene(title="flip", width=120, height=90, platform="free_space")
    laser = scene.add(Laser(center=(-40, 0), wavelength=635))
    scene.add(FlipMirror(center=(0, 0), angle=-45, state=state))
    (result,) = trace_branched(scene, (laser, "out"), mode="physical", wavelength_nm=635.0, exit_length=30)
    return result.points[-1]


@pytest.mark.parametrize("state", ["up", "both"])
def test_the_tracer_reflects_off_a_mirror_in_the_beam(state):
    end = _traced_end(state)
    assert abs(end.x) < 1.0 and abs(end.y) == pytest.approx(30.0, abs=1.0)


def test_the_tracer_runs_straight_past_a_mirror_out_of_the_beam():
    end = _traced_end("down")
    assert abs(end.y) < 1e-6                                      # the ray stays on its line to the end of its run


def _ports(part, port):
    behaviour = find_behaviour(part)
    return sorted(t.out_port for t in behaviour.transfers(part, "p1", port, 635.0, {}) if t.matrix.any())


@pytest.mark.parametrize("state, io, through", [("up", ["io"], []), ("down", [], ["pass"]), ("both", ["io"], ["pass"])])
def test_the_animation_takes_the_route_the_state_allows(state, io, through):
    flip = FlipMirror(state=state)
    assert _ports(flip, "io") == io
    assert _ports(flip, "pass") == through


@pytest.mark.parametrize("state", ["up", "down", "both"])
def test_the_3d_part_holds_together(state):
    assert check_part_3d(FlipMirror(state=state)) == []


def test_down_the_3d_mirror_drops_out_of_the_beam():
    def top(part):
        from optodraw.check import solid_boxes

        return max(box[1][1] for _, box in solid_boxes(part.geometry_3d()))

    assert top(FlipMirror(state="down")) < top(FlipMirror(state="up"))


def test_a_label_on_the_dashed_outline_is_found():
    scene, flip, _ = _bench("up")
    x = flip.out_offset * math.cos(math.radians(45.0))
    scene.add(Note("ND wheel", center=(x, x)))
    assert any('"ND wheel" sits on Flip' in finding for finding in check_figure(scene, view="2d"))


def test_a_label_clear_of_the_outline_is_left_alone():
    scene, _, _ = _bench("up")
    scene.add(Note("ND wheel", center=(-25, 25)))
    assert not any('"ND wheel" sits on' in finding for finding in check_figure(scene, view="2d"))


def test_in_1d_it_stands_and_meets_its_beams_as_a_mirror_does():
    """The removable mirror of the confocal PL preset: the main beam runs on through it, a second folds to the fibre.
    Its 1D symbol read its face as the bottom edge (the outline of its other place makes the box tall) and stood a
    quarter turn round, and the straight route met it off its face."""

    from optodraw import Mirror
    from optodraw.presets import build_preset
    from optodraw.symbols import lookup
    from optodraw.symbols.art import fit_art
    from optodraw.symbols.schematic import build_schematic

    flip, plain = FlipMirror(angle=45, state="both"), Mirror(angle=45)
    assert fit_art(flip, lookup(flip)).turn == fit_art(plain, lookup(plain)).turn
    scene = build_preset("confocal_pl")
    assert check_figure(scene, view="1d") == []
    item = next(item for item in build_schematic(scene).items if item.component.component_type == "FlipMirror")
    assert item.port("pass")[:2] == item.port("io")[:2]
