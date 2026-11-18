"""Technology and layer-stack definitions for GDS export."""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from os import PathLike
from pathlib import Path
from typing import Any

from optodraw.gds.styles import (
    GDS_LAYER_PALETTE,
    LayerSpec,
    _format_layer_description,
    _normalize_layer_key,
    coerce_scalar,
    get_gdsfactory_layer_styles,
    material_preset_from_layer_name,
    normalize_layer_stack,
)


def _style_bool(value: Any, *, field_name: str) -> bool:
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off"}:
            return False
        raise ValueError(f"Invalid {field_name} value: {value!r}")
    return bool(value)

@dataclass(frozen=True)
class TechnologyLayer:
    spec: LayerSpec
    name: str
    description: str = ""
    color: str = "#0b7285"
    opacity: float = 0.78
    thickness: float = 0.22
    zmin: float = 0.0
    material_preset: str = "silicon"
    visible: bool = True
    material_name: str | None = None
    level_name: str | None = None
    purpose: str | None = None
    style_source: str = "technology"
    metadata: dict[str, Any] = field(default_factory=dict)
    physical_stack_known: bool = True

    @classmethod
    def from_style(cls, spec: LayerSpec, style: dict[str, Any]) -> "TechnologyLayer":
        name = str(style.get("name", style.get("level_name", f"L{spec[0]}/{spec[1]}")))
        material_name = style.get("material") if isinstance(style.get("material"), str) else None
        material_preset = style.get("material_preset", style.get("preset"))
        if not isinstance(material_preset, str) or not material_preset:
            material_preset = material_preset_from_layer_name(name) or "silicon"

        thickness_value = coerce_scalar(style.get("thickness"))
        zmin_value = coerce_scalar(style.get("zmin", style.get("z_offset")))
        opacity_value = coerce_scalar(style.get("opacity"))
        for field_name, value in (
            ("thickness", thickness_value),
            ("zmin", zmin_value),
            ("opacity", opacity_value),
        ):
            if value is not None and not math.isfinite(value):
                raise ValueError(f"Layer {spec} has nonfinite {field_name}")
        known_keys = {
            "name",
            "description",
            "fill",
            "color",
            "opacity",
            "thickness",
            "zmin",
            "z_offset",
            "material",
            "material_preset",
            "preset",
            "visible",
            "level_name",
            "purpose",
            "style_source",
            "physical_stack_known",
        }
        metadata = {key: value for key, value in style.items() if key not in known_keys}
        description = style.get("description")
        if not isinstance(description, str) or not description:
            description = _format_layer_description(
                spec,
                name=name,
                material_name=material_name,
                material_preset=material_preset,
                thickness=thickness_value,
                zmin=zmin_value,
                source_label=str(style.get("style_source", "TECHNOLOGY")).upper(),
            )

        return cls(
            spec=spec,
            name=name,
            description=description,
            color=str(style.get("fill") or style.get("color") or GDS_LAYER_PALETTE[spec[0] % len(GDS_LAYER_PALETTE)]),
            opacity=max(0.0, min(1.0, float(opacity_value if opacity_value is not None else 0.78))),
            thickness=float(thickness_value if thickness_value is not None else 0.22),
            zmin=float(zmin_value if zmin_value is not None else 0.0),
            material_preset=material_preset,
            visible=_style_bool(style.get("visible", True), field_name="visible"),
            material_name=material_name,
            level_name=style.get("level_name") if isinstance(style.get("level_name"), str) else None,
            purpose=style.get("purpose") if isinstance(style.get("purpose"), str) else None,
            style_source=str(style.get("style_source", "technology")),
            metadata=metadata,
            physical_stack_known=_style_bool(
                style.get("physical_stack_known", thickness_value is not None and zmin_value is not None),
                field_name="physical_stack_known",
            ),
        )

    def to_style(self) -> dict[str, Any]:
        style: dict[str, Any] = {
            "name": self.name,
            "description": self.description,
            "color": self.color,
            "opacity": self.opacity,
            "thickness": self.thickness,
            "zmin": self.zmin,
            "z_offset": self.zmin,
            "material_preset": self.material_preset,
            "visible": self.visible,
            "style_source": self.style_source,
            "physical_stack_known": self.physical_stack_known,
        }
        if self.material_name is not None:
            style["material"] = self.material_name
        if self.level_name is not None:
            style["level_name"] = self.level_name
        if self.purpose is not None:
            style["purpose"] = self.purpose
        style.update(self.metadata)
        return style

    def to_dict(self) -> dict[str, Any]:
        return {"spec": self.spec, **self.to_style()}


