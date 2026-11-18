"""The top view: an SEM-like image of a chip region, seen from above or tilted.

The process that makes a cross-section runs again on cuts across the region: one along every pixel row and
one along every pixel column (a cut that crosses the same layout as one before it runs once). Each cut gives
the height of the top surface and what lies under it. A pixel takes the cut that changes nearest to it, so a
tapered wall shows in both directions and a buried edge does not cut into the surface over it. ``stage`` picks
how far the process runs: "device" stops before the first oxide (the wafer as a waveguide SEM shows it),
"chip" is the finished chip, and a step id stops after that step.

The shading follows look B: a grey per material, bright walls and edges (the secondary-electron yield rises
with the angle between the beam and the surface), beam blur, seeded noise, an info bar with a scale bar, and
the marks of a render. Under a dielectric the material below shows, fainter with depth; metal and silicon hide
what lies under them, so a device shows on a finished chip unless metal covers it. That fade is a model, not
a measured beam range.
"""

from __future__ import annotations

import dataclasses
import math
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from optodraw.gds.layout import GDSLayout, load_gds_layout
from optodraw.gds.xsection.cut import cut_layout, layer_key
from optodraw.gds.palette import canonical, is_metal
from optodraw.gds.xsection.sem import sem_grey

_SUB = 2                             # samples per pixel along a cut, averaged; rows per pixel in a tilt
_CHANGE = (1e-4, 0.5)                # um of height and grey levels: a step between pixels this large is a change
SEE_THROUGH = 2.5                    # um: by default a buried material shows with weight exp(-depth / this)
_OPAQUE = frozenset({"silicon", "polysilicon", "germanium"})    # and every metal
_THIN = 1e-6                         # um: a run of a region thinner than this is a sliver, not a film
_SLOPE = (22.0, 0.17)                # grey per unit of yield over a flat surface's, and the smallest cosine
_STEEP = 1.0                         # a slope over 45 degrees is a wall
_EDGE = (55.0, 0.03)                 # the glow on the top side of a wall: grey and fall-off length in um
_FOOT = (-25.0, 0.05)                # the shadow at the foot of a wall
_DETECTOR = (18.0, (-0.45, 0.89))    # walls that face the detector (up and to the left) show brighter


@dataclass
class TopMaps:
    """A view's pixels before shading: row 0 is the far edge of the view."""

    height: np.ndarray               # um, the top surface
    grey: np.ndarray                 # the material grey there, with what shows through
    pitch: float                     # um per pixel


