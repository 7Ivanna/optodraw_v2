"""Physics-driven animation payloads for the editor's 2D animation and Export GIF.

This module builds the 2D animation payloads only. :func:`anim_payload_map` walks a scene once and returns a
per-node dict of *numbers only* (speeds, powers, waists, polarization states, signal kinds). The 3D page and the
tour video do not use it: they draw the light from ``optodraw.animation_engine`` through ``optodraw.animation3d``.

Physical anchoring (accurate-but-not-FDTD):

- pulse speed per segment = c / n_group  (guided traces / medium defaults)
- power along a beam       = Jones-trace intensity where polarization elements
  are present, else per-component transmission factors
- beam envelopes           = Gaussian w(z) hyperbola through the anchor widths
- ring circulation         = buildup / through / drop powers from the Q trace
- electrical signals       = kind (dc / rf / digital / clock) from the signal spec

Every builder is fault-tolerant: a failed trace degrades to a plain pulse,
never a broken render.
"""

from __future__ import annotations

import math
from typing import Any

# Group indices used when a guided trace can't provide one (display defaults,
# same convention as core.guided's silicon strip stub).
_NG_SILICON = 4.2
_NG_FIBER = 1.468
_NG_AIR = 1.0

# Fraction of power carried past an intermediate beam anchor, by component
# type. Only consulted when a Jones trace can't decide (no polarization
# elements). Detectors/dumps absorb the pulse (0.0 ends the animation there).
_TRANSMISSION: dict[str, float] = {
    "BeamSplitter": 0.5,
    "NonPolarizingBeamSplitter": 0.5,
    "PBS": 0.5,
    "TapCoupler": 0.9,
    "Filter": 0.5,
    "DichroicMirror": 0.9,
    "Iris": 0.75,
    "Pinhole": 0.6,
    "ApertureStop": 0.75,
    "Sample": 0.7,
    "OpticalChopper": 0.5,
    "BeamDump": 0.0,
    "Photodiode": 0.0,
    "AmplifiedPhotodetector": 0.0,
    "PowerMeter": 0.0,
    "PMT": 0.0,
    "Camera": 0.0,
    "CMOSCamera": 0.0,
    "EMCCD": 0.0,
    "SPADArray": 0.0,
    "CameraSensor": 0.0,
    "Spectrometer": 0.0,
}

_POLARIZATION_TYPES = frozenset(
    {
        "Polarizer",
        "Analyzer",
        "WavePlate",
        "HalfWavePlate",
        "QuarterWavePlate",
        "PBS",
        "BrewsterWindow",
        "PolarizationRotator",
    }
)


def _ctype(node: Any) -> str:
    return getattr(node, "component_type", node.__class__.__name__)


def _anchor_component(anchor: Any) -> Any | None:
    """Resolve a beam anchor to its component.

    Beams accept bare components, ``(component, port_name)`` tuples (the editor's
    port-wired links), or raw points. Chaining and power stepping must see the
    component in all three cases — matching only bare components made every
    editor-built beam launch at t=0 (mirrors appeared to hold light)."""

    if hasattr(anchor, "component_type"):
        return anchor
    if isinstance(anchor, (tuple, list)) and anchor and hasattr(anchor[0], "component_type"):
        return anchor[0]
    return None


def _transmission(node: Any) -> float:
    """Power fraction continuing past a free-space component.

    Reads the INSTANCE's own optics first (transmission / reflectivity /
    efficiency attributes or physics metadata, plus insertion loss), then the
    per-type table."""

    meta = _node_meta(node)
    base = None
    for key in ("transmission", "transmittance", "reflectivity", "efficiency", "coupler_efficiency"):
        value = _node_num(node, meta, key)
        if value is not None and 0.0 <= value <= 1.0:
            base = value
            break
    if base is None:
        base = _TRANSMISSION.get(_ctype(node), 0.97)
    loss_db = _node_num(node, meta, "insertion_loss_db", "loss_db") or 0.0
    return base * 10.0 ** (-max(loss_db, 0.0) / 10.0)


def _segment_lengths(points: list[tuple[float, ...]]) -> list[float]:
    out = []
    for a, b in zip(points, points[1:]):
        dimensions = min(len(a), len(b), 3)
        out.append(math.dist(a[:dimensions], b[:dimensions]))
    return out


def _stokes_to_pol(stokes: tuple[float, float, float, float]) -> dict[str, float]:
    """Reduce a Stokes vector to the ellipse parameters the shaders need."""

    s0 = stokes[0] or 1.0
    psi = 0.5 * math.atan2(stokes[2], stokes[1])  # orientation of the major axis
    s3 = max(-1.0, min(1.0, stokes[3] / s0))
    chi = 0.5 * math.asin(s3)  # ellipticity angle: 0 linear, ±π/4 circular
    return {
        "orientation_deg": math.degrees(psi),
        "ellipticity": abs(math.tan(chi)),  # minor/major axis ratio, 0..1
        "handedness": 1.0 if stokes[3] >= 0 else -1.0,
        "intensity": s0,
    }


