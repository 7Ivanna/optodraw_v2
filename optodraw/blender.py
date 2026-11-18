"""Headless Blender script generation helpers."""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from os import PathLike
from pathlib import Path
import subprocess
from typing import Any, Mapping, Sequence


# Named camera presets — name -> (description, normalized direction in Blender
# coordinates with Z-up). Each direction is a 3-tuple looking from the camera
# back toward the scene center; the generated script normalizes the vector.
CAMERA_PRESETS: dict[str, dict[str, Any]] = {
    "isometric": {
        "description": "Standard isometric 3/4 view.",
        "direction": (1.25, -1.45, 0.92),
    },
    "top": {
        "description": "Plan view looking straight down on the wafer/table.",
        "direction": (0.0, 0.0, 1.0),
    },
    "front": {
        "description": "Front-elevation view from -Y looking at +Y.",
        "direction": (0.0, -1.0, 0.18),
    },
    "side": {
        "description": "Side-elevation view from +X looking at -X.",
        "direction": (1.0, 0.0, 0.18),
    },
    "cross_section": {
        "description": "Edge-on cross-section view of the layer stack.",
        "direction": (0.0, 1.0, 0.04),
    },
    "free_space_table": {
        "description": "Low oblique view ideal for free-space optical-table scenes.",
        "direction": (0.45, -0.85, 0.32),
    },
}

# Material preset table for common photonics materials. Each entry maps to
# Principled BSDF inputs that the generated Blender script applies after import.
# Colors are expressed as 0..1 RGB tuples; metallic/roughness/ior/transmission
# follow Blender's Principled BSDF semantics.
BLENDER_MATERIAL_PRESETS: dict[str, dict[str, Any]] = {
    "silicon": {
        "description": "Process-grade silicon waveguide / device finish.",
        "base_color": (0.45, 0.48, 0.50),
        "metallic": 0.15,
        "roughness": 0.48,
        "ior": 3.88,
    },
    "silicon_nitride": {
        "description": "Low-loss silicon-nitride waveguide finish.",
        "base_color": (0.62, 0.73, 0.79),
        "metallic": 0.05,
        "roughness": 0.32,
        "ior": 2.0,
    },
    "germanium": {
        "description": "Photodetector germanium absorber finish.",
        "base_color": (0.37, 0.40, 0.44),
        "metallic": 0.18,
        "roughness": 0.42,
        "ior": 4.0,
    },
    "sio2": {
        "description": "Transparent silicon-dioxide / oxide cladding.",
        "base_color": (0.85, 0.93, 0.97),
        "metallic": 0.0,
        "roughness": 0.05,
        "transmission": 0.9,
        "ior": 1.46,
        "alpha": 0.42,
    },
    "gold": {
        "description": "Warm metallic finish for pads and bonding.",
        "base_color": (0.83, 0.69, 0.22),
        "metallic": 1.0,
        "roughness": 0.22,
        "ior": 0.47,
    },
    "aluminum": {
        "description": "Bright neutral metal for routing and pads.",
        "base_color": (0.74, 0.77, 0.80),
        "metallic": 0.88,
        "roughness": 0.28,
        "ior": 1.39,
    },
    "copper": {
        "description": "Warm conductive metal for interconnect and heat-spreaders.",
        "base_color": (0.71, 0.41, 0.26),
        "metallic": 0.95,
        "roughness": 0.30,
        "ior": 0.95,
    },
    "titanium_nitride": {
        "description": "TiN heater / barrier metal finish.",
        "base_color": (0.55, 0.48, 0.34),
        "metallic": 0.72,
        "roughness": 0.34,
        "ior": 2.10,
    },
    "indium_tin_oxide": {
        "description": "Transparent conductive ITO finish.",
        "base_color": (0.72, 0.85, 0.88),
        "metallic": 0.10,
        "roughness": 0.14,
        "transmission": 0.72,
        "ior": 1.9,
        "alpha": 0.6,
    },
    "polymer": {
        "description": "Matte polymer / encapsulant finish.",
        "base_color": (0.62, 0.70, 0.66),
        "metallic": 0.0,
        "roughness": 0.78,
        "ior": 1.49,
    },
    "ceramic": {
        "description": "Neutral ceramic packaging finish.",
        "base_color": (0.87, 0.84, 0.78),
        "metallic": 0.02,
        "roughness": 0.82,
        "ior": 1.55,
    },
}

# Aliases for friendlier preset spelling (e.g. "sin" -> silicon_nitride).
_MATERIAL_PRESET_ALIASES: dict[str, str] = {
    "sin": "silicon_nitride",
    "si": "silicon",
    "ge": "germanium",
    "au": "gold",
    "al": "aluminum",
    "cu": "copper",
    "tin": "titanium_nitride",
    "ito": "indium_tin_oxide",
}

_CAMERA_PRESETS = frozenset(CAMERA_PRESETS)
_RENDER_ENGINES = {"CYCLES", "BLENDER_EEVEE_NEXT", "BLENDER_EEVEE", "BLENDER_WORKBENCH"}
_SCALE_BAR_CORNERS = {"bottom_left", "bottom_right", "top_left", "top_right"}
_CLIP_AXES = {"x", "y", "z"}
_OVERRIDE_MATCHES = {"exact", "contains", "startswith", "endswith", "regex"}


def list_blender_material_presets() -> list[str]:
    """Return preset keys for the Blender Principled BSDF material table."""

    return list(BLENDER_MATERIAL_PRESETS.keys())


