"""Server-side analytical-simulation plots for the GUI **Simulate** panel.

Presentation-only layer: takes a *built* component (or an ordered free-space chain)
plus UI params, loops the library's single-point ``trace_*`` evaluators into a sweep,
and returns ``{"kind", "plot_svg", "data", "controls"}`` — an SVG plot string, the raw
numbers, and the slider spec the panel renders. No optics live here beyond calling
``optodraw.core.*``; matplotlib is imported lazily (it is an optional dependency, the
same convention used by ``optodraw/gds/plotting.py``).
"""

from __future__ import annotations

from io import StringIO
from typing import Any

import numpy as np  # base dependency (used across optodraw.core)

_FG = "#0e2a3b"
_ACCENT = "#1f7a8c"
_ACCENT2 = "#c2603a"
_GRID = "#e3e9ee"

_AGG_SET = False


def _plt():
    """Return ``matplotlib.pyplot`` with a headless backend (lazy + optional)."""
    global _AGG_SET
    try:
        import matplotlib

        if not _AGG_SET:
            matplotlib.use("Agg")
            _AGG_SET = True
        import matplotlib.pyplot as plt
    except Exception as exc:  # pragma: no cover - exercised only without matplotlib
        raise ImportError("matplotlib is required for simulation plots (pip install matplotlib)") from exc
    return plt


def _slider(name: str, label: str, lo: float, hi: float, step: float, value: float) -> dict[str, Any]:
    return {"name": name, "label": label, "min": lo, "max": hi, "step": step, "value": float(value)}


