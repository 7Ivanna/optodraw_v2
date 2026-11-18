"""The viewer comparison harness: the three.js viewer and the vector 3D renderer draw one scene in flat id colours,
one colour per solid, from one camera. A solid that one side misses, moves or shapes differently shows as a patch of
wrong colour, also in front of a solid of the same base colour.

One headless Chrome serves a test session. Parts with equal page constants share one page load. Each part then goes
in through ``window.__odRebuild``, and one ``Runtime.evaluate`` paints the ids and returns both pictures and the
material of each mesh. The hook goes in after the page has loaded, so the viewer page itself does not change. The
renderer's pictures (the hidden step, then cairosvg) run in a process pool while Chrome works."""

from __future__ import annotations

import base64
import io
import json
import math
import multiprocessing
import os
import tempfile
import time
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field, replace
from itertools import combinations
from pathlib import Path

import numpy as np
import shapely
from PIL import Image, ImageColor
from scipy import ndimage

from optodraw.core.view_layout import display_scene
from optodraw.renderers.capture3d import _Pipe, find_chrome
from optodraw.renderers.threejs_renderer import ThreeJsRenderer
from optodraw.renderers.vector3d import draw_ids
from optodraw.renderers.vector3d_hidden import Camera, camera_for
from optodraw.renderers.vector3d_scene import scene_solids
from optodraw.renderers.vector3d_solids import Solid, SolidSet

