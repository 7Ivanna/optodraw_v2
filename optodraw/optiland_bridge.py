"""Optional Optiland physics backend for real sequential ray tracing.

Optodraw is a *diagram* tool: its built-in :mod:`optodraw.core.raytrace` is a
deliberately simplified paraxial stub that draws plausible beam paths. This
module is the bridge to `Optiland <https://github.com/optiland/optiland>`_
(MIT licensed), a real sequential ray tracer, so that diagrams can be drawn from
*physically traced* rays instead of thin-lens approximations.

Design (mirrors ``optodraw.blender`` and ``optodraw.gds``):

- Optiland is an **optional** dependency. Nothing here imports it at module load
  time; the optiland-touching functions import it lazily and raise a clear
  install hint when it is missing.
- The data model (:class:`OpticalSurface`, :class:`LensPrescription`) and the
  conversion helpers (:func:`ray_paths_from_arrays`, :func:`place_ray_paths`,
  :func:`rays_to_beams`) are pure Python + NumPy and are unit-testable without
  Optiland installed.
- The split of responsibility: Optiland is the *engine*, optodraw is the
  *renderer*. Traced rays are returned as ordinary
  :class:`optodraw.core.beam.Beam` objects that every existing renderer
  (SVG / TikZ / Three.js / Manim) already knows how to draw.

Two workflows are supported:

1. **Thin lens / optodraw component -> real rays.** Build a
   :class:`LensPrescription` (from a focal length, or from an optodraw
   :class:`~optodraw.components.optics.Lens`), trace it, and drop the rays into
   a scene::

       from optodraw import Scene, Lens
       from optodraw.optiland_bridge import LensPrescription, trace_lens_beams

       scene = Scene(title="Singlet", platform="free_space")
       lens = scene.add(Lens(center=(0, 0), focal_length=50, aperture=20))
       rx = LensPrescription.from_thin_lens(focal_length=50, aperture=20)
       trace_lens_beams(rx, scene=scene, origin=(0, 0), num_rays=9)
       scene.render_svg("singlet.svg")

2. **Any Optiland system (e.g. a Zemax import) -> publication diagram.** Load
   the system yourself with Optiland, then turn the traced rays into beams::

       from optiland.fileio import load_optiland_file  # user-side, optiland API
       optic = load_optiland_file("doublet.zmx")
       beams = optic_to_beams(optic, origin=(0, 0))
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Any, Iterable, Sequence

from optodraw.core.beam import Beam


INSTALL_HINT = (
    "Optiland is required for real sequential ray tracing. Install it with "
    "`pip install optodraw[optiland]` (or `pip install optiland`)."
)

# Maps optodraw material presets to a sensible Optiland glass-catalog name. Only
# transmissive optical glasses are mapped; everything else falls back to N-BK7.
_PRESET_TO_GLASS: dict[str, str] = {
    "glass": "N-BK7",
    "sio2": "F_SILICA",
    "silica": "F_SILICA",
    "fused_silica": "F_SILICA",
}

# Refractive index used by from_thin_lens when no glass is supplied (N-BK7 @ d).
_DEFAULT_INDEX = 1.5168


def optiland_available() -> bool:
    """Return ``True`` when the optional Optiland backend can be imported."""

    try:  # pragma: no cover - exercised indirectly
        import optiland  # noqa: F401
    except Exception:
        return False
    return True


#: Module-level convenience flag. Recomputed on import; call
#: :func:`optiland_available` for an always-fresh check.
OPTILAND_AVAILABLE: bool = optiland_available()


def require_optiland() -> Any:
    """Import and return the ``optiland`` package, or raise a helpful error."""

    try:
        import optiland
    except Exception as error:  # pragma: no cover - depends on environment
        raise ImportError(INSTALL_HINT) from error
    return optiland


# --------------------------------------------------------------------------- #
# Pure-python prescription model
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class OpticalSurface:
    """One sequential optical surface in a :class:`LensPrescription`.

    Coordinates follow the Optiland convention: ``radius`` and ``thickness`` are
    measured along the optical axis, ``thickness`` is the axial gap to the *next*
    surface, and ``material`` describes the medium *after* the surface.

    Parameters
    ----------
    radius:
        Vertex radius of curvature. Use ``math.inf`` (the default) for a flat
        surface. Positive curves toward +axial.
    thickness:
        Axial distance to the next surface. For the final lens surface this is
        the gap to the image plane (often the back focal distance).
    material:
        Medium after this surface: an Optiland glass name (``"N-BK7"``), a
        numeric refractive index, or ``None`` for air/vacuum.
    conic:
        Conic constant (0 = spherical, -1 = parabolic).
    is_stop:
        Marks this surface as the aperture stop.
    semi_diameter:
        Optional clear semi-diameter; used as a hint where the backend supports
        it and otherwise carried as metadata.
    """

    radius: float = math.inf
    thickness: float = 0.0
    material: str | float | None = None
    conic: float = 0.0
    is_stop: bool = False
    semi_diameter: float | None = None


@dataclass
class LensPrescription:
    """A sequential optical-system prescription that Optiland can trace.

    The prescription holds only the *real* lens surfaces plus global tracing
    parameters. The object surface (ahead of the first lens surface) and the
    image surface are synthesized when the Optiland :class:`Optic` is built.
    """

    surfaces: list[OpticalSurface] = field(default_factory=list)
    aperture_epd: float = 10.0
    wavelengths_um: tuple[float, ...] = (0.55,)
    field_angles_deg: tuple[float, ...] = (0.0,)
    object_distance: float = math.inf
    label: str = ""

    def __post_init__(self) -> None:
        if not math.isfinite(self.aperture_epd) or self.aperture_epd <= 0.0:
            raise ValueError("aperture_epd must be finite and positive.")
        if not self.wavelengths_um:
            raise ValueError("at least one wavelength (in microns) is required.")
        for wavelength in self.wavelengths_um:
            if not math.isfinite(wavelength) or wavelength <= 0.0:
                raise ValueError("wavelengths_um values must be finite positive microns.")
        if not self.field_angles_deg:
            raise ValueError("at least one field angle is required.")
        if any(not math.isfinite(angle) for angle in self.field_angles_deg):
            raise ValueError("field_angles_deg values must be finite.")
        self.surfaces = list(self.surfaces)

    def add_surface(self, surface: OpticalSurface) -> "LensPrescription":
        """Append a surface and return ``self`` for chaining."""

        if not isinstance(surface, OpticalSurface):
            raise TypeError("surface must be an OpticalSurface instance.")
        self.surfaces.append(surface)
        return self

    def with_stop(self, index: int) -> "LensPrescription":
        """Return a copy with surface ``index`` marked as the aperture stop."""

        if not self.surfaces:
            raise ValueError("prescription has no surfaces.")
        if not 0 <= index < len(self.surfaces):
            raise IndexError("aperture stop index is outside the prescription.")
        surfaces = [
            replace(surface, is_stop=(position == index))
            for position, surface in enumerate(self.surfaces)
        ]
        return replace(self, surfaces=surfaces)

    @property
    def has_stop(self) -> bool:
        """Whether any surface is flagged as the aperture stop."""

        return any(surface.is_stop for surface in self.surfaces)

    @classmethod
    def from_thin_lens(
        cls,
        focal_length: float,
        aperture: float,
        *,
        glass: str = "N-BK7",
        index: float = _DEFAULT_INDEX,
        center_thickness: float | None = None,
        wavelengths_um: Sequence[float] = (0.55,),
        field_angles_deg: Sequence[float] = (0.0,),
    ) -> "LensPrescription":
        """Build an equiconvex singlet that realizes a paraxial ``focal_length``.

        Uses the thin-lens lensmaker relation for an equiconvex element
        (``R1 = +R``, ``R2 = -R``): ``1/f = (n - 1) * (2 / R)`` so
        ``R = 2 * (n - 1) * f``. The image surface is placed one focal length
        behind the lens so the on-axis fan converges to a visible focus.
        """

        if not math.isfinite(focal_length) or focal_length <= 0.0:
            raise ValueError("focal_length must be finite and positive for an equiconvex singlet.")
        if not math.isfinite(aperture) or aperture <= 0.0:
            raise ValueError("aperture must be finite and positive.")
        if not math.isfinite(index) or index <= 1.0:
            raise ValueError("index must be finite and greater than one.")
        if center_thickness is not None and (not math.isfinite(center_thickness) or center_thickness <= 0.0):
            raise ValueError("center_thickness must be finite and positive.")

        curvature = 2.0 * (index - 1.0) * focal_length
        thickness = center_thickness if center_thickness is not None else max(aperture * 0.1, 1.0)
        front = OpticalSurface(
            radius=curvature,
            thickness=thickness,
            material=glass,
            is_stop=True,
            semi_diameter=aperture / 2.0,
        )
        back = OpticalSurface(
            radius=-curvature,
            thickness=abs(focal_length),
            material=None,
            semi_diameter=aperture / 2.0,
        )
        return cls(
            surfaces=[front, back],
            aperture_epd=aperture,
            wavelengths_um=tuple(wavelengths_um),
            field_angles_deg=tuple(field_angles_deg),
            label="thin_lens_singlet",
        )

    @classmethod
    def from_optodraw_lens(
        cls,
        lens: Any,
        *,
        glass: str | float | None = None,
        index: float = _DEFAULT_INDEX,
        image_distance: float | None = None,
        wavelengths_um: Sequence[float] = (0.55,),
        field_angles_deg: Sequence[float] = (0.0,),
    ) -> "LensPrescription":
        """Build a prescription from an optodraw ``Lens`` / ``AsphericLens``.

        The optodraw :class:`~optodraw.components.optics.Lens` is a symmetric
        biconvex element described by a single curvature ``radius`` and a
        ``center_thickness``; this maps it to ``R1 = +radius`` / ``R2 = -radius``.
        ``AsphericLens`` contributes its ``conic_constant`` to the front face.
        When the component carries no glass hint, its ``material_preset`` is
        mapped through :data:`_PRESET_TO_GLASS` (default ``N-BK7``).
        """

        aperture = float(getattr(lens, "aperture", 0.0))
        if aperture <= 0.0:
            raise ValueError("lens component must expose a positive aperture.")

        radius = float(getattr(lens, "radius", 0.0))
        if radius == 0.0:
            focal_length = getattr(lens, "focal_length", None)
            if not focal_length:
                raise ValueError(
                    "lens has neither a usable curvature radius nor a focal_length; "
                    "cannot build a prescription."
                )
            radius = 2.0 * (index - 1.0) * float(focal_length)

        thickness = float(getattr(lens, "center_thickness", max(aperture * 0.1, 1.0)))
        conic = float(getattr(lens, "conic_constant", 0.0))
        if glass is None:
            preset = str(getattr(lens, "material_preset", "glass")).lower()
            glass = _PRESET_TO_GLASS.get(preset, "N-BK7")

        focal_length = getattr(lens, "focal_length", None)
        if image_distance is None:
            image_distance = abs(float(focal_length)) if focal_length else abs(radius)

        front = OpticalSurface(
            radius=radius,
            thickness=thickness,
            material=glass,
            conic=conic,
            is_stop=True,
            semi_diameter=aperture / 2.0,
        )
        back = OpticalSurface(
            radius=-radius,
            thickness=image_distance,
            material=None,
            semi_diameter=aperture / 2.0,
        )
        return cls(
            surfaces=[front, back],
            aperture_epd=aperture,
            wavelengths_um=tuple(wavelengths_um),
            field_angles_deg=tuple(field_angles_deg),
            label=str(getattr(lens, "label", "") or "optodraw_lens"),
        )


# --------------------------------------------------------------------------- #
# Pure-python ray-path geometry (testable without Optiland)
# --------------------------------------------------------------------------- #

# A single ray path in the lens-local (axial, transverse) frame.
RayPath = list[tuple[float, float]]


def ray_paths_from_arrays(axial: Any, transverse: Any) -> list[RayPath]:
    """Convert Optiland per-surface coordinate arrays into ray polylines.

    Parameters
    ----------
    axial, transverse:
        Arrays shaped ``(num_surfaces, num_rays)`` such as Optiland's
        ``surface_group.z`` (axial) and ``surface_group.y`` (transverse). Lists
        of lists are accepted too.

    Returns
    -------
    list[RayPath]
        One polyline per ray, each a list of ``(axial, transverse)`` points.
        Non-finite samples (e.g. an object surface at infinity) split the path.
        Contiguous segments with fewer than two points are omitted.
    """

    import numpy as np

    z = np.atleast_2d(np.asarray(axial, dtype=float))
    y = np.atleast_2d(np.asarray(transverse, dtype=float))
    if z.shape != y.shape:
        raise ValueError(
            f"axial and transverse must share a shape; got {z.shape} and {y.shape}."
        )

    num_surfaces, num_rays = z.shape
    paths: list[RayPath] = []
    for ray in range(num_rays):
        points: RayPath = []
        for surface in range(num_surfaces):
            az = float(z[surface, ray])
            tv = float(y[surface, ray])
            if math.isfinite(az) and math.isfinite(tv):
                points.append((az, tv))
            else:
                if len(points) >= 2:
                    paths.append(points)
                points = []
        if len(points) >= 2:
            paths.append(points)
    return paths


def place_ray_paths(
    paths: Iterable[RayPath],
    *,
    origin: tuple[float, float] = (0.0, 0.0),
    direction_deg: float = 0.0,
    axial_scale: float = 1.0,
    transverse_scale: float = 1.0,
    axial_offset: float = 0.0,
) -> list[RayPath]:
    """Rigidly place lens-local ``(axial, transverse)`` paths into scene 2D.

    The optodraw convention is propagation along local +x with transverse +y.
    Each point is mapped as::

        world = origin + a*axial_dir + t*transverse_dir

    where ``a = (axial - axial_offset) * axial_scale``,
    ``t = transverse * transverse_scale``, ``axial_dir`` points along
    ``direction_deg`` and ``transverse_dir`` is its +90 deg normal.
    """

    angle = math.radians(direction_deg)
    ax, ay = math.cos(angle), math.sin(angle)
    tx, ty = -math.sin(angle), math.cos(angle)
    ox, oy = origin

    placed: list[RayPath] = []
    for path in paths:
        world: RayPath = []
        for axial, transverse in path:
            a = (axial - axial_offset) * axial_scale
            t = transverse * transverse_scale
            world.append((ox + a * ax + t * tx, oy + a * ay + t * ty))
        placed.append(world)
    return placed


def rays_to_beams(
    paths: Iterable[RayPath],
    *,
    wavelength_nm: float = 633.0,
    width: float = 0.5,
    opacity: float = 0.85,
    label: str = "",
) -> list[Beam]:
    """Convert placed 2D ray polylines into drawable :class:`Beam` objects."""

    beams: list[Beam] = []
    for index, path in enumerate(paths):
        if len(path) < 2:
            continue
        beam_label = label if (label and index == 0) else ""
        beams.append(
            Beam(
                *[(float(x), float(y)) for x, y in path],
                wavelength=wavelength_nm,
                width=width,
                label=beam_label,
                opacity=opacity,
            )
        )
    return beams


# --------------------------------------------------------------------------- #
# Optiland-backed tracing (lazy import)
# --------------------------------------------------------------------------- #


def _safe_add_surface(surface_group: Any, **kwargs: Any) -> None:
    """Call ``surface_group.add`` dropping kwargs the installed API rejects.

    Optiland's surface-add signature has varied across versions (e.g. whether
    ``semi_diameter`` is accepted). Rather than pin a single signature, retry
    without the optional keys on ``TypeError``.
    """

    optional_keys = ("semi_diameter", "conic")
    try:
        surface_group.add(**kwargs)
        return
    except TypeError:
        pruned = {key: value for key, value in kwargs.items() if key not in optional_keys}
        surface_group.add(**pruned)


def build_optic(prescription: LensPrescription) -> Any:
    """Build an Optiland ``Optic`` from a :class:`LensPrescription`.

    Requires Optiland; raises :class:`ImportError` with an install hint when it
    is unavailable.
    """

    require_optiland()
    from optiland import optic as optiland_optic

    system = optiland_optic.Optic()
    surfaces = system.surfaces

    index = 0
    # Object surface: flat, at object_distance ahead of the first lens surface.
    _safe_add_surface(surfaces, index=index, radius=math.inf, thickness=prescription.object_distance)
    index += 1

    has_stop = prescription.has_stop
    for position, surface in enumerate(prescription.surfaces):
        is_stop = surface.is_stop or (not has_stop and position == 0)
        kwargs: dict[str, Any] = {
            "index": index,
            "radius": surface.radius,
            "thickness": surface.thickness,
            "conic": surface.conic,
            "is_stop": is_stop,
        }
        if surface.material is not None:
            kwargs["material"] = surface.material
        if surface.semi_diameter is not None:
            kwargs["semi_diameter"] = surface.semi_diameter
        _safe_add_surface(surfaces, **kwargs)
        index += 1

    # Image surface.
    _safe_add_surface(surfaces, index=index)

    system.set_aperture(aperture_type="EPD", value=prescription.aperture_epd)

    system.fields.set_type(field_type="angle")
    for angle in prescription.field_angles_deg:
        system.fields.add(y=float(angle))

    for position, wavelength in enumerate(prescription.wavelengths_um):
        system.wavelengths.add(value=float(wavelength), is_primary=(position == 0))

    return system


def _surface_group(optic: Any) -> Any:
    """Return the optic's surface group across Optiland naming variants."""

    group = getattr(optic, "surface_group", None)
    if group is None:
        group = getattr(optic, "surfaces", None)
    if group is None:  # pragma: no cover - defensive
        raise AttributeError("Optiland optic exposes neither 'surface_group' nor 'surfaces'.")
    return group


