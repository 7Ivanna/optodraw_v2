"""Parts the light passes through: lenses, windows, filters, fibre, waveguides, gratings; and mirrors."""

from __future__ import annotations

import cmath
import dataclasses
import math

import numpy as np

from ..signals import scalar
from . import Behaviour, Transfer, register
from .geometry import N_FIBRE, anchor_xy, drawn_points, index_of, local_to_world, port_xy, straight, through_anchor


class TwoPort(Behaviour):
    """Light enters one port and leaves the other. ``amplitude`` scales the field (the root of the power ratio)."""

    def pair(self, part) -> tuple[str, str]:
        names = [name for name, port in part.ports().items() if port.kind != "electrical"]
        return (names[0], names[1])

    def amplitude(self, part, sid, wavelength_nm, params) -> float:
        return 1.0

    def points(self, part, a, b):
        return drawn_points(part, a, b, straight(part, a, b))

    def transfers(self, part, sid, in_port, wavelength_nm, params):
        a, b = self.pair(part)
        if in_port not in (a, b):
            return []
        out = b if in_port == a else a
        return [Transfer(in_port, out, scalar(self.amplitude(part, sid, wavelength_nm, params)),
                         self.points(part, in_port, out), index_of(part, in_port))]


@register("Lens", "AsphericLens", "CylindricalLens", "Objective", "Iris", "ApertureStop", "Pinhole",
          "BrewsterWindow", "CryostatWindow", "WedgePlate", "LensTube", "BeamExpanderTelescope", "Telescope",
          "FiberPort", "FiberCollimator", "NonlinearCrystal")
class ThinOptic(TwoPort):
    def points(self, part, a, b):
        return through_anchor(part, a, b)


@register("Razor")
class KnifeEdge(ThinOptic):
    """An edge on the axis of a symmetric beam passes half of the power, for any beam size. Another ``blade_pos`` needs
    the beam's radius, which a scene does not hold, so it does not change this."""

    def amplitude(self, part, sid, wavelength_nm, params):
        return math.sqrt(0.5)


@register("Filter")
class SpectralFilter(ThinOptic):
    def amplitude(self, part, sid, wavelength_nm, params):
        cutoff = getattr(part, "cutoff_wavelength", None)
        if cutoff is None:
            return 1.0
        longpass = getattr(part, "pass_band", "longpass") == "longpass"
        return 1.0 if (wavelength_nm >= cutoff) == longpass else 0.0


@register("NDFilter")
class NeutralDensity(ThinOptic):
    def amplitude(self, part, sid, wavelength_nm, params):
        return 10 ** (-float(getattr(part, "optical_density", 0.0)) / 2.0)


@register("VariableAttenuator")
class Attenuator(TwoPort):
    def amplitude(self, part, sid, wavelength_nm, params):
        return 10 ** (-float(params.get(f"attenuation:{sid}", getattr(part, "attenuation_db", 0.0))) / 20.0)


@register("FiberAmplifier", "SOA")
class Amplifier(TwoPort):
    passive = False

    def amplitude(self, part, sid, wavelength_nm, params):
        return 10 ** (float(getattr(part, "gain_db", 20.0)) / 20.0)


@register("FiberSpool")
class Spool(TwoPort):
    """The drawing is a coil; the light runs ``fiber_length_km`` of fibre."""

    def transfers(self, part, sid, in_port, wavelength_nm, params):
        km = float(getattr(part, "fiber_length_km", 1.0))
        return [dataclasses.replace(t, physical_length=km * 1.0e9, group_index=N_FIBRE)
                for t in super().transfers(part, sid, in_port, wavelength_nm, params)]


@register("Waveguide", "Taper", "WaveguideBend", "Spiral", "PolarizationController")
class Guide(TwoPort):
    pass


@register("VerticalGratingCoupler", "FocusedApodizedGratingCoupler", "EdgeCoupler")
class ChipCoupler(TwoPort):
    def pair(self, part):
        return ("f1", "o1")

    def amplitude(self, part, sid, wavelength_nm, params):
        default = 0.8 if part.component_type == "EdgeCoupler" else 0.5
        return math.sqrt(float(getattr(part, "coupling_efficiency", default)))


@register("OpticalIsolator")
class Isolator(ThinOptic):
    """Forward only: light that comes back from ``out`` is absorbed."""

    def transfers(self, part, sid, in_port, wavelength_nm, params):
        return super().transfers(part, sid, in_port, wavelength_nm, params) if in_port == "in" else []

    def sinks(self, part, port):
        return port == "out"