@dataclass
class TopView:
    layout: GDSLayout                # the shapes near the region only
    process: Any                     # the process, up to the stage
    names: dict[str, str]            # layer key -> process layer name (a process file names its own)
    region: tuple[float, float, float, float]
    stage: str
    reach: float                     # um: how far a cut runs past the region
    findings: list[str] = field(default_factory=list)
    film: tuple | None = None        # the conformal films that end the process: first step, thickness,
                                     # conformality, their region names
    see_through: float = SEE_THROUGH  # um: a buried material shows with weight exp(-depth / this)
    _maps: dict = field(default_factory=dict, repr=False)

    def check(self) -> list[str]:
        """One sentence per fault of this view; empty when it is clean. Look at the image too."""

        return list(self.findings)

    def maps(self, width_px: int = 2000, rotation: float = 0.0) -> TopMaps:
        """The height and grey of each pixel, ``width_px`` across, the view turned by ``rotation`` degrees."""

        key = (int(width_px), float(rotation) % 360.0)
        if key not in self._maps:
            self._maps[key] = _build_maps(self, *key)
        return self._maps[key]

    def locate(self, x: float, y: float, width_px: int = 2000, rotation: float = 0.0) -> tuple[float, float]:
        """The pixel ``(column, row)`` of ``maps(width_px, rotation)`` over the layout point ``(x, y)``, as a float:
        pixel ``i`` spans ``i`` to ``i + 1``. It is the map ``_build_maps`` samples through, run backwards."""

        x0, y0, x1, y1 = self.region
        wide, tall = x1 - x0, y1 - y0
        pitch = wide / max(1, width_px)
        phi = math.radians(rotation)
        dx, dy = float(x) - (x0 + x1) / 2.0, float(y) - (y0 + y1) / 2.0
        a, b = dx * math.cos(phi) + dy * math.sin(phi), -dx * math.sin(phi) + dy * math.cos(phi)
        return (a + wide / 2.0) / pitch, (tall / 2.0 - b) / pitch

    def png(self, path: str | Path | None = None, *, tilt: float = 0.0, rotation: float = 0.0, seed: int = 0,
            mark: bool = True, width_px: int = 2000) -> bytes:
        """The view as an SEM-like PNG ``width_px`` across, written to ``path`` when given. ``tilt`` (degrees)
        leans the view toward its bottom edge; ``rotation`` (degrees) turns it, so the image's horizontal runs
        along that direction of the layout. It is marked as a render; ``mark=False`` removes the visible
        marks, the PNG metadata stays."""

        if not 0.0 <= float(tilt) < 90.0:
            raise ValueError(f"tilt is in degrees from straight down, 0 to under 90, not {tilt!r}")
        data = render_top(self.maps(width_px, rotation), self.region[2] - self.region[0], tilt=float(tilt),
                          seed=seed, mark=mark)
        if path is not None:
            Path(path).write_bytes(data)
        return data


def top_view(gds: Any, stack: Any, region: tuple[float, float, float, float], *, stage: str = "device",
             cell_name: str | None = None, see_through: float = SEE_THROUGH) -> TopView:
    """The top view of ``region`` (x0, y0, x1, y1) of ``gds`` (a path or a loaded ``GDSLayout``), made by the
    process ``stack`` implies (a bundled stack name, a stack YAML, a loaded ``LayerStackSpec``, or a process
    YAML). ``stage`` is "device", "chip" or a step id. Under a dielectric a material shows with weight
    exp(-depth / ``see_through``), depth in um: a model of how a buried device shows, not a beam range."""

    from optodraw.gds.parsers import LayerStackSpec, load_layer_stack
    from optodraw.gds.xsection.model import _process_file
    from optodraw.gds.xsection.stack_process import process_from_stack

    x0, y0, x1, y1 = (float(value) for value in region)
    if x1 <= x0 or y1 <= y0:
        raise ValueError("a region is (x0, y0, x1, y1) with x1 > x0 and y1 > y0")
    if not float(see_through) > 0.0:
        raise ValueError(f"see_through is a depth in um above 0, not {see_through!r}")
    if isinstance(gds, GDSLayout):
        layout = gds
    else:
        with warnings.catch_warnings():          # undeclared layers are findings here, not warnings
            warnings.simplefilter("ignore", UserWarning)
            layout = load_gds_layout(gds, cell_name=cell_name)
    centre, radius = ((x0 + x1) / 2.0, (y0 + y1) / 2.0), math.hypot(x1 - x0, y1 - y0) / 2.0
    process = None if isinstance(stack, LayerStackSpec) else _process_file(stack)
    findings: list[str] = []
    names: dict[str, str] = {}
    if process is not None:
        names = {layer_key(item.gds): name for name, item in process.layout_layers.items()}
        reach = _reach(process)
        near = _near(layout, centre, radius + reach)
        known = set(names)
    else:
        spec = stack if isinstance(stack, LayerStackSpec) else load_layer_stack(stack)
        reach = _reach(process_from_stack(spec))
        near = _near(layout, centre, radius + reach)
        process = process_from_stack(spec, drawn={layer_key(r.spec) for r in near.layer_records})
        known = {layer_key(s) for s in spec.styles}
        findings += list(spec.warnings)
    inside = sorted({layer_key(r.spec) for r in _near(near, centre, radius).layer_records})
    for key in inside:
        if key not in known:
            findings.append(f"layer {key[1:].replace('_', '/')} is drawn in the region but the stack has no entry")
    if not inside:
        findings.append("the region holds no drawn layer: only the substrate and the cladding show")
    process = dataclasses.replace(process, process=_stage_steps(process.process, stage, process.fill_material))
    return TopView(layout=near, process=process, names=names, region=(x0, y0, x1, y1), stage=str(stage),
                   reach=reach, findings=findings, film=_trailing_film(process.process),
                   see_through=float(see_through))


