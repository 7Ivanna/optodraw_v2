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


@pytest.mark.parametrize("name", sorted(PRESETS))
def test_preset_content_stays_inside_its_frame(name: str):
    scene = build_preset(name)
    half_w, half_h = float(scene.width) / 2.0 + 1.0, float(scene.height) / 2.0 + 1.0
    cx, cy = getattr(scene, "frame_center", (0.0, 0.0))                 # fit_frame frames the content where it is
    for node in scene.walk():
        kind = getattr(node, "component_type", "")
        if not kind or kind in _NOT_A_PART:
            continue
        position = node.world_position
        assert abs(position.x - cx) <= half_w and abs(position.y - cy) <= half_h, (
            f"{name}: {kind} at ({position.x:.0f}, {position.y:.0f}) is outside the {scene.width}x{scene.height} frame"
        )
    for node, points in _routes(scene):
        for x, y in points:
            assert abs(x - cx) <= half_w and abs(y - cy) <= half_h, f"{name}: route leaves the frame at ({x:.0f}, {y:.0f})"


def _generated(name: str):
    built = _GENERATORS[name]()
    return built["scene"] if isinstance(built, dict) else built


@pytest.mark.parametrize("name", sorted(_GENERATORS))
def test_generated_layouts_are_direct(name: str):
    """Generators feed the Generate dialog and the on-chip examples alike. Their
    cells must be pitched wider than their own footprints -- at the old fixed
    pitches, mesh cells overlapped and every link ran backwards."""

    for node, points in _routes(_generated(name)):
        span = math.dist(points[0], points[-1])
        if span < 1e-6:
            continue
        length = sum(math.dist(a, b) for a, b in zip(points, points[1:]))
        assert length <= span * 2.2, f"{name}: {node.component_type} detours {length / span:.1f}x"


@pytest.mark.parametrize("name", sorted(_GENERATORS))
def test_generated_cells_do_not_overlap(name: str):
    """Neighbouring cells must not sit inside one another."""

    scene = _generated(name)
    cells = [
        node for node in scene.walk()
        if getattr(node, "component_type", "") in {"MZM", "MicroringWeightBank"}
    ]
    for index, first in enumerate(cells):
        for second in cells[index + 1:]:
            a, b = first.world_position, second.world_position
            if abs(a.y - b.y) > 1.0:
                continue  # different rows never collide
            ports = first.ports()
            width = abs(float(ports["o3" if "o3" in ports else "o2"].center.x) - float(ports["o1"].center.x))
            assert abs(a.x - b.x) >= width, f"{name}: {first.component_type} cells overlap in x"


@pytest.mark.parametrize("name", sorted(_GENERATORS))
def test_manhattan_links_stay_on_axis(name: str):
    """A waveguide laid out manhattan-style must run along the axes. Pushing a
    corner clear of a device body used to leave the neighbouring leg diagonal,
    so mesh links cut across the banks they were meant to skirt."""

    scene = _generated(name)
    for node, points in _routes(scene):
        if getattr(node, "smooth", False) or getattr(node, "path_type", "") != "manhattan":
            continue  # smoothed corners are arcs by design; straight runs are direct by name
        for (x1, y1), (x2, y2) in zip(points, points[1:]):
            assert abs(x1 - x2) < 1e-6 or abs(y1 - y2) < 1e-6, (
                f"{name}: diagonal leg ({x1:.1f},{y1:.1f})->({x2:.1f},{y2:.1f})"
            )


@pytest.mark.parametrize("name", sorted(PRESETS))
def test_preset_routes_stay_attached_to_their_ports(name: str):
    """Routes drawn in the editor follow the parts they connect. Python-built
    scenes serialized their routes as bare point lists, so opening a preset gave
    you dead polylines: drag a component and its links stayed behind."""

    spec = build_preset(name).to_spec()
    routes = spec.get("routes", [])
    anchored = [r for r in routes if r.get("from") and r.get("to")]
    free = [r for r in routes if not (r.get("from") and r.get("to"))]
    assert not free, f"{name}: {len(free)}/{len(routes)} routes lost their port anchors"
    assert anchored or not routes


def test_moving_a_preset_component_drags_its_routes_along():
    from optodraw.app.session import EditorSession

    session = EditorSession(build_preset("ring_resonator_chip").to_spec())
    spec = session.spec
    ring = next(c for c in spec["components"] if c.get("label") == "5th-order filter")
    linked = [
        index for index, route in enumerate(spec["routes"])
        if ring["id"] in (route.get("from", [None])[0], route.get("to", [None])[0])
    ]
    assert linked, "the ring should be wired to something"

    def endpoints():
        built = session.scene()
        return [
            [tuple(round(float(v), 3) for v in point[:2]) for point in (r.resolve_points()[0], r.resolve_points()[-1])]
            for r in built.walk() if getattr(r, "component_type", "") in _ROUTES
        ]

    before = endpoints()
    session.move_component(ring["id"], center=[ring["center"][0], ring["center"][1] + 25.0])
    after = endpoints()
    assert before != after, "the ring moved but its links did not follow"


