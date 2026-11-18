"""The lenses on a beam's way set its drawn width: the focal lengths give the ratios, the first width the scale."""

from __future__ import annotations


import pytest

from optodraw import Beam, BeamDump, Camera, FocusingBeam, Laser, Lens, Objective, Sample, Scene, check_figure
from optodraw.app.validation import run_checks

SCALE = 150.0 / 24.0                                     # a 150 mm telescope drawn 24 units long


def _telescope():
    scene = Scene(title="telescope", width=160, height=60, platform="free_space")
    laser = scene.add(Laser(center=(-60, 0), wavelength=450, label="Laser"))
    near = scene.add(Lens(center=(-26, 0), focal_length=50, label="f 50"))
    far = scene.add(Lens(center=(-2, 0), focal_length=100, label="f 100"))
    dump = scene.add(BeamDump(center=(30, 0), angle=180, label="Dump"))
    return scene, laser, near, far, dump


def test_a_telescope_drawn_short_says_the_scale_that_fixes_it():
    scene, laser, near, far, dump = _telescope()
    with pytest.warns(UserWarning, match=r"mm_per_unit=6\.25"):
        scene.lens_beam(laser, near, far, dump, width=1.0, wavelength=450)


def test_a_lens_alone_is_one_stop():
    scene, _, near, _, _ = _telescope()
    with pytest.raises(ValueError, match="two stops"):
        scene.lens_beam((near, "in"), (near, "out"), width=1.0)


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


def test_a_lane_stays_on_its_side_of_the_light_through_a_lens():
    scene, laser, near, far, dump = _telescope()
    pieces = scene.lens_beam(laser, near, far, dump, width=1.0, mm_per_unit=SCALE, wavelength=450, offset=1.5)
    assert {round(float(point[1]), 6) for piece in pieces if isinstance(piece, Beam)
            for point in piece.resolve_points()} == {1.5}
    assert {round(float(end.y), 6) for piece in pieces if isinstance(piece, FocusingBeam)
            for end in piece.endpoints()} == {1.5}


def test_a_distance_scale_must_be_positive():
    scene, laser, near, far, dump = _telescope()
    with pytest.raises(ValueError, match="mm_per_unit"):
        scene.lens_beam(laser, near, far, dump, width=1.0, mm_per_unit=0.0, wavelength=450)


def test_the_figure_gate_reads_the_pieces_as_one_path():
    scene, laser, near, far, dump = _telescope()
    scene.lens_beam(laser, near, far, dump, width=1.0, mm_per_unit=SCALE, wavelength=450)
    scene.fit_frame()
    assert [finding for finding in check_figure(scene) if "beam" in finding] == []


def test_a_cone_that_ends_on_a_camera_is_light_on_the_camera():
    scene = Scene(title="focus", width=160, height=60, platform="free_space")
    laser = scene.add(Laser(center=(-60, 0), wavelength=633))
    lens = scene.add(Lens(center=(0, 0), focal_length=30))
    camera = scene.add(Camera(center=(30, 0), angle=180, label="Camera"))
    scene.lens_beam(laser, lens, (camera, "in"), width=1.0, wavelength=633)
    assert [i for i in run_checks(scene) if "receives no light" in i["message"]] == []


def scene_svg(scene, tmp_path_factory=None):
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "scene.svg"
        scene.render_svg(path)
        return path.read_text(encoding="utf-8")


