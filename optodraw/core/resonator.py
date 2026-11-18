"""Lightweight microring / racetrack Lorentzian resonance trace stubs."""

from __future__ import annotations

import math
import warnings
from typing import Any

_DEFAULT_Q = 1e4
_DEFAULT_LAMBDA0_NM = 1550.0
_C = 299_792_458.0  # speed of light in m/s


def _component_metadata(component: Any) -> dict[str, Any]:
    if hasattr(component, "physics_metadata"):
        return component.physics_metadata()
    return {}


def _normalize_drive_style(style: str) -> str:
    return str(style).lower().replace("-", "").replace("_", "")


def lorentzian_fwhm_nm(lambda0_nm: float, Q: float) -> float:
    """Return Lorentzian full width at half maximum in nanometers."""

    if Q <= 0:
        raise ValueError("Q must be positive")
    if lambda0_nm <= 0:
        raise ValueError("lambda0_nm must be positive")
    return float(lambda0_nm) / float(Q)


def Q_from_kappa_gamma(
    lambda0_nm: float,
    kappa: float,
    gamma: float,
) -> float:
    """Return loaded Q from coupling (``kappa``) and loss (``gamma``) rates.

    Rates are angular frequencies in rad/s: ``Q = omega0 / (kappa + gamma)``.
    """

    if lambda0_nm <= 0:
        raise ValueError("lambda0_nm must be positive")
    total = float(kappa) + float(gamma)
    if total <= 0:
        raise ValueError("kappa + gamma must be positive")
    lambda_m = float(lambda0_nm) * 1e-9
    omega0 = 2.0 * math.pi * _C / lambda_m
    return omega0 / total


def _resolve_ring_Q(
    metadata: dict[str, Any],
    *,
    lambda0_nm: float,
    Q: float | None,
) -> tuple[float, str | None]:
    if Q is not None:
        return float(Q), None
    if metadata.get("Q") is not None:
        return float(metadata["Q"]), None

    kappa = metadata.get("kappa")
    gamma = metadata.get("gamma")
    if kappa is not None and gamma is not None:
        return Q_from_kappa_gamma(lambda0_nm, float(kappa), float(gamma)), "kappa_gamma"

    return _DEFAULT_Q, "default_stub"


def lorentzian_transmission(
    wavelength_nm: float,
    lambda0_nm: float,
    Q: float,
    *,
    port: str = "through",
) -> float:
    """Return normalized Lorentzian power transmission for a resonator stub.

    Uses a symmetric notch / peak model with FWHM ``lambda0_nm / Q``:

    - ``port="through"``: minimum at resonance (notch filter)
    - ``port="drop"``: maximum at resonance (add-drop stub)
    """

    if Q <= 0:
        raise ValueError("Q must be positive")
    if lambda0_nm <= 0:
        raise ValueError("lambda0_nm must be positive")

    half_width_nm = lambda0_nm / (2.0 * Q)
    if half_width_nm <= 0:
        return 1.0

    x = (float(wavelength_nm) - float(lambda0_nm)) / half_width_nm
    peak = 1.0 / (1.0 + x * x)
    normalized_port = port.lower().replace("-", "").replace("_", "")
    if normalized_port in {"drop", "adddrop", "add_drop"}:
        return peak
    return 1.0 - peak


def _ring_circumference_um(ring: Any, metadata: dict[str, Any]) -> float | None:
    if metadata.get("ring_radius") is not None:
        return 2.0 * math.pi * float(metadata["ring_radius"])
    ring_radius = getattr(ring, "ring_radius", None)
    if ring_radius is not None:
        return 2.0 * math.pi * float(ring_radius)

    bend_radius = metadata.get("bend_radius", getattr(ring, "bend_radius", None))
    coupling_length = metadata.get("coupling_length", getattr(ring, "coupling_length", None))
    length_y = getattr(ring, "length_y", 0.0) or 0.0
    if bend_radius is None or coupling_length is None:
        return None
    return 2.0 * math.pi * float(bend_radius) + 2.0 * float(coupling_length) + 2.0 * float(length_y)


