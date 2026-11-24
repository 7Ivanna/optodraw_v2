"""Vendor parts drawn to scale: one class per family, the part number (``part``) picks the row of its table in
:mod:`optodraw.components.vendor.data`.

Each family extends the optodraw part it is (a lens, a lens tube, a filter, a beamsplitter...), so it keeps that
part's ports, 1D symbol and light behaviour; only its size and its 3D body come from the vendor's drawing. Scene
units are the bench scale, 2.54 mm (a 1 inch optic is 10 units).

Visualization only: clean-room geometry from published dimensions, no vendor CAD.
"""

from __future__ import annotations

import math
from typing import Any

from optodraw.core.component import Component
from optodraw.core.ports import Port
from optodraw.core.transform import Vec3

from ..optics._shared import (
    _KNOB_STEEL,
    _MOUNT_ALU,
    _MOUNT_BLACK,
    _cylinder_along_x,
    _post_boss,
    _ring_along_x,
    _set_common_free_space_fields,
)
from ..optics.beamsplitters import BeamSplitter, NonPolarizingBeamSplitter
from ..optics.cage import CageCube, CageRightAngleMirror, CageSize, cage_size
from ..optics.filters_modulators import Filter, NDFilter
from ..optics.lenses import Lens
from ..optics.mirrors import Mirror
from ..optics.polarization_optics import GlanLaserPolarizer, Polarizer, WavePlate
from . import data as D

MM = 1.0 / 2.54                                   # scene units per millimetre

GLASS = {"color": "#bcd7ea", "opacity": 0.45, "transparent": True, "preset": "glass"}
FLINT = {"color": "#a9c6de", "opacity": 0.5, "transparent": True, "preset": "glass"}
BLACK = _MOUNT_BLACK
ALU = _MOUNT_ALU
STEEL = _KNOB_STEEL
BRASS = {"color": "#c9a24a", "metalness": 0.7, "roughness": 0.35}
DARK = {"color": "#1b1e22", "metalness": 0.3, "roughness": 0.6}
GREY = {"color": "#6f757c", "metalness": 0.45, "roughness": 0.55}   # grey-anodised forks
GOLD = {"color": "#d4af37", "metalness": 0.8, "roughness": 0.3}


def _row(table: dict, part: str, family: str) -> dict:
    if part not in table:
        raise ValueError(f"{family}: unknown part {part!r}; known parts: {', '.join(sorted(table))}")
    return table[part]


# Numbers in a part's row that are not sizes: optical values, counts and spacings set by the standard.
_NOT_SIZES = frozenset({"efl", "bfl", "nm", "wavelength", "od_value", "count", "fins", "slots", "f", "cage",
                        "rt", "range", "rod", "rod_outer"})   # rod spacing is the cage standard (30 or 60 mm)
# signed: a lens surface's radius (the side its centre lies on) and an offset of the axis from a reference
_SIGNED = frozenset({"r", "axis_y"})
# What the items of a size list are, so each gets a readable name.
_LIST_ITEMS = {"stack": ("length", "od", "bore"), "body": ("length", "width", "height")}


def size_paths(table: dict) -> dict[str, tuple]:
    """Every size a family's rows can hold, by name (``length``, ``stack2_od``, ``body_width``, ``cell_od``,
    ``r1``...), and where it sits in a row: (key,), (key, i), (key, i, j) or (key, subkey)."""

    paths: dict[str, tuple] = {}
    for row in table.values():
        for key, value in row.items():
            if key in _NOT_SIZES or isinstance(value, bool):
                continue
            if isinstance(value, (int, float)):
                paths.setdefault(key, (key,))
            elif isinstance(value, dict):
                for sub, v in value.items():
                    if isinstance(v, (int, float)) and not isinstance(v, bool):
                        paths.setdefault(f"{key}_{sub}", (key, sub))
            elif isinstance(value, (list, tuple)) and value:
                names = _LIST_ITEMS.get(key)
                if all(isinstance(item, (list, tuple)) for item in value):          # a stack of rings
                    for i, item in enumerate(value):
                        for j, v in enumerate(item):
                            if isinstance(v, (int, float)) and not isinstance(v, bool):
                                name = names[j] if names and j < len(names) else str(j + 1)
                                paths.setdefault(f"{key}{i + 1}_{name}", (key, i, j))
                elif all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in value):
                    for i in range(len(value)):
                        name = f"{key}_{names[i]}" if names and i < len(names) else f"{key}{i + 1}"
                        paths.setdefault(name, (key, i))
    return paths


def _get(row: dict, path: tuple) -> float | None:
    value: Any = row.get(path[0])
    for step in path[1:]:
        if isinstance(value, dict):
            value = value.get(step)
        elif isinstance(value, (list, tuple)) and isinstance(step, int) and step < len(value):
            value = value[step]
        else:
            return None
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _set(row: dict, path: tuple, value: float) -> None:
    if len(path) == 1:
        row[path[0]] = value
        return
    holder = row[path[0]]
    if isinstance(holder, tuple):                    # a row may hold a tuple: this row is the part's own copy
        holder = row[path[0]] = list(holder)
    if len(path) == 3:
        item = list(holder[path[1]])
        item[path[2]] = value
        holder[path[1]] = item
    else:
        holder[path[1]] = value


class _Vendor:
    """The part-number bookkeeping every vendor family shares.

    The part number fills in every size from the vendor's drawing; each size can also be set by hand, in mm, as
    ``<size>_mm`` (``length_mm=40``, ``stack2_od_mm=31``): the part is then that part number with those sizes
    changed. ``sizes_changed`` lists them. The names a family takes are ``size_names()``."""

    TABLE: dict = {}
    DEFAULT_PART: str | None = None
    part: str = ""
    _SIZE_PATHS: dict[str, tuple] = {}

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if cls.TABLE:
            cls._SIZE_PATHS = size_paths(cls.TABLE)
        init = cls.__dict__.get("__init__")
        if init is None or getattr(init, "_takes_sizes", False):
            return
        import inspect

        default = inspect.signature(getattr(init, "__wrapped__", init)).parameters.get("part")
        default = default.default if default is not None and default.default is not inspect.Parameter.empty else None

        def __init__(self, *args: Any, _init=init, _default=default, **kw: Any) -> None:
            sizes = {name[:-3]: kw.pop(name) for name in list(kw) if name.endswith("_mm")}
            part = kw.get("part") or _default or type(self).DEFAULT_PART
            self._size_changes = {}
            if part in type(self).TABLE:
                row, changes = self._sized_row(part, sizes)
                if changes:
                    # this part's own copy of the table, its row with the sizes set by hand: the family reads it as
                    # it reads the vendor's row
                    self.TABLE = {**type(self).TABLE, part: row}
                    self._size_changes = changes
            _init(self, *args, **kw)

        __init__.__wrapped__ = init  # type: ignore[attr-defined]
        __init__.__doc__ = init.__doc__
        __init__._takes_sizes = True  # type: ignore[attr-defined]
        __init__._keeps_label_side = True  # type: ignore[attr-defined]
        cls.__init__ = __init__  # type: ignore[method-assign]

    @classmethod
    def size_names(cls) -> list[str]:
        """The sizes this family takes by hand, as ``<name>_mm`` parameters."""

        return [f"{name}_mm" for name in cls._SIZE_PATHS]

    @classmethod
    def part_sizes(cls, part: str) -> dict[str, float]:
        """The sizes of ``part`` from the vendor's drawing, mm, by ``<name>_mm``."""

        row = cls.TABLE[part]
        return {f"{name}_mm": v for name, path in cls._SIZE_PATHS.items() if (v := _get(row, path)) is not None}

    def _sized_row(self, part: str, sizes: dict[str, Any]) -> tuple[dict, dict[str, float]]:
        import copy

        row = copy.deepcopy(type(self).TABLE[part])
        changes: dict[str, float] = {}
        for name, value in sizes.items():
            path = type(self)._SIZE_PATHS.get(name)
            if path is None:
                raise ValueError(f"{type(self).__name__} has no size {name!r}; its sizes are "
                                 f"{', '.join(type(self).size_names())}")
            if value is None or value == "":
                continue
            current = _get(row, path)
            if current is None:
                continue                                  # this part has no such size (a two-ring adapter's ring 3)
            value = float(value)
            if path[0] in _SIGNED:
                if value == 0:
                    raise ValueError(f"{name}_mm is a radius in mm and cannot be 0 (leave it empty for a flat face)")
            elif value < 0:
                raise ValueError(f"{name}_mm is a size in mm and cannot be negative, not {value}")
            if abs(value - current) > 1e-9:
                _set(row, path, value)
                changes[name] = value
        return row, changes

    @property
    def sizes_changed(self) -> dict[str, float]:
        """The sizes set by hand that differ from the part number's drawing, mm."""

        return dict(getattr(self, "_size_changes", {}) or {})

    def __getattr__(self, name: str) -> Any:
        # ``<size>_mm``: the size set by hand, or None while it is the drawing's (so a scene saves only changes)
        if name.endswith("_mm") and name[:-3] in type(self)._SIZE_PATHS:
            return (self.__dict__.get("_size_changes") or {}).get(name[:-3])
        raise AttributeError(name)

    @property
    def spec(self) -> dict:
        """This part's row of dimensions (mm): the vendor table's, with any size set by hand."""

        return self.TABLE[self.part]

    def _vendor_dict(self, data: dict) -> dict:
        data["part"] = self.part
        data.update({f"{name}_mm": value for name, value in self.sizes_changed.items()})
        return data


# --------------------------------------------------------------------------------------------- 3D helpers

