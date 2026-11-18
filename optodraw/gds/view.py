"""The vector top view of a GDS crop: each layer clipped to a region and merged into one shape, in the colours of the
one material table. :class:`optodraw.figure.sources.GdsView` draws it into an inset."""

from __future__ import annotations

from os import PathLike
from typing import Any, Iterator

import shapely
from shapely.geometry import MultiPolygon, Polygon, box

from optodraw.gds.palette import canonical, material_fill
from optodraw.gds.parsers import LayerSpec, LayerStackSpec
from optodraw.gds.xsection.schematic import _INK

LINE_MM = 0.09              # 0.255 pt: the outline of each layer, 2 % over the 0.25 pt line-weight gate
GRID_UM = 1e-3              # the GDS grid: pieces snap to it before the union, so float noise on a shared edge merges
SHADE_STEP = 0.2            # a higher layer of one material is this much nearer the ink per level
SHADE_MOST = 0.8            # the shade stops here, so a fill never turns into its own outline

Region = tuple[float, float, float, float]


def _band(style: dict[str, Any]) -> tuple[float, float]:
    zmin = float(style.get("zmin") or 0.0)
    return zmin, zmin + float(style.get("thickness") or 0.0)


def _mix(color: str, ink: str, share: float) -> str:
    a, b = ([int(c[i:i + 2], 16) for i in (1, 3, 5)] for c in (color, ink))
    return "#" + "".join(f"{round(x + (y - x) * share):02x}" for x, y in zip(a, b))


def layer_fills(stack: LayerStackSpec) -> dict[LayerSpec, str]:
    """The fill of each layer: its material's colour (the stack's own first), mixed toward the ink by
    :data:`SHADE_STEP` for each lower band of the same material in the stack, so an LN ridge stands apart from its
    slab. An etch (air) stays white."""

    bands: dict[str, set[tuple[float, float]]] = {}
    for style in stack.styles.values():
        bands.setdefault(canonical(style.get("material_preset") or ""), set()).add(_band(style))
    fills = {}
    for key, style in stack.styles.items():
        material = canonical(style.get("material_preset") or "")
        fill = material_fill(material, stack.materials)
        level = sorted(bands[material]).index(_band(style))
        fills[key] = fill if material == "air" else _mix(fill, _INK, min(SHADE_STEP * level, SHADE_MOST))
    return fills


def _polygons(shape: Any) -> Iterator[Polygon]:
    if isinstance(shape, Polygon):
        if not shape.is_empty:
            yield shape
    else:
        for part in getattr(shape, "geoms", ()):
            yield from _polygons(part)


def layer_shapes(gds: str | PathLike[str], stack: LayerStackSpec, region: Region,
                 layers: tuple[LayerSpec, ...] | None = None, *, cell_name: str | None = None,
                 limit: int) -> list[tuple[LayerSpec, str, MultiPolygon]]:
    """``(layer, material, shape)`` for each layer drawn in ``region``: its polygons clipped to the region and merged
    on the :data:`GRID_UM` grid, so pieces of one layer that touch across cells give one shape with no seam.
    The order is the stack's, by ``zmin`` then by top. ``layers=None`` takes the stack's visible layers; a layer
    the stack lacks is left out. More than ``limit`` polygons in the region raise ValueError, counted before the
    merge."""

    from optodraw.gds.layout import load_gds_cell

    x0, y0, x1, y1 = region
    wanted = set(layers) if layers is not None else {
        key for key, style in stack.styles.items() if style.get("visible") is not False}
    found: dict[LayerSpec, list[Any]] = {}
    for polygon in load_gds_cell(gds, cell_name).get_polygons():
        key = (int(polygon.layer), int(polygon.datatype))
        (bx0, by0), (bx1, by1) = polygon.bounding_box()
        if key in wanted and bx0 < x1 and bx1 > x0 and by0 < y1 and by1 > y0:
            found.setdefault(key, []).append(polygon.points)
    count = sum(len(points) for points in found.values())
    if count > limit:
        raise ValueError(f"GdsView: {count} polygons in the region (limit {limit}): pass a smaller region= or fewer "
                         "layers=")
    window = box(x0, y0, x1, y1)
    shapes = []
    for key in sorted(found, key=lambda key: (_band(stack.styles[key]), key)):
        pieces = [Polygon(points) for points in found[key]]
        merged = shapely.union_all([(p if p.is_valid else shapely.make_valid(p)).intersection(window) for p in pieces],
                                   grid_size=GRID_UM)
        shapes.append((key, str(stack.styles[key].get("material_preset") or ""), MultiPolygon(list(_polygons(merged)))))
    return shapes


def view_svg(shapes: list[tuple[LayerSpec, str, MultiPolygon]], stack: LayerStackSpec, region: Region,
             width_mm: float) -> str:
    """One SVG root ``width_mm`` wide in mm: one ``<path data-layer="2/0">`` per shape, y down, file x0 at 0."""

    x0, y0, x1, y1 = region
    k = width_mm / (x1 - x0)
    tall = (y1 - y0) * k
    fills = layer_fills(stack)

    def ring(line: Any) -> str:
        return "M" + "L".join(f"{(x - x0) * k:.3f} {(y1 - y) * k:.3f}" for x, y in line.coords[:-1]) + "Z"

    def outline(shape: MultiPolygon) -> str:
        return "".join(ring(line) for part in shape.geoms for line in (part.exterior, *part.interiors))

    paths = "".join(f'<path data-layer="{key[0]}/{key[1]}" d="{outline(shape)}" fill="{fills[key]}" '
                    f'fill-rule="evenodd" stroke="{_INK}" stroke-width="{LINE_MM}"/>'
                    for key, _, shape in shapes if not shape.is_empty)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width_mm:.6g}mm" height="{tall:.6g}mm" '
            f'viewBox="0 0 {width_mm:.6g} {tall:.6g}">{paths}</svg>')
