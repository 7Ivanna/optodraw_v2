"""Lightweight Mach-Zehnder interferometer and modulator trace stubs."""

from __future__ import annotations

import math
import warnings
from typing import Any, Iterable

from optodraw.core.guided import SILICON_STRIP_NEFF_STUB, trace_guided_path


def _component_metadata(component: Any) -> dict[str, Any]:
    if hasattr(component, "physics_metadata"):
        return component.physics_metadata()
    return {}


def _find_component(components: Iterable, component_type: str) -> Any | None:
    for component in components:
        if getattr(component, "component_type", component.__class__.__name__) == component_type:
            return component
    return None


def _normalize_drive_style(style: str) -> str:
    return str(style).lower().replace("-", "").replace("_", "")


def _resolve_vpi(
    metadata: dict[str, Any],
    mzm: Any,
    *,
    vpi_kw: float,
) -> float:
    if metadata.get("Vpi") is not None:
        return float(metadata["Vpi"])
    vpil = metadata.get("VpiL")
    if vpil is not None:
        length = metadata.get("electrode_length", getattr(mzm, "electrode_length", None))
        if length is not None and float(length) > 0:
            return float(vpil) / float(length)
    return float(vpi_kw)


def _mzi_transmission(delta_phi_rad: float) -> tuple[float, float]:
    """Return (through_power, drop_power) for a balanced 2x2 coupler MZI stub."""

    through = math.cos(delta_phi_rad / 2.0) ** 2
    return through, 1.0 - through


def _resolve_arm_length_delta(
    metadata: dict[str, Any],
    component: Any,
    *,
    arm_imbalance_um: float | None = None,
) -> float:
    if arm_imbalance_um is not None:
        return float(arm_imbalance_um)

    upper = metadata.get("arm_length_upper")
    lower = metadata.get("arm_length_lower")
    if upper is not None and lower is not None:
        return float(upper) - float(lower)

    if metadata.get("arm_length_delta") is not None:
        return float(metadata["arm_length_delta"])

    imbalance = metadata.get("arm_imbalance_um")
    if imbalance is not None:
        return float(imbalance)

    return float(getattr(component, "arm_imbalance_um", 0.0) or 0.0)


def _arm_imbalance_phase_rad(
    metadata: dict[str, Any],
    component: Any,
    *,
    wavelength_nm: float,
    effective_index: float | None = None,
    arm_imbalance_um: float | None = None,
) -> float:
    delta_length_um = _resolve_arm_length_delta(
        metadata,
        component,
        arm_imbalance_um=arm_imbalance_um,
    )
    if abs(delta_length_um) < 1e-15:
        return 0.0

    neff = effective_index
    if neff is None:
        neff = metadata.get("effective_index")
    if neff is None:
        neff = SILICON_STRIP_NEFF_STUB
    wavelength_um = float(wavelength_nm) / 1000.0
    if wavelength_um <= 0:
        return 0.0
    return 2.0 * math.pi * float(neff) * delta_length_um / wavelength_um


def _resolve_phase_bias(
    metadata: dict[str, Any],
    *,
    phase_bias_rad: float,
    phase_bias_upper_rad: float | None = None,
    phase_bias_lower_rad: float | None = None,
) -> tuple[float, float, float]:
    upper = float(
        phase_bias_upper_rad
        if phase_bias_upper_rad is not None
        else metadata.get("phase_bias_upper_arm", metadata.get("phase_bias_upper", 0.0))
    )
    lower = float(
        phase_bias_lower_rad
        if phase_bias_lower_rad is not None
        else metadata.get("phase_bias_lower_arm", metadata.get("phase_bias_lower", 0.0))
    )
    common = float(phase_bias_rad)
    if metadata.get("phase_bias") is not None:
        common += float(metadata["phase_bias"])
    return common + upper - lower, upper, lower


def _estimate_extinction_db(through_power: float, cross_power: float) -> float | None:
    peak = max(through_power, cross_power)
    null = min(through_power, cross_power)
    if null <= 0.0 or peak <= 0.0:
        return None
    return 10.0 * math.log10(peak / null)


