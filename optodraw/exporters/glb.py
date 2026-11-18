"""Deterministic scene → GLB export (Blender-friendly).

The browser ``GLTFExporter`` works for valid geometry, but real GDS imports can
trip it up (degenerate polygons, async edge cases). This server-side path builds
the GLB straight from the scene geometry with trimesh, so the result is always a
clean, spec-valid binary glTF that Blender opens.

GDS dies are exported precisely (one extruded mesh per polygon, with the layer's
colour, z-offset and thickness). Other components fall back to a footprint box so
the surrounding setup is still present.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

# glTF is Y-up; optodraw world is Z-up (x right, y "north", z height). This maps a
# world point (x, y, z) -> glTF (x, z, -y), matching the Three.js viewer.
_AXIS_SWAP = np.array(
    [[1, 0, 0, 0], [0, 0, 1, 0], [0, -1, 0, 0], [0, 0, 0, 1]], dtype=float
)


def _hex_to_rgba(color: str, opacity: float = 1.0) -> list[int]:
    color = (color or "#888888").lstrip("#")
    if len(color) == 3:
        color = "".join(c * 2 for c in color)
    try:
        r, g, b = (int(color[i : i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        r, g, b = 136, 136, 136
    return [r, g, b, int(max(0.0, min(1.0, opacity)) * 255)]


def _placement(node: Any, z_lift: float = 0.0) -> np.ndarray:
    """World placement (rotate about z, translate) for a node, plus a z lift."""

    wt = node.world_transform
    ang = math.radians(wt.rotation_deg.z)
    c, s = math.cos(ang), math.sin(ang)
    mat = np.array(
        [
            [c, -s, 0, wt.position.x],
            [s, c, 0, wt.position.y],
            [0, 0, 1, wt.position.z + z_lift],
            [0, 0, 0, 1],
        ],
        dtype=float,
    )
    return _AXIS_SWAP @ mat


def _gds_meshes(node: Any, issues: list[str] | None = None) -> list[Any]:
    import trimesh
    from shapely.geometry import Polygon

    if issues is None:
        issues = []
    polys_by_spec = getattr(node, "_polygons_by_spec", None)
    if not polys_by_spec:
        return []
    records = {r["key"]: r for r in node.layer_records()}
    exaggeration = getattr(node, "z_exaggeration", 1.0) or 1.0
    process_context = bool(getattr(node, "process_context", False))
    meshes: list[Any] = []
    for spec, polygons in polys_by_spec.items():
        record = records.get(f"{spec[0]}/{spec[1]}", {})
        if not record.get("visible", True):
            continue
        # with process context on, etch openings are carved from the oxide (below)
        if process_context and record.get("material") == "air":
            continue
        # a layer with no height assigned is left out, as in the 3D view: never a slab at a made-up height
        if record.get("thickness") is None or record.get("z") is None:
            continue
        z = float(record["z"]) * exaggeration
        thickness = max(float(record["thickness"]) * exaggeration, 1e-4)
        rgba = _hex_to_rgba(record.get("color", "#888888"), float(record.get("opacity", 1.0)))
        for polygon_index, polygon in enumerate(polygons):
            if len(polygon) < 3:
                issues.append(f"layer {spec[0]}/{spec[1]} polygon {polygon_index}: fewer than three points")
                continue
            try:
                shape = Polygon(polygon)
                if not shape.is_valid:
                    shape = shape.buffer(0)  # heal self-intersections (common in real GDS)
            except Exception as error:
                issues.append(f"layer {spec[0]}/{spec[1]} polygon {polygon_index}: {error}")
                continue
            if shape.is_empty or shape.area <= 0:
                issues.append(f"layer {spec[0]}/{spec[1]} polygon {polygon_index}: empty after repair")
                continue
            for geom in getattr(shape, "geoms", [shape]):
                try:
                    mesh = trimesh.creation.extrude_polygon(geom, thickness)
                except Exception as error:
                    issues.append(f"layer {spec[0]}/{spec[1]} polygon {polygon_index}: extrusion failed: {error}")
                    continue
                mesh.apply_transform(_placement(node, z_lift=z))
                mesh.visual.face_colors = rgba
                meshes.append(mesh)

    # synthesized BOX / top-oxide / handle (with OX_OPEN + deep-trench holes), so the
    # exported GLB carries the full dielectric stack for headless Blender polishing
    if process_context and hasattr(node, "process_context_regions"):
        for poly, za, zb, material in node.process_context_regions(exaggeration):
            try:
                mesh = trimesh.creation.extrude_polygon(poly, max(zb - za, 1e-4))
            except Exception as error:
                issues.append(f"process context region: extrusion failed: {error}")
                continue
            mesh.apply_transform(_placement(node, z_lift=za))
            mesh.visual.face_colors = _hex_to_rgba(material.get("color", "#bcd4ea"), float(material.get("opacity", 1.0)))
            meshes.append(mesh)
    return meshes


def _geometry2d_meshes(node: Any, issues: list[str] | None = None) -> list[Any]:
    """Build 3D meshes by extruding a component's 2D geometry, so non-GDS parts keep
    their real outline (lens, beamsplitter diamond, MMI body, …) instead of a generic
    box. Uses the same local→world placement as the GDS path."""

    import trimesh
    from shapely.affinity import scale as _affine_scale
    from shapely.geometry import LineString, Point, Polygon

    if issues is None:
        issues = []
    try:
        geo = node.geometry_2d()
    except Exception as error:
        issues.append(f"geometry_2d failed: {error}")
        return []
    if not geo:
        return []
    thickness = max(float(
        getattr(node, "chip_thickness", 0)
        or getattr(node, "thickness", 0)
        or getattr(node, "box_size", 0)
        or 2.0
    ), 1e-4)
    meshes: list[Any] = []

    def _emit(shape: Any, color: str, opacity: float) -> None:
        if shape.is_empty or shape.area <= 0:
            return
        if not shape.is_valid:
            shape = shape.buffer(0)
        for geom in getattr(shape, "geoms", [shape]):
            try:
                mesh = trimesh.creation.extrude_polygon(geom, thickness)
            except Exception as error:
                issues.append(f"2D {geom.geom_type} extrusion failed: {error}")
                continue
            mesh.apply_transform(_placement(node, z_lift=0.0))
            mesh.visual.face_colors = _hex_to_rgba(color, opacity)
            meshes.append(mesh)

    def _walk(g: dict[str, Any]) -> None:
        gtype = g.get("type")
        if gtype == "group":
            for child in g.get("children", []):
                _walk(child)
            return
        opacity = float(g.get("opacity", 1.0) or 1.0)
        if gtype in {"line", "polyline"}:
            stroke = g.get("stroke")
            stroke_width = float(g.get("stroke_width", 0.0) or 0.0)
            if not stroke or stroke == "none" or stroke_width <= 0:
                return
            if gtype == "line":
                points = [(g["x1"], g["y1"]), (g["x2"], g["y2"])]
            else:
                points = [(p[0], p[1]) for p in g.get("points", [])]
                if g.get("closed") and len(points) > 2 and points[0] != points[-1]:
                    points.append(points[0])
            if len(points) >= 2:
                _emit(LineString(points).buffer(stroke_width / 2.0, cap_style=2, join_style=1), stroke, opacity)
            return
        if gtype == "circle" and g.get("fill") in (None, "none"):
            stroke = g.get("stroke")
            stroke_width = float(g.get("stroke_width", 0.0) or 0.0)
            radius = float(g.get("r", 0.0) or 0.0)
            if stroke and stroke != "none" and stroke_width > 0 and radius > 0:
                center = Point(g.get("cx", 0.0), g.get("cy", 0.0))
                ring = center.buffer(radius + stroke_width / 2.0, resolution=48)
                inner_radius = radius - stroke_width / 2.0
                if inner_radius > 0:
                    ring = ring.difference(center.buffer(inner_radius, resolution=48))
                _emit(ring, stroke, opacity)
            return
        fill = g.get("fill")
        if not fill or fill == "none":  # only filled shapes become solids
            return
        if gtype == "rect":
            cx, cy, w, h = g.get("cx", 0.0), g.get("cy", 0.0), g["w"], g["h"]
            _emit(Polygon([(cx - w / 2, cy - h / 2), (cx + w / 2, cy - h / 2), (cx + w / 2, cy + h / 2), (cx - w / 2, cy + h / 2)]), fill, opacity)
        elif gtype == "polygon":
            pts = [(p[0], p[1]) for p in g.get("points", [])]
            if len(pts) >= 3:
                _emit(Polygon(pts), fill, opacity)
        elif gtype == "circle":
            _emit(Point(g.get("cx", 0.0), g.get("cy", 0.0)).buffer(g["r"], resolution=24), fill, opacity)
        elif gtype == "ellipse":
            unit = Point(g.get("cx", 0.0), g.get("cy", 0.0)).buffer(1.0, resolution=24)
            _emit(_affine_scale(unit, g["rx"], g["ry"]), fill, opacity)
        # Text and unfilled paths have no solid geometry here.

    _walk(geo)
    return meshes


def _geometry3d_meshes(node: Any) -> tuple[list[Any], str | None]:
    """Export supported chip solids in the same local frame as the browser."""

    import trimesh
    from shapely.geometry import Polygon

    try:
        geometry = node.geometry_3d()
    except Exception as error:
        return [], f"geometry_3d failed: {error}"
    if not isinstance(geometry, dict):
        return [], "no 3D geometry"

    world = node.world_transform
    if abs(world.rotation_deg.x) > 1e-9 or abs(world.rotation_deg.y) > 1e-9:
        return [], "non-planar component rotation"
    angle = math.radians(world.rotation_deg.z)
    c, s = math.cos(angle), math.sin(angle)
    placement = np.eye(4)
    placement[:3, :3] = [[c, 0, s], [0, 1, 0], [-s, 0, c]]
    placement[:3, 3] = [world.position.x, world.position.z, -world.position.y]
    mirror = np.diag([
        -1.0 if getattr(node, "flip_horizontal", False) else 1.0,
        1.0,
        -1.0 if getattr(node, "flip_vertical", False) else 1.0,
        1.0,
    ])
    placement = placement @ mirror
    x_to_y = np.eye(4)
    x_to_y[1:3, 1:3] = [[0, 1], [-1, 0]]
    meshes: list[Any] = []

    def walk(part: dict[str, Any], parent: np.ndarray) -> None:
        shape = part.get("shape")
        if shape not in {"group", "box", "cylinder", "extruded_polygon"}:
            raise ValueError(f"unsupported 3D shape {shape!r}")
        position = part.get("position", [0.0, 0.0, 0.0])
        rotation = part.get("rotation", [0.0, 0.0, 0.0])
        scale = part.get("scale", [1.0, 1.0, 1.0])
        if len(position) != 3 or len(rotation) != 3 or len(scale) != 3:
            raise ValueError(f"invalid {shape} transform")
        if abs(float(rotation[0])) > 1e-9 or abs(float(rotation[2])) > 1e-9:
            raise ValueError(f"unsupported {shape} rotation")
        yaw = float(rotation[1])
        cy, sy = math.cos(yaw), math.sin(yaw)
        local = np.eye(4)
        local[:3, :3] = [[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]]
        local[:3, 3] = [float(value) for value in position]
        local = parent @ local @ np.diag([float(value) for value in scale] + [1.0])

        solids: list[Any] = []
        if shape == "box":
            dimensions = [float(part[key]) for key in ("width", "height", "depth")]
            if min(dimensions) <= 0:
                raise ValueError("box has a non-positive dimension")
            solids.append(trimesh.creation.box(extents=dimensions))
        elif shape == "cylinder":
            radius, height = float(part["radius"]), float(part["height"])
            if radius <= 0 or height <= 0:
                raise ValueError("cylinder has a non-positive dimension")
            solid = trimesh.creation.cylinder(radius=radius, height=height, sections=32)
            solid.apply_transform(x_to_y)
            solids.append(solid)
        elif shape == "extruded_polygon":
            height = float(part["height"])
            points = [(float(p[0]), float(p[1])) for p in part.get("points", [])]
            holes = [[(float(p[0]), float(p[1])) for p in hole] for hole in part.get("holes", [])]
            if height <= 0 or len(points) < 3:
                raise ValueError("extruded polygon has invalid dimensions")
            polygon = Polygon(points, holes)
            if not polygon.is_valid:
                polygon = polygon.buffer(0)
            if polygon.is_empty:
                raise ValueError("extruded polygon is empty after repair")
            for region in getattr(polygon, "geoms", [polygon]):
                if region.area <= 0:
                    continue
                solid = trimesh.creation.extrude_polygon(region, height)
                solid.apply_transform(x_to_y)
                solids.append(solid)
            if not solids:
                raise ValueError("extruded polygon has no solid area")

        material = part.get("material") or {}
        rgba = _hex_to_rgba(material.get("color", "#888888"), float(material.get("opacity", 1.0)))
        for solid in solids:
            solid.apply_transform(local)
            solid.visual.face_colors = rgba
            meshes.append(solid)
        for child in part.get("children", []):
            if not isinstance(child, dict):
                raise ValueError("3D child is not a geometry object")
            walk(child, local)

    try:
        walk(geometry, placement)
    except Exception as error:
        return [], str(error)
    return (meshes, None) if meshes else ([], "no supported 3D solids")


def _footprint_box(node: Any) -> Any | None:
    """A small box approximating a non-GDS component's footprint."""

    import trimesh

    width = float(getattr(node, "aperture", 0) or getattr(node, "length", 0) or 6.0)
    width = max(width, 2.0)
    height = float(getattr(node, "thickness", 0) or 2.0)
    box = trimesh.creation.box(extents=[width, width, max(height, 1.0)])
    box.apply_transform(_placement(node, z_lift=max(height, 1.0) / 2))
    box.visual.face_colors = _hex_to_rgba(getattr(node, "color", "#9aa6b2"), 1.0)
    return box


