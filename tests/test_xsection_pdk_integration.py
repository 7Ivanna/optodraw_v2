"""Optional open-PDK cross-section integration (user-local paths only)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.xsection_pdk

EXPECTED_LAYERS_ENV = "OPTODRAW_OPEN_PDK_EXPECT_LAYERS"


def _user_process_path() -> Path | None:
    raw = os.environ.get("OPTODRAW_OPEN_PDK_STACK", "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.exists() else None


def _expected_layers() -> set[str]:
    raw = os.environ.get(EXPECTED_LAYERS_ENV, "").strip()
    if not raw:
        return set()
    return {name.strip() for name in raw.split(",") if name.strip()}


def _assert_bundle_structure(bundle, process, *, expected_nonempty: set[str] | None = None) -> None:
    assert bundle.composite_path.exists()
    assert bundle.manifest_path is not None
    assert bundle.manifest_path.exists()
    assert bundle.output_stack is not None

    expected_names = {layer.name for layer in process.output_layers}
    stack_layers = {layer.name: layer for layer in bundle.output_stack.layers}
    assert expected_names == set(stack_layers)
    if process.render.separate_layers:
        assert expected_names == set(bundle.layer_paths)
        assert all(path.exists() for path in bundle.layer_paths.values())

    nonempty = {name for name, layer in stack_layers.items() if not layer.geometry.is_empty}
    assert nonempty
    if expected_nonempty:
        assert expected_nonempty.issubset(nonempty)


@pytest.fixture
def open_pdk_process_path() -> Path:
    user_path = _user_process_path()
    if user_path is not None:
        return user_path
    pytest.skip("Set OPTODRAW_OPEN_PDK_STACK to a local open PDK process YAML")


@pytest.fixture
def open_pdk_gds_path() -> Path | None:
    raw = os.environ.get("OPTODRAW_OPEN_PDK_GDS", "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.exists() else None


class TestOpenPdkCrossSectionIntegration:
    def test_process_yaml_loads_and_exports_synthetic_layout_layers_cut(self, open_pdk_process_path, tmp_path):
        pytest.importorskip("yaml")
        from optodraw.gds.xsection import CrossSectionStripLayout, XSectionEngine, export_xsection_bundle

        engine = XSectionEngine.from_yaml(open_pdk_process_path)
        layout = CrossSectionStripLayout()
        layer_names = list(engine.process.layout_layers)
        if not layer_names:
            pytest.skip("Open PDK process YAML has no layout_layers entries")
        center_index = (len(layer_names) - 1) / 2.0
        for index, name in enumerate(layer_names):
            layout.strip(
                name,
                width_um=0.4 + 0.08 * index,
                center_y_um=(index - center_index) * 0.35,
            )
        cut = layout.section(label="open-pdk-synthetic").to_layout_cut()
        bundle = export_xsection_bundle(engine, cut, tmp_path)
        _assert_bundle_structure(bundle, engine.process, expected_nonempty=_expected_layers())

    def test_optional_gds_cut_when_env_set(self, open_pdk_process_path, open_pdk_gds_path, tmp_path):
        if open_pdk_gds_path is None:
            pytest.skip("OPTODRAW_OPEN_PDK_GDS not set")
        pytest.importorskip("gdstk")
        from optodraw.gds.layout import load_gds_layout
        from optodraw.gds.xsection import XSectionEngine, export_xsection_bundle
        from optodraw.gds.xsection.masks import LayoutCut

        engine = XSectionEngine.from_yaml(open_pdk_process_path)
        layout = load_gds_layout(open_pdk_gds_path)
        cut = LayoutCut.from_gds(
            layout,
            {"x": 0.0, "window": 4.0, "label": "pdk-integration"},
            process=engine.process,
        )
        bundle = export_xsection_bundle(engine, cut, tmp_path)
        _assert_bundle_structure(bundle, engine.process, expected_nonempty=_expected_layers())