def _new_fig():
    plt = _plt()
    fig, ax = plt.subplots(figsize=(4.7, 2.9), dpi=110)
    ax.grid(True, color=_GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color("#bcc7d0")
    ax.tick_params(colors=_FG, labelsize=8)
    # a panel this size cannot carry a dozen six-digit wavelength ticks without
    # them running together — cap the count and let matplotlib pick round values
    from matplotlib.ticker import MaxNLocator

    ax.xaxis.set_major_locator(MaxNLocator(nbins=5))
    ax.yaxis.set_major_locator(MaxNLocator(nbins=5))
    return fig, ax


def _svg(fig) -> str:
    buf = StringIO()
    try:
        fig.savefig(buf, format="svg", bbox_inches="tight", transparent=True)
        return buf.getvalue()
    finally:
        _plt().close(fig)


# --------------------------------------------------------------------------- #
# Which simulations apply to a given component
# --------------------------------------------------------------------------- #
_RESONATOR_TYPES = {"MicroringResonator", "PNMicroringModulator", "RacetrackResonator", "RacetrackModulator"}
_RESONATOR_FAMILIES = {"microring", "pn_microring", "racetrack", "racetrack_modulator"}
_KIND_LABELS = {
    "resonance": "Resonance spectrum",
    "mzi_transfer": "MZI transfer",
    "mzm_transfer": "MZM drive transfer",
    "guided": "Guided-mode phase",
}


def kind_label(kind: str) -> str:
    return _KIND_LABELS.get(kind, kind)


def simulate_kinds(component: Any) -> list[str]:
    """Return the analytical-simulation kinds applicable to ``component``."""
    ctype = getattr(component, "component_type", "") or ""
    family = getattr(component, "schematic_family", "") or ""
    kinds: list[str] = []
    if ctype in _RESONATOR_TYPES or family in _RESONATOR_FAMILIES:
        kinds.append("resonance")
    if ctype == "MZM" or family == "mzm":
        kinds.append("mzm_transfer")
    elif ctype == "MZI" or family == "mzi":
        kinds.append("mzi_transfer")
    if ctype == "Waveguide" or family == "waveguide":
        kinds.append("guided")
    return kinds


# --------------------------------------------------------------------------- #
# Per-component simulations
# --------------------------------------------------------------------------- #
def simulate(component: Any, kind: str, params: dict[str, Any] | None) -> dict[str, Any]:
    if params is None:
        params = {}
    elif not isinstance(params, dict):
        raise ValueError("Simulation parameters must be an object")
    if kind not in simulate_kinds(component):
        raise ValueError(f"{kind} is not available for {getattr(component, 'component_type', 'this component')}")
    if kind == "resonance":
        return _resonance(component, params)
    if kind == "mzi_transfer":
        return _mzi(component, params)
    if kind == "mzm_transfer":
        return _mzm(component, params)
    if kind == "guided":
        return _guided(component, params)
    raise ValueError(f"unknown simulation kind '{kind}'")


def _resonance(ring: Any, params: dict[str, Any]) -> dict[str, Any]:
    from optodraw.core.resonator import lorentzian_transmission, trace_ring_resonance

    bias = float(params.get("bias_voltage_v", 0.0))
    span = float(params.get("span_nm", 2.0))
    if not np.isfinite(bias) or not np.isfinite(span) or span <= 0:
        raise ValueError("bias must be finite and wavelength span must be positive and finite")
    op = trace_ring_resonance(ring, bias_voltage_v=bias)
    lam0 = float(op["lambda0_nm"])
    q = float(op["Q"])
    lams = np.linspace(lam0 - span / 2.0, lam0 + span / 2.0, 401)
    thru = [lorentzian_transmission(float(w), lam0, q, port="through") for w in lams]
    drop = [lorentzian_transmission(float(w), lam0, q, port="drop") for w in lams]
    fig, ax = _new_fig()
    ax.plot(lams, thru, color=_ACCENT, lw=1.8, label="through")
    ax.plot(lams, drop, color=_ACCENT2, lw=1.6, label="drop")
    ax.axvline(lam0, color="#9aa7b1", lw=0.8, ls="--")
    ax.set_xlabel("wavelength (nm)")
    ax.set_ylabel("transmission")
    ax.set_ylim(-0.03, 1.05)
    ax.legend(fontsize=7, frameon=False, loc="lower right")
    ax.set_title(f"λ₀ = {lam0:.3f} nm    Q = {q:,.0f}    FWHM = {float(op['fwhm_nm']) * 1000:.1f} pm", fontsize=8, color=_FG)
    return {
        "kind": "resonance",
        "plot_svg": _svg(fig),
        "data": {"lambda0_nm": lam0, "Q": q, "fwhm_nm": float(op["fwhm_nm"])},
        "controls": [
            _slider("bias_voltage_v", "Bias (V)", -5.0, 5.0, 0.1, bias),
            _slider("span_nm", "Span (nm)", 0.2, 6.0, 0.1, span),
        ],
    }


def _mzi(mzi: Any, params: dict[str, Any]) -> dict[str, Any]:
    from optodraw.core.interferometer import trace_mzi_transfer

    wl = float(params.get("wavelength_nm", 1550.0))
    imbalance = float(params.get("arm_imbalance_um", 0.0))
    if not np.isfinite(wl) or wl <= 0 or not np.isfinite(imbalance):
        raise ValueError("wavelength must be positive and finite; arm imbalance must be finite")
    phases = np.linspace(0.0, 2.0 * np.pi, 241)
    bar, cross = [], []
    for phase in phases:
        res = trace_mzi_transfer(mzi, phase_bias_rad=float(phase), wavelength_nm=wl, arm_imbalance_um=imbalance)
        bar.append(res["through_power"])
        cross.append(res["drop_power"])
    fig, ax = _new_fig()
    ax.plot(phases / np.pi, bar, color=_ACCENT, lw=1.8, label="bar")
    ax.plot(phases / np.pi, cross, color=_ACCENT2, lw=1.6, label="cross")
    ax.set_xlabel("phase bias (π rad)")
    ax.set_ylabel("power")
    ax.set_ylim(-0.03, 1.05)
    ax.legend(fontsize=7, frameon=False, loc="center right")
    ax.set_title("MZI transfer vs phase", fontsize=8, color=_FG)
    return {
        "kind": "mzi_transfer",
        "plot_svg": _svg(fig),
        "data": {"wavelength_nm": wl, "arm_imbalance_um": imbalance},
        "controls": [
            _slider("wavelength_nm", "λ (nm)", 1500.0, 1600.0, 1.0, wl),
            _slider("arm_imbalance_um", "ΔL (µm)", 0.0, 50.0, 0.5, imbalance),
        ],
    }


def _mzm(mzm: Any, params: dict[str, Any]) -> dict[str, Any]:
    from optodraw.core.interferometer import trace_mzm_transfer

    vpi = float(params.get("Vpi", 4.0))
    wl = float(params.get("wavelength_nm", 1550.0))
    if not np.isfinite(vpi) or vpi <= 0 or not np.isfinite(wl) or wl <= 0:
        raise ValueError("Vpi and wavelength must be positive and finite")
    volts = np.linspace(-2.0 * vpi, 2.0 * vpi, 241)
    out = []
    for volt in volts:
        res = trace_mzm_transfer(mzm, drive_voltage=float(volt), Vpi=vpi, wavelength_nm=wl)
        out.append(res["through_power"])
    fig, ax = _new_fig()
    ax.plot(volts, out, color=_ACCENT, lw=1.8)
    for marker in (vpi, -vpi):
        ax.axvline(marker, color="#9aa7b1", lw=0.8, ls="--")
    ax.set_xlabel("drive voltage (V)")
    ax.set_ylabel("transmission")
    ax.set_ylim(-0.03, 1.05)
    ax.set_title(f"MZM transfer    Vπ = {vpi:.1f} V", fontsize=8, color=_FG)
    return {
        "kind": "mzm_transfer",
        "plot_svg": _svg(fig),
        "data": {"Vpi": vpi, "wavelength_nm": wl},
        "controls": [
            _slider("Vpi", "Vπ (V)", 0.5, 10.0, 0.1, vpi),
            _slider("wavelength_nm", "λ (nm)", 1500.0, 1600.0, 1.0, wl),
        ],
    }


def _guided(waveguide: Any, params: dict[str, Any]) -> dict[str, Any]:
    from optodraw.core.guided import trace_guided_path

    loss = float(params.get("loss_db_per_um", 0.0))
    if not np.isfinite(loss) or loss < 0:
        raise ValueError("loss must be nonnegative and finite")
    wls = np.linspace(1500.0, 1600.0, 401)
    ref = trace_guided_path([waveguide], wavelength_nm=1550.0, loss_db_per_um=loss)
    phase = [trace_guided_path([waveguide], wavelength_nm=float(w), loss_db_per_um=loss).phase_rad for w in wls]
    fig, ax = _new_fig()
    ax.plot(wls, (np.array(phase) - ref.phase_rad) / np.pi, color=_ACCENT, lw=1.6)
    ax.set_xlabel("wavelength (nm)")
    ax.set_ylabel("phase change from 1550 nm (π rad)")
    ax.set_title(f"L = {ref.path_length_um:.1f} µm    n_eff = {ref.effective_index:.3f}    loss = {ref.loss_db:.2f} dB", fontsize=8, color=_FG)
    return {
        "kind": "guided",
        "plot_svg": _svg(fig),
        "data": {"path_length_um": float(ref.path_length_um), "effective_index": float(ref.effective_index), "loss_db": float(ref.loss_db)},
        "controls": [_slider("loss_db_per_um", "loss (dB/µm)", 0.0, 0.1, 0.001, loss)],
    }


# --------------------------------------------------------------------------- #
# Polarization (free-space chain) projected onto the S1-S2 plane
# --------------------------------------------------------------------------- #
_POL_INPUTS = {
    "H": (1.0, 1.0, 0.0, 0.0),
    "V": (1.0, -1.0, 0.0, 0.0),
    "D": (1.0, 0.0, 1.0, 0.0),
    "A": (1.0, 0.0, -1.0, 0.0),
    "R": (1.0, 0.0, 0.0, 1.0),
    "L": (1.0, 0.0, 0.0, -1.0),
}


def simulate_polarization(components: list[Any], params: dict[str, Any] | None) -> dict[str, Any]:
    from optodraw.core.polarization import StokesVector, trace_stokes_through

    if params is None:
        params = {}
    elif not isinstance(params, dict):
        raise ValueError("Simulation parameters must be an object")
    state = str(params.get("input", "H")).upper()
    if state not in _POL_INPUTS:
        raise ValueError(f"unknown polarization input '{state}'")
    wl = float(params.get("wavelength_nm", 633.0))
    if not np.isfinite(wl) or wl <= 0:
        raise ValueError("wavelength must be positive and finite")
    s_in = StokesVector(*_POL_INPUTS[state])
    comps = list(components)

    def _xy(stokes: Any) -> tuple[float, float]:
        s0 = stokes.S0 or 1.0
        return (stokes.S1 / s0, stokes.S2 / s0)

    pts = [_xy(s_in)]
    final = s_in
    for i in range(1, len(comps) + 1):
        result = trace_stokes_through(comps[: i], s_in, wavelength_nm=wl)
        final = result.stokes
        pts.append(_xy(final))

    fig, ax = _new_fig()
    circle = np.linspace(0, 2 * np.pi, 200)
    ax.plot(np.cos(circle), np.sin(circle), color="#bcc7d0", lw=1.0)
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    ax.plot(xs, ys, color=_ACCENT, lw=1.4, marker="o", ms=3)
    ax.scatter([xs[0]], [ys[0]], color="#2e7d32", zorder=5, s=28, label="in")
    ax.scatter([xs[-1]], [ys[-1]], color=_ACCENT2, zorder=5, s=28, label="out")
    for label, (lx, ly) in {"H": (1.06, 0), "V": (-1.16, 0), "D": (0, 1.07), "A": (0, -1.12)}.items():
        ax.text(lx, ly, label, fontsize=7, color="#9aa7b1", ha="center", va="center")
    ax.set_aspect("equal")
    ax.set_xlim(-1.3, 1.3)
    ax.set_ylim(-1.3, 1.3)
    ax.set_xlabel("S1 / S0")
    ax.set_ylabel("S2 / S0")
    ax.legend(fontsize=7, frameon=False, loc="upper right")
    dop = float(final.degree_of_polarization())
    ax.set_title(f"Stokes S1-S2 projection   DOP = {dop:.2f}   S3/S0 = {final.S3 / (final.S0 or 1.0):+.2f}", fontsize=8, color=_FG)
    return {
        "kind": "polarization",
        "plot_svg": _svg(fig),
        "data": {"stokes": [float(x) for x in final.as_tuple()], "degree_of_polarization": dop, "stages": len(comps)},
        "controls": [],
        "input_options": list(_POL_INPUTS.keys()),
        "input": state,
    }
