"""Registry-driven quickplot helpers for component smoke notebooks."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from optodraw import Scene
from optodraw.registry import build_component, component_registry


ASSET_DIR = Path(__file__).resolve().parent / "assets"

REGISTRY_NOTEBOOK_GROUPS: dict[str, dict[str, tuple[str, ...]]] = {
    "free_space": {
        "categories": ("optics", "devices", "instruments", "samples", "misc", "light_paths"),
        "platforms": ("free_space",),
    },
    "on_chip": {
        "categories": ("on_chip", "models"),
        "platforms": ("on_chip",),
    },
    "electronics": {
        "categories": ("electronics", "models", "routing", "annotation"),
        "platforms": ("mixed", "on_chip"),
    },
}


def registry_component_names(group: str) -> list[str]:
    """Return registry component names assigned to a quickplot notebook group."""

    if group not in REGISTRY_NOTEBOOK_GROUPS:
        raise KeyError(f"Unknown quickplot group: {group}")
    config = REGISTRY_NOTEBOOK_GROUPS[group]
    categories = set(config["categories"])
    platforms = set(config["platforms"])
    names: list[str] = []
    for name, spec in component_registry().items():
        if spec.category in categories and spec.platform in platforms:
            names.append(name)
    return names


def quickplot_registry_component_names() -> list[str]:
    """Return every registry component covered by the quickplot notebooks."""

    names: list[str] = []
    for group in REGISTRY_NOTEBOOK_GROUPS:
        names.extend(registry_component_names(group))
    return sorted(set(names))


def _grid_center(index: int, total: int, columns: int, spacing: tuple[float, float]) -> tuple[float, float]:
    row_count = (total + columns - 1) // columns
    row, col = divmod(index, columns)
    x0 = -spacing[0] * (columns - 1) / 2.0
    y0 = spacing[1] * (row_count - 1) / 2.0
    return x0 + col * spacing[0], y0 - row * spacing[1]


def _source_path(filename: str) -> str:
    path = ASSET_DIR / filename
    return path.as_posix() if path.exists() else filename


def _registry_kwargs(name: str, center: tuple[float, float]) -> dict[str, Any]:
    spec = component_registry()[name]
    x, y = center
    kwargs: dict[str, Any] = {}

    if "center" in spec.parameters:
        kwargs["center"] = center
    if "label" in spec.parameters:
        kwargs["label"] = name
    if "visual_style" in spec.parameters:
        kwargs["visual_style"] = "publication"

    if name == "Beam":
        return {"anchors": ((x - 12.0, y), (x + 12.0, y)), "label": name}
    if name == "Route":
        return {
            "points": ((x - 12.0, y), (x - 3.0, y + 7.0), (x + 12.0, y)),
            "width": 0.6,
            "kind": "waveguide",
            "label": name,
        }
    if name == "CustomModel":
        kwargs.update({"source": "quickplot_placeholder.glb", "footprint": (16.0, 12.0), "height": 8.0})
    elif name == "GDSModel":
        kwargs.update({"source": _source_path("demo_mask.gds"), "footprint": (20.0, 14.0)})
    elif name == "Grid":
        kwargs.update({"width": 18.0, "height": 18.0, "pitch": 4.0, "label": name})
    elif name == "Note":
        kwargs = {"text": name, "center": center}
    elif name == "MetalRoute":
        kwargs = {
            "points": ((x - 12.0, y - 5.0), (x - 3.0, y + 5.0), (x + 12.0, y + 5.0)),
            "label": name,
        }
    elif name == "SignalArrow":
        kwargs = {"start": (x - 12.0, y), "end": (x + 12.0, y), "signal": "rf", "label": name}
    elif name == "OpticalTable":
        kwargs.update({"length": 24.0, "width": 16.0, "include_holes": True})
    elif name == "Breadboard":
        kwargs.update({"length": 24.0, "width": 16.0, "include_holes": True})
    elif name == "VacuumChamber":
        kwargs.update({"diameter": 14.0, "length": 20.0, "window_count": 3})
    elif name == "TranslationStage":
        kwargs.update({"length": 20.0, "width": 12.0})
    elif name == "RotationStage":
        kwargs.update({"diameter": 16.0})
    elif name == "OpticalIOBank":
        kwargs.update({"count": 4, "pitch": 16.0})
    elif name == "StarCoupler":
        kwargs.update({"input_count": 3, "output_count": 4})
    elif name == "AWG":
        kwargs.update({"channel_count": 4, "array_count": 8})
    elif name == "GratingCouplerArray":
        kwargs.update({"count": 4, "pitch": 18.0})
    elif name == "MicroringWeightBank":
        kwargs.update({"ring_count": 3})
    elif name == "ElectricalIOBank":
        kwargs.update({"count": 5, "pitch": 8.0})
    elif name in {"CoherentReceiver", "TransmitterMacro", "ReceiverMacro", "PCB"}:
        kwargs.update({"length": 28.0, "width": 16.0, "visual_scale": 0.7})
    elif name == "MEMSActuator":
        kwargs.update({"finger_count": 8})

    return kwargs


def make_registry_component(name: str, center: tuple[float, float]):
    """Instantiate one registered component at a quickplot grid location."""

    return build_component(name, **_registry_kwargs(name, center))


def build_quickplot_scene(
    names: Iterable[str],
    *,
    title: str,
    platform: str = "mixed",
    columns: int = 5,
    spacing: tuple[float, float] = (48.0, 36.0),
    strict: bool = True,
) -> tuple[Scene, list[dict[str, str]]]:
    """Build a grid scene for registered components and collect failures."""

    component_names = list(names)
    row_count = (len(component_names) + columns - 1) // columns
    scene = Scene(
        title=title,
        width=max(160.0, columns * spacing[0] + 32.0),
        height=max(120.0, row_count * spacing[1] + 32.0),
        platform=platform,
    )
    failures: list[dict[str, str]] = []
    for index, name in enumerate(component_names):
        center = _grid_center(index, len(component_names), columns, spacing)
        try:
            scene.add(make_registry_component(name, center))
        except Exception as exc:  # pragma: no cover - notebook diagnostics path
            failures.append({"name": name, "error": repr(exc)})
            if strict:
                raise

    scene.metadata["quickplot_components"] = component_names
    scene.metadata["quickplot_failures"] = failures
    return scene, failures

