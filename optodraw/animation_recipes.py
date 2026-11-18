"""Prebuilt animation recipes for common optics teaching scenarios.

Each helper returns an :class:`~optodraw.animation.AnimationTimeline` ready for
``render_gif`` or ``render_video``.

Examples
--------

Michelson / MZI interference (see :func:`~optodraw.presets.ftir_setup`)::

    from optodraw import animate_interference
    from optodraw.presets import ftir_setup

    scene = ftir_setup()
    beams = [c for c in scene.walk() if c.component_type == "Beam"]
    bs = next(c for c in scene.walk() if c.label == "G1")
    tl = animate_interference(scene, beams[0], beams[1], bs, phase_steps=8)
    tl.render_gif("ftir_interference.gif")

Ring resonance wavelength scan (see :func:`~optodraw.layout.build_ring_filter`)::

    from optodraw import animate_resonance_scan
    from optodraw.layout import build_ring_filter

    built = build_ring_filter()
    scene, ring = built["scene"], built["ring"]
    tl = animate_resonance_scan(scene, ring, wavelength_steps=10)
    tl.render_gif("ring_scan.gif")

Lens focusing (paraxial waist stub)::

    from optodraw import Scene, Laser, Lens, Beam, animate_focus

    scene = Scene(platform="free_space")
    laser = scene.add(Laser(center=(-40, 0), wavelength=633, label="HeNe"))
    lens = scene.add(Lens(center=(0, 0), focal_length=50.0, label="L1"))
    beam = scene.add(Beam(laser, lens, wavelength=633))
    tl = animate_focus(scene, lens)
    tl.render_gif("focus.gif")
"""

from __future__ import annotations

import math
from os import PathLike
from pathlib import Path
from typing import Any

from optodraw.animation import AnimationTimeline
from optodraw.core.beam import Beam
from optodraw.core.component import Group
from optodraw.core.interferometer import trace_mzm_transfer
from optodraw.core.physics import (
    GaussianBeamState,
    grating_diffraction_angle_deg,
    snell_refract,
    trace_paraxial_beam,
)
from optodraw.core.resonator import trace_ring_resonance
from optodraw.core.routing import Route


def _timeline(scene) -> AnimationTimeline:
    if isinstance(scene, AnimationTimeline):
        return scene
    return scene.timeline()


def _is_path(component: Any) -> bool:
    if isinstance(component, (Beam, Route)):
        return True
    component_type = getattr(component, "component_type", component.__class__.__name__)
    return component_type in {"Beam", "Route", "WaveguideRoute", "FiberRoute"}


def _routes_for_resonator(scene, resonator) -> list[Route]:
    resonator_pos = resonator.world_position
    ring_radius = float(getattr(resonator, "ring_radius", 30.0) or 30.0)
    threshold = max(ring_radius * 2.5, 35.0)
    routes: list[Route] = []
    for component in scene.walk():
        if isinstance(component, Beam) or not _is_path(component):
            continue
        for point in component.resolve_points():
            distance = math.hypot(point[0] - resonator_pos.x, point[1] - resonator_pos.y)
            if distance <= threshold:
                routes.append(component)
                break
    if not routes:
        routes = [
            component
            for component in scene.walk()
            if _is_path(component) and not isinstance(component, Beam)
        ]
    return routes


def _beam_through_lens(scene, lens) -> Beam | None:
    lens_id = id(lens)
    for component in scene.walk():
        if not isinstance(component, Beam):
            continue
        if any(id(anchor) == lens_id for anchor in component.anchors):
            return component
    return None


def _upstream_source(beam: Beam) -> Any | None:
    if not beam.anchors:
        return None
    first = beam.anchors[0]
    if isinstance(first, Beam):
        return None
    from optodraw.core.component import Component

    return first if isinstance(first, Component) else None


def _interference_regime(through_power: float) -> str:
    if through_power >= 0.75:
        return "Constructive interference"
    if through_power <= 0.25:
        return "Destructive interference"
    return "Partial interference"


def animate_interference(
    scene,
    arm1,
    arm2,
    combiner,
    *,
    phase_steps: int = 8,
    caption: str = "",
) -> AnimationTimeline:
    """Build a two-arm interference tutoring timeline.

    Reveals the combiner and both arms, sweeps relative phase from 0 to 2π,
    and labels constructive vs destructive recombination using the balanced MZI
    stub ``T = cos²(Δφ/2)``.

    Parameters
    ----------
    scene : Scene | AnimationTimeline
        Scene (or existing timeline) to append steps to.
    arm1, arm2 : Beam | Route | Component
        The two interferometer arms — typically beam paths or waveguide routes.
    combiner : Component
        Splitter/combiner element (e.g. ``BeamSplitter`` or MZI coupler).
    phase_steps : int
        Number of relative-phase samples across one full 2π sweep.
    caption : str
        Optional opening caption for the lesson.
    """

    tl = _timeline(scene)
    if caption:
        tl.pause(0.5, caption=caption)

    tl.show(combiner, caption=getattr(combiner, "label", "") or "Combiner")

    for arm in (arm1, arm2):
        if _is_path(arm):
            tl.trace(arm, caption=f"{getattr(arm, 'label', 'Arm') or 'Arm'} path")
        else:
            tl.show(arm, caption=getattr(arm, "label", "") or "Arm")

    steps = max(int(phase_steps), 1)
    for index in range(steps):
        phase_rad = 2.0 * math.pi * index / steps
        through_power = math.cos(phase_rad / 2.0) ** 2
        regime = _interference_regime(through_power)
        tl.pause(
            1.0,
            caption=(
                f"Δφ = {math.degrees(phase_rad):.0f}° — {regime} "
                f"(T ≈ {through_power:.2f})"
            ),
        )

    return tl


