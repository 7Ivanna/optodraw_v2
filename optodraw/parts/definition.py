"""Immutable part definitions and validated vector assets."""

from __future__ import annotations

import hashlib
import json
import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from optodraw.core.ports import Port
from optodraw.core.transform import Vec3

_RESERVED = {"center", "angle", "label", "scale", "variant", "parameters"}
_SHAPES = {"path", "rect", "circle", "ellipse", "line", "polyline", "polygon"}
_ELEMENTS = _SHAPES | {"svg", "g", "defs", "clipPath", "title", "desc"}
_PRESENTATION = {"fill", "stroke", "stroke-width", "fill-rule", "clip-rule", "clip-path",
                 "opacity", "fill-opacity", "stroke-opacity", "stroke-linecap", "stroke-linejoin",
                 "stroke-dasharray", "stroke-dashoffset", "stroke-miterlimit", "display", "visibility"}
_SVG_NS = "http://www.w3.org/2000/svg"


def finite(value: Any, name: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    try:
        result = float(value)
    except OverflowError as error:
        raise ValueError(f"{name} must be finite") from error
    if not math.isfinite(result) or (positive and result <= 0):
        raise ValueError(f"{name} must be finite" + (" and positive" if positive else ""))
    return result


def qualified_name(name: str) -> str:
    if not isinstance(name, str) or not re.fullmatch(r"user:[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", name):
        raise ValueError("Use a qualified part name: user:library/Part")
    return name


@dataclass(frozen=True)
class ParameterSpec:
    name: str
    type: str
    default: Any
    min: float | None = None
    max: float | None = None
    choices: tuple[str, ...] = ()
    unit: str = ""

    def __post_init__(self):
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", self.name) or self.name in _RESERVED:
            raise ValueError(f"Invalid or reserved parameter name: {self.name}")
        if self.type not in {"float", "int", "bool", "enum", "string"}:
            raise ValueError(f"Unknown parameter type for {self.name}: {self.type}")
        if not isinstance(self.unit, str):
            raise ValueError(f"Parameter {self.name} unit must be a string")
        object.__setattr__(self, "choices", tuple(self.choices))
        if self.type == "enum":
            if not self.choices or any(not isinstance(item, str) for item in self.choices):
                raise ValueError(f"Parameter {self.name} needs string enum choices")
            if len(set(self.choices)) != len(self.choices):
                raise ValueError(f"Parameter {self.name} has duplicate enum choices")
        elif self.choices:
            raise ValueError(f"Only enum parameters have choices: {self.name}")
        for field in ("min", "max"):
            value = getattr(self, field)
            if value is not None:
                if self.type not in {"float", "int"}:
                    raise ValueError(f"Only numeric parameters have bounds: {self.name}")
                object.__setattr__(self, field, finite(value, self.name))
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError(f"Parameter {self.name} has reversed bounds")
        object.__setattr__(self, "default", self.validate(self.default))

    def validate(self, value: Any) -> Any:
        valid = {"int": type(value) is int, "bool": type(value) is bool,
                 "string": isinstance(value, str),
                 "enum": isinstance(value, str) and value in self.choices}
        if self.type == "float":
            value = finite(value, self.name)
        elif not valid.get(self.type, False):
            raise ValueError(f"Invalid {self.type} parameter: {self.name}")
        if self.type == "int":
            finite(value, self.name)
        if self.min is not None and value < self.min:
            raise ValueError(f"Parameter {self.name} is below its minimum")
        if self.max is not None and value > self.max:
            raise ValueError(f"Parameter {self.name} exceeds its maximum")
        return value

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.type, "default": self.default, "min": self.min,
                "max": self.max, "choices": list(self.choices), "unit": self.unit}


def parameter_specs(parameters: Mapping[str, Mapping[str, Any]] | None) -> tuple[ParameterSpec, ...]:
    result = []
    for name, spec in sorted((parameters or {}).items()):
        try:
            result.append(ParameterSpec(name=name, **dict(spec)))
        except TypeError as error:
            raise ValueError(f"Invalid parameter schema: {name}") from error
    return tuple(result)


def parameter_values(specs: tuple[ParameterSpec, ...], values: Mapping[str, Any]) -> dict[str, Any]:
    unknown = set(values) - {spec.name for spec in specs}
    if unknown:
        raise ValueError(f"Unknown parameter(s): {', '.join(sorted(unknown))}")
    return {spec.name: spec.validate(values.get(spec.name, spec.default)) for spec in specs}


