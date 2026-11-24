"""The 3D viewer's solids as planar faces, for the vector 3D renderer.

Each kind copies the three.js geometry the viewer page builds, vertex for vertex, so the silhouettes and the boxes
match the viewer. A face is planar, counter-clockwise seen from outside, with its holes clockwise. An open surface
(three.js DoubleSide) gives each facet twice, once per side. The curve and geometry rules come from the three.js
sources of the version the page loads (THREEJS_CDN)."""

from __future__ import annotations

import math
from collections.abc import Iterator
from dataclasses import dataclass, field, replace

import numpy as np

from optodraw.renderers.threejs_renderer import PageConstants

CREASE_DEG = 50.0          # the viewer's toCreasedNormals angle: a sharper turn starts a new surface
Y_AXIS = np.array([0.0, 1.0, 0.0])


class Vector3DError(ValueError):
    """The vector 3D view cannot draw this scene."""


@dataclass(frozen=True)
class Look:
    """A material as the viewer's makeMaterial() resolves it: the preset merged under the record."""

    color: str                 # the viewer's base colour; `physical` when metalness >= 0.9
    opacity: float = 1.0
    metalness: float = 0.0
    roughness: float = 1.0
    clearcoat: float = 0.0
    transmission: float = 0.0
    preset: str | None = None
    unlit: bool = False        # an emissive beam core: its colour takes no light
    edges: str | None = None   # an extrusion's outline colour (geo.edges): the viewer's EdgesGeometry(geo, 1) lines
    edge_opacity: float = 1.0

    @property
    def clear(self) -> bool:
        """A clear solid hides nothing and paints last."""

        return self.opacity < 1.0 or self.transmission > 0.0


@dataclass(frozen=True)
class Solid:
    id: int                    # build order, as the viewer adds its meshes; the index in SolidSet.solids
    part: str                  # the scene item's sid; "mount:<sid>" for its mount; "base:die" and "base:carrier"
    kind: str                  # the shape: "box", "cylinder", "sphere", "torus", "extruded_polygon", "lathe_profile",
                               # "tube_path", "text_decal"; or the page's own "beam", "strip", "cable"
    look: Look
    closed: bool               # False for an open surface: its faces hold the sides the viewer shows
    chip: bool                 # a chip item: its figure colour comes from the section palette


@dataclass(eq=False)
class Face:
    ring: np.ndarray           # (n, 3), counter-clockwise seen from outside
    holes: tuple[np.ndarray, ...]
    normal: np.ndarray         # unit, outward
    solid: int                 # Solid.id
    surface: tuple             # facets with one key merge into one path
    shading: str               # "flat" | "axis" (one gradient across `axis`) | "steps" (shade steps)
    axis: np.ndarray | None = None


@dataclass(eq=False)
class Decal:
    """The text of a text_decal. Its plane is clear but for the glyphs, so the solid has no faces."""

    solid: int                 # Solid.id
    plane: np.ndarray          # (4, 3) world corners, counter-clockwise seen from the front (local +z)
    rings: list[np.ndarray]    # glyph outlines, (n, 3) world, filled even-odd; from behind they show mirrored
    color: str


@dataclass(eq=False)
class HoleGrid:
    """The holes of a hole_grid top texture (odHolePlateTexture), each one dark ellipse on the box's top face."""

    solid: int                 # Solid.id of the plate; its other faces take the texture's side colour
    surface: tuple             # the top face's surface key
    top: Look                  # the top face: the texture's base colour (the viewer paints the top white under it)
    centres: np.ndarray        # (n, 3) world, on the top face
    axes: np.ndarray           # (2, 3) world half axes of every hole
    color: str = "#0e1218"     # the bore


@dataclass(eq=False)
class Band:
    """The clear glow along a beam segment, or a focusing beam's cone: a band from ``start`` to ``end`` that faces
    the camera, ``widths`` wide at its two ends. The viewer has no mesh for it, so it is no solid."""

    part: str                  # the scene item's sid
    start: np.ndarray          # (3,) world
    end: np.ndarray
    widths: tuple[float, float]
    color: str


Box = tuple[np.ndarray, np.ndarray]     # a three.js Box3: min and max corners, world


@dataclass(eq=False)
class SolidSet:
    constants: PageConstants
    solids: list[Solid] = field(default_factory=list)
    faces: list[Face] = field(default_factory=list)
    notes: tuple[str, ...] = ()
    decals: list[Decal] = field(default_factory=list)
    hole_grids: list[HoleGrid] = field(default_factory=list)
    bands: list[Band] = field(default_factory=list)
    boxes: list[Box] = field(default_factory=list)   # what the viewer frames: each content group, then the chip base