def animate_resonance_scan(
    scene,
    resonator,
    *,
    wavelength_steps: int = 10,
    caption: str = "",
    wavelength_nm: float = 1550.0,
) -> AnimationTimeline:
    """Build a microring resonance wavelength-scan tutoring timeline.

    Uses :func:`~optodraw.core.resonator.trace_ring_resonance` to sample
    transmission across a span around the nominal resonance, emitting
    ``cavity_power`` highlight steps with through-port power captions.

    Parameters
    ----------
    scene : Scene | AnimationTimeline
        Scene (or existing timeline) to append steps to.
    resonator : MicroringResonator | RacetrackResonator | ...
        Ring or racetrack resonator component.
    wavelength_steps : int
        Number of wavelength samples in the scan.
    caption : str
        Optional opening caption.
    wavelength_nm : float
        Center wavelength (nm) for the scan span when metadata lacks λ₀.
    """

    tl = _timeline(scene)
    if caption:
        tl.pause(0.5, caption=caption)

    tl.show(resonator, caption=getattr(resonator, "label", "") or "Resonator")

    routes = _routes_for_resonator(scene, resonator)
    if routes:
        tl.trace(routes[0], caption="Guided mode reaches the resonator")

    probe = trace_ring_resonance(resonator, wavelength_nm=wavelength_nm)
    lambda0 = float(probe["lambda0_nm"])
    fsr = float(probe.get("fsr_nm") or 1.0)
    span = max(fsr, 0.5)
    steps = max(int(wavelength_steps), 1)

    for index in range(steps):
        if steps == 1:
            wl = lambda0
        else:
            wl = lambda0 - span / 2.0 + span * index / (steps - 1)
        result = trace_ring_resonance(resonator, wavelength_nm=wl)
        transmission = float(result["transmission"])
        tl.cavity_power(
            resonator,
            caption=(
                f"λ = {wl:.2f} nm — T = {transmission:.2f} "
                f"(λ₀ ≈ {lambda0:.2f} nm)"
            ),
            steps=6,
        )

    return tl


def animate_focus(
    scene,
    lens,
    *,
    caption: str = "",
    input_beam: GaussianBeamState | None = None,
    exit_length: float | None = None,
) -> AnimationTimeline:
    """Build a paraxial lens-focusing tutoring timeline.

    Runs :func:`~optodraw.core.physics.trace_paraxial_beam` through ``lens``
    and emits ``cavity_power`` steps whose captions report the evolving beam
    waist (stub metadata for renderers).

    Parameters
    ----------
    scene : Scene | AnimationTimeline
        Scene (or existing timeline) to append steps to.
    lens : Lens
        Focusing lens component.
    caption : str
        Optional opening caption.
    input_beam : GaussianBeamState, optional
        Incoming Gaussian beam; defaults to a collimated 633 nm stub.
    exit_length : float, optional
        Propagation past the lens; defaults to the lens focal length.
    """

    tl = _timeline(scene)
    if caption:
        tl.pause(0.5, caption=caption)

    beam = _beam_through_lens(scene, lens)
    source = _upstream_source(beam) if beam is not None else None

    if source is not None:
        tl.show(source, caption=getattr(source, "label", "") or "Source")
    tl.show(lens, caption=getattr(lens, "label", "") or "Lens")

    if beam is not None:
        tl.trace(beam, caption="Collimated beam enters the lens")

    focal = float(getattr(lens, "focal_length", 0.0) or 50.0)
    propagate = float(exit_length if exit_length is not None else focal)
    beam_state = input_beam or GaussianBeamState(wavelength=0.633, waist_radius=1.5)

    if source is not None:
        start = source.world_position
    elif beam is not None and beam.anchors:
        first = beam.anchors[0]
        if hasattr(first, "world_position"):
            start = first.world_position
        else:
            start = lens.world_position
    else:
        start = lens.world_position

    lens_pos = lens.world_position
    direction_deg = math.degrees(
        math.atan2(lens_pos.y - start.y, lens_pos.x - start.x)
    )
    trace = trace_paraxial_beam(
        start,
        direction_deg,
        [lens],
        input_beam=beam_state,
        exit_length=propagate,
    )

    focus_samples = [
        sample
        for sample in trace.samples
        if sample.event in {"thin_lens", "exit"}
    ] or [trace.samples[-1]]

    for sample in focus_samples:
        waist = sample.beam.waist_radius
        radius = sample.beam.beam_radius
        event = sample.event.replace("_", " ")
        tl.cavity_power(
            lens,
            caption=(
                f"{event.title()} — waist w₀ ≈ {waist:.2f}, "
                f"beam radius w ≈ {radius:.2f}"
            ),
            steps=5,
        )

    return tl


def _resolve_vpi(mzm) -> float:
    metadata = getattr(mzm, "physics_metadata", lambda: {})()
    if metadata.get("Vpi") is not None:
        return float(metadata["Vpi"])
    if metadata.get("Vpi_stub_v") is not None:
        return float(metadata["Vpi_stub_v"])
    return 4.0


def _routes_for_mzm(scene, mzm) -> list[Route]:
    mzm_id = id(mzm)
    routes: list[Route] = []
    for component in scene.walk():
        if not _is_path(component) or isinstance(component, Beam):
            continue
        start = getattr(component, "start_component", None)
        end = getattr(component, "end_component", None)
        if start is not None and id(start) == mzm_id:
            routes.append(component)
        elif end is not None and id(end) == mzm_id:
            routes.append(component)
    return routes


def animate_modulation(
    scene,
    mzm,
    *,
    voltage_steps: int = 8,
    caption: str = "",
    Vpi: float | None = None,
    wavelength_nm: float = 1550.0,
) -> AnimationTimeline:
    """Build an MZM drive-voltage tutoring timeline.

    Sweeps electrical drive from 0 to ``Vpi`` and uses
    :func:`~optodraw.core.interferometer.trace_mzm_transfer` to emit
    ``cavity_power`` steps whose captions report the optical intensity waveform.

    Parameters
    ----------
    scene : Scene | AnimationTimeline
        Scene (or existing timeline) to append steps to.
    mzm : MZM
        Mach-Zehnder modulator component.
    voltage_steps : int
        Number of drive-voltage samples across one Vπ span.
    caption : str
        Optional opening caption.
    Vpi : float, optional
        Half-wave voltage override; defaults to component metadata or 4 V.
    wavelength_nm : float
        Optical wavelength for the transfer stub.
    """

    tl = _timeline(scene)
    if caption:
        tl.pause(0.5, caption=caption)

    vpi = float(Vpi if Vpi is not None else _resolve_vpi(mzm))
    tl.show(mzm, caption=getattr(mzm, "label", "") or "MZM")

    routes = _routes_for_mzm(tl.scene, mzm)
    if routes:
        tl.trace(routes[0], caption="Optical path through the modulator")

    steps = max(int(voltage_steps), 1)
    for index in range(steps):
        if steps == 1:
            voltage = 0.0
        else:
            voltage = vpi * index / (steps - 1)
        result = trace_mzm_transfer(
            mzm,
            drive_voltage=voltage,
            Vpi=vpi,
            wavelength_nm=wavelength_nm,
        )
        through = float(result["through_power"])
        tl.cavity_power(
            mzm,
            caption=(
                f"V = {voltage:.2f} V — T ≈ {through:.2f} "
                f"(Vπ = {vpi:.2f} V)"
            ),
            steps=6,
        )

    return tl