def _stage_steps(steps: list, stage: str, fill: str = "sio2") -> list:
    """The steps up to ``stage``: "device" stops before the first step of the ``fill`` material (the oxide, or a
    polymer that fills the etches), "chip" runs them all, a step id stops after that step."""

    if stage == "chip":
        return list(steps)
    if stage == "device":
        for index, step in enumerate(steps):
            adds = step.fill or step.deposit or {}
            if canonical(adds.get("material_key") or adds.get("material", "")) == canonical(fill):
                return list(steps[:index])
        return list(steps)
    ids = [step.id for step in steps]
    if stage not in ids:
        raise ValueError(f"stage is 'device', 'chip' or a step id; this process has {', '.join(ids)}")
    return list(steps[: ids.index(stage) + 1])


def _trailing_film(steps: list) -> tuple | None:
    """The conformal films that end the process (only etches after them, such as the pad openings): the
    index of the first, their thickness together, their conformality and their region names. None when the
    process ends otherwise."""

    i = len(steps) - 1
    while i >= 0 and steps[i].etch is not None and steps[i].deposit is None and steps[i].fill is None:
        i -= 1
    first, thickness, conformality = None, 0.0, None
    while i >= 0:
        step, film = steps[i], steps[i].deposit
        if (film is None or step.mask is not None or film.get("on") or step.etch or step.fill or step.implant
                or step.planarize or float(film.get("conformality", 0.0)) <= 0.0):
            break
        c = min(float(film["conformality"]), 1.0)
        if conformality is not None and abs(c - conformality) > 1e-9:
            break
        first, thickness, conformality = i, thickness + float(film.get("thickness", 0.0)), c
        i -= 1
    if first is None or thickness <= 0.0:
        return None
    names = tuple(sorted({str(step.deposit.get("material", "deposit")) for step in steps[first:]
                          if step.deposit is not None}))
    return first, thickness, conformality, names


def _reach(process) -> float:
    """How far past the region a cut must run so the region's edge looks as inside: the conformal films
    spread sideways by their thickness."""

    spread = sum(float(step.deposit.get("thickness", 0.0)) for step in process.process
                 if step.deposit is not None and float(step.deposit.get("conformality", 0.0)) > 0.0)
    return spread + 1.0


def _near(layout: GDSLayout, centre: tuple[float, float], radius: float) -> GDSLayout:
    """The layout with only the shapes whose bounding box comes within ``radius`` of ``centre`` (as a
    square)."""

    cx, cy = centre
    records = []
    for record in layout.layer_records:
        kept = []
        for points in record.polygons:
            if len(points) < 3:
                continue
            xy = np.asarray(points, dtype=float)
            if (xy[:, 0].min() <= cx + radius and xy[:, 0].max() >= cx - radius
                    and xy[:, 1].min() <= cy + radius and xy[:, 1].max() >= cy - radius):
                kept.append(points)
        if kept:
            records.append(dataclasses.replace(record, polygons=kept))
    return dataclasses.replace(layout, layer_records=records)


