"""A vector 3D view of a scene: the viewer's solids with the hidden parts cut away, as SVG paths. No Chrome.

``style="studio"`` lights each surface in a white studio: one path per surface, a gradient across a surface of
revolution, shade steps on a sphere, a torus or a curved wall, a sweep over a large flat face. Clear faces hide
nothing and paint last, cut by the solids in front. ``style="line"`` gives flat figure colours."""

from __future__ import annotations

import math
from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple

import numpy as np
import shapely

from optodraw.renderers.vector3d_hidden import CLOSE_MM, GRID_MM, Camera, Shown, _areal, camera_for, clip_lines, visible
from optodraw.renderers.vector3d_scene import _board_top, scene_solids
from optodraw.renderers.vector3d_solids import Band, Decal, Face, Look, Solid, SolidSet, Vector3DError, figure_color

__all__ = ["FACE_LIMIT", "Vector3DError", "draw", "draw_ids", "render_3d_svg"]

# The scale guard: the most front faces (after culling) a view draws, so a view takes about 60 s at most. Measured
# 2026-11-06 on an Apple M2 (8 cores, 16 GB): View3D.chip(..., "gdsfactory_generic", z_scale=4).fragment(120) on 1,
# 3 (3 by 1) and 10 (5 by 2) copies of tests/fixtures/spike_ring.gds, 3 runs each, interleaved, one process at a
# time. The machine was not idle (load 3.7 to 6.8, a video call), so these times are high. Medians: 4,345 faces
# 5.8 s (spread 8 %), 12,943 faces 15.4 s (14 %), 43,042 faces 52.6 s (4 %); peak RSS 286, 385 and 718 MB. The fit
# t = 0.00172 n^0.966 s gives 60 s at 50,432 faces; memory grows as n^0.40 and stays far under 4 GB. Faces predict
# the time better than overlapping pairs (rms log residual 0.033 against 0.053). At 10 copies the hidden step is
# 67 % of the time, the merge 24 % (the shadows 12 %), the solids 6 %. In the hidden step GEOS limits, not the
# Python pair loop: at 3 copies intersection takes 3.3 s and union_all 2.5 s of 10.0 s (cProfile).
FACE_LIMIT = 50_000

STYLES = ("studio", "line")
SIMPLIFY_MM = 0.004
SEAM_MM = 0.04             # each fill also strokes in its own colour, so neighbours leave no hairline
LINE_MM = 0.03
INK = 0.52                 # an outline is the fill colour times this
INK_OPACITY = 0.55

# The studio, tuned by eye in the Part B spike against render_3d_image(engine="studio"). World y is up.
KEY = np.array((-0.42, 0.86, 0.30)) / np.linalg.norm((-0.42, 0.86, 0.30))   # the soft box
RIM = np.array((0.80, 0.30, -0.52)) / np.linalg.norm((0.80, 0.30, -0.52))    # the rim strip
KEY_REACH = 1.6            # the key stands this many content sizes from the centre, so a large face falls off
PARALLEL_EYE = 2.5         # a parallel view takes its light from an eye this many content sizes away
TINT = np.array((0.97, 0.985, 1.0))   # the studio white
F0 = 0.09                  # the sheen of paint and anodising: a little over a bare dielectric
KNEE = 0.8                 # light over this rolls off, so a highlight keeps its colour
LEVELS, STEP = 14, 1 / 48  # shade steps on a sphere, a torus or a curved extrusion wall
AXIS_STOPS = 28            # the most stops in the gradient across a surface of revolution
SWEEP_MM2 = 2.0            # a flat face over this area falls off across the page,
SWEEP_MIN = 0.012          # when its two ends differ by more than this,
SWEEP = np.array((0.82, 0.57)) / np.linalg.norm((0.82, 0.57))   # along this page direction
GLASS_EDGE = 0.7           # the opacity of the edge of a clear surface
BAND = ((0.0, 0.0), (0.22, 0.08), (0.38, 0.3), (0.47, 0.8), (0.5, 1.0), (0.53, 0.8), (0.62, 0.3), (0.78, 0.08),
        (1.0, 0.0))        # a beam's glow across its band: offset and share of BAND_OPACITY
BAND_OPACITY = 0.5
CORE_LINE = 0.35           # a beam's white centre line, as a share of the core's page width
CORE_WHITE = 0.85          # its opacity
CORE_LIFT = 1.02           # it rides this many core radii toward the eye, so its own core does not hide it
EDGE_DEG = 1.0             # EdgesGeometry(geo, 1): a feature edge turns by more than this
HOLE_SIDES = 16            # a hole that the edge of its plate's shown top cuts


class ShadowBand(NamedTuple):
    """One band of a shadow: the opaque faces whose top stands between ``low`` and ``high`` world units over the
    plane, cast along ``light`` (toward the light, y up), in ``layers`` stacked clear shapes of ``alpha``, each grown
    by a share of ``reach_mm`` on a 120 mm page."""

    low: float
    high: float
    reach_mm: float
    alpha: float
    layers: int
    light: tuple[float, float, float] = tuple(KEY)


DOWN = (0.0, 1.0, 0.0)
# From the Part B spike: a contact shadow straight down, then softer ones along the key; a chip's heights carry its
# z scale (the spike drew it 4 times true)
BENCH_SHADOW = (ShadowBand(0.0, 9.0, 0.9, 0.07, 5, DOWN), ShadowBand(0.0, 9.0, 1.8, 0.05, 5),
                ShadowBand(9.0, math.inf, 3.5, 0.035, 6))
