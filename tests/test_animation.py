"""Smoke tests for the video/animation layer.

These tests do NOT require Manim (heavy install) or the gif extra (Cairo).
They validate:
  - GifRenderer frame-building logic
  - SvgRenderer hidden_ids / partial_beams extensions
  - AnimationTimeline step API and frame-state generation
  - Scene.timeline() / Scene.render_gif() integration (smoke, no output)
  - Partial-path geometry helper
"""

from __future__ import annotations

import pytest

from optodraw import (
    Scene,
    Grid,
    Laser,
    Mirror,
    Lens,
    Beam,
    GratingCouplerArray,
    VerticalGratingCoupler,
    MicroringResonator,
    OnChipPhotodetector,
)
from optodraw.core.beam import Beam as BeamType
from optodraw.core.routing import Route
from optodraw.renderers.svg_renderer import SvgRenderer
from optodraw.renderers.gif_renderer import GifRenderer


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _simple_scene() -> Scene:
    scene = Scene(title="Test", width=220, height=120, platform="free_space")
    scene.add(Grid(width=220, height=120, pitch=20))
    laser  = scene.add(Laser(center=(-60, 0), wavelength=532, label="Pump"))
    mirror = scene.add(Mirror(center=(0, 0), angle=45, label="M1"))
    lens   = scene.add(Lens(center=(0, 40), angle=90, label="L1"))
    beam   = scene.add(Beam(laser, mirror, lens, wavelength=532))
    return scene


def _chip_scene() -> Scene:
    chip = Scene(title="Chip", width=280, height=180, platform="on_chip")
    gca  = chip.add(GratingCouplerArray(count=4, pitch=127.0, label="GCA"))
    ring = chip.add(MicroringResonator(center=(0, -55), label="Ring"))
    pd   = chip.add(OnChipPhotodetector(center=(150, -55), label="PD"))
    r1   = chip.route((gca, "o2"), (ring, "o1"), kind="waveguide")
    r2   = chip.route((ring, "o2"), (pd, "o1"), kind="waveguide")
    return chip


# ---------------------------------------------------------------------------
# SvgRenderer animation extensions
# ---------------------------------------------------------------------------

class TestSvgRendererAnimationExtensions:
    def test_hidden_ids_hides_component(self):
        scene = _simple_scene()
        components = [c for c in scene.walk() if c.label == "Pump"]
        assert components, "Pump laser not found"
        laser = components[0]

        svg_full = SvgRenderer(scene).render().as_svg()
        svg_hidden = SvgRenderer(scene, hidden_ids={id(laser)}).render().as_svg()

        assert "Pump" in svg_full
        assert "Pump" not in svg_hidden


    def test_partial_beams_shorter_path(self):
        scene = _simple_scene()
        beams = [c for c in scene.walk() if isinstance(c, BeamType)]
        assert beams, "No beams in scene"
        beam = beams[0]

        svg_full = SvgRenderer(scene, partial_beams={id(beam): 1.0}).render().as_svg()
        svg_half = SvgRenderer(scene, partial_beams={id(beam): 0.3}).render().as_svg()

        # Both should be valid SVG; the half path should produce a shorter drawn path
        assert "<path" in svg_full
        assert "<path" in svg_half

    def test_partial_path_helper_fraction_one(self):
        pts = [(0, 0), (10, 0), (10, 10)]
        result = SvgRenderer._partial_path_points(pts, 1.0)
        assert result == pts

    def test_partial_path_helper_fraction_zero(self):
        pts = [(0, 0), (10, 0), (10, 10)]
        result = SvgRenderer._partial_path_points(pts, 0.0)
        assert result == [(0, 0)]


    def test_partial_path_helper_multi_segment(self):
        # Three equal-length segments; ask for 2/3 of total = first two segments exactly
        pts = [(0, 0), (10, 0), (20, 0), (30, 0)]
        result = SvgRenderer._partial_path_points(pts, 2 / 3)
        assert len(result) == 3
        assert abs(result[-1][0] - 20.0) < 1e-9

    def test_path_slice_helper_extracts_middle_segment(self):
        pts = [(0, 0), (10, 0), (20, 0)]
        result = SvgRenderer._path_slice_points(pts, 0.25, 0.75)
        assert len(result) == 3
        assert abs(result[0][0] - 5.0) < 1e-9
        assert abs(result[-1][0] - 15.0) < 1e-9


