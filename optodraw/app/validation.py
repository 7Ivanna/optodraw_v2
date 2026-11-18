"""Design-rule / consistency **checks** for the GUI 'Check' panel.

Runs the platform-appropriate ``validate_*`` helpers over the current scene and returns
a flat, structured issue list. Thin wrapper — all logic lives in ``optodraw.core.*``.
Validations are gated by scene content so an on-chip layout doesn't get flooded with
"visual-only for ray tracing" warnings (and vice-versa).
"""

from __future__ import annotations

from typing import Any

from optodraw.core.component import LINK_TYPES

_SKIP = LINK_TYPES | {"Group", "Grid", "PM"}
# Mounting hardware / carriers are never *in* the beam, so the free-space
# ray / polarization chain validators must not report them.
_CARRIERS = {"OpticalTable", "Breadboard", "Baseplate", "ChipSubstrate", "OpticalPost"}
# Free-space chain validators only consider components that can sit in the beam
# path; on-chip parts, electronics, imported models etc. are out of scope.
_BEAM_PATH_CATEGORIES = {"optics", "devices"}
_GRATING_COUPLERS = {"VerticalGratingCoupler", "FocusedApodizedGratingCoupler"}
_FREE_SPACE_HINTS = {"Laser", "Lamp", "Lens", "Mirror", "BeamSplitter", "Polarizer", "Analyzer", "QuarterWavePlate", "HalfWavePlate", "Objective", "Filter", "Prism", "Camera", "Spectrometer"}
# Beam dumps are meant to sit dark; the rest are there to see something.
_DETECTORS = {"Camera", "Photodiode", "AmplifiedPhotodetector", "PMT", "Spectrometer", "PowerMeter", "QuadrantPhotodiode", "BalancedDetector"}


def _dark_detectors(scene: Any, comps: list[Any]) -> list[dict[str, Any]]:
    """Detectors that no beam reaches.

    Physical tracing terminates a ray at the absorber it lands on, so a detector
    whose entrance is not the END of any beam is receiving nothing — the single
    most common reason a bench layout does not work. Scenes with no beams at all
    say nothing about illumination, so the check stays quiet there."""

    import math

    ends: list[tuple[float, float]] = []
    fed: set[int] = set()                     # parts at an end of a fibre: the fibre brings them the light
    for node in scene.walk():
        if getattr(node, "component_type", "") == "FiberRoute":
            fed |= {id(getattr(node, "start_component", None)), id(getattr(node, "end_component", None))}
        if getattr(node, "component_type", "") == "FocusingBeam":
            end = node.endpoints()[1]
            ends.append((float(end.x), float(end.y)))
            continue
        if getattr(node, "component_type", "") != "Beam":
            continue
        try:
            points = node.resolve_points()
        except Exception:  # pragma: no cover - defensive
            continue
        if len(points) >= 2:
            ends.append((float(points[-1][0]), float(points[-1][1])))
    if not ends:
        return []

    issues = []
    for node in comps:
        if getattr(node, "component_type", "") not in _DETECTORS or id(node) in fed:
            continue
        transform = node.world_transform
        cx, cy = float(transform.position.x), float(transform.position.y)
        span = 6.0
        try:
            ports = node.ports()
            port_name = "in" if "in" in ports else next(iter(ports))
            port = node.world_port(port_name)
            cx, cy = float(port.center.x), float(port.center.y)
            span = float(getattr(port, "width", 0.0) or 0.0) or span
        except Exception:  # pragma: no cover - portless detector: use the body
            pass
        tolerance = span / 2.0 + 1.0
        if not any(math.dist(end, (cx, cy)) <= tolerance for end in ends):
            label = getattr(node, "label", "") or node.component_type
            issues.append({
                "kind": "illumination",
                "level": "warning",
                "message": f"{label} receives no light — no beam reaches its entrance. Check the alignment of the optics in front of it.",
                "component_id": getattr(node, "_id", ""),
            })
    return issues