def _mzm_phase_shift_rad(
    drive_style: str,
    drive_voltage: float,
    vpi: float,
    *,
    phase_upper: float,
    phase_lower: float,
) -> tuple[float, str]:
    """Return (delta_phi_rad, phase_model) for MZM electro-optic stubs.

    Assumptions (diagram-level, not a full EO solver):

    - **gs / single-arm**: RF on one arm only → ``Δφ = π V / Vπ``.
    - **gsg / dual-arm (same polarity)**: treated like single-arm for ``Δφ``.
    - **dual_arm_gsg / push-pull**: opposite drive on arms → ``Δφ = 2 π V / Vπ``.
    """

    v = float(drive_voltage)
    base = math.pi * v / vpi if vpi != 0 else 0.0
    style = _normalize_drive_style(drive_style)

    if style in {"dualarmgsg", "pushpull", "differential"}:
        delta_phi = 2.0 * base + phase_upper - phase_lower
        return delta_phi, "push_pull"
    if style in {"gsg", "dual", "dualarm", "botharms"}:
        delta_phi = base + phase_upper - phase_lower
        return delta_phi, "dual_arm_same_polarity"
    delta_phi = base + phase_upper - phase_lower
    return delta_phi, "single_arm"


def trace_mzi_transfer(
    mzi,
    *,
    phase_bias_rad: float = 0.0,
    phase_bias_upper_rad: float | None = None,
    phase_bias_lower_rad: float | None = None,
    arm_imbalance_um: float | None = None,
    effective_index: float | None = None,
    wavelength_nm: float = 1550.0,
) -> dict[str, Any]:
    """Return through/drop transfer for an MZI with phase bias and arm imbalance."""

    metadata = _component_metadata(mzi)
    delta_phi, phase_upper, phase_lower = _resolve_phase_bias(
        metadata,
        phase_bias_rad=phase_bias_rad,
        phase_bias_upper_rad=phase_bias_upper_rad,
        phase_bias_lower_rad=phase_bias_lower_rad,
    )
    arm_phase = _arm_imbalance_phase_rad(
        metadata,
        mzi,
        wavelength_nm=wavelength_nm,
        effective_index=effective_index,
        arm_imbalance_um=arm_imbalance_um,
    )
    delta_phi += arm_phase

    through, drop = _mzi_transmission(delta_phi)
    extinction_db = _estimate_extinction_db(through, drop)
    if metadata.get("extinction_ratio_db") is not None:
        extinction_db = float(metadata["extinction_ratio_db"])

    return {
        "component": "MZI",
        "wavelength_nm": float(wavelength_nm),
        "phase_bias_rad": delta_phi,
        "phase_bias_upper_rad": phase_upper,
        "phase_bias_lower_rad": phase_lower,
        "arm_imbalance_um": _resolve_arm_length_delta(
            metadata,
            mzi,
            arm_imbalance_um=arm_imbalance_um,
        ),
        "arm_imbalance_phase_rad": arm_phase,
        "through_power": through,
        "drop_power": drop,
        "transmission": through,
        "cross_power": drop,
        "extinction_db": extinction_db,
        "arm_length": metadata.get("arm_length", getattr(mzi, "arm_length", None)),
        "arm_gap": metadata.get("arm_gap", getattr(mzi, "arm_gap", None)),
    }


def trace_mzi_power(
    mzi,
    *,
    phase_bias_rad: float = 0.0,
    wavelength_nm: float = 1550.0,
    **kwargs,
) -> dict[str, Any]:
    """Return through/drop port powers for a balanced MZI stub (T = cos²(Δφ/2))."""

    result = trace_mzi_transfer(
        mzi,
        phase_bias_rad=phase_bias_rad,
        wavelength_nm=wavelength_nm,
        **kwargs,
    )
    return {
        "component": result["component"],
        "wavelength_nm": result["wavelength_nm"],
        "phase_bias_rad": result["phase_bias_rad"],
        "through_power": result["through_power"],
        "drop_power": result["drop_power"],
        "arm_length": result["arm_length"],
        "arm_gap": result["arm_gap"],
        "extinction_ratio_db": result.get("extinction_db"),
    }


