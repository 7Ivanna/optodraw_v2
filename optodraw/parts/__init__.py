"""Python user parts, separate from the built-in component registry."""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Any, Mapping

from optodraw.core.component import Component
from optodraw.core.transform import Transform

from .definition import (PartDefinition, PartVariant, ParameterSpec, finite, load_svg,
                         parameter_specs, parameter_values, port_specs, qualified_name)


def _svg_namespace(owner: Component, digest: str, view: str) -> str:
    from ._svg_frame import svg_namespace

    return svg_namespace(owner, digest, view)


class UserPart(Component):
    """An instance of an immutable definition, with local ports in scene units."""

    component_type = "UserPart"

    def __init__(self, definition: PartDefinition, *, center=(0, 0), angle=0, label="",
                 scale=1.0, variant=None, parameters=None):
        if not isinstance(definition, PartDefinition):
            raise TypeError("UserPart needs a PartDefinition")
        position = self._parse_center(center)
        for value in position.as_tuple():
            finite(value, "center")
        super().__init__(label=label, transform=Transform.from_2d(position.x, position.y, finite(angle, "angle")))
        self.transform.position.z = position.z
        self._definition = definition
        self.scale = finite(scale, "scale", positive=True)
        self.variant = definition.variant(variant).name
        self.parameters = MappingProxyType(parameter_values(definition.parameters, parameters or {}))
        for port in self.ports().values():
            for value in (*port.center.as_tuple(), port.width):
                finite(value, "scaled port")

    @property
    def definition(self) -> PartDefinition:
        return self._definition

    def __deepcopy__(self, memo):
        result = object.__new__(type(self))
        memo[id(self)] = result
        for name, value in vars(self).items():
            setattr(result, name, value if name in {"_definition", "parameters"}
                    else copy.deepcopy(value, memo))
        return result

    def preview_scene(self, *, padding: float = 30.0, width: float | None = None,
                      height: float | None = None, platform: str | None = None):
        return super().preview_scene(padding=padding, width=width, height=height,
                                     platform=platform or self.definition.platform)

    @property
    def scale(self) -> float:
        return self._scale

    @scale.setter
    def scale(self, value):
        scale = finite(value, "scale", positive=True)
        variant = self.definition.variant(getattr(self, "variant", None))
        for port in variant.ports:
            for number in (*port.center, port.width):
                finite(number * scale, "scale")
        for asset in (variant.symbol_1d, variant.symbol_2d):
            if asset is not None:
                x, y, width, height = asset.view_box
                for number in (x, y, width, height, x + width, y + height):
                    finite(number * scale, "scale")
        self._scale = scale

    def ports(self):
        return {item.name: item.port(self.scale) for item in self.definition.variant(self.variant).ports}

    def geometry_2d(self) -> dict[str, Any]:
        variant = self.definition.variant(self.variant)
        asset = variant.symbol_2d or variant.symbol_1d
        x, y, width, height = asset.view_box
        return {"type": "art", "symbol": self.definition.name,
                "svg": asset.inner(namespace=_svg_namespace(self, asset.digest, "2d")),
                "matrix": (self.scale, 0, 0, self.scale, 0, 0),
                "size": (width, height),
                "bounds": (x * self.scale, -(y + height) * self.scale,
                           (x + width) * self.scale, -y * self.scale)}

    def geometry_3d(self) -> dict[str, Any]:
        variant = self.definition.variant(self.variant)
        asset = variant.symbol_2d or variant.symbol_1d
        height = min(asset.view_box[2:]) * 0.02
        return {"shape": "svg_extrusion", "svg": asset.document(),
                "height": height, "scale": [self.scale] * 3,
                "schematic": True, "part_name": self.definition.name,
                "material": {"color": "#777777", "roughness": 0.65}}

    def schematic_symbol(self, *, _namespace_owner: Component | None = None):
        from optodraw.symbols import Symbol, SymbolPort

        variant = self.definition.variant(self.variant)
        asset = variant.symbol_1d or variant.symbol_2d
        x, y, width, height = asset.view_box
        s = self.scale
        owner = self if _namespace_owner is None else _namespace_owner
        inner = asset.inner(monochrome=variant.symbol_1d is None,
                            namespace=_svg_namespace(owner, asset.digest, "1d"))
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width * s:g} {height * s:g}" '
               f'width="{width * s:g}pt" height="{height * s:g}pt">'
               f'<g transform="scale({s:g}) translate({-x:g} {-y:g})">'
               f'{inner}</g></svg>')
        sides = ("right", "top", "left", "bottom")
        ports = {item.name: SymbolPort(item.name, (item.center[0] - x) * s,
                                      (-item.center[1] - y) * s, item.kind,
                                      sides[int(math.floor((item.orientation_deg + 45) / 90)) % 4])
                 for item in variant.ports}
        return Symbol(self.definition.name, dict(self.parameters), svg, width * s, height * s,
                      (-x * s, -y * s), ports, True, "user")


