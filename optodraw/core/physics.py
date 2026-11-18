"""Paraxial optics and Gaussian beam propagation helpers."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable

from optodraw.core.beam import Beam
from optodraw.core.transform import Vec3, as_vec3 as _as_vec3


@dataclass(frozen=True)
class ABCDMatrix:
    """A first-order optical ray-transfer matrix."""

    a: float
    b: float
    c: float
    d: float
    label: str = ""

    def __matmul__(self, other: "ABCDMatrix") -> "ABCDMatrix":
        return ABCDMatrix(
            self.a * other.a + self.b * other.c,
            self.a * other.b + self.b * other.d,
            self.c * other.a + self.d * other.c,
            self.c * other.b + self.d * other.d,
            label=" @ ".join(part for part in (self.label, other.label) if part),
        )

    def apply_q(self, q_parameter: complex) -> complex:
        """Apply the matrix to a Gaussian-beam q parameter."""

        denominator = self.c * q_parameter + self.d
        if abs(denominator) < 1e-15:
            raise ZeroDivisionError("ABCD matrix maps the Gaussian q parameter to infinity.")
        return (self.a * q_parameter + self.b) / denominator

    def to_tuple(self) -> tuple[tuple[float, float], tuple[float, float]]:
        """Return the matrix as nested row tuples."""

        return ((self.a, self.b), (self.c, self.d))


def free_space_matrix(length: float) -> ABCDMatrix:
    """Return the ABCD matrix for propagation through a uniform medium."""

    distance = float(length)
    if not math.isfinite(distance):
        raise ValueError("length must be finite")
    return ABCDMatrix(1.0, distance, 0.0, 1.0, label=f"free_space({distance:g})")


def thin_lens_matrix(focal_length: float) -> ABCDMatrix:
    """Return the ABCD matrix for an ideal thin lens."""

    focal = float(focal_length)
    if not math.isfinite(focal) or abs(focal) < 1e-15:
        raise ValueError("focal_length must be finite and non-zero")
    return ABCDMatrix(1.0, 0.0, -1.0 / focal, 1.0, label=f"thin_lens({focal:g})")


@dataclass(frozen=True)
class GaussianBeamState:
    """Gaussian beam state at one transverse plane.

    ``wavelength``, ``waist_radius``, distances, and component positions must
    use the same length unit. For micron-scale layouts use values like
    ``wavelength=0.633`` for a 633 nm beam.
    """

    wavelength: float = 0.633
    waist_radius: float = 1.0
    z_from_waist: float = 0.0
    refractive_index: float = 1.0
    power: float | None = None
    label: str = ""

    def __post_init__(self) -> None:
        for name in ("wavelength", "waist_radius", "refractive_index"):
            value = getattr(self, name)
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be positive and finite")
        if not math.isfinite(self.z_from_waist):
            raise ValueError("z_from_waist must be finite")
        if self.power is not None and (not math.isfinite(self.power) or self.power < 0):
            raise ValueError("power must be non-negative and finite")

    @property
    def rayleigh_range(self) -> float:
        """Distance over which the beam radius grows by ``sqrt(2)``."""

        return math.pi * self.refractive_index * self.waist_radius**2 / self.wavelength

    @property
    def q_parameter(self) -> complex:
        """Complex Gaussian q parameter at this plane."""

        return complex(self.z_from_waist, self.rayleigh_range)

    @property
    def beam_radius(self) -> float:
        """Current 1/e^2 intensity radius of the Gaussian beam."""

        ratio = self.z_from_waist / self.rayleigh_range
        return self.waist_radius * math.sqrt(1.0 + ratio * ratio)

    @property
    def wavefront_radius(self) -> float:
        """Radius of curvature for the phase front, or infinity at the waist."""

        if abs(self.z_from_waist) < 1e-15:
            return math.inf
        ratio = self.rayleigh_range / self.z_from_waist
        return self.z_from_waist * (1.0 + ratio * ratio)

    @property
    def divergence_rad(self) -> float:
        """Far-field half-angle divergence in radians."""

        return self.wavelength / (math.pi * self.refractive_index * self.waist_radius)

    @classmethod
    def from_q(
        cls,
        q_parameter: complex,
        *,
        wavelength: float,
        refractive_index: float = 1.0,
        power: float | None = None,
        label: str = "",
    ) -> "GaussianBeamState":
        """Construct a beam state from a complex q parameter."""

        rayleigh_range = q_parameter.imag
        if not math.isfinite(rayleigh_range) or rayleigh_range < 1e-15:
            raise ValueError("q_parameter must have a positive finite imaginary part")
        if not math.isfinite(wavelength) or wavelength <= 0:
            raise ValueError("wavelength must be positive and finite")
        if not math.isfinite(refractive_index) or refractive_index <= 0:
            raise ValueError("refractive_index must be positive and finite")
        waist_radius = math.sqrt(wavelength * rayleigh_range / (math.pi * refractive_index))
        return cls(
            wavelength=wavelength,
            waist_radius=waist_radius,
            z_from_waist=q_parameter.real,
            refractive_index=refractive_index,
            power=power,
            label=label,
        )

    def propagate(self, matrix: ABCDMatrix) -> "GaussianBeamState":
        """Return the state after applying an ABCD matrix."""

        return self.from_q(
            matrix.apply_q(self.q_parameter),
            wavelength=self.wavelength,
            refractive_index=self.refractive_index,
            power=self.power,
            label=self.label,
        )

    def propagate_free_space(self, length: float) -> "GaussianBeamState":
        """Return the state after free-space propagation by ``length``."""

        return self.propagate(free_space_matrix(length))

    def through_thin_lens(self, focal_length: float) -> "GaussianBeamState":
        """Return the state immediately after an ideal thin lens."""

        return self.propagate(thin_lens_matrix(focal_length))

    def to_dict(self) -> dict[str, float | str | None]:
        """Serialize all derived and stored Gaussian beam quantities."""

        return {
            "wavelength": self.wavelength,
            "waist_radius": self.waist_radius,
            "z_from_waist": self.z_from_waist,
            "rayleigh_range": self.rayleigh_range,
            "beam_radius": self.beam_radius,
            "wavefront_radius": self.wavefront_radius,
            "divergence_rad": self.divergence_rad,
            "refractive_index": self.refractive_index,
            "power": self.power,
            "label": self.label,
        }


@dataclass(frozen=True)
class ParaxialSample:
    """One sampled point along a paraxial trace."""

    point: Vec3
    distance: float
    beam: GaussianBeamState
    event: str
    element_type: str | None = None
    element_label: str = ""

    def to_dict(self) -> dict[str, object]:
        """Serialize the sample point, event, and beam state."""

        return {
            "point": self.point.as_tuple(),
            "distance": self.distance,
            "event": self.event,
            "element_type": self.element_type,
            "element_label": self.element_label,
            "beam": self.beam.to_dict(),
        }


@dataclass(frozen=True)
class ParaxialTraceResult:
    """Ordered paraxial propagation result with sampled beam states."""

    samples: list[ParaxialSample]
    direction_deg: float

    @property
    def points(self) -> list[Vec3]:
        """Return the sampled positions without metadata."""

        return [sample.point for sample in self.samples]

    @property
    def final_state(self) -> GaussianBeamState:
        """Return the Gaussian beam state at the final sample."""

        return self.samples[-1].beam

    def beam_radius_profile(self) -> list[tuple[float, float, float, float]]:
        """Return ``(x, y, z, radius)`` values for plotting beam size."""

        return [(*sample.point.as_tuple(), sample.beam.beam_radius) for sample in self.samples]

    def as_beam(self, *, wavelength_nm: float | None = None, width: float | None = None, label: str = "") -> Beam:
        """Convert the trace centerline to a drawable beam path."""

        return Beam(
            *[point.as_tuple() for point in self.points],
            wavelength=self.samples[0].beam.wavelength * 1000.0 if wavelength_nm is None else wavelength_nm,
            width=width if width is not None else max(self.samples[0].beam.beam_radius, 0.1),
            label=label,
        )

    def to_dict(self) -> dict[str, object]:
        """Serialize the full paraxial trace."""

        return {
            "direction_deg": self.direction_deg,
            "samples": [sample.to_dict() for sample in self.samples],
        }


def _direction_vector(angle_deg: float) -> Vec3:
    """Return a unit vector for a 2D angle in degrees."""

    angle_rad = math.radians(angle_deg)
    return Vec3(math.cos(angle_rad), math.sin(angle_rad), 0.0).normalized()


def _direction_angle(vector: Vec3) -> float:
    """Return the 2D direction angle for a vector."""

    return math.degrees(math.atan2(vector.y, vector.x))


def _reflect(direction_deg: float, normal_deg: float) -> float:
    """Reflect an incident direction around a surface normal."""

    direction = _direction_vector(direction_deg)
    normal = _direction_vector(normal_deg)
    reflected = direction - normal * (2.0 * direction.dot(normal))
    return _direction_angle(reflected)


def snell_refract(
    incident_angle_deg: float,
    *,
    n1: float = 1.0,
    n2: float = 1.5,
) -> float | None:
    """Return the refracted angle (degrees) from the interface normal.

    Angles use the same sign convention as ``incident_angle_deg``. Returns
    ``None`` when Snell's law would require total internal reflection.
    """

    n1_val = float(n1)
    n2_val = float(n2)
    if not math.isfinite(n1_val) or not math.isfinite(n2_val) or n1_val <= 0 or n2_val <= 0:
        raise ValueError("refractive indices must be positive and finite")
    incident = float(incident_angle_deg)
    if not math.isfinite(incident):
        raise ValueError("incident_angle_deg must be finite")
    incident_rad = math.radians(incident)
    sin_refracted = (n1_val / n2_val) * math.sin(incident_rad)
    if abs(sin_refracted) > 1.0 + 1e-12:
        return None
    return math.degrees(math.asin(max(-1.0, min(1.0, sin_refracted))))


def grating_diffraction_angle_deg(
    pitch: float,
    wavelength_nm: float,
    *,
    order: int = 1,
) -> float | None:
    """Return diffraction angle (degrees) for normal-incidence grating stub.

    Uses ``sin(theta_m) = m * lambda / pitch`` with ``m=1`` by default.
    ``pitch`` is assumed to use the same length unit as ``wavelength_nm / 1000``
    (typically microns). Returns ``None`` when the order is evanescent or
    ``pitch`` is missing or non-positive.
    """

    pitch_val = float(pitch)
    if not math.isfinite(pitch_val) or pitch_val <= 0:
        return None
    wavelength = float(wavelength_nm) / 1000.0
    if not math.isfinite(wavelength) or wavelength <= 0:
        raise ValueError("wavelength_nm must be positive and finite")
    sin_theta = int(order) * wavelength / pitch_val
    if abs(sin_theta) > 1.0 + 1e-12:
        return None
    return math.degrees(math.asin(max(-1.0, min(1.0, sin_theta))))


def grating_coupler_angle_deg(
    pitch: float,
    wavelength_nm: float,
    *,
    neff: float,
    n_clad: float = 1.0,
    order: int = 1,
) -> float | None:
    """Radiation angle stub for a **waveguide grating coupler** (fiber coupler).

    Unlike a free-space transmission grating, a grating coupler phase-matches the
    *guided* mode: ``n_clad * sin(theta) = n_eff - m * lambda / pitch``. ``pitch``
    shares units with ``wavelength_nm / 1000`` (microns). Returns ``None`` when
    the first order is evanescent (no radiating angle exists).
    """

    pitch_val = float(pitch)
    if not math.isfinite(pitch_val) or pitch_val <= 0:
        return None
    if not math.isfinite(n_clad) or n_clad <= 0 or not math.isfinite(neff) or neff <= 0:
        raise ValueError("neff and n_clad must be positive and finite")
    wavelength = float(wavelength_nm) / 1000.0
    if not math.isfinite(wavelength) or wavelength <= 0:
        raise ValueError("wavelength_nm must be positive and finite")
    sin_theta = (float(neff) - int(order) * wavelength / pitch_val) / float(n_clad)
    if abs(sin_theta) > 1.0 + 1e-12:
        return None
    return math.degrees(math.asin(max(-1.0, min(1.0, sin_theta))))


def validate_paraxial_chain(components: Iterable) -> list[str]:
    """Return warnings for components that lack declared paraxial support."""

    from optodraw.registry import component_registry

    registry = component_registry()
    warnings: list[str] = []
    seen: set[str] = set()
    for component in components:
        component_type = getattr(component, "component_type", component.__class__.__name__)
        if component_type in seen:
            continue
        seen.add(component_type)
        spec = registry.get(component_type)
        if spec is None:
            warnings.append(f"{component_type} is not registered; paraxial support unknown.")
            continue
        if "paraxial" not in spec.physics_modes:
            warnings.append(
                f"{component_type} does not declare paraxial physics support "
                f"(modes={list(spec.physics_modes)})."
            )
    return warnings


def validate_ray_chain(components: Iterable) -> list[str]:
    """Return warnings for visual-only components in a ray-tracing chain."""

    from optodraw.registry import component_registry

    registry = component_registry()
    warnings: list[str] = []
    seen: set[str] = set()
    for component in components:
        component_type = getattr(component, "component_type", component.__class__.__name__)
        if component_type in seen:
            continue
        seen.add(component_type)
        spec = registry.get(component_type)
        if spec is None:
            warnings.append(f"{component_type} is not registered; ray support unknown.")
            continue
        if spec.visual_only:
            warnings.append(
                f"{component_type} is visual-only; ray tracing may be misleading."
            )
            continue
        if "ray" not in spec.physics_modes:
            warnings.append(
                f"{component_type} does not declare ray physics support "
                f"(modes={list(spec.physics_modes)})."
            )
    return warnings


def trace_paraxial_beam(
    start: Vec3 | tuple[float, float] | tuple[float, float, float],
    direction_deg: float,
    optics: Iterable,
    *,
    input_beam: GaussianBeamState | None = None,
    exit_length: float = 20.0,
    beamsplitter_mode: str = "transmit",
) -> ParaxialTraceResult:
    """Trace Gaussian beam metadata through ordered paraxial elements.

    Ordered component centers define interaction planes normal to the current
    ray. An optic outside its aperture does not intercept the ray. Between
    planes the Gaussian q parameter propagates through free space. A ``Lens``
    with a non-zero ``focal_length`` applies an ideal thin-lens ABCD matrix.
    Mirrors and reflective beam splitters update the path direction but leave
    the Gaussian q parameter unchanged at the interaction plane.
    """

    current = _as_vec3(start)
    angle = float(direction_deg)
    beam = input_beam or GaussianBeamState()
    distance = 0.0
    samples = [ParaxialSample(current, distance, beam, event="start")]

    for optic in optics:
        optic_center = optic.world_position
        direction = _direction_vector(angle)
        displacement = optic_center - current
        segment_length = displacement.dot(direction)
        if segment_length < -1e-9:
            raise ValueError(f"{optic.component_type} is behind the current beam direction")
        segment_length = max(segment_length, 0.0)
        interaction = current + direction * segment_length
        miss_distance = (optic_center - interaction).length()
        aperture = getattr(optic, "aperture", None)
        if aperture is not None and math.isfinite(float(aperture)) and float(aperture) > 0:
            if miss_distance > float(aperture) / 2.0:
                raise ValueError(
                    f"Beam misses {optic.component_type} by {miss_distance:g} "
                    f"(aperture radius {float(aperture) / 2.0:g})"
                )
        if segment_length > 0:
            beam = beam.propagate_free_space(segment_length)
            distance += segment_length

        optic_type = getattr(optic, "component_type", optic.__class__.__name__)
        event = "pass"
        focal_length = getattr(optic, "focal_length", None)
        if optic_type == "Lens" and focal_length:
            beam = beam.through_thin_lens(float(focal_length))
            event = "thin_lens"
        elif optic_type == "Mirror" or (optic_type == "FlipMirror" and not optic.out_of_beam):
            angle = _reflect(angle, optic.world_transform.angle)
            event = "reflect"
        elif optic_type == "BeamSplitter" and beamsplitter_mode == "reflect":
            angle = _reflect(angle, optic.world_transform.angle)
            event = "reflect"

        samples.append(
            ParaxialSample(
                interaction,
                distance,
                beam,
                event=event,
                element_type=optic_type,
                element_label=getattr(optic, "label", ""),
            )
        )
        current = interaction

    if exit_length > 0:
        beam = beam.propagate_free_space(exit_length)
        distance += exit_length
    exit_point = current + _direction_vector(angle) * exit_length
    samples.append(ParaxialSample(exit_point, distance, beam, event="exit"))

    return ParaxialTraceResult(samples=samples, direction_deg=angle)


__all__ = [
    "ABCDMatrix",
    "GaussianBeamState",
    "ParaxialSample",
    "ParaxialTraceResult",
    "free_space_matrix",
    "grating_coupler_angle_deg",
    "grating_diffraction_angle_deg",
    "snell_refract",
    "thin_lens_matrix",
    "trace_paraxial_beam",
    "validate_paraxial_chain",
    "validate_ray_chain",
]
