"""Tests for Blender script annotation helpers."""

from __future__ import annotations

import pytest

from optodraw.blender import (
    BlenderClippingPlane,
    BlenderLabel,
    export_blender_script,
)


@pytest.fixture
def source_glb(tmp_path):
    path = tmp_path / "scene.glb"
    path.write_bytes(b"glTF")
    return path


class TestBlenderAnnotations:
    def test_export_includes_scale_bar_helpers(self, tmp_path, source_glb):
        script_path = export_blender_script(
            tmp_path / "render.blender.py",
            source_glb=source_glb,
            scale_bar={"length": 10.0, "unit": "um", "corner": "bottom-left"},
        )
        script = script_path.read_text(encoding="utf-8")

        assert "def add_scale_bar" in script
        assert "'length': 10.0" in script
        assert "'corner': 'bottom_left'" in script
        assert "OptoDraw Scale Bar" in script

    def test_export_includes_labels_and_clipping_planes(self, tmp_path, source_glb):
        script_path = export_blender_script(
            tmp_path / "render.blender.py",
            source_glb=source_glb,
            labels=[
                BlenderLabel(text="Waveguide bus", location=(1.0, 2.0, 0.5)),
                {"text": "Grating coupler", "size": 0.12},
            ],
            clipping_planes=[
                BlenderClippingPlane(axis="z", offset=0.25, keep_positive=False),
                {"axis": "x", "offset": -1.0},
            ],
        )
        script = script_path.read_text(encoding="utf-8")

        assert "def add_labels" in script
        assert "Waveguide bus" in script
        assert "Grating coupler" in script
        assert "def apply_clipping_planes" in script
        assert "'axis': 'z'" in script
        assert "'keep_positive': False" in script

    def test_invalid_scale_bar_corner_raises(self, tmp_path, source_glb):
        with pytest.raises(ValueError, match="scale_bar corner"):
            export_blender_script(
                tmp_path / "render.blender.py",
                source_glb=source_glb,
                scale_bar={"length": 5.0, "corner": "center"},
            )

    def test_extended_camera_presets_compose_with_annotations(self, tmp_path, source_glb):
        # New presets (cross_section, free_space_table) must coexist with the
        # existing label/scale-bar/clipping-plane annotation pipeline.
        script_path = export_blender_script(
            tmp_path / "render.blender.py",
            source_glb=source_glb,
            camera_preset="cross_section",
            scale_bar={"length": 5.0, "unit": "um", "corner": "bottom_right"},
            labels=[BlenderLabel(text="Stack cut", location=(0.0, 0.0, 0.4))],
            clipping_planes=[BlenderClippingPlane(axis="y", offset=0.0)],
        )
        script = script_path.read_text(encoding="utf-8")
        assert "CAMERA_PRESET = 'cross_section'" in script
        assert "CAMERA_DIRECTIONS = {" in script
        assert "'cross_section'" in script
        assert "Stack cut" in script
        assert "OptoDraw Scale Bar" in script
        assert "apply_clipping_planes" in script

    def test_free_space_table_preset_with_overrides(self, tmp_path, source_glb):
        script_path = export_blender_script(
            tmp_path / "render.blender.py",
            source_glb=source_glb,
            camera_preset="free_space_table",
            material_overrides=[{"name": "OpticalTable", "preset": "aluminum"}],
        )
        script = script_path.read_text(encoding="utf-8")
        assert "CAMERA_PRESET = 'free_space_table'" in script
        assert "OpticalTable" in script
        assert "apply_material_overrides" in script
