"""Tests for on-chip chip_builder layout helpers."""

from __future__ import annotations

import pytest

from optodraw.layout.chip_builder import build_microring_weight_mesh, build_mzm_mesh


class TestBuildMzmMesh:


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