def _chip_route_meshes(node: Any) -> list[Any]:
    """Extrude a planar chip route as a strip rather than a round tube."""

    import trimesh
    from shapely.geometry import LineString

    points = []
    for point in node.resolve_points():
        coords = point.as_tuple() if hasattr(point, "as_tuple") else point
        points.append((float(coords[0]), float(coords[1]), float(coords[2]) if len(coords) > 2 else 0.0))
    if len(points) < 2:
        return []
    z_base = points[0][2]
    if any(abs(point[2] - z_base) > 1e-6 for point in points):
        raise ValueError("chip route is not planar")
    width = max(abs(float(getattr(node, "width", 0.5) or 0.5)), 0.05)
    outline = LineString([(x, y) for x, y, _ in points]).buffer(
        width / 2.0, cap_style=2, join_style=1
    )
    if not outline.is_valid:
        outline = outline.buffer(0)
    if outline.is_empty:
        return []
    thickness = 0.35 if getattr(node, "kind", "") == "electrical" else 0.22
    translation = np.eye(4)
    translation[2, 3] = z_base
    placement = _AXIS_SWAP @ translation
    color = _hex_to_rgba(getattr(node, "color", "#888888"), float(getattr(node, "opacity", 1.0)))
    meshes = []
    for region in getattr(outline, "geoms", [outline]):
        if region.area <= 0:
            continue
        mesh = trimesh.creation.extrude_polygon(region, thickness)
        mesh.apply_transform(placement)
        mesh.visual.face_colors = color
        meshes.append(mesh)
    return meshes


