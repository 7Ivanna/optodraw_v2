"""Smoke tests for the flagship ring-filter end-to-end demo."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
DEMO_PATH = REPO_ROOT / "examples" / "flagship_ring_filter_demo.py"


def _load_demo_module():
    spec = importlib.util.spec_from_file_location("flagship_ring_filter_demo", DEMO_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class TestFlagshipRingFilterDemo:
    def test_demo_module_imports(self):
        module = _load_demo_module()
        assert callable(module.main)
        assert callable(module.build_scene)
        assert callable(module.run_pipeline)

    def test_build_scene_has_gc_ring_pd_routes(self):
        module = _load_demo_module()
        scene, gc, ring, pd, routes = module.build_scene()

        assert scene.platform == "on_chip"
        assert gc.label == "GC"
        assert ring.component_type == "MicroringResonator"
        assert pd.component_type == "OnChipPhotodetector"
        assert len(routes) == 4

    def test_run_physics_returns_expected_keys(self):
        module = _load_demo_module()
        scene, gc, ring, pd, routes = module.build_scene()
        summary = module.run_physics(scene, gc=gc, ring=ring, pd=pd, routes=routes)

        assert summary.guided["path_length_um"] > 0.0
        assert "through_power" in summary.resonance
        assert isinstance(summary.validation_warnings, list)

    def test_run_pipeline_core_exports(self, tmp_path):
        module = _load_demo_module()
        result = module.run_pipeline(output_dir=tmp_path / "flagship", write_gif=False, run_blender=False)

        artifacts = result["artifacts"]
        for key in ("svg", "tikz", "html", "json", "physics"):
            path = artifacts[key]
            assert path is not None
            assert path.exists()

        spec = json.loads(artifacts["json"].read_text(encoding="utf-8"))
        assert spec["platform"] == "on_chip"
        assert any(item.get("type") == "MicroringResonator" for item in spec.get("components", []))

        physics = json.loads(artifacts["physics"].read_text(encoding="utf-8"))
        assert "guided_path" in physics
        assert "resonance" in physics

    def test_main_cli_smoke(self, tmp_path, capsys):
        module = _load_demo_module()
        exit_code = module.main(["--output-dir", str(tmp_path / "cli_out")])
        captured = capsys.readouterr()

        assert exit_code == 0
        assert "Flagship demo complete" in captured.out
        assert (tmp_path / "cli_out" / "ring_filter.svg").exists()

    def test_glb_export_when_trimesh_available(self, tmp_path):
        pytest.importorskip("trimesh")
        pytest.importorskip("shapely")
        module = _load_demo_module()
        scene, *_rest = module.build_scene()
        glb_path = tmp_path / "ring_filter.glb"

        assert module.try_export_glb(scene, glb_path) is True
        assert glb_path.exists()
        assert glb_path.stat().st_size > 0

    def test_glb_export_skips_without_trimesh(self, tmp_path, monkeypatch):
        module = _load_demo_module()
        scene, *_rest = module.build_scene()
        glb_path = tmp_path / "missing.glb"

        original_import = __import__

        def _block_trimesh(name, *args, **kwargs):
            if name == "trimesh":
                raise ImportError("trimesh unavailable")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr("builtins.__import__", _block_trimesh)
        assert module.try_export_glb(scene, glb_path) is False
        assert not glb_path.exists()
