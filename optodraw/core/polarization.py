"""Jones- and Mueller-matrix polarization stubs for free-space component chains."""

from __future__ import annotations

import cmath
import math
from dataclasses import dataclass
from typing import Any, Iterable

import numpy as np


def _as_complex(value: complex | float) -> complex:
    result = value if isinstance(value, complex) else complex(float(value))
    if not math.isfinite(result.real) or not math.isfinite(result.imag):
        raise ValueError("Jones values must be finite")
    return result


def _rotation_matrix(angle_deg: float) -> np.ndarray:
    theta = math.radians(angle_deg)
    cos_t = math.cos(theta)
    sin_t = math.sin(theta)
    return np.array([[cos_t, sin_t], [-sin_t, cos_t]], dtype=complex)


@dataclass(frozen=True)
class JonesVector:
    """Jones vector with Ex and Ey field components (complex or real linear stub)."""

    Ex: complex
    Ey: complex

    def __post_init__(self) -> None:
        object.__setattr__(self, "Ex", _as_complex(self.Ex))
        object.__setattr__(self, "Ey", _as_complex(self.Ey))

    @classmethod
    def linear(cls, angle_deg: float, *, amplitude: float = 1.0) -> JonesVector:
        """Build a linearly polarized Jones vector at ``angle_deg`` from +x."""

        theta = math.radians(angle_deg)
        amp = float(amplitude)
        return cls(Ex=amp * math.cos(theta), Ey=amp * math.sin(theta))

    @classmethod
    def unpolarized_stub(cls, *, amplitude: float = 1.0) -> JonesVector:
        """Diagram-level unpolarized stub as equal in-phase x/y components."""

        amp = float(amplitude) / math.sqrt(2.0)
        return cls(Ex=amp, Ey=amp)

    def as_tuple(self) -> tuple[complex, complex]:
        return (self.Ex, self.Ey)

    def as_array(self) -> np.ndarray:
        return np.array([self.Ex, self.Ey], dtype=complex)

    def intensity(self) -> float:
        return float(abs(self.Ex) ** 2 + abs(self.Ey) ** 2)

    def normalized(self) -> JonesVector:
        norm = math.sqrt(self.intensity())
        if norm <= 0.0:
            return JonesVector(0.0, 0.0)
        return JonesVector(self.Ex / norm, self.Ey / norm)

    def stokes(self) -> tuple[float, float, float, float]:
        """Return simplified Stokes parameters (S0, S1, S2, S3)."""

        s0 = abs(self.Ex) ** 2 + abs(self.Ey) ** 2
        s1 = abs(self.Ex) ** 2 - abs(self.Ey) ** 2
        cross = self.Ex * self.Ey.conjugate()
        s2 = 2.0 * cross.real
        s3 = 2.0 * cross.imag
        return (float(s0), float(s1), float(s2), float(s3))

    def __matmul__(self, other: JonesMatrix) -> JonesVector:
        if not isinstance(other, JonesMatrix):
            return NotImplemented
        return other.apply(self)


@dataclass(frozen=True)
class JonesMatrix:
    """2x2 Jones matrix with ``@`` multiply for vectors and matrix composition."""

    m00: complex
    m01: complex
    m10: complex
    m11: complex

    def __post_init__(self) -> None:
        object.__setattr__(self, "m00", _as_complex(self.m00))
        object.__setattr__(self, "m01", _as_complex(self.m01))
        object.__setattr__(self, "m10", _as_complex(self.m10))
        object.__setattr__(self, "m11", _as_complex(self.m11))

    @classmethod
    def identity(cls) -> JonesMatrix:
        return cls(1.0, 0.0, 0.0, 1.0)

    @classmethod
    def zeros(cls) -> JonesMatrix:
        return cls(0.0, 0.0, 0.0, 0.0)

    @classmethod
    def from_array(cls, array: np.ndarray | Iterable[Iterable[complex | float]]) -> JonesMatrix:
        arr = np.asarray(array, dtype=complex)
        if arr.shape != (2, 2):
            raise ValueError("Jones matrix must be 2x2")
        return cls(arr[0, 0], arr[0, 1], arr[1, 0], arr[1, 1])

    def as_array(self) -> np.ndarray:
        return np.array([[self.m00, self.m01], [self.m10, self.m11]], dtype=complex)

    def apply(self, jones: JonesVector) -> JonesVector:
        arr = self.as_array() @ jones.as_array()
        return JonesVector(arr[0], arr[1])

    def __matmul__(self, other: JonesVector | JonesMatrix) -> JonesVector | JonesMatrix:
        if isinstance(other, JonesVector):
            return self.apply(other)
        if isinstance(other, JonesMatrix):
            return JonesMatrix.from_array(self.as_array() @ other.as_array())
        return NotImplemented


