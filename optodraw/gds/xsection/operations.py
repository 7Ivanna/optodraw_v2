"""Process operations: deposit, etch, planarize, implant, fill, flip, snapshot."""

from __future__ import annotations

import math
from typing import Any

from shapely import affinity
from shapely.geometry import MultiPolygon, Polygon
from shapely.ops import unary_union

from optodraw.gds.xsection.masks import IntervalSet, LayoutCut
from optodraw.gds.xsection.regions import (
    RegionStack,
    extrude_mask,
    rectangle,
    region_bottom,
    region_top,
    repair,
)


_FLAT = 1e-3                      # the conformality of a directional deposit: a near-vertical ellipse
_PAST = 1e-6                      # um an etch reaches past the top it starts from, so no sliver stays above it


def _grown(seed: MultiPolygon, thickness: float, conformality: float) -> MultiPolygon:
    """``seed`` grown by an ellipse: ``thickness`` up and down, ``conformality * thickness`` sideways."""

    c = min(max(float(conformality), _FLAT), 1.0)
    wide = affinity.scale(seed, xfact=1.0 / c, yfact=1.0, origin=(0.0, 0.0))
    return repair(affinity.scale(wide.buffer(thickness, quad_segs=16), xfact=c, yfact=1.0, origin=(0.0, 0.0)))


def apply_deposit(stack: RegionStack, cut: LayoutCut, mask: IntervalSet | None, params: dict[str, Any]) -> None:
    """A film ``thickness`` thick on every exposed surface (or only on the regions ``on``), ``conformality``
    of it on the walls, into region ``material``. A mask keeps it to its columns (lift-off)."""

    del cut                                                  # the solid gives the extent
    material = str(params.get("material", "deposit"))
    thickness = float(params.get("thickness", 0.0))
    if thickness <= 0 or (mask is not None and mask.is_empty()):
        return
    solid = stack.solid()
    on = [str(name) for name in params.get("on", [])]
    seed = stack.resolve_targets(on) if on else solid
    if seed.is_empty:
        return
    y0, floor, y1, top = solid.bounds
    space = rectangle(y0, y1, floor, top + thickness + 1.0).difference(solid)
    added = _grown(seed, thickness, float(params.get("conformality", 1.0))).intersection(space)
    if mask is not None:
        added = added.intersection(extrude_mask(mask, floor, top + thickness + 1.0))
    # only film that touches what it grew on: never a sheet past a thin layer in between
    added = repair(MultiPolygon([piece for piece in repair(added).geoms if piece.distance(seed) < 1e-6]))
    stack.add(material, added, str(params.get("material_key", material)))


def apply_etch(stack: RegionStack, cut: LayoutCut, mask: IntervalSet | None, params: dict[str, Any]) -> None:
    """Remove the ``into`` regions under the mask, from their top in each column down by ``depth``, or down to
    the top of ``stop_on`` there, or down to the height ``to_z``, or all of them with ``through`` (a film
    patterned to its mask, whatever it rose over). ``sidewall_deg`` below 90 narrows the trench with depth."""

    if mask is None or mask.is_empty():
        return
    # a mask that runs to the window edge has no wall there: carry it past the edge, so a tapered etch stays
    # vertical at the edge of the figure and leaves no wedge behind
    reach = 10.0 * max(cut.y_max - cut.y_min, 1.0)
    mask = IntervalSet.from_intervals([(item.y0 - reach if item.y0 <= cut.y_min + 1e-9 else item.y0,
                                        item.y1 + reach if item.y1 >= cut.y_max - 1e-9 else item.y1)
                                       for item in mask.intervals])
    into = [str(name) for name in params.get("into", ["device"])]
    stop_on = [str(name) for name in params.get("stop_on", [])]
    depth = params.get("depth")
    to_z = params.get("to_z")
    through = bool(params.get("through", False))
    if depth is None and not stop_on and not through and to_z is None:
        raise ValueError("an etch needs a depth, a stop_on region, a to_z height or through")
    sidewall = 90.0 - float(params["taper_deg"]) if "taper_deg" in params else float(params.get("sidewall_deg", 90.0))
    bias = float(params.get("bias_um", 0.0))
    if bias > 0:
        mask = IntervalSet.from_intervals([(item.y0 - bias, item.y1 + bias) for item in mask.intervals])
    targets = stack.resolve_targets(into)
    if targets.is_empty:
        return
    stop = stack.resolve_targets(stop_on) if stop_on else MultiPolygon([])
    _, floor, _, top = stack.solid().bounds
    removal = []
    for item in mask.intervals:
        column = rectangle(item.y0, item.y1, floor - 1.0, top + 1.0)
        here = targets.intersection(column)
        if here.is_empty:
            continue
        z_top = here.bounds[3]
        under = stop.intersection(column)
        if not under.is_empty:
            z_floor = under.bounds[3]
        elif through:
            z_floor = here.bounds[1]
        elif to_z is not None:
            z_floor = float(to_z)
        elif depth is not None:
            z_floor = z_top - float(depth)
        else:
            z_floor = here.bounds[1]
        if z_floor >= z_top:
            continue
        if through:                     # a film's faces can tilt by a float step: reach past both of them
            z_floor -= _PAST
        removal.append(_tapered_extrusion(IntervalSet.from_intervals([(item.y0, item.y1)]), z_floor, z_top + _PAST,
                                          max(0.0, 90.0 - sidewall), wide_at_top=True))
    if removal:
        stack.difference_from(into, repair(unary_union(removal)))


