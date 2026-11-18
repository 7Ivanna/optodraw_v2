"""Look A: the cross-section as a textbook process figure, in vector SVG.

``s`` is always true. ``z`` is true too unless the thinnest layer would be under 2 pt tall at the figure
width: then it is stretched by the smallest of 2, 3, 5, 10, 20, 50 that makes it readable, and the figure
says "z × N" and carries a vertical scale bar. A thick BOX is cut short with a break, and a stub of
substrate sits under it. Labels sit inside a region when they fit, else beside the figure with a leader.
Lengths come out in nm under 1 um. A section made with a z window shows only that band of z, with no break.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from html import escape
from types import SimpleNamespace
from typing import Any, Callable

import numpy as np
import shapely
from shapely.geometry import LineString, MultiPolygon, Polygon, box
from shapely.ops import unary_union

from optodraw.core.markup import has_markup, plain, svg_spans, svg_text
from optodraw.gds.palette import DOPING, canonical, doping_label, material_fill

_MM_PER_PT = 0.3528
_LABEL_COLUMN = 18.0                 # mm on the right for labels that do not fit inside
_MARGIN = 2.0                        # mm round the plot
_STUB = 2.5                          # mm of substrate under a break
_OUTLINE = 0.5 * _MM_PER_PT          # region outlines, 0.5 pt
_MIN_PT = 2.0                        # the thinnest layer is drawn at least this tall
_Z_STEPS = (2, 3, 5, 10, 20, 50)     # the z stretches "auto" picks from
_INK = "#2b2f36"
_TOP_MIN_OXIDE = 0.6                 # um of top oxide over the highest feature before a cut-out is worth it
_TOP_SHARE = 0.4                     # ... and the share of the height that oxide must take
_TOP_KEEP = 0.4                      # um of oxide kept over the highest feature, and at least
_TOP_ROOM = 4.5                      # mm: room for the rib width dimension and its value
_TOP_UNDER = 0.2                     # um of oxide kept under the lowest point of the top surface
_TOP_GAP = 1.0                       # mm between the two parts, for the break mark
_BEAM_ROOM = 7.0                     # mm above the figure, at least, for a beam to come in through
_BEAM_TOP = 0.12                     # half the top of a beam's cone, as a share of the plot's width


@dataclass
class _Frame:
    s0: float
    s1: float
    z0: float
    z1: float
    scale: float                     # mm per um along s
    zscale: float                    # mm per um along z
    left: float
    top: float
    keep: float | None = None        # a thick top oxide is cut out between keep and resume ...
    resume: float | None = None
    gap: float = 0.0                 # ... and drawn with this gap (mm) for its break mark

    def x(self, s: float) -> float:
        return self.left + (s - self.s0) * self.scale

    def y(self, z: float) -> float:
        return float(self.ys(np.asarray(z, dtype=float)))

    def ys(self, z):
        """``y`` for an array of ``z``: the part above the cut-out moves down to close it, less the gap."""

        upper = self.top + (self.z1 - z) * self.zscale
        if self.keep is None:
            return upper
        lower = self.top + (self.z1 - self.resume) * self.zscale + self.gap + (self.keep - z) * self.zscale
        return np.where(z >= (self.keep + self.resume) / 2.0, upper, lower)

    def plot_height(self) -> float:
        span = self.z1 - self.z0 - (self.resume - self.keep if self.keep is not None else 0.0)
        return span * self.zscale + self.gap

    def clip(self):
        """The drawn part of the plane: one box, or two when the top oxide is cut out."""

        if self.keep is None:
            return box(self.s0, self.z0, self.s1, self.z1)
        return box(self.s0, self.z0, self.s1, self.keep).union(box(self.s0, self.resume, self.s1, self.z1))


def _size(um: float) -> str:
    return f"{um * 1000:.0f} nm" if um < 1.0 else f"{um:.3g} µm"


def _nice(limit: float) -> float:
    """The largest 1, 2 or 5 times a power of ten that is not above ``limit``."""

    exponent = math.floor(math.log10(max(limit, 1e-9)))
    return max(step * 10 ** exponent for step in (1, 2, 5) if step * 10 ** exponent <= limit)


def _path(polygon: Polygon, frame: _Frame) -> str:
    rings = [polygon.exterior, *polygon.interiors]
    parts = []
    for ring in rings:
        points = [f"{frame.x(s):.3f},{frame.y(z):.3f}" for s, z in ring.coords]
        parts.append("M" + " L".join(points) + " Z")
    return " ".join(parts)


def _label_text(x: float, y: float, text: str, font: float, family: str, anchor: str = "middle") -> str:
    """A label at ``x``, ``y`` (mm). Plain words keep their anchor. A label with markup (``SiO_2``) is set from a start
    worked out from the letter widths: a renderer anchors each run of an anchored text by itself."""

    if not has_markup(text):
        return (f'<text class="label" x="{x:.3f}" y="{y:.3f}" font-size="{font:.3f}" font-family="{family}" '
                f'text-anchor="{anchor}">{svg_spans(text, font)}</text>')
    return svg_text(text, round(font, 3), x, round(y, 3), anchor, f'class="label" font-family="{family}"')


def _polygons(geometry) -> list[Polygon]:
    if geometry.is_empty:
        return []
    return [g for g in shapely.get_parts(geometry) if isinstance(g, Polygon)]   # a clip at an edge leaves a line


def thinnest_layer(xs, columns: int = 400) -> float | None:
    """The thinnest layer in the window, in um: the shortest vertical run of a region (not the handle) that
    holds over two neighbouring columns. A sloped wall or a rounded corner changes from column to column and
    does not count."""

    solids = [g for g in xs.regions.values() if not g.is_empty]
    if not solids:
        return None
    s0, s1 = xs.window
    z_lo = min(g.bounds[1] for g in solids) - 1.0
    z_hi = max(g.bounds[3] for g in solids) + 1.0
    lines = [LineString([(s, z_lo), (s, z_hi)]) for s in
             (s0 + (k + 0.5) * (s1 - s0) / columns for k in range(columns))]
    best = None
    for name, geometry in xs.regions.items():
        if name == "handle" or geometry.is_empty:
            continue
        previous: list[float] = []
        for hit in shapely.intersection(geometry, lines):
            runs = [part.length for part in shapely.get_parts(hit) if part.length > 1e-6]
            for run in runs:
                if any(abs(run - other) <= 5e-3 * run for other in previous):
                    best = run if best is None else min(best, run)
            previous = runs
    return best


def _z_stretch(xs, z_scale: Any, scale: float) -> float:
    """``z_scale`` as a number; "auto" stretches z only as far as the thinnest layer needs."""

    if z_scale != "auto":
        return float(z_scale)
    thin = thinnest_layer(xs)
    if thin is None or thin * scale >= _MIN_PT * _MM_PER_PT:
        return 1.0
    return float(next((n for n in _Z_STEPS if thin * scale * n >= _MIN_PT * _MM_PER_PT), _Z_STEPS[-1]))


def _label_column(xs, font: float) -> float:
    """The width the label column needs: the longest label that may go there, 3 mm out from the plot, the
    text as schematic_labels.text_box measures it. The substrate labels inside its stub; an oxide goes to the
    column only when it has no room, and its short name fits the narrowest column."""

    longest = max((len(plain(str(text))) for name, text in xs.labels.items() if text and name != "handle"
                   and canonical(xs.materials.get(name, name)) != "sio2"), default=0)
    return max(_LABEL_COLUMN, 3.0 + longest * font * 0.6 + 0.5)


def _layout_frame(xs, width_mm: float, z_scale: Any, column: bool, font: float):
    """The frame, the z where a thick BOX is cut short (or None), the z stretch, the height of the z scale
    bar in um (or None) and the figure height in mm. ``column`` keeps room on the right for labels. A z window
    (``xs.z_window``) is the frame's band: the regions are cut to it, with no break and no cut-out, and only
    what lies in it sets the stretch."""

    s0, s1 = xs.window
    plot = width_mm - 2 * _MARGIN - (_label_column(xs, font) if column else 0.0)
    scale = plot / max(s1 - s0, 1e-9)
    if xs.z_window is not None:
        z0, z1 = xs.z_window
        band = box(s0, z0, s1, z1)
        inside = SimpleNamespace(window=xs.window, regions={name: MultiPolygon(_polygons(g.intersection(band)))
                                                            for name, g in xs.regions.items()})
        stretch = _z_stretch(inside, z_scale, scale)
        frame, cut_at = _Frame(s0, s1, z0, z1, scale, scale * stretch, _MARGIN, _MARGIN), None
    else:
        tops = [g.bounds[3] for name, g in xs.regions.items() if not g.is_empty and name not in ("handle", "box")]
        top = max(tops, default=1.0)
        box_region = xs.regions.get("box", MultiPolygon([]))
        box_depth = -box_region.bounds[1] if not box_region.is_empty else 0.0
        stretch = _z_stretch(xs, z_scale, scale)
        keep = max(_TOP_KEEP, _TOP_ROOM / (scale * stretch))     # room over the rib for its width and a label
        cut_out = _top_cut(xs, top, -min(box_depth, max(0.5, 0.25 * top)), keep)
        shown_top = cut_out[0] + top - cut_out[1] if cut_out else top
        shown = min(box_depth, max(0.5, 0.25 * shown_top))
        cut_at = -shown if box_depth > shown + 1e-9 else None
        handle = xs.regions.get("handle", MultiPolygon([]))
        if cut_at is None and not handle.is_empty and handle.bounds[1] < -box_depth - 1e-9:
            cut_at = -box_depth          # a BOX too thin to cut over a deep substrate: the substrate is the stub
        bottom = cut_at if cut_at is not None else min(g.bounds[1] for g in xs.regions.values() if not g.is_empty)
        frame = _Frame(s0, s1, bottom, top, scale, scale * stretch, _MARGIN, _MARGIN)
        if cut_out:
            frame.keep, frame.resume, frame.gap = cut_out[0], cut_out[1], _TOP_GAP
    z_bar = None
    if abs(stretch - 1.0) > 1e-9:
        z_bar = _nice(5.0 / frame.zscale)                     # at most 5 mm tall
    band = max(6.0, (z_bar * frame.zscale if z_bar else 0.0) + 3.5)   # the scale bars, clear of the figure
    stub = _stub(font) + 1.0 if cut_at is not None else 0.0
    height = 2 * _MARGIN + frame.plot_height() + stub + band
    return frame, cut_at, stretch, z_bar, height


def _top_cut(xs, top: float, bottom: float, keep: float) -> tuple[float, float] | None:
    """Where to cut a thick top oxide out: from ``keep`` um over the highest feature (a metal, else the
    device) to just under the lowest point of the top surface. None when the oxide over that feature is
    under 0.6 um, takes under 40 % of the height, or the cut would save less than 0.3 um."""

    features = [g.bounds[3] for name, g in xs.regions.items()
                if not g.is_empty and name not in ("handle", "box", "passivation")
                and canonical(xs.materials.get(name, name)) != "sio2"]
    if not features:
        return None
    highest = max(features)
    above = top - highest
    if above <= _TOP_MIN_OXIDE or above <= _TOP_SHARE * (top - bottom):
        return None
    keep, resume = highest + keep, _surface_low(xs) - _TOP_UNDER
    return (keep, resume) if resume - keep >= 0.3 else None


def _surface_low(xs, columns: int = 200) -> float:
    """The lowest point of the top surface across the window."""

    solid = unary_union([g for g in xs.regions.values() if not g.is_empty])
    s0, s1 = xs.window
    z_lo, z_hi = solid.bounds[1] - 1.0, solid.bounds[3] + 1.0
    lines = [LineString([(s, z_lo), (s, z_hi)]) for s in (s0 + (k + 0.5) * (s1 - s0) / columns for k in range(columns))]
    return min(hit.bounds[3] for hit in shapely.intersection(solid, lines) if not hit.is_empty)


def _stub(font: float) -> float:
    """The height of the substrate stub under a break: room for its label inside."""

    return max(_STUB, 1.6 * font)


def render_schematic(xs, *, preset: str | None = "single_column", width_mm: float | None = None,
                     z_scale: Any = "auto", labels: bool = True, dims: Any = "auto", scale_bar: bool = True,
                     colors: dict[str, str] | None = None, font_family: str = "Helvetica, Arial, sans-serif",
                     font_pt: float | None = None, frames: list | None = None) -> str:
    """The cross-section ``xs`` as an SVG figure ``width_mm`` wide (or the preset's width). A list given as
    ``frames`` gets the frame the figure is drawn in, for :func:`section_place`.

    ``z_scale="auto"`` stretches z only when the thinnest layer would be under 2 pt tall; ``z_scale=1`` is
    true aspect; any other number stretches z by that much. ``dims`` is "auto", None, or a list of "rib
    width", "rib height", "slab height", "metal gap". ``colors`` maps a region to a fill and overrides the
    material palette."""

    from optodraw.publication import paper_figure_preset

    values = paper_figure_preset(preset) if preset else {}
    width = float(width_mm if width_mm is not None else values.get("width", 89.0))
    font = float(font_pt if font_pt is not None else values.get("font_size_pt", 8.0)) * _MM_PER_PT
    parts, height = _figure(xs, width, font, z_scale=z_scale, labels=labels, dims=dims, scale_bar=scale_bar,
                            colors=colors, family=font_family, beams=xs.beams, frames=frames)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:g}mm" height="{height:.2f}mm" '
            f'viewBox="0 0 {width:g} {height:.2f}"><rect width="100%" height="100%" fill="#ffffff"/>'
            + "".join(parts) + "</svg>")


def section_place(xs, *, width_mm: float, font_pt: float,
                  **options: Any) -> Callable[[float, float], tuple[float, float]]:
    """``place(s, z)``: where the cut position ``s`` and the height ``z`` (both in um) fall in the figure ``xs.svg``
    draws at this width and text size, in mm from its top left, y down. It reads the frame of the drawing itself, so
    the two agree for the same ``options``."""

    frame, room = section_frame(xs, width_mm=width_mm, font_pt=font_pt, **options)
    return lambda s, z: (frame.x(s), frame.y(z) + room)


def section_frame(xs, *, width_mm: float, font_pt: float, **options: Any) -> tuple[_Frame, float]:
    """The frame ``xs.svg`` draws in at this width and text size, and the mm the beam band moves it down."""

    frames: list = []
    render_schematic(xs, width_mm=width_mm, font_pt=font_pt, frames=frames, **options)
    return frames[0]


def _beam_marks(beams, frame: _Frame, font: float, family: str, room: float) -> list[str]:
    """Each beam as a cone from the band above the figure (y = -``room``) to its end."""

    from optodraw.core.beam import wavelength_to_hex

    half = _BEAM_TOP * (frame.x(frame.s1) - frame.x(frame.s0))
    out = []
    for beam in beams:
        x, y, color = frame.x(beam.s), frame.y(beam.z), wavelength_to_hex(beam.wavelength)
        out.append(f'<path data-beam="{beam.wavelength:g}" fill="{color}" fill-opacity="0.5" stroke="none" '
                   f'd="M{x - half:.3f} {-room:.3f}L{x + half:.3f} {-room:.3f}L{x:.3f} {y:.3f}Z"/>')
        if beam.label:
            out.append(f'<text x="{x + half + 1.0:.3f}" y="{font - room:.3f}" font-size="{font:.3f}" '
                       f'font-family="{family}" fill="{color}">{escape(beam.label)}</text>')
    return out


def _figure(xs, width: float, font: float, *, z_scale: Any, labels: bool, dims: Any, scale_bar: bool,
            colors: dict[str, str] | None, family: str, shape=None, beams=(),
            frames: list | None = None) -> tuple[list[str], float]:
    """The SVG elements of the figure, in mm, and its height. ``shape`` (default ``xs``) is the
    cross-section whose extent sets the frame, so the panels of a strip share one frame. A list given as ``frames``
    gets the frame the figure is drawn in and the mm the beam band moves it down."""

    from optodraw.gds.xsection.schematic_dims import dimension_lines
    from optodraw.gds.xsection.schematic_labels import place_labels

    for column in (False, True):                 # the label column only when a label needs it
        frame, cut_at, stretch, z_bar, height = _layout_frame(shape or xs, width, z_scale, column, font)
        clip = frame.clip()
        notes, taken = dimension_lines(xs, frame, clip, dims, font, family) if dims else ([], [])
        if not labels:
            break
        placed = place_labels(xs, frame, clip, font, family, width, obstacles=taken, column=column)
        if placed is not None:
            notes += placed
            break
    fills = {name: (colors or {}).get(name) or xs.fills.get(name) or material_fill(xs.materials.get(name, name))
             for name in xs.regions}
    out: list[str] = []
    room = max(_BEAM_ROOM, 2.0 * font) if beams else 0.0
    if frames is not None:
        frames.append((frame, room))
    for name, geometry in xs.regions.items():
        for polygon in _polygons(geometry.intersection(clip)):
            out.append(f'<path class="region" data-region="{name}" fill="{fills[name]}" stroke="{_INK}" '
                       f'stroke-width="{_OUTLINE:.3f}" stroke-linejoin="round" fill-rule="evenodd" '
                       f'd="{_path(polygon, frame)}"/>')
    for species, geometry in xs.doping.items():
        tint = DOPING.get(species.upper(), "#888888")
        for polygon in _polygons(geometry.intersection(clip)):
            out.append(f'<path class="doping" data-species="{species}" fill="{tint}" fill-opacity="0.45" '
                       f'stroke="none" d="{_path(polygon, frame)}"/>')
    if cut_at is not None:
        out += _break(frame, fills.get("handle", material_fill("silicon")), font, family,
                      xs.labels.get("handle") if labels else None)
    if frame.keep is not None and any(g.bounds[3] > frame.keep + 1e-9 for g in xs.regions.values() if not g.is_empty):
        out.append(_zigzag(frame, frame.y(frame.keep), -0.6))
    if scale_bar:
        out += _scale_bar(frame, stretch, z_bar, font, family, height)
    if not beams:
        return out + notes, height
    return ([f'<g transform="translate(0 {room:.3f})">', *out, *_beam_marks(beams, frame, font, family, room), *notes,
             "</g>"], height + room)


def render_steps(xs, *, columns: int = 4, preset: str | None = "double_column", width_mm: float | None = None,
                 z_scale: Any = "auto", font_family: str = "Helvetica, Arial, sans-serif",
                 font_pt: float | None = None, colors: dict[str, str] | None = None) -> str:
    """The process strip: one small panel per step, in order, each with its caption. Every panel has the same
    scale; the first carries the scale bar."""

    from optodraw.publication import paper_figure_preset

    values = paper_figure_preset(preset) if preset else {}
    width = float(width_mm if width_mm is not None else values.get("width", 183.0))
    font = float(font_pt if font_pt is not None else values.get("font_size_pt", 8.0)) * _MM_PER_PT
    gap = 3.0
    panel = (width - gap * (columns - 1)) / columns
    if z_scale == "auto":                        # one stretch for the strip, from the finished cross-section
        z_scale = _z_stretch(xs, "auto", (panel - 2 * _MARGIN) / max(xs.window[1] - xs.window[0], 1e-9))
    since = {}                                   # an implant shows from its own step on
    for species in xs.doping:
        found = [i for i, (_, caption, _) in enumerate(xs.steps)
                 if caption.startswith(f"{doping_label(species)} implant")]
        since[species] = found[0] if found else len(xs.steps) - 1
    panels = []
    for index, (_, caption, regions) in enumerate(xs.steps):
        device = regions.get("device", MultiPolygon([]))
        doping = {species: geometry.intersection(device) for species, geometry in xs.doping.items()
                  if index >= since[species]}
        step = SimpleNamespace(regions=regions, materials=xs.materials, labels=xs.labels, doping=doping,
                               window=xs.window, fills=xs.fills)
        parts, height = _figure(step, panel, font, z_scale=z_scale, labels=False, dims=None,
                                scale_bar=index == 0, colors=colors, family=font_family, shape=xs)
        panels.append((parts, height, _wrap(f"{index + 1}. {caption}", (panel - _MARGIN) / (0.55 * font))))
    row_height = max(height for _, height, _ in panels)
    cell = row_height + font * (1.2 * max(len(lines) for _, _, lines in panels) + 1.0)
    rows = (len(panels) + columns - 1) // columns
    out = []
    for index, (parts, height, lines) in enumerate(panels):
        x, y = (index % columns) * (panel + gap), (index // columns) * cell
        out.append(f'<svg class="step" x="{x:.3f}" y="{y:.3f}" width="{panel:.3f}" height="{height:.3f}" '
                   f'viewBox="0 0 {panel:.3f} {height:.3f}">' + "".join(parts) + "</svg>")
        spans = "".join(f'<tspan x="{x + _MARGIN:.3f}" y="{y + height + font * 1.2 * (k + 1):.3f}">'
                        f'{svg_spans(line, font)}</tspan>' for k, line in enumerate(lines))
        out.append(f'<text class="caption" font-size="{font:.3f}" font-family="{font_family}">{spans}</text>')
    total = rows * cell
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:g}mm" height="{total:.2f}mm" '
            f'viewBox="0 0 {width:g} {total:.2f}"><rect width="100%" height="100%" fill="#ffffff"/>'
            + "".join(out) + "</svg>")


def _wrap(text: str, chars: float) -> list[str]:
    """``text`` in lines of at most ``chars`` characters, broken between words."""

    lines: list[str] = []
    for word in text.split():
        if lines and len(lines[-1]) + 1 + len(word) <= chars:
            lines[-1] += " " + word
        else:
            lines.append(word)
    return lines or [""]


def _zigzag(frame: _Frame, y: float, depth: float) -> str:
    """A break mark across the window at ``y``: teeth ``depth`` mm deep (up the page when negative)."""

    x0, x1 = frame.x(frame.s0), frame.x(frame.s1)
    count = max(2, int((x1 - x0) / 1.2))
    zig = " L".join(f"{x0 + (x1 - x0) * k / count:.3f},{y + (depth if k % 2 else 0.0):.3f}" for k in range(count + 1))
    return f'<path class="break" d="M{zig}" fill="none" stroke="{_INK}" stroke-width="{_OUTLINE:.3f}"/>'


def _break(frame: _Frame, handle_fill: str, font: float, family: str, label: str | None) -> list[str]:
    """A zigzag where the BOX is cut short, and a stub of substrate under it with the substrate's ``label``."""

    x0, x1 = frame.x(frame.s0), frame.x(frame.s1)
    y = frame.y(frame.z0)
    stub_top, stub = y + 1.0, _stub(font)
    out = [_zigzag(frame, y, 0.6),
           f'<rect class="region" data-region="handle-stub" x="{x0:.3f}" y="{stub_top:.3f}" width="{x1 - x0:.3f}" '
           f'height="{stub:.3f}" fill="{handle_fill}" stroke="{_INK}" stroke-width="{_OUTLINE:.3f}"/>']
    if label:
        out.append(_label_text((x0 + x1) / 2, stub_top + stub / 2 + font / 3, label, font, family))
    return out


def _scale_bar(frame: _Frame, stretch: float, z_bar: float | None, font: float, family: str,
               height: float) -> list[str]:
    """A bar along ``s`` at the bottom left with its length on its right. When z is stretched, a bar along
    ``z`` rises from the left end with its length on its left, and the stretch is printed after it all."""

    length = _nice((frame.s1 - frame.s0) / 4.0)
    y = height - 2.0
    z_text = _size(z_bar) if z_bar is not None else ""
    corner = frame.x(frame.s0) + (len(z_text) * font * 0.6 + 1.0 if z_bar is not None else 0.0)
    bar = length * frame.scale
    out = [f'<g class="scale-bar"><path d="M{corner:.3f},{y:.3f} h{bar:.3f}" stroke="#000000" stroke-width="0.35"/>'
           f'<text x="{corner + bar + 1.0:.3f}" y="{y + font / 3:.3f}" font-size="{font:.3f}" '
           f'font-family="{family}">{_size(length)}</text></g>']
    if z_bar is not None:
        tall = z_bar * frame.zscale
        middle = min(y - tall / 2 + font / 3, y - 0.3 - 0.2 * font)    # its value stays above the s bar
        after = corner + bar + 1.0 + (len(_size(length)) + 2) * font * 0.6
        out.append(f'<g class="z-scale-bar"><path d="M{corner:.3f},{y:.3f} v{-tall:.3f}" stroke="#000000" '
                   f'stroke-width="0.35"/><text x="{corner - 1.0:.3f}" y="{middle:.3f}" font-size="{font:.3f}" '
                   f'font-family="{family}" text-anchor="end">{z_text}</text></g>')
        out.append(f'<text class="z-stretch" x="{after:.3f}" y="{y + font / 3:.3f}" font-size="{font:.3f}" '
                   f'font-family="{family}">z × {stretch:g}</text>')
    return out