def _hex(color) -> str:
    if isinstance(color, (int, float)):
        return f"#{int(color) & 0xFFFFFF:06x}"
    text = str(color).strip().lower()
    if len(text) == 4 and text.startswith("#"):
        return "#" + "".join(c * 2 for c in text[1:])
    return text


def look_of(material: dict, catalog: dict) -> Look:
    """The look of a material record, as makeMaterial() builds it: ``{...preset, ...record}``."""

    preset = material.get("preset")
    base = (catalog.get(preset) or {}) if preset else {}
    merged = {**base, **material}
    metalness = float(merged.get("metalness") or 0.0)
    color = merged.get("color") or "#ffffff"
    if merged.get("physical") and metalness >= 0.9:
        color = merged["physical"]
    opacity = merged.get("opacity")
    roughness = merged.get("roughness")
    return Look(color=_hex(color), opacity=1.0 if opacity is None else float(opacity), metalness=metalness,
                roughness=1.0 if roughness is None else float(roughness),
                clearcoat=float(merged.get("clearcoat") or 0.0),
                transmission=float(merged.get("transmission") or 0.0), preset=preset)


def figure_color(solid: Solid) -> str:
    """The flat colour of a solid in a figure: the section palette's colour for a chip material, else its own."""

    from optodraw.gds.palette import material_fill, material_label

    preset = solid.look.preset
    if solid.chip and preset and material_label(preset) is not None:
        return material_fill(preset)
    if solid.part == "base:die":            # a chip's top is its oxide, as the section draws it: silicon shows on it
        return material_fill("sio2")
    return solid.look.color


def _rotation(x: float, y: float, z: float) -> np.ndarray:
    """three.js Euler order XYZ."""

    cx, sx, cy, sy, cz, sz = math.cos(x), math.sin(x), math.cos(y), math.sin(y), math.cos(z), math.sin(z)
    rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
    return rx @ ry @ rz


def trs(position=None, rotation=None, scale=None) -> np.ndarray:
    """The matrix of an Object3D: T(position) R(rotation) S(scale)."""

    m = np.eye(4)
    m[:3, :3] = _rotation(*(rotation or (0.0, 0.0, 0.0))) @ np.diag([float(v) for v in (scale or (1.0, 1.0, 1.0))])
    m[:3, 3] = [float(v) for v in (position or (0.0, 0.0, 0.0))]
    return m


def _newell(ring: np.ndarray) -> np.ndarray:
    """The vector area of a ring: its normal times its area, by the winding."""

    nxt = np.roll(ring, -1, axis=0)
    return 0.5 * np.cross(ring, nxt).sum(axis=0)


def _facet(ring, outward, surface: tuple, shading: str = "flat", holes=(), axis=None) -> Face:
    """A face with its ring turned counter-clockwise seen along ``outward``, and its holes the other way."""

    ring = np.asarray(ring, float)
    outward = np.asarray(outward, float)
    area = _newell(ring)
    if area @ outward < 0:
        ring, area = ring[::-1], -area
    holes = tuple(h if _newell(h) @ outward < 0 else h[::-1] for h in (np.asarray(h, float) for h in holes))
    return Face(ring, holes, area / np.linalg.norm(area), -1, surface, shading, axis)


def box(geo: dict) -> list[Face]:
    """BoxGeometry(width, height, depth): six faces. A missing size is 1; a box with a size of 0 draws nothing,
    as in the viewer."""

    half = np.array([float(1 if geo.get(k) is None else geo[k]) for k in ("width", "height", "depth")]) / 2
    if not (half > 0).all():
        return []
    faces = []
    for axis, name in enumerate("xyz"):
        u, v = [a for a in range(3) if a != axis]
        for sign in (1, -1):
            corners = []
            for a, b in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
                p = np.zeros(3)
                p[axis], p[u], p[v] = sign * half[axis], a * half[u], b * half[v]
                corners.append(p)
            normal = np.zeros(3)
            normal[axis] = sign
            faces.append(_facet(corners, normal, (("p" if sign > 0 else "n") + name,)))
    return faces


def _cap(points: np.ndarray, sign: float) -> Face:
    return _facet(points, (0.0, sign, 0.0), ("top" if sign > 0 else "bottom",))


