"""Tests for optodraw core."""


import pytest

from optodraw.core.transform import Vec3, Transform
from optodraw.core.component import Group
from optodraw.core.scene import Scene
from optodraw.core.beam import Beam, wavelength_to_hex
from optodraw.components.optics import Lens, Mirror
from optodraw.components.devices import Laser
from optodraw.components.samples import Sample
from optodraw.components.misc import Grid


# ---------- Vec3 ----------

class TestVec3:
    def test_add(self):
        a = Vec3(1, 2, 3)
        b = Vec3(4, 5, 6)
        c = a + b
        assert c.x == 5 and c.y == 7 and c.z == 9

    def test_length(self):
        v = Vec3(3, 4, 0)
        assert abs(v.length() - 5.0) < 1e-10

    def test_normalized(self):
        v = Vec3(0, 0, 10)
        n = v.normalized()
        assert abs(n.z - 1.0) < 1e-10
        assert abs(n.length() - 1.0) < 1e-10

    def test_dot(self):
        a = Vec3(1, 0, 0)
        b = Vec3(0, 1, 0)
        assert abs(a.dot(b)) < 1e-10

    def test_cross(self):
        a = Vec3(1, 0, 0)
        b = Vec3(0, 1, 0)
        c = a.cross(b)
        assert abs(c.z - 1.0) < 1e-10


# ---------- Transform ----------

class TestTransform:
    def test_from_2d(self):
        t = Transform.from_2d(10, 20, 45)
        assert t.position.x == 10
        assert t.position.y == 20
        assert t.angle == 45

    def test_identity_matrix(self):
        t = Transform()
        m = t.to_matrix_4x4()
        assert abs(m[0, 0] - 1.0) < 1e-10
        assert abs(m[3, 3] - 1.0) < 1e-10

    def test_compose_translation(self):
        parent = Transform.from_2d(10, 0, 0)
        child = Transform.from_2d(5, 0, 0)
        world = parent.compose(child)
        assert abs(world.position.x - 15.0) < 1e-10

    def test_compose_rotation(self):
        parent = Transform.from_2d(0, 0, 90)
        child = Transform.from_2d(10, 0, 0)
        world = parent.compose(child)
        # After 90-degree rotation, x=10 becomes y=10
        assert abs(world.position.y - 10.0) < 1e-6
        assert abs(world.position.x) < 1e-6


# ---------- Scene graph ----------

class TestSceneGraph:
    def test_add_component(self):
        s = Scene()
        l = s.add(Laser(center=(0, 0)))
        assert sum(1 for _ in s.walk()) == 1

    def test_nested_groups(self):
        s = Scene()
        g = s.group(label="periscope")
        g.add(Mirror(center=(0, 0), angle=45))
        g.add(Mirror(center=(0, 20), angle=-45))
        assert sum(1 for _ in s.walk()) == 3  # group + 2 mirrors

    def test_world_position(self):
        s = Scene()
        g = Group(label="offset")
        g.transform = Transform.from_2d(10, 0, 0)
        s.add(g)
        m = Mirror(center=(5, 0))
        g.add(m)
        wp = m.world_position
        assert abs(wp.x - 15.0) < 1e-6

    def test_serialization(self):
        from optodraw.schema import SCHEMA_VERSION

        s = Scene(title="Test")
        s.add(Lens(center=(0, 0), label="L1"))
        d = s.to_dict()
        assert d["title"] == "Test"
        assert d["schema_version"] == SCHEMA_VERSION
        assert isinstance(d["components"], list)
        assert d["components"][0]["type"] == "Lens"


# ---------- Beam ----------

class TestBeam:
    def test_beam_points(self):
        s = Scene()
        las = s.add(Laser(center=(0, 0)))
        mir = s.add(Mirror(center=(30, 0), angle=45))
        b = Beam(las, mir)
        s.add(b)
        pts = b.resolve_points()
        assert len(pts) == 2
        assert abs(pts[0][0]) < 1e-6
        assert abs(pts[1][0] - 30.0) < 1e-6

    def test_wavelength_color(self):
        c = wavelength_to_hex(532)  # green
        assert c.startswith("#")
        assert len(c) == 7


# ---------- Components ----------

class TestComponents:
    def test_lens_geometry(self):
        l = Lens(center=(0, 0), radius=3, aperture=12)
        g2d = l.geometry_2d()
        assert g2d["type"] == "group"
        assert any(child["type"] == "path" for child in g2d["children"])

        g3d = l.geometry_3d()
        assert g3d["shape"] == "group"

    def test_mirror_geometry(self):
        m = Mirror(center=(0, 0))
        g3d = m.geometry_3d()
        assert g3d["shape"] == "group"

    def test_sample_cryostat(self):
        s = Sample(in_cryostat=True)
        g3d = s.geometry_3d()
        assert "children" in g3d

    def test_laser_color(self):
        l = Laser(wavelength=532)
        assert l.color.startswith("#")

    def test_grid_defaults(self):
        g = Grid()
        assert g.pitch == 10.0


