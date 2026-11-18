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
    TABLES,
    UnsupportedGeometryError,
)
from optodraw.renderers.tikz_renderer import TikzRenderer


def _scene() -> Scene:
    scene = Scene(width=120, height=80)
    scene.add(Laser(center=(-30, 0), label="Pump"))
    scene.add(Lens(center=(10, 0)))
    return scene


class TestTables:
    def test_known_renderers_have_tables(self):
        assert set(TABLES) == {"svg", "tikz", "glb", "threejs"}


class TestTikzStrict:
    def test_unknown_type_records_skip(self):
        renderer = TikzRenderer(_scene())
        assert renderer._render_geometry({"type": "teleport"}) == []
        assert any("teleport" in entry for entry in renderer.report.skipped)

    def test_strict_raises_on_unknown_type(self):
        renderer = TikzRenderer(_scene(), strict=True)
        with pytest.raises(UnsupportedGeometryError, match="teleport"):
            renderer._render_geometry({"type": "teleport"})


class TestGlbStrict:

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
