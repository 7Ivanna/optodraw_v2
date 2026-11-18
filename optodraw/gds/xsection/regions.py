"""Shapely material regions in the (y, z) cross-section plane."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from shapely.geometry import MultiPolygon, Polygon, box
from shapely.ops import unary_union

from optodraw.gds.xsection.masks import IntervalSet


def repair(geometry: MultiPolygon | Polygon) -> MultiPolygon:
    if isinstance(geometry, Polygon):
        geometry = MultiPolygon([geometry])
    if geometry.is_empty:
        return MultiPolygon([])
    fixed = geometry.buffer(0)
    if isinstance(fixed, Polygon):
        return MultiPolygon([fixed])
    if isinstance(fixed, MultiPolygon):
        return fixed
    polygons: list[Polygon] = []

    def collect(part) -> None:
        if isinstance(part, Polygon):
            polygons.append(part)
        elif hasattr(part, "geoms"):
            for child in part.geoms:
                collect(child)

    collect(fixed)
    return MultiPolygon(polygons)


def rectangle(y0: float, y1: float, z0: float, z1: float) -> MultiPolygon:
    if y1 < y0:
        y0, y1 = y1, y0
    if z1 < z0:
        z0, z1 = z1, z0
    return repair(box(y0, z0, y1, z1))


def extrude_mask(mask: IntervalSet, z0: float, z1: float) -> MultiPolygon:
    pieces = [rectangle(item.y0, item.y1, z0, z1) for item in mask.intervals]
    if not pieces:
        return MultiPolygon([])
    return repair(unary_union(pieces))


def region_top(geometry: MultiPolygon, default: float = 0.0) -> float:
    if geometry.is_empty:
        return default
    return float(geometry.bounds[3])


def region_bottom(geometry: MultiPolygon, default: float = 0.0) -> float:
    if geometry.is_empty:
        return default
    return float(geometry.bounds[1])


def clip_to_z(geometry: MultiPolygon, z_min: float, z_max: float) -> MultiPolygon:
    if geometry.is_empty or z_max <= z_min:
        return MultiPolygon([])
    y_min, _, y_max, _ = geometry.bounds
    return repair(geometry.intersection(box(y_min, z_min, y_max, z_max)))


@dataclass
class RegionStack:
    regions: dict[str, MultiPolygon] = field(default_factory=dict)
    snapshots: dict[str, MultiPolygon] = field(default_factory=dict)
    materials: dict[str, str] = field(default_factory=dict)          # region -> palette key
    doping: dict[str, MultiPolygon] = field(default_factory=dict)    # species -> region inside the device layer

    def get(self, name: str) -> MultiPolygon:
        return self.regions.get(name, MultiPolygon([]))

    def set(self, name: str, geometry: MultiPolygon) -> None:
        self.regions[name] = repair(geometry)

    def add(self, name: str, geometry: MultiPolygon, material: str | None = None) -> None:
        """Union ``geometry`` into region ``name``; the first material given is the region's."""

        self.set(name, repair(unary_union([self.get(name), geometry])))
        if material is not None:
            self.materials.setdefault(name, material)

    def solid(self) -> MultiPolygon:
        """Everything made so far, as one region."""

        pieces = [geometry for geometry in self.regions.values() if not geometry.is_empty]
        return repair(unary_union(pieces)) if pieces else MultiPolygon([])

    def resolve_targets(self, names: Iterable[str]) -> MultiPolygon:
        pieces = [self.get(name) for name in names]
        nonempty = [piece for piece in pieces if not piece.is_empty]
        if not nonempty:
            return MultiPolygon([])
        return repair(unary_union(nonempty))

    def difference_from(self, target_names: Iterable[str], removal: MultiPolygon) -> None:
        if removal.is_empty:
            return
        for name in target_names:
            current = self.get(name)
            if current.is_empty:
                continue
            self.set(name, repair(current.difference(removal)))

    def snapshot(self, source: str, alias: str) -> None:
        self.snapshots[alias] = repair(self.get(source))
        self.set(alias, self.snapshots[alias])

    def copy(self) -> RegionStack:
        clone = RegionStack()
        clone.regions = {name: repair(geom) for name, geom in self.regions.items()}
        clone.snapshots = {name: repair(geom) for name, geom in self.snapshots.items()}
        clone.materials = dict(self.materials)
        clone.doping = {name: repair(geom) for name, geom in self.doping.items()}
        return clone