def polarizer_matrix(axis_angle_deg: float, extinction_ratio_db: float) -> JonesMatrix:
    """Ideal linear polarizer with finite extinction (dB)."""

    eps = 10.0 ** (-float(extinction_ratio_db) / 20.0)
    axis = float(axis_angle_deg)
    cos_t = math.cos(math.radians(axis))
    sin_t = math.sin(math.radians(axis))
    cos2 = cos_t ** 2
    sin2 = sin_t ** 2
    sin_cos = sin_t * cos_t
    return JonesMatrix(
        cos2 + eps * sin2,
        (1.0 - eps) * sin_cos,
        (1.0 - eps) * sin_cos,
        sin2 + eps * cos2,
    )


def _scale_retardance(
    retardance_rad: float,
    *,
    wavelength_nm: float | None,
    design_wavelength_nm: float | None,
) -> float:
    """Scale retardance when operating away from the design wavelength."""

    if wavelength_nm is not None and (
        not math.isfinite(float(wavelength_nm)) or float(wavelength_nm) <= 0.0
    ):
        raise ValueError("wavelength_nm must be a finite positive number")
    if design_wavelength_nm is not None and (
        not math.isfinite(float(design_wavelength_nm)) or float(design_wavelength_nm) <= 0.0
    ):
        raise ValueError("design_wavelength_nm must be a finite positive number")
    if wavelength_nm is None or design_wavelength_nm is None:
        return float(retardance_rad)
    return float(retardance_rad) * float(design_wavelength_nm) / float(wavelength_nm)


def wave_plate_matrix(
    fast_axis_deg: float,
    retardance_rad: float,
    *,
    wavelength_nm: float | None = None,
    design_wavelength_nm: float | None = None,
) -> JonesMatrix:
    """Generic retarder with fast axis at ``fast_axis_deg``."""

    delta = complex(
        _scale_retardance(
            retardance_rad,
            wavelength_nm=wavelength_nm,
            design_wavelength_nm=design_wavelength_nm,
        )
    )
    phase = cmath.exp(1j * delta)
    local = JonesMatrix.from_array(np.diag([1.0, phase]))
    rot_in = JonesMatrix.from_array(_rotation_matrix(fast_axis_deg))
    rot_out = JonesMatrix.from_array(_rotation_matrix(-fast_axis_deg))
    return rot_out @ local @ rot_in


def half_wave_plate(
    fast_axis_deg: float,
    *,
    wavelength_nm: float | None = None,
    design_wavelength_nm: float | None = None,
) -> JonesMatrix:
    return wave_plate_matrix(
        fast_axis_deg,
        math.pi,
        wavelength_nm=wavelength_nm,
        design_wavelength_nm=design_wavelength_nm,
    )


def quarter_wave_plate(
    fast_axis_deg: float,
    *,
    wavelength_nm: float | None = None,
    design_wavelength_nm: float | None = None,
) -> JonesMatrix:
    return wave_plate_matrix(
        fast_axis_deg,
        math.pi / 2.0,
        wavelength_nm=wavelength_nm,
        design_wavelength_nm=design_wavelength_nm,
    )


