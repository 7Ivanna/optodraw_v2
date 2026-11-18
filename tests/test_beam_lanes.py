"""Two beams on one path stay readable: the lower one shows through, or each keeps a lane of its own."""

from __future__ import annotations

import inspect
import math
import re

import pytest

from optodraw import Beam, FocusingBeam, Laser, Mirror, Photodiode, Scene
from optodraw.core.beam import NESTED_RATIO, drawn_widths
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


def _distance_to_line(point, a, b):
    (x, y), (x0, y0), (x1, y1) = point[:2], a[:2], b[:2]
    return abs((x1 - x0) * (y - y0) - (y1 - y0) * (x - x0)) / math.hypot(x1 - x0, y1 - y0)


def test_opacity_and_offset_are_named_parameters():
    for cls in (Beam, FocusingBeam):
        names = inspect.signature(cls.__init__).parameters
        assert "opacity" in names and "offset" in names


def test_a_lower_beam_shows_through_by_default():
    """What shows of a lower beam under an upper one of opacity a is a(1 - a) of its colour."""

    a = Beam((0, 0), (1, 0)).opacity
    assert a * (1 - a) >= 0.2


def test_opacity_reaches_the_svg():
    scene, laser, mirror, pd = _fold()
    scene.add(Beam.through(laser, mirror, pd, wavelength=450, opacity=0.37))
    assert 'opacity="0.37"' in scene.render_svg().as_svg()


def test_opacity_reaches_the_tikz():
    scene, laser, mirror, pd = _fold()
    scene.add(Beam.through(laser, mirror, pd, wavelength=450, opacity=0.37))
    assert "opacity=0.370" in scene.render_tikz()


def test_a_focusing_beam_opacity_reaches_the_tikz():
    scene, laser, mirror, pd = _fold()
    scene.add(FocusingBeam((mirror, "io"), (pd, "in"), width1=3.0, opacity=0.37))
    assert "fill opacity=0.370" in scene.render_tikz()


def test_a_png_shows_both_colours_on_one_path():
    from optodraw.raster import svg_to_png
    image = pytest.importorskip("PIL.Image")
    import io

    def pixel(*wavelengths):
        scene = Scene(title="one path", width=40, height=10, platform="free_space")
        for nm in wavelengths:
            scene.add(Beam((-20, 0), (20, 0), wavelength=nm, width=4.0))
        png = svg_to_png(scene.render_svg().as_svg(), width=400)
        return image.open(io.BytesIO(png)).convert("RGB").getpixel((200, 50))

    both, upper_alone = pixel(635, 450), pixel(450)     # the wider red draws first, so the blue lies on top
    assert math.dist(both, upper_alone) > 60            # 0.85 gave 40: the eye loses the lower beam


def test_a_positive_offset_moves_the_beam_to_the_left_of_the_light():
    beam = Beam((0, 0), (10, 0), offset=0.5)
    assert beam.resolve_points() == [(0.0, 0.5, 0.0), (10.0, 0.5, 0.0)]


def test_no_offset_leaves_the_path_as_it_was():
    assert Beam((0, 0), (10, 0)).resolve_points() == [(0, 0, 0), (10, 0, 0)]


def test_two_beams_that_meet_head_on_take_opposite_lanes_with_one_offset():
    out = Beam((0, 0), (10, 0), offset=0.5).resolve_points()
    back = Beam((10, 0), (0, 0), offset=0.5).resolve_points()
    assert out[0][1] == -back[0][1] != 0.0


def test_a_lane_keeps_its_distance_round_a_mirror():
    scene, laser, mirror, pd = _fold()
    plain = Beam.through(laser, mirror, pd, wavelength=450).resolve_points()
    lane = Beam.through(laser, mirror, pd, wavelength=450, offset=0.6).resolve_points()
    assert _distance_to_line(lane[0], plain[0], plain[1]) == pytest.approx(0.6)
    assert _distance_to_line(lane[-1], plain[1], plain[2]) == pytest.approx(0.6)
    assert _distance_to_line(lane[1], plain[0], plain[1]) == pytest.approx(0.6)     # the corner is on both


def test_a_lane_turns_on_the_mirror_face_not_behind_it():
    scene, laser, mirror, pd = _fold()
    plain = Beam.through(laser, mirror, pd).resolve_points()
    lane = Beam.through(laser, mirror, pd, offset=0.6).resolve_points()
    (ax, ay), (cx, cy), (bx, by) = plain[0][:2], plain[1][:2], plain[2][:2]
    to_laser, to_pd = math.hypot(ax - cx, ay - cy), math.hypot(bx - cx, by - cy)
    normal = ((ax - cx) / to_laser + (bx - cx) / to_pd, (ay - cy) / to_laser + (by - cy) / to_pd)
    behind = (lane[1][0] - cx) * normal[0] + (lane[1][1] - cy) * normal[1]
    assert behind == pytest.approx(0.0, abs=1e-9)


def test_a_mirror_swaps_the_side_of_the_lane():
    scene, laser, mirror, pd = _fold()
    plain = Beam.through(laser, mirror, pd).resolve_points()
    lane = Beam.through(laser, mirror, pd, offset=0.6).resolve_points()
    assert lane[0][1] > plain[0][1]                         # left of the light, which runs along +x
    assert lane[-1][0] > plain[-1][0]                       # right of the light, which now runs along +y