def get_blender_material_preset(name: str) -> dict[str, Any]:
    """Return a copy of one Blender Principled BSDF preset by name or alias."""

    resolved = _resolve_material_preset_name(name)
    return dict(BLENDER_MATERIAL_PRESETS[resolved])


def _resolve_material_preset_name(name: str) -> str:
    key = str(name).strip().lower().replace("-", "_")
    if key in BLENDER_MATERIAL_PRESETS:
        return key
    if key in _MATERIAL_PRESET_ALIASES:
        return _MATERIAL_PRESET_ALIASES[key]
    raise KeyError(
        f"Unknown Blender material preset '{name}'. "
        f"Available: {', '.join(list_blender_material_presets())}"
    )


@dataclass(frozen=True)
class BlenderLabel:
    """Text annotation placed in the generated Blender scene."""

    text: str
    location: tuple[float, float, float] | None = None
    size: float = 0.08
    color: str = "#111111"


@dataclass(frozen=True)
class BlenderScaleBar:
    """Scale bar annotation rendered beside the imported geometry."""

    length: float
    unit: str = "um"
    corner: str = "bottom_left"
    label: str | None = None
    color: str = "#111111"


@dataclass(frozen=True)
class BlenderClippingPlane:
    """Half-space clip applied to imported meshes for stack inspection."""

    axis: str = "z"
    offset: float = 0.0
    keep_positive: bool = True


@dataclass(frozen=True)
class BlenderMaterialOverride:
    """Principled BSDF override applied to imported materials by name.

    Either ``preset`` (a key from :data:`BLENDER_MATERIAL_PRESETS`) or one or
    more explicit Principled BSDF inputs must be provided. Explicit inputs
    override the preset values when both are supplied.

    ``match`` controls how ``name`` is matched against imported material names
    in the generated Blender script: ``exact`` (default), ``contains``,
    ``startswith``, ``endswith``, or ``regex``.
    """

    name: str
    preset: str | None = None
    base_color: tuple[float, float, float] | str | None = None
    metallic: float | None = None
    roughness: float | None = None
    ior: float | None = None
    transmission: float | None = None
    alpha: float | None = None
    match: str = "exact"


@dataclass(frozen=True)
class BlenderAddonInvocation:
    """Opt-in Blender add-on operator call emitted in the generated script.

    Optodraw never bundles or links to third-party add-ons. This dataclass
    only records a deterministic ``bpy.ops`` call (and optional
    ``addon_utils.enable``) that will be written into the generated script.
    The user is responsible for installing and enabling the add-on inside
    their own Blender environment, so the resulting script remains
    license-compatible with GPL-only add-ons such as BlenderGDS.
    """

    operator: str
    kwargs: Mapping[str, Any] = field(default_factory=dict)
    module: str | None = None
    enable_first: bool = True


@dataclass(frozen=True)
class BlenderScriptConfig:
    """Normalized settings for a generated headless Blender render script."""

    source_glb: Path
    output_image: Path | None = None
    camera_preset: str = "isometric"
    resolution: tuple[int, int] = (1600, 1200)
    background_color: str = "#ffffff"
    engine: str = "CYCLES"
    samples: int = 64
    lens_mm: float = 55.0
    view_margin: float = 1.35
    camera_from_scene: bool = False
    labels: tuple[BlenderLabel, ...] = ()
    scale_bar: BlenderScaleBar | None = None
    clipping_planes: tuple[BlenderClippingPlane, ...] = ()
    material_overrides: tuple[BlenderMaterialOverride, ...] = ()
    addon_invocation: BlenderAddonInvocation | None = None


def _resolve_output_path(path: str | PathLike[str]) -> Path:
    """Return an expanded absolute path without requiring it to exist."""

    return Path(path).expanduser().resolve(strict=False)


def _hex_to_rgb_fraction(color: str) -> tuple[float, float, float]:
    """Convert a CSS-style hex color to Blender RGB fractions."""

    value = color.strip().lstrip("#")
    if len(value) == 3:
        value = "".join(char * 2 for char in value)
    if len(value) != 6:
        raise ValueError("background_color must be a hex color such as '#ffffff'.")
    return (
        int(value[0:2], 16) / 255.0,
        int(value[2:4], 16) / 255.0,
        int(value[4:6], 16) / 255.0,
    )


def _normalize_label(label: BlenderLabel | dict[str, Any]) -> BlenderLabel:
    """Validate a label annotation specification."""

    if isinstance(label, BlenderLabel):
        spec = label
    else:
        spec = BlenderLabel(
            text=str(label["text"]),
            location=tuple(label["location"]) if label.get("location") is not None else None,
            size=float(label.get("size", 0.08)),
            color=str(label.get("color", "#111111")),
        )
    if not spec.text.strip():
        raise ValueError("label text must be non-empty.")
    if spec.size <= 0.0:
        raise ValueError("label size must be positive.")
    _hex_to_rgb_fraction(spec.color)
    if spec.location is not None and len(spec.location) != 3:
        raise ValueError("label location must be a 3-tuple.")
    return spec


def _normalize_scale_bar(scale_bar: BlenderScaleBar | dict[str, Any]) -> BlenderScaleBar:
    """Validate a scale-bar annotation specification."""

    if isinstance(scale_bar, BlenderScaleBar):
        spec = scale_bar
    else:
        spec = BlenderScaleBar(
            length=float(scale_bar["length"]),
            unit=str(scale_bar.get("unit", "um")),
            corner=str(scale_bar.get("corner", "bottom_left")),
            label=scale_bar.get("label"),
            color=str(scale_bar.get("color", "#111111")),
        )
    if spec.length <= 0.0:
        raise ValueError("scale_bar length must be positive.")
    corner = spec.corner.strip().lower().replace("-", "_")
    if corner not in _SCALE_BAR_CORNERS:
        raise ValueError(f"scale_bar corner must be one of: {', '.join(sorted(_SCALE_BAR_CORNERS))}.")
    _hex_to_rgb_fraction(spec.color)
    return BlenderScaleBar(
        length=float(spec.length),
        unit=spec.unit,
        corner=corner,
        label=spec.label,
        color=spec.color,
    )


