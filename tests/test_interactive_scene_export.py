"""Tests for interactive scene HTML export."""

from __future__ import annotations

from optodraw import Scene
from optodraw.components.devices import Laser
from optodraw.components.optics import Mirror
from optodraw.layout.chip_builder import build_ring_filter
from optodraw.renderers.interactive_scene import export_interactive_html
from optodraw.schema import AUTHORING_PATCH_SCHEMA_VERSION


class TestInteractiveSceneExport:

    def test_chip_scene_lists_physical_spec_and_dimension_toggle(self):
        built = build_ring_filter(title="Interactive Ring Filter")
        scene = built["scene"]
        built["grating_coupler"]._id = "gc"
        built["ring"]._id = "ring"

        html = export_interactive_html(scene, show_grid=False, camera_distance=175)

        assert 'data-component-id="gc"' in html
        assert 'data-component-id="ring"' in html
        assert "MicroringResonator" in html
        assert "ring_radius" in html or "component-spec" in html
        assert 'id="btn-toggle-dimensions"' in html
        bar = html[html.index('<div id="od-bar"'):html.index("<!-- /od-bar -->")]
        assert 'id="btn-toggle-dimensions"' in bar                          # a button of the bar, like Labels
        assert 'data-dimension-toggle="true"' in html
        assert "dimensionMarkersGroup" in html

    def test_scene_render_interactive_html_wrapper(self, tmp_path):
        scene = Scene(platform="free_space")
        scene.add(Mirror(center=(0, 0), angle=0, label="M"))

        out = tmp_path / "interactive.html"
        html = scene.render_interactive_html(out.as_posix(), show_dimension_markers=False)

        assert out.is_file()
        assert 'id="component-sidebar"' in html
        assert "component-row" in html


    def test_default_authoring_panel_exports_patch_controls(self):
        scene = Scene(title="Interactive Authoring", width=120, height=80, platform="free_space")
        scene.add(Laser(center=(-20, 0), label="Pump"))

        html = export_interactive_html(scene, show_dimension_markers=False)

        assert 'data-optodraw-authoring-panel="true"' in html
        assert 'id="author-label"' in html
        assert 'id="author-color"' in html
        assert 'id="author-opacity"' in html
        assert 'id="author-visible"' in html
        assert 'id="btn-download-authoring-patch"' in html
        assert "authoringPatch" in html
        assert "downloadAuthoringPatchJson" in html
        assert "applyAuthoringState" in html
        assert "Object.keys(authoringPatch).sort()" in html
        assert '"color":' in html
        assert '"opacity":' in html


    def test_scene_apply_authoring_patch_updates_display_metadata(self):
        scene = Scene(title="Authoring Patch Demo", width=120, height=80, platform="free_space")
        pump = scene.add(Laser(center=(-20, 0), label="Pump"))

        scene.apply_authoring_patch(
            {
                "schema_version": AUTHORING_PATCH_SCHEMA_VERSION,
                "generated_by": "test",
                "patches": [
                    {
                        "component_id": "Pump",
                        "component_type": "Laser",
                        "label": "Seed",
                        "color": "#123456",
                        "opacity": 0.4,
                        "visible": False,
                    }
                ],
            }
        )

        assert pump.label == "Seed"
        assert pump.color == "#123456"
        assert pump.opacity == 0.4
        assert getattr(pump, "visible") is False
