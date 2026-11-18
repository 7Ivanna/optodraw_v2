"""The 1D schematic as TikZ: the symbol library, one pic per part, links between named ports."""

from __future__ import annotations

import re
from typing import Any

from . import PT_PER_CM
from .build import keys
from .router import CORNER
from .schematic import JUNCTION, build_schematic, hub_paths, junctions, link_curve
from .svg_tikz import _color

_ESCAPES = {"\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#", "_": r"\_",
            "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}", "^": r"\textasciicircum{}"}


def _tex(text: str) -> str:
    return "".join(_ESCAPES.get(character, character) for character in text)


def _cm(x: float, y: float) -> str:
    return f"({x / PT_PER_CM:.3f},{-y / PT_PER_CM:.3f})"


def _offset(start: tuple[float, float], end: tuple[float, float]) -> str:
    return f"+({(end[0] - start[0]) / PT_PER_CM:.3f},{-(end[1] - start[1]) / PT_PER_CM:.3f})"


def library_source() -> str:
    """The TikZ library as one block that typesets nothing where it sits (shared with the 2D art)."""

    from .art import library_tex

    return library_tex()


def render_tikz_1d(scene: Any, positions: dict[str, Any] | None = None, *, include_library: bool = True) -> str:
    """Write the scene's 1D schematic as a ``tikzpicture``. The document needs ``\\usepackage{tikz}``.

    ``include_library=False`` leaves the library out, for a second figure in the same document.
    """

    schematic = build_schematic(scene, positions)
    lines = ["% optodraw 1D schematic. Needs \\usepackage{tikz}."]
    if include_library:
        lines += ["% --- optodraw symbol library (keep one copy per document) ---", library_source().rstrip(),
                  "% --- end of the library ---"]
    lines.append("\\begin{tikzpicture}")
    for a, b in hub_paths(schematic):                       # the beams inside a splitter, under its glass
        lines.append(f"\\draw[od wg] {_cm(*a)} -- {_cm(*b)};")
    for mark in schematic.marks:                            # a region's box, a bracket, a stage's motion mark
        colour = _color(mark.color) or "black"
        dash = ", dashed" if mark.dashed else ""
        for line in mark.lines:
            lines.append(f"\\draw[draw={colour}, line width=0.5pt{dash}] " + " -- ".join(_cm(*p) for p in line) + ";")
        for head in mark.heads:
            lines.append(f"\\fill[fill={colour}] " + " -- ".join(_cm(*p) for p in head) + " -- cycle;")
        if mark.label:
            x, baseline, anchor = mark.label_at
            corner = {"middle": "base", "start": "base west", "end": "base east"}[anchor]
            lines.append(f"\\node[font=\\scriptsize, text={colour}, anchor={corner}] at {_cm(x, baseline)} "
                         f"{{{_tex(mark.label)}}};")
    for position, item in enumerate(schematic.items):
        symbol, name = item.symbol, f"n{position}"
        if symbol.source == "block":                 # no pic for this part yet: a labeled box
            m = 9.0
            lines.append(f"\\draw[od wg, fill=white] {_cm(item.x + m, item.y + m)} rectangle "
                         f"{_cm(item.x + symbol.width - m, item.y + symbol.height - m)};")
            lines.append(f"\\node[font=\\scriptsize] at {_cm(item.x + symbol.width / 2, item.y + symbol.height / 2)} "
                         f"{{{_tex(symbol.params['label'])}}};")
            for port in symbol.ports.values():
                inner = {"left": (m, port.y), "right": (symbol.width - m, port.y),
                         "top": (port.x, m), "bottom": (port.x, symbol.height - m)}[port.side]
                lines.append(f"\\draw[od wg] {_cm(item.x + port.x, item.y + port.y)} coordinate ({name}-{port.name}) "
                             f"-- {_cm(item.x + inner[0], item.y + inner[1])};")
        elif symbol.source == "user":                 # a part made from SVG art: its art as TikZ paths
            from .svg_tikz import svg_to_tikz

            lines += svg_to_tikz(symbol.svg, lambda x, y, item=item: _cm(item.x + x, item.y + y))
            for port in symbol.ports.values():
                lines.append(f"\\coordinate ({name}-{port.name}) at {_cm(item.x + port.x, item.y + port.y)};")
        else:
            origin = _cm(item.x + symbol.origin[0], item.y + symbol.origin[1])
            turn = [f"rotate={symbol.rotation:g}"] if symbol.rotation else []
            mirror = "[" + ", ".join(turn + (["xscale=-1"] if symbol.flipped else [])) + "] " if turn or symbol.flipped else ""
            lines.append(f"\\pic {mirror}({name}) at {origin} {{od {symbol.name}={{{keys(symbol.params)}}}}};")
        if item.label:
            x, baseline, anchor = item.label_at
            corner = {"middle": "base", "start": "base west", "end": "base east"}[anchor]
            lines.append(f"\\node[font=\\scriptsize, anchor={corner}] at {_cm(x, baseline)} {{{_tex(item.label)}}};")
    for number, link in enumerate(schematic.links):
        a, c1, c2, b = link_curve(schematic, link)
        ends = []
        for index, port_name, point in ((link.start, link.start_port, a), (link.end, link.end_port, b)):
            known = port_name in schematic.items[index].symbol.ports and re.fullmatch(r"[A-Za-z0-9_]+", port_name)
            ends.append(f"(n{index}-{port_name})" if known else _cm(*point))
        style = "od cable" if link.electrical else "od wg"
        route = schematic.routes.get(number)
        if route:                             # a square route: a waveguide bends, a wire turns sharp as in a circuit
            middle = "".join(f" -- {_cm(*point)}" for point in route[1:-1])
            bend = "" if link.electrical else f", rounded corners={CORNER:g}pt"
            lines.append(f"\\draw[{style}{bend}] {ends[0]}{middle} -- {ends[1]};")
        else:
            lines.append(f"\\draw[{style}] {ends[0]} .. controls {_offset(a, c1)} and {_offset(b, c2)} .. {ends[1]};")
    for x, y in junctions(schematic):                 # a dot where wires of one node join, in the cable's grey
        lines.append(f"\\fill[black!65] {_cm(x, y)} circle ({JUNCTION:g}pt);")
    lines.append("\\end{tikzpicture}")
    return "\n".join(lines) + "\n"
