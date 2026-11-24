"""Three.js renderer — interactive 3D optical setups in the browser."""

from __future__ import annotations

import copy

import html as _html
import json
import math
import warnings
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping, Sequence

from optodraw.animation3d.payload import build_light_payload, disabled_payload
from optodraw.animation_engine.errors import NotModelledYet
from optodraw.animation_engine.ids import port_id, scene_ids
from optodraw.blender import CAMERA_PRESETS as _BLENDER_CAMERA_PRESETS
from optodraw.core.markup import plain
from optodraw.core.component import Component, Group
from optodraw.core.beam import Beam, FocusingBeam
from optodraw.core.beam_heights import BeamHeights, link_beam_heights
from optodraw.core.routing import Route, WireBond
from optodraw.components.optics.fibers import LEAD_HEIGHT
from optodraw.components.optics.optomech import BEAM_HEIGHT
from optodraw.materials import material_catalog
from optodraw.renderers.capabilities import APPROXIMATE, RenderReport
from optodraw.renderers._scene_data import pack_scene_data

# Three.js CDN (pinned version for reproducibility)
THREEJS_CDN = "https://cdn.jsdelivr.net/npm/three@0.186.0"
THREEJS_VERSION = "0.186.0"
THREEJS_TAG = "r186"  # release tag carrying the examples/jsm addon tree

_JS_DIR = Path(__file__).parent / "js"