def axial(stack, x0: float = 0.0, material=BLACK) -> list[dict[str, Any]]:
    """Coaxial rings and cylinders along +x from ``x0`` (scene units): ``stack`` is (length, outer d, inner d) in
    mm, an inner diameter of 0 being a solid cylinder; a fourth item overrides the material."""

    out, x = [], x0
    for item in stack:
        length, od, inner = (float(v) for v in item[:3])
        mat = item[3] if len(item) > 3 else material
        l, ro = length * MM, od * MM / 2
        cx = x + l / 2
        if inner > 0:
            out.append(_ring_along_x(inner * MM / 2, ro, l, mat, x=cx))
        else:
            out.append(_cylinder_along_x(ro, l, mat, position=[cx, 0.0, 0.0]))
        x += l
    return out


def _sag(radius: float | None, r: float) -> float:
    if not radius:
        return 0.0
    r = min(r, abs(radius) * 0.999)
    return radius - math.copysign(math.sqrt(radius * radius - r * r), radius)


def lens_solids(spec: dict, x0: float = 0.0) -> list[dict[str, Any]]:
    """The glass of a lens with its true surfaces, a lathe per element, front surface vertex at ``x0`` (mm in,
    scene units out)."""

    a = spec["d"] / 2.0
    if spec["type"] == "pcx":
        surfaces, thick = [spec["r"][0], None], [spec["ct"]]
    else:
        surfaces, thick = list(spec["r"]), [spec["ct1"], spec["ct2"]]
    out, xa = [], x0
    for i, t in enumerate(thick):
        ra, rb = surfaces[i], surfaces[i + 1]
        xb = xa + t
        n = 18
        front = [(a * k / n, xa + _sag(ra, a * k / n)) for k in range(n + 1)]
        back = [(a * k / n, xb + _sag(rb, a * k / n)) for k in range(n, -1, -1)]
        pts = [[max(r, 0.0) * MM, h * MM] for r, h in front + back]
        pts.append(pts[0])
        out.append({"shape": "lathe_profile", "points": pts, "segments": 40, "rotation": [0.0, 0.0, -math.pi / 2],
                    "position": [0.0, 0.0, 0.0], "material": GLASS if i == 0 else FLINT, "role": "glass element"})
        xa = xb
    return out


def _box(w, h, d, pos, mat=BLACK, role="body", rot=None) -> dict[str, Any]:
    out = {"shape": "box", "width": w, "height": h, "depth": d, "position": list(pos), "material": mat, "role": role}
    if rot:
        out["rotation"] = list(rot)
    return out


def _plate_x(w: float, h: float, t: float, x: float, bore: float, mat=BLACK, y: float = 0.0) -> dict[str, Any]:
    """A plate across the beam (w along z, h along y, t along x) centred at x, with a round bore on the axis."""

    # turned about z, the outline's u runs along y (the height) and v along -z (the width)
    hole = [(bore / 2 * math.sin(2 * math.pi * k / 40) - y, bore / 2 * math.cos(2 * math.pi * k / 40)) for k in range(40)] if bore > 0 else []
    hw, hh = w / 2, h / 2
    return {"shape": "extruded_polygon", "points": [(-hh, -hw), (hh, -hw), (hh, hw), (-hh, hw)], "holes": [hole] if hole else [],
            "height": t, "position": [x + t / 2, y, 0.0], "rotation": [0.0, 0.0, math.pi / 2], "material": mat, "role": "plate"}


def _outline_2d(x0: float, x1: float, half: float, fill: str = "#2b3036") -> dict[str, Any]:
    """A top view: the part's extent along the beam (x0 to x1) and across it (+-half), in scene units."""

    return {"type": "rect", "cx": (x0 + x1) / 2, "cy": 0.0, "w": max(x1 - x0, 0.05), "h": 2 * half, "fill": fill,
            "stroke": "#111827", "stroke_width": 0.08}


def _extent_2d(geo: dict[str, Any]) -> dict[str, Any]:
    """A top view from the 3D solids: the box they span along the beam (x) and across it (z)."""

    xs, zs = [], []
    for solid in geo.get("children", [geo]):
        x, _, z = solid.get("position", [0.0, 0.0, 0.0])
        size = max(float(solid.get(k, 0.0) or 0.0) for k in ("width", "depth", "height", "radius")) or 0.5
        if solid.get("shape") == "cylinder" or solid.get("shape") == "lathe_profile":
            pts = solid.get("points") or [[solid.get("radius", 0.5), 0]]
            size = max(abs(p[0]) for p in pts) if solid.get("shape") == "lathe_profile" else solid.get("radius", 0.5)
            xs += [x - (solid.get("height", 0.5) / 2 if solid.get("shape") == "cylinder" else 0.5), x + (solid.get("height", 0.5) / 2 if solid.get("shape") == "cylinder" else 0.5)]
            zs += [z - size, z + size]
        else:
            w, d = float(solid.get("width", 0.5) or 0.5), float(solid.get("depth", 0.5) or 0.5)
            xs += [x - w / 2, x + w / 2]
            zs += [z - d / 2, z + d / 2]
    half = max(abs(min(zs)), abs(max(zs))) if zs else 1.0
    return _outline_2d(min(xs) if xs else -0.5, max(xs) if xs else 0.5, half)


def _rod_holes(rod: float, t: float, x: float, y: float = 0.0) -> list[dict[str, Any]]:
    return [{**_cylinder_along_x(3.0 * MM * 1.05, t * 1.02, DARK, position=[x, y + sy * rod / 2, sz * rod / 2]), "role": "rod hole"}
            for sy in (-1, 1) for sz in (-1, 1)]


# --------------------------------------------------------------------------------------------- lenses

class CatalogLens(_Vendor, Lens):
    """A catalogue lens at its true size and shape: Edmund Optics (stock number) or Thorlabs (item number). A
    plano-convex lens shows its curved and flat faces, an achromatic doublet its two cemented elements. The
    focal length is the vendor's effective focal length."""

    component_type = "CatalogLens"
    TABLE = D.LENSES

    def __init__(self, center=(0, 0), angle=0, part="45-806", **kwargs):
        s = _row(self.TABLE, part, "CatalogLens")
        self.part = part
        ct = s.get("ct") or (s["ct1"] + s["ct2"])
        kwargs.setdefault("label", part)
        super().__init__(center=center, angle=angle, aperture=s["d"] * MM, focal_length=s["efl"] * MM,
                         center_thickness=ct * MM, edge_thickness=(s.get("et") or ct * 0.6) * MM, **kwargs)

    def geometry_2d(self) -> dict[str, Any]:
        children = []
        for solid in lens_solids(self.spec, -(self.spec.get("ct") or (self.spec["ct1"] + self.spec["ct2"])) / 2):
            pts = solid["points"]                         # (radius, axial) pairs: mirror them about the axis
            outline = [(h, r) for r, h in pts] + [(h, -r) for r, h in reversed(pts)]
            children.append({"type": "polygon", "points": outline, "fill": "#bcd7ea", "stroke": "#4a7fa8",
                             "stroke_width": 0.06, "opacity": 0.9})
        return {"type": "group", "children": children}

    def geometry_3d(self) -> dict[str, Any]:
        geo = super().geometry_3d()
        s = self.spec
        ct = s.get("ct") or (s["ct1"] + s["ct2"])
        holder = [c for c in geo.get("children", []) if (c.get("material") or {}).get("preset") != "glass"]
        glass = lens_solids(s, -ct / 2)
        cell = s.get("cell")
        if cell:                                     # a threaded cell around the lens (AC080-016-B-ML)
            holder = [_ring_along_x(s["d"] * MM / 2 * 1.02, cell["od"] * MM / 2, cell["length"] * MM, BLACK, x=0.0),
                      _post_boss(cell["od"] * MM / 2, cell["length"] * MM * 0.8)]
            geo["post_at"] = [0.0, -cell["od"] * MM / 2 * 1.12, 0.0]
        geo["children"] = holder + glass
        return geo

    def to_dict(self) -> dict[str, Any]:
        return self._vendor_dict(super().to_dict())


# --------------------------------------------------------------------------------------------- lens tubes

class CatalogLensTube(_Vendor, Component):
    """A Thorlabs lens tube (SM1L.., SM1V.. adjustable, SM05L10) at its size: the body, the male thread stub at
    the back and the lip at the front. Light passes along the axis."""

    component_type = "CatalogLensTube"
    TABLE = D.TUBES
    beam_passes = True

    def __init__(self, center=(0, 0), angle=0, part="SM1L10", **kwargs):
        _row(self.TABLE, part, "CatalogLensTube")
        self.part = part
        _set_common_free_space_fields(self, center, angle, kwargs, color="#23282e", opacity=1.0, material_preset="steel",
                                      label=kwargs.get("label", part))

    @property
    def length(self) -> float:
        return self.spec["length"] * MM

    def symbol_1d(self):
        return ("lenstube", {})

    def ports(self) -> dict[str, Port]:
        h, w = self.length / 2, self.spec["od"] * MM
        return {"in": Port("in", Vec3(-h, 0, 0), orientation_deg=180.0, width=w, kind="free_space"),
                "out": Port("out", Vec3(h, 0, 0), orientation_deg=0.0, width=w, kind="free_space")}

    def geometry_2d(self) -> dict[str, Any]:
        s = self.spec
        return {"type": "rect", "cx": 0, "cy": 0, "w": self.length, "h": s["od"] * MM, "fill": "#2b3036", "stroke": "#111827", "stroke_width": 0.1}

    def geometry_3d(self) -> dict[str, Any]:
        s = self.spec
        bore = s["stub_od"] * 0.985
        body = s["length"] - s["stub"]
        if s.get("adjustable"):
            inner = body - s["housing"]
            stack = [(s["housing"], s["od"], bore), (inner, s["stub_od"] * 1.0, s["clear"], ALU), (s["stub"], s["stub_od"], s["clear"])]
        else:
            stack = [(s["lip"], s["od"], s["clear"]), (body - s["lip"], s["od"], bore), (s["stub"], s["stub_od"], s["clear"])]
        r = s["od"] * MM / 2
        bx = -self.length / 2 + (s["housing"] * MM / 2 if s.get("adjustable") else self.length / 2 - s["stub"] * MM / 2)
        boss = _post_boss(r, min(self.length * 0.5, 4.0, (s.get("housing") or s["length"]) * MM * 0.8), x=bx)
        return {"shape": "group", "children": axial(stack, -self.length / 2) + [boss], "post_at": [bx, -r * 1.12, 0.0]}

    def to_dict(self) -> dict[str, Any]:
        return self._vendor_dict(super().to_dict())