def trace_optic_ray_paths(
    optic: Any,
    *,
    field_deg: float = 0.0,
    max_field_deg: float | None = None,
    wavelength_um: float = 0.55,
    num_rays: int = 9,
    distribution: str = "line_y",
) -> list[RayPath]:
    """Trace a meridional ray fan through any Optiland ``Optic``.

    Returns ray polylines in the lens-local ``(axial=z, transverse=y)`` frame.
    ``field_deg`` is converted to a normalized field coordinate using
    ``max_field_deg`` (defaults to ``abs(field_deg)``).
    """

    if not math.isfinite(field_deg):
        raise ValueError("field_deg must be finite.")
    if max_field_deg is not None and (not math.isfinite(max_field_deg) or max_field_deg <= 0.0):
        raise ValueError("max_field_deg must be finite and positive.")
    if not math.isfinite(wavelength_um) or wavelength_um <= 0.0:
        raise ValueError("wavelength_um must be finite and positive.")
    if isinstance(num_rays, bool) or not isinstance(num_rays, int) or num_rays <= 0:
        raise ValueError("num_rays must be a positive integer.")

    require_optiland()
    import numpy as np

    normalized = 0.0
    reference = max_field_deg if max_field_deg is not None else abs(field_deg)
    if reference:
        normalized = field_deg / reference

    optic.trace(
        Hx=0.0,
        Hy=float(normalized),
        wavelength=float(wavelength_um),
        num_rays=int(num_rays),
        distribution=distribution,
    )

    group = _surface_group(optic)
    z = np.asarray(group.z, dtype=float)
    y = np.asarray(group.y, dtype=float)
    return ray_paths_from_arrays(z, y)