CHIP_SHADOW = (ShadowBand(0.0, 3.0, 0.28, 0.10, 3, DOWN), ShadowBand(1.5, 30.0, 0.7, 0.06, 5))
SHADOW_INK = "#0d1a26"
SHADOW_PAGE_MM = 120.0     # the reaches hold on a drawing this wide and scale with its width
SHADOW_SIMPLIFY_MM = 0.01
UP = 1 - 1e-6              # a face whose normal has this much y faces straight up


def _rgb(color: str) -> np.ndarray:
    c = color.lstrip("#")
    return np.array([int(c[i:i + 2], 16) for i in (0, 2, 4)], float) / 255.0


def _hex(rgb) -> str:
    return "#" + "".join(f"{int(round(min(max(v, 0.0), 1.0) * 255)):02x}" for v in rgb)


def _unit(v) -> np.ndarray:
    v = np.asarray(v, float)
    size = float(np.linalg.norm(v))
    return v / size if size > 0 else v


def _smooth(x: float, a: float, b: float) -> float:
    t = min(max((x - a) / (b - a), 0.0), 1.0)
    return t * t * (3 - 2 * t)


def env(direction: np.ndarray, roughness: float) -> np.ndarray:
    """The studio seen along ``direction``: a soft dome, a bright floor, a dark band at the horizon, the soft box,
    the rim strip, and dark cards round the set that give a metal cylinder its streaks. Roughness widens every edge,
    as it blurs a reflection."""

    y = float(direction[1])
    edge = 0.05 + roughness * 0.9
    dome = 0.50 + 0.30 * _smooth(y, 0.0, 0.9)
    floor = 0.86 - 0.16 * _smooth(-y, 0.05, 0.9)
    tone = floor + (dome - floor) * _smooth(y, -edge, edge)
    tone *= 1.0 - 0.62 * (1 - _smooth(abs(y), 0.02, 0.10 + edge))
    cards = 0.5 + 0.5 * math.cos(3.0 * math.atan2(float(direction[2]), float(direction[0])) + 0.7)
    tone *= 1.0 - (1 - roughness) ** 2 * 0.55 * cards
    gloss = 1 - roughness * 0.7
    tone += 1.4 * gloss * _smooth(float(direction @ KEY), 0.86 - edge * 0.8, 0.97)
    tone += 0.55 * gloss * _smooth(float(direction @ RIM), 0.90 - edge * 0.8, 0.985)
    return tone * TINT


class Studio:
    """The light of one view. The key stands at a finite distance, so a large flat face falls off as in a photograph."""

    def __init__(self, faces: list[Face], camera: Camera):
        pts = np.vstack([f.ring for f in faces]) if faces else np.zeros((1, 3))
        lo, hi = pts.min(axis=0), pts.max(axis=0)
        centre, size = (lo + hi) / 2, float(np.linalg.norm(hi - lo)) or 1.0
        self.key = centre + KEY * size * KEY_REACH
        self.eye = np.asarray(camera.eye, float) if camera.perspective else centre + camera.basis[2] * size * PARALLEL_EYE

    def shade(self, look: Look, base: np.ndarray, normal: np.ndarray, point: np.ndarray) -> np.ndarray:
        """The colour at a surface point: diffuse light from the dome and the key, the studio mirrored with Fresnel,
        the backdrop through a clear material and a clear coat. An unlit material keeps its colour."""

        if look.unlit:
            return base
        view = _unit(self.eye - point)
        facing = max(float(normal @ view), 0.02)
        mirror = 2 * facing * normal - view
        irradiance = 0.42 + 0.28 * (normal[1] * 0.5 + 0.5) + 0.42 * max(float(normal @ _unit(self.key - point)), 0.0)
        f0 = F0 + (base - F0) * look.metalness
        fresnel = f0 + (1 - f0) * (1 - facing) ** 5 * (1 - look.roughness)
        through = look.transmission
        rgb = (base * (1 - look.metalness) * (1 - through) * irradiance + through * base * env(-view, look.roughness)
               + fresnel * env(mirror, look.roughness))
        if look.clearcoat:
            rgb = rgb + look.clearcoat * (0.04 + 0.96 * (1 - facing) ** 5) * env(mirror, 0.05)
        return np.where(rgb < KNEE, rgb, KNEE + (1 - KNEE) * (1 - np.exp(-(rgb - KNEE) / (1 - KNEE))))


def _rings(geom, close: bool) -> str:
    out = []
    for poly in shapely.get_parts(geom):
        if poly.geom_type != "Polygon" or poly.is_empty:
            continue
        for ring in (poly.exterior, *poly.interiors):
            pts = np.round(np.asarray(ring.coords)[:-1] if close else np.asarray(ring.coords), 3)
            out.append("M" + "L".join(f"{x:g} {y:g}" for x, y in pts) + ("Z" if close else ""))
    return "".join(out)


def _polylines(lines) -> str:
    return "".join("M" + "L".join(f"{x:g} {y:g}" for x, y in np.round(np.asarray(line.coords), 3))
                   for line in shapely.get_parts(lines) if line.geom_type == "LineString" and not line.is_empty)


