"""Callable component catalogs.

These helpers make it easy to discover components without opening source files.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from optodraw.registry import SOURCE_COMPONENT_TYPES, component_registry, describe_physics_support
from optodraw.schema import UNITS


def _spec_to_catalog_entry(spec) -> dict[str, Any]:
    return {
        "category": spec.category,
        "platform": spec.platform,
        "description": spec.description,
        "parameters": list(spec.parameters),
        "physics_modes": list(spec.physics_modes),
        "visual_only": spec.visual_only,
        "schematic_default": spec.schematic_default,
        "supports_render_physical": spec.supports_render_physical,
        "supports_physical_spec": spec.supports_physical_spec,
        "units": dict(UNITS),
    }


# Clean, consistent palette labels. Registry keys stay unique (some collide across
# the on-chip vs electronics families), but the palette shows these friendly names.
_DISPLAY_NAMES: dict[str, str] = {
    "ADCBlock": "ADC",
    "CatalogTableClamp": "Table Clamp",
    "CatalogHardware": "Brackets & Platforms",
    "TIABlock": "TIA",
    "MetalRoute": "Metal route",
    "ElectricalPad": "Electrical pad",
    "ElectricalIOBank": "Electrical I/O bank",
    "GSGProbePad": "GSG probe pad",
    "RFDriver": "RF driver",
    "HeaterPad": "Heater pad",
    "MEMSActuator": "MEMS actuator",
    "SignalArrow": "Signal arrow",
    "BalancedPhotodetector": "Balanced photodetector",
    "CoherentReceiver": "Coherent receiver",
    "TransmitterMacro": "Transmitter (macro)",
    "ReceiverMacro": "Receiver (macro)",
    "OpAmp": "Op amp",
    "BiasTee": "Bias tee",
    "RFMixer": "RF mixer",
    "Amplifier": "Amplifier",
    "RFFilter": "Electrical filter",
    "LockInAmplifier": "Lock-in amplifier",
    "FiberArray": "Fibre array",
    "SMAConnector": "SMA connector",
    "PIDController": "PID controller",
    "SignalSource": "Signal source",
    "SummingJunction": "Summing junction",
    "RFSpectrumAnalyzer": "RF spectrum analyser",
    "RFSplitter": "RF power splitter",
    "RFCoupler": "RF directional coupler",
    "RFPhaseShifter": "RF phase shifter",
    # on-chip family
    "DACDriver": "DAC driver",
    "OnChipBalancedPhotodetector": "Balanced PD (on-chip)",
    "OnChipLaser": "On-chip laser",
    "OnChipPhotodetector": "On-chip photodetector",
    # compact blocks the preset chips are drawn from — small enough that a whole
    # processor fits in one figure, which is why they exist beside the full parts
    "PresetWDMInput": "WDM input (compact)",
}


def builtin_component_catalog(*, platform: str | None = None, category: str | None = None) -> dict[str, dict[str, Any]]:
    catalog: dict[str, dict[str, Any]] = {}
    for name, spec in component_registry().items():
        if platform and spec.platform not in {platform, "mixed"}:
            continue
        if category and spec.category != category:
            continue
        entry = deepcopy(_spec_to_catalog_entry(spec))
        if name in _DISPLAY_NAMES:
            entry["display_name"] = _DISPLAY_NAMES[name]
        if name in SOURCE_COMPONENT_TYPES:
            entry["source"] = True  # emits light: drives Trace mode in the editor
        catalog[name] = entry
    return catalog


def component_catalog(
    *,
    platform: str | None = None,
    category: str | None = None,
) -> dict[str, dict[str, Any]]:
    return builtin_component_catalog(platform=platform, category=category)


def list_components(
    *,
    platform: str | None = None,
    category: str | None = None,
) -> list[str]:
    return sorted(component_catalog(platform=platform, category=category).keys())


def _param_meta(name: str) -> dict[str, dict[str, Any]]:
    """Introspect a component's ``__init__`` so the editor can render the right
    widget for each parameter (toggle for bool, number for float, etc.) even when
    the value isn't set on the instance yet. Returns ``{param: {type, default}}``."""

    import inspect

    spec = component_registry().get(name)
    cls = getattr(spec, "cls", None)
    if cls is None:
        return {}
    try:
        sig = inspect.signature(cls.__init__)
    except (ValueError, TypeError):
        return {}

    meta: dict[str, dict[str, Any]] = {}
    for pname, p in sig.parameters.items():
        if pname in ("self", "args", "kwargs") or p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD):
            continue
        default = None if p.default is inspect.Parameter.empty else p.default
        # annotations are strings here (from __future__ import annotations)
        ann = p.annotation
        ann_str = ann if isinstance(ann, str) else getattr(ann, "__name__", "")
        if isinstance(default, bool) or ann_str.startswith("bool"):
            ptype = "bool"
        elif (isinstance(default, (int, float)) and not isinstance(default, bool)) or ann_str.split(" ")[0] in ("int", "float"):
            ptype = "number"
        else:
            ptype = "text"
        if ptype == "text" and default is None:
            # unannotated None-default params: the dataclass class attribute knows
            # the real type — without this, booleans render as free-text inputs
            attr = getattr(cls, pname, None)
            if isinstance(attr, bool):
                ptype, default = "bool", attr
            elif isinstance(attr, (int, float)):
                ptype, default = "number", attr
        meta[pname] = {"type": ptype, "default": default if isinstance(default, (bool, int, float, str)) else None}
        comp_choices = _COMPONENT_PARAM_CHOICES.get(name, {})
        if pname in comp_choices:
            meta[pname]["choices"] = list(comp_choices[pname])
        elif pname in _PARAM_CHOICES:
            meta[pname]["choices"] = list(_PARAM_CHOICES[pname])

    # Many registered options arrive through **kwargs and do not appear in the
    # constructor signature. Infer their controls from a default instance.
    missing = [pname for pname in spec.parameters if pname not in meta]
    if missing:
        try:
            instance = cls()
        except Exception:
            instance = None
        for pname in missing:
            try:
                default = getattr(instance, pname, None) if instance is not None else getattr(cls, pname, None)
            except Exception:
                default = None
            if isinstance(default, bool):
                ptype = "bool"
            elif isinstance(default, (int, float)):
                ptype = "number"
            else:
                ptype = "text"
            meta[pname] = {
                "type": ptype,
                "default": default if isinstance(default, (bool, int, float, str)) else None,
            }
            comp_choices = _COMPONENT_PARAM_CHOICES.get(name, {})
            if pname in comp_choices:
                meta[pname]["choices"] = list(comp_choices[pname])
            elif pname in _PARAM_CHOICES:
                meta[pname]["choices"] = list(_PARAM_CHOICES[pname])
    return meta