def trace_mzm_transfer(
    mzm,
    *,
    drive_voltage: float = 0.0,
    Vpi: float = 4.0,
    wavelength_nm: float = 1550.0,
) -> dict[str, Any]:
    """Return intensity transfer for an MZM stub driven at ``drive_voltage``."""

    metadata = _component_metadata(mzm)
    vpi = _resolve_vpi(metadata, mzm, vpi_kw=Vpi)

    drive_style = metadata.get("drive_style", getattr(mzm, "drive_style", "gs"))
    phase_upper = float(metadata.get("phase_bias_upper_arm", 0.0))
    phase_lower = float(metadata.get("phase_bias_lower_arm", 0.0))

    delta_phi, phase_model = _mzm_phase_shift_rad(
        drive_style,
        drive_voltage,
        vpi,
        phase_upper=phase_upper,
        phase_lower=phase_lower,
    )
    arm_phase = _arm_imbalance_phase_rad(
        metadata,
        mzm,
        wavelength_nm=wavelength_nm,
        effective_index=metadata.get("effective_index"),
    )
    delta_phi += arm_phase

    through, cross = _mzi_transmission(delta_phi)
    extinction_db = _estimate_extinction_db(through, cross)
    if metadata.get("extinction_ratio_db") is not None:
        extinction_db = float(metadata["extinction_ratio_db"])

    return {
        "component": "MZM",
        "wavelength_nm": float(wavelength_nm),
        "drive_voltage": float(drive_voltage),
        "Vpi": vpi,
        "VpiL": metadata.get("VpiL"),
        "drive_style": drive_style,
        "phase_model": phase_model,
        "phase_shift_rad": delta_phi,
        "phase_rad": delta_phi,
        "arm_imbalance_phase_rad": arm_phase,
        "through_power": through,
        "cross_power": cross,
        "transmission": through,
        "drop_power": cross,
        "extinction_db": extinction_db,
    }


def _apply_soa_gain(
    power: float,
    component: Any,
) -> tuple[float, dict[str, Any] | None]:
    metadata = _component_metadata(component)
    gain_db = float(metadata.get("gain_db", 20.0))
    linear_gain = 10.0 ** (gain_db / 10.0)
    output_power = power * linear_gain

    saturation_power_mw = metadata.get("saturation_power_mw")
    capped = False
    if saturation_power_mw is not None and float(saturation_power_mw) > 0:
        input_mw = power * 1000.0
        sat = float(saturation_power_mw)
        output_mw = input_mw * linear_gain
        if output_mw > sat:
            output_power = sat / 1000.0
            capped = True

    return output_power, {
        "gain_db": gain_db,
        "linear_gain": linear_gain,
        "input_power": power,
        "output_power": output_power,
        "saturation_power_mw": saturation_power_mw,
        "gain_capped": capped,
    }


