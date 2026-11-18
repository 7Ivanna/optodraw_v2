"""Hidden surfaces for the vector 3D renderer: the camera, and the part of each face that shows.

No depth sort. Each pair of faces that overlap on the page is compared on the two depth planes, which are linear on
the page in both projections (in perspective the depth is 1 / distance). Where the planes cross, the overlap is
split along their line. Shapely cuts the hidden parts away, in final page mm."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from functools import cached_property
from typing import Callable

import numpy as np
import shapely
from shapely import STRtree

from optodraw.renderers.threejs_renderer import _THREEJS_CAMERA_DIRECTIONS
from optodraw.renderers.vector3d_solids import Face, Solid, SolidSet, Vector3DError

GRID_MM = 2e-4             # snap on the page: no sliver along a shared edge
MIN_AREA_MM2 = 1e-7        # a smaller overlap hides nothing
CLOSE_MM = 6e-4            # what hides a face grows by this, so two neighbours leave no hairline between them
SLIVER_MM = 3e-3           # a cut piece thinner than this (2 * area / length) goes
DEPTH_TOL = 1e-9           # two depths closer than this times the largest depth are one depth
Y_UP = np.array([0.0, 1.0, 0.0])


@dataclass(frozen=True, eq=False)
class Camera:
    eye: np.ndarray            # world, y up
    target: np.ndarray
    perspective: bool
    up: np.ndarray = field(default_factory=lambda: Y_UP)
    fov_deg: float = 50.0      # the viewer's PerspectiveCamera(50, ...)
    k: float = 1.0             # mm per world unit (parallel), or mm per unit of x over distance (perspective)
    origin: tuple[float, float] = (0.0, 0.0)   # mm on the page, y down

    @cached_property
    def basis(self) -> np.ndarray:
        """Rows right, up and back, by the three.js Matrix4.lookAt rule."""

        back = np.asarray(self.eye, float) - np.asarray(self.target, float)
        if not back.any():
            back = np.array([0.0, 0.0, 1.0])
        back = back / np.linalg.norm(back)
        up = np.asarray(self.up, float)
        right = np.cross(up, back)
        if not right.any():
            back = back + (np.array([1e-4, 0, 0]) if abs(up[2]) == 1 else np.array([0, 0, 1e-4]))
            back = back / np.linalg.norm(back)
            right = np.cross(up, back)
        right = right / np.linalg.norm(right)
        return np.array([right, np.cross(back, right), back])

    def _view(self, pts) -> np.ndarray:
        return (np.atleast_2d(np.asarray(pts, float)) - self.eye) @ self.basis.T

    def page(self, pts) -> np.ndarray:
        """(n, 2) mm on the page, y down."""

        v = self._view(pts)
        scale = self.k / -v[:, 2] if self.perspective else self.k
        return np.column_stack((v[:, 0] * scale, -v[:, 1] * scale)) + self.origin

    def depth(self, pts) -> np.ndarray:
        """Larger is nearer: minus the distance along the view (parallel), 1 / that distance (perspective)."""

        z = self._view(pts)[:, 2]
        return -1.0 / z if self.perspective else z

    def distance(self, depth) -> np.ndarray:
        """The distance along the view of a depth."""

        depth = np.asarray(depth, float)
        return 1.0 / depth if self.perspective else -depth

    def facing(self, face: Face) -> bool:
        view = self.eye - face.ring[0] if self.perspective else self.basis[2]
        return float(face.normal @ view) > 1e-9 * float(np.linalg.norm(view))


def _direction(direction) -> np.ndarray:
    if isinstance(direction, str):
        name = direction.strip().lower().replace("-", "_")
        if name not in _THREEJS_CAMERA_DIRECTIONS:
            raise ValueError(f"direction must be one of: {', '.join(_THREEJS_CAMERA_DIRECTIONS)}, or (x, y, z)")
        d = np.array(_THREEJS_CAMERA_DIRECTIONS[name], float)
    else:
        x, y, z = (float(v) for v in direction)
        d = np.array([x, z, -y])                 # z up, toward the camera, as render_3d_image(camera=...)
    if not np.isfinite(d).all() or not d.any():
        raise ValueError("direction must be three finite numbers, not all zero")
    return d / np.linalg.norm(d)


def camera_for(solids: SolidSet, direction, projection: str, width_mm: float, *, camera: str | None = None,
               also: np.ndarray | None = None, margin_mm: float = 1.0) -> tuple[Camera, float]:
    """A camera that fits the solids, and the world points ``also``, into ``width_mm``, and the page height. The
    target is the centre of the content box; the eye stands 2.2 box diagonals away along ``direction``.
    ``camera="home"`` takes the viewer's framed pose (``home_pose``) in place of that eye and target."""

    if projection not in ("parallel", "perspective"):
        raise ValueError("projection must be 'parallel' or 'perspective'")
    if camera not in (None, "home"):
        raise ValueError(f"camera is None or 'home', got {camera!r}")
    if not solids.faces:
        raise Vector3DError("the scene has no solids to draw")
    pts = np.vstack([f.ring for f in solids.faces])
    if camera == "home":
        from optodraw.renderers.vector3d_scene import home_pose     # the scene module imports this one

        eye, target = home_pose(solids, direction)
    else:
        lo, hi = pts.min(axis=0), pts.max(axis=0)
        target = (lo + hi) / 2
        eye = target + _direction(direction) * 2.2 * max(float(np.linalg.norm(hi - lo)), 1e-9)
    view = Camera(eye=eye, target=target, perspective=projection == "perspective")
    flat = view.page(pts if also is None else np.vstack((pts, also)))
    (x0, y0), (x1, y1) = flat.min(axis=0), flat.max(axis=0)
    if x1 - x0 <= 0 or width_mm <= 2 * margin_mm:
        raise Vector3DError("the view has no width to draw")
    k = (width_mm - 2 * margin_mm) / (x1 - x0)
    return replace(view, k=k, origin=(margin_mm - x0 * k, margin_mm - y0 * k)), float((y1 - y0) * k + 2 * margin_mm)