def cylinder(geo: dict) -> list[Face]:
    """CylinderGeometry(radiusTop, radiusBottom, h, radialSegments): a vertex at angle t is (r sin t, y, r cos t),
    t from 0. A catalog part gives ``radius`` only, and the viewer draws it with 32 sides; the page's own mounts and
    beams give the three.js arguments."""

    r = float(geo.get("radius") or 1)
    r_top, r_bottom = float(geo.get("radiusTop", r)), float(geo.get("radiusBottom", r))
    h, n = float(geo.get("height") or 1) / 2, int(geo.get("radialSegments") or 32)
    t = 2 * math.pi * np.arange(n) / n
    ring = np.column_stack((np.sin(t), np.full(n, h), np.cos(t)))
    top, bottom = ring * (r_top, 1, r_top), ring * (r_bottom, -1, r_bottom)
    axis = np.array([0.0, 1.0, 0.0])
    walls = []
    for x in range(n):
        y = (x + 1) % n
        mid = (t[x] + math.pi / n)
        walls.append(_facet([top[x], bottom[x], bottom[y], top[y]], (math.sin(mid), 0, math.cos(mid)),
                            ("wall", 0), "axis", axis=axis))
    return walls + [_cap(top, 1.0), _cap(bottom, -1.0)]


def sphere(geo: dict) -> list[Face]:
    """SphereGeometry(r, 32, 32): vertex (-r cos(phi) sin(theta), r cos(theta), r sin(phi) sin(theta)); a
    triangle at each pole, a planar quad elsewhere."""

    r = float(geo.get("radius") or 1)
    phi = 2 * math.pi * np.arange(33) / 32
    theta = math.pi * np.arange(33) / 32
    grid = np.stack([np.column_stack((-r * np.cos(phi) * math.sin(th), np.full(33, r * math.cos(th)),
                                      r * np.sin(phi) * math.sin(th))) for th in theta])
    faces = []
    for iy in range(32):
        for ix in range(32):
            a, b, c, d = grid[iy, ix + 1], grid[iy, ix], grid[iy + 1, ix], grid[iy + 1, ix + 1]
            ring = [b, c, d] if iy == 0 else [a, b, d] if iy == 31 else [a, b, c, d]
            faces.append(_facet(ring, np.mean(ring, axis=0), ("sphere",), "steps"))
    return faces


def _contour(points) -> np.ndarray:
    """A Shape path as three.js reads it: consecutive repeats dropped, then a closing repeat."""

    pts = [(float(p[0]), float(p[1])) for p in points]
    out = [p for i, p in enumerate(pts) if i == 0 or p != pts[i - 1]]
    if len(out) > 1 and out[-1] == out[0]:
        out.pop()
    return np.array(out, float).reshape(-1, 2)


def _signed_area(ring: np.ndarray) -> float:
    x, y = ring[:, 0], ring[:, 1]
    return 0.5 * float(np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y))


def _walls(ring: np.ndarray, height: float, number: int) -> list[Face]:
    """The side walls along one contour, ring counter-clockwise for the outline and clockwise for a hole, so the
    outward normal of an edge (du, dv) is (dv, -du). A turn over CREASE_DEG starts a new surface."""

    count = len(ring)
    edges = np.roll(ring, -1, axis=0) - ring
    heading = np.arctan2(edges[:, 1], edges[:, 0])
    turn = np.degrees(np.abs((heading - np.roll(heading, 1) + math.pi) % (2 * math.pi) - math.pi))
    creases = [i for i in range(count) if turn[i] > CREASE_DEG]
    start = creases[0] if creases else 0
    runs: list[list[int]] = []
    run: list[int] = []
    for step in range(count):
        i = (start + step) % count
        if run and turn[i] > CREASE_DEG:
            runs.append(run)
            run = []
        run.append(i)
    runs.append(run)
    faces = []
    for number_in_ring, members in enumerate(runs):
        shading = "flat" if len(members) == 1 else "steps"
        for i in members:
            (u0, v0), (u1, v1) = ring[i], ring[(i + 1) % count]
            quad = [(u0, 0, -v0), (u1, 0, -v1), (u1, height, -v1), (u0, height, -v0)]
            du, dv = u1 - u0, v1 - v0
            faces.append(_facet(quad, (dv, 0, du), ("wall", number, number_in_ring), shading))
    return faces


