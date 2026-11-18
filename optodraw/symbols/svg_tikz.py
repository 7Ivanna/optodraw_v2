"""SVG art as TikZ paths: the 1D symbol of a part made from SVG art, drawn without a pic of its own.

Groups with transforms, paths (M L H V C S Q T A Z, absolute and relative), rectangles (rounded too),
circles, ellipses, lines, polylines and polygons become ``\\path`` commands with their fill, stroke and
stroke width. An arc becomes short line segments. Coordinates come out in the caller's frame through ``place``.
"""

from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET
from typing import Callable

from optodraw.parts.svg_import import _IDENTITY, _multiply, _transform

Point = tuple[float, float]
_NUMBER = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"
_SHAPES = {"path", "rect", "circle", "ellipse", "line", "polyline", "polygon"}


def _apply(m, x: float, y: float) -> Point:
    return m[0] * x + m[2] * y + m[4], m[1] * x + m[3] * y + m[5]


def _color(value: str | None) -> str | None:
    if value is None or value == "none":
        return None
    value = value.strip()
    if re.fullmatch(r"#[0-9a-fA-F]{3}", value):
        value = "#" + "".join(c * 2 for c in value[1:])
    if re.fullmatch(r"#[0-9a-fA-F]{6}", value):
        r, g, b = (int(value[i:i + 2], 16) for i in (1, 3, 5))
        return f"{{rgb,255:red,{r};green,{g};blue,{b}}}"
    named = {"black": "black", "white": "white", "red": "red", "blue": "blue", "green": "green", "gray": "gray",
             "grey": "gray", "currentcolor": "black"}
    return named.get(value.lower(), "black")


def _style(node: ET.Element, inherited: dict[str, str]) -> dict[str, str]:
    style = dict(inherited)
    for key in ("fill", "stroke", "stroke-width", "opacity", "fill-opacity", "stroke-opacity"):
        if key in node.attrib:
            style[key] = node.attrib[key]
    for part in node.attrib.get("style", "").split(";"):
        if ":" in part:
            key, value = (s.strip() for s in part.split(":", 1))
            style[key] = value
    return style


def _arc(start: Point, rx: float, ry: float, angle: float, large: bool, sweep: bool, end: Point) -> list[Point]:
    """Points on an SVG elliptical arc (endpoint form), start excluded."""

    if rx == 0 or ry == 0 or start == end:
        return [end]
    phi = math.radians(angle)
    cos, sin = math.cos(phi), math.sin(phi)
    dx, dy = (start[0] - end[0]) / 2.0, (start[1] - end[1]) / 2.0
    x1, y1 = cos * dx + sin * dy, -sin * dx + cos * dy
    rx, ry = abs(rx), abs(ry)
    scale = x1 * x1 / (rx * rx) + y1 * y1 / (ry * ry)
    if scale > 1:
        rx, ry = rx * math.sqrt(scale), ry * math.sqrt(scale)
    num = rx * rx * ry * ry - rx * rx * y1 * y1 - ry * ry * x1 * x1
    den = rx * rx * y1 * y1 + ry * ry * x1 * x1
    factor = math.sqrt(max(num / den, 0.0)) * (-1 if large == sweep else 1)
    cx1, cy1 = factor * rx * y1 / ry, -factor * ry * x1 / rx
    cx = cos * cx1 - sin * cy1 + (start[0] + end[0]) / 2.0
    cy = sin * cx1 + cos * cy1 + (start[1] + end[1]) / 2.0

    def theta(ux, uy, vx, vy):
        return math.atan2(ux * vy - uy * vx, ux * vx + uy * vy)

    t1 = theta(1, 0, (x1 - cx1) / rx, (y1 - cy1) / ry)
    dt = theta((x1 - cx1) / rx, (y1 - cy1) / ry, (-x1 - cx1) / rx, (-y1 - cy1) / ry)
    if not sweep and dt > 0:
        dt -= 2 * math.pi
    elif sweep and dt < 0:
        dt += 2 * math.pi
    steps = max(4, int(abs(dt) / (math.pi / 12)))
    points = []
    for i in range(1, steps + 1):
        t = t1 + dt * i / steps
        x, y = rx * math.cos(t), ry * math.sin(t)
        points.append((cos * x - sin * y + cx, sin * x + cos * y + cy))
    points[-1] = end
    return points