def _ring_fsr_nm(
    ring: Any,
    metadata: dict[str, Any],
    *,
    wavelength_nm: float,
) -> float | None:
    """Estimate FSR from group index and round-trip length when not supplied."""

    if metadata.get("fsr_nm") is not None:
        fsr_nm = float(metadata["fsr_nm"])
        if not math.isfinite(fsr_nm) or fsr_nm <= 0:
            raise ValueError("fsr_nm must be a finite positive number")
        return fsr_nm

    circumference_um = _ring_circumference_um(ring, metadata)
    group_index = metadata.get("group_index", getattr(ring, "group_index", None))
    if circumference_um is None or circumference_um <= 0 or group_index is None:
        return None

    ng = float(group_index)
    if not math.isfinite(ng) or ng <= 0:
        raise ValueError("group_index must be a finite positive number")
    wavelength_um = float(wavelength_nm) / 1000.0
    return (wavelength_um**2) / (ng * circumference_um) * 1000.0


def _resonator_lambda0_nm(
    ring: Any,
    metadata: dict[str, Any],
    *,
    wavelength_nm: float,
    bias_voltage_v: float,
    tuning_efficiency_nm_per_v: float,
) -> float:
    lambda0 = metadata.get("lambda0_nm", metadata.get("resonance_wavelength_nm"))
    if lambda0 is None:
        lambda0 = _DEFAULT_LAMBDA0_NM
    lambda0 = float(lambda0) + float(bias_voltage_v) * float(tuning_efficiency_nm_per_v)
    return lambda0


def trace_ring_resonance(
    ring: Any,
    *,
    wavelength_nm: float = _DEFAULT_LAMBDA0_NM,
    bias_voltage_v: float = 0.0,
    tuning_efficiency_nm_per_v: float = 0.01,
    port: str = "through",
    Q: float | None = None,
) -> dict[str, Any]:
    """Trace a Lorentzian microring / racetrack resonance stub."""

    metadata = _component_metadata(ring)
    component_type = getattr(ring, "component_type", ring.__class__.__name__)

    lambda0_nm = _resonator_lambda0_nm(
        ring,
        metadata,
        wavelength_nm=wavelength_nm,
        bias_voltage_v=bias_voltage_v,
        tuning_efficiency_nm_per_v=tuning_efficiency_nm_per_v,
    )

    q_value, q_source = _resolve_ring_Q(metadata, lambda0_nm=lambda0_nm, Q=Q)
    if q_source == "default_stub":
        warnings.warn(
            f"{component_type} Q stub used (default {_DEFAULT_Q:g}); "
            "set physics_metadata['Q'] or kappa/gamma for better estimates.",
            stacklevel=2,
        )
    through_power = lorentzian_transmission(
        wavelength_nm,
        lambda0_nm,
        q_value,
        port="through",
    )
    cross_power = lorentzian_transmission(
        wavelength_nm,
        lambda0_nm,
        q_value,
        port="drop",
    )
    selected = lorentzian_transmission(
        wavelength_nm,
        lambda0_nm,
        q_value,
        port=port,
    )
    fsr_nm = _ring_fsr_nm(ring, metadata, wavelength_nm=lambda0_nm)

    return {
        "component": component_type,
        "wavelength_nm": float(wavelength_nm),
        "lambda0_nm": lambda0_nm,
        "Q": q_value,
        "Q_source": q_source,
        "fwhm_nm": lorentzian_fwhm_nm(lambda0_nm, q_value),
        "kappa": metadata.get("kappa"),
        "gamma": metadata.get("gamma"),
        "fsr_nm": fsr_nm,
        "fsr_source": (
            "metadata" if metadata.get("fsr_nm") is not None
            else "group_index" if fsr_nm is not None
            else None
        ),
        "bias_voltage_v": float(bias_voltage_v),
        "tuning_efficiency_nm_per_v": float(tuning_efficiency_nm_per_v),
        "port": port,
        "transmission": selected,
        "through_power": through_power,
        "cross_power": cross_power,
        "ring_radius": metadata.get("ring_radius", getattr(ring, "ring_radius", None)),
        "bend_radius": metadata.get("bend_radius", getattr(ring, "bend_radius", None)),
        "coupling_length": metadata.get("coupling_length", getattr(ring, "coupling_length", None)),
    }


_RESONATOR_TYPES = frozenset(
    {
        "MicroringResonator",
        "PNMicroringModulator",
        "RacetrackResonator",
        "RacetrackModulator",
    }
)


def is_resonator_component(component: Any) -> bool:
    component_type = getattr(component, "component_type", component.__class__.__name__)
    return component_type in _RESONATOR_TYPES


__all__ = [
    "Q_from_kappa_gamma",
    "is_resonator_component",
    "lorentzian_fwhm_nm",
    "lorentzian_transmission",
    "trace_ring_resonance",
]