def _dichroics_without_an_edge(comps: list[Any]) -> list[dict[str, Any]]:
    """Dichroics that carry no cutoff wavelength.

    ``dichroic=True`` changes the colour of the drawn coating and nothing else:
    physical tracing needs an edge wavelength to decide what passes and what
    reflects, and without one it falls back to an even 50/50 split. The drawing
    looks like a working dichroic; the light does not behave like one."""

    issues = []
    for node in comps:
        if getattr(node, "component_type", "") != "BeamSplitter":
            continue
        if not getattr(node, "dichroic", False) or getattr(node, "cutoff_wavelength", None):
            continue
        label = getattr(node, "label", "") or "Dichroic"
        issues.append({
            "kind": "dichroic",
            "level": "warning",
            "message": (
                f"{label} is marked dichroic but has no cutoff wavelength, so tracing splits "
                f"it 50/50 instead of by colour. Set the cutoff to the edge of the coating."
            ),
            "component_id": getattr(node, "_id", ""),
        })
    return issues


def _outside_the_frame(scene: Any, comps: list[Any]) -> list[dict[str, Any]]:
    """Components the export frame will cut off.

    The frame is what an SVG, a PNG or a TikZ figure gets cropped to. A part
    outside it is not "off to one side" in the export — it is missing, with
    nothing to say so. The canvas itself is unbounded, which is what makes this
    easy to do by accident."""

    from optodraw.core.transform import Vec3
    from optodraw.layout import estimate_component_bounds

    half_width = float(getattr(scene, "width", 0.0) or 0.0) / 2.0
    half_height = float(getattr(scene, "height", 0.0) or 0.0) / 2.0
    if half_width <= 0 or half_height <= 0:
        return []
    cx, cy = getattr(scene, "frame_center", (0.0, 0.0))

    issues = []
    for node in comps:
        if getattr(node, "component_type", "") in {"Grid"}:
            continue
        try:
            left, bottom, right, top = estimate_component_bounds(node)
        except Exception:  # pragma: no cover - nothing drawable to measure
            continue
        transform = node.world_transform
        corners = ((left, bottom), (left, top), (right, bottom), (right, top))
        world_corners = [transform.apply_to_point(Vec3(x, y, 0.0)) for x, y in corners]
        xs = [corner.x for corner in world_corners]
        ys = [corner.y for corner in world_corners]
        over_x = max(max(xs) - cx - half_width, cx - half_width - min(xs))
        over_y = max(max(ys) - cy - half_height, cy - half_height - min(ys))
        if over_x <= 0.5 and over_y <= 0.5:
            continue
        # Two parts can share a label — a block and the arrow annotating it —
        # and naming only the label made one warning look like two copies of
        # the same one.
        label = getattr(node, "label", "") or node.component_type
        if label != node.component_type:
            label = f"{label} ({node.component_type})"
        issues.append({
            "kind": "frame",
            "level": "warning",
            "message": (
                f"{label} sits outside the export frame, so it will be cut off the figure. "
                f"Move it inside, or grow the scene in Scene settings."
            ),
            "component_id": getattr(node, "_id", ""),
        })
    return issues


def _parts_without_an_exact_symbol(comps: list[Any]) -> list[dict[str, Any]]:
    """Parts that the 1D view draws as a labeled block or as a near variant: one line per part type."""

    from optodraw.symbols import lookup
    from optodraw.symbols.schematic import _NOT_IN_A_SCHEMATIC

    missing: dict[tuple[str, str], int] = {}
    for node in comps:
        if node.component_type in _NOT_IN_A_SCHEMATIC:
            continue
        try:
            symbol = lookup(node)
        except Exception:  # pragma: no cover - defensive
            continue
        if not symbol.exact:
            key = (node.component_type, symbol.source)
            missing[key] = missing.get(key, 0) + 1
    shown = {"block": "a labeled block", "nearest": "the nearest prebuilt variant"}
    return [
        {"kind": "symbol", "level": "info",
         "message": f"{ctype} ({count}): no exact 1D symbol; the 1D view shows {shown.get(source, source)}."}
        for (ctype, source), count in sorted(missing.items())
    ]