def animate_mzm_mechanism(
    scene,
    mzm,
    *,
    phase_steps: int = 6,
    caption: str = "",
    Vpi: float | None = None,
    wavelength_nm: float = 1550.0,
) -> AnimationTimeline:
    """Build an MZM phase-interference tutoring timeline using ``wave_travel``.

    Shows the modulator, animates optical propagation along the first connected
    route, then sweeps relative phase in one arm with transfer-function captions.
    """

    tl = _timeline(scene)
    if caption:
        tl.pause(0.5, caption=caption)

    vpi = float(Vpi if Vpi is not None else _resolve_vpi(mzm))
    tl.show(mzm, caption=getattr(mzm, "label", "") or "MZM")

    routes = _routes_for_mzm(tl.scene, mzm)
    if routes:
        tl.wave_travel(routes[0], caption="Optical mode splits into two arms", steps=12)
        if len(routes) > 1:
            tl.wave_travel(routes[1], caption="Phase accumulates in the driven arm", steps=10)

    tl.pause(0.8, caption="Recombination converts phase difference to intensity")

    steps = max(int(phase_steps), 1)
    for index in range(steps):
        if steps == 1:
            voltage = 0.0
        else:
            voltage = vpi * index / (steps - 1)
        result = trace_mzm_transfer(
            mzm,
            drive_voltage=voltage,
            Vpi=vpi,
            wavelength_nm=wavelength_nm,
        )
        through = float(result["through_power"])
        regime = _interference_regime(through)
        tl.cavity_power(
            mzm,
            caption=(
                f"V = {voltage:.2f} V — {regime} (T ≈ {through:.2f}, Vπ = {vpi:.2f} V)"
            ),
            steps=5,
        )

    return tl


def animate_ring_coupling(
    scene,
    ring,
    *,
    coupling_steps: int = 6,
    caption: str = "",
    wavelength_nm: float = 1550.0,
) -> AnimationTimeline:
    """Build a bus-to-ring coupling tutoring timeline using ``wave_travel``.

    Traces the bus waveguide, animates evanescent coupling into the ring, and
    highlights resonance build-up with cavity-power captions.
    """

    tl = _timeline(scene)
    if caption:
        tl.pause(0.5, caption=caption)

    tl.show(ring, caption=getattr(ring, "label", "") or "Microring")

    routes = _routes_for_resonator(scene, ring)
    if routes:
        tl.wave_travel(routes[0], caption="Guided mode travels along the bus waveguide", steps=12)

    tl.pause(0.6, caption="Evanescent field couples power into the ring cavity")

    probe = trace_ring_resonance(ring, wavelength_nm=wavelength_nm)
    lambda0 = float(probe["lambda0_nm"])
    fsr = float(probe.get("fsr_nm") or 1.0)
    span = max(fsr * 0.5, 0.3)
    steps = max(int(coupling_steps), 1)

    for index in range(steps):
        if steps == 1:
            wl = lambda0
        else:
            wl = lambda0 - span / 2.0 + span * index / (steps - 1)
        result = trace_ring_resonance(ring, wavelength_nm=wl)
        transmission = float(result["transmission"])
        tl.cavity_power(
            ring,
            caption=(
                f"λ = {wl:.2f} nm — bus transmission T = {transmission:.2f} "
                f"(λ₀ ≈ {lambda0:.2f} nm)"
            ),
            steps=6,
        )

    return tl


def _try_load_gds_layout(source: str | PathLike[str]):
    try:
        from optodraw.gds.layout import GDSLayout, load_gds_layout
    except ImportError:
        return None

    if isinstance(source, GDSLayout):
        return source

    if isinstance(source, (str, Path)):
        path = Path(source)
        if path.suffix.lower() == ".gds" or path.exists():
            return load_gds_layout(path)
    return None


def _layer_reveal_targets(gds_layout_or_scene) -> tuple[Any, list[tuple[Any, str]]]:
    """Return ``(scene, [(component, layer_caption), ...])`` for layer reveal."""

    layout = _try_load_gds_layout(gds_layout_or_scene)
    if layout is not None:
        scene, _model = layout.build_scene(title="GDS layer stack")
        targets: list[tuple[Any, str]] = []
        records = sorted(
            (record for record in layout.layer_records if record.visible),
            key=lambda record: (record.zmin, record.name, record.spec),
        )
        for record in records:
            group = scene.add(
                Group(
                    label=record.name or f"L{record.spec[0]}/{record.spec[1]}",
                )
            )
            layer_caption = (
                f"{record.name} — z = {record.zmin:.3f} µm, "
                f"{record.material_preset}"
            )
            targets.append((group, layer_caption))
        return scene, targets

    if isinstance(gds_layout_or_scene, AnimationTimeline):
        scene = gds_layout_or_scene.scene
    else:
        scene = gds_layout_or_scene

    groups = [
        component
        for component in scene.walk()
        if isinstance(component, Group)
        or getattr(component, "component_type", "") == "Group"
    ]
    if groups:
        return scene, [
            (group, getattr(group, "label", "") or "Layer group")
            for group in groups
        ]

    stub_labels = ("Substrate", "BOX", "Waveguide", "Cladding", "Metal")
    targets = []
    for index, label in enumerate(stub_labels):
        group = scene.add(Group(label=label))
        targets.append((group, f"{label} — stack level {index + 1}"))
    return scene, targets


