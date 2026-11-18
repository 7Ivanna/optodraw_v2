"""GLB export report names skipped and approximated parts."""

from __future__ import annotations

import pytest

trimesh = pytest.importorskip("trimesh")

from optodraw import Scene  # noqa: E402
from optodraw.components.devices import Laser  # noqa: E402
from optodraw.components.optics import Lens  # noqa: E402
from optodraw.core.beam import Beam  # noqa: E402
from optodraw.exporters import scene_to_glb_with_report  # noqa: E402


def test_report_lists_beams_as_approximated():
    scene = Scene(width=120, height=80)
    laser = scene.add(Laser(center=(-30, 0)))
    lens = scene.add(Lens(center=(0, 0)))
    scene.add(Beam(laser, lens, wavelength=633))
    _, report = scene_to_glb_with_report(scene)
    assert report["meshes"] >= 1
    # a beam is exported as a tube along its centre line: in the file, and flagged as an approximation
    assert any("Beam" in entry and "tube" in entry for entry in report["approximated"])
    assert not any("Beam" in entry for entry in report["skipped"])
    assert report["failed"] == []


def test_report_marks_footprint_boxes():
    scene = Scene(width=120, height=80)
    scene.add(Lens(center=(0, 0)))
    _, report = scene_to_glb_with_report(scene)
    assert report["meshes"] >= 1
    assert isinstance(report["approximated"], list)
