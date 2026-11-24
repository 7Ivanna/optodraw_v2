"""Versioned scene schema for save/load round-trip."""

from __future__ import annotations

import json
from dataclasses import asdict
from functools import lru_cache
from pathlib import Path
from typing import Any

from optodraw.core.beam import DEFAULT_BEAM_STYLE, Beam, BeamStyle, FocusingBeam
from optodraw.core.component import Component, Group
from optodraw.core.routing import FiberRoute, Route, WaveguideRoute, WireBond
from optodraw.core.scene import Scene
from optodraw.core.transform import Transform, Vec3
from optodraw.provenance import Source, Sourced
from optodraw.registry import build_component, component_registry

_MISSING = object()  # "the constructor names no default for this parameter"

SCHEMA_VERSION = 3
SUPPORTED_SCHEMA_VERSIONS: tuple[int, ...] = (1, 2, 3)
AUTHORING_PATCH_SCHEMA_VERSION = "optodraw.interactive_authoring_patch.v1"

UNITS = {"length": "um", "angle": "deg", "wavelength": "nm"}

#: ChipComponent attributes that should round-trip even when the registry
#: parameter list for a given component does not enumerate them. These match
#: the schematic-first metadata model (see ``schematic_geometry.py``).
_CHIP_EXTRA_FIELDS: tuple[str, ...] = (
    "render_physical",
    "visual_style",
    "visual_scale",
    "flip_horizontal",
    "flip_vertical",
)

_CHIP_EXTRA_DEFAULTS: dict[str, Any] = {
    "render_physical": False,
    "visual_style": "publication",
    "visual_scale": 1.0,
    "flip_horizontal": False,
    "flip_vertical": False,
}


def validate_units(units: Any) -> dict[str, str]:
    """Validate scene unit metadata against the schema contract."""

    if not isinstance(units, dict):
        raise ValueError("units must be a dict")
    normalized = dict(units)
    for key, expected in UNITS.items():
        actual = normalized.get(key)
        if actual != expected:
            raise ValueError(f"Invalid units[{key!r}]: expected {expected!r}, got {actual!r}")
    return normalized


_ROUTE_TYPES = {"Route", "WaveguideRoute", "FiberRoute"}
_BEAM_TYPES = {"Beam", "FocusingBeam"}
_SKIP_COMPONENT_TYPES = _ROUTE_TYPES | _BEAM_TYPES


def _ref_id(component: Component, refs: dict[int, str] | None) -> str:
    """The id a spec gives ``component``: from ``refs`` (``id(node) -> id``), else its own id or label."""

    return (refs or {}).get(id(component)) or component._id or component.label


def _is_anchor(value: Any) -> bool:
    return hasattr(value, "xy") and hasattr(value, "inset")


def _orphan(value: Any, refs: dict[int, str] | None) -> bool:
    """True when ``value`` holds an anchor whose inset is not in the scene being saved (it left the page)."""

    if _is_anchor(value):
        return refs is not None and id(value.inset) not in refs
    return isinstance(value, (list, tuple)) and any(_orphan(item, refs) for item in value)


def _json_value(value: Any, refs: dict[int, str] | None = None) -> Any:
    if _is_anchor(value) and _orphan(value, refs):              # its inset left the page: the place it has now
        return _json_value(tuple(value.xy()))
    if _is_anchor(value):                                       # an Anchor: its inset by id, and the source point
        return {"anchor": _ref_id(value.inset, refs), "point": [float(v) for v in value.point],
                "options": _json_value(dict(value.options), refs)}
    if isinstance(value, Component):                            # a part another part names: a zoom's insets
        return _ref_id(value, refs)
    if isinstance(value, Vec3):
        return _json_value(value.as_tuple())
    if isinstance(value, tuple):
        return [_json_value(item, refs) for item in value]
    if isinstance(value, list):
        return [_json_value(item, refs) for item in value]
    if isinstance(value, dict):
        return {key: _json_value(item, refs) for key, item in value.items()}
    return value


def _anchor_from_spec(value: Any, refs: dict[str, Component]) -> Any:
    """An anchor that ``_json_value`` wrote, as the live place in its inset again, also inside a list (the ends of a
    span); any other value as it is. The inset comes first in the spec, as ``page.add`` order gives."""

    if isinstance(value, list):
        return [_anchor_from_spec(item, refs) for item in value]
    if not (isinstance(value, dict) and "anchor" in value and set(value) <= {"anchor", "point", "options"}):
        return value
    inset = _resolve_ref(value["anchor"], refs)
    if not callable(getattr(inset, "at", None)):
        raise ValueError(f"an anchor names {value['anchor']!r}, which is not an inset")
    point, options = value.get("point"), value.get("options") or {}
    if not isinstance(point, list) or not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in point):
        raise ValueError(f"an anchor's point is a list of numbers, got {point!r}")
    if not isinstance(options, dict):
        raise ValueError(f"an anchor's options are a mapping, got {options!r}")
    return inset.at(*point, **options)


