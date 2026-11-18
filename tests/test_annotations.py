"""Callout, Bracket and DashedLink: the marks a figure adds to name, group and tie its parts."""

import pytest

from optodraw import Beam, Bracket, Callout, DashedLink, Laser, Lens, Mirror, Note, Scene, check_figure
from optodraw.notebook_1d import render_notebook_1d
from optodraw.schema import scene_from_spec, scene_to_spec


def bench():
    scene = Scene(title="Bench", width=120, height=60, platform="free_space")
    laser = scene.add(Laser(center=(-40, 0), label="Laser", label_side="top"))
    lens = scene.add(Lens(center=(0, 0), focal_length=40, label="Lens", label_side="top"))
    mirror = scene.add(Mirror(center=(40, 0), angle=135, label="Mirror", label_side="top"))
    return scene, laser, lens, mirror


def children(mark, scale=1.0):
    return {child["type"]: child for child in mark.annotation_2d(scale)["children"]}


def reloaded(scene, kind):
    return next(n for n in scene_from_spec(scene_to_spec(scene)).walk() if isinstance(n, kind))


# ---------------------------------------------------------------- Callout


def test_the_leader_of_centred_text_leaves_over_or_under_it():
    above = children(Callout("x", center=(0, 10), target=(0, 0), anchor="middle"))["line"]
    below = children(Callout("x", center=(0, -10), target=(0, 0), anchor="middle"))["line"]
    assert above["x1"] == 0.0 and above["y1"] < 0.0
    assert below["x1"] == 0.0 and below["y1"] > 0.0


def test_a_callout_draws_in_svg_and_in_tikz():
    scene, _, lens, _ = bench()
    scene.add(Callout("Focus", center=(20, 18), target=lens))
    svg = scene.render_svg().as_svg()
    assert "<line" in svg and "<circle" in svg and ">Focus<" in svg
    assert "Focus" in scene.render_tikz()


# ---------------------------------------------------------------- Bracket


@pytest.mark.parametrize("bad", [{"side": "up"}])
def test_a_bracket_names_a_bad_side(bad):
    with pytest.raises(ValueError, match="side"):
        Bracket("x", (-10, 0), (10, 0), **bad)


def test_a_bracket_needs_two_places():
    with pytest.raises(ValueError, match="same place"):
        Bracket("x", (5, 5), (5, 5))


def test_a_bracket_draws_with_no_text():
    assert "polyline" in Bracket("", (-10, 0), (10, 0)).annotation_2d()["children"][0]["type"]


# ---------------------------------------------------------------- DashedLink


def test_an_arrow_points_at_the_end():
    mark = DashedLink((0, 0), (10, 0), arrow=True)
    head = next(c for c in mark.annotation_2d()["children"] if c["type"] == "polygon")
    cx, cy = mark.world_position.x, mark.world_position.y
    assert max(x + cx for x, _ in head["points"]) == pytest.approx(10.0)
    assert (10.0 - cx, 0.0 - cy) in [(x, y) for x, y in head["points"]]


def test_tikz_draws_a_link_with_its_dash():
    scene, laser, lens, _ = bench()
    scene.add(DashedLink(laser, lens, text="sync"))
    tex = scene.render_tikz()
    assert "dash pattern" in tex and "sync" in tex


# ---------------------------------------------------------------- with the rest of the package


@pytest.mark.parametrize("mark", [Callout("x", center=(0, 20), target=(0, 0)), Bracket("x", (-10, 20), (10, 20)),
                                  DashedLink((-10, 20), (10, 20), text="x")])
def test_a_mark_stays_out_of_the_parts_and_the_1d_view(mark):
    scene, *_ = bench()
    scene.add(mark)
    assert not any(n is mark for n in scene._parts())
    assert "Bracket" not in render_notebook_1d(scene)


def test_the_gate_reads_a_mark_as_a_note():
    scene, _, lens, _ = bench()
    scene.add(Callout("a callout that runs on for many more words", center=(10, 20), target=lens))
    assert not [f for f in check_figure(scene, view="2d") if "name the part in" in f]


def test_the_gate_finds_a_leader_across_a_label():
    scene, _, lens, mirror = bench()
    scene.add(Note("Key", center=(20, 12), anchor="middle"))
    scene.add(Callout("Focus", center=(40, 24), target=(0, 0)))
    found = [f for f in check_figure(scene, view="2d") if "leader" in f]
    assert len(found) == 1 and '"Focus"' in found[0] and '"Key"' in found[0]


def test_the_gate_finds_a_leader_across_a_part():
    scene, laser, lens, mirror = bench()
    scene.add(Callout("Far", center=(70, 0), target=(laser, "out"), anchor="start"))
    found = [f for f in check_figure(scene, view="2d") if "leader" in f]
    assert any("Mirror" in f for f in found)


def test_a_beam_is_no_reason_to_move_a_mark():
    scene, laser, lens, mirror = bench()
    scene.add(Beam((laser, "out"), (lens, "in"), (lens, "out"), (mirror, "io"), wavelength=635))
    scene.add(Bracket("Telescope", laser, lens))
    assert not [f for f in check_figure(scene, view="2d") if "Telescope" in f and "far" in f]


# ---------------------------------------------------------------- in the editor

def session_with(mark):
    from optodraw.app.session import EditorSession

    scene, *_ = bench()
    scene.add(mark)
    session = EditorSession(scene_to_spec(scene))
    entry = next(c for c in session.spec["components"] if c["type"] == mark.component_type)
    return session, entry["id"]


def built(session, kind):
    return next(n for n in scene_from_spec(session.spec).walk() if isinstance(n, kind))