def _merged(parts: list) -> shapely.Geometry:
    geom = shapely.union_all(np.array(parts, dtype=object), grid_size=GRID_MM)
    return geom.simplify(SIMPLIFY_MM, preserve_topology=True)


def _plane(face: Face) -> tuple:
    return (*np.round(face.normal, 6), round(float(face.normal @ face.ring[0]), 6))


def _body_key(face: Face, solid: Solid) -> tuple | None:
    """The key that merges a flat wall of a part's clear extrusion with the walls of its other extrusions in one look
    and one plane: a clear body built in bands (a chip's cladding) shows each wall as one surface. None otherwise."""

    if solid.kind == "extruded_polygon" and solid.look.clear and face.shading == "flat" \
            and face.surface[1:2] == ("wall",):
        return (solid.part, solid.look, solid.chip, "wall", *_plane(face))
    return None


def _inside(faces: list[Face], solids: list[Solid], camera: Camera) -> dict[int, shapely.Geometry]:
    """The page area of each front face of a part's clear extrusion that lies on a back face of another of its
    extrusions in the same look, turned the other way: there two bands of one clear body touch, and neither face
    shows. A clear body built in bands then draws no seam."""

    groups: dict[tuple, list[int]] = {}
    for i, face in enumerate(faces):
        solid = solids[face.solid]
        if solid.kind == "extruded_polygon" and solid.look.clear:
            groups.setdefault((solid.part, solid.look, _plane(face)), []).append(i)
    out: dict[int, shapely.Geometry] = {}
    for (part, look, plane), members in groups.items():
        backs = [faces[j] for j in groups.get((part, look, tuple(-v for v in plane)), []) if not camera.facing(faces[j])]
        front = [i for i in members if camera.facing(faces[i])]
        if backs and front:            # an extrusion is never 0 thick, so a back face here is another band's
            cut = shapely.union_all([shapely.make_valid(shapely.Polygon(camera.page(f.ring),
                                                                        [camera.page(h) for h in f.holes]))
                                     for f in backs])
            cut = shapely.buffer(cut, CLOSE_MM, join_style="mitre")
            out.update(dict.fromkeys(front, cut))
    return out


def _outside(pieces, inside: dict[int, shapely.Geometry]) -> list[tuple[int, shapely.Geometry]]:
    """The clear ``pieces`` less what lies inside a clear body (``_inside``)."""

    out = []
    for i, geom in pieces:
        if i in inside:
            geom = _areal(shapely.difference(geom, inside[i], grid_size=GRID_MM))
        if not geom.is_empty:
            out.append((i, geom))
    return out


def _step(rgb: np.ndarray) -> tuple:
    """A shade step: the brightness to one of LEVELS, then each channel to STEP."""

    top = float(rgb.max())
    if top > 0:
        rgb = rgb * (round(top * LEVELS) / LEVELS) / top
    return tuple(np.round(rgb / STEP) * STEP)


def _hides(solid: Solid) -> bool:
    """In the studio an unlit beam core hides what lies behind it at any opacity; a decal and a glow hide nothing."""

    return solid.kind not in ("text_decal", "band") and (solid.look.unlit or not solid.look.clear)


def _mm_per_unit(camera: Camera, point) -> float:
    return camera.k / float(camera.distance(camera.depth(point))[0]) if camera.perspective else camera.k


def _toward_eye(camera: Camera, point: np.ndarray) -> np.ndarray:
    return _unit(camera.eye - point) if camera.perspective else camera.basis[2]


def _band_face(band: Band, camera: Camera, solid: int) -> Face | None:
    """The band as one flat quad that faces the camera at its middle; None when the beam runs at the eye."""

    run = band.end - band.start
    side = np.cross(run, _toward_eye(camera, (band.start + band.end) / 2))
    if np.linalg.norm(side) <= 1e-12 * max(float(np.linalg.norm(run)), 1.0) ** 2:
        return None
    side = _unit(side)
    normal = _unit(np.cross(side, run))
    w0, w1 = band.widths[0] / 2, band.widths[1] / 2
    ring = np.array([band.start - side * w0, band.end - side * w1, band.end + side * w1, band.start + side * w0])
    if np.cross(ring[1] - ring[0], ring[2] - ring[0]) @ normal < 0:
        ring = ring[::-1]
    return Face(ring, (), normal, solid, ("band", solid), "flat")


def _decal_face(decal: Decal, camera: Camera) -> Face:
    """The decal's plane, turned to face the camera: from behind its text shows mirrored, as in the viewer."""

    ring = decal.plane
    normal = _unit(np.cross(ring[1] - ring[0], ring[2] - ring[0]))
    face = Face(ring, (), normal, decal.solid, ("decal", decal.solid), "flat")
    return face if camera.facing(face) else Face(ring[::-1], (), -normal, decal.solid, face.surface, "flat")


def _feature_edges(faces: list[Face]) -> list[np.ndarray]:
    """EdgesGeometry(geo, 1) of one solid: each edge that bounds one face, or where two faces turn by over EDGE_DEG."""

    found: dict[tuple, list] = {}
    for f in faces:
        for ring in (f.ring, *f.holes):
            for a, b in zip(ring, np.roll(ring, -1, axis=0)):
                ends = tuple(sorted((tuple(np.round(a, 6)), tuple(np.round(b, 6)))))
                found.setdefault(ends, [a, b, []])[2].append(f.normal)
    limit = math.cos(math.radians(EDGE_DEG))
    return [np.array([a, b]) for a, b, normals in found.values()
            if len(normals) != 2 or float(normals[0] @ normals[1]) < limit]