def extruded_polygon(geo: dict) -> list[Face]:
    """ExtrudeGeometry of a Shape (x, y) with holes, depth ``height``, turned by rotateX(-pi/2): (x, y) at depth h
    goes to (x, h, -y)."""

    if len(geo.get("points") or []) < 3:
        return []
    height = float(geo.get("height") or 0.22)
    outline = _contour(geo["points"])
    if len(outline) < 3:
        return []
    if _signed_area(outline) < 0:
        outline = outline[::-1]
    holes = []
    for hole in geo.get("holes") or []:
        if hole and len(hole) >= 3:
            ring = _contour(hole)
            holes.append(ring if _signed_area(ring) < 0 else ring[::-1])

    def lift(ring, y):
        return np.column_stack((ring[:, 0], np.full(len(ring), y), -ring[:, 1]))

    faces = [_facet(lift(outline, height), (0, 1, 0), ("top",), holes=[lift(h, height) for h in holes]),
             _facet(lift(outline, 0.0), (0, -1, 0), ("bottom",), holes=[lift(h, 0.0) for h in holes])]
    for number, ring in enumerate([outline, *holes]):
        faces += _walls(ring, height, number)
    return faces


def _both_sides(faces: list[Face]) -> list[Face]:
    """An open surface, as three.js DoubleSide draws it: each facet again, wound the other way."""

    return faces + [Face(f.ring[::-1], tuple(h[::-1] for h in f.holes), -f.normal, f.solid, (*f.surface, "back"),
                         f.shading, f.axis) for f in faces]


def _revolved(profile: np.ndarray, radial: np.ndarray, axis: np.ndarray, key, shading) -> list[Face]:
    """The facets between profile points j, j + 1 (radius, height) at the angles i, i + 1: planar trapezoids, or
    triangles where the profile meets the axis. ``radial`` holds the unit radial vector at each angle, the first
    one again at the end. The outward side of a profile edge (dr, dh) is (dh, -dr), as three.js sets the normals."""

    faces = []
    for i in range(len(radial) - 1):
        for j in range(len(profile) - 1):
            (r0, h0), (r1, h1) = profile[j], profile[j + 1]
            ring = [r0 * radial[i] + h0 * axis, r0 * radial[i + 1] + h0 * axis,
                    r1 * radial[i + 1] + h1 * axis, r1 * radial[i] + h1 * axis]
            ring = [p for k, p in enumerate(ring) if not np.array_equal(p, ring[k - 1])]
            if len(ring) < 3:
                continue
            outward = (h1 - h0) * (radial[i] + radial[i + 1]) - (r1 - r0) * axis
            faces.append(_facet(ring, outward, key(i, j), shading(j), axis=axis))
    return faces


def torus(geo: dict) -> list[Face]:
    """TorusGeometry(radius, tube, 18, 96) in local x-y: vertex ((R + r cos v) cos u, (R + r cos v) sin u, r sin v),
    u = 2 pi i / 96 and v = 2 pi j / 18, both from 0."""

    big, small = float(geo.get("radius") or 1), float(geo.get("tube") or 0.2)
    v = np.arange(19) / 18 * (2 * math.pi)
    u = np.arange(97) / 96 * (2 * math.pi)
    profile = np.column_stack((big + small * np.cos(v), small * np.sin(v)))
    radial = np.column_stack((np.cos(u), np.sin(u), np.zeros(97)))
    return _revolved(profile, radial, np.array([0.0, 0.0, 1.0]), lambda i, j: ("torus",), lambda j: "steps")


def _profile(geo: dict) -> np.ndarray:
    return np.array([(float(p[0]), float(p[1])) for p in geo.get("points") or []], float).reshape(-1, 2)


def _lathe_closed(points: np.ndarray) -> bool:
    """A lathe encloses a solid when its profile is a loop or runs from the axis to the axis. three.js adds no caps,
    so any other profile is an open surface."""

    return bool(np.array_equal(points[0], points[-1]) or (points[0][0] == 0 and points[-1][0] == 0))


