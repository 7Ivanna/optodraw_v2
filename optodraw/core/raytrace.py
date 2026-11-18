"""Lightweight 2D ray tracing helpers.

This is intentionally not a full non-sequential optical simulator. It provides
physical beam-path construction across ordered optical elements so scenes can be
drawn from actual interaction rules instead of only hand-authored waypoints.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Iterable

import warnings

from optodraw.core.beam import Beam
from optodraw.core.physics import grating_diffraction_angle_deg, snell_refract
from optodraw.core.transform import Vec3, as_vec3 as _as_vec3

@dataclass
class _HeightPlan:
    """The beam heights the parts in a trace ask for (3D): the run before any periscope ("start"), or the
    run after one (its id), mapped to a height above the bench beam plane. A first pass fills it as the
    rays meet parts with their own ``beam_height``; a second pass traces with it."""

    plane: float
    heights: dict[Any, float] = field(default_factory=dict)


def _height_plan(nodes: Iterable[Any], start_node: Any, plane: float | None) -> _HeightPlan | None:
    """A plan when any part (the source too) sets its own beam height, else None: one pass is enough."""

    from optodraw.core.beam_heights import _own_height

    if plane is None:
        from optodraw.components.optics.optomech import BEAM_HEIGHT

        plane = BEAM_HEIGHT
    if not any(_own_height(n) is not None for n in [start_node, *nodes] if n is not None):
        return None
    plan = _HeightPlan(plane=float(plane))
    own = _own_height(start_node) if start_node is not None else None
    if own is not None:
        plan.heights["start"] = own - plan.plane
    return plan


def _two_passes(plan: _HeightPlan | None, trace) -> list[RayTraceResult]:
    """Run ``trace(plan)`` once, or twice when parts set heights: the first pass finds which run each
    height belongs to."""

    if plan is not None:
        trace(plan)
    return trace(plan)


_SKIP_SCENE_TYPES = frozenset(
    {
        "Beam",
        "FocusingBeam",
        "Route",
        "WaveguideRoute",
        "FiberRoute",
        "Group",
        "Grid",
        "Block",
    }
)


@dataclass
class RayTraceResult:
    """Result of tracing a single 2D ray through ordered optics."""

    points: list[Vec3]
    direction_deg: float
    power: float = 1.0  # fraction of the launch power carried by this branch
    ray: int = 0  # bundle index: 0 = chief ray, 1..k = rim rays (launch height = points[0].z)
    offset: float = 0.0  # in-plane launch offset from the axis (marginal rays = the extremes)

    def as_beam(self, *, wavelength: float = 633.0, width: float = 0.8, label: str = "") -> Beam:
        """Convert the traced path into a drawable :class:`~optodraw.core.beam.Beam`."""

        return Beam(*[point.as_tuple() for point in self.points], wavelength=wavelength, width=width, label=label)


@dataclass
class ComponentRayInteraction:
    """Direction change produced by a single optical element."""

    input_direction_deg: float
    output_direction_deg: float
    deflection_deg: float
    interaction: str
    wavelength_nm: float
    component_type: str
    metadata: dict[str, Any] = field(default_factory=dict)


def _direction_vector(angle_deg: float) -> Vec3:
    """Return a unit vector for a 2D angle in degrees."""

    angle_rad = math.radians(angle_deg)
    return Vec3(math.cos(angle_rad), math.sin(angle_rad), 0.0).normalized()


def _planar_interaction(origin: Vec3, optic: Any) -> Vec3:
    """Project an optic center into the ray's fixed-height schematic plane."""

    center = optic.world_position
    return Vec3(center.x, center.y, origin.z)


def _direction_angle(vector: Vec3) -> float:
    """Return the 2D direction angle for a vector."""

    return math.degrees(math.atan2(vector.y, vector.x))


def _normalize_angle(angle_deg: float) -> float:
    angle = float(angle_deg) % 360.0
    if angle > 180.0:
        angle -= 360.0
    return angle


def _angle_delta(output_deg: float, input_deg: float) -> float:
    return _normalize_angle(output_deg - input_deg)


def _reflect_vec(direction: Vec3, normal: Vec3) -> Vec3:
    """Reflect a direction vector around a surface normal (sign-agnostic)."""

    return direction - normal * (2.0 * direction.dot(normal))


_CAUCHY_B_UM2 = 0.00420  # BK7-like dispersion term; anchors the given index at the d-line
_D_LINE_UM = 0.5876


def _dispersed_index(index: float, wavelength_nm: float) -> float:
    """Cauchy n(lambda) = n_d + B(1/lambda^2 - 1/lambda_d^2) — the component's
    ``refractive_index`` is taken as its d-line value, so a prism actually
    separates colors instead of bending them all alike."""

    lam = max(float(wavelength_nm), 1.0) / 1000.0
    return index + _CAUCHY_B_UM2 * (1.0 / (lam * lam) - 1.0 / (_D_LINE_UM * _D_LINE_UM))


def _refract_vec(direction: Vec3, normal: Vec3, n1: float, n2: float) -> Vec3 | None:
    """Snell's law in vector form; ``None`` on total internal reflection."""

    incident = direction.normalized()
    n = normal.normalized()
    cos_i = -incident.dot(n)
    if cos_i < 0.0:  # normal points downstream — flip it to face the incoming ray
        n, cos_i = n * -1.0, -cos_i
    eta = n1 / n2
    k = 1.0 - eta * eta * (1.0 - cos_i * cos_i)
    if k < 0.0:
        return None  # beyond the critical angle
    return (incident * eta + n * (eta * cos_i - math.sqrt(k))).normalized()


def _reflect(direction_deg: float, normal_deg: float) -> float:
    """Reflect an incident direction around a surface normal."""

    return _direction_angle(_reflect_vec(_direction_vector(direction_deg), _direction_vector(normal_deg)))


def _component_metadata(optic: Any) -> dict[str, Any]:
    if hasattr(optic, "physics_metadata"):
        return dict(optic.physics_metadata())
    return {}


def _prism_refractive_index(optic: Any) -> float | None:
    metadata = _component_metadata(optic)
    index = getattr(optic, "refractive_index", None)
    if index is None:
        index = metadata.get("refractive_index")
    return None if index is None else float(index)


def _apply_snell_at_interface(
    direction_deg: float,
    interface_normal_deg: float,
    *,
    n1: float = 1.0,
    n2: float,
) -> tuple[float, str]:
    incident_from_normal = direction_deg - interface_normal_deg
    refracted_from_normal = snell_refract(incident_from_normal, n1=n1, n2=n2)
    if refracted_from_normal is None:
        return _reflect(direction_deg, interface_normal_deg), "reflect"
    return interface_normal_deg + refracted_from_normal, "refract"