def pbs_matrix() -> JonesMatrix:
    """Polarizing beam splitter stub: transmit horizontal, block vertical."""

    return JonesMatrix(1.0, 0.0, 0.0, 0.0)


def pbs_reflected_matrix() -> JonesMatrix:
    """PBS reflected port stub: transmit vertical, block horizontal."""

    return JonesMatrix(0.0, 0.0, 0.0, 1.0)


def _linear_extinction_db(extinction_ratio: float) -> float:
    ratio = float(extinction_ratio)
    if ratio <= 1.0:
        return 0.0
    return 10.0 * math.log10(ratio)


def _component_metadata(component: Any) -> dict[str, Any]:
    if hasattr(component, "physics_metadata"):
        return component.physics_metadata()
    return {}


def jones_matrix_from_component(component: Any, *, wavelength_nm: float | None = None) -> JonesMatrix | None:
    """Build a Jones matrix from a component's physics metadata when supported."""

    metadata = _component_metadata(component)
    component_kind = metadata.get("component", "")
    component_type = getattr(component, "component_type", component.__class__.__name__)

    if component_kind in {"linear_polarizer", "analyzer"}:
        axis = metadata.get("axis_angle", getattr(component, "axis_angle", 0.0))
        er = metadata.get("extinction_ratio", getattr(component, "extinction_ratio", 1000.0))
        return polarizer_matrix(float(axis), _linear_extinction_db(float(er)))

    if component_kind == "wave_plate" or component_type in {
        "WavePlate",
        "HalfWavePlate",
        "QuarterWavePlate",
    }:
        fast_axis = metadata.get(
            "fast_axis_angle",
            getattr(component, "fast_axis_angle", 0.0),
        )
        retardance = metadata.get("retardance", getattr(component, "retardance", math.pi))
        design_wavelength_nm = metadata.get(
            "design_wavelength_nm",
            getattr(component, "design_wavelength_nm", None),
        )
        if component_type == "HalfWavePlate":
            retardance = math.pi
        elif component_type == "QuarterWavePlate":
            retardance = math.pi / 2.0
        wp_kwargs = {
            "wavelength_nm": wavelength_nm,
            "design_wavelength_nm": design_wavelength_nm,
        }
        if abs(float(retardance) - math.pi) < 1e-9:
            return half_wave_plate(float(fast_axis), **wp_kwargs)
        if abs(float(retardance) - math.pi / 2.0) < 1e-9:
            return quarter_wave_plate(float(fast_axis), **wp_kwargs)
        return wave_plate_matrix(float(fast_axis), float(retardance), **wp_kwargs)

    if component_kind == "polarizing_beam_splitter" or component_type == "PBS":
        return pbs_matrix()

    return None


@dataclass(frozen=True)
class PolarizationTraceResult:
    """Result of a Jones-vector walk through ordered polarization components."""

    jones: JonesVector
    stokes: tuple[float, float, float, float]
    components_applied: tuple[str, ...]
    warnings: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "jones": {"Ex": self.jones.Ex, "Ey": self.jones.Ey},
            "stokes": {
                "S0": self.stokes[0],
                "S1": self.stokes[1],
                "S2": self.stokes[2],
                "S3": self.stokes[3],
            },
            "intensity": self.jones.intensity(),
            "components_applied": list(self.components_applied),
            "warnings": list(self.warnings),
        }


def trace_jones_through(
    components: Iterable,
    jones_in: JonesVector | None = None,
    *,
    wavelength_nm: float = 633.0,
    unpolarized: bool = False,
) -> PolarizationTraceResult:
    """Walk ordered free-space components and apply Jones matrices where available."""

    if unpolarized:
        raise ValueError("Jones vectors cannot represent unpolarized light; use trace_stokes_through(unpolarized=True)")
    if jones_in is None:
        state = JonesVector.linear(0.0)
    else:
        state = jones_in

    applied: list[str] = []
    trace_warnings: list[str] = []

    for component in components:
        component_type = getattr(component, "component_type", component.__class__.__name__)
        matrix = jones_matrix_from_component(component, wavelength_nm=wavelength_nm)
        if matrix is None:
            trace_warnings.append(
                f"{component_type} lacks polarization Jones support; state unchanged."
            )
            continue
        state = matrix @ state
        applied.append(component_type)

    return PolarizationTraceResult(
        jones=state,
        stokes=state.stokes(),
        components_applied=tuple(applied),
        warnings=tuple(trace_warnings),
    )