#: Enumerated parameters the editor renders as a dropdown rather than free text.
_PARAM_CHOICES: dict[str, tuple[str, ...]] = {
    "drive_style": ("gs", "gsg"),
    "pass_band": ("longpass", "shortpass"),
    "mechanism": ("electro_optic", "thermo_optic"),
    "port_side": ("center", "left", "right", "top", "bottom"),
    "splitter": ("ybranch", "coupler"),
    "coupler_kind": ("vertical", "focused"),
    "visual_style": ("symbolic", "publication", "presentation", "physical"),
    "package_style": ("qfp", "qfn", "bga", "die"),
}

#: Per-component choices for GENERIC parameter names ("kind", "mode", "side") whose
#: vocabulary differs between components — consulted before the global map.
def _vendor_families() -> tuple:
    """The vendor part families: each one's part numbers are the choices of its ``part``."""

    from optodraw.components.vendor import FAMILIES

    return FAMILIES


def _breadboard_parts() -> tuple[str, ...]:
    """The vendor boards a Breadboard can be, besides one sized by hand."""

    from optodraw.components.vendor.data import BREADBOARDS

    return tuple(BREADBOARDS)


_COMPONENT_PARAM_CHOICES: dict[str, dict[str, tuple[str, ...]]] = {
    **{cls.__name__: {"part": tuple(cls.TABLE)} for cls in _vendor_families()},
    "Breadboard": {"part": ("custom", *_breadboard_parts())},
    "Note": {"anchor": ("start", "middle", "end")},
    "Callout": {"anchor": ("start", "middle", "end")},
    "Bracket": {"anchor": ("start", "middle", "end"), "side": ("left", "right")},
    "DashedLink": {"anchor": ("start", "middle", "end"), "side": ("left", "right")},
    "Glyph": {"kind": ("pulse", "train", "spectrum", "wave", "spot")},
    "FlipMirror": {"state": ("up", "down", "both")},
    "GratingCouplerArray": {"coupler_kind": ("vertical", "focused")},
    "OpticalIOBank": {"coupler_kind": ("vertical", "focused"), "side": ("left", "right", "top", "bottom")},
    "ElectricalIOBank": {"side": ("left", "right", "top", "bottom")},
    "ChipSubstrate": {"kind": ("soi", "silicon", "sin", "inp")},
    "PCB": {"style": ("traces", "plain")},
    "SLM": {"mode": ("phase", "amplitude")},
    "TIABlock": {"mode": ("tia", "integrator")},
}


