"""Tests for versioned scene schema save/load round-trip."""

from __future__ import annotations

import pytest

from optodraw import Beam, Mirror, Scene
from optodraw.components.devices import Laser
from optodraw.components.optics import Lens
from optodraw.schema import SCHEMA_VERSION, scene_from_spec, scene_to_spec


def _find(scene: Scene, component_type: str, *, label: str | None = None):
    for node in scene.walk():
        if node.component_type != component_type:
            continue
        if label is None or node.label == label:
            return node
    return None


class TestSceneSchemaRoundTrip:
    def test_round_trip_free_space_setup(self):
        scene = Scene(title="Free Space Demo", width=180, height=120, platform="free_space")
        laser = Laser(center=(0, 0), angle=0, wavelength=532, label="Laser")
        mirror = Mirror(center=(40, 0), angle=45, label="Mirror")
        lens = Lens(center=(40, 40), angle=90, focal_length=40, label="L1")
        laser._id = "laser"
        mirror._id = "mirror"
        lens._id = "l1"
        scene.add(laser)
        scene.add(mirror)
        scene.add(lens)
        scene.add(Beam(laser, mirror, lens, wavelength=532, width=0.9))

        spec = scene_to_spec(scene)
        restored = scene_from_spec(spec)

        assert restored.title == "Free Space Demo"
        assert restored.platform == "free_space"
        assert spec["schema_version"] == SCHEMA_VERSION

        restored_laser = _find(restored, "Laser", label="Laser")
        restored_mirror = _find(restored, "Mirror", label="Mirror")
        restored_lens = _find(restored, "Lens", label="L1")
        restored_beam = _find(restored, "Beam")

        assert restored_laser.wavelength == pytest.approx(532)
        assert restored_mirror.transform.angle == pytest.approx(45)
        assert restored_lens.focal_length == pytest.approx(40)
        assert restored_beam.wavelength == pytest.approx(532)
        assert restored_beam.width == pytest.approx(0.9)
        assert len(restored_beam.anchors) == 3


    def test_unknown_schema_version_raises_clear_error(self):
        with pytest.raises(ValueError, match="Unsupported schema version 999"):
            scene_from_spec({"schema_version": 999, "components": []})


