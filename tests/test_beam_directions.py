"""Light leaves a port along its outward direction and enters the next port against it."""

from __future__ import annotations

from optodraw import Beam, Laser, Photodiode, Scene
from optodraw.app.validation import run_checks


def _bench(laser_angle=0.0, pd_angle=0.0):
    scene = Scene(title="bench", width=100, height=40, platform="free_space")
    laser = scene.add(Laser(center=(-30, 0), angle=laser_angle, label="Laser"))
    pd = scene.add(Photodiode(center=(30, 0), angle=pd_angle, label="PD"))
    scene.add(Beam.through(laser, pd))
    return scene


def _beam_issues(scene):
    return [issue["message"] for issue in run_checks(scene) if issue["kind"] == "beam"]


def test_a_detector_that_faces_its_beam_is_quiet():
    assert _beam_issues(_bench()) == []


def test_a_detector_turned_away_is_lit_from_behind():
    issues = _beam_issues(_bench(pd_angle=180.0))
    assert any("PD" in message and "from behind" in message for message in issues)


def test_a_laser_turned_away_sends_its_beam_backwards():
    issues = _beam_issues(_bench(laser_angle=180.0))
    assert any("Laser" in message and "backwards" in message for message in issues)


def test_face_turns_a_detector_toward_its_source():
    from optodraw.layout import face

    scene = Scene(title="bench", width=100, height=60, platform="free_space")
    laser = scene.add(Laser(center=(0, -20), angle=90, label="Laser"))
    pd = scene.add(Photodiode(center=(0, 20), angle=0, label="PD"))         # its input faces west, away from the beam
    face(pd, laser)
    scene.add(Beam.through(laser, pd))
    assert round(pd.world_port("in").orientation_deg % 360) == 270          # it now looks down at the laser
    assert _beam_issues(scene) == []


def test_a_beam_that_leans_a_little_off_a_straight_run_is_reported():
    scene = Scene(title="bench", width=100, height=40, platform="free_space")
    laser = scene.add(Laser(center=(-30, 0), label="Laser"))
    pd = scene.add(Photodiode(center=(30, 0.5), label="PD"))
    scene.add(Beam.through(laser, pd))
    assert any("leans" in message and "PD" in message for message in _beam_issues(scene))


def test_a_level_or_a_diagonal_beam_does_not_lean():
    assert not any("leans" in m for m in _beam_issues(_bench()))
    scene = Scene(title="bench", width=100, height=100, platform="free_space")
    laser = scene.add(Laser(center=(-30, -30), angle=45, label="Laser"))
    pd = scene.add(Photodiode(center=(30, 30), angle=45, label="PD"))
    scene.add(Beam.through(laser, pd))
    assert not any("leans" in m for m in _beam_issues(scene))


def test_a_beam_meets_a_plate_splitter_at_its_centre_so_aligned_runs_stay_straight():
    """The plate's ports sit along its face; a beam drawn to them leaned about a degree on every run."""

    from optodraw import BeamSplitter, Mirror, Sample
    from optodraw.layout import aim, face

    scene = Scene(title="split", width=120, height=80, platform="free_space")
    laser = scene.add(Laser(center=(-40, 0), label="Laser"))
    bs = scene.add(BeamSplitter(center=(0, 0), label="BS"))
    sample = scene.add(Sample(center=(30, 0), label="Sample"))
    mirror = scene.add(Mirror(center=(0, 30), label="M"))
    pd = scene.add(Photodiode(center=(40, 30), label="PD"))
    aim(bs, laser, mirror)
    aim(mirror, bs, pd)
    face(pd, mirror)
    beam = scene.add(Beam.through(laser, bs, sample))
    scene.add(Beam.through((bs, "refl"), mirror, pd))
    points = beam.resolve_points()
    assert all(abs(y) < 1e-9 for _, y, _ in points)                      # level all the way through the plate
    assert not any("leans" in message for message in _beam_issues(scene))


def test_a_lens_turned_along_its_beam_is_reported():
    """A lens at angle=90 on a level beam lies flat along it: the light must pass through its faces."""

    from optodraw import Lens

    def bench(angle):
        scene = Scene(title="lens", width=120, height=40, platform="free_space")
        laser = scene.add(Laser(center=(-40, 0), label="Laser"))
        lens = scene.add(Lens(center=(0, 0), angle=angle, focal_length=40, label="L"))
        pd = scene.add(Photodiode(center=(40, 0), label="PD"))
        scene.add(Beam.through(laser, lens, pd))
        return [i["message"] for i in run_checks(scene)]

    assert any("runs along L" in m for m in bench(90))
    assert not [m for m in bench(0) if "runs along" in m]