def _beam_anim(beam: Any, wavelength_nm: float, heights: Any = None) -> dict[str, Any] | None:
    """Pulse + polarization payload for a free-space Beam (``heights``: the 3D beam heights it runs at)."""

    try:
        points = beam.resolve_points(heights)
    except Exception:
        return None
    if len(points) < 2:
        return None
    lengths = _segment_lengths([tuple(p) for p in points])
    anchors = [c for c in (_anchor_component(a) for a in getattr(beam, "anchors", [])) if c is not None]

    # Per-segment power: prefer the Jones trace when the chain actually
    # manipulates polarization; otherwise multiply transmission factors.
    n_segments = len(lengths)
    powers = [1.0] * n_segments
    pol_states: list[dict[str, float]] = []
    use_jones = any(_ctype(a) in _POLARIZATION_TYPES for a in anchors)
    jones_ok = False
    if use_jones and len(anchors) >= 2:
        try:
            from optodraw.core.polarization import trace_jones_through

            wl = float(getattr(beam, "wavelength", wavelength_nm) or wavelength_nm)
            base = trace_jones_through(anchors[:1], wavelength_nm=wl)
            i0 = base.jones.intensity() or 1.0
            for k in range(1, len(anchors)):
                step = trace_jones_through(anchors[: k + 1], wavelength_nm=wl)
                pol = _stokes_to_pol(step.stokes)
                pol["intensity"] = step.jones.intensity() / i0
                pol_states.append(pol)
            jones_ok = True
        except Exception:
            pol_states = []
    if jones_ok and len(pol_states) == n_segments:
        powers = [max(0.0, min(1.0, p["intensity"])) for p in pol_states]
    else:
        # Transmission product across the intermediate anchors.
        running = 1.0
        for i in range(n_segments):
            if i > 0 and i < len(anchors):
                running *= _transmission(anchors[i])
            powers[i] = max(0.0, running)
    if not pol_states:
        # No polarization elements: assume horizontal linear (bench convention).
        pol_states = [
            {"orientation_deg": 0.0, "ellipticity": 0.0, "handedness": 1.0, "intensity": p}
            for p in powers
        ]

    return {
        "pulse": {
            "segments": [
                {"len": round(ln, 4), "n": _NG_AIR, "power": round(pw, 4)}
                for ln, pw in zip(lengths, powers)
            ],
            "wavelength_nm": float(getattr(beam, "wavelength", wavelength_nm) or wavelength_nm),
        },
        "pol": pol_states[: n_segments] or None,
        # kept for the chaining pass, stripped before emit
        "_anchors": anchors,
        "_lengths": lengths,
        "_powers": powers,
    }


def _route_anim(route: Any, wavelength_nm: float) -> dict[str, Any] | None:
    """Guided-flow (optical/fiber) or signal (electrical) payload for a Route."""

    kind = getattr(route, "kind", "optical")
    try:
        points = route.resolve_points()
    except Exception:
        return None
    if len(points) < 2:
        return None
    total = sum(_segment_lengths([tuple(p) for p in points]))

    if kind == "electrical":
        if str((getattr(route, "anim_params", None) or {}).get("drive", "on")) == "off":
            return None  # drive off: the conductor sits dark
        signal = "rf"
        try:
            from optodraw.core.electrical import route_signal_spec

            signal = route_signal_spec(route).kind or "rf"
        except Exception:
            pass
        return {"signal": {"kind": signal, "len": round(total, 4)}}

    ng = _NG_FIBER if _ctype(route) == "FiberRoute" else _NG_SILICON
    try:
        from optodraw.core.guided import trace_guided_path

        result = trace_guided_path([route], wavelength_nm=wavelength_nm)
        value = getattr(result, "group_index", None)
        if value:
            ng = float(value)
    except Exception:
        pass
    return {"flow": {"len": round(total, 4), "n": ng, "power": 1.0}}