def _apply_prism_refraction(direction_deg: float, optic: Any) -> tuple[float, str]:
    """Apply a single Snell refraction at a simplified prism entry face."""

    n2 = _prism_refractive_index(optic)
    if n2 is None:
        return direction_deg, "pass"
    interface_normal = float(optic.world_transform.angle)
    return _apply_snell_at_interface(direction_deg, interface_normal, n1=1.0, n2=n2)


def _apply_wedge_refraction(direction_deg: float, optic: Any) -> tuple[float, str]:
    """Apply a paraxial wedge deviation using metadata ``deflection_angle_deg``."""

    metadata = _component_metadata(optic)
    delta = metadata.get("deflection_angle_deg")
    if delta is None:
        wedge_angle = float(getattr(optic, "wedge_angle_deg", metadata.get("wedge_angle_deg", 0.0)))
        index = _prism_refractive_index(optic) or 1.0
        delta = (index - 1.0) * wedge_angle
    return direction_deg - float(delta), "wedge"


def _apply_fold_deflection(direction_deg: float, optic: Any) -> tuple[float, str]:
    """Apply a fixed fold deflection relative to the component orientation."""

    metadata = _component_metadata(optic)
    deflection = float(metadata.get("deflection_angle_deg", metadata.get("fold_angle_deg", 90.0)))
    base = float(optic.world_transform.angle)
    return base + deflection, "fold"


def _grating_pitch(optic: Any) -> float | None:
    pitch = getattr(optic, "pitch", None)
    if pitch is None:
        pitch = _component_metadata(optic).get("pitch")
    if pitch is None:
        return None
    pitch_val = float(pitch)
    return pitch_val if pitch_val > 0 else None


def _apply_grating_diffraction(
    direction_deg: float,
    optic: Any,
    *,
    wavelength_nm: float,
    diffraction_order: int,
) -> tuple[float, str]:
    """Apply first-order grating deflection for normal-incidence stub."""

    pitch = _grating_pitch(optic)
    if pitch is None:
        return direction_deg, "pass"

    diffraction_angle = grating_diffraction_angle_deg(
        pitch,
        wavelength_nm,
        order=diffraction_order,
    )
    if diffraction_angle is None:
        return direction_deg, "pass"

    grating_normal = float(optic.world_transform.angle)
    incident_from_normal = direction_deg - grating_normal
    if abs(incident_from_normal) > 90.0:
        incident_from_normal -= 180.0 if incident_from_normal > 0 else -180.0
    if abs(incident_from_normal) > 5.0:
        return direction_deg, "pass"

    sign = 1.0 if incident_from_normal >= 0 else -1.0
    return grating_normal + sign * diffraction_angle, "grating"


def _apply_thin_lens(direction_deg: float, optic: Any, current: Vec3, interaction: Vec3) -> tuple[float, str]:
    """Apply a paraxial thin-lens angle change using ``focal_length``."""

    focal = getattr(optic, "focal_length", None)
    if not focal:
        return direction_deg, "pass"

    focal_length = float(focal)
    if abs(focal_length) < 1e-15:
        return direction_deg, "pass"

    optic_angle = float(optic.world_transform.angle)
    axis_dir = _direction_vector(optic_angle)
    perp = Vec3(-axis_dir.y, axis_dir.x, 0.0)
    height_offset = (current - interaction).dot(perp)
    slope_in = math.radians(direction_deg - optic_angle)
    slope_out = slope_in - height_offset / focal_length
    return optic_angle + math.degrees(slope_out), "thin_lens"


def _apply_optic_interaction(
    direction_deg: float,
    optic: Any,
    *,
    current: Vec3 | None = None,
    interaction: Vec3 | None = None,
    wavelength_nm: float = 633.0,
    beamsplitter_mode: str = "transmit",
    diffraction_order: int = 1,
) -> tuple[float, str]:
    """Return the outgoing direction and interaction label for one optic."""

    optic_type = getattr(optic, "component_type", optic.__class__.__name__)

    if optic_type == "Mirror" or (optic_type == "FlipMirror" and not optic.out_of_beam):
        return _reflect(direction_deg, optic.world_transform.angle), "reflect"
    if optic_type == "BeamSplitter" and beamsplitter_mode == "reflect":
        return _reflect(direction_deg, optic.world_transform.angle), "reflect"
    if optic_type == "Lens" and current is not None and interaction is not None:
        return _apply_thin_lens(direction_deg, optic, current, interaction)
    if optic_type == "Prism":
        return _apply_prism_refraction(direction_deg, optic)
    if optic_type == "RightAnglePrism":
        return _apply_fold_deflection(direction_deg, optic)
    if optic_type == "WedgePlate":
        return _apply_wedge_refraction(direction_deg, optic)
    if optic_type == "Grating":
        return _apply_grating_diffraction(
            direction_deg,
            optic,
            wavelength_nm=wavelength_nm,
            diffraction_order=diffraction_order,
        )
    return direction_deg, "pass"


def trace_beam_through_component(
    component: Any,
    wavelength_nm: float,
    *,
    direction_deg: float = 0.0,
    beamsplitter_mode: str = "transmit",
    diffraction_order: int = 1,
) -> ComponentRayInteraction:
    """Return the paraxial direction change for a single optical element.

    Uses the same interaction stubs as :func:`trace_ray` and reads
    ``physics_metadata()`` for wedge/prism deflection hints.
    """

    position = component.world_position
    output_direction, interaction = _apply_optic_interaction(
        direction_deg,
        component,
        current=position,
        interaction=position,
        wavelength_nm=wavelength_nm,
        beamsplitter_mode=beamsplitter_mode,
        diffraction_order=diffraction_order,
    )
    return ComponentRayInteraction(
        input_direction_deg=float(direction_deg),
        output_direction_deg=output_direction,
        deflection_deg=_angle_delta(output_direction, direction_deg),
        interaction=interaction,
        wavelength_nm=float(wavelength_nm),
        component_type=getattr(component, "component_type", component.__class__.__name__),
        metadata=_component_metadata(component),
    )


def _resolve_start_port(start_port) -> tuple[Any, Any, str, Vec3, float]:
    from optodraw.core.ports import Port
    from optodraw.core.routing import _resolve_port_endpoint

    port, component, port_name = _resolve_port_endpoint(start_port)
    if component is None and isinstance(start_port, Port):
        raise ValueError("start_port must reference a component port, not a bare Port")
    default_direction = float(port.orientation_deg)
    return component, port, port_name, port.center, default_direction


def _free_space_optics_from_scene(scene) -> list[Any]:
    optics: list[Any] = []
    for node in scene.walk():
        component_type = getattr(node, "component_type", node.__class__.__name__)
        if component_type in _SKIP_SCENE_TYPES or getattr(node, "out_of_beam", False):
            continue
        if not hasattr(node, "physics_metadata"):
            continue
        metadata = node.physics_metadata()
        if metadata.get("domain") not in {None, "free_space"}:
            continue
        optics.append(node)
    return optics


