"""Smoke tests for the documented quickstart workflows."""

from pathlib import Path

import pytest

from optodraw import (
    Beam,
    Grid,
    Laser,
    Lens,
    MicroringResonator,
    Mirror,
    Scene,
    describe_component,
    list_components,
    list_material_presets,
    load_gds_layout,
)
from examples.tutorial_scenes import gc_ring_photodetector


REPO_ROOT = Path(__file__).resolve().parents[1]
DEMO_GDS = REPO_ROOT / "examples" / "assets" / "demo_mask.gds"


class TestQuickstartDocs:
    def test_free_space_quickstart_scene(self, tmp_path):
        scene = Scene(title="Fold and focus", width=220, height=120, platform="free_space")
        scene.add(Grid(width=220, height=120, pitch=20))
        laser = scene.add(Laser(center=(-75, 0), wavelength=532, label="Pump"))
        mirror = scene.add(Mirror(center=(20, 0), angle=45, label="M1"))
        lens = scene.add(Lens(center=(20, 42), angle=90, label="L1"))
        scene.add(Beam(laser, mirror, lens, wavelength=532, label="Excitation"))

        svg_path = tmp_path / "setup.svg"
        tex_path = tmp_path / "setup.tex"
        html_path = tmp_path / "setup.html"
        scene.render_svg(svg_path.as_posix())
        scene.render_tikz(tex_path.as_posix(), standalone=False)
        scene.render_threejs(html_path.as_posix())
        assert svg_path.exists()
        assert tex_path.exists()
        assert html_path.exists()

    def test_component_preview_quickstart(self, tmp_path):
        ring = MicroringResonator(label="Ring", material_preset="silicon")
        html_path = tmp_path / "ring_component.html"
        html = ring.render_threejs(html_path.as_posix(), show_grid=False)
        assert html_path.exists()
        assert "Ring" in html

    def test_onchip_routing_quickstart(self, tmp_path):
        chip = gc_ring_photodetector()
        svg_path = tmp_path / "chip.svg"
        html_path = tmp_path / "chip.html"
        chip.render_svg(svg_path.as_posix())
        chip.render_threejs(html_path.as_posix(), show_grid=False)
        assert svg_path.exists()
        assert html_path.exists()
        assert "dangling" in chip.metadata
        assert isinstance(chip.metadata["dangling"], list)

    def test_component_discovery_quickstart(self):
        on_chip = list_components(platform="on_chip")
        info = describe_component("GratingCouplerArray")
        presets = list_material_presets()
        assert "GratingCouplerArray" in on_chip
        assert info["category"] == "on_chip"
        assert "silicon" in presets

    def test_gds_mesh_export_quickstart(self, tmp_path):
        pytest.importorskip("gdsfactory")
        pytest.importorskip("gdstk")
        pytest.importorskip("shapely")
        pytest.importorskip("trimesh")
        assert DEMO_GDS.exists()
        layout = load_gds_layout(DEMO_GDS)
        scene, _model = layout.build_scene(material_preset="silicon")
        svg_path = tmp_path / "demo_mask.svg"
        scene.render_svg(svg_path.as_posix())
        exports = layout.export_mesh(tmp_path / "gds", backend="auto")
        assert svg_path.exists()
        assert exports["backend"] in {"gdsfactory", "trimesh"}
        assert exports["stl"].exists()
        assert exports["glb"].exists()
        assert exports["layers"] > 0


class TestTheRayTracingDocMatchesTheTracer:
    """The docs are the physics contract this tool asks to be trusted on.

    A surface kind the tracer grew and the page never mentioned is a promise
    quietly broken in the other direction — the reader has no way to know the
    behaviour exists, or that it changed.
    """

    def _documented_kinds(self) -> set[str]:
        import re
        from pathlib import Path

        doc = Path(__file__).resolve().parents[1] / "docs" / "content" / "ray-tracing.mdx"
        block = doc.read_text(encoding="utf-8").split('kind="lens"', 1)
        assert len(block) == 2, "the interface-protocol example is gone from the docs"
        listing = block[1].split(")")[0]
        return {"lens", *re.findall(r"\|\s*(\w+)", listing)}

    def _implemented_kinds(self) -> set[str]:
        import re
        from pathlib import Path

        src = (Path(__file__).resolve().parents[1] / "optodraw" / "core" / "raytrace.py").read_text()
        return set(re.findall(r'spec\.kind == "(\w+)"', src)) | {"schematic", "beam_splitter"}

    def test_every_surface_kind_the_tracer_handles_is_documented(self):
        missing = self._implemented_kinds() - self._documented_kinds()
        assert not missing, f"surface kinds the docs never mention: {sorted(missing)}"

    def test_the_docs_do_not_promise_surfaces_that_do_not_exist(self):
        phantom = self._documented_kinds() - self._implemented_kinds()
        assert not phantom, f"documented but not implemented: {sorted(phantom)}"
