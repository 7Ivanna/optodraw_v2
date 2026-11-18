"""A KLayout layer-properties file (.lyp) written from layer styles.

The layout view takes its layer colours and names from the part's layer stack, so it can never disagree with
the 3D view or the top view of the same part. GDS Lens reads `name`, `fill-color`, `frame-color` and `visible`
from a .lyp; KLayout reads the same fields.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections.abc import Mapping
from typing import Any


def _spec(key: Any) -> tuple[int, int] | None:
    if isinstance(key, (tuple, list)) and len(key) >= 2:
        return int(key[0]), int(key[1])
    if isinstance(key, str) and "/" in key:
        layer, datatype = key.split("/", 1)
        if layer.strip().isdigit() and datatype.strip().isdigit():
            return int(layer), int(datatype)
    return None


def stack_to_lyp(styles: Mapping[Any, Mapping[str, Any]]) -> str:
    """The .lyp text for ``styles`` (keys ``(layer, datatype)`` or ``"L/D"``): per layer its name, fill colour
    (``color``), frame colour (``stroke``, else ``color``) and visibility, sorted by layer. A layer with no
    colour is left out."""

    root = ET.Element("layer-properties")
    layers = sorted((spec, style) for spec, style in ((_spec(key), style) for key, style in styles.items())
                    if spec is not None and style.get("color"))
    for (layer, datatype), style in layers:
        properties = ET.SubElement(root, "properties")
        for tag, value in (("frame-color", style.get("stroke") or style["color"]),
                           ("fill-color", style["color"]),
                           ("visible", "false" if style.get("visible") is False else "true"),
                           ("name", str(style.get("name") or f"{layer}/{datatype}")),
                           ("source", f"{layer}/{datatype}@1")):
            ET.SubElement(properties, tag).text = str(value)
    ET.indent(root, space=" ")
    return '<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(root, encoding="unicode") + "\n"
