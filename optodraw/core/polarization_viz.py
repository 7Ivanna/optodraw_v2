"""Stokes-to-geometry helpers for 2D polarization ellipse and Poincaré inset overlays."""

from __future__ import annotations

import math
from typing import Any

from optodraw.core.polarization import StokesVector, stokes_annotation_stub


def _parse_stokes(stokes: Any) -> tuple[float, float, float, float]:
    if isinstance(stokes, StokesVector):
        return stokes.as_tuple()
    if isinstance(stokes, dict):
        values = (
            float(stokes.get("S0", stokes.get("s0", 0.0))),
            float(stokes.get("S1", stokes.get("s1", 0.0))),
            float(stokes.get("S2", stokes.get("s2", 0.0))),
            float(stokes.get("S3", stokes.get("s3", 0.0))),
        )
    elif isinstance(stokes, (tuple, list)) and len(stokes) == 4:
        values = tuple(float(v) for v in stokes)
    else:
        raise TypeError("stokes must be StokesVector, 4-tuple, or dict with S0..S3")
    return StokesVector(*values).as_tuple()


def stokes_to_ellipse(
    stokes: Any,
    *,
    cx: float = 0.0,
    cy: float = 0.0,
    scale: float = 4.0,
) -> dict[str, float | str]:
    """Map a Stokes vector to SVG ellipse overlay geometry.

    Returns ``cx``, ``cy``, ``rx``, ``ry``, ``angle`` (degrees), plus ``s3`` and
    a short ``label`` for captions.
    """

    s0, s1, s2, s3 = _parse_stokes(stokes)
    stokes_vec = StokesVector(s0, s1, s2, s3)
    label = stokes_annotation_stub(stokes_vec)

    if s0 <= 1e-12:
        return {"cx": cx, "cy": cy, "rx": 0.0, "ry": 0.0, "angle": 0.0, "s3": 0.0, "label": label}

    n1, n2, n3 = s1 / s0, s2 / s0, s3 / s0
    dop = stokes_vec.degree_of_polarization()

    if dop < 0.05:
        radius = scale * 0.35
        return {
            "cx": cx,
            "cy": cy,
            "rx": radius,
            "ry": radius,
            "angle": 0.0,
            "s3": n3,
            "label": label,
        }

    psi = 0.5 * math.atan2(n2, n1)
    chi = 0.5 * math.atan2(n3, math.hypot(n1, n2))
    semi_major = scale * 0.5 * math.sqrt(max(dop, 0.0))

    if abs(math.cos(chi)) < 1e-9:
        rx = ry = semi_major
    elif abs(chi) < 1e-4:
        rx = semi_major
        ry = max(semi_major * 0.06, scale * 0.03)
    else:
        semi_minor = semi_major * abs(math.tan(chi))
        rx = max(semi_major, semi_minor)
        ry = min(semi_major, semi_minor)

    return {
        "cx": cx,
        "cy": cy,
        "rx": rx,
        "ry": ry,
        "angle": math.degrees(psi),
        "s3": n3,
        "label": label,
    }


def stokes_to_poincare_2d(stokes: Any) -> tuple[float, float]:
    """Project normalized S1, S2 for a 2D Poincaré-sphere inset (S3 via color/label)."""

    s0, s1, s2, _s3 = _parse_stokes(stokes)
    if s0 <= 1e-12:
        return (0.0, 0.0)
    return (s1 / s0, s2 / s0)


def stokes_s3_normalized(stokes: Any) -> float:
    """Return normalized S3 for inset coloring."""

    s0, _s1, _s2, s3 = _parse_stokes(stokes)
    if s0 <= 1e-12:
        return 0.0
    return s3 / s0
