"""TikZ renderer for LaTeX documents."""

from __future__ import annotations

from typing import Any

from optodraw.core.component import ANNOTATION_TYPES, Component, Group
from optodraw.core.beam import Beam, FocusingBeam, drawn_widths
from optodraw.core.markup import latex
from optodraw.core.routing import Route, bench_cable
from optodraw.renderers.capabilities import RenderReport
from optodraw.symbols.art import art_2d, library_tex, tikz_pic


class TikzRenderer:
    """Render scenes to TikZ code for LaTeX documents."""

    def __init__(self, scene, **kwargs):
        """Create a TikZ renderer for a scene.

        ``standalone`` wraps the output in a full LaTeX document, while
        ``scale`` controls the scene-unit to TikZ-point conversion used by
        callers that post-process coordinates. ``view="1d"`` selects compact
        monochrome component symbols instead of the default 2D geometry.
        """

        self.scene = scene
        self.standalone = kwargs.get("standalone", False)
        self.scale = kwargs.get("scale", 0.05)
        from optodraw.renderers.capabilities import view_keyword

        self.view = view_keyword(kwargs, "TikZ view")
        self.include_library: bool = kwargs.get("include_library", True)
        self.strict: bool = kwargs.get("strict", False)
        self.report = RenderReport()
        self._colors: dict[str, str] = {}
        self._uses_library = False                             # an art node needs the symbol library
        self.beam_widths: dict[int, float] = {}             # id(beam) -> its drawn width, nested on a shared path

    def _beam_width(self, node: Any) -> float:
        return self.beam_widths.get(id(node), node.display_width)

    def render(self, filename: str | None = None) -> str:
        """Render the scene to TikZ text and optionally write it to a file."""

        if self.view == "1d":
            return self._render_schematic(filename)
        self.beam_widths = drawn_widths([n for n in self.scene.walk() if isinstance(n, Beam)])
        body = ["\\begin{tikzpicture}[x=1pt,y=1pt,line cap=round,line join=round]"]
        body.extend(self._render_node(self.scene.root))
        body.append("\\end{tikzpicture}")

        header = [library_tex().rstrip()] if self._uses_library else []
        for name, hex_color in self._colors.items():
            header.append(f"\\definecolor{{{name}}}{{HTML}}{{{hex_color[1:]}}}")

        content = "\n".join(header + body)
        if self.standalone:
            content = "\n".join([
                "\\documentclass[tikz]{standalone}",
                "\\usepackage{xcolor}",
                "\\begin{document}",
                content,
                "\\end{document}",
            ])
        if filename:
            with open(filename, "w", encoding="utf-8") as handle:
                handle.write(content)
        return content

    def _render_schematic(self, filename: str | None) -> str:
        """The 1D view: the symbol library, one pic per part, links between named ports."""

        from optodraw.symbols.tikz_export import render_tikz_1d

        content = render_tikz_1d(self.scene, include_library=self.include_library)
        if self.standalone:
            content = "\n".join(["\\documentclass[tikz]{standalone}", "\\begin{document}", content, "\\end{document}"])
        if filename:
            with open(filename, "w", encoding="utf-8") as handle:
                handle.write(content)
        return content

    def _color_name(self, value: str) -> str:
        if not value.startswith("#") or len(value) != 7:
            return value
        if value not in self._colors.values():
            name = f"optodrawColor{len(self._colors) + 1}"
            self._colors[name] = value
            return name
        for name, existing in self._colors.items():
            if existing == value:
                return name
        return value

    def _fmt(self, x: float, y: float) -> str:
        return f"({x:.3f},{y:.3f})"

    def _opacity_option(self, geometry: dict[str, Any]) -> list[str]:
        opacity = geometry.get("opacity")
        if isinstance(opacity, (int, float)):
            return [f"opacity={opacity:.3f}"]
        return []

    @staticmethod
    def _dash_tikz(dash: str) -> str:
        parts = dash.split()
        if len(parts) >= 2:
            try:
                on, off = float(parts[0]), float(parts[1])
                return f"dash pattern=on {on:.1f}pt off {off:.1f}pt"
            except ValueError:
                pass
        return "dashed"

    def _render_node(self, node: Component) -> list[str]:
        if isinstance(node, Group):
            lines: list[str] = []
            # a bench cable lies under the parts, as in the SVG: its end goes under its connector
            cables = {id(c) for c in node.children
                      if isinstance(c, Route) and bench_cable(c.kind, c.start_component, c.end_component)}
            children = list(node.children)
            slots = [i for i, c in enumerate(children) if isinstance(c, Beam)]
            widest_first = sorted((children[i] for i in slots), key=self._beam_width, reverse=True)
            for i, beam in zip(slots, widest_first):           # as in the SVG, a lower beam shows round the next
                children[i] = beam
            for child in sorted(children, key=lambda c: id(c) not in cables):
                lines.extend(self._render_node(child))
            return lines

        if isinstance(node, Beam) and getattr(node, "envelope", False):
            return []  # drawn as a fill in SVG only
        if isinstance(node, Beam):
            color = node.color
            return [self._polyline(node.resolve_points(), color, self._beam_width(node), opacity=node.opacity)]

        if isinstance(node, Route):
            color = node.color
            return [self._polyline(node.resolve_points(), color, node.width)]

        if isinstance(node, FocusingBeam):
            return self._focusing_beam(node)

        art = art_2d(node)                                    # painted with its symbol: see optodraw/symbols/art.py
        geometry = art or node.geometry_2d()
        pos = node.world_transform.position
        try:
            angle = float(node.world_transform.rotation_deg.z)
        except Exception:
            angle = 0.0
        if abs(angle) > 1e-9:
            inner = self._render_geometry(geometry, 0.0, 0.0)
            lines = [
                f"\\begin{{scope}}[shift={{{self._fmt(pos.x, pos.y)}}},rotate={angle:.3f}]",
                *inner,
                "\\end{scope}",
            ]
        else:
            lines = self._render_geometry(geometry, pos.x, pos.y)
        if node.component_type in ANNOTATION_TYPES:
            anchor = {"start": "anchor=west,", "end": "anchor=east,"}.get(node.anchor, "")
            weight = "\\bfseries" if node.bold else ""
            if node.label and node.component_type != "Inset":
                lines.append(f"\\node[{anchor}text={self._color_name(node.color)},font=\\scriptsize{weight}] at "
                             f"{self._fmt(pos.x, pos.y)} {{{latex(node.label, self._latex_escape)}}};")
        elif node.label:
            from optodraw.renderers.labels import label_side, label_spot

            wpos = node.world_position
            side = label_side(node)
            if side == "top":
                label_offset = 8
                lines.append(f"\\node[anchor=south] at {self._fmt(wpos.x, wpos.y + label_offset)} {{{latex(node.label, self._latex_escape)}}};")
            else:
                dx, dy = label_spot(node)
                anchor = {"left": "east", "right": "west", "bottom": "north", "top-left": "south east",
                          "top-right": "south west", "bottom-left": "north east", "bottom-right": "north west"}[side]
                lines.append(f"\\node[anchor={anchor}] at {self._fmt(wpos.x + dx, wpos.y + dy)} {{{latex(node.label, self._latex_escape)}}};")
        return lines

    def _polyline(self, points: list[tuple[float, float, float]], color: str, width: float,
                  opacity: float | None = None) -> str:
        coords = " -- ".join(self._fmt(p[0], p[1]) for p in points)
        tikz_color = self._color_name(color)
        see_through = f",opacity={opacity:.3f}" if opacity is not None else ""
        return f"\\draw[line width={max(width, 0.4):.3f}pt,color={tikz_color}{see_through}] {coords};"

    @staticmethod
    def _latex_escape(text: str) -> str:
        # Use a placeholder for backslashes so the braces in \textbackslash{} are not re-escaped
        placeholder = "\x00"
        out = text.replace("\\", placeholder)
        for ch in ("&", "%", "$", "#", "_", "{", "}", "~", "^"):
            if ch == "~":
                out = out.replace(ch, r"\textasciitilde{}")
            elif ch == "^":
                out = out.replace(ch, r"\textasciicircum{}")
            else:
                out = out.replace(ch, "\\" + ch)
        return out.replace(placeholder, r"\textbackslash{}")

    def _focusing_beam(self, node: FocusingBeam) -> list[str]:
        """A converging/diverging beam as a filled trapezoid (width1 -> width2)."""

        corners = node.corners()          # the beam owns its own geometry
        if not corners:
            return []
        coords = " -- ".join(self._fmt(x, y) for x, y in corners) + " -- cycle"
        return [f"\\path[fill={self._color_name(node.color)},fill opacity={node.opacity:.3f}] {coords};"]

    @staticmethod
    def _split_path_tokens(d: str) -> list[str]:
        import re as _re

        return _re.findall(r"[MLHVQCAZmlhvqcaz]|-?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?", d or "")

    def _render_path(self, geometry: dict[str, Any], tx: float = 0.0, ty: float = 0.0) -> str:
        """Translate the M/L/H/V/Q/C/A/Z path subset our components emit into TikZ.

        Anything outside the subset falls back to a straight polyline through
        the command endpoints so output never silently drops a shape.
        """

        import math as _math

        def pt(x: float, y: float) -> str:
            return self._fmt(tx + x, ty + y)

        tokens = self._split_path_tokens(str(geometry.get("d", "")))
        commands = "MLHVQCAZmlhvqcaz"
        parts: list[str] = []
        i, n = 0, len(tokens)

        def take(count: int) -> list[float] | None:
            nonlocal i
            vals: list[float] = []
            while len(vals) < count and i < n and tokens[i] not in commands:
                try:
                    vals.append(float(tokens[i]))
                except ValueError:
                    return None
                i += 1
            return vals if len(vals) == count else None

        pen: tuple[float, float] | None = None
        start: tuple[float, float] | None = None
        while i < n:
            token = tokens[i]
            i += 1
            if token in "Mm":
                pair = take(2)
                if pair is None:
                    break
                base = pen if token == "m" and pen is not None else (0.0, 0.0)
                pen = (base[0] + pair[0], base[1] + pair[1])
                start = pen
                parts.append(pt(*pen))
                while i < n and tokens[i] not in commands:
                    pair = take(2)
                    if pair is None:
                        break
                    if token == "m":
                        pen = (pen[0] + pair[0], pen[1] + pair[1])
                    else:
                        pen = (pair[0], pair[1])
                    parts.append(f"-- {pt(*pen)}")
            elif token in "Ll":
                while True:
                    pair = take(2)
                    if pair is None:
                        break
                    if token == "l" and pen is not None:
                        pen = (pen[0] + pair[0], pen[1] + pair[1])
                    else:
                        pen = (pair[0], pair[1])
                    parts.append(f"-- {pt(*pen)}")
            elif token in "Hh":
                while True:
                    value = take(1)
                    if value is None or pen is None:
                        break
                    pen = (pen[0] + value[0] if token == "h" else value[0], pen[1])
                    parts.append(f"-- {pt(*pen)}")
            elif token in "Vv":
                while True:
                    value = take(1)
                    if value is None or pen is None:
                        break
                    pen = (pen[0], pen[1] + value[0] if token == "v" else value[0])
                    parts.append(f"-- {pt(*pen)}")
            elif token in "Qq":
                while True:
                    vals = take(4)
                    if vals is None:
                        break
                    base = pen if token == "q" and pen is not None else (0.0, 0.0)
                    control = (base[0] + vals[0], base[1] + vals[1])
                    pen = (base[0] + vals[2], base[1] + vals[3])
                    parts.append(f".. controls {pt(*control)} .. {pt(*pen)}")
            elif token in "Cc":
                while True:
                    vals = take(6)
                    if vals is None:
                        break
                    base = pen if token == "c" and pen is not None else (0.0, 0.0)
                    control1 = (base[0] + vals[0], base[1] + vals[1])
                    control2 = (base[0] + vals[2], base[1] + vals[3])
                    pen = (base[0] + vals[4], base[1] + vals[5])
                    parts.append(f".. controls {pt(*control1)} and {pt(*control2)} .. {pt(*pen)}")
            elif token in "Aa":
                while True:
                    vals = take(7)
                    if vals is None:
                        break
                    rx, ry, rotation, large_flag, sweep_flag, ex, ey = vals
                    if token == "a" and pen is not None:
                        ex += pen[0]
                        ey += pen[1]
                    end = (ex, ey)
                    if pen is None:
                        pen = end
                        parts.append(pt(*pen))
                        continue
                    rx, ry = abs(rx), abs(ry)
                    if rx <= 1e-12 or ry <= 1e-12:
                        parts.append(f"-- {pt(*end)}")
                        pen = end
                        continue
                    if _math.dist(pen, end) <= 1e-12:
                        pen = end
                        continue
                    phi = _math.radians(rotation)
                    cos_phi, sin_phi = _math.cos(phi), _math.sin(phi)
                    dx, dy = (pen[0] - ex) / 2.0, (pen[1] - ey) / 2.0
                    x1p = cos_phi * dx + sin_phi * dy
                    y1p = -sin_phi * dx + cos_phi * dy
                    radius_scale = _math.sqrt((x1p / rx) ** 2 + (y1p / ry) ** 2)
                    if radius_scale > 1.0:
                        rx *= radius_scale
                        ry *= radius_scale
                    rx2, ry2 = rx * rx, ry * ry
                    numerator = rx2 * ry2 - rx2 * y1p * y1p - ry2 * x1p * x1p
                    denominator = rx2 * y1p * y1p + ry2 * x1p * x1p
                    if denominator <= 1e-24:
                        parts.append(f"-- {pt(*end)}")
                        pen = end
                        continue
                    sign = -1.0 if bool(large_flag) == bool(sweep_flag) else 1.0
                    factor = sign * _math.sqrt(max(numerator / denominator, 0.0))
                    cxp = factor * rx * y1p / ry
                    cyp = -factor * ry * x1p / rx
                    cx = cos_phi * cxp - sin_phi * cyp + (pen[0] + ex) / 2.0
                    cy = sin_phi * cxp + cos_phi * cyp + (pen[1] + ey) / 2.0
                    ux, uy = (x1p - cxp) / rx, (y1p - cyp) / ry
                    vx, vy = (-x1p - cxp) / rx, (-y1p - cyp) / ry
                    start_angle = _math.atan2(uy, ux)
                    sweep_angle = _math.atan2(ux * vy - uy * vx, ux * vx + uy * vy)
                    if not sweep_flag and sweep_angle > 0:
                        sweep_angle -= 2.0 * _math.pi
                    elif sweep_flag and sweep_angle < 0:
                        sweep_angle += 2.0 * _math.pi

                    def ellipse(angle: float) -> tuple[float, float]:
                        return (
                            cx + cos_phi * rx * _math.cos(angle) - sin_phi * ry * _math.sin(angle),
                            cy + sin_phi * rx * _math.cos(angle) + cos_phi * ry * _math.sin(angle),
                        )

                    def tangent(angle: float) -> tuple[float, float]:
                        return (
                            -cos_phi * rx * _math.sin(angle) - sin_phi * ry * _math.cos(angle),
                            -sin_phi * rx * _math.sin(angle) + cos_phi * ry * _math.cos(angle),
                        )

                    segments = max(1, _math.ceil(abs(sweep_angle) / (_math.pi / 2.0)))
                    step = sweep_angle / segments
                    for segment in range(segments):
                        a0 = start_angle + segment * step
                        a1 = a0 + step
                        alpha = 4.0 / 3.0 * _math.tan(step / 4.0)
                        p0, p1 = ellipse(a0), ellipse(a1)
                        t0, t1 = tangent(a0), tangent(a1)
                        control1 = (p0[0] + alpha * t0[0], p0[1] + alpha * t0[1])
                        control2 = (p1[0] - alpha * t1[0], p1[1] - alpha * t1[1])
                        parts.append(f".. controls {pt(*control1)} and {pt(*control2)} .. {pt(*p1)}")
                    pen = end
            elif token in "Zz":
                parts.append("-- cycle")
                pen = start
            else:
                break

        opts: list[str] = []
        fill, stroke = geometry.get("fill"), geometry.get("stroke")
        if fill and fill != "none":
            opts.append(f"fill={self._color_name(fill)}")
        if stroke and stroke != "none":
            opts.append(f"draw={self._color_name(stroke)},line width={geometry.get('stroke_width', 0.4):.3f}pt")
        if not opts:
            opts.append("draw=black")
        opts.extend(self._opacity_option(geometry))
        body = " ".join(parts) if parts else self._fmt(tx, ty)
        return f"\\path[{','.join(opts)}] {body};"

    def _render_geometry(self, geometry: dict[str, Any], tx: float = 0.0, ty: float = 0.0) -> list[str]:
        if not geometry:
            return []
        gtype = geometry.get("type")
        if gtype != "group":
            self.report.check("tikz", gtype, strict=self.strict, detail=f"{self.view.upper()} node type {gtype!r}")
        if gtype == "group":
            lines: list[str] = []
            for child in geometry.get("children", []):
                lines.extend(self._render_geometry(child, tx, ty))
            return lines
        if gtype == "art":
            if "pic" not in geometry:                   # a part made from SVG art: no pic, its art as paths
                from optodraw.symbols.svg_tikz import svg_to_tikz

                a, b, c, d, e, f = geometry.get("matrix", (1.0, 0.0, 0.0, 1.0, 0.0, 0.0))
                svg = geometry["svg"]
                if not svg.lstrip().startswith("<svg"):
                    svg = ('<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink">'
                           f"{svg}</svg>")
                return svg_to_tikz(svg, lambda x, y: self._fmt(tx + a * x + c * y + e, ty - (b * x + d * y + f)))
            self._uses_library = True
            extras = [line for extra in ("overlay", "outline") if extra in geometry
                      for line in self._render_geometry(geometry[extra], tx, ty)]
            return [tikz_pic(geometry, tx, ty), *extras]
        if gtype == "rect":
            x1 = tx + geometry.get("cx", 0.0) - geometry["w"] / 2.0
            y1 = ty + geometry.get("cy", 0.0) - geometry["h"] / 2.0
            x2 = x1 + geometry["w"]
            y2 = y1 + geometry["h"]
            opts = []
            fill = geometry.get("fill")
            stroke = geometry.get("stroke")
            if fill and fill != "none":
                opts.append(f"fill={self._color_name(fill)}")
            if stroke and stroke != "none":
                opts.append(f"draw={self._color_name(stroke)},line width={geometry.get('stroke_width', 0.4):.3f}pt")
            else:
                opts.append("draw=none")
            if geometry.get("rx"):
                opts.append(f"rounded corners={geometry['rx']:.3f}pt")
            opts.extend(self._opacity_option(geometry))
            return [f"\\path[{','.join(opts)}] {self._fmt(x1, y1)} rectangle {self._fmt(x2, y2)};"]
        if gtype == "line":
            color = self._color_name(geometry.get("stroke", "#000000"))
            dash = geometry.get("stroke_dasharray")
            dash_opt = f",{self._dash_tikz(dash)}" if dash else ""
            opacity_opt = ",".join(self._opacity_option(geometry))
            opacity_opt = f",{opacity_opt}" if opacity_opt else ""
            return [f"\\draw[line width={geometry.get('stroke_width', 0.6):.3f}pt,color={color}{dash_opt}{opacity_opt}] {self._fmt(tx + geometry['x1'], ty + geometry['y1'])} -- {self._fmt(tx + geometry['x2'], ty + geometry['y2'])};"]
        if gtype == "circle":
            stroke = geometry.get("stroke")
            fill = geometry.get("fill", "none")
            opts = [f"draw={self._color_name(stroke)}"] if stroke and stroke != "none" else ["draw=none"]
            if fill != "none":
                opts.append(f"fill={self._color_name(fill)}")
            opts.extend(self._opacity_option(geometry))
            return [f"\\draw[{','.join(opts)},line width={geometry.get('stroke_width', 0.6):.3f}pt] {self._fmt(tx + geometry.get('cx', 0.0), ty + geometry.get('cy', 0.0))} circle ({geometry['r']:.3f}pt);"]
        if gtype == "polyline":
            color = self._color_name(geometry.get("stroke", "#000000"))
            coords = " -- ".join(self._fmt(tx + p[0], ty + p[1]) for p in geometry.get("points", []))
            if geometry.get("closed"):
                coords += " -- cycle"
            dash = geometry.get("stroke_dasharray")
            dash_opt = f",{self._dash_tikz(dash)}" if dash else ""
            opacity_opt = ",".join(self._opacity_option(geometry))
            opacity_opt = f",{opacity_opt}" if opacity_opt else ""
            return [f"\\draw[line width={geometry.get('stroke_width', 0.6):.3f}pt,color={color}{dash_opt}{opacity_opt}] {coords};"]
        if gtype == "path":
            return [self._render_path(geometry, tx, ty)]
        if gtype == "polygon":
            points = geometry.get("points", [])
            if len(points) < 2:
                return []
            coords = " -- ".join(self._fmt(tx + p[0], ty + p[1]) for p in points) + " -- cycle"
            opts: list[str] = []
            fill, stroke = geometry.get("fill"), geometry.get("stroke")
            if fill and fill != "none":
                opts.append(f"fill={self._color_name(fill)}")
            if stroke and stroke != "none":
                opts.append(f"draw={self._color_name(stroke)},line width={geometry.get('stroke_width', 0.4):.3f}pt")
            if not opts:
                opts.append("draw=black")
            opts.extend(self._opacity_option(geometry))
            return [f"\\path[{','.join(opts)}] {coords};"]
        if gtype == "ellipse":
            cx, cy = tx + geometry.get("cx", 0.0), ty + geometry.get("cy", 0.0)
            opts = []
            fill, stroke = geometry.get("fill"), geometry.get("stroke")
            if fill and fill != "none":
                opts.append(f"fill={self._color_name(fill)}")
            if stroke and stroke != "none":
                opts.append(f"draw={self._color_name(stroke)}")
            if not opts:
                opts.append("draw=black")
            opts.extend(self._opacity_option(geometry))
            return [f"\\draw[{','.join(opts)},line width={geometry.get('stroke_width', 0.6):.3f}pt] {self._fmt(cx, cy)} ellipse ({geometry['rx']:.3f}pt and {geometry['ry']:.3f}pt);"]
        if gtype == "text":
            txt = str(geometry.get("text", "")).strip()
            if not txt:
                return []
            x, y = tx + geometry.get("x", 0.0), ty + geometry.get("y", 0.0)
            color = self._color_name(geometry.get("fill", "#1f2937"))
            anchor = {"start": "anchor=west,", "end": "anchor=east,"}.get(geometry.get("text_anchor", "middle"), "")
            opacity_opt = ",".join(self._opacity_option(geometry))
            opacity_opt = f",{opacity_opt}" if opacity_opt else ""
            size = geometry.get("font_pt")                     # a text sized to its part, as on a screen: 10 pt
            font = f"\\fontsize{{10}}{{12}}\\selectfont,scale={size / 10:.4g}" if size else "\\scriptsize"   # exists in every font
            return [f"\\node[{anchor}text={color},font={font}{opacity_opt}] at {self._fmt(x, y)} {{{self._latex_escape(txt)}}};"]
        return []