# ---------------------------------------------------------------------------
# GifRenderer frame logic
# ---------------------------------------------------------------------------

class TestGifRendererFrameLogic:
    def test_build_up_frames_count(self):
        scene = _simple_scene()
        renderer = GifRenderer(scene)
        frames = renderer._build_frames("build_up")

        solids, beams = renderer._collect_components()
        # 1 blank + 1 per solid + 1 per beam
        expected = 1 + len(solids) + len(beams)
        assert len(frames) == expected

    def test_beam_trace_frames_more_than_build_up(self):
        scene = _simple_scene()
        renderer = GifRenderer(scene)
        frames_build = renderer._build_frames("build_up")
        frames_trace = renderer._build_frames("beam_trace")
        assert len(frames_trace) > len(frames_build)


# ---------------------------------------------------------------------------
# AnimationTimeline API
# ---------------------------------------------------------------------------

class TestAnimationTimeline:


    def test_full_timeline_frame_count(self):
        scene = _simple_scene()
        laser  = next(c for c in scene.walk() if c.label == "Pump")
        mirror = next(c for c in scene.walk() if c.label == "M1")
        lens   = next(c for c in scene.walk() if c.label == "L1")
        beam   = next(c for c in scene.walk() if isinstance(c, BeamType))

        tl = scene.timeline()
        tl.show(laser).show(mirror).show(lens).trace(beam, steps=10).pause(1.5)
        states = tl._to_frame_states()
        # blank + 3 show + 10 trace + 1 pause = 15
        assert len(states) == 15


    def test_absorb_preserves_route_after_animation(self):
        chip = _chip_scene()
        route = next(c for c in chip.walk() if isinstance(c, Route))

        tl = chip.timeline().show(route).absorb(route, steps=4)
        states = tl._to_frame_states()

        assert id(route) not in states[-1]["hidden_ids"]


    def test_svg_traveling_wave_state_adds_overlay(self):
        chip = _chip_scene()
        route = next(c for c in chip.walk() if isinstance(c, Route))

        base_svg = SvgRenderer(chip).render().as_svg()
        wave_svg = SvgRenderer(chip, traveling_waves={id(route): (0.25, 0.45)}).render().as_svg()

        assert len(wave_svg) > len(base_svg)

    def test_svg_highlight_state_adds_component_emphasis(self):
        chip = _chip_scene()
        ring = next(c for c in chip.walk() if isinstance(c, MicroringResonator))

        base_svg = SvgRenderer(chip).render().as_svg()
        highlighted_svg = SvgRenderer(chip, highlight_levels={id(ring): 0.8}).render().as_svg()

        assert len(highlighted_svg) > len(base_svg)


    def test_onchip_orientation_deg_alias_matches_angle(self):
        gc_by_angle = VerticalGratingCoupler(center=(0, 0), angle=180)
        gc_by_alias = VerticalGratingCoupler(center=(0, 0), orientation_deg=180)

        port_angle = gc_by_angle.world_port("o1")
        port_alias = gc_by_alias.world_port("o1")
        assert port_angle.center.x == pytest.approx(port_alias.center.x)
        assert port_angle.center.y == pytest.approx(port_alias.center.y)
        assert port_angle.orientation_deg == pytest.approx(port_alias.orientation_deg)


# ---------------------------------------------------------------------------
# Scene integration (no I/O — just confirms the plumbing doesn't crash)
# ---------------------------------------------------------------------------


def test_gif_frames_sit_on_white_not_black(tmp_path):
    """The SVG background is transparent; a palette frame drops alpha, so every frame must be put on
    white first, or the GIF shows dark labels on black."""

    from PIL import Image

    path = tmp_path / "scene.gif"
    _simple_scene().render_gif(str(path), mode="beam_trace")
    gif = Image.open(path)
    for index in (0, gif.n_frames - 1):
        gif.seek(index)
        assert gif.convert("RGB").getpixel((2, 2)) == (255, 255, 255)
