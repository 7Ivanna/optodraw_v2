"""Import sanitized SVG artwork and affine-transformed port marks."""

from __future__ import annotations

from copy import deepcopy
import math
from pathlib import Path
import re
import xml.etree.ElementTree as ET

from .definition import _ELEMENTS, finite, load_svg, port_specs
from ._svg_frame import resolved_root

_NUMBER = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
_IDENTITY = (1., 0., 0., 1., 0., 0.)


def _path_ends(d, label):
    """The first point of a path and the point after it (None when the path has one point)."""

    tokens = re.findall(r"[MmLlHhVv]|[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?", d)
    if len(tokens) < 3 or tokens[0] not in "Mm":
        raise ValueError(f"{label}: a path port mark starts with M x,y")
    x, y = float(tokens[1]), float(tokens[2])
    rest = tokens[3:]
    if not rest:
        return (x, y), None
    command = rest[0] if rest[0].isalpha() else ("l" if tokens[0] == "m" else "L")
    numbers = [float(v) for v in (rest[1:] if rest[0].isalpha() else rest)[:2]]
    relative = command.islower()
    if command in "Ll" and len(numbers) == 2:
        return (x, y), ((x + numbers[0], y + numbers[1]) if relative else (numbers[0], numbers[1]))
    if command in "Hh" and numbers:
        return (x, y), ((x + numbers[0]) if relative else numbers[0], y)
    if command in "Vv" and numbers:
        return (x, y), (x, (y + numbers[0]) if relative else numbers[0])
    raise ValueError(f"{label}: a path port mark is M x,y followed by one L, H or V segment")


def _multiply(a, b):
    return (a[0]*b[0]+a[2]*b[1], a[1]*b[0]+a[3]*b[1],
            a[0]*b[2]+a[2]*b[3], a[1]*b[2]+a[3]*b[3],
            a[0]*b[4]+a[2]*b[5]+a[4], a[1]*b[4]+a[3]*b[5]+a[5])


def _transform(text):
    matrix = _IDENTITY
    position = 0
    for match in re.finditer(r"([A-Za-z]+)\s*\(([^()]*)\)", text):
        if text[position:match.start()].strip(" ,\t\n\r"):
            raise ValueError("Invalid SVG transform")
        name, args = match.groups()
        if re.sub(_NUMBER, "", args).strip(" ,\t\n\r"):
            raise ValueError("Invalid SVG transform numbers")
        values = [finite(float(v), "SVG transform") for v in re.findall(_NUMBER, args)]
        if name == "matrix" and len(values) == 6:
            next_matrix = tuple(values)
        elif name == "translate" and len(values) in {1, 2}:
            next_matrix = (1, 0, 0, 1, values[0], values[1] if len(values) == 2 else 0)
        elif name == "scale" and len(values) in {1, 2}:
            next_matrix = (values[0], 0, 0, values[-1], 0, 0)
        elif name == "rotate" and len(values) in {1, 3}:
            c, s = math.cos(math.radians(values[0])), math.sin(math.radians(values[0]))
            next_matrix = (c, s, -s, c, 0, 0)
            if len(values) == 3:
                x, y = values[1:]
                next_matrix = (c, s, -s, c, x-c*x+s*y, y-s*x-c*y)
        elif name in {"skewX", "skewY"} and len(values) == 1:
            t = math.tan(math.radians(values[0]))
            next_matrix = (1, 0, t, 1, 0, 0) if name == "skewX" else (1, t, 0, 1, 0, 0)
        else:
            raise ValueError(f"Unsupported SVG transform: {name}")
        matrix = _multiply(matrix, next_matrix)
        position = match.end()
    if text[position:].strip(" ,\t\n\r"):
        raise ValueError("Invalid SVG transform")
    return matrix