def _sort_optics_along_ray(start: Vec3, direction_deg: float, optics: Iterable[Any]) -> list[Any]:
    direction = _direction_vector(direction_deg)
    ranked: list[tuple[float, float, Any]] = []
    for optic in optics:
        offset = optic.world_position - start
        projection = offset.dot(direction)
        if projection <= 1e-6:
            continue
        lateral = (offset - direction * projection).length()
        ranked.append((projection, lateral, optic))
    ranked.sort(key=lambda item: (item[0], item[1]))
    return [optic for _, _, optic in ranked]


def _aperture_radius(optic: Any) -> float | None:
    for key in ("aperture", "aperture_diameter", "diameter", "outer_diameter", "clear_aperture"):
        if hasattr(optic, key):
            try:
                return float(getattr(optic, key)) / 2.0
            except Exception:
                pass
    return None


def _warn_if_misses_aperture(optic: Any, current: Vec3, direction_deg: float) -> None:
    radius = _aperture_radius(optic)
    if radius is None or radius <= 0:
        return
    direction = _direction_vector(direction_deg)
    offset = optic.world_position - current
    projection = offset.dot(direction)
    if projection <= 1e-6:
        return
    lateral = (offset - direction * projection).length()
    if lateral > radius + 1e-6:
        warnings.warn(
            f"{getattr(optic, 'component_type', optic.__class__.__name__)} at {optic.world_position.as_tuple()[:2]} would miss a {radius*2:.1f} aperture by {lateral - radius:.1f} (lateral {lateral:.1f})",
            stacklevel=4,
        )


def trace_paraxial_ray(
    scene,
    start_port,
    direction: float | None = None,
    *,
    wavelength_nm: float = 633.0,
    exit_length: float = 20.0,
    beamsplitter_mode: str = "transmit",
    diffraction_order: int = 1,
    optics: Iterable[Any] | None = None,
) -> RayTraceResult:
    """Trace a paraxial ray from a scene port through free-space optics.

    Parameters
    ----------
    scene
        Scene containing free-space optical components.
    start_port
        ``(component, port_name)`` tuple, a single-port component, or a world
        :class:`~optodraw.core.ports.Port` tied to a component.
    direction
        Initial world-frame direction in degrees. When omitted, the port's
        outward orientation is used.
    optics
        Optional explicit optic ordering. When omitted, scene free-space
        components are sorted by distance along the initial ray.
    """

    _, port, _, port_center, default_direction = _resolve_start_port(start_port)
    direction_deg = float(default_direction if direction is None else direction)
    current = _as_vec3(port_center)
    points = [current]
    angle = direction_deg

    chain = list(optics) if optics is not None else _sort_optics_along_ray(
        current,
        direction_deg,
        _free_space_optics_from_scene(scene),
    )

    for optic in chain:
        _warn_if_misses_aperture(optic, current, angle)
        interaction = _planar_interaction(current, optic)
        points.append(interaction)
        angle, _ = _apply_optic_interaction(
            angle,
            optic,
            current=current,
            interaction=interaction,
            wavelength_nm=wavelength_nm,
            beamsplitter_mode=beamsplitter_mode,
            diffraction_order=diffraction_order,
        )
        current = interaction

    points.append(current + _direction_vector(angle) * exit_length)
    return RayTraceResult(points=points, direction_deg=angle)


def trace_ray(
    start: Vec3 | tuple[float, float] | tuple[float, float, float],
    direction_deg: float,
    optics: Iterable,
    *,
    exit_length: float = 20.0,
    beamsplitter_mode: str = "transmit",
    wavelength_nm: float = 633.0,
    diffraction_order: int = 1,
) -> RayTraceResult:
    """Trace a 2D ray through an ordered list of optics.

    The tracer uses component centers as interaction points and updates the ray
    direction according to simple optical rules:

    - ``Mirror``: specular reflection about the component normal
    - ``BeamSplitter``: either transmit or reflect depending on ``beamsplitter_mode``
    - ``Lens``: paraxial thin-lens redirect when ``focal_length`` is set
    - ``Prism``: single Snell refraction at a simplified entry face
    - ``RightAnglePrism``: fixed fold using ``deflection_angle_deg`` metadata
    - ``WedgePlate``: paraxial wedge deviation from metadata
    - ``Grating``: first-order diffraction stub using ``sin(theta_m) = m * lambda / pitch``
      for near-normal incidence (``m=1`` by default via ``diffraction_order``)
    - other optics: pass-through, keeping the current direction

    Call :func:`~optodraw.core.scene.Scene.validate_physics` before tracing mixed
    free-space and on-chip scenes to collect mode-specific warnings.
    """
    current = _as_vec3(start)
    points = [current]
    angle = direction_deg

    for optic in optics:
        _warn_if_misses_aperture(optic, current, angle)
        interaction = _planar_interaction(current, optic)
        points.append(interaction)
        angle, _ = _apply_optic_interaction(
            angle,
            optic,
            current=current,
            interaction=interaction,
            wavelength_nm=wavelength_nm,
            beamsplitter_mode=beamsplitter_mode,
            diffraction_order=diffraction_order,
        )
        current = interaction

    points.append(current + _direction_vector(angle) * exit_length)
    return RayTraceResult(points=points, direction_deg=angle)


# Beam-splitting components: a ray hitting one branches into a transmitted ray
# (passes straight through) AND a reflected ray (specular about the surface).
_SPLITTER_TYPES = frozenset(
    {"BeamSplitter", "NonPolarizingBeamSplitter", "PBS", "DichroicMirror"}
)


def _is_splitter(optic: Any) -> bool:
    return getattr(optic, "component_type", "") in _SPLITTER_TYPES or bool(getattr(optic, "dichroic", False))


def _branch_trace(
    pos: Vec3,
    dir_deg: float,
    optics: list[Any],
    acc: list[Vec3],
    results: list[RayTraceResult],
    *,
    wavelength_nm: float,
    exit_length: float,
    diffraction_order: int,
    budget: int,
) -> None:
    ordered = _sort_optics_along_ray(pos, dir_deg, optics) if budget > 0 else []
    if not ordered:
        results.append(
            RayTraceResult(points=acc + [pos + _direction_vector(dir_deg) * exit_length], direction_deg=dir_deg)
        )
        return
    optic = ordered[0]
    hit = _planar_interaction(pos, optic)
    remaining = [o for o in optics if o is not optic]  # don't re-hit the same element
    new_acc = acc + [hit]
    if _is_splitter(optic):
        reflected = _reflect(dir_deg, float(optic.world_transform.angle))
        # transmitted branch (straight through) + reflected branch
        _branch_trace(hit, dir_deg, remaining, list(new_acc), results,
                      wavelength_nm=wavelength_nm, exit_length=exit_length,
                      diffraction_order=diffraction_order, budget=budget - 1)
        _branch_trace(hit, reflected, remaining, list(new_acc), results,
                      wavelength_nm=wavelength_nm, exit_length=exit_length,
                      diffraction_order=diffraction_order, budget=budget - 1)
        return
    out_dir, _ = _apply_optic_interaction(
        dir_deg, optic, current=pos, interaction=hit,
        wavelength_nm=wavelength_nm, diffraction_order=diffraction_order,
    )
    _branch_trace(hit, out_dir, remaining, new_acc, results,
                  wavelength_nm=wavelength_nm, exit_length=exit_length,
                  diffraction_order=diffraction_order, budget=budget - 1)


