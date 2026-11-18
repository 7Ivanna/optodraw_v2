"""The lenses on a beam's way set its drawn width: the focal lengths give the ratios, the first width the scale."""

from __future__ import annotations

import warnings

import pytest

from optodraw import Beam, BeamDump, Camera, FocusingBeam, Laser, Lens, Mirror, Objective, Sample, Scene, check_figure
from optodraw.app.validation import run_checks
from optodraw.core.beam import wavelength_to_width_factor
from optodraw.schema import scene_from_spec, scene_to_spec

SCALE = 150.0 / 24.0                                     # a 150 mm telescope drawn 24 units long


def _telescope():
    scene = Scene(title="telescope", width=160, height=60, platform="free_space")
    laser = scene.add(Laser(center=(-60, 0), wavelength=450, label="Laser"))
    near = scene.add(Lens(center=(-26, 0), focal_length=50, label="f 50"))
    far = scene.add(Lens(center=(-2, 0), focal_length=100, label="f 100"))
    dump = scene.add(BeamDump(center=(30, 0), angle=180, label="Dump"))
    return scene, laser, near, far, dump


def test_a_telescope_grows_the_beam_by_the_ratio_of_its_focal_lengths():
    scene, laser, near, far, dump = _telescope()
    pieces = scene.lens_beam(laser, near, far, dump, width=1.0, mm_per_unit=SCALE, wavelength=450)
    assert [type(piece) for piece in pieces] == [Beam, FocusingBeam, FocusingBeam, Beam]
    assert pieces[0].width == pytest.approx(1.0)
    assert pieces[-1].width == pytest.approx(2.0)


def test_the_focus_lands_where_the_focal_lengths_put_it():
    scene, laser, near, far, dump = _telescope()
    pieces = scene.lens_beam(laser, near, far, dump, width=1.0, mm_per_unit=SCALE, wavelength=450)
    focus = pieces[1].endpoints()[1]
    assert (focus.x, focus.y) == pytest.approx((-18.0, 0.0))     # 50 mm past the first lens, at 6.25 mm a unit
    assert pieces[1].width2 == 0.0 and pieces[2].width1 == 0.0


def test_a_cone_starts_as_wide_as_the_beam_it_continues():
    scene, laser, near, far, dump = _telescope()
    pieces = scene.lens_beam(laser, near, far, dump, width=1.0, mm_per_unit=SCALE, wavelength=450)
    assert pieces[1].width1 == pytest.approx(pieces[0].display_width, rel=0.05)
    assert pieces[2].width2 == pytest.approx(pieces[3].display_width, rel=0.05)


def test_the_first_width_is_the_display_scale():
    scene, laser, near, far, dump = _telescope()
    wide = scene.lens_beam(laser, near, far, dump, width=3.0, mm_per_unit=SCALE, wavelength=450)
    assert wide[-1].width == pytest.approx(6.0)
    assert wide[1].width1 == pytest.approx(3.0 * wavelength_to_width_factor(450), rel=0.05)


def test_a_telescope_drawn_short_says_the_scale_that_fixes_it():
    scene, laser, near, far, dump = _telescope()
    with pytest.warns(UserWarning, match=r"mm_per_unit=6\.25"):
        scene.lens_beam(laser, near, far, dump, width=1.0, wavelength=450)


def test_a_telescope_to_scale_says_nothing():
    scene, laser, near, far, dump = _telescope()
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        scene.lens_beam(laser, near, far, dump, width=1.0, mm_per_unit=SCALE, wavelength=450)


def test_a_lens_named_by_one_port_still_acts():
    scene, laser, near, far, dump = _telescope()
    pieces = scene.lens_beam(laser, (near, "in"), (far, "out"), dump, width=1.0, mm_per_unit=SCALE, wavelength=450)
    assert pieces[-1].width == pytest.approx(2.0)


def test_a_lens_named_by_its_two_ports_acts_once():
    scene, laser, near, far, dump = _telescope()
    pieces = scene.lens_beam(laser, (near, "in"), (near, "out"), (far, "in"), (far, "out"), dump, width=1.0,
                             mm_per_unit=SCALE, wavelength=450)
    assert pieces[-1].width == pytest.approx(2.0)


def test_one_stop_is_refused():
    scene, laser, _, _, _ = _telescope()
    with pytest.raises(ValueError, match="two stops"):
        scene.lens_beam(laser, width=1.0)


def test_a_lens_alone_is_one_stop():
    scene, _, near, _, _ = _telescope()
    with pytest.raises(ValueError, match="two stops"):
        scene.lens_beam((near, "in"), (near, "out"), width=1.0)


def test_a_focus_inside_a_lens_body_lies_its_focal_length_from_the_middle():
    scene, laser, near, far, dump = _telescope()
    far.focal_length = 1.0                                    # shorter than half the lens: the focus lies in the glass
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        pieces = scene.lens_beam(laser, far, dump, width=1.0, wavelength=450)
    assert pieces[1].endpoints()[1].x == pytest.approx(far.world_position.x + 1.0)


