"""Optional bootstrap helpers from gdsfactory LayerStack definitions."""

from __future__ import annotations

import math
from numbers import Integral
from typing import Any


def layer_stack_hints(layer_stack: Any) -> dict[str, dict[str, Any]]:
    """Extract nominal thickness/z hints from a gdsfactory LayerStack object."""
    hints: dict[str, dict[str, Any]] = {}
    layers = getattr(layer_stack, "layers", None) or {}
    for key, level in layers.items():
        layer = getattr(level, "layer", None)
        spec = getattr(layer, "layer", layer)
        if spec is None:
            continue
        try:
            gds = tuple(spec)
        except TypeError:
            continue
        if len(gds) != 2 or any(isinstance(value, bool) or not isinstance(value, Integral) or value < 0 for value in gds):
            continue
        hints[str(key)] = {
            "gds": tuple(int(value) for value in gds),
            "zmin": float(getattr(level, "zmin", 0.0)),
            "thickness": float(getattr(level, "thickness", 0.0)),
            "material": str(getattr(level, "material", "")),
        }
    return hints


def bootstrap_process_skeleton(
    *,
    name: str = "bootstrap_process",
    layer_stack: Any | None = None,
    layout_layer_map: dict[str, tuple[int, int]] | None = None,
    device_layer: str | None = None,
) -> dict[str, Any]:
    """Return a minimal process YAML-shaped dict from LayerStack hints."""
    hints = layer_stack_hints(layer_stack) if layer_stack is not None else {}
    layout_layers: dict[str, Any] = {}
    if layout_layer_map:
        for layer_name, gds in layout_layer_map.items():
            layout_layers[layer_name] = {"gds": list(gds)}
    elif layer_stack is not None:
        for key, hint in hints.items():
            layout_layers[key] = {"gds": list(hint["gds"])}

    substrate = {"handle_thickness": 1.0, "box_thickness": 2.0}
    device = {"material": "silicon", "thickness": 0.22, "z_on_box": 0.0}
    selected = None
    if device_layer is not None:
        if device_layer not in hints:
            raise ValueError(f"Unknown device_layer {device_layer!r} in layer stack")
        selected = hints[device_layer]
    else:
        candidates = []
        for key, hint in hints.items():
            material = hint.get("material", "").lower()
            if material in {"si", "silicon", "c-si", "a-si", "poly-si", "polysilicon"} and math.isfinite(hint["thickness"]) and hint["thickness"] > 0:
                candidates.append((key, hint))
        if len(candidates) > 1:
            names = ", ".join(key for key, _ in candidates)
            raise ValueError(f"Multiple silicon device layers ({names}); specify device_layer")
        if candidates:
            selected = candidates[0][1]
    if selected is not None:
        if not math.isfinite(selected["thickness"]) or selected["thickness"] <= 0 or not math.isfinite(selected["zmin"]):
            raise ValueError("Selected device layer needs finite zmin and positive thickness")
        device["thickness"] = selected["thickness"]
        device["z_on_box"] = selected["zmin"]
        device["material"] = selected["material"] or "silicon"

    return {
        "name": name,
        "units": "um",
        "substrate": substrate,
        "device": device,
        "layout_layers": layout_layers,
        "process": [],
        "output_layers": [
            {"name": device["material"].title(), "from": "device", "color": "#004080"},
            {"name": "Oxide", "union": ["box"], "color": "#c0c0c0"},
        ],
        "render": {"z_exaggeration": 28, "legend": "right"},
    }