def trace_branched(
    scene,
    start_port,
    direction: float | None = None,
    *,
    wavelength_nm: float = 633.0,
    exit_length: float = 20.0,
    diffraction_order: int = 1,
    max_segments: int = 16,
    optics: Iterable[Any] | None = None,
    mode: str = "schematic",
    plane: float | None = None,
) -> list[RayTraceResult]:
    """Trace a ray that **branches** at beam splitters / dichroics.

    Each branch is a separate :class:`RayTraceResult` (transmitted + reflected
    continuations at every splitter), so a dichroic produces both the reflected
    beam and the through beam. Non-splitting optics behave as in
    :func:`trace_paraxial_ray`.

    ``mode`` selects the geometry model:

    - ``"schematic"`` (default): rays snap to each optic's center — diagrams
      always look aligned, misses are impossible.
    - ``"physical"``: rays intersect each optic's **interface segments**
      (:class:`OpticalInterface`) — apertures clip, misses propagate straight,
      off-axis lens hits bend by hit height, curved mirrors focus, dichroics
      pass or reflect by wavelength, and detectors absorb.

    In physical mode the ray's height follows the scene in 3D: a periscope lifts it by its rise, a part
    with its own ``beam_height`` sets the height of its run, and lenses focus round the run's axis.
    ``plane`` is the scene's beam height above the table (default ``BEAM_HEIGHT``); the heights in the
    results are above it.
    """

    start_node, _, _, port_center, default_direction = _resolve_start_port(start_port)
    start_dir = float(default_direction if direction is None else direction)
    physical = str(mode) == "physical"
    if optics is not None:
        chain = list(optics)
    elif physical:
        chain = _physical_scene_nodes(scene)
    else:
        chain = _free_space_optics_from_scene(scene)
    start = _as_vec3(port_center)
    results: list[RayTraceResult] = []
    if physical:
        for optic in chain:
            if optic is start_node:
                continue
            transform = optic.world_transform
            if abs(float(transform.position.z) - float(start.z)) > 1e-6:
                raise ValueError("physical ray tracing requires all optical interfaces at the launch height")
        interfaces = _world_interfaces(o for o in chain if o is not start_node)

        def trace(plan: _HeightPlan | None) -> list[RayTraceResult]:
            out: list[RayTraceResult] = []
            axis = plan.heights.get("start", 0.0) if plan is not None else 0.0
            _branch_trace_physical(
                Vec3(start.x, start.y, float(start.z) + axis), start_dir, interfaces, -1,
                [Vec3(start.x, start.y, float(start.z) + axis)], out,
                wavelength_nm=wavelength_nm, exit_length=exit_length,
                diffraction_order=diffraction_order, budget=max_segments, power=1.0,
                vz=float(start.z) + axis, vaxis=axis, plan=plan,
            )
            return out

        return _two_passes(_height_plan(chain, start_node, plane), trace)
    _branch_trace(
        start, start_dir, chain, [start], results,
        wavelength_nm=wavelength_nm, exit_length=exit_length,
        diffraction_order=diffraction_order, budget=max_segments,
    )
    return results


def trace_bundle(
    scene,
    start_port,
    direction: float | None = None,
    *,
    rays: int = 6,
    width: float = 1.6,
    divergence_deg: float = 0.0,
    wavelength_nm: float = 633.0,
    exit_length: float = 20.0,
    diffraction_order: int = 1,
    max_segments: int = 16,
    optics: Iterable[Any] | None = None,
    mode: str = "physical",
    plane: float | None = None,
) -> list[RayTraceResult]:
    """Trace a cylindrical N-ray bundle from a source port (the Optiverse look).

    The bundle is a real beam cross-section — a chief ray plus a rim of rays on
    a circle of diameter ``width`` around the launch axis. The in-plane offset
    of each rim ray drives the 2D trace (lenses converge the fan, apertures
    clip it, splitters branch it); the out-of-plane offset rides along as
    ``dz`` so the 3D view shows a round beam, not a flat ribbon. Results carry
    ``ray`` (0 = chief, 1..k = rim) and are ordered chief-first.

    ``divergence_deg`` is the edge-ray half-angle: 0 (the default) launches a
    parallel bundle, above 0 fans it out from the launch face like a lamp or a
    bare fiber tip — a lens one focal length away turns that fan back into a
    beam. Each ray's tilt scales with how far off-axis it starts, so the cone
    appears to come from a point behind the source.

    Only meaningful in ``physical`` mode — schematic tracing snaps every ray to
    the same centers, so there this degenerates to the single chief ray.
    Heights follow the scene in 3D as in :func:`trace_branched` (``plane``).
    """

    if str(mode) != "physical" or rays <= 1 or width <= 0:
        return trace_branched(
            scene, start_port, direction,
            wavelength_nm=wavelength_nm, exit_length=exit_length,
            diffraction_order=diffraction_order, max_segments=max_segments,
            optics=optics, mode=mode, plane=plane,
        )
    start_node, _, _, port_center, default_direction = _resolve_start_port(start_port)
    start_dir = float(default_direction if direction is None else direction)
    launch = _direction_vector(start_dir)
    across = Vec3(-launch.y, launch.x, 0.0)
    chain = list(optics) if optics is not None else _physical_scene_nodes(scene)
    interfaces = _world_interfaces(o for o in chain if o is not start_node)
    start = _as_vec3(port_center)
    radius = float(width) / 2.0
    fan = float(divergence_deg or 0.0)

    def trace(plan: _HeightPlan | None) -> list[RayTraceResult]:
        results: list[RayTraceResult] = []
        axis = plan.heights.get("start", 0.0) if plan is not None else 0.0
        for ray_index, (in_plane, out_of_plane) in enumerate(_bundle_offsets(int(rays), radius)):
            origin = Vec3(start.x + across.x * in_plane, start.y + across.y * in_plane, axis + out_of_plane)
            # a diverging source tilts each ray by how far off-axis it launches, so
            # the edge rays ride the cone and the chief ray stays on the axis
            ray_dir = start_dir + fan * (in_plane / radius) if fan and radius else start_dir
            vslope = math.tan(math.radians(fan)) * (out_of_plane / radius) if fan and radius else 0.0
            branch: list[RayTraceResult] = []
            _branch_trace_physical(
                origin, ray_dir, interfaces, -1, [origin], branch,
                wavelength_nm=wavelength_nm, exit_length=exit_length,
                diffraction_order=diffraction_order, budget=max_segments, power=1.0,
                vz=float(start.z) + axis + out_of_plane, vslope=vslope, vaxis=axis, plan=plan,
            )
            for result in branch:
                result.ray = ray_index
                result.offset = in_plane
            results.extend(branch)
        return results

    return _two_passes(_height_plan(chain, start_node, plane), trace)


