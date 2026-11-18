"""Every on-chip part draws its waveguide ports at the schematic guide width, so the guides of a schematic meet.

Fourteen parts drew 0.5 um guides in a schematic beside the 1.2 of the rest (a PresetWDMInput 0.7): their families
in schematic_tables.py held only the thickness, and the classes read ``self.waveguide_width`` or ``self.width`` in
place of ``self._draw(...)``. A route between two of them tapered at each joint. A part drawn physical keeps the
true widths.
"""

from __future__ import annotations

import pytest

from optodraw.components.onchip.schematic_tables import SCHEMATIC_TABLES
from optodraw.registry import build_component, component_registry

_NO_GUIDE = {"TIA", "ADC", "DACDriver", "ChipSubstrate", "GDSModel", "CustomModel", "Route"}
# A port that is not the part's guide: the wide end of a taper.
_NOT_THE_GUIDE = {("Taper", "o2")}
PARTS = sorted(name for name, spec in component_registry().items()
               if spec.category == "on_chip" and name not in _NO_GUIDE)
SHARED = SCHEMATIC_TABLES["_shared"]["waveguide_width"]


@pytest.mark.parametrize("name", ["WaveguideBend", "TapCoupler", "AdiabaticCoupler",
                                  "PolarizationSplitterRotator", "TwoDGratingCoupler", "Taper", "Terminator"])
def test_the_drawn_guide_is_as_wide_as_its_port(name):
    """The 2D drawing ends at each port as wide as the port says: a port on a narrower drawn guide hid a step."""

    from shapely.geometry import Point, Polygon

    part = build_component(name)

    def polygons(node):
        if node.get("type") == "group":
            for child in node.get("children", []):
                yield from polygons(child)
        elif node.get("type") == "polygon" and len(node.get("points") or []) >= 3:
            yield Polygon([p[:2] for p in node["points"]]).buffer(0)

    drawn = list(polygons(part.geometry_2d()))
    for key, port in part.ports().items():
        if port.kind != "optical" or (name, key) in _NOT_THE_GUIDE:
            continue
        normal = port.normal()
        x, y = port.center.x - normal.x * 0.05, port.center.y - normal.y * 0.05      # just inside the part
        half = float(port.width) / 2.0 * 0.9
        for side in (1.0, -1.0):
            edge = Point(x - normal.y * half * side, y + normal.x * half * side)
            assert any(p.buffer(1e-6).contains(edge) for p in drawn), f"{name} {key}: the drawn guide is narrower"