def _normalize_clipping_plane(plane: BlenderClippingPlane | dict[str, Any]) -> BlenderClippingPlane:
    """Validate a clipping-plane specification."""

    if isinstance(plane, BlenderClippingPlane):
        spec = plane
    else:
        spec = BlenderClippingPlane(
            axis=str(plane.get("axis", "z")).lower(),
            offset=float(plane.get("offset", 0.0)),
            keep_positive=bool(plane.get("keep_positive", True)),
        )
    if spec.axis not in _CLIP_AXES:
        raise ValueError(f"clipping plane axis must be one of: {', '.join(sorted(_CLIP_AXES))}.")
    return spec


def _coerce_color(color: str | tuple[float, float, float] | list[float]) -> tuple[float, float, float]:
    """Accept either a hex string or an RGB 0..1 tuple and return RGB 0..1."""

    if isinstance(color, str):
        return _hex_to_rgb_fraction(color)
    if isinstance(color, (tuple, list)) and len(color) >= 3:
        r, g, b = (float(color[0]), float(color[1]), float(color[2]))
        for value in (r, g, b):
            if value < 0.0 or value > 1.0:
                raise ValueError("base_color RGB values must lie in [0, 1].")
        return (r, g, b)
    raise ValueError("base_color must be a hex string or RGB 0..1 tuple.")


def _normalize_material_override(
    override: BlenderMaterialOverride | Mapping[str, Any],
) -> BlenderMaterialOverride:
    """Validate a single material override specification."""

    if isinstance(override, BlenderMaterialOverride):
        spec = override
    else:
        spec = BlenderMaterialOverride(
            name=str(override["name"]),
            preset=override.get("preset"),
            base_color=override.get("base_color"),
            metallic=override.get("metallic"),
            roughness=override.get("roughness"),
            ior=override.get("ior"),
            transmission=override.get("transmission"),
            alpha=override.get("alpha"),
            match=str(override.get("match", "exact")).strip().lower(),
        )
    if not spec.name.strip():
        raise ValueError("material override name must be non-empty.")
    if spec.match not in _OVERRIDE_MATCHES:
        raise ValueError(
            f"material override match must be one of: {', '.join(sorted(_OVERRIDE_MATCHES))}."
        )
    if spec.preset is None and all(
        value is None
        for value in (
            spec.base_color,
            spec.metallic,
            spec.roughness,
            spec.ior,
            spec.transmission,
            spec.alpha,
        )
    ):
        raise ValueError(
            "material override must supply a preset or at least one Principled BSDF input."
        )
    if spec.preset is not None:
        _resolve_material_preset_name(spec.preset)
    if spec.base_color is not None:
        _coerce_color(spec.base_color)
    for label, value in (
        ("metallic", spec.metallic),
        ("roughness", spec.roughness),
        ("transmission", spec.transmission),
        ("alpha", spec.alpha),
    ):
        if value is not None and not 0.0 <= float(value) <= 1.0:
            raise ValueError(f"material override '{label}' must lie in [0, 1].")
    if spec.ior is not None and float(spec.ior) <= 0.0:
        raise ValueError("material override 'ior' must be positive.")
    return spec


def _resolve_material_override_payload(override: BlenderMaterialOverride) -> dict[str, Any]:
    """Resolve preset + explicit fields into a flat Principled BSDF param dict."""

    params: dict[str, Any] = {}
    if override.preset is not None:
        params.update(BLENDER_MATERIAL_PRESETS[_resolve_material_preset_name(override.preset)])
        params.pop("description", None)
    if override.base_color is not None:
        params["base_color"] = _coerce_color(override.base_color)
    elif "base_color" in params:
        params["base_color"] = tuple(params["base_color"])
    if override.metallic is not None:
        params["metallic"] = float(override.metallic)
    if override.roughness is not None:
        params["roughness"] = float(override.roughness)
    if override.ior is not None:
        params["ior"] = float(override.ior)
    if override.transmission is not None:
        params["transmission"] = float(override.transmission)
    if override.alpha is not None:
        params["alpha"] = float(override.alpha)
    return {
        "name": override.name,
        "match": override.match,
        "inputs": params,
    }


def _normalize_addon_invocation(
    invocation: BlenderAddonInvocation | Mapping[str, Any],
) -> BlenderAddonInvocation:
    """Validate an opt-in Blender add-on operator invocation."""

    if isinstance(invocation, BlenderAddonInvocation):
        spec = invocation
    else:
        spec = BlenderAddonInvocation(
            operator=str(invocation["operator"]),
            kwargs=dict(invocation.get("kwargs", {})),
            module=invocation.get("module"),
            enable_first=bool(invocation.get("enable_first", True)),
        )
    operator = spec.operator.strip()
    if not operator:
        raise ValueError("addon invocation operator must be a non-empty string.")
    parts = operator.split(".")
    if len(parts) < 2 or not all(part.isidentifier() for part in parts):
        raise ValueError(
            "addon invocation operator must look like 'category.operator' (e.g. 'blendergds.import_gdsii')."
        )
    module = spec.module
    if module is not None:
        module = module.strip()
        if not all(part.isidentifier() for part in module.split(".") if part):
            raise ValueError("addon invocation module must be a valid python module path.")
    return BlenderAddonInvocation(
        operator=operator,
        kwargs=dict(spec.kwargs),
        module=module or None,
        enable_first=bool(spec.enable_first),
    )


