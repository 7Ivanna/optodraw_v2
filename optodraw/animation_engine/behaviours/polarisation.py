"""Polarisation optics: Jones matrices from optodraw.core.polarization; projections; on-chip rotators."""

from __future__ import annotations

import math

import numpy as np

from optodraw.core.polarization import half_wave_plate, jones_matrix_from_component, polarizer_matrix, quarter_wave_plate

from . import Behaviour, Transfer, register
from .geometry import drawn_points, index_of, straight, through_anchor

_H = np.array([[1, 0], [0, 0]], dtype=complex)
_V = np.array([[0, 0], [0, 1]], dtype=complex)
_Y_TO_X = np.array([[0, 1], [0, 0]], dtype=complex)        # the y field leaves as the x (TE) field
_X_TO_Y = np.array([[0, 0], [1, 0]], dtype=complex)
_ROTATE_90 = np.array([[0, -1], [1, 0]], dtype=complex)
_FLIP = np.array([[1, 0], [0, -1]], dtype=complex)            # the frame a mirror leaves: y flipped (passive.Reflector)


@register("Polarizer", "Analyzer", "HalfWavePlate", "QuarterWavePlate", "WavePlate")
class JonesTwoPort(Behaviour):
    def matrix(self, part, sid, wavelength_nm, params) -> np.ndarray:
        angle = params.get(f"angle:{sid}")
        ctype = part.component_type
        if angle is not None:
            if ctype in ("Polarizer", "Analyzer"):
                ratio = max(float(getattr(part, "extinction_ratio", 1000.0)), 1.0)
                return polarizer_matrix(float(angle), 10.0 * math.log10(ratio)).as_array()
            if ctype == "HalfWavePlate":
                return half_wave_plate(float(angle)).as_array()
            if ctype == "QuarterWavePlate":
                return quarter_wave_plate(float(angle)).as_array()
        found = jones_matrix_from_component(part, wavelength_nm=wavelength_nm)
        return np.eye(2, dtype=complex) if found is None else found.as_array()

    def transfers(self, part, sid, in_port, wavelength_nm, params):
        if in_port not in ("in", "out"):
            return []
        out = "out" if in_port == "in" else "in"
        m = self.matrix(part, sid, wavelength_nm, params)
        if in_port == "out":            # seen from behind, in the frame a mirror leaves (y flipped): F J^T F
            m = _FLIP @ m.T @ _FLIP
        return [Transfer(in_port, out, m, through_anchor(part, in_port, out), index_of(part, in_port))]


@register("PBS")
class PolarisingSplitter(Behaviour):
    # The coating runs from the in-tap corner to the trans-refl corner: H passes straight, V turns.
    _ROUTES = {"in": (("trans", _H), ("refl", _V)), "tap": (("refl", _H), ("trans", _V)),
               "trans": (("in", _H), ("tap", _V)), "refl": (("in", _V), ("tap", _H))}

    def transfers(self, part, sid, in_port, wavelength_nm, params):
        return [Transfer(in_port, out, m, through_anchor(part, in_port, out), index_of(part, in_port))
                for out, m in self._ROUTES.get(in_port, ()) if out in part.ports()]


@register("GlanLaserPolarizer")
class GlanPrism(Behaviour):
    """p (H) passes straight from in to out; s (V) leaves through the side window."""

    _ROUTES = {"in": (("out", _H), ("reject", _V)), "out": (("in", _H),), "reject": (("in", _V),)}

    def transfers(self, part, sid, in_port, wavelength_nm, params):
        return [Transfer(in_port, out, m, through_anchor(part, in_port, out), index_of(part, in_port))
                for out, m in self._ROUTES.get(in_port, ())]


@register("WollastonPrism")
class Wollaston(Behaviour):
    """H leaves at o, above the axis; V leaves at e, below it; and back."""

    _ROUTES = {"in": (("o", _H), ("e", _V)), "o": (("in", _H),), "e": (("in", _V),)}

    def transfers(self, part, sid, in_port, wavelength_nm, params):
        return [Transfer(in_port, out, m, through_anchor(part, in_port, out), index_of(part, in_port))
                for out, m in self._ROUTES.get(in_port, ())]


@register("PolarizationRotator")
class Rotator(Behaviour):
    def transfers(self, part, sid, in_port, wavelength_nm, params):
        if in_port not in ("o1", "o2"):
            return []
        out = "o2" if in_port == "o1" else "o1"
        matrix = _ROTATE_90 if in_port == "o1" else _ROTATE_90.T
        return [Transfer(in_port, out, matrix, drawn_points(part, in_port, out, straight(part, in_port, out)), index_of(part, in_port))]


@register("PolarizationSplitterRotator")
class SplitterRotator(Behaviour):
    """TE goes on in o2; TM is turned into TE and leaves in o3."""

    _ROUTES = {"o1": (("o2", _H), ("o3", _Y_TO_X)), "o2": (("o1", _H),), "o3": (("o1", _X_TO_Y),)}

    def transfers(self, part, sid, in_port, wavelength_nm, params):
        return [Transfer(in_port, out, m, drawn_points(part, in_port, out, straight(part, in_port, out)), index_of(part, in_port))
                for out, m in self._ROUTES.get(in_port, ())]


@register("TwoDGratingCoupler")
class TwoDGrating(Behaviour):
    """The fibre's x field couples into o1, its y field into o2 (as TE); and back."""

    def transfers(self, part, sid, in_port, wavelength_nm, params):
        eta = math.sqrt(float(getattr(part, "coupling_efficiency", 0.5)))
        routes = {"f1": (("o1", _H), ("o2", _Y_TO_X)), "o1": (("f1", _H),), "o2": (("f1", _X_TO_Y),)}
        return [Transfer(in_port, out, m * eta, drawn_points(part, in_port, out, straight(part, in_port, out)), index_of(part, in_port))
                for out, m in routes.get(in_port, ())]


@register("FaradayRotator")
class Faraday(Behaviour):
    """The rod turns the polarization by ``rotation_deg`` about the magnet's field, whichever way the light runs.

    A mirror turns the engine's frame (it flips y), so in that frame the pass back from ``out`` is the transposed
    turn. Two passes then add, as a Faraday rotator's do; a wave plate's two passes cancel."""

    def transfers(self, part, sid, in_port, wavelength_nm, params):
        if in_port not in ("in", "out"):
            return []
        turn = math.radians(float(getattr(part, "rotation_deg", 45.0)))
        c, s = math.cos(turn), math.sin(turn)
        forward = np.array([[c, -s], [s, c]], dtype=complex)
        out = "out" if in_port == "in" else "in"
        return [Transfer(in_port, out, forward if in_port == "in" else forward.T,
                         through_anchor(part, in_port, out), index_of(part, in_port))]
