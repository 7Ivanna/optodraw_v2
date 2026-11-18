"""Smoke tests for the flagship ring-filter end-to-end demo."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


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


    def test_run_physics_returns_expected_keys(self):
        module = _load_demo_module()
        scene, gc, ring, pd, routes = module.build_scene()
        summary = module.run_physics(scene, gc=gc, ring=ring, pd=pd, routes=routes)

        assert summary.guided["path_length_um"] > 0.0
        assert "through_power" in summary.resonance
        assert isinstance(summary.validation_warnings, list)


