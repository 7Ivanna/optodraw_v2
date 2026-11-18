"""2D art: a part painted with its symbol, fitted to the part's physical ports.

A part keeps ``geometry_2d()``: the ray tracer reads its optical surfaces and
the layout reads its bounds. The renderers paint the art instead of the
geometry when :func:`art_2d` gives one. The art is the same TikZ drawing as
the 1D symbol (or a top-view variant that the part asks for with
``symbol_2d()``), so the two views cannot drift apart.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, replace
from functools import lru_cache
from typing import Any

from optodraw.core.component import ANNOTATION_TYPES

from . import Symbol, lookup
from .build import BORDER_PT, PT_TO_BP, keys, library_files

MAX_RESIDUAL = 0.15              # art port to physical port, as a share of the port span
PORT_TOLERANCE = 0.5             # scene units: a wire or light ends this close to the drawn port, or in the air
LINE_SCALE = 0.5                 # scene units per point, at most, for a line: a large part gets no heavy lines
# The families painted with art, by catalog category. Widened stage by stage
# (docs/superpowers/specs/2026-10-02-2d-art-from-symbols-design.md).
ART_CATEGORIES = {"optics", "instruments", "devices", "samples", "misc", "electronics"}
# The plates a bench stands on keep their own drawing: a grid of holes under everything else.
# The grid is a guide, not a part. A periscope, a telescope and a 4f relay draw their parts at
# their true spacing: a symbol has one length. Physical layout (pads, the heater, metal routes,
# a circuit board) keeps its true geometry: its size is the design.
NO_ART = {"OpticalTable", "Breadboard", "Baseplate", "Grid", "Periscope", "Telescope", "FourFSystem",
          "ElectricalPad", "GSGProbePad", "HeaterPad", "MetalRoute", "PCB",
          "SignalArrow"} | ANNOTATION_TYPES    # an annotation: its ends and colour are its drawing
# On-chip circuit blocks: drawn as blocks, not layout, so they take the art of their electronic twins.
ART_PARTS = {"TIA", "ADC", "DACDriver"}


@lru_cache(maxsize=1)
def _painted() -> frozenset[str]:
    from optodraw.registry import component_registry

    return frozenset(name for name, spec in component_registry().items()
                     if spec.category in ART_CATEGORIES and name not in NO_ART) | ART_PARTS
_FACING = {"right": 0.0, "top": 90.0, "left": 180.0, "bottom": 270.0}


@dataclass(frozen=True)
class Art:
    symbol: Symbol
    scale: float                         # scene units per symbol point
    turn: float                          # degrees counterclockwise, after the mirror
    mirror: bool                         # reflected left to right first
    shift: tuple[float, float]           # where the symbol corner (0, 0) lands: local units, y up
    residual: float

    def local(self, x: float, y: float) -> tuple[float, float]:
        """A symbol point (SVG points, y down) in the part's local frame (y up)."""

        qx, qy = self._turned(x, y)
        return self.scale * qx + self.shift[0], self.scale * qy + self.shift[1]

    def _turned(self, x: float, y: float) -> tuple[float, float]:
        c, s = math.cos(math.radians(self.turn)), math.sin(math.radians(self.turn))
        qx, qy = (-x if self.mirror else x), -y
        return c * qx - s * qy, s * qx + c * qy

    def matrix(self) -> tuple[float, float, float, float, float, float]:
        """The SVG matrix from symbol points to the part's SVG frame (x right, y down)."""

        (ox, oy), (ux, uy), (vx, vy) = self.local(0.0, 0.0), self.local(1.0, 0.0), self.local(0.0, 1.0)
        return ux - ox, -(uy - oy), vx - ox, -(vy - oy), ox, -oy


def symbol_for_2d(component: Any) -> Symbol:
    """The drawing of a part in 2D: its ``symbol_2d()`` variant when it has one, else its 1D symbol."""

    method = getattr(component, "symbol_2d", None)
    request = method() if callable(method) else None
    return lookup(component, request)


def _turned_points(points: list[tuple[float, float]], turn: float, mirror: bool) -> list[tuple[float, float]]:
    probe = Art(symbol=None, scale=1.0, turn=turn, mirror=mirror, shift=(0.0, 0.0), residual=0.0)  # type: ignore[arg-type]
    return [probe._turned(x, y) for x, y in points]


