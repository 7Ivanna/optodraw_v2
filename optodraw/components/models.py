"""Imported 3D model components.

Supports browser-side GLTF/GLB/OBJ loading and a lightweight GDS footprint
component for photonic chip layouts.

For GDS-backed models, optodraw prefers the gdsfactory ecosystem for import and
interoperability, while keeping gdstk as a low-level fallback reader.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from os import PathLike
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from optodraw.core.component import Component
from optodraw.core.transform import Transform
from optodraw.gds import (
    GDS_LAYER_PALETTE as _GDS_LAYER_PALETTE,
    LayerSpec,
    coerce_scalar as _coerce_scalar,
    get_gdsfactory_layer_styles as _generic_pdk_layer_styles,
    load_bounds_from_source as _load_bounds_from_source,
    load_gds_geometry_from_source as _load_gds_geometry_from_source,
    normalize_layer_stack as _normalize_layer_stack,
)


def _guess_format(source: str) -> str:
    """Infer the external model format from a filename suffix."""

    suffix = Path(urlsplit(str(source)).path).suffix.lower()
    return {
        ".gltf": "gltf",
        ".glb": "glb",
        ".obj": "obj",
        ".gds": "gds",
    }.get(suffix, "gltf")


def _is_path_source(source: Any) -> bool:
    """Return true when ``source`` can be interpreted as a filesystem path."""

    return isinstance(source, (str, PathLike))


def _source_path(source: Any) -> str | None:
    """Normalize a path-like source to a POSIX string for render dictionaries."""

    if not _is_path_source(source):
        return None
    return Path(source).expanduser().as_posix()


def _source_label(source: Any) -> str:
    """Return a readable label for filepath or component-like sources."""

    source_path = _source_path(source)
    if source_path is not None:
        return Path(source_path).stem
    return getattr(source, "name", source.__class__.__name__)


@dataclass
class CustomModel(Component):
    """External GLTF/GLB/OBJ model."""

    component_type = "CustomModel"
    source: str = ""
    model_format: str = "gltf"
    scale: float = 1.0
    footprint: tuple[float, float] = (12.0, 12.0)
    height: float = 12.0

    def __init__(
        self,
        source: str,
        *,
        center=(0, 0),
        angle=0,
        model_format: str | None = None,
        scale: float = 1.0,
        footprint: tuple[float, float] = (12.0, 12.0),
        height: float = 12.0,
        **kwargs,
    ):
        """Create a placeholder for a browser-loaded 3D asset.

        Parameters
        ----------
        source : str
            Path or URL for the GLTF, GLB, OBJ, or similar asset.
        center, angle
            Component placement and rotation.
        model_format : str | None
            Explicit format override. When omitted, the suffix is used.
        scale : float
            Renderer scale factor applied to the imported asset.
        footprint : tuple[float, float]
            2D placeholder size and 3D width/depth hints.
        height : float
            3D height hint for fallback bounds.
        **kwargs
            Supports ``material_preset``, ``color``, ``opacity``, and ``label``.
        """

        # Path -> str keeps specs JSON-serializable; live objects pass through untouched.
        self.source = str(source) if isinstance(source, PathLike) else source
        self.model_format = model_format or _guess_format(source)
        self.scale = scale
        self.footprint = footprint
        self.height = height
        self.material_preset = kwargs.get("material_preset", "aluminum")
        self.color = kwargs.get("color", "#6c757d")
        self.opacity = kwargs.get("opacity", 1.0)
        self.label = kwargs.get("label", Path(urlsplit(str(source)).path).stem)
        self.transform = Transform.from_2d(*self._parse_center(center).as_2d(), angle)
        self._parent = None
        self._id = ""

    def geometry_2d(self) -> dict[str, Any]:
        """Return a 2D placeholder footprint for an external model."""

        width, height = self.footprint
        return {
            "type": "group",
            "children": [
                {"type": "rect", "cx": 0, "cy": 0, "w": width, "h": height, "fill": "#e9ecef", "stroke": self.color, "stroke_width": 0.8, "opacity": self.opacity},
                {"type": "line", "x1": -width / 2, "y1": -height / 2, "x2": width / 2, "y2": height / 2, "stroke": self.color, "stroke_width": 0.8, "opacity": self.opacity},
                {"type": "line", "x1": -width / 2, "y1": height / 2, "x2": width / 2, "y2": -height / 2, "stroke": self.color, "stroke_width": 0.8, "opacity": self.opacity},
            ],
        }

    def geometry_3d(self) -> dict[str, Any]:
        """Return external-model metadata for the Three.js renderer."""

        return {
            "shape": "external_model",
            "source": self.source,
            "format": self.model_format,
            "scale": self.scale,
            "width": self.footprint[0],
            "depth": self.footprint[1],
            "height": self.height,
            "material": {"color": self.color, "opacity": self.opacity, "preset": self.material_preset},
        }


@dataclass
class GDSModel(Component):
    """A lightweight imported GDS cell with real planar polygons when available.

    ``source`` may be a ``.gds`` filepath or a gdsfactory-style component-like
    object. Path-based import prefers gdsfactory for ecosystem interoperability
    and falls back to gdstk for polygon and low-level bounding-box extraction.
    Use ``layer_stack`` to assign per-layer colors, thicknesses, z offsets, and
    material presets for 3D rendering.
    """

    component_type = "GDSModel"
    source: Any = ""
    cell_name: str | None = None
    scale: float = 1.0
    footprint: tuple[float, float] = (50.0, 30.0)
    thickness: float = 0.22
    layer_stack: dict[LayerSpec, dict[str, Any]] = field(default_factory=dict)

    def __init__(
        self,
        source: Any,
        *,
        cell_name: str | None = None,
        center=(0, 0),
        angle=0,
        scale: float = 1.0,
        footprint: tuple[float, float] = (50.0, 30.0),
        thickness: float = 0.22,
        z_exaggeration: float = 1.0,
        process_context: bool = False,
        oxide_opacity: float = 0.12,
        handle_opacity: float = 1.0,
        context_edge_opacity: float = 0.9,
        box_depth: float = 2.0,
        cladding_top: float = 0.0,
        handle_thickness: float = 1.0,
        passivation: float = 0.0,
        passivation_material: str = "",
        layer_stack: dict[Any, dict[str, Any]] | None = None,
        crop_region: tuple[float, float, float, float] | None = None,
        **kwargs,
    ):
        """Create a renderable footprint from a GDS path or component-like object.

        Parameters
        ----------
        source : Any
            ``.gds`` path or an object accepted by the GDS loading helpers.
        cell_name : str | None
            Optional cell selection for multi-cell GDS files.
        center, angle
            Component placement and rotation.
        scale : float
            Coordinate scale applied while loading geometry and bounds.
        footprint : tuple[float, float]
            Fallback footprint when polygon extraction is unavailable.
        thickness : float
            Default extrusion height for 3D polygons.
        layer_stack : dict | None
            Optional per-layer style overrides keyed by layer spec.
        **kwargs
            Supports ``material_preset``, ``color``, ``opacity``, and ``label``.
        """

        # Path -> str keeps specs JSON-serializable; live objects (e.g. a gdsfactory
        # component) pass through untouched.
        self.source = str(source) if isinstance(source, PathLike) else source
        self.cell_name = cell_name
        self.scale = scale
        self.footprint = footprint
        self.thickness = thickness
        # Vertical exaggeration for the 3D view: GDS films are sub-micron yet masks
        # span tens of microns, so the z-stack is invisible at 1.0. Scale z + height
        # to reveal the layer structure (the 2D top view is unaffected).
        self.z_exaggeration = max(float(z_exaggeration), 0.0) or 1.0
        # When True, geometry_3d wraps the device in auto-generated SiO2 (buried
        # oxide + top cladding) on a handle-Si substrate, and subtracts the etch
        # openings (layers with material "air": OX_OPEN / deep trench). BOX/TOX are
        # process layers not drawn in the GDS, so they're synthesized here.
        self.process_context = bool(process_context)
        # process-context appearance controls (used when process_context is on)
        self.oxide_opacity = max(0.0, min(float(oxide_opacity), 1.0))
        self.handle_opacity = max(0.0, min(float(handle_opacity), 1.0))
        # opacity of the outline around the oxide / etched openings (0 = no outline)
        self.context_edge_opacity = max(0.0, min(float(context_edge_opacity), 1.0))
        # dielectric heights (um). cladding_top = 0 -> auto (top of the tallest layer);
        # set it explicitly for a foundry's real top-oxide surface (process-dependent).
        self.box_depth = max(0.0, float(box_depth))
        self.cladding_top = max(0.0, float(cladding_top))
        self.handle_thickness = max(0.0, float(handle_thickness))
        # the stack's passivation over the top metal (um, material): the cross-section draws it
        self.passivation = max(0.0, float(passivation))
        self.passivation_material = str(passivation_material or "")
        self.layer_stack = _normalize_layer_stack(layer_stack)
        if crop_region is not None:
            if len(crop_region) != 4 or not all(math.isfinite(float(value)) for value in crop_region):
                raise ValueError("crop_region must have four finite coordinates")
            x0, y0, x1, y1 = (float(value) for value in crop_region)
            if x0 >= x1 or y0 >= y1:
                raise ValueError("crop_region must have positive width and height")
            self.crop_region = (x0, y0, x1, y1)
        else:
            self.crop_region = None
        self.material_preset = kwargs.get("material_preset", "silicon")
        self.color = kwargs.get("color", "#0b7285")
        self.opacity = kwargs.get("opacity", 1.0)
        self.label = kwargs.get("label", cell_name or _source_label(source))
        self.transform = Transform.from_2d(*self._parse_center(center).as_2d(), angle)
        self._parent = None
        self._id = ""
        self._polygons_by_spec: dict[LayerSpec, list[list[tuple[float, float]]]] = {}
        self._inferred_layer_stack: dict[LayerSpec, dict[str, Any]] = {}
        self._empty_crop = False
        self._gds_origin: tuple[float, float] = (0.0, 0.0)  # the file point the part's frame centres on
        self._crop_shift: tuple[float, float] = (0.0, 0.0)  # and the further shift a crop makes
        self._gds_cell: str | None = None  # the cell the part read (its cell_name, else the chosen top cell)
        self._load_geometry_if_possible()
        from optodraw.gds.layout import _warn_unstyled

        _warn_unstyled(spec for spec in self._polygons_by_spec
                       if spec not in self.layer_stack and spec not in self._inferred_layer_stack)

    def _load_geometry_if_possible(self) -> None:
        """Populate polygons and inferred styles when GDS geometry can be loaded."""

        geometry = _load_gds_geometry_from_source(self.source, self.cell_name, self.scale)
        if geometry is not None:
            self.footprint = geometry.footprint
            self._polygons_by_spec = geometry.polygons_by_spec
            self._gds_origin = (float(geometry.origin[0]), float(geometry.origin[1]))
            self._gds_cell = geometry.cell_name
            inferred_styles = _generic_pdk_layer_styles(aux_layer_depths={})
            self._inferred_layer_stack = {
                spec: inferred_styles[spec] for spec in self._polygons_by_spec if spec in inferred_styles
            }
            if self.crop_region is not None:
                from optodraw.gds.layout import _clip_polygon_to_rect

                x0, y0, x1, y1 = self.crop_region
                origin_x, origin_y = geometry.origin
                scaled_x = ((x0 - origin_x) * self.scale, (x1 - origin_x) * self.scale)
                scaled_y = ((y0 - origin_y) * self.scale, (y1 - origin_y) * self.scale)
                local_crop = (min(scaled_x), min(scaled_y), max(scaled_x), max(scaled_y))
                shift_x = ((x0 + x1) / 2.0 - origin_x) * self.scale
                shift_y = ((y0 + y1) / 2.0 - origin_y) * self.scale
                self._crop_shift = (shift_x, shift_y)
                cropped: dict[LayerSpec, list[list[tuple[float, float]]]] = {}
                for spec, polygons in self._polygons_by_spec.items():
                    clipped = [_clip_polygon_to_rect(polygon, local_crop) for polygon in polygons]
                    kept = [
                        [(x - shift_x, y - shift_y) for x, y in polygon]
                        for polygon in clipped if polygon is not None
                    ]
                    if kept:
                        cropped[spec] = kept
                self._polygons_by_spec = cropped
                self._empty_crop = not bool(cropped)
                self.footprint = ((x1 - x0) * abs(self.scale), (y1 - y0) * abs(self.scale))
                return
            fp = self._floorplan_bounds()
            if fp is not None:  # the die boundary defines the footprint, not the drawn extent
                self.footprint = (abs(fp[2] - fp[0]), abs(fp[3] - fp[1]))
            return
        self._load_bounds_if_possible()
        if self.crop_region is not None:
            x0, y0, x1, y1 = self.crop_region
            self.footprint = ((x1 - x0) * abs(self.scale), (y1 - y0) * abs(self.scale))

    def _load_bounds_if_possible(self) -> None:
        """Use available GDS bounds as the fallback footprint."""

        bounds = _load_bounds_from_source(self.source, self.cell_name, self.scale)
        if bounds is not None:
            self.footprint = bounds

    def _sorted_layer_items(self) -> list[tuple[LayerSpec, list[list[tuple[float, float]]]]]:
        """Return loaded GDS polygons in deterministic layer order."""

        return [(spec, self._polygons_by_spec[spec]) for spec in sorted(self._polygons_by_spec)]

    def _resolve_layer_style(self, spec: LayerSpec, index: int, layer_count: int) -> dict[str, Any]:
        """Merge inferred PDK style, explicit layer overrides, and defaults."""

        base = self._inferred_layer_stack.get(spec, {})
        override = self.layer_stack.get(spec, {})
        combined = {**base, **override}
        if base.get("visible") is False or override.get("visible") is False:
            combined["visible"] = False
        if combined.get("visible") is False:
            return {"visible": False}

        color_default = self.color if index == 0 else _GDS_LAYER_PALETTE[(index - 1) % len(_GDS_LAYER_PALETTE)]

        opacity = _coerce_scalar(combined.get("opacity"))
        if opacity is None:
            opacity = self.opacity if layer_count <= 1 else min(self.opacity, 0.8)

        stroke_width = _coerce_scalar(combined.get("stroke_width"))
        if stroke_width is None:
            stroke_width = 0.08

        thickness = _coerce_scalar(combined.get("thickness"))
        if thickness is None:
            thickness = self.thickness if layer_count <= 1 or index == 0 else max(self.thickness * 0.6, 0.06)

        z_offset = _coerce_scalar(combined.get("z_offset"))
        if z_offset is None:
            z_offset = _coerce_scalar(combined.get("zmin"))

        return {
            "visible": True,
            "color": combined.get("fill", combined.get("color", color_default)),
            "opacity": float(opacity),
            "stroke": combined.get("stroke", "#1f2937"),
            "stroke_width": float(stroke_width),
            "thickness": float(thickness),
            "z_offset": z_offset,
            "material_preset": combined.get("material_preset", combined.get("preset", self.material_preset)),
        }

    def file_to_local(self, x: float, y: float) -> tuple[float, float]:
        """A point of the GDS file (microns, as the layout view's ruler gives it) in the part's own frame: the
        cell's bounding box centred, scaled, and shifted again by a crop (the frame cuts are made in)."""

        (ox, oy), (sx, sy) = self._gds_origin, self._crop_shift
        return ((float(x) - ox) * self.scale - sx, (float(y) - oy) * self.scale - sy)

    def local_to_file(self, x: float, y: float) -> tuple[float, float]:
        """A point of the part's own frame in the GDS file's frame (the inverse of ``file_to_local``)."""

        (ox, oy), (sx, sy) = self._gds_origin, self._crop_shift
        return ((float(x) + sx) / self.scale + ox, (float(y) + sy) / self.scale + oy)

    def layout_cell(self) -> str | None:
        """The cell the part shows: its ``cell_name``, else the top cell the loader chose (the one with the most
        geometry when the file has several), so the layout view draws what the part holds."""

        return self.cell_name or self._gds_cell

    def layout_lyp(self) -> str:
        """The part's layer colours and names as a KLayout .lyp: each drawn layer with the colour the 3D view
        gives it (the merged stack), its name, and its frame colour when the stack sets one."""

        from optodraw.gds.lyp import stack_to_lyp

        items = self._sorted_layer_items()
        styles = {}
        for index, (spec, _) in enumerate(items):
            raw = {**self._inferred_layer_stack.get(spec, {}), **self.layer_stack.get(spec, {})}
            style = self._resolve_layer_style(spec, index, len(items))
            styles[spec] = {"name": raw.get("name") or f"{spec[0]}/{spec[1]}", "visible": style.get("visible", True),
                            "color": style.get("color") or raw.get("color"), "stroke": raw.get("stroke")}
        return stack_to_lyp(styles)

    def layout_view(self, width: int = 900, height: int = 600):
        """The part's layout in GDS Lens, for a notebook cell (``_repr_html_``) or a file (``save``): zoom with
        the wheel, pan by dragging, the cell tree, the layers in the part's colours, a ruler (M)."""

        from optodraw.gds.layout import _source_path
        from optodraw.gds.layout_view import LayoutPreview, layout_html

        path = _source_path(self.source)
        if path is None:
            raise ValueError("the layout view needs an imported GDS file; this part has no file source")
        html = layout_html(path, cell=self.layout_cell(), lyp=self.layout_lyp(),
                           title=str(getattr(self, "label", "") or Path(path).name))
        return LayoutPreview(html, width=width, height=height)

    def layer_records(self) -> list[dict[str, Any]]:
        """Return one record per loaded GDS layer for the editor's layer panel.

        Each record is JSON-safe (string ``key`` like ``"1/0"``) and reflects the
        merged inferred PDK style + user overrides (``layer_stack``). The editor
        edits visibility/color/thickness/z by writing back into ``layer_stack``.
        ``thickness`` and ``z`` are None when no height is assigned (neither the
        stack nor the generic styles give one), and ``material`` is None when no
        material is: never a made-up default such as the part's own preset.
        """

        records: list[dict[str, Any]] = []
        items = self._sorted_layer_items()
        for index, (spec, polygons) in enumerate(items):
            base = self._inferred_layer_stack.get(spec, {})
            override = self.layer_stack.get(spec, {})
            combined = {**base, **override}
            visible = not (base.get("visible") is False or override.get("visible") is False)
            color_default = self.color if index == 0 else _GDS_LAYER_PALETTE[(index - 1) % len(_GDS_LAYER_PALETTE)]
            thickness = _coerce_scalar(combined.get("thickness"))
            z = _coerce_scalar(combined.get("z_offset", combined.get("zmin")))
            opacity = _coerce_scalar(combined.get("opacity"))
            records.append(
                {
                    "key": f"{spec[0]}/{spec[1]}",
                    "layer": spec[0],
                    "datatype": spec[1],
                    "name": combined.get("name") or combined.get("material_preset") or f"L{spec[0]}/{spec[1]}",
                    "material": combined.get("material_preset", combined.get("preset")),
                    "color": combined.get("fill", combined.get("color", color_default)),
                    "opacity": float(opacity) if opacity is not None else self.opacity,
                    "thickness": float(thickness) if thickness is not None else None,
                    "z": float(z) if z is not None else None,
                    "visible": visible,
                    "polygon_count": len(polygons),
                }
            )
        return records

    def layers_without_height(self) -> list[str]:
        """The keys (``"20/0"``) of the shown layers with no height assigned: no thickness or no z in the stack
        or the generic styles. The 3D view and the GLB leave them out, never draw them at a made-up height."""

        return [r["key"] for r in self.layer_records()
                if r["visible"] and (r["thickness"] is None or r["z"] is None)]

    def _fallback_geometry_2d(self) -> dict[str, Any]:
        """Return a hatched footprint when real GDS polygons are unavailable."""

        width, height = self.footprint
        spacing = max(min(width, height) / 8.0, 1.0)
        children = [
            {"type": "rect", "cx": 0, "cy": 0, "w": width, "h": height, "fill": "#dff3f7", "stroke": self.color, "stroke_width": 0.8, "opacity": self.opacity},
        ]
        x = -width / 2 + spacing
        while x < width / 2:
            end_x = min(x + height, width / 2)
            end_y = -height / 2 + (end_x - x)
            children.append({"type": "line", "x1": x, "y1": -height / 2, "x2": end_x, "y2": end_y, "stroke": self.color, "stroke_width": 0.5, "opacity": 0.35})
            x += spacing
        return {"type": "group", "children": children}

    def _fallback_geometry_3d(self) -> dict[str, Any]:
        """Return a simple 3D slab when real GDS polygons are unavailable."""

        width, depth = self.footprint
        return {
            "shape": "box",
            "width": width,
            "height": self.thickness,
            "depth": depth,
            "material": {"color": self.color, "opacity": self.opacity, "preset": self.material_preset},
        }

    def geometry_2d(self) -> dict[str, Any]:
        """Return imported GDS polygons or a fallback footprint."""

        if not self._polygons_by_spec:
            if self._empty_crop:
                return {"type": "group", "children": []}
            return self._fallback_geometry_2d()

        children: list[dict[str, Any]] = []
        layer_items = self._sorted_layer_items()
        for index, (spec, polygons) in enumerate(layer_items):
            style = self._resolve_layer_style(spec, index, len(layer_items))
            if not style.get("visible", True):
                continue

            for polygon in polygons:
                children.append(
                    {
                        "type": "polygon",
                        "points": [(x, y, 0.0) for x, y in polygon],
                        "fill": style["color"],
                        "opacity": style["opacity"],
                        "stroke": style["stroke"],
                        "stroke_width": style["stroke_width"],
                    }
                )

        return {"type": "group", "children": children}

    def geometry_3d(self) -> dict[str, Any]:
        """Return extruded GDS polygons or a fallback 3D footprint."""

        if not self._polygons_by_spec:
            if self._empty_crop:
                return {"shape": "group", "children": []}
            return self._fallback_geometry_3d()

        children: list[dict[str, Any]] = []
        exaggeration = getattr(self, "z_exaggeration", 1.0) or 1.0
        unassigned = set(self.layers_without_height())
        layer_items = self._sorted_layer_items()
        for index, (spec, polygons) in enumerate(layer_items):
            style = self._resolve_layer_style(spec, index, len(layer_items))
            if not style.get("visible", True) or f"{spec[0]}/{spec[1]}" in unassigned:
                continue
            # with process context on, etch openings are carved from the oxide
            # (below) instead of drawn as solid prisms
            if self.process_context and style.get("material_preset") == "air":
                continue

            thickness = float(style["thickness"]) * exaggeration
            z_offset = float(style["z_offset"]) * exaggeration

            for polygon in polygons:
                child: dict[str, Any] = {
                    "shape": "extruded_polygon",
                    "points": [(x, y, 0.0) for x, y in polygon],
                    "height": thickness,
                    "material": {
                        "color": style["color"],
                        "opacity": style["opacity"],
                        "preset": style["material_preset"],
                    },
                }
                if abs(z_offset) > 1e-12:
                    child["position"] = [0.0, z_offset, 0.0]
                children.append(child)

        if self.process_context:
            children = self._process_context_children(exaggeration) + children

        return {"shape": "group", "children": children}

    def _floorplan_bounds(self) -> tuple[float, float, float, float] | None:
        """The die boundary from an explicit FloorPlan / Chip-design-area layer, if the
        design has one — so the oxide/substrate ends at the real chip edge (and an edge
        coupler at the facet isn't buried under cladding) instead of being estimated from
        the drawn geometry. ``None`` when there's no such layer."""

        ls = self.layer_stack if isinstance(self.layer_stack, dict) else {}
        for spec, polygons in self._polygons_by_spec.items():
            if not polygons:
                continue
            style = ls.get(f"{spec[0]}/{spec[1]}") or ls.get(spec) or ls.get(tuple(spec)) or {}
            name = str(style.get("name") or "").strip().lower().replace(" ", "")
            if name in ("floorplan", "chipdesignarea") or tuple(spec) in ((99, 0), (290, 0)):
                xs = [p[0] for poly in polygons for p in poly]
                ys = [p[1] for poly in polygons for p in poly]
                if xs and ys:
                    return (min(xs), min(ys), max(xs), max(ys))
        return None

    def _etch_voids(self, exaggeration: float) -> list[tuple[Any, float, float]]:
        """``(plan union, z_bottom, z_top)`` of each shown etch layer (material "air": OX_OPEN / deep trench), in
        layer order: the holes the process context cuts."""

        from shapely.geometry import Polygon as _SPoly
        from shapely.ops import unary_union

        items = self._sorted_layer_items()
        unassigned = set(self.layers_without_height())
        voids: list[tuple[Any, float, float]] = []
        for index, (spec, polygons) in enumerate(items):
            style = self._resolve_layer_style(spec, index, len(items))
            if (style.get("material_preset") != "air" or not style.get("visible", True)
                    or f"{spec[0]}/{spec[1]}" in unassigned):
                continue
            shapes = []
            for poly in polygons:
                if len(poly) < 3:
                    continue
                sp = _SPoly(poly)
                shapes.append(sp if sp.is_valid else sp.buffer(0))
            if shapes:
                z = style["z_offset"]
                z = (float(z) * exaggeration) if z is not None else 0.0
                voids.append((unary_union(shapes), z, z + float(style["thickness"]) * exaggeration))
        return voids

    def process_context_regions(self, exaggeration: float = 1.0):
        """Yield ``(shapely_polygon, z_bottom, z_top, material)`` for the synthesized
        dielectric stack: a translucent SiO2 block (buried oxide + top cladding) on a
        handle-Si slab, with etch openings (layers whose material is "air": OX_OPEN /
        deep trench) subtracted as real holes. Shared by the WebGL + GLB exporters."""

        try:
            from shapely.geometry import Polygon as _SPoly
            from shapely.geometry import box as _sbox
            from shapely.ops import unary_union
        except ImportError:
            return

        from optodraw.gds.palette import canonical, is_metal, material_fill

        def _valid(poly):
            shape = _SPoly(poly)
            return shape if shape.is_valid else shape.buffer(0)

        items = self._sorted_layer_items()
        xs: list[float] = []
        ys: list[float] = []
        tops: list[float] = []
        metal_tops: list[float] = []
        pads: list[tuple[list, float]] = []   # (polygons, top) of the pad metal
        openings: list = []                    # the pad-opening layer's polygons: the etch down to the pads
        air_tops: list[float] = []    # etch layers end AT the oxide surface
        guide_tops: list[float] = []  # non-metal device layers (metal pads poke through)
        voids = self._etch_voids(exaggeration)  # (plan union, z_bottom, z_top); the pad windows join below
        unassigned = set(self.layers_without_height())  # not drawn, so they do not shape the oxide
        for index, (spec, polygons) in enumerate(items):
            role = str({**self._inferred_layer_stack.get(spec, {}), **self.layer_stack.get(spec, {})}.get("role")
                       or "").lower()
            if role == "pad_open":
                openings.extend(poly for poly in polygons if len(poly) >= 3)
            style = self._resolve_layer_style(spec, index, len(items))
            if not style.get("visible", True) or f"{spec[0]}/{spec[1]}" in unassigned:
                continue
            th = float(style["thickness"]) * exaggeration
            z = style["z_offset"]
            z = (float(z) * exaggeration) if z is not None else 0.0
            tops.append(z + th)
            preset = str(style.get("material_preset", "")).lower()
            if preset == "air":
                air_tops.append(z + th)
            elif not is_metal(preset):
                guide_tops.append(z + th)
            else:
                metal_tops.append(z + th)
                if role == "pad":
                    pads.append(([poly for poly in polygons if len(poly) >= 3], z + th))
            for poly in polygons:
                for x, y in poly:
                    xs.append(x)
                    ys.append(y)
        if not xs:
            return

        # Chip footprint: an explicit FloorPlan layer defines the real die edge (so the
        # oxide stops at the facet); otherwise pad the drawn-feature bbox a little so the
        # cladding extends past the device and the openings read as interior windows.
        fp = self._floorplan_bounds()
        if self.crop_region is not None:  # a crop is a piece of a chip: its edges are the crop's own edges
            half_w, half_h = self.footprint[0] / 2.0, self.footprint[1] / 2.0
            foot = _sbox(-half_w, -half_h, half_w, half_h)
        elif fp is not None:
            foot = _sbox(*fp)
        else:
            xmin, xmax, ymin, ymax = min(xs), max(xs), min(ys), max(ys)
            pad = max(2.0, 0.04 * max(xmax - xmin, ymax - ymin))
            foot = _sbox(xmin - pad, ymin - pad, xmax + pad, ymax + pad)
        # Top-oxide surface — the SAME resolution order as the stack loader so 3D,
        # cross-section, and GLB agree: an explicit cladding_top is AUTHORITATIVE
        # for the cladding (a metal may stand on it); auto mode derives from the etch
        # tops (etches end at the oxide surface), then the tallest non-metal device
        # layer, then the tallest layer. The cover over the top metal follows below.
        if self.cladding_top > 0:
            oxide_top = self.cladding_top * exaggeration
        elif air_tops and max(air_tops) > 0:
            oxide_top = max(air_tops)
        elif guide_tops:
            oxide_top = max(guide_tops) + 0.3 * exaggeration
        else:
            oxide_top = max(tops) if tops else 0.3 * exaggeration
        # The cover over the top metal, as the cross-section's process builds it: a passivation of the oxide's own
        # material is the last oxide level, so the oxide rises to the top metal's top plus its thickness round a
        # metal that stands above it, and by its thickness over a cladding that buries the metal. A passivation
        # of another material is a film of its own on an oxide flush with the top metal. The pad openings are
        # etched through the cover down to the pads.
        cover = max(0.0, float(self.passivation)) * exaggeration
        film = None
        if cover > 0:
            top_metal = max(metal_tops, default=oxide_top)
            if canonical(self.passivation_material or "silicon_nitride") == "sio2":
                oxide_top = top_metal + cover if top_metal > oxide_top + 1e-9 else oxide_top + cover
            else:
                oxide_top = max(oxide_top, top_metal)
                film = (oxide_top, oxide_top + cover)
            surface = film[1] if film else oxide_top
            opened = unary_union([_valid(poly) for poly in openings]) if openings else None
            for shapes, top in pads:
                pad = unary_union([_valid(poly) for poly in shapes])
                window = pad if opened is None else pad.intersection(opened)
                if not window.is_empty and top < surface:
                    voids.append((window, top, surface))
        box_depth = self.box_depth * exaggeration  # buried oxide
        handle = self.handle_thickness * exaggeration  # handle silicon
        deepest_void = min((z0 for _, z0, _ in voids), default=0.0)
        handle_bottom = min(-box_depth - handle, deepest_void - 0.3 * exaggeration)

        # (z_bottom, z_top, material) — bottom-up. The oxide is a light translucent
        # block (depthWrite off) so the device shows through; opacities + edge outline
        # are user-controllable via oxide_opacity / handle_opacity / context_edge_opacity.
        oxide_mat: dict[str, Any] = {"color": "#bcd4ea", "opacity": self.oxide_opacity, "depthWrite": False}
        if self.context_edge_opacity > 0:
            oxide_mat["edges"] = "#3f6fa3"
            oxide_mat["edge_opacity"] = self.context_edge_opacity
        regions = [
            (handle_bottom, -box_depth, {"color": "#8b97a4", "opacity": self.handle_opacity, "preset": "silicon"}),
            (-box_depth, oxide_top, oxide_mat),
        ]
        if film is not None:
            regions.append((film[0], film[1], {**oxide_mat, "color": material_fill(self.passivation_material
                                                                                    or "silicon_nitride")}))

        for r_bot, r_top, material in regions:
            # split the region into z-bands at the void boundaries, then subtract
            # the voids active in each band from the footprint (slab-with-holes)
            z_edges = {r_bot, r_top}
            for _, z0, z1 in voids:
                for zz in (z0, z1):
                    if r_bot < zz < r_top:
                        z_edges.add(zz)
            ordered = sorted(z_edges)
            for za, zb in zip(ordered[:-1], ordered[1:]):
                if zb - za < 1e-9:
                    continue
                zc = (za + zb) / 2.0
                active = [u for u, z0, z1 in voids if z0 < zc < z1]
                region = foot.difference(unary_union(active)) if active else foot
                if region.is_empty:
                    continue
                for g in getattr(region, "geoms", [region]):
                    if getattr(g, "geom_type", "") == "Polygon" and not g.is_empty:
                        yield g, za, zb, material

    def _process_context_children(self, exaggeration: float) -> list[dict[str, Any]]:
        """The synthesized dielectric stack as Three.js extruded-polygon children."""

        children: list[dict[str, Any]] = []
        for g, za, zb, material in self.process_context_regions(exaggeration):
            outer = [(x, y, 0.0) for x, y in list(g.exterior.coords)[:-1]]
            holes = [[(x, y, 0.0) for x, y in list(ring.coords)[:-1]] for ring in g.interiors]
            child: dict[str, Any] = {
                "shape": "extruded_polygon",
                "points": outer,
                "height": zb - za,
                "position": [0.0, za, 0.0],
                "material": {k: v for k, v in material.items() if k != "edges"},
            }
            if holes:
                child["holes"] = holes
            if material.get("edges"):
                child["edges"] = material["edges"]
                child["edge_opacity"] = material.get("edge_opacity", 1.0)
            children.append(child)
        return children