def _center_from_component(component: Component) -> list[float]:
    position = component.transform.position
    if abs(position.z) < 1e-9:
        return [position.x, position.y]
    return [position.x, position.y, position.z]


def _resolve_component_id(component: Component, assigned: dict[int, str]) -> str:
    if component._id:
        return component._id
    key = id(component)
    if key in assigned:
        return assigned[key]
    base = component.label or component.component_type.lower()
    assigned[key] = base
    return base


def _assign_component_ids(scene: Scene) -> dict[int, str]:
    refs: dict[int, str] = {}
    seen: dict[str, int] = {}
    assigned: dict[int, str] = {}

    for node in scene.walk():
        if node.component_type == "Group":
            continue
        if node.component_type in _SKIP_COMPONENT_TYPES:
            continue

        component_id = _resolve_component_id(node, assigned)
        if component_id in seen:
            seen[component_id] += 1
            component_id = f"{component_id}_{seen[component_id]}"
        else:
            seen[component_id] = 0
        refs[id(node)] = component_id

    return refs


def _parameter_value(component: Component, name: str) -> Any:
    if name == "center":
        return _center_from_component(component)
    if name == "angle":
        return component.transform.angle
    if name == "points" and hasattr(component, "points"):
        return [_json_value(point.as_tuple() if isinstance(point, Vec3) else point) for point in component.points]
    if not hasattr(component, name):
        return None
    return getattr(component, name)


@lru_cache(maxsize=None)
def _default_instance(cls: type) -> Any:
    """One default-constructed component per class, or None if it needs arguments."""

    try:
        return cls()
    except Exception:  # requires a source file, a name, points...
        return None


def _constructor_default(cls: type, name: str) -> Any:
    """What a component ends up with when a parameter is not given.

    Read off a default-constructed instance rather than the signature, because
    plenty of options arrive through ``**kwargs`` and never appear as named
    parameters. ``_MISSING`` when the class cannot be built without arguments."""

    instance = _default_instance(cls)
    if instance is None:
        return _MISSING
    return getattr(instance, name, _MISSING)


def _should_include_param(name: str, value: Any, component: Component | None = None) -> bool:
    if value is None:
        return False
    if name in {"center", "angle", "label"}:
        return True
    if isinstance(value, bool):
        # A toggle is written whenever it differs from the constructor default.
        # Writing only the True state kept specs lean and lost every option that
        # defaults to ON the moment somebody turned it off: the spec said
        # nothing, so the default switched it straight back on reload.
        default = _constructor_default(type(component), name) if component is not None else _MISSING
        return value is not default
    if isinstance(value, (int, float, str)):
        return True
    if isinstance(value, (list, tuple, dict)):
        return bool(value)
    return True


def _is_chip_component(component: Component) -> bool:
    """Return True for on-chip components that carry schematic-first metadata."""

    return (
        hasattr(component, "schematic_family")
        and hasattr(component, "render_physical")
        and hasattr(component, "physical_spec")
    )


def _physical_spec_payload(component: Component) -> dict[str, Any] | None:
    """Read ``component.physical_spec()`` into a JSON-friendly dict (or None)."""

    if not hasattr(component, "physical_spec"):
        return None
    try:
        spec = component.physical_spec()
    except Exception:
        return None
    values = getattr(spec, "values", None)
    if not values:
        return None
    return {
        "device_family": getattr(spec, "device_family", ""),
        "values": {key: _json_value(value) for key, value in values.items()},
    }


def _emit_chip_extras(component: Component, spec: dict[str, Any]) -> None:
    """Attach schematic-first metadata to a chip component's spec dict."""

    if not _is_chip_component(component):
        return

    for field_name in _CHIP_EXTRA_FIELDS:
        value = getattr(component, field_name, None)
        if value is None:
            continue
        default = _CHIP_EXTRA_DEFAULTS.get(field_name)
        if value == default:
            continue
        spec[field_name] = _json_value(value)

    physical_payload = _physical_spec_payload(component)
    if physical_payload is not None:
        spec["physical_spec"] = physical_payload