# ---------- Renderers (smoke tests) ----------

class TestSvgRenderer:
    def test_render_returns_drawing(self):
        s = Scene(width=100, height=50)
        s.add(Grid())
        s.add(Laser(center=(-30, 0)))
        s.add(Mirror(center=(0, 0), angle=45))
        svg = s.render_svg()
        assert svg is not None

class TestThreeJsRenderer:
    def test_render_returns_html(self):
        s = Scene(width=100, height=50)
        s.add(Laser(center=(-30, 0), label="HeNe"))
        s.add(Mirror(center=(0, 0), angle=45))
        html = s.render_threejs()
        assert "<!DOCTYPE html>" in html
        assert "three" in html.lower()
        assert "HeNe" in html

@pytest.mark.parametrize("angle", [90, 180, 270, 45])
def test_labels_read_upright_at_any_angle(angle):
    """The counter-rotation has to CANCEL the group's rotation, not mirror it:
    with the y-flip the group applies rotate(-angle), so the label needs +angle.
    Getting the sign wrong still looks right at 180 deg and is upside down at 90."""

    import re

    from optodraw import Scene
    from optodraw.components.optics import Lens

    scene = Scene(width=80, height=60)
    scene.add(Lens(center=(0, 0), angle=angle, label="L1"))
    svg = scene.render_svg().as_svg()
    group = svg[: svg.index("L1")]
    turns = re.findall(r'transform="[^"]*rotate\((-?[\d.]+)\)', group)   # the renderer's groups, not a gradient
    outer, inner = float(turns[-2]), float(turns[-1])
    assert (outer + inner) % 360 == 0  # net rotation on the glyphs is nil


def test_labels_stay_upright_on_rotated_components():
    """A label rotates with its component, so anything placed at 180 deg reads
    upside down. Component art must rotate; its NAME must stay readable."""

    from optodraw import Scene
    from optodraw.components.optics import Lens

    scene = Scene(width=80, height=60)
    scene.add(Lens(center=(0, 0), angle=180, label="L1"))
    svg = scene.render_svg().as_svg()
    text_index = svg.index("L1")
    group = svg[:text_index]
    # the text carries its own counter-rotation right before it is drawn
    assert "rotate(180" in group[-260:]

def test_labels_clear_tall_components():
    """A fixed -8 offset drops the label inside anything taller than ~16 units:
    the microring's name landed on its own drop waveguide."""

    import re

    from optodraw import MicroringResonator, Scene
    from optodraw.components.optics import Lens

    ring = MicroringResonator(center=(0, 0), add_drop=True, label="Ring")
    scene = Scene(width=120, height=90, platform="on_chip")
    scene.add(ring)
    y = float(re.search(r'<text x="0" y="(-?[\d.]+)"[^>]*>Ring', scene.render_svg().as_svg()).group(1))
    assert y < -14.0  # above the ring, not across it

    small = Scene(width=60, height=40)
    small.add(Lens(center=(0, 0), label="L1"))
    y_small = float(re.search(r'<text x="0" y="(-?[\d.]+)"[^>]*>L1', small.render_svg().as_svg()).group(1))
    assert -9.0 < y_small <= -8.0  # small parts keep a tight offset (just clear of their drawing)


def test_a_beam_does_not_draw_across_the_parts_it_passes_through():
    """A beam threaded through in/out ports contains spans that live INSIDE a
    component. Drawing them puts a line straight across the part's art; the
    light between parts is what a setup figure is meant to show."""

    from optodraw.components.optics import Polarizer

    scene = Scene(width=160, height=80)
    laser = scene.add(Laser(center=(-60, 0), label="L"))
    polarizer = scene.add(Polarizer(center=(0, 0), label="P"))
    camera = scene.add(Lens(center=(60, 0), label="Lens"))
    beam = scene.add(Beam((laser, "out"), (polarizer, "in"), (polarizer, "out"), (camera, "in")))

    segments = beam.segments()
    assert len(segments) == 2  # laser -> polarizer, then polarizer -> lens
    assert all(len(seg) == 2 for seg in segments)
    # the gap between them IS the polarizer, so nothing is drawn over its body
    assert segments[0][-1][0] < segments[1][0][0]

    svg = scene.render_svg().as_svg()
    assert svg.count('fill="none"') >= 2  # drawn as two strokes, not one line through


def test_a_plain_two_point_beam_is_still_one_segment():
    scene = Scene(width=120, height=60)
    laser = scene.add(Laser(center=(-40, 0)))
    lens = scene.add(Lens(center=(40, 0)))
    beam = scene.add(Beam((laser, "out"), (lens, "in")))
    assert len(beam.segments()) == 1


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

    def test_optimize_layout_leaves_routes_alone(self):
        scene, route = self._chip_with_a_link()
        before = (route.transform.position.x, route.transform.position.y)
        scene.optimize_layout()
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