def animate_layer_stack(
    gds_layout_or_scene,
    *,
    caption: str = "",
) -> AnimationTimeline:
    """Build a GDS layer-stack reveal tutoring timeline.

    When a GDS layout (or ``.gds`` path) is provided and the ``gds`` extra is
    available, layers are ordered by ``zmin`` from
    :func:`~optodraw.gds.layout.load_gds_layout`. Otherwise stub
    :class:`~optodraw.core.component.Group` layers are synthesized on the scene.

    Parameters
    ----------
    gds_layout_or_scene : GDSLayout | str | PathLike | Scene | AnimationTimeline
        Loaded layout, GDS filepath, or scene containing layer groups.
    caption : str
        Optional opening caption.
    """

    scene, targets = _layer_reveal_targets(gds_layout_or_scene)
    tl = _timeline(scene)
    if caption:
        tl.pause(0.5, caption=caption)

    for component, layer_caption in targets:
        tl.show(component, caption=layer_caption)

    if len(targets) > 1:
        tl.pause(
            1.0,
            caption=f"Full stack — {len(targets)} layers revealed bottom to top",
        )

    return tl


def _dispersion_wavelengths(
    element,
    *,
    wavelength_steps: int,
    center_nm: float = 633.0,
    span_nm: float = 120.0,
) -> list[float]:
    steps = max(int(wavelength_steps), 1)
    if steps == 1:
        return [center_nm]
    half = span_nm / 2.0
    return [center_nm - half + span_nm * index / (steps - 1) for index in range(steps)]


def _refractive_index_stub(base_n: float, wavelength_nm: float) -> float:
    """Simple Cauchy dispersion stub: ``n(λ) = n₀ + B / λ²``."""

    lambda_um = float(wavelength_nm) / 1000.0
    if lambda_um <= 0:
        return base_n
    return base_n + 0.004 / (lambda_um**2)


def _dispersion_exit_angle_deg(element, wavelength_nm: float) -> float | None:
    component_type = getattr(element, "component_type", element.__class__.__name__)

    if component_type == "Grating":
        pitch = float(getattr(element, "pitch", 0.0) or 1.0)
        return grating_diffraction_angle_deg(pitch, wavelength_nm)

    if component_type == "Prism":
        n0 = float(getattr(element, "refractive_index", 1.515) or 1.515)
        n = _refractive_index_stub(n0, wavelength_nm)
        return snell_refract(30.0, n1=1.0, n2=n)

    pitch = float(getattr(element, "pitch", 0.0) or 0.0)
    if pitch > 0:
        return grating_diffraction_angle_deg(pitch, wavelength_nm)
    n0 = float(getattr(element, "refractive_index", 0.0) or 0.0)
    if n0 > 0:
        return snell_refract(30.0, n1=1.0, n2=_refractive_index_stub(n0, wavelength_nm))
    return None


def animate_dispersion(
    scene,
    dispersive_element,
    *,
    wavelength_steps: int = 6,
    caption: str = "",
    center_wavelength_nm: float = 633.0,
    wavelength_span_nm: float = 120.0,
) -> AnimationTimeline:
    """Build a multi-wavelength dispersion fan tutoring timeline.

    Samples prism or grating exit angles across a wavelength span and labels
    angular spread using grating-diffraction or Snell stubs.

    Parameters
    ----------
    scene : Scene | AnimationTimeline
        Scene (or existing timeline) to append steps to.
    dispersive_element : Prism | Grating | ...
        Dispersive optic whose metadata drives the angle stub.
    wavelength_steps : int
        Number of wavelength samples in the fan.
    caption : str
        Optional opening caption.
    center_wavelength_nm : float
        Center wavelength (nm) for the scan span.
    wavelength_span_nm : float
        Total wavelength span (nm) sampled by the fan.
    """

    tl = _timeline(scene)
    if caption:
        tl.pause(0.5, caption=caption)

    label = getattr(dispersive_element, "label", "") or "Dispersive element"
    tl.show(dispersive_element, caption=label)

    wavelengths = _dispersion_wavelengths(
        dispersive_element,
        wavelength_steps=wavelength_steps,
        center_nm=center_wavelength_nm,
        span_nm=wavelength_span_nm,
    )
    angles: list[float] = []
    for wavelength_nm in wavelengths:
        angle = _dispersion_exit_angle_deg(dispersive_element, wavelength_nm)
        if angle is not None:
            angles.append(angle)
        caption_text = (
            f"λ = {wavelength_nm:.0f} nm — θ ≈ {angle:.1f}°"
            if angle is not None
            else f"λ = {wavelength_nm:.0f} nm — evanescent order"
        )
        tl.cavity_power(
            dispersive_element,
            caption=caption_text,
            steps=5,
        )

    if len(angles) >= 2:
        spread = max(angles) - min(angles)
        tl.pause(
            1.0,
            caption=(
                f"Angular spread Δθ ≈ {spread:.1f}° "
                f"({wavelengths[0]:.0f}–{wavelengths[-1]:.0f} nm)"
            ),
        )

    return tl


def _routes_for_component(scene, component) -> list[Route]:
    """Return routes attached to ``component`` via ``start_/end_component``."""

    component_id = id(component)
    routes: list[Route] = []
    for candidate in scene.walk():
        if not _is_path(candidate) or isinstance(candidate, Beam):
            continue
        start = getattr(candidate, "start_component", None)
        end = getattr(candidate, "end_component", None)
        if (start is not None and id(start) == component_id) or (
            end is not None and id(end) == component_id
        ):
            routes.append(candidate)
    return routes


def _route_endpoint_is(route, component) -> str | None:
    """Return ``"start"`` / ``"end"`` if ``route`` touches ``component``."""

    component_id = id(component)
    if getattr(route, "start_component", None) is not None and id(route.start_component) == component_id:
        return "start"
    if getattr(route, "end_component", None) is not None and id(route.end_component) == component_id:
        return "end"
    return None


