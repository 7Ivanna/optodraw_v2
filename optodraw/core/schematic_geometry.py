"""Schematic vs physical geometry resolution for on-chip components.

Drawing paths (2D SVG, 3D HTML, GIF) default to legible schematic dimensions.
Ports, routing, and GDS export remain in physical µm — see ``PhysicalSpec`` and
``ChipComponent.physical_spec()``.  Opt in to true-scale art with
``render_physical=True``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from optodraw.components.onchip.schematic_tables import SCHEMATIC_TABLES


@dataclass(frozen=True)
class PhysicalSpec:
    """True PDK / user dimensions stored separately from schematic draw dims."""

    device_family: str
    values: dict[str, float | int | bool] = field(default_factory=dict)

    def get(self, key: str, default: float | int | bool | None = None) -> float | int | bool | None:
        return self.values.get(key, default)

    def __getitem__(self, key: str) -> float | int | bool:
        return self.values[key]


@dataclass(frozen=True)
class SchematicDims:
    """Legible diagram dimensions for 2D/3D rendering (µm unless noted)."""

    device_family: str
    values: dict[str, float] = field(default_factory=dict)

    def get(self, key: str, default: float | None = None) -> float | None:
        value = self.values.get(key, default)
        return None if value is None else float(value)

    def __getitem__(self, key: str) -> float:
        return float(self.values[key])

    @property
    def thickness(self) -> float:
        return float(self.values.get("thickness", 0.55))


def resolve_schematic_dims(
    device_family: str,
    physical: PhysicalSpec,
    *,
    visual_scale: float = 1.0,
    overrides: dict[str, float] | None = None,
) -> SchematicDims:
    """Merge per-device schematic table defaults with optional overrides.

    ``visual_scale`` multiplies schematic table entries (legacy escape hatch).
    Physical values are never copied into schematic dims — they live in
    ``PhysicalSpec`` for ports, routes, and metadata.
    """

    scale = max(float(visual_scale), 0.05)
    table = dict(SCHEMATIC_TABLES.get(device_family, {}))
    if overrides:
        table.update(overrides)

    resolved: dict[str, float] = {}
    for key, schematic_default in table.items():
        if isinstance(schematic_default, (int, float)):
            resolved[key] = float(schematic_default) * scale

    # Propagate shared keys from the device table when a family omits them.
    shared = SCHEMATIC_TABLES.get("_shared", {})
    for key, schematic_default in shared.items():
        if key not in resolved and isinstance(schematic_default, (int, float)):
            resolved[key] = float(schematic_default) * scale

    return SchematicDims(device_family=device_family, values=resolved)


def schematic_material_preset(base_preset: str, *, schematic: bool) -> str:
    """Map silicon-family presets to schematic-readable variants for 3D."""

    if not schematic:
        return base_preset
    if base_preset in {"silicon", "germanium", "indium_phosphide", "gallium_arsenide"}:
        return f"{base_preset}_schematic"
    return base_preset