def component_to_spec(
    component: Component,
    *,
    component_id: str | None = None,
    assigned_ids: dict[int, str] | None = None,
    _part_tables: tuple[dict, dict] | None = None,
    base: str | Path | None = None,
) -> dict[str, Any]:
    """Serialize a component to the current schema dict form. ``base`` is the folder of the page file: an inset's
    source paths are written relative to it, or absolute with none."""

    if isinstance(component, Group):
        spec: dict[str, Any] = {
            "type": "Group",
            "label": component.label,
            "center": _center_from_component(component),
            "angle": component.transform.angle,
            "children": [
                component_to_spec(
                    child,
                    component_id=assigned_ids.get(id(child)) if assigned_ids is not None else None,
                    assigned_ids=assigned_ids,
                    _part_tables=_part_tables,
                    base=base,
                )
                for child in component.children
            ],
        }
        if component_id:
            spec["id"] = component_id
        return spec

    from optodraw.parts import UserPart
    from optodraw.parts.serialization import add_definition

    definition = component.definition if isinstance(component, UserPart) else getattr(component, "_part_definition", None)
    if definition is not None:
        manifests, assets = _part_tables if _part_tables is not None else ({}, {})
        spec = {"type": definition.name,
                "part_definition": add_definition(definition, manifests, assets),
                "center": _center_from_component(component), "angle": component.transform.angle,
                "scale": component.scale if isinstance(component, UserPart) else 1.0,
                "variant": component.variant if isinstance(component, UserPart) else definition.default_variant,
                "parameters": dict(component.parameters if isinstance(component, UserPart)
                                   else component._part_parameters)}
        if component_id:
            spec["id"] = component_id
        if component.label:
            spec["label"] = component.label
        if _part_tables is None:
            spec.update(part_definitions=manifests, assets=assets)
        return spec

    component_type = component.component_type
    spec = {"type": component_type}
    if component_id:
        spec["id"] = component_id

    registry_spec = component_registry().get(component_type)
    if registry_spec is not None:
        for param in registry_spec.parameters:
            value = _parameter_value(component, param)
            if _should_include_param(param, value, component):
                spec[param] = _json_value(value, assigned_ids)
        if component.label and "label" not in spec and spec.get("text") != component.label:
            # label reaches many parts through **kwargs, not the signature; a note's label is its text, saved once
            spec["label"] = component.label
    else:
        spec["center"] = _center_from_component(component)
        spec["angle"] = component.transform.angle
        if component.label:
            spec["label"] = component.label
    if component_type == "Inset":
        _emit_inset(component, spec, assigned_ids, base)
    saved = component._saved_params() if callable(getattr(component, "_saved_params", None)) else {}
    if not any(_orphan(value, assigned_ids) for value in saved.values()):   # a mark's anchors, live after a load
        spec.update({key: _json_value(value, assigned_ids) for key, value in saved.items()})

    for flag in ("flip_horizontal", "flip_vertical"):
        if getattr(component, flag, False):
            spec[flag] = True
    if isinstance(spec.get("center"), list) and len(spec["center"]) == 3:
        spec["center"] = spec["center"][:2]                       # the height is its own key, kept by a 2D move
    height = float(component.transform.position.z)
    if abs(height) > 1e-9 and component_type != "Group":
        spec["z"] = height
    for axis in ("x", "y"):                                       # a turn out of the table plane (3D)
        turn = float(getattr(component.transform.rotation_deg, axis))
        if abs(turn) > 1e-9:
            spec[f"rotation_{axis}"] = turn
    beam_height = getattr(component, "beam_height", None)
    if beam_height is not None and not getattr(component, "_scene_beam", False):
        spec["beam_height"] = float(beam_height)
    mount, default = getattr(component, "base_mount", "post"), _constructor_default(type(component), "base_mount")
    if mount != ("post" if default is _MISSING else default):            # a stage: its motion mark and its 3D stage
        spec["base_mount"] = str(mount)
    if getattr(component, "label_side", "top") not in (None, "", "top"):
        spec["label_side"] = str(component.label_side)
    if getattr(component, "left_open", ()):                          # ports the figure leaves open on purpose
        spec["left_open"] = list(component.left_open)

    _emit_chip_extras(component, spec)
    _emit_gds_layer_stack(component, spec)
    sources = {name: {"value": float(value), **asdict(value.source)}       # a physics number and where it comes from
               for name, value in getattr(component, "__dict__", {}).items() if isinstance(value, Sourced)}
    if sources:
        spec["sources"] = sources

    return spec


def _emit_inset(inset: Any, spec: dict[str, Any], refs: dict[int, str] | None, base: str | Path | None) -> None:
    """An inset's name, scale bar and backing, its source record and its last fragment, inline: the page needs no
    source file to open."""

    if inset.label:
        spec["label"] = inset.label
    if inset.bar is not None:
        spec["bar"] = _json_value(inset.bar)
    if inset.opacity != 1.0:
        spec["opacity"] = inset.opacity
    if inset.over is not None:                       # the inset it stands over, by id; over the page itself, true
        spec["over"] = _ref_id(inset.over, refs) if isinstance(inset.over, Component) else True
    spec["source"], fragment = inset._saved(base)
    if fragment is not None:                         # a record never built keeps none
        spec["fragment"] = fragment


