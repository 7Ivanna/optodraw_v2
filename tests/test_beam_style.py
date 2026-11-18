"""One look for the light of a figure: nested bands on the axis, cut on the mirror, and one place to change them."""

from __future__ import annotations

import re

import pytest

from optodraw import Beam, BeamSplitter, BeamStyle, FocusingBeam, Laser, Mirror, Photodiode, Scene
from optodraw.app.session import EditorSession
from optodraw.core.beam import band_quads, wavelength_to_width_factor
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


def _plate():
    scene = Scene(title="plate", width=100, height=80, platform="free_space")
    plate = scene.add(BeamSplitter(center=(0, 0), angle=45, dichroic=True, cutoff_wavelength=900))
    laser = scene.add(Laser(center=(-30, 0), wavelength=450))
    return scene, plate, laser


UP_AT_ORIGIN = [(-10.0, 0.0, 0.0), (0.0, 0.0, 0.0), (0.0, 10.0, 0.0)]


def _inside(quads, x, y):
    def within(quad):
        signs = [(b[0] - a[0]) * (y - a[1]) - (b[1] - a[1]) * (x - a[0]) for a, b in zip(quad, quad[1:] + quad[:1])]
        return all(sign >= 0.0 for sign in signs) or all(sign <= 0.0 for sign in signs)

    return any(within(quad) for quad in quads)


def test_a_fold_is_cut_on_the_mirror_line():
    quads = band_quads(UP_AT_ORIGIN, 2.0)
    corners = {(round(p[0], 6), round(p[1], 6)) for quad in quads for p in quad}
    assert (1.0, 1.0) in corners and (-1.0, -1.0) in corners         # the mirror here runs along y = x


def test_no_light_reaches_behind_the_mirror():
    quads = band_quads(UP_AT_ORIGIN, 2.0)
    assert _inside(quads, -0.5, 0.5)                                 # the light side
    assert not _inside(quads, 0.8, -0.8)                             # where a stroke's corner would stand


def test_a_straight_beam_has_no_band_to_cut():
    assert band_quads([(0.0, 0.0, 0.0), (5.0, 0.0, 0.0), (10.0, 0.0, 0.0)], 2.0) == []


def test_every_span_of_a_band_turns_the_same_way():
    def area(quad):
        return sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(quad, quad[1:] + quad[:1]))

    points = [(-10.0, 0.0, 0.0), (0.0, 0.0, 0.0), (0.0, 10.0, 0.0), (10.0, 10.0, 0.0)]
    assert all(area(quad) > 0.0 for quad in band_quads(points, 2.0))


def test_a_folded_beam_is_one_filled_shape_so_its_fold_is_not_darker():
    scene, laser, mirror, pd = _fold()
    scene.add(Beam.through(laser, mirror, pd, wavelength=450, width=2.0))
    svg = scene.render_svg().as_svg()
    color = re.search(r'<g opacity="0.5">\s*<path d="[^"]*" fill="(#[0-9a-f]{6})"', svg)   # one fill in its layer
    assert color is not None
    assert svg.count('stroke="#0000ff"') == 0


def test_a_straight_beam_stays_a_stroke():
    scene = Scene(title="line", width=100, height=40, platform="free_space")
    laser = scene.add(Laser(center=(-30, 0), wavelength=450))
    pd = scene.add(Photodiode(center=(30, 0), angle=180))
    scene.add(Beam((laser, "out"), (pd, "in"), wavelength=450))
    assert re.search(r'stroke="#[0-9a-f]{6}"[^>]*stroke-width', scene.render_svg().as_svg())


def test_a_plate_that_folds_light_joins_the_two_legs():
    scene, plate, laser = _plate()
    beam = scene.add(Beam((laser, "out"), (plate, "in"), (plate, "refl"), (0, 30), wavelength=450))
    assert len(beam.segments()) == 1


def test_a_part_with_a_real_span_still_splits_the_beam():
    from optodraw import Objective

    scene = Scene(title="objective", width=100, height=40, platform="free_space")
    objective = scene.add(Objective(center=(0, 0)))
    beam = scene.add(Beam((-20, 0), (objective, "in"), (objective, "out"), (20, 0)))
    assert len(beam.segments()) == 2


def test_the_default_opacity_shows_a_lower_beam_most():
    a = Beam((0, 0), (1, 0)).opacity
    assert a == pytest.approx(0.5)
    assert FocusingBeam((0, 0), (1, 0)).opacity == a


