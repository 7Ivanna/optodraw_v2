"""Callout, Bracket and DashedLink: the marks a figure adds to name, group and tie its parts."""

import pytest

from optodraw import Beam, Bracket, Callout, DashedLink, Laser, Lens, Mirror, Note, Scene, check_figure
from optodraw.core.component import ANNOTATION_TYPES, NON_PART_TYPES
from optodraw.notebook_1d import render_notebook_1d
from optodraw.registry import build_component
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

def test_a_callout_ends_in_a_dot_on_its_target():
    mark = Callout("Focus", center=(20, 10), target=(0, 0))
    parts = children(mark)
    assert (parts["circle"]["cx"], parts["circle"]["cy"]) == (-20, -10)
    assert (parts["line"]["x2"], parts["line"]["y2"]) == (-20, -10)


def test_a_callout_names_a_part_or_a_port():
    _, laser, lens, _ = bench()
    assert Callout("x", center=(0, 20), target=lens).target == (0.0, 0.0)
    assert Callout("x", center=(0, 20), target=(laser, "out")).target == pytest.approx(
        (laser.world_port("out").center.x, laser.world_port("out").center.y))


def test_the_text_of_a_callout_starts_at_the_end_near_its_target():
    assert Callout("x", center=(20, 10), target=(0, 0)).anchor == "start"
    assert Callout("x", center=(-20, 10), target=(0, 0)).anchor == "end"
    assert Callout("x", center=(-20, 10), target=(0, 0), anchor="middle").anchor == "middle"


def test_the_leader_leaves_the_end_of_the_text_near_the_target():
    assert children(Callout("x", center=(20, 10), target=(0, 0)))["line"]["x1"] < 0.0
    assert children(Callout("x", center=(-20, 10), target=(0, 0)))["line"]["x1"] > 0.0


def test_the_leader_of_centred_text_leaves_over_or_under_it():
    above = children(Callout("x", center=(0, 10), target=(0, 0), anchor="middle"))["line"]
    below = children(Callout("x", center=(0, -10), target=(0, 0), anchor="middle"))["line"]
    assert above["x1"] == 0.0 and above["y1"] < 0.0
    assert below["x1"] == 0.0 and below["y1"] > 0.0


def test_a_leader_keeps_its_share_of_the_text_at_any_font_size():
    mark = Callout("x", center=(20, 10), target=(0, 0))
    assert children(mark, 2.0)["line"]["stroke_width"] == 2.0 * children(mark)["line"]["stroke_width"]
    assert children(mark, 2.0)["circle"]["r"] == 2.0 * children(mark)["circle"]["r"]


def test_a_moved_callout_keeps_its_target():
    mark = Callout("x", center=(20, 10), target=(0, 0))
    mark.transform.position.x += 5.0
    assert mark.target == (0.0, 0.0)
    assert children(mark)["circle"]["cx"] == -25.0


def test_a_callout_draws_in_svg_and_in_tikz():
    scene, _, lens, _ = bench()
    scene.add(Callout("Focus", center=(20, 18), target=lens))
    svg = scene.render_svg().as_svg()
    assert "<line" in svg and "<circle" in svg and ">Focus<" in svg
    assert "Focus" in scene.render_tikz()


def test_a_saved_callout_comes_back():
    scene, _, lens, _ = bench()
    scene.add(Callout("Focus", center=(20, 18), target=lens, color="#112233"))
    back = reloaded(scene, Callout)
    assert (back.text, back.target, back.anchor, back.color) == ("Focus", (0.0, 0.0), "start", "#112233")
    assert (back.world_position.x, back.world_position.y) == (20.0, 18.0)


def test_the_frame_holds_a_target_past_the_parts():
    scene, *_ = bench()
    x0, y0, x1, y1 = scene.content_bounds()
    scene.add(Callout("x", center=(0, 10), target=(0, y1 + 30)))
    assert scene.content_bounds()[3] >= y1 + 30


# ---------------------------------------------------------------- Bracket

def test_a_bracket_runs_beside_its_span():
    mark = Bracket("Telescope", (-10, 0), (10, 0))
    points = mark.annotation_2d()["children"][0]["points"]
    cx, cy = mark.world_position.x, mark.world_position.y
    world = [(x + cx, y + cy) for x, y in points]
    assert world == pytest.approx([(-10, 1.0), (-10, 2.5), (10, 2.5), (10, 1.0)])