def _geometry_bounds(component: Any) -> tuple[float, float, float, float]:
    """The bounds of the part's own geometry, without its art (the fit must not depend on itself)."""

    from optodraw.layout import _bounds_from_geometry

    try:
        bounds = _bounds_from_geometry(component.geometry_2d())
    except (AttributeError, TypeError, ValueError):
        bounds = None
    return bounds or (-5.0, -5.0, 5.0, 5.0)


def _symbol_box(matrix: tuple[float, ...], size: tuple[float, float]) -> tuple[float, float, float, float]:
    """The local box (y up) of a symbol drawn with an SVG ``matrix``."""

    a, b, c, d, e, f = matrix
    width, height = size
    corners = [(a * x + c * y + e, -(b * x + d * y + f)) for x, y in ((0, 0), (width, 0), (0, height), (width, height))]
    return (min(x for x, _ in corners), min(y for _, y in corners), max(x for x, _ in corners), max(y for _, y in corners))


def _dashed_outline(box: tuple[float, float, float, float], along: float) -> dict[str, Any]:
    """The box as a dashed outline, ``along`` up the part's local y: where a part that moves is not."""

    x0, y0, x1, y1 = box
    y0, y1 = y0 + along, y1 + along
    dash = 0.06 * (y1 - y0)
    return {"type": "polyline", "points": [(x0, y0), (x1, y0), (x1, y1), (x0, y1)], "closed": True, "fill": "none",
            "stroke": "#5d6570", "stroke_width": 0.2, "stroke_dasharray": f"{dash:.3g} {dash:.3g}"}


def art_bounds(component: Any) -> tuple[float, float, float, float] | None:
    """The local box (y up) that the art of a part covers, or None when the part has no art."""

    art = art_2d(component)
    if art is None:
        return None
    box = _symbol_box(art["matrix"], art["size"])
    outline = art.get("outline")
    if outline is None:
        return box
    xs, ys = zip(*outline["points"])
    return union(box, (min(xs), min(ys), max(xs), max(ys)))


def union(first: tuple[float, float, float, float] | None,
          second: tuple[float, float, float, float] | None) -> tuple[float, float, float, float] | None:
    if first is None or second is None:
        return first or second
    return min(first[0], second[0]), min(first[1], second[1]), max(first[2], second[2]), max(first[3], second[3])


def _extent(points: list[tuple[float, float]], horizontal: bool) -> float:
    """The size across the beam: the height of the points for a beam along x, else their width."""

    values = [y for _, y in points] if horizontal else [x for x, _ in points]
    return max(values) - min(values)


def _drawn_corners(symbol: Symbol) -> list[tuple[float, float]]:
    """The corners of what the symbol draws: its SVG frame less the blank border round the picture."""

    b = BORDER_PT * PT_TO_BP
    return [(b, b), (symbol.width - b, b), (b, symbol.height - b), (symbol.width - b, symbol.height - b)]


