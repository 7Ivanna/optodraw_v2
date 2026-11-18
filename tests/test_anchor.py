"""An Anchor names a place inside an inset: marks that hold one stay on that place when the inset moves."""

import pytest

from optodraw import Bracket, DashedLink, Inset, Note, Scene

SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 20"><rect width="40" height="20"/></svg>'


def _scene(tmp_path, **options):                    # a 40 by 20 file in a scene, centred at the origin
    path = tmp_path / "a.svg"
    path.write_text(SVG)
    scene = Scene(width=200, height=120)
    inset = scene.add(Inset(str(path), center=(0, 0), width=40.0, **options))
    return scene, inset


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


