"""Tests for optodraw core."""


import pytest

from optodraw.core.transform import Vec3
from optodraw.core.scene import Scene
from optodraw.components.optics import Mirror
from optodraw.components.devices import Laser
from optodraw.components.samples import Sample
from optodraw.components.misc import Grid


# ---------- Vec3 ----------

class TestVec3:


    def test_cross(self):
        a = Vec3(1, 0, 0)
        b = Vec3(0, 1, 0)
        c = a.cross(b)
        assert abs(c.z - 1.0) < 1e-10


# ---------- Transform ----------


# ---------- Scene graph ----------


# ---------- Beam ----------


# ---------- Components ----------

class TestComponents:


    def test_sample_cryostat(self):
        s = Sample(in_cryostat=True)
        g3d = s.geometry_3d()
        assert "children" in g3d


# ---------- Renderers (smoke tests) ----------

class TestSvgRenderer:
    def test_render_returns_drawing(self):
        s = Scene(width=100, height=50)
        s.add(Grid())
        s.add(Laser(center=(-30, 0)))
        s.add(Mirror(center=(0, 0), angle=45))
        svg = s.render_svg()
        assert svg is not None


class TestSceneLayoutSkipsLinks:
    """Arranging a scene lays out its parts, not the links between them.

    Scene carried four copies of the skip list, and every copy named "Route"
    without the three subclasses the router actually builds — so a waveguide,
    fibre or metal link counted as a part: it took a slot in the line, spaced
    the real components wrongly, and had its transform moved out from under it.
    """

    def _chip_with_a_link(self):
        from optodraw import Scene
        from optodraw.components.onchip import OnChipPhotodetector, VerticalGratingCoupler

        scene = Scene(width=200, height=120, platform="on_chip")
        gc = scene.add(VerticalGratingCoupler(center=(-60, 0), label="GC"))
        pd = scene.add(OnChipPhotodetector(center=(40, 0), label="PD"))
        route = scene.route((gc, "o1"), (pd, "o1"), kind="waveguide")
        return scene, route

    def test_arrange_line_leaves_routes_alone(self):
        scene, route = self._chip_with_a_link()
        before = (route.transform.position.x, route.transform.position.y)
        arranged = scene.arrange_line()
        assert [type(n).__name__ for n in arranged] == ["VerticalGratingCoupler", "OnChipPhotodetector"]
        assert (route.transform.position.x, route.transform.position.y) == before

    def test_arrange_grid_leaves_routes_alone(self):
        scene, route = self._chip_with_a_link()
        before = (route.transform.position.x, route.transform.position.y)
        scene.arrange_grid()
        assert (route.transform.position.x, route.transform.position.y) == before


class TestEveryRendererDrawsTheSameBeam:
    """SVG and TikZ used to work out the focusing-beam trapezoid separately.

    Same four corners, two chances to disagree about them — so the shape now
    belongs to the beam, and this test holds the renderers to it.
    """

    def _scene(self):
        from optodraw import Scene
        from optodraw.core.beam import FocusingBeam

        scene = Scene(width=120, height=80)
        scene.add(FocusingBeam((-30, 0), (30, 6), width1=8.0, width2=1.0, wavelength=532))
        return scene

    def test_svg_and_tikz_place_the_same_corners(self):
        import re

        scene = self._scene()
        beam = next(n for n in scene.walk() if n.component_type == "FocusingBeam")
        expected = beam.corners()

        flat = [value for corner in expected for value in corner]

        path = re.search(r'<path d="([^"]+)"', scene.render_svg().as_svg()).group(1)
        svg = [(float(x), -float(y)) for x, y in re.findall(r"[ML]([-\d.]+),([-\d.]+)", path)]
        assert [v for corner in svg for v in corner] == pytest.approx(flat, abs=1e-6)

        line = next(ln for ln in scene.render_tikz().splitlines() if "fill opacity=" in ln)
        tikz = [(float(x), float(y)) for x, y in re.findall(r"\(([-\d.]+),([-\d.]+)\)", line)]
        assert [v for corner in tikz for v in corner] == pytest.approx(flat, abs=1e-3)

    def test_a_beam_with_nowhere_to_go_draws_nothing(self):
        from optodraw.core.beam import FocusingBeam

        assert FocusingBeam((5, 5), (5, 5), width1=4.0).corners() == []