# ---------------------------------------------------------------------------
# Stokes / Mueller calculus (Tier 3 slice 3)
# ---------------------------------------------------------------------------

_SIGMA0 = np.array([[1.0, 0.0], [0.0, 1.0]], dtype=complex)
_SIGMA1 = np.array([[1.0, 0.0], [0.0, -1.0]], dtype=complex)
_SIGMA2 = np.array([[0.0, 1.0], [1.0, 0.0]], dtype=complex)
_SIGMA3 = np.array([[0.0, -1.0j], [1.0j, 0.0]], dtype=complex)
_SIGMAS = (_SIGMA0, _SIGMA1, _SIGMA2, _SIGMA3)


@dataclass(frozen=True)
class StokesVector:
    """Stokes vector (S0, S1, S2, S3) in the same convention as :meth:`JonesVector.stokes`."""

    S0: float
    S1: float
    S2: float
    S3: float

    def __post_init__(self) -> None:
        values = self.as_tuple()
        if not all(math.isfinite(value) for value in values) or self.S0 < 0:
            raise ValueError("Stokes parameters must be finite with non-negative S0")
        polarized = math.sqrt(self.S1 ** 2 + self.S2 ** 2 + self.S3 ** 2)
        if polarized > self.S0 * (1.0 + 1e-9) + 1e-12:
            raise ValueError("Stokes polarization magnitude cannot exceed S0")

    @classmethod
    def unpolarized(cls, *, intensity: float = 1.0) -> StokesVector:
        return cls(float(intensity), 0.0, 0.0, 0.0)

    @classmethod
    def linear_horizontal(cls, *, intensity: float = 1.0) -> StokesVector:
        i = float(intensity)
        return cls(i, i, 0.0, 0.0)

    def as_tuple(self) -> tuple[float, float, float, float]:
        return (self.S0, self.S1, self.S2, self.S3)

    def as_array(self) -> np.ndarray:
        return np.array([self.S0, self.S1, self.S2, self.S3], dtype=float)

    def intensity(self) -> float:
        return float(self.S0)

    def degree_of_polarization(self) -> float:
        if self.S0 <= 0.0:
            return 0.0
        return math.sqrt(self.S1 ** 2 + self.S2 ** 2 + self.S3 ** 2) / self.S0

    def normalized(self) -> StokesVector:
        if self.S0 <= 0.0:
            return StokesVector(0.0, 0.0, 0.0, 0.0)
        return StokesVector(1.0, self.S1 / self.S0, self.S2 / self.S0, self.S3 / self.S0)


def jones_to_stokes(jones: JonesVector) -> StokesVector:
    s0, s1, s2, s3 = jones.stokes()
    return StokesVector(s0, s1, s2, s3)


def stokes_to_jones(stokes: StokesVector) -> JonesVector:
    """Convert a fully polarized Stokes vector back to a Jones vector (partial inverse)."""

    s0, s1, s2, s3 = stokes.as_tuple()
    if s0 <= 0.0:
        return JonesVector(0.0, 0.0)

    dop = math.sqrt(s1 ** 2 + s2 ** 2 + s3 ** 2) / s0
    if dop < 1.0 - 1e-6:
        raise ValueError("stokes_to_jones supports fully polarized states only (DOP ≈ 1)")

    ex2 = max(0.0, (s0 + s1) / 2.0)
    ey2 = max(0.0, (s0 - s1) / 2.0)
    ex = math.sqrt(ex2)
    if ey2 <= 0.0:
        return JonesVector(ex, 0.0)

    phi = math.atan2(s3, s2)
    ey = math.sqrt(ey2) * complex(math.cos(phi), -math.sin(phi))
    return JonesVector(ex, ey)