@dataclass(frozen=True)
class Technology:
    name: str = "custom"
    layers: dict[LayerSpec, TechnologyLayer] = field(default_factory=dict)
    source: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_layer_styles(
        cls,
        styles: dict[Any, dict[str, Any]],
        *,
        name: str = "custom",
        source: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> "Technology":
        layers = {
            spec: TechnologyLayer.from_style(spec, style)
            for spec, style in normalize_layer_stack(styles).items()
        }
        return cls(name=name, layers=layers, source=source, metadata=dict(metadata or {}))

    @classmethod
    def from_blendergds_layer_config(
        cls,
        layer_config_path: str | PathLike[str],
        *,
        color_config_path: str | PathLike[str] | None = None,
        name: str | None = None,
        include_filler: bool = False,
        **kwargs,
    ) -> "Technology":
        from optodraw.gds.parsers import parse_blendergds_layer_config

        styles = parse_blendergds_layer_config(
            layer_config_path,
            color_config_path=color_config_path,
            include_filler=include_filler,
            **kwargs,
        )
        path = Path(layer_config_path).expanduser()
        return cls.from_layer_styles(
            styles,
            name=name or path.stem,
            source=path.as_posix(),
            metadata={"format": "blendergds-yaml"},
        )

    @classmethod
    def from_blendergds_yaml(
        cls,
        stack: str | PathLike[str],
        *,
        colors: str | PathLike[str] | None = None,
        **kwargs,
    ) -> "Technology":
        return cls.from_blendergds_layer_config(
            stack,
            color_config_path=colors,
            **kwargs,
        )

    @classmethod
    def from_gds3d_techfile(
        cls,
        techfile_path: str | PathLike[str],
        *,
        name: str | None = None,
        **kwargs,
    ) -> "Technology":
        from optodraw.gds.parsers import parse_gds3d_techfile

        styles = parse_gds3d_techfile(techfile_path, **kwargs)
        path = Path(techfile_path).expanduser()
        return cls.from_layer_styles(
            styles,
            name=name or path.stem,
            source=path.as_posix(),
            metadata={"format": "gds3d-techfile"},
        )

    @classmethod
    def from_klayout_lyp(
        cls,
        lyp_path: str | PathLike[str],
        *,
        name: str | None = None,
        include_hidden: bool = False,
        **kwargs,
    ) -> "Technology":
        from optodraw.gds.parsers import parse_klayout_lyp

        styles = parse_klayout_lyp(lyp_path, include_hidden=include_hidden, **kwargs)
        path = Path(lyp_path).expanduser()
        return cls.from_layer_styles(
            styles,
            name=name or path.stem,
            source=path.as_posix(),
            metadata={"format": "klayout-lyp"},
        )

    @classmethod
    def from_gdsfactory(
        cls,
        *,
        name: str = "gdsfactory",
        pdk: Any | None = None,
        layers: Any | None = None,
        layer_stack: Any | None = None,
        layer_views: Any | None = None,
        aux_layer_depths: dict[Any, dict[str, Any]] | None = None,
        material_aliases: dict[str, str] | None = None,
    ) -> "Technology":
        styles = get_gdsfactory_layer_styles(
            pdk=pdk,
            layers=layers,
            layer_stack=layer_stack,
            layer_views=layer_views,
            aux_layer_depths=aux_layer_depths,
            material_aliases=material_aliases,
        )
        return cls.from_layer_styles(styles, name=name, metadata={"format": "gdsfactory"})

    @classmethod
    def from_gdsfactory_pdk(cls, pdk: Any | None = None, **kwargs) -> "Technology":
        return cls.from_gdsfactory(pdk=pdk, **kwargs)

    @classmethod
    def generic_pdk(cls) -> "Technology":
        return cls.from_gdsfactory(name="generic-pdk")

    def layer_styles(self, *, include_hidden: bool = True) -> dict[LayerSpec, dict[str, Any]]:
        return {
            spec: layer.to_style()
            for spec, layer in self.layers.items()
            if include_hidden or layer.visible
        }

    def to_layer_styles(self, *, include_hidden: bool = True) -> dict[LayerSpec, dict[str, Any]]:
        return self.layer_styles(include_hidden=include_hidden)

    def layer_name_map(self) -> dict[LayerSpec, str]:
        return {spec: layer.name for spec, layer in self.layers.items()}

    def describe_layers(self, *, include_hidden: bool = True) -> list[dict[str, Any]]:
        return [
            self.layers[spec].to_dict()
            for spec in sorted(self.layers)
            if include_hidden or self.layers[spec].visible
        ]

    def get(self, spec: Any) -> TechnologyLayer | None:
        normalized = _normalize_layer_key(spec)
        if normalized is None:
            return None
        return self.layers.get(normalized)

    def with_overrides(
        self,
        overrides: dict[Any, dict[str, Any]],
        *,
        name: str | None = None,
    ) -> "Technology":
        styles = self.layer_styles(include_hidden=True)
        for spec, override in normalize_layer_stack(overrides).items():
            styles[spec] = {**styles.get(spec, {}), **override}
        return Technology.from_layer_styles(
            styles,
            name=name or self.name,
            source=self.source,
            metadata=self.metadata,
        )