def _json_script_safe(obj: Any, **kwargs: Any) -> str:
    """json.dumps for embedding inside an HTML <script> block.

    A raw dump lets a value such as ``</script><script>...`` close the page's
    own script element and run attacker markup. Escaping ``<``, ``>`` and
    ``&`` as \\uXXXX keeps the JSON valid and the payload inert. U+2028 and
    U+2029 are escaped too because they terminate JavaScript source lines.
    """

    kwargs.setdefault("separators", (",", ":"))
    text = json.dumps(obj, **kwargs)
    return (
        text.replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


@lru_cache(maxsize=None)
def _js(name: str) -> str:
    """Read a JavaScript file that ships beside this renderer.

    These used to be thousand-line string literals in this module, where no
    linter, formatter or editor could see them as code. They are files now, and
    the page is still assembled here."""

    return (_JS_DIR / name).read_text(encoding="utf-8")

# The light player (window.odLight): it draws the physics engine's light payload (window.__odLightData) on the
# drawn guides, beams and cables. All physics comes from the payload. Appended after odBuildAll/odRebuild.
_LIGHT_PLAYER_JS = _js("light_player.js")
LOOKS: tuple[str, ...] = ("light", "field")

# Editor selection bridge injected when ThreeJsRenderer(editable=True). It lives
# in the iframe and talks to the editor via postMessage: click a tagged mesh ->
# 'optodraw-select'; the editor pushes 'optodraw-highlight' back. Drag-aware so it
# does not fight OrbitControls.
_EDITOR_BRIDGE_JS = _js("editor_bridge.js")
_SCENE_RESOURCES_JS = _js("scene_resources.js")
_STUDIO_JS = _js("studio_core.js") + "\n" + _js("studio_render.js")
# GTAO reconstructs view positions from depth assuming perspective depth; the viewer writes logarithmic depth
# (d = log2(1 + w) / log2(far + 1)). The patch rebuilds the view position from the linear view depth.
_GTAO_LOG_DEPTH_JS = r"""
      for (const shader of [GTAOShader, PoissonDenoiseShader]) {
        shader.uniforms.odLogFar = { value: 1.0 };
        let fs = shader.fragmentShader.replace('uniform mat4 cameraProjectionMatrixInverse;',
          'uniform mat4 cameraProjectionMatrixInverse;\nuniform float odLogFar;');
        fs = fs.replace(/vec3 getViewPosition\(\s*const in vec2 screenPosition,\s*const in float depth\s*\)\s*\{[\s\S]*?return viewSpacePosition\.xyz \/ viewSpacePosition\.w;\s*\}/,
          'vec3 getViewPosition( const in vec2 screenPosition, const in float depth ) {\n' +
          '  float viewZ = -(exp2(depth * odLogFar) - 1.0);\n' +
          '  vec4 p = cameraProjectionMatrixInverse * vec4(screenPosition * 2.0 - 1.0, -1.0, 1.0);\n' +
          '  vec3 nearPoint = p.xyz / p.w;\n' +
          '  return nearPoint * (viewZ / nearPoint.z);\n}');
        fs = fs.replace('return perspectiveDepthToViewZ(depth, cameraNear, cameraFar);', 'return -(exp2(depth * odLogFar) - 1.0);');
        shader.fragmentShader = fs;
      }
      const gtao = new GTAOPass(scene, camera, window.innerWidth, window.innerHeight);
      gtao.gtaoMaterial.uniforms.odLogFar.value = Math.log2(camera.far + 1.0);
      gtao.pdMaterial.uniforms.odLogFar.value = Math.log2(camera.far + 1.0);
      gtao.blendIntensity = 0.85;
      composer.addPass(gtao);
      window.__odGTAO = gtao;"""

# Camera preset names are kept in lockstep with the Blender pipeline so that
# scene metadata, docs, and tests can refer to the same canonical labels.
# The actual direction vectors below are expressed in Three.js coordinates
# (Y-up, looking back toward the scene origin).
CAMERA_PRESETS: tuple[str, ...] = tuple(_BLENDER_CAMERA_PRESETS)

_THREEJS_CAMERA_DIRECTIONS: dict[str, tuple[float, float, float]] = {
    "top": (0.0, 1.0, 0.0001),
    "isometric": (0.75, 0.62, 1.0),
    "side": (1.0, 0.25, 0.0),
    "front": (0.0, 0.18, 1.0),
    "cross_section": (0.0, 0.04, -1.0),
    "free_space_table": (0.45, 0.32, -0.85),
}

# Friendly labels shown on toolbar buttons.
_CAMERA_PRESET_LABELS: dict[str, str] = {
    "top": "Top",
    "isometric": "Isometric",
    "side": "Side",
    "front": "Front",
    "cross_section": "Cross-section",
    "free_space_table": "Free-space table",
}

LIGHTING_PRESETS: tuple[str, ...] = ("studio", "publication", "dramatic")

_LIGHTING_PRESET_CONFIGS: dict[str, dict[str, Any]] = {
  "studio": {
    "fogDensity": 0.0012,
    "toneMappingExposure": 1.2,
    "hemiSky": "0xffffff",
    "hemiGround": "0xd8dee6",
    "hemiIntensity": 1.1,
    "ambientColor": "0xffffff",
    "ambientIntensity": 1.05,
    "keyColor": "0xffffff",
    "keyIntensity": 1.8,
    "keyPosition": (30, 50, 40),
    "fillColor": "0xfff6e8",
    "fillIntensity": 1.0,
    "fillPosition": (-20, 25, -20),
    "rimColor": "0xdde9ff",
    "rimIntensity": 0.65,
    "rimPosition": (10, 18, 32),
    "bloomStrength": 0.18,
    "bloomRadius": 0.24,
    "bloomThreshold": 0.72,
  },
  "publication": {
    "fogDensity": 0.00075,
    "toneMappingExposure": 1.05,
    "hemiSky": "0xffffff",
    "hemiGround": "0xe6edf5",
    "hemiIntensity": 1.25,
    "ambientColor": "0xffffff",
    "ambientIntensity": 0.85,
    "keyColor": "0xffffff",
    "keyIntensity": 2.15,
    "keyPosition": (36, 54, 34),
    "fillColor": "0xf8efe2",
    "fillIntensity": 0.72,
    "fillPosition": (-34, 22, -26),
    "rimColor": "0xd7e7ff",
    "rimIntensity": 0.95,
    "rimPosition": (16, 22, 38),
    "bloomStrength": 0.1,
    "bloomRadius": 0.18,
    "bloomThreshold": 0.86,
  },
  "dramatic": {
    "fogDensity": 0.0016,
    "toneMappingExposure": 1.32,
    "hemiSky": "0xeaf2ff",
    "hemiGround": "0x1e293b",
    "hemiIntensity": 0.74,
    "ambientColor": "0xdbeafe",
    "ambientIntensity": 0.48,
    "keyColor": "0xffffff",
    "keyIntensity": 2.35,
    "keyPosition": (26, 58, 24),
    "fillColor": "0xffedd5",
    "fillIntensity": 0.35,
    "fillPosition": (-38, 18, -30),
    "rimColor": "0x93c5fd",
    "rimIntensity": 1.35,
    "rimPosition": (18, 24, 42),
    "bloomStrength": 0.24,
    "bloomRadius": 0.32,
    "bloomThreshold": 0.68,
  },
}

_RENDER_QUALITIES: tuple[str, ...] = ("interactive", "publication")


def list_camera_presets() -> list[str]:
    """Return the canonical Three.js camera preset names."""

    return list(CAMERA_PRESETS)


def list_lighting_presets() -> list[str]:
  """Return built-in Three.js lighting preset names."""

  return list(LIGHTING_PRESETS)


_FONT_LINKS = """<link rel="preconnect" href="https://fonts.googleapis.com"/>
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin="anonymous"/>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap"/>
"""


@dataclass(frozen=True)
class PageConstants:
    """The constants the 3D page writes into its script. The vector 3D renderer reads the same values."""

    beam_plane: float          # BEAM_PLANE
    board_top: float           # BOARD_TOP: the tallest table, breadboard or baseplate top
    chip_z: float              # CHIP_Z: schematic chip parts are drawn this much taller
    chip_lift: float           # CHIP_LIFT: 8.2 on a chip on a bench, else 0
    mixed: bool                # MIXED: chip and bench content in one scene
    on_chip: bool              # IS_ONCHIP
    lift_meshes: bool          # liftMeshesToTable: only on a free-space page
    show_grid: bool
    show_chip_base: bool
    has_user_die: bool
    lead_height: float         # CABLE_Y: the height of a cable over the table


# On-chip dies, imported models, electronics and instruments stand on the table:
# they never get the free-space optical post or the beam-plane lift.
_NON_BEAM_PLANE_CATEGORIES = frozenset({"models", "on_chip", "electronics", "instruments"})


def is_beam_plane_optic(node: Component, category: str, platform: str = "free_space") -> bool:
    """True for free-space optics/devices that sit at the optical beam plane, on the post the viewer builds.

    The 3D renderer places these at a constant axis height (with a uniform post
    to the table) so the whole light path is coplanar. GDS, on-chip and electronics
    parts sit flat on the table, not on a post. ``category`` is
    the part's registry category; ``platform`` is the scene's."""

    ctype = getattr(node, "component_type", "")
    if getattr(node, "lies_on_table", False):
        return False  # a fibre part lies on the table, where its fibre cables run
    if ctype in {
        "Beam", "FocusingBeam", "Route", "WaveguideRoute", "FiberRoute",
        "Grid", "OpticalTable", "Breadboard", "Baseplate", "OpticalPost", "PlatformMount",
        "TranslationStage", "RotationStage", "Periscope", "KinematicMount", "Cryostat",
        "GDSModel", "CustomModel",
    }:
        return False  # a carrier (table, baseplate, post, stage, kinematic mount) sits flat; optics mount on top
    if category in _NON_BEAM_PLANE_CATEGORIES:
        return False
    # Free-space bench instruments (lasers, detectors, cameras, ...) belong on
    # posts at the beam plane even in mixed and chip scenes, whatever the scene
    # platform (they lack free-space physics_metadata).
    if category in {"optics", "devices"}:
        return True
    meta = node.physics_metadata() if hasattr(node, "physics_metadata") else {}
    if isinstance(meta, dict) and meta.get("domain") == "free_space":
        return True
    return platform == "free_space"


def three_euler(rotation_deg: Any) -> list[float]:
    """A part's rotation (degrees about x, y, z of the table frame, z up, applied as Rz Ry Rx) as the three.js
    Euler angles (order XYZ, y up) of the same turn. A turn about z alone is the yaw (0, z, 0)."""

    ax, ay, az = (math.radians(float(v)) for v in (rotation_deg.x, rotation_deg.y, rotation_deg.z))
    cx, sx, cy, sy, cz, sz = math.cos(ax), math.sin(ax), math.cos(ay), math.sin(ay), math.cos(az), math.sin(az)
    m = [[cz * cy, cz * sy * sx - sz * cx, cz * sy * cx + sz * sx],
         [sz * cy, sz * sy * sx + cz * cx, sz * sy * cx - cz * sx],
         [-sy, cy * sx, cy * cx]]
    # the table frame (x, y, z up) seen in three.js (x, y up, z = -y): M3 = P M P^T, P = [[1,0,0],[0,0,1],[0,-1,0]]
    t = [[m[0][0], m[0][2], -m[0][1]],
         [m[2][0], m[2][2], -m[2][1]],
         [-m[1][0], -m[1][2], m[1][1]]]
    y = math.asin(max(-1.0, min(1.0, t[0][2])))
    if abs(t[0][2]) < 0.9999999:
        return [math.atan2(-t[1][2], t[2][2]), y, math.atan2(-t[0][1], t[0][0])]
    return [math.atan2(t[2][1], t[1][1]), y, 0.0]


class ThreeJsRenderer:
    """Renders a Scene to a self-contained HTML file with Three.js."""

    def __init__(self, scene, **kwargs):
        self.scene = scene
        self.strict: bool = kwargs.get("strict", False)
        self.offline: bool = kwargs.get("offline", False)
        self.report = RenderReport()
        # Effective platform: an explicit "on_chip" flag wins, but a scene whose
        # drawable content is entirely on-chip is treated as a chip even when the
        # meta flag was left at the "free_space" default — so a chip system built
        # in a scratch workspace still gets its die + carrier base in 3D.
        self.platform = self._effective_platform()
        # A user-placed ChipSubstrate IS the die — the auto base then draws only
        # the dark carrier underneath it, never a duplicate die slab.
        self.has_user_die = any(
            getattr(node, "component_type", "") == "ChipSubstrate" for node in scene.walk()
        )
        # Scene meta ``chip_base: false`` turns the auto base off entirely.
        self.show_chip_base = bool(kwargs.get("show_chip_base", True))
        self.camera_distance = kwargs.get("camera_distance", 80)
        self.background = kwargs.get("background", "#f4f6f8")
        self.show_grid = kwargs.get("show_grid", True)
        # Optical (beam) height: the constant axis height free-space optics rise to on
        # their posts. Adjustable per scene; all posts/optics/beams scale together.
        self.beam_height = max(4.0, min(float(kwargs.get("beam_height", BEAM_HEIGHT)), 60.0))
        self._heights = BeamHeights()  # filled per render: the height of each run between periscopes
        self._sids: dict[int, str] = {}  # filled per render: the engine's id of each part
        # Schematic chip parts are drawn taller in 3D: silicon 0.55 high under parts 20 to 400 long read
        # flat. None means automatic (see _chip_height); true-size parts and GDS models keep their heights.
        scale = kwargs.get("chip_height_scale")
        self.chip_height_scale = None if scale is None else max(1.0, min(float(scale), 10.0))
        # Atmospheric fog is off by default: its colour is the background, so on large
        # (mm-scale chip) scenes it washes everything to white. Opt in for free-space mood.
        self.show_fog = kwargs.get("show_fog", False)
        # 3D world/environment preset: "light" (neutral studio gradient) or "dark"
        # (charcoal studio). Switchable at runtime via the World toolbar buttons.
        self.world = kwargs.get("world", "light")
        self.show_labels = kwargs.get("show_labels", False)
        self.orbit_controls = kwargs.get("orbit_controls", True)
        self.show_export_controls = kwargs.get("show_export_controls", True)
        # The light starts off: the page's Light button (or the editor's Animate) turns it on; animate=True starts it.
        self.animate = bool(kwargs.get("animate", False))
        # The light comes from the physics engine: its look, and the engine's parameters and inputs as given.
        self.look = str(kwargs.get("look", "light"))
        if self.look not in LOOKS:
            raise ValueError(f"look must be one of: {', '.join(LOOKS)}.")
        self.params: dict | None = kwargs.get("params")
        self.inputs: list | None = kwargs.get("inputs")
        # The tour always comes with the light; its drive tables (a drive that swings at each driven stop) only on
        # request: they take one engine solve per sample. Without them the tour keeps the drives as set.
        self.tour_drives = bool(kwargs.get("tour_drives", False))
        # A given Tour replaces the saved or automatic one. ``video`` (optodraw.animation3d.video) makes the page a
        # recording stage: no controls, no loop, seeded random numbers, and the tour driven frame by frame.
        self.tour = kwargs.get("tour")
        self.video: dict[str, Any] | None = dict(kwargs["video"]) if kwargs.get("video") else None
        # Editor integration (opt-in): tag meshes with component ids and add a
        # raycast -> postMessage selection bridge so the editor can sync 2D<->3D.
        self.editable = kwargs.get("editable", False)
        self.component_ids: dict[int, str] = dict(kwargs.get("component_ids", {}))
        camera_preset = str(kwargs.get("camera_preset", "isometric")).strip().lower().replace("-", "_")
        if camera_preset not in _THREEJS_CAMERA_DIRECTIONS:
            raise ValueError(
                f"camera_preset must be one of: {', '.join(CAMERA_PRESETS)}."
            )
        self.camera_preset = camera_preset
        # A camera direction (x, y, z), world axes with z up, from the target toward the camera: it overrides
        # the preset's first view.
        direction = kwargs.get("camera_direction")
        self.camera_direction = None
        if direction is not None:
            values = [float(v) for v in direction]
            if len(values) != 3 or not all(math.isfinite(v) for v in values) or not any(values):
                raise ValueError("camera_direction must be three finite numbers, not all zero.")
            self.camera_direction = (values[0], values[2], -values[1])        # three.js is y up
        lighting_preset = str(kwargs.get("lighting_preset", "studio")).strip().lower().replace("-", "_")
        if lighting_preset not in _LIGHTING_PRESET_CONFIGS:
          raise ValueError(
            f"lighting_preset must be one of: {', '.join(LIGHTING_PRESETS)}."
          )
        self.lighting_preset = lighting_preset
        render_quality = str(kwargs.get("render_quality", "interactive")).strip().lower().replace("-", "_")
        if render_quality not in _RENDER_QUALITIES:
          raise ValueError(
            f"render_quality must be one of: {', '.join(_RENDER_QUALITIES)}."
          )
        self.render_quality = render_quality
        # live-view quality: "high" adds ambient occlusion (GTAO), "fast" leaves it out for weak GPUs
        quality = str(kwargs.get("quality", "high")).strip().lower()
        if quality not in ("high", "fast"):
            raise ValueError("quality must be one of: high, fast.")
        self.quality = quality
        postprocessing = kwargs.get("postprocessing", False)
        self.postprocessing = bool(postprocessing)
        self.postprocessing_options = dict(postprocessing) if isinstance(postprocessing, Mapping) else {}
        self.material_preset_overrides: dict[str, dict[str, Any]] = {
            str(key): dict(value)
            for key, value in (kwargs.get("material_preset_overrides") or {}).items()
        }
        self.layer_legend: list[dict[str, str]] | None = self._normalize_legend(
            kwargs.get("layer_legend")
        )
        # The floor stays (it catches shadows); its grid of tile lines is off unless asked for.
        self.floor_grid = bool(kwargs.get("floor_grid", False))
        # Capture mode (optodraw.renderers.capture3d): render once at a set size and background,
        # write the PNG into the page, no panels and no animation loop.
        capture = kwargs.get("capture")
        self.capture: dict[str, Any] | None = dict(capture) if capture else None
        if self.capture:
            self.show_export_controls = False
            self.show_labels = bool(self.capture.get("labels", False))
        # world "none": no background and no floor (a transparent canvas)
        self.transparent_world = self.world == "none" or bool(self.capture and self.capture.get("background") == "none")

    @staticmethod
    def _normalize_legend(
        legend: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None,
    ) -> list[dict[str, str]] | None:
        """Coerce a layer legend input into a sorted list of swatch entries."""

        if legend is None:
            return None
        entries: list[dict[str, str]] = []
        if isinstance(legend, Mapping):
            iterator = legend.items()
        else:
            iterator = ((entry.get("name"), entry) for entry in legend)
        for name, value in iterator:
            label = ""
            color = "#888888"
            description = ""
            if isinstance(value, Mapping):
                label = str(value.get("label") or value.get("name") or name or "").strip()
                color = str(value.get("color") or value.get("fill") or "#888888")
                description = str(value.get("description") or "").strip()
            elif isinstance(value, str):
                label = str(name or "").strip()
                color = value
            else:
                continue
            if not label and name is not None:
                label = str(name).strip()
            if not label:
                continue
            entries.append({"label": label, "color": color, "description": description})
        return entries or None

    def render(self, filename: str | None = None, *, offline: bool | None = None) -> str:
        """Generate the full HTML string. Optionally write to file.

        ``offline=True`` (requires ``filename``) additionally writes a
        sibling ``<stem>_assets/`` directory with pinned 3D assets and
        rewrites the page to load them by relative path — see
        :mod:`optodraw.renderers.offline_assets`. May also be set through
        the constructor, so ``scene.render_threejs(path, offline=True)`` works.
        """
        from optodraw.renderers.offline_assets import bundle_offline_assets, rewrite_html_offline

        want_offline = self.offline if offline is None else offline
        scene_data = self._collect_scene_data()
        html = self._build_html(scene_data)
        if filename:
            Path(filename).write_text(html, encoding="utf-8")
            if want_offline:
                stem = Path(filename).stem or "scene"
                assets = Path(filename).parent / f"{stem}_assets"
                bundle_offline_assets(assets)
                html = rewrite_html_offline(html, assets.name)
                Path(filename).write_text(html, encoding="utf-8")
        elif want_offline:
            raise ValueError("offline=True needs a filename to place the assets beside")
        return html

    def _collect_scene_data(self) -> list[dict]:
        """Walk the scene graph and collect 3D geometry data."""
        # a periscope and the parts after it share one beam height: either side sets it, the other follows
        nodes = list(self.scene.walk())
        self._heights = link_beam_heights(
            [n for n in nodes if isinstance(n, Beam)], self.beam_height,
            parts=[n for n in nodes if getattr(n, "lifts_beam", False) or self._is_beam_plane_optic(n)])
        self._sids = scene_ids(self.scene)            # the engine's part ids: the light payload names its hosts by them
        items = []
        self._walk(self.scene.root, items)
        cladding = self._cladding_entry(items)
        if cladding is not None:
            items.append(cladding)
        return items

    def _cladding_entry(self, items: list[dict]) -> dict[str, Any] | None:
        """The foundry stack's upper cladding over the chip parts, one clear entry that the page and the vector view
        both draw: from the top of the lower cladding to the top of the fill, in the fill's material, over the box
        round the parts and their routes. Each solid fills its own place in it (the cladding fills round the
        cores), a metal that rises through it leaves its own hole, and each pad is etched open down to its top.
        Bands of one plan are one solid. None with no foundry stack, or with no numpy or shapely."""

        part = next((n for n in self.scene.walk() if hasattr(n, "_draw_layer_stack")), None)
        films = part._foundry_core() if part is not None else None
        if films is None or films.cladding is None:
            return None
        try:
            import shapely

            from optodraw.renderers.vector3d_scene import place_mesh, strip_solids
            from optodraw.renderers.vector3d_solids import SolidSet, Vector3DError
        except ImportError:
            return None
        from dataclasses import replace

        stack = part._draw_layer_stack()
        scale = part._draw_thickness() / float(part._foundry_heights().get("chip_thickness", part.chip_thickness))
        bottom, top = films.cladding[0] * scale, films.cladding[1] * scale
        built = SolidSet(constants=replace(self.page_constants(items), chip_z=1.0, chip_lift=0.0))   # draw units
        parts = [item for item in items if item.get("chip") and not item.get("cable")
                 and (item.get("type") == "route" or (item.get("type") == "mesh" and item.get("zScale")))]
        for item in parts:
            try:
                if item["type"] == "mesh":
                    place_mesh(item, built.constants, {}, built)
                elif len(item.get("points") or []) >= 2:
                    strip_solids(item, built.constants, {}, built)
            except Vector3DError:               # a shape the vector view cannot draw stays inside the cladding
                continue
        faces: dict[int, list] = {}
        for face in built.faces:
            faces.setdefault(face.solid, []).append(face)
        plans, voids = [], []                  # voids: (plan in world x and z, bottom, top)
        for solid in built.solids:
            own = faces.get(solid.id, [])
            flat = [shapely.make_valid(shapely.Polygon(f.ring[:, [0, 2]], [h[:, [0, 2]] for h in f.holes]))
                    for f in own if abs(f.normal[1]) > 1e-6]
            if not flat:
                continue
            plan = shapely.union_all(flat)
            low = min(float(f.ring[:, 1].min()) for f in own)
            high = max(float(f.ring[:, 1].max()) for f in own)
            plans.append(plan)
            if low < top - 1e-9 and high > bottom + 1e-9:
                voids.append((plan, max(low, bottom), min(high, top)))
            if abs(low - stack["pad_z"]) < 1e-6 and high < top:     # a pad: opened down to it (a pad plate may
                voids.append((plan, high, top))                       # carry no preset, so its level names it)
        if not plans:
            return None
        x0, z0, x1, z1 = shapely.union_all(plans).bounds
        rim = max(2.0, 0.04 * max(x1 - x0, z1 - z0))                  # as a GDSModel's cladding runs past its layout
        foot = shapely.box(x0 - rim, z0 - rim, x1 + rim, z1 + rim)
        edges: list[float] = []                # each level once, as a solid has it: a rounded one leaves a sliver
        for z in sorted({bottom, top, *(z for _, a, b in voids for z in (a, b))}):
            if not edges or z - edges[-1] > 1e-9:
                edges.append(z)
        bands: list[list] = []                 # [region, bottom, top]
        for za, zb in zip(edges, edges[1:]):
            active = [plan for plan, a, b in voids if a < (za + zb) / 2.0 < b]
            # closed by 0.05: the hair gaps where a part's segments meet hold no slivers of cladding; a sharp tip
            # the closing blunts stays held
            region = foot
            if active:
                held = shapely.union_all(active)
                region = foot.difference(held.union(held.buffer(0.05, join_style="mitre").buffer(-0.05,
                                                                                                 join_style="mitre")))
            if bands and abs(bands[-1][2] - za) < 1e-9 and bands[-1][0].equals(region):
                bands[-1][2] = zb
            else:
                bands.append([region, za, zb])
        centres = [item["position"] for item in parts if item.get("zScale")] or [[0.0, 0.0, 0.0]]
        px = sum(float(p[0]) for p in centres) / len(centres)   # inside the parts' spread: the chip height keeps
        pz = sum(float(p[2]) for p in centres) / len(centres)

        def ring(coords) -> list[tuple[float, float, float]]:
            return [(x - px, pz - z, 0.0) for x, z in list(coords)[:-1]]   # world x, z to the shape's x, y

        # the viewer's clear oxide over a GDS chip; no transmission pass: on the faces where a metal stands in the
        # cladding it left pixels with no colour in the page
        material = {"color": films.fills[films.cladding[2]], "preset": films.cladding[2], "opacity": 0.12,
                    "transmission": 0.0, "depthWrite": False}
        children = []
        for region, za, zb in bands:
            for piece in shapely.get_parts(region):
                if piece.geom_type != "Polygon" or piece.area <= 1e-9:
                    continue
                child = {"shape": "extruded_polygon", "points": ring(piece.exterior.coords), "height": zb - za,
                         "position": [0.0, za, 0.0], "material": dict(material)}
                if piece.interiors:
                    child["holes"] = [ring(hole.coords) for hole in piece.interiors]
                children.append(child)
        return {"sid": None, "label": "", "position": [px, 0.0, pz], "rotation": [0.0, 0.0, 0.0], "type": "mesh",
                "geometry": {"shape": "group", "children": children}, "chip": True, "zScale": True}

    def _light_payload(self) -> dict[str, Any] | None:
        """The engine's light for the player, with its tour (and, with ``tour_drives``, the drive tables of the tour's
        driven stops), or None in a capture (a still never shows the light nor the tour).

        A scene with a part the engine cannot model yet as drawn still renders: its light is off, with a warning
        that says why. Every other refusal raises, and so does any refusal when the caller gave ``params`` or
        ``inputs``. The editable page embeds a light-off payload: building the real one is slow on a large chip."""

        if self.capture:
            return None
        if self.editable:       # the editor fetches the payload (/api/scene3d?light=1) when the light is on
            return disabled_payload([], look=self.look)
        try:
            return build_light_payload(self.scene, params=self.params, inputs=self.inputs, look=self.look,
                                       drives="tour" if self.tour_drives else None, tour=self.tour)
        except NotModelledYet as error:
            if self.params is not None or self.inputs is not None:
                raise
            notice = f"no light: {error}"
            warnings.warn(notice, RuntimeWarning, stacklevel=2)
            return disabled_payload([notice], look=self.look)

    def _chip_stack(self) -> dict[str, float] | None:
        """The process stack of the scene's chip parts (the first that has one), or None with no chip."""

        if not hasattr(self, "_chip_stack_cache"):
            part = next((n for n in self.scene.walk() if hasattr(n, "_draw_layer_stack")), None)
            self._chip_stack_cache = part._draw_layer_stack() if part is not None else None
        return self._chip_stack_cache

    def _is_chip_item(self, node: Component) -> bool:
        """A part on the die: a chip part, an imported layout, or on-chip electronics (pads) with a chip in the
        scene. The die fits round these, and a wire between two of them is chip metal."""

        if getattr(node, "chip_thickness", None) is not None or getattr(node, "component_type", "") == "GDSModel":
            return True
        from optodraw.registry import component_registry

        spec = component_registry().get(getattr(node, "component_type", ""))
        return (spec is not None and spec.category == "electronics" and spec.platform == "on_chip"
                and self._chip_stack() is not None)

    def _pad_on_the_stack(self, node: Component, geometry: dict[str, Any]) -> dict[str, Any]:
        """An on-chip pad on the pad layer, the top of the stack, with the route up to it at each port, where a
        wire on the metal lands: a short landing from the port and a small via up to the pad. A heater pad's
        meander lies on the heater layer; only its pads go up."""

        stack = self._chip_stack()
        if stack is None or getattr(node, "component_type", "") not in self._ON_CHIP_PADS:
            return geometry
        from optodraw.components.onchip.geometry import _pad_route

        def solids(item, offset=(0.0, 0.0, 0.0)):
            position = item.get("position") or [0.0, 0.0, 0.0]
            here = tuple(o + float(p) for o, p in zip(offset, position))
            if item.get("shape") == "group":
                for child in item.get("children", []):
                    yield from solids(child, here)
            else:
                yield item, here

        parts = list(solids(geometry))
        base = min((at[1] - float(item.get("height", 0.0)) / 2.0 for item, at in parts), default=0.0)
        lift = stack["pad_z"] - base
        plates = [(at[0], at[2], float(item["width"]), float(item["depth"])) for item, at in parts
                  if item.get("shape") == "box" and abs(at[1] - float(item["height"]) / 2.0 - base) < 1e-6]
        widest = max((min(w, d) for _, _, w, d in plates), default=0.0)
        metal_top = stack["metal_z"] + stack["metal_height"]
        pads = [(x, z, w, d) for x, z, w, d in plates if min(w, d) >= 0.25 * widest]   # thinner: a heater, a lead
        routes = []
        for port in node.ports().values():           # where a wire on the metal lands: a small via up to its pad
            px, py = port.center.x, port.center.y
            home = min(pads, default=None, key=lambda p: max(abs(px - p[0]) - p[2] / 2.0, abs(-py - p[1]) - p[3] / 2.0))
            if home is not None:
                x, z, w, d = home
                routes += _pad_route(w, d, x, -z, stack, below=metal_top, arrive=(px, py))

        def over_a_pad(at) -> bool:
            return any(abs(at[0] - x) <= w / 2.0 + 1e-6 and abs(at[2] - z) <= d / 2.0 + 1e-6 for x, z, w, d in pads)

        # the pads go up to the pad layer; the rest (a heater pad's meander) lies on the heater layer
        placed = [{**item, "position": [at[0], at[1] + (lift if over_a_pad(at) else stack["heater_z"] - base), at[2]]}
                  for item, at in parts]
        return {"shape": "group", "children": [*placed, *routes]}

    _ON_CHIP_PADS = frozenset({"ElectricalPad", "GSGProbePad", "HeaterPad"})

    def _geometry_3d(self, node: Component) -> dict[str, Any]:
        """The part's 3D model; a part that builds the bench beam height into it (a periscope, a cryostat)
        and was given none gets the height the beam runs at there, so its mirrors and windows meet it. A
        periscope takes the rise its raised run asks for. An on-chip pad stands on the stack's pad layer."""

        if getattr(node, "component_type", "") in self._ON_CHIP_PADS:
            return self._pad_on_the_stack(node, node.geometry_3d())
        heights = self._heights
        node = heights.part(node)
        beam = self.beam_height + heights.lift(node)
        if getattr(node, "_scene_beam", False) and abs(float(node.beam_height) - beam) > 1e-9:
            node = copy.copy(node)
            node.beam_height = beam
        geometry = node.geometry_3d()
        definition = getattr(node, "_part_definition", None)
        if not geometry and definition is not None:
            from optodraw.parts import UserPart

            geometry = UserPart(definition, parameters=dict(node._part_parameters)).geometry_3d()
        return geometry

    def _is_beam_plane_optic(self, node: Component) -> bool:
        return is_beam_plane_optic(node, self._category_for(getattr(node, "component_type", "")), self.platform)

    def _chip_height(self, scene_data: list[dict]) -> float:
        """How much taller the schematic chip parts are drawn: the number given, else 2.5 for a part or a
        small chip, rising with the chip's size (the spread of its parts plus one part) up to 4.5. At 2.5
        the guides of a 400-unit chip still read as lines; above 4.5 its rings start to look like tubes."""

        if self.chip_height_scale is not None:
            return self.chip_height_scale
        points = [item["position"] for item in scene_data if item.get("zScale")]
        if not points:
            return 2.5
        span = max(max(p[0] for p in points) - min(p[0] for p in points),
                   max(p[2] for p in points) - min(p[2] for p in points)) + 40.0
        return round(min(max(2.5 * math.sqrt(span / 120.0), 2.5), 4.5), 2)

    def _scales_with_chip(self, node: Component) -> bool:
        """True for the schematic parts on a die, drawn ``chip_height_scale`` taller in 3D."""

        ctype = getattr(node, "component_type", "")
        if ctype == "GDSModel" or getattr(node, "render_physical", False):
            return False
        if getattr(node, "chip_thickness", None) is not None:
            return True
        from optodraw.registry import component_registry

        spec = component_registry().get(ctype)
        return spec is not None and spec.category == "electronics" and spec.platform == "on_chip"

    def _category_for(self, ctype: str) -> str:
        """Return a component type's registry category (cached, empty if unknown)."""

        cache = getattr(self, "_category_cache", None)
        if cache is None:
            from optodraw.registry import component_registry

            cache = {name: spec.category for name, spec in component_registry().items()}
            self._category_cache = cache
        return cache.get(ctype, "")

    def _walk(self, node: Component, items: list, parent_id: str = ""):
        if isinstance(node, Group):
            for child in node.children:
                self._walk(child, items, parent_id)
            return

        wt = node.world_transform
        entry: dict[str, Any] = {
            "sid": self._sids.get(id(node)),
            "label": plain(node.label),
            "position": [wt.position.x, wt.position.z, -wt.position.y],  # Y-up for Three.js
            "rotation": three_euler(wt.rotation_deg),
        }
        if abs(wt.rotation_deg.x) > 1e-9 or abs(wt.rotation_deg.y) > 1e-9:
            entry["tilted"] = True        # turned out of the table plane: the post goes under its lowest point
        sx = -1.0 if getattr(node, "flip_horizontal", False) else 1.0
        sz = -1.0 if getattr(node, "flip_vertical", False) else 1.0
        if sx != 1.0 or sz != 1.0:
          entry["localScale"] = [sx, 1.0, sz]
        if self.editable:
            entry["componentId"] = self.component_ids.get(id(node))
        ctype_entry = getattr(node, "component_type", "")
        if self._is_chip_item(node):
            entry["chip"] = True  # the auto die fits around CHIP items only
        if self._is_beam_plane_optic(node):
            entry["beamPlane"] = True
            lift = self._heights.lift(node)
            if lift:
                entry["lift"] = lift  # above the bench beam plane: the run after a periscope
            entry["baseMount"] = getattr(node, "base_mount", "post")  # "post" | "stage" | "xyz_stage" | "rotation_stage" | "post_beam" | "none"
            mh = getattr(node, "mount_height", None)
            if mh is not None:
                try:
                    entry["mountHeight"] = float(mh)
                except Exception:
                    pass
            try:
                world_ports = node.world_ports()
            except Exception:
                world_ports = {}
            if world_ports:
                # world (x, y) -> 3D (x, BEAM_PLANE, -y); markers drawn on the plane
                entry["ports3d"] = [[p.center.x, -p.center.y, lift] for p in world_ports.values()]

        if isinstance(node, Beam) and getattr(node, "envelope", False):
            return  # 2D figure device: the 3D view already shows the real bundle
        if isinstance(node, Beam):
            pts = node.resolve_points(self._heights)
            entry["type"] = "beam"
            entry["points"] = [[p[0], p[2] if len(p) > 2 else 0, -p[1]] for p in pts]
            entry["color"] = node.color
            entry["width"] = node.display_width  # wavelength-scaled (IR wider)
            entry["anchorSids"] = self._anchor_sids(node.anchors)   # which way the light runs on each beam segment
        elif isinstance(node, WireBond):
            geo = node.geometry_3d(self._geometry_3d)              # each end on its pad as this page draws the pad
            x, _, z = geo["points"][0]
            entry["type"], entry["position"] = "mesh", [x, 0.0, z]  # at its first pad: the chip's spread stays as it was
            entry["geometry"] = {**geo, "points": [[p[0] - x, p[1], p[2] - z] for p in geo["points"]]}
            pad = node.start_component
            # shortcut: the wire takes the chip height and lift of its first pad; a bond from a chip pad to a part
            # drawn at true height lands off the second pad top. Scale each end in the page if a figure needs that.
            if pad is not None and self._scales_with_chip(pad):
                entry["zScale"] = True
            if pad is not None and self._is_chip_item(pad):
                entry["chip"] = True
        elif isinstance(node, Route):
            pts = node.resolve_points()
            entry["type"] = "route"
            entry["points"] = [[p[0], p[2] if len(p) > 2 else 0, -p[1]] for p in pts]
            entry["color"] = node.color
            entry["width"] = node.width
            if getattr(node, "width2", None):
                entry["width2"] = node.width2
            entry["kind"] = node.kind
            entry["bendRadius"] = float(getattr(node, "bend_radius", 10.0) or 10.0)
            ends = [getattr(node, "start_component", None), getattr(node, "end_component", None)]
            ports = [getattr(node, "start_port", None), getattr(node, "end_port", None)]
            if all(id(c) in self._sids for c in ends) and all(ports):     # the engine's port at each end of the points
                entry["ends"] = [port_id(self._sids[id(c)], str(p)) for c, p in zip(ends, ports)]
            if node.kind == "waveguide":
                entry["chip"] = True  # waveguides are chip content
                # as high as the silicon of the parts it joins, so the joint shows no step
                cores = [c for c in ends if c is not None and hasattr(c, "_draw_thickness")]
                if cores:
                    core = cores[0]._core()
                    entry["stripThick"] = float(cores[0]._draw_thickness())
                    entry["stripZ"] = core["z_offset"]                     # on the level the stack gives the core
                    entry["stripScale"] = self._scales_with_chip(cores[0])
                    # and of its material: a route in another blue showed a band at every joint
                    entry["stripMaterial"] = {"color": core["color"], "preset": core["preset"]}
                    under = cores[0]._slab_under_core()
                    if under is not None:                 # a ridge on a slab: the slab runs under the route too
                        slab = {key: value for key, value in entry.items() if key not in ("sid", "ends", "label", "componentId")}
                        slab.update(width=entry["width"] + 2.0 * under["margin"], stripThick=under["height"],
                                    stripZ=under["z_offset"], stripMaterial={"color": under["color"],
                                                                             "preset": under["preset"]})
                        if entry.get("width2"):
                            slab["width2"] = entry["width2"] + 2.0 * under["margin"]
                        items.append(slab)
            if node.kind in ("electrical", "fiber"):
                # Bench wiring is round CABLE, not chip metal deposition. Fiber is
                # always a cable (it's bench patch cord). A MIXED route — one end
                # on an instrument, one on a chip pad / coupler — stays a cable
                # but DROPS VERTICALLY onto the chip end (probe-landing style).
                ends = [getattr(node, "start_component", None), getattr(node, "end_component", None)]
                is_chip = [c is not None and self._is_chip_item(c) for c in ends]
                mixed = any(is_chip) and not all(is_chip)
                offchip = not any(is_chip) and (any(c is not None for c in ends) or self.platform != "on_chip")
                if node.kind == "fiber" or offchip or mixed:
                    entry["cable"] = True
                    if mixed:
                        entry["cableDrop"] = "start" if is_chip[0] else "end"
                    # a cable runs on the table; an end on a part at the beam height (on a post) rises to its
                    # connector instead of ending at the foot of the post
                    rise = [c is not None and self._is_beam_plane_optic(c) for c in ends]
                    if any(rise):
                        entry["cableRise"] = rise
                elif node.kind == "electrical" and all(is_chip) and ends[0] is not None:
                    entry["chip"] = True  # pad-to-pad chip metal
                    # at the parts' metal level (on their vias), not on the die under their leads
                    stacks = [c for c in ends if hasattr(c, "_draw_layer_stack")]
                    if stacks:
                        stack = stacks[0]._draw_layer_stack()
                        entry["stripThick"], entry["stripZ"] = float(stack["metal_height"]), float(stack["metal_z"])
                        entry["stripScale"] = self._scales_with_chip(stacks[0])
                        entry["stripMaterial"] = {"color": "#d4af37", "preset": "gold"}   # the parts' lead metal
        elif isinstance(node, FocusingBeam):
            # not drawn by the static view; the light player draws its light: world (x, y) -> (x, 0, -y), lifted
            # to the beam plane in the page
            entry["type"] = "fbeam"
            entry["points"] = [[float(p.x), 0, -float(p.y)] for p in node.endpoints()]
            entry["color"] = node.color
            entry["width"] = max(node.width1, node.width2)
            entry["anchorSids"] = self._anchor_sids([node.anchor1, node.anchor2])
        else:
            geo = self._geometry_3d(node)
            if not geo:
                return
            if geo.get("shape") == "external_model":
                entry["geometry"] = geo
                entry["type"] = "external_model"
            else:
                entry["geometry"] = geo
                entry["type"] = "mesh"
                unassigned = node.layers_without_height() if hasattr(node, "layers_without_height") else []
                if unassigned:
                    entry["noHeight"] = unassigned       # left out of the 3D view: the page's note names them
                if self._scales_with_chip(node):
                    entry["zScale"] = True
                self.report.check(
                    "threejs",
                    geo.get("shape"),
                    strict=self.strict,
                    unknown_as=APPROXIMATE,
                    detail=(f"schematic 3D outline on {geo.get('part_name', ctype_entry)}"
                            if geo.get("schematic") else
                            f"3D shape {geo.get('shape')!r} on {ctype_entry or type(node).__name__}"),
                )
                if ctype_entry in ("OpticalTable", "Breadboard", "Baseplate"):
                    entry["board"] = True
                if hasattr(node, "_draw_material_preset"):
                    # the materials of its waveguides, drawn and plain (an MZM draws its arms in plain silicon)
                    entry["guide"] = sorted({node._draw_material_preset(), str(getattr(node, "material_preset", "")),
                                             node._core()["preset"]} - {""})

        items.append(entry)

    def _anchor_sids(self, anchors) -> list[str | None]:
        """The engine id of the part at each beam anchor (None for a coordinate)."""

        parts = [a[0] if isinstance(a, (tuple, list)) and a and isinstance(a[0], Component) else a for a in anchors]
        return [self._sids.get(id(p)) if isinstance(p, Component) else None for p in parts]

    def _effective_platform(self) -> str:
        declared = getattr(self.scene, "platform", "free_space")
        if declared == "on_chip":
            return "on_chip"
        on_chip = free_space = 0
        for node in self.scene.walk():
            ctype = getattr(node, "component_type", "")
            category = self._category_for(ctype)
            if category == "on_chip":
                on_chip += 1
            elif category in {"optics", "devices"}:
                free_space += 1
        return "on_chip" if on_chip and not free_space else declared

    def _stage_config(self) -> dict[str, str | float | bool]:
        if self.platform == "on_chip":
            return {
                "gridColor1": "0xd3d9df",
                "gridColor2": "0xe7ebef",
                "surfaceColor": "0xf8fafc",
                "surfaceRoughness": 0.95,
                "surfaceMetalness": 0.02,
                "surfaceThickness": 0.35,
                "cameraDistanceScale": 1.35,
                "verticalExtentScale": 4.5,
            }
        return {
            "gridColor1": "0xc7c2b6",
            "gridColor2": "0xe2ddd0",
            "surfaceColor": "0xd8d2c3",
            "surfaceRoughness": 0.85,
            "surfaceMetalness": 0.08,
            "surfaceThickness": 1.0,
            "cameraDistanceScale": 1.0,
            "verticalExtentScale": 3.0,
        }

    @staticmethod
    def _geometry_exportable(scene_data: list[dict]) -> bool:
        return any(item.get("type") in ("mesh", "external_model") for item in scene_data)

    def _export_controls_js(
        self,
        scene_spec_json: str,
        geometry_exportable: bool,
        *,
        use_postprocessing: bool,
    ) -> str:
        glb_handler = ""
        if geometry_exportable:
            glb_handler = """
function downloadGlb() {
  if (window.odLight) window.odLight.control('tour', false);   // the tour's see-through copies never reach a file
  const exporter = new GLTFExporter();
  // hide the light so its glow does not end up in the file
  const light = window.odLight;
  const wasEnabled = light ? light.state.enabled : false;
  if (light && light.state.group) { light.state.enabled = false; light.state.group.visible = false; }
  const release = () => { if (light) light.state.enabled = wasEnabled; };
  exporter.parse(
    scene,
    (arrayBuffer) => {
      release();
      const blob = new Blob([arrayBuffer], { type: 'application/octet-stream' });
      const link = document.createElement('a');
      link.download = (document.title || 'optodraw-scene').replace(/ [|] .*$/, '') + '.glb';
      link.href = URL.createObjectURL(blob);
      link.click();
      URL.revokeObjectURL(link.href);
    },
    (error) => { release(); console.error('GLB export failed', error); },
    { binary: true }
  );
}
"""
        camera_directions_json = _json_script_safe(_THREEJS_CAMERA_DIRECTIONS, indent=2)
        screenshot_render = (
            "composer.render();"
            if use_postprocessing
            else "renderer.render(scene, camera);"
        )
        return f"""
// --- Export toolbar and camera presets ---
const sceneSpec = {scene_spec_json};
const geometryExportable = {str(geometry_exportable).lower()};
const cameraPresetDirections = {camera_directions_json};
let viewTarget = new THREE.Vector3(0, 0, 0);
let viewDistance = requestedCameraDistance;

function refreshViewMetrics() {{
  if (hasContentBounds) {{
    viewTarget.copy(contentBounds.getBoundingSphere(new THREE.Sphere()).center);
    viewDistance = odFitDistance(contentBounds, 1.0);
  }}
}}
refreshViewMetrics();

function applyCameraPreset(preset) {{
  const direction = cameraPresetDirections[preset];
  if (!direction) {{
    console.warn('Unknown camera preset', preset);
    return;
  }}
  const d = viewDistance;
  const t = viewTarget;
  const offset = new THREE.Vector3(direction[0], direction[1], direction[2]);
  if (offset.lengthSq() === 0) {{
    return;
  }}
  offset.normalize().multiplyScalar(d);
  camera.position.set(t.x + offset.x, t.y + offset.y, t.z + offset.z);
  camera.lookAt(t);
  controls.target.copy(t);
  controls.update();
}}

function downloadFile(filename, blob) {{
  const link = document.createElement('a');
  link.download = filename;
  link.href = URL.createObjectURL(blob);
  link.click();
  URL.revokeObjectURL(link.href);
}}

// Render the scene at high resolution (supersampled) before saving, so exported PNGs
// are crisp print-quality rather than a screen-resolution grab.
function renderToPng() {{
  const w = window.innerWidth, h = window.innerHeight;
  const prevPixelRatio = renderer.getPixelRatio();
  const scale = Math.max(1, Math.min(3, 4096 / Math.max(w, h)));   // cap longest edge ~4k
  const tw = Math.round(w * scale), th = Math.round(h * scale);
  const hasComposer = (typeof composer !== 'undefined' && composer);
  renderer.setPixelRatio(1);
  renderer.setSize(tw, th, false);
  if (hasComposer) composer.setSize(tw, th);
  camera.aspect = tw / th; camera.updateProjectionMatrix();
  {screenshot_render}
  const dataUrl = renderer.domElement.toDataURL('image/png');
  // restore the interactive viewport
  renderer.setPixelRatio(prevPixelRatio);
  renderer.setSize(w, h, false);
  if (hasComposer) composer.setSize(w, h);
  camera.aspect = w / h; camera.updateProjectionMatrix();
  {screenshot_render}
  labelRenderer.render(scene, camera);
  return dataUrl;
}}

function downloadPngScreenshot() {{
  const baseName = (document.title || 'optodraw-scene').replace(/ [|] .*$/, '');
  downloadFile(baseName + '.png', dataUrlToBlob(renderToPng()));
}}

function dataUrlToBlob(dataUrl) {{
  const [header, data] = dataUrl.split(',');
  const mime = header.match(/:(.*?);/)[1];
  const bytes = atob(data);
  const buffer = new Uint8Array(bytes.length);
  for (let i = 0; i < bytes.length; i++) buffer[i] = bytes.charCodeAt(i);
  return new Blob([buffer], {{ type: mime }});
}}

function downloadSceneJson() {{
  const blob = new Blob([JSON.stringify(sceneSpec, null, 2)], {{ type: 'application/json' }});
  const baseName = (document.title || 'optodraw-scene').replace(/ [|] .*$/, '');
  downloadFile(baseName + '.json', blob);
}}
{glb_handler}
document.getElementById('btn-export-png')?.addEventListener('click', downloadPngScreenshot);
document.getElementById('btn-export-png-clear')?.addEventListener('click', () => {{
  const before = _world;
  applyWorld('none');
  downloadPngScreenshot();
  applyWorld(before);
}});
document.getElementById('btn-export-json')?.addEventListener('click', downloadSceneJson);
if (geometryExportable) {{
  document.getElementById('btn-export-glb')?.addEventListener('click', downloadGlb);
}}
for (const btn of document.querySelectorAll('[data-camera-preset]')) {{
  btn.addEventListener('click', () => applyCameraPreset(btn.dataset.cameraPreset));
}}
for (const btn of document.querySelectorAll('[data-world]')) {{
  btn.addEventListener('click', () => applyWorld(btn.dataset.world));
}}
const _tableColorInput = document.getElementById('world-table-color');
if (_tableColorInput) {{
  _tableColorInput.addEventListener('input', () => {{ const c = _tableColorInput.value; if (window.__odDieMat) window.__odDieMat.color.set(c); else if (tableMat) tableMat.color.set(c); }});
}}
"""

    def _camera_buttons_html(self) -> str:
        rows = []
        for preset in CAMERA_PRESETS:
            label = _CAMERA_PRESET_LABELS.get(preset, preset.replace("_", " ").title())
            slug = preset.replace("_", "-")
            rows.append(
                f'    <button type="button" id="btn-camera-{slug}" data-camera-preset="{preset}">{label}</button>'
            )
        return "\n".join(rows)

    def _resolved_material_catalog(self) -> dict[str, Any]:
        catalog = material_catalog()
        for name, override in self.material_preset_overrides.items():
            base = dict(catalog.get(name, {}))
            base.update(override)
            catalog[name] = base
        return catalog

    def _layer_legend_html(self) -> str:
        if not self.layer_legend:
            return ""
        items: list[str] = []
        for entry in self.layer_legend:
            description = _html.escape(str(entry.get("description") or ""), quote=True)
            title_attr = f' title="{description}"' if description else ""
            color = _html.escape(str(entry["color"]), quote=True)
            label = _html.escape(str(entry["label"]))
            items.append(
                "    <li class=\"layer-legend-item\""
                f"{title_attr}>"
                f'<span class="layer-legend-swatch" style="background:{color}"></span>'
                f"<span class=\"layer-legend-name\">{label}</span></li>"
            )
        body = "\n".join(items)
        return f"""
<div id=\"layer-legend\" data-optodraw-layer-legend=\"true\">
  <div class=\"layer-legend-title\">Layer legend</div>
  <ul class=\"layer-legend-list\">
{body}
  </ul>
</div>
"""

    def _layer_legend_css(self) -> str:
        if not self.layer_legend:
            return ""
        return """
      #layer-legend { position: absolute; bottom: 14px; left: 14px; z-index: 10; background: rgba(255,255,255,0.92); border: 1px solid #e6e9f0; border-radius: 11px; padding: 8px 12px; box-shadow: 0 4px 12px -2px rgba(16,24,40,0.08), 0 2px 4px -2px rgba(16,24,40,0.05); font-size: 12px; max-width: 240px; color: #141b2d; backdrop-filter: blur(8px); }
      #layer-legend .layer-legend-title { font-size: 10px; font-weight: 600; color: #939cab; margin-bottom: 6px; letter-spacing: 0.6px; text-transform: uppercase; }
      #layer-legend .layer-legend-list { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 4px; }
      #layer-legend .layer-legend-item { display: flex; align-items: center; gap: 8px; }
      #layer-legend .layer-legend-swatch { width: 14px; height: 14px; border-radius: 3px; border: 1px solid rgba(38,50,63,0.18); display: inline-block; }
      #layer-legend .layer-legend-name { line-height: 1.2; }
"""

    def _content_flags(self) -> tuple[bool, bool]:
        """(has_chip, has_bench): drives the chip-on-bench mixed 3D layout."""

        skip = {"Beam", "Route", "WaveguideRoute", "FiberRoute", "MetalRoute", "Group", "Grid", "FocusingBeam",
                "OpticalTable", "Breadboard", "Baseplate", "OpticalPost", "PlatformMount", "TranslationStage", "RotationStage"}
        has_chip = has_bench = False
        for n in self.scene.walk():
            ct = getattr(n, "component_type", "")
            if not ct or ct in skip:
                continue
            if self._is_chip_item(n):
                has_chip = True
            else:
                has_bench = True
        return has_chip, has_bench

    def page_constants(self, scene_data: list[dict]) -> PageConstants:
        """The constants of the page for ``scene_data`` (from ``_collect_scene_data``)."""

        # Board top for post placement: tallest table/breadboard/baseplate thickness in the scene.
        # Without a board it stays 0; posts sit on the ground plane.
        board_top = 0.0
        try:
            for node in self.scene.walk():
                if getattr(node, "component_type", "") in ("OpticalTable", "Breadboard", "Baseplate"):
                    try:
                        board_top = max(board_top, float(getattr(node, "thickness", 0.0) or 0.0))
                    except Exception:
                        pass
        except Exception:
            board_top = 0.0
        mixed = all(self._content_flags())
        return PageConstants(
            beam_plane=self.beam_height, board_top=board_top, chip_z=self._chip_height(scene_data),
            chip_lift=8.2 if mixed else 0.0, mixed=mixed, on_chip=self.platform == "on_chip",
            lift_meshes=self.platform == "free_space", show_grid=bool(self.show_grid),
            show_chip_base=self.show_chip_base, has_user_die=self.has_user_die, lead_height=LEAD_HEIGHT)

    def _build_html(self, scene_data: list[dict]) -> str:
        k = self.page_constants(scene_data)
        data_json = "odExpandSceneData(" + _json_script_safe(pack_scene_data(scene_data, copy_records=False), default=str) + ")"
        material_json = _json_script_safe(self._resolved_material_catalog())
        from optodraw.figure.inset import views_note

        views_note_json = _json_script_safe(views_note(self.scene, "3D"))     # the insets: 2D only
        stage = self._stage_config()
        geometry_exportable = self._geometry_exportable(scene_data)
        show_controls = self.show_export_controls
        scene_spec_json = _json_script_safe(self.scene.to_spec(), default=str) if show_controls else ""
        light = self._light_payload()
        light_js = "" if light is None else (
            f"window.__odLightData = {_json_script_safe(light)};\n{_LIGHT_PLAYER_JS}\n"
            "window.odLight.build(window.__odLightData, sceneData);\n"
            + ("window.odLight.setEnabled(true);   // animate=True: the light starts on\n" if self.animate else ""))
        studio_js = _STUDIO_JS                      # the studio light, the Photoreal button and studio captures
        editor_bridge_js = _EDITOR_BRIDGE_JS if self.editable else ""
        editor_imports = (
            "import { TransformControls } from 'three/addons/controls/TransformControls.js';"
            if self.editable
            else ""
        )
        legend_html = self._layer_legend_html()
        legend_css = self._layer_legend_css()
        initial_dir = self.camera_direction or _THREEJS_CAMERA_DIRECTIONS[self.camera_preset]
        lighting = _LIGHTING_PRESET_CONFIGS[self.lighting_preset]
        post_options = dict(lighting)
        post_options.update(self.postprocessing_options)
        shadow_map_size = 4096 if self.render_quality == "publication" else 2048
        if self.render_quality == "publication":
            pixel_ratio = "Math.min(window.devicePixelRatio, 2)"
        elif self.editable:     # the editor's view: a high-DPI screen at 1.5x looks the same and draws far fewer pixels
            pixel_ratio = "Math.min(window.devicePixelRatio, 1.5)"
        else:
            pixel_ratio = "window.devicePixelRatio"
        show_bar = show_controls and not self.editable    # the editor carries these controls in its own toolbar
        toolbar_css = ("""
      /* one slim bar at the bottom: icon buttons, each menu opens upward; nothing else covers the view */
      #od-bar { position: absolute; left: 50%; bottom: 12px; transform: translateX(-50%); z-index: 10; display: flex; align-items: center; gap: 2px; padding: 4px; background: rgba(255,255,255,0.94); border: 1px solid #e6e9f0; border-radius: 12px; box-shadow: 0 4px 12px -2px rgba(16,24,40,0.10), 0 2px 4px -2px rgba(16,24,40,0.06); backdrop-filter: blur(8px); max-width: calc(100vw - 24px); }
      #od-bar .od-item { position: relative; display: flex; align-items: center; }
      #od-bar .od-btn { display: inline-flex; align-items: center; gap: 6px; height: 30px; padding: 0 10px; font: 500 12px Inter, -apple-system, 'Segoe UI', sans-serif; color: #3d4659; background: transparent; border: 1px solid transparent; border-radius: 8px; cursor: pointer; white-space: nowrap; }
      #od-bar .od-btn:hover { background: #f1f4f9; color: #141b2d; }
      #od-bar .od-btn[aria-pressed="true"], #od-bar .od-btn[aria-expanded="true"] { background: #e9eeff; color: #2f5cff; }
      #od-bar .od-btn svg { width: 16px; height: 16px; flex: none; fill: none; stroke: currentColor; stroke-width: 1.8; stroke-linecap: round; stroke-linejoin: round; }
      #od-bar .od-caret { padding: 0 6px; margin-left: -2px; }
      #od-bar .od-sep { width: 1px; height: 18px; background: #e6e9f0; margin: 0 2px; }
      #od-bar .od-menu { position: absolute; bottom: calc(100% + 8px); left: 50%; transform: translateX(-50%); min-width: 190px; display: flex; flex-direction: column; gap: 2px; padding: 6px; background: #fff; border: 1px solid #e6e9f0; border-radius: 11px; box-shadow: 0 12px 28px -6px rgba(16,24,40,0.18); }
      #od-bar .od-menu[hidden] { display: none; }
      #od-bar .od-menu-end { left: auto; right: 0; transform: none; }
      #od-bar .od-menu button { display: block; width: 100%; text-align: left; font: 500 12px Inter, -apple-system, 'Segoe UI', sans-serif; padding: 6px 9px; color: #141b2d; background: #fff; border: 0; border-radius: 7px; cursor: pointer; }
      #od-bar .od-menu button:hover:not(:disabled) { background: #f1f4f9; }
      #od-bar .od-menu button:disabled { opacity: 0.45; cursor: not-allowed; }
      #od-bar .od-menu button.active { color: #2f5cff; font-weight: 600; }
      #od-bar .od-row { display: flex; align-items: center; justify-content: space-between; gap: 10px; font-size: 12px; color: #141b2d; padding: 4px 9px; }
      #od-bar .od-row input[type=range] { flex: 1; min-width: 90px; accent-color: #2f5cff; }
      #od-bar .od-row input[type=color] { width: 34px; height: 22px; padding: 0; border: 1px solid #e6e9f0; border-radius: 5px; background: none; cursor: pointer; }
      #od-bar .od-row select { font: inherit; font-size: 12px; padding: 3px 6px; border: 1px solid #e6e9f0; border-radius: 6px; background: #fff; color: #141b2d; }
      #od-bar .od-help { margin: 4px 9px 2px; font-size: 11px; color: #707a8c; line-height: 1.4; }
      #od-bar .od-divider { height: 1px; background: #eef1f5; margin: 3px 2px; }
      @media (max-width: 640px) { #od-bar .od-btn span { display: none; } }
""" if show_bar else "") + """
      #render-overlay { position: absolute; left: 50%; bottom: 18px; transform: translateX(-50%); z-index: 20; display: flex; align-items: center; gap: 12px; background: rgba(17,22,28,0.86); color: #f3f6fa; padding: 10px 14px; border-radius: 12px; box-shadow: 0 10px 30px rgba(0,0,0,0.35); font-size: 13px; backdrop-filter: blur(6px); }
      #render-overlay[hidden] { display: none; }
      #render-status { min-width: 190px; font-variant-numeric: tabular-nums; }
      #render-overlay .render-actions { display: flex; gap: 6px; }
      #render-overlay button { font-family: inherit; font-size: 12px; padding: 6px 12px; border-radius: 7px; border: 1px solid rgba(255,255,255,0.18); background: rgba(255,255,255,0.1); color: #fff; cursor: pointer; }
      #render-overlay button:hover { background: rgba(255,255,255,0.2); }
      #btn-render-save { background: #2f5cff !important; border-color: #2f5cff !important; }
""" if show_controls else ""
        glb_disabled = " disabled" if not geometry_exportable else ""
        icon = {
            "camera": '<path d="M3 8h3l2-3h8l2 3h3v11H3z"/><circle cx="12" cy="13" r="3.5"/>',
            "world": '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18"/>',
            "labels": '<path d="M3 12V4h8l10 10-8 8z"/><circle cx="7.5" cy="8" r="1.4"/>',
            "light": '<path d="M7 4l13 8-13 8z"/>',
            "caret": '<path d="M7 10l5 5 5-5"/>',
            "save": '<path d="M12 4v11M7 10l5 5 5-5M4 19h16"/>',
            "full": '<path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/>',
            "more": '<path d="M5 12h.01M12 12h.01M19 12h.01" stroke-width="3"/>',
        }
        svg = {name: f'<svg viewBox="0 0 24 24" aria-hidden="true">{body}</svg>' for name, body in icon.items()}
        labels_on = "true" if self.show_labels else "false"
        look_light, look_field = (" selected", "") if self.look == "light" else ("", " selected")
        bar_html = f"""
<div id="od-bar" role="toolbar" aria-label="3D view" data-optodraw-export-controls="true">
  <div class="od-item">
    <button type="button" class="od-btn" aria-haspopup="true" aria-expanded="false" title="Camera">{svg['camera']}<span>Camera</span></button>
    <div class="od-menu" hidden>
{self._camera_buttons_html()}
    </div>
  </div>
  <div class="od-item">
    <button type="button" class="od-btn" aria-haspopup="true" aria-expanded="false" title="World: the background and the floor">{svg['world']}<span>World</span></button>
    <div class="od-menu" hidden>
      <button type="button" data-world="light">Light</button>
      <button type="button" data-world="dark">Dark</button>
      <button type="button" data-world="none" title="No background and no floor: a transparent canvas">None</button>
      <label class="od-row">Table<input type="color" id="world-table-color" value="#dde3ea" /></label>
    </div>
  </div>
  <button type="button" class="od-btn" id="btn-labels" aria-pressed="{labels_on}" title="Labels on or off (they are never in saved images)">{svg['labels']}<span>Labels</span></button>
  <div class="od-item" id="anim-section">
    <button type="button" class="od-btn" id="anim-toggle" aria-pressed="false" title="Light on or off. Off removes it; Pause in the menu only freezes it">{svg['light']}<span>Light</span></button>
    <button type="button" class="od-btn od-caret" aria-haspopup="true" aria-expanded="false" title="Light controls">{svg['caret']}</button>
    <div class="od-menu" hidden>
      <button type="button" id="anim-play">Play</button>
      <label class="od-row" title="Playback speed">Speed<input id="anim-speed" type="range" min="0.25" max="4" step="0.05" value="1" /></label>
      <label class="od-row" title="Scrub through the loop">Time<input id="anim-scrub" type="range" min="0" max="1000" value="0" /></label>
      <label class="od-row" title="How the light looks">Look<select id="light-look">
        <option value="light"{look_light}>Light</option><option value="field"{look_field} title="The steady field: crests, mode shape and interference">Field</option></select></label>
      <div class="od-divider"></div>
      <button type="button" id="light-tour" title="Play tour: the camera follows the light from device to device">Play tour</button>
      <button type="button" id="light-record" disabled title="Record video: saves the tour as a WebM in real time. The WebM has no part labels. The editor and Python make the MP4.">Record video</button>
    </div>
  </div>
  <div class="od-sep"></div>
  <div class="od-item">
    <button type="button" class="od-btn" aria-haspopup="true" aria-expanded="false" title="Save an image">{svg['save']}<span>Save</span></button>
    <div class="od-menu" hidden>
      <button type="button" id="btn-export-png" data-export-hook="png">PNG image</button>
      <button type="button" id="btn-export-png-clear" title="The parts only, on a transparent background">PNG, transparent</button>
    </div>
  </div>
  <button type="button" class="od-btn" id="btn-fullscreen" title="Fullscreen">{svg['full']}<span>Fullscreen</span></button>
  <div class="od-item">
    <button type="button" class="od-btn" aria-haspopup="true" aria-expanded="false" title="More">{svg['more']}<span>More</span></button>
    <div class="od-menu od-menu-end" hidden>
      <button type="button" id="btn-export-glb" data-export-hook="glb"{glb_disabled}>3D model (GLB)</button>
      <button type="button" id="btn-export-json" data-export-hook="json">Scene (JSON)</button>
      <button type="button" id="btn-pathtrace" title="A photoreal image from optodraw's studio renderer">Photoreal render</button>
      <p class="od-help">Drag to orbit. Scroll to zoom. Right-click to pan.</p>
    </div>
  </div>
</div><!-- /od-bar -->
""" if show_bar else ""
        toolbar_html = (bar_html + """
<div id="render-overlay" hidden>
  <div id="render-status">Starting…</div>
  <div class="render-actions">
    <button type="button" id="btn-render-save">Save PNG</button>
    <button type="button" id="btn-render-exit">Exit render</button>
  </div>
</div>
""") if show_controls else ""
        gltf_exporter_import = (
            "import { GLTFExporter } from 'three/addons/exporters/GLTFExporter.js';\n"
            if show_controls and geometry_exportable
            else ""
        )
        export_controls_js = self._export_controls_js(
          scene_spec_json,
          geometry_exportable,
          use_postprocessing=self.postprocessing,
        ) if show_controls else ""
        path_tracer_js = """
// --- Photoreal render: the studio renderer (CPU workers), the image render_3d_image saves ---
const odPT = { active: false, busy: false, gen: 0, url: null };
window.__odPT = odPT;                    // odLight hides the light while a render runs or shows
const _renderOverlay = document.getElementById('render-overlay');
const _renderStatus = document.getElementById('render-status');
function _ptShow(msg, withActions) {
  if (_renderStatus) _renderStatus.textContent = msg;
  if (_renderOverlay) _renderOverlay.hidden = false;
  const acts = _renderOverlay ? _renderOverlay.querySelector('.render-actions') : null;
  if (acts) acts.style.visibility = withActions ? 'visible' : 'hidden';
}
function _ptHide() { if (_renderOverlay) _renderOverlay.hidden = true; }
let _renderImage = null;
function _ptImage() {
  if (!_renderImage) {
    _renderImage = document.createElement('img');
    _renderImage.id = 'render-image';
    _renderImage.alt = 'Photoreal render';
    Object.assign(_renderImage.style, { position: 'fixed', left: '0', top: '0', width: '100%', height: '100%',
      objectFit: 'contain', zIndex: '15', pointerEvents: 'none', display: 'none' });
    document.body.appendChild(_renderImage);
  }
  return _renderImage;
}
async function odStartRender() {
  if (odPT.busy) return;
  if (window.odLight) window.odLight.control('tour', false);   // a photoreal render shows the parts as they are
  const gen = ++odPT.gen;
  odPT.busy = true; odPT.active = true; odPT.url = null;
  setLabels(false);                        // labels are never baked into a saved render
  _ptShow('Rendering… 0%', false);
  try {
    const url = await odStudio.render(THREE, scene, camera, odStudioOptions(renderer.domElement.width, renderer.domElement.height, {
      onProgress: (done, total) => {
        if (gen === odPT.gen && _renderStatus) _renderStatus.textContent = 'Rendering… ' + Math.floor((100 * done) / total) + '%';
      },
      cancelled: () => gen !== odPT.gen,
    }));
    if (gen !== odPT.gen) return;
    odPT.url = url;
    const img = _ptImage();
    img.src = url; img.style.display = '';
    _ptShow('Render complete · orbit to exit', true);
  } catch (e) {
    if (gen === odPT.gen) _ptShow('Render failed: ' + (e && e.message ? e.message : e), true);
  } finally {
    if (gen === odPT.gen) odPT.busy = false;
  }
}
function odExitRender() {
  odPT.gen++; odPT.busy = false; odPT.active = false; odPT.url = null;
  if (_renderImage) _renderImage.style.display = 'none';
  _ptHide();
}
function odSaveRender() {
  if (!odPT.url) return;
  const baseName = (document.title || 'optodraw-scene').replace(/ [|] .*$/, '');
  downloadFile(baseName + '-render.png', dataUrlToBlob(odPT.url));
}
controls.addEventListener('start', () => { if (odPT.active) odExitRender(); });   // the user moves the view
document.getElementById('btn-pathtrace')?.addEventListener('click', odStartRender);
document.getElementById('btn-render-save')?.addEventListener('click', odSaveRender);
document.getElementById('btn-render-exit')?.addEventListener('click', odExitRender);
document.getElementById('btn-labels')?.addEventListener('click', () => setLabels(!_labelsOn));
function odToggleFullscreen() {
  const el = document.documentElement;
  try {
    if (document.fullscreenElement) { document.exitFullscreen(); }
    else { (el.requestFullscreen || el.webkitRequestFullscreen || function() {}).call(el); }
  } catch (e) { console.warn('fullscreen failed', e); }
}
document.getElementById('btn-fullscreen')?.addEventListener('click', odToggleFullscreen);
// The bar: one menu open at a time, opening upward; a click outside or Escape closes it. The Light button turns
// the light on or off (odLight.setEnabled); Pause in its menu only freezes it.
(function() {
  const bar = document.getElementById('od-bar');
  if (!bar) return;
  const items = [...bar.querySelectorAll('.od-item')].filter((item) => item.querySelector('.od-menu'));
  function closeAll(except) {
    for (const item of items) {
      if (item === except) continue;
      item.querySelector('.od-menu').hidden = true;
      const trigger = item.querySelector('[aria-haspopup]');
      if (trigger) trigger.setAttribute('aria-expanded', 'false');
    }
  }
  for (const item of items) {
    const trigger = item.querySelector('[aria-haspopup]'), menu = item.querySelector('.od-menu');
    trigger.addEventListener('click', (e) => {
      e.stopPropagation();
      const open = menu.hidden;
      closeAll(item);
      menu.hidden = !open;
      trigger.setAttribute('aria-expanded', String(open));
    });
    menu.addEventListener('click', (e) => e.stopPropagation());
    for (const b of menu.querySelectorAll('button[data-camera-preset], button[data-export-hook], #btn-export-png-clear, #btn-pathtrace, #light-tour')) {
      b.addEventListener('click', () => closeAll(null));      // an action closes its menu; a toggle keeps it open
    }
  }
  document.addEventListener('click', () => closeAll(null));
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeAll(null); });
  const lightBtn = document.getElementById('anim-toggle');
  const sync = () => { if (lightBtn && window.odLight) lightBtn.setAttribute('aria-pressed', String(window.odLight.state.enabled)); };
  if (lightBtn) lightBtn.addEventListener('click', () => {
    if (!window.odLight) return;
    window.odLight.setEnabled(!window.odLight.state.enabled);
    sync();
  });
  sync();
  const labelsBtn = document.getElementById('btn-labels');
  if (labelsBtn) labelsBtn.addEventListener('click', () => labelsBtn.setAttribute('aria-pressed', String(_labelsOn)));
})();
""" if show_controls else ""
        ao = self.quality == "high"
        composing = self.postprocessing or ao
        imports = []
        if composing:
            imports += ["import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js';",
                        "import { RenderPass } from 'three/addons/postprocessing/RenderPass.js';",
                        "import { OutputPass } from 'three/addons/postprocessing/OutputPass.js';"]
        if self.postprocessing:
            imports.append("import { UnrealBloomPass } from 'three/addons/postprocessing/UnrealBloomPass.js';")
        if ao:
            imports += ["import { GTAOPass } from 'three/addons/postprocessing/GTAOPass.js';",
                        "import { GTAOShader } from 'three/addons/shaders/GTAOShader.js';",
                        "import { PoissonDenoiseShader } from 'three/addons/shaders/PoissonDenoiseShader.js';"]
        postprocessing_imports = "\n".join(imports)
        bloom_js = f"""
      composer.addPass(new UnrealBloomPass(
        new THREE.Vector2(window.innerWidth, window.innerHeight),
        {float(post_options.get('bloomStrength', 0.12))},
        {float(post_options.get('bloomRadius', 0.22))},
        {float(post_options.get('bloomThreshold', 0.8))}
      ));""" if self.postprocessing else ""
        ao_js = _GTAO_LOG_DEPTH_JS if ao else ""
        postprocessing_js = f"""
    // --- Post-processing: ambient occlusion (quality "high") and the optional publication bloom ---
    const composer = renderer.noWebGL ? null : (() => {{
      const composer = new EffectComposer(renderer);
      composer.addPass(new RenderPass(scene, camera));{ao_js}{bloom_js}
      composer.addPass(new OutputPass());
      return composer;
    }})();
    """ if composing else "\n    const composer = null;\n"
        render_scene_call = "if (composer) composer.render(); else renderer.render(scene, camera);"
        resize_composer = "\n  if (composer) composer.setSize(window.innerWidth, window.innerHeight);"
        info_html = "" if (self.capture or self.editable) else f"""<div id="info">
  <h3>{_html.escape(self.scene.title)}</h3>
</div>"""
        if self.capture:
            info_html = ('<textarea id="od-capture" style="display:none"></textarea>'
                         '<textarea id="od-stage" style="display:none"></textarea>'
                         # a page error ends the capture at once with its message, not at the timeout
                         "<script>(function(){function fail(m){var o=document.getElementById('od-capture');"
                         "if(o&&!o.value)o.value='error: '+m;}"
                         "window.addEventListener('error',function(e){fail(e.message||'page error');});"
                         "window.addEventListener('unhandledrejection',function(e){var r=e.reason;"
                         "fail(r&&r.message?r.message:String(r));});})();</script>")
        capture_json = json.dumps(self.capture) if self.capture else "null"
        video_head, video_css, video_body = _FONT_LINKS, "", ""
        if self.video:
            from optodraw.animation3d.video import video_page_parts

            video_head, video_css, video_body = video_page_parts(self.video)
            info_html = ""
        # the note that names the layers left out of 3D; never in a capture or a video frame
        note_html = "" if (self.capture or self.video) else '<div id="od-note" role="status" hidden></div>\n'
        # the studio branch of a capture: our own renderer draws the viewer's scene (studio_render.js)
        capture_studio_js = """    if (OD_CAPTURE.engine === 'studio') {
      odStudio.render(THREE, scene, camera, odStudioOptions(Math.round(W * S), Math.round(H * S),
        { samples: OD_CAPTURE.samples || 4, quality: OD_CAPTURE.quality || 'final', workers: OD_CAPTURE.workers }))
        .then((url) => { out.value = url; },
              (error) => { out.value = 'error: ' + (error && error.message ? error.message : String(error)); });
      return;
    }
""" if self.capture and self.capture.get("engine") == "studio" else ""
        body_attrs = (
          (' data-show-export-controls="true"' if show_controls else "")
          + f' data-optodraw-lighting-preset="{_html.escape(str(self.lighting_preset), quote=True)}"'
          + f' data-optodraw-render-quality="{_html.escape(str(self.render_quality), quote=True)}"'
          + f' data-optodraw-postprocessing="{str(self.postprocessing).lower()}"'
        )
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>{_html.escape(self.scene.title)} | optodraw 3D</title>
{video_head}<style>
      body {{ margin: 0; overflow: hidden; background: {_html.escape(str(self.background))}; font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; color: #141b2d; }}
      #info {{ position: absolute; top: 12px; left: 12px; color: #586173; font-size: 12px; z-index: 10;
           background: rgba(255,255,255,0.92); padding: 10px 14px; border-radius: 11px; border: 1px solid #e6e9f0;
           box-shadow: 0 4px 12px -2px rgba(16,24,40,0.08), 0 2px 4px -2px rgba(16,24,40,0.05); backdrop-filter: blur(8px); }}
      #info h3 {{ margin: 0; color: #141b2d; font-weight: 600; font-size: 13px; letter-spacing: -0.01em; }}
      #info {{ padding: 7px 12px; max-width: calc(100vw - 52px); }}
      #od-note {{ position: absolute; top: 12px; left: 12px; z-index: 10; max-width: min(440px, calc(100vw - 52px));
           background: rgba(255,255,255,0.92); color: #586173; font-size: 12px; line-height: 1.4; padding: 7px 12px;
           border-radius: 11px; border: 1px solid #e6e9f0; }}
      #info ~ #od-note {{ top: 52px; }}
      #od-note[hidden] {{ display: none; }}
{toolbar_css}{legend_css}{video_css}</style>
</head>
<body{body_attrs}>
{info_html}
{note_html}{toolbar_html}{legend_html}

<script type="importmap">
{{
  "imports": {{
    "three": "{THREEJS_CDN}/build/three.module.js",
    "three/addons/": "{THREEJS_CDN}/examples/jsm/",
    "three/examples/jsm/": "{THREEJS_CDN}/examples/jsm/"
  }}
}}
</script>

<script type="module">
import * as THREE from 'three';
import {{ OrbitControls }} from 'three/addons/controls/OrbitControls.js';
import {{ RoomEnvironment }} from 'three/addons/environments/RoomEnvironment.js';
import {{ GLTFLoader }} from 'three/addons/loaders/GLTFLoader.js';
import {{ OBJLoader }} from 'three/addons/loaders/OBJLoader.js';
import {{ SVGLoader }} from 'three/addons/loaders/SVGLoader.js';
import {{ CSS2DRenderer, CSS2DObject }} from 'three/addons/renderers/CSS2DRenderer.js';
import {{ toCreasedNormals }} from 'three/addons/utils/BufferGeometryUtils.js';
{gltf_exporter_import}
{postprocessing_imports}
{editor_imports}
// --- Setup ---
const scene = new THREE.Scene();
scene.background = new THREE.Color('{self.background}');
scene.fog = new THREE.FogExp2('{self.background}', {lighting['fogDensity'] if self.show_fog else 0.0});
scene.userData.optodrawRender = {{ lightingPreset: '{self.lighting_preset}', renderQuality: '{self.render_quality}', postprocessing: {str(self.postprocessing).lower()} }};

// Wide clip range + logarithmic depth buffer (see renderer) so you can zoom from
// sub-micron features out to a whole mm-scale chip with no hard limits and no z-fighting.
const camera = new THREE.PerspectiveCamera(50, window.innerWidth / window.innerHeight, 0.02, 5_000_000);
const _initialDir = new THREE.Vector3({initial_dir[0]}, {initial_dir[1]}, {initial_dir[2]});
if (_initialDir.lengthSq() > 0) {{ _initialDir.normalize(); }} else {{ _initialDir.set(1, 1, 1).normalize(); }}
camera.position.copy(_initialDir.clone().multiplyScalar({self.camera_distance}));
camera.lookAt(0, 0, 0);

const renderer = (() => {{
  try {{
    return new THREE.WebGLRenderer({{ antialias: true, alpha: true, logarithmicDepthBuffer: true, preserveDrawingBuffer: true }});
  }} catch (error) {{
    const cap = {capture_json};
    if (!(cap && cap.engine === 'studio')) throw error;
    // no WebGL here: a stand-in, so the page still builds the scene that the studio renderer draws on the CPU
    return {{ noWebGL: true, domElement: document.createElement('canvas'), shadowMap: {{}}, toneMapping: 0,
             toneMappingExposure: 1, outputColorSpace: '', setSize() {{}}, setPixelRatio() {{}}, setClearColor() {{}},
             render() {{}} }};
  }}
}})();
const FLOOR_GRID = {str(self.floor_grid).lower()};
const TRANSPARENT_WORLD = {str(self.transparent_world).lower()};
const OD_CAPTURE = {capture_json};
const OD_VIDEO = {json.dumps(bool(self.video))};
const STUDIO_LIGHT = {str(self.lighting_preset == "studio").lower()};   // the viewer lit by the studio renderer's softboxes
renderer.setSize(window.innerWidth, window.innerHeight);
renderer.setPixelRatio({pixel_ratio});
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
// Khronos PBR Neutral keeps a base colour true (ACES washed #2b6cb0 silicon out to a pale sky blue)
renderer.toneMapping = THREE.NeutralToneMapping;
renderer.toneMappingExposure = {lighting['toneMappingExposure']};
renderer.outputColorSpace = THREE.SRGBColorSpace;
document.body.appendChild(renderer.domElement);

if (!renderer.noWebGL) {{
  const pmremGenerator = new THREE.PMREMGenerator(renderer);
  scene.environment = pmremGenerator.fromScene(new RoomEnvironment(), 0.04).texture;
}}

// Label renderer
const labelRenderer = new CSS2DRenderer();
labelRenderer.setSize(window.innerWidth, window.innerHeight);
labelRenderer.domElement.style.position = 'absolute';
labelRenderer.domElement.style.top = '0px';
labelRenderer.domElement.style.pointerEvents = 'none';
document.body.appendChild(labelRenderer.domElement);

// Component labels are HTML overlays (never baked into saved WebGL images); toggleable.
let _labelsOn = {str(self.show_labels).lower()};
let _labelsForced = false;     // the tour shows the label of the device in focus, also with labels off
function setLabels(on) {{
  _labelsOn = !!on;
  labelRenderer.domElement.style.display = _labelsOn || _labelsForced ? '' : 'none';
  const b = document.getElementById('btn-labels');
  if (b) b.classList.toggle('active', _labelsOn);
}}
function odForceLabels(on) {{
  _labelsForced = !!on;
  labelRenderer.domElement.style.display = _labelsOn || _labelsForced ? '' : 'none';
}}

// Controls
const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.dampingFactor = 0.05;
controls.zoomToCursor = true;   // wheel zoom dives toward the pointer — natural deep zoom
controls.zoomSpeed = 1.2;
{postprocessing_js}

// --- Lighting ---
const hemiLight = new THREE.HemisphereLight({lighting['hemiSky']}, {lighting['hemiGround']}, {lighting['hemiIntensity']});
scene.add(hemiLight);

const ambientLight = new THREE.AmbientLight({lighting['ambientColor']}, {lighting['ambientIntensity']});
scene.add(ambientLight);

const dirLight = new THREE.DirectionalLight({lighting['keyColor']}, {lighting['keyIntensity']});
dirLight.position.set({lighting['keyPosition'][0]}, {lighting['keyPosition'][1]}, {lighting['keyPosition'][2]});
dirLight.castShadow = true;
dirLight.shadow.mapSize.width = {shadow_map_size};
dirLight.shadow.mapSize.height = {shadow_map_size};
scene.add(dirLight);
scene.add(dirLight.target);
const _keyDir = dirLight.position.clone().normalize();
// the default shadow box is 10 units round the origin with no bias: no shadow outside it, stripes inside.
// Fit it to the content and keep the key light's direction.
// The studio's overhead softbox in real time: a second shadowing light from straight above (its soft
// shadow grounds the parts); off until the studio light turns it on.
const topLight = new THREE.DirectionalLight(0xffffff, 0);
topLight.castShadow = true;
topLight.shadow.camera.up.set(0, 0, 1);            // it looks straight down: y cannot be its up
topLight.shadow.mapSize.width = {shadow_map_size};
topLight.shadow.mapSize.height = {shadow_map_size};
scene.add(topLight);
scene.add(topLight.target);
const _topDir = new THREE.Vector3(0, 1, 0);
function odFitLight(light, dir, sphere) {{
  const r = Math.max(sphere.radius, 1.0);
  light.target.position.copy(sphere.center);
  light.position.copy(sphere.center).addScaledVector(dir, r * 3.0);
  const cam = light.shadow.camera;
  cam.left = -r * 1.05; cam.right = r * 1.05; cam.top = r * 1.05; cam.bottom = -r * 1.05;
  cam.near = r * 0.5; cam.far = r * 6.0; cam.updateProjectionMatrix();
  light.shadow.bias = -0.0004;
  light.shadow.normalBias = r * 0.003;
}}
// A chip alone stands on a studio floor that fades into the backdrop, as in the studio renderer's image
// (solid to 0.75 of the content's half-diagonal, gone at 1.6). The studio renderer draws its own exact floor.
let _studioFloor = null;
function odStudioFloor(box) {{
  if (!STUDIO_LIGHT || !IS_ONCHIP || MIXED || box.isEmpty()) return;
  const R = Math.max(0.5 * Math.hypot(box.max.x - box.min.x, box.max.z - box.min.z), 1e-3);
  if (!_studioFloor) {{
    const n = 256, cv = document.createElement('canvas');
    cv.width = n; cv.height = n;
    const g = cv.getContext('2d'), grad = g.createRadialGradient(n / 2, n / 2, 0, n / 2, n / 2, n / 2);
    grad.addColorStop(0, '#ffffff'); grad.addColorStop(0.75 / 1.6, '#ffffff'); grad.addColorStop(1, '#000000');
    g.fillStyle = grad; g.fillRect(0, 0, n, n);
    const mat = new THREE.MeshStandardMaterial({{ color: (WORLDS[_world] || WORLDS.light).bgBottom, roughness: 0.85,
      metalness: 0, transparent: true, alphaMap: new THREE.CanvasTexture(cv), depthWrite: false }});
    _studioFloor = new THREE.Mesh(new THREE.PlaneGeometry(1, 1), mat);
    _studioFloor.rotation.x = -Math.PI / 2;
    _studioFloor.receiveShadow = true;
    _studioFloor.userData.odStudioFloor = true;
    scene.add(_studioFloor);
  }}
  _studioFloor.scale.set(3.2 * R, 3.2 * R, 1);
  _studioFloor.position.set((box.min.x + box.max.x) / 2, box.min.y, (box.min.z + box.max.z) / 2);
  _studioFloor.visible = _world !== 'none';
}}
function odFitShadow(box) {{
  odStudioFloor(box);
  const sphere = box.getBoundingSphere(new THREE.Sphere());
  odFitLight(dirLight, _keyDir, sphere);
  odFitLight(topLight, _topDir, sphere);
  // ambient occlusion reaches a few percent of the content: contact shadows, not a dark haze
  if (window.__odGTAO) {{
    const reach = Math.max(sphere.radius, 1.0) * 0.08;
    window.__odGTAO.updateGtaoMaterial({{ radius: reach, thickness: reach, scale: 1.2 }});
  }}
}}

const fillLight = new THREE.DirectionalLight({lighting['fillColor']}, {lighting['fillIntensity']});
fillLight.position.set({lighting['fillPosition'][0]}, {lighting['fillPosition'][1]}, {lighting['fillPosition'][2]});
scene.add(fillLight);

const rimLight = new THREE.DirectionalLight({lighting['rimColor']}, {lighting['rimIntensity']});
rimLight.position.set({lighting['rimPosition'][0]}, {lighting['rimPosition'][1]}, {lighting['rimPosition'][2]});
scene.add(rimLight);

// --- Optical table material (the table + grid are sized to the content below) ---
const tableMat = new THREE.MeshStandardMaterial({{ color: {stage['surfaceColor']}, roughness: {stage['surfaceRoughness']}, metalness: {stage['surfaceMetalness']} }});

// --- World / environment presets (neutral studio; lights stay fixed in world space) ---
let _gridHelper = null;
let _tableMesh = null;
const WORLDS = {{
  light: {{ bgTop: '#eef1f4', bgBottom: '#bcc5d2', hemiSky: '#ffffff', hemiGround: '#d8dee6', hemiIntensity: 0.6, ambient: '#ffffff', ambientIntensity: 0.3, exposure: 1.0, envIntensity: 0.4, tableColor: '#dde3ea', gridColor: '#b4bdca' }},
  night: {{ bgTop: '#0b1033', bgBottom: '#151a4a', hemiSky: '#aab6d8', hemiGround: '#0a0d26', hemiIntensity: 0.55, ambient: '#9fb0d8', ambientIntensity: 0.32, exposure: 1.28, envIntensity: 0.45, tableColor: '#171c4a', gridColor: '#2a3170', lights: 0.12 }},
  dark:  {{ bgTop: '#232a33', bgBottom: '#13171c', hemiSky: '#aab6c4', hemiGround: '#0d1014', hemiIntensity: 0.62, ambient: '#9fb0c4', ambientIntensity: 0.36, exposure: 1.28, envIntensity: 0.5, tableColor: '#1b2027', gridColor: '#3a434f' }},
}};
function _gradientTexture(top, bottom) {{
  const c = document.createElement('canvas'); c.width = 2; c.height = 256;
  const g = c.getContext('2d'); const grad = g.createLinearGradient(0, 0, 0, 256);
  grad.addColorStop(0, top); grad.addColorStop(1, bottom);
  g.fillStyle = grad; g.fillRect(0, 0, 2, 256);
  const tex = new THREE.CanvasTexture(c); tex.colorSpace = THREE.SRGBColorSpace; return tex;
}}
let _world = 'light';
// The studio renderer's light in the live viewer: ambient, overhead, fill and rim softboxes as the
// environment map; the key softbox as the directional light that casts the (soft) shadow, same energy.
function odApplyStudioLight() {{
  if (!STUDIO_LIGHT || renderer.noWebGL || typeof odStudioCore === 'undefined') return;
  camera.updateMatrixWorld();
  const e = camera.matrixWorld.elements;
  const env = odStudioCore.studioEnv(_world === 'dark' || _world === 'night' ? 'dark' : 'light', {{ right: [e[0], e[1], e[2]] }});
  const key = env.lobes[0], top = env.lobes[3], TOP_SHARE = 0.6;
  const rest = env.lobes.slice(1).map((L) => L === top ? {{ ...L, color: L.color.map((c) => c * (1 - TOP_SHARE)) }} : L);
  const W = 256, H = 128, data = new Float32Array(W * H * 4);
  for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {{
    const phi = ((x + 0.5) / W - 0.5) * 2 * Math.PI, lat = ((y + 0.5) / H - 0.5) * Math.PI;
    const dx = Math.cos(lat) * Math.cos(phi), dy = Math.sin(lat), dz = Math.cos(lat) * Math.sin(phi);
    const i = (y * W + x) * 4;
    data[i] = env.ambient[0]; data[i + 1] = env.ambient[1]; data[i + 2] = env.ambient[2]; data[i + 3] = 1;
    for (const L of rest) {{
      const w = Math.exp(L.sharpness * (dx * L.dir[0] + dy * L.dir[1] + dz * L.dir[2] - 1));
      data[i] += L.color[0] * w; data[i + 1] += L.color[1] * w; data[i + 2] += L.color[2] * w;
    }}
  }}
  const tex = new THREE.DataTexture(data, W, H, THREE.RGBAFormat, THREE.FloatType);
  tex.mapping = THREE.EquirectangularReflectionMapping;
  tex.needsUpdate = true;
  const pmrem = new THREE.PMREMGenerator(renderer);
  if (scene.environment && scene.userData.studioLight) scene.environment.dispose();
  scene.environment = pmrem.fromEquirectangular(tex).texture;
  pmrem.dispose(); tex.dispose();
  scene.environmentIntensity = 1;
  const energy = (2 * Math.PI * (1 - Math.exp(-2 * key.sharpness))) / key.sharpness, peak = Math.max(...key.color);
  dirLight.color.setRGB(key.color[0] / peak, key.color[1] / peak, key.color[2] / peak, THREE.LinearSRGBColorSpace);
  dirLight.intensity = peak * energy;
  _keyDir.set(key.dir[0], key.dir[1], key.dir[2]);
  // the new direction at the light's fitted distance: odFitShadow sized the shadow camera for it
  const reach = dirLight.position.distanceTo(dirLight.target.position) || 100;
  dirLight.position.copy(dirLight.target.position).addScaledVector(_keyDir, reach);
  const topEnergy = (2 * Math.PI * ((top.sharpness - 1) + Math.exp(-top.sharpness))) / (top.sharpness * top.sharpness);
  const topPeak = Math.max(...top.color);
  topLight.color.setRGB(top.color[0] / topPeak, top.color[1] / topPeak, top.color[2] / topPeak, THREE.LinearSRGBColorSpace);
  topLight.intensity = TOP_SHARE * topPeak * topEnergy;       // the irradiance it gives a face looking up
  _topDir.set(top.dir[0], top.dir[1], top.dir[2]);
  const topReach = topLight.position.distanceTo(topLight.target.position) || 100;
  topLight.position.copy(topLight.target.position).addScaledVector(_topDir, topReach);
  renderer.shadowMap.type = THREE.PCFShadowMap;    // PCF with a radius: a soft edge, as from a softbox
  dirLight.shadow.radius = 4;
  topLight.shadow.radius = 10;                     // the broad diffuser: a wide, soft contact shadow
  hemiLight.intensity = 0; ambientLight.intensity = 0; fillLight.intensity = 0; rimLight.intensity = 0;
  scene.traverse((o) => {{                         // a private room map would hide the studio
    const list = o.isMesh ? (Array.isArray(o.material) ? o.material : [o.material]) : [];
    for (const m of list) if (m && m.envMap) {{ m.envMap = null; m.envMapIntensity = 1; m.needsUpdate = true; }}
  }});
  scene.userData.studioLight = true;
}}
// A world can dim every scene light (the night world, while the light plays: the chip reads dark and the unlit glow
// stands out). Each dimmed light keeps its own intensity here, and the next world gives it back first.
const _undimmed = new Map();
function odDimLights(factor) {{
  for (const [light, intensity] of _undimmed) light.intensity = intensity;
  _undimmed.clear();
  if (!(factor < 1)) return;
  scene.traverse((o) => {{ if (o.isLight) {{ _undimmed.set(o, o.intensity); o.intensity *= factor; }} }});
  scene.environmentIntensity *= factor;
}}
function applyWorld(name) {{
  odDimLights(1);
  const w = WORLDS[name] || WORLDS.light; _world = WORLDS[name] ? name : 'light';
  if (scene.background && scene.background.isTexture) scene.background.dispose();
  scene.background = _gradientTexture(w.bgTop, w.bgBottom);
  hemiLight.color.set(w.hemiSky); hemiLight.groundColor.set(w.hemiGround); hemiLight.intensity = w.hemiIntensity;
  ambientLight.color.set(w.ambient); ambientLight.intensity = w.ambientIntensity;
  renderer.toneMappingExposure = w.exposure;
  scene.environmentIntensity = w.envIntensity;     // the room map is fill light too: full strength flattened every colour
  if (tableMat) tableMat.color.set(w.tableColor);
  if (_studioFloor) {{ _studioFloor.material.color.set(w.bgBottom); _studioFloor.visible = name !== 'none'; }}
  if (scene.fog) scene.fog.color.set(w.bgBottom);
  if (_gridHelper) {{ _gridHelper.material.vertexColors = false; _gridHelper.material.color.set(w.gridColor); _gridHelper.material.needsUpdate = true; }}
  const _tc = document.getElementById('world-table-color'); if (_tc) _tc.value = w.tableColor;
  // "none": the light world's lights, no background, no floor (a transparent canvas)
  const clear = name === 'none';
  if (clear) {{ if (scene.background && scene.background.isTexture) scene.background.dispose(); scene.background = null; renderer.setClearColor(0x000000, 0); _world = 'none'; }}
  if (_tableMesh && !IS_ONCHIP) _tableMesh.visible = !clear;
  if (_gridHelper) _gridHelper.visible = !clear;
  for (const b of document.querySelectorAll('[data-world]')) b.classList.toggle('active', b.dataset.world === _world);
  odApplyStudioLight();
  odDimLights(w.lights);
}}
window.__odWorld = {{ apply: applyWorld, name: () => _world, background: () => scene.background,   // for checks
  lights: () => {{ const out = []; scene.traverse((o) => {{ if (o.isLight) out.push(o.intensity); }}); return out.concat([scene.environmentIntensity]); }} }};

// --- Build scene from data ---
const sceneData = {data_json};
const odViewsNote = {views_note_json};
const materialPresets = {material_json};
const cameraDistanceScale = {stage.get('cameraDistanceScale', 1.0)};
const verticalExtentScale = {stage.get('verticalExtentScale', 3.0)};
const liftMeshesToTable = {str(k.lift_meshes).lower()};
const IS_ONCHIP = {str(k.on_chip).lower()};
const HAS_USER_DIE = {str(k.has_user_die).lower()};   // a placed ChipSubstrate replaces the auto die
const SHOW_CHIP_BASE = {str(k.show_chip_base).lower()}; // scene meta chip_base: false kills the auto base

const requestedCameraDistance = {self.camera_distance};
// chip-on-bench: with BOTH chip and bench content, the die+carrier stack is
// lifted so it SITS ON the table, and the die hugs only the chip content
const MIXED = {str(k.mixed).lower()};
const CHIP_LIFT = {k.chip_lift};
window.__odChipBox = new THREE.Box3();
const chipRoughBounds = new THREE.Box3();
for (const item of sceneData) {{
  if (!item.chip) continue;
  if (item.position) chipRoughBounds.expandByPoint(new THREE.Vector3(...item.position));
  if (item.points) item.points.forEach(p => chipRoughBounds.expandByPoint(new THREE.Vector3(...p)));
}}
const contentBounds = new THREE.Box3();
let hasContentBounds = false;
function expandContentBounds(point) {{
  contentBounds.expandByPoint(new THREE.Vector3(...point));
  hasContentBounds = true;
}}
for (const item of sceneData) {{
  if (item.position) expandContentBounds(item.position);
  if (item.points) item.points.forEach(expandContentBounds);
}}

// ground, sized and centered to the actual content (not a fixed 220)
let _floorSpan = 220, _floorCx = 0, _floorCz = 0, _floorY = 0, _floorSizeX = 200, _floorSizeZ = 200;
if (hasContentBounds) {{
  const _fc = contentBounds.getCenter(new THREE.Vector3());
  const _fs = contentBounds.getSize(new THREE.Vector3());
  _floorSpan = Math.max(Math.max(_fs.x, _fs.z) * 1.8, 20);
  _floorSizeX = _fs.x; _floorSizeZ = _fs.z;
  _floorCx = _fc.x; _floorCz = _fc.z; _floorY = Math.min(0, contentBounds.min.y);
}}
// On-chip ground = a chamfered silicon die on a darker chip carrier (NOT a breadboard).
// Built from a content Box3 so the die hugs the layout; refit after meshes exist.
let _onChipBase = [];
// the die's XZ footprint — what the base is drawn to, and what bench cables
// must climb over instead of tunnelling straight through
function odDieFootprint(box) {{
  if (!box || box.isEmpty()) return null;
  const c = box.getCenter(new THREE.Vector3());
  const s = box.getSize(new THREE.Vector3());
  return {{
    cx: c.x, cz: c.z,
    hx: Math.max(s.x * 0.5 + Math.max(s.x * 0.05, 5), 8),
    hz: Math.max(s.z * 0.5 + Math.max(s.z * 0.05, 5), 8),
  }};
}}
// where a bench->chip segment first crosses the die edge (slab entry)
function odFootprintEntry(a, b, foot) {{
  const dx = b.x - a.x, dz = b.z - a.z;
  let t = 0;
  if (Math.abs(dx) > 1e-6) t = Math.max(t, Math.min(((foot.cx - foot.hx) - a.x) / dx, ((foot.cx + foot.hx) - a.x) / dx));
  if (Math.abs(dz) > 1e-6) t = Math.max(t, Math.min(((foot.cz - foot.hz) - a.z) / dz, ((foot.cz + foot.hz) - a.z) / dz));
  return (t > 0 && t < 1) ? {{ x: a.x + dx * t, z: a.z + dz * t }} : null;
}}
// the die's thickness follows its footprint (a 5-unit die under a 16-unit part was a brick);
// the carrier is a dark rim round the die, so the whole stack stays in the frame
// A cable end on a part at the beam height: it leaves the connector level along the route, then
// eases down to the table along the route's own path, the way a patch cord hangs from its connector.
// pts are [x, y, z] arrays.
function odCableRise(pts, atStart, beamY, benchY) {{
  const p = atStart ? pts.slice() : pts.slice().reverse();
  if (p.length < 2) return pts;
  const cum = [0];                                                         // arc length in plan
  for (let i = 1; i < p.length; i++) cum.push(cum[i - 1] + Math.hypot(p[i][0] - p[i - 1][0], p[i][2] - p[i - 1][2]));
  const total = cum[cum.length - 1], drop = Math.max(beamY - benchY, 0);
  const lead = Math.min(total * 0.15, Math.max(drop * 0.25, 2.0));         // straight out of the connector
  const reach = Math.min(total * 0.6, lead + drop * 1.4);                  // where it lies on the table
  const height = (d) => d <= lead ? beamY : d >= reach ? benchY
    : benchY + drop * 0.5 * (1 + Math.cos(Math.PI * (d - lead) / (reach - lead)));
  const planAt = (d) => {{
    let i = 0;
    while (i < cum.length - 2 && cum[i + 1] < d) i++;
    const t = cum[i + 1] > cum[i] ? (d - cum[i]) / (cum[i + 1] - cum[i]) : 0;
    return [p[i][0] + (p[i + 1][0] - p[i][0]) * t, p[i][2] + (p[i + 1][2] - p[i][2]) * t];
  }};
  const path = [];
  for (let k = 0; k <= 12; k++) {{
    const d = reach * k / 12, [x, z] = planAt(d);
    path.push([x, height(d), z]);
  }}
  for (let i = 0; i < p.length; i++) if (cum[i] > reach + 1e-6) path.push(p[i]);
  return atStart ? path : path.reverse();
}}
function odChipStack(hx, hz) {{
  const side = 2 * Math.min(hx, hz);
  const dieT = Math.min(Math.max(side * 0.08, 1.0), 5.0);
  return {{ dieT: dieT, carT: dieT * 0.64, rim: Math.min(Math.max(side * 0.06, 0.8), 6.0) }};
}}
function odBuildOnChipBase(box) {{
  if ((!IS_ONCHIP && !MIXED) || !SHOW_CHIP_BASE || !box || box.isEmpty()) return;
  for (const m of _onChipBase) {{ if (m.parent) m.parent.remove(m); if (m.geometry) m.geometry.dispose(); }}
  _onChipBase = [];
  const c = box.getCenter(new THREE.Vector3());
  const s = box.getSize(new THREE.Vector3());
  const {{ hx, hz }} = odDieFootprint(box);
  const stack = odChipStack(hx, hz), ch = Math.min(hx, hz) * 0.24;  // cut corner = die orientation
  if (MIXED) {{ stack.dieT = 5.0; stack.carT = 3.2; }}   // a chip on a bench: CHIP_LIFT (8.2) lifted its devices already
  const {{ dieT, carT, rim }} = stack;
  // mixed: the stack stands ON the table (carrier bottom at 0, devices lifted onto the die top)
  const top = MIXED ? CHIP_LIFT : Math.min(0, box.min.y);
  if (!HAS_USER_DIE) {{
    const shape = new THREE.Shape();
    shape.moveTo(-hx, hz - ch); shape.lineTo(-hx, -hz); shape.lineTo(hx, -hz);
    shape.lineTo(hx, hz); shape.lineTo(-hx + ch, hz); shape.closePath();
    const dieGeo = new THREE.ExtrudeGeometry(shape, {{ depth: dieT, bevelEnabled: false }});
    dieGeo.rotateX(Math.PI / 2); dieGeo.computeVertexNormals();  // shape XY -> world XZ
    if (!window.__odDieMat) window.__odDieMat = new THREE.MeshStandardMaterial({{ color: 0x9aa4b0, roughness: 0.5, metalness: 0.45 }});
    const die = new THREE.Mesh(dieGeo, window.__odDieMat);
    die.position.set(c.x, top, c.z); die.receiveShadow = true; if (!MIXED) _tableMesh = die;
    scene.add(die); _onChipBase.push(die);
  }}
  // dark carrier under the die (or under the user's ChipSubstrate)
  const carrierTop = HAS_USER_DIE ? top - carT / 2 : top - dieT - carT / 2;
  const carrier = new THREE.Mesh(new THREE.BoxGeometry(hx * 2 + rim * 2, carT, hz * 2 + rim * 2),
    new THREE.MeshStandardMaterial({{ color: 0x2f353d, roughness: 0.62, metalness: 0.35 }}));
  carrier.position.set(c.x, carrierTop, c.z); carrier.receiveShadow = true;
  if (HAS_USER_DIE && !MIXED) _tableMesh = carrier;
  scene.add(carrier); _onChipBase.push(carrier);
}}
// show_grid toggles the ENTIRE ground (free-space: optical table + grid; on-chip: die + carrier)
if ({str(k.show_grid).lower()}) {{
  if (IS_ONCHIP && !MIXED) {{
    odBuildOnChipBase(contentBounds);   // rough (position bounds); refit precisely after odBuildAll
  }} else {{
    if (FLOOR_GRID) {{
      const gridHelper = new THREE.GridHelper(_floorSpan, 40, {stage['gridColor1']}, {stage['gridColor2']});
      gridHelper.position.set(_floorCx, _floorY, _floorCz);
      _gridHelper = gridHelper;
      scene.add(gridHelper);
    }}
    const _tableThick = {stage['surfaceThickness']};
    // the white floor stays plain: holes belong to the breadboards and plates on it
    const table = new THREE.Mesh(new THREE.BoxGeometry(_floorSpan, _tableThick, _floorSpan), tableMat);
    table.position.set(_floorCx, _floorY - _tableThick / 2, _floorCz);
    table.receiveShadow = true;
    _tableMesh = table;
    scene.add(table);
    if (MIXED) odBuildOnChipBase(chipRoughBounds);  // chip-on-bench: die on the table
  }}
}}

if (hasContentBounds) {{
  const contentCenter = contentBounds.getCenter(new THREE.Vector3());
  const contentSize = contentBounds.getSize(new THREE.Vector3());
  const horizontalExtent = Math.max(contentSize.x, contentSize.z, 20);
  const verticalExtent = Math.max(contentSize.y, 10);
  const viewDistance = Math.max(requestedCameraDistance * cameraDistanceScale, horizontalExtent * 1.55 * cameraDistanceScale, verticalExtent * verticalExtentScale);
  // No hard zoom limits — the log depth buffer + wide clip range handle any scale.
  const _framingDir = _initialDir.clone();
  camera.position.copy(contentCenter.clone().add(_framingDir.multiplyScalar(viewDistance)));
  camera.lookAt(contentCenter);
  controls.target.copy(contentCenter);
  controls.update();
}}
// remember the framed pose so the editor's reset-view button can restore it
window.__odHome = {{ pos: camera.position.clone(), target: controls.target.clone() }};

// Apply the initial world/environment (sets the gradient background, lights, grid tint)
applyWorld(TRANSPARENT_WORLD ? 'none' : '{self.world}');

{_SCENE_RESOURCES_JS}

function makeMaterial(matDef) {{
  const preset = (matDef.preset && materialPresets[matDef.preset]) ? materialPresets[matDef.preset] : {{}};
  const merged = {{ ...preset, ...matDef }};
  const params = {{}};
  if (merged.color) params.color = new THREE.Color(merged.color);
  // a bare metal reflects with its measured base colour; the 2D fill stays the painted one
  if (merged.physical && (merged.metalness ?? 0) >= 0.9) params.color = new THREE.Color(merged.physical);
  // only mark transparent when actually see-through (opacity 1.0 stays opaque, so it
  // renders in the opaque pass and writes depth — otherwise sorting hides solids)
  if (merged.opacity !== undefined) {{
    params.opacity = merged.opacity;
    if (merged.opacity < 1) params.transparent = true;
  }}
  if (merged.transparent) params.transparent = true;
  // depthWrite:false lets a translucent enclosure (e.g. SiO2 cladding) show what's inside
  if (merged.depthWrite === false) params.depthWrite = false;
  if (merged.metalness !== undefined) params.metalness = merged.metalness;
  if (merged.roughness !== undefined) params.roughness = merged.roughness;
  if (merged.envMapIntensity !== undefined) params.envMapIntensity = merged.envMapIntensity;
  if (merged.wireframe) params.wireframe = true;
  if (merged.emissive) {{ params.emissive = new THREE.Color(merged.emissive); params.emissiveIntensity = merged.emissiveIntensity || 1; }}
  if (merged.transmission !== undefined) params.transmission = merged.transmission;
  if (merged.ior !== undefined) params.ior = merged.ior;
  if (merged.thickness !== undefined) params.thickness = merged.thickness;
  if (merged.clearcoat !== undefined) params.clearcoat = merged.clearcoat;
  if (merged.clearcoatRoughness !== undefined) params.clearcoatRoughness = merged.clearcoatRoughness;
  // a metal shows the room map, not its base colour: keep the full map on metals (the world dims it for the rest)
  if (!STUDIO_LIGHT && (merged.metalness || 0) >= 0.6 && scene.environment) {{ params.envMap = scene.environment; params.envMapIntensity = merged.envMapIntensity ?? 1.6; }}
  params.side = THREE.DoubleSide;
  const MaterialCtor = (merged.transmission !== undefined || merged.ior !== undefined || merged.clearcoat !== undefined || merged.clearcoatRoughness !== undefined) ? THREE.MeshPhysicalMaterial : THREE.MeshStandardMaterial;
  return odSharedMaterial(merged, () => {{
    const material = new MaterialCtor(params);
    material.userData.odPreset = merged.preset || null;   // the light player finds a part's guides by it
    return material;
  }});
}}

// Baked tapped-hole-grid top texture for optical tables / breadboards / baseplates:
// counterbored holes over a brushed finish, one canvas per plate (cached), instead of
// thousands of hole meshes. Deterministic (seeded LCG) so exports are repeatable.
const _holePlateTexCache = new Map();
function odHolePlateTexture(t) {{
  const key = JSON.stringify(t);
  if (_holePlateTexCache.has(key)) return _holePlateTexCache.get(key);
  const L = Math.max(Number(t.length) || 1, 0.001), W = Math.max(Number(t.width) || 1, 0.001);
  const ppu = Math.max(2, Math.min(2048 / L, 2048 / W, 26)); // px per scene unit
  const cw = Math.max(32, Math.round(L * ppu)), ch = Math.max(32, Math.round(W * ppu));
  const cv = document.createElement('canvas'); cv.width = cw; cv.height = ch;
  const g = cv.getContext('2d');
  g.fillStyle = t.base || '#9aa3ad';
  g.fillRect(0, 0, cw, ch);
  let seed = (cw * 73856093) ^ (ch * 19349663);
  const rand = () => {{ seed = (seed * 1664525 + 1013904223) >>> 0; return seed / 4294967296; }};
  if (t.brushed) {{
    // faint lengthwise brushing streaks
    for (let i = 0; i < 160; i++) {{
      const y = rand() * ch;
      g.globalAlpha = 0.028 + rand() * 0.03;
      g.fillStyle = rand() > 0.5 ? '#ffffff' : '#000000';
      g.fillRect(0, y, cw, Math.max(1, ppu * 0.045));
    }}
    g.globalAlpha = 1;
  }}
  const pitch = Number(t.pitch) || 2.54;
  const margin = t.margin != null ? Number(t.margin) : pitch * 0.75;
  const cols = Math.min(Math.max(Math.floor((L - 2 * margin) / pitch) + 1, 0), 320);
  const rows = Math.min(Math.max(Math.floor((W - 2 * margin) / pitch) + 1, 0), 320);
  const x0 = (L - (cols - 1) * pitch) / 2, y0 = (W - (rows - 1) * pitch) / 2;
  const r = Math.max((Number(t.hole_r) || pitch * 0.125) * ppu, 1.2);
  for (let c = 0; c < cols; c++) {{
    for (let rr = 0; rr < rows; rr++) {{
      const x = (x0 + c * pitch) * ppu, y = (y0 + rr * pitch) * ppu;
      // chamfer: bright upper-left rim falling to a soft lower-right shadow
      const ring = g.createRadialGradient(x - r * 0.4, y - r * 0.4, r * 0.15, x, y, r * 1.6);
      ring.addColorStop(0, 'rgba(255,255,255,0.5)');
      ring.addColorStop(0.55, 'rgba(255,255,255,0.12)');
      ring.addColorStop(1, 'rgba(0,0,0,0.22)');
      g.fillStyle = ring;
      g.beginPath(); g.arc(x, y, r * 1.6, 0, Math.PI * 2); g.fill();
      // the bore itself, with an off-center highlight faking depth
      const bore = g.createRadialGradient(x + r * 0.3, y + r * 0.34, r * 0.1, x, y, r);
      bore.addColorStop(0, '#04060a');
      bore.addColorStop(0.72, '#0e1218');
      bore.addColorStop(1, '#232932');
      g.fillStyle = bore;
      g.beginPath(); g.arc(x, y, r, 0, Math.PI * 2); g.fill();
    }}
  }}
  const tex = new THREE.CanvasTexture(cv);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.anisotropy = 8;
  _holePlateTexCache.set(key, tex);
  return tex;
}}

{_js("user_parts.js")}

function makeGeometry(geo) {{
  return odSharedGeometry(geo, makeGeometryTemplate);
}}

function makeGeometryTemplate(geo) {{
  let mesh;
  switch (geo.shape) {{
    case 'group':
      mesh = new THREE.Group();
      break;
    case 'svg_extrusion':
      mesh = odMakeSvgExtrusion(geo);
      break;
    case 'box':
      // a missing size is 1; a size of 0 is a box of no volume, which draws nothing (the old fallback drew it 1 tall)
      const boxSize = [geo.width ?? 1, geo.height ?? 1, geo.depth ?? 1];
      if (!boxSize.every((size) => size > 0)) {{
        mesh = new THREE.Group();
        break;
      }}
      if (geo.top_texture && geo.top_texture.kind === 'hole_grid') {{
        // per-face materials: textured top, plain metal skirt on the other five faces
        const topMat = makeMaterial(geo.material || {{}}).clone();
        topMat.map = odHolePlateTexture(geo.top_texture);
        topMat.color = new THREE.Color('#ffffff'); // the texture carries the plate color
        topMat.needsUpdate = true;
        const sideMat = makeMaterial(geo.material || {{}}).clone();
        if (geo.top_texture.side) sideMat.color = new THREE.Color(geo.top_texture.side);
        mesh = new THREE.Mesh(
          new THREE.BoxGeometry(...boxSize),
          [sideMat, sideMat, topMat, sideMat, sideMat, sideMat]
        );
      }} else {{
        mesh = new THREE.Mesh(
          new THREE.BoxGeometry(...boxSize),
          makeMaterial(geo.material || {{}})
        );
      }}
      break;
    case 'cylinder':
      mesh = new THREE.Mesh(
        new THREE.CylinderGeometry(geo.radius || 1, geo.radius || 1, geo.height || 1, 32),
        makeMaterial(geo.material || {{}})
      );
      break;
    case 'sphere':
      mesh = new THREE.Mesh(
        new THREE.SphereGeometry(geo.radius || 1, 32, 32),
        makeMaterial(geo.material || {{}})
      );
      break;
    case 'torus':
      mesh = new THREE.Mesh(
        new THREE.TorusGeometry(geo.radius || 1, geo.tube || 0.2, 18, 96),
        makeMaterial(geo.material || {{}})
      );
      break;
    case 'extruded_polygon':
      const polygonPoints = geo.points || [];
      if (polygonPoints.length < 3) {{
        mesh = new THREE.Group();
        break;
      }}
      const shape = new THREE.Shape();
      shape.moveTo(polygonPoints[0][0], polygonPoints[0][1]);
      for (const point of polygonPoints.slice(1)) {{
        shape.lineTo(point[0], point[1]);
      }}
      // holes (e.g. OX_OPEN / deep-trench openings carved out of the SiO2 cladding)
      for (const hole of (geo.holes || [])) {{
        if (!hole || hole.length < 3) continue;
        const path = new THREE.Path();
        path.moveTo(hole[0][0], hole[0][1]);
        for (const pt of hole.slice(1)) path.lineTo(pt[0], pt[1]);
        shape.holes.push(path);
      }}
      let extrudedGeometry = new THREE.ExtrudeGeometry(shape, {{
        depth: geo.height || 0.22,
        bevelEnabled: false,
        curveSegments: 24,
        steps: 1,
      }});
      extrudedGeometry.rotateX(-Math.PI / 2);
      // Smooth curved walls (rings, bends) while keeping rectilinear corners crisp:
      // creased-normals blends faces meeting below ~50deg and splits sharper edges.
      extrudedGeometry = toCreasedNormals(extrudedGeometry, (50 * Math.PI) / 180);
      mesh = new THREE.Mesh(extrudedGeometry, makeMaterial(geo.material || {{}}));
      // outline edges (incl. hole walls) — makes etched openings legible in faint glass
      if (geo.edges) {{
        const eg = new THREE.EdgesGeometry(extrudedGeometry, 1);
        const eo = geo.edge_opacity !== undefined ? geo.edge_opacity : 1.0;
        const lines = new THREE.LineSegments(eg, new THREE.LineBasicMaterial({{ color: new THREE.Color(geo.edges), transparent: eo < 1, opacity: eo }}));
        lines.renderOrder = 3;
        mesh.add(lines);
      }}
      break;
    case 'lathe_profile': {{
      // lathed side-profile (solder bumps): points are [radius, height] pairs
      const lpts = (geo.points || []).map(p => new THREE.Vector2(p[0], p[1]));
      if (lpts.length < 2) {{ mesh = new THREE.Group(); break; }}
      // crease like an extrusion: the round stays smooth, a flat ring keeps its sharp corners (smoothed
      // corners shaded a flat retaining ring like a rounded chrome donut)
      mesh = new THREE.Mesh(
        toCreasedNormals(new THREE.LatheGeometry(lpts, geo.segments || 24), (50 * Math.PI) / 180),
        makeMaterial(geo.material || {{}})
      );
      break;
    }}
    case 'tube_path': {{
      // swept tube along a smooth curve (wirebonds, bond wires)
      const tpts = (geo.points || []).map(p => new THREE.Vector3(p[0], p[1], p[2]));
      if (tpts.length < 2) {{ mesh = new THREE.Group(); break; }}
      const tcurve = new THREE.CatmullRomCurve3(tpts);
      mesh = new THREE.Mesh(
        new THREE.TubeGeometry(tcurve, geo.segments || 32, geo.radius || 0.2, geo.radialSegments || 12, false),
        makeMaterial(geo.material || {{}})
      );
      break;
    }}
    case 'text_sprite': {{
      // in-scene text decal (chip top markings) drawn to a canvas texture
      const tcanvas = document.createElement('canvas');
      tcanvas.width = 512; tcanvas.height = 256;
      const tctx = tcanvas.getContext('2d');
      tctx.clearRect(0, 0, 512, 256);
      tctx.fillStyle = geo.color || '#ffffff';
      tctx.font = (geo.fontWeight || '700') + ' ' + Math.min(geo.fontSize || 120, 200) + 'px sans-serif';
      tctx.textAlign = 'center'; tctx.textBaseline = 'middle';
      tctx.fillText(geo.text || '', 256, 128);
      const ttex = new THREE.CanvasTexture(tcanvas);
      ttex.anisotropy = 4;
      const smat = new THREE.SpriteMaterial({{ map: ttex, transparent: true, depthWrite: false }});
      mesh = new THREE.Sprite(smat);
      mesh.scale.set(geo.width || 4, geo.height || 2, 1);
      break;
    }}
    case 'text_decal': {{
      // flat text label printed onto a surface (rotates WITH the part, not a billboard)
      const dcanvas = document.createElement('canvas');
      dcanvas.width = 512; dcanvas.height = 256;
      const dctx = dcanvas.getContext('2d');
      dctx.clearRect(0, 0, 512, 256);
      dctx.fillStyle = geo.color || '#ffffff';
      dctx.font = (geo.fontWeight || '700') + ' ' + Math.min(geo.fontSize || 140, 230) + 'px sans-serif';
      dctx.textAlign = 'center'; dctx.textBaseline = 'middle';
      dctx.fillText(geo.text || '', 256, 128);
      const dtex = new THREE.CanvasTexture(dcanvas);
      dtex.anisotropy = 4;
      const dmat = new THREE.MeshBasicMaterial({{ map: dtex, transparent: true, depthWrite: false, side: THREE.DoubleSide }});
      mesh = new THREE.Mesh(new THREE.PlaneGeometry(geo.width || 4, geo.height || 2), dmat);
      break;
    }}
    default:
      mesh = new THREE.Mesh(
        new THREE.BoxGeometry(2, 2, 2),
        new THREE.MeshStandardMaterial({{ color: 0xff00ff }})
      );
  }}
  mesh.castShadow = true;
  mesh.receiveShadow = true;

  // Add children (sub-parts)
  if (geo.children) {{
    for (const childGeo of geo.children) {{
      const childMesh = makeGeometry(childGeo);
      mesh.add(childMesh);
    }}
  }}
  if (geo.position) mesh.position.set(...geo.position);
  if (geo.rotation) mesh.rotation.set(...geo.rotation);
  if (geo.scale) mesh.scale.set(...geo.scale);
  return mesh;
}}

function addLabel(parent, text) {{
  const div = document.createElement('div');
  div.textContent = text;
  div.style.cssText = 'color: #3a4654; font-size: 10px; font-weight: 600; background: rgba(255,255,255,0.66); padding: 1px 5px; border-radius: 4px; border: 1px solid rgba(24,34,45,0.06); pointer-events: none; white-space: nowrap;';
  const label = new CSS2DObject(div);
  label.position.set(0, 6, 0);
  parent.add(label);
}}

function liftToTable(mesh, targetY = 0) {{
  if (!liftMeshesToTable) return;
  const bounds = new THREE.Box3().setFromObject(mesh);
  if (!Number.isFinite(bounds.min.y)) return;
  if (bounds.min.y < targetY) mesh.position.y += targetY - bounds.min.y;
}}

// All scene content is built into a single group so the editor can rebuild it
// in place (no iframe reload). Inside odBuildAll we shadow `scene` with this
// group, so every existing `scene.add(...)` below routes into it unchanged.
const odContent = new THREE.Group();
scene.add(odContent);
const BEAM_PLANE = {k.beam_plane}; // optical-axis height (units above the table; per-scene)
const CHIP_Z = {k.chip_z}; // schematic chip parts and chip routes are drawn this much taller
const BOARD_TOP = {k.board_top:.2f}; // tallest table/breadboard/baseplate top — posts and flat mounts sit here
const _POST_ALU = new THREE.MeshStandardMaterial({{ color: 0xc4c9cf, metalness: 0.88, roughness: 0.22 }});   // brushed post
const _POST_ANOD = new THREE.MeshStandardMaterial({{ color: 0x22272d, metalness: 0.45, roughness: 0.55 }});  // anodised base/holder
// Mounting hardware, measured off the real parts (cad/post_assembly.py) and
// expressed against the Ø1in optic optodraw draws at 10 units:
//   Ø1/2in post 0.50a · post-holder OD 0.75a · pedestal base 1.5a · base 0.37a thick
// These were all ~4x too small, as if the hardware were metres while the optics
// were inches — the pedestals read as pins under the optics they carry.
const OPTIC_UNIT = 10.0;
const POST_R = OPTIC_UNIT * 0.25;      // Ø0.50a
const HOLDER_R = OPTIC_UNIT * 0.374;   // Ø0.75a
const PED_BASE_R = OPTIC_UNIT * 0.75;  // Ø1.50a
const PED_BASE_T = OPTIC_UNIT * 0.374;
const HOLDER_H = OPTIC_UNIT * 0.6;   // the post holder above the base
function odAddPost(scene, x, z, topY) {{
  // Thorlabs-style pedestal: round base + anodised post-holder + brushed post.
  // The post rises to topY = the DEVICE BOTTOM (not the beam axis), so the silver
  // post always pushes up against the underside and never pierces the optic.
  // Posts sit on BOARD_TOP (tallest table/breadboard/baseplate top), not at 0,
  // so they do not sink into the board.
  // Base and holder are fixed parts, the same under every optic; the brushed post takes the rest of the
  // height. They shrink only when an optic is too large for them (holder at most 60% of the rise).
  const grp = new THREE.Group();
  const rawTop = topY === undefined ? BEAM_PLANE : topY;
  const H = Math.max(rawTop - BOARD_TOP, 2.4);
  const baseH = Math.min(PED_BASE_T, H * 0.22), postR = POST_R, holderR = HOLDER_R;
  const holderH = Math.min(HOLDER_H, (H - baseH) * 0.6);
  const base = new THREE.Mesh(new THREE.CylinderGeometry(PED_BASE_R * 0.92, PED_BASE_R, baseH, 28), _POST_ANOD);
  base.position.y = baseH / 2; grp.add(base);
  const holder = new THREE.Mesh(new THREE.CylinderGeometry(holderR, holderR, holderH, 22), _POST_ANOD);
  holder.position.y = baseH + holderH / 2; grp.add(holder);
  const collar = new THREE.Mesh(new THREE.CylinderGeometry(holderR * 0.82, holderR * 0.82, 0.5, 22), _POST_ALU);
  collar.position.y = baseH + holderH; grp.add(collar);
  const postH = H - baseH - holderH * 0.7;
  const post = new THREE.Mesh(new THREE.CylinderGeometry(postR, postR, postH, 20), _POST_ALU);
  post.position.y = baseH + holderH * 0.7 + postH / 2; grp.add(post);
  grp.position.set(x, BOARD_TOP, z);
  grp.traverse((o) => {{ if (o.isMesh) {{ o.castShadow = true; o.receiveShadow = true; }} }});
  scene.add(grp);
}}
const _STAGE_BODY = new THREE.MeshStandardMaterial({{ color: 0x2b3037, metalness: 0.5, roughness: 0.5 }});
const _STAGE_TOP = new THREE.MeshStandardMaterial({{ color: 0x3b424b, metalness: 0.55, roughness: 0.42 }});
// The clean post pedestal (anodised holder + brushed collar + post) from fromY up to toY,
// shared by the plain post and both stage bases so they all read consistently.
function odRiser(grp, fromY, toY) {{
  const rise = toY - fromY;
  if (rise <= 0.6) return;
  const holderH = Math.min(rise * 0.4, 5.5);
  const holder = new THREE.Mesh(new THREE.CylinderGeometry(HOLDER_R, HOLDER_R, holderH, 22), _POST_ANOD);
  holder.position.y = fromY + holderH / 2; grp.add(holder);
  const collar = new THREE.Mesh(new THREE.CylinderGeometry(POST_R * 1.3, POST_R * 1.3, 0.5, 22), _POST_ALU);
  collar.position.y = fromY + holderH; grp.add(collar);
  const postH = Math.max(rise - holderH * 0.7, 0.4);
  const post = new THREE.Mesh(new THREE.CylinderGeometry(POST_R, POST_R, postH, 20), _POST_ALU);
  post.position.y = fromY + holderH * 0.7 + postH / 2; grp.add(post);
}}
function odAddStage(scene, x, z, topY) {{
  // Translation stage on the table, then the shared post pedestal up to the DEVICE BOTTOM.
  const grp = new THREE.Group();
  const rawTop = topY === undefined ? BEAM_PLANE : topY;
  const H = Math.max(rawTop - BOARD_TOP, 4.0);
  const baseH = OPTIC_UNIT * 0.22, topH = OPTIC_UNIT * 0.14, sw = OPTIC_UNIT * 2.0, sd = OPTIC_UNIT * 1.5;
  const base = new THREE.Mesh(new THREE.BoxGeometry(sw, baseH, sd), _STAGE_BODY);
  base.position.y = baseH / 2; grp.add(base);
  const top = new THREE.Mesh(new THREE.BoxGeometry(sw * 0.8, topH, sd * 0.92), _STAGE_TOP);
  top.position.y = baseH + topH / 2; grp.add(top);
  // micrometer barrel + thimble on the +x end
  const barrel = new THREE.Mesh(new THREE.CylinderGeometry(0.5, 0.5, sw * 0.42, 16), _POST_ALU);
  barrel.rotation.z = Math.PI / 2; barrel.position.set(sw * 0.6, baseH + topH * 0.3, 0); grp.add(barrel);
  const thimble = new THREE.Mesh(new THREE.CylinderGeometry(0.66, 0.66, sw * 0.16, 16), _POST_ANOD);
  thimble.rotation.z = Math.PI / 2; thimble.position.set(sw * 0.88, baseH + topH * 0.3, 0); grp.add(thimble);
  odRiser(grp, baseH + topH, H);
  grp.position.set(x, BOARD_TOP, z);
  grp.traverse((o) => {{ if (o.isMesh) {{ o.castShadow = true; o.receiveShadow = true; }} }});
  scene.add(grp);
}}
function odAddXYZStage(scene, x, z, topY) {{
  // Three axes: an x stage, a y stage crossed on it and a z lift, then the shared riser to the device bottom.
  const grp = new THREE.Group();
  const rawTop = topY === undefined ? BEAM_PLANE : topY;
  const H = Math.max(rawTop - BOARD_TOP, 4.0);
  const baseH = OPTIC_UNIT * 0.2, sw = OPTIC_UNIT * 2.0, sd = OPTIC_UNIT * 1.5, zH = OPTIC_UNIT * 0.6;
  const xs = new THREE.Mesh(new THREE.BoxGeometry(sw, baseH, sd), _STAGE_BODY);
  xs.position.y = baseH / 2; grp.add(xs);
  const ys = new THREE.Mesh(new THREE.BoxGeometry(sd, baseH, sw), _STAGE_TOP);
  ys.position.y = baseH * 1.5; grp.add(ys);
  const zs = new THREE.Mesh(new THREE.BoxGeometry(sd * 0.7, zH, sd * 0.7), _STAGE_BODY);
  zs.position.y = baseH * 2 + zH / 2; grp.add(zs);
  // a micrometer on each axis
  const mx = new THREE.Mesh(new THREE.CylinderGeometry(0.5, 0.5, sw * 0.4, 16), _POST_ALU);
  mx.rotation.z = Math.PI / 2; mx.position.set(sw * 0.6, baseH * 0.5, 0); grp.add(mx);
  const my = new THREE.Mesh(new THREE.CylinderGeometry(0.5, 0.5, sw * 0.4, 16), _POST_ALU);
  my.rotation.x = Math.PI / 2; my.position.set(0, baseH * 1.5, sw * 0.6); grp.add(my);
  const mz = new THREE.Mesh(new THREE.CylinderGeometry(0.45, 0.45, zH * 0.8, 16), _POST_ANOD);
  mz.position.set(sd * 0.48, baseH * 2 + zH / 2, 0); grp.add(mz);
  odRiser(grp, baseH * 2 + zH, H);
  grp.position.set(x, BOARD_TOP, z);
  grp.traverse((o) => {{ if (o.isMesh) {{ o.castShadow = true; o.receiveShadow = true; }} }});
  scene.add(grp);
}}
function odAddRotationStage(scene, x, z, topY) {{
  // Rotary rotation stage: a round graduated platform on the table + the shared post
  // pedestal up to the DEVICE BOTTOM. Distinct round silhouette vs the translation stage.
  const grp = new THREE.Group();
  const rawTop = topY === undefined ? BEAM_PLANE : topY;
  const H = Math.max(rawTop - BOARD_TOP, 4.0);
  const baseH = OPTIC_UNIT * 0.24, r = OPTIC_UNIT * 1.0;
  const base = new THREE.Mesh(new THREE.CylinderGeometry(r, r * 1.06, baseH, 36), _STAGE_BODY);
  base.position.y = baseH / 2; grp.add(base);
  // brushed rotating dial + graduation ticks around its rim
  const dial = new THREE.Mesh(new THREE.CylinderGeometry(r * 0.9, r * 0.9, 0.5, 36), _POST_ALU);
  dial.position.y = baseH + 0.25; grp.add(dial);
  for (let i = 0; i < 24; i++) {{
    const a = i * Math.PI / 12;
    const tick = new THREE.Mesh(new THREE.BoxGeometry(0.1, 0.55, 0.5), _STAGE_BODY);
    tick.position.set(Math.cos(a) * r * 0.88, baseH + 0.25, Math.sin(a) * r * 0.88);
    tick.rotation.y = -a; grp.add(tick);
  }}
  // radial locking thumbscrew on the side
  const screw = new THREE.Mesh(new THREE.CylinderGeometry(0.5, 0.5, 1.4, 14), _POST_ALU);
  screw.rotation.z = Math.PI / 2; screw.position.set(r + 0.5, baseH * 0.55, 0); grp.add(screw);
  odRiser(grp, baseH + 0.5, H);
  grp.position.set(x, BOARD_TOP, z);
  grp.traverse((o) => {{ if (o.isMesh) {{ o.castShadow = true; o.receiveShadow = true; }} }});
  scene.add(grp);
}}
function odAddPort3D(scene, x, z, lift) {{
  // small marker at a port, on the beam plane (lift: the run's height above it, after a periscope)
  const m = new THREE.Mesh(
    new THREE.SphereGeometry(0.7, 12, 12),
    new THREE.MeshStandardMaterial({{ color: 0x2563eb, emissive: 0x2563eb, emissiveIntensity: 0.5, roughness: 0.4 }})
  );
  m.position.set(x, BEAM_PLANE + (lift || 0), z);
  scene.add(m);
}}
window.__odPickables = [];
// Round polyline corners with quadratic arcs (waveguide bends — light can't turn
// sharp corners). Radius clamps to half the shorter adjacent segment.
function odFillet(pts, radius) {{
  if (!pts || pts.length < 3 || !(radius > 0)) return pts;
  const out = [pts[0]];
  for (let i = 1; i < pts.length - 1; i++) {{
    const p = pts[i], a = pts[i - 1], b = pts[i + 1];
    const da = p.clone().sub(a), db = b.clone().sub(p);
    const la = da.length(), lb = db.length();
    const rr = Math.min(radius, la * 0.49, lb * 0.49);
    if (rr < 0.05 || la < 1e-6 || lb < 1e-6) {{ out.push(p.clone()); continue; }}
    da.normalize(); db.normalize();
    if (Math.abs(da.dot(db)) > 0.999) {{ out.push(p.clone()); continue; }} // collinear
    const pA = p.clone().addScaledVector(da, -rr);
    const pB = p.clone().addScaledVector(db, rr);
    out.push(pA);
    for (let k = 1; k < 8; k++) {{
      const t = k / 8;
      out.push(pA.clone().multiplyScalar((1 - t) * (1 - t))
        .addScaledVector(p, 2 * t * (1 - t)).addScaledVector(pB, t * t));
    }}
    out.push(pB);
  }}
  out.push(pts[pts.length - 1]);
  return out;
}}
function odBuildAll(data) {{
  odNote(data);
  odClearResources();
  data = odExpandSceneData(data);
  const scene = odContent;
  window.__odPickables = [];
  for (const item of data) {{
  if (item.type === 'mesh' && item.geometry) {{
    const mesh = makeGeometry(item.geometry);
    // Measure the geometry BEFORE parenting it: Box3.setFromObject reports WORLD
    // bounds, so once the anchor is positioned this same call returns world
    // coordinates and adding the position again throws the post across the table.
    mesh.updateMatrixWorld(true);
    const _lb = new THREE.Box3().setFromObject(mesh);
    const anchor = new THREE.Group();
    anchor.userData.odComponent = true;
    anchor.add(mesh);
    // Orient FIRST: the post is placed from the anchor's world bounds, and a
    // mount stack that sits behind the glass swings around with the optic.
    // Measuring before the rotation put a folding mirror's post out along world
    // +x while its mount leaned the other way — visibly off its own post.
    anchor.rotation.set(...item.rotation);
    if (item.beamPlane) {{
      // Mount height modes:
      //  "post" (default): post to device bottom → aperture-dependent height, most realistic
      //  "post_beam": post to beam axis → uniform height regardless of aperture
      //  "stage"/"rotation_stage": stage to device bottom
      //  "none": no post (optic floats, e.g. for custom rigs)
      // a part after a periscope rides at its exit height; z raises a part above the beam plane (item.position[1])
      const _axis = BEAM_PLANE + (item.lift || 0) + (item.position[1] || 0);
      anchor.position.set(item.position[0], _axis, item.position[2]);
      anchor.updateMatrixWorld(true);
      const _wb = new THREE.Box3().setFromObject(anchor);
      const _bottom = isFinite(_wb.min.y) ? _wb.min.y : _axis;
      // the post stands under the MOUNT, not the optical anchor: an optic whose
      // hardware sits behind the glass (mirror, waveplate) is carried from behind
      // a part can name the point its post holds (``post_at``, local x, y, z): a micrometer or a knob on one
      // side moves the middle of the bounds away from the stem
      // a part turned out of the table plane (rotation about x or y): its post_at turns with it. The post
      // holds that point while it stays in the lower part of the part; turned on its side, the part stands on
      // its lowest point instead
      let _pa = item.geometry.post_at;
      let _tilt = null;
      if (item.tilted) {{
        if (_pa) {{
          const _w = anchor.localToWorld(new THREE.Vector3(_pa[0], _pa[1], _pa[2]));
          if (_w.y <= _bottom + 0.35 * (_wb.max.y - _wb.min.y)) _tilt = [_w.x, _w.y, _w.z];
        }}
        if (!_tilt) {{                     // the part's lowest point: the corner a tilted mount rests on
          let _low = null;
          const _v = new THREE.Vector3();
          anchor.traverse(o => {{
            const a = o.isMesh && o.geometry && o.geometry.attributes.position;
            if (!a) return;
            const step = Math.max(1, Math.floor(a.count / 400));
            for (let i = 0; i < a.count; i += step) {{
              _v.fromBufferAttribute(a, i).applyMatrix4(o.matrixWorld);
              if (!_low || _v.y < _low.y) _low = _v.clone();
            }}
          }});
          _tilt = _low ? [_low.x, _low.y, _low.z] : [(_wb.min.x + _wb.max.x) / 2, _bottom, (_wb.min.z + _wb.max.z) / 2];
        }}
        _pa = null;
      }}
      const _yaw = item.rotation ? item.rotation[1] : 0;
      const _lx = _pa ? _pa[0] : (isFinite(_lb.min.x) ? (_lb.min.x + _lb.max.x) / 2 : 0);
      const _lz = _pa ? _pa[2] : (isFinite(_lb.min.z) ? (_lb.min.z + _lb.max.z) / 2 : 0);
      const _px = _tilt ? _tilt[0] : item.position[0] + _lx * Math.cos(_yaw) + _lz * Math.sin(_yaw);
      const _pz = _tilt ? _tilt[2] : item.position[2] - _lx * Math.sin(_yaw) + _lz * Math.cos(_yaw);
      const _postTop = item.mountHeight !== undefined ? item.mountHeight : (_tilt ? _tilt[1] : _pa ? _axis + _pa[1] : _bottom) + 0.15;
      const _beamTop = item.mountHeight !== undefined ? item.mountHeight : _axis;
      if (item.baseMount === 'stage') odAddStage(scene, _px, _pz, _postTop);
      else if (item.baseMount === 'xyz_stage') odAddXYZStage(scene, _px, _pz, _postTop);
      else if (item.baseMount === 'rotation_stage') odAddRotationStage(scene, _px, _pz, _postTop);
      else if (item.baseMount === 'post_beam') odAddPost(scene, _px, _pz, _beamTop);
      else if (item.baseMount === 'none') {{}} // no post
      else odAddPost(scene, _px, _pz, _postTop);
      // Ports remain in scene data for connections, without visible marker spheres.
    }} else {{
      if (item.zScale) mesh.scale.y *= CHIP_Z;
      liftToTable(mesh, item.board ? 0 : BOARD_TOP);
      anchor.position.set(...item.position);
      if (CHIP_LIFT > 0 && item.chip) anchor.position.y += CHIP_LIFT;
    }}
    if (item.localScale) anchor.scale.set(...item.localScale);
    anchor.userData.odSid = item.sid;
    anchor.userData.componentId = item.componentId;
    anchor.userData.movable = true;
    if (item.componentId) window.__odPickables.push(anchor);
    scene.add(anchor);
    if (item.chip) {{ anchor.updateMatrixWorld(true); window.__odChipBox.expandByObject(anchor); }}
    {'if (item.label) addLabel(anchor, item.label);' if self.show_labels else ''}
  }} else if (item.type === 'beam' && item.points && item.points.length >= 2) {{
    // free-space beams ride the beam plane (not the floor)
    const points = item.points.map(p => new THREE.Vector3(p[0], p[1] + BEAM_PLANE, p[2]));
    const linkGroup = new THREE.Group();
    // Beam tube
    for (let i = 0; i < points.length - 1; i++) {{
      const start = points[i], end = points[i + 1];
      const dir = new THREE.Vector3().subVectors(end, start);
      const len = dir.length();
      const tubeRadius = (item.width || 0.8) * 0.3;
      const tubeGeo = new THREE.CylinderGeometry(tubeRadius, tubeRadius, len, 8);
      const tubeMat = new THREE.MeshStandardMaterial({{
        color: new THREE.Color(item.color || '#ff0000'),
        emissive: new THREE.Color(item.color || '#ff0000'),
        emissiveIntensity: 1.5,
        transparent: true,
        opacity: 0.7,
      }});
      const tube = new THREE.Mesh(tubeGeo, tubeMat);
      const mid = new THREE.Vector3().addVectors(start, end).multiplyScalar(0.5);
      tube.position.copy(mid);
      tube.lookAt(end);
      tube.rotateX(Math.PI / 2);
      linkGroup.add(tube);
    }}
    // Glow line
    const lineMat = new THREE.LineBasicMaterial({{
      color: new THREE.Color(item.color || '#ff0000'),
      linewidth: 2,
    }});
    const lineGeo = new THREE.BufferGeometry().setFromPoints(points);
    linkGroup.add(new THREE.Line(lineGeo, lineMat));
    linkGroup.userData.odSid = item.sid;
    linkGroup.userData.componentId = item.componentId;
    linkGroup.userData.movable = false; // beams follow ports; selectable, not draggable
    if (item.componentId) window.__odPickables.push(linkGroup);
    scene.add(linkGroup);
  }} else if (item.type === 'route' && item.points && item.points.length >= 2) {{
    const rawPoints = item.points.map(p => new THREE.Vector3(...p));
    const isElec = item.kind === 'electrical';
    if (item.cable) {{
      // bench wiring: a round insulated cable resting on the table — NOT the
      // on-chip metal-deposition strip (that stays for chip electrical routes)
      const cablePts = odFillet(rawPoints, 4);
      const cableR = Math.min(Math.max((item.width || 1) * 0.22, 0.4), item.kind === 'fiber' ? 0.5 : 0.75);
      const cableMat = new THREE.MeshStandardMaterial({{ color: new THREE.Color(item.color || '#2a2d33'), roughness: 0.62, metalness: 0.08 }});
      const cableGroup = new THREE.Group();
      // run at connector height; a chip-side end turns and DROPS vertically
      // onto the pad / grating coupler (the vertical leg that matters)
      const CABLE_Y = {k.lead_height};
      // on the board top when there is one: the fibre parts lie there, so must their cables
      let runPts = cablePts.map(p => {{ const q = p.clone(); q.y += BOARD_TOP + CABLE_Y; return q; }});
      if (item.cableDrop) {{
        const di = item.cableDrop === 'start' ? 0 : runPts.length - 1;
        const pad = cablePts[di].clone(); pad.y += 0.4 * CHIP_Z + CHIP_LIFT; // land just above the (lifted, taller) metal
        const benchY = cablePts[di].y + BOARD_TOP + CABLE_Y;
        // the REAL die box (mesh extents, filled as chip items are built): a cable
        // rides UP at the die edge and travels on top — it never tunnels through
        const foot = odDieFootprint(window.__odChipBox.isEmpty() ? chipRoughBounds : window.__odChipBox);
        const onDie = p => !!foot && Math.abs(p.x - foot.cx) <= foot.hx && Math.abs(p.z - foot.cz) <= foot.hz;
        const path = item.cableDrop === 'start' ? runPts.slice().reverse() : runPts.slice();
        path[path.length - 1] = pad;  // walk bench-end -> pad, so the climb reads forwards
        const run = [];
        let climbed = false;
        for (const p of path) {{
          if (!climbed && onDie(p)) {{
            climbed = true;
            const prev = run.length ? run[run.length - 1] : null;
            const edge = prev ? odFootprintEntry(prev, p, foot) : {{ x: p.x, z: p.z }};
            if (edge) run.push(new THREE.Vector3(edge.x, benchY, edge.z), new THREE.Vector3(edge.x, pad.y, edge.z));
          }}
          run.push(climbed ? new THREE.Vector3(p.x, Math.max(p.y, pad.y), p.z) : p);
        }}
        runPts = item.cableDrop === 'start' ? run.reverse() : run;
      }}
      (item.cableRise || []).forEach((rises, index) => {{
        if (!rises) return;
        const benchY = BOARD_TOP + CABLE_Y;
        const raised = odCableRise(runPts.map((q) => [q.x, q.y, q.z]), index === 0, BEAM_PLANE, benchY);
        runPts = raised.map((q) => new THREE.Vector3(q[0], q[1], q[2]));
      }});
      // ONE swept tube — butted cylinders + joint spheres read as a dashed line
      // once the camera pulls back (every seam aliases against the background)
      const spine = runPts.filter((p, i) => i === 0 || p.distanceTo(runPts[i - 1]) > 1e-3);
      if (spine.length >= 2) {{
        const curve = new THREE.CatmullRomCurve3(spine, false, 'centripetal', 0.4);
        const steps = Math.min(400, Math.max(32, spine.length * 12));
        cableGroup.add(new THREE.Mesh(new THREE.TubeGeometry(curve, steps, cableR, 10, false), cableMat));
        cableGroup.userData.odCable = {{ curve, radius: cableR }};   // light in a fibre follows the cable
      }}
      cableGroup.userData.odSid = item.sid;
      cableGroup.userData.componentId = item.componentId;
      cableGroup.userData.movable = false;
      if (item.componentId) window.__odPickables.push(cableGroup);
      scene.add(cableGroup);
      continue;
    }}
    // optical waveguides bend smoothly (light can't turn sharp corners); metal can
    const points = isElec ? rawPoints : odFillet(rawPoints, item.bendRadius || 6);
    const routeColor = new THREE.Color(item.color || '#2d6cdf');
    // Fabricated routes are FLAT, sharp-edged strips — a deposited metal trace
    // (electrical) or a strip waveguide (optical, as in GDS) — never round rods.
    const stripWidth = Math.max(item.width || 0.5, 0.2);
    const stripWidth2 = item.width2 ? Math.max(item.width2, 0.2) : null; // taper end width
    // the parts' own silicon or metal height when the route carries it, else metal deposition vs Si strip
    const stripScale = item.stripThick !== undefined ? (item.stripScale ? CHIP_Z : 1) : (item.chip ? CHIP_Z : 1);
    const stripThick = (item.stripThick !== undefined ? item.stripThick : (isElec ? 0.35 : 0.22)) * stripScale;
    const stripZ = (item.stripZ || 0) * stripScale;
    // the material of the parts it joins when the route carries it: one material, no band at the joints
    const stripMat = item.stripMaterial ? makeMaterial({{ ...item.stripMaterial }}) : new THREE.MeshStandardMaterial({{
      color: routeColor,
      roughness: isElec ? 0.32 : 0.5,
      metalness: isElec ? 0.74 : 0.12,
      flatShading: true, // crisp, sharp-edged faces
    }});
    const linkGroup = new THREE.Group();
    const addStrip = (geo, pos, rotY) => {{
      const m = new THREE.Mesh(geo, stripMat);
      m.position.copy(pos);
      m.rotation.y = rotY;
      linkGroup.add(m);
    }};
    // arclength table so a tapered route lerps its width start -> end
    const segLens = [];
    let routeLen = 0;
    for (let i = 0; i < points.length - 1; i++) {{
      const l = points[i + 1].distanceTo(points[i]);
      segLens.push(l); routeLen += l;
    }}
    let run = 0;
    for (let i = 0; i < points.length - 1; i++) {{
      const start = points[i], end = points[i + 1];
      const dir = new THREE.Vector3().subVectors(end, start);
      const len = dir.length();
      if (len < 1e-4) {{ run += segLens[i]; continue; }}
      const mid = new THREE.Vector3().addVectors(start, end).multiplyScalar(0.5);
      mid.y += stripZ + stripThick / 2; // rest the strip flat on its level
      const t = routeLen > 0 ? (run + segLens[i] / 2) / routeLen : 0;
      const w = stripWidth2 === null ? stripWidth : stripWidth + (stripWidth2 - stripWidth) * t;
      // BoxGeometry(length, thickness, width): length along the segment, width flat
      addStrip(new THREE.BoxGeometry(len, stripThick, w), mid, Math.atan2(-dir.z, dir.x));
      run += segLens[i];
    }}
    // square fillers only at real corners so 90° bends read as solid metal
    for (let i = 1; i < points.length - 1; i++) {{
      const a = new THREE.Vector3().subVectors(points[i], points[i - 1]);
      const b = new THREE.Vector3().subVectors(points[i + 1], points[i]);
      if (a.length() < 1e-4 || b.length() < 1e-4 || a.angleTo(b) < 0.26) continue;
      const v = points[i].clone();
      v.y += stripZ + stripThick / 2;
      addStrip(new THREE.BoxGeometry(stripWidth, stripThick, stripWidth), v, 0);
    }}
    if (CHIP_LIFT > 0 && item.chip) linkGroup.position.y += CHIP_LIFT;
    linkGroup.userData.odSid = item.sid;
    // the drawn strip, for the light player: its centreline (before the group's lift), mid-height and size
    linkGroup.userData.odStrip = {{ points, mid: stripZ + stripThick / 2, thick: stripThick, width: stripWidth }};
    linkGroup.userData.componentId = item.componentId;
    linkGroup.userData.movable = false; // routes follow ports; selectable, not draggable
    if (item.componentId) window.__odPickables.push(linkGroup);
    scene.add(linkGroup);
    if (item.chip) {{ linkGroup.updateMatrixWorld(true); window.__odChipBox.expandByObject(linkGroup); }}
  }} else if (item.type === 'external_model' && item.geometry) {{
    const geo = item.geometry;
    const addFallback = () => {{
      const fallback = new THREE.Mesh(
        new THREE.BoxGeometry(geo.width || 10, geo.height || 10, geo.depth || geo.width || 10),
        new THREE.MeshStandardMaterial({{ color: new THREE.Color((geo.material && geo.material.color) || '#6c757d'), wireframe: true }})
      );
      fallback.position.set(...item.position);
      fallback.rotation.set(...item.rotation);
      scene.add(fallback);
      {'if (item.label) addLabel(fallback, item.label);' if self.show_labels else ''}
    }};

    const placeModel = (object3d) => {{
      object3d.position.set(...item.position);
      object3d.rotation.set(...item.rotation);
      const modelScale = geo.scale || 1;
      object3d.scale.set(modelScale, modelScale, modelScale);
      scene.add(object3d);
      {'if (item.label) addLabel(object3d, item.label);' if self.show_labels else ''}
    }};

    const format = (geo.format || 'gltf').toLowerCase();
    if (format === 'obj') {{
      new OBJLoader().load(geo.source, placeModel, undefined, addFallback);
    }} else if (format === 'gltf' || format === 'glb') {{
      new GLTFLoader().load(geo.source, (gltf) => placeModel(gltf.scene), undefined, addFallback);
    }} else {{
      addFallback();
    }}
  }}
}}
}}
// what 3D leaves out, named in the note: the layers a part has no height for, and the insets (2D only); no note
// when nothing is left out
function odNote(data) {{
  const note = document.getElementById('od-note');
  if (!note) return;
  const parts = data.filter((item) => item.noHeight && item.noHeight.length)
    .map((item) => (item.label ? item.label + ' ' : '') + item.noHeight.join(', '));
  const layers = parts.length ? 'Not in 3D, no height assigned: ' + parts.join('; ')
    + '. Give each a thickness and z in the layer stack.' : '';
  note.textContent = [layers, odViewsNote].filter(Boolean).join(' ');
  note.hidden = !note.textContent;
}}
odBuildAll(sceneData);
// now that the real device meshes exist, refit the on-chip die to their true footprint
if ({str(k.show_grid).lower()}) odBuildOnChipBase(MIXED ? window.__odChipBox : new THREE.Box3().setFromObject(odContent));
// frame the camera on the real meshes (their bounding sphere), not on the parts' centres
function odFitDistance(box, margin) {{
  const sphere = box.getBoundingSphere(new THREE.Sphere());
  const vfov = THREE.MathUtils.degToRad(camera.fov);
  const hfov = 2 * Math.atan(Math.tan(vfov / 2) * camera.aspect);
  return Math.max(sphere.radius, 1e-3) / Math.sin(Math.min(vfov, hfov) / 2) * margin;
}}
// the corners of a box (all eight)
function odBoxCorners(b, out) {{
  if (!b.isEmpty()) for (const x of [b.min.x, b.max.x]) for (const y of [b.min.y, b.max.y]) for (const z of [b.min.z, b.max.z]) out.push(new THREE.Vector3(x, y, z));
  return out;
}}
// fill: the share of the frame the content's projected box may take (0.9 = tight)
function odFrameToContent(fill) {{
  const box = new THREE.Box3().setFromObject(odContent);
  if (box.isEmpty()) return;
  for (const m of _onChipBase) box.expandByObject(m);              // a chip is framed with its die and carrier rim
  // the corners of each part's own box: one box round an L-shaped bench frames its empty corner
  const corners = [];
  odContent.children.forEach((child) => {{ if (child.visible) odBoxCorners(new THREE.Box3().setFromObject(child), corners); }});
  for (const m of _onChipBase) odBoxCorners(new THREE.Box3().setFromObject(m), corners);
  if (!corners.length) odBoxCorners(box, corners);
  const pose = odPoseForBox(box, corners, _initialDir, fill);
  camera.position.copy(pose.pos);
  camera.lookAt(pose.target);
  controls.target.copy(pose.target);
  controls.update();
  odFitShadow(box);
  contentBounds.copy(box); hasContentBounds = true;      // the camera buttons frame the same box
  window.__odHome = {{ pos: camera.position.clone(), target: controls.target.clone() }};
}}
// the camera pose that frames a box's corners from a direction (from the target toward the camera), with the
// projected corners taking ``fill`` of the frame; the camera does not move. Exact fit: each frustum side bounds the
// camera position by a plane through the outermost corner, so the tightest position solves two small linear systems.
function odPoseForBox(box, corners, dir, fill) {{
  const target = box.getBoundingSphere(new THREE.Sphere()).center;
  let dist = odFitDistance(box, 1.0);
  const basis = new THREE.Matrix4().lookAt(target.clone().add(dir.clone().normalize().multiplyScalar(dist)), target, camera.up);
  const r = new THREE.Vector3().setFromMatrixColumn(basis, 0);
  const u = new THREE.Vector3().setFromMatrixColumn(basis, 1);
  const f = new THREE.Vector3().setFromMatrixColumn(basis, 2).negate();
  const tV = Math.tan(THREE.MathUtils.degToRad(camera.fov) / 2) * fill, tH = tV * camera.aspect;
  let mR = -Infinity, mL = -Infinity, mU = -Infinity, mD = -Infinity;
  for (const c of corners) {{
    const x = c.dot(r), y = c.dot(u), z = c.dot(f);
    mR = Math.max(mR, x - tH * z); mL = Math.max(mL, -x - tH * z);
    mU = Math.max(mU, y - tV * z); mD = Math.max(mD, -y - tV * z);
  }}
  const back = Math.min(-(mR + mL) / (2 * tH), -(mU + mD) / (2 * tV));
  // centre each axis on screen: the near and the far extreme corners sit at different depths
  const centreOn = (axis) => {{
    const pts = corners.map((c) => [c.dot(axis), Math.max(c.dot(f) - back, 1e-6)]);
    const spread = (s) => {{ let hi = -Infinity, lo = Infinity; for (const [v, z] of pts) {{ const q = (v - s) / z; hi = Math.max(hi, q); lo = Math.min(lo, q); }} return hi + lo; }};
    let lo = Math.min(...pts.map((p) => p[0])), hi = Math.max(...pts.map((p) => p[0]));
    for (let i = 0; i < 60; i++) {{ const mid = (lo + hi) / 2; if (spread(mid) > 0) lo = mid; else hi = mid; }}
    return (lo + hi) / 2;
  }};
  const eye = r.clone().multiplyScalar(centreOn(r)).add(u.clone().multiplyScalar(centreOn(u))).add(f.clone().multiplyScalar(back));
  const centre = box.getCenter(new THREE.Vector3());
  dist = Math.max(centre.clone().sub(eye).dot(f), 1e-3);
  return {{ pos: eye, target: eye.clone().add(f.clone().multiplyScalar(dist)) }};
}}
odFrameToContent(0.8);
function odRebuild(data, light, pending) {{
  odContent.traverse((o) => {{
    if (o.geometry) o.geometry.dispose();
    if (o.material) {{ (Array.isArray(o.material) ? o.material : [o.material]).forEach((m) => m.dispose()); }}
  }});
  odContent.clear();
  window.__odChipBox = new THREE.Box3();
  odBuildAll(data);
  if ({str(k.show_grid).lower()}) odBuildOnChipBase(MIXED ? window.__odChipBox : new THREE.Box3().setFromObject(odContent));
  // the editor sends a fresh payload while the light is on, else null (no light; pending: the light comes later and
  // stays on meanwhile); a call without one keeps the page's
  if (window.odLight) window.odLight.build(light === undefined ? window.__odLightData : light, data, pending);
}}
window.__odRebuild = odRebuild;
// one frame of the view: the loop draws it, and odLight.frameAt draws it for a set time
function odRenderFrame() {{
  {render_scene_call}
  if (_labelsOn || _labelsForced) labelRenderer.render(scene, camera);
}}

{light_js}{studio_js}
applyWorld(_world);   // the first applyWorld ran before the studio code existed: now the first view gets its studio light

{export_controls_js}
{path_tracer_js}
{editor_bridge_js}
// The studio renderer's options for this view: one place for a saved image and the Photoreal button.
function odStudioOptions(width, height, extra) {{
  const w = WORLDS[_world] || WORLDS.light, none = _world === 'none';
  return Object.assign({{
    width, height, samples: 4, quality: 'final', world: _world === 'dark' || _world === 'night' ? 'dark' : 'light',
    exposure: renderer.toneMappingExposure,
    background: none ? null : {{ top: w.bgTop, bottom: w.bgBottom }},
    // a transparent image keeps its shadows on a catcher; a chip alone stands on a studio floor
    floor: none ? 'shadow' : (IS_ONCHIP && !MIXED ? 'studio' : null),
    floorColor: w.bgBottom,
  }}, extra || {{}});
}}
// --- Capture (a 3D image from Python): render once, write the PNG into the page, no loop ---
function odCapture() {{
  window.__odView = {{ THREE, scene, camera, studio: typeof odStudio === 'undefined' ? null : odStudio }};   // for checks
  const out = document.getElementById('od-capture');
  try {{
    const W = OD_CAPTURE.width, H = OD_CAPTURE.height, S = OD_CAPTURE.scale || 1;
    camera.aspect = W / H; camera.updateProjectionMatrix();
    applyWorld(OD_CAPTURE.background === 'none' ? 'none' : OD_CAPTURE.background);
    odFrameToContent(0.9);
    renderer.setPixelRatio(1);
    renderer.setSize(Math.round(W * S), Math.round(H * S), false);
    if (composer) {{ composer.setPixelRatio(1); composer.setSize(Math.round(W * S), Math.round(H * S)); composer.render(); }}
    else renderer.render(scene, camera);
{capture_studio_js}    out.value = renderer.domElement.toDataURL('image/png');
  }} catch (error) {{
    out.value = 'error: ' + (error && error.message ? error.message : String(error));
  }}
}}
// --- Animate ---
// Draw on demand: a still view draws nothing. A frame is drawn while the camera moves (orbit or its damping), while
// the light shows or a render runs, and for a short while after any input, message, resize or load, which covers
// everything that changes the scene (edits, the gizmo, menus). Shadows are drawn again only after such a change,
// never for a camera move alone: the lights stand still in the world.
let _odWakeUntil = 0, _odDrawnAt = 0;
function odWake(ms, shadows) {{
  _odWakeUntil = Math.max(_odWakeUntil, performance.now() + (ms || 700));
  if (shadows !== false) renderer.shadowMap.needsUpdate = true;
}}
window.odWake = odWake;
if (!OD_CAPTURE && !OD_VIDEO) renderer.shadowMap.autoUpdate = false;   // a capture or a video frame draws its shadows each time
renderer.shadowMap.needsUpdate = true;
for (const t of ['pointerdown', 'pointerup', 'wheel', 'keydown', 'keyup', 'message', 'resize', 'focus'])
  window.addEventListener(t, () => odWake(), {{ passive: true, capture: true }});
window.addEventListener('pointermove', () => odWake(700, false), {{ passive: true, capture: true }});   // hover or orbit: no shadow change (the gizmo wakes them itself)
document.addEventListener('visibilitychange', () => odWake());
// The camera counts as moving while a frame moves it by more than 1e-5 of its distance: the controls' damping creeps on
// by ever smaller steps for many seconds, and what it adds after that point is far below a pixel.
const _odCamPos = new THREE.Vector3(), _odCamTarget = new THREE.Vector3(), _odCamQuat = new THREE.Quaternion();
function odCameraMoved() {{
  const tol = 1e-5 * Math.max(camera.position.distanceTo(controls.target), 1e-6);
  const moved = camera.position.distanceTo(_odCamPos) > tol || controls.target.distanceTo(_odCamTarget) > tol
    || 1 - Math.abs(camera.quaternion.dot(_odCamQuat)) > 1e-10;
  if (moved) {{ _odCamPos.copy(camera.position); _odCamTarget.copy(controls.target); _odCamQuat.copy(camera.quaternion); }}
  return moved;
}}
THREE.DefaultLoadingManager.onLoad = () => odWake();
function animate() {{
  requestAnimationFrame(animate);
  controls.update();
  const moved = odCameraMoved();
  const light = window.odLight ? window.odLight.state : null;
  if (window.odLight) window.odLight.tick();
  const lit = !!(light && (light.tour || (light.group && light.group.visible)));
  if (lit) renderer.shadowMap.needsUpdate = true;   // the light's own meshes may move every frame
  const now = performance.now();
  if (!moved && !lit && !odPT.active && now > _odWakeUntil) {{
    // once a second a still view draws anyway, shadows too: work that finishes late with no event still shows
    if (now - _odDrawnAt < 1000) return;
    renderer.shadowMap.needsUpdate = true;
  }}
  _odDrawnAt = now;
  // the overhead softbox is off unless the studio light turns it up: no shadow pass for a light that gives none
  const topShadow = topLight.intensity > 0;
  if (topLight.castShadow !== topShadow) {{ topLight.castShadow = topShadow; renderer.shadowMap.needsUpdate = true; }}
  odRenderFrame();
}}
if (OD_CAPTURE) odCapture(); else if (OD_VIDEO) odRenderFrame(); else animate();

window.addEventListener('resize', () => {{
  camera.aspect = window.innerWidth / window.innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(window.innerWidth, window.innerHeight);
  renderer.setPixelRatio({pixel_ratio});{resize_composer}
  labelRenderer.setSize(window.innerWidth, window.innerHeight);
}});
</script>
{video_body}</body>
</html>"""
