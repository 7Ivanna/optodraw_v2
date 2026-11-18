"""Renderer capability tables and strict mode.

Every renderer used to drop unsupported content silently. Each table maps a
geometry type to full/approximate/skip, ``strict=True`` raises instead of
dropping, and default output stays byte-identical.
"""

from __future__ import annotations

import pytest

from optodraw import Scene
from optodraw.components.devices import Laser
from optodraw.components.optics import Lens
from optodraw.renderers.capabilities import (
    APPROXIMATE,
    FULL,
    SKIP,
    TABLES,
    UnsupportedGeometryError,
    verdict,
)
from optodraw.renderers.svg_renderer import SvgRenderer
from optodraw.renderers.tikz_renderer import TikzRenderer


def _scene() -> Scene:
    scene = Scene(width=120, height=80)
    scene.add(Laser(center=(-30, 0), label="Pump"))
    scene.add(Lens(center=(10, 0)))
    return scene


class TestTables:
    def test_known_renderers_have_tables(self):
        assert set(TABLES) == {"svg", "tikz", "glb", "threejs"}

    def test_unknown_renderer_or_type_skips(self):
        assert verdict("svg", "teleport") == SKIP
        assert verdict("nope", "rect") == SKIP
        assert verdict("svg", None) == SKIP

    def test_svg_covers_all_dispatched_types(self):
        for gtype in ("group", "text", "rect", "line", "circle", "path", "ellipse", "polygon", "polyline"):
            assert verdict("svg", gtype) == FULL

    def test_tikz_path_is_approximate(self):
        assert verdict("tikz", "path") == APPROXIMATE
        assert verdict("tikz", "rect") == FULL


class TestSvgStrict:
    def test_default_output_unchanged_and_report_empty(self):
        renderer = SvgRenderer(_scene())
        before = renderer.render().as_svg()
        assert renderer.report.to_dict()["skipped"] == []
        assert renderer.report.to_dict()["approximated"] == []

    def test_unknown_type_records_skip(self):
        renderer = SvgRenderer(_scene())
        renderer._draw_geometry.__self__  # bound method sanity
        import drawsvg as draw

        parent = draw.Drawing(10, 10)
        renderer._draw_geometry(parent, {"type": "teleport", "x": 0})
        assert any("teleport" in entry for entry in renderer.report.skipped)

    def test_strict_raises_on_unknown_type(self):
        import drawsvg as draw

        renderer = SvgRenderer(_scene(), strict=True)
        parent = draw.Drawing(10, 10)
        with pytest.raises(UnsupportedGeometryError, match="teleport"):
            renderer._draw_geometry(parent, {"type": "teleport", "x": 0})

    def test_strict_standard_scene_renders(self):
        renderer = SvgRenderer(_scene(), strict=True)
        assert renderer.render().as_svg().startswith("<?xml")


class TestTikzStrict:
    def test_unknown_type_records_skip(self):
        renderer = TikzRenderer(_scene())
        assert renderer._render_geometry({"type": "teleport"}) == []
        assert any("teleport" in entry for entry in renderer.report.skipped)

    def test_strict_raises_on_unknown_type(self):
        renderer = TikzRenderer(_scene(), strict=True)
        with pytest.raises(UnsupportedGeometryError, match="teleport"):
            renderer._render_geometry({"type": "teleport"})

    def test_default_output_unchanged(self):
        plain = TikzRenderer(_scene()).render()
        assert "\\begin{tikzpicture}" in plain


class TestThreejsStrict:
    def test_unknown_shape_records_approximate(self):
        from optodraw.renderers.capabilities import APPROXIMATE
        from optodraw.renderers.threejs_renderer import ThreeJsRenderer

        scene = _scene()
        renderer = ThreeJsRenderer(scene)
        renderer.report.check(
            "threejs",
            "teleport",
            strict=False,
            unknown_as=APPROXIMATE,
            detail="3D shape 'teleport' on probe",
        )
        assert any("teleport" in entry for entry in renderer.report.approximated)

    def test_strict_standard_scene_renders(self):
        from optodraw.renderers.threejs_renderer import ThreeJsRenderer

        html = ThreeJsRenderer(_scene(), strict=True).render()
        assert "<!DOCTYPE html>" in html


class TestGlbStrict:
    def test_beam_scene_reports_the_beam_as_approximated(self):
        pytest.importorskip("trimesh")
        from optodraw.core.beam import Beam
        from optodraw.exporters import scene_to_glb_with_report

        scene = _scene()
        laser = next(n for n in scene.walk() if getattr(n, "component_type", "") == "Laser")
        lens = next(n for n in scene.walk() if getattr(n, "component_type", "") == "Lens")
        scene.add(Beam(laser, lens))
        _, report = scene_to_glb_with_report(scene)
        assert any("Beam" in entry for entry in report["approximated"])
        assert not any("Beam" in entry for entry in report["skipped"])

    def test_strict_raises_on_dropped_content(self):
        pytest.importorskip("trimesh")
        from optodraw.core.beam import Beam
        from optodraw.exporters import scene_to_glb

        scene = _scene()
        laser = next(n for n in scene.walk() if getattr(n, "component_type", "") == "Laser")
        lens = next(n for n in scene.walk() if getattr(n, "component_type", "") == "Lens")
        scene.add(Beam(laser, lens))
        with pytest.raises(UnsupportedGeometryError, match="glb: (skipped|approximated)"):
            scene_to_glb(scene, strict=True)
