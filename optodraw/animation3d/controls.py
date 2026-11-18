"""The light settings of one part: what the editor's "Light" section shows, and how a value becomes an engine
parameter. The editor holds no physics. A heater's power (mW) is ``heater:<name>``; a modulator's drive (V) is
``drive:<sid>``; a ring's tuning is in linewidths, and its ``phase:<name>`` is the ring's resonance phase plus the
tuning times the ring's linewidth (both from the engine's ring model, ``solver.resonance_phases`` and
``solver.ring_linewidths``). A value at its default (0) is not stored."""

from __future__ import annotations

import math
from typing import Any

from optodraw.animation_engine.graph import build_graph
from optodraw.animation_engine.solver import resonance_phases, ring_linewidths

from .effects import drive_keys
from .inputs import default_inputs, input_wavelength

HEATER_MAX_MW = 40.0            # the slider range of a heater; the engine takes any power
TUNING_MAX = 2.0                # a ring is tuned up to this many linewidths either side of its resonance


def _label(what: str, tail: str) -> str:
    """``Heater power`` for a part's own heater, ``Ring 2 heater power`` for the heater of its ring 2."""

    if tail.startswith("ring") and tail[4:].isdigit():
        return f"Ring {tail[4:]} {what[0].lower() + what[1:]}"
    return f"{what} {tail}".strip() if tail else what


def light_controls(scene: Any, sid: str, *, params: dict | None = None, inputs: list | None = None) -> list[dict[str, Any]]:
    """The controls of part ``sid``, in the order the inspector shows them: per ring its tuning then its heater, then a
    modulator's drive. Each is ``key`` (what the API takes), ``param`` (the engine key it sets), ``kind`` (``tuning``,
    ``heater`` or ``drive``), ``label``, ``unit``, ``min``, ``max``, ``step``, ``value`` and ``default``. A ring has
    a tuning control only when the scene has light to tune it to. A part with no heater has no heater control."""

    given = dict(params or {})
    graph = build_graph(scene)
    part = graph.parts.get(sid)
    if part is None:
        return []
    if inputs is None:
        inputs, _ = default_inputs(scene, graph)
    wavelength = input_wavelength(graph, list(inputs), given)
    rings = resonance_phases(part, sid, wavelength, given) if wavelength is not None else {}
    widths = ring_linewidths(part, sid, wavelength, given) if wavelength is not None else {}
    heaters = {name.split(":", 1)[1]: top for name, top in drive_keys(part, sid) if name.startswith("heater:")}
    drives = {name: top for name, top in drive_keys(part, sid) if name.startswith("drive:")}
    controls: list[dict[str, Any]] = []
    names = list(dict.fromkeys([k.split(":", 1)[1] for k in rings] + list(heaters)))
    for name in names:
        tail = name[len(sid) + 1:] if name.startswith(sid + ":") else ""
        if f"phase:{name}" in rings:
            key = f"phase:{name}"
            stored = given.get(key)
            tuning = 0.0 if stored is None else (float(stored) - rings[key]) / widths[key]
            controls.append({"key": f"tuning:{name}", "param": key, "kind": "tuning", "label": _label("Tuning", tail),
                             "unit": "linewidths", "min": -TUNING_MAX, "max": TUNING_MAX, "step": 0.05,
                             "value": tuning, "default": 0.0, "resonance_rad": rings[key], "linewidth_rad": widths[key]})
        if name in heaters:
            controls.append({"key": f"heater:{name}", "param": f"heater:{name}", "kind": "heater",
                             "label": _label("Heater power", tail), "unit": "mW", "min": 0.0, "max": HEATER_MAX_MW,
                             "step": 0.5, "value": float(given.get(f"heater:{name}", 0.0)), "default": 0.0})
    for key, top in drives.items():
        controls.append({"key": key, "param": key, "kind": "drive", "label": "Modulator drive", "unit": "V", "min": 0.0,
                         "max": float(top), "step": round(float(top) / 100.0, 4), "value": float(given.get(key, 0.0)),
                         "default": 0.0})
    return controls


def light_changes(scene: Any, sid: str, values: dict[str, Any], *, params: dict | None = None,
                  inputs: list | None = None) -> dict[str, float | None]:
    """``{engine key: value}`` for ``values`` (``{control key: value in the control's unit}``) set on part ``sid``; a
    value at its default maps to ``None`` (remove the key). Raises ``ValueError`` for a key the part has no control
    for, and for a value that is not a number in the control's range."""

    controls = {c["key"]: c for c in light_controls(scene, sid, params=params, inputs=inputs)}
    out: dict[str, float | None] = {}
    for key, value in values.items():
        control = controls.get(key)
        if control is None:
            raise ValueError(f"{sid}: no light control {key}")
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f"{key} must be a number")
        if not control["min"] <= value <= control["max"]:
            raise ValueError(f"{key} must be between {control['min']:g} and {control['max']:g} {control['unit']}")
        if value == control["default"]:
            out[control["param"]] = None
        elif control["kind"] == "tuning":
            out[control["param"]] = control["resonance_rad"] + float(value) * control["linewidth_rad"]
        else:
            out[control["param"]] = float(value)
    return out
