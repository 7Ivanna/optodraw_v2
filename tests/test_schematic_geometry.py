"""Tests for schematic vs physical geometry resolution."""

from __future__ import annotations


from optodraw.core.schematic_geometry import schematic_material_preset
from optodraw.components.onchip.schematic_tables import SCHEMATIC_TABLES


class TestSchematicResolver:


    def test_schematic_material_preset_suffix(self):
        assert schematic_material_preset("silicon", schematic=True) == "silicon_schematic"
        assert schematic_material_preset("silicon", schematic=False) == "silicon"
        assert schematic_material_preset("gold", schematic=True) == "gold"

    def test_tables_cover_onchip_families(self):
        expected = {
            "waveguide",
            "mmi",
            "grating_coupler",
            "edge_coupler",
            "microring",
            "mzi",
            "mzm",
            "photodetector",
        }
        assert expected.issubset(set(SCHEMATIC_TABLES) - {"_shared"})
