"""Manim renderer — animated video output (Manim Community Edition).

Requires ``pip install optodraw[manim]``.

Two usage paths:

1. **Direct**: ``scene.render_video("out.mp4", animation_style="build_up")``
2. **Timeline-driven**: build an :class:`~optodraw.animation.AnimationTimeline` for
   per-step captions and custom ordering, then call ``timeline.render_video("out.mp4")``.

Animation styles (``animation_style`` kwarg):

- ``"build_up"``: components fade in one at a time; beams draw in full after all
  solids are visible.
- ``"beam_trace"``: same as build_up but each beam grows along its path with a
  :class:`manim.animations.creation.Create` animation.
- ``"simultaneous"``: all components appear together.

Quality presets map to the Manim ``-q`` flag:
``"low"``, ``"medium"`` (default), ``"high"``, ``"fourk"``.
"""

from __future__ import annotations

import tempfile
import math
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from optodraw.animation import AnimationTimeline

from optodraw.core.beam import Beam
from optodraw.core.component import Group
from optodraw.core.routing import Route


# ---------------------------------------------------------------------------
# Renderer
# ---------------------------------------------------------------------------


class ManimRenderer:
    """Renders a Scene to an animated video using Manim CE.

    Parameters
    ----------
    scene : Scene
        The optodraw scene to render.
    timeline : AnimationTimeline, optional
        If supplied, the video follows the timeline's step ordering with captions.
    animation_style : str
        ``"build_up"`` (default), ``"beam_trace"``, or ``"simultaneous"``.
    quality : str
        ``"low"``, ``"medium"`` (default), ``"high"``, or ``"fourk"``.
    """

    def __init__(self, scene, **kwargs):
        self.scene = scene
        self.timeline: AnimationTimeline | None = kwargs.get("timeline", None)
        self.quality: str = self._normalize_quality(kwargs.get("quality", "medium_quality"))
        self.animation_style: str = kwargs.get("animation_style", "build_up")

    @staticmethod
    def _normalize_quality(value: str) -> str:
        q = str(value).strip().lower().replace("-", "_")
        aliases = {
            "low": "low_quality",
            "medium": "medium_quality",
            "high": "high_quality",
            "fourk": "fourk_quality",
        }
        return aliases.get(q, q)

    # -- public ---------------------------------------------------------------

    def render(self, filename: str = "scene.mp4") -> None:
        """Build a Manim scene from the optodraw scene and render to *filename*."""
        try:
            from manim import (
                Scene as MScene,
                SVGMobject,
                VGroup,
                Line,
                Text,
                Create,
                FadeIn,
                FadeOut,
                Write,
                config,
                WHITE,
                DOWN,
            )
        except ImportError:
            raise ImportError(
                "Manim is required for video rendering.\n"
                "Install with: pip install optodraw[manim]"
            )

        config.output_file = filename
        config.quality = self.quality

        renderer_self = self

        with tempfile.TemporaryDirectory() as tmp_dir_str:
            tmp_dir = Path(tmp_dir_str)

            if renderer_self.timeline is not None:
                _build_timeline_scene(
                    renderer_self, tmp_dir,
                    MScene, SVGMobject, VGroup, Line,
                    Text, Create, FadeIn, FadeOut, Write, WHITE, DOWN,
                )
            else:
                _build_auto_scene(
                    renderer_self, tmp_dir,
                    MScene, SVGMobject, VGroup, Line,
                    Text, Create, FadeIn, FadeOut, Write, WHITE, DOWN,
                )


# ---------------------------------------------------------------------------
# Auto-mode scene builder (no timeline)
# ---------------------------------------------------------------------------

