"""Tests for GDS polygon slice → layout cut → engine."""

from __future__ import annotations

from pathlib import Path

import pytest

from optodraw.gds.layout import GDSLayout, GDSLayerRecord, GDSSection
from optodraw.gds.xsection import XSectionEngine, export_xsection_bundle
from optodraw.gds.xsection.masks import LayoutCut


pytest.importorskip("yaml")
pytest.importorskip("shapely")


FIXTURE = Path(__file__).parent / "fixtures" / "xsection" / "generic_siph_minimal.yaml"


def _synthetic_layout() -> GDSLayout:
    return GDSLayout(
        source_path=Path("synthetic.gds"),
        cell_name="TEST",
        bounds=(0.0, -2.0, 10.0, 2.0),
        layer_records=[
            GDSLayerRecord(
                spec=(10, 0),
                name="RIB",
                description="rib",
                color="#004080",
                opacity=1.0,
                thickness=0.22,
                zmin=0.0,
                material_preset="silicon",
                polygons=[[(0.0, -0.25), (10.0, -0.25), (10.0, 0.25), (0.0, 0.25)]],
                matched_pdk=False,
            ),
            GDSLayerRecord(
                spec=(12, 0),
                name="SLAB",
                description="slab",
                color="#004080",
                opacity=1.0,
                thickness=0.22,
                zmin=0.0,
                material_preset="silicon",
                polygons=[[(0.0, -1.0), (10.0, -1.0), (10.0, 1.0), (0.0, 1.0)]],
                matched_pdk=False,
            ),
        ],
    )


def test_layout_cut_from_gds_maps_intervals_and_runs_engine(tmp_path):
    layout = _synthetic_layout()
    process = XSectionEngine.from_yaml(FIXTURE).process
    cut = LayoutCut.from_gds(
        layout,
        GDSSection(label="A-A'", x=5.0, window=4.0),
        process=process,
    )
    assert "RIB" in cut.layer_intervals
    assert "SLAB" in cut.layer_intervals
    rib = cut.layer_intervals["RIB"].intervals[0]
    assert rib.y0 <= -0.25 + 1e-6
    assert rib.y1 >= 0.25 - 1e-6

    bundle = export_xsection_bundle(XSectionEngine(process), cut, tmp_path)
    assert bundle.composite_path.exists()
    assert bundle.output_stack is not None
    assert any(layer.name == "Silicon" for layer in bundle.output_stack.layers)


def _diagonal_layout() -> GDSLayout:
    return GDSLayout(
        source_path=Path("diagonal.gds"),
        cell_name="TEST",
        bounds=(0.0, -2.0, 10.0, 2.0),
        layer_records=[
            GDSLayerRecord(
                spec=(10, 0),
                name="RIB",
                description="rib",
                color="#004080",
                opacity=1.0,
                thickness=0.22,
                zmin=0.0,
                material_preset="silicon",
                polygons=[[(4.0, -1.0), (6.0, -1.0), (6.0, 1.0), (4.0, 1.0)]],
                matched_pdk=False,
            ),
        ],
    )


def test_section_mode_matches_projection_on_aligned_shapes():
    layout = _diagonal_layout()
    process = XSectionEngine.from_yaml(FIXTURE).process
    projected = LayoutCut.from_gds(
        layout, GDSSection(label="A", x=5.0, window=4.0), process=process
    )
    exact = LayoutCut.from_gds(
        layout, GDSSection(label="A", x=5.0, window=4.0, mode="section"), process=process
    )
    rib_proj = projected.layer_intervals["RIB"].intervals[0]
    rib_exact = exact.layer_intervals["RIB"].intervals[0]
    assert rib_proj.y0 == rib_exact.y0 == -1.0
    assert rib_proj.y1 == rib_exact.y1 == 1.0


def test_section_mode_is_narrower_than_projection_off_center():
    layout = _diagonal_layout()
    process = XSectionEngine.from_yaml(FIXTURE).process
    slanted = GDSLayout(
        source_path=Path("slanted.gds"),
        cell_name="TEST",
        bounds=(0.0, -2.0, 10.0, 2.0),
        layer_records=[
            GDSLayerRecord(
                spec=(10, 0),
                name="RIB",
                description="rib",
                color="#004080",
                opacity=1.0,
                thickness=0.22,
                zmin=0.0,
                material_preset="silicon",
                polygons=[[(2.0, -1.0), (4.0, -1.0), (6.0, 1.0), (4.0, 1.0)]],
                matched_pdk=False,
            ),
        ],
    )
    projected = LayoutCut.from_gds(
        slanted, GDSSection(label="A", x=5.0, window=2.0), process=process
    )
    exact = LayoutCut.from_gds(
        slanted, GDSSection(label="A", x=5.0, window=2.0, mode="section"), process=process
    )
    proj_width = projected.layer_intervals["RIB"].intervals[0].y1 - projected.layer_intervals["RIB"].intervals[0].y0
    exact_width = exact.layer_intervals["RIB"].intervals[0].y1 - exact.layer_intervals["RIB"].intervals[0].y0
    assert exact_width < proj_width


def test_unknown_section_mode_rejected():
    import pytest as _pytest

    with _pytest.raises(ValueError, match="mode must be"):
        GDSSection(label="A", x=0.0, window=1.0, mode="diagonal")

    cut = LayoutCut.from_gds(
        _diagonal_layout(),
        {"label": "A", "x": 5.0, "window": 4.0, "mode": "section"},
        process=None,
    )
    assert cut.layer_intervals["RIB"].intervals[0].y0 == -1.0