def jones_to_mueller(jones: JonesMatrix) -> "MuellerMatrix":
    """Build a Mueller matrix from a Jones matrix (coherent / fully polarized model)."""

    j_arr = jones.as_array()
    m = np.zeros((4, 4), dtype=float)
    for i in range(4):
        for j in range(4):
            m[i, j] = 0.5 * float(np.real(np.trace(_SIGMAS[i] @ j_arr @ _SIGMAS[j] @ j_arr.conj().T)))
    return MuellerMatrix.from_array(m)


@dataclass(frozen=True)
class MuellerMatrix:
    """4x4 Mueller matrix with ``@`` multiply for Stokes vectors and matrix composition."""

    m00: float
    m01: float
    m02: float
    m03: float
    m10: float
    m11: float
    m12: float
    m13: float
    m20: float
    m21: float
    m22: float
    m23: float
    m30: float
    m31: float
    m32: float
    m33: float

    @classmethod
    def identity(cls) -> MuellerMatrix:
        return cls.from_array(np.eye(4, dtype=float))

    @classmethod
    def from_array(cls, array: np.ndarray | Iterable[Iterable[float]]) -> MuellerMatrix:
        arr = np.asarray(array, dtype=float)
        if arr.shape != (4, 4):
            raise ValueError("Mueller matrix must be 4x4")
        return cls(
            arr[0, 0], arr[0, 1], arr[0, 2], arr[0, 3],
            arr[1, 0], arr[1, 1], arr[1, 2], arr[1, 3],
            arr[2, 0], arr[2, 1], arr[2, 2], arr[2, 3],
            arr[3, 0], arr[3, 1], arr[3, 2], arr[3, 3],
        )

    def as_array(self) -> np.ndarray:
        return np.array(
            [
                [self.m00, self.m01, self.m02, self.m03],
                [self.m10, self.m11, self.m12, self.m13],
                [self.m20, self.m21, self.m22, self.m23],
                [self.m30, self.m31, self.m32, self.m33],
            ],
            dtype=float,
        )

    def apply(self, stokes: StokesVector) -> StokesVector:
        out = self.as_array() @ stokes.as_array()
        return StokesVector(out[0], out[1], out[2], out[3])

    def __matmul__(self, other: StokesVector | MuellerMatrix) -> StokesVector | MuellerMatrix:
        if isinstance(other, StokesVector):
            return self.apply(other)
        if isinstance(other, MuellerMatrix):
            return MuellerMatrix.from_array(self.as_array() @ other.as_array())
        return NotImplemented


def polarizer_mueller(axis_angle_deg: float, extinction_ratio_db: float) -> MuellerMatrix:
    return jones_to_mueller(polarizer_matrix(axis_angle_deg, extinction_ratio_db))


def wave_plate_mueller(
    fast_axis_deg: float,
    retardance_rad: float,
    *,
    wavelength_nm: float | None = None,
    design_wavelength_nm: float | None = None,
) -> MuellerMatrix:
    return jones_to_mueller(
        wave_plate_matrix(
            fast_axis_deg,
            retardance_rad,
            wavelength_nm=wavelength_nm,
            design_wavelength_nm=design_wavelength_nm,
        )
    )


def beam_splitter_mueller(
    split_ratio: tuple[float, float] = (0.5, 0.5),
    *,
    depolarization: float = 0.0,
) -> MuellerMatrix:
    """PBS Mueller stub with optional partial depolarization mixing."""

    transmitted = jones_to_mueller(pbs_matrix())
    reflected = jones_to_mueller(pbs_reflected_matrix())
    t_frac, r_frac = float(split_ratio[0]), float(split_ratio[1])
    total = t_frac + r_frac
    if total <= 0.0:
        t_frac, r_frac = 0.5, 0.5
        total = 1.0
    t_frac /= total
    r_frac /= total
    combined = MuellerMatrix.from_array(
        t_frac * transmitted.as_array() + r_frac * reflected.as_array()
    )
    depol = max(0.0, min(1.0, float(depolarization)))
    if depol <= 0.0:
        return combined
    depolarizer = np.diag([1.0, 1.0 - depol, 1.0 - depol, 1.0 - depol])
    return MuellerMatrix.from_array(depolarizer @ combined.as_array())


