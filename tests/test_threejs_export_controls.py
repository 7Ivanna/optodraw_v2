"""Smoke tests for the Three.js page's export controls (in the bottom bar) and camera presets."""

from __future__ import annotations

from optodraw import Scene
from optodraw.components.devices import Laser
from optodraw.components.optics import Mirror
from optodraw.renderers.threejs_renderer import ThreeJsRenderer


class TestThreeJsExportControls:
    def test_default_html_includes_export_toolbar_hooks(self):
        scene = Scene(title="Export Demo", width=120, height=80, platform="free_space")
        scene.add(Laser(center=(-20, 0), label="Laser"))
        scene.add(Mirror(center=(10, 0), angle=45, label="M1"))

        html = scene.render_threejs()

        assert 'id="od-bar"' in html
        assert 'data-optodraw-export-controls="true"' in html
        assert 'id="btn-export-png"' in html
        assert 'data-export-hook="png"' in html
        assert 'id="btn-export-json"' in html
        assert 'data-export-hook="json"' in html
        assert 'id="btn-camera-top"' in html
        assert 'id="btn-camera-isometric"' in html
        assert 'id="btn-camera-side"' in html
        assert "applyCameraPreset" in html
        assert "downloadPngScreenshot" in html
        assert "downloadSceneJson" in html
        assert '"schema_version"' in html

    def test_mesh_scene_enables_glb_export(self):
        scene = Scene(platform="free_space")
        scene.add(Laser(center=(0, 0), label="Laser"))
        scene.add(Mirror(center=(20, 0), angle=45, label="M1"))

        html = scene.render_threejs()

        assert 'id="btn-export-glb"' in html
        assert 'data-export-hook="glb"' in html
        assert "GLTFExporter" in html
        assert "downloadGlb" in html
        assert 'id="btn-export-glb" data-export-hook="glb">3D model (GLB)</button>' in html

    def test_beam_only_data_disables_glb_export(self):
        scene = Scene(platform="free_space", title="Beams Only")
        renderer = ThreeJsRenderer(scene, show_export_controls=True)
        html = renderer._build_html(
            [
                {
                    "type": "beam",
                    "points": [[0, 0, 0], [10, 0, 0]],
                    "color": "#ff0000",
                    "position": [0, 0, 0],
                    "rotation": [0, 0, 0],
                }
            ]
        )

        assert 'id="btn-export-glb"' in html
        assert 'id="btn-export-glb" data-export-hook="glb" disabled' in html
        assert "GLTFExporter" not in html
        assert "function downloadGlb" not in html

    def test_show_export_controls_false_omits_toolbar(self):
        scene = Scene()
        scene.add(Laser(center=(0, 0), label="Laser"))

        html = scene.render_threejs(show_export_controls=False)

        # no bar element; the light player may name the id in its lookup code
        assert 'id="od-bar"' not in html and 'role="toolbar"' not in html
        assert "btn-export-png" not in html
        assert "applyCameraPreset" not in html
        assert "data-show-export-controls" not in html

    def test_renderer_geometry_exportable_helper(self):
        mesh_data = [{"type": "mesh", "geometry": {"shape": "box"}}]
        beam_data = [{"type": "beam", "points": [[0, 0, 0], [1, 0, 0]]}]

        assert ThreeJsRenderer._geometry_exportable(mesh_data) is True
        assert ThreeJsRenderer._geometry_exportable(beam_data) is False

    def test_backward_compatible_without_kwarg(self):
        scene = Scene()
        scene.add(Mirror(center=(0, 0), angle=0, label="M"))

        html = scene.render_threejs()

        assert "<!DOCTYPE html>" in html
        assert "three" in html.lower()
        assert 'id="btn-export-png"' in html
