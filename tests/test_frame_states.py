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
from optodraw.renderers.frame_states import (
    BEAM_TRACE_STEPS,
    build_auto_frames,
    collect_frame_components,
)
from optodraw.renderers.gif_renderer import GifRenderer
from optodraw.renderers.manim_renderer import ManimRenderer, _write_svg


def _simple_scene() -> Scene:
    scene = Scene(title="Test", width=220, height=120, platform="free_space")
    scene.add(Grid(width=220, height=120, pitch=20))
    laser = scene.add(Laser(center=(-60, 0), wavelength=532, label="Pump"))
    mirror = scene.add(Mirror(center=(0, 0), angle=45, label="M1"))
    lens = scene.add(Lens(center=(0, 40), angle=90, label="L1"))
    scene.add(Beam(laser, mirror, lens, wavelength=532))
    return scene


class TestSharedFrameBuilder:
    @pytest.mark.parametrize("mode", ["build_up", "beam_trace"])
    def test_matches_gif_renderer_frames(self, mode: str):
        scene = _simple_scene()
        shared = build_auto_frames(scene, mode)
        legacy = GifRenderer(scene)._build_frames(mode)
        assert len(shared) == len(legacy)
        for mine, theirs in zip(shared, legacy):
            assert set(mine["hidden_ids"]) == set(theirs["hidden_ids"])
            assert mine["partial_beams"] == theirs["partial_beams"]

    def test_beam_trace_uses_shared_step_count(self):
        scene = _simple_scene()
        frames = build_auto_frames(scene, "beam_trace")
        solids, beams = collect_frame_components(scene)
        # blank + solids + len(beams) * steps
        assert len(frames) == 1 + len(solids) + len(beams) * BEAM_TRACE_STEPS
        assert BEAM_TRACE_STEPS == 12

    def test_unknown_mode_falls_back_to_build_up(self):
        scene = _simple_scene()
        assert build_auto_frames(scene, "simultaneous") == build_auto_frames(scene, "build_up")

    def test_grid_is_never_an_animated_solid(self):
        scene = Scene(title="Grid only", width=100, height=100, platform="free_space")
        scene.add(Grid(width=100, height=100, pitch=20))
        solids, beams = collect_frame_components(scene)
        assert solids == [] and beams == []
        frames = build_auto_frames(scene, "build_up")
        assert len(frames) == 1  # only the blank opening frame
        assert frames[0]["hidden_ids"] == set()

    def test_partial_fractions_stay_in_range(self):
        scene = _simple_scene()
        for state in build_auto_frames(scene, "beam_trace"):
            for value in state["partial_beams"].values():
                assert 0.0 < value <= 1.0


class TestManimPureParts:
    def test_init_defaults_without_manim(self):
        scene = _simple_scene()
        renderer = ManimRenderer(scene)
        assert renderer.animation_style == "build_up"
        assert renderer.quality == "medium_quality"
        assert renderer.timeline is None

    @pytest.mark.parametrize(
        ("given", "expected"),
        [
            ("low", "low_quality"),
            ("medium", "medium_quality"),
            ("high", "high_quality"),
            ("fourk", "fourk_quality"),
            ("medium_quality", "medium_quality"),
            ("HIGH", "high_quality"),
        ],
    )
    def test_quality_normalization(self, given: str, expected: str):
        scene = _simple_scene()
        assert ManimRenderer(scene, quality=given).quality == expected

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