def import_svg_part(name, source, *, platform="on_chip", origin=(0, 0), scale=1,
                    ports=None, symbol_1d=None, parameters=None, description="", library=None):
    """Read circle, line or group marks named port:<name>.

    data-orientation uses SVG degrees (clockwise); local ports use y up.
    data-kind defaults to optical and data-width defaults to 0.5 micrometres.
    Line endpoints supply a direction when data-orientation is absent.
    Explicit ports use local coordinates and replace all marker definitions.
    """
    from . import define_part

    if isinstance(source, bytes):
        data = source
    elif isinstance(source, str) and source.lstrip().startswith("<"):
        data = source.encode("utf-8")
    else:
        path = Path(source)
        if path.stat().st_size > 10*1024*1024:
            raise ValueError("SVG exceeds the 10 MiB asset limit")
        data = path.read_bytes()
    if len(data) > 10*1024*1024 or b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
        raise ValueError("Unsafe or oversized SVG")
    try:
        raw = ET.fromstring(data)
    except ET.ParseError as error:
        raise ValueError("Invalid SVG document") from error
    for node in raw.iter():
        node.tag = node.tag.removeprefix("{http://www.w3.org/2000/svg}")
        if node.tag not in _ELEMENTS:
            raise ValueError(f"Unsupported SVG element: {node.tag}")
    art = deepcopy(raw)

    def remove_marks(node):
        for child in list(node):
            if child.get("id", "").startswith("port:"):
                node.remove(child)
            else:
                remove_marks(child)

    remove_marks(art)
    asset = load_svg(ET.tostring(art))  # validate art before any editor preview
    measured = resolved_root(raw, asset.view_box)
    ox, oy = [finite(value, "SVG origin") for value in origin]
    scale = finite(scale, "SVG scale", positive=True)
    found = []

    def walk(node, parent, nested=False):
        matrix = _multiply(parent, _transform(node.get("transform", "")))
        marker = node.get("id", "")
        if marker.startswith("port:"):
            if nested:
                raise ValueError(f"{name} {marker}: flatten nested SVG viewports before import")
            toward = None                     # a second point that gives the port its direction
            if node.tag in {"circle", "ellipse"}:
                x, y = float(node.get("cx", "0")), float(node.get("cy", "0"))
            elif node.tag == "line":
                x, y = float(node.get("x1", "0")), float(node.get("y1", "0"))
                toward = (float(node.get("x2", "0")), float(node.get("y2", "0")))
            elif node.tag == "path":          # drawsvg writes a Line as <path d="M x,y L x,y">
                (x, y), toward = _path_ends(node.get("d", ""), f"{name} {marker}")
            elif node.tag == "g" and "data-x" in node.attrib and "data-y" in node.attrib:
                x, y = float(node.get("data-x")), float(node.get("data-y"))
            else:
                raise ValueError(f"{name} {marker}: a port mark is a circle, ellipse, line, path, or a group "
                                 f"with data-x and data-y; got <{node.tag}>")
            if "data-orientation" in node.attrib:
                angle = finite(float(node.get("data-orientation")), f"{name} {marker} orientation")
            elif toward is not None and toward != (x, y):
                angle = math.degrees(math.atan2(toward[1]-y, toward[0]-x))
            else:
                angle = 0
            dx, dy = math.cos(math.radians(angle)), math.sin(math.radians(angle))
            vx, vy = matrix[0]*dx+matrix[2]*dy, matrix[1]*dx+matrix[3]*dy
            length = math.hypot(vx, vy)
            if length == 0:
                raise ValueError(f"{name} {marker}: singular port transform")
            width = finite(float(node.get("data-width", "0.5")), f"{name} {marker} width", positive=True)
            width *= scale*abs(matrix[0]*matrix[3]-matrix[1]*matrix[2])/length
            found.append({"name": marker[5:], "center": [
                (matrix[0]*x+matrix[2]*y+matrix[4]-ox)*scale,
                -(matrix[1]*x+matrix[3]*y+matrix[5]-oy)*scale],
                "orientation_deg": math.degrees(math.atan2(-vy, vx)) % 360,
                "width": width, "kind": node.get("data-kind", "optical")})
            return
        for child in node:
            walk(child, matrix, nested or child.tag == "svg")

    walk(measured, _IDENTITY)
    if ports is None and not found:
        raise ValueError(f"{name}: SVG needs port marks; supply explicit ports= to import unmarked art")
    chosen = [port.to_dict() for port in port_specs(found if ports is None else ports)]
    if scale != 1 or ox != 0 or oy != 0:
        inner = asset.root()
        inner.tag = "g"
        inner.attrib.pop("viewBox", None)
        root = ET.Element("svg")
        x, y, w, h = asset.view_box
        root.set("viewBox", f"{(x-ox)*scale:g} {(y-oy)*scale:g} {w*scale:g} {h*scale:g}")
        group = ET.SubElement(root, "g", transform=f"matrix({scale:g} 0 0 {scale:g} {-ox*scale:g} {-oy*scale:g})")
        group.append(inner)
        asset = load_svg(ET.tostring(root))
    return define_part(name, platform=platform, ports=chosen, symbol_2d=asset.data,
                       symbol_1d=symbol_1d, parameters=parameters, description=description, library=library)