def _overrides_from_layer_styles(
    layer_styles: Mapping[Any, Mapping[str, Any]],
) -> list[BlenderMaterialOverride]:
    """Convert a Technology / layer-styles mapping into material overrides.

    The Blender materials produced by GLB exporters typically inherit the
    Optodraw layer ``name`` (e.g. ``"Metal1"``, ``"RIB"``), so the resulting
    overrides match by exact name. Each style's ``material_preset``,
    ``color``/``fill``, ``metalness``/``metallic``, ``roughness``, and
    ``opacity`` keys are forwarded as Principled BSDF inputs.
    """

    overrides: list[BlenderMaterialOverride] = []
    seen: set[str] = set()
    for style in layer_styles.values():
        if not isinstance(style, Mapping):
            continue
        name = style.get("name") or style.get("level_name")
        if not isinstance(name, str) or not name.strip():
            continue
        if name in seen:
            continue
        seen.add(name)
        preset_name = style.get("material_preset") or style.get("preset")
        try:
            preset = _resolve_material_preset_name(preset_name) if preset_name else None
        except KeyError:
            preset = None
        color = style.get("color", style.get("fill"))
        metallic = style.get("metallic", style.get("metalness"))
        roughness = style.get("roughness")
        alpha = style.get("opacity")
        if alpha is None and style.get("transparent"):
            alpha = 0.6
        overrides.append(
            BlenderMaterialOverride(
                name=name,
                preset=preset,
                base_color=color if isinstance(color, (str, tuple, list)) else None,
                metallic=float(metallic) if isinstance(metallic, (int, float)) else None,
                roughness=float(roughness) if isinstance(roughness, (int, float)) else None,
                transmission=(
                    float(style["transmission"])
                    if isinstance(style.get("transmission"), (int, float))
                    else None
                ),
                ior=float(style["ior"]) if isinstance(style.get("ior"), (int, float)) else None,
                alpha=float(alpha) if isinstance(alpha, (int, float)) else None,
            )
        )
    return overrides


def _normalize_config(
    source_glb: str | PathLike[str],
    *,
    output_image: str | PathLike[str] | None = None,
    camera_preset: str = "isometric",
    resolution: tuple[int, int] = (1600, 1200),
    background_color: str = "#ffffff",
    engine: str = "CYCLES",
    samples: int = 64,
    lens_mm: float = 55.0,
    view_margin: float = 1.35,
    camera_from_scene: bool = False,
    labels: Sequence[BlenderLabel | dict[str, Any]] | None = None,
    scale_bar: BlenderScaleBar | dict[str, Any] | None = None,
    clipping_planes: Sequence[BlenderClippingPlane | dict[str, Any]] | None = None,
    material_overrides: Sequence[BlenderMaterialOverride | Mapping[str, Any]] | None = None,
    layer_styles: Mapping[Any, Mapping[str, Any]] | None = None,
    addon_invocation: BlenderAddonInvocation | Mapping[str, Any] | None = None,
) -> BlenderScriptConfig:
    """Validate user options and return a normalized Blender config."""

    preset = camera_preset.strip().lower().replace("-", "_")
    if preset not in _CAMERA_PRESETS:
        raise ValueError(f"camera_preset must be one of: {', '.join(sorted(_CAMERA_PRESETS))}.")

    normalized_engine = engine.strip().upper()
    if normalized_engine not in _RENDER_ENGINES:
        raise ValueError(f"engine must be one of: {', '.join(sorted(_RENDER_ENGINES))}.")

    width, height = resolution
    if int(width) <= 0 or int(height) <= 0:
        raise ValueError("resolution must contain positive width and height values.")

    if int(samples) <= 0:
        raise ValueError("samples must be positive.")

    if float(view_margin) <= 0.0:
        raise ValueError("view_margin must be positive.")

    if str(background_color).lower() != "none":                 # "none": a transparent film
        _hex_to_rgb_fraction(background_color)
    normalized_labels = tuple(_normalize_label(label) for label in (labels or ()))
    normalized_scale_bar = _normalize_scale_bar(scale_bar) if scale_bar is not None else None
    normalized_planes = tuple(_normalize_clipping_plane(plane) for plane in (clipping_planes or ()))
    layer_overrides = _overrides_from_layer_styles(layer_styles) if layer_styles else []
    user_overrides = list(material_overrides or ())
    normalized_overrides = tuple(
        _normalize_material_override(item) for item in (*layer_overrides, *user_overrides)
    )
    normalized_addon = (
        _normalize_addon_invocation(addon_invocation) if addon_invocation is not None else None
    )
    return BlenderScriptConfig(
        source_glb=_resolve_output_path(source_glb),
        output_image=_resolve_output_path(output_image) if output_image is not None else None,
        camera_preset=preset,
        resolution=(int(width), int(height)),
        background_color=background_color,
        engine=normalized_engine,
        samples=int(samples),
        lens_mm=float(lens_mm),
        view_margin=float(view_margin),
        camera_from_scene=bool(camera_from_scene),
        labels=normalized_labels,
        scale_bar=normalized_scale_bar,
        clipping_planes=normalized_planes,
        material_overrides=normalized_overrides,
        addon_invocation=normalized_addon,
    )