def _link_meshes(node: Any) -> list[Any]:
    """Approximate a beam or route by short tubes along its resolved world path."""

    import trimesh

    points = node.resolve_points()
    radius = max(abs(float(getattr(node, "width", 0.3) or 0.3)) / 2.0, 0.05)
    rgba = _hex_to_rgba(getattr(node, "color", "#888888"), float(getattr(node, "opacity", 1.0)))

    def glb_point(point: Any) -> np.ndarray:
        coords = point.as_tuple() if hasattr(point, "as_tuple") else point
        x, y = float(coords[0]), float(coords[1])
        z = float(coords[2]) if len(coords) > 2 else 0.0
        return np.array([x, z, -y], dtype=float)

    meshes: list[Any] = []
    for first, second in zip(points, points[1:]):
        start, end = glb_point(first), glb_point(second)
        vector = end - start
        length = float(np.linalg.norm(vector))
        if length <= 1e-9:
            continue
        direction = vector / length
        cross = np.cross(np.array([0.0, 0.0, 1.0]), direction)
        cosine = float(direction[2])
        if cosine > 1.0 - 1e-10:
            rotation = np.eye(3)
        elif cosine < -1.0 + 1e-10:
            rotation = np.diag([1.0, -1.0, -1.0])
        else:
            skew = np.array([
                [0.0, -cross[2], cross[1]],
                [cross[2], 0.0, -cross[0]],
                [-cross[1], cross[0], 0.0],
            ])
            rotation = np.eye(3) + skew + skew @ skew / (1.0 + cosine)
        placement = np.eye(4)
        placement[:3, :3] = rotation
        placement[:3, 3] = (start + end) / 2.0
        mesh = trimesh.creation.cylinder(radius=radius, height=length, sections=12)
        mesh.apply_transform(placement)
        mesh.visual.face_colors = rgba
        meshes.append(mesh)
    return meshes