@register("Mirror", "ConcaveMirror", "ConvexMirror", "BiconcaveMirror", "BiconvexMirror", "GalvoMirror",
          "Retroreflector", "DMD")
class Reflector(Behaviour):
    """A one-port mirror folds the beam at ``io``; a two-port mirror reflects from one port to the other."""

    fold_ports = frozenset({"io"})
    _MATRIX = np.array([[1, 0], [0, -1]], dtype=complex)

    def transfers(self, part, sid, in_port, wavelength_nm, params):
        ports = [name for name, port in part.ports().items() if port.kind != "electrical"]
        if in_port not in ports:
            return []
        out = in_port if len(ports) == 1 else next(name for name in ports if name != in_port)
        r = math.sqrt(float(getattr(part, "reflectance", 0.99)))
        return [Transfer(in_port, out, self._MATRIX * r, (port_xy(part, in_port), anchor_xy(part), port_xy(part, out)),
                         index_of(part, in_port))]


@register("FlipMirror")
class FlipReflector(Reflector):
    """In the beam the mirror folds it at ``io``. Out of the beam the light runs straight on through ``pass``."""

    fold_ports = frozenset({"io", "pass"})

    def transfers(self, part, sid, in_port, wavelength_nm, params):
        if in_port == "pass":
            if part.state == "up":
                return []
            return [Transfer("pass", "pass", np.eye(2, dtype=complex), (port_xy(part, "io"), port_xy(part, "io")),
                             index_of(part, "pass"))]
        if in_port != "io" or part.out_of_beam:
            return []
        r = math.sqrt(float(getattr(part, "reflectance", 0.99)))
        return [Transfer("io", "io", self._MATRIX * r, (port_xy(part, "io"), anchor_xy(part), port_xy(part, "io")),
                         index_of(part, "io"))]


@register("FourFSystem", "SpectrometerSlit", "VacuumChamber", "Prism", "Pentaprism")
class ClearOptic(ThinOptic):
    """Light crosses the part from one optical port to the other and keeps its power: a 4f relay (object to image
    through the Fourier plane), a slit, the two windows of a chamber, a prism. Surface losses are left out."""


@register("OpticalChopper")
class Chopper(ThinOptic):
    """The slots and the blades of the wheel are equally wide, so the beam is open half of each turn: the time
    average passes half of the power."""

    def amplitude(self, part, sid, wavelength_nm, params):
        return math.sqrt(0.5)


@register("AOM")
class AcoustoOptic(ThinOptic):
    """``out`` carries the first diffracted order, ``diffraction_efficiency`` of the power. The zeroth order leaves
    beside it and is not followed."""

    def amplitude(self, part, sid, wavelength_nm, params):
        return math.sqrt(float(getattr(part, "diffraction_efficiency", 0.75)))


@register("EOM")
class PhaseModulator(ThinOptic):
    """A Pockels phase modulator: a drive of ``drive:<sid>`` volts adds a phase of pi V / ``half_wave_voltage_v``."""

    def amplitude(self, part, sid, wavelength_nm, params):
        return cmath.exp(1j * math.pi * float(params.get(f"drive:{sid}", 0.0)) / float(part.half_wave_voltage_v))


@register("SLM")
class SpatialLightModulator(ThinOptic):
    """The pixels pass ``fill_factor`` of the power into the modulated beam (the gaps between them scatter the rest)
    and add the phase ``phase:<sid>``."""

    def amplitude(self, part, sid, wavelength_nm, params):
        return math.sqrt(float(part.fill_factor)) * cmath.exp(1j * float(params.get(f"phase:{sid}", 0.0)))


@register("Periscope")
class PeriscopeRelay(ThinOptic):
    """Two 45 degree mirrors, each keeping ``reflectance`` (0.99) of the power. Two reflections make a rotation: a
    periscope that turns the beam by ``output_angle_deg`` turns its polarisation by that angle too, so a 90 degree
    periscope swaps horizontal and vertical."""

    def transfers(self, part, sid, in_port, wavelength_nm, params):
        r = float(getattr(part, "reflectance", 0.99))
        turn = math.radians(float(part.output_angle_deg))
        rotate = np.array([[math.cos(turn), -math.sin(turn)], [math.sin(turn), math.cos(turn)]], dtype=complex)
        return [dataclasses.replace(t, matrix=r * (rotate if in_port == "in" else rotate.T))
                for t in super().transfers(part, sid, in_port, wavelength_nm, params)]


