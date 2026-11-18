"""A short route between two close parts draws no spur at a port.

The measure reads the route's path as the 2D SVG draws it. At each port the path must leave forward and arrive from in
front: the first leg points along the start port's outward normal (dot product > 0) and the last leg against the end
port's (dot product < 0). Between the ports no corner turns more than 90 degrees: a sharper turn runs the path back over
the line it just drew, and the part it runs back over is the spur.
"""

import math
import re
import xml.etree.ElementTree as ET

import pytest

from optodraw import ElectricalPad, Scene, Waveguide
from optodraw.core.transform import Vec3

SVG = "{http://www.w3.org/2000/svg}"


def _place(scene, part, port, xy):
    """Add ``part`` and move it so its ``port`` lies at ``xy``."""

    scene.add(part)
    at = part.world_port(port).center
    part.transform.position = part.transform.position + (Vec3(xy[0], xy[1], 0.0) - at)
    return part


def _drawn_path(scene, route):
    """The route's polyline as the 2D SVG draws it, in world units (y up)."""

    root = ET.fromstring(scene.render_svg().as_svg())
    paths = [p for p in root.iter(f"{SVG}path") if p.get("stroke") == route.color and p.get("fill") == "none"]
    assert len(paths) == 1, f"expected one drawn path in {route.color}, found {len(paths)}"
    numbers = [float(v) for v in re.findall(r"-?\d+(?:\.\d+)?(?:e-?\d+)?", paths[0].get("d"))]
    points = []
    for x, y in zip(numbers[::2], numbers[1::2]):
        if not points or math.dist(points[-1], (x, -y)) > 1e-9:
            points.append((x, -y))
    return points


def _unit(p, q):
    d = math.dist(p, q)
    return ((q[0] - p[0]) / d, (q[1] - p[1]) / d)


def _spurs(scene, route):
    points = _drawn_path(scene, route)
    n1 = route.start_component.world_port(route.start_port).normal()
    n2 = route.end_component.world_port(route.end_port).normal()
    found = []
    first, last = _unit(points[0], points[1]), _unit(points[-2], points[-1])
    if first[0] * n1.x + first[1] * n1.y <= 1e-6:
        found.append(f"leaves {route.start_port} backward or sideways")
    if last[0] * n2.x + last[1] * n2.y >= -1e-6:
        found.append(f"enters {route.end_port} from behind or the side")
    for p, q, r in zip(points, points[1:], points[2:]):
        a, b = _unit(p, q), _unit(q, r)
        if a[0] * b[0] + a[1] * b[1] < -1e-6:
            spur = min(math.dist(p, q), math.dist(q, r))
            found.append(f"runs back over itself at ({q[0]:.2f}, {q[1]:.2f}): a {spur:.2f} um spur")
    return points, found


# Each layout: (start part, start port, its point), (end part, end port, its point). Points in um.
def _pads(start_angle, start_xy, end_angle, end_xy):
    def build(scene):
        a = _place(scene, ElectricalPad(width=4, height=4, angle=start_angle), "e1", start_xy)
        b = _place(scene, ElectricalPad(width=4, height=4, angle=end_angle), "e1", end_xy)
        return (a, "e1"), (b, "e1")
    return build


def _guides(start_angle, start_port, start_xy, end_angle, end_port, end_xy):
    def build(scene):
        a = _place(scene, Waveguide(length=20, angle=start_angle), start_port, start_xy)
        b = _place(scene, Waveguide(length=20, angle=end_angle), end_port, end_xy)
        return (a, start_port), (b, end_port)
    return build


FACING_PADS = _pads(180, (0.0, 0.0), 0, (5.0, 3.0))           # east-facing port, a west-facing one 5 right, 3 up
UP_TURN_PADS = _pads(180, (0.0, 0.0), 90, (20.0, 3.0))        # the end port faces down, 3 above the start's line
SAME_SIDE_PADS = _pads(0, (0.0, 6.6), 0, (-1.2, 0.0))         # both face west: the TIA's feedback resistor to in-
DOWN_THEN_RIGHT_PADS = _pads(90, (0.0, 0.0), 0, (35.0, 11.4))  # a south-facing port to a west one above: the TIA's PD
FACING_GUIDES = _guides(0, "o2", (0.0, 0.0), 0, "o1", (5.0, 3.0))
UP_TURN_GUIDES = _guides(0, "o2", (0.0, 0.0), 90, "o1", (20.0, 3.0))

CASES = [
    ("electrical", "manhattan", FACING_PADS),
    ("electrical", "manhattan", SAME_SIDE_PADS),
    ("electrical", "manhattan", DOWN_THEN_RIGHT_PADS),
    ("electrical", "L", FACING_PADS),
    ("electrical", "L", UP_TURN_PADS),
    ("electrical", "straight", FACING_PADS),
    ("electrical", "smooth", FACING_PADS),
    ("waveguide", "manhattan", FACING_GUIDES),
    ("waveguide", "L", UP_TURN_GUIDES),
    ("waveguide", "straight", UP_TURN_GUIDES),
    ("waveguide", "smooth", FACING_GUIDES),
]
IDS = ["electrical-manhattan-facing", "electrical-manhattan-same-side", "electrical-manhattan-down-then-right",
       "electrical-L-facing", "electrical-L-up-turn", "electrical-straight-facing", "electrical-smooth-facing",
       "waveguide-manhattan-facing", "waveguide-L-up-turn", "waveguide-straight-up-turn", "waveguide-smooth-facing"]


@pytest.mark.filterwarnings("ignore::UserWarning")      # a waveguide manhattan route first asks gdsfactory, which refuses
@pytest.mark.parametrize(("kind", "path_type", "layout"), CASES, ids=IDS)
def test_a_short_route_draws_no_spur_at_a_port(kind, path_type, layout):
    scene = Scene(title="", platform="on_chip")
    start, end = layout(scene)
    route = scene.route(start, end, kind=kind, path_type=path_type)
    points, found = _spurs(scene, route)
    assert not found, f"{kind} {path_type}: {found}; drawn path {[(round(x, 2), round(y, 2)) for x, y in points]}"