def _objectives_inside_a_cryostat(nodes: list[Any]) -> list[dict[str, Any]]:
    """An objective focuses through a cryostat's window from outside: its nose never reaches past the glass."""

    import math

    found: list[dict[str, Any]] = []
    for sample in nodes:
        if getattr(sample, "component_type", "") != "Sample" or not sample.in_cryostat:
            continue
        centre = sample.world_position
        for objective in nodes:
            if getattr(objective, "component_type", "") != "Objective":
                continue
            nose = objective.world_port("out").center
            if math.hypot(nose.x - centre.x, nose.y - centre.y) < sample.window_reach:
                found.append({"kind": "beam", "level": "warning", "component_id": getattr(objective, "_id", ""),
                              "message": f"{objective.label or 'The objective'} reaches inside the window of the "
                                         f"cryostat: give it a working_distance above {sample.window_reach:.3g}, so "
                                         "that it focuses through the glass from outside"})
    return found


def _beams_through_the_back(nodes: list[Any]) -> list[dict[str, Any]]:
    """Light leaves a port along its outward direction and enters the next port against it. A detector
    turned away from its beam, or a laser that faces the wrong way, draws light through the part's back."""

    import math

    from optodraw.core.beam import Beam, beam_point
    from optodraw.core.component import Component

    found: list[dict[str, Any]] = []
    for beam in nodes:
        if not isinstance(beam, Beam):
            continue
        stops = []
        for anchor in beam.anchors:
            if isinstance(anchor, (tuple, list)) and len(anchor) == 2 and isinstance(anchor[0], Component):
                part, name = anchor
                port = part.world_port(str(name))
                turn = math.radians(port.orientation_deg)
                drawn = beam_point(part, str(name))
                faced = str(name) != "pass" and not getattr(part, "out_of_beam", False)  # no face in the light's way
                stops.append((part, (drawn.x, drawn.y), (math.cos(turn), math.sin(turn)), faced))
            else:
                stops.append(None)
        for a, b in zip(stops, stops[1:]):
            if a is None or b is None or a[0] is b[0]:
                continue
            dx, dy = b[1][0] - a[1][0], b[1][1] - a[1][1]
            length = math.hypot(dx, dy)
            if length < 1e-9:
                continue
            ux, uy = dx / length, dy / length
            # a run meant to be straight (level, upright or at 45 degrees) that leans a little: ports off line
            angle = math.degrees(math.atan2(dy, dx))
            lean = abs((angle + 22.5) % 45.0 - 22.5)
            if 0.05 < lean < 3.0:
                names = [getattr(p, "label", "") or getattr(p, "component_type", "part") for p in (a[0], b[0])]
                found.append({"kind": "beam", "level": "warning", "component_id": getattr(b[0], "_id", ""),
                              "message": f"The beam from {names[0]} to {names[1]} leans {lean:.2f} degrees off a "
                                         "straight run: line up the two ports, not the part centres"})
            for stop, sign, words in ((a, -1.0, "leaves {} backwards: turn it so its output faces the beam"),
                                      (b, 1.0, "enters {} from behind: turn it so its input faces the beam "
                                               "(optodraw.layout.face)")):
                part, normal, faced = stop[0], stop[2], stop[3]
                if not faced:
                    continue
                along = ux * normal[0] + uy * normal[1]
                name = getattr(part, "label", "") or getattr(part, "component_type", "part")
                if sign * along > 0.2:
                    found.append({"kind": "beam", "level": "warning", "message": "The beam " + words.format(name),
                                  "component_id": getattr(part, "_id", "")})
                elif part is b[0] and abs(along) < 0.5 and not callable(getattr(part, "beam_point", None)):
                    # the beam meets the face edge-on: it lies along the part (a plate reflects off the face it
                    # enters, so a plate's one port normal says nothing here)
                    found.append({"kind": "beam", "level": "warning", "component_id": getattr(part, "_id", ""),
                                  "message": f"The beam runs along {name} instead of through it: turn it to face "
                                             "the beam (a lens or a filter on a level beam has angle=0)"})
    return found


