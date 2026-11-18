"""Tests for on-chip chip_builder layout helpers."""

from __future__ import annotations

import pytest

from optodraw.layout.chip_builder import build_microring_weight_mesh, build_mzm_mesh, build_ring_filter


class TestBuildRingFilter:
    def test_build_ring_filter_returns_routed_scene(self):
        built = build_ring_filter()
        assert built["scene"].platform == "on_chip"
        assert len(built["routes"]) == 4
        assert built["grating_coupler"].label == "GC"
        assert built["ring"].ring_radius > 0

    def test_physical_spacing_separates_components(self):
        built = build_ring_filter(spacing_um=20.0)
        gc_x = built["grating_coupler"].transform.position.x
        ring_x = built["ring"].transform.position.x
        assert ring_x > gc_x + 10.0


class TestBuildMzmMesh:
    def test_build_mzm_mesh_grid(self):
        built = build_mzm_mesh(rows=2, cols=2)
        assert len(built["mzms"]) == 4
        assert built["rows"] == 2
        assert built["cols"] == 2
        assert len(built["grid"]) == 2
        assert len(built["grid"][0]) == 2

    def test_mesh_links_adjacent_columns(self):
        built = build_mzm_mesh(rows=1, cols=3, topology="row", link_length_um=18.0)
        assert len(built["routes"]) == 2
        assert [link["direction"] for link in built["links"]] == ["east", "east"]

    def test_rectangular_mesh_links_rows_and_columns(self):
        built = build_mzm_mesh(rows=2, cols=3, topology="rectangular")
        assert len(built["links"]) == 7
        assert sum(1 for link in built["links"] if link["direction"] == "east") == 4
        assert sum(1 for link in built["links"] if link["direction"] == "south") == 3
        assert {link["source_port"] for link in built["links"] if link["direction"] == "south"} == {"o4"}
        assert {link["target_port"] for link in built["links"] if link["direction"] == "south"} == {"o2"}

    def test_serpentine_mesh_creates_single_path_through_cells(self):
        built = build_mzm_mesh(rows=2, cols=3, topology="serpentine")
        assert len(built["links"]) == 5
        assert built["links"][2]["source"] == (0, 2)
        assert built["links"][2]["target"] == (1, 2)
        assert built["links"][3]["direction"] == "west"

    def test_mesh_edge_io_adds_row_inputs_outputs(self):
        built = build_mzm_mesh(rows=2, cols=2, include_io=True)
        assert len(built["inputs"]) == 2
        assert len(built["outputs"]) == 2
        assert len(built["io_routes"]) == 4
        assert len(built["routes"]) == len(built["links"]) + len(built["io_routes"])

    def test_mesh_cell_kwargs_customize_individual_mzms(self):
        built = build_mzm_mesh(
            rows=1,
            cols=2,
            cell_kwargs=lambda row, col: {"drive_style": "gsg", "label": "push-pull"} if col else {},
        )
        assert built["grid"][0][0].drive_style == "gs"
        assert built["grid"][0][1].drive_style == "gsg"
        assert built["grid"][0][1].label == "push-pull"

    def test_invalid_mesh_topology_raises(self):
        with pytest.raises(ValueError):
            build_mzm_mesh(topology="bad topology")


class TestBuildMicroringWeightMesh:
    def test_build_microring_weight_mesh_grid(self):
        built = build_microring_weight_mesh(rows=2, cols=2, ring_count=3)
        assert len(built["banks"]) == 4
        assert built["rows"] == 2
        assert built["cols"] == 2
        assert built["grid"][0][0].ring_count == 3

    def test_ring_weight_mesh_rectangular_links(self):
        built = build_microring_weight_mesh(rows=2, cols=2, topology="rectangular")
        assert len(built["links"]) == 4
        assert sum(1 for link in built["links"] if link["direction"] == "east") == 2
        assert sum(1 for link in built["links"] if link["direction"] == "south") == 2
        assert {link["source_port"] for link in built["links"] if link["direction"] == "south"} == {"d1"}