def fit_art(component: Any, symbol: Symbol | None = None) -> Art | None:
    """The scale, turn, mirror and shift that put the symbol on the part.

    The turn and the mirror come from the ports: the symbol's ports must lie
    the way the part's ports lie (``residual`` measures that). The size comes
    from the ports too, unless the part carries light and that size is far
    from the part's real size across the beam, measured on what the symbol
    draws (not its blank border): a thin plate whose 1D symbol carries its
    output at the end of a short beam would come out too small. Then the size
    is the real size, and the first port sits on its port. A part with only
    wires always takes the size of its ports: a wire has no stub to run over.
    """

    symbol = symbol or symbol_for_2d(component)
    if symbol.source == "block":
        return None
    x0, y0, x1, y1 = _geometry_bounds(component)
    ports = component.ports() if callable(getattr(component, "ports", None)) else {}
    size = max(x1 - x0, y1 - y0, 1e-9)
    # A port at the middle of the part is a reference point (a mount, a Fourier plane), not where a beam ends.
    common = [name for name in ports if name in symbol.ports
              and math.hypot(float(ports[name].center.x), float(ports[name].center.y)) > 0.01 * size]
    physical = [(float(ports[name].center.x), float(ports[name].center.y)) for name in common]
    drawn = [(symbol.ports[name].x, symbol.ports[name].y) for name in common]
    corners = [(0.0, 0.0), (symbol.width, 0.0), (0.0, symbol.height), (symbol.width, symbol.height)]
    span = max((math.dist(a, b) for a in physical for b in physical), default=0.0)
    if len(common) >= 2 and span > 1e-9:
        best = None
        for turn in range(0, 360, 45):
            for mirror in (False, True):
                turned = _turned_points(drawn, turn, mirror)
                ax = sum(x for x, _ in turned) / len(turned)
                ay = sum(y for _, y in turned) / len(turned)
                px = sum(x for x, _ in physical) / len(physical)
                py = sum(y for _, y in physical) / len(physical)
                spread = sum((x - ax) ** 2 + (y - ay) ** 2 for x, y in turned)
                if spread < 1e-12:
                    continue
                scale = sum((x - ax) * (u - px) + (y - ay) * (v - py) for (x, y), (u, v) in zip(turned, physical)) / spread
                if scale <= 0:
                    continue
                shift = (px - scale * ax, py - scale * ay)
                miss = max(math.dist((scale * x + shift[0], scale * y + shift[1]), point)
                           for (x, y), point in zip(turned, physical)) / span
                key = (round(miss, 4), turn != 0, mirror)
                if best is None or key < best[0]:
                    best = (key, Art(symbol, scale, float(turn), mirror, shift, miss))
        if best is None:
            return None
        art = best[1]
        horizontal = abs(physical[-1][0] - physical[0][0]) >= abs(physical[-1][1] - physical[0][1])
        across = _extent(_turned_points(_drawn_corners(symbol), art.turn, art.mirror), horizontal)
        real = (y1 - y0) if horizontal else (x1 - x0)
        sized = real / max(across, 1e-9)
        if (not 1 / 1.5 <= art.scale / sized <= 1.5
                and any(ports[name].kind != "electrical" for name in common)
                and not getattr(component, "_art_scale_from_ports", False)):
            if symbol.hub is not None:                          # a splitter: where its beams meet sits on their crossing
                (qx, qy), = _turned_points([symbol.hub], art.turn, art.mirror)
                anchor = (0.0, 0.0)                             # a splitter's beams cross at its own origin
            elif getattr(component, "_art_anchor_at_origin", False):
                (qx, qy), = _turned_points([symbol.origin], art.turn, art.mirror)
                anchor = (0.0, 0.0)
            else:                                               # else the first port on its port
                (qx, qy), = _turned_points([drawn[0]], art.turn, art.mirror)
                anchor = physical[0]
            art = Art(symbol, sized, art.turn, art.mirror, (anchor[0] - sized * qx, anchor[1] - sized * qy), art.residual)
        return art
    if len(common) == 1:                                       # one port: face it the way the part does, fill its height
        name = common[0]
        turn = round((float(getattr(ports[name], "orientation_deg", 180.0)) - _FACING[symbol.ports[name].side]) / 45.0) * 45.0 % 360.0
        horizontal = abs(math.cos(math.radians(turn + _FACING[symbol.ports[name].side]))) > 0.5
        scale = ((y1 - y0) if horizontal else (x1 - x0)) / max(_extent(_turned_points(corners, turn, False), horizontal), 1e-9)
        unit = getattr(component, "_art_unit", None)            # a drawing to a plan: the size of one cm of the pic
        if unit is not None:
            scale = unit * 2.54 / 72.0
        (qx, qy), = _turned_points([drawn[0]], turn, False)
        return Art(symbol, scale, turn, False, (physical[0][0] - scale * qx, physical[0][1] - scale * qy), 0.0)
    turned = _turned_points(corners, 0.0, False)                # no beam port: fill the bounds
    width = max(x for x, _ in turned) - min(x for x, _ in turned)
    height = max(y for _, y in turned) - min(y for _, y in turned)
    scale = min((x1 - x0) / max(width, 1e-9), (y1 - y0) / max(height, 1e-9))
    left, top = min(x for x, _ in turned), max(y for _, y in turned)
    shift = ((x0 + x1) / 2.0 - scale * (left + width / 2.0), (y0 + y1) / 2.0 - scale * (top - height / 2.0))
    return Art(symbol, scale, 0.0, False, shift, 0.0)


