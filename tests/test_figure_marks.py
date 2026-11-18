"""Marks a figure puts on its parts with no place read off a render: a glyph or a note on a route, a named place on
a part, a cut line A to A′, a named region round a group, and the box a part's drawing covers.

Mutants (each one fails a test here):
- delete ``Route.legs``: ``Glyph.on(route)`` raises AttributeError again.
- merge no collinear points in ``Route.legs``: the route through (5, 0) has three legs, not two.
- drop the bend filter in ``Route.legs``: the bent route has the chords of its bends as legs.
- in ``Component.anchors``, return the local places without the part's transform: the turned ring's gap is wrong.
- in ``MicroringResonator._anchor_points``, put the gap on the ring (drop the half gap): it no longer lies in the gap.
- swap the letters of ``SectionMark``: A′ stands at the start.
- drop ``pad`` from the box of ``Region``: the parts touch the box.
- leave ``corners`` out of the saved parameters of Region: the box is lost in a save.
"""

from __future__ import annotations

import pytest

from optodraw import (MMI1x2, MZI, ADCBlock, ElectricalPad, FocusedApodizedGratingCoupler, GratingCouplerArray, Glyph,
                      MicroringResonator, Note, Region, Scene, SectionMark, VerticalGratingCoupler)
from optodraw.core.routing import Route
from optodraw.schema import component_from_spec, component_to_spec


def _wire():
    return Route([(0, 0), (5, 0), (10, 0), (10, 8), (10, 8)], kind="electrical", width=0.6)


# ---------------------------------------------------------------- a route's legs

def test_a_route_has_its_straight_legs():
    assert _wire().legs() == [((0.0, 0.0), (10.0, 0.0)), ((10.0, 0.0), (10.0, 8.0))]


def test_a_bent_route_counts_its_straights_not_the_chords_of_its_bends():
    scene = Scene(title="", width=200, height=100, platform="on_chip")
    a = scene.add(MMI1x2(center=(0, 0)))
    b = scene.add(MMI1x2(center=(80, 30), angle=180))
    legs = scene.route((a, "o2"), (b, "o3")).legs()
    assert len(legs) == 3
    assert [round(p[1] - q[1], 6) == 0 or round(p[0] - q[0], 6) == 0 for p, q in legs] == [True, True, True]


def test_a_taper_is_drawn_at_its_wider_end():
    assert Route([(0, 0), (1, 0)], width=0.5, width2=2.0).display_width == 2.0


def test_a_glyph_and_a_note_stand_beside_a_route():
    wire = _wire()
    glyph = Glyph.on(wire, "pulse", leg=0, size=4.0)
    # beside the middle of the first leg: half the wire, the gap, half the glyph's height
    assert (float(glyph.world_position.x), float(glyph.world_position.y)) == pytest.approx((5.0, 0.3 + 1.0 + 1.2))
    assert glyph.color == wire.color
    note = Note.on(wire, "5 V", leg=1, side="right")
    assert (float(note.world_position.x), float(note.world_position.y)) == pytest.approx((11.3, 4.0))
    assert note.anchor == "start"


# ---------------------------------------------------------------- named places on a part

def test_a_ring_names_its_centre_and_its_coupling_gap():
    ring = MicroringResonator(center=(0, 0))
    assert ring.anchor("ring") == ring.anchor("center") == (0.0, 0.0)
    bus = float(ring.ports()["o1"].center.y)
    assert bus < ring.anchor("gap")[1] < -ring.ring_radius            # between the bus and the ring
    assert set(MicroringResonator(add_drop=True).anchors()) == {"center", "ring", "gap", "drop_gap"}


def test_a_named_place_turns_and_moves_with_its_part():
    flat, turned = MicroringResonator(center=(0, 0)), MicroringResonator(center=(5, 5), angle=90)
    depth = -flat.anchor("gap")[1]
    assert turned.anchor("gap") == pytest.approx((5.0 + depth, 5.0))


def test_an_mzi_names_its_couplers_and_its_arms():
    mzi = MZI()
    places = mzi.anchors()
    assert places["left_coupler"][0] == pytest.approx(-places["right_coupler"][0])
    assert float(mzi.ports()["o1"].center.x) < places["left_coupler"][0] < 0.0
    assert places["upper_arm"][1] > 0.0 > places["lower_arm"][1]