def lathe_profile(geo: dict) -> list[Face]:
    """LatheGeometry(points, segments or 24), no caps: a profile point (x, y) at phi = 2 pi i / segments goes to
    (x sin phi, y, x cos phi). A profile turn over CREASE_DEG starts a new surface, and so does each side when the
    sides themselves turn by more."""

    points = _profile(geo)
    if len(points) < 2:
        return []
    count = int(geo.get("segments") or 24)
    closed = _lathe_closed(points)
    if closed and _signed_area(points) < 0:
        points = points[::-1]
    edges = np.diff(points, axis=0)
    a, b = edges[:-1], edges[1:]
    turn = np.degrees(np.arctan2(np.abs(a[:, 0] * b[:, 1] - a[:, 1] * b[:, 0]), np.sum(a * b, axis=1)))
    run = np.concatenate(([0], np.cumsum(turn > CREASE_DEG)))       # the crease run of each profile edge
    phi = np.arange(count + 1) * (1.0 / count) * (2 * math.pi)
    radial = np.column_stack((np.sin(phi), np.zeros(count + 1), np.cos(phi)))
    if 360.0 / count > CREASE_DEG:
        sizes = np.bincount(run)
        faces = _revolved(points, radial, Y_AXIS, lambda i, j: ("lathe", int(run[j]), i),
                          lambda j: "flat" if sizes[run[j]] == 1 else "steps")
    else:
        faces = _revolved(points, radial, Y_AXIS, lambda i, j: ("lathe", int(run[j])), lambda j: "axis")
    return faces if closed else _both_sides(faces)


def _turn(axis: np.ndarray, angle: float) -> np.ndarray:
    """Matrix4.makeRotationAxis."""

    c, s = math.cos(angle), math.sin(angle)
    t = 1 - c
    x, y, z = axis
    return np.array([[t * x * x + c, t * x * y - s * z, t * x * z + s * y],
                     [t * x * y + s * z, t * y * y + c, t * y * z - s * x],
                     [t * x * z - s * y, t * y * z + s * x, t * z * z + c]])


class CatmullRom:
    """CatmullRomCurve3(points), open and centripetal, with the Curve base's arc-length table of 200 divisions.
    three.js reads the tension only for the uniform type, so a centripetal curve has none."""

    def __init__(self, points):
        p = np.asarray(points, float).reshape(-1, 3)
        self.points = p
        self._ends = np.vstack(((p[0] - p[1]) + p[0], p, (p[-1] - p[-2]) + p[-1]))   # three.js extrapolates both ends
        steps = self.point(np.arange(201) / 200)
        self.lengths = np.concatenate(([0.0], np.cumsum(np.linalg.norm(np.diff(steps, axis=0), axis=1))))

    def point(self, t) -> np.ndarray:
        """getPoint(t) for an array of t in [0, 1]."""

        n = len(self.points)
        p = (n - 1) * np.asarray(t, float)
        k = np.floor(p).astype(int)
        w = p - k
        end = (w == 0) & (k == n - 1)
        k, w = np.where(end, n - 2, k), np.where(end, 1.0, w)[..., None]
        p0, p1, p2, p3 = (self._ends[k + s] for s in range(4))

        def knot(a, b):
            return np.sum((a - b) ** 2, axis=-1) ** 0.25

        d0, d1, d2 = knot(p0, p1), knot(p1, p2), knot(p2, p3)
        d1 = np.where(d1 < 1e-4, 1.0, d1)
        d0, d2 = np.where(d0 < 1e-4, d1, d0)[..., None], np.where(d2 < 1e-4, d1, d2)[..., None]
        d1 = d1[..., None]
        m1 = ((p1 - p0) / d0 - (p2 - p0) / (d0 + d1) + (p2 - p1) / d1) * d1
        m2 = ((p2 - p1) / d1 - (p3 - p1) / (d1 + d2) + (p3 - p2) / d2) * d1
        c2 = -3 * p1 + 3 * p2 - 2 * m1 - m2
        c3 = 2 * p1 - 2 * p2 + m1 + m2
        w2 = w * w
        return p1 + m1 * w + c2 * w2 + c3 * (w2 * w)

    def u_to_t(self, u) -> np.ndarray:
        """getUtoTmapping: the t at the arc-length fraction u, read from the table."""

        arcs = self.lengths
        target = np.asarray(u, float) * arcs[-1]
        i = np.clip(np.searchsorted(arcs, target, side="right") - 1, 0, len(arcs) - 2)
        span = arcs[i + 1] - arcs[i]
        frac = np.where(span > 0, (target - arcs[i]) / np.where(span > 0, span, 1.0), 0.0)
        return (i + frac) / (len(arcs) - 1)

    def point_at(self, u) -> np.ndarray:
        return self.point(self.u_to_t(u))

    def tangent(self, t) -> np.ndarray:
        """getTangent: the unit chord over t - 1e-4 to t + 1e-4, held inside [0, 1]."""

        t = np.asarray(t, float)
        d = self.point(np.minimum(t + 1e-4, 1.0)) - self.point(np.maximum(t - 1e-4, 0.0))
        return d / np.linalg.norm(d, axis=-1, keepdims=True)

    def frames(self, segments: int) -> tuple[np.ndarray, np.ndarray]:
        """computeFrenetFrames(segments, false): the normals and binormals at u = i / segments. The first normal is
        square to the tangent and its smallest axis; each next one turns with the tangent."""

        tangents = self.tangent(self.u_to_t(np.arange(segments + 1) / segments))
        first = tangents[0]
        least = np.eye(3)[2 - int(np.argmin(np.abs(first)[::-1]))]          # a tie goes to the later axis
        side = np.cross(first, least)
        normals = [np.cross(first, side / np.linalg.norm(side))]
        for before, after in zip(tangents[:-1], tangents[1:]):
            normal = normals[-1]
            pivot = np.cross(before, after)
            if np.linalg.norm(pivot) > np.finfo(float).eps:
                angle = math.acos(min(max(float(before @ after), -1.0), 1.0))
                normal = _turn(pivot / np.linalg.norm(pivot), angle) @ normal
            normals.append(normal)
        normals = np.array(normals)
        return normals, np.cross(tangents, normals)


