"""A lightweight SVG top view of a GDS layout with the cut line.

Pure string building (no matplotlib): crisp at any zoom, small, exportable, and
visually consistent with the rest of the editor (which is SVG everywhere).
"""

from __future__ import annotations

import hashlib
from html import escape

_FONT = "Inter, system-ui, -apple-system, Segoe UI, Roboto, sans-serif"
_INK = "#1b2330"
_GRID = "#e3e8ef"
_MUTED = "#586173"


def _clip_id(prefix: str, *values: object) -> str:
    digest = hashlib.blake2s(repr(values).encode("utf-8"), digest_size=6).hexdigest()
    return f"{prefix}-{digest}"


def topview_svg(
    polys: list[tuple[list, str, float]],
    cut: tuple[float, float, float, float],
    *,
    bounds: tuple[float, float, float, float],
    title: str,
    width: int = 360,
    height: int = 340,
    frame: list[tuple[float, float]] | None = None,
) -> str:
    """Top view: filled polygons (data coords, y-up), the red cut line, and ``frame`` (a polygon, such as the
    square a top view shows) dashed."""

    xmin, ymin, xmax, ymax = bounds
    if xmax <= xmin:
        xmax = xmin + 1.0
    if ymax <= ymin:
        ymax = ymin + 1.0
    ml, mr, mt, mb = 44, 14, 30, 34
    if width <= ml + mr or height <= mt + mb:
        raise ValueError("Top-view dimensions are too small for the plot")
    pw, ph = width - ml - mr, height - mt - mb
    clip_id = _clip_id("optodraw-topview", width, height, title, bounds, polys, cut)
    sc = min(pw / (xmax - xmin), ph / (ymax - ymin))
    ox = ml + (pw - sc * (xmax - xmin)) / 2
    oy = mt + (ph - sc * (ymax - ymin)) / 2

    def sx(x: float) -> float:
        return ox + (x - xmin) * sc

    def sy(y: float) -> float:  # y-up -> SVG y-down
        return oy + (ymax - y) * sc

    out: list[str] = []
    out.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'font-family="{_FONT}" font-size="11">'
    )
    out.append(f'<rect x="0" y="0" width="{width}" height="{height}" fill="#ffffff"/>')
    out.append(
        f'<text x="{ml}" y="20" font-size="12" font-weight="600" fill="{_INK}">{escape(title)}</text>'
    )
    out.append(
        f'<rect x="{ml}" y="{mt}" width="{pw}" height="{ph}" fill="#fbfcfe" stroke="{_GRID}"/>'
    )
    out.append(f'<clipPath id="{clip_id}"><rect x="{ml}" y="{mt}" width="{pw}" height="{ph}"/></clipPath>')
    out.append(f'<g clip-path="url(#{clip_id})">')
    for poly, color, alpha in polys:
        pts = " ".join(f"{sx(px):.1f},{sy(py):.1f}" for px, py in poly)
        out.append(f'<polygon points="{pts}" fill="{escape(color)}" fill-opacity="{alpha:.2f}"/>')
    ax, ay, bx, by = cut
    out.append(
        f'<line x1="{sx(ax):.1f}" y1="{sy(ay):.1f}" x2="{sx(bx):.1f}" y2="{sy(by):.1f}" '
        f'stroke="#e8123a" stroke-width="1.6"/>'
    )
    for x, y in ((ax, ay), (bx, by)):
        out.append(f'<circle cx="{sx(x):.1f}" cy="{sy(y):.1f}" r="2.6" fill="#e8123a" stroke="#fff" stroke-width="0.6"/>')
    if frame:
        pts = " ".join(f"{sx(px):.1f},{sy(py):.1f}" for px, py in frame)
        out.append(f'<polygon points="{pts}" fill="none" stroke="{_INK}" stroke-width="1.2" stroke-dasharray="4 3"/>')
    out.append("</g>")
    out.append(
        f'<text x="{ml + pw / 2}" y="{height - 4}" text-anchor="middle" fill="{_MUTED}">x (µm)</text>'
    )
    out.append("</svg>")
    return "".join(out)