def describe_component(name: str) -> dict[str, Any]:
    catalog = component_catalog()
    if name not in catalog:
        raise KeyError(f"Unknown component '{name}'. Available examples: {', '.join(list_components()[:15])}")
    entry = deepcopy(catalog[name])
    entry.update(describe_physics_support(name))
    entry["units"] = dict(UNITS)
    entry["param_meta"] = _param_meta(name)
    cls = getattr(component_registry().get(name), "cls", None)
    if callable(getattr(cls, "part_sizes", None)):
        # a catalogue part: each part number's sizes from its drawing, mm, so the editor shows them as the values
        # in force until one is set by hand
        entry["part_sizes"] = {part: cls.part_sizes(part) for part in cls.TABLE}
        entry["default_part"] = cls().part                  # what a part with no ``part`` saved is
        for size in cls.size_names():
            entry["param_meta"][size] = {"type": "number", "default": None, "unit": "mm"}
    return entry


def list_component_categories() -> list[str]:
    return sorted({spec.category for spec in component_registry().values()})


def list_on_chip_components(
    *,
    schematic_default: bool | None = None,
) -> list[dict[str, Any]]:
    """Return on-chip component metadata, optionally filtered by schematic default."""

    entries: list[dict[str, Any]] = []
    for name, info in sorted(component_catalog(platform="on_chip").items()):
        if schematic_default is not None and info.get("schematic_default") is not schematic_default:
            continue
        entries.append({"name": name, **deepcopy(info)})
    return entries


_ANIMATION_RECIPE_CATALOG: tuple[tuple[str, str], ...] = (
    ("animate_focus", "Ray bundle focusing and Gaussian waist evolution."),
    ("animate_interference", "Two-path phase sweep and constructive/destructive recombination."),
    ("animate_resonance_scan", "Ring or filter resonance scan with through/drop power."),
    ("animate_modulation", "Electrical drive mapped to optical intensity modulation."),
    ("animate_mzm_mechanism", "MZM push-pull phase and intensity transfer curve."),
    ("animate_layer_stack", "GDS layer stack reveal for fabrication teaching."),
    ("animate_fiber_alignment", "Fiber-to-chip active alignment offsets and coupling loss."),
    ("animate_dispersion", "Prism or grating wavelength separation."),
    ("animate_ring_coupling", "Microring bus coupling and cavity build-up."),
    ("animate_grating_coupler_in_out", "Grating coupler fiber-to-chip coupling animation."),
    ("animate_directional_coupler_power_transfer", "Directional coupler power exchange."),
    ("animate_mmi_split_recombine", "MMI split and recombine power evolution."),
    ("animate_photodetector_absorption", "Guided mode absorption at a photodetector."),
    ("animate_pn_modulation_phase_shift", "PN junction phase shift in a modulator arm."),
    ("animate_polarization", "Jones/Stokes polarization evolution through optics."),
)


def list_animation_recipes() -> list[str]:
    return [name for name, _ in _ANIMATION_RECIPE_CATALOG]


def compile_physics_animation(scene, **kwargs: Any) -> Any:
    """Compile physics traces into animation output (requires ``optodraw.core.physics_compiler``)."""

    try:
        from optodraw.core.physics_compiler import compile_physics_animation as _compile
    except ImportError as exc:
        raise ImportError(
            "compile_physics_animation is unavailable: install or enable optodraw.core.physics_compiler."
        ) from exc
    return _compile(scene, **kwargs)