def tube_path(geo: dict, *, double_sided: bool = True) -> list[Face]:
    """TubeGeometry(CatmullRomCurve3(points), segments or 32, radius or 0.2, radialSegments or 12, open): ring i
    sits at getPointAt(i / segments), its vertex j at angle v = 2 pi j / radialSegments along -cos(v) N + sin(v) B.
    Triangles, as three.js indexes them; no caps, so both sides show, unless ``double_sided`` is False (a page
    cable, drawn FrontSide)."""

    if len(geo.get("points") or []) < 2:
        return []
    segments, radial = int(geo.get("segments") or 32), int(geo.get("radialSegments") or 12)
    curve = CatmullRom(geo["points"])
    normals, binormals = curve.frames(segments)
    v = np.arange(radial + 1) / radial * math.pi * 2
    out = -np.cos(v)[None, :, None] * normals[:, None] + np.sin(v)[None, :, None] * binormals[:, None]
    out /= np.linalg.norm(out, axis=2, keepdims=True)
    grid = curve.point_at(np.arange(segments + 1) / segments)[:, None] + float(geo.get("radius") or 0.2) * out
    faces = []
    for j in range(1, segments + 1):
        for i in range(1, radial + 1):
            a, b, c, d = (j - 1, i - 1), (j, i - 1), (j, i), (j - 1, i)
            for tri in ((a, b, d), (b, c, d)):
                faces.append(_facet([grid[k] for k in tri], sum(out[k] for k in tri), ("tube",), "steps"))
    return _both_sides(faces) if double_sided else faces


def text_decal(geo: dict) -> list[Face]:
    """PlaneGeometry(width, height) in local x-y, facing +z. The plane only sizes the part's box: it is clear but
    for its text, so the solid keeps no faces and decal_glyphs() gives the text."""

    w, h = float(geo.get("width") or 4) / 2, float(geo.get("height") or 2) / 2
    return [_facet([(-w, -h, 0.0), (w, -h, 0.0), (w, h, 0.0), (-w, h, 0.0)], (0.0, 0.0, 1.0), ("decal",))]