@dataclass(frozen=True)
class PartFactory:
    definition: PartDefinition

    @property
    def component_class(self):
        return UserPart

    def __call__(self, *, center=(0, 0), angle=0, label="", scale=1.0, variant=None,
                 parameters=None, **values) -> UserPart:
        merged = dict(parameters or {})
        if merged.keys() & values.keys():
            raise ValueError("A parameter was supplied twice")
        merged.update(values)
        return UserPart(self.definition, center=center, angle=angle, label=label, scale=scale,
                        variant=variant, parameters=merged)


@dataclass(frozen=True)
class _TrustedFactory:
    name: str
    component_class: type[Component]
    parameters: tuple[ParameterSpec, ...]
    platform: str
    description: str

    def __call__(self, **kwargs):
        placement = {key: kwargs.pop(key) for key in ("center", "angle", "label") if key in kwargs}
        values = parameter_values(self.parameters, kwargs)
        part = self.component_class(**placement, **values)
        definition = part.portable_definition(dict(values))
        if not isinstance(definition, PartDefinition):
            raise TypeError(f"{self.name}: portable_definition must return a PartDefinition")
        part._part_definition = replace(definition, name=self.name, platform=self.platform,
                                        parameters=self.parameters)
        part._part_parameters = tuple(sorted(values.items()))
        part.component_type = self.name
        return part


class PartLibrary:
    """A scoped user registry. Updates never alter definitions held by instances."""

    def __init__(self):
        self._entries: dict[str, PartFactory | _TrustedFactory] = {}

    def add(self, definition: PartDefinition, *, replace: bool = False) -> PartFactory:
        if not isinstance(definition, PartDefinition):
            raise TypeError("PartLibrary.add needs a PartDefinition")
        old = self._entries.get(definition.name)
        if isinstance(old, PartFactory) and old.definition.digest == definition.digest:
            return old
        if old is not None and not replace:
            raise ValueError(f"Part already registered: {definition.name}")
        factory = PartFactory(definition)
        self._entries[definition.name] = factory
        return factory

    def get(self, name: str) -> PartFactory | _TrustedFactory:
        try:
            return self._entries[name]
        except KeyError:
            raise KeyError(f"Unknown user part: {name}") from None

    def names(self) -> list[str]:
        return sorted(self._entries)


_DEFAULT_LIBRARY = PartLibrary()


def default_library() -> PartLibrary:
    return _DEFAULT_LIBRARY


def define_part(name: str, *, platform: str, ports=None, symbol_2d=None, symbol_1d=None,
                parameters: Mapping[str, Mapping[str, Any]] | None = None, variants=None,
                default_variant: str | None = None, description: str = "",
                library: PartLibrary | None = None) -> PartFactory:
    """Read SVG assets now and return a factory with an immutable definition.

    SVG coordinates use y down; port coordinates use the scene's y-up frame.
    Variants supply complete ports and artwork. Parameters do not deform SVGs.
    """

    qualified_name(name)
    if variants is None:
        default_variant = default_variant or "default"
        variants = {default_variant: {"ports": ports, "symbol_2d": symbol_2d, "symbol_1d": symbol_1d}}
    elif ports is not None or symbol_2d is not None or symbol_1d is not None:
        raise ValueError("Complete variants cannot mix with top-level ports or symbols")
    if not isinstance(variants, Mapping) or not variants:
        raise ValueError("Supply at least one complete variant")
    definitions = []
    for key, values in sorted(variants.items()):
        if not isinstance(values, Mapping) or set(values) - {"ports", "symbol_1d", "symbol_2d"}:
            raise ValueError(f"Invalid complete variant: {key}")
        definitions.append(PartVariant(key, port_specs(values.get("ports")),
                                       load_svg(values.get("symbol_2d")), load_svg(values.get("symbol_1d"))))
    if default_variant is None:
        default_variant = definitions[0].name
    definition = PartDefinition(name, platform, parameter_specs(parameters), tuple(definitions),
                                default_variant, description)
    return (library if library is not None else default_library()).add(definition)


def register_part(name: str, *, parameters=None, platform="on_chip", description="",
                  library: PartLibrary | None = None):
    """Register trusted Python code; portable_definition provides its evaluated assets."""

    qualified_name(name)
    specs = parameter_specs(parameters)
    target = library if library is not None else default_library()

    def decorate(cls):
        if not isinstance(cls, type) or not issubclass(cls, Component):
            raise TypeError("register_part requires a Component subclass")
        if not callable(getattr(cls, "portable_definition", None)):
            raise TypeError("A registered Component needs portable_definition(parameters)")
        if name in target._entries:
            raise ValueError(f"Part already registered: {name}")
        if platform not in {"on_chip", "free_space", "electronics"}:
            raise ValueError(f"Unknown part platform: {platform}")
        target._entries[name] = _TrustedFactory(name, cls, specs, platform, description)
        return cls

    return decorate


from .files import load_part, save_part  # noqa: E402
from .svg_import import import_svg_part  # noqa: E402

__all__ = ["PartDefinition", "PartLibrary", "UserPart", "define_part", "register_part",
           "load_part", "save_part", "import_svg_part"]