def test_the_side_of_a_bracket_is_taken_along_the_span():
    left = Bracket("x", (-10, 0), (10, 0), side="left")
    right = Bracket("x", (-10, 0), (10, 0), side="right")
    assert left.world_position.y > 0.0 > right.world_position.y


def test_text_beside_an_upright_bracket_starts_at_it():
    up = Bracket("x", (0, -10), (0, 10), side="right")
    assert up.anchor == "start" and up.world_position.x > 2.5
    assert Bracket("x", (0, -10), (0, 10), side="left").anchor == "end"


def test_text_over_a_flat_bracket_clears_the_bracket():
    mark = Bracket("x", (-10, 0), (10, 0))
    assert mark.anchor == "middle" and mark.world_position.y - 1.5 >= 2.5


def test_a_bracket_spans_parts_and_ports():
    _, laser, lens, _ = bench()
    mark = Bracket("x", laser, lens)
    assert mark.start == pytest.approx((-40.0, 0.0)) and mark.end == pytest.approx((0.0, 0.0))
    mark = Bracket("x", (laser, "out"), lens)
    assert mark.start[0] == pytest.approx(laser.world_port("out").center.x)


def test_a_moved_bracket_moves_whole():
    mark = Bracket("x", (-10, 0), (10, 0))
    mark.transform.position.x += 5.0
    assert mark.start == pytest.approx((-5.0, 0.0)) and mark.end == pytest.approx((15.0, 0.0))


@pytest.mark.parametrize("bad", [{"side": "up"}])
def test_a_bracket_names_a_bad_side(bad):
    with pytest.raises(ValueError, match="side"):
        Bracket("x", (-10, 0), (10, 0), **bad)


def test_a_bracket_needs_two_places():
    with pytest.raises(ValueError, match="same place"):
        Bracket("x", (5, 5), (5, 5))


def test_a_bracket_draws_with_no_text():
    assert "polyline" in Bracket("", (-10, 0), (10, 0)).annotation_2d()["children"][0]["type"]


def test_a_saved_bracket_comes_back():
    scene, laser, lens, _ = bench()
    scene.add(Bracket("Telescope", laser, lens, side="right", clear=2.0, depth=3.0))
    back = reloaded(scene, Bracket)
    assert (back.text, back.side, back.clear, back.depth) == ("Telescope", "right", 2.0, 3.0)
    assert back.start == pytest.approx((-40.0, 0.0)) and back.end == pytest.approx((0.0, 0.0))


def test_the_frame_holds_a_bracket():
    scene, *_ = bench()
    _, _, _, top = scene.content_bounds()
    scene.add(Bracket("", (-10, top + 20), (10, top + 20)))
    assert scene.content_bounds()[3] >= top + 20


# ---------------------------------------------------------------- DashedLink

def test_a_dashed_link_joins_two_parts_and_is_dashed():
    scene, laser, lens, _ = bench()
    mark = scene.add(DashedLink(laser, lens))
    line = mark.annotation_2d()["children"][0]
    assert line["stroke_dasharray"]
    assert 'stroke-dasharray=' in scene.render_svg().as_svg()
    assert mark.start == pytest.approx((-40.0, 0.0)) and mark.end == pytest.approx((0.0, 0.0))


def test_a_link_can_be_solid():
    assert not DashedLink((0, 0), (10, 0), dashed=False).annotation_2d()["children"][0].get("stroke_dasharray")


def test_an_arrow_points_at_the_end():
    mark = DashedLink((0, 0), (10, 0), arrow=True)
    head = next(c for c in mark.annotation_2d()["children"] if c["type"] == "polygon")
    cx, cy = mark.world_position.x, mark.world_position.y
    assert max(x + cx for x, _ in head["points"]) == pytest.approx(10.0)
    assert (10.0 - cx, 0.0 - cy) in [(x, y) for x, y in head["points"]]


def test_the_text_of_a_link_stands_beside_its_middle():
    mark = DashedLink((0, 0), (10, 0), text="sync", side="left")
    assert mark.world_position.x == 5.0 and mark.world_position.y > 0.0


def test_a_saved_link_comes_back():
    scene, laser, lens, _ = bench()
    scene.add(DashedLink(laser, lens, text="sync", arrow=True, dashed=False))
    back = reloaded(scene, DashedLink)
    assert (back.text, back.arrow, back.dashed) == ("sync", True, False)
    assert back.end == pytest.approx((0.0, 0.0))


def test_tikz_draws_a_link_with_its_dash():
    scene, laser, lens, _ = bench()
    scene.add(DashedLink(laser, lens, text="sync"))
    tex = scene.render_tikz()
    assert "dash pattern" in tex and "sync" in tex


