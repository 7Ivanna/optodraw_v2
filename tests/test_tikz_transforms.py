"""TikZ renderer keeps rotation and curved bodies.

Mirrors at different angles must produce different TikZ, and lens bodies
drawn as SVG paths must survive as TikZ paths instead of vanishing.
"""

from __future__ import annotations

import pytest

from optodraw import Scene


class TestTikzPaths:


    def test_an_arc_becomes_a_curve_on_its_circle(self):
        """An SVG arc is written as a cubic Bezier, and the Bezier stays on the circle.

        TikZ's own ``arc`` needs start and end angles, which rotated and
        elliptical arcs make fragile. A cubic through the same end points is
        exact enough: its midpoint is 0.03 percent off a radius 10 circle.
        """
        import math
        import re

        from optodraw.renderers.tikz_renderer import TikzRenderer

        out = TikzRenderer(Scene(width=40, height=40))._render_path(
            {"type": "path", "d": "M 10 0 A 10 10 0 0 1 0 10", "stroke": "#000000", "stroke_width": 0.5, "fill": "none"})
        points = [(float(x), float(y)) for x, y in re.findall(r"\((-?[\d.]+),(-?[\d.]+)\)", out)]
        assert len(points) == 4, out                       # start, two controls, end
        start, c1, c2, end = points
        assert math.hypot(*start) == pytest.approx(10.0) and math.hypot(*end) == pytest.approx(10.0)
        mid = tuple((start[i] + 3 * c1[i] + 3 * c2[i] + end[i]) / 8.0 for i in (0, 1))
        assert math.hypot(*mid) == pytest.approx(10.0, rel=1e-3)