def _metal_anim(node: Any) -> dict[str, Any] | None:
    """Signal payload for drawn metal traces (MetalRoute, not Route objects).

    These components carry local points, so the payload includes the
    world-transformed polyline — the JS engine has no transform math."""

    local = list(getattr(node, "points", None) or [])
    pts: list[tuple[float, float]] = []
    for p in local:
        if p is None:
            return None
        if hasattr(p, "x"):
            pts.append((float(p.x), float(p.y)))
        else:
            pts.append((float(p[0]), float(p[1])))
    if len(pts) < 2:
        return None
    try:
        wt = node.world_transform
        theta = math.radians(float(wt.rotation_deg.z))
        cx, cy = float(wt.position.x), float(wt.position.y)
    except Exception:
        theta, cx, cy = 0.0, 0.0, 0.0
    cos_t, sin_t = math.cos(theta), math.sin(theta)
    world = [(cx + x * cos_t - y * sin_t, cy + x * sin_t + y * cos_t) for x, y in pts]
    total = sum(math.dist(a, b) for a, b in zip(world, world[1:]))
    if total <= 0:
        return None
    if str((getattr(node, "anim_params", None) or {}).get("drive", "on")) == "off":
        return None  # drive switched off: static metal
    kind = str(getattr(node, "signal", None) or "rf")
    if kind not in ("dc", "rf", "digital", "clock"):
        kind = "rf"
    return {"signal": {"kind": kind, "len": round(total, 4), "points": [[round(x, 4), round(y, 4)] for x, y in world]}}


def _envelope_anim(fbeam: Any) -> dict[str, Any] | None:
    """Gaussian w(z) profile through a FocusingBeam's two anchor widths.

    The hyperbola is anchored to the drawn widths (w0 at the narrow end); the
    Rayleigh range is solved so the wide end matches exactly — the physically
    shaped envelope through both constraints.
    """

    def _xy(anchor: Any) -> tuple[float, float]:
        point = anchor.beam_anchor_point() if hasattr(anchor, "beam_anchor_point") else anchor
        if hasattr(point, "x"):
            return float(point.x), float(point.y)
        return float(point[0]), float(point[1])

    try:
        x1, y1 = _xy(fbeam.anchor1)
        x2, y2 = _xy(fbeam.anchor2)
    except Exception:
        return None
    length = math.dist((x1, y1), (x2, y2))
    if length <= 0:
        return None
    w1 = max(float(getattr(fbeam, "width1", 5.0)), 0.05)
    w2 = max(float(getattr(fbeam, "width2", 0.0)), 0.05)
    w0 = min(w1, w2)
    wmax = max(w1, w2)
    focus_at_end = w2 <= w1  # narrow end = focus
    if wmax / w0 > 1.001:
        z_rayleigh = length / math.sqrt((wmax / w0) ** 2 - 1.0)
    else:
        z_rayleigh = length  # nearly collimated
    profile = []
    steps = 24
    for i in range(steps + 1):
        s = i / steps  # 0 at anchor1
        z_from_focus = (1.0 - s) * length if focus_at_end else s * length
        w = w0 * math.sqrt(1.0 + (z_from_focus / z_rayleigh) ** 2)
        profile.append([round(s, 4), round(w, 4)])
    return {
        "points": [[x1, y1], [x2, y2]],
        "envelope": {"profile": profile, "wavelength_nm": float(getattr(fbeam, "wavelength", 633.0))},
        "pulse": {
            "segments": [{"len": round(length, 4), "n": _NG_AIR, "power": 1.0}],
            "wavelength_nm": float(getattr(fbeam, "wavelength", 633.0)),
        },
        "color": getattr(fbeam, "color", "#ff4444"),
        "opacity": getattr(fbeam, "opacity", 0.5),
        "_anchors": [_anchor_component(fbeam.anchor1)] if _anchor_component(fbeam.anchor1) is not None else [],
        "_lengths": [length],
        "_powers": [1.0],
    }


def _anim_param(node: Any, key: str, default: str = "auto") -> str:
    params = getattr(node, "anim_params", None) or {}
    return str(params.get(key, default))


def _world_xy(node: Any, pts: list[list[float]]) -> list[list[float]]:
    """Apply the node's world transform (rotation about z + translation) to 2D points."""

    try:
        wt = node.world_transform
        theta = math.radians(float(wt.rotation_deg.z))
        cx, cy = float(wt.position.x), float(wt.position.y)
    except Exception:
        theta, cx, cy = 0.0, 0.0, 0.0
    cos_t, sin_t = math.cos(theta), math.sin(theta)
    return [[round(cx + x * cos_t - y * sin_t, 4), round(cy + x * sin_t + y * cos_t, 4)] for x, y in pts]


