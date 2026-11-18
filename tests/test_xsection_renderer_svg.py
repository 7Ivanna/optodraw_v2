"""Tests for drawsvg cross-section renderer."""

from __future__ import annotations

from pathlib import Path

import pytest

from optodraw.gds.xsection import CrossSectionStripLayout, XSectionEngine
from optodraw.gds.xsection.renderer_svg import render_layer_svgs, render_output_stack_svg, svg_dom_summary


pytest.importorskip("yaml")


FIXTURE = Path(__file__).parent / "fixtures" / "xsection" / "generic_siph_minimal.yaml"


def test_renderer_emits_layer_groups_paths_and_hatch_defs(tmp_path):
    engine = XSectionEngine.from_yaml(FIXTURE)
    cut = (
        CrossSectionStripLayout()
        .strip("RIB", width_um=0.5, center_y_um=0.0)
        .strip("SLAB", width_um=2.0, center_y_um=0.0)
        .to_layout_cut()
    )
    stack = engine.run(cut)
    svg = render_output_stack_svg(stack, engine.process)
    summary = svg_dom_summary(svg)
    assert summary["layer_count"] >= 2
    assert summary["path_count"] >= 2
    assert "layer-Silicon" in summary["layer_ids"]

    layer_paths = render_layer_svgs(stack, engine.process, tmp_path)
    assert len(layer_paths) >= 2
    for path in layer_paths.values():
        text = path.read_text(encoding="utf-8")
        assert "<svg" in text
        assert "layer-" in text
