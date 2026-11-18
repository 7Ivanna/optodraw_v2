"""Load and validate YAML/JSON process definitions for the cross-section engine."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import math
from numbers import Integral
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class WaferLayer:
    """One blanket band of the wafer before any mask, ``z0`` to ``z1`` (um). ``name`` is its region: ``handle``,
    ``box``, ``device`` (the core) or a film's own name."""

    name: str
    material: str
    z0: float
    z1: float

    @property
    def thickness(self) -> float:
        return self.z1 - self.z0


@dataclass(frozen=True)
class LayoutLayerSpec:
    name: str
    gds: tuple[int, int]


@dataclass(frozen=True)
class ProcessStep:
    id: str
    mask: str | None = None
    deposit: dict[str, Any] | None = None
    etch: dict[str, Any] | None = None
    planarize: dict[str, Any] | None = None
    implant: dict[str, Any] | None = None
    fill: dict[str, Any] | None = None
    flip: bool = False
    snapshot: str | None = None
    caption: str | None = None


@dataclass(frozen=True)
class OutputLayerSpec:
    name: str
    color: str = "#808080"
    hatch: str = "none"
    opacity: float = 1.0
    stroke: str = "#1f2937"
    z_order: int = 0
    from_region: str | None = None
    union: list[str] | None = None


@dataclass(frozen=True)
class RenderSpec:
    z_exaggeration: float = 28.0
    y_margin_um: float = 0.5
    show_substrate: bool = True
    show_box_line: bool = True
    legend: str = "right"
    dpi: int = 300
    separate_layers: bool = True
    width_px: int = 900
    height_px: int = 420