def _build_maps(view: TopView, width_px: int, rotation: float) -> TopMaps:
    x0, y0, x1, y1 = view.region
    wide, tall = x1 - x0, y1 - y0
    nu = max(1, width_px)
    pitch = wide / nu
    nv = max(1, round(tall / pitch))
    cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    phi = math.radians(rotation)
    eu, ev = (math.cos(phi), math.sin(phi)), (-math.sin(phi), math.cos(phi))
    m = view.reach
    u = -wide / 2.0 + (np.arange(nu) + 0.5) * pitch
    v = tall / 2.0 - (np.arange(nv) + 0.5) * pitch

    def point(a: float, b: float) -> tuple[float, float]:
        return cx + a * eu[0] + b * ev[0], cy + a * eu[1] + b * ev[1]

    cache: dict = {}
    rows = [(point(-wide / 2.0 - m, b), point(wide / 2.0 + m, b)) for b in v]          # along +u
    columns = [(point(a, tall / 2.0 + m), point(a, -tall / 2.0 - m)) for a in u]      # top to bottom
    zr, gr, ur, fr = _cuts(view, rows, nu, pitch, wide + 2.0 * m, cache)
    zc, gc, uc, fc = (a.T for a in _cuts(view, columns, nv, pitch, tall + 2.0 * m, cache))
    # each pixel takes the cut that changes nearest to it: the height by its height, the grey by either
    dx_z, dy_z = _distance(_changes(zr, _CHANGE[0], 1), 1), _distance(_changes(zc, _CHANGE[0], 0), 0)
    dx_g = np.minimum(dx_z, _distance(_changes(gr, _CHANGE[1], 1), 1))
    dy_g = np.minimum(dy_z, _distance(_changes(gc, _CHANGE[1], 0), 0))
    wz, wg = _share(dx_z, dy_z), _share(dx_g, dy_g)
    height = wz * zr + (1.0 - wz) * zc
    if view.film is not None:                            # the film's top as a 3D film makes it
        wu = _share(_distance(_changes(ur, _CHANGE[0], 1), 1), _distance(_changes(uc, _CHANGE[0], 0), 0))
        on_top = wz * fr + (1.0 - wz) * fc > 0.5
        height = _film_top(height, wu * ur + (1.0 - wu) * uc, on_top, pitch, *view.film[1:3])
    return TopMaps(height=height, grey=wg * gr + (1.0 - wg) * gc, pitch=pitch)


