"""Lightweight electrical port classification and route validation."""

from __future__ import annotations

from dataclasses import dataclass, field
from math import isfinite
from typing import Any

_RF_COMPONENTS = frozenset({"GSGProbePad"})
_DC_COMPONENTS = frozenset({"ElectricalPad"})
_HEATER_COMPONENTS = frozenset({"HeaterPad"})
_RF_DRIVE_COMPONENTS = frozenset({"MZM", "MZI", "PNMicroringModulator", "RacetrackModulator"})
_ANALOG_COMPONENTS = frozenset({"TIA", "TIABlock"})


@dataclass(frozen=True)
class ElectricalSignalSpec:
    """Normalized signal metadata for an electrical port or route.

    The fields are intentionally lightweight and optional so schematic figures
    can carry useful assumptions without becoming a SPICE or RF simulator.
    """

    kind: str
    component_type: str = ""
    port_name: str = ""
    voltage_v: float | None = None
    current_a: float | None = None
    impedance_ohms: float | None = None
    resistance_ohms: float | None = None
    bandwidth_ghz: float | None = None
    rf_power_dbm: float | None = None
    phase_deg: float | None = None
    bit_rate_gbps: float | None = None
    timing_ps: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly dict without dropping the original metadata."""

        return {
            "kind": self.kind,
            "component_type": self.component_type,
            "port_name": self.port_name,
            "voltage_v": self.voltage_v,
            "current_a": self.current_a,
            "impedance_ohms": self.impedance_ohms,
            "resistance_ohms": self.resistance_ohms,
            "bandwidth_ghz": self.bandwidth_ghz,
            "rf_power_dbm": self.rf_power_dbm,
            "phase_deg": self.phase_deg,
            "bit_rate_gbps": self.bit_rate_gbps,
            "timing_ps": self.timing_ps,
            "metadata": dict(self.metadata),
        }


def _component_type(component: Any) -> str:
    return getattr(component, "component_type", component.__class__.__name__)


def _component_metadata(component: Any) -> dict[str, Any]:
    metadata_fn = getattr(component, "physics_metadata", None)
    if callable(metadata_fn):
        try:
            metadata = metadata_fn()
        except TypeError:
            metadata = {}
        if isinstance(metadata, dict):
            return dict(metadata)
    return {}


def _component_port_kind(component: Any, port_name: str) -> str | None:
    ports_fn = getattr(component, "ports", None)
    if not callable(ports_fn):
        return None
    try:
        port = ports_fn().get(port_name)
    except Exception:
        return None
    kind = getattr(port, "kind", None)
    return str(kind).lower() if kind else None


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
        return number if isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _first_float(*values: Any) -> float | None:
    for value in values:
        coerced = _float_or_none(value)
        if coerced is not None:
            return coerced
    return None


def _electrical_io_bank_kind(component: Any, port_key: str) -> str:
    metadata = _component_metadata(component)
    signal_kinds = metadata.get("signal_kinds", ())
    if port_key.startswith("e") and port_key[1:].isdigit():
        index = int(port_key[1:]) - 1
        if isinstance(signal_kinds, (list, tuple)) and 0 <= index < len(signal_kinds):
            return str(signal_kinds[index]).lower()
    return str(metadata.get("bank_kind", "electrical")).lower()


def port_signal_kind(component: Any, port_name: str) -> str:
    """Return a coarse signal class for an electrical port."""

    component_type = _component_type(component)
    port_key = str(port_name).lower()
    declared_port_kind = _component_port_kind(component, str(port_name))
    if declared_port_kind and declared_port_kind != "electrical":
        return declared_port_kind

    if component_type in _DC_COMPONENTS:
        return "dc"
    if component_type in _RF_COMPONENTS:
        return "ground" if port_key.endswith(("g1", "g2")) or port_key in {"g1", "g2"} else "rf"
    if component_type == "RFDriver":
        if port_key == "bias":
            return "dc"
        if port_key == "gnd":
            return "ground"
        return "rf"
    if component_type in _HEATER_COMPONENTS:
        return "heater"
    if component_type == "ElectricalIOBank":
        return _electrical_io_bank_kind(component, port_key)
    if component_type in _RF_DRIVE_COMPONENTS and port_key.startswith("e"):
        return "rf"
    if component_type == "OnChipPhotodetector" and port_key.startswith("e"):
        return "photocurrent"
    if component_type in _ANALOG_COMPONENTS:
        return "analog"
    if component_type == "ADC":
        return "digital" if port_key in {"e2", "e3"} else "analog"
    if component_type == "ADCBlock":
        return "digital" if port_key in {"digital", "dout", "out", "clk"} else "analog"
    if component_type == "DAC":
        return "analog" if port_key in {"out", "iout", "vout"} else "digital"
    if component_type == "DACDriver":
        return "rf" if port_key in {"e3", "e4"} else "digital"
    if component_type == "Microcontroller":
        if port_key in {"pwr", "vdd"}:
            return "dc"
        if port_key == "gnd":
            return "ground"
        if port_key == "clk":
            return "clock"
        return "digital"
    if component_type == "BalancedPhotodetector":
        if port_key.startswith("out"):
            return "photocurrent"
        if port_key == "bias":
            return "dc"
        if port_key == "gnd":
            return "ground"
    if component_type == "CoherentReceiver":
        if port_key.startswith(("i_", "q_")):
            return "analog"
        if port_key == "clk":
            return "clock"
        if port_key == "vdd":
            return "dc"
        if port_key == "gnd":
            return "ground"
    if component_type == "TransmitterMacro":
        if port_key == "data":
            return "digital"
        if port_key == "clk":
            return "clock"
        if port_key in {"bias", "gnd"}:
            return "ground" if port_key == "gnd" else "dc"
    if component_type == "ReceiverMacro":
        if port_key == "digital_out":
            return "digital"
        if port_key == "clk":
            return "clock"
        if port_key in {"bias", "gnd"}:
            return "ground" if port_key == "gnd" else "dc"
    if component_type == "MetalRoute":
        return "electrical"
    if component_type == "SignalArrow":
        return str(getattr(component, "signal", "electrical")).lower()
    return "electrical"


def electrical_signal_spec(component: Any, port_name: str = "") -> ElectricalSignalSpec:
    """Return normalized signal metadata for a component port."""

    metadata = _component_metadata(component)
    return ElectricalSignalSpec(
        kind=port_signal_kind(component, port_name),
        component_type=_component_type(component),
        port_name=str(port_name),
        voltage_v=_first_float(metadata.get("voltage_v"), metadata.get("bias_voltage_v")),
        current_a=_first_float(metadata.get("current_a"), metadata.get("photocurrent_a")),
        impedance_ohms=_first_float(metadata.get("impedance_ohms")),
        resistance_ohms=_first_float(metadata.get("resistance_ohms")),
        bandwidth_ghz=_first_float(metadata.get("bandwidth_ghz")),
        rf_power_dbm=_first_float(metadata.get("rf_power_dbm")),
        phase_deg=_first_float(metadata.get("phase_deg")),
        bit_rate_gbps=_first_float(metadata.get("bit_rate_gbps"), metadata.get("data_rate_gbps")),
        timing_ps=_first_float(metadata.get("timing_ps")),
        metadata=metadata,
    )


def _route_signal_kind(route: Any) -> str | None:
    explicit = getattr(route, "signal", None)
    if explicit:
        return str(explicit).lower()
    start_component = getattr(route, "start_component", None)
    start_port = getattr(route, "start_port", None)
    end_component = getattr(route, "end_component", None)
    end_port = getattr(route, "end_port", None)
    kinds: set[str] = set()
    if start_component is not None and start_port is not None:
        kinds.add(port_signal_kind(start_component, start_port))
    if end_component is not None and end_port is not None:
        kinds.add(port_signal_kind(end_component, end_port))
    if "rf" in kinds:
        return "rf"
    if kinds:
        return sorted(kinds)[0]
    return None


def _endpoint_specs(route: Any) -> list[ElectricalSignalSpec]:
    specs: list[ElectricalSignalSpec] = []
    start_component = getattr(route, "start_component", None)
    start_port = getattr(route, "start_port", None)
    end_component = getattr(route, "end_component", None)
    end_port = getattr(route, "end_port", None)
    if start_component is not None and start_port is not None:
        specs.append(electrical_signal_spec(start_component, start_port))
    if end_component is not None and end_port is not None:
        specs.append(electrical_signal_spec(end_component, end_port))
    return specs


def _min_present(values: list[float | None]) -> float | None:
    present = [value for value in values if value is not None]
    return min(present) if present else None


def route_signal_spec(route: Any) -> ElectricalSignalSpec:
    """Return normalized signal metadata for an electrical route."""

    endpoint_specs = _endpoint_specs(route)
    route_metadata = {
        "physical_length_um": _first_float(getattr(route, "physical_length_um", None)),
        "start_component": _component_type(getattr(route, "start_component")) if getattr(route, "start_component", None) is not None else None,
        "start_port": getattr(route, "start_port", None),
        "end_component": _component_type(getattr(route, "end_component")) if getattr(route, "end_component", None) is not None else None,
        "end_port": getattr(route, "end_port", None),
        "endpoint_kinds": [spec.kind for spec in endpoint_specs],
    }
    endpoint_bandwidth = _min_present([spec.bandwidth_ghz for spec in endpoint_specs])
    endpoint_bit_rate = _min_present([spec.bit_rate_gbps for spec in endpoint_specs])
    return ElectricalSignalSpec(
        kind=_route_signal_kind(route) or "electrical",
        component_type=_component_type(route),
        port_name="",
        voltage_v=_first_float(getattr(route, "voltage_v", None)),
        current_a=_first_float(getattr(route, "current_a", None)),
        impedance_ohms=_first_float(getattr(route, "impedance_ohms", None), *(spec.impedance_ohms for spec in endpoint_specs)),
        bandwidth_ghz=_first_float(getattr(route, "bandwidth_ghz", None), endpoint_bandwidth),
        rf_power_dbm=_first_float(getattr(route, "rf_power_dbm", None)),
        phase_deg=_first_float(getattr(route, "phase_deg", None)),
        bit_rate_gbps=_first_float(getattr(route, "bit_rate_gbps", None), endpoint_bit_rate),
        timing_ps=_first_float(getattr(route, "timing_ps", None)),
        metadata=route_metadata,
    )


def validate_electrical_chain(components: list[Any]) -> list[str]:
    """Return warnings for mismatched electrical routes in ``components``."""

    warnings: list[str] = []
    for item in components:
        component_type = getattr(item, "component_type", item.__class__.__name__)
        if component_type not in {"Route", "WaveguideRoute", "FiberRoute", "MetalRoute"}:
            continue
        if getattr(item, "kind", "") != "electrical":
            continue

        start_component = getattr(item, "start_component", None)
        start_port = getattr(item, "start_port", None)
        end_component = getattr(item, "end_component", None)
        end_port = getattr(item, "end_port", None)
        if start_component is None or end_component is None:
            continue

        incompatible = False
        for component, port_name in ((start_component, start_port), (end_component, end_port)):
            ports_fn = getattr(component, "ports", None)
            try:
                ports = ports_fn() if callable(ports_fn) else {}
            except Exception:
                ports = {}
            if not isinstance(ports, dict) or port_name not in ports:
                warnings.append(
                    f"Electrical route references missing port "
                    f"({_component_type(component)}.{port_name}); select an existing electrical port."
                )
                incompatible = True
                continue
            declared_kind = _component_port_kind(component, port_name or "")
            if declared_kind in {"optical", "fiber", "free_space"}:
                warnings.append(
                    f"Electrical route connects to {declared_kind} port "
                    f"({_component_type(component)}.{port_name}); use an electrical port instead."
                )
                incompatible = True
        if incompatible:
            continue

        start_kind = port_signal_kind(start_component, start_port or "")
        end_kind = port_signal_kind(end_component, end_port or "")
        route_kind = _route_signal_kind(item) or start_kind
        endpoint_specs = _endpoint_specs(item)
        route_spec = route_signal_spec(item)

        if route_kind == "rf" and ("dc" in {start_kind, end_kind}):
            dc_side = start_component if start_kind == "dc" else end_component
            dc_port = start_port if start_kind == "dc" else end_port
            dc_type = _component_type(dc_side)
            warnings.append(
                f"RF electrical route connects to DC-only pad "
                f"({dc_type}.{dc_port}); use an RF probe or GSG pad instead."
            )
        if route_kind == "rf" and route_spec.impedance_ohms is not None:
            for spec in endpoint_specs:
                if spec.impedance_ohms is None:
                    continue
                delta = abs(spec.impedance_ohms - route_spec.impedance_ohms)
                tolerance = max(5.0, route_spec.impedance_ohms * 0.1)
                if delta > tolerance:
                    warnings.append(
                        f"RF impedance mismatch on route: expected {route_spec.impedance_ohms:g} ohm, "
                        f"but {spec.component_type}.{spec.port_name} declares {spec.impedance_ohms:g} ohm."
                    )

        required_bandwidth = _first_float(getattr(item, "required_bandwidth_ghz", None), getattr(item, "bandwidth_ghz", None))
        if required_bandwidth is None and route_spec.bit_rate_gbps is not None:
            required_bandwidth = route_spec.bit_rate_gbps * 0.5
        if required_bandwidth is not None:
            for spec in endpoint_specs:
                if spec.bandwidth_ghz is not None and spec.bandwidth_ghz < required_bandwidth:
                    warnings.append(
                        f"Bandwidth bottleneck on {route_kind} electrical route: "
                        f"{spec.component_type}.{spec.port_name} supports {spec.bandwidth_ghz:g} GHz, "
                        f"below required {required_bandwidth:g} GHz."
                    )
    return warnings


__all__ = [
    "ElectricalSignalSpec",
    "electrical_signal_spec",
    "port_signal_kind",
    "route_signal_spec",
    "validate_electrical_chain",
]