class CatalogAdapter(_Vendor, Component):
    """A thread adapter, coupler or small spacer (SM1A.., SM1T.., AD.., ERSCB.., S1TM12...) as its stack of rings.
    It sits in a tube or a mount (no post of its own); light passes along the axis."""

    component_type = "CatalogAdapter"
    TABLE = D.ADAPTERS
    beam_passes = True

    def __init__(self, center=(0, 0), angle=0, part="SM1A3", **kwargs):
        _row(self.TABLE, part, "CatalogAdapter")
        self.part = part
        kwargs.setdefault("base_mount", "none")
        _set_common_free_space_fields(self, center, angle, kwargs, color="#23282e", opacity=1.0, material_preset="steel",
                                      label=kwargs.get("label", part))

    @property
    def length(self) -> float:
        return sum(item[0] for item in self.spec["stack"]) * MM

    @property
    def outer(self) -> float:
        return max(item[1] for item in self.spec["stack"]) * MM

    def symbol_1d(self):
        return ("tubering", {})

    def ports(self) -> dict[str, Port]:
        h = self.length / 2
        return {"in": Port("in", Vec3(-h, 0, 0), orientation_deg=180.0, width=self.outer, kind="free_space"),
                "out": Port("out", Vec3(h, 0, 0), orientation_deg=0.0, width=self.outer, kind="free_space")}

    def geometry_2d(self) -> dict[str, Any]:
        return {"type": "rect", "cx": 0, "cy": 0, "w": self.length, "h": self.outer, "fill": "#2b3036", "stroke": "#111827", "stroke_width": 0.08}

    def geometry_3d(self) -> dict[str, Any]:
        mat = STEEL if self.spec["stack"][0][1] < 8 else BLACK
        return {"shape": "group", "children": axial(self.spec["stack"], -self.length / 2, mat)}

    def to_dict(self) -> dict[str, Any]:
        return self._vendor_dict(super().to_dict())


# --------------------------------------------------------------------------------------------- filters and plates

class CatalogFilter(_Vendor, Filter):
    """A Ø25 mm Thorlabs longpass or shortpass filter (FELH.., FESH..) in its unthreaded ring."""

    component_type = "CatalogFilter"
    TABLE = D.FILTERS

    def __init__(self, center=(0, 0), angle=0, part="FELH0800", **kwargs):
        s = _row(self.TABLE, part, "CatalogFilter")
        self.part = part
        kwargs.setdefault("label", part)
        super().__init__(center=center, angle=angle, aperture=s["od"] * MM, thickness=s["thickness"] * MM,
                         cutoff_wavelength=s["edge"], pass_band=s["band"], **kwargs)

    def geometry_2d(self) -> dict[str, Any]:
        s = self.spec
        half, length = s["od"] * MM / 2, s["thickness"] * MM
        return _outline_2d(-length / 2, length / 2, half)

    def geometry_3d(self) -> dict[str, Any]:
        s = self.spec
        t, r = s["thickness"] * MM, s["od"] * MM / 2
        tint = {"color": "#e9b04a" if s["band"] == "longpass" else "#7ab8e8", "opacity": 0.6, "transparent": True, "preset": "glass"}
        return {"shape": "group", "children": [
            _ring_along_x(s["clear"] * MM / 2, r, t, BLACK),
            {**_cylinder_along_x(s["clear"] * MM / 2 * 0.99, t * 0.6, tint), "role": "filter glass"},
            _post_boss(r, t)], "post_at": [0.0, -r * 1.12, 0.0]}

    def to_dict(self) -> dict[str, Any]:
        return self._vendor_dict(super().to_dict())


class CatalogNDFilter(_Vendor, NDFilter):
    """A Thorlabs absorptive ND filter in its engraved SM1 mount (NE..A-B, NENIR..), or the NDC-50C-4M-B
    continuously variable wheel (the beam crosses the coated annulus below the wheel's axle)."""

    component_type = "CatalogNDFilter"
    TABLE = D.ND_FILTERS

    def __init__(self, center=(0, 0), angle=0, part="NE10A-B", **kwargs):
        s = _row(self.TABLE, part, "CatalogNDFilter")
        self.part = part
        kwargs.setdefault("label", part)
        if s.get("wheel"):
            ap, t = 25.0 * MM, s["glass_t"] * MM
        else:
            ap, t = 25.0 * MM, s["length"] * MM
        super().__init__(center=center, angle=angle, aperture=ap, thickness=t, optical_density=s["od_value"], **kwargs)

    def geometry_2d(self) -> dict[str, Any]:
        s = self.spec
        half, length = s["od"] * MM / 2 if not s.get("wheel") else s["od"] * MM / 2, s["length"] * MM if not s.get("wheel") else s["ring_t"] * MM
        return _outline_2d(-length / 2, length / 2, half)

    def geometry_3d(self) -> dict[str, Any]:
        s = self.spec
        smoke = {"color": "#3b3f45", "opacity": 0.75, "transparent": True, "preset": "glass"}
        if s.get("wheel"):
            # the wheel's axle sits above the beam, on the middle of the coated annulus
            hub_y = (s["axle_d"] / 2 + (s["glass_d"] / 2 - s["axle_d"] / 2) / 2) * MM
            t, r = s["glass_t"] * MM, s["od"] * MM / 2
            children = [
                {**_ring_along_x(s["glass_d"] * MM / 2 * 1.01, r, s["ring_t"] * MM, ALU), "position": [0.0, hub_y, 0.0], "role": "graduated ring"},
                {**_cylinder_along_x(s["glass_d"] * MM / 2, t, smoke), "position": [0.0, hub_y, 0.0], "role": "ND wheel"},
                {**_cylinder_along_x(s["axle_d"] * MM / 2, s["depth"] * MM * 0.5, STEEL), "position": [s["depth"] * MM * 0.25, hub_y, 0.0], "role": "axle"},
                _box(s["block"] * MM, s["block"] * MM, s["block"] * MM, (s["depth"] * MM * 0.5, hub_y, 0.0), role="hub block"),
            ]
            return {"shape": "group", "children": children, "post_at": [s["depth"] * MM * 0.5, hub_y - s["block"] * MM / 2, 0.0]}
        l, r = s["length"] * MM, s["od"] * MM / 2
        body = s["length"] - s["stub"]
        children = axial([(body, s["od"], 26.3 * 0.985), (s["stub"], 26.3, 24.0)], -l / 2)
        children += [{**_cylinder_along_x(12.5 * MM, 1.0 * MM, smoke, position=[-l / 2 + body * MM * 0.4, 0, 0]), "role": "ND glass"},
                     _post_boss(r, min(l * 0.5, 3.0))]
        return {"shape": "group", "children": children, "post_at": [0.0, -r * 1.12, 0.0]}

    def to_dict(self) -> dict[str, Any]:
        return self._vendor_dict(super().to_dict())


class CatalogWavePlate(_Vendor, WavePlate):
    """A Thorlabs zero-order half- or quarter-wave plate in its mount (WPH05M / WPQ05M: Ø1/2" plate in a Ø1"
    ring; WPH10M / WPQ10M: Ø1" plate in an SM1-threaded mount). The design wavelength is in the part number."""

    component_type = "CatalogWavePlate"
    TABLE = D.WAVE_PLATES

    def __init__(self, center=(0, 0), angle=0, part="WPH10M-915", fast_axis_angle=0.0, **kwargs):
        s = _row(self.TABLE, part, "CatalogWavePlate")
        self.part = part
        kwargs.setdefault("label", part)
        super().__init__(center=center, angle=angle, aperture=s["od"] * MM, thickness=s["length"] * MM,
                         retardance=math.pi if s["plate"] == "half" else math.pi / 2, fast_axis_angle=fast_axis_angle,
                         design_wavelength_nm=s["wavelength"], **kwargs)

    def geometry_2d(self) -> dict[str, Any]:
        s = self.spec
        half, length = s["od"] * MM / 2, s["length"] * MM
        return _outline_2d(-length / 2, length / 2, half)

    def geometry_3d(self) -> dict[str, Any]:
        s = self.spec
        l, r = s["length"] * MM, s["od"] * MM / 2
        body = s["length"] - s["stub"]
        stack = [(body, s["od"], s["optic_d"] * 0.95)] + ([(s["stub"], 26.3, s["clear"])] if s["stub"] else [])
        tint = {"color": "#b9a7f5" if s["plate"] == "half" else "#8fd3c4", "opacity": 0.55, "transparent": True, "preset": "glass"}
        fast = math.radians(float(self.fast_axis_angle))
        children = axial(stack, -l / 2)
        children += [{**_cylinder_along_x(s["optic_d"] * MM / 2 * 0.94, 1.0 * MM, tint, position=[-l / 2 + body * MM * 0.5, 0, 0]), "role": "retarder"},
                     _box(0.15, s["optic_d"] * MM * 0.85, 0.3, (-l / 2 - 0.05, 0.0, 0.0), {"color": "#ffffff", "opacity": 0.9, "transparent": True}, "fast axis", [fast, 0.0, 0.0]),
                     _post_boss(r, min(body * MM, 3.0))]
        return {"shape": "group", "children": children, "post_at": [0.0, -r * 1.12, 0.0]}

    def to_dict(self) -> dict[str, Any]:
        return self._vendor_dict(super().to_dict())


