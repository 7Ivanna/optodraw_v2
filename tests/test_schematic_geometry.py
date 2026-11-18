"""Tests for schematic vs physical geometry resolution."""

from __future__ import annotations

import pytest

from optodraw.core.schematic_geometry import PhysicalSpec, resolve_schematic_dims, schematic_material_preset
from optodraw.components.onchip.schematic_tables import SCHEMATIC_TABLES


class TestSchematicResolver:
    def test_resolve_waveguide_table_defaults(self):
        physical = PhysicalSpec("waveguide", {"length": 1000.0, "width": 0.5})
        dims = resolve_schematic_dims("waveguide", physical)
        assert dims["length"] == pytest.approx(24.0)
        assert dims["width"] == pytest.approx(1.2)
        assert dims.thickness == pytest.approx(0.55)

    def test_visual_scale_multiplies_schematic_table(self):
        physical = PhysicalSpec("waveguide", {"length": 20.0, "width": 0.5})
        dims = resolve_schematic_dims("waveguide", physical, visual_scale=2.0)
        assert dims["length"] == pytest.approx(48.0)
        assert dims["width"] == pytest.approx(2.4)

    def test_shared_keys_merged(self):
        physical = PhysicalSpec("mmi", {"body_length": 5.5})
        dims = resolve_schematic_dims("mmi", physical)
        # mmi now defines its own waveguide_width, so check a key only in _SHARED.
        assert dims["oxide_clad_height"] == pytest.approx(0.35)

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