def test_two_ports_on_one_spot_make_one_corner():
    """A plate names its in and refl ports on one point: the corner counts once, so the side swaps once."""

    once = Beam((0, 0), (10, 0), (10, -10), offset=0.5).resolve_points()
    twice = Beam((0, 0), (10, 0), (10, 0), (10, -10), offset=0.5).resolve_points()
    assert twice[1] == twice[2] == once[1] and twice[3] == once[2]


def test_a_rise_on_one_spot_stays_in_its_lane():
    """A periscope rises on one spot of the plan: the height changes and the lane does not."""

    points = Beam((0, 0, 0), (10, 0, 0), (10, 0, 5), (20, 0, 5), offset=0.5).resolve_points()
    assert [p[1] for p in points] == pytest.approx([0.5] * 4) and [p[2] for p in points] == [0, 0, 5, 5]


def test_a_small_bend_keeps_its_lane():
    points = Beam((0, 0), (10, 0), (20, 1), offset=0.5).resolve_points()
    assert points[0][1] == pytest.approx(0.5) and points[-1][1] > 1.0   # still left of the light after the bend


def test_a_lane_reaches_the_3d_points():
    scene, laser, mirror, pd = _fold()
    plain = Beam.through(laser, mirror, pd).resolve_points()
    lane = Beam.through(laser, mirror, pd, offset=0.6).resolve_points()
    assert [p[2] for p in lane] == [p[2] for p in plain]
    assert lane[0][:2] != plain[0][:2]


def test_a_beam_sent_straight_back_runs_back_on_itself():
    points = Beam((0, 0), (10, 0), (0, 0), offset=0.5).resolve_points()
    assert [p[1] for p in points] == pytest.approx([0.5, 0.5, 0.5])


def test_a_focusing_beam_takes_a_lane():
    plain = FocusingBeam((0, 0), (10, 0), width1=2.0, width2=0.0).corners()
    lane = FocusingBeam((0, 0), (10, 0), width1=2.0, width2=0.0, offset=0.5).corners()
    assert [(x, y + 0.5) for x, y in plain] == pytest.approx(lane)


def test_opacity_and_offset_survive_a_save():
    scene, laser, mirror, pd = _fold()
    scene.add(Beam.through(laser, mirror, pd, wavelength=450, opacity=0.4, offset=0.6, label="lane"))
    scene.add(FocusingBeam((mirror, "io"), (pd, "in"), width1=3.0, opacity=0.3, offset=-0.2))
    loaded = scene_from_spec(scene_to_spec(scene))
    beams = [n for n in loaded.walk() if isinstance(n, Beam)]
    cones = [n for n in loaded.walk() if isinstance(n, FocusingBeam)]
    assert (beams[0].opacity, beams[0].offset) == (0.4, 0.6)
    assert (cones[0].opacity, cones[0].offset) == (0.3, -0.2)


def test_defaults_stay_out_of_a_saved_scene():
    scene, laser, mirror, pd = _fold()
    scene.add(Beam.through(laser, mirror, pd))
    spec = scene_to_spec(scene)
    assert "opacity" not in spec["beams"][0] and "offset" not in spec["beams"][0]


@pytest.mark.parametrize("order", [(450, 532, 635), (532, 635, 450)], ids=["blue first", "green first"])
def test_beams_on_one_path_draw_nested_with_the_longer_wavelength_outside(order):
    scene = Scene(title="shared", width=100, height=40, platform="free_space")
    beams = {nm: scene.add(Beam((-30, 0), (30, 0), wavelength=nm, width=1.0)) for nm in order}
    blue, green, red = beams[450], beams[532], beams[635]
    widths = [blue.display_width * NESTED_RATIO ** step for step in range(3)]
    svg = dict(re.findall(r'stroke="(#\w+)" fill="none" stroke-width="([\d.]+)"', scene.render_svg().as_svg()))
    assert [float(svg[beam.color]) for beam in (blue, green, red)] == pytest.approx(widths)
    tikz = scene.render_tikz()                                    # drawn widest first, as in the SVG
    assert tikz.index(f"line width={widths[2]:.3f}pt") < tikz.index(f"line width={widths[1]:.3f}pt") \
        < tikz.index(f"line width={widths[0]:.3f}pt")


@pytest.mark.parametrize("beams", [
    lambda: [Beam((-30, 0), (30, 0), wavelength=450), Beam((-30, 0), (30, 0), wavelength=635, offset=0.8)],
    lambda: [Beam((-30, 0), (30, 0), wavelength=450, width=3.0), Beam((-30, 0), (30, 0), wavelength=635, width=0.5)],
    lambda: [Beam((-30, 0), (10, 0), wavelength=450), Beam((-10, 0), (30, 0), wavelength=450)],
], ids=["a lane of its own", "nested by hand", "one colour in two pieces"])
def test_a_beam_that_already_shows_keeps_its_width(beams):
    beams = beams()
    assert drawn_widths(beams) == {id(beam): beam.display_width for beam in beams}
