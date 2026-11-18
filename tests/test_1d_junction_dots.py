"""A dot marks where wires of one node join, as in KiCad: three or more branches meet at a point (a T, or two
wires leaving one pin). Wires that only cross carry no dot, so a crossing never reads as a connection."""

import re

from optodraw.notebook_1d import schematic_body
from optodraw.symbols.schematic import build_schematic, junctions
from optodraw.symbols.tikz_export import render_tikz_1d
from test_1d_wires_line_up import _docs_tia, _tia_circuit


def test_each_amplifier_node_shows_its_dots_in_every_drawing():
    """The feedback loop joins the input node and the output node: each join has a dot, in the SVG and in TikZ."""

    for scene in (_tia_circuit(), _docs_tia()):
        schematic = build_schematic(scene)
        dots = junctions(schematic)
        assert len(dots) >= 2
        body = schematic_body(schematic)
        assert len(re.findall(r'<circle class="od1-junction"', body)) == len(dots)
        tikz = render_tikz_1d(scene)
        assert tikz.count("\\fill[black!65]") == len(dots)