def _path_segments(d: str) -> list[list[tuple[str, tuple[Point, ...]]]]:
    """Subpaths of an SVG path as ('M'|'L'|'C'|'Z', points) in absolute coordinates."""

    tokens = re.findall(r"[MmLlHhVvCcSsQqTtAaZz]|" + _NUMBER, d)
    subpaths, current, i = [], [], 0
    pos, start, command, last_control = (0.0, 0.0), (0.0, 0.0), None, None
    while i < len(tokens):
        if re.fullmatch(r"[A-Za-z]", tokens[i]):
            command = tokens[i]
            i += 1
            if command in "Zz":
                current.append(("Z", ()))
                pos, last_control = start, None
                continue
        elif command is None:
            raise ValueError("an SVG path starts with a command")
        rel = command.islower()
        op = command.upper()

        def take(n):
            nonlocal i
            values = [float(v) for v in tokens[i:i + n]]
            i += n
            return values

        if op == "M":
            x, y = take(2)
            pos = (pos[0] + x, pos[1] + y) if rel else (x, y)
            if current:
                subpaths.append(current)
            current, start = [("M", (pos,))], pos
            command = "l" if rel else "L"                       # later pairs are line-tos
        elif op in "LHV":
            if op == "L":
                x, y = take(2)
                pos = (pos[0] + x, pos[1] + y) if rel else (x, y)
            elif op == "H":
                (x,) = take(1)
                pos = (pos[0] + x if rel else x, pos[1])
            else:
                (y,) = take(1)
                pos = (pos[0], pos[1] + y if rel else y)
            current.append(("L", (pos,)))
            last_control = None
        elif op in "CS":
            if op == "C":
                x1, y1, x2, y2, x, y = take(6)
                c1 = (pos[0] + x1, pos[1] + y1) if rel else (x1, y1)
            else:
                x2, y2, x, y = take(4)
                c1 = (2 * pos[0] - last_control[0], 2 * pos[1] - last_control[1]) if last_control else pos
            c2 = (pos[0] + x2, pos[1] + y2) if rel else (x2, y2)
            end = (pos[0] + x, pos[1] + y) if rel else (x, y)
            current.append(("C", (c1, c2, end)))
            pos, last_control = end, c2
        elif op in "QT":
            if op == "Q":
                qx, qy, x, y = take(4)
                q = (pos[0] + qx, pos[1] + qy) if rel else (qx, qy)
            else:
                x, y = take(2)
                q = (2 * pos[0] - last_control[0], 2 * pos[1] - last_control[1]) if last_control else pos
            end = (pos[0] + x, pos[1] + y) if rel else (x, y)
            c1 = (pos[0] + 2 / 3 * (q[0] - pos[0]), pos[1] + 2 / 3 * (q[1] - pos[1]))
            c2 = (end[0] + 2 / 3 * (q[0] - end[0]), end[1] + 2 / 3 * (q[1] - end[1]))
            current.append(("C", (c1, c2, end)))
            pos, last_control = end, q
        elif op == "A":
            rx, ry, angle, large, sweep, x, y = take(7)
            end = (pos[0] + x, pos[1] + y) if rel else (x, y)
            current += [("L", (p,)) for p in _arc(pos, rx, ry, angle, bool(large), bool(sweep), end)]
            pos, last_control = end, None
        else:
            raise ValueError(f"unsupported SVG path command {command}")
    if current:
        subpaths.append(current)
    return subpaths