def _classify_grating_routes(scene, coupler) -> tuple[list[Route], list[Route]]:
    """Split routes touching ``coupler`` into ``(fiber_routes, chip_routes)``.

    A ``fiber``/``FiberRoute`` is treated as the fiber side, everything else as
    the chip side. Falls back to splitting by the first route returned.
    """

    fiber_routes: list[Route] = []
    chip_routes: list[Route] = []
    for route in _routes_for_component(scene, coupler):
        component_type = getattr(route, "component_type", route.__class__.__name__)
        if component_type == "FiberRoute" or getattr(route, "kind", "") == "fiber":
            fiber_routes.append(route)
        else:
            chip_routes.append(route)
    return fiber_routes, chip_routes


def _coupling_efficiency_caption(coupler, efficiency: float) -> str:
    label = getattr(coupler, "label", "") or "Grating coupler"
    pct = max(0.0, min(1.0, efficiency)) * 100.0
    loss_db = -10.0 * math.log10(max(efficiency, 1e-6))
    return f"{label} — coupling η ≈ {pct:.0f}% (loss ≈ {loss_db:.1f} dB, mode mismatch stub)"


def _resolve_grating_efficiency(coupler, override: float | None) -> float:
    if override is not None:
        return max(min(float(override), 1.0), 0.0)
    metadata = getattr(coupler, "physics_metadata", lambda: {})()
    eta = metadata.get("coupling_efficiency")
    if eta is not None:
        return max(min(float(eta), 1.0), 0.0)
    return 0.55


def _offset_triplet(value: tuple[float, ...] | list[float], *, name: str) -> tuple[float, float, float]:
    if len(value) == 2:
        return (float(value[0]), float(value[1]), 0.0)
    if len(value) == 3:
        return (float(value[0]), float(value[1]), float(value[2]))
    raise ValueError(f"{name} must contain 2 or 3 offsets")


def _alignment_efficiency(
    offset: tuple[float, float, float],
    *,
    mode_field_diameter_um: float,
    axial_tolerance_um: float,
) -> tuple[float, float]:
    if mode_field_diameter_um <= 0:
        raise ValueError("mode_field_diameter_um must be > 0")
    if axial_tolerance_um <= 0:
        raise ValueError("axial_tolerance_um must be > 0")

    dx, dy, dz = offset
    mode_radius = mode_field_diameter_um / 2.0
    transverse = dx * dx + dy * dy
    eta_xy = math.exp(-2.0 * transverse / max(mode_radius * mode_radius, 1e-9))
    eta_z = math.exp(-(dz / axial_tolerance_um) ** 2)
    eta = max(0.0, min(1.0, eta_xy * eta_z))
    loss_db = 0.0 if eta >= 0.999999 else -10.0 * math.log10(max(eta, 1e-6))
    return eta, loss_db


def _default_mode_field_diameter(coupler) -> float:
    for attr in ("fiber_mode_diameter", "fiber_port_width"):
        value = getattr(coupler, attr, None)
        if value is not None:
            return float(value)
    return 10.4


def animate_fiber_alignment(
    scene,
    coupler,
    *,
    caption: str = "",
    start_offset_um: tuple[float, ...] | list[float] = (6.0, 3.0, 0.0),
    end_offset_um: tuple[float, ...] | list[float] = (0.0, 0.0, 0.0),
    alignment_steps: int = 6,
    mode_field_diameter_um: float | None = None,
    axial_tolerance_um: float = 25.0,
    pulse_width: float = 0.18,
    wavelength_nm: float = 1550.0,
    steps: int = 14,
) -> AnimationTimeline:
    """Visualize active fiber-to-chip alignment and mode-overlap loss.

    Samples a straight-line alignment move from ``start_offset_um`` to
    ``end_offset_um`` and highlights the coupler with Gaussian-overlap captions
    reporting transverse/axial offset, coupling efficiency, and insertion loss.
    If routes touch the coupler, a reference pulse is animated on the fiber side
    before the sweep and on the chip side after alignment.
    """

    if alignment_steps < 1:
        raise ValueError("alignment_steps must be >= 1")

    start = _offset_triplet(start_offset_um, name="start_offset_um")
    end = _offset_triplet(end_offset_um, name="end_offset_um")
    mode_field = float(mode_field_diameter_um if mode_field_diameter_um is not None else _default_mode_field_diameter(coupler))

    tl = _timeline(scene)
    if caption:
        tl.pause(0.5, caption=caption)

    label = getattr(coupler, "label", "") or "Fiber coupler"
    tl.show(coupler, caption=label)

    fiber_routes, chip_routes = _classify_grating_routes(tl.scene, coupler)
    if not fiber_routes and chip_routes:
        fiber_routes = [chip_routes[0]]

    for route in fiber_routes[:1]:
        tl.wave_travel(
            route,
            caption=f"Reference pulse at fiber facet ({label})",
            steps=steps,
            pulse_width=pulse_width,
            wavelength_nm=wavelength_nm,
            opacity_envelope="gaussian",
        )

    sample_count = max(int(alignment_steps), 1)
    for index in range(sample_count):
        if sample_count == 1:
            alpha = 1.0
        else:
            alpha = index / (sample_count - 1)
        offset = tuple(start[axis] + (end[axis] - start[axis]) * alpha for axis in range(3))
        eta, loss_db = _alignment_efficiency(
            offset,
            mode_field_diameter_um=mode_field,
            axial_tolerance_um=float(axial_tolerance_um),
        )
        dx, dy, dz = offset
        tl.cavity_power(
            coupler,
            caption=(
                f"Alignment {index + 1}/{sample_count}: "
                f"Δx={dx:.2f} µm, Δy={dy:.2f} µm, Δz={dz:.2f} µm — "
                f"η≈{eta:.2f}, loss≈{loss_db:.1f} dB"
            ),
            steps=5,
        )

    for route in chip_routes[:1]:
        tl.wave_travel(
            route,
            caption=f"Aligned mode launches into chip ({label})",
            steps=steps,
            pulse_width=pulse_width,
            wavelength_nm=wavelength_nm,
            opacity_envelope="gaussian",
            trail=True,
        )

    return tl