def _ellipse(centre: np.ndarray, u: np.ndarray, v: np.ndarray) -> str:
    """The ellipse centre + u cos t + v sin t as two SVG arcs."""

    turn, size, _ = np.linalg.svd(np.column_stack((u, v)))
    a, b, axis = float(size[0]), float(size[1]), turn[:, 0]
    angle = math.degrees(math.atan2(axis[1], axis[0]))
    p, q = np.round(centre + a * axis, 3), np.round(centre - a * axis, 3)
    arc = f"A{a:.3f} {b:.3f} {angle:.2f} 0 0"
    return f"M{p[0]:g} {p[1]:g}{arc} {q[0]:g} {q[1]:g}{arc} {p[0]:g} {p[1]:g}Z"


def _bench(k) -> bool:
    """A bench casts its shadows on the floor; a chip alone on its page, on the top of its lower cladding."""

    return k.mixed or not k.on_chip


def _dropped(solids: SolidSet, plane: float, band: ShadowBand):
    """The rings (outline, then holes) of each opaque face of the band, cast along its light onto the plane
    y = ``plane``, in world units."""

    light = _unit(band.light)
    for f in solids.faces:
        if solids.solids[f.solid].look.clear:
            continue
        rise = f.ring[:, 1] - plane
        if rise.min() < -1e-6 or rise.max() > band.high or rise.max() <= band.low:
            continue
        yield [ring - ((ring[:, 1] - plane) / light[1])[:, None] * light for ring in (f.ring, *f.holes)]


