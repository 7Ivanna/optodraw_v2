"""Shared animation frame states for the GIF and Manim renderers.

Both renderers animate the same way in their automatic modes: reveal solid
components one by one, then reveal beams — either whole (``build_up``) or
grown step by step (``beam_trace``). Each frame is a plain dict consumed by
``SvgRenderer``::

    {"hidden_ids": set[int], "partial_beams": {id(beam): fraction}}

The timeline-driven paths (``AnimationTimeline._to_frame_states``) are richer
and keep their own builder; this module covers only the automatic modes both
renderers used to implement separately (with different beam-trace step counts
and different Group/Grid handling — now unified).
"""

from __future__ import annotations

from optodraw.components.misc import Grid
from optodraw.core.beam import Beam
from optodraw.core.component import Group
from optodraw.core.routing import Route

#: Frames used to grow one beam in ``beam_trace`` mode.
BEAM_TRACE_STEPS = 12


def collect_frame_components(scene) -> tuple[list, list]:
    """Split scene nodes into (solids, beams_and_routes).

    ``Group`` containers and ``Grid`` backgrounds are not animated
    components: the grid stays visible throughout and groups only
    structure the scene.
    """

    solids: list = []
    beams: list = []
    for node in scene.walk():
        if isinstance(node, (Group, Grid)):
            continue
        if isinstance(node, (Beam, Route)):
            beams.append(node)
        else:
            solids.append(node)
    return solids, beams


def build_auto_frames(scene, mode: str, *, trace_steps: int = BEAM_TRACE_STEPS) -> list[dict]:
    """Return ordered frame-state dicts for an automatic animation.

    ``mode`` is ``"build_up"`` (each beam appears whole) or ``"beam_trace"``
    (each beam grows over ``trace_steps`` frames). Unknown modes fall back to
    ``build_up`` so callers that pass animation_style strings through keep
    rendering instead of raising.
    """

    if mode == "beam_trace" and (
        isinstance(trace_steps, bool) or not isinstance(trace_steps, int) or trace_steps < 1
    ):
        raise ValueError("trace_steps must be a positive integer")

    solids, beams = collect_frame_components(scene)

    all_ids = {id(c) for c in solids} | {id(b) for b in beams}
    visible_ids: set[int] = set()
    frames: list[dict] = []

    def _frame(partial: dict | None = None) -> dict:
        return {"hidden_ids": all_ids - visible_ids, "partial_beams": partial or {}}

    # Opening blank frame (only the static background/grid is visible)
    frames.append(_frame())

    # Reveal solid components one by one
    for comp in solids:
        visible_ids.add(id(comp))
        frames.append(_frame())

    # Reveal beams
    if mode == "beam_trace":
        for beam in beams:
            visible_ids.add(id(beam))
            # Grow this beam over trace_steps frames
            for step in range(1, trace_steps + 1):
                fraction = step / trace_steps
                partial: dict[int, float] = {
                    id(b): 1.0
                    for b in beams
                    if id(b) in visible_ids and b is not beam
                }
                partial[id(beam)] = fraction
                frames.append(_frame(partial))
    else:
        # build_up (and anything unrecognized): each beam appears in full
        for beam in beams:
            visible_ids.add(id(beam))
            frames.append(_frame())

    return frames
