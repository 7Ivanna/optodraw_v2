"""Sources emit; detectors, dumps and samples absorb."""

from __future__ import annotations

import dataclasses
import math

from ..errors import AnimationError
from ..signals import linear, scalar
from . import Behaviour, Emission, Transfer, register
from .geometry import index_of, optical_path_points


@register("Laser", "Lamp", "FrequencyComb")
class Source(Behaviour):
    """Emits ``power:<sid>`` mW, else the part's ``power_mw``, else 1 mW: a field amplitude of sqrt(power)."""

    passive = False

    def emissions(self, part, sid, params):
        ports = part.ports()
        port = "out" if "out" in ports else "o1"
        default = getattr(part, "wavelength", None) or getattr(part, "wavelength_nm", None) or (
            1550.0 if port == "o1" else 633.0)
        wavelength = float(params.get(f"wavelength:{sid}", params.get("wavelength", default)))
        own = getattr(part, "power_mw", None)
        power_mw = float(params.get(f"power:{sid}", 1.0 if own is None else own))
        if not power_mw >= 0.0:
            raise AnimationError(f"{sid}: an optical power is 0 mW or more, not {power_mw}")
        return [Emission(port, linear(float(params.get(f"angle:{sid}", 0.0)), math.sqrt(power_mw)), wavelength,
                         width_ps=float(params.get(f"width:{sid}", 0.2)))]

    def sinks(self, part, port):
        """Light that comes back into a source (a Michelson's return) ends there."""

        return part.ports()[port].kind != "electrical"


@register("OnChipLaser", "DBRLaser")
class ChipLaser(Source):
    """A chip laser starts its light in the drawn active region, not at the output port.

    The light begins on the internal port ``_active`` and runs the part's drawn emission path to ``o1``.
    That edge takes the drawn length times the group index. The laser has no ``group_index`` of its own,
    so ``index_of`` gives the silicon default, 4.2.
    """

    ACTIVE = "_active"

    def emissions(self, part, sid, params):
        return [dataclasses.replace(emission, port=self.ACTIVE) for emission in super().emissions(part, sid, params)]

    def sinks(self, part, port):
        return port != self.ACTIVE and super().sinks(part, port)

    def transfers(self, part, sid, in_port, wavelength_nm, params):
        if in_port != self.ACTIVE:
            return []
        path = optical_path_points(part, "o1")["o1"][0]
        return [Transfer(self.ACTIVE, "o1", scalar(1.0), path, index_of(part, "o1"), "emission")]


SINK_TYPES = ("Photodiode", "AmplifiedPhotodetector", "Camera", "CMOSCamera", "EMCCD", "CameraSensor",
              "PowerMeter", "OpticalPowerMeter", "Spectrometer", "OSA", "PMT", "SPADArray", "SNSPD",
              "BeamDump", "Block", "Sample", "AvalanchePhotodetector", "Terminator", "QuadrantPhotodiode", "BalancedDetector")


@register(*SINK_TYPES)
class Sink(Behaviour):
    def sinks(self, part, port):
        return part.ports()[port].kind != "electrical"


@register("OnChipPhotodetector", "OnChipBalancedPhotodetector")
class ChipDetector(Behaviour):
    """The light runs from the input port into the drawn absorber and ends there.

    Each input ``oN`` has an edge to the internal port ``_absorb_oN``, which absorbs. The edge keeps the power:
    the absorbed power equals the power at the port.
    """

    def sinks(self, part, port):
        return port.startswith("_absorb_")

    def transfers(self, part, sid, in_port, wavelength_nm, params):
        port = part.ports().get(in_port)
        found = optical_path_points(part, in_port) if port is not None and port.kind != "electrical" else {}
        return [Transfer(in_port, out, scalar(1.0), paths[0], index_of(part, in_port), "absorb")
                for out, paths in found.items()]


@register("PresetWDMInput")
class WavelengthDivisionSource(Source):
    """Illustrative defaults: 1549, 1550, 1551 nm, each with power 1.

    Numeric channels do not come from the colours in the component drawing.
    """

    def emissions(self, part, sid, params):
        wavelengths = params.get(f"wavelengths:{sid}", part.wavelengths_nm)
        powers = params.get(f"channel_powers:{sid}", part.channel_powers)
        if not wavelengths or len(wavelengths) != len(powers):
            raise AnimationError(f"{sid}: wavelengths and channel powers must have matching nonempty lengths")
        out = []
        for wavelength, amplitude_power in zip(wavelengths, powers):
            wavelength, amplitude_power = float(wavelength), float(amplitude_power)
            if not math.isfinite(wavelength) or wavelength <= 0 or not math.isfinite(amplitude_power) or amplitude_power < 0:
                raise AnimationError(f"{sid}: wavelengths must be positive and powers must be nonnegative")
            out.append(Emission("o1", linear(float(params.get(f"angle:{sid}", 0)), math.sqrt(amplitude_power)),
                                wavelength, width_ps=float(params.get(f"width:{sid}", 0.2))))
        return out


@register("PhotonCounter", "BalancedPhotodetector", "ReceiverMacro")
class EnclosedDetector(Sink):
    """A photon counter's fibre inputs, a balanced detector's two optical inputs and a receiver's optical input
    absorb what reaches them."""


@register("TransmitterMacro")
class TransmitterSource(Source):
    """A transmitter's laser emits from ``opt_out`` at its ``wavelength_nm``, unless the params give another."""

    def emissions(self, part, sid, params):
        return [dataclasses.replace(emission, port="opt_out") for emission in super().emissions(part, sid, params)]


@register("FiberArray", "OpticalIOBank")
class ChipExit(Sink):
    """The light leaves the chip here, into fibres the drawing does not follow: it ends at the port it reaches."""
