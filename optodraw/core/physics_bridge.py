"""Bridge physics traces to animation recipe hints (compiler foundation layer)."""

from __future__ import annotations

from typing import Any

from optodraw.core.guided import summarize_path, trace_guided_path
from optodraw.core.interferometer import trace_mzi_transfer, trace_mzm_transfer
from optodraw.core.resonator import is_resonator_component, trace_ring_resonance
from optodraw.schema import _assign_component_ids

_SKIP_HINT_TYPES = frozenset(
    {
        "Group",
        "Route",
        "WaveguideRoute",
        "FiberRoute",
        "Beam",
        "FocusingBeam",
        "Grid",
    }
)

_MMI_TYPES = frozenset(
    {
        "MMI1x2",
        "MMI1x3",
        "MMI1x4",
        "MMI2x2",
        "MMI2x2PowerSplitter",
    }
)

_GRATING_COUPLER_TYPES = frozenset(
    {
        "VerticalGratingCoupler",
        "FocusedApodizedGratingCoupler",
        "GratingCouplerArray",
        "EdgeCoupler",
    }
)


_MODULATOR_RESONATOR_TYPES = frozenset({"PNMicroringModulator", "RacetrackModulator"})
_PASSIVE_RESONATOR_TYPES = frozenset({"MicroringResonator", "RacetrackResonator"})


def _recipe_for_component_type(component_type: str) -> str | None:
    if component_type == "MZI":
        return "animate_interference"
    if component_type == "MZM":
        return "animate_mzm_mechanism"
    if component_type in _MODULATOR_RESONATOR_TYPES:
        return "animate_pn_modulation_phase_shift"
    if component_type in _PASSIVE_RESONATOR_TYPES:
        return "animate_resonance_scan"
    if component_type in _GRATING_COUPLER_TYPES:
        return "animate_grating_coupler_in_out"
    if component_type == "DirectionalCoupler":
        return "animate_directional_coupler_power_transfer"
    if component_type in _MMI_TYPES:
        return "animate_mmi_split_recombine"
    if component_type == "OnChipPhotodetector":
        return "animate_photodetector_absorption"
    if component_type == "Lens":
        return "animate_focus"
    if component_type in {"Prism", "Grating"}:
        return "animate_dispersion"
    return None


def _secondary_recipes(component_type: str) -> list[str]:
    recipes: list[str] = []
    if component_type == "MZM":
        recipes.append("animate_modulation")
    if component_type in _PASSIVE_RESONATOR_TYPES:
        recipes.append("animate_ring_coupling")
    if component_type in _MODULATOR_RESONATOR_TYPES:
        recipes.extend(["animate_resonance_scan", "animate_ring_coupling"])
    return recipes


def _interference_regime(through_power: float) -> str:
    if through_power >= 0.9:
        return "constructive"
    if through_power <= 0.1:
        return "destructive"
    return "partial"