def scene_to_glb(scene: Any, *, strict: bool = False) -> bytes:
    """Render a scene to a binary glTF (GLB) ``bytes`` blob.

    Approximate footprint export: GDS dies export precisely, other parts
    export as extruded 2D outlines or footprint boxes — not the full
    ``geometry_3d()`` the browser shows. Beams and routes become centerline
    tubes; grids and groups are skipped. Raises ``RuntimeError`` if nothing renderable was produced.
    Strict mode raises :class:`UnsupportedGeometryError` on the first skipped,
    approximated, or failed node instead of dropping it."""

    data, _ = scene_to_glb_with_report(scene, strict=strict)
    return data


def scene_to_glb_with_report(scene: Any, *, strict: bool = False) -> tuple[bytes, dict[str, Any]]:
    """Render a scene to ``(glb_bytes, report)``.

    The report names skipped parts, footprint-box approximations, and failed
    nodes so Blender handoff never silently drops geometry. It shares the
    shape defined in :mod:`optodraw.renderers.capabilities`.
    """

    import trimesh

    from optodraw.core.beam import Beam, FocusingBeam
    from optodraw.core.routing import Route
    from optodraw.renderers.capabilities import RenderReport, UnsupportedGeometryError

    tscene = trimesh.Scene()
    count = 0
    report = RenderReport()
    for node in scene.walk():
        ctype = getattr(node, "component_type", "")
        label = getattr(node, "_id", "") or getattr(node, "label", "") or ctype
        if isinstance(node, (Beam, FocusingBeam, Route)):
            ends = (getattr(node, "start_component", None), getattr(node, "end_component", None))
            chip_route = isinstance(node, Route) and (
                getattr(node, "kind", "") == "waveguide"
                or (getattr(node, "kind", "") == "electrical" and all(
                    end is not None and getattr(end, "chip_thickness", None) is not None for end in ends
                ))
            )
            detail = f"{label} ({ctype or type(node).__name__}): {'flat strip' if chip_route else 'centerline tube'} approximation"
            if strict:
                raise UnsupportedGeometryError(f"glb: approximated {detail}")
            try:
                if chip_route:
                    try:
                        meshes = _chip_route_meshes(node)
                    except Exception as error:
                        report.failed.append(f"{label} ({ctype or type(node).__name__}): flat strip failed: {error}")
                        meshes = _link_meshes(node)
                        detail = f"{label} ({ctype or type(node).__name__}): centerline tube fallback"
                else:
                    meshes = _link_meshes(node)
            except Exception as error:
                report.failed.append(f"{detail}: {error}")
                continue
            if not meshes:
                report.skipped.append(f"{label} ({ctype or type(node).__name__}): no drawable segments")
                continue
            report.approximated.append(detail)
            for i, mesh in enumerate(meshes):
                tscene.add_geometry(mesh, node_name=f"{getattr(node, '_id', '') or ctype}_{i}")
                count += 1
            continue
        if ctype in {"Grid", "Group"}:
            detail = f"{label} ({ctype or type(node).__name__})"
            if strict:
                raise UnsupportedGeometryError(f"glb: skipped {detail}")
            report.skipped.append(detail)
            continue
        try:
            if ctype == "GDSModel":
                gds_issues: list[str] = []
                meshes = _gds_meshes(node, gds_issues)
                if gds_issues:
                    if strict:
                        raise UnsupportedGeometryError(f"glb: failed {label} ({ctype}): {gds_issues[0]}")
                    report.failed.extend(f"{label} ({ctype}): {issue}" for issue in gds_issues)
                if not meshes:
                    detail = f"{label} ({ctype}): no exportable GDS geometry"
                    if strict:
                        raise UnsupportedGeometryError(f"glb: skipped {detail}")
                    report.skipped.append(detail)
            else:
                meshes = []
                if getattr(node, "chip_thickness", None) is not None:
                    meshes, geometry_3d_issue = _geometry3d_meshes(node)
                    if meshes:
                        detail = f"{label} ({ctype}): browser 3D solids with flat material approximation"
                        if strict:
                            raise UnsupportedGeometryError(f"glb: approximated {detail}")
                        report.approximated.append(detail)
                    else:
                        report.approximated.append(
                            f"{label} ({ctype}): 3D solids unavailable ({geometry_3d_issue}); using 2D geometry"
                        )
                if not meshes:
                    geometry_issues: list[str] = []
                    meshes = _geometry2d_meshes(node, geometry_issues)
                    if geometry_issues:
                        if strict:
                            raise UnsupportedGeometryError(f"glb: failed {label} ({ctype}): {geometry_issues[0]}")
                        report.failed.extend(f"{label} ({ctype}): {issue}" for issue in geometry_issues)
                if meshes and getattr(node, "chip_thickness", None) is not None and not geometry_3d_issue:
                    pass
                elif meshes:
                    detail = f"{label} ({ctype}): extruded 2D outline, not browser 3D geometry"
                    if strict:
                        raise UnsupportedGeometryError(f"glb: approximated {detail}")
                    report.approximated.append(detail)
                else:
                    box = _footprint_box(node)
                    meshes = [box] if box is not None else []
                    if meshes:
                        detail = f"{label} ({ctype}): footprint box"
                        if strict:
                            raise UnsupportedGeometryError(f"glb: approximated {detail}")
                        report.approximated.append(detail)
        except UnsupportedGeometryError:
            raise
        except Exception as error:
            detail = f"{label} ({ctype}): {error}"
            if strict:
                raise UnsupportedGeometryError(f"glb: failed {detail}") from error
            report.failed.append(detail)
            meshes = []
        for i, mesh in enumerate(meshes):
            tscene.add_geometry(mesh, node_name=f"{getattr(node, '_id', '') or ctype}_{i}")
            count += 1

    if count == 0:
        raise RuntimeError("nothing to export (scene has no renderable geometry)")
    report.nodes = count
    payload = report.to_dict()
    payload["meshes"] = count
    data = tscene.export(file_type="glb")
    assert isinstance(data, bytes)
    return data, payload
