"""AnimationTimeline — structured step-by-step animation for tutoring output.

Usage::

    from optodraw import Scene, Laser, Mirror, Lens, Beam

    scene = Scene(title="PL Setup", width=220, height=120, platform="free_space")
    laser  = scene.add(Laser(center=(0, 0), wavelength=532, label="Pump"))
    mirror = scene.add(Mirror(center=(30, 0), angle=45, label="M1"))
    lens   = scene.add(Lens(center=(30, 42), angle=90, label="L1"))
    beam   = scene.add(Beam(laser, mirror, lens, wavelength=532))

    tl = scene.timeline()
    tl.show(laser,  caption="Pump laser — 532 nm")
    tl.show(mirror, caption="Dichroic mirror — reflects pump")
    tl.show(lens,   caption="Objective lens — NA 0.6")
    tl.trace(beam,  caption="Excitation beam path")

    tl.render_gif("pl_tutorial.gif", fps=6)
    tl.render_video("pl_tutorial.mp4")

Each :meth:`show`, :meth:`trace`, and :meth:`pause` call appends a *step*
to the timeline.  Calling :meth:`render_gif` or :meth:`render_video` converts
the step list to frame states and delegates to the appropriate renderer.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any


def _resolve_wave_color(explicit_color: str | None, wavelength_nm: float | None) -> str | None:
    """Resolve a pulse color from an explicit override or a wavelength hint.

    ``explicit_color`` always wins. ``wavelength_nm`` is mapped through the
    project's ``wavelength_to_hex`` palette (also used by ``Beam``). Returns
    ``None`` when neither is supplied so renderers can fall back to their
    own defaults.
    """

    if explicit_color is not None:
        return str(explicit_color)
    if wavelength_nm is None:
        return None
    from optodraw.core.beam import wavelength_to_hex

    return wavelength_to_hex(float(wavelength_nm))


@dataclass
class _Step:
    """One timeline command after it has been normalized for renderers."""

    kind: str           # "show" | "trace" | "pause" | "wave_travel" | "cavity_power" | "absorb" | "polarization"
    component: Any = None
    caption: str = ""
    dwell: float = 1.0
    trace_steps: int = 12
    # Optional: for optical effects
    target_component: Any = None  # used by cavity_power to brighten a target
    effect_intensity: float = 1.0  # used by absorb/cavity_power for fade/brighten
    # Optional: 3D pulse rendering hints (consumed by Three.js/Manim renderers)
    pulse_width: float | None = None       # fraction of the path in [0, 1]
    wavelength_nm: float | None = None     # used to colorize the wave packet
    pulse_color: str | None = None         # explicit color override (hex string)
    opacity_envelope: str | None = None    # "gaussian" | "linear" | "constant" | None
    trail: bool = False                    # leave a fading trail behind the head
    trail_length: float | None = None      # fraction of path for the trail; defaults to 3*pulse_width
    fade: bool = False                     # fade the wave packet out over time
    # Optional: polarization tutoring metadata
    stokes: Any = None
    jones: Any = None
    polarization_annotation: str = ""


class AnimationTimeline:
    """Structured step-by-step animation sequence for a :class:`~optodraw.core.scene.Scene`.

    Obtain an instance via ``scene.timeline()`` rather than constructing directly.
    """

    def __init__(self, scene):
        self.scene = scene
        self._steps: list[_Step] = []

    # -- builder API ----------------------------------------------------------

    def show(
        self, component, *, caption: str = "", dwell: float = 1.0
    ) -> "AnimationTimeline":
        """Reveal a component in the next animation step.

        Parameters
        ----------
        component : Component
            The scene component to make visible.
        caption : str
            Optional tutoring caption displayed alongside this step (Manim only).
        dwell : float
            Hold time in seconds on this frame (affects GIF timing).
        """
        self._steps.append(_Step("show", component=component, caption=caption, dwell=dwell))
        return self

    def trace(
        self,
        component,
        *,
        caption: str = "",
        dwell: float = 1.5,
        steps: int = 12,
    ) -> "AnimationTimeline":
        """Animate a beam or route growing along its path.

        Parameters
        ----------
        component : Beam | Route
            The beam or route to animate.
        caption : str
            Optional tutoring caption.
        dwell : float
            Hold time after the trace completes (seconds).
        steps : int
            Number of intermediate frames for the grow animation.
        """
        self._steps.append(
            _Step("trace", component=component, caption=caption, dwell=dwell, trace_steps=steps)
        )
        return self

    def pause(self, duration: float = 1.0, *, caption: str = "") -> "AnimationTimeline":
        """Insert a hold at the current state without changing visibility.

        Parameters
        ----------
        duration : float
            Hold duration in seconds.
        caption : str
            Optional caption for Manim output.
        """
        self._steps.append(_Step("pause", caption=caption, dwell=duration))
        return self

    def wave_travel(
        self,
        route,
        *,
        caption: str = "",
        dwell: float = 2.0,
        steps: int = 16,
        pulse_width: float | None = None,
        wavelength_nm: float | None = None,
        pulse_color: str | None = None,
        opacity_envelope: str | None = None,
        trail: bool = False,
        trail_length: float | None = None,
        fade: bool = False,
    ) -> "AnimationTimeline":
        """Animate a wave packet traveling along a route (e.g., signal propagation).

        This creates a smooth wave-motion effect by showing the route growing
        from start to end, simulating wave propagation.

        Parameters
        ----------
        route : Route | Beam
            The route or beam to animate as a traveling wave.
        caption : str
            Optional tutoring caption describing the wave propagation.
        dwell : float
            Duration of the wave travel animation (seconds).
        steps : int
            Number of intermediate frames for smooth motion.
        pulse_width : float, optional
            Fraction of the path occupied by the wave packet (``0 < w < 1``).
            When ``None``, an auto value is chosen from ``steps``.
        wavelength_nm : float, optional
            If provided, the renderer is hinted to colorize the packet using a
            visible-spectrum mapping (``wavelength_to_hex``).
        pulse_color : str, optional
            Explicit hex color override; takes precedence over ``wavelength_nm``.
        opacity_envelope : {"gaussian", "linear", "constant"}, optional
            Shape used to taper packet opacity along its length. Renderers may
            use this hint to draw soft-edged pulses; default is ``"constant"``.
        trail : bool
            If ``True``, leave a fading trail behind the wave-packet head.
            The Three.js renderer is the primary consumer of this hook.
        trail_length : float, optional
            Trail length as a fraction of the path; defaults to ``3 * pulse_width``.
        fade : bool
            If ``True``, the packet fades out over the duration of the step.
        """
        if pulse_width is not None and not (0.0 < float(pulse_width) <= 1.0):
            raise ValueError("pulse_width must be in the open-closed interval (0, 1]")
        if opacity_envelope is not None and opacity_envelope not in {
            "gaussian",
            "linear",
            "constant",
        }:
            raise ValueError(
                "opacity_envelope must be one of 'gaussian', 'linear', 'constant'"
            )
        if trail_length is not None and trail_length < 0.0:
            raise ValueError("trail_length must be non-negative")
        self._steps.append(
            _Step(
                "wave_travel",
                component=route,
                caption=caption,
                dwell=dwell,
                trace_steps=steps,
                pulse_width=None if pulse_width is None else float(pulse_width),
                wavelength_nm=None if wavelength_nm is None else float(wavelength_nm),
                pulse_color=pulse_color,
                opacity_envelope=opacity_envelope,
                trail=bool(trail),
                trail_length=None if trail_length is None else float(trail_length),
                fade=bool(fade),
            )
        )
        return self

    def cavity_power(
        self,
        cavity_component,
        *,
        caption: str = "",
        dwell: float = 2.0,
        steps: int = 12,
    ) -> "AnimationTimeline":
        """Animate power building up in a cavity (e.g., microring resonator).

        Shows the cavity component becoming brighter/more intense over time,
        simulating resonant power buildup.

        Parameters
        ----------
        cavity_component : Component
            The cavity (e.g., MicroringResonator) to animate.
        caption : str
            Optional caption explaining the cavity resonance effect.
        dwell : float
            Duration of the power buildup (seconds).
        steps : int
            Number of frames for the intensity ramp.
        """
        self._steps.append(
            _Step("cavity_power", component=cavity_component, caption=caption, dwell=dwell, trace_steps=steps)
        )
        return self

    def absorb(
        self,
        route,
        *,
        caption: str = "",
        dwell: float = 1.5,
        steps: int = 12,
    ) -> "AnimationTimeline":
        """Animate a wave being absorbed (fades out at detector).

        Shows the route gradually fading to represent photon absorption or
        detection.

        Parameters
        ----------
        route : Route | Beam
            The route or beam to animate as absorbed.
        caption : str
            Optional caption explaining the detection/absorption.
        dwell : float
            Duration of the fade-out (seconds).
        steps : int
            Number of frames for smooth fade.
        """
        self._steps.append(
            _Step("absorb", component=route, caption=caption, dwell=dwell, trace_steps=steps)
        )
        return self

    def polarization(
        self,
        component,
        *,
        stokes=None,
        jones=None,
        caption: str = "",
        annotation: str = "",
        dwell: float = 1.5,
    ) -> "AnimationTimeline":
        """Append a polarization tutoring step with Stokes/Jones metadata.

        Renderers may use ``stokes``, ``jones``, and ``annotation`` to draw
        ellipse or Poincaré-sphere overlays (stub metadata today).
        """

        self._steps.append(
            _Step(
                "polarization",
                component=component,
                caption=caption,
                dwell=dwell,
                stokes=stokes,
                jones=jones,
                polarization_annotation=annotation,
            )
        )
        return self

    # -- render entry points --------------------------------------------------

    def render_gif(self, filename: str, *, fps: int = 6, dwell: float = 1.0) -> None:
        """Render the timeline to an animated GIF.

        Requires ``pip install optodraw[gif]``.
        """
        from optodraw.renderers.gif_renderer import GifRenderer

        GifRenderer(self.scene).render_from_timeline(filename, self, fps=fps, dwell=dwell)

    def render_video(self, filename: str = "out.mp4", **kwargs) -> None:
        """Render the timeline to an MP4 via Manim.

        Requires ``pip install optodraw[manim]``.
        """
        from optodraw.renderers.manim_renderer import ManimRenderer

        ManimRenderer(self.scene, timeline=self, **kwargs).render(filename)

    # -- internal: convert to frame states for GIF renderer ------------------

    def _to_frame_states(self) -> list[dict]:
        """Convert the step list to GIF frame states.

        Each state is a dict with keys:

        - ``hidden_ids``: set of ``id(component)`` values that should not be drawn.
        - ``partial_beams``: dict mapping ``id(beam)`` to a draw fraction 0..1.
        - ``traveling_waves``: dict mapping ``id(beam_or_route)`` to ``(start, end)`` fractions.
        - ``highlight_levels``: dict mapping ``id(component)`` to a 0..1 highlight strength.
        """
        from optodraw.core.beam import Beam
        from optodraw.core.component import Group
        from optodraw.core.routing import Route
        from optodraw.renderers.frame_states import collect_frame_components

        solids, beams = collect_frame_components(self.scene)
        all_ids: set[int] = {id(c) for c in solids + beams}
        visible_ids: set[int] = set()
        frames: list[dict] = []

        def _reveal(component: Any) -> None:
            if isinstance(component, Group):
                for child in component.children:
                    _reveal(child)
            elif component is not None:
                visible_ids.add(id(component))

        def _frame(
            partial: dict | None = None,
            traveling: dict | None = None,
            highlighted: dict | None = None,
            polarization_overlays: dict | None = None,
            polarization_caption: str = "",
            pulse_widths: dict | None = None,
            wave_colors: dict | None = None,
            wave_opacities: dict | None = None,
            wave_opacity_envelopes: dict | None = None,
            trail_windows: dict | None = None,
        ) -> dict:
            """Build one renderer frame state from the current visible set.

            ``pulse_widths``, ``wave_colors``, ``wave_opacities``,
            ``wave_opacity_envelopes`` and ``trail_windows`` are optional render
            hints used by 3D renderers; existing renderers ignore them.
            """

            return {
                "hidden_ids": all_ids - visible_ids,
                "partial_beams": partial or {},
                "traveling_waves": traveling or {},
                "highlight_levels": highlighted or {},
                "polarization_overlays": polarization_overlays or {},
                "polarization_caption": polarization_caption,
                "pulse_widths": pulse_widths or {},
                "wave_colors": wave_colors or {},
                "wave_opacities": wave_opacities or {},
                "wave_opacity_envelopes": wave_opacity_envelopes or {},
                "trail_windows": trail_windows or {},
            }

        # Opening blank frame
        frames.append(_frame())

        for step in self._steps:
            if step.kind == "show":
                _reveal(step.component)
                frames.append(_frame())

            elif step.kind == "trace":
                comp = step.component
                _reveal(comp)
                # Grow animation
                for i in range(1, step.trace_steps + 1):
                    fraction = i / step.trace_steps
                    partial: dict[int, float] = {
                        id(c): 1.0
                        for c in self.scene.walk()
                        if isinstance(c, (Beam, Route))
                        and id(c) in visible_ids
                        and c is not comp
                    }
                    partial[id(comp)] = fraction
                    frames.append(_frame(partial))

            elif step.kind == "pause":
                frames.append(_frame())

            elif step.kind == "wave_travel":
                comp = step.component
                _reveal(comp)
                if step.pulse_width is not None:
                    packet_length = max(min(float(step.pulse_width), 1.0), 1e-6)
                else:
                    packet_length = min(
                        0.22, max(0.08, 2.0 / max(step.trace_steps, 1))
                    )
                color = _resolve_wave_color(step.pulse_color, step.wavelength_nm)
                envelope = step.opacity_envelope or "constant"
                trail_total = (
                    step.trail_length
                    if step.trail_length is not None
                    else 3.0 * packet_length
                )
                trail_total = max(min(float(trail_total), 1.0), 0.0)

                steps_n = max(int(step.trace_steps), 1)
                for i in range(1, steps_n + 1):
                    head = i / steps_n
                    tail = max(0.0, head - packet_length)
                    pulse_widths = {id(comp): packet_length}
                    wave_colors = {id(comp): color} if color else {}
                    if step.fade:
                        progress = i / steps_n
                        opacity = max(0.0, 1.0 - progress)
                    else:
                        opacity = 1.0
                    wave_opacities = {id(comp): opacity}
                    wave_envelopes = {id(comp): envelope}
                    trail_windows: dict[int, tuple[float, float]] = {}
                    if step.trail and trail_total > 0.0:
                        trail_tail = max(0.0, tail - trail_total)
                        trail_windows[id(comp)] = (trail_tail, tail)
                    frames.append(
                        _frame(
                            traveling={id(comp): (tail, head)},
                            pulse_widths=pulse_widths,
                            wave_colors=wave_colors,
                            wave_opacities=wave_opacities,
                            wave_opacity_envelopes=wave_envelopes,
                            trail_windows=trail_windows,
                        )
                    )

            elif step.kind == "cavity_power":
                comp = step.component
                _reveal(comp)
                for i in range(step.trace_steps):
                    phase = i / max(step.trace_steps - 1, 1)
                    strength = 0.2 + 0.8 * math.sin(math.pi * phase)
                    frames.append(_frame(highlighted={id(comp): strength}))

            elif step.kind == "absorb":
                comp = step.component
                _reveal(comp)
                packet_length = min(0.22, max(0.08, 2.0 / max(step.trace_steps, 1)))
                for i in range(1, step.trace_steps + 1):
                    progress = i / step.trace_steps
                    tail = min(1.0, 1.0 - packet_length * (1.0 - progress))
                    frames.append(_frame(traveling={id(comp): (tail, 1.0)}))
                frames.append(_frame())

            elif step.kind == "polarization":
                comp = step.component
                if comp is not None:
                    _reveal(comp)
                highlighted = {}
                if comp is not None:
                    highlighted[id(comp)] = 1.0
                pol_overlays: dict[int, Any] = {}
                if step.stokes is not None and comp is not None:
                    pol_overlays[id(comp)] = step.stokes
                caption = step.caption or step.polarization_annotation
                frames.append(
                    _frame(
                        highlighted=highlighted,
                        polarization_overlays=pol_overlays,
                        polarization_caption=caption,
                    )
                )

        return frames


def animate_polarization(
    scene,
    components,
    *,
    caption: str = "",
    wavelength_nm: float = 633.0,
    stokes_in=None,
    unpolarized: bool = False,
    dwell: float = 1.5,
) -> AnimationTimeline:
    """Build a polarization tutoring timeline from Mueller/Stokes trace steps."""

    from optodraw.core.polarization import (
        StokesVector,
        stokes_annotation_stub,
        trace_stokes_through,
    )

    tl = scene.timeline() if hasattr(scene, "timeline") else scene
    state = (
        StokesVector.unpolarized()
        if unpolarized and stokes_in is None
        else (
            stokes_in
            if isinstance(stokes_in, StokesVector)
            else StokesVector.linear_horizontal()
            if stokes_in is None
            else StokesVector(*stokes_in)
        )
    )

    if caption:
        tl.polarization(
            None,
            stokes=state,
            caption=caption,
            annotation=stokes_annotation_stub(state),
            dwell=dwell,
        )

    for component in components:
        result = trace_stokes_through(
            [component],
            state,
            wavelength_nm=wavelength_nm,
        )
        state = result.stokes
        component_type = getattr(component, "component_type", component.__class__.__name__)
        annotation = stokes_annotation_stub(state)
        step_caption = f"{component_type}: {annotation}"
        if result.dual_outputs is not None:
            p_frac = result.dual_outputs["p"]["power_fraction"]
            s_frac = result.dual_outputs["s"]["power_fraction"]
            step_caption = (
                f"{component_type}: p={p_frac:.2f}, s={s_frac:.2f} ({annotation})"
            )
        tl.polarization(
            component,
            stokes=state,
            caption=step_caption,
            annotation=annotation,
            dwell=dwell,
        )

    return tl