def _emit_gds_layer_stack(component: Component, spec: dict[str, Any]) -> None:
    """Serialize a GDSModel's per-layer overrides with JSON-safe string keys.

    ``layer_stack`` is keyed by ``LayerSpec`` tuples in memory; persist them as
    ``"layer/datatype"`` so PDK / techfile edits survive save + reload."""

    stack = getattr(component, "layer_stack", None)
    if not stack:
        return
    out: dict[str, Any] = {}
    for key, style in stack.items():
        skey = f"{key[0]}/{key[1]}" if isinstance(key, (tuple, list)) else str(key)
        out[skey] = _json_value(style)
    if out:
        spec["layer_stack"] = out


def _beam_to_spec(beam: Beam | FocusingBeam, refs: dict[int, str]) -> dict[str, Any]:
    if isinstance(beam, FocusingBeam):
        path: list[Any] = []
        for anchor in (beam.anchor1, beam.anchor2):
            if isinstance(anchor, Component):
                path.append(refs.get(id(anchor), anchor._id or anchor.label))
            elif anchor is not None:
                path.append(_json_value(anchor))
        spec: dict[str, Any] = {
            "type": "FocusingBeam",
            "path": path,
            "wavelength": beam.wavelength,
            "width1": beam.width1,
            "width2": beam.width2,
        }
        if beam.label:
            spec["label"] = beam.label
        if getattr(beam, "_id", ""):
            spec["id"] = beam._id
        if beam._opacity is not None:
            spec["opacity"] = beam._opacity
        if beam.offset:
            spec["offset"] = beam.offset
        return spec

    path = []
    for anchor in beam.anchors:
        if isinstance(anchor, Component):
            path.append(refs.get(id(anchor), anchor._id or anchor.label))
        elif isinstance(anchor, (tuple, list)) and len(anchor) == 2 and isinstance(anchor[0], Component):
            comp, port = anchor
            path.append([refs.get(id(comp), comp._id or comp.label), port])
        else:
            path.append(_json_value(anchor))
    spec = {
        "path": path,
        "wavelength": beam.wavelength,
        "width": beam.width,
    }
    if beam.label:
        spec["label"] = beam.label
    if getattr(beam, "_id", ""):
        spec["id"] = beam._id
    # Preserve traced beam metadata so notebook round-trip does not lose source link
    for _k in ("traced_from", "trace_mode", "power", "ray"):
        _v = getattr(beam, _k, None)
        if _v is not None:
            spec[_k] = _json_value(_v)
    from optodraw.core.beam import wavelength_to_hex

    if beam.color and beam.color != wavelength_to_hex(beam.wavelength):
        spec["color"] = beam.color  # explicit override survives the round-trip
    if getattr(beam, "envelope", False):
        spec["envelope"] = True
    if beam._opacity is not None:
        spec["opacity"] = beam._opacity
    if beam.offset:
        spec["offset"] = beam.offset
    return spec


def _spec_kind(route: Route) -> str:
    """The kind a spec records: a wire bond is an electrical link, made again by the kind "wirebond"."""

    return "wirebond" if isinstance(route, WireBond) else route.kind


def _route_to_spec(route: Route, refs: dict[int, str]) -> dict[str, Any]:
    physical_length_um = float(getattr(route, "physical_length_um", 0.0))

    # A port-routed link is stored as the two PORTS it joins, exactly like one
    # drawn in the editor, so it re-resolves (and follows its parts) on load.
    # This used to read _endpoint_from/_endpoint_to, which nothing ever set, so
    # every Python-built route was flattened into a dead polyline.
    from_comp, from_port = route.start_component, route.start_port
    to_comp, to_port = route.end_component, route.end_port
    if from_comp is not None and from_port and to_comp is not None and to_port:
        spec: dict[str, Any] = {
            "from": [refs.get(id(from_comp), from_comp._id or from_comp.label), from_port],
            "to": [refs.get(id(to_comp), to_comp._id or to_comp.label), to_port],
            "kind": _spec_kind(route),
            "width": route.width,
            "path_type": route.path_type,
            "smooth": route.smooth,
            "bend_radius": route.bend_radius,
            "backend": route.backend,
            "physical_length_um": physical_length_um,
        }
        spec.update(_json_value(getattr(route, "_routing_options", {})))
        if route.width2 is not None:
            spec["width2"] = route.width2
        if route.label:
            spec["label"] = route.label
        if getattr(route, "_id", ""):
            spec["id"] = route._id
        return spec

    spec = {
        "type": route.component_type,
        "points": [_json_value(point.as_tuple()) for point in route.points],
        "width": route.width,
        "kind": _spec_kind(route),
        "path_type": route.path_type,
        "smooth": route.smooth,
        "bend_radius": route.bend_radius,
        "backend": route.backend,
        "label": route.label,
        "physical_length_um": physical_length_um,
    }
    if getattr(route, "_id", ""):
        spec["id"] = route._id
    return spec