def _junction_anim(node: Any) -> dict[str, Any] | None:
    """Carrier animation for PN (depletion) / PIN (injection) optical control.

    Reverse-biasing a PN junction sweeps carriers OUT of the waveguide (plasma
    dispersion phase shift); forward-biasing a PIN floods carriers IN (absorption).
    The payload carries the junction line(s) along the waveguide; the JS engine
    oscillates ± carriers toward/away from it with the drive cycle."""

    mode = _anim_param(node, "junction")
    if mode == "off":
        return None
    ctype = _ctype(node)
    paths: list[dict[str, Any]] = []
    kind = "pn"
    push_pull = False
    if ctype == "MZM":
        draw = node._draw_variant() if hasattr(node, "_draw_variant") else node
        half = float(draw.electrode_length) / 2.0
        arm_y = float(draw.arm_gap) / 2.0  # carriers straddle the DRAWN arms
        paths.append({"pts": _world_xy(node, [[-half, arm_y], [half, arm_y]])})
        paths.append({"pts": _world_xy(node, [[-half, -arm_y], [half, -arm_y]])})
        push_pull = True  # arms drive in antiphase
    elif ctype == "PNMicroringModulator":
        radius = float(node.ring_radius)
        center_y = float(getattr(node, "ring_center_y", 0.0))
        start, end = node._pn_sectors()[0] if hasattr(node, "_pn_sectors") else (-160.0, -20.0)
        pts = []
        for i in range(21):  # along the drawn p and n bands
            ang = math.radians(start + (end - start) * i / 20)
            pts.append([radius * math.cos(ang), center_y + radius * math.sin(ang)])
        paths.append({"pts": _world_xy(node, pts)})
    elif ctype == "ElectroAbsorptionModulator":
        half = float(node.active_length) / 2.0
        paths.append({"pts": _world_xy(node, [[-half, 0.0], [half, 0.0]])})
        kind = "pin"
    else:
        return None
    if mode in ("pn", "pin"):
        kind = mode
    if not paths:
        return None
    return {"junction": {"kind": kind, "paths": paths, "period_s": 1.8, "push_pull": push_pull}}


def _heater_is_on(node: Any) -> bool:
    return str((getattr(node, "anim_params", None) or {}).get("heater", "on")) != "off"


def _heat_anim(node: Any) -> dict[str, Any] | None:
    """Shape-following heat payload: the heater METAL's spine polyline(s) + width.

    Heat must hug the actual heater — a straight strip on a pad or an MZI arm, an
    ARC around a microring, a bar over a racetrack's coupling straight — because
    that's where the resistive metal is. Local paths come from each component's
    own heater geometry properties; the payload carries world coordinates."""

    ctype = _ctype(node)
    if not _heater_is_on(node):
        return None  # heater switched off: no halo, no thermo-optic response
    if ctype == "MZM" and str(getattr(node, "mechanism", "")) != "thermo_optic":
        return None  # electro-optic MZM draws NO heater — nothing to warm
    original = node
    if hasattr(node, "_draw_variant"):
        try:
            node = node._draw_variant()  # heater must hug the DRAWN metal
        except Exception:
            node = original
    paths: list[dict[str, Any]] = []

    def strip(x1: float, y1: float, x2: float, y2: float, width: float) -> None:
        paths.append({"pts": [[x1, y1], [x2, y2]], "w": float(width)})

    try:
        if ctype == "HeaterPad":
            half = float(node.heater_length) / 2.0
            strip(-half, 0.0, half, 0.0, node.heater_width)
        elif ctype == "PhaseShifter":
            half = float(getattr(node, "shifter_length", node.length)) / 2.0
            strip(-half, 0.0, half, 0.0, max(float(node.width) * 1.8, 0.9))
        elif ctype in ("MZI", "MZM") and hasattr(node, "heater_length"):
            # thermo-optic phase shifter on the upper arm
            half = float(node.heater_length) / 2.0
            arm_y = float(node.arm_gap) / 2.0
            strip(-half, arm_y, half, arm_y, node.heater_strip_width)
        elif ctype == "RingAssistedMZI":
            if not node.with_heaters:
                return None
            # the arm phase shifter on the top arm, and the C-shaped strip inside every ring
            half = float(node.heater_length) / 2.0
            strip(node.arm_heater_x - half, node.arm_gap / 2.0, node.arm_heater_x + half, node.arm_gap / 2.0, node.heater_strip_width)
            opening = node._ring_heater_gap_deg
            for ring in node.ring_layout():
                arc = [[ring["x"] + node.ring_heater_radius * math.cos(math.radians(a)),
                        ring["y"] + ring["sign"] * node.ring_heater_radius * math.sin(math.radians(a))]
                       for a in (90.0 + opening + (360.0 - 2.0 * opening) * i / 48 for i in range(49))]
                paths.append({"pts": arc, "w": float(node.ring_heater_width)})
        elif getattr(node, "with_heater", False) and hasattr(node, "heater_centerline"):
            # rings and racetracks hand us their heater's own spine, so heat
            # follows the drawn metal instead of a shape guessed from here
            spine = [[float(x), float(y)] for x, y in node.heater_centerline()]
            if spine:
                paths.append({"pts": spine, "w": float(node.heater_width)})
        elif ctype == "MicroringWeightBank" and getattr(node, "with_heaters", False):
            # one heater ARC per sub-ring, hugging each drawn ring
            template = node._ring_component()
            if hasattr(template, "heater_arc_angles"):
                r_h = float(template.heater_radius)
                a0, a1 = template.heater_arc_angles
                for cx in node._ring_centers():
                    arc = []
                    for i in range(21):
                        ang = math.radians(a0 + (a1 - a0) * i / 20)
                        arc.append([cx + r_h * math.cos(ang), r_h * math.sin(ang)])
                    paths.append({"pts": arc, "w": float(template.heater_width)})
    except Exception:
        return None
    if not paths:
        return None

    try:
        wt = original.world_transform
        theta = math.radians(float(wt.rotation_deg.z))
        cx, cy = float(wt.position.x), float(wt.position.y)
    except Exception:
        theta, cx, cy = 0.0, 0.0, 0.0
    cos_t, sin_t = math.cos(theta), math.sin(theta)
    world_paths = []
    for path in paths:
        pts = [
            [round(cx + x * cos_t - y * sin_t, 4), round(cy + x * sin_t + y * cos_t, 4)]
            for x, y in path["pts"]
        ]
        world_paths.append({"pts": pts, "w": round(path["w"], 4)})
    return {"heat": {"paths": world_paths, "tau_s": 1.4}}