def _blender_script(config: BlenderScriptConfig) -> str:
    """Return the Python source for the generated Blender script."""

    transparent = str(config.background_color).lower() == "none"
    bg_rgb = (1.0, 1.0, 1.0) if transparent else _hex_to_rgb_fraction(config.background_color)
    output_image = config.output_image.as_posix() if config.output_image is not None else None
    width, height = config.resolution
    labels_payload = [
        {
            "text": label.text,
            "location": label.location,
            "size": label.size,
            "color": _hex_to_rgb_fraction(label.color),
        }
        for label in config.labels
    ]
    scale_bar_payload = None
    if config.scale_bar is not None:
        scale_bar_payload = {
            "length": config.scale_bar.length,
            "unit": config.scale_bar.unit,
            "corner": config.scale_bar.corner,
            "label": config.scale_bar.label,
            "color": _hex_to_rgb_fraction(config.scale_bar.color),
        }
    clipping_payload = [
        {
            "axis": plane.axis,
            "offset": plane.offset,
            "keep_positive": plane.keep_positive,
        }
        for plane in config.clipping_planes
    ]
    camera_directions = {name: spec["direction"] for name, spec in CAMERA_PRESETS.items()}
    material_payload = [
        _resolve_material_override_payload(override) for override in config.material_overrides
    ]
    addon_payload = None
    if config.addon_invocation is not None:
        addon_payload = {
            "operator": config.addon_invocation.operator,
            "kwargs": dict(config.addon_invocation.kwargs),
            "module": config.addon_invocation.module,
            "enable_first": config.addon_invocation.enable_first,
        }
    return f'''"""Generated by OptoDraw. Run with: blender --background --python this_file.py"""

import math
from pathlib import Path

import bpy
from mathutils import Vector

SOURCE_GLB = {config.source_glb.as_posix()!r}
OUTPUT_IMAGE = {output_image!r}
CAMERA_PRESET = {config.camera_preset!r}
CAMERA_DIRECTIONS = {camera_directions!r}
RESOLUTION = ({width}, {height})
BACKGROUND_RGB = {bg_rgb!r}
TRANSPARENT = {transparent!r}
ENGINE = {config.engine!r}
SAMPLES = {config.samples!r}
LENS_MM = {config.lens_mm!r}
VIEW_MARGIN = {config.view_margin!r}
CAMERA_FROM_SCENE = {config.camera_from_scene!r}
LABELS = {labels_payload!r}
SCALE_BAR = {scale_bar_payload!r}
CLIPPING_PLANES = {clipping_payload!r}
MATERIAL_OVERRIDES = {material_payload!r}
ADDON_INVOCATION = {addon_payload!r}


def clear_scene():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete()


def import_scene():
    bpy.ops.import_scene.gltf(filepath=SOURCE_GLB)
    return [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]


def scene_bounds(objects):
    corners = []
    for obj in objects:
        corners.extend(obj.matrix_world @ Vector(corner) for corner in obj.bound_box)
    if not corners:
        origin = Vector((0, 0, 0))
        return origin, 1.0, origin.copy(), origin.copy()
    min_corner = Vector((min(point.x for point in corners), min(point.y for point in corners), min(point.z for point in corners)))
    max_corner = Vector((max(point.x for point in corners), max(point.y for point in corners), max(point.z for point in corners)))
    center = (min_corner + max_corner) * 0.5
    span = max(max_corner.x - min_corner.x, max_corner.y - min_corner.y, max_corner.z - min_corner.z, 1.0)
    return center, span, min_corner, max_corner


def aim_at(camera, target):
    direction = target - camera.location
    camera.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def camera_direction(preset):
    direction = CAMERA_DIRECTIONS.get(preset)
    if direction is None:
        raise ValueError(
            "Unknown camera preset '%s'. Available: %s" % (preset, sorted(CAMERA_DIRECTIONS))
        )
    return Vector(direction).normalized()


def setup_camera(center, span):
    imported = next((obj for obj in bpy.context.scene.objects if obj.type == "CAMERA"), None)
    if CAMERA_FROM_SCENE and imported is not None:      # the viewer's own camera: the same framing as the viewer
        distance = (imported.matrix_world.translation - center).length
        imported.data.clip_start = max(distance * 1e-4, 1e-4)
        imported.data.clip_end = distance + span * 10.0
        bpy.context.scene.camera = imported
        return imported
    camera_data = bpy.data.cameras.new("OptoDraw Camera")
    camera = bpy.data.objects.new("OptoDraw Camera", camera_data)
    bpy.context.collection.objects.link(camera)
    camera_data.lens = LENS_MM
    # half the span fills half the view (times the margin); the angle is in radians already
    distance = 0.5 * span * VIEW_MARGIN / max(math.tan(camera_data.angle * 0.5), 0.05)
    # scene units import as metres: the clip range must reach a scene of any size (default far clip 100 m)
    camera_data.clip_start = max(distance * 1e-4, 1e-4)
    camera_data.clip_end = distance + span * 10.0
    camera.location = center + camera_direction(CAMERA_PRESET) * distance
    aim_at(camera, center)
    bpy.context.scene.camera = camera
    return camera


def setup_lighting(center, span):
    sun_data = bpy.data.lights.new("OptoDraw Sun", type="SUN")
    sun_data.energy = 2.0
    sun = bpy.data.objects.new("OptoDraw Sun", sun_data)
    bpy.context.collection.objects.link(sun)
    sun.rotation_euler = (math.radians(42), 0.0, math.radians(36))

    area_data = bpy.data.lights.new("OptoDraw Softbox", type="AREA")
    area_data.energy = 10.0 * (span * 1.8) ** 2     # its distance grows with the scene: so must its power
    area_data.size = max(span * 0.8, 1.0)
    area = bpy.data.objects.new("OptoDraw Softbox", area_data)
    bpy.context.collection.objects.link(area)
    area.location = center + Vector((-0.6, -0.8, 1.2)).normalized() * span * 1.8
    return sun, area


def _annotation_material(name, rgb):
    material = bpy.data.materials.new(name=name)
    material.use_nodes = True
    bsdf = material.node_tree.nodes.get("Principled BSDF")
    if bsdf is not None:
        bsdf.inputs["Base Color"].default_value = (*rgb, 1.0)
        bsdf.inputs["Roughness"].default_value = 0.9
    return material


def _add_text_object(text, location, size, rgb):
    bpy.ops.object.text_add(location=location)
    text_obj = bpy.context.active_object
    text_obj.data.body = text
    text_obj.data.size = size
    text_obj.data.extrude = size * 0.05
    text_obj.data.align_x = "LEFT"
    text_obj.data.align_y = "BOTTOM"
    text_obj.data.materials.append(_annotation_material("OptoDraw Label", rgb))
    return text_obj


def add_labels(center, span, min_corner, max_corner):
    if not LABELS:
        return []
    created = []
    for index, label in enumerate(LABELS):
        location = label.get("location")
        if location is None:
            location = (max_corner.x - span * 0.05, max_corner.y - span * 0.05, max_corner.z + span * 0.02)
        else:
            location = tuple(location)
        text_obj = _add_text_object(label["text"], location, label["size"], label["color"])
        text_obj.name = f"OptoDraw Label {{index + 1}}"
        created.append(text_obj)
    return created


def _scale_bar_anchor(corner, min_corner, max_corner, span):
    margin = span * 0.08
    anchors = {{
        "bottom_left": Vector((min_corner.x + margin, min_corner.y + margin, min_corner.z)),
        "bottom_right": Vector((max_corner.x - margin, min_corner.y + margin, min_corner.z)),
        "top_left": Vector((min_corner.x + margin, max_corner.y - margin, min_corner.z)),
        "top_right": Vector((max_corner.x - margin, max_corner.y - margin, min_corner.z)),
    }}
    return anchors[corner]


def add_scale_bar(span, min_corner, max_corner):
    if SCALE_BAR is None:
        return None
    anchor = _scale_bar_anchor(SCALE_BAR["corner"], min_corner, max_corner, span)
    bar_length = SCALE_BAR["length"]
    thickness = max(span * 0.01, bar_length * 0.05)
    tick = max(thickness * 1.5, bar_length * 0.08)
    material = _annotation_material("OptoDraw Scale Bar", SCALE_BAR["color"])

    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(anchor.x + bar_length * 0.5, anchor.y, anchor.z))
    bar = bpy.context.active_object
    bar.name = "OptoDraw Scale Bar"
    bar.scale = (bar_length, thickness, thickness)
    bar.data.materials.append(material)

    for sign in (-1.0, 1.0):
        bpy.ops.mesh.primitive_cube_add(
            size=1.0,
            location=(anchor.x, anchor.y, anchor.z + sign * tick * 0.5),
        )
        end_cap = bpy.context.active_object
        end_cap.name = "OptoDraw Scale Bar Tick"
        end_cap.scale = (thickness, thickness, tick)
        end_cap.data.materials.append(material)

    label_text = SCALE_BAR["label"]
    if label_text is None:
        label_text = f"{{SCALE_BAR['length']:g}} {{SCALE_BAR['unit']}}"
    text_obj = _add_text_object(
        label_text,
        (anchor.x, anchor.y + thickness * 3.0, anchor.z + tick * 1.5),
        max(span * 0.04, thickness * 4.0),
        SCALE_BAR["color"],
    )
    text_obj.name = "OptoDraw Scale Bar Label"
    return bar


def apply_clipping_planes(objects, center, span):
    if not CLIPPING_PLANES or not objects:
        return []
    cutters = []
    for index, plane in enumerate(CLIPPING_PLANES):
        axis = plane["axis"]
        offset = plane["offset"]
        keep_positive = plane["keep_positive"]
        location = Vector(center)
        half_extent = span * 2.0
        direction = 1.0 if keep_positive else -1.0
        if axis == "x":
            location.x = center.x + offset + direction * half_extent
        elif axis == "y":
            location.y = center.y + offset + direction * half_extent
        else:
            location.z = center.z + offset + direction * half_extent
        bpy.ops.mesh.primitive_cube_add(size=span * 4.0, location=location)
        cutter = bpy.context.active_object
        cutter.name = f"OptoDraw Clip {{index + 1}}"
        cutters.append(cutter)
        for obj in objects:
            modifier = obj.modifiers.new(name=f"OptoDraw Clip {{index + 1}}", type="BOOLEAN")
            modifier.object = cutter
            modifier.operation = "INTERSECT"
            modifier.solver = "EXACT"
            bpy.context.view_layer.objects.active = obj
            bpy.ops.object.modifier_apply(modifier=modifier.name)
    for cutter in cutters:
        bpy.data.objects.remove(cutter, do_unlink=True)
    return objects


def _principled_input_aliases():
    return {{
        "base_color": ("Base Color",),
        "metallic": ("Metallic",),
        "roughness": ("Roughness",),
        "ior": ("IOR",),
        "transmission": ("Transmission Weight", "Transmission"),
        "alpha": ("Alpha",),
    }}


def _apply_principled_inputs(material, inputs):
    if not material or not material.use_nodes:
        if material is not None:
            material.use_nodes = True
    nodes = material.node_tree.nodes if material and material.node_tree else None
    bsdf = nodes.get("Principled BSDF") if nodes else None
    if bsdf is None:
        return
    aliases = _principled_input_aliases()
    for key, value in inputs.items():
        socket = None
        for socket_name in aliases.get(key, ()):
            socket = bsdf.inputs.get(socket_name)
            if socket is not None:
                break
        if socket is None:
            continue
        if key == "base_color":
            socket.default_value = (float(value[0]), float(value[1]), float(value[2]), 1.0)
        else:
            socket.default_value = float(value)
    alpha = inputs.get("alpha")
    transmission = inputs.get("transmission")
    if alpha is not None and float(alpha) < 1.0:
        material.blend_method = "BLEND"
    elif transmission is not None and float(transmission) > 0.0:
        material.blend_method = "BLEND"


def _name_matches(name, pattern, match):
    if match == "exact":
        return name == pattern
    if match == "contains":
        return pattern in name
    if match == "startswith":
        return name.startswith(pattern)
    if match == "endswith":
        return name.endswith(pattern)
    if match == "regex":
        import re
        return re.search(pattern, name) is not None
    return False


def apply_material_overrides(objects):
    if not MATERIAL_OVERRIDES:
        return
    for obj in objects:
        if getattr(obj, "type", None) != "MESH":
            continue
        for slot in obj.material_slots:
            material = slot.material
            if material is None:
                continue
            for override in MATERIAL_OVERRIDES:
                if _name_matches(material.name, override["name"], override["match"]):
                    _apply_principled_inputs(material, override["inputs"])
                    break


def invoke_optional_addon():
    if not ADDON_INVOCATION:
        return
    operator_path = ADDON_INVOCATION["operator"]
    kwargs = dict(ADDON_INVOCATION.get("kwargs", {{}}))
    module = ADDON_INVOCATION.get("module")
    if ADDON_INVOCATION.get("enable_first") and module:
        try:
            import addon_utils
            addon_utils.enable(module, default_set=True, persistent=True, handle_error=None)
        except Exception as error:
            print("OptoDraw: failed to enable add-on '%s': %s" % (module, error))
            return
    category, _, op = operator_path.partition(".")
    try:
        target = getattr(getattr(bpy.ops, category), op)
    except AttributeError as error:
        print("OptoDraw: add-on operator '%s' not available (%s)" % (operator_path, error))
        return
    try:
        target(**kwargs)
    except Exception as error:
        print("OptoDraw: add-on operator '%s' raised: %s" % (operator_path, error))


def setup_render():
    scene = bpy.context.scene
    scene.render.engine = ENGINE
    if ENGINE == "CYCLES":
        scene.cycles.samples = SAMPLES
        scene.cycles.use_denoising = True
    scene.render.resolution_x = RESOLUTION[0]
    scene.render.resolution_y = RESOLUTION[1]
    # a view transform that keeps white white and colours true (Filmic turned a white background grey)
    for transform in ("Khronos PBR Neutral", "AgX", "Standard"):
        try:
            scene.view_settings.view_transform = transform
            break
        except TypeError:
            continue
    try:
        scene.view_settings.look = "None"
    except TypeError:
        pass
    scene.view_settings.exposure = 0.0
    scene.view_settings.gamma = 1.0
    world = scene.world or bpy.data.worlds.new("OptoDraw World")
    scene.world = world
    world.color = BACKGROUND_RGB
    # a world with nodes ignores world.color: set its Background node (found by type, not by name)
    world.use_nodes = True
    nodes = world.node_tree.nodes
    background = next((node for node in nodes if node.type == 'BACKGROUND'), None)
    if background is None:
        background = nodes.new("ShaderNodeBackground")
        output = next((node for node in nodes if node.type == 'OUTPUT_WORLD'), None) or nodes.new("ShaderNodeOutputWorld")
        world.node_tree.links.new(background.outputs[0], output.inputs[0])
    background.inputs[0].default_value = (*BACKGROUND_RGB, 1.0)
    background.inputs[1].default_value = 0.6 if TRANSPARENT else 1.0
    scene.render.film_transparent = TRANSPARENT
    if OUTPUT_IMAGE:
        scene.render.filepath = OUTPUT_IMAGE
        scene.render.image_settings.file_format = Path(OUTPUT_IMAGE).suffix.lstrip(".").upper() or "PNG"
        if scene.render.image_settings.file_format == "JPG":
            scene.render.image_settings.file_format = "JPEG"
        if TRANSPARENT and scene.render.image_settings.file_format == "PNG":
            scene.render.image_settings.color_mode = 'RGBA'


def main():
    clear_scene()
    objects = import_scene()
    invoke_optional_addon()
    apply_material_overrides(objects)
    center, span, min_corner, max_corner = scene_bounds(objects)
    objects = apply_clipping_planes(objects, center, span)
    setup_camera(center, span)
    setup_lighting(center, span)
    add_scale_bar(span, min_corner, max_corner)
    add_labels(center, span, min_corner, max_corner)
    setup_render()
    if OUTPUT_IMAGE:
        bpy.ops.render.render(write_still=True)


if __name__ == "__main__":
    main()
'''


