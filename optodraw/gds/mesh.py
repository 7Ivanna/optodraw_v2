"""GDS mesh and section export helpers."""

from __future__ import annotations

from typing import Any

from optodraw.gds.layout import GDSLayout, GDSLayerRecord, GDSSection
from optodraw.gds.styles import LayerSpec, MeshBackend, color_to_rgba

def _require_shapely_geometry() -> tuple[Any, Any]:
    try:
        from shapely.geometry import Polygon, box
    except ImportError as exc:
        raise ImportError("shapely is required for GDS section utilities") from exc
    return Polygon, box


def _require_geometry_packages() -> tuple[Any, Any, Any]:
    try:
        import trimesh
    except ImportError as exc:
        raise ImportError("trimesh is required for GDS mesh utilities") from exc
    Polygon, box = _require_shapely_geometry()
    return trimesh, Polygon, box


def _iter_simple_geometries(geometry):
    if geometry.is_empty:
        return
    if hasattr(geometry, "geoms"):
        for child in geometry.geoms:
            yield from _iter_simple_geometries(child)
        return
    yield geometry


def _unique_layer_key(name: str | None, spec: LayerSpec, used: set[str]) -> str:
    base = (name or f"L{spec[0]}_{spec[1]}").strip().replace(" ", "_").replace("/", "_")
    if not base:
        base = f"L{spec[0]}_{spec[1]}"
    candidate = base
    suffix = 2
    while candidate in used:
        candidate = f"{base}_{suffix}"
        suffix += 1
    used.add(candidate)
    return candidate


def _build_gdsfactory_layer_stack_from_records(layer_records: list[GDSLayerRecord]):
    from gdsfactory.technology import LayerLevel, LayerStack, LogicalLayer

    layers: dict[str, Any] = {}
    used: set[str] = set()
    for record in layer_records:
        key = _unique_layer_key(record.level_name or record.name, record.spec, used)
        layers[key] = LayerLevel(
            name=record.name,
            layer=LogicalLayer(layer=record.spec),
            thickness=float(record.thickness),
            zmin=float(record.zmin),
            material=record.material_name or record.material_preset,
            info={"style_source": record.style_source, "layer_spec": record.spec},
        )
    return LayerStack(layers=layers)


def _build_gdsfactory_layer_views_from_records(layer_records: list[GDSLayerRecord]):
    from gdsfactory.technology import LayerView, LayerViews

    layer_views = LayerViews()
    used: set[str] = set()
    for record in layer_records:
        name = _unique_layer_key(record.name, record.spec, used)
        layer_views.add_layer_view(
            name,
            layer_view=LayerView(
                name=record.name,
                layer=record.spec,
                color=record.color,
                visible=record.visible,
                transparent=record.opacity < 0.999,
            ),
        )
    return layer_views


def _build_gdsfactory_scene(layout: GDSLayout):
    # The gdsfactory exporter re-imports the full cell, so it cannot honor a
    # crop already applied to the layout's polygon records.
    if not layout.layer_records or layout.crop_region is not None:
        return None

    try:
        from gdsfactory.export.to_3d import to_3d
    except ImportError:
        return None

    from optodraw.gds.layout import _import_gdsfactory_component

    component = _import_gdsfactory_component(layout.source_path.as_posix(), layout.cell_name)
    if component is None:
        return None

    layer_stack = layout.gdsfactory_layer_stack
    layer_views = layout.gdsfactory_layer_views
    if layer_stack is None:
        try:
            layer_stack = _build_gdsfactory_layer_stack_from_records(layout.layer_records)
        except Exception:
            layer_stack = None
    if layer_views is None:
        try:
            layer_views = _build_gdsfactory_layer_views_from_records(layout.layer_records)
        except Exception:
            layer_views = None
    if layer_stack is None or layer_views is None:
        return None

    try:
        return to_3d(component, layer_views=layer_views, layer_stack=layer_stack)
    except Exception:
        return None


def _flatten_trimesh_scene(scene):
    trimesh, _, _ = _require_geometry_packages()
    meshes = []
    for node in scene.graph.nodes_geometry:
        transform, geometry_name = scene.graph.get(node)
        geometry = scene.geometry.get(geometry_name)
        if not isinstance(geometry, trimesh.Trimesh):
            continue
        mesh = geometry.copy()
        mesh.apply_transform(transform)
        meshes.append(mesh)
    if not meshes:
        raise ValueError("No geometry found in trimesh scene")
    return trimesh.util.concatenate(meshes)


def _record_polygon_geometries(record: GDSLayerRecord, Polygon) -> list[Any]:
    geometries = []
    for polygon in record.polygons:
        shape = Polygon(polygon)
        if not shape.is_valid:
            shape = shape.buffer(0)
        if shape.is_empty:
            continue
        geometries.extend(
            part for part in _iter_simple_geometries(shape)
            if part.geom_type == "Polygon" and part.area > 0
        )
    return geometries


