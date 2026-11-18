"""check_figure names a waveguide that leaves or meets its port from behind: the part faces the wrong way.

A grating coupler placed left of a detector at angle 0 points its waveguide port left, away from the detector. The
router cannot turn round on one line, so the waveguide runs back through the coupler to the detector, and no other
check sees it: the route only crosses the two parts it joins.
"""

from pathlib import Path

from optodraw import OnChipPhotodetector, Scene, VerticalGratingCoupler, check_figure

DOCS_TIA = Path(__file__).resolve().parents[1] / "docs" / "examples" / "electronics" / "02-tia.py"


def _coupler_to_detector(angle):
    scene = Scene(title="feed", platform="on_chip")
    gc = scene.add(VerticalGratingCoupler(center=(-60, 0), angle=angle, label="in"))
    pd = scene.add(OnChipPhotodetector(center=(0, 0), label="PD", label_side="top"))
    scene.route((gc, "o1"), (pd, "o1"))
    scene.fit_frame(margin=4)
    return scene


def _backwards(findings):
    return [f for f in findings if "backwards" in f]


def test_a_coupler_facing_away_is_named():
    found = _backwards(check_figure(_coupler_to_detector(0), view="2d"))
    assert len(found) == 1 and "in:o1" in found[0], found