def _bundle_offsets(count: int, radius: float) -> list[tuple[float, float]]:
    """(in-plane, out-of-plane) launch offsets: chief + concentric staggered rings.

    Rings hold rays roughly proportional to their circumference, so a dense
    bundle fills the beam cross-section like physical light instead of a single
    hollow rim. Chief first — beam ids stay stable across refreshes."""

    if count <= 1 or radius <= 0:
        return [(0.0, 0.0)]
    remaining = count - 1
    n_rings = 1 if remaining <= 8 else (2 if remaining <= 20 else 3)
    weights = list(range(1, n_rings + 1))
    total = sum(weights)
    counts = [max(1, round(remaining * w / total)) for w in weights]
    while sum(counts) > remaining:
        counts[counts.index(max(counts))] -= 1
    while sum(counts) < remaining:
        counts[-1] += 1
    offsets = [(0.0, 0.0)]
    for ring, ring_count in enumerate(counts, start=1):
        r = radius * ring / n_rings
        stagger = math.pi * ring / max(ring_count, 1)  # de-align successive rings
        for k in range(ring_count):
            phi = 2.0 * math.pi * k / ring_count + stagger
            offsets.append((r * math.cos(phi), r * math.sin(phi)))
    return offsets


# -- physical mode: interface-segment tracing --------------------------------
#
# The free-space analogue of the on-chip ``optical_paths()`` protocol: every
# optic exposes its real surfaces as typed line segments, and rays interact
# where they actually hit. Components may override ``optical_interfaces()``
# (return a list of :class:`OpticalInterface` in the local drawing frame);
# anything else gets a sensible default synthesized from its type.


@dataclass
class OpticalInterface:
    """One optical surface as a line segment in a component's LOCAL frame.

    Coordinates are scene units, y-up, origin at the component center — the
    same frame ``geometry_2d`` draws in. At ``angle=0`` a plate optic's face
    runs along local +y with its normal along x (matching the schematic
    convention that a component's angle is its surface normal).
    """

    p1: tuple[float, float]
    p2: tuple[float, float]
    kind: str = "schematic"  # lens | mirror | beam_splitter | dichroic | absorber | schematic
    efl: float | None = None  # lens focal length; for curved mirrors f = R/2 (+concave, -convex)
    reflectivity: float = 1.0  # mirror power fraction
    split_t: float = 0.5  # beam-splitter transmitted power fraction
    split_r: float = 0.5  # beam-splitter reflected power fraction
    polarizing: bool = False  # PBS coating (Jones handling hooks in later)
    cutoff_nm: float | None = None  # dichroic edge wavelength
    pass_type: str = "longpass"  # "longpass" | "shortpass"
    one_sided: bool = False  # coating on ONE face; hits on the back just transmit
    front_sign: int = 1  # coated face along +n (n = left normal of p1→p2); -1 = along -n
    axes: str = "both"  # focal power applies to: "both" | "inplane" | "vertical" (cylindrical)
    open_radius: float | None = None  # aperture kind: half-width of the opening
    index: float | None = None  # refract kind: index of the glass BEHIND the face (ambient = 1)
    pitch_um: float | None = None  # grating kind: groove period, same units as the wavelength
    rise: float = 0.0  # relay kind: signed height the beam gains crossing the assembly
    turn_deg: float = 0.0  # relay kind: exit heading relative to the component's own angle
    name: str = ""


@dataclass
class _WorldInterface:
    """An :class:`OpticalInterface` resolved to world coordinates."""

    a: Vec3
    b: Vec3
    spec: OpticalInterface
    optic: Any


_MIRROR_TYPES = frozenset(
    {"Mirror", "FlipMirror", "ConcaveMirror", "ConvexMirror", "BiconcaveMirror", "BiconvexMirror", "GalvoMirror"}
)
_CUBE_SPLITTER_TYPES = frozenset({"PBS", "NonPolarizingBeamSplitter"})
_LENS_TYPES = frozenset({"Lens", "AsphericLens", "CylindricalLens", "FiberCollimator"})
# Anything a physical ray ends on: detectors, dumps, and the thing under study.
# A sample is where the incident beam stops — what leaves it is emission or
# scatter, which is a different beam, not a continuation of this one. Without
# the sample here, a beam aimed into a cryostat sails out the far wall.
_ABSORBER_TYPES = frozenset(
    {"Camera", "Photodiode", "AmplifiedPhotodetector", "PMT", "Spectrometer", "BeamDump", "PowerMeter",
     "CMOSCamera", "EMCCD", "SPADArray", "CameraSensor", "Sample", "Cryostat"}
)
_SCHEMATIC_IFACE_TYPES = frozenset({"Prism", "RightAnglePrism", "WedgePlate", "Grating"})
_REFRACTING_TYPES = frozenset({"Prism", "RightAnglePrism", "WedgePlate"})
_APERTURE_TYPES = frozenset({"Iris", "Pinhole", "ApertureStop"})

_HIT_EPS = 1e-6
_MIN_BRANCH_POWER = 1e-4
_MAX_BRANCH_RESULTS = 256  # per-launch guard: facing 50/50 splitters would otherwise go 2^n


def _body_outline(optic: Any) -> list[tuple[float, float]]:
    """The glass body's drawn outline — refracting faces ARE the drawn edges."""

    def first_polyline(node: Any) -> list | None:
        if not isinstance(node, dict):
            return None
        if node.get("type") in ("polyline", "polygon") and node.get("points"):
            return node["points"]
        for child in node.get("children") or []:
            found = first_polyline(child)
            if found:
                return found
        return None

    try:
        points = first_polyline(optic.geometry_2d()) or []
    except Exception:
        return []
    return [(float(p[0]), float(p[1])) for p in points]


def _aperture_span(optic: Any, default: float = 10.0) -> float:
    for attr in ("aperture", "diameter", "size", "width"):
        value = getattr(optic, attr, None)
        if value:
            try:
                span = float(value)
            except (TypeError, ValueError):
                continue
            if span > 0:
                return span
    return default