def trace_ray_paths(
    prescription: LensPrescription,
    *,
    field_deg: float = 0.0,
    wavelength_um: float | None = None,
    num_rays: int = 9,
    distribution: str = "line_y",
) -> list[RayPath]:
    """Build an optic from ``prescription`` and trace one meridional fan."""

    optic = build_optic(prescription)
    wavelength = wavelength_um if wavelength_um is not None else prescription.wavelengths_um[0]
    max_field = max((abs(angle) for angle in prescription.field_angles_deg), default=0.0)
    return trace_optic_ray_paths(
        optic,
        field_deg=field_deg,
        max_field_deg=max_field or None,
        wavelength_um=wavelength,
        num_rays=num_rays,
        distribution=distribution,
    )


def optic_to_beams(
    optic: Any,
    *,
    origin: tuple[float, float] = (0.0, 0.0),
    direction_deg: float = 0.0,
    field_angles_deg: Sequence[float] = (0.0,),
    wavelengths_um: Sequence[float] = (0.55,),
    num_rays: int = 9,
    distribution: str = "line_y",
    axial_scale: float = 1.0,
    transverse_scale: float = 1.0,
    axial_offset: float | None = None,
    width: float = 0.5,
    scene: Any = None,
) -> list[Beam]:
    """Trace any Optiland ``Optic`` and return placed :class:`Beam` objects.

    This is the workflow for externally built systems (for example a Zemax file
    loaded with Optiland's own importer): the caller supplies the ``Optic`` and
    gets back beams ready for any optodraw renderer. One fan is traced per
    (field, wavelength) pair; beam color follows the wavelength.

    When ``scene`` is provided, each beam is also added to it.
    """

    max_field = max((abs(angle) for angle in field_angles_deg), default=0.0)
    beams: list[Beam] = []
    resolved_offset = axial_offset

    for wavelength in wavelengths_um:
        wavelength_nm = float(wavelength) * 1000.0
        for field_deg in field_angles_deg:
            local_paths = trace_optic_ray_paths(
                optic,
                field_deg=float(field_deg),
                max_field_deg=max_field or None,
                wavelength_um=float(wavelength),
                num_rays=num_rays,
                distribution=distribution,
            )
            if resolved_offset is None:
                resolved_offset = _first_axial(local_paths)
            placed = place_ray_paths(
                local_paths,
                origin=origin,
                direction_deg=direction_deg,
                axial_scale=axial_scale,
                transverse_scale=transverse_scale,
                axial_offset=resolved_offset or 0.0,
            )
            beams.extend(rays_to_beams(placed, wavelength_nm=wavelength_nm, width=width))

    if scene is not None:
        for beam in beams:
            scene.add(beam)
    return beams


