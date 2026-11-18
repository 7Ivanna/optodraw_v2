"""Look C: the cut 3D slab. A block of the layout on one side of the cut, made by the same process.

The block is the window of the cut wide and ``depth`` deep, on the left of the cut (seen from its first
point). Its face is the cross-section itself. Behind the face, the process runs again on cuts parallel to
it, one in each band of depth where the layout does not change, and each band's regions are extruded over
the band: the conformal oxide, the vias and the implants carry into 3D. A sidewall shows as the etch taper
across the cut; walls across the depth stay vertical. The cladding is cut away in steps toward the back,
with the wiring that starts above each step, so the lowest metal and then the waveguide show.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from shapely import affinity
from shapely.geometry import MultiPolygon, Polygon, box
from shapely.ops import unary_union

from optodraw.gds.xsection.cut import cut_layout, layer_key
from optodraw.gds.palette import DOPING, is_metal, material_fill

_EPS = 1e-9
_SLANT_STEPS = 32                    # bands across the depth where an edge runs at a slant to the cut
_FRONT = 0.15                        # the full stack in front, as a share of the depth
_SEEN = 0.15                         # the share of the depth each lower step shows past the one before it
_CLADDING = frozenset({"oxide", "passivation"})
_TINT = 0.45                         # an implant tints the silicon as in look A
INK = "#2b2f36"                      # the outlines on the face, as in look A


@dataclass
class SlabPiece:
    region: str
    material: str                    # palette key
    species: tuple[str, ...]         # the implants in this piece of silicon
    polygon: Polygon                 # in (s, z), z already stretched
    t0: float                        # its depth behind the face
    t1: float


@dataclass
class SlabModel:
    pieces: list[SlabPiece]
    window: tuple[float, float]
    depth: float
    strips: list[tuple[float, float, float | None]]   # t0, t1 and the cladding top there (None: not cut)
    z_scale: float = 1.0
    materials: dict[str, str] = field(default_factory=dict)


def _frame(cut):
    (x0, y0), (x1, y1) = cut
    length = math.hypot(x1 - x0, y1 - y0)
    ux, uy = (x1 - x0) / length, (y1 - y0) / length
    return (x0, y0), (ux, uy), (-uy, ux)


def _layout_events(layout, cut, window, depth) -> tuple[list[float], set[str]]:
    """The depths where the layout inside the block changes, and the layers it holds."""

    (x0, y0), (ux, uy), (nx, ny) = _frame(cut)
    block = box(window[0], 0.0, window[1], depth)
    events, keys, slanted = {0.0, depth}, set(), False
    for record in layout.layer_records:
        for points in record.polygons:
            if len(points) < 3:
                continue
            local = Polygon([((x - x0) * ux + (y - y0) * uy, (x - x0) * nx + (y - y0) * ny) for x, y in points])
            if not local.is_valid:
                local = local.buffer(0)
            inside = local.intersection(block)
            if inside.is_empty or inside.area <= _EPS:
                continue
            keys.add(layer_key(record.spec))
            for part in getattr(inside, "geoms", [inside]):
                if not isinstance(part, Polygon):
                    continue
                for ring in (part.exterior, *part.interiors):
                    coords = list(ring.coords)
                    events.update(t for _, t in coords)
                    for (sa, ta), (sb, tb) in zip(coords, coords[1:]):
                        slanted |= abs(sa - sb) > 1e-6 and abs(ta - tb) > 1e-6
    if slanted:                                          # a slanted edge moves along s: sample it
        events.update(depth * k / _SLANT_STEPS for k in range(1, _SLANT_STEPS))
    return sorted(t for t in events if -_EPS <= t <= depth + _EPS), keys


def _same(a: dict, b: dict) -> bool:
    if set(a) != set(b):
        return False
    return all(a[k].symmetric_difference(b[k]).area <= 1e-12 for k in a)


def _wiring(name: str, roles: dict[str, str], materials: dict[str, str]) -> tuple[bool, bool]:
    """Whether a region is wiring (metal, via, contact, pad or heater), and whether it is a metal line."""

    role = roles.get(name, "")
    via = role in ("contact", "via") or name.upper().startswith("VIA")
    wire = via or role in ("metal", "heater", "pad") or is_metal(materials.get(name, ""))
    return wire, wire and not via


def _metal_bottom(bands, roles: dict[str, str], materials: dict[str, str]) -> float | None:
    bottoms = [region.bounds[1] for _, _, regions, _, _ in bands for name, region in regions.items()
               if _wiring(name, roles, materials)[1] and not region.is_empty]
    return min(bottoms) if bottoms else None


def _strip_edges(xs, depth: float, level: float) -> list[float]:
    """Where the steps start: a step hides the floor behind it over its height / VIEW slope, so the middle
    step is that much longer than the share it shows."""

    slope = VIEW[2] / math.hypot(VIEW[0], VIEW[1])
    top = max(g.bounds[3] for g in xs.regions.values() if not g.is_empty)
    front = _FRONT * depth
    middle = front + max(2.0 * _SEEN * depth, (top - level) / slope + _SEEN * depth)
    return [0.0, front, min(middle, (1.0 - 2.0 * _SEEN) * depth), depth]


def slab_model(xs, depth: float | None = None, cutaway: bool = True, z_scale: float = 1.0) -> SlabModel:
    """The pieces of the cut 3D slab of ``xs``: ``depth`` um deep (default: as deep as the window is wide),
    the cladding cut away in steps when ``cutaway``, heights stretched by ``z_scale``."""

    from optodraw.gds.xsection.engine import XSectionEngine
    from optodraw.gds.xsection.model import _clip
    from optodraw.gds.xsection.stack_process import process_from_stack

    source = xs.source or {}
    if source.get("layout") is None or source.get("cut") is None:
        raise ValueError("a slab needs a cross-section made by cross_section(): it cuts the layout again")
    s0, s1 = xs.window
    depth = float(depth) if depth is not None else s1 - s0
    if depth <= 0:
        raise ValueError("the depth of a slab must be positive")
    layout, cut = source["layout"], source["cut"]
    events, keys = _layout_events(layout, cut, (s0, s1), depth)
    names: dict[str, str] = {}
    if source.get("stack") is not None:                  # every layer in the block gets its steps
        process = process_from_stack(source["stack"], drawn=keys)
    else:
        process = source["process"]
        names = {layer_key(item.gds): name for name, item in process.layout_layers.items()}
    levels: list[float | None] = [None]
    edges = [0.0, depth]
    if cutaway:
        face = [(0.0, 0.0, xs.regions, {}, 0)]
        metal = _metal_bottom(face, xs.roles, xs.materials)
        levels = [None, metal, 0.0] if metal is not None else [None, 0.0, 0.0]
        edges = _strip_edges(xs, depth, levels[1])
    events = sorted(set(events) | set(edges))
    _, _, (nx, ny) = _frame(cut)
    (xa, ya), (xb, yb) = cut
    materials = dict(xs.materials)
    bands: list[tuple[float, float, dict, dict, int]] = []      # t0, t1, regions, doping, strip
    for t0, t1 in zip(events, events[1:]):
        if t1 - t0 <= 1e-6:
            continue
        if t0 == 0.0:
            regions, doping = dict(xs.regions), {k: v for k, v in xs.doping.items() if not v.is_empty}
        else:
            t = (t0 + t1) / 2.0
            full = cut_layout(layout, (xa + nx * t, ya + ny * t), (xb + nx * t, yb + ny * t))
            out = XSectionEngine(process).run(_clip(full, s0, s1, names))
            regions, doping = out.internal_regions, {k: v for k, v in out.doping.items() if not v.is_empty}
            for name, material in out.materials.items():
                materials.setdefault(name, material)
        strip = max(i for i, edge in enumerate(edges[:-1]) if edge <= t0 + 1e-9)
        last = bands[-1] if bands else None
        if (last is not None and abs(last[1] - t0) <= 1e-9 and last[4] == strip and _same(last[2], regions)
                and _same(last[3], doping)):
            bands[-1] = (last[0], t1, last[2], last[3], strip)          # nothing changed: one longer band
        else:
            bands.append((t0, t1, regions, doping, strip))
    strips = [(edges[i], edges[i + 1], levels[i]) for i in range(len(edges) - 1)]
    cladding = _CLADDING | {name for name, material in materials.items()
                            if name != "box" and str(material).lower() in ("sio2", "oxide")}
    pieces: list[SlabPiece] = []
    for t0, t1, regions, doping, strip in bands:
        level = levels[strip]
        for name, region in regions.items():
            if region.is_empty:
                continue
            if level is not None and name in cladding:
                x_lo, z_lo, x_hi, _ = region.bounds
                region = region.intersection(box(x_lo - 1.0, z_lo - 1.0, x_hi + 1.0, level))
            elif level is not None and region.bounds[1] > level + 1e-9 and _wiring(name, xs.roles, materials)[0]:
                continue                                 # wiring that starts above the step goes with it
            parts = [(region, ())]
            for species, dose in doping.items():
                split = []
                for geometry, held in parts:
                    inside = geometry.intersection(dose)
                    if inside.area > _EPS:
                        split += [(inside, (*held, species)), (geometry.difference(dose), held)]
                    else:
                        split.append((geometry, held))
                parts = split
            for geometry, held in parts:
                for polygon in _polygons(geometry):
                    if z_scale != 1.0:
                        polygon = affinity.scale(polygon, 1.0, z_scale, origin=(0.0, 0.0))
                    pieces.append(SlabPiece(name, str(materials.get(name, name)), held, polygon, t0, t1))
    return SlabModel(pieces=pieces, window=(s0, s1), depth=depth, strips=strips, z_scale=float(z_scale),
                     materials=materials)


def _polygons(geometry) -> list[Polygon]:
    if geometry.is_empty:
        return []
    if isinstance(geometry, Polygon):
        return [geometry] if geometry.area > _EPS else []
    if isinstance(geometry, MultiPolygon) or hasattr(geometry, "geoms"):
        return [p for g in geometry.geoms for p in _polygons(g)]
    return []


def _blend(base: str, tint: str, share: float) -> str:
    a = [int(base.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)]
    b = [int(tint.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)]
    return "#" + "".join(f"{round(x + (y - x) * share):02x}" for x, y in zip(a, b))


def piece_style(piece: SlabPiece) -> dict[str, object]:
    """The name, colour and finish of a piece: the look A palette, an implant as a tint, metals shine."""

    color = material_fill(piece.material)
    for species in piece.species:
        color = _blend(color, DOPING.get(species.upper(), "#888888"), _TINT)
    metal = is_metal(piece.material)
    return {"name": " ".join([piece.material, *piece.species]), "color": color,
            "metalness": 0.6 if metal else 0.0, "roughness": 0.35 if metal else 0.75}


def slab_glb(model: SlabModel) -> bytes:
    """The slab as a binary glTF: one mesh per region and implant, named, with a named material each.

    The block's axes are s along x, depth along y and z up; glTF is y up, so a point (s, t, z) is written
    (s, z, -t) and the face lies at z = 0, facing +z, as in the three.js viewer.
    """

    import numpy as np
    import trimesh
    from trimesh.visual.material import PBRMaterial

    from optodraw.gds.layout import _exported_glb_bytes

    groups: dict[str, list] = {}
    styles: dict[str, dict] = {}
    for piece in model.pieces:
        h = piece.t1 - piece.t0
        solid = trimesh.creation.extrude_polygon(piece.polygon, h)        # (s, z, e), e = 0 .. h
        # (s, z, e) -> glTF (s, z, e - t1): e = h is the side nearest the face
        solid.apply_transform(np.array([[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, -piece.t1], [0, 0, 0, 1]], float))
        key = " ".join([piece.region, *piece.species])
        groups.setdefault(key, []).append(solid)
        styles.setdefault(key, piece_style(piece))
    scene = trimesh.Scene()
    for key, solids in groups.items():
        mesh = trimesh.util.concatenate(solids)
        style = styles[key]
        rgba = [int(style["color"][i:i + 2], 16) / 255.0 for i in (1, 3, 5)] + [1.0]
        mesh.visual = trimesh.visual.TextureVisuals(material=PBRMaterial(
            name=str(style["name"]), baseColorFactor=rgba, metallicFactor=float(style["metalness"]),
            roughnessFactor=float(style["roughness"]), doubleSided=False))
        scene.add_geometry(mesh, geom_name=key, node_name=key)
    return _exported_glb_bytes(scene.export(file_type="glb"))


VIEW = (0.55, -1.0, 1.1)             # the slab image looks down at about 40 degrees, from the front right


def face_outline(model: SlabModel) -> MultiPolygon:
    """Thin strips round each region of the face, as look A outlines them (not round the implants)."""

    on_face: dict[str, list[Polygon]] = {}
    for piece in model.pieces:
        if piece.t0 == 0.0:
            on_face.setdefault(piece.region, []).append(piece.polygon)
    if not on_face:
        return MultiPolygon([])
    edges = unary_union([unary_union(parts).boundary for parts in on_face.values()])
    face = unary_union([unary_union(parts) for parts in on_face.values()])
    width = (model.window[1] - model.window[0]) / 800.0
    strips = edges.buffer(width / 2.0, cap_style="flat", join_style="mitre").intersection(face)
    return MultiPolygon(_polygons(strips))


def _prism(polygon: Polygon, t0: float, t1: float, material: dict, centre: tuple[float, float]) -> dict:
    # the polygon lies in the x-y plane, extruded along +z by its depth, then moved back by t1: the face at
    # t = 0 faces +z and the block runs to -z (+y in the world); ``centre`` (s, t) goes to the part's origin
    s_mid, t_mid = centre
    return {"shape": "extruded_polygon", "height": t1 - t0,
            "points": [[x - s_mid, z] for x, z in polygon.exterior.coords[:-1]],
            "holes": [[[x - s_mid, z] for x, z in ring.coords[:-1]] for ring in polygon.interiors],
            "rotation": [math.pi / 2.0, 0.0, 0.0], "position": [0.0, 0.0, t_mid - t1], "material": material}


def _part(model: SlabModel, outline: bool):
    from optodraw.core.component import Component
    from optodraw.core.transform import Transform

    class CrossSectionSlab(Component):
        """The cut 3D slab as one part: s along x, the depth along y, z up."""

        component_type = "CrossSectionSlab"

        def __init__(self) -> None:
            self.label, self.color, self.opacity = "", "#9aa9bd", 1.0
            self.lies_on_table = True                        # it stands on the table, not on a post
            self.transform = Transform.from_2d(0.0, 0.0, 0.0)
            self._parent, self._id = None, ""

        def geometry_2d(self) -> dict:
            (s0, s1), d = model.window, model.depth
            return {"type": "rect", "cx": 0.0, "cy": 0.0, "w": s1 - s0, "h": d,
                    "fill": "#e6eff7", "stroke": INK, "stroke_width": 0.1}

        def geometry_3d(self) -> dict:
            centre = ((model.window[0] + model.window[1]) / 2.0, model.depth / 2.0)
            children = []
            for piece in model.pieces:
                style = piece_style(piece)
                children.append(_prism(piece.polygon, piece.t0, piece.t1, {
                    "color": style["color"], "metalness": style["metalness"], "roughness": style["roughness"]},
                    centre))
            if outline:                                      # just in front of the face
                width = (model.window[1] - model.window[0]) / 800.0
                ink = {"color": INK, "metalness": 0.0, "roughness": 1.0}
                for strip in face_outline(model).geoms:      # its edges keep a line one pixel wide when small
                    children.append({**_prism(strip, -width / 2.0, 0.0, ink, centre), "edges": INK})
            return {"shape": "group", "children": children}

    return CrossSectionSlab()


def slab_scene(model: SlabModel, outline: bool = True):
    """A scene that holds the slab, for the three.js view and the headless image. ``outline`` draws the
    region edges on the face, as look A does."""

    from optodraw.core.scene import Scene

    (s0, s1), d = model.window, model.depth
    scene = Scene(title="Cross-section slab", width=max(s1 - s0, 1.0), height=max(d, 1.0))
    scene.add(_part(model, outline))
    return scene


def render_slab(model: SlabModel, path, *, background: str = "none", camera=VIEW, width: int = 1600,
                height: int = 1000, scale: float = 2.0, chrome: str | None = None):
    """The slab as a PNG from the viewer, headless (needs Chrome, Chromium or Edge)."""

    return slab_scene(model).render_3d_image(str(path), background=background, camera=camera, width=width,
                                             height=height, scale=scale, engine="viewer", chrome=chrome)
