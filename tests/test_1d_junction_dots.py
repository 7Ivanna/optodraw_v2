"""A dot marks where wires of one node join, as in KiCad: three or more branches meet at a point (a T, or two
wires leaving one pin). Wires that only cross carry no dot, so a crossing never reads as a connection."""

import re

from optodraw.notebook_1d import schematic_body
from optodraw.symbols.schematic import Link, Schematic, build_schematic, junctions
from optodraw.symbols.tikz_export import render_tikz_1d
from test_1d_wires_line_up import _docs_tia, _tia_circuit


def _wires(routes, ports):
    """A schematic of bare wires: ``ports`` gives each wire's two (part, port) ends, ``routes`` its polyline."""

    links = [Link(a[0], a[1], b[0], b[1], "electrical") for a, b in ports]
    return Schematic([], links, 0, 100.0, 100.0, routes=dict(enumerate(routes)))


def test_a_wire_that_meets_another_of_its_node_in_a_t_gets_a_dot():
    # two wires into one pin (part 2, port "in"): one along the run, one that joins it from above
    schematic = _wires([[(0.0, 50.0), (60.0, 50.0)], [(30.0, 10.0), (30.0, 50.0), (60.0, 50.0)]],
                       [((0, "o"), (2, "in")), ((1, "o"), (2, "in"))])
    assert junctions(schematic) == [(30.0, 50.0)]


def test_two_wires_of_different_nodes_cross_with_no_dot():
    """Even where one of them has a point of its route on the other: only wires of one node join."""

    schematic = _wires([[(0.0, 50.0), (60.0, 50.0)], [(30.0, 10.0), (30.0, 50.0), (30.0, 90.0)]],
                       [((0, "o"), (2, "in")), ((1, "o"), (3, "in"))])
    assert junctions(schematic) == []


def test_two_wires_that_leave_one_pin_apart_get_a_dot_at_the_pin():
    schematic = _wires([[(50.0, 50.0), (50.0, 10.0)], [(50.0, 50.0), (90.0, 50.0)]],
                       [((0, "e"), (1, "a")), ((0, "e"), (2, "a"))])
    assert junctions(schematic) == [(50.0, 50.0)]


def test_one_wire_into_a_pin_and_a_corner_get_no_dot():
    schematic = _wires([[(0.0, 50.0), (30.0, 50.0), (30.0, 10.0)]], [((0, "o"), (1, "in"))])
    assert junctions(schematic) == []


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