class CatalogGlanPolarizer(_Vendor, GlanLaserPolarizer):
    """A Thorlabs Glan-Taylor polarizer (GT10, GT10-C): a square aluminium housing with the calcite pair, the
    entrance and exit windows and the escape window on its side."""

    component_type = "CatalogGlanPolarizer"
    TABLE = D.GLAN_POLARIZERS

    def __init__(self, center=(0, 0), angle=0, part="GT10", **kwargs):
        s = _row(self.TABLE, part, "CatalogGlanPolarizer")
        self.part = part
        kwargs.setdefault("label", part)
        super().__init__(center=center, angle=angle, length=s["length"] * MM, aperture=s["clear"] * MM, **kwargs)

    def geometry_2d(self) -> dict[str, Any]:
        return _extent_2d(self.geometry_3d())

    def geometry_3d(self) -> dict[str, Any]:
        s = self.spec
        l, w, h = s["length"] * MM, s["w"] * MM, s["h"] * MM
        win = s["window"] * MM
        children = [_box(l, h, w, (0, 0, 0), ALU, "housing")]
        for sx in (-1, 1):
            children.append(_box(0.2, win, win, (sx * (l / 2 + 0.05), 0, 0), GLASS, "window"))
        children.append(_box(s["escape"] * MM, s["escape"] * MM * 0.8, 0.2, (0.0, 0.0, w / 2 + 0.05), GLASS, "escape window"))
        children.append(_box(l * 0.6, 1.0, w * 0.5, (0.0, -h / 2 - 0.5, 0.0), BLACK, "boss"))
        return {"shape": "group", "children": children, "post_at": [0.0, -h / 2 - 1.0, 0.0]}

    def to_dict(self) -> dict[str, Any]:
        return self._vendor_dict(super().to_dict())


class CatalogPolarizer(_Vendor, Polarizer):
    """A Thorlabs SM05-mounted linear polarizer (LPNIR050-MP2): the film in its threaded housing."""

    component_type = "CatalogPolarizer"
    TABLE = D.POLARIZERS

    def __init__(self, center=(0, 0), angle=0, part="LPNIR050-MP2", **kwargs):
        s = _row(self.TABLE, part, "CatalogPolarizer")
        self.part = part
        kwargs.setdefault("label", part)
        super().__init__(center=center, angle=angle, aperture=s["od"] * MM, thickness=s["length"] * MM, **kwargs)

    def geometry_2d(self) -> dict[str, Any]:
        s = self.spec
        half, length = s["od"] * MM / 2, s["length"] * MM
        return _outline_2d(-length / 2, length / 2, half)

    def geometry_3d(self) -> dict[str, Any]:
        s = self.spec
        l, r = s["length"] * MM, s["od"] * MM / 2
        body = s["length"] - s["stub"]
        film = {"color": "#2d2f33", "opacity": 0.7, "transparent": True, "preset": "glass"}
        children = axial([(body, s["od"], s["clear"]), (s["stub"], s["stub_od"], s["clear"])], -l / 2)
        children += [{**_cylinder_along_x(s["clear"] * MM / 2, 0.3 * MM, film, position=[-l / 2 + body * MM * 0.5, 0, 0]), "role": "polarizer film"},
                     _post_boss(r, min(body * MM, 2.5))]
        return {"shape": "group", "children": children, "post_at": [0.0, -r * 1.12, 0.0]}

    def to_dict(self) -> dict[str, Any]:
        return self._vendor_dict(super().to_dict())


class CatalogCubeSplitter(_Vendor, NonPolarizingBeamSplitter):
    """A bare beamsplitter cube at its size (BS0.., PBS1.., PBS255, 20 and 25 mm cubes): the glass cube and its
    coated diagonal. Non-polarizing parts split by the vendor's R:T, polarizing ones by polarization. Stand it
    in a platform mount (BSH05, BSH20, BSH1) or a cage cube."""

    component_type = "CatalogCubeSplitter"
    TABLE = D.CUBE_SPLITTERS

    def __init__(self, center=(0, 0), angle=0, part="BS013", **kwargs):
        s = _row(self.TABLE, part, "CatalogCubeSplitter")
        self.part = part
        kwargs.setdefault("label", part)
        kwargs.setdefault("polarization_selective", bool(s["pol"]))
        r, t = s["rt"]
        super().__init__(center=center, angle=angle, aperture=s["edge"] * MM / 0.72, split_ratio=(r / 100.0, t / 100.0), **kwargs)

    def physics_metadata(self) -> dict[str, Any]:
        meta = super().physics_metadata()
        if self.spec["pol"]:
            meta["component"] = "polarizing_beam_splitter"
            meta["polarization_selective"] = True
        return meta

    def geometry_2d(self) -> dict[str, Any]:
        return _extent_2d(self.geometry_3d())

    def geometry_3d(self) -> dict[str, Any]:
        e = self.spec["edge"] * MM
        coat = {"color": "#ffffff" if not self.spec["pol"] else "#d8e6ff", "opacity": 0.55, "transparent": True}
        return {"shape": "group", "children": [
            _box(e, e, e, (0, 0, 0), GLASS, "glass"),
            _box(e * 1.40, 0.04, e * 0.99, (0, 0, 0), coat, "coating", [0.0, -math.pi / 4, 0.0])], "post_at": [0.0, -e / 2, 0.0]}

    def to_dict(self) -> dict[str, Any]:
        return self._vendor_dict(super().to_dict())


class CatalogPlateSplitter(_Vendor, BeamSplitter):
    """A plate or pellicle beamsplitter at its size (BSN11R, BSW29, BSW29R; BP108, BP145B3 pellicles in their
    frame). Aim it like any plate beamsplitter; the transmission is the vendor's T."""

    component_type = "CatalogPlateSplitter"
    TABLE = D.PLATE_SPLITTERS

    def __init__(self, center=(0, 0), angle=0, part="BSW29", **kwargs):
        s = _row(self.TABLE, part, "CatalogPlateSplitter")
        self.part = part
        kwargs.setdefault("label", part)
        ap = (s.get("d") or s.get("h")) * MM
        super().__init__(center=center, angle=angle, aperture=ap, thickness=max(s["t"], 0.5) * MM, transmission=s["rt"][1], **kwargs)

    def geometry_3d(self) -> dict[str, Any]:
        geo = super().geometry_3d()
        s = self.spec
        holder = [c for c in geo.get("children", []) if (c.get("material") or {}).get("preset") != "glass"
                  and "glass" not in str(c.get("role", ""))]
        t = max(s["t"], 0.05) * MM
        if s["shape"] == "rect":
            optic = [_box(t, s["h"] * MM, s["w"] * MM, (0, 0, 0), GLASS, "plate")]
        elif s["shape"] == "pellicle":
            optic = [_ring_along_x(s["d"] * MM / 2, s["frame_d"] * MM / 2, s["frame_t"] * MM, ALU),
                     {**_cylinder_along_x(s["d"] * MM / 2, 0.03, {"color": "#e8f0ff", "opacity": 0.35, "transparent": True, "preset": "glass"}), "role": "membrane"}]
            holder = []
        else:
            optic = [{**_cylinder_along_x(s["d"] * MM / 2, t, GLASS), "role": "plate"}]
        geo["children"] = holder + optic
        if not holder:
            geo["children"].append(_post_boss(s["frame_d"] * MM / 2, s["frame_t"] * MM))
            geo["post_at"] = [0.0, -s["frame_d"] * MM / 2 * 1.12, 0.0]
        return geo

    def to_dict(self) -> dict[str, Any]:
        return self._vendor_dict(super().to_dict())


class CatalogMirror(_Vendor, Mirror):
    """A Thorlabs protected-silver mirror (PF10-03-P01 Ø1", PF20-03-P01 Ø2", PFD10-03-P01 D-shaped) at its size,
    in a kinematic mount sized to it."""

    component_type = "CatalogMirror"
    TABLE = D.MIRRORS

    def __init__(self, center=(0, 0), angle=0, part="PF10-03-P01", **kwargs):
        s = _row(self.TABLE, part, "CatalogMirror")
        self.part = part
        kwargs.setdefault("label", part)
        super().__init__(center=center, angle=angle, aperture=s["d"] * MM, thickness=s["t"] * MM, **kwargs)

    def to_dict(self) -> dict[str, Any]:
        return self._vendor_dict(super().to_dict())


from ..optics.mirrors import DichroicMirror  # noqa: E402


class CatalogDichroic(_Vendor, DichroicMirror):
    """A Thorlabs Ø1" dichroic mirror (DMLP805 longpass, DMSP650 shortpass) at its size."""

    component_type = "CatalogDichroic"
    TABLE = D.DICHROICS

    def __init__(self, center=(0, 0), angle=0, part="DMLP805", **kwargs):
        s = _row(self.TABLE, part, "CatalogDichroic")
        self.part = part
        kwargs.setdefault("label", part)
        super().__init__(center=center, angle=angle, aperture=s["d"] * MM, thickness=s["t"] * MM,
                         cutoff_wavelength=s["edge"], pass_band=s["band"], **kwargs)

    def to_dict(self) -> dict[str, Any]:
        return self._vendor_dict(super().to_dict())


# --------------------------------------------------------------------------------------------- cage hardware

