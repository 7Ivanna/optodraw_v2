"""Tests for Tier 2 product contract foundation."""

from __future__ import annotations

import warnings

import pytest

from optodraw import Scene, Waveguide
from optodraw.catalog import describe_component
from optodraw.components.misc import Grid
from optodraw.components.optics import Prism
from optodraw.registry import component_registry, describe_physics_support
from optodraw.schema import UNITS, scene_from_spec, validate_units


class TestChipComponentVisualContract:
    def test_waveguide_accepts_visual_style_and_scale(self):
        wg = Waveguide(center=(0, 0), visual_style="symbolic", visual_scale=2.0, length=10.0, width=0.5)
        assert wg.visual_style == "symbolic"
        assert wg.visual_scale == pytest.approx(2.0)
        assert wg.length == pytest.approx(10.0)
        assert wg.width == pytest.approx(0.5)
        assert wg.schematic_dims()["length"] == pytest.approx(48.0)

    def test_invalid_visual_style_raises(self):
        with pytest.raises(ValueError, match="visual_style must be one of"):
            Waveguide(visual_style="cartoon")


class TestRegistryPhysicsContract:
    def test_lens_physics_modes(self):
        spec = component_registry()["Lens"]
        assert spec.physics_modes == ("diagram", "ray", "paraxial")
        assert spec.visual_only is False
        assert spec.schematic_default is False

    def test_waveguide_physics_modes(self):
        spec = component_registry()["Waveguide"]
        assert spec.physics_modes == ("diagram",)
        assert spec.visual_only is False
        assert spec.schematic_default is True
        assert spec.supports_render_physical is True
        assert spec.supports_physical_spec is True

    def test_microring_schematic_metadata(self):
        info = describe_physics_support("MicroringResonator")
        assert info["schematic_default"] is True
        assert info["supports_render_physical"] is True
        assert info["supports_physical_spec"] is True

    def test_prism_lacks_paraxial_mode(self):
        spec = component_registry()["Prism"]
        assert "ray" in spec.physics_modes
        assert "paraxial" not in spec.physics_modes

    def test_describe_physics_support(self):
        info = describe_physics_support("MicroringResonator")
        assert info["physics_modes"] == ["diagram", "modulation"]
        assert info["supports_paraxial"] is False


class TestSchemaUnitsContract:
    def test_default_scene_units(self):
        scene = Scene()
        assert scene.units == UNITS

    def test_scene_from_spec_preserves_units(self):
        scene = scene_from_spec({"components": [], "units": dict(UNITS)})
        assert scene.units == UNITS

    def test_validate_units_rejects_invalid_length(self):
        with pytest.raises(ValueError, match="Invalid units\\['length'\\]"):
            validate_units({"length": "mm", "angle": "deg", "wavelength": "nm"})

    def test_scene_from_spec_rejects_invalid_units(self):
        with pytest.raises(ValueError, match="Invalid units"):
            scene_from_spec(
                {
                    "components": [],
                    "units": {"length": "mm", "angle": "deg", "wavelength": "nm"},
                }
            )


class TestCatalogUnitsHint:
    def test_describe_component_includes_units_and_physics(self):
        info = describe_component("Lens")
        assert info["units"] == UNITS
        assert "paraxial" in info["physics_modes"]


class TestPhysicsWarnings:
    def test_paraxial_trace_warns_on_visual_only_component(self):
        scene = Scene()
        grid = Grid(pitch=10, width=100, height=100)

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            scene.trace_paraxial_beam((0, 0), 0.0, [grid], exit_length=5.0)

        assert any("visual-only" in str(item.message) for item in caught)

    def test_paraxial_trace_warns_when_paraxial_not_declared(self):
        scene = Scene()
        prism = Prism(center=(10, 0))

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            scene.trace_paraxial_beam((0, 0), 0.0, [prism], exit_length=5.0)

        assert any("does not declare paraxial physics support" in str(item.message) for item in caught)