def _mirror_focal(optic: Any) -> float | None:
    """Mirror focal length: explicit ``focal_length`` wins (sign resolved from
    the surface type), else derived from the drawn sagitta: R = (a² + s²) / 2s,
    f = R/2 (+concave/focusing, -convex/diverging)."""

    surface = str(getattr(optic, "surface_type", "flat") or "flat")
    explicit = getattr(optic, "focal_length", None)
    if explicit:
        focal = float(explicit)
        if "convex" in surface:
            return -abs(focal)
        if "concave" in surface:
            return abs(focal)
        return focal
    if "concave" not in surface and "convex" not in surface:
        return None
    sag = float(getattr(optic, "curvature_depth", 0.0) or 0.0)
    if sag <= 1e-9:
        return None
    half = _aperture_span(optic) / 2.0
    radius = (half * half + sag * sag) / (2.0 * sag)
    focal = radius / 2.0
    return focal if "concave" in surface else -focal


def _default_interfaces(optic: Any) -> list[OpticalInterface]:
    """Synthesize interface segments for a component that declares none."""

    component_type = getattr(optic, "component_type", optic.__class__.__name__)
    half = _aperture_span(optic) / 2.0
    face = ((0.0, -half), (0.0, half))  # plate face along local y, normal along x

    if component_type in _CUBE_SPLITTER_TYPES:
        # Cube splitters draw their coating on the local 45° diagonal.
        edge = half * 0.72
        ratio = getattr(optic, "split_ratio", None) or (0.5, 0.5)
        polarizing = bool(getattr(optic, "polarization_selective", component_type != "NonPolarizingBeamSplitter"))
        return [OpticalInterface(
            p1=(-edge, -edge), p2=(edge, edge), kind="beam_splitter",
            split_t=float(ratio[0]), split_r=float(ratio[1]), polarizing=polarizing,
        )]
    if component_type == "BeamSplitter":
        cutoff = getattr(optic, "cutoff_wavelength", None)
        if getattr(optic, "dichroic", False) and cutoff:
            return [OpticalInterface(*face, kind="dichroic", cutoff_nm=float(cutoff))]
        raw_t = getattr(optic, "transmission", None)
        transmit = min(max((50.0 if raw_t is None else float(raw_t)) / 100.0, 0.0), 1.0)
        return [OpticalInterface(*face, kind="beam_splitter", split_t=transmit, split_r=1.0 - transmit)]
    if component_type == "DichroicMirror":
        # The coating is drawn on the local +x face — dichroic behavior applies
        # only there; light arriving at the back face passes through the substrate.
        cutoff = getattr(optic, "cutoff_wavelength", None)
        if cutoff:
            return [OpticalInterface(
                *face, kind="dichroic", cutoff_nm=float(cutoff),
                pass_type=str(getattr(optic, "pass_band", "longpass") or "longpass"),
                one_sided=True, front_sign=-1,
            )]
        return [OpticalInterface(*face, kind="beam_splitter")]
    if component_type in _MIRROR_TYPES:
        return [OpticalInterface(*face, kind="mirror", efl=_mirror_focal(optic))]
    metadata_kind = str(_component_metadata(optic).get("component") or "")
    if component_type in _LENS_TYPES or metadata_kind.endswith("lens"):
        focal = getattr(optic, "focal_length", None)
        if focal:
            axes = "both"
            if component_type == "CylindricalLens":
                # cylinder axis vertical ('y') → curvature acts in the scene plane
                axes = "vertical" if str(getattr(optic, "cylinder_axis", "y")).lower() == "x" else "inplane"
            return [OpticalInterface(*face, kind="lens", efl=float(focal), axes=axes)]
        return [OpticalInterface(*face, kind="schematic")]
    if component_type in _APERTURE_TYPES:
        # The plate spans the housing; only the central opening passes light.
        outer = float(getattr(optic, "outer_diameter", 0.0) or 0.0) or _aperture_span(optic)
        opening = float(getattr(optic, "aperture_diameter", 0.0) or 0.0) / 2.0
        h = outer / 2.0
        return [OpticalInterface(
            p1=(0.0, -h), p2=(0.0, h), kind="aperture", open_radius=opening, name="iris",
        )]
    if component_type in _ABSORBER_TYPES:
        # Absorb at the ENTRANCE window (the input port / aperture), not the body
        # center — rays terminate where light physically enters the detector.
        px, py, orient = 0.0, 0.0, 180.0
        span = _aperture_span(optic, default=8.0)
        try:
            ports = optic.ports()
            port = ports.get("in") or next(iter(ports.values()))
            px, py = float(port.center.x), float(port.center.y)
            orient = float(port.orientation_deg)
            span = float(getattr(port, "width", 0.0) or 0.0) or span
        except Exception:
            pass  # portless detector: fall back to a centered face
        rad = math.radians(orient)
        sx, sy = -math.sin(rad), math.cos(rad)  # window runs ⊥ to the outward normal
        h = span / 2.0
        return [OpticalInterface(
            p1=(px - sx * h, py - sy * h), p2=(px + sx * h, py + sy * h),
            kind="absorber", name="entrance",
        )]
    if component_type in _REFRACTING_TYPES:
        outline = _body_outline(optic)
        index = float(getattr(optic, "refractive_index", 0.0) or 0.0)
        if outline and index > 1.0:
            # every drawn edge is a real glass face: the ray refracts in at one
            # and out at another (the old model bent it once and forgot the exit)
            return [
                OpticalInterface(p1=outline[i], p2=outline[(i + 1) % len(outline)], kind="refract", index=index)
                for i in range(len(outline))
            ]
        return [OpticalInterface(*face, kind="schematic")]
    if component_type == "Grating":
        pitch = _grating_pitch(optic)
        if pitch:
            return [OpticalInterface(*face, kind="grating", pitch_um=float(pitch))]
        return [OpticalInterface(*face, kind="schematic")]
    if component_type in _SCHEMATIC_IFACE_TYPES:
        return [OpticalInterface(*face, kind="schematic")]
    # metadata fallback: components that self-describe via physics_metadata()
    # (e.g. user subclasses with unknown type names) still get physics
    if metadata_kind == "mirror":
        return [OpticalInterface(*face, kind="mirror", efl=_mirror_focal(optic))]
    if metadata_kind == "beam_splitter" or _component_metadata(optic).get("splitter"):
        return [OpticalInterface(*face, kind="beam_splitter")]
    return []  # purely passive visuals: physical rays pass by untouched


def _physical_scene_nodes(scene) -> list[Any]:
    """Free-space optics plus detector bodies (which absorb physical rays).

    Detectors don't carry free-space ``physics_metadata`` — schematic rays fly
    through them — but in physical mode a ray landing on a camera, photodiode,
    or beam dump should terminate at its face."""

    nodes = _free_space_optics_from_scene(scene)
    seen = {id(node) for node in nodes}
    for node in scene.walk():
        component_type = getattr(node, "component_type", node.__class__.__name__)
        if component_type in _ABSORBER_TYPES and id(node) not in seen:
            nodes.append(node)
            seen.add(id(node))
    return nodes