@dataclass
class Shown:
    pieces: list[tuple[int, shapely.Geometry]]   # face index, its visible part in mm
    clear: list[tuple[int, shapely.Geometry]]    # clear faces, cut by the solids in front
    planes: np.ndarray                           # (faces, 3): depth = a x + b y + c on the page; NaN when culled
    tree: STRtree                                # over pieces, for covered()
    tol: float                                   # two depths closer than this are one


def _areal(geom) -> shapely.Geometry:
    """Only the area parts: snapping can turn a thin overlap into a line."""

    if geom.geom_type in ("Polygon", "MultiPolygon"):
        return geom
    parts = []
    for part in shapely.get_parts(geom):
        if part.geom_type == "Polygon":
            parts.append(part)
        elif part.geom_type in ("MultiPolygon", "GeometryCollection"):
            parts.extend(shapely.get_parts(_areal(part)))
    return shapely.MultiPolygon([p for p in parts if not p.is_empty])


def _no_slivers(geom) -> shapely.Geometry:
    parts = [p for p in shapely.get_parts(geom) if p.length > 0 and 2 * p.area / p.length > SLIVER_MM]
    return parts[0] if len(parts) == 1 else shapely.MultiPolygon(parts)


def _half(bounds, plane) -> shapely.Polygon:
    """Where a x + b y + c >= 0, inside the bounds grown by 1 mm."""

    x0, y0, x1, y1 = bounds
    corners = [(x0 - 1, y0 - 1), (x1 + 1, y0 - 1), (x1 + 1, y1 + 1), (x0 - 1, y1 + 1)]
    a, b, c = plane
    out = []
    for p, q in zip(corners, corners[1:] + corners[:1]):
        dp, dq = a * p[0] + b * p[1] + c, a * q[0] + b * q[1] + c
        if dp >= 0:
            out.append(p)
        if (dp >= 0) != (dq >= 0):
            t = dp / (dp - dq)
            out.append((p[0] + t * (q[0] - p[0]), p[1] + t * (q[1] - p[1])))
    return shapely.Polygon(out) if len(out) >= 3 else shapely.Polygon()


def visible(faces: list[Face], solids: list[Solid], camera: Camera, *,
            opaque: Callable[[Solid], bool] = lambda s: not s.look.clear) -> Shown:
    """The shown part of each front face. Opaque faces hide; clear faces hide nothing and are cut by the opaque
    faces in front. On one plane the later face wins."""

    solid_opaque = {s.id: bool(opaque(s)) for s in solids}
    front = [i for i, f in enumerate(faces) if camera.facing(f)]
    planes = np.full((len(faces), 3), np.nan)
    found: list[shapely.Geometry] = []
    top = 0.0
    for i in front:
        f = faces[i]
        ring = camera.page(f.ring)
        poly = shapely.Polygon(ring, [camera.page(h) for h in f.holes])
        found.append(poly if poly.is_valid else _areal(shapely.make_valid(poly)))
        depth = camera.depth(f.ring)
        planes[i] = np.linalg.lstsq(np.column_stack((ring, np.ones(len(ring)))), depth, rcond=None)[0]
        top = max(top, float(np.abs(depth).max()))
    tol = DEPTH_TOL * (top or 1.0)
    polys = np.array(found, dtype=object)
    lit = np.array([solid_opaque[faces[i].solid] for i in front], dtype=bool)
    hide: list[list] = [[] for _ in front]
    if len(front) > 1:
        a, b = STRtree(polys).query(polys, predicate="intersects")
        keep = (a < b) & (lit[a] | lit[b])
        a, b = a[keep], b[keep]
        both = shapely.intersection(polys[a], polys[b], grid_size=GRID_MM)
        big = shapely.area(both) > MIN_AREA_MM2
        a, b = a[big], b[big]
        both = np.array([_areal(g) for g in both[big]], dtype=object)
        coords, index = shapely.get_coordinates(both, return_index=True)
        rows = np.array(front)
        gap = planes[rows[a[index]]] - planes[rows[b[index]]]
        diff = gap[:, 0] * coords[:, 0] + gap[:, 1] * coords[:, 1] + gap[:, 2]
        low, high = np.full(len(a), np.inf), np.full(len(a), -np.inf)
        np.minimum.at(low, index, diff)
        np.maximum.at(high, index, diff)

        def over(near: int, far: int, region) -> None:
            if lit[near] and not region.is_empty:
                hide[far].append(region)

        for n in range(len(a)):
            i, j, region = int(a[n]), int(b[n]), both[n]
            if low[n] >= -tol and high[n] > tol:              # i is nearer all over the overlap
                over(i, j, region)
            elif high[n] <= tol:                              # j is nearer, or one plane: the later face wins
                over(j, i, region)
            else:                                             # the planes cross: split along their line
                near = _half(region.bounds, planes[rows[i]] - planes[rows[j]])
                over(i, j, _areal(shapely.intersection(region, near, grid_size=GRID_MM)))
                over(j, i, _areal(shapely.difference(region, near, grid_size=GRID_MM)))
    pieces: list[tuple[int, shapely.Geometry]] = []
    clear: list[tuple[int, shapely.Geometry]] = []
    for n, i in enumerate(front):
        shape = polys[n]
        if hide[n]:
            cover = shapely.union_all(np.array(hide[n], dtype=object), grid_size=GRID_MM)
            cover = shapely.buffer(cover, CLOSE_MM, quad_segs=1, join_style="mitre")
            shape = _no_slivers(_areal(shapely.difference(shape, cover, grid_size=GRID_MM)))
        if not shape.is_empty:
            (pieces if lit[n] else clear).append((i, shape))
    return Shown(pieces, clear, planes, STRtree([g for _, g in pieces]), tol)


