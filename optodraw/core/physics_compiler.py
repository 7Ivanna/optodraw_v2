"""Compile physics trace hints into concrete animation timelines."""

from __future__ import annotations

from typing import Any, Callable

from optodraw.animation import AnimationTimeline
from optodraw.animation_recipes import (
    animate_directional_coupler_power_transfer,
    animate_dispersion,
    animate_focus,
    animate_grating_coupler_in_out,
    animate_interference,
    animate_mmi_split_recombine,
    animate_mzm_mechanism,
    animate_photodetector_absorption,
    animate_pn_modulation_phase_shift,
    animate_resonance_scan,
)
from optodraw.core.beam import Beam
from optodraw.core.physics_bridge import physics_trace_to_timeline_hints
from optodraw.core.routing import FiberRoute, Route, WaveguideRoute
from optodraw.schema import _assign_component_ids

_PATH_TYPES = frozenset({"Beam", "Route", "WaveguideRoute", "FiberRoute"})

_SKIP_HINT_KEYS = frozenset(
    {
        "component_type",
        "guided_path_summary",
        "interference_regime",
        "through_power",
        "drop_power",
        "drive_style",
        "phase_model",
        "drive_voltage_start",
        "drive_voltage_end",
        "phase_bias_rad",
        "arm_imbalance_um",
        "Q",
        "fwhm_nm",
        "fsr_nm",
        "lambda0_nm",
        "wavelength_start_nm",
        "wavelength_end_nm",
        "coupling_angle_deg",
        "tooth_pitch",
        "coupling_length",
        "coupling_ratio",
        "split_ratio",
        "input_port_count",
        "output_port_count",
        "material_stub",
        "focal_length",
        "bandwidth_ghz",
        "bias_voltage_v",
        "tuning_efficiency_nm_per_v",
    }
)


def _is_path(component: Any) -> bool:
    if isinstance(component, (Beam, Route, WaveguideRoute, FiberRoute)):
        return True
    component_type = getattr(component, "component_type", component.__class__.__name__)
    return component_type in _PATH_TYPES


def _components_by_id(scene) -> dict[str, Any]:
    refs = _assign_component_ids(scene)
    by_id: dict[str, Any] = {}
    for node in scene.walk():
        component_id = refs.get(id(node))
        if component_id is not None:
            by_id[component_id] = node
    return by_id


def _routes_for_component(scene, component) -> list[Route]:
    component_key = id(component)
    routes: list[Route] = []
    for candidate in scene.walk():
        if not _is_path(candidate) or isinstance(candidate, Beam):
            continue
        start = getattr(candidate, "start_component", None)
        end = getattr(candidate, "end_component", None)
        if (start is not None and id(start) == component_key) or (
            end is not None and id(end) == component_key
        ):
            routes.append(candidate)
    return routes


def _first_route(scene) -> Route | Beam | None:
    for candidate in scene.walk():
        if _is_path(candidate):
            return candidate
    return None