def apply_planarize(stack: RegionStack, cut: LayoutCut, params: dict[str, Any]) -> None:
    """CMP: remove the ``into`` regions (every region when none is named) above ``to_z``. It adds nothing."""

    del cut
    to_z = float(params["to_z"])
    names = [str(name) for name in params.get("into", [])] or list(stack.regions)
    solid = stack.solid()
    if solid.is_empty:
        return
    y0, _, y1, top = solid.bounds
    if top <= to_z:
        return
    stack.difference_from(names, rectangle(y0 - 1.0, y1 + 1.0, to_z, top + 1.0))


def apply_implant(stack: RegionStack, cut: LayoutCut, mask: IntervalSet | None, params: dict[str, Any]) -> None:
    """Dope the ``into`` regions under the mask, between ``zmin`` and ``zmax`` when given. The material stays."""

    del cut
    if mask is None or mask.is_empty():
        return
    target = stack.resolve_targets([str(name) for name in params.get("into", ["device"])])
    if target.is_empty:
        return
    z0 = max(float(params.get("zmin", -math.inf)), region_bottom(target))
    z1 = min(float(params.get("zmax", math.inf)), region_top(target))
    if z1 <= z0:
        return
    species = str(params.get("species", "implant"))
    dose = repair(target.intersection(extrude_mask(mask, z0, z1)))
    if dose.is_empty:
        return
    stack.doping[species] = repair(unary_union([stack.doping.get(species, MultiPolygon([])), dose]))


def apply_fill(stack: RegionStack, cut: LayoutCut, params: dict[str, Any]) -> None:
    """Fill to a flat top at ``to_z``: a conformal film thick enough to close every gap, then CMP of that film
    only. A part that stands higher keeps the height its layer gives it."""

    material = str(params.get("material", "fill"))
    to_z = float(params["to_z"])
    solid = stack.solid()
    if solid.is_empty or to_z <= solid.bounds[1]:
        return
    apply_deposit(stack, cut, None, {"material": material, "thickness": to_z - solid.bounds[1],
                                     "conformality": 1.0, "material_key": params.get("material_key", material)})
    apply_planarize(stack, cut, {"to_z": to_z, "into": [material]})


def apply_flip(stack: RegionStack) -> None:
    if not stack.regions:
        return
    all_geoms = [geom for geom in stack.regions.values() if not geom.is_empty]
    if not all_geoms:
        return
    merged = unary_union(all_geoms)
    _, z_min, _, z_max = merged.bounds
    pivot = (z_min + z_max) / 2.0

    def flip_geom(geometry: MultiPolygon) -> MultiPolygon:
        if geometry.is_empty:
            return MultiPolygon([])
        flipped = []
        for poly in geometry.geoms:
            shell = [(y, 2 * pivot - z) for y, z in poly.exterior.coords]
            holes = [[(y, 2 * pivot - z) for y, z in ring.coords] for ring in poly.interiors]
            flipped.append(repair(type(poly)(shell, holes)))
        return repair(unary_union(flipped))

    for name, geometry in stack.regions.items():
        stack.set(name, flip_geom(geometry))


def apply_snapshot(stack: RegionStack, alias: str, source: str = "device") -> None:
    stack.snapshot(source, alias)


def _tapered_extrusion(
    mask: IntervalSet, z0: float, z1: float, taper_deg: float, *, wide_at_top: bool = False
) -> MultiPolygon:
    if z1 < z0:
        z0, z1 = z1, z0
    delta_z = z1 - z0
    inset = math.tan(math.radians(taper_deg)) * delta_z
    pieces = []
    for item in mask.intervals:
        width = item.y1 - item.y0
        if inset <= 0 or width <= 0:
            pieces.append(rectangle(item.y0, item.y1, z0, z1))
            continue
        if wide_at_top:
            bottom_y0, bottom_y1 = item.y0 + inset, item.y1 - inset
            if bottom_y1 > bottom_y0:
                wall = [(bottom_y0, z0), (bottom_y1, z0), (item.y1, z1), (item.y0, z1)]
            else:
                slope = math.tan(math.radians(taper_deg))
                pinch_z = z1 - (width / 2.0) / slope
                mid = (item.y0 + item.y1) / 2.0
                wall = [(mid, max(pinch_z, z0)), (item.y1, z1), (item.y0, z1)]
            pieces.append(repair(Polygon(wall)))
            continue
        top_y0, top_y1 = item.y0 + inset, item.y1 - inset
        if top_y1 > top_y0:
            wall = [(item.y0, z0), (item.y1, z0), (top_y1, z1), (top_y0, z1)]
        else:
            # Walls meet before full depth: close as a triangle at the pinch height.
            slope = math.tan(math.radians(taper_deg))
            pinch_z = z0 + (width / 2.0) / slope if slope > 0 else z1
            mid = (item.y0 + item.y1) / 2.0
            wall = [(item.y0, z0), (item.y1, z0), (mid, min(pinch_z, z1))]
        pieces.append(repair(Polygon(wall)))
    if not pieces:
        return MultiPolygon([])
    return repair(unary_union(pieces))