def scene_to_spec(scene: Scene, *, base: str | Path | None = None) -> dict[str, Any]:
    """Serialize a scene to the current schema version. ``base`` is the folder of the page file: the source paths of
    insets are written relative to it, or absolute with none. A :class:`~optodraw.figure.page.Page` also writes its
    ``page`` block."""

    from optodraw import __version__
    from optodraw.figure.page import Page

    if isinstance(scene, Page):
        scene._insets()                      # each inset at the page's print scale: the fragment the page draws
    refs = _assign_component_ids(scene)
    components: list[dict[str, Any]] = []
    routes: list[dict[str, Any]] = []
    beams: list[dict[str, Any]] = []
    part_tables: tuple[dict, dict] = ({}, {})

    for child in scene.root.children:
        if isinstance(child, Group):
            components.append(component_to_spec(child, component_id=refs.get(id(child)), assigned_ids=refs,
                                                _part_tables=part_tables, base=base))
            continue
        if child.component_type in _BEAM_TYPES:
            beams.append(_beam_to_spec(child, refs))
            continue
        if child.component_type in _ROUTE_TYPES:
            routes.append(_route_to_spec(child, refs))
            continue
        components.append(component_to_spec(child, component_id=refs.get(id(child)), assigned_ids=refs,
                                            _part_tables=part_tables, base=base))

    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "optodraw_version": __version__,
        "units": dict(UNITS),
        "title": scene.title,
        "width": scene.width,
        "height": scene.height,
        "platform": scene.platform,
        **({"frame_center": [float(v) for v in scene.frame_center]}
           if tuple(getattr(scene, "frame_center", (0.0, 0.0))) != (0.0, 0.0) else {}),
        "components": components,
        "routes": routes,
        "beams": beams,
    }

    if part_tables[0]:
        payload["part_definitions"], payload["assets"] = part_tables

    scene_metadata = getattr(scene, "metadata", None)
    if isinstance(scene_metadata, dict) and scene_metadata:
        payload["metadata"] = _json_value(scene_metadata)

    if getattr(scene, "foundry_stack", None):
        payload["foundry_stack"] = str(scene.foundry_stack)

    if scene.beam_style != DEFAULT_BEAM_STYLE:
        payload["beam_style"] = asdict(scene.beam_style)

    if isinstance(scene, Page):
        payload["page"] = {"width_mm": scene.width_mm, "height_mm": scene.height_mm, "font_pt": scene.font_pt,
                           "letters": scene.letters, "letter_pt": scene.letter_pt}

    return payload


def _resolve_ref(ref: Any, refs: dict[str, Component]) -> Any:
    if isinstance(ref, str):
        if ref not in refs:
            raise KeyError(f"Unknown component reference '{ref}'")
        return refs[ref]
    if isinstance(ref, (list, tuple)) and len(ref) == 2 and isinstance(ref[0], str):
        component = _resolve_ref(ref[0], refs)
        return (component, ref[1])
    if isinstance(ref, (list, tuple)):
        return tuple(ref)
    return ref