class _Studio:
    """One studio drawing: the faces with the glow bands and decal planes added, and the gradients so far."""

    def __init__(self, solids: SolidSet, camera: Camera):
        self.given, self.camera = solids, camera
        self.faces, self.solids = list(solids.faces), list(solids.solids)
        self.extra: dict[int, Band | Decal] = {}            # face index: what an added face draws
        for band in solids.bands:
            face = _band_face(band, camera, len(self.solids))
            if face is not None:
                self.solids.append(Solid(len(self.solids), band.part, "band", Look(band.color, opacity=BAND_OPACITY),
                                         closed=False, chip=False))
                self.extra[len(self.faces)] = band
                self.faces.append(face)
        for decal in solids.decals:
            if decal.rings:
                self.extra[len(self.faces)] = decal
                self.faces.append(_decal_face(decal, camera))
        self.light = Studio(solids.faces, camera)
        self.tops = {grid.surface: grid for grid in solids.hole_grids}
        self.defs: list[str] = []

    def gradient(self, p0, p1, stops, opacity: Callable[[float], float] | None = None) -> str:
        """A linear gradient from page point p0 to p1, ids from 1 in the order they are made."""

        name = f"g{len(self.defs) + 1}"
        rows = "".join(f'<stop offset="{t:.3f}" stop-color="{c if isinstance(c, str) else _hex(c)}"'
                       + (f' stop-opacity="{opacity(t):.3f}"' if opacity else "") + "/>" for t, c in stops)
        self.defs.append(f'<linearGradient id="{name}" gradientUnits="userSpaceOnUse" x1="{p0[0]:.3f}" '
                         f'y1="{p0[1]:.3f}" x2="{p1[0]:.3f}" y2="{p1[1]:.3f}">{rows}</linearGradient>')
        return f"url(#{name})"

    def key(self, i: int) -> tuple:
        """The merge key of a face. The tops and bottoms of one item's extrusions in one plane and one material share
        a key, so a chip's cells merge with no seam; so do the flat walls of a clear body built in bands."""

        face = self.faces[i]
        solid = self.solids[face.solid]
        if solid.kind == "extruded_polygon" and face.surface[1:] in (("top",), ("bottom",)):
            return (solid.part, solid.look, solid.chip, face.surface[1], *np.round(face.normal, 6),
                    round(float(face.normal @ face.ring[0]), 6))
        return _body_key(face, solid) or face.surface

    def surfaces(self, pieces) -> list[list[tuple[int, shapely.Geometry]]]:
        """The pieces of each merged surface, far first; the first face index breaks a tie."""

        groups: dict[tuple, list] = {}
        for i, geom in pieces:
            groups.setdefault(self.key(i), []).append((i, geom))

        def order(members) -> tuple[float, int]:
            return float(np.mean([self.camera.depth(self.faces[i].ring).mean() for i, _ in members])), members[0][0]

        return sorted(groups.values(), key=order)

    def look(self, i: int) -> tuple[Look, np.ndarray]:
        """The material and the base colour of a face: a hole plate's top takes its texture's base colour."""

        face = self.faces[i]
        grid = self.tops.get(face.surface)
        if grid is not None:
            return grid.top, _rgb(grid.top.color)
        solid = self.solids[face.solid]
        return solid.look, _rgb(figure_color(solid))

    def shade(self, i: int, look: Look, base: np.ndarray, point=None) -> np.ndarray:
        face = self.faces[i]
        return self.light.shade(look, base, face.normal, face.ring.mean(axis=0) if point is None else point)

    def paths(self, members, look: Look, base: np.ndarray, clear: bool = False) -> list[tuple[shapely.Geometry, str]]:
        """The filled paths of one surface: a step per shade, or one path with its colour or gradient. A clear
        stepped surface takes one tint, the mean shade: through the glass its steps would show as patches."""

        shading = self.faces[members[0][0]].shading
        if shading == "steps" and not clear:
            steps: dict[tuple, list] = {}
            for i, geom in members:
                steps.setdefault(_step(self.shade(i, look, base)), []).append(geom)
            out = [(_merged(parts), _hex(rgb)) for rgb, parts in steps.items()]
            return [(geom, fill) for geom, fill in out if not geom.is_empty]
        geom = _merged([g for _, g in members])
        if geom.is_empty:
            return []
        if shading == "axis":
            return [(geom, self.across_axis(members, look, base))]
        if shading == "steps":
            return [(geom, _hex(np.mean([self.shade(i, look, base) for i, _ in members], axis=0)))]
        return [(geom, self.sweep(members, look, base, geom.area))]

    def across_axis(self, members, look: Look, base: np.ndarray) -> str:
        """One gradient across the axis of a surface of revolution, at most AXIS_STOPS stops from the facet centres."""

        centres = np.array([self.faces[i].ring.mean(axis=0) for i, _ in members])
        colours = np.array([self.shade(i, look, base, c) for (i, _), c in zip(members, centres)])
        axis = self.faces[members[0][0]].axis
        middle = centres.mean(axis=0)
        reach = float(np.ptp(np.vstack([self.faces[i].ring for i, _ in members]), axis=0).max()) or 1.0
        ends = self.camera.page(np.array([middle - axis * reach, middle + axis * reach]))
        across = _unit((ends[0, 1] - ends[1, 1], ends[1, 0] - ends[0, 0]))
        if not across.any():
            across = np.array((1.0, 0.0))                  # the axis points at the eye
        t = self.camera.page(centres) @ across
        lo, hi = float(t.min()), float(t.max())
        if hi - lo < 1e-6 or float(np.ptp(colours, axis=0).max()) < 0.5 / 255:
            return _hex(colours.mean(axis=0))
        bins = np.minimum(((t - lo) / (hi - lo) * AXIS_STOPS).astype(int), AXIS_STOPS - 1)
        stops = [((float(t[bins == b].mean()) - lo) / (hi - lo), colours[bins == b].mean(axis=0))
                 for b in np.unique(bins)]
        return self.gradient(across * lo, across * hi, stops)

    def sweep(self, members, look: Look, base: np.ndarray, area: float) -> str:
        """A flat surface's colour; over SWEEP_MM2, three stops along SWEEP where the positional key falls off."""

        first = members[0][0]
        pts = np.vstack([self.faces[i].ring for i, _ in members])
        centre = self.shade(first, look, base, pts.mean(axis=0))
        if area <= SWEEP_MM2:
            return _hex(centre)
        t = self.camera.page(pts) @ SWEEP
        near, far = pts[int(t.argmin())], pts[int(t.argmax())]
        a, b = self.shade(first, look, base, near), self.shade(first, look, base, far)
        if float(np.abs(a - b).max()) <= SWEEP_MIN:
            return _hex(centre)
        mid = self.shade(first, look, base, (near + far) / 2)
        return self.gradient(SWEEP * t.min(), SWEEP * t.max(), [(0.0, a), (0.5, mid), (1.0, b)])

    def opaque(self, pieces) -> tuple[list[str], list[str]]:
        fills, lines = [], []
        for members in self.surfaces(pieces):
            look, base = self.look(members[0][0])
            for geom, fill in self.paths(members, look, base):
                if d := _rings(geom, True):
                    fills.append(f'<path d="{d}" fill="{fill}" fill-rule="evenodd" stroke="{fill}" '
                                 f'stroke-width="{SEAM_MM:g}"/>')
            outline = _rings(_merged([g for _, g in members]), False)
            if outline:
                lines.append(f'<path d="{outline}" stroke="{_hex(base * INK)}"/>')
        return fills, lines

    def clear(self, pieces) -> list[tuple[float, int, str]]:
        """Each clear surface with its depth: its fills at the material's opacity, and its edge."""

        out = []
        for members in self.surfaces(pieces):
            first = members[0][0]
            look, base = self.look(first)
            opacity = min(look.opacity, 0.5) if look.transmission > 0 else look.opacity
            body = [f'<path d="{d}" fill="{fill}" fill-opacity="{opacity:g}" fill-rule="evenodd"/>'
                    for geom, fill in self.paths(members, look, base, clear=True) if (d := _rings(geom, True))]
            edge = _rings(_merged([g for _, g in members]), False)
            if edge:
                body.append(f'<path d="{edge}" fill="none" stroke="{_hex(base * INK)}" stroke-width="{LINE_MM:g}" '
                            f'stroke-opacity="{GLASS_EDGE:g}"/>')
            out.append((self.depth(members), first, "".join(body)))
        return out

    def depth(self, members) -> float:
        return float(np.mean([self.camera.depth(self.faces[i].ring).mean() for i, _ in members]))

    def band(self, i: int, band: Band, parts: list) -> tuple[float, int, str] | None:
        """The glow: the band's shown part, filled with a gradient in opacity across it."""

        geom = _merged(parts)
        ends = self.camera.page(np.array([band.start, band.end]))
        along = _unit(ends[1] - ends[0])
        if geom.is_empty or not along.any():
            return None
        across = np.array((-along[1], along[0]))
        half = (band.widths[0] * _mm_per_unit(self.camera, band.start)
                + band.widths[1] * _mm_per_unit(self.camera, band.end)) / 4
        middle = ends.mean(axis=0)
        fill = self.gradient(middle - across * half, middle + across * half, [(t, band.color) for t, _ in BAND],
                             opacity=lambda t: BAND_OPACITY * dict(BAND)[t])
        return self.depth([(i, geom)]), i, f'<path d="{_rings(geom, True)}" fill="{fill}" fill-rule="evenodd"/>'

    def glyphs(self, decal: Decal, parts: list) -> str:
        """The text of a decal: its glyphs on the page, cut to the shown part of its plane."""

        ink = shapely.Polygon()
        for ring in decal.rings:
            glyph = shapely.Polygon(self.camera.page(ring))
            ink = ink.symmetric_difference(glyph if glyph.is_valid else shapely.make_valid(glyph))
        geom = shapely.intersection(ink, shapely.union_all(np.array(parts, dtype=object)), grid_size=GRID_MM)
        d = _rings(geom, True)
        return f'<path d="{d}" fill="{decal.color}" fill-rule="evenodd"/>' if d else ""

    def holes(self, shown: Shown) -> list[str]:
        """Each plate's holes as one path of dark ellipses, cut to the shown part of its top."""

        out = []
        for grid in self.given.hole_grids:
            parts = [g for i, g in shown.pieces if self.faces[i].surface == grid.surface]
            if not parts or not len(grid.centres):
                continue
            top = shapely.union_all(np.array(parts, dtype=object), grid_size=GRID_MM)
            centre = self.camera.page(grid.centres)
            u = self.camera.page(grid.centres + grid.axes[0]) - centre
            v = self.camera.page(grid.centres + grid.axes[1]) - centre
            t = 2 * math.pi * np.arange(HOLE_SIDES) / HOLE_SIDES
            rings = centre[:, None] + u[:, None] * np.cos(t)[None, :, None] + v[:, None] * np.sin(t)[None, :, None]
            polys = shapely.polygons(rings)
            shapely.prepare(top)
            inside = shapely.contains(top, polys)
            cut = ~inside & shapely.intersects(top, polys)
            d = [_ellipse(centre[k], u[k], v[k]) for k in np.flatnonzero(inside)]
            if cut.any():
                d.append(_rings(shapely.intersection(shapely.union_all(polys[cut]), top, grid_size=GRID_MM), True))
            if any(d):
                out.append(f'<path d="{"".join(d)}" fill="{grid.color}"/>')
        return out

    def centre_lines(self, shown: Shown) -> list[str]:
        """The white centre of each beam core, lifted toward the eye over its core, cut where a solid lies in front."""

        caps: dict[int, list[Face]] = {}
        for f in self.given.faces:
            if self.solids[f.solid].kind == "beam" and f.surface[1:] in (("top",), ("bottom",)):
                caps.setdefault(f.solid, []).append(f)
        out = []
        for ends in caps.values():
            if len(ends) != 2:
                continue
            centres = [f.ring.mean(axis=0) for f in ends]
            radius = float(np.linalg.norm(ends[0].ring[0] - centres[0]))
            along = _unit(centres[1] - centres[0])
            lifted = []
            for c in centres:
                # along the ray, so the line keeps the axis's page position; a slant ray meets the core at r / sin
                ray = _toward_eye(self.camera, c)
                sine = max(float(np.linalg.norm(np.cross(ray, along))), 0.05)
                lifted.append(c + ray * radius * CORE_LIFT / sine)
            lifted = np.array(lifted)
            d = _polylines(clip_lines([lifted], shown, self.camera))
            width = CORE_LINE * radius * (_mm_per_unit(self.camera, centres[0]) + _mm_per_unit(self.camera, centres[1]))
            if d:
                out.append(f'<path d="{d}" fill="none" stroke="#ffffff" stroke-opacity="{CORE_WHITE:g}" '
                           f'stroke-width="{width:.4f}"/>')
        return out

    def edges(self, shown: Shown) -> list[str]:
        """The feature edges of each clear solid with an outline colour, front and back, cut by the solids in front."""

        out = []
        for solid in self.given.solids:
            if solid.look.edges is None or _hides(solid):
                continue
            segments = _feature_edges([f for f in self.given.faces if f.solid == solid.id])
            d = _polylines(clip_lines(segments, shown, self.camera))
            if d:
                out.append(f'<path d="{d}" fill="none" stroke="{solid.look.edges}" stroke-width="{LINE_MM:g}" '
                           f'stroke-opacity="{solid.look.edge_opacity:g}"/>')
        return out

    def cast(self, plane: float, band: ShadowBand) -> shapely.Geometry | None:
        """The page footprint of the band's faces, cast onto the plane y = ``plane``."""

        shapes = []
        for ring, *holes in _dropped(self.given, plane, band):
            poly = shapely.Polygon(self.camera.page(ring), [self.camera.page(h) for h in holes])
            poly = poly if poly.is_valid else _areal(shapely.make_valid(poly))
            if poly.area > 1e-8:
                shapes.append(poly)
        return shapely.union_all(np.array(shapes, dtype=object), grid_size=GRID_MM) if shapes else None

    def shadows(self, shown: Shown) -> tuple[list[str], list[str]]:
        """Soft shadows on one plane, as stacked clear shapes: they stay vector, where a blur filter turns to pixels
        in a PDF. A bench casts on its floor (BOARD_TOP), which runs under everything, so those paint under the
        fills; a chip casts on the shown floor it shows most of, the top of its lower cladding, so those paint over
        the fills, cut to that floor. A shadow on a bench's board top paints over it the same way. Stated limit: a
        part casts no shadow onto another part."""

        k = self.given.constants
        bench = _bench(k)
        levels: dict[float, list] = {}
        for i, geom in shown.pieces:
            f = self.faces[i]
            if f.normal[1] > UP:
                levels.setdefault(round(float(f.ring[:, 1].mean()), 6), []).append(geom)
        if bench:
            plane = _board_top(k)
        elif levels:
            plane = max(levels, key=lambda y: sum(g.area for g in levels[y]))
        else:
            return [], []
        floor = [g for y, parts in levels.items() if abs(y - plane) <= 1e-6 for g in parts]
        receiver = shapely.union_all(np.array(floor, dtype=object), grid_size=GRID_MM) if floor else None
        pts = self.camera.page(np.vstack([f.ring for f in self.given.faces]))
        scale = float(np.ptp(pts[:, 0])) / SHADOW_PAGE_MM
        under, over = [], []
        for band in BENCH_SHADOW if bench else CHIP_SHADOW:
            cast = self.cast(plane, band)
            if cast is None:
                continue
            for layer in range(band.layers):
                grown = shapely.buffer(cast, band.reach_mm * scale * (1 - layer / band.layers), quad_segs=3)
                paint = f'fill="{SHADOW_INK}" fill-opacity="{band.alpha:g}" fill-rule="evenodd"'
                if bench and (d := _rings(grown.simplify(SHADOW_SIMPLIFY_MM, preserve_topology=True), True)):
                    under.append(f'<path d="{d}" {paint}/>')
                if receiver is not None:
                    on = _areal(shapely.intersection(grown, receiver, grid_size=GRID_MM))
                    if d := _rings(on.simplify(SHADOW_SIMPLIFY_MM, preserve_topology=True), True):
                        over.append(f'<path d="{d}" {paint}/>')
        return under, over

    def draw(self, shadows: bool = True) -> tuple[str, Shown]:
        shown = visible(self.faces, self.solids, self.camera, opaque=_hides)
        under, over = self.shadows(shown) if shadows else ([], [])
        fills, lines = self.opaque(shown.pieces)
        fills = under + fills + over
        marks = self.holes(shown) + self.centre_lines(shown)
        own = len(self.given.faces)
        added: dict[int, list] = {}
        for i, geom in shown.clear:
            if i >= own:
                added.setdefault(i, []).append(geom)
        marks += [self.glyphs(self.extra[i], parts) for i, parts in added.items() if isinstance(self.extra[i], Decal)]
        inside = _inside(self.faces[:own], self.solids, self.camera)
        glass = self.clear(_outside([(i, g) for i, g in shown.clear if i < own], inside))
        glass += [b for i, parts in added.items() if isinstance(self.extra[i], Band)
                  if (b := self.band(i, self.extra[i], parts)) is not None]
        glass.sort(key=lambda item: item[:2])
        outline = (f'<g fill="none" stroke-width="{LINE_MM:g}" stroke-opacity="{INK_OPACITY:g}" '
                   f'stroke-linejoin="round" stroke-linecap="round">{"".join(lines)}</g>')
        defs = f'<defs>{"".join(self.defs)}</defs>' if self.defs else ""
        return (f'<g data-art="3d">{defs}{"".join(fills)}{"".join(marks)}{outline}'
                f'{"".join(svg for *_, svg in glass)}{"".join(self.edges(shown))}</g>'), shown