def animate_grating_coupler_in_out(
    scene,
    coupler,
    *,
    caption: str = "",
    direction: str = "both",
    coupling_efficiency: float | None = None,
    pulse_width: float = 0.18,
    wavelength_nm: float = 1550.0,
    steps: int = 14,
) -> AnimationTimeline:
    """Build a fiber-to-chip / chip-to-fiber tutoring timeline.

    Animates a wave packet across whichever routes touch ``coupler`` and
    labels the mode-mismatch / coupling-efficiency stub. ``direction`` selects
    the order of the in/out passes.

    Parameters
    ----------
    scene : Scene | AnimationTimeline
        Scene (or existing timeline) to append steps to.
    coupler : Component
        Grating coupler (vertical, focused or array) being illustrated.
    caption : str
        Optional opening caption.
    direction : {"both", "in", "out"}
        Which directions to animate. ``"both"`` plays fiber→chip then chip→fiber.
    coupling_efficiency : float, optional
        Override the η stub used in the caption (defaults to coupler metadata).
    pulse_width : float
        Wave-packet width as a fraction of each route, passed to ``wave_travel``.
    wavelength_nm : float
        Wavelength used to colorize the pulse via ``wavelength_to_hex``.
    steps : int
        Frames per wave_travel pass.
    """

    if direction not in {"both", "in", "out"}:
        raise ValueError("direction must be 'both', 'in', or 'out'")

    tl = _timeline(scene)
    if caption:
        tl.pause(0.5, caption=caption)

    label = getattr(coupler, "label", "") or "Grating coupler"
    tl.show(coupler, caption=label)

    efficiency = _resolve_grating_efficiency(coupler, coupling_efficiency)
    eff_caption = _coupling_efficiency_caption(coupler, efficiency)

    fiber_routes, chip_routes = _classify_grating_routes(tl.scene, coupler)
    # When the user did not annotate fiber routes, treat the first route as fiber
    if not fiber_routes and chip_routes:
        fiber_routes = [chip_routes[0]]

    def _in_pass() -> None:
        for route in fiber_routes:
            tl.wave_travel(
                route,
                caption=f"Fiber → chip — {label}",
                steps=steps,
                pulse_width=pulse_width,
                wavelength_nm=wavelength_nm,
                opacity_envelope="gaussian",
            )
        for route in chip_routes:
            tl.wave_travel(
                route,
                caption=f"Guided mode launched into chip ({label})",
                steps=steps,
                pulse_width=pulse_width,
                wavelength_nm=wavelength_nm,
                opacity_envelope="gaussian",
                trail=True,
            )

    def _out_pass() -> None:
        for route in chip_routes:
            tl.wave_travel(
                route,
                caption=f"Chip → grating ({label})",
                steps=steps,
                pulse_width=pulse_width,
                wavelength_nm=wavelength_nm,
                opacity_envelope="gaussian",
            )
        for route in fiber_routes:
            tl.wave_travel(
                route,
                caption=f"Grating → fiber ({label})",
                steps=steps,
                pulse_width=pulse_width,
                wavelength_nm=wavelength_nm,
                opacity_envelope="gaussian",
                trail=True,
            )

    if direction in {"in", "both"}:
        _in_pass()
    if direction in {"out", "both"}:
        _out_pass()

    tl.cavity_power(coupler, caption=eff_caption, steps=6)
    return tl


def _dc_coupling_envelope(L: float, Lc: float) -> tuple[float, float]:
    """Sinusoidal codirectional-coupling envelope.

    Returns ``(P_through, P_cross)`` for a coupler of physical length ``L``
    and full-crossover length ``Lc``. At ``L = Lc`` all power has been
    transferred to the cross port (``P_cross = 1``).
    """

    if Lc <= 0:
        return (1.0, 0.0)
    phase = math.pi * L / (2.0 * Lc)
    through = math.cos(phase) ** 2
    cross = math.sin(phase) ** 2
    return (through, cross)


def animate_directional_coupler_power_transfer(
    scene,
    coupler,
    *,
    caption: str = "",
    length_steps: int = 8,
    full_crossover_length: float | None = None,
    pulse_width: float = 0.16,
    wavelength_nm: float = 1550.0,
) -> AnimationTimeline:
    """Visualize codirectional power transfer in a :class:`DirectionalCoupler`.

    Reveals the coupler, traces a wave packet along both input arms, then
    sweeps coupler length from 0 to a full-crossover length ``Lc``, emitting
    ``cavity_power`` captions with the (P_through, P_cross) envelope.

    Parameters
    ----------
    scene : Scene | AnimationTimeline
        Scene (or existing timeline) to append steps to.
    coupler : DirectionalCoupler
        Two-port codirectional coupler being illustrated.
    length_steps : int
        Number of samples across ``[0, Lc]``.
    full_crossover_length : float, optional
        Crossover length ``Lc`` in µm; defaults to twice ``coupler.coupling_length``.
    pulse_width : float
        Wave-packet width fraction passed to ``wave_travel``.
    wavelength_nm : float
        Wavelength used for caption + color hinting.
    """

    tl = _timeline(scene)
    if caption:
        tl.pause(0.5, caption=caption)

    label = getattr(coupler, "label", "") or "Directional coupler"
    tl.show(coupler, caption=label)

    arms = _routes_for_component(tl.scene, coupler)
    for arm in arms[:2]:
        tl.wave_travel(
            arm,
            caption=f"{getattr(arm, 'label', 'Arm') or 'Arm'} — guided mode approaches the coupler",
            steps=12,
            pulse_width=pulse_width,
            wavelength_nm=wavelength_nm,
            opacity_envelope="gaussian",
        )

    Lc = float(
        full_crossover_length
        if full_crossover_length is not None
        else max(float(getattr(coupler, "coupling_length", 7.0)) * 2.0, 1.0)
    )
    steps = max(int(length_steps), 1)
    for index in range(steps):
        if steps == 1:
            L = Lc
        else:
            L = Lc * index / (steps - 1)
        through, cross = _dc_coupling_envelope(L, Lc)
        tl.cavity_power(
            coupler,
            caption=(
                f"L = {L:.2f} µm — P_through ≈ {through:.2f}, P_cross ≈ {cross:.2f} "
                f"(Lc = {Lc:.2f} µm, λ = {wavelength_nm:.0f} nm)"
            ),
            steps=5,
        )

    return tl