@dataclass(frozen=True)
class PortSpec:
    name: str
    center: tuple[float, ...]
    orientation_deg: float = 0
    width: float = 0.5
    kind: str = "optical"
    layer: str | None = None

    def __post_init__(self):
        if not isinstance(self.name, str) or not self.name or len(self.name) > 128:
            raise ValueError("A port needs a nonempty name")
        if self.kind not in {"optical", "waveguide", "fiber", "electrical", "thermal", "free_space"}:
            raise ValueError(f"Unknown port kind: {self.kind}")
        if self.layer is not None and not isinstance(self.layer, str):
            raise ValueError(f"Invalid port layer: {self.name}")
        if not isinstance(self.center, (list, tuple)) or len(self.center) not in {2, 3}:
            raise ValueError(f"A port center needs two or three coordinates: {self.name}")
        coords = tuple(finite(value, f"port {self.name} center") for value in self.center)
        object.__setattr__(self, "center", coords if len(coords) == 3 else (*coords, 0.0))
        object.__setattr__(self, "orientation_deg", finite(self.orientation_deg, f"port {self.name} angle") % 360)
        object.__setattr__(self, "width", finite(self.width, f"port {self.name} width", positive=True))

    def port(self, scale: float) -> Port:
        return Port(self.name, Vec3(*(value * scale for value in self.center)),
                    self.orientation_deg, self.width * scale, self.kind, self.layer)

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "center": list(self.center), "orientation_deg": self.orientation_deg,
                "width": self.width, "kind": self.kind, "layer": self.layer}


def port_specs(ports) -> tuple[PortSpec, ...]:
    if ports is None:
        raise ValueError("Each complete variant must declare its ports")
    try:
        result = tuple(sorted((PortSpec(**dict(port)) for port in ports), key=lambda port: port.name))
    except TypeError as error:
        raise ValueError("Invalid port definition") from error
    if len({port.name for port in result}) != len(result):
        raise ValueError("Duplicate port name")
    return result


@dataclass(frozen=True)
class SvgAsset:
    data: bytes
    view_box: tuple[float, float, float, float]

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.data).hexdigest()

    def root(self) -> ET.Element:
        root = ET.fromstring(self.data)
        for node in root.iter():
            node.tag = node.tag.removeprefix(f"{{{_SVG_NS}}}")
        return root

    def document(self) -> str:
        """Render SVG lengths in the asset frame; keep its stored bytes unchanged."""
        from ._svg_frame import resolved_root

        root = resolved_root(self.root(), self.view_box)
        root.set("xmlns", "http://www.w3.org/2000/svg")
        return ET.tostring(root, encoding="unicode")

    def inner(self, *, monochrome: bool = False, namespace: str | None = None) -> str:
        from ._svg_frame import resolved_root

        root = resolved_root(self.root(), self.view_box, namespace=namespace)
        if monochrome:
            def paint(node):
                if node.tag in {"defs", "clipPath"}:
                    return
                for key in ("fill", "stroke", "opacity", "fill-opacity", "stroke-opacity"):
                    node.attrib.pop(key, None)
                if node.tag in _SHAPES:
                    node.set("fill", "none")
                    node.set("stroke", "#000")
                    node.set("stroke-width", f"{max(min(self.view_box[2:]) * 0.04, 1e-6):g}")
                for child in node:
                    paint(child)

            paint(root)
        root.tag = "g"
        for key in ("viewBox", "width", "height", "xmlns"):
            root.attrib.pop(key, None)
        return ET.tostring(root, encoding="unicode")