@register("RightAnglePrism")
class TotalInternalFold(ThinOptic):
    """The hypotenuse folds the beam at 45 degrees inside the glass. From an index of sqrt(2) up, 45 degrees is past
    the critical angle and the face reflects all the light; below it, the Fresnel share for p (horizontal, in the
    plane of the fold) and for s (vertical), and the rest leaves through the hypotenuse."""

    @staticmethod
    def fresnel(n: float) -> tuple[complex, complex]:
        """``(r_p, r_s)`` at 45 degrees inside glass of index ``n``, toward air."""

        cos_in = math.sqrt(0.5)
        cos_out = cmath.sqrt(1.0 - n * n * 0.5)               # imaginary past the critical angle: |r| = 1
        return (cos_in - n * cos_out) / (cos_in + n * cos_out), (n * cos_in - cos_out) / (n * cos_in + cos_out)

    def transfers(self, part, sid, in_port, wavelength_nm, params):
        fold = np.diag(self.fresnel(float(part.refractive_index))).astype(complex)
        return [dataclasses.replace(t, matrix=fold) for t in super().transfers(part, sid, in_port, wavelength_nm, params)]


@register("Monochromator")
class SlitBandpass(ThinOptic):
    """Equal entrance and exit slits pass a triangle of wavelengths: all of the power at ``center_wavelength_nm``,
    falling to none one bandpass away. The bandpass is the slit width (``slit:<sid>`` in µm, 100 by default) times
    the reciprocal linear dispersion, 10^6 / (groove density x focal length) nm per mm in first order."""

    def bandpass_nm(self, part, sid, params) -> float:
        slit_mm = float(params.get(f"slit:{sid}", 100.0)) * 1e-3
        return slit_mm * 1e6 / (float(part.groove_density_l_mm) * float(part.focal_length_mm))

    def amplitude(self, part, sid, wavelength_nm, params):
        offset = abs(wavelength_nm - float(part.center_wavelength_nm)) / self.bandpass_nm(part, sid, params)
        return math.sqrt(max(0.0, 1.0 - offset))


@register("Cryostat")
class CryostatWindows(ThinOptic):
    """The two windows pass the beam from ``in`` to ``out``. With its own sample on the stage (``with_sample``), the
    sample takes the light at every optical port, as a ``Sample`` does; without one, light sent to ``sample`` ends
    on the bare stage."""

    def sinks(self, part, port):
        optical = part.ports()[port].kind != "electrical"
        return optical and (port == "sample" or bool(getattr(part, "with_sample", True)))


@register("GratingCouplerArray")
class CouplerArray(Behaviour):
    """Each grating joins its fibre ``fK`` to its guide ``oK``, both ways, with the efficiency of one coupler
    (``coupling_efficiency``, 0.5 as for ``VerticalGratingCoupler``)."""

    def transfers(self, part, sid, in_port, wavelength_nm, params):
        out = {"f": "o", "o": "f"}.get(in_port[:1], "?") + in_port[1:]
        if out not in part.ports():
            return []
        amplitude = math.sqrt(float(getattr(part, "coupling_efficiency", 0.5)))
        return [Transfer(in_port, out, scalar(amplitude), straight(part, in_port, out), index_of(part, in_port))]


@register("ElectroAbsorptionModulator")
class ElectroAbsorption(Guide):
    """The drive (``drive:<sid>``, V) raises the absorption of the active section: the loss in dB grows in proportion
    to the drive up to ``extinction_ratio_db`` (10 dB) at ``v_swing`` (2 V) and stays there. Illustrative values,
    not a measured device."""

    def amplitude(self, part, sid, wavelength_nm, params):
        swing = min(max(float(params.get(f"drive:{sid}", 0.0)) / float(getattr(part, "v_swing", 2.0)), 0.0), 1.0)
        return 10 ** (-float(getattr(part, "extinction_ratio_db", 10.0)) * swing / 20.0)


