"""Animation recipes for the GUI **Animate** feature → GIF export.

Maps a selected component to the applicable ``animate_*`` recipe(s), builds an
``AnimationTimeline`` for the current scene, and renders an animated GIF (bytes).
Needs ``optodraw[gif]`` (pillow). No animation logic here beyond calling the library
recipes — keeps the API a thin adapter.
"""

from __future__ import annotations

import math
import pathlib
import tempfile
from typing import Any


def _integer_param(params: dict[str, Any], key: str, default: int, minimum: int, maximum: int) -> int:
    value = params.get(key, default)
    if isinstance(value, bool):
        raise ValueError(f"{key} must be a whole number between {minimum} and {maximum}")
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{key} must be a whole number between {minimum} and {maximum}") from error
    if not math.isfinite(number) or not number.is_integer() or not minimum <= number <= maximum:
        raise ValueError(f"{key} must be a whole number between {minimum} and {maximum}")
    return int(number)


def _params_dict(params: dict[str, Any] | None) -> dict[str, Any]:
    if params is None:
        return {}
    if not isinstance(params, dict):
        raise ValueError("Animation parameters must be an object")
    return params


def _catalog() -> dict[str, dict[str, Any]]:
    """recipe name → {label, fn, types, step_key, step_default}."""
    from optodraw import (
        animate_directional_coupler_power_transfer,
        animate_dispersion,
        animate_fiber_alignment,
        animate_focus,
        animate_grating_coupler_in_out,
        animate_mmi_split_recombine,
        animate_modulation,
        animate_mzm_mechanism,
        animate_photodetector_absorption,
        animate_pn_modulation_phase_shift,
        animate_resonance_scan,
        animate_ring_coupling,
    )

    return {
        "resonance_scan": {"label": "Resonance scan", "fn": animate_resonance_scan,
                           "types": {"MicroringResonator", "PNMicroringModulator", "RacetrackResonator", "RacetrackModulator"},
                           "step_key": "wavelength_steps", "step_default": 10},
        "ring_coupling": {"label": "Ring coupling buildup", "fn": animate_ring_coupling,
                          "types": {"MicroringResonator", "PNMicroringModulator", "RacetrackResonator", "RacetrackModulator"},
                          "step_key": "coupling_steps", "step_default": 6},
        "pn_phase_shift": {"label": "PN phase shift", "fn": animate_pn_modulation_phase_shift,
                           "types": {"PNMicroringModulator", "RacetrackModulator"},
                           "step_key": "voltage_steps", "step_default": 8},
        "modulation": {"label": "MZM modulation", "fn": animate_modulation,
                       "types": {"MZM"}, "step_key": "voltage_steps", "step_default": 8},
        "mzm_mechanism": {"label": "MZM mechanism", "fn": animate_mzm_mechanism,
                          "types": {"MZM"}, "step_key": "phase_steps", "step_default": 6},
        "mmi_split": {"label": "MMI split / recombine", "fn": animate_mmi_split_recombine,
                      "types": {"MMI1x2", "MMI1x3", "MMI1x4", "MMI2x2", "MMI2x2PowerSplitter"},
                      "step_key": "steps", "step_default": 6},
        "coupler_power": {"label": "Coupler power transfer", "fn": animate_directional_coupler_power_transfer,
                          "types": {"DirectionalCoupler"}, "step_key": "length_steps", "step_default": 8},
        "grating_in_out": {"label": "Grating coupler in/out", "fn": animate_grating_coupler_in_out,
                           "types": {"VerticalGratingCoupler", "FocusedApodizedGratingCoupler"},
                           "step_key": "steps", "step_default": 8},
        "pd_absorption": {"label": "Photodetector absorption", "fn": animate_photodetector_absorption,
                          "types": {"OnChipPhotodetector"}, "step_key": None, "step_default": 0},
        "focus": {"label": "Lens focusing", "fn": animate_focus,
                  "types": {"Lens"}, "step_key": None, "step_default": 0},
        "dispersion": {"label": "Dispersion (wavelength fan)", "fn": animate_dispersion,
                       "types": {"Prism", "Grating"}, "step_key": "wavelength_steps", "step_default": 8},
        "fiber_alignment": {"label": "Fiber alignment", "fn": animate_fiber_alignment,
                            "types": {"EdgeCoupler", "VerticalGratingCoupler", "FocusedApodizedGratingCoupler", "GratingCouplerArray"},
                            "step_key": "alignment_steps", "step_default": 8},
    }


def recipes_for(component: Any) -> list[dict[str, str]]:
    """Applicable recipes for ``component`` (by component_type)."""

    ctype = getattr(component, "component_type", "") or ""
    return [{"name": name, "label": spec["label"]} for name, spec in _catalog().items() if ctype in spec["types"]]


def render_gif_bytes(scene: Any, component: Any, recipe: str, params: dict[str, Any] | None) -> bytes:
    """Build the recipe's timeline and render it to an animated GIF (bytes)."""

    params = _params_dict(params)
    catalog = _catalog()
    if recipe not in catalog:
        raise KeyError(recipe)
    spec = catalog[recipe]
    component_type = getattr(component, "component_type", "")
    if component_type not in spec["types"]:
        raise ValueError(f"{recipe} is not available for {component_type or 'this component'}")
    kwargs: dict[str, Any] = {}
    if spec["step_key"]:
        kwargs[spec["step_key"]] = _integer_param(params, "steps", spec["step_default"], 2, 120)
    fps = _integer_param(params, "fps", 6, 1, 60)
    timeline = spec["fn"](scene, component, **kwargs)
    with tempfile.TemporaryDirectory() as tmp:
        path = pathlib.Path(tmp) / "animation.gif"
        timeline.render_gif(path.as_posix(), fps=fps)
        return path.read_bytes()


_ROUTE_TYPES = {"WaveguideRoute", "Route", "FiberRoute"}


def render_flow_gif(scene: Any, params: dict[str, Any] | None) -> bytes:
    """Scene-level **light-flow** animation: a pulse travels through every route /
    beam in the scene (visible motion), unlike the per-component highlight recipes.
    """

    params = _params_dict(params)
    fps = _integer_param(params, "fps", 8, 1, 60)
    steps = _integer_param(params, "steps", 14, 4, 120)
    timeline = scene.timeline()
    found = False
    for node in scene.walk():
        ctype = getattr(node, "component_type", "")
        if ctype == "Beam" and not getattr(node, "envelope", False):
            timeline.trace(node, steps=steps)
            found = True
        elif ctype in _ROUTE_TYPES and getattr(node, "kind", "") not in {"electrical", "thermal", "rf", "dc", "metal"}:
            timeline.wave_travel(node, steps=steps, trail=True)
            found = True
    if not found:
        raise ValueError("scene has no routes or beams — connect components (Links / Route) first")
    with tempfile.TemporaryDirectory() as tmp:
        path = pathlib.Path(tmp) / "flow.gif"
        timeline.render_gif(path.as_posix(), fps=fps)
        return path.read_bytes()
