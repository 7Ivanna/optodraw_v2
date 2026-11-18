"""On-chip guided-mode propagation stubs."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Iterable

from optodraw.core.physics import grating_coupler_angle_deg
from optodraw.core.transform import Vec3

SILICON_STRIP_NEFF_STUB = 2.4
SILICON_STRIP_NG_STUB = 4.2
# Speed of light in um/ps: 299_792_458 m/s * 1e6 um/m / 1e12 ps/s.
_C = 299.792458
_COUPLING_ANGLE_TOLERANCE_DEG = 5.0


@dataclass(frozen=True)
class GuidedModeTraceResult:
    """Lightweight guided-mode trace along routed on-chip paths."""

    path_length_um: float
    effective_index: float
    phase_rad: float
    loss_db: float = 0.0
    group_index: float | None = None
    group_delay_ps: float | None = None
    loss_budget_db: float | None = None
    loss_budget_exceeded: bool = False
    neff_min: float | None = None
    neff_max: float | None = None
    segment_count: int = 0
    wavelength_nm: float | None = None

    def to_dict(self) -> dict[str, float | bool | int | None]:
        return {
            "path_length_um": self.path_length_um,
            "effective_index": self.effective_index,
            "phase_rad": self.phase_rad,
            "wavelength_nm": self.wavelength_nm,
            "loss_db": self.loss_db,
            "group_index": self.group_index,
            "group_delay_ps": self.group_delay_ps,
            "loss_budget_db": self.loss_budget_db,
            "loss_budget_exceeded": self.loss_budget_exceeded,
            "neff_min": self.neff_min,
            "neff_max": self.neff_max,
            "segment_count": self.segment_count,
        }


def _polyline_length(points: Iterable[Vec3]) -> float:
    points_list = list(points)
    total = 0.0
    for index in range(1, len(points_list)):
        total += (points_list[index] - points_list[index - 1]).length()
    return total


def _resolve_effective_index(component: Any, explicit: float | None) -> float | None:
    if explicit is not None:
        return float(explicit)
    if hasattr(component, "effective_index"):
        value = getattr(component, "effective_index")
        if value is not None:
            return float(value)
    if hasattr(component, "physics_metadata"):
        metadata = component.physics_metadata()
        value = metadata.get("effective_index")
        if value is not None:
            return float(value)
    return None


def _resolve_group_index(component: Any, explicit: float | None) -> float | None:
    if explicit is not None:
        return float(explicit)
    if hasattr(component, "group_index"):
        value = getattr(component, "group_index")
        if value is not None:
            return float(value)
    if hasattr(component, "physics_metadata"):
        metadata = component.physics_metadata()
        value = metadata.get("group_index")
        if value is not None:
            return float(value)
    return None


def _segment_loss_db(
    component: Any,
    segment_length_um: float,
    *,
    loss_db_per_um: float,
) -> float:
    if hasattr(component, "physics_metadata"):
        metadata = component.physics_metadata()
        segment_loss = metadata.get("loss_db")
        if segment_loss is not None:
            return float(segment_loss)
        per_um = metadata.get("loss_db_per_um")
        if per_um is not None and segment_length_um > 0:
            return float(per_um) * segment_length_um
    component_loss = getattr(component, "loss_db", None)
    if component_loss is not None:
        return float(component_loss)
    if segment_length_um > 0 and loss_db_per_um > 0:
        return float(loss_db_per_um) * segment_length_um
    return 0.0


def _group_delay_ps(group_index: float, path_length_um: float) -> float:
    if path_length_um <= 0:
        return 0.0
    return group_index * path_length_um / _C


def _component_path_length(component: Any) -> float:
    component_type = getattr(component, "component_type", component.__class__.__name__)

    if component_type in {"Route", "WaveguideRoute", "FiberRoute"}:
        if hasattr(component, "resolve_points"):
            points = component.resolve_points()
            return sum(math.dist(first[:3], second[:3]) for first, second in zip(points, points[1:]))
        transform = component.world_transform
        world_points = [transform.apply_to_point(point) for point in component.points]
        return _polyline_length(world_points)

    if component_type == "Waveguide":
        return float(getattr(component, "length", 0.0))

    if hasattr(component, "physics_metadata"):
        metadata = component.physics_metadata()
        length = metadata.get("length")
        if length is not None:
            return float(length)

    length = getattr(component, "length", None)
    if length is not None:
        return float(length)
    return 0.0


def trace_guided_mode(
    start_port,
    route_or_waveguide,
    *,
    wavelength_nm: float = 1550.0,
    effective_index: float | None = None,
    loss_db: float = 0.0,
) -> GuidedModeTraceResult:
    """Trace a single guided segment between a port and a route or waveguide."""

    del start_port  # reserved for future port-aware routing hooks
    return trace_guided_path(
        (route_or_waveguide,),
        wavelength_nm=wavelength_nm,
        effective_index=effective_index,
        loss_db=loss_db,
    )


def trace_guided_path(
    components_or_route: Iterable,
    *,
    wavelength_nm: float = 1550.0,
    effective_index: float | None = None,
    group_index: float | None = None,
    loss_db: float = 0.0,
    loss_db_per_um: float = 0.0,
    loss_budget_db: float | None = None,
) -> GuidedModeTraceResult:
    """Accumulate guided-mode path length over waveguides and routed interconnects.

    When ``loss_budget_db`` is set, propagation loss from ``loss_db_per_um`` and
    per-component ``physics_metadata`` entries is accumulated and compared to the
    budget. ``group_index`` enables a stub group-delay estimate alongside phase.
    """

    path_length_um = 0.0
    accumulated_loss_db = float(loss_db)
    neff_values: list[float] = []
    ng = group_index
    weighted_neff = 0.0
    weighted_ng = 0.0
    segment_count = 0
    wavelength_um = float(wavelength_nm) / 1000.0
    if not math.isfinite(wavelength_um) or wavelength_um <= 0:
        raise ValueError("wavelength_nm must be positive and finite")
    phase_rad = 0.0
    delay_ps = 0.0

    for component in components_or_route:
        segment_length = _component_path_length(component)
        if not math.isfinite(segment_length) or segment_length < 0:
            raise ValueError("guided segment length must be non-negative and finite")
        if segment_length == 0:
            continue
        segment_count += 1
        path_length_um += segment_length
        accumulated_loss_db += _segment_loss_db(
            component,
            segment_length,
            loss_db_per_um=loss_db_per_um,
        )
        component_neff = _resolve_effective_index(component, None)
        if component_neff is not None:
            neff_values.append(component_neff)
        if ng is None:
            ng = _resolve_group_index(component, None)
        # Accumulate per segment so reordering segments cannot change the totals.
        seg_neff = _resolve_effective_index(component, effective_index)
        seg_ng = _resolve_group_index(component, group_index)
        actual_neff = seg_neff if seg_neff is not None else SILICON_STRIP_NEFF_STUB
        actual_ng = seg_ng if seg_ng is not None else SILICON_STRIP_NG_STUB
        if not math.isfinite(actual_neff) or actual_neff <= 0:
            raise ValueError("effective_index must be positive and finite")
        if not math.isfinite(actual_ng) or actual_ng <= 0:
            raise ValueError("group_index must be positive and finite")
        weighted_neff += actual_neff * segment_length
        weighted_ng += actual_ng * segment_length
        phase_rad += 2.0 * math.pi * actual_neff * segment_length / wavelength_um
        delay_ps += actual_ng * segment_length / _C

    resolved_neff = weighted_neff / path_length_um if path_length_um > 0 else (effective_index if effective_index is not None else SILICON_STRIP_NEFF_STUB)
    resolved_ng = weighted_ng / path_length_um if path_length_um > 0 else (group_index if group_index is not None else SILICON_STRIP_NG_STUB)
    budget_exceeded = (
        loss_budget_db is not None and accumulated_loss_db > float(loss_budget_db)
    )
    return GuidedModeTraceResult(
        path_length_um=path_length_um,
        effective_index=resolved_neff,
        phase_rad=phase_rad,
        wavelength_nm=float(wavelength_nm),
        loss_db=accumulated_loss_db,
        group_index=resolved_ng if group_index is not None or ng is not None else None,
        group_delay_ps=delay_ps if (group_index is not None or ng is not None) else None,
        loss_budget_db=loss_budget_db,
        loss_budget_exceeded=budget_exceeded,
        neff_min=min(neff_values) if neff_values else None,
        neff_max=max(neff_values) if neff_values else None,
        segment_count=segment_count,
    )


def summarize_path(
    trace_or_components: GuidedModeTraceResult | Iterable,
    *,
    wavelength_nm: float = 1550.0,
    effective_index: float | None = None,
    group_index: float | None = None,
    loss_db: float = 0.0,
    loss_db_per_um: float = 0.0,
    loss_budget_db: float | None = None,
) -> dict[str, float | bool | int | None]:
    """Summarize guided-path length, loss, and effective-index statistics."""

    if isinstance(trace_or_components, GuidedModeTraceResult):
        trace = trace_or_components
    else:
        trace = trace_guided_path(
            trace_or_components,
            wavelength_nm=wavelength_nm,
            effective_index=effective_index,
            group_index=group_index,
            loss_db=loss_db,
            loss_db_per_um=loss_db_per_um,
            loss_budget_db=loss_budget_db,
        )

    neff_spread = None
    if trace.neff_min is not None and trace.neff_max is not None:
        neff_spread = trace.neff_max - trace.neff_min

    return {
        "path_length_um": trace.path_length_um,
        "loss_db": trace.loss_db,
        "effective_index": trace.effective_index,
        "effective_index_min": trace.neff_min,
        "effective_index_max": trace.neff_max,
        "effective_index_spread": neff_spread,
        "group_index": trace.group_index,
        "group_delay_ps": trace.group_delay_ps,
        "phase_rad": trace.phase_rad,
        "segment_count": trace.segment_count,
        "loss_budget_db": trace.loss_budget_db,
        "loss_budget_exceeded": trace.loss_budget_exceeded,
        "wavelength_nm": trace.wavelength_nm if trace.wavelength_nm is not None else float(wavelength_nm),
    }


def validate_coupler_transition(
    gc,
    *,
    wavelength_nm: float = 1550.0,
    fiber_port_or_wavelength: float | None = None,
) -> list[str]:
    """Return warnings when grating coupler angle metadata disagrees with the pitch stub."""

    if fiber_port_or_wavelength is not None and fiber_port_or_wavelength > 100.0:
        wavelength_nm = float(fiber_port_or_wavelength)

    metadata = gc.physics_metadata() if hasattr(gc, "physics_metadata") else {}
    pitch = metadata.get("tooth_pitch") or getattr(gc, "tooth_pitch", None)
    declared_angle = metadata.get("coupling_angle_deg")
    if declared_angle is None:
        declared_angle = getattr(gc, "coupling_angle_deg", None)

    if pitch is None or float(pitch) <= 0:
        return ["Grating coupler pitch is missing; coupling-angle validation skipped."]

    # Phase-match the GUIDED mode (n_clad·sinθ = n_eff − λ/Λ) — the free-space
    # grating equation (sinθ = λ/Λ) mislabelled every real coupler pitch as
    # evanescent because λ/Λ > 1 by design for sub-wavelength-ish pitches.
    neff = metadata.get("neff") or SILICON_STRIP_NEFF_STUB
    expected = grating_coupler_angle_deg(float(pitch), wavelength_nm, neff=float(neff))
    if expected is None:
        return [
            f"Grating coupler pitch={pitch:g} is evanescent at {wavelength_nm:g} nm "
            f"(phase mismatch with n_eff={float(neff):g}; no radiating angle)."
        ]

    if declared_angle is None:
        return []

    delta = abs(float(declared_angle) - expected)
    if delta > _COUPLING_ANGLE_TOLERANCE_DEG:
        return [
            "Grating coupler coupling_angle_deg "
            f"({declared_angle:g}) differs from pitch/wavelength stub "
            f"({expected:g}) by {delta:g} deg."
        ]
    return []


__all__ = [
    "GuidedModeTraceResult",
    "SILICON_STRIP_NEFF_STUB",
    "SILICON_STRIP_NG_STUB",
    "summarize_path",
    "trace_guided_mode",
    "trace_guided_path",
    "validate_coupler_transition",
]