class CatalogCageMount(_Vendor, Component):
    """A Thorlabs 30 or 60 mm cage plate, cage mount or cage accessory at its size: plates (CP32, CP33, CP33T,
    CP36, CP42, LCP6S), the drop-in DCP1, rotation mounts (CRM1T, CRM1LT, C45M1, CP360Q, LCP360R), XY mounts
    (CXY1A, CXYZ05A), the dual rotation mount DLM1, the CP33C bracket, the 30-to-60 mm adapters LCP33 and CDA1, the
    alignment plates CPA1, VRC2CPT and VRC8CPT, the ER8 rod, the ERCPS rod stop and the C30L24 cover. Light passes
    along the axis through the bore."""

    component_type = "CatalogCageMount"
    TABLE = D.CAGE_MOUNTS
    beam_passes = True

    def __init__(self, center=(0, 0), angle=0, part="CP33", **kwargs):
        row = _row(self.TABLE, part, "CatalogCageMount")
        self.part = part
        if row["kind"] in _ON_RODS:                    # held by the cage rods, not stood on a post
            kwargs.setdefault("base_mount", "none")
        _set_common_free_space_fields(self, center, angle, kwargs, color="#23282e", opacity=1.0, material_preset="steel",
                                      label=kwargs.get("label", part))

    def symbol_1d(self):
        return ("cageplate", {})

    @property
    def depth(self) -> float:
        return self.spec["depth"] * MM

    def ports(self) -> dict[str, Port]:
        h, w = self.depth / 2, self.spec["w"] * MM
        return {"in": Port("in", Vec3(-h, 0, 0), orientation_deg=180.0, width=w, kind="free_space"),
                "out": Port("out", Vec3(h, 0, 0), orientation_deg=0.0, width=w, kind="free_space")}

    def geometry_2d(self) -> dict[str, Any]:
        s = self.spec
        return {"type": "rect", "cx": 0, "cy": 0, "w": self.depth, "h": s["w"] * MM, "fill": "#2b3036", "stroke": "#111827", "stroke_width": 0.1}

    def geometry_3d(self) -> dict[str, Any]:
        s = self.spec
        w, h, t = s["w"] * MM, s["h"] * MM, self.depth
        cy = -s.get("axis_y", 0.0) * MM                # the body's centre, from the optical axis
        bore = s["bore"] * MM
        kind = s["kind"]
        out: list[dict[str, Any]] = []
        if kind == "bracket":                          # CP33C: a bar between two rods, the captive screw underneath
            out.append(_box(t, h, w, (0, 0, 0), BLACK, "bracket"))
            out += [{**_cylinder_along_x(3.0 * MM * 1.05, t * 1.02, DARK, position=[0.0, 0.0, sz * s["rod"] * MM / 2]), "role": "rod hole"}
                    for sz in (-1, 1)]
            out.append({"shape": "cylinder", "radius": 2.0 * MM, "height": 5.6 * MM, "position": [0, -h / 2 - 2.8 * MM, 0],
                        "material": STEEL, "role": "captive screw"})
            return {"shape": "group", "children": out, "post_at": [0.0, -h / 2 - 5.6 * MM, 0.0]}
        special = _cage_part_solids(s, t)
        if special is not None:
            return special
        out.append(_plate_x(w, h, t, -t / 2, bore, BLACK, y=cy))
        if s["rod"]:
            out += _rod_holes(s["rod"] * MM, t, 0.0)
        if s.get("rod_outer"):
            out += _rod_holes(s["rod_outer"] * MM, t, 0.0)
        if kind in ("rotation", "pivot", "dual", "rotation45"):
            rl, rd = s["ring_l"] * MM, s["ring_d"] * MM / 2
            out.append({**_ring_along_x(s["clear"] * MM / 2 * 1.02, rd, rl, ALU, x=-t / 2 - rl * 0.3), "role": "rotating ring"})
            for k in range(24):                        # the scale on the ring's face
                a = 2 * math.pi * k / 24
                out.append(_box(0.08, rd * (0.14 if k % 6 else 0.24), 0.06, (-t / 2 - rl * 0.8, math.sin(a) * rd * 0.92, math.cos(a) * rd * 0.92),
                                {"color": "#ffffff", "metalness": 0.1, "roughness": 0.6}, "tick", [a, 0.0, 0.0]))
        if kind in ("xy", "pivot"):
            kd, kl = s["knob_d"] * MM / 2, s["knob_l"] * MM
            for pos, rot in (((0.0, h / 2 + kl / 2 + cy, 0.0), None), ((0.0, cy, w / 2 + kl / 2), [math.pi / 2, 0, 0])):
                knob = {"shape": "cylinder", "radius": kd, "height": kl, "position": list(pos), "material": STEEL, "role": "knob"}
                if rot:
                    knob["rotation"] = rot
                out.append(knob)
                if kind == "pivot":
                    break
        if s.get("dial_d"):
            out.append({**_ring_along_x(s["clear"] * MM / 2 * 1.02, s["dial_d"] * MM / 2, s["dial_l"] * MM, ALU, x=t / 2 + s["dial_l"] * MM / 2), "role": "zoom dial"})
        return {"shape": "group", "children": out, "post_at": [0.0, cy - h / 2, 0.0]}

    def to_dict(self) -> dict[str, Any]:
        return self._vendor_dict(super().to_dict())


_ON_RODS = ("dropin_cell", "drop_adapter", "alignment", "rod", "rod_stop", "cover")


def _cage_part_solids(s: dict, t: float) -> dict[str, Any] | None:
    """The solids of the cage parts that are not a plate round the axis (LCP360R, CDA1, the alignment plates, ER8,
    ERCPS, C30L24), in the part frame: x along the beam, y up, z across. None for a plate."""

    kind = s["kind"]
    r = s["rod"] * MM / 2                              # the rods sit at (y, z) = (+-r, +-r)
    out: list[dict[str, Any]] = []
    if kind == "dropin_cell":                          # LCP360R: a bar hooked on the top rods, the cell hanging below
        bar_h, ring_r, ring_l = s["h"] * MM, s["ring_d"] * MM / 2, s["ring_l"] * MM
        out.append(_box(7.0 * MM, bar_h + 3.0 * MM, s["w"] * MM, (0, r + (bar_h - 3.0 * MM) / 2, 0), BLACK, "bar"))
        out.append({**_ring_along_x(s["clear"] * MM / 2, ring_r, ring_l, BLACK, x=0.0), "role": "rotating cell"})
        for z in (-r, r):
            out.append({**_cylinder_along_x(3.0 * MM * 1.05, 7.0 * MM * 1.02, DARK, position=[0.0, r, z]), "role": "rod hook"})
        out.append({"shape": "cylinder", "radius": s["knob_d"] * MM / 2, "height": s["knob_l"] * MM,
                    "position": [0.0, r + bar_h + s["knob_l"] * MM / 2, 0.0], "material": STEEL, "role": "thumbscrew"})
        return {"shape": "group", "children": out, "post_at": [0.0, -ring_r, 0.0]}
    if kind == "drop_adapter":                         # CDA1: hooks on the top rods of a 30 and a 60 mm cage
        low_w, low_h, top_h = s["lower_w"] * MM, s["lower_h"] * MM, s["h"] * MM
        cut = s["bore"] * MM / 2
        leg = (low_w / 2 - cut)
        for z in (-1, 1):
            out.append(_box(t, low_h, leg, (0, low_h / 2, z * (cut + leg / 2)), BLACK, "leg"))
        out.append(_box(t, low_h - cut, low_w, (0, (low_h + cut) / 2, 0), BLACK, "bridge"))
        out.append(_box(t, top_h - low_h + 3.0 * MM, s["w"] * MM, (0, (top_h + low_h - 3.0 * MM) / 2, 0), BLACK, "arms"))
        for y, z in ((r, -r), (r, r), (s["rod_outer"] * MM / 2, -s["rod_outer"] * MM / 2), (s["rod_outer"] * MM / 2, s["rod_outer"] * MM / 2)):
            out.append({**_cylinder_along_x(3.0 * MM * 1.05, t * 1.02, DARK, position=[0.0, y, z]), "role": "rod hook"})
        return {"shape": "group", "children": out, "post_at": [0.0, 0.0, 0.0]}
    if kind == "alignment":                            # CPA1, VRC*CPT: a T-shaped target hung on the top rods
        top, bar_h, stem_w = s["top"] * MM, s["bar_h"] * MM, s["stem_w"] * MM
        bottom = top - s["h"] * MM
        out.append(_box(t, bar_h, s["w"] * MM, (0, top - bar_h / 2, 0), BLACK, "bar"))
        out.append(_box(t, top - bar_h - bottom, stem_w, (0, (top - bar_h + bottom) / 2, 0), BLACK, "stem"))
        white = {"color": "#e8e8e8", "metalness": 0.1, "roughness": 0.6}
        for k, d in enumerate((4.0, 7.0, 10.0, 13.0)):       # the engraved rings round the pinhole
            out.append({**_ring_along_x(d * MM / 2 - 0.15 * MM, d * MM / 2 + 0.15 * MM, 0.05, white, x=-t / 2 - 0.03), "role": "ring"})
        out.append({**_cylinder_along_x(s["bore"] * MM / 2, 0.06, DARK, position=[-t / 2 - 0.04, 0.0, 0.0]), "role": "pinhole"})
        if s.get("disk_d"):
            out.append({**_cylinder_along_x(s["disk_d"] * MM / 2, s["disk_t"] * MM, {"color": s["disk_color"], "metalness": 0.1, "roughness": 0.7},
                                            position=[t / 2 + s["disk_t"] * MM / 2, 0.0, 0.0]), "role": "fluorescing disk"})
        return {"shape": "group", "children": out, "post_at": [0.0, bottom, 0.0]}
    if kind == "rod":                                  # ER8: one Ø6 mm rod along the beam
        out.append({**_cylinder_along_x(s["w"] * MM / 2, t, STEEL, position=[0.0, 0.0, 0.0]), "role": "rod"})
        return {"shape": "group", "children": out, "post_at": [0.0, -s["w"] * MM / 2, 0.0]}
    if kind == "rod_stop":                             # ERCPS: a collar clamped round its rod
        out.append(_box(t, s["h"] * MM, s["w"] * MM, (0, 0, 0), BLACK, "collar"))
        out.append({**_cylinder_along_x(3.0 * MM, t * 1.02, DARK, position=[0.0, 0.0, 0.0]), "role": "rod bore"})
        return {"shape": "group", "children": out, "post_at": [0.0, -s["h"] * MM / 2, 0.0]}
    if kind == "cover":                                # C30L24: four snap-on covers closing the cage
        side, wall = s["w"] * MM, s["wall"] * MM
        for y in (-1, 1):
            out.append(_box(t, wall, side, (0, y * (side - wall) / 2, 0), BLACK, "cover"))
            out.append(_box(t, side, wall, (0, 0, y * (side - wall) / 2), BLACK, "cover"))
        return {"shape": "group", "children": out, "post_at": [0.0, -side / 2, 0.0]}
    return None


