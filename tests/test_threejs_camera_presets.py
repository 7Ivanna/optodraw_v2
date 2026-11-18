"""Tests for Three.js camera presets, material preset overrides, and layer legend."""

from __future__ import annotations

import pytest

from optodraw import Scene
from optodraw.blender import CAMERA_PRESETS as BLENDER_CAMERA_PRESETS
from optodraw.components.devices import Laser
from optodraw.components.optics import Mirror
from optodraw.renderers.threejs_renderer import (
    CAMERA_PRESETS,
    LIGHTING_PRESETS,
    _THREEJS_CAMERA_DIRECTIONS,
    list_camera_presets,
    list_lighting_presets,
)


def _make_scene(title: str = "Camera Presets") -> Scene:
    scene = Scene(title=title, width=140, height=80, platform="free_space")
    scene.add(Laser(center=(-20, 0), label="Laser"))
    scene.add(Mirror(center=(10, 0), angle=45, label="M1"))
    return scene


class TestThreeJsCameraPresetTable:
    def test_camera_preset_names_align_with_blender(self):
        # The renderer should expose exactly the canonical Blender presets so
        # that pipelines can reference the same preset name on both sides.
        assert set(CAMERA_PRESETS) == set(BLENDER_CAMERA_PRESETS.keys())
        assert set(list_camera_presets()) == set(CAMERA_PRESETS)

    def test_extended_presets_present(self):
        for name in ("top", "isometric", "side", "front", "cross_section", "free_space_table"):
            assert name in CAMERA_PRESETS
            assert name in _THREEJS_CAMERA_DIRECTIONS
            direction = _THREEJS_CAMERA_DIRECTIONS[name]
            assert len(direction) == 3
            assert any(abs(v) > 0.0 for v in direction)


class TestRenderedToolbarButtons:


    def test_unknown_camera_preset_rejected(self):
        scene = _make_scene()
        with pytest.raises(ValueError, match="camera_preset"):
            scene.render_threejs(camera_preset="overhead")


class TestThreeJsProfessionalPipeline:
    def test_lighting_preset_names_are_listed(self):
        assert set(LIGHTING_PRESETS) == {"studio", "publication", "dramatic"}
        assert set(list_lighting_presets()) == set(LIGHTING_PRESETS)

    def test_publication_pipeline_writes_quality_metadata(self):
        html = _make_scene().render_threejs(
            lighting_preset="publication",
            render_quality="publication",
            postprocessing=True,
        )

        assert 'data-optodraw-lighting-preset="publication"' in html
        assert 'data-optodraw-render-quality="publication"' in html
        assert 'data-optodraw-postprocessing="true"' in html
        assert "lightingPreset: 'publication'" in html
        assert "renderQuality: 'publication'" in html
        assert "renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));" in html
        assert "dirLight.shadow.mapSize.width = 4096;" in html
        assert "renderer.toneMappingExposure = 1.05;" in html
        assert "EffectComposer" in html
        assert "UnrealBloomPass" in html
        assert "composer.render();" in html


    def test_unknown_lighting_and_quality_are_rejected(self):
        scene = _make_scene()

        with pytest.raises(ValueError, match="lighting_preset"):
            scene.render_threejs(lighting_preset="gallery")
        with pytest.raises(ValueError, match="render_quality"):
            scene.render_threejs(render_quality="poster")


class TestMaterialPresetOverrides:
    def test_material_preset_override_merges_into_catalog(self):
        scene = _make_scene()
        html = scene.render_threejs(
            material_preset_overrides={
                "silicon": {"color": "#202020", "roughness": 0.07},
                "custom_neon": {"color": "#33ff99", "metalness": 0.0, "roughness": 0.2},
            }
        )
        assert '"#202020"' in html
        assert '"#33ff99"' in html
        assert "custom_neon" in html


class TestLayerLegendOverlay:
    def test_legend_dict_renders_swatches(self):
        scene = _make_scene("Legend Demo")
        html = scene.render_threejs(
            layer_legend={
                "Waveguide": "#1f77b4",
                "Metal1": {"color": "#bcc4cc", "label": "M1 routing", "description": "Aluminum routing"},
                "VIA": {"color": "#777777"},
            }
        )
        assert 'id="layer-legend"' in html
        assert 'data-optodraw-layer-legend="true"' in html
        assert "layer-legend-swatch" in html
        assert "#1f77b4" in html
        assert "M1 routing" in html
        assert 'title="Aluminum routing"' in html

    def test_legend_list_form_works(self):
        scene = _make_scene("Legend Demo")
        html = scene.render_threejs(
            layer_legend=[
                {"name": "RIB", "color": "#0b7285"},
                {"name": "Metal1", "color": "#bcc4cc", "label": "Routing M1"},
            ]
        )
        assert "RIB" in html
        assert "Routing M1" in html
        assert "#0b7285" in html


