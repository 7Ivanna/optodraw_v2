"""Smoke tests for publication figure templates and export bundles."""

from __future__ import annotations

import json

import pytest

from optodraw import Laser, Mirror, Scene, build_qwp_circular_lab
from optodraw.publication import (
    export_figure_bundle,
    list_paper_figure_presets,
    paper_figure_preset,
)


class TestPaperFigurePreset:
    def test_list_presets_nonempty(self):
        presets = list_paper_figure_presets()
        assert "single_column" in presets
        assert "double_column" in presets

    def test_single_column_has_expected_keys(self):
        preset = paper_figure_preset("single_column")
        assert preset["width"] == pytest.approx(89.0)
        assert preset["height"] == pytest.approx(70.0)
        assert "font_size_pt" in preset
        assert "camera_distance" in preset
        assert preset["lighting_preset"] == "publication"
        assert preset["render_quality"] == "publication"

    def test_alias_resolves(self):
        assert paper_figure_preset("two_column") == paper_figure_preset("double_column")

    def test_unknown_preset_raises(self):
        with pytest.raises(KeyError, match="Unknown paper figure preset"):
            paper_figure_preset("not_a_preset")


class TestExportFigureBundle:
    def test_export_bundle_smoke(self, tmp_path):
        scene = Scene(title="Michelson Demo", width=180, height=100)
        laser = scene.add(Laser(center=(0, 0), wavelength=633, label="Laser"))
        mirror = scene.add(Mirror(center=(40, 0), angle=45, label="M1"))

        written = export_figure_bundle(scene, tmp_path, preset="single_column")

        assert set(written) == {"svg", "html", "json", "manifest"}
        assert written["svg"].name == "michelson_demo.svg"
        assert written["html"].name == "michelson_demo.html"
        assert written["json"].name == "michelson_demo.json"
        assert written["svg"].read_text().lstrip().startswith("<")
        html = written["html"].read_text()
        assert "three" in html.lower()
        assert 'data-optodraw-lighting-preset="publication"' in html
        assert 'data-optodraw-render-quality="publication"' in html
        payload = json.loads(written["json"].read_text())
        assert payload["title"] == "Michelson Demo"
        assert laser.label in json.dumps(payload)
        assert mirror.label in json.dumps(payload)

    def test_polarization_overlay_option(self, tmp_path):
        scene = build_qwp_circular_lab()
        written = export_figure_bundle(
            scene,
            tmp_path,
            formats=("svg",),
            include_polarization=True,
            stem="qwp_lab",
        )
        svg = written["svg"].read_text()
        assert "ellipse" in svg.lower()

    def test_scene_wrapper(self, tmp_path):
        scene = Scene(title="Wrapper Test")
        scene.add(Laser(center=(0, 0), wavelength=532))
        written = scene.export_paper_figures(tmp_path, formats=("json",))
        assert written["json"].exists()

    def test_restores_scene_dimensions(self, tmp_path):
        scene = Scene(title="Dims", width=200, height=120)
        scene.add(Laser(center=(0, 0)))
        export_figure_bundle(scene, tmp_path, formats=("svg",), preset="double_column")
        assert scene.width == pytest.approx(200.0)
        assert scene.height == pytest.approx(120.0)

    def test_clipping_content_warns(self, tmp_path):
        import warnings

        from optodraw.components.optics import Mirror

        scene = Scene(title="Wide", width=200, height=100)
        scene.add(Laser(center=(-70, 0)))
        scene.add(Mirror(center=(70, 0), angle=45))
        with warnings.catch_warnings(record=True) as records:
            warnings.simplefilter("always")
            export_figure_bundle(scene, tmp_path, formats=("svg",), preset="single_column")
        assert any("clips content" in str(w.message) for w in records)

    def test_fitting_content_stays_silent(self, tmp_path):
        import warnings

        scene = Scene(title="Narrow", width=60, height=40)
        scene.add(Laser(center=(0, 0)))
        with warnings.catch_warnings(record=True) as records:
            warnings.simplefilter("always")
            export_figure_bundle(scene, tmp_path, formats=("svg",), preset="single_column")
        assert not [w for w in records if "clips content" in str(w.message)]

    def test_font_size_pt_changes_type(self, tmp_path):
        from optodraw.renderers.svg_renderer import SvgRenderer

        scene = Scene(title="Type", width=120, height=60)
        scene.add(Laser(center=(0, 0), label="Pump"))
        small = SvgRenderer(scene, font_size_pt=7.0).render().as_svg()
        large = SvgRenderer(scene, font_size_pt=20.0).render().as_svg()
        assert small != large

    def test_manifest_records_figure_provenance(self, tmp_path):
        import json as _json

        scene = Scene(title="Manifest Demo", width=180, height=100)
        scene.add(Laser(center=(0, 0), label="Pump"))
        written = export_figure_bundle(scene, tmp_path, preset="single_column")
        manifest = _json.loads(written["manifest"].read_text(encoding="utf-8"))
        assert manifest["title"] == "Manifest Demo"
        assert manifest["optodraw_version"]
        assert manifest["scene_hash_sha256"]
        assert manifest["extras"]["preset"] == "single_column"
        assert set(manifest["panels"][0]["paths"]) >= {"svg", "html", "json"}