def art_2d(component: Any) -> dict[str, Any] | None:
    """The art node that paints this part in 2D, or None (the renderer draws the geometry)."""

    if str(getattr(component, "component_type", "")) not in _painted():
        return None
    try:
        art = fit_art(component)
    except (AttributeError, KeyError, TypeError, ValueError):
        return None
    if art is None or art.residual >= MAX_RESIDUAL:
        return None
    # A line shrinks with a small part (its drawing keeps its proportions) and is capped in a large one.
    line = min(art.scale, LINE_SCALE) / art.scale
    place = getattr(component, "art_place", None)               # a part that moves: where it is, and where it is not
    here, there = place() if callable(place) else (0.0, None)
    art = replace(art, shift=(art.shift[0], art.shift[1] + here))
    painted = art.symbol.svg2d or art.symbol.svg               # the 2D look: the same drawing with paint and depth
    overlay = _screen_overlay(component, art)
    if overlay is not None:                                     # computed data replaces the demo trace on the screen
        painted = _DEMO_TRACE.sub("", painted)
    svg = re.sub(r"stroke-width='([\d.]+)'", lambda m: f"stroke-width='{float(m.group(1)) * line:.4g}'",
                 re.search(r"<svg[^>]*>(.*)</svg>", painted, re.S).group(1))
    origin = art.local(*art.symbol.origin)
    node = {
        "type": "art",
        "symbol": art.symbol.name,
        "params": dict(art.symbol.params),
        "svg": svg,
        "matrix": art.matrix(),
        "size": (art.symbol.width, art.symbol.height),
        "residual": art.residual,
        "pic": {"origin": origin, "turn": art.turn, "mirror": art.mirror, "scale": art.scale},
    }
    if there is not None:
        node["outline"] = _dashed_outline(_symbol_box(node["matrix"], node["size"]), there - here)
    if overlay is not None:
        node["overlay"] = overlay
        node["params"]["trace"] = "none"                        # the TikZ pic draws no demo trace either
    return node


# A demo trace in a symbol drawing: the trace colour of the 2D look and of the plain look.
_DEMO_TRACE = re.compile(r"<g (?:(?:stroke|fill)='#(?:fb923c|d55e00)' ?)+>\s*(?:<path[^>]*/>\s*)+</g>", re.I)
PT_PER_CM = 72.0 / 2.54


def _screen_overlay(component: Any, art: Art) -> dict[str, Any] | None:
    """Computed data on the symbol's own screen, in the part's local frame, or None. ``component.screen_data()`` gives
    ``(kind, value, colour)``: a trace as points from -1 to 1 of the screen, or a text at the height
    ``component.READING_V`` (0, the middle, when unset); ``component.SCREEN`` is the screen of the pic
    (x0, y0, x1, y1) in symbol centimetres, y up."""

    data = getattr(component, "screen_data", None)
    items = data() if callable(data) else None
    if not items:
        return None
    x0, y0, x1, y1 = component.SCREEN
    ox, oy = art.symbol.origin

    def at(u: float, v: float) -> tuple[float, float]:          # the margins of a trace on a 3D screen (``_display``)
        x, y = (x0 + x1) / 2 + u * (x1 - x0) * 0.45, (y0 + y1) / 2 + v * (y1 - y0) * 0.4
        return art.local(ox + PT_PER_CM * x, oy - PT_PER_CM * y)

    children = []
    for kind, value, colour in items:
        if kind == "trace":
            children.append({"type": "polyline", "points": [at(u, v) for u, v in value], "stroke": colour,
                             "stroke_width": 0.7 * min(art.scale, LINE_SCALE), "fill": "none",
                             "linecap": "round", "linejoin": "round"})
        else:
            x, y = at(0.0, float(getattr(component, "READING_V", 0.0)))
            size = 0.3 * (y1 - y0) * PT_PER_CM * art.scale
            children.append({"type": "text", "text": str(value), "x": x, "y": y, "fill": colour, "size": size,
                             "font_pt": size})                  # TikZ: one scene unit is one point
    return {"type": "group", "children": children}


