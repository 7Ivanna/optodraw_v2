"""An Anchor names a place inside an inset: marks that hold one stay on that place when the inset moves."""

import pytest

from optodraw.core.transform import Transform
from optodraw import Bracket, Callout, DashedLink, Inset, Note, Scene
from optodraw.core.view_layout import display_scene

SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 20"><rect width="40" height="20"/></svg>'


def _scene(tmp_path, **options):                    # a 40 by 20 file in a scene, centred at the origin
    path = tmp_path / "a.svg"
    path.write_text(SVG)
    scene = Scene(width=200, height=120)
    inset = scene.add(Inset(str(path), center=(0, 0), width=40.0, **options))
    return scene, inset


def test_at_maps_the_file_point_to_the_scene(tmp_path):
    scene, inset = _scene(tmp_path)
    assert inset.at(0, 0).xy() == pytest.approx((-20, 10))        # file y runs down, scene y runs up
    assert inset.at(40, 20).xy() == pytest.approx((20, -10))


def test_the_anchor_is_live(tmp_path):
    scene, inset = _scene(tmp_path)
    target = inset.at(10, 5)
    inset.move_to(30, 7)
    assert tuple(target) == pytest.approx((20, 12))


def test_the_anchor_acts_as_a_pair(tmp_path):
    scene, inset = _scene(tmp_path)
    x, y = inset.at(10, 5)
    assert (x, y) == pytest.approx((-10, 5)) and len(inset.at(10, 5)) == 2


def test_a_callout_keeps_its_point_and_moves_with_the_inset(tmp_path):
    scene, inset = _scene(tmp_path)
    call = scene.add(Callout("Heater", center=(50, 30), target=inset.at(10, 5)))
    inset.move_to(30, 7)
    assert call.target[0] == pytest.approx(20) and call.world_position.x == pytest.approx(80)
    assert call.world_position.y == pytest.approx(37)


def test_a_note_and_a_dashed_link_follow_too(tmp_path):
    scene, inset = _scene(tmp_path)
    note = scene.add(Note("A", center=inset.at(10, 5)))
    link = scene.add(DashedLink(inset.at(0, 0), (60, 40), text="x"))
    bracket = scene.add(Bracket("b", inset.at(0, 20), inset.at(40, 20)))
    before = [link.start, link.end, bracket.start, bracket.end]
    inset.move_to(30, 7)
    assert (note.world_position.x, note.world_position.y) == pytest.approx((20, 12))
    assert link.start == pytest.approx((10, 17)) and link.end == pytest.approx((60, 40))
    assert bracket.start == pytest.approx((before[2][0] + 30, before[2][1] + 7))
    assert bracket.end == pytest.approx((before[3][0] + 30, before[3][1] + 7))


def test_a_mark_of_another_inset_stays(tmp_path):
    scene, inset = _scene(tmp_path)
    other = scene.add(Inset(center=(80, 0), width=20.0))
    call = scene.add(Callout("Far", center=(80, 30), target=other.at(5, 5)))
    inset.move_to(30, 7)
    assert call.world_position.x == pytest.approx(80) and call.world_position.y == pytest.approx(30)


def test_a_rotated_inset_keeps_its_point(tmp_path):
    scene, inset = _scene(tmp_path, angle=90.0)
    assert inset.at(40, 10).xy() == pytest.approx((0, 20))


def test_display_scene_copy_keeps_the_anchor(tmp_path):
    scene, inset = _scene(tmp_path)
    scene.add(Callout("Heater", center=(50, 30), target=inset.at(10, 5)))
    scene.set_view_layout({"2d": {"spacing": 2}})
    copy = display_scene(scene, "2d")
    new_inset = next(n for n in copy.walk() if isinstance(n, Inset))
    new_call = next(n for n in copy.walk() if isinstance(n, Callout))
    assert new_call.target.inset is new_inset and new_inset is not inset
    assert tuple(new_call.target) == pytest.approx(new_inset.at(10, 5).xy())


def test_a_span_across_two_insets_keeps_both_ends(tmp_path):
    scene, a = _scene(tmp_path)
    b = scene.add(Inset(center=(80, 0), width=20.0))
    link = scene.add(DashedLink(a.at(40, 10), b.at(0, 10)))
    a.move_to(-50, 30)
    assert link.start == pytest.approx(a.at(40, 10).xy()) and link.end == pytest.approx(b.at(0, 10).xy())
    assert link.end == pytest.approx((70, -4))


def test_move_to_takes_scene_coordinates_in_a_turned_group(tmp_path):
    from optodraw import Group

    path = tmp_path / "a.svg"
    path.write_text(SVG)
    scene = Scene(width=200, height=120)
    group = scene.add(Group(label="g", transform=Transform.from_2d(0, 0, 90)))
    inset = group.add(Inset(str(path), center=(0, 0), width=40.0))
    mark = group.add(Note("m", center=inset.at(10, 5)))
    out = scene.add(Note("o", center=inset.at(0, 0)))
    start = (inset.world_position.x, inset.world_position.y)
    before = [(n.world_position.x, n.world_position.y) for n in (mark, out)]
    inset.move_to(30, 7)
    assert (inset.world_position.x, inset.world_position.y) == pytest.approx((30, 7))
    step = (30 - start[0], 7 - start[1])
    for node, (x, y) in zip((mark, out), before):                  # each moved by the same scene step
        assert (node.world_position.x, node.world_position.y) == pytest.approx((x + step[0], y + step[1]))


def test_an_anchor_saves_as_an_anchor(tmp_path):
    import json

    from optodraw.figure.inset import Anchor
    from optodraw.schema import scene_from_spec, scene_to_spec

    scene, inset = _scene(tmp_path)
    scene.add(Callout("Heater", center=(50, 30), target=inset.at(10, 5)))
    scene.add(DashedLink(inset.at(0, 0), (60, 40)))
    json.dumps(scene.to_dict())
    spec = json.loads(json.dumps(scene_to_spec(scene)))
    call = next(c for c in spec["components"] if c["type"] == "Callout")
    assert call["target"] == {"anchor": "inset", "point": [10.0, 5.0], "options": {}}
    loaded = scene_from_spec(spec)
    back = next(n for n in loaded.walk() if isinstance(n, Callout))
    assert isinstance(back.target, Anchor) and tuple(back.target) == pytest.approx((-10, 5))