def _plane_at(shown: Shown, face: int, xy) -> float:
    a, b, c = shown.planes[face]
    return float(a * xy[0] + b * xy[1] + c)


def covered(shown: Shown, camera: Camera, point, *, tol: float) -> bool:
    """True when a shown opaque face lies nearer than ``point`` by more than ``tol`` world units, along the ray
    through it. A clear face never covers."""

    point = np.asarray(point, float)
    xy = camera.page(point)[0]
    hits = shown.tree.query(shapely.Point(xy), predicate="intersects")
    if not len(hits):
        return False
    face = max((shown.pieces[h][0] for h in hits), key=lambda f: _plane_at(shown, f, xy))
    ahead = camera.distance(camera.depth(point)[0]) - camera.distance(_plane_at(shown, face, xy))
    if camera.perspective:                        # distance along the view to distance along the ray
        ray = camera.eye - point
        ahead *= float(np.linalg.norm(ray) / (ray @ camera.basis[2]))
    return bool(ahead > tol)


def clip_lines(segments: list[np.ndarray], shown: Shown, camera: Camera) -> shapely.MultiLineString:
    """The shown parts of world segments, each (2, 3), in page mm: cut where an opaque piece lies in front. A shown
    part shorter than SLIVER_MM goes."""

    out: list[shapely.LineString] = []
    for segment in segments:
        ends = camera.page(segment)
        run = ends[1] - ends[0]
        size = float(run @ run)
        if size == 0:
            continue
        line = shapely.LineString(ends)
        d0, d1 = camera.depth(segment)
        # hidden spans as parameters along the line: a geometric difference of two near-collinear lines keeps them
        hidden: list[tuple[float, float]] = []
        for h in shown.tree.query(line, predicate="intersects"):
            face, piece = shown.pieces[h]
            a, b, c = shown.planes[face]
            # the face depth minus the line depth, linear in t along the page line from ends[0] to ends[1]
            start = a * ends[0, 0] + b * ends[0, 1] + c - d0
            slope = a * (ends[1, 0] - ends[0, 0]) + b * (ends[1, 1] - ends[0, 1]) - (d1 - d0)
            if abs(slope) < 1e-300:
                t0, t1 = (0.0, 1.0) if start > shown.tol else (1.0, 1.0)
            else:
                t = (shown.tol - start) / slope            # where the face starts to be nearer
                t0, t1 = (max(t, 0.0), 1.0) if slope > 0 else (0.0, min(t, 1.0))
            if t1 <= t0:
                continue
            for part in shapely.get_parts(shapely.intersection(line, piece)):
                t = (np.asarray(part.coords) - ends[0]) @ run / size
                if len(t) and min(t.max(), t1) > max(t.min(), t0):
                    hidden.append((max(t.min(), t0), min(t.max(), t1)))
        cursor, shown_spans = 0.0, []
        for lo, hi in sorted(hidden) + [(1.0, 1.0)]:
            if lo > cursor:
                shown_spans.append((cursor, lo))
            cursor = max(cursor, hi)
        reach = size ** 0.5
        out.extend(shapely.LineString([ends[0] + run * lo, ends[0] + run * hi]) for lo, hi in shown_spans
                   if (hi - lo) * reach > SLIVER_MM)
    return shapely.MultiLineString(out)