@pytest.mark.parametrize("coupler", [VerticalGratingCoupler(center=(3, 4), angle=30),
                                     FocusedApodizedGratingCoupler(center=(-2, 1))], ids=lambda c: type(c).__name__)
def test_a_grating_coupler_names_its_grating_under_the_fibre(coupler):
    f1 = coupler.world_port("f1").center
    assert coupler.anchor("grating") == pytest.approx((float(f1.x), float(f1.y)))


def test_each_grating_of_an_array_has_its_name():
    array = GratingCouplerArray(center=(0, 0))
    f3 = array.world_port("f3").center
    assert array.anchor("grating3") == pytest.approx((float(f3.x), float(f3.y)))


def test_a_pad_names_its_centre():
    pad = ElectricalPad(center=(3, 4))
    x0, y0, x1, y1 = pad.drawn_box()
    assert pad.anchor("center") == pytest.approx(((x0 + x1) / 2.0, (y0 + y1) / 2.0))


def test_an_unknown_place_says_which_places_there_are():
    with pytest.raises(KeyError, match="center, gap, ring"):
        MicroringResonator().anchor("hub")


# ---------------------------------------------------------------- the box a part's drawing covers

def test_the_drawn_box_turns_with_the_part():
    x0, y0, x1, y1 = ADCBlock(center=(0, 0)).drawn_box()
    u0, v0, u1, v1 = ADCBlock(center=(0, 0), angle=90).drawn_box()
    assert (u1 - u0, v1 - v0) == pytest.approx((y1 - y0, x1 - x0))


# ---------------------------------------------------------------- the cut line

def _world_letters(mark):
    x, y = float(mark.world_position.x), float(mark.world_position.y)
    return [(c["text"], c["x"] + x, c["y"] + y) for c in mark.annotation_2d()["children"] if c["type"] == "text"]


def test_a_section_mark_draws_its_line_and_its_letters_past_the_ends():
    cut = SectionMark((0, 0), (0, 20), name="B")
    assert cut.start == pytest.approx((0.0, 0.0)) and cut.end == pytest.approx((0.0, 20.0))
    (first, _, below), (second, _, above) = _world_letters(cut)
    assert (first, second) == ("B", "B′")
    assert below < 0.0 and above > 20.0


def test_a_section_mark_cuts_through_a_named_place_and_comes_back_after_a_save():
    ring = MicroringResonator(center=(0, 0))
    cut = SectionMark(ring.anchor("gap"), (0, 20), name="A")
    assert cut.start == pytest.approx(ring.anchor("gap"))
    back = component_from_spec(component_to_spec(cut))
    assert (back.name, back.start, back.end) == ("A", pytest.approx(cut.start), pytest.approx(cut.end))


# ---------------------------------------------------------------- the named region

def _world_box(region):
    (x0, y0), (x1, y1) = region.corners
    x, y = float(region.world_position.x), float(region.world_position.y)
    return x0 + x, y0 + y, x1 + x, y1 + y


def test_a_region_boxes_its_parts_with_room_and_names_them_over_its_corner():
    a = ElectricalPad(center=(-30, 0), width=9, height=9)
    b = ElectricalPad(center=(30, 10), width=9, height=9)
    region = Region([a, b], label="TX", pad=2.0)
    boxes = [a.drawn_box(), b.drawn_box()]
    expected = (min(p[0] for p in boxes) - 2.0, min(p[1] for p in boxes) - 2.0,
                max(p[2] for p in boxes) + 2.0, max(p[3] for p in boxes) + 2.0)
    assert _world_box(region) == pytest.approx(expected)
    assert float(region.world_position.y) > expected[3]                 # the name over the top edge
    assert region.label == "TX" and region.annotation_2d()["children"][0]["stroke_dasharray"]


def test_a_region_keeps_its_box_in_a_save():
    region = Region([ElectricalPad(center=(0, 0))], label="driver")
    back = component_from_spec(component_to_spec(region))
    assert back.label == "driver" and _world_box(back) == pytest.approx(_world_box(region))


def test_a_region_dropped_in_the_editor_is_a_box_under_its_name():
    (x0, y0), (x1, y1) = Region().corners
    assert x1 - x0 > 0.0 and y1 < 0.0 < x1
