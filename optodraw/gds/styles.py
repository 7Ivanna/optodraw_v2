"""GDS layer style constants and helpers."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Literal

from optodraw.gds.palette import ALIASES as GDS_MATERIAL_ALIASES, normal_name

LayerSpec = tuple[int, int]
MeshBackend = Literal["auto", "gdsfactory", "trimesh"]


@dataclass(frozen=True)
class _ResolvedGdsfactoryContext:
    pdk: Any | None
    layer_stack: Any | None
    layer_views: Any | None


def _load_generic_gdsfactory_pdk() -> Any | None:
    """Return the generic PDK on gdsfactory 9 (gpdk) or 8 (generic_tech)."""

    try:
        from gdsfactory.gpdk import get_generic_pdk

        return get_generic_pdk()
    except Exception:
        pass
    try:
        from gdsfactory.gpdk import PDK

        return PDK
    except Exception:
        pass
    try:
        from gdsfactory.generic_tech import get_generic_pdk

        return get_generic_pdk()
    except Exception:
        return None

GDS_LAYER_PALETTE = (
    "#0b7285",
    "#f08c6d",
    "#d4af37",
    "#5c7cfa",
    "#2b8a3e",
    "#e8590c",
    "#c2255c",
    "#495057",
)

GENERIC_AUX_LAYER_DEPTHS = {
    (20, 0): {"zmin": 0.16, "thickness": 0.03, "material_preset": "silicon"},
    (21, 0): {"zmin": 0.16, "thickness": 0.03, "material_preset": "silicon"},
    (22, 0): {"zmin": 0.155, "thickness": 0.04, "material_preset": "silicon"},
    (23, 0): {"zmin": 0.155, "thickness": 0.04, "material_preset": "silicon"},
    (24, 0): {"zmin": 0.15, "thickness": 0.05, "material_preset": "silicon"},
    (25, 0): {"zmin": 0.15, "thickness": 0.05, "material_preset": "silicon"},
    (26, 0): {"zmin": 0.22, "thickness": 0.08, "material_preset": "silicon"},
}


def coerce_scalar(value: Any) -> float | None:
    if callable(value):
        try:
            value = value()
        except TypeError:
            return None
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _layer_number(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    number = coerce_scalar(value)
    if number is None or not math.isfinite(number) or number < 0 or not number.is_integer():
        return None
    return int(number)


def _normalize_layer_key(key: Any) -> LayerSpec | None:
    if isinstance(key, int):
        layer = _layer_number(key)
        return (layer, 0) if layer is not None else None

    if isinstance(key, str):
        text = key.strip()
        for separator in ("/", ":", ","):
            if separator not in text:
                continue
            left, right = text.split(separator, 1)
            layer = _layer_number(left.strip())
            datatype = _layer_number(right.strip())
            if layer is None or datatype is None:
                return None
            return (layer, datatype)

        layer = _layer_number(text)
        if layer is None:
            return None
        return (layer, 0)

    if isinstance(key, (tuple, list)) and len(key) >= 2:
        layer = _layer_number(key[0])
        datatype = _layer_number(key[1])
        if layer is None or datatype is None:
            return None
        return (layer, datatype)

    return None


def normalize_layer_stack(layer_stack: Any) -> dict[LayerSpec, dict[str, Any]]:
    if not isinstance(layer_stack, dict):
        return {}

    normalized: dict[LayerSpec, dict[str, Any]] = {}
    for key, value in layer_stack.items():
        spec = _normalize_layer_key(key)
        if spec is None:
            continue
        if value is None:
            normalized[spec] = {"visible": False}
            continue
        if isinstance(value, dict):
            normalized[spec] = dict(value)
    return normalized


def layer_tuple_from_value(value: Any) -> LayerSpec | None:
    if value is None:
        return None

    if isinstance(value, (tuple, list)) and len(value) >= 2:
        layer = _layer_number(value[0])
        datatype = _layer_number(value[1])
        if layer is not None and datatype is not None:
            return (layer, datatype)

    if hasattr(value, "layer") and hasattr(value, "datatype"):
        layer = _layer_number(getattr(value, "layer"))
        datatype = _layer_number(getattr(value, "datatype"))
        if layer is not None and datatype is not None:
            return (layer, datatype)

    nested_layer = getattr(value, "layer", None)
    if nested_layer is not None and nested_layer is not value:
        spec = layer_tuple_from_value(nested_layer)
        if spec is not None:
            return spec

    derived_layer = getattr(value, "derived_layer", None)
    if derived_layer is not None and derived_layer is not value:
        spec = layer_tuple_from_value(derived_layer)
        if spec is not None:
            return spec

    if not isinstance(value, (str, bytes)):
        try:
            items = list(value)
        except TypeError:
            items = []
        if len(items) >= 2:
            spec = _normalize_layer_key((items[0], items[1]))
            if spec is not None:
                return spec
        if items:
            spec = layer_tuple_from_value(items[0])
            if spec is not None:
                return spec

    return None


def _rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    return f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"


def _rgb_fraction_to_hex(red: float, green: float, blue: float) -> str:
    return _rgb_to_hex(
        (
            int(round(max(0.0, min(1.0, red)) * 255)),
            int(round(max(0.0, min(1.0, green)) * 255)),
            int(round(max(0.0, min(1.0, blue)) * 255)),
        )
    )


def material_preset_from_name(
    material: Any,
    material_aliases: dict[str, str] | None = None,
) -> str | None:
    if not isinstance(material, str):
        return None
    aliases = dict(GDS_MATERIAL_ALIASES)
    if material_aliases:
        aliases.update({normal_name(key): value for key, value in material_aliases.items()})
    return aliases.get(normal_name(material))


def material_preset_from_layer_name(layer_name: str | None) -> str | None:
    if not layer_name:
        return None

    normalized = layer_name.strip().lower()
    if normalized.startswith(("via", "mt", "metal", "topmetal", "cont")) or normalized in {"m1", "m2", "m3", "pad", "viac"}:
        return "aluminum"
    if normalized in {"htr", "heater"} or "heater" in normalized:
        return "titanium_nitride"
    if normalized.startswith("ge") or normalized.endswith("ge") or "geep" in normalized or "nppge" in normalized:
        return "germanium"
    if normalized.startswith("inp") or "indium_phosphide" in normalized:
        return "indium_phosphide"
    if normalized.startswith("gaas") or "gallium_arsenide" in normalized:
        return "gallium_arsenide"
    if normalized == "ito" or "indium_tin_oxide" in normalized:
        return "indium_tin_oxide"
    if normalized.startswith("wgn") or "nitride" in normalized:
        return "silicon_nitride"
    if normalized.startswith(("ox", "box", "clad")) or "oxide" in normalized:
        return "sio2"
    if normalized in {"text", "label", "lbl", "devrec", "bbox", "marker", "bound"}:
        return None
    if normalized.startswith(("rib", "wg", "slab", "pp", "np", "pim", "nim", "ipd", "ind")):
        return "silicon"
    return None


def _iter_layer_source_items(layer_source: Any) -> list[tuple[Any, Any]]:
    if layer_source is None:
        return []

    nested_layers = getattr(layer_source, "layers", None)
    if nested_layers is not None and nested_layers is not layer_source:
        nested_items = _iter_layer_source_items(nested_layers)
        if nested_items:
            return nested_items

    if isinstance(layer_source, dict):
        return list(layer_source.items())

    namespaces: list[dict[str, Any]] = []
    if isinstance(layer_source, type):
        namespaces.append(dict(vars(layer_source)))
    else:
        try:
            instance_namespace = dict(vars(layer_source))
        except TypeError:
            instance_namespace = {}
        if instance_namespace:
            namespaces.append(instance_namespace)
        try:
            type_namespace = dict(vars(type(layer_source)))
        except TypeError:
            type_namespace = {}
        if type_namespace and type(layer_source) is not object:
            namespaces.append(type_namespace)

    items: list[tuple[Any, Any]] = []
    seen_names: set[str] = set()
    for namespace in namespaces:
        for name, value in namespace.items():
            if not isinstance(name, str) or name.startswith("_") or name in seen_names:
                continue
            seen_names.add(name)
            items.append((name, value))
    if items:
        return items

    return [
        (name, getattr(layer_source, name))
        for name in dir(layer_source)
        if not name.startswith("_")
    ]


def get_layer_name_map(layer_source: Any) -> dict[LayerSpec, str]:
    mapping: dict[LayerSpec, str] = {}
    for key, value in _iter_layer_source_items(layer_source):
        if isinstance(layer_source, dict):
            spec_from_key = _normalize_layer_key(key)
            spec_from_value = layer_tuple_from_value(value)

            if spec_from_key is not None:
                if isinstance(value, str) and value:
                    mapping.setdefault(spec_from_key, value)
                    continue
                if isinstance(value, dict) and isinstance(value.get("name"), str):
                    mapping.setdefault(spec_from_key, value["name"])
                    continue
            if spec_from_value is not None:
                mapping.setdefault(spec_from_value, str(key))
            continue

        spec = layer_tuple_from_value(value)
        if spec is not None:
            mapping.setdefault(spec, str(key))

    return mapping


def _format_layer_description(
    spec: LayerSpec,
    *,
    name: str,
    material_name: str | None,
    material_preset: str | None,
    thickness: float | None,
    zmin: float | None,
    source_label: str,
) -> str:
    material_label = material_name or material_preset or "unspecified material"
    thickness_label = f"{thickness:.3f} um" if thickness is not None else "unknown thickness"
    zmin_label = f"{zmin:.3f} um" if zmin is not None else "unknown z"
    return f"{name} ({spec[0]}/{spec[1]}): {material_label}, z={zmin_label}, t={thickness_label}, {source_label}"


def _resolve_gdsfactory_context(
    *,
    pdk: Any | None = None,
    layer_stack: Any | None = None,
    layer_views: Any | None = None,
) -> _ResolvedGdsfactoryContext:
    resolved_pdk = pdk
    resolved_layer_stack = layer_stack
    resolved_layer_views = layer_views

    if resolved_layer_stack is None or resolved_layer_views is None:
        if resolved_pdk is None:
            resolved_pdk = _load_generic_gdsfactory_pdk()
            if resolved_pdk is None:
                return _ResolvedGdsfactoryContext(None, resolved_layer_stack, resolved_layer_views)

        try:
            activate = getattr(resolved_pdk, "activate", None)
            if callable(activate):
                activate()
        except Exception:
            pass

        if resolved_layer_stack is None:
            getter = getattr(resolved_pdk, "get_layer_stack", None)
            if callable(getter):
                try:
                    resolved_layer_stack = getter()
                except Exception:
                    resolved_layer_stack = None
        if resolved_layer_views is None:
            getter = getattr(resolved_pdk, "get_layer_views", None)
            if callable(getter):
                try:
                    resolved_layer_views = getter()
                except Exception:
                    resolved_layer_views = None

    return _ResolvedGdsfactoryContext(resolved_pdk, resolved_layer_stack, resolved_layer_views)


def get_gdsfactory_layer_styles(
    *,
    pdk: Any | None = None,
    layers: Any | None = None,
    layer_stack: Any | None = None,
    layer_views: Any | None = None,
    aux_layer_depths: dict[Any, dict[str, Any]] | None = None,
    material_aliases: dict[str, str] | None = None,
) -> dict[LayerSpec, dict[str, Any]]:
    resolved_context = _resolve_gdsfactory_context(
        pdk=pdk,
        layer_stack=layer_stack,
        layer_views=layer_views,
    )
    resolved_pdk = resolved_context.pdk
    resolved_layer_stack = resolved_context.layer_stack
    resolved_layer_views = resolved_context.layer_views

    if resolved_layer_stack is None:
        return {}

    stack_layers = getattr(resolved_layer_stack, "layers", None)
    if not isinstance(stack_layers, dict):
        return {}

    name_map = get_layer_name_map(layers if layers is not None else resolved_pdk)
    styles: dict[LayerSpec, dict[str, Any]] = {}
    layer_views_obj: Any = resolved_layer_views
    for level_name, level in stack_layers.items():
        spec = layer_tuple_from_value(getattr(level, "layer", None))
        if spec is None:
            spec = layer_tuple_from_value(getattr(level, "derived_layer", None))
        if spec is None:
            continue

        style: dict[str, Any] = {
            "name": name_map.get(spec, level_name),
            "level_name": level_name,
            "style_source": "pdk",
        }
        material_name = getattr(level, "material", None)
        if isinstance(material_name, str) and material_name:
            style["material"] = material_name

        layer_view = None
        if layer_views_obj is not None:
            try:
                layer_view = layer_views_obj.get_from_tuple(spec)
            except Exception:
                layer_view = None

        fill_color = getattr(layer_view, "fill_color", None)
        if fill_color is not None and hasattr(fill_color, "as_rgb_tuple"):
            style["color"] = _rgb_to_hex(fill_color.as_rgb_tuple(alpha=False))

        visible = getattr(layer_view, "visible", True)
        style["visible"] = visible is not False

        thickness = coerce_scalar(getattr(level, "thickness", None))
        if thickness is not None:
            style["thickness"] = float(thickness)

        zmin = coerce_scalar(getattr(level, "zmin", None))
        if zmin is not None:
            style["zmin"] = float(zmin)

        preset = material_preset_from_name(material_name, material_aliases)
        if preset is not None:
            style["material_preset"] = preset

        styles[spec] = style

    resolved_aux_layer_depths = GENERIC_AUX_LAYER_DEPTHS if aux_layer_depths is None else aux_layer_depths
    for spec, extra in normalize_layer_stack(resolved_aux_layer_depths).items():
        style = styles.setdefault(spec, {"name": name_map.get(spec, f"L{spec[0]}/{spec[1]}")})
        for key, value in extra.items():
            normalized_key = "zmin" if key == "z_offset" else key
            if normalized_key not in style:
                style[normalized_key] = value

        if layer_views_obj is not None:
            try:
                layer_view = layer_views_obj.get_from_tuple(spec)
            except Exception:
                layer_view = None
            fill_color = getattr(layer_view, "fill_color", None)
            if fill_color is not None and hasattr(fill_color, "as_rgb_tuple") and "color" not in style:
                style["color"] = _rgb_to_hex(fill_color.as_rgb_tuple(alpha=False))
            style.setdefault("visible", getattr(layer_view, "visible", True) is not False)
        else:
            style.setdefault("visible", True)

    for spec, style in styles.items():
        zmin = coerce_scalar(style.get("zmin", style.get("z_offset")))
        if zmin is not None:
            style["zmin"] = float(zmin)
        thickness = coerce_scalar(style.get("thickness"))
        if thickness is not None:
            style["thickness"] = float(thickness)
        style.setdefault("name", name_map.get(spec, f"L{spec[0]}/{spec[1]}"))
        style.setdefault(
            "description",
            _format_layer_description(
                spec,
                name=style["name"],
                material_name=style.get("material"),
                material_preset=style.get("material_preset"),
                thickness=coerce_scalar(style.get("thickness")),
                zmin=coerce_scalar(style.get("zmin")),
                source_label="PDK",
            ),
        )

    return styles


def get_generic_pdk_layer_styles() -> dict[LayerSpec, dict[str, Any]]:
    return get_gdsfactory_layer_styles()

def color_to_rgba(color: str, opacity: float) -> tuple[int, int, int, int]:
    value = color.lstrip("#")
    if len(value) == 3:
        value = "".join(char * 2 for char in value)
    r = int(value[0:2], 16)
    g = int(value[2:4], 16)
    b = int(value[4:6], 16)
    a = max(0, min(int(opacity * 255), 255))
    return (r, g, b, a)