def mueller_matrix_from_component(component: Any, *, wavelength_nm: float | None = None) -> MuellerMatrix | None:
    """Build a Mueller matrix from a component's physics metadata when supported."""

    metadata = _component_metadata(component)
    component_kind = metadata.get("component", "")
    component_type = getattr(component, "component_type", component.__class__.__name__)

    if component_kind in {"linear_polarizer", "analyzer"}:
        axis = metadata.get("axis_angle", getattr(component, "axis_angle", 0.0))
        er = metadata.get("extinction_ratio", getattr(component, "extinction_ratio", 1000.0))
        return polarizer_mueller(float(axis), _linear_extinction_db(float(er)))

    if component_kind == "wave_plate" or component_type in {
        "WavePlate",
        "HalfWavePlate",
        "QuarterWavePlate",
    }:
        fast_axis = metadata.get(
            "fast_axis_angle",
            getattr(component, "fast_axis_angle", 0.0),
        )
        retardance = metadata.get("retardance", getattr(component, "retardance", math.pi))
        design_wavelength_nm = metadata.get(
            "design_wavelength_nm",
            getattr(component, "design_wavelength_nm", None),
        )
        if component_type == "HalfWavePlate":
            retardance = math.pi
        elif component_type == "QuarterWavePlate":
            retardance = math.pi / 2.0
        return wave_plate_mueller(
            float(fast_axis),
            float(retardance),
            wavelength_nm=wavelength_nm,
            design_wavelength_nm=design_wavelength_nm,
        )

    if component_kind == "polarizing_beam_splitter" or component_type == "PBS":
        split_ratio = metadata.get("split_ratio", getattr(component, "split_ratio", (0.5, 0.5)))
        return beam_splitter_mueller(tuple(split_ratio))

    return None


def _pbs_split_ratio(component: Any) -> tuple[float, float]:
    metadata = _component_metadata(component)
    ratio = metadata.get("split_ratio", getattr(component, "split_ratio", (0.5, 0.5)))
    t_frac, r_frac = float(ratio[0]), float(ratio[1])
    total = t_frac + r_frac
    if total <= 0.0:
        return (0.5, 0.5)
    return (t_frac / total, r_frac / total)


def pbs_routing_annotation(
    component: Any,
    stokes_in: StokesVector,
) -> dict[str, Any]:
    """Beam-routing annotation stub for a PBS without full NSS branching."""

    split_ratio = _pbs_split_ratio(component)
    m_t = jones_to_mueller(pbs_matrix())
    m_r = jones_to_mueller(pbs_reflected_matrix())
    t_stokes = m_t.apply(stokes_in)
    r_stokes = m_r.apply(stokes_in)
    transmitted_power = t_stokes.intensity()
    reflected_power = r_stokes.intensity()
    powers = {
        "transmitted": transmitted_power,
        "reflected": reflected_power,
        "p": transmitted_power,
        "s": reflected_power,
    }
    return {
        "component": getattr(component, "component_type", component.__class__.__name__),
        "split_ratio": split_ratio,
        "power_fractions": powers,
        "transmitted": {"stokes": t_stokes, "power_fraction": powers["transmitted"]},
        "reflected": {"stokes": r_stokes, "power_fraction": powers["reflected"]},
        "p": {"stokes": t_stokes, "power_fraction": powers["p"]},
        "s": {"stokes": r_stokes, "power_fraction": powers["s"]},
    }


