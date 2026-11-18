"""Tests for Tier 2 visual scale, symbolic style, and optics metadata."""

from __future__ import annotations


from optodraw import Waveguide


class TestSymbolicVisualStyle:
    def test_waveguide_symbolic_geometry_is_line_group(self):
        symbolic = Waveguide(length=20.0, visual_style="symbolic")
        publication = Waveguide(length=20.0, visual_style="publication")

        symbolic_geo = symbolic.geometry_2d()
        publication_geo = publication.geometry_2d()

        assert symbolic_geo["type"] == "group"
        assert symbolic_geo["children"][0]["type"] == "line"
        assert publication_geo["type"] == "rect"


