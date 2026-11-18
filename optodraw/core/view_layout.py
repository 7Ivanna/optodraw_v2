"""Display spacing for one scene, without changing its source geometry."""

from __future__ import annotations

from copy import deepcopy
import math

from optodraw.core.component import Component, LINK_TYPES
from optodraw.core.transform import Vec3


def validate_layout(layout):
    """Return independent, JSON-compatible settings for each requested view."""
    if not isinstance(layout, dict):
        raise ValueError("layout must map '1d', '2d', or '3d' to settings")
    result = {}
    for mode, settings in layout.items():
        if mode not in {"1d", "2d", "3d"} or not isinstance(settings, dict):
            raise ValueError("layout must map '1d', '2d', or '3d' to settings")
        unknown = set(settings) - {"spacing", "clearance"}
        if unknown:
            raise ValueError(f"Unknown {mode} layout settings: {sorted(unknown)}")
        spacing = settings.get("spacing", 1.0)
        if spacing == "auto":
            if mode != "3d":
                raise ValueError("Automatic spacing is available only for 3D")
        else:
            spacing = float(spacing)
            if not math.isfinite(spacing) or spacing <= 0:
                raise ValueError("View spacing must be finite and positive")
        clearance = float(settings.get("clearance", 5.0))
        if not math.isfinite(clearance) or clearance < 0:
            raise ValueError("View clearance must be finite and nonnegative")
        result[mode] = {"spacing": spacing, "clearance": clearance}
    return result


def automatic_spacing(scene, clearance):
    """Estimate separation using drawing footprints and the 7.5-unit pedestal radius.

    This is a floor-layout estimate, not a mesh collision or optical check.
    """
    from optodraw.layout import estimate_component_bounds

    discs = []
    for part in scene._parts():
        left, bottom, right, top = estimate_component_bounds(part)
        radius = max(math.hypot(x, y) for x in (left, right) for y in (bottom, top))
        if getattr(part, "base_mount", "post") != "none":
            radius = max(radius, 7.5)
        discs.append((part, part.world_position, radius))
    spacing = 1.0
    for i, (part, point, radius) in enumerate(discs):
        for other, end, other_radius in discs[:i]:
            distance = math.hypot(point.x - end.x, point.y - end.y)
            if distance < 1e-9:
                raise ValueError(
                    f"Automatic spacing cannot separate coincident parts: "
                    f"{part.label or part.component_type}, {other.label or other.component_type}"
                )
            spacing = max(spacing, (radius + other_radius + clearance) / distance)
    return spacing


def _respace_route(route, spacing):
    """A route between moved parts: routed again from its request with its lanes spread by ``spacing``, or,
    with no request, its corners spread and its two ends put back on their ports."""

    from optodraw.core.routing import route_ports

    request = getattr(route, "_request", None)
    if request is not None:
        port1, port2, kwargs = request
        kwargs = dict(kwargs)
        if kwargs.get("steps"):
            kwargs["steps"] = [{key: value * spacing for key, value in step.items()} for step in kwargs["steps"]]
        route.points = route_ports(port1, port2, **kwargs).points
        return
    points = [Vec3(point.x * spacing, point.y * spacing, point.z) for point in route.points]
    for index, (part, port) in ((0, (route.start_component, route.start_port)),
                                (-1, (route.end_component, route.end_port))):
        if part is not None and port in part.world_ports():
            points[index] = part.world_ports()[port].center
    route.points = points


def display_scene(scene, mode):
    """Resolve display positions on a copy. Beam references remain attached to copied parts."""
    settings = scene.metadata.get("view_layout", {}).get(mode, {})
    spacing = settings.get("spacing", 1.0)
    if spacing == 1.0:
        return scene
    if scene.platform != "free_space":
        raise ValueError("Display spacing currently supports free-space scenes only")
    if spacing == "auto":
        spacing = automatic_spacing(scene, settings.get("clearance", 5.0))
    if spacing == 1.0:
        return scene
    result = deepcopy(scene)
    nodes = list(result.walk())
    # Save world positions before changing any parent. Walk order is parent first.
    positions = [(node, node.world_position) for node in nodes]
    for node, original in positions:
        if node.component_type in LINK_TYPES:
            continue
        target = Vec3(original.x * spacing, original.y * spacing, original.z)
        if node._parent is None:
            node.transform.position = target
        else:
            import numpy as np

            local = np.linalg.solve(node._parent.world_transform.to_matrix_4x4(),
                                    [target.x, target.y, target.z, 1.0])
            node.transform.position = Vec3(*local[:3])

    def anchor(value):
        if isinstance(value, Component):
            return value
        if isinstance(value, Vec3):
            return Vec3(value.x * spacing, value.y * spacing, value.z)
        if isinstance(value, (tuple, list)):
            if len(value) == 2 and isinstance(value[0], Component):
                return value
            return (value[0] * spacing, value[1] * spacing, *value[2:])
        raise TypeError(f"Unsupported display anchor: {type(value).__name__}")

    for node in nodes:
        if node.component_type == "Beam":
            node.anchors = [anchor(value) for value in node.anchors]
        elif node.component_type == "FocusingBeam":
            node.anchor1, node.anchor2 = anchor(node.anchor1), anchor(node.anchor2)
        elif node.component_type in LINK_TYPES:
            _respace_route(node, spacing)
    # A derived scene is already laid out; do not expand it again on export.
    result.metadata.pop("view_layout", None)
    result.metadata["resolved_view_layout"] = {"view": mode, "spacing": spacing}
    result.fit_frame()
    return result