def _hints_for_component(
    component: Any,
    *,
    wavelength_nm: float,
) -> dict[str, Any]:
    component_type = getattr(component, "component_type", component.__class__.__name__)
    hints: dict[str, Any] = {
        "component_type": component_type,
        "wavelength_nm": float(wavelength_nm),
    }

    if component_type == "MZI":
        trace = trace_mzi_transfer(component, wavelength_nm=wavelength_nm)
        hints.update(
            {
                "phase_bias_rad": trace["phase_bias_rad"],
                "arm_imbalance_um": trace["arm_imbalance_um"],
                "through_power": trace["through_power"],
                "drop_power": trace["drop_power"],
                "interference_regime": _interference_regime(trace["through_power"]),
                "phase_steps": 8,
            }
        )
        return hints

    if component_type == "MZM":
        trace = trace_mzm_transfer(component, drive_voltage=0.0, wavelength_nm=wavelength_nm)
        hints.update(
            {
                "drive_style": trace["drive_style"],
                "Vpi": trace["Vpi"],
                "phase_model": trace["phase_model"],
                "drive_voltage_start": 0.0,
                "drive_voltage_end": trace["Vpi"],
                "through_power": trace["through_power"],
            }
        )
        return hints

    if is_resonator_component(component):
        trace = trace_ring_resonance(component, wavelength_nm=wavelength_nm)
        span_nm = max(trace.get("fwhm_nm") or 0.2, 0.05) * 5.0
        hints.update(
            {
                "lambda0_nm": trace["lambda0_nm"],
                "Q": trace["Q"],
                "fwhm_nm": trace["fwhm_nm"],
                "fsr_nm": trace.get("fsr_nm"),
                "wavelength_start_nm": trace["lambda0_nm"] - span_nm,
                "wavelength_end_nm": trace["lambda0_nm"] + span_nm,
                "wavelength_steps": 10,
                "through_power": trace["through_power"],
                "drop_power": trace["cross_power"],
            }
        )
        if component_type in {"PNMicroringModulator", "RacetrackModulator"}:
            hints["bias_voltage_v"] = 0.0
            hints["tuning_efficiency_nm_per_v"] = 0.01
        return hints

    if component_type in _GRATING_COUPLER_TYPES:
        metadata = component.physics_metadata() if hasattr(component, "physics_metadata") else {}
        hints.update(
            {
                "coupling_angle_deg": metadata.get("coupling_angle_deg"),
                "tooth_pitch": metadata.get("tooth_pitch"),
                "efficiency_stub": metadata.get("coupling_efficiency", 0.35),
            }
        )
        return hints

    if component_type == "DirectionalCoupler":
        metadata = component.physics_metadata() if hasattr(component, "physics_metadata") else {}
        hints.update(
            {
                "coupling_length": metadata.get("coupling_length"),
                "coupling_ratio": metadata.get("coupling_ratio", 0.5),
            }
        )
        return hints

    if component_type in _MMI_TYPES:
        metadata = component.physics_metadata() if hasattr(component, "physics_metadata") else {}
        default_outputs = {"MMI1x3": 3, "MMI1x4": 4}.get(component_type, 2)
        output_count = int(metadata.get("output_port_count") or default_outputs)
        if output_count < 1:
            raise ValueError("output_port_count must be positive")
        hints.update(
            {
                "split_ratio": (
                    metadata.get("split_ratio", 0.5)
                    if output_count == 2
                    else 1.0 / output_count
                ),
                "split_ratios": metadata.get("split_ratios"),
                "input_port_count": metadata.get("input_port_count"),
                "output_port_count": output_count,
            }
        )
        return hints

    if component_type == "OnChipPhotodetector":
        metadata = component.physics_metadata() if hasattr(component, "physics_metadata") else {}
        hints.update(
            {
                "responsivity_a_per_w": metadata.get("responsivity_a_per_w", 0.8),
                "bandwidth_ghz": metadata.get("bandwidth_ghz"),
            }
        )
        return hints

    if component_type == "Lens":
        hints["focal_length"] = getattr(component, "focal_length", None)
        return hints

    if component_type in {"Prism", "Grating"}:
        hints["material_stub"] = getattr(component, "material", "BK7")
        return hints

    return hints


def physics_trace_to_timeline_hints(
    scene,
    *,
    wavelength_nm: float = 1550.0,
    include_guided_paths: bool = True,
) -> dict[str, dict[str, Any]]:
    """Map scene component ids to suggested animation recipes and parameter hints.

    This is a bridge layer only: it does not build an ``AnimationTimeline``.
    Recipe names match ``optodraw.animation_recipes`` entry points.
    """

    component_ids = _assign_component_ids(scene)
    hints: dict[str, dict[str, Any]] = {}

    guided_components = [
        node
        for node in scene.walk()
        if getattr(node, "component_type", "") not in _SKIP_HINT_TYPES
    ]
    guided_summary = None
    if include_guided_paths and guided_components:
        guided_summary = summarize_path(
            trace_guided_path(guided_components, wavelength_nm=wavelength_nm)
        )

    for node in scene.walk():
        component_type = getattr(node, "component_type", node.__class__.__name__)
        if component_type in _SKIP_HINT_TYPES:
            continue

        recipe = _recipe_for_component_type(component_type)
        if recipe is None:
            continue

        component_id = component_ids.get(id(node), component_type.lower())
        entry: dict[str, Any] = {
            "recipe": recipe,
            "hints": _hints_for_component(node, wavelength_nm=wavelength_nm),
        }
        secondary = _secondary_recipes(component_type)
        if secondary:
            entry["alternate_recipes"] = secondary
        if guided_summary is not None:
            entry["hints"]["guided_path_summary"] = guided_summary
        hints[component_id] = entry

    return hints


__all__ = ["physics_trace_to_timeline_hints"]
