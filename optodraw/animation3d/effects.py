"""The heat and the RF the Field look draws, from the engine's numbers.

Heat: every driven heater gets its spine (the parts' own heater geometry, as ``timeline3d._heat_anim`` reads it, which
this module does not import), its width, and the peak rise in temperature that gives the engine's phase for that heater
over the heater's length (``heater_delta_t_k``). RF: every driven electro-optic modulator gets the two electrode edges
that face each other across the gap and the drive from the engine's parameters. The player draws the closed forms from
these constants only.
"""

from __future__ import annotations

import math
import re
from typing import Any

from optodraw.animation_engine.behaviours import polyline_length
from optodraw.animation_engine.behaviours.geometry import local_to_world
from optodraw.animation_engine.behaviours.interferometers import P_PI_MW, heater_phase, mzm_v_pi

from .fieldmodel import C_UM_PER_PS, heater_delta_t_k, rf_field_v_per_um

HEAT_TAU_S = 0.4                    # the heat's time constant as drawn: far slower than a real heater's (model)
REAL_TAU_S = 4e-6                   # a thin-film heater on thin oxide: a few microseconds (illustrative)
OXIDE_DIFFUSIVITY_UM2_S = 8.5e5     # heat diffusivity of silicon dioxide, 8.5e-7 m^2/s (literature)
# the Gaussian's variance grows as sigma0^2 + GROW t: the spread a real heater reaches in REAL_TAU_S, drawn over HEAT_TAU_S
HEAT_GROW_UM2_PER_S = 2.0 * OXIDE_DIFFUSIVITY_UM2_S * REAL_TAU_S / HEAT_TAU_S
HEAT_HOLD_TAU = 3                   # the map holds after this many time constants (display)
RF_INDEX = 2.5                      # the RF wave's index on the electrodes (model: a typical slow-wave electrode)
RF_CYCLE_S = 1.0                    # one RF period is drawn in this many seconds
RF_PERIODS = 2                      # periods drawn along the electrodes
ELECTRODE_FRACTION = 0.47           # the drawn rails are this fraction of the active length each way


def _world(part: Any, points) -> list[list[float]]:
    return [[round(x, 4), round(y, 4)] for x, y in local_to_world(part, points)]


def _arc(cx: float, cy: float, radius: float, start_deg: float, end_deg: float, count: int = 49):
    return [(cx + radius * math.cos(math.radians(start_deg + (end_deg - start_deg) * i / (count - 1))),
             cy + radius * math.sin(math.radians(start_deg + (end_deg - start_deg) * i / (count - 1))))
            for i in range(count)]


def _spines(part: Any, sid: str, params: dict) -> list[tuple[str, list, float, bool]]:
    """``(name, local spine, width, engine uses the heater)`` for each heater the part draws, from its own heater
    geometry. The heater's power is the engine's parameter ``heater:<name>``. A ring's heater adds to the ring's
    phase; an MZI's or a phase shifter's heater is used unless a ``phase`` parameter for the same place takes over."""

    draw = part._draw_variant() if hasattr(part, "_draw_variant") else part
    kind = getattr(part, "component_type", "")
    out: list[tuple[str, list, float, bool]] = []
    if kind == "CoupledRingFilter" and part.with_heaters:
        for k in range(1, int(part.order) + 1):
            out.append((f"{sid}:ring{k}", list(draw.heater_centerline(k)), float(draw.heater_width), True))
    elif kind == "MicroringWeightBank" and part.with_heaters:
        ring = draw._ring_component()
        if hasattr(ring, "heater_arc_angles"):
            start, end = ring.heater_arc_angles
            for j, cx in enumerate(draw._ring_centers()):         # the bank adds the heater's phase to any other
                out.append((f"{sid}:ring{j + 1}", _arc(cx, 0.0, float(ring.heater_radius), start, end, 21),
                            float(ring.heater_width), True))
    elif kind == "MZI":
        half, arm_y = float(draw.heater_length) / 2.0, float(draw.arm_gap) / 2.0
        out.append((sid, [(-half, arm_y), (half, arm_y)], float(draw.heater_strip_width),
                    f"phase:{sid}:arm1" not in params))
    elif kind == "PhaseShifter":
        half = float(draw.shifter_length) / 2.0
        out.append((sid, [(-half, 0.0), (half, 0.0)], max(float(draw.width) * 1.8, 0.9), f"phase:{sid}" not in params))
    elif getattr(part, "with_heater", False) and hasattr(draw, "heater_centerline"):
        out.append((sid, [(float(x), float(y)) for x, y in draw.heater_centerline()], float(draw.heater_width), True))
    return out


