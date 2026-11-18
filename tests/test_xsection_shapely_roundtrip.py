"""Geometry validity after each process step."""

from __future__ import annotations

from pathlib import Path

import pytest

from optodraw.gds.xsection import CrossSectionStripLayout, XSectionEngine


pytest.importorskip("yaml")
pytest.importorskip("shapely")


FIXTURE = Path(__file__).parent / "fixtures" / "xsection" / "generic_siph_minimal.yaml"


def test_all_internal_regions_valid_after_each_step():
    engine = XSectionEngine.from_yaml(FIXTURE)
    cut = (
        CrossSectionStripLayout()
        .strip("RIB", width_um=0.5, center_y_um=0.0)
        .strip("SLAB", width_um=2.0, center_y_um=0.0)
        .strip("MT1", width_um=0.6, center_y_um=0.0)
        .to_layout_cut()
    )
    stack = engine.run(cut, debug=True)
    for step_id, regions in stack.debug_steps.items():
        for name, geometry in regions.items():
            assert geometry.is_valid, f"{step_id}:{name} invalid"
            assert geometry.is_empty or geometry.area >= 0.0

    for layer in stack.layers:
        assert layer.geometry.is_valid
        if not layer.geometry.is_empty:
            assert layer.geometry.area > 0.0
