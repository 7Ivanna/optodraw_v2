"""Tests for Tier 2 product contract foundation."""

from __future__ import annotations

import warnings

import pytest

from optodraw import Scene, Waveguide
from optodraw.components.misc import Grid
from optodraw.components.optics import Prism
from optodraw.schema import UNITS, scene_from_spec


class TestChipComponentVisualContract:

    def test_invalid_visual_style_raises(self):
        with pytest.raises(ValueError, match="visual_style must be one of"):
            Waveguide(visual_style="cartoon")


class TestSchemaUnitsContract:
    def test_default_scene_units(self):
        scene = Scene()
        assert scene.units == UNITS


    def test_scene_from_spec_rejects_invalid_units(self):
        with pytest.raises(ValueError, match="Invalid units"):
            scene_from_spec(
                {
                    "components": [],
                    "units": {"length": "mm", "angle": "deg", "wavelength": "nm"},
                }
            )


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