def _line(solids: SolidSet, camera: Camera) -> tuple[str, Shown]:
    faces = solids.faces
    shown = visible(faces, solids.solids, camera)

    def surfaces(pieces) -> list[tuple[int, list]]:
        """The pieces of each surface with its first face, far first; the first face index breaks a tie."""

        groups: dict[tuple, list] = {}
        for i, geom in pieces:
            groups.setdefault(_body_key(faces[i], solids.solids[faces[i].solid]) or faces[i].surface, []).append(
                (i, geom))

        def order(members) -> tuple[float, int]:
            return float(np.mean([camera.depth(faces[i].ring).mean() for i, _ in members])), members[0][0]

        return [(members[0][0], [g for _, g in members]) for members in sorted(groups.values(), key=order)]

    fills, lines = [], []
    for first, parts in surfaces(shown.pieces):
        geom = _merged(parts)
        d = _rings(geom, True)
        if not d:
            continue
        color = figure_color(solids.solids[faces[first].solid])
        fills.append(f'<path d="{d}" fill="{color}" fill-rule="evenodd" stroke="{color}" stroke-width="{SEAM_MM:g}"/>')
        lines.append(f'<path d="{_rings(geom, False)}" stroke="{_hex(_rgb(color) * INK)}"/>')
    glass = []
    for first, parts in surfaces(_outside(shown.clear, _inside(faces, solids.solids, camera))):
        d = _rings(_merged(parts), True)
        if not d:
            continue
        look = solids.solids[faces[first].solid].look
        opacity = min(look.opacity, 0.5) if look.transmission > 0 else look.opacity
        color = figure_color(solids.solids[faces[first].solid])
        glass.append(f'<path d="{d}" fill="{color}" fill-opacity="{opacity:g}" fill-rule="evenodd" '
                     f'stroke="{_hex(_rgb(color) * INK)}" stroke-width="{LINE_MM:g}" stroke-opacity="0.7"/>')
    outline = (f'<g fill="none" stroke-width="{LINE_MM:g}" stroke-opacity="{INK_OPACITY:g}" stroke-linejoin="round" '
               f'stroke-linecap="round">{"".join(lines)}</g>')
    return f'<g data-art="3d">{"".join(fills)}{outline}{"".join(glass)}</g>', shown