def component_from_spec(spec: dict[str, Any], *, refs: dict[str, Component] | None = None,
                        _definitions: dict | None = None, base: str | Path | None = None) -> Component:
    """Deserialize a component spec dict. ``base`` is the folder of the page file, where an inset's relative source
    paths start (the working folder with none). An anchor or a zoom names an inset that comes before it."""

    refs = refs if refs is not None else {}
    component_type = spec.get("type", "")
    if not component_type:
        raise ValueError("Component spec is missing 'type'")

    if "part_definition" in spec or component_type.startswith("user:"):
        from optodraw.parts import UserPart
        from optodraw.parts.serialization import read_definitions

        definitions = read_definitions(spec) if _definitions is None else _definitions
        digest = spec.get("part_definition")
        if not isinstance(digest, str) or digest not in definitions:
            raise ValueError(f"Missing part definition for {component_type}: {digest}")
        definition = definitions[digest]
        if component_type != definition.name:
            raise ValueError(f"Component type {component_type} does not match definition {definition.name}")
        allowed = {"type", "id", "part_definition", "part_definitions", "assets", "center", "angle", "label",
                   "scale", "variant", "parameters"}
        if spec.keys() - allowed:
            raise ValueError(f"Unknown user definition instance fields: {sorted(spec.keys() - allowed)}")
        component = UserPart(definition, **{key: value for key, value in spec.items()
                                           if key in {"center", "angle", "label", "scale", "variant", "parameters"}})
        if "id" in spec:
            component._id = spec["id"]
            refs[spec["id"]] = component
        elif component.label:
            refs[component.label] = component
        return component

    if component_type == "Group":
        center = spec.get("center", (0, 0))
        if isinstance(center, list):
            center = tuple(center)
        group = Group(
            label=spec.get("label", ""),
            transform=Transform.from_2d(center[0], center[1], spec.get("angle", 0)),
        )
        if len(center) > 2:
            group.transform.position.z = float(center[2])
        if "id" in spec:
            group._id = spec["id"]
            refs[spec["id"]] = group
        for child_spec in spec.get("children", []):
            group.add(component_from_spec(child_spec, refs=refs, _definitions=_definitions, base=base))
        return group

    if component_type in _ROUTE_TYPES:
        route = _build_route_component(spec)
        if "id" in spec:
            route._id = spec["id"]
            refs[spec["id"]] = route
        return route

    constructor_kwargs = {
        key: _anchor_from_spec(value, refs)
        for key, value in spec.items()
        if key not in {"type", "id", "physical_spec", "base_mount", "anim_params", "beam_height", "label_side", "rotation_x", "rotation_y", "z",
                       "center_offset", "sources", "left_open"}
    }
    stored = None
    if component_type == "Inset" and "source" in spec:          # the record and the last fragment: no file read
        from optodraw.figure.sources import stored_source

        stored = stored_source(spec["source"], constructor_kwargs.pop("fragment", None), Path(base or "."))
        constructor_kwargs["source"] = stored
        if isinstance(constructor_kwargs.get("bar"), list):
            constructor_kwargs["bar"] = tuple(constructor_kwargs["bar"])
    from optodraw.figure.inset import LINK_ENDS

    for key in LINK_ENDS.get(component_type, ()):              # a zoom's or a cut's two insets, by id
        if isinstance(constructor_kwargs.get(key), str):
            constructor_kwargs[key] = _resolve_ref(constructor_kwargs[key], refs)
    component = build_component(component_type, **constructor_kwargs)
    if stored is not None and stored.at is not None and component.width:
        component.set_print(stored.at[0] / component.width, stored.at[2])   # the print scale it was saved at
    offset = spec.get("center_offset")
    if offset is not None and _is_anchor(constructor_kwargs.get("center")):  # a note moved off its place by hand
        if not (isinstance(offset, list) and len(offset) == 2 and all(
                isinstance(v, (int, float)) and not isinstance(v, bool) for v in offset)):
            raise ValueError(f"center_offset is two numbers, got {offset!r}")
        at = component.transform.position
        component.transform.position = Vec3(float(at.x) + offset[0], float(at.y) + offset[1], at.z)
    # base_mount / anim_params / beam_height are post-construction attributes (work for every type,
    # incl. devices whose constructors don't take them): 3D mount + animation choices.
    if "base_mount" in spec:
        component.base_mount = str(spec["base_mount"])
    if spec.get("z") is not None:
        height = spec["z"]
        if isinstance(height, bool) or not isinstance(height, (int, float)):
            raise ValueError(f"z is a height in scene units, got {height!r}")
        component.z = float(height)
    for key in ("rotation_x", "rotation_y"):
        turn = spec.get(key)
        if turn is None:
            continue
        if isinstance(turn, bool) or not isinstance(turn, (int, float)):
            raise ValueError(f"{key} is a number of degrees, got {turn!r}")
        setattr(component, key, float(turn))
    if isinstance(spec.get("anim_params"), dict):
        component.anim_params = dict(spec["anim_params"])
    if spec.get("label_side"):
        component.label_side = str(spec["label_side"])
    if spec.get("left_open"):
        if not (isinstance(spec["left_open"], list) and all(isinstance(p, str) for p in spec["left_open"])):
            raise ValueError(f"left_open is a list of port names, got {spec['left_open']!r}")
        component.left_open = tuple(spec["left_open"])
    if spec.get("beam_height") is not None:
        component.beam_height = float(spec["beam_height"])
        if hasattr(component, "_scene_beam"):
            component._scene_beam = False                   # a periscope or cryostat given its own height
    for name, entry in (spec.get("sources") or {}).items():      # set after the constructor, which may float() them
        source = Source(entry["kind"], entry.get("ref", ""), entry.get("note", ""))
        setattr(component, name, Sourced(entry["value"], source))
    if "id" in spec:
        component._id = spec["id"]
        refs[spec["id"]] = component
    elif component.label:
        refs[component.label] = component
    return component


def _build_route_component(route_spec: dict[str, Any]) -> Route:
    route_type = route_spec.get("type", "Route")
    kwargs = {
        key: value
        for key, value in route_spec.items()
        if key not in {"type", "from", "to", "id", "physical_length_um"}
    }
    points = kwargs.pop("points", ())

    if kwargs.get("kind") == "wirebond":
        return WireBond(points, **kwargs)
    if route_type == "WaveguideRoute":
        return WaveguideRoute(points, **kwargs)
    if route_type == "FiberRoute":
        return FiberRoute(points, **kwargs)
    if route_type == "Route":
        return Route(points, **kwargs)
    raise ValueError(f"Unknown route type '{route_type}'")


