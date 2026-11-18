"""check_figure names a waveguide that leaves or meets its port from behind: the part faces the wrong way.

A grating coupler placed left of a detector at angle 0 points its waveguide port left, away from the detector. The
router cannot turn round on one line, so the waveguide runs back through the coupler to the detector, and no other
check sees it: the route only crosses the two parts it joins.
"""

import runpy
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


def test_a_coupler_facing_the_detector_passes():
    assert _backwards(check_figure(_coupler_to_detector(180), view="2d")) == []


def test_the_docs_amplifier_feeds_its_detector_from_the_front():
    scene = runpy.run_path(str(DOCS_TIA))["scene"]
    assert check_figure(scene, view="both") == []
    light = next(n for n in scene.walk() if n.component_type == "VerticalGratingCoupler")
    pd = next(n for n in scene.walk() if n.component_type == "OnChipPhotodetector")
    port = light.world_port("o1")
    assert port.normal().x > 0.99 and port.center.x < pd.world_port("o1").center.x       # it faces the detector


def test_a_wire_bond_from_a_pad_centre_is_not_backwards():
    """A bond leaves a pad's centre in any direction: only an optical port has a front."""

    scene = runpy.run_path(str(DOCS_TIA.with_name("03-package.py")))["scene"]
    assert _backwards(check_figure(scene, view="2d")) == []
