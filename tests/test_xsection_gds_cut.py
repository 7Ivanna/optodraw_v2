"""Tests for GDS polygon slice → layout cut → engine."""

from __future__ import annotations

from pathlib import Path

import pytest

from optodraw.gds.layout import GDSLayout, GDSLayerRecord, GDSSection
from optodraw.gds.xsection import XSectionEngine
from optodraw.gds.xsection.masks import LayoutCut


pytest.importorskip("yaml")
pytest.importorskip("shapely")


FIXTURE = Path(__file__).parent / "fixtures" / "xsection" / "generic_siph_minimal.yaml"


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