def _build_auto_scene(rself, tmp_dir, MScene, SVGMobject, VGroup, Line,
                      Text, Create, FadeIn, FadeOut, Write, WHITE, DOWN):
    """Build and render an automatic build-up or simultaneous scene."""

    from optodraw.renderers.frame_states import build_auto_frames, collect_frame_components
    from optodraw.renderers.svg_renderer import SvgRenderer

    scene = rself.scene
    style = rself.animation_style

    def _render_state(state) -> object:
        svgr = SvgRenderer(
            scene,
            hidden_ids=state.get("hidden_ids", set()),
            partial_beams=state.get("partial_beams", {}),
        )
        svg_str = svgr.render().as_svg()
        mob = SVGMobject(str(_write_svg(tmp_dir, svg_str)))
        mob.scale_to_fit_width(6.5)
        return mob

    class AutoScene(MScene):
        def construct(self_ms):
            if style == "simultaneous":
                # Render the full scene once
                svgr = SvgRenderer(scene)
                svg_str = svgr.render().as_svg()
                mob = SVGMobject(str(_write_svg(tmp_dir, svg_str)))
                mob.scale_to_fit_width(6.5)
                self_ms.play(Create(mob))
                self_ms.wait(2)
                return

            # build_up / beam_trace: same frame states as the GIF renderer;
            # only the per-frame pacing (and the label captions) differ.
            solids, _beams = collect_frame_components(scene)
            by_id = {id(comp): comp for comp in solids}
            frames = build_auto_frames(scene, style)
            solid_frame_count = 1 + len(solids)

            current_mob = None
            prev_hidden: set[int] | None = None
            for index, state in enumerate(frames):
                next_mob = _render_state(state)
                if current_mob is None:
                    self_ms.play(FadeIn(next_mob), run_time=0.5)
                elif style == "beam_trace" and index >= solid_frame_count:
                    self_ms.play(FadeOut(current_mob), FadeIn(next_mob), run_time=0.05)
                else:
                    self_ms.play(FadeOut(current_mob), FadeIn(next_mob), run_time=0.4)
                current_mob = next_mob

                if prev_hidden is not None:
                    for revealed_id in prev_hidden - state["hidden_ids"]:
                        comp = by_id.get(revealed_id)
                        if comp is not None and comp.label:
                            lbl = Text(comp.label, font_size=20, color=WHITE)
                            lbl.to_edge(DOWN, buff=0.3)
                            self_ms.play(Write(lbl), run_time=0.3)
                            self_ms.wait(0.4)
                            self_ms.play(FadeOut(lbl), run_time=0.2)
                prev_hidden = state["hidden_ids"]

            self_ms.wait(2)

    AutoScene().render()


# ---------------------------------------------------------------------------
# Timeline-driven scene builder
# ---------------------------------------------------------------------------

