"""Parameterized scene generators for the GUI **Generate** dialog.

Thin registry over the optodraw layout/recipe builders. Each entry exposes a
``label`` plus ``fields`` (the dialog input spec the front-end renders) and builds a
fresh ``Scene`` to load into the editor. No layout logic lives here — it only calls the
library ``build_*`` functions (the same path as presets), keeping the API a thin adapter.
"""

from __future__ import annotations

import math
from typing import Any

_TOPOLOGIES = ["rectangular", "row", "column", "serpentine"]

# field spec mirrors dialogForm: {key, label, type: number|select|checkbox, value, ...}
_GENERATORS: dict[str, dict[str, Any]] = {
    "mzm_mesh": {
        "label": "MZM mesh (modulators + couplers)",
        "fields": [
            {"key": "modes", "label": "Modes", "type": "number", "value": 4, "min": 2, "max": 8, "step": 1},
            {"key": "layers", "label": "Layers", "type": "number", "value": 4, "min": 1, "max": 8, "step": 1},
            {"key": "drive_style", "label": "Drive", "type": "select", "value": "gsg", "options": ["gs", "gsg"]},
        ],
    },
    "microring_weight_mesh": {
        "label": "Microring weight mesh",
        "fields": [
            {"key": "rows", "label": "Rows", "type": "number", "value": 2, "min": 1, "max": 6, "step": 1},
            {"key": "cols", "label": "Columns", "type": "number", "value": 2, "min": 1, "max": 6, "step": 1},
            {"key": "ring_count", "label": "Rings / bank", "type": "number", "value": 4, "min": 1, "max": 8, "step": 1},
            {"key": "topology", "label": "Topology", "type": "select", "value": "rectangular", "options": _TOPOLOGIES},
            {"key": "with_heaters", "label": "Heaters", "type": "checkbox", "value": True},
        ],
    },
    "ring_filter": {
        "label": "Ring filter (GC → ring → PD)",
        "fields": [
            {"key": "add_drop", "label": "Add-drop", "type": "checkbox", "value": True},
            {"key": "spacing_um", "label": "Spacing (µm)", "type": "number", "value": 12.0, "min": 4, "max": 40, "step": 1},
        ],
    },
    "detector_readout_chain": {
        "label": "Detector readout (PD → TIA → ADC)",
        "fields": [],
    },
    "modulator_drive_chain": {
        "label": "Modulator drive (DAC → MZM)",
        "fields": [
            {"key": "drive_style", "label": "Drive", "type": "select", "value": "gsg", "options": ["gs", "gsg"]},
        ],
    },
}


def list_generators() -> list[dict[str, Any]]:
    """Return the available generators + their dialog field schemas."""

    return [{"name": name, "label": gen["label"], "fields": gen["fields"]} for name, gen in _GENERATORS.items()]


def _scene_of(result: Any):
    return result["scene"] if isinstance(result, dict) else result


def _validated_params(name: str, params: dict[str, Any] | None) -> dict[str, Any]:
    if name not in _GENERATORS:
        raise KeyError(name)
    supplied = params or {}
    if not isinstance(supplied, dict):
        raise ValueError("Generator parameters must be an object")

    fields = {field["key"]: field for field in _GENERATORS[name]["fields"]}
    unknown = set(supplied) - set(fields)
    if unknown:
        raise ValueError(f"Unknown generator parameter(s): {', '.join(sorted(unknown))}")

    validated: dict[str, Any] = {}
    for key, field in fields.items():
        value = supplied.get(key, field["value"])
        if field["type"] == "number":
            if isinstance(value, bool):
                raise ValueError(f"{key} must be a number")
            try:
                number = float(value)
            except (TypeError, ValueError) as error:
                raise ValueError(f"{key} must be a number") from error
            if not math.isfinite(number) or not field["min"] <= number <= field["max"]:
                raise ValueError(f"{key} must be between {field['min']} and {field['max']}")
            if isinstance(field["value"], int):
                if not number.is_integer():
                    raise ValueError(f"{key} must be a whole number")
                validated[key] = int(number)
            else:
                validated[key] = number
        elif field["type"] == "select":
            if value not in field["options"]:
                raise ValueError(f"{key} must be one of {', '.join(field['options'])}")
            validated[key] = value
        elif field["type"] == "checkbox":
            if not isinstance(value, bool):
                raise ValueError(f"{key} must be true or false")
            validated[key] = value
    return validated


def build(name: str, params: dict[str, Any] | None):
    """Build a fresh ``Scene`` for ``name`` from ``params`` (KeyError if unknown)."""

    params = _validated_params(name, params)
    from optodraw import (
        build_detector_readout_chain,
        build_microring_weight_mesh,
        build_modulator_drive_chain,
        build_mzm_coupler_mesh,
        build_ring_filter,
    )

    if name == "mzm_mesh":
        return _scene_of(
            build_mzm_coupler_mesh(
                modes=int(params.get("modes", 4)),
                layers=int(params.get("layers", 4)),
                drive_style=str(params.get("drive_style", "gsg")),
            )
        )
    if name == "microring_weight_mesh":
        return _scene_of(
            build_microring_weight_mesh(
                rows=int(params.get("rows", 2)),
                cols=int(params.get("cols", 2)),
                ring_count=int(params.get("ring_count", 4)),
                topology=str(params.get("topology", "rectangular")),
                with_heaters=bool(params.get("with_heaters", True)),
            )
        )
    if name == "ring_filter":
        return _scene_of(
            build_ring_filter(
                add_drop=bool(params.get("add_drop", True)),
                spacing_um=float(params.get("spacing_um", 12.0)),
            )
        )
    if name == "detector_readout_chain":
        return _scene_of(build_detector_readout_chain())
    if name == "modulator_drive_chain":
        return _scene_of(build_modulator_drive_chain(drive_style=str(params.get("drive_style", "gsg"))))
    raise KeyError(name)  # pragma: no cover - guarded above