PROJECTIONS = ("parallel", "perspective")
DIRECTION = "isometric"
WIDTH_MM = 120.0
WIDTH_PX = 1000
MIN_OPACITY = 0.5          # a clearer solid stays out of the pictures on both sides
TOL = 6                    # a pixel is wrong when a channel differs by more than this
STEP = 17                  # the id lattice: 16 levels per channel; white is the background
COLORS = tuple("#%02x%02x%02x" % (STEP * (i % 16), STEP * (i // 16 % 16), STEP * (i // 256)) for i in range(4095))
LOOK_KEYS = ("opacity", "metalness", "roughness", "clearcoat", "transmission")
CAPTURE = {"width": 64, "height": 64, "scale": 1.0, "background": "none", "labels": False}

# Runs in the loaded capture page. The meshes are numbered as the renderer numbers its solids: a preorder walk of the
# visible scene, odContent first, then the chip base. Lines, points and sprites are no solids and are hidden.
HOOK = """(() => {
  const view = window.__odView, rebuild = window.__odRebuild;
  if (!view || !view.THREE || !view.scene || typeof rebuild !== 'function') {
    throw new Error('the viewer page has no window.__odView or window.__odRebuild');
  }
  const { THREE, scene } = view;
  const colors = __COLORS__;
  const gl = new THREE.WebGLRenderer({ antialias: false, alpha: false, preserveDrawingBuffer: true });
  gl.setPixelRatio(1);
  gl.toneMapping = THREE.NoToneMapping;
  gl.outputColorSpace = THREE.SRGBColorSpace;
  gl.setClearColor(0xffffff, 1);
  window.__odFlat = (data, views, minOpacity) => {
    rebuild(data);
    const meshes = [];
    scene.traverseVisible((o) => {
      if (o.isMesh) meshes.push(o);
      else if (o.isLine || o.isPoints || o.isSprite) o.visible = false;
    });
    const table = meshes.map((o) => {
      const m = Array.isArray(o.material) ? o.material[0] : o.material;
      return { color: m.color ? '#' + m.color.getHexString() : null, opacity: m.opacity, metalness: m.metalness ?? 0,
               roughness: m.roughness ?? 1, clearcoat: m.clearcoat ?? 0, transmission: m.transmission ?? 0,
               decal: !!(m.transparent && m.map), side: m.side };
    });
    meshes.forEach((o, i) => {
      const row = table[i];
      o.material = new THREE.MeshBasicMaterial({ color: colors[i] || '#ff00ff', side: row.side, fog: false,
        visible: row.opacity >= minOpacity && !row.decal });
    });
    const images = views.map((v) => {
      const camera = new THREE.Camera();
      camera.matrixAutoUpdate = false;
      camera.matrixWorldAutoUpdate = false;
      camera.matrixWorld.set(...v.world);
      camera.matrixWorldInverse.copy(camera.matrixWorld).invert();
      camera.projectionMatrix.set(...v.projection);
      camera.projectionMatrixInverse.copy(camera.projectionMatrix).invert();
      gl.setSize(v.width, v.height, false);
      gl.render(scene, camera);
      return gl.domElement.toDataURL('image/png');
    });
    return { table, images };
  };
})()"""


@dataclass(frozen=True)
class Frame:
    """One projection of a scene: the renderer's camera and the picture size. The viewer renders through the same
    matrices, so a point lands on the same pixel on both sides."""

    camera: Camera
    width_mm: float
    height_mm: float
    pixels: tuple[int, int]
    near: float
    far: float

    def view(self) -> dict:
        """The record the hook reads: the camera's world matrix and its projection, row-major, and the size."""

        c, w, h, n, f = self.camera, self.width_mm, self.height_mm, self.near, self.far
        world = np.eye(4)
        world[:3, :3] = c.basis.T            # columns right, up and back
        world[:3, 3] = c.eye
        (ox, oy), k = c.origin, c.k
        if c.perspective:                    # Camera.page: k times view x and y over the distance, plus the origin
            projection = [[2 * k / w, 0, 1 - 2 * ox / w, 0], [0, 2 * k / h, 2 * oy / h - 1, 0],
                          [0, 0, -(f + n) / (f - n), -2 * f * n / (f - n)], [0, 0, -1, 0]]
        else:
            projection = [[2 * k / w, 0, 0, 2 * ox / w - 1], [0, 2 * k / h, 0, 1 - 2 * oy / h],
                          [0, 0, -2 / (f - n), -(f + n) / (f - n)], [0, 0, 0, 1]]
        return {"world": world.ravel().tolist(), "projection": np.ravel(projection).tolist(),
                "width": self.pixels[0], "height": self.pixels[1]}


def frame_for(solids: SolidSet, projection: str) -> Frame:
    """The renderer's camera for ``solids``, with the page height rounded up to whole pixels."""

    camera, height_mm = camera_for(solids, DIRECTION, projection, WIDTH_MM)
    scale = WIDTH_PX / WIDTH_MM
    rows = math.ceil(height_mm * scale)
    distance = camera.distance(camera.depth(np.vstack([f.ring for f in solids.faces])))
    return Frame(camera, WIDTH_MM, rows / scale, (WIDTH_PX, rows), 0.5 * float(distance.min()),
                 2.0 * float(distance.max()))


def own_pictures(solids: SolidSet, frames: list[Frame]) -> list[bytes]:
    """The renderer's id pictures, one PNG per frame. Runs in a worker process."""

    import cairosvg

    # crisp edges: the viewer's id pass runs with antialias off, so both sides sample the pixel centre
    return [cairosvg.svg2png(bytestring=draw_ids(solids, f.camera, f.width_mm, f.height_mm, COLORS.__getitem__,
                                                 min_opacity=MIN_OPACITY).replace(
                                 "<svg ", '<svg shape-rendering="crispEdges" ', 1).encode(),
                             output_width=f.pixels[0], output_height=f.pixels[1], background_color="white")
            for f in frames]


def without_solid(solids: SolidSet, solid: int) -> SolidSet:
    """A mutant: the faces of one solid removed, the ids kept."""

    return replace(solids, faces=[f for f in solids.faces if f.solid != solid])


def moved_solid(solids: SolidSet, solid: int, offset) -> SolidSet:
    """A mutant: one solid moved by ``offset`` in world units."""

    shift = np.asarray(offset, float)
    return replace(solids, faces=[replace(f, ring=f.ring + shift, holes=tuple(h + shift for h in f.holes))
                                  if f.solid == solid else f for f in solids.faces])


class Viewer:
    """One headless Chrome for a test session, with the page of the last group of parts loaded."""

    def __init__(self, chrome: str | None = None):
        self._folder = tempfile.TemporaryDirectory(prefix="optodraw-flat-")
        self._pipe = _Pipe(chrome or find_chrome(), Path(self._folder.name) / "profile", 800, 600)
        target = self._pipe.call("Target.createTarget", {"url": "about:blank"})["targetId"]
        self._session = self._pipe.call("Target.attachToTarget", {"targetId": target, "flatten": True})["sessionId"]
        self._loaded = None
        self.loads = 0

    def __enter__(self) -> Viewer:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        self._pipe.close()
        self._folder.cleanup()

    def _evaluate(self, expression: str, timeout: float = 120.0):
        reply = self._pipe.call("Runtime.evaluate", {"expression": expression, "returnByValue": True}, self._session,
                                timeout=timeout)
        if "exceptionDetails" in reply:
            details = reply["exceptionDetails"]
            raise RuntimeError(details.get("exception", {}).get("description") or details.get("text") or "page error")
        return reply.get("result", {}).get("value")

    def load(self, key, html: Callable[[], str], timeout: float = 120.0) -> None:
        """Load the page of ``key`` unless it is loaded now, and put the hook in."""

        if key == self._loaded:
            return
        self._loaded = None
        self.loads += 1
        page = Path(self._folder.name) / f"page{self.loads}.html"
        page.write_text(html(), encoding="utf-8")
        self._pipe.call("Page.navigate", {"url": page.as_uri()}, self._session)
        probe = (f"location.pathname.endsWith('/{page.name}') && "
                 "(document.getElementById('od-capture') || {}).value || ''")
        deadline, value = time.monotonic() + timeout, ""
        while not value:
            if time.monotonic() > deadline:
                raise TimeoutError(f"the viewer page did not render in {timeout:g} s")
            time.sleep(0.25)
            try:
                value = self._evaluate(probe, timeout=10.0)
            except RuntimeError:                 # the old page went away under the call
                value = ""
        if value.startswith("error"):
            raise RuntimeError(f"the viewer page failed: {value}")
        self._evaluate(HOOK.replace("__COLORS__", json.dumps(COLORS)))
        self._loaded = key

    def flat(self, items: list[dict], frames: list[Frame]) -> tuple[list[dict], list[bytes]]:
        """Rebuild the page from ``items`` and return the material of each mesh and one id picture per frame."""

        value = self._evaluate(f"JSON.stringify(window.__odFlat({json.dumps(items, default=str)}, "
                               f"{json.dumps([f.view() for f in frames])}, {MIN_OPACITY}))")
        out = json.loads(value)
        return out["table"], [base64.b64decode(url.split(",", 1)[1]) for url in out["images"]]


@dataclass
class Result:
    """The comparison of one scene. Solid ids are the renderer's; the viewer numbers its meshes the same way."""

    name: str
    error: str = ""
    solids: list[Solid] = field(default_factory=list)
    counts: tuple[int, int] = (0, 0)                     # viewer meshes, renderer solids
    materials: list[str] = field(default_factory=list)
    patches: dict[str, int] = field(default_factory=dict)
    wrong: dict[str, dict[int, tuple[int, int, int]]] = field(default_factory=dict)  # id: wrong, viewer, renderer px
    areas: dict[str, dict[int, int]] = field(default_factory=dict)                   # renderer px per solid id
    coplanar: list[tuple[int, int]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return (not self.error and self.counts[0] == self.counts[1] and not self.materials
                and not any(self.patches.values()))

    def _solid(self, i: int) -> str:
        if 0 <= i < len(self.solids):
            return f"{i} ({self.solids[i].part}, {self.solids[i].kind})"
        return f"{i} (not in the renderer)"

    def report(self) -> str:
        if self.error:
            return f"{self.name}: {self.error}"
        lines = []
        if self.counts[0] != self.counts[1]:
            lines.append(f"{self.name}: the viewer has {self.counts[0]} meshes, the renderer {self.counts[1]} solids")
        lines += [f"{self.name}: {line}" for line in self.materials]
        for projection, count in self.patches.items():
            if count:
                lines.append(f"{self.name}, {projection}: {count} patches")
                lines += [f"    solid {self._solid(i)}: {w} px wrong, viewer {a} px, renderer {b} px"
                          for i, (w, a, b) in sorted(self.wrong[projection].items())]
        if self.coplanar:
            lines.append(f"{self.name}: faces of two solids on one plane, which the viewer z-fights (a part fault): "
                         + ", ".join(f"{a} and {b}" for a, b in self.coplanar))
        return "\n".join(lines)


def _renderer(scene, options: dict) -> ThreeJsRenderer:
    return ThreeJsRenderer(display_scene(scene, "3d"), capture=dict(CAPTURE), world="light", **options)


def _pixels(png: bytes) -> np.ndarray:
    return np.asarray(Image.open(io.BytesIO(png)).convert("RGB")).astype(np.int16)


def _ids(picture: np.ndarray) -> np.ndarray:
    """The solid id of each pixel; -1 for the background and for a blend at an edge."""

    level = np.rint(picture / STEP)
    exact = (np.abs(picture - STEP * level) <= TOL).all(axis=2)
    ids = (level[..., 0] + 16 * level[..., 1] + 256 * level[..., 2]).astype(int)
    ids[~exact | (ids >= len(COLORS))] = -1
    return ids


def _near(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """True where the id of ``b`` shows in ``a`` within one pixel. WebGL and the renderer place a sub-pixel edge
    differently, so a grating tooth one pixel wide can sit one pixel over; a solid that is missing is still wrong
    across its inside."""

    padded = np.pad(a, 1, constant_values=-2)
    rows, cols = a.shape
    return np.logical_or.reduce([padded[1 + dy:1 + dy + rows, 1 + dx:1 + dx + cols] == b
                                 for dy in (-1, 0, 1) for dx in (-1, 0, 1)])


def _patches(viewer: np.ndarray, own: np.ndarray, pairs=()) -> tuple[int, dict[int, tuple[int, int, int]],
                                                                    dict[int, int]]:
    """The wrong pixels that survive 2 erosions, grown back: an edge blend or a patch under about 5 px does not
    count. A pixel where the two pictures show the two solids of a coplanar pair (``pairs``) is right either way:
    the viewer z-fights there. Returns the patch count, the solids in the patches, and the renderer's area of each
    solid."""

    a, b = _ids(viewer), _ids(own)
    wrong = (np.abs(viewer - own) > TOL).any(axis=2)
    wrong &= ~(_near(a, b) & _near(b, a))           # an edge one pixel off is a sampling rule, not a solid
    for i, j in pairs:
        wrong &= ~(((a == i) & (b == j)) | ((a == j) & (b == i)))
    patch = ndimage.binary_dilation(ndimage.binary_erosion(wrong, iterations=2), iterations=2) & wrong
    area = {int(i): int(n) for i, n in zip(*np.unique(b[b >= 0], return_counts=True))}
    if not patch.any():
        return 0, {}, area
    hit = np.concatenate((a[patch], b[patch]))
    solids = {int(i): (int(((a == i) | (b == i))[patch].sum()), int((a == i).sum()), int((b == i).sum()))
              for i in np.unique(hit[hit >= 0])}
    return int(ndimage.label(patch)[1]), solids, area


def _material_faults(table: list[dict], solids: list[Solid]) -> list[str]:
    out = []
    for i, (row, solid) in enumerate(zip(table, solids)):
        look, name = solid.look, f"solid {i} ({solid.part}, {solid.kind})"
        try:
            far = max(abs(x - y) for x, y in zip(ImageColor.getrgb(row["color"] or "")[:3],
                                                 ImageColor.getrgb(look.color)[:3]))
        except ValueError:
            far = 255
        if far > 1:                         # three.js holds a colour in linear light: one rounding step back
            out.append(f"{name}: colour viewer {row['color']}, renderer {look.color}")
        out += [f"{name}: {key} viewer {row[key]:g}, renderer {getattr(look, key):g}" for key in LOOK_KEYS
                if not math.isclose(float(row[key]), float(getattr(look, key)), abs_tol=1e-6)]
    return out


def coplanar(solids: SolidSet, ids) -> list[tuple[int, int]]:
    """Pairs of solids among ``ids`` with faces on one plane that face one way and overlap. The viewer z-fights
    there, so no renderer can match it: a part fault, to fix in the part."""

    planes: dict[tuple, list] = {}
    for face in solids.faces:
        if face.solid in ids:
            key = (*np.round(face.normal, 6).tolist(), round(float(face.normal @ face.ring[0]), 6))
            planes.setdefault(key, []).append(face)
    pairs = set()
    for key, faces in planes.items():
        if len({f.solid for f in faces}) < 2:
            continue
        normal = np.array(key[:3])
        u = np.cross(normal, (1.0, 0.0, 0.0) if abs(normal[0]) < 0.9 else (0.0, 1.0, 0.0))
        u /= np.linalg.norm(u)
        axes = np.column_stack((u, np.cross(normal, u)))
        flat = [(f.solid, shapely.make_valid(shapely.Polygon(f.ring @ axes, [h @ axes for h in f.holes])))
                for f in faces]
        for (a, pa), (b, pb) in combinations(flat, 2):
            if a != b and pa.intersection(pb).area > 1e-9:
                pairs.add((min(a, b), max(a, b)))
    return sorted(pairs)


def _judge(result: Result, solids: SolidSet, table: list[dict], pictures: list[bytes], own: list[bytes]) -> None:
    result.counts = (len(table), len(solids.solids))
    result.materials = _material_faults(table, solids.solids)
    shown = [(projection, _pixels(viewer_png), _pixels(own_png), viewer_png, own_png)
             for projection, viewer_png, own_png in zip(PROJECTIONS, pictures, own)]
    result.coplanar = coplanar(solids, range(len(solids.solids)))     # z-fights in the viewer: part faults
    for projection, a, b, viewer_png, own_png in shown:
        if a.shape != b.shape:
            raise RuntimeError(f"{projection}: the viewer picture is {a.shape}, the renderer's {b.shape}")
        result.patches[projection], result.wrong[projection], result.areas[projection] = _patches(
            a, b, result.coplanar)
        folder = os.environ.get("OD_FLAT_DUMP")             # a folder for the two pictures of a part that differs
        if folder and result.patches[projection]:
            for side, png in (("viewer", viewer_png), ("renderer", own_png)):
                (Path(folder) / f"{result.name}_{projection}_{side}.png").write_bytes(png)


def compare(viewer: Viewer, scenes: dict, *, renderer_options: dict | None = None,
            mutate: Callable[[SolidSet], SolidSet] | None = None, workers: int = 6) -> list[Result]:
    """Compare each scene of ``scenes`` (name: Scene) in the viewer and in the renderer, in both projections.

    ``mutate`` changes the renderer's solids after the ids and the cameras are set (the mutant tests). One part that
    fails to draw gives its error in its result and does not stop the others."""

    options = dict(renderer_options or {})
    results = {name: Result(name) for name in scenes}
    groups: dict = {}
    for name, scene in scenes.items():
        try:
            solids = scene_solids(scene, renderer_options=options)
            frames = [frame_for(solids, projection) for projection in PROJECTIONS]
        except Exception as error:
            results[name].error = f"{type(error).__name__}: {error}"
            continue
        results[name].solids = solids.solids
        groups.setdefault(solids.constants, []).append((name, scene, solids, frames))
    parts = sum(len(members) for members in groups.values())
    pool = (ProcessPoolExecutor(min(workers, os.cpu_count() or 1), mp_context=multiprocessing.get_context("spawn"))
            if workers > 1 and parts > 1 else None)
    shots = {}
    try:
        for constants, members in groups.items():
            viewer.load((constants, json.dumps(options, sort_keys=True, default=str)),
                        lambda: _renderer(members[0][1], options).render())
            for name, scene, solids, frames in members:
                drawn = mutate(solids) if mutate else solids
                drawn = replace(drawn, faces=[f for f in drawn.faces if drawn.solids[f.solid].kind != "text_decal"])
                own = pool.submit(own_pictures, drawn, frames) if pool else own_pictures(drawn, frames)
                try:
                    renderer = _renderer(scene, options)
                    items = renderer._collect_scene_data()
                    if renderer.page_constants(items) != constants:
                        raise RuntimeError("the page constants differ from the renderer's")
                    shots[name] = (solids, *viewer.flat(items, frames), own)
                except Exception as error:
                    results[name].error = f"{type(error).__name__}: {error}"
        for name, (solids, table, pictures, own) in shots.items():
            try:
                _judge(results[name], solids, table, pictures, own.result() if pool else own)
            except Exception as error:
                results[name].error = f"{type(error).__name__}: {error}"
    finally:
        if pool:
            pool.shutdown(cancel_futures=True)
    return list(results.values())