class CatalogCageCube(_Vendor, CageCube):
    """A Thorlabs 30 mm cage cube at its size (CCM1-4ER compact, CM1-DCH with its dichroic holder, the DFM1BS
    kinematic cube, BS20CAM holding a 20 mm cube). It splits light like a beamsplitter cube."""

    component_type = "CatalogCageCube"
    TABLE = D.CAGE_CUBES

    def __init__(self, center=(0, 0), angle=0, part="CCM1-4ER", **kwargs):
        s = _row(self.TABLE, part, "CatalogCageCube")
        self.part = part
        kwargs.setdefault("label", part)
        colour = {"mirror": "#e8eef3", "dichroic": "#7fd6d0", "plate": "#ffffff", "cube20": "#ffffff"}[s["insert"]]
        kwargs.setdefault("coating_color", colour)
        super().__init__(center=center, angle=angle, **kwargs)

    @property
    def size(self) -> CageSize:
        s = self.spec
        base = cage_size(30)
        return CageSize(30, s["rod"] * MM / 2, base.rod_r, s["side"] * MM / 2, base.wall, s["bore"] * MM / 2 * 0.97,
                        10.0 * MM if s["insert"] == "cube20" else base.glass_half)

    def geometry_2d(self) -> dict[str, Any]:
        return _extent_2d(self.geometry_3d())

    def geometry_3d(self) -> dict[str, Any]:
        geo = super().geometry_3d()
        s = self.spec
        z = self.size
        gap = z.cube_half - z.wall - z.glass_half
        if gap > 0.05:                                  # the optic's seat, from the bottom wall up to the optic
            geo["children"].append(_box(z.glass_half * 1.6, gap, z.glass_half * 1.6, (0, -z.glass_half - gap / 2, 0), BLACK, "optic seat"))
        if s.get("cap"):                                # DFM1BS: the kinematic cap on top
            h = s["side"] * MM / 2
            geo["children"].append(_box(s["side"] * MM, s["cap"] * MM, s["side"] * MM, (0, h + s["cap"] * MM / 2, 0), BLACK, "kinematic cap"))
        return geo

    def to_dict(self) -> dict[str, Any]:
        return self._vendor_dict(super().to_dict())


class CatalogRightAngleMount(_Vendor, CageRightAngleMirror):
    """A Thorlabs right-angle kinematic cage mount at its size (KCB1C on a 30 mm cage, KCB2C on a 60 mm cage)."""

    component_type = "CatalogRightAngleMount"
    TABLE = D.RIGHT_ANGLE_MOUNTS

    def __init__(self, center=(0, 0), angle=0, part="KCB1C", **kwargs):
        row = _row(self.TABLE, part, "CatalogRightAngleMount")
        self.part = part
        kwargs.setdefault("label", part)
        kwargs["cage"] = int(row["rod"])               # the part number sets the cage size
        super().__init__(center=center, angle=angle, **kwargs)

    @property
    def size(self) -> CageSize:
        s = self.spec
        base = cage_size(int(s["rod"]))
        return CageSize(int(s["rod"]), s["rod"] * MM / 2, base.rod_r, s["side"] * MM / 2, base.wall, s["bore"] * MM / 2, base.glass_half)

    def to_dict(self) -> dict[str, Any]:
        return self._vendor_dict(super().to_dict())


# --------------------------------------------------------------------------------------------- sources, detectors

from ..devices import Camera, Lamp  # noqa: E402
from ..devices import Photodiode  # noqa: E402
from ..optics.fibers import FiberCollimator  # noqa: E402


class CatalogPhotodiode(_Vendor, Photodiode):
    """A Thorlabs photodiode or power sensor at its size: a bare TO can with its leads (FDS100, FGA01, FGA015),
    the SM05-mounted SM05PD4A, the S144C integrating-sphere sensor, or the PM121D console. Light enters at
    ``in``, on the front face."""

    component_type = "CatalogPhotodiode"
    TABLE = D.DETECTORS

    def __init__(self, center=(0, 0), angle=0, part="FDS100", **kwargs):
        _row(self.TABLE, part, "CatalogPhotodiode")
        self.part = part
        kwargs.setdefault("label", part)
        super().__init__(center=center, angle=angle, **kwargs)

    def geometry_2d(self) -> dict[str, Any]:
        return _extent_2d(self.geometry_3d())

    def geometry_2d(self) -> dict[str, Any]:
        return _extent_2d(self.geometry_3d())

    def geometry_3d(self) -> dict[str, Any]:
        s = self.spec
        x0 = self.ports()["in"].center.x               # the light's face
        kind = s["kind"]
        if kind == "can":
            out = axial([(s["cap_l"], s["cap_d"], 0.0, ALU), (s["flange_l"], s["flange_d"], 0.0, ALU)], x0)
            out.append({**_cylinder_along_x(s["cap_d"] * MM * 0.3, 0.05, {"color": "#2a3a6a", "metalness": 0.4, "roughness": 0.3}, position=[x0 - 0.02, 0, 0]), "role": "window"})
            back = x0 + (s["cap_l"] + s["flange_l"]) * MM
            for k in range(3):
                a = 2 * math.pi * k / 3
                out.append({**_cylinder_along_x(0.2 * MM, s["lead_l"] * MM, GOLD, position=[back + s["lead_l"] * MM / 2, math.sin(a) * 2.5 * MM, math.cos(a) * 2.5 * MM]), "role": "lead"})
            r = s["flange_d"] * MM / 2
            out.append(_post_boss(r, s["flange_l"] * MM + 0.5))
            out[-1]["position"][0] = x0 + (s["cap_l"] + s["flange_l"] / 2) * MM
            return {"shape": "group", "children": out, "post_at": [out[-1]["position"][0], -r * 1.12, 0.0]}
        if kind == "sm05":
            stack = [(l, d, 0.0) for l, d in s["stack"]]
            stack[-1] = (*stack[-1][:3], BRASS)
            out = axial(stack, x0)
            r = s["stack"][1][1] * MM / 2                # the post holds the collar
            out.append(_post_boss(r, 2.0))
            out[-1]["position"][0] = x0 + s["stack"][0][0] * MM + 1.5
            return {"shape": "group", "children": out, "post_at": [out[-1]["position"][0], -r * 1.12, 0.0]}
        if kind == "sphere":
            rs = s["sphere_d"] * MM / 2
            out = [{"shape": "sphere", "radius": rs, "position": [x0 + rs, 0, 0], "material": {"color": "#e9edf1", "metalness": 0.3, "roughness": 0.5}, "role": "sphere"},
                   {**_ring_along_x(s["port_d"] * MM / 2, s["port_d"] * MM / 2 + 1.0, 1.2, BLACK, x=x0 + 0.6), "role": "input port"},
                   _box(rs * 1.2, 1.0, rs * 1.2, (x0 + rs, -rs - 0.5, 0), BLACK, "base")]
            return {"shape": "group", "children": out, "post_at": [x0 + rs, -rs - 1.0, 0.0]}
        w, l, h = (v * MM for v in s["box"])            # console: width, length (along the beam), height
        out = [_box(l, h, w, (x0 + l / 2, 0, 0), DARK, "console"),
               _box(0.1, h * 0.5, w * 0.7, (x0 + l - 0.05 + 0.1, h * 0.1, 0), {"color": "#93b8a0", "metalness": 0.1, "roughness": 0.4}, "display"),
               {**_ring_along_x(3.0, 4.0, 1.0, BLACK, x=x0 + 0.5), "role": "sensor aperture"}]
        return {"shape": "group", "children": out, "post_at": [x0 + l / 2, -h / 2, 0.0]}

    def to_dict(self) -> dict[str, Any]:
        return self._vendor_dict(super().to_dict())