def _build_timeline_scene(rself, tmp_dir, MScene, SVGMobject, VGroup, Line,
                           Text, Create, FadeIn, FadeOut, Write, WHITE, DOWN):
    """Build and render a scene driven by an AnimationTimeline."""

    from optodraw.renderers.frame_states import collect_frame_components
    from optodraw.renderers.svg_renderer import SvgRenderer

    scene = rself.scene
    timeline = rself.timeline
    steps = timeline._steps

    solids, beams = collect_frame_components(scene)
    all_ids: set[int] = {id(c) for c in solids + beams}
    visible_ids: set[int] = set()

    def _reveal(component):
        if isinstance(component, Group):
            for child in component.children:
                _reveal(child)
        else:
            visible_ids.add(id(component))

    def _render(partial=None, traveling=None, highlighted=None,
                polarization_overlays=None, polarization_caption=""):
        svgr = SvgRenderer(
            scene,
            hidden_ids=all_ids - visible_ids,
            partial_beams=partial or {},
            traveling_waves=traveling or {},
            highlight_levels=highlighted or {},
            show_polarization_overlay=bool(polarization_overlays),
            polarization_overlays=polarization_overlays or {},
            polarization_caption=polarization_caption,
        )
        svg_str = svgr.render().as_svg()
        mob = SVGMobject(str(_write_svg(tmp_dir, svg_str)))
        mob.scale_to_fit_width(6.5)
        return mob

    class TimelineScene(MScene):
        def construct(self_ms):
            current_mob = None
            caption_mob = None

            def _swap(next_mob):
                nonlocal current_mob
                if current_mob is None:
                    self_ms.play(FadeIn(next_mob), run_time=0.5)
                else:
                    self_ms.play(FadeOut(current_mob), FadeIn(next_mob), run_time=0.4)
                current_mob = next_mob

            def _show_caption(text: str):
                nonlocal caption_mob
                if caption_mob is not None:
                    self_ms.play(FadeOut(caption_mob), run_time=0.2)
                if text:
                    caption_mob = Text(text, font_size=22, color=WHITE)
                    caption_mob.to_edge(DOWN, buff=0.3)
                    self_ms.play(Write(caption_mob), run_time=0.4)

            def _clear_caption():
                nonlocal caption_mob
                if caption_mob is not None:
                    self_ms.play(FadeOut(caption_mob), run_time=0.2)
                    caption_mob = None

            for step in steps:
                if step.kind == "show":
                    _reveal(step.component)
                    next_mob = _render()
                    _swap(next_mob)
                    if step.caption:
                        _show_caption(step.caption)
                    self_ms.wait(max(0.3, step.dwell * 0.5))
                    _clear_caption()

                elif step.kind == "trace":
                    comp = step.component
                    _reveal(comp)
                    if step.caption:
                        _show_caption(step.caption)
                    _trace_steps = step.trace_steps
                    for i in range(1, _trace_steps + 1):
                        fraction = i / _trace_steps
                        partial: dict[int, float] = {
                            id(c): 1.0
                            for c in scene.walk()
                            if isinstance(c, (Beam, Route))
                            and id(c) in visible_ids
                            and c is not comp
                        }
                        partial[id(comp)] = fraction
                        next_mob = _render(partial)
                        _swap(next_mob)
                        self_ms.wait(0.04)
                    self_ms.wait(max(0.3, step.dwell * 0.5))
                    _clear_caption()

                elif step.kind == "pause":
                    if step.caption:
                        _show_caption(step.caption)
                    self_ms.wait(step.dwell)
                    _clear_caption()

                elif step.kind == "wave_travel":
                    comp = step.component
                    _reveal(comp)
                    if step.caption:
                        _show_caption(step.caption)
                    packet_length = min(0.22, max(0.08, 2.0 / max(step.trace_steps, 1)))
                    run_time = max(0.03, step.dwell / max(step.trace_steps, 1))
                    for i in range(1, step.trace_steps + 1):
                        head = i / step.trace_steps
                        tail = max(0.0, head - packet_length)
                        next_mob = _render(traveling={id(comp): (tail, head)})
                        _swap(next_mob)
                        self_ms.wait(run_time)
                    _clear_caption()

                elif step.kind == "cavity_power":
                    comp = step.component
                    _reveal(comp)
                    if step.caption:
                        _show_caption(step.caption)
                    run_time = max(0.03, step.dwell / max(step.trace_steps, 1))
                    for i in range(step.trace_steps):
                        phase = i / max(step.trace_steps - 1, 1)
                        strength = 0.2 + 0.8 * math.sin(math.pi * phase)
                        next_mob = _render(highlighted={id(comp): strength})
                        _swap(next_mob)
                        self_ms.wait(run_time)
                    _clear_caption()

                elif step.kind == "absorb":
                    comp = step.component
                    _reveal(comp)
                    if step.caption:
                        _show_caption(step.caption)
                    packet_length = min(0.22, max(0.08, 2.0 / max(step.trace_steps, 1)))
                    run_time = max(0.03, step.dwell / max(step.trace_steps, 1))
                    for i in range(1, step.trace_steps + 1):
                        progress = i / step.trace_steps
                        tail = min(1.0, 1.0 - packet_length * (1.0 - progress))
                        next_mob = _render(traveling={id(comp): (tail, 1.0)})
                        _swap(next_mob)
                        self_ms.wait(run_time)
                    _swap(_render())
                    _clear_caption()

                elif step.kind == "polarization":
                    comp = step.component
                    if comp is not None:
                        _reveal(comp)
                    if step.caption:
                        _show_caption(step.caption)
                    highlighted = {id(comp): 1.0} if comp is not None else {}
                    overlays = (
                        {id(comp): step.stokes}
                        if comp is not None and step.stokes is not None
                        else {}
                    )
                    _swap(_render(
                        highlighted=highlighted,
                        polarization_overlays=overlays,
                        polarization_caption=step.caption or step.polarization_annotation,
                    ))
                    self_ms.wait(max(0.3, step.dwell))
                    _clear_caption()

            # Final hold
            _clear_caption()
            self_ms.wait(2)

    TimelineScene().render()


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _write_svg(tmp_dir: Path, svg_str: str) -> Path:
    """Write svg_str to a unique temp file and return the path.

    The name is random per call (not a module-global counter) so parallel or
    repeated renders never collide, even across processes sharing a tmp dir.
    """

    import uuid

    p = tmp_dir / f"frame_{uuid.uuid4().hex[:12]}.svg"
    p.write_text(svg_str, encoding="utf-8")
    return p