@dataclass
class ProcessDefinition:
    name: str
    units: str
    scale: float
    wafer: tuple[WaferLayer, ...]           # bottom up; one of them is the device
    layout_layers: dict[str, LayoutLayerSpec]
    process: list[ProcessStep]
    output_layers: list[OutputLayerSpec]
    render: RenderSpec
    raw: dict[str, Any] = field(repr=False, default_factory=dict)
    fill_material: str = "sio2"             # what fills the etched space: the "oxide" region

    @property
    def device(self) -> WaferLayer:
        found = [layer for layer in self.wafer if layer.name == "device"]
        if not found:
            raise ValueError("the wafer has no device layer")
        return found[0]

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> ProcessDefinition:
        units = str(data.get("units", "um")).lower()
        if units not in ("um", "nm"):
            raise ValueError(f"Process units must be 'um' or 'nm', got {units!r}")
        scale = 1.0 if units == "um" else 0.001

        render_raw = data.get("render") or {}

        layout_layers: dict[str, LayoutLayerSpec] = {}
        gds_names: dict[tuple[int, int], str] = {}
        for name, spec in (data.get("layout_layers") or {}).items():
            gds_value = spec.get("gds") if isinstance(spec, dict) else spec
            if not isinstance(gds_value, (list, tuple)) or len(gds_value) != 2:
                raise ValueError(f"layout_layers.{name}.gds must be [layer, datatype]")
            if any(isinstance(value, bool) or not isinstance(value, Integral) or value < 0 for value in gds_value):
                raise ValueError(f"layout_layers.{name}.gds must contain nonnegative integers")
            gds = (int(gds_value[0]), int(gds_value[1]))
            if gds in gds_names:
                raise ValueError(f"layout_layers.{name}.gds duplicates {gds_names[gds]!r}")
            gds_names[gds] = str(name)
            layout_layers[str(name)] = LayoutLayerSpec(
                name=str(name),
                gds=gds,
            )

        # Length fields scale with units; fields suffixed `_um` are always
        # micrometres (layout-cut units) and fields like `taper_deg` are not
        # lengths, so neither group is scaled here.
        process_steps: list[ProcessStep] = []
        step_ids: set[str] = set()
        for entry in data.get("process") or []:
            if not isinstance(entry, dict):
                raise ValueError("Each process step must be a mapping")
            step_id = str(entry.get("id") or entry.get("name") or f"step_{len(process_steps)}")
            if step_id in step_ids:
                raise ValueError(f"Duplicate process step ID {step_id!r}")
            step_ids.add(step_id)
            deposit = _copy_dict(entry.get("deposit"))
            if deposit is None and entry.get("grow") is not None:    # the old name: a directional film
                deposit = {"conformality": 0.0, **_copy_dict(entry.get("grow"))}
            process_steps.append(
                ProcessStep(
                    id=step_id,
                    mask=str(entry["mask"]) if entry.get("mask") is not None else None,
                    deposit=_scale_lengths(deposit, ("thickness",), scale),
                    etch=_scale_lengths(_copy_dict(entry.get("etch")), ("depth",), scale),
                    planarize=_scale_lengths(_copy_dict(entry.get("planarize")), ("to_z",), scale),
                    implant=_scale_lengths(_copy_dict(entry.get("implant")), ("zmin", "zmax"), scale),
                    fill=_scale_lengths(_copy_dict(entry.get("fill")), ("to_z",), scale),
                    flip=_parse_bool(entry.get("flip", False), f"process.{step_id}.flip"),
                    snapshot=str(entry["snapshot"]) if entry.get("snapshot") is not None else None,
                    caption=str(entry["caption"]) if entry.get("caption") is not None else None,
                )
            )

        output_layers: list[OutputLayerSpec] = []
        for entry in data.get("output_layers") or []:
            if not isinstance(entry, dict):
                raise ValueError("Each output_layers entry must be a mapping")
            output_layers.append(
                OutputLayerSpec(
                    name=str(entry["name"]),
                    color=str(entry.get("color", "#808080")),
                    hatch=str(entry.get("hatch", "none")),
                    opacity=float(entry.get("opacity", 1.0)),
                    stroke=str(entry.get("stroke", "#1f2937")),
                    z_order=int(entry.get("z_order", len(output_layers))),
                    from_region=str(entry["from"]) if entry.get("from") is not None else None,
                    union=[str(item) for item in entry["union"]] if entry.get("union") else None,
                )
            )

        definition = cls(
            name=str(data.get("name", "process")),
            units=units,
            scale=scale,
            wafer=_wafer(data, scale),
            layout_layers=layout_layers,
            process=process_steps,
            output_layers=output_layers,
            render=RenderSpec(
                z_exaggeration=float(render_raw.get("z_exaggeration", 28.0)),
                y_margin_um=float(render_raw.get("y_margin_um", 0.5)),
                show_substrate=_parse_bool(render_raw.get("show_substrate", True), "render.show_substrate"),
                show_box_line=_parse_bool(render_raw.get("show_box_line", True), "render.show_box_line"),
                legend=str(render_raw.get("legend", "right")),
                dpi=int(render_raw.get("dpi", 300)),
                separate_layers=_parse_bool(render_raw.get("separate_layers", True), "render.separate_layers"),
                width_px=int(render_raw.get("width_px", 900)),
                height_px=int(render_raw.get("height_px", 420)),
            ),
            raw=data,
            fill_material=str(data.get("fill_material", "sio2")),
        )
        _validate_process_definition(definition)
        return definition

    def gds_to_layout_name(self) -> dict[tuple[int, int], str]:
        return {spec.gds: name for name, spec in self.layout_layers.items()}

    def to_layer_styles(self, output: str = "mesh") -> dict[tuple[int, int], dict[str, Any]]:
        """Emit flat zmin/thickness hints from nominal stack geometry."""
        del output
        box_bottom = next((layer.z0 for layer in self.wafer if layer.name == "box"), self.device.z0)
        device_top = self.device.z1
        styles: dict[tuple[int, int], dict[str, Any]] = {}
        for name, spec in self.layout_layers.items():
            if name.upper() in {"RIB", "SLAB", "GRAT", "WG", "WAVEGUIDE"}:
                styles[spec.gds] = {
                    "name": name,
                    "zmin": self.device.z0,
                    "thickness": self.device.thickness,
                    "color": "#004080",
                }
            elif "OX" in name.upper() or "CLAD" in name.upper():
                styles[spec.gds] = {
                    "name": name,
                    "zmin": device_top,
                    "thickness": 0.5,
                    "color": "#c0c0c0",
                }
            elif "MT" in name.upper() or "METAL" in name.upper():
                styles[spec.gds] = {
                    "name": name,
                    "zmin": device_top + 0.5,
                    "thickness": 0.2,
                    "color": "#ffcc00",
                }
            else:
                styles[spec.gds] = {
                    "name": name,
                    "zmin": box_bottom,
                    "thickness": -box_bottom + self.device.thickness,
                    "color": "#888888",
                }
        return styles


