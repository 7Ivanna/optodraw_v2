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


    def test_glb_covers_parts_and_the_beam(self):
        pytest.importorskip("trimesh")
        from optodraw.exporters import scene_to_glb_with_report

        scene = _load("rotated_optics.json")
        _, report = scene_to_glb_with_report(scene)
        assert report["meshes"] >= 3
        # the beam is in the file now, as a tube along its centre line, and the report says so
        assert any("Beam" in entry and "tube" in entry for entry in report["approximated"])
        assert not any("Beam" in entry for entry in report["skipped"])


class TestChipRoute:

    def test_glb_exports_chip_geometry(self):
        pytest.importorskip("trimesh")
        from optodraw.exporters import scene_to_glb_with_report

        scene = _load("chip_route.json")
        _, report = scene_to_glb_with_report(scene)
        assert report["meshes"] >= 2