@pytest.mark.parametrize("name", sorted(PRESETS))
def test_preset_parts_sit_on_whole_units(name: str):
    """Positions should read as short numbers in the inspector: a figure places parts on ports, foci and ray
    angles, so a position may have hundredths, never a long tail. A mirror or a splitter placed by ``aim`` is held
    by the point where the beam meets it (its face sits half a substrate off its centre), so that point counts."""

    from optodraw.core.beam import Beam, beam_point
    from optodraw.core.routing import Route

    for part in build_preset(name).root.children:
        if isinstance(part, (Beam, Route)) or not hasattr(part, "transform"):
            continue
        ports = part.ports() if callable(getattr(part, "ports", None)) else {}
        reflecting = "io" if "io" in ports else ("refl" if "refl" in ports and hasattr(part, "beam_point") else None)
        points = [part.transform.position] + ([beam_point(part, reflecting)] if reflecting is not None else [])

        def whole(point):
            return all(abs(float(v) * 100.0 - round(float(v) * 100.0)) < 1e-6 for v in (point.x, point.y))

        assert any(whole(point) for point in points), f"{name}: {part.label} at {points}"


class TestPresetsFitTheirFrame:
    """Nothing a preset places may fall outside the figure it exports.

    The weight-bank chip sizes itself from ring counts and delay lengths, and
    its hand-picked width had drifted 7 units too narrow — enough to cut the
    balanced detectors in half on the right edge of every export.
    """

    def test_no_preset_places_a_component_outside_its_frame(self):
        from optodraw.presets import build_preset, list_presets

        clipped = []
        for name in list_presets():
            scene = build_preset(name)
            min_x, min_y, max_x, max_y = scene.content_bounds()
            cx, cy = scene.frame_center                          # the frame stands round the content, where it is
            over_x = max(max_x - cx - scene.width / 2.0, cx - scene.width / 2.0 - min_x)
            over_y = max(max_y - cy - scene.height / 2.0, cy - scene.height / 2.0 - min_y)
            if over_x > 0.5 or over_y > 0.5:
                clipped.append(f"{name} (x by {over_x:.1f}, y by {over_y:.1f})")
        assert not clipped, "content outside the frame: " + ", ".join(clipped)

    def test_fit_frame_wraps_the_content_it_is_given(self):
        from optodraw import Lens, Scene

        scene = Scene(width=40, height=40)
        scene.add(Lens(center=(120, 0), aperture=20.0))
        scene.fit_frame(margin=10.0)
        min_x, _, max_x, _ = scene.content_bounds()
        cx = scene.frame_center[0]                           # the frame stands round the content, where it is
        assert cx + scene.width / 2.0 >= max_x + 9.0
        assert cx - scene.width / 2.0 <= min_x - 0.0
        assert scene.width % 10 == 0  # round numbers, not 263.4


class TestNoPortDrivesTwoLinks:
    """One waveguide port, one link.

    A port with two routes leaving it is a splitter that is not there: the
    weight-bank chip fanned one bank output into both balanced detectors, and
    drew the two waveguides exactly on top of each other.
    """

    def test_no_preset_fans_one_port_into_two_routes(self):
        from optodraw.presets import build_preset, list_presets

        route_types = {"Route", "WaveguideRoute", "FiberRoute", "MetalRoute"}
        shared = []
        for name in list_presets():
            scene = build_preset(name)
            seen: dict[tuple, int] = {}
            for node in scene.walk():
                if getattr(node, "component_type", "") not in route_types:
                    continue
                for component, port in (
                    (getattr(node, "start_component", None), getattr(node, "start_port", None)),
                    (getattr(node, "end_component", None), getattr(node, "end_port", None)),
                ):
                    if component is None or port is None:
                        continue
                    if getattr(component, "component_type", "") in {"ElectricalPad", "BondPad"}:
                        continue  # electrical nets legitimately fan out
                    key = (id(component), port)
                    seen[key] = seen.get(key, 0) + 1
                    if seen[key] == 2:
                        label = getattr(component, "label", "") or component.component_type
                        shared.append(f"{name}: {label}.{port}")
        assert not shared, "ports driving more than one link: " + ", ".join(shared)


class TestEveryPresetSurvivesTheEditor:
    """A preset has to load in the app, not only build in Python.

    The weight-bank chip drew its own star coupler, weight bank, delay spiral
    and balanced detector. None were registered, so the scene built fine in
    Python and then failed the moment it was written to a spec and read back —
    which is exactly what picking the preset in the editor does. It answered
    500, and a saved copy could not be reopened either.
    """

    def test_every_preset_round_trips_through_a_spec(self):
        from optodraw.presets import build_preset, list_presets
        from optodraw.schema import scene_from_spec

        def count(entries):                                    # a group's parts are in its children
            return sum(1 + count(entry.get("children", [])) for entry in entries)

        for name in list_presets():
            spec = build_preset(name).to_spec()
            restored = scene_from_spec(spec)  # raises on an unregistered type
            assert len(list(restored.walk())) == count(spec["components"]) + len(
                spec.get("beams", [])) + len(spec.get("routes", []))

    def test_every_component_a_preset_places_is_in_the_registry(self):
        from optodraw.presets import build_preset, list_presets
        from optodraw.registry import component_registry

        registry = component_registry()
        missing = set()
        for name in list_presets():
            for node in build_preset(name).walk():
                ctype = getattr(node, "component_type", "")
                if ctype and ctype not in registry and ctype not in {"Group", "Beam", "Route",
                                                                     "WaveguideRoute", "FiberRoute",
                                                                     "MetalRoute", "FocusingBeam"}:
                    missing.add(f"{name}: {ctype}")
        assert not missing, "unregistered components in presets: " + ", ".join(sorted(missing))


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


def test_modulator_drive_electrical_traces_do_not_stack():
    from optodraw import build_modulator_drive_chain

    hits = _stacked_electrical(build_modulator_drive_chain()["scene"])
    assert not hits, hits
