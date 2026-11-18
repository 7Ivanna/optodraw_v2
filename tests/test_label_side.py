"""A part's label beside it (left, right, below) as well as above: papers label a vertical path at its side."""

from __future__ import annotations

import re

import pytest

import optodraw
from optodraw import Mirror, Scene


def _label(scene, name):
    svg = scene.render_svg().as_svg()
    match = re.search(r'<text[^>]*x="([-\d.]+)"[^>]*y="([-\d.]+)"[^>]*text-anchor="(\w+)"[^>]*>' + name, svg) or \
        re.search(r'<text[^>]*text-anchor="(\w+)"[^>]*x="([-\d.]+)"[^>]*y="([-\d.]+)"[^>]*>' + name, svg)
    assert match, svg[:2000]
    groups = match.groups()
    return (float(groups[0]), float(groups[1]), groups[2]) if groups[0][0] in "-0123456789" else \
        (float(groups[1]), float(groups[2]), groups[0])


def _one(side=None, angle=0):
    scene = Scene(width=80, height=60, platform="free_space")
    mirror = scene.add(Mirror(center=(0, 0), angle=angle, aperture=10, label="M1"))
    if side is not None:
        mirror.label_side = side
    return scene


def test_the_label_sits_above_by_default():
    x, y, anchor = _label(_one(), "M1")
    assert anchor == "middle" and x == pytest.approx(0.0) and y < 0          # svg y runs down: above


def test_a_label_at_the_left_ends_just_left_of_the_part():
    x, y, anchor = _label(_one("left"), "M1")
    assert anchor == "end" and -6.0 < x < -1.0, x                            # the mirror is 3.5 wide


def test_a_label_at_the_right_starts_just_right_of_the_part():
    x, y, anchor = _label(_one("right"), "M1")
    assert anchor == "start" and 1.0 < x < 6.0, x


def test_a_label_below_sits_under_the_part():
    x, y, anchor = _label(_one("bottom"), "M1")
    assert anchor == "middle" and y > 5.0, y


def test_a_turned_part_measures_its_label_gap_in_the_world():
    """A mirror at 90 degrees lies flat: its world width is its aperture, so a left label clears 5, not 1.75."""

    x, y, anchor = _label(_one("left", angle=90), "M1")
    assert anchor == "end" and -9.0 < x < -5.0, x


def test_an_unknown_label_side_names_the_part():
    with pytest.raises(ValueError, match="M1.*label_side"):
        _one("middle").render_svg()


def test_tikz_follows_the_label_side():
    tex = _one("left").render_tikz(standalone=False)
    assert re.search(r"\\node\[anchor=east\][^\n]*\{M1\}", tex), tex


def test_the_label_side_survives_the_scene_spec():
    from optodraw.schema import scene_from_spec, scene_to_spec

    again = scene_from_spec(scene_to_spec(_one("right")))
    assert next(c for c in again.walk() if c.label == "M1").label_side == "right"
    assert "label_side" not in next(c for c in scene_to_spec(_one())["components"] if c.get("label") == "M1")


def test_a_corner_label_clears_beams_in_all_four_directions():
    """A beam splitter has light on every side; the paper puts its name at a corner."""

    x, y, anchor = _label(_one("top-right"), "M1")
    assert anchor == "start" and x > 1.0 and y < -4.0, (x, y)
    x, y, anchor = _label(_one("bottom-left"), "M1")
    assert anchor == "end" and x < -1.0 and y > 4.0, (x, y)
    tex = _one("top-left").render_tikz(standalone=False)
    assert re.search(r"\\node\[anchor=south east\][^\n]*\{M1\}", tex), tex


def test_a_flipped_part_keeps_its_label_readable():
    """A part flipped top to bottom drew its name upside down: the flip reached the label too."""

    scene = Scene(width=80, height=60, platform="free_space")
    pbs = scene.add(optodraw.PBS(center=(0, 0), label="PBS"))
    pbs.flip_vertical = True
    svg = scene.render_svg().as_svg()
    group = svg[svg.index("scale(1,-1)"):]
    label = group[:group.index(">PBS<")]
    assert label.count("scale(1,-1)") == 2, label[-400:]          # the art is flipped; the label is flipped back