def _build_trimesh_from_records(layer_records: list[GDSLayerRecord], *, merge_polygons: bool = False):
    trimesh, Polygon, _ = _require_geometry_packages()
    if merge_polygons:
        from shapely.ops import unary_union

    meshes = []
    for record in layer_records:
        if not record.visible:
            continue
        rgba = color_to_rgba(record.color, record.opacity)
        geometries = _record_polygon_geometries(record, Polygon)
        if merge_polygons and geometries:
            geometries = [
                part for part in _iter_simple_geometries(unary_union(geometries))
                if part.geom_type == "Polygon" and part.area > 0
            ]
        for geometry in geometries:
            mesh = trimesh.creation.extrude_polygon(geometry, height=record.thickness)
            mesh.apply_translation((0.0, 0.0, record.zmin))
            mesh.visual.face_colors = rgba
            meshes.append(mesh)

    if not meshes:
        raise ValueError("No polygons found in the provided GDS layer records")

    return trimesh.util.concatenate(meshes)


def _resolve_gds_mesh_backend(
    layout_or_records: GDSLayout | list[GDSLayerRecord],
    *,
    backend: MeshBackend = "auto",
    merge_polygons: bool = False,
):
    normalized_backend = backend.strip().lower()
    if normalized_backend not in {"auto", "gdsfactory", "trimesh"}:
        raise ValueError("Unsupported mesh backend. Use 'auto', 'gdsfactory', or 'trimesh'.")
    if merge_polygons and normalized_backend == "gdsfactory":
        raise ValueError("merge_polygons=True requires backend='auto' or backend='trimesh'.")

    if isinstance(layout_or_records, GDSLayout):
        if not merge_polygons and normalized_backend in {"auto", "gdsfactory"}:
            scene = _build_gdsfactory_scene(layout_or_records)
            if scene is not None:
                return ("gdsfactory", scene, _flatten_trimesh_scene(scene))
            if normalized_backend == "gdsfactory":
                raise ValueError("Unable to build a gdsfactory 3D scene for this layout.")
        return ("trimesh", None, _build_trimesh_from_records(layout_or_records.layer_records, merge_polygons=merge_polygons))

    if normalized_backend == "gdsfactory":
        raise ValueError("The gdsfactory mesh backend requires a GDSLayout input.")
    return ("trimesh", None, _build_trimesh_from_records(layout_or_records, merge_polygons=merge_polygons))


def build_gds_trimesh(
    layout_or_records: GDSLayout | list[GDSLayerRecord],
    *,
    backend: MeshBackend = "auto",
    merge_polygons: bool = False,
):
    _, _, mesh = _resolve_gds_mesh_backend(
        layout_or_records,
        backend=backend,
        merge_polygons=merge_polygons,
    )
    return mesh


def weighted_x_positions(layout: GDSLayout, quantiles: list[float]) -> list[float]:
    Polygon, _ = _require_shapely_geometry()

    entries = []
    for record in layout.layer_records:
        if not record.visible:
            continue
        for polygon in record.polygons:
            shape = Polygon(polygon)
            if not shape.is_valid:
                shape = shape.buffer(0)
            if shape.is_empty:
                continue
            geometries = [
                part for part in _iter_simple_geometries(shape)
                if part.geom_type == "Polygon" and part.area > 0
            ]
            for geometry in geometries:
                area = float(geometry.area)
                if area > 0:
                    entries.append((float(geometry.centroid.x), area))

    min_x, _, max_x, _ = layout.bounds
    if not entries:
        width = max_x - min_x
        return [min_x + width * quantile for quantile in quantiles]

    entries.sort(key=lambda item: item[0])
    total_weight = sum(weight for _, weight in entries)
    positions = []
    for quantile in quantiles:
        target = total_weight * quantile
        cumulative = 0.0
        chosen = entries[-1][0]
        for x_position, weight in entries:
            cumulative += weight
            if cumulative >= target:
                chosen = x_position
                break
        positions.append(chosen)
    return positions


def build_gds_sections(layout: GDSLayout, count: int = 3) -> list[GDSSection]:
    if count <= 0:
        return []

    min_x, _, max_x, _ = layout.bounds
    width = max_x - min_x
    base_quantiles = [0.2, 0.5, 0.8]
    quantiles = base_quantiles[:count] if count <= len(base_quantiles) else [
        (index + 1) / (count + 1) for index in range(count)
    ]
    positions = weighted_x_positions(layout, quantiles)
    window = max(width * 0.02, 2.0)
    margin = min(max(width * 0.08, window), max(width, 0.0) / 2.0)

    sections: list[GDSSection] = []
    for index, position in enumerate(positions):
        clamped = min(max(position, min_x + margin), max_x - margin)
        sections.append(GDSSection(label=chr(65 + index), x=float(clamped), window=float(window)))
    return sections


def _coerce_section(section: GDSSection | dict[str, Any]) -> GDSSection:
    if isinstance(section, GDSSection):
        return section
    return GDSSection(
        label=str(section.get("label", "A")),
        x=float(section["x"]),
        window=float(section["window"]),
        mode=str(section.get("mode", "projection")),
    )