def trace_lens_beams(
    prescription: LensPrescription,
    *,
    origin: tuple[float, float] = (0.0, 0.0),
    direction_deg: float = 0.0,
    num_rays: int = 9,
    distribution: str = "line_y",
    axial_scale: float = 1.0,
    transverse_scale: float = 1.0,
    axial_offset: float | None = None,
    width: float = 0.5,
    scene: Any = None,
) -> list[Beam]:
    """Trace a :class:`LensPrescription` and return placed :class:`Beam` objects.

    Convenience wrapper that builds the optic and traces every field/wavelength
    declared on the prescription. Pass ``scene=`` to also add the beams.
    """

    optic = build_optic(prescription)
    return optic_to_beams(
        optic,
        origin=origin,
        direction_deg=direction_deg,
        field_angles_deg=prescription.field_angles_deg,
        wavelengths_um=prescription.wavelengths_um,
        num_rays=num_rays,
        distribution=distribution,
        axial_scale=axial_scale,
        transverse_scale=transverse_scale,
        axial_offset=axial_offset,
        width=width,
        scene=scene,
    )


def _first_axial(paths: Sequence[RayPath]) -> float:
    """Return the axial coordinate of the first valid point, or 0.0."""

    for path in paths:
        if path:
            return path[0][0]
    return 0.0


__all__ = [
    "INSTALL_HINT",
    "OPTILAND_AVAILABLE",
    "LensPrescription",
    "OpticalSurface",
    "RayPath",
    "build_optic",
    "optic_to_beams",
    "optiland_available",
    "place_ray_paths",
    "ray_paths_from_arrays",
    "rays_to_beams",
    "require_optiland",
    "trace_lens_beams",
    "trace_optic_ray_paths",
    "trace_ray_paths",
]