@register("BraggGrating")
class BraggReflector(Behaviour):
    """A uniform grating by coupled-mode theory (T. Erdogan, J. Lightwave Technol. 15, 1277 (1997)). The peak power
    reflectance at ``center_wavelength_nm`` is ``reflectivity`` = tanh^2(kappa L), L the ``length`` in µm. A
    detuning delta = 2 pi n_g (1 / lambda - 1 / lambda_B) gives
    r = -kappa sinh(sL) / (delta sinh(sL) + i s cosh(sL)) and t = i s / (delta sinh(sL) + i s cosh(sL)),
    with s^2 = kappa^2 - delta^2: lossless, |r|^2 + |t|^2 = 1. The light reflects back out of the port it came in."""

    fold_ports = frozenset({"o1", "o2"})

    @staticmethod
    def coefficients(part, wavelength_nm: float) -> tuple[complex, complex]:
        length = float(part.length)
        kappa = math.atanh(math.sqrt(min(float(part.reflectivity), 1.0 - 1e-12))) / length
        delta = 2.0 * math.pi * index_of(part, "o1") * (1e3 / wavelength_nm - 1e3 / float(part.center_wavelength_nm))
        s = cmath.sqrt(kappa * kappa - delta * delta)
        over_s = length if abs(s * length) < 1e-9 else cmath.sinh(s * length) / s     # sinh(sL) / s, L as s -> 0
        below = delta * over_s + 1j * cmath.cosh(s * length)
        return -kappa * over_s / below, 1j / below

    def transfers(self, part, sid, in_port, wavelength_nm, params):
        if in_port not in self.fold_ports:
            return []
        r, t = self.coefficients(part, wavelength_nm)
        other = "o2" if in_port == "o1" else "o1"
        n = index_of(part, in_port)
        return [Transfer(in_port, other, scalar(t), straight(part, in_port, other), n, "transmit"),
                Transfer(in_port, in_port, scalar(r), through_anchor(part, in_port, in_port), n, "reflect")]


@register("SagnacLoop")
class LoopMirror(Behaviour):
    """A loop mirror: the coupler (power ``coupling_ratio``, 0.5) sends the light both ways round one loop, and the
    two waves meet again at the coupler. Back out of the port it came in: 4 k (1 - k) of the power; on to the other
    port: (1 - 2 k)^2. A 3 dB coupler reflects it all."""

    fold_ports = frozenset({"o1", "o2"})

    def transfers(self, part, sid, in_port, wavelength_nm, params):
        if in_port not in self.fold_ports:
            return []
        k = float(getattr(part, "coupling_ratio", 0.5))
        bar, cross = math.sqrt(1.0 - k), 1j * math.sqrt(k)
        other = "o2" if in_port == "o1" else "o1"
        trip = 2.0 * math.pi * float(part.loop_radius) + 2.0 * float(part.coupler_length)   # µm round the loop
        n = index_of(part, in_port)
        return [Transfer(in_port, in_port, scalar(2.0 * bar * cross), through_anchor(part, in_port, in_port), n,
                         "reflect", trip),
                Transfer(in_port, other, scalar(bar * bar + cross * cross), through_anchor(part, in_port, other), n,
                         "transmit", trip)]
@register("ModeCleaner")
class RingCavity(Behaviour):
    """Locked, the ring passes ``transmission`` percent of the power from ``in`` to ``out`` (and back), on the input
    line; the rest leaves M1 as ``refl``. Light that comes back by ``out`` circulates the other way and leaves by ``in``."""

    def transfers(self, part, sid, in_port, wavelength_nm, params):
        t = min(max(float(getattr(part, "transmission", 90.0)) / 100.0, 0.0), 1.0)
        routes = {"in": (("out", t), ("refl", 1.0 - t)), "out": (("in", t),)}
        return [Transfer(in_port, out, scalar(math.sqrt(power)), local_to_world(part, part.light_path(in_port, out)),
                         index_of(part, in_port))
                for out, power in routes.get(in_port, ()) if out in part.ports()]


@register("RoofMirror")
class Roof(Behaviour):
    """Light that enters ``in`` meets both faces and leaves ``out`` (and back): two reflections, so the field keeps
    its frame, and each face keeps ``reflectance`` of the power."""

    def transfers(self, part, sid, in_port, wavelength_nm, params):
        if in_port not in ("in", "out"):
            return []
        out = "out" if in_port == "in" else "in"
        r = float(getattr(part, "reflectance", 0.99))
        return [Transfer(in_port, out, scalar(r), local_to_world(part, part.light_path(in_port, out)),
                         index_of(part, in_port))]