def _world_interfaces(optics: Iterable[Any]) -> list[_WorldInterface]:
    """Resolve every optic's interfaces to world space (rotation + translation)."""

    resolved: list[_WorldInterface] = []
    for optic in optics:
        declared = None
        getter = getattr(optic, "optical_interfaces", None)
        if callable(getter):
            try:
                declared = getter()
            except Exception:
                declared = None
        interfaces = declared if declared is not None else _default_interfaces(optic)
        if not interfaces:
            continue
        transform = optic.world_transform
        for spec in interfaces:
            a = transform.apply_to_point(Vec3(float(spec.p1[0]), float(spec.p1[1]), 0.0))
            b = transform.apply_to_point(Vec3(float(spec.p2[0]), float(spec.p2[1]), 0.0))
            if abs(a.z - b.z) > 1e-6:
                raise ValueError("physical ray tracing does not support tilted optical interfaces")
            # Planar restriction: intersection math is 2D (x, y) only. Height
            # rides the separate vz channel seeded from the launch point, so
            # translating a whole setup vertically cannot change the path.
            resolved.append(_WorldInterface(
                a=Vec3(a.x, a.y, 0.0), b=Vec3(b.x, b.y, 0.0), spec=spec, optic=optic,
            ))
    return resolved


def _ray_segment_intersection(pos: Vec3, direction: Vec3, a: Vec3, b: Vec3) -> float | None:
    """Distance t along the ray to segment AB, or None (forward hits only)."""

    rx, ry = direction.x, direction.y
    sx, sy = b.x - a.x, b.y - a.y
    denom = rx * sy - ry * sx
    if abs(denom) < 1e-12:
        return None
    qx, qy = a.x - pos.x, a.y - pos.y
    t = (qx * sy - qy * sx) / denom
    u = (qx * ry - qy * rx) / denom
    if t <= _HIT_EPS or u < -1e-9 or u > 1.0 + 1e-9:
        return None
    return t


def _segment_axes(interface: _WorldInterface) -> tuple[Vec3, Vec3]:
    """Unit vector along the segment and its (left-hand) normal."""

    along = (interface.b - interface.a).normalized()
    return along, Vec3(-along.y, along.x, 0.0)


def _hit_height(interface: _WorldInterface, hit: Vec3, along: Vec3) -> float:
    mid = (interface.a + interface.b) * 0.5
    return (hit - mid).dot(along)


def _element_z(interface: _WorldInterface) -> float:
    """World height of the optic that owns an interface (0.0 when unknown).

    Vertical thin-element kicks measure height relative to the element, so a
    whole setup translated vertically traces the same relative path.
    """

    try:
        return float(interface.optic.world_transform.position.z)
    except Exception:
        return 0.0


def _thin_element_out(direction: Vec3, interface: _WorldInterface, hit: Vec3, *, reflect: bool) -> float:
    """Paraxial thin-element interaction at the true hit point.

    Transmissive (lens): slope' = slope - h/f in the frame of the element axis.
    Reflective (curved mirror): mirror-reflect first, then the same focal kick.
    """

    along, normal = _segment_axes(interface)
    outgoing = _reflect_vec(direction, normal) if reflect else direction
    focal = interface.spec.efl
    if not focal:
        return _direction_angle(outgoing)
    axial = outgoing.dot(normal)
    if abs(axial) < 1e-9:
        return _direction_angle(outgoing)  # grazing along the element plane
    axis = normal if axial > 0 else normal * -1.0
    slope = outgoing.dot(along) / abs(axial) - _hit_height(interface, hit, along) / float(focal)
    return _direction_angle(axis + along * slope)


