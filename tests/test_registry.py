"""Tests for the unified component registry."""

from __future__ import annotations

import pytest

from optodraw.catalog import list_components
from optodraw.mcp_server import _build_scene_from_spec
from optodraw.registry import (
    build_component,
    component_registry,
    creatable_component_names,
    get_component_class,
)


class TestRegistryCatalogAlignment:
    def test_catalog_and_registry_same_keys(self):
        catalog_names = set(list_components())
        registry_names = set(creatable_component_names())
        assert catalog_names == registry_names


class TestRegistryClasses:
    def test_registry_classes_importable(self):
        for spec in component_registry().values():
            assert isinstance(spec.cls, type)


class TestRegistryBuild:
    def test_build_component_prism(self):
        prism = build_component("Prism", center=(0, 0), angle=0)
        assert prism.component_type == "Prism"

    def test_build_component_mirror_is_flat(self):
        mirror = build_component("Mirror", center=(1, 2), angle=45)
        assert mirror.component_type == "Mirror" and mirror.surface_type == "flat"

    @pytest.mark.parametrize("alias", ["FlatMirror", "DiconcaveMirror", "PolarizingBeamSplitter"])
    def test_removed_alias_parts_are_unknown(self, alias):
        with pytest.raises(KeyError, match="Unknown component"):
            build_component(alias)

    def test_get_component_class_missing(self):
        assert get_component_class("NotARealComponent") is None


class TestMcpBuildScene:
    def test_mcp_build_scene_smoke(self):
        spec = {
            "title": "Registry Smoke",
            "components": [
                {"type": "Laser", "center": [0, 0], "angle": 0, "id": "las"},
                {"type": "Mirror", "center": [20, 0], "angle": 45, "id": "mir"},
                {"type": "Prism", "center": [40, 0], "angle": 0, "id": "prism"},
            ],
            "beams": [
                {"path": ["las", "mir", "prism"], "wavelength": 532},
            ],
        }
        scene = _build_scene_from_spec(spec)
        component_types = [node.component_type for node in scene.walk() if node.component_type != "Group"]
        assert len(component_types) == 4
        assert "Prism" in component_types

    def test_mcp_builds_previously_missing_components(self):
        spec = {
            "components": [
                {"type": "Polarizer", "center": [0, 0]},
                {"type": "GratingCouplerArray", "center": [10, 0], "count": 2},
                {"type": "Razor", "center": [20, 0]},
            ],
        }
        scene = _build_scene_from_spec(spec)
        types = {
            node.component_type
            for node in scene.walk()
            if node.component_type not in {"Group", "Beam"}
        }
        assert types == {"Polarizer", "GratingCouplerArray", "Razor"}


def test_no_part_description_has_an_em_or_en_dash():
    """The descriptions show in the editor's palette and on the site's parts table, which use neither dash."""

    from optodraw.registry import component_registry

    dashed = [name for name, spec in component_registry().items() if "—" in spec.description or "–" in spec.description]
    assert dashed == []
