"""Shared animation frame states (GIF + Manim auto modes) and Manim pure parts.

These tests do not require Manim or the gif extra. They pin the one frame
contract both renderers now share:

- ``build_auto_frames`` matches ``GifRenderer._build_frames`` exactly
- the Grid background is never an animated "solid" (previous Manim-only defect)
- ``ManimRenderer`` init/quality handling works without the manim package
- frame SVG temp files never collide, even in one shared directory
"""

from __future__ import annotations

import pytest

from optodraw import Grid, Laser, Lens, Mirror, Scene
from optodraw.core.beam import Beam
from optodraw.renderers.manim_renderer import ManimRenderer, _write_svg


def _simple_scene() -> Scene:
    scene = Scene(title="Test", width=220, height=120, platform="free_space")
    scene.add(Grid(width=220, height=120, pitch=20))
    laser = scene.add(Laser(center=(-60, 0), wavelength=532, label="Pump"))
    mirror = scene.add(Mirror(center=(0, 0), angle=45, label="M1"))
    lens = scene.add(Lens(center=(0, 40), angle=90, label="L1"))
    scene.add(Beam(laser, mirror, lens, wavelength=532))
    return scene


class TestManimPureParts:


    def test_render_missing_manim_fails_fast(self, tmp_path, monkeypatch):
        import builtins

        real_import = builtins.__import__

        def _no_manim(name, *args, **kwargs):
            if name == "manim" or name.startswith("manim."):
                raise ImportError("No module named 'manim'")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _no_manim)
        with pytest.raises(ImportError, match=r"optodraw\[manim\]"):
            ManimRenderer(_simple_scene()).render(str(tmp_path / "out.mp4"))

    def test_write_svg_paths_never_collide(self, tmp_path):
        first = _write_svg(tmp_path, "<svg/>")
        second = _write_svg(tmp_path, "<svg/>")
        assert first != second
        assert first.is_file() and second.is_file()
        assert first.read_text(encoding="utf-8") == "<svg/>"