def trace_active_chain(
    components: Iterable,
    *,
    wavelength_nm: float = 1550.0,
    phase_bias_rad: float = 0.0,
    drive_voltage: float = 0.0,
    Vpi: float = 4.0,
    **kwargs,
) -> dict[str, Any]:
    """Combine guided-path and interferometer stubs for GC→MZI/MZM→PD chains."""

    components_list = list(components)
    guided = trace_guided_path(components_list, wavelength_nm=wavelength_nm, **kwargs)

    interferometer_result: dict[str, Any] | None = None
    for component in components_list:
        component_type = getattr(component, "component_type", component.__class__.__name__)
        if component_type == "MZI":
            interferometer_result = trace_mzi_power(
                component,
                phase_bias_rad=phase_bias_rad,
                wavelength_nm=wavelength_nm,
            )
            break
        if component_type == "MZM":
            interferometer_result = trace_mzm_transfer(
                component,
                drive_voltage=drive_voltage,
                Vpi=Vpi,
                wavelength_nm=wavelength_nm,
            )
            break

    optical_power = 1.0
    if interferometer_result is not None:
        optical_power = float(interferometer_result.get("through_power", 1.0))

    soa_result: dict[str, Any] | None = None
    for component in components_list:
        component_type = getattr(component, "component_type", component.__class__.__name__)
        if component_type != "SOA":
            continue
        optical_power, soa_result = _apply_soa_gain(optical_power, component)

    photodetector_result: dict[str, Any] | None = None
    for component in components_list:
        component_type = getattr(component, "component_type", component.__class__.__name__)
        if component_type != "OnChipPhotodetector":
            continue
        metadata = _component_metadata(component)
        responsivity = metadata.get("responsivity_a_per_w")
        if responsivity is None:
            responsivity = 0.8
            warnings.warn(
                "OnChipPhotodetector responsivity stub used; set physics_metadata for better estimates.",
                stacklevel=2,
            )
        photodetector_result = {
            "responsivity_a_per_w": float(responsivity),
            "input_power": optical_power,
            "photocurrent_a": float(responsivity) * optical_power,
            "bandwidth_ghz": metadata.get("bandwidth_ghz"),
        }
        break

    return {
        "guided": guided.to_dict(),
        "interferometer": interferometer_result,
        "soa": soa_result,
        "photodetector": photodetector_result,
        "combined_path_length_um": guided.path_length_um,
    }


def trace_readout_chain(
    components: Iterable,
    *,
    optical_power_w: float = 1.0,
    transimpedance_ohm: float = 1000.0,
    adc_full_scale_v: float = 1.0,
    adc_bits: int = 10,
) -> dict[str, Any]:
    """Estimate detector-to-ADC readout values for PD→TIA→ADC chains."""

    components_list = list(components)
    photodetector = _find_component(components_list, "OnChipPhotodetector")
    tia = _find_component(components_list, "TIA")
    adc = _find_component(components_list, "ADC")

    pd_metadata = _component_metadata(photodetector) if photodetector is not None else {}
    tia_metadata = _component_metadata(tia) if tia is not None else {}
    adc_metadata = _component_metadata(adc) if adc is not None else {}

    responsivity = float(pd_metadata.get("responsivity_a_per_w", 0.8))
    if photodetector is None:
        warnings.warn(
            "trace_readout_chain used default photodetector responsivity stub (0.8 A/W).",
            stacklevel=2,
        )

    optical_power = float(optical_power_w)
    photocurrent = responsivity * optical_power

    tia_transimpedance = float(tia_metadata.get("transimpedance_ohm", transimpedance_ohm))
    if tia is None:
        warnings.warn(
            "trace_readout_chain used default TIA transimpedance stub; add a TIA component for explicit metadata.",
            stacklevel=2,
        )
    voltage = photocurrent * tia_transimpedance

    bits = max(1, int(adc_metadata.get("bits", adc_bits)))
    full_scale = float(adc_metadata.get("full_scale_v", adc_full_scale_v))
    if full_scale <= 0:
        adc_code_stub = 0
    else:
        normalized = max(0.0, min(voltage / full_scale, 1.0))
        adc_code_stub = int(round(normalized * ((1 << bits) - 1)))

    return {
        "optical_power_w": optical_power,
        "responsivity_a_per_w": responsivity,
        "photocurrent_a": photocurrent,
        "tia_transimpedance_ohm_stub": tia_transimpedance,
        "tia_output_voltage_v": voltage,
        "adc_full_scale_v": full_scale,
        "adc_bits": bits,
        "adc_code_stub": adc_code_stub,
    }


__all__ = [
    "trace_active_chain",
    "trace_mzi_power",
    "trace_mzi_transfer",
    "trace_mzm_transfer",
    "trace_readout_chain",
]