def drawn(solids: SolidSet, camera: Camera, *, style: str = "studio", shadows: bool = True,
          face_limit: int = FACE_LIMIT) -> tuple[str, Shown]:
    """:func:`draw`, and the hidden-surface result it drew from, for ``covered``."""

    if style not in STYLES:
        raise ValueError(f"style must be one of: {', '.join(STYLES)}")
    front = sum(map(camera.facing, solids.faces))
    if front > face_limit:
        raise Vector3DError(f"this 3D view has {front:,} faces after culling, over the limit of {face_limit:,}: crop "
                            "the chip with region=(x0, y0, x1, y1), or use the studio render (scene.render_3d_image)")
    return _Studio(solids, camera).draw(shadows) if style == "studio" else _line(solids, camera)


def draw(solids: SolidSet, camera: Camera, *, style: str = "studio", shadows: bool = True,
         face_limit: int = FACE_LIMIT) -> str:
    """The view as one SVG group in page mm. ``style="studio"``: lit surfaces, soft shadows, decals, hole grids and
    beams; ``shadows=False`` leaves the shadows out. ``style="line"``: flat figure colours, outlines and clear faces.
    A view of more than ``face_limit`` front faces raises Vector3DError before the hidden step."""

    return drawn(solids, camera, style=style, shadows=shadows, face_limit=face_limit)[0]


