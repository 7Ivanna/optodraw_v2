"""Tests for registry-driven quickplot notebook helpers."""

from __future__ import annotations

import json
from pathlib import Path

from examples.quickplot_helpers import (
    build_quickplot_scene,
    quickplot_registry_component_names,
    registry_component_names,
)
from optodraw.registry import component_registry


QUICKPLOT_NOTEBOOKS = [
    "quickplot_free_space_components.ipynb",
    "quickplot_onchip_components.ipynb",
    "quickplot_electronics_packaging_components.ipynb",
]


def test_quickplot_groups_cover_registry_components():
    assert set(quickplot_registry_component_names()) == set(component_registry())


def test_quickplot_notebooks_exist_and_are_valid_json():
    examples_dir = Path(__file__).resolve().parents[1] / "examples"
    for name in QUICKPLOT_NOTEBOOKS:
        notebook = json.loads((examples_dir / name).read_text(encoding="utf-8"))
        assert notebook["nbformat"] == 4
        assert any(cell["cell_type"] == "code" for cell in notebook["cells"])


def test_quickplot_group_scenes_render_svg():
    groups = [
        ("free_space", "free_space", 6),
        ("on_chip", "on_chip", 5),
        ("electronics", "mixed", 5),
    ]
    for group, platform, columns in groups:
        scene, failures = build_quickplot_scene(
            registry_component_names(group),
            title=f"{group} quickplot",
            platform=platform,
            columns=columns,
        )
        assert failures == []
        assert "<svg" in scene.render_svg().as_svg()