def _parse_bool(value: Any, name: str) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "yes", "on", "1"}:
            return True
        if normalized in {"false", "no", "off", "0"}:
            return False
    raise ValueError(f"{name} must be a boolean")


def _wafer(data: dict[str, Any], scale: float) -> tuple[WaferLayer, ...]:
    """The ``wafer:`` list, bottom up. An old process file gives ``substrate:`` and ``device:`` instead: a handle, a
    box that ends at z = 0 and the device on it."""

    if data.get("wafer") is not None:
        entries = data["wafer"]
        if not isinstance(entries, list) or not all(isinstance(entry, dict) for entry in entries):
            raise ValueError("wafer must be a list of mappings with name, material, z0 and z1, bottom up")
        return tuple(WaferLayer(str(entry["name"]), str(entry["material"]), float(entry["z0"]) * scale,
                                float(entry["z1"]) * scale) for entry in entries)
    substrate = data.get("substrate") or {}
    device = data.get("device") or {}
    handle = float(substrate.get("handle_thickness", 0.0)) * scale
    box = float(substrate.get("box_thickness", 0.0)) * scale
    thickness = float(device.get("thickness", 0.22 if scale == 1.0 else 220.0)) * scale
    z_on_box = float(device.get("z_on_box", 0.0)) * scale
    return (WaferLayer("handle", str(substrate.get("handle_material", "handle")), -box - handle, -box),
            WaferLayer("box", str(substrate.get("box_material", "sio2")), -box, 0.0),
            WaferLayer("device", str(device.get("material", "silicon")), z_on_box, z_on_box + thickness))


def _validate_process_definition(definition: ProcessDefinition) -> None:
    def nonnegative(name: str, value: float) -> None:
        if not math.isfinite(value) or value < 0:
            raise ValueError(f"{name} must be finite and nonnegative")

    def positive(name: str, value: float) -> None:
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"{name} must be finite and positive")

    for layer in definition.wafer:
        if not (math.isfinite(layer.z0) and math.isfinite(layer.z1)):
            raise ValueError(f"wafer layer {layer.name!r} must have finite z0 and z1")
        nonnegative(f"wafer layer {layer.name!r} thickness", layer.thickness)
    positive("device.thickness", definition.device.thickness)
    positive("render.z_exaggeration", definition.render.z_exaggeration)
    nonnegative("render.y_margin_um", definition.render.y_margin_um)
    positive("render.dpi", definition.render.dpi)
    positive("render.width_px", definition.render.width_px)
    positive("render.height_px", definition.render.height_px)
    for layer in definition.output_layers:
        if not math.isfinite(layer.opacity) or not 0 <= layer.opacity <= 1:
            raise ValueError(f"output layer {layer.name!r} opacity must be between 0 and 1")


def _copy_dict(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("Process operation blocks must be mappings")
    return dict(value)


def _scale_lengths(mapping: dict[str, Any] | None, keys: tuple[str, ...], scale: float) -> dict[str, Any] | None:
    if mapping is None or scale == 1.0:
        return mapping
    scaled = dict(mapping)
    for key in keys:
        if key in scaled and scaled[key] is not None:
            scaled[key] = float(scaled[key]) * scale
    return scaled


def _load_mapping(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    suffix = path.suffix.lower()
    if suffix in {".yaml", ".yml"}:
        try:
            import yaml
        except ImportError as exc:
            raise ImportError("pyyaml is required to load YAML process definitions") from exc
        loaded = yaml.safe_load(text)
    elif suffix == ".json":
        loaded = json.loads(text)
    else:
        try:
            loaded = json.loads(text)
        except json.JSONDecodeError:
            try:
                import yaml
            except ImportError as exc:
                raise ImportError("pyyaml is required to load YAML process definitions") from exc
            loaded = yaml.safe_load(text)
    if not isinstance(loaded, dict):
        raise ValueError("Process definition root must be a mapping")
    return loaded


def load_process_definition(path: str | Path) -> ProcessDefinition:
    return ProcessDefinition.from_mapping(_load_mapping(Path(path)))
