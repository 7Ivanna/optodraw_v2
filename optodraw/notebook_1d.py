"""The 1D schematic of a scene as one SVG: the notebook tab and the SVG export."""

from __future__ import annotations

from html import escape
from typing import Any

from optodraw.core.markup import has_markup, svg_text
from optodraw.symbols.router import CORNER, rounded_path
from optodraw.symbols.schematic import (JUNCTION, LABEL_SIZE, Schematic, build_schematic, hub_paths, junctions,
                                        link_curve)

DISPLAY_ZOOM = 1.5               # screen pixels per SVG point in a notebook
_FONT = 'font-family="Helvetica,Arial,sans-serif"'


def schematic_body(schematic: Schematic, label_size: float = LABEL_SIZE) -> str:
    """The drawing without its <svg> wrapper: a white page, the links, the symbols, the labels at ``label_size``."""

    width, height = schematic.width, schematic.height
    parts = [f'<rect width="{width:.2f}" height="{height:.2f}" fill="white"/>']
    if not schematic.items:
        parts.append(
            f'<text x="{width / 2:.2f}" y="{height / 2:.2f}" text-anchor="middle" fill="#555" {_FONT} '
            'font-size="8">No components</text>'
        )
    if schematic.unresolved:
        parts.append(
            f'<text x="4" y="8" fill="#8a2d22" {_FONT} font-size="6">'
            f'{schematic.unresolved} unresolved connection(s)</text>'
        )
    for index, link in enumerate(schematic.links):
        style = 'stroke="#595959" stroke-width="0.55"' if link.electrical else 'stroke="#000" stroke-width="0.9"'
        if index in schematic.routes:          # a square route: a waveguide bends, a wire turns sharp as in a circuit
            d = rounded_path(schematic.routes[index], 0.0 if link.electrical else CORNER)
        else:
            a, c1, c2, b = link_curve(schematic, link)
            d = f"M{a[0]:.2f} {a[1]:.2f}C{c1[0]:.2f} {c1[1]:.2f} {c2[0]:.2f} {c2[1]:.2f} {b[0]:.2f} {b[1]:.2f}"
        parts.append(f'<path d="{d}" fill="none" stroke-linecap="round" stroke-linejoin="round" {style}/>')
    for x, y in junctions(schematic):                          # a dot where wires of one node join; a crossing has none
        parts.append(f'<circle class="od1-junction" cx="{x:.2f}" cy="{y:.2f}" r="{JUNCTION:g}" fill="#595959"/>')
    for (ax, ay), (bx, by) in hub_paths(schematic):            # the beams inside a splitter, under its glass
        parts.append(f'<path d="M{ax:.2f} {ay:.2f}L{bx:.2f} {by:.2f}" fill="none" stroke="#000" '
                     'stroke-linecap="round" stroke-width="0.9"/>')
    size = LABEL_SIZE if label_size == LABEL_SIZE else format(label_size, ".4g")     # the default prints as it did

    def text(label: str, at: tuple[float, float, str], fill: str) -> str:
        x, baseline, anchor = at
        if has_markup(label):
            return svg_text(label, label_size, x, f"{baseline:.2f}", anchor, f'fill="{fill}" {_FONT}')
        return (f'<text x="{x:.2f}" y="{baseline:.2f}" text-anchor="{anchor}" fill="{fill}" {_FONT} '
                f'font-size="{size}">{escape(label)}</text>')

    for mark in schematic.marks:                               # a region's box, a bracket, a stage's motion mark
        dash = ' stroke-dasharray="2.4 2"' if mark.dashed else ""
        for line in mark.lines:
            d = "M" + "L".join(f"{x:.2f} {y:.2f}" for x, y in line)
            parts.append(f'<path class="od1-mark" d="{d}" fill="none" stroke="{mark.color}" stroke-width="0.5" '
                         f'stroke-linecap="round" stroke-linejoin="round"{dash}/>')
        for head in mark.heads:
            d = "M" + "L".join(f"{x:.2f} {y:.2f}" for x, y in head) + "Z"
            parts.append(f'<path class="od1-mark" d="{d}" fill="{mark.color}" stroke="none"/>')
        if mark.label:
            parts.append(text(mark.label, mark.label_at, mark.color))
    for item in schematic.items:
        symbol = item.symbol
        parts.append(f'<g transform="translate({item.x:.2f} {item.y:.2f})">{symbol.inner()}</g>')
        if item.label:
            parts.append(text(item.label, item.label_at, "#000"))
    return "".join(parts)


def render_notebook_1d(scene: Any, positions: dict[str, Any] | None = None, *, width_mm: float | None = None,
                       font_pt: float | None = None) -> str:
    """Render a 1D schematic without changing the source scene.

    ``positions`` maps a component id to ``[x, y]`` in SVG points. Without it the
    saved layout in ``scene.metadata["one_d_layout"]`` is used, and a part with
    no saved position gets a compact automatic one. With ``scene.set_view_layout``,
    free-space symbols instead follow source positions and component footprints.

    With ``width_mm`` and ``font_pt`` the labels print at ``font_pt`` when the drawing is ``width_mm`` wide.
    """

    schematic = build_schematic(scene, positions)
    width, height = schematic.width, schematic.height
    label = LABEL_SIZE if width_mm is None or font_pt is None else font_pt * 0.3528 * width / width_mm
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width:.2f} {height:.2f}" '
        f'width="{width * DISPLAY_ZOOM:.0f}" height="{height * DISPLAY_ZOOM:.0f}" role="img" '
        f'aria-label="1D schematic">{schematic_body(schematic, label)}</svg>'
    )