def test_a_scene_sets_the_opacity_of_its_beams():
    scene = Scene(title="s", beam_style=BeamStyle(opacity=0.35))
    beam = scene.add(Beam((0, 0), (10, 0)))
    cone = scene.add(FocusingBeam((0, 0), (10, 0)))
    assert (beam.opacity, cone.opacity) == (0.35, 0.35)


def test_a_beam_keeps_the_opacity_it_names():
    scene = Scene(title="s", beam_style=BeamStyle(opacity=0.35))
    assert scene.add(Beam((0, 0), (10, 0), opacity=0.9)).opacity == 0.9


def test_a_beam_in_a_group_finds_the_scene():
    scene = Scene(title="s", beam_style=BeamStyle(opacity=0.35))
    assert scene.group("arm").add(Beam((0, 0), (10, 0))).opacity == 0.35


def test_the_style_can_change_after_the_beams():
    scene = Scene(title="s")
    beam = scene.add(Beam((0, 0), (10, 0)))
    scene.beam_style = BeamStyle(opacity=0.3)
    assert beam.opacity == 0.3


def test_the_scale_reaches_beams_and_cones_alike():
    scene = Scene(title="s", beam_style=BeamStyle(scale=2.0))
    beam = scene.add(Beam((0, 0), (10, 0), wavelength=633, width=1.0))
    cone = scene.add(FocusingBeam((0, 0), (10, 0), width1=4.0, width2=0.0, wavelength=633))
    assert beam.display_width == pytest.approx(2.0 * wavelength_to_width_factor(633))
    ys = [y for _, y in cone.corners()]
    assert max(ys) - min(ys) == pytest.approx(8.0)


def test_width_can_stop_following_wavelength():
    scene = Scene(title="s", beam_style=BeamStyle(by_wavelength=0.0))
    widths = {round(scene.add(Beam((0, 0), (10, 0), wavelength=nm, width=1.0)).display_width, 6)
              for nm in (450, 635, 1218)}
    assert widths == {1.0}


def test_infrared_can_be_wider_still():
    plain = Beam((0, 0), (10, 0), wavelength=1218, width=1.0).display_width
    scene = Scene(title="s", beam_style=BeamStyle(by_wavelength=2.0))
    assert scene.add(Beam((0, 0), (10, 0), wavelength=1218, width=1.0)).display_width > plain * 1.4


def test_a_cone_widens_with_a_beam_it_continues():
    scene = Scene(title="s", beam_style=BeamStyle(by_wavelength=2.0))
    beam = scene.add(Beam((0, 0), (10, 0), wavelength=1218, width=1.0))
    cone = scene.add(FocusingBeam((10, 0), (20, 0), width1=wavelength_to_width_factor(1218), width2=0.0,
                                  wavelength=1218))
    ys = [y for _, y in cone.corners()]
    assert max(ys) - min(ys) == pytest.approx(beam.display_width)


@pytest.mark.parametrize("kwargs", [{"opacity": 0.0}, {"opacity": 1.5}, {"scale": 0.0}, {"by_wavelength": -1.0}])
def test_a_style_out_of_range_is_refused(kwargs):
    with pytest.raises(ValueError):
        BeamStyle(**kwargs)


def test_a_short_wavelength_keeps_some_width_at_any_spread():
    assert Scene(title="s", beam_style=BeamStyle(by_wavelength=9.0)).add(
        Beam((0, 0), (10, 0), wavelength=400)).display_width > 0.0


def test_the_style_survives_a_save():
    scene = Scene(title="s", beam_style=BeamStyle(opacity=0.4, scale=1.5, by_wavelength=0.5))
    scene.add(Beam((0, 0), (10, 0)))
    loaded = scene_from_spec(scene_to_spec(scene))
    assert loaded.beam_style == BeamStyle(opacity=0.4, scale=1.5, by_wavelength=0.5)


def test_a_save_leaves_the_opacity_to_the_scene_when_the_beam_names_none():
    scene = Scene(title="s", beam_style=BeamStyle(opacity=0.4))
    scene.add(Beam((0, 0), (10, 0)))
    scene.add(FocusingBeam((0, 0), (10, 0)))
    assert all("opacity" not in beam for beam in scene_to_spec(scene)["beams"])


def test_a_save_keeps_the_opacity_a_beam_names():
    scene = Scene(title="s")
    scene.add(Beam((0, 0), (10, 0), opacity=0.8))
    assert scene_to_spec(scene)["beams"][0]["opacity"] == 0.8


def test_the_default_style_is_not_written():
    assert "beam_style" not in scene_to_spec(Scene(title="s"))


