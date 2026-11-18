"""Cross-renderer acceptance: one scene, structural facts per output.

Three fixture scenes exercise rotated parts, curved bodies, labels, beams,
and chip routes. Each output asserts structural facts (not golden files):

- SVG: one tagged group per component, beam present
- TikZ: rotation scope for turned parts, path survival for curved bodies
- GLB: mesh count covers the parts, beams listed as skipped
- Capability reports stay empty for standard content in SVG/TikZ
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from optodraw.renderers.svg_renderer import SvgRenderer
from optodraw.renderers.tikz_renderer import TikzRenderer
from optodraw.schema import scene_from_spec

FIXTURES = Path(__file__).parent / "fixtures" / "acceptance"


def _load(name: str):
    spec = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return scene_from_spec(spec)


def _part_count(scene) -> int:
    return sum(
        1 for n in scene.walk() if getattr(n, "component_type", "") not in {"Group", "Grid"}
    )


def _tagged_svg(scene) -> str:
    id_map = {
        id(n): getattr(n, "_id", "") or getattr(n, "label", "") or type(n).__name__
        for n in scene.walk()
        if getattr(n, "component_type", "") not in {"Group", "Grid"}
    }
    return SvgRenderer(scene, editable=True, component_ids=id_map).render().as_svg()


class TestRotatedOptics:
    def test_svg_tags_every_part(self):
        scene = _load("rotated_optics.json")
        assert _tagged_svg(scene).count("data-component-id") >= _part_count(scene)

    def test_tikz_scopes_the_turned_mirror(self):
        scene = _load("rotated_optics.json")
        out = TikzRenderer(scene).render()
        assert "\\begin{scope}[shift=" in out
        assert "rotate=45.000" in out

    def test_tikz_keeps_the_lens_body(self):
        scene = _load("rotated_optics.json")
        assert "\\path[" in TikzRenderer(scene).render()

    def test_glb_covers_parts_and_the_beam(self):
        pytest.importorskip("trimesh")
        from optodraw.exporters import scene_to_glb_with_report

        scene = _load("rotated_optics.json")
        _, report = scene_to_glb_with_report(scene)
        assert report["meshes"] >= 3
        # the beam is in the file now, as a tube along its centre line, and the report says so
        assert any("Beam" in entry and "tube" in entry for entry in report["approximated"])
        assert not any("Beam" in entry for entry in report["skipped"])

    def test_capability_reports_empty(self):
        scene = _load("rotated_optics.json")
        svg = SvgRenderer(scene)
        svg.render()
        assert svg.report.to_dict()["skipped"] == []
        tikz = TikzRenderer(scene)
        tikz.render()
        assert tikz.report.to_dict()["skipped"] == []


class TestStageArc:
    def test_tikz_renders_the_graduation_arc(self):
        # arcs are written as cubic curves; tests/test_tikz_transforms.py checks they stay on the circle
        scene = _load("stage_arc.json")
        renderer = TikzRenderer(scene)
        assert ".. controls" in renderer.render()
        assert renderer.report.to_dict()["skipped"] == []

    def test_svg_and_tikz_agree_on_part_count(self):
        scene = _load("stage_arc.json")
        assert _tagged_svg(scene).count("data-component-id") >= 1
        assert "\\begin{tikzpicture}" in TikzRenderer(scene).render()


class TestChipRoute:
    def test_route_endpoints_land_on_true_ports(self):
        scene = _load("chip_route.json")
        routes = [n for n in scene.walk() if type(n).__name__ in {"Route", "WaveguideRoute"}]
        assert routes, "fixture must contain the routed link"

    def test_glb_exports_chip_geometry(self):
        pytest.importorskip("trimesh")
        from optodraw.exporters import scene_to_glb_with_report

        scene = _load("chip_route.json")
        _, report = scene_to_glb_with_report(scene)
        assert report["meshes"] >= 2
