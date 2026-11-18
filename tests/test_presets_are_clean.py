"""Every built-in preset must read like something a person laid out by hand.

Presets are the first thing a new user opens, and they drifted: couplers faced
away from the chain so routes looped around the far side of the die, a receiver's
signal and LO crossed on the way in, and a mesh grew off the right edge of its
own frame. These checks pin down what "clean" means so it cannot rot quietly.
"""

from __future__ import annotations

import math
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from optodraw.presets import PRESETS, build_preset  # noqa: E402

# the parameterized builders behind the Generate dialog AND the on-chip examples
_GENERATORS = {
    "ring_filter": lambda: __import__("optodraw", fromlist=["build_ring_filter"]).build_ring_filter(),
    "ring_filter_through": lambda: __import__("optodraw", fromlist=["build_ring_filter"]).build_ring_filter(add_drop=False),
    "mzm_mesh": lambda: __import__("optodraw", fromlist=["build_mzm_mesh"]).build_mzm_mesh(),
    "weight_mesh": lambda: __import__("optodraw", fromlist=["build_microring_weight_mesh"]).build_microring_weight_mesh(),
    "mzm_coupler_mesh": lambda: __import__("optodraw.layout", fromlist=["build_mzm_coupler_mesh"]).build_mzm_coupler_mesh(),
    "detector_readout": lambda: __import__("optodraw", fromlist=["build_detector_readout_chain"]).build_detector_readout_chain(),
    "modulator_drive": lambda: __import__("optodraw", fromlist=["build_modulator_drive_chain"]).build_modulator_drive_chain(),
}

_ROUTES = {"Route", "WaveguideRoute", "FiberRoute", "MetalRoute"}
_NOT_A_PART = _ROUTES | {"Beam", "FocusingBeam", "Group", "Grid"}


def _routes(scene):
    for node in scene.walk():
        if getattr(node, "component_type", "") in _ROUTES:
            points = [(float(p[0]), float(p[1])) for p in node.resolve_points()]
            if len(points) >= 2:
                yield node, points


def _overlap(a0: float, a1: float, b0: float, b1: float, pad: float = 1.0) -> bool:
    lo_a, hi_a = (a0, a1) if a0 <= a1 else (a1, a0)
    lo_b, hi_b = (b0, b1) if b0 <= b1 else (b1, b0)
    return min(hi_a, hi_b) - max(lo_a, lo_b) > pad


def _point_on_segment(px: float, py: float, x1: float, y1: float, x2: float, y2: float, tol: float = 0.6) -> bool:
    """True if (px, py) sits on the open segment, not at an endpoint."""

    dx, dy = x2 - x1, y2 - y1
    length = math.hypot(dx, dy)
    if length < 1e-6:
        return False
    if math.hypot(px - x1, py - y1) < tol or math.hypot(px - x2, py - y2) < tol:
        return False
    t = ((px - x1) * dx + (py - y1) * dy) / (length * length)
    if t <= 0.0 or t >= 1.0:
        return False
    qx, qy = x1 + t * dx, y1 + t * dy
    return math.hypot(px - qx, py - qy) < tol


def _stacked_electrical(scene) -> list[str]:
    """Return pairs of electrical traces that share a collinear overlap.

    Manhattan mid_x averaging puts several nets on one vertical. The usual
    segment-crossing test reports 0 hits because the traces never leave that
    line. A T-join onto another net's run is the same fault: the traces short.
    """

    lines = []
    for node, points in _routes(scene):
        if getattr(node, "kind", None) != "electrical":
            continue
        lines.append((getattr(node, "label", None) or node.component_type, points))
    hits: list[str] = []
    for i, (left_name, left) in enumerate(lines):
        for right_name, right in lines[i + 1 :]:
            for (x1, y1), (x2, y2) in zip(left, left[1:]):
                for (x3, y3), (x4, y4) in zip(right, right[1:]):
                    vertical = abs(x1 - x2) < 0.5 and abs(x3 - x4) < 0.5 and abs(x1 - x3) < 0.5
                    horizontal = abs(y1 - y2) < 0.5 and abs(y3 - y4) < 0.5 and abs(y1 - y3) < 0.5
                    if vertical and _overlap(y1, y2, y3, y4):
                        hits.append(f"{left_name}/{right_name} x={x1:.1f}")
                    if horizontal and _overlap(x1, x2, x3, x4):
                        hits.append(f"{left_name}/{right_name} y={y1:.1f}")
            for px, py in left:
                for (x3, y3), (x4, y4) in zip(right, right[1:]):
                    if _point_on_segment(px, py, x3, y3, x4, y4):
                        hits.append(f"{left_name}/{right_name} T at ({px:.1f},{py:.1f})")
            for px, py in right:
                for (x1, y1), (x2, y2) in zip(left, left[1:]):
                    if _point_on_segment(px, py, x1, y1, x2, y2):
                        hits.append(f"{right_name}/{left_name} T at ({px:.1f},{py:.1f})")
    return hits


@pytest.mark.parametrize("name", sorted(PRESETS))
def test_preset_routes_are_direct(name: str):
    """A link should be a hop between two ports, not a trip around the scene. A loop round the outside of the
    other parts (a feedback bus, a sync cable) is the one long route a figure may have, as the gate allows."""

    from optodraw.check import _round_the_rest

    scene = build_preset(name)
    parts = [node for node in scene.walk() if getattr(node, "component_type", "") not in _NOT_A_PART | {"", "Scene"}]
    for node, points in _routes(scene):
        span = math.dist(points[0], points[-1])
        if span < 1e-6:
            continue
        length = sum(math.dist(a, b) for a, b in zip(points, points[1:]))
        others = [part.drawn_box() for part in parts if part is not node.start_component and part is not node.end_component]
        assert length <= span * 2.2 or _round_the_rest(points, others), (
            f"{name}: {node.component_type} detours {length / span:.1f}x")


def test_coherent_receiver_electrical_traces_do_not_stack():
    hits = _stacked_electrical(build_preset("coherent_receiver_chip"))
    assert not hits, hits


def test_the_ring_filter_ends_every_spare_port():
    """The add port and the taps' spare ports end in terminators: no light leaves the chip unseen."""

    from optodraw.core.routing import Route

    scene = build_preset("ring_resonator_chip")
    ended = {(id(node.start_component), node.start_port) for node in scene.walk()
             if isinstance(node, Route) and getattr(node.end_component, "component_type", "") == "Terminator"}
    for part in scene.walk():
        if getattr(part, "component_type", "") == "TapCoupler":
            linked = {(id(node.start_component), node.start_port) for node in scene.walk() if isinstance(node, Route)}
            linked |= {(id(node.end_component), node.end_port) for node in scene.walk() if isinstance(node, Route)}
            assert all((id(part), port) in linked for port in ("o1", "o2", "o3", "o4")), part.label
    filters = [part for part in scene.walk() if getattr(part, "component_type", "") == "CoupledRingFilter"]
    assert len(filters) == 1 and (id(filters[0]), "o3") in ended                  # the add port