def test_the_editor_sets_the_style_of_the_scene():
    session = EditorSession()
    spec = session.set_meta(beam_style={"opacity": 0.4, "scale": 1.2, "by_wavelength": 1.5})
    assert scene_from_spec(spec).beam_style == BeamStyle(opacity=0.4, scale=1.2, by_wavelength=1.5)


def test_the_editor_refuses_a_style_out_of_range():
    with pytest.raises(ValueError):
        EditorSession().set_meta(beam_style={"opacity": 3.0})


def test_the_editor_sets_the_opacity_and_the_lane_of_one_beam():
    session = EditorSession()
    first = session.add_component("Laser", {"center": [-30, 0]})
    second = session.add_component("Photodiode", {"center": [30, 0], "angle": 180})
    session.update(session.add_beam([first, second]), {"opacity": 0.3, "offset": 1.5})
    drawn = next(n for n in session.scene().walk() if isinstance(n, Beam))
    assert (drawn.opacity, drawn.offset) == (0.3, 1.5)


def test_infrared_is_as_wide_in_tikz_as_in_svg():
    scene, laser, mirror, pd = _fold()
    beam = scene.add(Beam.through(laser, mirror, pd, wavelength=1218, width=1.0))
    assert f"line width={beam.display_width:.3f}pt" in scene.render_tikz()


def test_the_envelope_of_a_bundle_keeps_its_strength():
    scene = Scene(title="s", width=60, height=40, platform="free_space")
    scene.add(Beam((0, 0), (20, 5), (20, -5), (0, 0), envelope=True))
    assert re.search(r'opacity="0\.15\d*"', scene.render_svg().as_svg())


def test_a_mirror_cut_reaches_the_mirror_in_a_scene():
    scene, laser, mirror, pd = _fold()
    beam = scene.add(Beam.through(laser, mirror, pd, wavelength=450, width=2.0))
    run = beam.segments()[0]
    quads = band_quads(run, beam.display_width)
    io = mirror.world_port("io").center
    leg = [(b[0] - a[0], b[1] - a[1]) for a, b in zip(run, run[1:])]
    lengths = [(dx * dx + dy * dy) ** 0.5 for dx, dy in leg]
    along = tuple(leg[0][i] / lengths[0] + leg[1][i] / lengths[1] for i in (0, 1))    # the mirror lies along their sum
    gaps = [abs((p[0] - io.x) * along[1] - (p[1] - io.y) * along[0]) for quad in quads for p in quad
            if abs(p[0] - io.x) < beam.display_width and abs(p[1] - io.y) < beam.display_width]
    assert gaps and max(gaps) < 1e-6
    assert isinstance(mirror, Mirror)


def test_light_that_passes_twice_is_drawn_once():
    """A double-pass beam drew each run between parts as its own translucent path: the span the light crosses out and
    back through a wave plate showed twice as strong as the span it crosses out and back to the mirror."""

    import io
    import re

    from optodraw.raster import svg_to_png
    image = pytest.importorskip("PIL.Image")
    from optodraw import PBS, Beam, Laser, Mirror, Photodiode, QuarterWavePlate, Scene

    scene = Scene(platform="free_space")
    laser = scene.add(Laser(center=(-40, 0), wavelength=1064))
    pbs = scene.add(PBS(center=(-15, 0)))
    qwp = scene.add(QuarterWavePlate(center=(5, 0), fast_axis_angle=45))
    mirror = scene.add(Mirror(center=(25, 0)))
    pd = scene.add(Photodiode(center=(-15, -20), angle=90))
    scene.add(Beam.through(laser, (pbs, "in"), (pbs, "trans"), qwp, mirror, qwp, (pbs, "trans"), (pbs, "tap"), pd))
    svg = scene.render_svg().as_svg()
    x0, y0, w, h = (float(v) for v in re.search(r'viewBox="([-\d.]+) ([-\d.]+) ([-\d.]+) ([-\d.]+)"', svg).groups())
    png = image.open(io.BytesIO(svg_to_png(svg, width=800, background="white")))
    scale = png.width / w

    def colour(x, y):                                        # world x, y (y up) to the pixel there
        return png.convert("RGB").getpixel((int((x - x0) * scale), int((-y - y0) * scale)))

    out_and_back_through_the_plate, out_and_back_to_the_mirror = colour(-4.0, 0.0), colour(15.0, 0.0)
    assert out_and_back_through_the_plate == out_and_back_to_the_mirror