class CatalogLED(_Vendor, Lamp):
    """A Thorlabs LED at its size: a mounted LED (M..L4, M..L5, MNWHL4) with its SM1 housing and finned heat sink,
    or a fiber-coupled LED (M..F1, M..F4) with its finned box and SMA port. Light leaves at ``out``."""

    component_type = "CatalogLED"
    TABLE = D.LEDS

    def __init__(self, center=(0, 0), angle=0, part="M660L4", **kwargs):
        s = _row(self.TABLE, part, "CatalogLED")
        self.part = part
        self.wavelength_nm = s["nm"]
        kwargs.setdefault("label", part)
        super().__init__(center=center, angle=angle, **kwargs)

    def geometry_2d(self) -> dict[str, Any]:
        return _extent_2d(self.geometry_3d())

    def geometry_3d(self) -> dict[str, Any]:
        s = self.spec
        x1 = self.ports()["out"].center.x                # the emitter's face, light going +x
        if s["kind"] == "mounted":
            out = axial([(s["board_l"], s["board_d"], 0.0, {"color": "#f4f0e2", "metalness": 0.2, "roughness": 0.5}),
                         (s["core_l"], s["core_d"], 0.0, ALU), (s["sleeve_l"], s["sleeve_d"], 0.0)], 0.0)
            # built from the front backward: flip each piece's x about the emitter face
            for solid in out:
                solid["position"][0] = x1 - solid["position"][0]
            back = x1 - (s["board_l"] + s["core_l"] + s["sleeve_l"]) * MM
            for k in range(s["fins"]):
                out.append({**_cylinder_along_x(s["fin_d"] * MM / 2, s["fin_t"] * MM, DARK, position=[back - k * s["pitch"] * MM - s["fin_t"] * MM / 2, 0, 0]), "role": "fin"})
            out.append({**_cylinder_along_x(s["root_d"] * MM / 2, s["fin_l"] * MM, DARK, position=[back - s["fin_l"] * MM / 2, 0, 0]), "role": "heat sink core"})
            out.append({**_cylinder_along_x(s["boss_d"] * MM / 2, s["boss_l"] * MM, DARK, position=[back - s["fin_l"] * MM - s["boss_l"] * MM / 2, 0, 0]), "role": "cable boss"})
            r = s["sleeve_d"] * MM / 2
            mid = x1 - (s["board_l"] + s["core_l"] + s["sleeve_l"] / 2) * MM
            out.append(_post_boss(r, 4.0))
            out[-1]["position"][0] = mid
            return {"shape": "group", "children": out, "post_at": [mid, -r * 1.12, 0.0]}
        w, h = s["w"] * MM, s["h"] * MM
        y0 = -s["axis_h"] * MM                            # the box's bottom, from the port's axis
        front = x1 - s["port_l"] * MM
        out = [{**_cylinder_along_x(s["port_d"] * MM / 2, s["port_l"] * MM, BRASS, position=[x1 - s["port_l"] * MM / 2, 0, 0]), "role": "SMA port"},
               _box(s["front_l"] * MM, h, w, (front - s["front_l"] * MM / 2, y0 + h / 2, 0), DARK, "front block")]
        fin_x0 = front - s["front_l"] * MM
        pitch = s["fin_l"] * MM / (s["slots"] + 1)
        out.append(_box(s["fin_l"] * MM, h * 0.6, w * 0.6, (fin_x0 - s["fin_l"] * MM / 2, y0 + h * 0.4, 0), DARK, "fin core"))
        for k in range(s["slots"] + 1):
            out.append(_box(pitch * 0.4, h, w, (fin_x0 - (k + 0.5) * pitch, y0 + h / 2, 0), DARK, "fin"))
        fw, fh, fl = (v * MM for v in s["flange"])
        out.append(_box(fl, fh, fw, (fin_x0 - fl / 2, y0 + fh / 2, 0), DARK, "base flange"))
        return {"shape": "group", "children": out, "lies_flat": True, "post_at": [fin_x0 - fl / 2, y0, 0.0]}

    def to_dict(self) -> dict[str, Any]:
        return self._vendor_dict(super().to_dict())


class CatalogCollimator(_Vendor, FiberCollimator):
    """A Thorlabs fixed fiber collimator (F220.., F280..) at its size: the Ø11 barrel with its M11 front and the
    FC or SMA adapter at the back. The fiber enters at ``in``; the collimated beam leaves at ``out``."""

    component_type = "CatalogCollimator"
    TABLE = D.COLLIMATORS

    def __init__(self, center=(0, 0), angle=0, part="F280APC-980", **kwargs):
        s = _row(self.TABLE, part, "CatalogCollimator")
        self.part = part
        kwargs.setdefault("label", part)
        super().__init__(center=center, angle=angle, aperture=s["d"] * MM, length=(s["length"] + s["conn_l"]) * MM,
                         focal_length=s["f"] * MM, **kwargs)

    def ports(self) -> dict[str, Port]:
        s = self.spec
        h = (s["length"] + s["conn_l"]) * MM / 2
        return {"in": Port("in", Vec3(-h, 0, 0), orientation_deg=180.0, width=s["conn_d"] * MM, kind="fiber"),
                "out": Port("out", Vec3(h, 0, 0), orientation_deg=0.0, width=s["d"] * MM, kind="free_space")}

    def geometry_2d(self) -> dict[str, Any]:
        return _extent_2d(self.geometry_3d())

    def geometry_3d(self) -> dict[str, Any]:
        s = self.spec
        h = (s["length"] + s["conn_l"]) * MM / 2
        conn = (s["conn_l"], s["conn_d"], 0.0, STEEL if s["connector"] == "FC" else BRASS)
        out = axial([conn, (s["length"], s["d"], 0.0, STEEL)], -h)
        out.append({**_cylinder_along_x(s["d"] * MM / 2 * 0.7, 0.05, GLASS, position=[h + 0.02, 0, 0]), "role": "lens"})
        r = s["d"] * MM / 2
        mid = -h + (s["conn_l"] + s["length"] / 2) * MM
        out.append(_post_boss(r, 3.0))
        out[-1]["position"][0] = mid
        return {"shape": "group", "children": out, "post_at": [mid, -r * 1.12, 0.0]}

    def to_dict(self) -> dict[str, Any]:
        return self._vendor_dict(super().to_dict())


class CatalogCamera(_Vendor, Camera):
    """A camera at its size: Thorlabs Zelux CS165MU (SM1 front, 30 mm cage taps) or an Allied Vision Alvium
    1800 U (C-mount). Light enters at ``in``, on the front face."""

    component_type = "CatalogCamera"
    TABLE = D.CAMERAS

    def __init__(self, center=(0, 0), angle=0, part="CS165MU", **kwargs):
        _row(self.TABLE, part, "CatalogCamera")
        self.part = part
        kwargs.setdefault("label", part)
        super().__init__(center=center, angle=angle, **kwargs)

    def ports(self) -> dict[str, Port]:
        l, w, h = (v * MM for v in self.spec["body"])
        return {"in": Port("in", Vec3(-l / 2 - 1.0, 0, 0), orientation_deg=180.0, width=min(w, h) * 0.6, kind="free_space")}

    def geometry_2d(self) -> dict[str, Any]:
        return _extent_2d(self.geometry_3d())

    def geometry_3d(self) -> dict[str, Any]:
        s = self.spec
        l, w, h = (v * MM for v in s["body"])
        thread = D.THREAD_OD["SM1"] if s["mount"] == "SM1" else D.THREAD_OD["C"]
        out = [_box(l, h, w, (0, 0, 0), DARK if s["mount"] == "SM1" else {"color": "#8f1d22", "metalness": 0.4, "roughness": 0.5}, "housing"),
               {**_ring_along_x(thread * MM / 2 * 0.85, thread * MM / 2, 1.0, BLACK, x=-l / 2 - 0.5), "role": "lens mount"},
               _box(0.2, h * 0.2, w * 0.3, (l / 2 + 0.1, h * 0.25, 0), {"color": "#2f6fd1", "metalness": 0.2, "roughness": 0.5}, "USB")]
        if s.get("cage"):
            out += _rod_holes(s["cage"] * MM, 0.2, -l / 2 - 0.1)
        return {"shape": "group", "children": out, "post_at": [0.0, -h / 2, 0.0]}

    def to_dict(self) -> dict[str, Any]:
        return self._vendor_dict(super().to_dict())


# --------------------------------------------------------------------------------------------- bench hardware

def _fork_outline(s: dict) -> list[tuple[float, float]]:
    """A clamping fork's plan outline in mm, counter-clockwise: the tines at -x, the pedestal's centre at
    ``-l / 2 + post_from_tip``, the round end at +x (CF125 drawing)."""

    l, half = s["l"], s["w"] / 2
    x0, end_r, waist = -l / 2, s["end_w"] / 2, s["waist"] / 2
    bore_r, cx = s["bore"] / 2, -l / 2 + s["post_from_tip"]
    inner = half - s["tine"]
    edge = [(x0 + 1.0, half), (x0 + 12.0, half - 0.5), (x0 + 24.0, half - 3.6), (x0 + s["waist_at"], waist),
            (l / 2 - end_r - 10.0, end_r + 0.4), (l / 2 - end_r, end_r)]
    upper = edge + [(l / 2 - end_r + end_r * math.cos(math.radians(a)), end_r * math.sin(math.radians(a)))
                    for a in range(80, -1, -10)]
    lower = [(x, -y) for x, y in reversed(upper[:-1])]
    reach = math.degrees(math.asin(min(inner / bore_r, 1.0)))
    bore = [(cx + bore_r * math.cos(math.radians(a)), bore_r * math.sin(math.radians(a)))
            for a in [-reach + k * (2 * reach) / 16 for k in range(17)]]
    pts = upper + lower + [(x0, -half + 0.8), (x0, -inner - 0.6), (x0 + 0.6, -inner)] + bore + \
        [(x0 + 0.6, inner), (x0, inner + 0.6), (x0, half - 0.8)]
    area = sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(pts, pts[1:] + pts[:1]))
    return pts if area > 0 else pts[::-1]


def _stadium(x0: float, x1: float, r: float, n: int = 10) -> list[tuple[float, float]]:
    """A slot from centre x0 to centre x1 along x, radius r, counter-clockwise."""

    right = [(x1 + r * math.cos(math.radians(a)), r * math.sin(math.radians(a))) for a in
             [-90 + 180 * k / n for k in range(n + 1)]]
    left = [(x0 + r * math.cos(math.radians(a)), r * math.sin(math.radians(a))) for a in
            [90 + 180 * k / n for k in range(n + 1)]]
    return right + left


STAINLESS = {"color": "#a7adb3", "metalness": 0.65, "roughness": 0.32}


def _fork_solids(s: dict) -> list[dict[str, Any]]:
    """A clamping fork from its drawing: the waisted plate with the bore for the pedestal and the slot cut through,
    and the counterbore round the slot."""

    end = s["l"] / 2
    a, b = (end - d for d in s["slot_from_end"])
    plate = {"shape": "extruded_polygon", "role": "fork plate", "points": [(x * MM, y * MM) for x, y in _fork_outline(s)],
             "holes": [[(x * MM, y * MM) for x, y in _stadium(min(a, b), max(a, b), 3.3)]],
             "height": s["t"] * MM, "material": STAINLESS}
    counterbore = {"shape": "extruded_polygon", "role": "counterbore",
                   "points": [(x * MM, y * MM) for x, y in _stadium(min(a, b), max(a, b), 5.6)],
                   "holes": [[(x * MM, y * MM) for x, y in _stadium(min(a, b), max(a, b), 3.3)]],
                   "height": 0.04, "position": [0.0, s["t"] * MM - 0.02, 0.0], "material": DARK}
    return [plate, counterbore]