def drive_keys(part: Any, sid: str) -> list[tuple[str, float]]:
    """``(parameter, top of its swing)`` for each drive of a part: each heater it draws and each heater of a
    ring-assisted MZI (``heater:<name>``, 0 to the engine's 20 mW, about pi), and a modulator's drive (``drive:<sid>``,
    0 to its v_pi). [] for a part with no drive."""

    kind = getattr(part, "component_type", "")
    if kind == "MZM":
        return [(f"drive:{sid}", mzm_v_pi(part))]
    names = [name for name, *_ in _spines(part, sid, {})]
    if kind == "RingAssistedMZI" and part.with_heaters:
        names = [sid] + [f"{sid}:ring{r['k']}" for r in part._draw_variant().ring_layout()]
    return [(f"heater:{name}", P_PI_MW) for name in names]


def nice_ceiling(value: float) -> float:
    """The least 1, 2 or 5 times a power of ten that is at least ``value`` (0 for no value)."""

    if value <= 0:
        return 0.0
    base = 10.0 ** math.floor(math.log10(value))
    return next(m * base for m in (1, 2, 5, 10) if m * base >= value * (1 - 1e-12))


def build_heat(parts: dict[str, Any], params: dict | None, wavelength_nm: float) -> list[dict[str, Any]]:
    """One entry per driven heater: the spine in world coordinates, its width, and the peak rise in temperature (K)
    that gives the phase the engine gets from the heater's power (``heater:<name>``, mW) over the spine's length, at
    the light's wavelength (``wavelength_nm``, the input wavelength). A heater with no power has no entry, nor has an
    MZI's or a phase shifter's heater whose place the engine sets by ``phase``: heat comes only from a drawn heater
    with power. A ring's heater adds to the ring's ``phase``, so it is drawn whatever that phase."""

    out = []
    for sid, part in parts.items():
        for name, spine, width, used in _spines(part, sid, params or {}):
            length = polyline_length(spine)
            power = float((params or {}).get(f"heater:{name}", 0.0))
            if not used or power <= 0.0 or length <= 0 or len(spine) < 2:
                continue
            out.append({"sid": name, "path": _world(part, spine), "width_um": round(width, 4),
                        "delta_t_k": heater_delta_t_k(heater_phase(name, params or {}), wavelength_nm, length),
                        "tau_s": HEAT_TAU_S, "grow_um2_per_s": HEAT_GROW_UM2_PER_S, "hold_tau": HEAT_HOLD_TAU})
    return out


def heat_notices(parts: dict[str, Any], params: dict | None) -> list[str]:
    """A notice for each driven part whose heat is not drawn: a thermo-optic modulator, a ring-assisted interferometer
    and a heater pad."""

    found = []
    for sid, part in parts.items():
        kind, given = getattr(part, "component_type", ""), params or {}
        if kind == "MZM":
            driven = getattr(part, "mechanism", "") == "thermo_optic" and float(given.get(f"drive:{sid}", 0.0)) != 0.0
        elif kind in ("RingAssistedMZI", "HeaterPad"):
            driven = any(float(v) > 0 for k, v in given.items() if k == f"heater:{sid}" or k.startswith(f"heater:{sid}:"))
        else:
            driven = False
        if driven:
            found.append(f"{shown_name(parts, sid)} is driven; its heat is not drawn yet")
    return found


