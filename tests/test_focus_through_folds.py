"""A flat fold mirror after a lens is not the focal plane: the focus check measures along the folds."""

from __future__ import annotations

from optodraw import Beam, Camera, Lens, Mirror, Photodiode, Scene, check_figure
from optodraw.layout import aim, face


def _folded(distance_after_fold: float, *, detector=Camera):
    """A lens of focal length 40 on a level beam, a fold mirror 13 after it, then a detector below the fold."""

    scene = Scene(title="", platform="free_space")
    lens = scene.add(Lens(center=(0, 0), angle=-90, focal_length=40, label="L1"))
    fold = scene.add(Mirror(center=(0, -13), label="M"))
    end = scene.add(detector(center=(distance_after_fold, -13), label="Det"))
    source = scene.add(Mirror(center=(0, 20), label="M0"))
    aim(fold, lens, end)
    face(end, fold)
    scene.add(Beam.through(source, lens, fold, end, wavelength=560))
    return scene


def _focus_findings(scene):
    return [line for line in check_figure(scene, view="2d") if "off its focus" in line]


def test_a_fold_mirror_is_not_reported_as_the_focus():
    assert not any(line.startswith("M ") for line in _focus_findings(_folded(30)))


def test_a_detector_at_the_focus_along_the_fold_passes():
    assert _focus_findings(_folded(30)) == []                  # 13 + about 27 to the camera face: 40


def test_a_detector_off_the_focus_along_the_fold_is_named():
    findings = _focus_findings(_folded(60))
    assert len(findings) == 1 and findings[0].startswith("Det sits") and "L1" in findings[0]


def test_a_detector_straight_after_its_lens_is_still_checked():
    scene = Scene(title="", platform="free_space")
    source = scene.add(Mirror(center=(-20, 0), label="M0"))
    lens = scene.add(Lens(center=(0, 0), focal_length=10, label="L"))
    pd = scene.add(Photodiode(center=(30, 0), label="PD"))
    scene.add(Beam.through(source, lens, pd, wavelength=633))
    assert [line for line in _focus_findings(scene) if line.startswith("PD sits")]