def load_svg(source: str | bytes | Path | None) -> SvgAsset | None:
    if source is None:
        return None
    if isinstance(source, bytes):
        data = source
    elif isinstance(source, str) and source.lstrip().startswith("<"):
        data = source.encode("utf-8")
    else:
        path = Path(source).expanduser()
        if path.stat().st_size > 10 * 1024 * 1024:
            raise ValueError("SVG exceeds the 10 MiB asset limit")
        data = path.read_bytes()
    if len(data) > 10 * 1024 * 1024 or b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
        raise ValueError("SVG is too large or contains an XML declaration with entities")
    try:
        root = ET.fromstring(data.decode("utf-8"))
    except (ET.ParseError, UnicodeError) as error:
        raise ValueError("Invalid SVG document") from error
    if root.tag not in {"svg", f"{{{_SVG_NS}}}svg"}:
        raise ValueError("SVG needs an svg root")
    for index, node in enumerate(root.iter()):
        if index >= 10000:
            raise ValueError("SVG has too many elements")
        tag = node.tag.removeprefix(f"{{{_SVG_NS}}}")
        if tag not in _ELEMENTS:
            raise ValueError(f"Unsupported SVG element: {tag}; convert text to paths")
        node.tag = tag
        style = node.attrib.pop("style", "")
        for declaration in style.split(";"):
            if declaration.strip():
                key, separator, value = declaration.partition(":")
                if not separator or key.strip() not in _PRESENTATION:
                    raise ValueError("Unsupported SVG style")
                node.set(key.strip(), value.strip())
        for key, value in node.attrib.items():
            if key.lower().startswith("on") or "href" in key.lower() or key.startswith("{"):
                raise ValueError(f"Unsafe SVG attribute: {key}")
            if re.search(r"url\s*\(", value, re.I) and not re.fullmatch(r"url\(#[A-Za-z0-9_.:-]+\)", value):
                raise ValueError("External SVG references are not allowed")
        node.tail = None
    try:
        box = tuple(float(value) for value in re.split(r"[\s,]+", root.attrib["viewBox"].strip()))
    except (KeyError, ValueError) as error:
        raise ValueError("SVG needs a numeric viewBox") from error
    if len(box) != 4 or not all(math.isfinite(value) for value in box) or box[2] <= 0 or box[3] <= 0:
        raise ValueError("SVG viewBox must have finite coordinates and positive dimensions")
    root.set("xmlns", _SVG_NS)
    root.attrib.pop("width", None)
    root.attrib.pop("height", None)
    return SvgAsset(ET.tostring(root, encoding="utf-8"), box)


@dataclass(frozen=True)
class PartVariant:
    name: str
    ports: tuple[PortSpec, ...]
    symbol_2d: SvgAsset | None
    symbol_1d: SvgAsset | None

    def __post_init__(self):
        if not isinstance(self.name, str) or not self.name:
            raise ValueError("Each variant needs a name")
        object.__setattr__(self, "ports", tuple(self.ports))
        if self.symbol_1d is None and self.symbol_2d is None:
            raise ValueError("Supply a 1D symbol SVG or a 2D SVG for monochrome lines")

    def to_dict(self) -> dict[str, Any]:
        return {"ports": [port.to_dict() for port in self.ports],
                "symbol_2d": None if self.symbol_2d is None else self.symbol_2d.digest,
                "symbol_1d": None if self.symbol_1d is None else self.symbol_1d.digest}


@dataclass(frozen=True)
class PartDefinition:
    """A portable definition; all nested data is immutable and content hashed."""

    name: str
    platform: str
    parameters: tuple[ParameterSpec, ...]
    variants: tuple[PartVariant, ...]
    default_variant: str
    description: str = ""

    def __post_init__(self):
        qualified_name(self.name)
        if self.platform not in {"on_chip", "free_space", "electronics"}:
            raise ValueError(f"Unknown part platform: {self.platform}")
        if not isinstance(self.description, str):
            raise ValueError("A part description must be a string")
        object.__setattr__(self, "parameters", tuple(self.parameters))
        object.__setattr__(self, "variants", tuple(self.variants))
        if len({item.name for item in self.parameters}) != len(self.parameters):
            raise ValueError("Duplicate parameter name")
        names = {item.name for item in self.variants}
        if len(names) != len(self.variants) or self.default_variant not in names:
            raise ValueError("Invalid or duplicate default variant")

    @property
    def assets(self) -> Mapping[str, bytes]:
        return MappingProxyType({asset.digest: asset.data for variant in self.variants
                                 for asset in (variant.symbol_1d, variant.symbol_2d) if asset is not None})

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "platform": self.platform, "description": self.description,
                "parameters": {item.name: item.to_dict() for item in self.parameters},
                "variants": {item.name: item.to_dict() for item in self.variants},
                "default_variant": self.default_variant}

    @property
    def digest(self) -> str:
        payload = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"), allow_nan=False)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def variant(self, name: str | None = None) -> PartVariant:
        name = self.default_variant if name is None else name
        for variant in self.variants:
            if variant.name == name:
                return variant
        raise ValueError(f"Unknown variant for {self.name}: {name}")