def workflow_catalog() -> dict[str, Any]:
    """Discover high-level workflow APIs (xsection, layout, animation, publication)."""

    from optodraw.presets import list_presets
    from optodraw.publication import list_publication_templates

    return {
        "xsection": {
            "XSectionEngine": {
                "module": "optodraw.gds",
                "description": "Run process-aware cross-section extraction from layout cuts.",
                "entrypoints": ["XSectionEngine.from_yaml(path)", "XSectionEngine(process)"],
            },
            "export_xsection_bundle": {
                "module": "optodraw.gds",
                "description": "Export composite SVG, per-layer SVG, and manifest for a layout cut.",
                "parameters": [
                    "process (ProcessDefinition | XSectionEngine | yaml path)",
                    "cut (LayoutCut)",
                    "output_dir",
                    "mode ('auto' | 'expert' | 'fast')",
                    "layout (optional, required for fast mode)",
                    "section (optional, required for fast mode)",
                    "rasterize (bool)",
                ],
            },
            "load_process_definition": {
                "module": "optodraw.gds",
                "description": "Load a process YAML into a ProcessDefinition.",
            },
        },
        "layout_builders": {
            "build_ring_filter": {
                "module": "optodraw.layout",
                "description": "Compose a ring-filter PIC scene from grating couplers, waveguides, ring, and detector.",
            },
            "build_mzm_mesh": {
                "module": "optodraw.layout",
                "description": (
                    "Compose a configurable MZM mesh with rectangular, row, column, "
                    "or serpentine routing."
                ),
                "parameters": [
                    "rows",
                    "cols",
                    "topology ('rectangular' | 'row' | 'column' | 'serpentine' | 'none')",
                    "row_pitch_um",
                    "col_pitch_um",
                    "include_io",
                    "cell_kwargs",
                ],
            },
            "build_microring_weight_mesh": {
                "module": "optodraw.layout",
                "description": "Compose a 2D grid of microring weight-bank cells with row and drop-bus links.",
                "parameters": [
                    "rows",
                    "cols",
                    "topology ('rectangular' | 'row' | 'column' | 'serpentine' | 'none')",
                    "ring_count",
                    "with_heaters",
                    "cell_kwargs",
                ],
            },
        },
        "animation_recipes": [
            {"name": name, "description": description}
            for name, description in _ANIMATION_RECIPE_CATALOG
        ],
        "publication": {
            "build_publication_bundle": {
                "module": "optodraw.publication",
                "description": "Render coordinated multi-format publication bundles from a scene.",
                "parameters": [
                    "scene",
                    "output_dir",
                    "template (name or TemplateSpec)",
                    "formats ('svg', 'tikz', 'png', 'html', 'json')",
                    "preset",
                    "dpi",
                    "include_polarization",
                    "caption",
                    "xsection (optional XSectionBundle)",
                ],
            },
            "templates": list_publication_templates(),
        },
        "schematic_rendering": {
            "description": "On-chip components render schematic art by default; ports and physical_spec stay in µm.",
            "component_flags": {
                "render_physical": "When True, geometry follows PDK/literal physical dimensions.",
                "visual_style": "Presentation style hint ('schematic', 'publication', 'presentation', 'physical', 'symbolic').",
                "visual_scale": "Multiplier for schematic exaggeration without changing port coordinates.",
            },
            "catalog_fields": [
                "schematic_default",
                "supports_render_physical",
                "supports_physical_spec",
            ],
        },
        "presets": list_presets(),
        "physics_bridge": {
            "physics_trace_to_timeline_hints": {
                "module": "optodraw.core.physics_bridge",
                "description": (
                    "Map scene component ids to suggested animation recipes and parameter hints."
                ),
                "parameters": [
                    "scene",
                    "wavelength_nm (default 1550.0)",
                    "include_guided_paths (default True)",
                ],
                "mcp_tool": "optodraw_physics_timeline_hints",
            },
            "compile_physics_animation": {
                "module": "optodraw.core.physics_compiler",
                "fallback_module": "optodraw.catalog",
                "description": (
                    "Compile physics traces into concrete animation recipe calls and output."
                ),
                "optional": True,
                "parameters": ["scene", "fps", "duration_s", "wavelength_nm", "include_guided_paths"],
                "mcp_tool": "optodraw_compile_physics_animation",
            },
        },
        "interactive": {
            "export_interactive_html": {
                "module": "optodraw.renderers.interactive_scene",
                "description": (
                    "Export an enhanced interactive Three.js HTML viewer with component sidebar "
                    "and optional dimension overlays."
                ),
                "parameters": [
                    "scene",
                    "path",
                    "show_component_sidebar (default True)",
                    "show_dimension_markers (default True)",
                    "dimension_markers_default (default False)",
                ],
                "mcp_tool": "optodraw_export_interactive_html",
            },
        },
    }


def describe_workflow_api(name: str) -> dict[str, Any]:
    """Return metadata for a named workflow helper (animation recipe or layout builder)."""

    catalog = workflow_catalog()
    for entry in catalog["animation_recipes"]:
        if entry["name"] == name:
            return {"kind": "animation_recipe", **entry}
    if name in catalog["layout_builders"]:
        return {"kind": "layout_builder", "name": name, **catalog["layout_builders"][name]}
    if name in catalog["publication"]["templates"]:
        from optodraw.publication import get_publication_template

        spec = get_publication_template(name)
        return {
            "kind": "publication_template",
            "name": name,
            "panel_count": spec.panel_count,
            "rows": spec.rows,
            "columns": spec.columns,
            "suggested_preset": spec.suggested_preset,
            "panels": [{"role": panel.role, "label": panel.label} for panel in spec.panels],
        }
    if name in {"XSectionEngine", "export_xsection_bundle", "load_process_definition"}:
        return {"kind": "xsection", "name": name, **catalog["xsection"][name]}
    if name == "build_publication_bundle":
        return {"kind": "publication", "name": name, **catalog["publication"][name]}
    if name in catalog.get("physics_bridge", {}):
        return {"kind": "physics_bridge", "name": name, **catalog["physics_bridge"][name]}
    if name in catalog.get("interactive", {}):
        return {"kind": "interactive", "name": name, **catalog["interactive"][name]}
    raise KeyError(
        f"Unknown workflow API '{name}'. "
        f"Try animation recipes: {', '.join(list_animation_recipes()[:8])}..."
    )