def _clamp_solids(s: dict) -> list[dict[str, Any]]:
    """A table clamp from its side profile (CL5 drawing): a foot of the arm's thickness at -x, an inside fillet, the
    arm at the top and a rounded lip at +x that presses down on a base; the slot runs along the arm."""

    l, w, h, t = s["l"], s["w"], s["h"], s["t"]
    fillet, lip = 4.5 * t / 6.4, 4.6 * l / 50.8
    pts = [(0.0, 0.0), (t, 0.0)]
    cx, cy = t + fillet, h - t - fillet                      # inside fillet, from the foot up to the arm
    pts += [(cx + fillet * math.cos(math.radians(a)), cy + fillet * math.sin(math.radians(a))) for a in range(180, 89, -15)]
    pts += [(l - lip + lip * math.cos(math.radians(a)), h + t * math.sin(math.radians(a))) for a in range(-90, 1, 15)]
    pts.append((0.0, h))
    profile = [((x - l / 2) * MM, y * MM) for x, y in pts]
    # extruded up (u, v) -> (u, height, -v), then turned +90 deg about x: (u, v) stands in the x-y plane, the
    # extrusion runs along +z
    body = {"shape": "extruded_polygon", "role": "clamp body", "points": profile, "height": w * MM,
            "rotation": [math.pi / 2, 0.0, 0.0], "position": [0.0, 0.0, -w * MM / 2], "material": BLACK}
    slot_x = (26.0 * l / 50.8 - l / 2) * MM                  # the slot's middle, 26 mm from the foot on a CL5
    slot = _box(s["slot"] * MM + 6.6 * MM, 0.05, 6.6 * MM, (slot_x, h * MM + 0.025, 0), DARK, "slot")
    return [body, slot]


class CatalogHardware(_Vendor, Component):
    """Optical-table hardware at its size: the AB90A right-angle bracket, platform mounts (BSH05, BSH1, BSH20), the BP107 pellicle mount, the DMM1 D-mirror
    mount and the quadruple fiber mating-sleeve brackets (ADAFCB6, ADAFCPMB6). It stands on the table."""

    component_type = "CatalogHardware"
    TABLE = D.HARDWARE
    lies_on_table = True

    DEFAULT_PART = "AB90A"

    def __init__(self, center=(0, 0), angle=0, part=None, **kwargs):
        part = part or self.DEFAULT_PART
        _row(self.TABLE, part, self.component_type)
        self.part = part
        kwargs.setdefault("base_mount", "none")
        _set_common_free_space_fields(self, center, angle, kwargs, color="#23282e", opacity=1.0, material_preset="steel",
                                      label=kwargs.get("label", part))

    def symbol_1d(self):
        return ("platform", {})

    def ports(self) -> dict[str, Port]:
        return {}

    def _footprint(self) -> tuple[float, float]:
        s = self.spec
        return (s.get("l") or s.get("w")) * MM, (s.get("w") if s.get("l") else s.get("d", s.get("t", 10))) * MM

    def geometry_2d(self) -> dict[str, Any]:
        lx, wy = self._footprint()
        return {"type": "rect", "cx": 0, "cy": 0, "w": lx, "h": wy, "fill": "#3a3f45", "stroke": "#111827", "stroke_width": 0.1, "opacity": 0.9}

    def geometry_3d(self) -> dict[str, Any]:
        s = self.spec
        k = s["kind"]
        out: list[dict[str, Any]] = []
        if k == "fork":                               # the drawing's outline, the slot cut through it
            out += _fork_solids(s)
        elif k == "clamp":                            # an L: a foot at -x, an arm over to a rounded lip at +x
            out += _clamp_solids(s)
        elif k == "angle":                            # two slotted legs at a right angle
            l, w, h, t = s["l"] * MM, s["w"] * MM, s["h"] * MM, s["t"] * MM
            out.append(_box(l, t, w, (0, t / 2, 0), BLACK, "horizontal leg"))
            out.append(_box(t, h, w, (l / 2 - t / 2, h / 2, 0), BLACK, "vertical leg"))
        elif k == "platform":                         # a platform with a pocket for the cube
            l, w, t = s["l"] * MM, s["w"] * MM, s["t"] * MM
            floor = s["floor"] * MM
            out.append(_box(l, floor, w, (0, floor / 2, 0), BLACK, "base"))
            rim = (l - s["pocket"] * MM) / 2
            out.append(_box(rim, t - floor, w, (-l / 2 + rim / 2, floor + (t - floor) / 2, 0), BLACK, "clamp arm"))
            out.append(_box(rim, t - floor, w, (l / 2 - rim / 2, floor + (t - floor) / 2, 0), BLACK, "rim"))
        elif k in ("fork_mount", "cradle"):           # a half ring cradle on a base, the optic's axis at "axis"
            w, t, ax = s["w"] * MM, s["t"] * MM, s["axis"] * MM
            ri = s["inner_d"] * MM / 2
            out.append({**_ring_along_x(ri, min(w / 2, ri + 3.2 * MM), t, BLACK), "position": [0, ax, 0], "role": "frame"})
            out.append(_box(t, ax - ri + 0.5, w * 0.4, (0, (ax - ri + 0.5) / 2, 0), BLACK, "base"))
        elif k == "sleeve_bracket":                   # an L plate carrying a row of mating sleeves
            w, d, h, t = s["w"] * MM, s["d"] * MM, s["h"] * MM, s["t"] * MM
            out.append(_box(d, t, w, (0, t / 2, 0), BLACK, "base"))
            out.append(_box(t, h, w, (d / 2 - t / 2, h / 2, 0), BLACK, "plate"))
            n = int(s["count"])
            for i in range(n):
                z = (i - (n - 1) / 2) * s["pitch"] * MM
                out.append({**_cylinder_along_x(4.2 * MM, 15.0 * MM, STEEL, position=[d / 2, s["axis"] * MM, z]), "role": "mating sleeve"})
        return {"shape": "group", "children": out}

    def to_dict(self) -> dict[str, Any]:
        return self._vendor_dict(super().to_dict())


class CatalogTableClamp(CatalogHardware):
    """A table clamp or clamping fork at its size (CL4, CL5, CL5A, CL6, CL8, CF125): it holds a post's base or a
    mount's foot down on the table with one screw through its slot. It lies on the table."""

    component_type = "CatalogTableClamp"
    TABLE = D.CLAMPS
    DEFAULT_PART = "CL5"

    def geometry_2d(self) -> dict[str, Any]:
        if self.spec["kind"] != "fork":
            return super().geometry_2d()
        pts = " L ".join(f"{x * MM:.3f},{y * MM:.3f}" for x, y in _fork_outline(self.spec))
        return {"type": "path", "d": f"M {pts} Z", "fill": "#c3c8ce", "stroke": "#111827", "stroke_width": 0.1}


class CatalogSleeve(_Vendor, Component):
    """A fiber mating sleeve (butt coupler) with its square flange (ADAFC2 and the square-flange FC couplers):
    two fiber connectors meet in it, ``a`` and ``b``."""

    component_type = "CatalogSleeve"
    TABLE = D.SLEEVES

    def __init__(self, center=(0, 0), angle=0, part="ADAFC2", **kwargs):
        _row(self.TABLE, part, "CatalogSleeve")
        self.part = part
        _set_common_free_space_fields(self, center, angle, kwargs, color="#b9bfc6", opacity=1.0, material_preset="steel",
                                      label=kwargs.get("label", part))

    def symbol_1d(self):
        return ("matingsleeve", {})

    def ports(self) -> dict[str, Port]:
        h, w = self.spec["length"] * MM / 2, self.spec["barrel_d"] * MM
        return {"a": Port("a", Vec3(-h, 0, 0), orientation_deg=180.0, width=w, kind="fiber"),
                "b": Port("b", Vec3(h, 0, 0), orientation_deg=0.0, width=w, kind="fiber")}

    def geometry_2d(self) -> dict[str, Any]:
        s = self.spec
        return {"type": "group", "children": [
            {"type": "rect", "cx": 0, "cy": 0, "w": s["length"] * MM, "h": s["barrel_d"] * MM, "fill": "#b9bfc6", "stroke": "#4b5563", "stroke_width": 0.08},
            {"type": "rect", "cx": 0, "cy": 0, "w": s["flange_t"] * MM, "h": s["flange"] * MM, "fill": "#8f969e", "stroke": "#4b5563", "stroke_width": 0.08}]}

    def geometry_3d(self) -> dict[str, Any]:
        s = self.spec
        f, ft = s["flange"] * MM, s["flange_t"] * MM
        return {"shape": "group", "children": [
            {**_cylinder_along_x(s["barrel_d"] * MM / 2, s["length"] * MM, STEEL), "role": "barrel"},
            _box(ft, f, f, (0, 0, 0), ALU, "flange")], "post_at": [0.0, -f / 2, 0.0]}

    def to_dict(self) -> dict[str, Any]:
        return self._vendor_dict(super().to_dict())


FAMILIES = (CatalogLens, CatalogLensTube, CatalogAdapter, CatalogFilter, CatalogNDFilter, CatalogWavePlate,
            CatalogGlanPolarizer, CatalogPolarizer, CatalogCubeSplitter, CatalogPlateSplitter, CatalogMirror,
            CatalogDichroic, CatalogCageMount, CatalogCageCube, CatalogRightAngleMount, CatalogPhotodiode, CatalogLED,
            CatalogCollimator, CatalogCamera, CatalogHardware, CatalogTableClamp, CatalogSleeve)