def port_gaps(component: Any) -> dict[str, float]:
    """How far the 2D art leaves each port it draws from the port a wire, a fibre, a waveguide or a beam ends at,
    in scene units. Empty when the part has no art. A gap over ``PORT_TOLERANCE`` leaves that end in the air.

    A wire must end on the lead the art draws: its gap is the distance. Light runs on along its port's facing, so
    art that reaches past the port that way (the beam stub of a thin plate's 1D symbol) lies under the light: then
    only the sideways offset counts. Art that stops short of the port leaves the light to start in the air."""

    node = art_2d(component)
    if node is None:
        return {}
    a, b, c, d, e, f = node["matrix"]
    symbol = symbol_for_2d(component)
    gaps = {}
    for name, port in component.ports().items():
        if name not in symbol.ports:
            continue
        x, y = symbol.ports[name].x, symbol.ports[name].y
        dx, dy = a * x + c * y + e - float(port.center.x), -(b * x + d * y + f) - float(port.center.y)
        facing = math.radians(float(port.orientation_deg))
        along, across = dx * math.cos(facing) + dy * math.sin(facing), -dx * math.sin(facing) + dy * math.cos(facing)
        gaps[name] = abs(across) if port.kind != "electrical" and along > 0 else math.hypot(dx, dy)
    return gaps


def art_piece(component: Any, x: float) -> dict[str, Any]:
    """The art of a part as one piece of a larger drawing, ``x`` along the local axis of that drawing."""

    node = art_2d(component)
    a, b, c, d, e, f = node["matrix"]
    origin = node["pic"]["origin"]
    return {**node, "matrix": (a, b, c, d, e + x, f), "pic": {**node["pic"], "origin": (origin[0] + x, origin[1])}}


def tikz_pic(node: dict[str, Any], tx: float = 0.0, ty: float = 0.0) -> str:
    """The art node as a ``\\pic`` of the library, in a picture drawn with ``x=1pt, y=1pt``."""

    pic = node["pic"]
    options = ["transform shape"]          # a pic, like a node, ignores the turn of its scope without this
    if pic["turn"]:
        options.append(f"rotate={pic['turn']:g}")
    if pic["mirror"]:
        options.append("xscale=-1")
    options += ["x=1cm", "y=1cm", f"scale={pic['scale'] * 72.0 / 2.54 / (72.27 / 2.54):.5f}"]
    # The shift sits in its own scope: inside the pic options TikZ would read it in the pic's unit (1 cm).
    # The line scale is set in that scope too (the picture is drawn with x=1pt: one scene unit is one point).
    # The pic stays out of the bounding box (a gradient in a scaled pic counts its whole shading square);
    # the box of the art goes in instead.
    a, b, c, d, e, f = node["matrix"]
    width, height = node["size"]
    corners = [(tx + a * x + c * y + e, ty - (b * x + d * y + f)) for x, y in ((0, 0), (width, 0), (0, height), (width, height))]
    box = "\\path ({:.3f},{:.3f}) rectangle ({:.3f},{:.3f});".format(
        min(x for x, _ in corners), min(y for _, y in corners), max(x for x, _ in corners), max(y for _, y in corners))
    return (f"\\begin{{pgfinterruptboundingbox}}\\begin{{scope}}[shift={{({tx + pic['origin'][0]:.3f},{ty + pic['origin'][1]:.3f})}}]"
            f"\\def\\odls{{{min(pic['scale'], LINE_SCALE):.4g}}}\\odtwodlook"
            f"\\pic[{', '.join(options)}] {{od {node['symbol']}={{{keys(node['params'])}}}}};\\end{{scope}}"
            f"\\end{{pgfinterruptboundingbox}}{box}")


def library_tex() -> str:
    """The TikZ library as one block that typesets nothing where it sits.

    Every line ends in a comment and blank lines are dropped: a line end would
    be a space in the text.
    """

    lines = []
    for path in library_files():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.rstrip()
            if line:                      # the spaces before a comment are text too
                lines.append(re.sub(r"[ \t]+%", "%", line, count=1) if re.search(r"(?<!\\)%", line) else line + "%")
    return "\n".join(lines) + "\n"
