"""GDS layout loading and layer record types."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from os import PathLike
from pathlib import Path
from typing import Any
import tempfile
import warnings

from optodraw.gds.styles import (
    GDS_LAYER_PALETTE,
    LayerSpec,
    MeshBackend,
    _ResolvedGdsfactoryContext,
    _format_layer_description,
    _resolve_gdsfactory_context,
    coerce_scalar,
    get_gdsfactory_layer_styles,
    get_layer_name_map,
    material_preset_from_layer_name,
    normalize_layer_stack,
)
from optodraw.gds.technology import Technology

logger = logging.getLogger(__name__)


@dataclass
class _LoadedGDSGeometry:
    footprint: tuple[float, float]
    polygons_by_spec: dict[LayerSpec, list[list[tuple[float, float]]]]
    origin: tuple[float, float] = (0.0, 0.0)
    cell_name: str | None = None          # the cell read: the one asked for, else the chosen top cell


@dataclass
class GDSSection:
    label: str
    x: float
    window: float
    mode: str = "projection"

    def __post_init__(self) -> None:
        normalized = str(self.mode or "projection").strip().lower()
        if normalized not in ("projection", "section"):
            raise ValueError(f"GDSSection mode must be 'projection' or 'section', got {self.mode!r}")
        self.mode = normalized

    def to_dict(self) -> dict[str, Any]:
        return {"label": self.label, "x": self.x, "window": self.window, "mode": self.mode}


@dataclass
class GDSLayerRecord:
    spec: LayerSpec
    name: str
    description: str
    color: str
    opacity: float
    thickness: float
    zmin: float
    material_preset: str
    polygons: list[list[tuple[float, float]]]
    matched_pdk: bool
    visible: bool = True
    material_name: str | None = None
    level_name: str | None = None
    style_source: str = "fallback"
    physical_stack_known: bool = False

    @property
    def polygon_count(self) -> int:
        return len(self.polygons)

    @property
    def total_area_um2(self) -> float:
        return sum(abs(_polygon_area(polygon)) for polygon in self.polygons)

    @property
    def label_anchor(self) -> tuple[float, float] | None:
        return _layer_label_anchor(self.polygons)

    def to_layer_stack_entry(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "color": self.color,
            "opacity": self.opacity,
            "thickness": self.thickness,
            "z_offset": self.zmin,
            "material_preset": self.material_preset,
            "visible": self.visible,
            "physical_stack_known": self.physical_stack_known,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "spec": self.spec,
            "name": self.name,
            "description": self.description,
            "color": self.color,
            "opacity": self.opacity,
            "thickness": self.thickness,
            "zmin": self.zmin,
            "material_preset": self.material_preset,
            "material_name": self.material_name,
            "level_name": self.level_name,
            "matched_pdk": self.matched_pdk,
            "style_source": self.style_source,
            "physical_stack_known": self.physical_stack_known,
            "visible": self.visible,
            "polygon_count": self.polygon_count,
            "total_area_um2": self.total_area_um2,
            "label_anchor": self.label_anchor,
        }


@dataclass
class GDSLayout:
    source_path: Path
    cell_name: str
    bounds: tuple[float, float, float, float]
    layer_records: list[GDSLayerRecord]
    technology: Technology | None = None
    gdsfactory_layer_stack: Any | None = None
    gdsfactory_layer_views: Any | None = None
    crop_region: tuple[float, float, float, float] | None = None

    @property
    def footprint_um(self) -> tuple[float, float]:
        min_x, min_y, max_x, max_y = self.bounds
        return (float(max_x - min_x), float(max_y - min_y))

    def summary(self) -> dict[str, Any]:
        return {
            "cell_name": self.cell_name,
            "polygon_count": sum(record.polygon_count for record in self.layer_records),
            "layer_specs": [record.spec for record in self.layer_records],
            "matched_pdk_layers": sum(1 for record in self.layer_records if record.matched_pdk),
            "fallback_layers": sum(1 for record in self.layer_records if not record.matched_pdk),
            "layers_with_physical_stack": sum(1 for record in self.layer_records if record.physical_stack_known),
            "layers_with_inferred_stack": sum(1 for record in self.layer_records if not record.physical_stack_known),
            "footprint_um": tuple(round(value, 3) for value in self.footprint_um),
            "bounds": self.bounds,
            "technology": self.technology.name if self.technology is not None else None,
        }

    def describe_layers(self) -> list[dict[str, Any]]:
        return [record.to_dict() for record in self.layer_records]

    def layer_report(
        self,
        *,
        format: str = "records",
        include_summary: bool = True,
        float_precision: int = 3,
    ) -> list[dict[str, Any]] | str:
        normalized = format.strip().lower()
        if normalized in {"records", "record", "dict", "dicts", "python"}:
            return self.describe_layers()

        from optodraw.gds.plotting import (
            _layer_report_csv,
            _layer_report_markdown,
            _layer_report_rows,
        )

        rows = _layer_report_rows(self.layer_records, float_precision=float_precision)
        if normalized == "csv":
            return _layer_report_csv(rows)
        if normalized in {"md", "markdown"}:
            return _layer_report_markdown(
                self,
                rows,
                include_summary=include_summary,
            )

        raise ValueError("Unsupported layer report format. Use 'records', 'csv', or 'markdown'.")

    def export_layer_report(
        self,
        output_path: str | PathLike[str],
        *,
        format: str | None = None,
        include_summary: bool = True,
        float_precision: int = 3,
    ) -> Path:
        from optodraw.gds.plotting import _infer_layer_report_format

        path = Path(output_path)
        normalized_format = _infer_layer_report_format(path, format)
        content = self.layer_report(
            format=normalized_format,
            include_summary=include_summary,
            float_precision=float_precision,
        )
        if not isinstance(content, str):
            raise TypeError("Layer report export requires a text format such as 'csv' or 'markdown'.")

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def to_layer_stack(self) -> dict[LayerSpec, dict[str, Any]]:
        return {record.spec: record.to_layer_stack_entry() for record in self.layer_records}

    def to_model(self, **kwargs):
        from optodraw.components.models import GDSModel

        kwargs.setdefault("crop_region", self.crop_region)
        return GDSModel(
            self.source_path,
            cell_name=self.cell_name,
            layer_stack=self.to_layer_stack(),
            **kwargs,
        )

    def build_scene(
        self,
        *,
        title: str | None = None,
        width_padding: float = 40.0,
        height_padding: float = 40.0,
        min_width: float = 220.0,
        min_height: float = 160.0,
        **model_kwargs,
    ):
        from optodraw.core.scene import Scene

        model = self.to_model(**model_kwargs)
        width, height = model.footprint
        scene = Scene(
            title=title or f"GDSModel:{self.cell_name}",
            width=max(width + width_padding, min_width),
            height=max(height + height_padding, min_height),
            platform="on_chip",
        )
        scene.add(model)
        return scene, model

    def build_trimesh(self, *, backend: MeshBackend = "auto", merge_polygons: bool = False):
        from optodraw.gds.mesh import build_gds_trimesh

        return build_gds_trimesh(self, backend=backend, merge_polygons=merge_polygons)

    def export_mesh(
        self,
        output_dir: str | PathLike[str],
        *,
        stem: str | None = None,
        formats: tuple[str, ...] = ("stl", "glb"),
        backend: MeshBackend = "auto",
        merge_polygons: bool = False,
    ) -> dict[str, Any]:
        from optodraw.gds.mesh import _resolve_gds_mesh_backend

        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        resolved_backend, scene, mesh = _resolve_gds_mesh_backend(
            self,
            backend=backend,
            merge_polygons=merge_polygons,
        )
        file_stem = stem or self.source_path.stem.lower()
        result: dict[str, Any] = {
            "cell_name": self.cell_name,
            "backend": resolved_backend,
            "faces": int(len(mesh.faces)),
            "vertices": int(len(mesh.vertices)),
            "layers": len(self.layer_records),
            "merged_polygons": bool(merge_polygons),
        }

        for fmt in formats:
            normalized = fmt.lower()
            out_path = output_path / f"{file_stem}_stacked.{normalized}"
            if normalized == "glb" and scene is not None:
                try:
                    out_path.write_bytes(_exported_glb_bytes(scene.export(file_type="glb")))
                except Exception as exc:
                    raise RuntimeError(
                        "Layered GLB export failed; a flattened mesh would lose layer materials"
                    ) from exc
            elif normalized == "glb":
                out_path.write_bytes(_exported_glb_bytes(mesh.export(file_type="glb")))
            else:
                mesh.export(out_path.as_posix(), file_type=normalized)
            result[normalized] = out_path

        return result

    def export_blender_script(
        self,
        output_path: str | PathLike[str],
        *,
        source_glb: str | PathLike[str] | None = None,
        render_path: str | PathLike[str] | None = None,
        mesh_dir: str | PathLike[str] | None = None,
        backend: MeshBackend = "auto",
        merge_polygons: bool = False,
        **script_kwargs,
    ) -> Path:
        """Write a headless Blender script for this layout, exporting GLB first if needed."""
        from optodraw.blender import export_blender_script as _export_blender_script

        resolved_source_glb = source_glb
        if resolved_source_glb is None:
            output_dir = Path(mesh_dir) if mesh_dir is not None else Path(output_path).expanduser().parent
            exports = self.export_mesh(
                output_dir,
                formats=("glb",),
                backend=backend,
                merge_polygons=merge_polygons,
            )
            resolved_source_glb = exports["glb"]

        return _export_blender_script(
            output_path,
            source_glb=resolved_source_glb,
            output_image=render_path,
            **script_kwargs,
        )


def _exported_glb_bytes(data: Any) -> bytes:
    if isinstance(data, bytes):
        return data
    if isinstance(data, bytearray):
        return bytes(data)
    if isinstance(data, memoryview):
        return data.tobytes()
    raise TypeError(f"Expected GLB export bytes, got {type(data).__name__}")


def _is_path_source(source: Any) -> bool:
    return isinstance(source, (str, PathLike))


def _source_path(source: Any) -> str | None:
    if not _is_path_source(source):
        return None
    return Path(source).expanduser().as_posix()


def _bounds_from_bbox_like(bbox: Any, scale: float) -> tuple[float, float] | None:
    if bbox is None:
        return None

    if hasattr(bbox, "tolist"):
        bbox = bbox.tolist()

    left = coerce_scalar(getattr(bbox, "left", None))
    right = coerce_scalar(getattr(bbox, "right", None))
    top = coerce_scalar(getattr(bbox, "top", None))
    bottom = coerce_scalar(getattr(bbox, "bottom", None))
    if all(value is not None for value in (left, right, top, bottom)):
        assert left is not None and right is not None and top is not None and bottom is not None
        width = abs(float(right) - float(left)) * scale
        height = abs(float(top) - float(bottom)) * scale
        if width > 0 and height > 0:
            return (width, height)

    if not isinstance(bbox, (tuple, list)) or len(bbox) != 2:
        return None

    point_a, point_b = bbox
    if all(hasattr(point, "x") and hasattr(point, "y") for point in (point_a, point_b)):
        x0 = coerce_scalar(point_a.x)
        y0 = coerce_scalar(point_a.y)
        x1 = coerce_scalar(point_b.x)
        y1 = coerce_scalar(point_b.y)
    elif all(isinstance(point, (tuple, list)) and len(point) >= 2 for point in (point_a, point_b)):
        x0 = coerce_scalar(point_a[0])
        y0 = coerce_scalar(point_a[1])
        x1 = coerce_scalar(point_b[0])
        y1 = coerce_scalar(point_b[1])
    else:
        return None

    if any(value is None for value in (x0, y0, x1, y1)):
        return None

    assert x0 is not None and y0 is not None and x1 is not None and y1 is not None
    width = abs(float(x1) - float(x0)) * scale
    height = abs(float(y1) - float(y0)) * scale
    if width > 0 and height > 0:
        return (width, height)
    return None


def _bounds_from_component_like(source: Any, scale: float) -> tuple[float, float] | None:
    width = coerce_scalar(getattr(source, "dxsize", None))
    height = coerce_scalar(getattr(source, "dysize", None))
    if width is not None and height is not None and width > 0 and height > 0:
        return (width * scale, height * scale)

    for bbox_attr in ("bbox_np", "dbbox", "bbox"):
        bbox = getattr(source, bbox_attr, None)
        if bbox is None:
            continue
        if callable(bbox):
            try:
                bbox = bbox()
            except TypeError:
                continue
        bounds = _bounds_from_bbox_like(bbox, scale)
        if bounds is not None:
            return bounds

    return None


def _select_gds_cell(library: Any, cell_name: str | None) -> Any | None:
    cells = list(getattr(library, "cells", []) or [])
    if cell_name:
        return next((cell for cell in cells if getattr(cell, "name", None) == cell_name), None)

    top_level_fn = getattr(library, "top_level", None)
    if callable(top_level_fn):
        top_level_items_raw: Any = top_level_fn()
        top_level_items: list[Any] = list(top_level_items_raw) if top_level_items_raw is not None else []
        # Skip gdsfactory / KLayout metadata cells (e.g. "$$$CONTEXT_INFO$$$") so a
        # gdsfactory-exported GDS resolves to the actual device, not the context cell.
        real = [c for c in top_level_items if not str(getattr(c, "name", "")).startswith("$$$")]
        candidates = real or top_level_items
        if len(candidates) == 1:
            return candidates[0]
        if candidates:
            # multiple real tops: pick the one with the most (recursive) geometry
            def _weight(cell: Any) -> int:
                get_polygons = getattr(cell, "get_polygons", None)
                try:
                    return len(get_polygons()) if callable(get_polygons) else len(getattr(cell, "polygons", []) or [])
                except Exception:
                    return len(getattr(cell, "polygons", []) or [])

            return max(candidates, key=_weight)

    return cells[0] if cells else None


def _polygon_area(points: list[tuple[float, float]]) -> float:
    area = 0.0
    for index, (x0, y0) in enumerate(points):
        x1, y1 = points[(index + 1) % len(points)]
        area += x0 * y1 - x1 * y0
    return area * 0.5


def _normalize_crop_region(crop_region: tuple[float, float, float, float] | list[float] | None) -> tuple[float, float, float, float] | None:
    if crop_region is None:
        return None
    if not isinstance(crop_region, (tuple, list)) or len(crop_region) != 4:
        raise ValueError("crop_region must be a 4-tuple: (min_x, min_y, max_x, max_y).")
    values = [coerce_scalar(value) for value in crop_region]
    if any(value is None for value in values):
        raise ValueError("crop_region values must be numeric.")
    min_x, min_y, max_x, max_y = (float(value) for value in values if value is not None)
    if min_x == max_x or min_y == max_y:
        raise ValueError("crop_region must have non-zero width and height.")
    return (min(min_x, max_x), min(min_y, max_y), max(min_x, max_x), max(min_y, max_y))


def _clip_edge(
    points: list[tuple[float, float]],
    *,
    inside,
    intersect,
) -> list[tuple[float, float]]:
    if not points:
        return []

    clipped: list[tuple[float, float]] = []
    previous = points[-1]
    previous_inside = inside(previous)
    for current in points:
        current_inside = inside(current)
        if current_inside:
            if not previous_inside:
                clipped.append(intersect(previous, current))
            clipped.append(current)
        elif previous_inside:
            clipped.append(intersect(previous, current))
        previous = current
        previous_inside = current_inside
    return clipped


def _dedupe_consecutive_points(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    deduped: list[tuple[float, float]] = []
    for x, y in points:
        point = (float(x), float(y))
        if deduped and abs(deduped[-1][0] - point[0]) <= 1e-9 and abs(deduped[-1][1] - point[1]) <= 1e-9:
            continue
        deduped.append(point)
    if len(deduped) > 1 and abs(deduped[0][0] - deduped[-1][0]) <= 1e-9 and abs(deduped[0][1] - deduped[-1][1]) <= 1e-9:
        deduped.pop()
    return deduped


def _clip_polygon_to_rect(
    points: list[tuple[float, float]],
    crop_region: tuple[float, float, float, float],
) -> list[tuple[float, float]] | None:
    min_x, min_y, max_x, max_y = crop_region

    def vertical_intersection(x_edge: float):
        def _intersect(start: tuple[float, float], end: tuple[float, float]) -> tuple[float, float]:
            x0, y0 = start
            x1, y1 = end
            if abs(x1 - x0) <= 1e-12:
                return (x_edge, y0)
            t = (x_edge - x0) / (x1 - x0)
            return (x_edge, y0 + t * (y1 - y0))

        return _intersect

    def horizontal_intersection(y_edge: float):
        def _intersect(start: tuple[float, float], end: tuple[float, float]) -> tuple[float, float]:
            x0, y0 = start
            x1, y1 = end
            if abs(y1 - y0) <= 1e-12:
                return (x0, y_edge)
            t = (y_edge - y0) / (y1 - y0)
            return (x0 + t * (x1 - x0), y_edge)

        return _intersect

    clipped = list(points)
    clipped = _clip_edge(clipped, inside=lambda point: point[0] >= min_x, intersect=vertical_intersection(min_x))
    clipped = _clip_edge(clipped, inside=lambda point: point[0] <= max_x, intersect=vertical_intersection(max_x))
    clipped = _clip_edge(clipped, inside=lambda point: point[1] >= min_y, intersect=horizontal_intersection(min_y))
    clipped = _clip_edge(clipped, inside=lambda point: point[1] <= max_y, intersect=horizontal_intersection(max_y))
    clipped = _dedupe_consecutive_points(clipped)
    if len(clipped) < 3 or abs(_polygon_area(clipped)) <= 1e-12:
        return None
    return clipped


def _polygon_centroid(points: list[tuple[float, float]]) -> tuple[float, float] | None:
    signed_area = _polygon_area(points)
    if abs(signed_area) <= 1e-12:
        return None

    cx = 0.0
    cy = 0.0
    for index, (x0, y0) in enumerate(points):
        x1, y1 = points[(index + 1) % len(points)]
        cross = x0 * y1 - x1 * y0
        cx += (x0 + x1) * cross
        cy += (y0 + y1) * cross

    scale = 1.0 / (6.0 * signed_area)
    return (cx * scale, cy * scale)


def _layer_label_anchor(polygons: list[list[tuple[float, float]]]) -> tuple[float, float] | None:
    if not polygons:
        return None

    largest_polygon = max(polygons, key=lambda polygon: abs(_polygon_area(polygon)))
    centroid = _polygon_centroid(largest_polygon)
    if centroid is not None:
        return centroid

    xs = [point[0] for point in largest_polygon]
    ys = [point[1] for point in largest_polygon]
    if not xs or not ys:
        return None
    return ((min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0)


def _normalize_polygon_points(
    points: Any,
    *,
    scale: float,
    center_x: float,
    center_y: float,
) -> list[tuple[float, float]] | None:
    normalized: list[tuple[float, float]] = []
    try:
        point_iter = list(points)
    except TypeError:
        return None

    for point in point_iter:
        if hasattr(point, "tolist"):
            point = point.tolist()
        if not isinstance(point, (tuple, list)) or len(point) < 2:
            return None

        x = coerce_scalar(point[0])
        y = coerce_scalar(point[1])
        if x is None or y is None:
            return None

        normalized.append(((float(x) - center_x) * scale, (float(y) - center_y) * scale))

    if len(normalized) >= 2:
        first_x, first_y = normalized[0]
        last_x, last_y = normalized[-1]
        if abs(first_x - last_x) <= 1e-9 and abs(first_y - last_y) <= 1e-9:
            normalized = normalized[:-1]

    if len(normalized) < 3:
        return None

    unique_points = {(round(x, 9), round(y, 9)) for x, y in normalized}
    if len(unique_points) < 3:
        return None

    if abs(_polygon_area(normalized)) <= 1e-12:
        return None

    return normalized


def _layer_spec_from_polygon(polygon: Any) -> LayerSpec:
    layer = coerce_scalar(getattr(polygon, "layer", 0))
    datatype = coerce_scalar(getattr(polygon, "datatype", 0))
    return (int(layer or 0), int(datatype or 0))


def _import_gdsfactory_component(source_path: str, cell_name: str | None) -> Any | None:
    try:
        import gdsfactory as gf
    except ImportError:
        return None

    import_gds = getattr(gf, "import_gds", None)
    if import_gds is None:
        reader = getattr(gf, "read", None)
        import_gds = getattr(reader, "import_gds", None) if reader is not None else None
    if import_gds is None:
        return None

    attempts = [{}]
    if cell_name:
        attempts = [{"cell_name": cell_name}, {"cellname": cell_name}, {}]

    for kwargs in attempts:
        try:
            return import_gds(source_path, **kwargs)
        except TypeError:
            continue
        except Exception as error:
            logger.warning("gdsfactory could not import %s: %s", source_path, error)
            return None

    return None


def load_bounds_from_path(source_path: str, cell_name: str | None, scale: float) -> tuple[float, float] | None:
    component = _import_gdsfactory_component(source_path, cell_name)
    if component is not None:
        bounds = _bounds_from_component_like(component, scale)
        if bounds is not None:
            return bounds

    try:
        import gdstk
    except ImportError:
        return None

    try:
        library = gdstk.read_gds(source_path)
        cell = _select_gds_cell(library, cell_name)
        if cell is None:
            return None
        bbox_fn = getattr(cell, "bounding_box", None)
        if not callable(bbox_fn):
            return None
        return _bounds_from_bbox_like(bbox_fn(), scale)
    except Exception as error:
        logger.warning("could not read bounds from %s: %s", source_path, error)
        return None


def load_bounds_from_source(source: Any, cell_name: str | None, scale: float) -> tuple[float, float] | None:
    source_path = _source_path(source)
    if source_path is not None:
        return load_bounds_from_path(source_path, cell_name, scale)

    bounds = _bounds_from_component_like(source, scale)
    if bounds is not None:
        return bounds

    write_gds = getattr(source, "write_gds", None)
    if not callable(write_gds):
        return None

    with tempfile.NamedTemporaryFile(suffix=".gds", delete=False) as handle:
        temp_path = handle.name

    try:
        write_gds(temp_path)
        return load_bounds_from_path(temp_path, cell_name, scale)
    except Exception as error:
        logger.warning("could not read bounds from live component: %s", error)
        return None
    finally:
        Path(temp_path).unlink(missing_ok=True)


def load_gds_geometry_from_path(
    source_path: str,
    cell_name: str | None,
    scale: float,
) -> _LoadedGDSGeometry | None:
    try:
        import gdstk
    except ImportError:
        return None

    try:
        library = gdstk.read_gds(source_path)
        cell = _select_gds_cell(library, cell_name)
        if cell is None:
            return None

        bbox_fn = getattr(cell, "bounding_box", None)
        if not callable(bbox_fn):
            return None

        bbox = bbox_fn()
        footprint = _bounds_from_bbox_like(bbox, scale)
        if footprint is None:
            return None

        bbox_any: Any = bbox
        bbox_to_list = getattr(bbox_any, "tolist", None)
        if callable(bbox_to_list):
            bbox = bbox_to_list()
        if not isinstance(bbox, (tuple, list)) or len(bbox) != 2:
            return None

        min_point, max_point = bbox
        min_x = coerce_scalar(min_point[0] if isinstance(min_point, (tuple, list)) and len(min_point) >= 2 else None)
        min_y = coerce_scalar(min_point[1] if isinstance(min_point, (tuple, list)) and len(min_point) >= 2 else None)
        max_x = coerce_scalar(max_point[0] if isinstance(max_point, (tuple, list)) and len(max_point) >= 2 else None)
        max_y = coerce_scalar(max_point[1] if isinstance(max_point, (tuple, list)) and len(max_point) >= 2 else None)
        if any(value is None for value in (min_x, min_y, max_x, max_y)):
            return None

        assert min_x is not None and min_y is not None and max_x is not None and max_y is not None
        center_x = (float(min_x) + float(max_x)) / 2.0
        center_y = (float(min_y) + float(max_y)) / 2.0

        polygons_by_spec: dict[LayerSpec, list[list[tuple[float, float]]]] = {}
        get_polygons = getattr(cell, "get_polygons", None)
        polygon_iter: Any = get_polygons() if callable(get_polygons) else []
        for polygon in list(polygon_iter):
            polygon_points = _normalize_polygon_points(
                getattr(polygon, "points", polygon),
                scale=scale,
                center_x=center_x,
                center_y=center_y,
            )
            if polygon_points is None:
                continue

            spec = _layer_spec_from_polygon(polygon)
            polygons_by_spec.setdefault(spec, []).append(polygon_points)

        return _LoadedGDSGeometry(
            footprint=footprint,
            polygons_by_spec=polygons_by_spec,
            origin=(center_x, center_y),
            cell_name=getattr(cell, "name", None),
        )
    except Exception as error:
        logger.warning("could not read geometry from %s: %s", source_path, error)
        return None


def load_gds_geometry_from_source(
    source: Any,
    cell_name: str | None,
    scale: float,
) -> _LoadedGDSGeometry | None:
    source_path = _source_path(source)
    if source_path is not None:
        return load_gds_geometry_from_path(source_path, cell_name, scale)

    write_gds = getattr(source, "write_gds", None)
    if not callable(write_gds):
        return None

    with tempfile.NamedTemporaryFile(suffix=".gds", delete=False) as handle:
        temp_path = handle.name

    try:
        write_gds(temp_path)
        return load_gds_geometry_from_path(temp_path, cell_name, scale)
    except Exception as error:
        logger.warning("could not read geometry from live component: %s", error)
        return None
    finally:
        Path(temp_path).unlink(missing_ok=True)


def load_gds_cell(source_path: str | PathLike[str], cell_name: str | None = None):
    try:
        import gdstk
    except ImportError as exc:
        raise ImportError("gdstk is required to parse GDS files") from exc

    library = gdstk.read_gds(Path(source_path).as_posix())
    cell = _select_gds_cell(library, cell_name)
    if cell is None:
        raise ValueError(f"No GDS cell found in {source_path}")
    return cell


def polygon_points(polygon: Any) -> list[tuple[float, float]]:
    points = polygon.points if hasattr(polygon, "points") else polygon
    return [(float(x), float(y)) for x, y in points]


def _merge_polygon_points(polygons: list[list[tuple[float, float]]]) -> list[list[tuple[float, float]]]:
    if len(polygons) <= 1:
        return polygons
    try:
        import gdstk
    except ImportError:
        return polygons

    try:
        gdstk_polygons = [gdstk.Polygon(polygon) for polygon in polygons]
        merged = gdstk.boolean(gdstk_polygons, [], "or")
    except Exception:
        return polygons

    merged_polygons: list[list[tuple[float, float]]] = []
    for polygon in merged:
        points = _dedupe_consecutive_points(polygon_points(polygon))
        if len(points) >= 3 and abs(_polygon_area(points)) > 1e-12:
            merged_polygons.append(points)
    return merged_polygons or polygons


def _warn_unstyled(specs) -> None:
    """A layer with no style has no height, so the 3D view and the GLB leave it out: say so, not silently."""

    missing = sorted(set(specs))
    if missing:
        warnings.warn(
            f"GDS layers {', '.join(map(str, missing))} are not in the layer stack; they have no height, so the "
            "3D view and the GLB leave them out. Add them to the stack, or hide them with visible: false "
            "(optodraw.gds.check_stack lists every stack fault).",
            stacklevel=3,
        )


def load_gds_layout(
    source_path: str | PathLike[str],
    *,
    cell_name: str | None = None,
    crop_region: tuple[float, float, float, float] | list[float] | None = None,
    merge_polygons: bool = False,
    technology: Technology | dict[Any, dict[str, Any]] | None = None,
    pdk: Any | None = None,
    layers: Any | None = None,
    layer_styles: dict[Any, dict[str, Any]] | None = None,
    layer_style_overrides: dict[Any, dict[str, Any]] | None = None,
    gds3d_techfile: str | PathLike[str] | None = None,
    gds3d_unit_scale: float = 1e-3,
    aux_layer_depths: dict[Any, dict[str, Any]] | None = None,
    fallback_thickness: float = 0.22,
    fallback_material_preset: str = "silicon",
    fallback_layer_gap: float = 0.08,
    include_hidden: bool = False,
) -> GDSLayout:
    from optodraw.gds.parsers import parse_gds3d_techfile
    from optodraw.gds.technology import Technology

    path = Path(source_path)
    cell = load_gds_cell(path, cell_name)
    normalized_crop_region = _normalize_crop_region(crop_region)

    polygons_by_spec: dict[LayerSpec, list[list[tuple[float, float]]]] = {}
    for polygon in cell.get_polygons():
        spec = (int(polygon.layer), int(polygon.datatype))
        points = polygon_points(polygon)
        if normalized_crop_region is not None:
            clipped = _clip_polygon_to_rect(points, normalized_crop_region)
            if clipped is None:
                continue
            points = clipped
        polygons_by_spec.setdefault(spec, []).append(points)

    if merge_polygons:
        polygons_by_spec = {
            spec: _merge_polygon_points(polygons)
            for spec, polygons in polygons_by_spec.items()
        }

    bbox = cell.bounding_box()
    (min_x, min_y), (max_x, max_y) = bbox
    bounds = normalized_crop_region or (float(min_x), float(min_y), float(max_x), float(max_y))

    resolved_context = _ResolvedGdsfactoryContext(None, None, None)
    if isinstance(technology, Technology):
        resolved_technology: Technology | None = technology
    elif technology is not None:
        resolved_technology = Technology.from_layer_styles(technology, name="inline")
    else:
        resolved_technology = None

    base_styles = resolved_technology.layer_styles(include_hidden=True) if resolved_technology is not None else {}
    base_styles.update(normalize_layer_stack(layer_styles))
    if not base_styles and gds3d_techfile is not None:
        base_styles = parse_gds3d_techfile(
            gds3d_techfile,
            unit_scale=gds3d_unit_scale,
            include_hidden=include_hidden,
        )
        resolved_technology = Technology.from_layer_styles(
            base_styles,
            name=Path(gds3d_techfile).stem,
            source=Path(gds3d_techfile).expanduser().as_posix(),
            metadata={"format": "gds3d-techfile"},
        )
    if not base_styles:
        if pdk is not None:
            resolved_context = _resolve_gdsfactory_context(pdk=pdk)
            base_styles = get_gdsfactory_layer_styles(
                pdk=resolved_context.pdk,
                layers=layers,
                layer_stack=resolved_context.layer_stack,
                layer_views=resolved_context.layer_views,
                aux_layer_depths=aux_layer_depths,
            )
        elif layers is None:
            resolved_context = _resolve_gdsfactory_context()
            base_styles = get_gdsfactory_layer_styles(
                pdk=resolved_context.pdk,
                layer_stack=resolved_context.layer_stack,
                layer_views=resolved_context.layer_views,
                aux_layer_depths=aux_layer_depths,
            )
    override_styles = normalize_layer_stack(layer_style_overrides)
    name_map = resolved_technology.layer_name_map() if resolved_technology is not None else get_layer_name_map(layers if layers is not None else pdk)

    fallback_z = max(
        (
            float(style.get("zmin", style.get("z_offset", 0.0)))
            + float(style.get("thickness", fallback_thickness))
            for style in base_styles.values()
            if style.get("visible", True) is not False
        ),
        default=0.0,
    ) + 0.15

    _warn_unstyled(
        spec for spec in polygons_by_spec
        if not base_styles.get(spec) and not override_styles.get(spec)
    )

    records: list[GDSLayerRecord] = []
    for index, (spec, polygons) in enumerate(sorted(polygons_by_spec.items())):
        base = dict(base_styles.get(spec, {}))
        override = dict(override_styles.get(spec, {}))
        default_name = name_map.get(spec, f"L{spec[0]}/{spec[1]}")
        fallback_material = material_preset_from_layer_name(default_name) or fallback_material_preset
        fallback_style = {
            "name": default_name,
            "color": GDS_LAYER_PALETTE[index % len(GDS_LAYER_PALETTE)],
            "thickness": fallback_thickness,
            "zmin": fallback_z,
            "material_preset": fallback_material,
            "visible": True,
            "style_source": "fallback",
        }
        combined = {**(base if base else fallback_style), **override}
        if base.get("visible") is False or override.get("visible") is False:
            combined["visible"] = False
        supplied = {**base, **override}
        physical_stack_known = supplied.get("physical_stack_known")
        if physical_stack_known is None:
            physical_stack_known = (
                coerce_scalar(supplied.get("thickness")) is not None
                and coerce_scalar(supplied.get("zmin", supplied.get("z_offset"))) is not None
            )

        if combined.get("visible") is False and not include_hidden:
            continue

        matched_pdk = bool(base)
        if base and override:
            style_source = "pdk+override"
        elif base:
            style_source = str(base.get("style_source", "pdk"))
        elif override:
            style_source = "override"
        else:
            style_source = "fallback"
        combined["style_source"] = style_source

        name = combined.get("name", default_name)
        material_preset = combined.get("material_preset", combined.get("preset", fallback_material_preset))
        if not isinstance(material_preset, str) or not material_preset:
            material_preset = material_preset_from_layer_name(name) or fallback_material_preset

        opacity_value = coerce_scalar(combined.get("opacity"))
        if opacity_value is None:
            opacity_value = 0.34 if material_preset == "sio2" else 0.78

        thickness_value = coerce_scalar(combined.get("thickness"))
        thickness = float(thickness_value if thickness_value is not None else fallback_thickness)

        zmin_value = coerce_scalar(combined.get("zmin", combined.get("z_offset")))
        zmin = float(zmin_value if zmin_value is not None else 0.0)
        if not base:
            fallback_z = max(fallback_z, zmin + thickness + fallback_layer_gap)

        name = combined.get("name", name_map.get(spec, combined.get("level_name", default_name)))
        material_name = combined.get("material") if isinstance(combined.get("material"), str) else None
        description = combined.get(
            "description",
            _format_layer_description(
                spec,
                name=name,
                material_name=material_name,
                material_preset=material_preset,
                thickness=thickness,
                zmin=zmin,
                source_label=style_source.upper(),
            ),
        )

        records.append(
            GDSLayerRecord(
                spec=spec,
                name=name,
                description=description,
                color=combined.get("fill", combined.get("color", GDS_LAYER_PALETTE[index % len(GDS_LAYER_PALETTE)])),
                opacity=float(opacity_value),
                thickness=thickness,
                zmin=zmin,
                material_preset=material_preset,
                polygons=polygons,
                matched_pdk=matched_pdk,
                visible=combined.get("visible", True) is not False,
                material_name=material_name,
                level_name=combined.get("level_name"),
                style_source=style_source,
                physical_stack_known=bool(physical_stack_known),
            )
        )

    return GDSLayout(
        source_path=path,
        cell_name=cell.name,
        bounds=bounds,
        layer_records=records,
        technology=resolved_technology,
        gdsfactory_layer_stack=resolved_context.layer_stack,
        gdsfactory_layer_views=resolved_context.layer_views,
        crop_region=normalized_crop_region,
    )
