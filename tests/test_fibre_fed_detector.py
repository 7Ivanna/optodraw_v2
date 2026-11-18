"""A detector that a fibre feeds receives light: the no-light check counts the fibre's end."""

from optodraw import Beam, FiberCollimator, FiberRoute, Laser, Scene, Spectrometer
from optodraw.app.validation import run_checks


def _dark(scene):
    return [issue for issue in run_checks(scene) if issue["kind"] == "illumination"]


def test_a_spectrometer_at_the_end_of_a_fibre_is_lit():
    scene = Scene(title="", width=200, height=80, platform="free_space")
    laser = scene.add(Laser(center=(-60, 0), wavelength=785))
    collimator = scene.add(FiberCollimator(center=(-30, 0), angle=180))
    spectrometer = scene.add(Spectrometer(center=(40, 0), angle=180))
    scene.add(Beam.through(laser, (collimator, "out")))
    scene.add(FiberRoute([(-24, 0), (30, 0)], start_component=collimator, start_port="in",
                         end_component=spectrometer, end_port="in"))
    assert _dark(scene) == []


def test_a_spectrometer_no_beam_and_no_fibre_reaches_is_still_dark():
    scene = Scene(title="", width=200, height=80, platform="free_space")
    laser = scene.add(Laser(center=(-60, 0), wavelength=785))
    collimator = scene.add(FiberCollimator(center=(-30, 0), angle=180))
    scene.add(Spectrometer(center=(40, 30), angle=180, label="Spec"))
    scene.add(Beam.through(laser, (collimator, "out")))
    assert [issue["message"][:4] for issue in _dark(scene)] == ["Spec"]