def decal_glyphs(geo: dict) -> list[np.ndarray]:
    """The glyph outlines of a text_decal on its plane, local (x, y, 0), filled even-odd. The viewer prints the text
    bold, sans-serif, at min(fontSize or 140, 230) px, centred on a 512 x 256 canvas that it stretches over
    width x height and that clips the text."""

    import shapely
    from matplotlib.font_manager import FontProperties
    from matplotlib.textpath import TextPath

    text = str(geo.get("text") or "")
    if not text.strip():
        return []
    # shortcut: matplotlib's bundled sans, centred by its ink box, stands in for the browser's sans and its em box;
    # match the browser's font metrics if a figure must show the decal exactly as the viewer does
    weight = str(geo.get("fontWeight") or "700")
    bold = weight == "bold" or (weight.isdigit() and int(weight) >= 600)    # the bundled sans has two weights
    path = TextPath((0, 0), text, size=min(float(geo.get("fontSize") or 140), 230.0),
                    prop=FontProperties(family="sans-serif", weight="bold" if bold else "normal"))
    ink = shapely.Polygon()
    for ring in path.to_polygons():
        if len(ring) >= 3:
            ink = ink.symmetric_difference(shapely.make_valid(shapely.Polygon(ring)))
    box = path.get_extents()
    w, h = float(geo.get("width") or 4), float(geo.get("height") or 2)
    centre, scale = ((box.x0 + box.x1) / 2, (box.y0 + box.y1) / 2), (w / 512, h / 256)   # canvas px to the plane
    ink = shapely.transform(ink, lambda c: (c - centre) * scale)
    ink = ink.intersection(shapely.box(-w / 2, -h / 2, w / 2, h / 2))
    rings = [np.asarray(ring.coords)[:-1] for poly in shapely.get_parts(ink) if poly.geom_type == "Polygon"
             for ring in (poly.exterior, *poly.interiors)]
    return [np.column_stack((r, np.zeros(len(r)))) for r in rings if len(r) >= 3]


def hole_grid(geo: dict) -> tuple[np.ndarray, np.ndarray] | None:
    """The holes odHolePlateTexture draws on a box top, local: centres (n, 3) and the two half axes (2, 3). The
    canvas spans the top face, its left edge at -width / 2 and its top edge at -depth / 2."""

    t = geo.get("top_texture") or {}
    if t.get("kind") != "hole_grid":
        return None
    length, wide = max(float(t.get("length") or 1), 0.001), max(float(t.get("width") or 1), 0.001)
    ppu = max(2.0, min(2048 / length, 2048 / wide, 26.0))
    cw, ch = max(32, math.floor(length * ppu + 0.5)), max(32, math.floor(wide * ppu + 0.5))   # Math.round
    pitch = float(t.get("pitch") or 2.54)
    margin = float(t["margin"]) if t.get("margin") is not None else pitch * 0.75
    cols = min(max(math.floor((length - 2 * margin) / pitch) + 1, 0), 320)
    rows = min(max(math.floor((wide - 2 * margin) / pitch) + 1, 0), 320)
    x0, y0 = (length - (cols - 1) * pitch) / 2, (wide - (rows - 1) * pitch) / 2
    r = max((float(t.get("hole_r") or 0) or pitch * 0.125) * ppu, 1.2)                     # px
    width, height, depth = (float(geo.get(k) or 1) for k in ("width", "height", "depth"))
    x = -width / 2 + (x0 + np.arange(cols) * pitch) * ppu / cw * width
    z = -depth / 2 + (y0 + np.arange(rows) * pitch) * ppu / ch * depth
    centres = np.array([(cx, height / 2, cz) for cx in x for cz in z], float).reshape(-1, 3)
    return centres, np.array([(r / cw * width, 0.0, 0.0), (0.0, 0.0, r / ch * depth)])


KINDS = {"box": box, "cylinder": cylinder, "sphere": sphere, "torus": torus, "extruded_polygon": extruded_polygon,
         "lathe_profile": lathe_profile, "tube_path": tube_path, "text_decal": text_decal}
OPEN_KINDS = ("tube_path", "text_decal")


def _closed(geo: dict) -> bool:
    if geo.get("shape") == "lathe_profile":
        return _lathe_closed(_profile(geo))
    return geo.get("shape") not in OPEN_KINDS


def nodes(tree: dict, matrix: np.ndarray) -> Iterator[tuple[dict, np.ndarray]]:
    """Each node of a geometry tree with its world matrix, in preorder."""

    m = matrix @ trs(tree.get("position"), tree.get("rotation"), tree.get("scale"))
    yield tree, m
    for child in tree.get("children") or []:
        yield from nodes(child, m)


def local_faces(geo: dict, part: str) -> list[Face]:
    """The faces of one node in its own frame; none for a group."""

    shape = geo.get("shape")
    if shape == "group":
        return []
    if shape not in KINDS:
        raise Vector3DError(f"{part}: the vector 3D view does not draw the shape {shape!r} yet. "
                            "Use scene.render_3d_image for this scene.")
    return KINDS[shape](geo)


def three_box(faces: list[Face], matrix: np.ndarray) -> Box | None:
    """The three.js Box3.setFromObject box of one mesh: the 8 corners of its local vertex box, moved by its
    matrix. None for a mesh with no faces."""

    if not faces:
        return None
    pts = np.vstack([np.vstack((f.ring, *f.holes)) for f in faces])
    lo, hi = pts.min(axis=0), pts.max(axis=0)
    corners = np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])])
    moved = corners @ matrix[:3, :3].T + matrix[:3, 3]
    return moved.min(axis=0), moved.max(axis=0)