def _flip_mirror_routes(nodes: list[Any]) -> list[dict[str, Any]]:
    """A flip mirror that is up blocks the straight route. One that is down is not there to fold a beam."""

    from optodraw.core.beam import Beam

    found: list[dict[str, Any]] = []
    for beam in nodes:
        if not isinstance(beam, Beam):
            continue
        for anchor in beam.anchors:
            if not (isinstance(anchor, (tuple, list)) and len(anchor) == 2):
                continue
            part, port = anchor
            if getattr(part, "component_type", "") != "FlipMirror":
                continue
            name = getattr(part, "label", "") or "The flip mirror"
            if port == "pass" and part.state == "up":
                words = f"The beam runs straight through {name}, but the mirror is up and blocks it: set state=\"down\""
            elif port != "pass" and part.state == "down":
                words = f"The beam folds at {name}, but the mirror is down, out of the beam: set state=\"up\""
            else:
                continue
            found.append({"kind": "beam", "level": "warning", "component_id": getattr(part, "_id", ""),
                          "message": words + ', or state="both" for a figure of the two routes'})
    return found


def run_checks(scene: Any) -> list[dict[str, Any]]:
    """Return a list of ``{kind, level, message, component_id?}`` issues for the scene."""

    nodes = list(scene.walk())
    comps = [n for n in nodes if getattr(n, "component_type", "") and n.component_type not in _SKIP]
    electrical_routes = [
        n for n in nodes
        if getattr(n, "component_type", "") in {"Route", "WaveguideRoute", "FiberRoute", "MetalRoute"}
        and getattr(n, "kind", "") == "electrical"
    ]
    types = {getattr(n, "component_type", "") for n in comps}
    platform = getattr(scene, "platform", "free_space")
    checks: list[dict[str, Any]] = []

    def add(kind: str, messages: list[str], level: str = "warning") -> None:
        for msg in messages or []:
            checks.append({"kind": kind, "level": level, "message": msg})

    def _beam_path_components() -> list[Any]:
        from optodraw.registry import component_registry

        registry = component_registry()
        kept = []
        for node in comps:
            ctype = getattr(node, "component_type", "")
            if ctype in _CARRIERS:
                continue
            spec = registry.get(ctype)
            if spec is not None and spec.category not in _BEAM_PATH_CATEGORIES:
                continue
            kept.append(node)
        return kept

    # On-chip content without an explicit substrate leaves the 3D die auto-fitted;
    # recommend placing one BEFORE designing so die size/position is deliberate.
    if platform == "on_chip" and comps and "ChipSubstrate" not in types:
        checks.append({
            "kind": "layout",
            "level": "info",
            "message": "On-chip layout has no Chip Substrate — the 3D die is auto-fitted around the components. Place a Chip Substrate (palette → on-chip) first to control die size, position, and orientation.",
        })

    is_free_space = platform == "free_space" or bool(types & _FREE_SPACE_HINTS)
    if is_free_space:
        from optodraw.core.physics import validate_ray_chain
        from optodraw.core.polarization import validate_polarization_chain

        path_comps = _beam_path_components()
        # "declares no X support" is advisory (drawing-only components are
        # by-design in a viz tool), so these report at info level.
        try:
            add("ray", validate_ray_chain(path_comps), level="info")
        except Exception:  # pragma: no cover - defensive
            pass
        if types & {"Polarizer", "Analyzer", "QuarterWavePlate", "HalfWavePlate", "WavePlate", "PBS"}:
            try:
                add("polarization", validate_polarization_chain(path_comps), level="info")
            except Exception:  # pragma: no cover - defensive
                pass

    checks.extend(_outside_the_frame(scene, comps))
    checks.extend(_parts_without_an_exact_symbol(comps))
    checks.extend(_dichroics_without_an_edge(comps))
    if is_free_space:
        checks.extend(_dark_detectors(scene, comps))
    checks.extend(_beams_through_the_back(nodes))
    checks.extend(_objectives_inside_a_cryostat(nodes))
    checks.extend(_flip_mirror_routes(nodes))

    if electrical_routes:
        from optodraw.core.electrical import validate_electrical_chain

        try:
            add("electrical", validate_electrical_chain(electrical_routes), level="info")
        except Exception:  # pragma: no cover - defensive
            pass

    if types & _GRATING_COUPLERS:
        from optodraw.core.guided import validate_coupler_transition

        for node in comps:
            if getattr(node, "component_type", "") in _GRATING_COUPLERS:
                try:
                    for msg in validate_coupler_transition(node) or []:
                        checks.append({"kind": "coupler", "level": "warning", "message": msg, "component_id": getattr(node, "_id", "")})
                except Exception:  # pragma: no cover - defensive
                    pass

    return checks