def _add_route_from_spec(scene: Scene, route_spec: dict[str, Any], refs: dict[str, Component]) -> Route:
    if "from" in route_spec and "to" in route_spec:
        port1 = _resolve_ref(route_spec["from"], refs)
        port2 = _resolve_ref(route_spec["to"], refs)
        route_kwargs = {
            key: route_spec[key]
            for key in (
                "kind", "width", "width2", "path_type", "bend_radius", "smooth", "backend", "label", "steps",
                "start_straight_length", "end_straight_length", "snap_tolerance",
            )
            if key in route_spec
        }
        route = scene.route(port1, port2, **route_kwargs)
        if route_spec.get("id"):
            route._id = str(route_spec["id"])
            refs[route._id] = route
        return route

    route = _build_route_component(route_spec)
    added = scene.add(route)
    if route_spec.get("id"):
        added._id = str(route_spec["id"])
        refs[added._id] = added
    return added


def _add_beam_from_spec(scene: Scene, beam_spec: dict[str, Any], refs: dict[str, Component]) -> Beam | FocusingBeam:
    beam_type = beam_spec.get("type", "Beam")
    path = [_resolve_ref(ref, refs) for ref in beam_spec.get("path", [])]

    if beam_type == "FocusingBeam":
        if len(path) < 2:
            raise ValueError("FocusingBeam requires at least two path anchors")
        beam = FocusingBeam(
            path[0],
            path[1],
            width1=beam_spec.get("width1", 5.0),
            width2=beam_spec.get("width2", 0.0),
            wavelength=beam_spec.get("wavelength", 633.0),
            opacity=beam_spec.get("opacity"),
            offset=beam_spec.get("offset", 0.0),
            label=beam_spec.get("label", ""),
        )
        added = scene.add(beam)
        if "id" in beam_spec and beam_spec["id"]:
            added._id = str(beam_spec["id"])
            refs[str(beam_spec["id"])] = added
        return added

    if len(path) < 2:
        raise ValueError("Beam requires at least two path anchors")
    beam = Beam(
        *path,
        wavelength=beam_spec.get("wavelength", 633.0),
        width=beam_spec.get("width", 0.8),
        opacity=beam_spec.get("opacity"),
        offset=beam_spec.get("offset", 0.0),
        label=beam_spec.get("label", ""),
        color=beam_spec.get("color"),
        envelope=beam_spec.get("envelope", False),
    )
    added = scene.add(beam)
    if "id" in beam_spec and beam_spec["id"]:
        added._id = str(beam_spec["id"])
        refs[str(beam_spec["id"])] = added
    for _k in ("traced_from", "trace_mode", "power", "ray"):
        if _k in beam_spec:
            setattr(added, _k, beam_spec[_k])
    return added


def scene_from_spec(spec: dict[str, Any], *, base: str | Path | None = None) -> Scene:
    """Deserialize a scene spec.

    Supports legacy schemas 1 and 2. Schema 3 embeds immutable user definitions
    and hashed artwork. Schema 2 fields include ``render_physical``, ``visual_style``,
    ``visual_scale``, route ``physical_length_um``, scene ``metadata`` such as
    dimension markers, and a read-only ``physical_spec`` payload on chip
    components.

    A spec with a ``page`` block gives a :class:`~optodraw.figure.page.Page`. ``base`` is the folder of the page file,
    where the relative source paths of insets start.
    """

    version = spec.get("schema_version")
    if version is not None and version not in SUPPORTED_SCHEMA_VERSIONS:
        supported = ", ".join(str(value) for value in SUPPORTED_SCHEMA_VERSIONS)
        raise ValueError(
            f"Unsupported schema version {version}; supported versions: {supported}"
        )

    page = spec.get("page")
    if page is not None:
        from optodraw.figure.page import Page

        scene = Page(width_mm=page["width_mm"], height_mm=page.get("height_mm"), font_pt=page.get("font_pt", 7.0),
                     title=spec.get("title", "Figure"), letters=page.get("letters", True),
                     letter_pt=page.get("letter_pt", 8.0))
        scene._units = validate_units(spec.get("units", UNITS))
        scene.metadata = dict(spec.get("metadata") or {})
    else:
        scene = Scene(
            title=spec.get("title", "Optical Setup"),
            width=spec.get("width", 200),
            height=spec.get("height", 100),
            platform=spec.get("platform", "free_space"),
            units=validate_units(spec.get("units", UNITS)),
            metadata=spec.get("metadata"),
        )
    if spec.get("frame_center"):
        scene.frame_center = tuple(float(v) for v in spec["frame_center"])[:2]
    if spec.get("beam_style"):
        scene.beam_style = BeamStyle(**spec["beam_style"])

    if spec.get("foundry_stack"):
        try:
            scene.set_foundry_stack(str(spec["foundry_stack"]))
        except Exception:
            pass  # missing stack file: components fall back to heuristic heights

    refs: dict[str, Component] = {}
    from optodraw.parts.serialization import read_definitions

    definitions = read_definitions(spec)
    built: list[Any] = []
    later: list[tuple[int, dict[str, Any]]] = []
    for component_spec in spec.get("components", []):
        if component_spec.get("type") in _ROUTE_TYPES:
            continue
        try:
            built.append(component_from_spec(component_spec, refs=refs, _definitions=definitions, base=base))
        except KeyError as error:                    # it names a part that comes later, such as a mark before its
            if "Unknown component reference" not in str(error):           # inset: it is built in a second pass
                raise
            later.append((len(built), component_spec))
            built.append(None)
    for index, component_spec in later:
        built[index] = component_from_spec(component_spec, refs=refs, _definitions=definitions, base=base)
    for component in built:                          # in the spec's order
        scene.add(component)
    for node in scene.walk():                        # an inset over another one: by id, in any order
        if node.component_type == "Inset" and isinstance(getattr(node, "over", None), str):
            node.over = _resolve_ref(node.over, refs)

    for route_spec in spec.get("routes", []):
        if route_spec.get("type") in _ROUTE_TYPES or "points" in route_spec:
            route = _build_route_component(route_spec)
            scene.add(route)
            if "id" in route_spec:
                route._id = route_spec["id"]
                refs[route_spec["id"]] = route
        else:
            _add_route_from_spec(scene, route_spec, refs)

    for beam_spec in spec.get("beams", []):
        _add_beam_from_spec(scene, beam_spec, refs)

    return scene