def export_blender_script(
    output_path: str | PathLike[str],
    *,
    source_glb: str | PathLike[str],
    output_image: str | PathLike[str] | None = None,
    camera_preset: str = "isometric",
    resolution: tuple[int, int] = (1600, 1200),
    background_color: str = "#ffffff",
    engine: str = "CYCLES",
    samples: int = 64,
    lens_mm: float = 55.0,
    view_margin: float = 1.35,
    camera_from_scene: bool = False,
    labels: Sequence[BlenderLabel | dict[str, Any]] | None = None,
    scale_bar: BlenderScaleBar | dict[str, Any] | None = None,
    clipping_planes: Sequence[BlenderClippingPlane | dict[str, Any]] | None = None,
    material_overrides: Sequence[BlenderMaterialOverride | Mapping[str, Any]] | None = None,
    layer_styles: Mapping[Any, Mapping[str, Any]] | None = None,
    addon_invocation: BlenderAddonInvocation | Mapping[str, Any] | None = None,
) -> Path:
    """Write a deterministic Blender Python script that imports a GLB and renders it.

    Optional knobs beyond the basics:

    - ``camera_from_scene``: render through the camera stored in the GLB (the
      viewer's framing) instead of a ``camera_preset`` fitted to every mesh.
    - ``material_overrides``: explicit Principled BSDF overrides applied by
      imported material name. Each entry may reference :data:`BLENDER_MATERIAL_PRESETS`
      via ``preset`` and/or specify individual BSDF inputs.
    - ``layer_styles``: mapping of layer-spec -> style dict (typically from
      :class:`optodraw.Technology` or :func:`parse_blendergds_layer_config`).
      Each style is converted into a material override keyed on its ``name``,
      letting GDS layer materials follow process/foundry appearance metadata.
    - ``addon_invocation``: opt-in :class:`BlenderAddonInvocation` describing a
      third-party Blender add-on operator (such as BlenderGDS) to enable and
      call after the GLB import. Optodraw only emits the deterministic call;
      the user must install/enable the add-on in their Blender environment.
    """
    config = _normalize_config(
        source_glb,
        output_image=output_image,
        camera_preset=camera_preset,
        resolution=resolution,
        background_color=background_color,
        engine=engine,
        samples=samples,
        lens_mm=lens_mm,
        view_margin=view_margin,
        camera_from_scene=camera_from_scene,
        labels=labels,
        scale_bar=scale_bar,
        clipping_planes=clipping_planes,
        material_overrides=material_overrides,
        layer_styles=layer_styles,
        addon_invocation=addon_invocation,
    )
    path = Path(output_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_blender_script(config), encoding="utf-8")
    return path