def _mmi_split_ratios(mmi, imbalance_db: float, output_count: int) -> list[float]:
    """Return normalized power fractions for every MMI output."""

    if output_count < 1:
        raise ValueError("output_count must be positive")
    if not math.isfinite(imbalance_db):
        raise ValueError("imbalance_db must be finite")
    metadata = getattr(mmi, "physics_metadata", lambda: {})()
    explicit = metadata.get("split_ratios")
    if explicit is not None:
        if not isinstance(explicit, (list, tuple)) or len(explicit) != output_count:
            raise ValueError("split_ratios must contain one value per output")
        weights = [float(value) for value in explicit]
    elif output_count == 2 and metadata.get("split_ratio") is not None:
        top = float(metadata["split_ratio"])
        if not math.isfinite(top) or not 0.0 <= top <= 1.0:
            raise ValueError("split_ratio must lie in [0, 1]")
        weights = [top, 1.0 - top]
    else:
        weights = [1.0] * output_count
    if any(not math.isfinite(value) or value < 0.0 for value in weights):
        raise ValueError("split ratios must be finite and non-negative")
    if output_count > 1 and imbalance_db != 0.0:
        weights[1] *= 10.0 ** (-imbalance_db / 10.0)
    total = sum(weights)
    if not math.isfinite(total) or total <= 0.0:
        raise ValueError("split ratios must have a positive total")
    return [value / total for value in weights]


def animate_mmi_split_recombine(
    scene,
    mmi,
    *,
    caption: str = "",
    imbalance_db: float = 0.0,
    pulse_width: float = 0.18,
    wavelength_nm: float = 1550.0,
    steps: int = 14,
) -> AnimationTimeline:
    """Visualize an MMI splitting (and optionally recombining) a pulse.

    Animates the input wave_travel, a cavity_power "diffraction inside the
    body" highlight on the MMI, and per-output traces. Captions report the
    split ratio derived from the MMI's metadata, optionally biased by
    ``imbalance_db`` for asymmetric output captions.

    Parameters
    ----------
    scene : Scene | AnimationTimeline
        Scene (or existing timeline) to append steps to.
    mmi : MMI1x2 | MMI1x3 | MMI1x4 | MMI2x2 | ...
        Multi-mode interferometer component.
    imbalance_db : float
        Optional imbalance on output 2 (positive means output 2 loses power).
    pulse_width : float
        Wave-packet width fraction for ``wave_travel``.
    wavelength_nm : float
        Wavelength used in the pulse color and captions.
    steps : int
        Frames per wave_travel pass.
    """

    tl = _timeline(scene)
    if caption:
        tl.pause(0.5, caption=caption)

    label = getattr(mmi, "label", "") or getattr(mmi, "component_type", "MMI")
    tl.show(mmi, caption=label)

    routes = _routes_for_component(tl.scene, mmi)
    input_routes = [r for r in routes if _route_endpoint_is(r, mmi) == "end"]
    output_routes = [r for r in routes if _route_endpoint_is(r, mmi) == "start"]
    if not input_routes and routes:
        input_routes = [routes[0]]
        output_routes = routes[1:]

    for route in input_routes:
        tl.wave_travel(
            route,
            caption=f"Input mode enters {label}",
            steps=steps,
            pulse_width=pulse_width,
            wavelength_nm=wavelength_nm,
            opacity_envelope="gaussian",
        )

    tl.cavity_power(
        mmi,
        caption=f"Self-imaging inside {label} — multimode interference",
        steps=6,
    )

    metadata = getattr(mmi, "physics_metadata", lambda: {})()
    component_type = getattr(mmi, "component_type", mmi.__class__.__name__)
    default_count = {"MMI1x3": 3, "MMI1x4": 4}.get(component_type, 2)
    output_count = max(int(metadata.get("output_port_count") or default_count), len(output_routes))
    fractions = _mmi_split_ratios(mmi, imbalance_db, output_count)
    if abs(imbalance_db) >= 1e-6:
        regime = f"output 2 imbalance ({imbalance_db:.1f} dB)"
    elif max(fractions) - min(fractions) < 1e-6:
        regime = "equal split"
    else:
        regime = "asymmetric split"
    for index, route in enumerate(output_routes):
        fraction = fractions[index]
        tl.wave_travel(
            route,
            caption=(
                f"Output {index + 1}: P ≈ {fraction:.2f} of input — {regime}"
            ),
            steps=steps,
            pulse_width=pulse_width,
            wavelength_nm=wavelength_nm,
            opacity_envelope="gaussian",
            trail=True,
        )

    if not output_routes:
        tl.pause(
            0.8,
            caption=(
                f"{label}: "
                + ", ".join(
                    f"P{index + 1} ≈ {fraction:.2f}"
                    for index, fraction in enumerate(fractions)
                )
                + f" — {regime}"
            ),
        )

    return tl


def _photodetector_path(scene, pd) -> tuple[list[Route], list[Route]]:
    """Return ``(optical_routes, electrical_routes)`` touching ``pd``."""

    optical: list[Route] = []
    electrical: list[Route] = []
    for route in _routes_for_component(scene, pd):
        kind = getattr(route, "kind", "")
        component_type = getattr(route, "component_type", route.__class__.__name__)
        if kind == "electrical" or component_type == "ElectricalRoute":
            electrical.append(route)
        else:
            optical.append(route)
    return optical, electrical