def draw_ids(solids: SolidSet, camera: Camera, width_mm: float, height_mm: float, color_of: Callable[[int], str], *,
             min_opacity: float = 0.5) -> str:
    """An SVG with each solid in its own flat colour ``color_of(solid.id)``, for the viewer comparison. Solids under
    ``min_opacity`` are left out; all others paint opaque."""

    keep = {s.id for s in solids.solids if s.look.opacity >= min_opacity}
    shown = visible(solids.faces, solids.solids, camera, opaque=lambda s: s.id in keep)
    per_solid: dict[int, list] = {}
    for i, geom in shown.pieces:
        per_solid.setdefault(solids.faces[i].solid, []).append(geom)
    body = "".join(f'<path d="{_rings(shapely.union_all(np.array(g, dtype=object), grid_size=GRID_MM), True)}" '
                   f'fill="{color_of(sid)}" fill-rule="evenodd"/>' for sid, g in sorted(per_solid.items()))
    return _svg(body, width_mm, height_mm)


def _svg(body: str, width_mm: float, height_mm: float) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width_mm:.3f}mm" height="{height_mm:.3f}mm" '
            f'viewBox="0 0 {width_mm:.3f} {height_mm:.3f}">{body}</svg>')


def frame(solids: SolidSet, direction, projection: str, width_mm: float, *, camera: str | None = None,
          style: str = "studio", shadows: bool = True) -> tuple[Camera, float]:
    """:func:`camera_for`, with a bench's floor shadow inside the page and its widest reach in the margin: a page
    edge would cut it in a hard line."""

    floor = []
    if style == "studio" and shadows and _bench(solids.constants):
        plane = _board_top(solids.constants)
        floor = [rings[0] for band in BENCH_SHADOW for rings in _dropped(solids, plane, band)]
    if not floor:
        return camera_for(solids, direction, projection, width_mm, camera=camera)
    reach = max(band.reach_mm for band in BENCH_SHADOW) * width_mm / SHADOW_PAGE_MM
    return camera_for(solids, direction, projection, width_mm, camera=camera, also=np.vstack(floor),
                      margin_mm=1.0 + reach)


def render_3d_svg(scene, path=None, *, direction="isometric", projection: str = "perspective", style: str = "studio",
                  width_mm: float = 120.0, shadows: bool = True, camera: str | None = None,
                  face_limit: int = FACE_LIMIT) -> str | Path:
    """One SVG of ``scene`` in 3D, ``width_mm`` wide, its height from the content. Returns the SVG text, or the
    path when ``path`` is given.

    ``direction`` is a viewer camera preset, such as ``"isometric"``, or ``(x, y, z)`` from the scene toward the
    camera, z up. ``projection`` is ``"perspective"`` or ``"parallel"``. ``style`` is ``"studio"`` (lit) or
    ``"line"`` (flat figure colours). ``shadows=False`` leaves the studio's shadows out. ``camera="home"`` takes
    the viewer's framed pose. A view of more than ``face_limit`` front faces raises Vector3DError."""

    solids = scene_solids(scene)
    view, height_mm = frame(solids, direction, projection, width_mm, camera=camera, style=style, shadows=shadows)
    text = _svg(draw(solids, view, style=style, shadows=shadows, face_limit=face_limit), width_mm, height_mm)
    if path is None:
        return text
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    return out