def save_scene(scene: Scene, path: str | Path) -> None:
    """Write a scene spec to JSON."""

    import warnings

    from optodraw.figure import sources

    output = Path(path)
    spec = scene_to_spec(scene, base=output.parent)
    text = json.dumps(spec, indent=2) + "\n"
    size = len(text.encode("utf-8"))
    if size > sources.PICTURE_LIMIT:                    # a pixel inset makes a large file: warn above 16 MB
        def insets(entries: list[Any]) -> list[dict[str, Any]]:      # in groups too
            found = []
            for entry in entries:
                found += ([entry] if entry.get("type") == "Inset" else []) + insets(entry.get("children") or [])
            return found

        sizes = sorted(((len(json.dumps(c)), c.get("id") or c.get("label") or c["type"])
                        for c in insets(spec["components"])), reverse=True)
        top = ", ".join(f"{name} ({n / 2 ** 20:.1f} MB)" for n, name in sizes[:3])
        warnings.warn(f"{output.name} holds {size / 2 ** 20:.1f} MB (limit {sources.PICTURE_LIMIT / 2 ** 20:.0f} MB)"
                      + (f"; the insets with the most data: {top}" if top else "")
                      + ". Shrink the pictures first for a smaller file", UserWarning, stacklevel=3)
    output.write_text(text, encoding="utf-8")


def load_scene(path: str | Path) -> Scene:
    """Load a scene from a JSON spec file. Inset source paths start at the file's folder."""

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return scene_from_spec(payload, base=Path(path).parent)


def load_authoring_patch(path: str | Path) -> dict[str, Any]:
    """Load an interactive authoring patch JSON file."""

    return json.loads(Path(path).read_text(encoding="utf-8"))


def _component_refs(scene: Scene) -> dict[str, Component]:
    refs: dict[str, Component] = {}
    assigned = _assign_component_ids(scene)
    for node in scene.walk():
        if node.component_type == "Group":
            continue
        component_id = assigned.get(id(node))
        if component_id:
            refs[component_id] = node
    return refs


def apply_authoring_patch(scene: Scene, patch: dict[str, Any]) -> Scene:
    """Apply an interactive authoring patch to a scene in place."""

    if not isinstance(patch, dict):
        raise ValueError("authoring patch must be a dict")

    schema_version = patch.get("schema_version")
    if schema_version != AUTHORING_PATCH_SCHEMA_VERSION:
        raise ValueError(
            f"Unsupported authoring patch schema version {schema_version!r}; expected {AUTHORING_PATCH_SCHEMA_VERSION!r}"
        )

    patches = patch.get("patches", [])
    if not isinstance(patches, list):
        raise ValueError("authoring patch 'patches' must be a list")

    refs = _component_refs(scene)
    for entry in patches:
        if not isinstance(entry, dict):
            raise ValueError("each authoring patch entry must be a dict")
        component_id = entry.get("component_id")
        if not isinstance(component_id, str) or not component_id:
            raise ValueError("authoring patch entries require a non-empty component_id")
        component = refs.get(component_id)
        if component is None:
            raise KeyError(f"Unknown component reference '{component_id}' in authoring patch")

        component_type = entry.get("component_type")
        if component_type and component_type != component.component_type:
            raise ValueError(
                f"Authoring patch component type mismatch for '{component_id}': "
                f"expected {component.component_type!r}, got {component_type!r}"
            )

        if "label" in entry:
            component.label = str(entry["label"])
        if "color" in entry:
            component.color = str(entry["color"])
        if "opacity" in entry:
            component.opacity = float(entry["opacity"])
        if "visible" in entry:
            setattr(component, "visible", bool(entry["visible"]))

    return scene