def _gaps(draw: Any) -> list[tuple[float, float, float]]:
    """``(signal edge y, ground edge y, half length)`` of each pair of facing electrode edges of a modulator, in its
    own frame, from the rails it draws."""

    m = draw._active_metrics()
    upper, off = draw.arm_gap / 2.0, m["outer_rail_offset"]
    sig_w, gnd_w, half = m["signal_rail_width"] / 2.0, m["rail_width"] / 2.0, m["pin_length"] * ELECTRODE_FRACTION
    if draw.drive_style == "gs":
        return [(upper + off - sig_w, upper - off + gnd_w, half)]
    return [(sig_w, upper + off - gnd_w, half), (-sig_w, -upper - off + gnd_w, half)]


def build_rf(parts: dict[str, Any], params: dict | None) -> list[dict[str, Any]]:
    """One entry per gap of each electro-optic modulator the engine drives (``drive:<sid>`` not zero)."""

    out = []
    for sid, part in parts.items():
        voltage = float((params or {}).get(f"drive:{sid}", 0.0))
        if getattr(part, "component_type", "") != "MZM" or part.mechanism != "electro_optic" or voltage == 0.0:
            continue
        draw = part._draw_variant()
        for signal_y, ground_y, half in _gaps(draw):
            length = 2.0 * half
            out.append({"sid": sid, "signal": _world(part, [(-half, signal_y), (half, signal_y)]),
                        "ground": _world(part, [(-half, ground_y), (half, ground_y)]),
                        "gap_um": round(abs(signal_y - ground_y), 4), "v": voltage,
                        "v_rf_um_per_ps": C_UM_PER_PS / RF_INDEX, "wave_um": length / RF_PERIODS,
                        # the drawn wave runs one period in RF_CYCLE_S: the display time scale of the RF alone
                        "seconds_per_ps": RF_CYCLE_S * (C_UM_PER_PS / RF_INDEX) / (length / RF_PERIODS)})
    return out


def shown_name(parts: dict[str, Any], name: str) -> str:
    """What the captions, the notices and the tour call a part (or a heater of it): its label, else its type in words
    and its number ("MZM 1", "Directional coupler 3"); a heater keeps its place in words ("ring 2")."""

    sid = name.split(":")[0]
    part = parts.get(sid)
    shown = str(getattr(part, "label", "") or "").strip()
    if not shown:
        words = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", getattr(part, "component_type", "") or sid).split()
        number = re.search(r"\d+$", sid)
        shown = " ".join(words[:1] + [w if w.isupper() else w.lower() for w in words[1:]])
        shown += f" {number.group()}" if number else ""
    rest = name[len(sid):].lstrip(":")
    return shown + (" " + re.sub(r"(?<=[a-z])(?=\d)", " ", rest) if rest else "")


def heat_captions(heat: list[dict[str, Any]], parts: dict[str, Any] | None = None) -> list[str]:
    if not heat:
        return []
    parts = parts or {}
    shown = [f"Heater on {shown_name(parts, h['sid'])}: up to {h['delta_t_k']:.1f} K above the chip." for h in heat[:3]]
    if len(heat) > 3:
        shown.append(f"{len(heat)} heaters are driven. The largest rise is {max(h['delta_t_k'] for h in heat):.1f} K.")
    return shown + ["Heat is a simple diffusion model.",
                    f"Heat time constant is shown as {HEAT_TAU_S:g} s, about {REAL_TAU_S * 1e6:g} us real.",
                    f"The heat map holds after {HEAT_HOLD_TAU} time constants."]


def rf_captions(rf: list[dict[str, Any]], parts: dict[str, Any] | None = None) -> list[str]:
    if not rf:
        return []
    parts = parts or {}
    shown = [f"Drive on {shown_name(parts, r['sid'])}: {r['v']:g} V, {rf_field_v_per_um(r['v'], r['gap_um']):.2f} V per um "
             f"across a {r['gap_um']:.1f} um gap." for r in rf[:3]]
    return shown + [f"RF wave is drawn {RF_PERIODS} periods long on the electrodes, at {RF_CYCLE_S:g} s per period.",
                    f"RF time scale is {rf[0]['seconds_per_ps']:.3g} s per ps, slower than real."]