def _branch_trace_physical(
    pos: Vec3,
    dir_deg: float,
    interfaces: list[_WorldInterface],
    skip_index: int,
    acc: list[Vec3],
    results: list[RayTraceResult],
    *,
    wavelength_nm: float,
    exit_length: float,
    diffraction_order: int,
    budget: int,
    power: float,
    vz: float = 0.0,
    vslope: float = 0.0,
    vaxis: float = 0.0,
    plan: _HeightPlan | None = None,
    run: Any = "start",
) -> None:
    """2D branch tracer with a paraxial VERTICAL channel riding along.

    ``vz``/``vslope`` are the ray's out-of-plane height and slope; axially
    symmetric elements (lenses, curved mirrors) apply the same thin-element
    kick vertically, so a 3D bundle converges to a true point focus. Every
    appended path vertex carries the height in its z component. ``vaxis`` is
    the height of the run the ray is in (a periscope changes it), and the
    elements in a run are centred on it; ``run`` names that run in ``plan``."""

    if power < _MIN_BRANCH_POWER or len(results) >= _MAX_BRANCH_RESULTS:
        return
    direction = _direction_vector(dir_deg)
    best_t: float | None = None
    best_index = -1
    for index, interface in enumerate(interfaces):
        if index == skip_index:
            continue  # a thin element can't re-hit itself without another hit between
        t = _ray_segment_intersection(pos, direction, interface.a, interface.b)
        if t is not None and (best_t is None or t < best_t):
            best_t, best_index = t, index
    if best_t is None:
        end = pos + direction * exit_length
        results.append(RayTraceResult(
            points=acc + [Vec3(end.x, end.y, vz + vslope * exit_length)],
            direction_deg=dir_deg, power=power,
        ))
        return
    if budget <= 0:
        # out of bounces with a surface ahead: terminate AT it — never draw the
        # ray punching through a mirror for the whole exit tail
        stop = pos + direction * best_t
        results.append(RayTraceResult(
            points=acc + [Vec3(stop.x, stop.y, vz + vslope * best_t)],
            direction_deg=dir_deg, power=power,
        ))
        return
    interface = interfaces[best_index]
    spec = interface.spec
    hit2 = pos + direction * best_t
    vz_hit = vz + vslope * best_t
    hit = Vec3(hit2.x, hit2.y, vz_hit)
    path = acc + [hit]
    centre_z = vaxis + _element_z(interface)   # the element sits on its run's axis
    if plan is not None:
        from optodraw.core.beam_heights import _own_height

        own = _own_height(interface.optic)
        if own is not None:
            plan.heights.setdefault(run, own - plan.plane)

    def continue_ray(out_deg: float, out_power: float, out_vslope: float = vslope) -> None:
        _branch_trace_physical(
            hit, out_deg, interfaces, best_index, list(path), results,
            wavelength_nm=wavelength_nm, exit_length=exit_length,
            diffraction_order=diffraction_order, budget=budget - 1, power=out_power,
            vz=vz_hit, vslope=out_vslope, vaxis=vaxis, plan=plan, run=run,
        )

    if spec.kind == "absorber":
        results.append(RayTraceResult(points=path, direction_deg=dir_deg, power=power))
        return
    if spec.kind == "retro":
        # A corner cube returns the ray ANTIPARALLEL to the one that arrived,
        # displaced to the far side of its apex — that displacement is what
        # makes the return leg visible instead of drawn on top of the input.
        along, _ = _segment_axes(interface)
        centre = (interface.a + interface.b) * 0.5
        offset = (hit2 - centre).dot(along)
        exit_point = centre + along * (-offset)
        turned = path + [Vec3(exit_point.x, exit_point.y, vz_hit)]
        _branch_trace_physical(
            Vec3(exit_point.x, exit_point.y, vz_hit), dir_deg + 180.0,
            interfaces, best_index, turned, results,
            wavelength_nm=wavelength_nm, exit_length=exit_length,
            diffraction_order=diffraction_order, budget=budget - 1, power=power,
            vz=vz_hit, vslope=-vslope, vaxis=vaxis, plan=plan, run=run,
        )
        return
    if spec.kind == "relay":
        # A relay hands the beam on along ITS OWN fixed output direction, at its
        # own height, whatever direction the light arrived from — a periscope
        # takes it up a column, a pentaprism turns it a fixed 90 degrees. The
        # height change is one vertical segment: same (x, y), new z, which a
        # plan view collapses to a point. A part after it with its own beam
        # height sets the new height instead (its mounts slide on the post).
        key = id(interface.optic)
        axis = plan.heights.get(key, vaxis + float(spec.rise or 0.0)) if plan is not None \
            else vaxis + float(spec.rise or 0.0)
        lifted_z = vz_hit + axis - vaxis
        climbed = path + [Vec3(hit2.x, hit2.y, lifted_z)]
        heading = 0.0
        try:
            heading = float(interface.optic.world_transform.rotation_deg.z)
        except Exception:  # pragma: no cover - defensive: unrotatable optic
            pass
        _branch_trace_physical(
            Vec3(hit2.x, hit2.y, lifted_z), heading + float(spec.turn_deg or 0.0),
            interfaces, best_index, climbed, results,
            wavelength_nm=wavelength_nm, exit_length=exit_length,
            diffraction_order=diffraction_order, budget=budget - 1, power=power,
            vz=lifted_z, vslope=vslope, vaxis=axis, plan=plan, run=key,
        )
        return
    if spec.kind == "beam_splitter" or (spec.kind == "dichroic" and spec.cutoff_nm is None):
        _, normal = _segment_axes(interface)
        reflected = _direction_angle(_reflect_vec(direction, normal))
        continue_ray(dir_deg, power * float(spec.split_t))
        continue_ray(reflected, power * float(spec.split_r))
        return
    if spec.kind == "dichroic":
        if spec.one_sided:
            _, normal = _segment_axes(interface)
            if direction.dot(normal) * float(spec.front_sign or 1) > 0:
                continue_ray(dir_deg, power)  # back face: plain substrate, pass through
                return
        longpass = spec.pass_type != "shortpass"
        passes = (wavelength_nm >= float(spec.cutoff_nm)) if longpass else (wavelength_nm <= float(spec.cutoff_nm))
        if passes:
            continue_ray(dir_deg, power)
        else:
            _, normal = _segment_axes(interface)
            continue_ray(_direction_angle(_reflect_vec(direction, normal)), power)
        return
    if spec.kind == "filter":
        # Same in-band test as a dichroic, different fate for what fails it: a
        # filter absorbs the rejected light instead of sending it sideways.
        longpass = spec.pass_type != "shortpass"
        cutoff = float(spec.cutoff_nm or 0.0)
        passes = (wavelength_nm >= cutoff) if longpass else (wavelength_nm <= cutoff)
        if passes:
            continue_ray(dir_deg, power)
        else:
            results.append(RayTraceResult(points=path, direction_deg=dir_deg, power=0.0))
        return
    if spec.kind == "aperture":
        along, _ = _segment_axes(interface)
        opening = float(spec.open_radius or 0.0)
        radial = _hit_height(interface, hit2, along) ** 2 + (vz_hit - centre_z) ** 2
        if radial <= opening * opening:  # circular hole: through untouched
            continue_ray(dir_deg, power)
        else:  # blades block the ray — it ends on the plate
            results.append(RayTraceResult(points=path, direction_deg=dir_deg, power=power))
        return
    if spec.kind == "mirror":
        # reflection off a vertical plane keeps the vertical slope; a curved
        # mirror adds the same focal kick vertically (axially symmetric),
        # measured from the element height so translation cannot change it
        new_vslope = vslope - ((vz_hit - centre_z) / float(spec.efl)) if spec.efl else vslope
        continue_ray(
            _thin_element_out(direction, interface, hit2, reflect=True),
            power * float(spec.reflectivity),
            new_vslope,
        )
        return
    if spec.kind == "lens":
        in_plane = dir_deg if spec.axes == "vertical" else _thin_element_out(direction, interface, hit2, reflect=False)
        new_vslope = vslope
        if spec.efl and spec.axes in ("both", "vertical"):
            new_vslope = vslope - (vz_hit - centre_z) / float(spec.efl)
        continue_ray(in_plane, power, new_vslope)
        return
    if spec.kind == "refract":
        _, normal = _segment_axes(interface)
        glass = _dispersed_index(float(spec.index or 1.0), wavelength_nm)
        mid = (interface.a + interface.b) * 0.5
        center = interface.optic.world_transform.position
        outward = normal if (mid - center).dot(normal) > 0 else normal * -1.0
        n1, n2 = (1.0, glass) if direction.dot(outward) < 0 else (glass, 1.0)
        refracted = _refract_vec(direction, normal, n1, n2)
        if refracted is None:  # total internal reflection: stays in the glass
            continue_ray(_direction_angle(_reflect_vec(direction, normal.normalized())), power)
        else:
            continue_ray(_direction_angle(refracted), power)
        return
    if spec.kind == "grating":
        along, normal = _segment_axes(interface)
        pitch = float(spec.pitch_um or 0.0)
        sin_in = direction.normalized().dot(along)  # component along the grooves' plane
        sin_out = sin_in + diffraction_order * (wavelength_nm / 1000.0) / pitch if pitch > 0 else sin_in
        if abs(sin_out) > 1.0:  # that order is evanescent — light goes straight on
            continue_ray(dir_deg, power)
            return
        forward = 1.0 if direction.dot(normal) >= 0 else -1.0
        out = along * sin_out + normal * (forward * math.sqrt(max(0.0, 1.0 - sin_out * sin_out)))
        continue_ray(_direction_angle(out), power)
        return
    # "schematic" fallback: the existing per-type interaction math, applied at
    # the true geometric hit point (prisms, gratings, wedges, f-less lenses).
    out_deg, _label = _apply_optic_interaction(
        dir_deg, interface.optic, current=pos, interaction=hit,
        wavelength_nm=wavelength_nm, diffraction_order=diffraction_order,
    )
    continue_ray(out_deg, power)
