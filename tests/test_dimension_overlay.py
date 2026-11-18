"""Tests for 2D dimension marker overlay."""

from __future__ import annotations


from optodraw import Scene, Waveguide
from optodraw.renderers.dimension_overlay import (
    linear_dimension,
    markers_from_physical_spec,
)
from optodraw.renderers.svg_renderer import SvgRenderer


class TestDimensionOverlay:

    def test_markers_from_physical_spec(self):
        markers = markers_from_physical_spec(0, 0, length_um=20.0, width_um=0.5)
        assert len(markers) == 2
        assert "20" in markers[0].label

    def test_svg_renderer_appends_overlay_when_enabled(self):
        scene = Scene(title="Dims", platform="on_chip", width=120, height=80)
        scene.add(Waveguide(length=20.0))
        marker = linear_dimension(-10, -5, 10, -5, "20 µm")
        drawing = SvgRenderer(scene, show_dimension_overlay=True, dimension_markers=[marker]).render()
        svg = drawing.as_svg()
        assert "20 µm" in svg