def box_union(boxes) -> Box | None:
    """Box3.union over ``boxes``; None stands for an empty box."""

    boxes = [b for b in boxes if b is not None]
    if not boxes:
        return None
    return np.min([b[0] for b in boxes], axis=0), np.max([b[1] for b in boxes], axis=0)


def tree_box(tree: dict, matrix: np.ndarray, part: str = "") -> Box | None:
    """The Box3.setFromObject box of a whole geometry tree."""

    return box_union(three_box(local_faces(geo, part), m) for geo, m in nodes(tree, matrix))


def lowest_point(tree: dict, matrix: np.ndarray, part: str = "") -> tuple[float, float, float] | None:
    """The lowest corner of a whole geometry tree (y up): where a tilted part rests on its post."""

    best = None
    for geo, m in nodes(tree, matrix):
        for face in local_faces(geo, part):
            pts = _world(face.ring, m)
            low = pts[int(np.argmin(pts[:, 1]))]
            if best is None or low[1] < best[1]:
                best = low
    return None if best is None else (float(best[0]), float(best[1]), float(best[2]))


def _move(face: Face, matrix: np.ndarray, solid: int) -> Face:
    turn, shift = matrix[:3, :3], matrix[:3, 3]
    mirror = np.linalg.det(turn) < 0                 # a mirror turns the winding round

    def place(ring):
        moved = ring @ turn.T + shift
        return moved[::-1] if mirror else moved

    normal = np.linalg.inv(turn).T @ face.normal
    axis = None if face.axis is None else turn @ face.axis
    return Face(place(face.ring), tuple(place(h) for h in face.holes), normal / np.linalg.norm(normal), solid,
                (solid, *face.surface), face.shading, None if axis is None else axis / np.linalg.norm(axis))


def _world(pts, matrix: np.ndarray) -> np.ndarray:
    return np.asarray(pts) @ matrix[:3, :3].T + matrix[:3, 3]


def add_solid(out: SolidSet, faces: list[Face], matrix: np.ndarray, *, part: str, kind: str, look: Look,
              closed: bool = True, chip: bool = False) -> Solid:
    """Add one mesh as the next solid: its local faces moved by ``matrix``."""

    solid = Solid(id=len(out.solids), part=part, kind=kind, look=look, closed=closed, chip=chip)
    out.solids.append(solid)
    out.faces.extend(_move(f, matrix, solid.id) for f in faces)
    return solid


def solids_from_tree(tree: dict, matrix: np.ndarray, *, part: str, chip: bool, catalog: dict,
                     out: SolidSet) -> Box | None:
    """Add the solids of one geometry tree, in preorder; a group adds no solid. A text decal adds a solid with no
    faces and its Decal; a hole_grid top adds its HoleGrid. Returns the tree's Box3."""

    boxes = []
    for geo, m in nodes(tree, matrix):
        faces = local_faces(geo, part)
        if not faces:
            continue
        boxes.append(three_box(faces, m))
        look = look_of(geo.get("material") or {}, catalog)
        holes, texture = hole_grid(geo), geo.get("top_texture") or {}
        if holes is not None and texture.get("side"):
            look = replace(look, color=_hex(texture["side"]))
        if geo["shape"] == "extruded_polygon" and geo.get("edges"):
            seen = geo.get("edge_opacity")
            look = replace(look, edges=_hex(geo["edges"]), edge_opacity=1.0 if seen is None else float(seen))
        if geo["shape"] == "text_decal":
            solid = add_solid(out, [], m, part=part, kind="text_decal", look=look, closed=False, chip=chip)
            out.decals.append(Decal(solid.id, _world(faces[0].ring, m), [_world(r, m) for r in decal_glyphs(geo)],
                                    _hex(geo.get("color") or "#ffffff")))
            continue
        solid = add_solid(out, faces, m, part=part, kind=geo["shape"], look=look, closed=_closed(geo), chip=chip)
        if holes is not None:
            top = replace(look, color=_hex(texture.get("base") or "#9aa3ad"))
            out.hole_grids.append(HoleGrid(solid.id, (solid.id, "py"), top, _world(holes[0], m), holes[1] @ m[:3, :3].T))
    return box_union(boxes)
