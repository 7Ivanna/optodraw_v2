"""TikZ renderer keeps rotation and curved bodies.

Mirrors at different angles must produce different TikZ, and lens bodies
drawn as SVG paths must survive as TikZ paths instead of vanishing.
"""

from __future__ import annotations

import pytest

from optodraw import Scene
from optodraw.components.optics import Lens, Mirror


def _tikz(*components) -> str:
    scene = Scene(width=160, height=80)
    for index, component in enumerate(components):
        scene.add(component)
    return scene.render_tikz()


class TestTikzRotation:
    def test_mirrors_at_different_angles_differ(self):
        flat = _tikz(Mirror(center=(0, 0), angle=0))
        turned = _tikz(Mirror(center=(0, 0), angle=45))
        assert flat != turned

    def test_rotated_mirror_uses_scope(self):
        out = _tikz(Mirror(center=(10, 0), angle=45))
        assert "\\begin{scope}[shift={(10.000,0.000)},rotate=45.000]" in out
        assert "\\end{scope}" in out

    def test_unrotated_mirror_has_no_scope(self):
        out = _tikz(Mirror(center=(0, 0), angle=0))
        assert "rotate" not in out.split("\\begin{tikzpicture}", 1)[1]    # no turn for an unturned mirror


class TestTikzPaths:
    def test_lens_body_survives_as_path(self):
        out = _tikz(Lens(center=(0, 0)))
        assert "\\path[" in out
        assert "controls" in out

    def test_arc_renders(self):
        """The stage's graduation arc is drawn, as a curve, and nothing is dropped."""
        from optodraw import Scene
        from optodraw.components.optics.optomech import RotationStage
        from optodraw.renderers.tikz_renderer import TikzRenderer

        scene = Scene(width=120, height=80)
        scene.add(RotationStage())
        renderer = TikzRenderer(scene)
        out = renderer.render()
        assert ".. controls" in out
        assert renderer.report.to_dict()["skipped"] == []

    def test_an_arc_becomes_a_curve_on_its_circle(self):
        """An SVG arc is written as a cubic Bezier, and the Bezier stays on the circle.

        TikZ's own ``arc`` needs start and end angles, which rotated and
        elliptical arcs make fragile. A cubic through the same end points is
        exact enough: its midpoint is 0.03 percent off a radius 10 circle.
        """
        import math
        import re

        from optodraw import Scene
        from optodraw.renderers.tikz_renderer import TikzRenderer

        out = TikzRenderer(Scene(width=40, height=40))._render_path(
            {"type": "path", "d": "M 10 0 A 10 10 0 0 1 0 10", "stroke": "#000000", "stroke_width": 0.5, "fill": "none"})
        points = [(float(x), float(y)) for x, y in re.findall(r"\((-?[\d.]+),(-?[\d.]+)\)", out)]
        assert len(points) == 4, out                       # start, two controls, end
        start, c1, c2, end = points
        assert math.hypot(*start) == pytest.approx(10.0) and math.hypot(*end) == pytest.approx(10.0)
        mid = tuple((start[i] + 3 * c1[i] + 3 * c2[i] + end[i]) / 8.0 for i in (0, 1))
        assert math.hypot(*mid) == pytest.approx(10.0, rel=1e-3)