def test_a_beam_with_no_lens_is_one_beam():
    scene, laser, _, _, dump = _telescope()
    pieces = scene.lens_beam((laser, "out"), (dump, "in"), width=1.5, wavelength=450)
    assert [type(piece) for piece in pieces] == [Beam]
    assert pieces[0].width == 1.5


def test_a_lens_with_no_focal_length_leaves_the_beam_alone():
    scene, laser, _, _, dump = _telescope()
    blank = scene.add(Lens(center=(10, 0), focal_length=None))
    pieces = scene.lens_beam(laser, blank, dump, width=1.0, wavelength=450)
    assert all(isinstance(piece, Beam) and piece.width == 1.0 for piece in pieces)


def test_a_diverging_lens_widens_the_beam_with_no_focus():
    scene = Scene(title="diverge", width=160, height=60, platform="free_space")
    laser = scene.add(Laser(center=(-60, 0), wavelength=633))
    spread = scene.add(Lens(center=(-20, 0), focal_length=-20))
    dump = scene.add(BeamDump(center=(20, 0), angle=180))
    pieces = scene.lens_beam(laser, spread, dump, width=1.0, wavelength=633)
    assert [type(piece) for piece in pieces] == [Beam, FocusingBeam]
    assert pieces[1].width2 == pytest.approx(pieces[1].width1 * 3.0, rel=0.1)


def test_an_objective_focuses_on_its_own_focus_point():
    scene = Scene(title="objective", width=160, height=60, platform="free_space")
    laser = scene.add(Laser(center=(-70, 0), wavelength=450))
    objective = scene.add(Objective(center=(0, 0), magnification=10))
    fx, fy = objective.focus_point()
    sample = scene.add(Sample(center=(fx + 1.0, fy), angle=180))
    pieces = scene.lens_beam(laser, objective, (fx, fy), width=2.0, wavelength=450)
    cone = pieces[-1]
    assert isinstance(cone, FocusingBeam) and cone.width2 == pytest.approx(0.0, abs=1e-9)
    assert (cone.endpoints()[1].x, cone.endpoints()[1].y) == pytest.approx((fx, fy))
    assert sample is not None


def test_a_mirror_inside_a_cone_keeps_the_width_across_it():
    scene = Scene(title="fold", width=160, height=120, platform="free_space")
    laser = scene.add(Laser(center=(-60, 0), wavelength=450))
    lens = scene.add(Lens(center=(-30, 0), focal_length=60))
    fold = scene.add(Mirror(center=(0, 0), angle=-45))
    dump = scene.add(BeamDump(center=(fold.world_port("io").center.x, 60), angle=270))
    pieces = scene.lens_beam(laser, lens, fold, dump, width=1.0, wavelength=450)
    cones = [piece for piece in pieces if isinstance(piece, FocusingBeam)]
    assert cones[0].width2 == pytest.approx(cones[1].width1)
    assert cones[0].endpoints()[1].x == pytest.approx(cones[1].endpoints()[0].x)


def test_a_lane_stays_on_its_side_of_the_light_through_a_lens():
    scene, laser, near, far, dump = _telescope()
    pieces = scene.lens_beam(laser, near, far, dump, width=1.0, mm_per_unit=SCALE, wavelength=450, offset=1.5)
    assert {round(float(point[1]), 6) for piece in pieces if isinstance(piece, Beam)
            for point in piece.resolve_points()} == {1.5}
    assert {round(float(end.y), 6) for piece in pieces if isinstance(piece, FocusingBeam)
            for end in piece.endpoints()} == {1.5}


def test_a_lane_changes_side_after_a_mirror_as_the_light_does():
    scene = Scene(title="fold", width=160, height=120, platform="free_space")
    laser = scene.add(Laser(center=(-60, 0), wavelength=450))
    fold = scene.add(Mirror(center=(-30, 0), angle=-45))
    io = fold.world_port("io").center
    lens = scene.add(Lens(center=(io.x, 30), angle=90, focal_length=20))
    dump = scene.add(BeamDump(center=(io.x, 80), angle=270))
    plain = Beam((laser, "out"), (fold, "io"), (lens, "in"), wavelength=450, offset=1.0)
    pieces = scene.lens_beam((laser, "out"), (fold, "io"), lens, dump, width=1.0, wavelength=450, offset=1.0)
    assert float(pieces[1].endpoints()[0].x) == pytest.approx(float(plain.resolve_points()[-1][0]))


def test_every_piece_shares_one_opacity_and_only_the_first_a_label():
    scene, laser, near, far, dump = _telescope()
    pieces = scene.lens_beam(laser, near, far, dump, width=1.0, mm_per_unit=SCALE, wavelength=450, opacity=0.6,
                             label="Anneal")
    assert {piece.opacity for piece in pieces} == {0.6}
    assert [piece.label for piece in pieces] == ["Anneal", "", "", ""]