def _float_hint(hints: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = hints.get(key)
        if value is not None:
            return float(value)
    return None


def _recipe_kwargs(hints: dict[str, Any], *, allowed: set[str]) -> dict[str, Any]:
    kwargs: dict[str, Any] = {}
    for key, value in hints.items():
        if key in _SKIP_HINT_KEYS or key not in allowed:
            continue
        kwargs[key] = value
    return kwargs


def _dispatch_interference(scene, component, hints: dict[str, Any]) -> AnimationTimeline:
    routes = _routes_for_component(scene, component)
    if len(routes) < 2:
        tl = scene.timeline()
        tl.show(component, caption="MZI")
        for route in routes:
            tl.trace(route, caption="Connected optical path")
        tl.pause(caption="Connect two arm paths to animate interference")
        return tl
    arm1, arm2 = routes[:2]
    kwargs = _recipe_kwargs(hints, allowed={"phase_steps", "caption"})
    return animate_interference(scene, arm1, arm2, component, **kwargs)


def _dispatch_resonance_scan(scene, component, hints: dict[str, Any]) -> AnimationTimeline:
    kwargs = _recipe_kwargs(hints, allowed={"wavelength_steps", "caption"})
    wavelength_nm = _float_hint(hints, "wavelength_nm", "lambda0_nm")
    if wavelength_nm is not None:
        kwargs["wavelength_nm"] = wavelength_nm
    return animate_resonance_scan(scene, component, **kwargs)


def _dispatch_mzm_mechanism(scene, component, hints: dict[str, Any]) -> AnimationTimeline:
    kwargs = _recipe_kwargs(hints, allowed={"phase_steps", "caption"})
    vpi = _float_hint(hints, "Vpi")
    if vpi is not None:
        kwargs["Vpi"] = vpi
    wavelength_nm = _float_hint(hints, "wavelength_nm")
    if wavelength_nm is not None:
        kwargs["wavelength_nm"] = wavelength_nm
    return animate_mzm_mechanism(scene, component, **kwargs)


def _dispatch_pn_modulation(scene, component, hints: dict[str, Any]) -> AnimationTimeline:
    kwargs = _recipe_kwargs(hints, allowed={"voltage_steps", "caption"})
    voltage_max = _float_hint(hints, "Vpi", "drive_voltage_end")
    if voltage_max is not None:
        kwargs["voltage_max"] = voltage_max
    wavelength_nm = _float_hint(hints, "wavelength_nm")
    if wavelength_nm is not None:
        kwargs["wavelength_nm"] = wavelength_nm
    return animate_pn_modulation_phase_shift(scene, component, **kwargs)


def _dispatch_grating_coupler(scene, component, hints: dict[str, Any]) -> AnimationTimeline:
    kwargs = _recipe_kwargs(hints, allowed={"caption", "steps", "pulse_width", "direction"})
    efficiency = _float_hint(hints, "efficiency_stub", "coupling_efficiency")
    if efficiency is not None:
        kwargs["coupling_efficiency"] = efficiency
    wavelength_nm = _float_hint(hints, "wavelength_nm")
    if wavelength_nm is not None:
        kwargs["wavelength_nm"] = wavelength_nm
    return animate_grating_coupler_in_out(scene, component, **kwargs)


def _dispatch_directional_coupler(scene, component, hints: dict[str, Any]) -> AnimationTimeline:
    kwargs = _recipe_kwargs(hints, allowed={"caption", "length_steps", "pulse_width"})
    crossover = _float_hint(hints, "full_crossover_length")
    if crossover is None:
        coupling_length = _float_hint(hints, "coupling_length")
        if coupling_length is not None:
            crossover = 2.0 * coupling_length
    if crossover is not None:
        kwargs["full_crossover_length"] = crossover
    wavelength_nm = _float_hint(hints, "wavelength_nm")
    if wavelength_nm is not None:
        kwargs["wavelength_nm"] = wavelength_nm
    return animate_directional_coupler_power_transfer(scene, component, **kwargs)


def _dispatch_mmi(scene, component, hints: dict[str, Any]) -> AnimationTimeline:
    kwargs = _recipe_kwargs(hints, allowed={"caption", "steps", "pulse_width", "imbalance_db"})
    wavelength_nm = _float_hint(hints, "wavelength_nm")
    if wavelength_nm is not None:
        kwargs["wavelength_nm"] = wavelength_nm
    return animate_mmi_split_recombine(scene, component, **kwargs)


def _dispatch_photodetector(scene, component, hints: dict[str, Any]) -> AnimationTimeline:
    kwargs = _recipe_kwargs(hints, allowed={"caption", "steps", "pulse_width", "absorption_efficiency"})
    responsivity = _float_hint(hints, "responsivity_a_per_w")
    if responsivity is not None:
        kwargs["responsivity_a_per_w"] = responsivity
    wavelength_nm = _float_hint(hints, "wavelength_nm")
    if wavelength_nm is not None:
        kwargs["wavelength_nm"] = wavelength_nm
    return animate_photodetector_absorption(scene, photodetector=component, **kwargs)


def _dispatch_focus(scene, component, hints: dict[str, Any]) -> AnimationTimeline:
    kwargs = _recipe_kwargs(hints, allowed={"caption", "exit_length"})
    return animate_focus(scene, component, **kwargs)


def _dispatch_dispersion(scene, component, hints: dict[str, Any]) -> AnimationTimeline:
    kwargs = _recipe_kwargs(hints, allowed={"caption", "wavelength_steps", "wavelength_span_nm"})
    center = _float_hint(hints, "wavelength_nm", "center_wavelength_nm")
    if center is not None:
        kwargs["center_wavelength_nm"] = center
    return animate_dispersion(scene, component, **kwargs)


_RECIPE_DISPATCH: dict[str, Callable[[Any, Any, dict[str, Any]], AnimationTimeline]] = {
    "animate_interference": _dispatch_interference,
    "animate_resonance_scan": _dispatch_resonance_scan,
    "animate_mzm_mechanism": _dispatch_mzm_mechanism,
    "animate_pn_modulation_phase_shift": _dispatch_pn_modulation,
    "animate_grating_coupler_in_out": _dispatch_grating_coupler,
    "animate_directional_coupler_power_transfer": _dispatch_directional_coupler,
    "animate_mmi_split_recombine": _dispatch_mmi,
    "animate_photodetector_absorption": _dispatch_photodetector,
    "animate_focus": _dispatch_focus,
    "animate_dispersion": _dispatch_dispersion,
}


def _fallback_wave_travel(
    tl: AnimationTimeline,
    *,
    fps: int,
    duration_s: float,
    wavelength_nm: float,
) -> None:
    route = _first_route(tl.scene)
    if route is None:
        tl.pause(duration_s, caption="No physics-driven animation hints found")
        return

    steps = max(int(fps * duration_s / 4.0), 4)
    tl.wave_travel(
        route,
        caption="Guided-mode propagation (physics compiler fallback)",
        steps=steps,
        dwell=max(duration_s / max(steps, 1), 0.1),
        wavelength_nm=wavelength_nm,
        opacity_envelope="gaussian",
    )


def compile_physics_animation(
    scene,
    *,
    fps: int = 30,
    duration_s: float = 4.0,
    wavelength_nm: float = 1550.0,
    include_guided_paths: bool = True,
) -> AnimationTimeline:
    """Compile physics trace hints into a merged :class:`AnimationTimeline`.

    Uses :func:`~optodraw.core.physics_bridge.physics_trace_to_timeline_hints`
    to choose ``animate_*`` recipes, merges parameter hints into each call, and
    falls back to a generic ``wave_travel`` on the first route when no hints
    are available.
    """

    tl = scene.timeline()
    tl.fps = int(fps)
    tl.duration_s = float(duration_s)

    hints_map = physics_trace_to_timeline_hints(
        scene,
        wavelength_nm=wavelength_nm,
        include_guided_paths=include_guided_paths,
    )
    if not hints_map:
        _fallback_wave_travel(
            tl,
            fps=tl.fps,
            duration_s=tl.duration_s,
            wavelength_nm=wavelength_nm,
        )
        return tl

    components = _components_by_id(scene)
    for component_id, entry in hints_map.items():
        component = components.get(component_id)
        if component is None:
            continue
        recipe_name = entry.get("recipe")
        dispatch = _RECIPE_DISPATCH.get(recipe_name or "")
        if dispatch is None:
            continue
        partial = dispatch(scene, component, dict(entry.get("hints") or {}))
        tl._steps.extend(partial._steps)

    if not tl._steps:
        _fallback_wave_travel(
            tl,
            fps=tl.fps,
            duration_s=tl.duration_s,
            wavelength_nm=wavelength_nm,
        )

    return tl


__all__ = ["compile_physics_animation"]
