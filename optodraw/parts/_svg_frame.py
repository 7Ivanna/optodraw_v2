"""Resolve embedded SVG frames without changing canonical asset bytes."""

import math
import re
import xml.etree.ElementTree as ET


_X_LENGTHS = {"x", "x1", "x2", "cx", "rx", "width"}
_Y_LENGTHS = {"y", "y1", "y2", "cy", "ry", "height"}
_OTHER_LENGTHS = {"r", "stroke-width", "stroke-dashoffset"}
_OPACITIES = {"opacity", "fill-opacity", "stroke-opacity"}
_LINK_TYPES = {"Route", "WaveguideRoute", "FiberRoute", "Beam", "FocusingBeam"}
_RELATIVE_UNIT = re.compile(r"(?:em|ex|ch|rem|vw|vh|vmin|vmax)$", re.I)
_REFERENCE = re.compile(r"url\(#([^)]*)\)")


def svg_namespace(owner, digest: str, view: str) -> str:
    """Use stable non-link scene paths for placed artwork."""
    path = []
    node = owner
    while node._parent is not None:
        parent = node._parent
        siblings = (child for child in parent.children if child.component_type not in _LINK_TYPES)
        path.append(str(next(index for index, child in enumerate(siblings) if child is node)))
        node = parent
    slot = "-".join(reversed(path)) or "single"
    return f"odpart-{view}-{digest}-{slot}"


def resolved_root(root: ET.Element, view_box, *, namespace: str | None = None) -> ET.Element:
    """Resolve relative lengths in their original SVG viewport."""
    def length(value: str, basis: float, node: ET.Element, attribute: str, object_box: bool) -> str:
        value = value.strip()
        name = f"SVG {node.tag}.{attribute}"
        if _RELATIVE_UNIT.search(value):
            raise ValueError(f"{name}: unsupported relative dimension {value!r}")
        if "%" not in value:
            return value
        if not value.endswith("%") or object_box:
            raise ValueError(f"{name}: unsupported relative dimension {value!r}")
        try:
            number = float(value[:-1]) * basis / 100
        except ValueError as error:
            raise ValueError(f"{name}: invalid relative dimension {value!r}") from error
        if not math.isfinite(number):
            raise ValueError(f"{name}: non-finite relative dimension")
        return repr(number)

    def visit(node: ET.Element, width: float, height: float, *, outer=False, object_box=False):
        object_box = object_box or node.attrib.get("clipPathUnits") == "objectBoundingBox"
        diagonal = math.hypot(width, height) / math.sqrt(2)
        for attribute, value in list(node.attrib.items()):
            if attribute in _X_LENGTHS:
                node.set(attribute, length(value, width, node, attribute, object_box))
            elif attribute in _Y_LENGTHS:
                node.set(attribute, length(value, height, node, attribute, object_box))
            elif attribute in _OTHER_LENGTHS:
                node.set(attribute, length(value, diagonal, node, attribute, object_box))
            elif attribute == "stroke-dasharray" and value != "none":
                values = re.split(r"[\s,]+", value.strip())
                node.set(attribute, " ".join(length(item, diagonal, node, attribute, object_box) for item in values))
            elif attribute in _OPACITIES and "%" in value:
                node.set(attribute, length(value, 1, node, attribute, False))
            elif attribute in {"transform", "points", "d"} and "%" in value:
                raise ValueError(f"SVG {node.tag}.{attribute}: unsupported relative dimension")
        if node.tag == "svg" and not outer:
            if "viewBox" in node.attrib:
                try:
                    box = [float(value) for value in re.split(r"[\s,]+", node.attrib["viewBox"].strip())]
                    if len(box) != 4 or not all(math.isfinite(value) for value in box) or min(box[2:]) <= 0:
                        raise ValueError
                except ValueError as error:
                    raise ValueError("SVG svg.viewBox: invalid nested viewport") from error
                width, height = box[2:]
            else:
                try:
                    width = float(node.attrib.get("width", width))
                    height = float(node.attrib.get("height", height))
                except ValueError as error:
                    raise ValueError("SVG svg: nested viewport requires numeric dimensions or a viewBox") from error
        for child in node:
            visit(child, width, height, object_box=object_box)

    visit(root, view_box[2], view_box[3], outer=True)
    if namespace is not None:
        identifiers = [node.attrib["id"] for node in root.iter() if "id" in node.attrib]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("SVG id: duplicate identifiers in one asset")
        renamed = {identifier: f"{namespace}-{identifier}" for identifier in identifiers}
        for node in root.iter():
            for attribute, value in list(node.attrib.items()):
                if attribute == "id":
                    node.set(attribute, renamed[value])
                else:
                    node.set(attribute, _REFERENCE.sub(lambda match: f"url(#{renamed.get(match[1], match[1])})", value))
    return root