def _film_top(height: np.ndarray, under: np.ndarray, on_top: np.ndarray, pitch: float, thickness: float,
              conformality: float) -> np.ndarray:
    """A conformal film is the surface ``under`` it grown by a half ellipsoid, ``thickness`` up and
    ``conformality * thickness`` sideways. A cut finds that beside an edge it crosses but not round an outside
    corner, which no row and no column crosses. Where the film is on top within that reach of a change of
    ``under``, take its top from the half ellipsoid itself: it rounds the corners and meets the cuts beside
    the edges."""

    from scipy import ndimage

    reach = conformality * thickness / pitch             # pixels the film spreads sideways
    changed = _changes(under, _CHANGE[0], 1) | _changes(under, _CHANGE[0], 0)
    if reach < 1.0 or not changed.any():
        return height
    missed = on_top & (ndimage.distance_transform_edt(~changed) <= reach)
    if not missed.any():
        return height
    r, stride = int(math.ceil(reach)), max(1, math.ceil(reach / 40.0))
    oy, ox = np.mgrid[-r:r + 1:stride, -r:r + 1:stride]
    inside = oy * oy + ox * ox <= reach * reach
    oy, ox = oy[inside], ox[inside]
    lift = thickness * np.sqrt(np.clip(1.0 - (oy * oy + ox * ox) / (reach * reach), 0.0, None))
    padded = np.pad(under, r, constant_values=-np.inf)
    rows, cols = np.nonzero(missed)
    top = np.empty(len(rows))
    chunk = max(1, 2_000_000 // len(oy))
    for start in range(0, len(rows), chunk):
        rr, cc = rows[start:start + chunk, None] + r + oy, cols[start:start + chunk, None] + r + ox
        top[start:start + chunk] = (padded[rr, cc] + lift).max(axis=1)
    out = height.copy()
    out[rows, cols] = np.maximum(out[rows, cols], top)
    return out


def _changes(values: np.ndarray, step: float, axis: int) -> np.ndarray:
    """Where ``values`` step by more than ``step`` to a neighbour along ``axis``."""

    jump = np.abs(np.diff(values, axis=axis)) > step
    found = np.zeros(values.shape, dtype=bool)
    lead, tail = [slice(None)] * 2, [slice(None)] * 2
    lead[axis], tail[axis] = slice(1, None), slice(None, -1)
    found[tuple(lead)] |= jump
    found[tuple(tail)] |= jump
    return found


def _distance(found: np.ndarray, axis: int) -> np.ndarray:
    """Pixels to the nearest ``found`` along ``axis`` only; infinite where that line has none."""

    from scipy import ndimage

    if not found.any():
        return np.full(found.shape, np.inf)
    far = 1e9
    sampling = (far, 1.0) if axis == 1 else (1.0, far)
    distance = ndimage.distance_transform_edt(~found, sampling=sampling)
    return np.where(distance >= far, np.inf, distance)


def _share(dx: np.ndarray, dy: np.ndarray) -> np.ndarray:
    """The row cut's share: whole where only the row changes near, none where only the column does."""

    with np.errstate(invalid="ignore", divide="ignore"):
        w = np.where(np.isinf(dy), 1.0, dy / (dx + dy))
    return np.where((np.isinf(dx) & np.isinf(dy)) | (dx + dy == 0.0), 0.5, w)


def _cuts(view: TopView, ends: list, count: int, pitch: float, length: float, cache: dict):
    """The height and grey along each cut from ``ends``, ``count`` pixels over the middle. A cut that crosses
    the same layout as one before it reuses its result."""

    from optodraw.gds.xsection.engine import XSectionEngine
    from optodraw.gds.xsection.model import _clip

    engine = XSectionEngine(view.process)
    margin = (length - count * pitch) / 2.0
    s = margin + (np.arange(count * _SUB) + 0.5) * pitch / _SUB
    heights, greys, unders, films = [], [], [], []
    names = view.film[3] if view.film is not None else ()
    for start, end in ends:
        cut = _clip(cut_layout(view.layout, start, end), 0.0, length, view.names)
        key = (round(length, 7), tuple(sorted(
            (name, tuple((round(i.y0, 7), round(i.y1, 7)) for i in found.intervals))
            for name, found in cut.layer_intervals.items())))
        if key not in cache:
            out = engine.run(cut)
            z, g, on_film = _profile(out.internal_regions, out.materials, s, names, view.see_through)
            under = z if view.film is None else _profile(out.steps[view.film[0]][2], out.materials, s)[0]
            cache[key] = tuple(a.reshape(count, _SUB).mean(axis=1) for a in (z, g, under, on_film))
        for found, value in zip((heights, greys, unders, films), cache[key]):
            found.append(value)
    return np.vstack(heights), np.vstack(greys), np.vstack(unders), np.vstack(films)


def _edges(geometry) -> np.ndarray:
    """(s_a, z_a, s_b, z_b) of every ring edge of a region."""

    from optodraw.gds.xsection.schematic import _polygons

    rings = []
    for polygon in _polygons(geometry):
        for ring in (polygon.exterior, *polygon.interiors):
            xy = np.asarray(ring.coords, dtype=float)
            rings.append(np.hstack([xy[:-1], xy[1:]]))
    return np.vstack(rings) if rings else np.zeros((0, 4))


def _crossings(edges: np.ndarray, s: np.ndarray):
    """The sample index and z where each edge crosses the samples ``s`` (sorted). An edge holds a sample
    when its lower s <= sample < its higher s, so a closed ring crosses each sample an even number of times."""

    sa, za, sb, zb = edges.T
    j0 = np.searchsorted(s, np.minimum(sa, sb), "left")
    j1 = np.searchsorted(s, np.maximum(sa, sb), "left")
    counts = np.maximum(j1 - j0, 0)
    edge = np.repeat(np.arange(len(edges)), counts)
    index = j0[edge] + np.arange(counts.sum()) - np.repeat(np.cumsum(counts) - counts, counts)
    t = (s[index] - sa[edge]) / (sb[edge] - sa[edge])
    return index, za[edge] + t * (zb[edge] - za[edge])


def _intervals(index: np.ndarray, z: np.ndarray):
    """The runs inside a region at each sample: pairs of crossings, bottom and top, in order."""

    order = np.lexsort((z, index))
    index, z = index[order], z[order]
    if len(index) < 2:
        return index[:0], z[:0], z[:0]
    first = np.r_[True, index[1:] != index[:-1]]
    starts = np.flatnonzero(first)
    rank = np.arange(len(index)) - np.repeat(starts, np.diff(np.r_[starts, len(index)]))
    lower = np.flatnonzero((rank % 2 == 0)[:-1] & (index[1:] == index[:-1]))
    return index[lower], z[lower], z[lower + 1]


def _profile(regions: dict, materials: dict, s: np.ndarray, film: tuple = (), see_through: float = SEE_THROUGH):
    """The top surface along a cut at ``s``, its grey (the first opaque material down from the surface and the
    dielectrics over it, each weighted by exp(-depth / ``see_through``)), and 1 where the top is one of the
    regions ``film``, else 0."""

    names = [name for name, geometry in regions.items() if not geometry.is_empty]
    tops = np.full((len(names), len(s)), -np.inf)
    found = []
    for row, name in enumerate(names):
        index, lo, hi = _intervals(*_crossings(_edges(regions[name]), s))
        real = hi - lo > _THIN                           # a sliver with no thickness hides nothing
        index, lo, hi = index[real], lo[real], hi[real]
        np.maximum.at(tops[row], index, hi)
        found.append((index, lo, hi))
    grey_of = np.array([float(sem_grey(materials.get(name, name))) for name in names])
    opaque = np.array([is_metal(m) or canonical(m) in _OPAQUE for m in (materials.get(n, n) for n in names)],
                      dtype=bool)
    top = tops.max(axis=0)
    covered = np.where(opaque[:, None], tops, -np.inf)
    floor, under = covered.max(axis=0), covered.argmax(axis=0)
    grey = np.zeros(len(s))
    seen = np.isfinite(floor)
    grey[seen] = grey_of[under[seen]] * np.exp(-(top[seen] - floor[seen]) / see_through)
    for row in np.flatnonzero(~opaque):
        index, lo, hi = found[row]
        a = np.maximum(lo, floor[index])
        b = np.minimum(hi, top[index])
        keep = b > a
        index, a, b = index[keep], a[keep], b[keep]
        depth = top[index]
        np.add.at(grey, index, grey_of[row] * (np.exp(-(depth - b) / see_through) - np.exp(-(depth - a) / see_through)))
    on_film = np.isin(np.asarray(names, dtype=object)[tops.argmax(axis=0)], list(film)) if names else np.zeros(len(s))
    return np.where(np.isfinite(top), top, 0.0), grey, on_film.astype(float)


def project(height: np.ndarray, shade: np.ndarray, pitch: float, tilt: float) -> np.ndarray:
    """The view leaned ``tilt`` degrees toward its bottom edge, seen straight on: a row nearer the viewer
    hides what stands behind it lower than its own top, and the front face of a step shows. The image ends at
    the far edge of the view, so every pixel shows the sample."""

    if tilt == 0.0:
        return shade
    t = math.radians(tilt)
    ss = _SUB                                             # rows per pixel, averaged at the end
    height, shade = np.repeat(height, ss, axis=0), np.repeat(shade, ss, axis=0)
    nv, nu = height.shape
    lift = (height - height.min()) / pitch * ss * math.sin(t)
    rows = int(math.ceil(nv * math.cos(t) + lift.max() - 1e-9))
    image = np.zeros((rows, nu))
    horizon = np.zeros(nu, dtype=int)
    columns = np.arange(nu)
    for i in range(nv - 1, -1, -1):                      # from the near edge to the far one
        top = np.minimum(np.rint((nv - i) * math.cos(t) + lift[i]).astype(int), rows)
        grow = np.maximum(top - horizon, 0)
        if grow.any():
            at = np.repeat(columns, grow)
            up = horizon[at] + np.arange(grow.sum()) - np.repeat(np.cumsum(grow) - grow, grow)
            image[rows - 1 - up, at] = np.repeat(shade[i], grow)
            horizon = np.maximum(horizon, top)
    seen = (int(horizon.min()) // ss) * ss
    return image[rows - seen:].reshape(-1, ss, nu).mean(axis=1)


def _shade(maps: TopMaps, tilt: float) -> np.ndarray:
    """The grey of each pixel as the beam sees it: the material, the yield of its slope, the glow on the top
    side of a wall and the shadow at its foot, and the side that faces the detector."""

    from scipy import ndimage

    p = maps.pitch
    d_row, d_col = np.gradient(maps.height, p) if min(maps.height.shape) > 1 else (
        np.zeros_like(maps.height), np.zeros_like(maps.height))
    gu, gv = d_col, -d_row                               # row 0 is the far edge: v runs up the image
    norm = np.sqrt(gu * gu + gv * gv + 1.0)
    t = math.radians(tilt)
    facing = (gv * math.sin(t) + math.cos(t)) / norm     # the cosine between the beam and the surface normal
    gain, least = _SLOPE
    shade = maps.grey + gain * (1.0 / np.clip(facing, least, 1.0) - 1.0 / math.cos(t))
    steep = np.hypot(gu, gv) > _STEEP
    if steep.any() and not steep.all():
        distance, (ii, jj) = ndimage.distance_transform_edt(~steep, return_indices=True)
        upper = maps.height > maps.height[ii, jj]
        (up_gain, up_len), (foot_gain, foot_len) = _EDGE, _FOOT
        glow = np.where(upper, up_gain * np.exp(-distance / max(up_len / p, 1.5)),
                        foot_gain * np.exp(-distance / max(foot_len / p, 1.5)))
        shade = shade + np.where(steep, 0.0, glow)
    detector_gain, (du, dv) = _DETECTOR
    return shade + detector_gain * (-gu * du - gv * dv) / norm


def render_top(maps: TopMaps, span: float, *, tilt: float = 0.0, seed: int = 0, mark: bool = True) -> bytes:
    """``maps`` as an SEM-like PNG with an info bar under it; ``span`` is the view's width in um."""

    from scipy import ndimage

    from optodraw.gds.xsection.sem import _BEAM, _NOISE, _diagonal_mark, _info_bar, _png_bytes

    image = project(maps.height, _shade(maps, tilt), maps.pitch, tilt)
    band = _feature_rows(image)
    image = ndimage.gaussian_filter(image, max(_BEAM / maps.pitch, 0.7))
    rng = np.random.default_rng(seed)
    image = image + rng.normal(0.0, 1.0, image.shape) * (_NOISE[0] + _NOISE[1] * np.clip(image, 0.0, None))
    image = ndimage.gaussian_filter(image, 0.5)
    if mark:
        image = _diagonal_mark(image, band)
    bar = _info_bar(span, 1.0 / maps.pitch, image.shape[1], mark, f"tilt {tilt:g}°" if tilt else "")
    return _png_bytes(np.vstack([image, bar]))


def _feature_rows(image: np.ndarray) -> tuple[float, float, float] | None:
    """The first and last rows that hold a feature (a row that is not one grey), as the mark wants them: it
    goes in the taller clear band over or under them. None when every row is one grey."""

    busy = np.flatnonzero(image.std(axis=1) > 2.0)
    if len(busy) == 0:
        return None
    return 0.0, float(busy[0]), float(busy[-1] + 1)