@dataclass(frozen=True)
class StokesTraceResult:
    """Result of a Mueller/Stokes walk through ordered polarization components."""

    stokes: StokesVector
    components_applied: tuple[str, ...]
    warnings: tuple[str, ...]
    dual_outputs: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "stokes": {
                "S0": self.stokes.S0,
                "S1": self.stokes.S1,
                "S2": self.stokes.S2,
                "S3": self.stokes.S3,
            },
            "intensity": self.stokes.intensity(),
            "degree_of_polarization": self.stokes.degree_of_polarization(),
            "components_applied": list(self.components_applied),
            "warnings": list(self.warnings),
        }
        if self.dual_outputs is not None:
            payload["dual_outputs"] = self.dual_outputs
        return payload


def trace_stokes_through(
    components: Iterable,
    stokes_in: StokesVector | None = None,
    *,
    wavelength_nm: float = 633.0,
    unpolarized: bool = False,
) -> StokesTraceResult:
    """Walk ordered free-space components and apply Mueller matrices where available."""

    if stokes_in is None:
        state = StokesVector.unpolarized() if unpolarized else StokesVector.linear_horizontal()
    else:
        state = stokes_in

    applied: list[str] = []
    trace_warnings: list[str] = []
    dual_outputs: dict[str, Any] | None = None

    for component in components:
        component_type = getattr(component, "component_type", component.__class__.__name__)
        metadata = _component_metadata(component)
        component_kind = metadata.get("component", "")

        if component_kind == "polarizing_beam_splitter" or component_type == "PBS":
            routing = pbs_routing_annotation(component, state)
            dual_outputs = {
                "transmitted": routing["transmitted"],
                "reflected": routing["reflected"],
                "p": routing["p"],
                "s": routing["s"],
                "split_ratio": routing["split_ratio"],
                "power_fractions": routing["power_fractions"],
            }
            state = routing["transmitted"]["stokes"]
            applied.append(component_type)
            continue

        matrix = mueller_matrix_from_component(component, wavelength_nm=wavelength_nm)
        if matrix is None:
            trace_warnings.append(
                f"{component_type} lacks polarization Mueller support; state unchanged."
            )
            continue
        state = matrix @ state
        applied.append(component_type)

    return StokesTraceResult(
        stokes=state,
        components_applied=tuple(applied),
        warnings=tuple(trace_warnings),
        dual_outputs=dual_outputs,
    )


def validate_polarization_chain(components: Iterable) -> list[str]:
    """Return warnings for components that lack declared polarization / Mueller support."""

    from optodraw.registry import component_registry

    registry = component_registry()
    warnings_out: list[str] = []
    seen: set[str] = set()
    for component in components:
        component_type = getattr(component, "component_type", component.__class__.__name__)
        if component_type in seen:
            continue
        seen.add(component_type)
        spec = registry.get(component_type)
        if spec is None:
            warnings_out.append(f"{component_type} is not registered; polarization support unknown.")
            continue
        if "polarization" not in spec.physics_modes:
            warnings_out.append(
                f"{component_type} does not declare polarization physics support "
                f"(modes={list(spec.physics_modes)})."
            )
            continue
        if mueller_matrix_from_component(component) is None:
            warnings_out.append(
                f"{component_type} declares polarization support but lacks a Mueller matrix stub."
            )
    return warnings_out


def stokes_annotation_stub(stokes: StokesVector) -> str:
    """Short tutoring label for a Stokes state (ellipse annotation stub)."""

    s0, s1, s2, s3 = stokes.as_tuple()
    if s0 <= 1e-12:
        return "dark"
    dop = stokes.degree_of_polarization()
    if dop < 0.05:
        return "unpolarized"
    if abs(s3) > 0.1 * s0 and abs(s1) < 0.1 * s0 and abs(s2) < 0.1 * s0:
        return "circular"
    if abs(s3) < 0.05 * s0:
        angle = 0.5 * math.degrees(math.atan2(s2, s1))
        return f"linear {angle:.0f}°"
    return "elliptical"