# ---------------------------------------------------------------- with the rest of the package

@pytest.mark.parametrize("name", ["Note", "Callout", "Bracket", "DashedLink"])
def test_each_mark_is_built_by_name_and_is_no_part(name):
    assert name in ANNOTATION_TYPES and name in NON_PART_TYPES
    assert build_component(name).ports() == {}


@pytest.mark.parametrize("mark", [Callout("x", center=(0, 20), target=(0, 0)), Bracket("x", (-10, 20), (10, 20)),
                                  DashedLink((-10, 20), (10, 20), text="x")])
def test_a_mark_stays_out_of_the_parts_and_the_1d_view(mark):
    scene, *_ = bench()
    scene.add(mark)
    assert not any(n is mark for n in scene._parts())
    assert "Bracket" not in render_notebook_1d(scene)


def test_a_mark_may_carry_markup():
    scene, *_ = bench()
    scene.add(Callout("f_p", center=(20, 18), target=(0, 0)))
    assert "<tspan" in scene.render_svg().as_svg()


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


def test_a_leader_to_its_own_part_passes():
    scene, _, lens, _ = bench()
    scene.add(Callout("Focus", center=(20, 18), target=lens))
    assert not [f for f in check_figure(scene, view="2d") if "leader" in f]


def test_a_beam_is_no_reason_to_move_a_mark():
    scene, laser, lens, mirror = bench()
    scene.add(Beam((laser, "out"), (lens, "in"), (lens, "out"), (mirror, "io"), wavelength=635))
    scene.add(Bracket("Telescope", laser, lens))
    assert not [f for f in check_figure(scene, view="2d") if "Telescope" in f and "far" in f]


def test_the_gate_finds_a_label_on_a_dashed_link():
    scene, laser, lens, mirror = bench()
    scene.add(DashedLink((-40, 9.5), (40, 9.5)))                       # along the label row
    assert any('"Lens" sits on' in f for f in check_figure(scene, view="2d"))


def test_a_link_leaves_its_own_text_alone():
    scene, laser, lens, mirror = bench()
    scene.add(DashedLink((-40, 20), (40, 20), text="sync"))
    assert not [f for f in check_figure(scene, view="2d") if "sync" in f]


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


@pytest.mark.parametrize("name, kind", [("Callout", Callout), ("Bracket", Bracket), ("DashedLink", DashedLink)])
def test_a_mark_dropped_from_the_palette_draws_where_it_was_dropped(name, kind):
    from optodraw.app.session import EditorSession

    session = EditorSession()
    session.add_component(name, {"center": [60.0, 20.0]})
    points = built(session, kind).drawn_points()
    assert all(abs(x - 60.0) <= 20.0 and abs(y - 20.0) <= 20.0 for x, y in points)


def test_a_dragged_bracket_moves_whole():
    session, ident = session_with(Bracket("Telescope", (-10, 20), (10, 20)))
    before = built(session, Bracket).start
    place = built(session, Bracket).world_position
    session.move_component(ident, center=[place.x + 5.0, place.y + 3.0])
    assert built(session, Bracket).start == pytest.approx((before[0] + 5.0, before[1] + 3.0))


def test_a_dragged_link_moves_whole():
    session, ident = session_with(DashedLink((-10, 20), (10, 20), text="sync"))
    before = built(session, DashedLink).end
    place = built(session, DashedLink).world_position
    session.move_component(ident, center=[place.x + 5.0, place.y])
    assert built(session, DashedLink).end == pytest.approx((before[0] + 5.0, before[1]))


def test_dragging_a_callout_moves_its_text_and_keeps_its_dot():
    session, ident = session_with(Callout("Focus", center=(20, 18), target=(0, 0)))
    session.move_component(ident, center=[30.0, 25.0])
    mark = built(session, Callout)
    assert mark.target == (0.0, 0.0) and mark.world_position.x == 30.0


def test_a_changed_side_keeps_the_ends():
    session, ident = session_with(Bracket("x", (-10, 20), (10, 20)))
    session.update(ident, {"side": "right"})
    mark = built(session, Bracket)
    assert mark.side == "right" and mark.end[0] - mark.start[0] == pytest.approx(20.0)


def test_text_beside_a_slanted_link_clears_the_link():
    from optodraw.check import _hits, _label_box

    mark = DashedLink((-40, 12), (40, -12), text="trigger signal", side="right")
    assert not _hits(mark.start, mark.end, _label_box(mark, 8.0))