def test_a_distance_scale_must_be_positive():
    scene, laser, near, far, dump = _telescope()
    with pytest.raises(ValueError, match="mm_per_unit"):
        scene.lens_beam(laser, near, far, dump, width=1.0, mm_per_unit=0.0, wavelength=450)


def test_the_figure_gate_reads_the_pieces_as_one_path():
    scene, laser, near, far, dump = _telescope()
    scene.lens_beam(laser, near, far, dump, width=1.0, mm_per_unit=SCALE, wavelength=450)
    scene.fit_frame()
    assert [finding for finding in check_figure(scene) if "beam" in finding] == []


def test_the_pieces_survive_a_save():
    scene, laser, near, far, dump = _telescope()
    scene.lens_beam(laser, near, far, dump, width=1.0, mm_per_unit=SCALE, wavelength=450)
    loaded = scene_from_spec(scene_to_spec(scene))
    assert sorted(type(n).__name__ for n in loaded.walk() if isinstance(n, (Beam, FocusingBeam))) == [
        "Beam", "Beam", "FocusingBeam", "FocusingBeam"]


def test_a_cone_that_ends_on_a_camera_is_light_on_the_camera():
    scene = Scene(title="focus", width=160, height=60, platform="free_space")
    laser = scene.add(Laser(center=(-60, 0), wavelength=633))
    lens = scene.add(Lens(center=(0, 0), focal_length=30))
    camera = scene.add(Camera(center=(30, 0), angle=180, label="Camera"))
    scene.lens_beam(laser, lens, (camera, "in"), width=1.0, wavelength=633)
    assert [i for i in run_checks(scene) if "receives no light" in i["message"]] == []


def test_a_cone_that_stops_short_of_a_camera_is_still_reported():
    scene = Scene(title="focus", width=160, height=60, platform="free_space")
    laser = scene.add(Laser(center=(-60, 0), wavelength=633))
    lens = scene.add(Lens(center=(-30, 0), focal_length=10))
    scene.add(Camera(center=(40, 0), angle=180, label="Camera"))
    scene.lens_beam(laser, lens, (-20, 0), width=1.0, wavelength=633)
    assert [i for i in run_checks(scene) if "receives no light" in i["message"]] != []


def scene_svg(scene, tmp_path_factory=None):
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "scene.svg"
        scene.render_svg(path)
        return path.read_text(encoding="utf-8")


def _cone_fill(svg, color):
    """Where the last piece of light of this colour is drawn: a later one lies on top."""

    return svg.rindex(f'fill="{color}"')


def _bands(scene, near, far, laser, dump):
    red = scene.lens_beam((laser, "out"), near, far, dump, width=1.6, mm_per_unit=SCALE, wavelength=635)
    blue = scene.lens_beam((laser, "out"), near, far, dump, width=0.8, mm_per_unit=SCALE, wavelength=450)
    return red, blue


def test_a_narrow_cone_nests_inside_a_wide_one_as_a_narrow_band_does():
    """The blue cone lay under the red one, so the beam changed colour at each lens: purple band, mauve cone."""

    scene, laser, near, far, dump = _telescope()
    red, blue = _bands(scene, near, far, laser, dump)
    assert red[1].display_width > blue[1].display_width
    assert red[1].display_width == pytest.approx(red[0].display_width)
    svg = scene_svg(scene)
    blue_cone, red_cone = _cone_fill(svg, blue[1].color), _cone_fill(svg, red[1].color)
    assert red_cone < blue_cone


def test_a_beam_reaches_the_middle_of_a_lens_so_no_gap_shows_at_the_curved_faces():
    """A band cut at the tip of a lens left a white wedge at each corner, where the face curves away from the port."""

    scene, laser, near, far, dump = _telescope()
    pieces = scene.lens_beam(laser, near, far, dump, width=1.0, mm_per_unit=SCALE, wavelength=450)
    middle = near.world_position
    assert pieces[0].resolve_points()[-1][:2] == pytest.approx((middle.x, middle.y))
    assert pieces[1].corners()[0][0] == pytest.approx(middle.x)
    run = scene.add(Beam.through(laser, near, dump, wavelength=450))
    assert len(run.segments()) == 1                      # the lens is drawn over it: one band, no span left out


def test_a_cone_starts_as_wide_as_the_beam_it_continues_at_the_middle_of_the_lens():
    scene, laser, near, far, dump = _telescope()
    band, cone, *_ = scene.lens_beam(laser, near, far, dump, width=1.0, mm_per_unit=SCALE, wavelength=450)
    corners = cone.corners()
    assert abs(corners[0][1] - corners[1][1]) == pytest.approx(band.display_width)