def _shape_segments(node: ET.Element, tag: str) -> list[list[tuple[str, tuple[Point, ...]]]]:
    get = lambda key, default=0.0: float(node.attrib.get(key, default))  # noqa: E731
    if tag == "path":
        return _path_segments(node.attrib.get("d", ""))
    if tag == "rect":
        x, y, w, h = get("x"), get("y"), get("width"), get("height")
        r = min(get("rx", node.attrib.get("ry", 0)), w / 2, h / 2)
        if r <= 0:
            return [[("M", ((x, y),)), ("L", ((x + w, y),)), ("L", ((x + w, y + h),)), ("L", ((x, y + h),)), ("Z", ())]]
        d = (f"M{x + r} {y} H{x + w - r} A{r} {r} 0 0 1 {x + w} {y + r} V{y + h - r} A{r} {r} 0 0 1 {x + w - r} {y + h} "
             f"H{x + r} A{r} {r} 0 0 1 {x} {y + h - r} V{y + r} A{r} {r} 0 0 1 {x + r} {y} Z")
        return _path_segments(d)
    if tag in ("circle", "ellipse"):
        cx, cy = get("cx"), get("cy")
        rx = get("r") if tag == "circle" else get("rx")
        ry = get("r") if tag == "circle" else get("ry")
        return _path_segments(f"M{cx + rx} {cy} A{rx} {ry} 0 1 1 {cx - rx} {cy} A{rx} {ry} 0 1 1 {cx + rx} {cy} Z")
    if tag == "line":
        return [[("M", ((get("x1"), get("y1")),)), ("L", ((get("x2"), get("y2")),))]]
    values = [float(v) for v in re.findall(_NUMBER, node.attrib.get("points", ""))]
    points = list(zip(values[0::2], values[1::2]))
    if not points:
        return []
    segments = [("M", (points[0],))] + [("L", (p,)) for p in points[1:]]
    return [segments + ([("Z", ())] if tag == "polygon" else [])]


def svg_to_tikz(svg: str, place: Callable[[float, float], str]) -> list[str]:
    """One ``\\path`` line per filled or stroked shape of ``svg``; ``place(x, y)`` turns an SVG point of the
    document into a TikZ coordinate."""

    root = ET.fromstring(svg)
    lines: list[str] = []

    def walk(node: ET.Element, matrix, style: dict[str, str]) -> None:
        tag = node.tag.split("}")[-1]
        if tag in ("defs", "title", "desc", "clipPath", "mask", "text", "style"):
            return
        matrix = _multiply(matrix, _transform(node.attrib.get("transform", "")))
        style = _style(node, style)
        if tag in _SHAPES:
            fill = _color(style.get("fill", "#000000" if tag not in ("line", "polyline") else "none"))
            stroke = _color(style.get("stroke"))
            if fill is None and stroke is None:
                return
            scale = math.sqrt(abs(matrix[0] * matrix[3] - matrix[1] * matrix[2]))
            options = []
            if fill:
                options.append(f"fill={fill}")
            if stroke:
                width = float(re.findall(_NUMBER, style.get("stroke-width", "1"))[0]) * scale
                options.append(f"draw={stroke}, line width={width:.3f}pt")
            opacity = style.get("opacity")
            if opacity not in (None, "1"):
                options.append(f"opacity={float(opacity):g}")
            for subpath in _shape_segments(node, tag):
                parts = []
                for op, points in subpath:
                    if op == "M":
                        parts.append(place(*_apply(matrix, *points[0])))
                    elif op == "L":
                        parts.append("-- " + place(*_apply(matrix, *points[0])))
                    elif op == "C":
                        c1, c2, end = (place(*_apply(matrix, *p)) for p in points)
                        parts.append(f".. controls {c1} and {c2} .. {end}")
                    else:
                        parts.append("-- cycle")
                lines.append(f"\\path[{', '.join(options)}] {' '.join(parts)};")
        for child in node:
            walk(child, matrix, style)

    walk(root, _IDENTITY, {})
    return lines
