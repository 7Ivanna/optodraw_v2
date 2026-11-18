"""Smoke tests for publication figure templates and export bundles."""

from __future__ import annotations


import pytest

from optodraw import Laser, Scene, build_qwp_circular_lab
from optodraw.publication import (
    export_figure_bundle,
    paper_figure_preset,
)


class TestPaperFigurePreset:


    def test_unknown_preset_raises(self):
        with pytest.raises(KeyError, match="Unknown paper figure preset"):
            paper_figure_preset("not_a_preset")


class TestExportFigureBundle:

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