# Fraction of power leaving EACH output branch of a splitting device.
_SPLIT_POWER = {
    "MMI1x2": 0.5, "YBranch": 0.5, "MMI2x2": 0.5, "MMI2x2PowerSplitter": 0.5,
    "MMI1x3": 1 / 3, "MMI1x4": 0.25, "DirectionalCoupler": 0.5, "StarCoupler": None,
    "AWG": None,  # None = 1/n_outputs
}


def _optical_ports(node: Any) -> dict[str, Any]:
    """The node's optical world ports (skip electrical sig/gnd/pads)."""

    out = {}
    try:
        for name, port in node.world_ports().items():
            if str(getattr(port, "kind", "optical")).lower() in ("electrical", "rf", "dc"):
                continue
            out[name] = port
    except Exception:
        pass
    return out


def _node_meta(node: Any) -> dict[str, Any]:
    try:
        return node.physics_metadata() or {}
    except Exception:
        return {}


def _node_num(node: Any, meta: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = getattr(node, key, None)
        if value is None:
            value = meta.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
    return None


def _port_transmissions(node: Any, in_port: str, ports: dict[str, Any]) -> dict[str, float]:
    """Per-COMPONENT optical transmissions {exit_port: power fraction}.

    Resolution order: (1) explicit per-instance override `anim_params.transmissions`;
    (2) the instance's own optical parameters — tap_ratio / coupling_ratio /
    split_ratio (bar/cross by rail geometry) and insertion_loss_db — from attributes
    or physics_metadata(); (3) the type's split table; (4) equal split. Exit ports on
    the same facet as the input are excluded (light doesn't leave the way it came)."""

    exits = [name for name in ports if name != in_port]
    if not exits:
        return {}
    params = getattr(node, "anim_params", None) or {}
    override = params.get("transmissions")
    if isinstance(override, dict):
        return {k: max(0.0, min(float(v), 1.0)) for k, v in override.items() if k in ports}
    meta = _node_meta(node)
    in_x = float(ports[in_port].center.x)
    in_y = float(ports[in_port].center.y)
    if len(exits) > 1:
        same_facet = [e for e in exits if abs(float(ports[e].center.x) - in_x) < 0.75]
        if len(same_facet) < len(exits):
            exits = [e for e in exits if e not in same_facet]
    loss_db = _node_num(node, meta, "insertion_loss_db", "loss_db") or 0.0
    il = 10.0 ** (-max(loss_db, 0.0) / 10.0)
    ratio = _node_num(node, meta, "tap_ratio", "coupling_ratio", "split_ratio")
    if ratio is not None and 0.0 <= ratio <= 1.0 and len(exits) == 2:
        # bar port = exit on the input's rail; cross port gets the coupled fraction
        def off_rail(name: str) -> float:
            p = ports[name]
            return min(abs(float(p.center.y) - in_y), abs(float(p.center.x) - in_x))

        bar = min(exits, key=off_rail)
        cross = next(e for e in exits if e != bar)
        return {bar: (1.0 - ratio) * il, cross: ratio * il}
    ctype = _ctype(node)
    split = _SPLIT_POWER.get(ctype)
    if ctype in _SPLIT_POWER and split is None:
        split = 1.0 / len(exits)
    if split is not None:
        return {e: split * il for e in exits}
    eq = 0.97 if len(exits) == 1 else 1.0 / len(exits)
    return {e: eq * il for e in exits}


def _internal_paths(node: Any, in_port: str, ports: dict[str, Any]) -> list[dict[str, Any]]:
    """Waveguide spines THROUGH a device from the arrival port to each exit port.

    On-chip devices ARE waveguides — light entering a port continues through the
    drawn device to its other ports. Default topology: straight if the two ports
    are collinear, else via the device centre (tapers/branches meet at the body).
    MZI/MZM route via their two interferometer arms at half power each."""

    entry = ports[in_port]
    try:
        wt = node.world_transform
        cx, cy = float(wt.position.x), float(wt.position.y)
    except Exception:
        cx = cy = 0.0
    e_x, e_y = float(entry.center.x), float(entry.center.y)
    transmissions = _port_transmissions(node, in_port, ports)
    if not transmissions:
        return []

    # The device's OWN waveguide geometry wins: components implementing
    # optical_paths(in_port) return their real drawn paths in local coords
    # (each path's "power" is its fraction of the device transmission).
    custom = getattr(node, "optical_paths", None)
    if callable(custom):
        try:
            declared = custom(in_port) or []
        except Exception:
            declared = []
        if declared:
            # the device's declared paths define the internal split; scale by the
            # TOTAL throughput (an interferometer recombines its arms to one port)
            total = min(sum(transmissions.values()), 1.0) or 1.0
            out = []
            for path in declared:
                resolved = {
                    "port": str(path.get("port", "")),
                    "power": float(path.get("power", 1.0)) * total,
                    "pts": _world_xy(node, path["pts"]),
                    "delay_len": float(path.get("delay_len", 0.0)),
                }
                if path.get("powers"):  # absolute power profile along the path
                    resolved["powers"] = [float(v) * total for v in path["powers"]]
                if path.get("color"):  # resonant channel color (WDM)
                    resolved["color"] = str(path["color"])
                if path.get("mod"):  # thermo-optic response to the device heater
                    resolved["mod"] = dict(path["mod"])
                out.append(resolved)
            return out

    paths = []
    for name, power in transmissions.items():
        p = ports[name]
        p_x, p_y = float(p.center.x), float(p.center.y)
        collinear = abs(p_y - e_y) < 0.75 or abs(p_x - e_x) < 0.75
        pts = [[e_x, e_y], [p_x, p_y]] if collinear else [[e_x, e_y], [cx, cy], [p_x, p_y]]
        paths.append({"port": name, "power": power, "pts": pts})
    return paths


def _path_len(pts: list[list[float]]) -> float:
    return sum(math.dist(a, b) for a, b in zip(pts, pts[1:]))


def _circuit_trace(scene: Any, payloads: dict[int, dict[str, Any]]) -> None:
    """Trace connected on-chip circuits so light flows THROUGH devices.

    Routes bind to component ports; from each source the pulse train propagates:
    route -> device internal waveguide (split per type) -> next route, with the
    cumulative delay (length x n_group) carried as t0 so the flow is continuous
    across every joint. Resonators get their loading clock (t_arrive) from the
    real arrival time instead of a fixed offset."""

    routes = [
        n for n in scene.walk()
        if _ctype(n) in ("Route", "WaveguideRoute", "FiberRoute") and getattr(n, "kind", "optical") != "electrical"
    ]
    if not routes:
        return
    by_start: dict[tuple[int, str], list[Any]] = {}
    ends: set[tuple[int, str]] = set()
    for route in routes:
        sc_, sp = getattr(route, "start_component", None), getattr(route, "start_port", None)
        ec, ep = getattr(route, "end_component", None), getattr(route, "end_port", None)
        if sc_ is not None and sp:
            by_start.setdefault((id(sc_), str(sp)), []).append(route)
        if ec is not None and ep:
            ends.add((id(ec), str(ep)))

    def route_time(route: Any) -> float:
        flow = (payloads.get(id(route)) or {}).get("flow") or {}
        return float(flow.get("len", 0.0)) * float(flow.get("n", _NG_SILICON))

    # sources: routes leaving an UNFED component (nothing routes into it) — a route
    # out of a splitter's second port is downstream, not a new source. The source
    # component's behavioral state decides HOW the light starts:
    #   emission "cw" (default) = continuous phase fronts, "pulsed" = one packet,
    #   "off" = the whole downstream subtree stays dark.
    fed_components = {comp_id for comp_id, _ in ends}
    queue = []
    for r in routes:
        source = getattr(r, "start_component", None)
        if source is not None and id(source) in fed_components:
            continue
        emission = str(((getattr(source, "anim_params", None) or {}) if source is not None else {}).get("emission", "cw"))
        if emission == "off":
            flow = (payloads.setdefault(id(r), {})).setdefault("flow", {"len": 0.0, "n": _NG_SILICON, "power": 1.0})
            flow["power"] = 0.0  # dark route — the source is switched off
            flow["t0"] = 0.0
            continue
        queue.append((r, 0.0, 1.0, emission == "pulsed"))
    visited: set[int] = set()
    hops = 0
    while queue and hops < 400:
        hops += 1
        route, t0, power, pulsed = queue.pop(0)
        if id(route) in visited:
            continue
        visited.add(id(route))
        flow = (payloads.setdefault(id(route), {})).setdefault("flow", {"len": 0.0, "n": _NG_SILICON, "power": 1.0})
        flow["t0"] = round(t0, 4)
        flow["power"] = round(min(flow.get("power", 1.0) * power, 1.0), 4)
        if pulsed:
            flow["pulsed"] = True
        t_exit = t0 + route_time(route)
        comp = getattr(route, "end_component", None)
        in_port = str(getattr(route, "end_port", "") or "")
        if comp is None or not in_port:
            continue
        payload = payloads.setdefault(id(comp), {})
        ports = _optical_ports(comp)
        if in_port not in ports:
            continue
        guides = payload.setdefault("guides", [])
        onward: dict[str, list[float]] = {}  # exit port -> [arrival, power sum]
        for path in _internal_paths(comp, in_port, ports):
            entry = _guide_entry(path, power, t_exit)
            if pulsed:
                entry["pulsed"] = True
            guides.append(entry)
            length = _path_len(path["pts"]) + float(path.get("delay_len", 0.0))
            g_power = min(power * path["power"], 1.0)
            rec = onward.setdefault(path["port"], [0.0, 0.0])
            rec[0] = max(rec[0], t_exit + length * _NG_SILICON)
            rec[1] += g_power  # parallel paths (MZI arms) recombine at the port
        for port_name, (t_on, p_on) in onward.items():
            for nxt in by_start.get((id(comp), port_name), []):
                queue.append((nxt, t_on, min(p_on, 1.0), pulsed))


def _guide_entry(path: dict[str, Any], power: float, t_exit: float) -> dict[str, Any]:
    """One in-device animation path; a power PROFILE becomes per-segment powers so
    evanescent transfer (cos^2/sin^2 along a coupler) is baked into the light.

    ``delay_len`` (geometric length) starts the path late: coupled light GROWS on
    the neighbouring guide's own rail after the lead-in — no geometric rail-hop."""

    length = _path_len(path["pts"])
    delay = float(path.get("delay_len", 0.0)) * _NG_SILICON
    entry: dict[str, Any] = {
        "pts": [[round(x, 4), round(y, 4)] for x, y in path["pts"]],
        "len": round(length, 4), "n": _NG_SILICON,
        "power": round(min(power * path["power"], 1.0), 4), "t0": round(t_exit + delay, 4),
    }
    if path.get("color"):
        entry["color"] = str(path["color"])
    if path.get("mod"):
        entry["mod"] = dict(path["mod"])
    profile = path.get("powers")
    if profile and len(profile) == len(path["pts"]):
        pts = path["pts"]
        segments = []
        for i in range(len(pts) - 1):
            seg_p = power * (profile[i] + profile[i + 1]) / 2.0
            segments.append({
                "len": round(math.dist(pts[i], pts[i + 1]), 4),
                "n": _NG_SILICON,
                "power": round(min(seg_p, 1.0), 4),
            })
        entry["segments"] = segments
    return entry


def _seed_unrouted(scene: Any, payloads: dict[int, dict[str, Any]]) -> None:
    """Devices that declare real waveguide paths but aren't part of ANY routed
    circuit still animate standalone (galleries/demos): seed their guides from the
    west-most optical port at t0=0, full power. Devices touched by routes never
    self-seed — their light comes from the trace, or (source off) not at all."""

    touched: set[int] = set()
    for node in scene.walk():
        if _ctype(node) in ("Route", "WaveguideRoute", "FiberRoute"):
            for end in (getattr(node, "start_component", None), getattr(node, "end_component", None)):
                if end is not None:
                    touched.add(id(end))
    for node in scene.walk():
        if not callable(getattr(node, "optical_paths", None)):
            continue
        if id(node) in touched:
            continue
        payload = payloads.setdefault(id(node), {})
        if payload.get("guides"):
            continue
        ports = _optical_ports(node)
        if not ports:
            continue
        in_port = min(ports, key=lambda n: float(ports[n].center.x))
        guides = [
            _guide_entry(path, 1.0, 0.0)
            for path in _internal_paths(node, in_port, ports)
        ]
        if guides:
            payload["guides"] = guides


def anim_payload_map(scene: Any, *, wavelength_nm: float | None = None, heights: Any = None) -> dict[int, dict[str, Any]]:
    """Return ``{id(node): anim_payload}`` for every animatable node in ``scene``.

    The renderer attaches each payload to that node's scene-data item as
    ``item["anim"]``; the JS engine derives all timing from the payloads (the
    slowest full traversal is normalized to a few seconds of wall clock, so
    relative speeds — air vs fiber vs silicon — stay physically exact).
    """

    wl = float(wavelength_nm or (1550.0 if getattr(scene, "platform", "") == "on_chip" else 633.0))
    out: dict[int, dict[str, Any]] = {}
    for node in scene.walk():
        ctype = _ctype(node)
        payload: dict[str, Any] | None = None
        try:
            if ctype == "Beam":
                payload = _beam_anim(node, wl, heights)
            elif ctype == "FocusingBeam":
                payload = _envelope_anim(node)
            elif ctype in ("Route", "WaveguideRoute", "FiberRoute"):
                payload = _route_anim(node, wl)
            elif ctype == "MetalRoute":
                payload = _metal_anim(node)
            else:
                parts: dict[str, Any] = {}
                # ALL guided devices (couplers, MZIs, resonators, banks) animate via
                # their own optical_paths() — one system: port in, port out, no overlays
                if ctype in ("MZM", "PNMicroringModulator", "ElectroAbsorptionModulator"):
                    parts.update(_junction_anim(node) or {})
                heat = _heat_anim(node)  # heaters on pads, MZI arms, rings, racetracks
                if heat:
                    parts.update(heat)
                payload = parts or None
        except Exception:
            payload = None
        if payload:
            out[id(node)] = payload
    _chain_pulses(out)
    try:
        _circuit_trace(scene, out)  # light flows THROUGH devices, not around them
    except Exception:
        pass
    try:
        _seed_unrouted(scene, out)  # standalone devices still animate their guides
    except Exception:
        pass
    # drop any payloads that ended up empty
    return {k: v for k, v in out.items() if v}


def _chain_pulses(payloads: dict[int, dict[str, Any]]) -> None:
    """Give downstream beams a start delay (t0) so splits fire when the pulse arrives.

    A beam whose FIRST anchor appears mid-path in another beam is a branch (e.g. the
    reflected arm of a beamsplitter): it starts at the parent pulse's arrival time at
    that component and inherits the split power. A beam starting at another beam's
    LAST anchor is a continuation and inherits the through power. Timing is in the
    same length·n units the JS engine normalizes, so the delay is exact."""

    records = []
    for payload in payloads.values():
        if "_anchors" not in payload:
            continue
        anchors = payload["_anchors"]
        lengths = payload["_lengths"]
        arrivals = [sum(lengths[:i]) for i in range(len(anchors))]  # n=1 free space
        records.append({"p": payload, "anchors": anchors, "arrivals": arrivals, "t0": None})

    # Roots: beams whose first anchor is nobody's mid/late anchor.
    def parent_of(rec):
        first = rec["anchors"][0] if rec["anchors"] else None
        if first is None:
            return None
        for other in records:
            if other is rec:
                continue
            for j, comp in enumerate(other["anchors"]):
                if comp is first and j > 0:
                    return other, j
        return None

    for rec in records:
        if parent_of(rec) is None:
            rec["t0"] = 0.0
    for _ in range(len(records)):  # resolve chains breadth-first
        progressed = False
        for rec in records:
            if rec["t0"] is not None:
                continue
            parent = parent_of(rec)
            if parent is None or parent[0]["t0"] is None:
                continue
            up, j = parent
            comp = rec["anchors"][0]
            rec["t0"] = up["t0"] + up["arrivals"][j]
            parent_power = up["p"]["_powers"][max(j - 1, 0)]
            if j == len(up["anchors"]) - 1:
                scale = parent_power * _transmission(comp)  # continuation past the end
            else:
                scale = parent_power * max(1.0 - _transmission(comp), 0.0)  # branched arm
            segments = rec["p"]["pulse"]["segments"]
            for k, seg in enumerate(segments):
                seg["power"] = round(seg["power"] * scale, 4)
                rec["p"]["_powers"][k] = seg["power"]
            progressed = True
        if not progressed:
            break
    for rec in records:
        rec["p"]["pulse"]["t0"] = round(rec["t0"] or 0.0, 4)
    for payload in payloads.values():
        payload.pop("_anchors", None)
        payload.pop("_lengths", None)
        payload.pop("_powers", None)