def render_blender_script(
    script_path: str | PathLike[str],
    *,
    blender_executable: str = "blender",
    background: bool = True,
    timeout: float | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a generated Blender script with the Blender command-line executable."""
    command = [blender_executable]
    if background:
        command.append("--background")
    command.extend(["--python", Path(script_path).expanduser().as_posix()])
    return subprocess.run(command, check=True, text=True, capture_output=True, timeout=timeout)


def _default_script_path(source_glb: Path, output_image: Path | None) -> Path:
    """Choose a default script path beside the render output or GLB."""

    if output_image is not None:
        return output_image.with_suffix(".blender.py")
    return source_glb.with_suffix(".blender.py")


def main(argv: Sequence[str] | None = None) -> int:
    """Command-line entry point for generating and optionally running scripts."""

    parser = argparse.ArgumentParser(description="Generate or run a headless Blender render script for an OptoDraw GLB.")
    parser.add_argument("--input", required=True, help="Input GLB file to import in Blender.")
    parser.add_argument("--script", help="Output Blender Python script path. Defaults beside the input or output image.")
    parser.add_argument("--output", help="Optional rendered image path written by the generated script.")
    parser.add_argument(
        "--camera",
        default="isometric",
        choices=sorted(_CAMERA_PRESETS),
        help="Camera preset (one of: %s)." % ", ".join(sorted(_CAMERA_PRESETS)),
    )
    parser.add_argument("--width", type=int, default=1600, help="Render width in pixels.")
    parser.add_argument("--height", type=int, default=1200, help="Render height in pixels.")
    parser.add_argument("--engine", default="CYCLES", choices=sorted(_RENDER_ENGINES), help="Blender render engine.")
    parser.add_argument("--samples", type=int, default=64, help="Cycles sample count.")
    parser.add_argument("--background-color", default="#ffffff", help="World background color as hex.")
    parser.add_argument("--run", action="store_true", help="Run Blender after writing the script.")
    parser.add_argument("--blender", default="blender", help="Blender executable path or command name.")
    args = parser.parse_args(argv)

    source_glb = _resolve_output_path(args.input)
    output_image = _resolve_output_path(args.output) if args.output else None
    script_path = Path(args.script).expanduser() if args.script else _default_script_path(source_glb, output_image)
    written_script = export_blender_script(
        script_path,
        source_glb=source_glb,
        output_image=output_image,
        camera_preset=args.camera,
        resolution=(args.width, args.height),
        background_color=args.background_color,
        engine=args.engine,
        samples=args.samples,
    )
    print(written_script)
    if args.run:
        render_blender_script(written_script, blender_executable=args.blender)
    return 0


__all__ = [
    "BLENDER_MATERIAL_PRESETS",
    "BlenderAddonInvocation",
    "BlenderClippingPlane",
    "BlenderLabel",
    "BlenderMaterialOverride",
    "BlenderScaleBar",
    "BlenderScriptConfig",
    "CAMERA_PRESETS",
    "export_blender_script",
    "get_blender_material_preset",
    "list_blender_material_presets",
    "list_camera_presets",
    "render_blender_script",
    "main",
]


def list_camera_presets() -> list[str]:
    """Return the canonical Blender/Three.js camera preset names."""

    return list(CAMERA_PRESETS.keys())