def animate_photodetector_absorption(
    scene,
    photodetector=None,
    *,
    caption: str = "",
    readout_chain: dict | None = None,
    absorption_efficiency: float = 0.92,
    responsivity_a_per_w: float = 0.95,
    pulse_width: float = 0.18,
    wavelength_nm: float = 1550.0,
    steps: int = 14,
) -> AnimationTimeline:
    """Visualize a pulse landing on a photodetector and the electrical readout.

    Accepts either an explicit ``photodetector`` plus its hosting ``scene``, or
    a ``readout_chain`` dict produced by
    :func:`~optodraw.recipes.build_detector_readout_chain` (in which case
    ``scene`` may also be omitted and is taken from the chain).

    The optical-side route is animated with ``wave_travel(..., fade=True,
    opacity_envelope="gaussian")`` to suggest absorption, the PD is highlighted
    with ``cavity_power``, and the electrical readout routes are traced.

    Parameters
    ----------
    scene : Scene | AnimationTimeline, optional
        Scene to append steps to. Required unless ``readout_chain`` is given.
    photodetector : OnChipPhotodetector | Photodiode, optional
        Photodetector being illustrated. Inferred from ``readout_chain`` when
        provided.
    readout_chain : dict, optional
        Result of :func:`build_detector_readout_chain`. Supplies the scene,
        photodetector and readout routes.
    absorption_efficiency : float
        Optical absorption efficiency stub (0–1) shown in captions.
    responsivity_a_per_w : float
        Photodetector responsivity (A/W) used in the readout caption.
    pulse_width : float
        Wave-packet width fraction passed to ``wave_travel``.
    wavelength_nm : float
        Wavelength used for the pulse color and captions.
    steps : int
        Frames per wave_travel pass.
    """

    if readout_chain is not None:
        if scene is None:
            scene = readout_chain.get("scene")
        if photodetector is None:
            photodetector = readout_chain.get("photodetector")
        explicit_readout = list(readout_chain.get("routes", []))
    else:
        explicit_readout = []

    if scene is None:
        raise ValueError("scene is required when readout_chain is not provided")
    if photodetector is None:
        raise ValueError("photodetector is required when readout_chain is not provided")
    if not (0.0 <= absorption_efficiency <= 1.0):
        raise ValueError("absorption_efficiency must lie in [0, 1]")

    tl = _timeline(scene)
    if caption:
        tl.pause(0.5, caption=caption)

    label = getattr(photodetector, "label", "") or "Photodetector"
    tl.show(photodetector, caption=label)

    optical_routes, electrical_routes = _photodetector_path(tl.scene, photodetector)

    for route in optical_routes:
        tl.wave_travel(
            route,
            caption=f"Optical pulse approaches {label}",
            steps=steps,
            pulse_width=pulse_width,
            wavelength_nm=wavelength_nm,
            opacity_envelope="gaussian",
            trail=True,
        )
        tl.absorb(
            route,
            caption=(
                f"{label} absorbs the pulse — η_abs ≈ {absorption_efficiency:.2f}"
            ),
            steps=steps,
        )

    tl.cavity_power(
        photodetector,
        caption=(
            f"Photogeneration: I_photo = R · P_in (R ≈ {responsivity_a_per_w:.2f} A/W)"
        ),
        steps=6,
    )

    readout = explicit_readout or electrical_routes
    for index, route in enumerate(readout):
        signal_label = "I_photo" if index == 0 else "Readout signal"
        tl.trace(
            route,
            caption=f"{signal_label} flows through electrical chain",
            steps=10,
        )

    return tl


def _pn_phase_shift_per_volt(modulator) -> float:
    metadata = getattr(modulator, "physics_metadata", lambda: {})()
    if metadata.get("phase_shift_per_volt") is not None:
        return float(metadata["phase_shift_per_volt"])
    Vpi = metadata.get("Vpi") or metadata.get("Vpi_stub_v") or 4.0
    return math.pi / max(float(Vpi), 1e-6)


def animate_pn_modulation_phase_shift(
    scene,
    modulator,
    *,
    voltage_steps: int = 8,
    voltage_max: float = 4.0,
    caption: str = "",
    wavelength_nm: float = 1550.0,
) -> AnimationTimeline:
    """Visualize the optical phase shift induced by a PN-junction modulator.

    Sweeps reverse bias from ``0`` to ``voltage_max``, computes the induced
    phase shift from the modulator's metadata stub (or ``π/Vπ`` fallback) and
    emits ``cavity_power`` steps whose captions report ``Δφ`` and the resulting
    transmission ``T = cos²(Δφ/2)``.

    Works for any modulator that exposes a ``physics_metadata`` dict (e.g.
    :class:`~optodraw.components.onchip.PNMicroringModulator` or :class:`MZM`).

    Parameters
    ----------
    scene : Scene | AnimationTimeline
        Scene (or existing timeline) to append steps to.
    modulator : Component
        PN modulator (ring or MZM) being illustrated.
    voltage_steps : int
        Number of bias-voltage samples across ``[0, voltage_max]``.
    voltage_max : float
        Maximum reverse bias (V) for the sweep.
    caption : str
        Optional opening caption.
    wavelength_nm : float
        Optical wavelength (nm) reported in captions.
    """

    if voltage_steps < 1:
        raise ValueError("voltage_steps must be >= 1")
    if voltage_max <= 0:
        raise ValueError("voltage_max must be > 0")

    tl = _timeline(scene)
    if caption:
        tl.pause(0.5, caption=caption)

    label = getattr(modulator, "label", "") or getattr(
        modulator, "component_type", "PN modulator"
    )
    tl.show(modulator, caption=label)

    routes = _routes_for_component(tl.scene, modulator)
    if routes:
        tl.wave_travel(
            routes[0],
            caption=f"Guided mode enters the {label} phase section",
            steps=12,
            pulse_width=0.18,
            wavelength_nm=wavelength_nm,
            opacity_envelope="gaussian",
        )

    phase_per_v = _pn_phase_shift_per_volt(modulator)
    steps = max(int(voltage_steps), 1)
    for index in range(steps):
        if steps == 1:
            voltage = voltage_max
        else:
            voltage = voltage_max * index / (steps - 1)
        delta_phi = voltage * phase_per_v
        transmission = math.cos(delta_phi / 2.0) ** 2
        tl.cavity_power(
            modulator,
            caption=(
                f"V_rev = {voltage:.2f} V → Δφ ≈ {delta_phi:.2f} rad "
                f"→ T ≈ {transmission:.2f} (λ = {wavelength_nm:.0f} nm)"
            ),
            steps=5,
        )

    tl.pause(
        0.8,
        caption=(
            f"{label}: phase efficiency ≈ {phase_per_v:.2f} rad/V (depletion-stub)"
        ),
    )

    return tl


__all__ = [
    "animate_directional_coupler_power_transfer",
    "animate_dispersion",
    "animate_fiber_alignment",
    "animate_focus",
    "animate_grating_coupler_in_out",
    "animate_interference",
    "animate_layer_stack",
    "animate_mmi_split_recombine",
    "animate_modulation",
    "animate_mzm_mechanism",
    "animate_photodetector_absorption",
    "animate_pn_modulation_phase_shift",
    "animate_resonance_scan",
    "animate_ring_coupling",
]
