"""A route must not wander. The measure is its length against the direct line.

Two bugs hid here, and neither showed up in a total-length check over a scene,
because component internals dominate that sum. Both show immediately in the
ratio of one route's drawn length to the straight-line distance between the two
ports it joins.

1. ``path_type="smooth"`` was handed to gdsfactory's Manhattan router, which
   cannot draw a smooth path. It came back with right angles at 3.3x direct.
2. The default 10 um bend radius does not fit between ports 10 um apart in y: a
   90 degree bend eats the radius in both axes and a Manhattan link needs two.
   gdsfactory does not refuse, it loops around and returns, which drew a 120 um
   route between ports 31 um apart, dipping 20 um below both of them.
"""

from __future__ import annotations

import math

import pytest

from optodraw import Waveguide, route_ports

PORT_PAIRS = [((0, 0), (50, 10)), ((0, 0), (60, 40)), ((0, 0), (120, 5)), ((0, 0), (30, 60))]


def _ratio(route) -> float:
    points = [(p.x, p.y) for p in route.points]
    drawn = sum(math.dist(a, b) for a, b in zip(points, points[1:]))
    return drawn / max(math.dist(points[0], points[-1]), 1e-9)


def _route(start, end, **kwargs):
    left = Waveguide(center=start, length=20, width=0.5)
    right = Waveguide(center=end, length=20, width=0.5)
    return route_ports((left, "o2"), (right, "o1"), **kwargs)


@pytest.mark.parametrize("start, end", PORT_PAIRS)
def test_a_manhattan_route_does_not_loop_around(start, end):
    ratio = _ratio(_route(start, end, path_type="manhattan"))
    assert ratio < 1.6, f"drawn path is {ratio:.2f}x the direct distance: it is detouring"


@pytest.mark.parametrize("start, end", PORT_PAIRS)
def test_a_smooth_route_is_smooth(start, end):
    route = _route(start, end, path_type="smooth")
    assert route.backend == "local", "the Manhattan router cannot draw a smooth path"
    assert _ratio(route) < 1.3


def test_the_bend_radius_is_fitted_to_the_gap():
    """Ports close together in one axis get a radius that fits between them."""

    tight = _route((0, 0), (50, 10), path_type="manhattan")
    assert tight.bend_radius <= 5.0 + 1e-6
    roomy = _route((0, 0), (60, 40), path_type="manhattan")
    assert roomy.bend_radius >= tight.bend_radius


def test_an_explicit_backend_is_still_honoured():
    assert _route((0, 0), (60, 40), path_type="manhattan", backend="local").backend == "local"


def _sharpest_turn_deg(route) -> float:
    points = [(p.x, p.y) for p in route.points]
    legs = [(b[0] - a[0], b[1] - a[1]) for a, b in zip(points, points[1:]) if math.dist(a, b) > 1e-9]
    turns = [abs(math.degrees(math.atan2(u[0] * v[1] - u[1] * v[0], u[0] * v[0] + u[1] * v[1])))
             for u, v in zip(legs, legs[1:])]
    return max(turns, default=0.0)


@pytest.mark.parametrize("turn", [-55.0, -35.0, 40.0])
def test_a_smooth_route_leaves_a_skewed_port_without_a_corner(turn):
    """An AWG aperture faces along its arc, up to 60 degrees off the line to its detector. The S-bend left along the
    axis while its lead ran along the port: a 52 degree corner at the end of the lead."""

    aperture = Waveguide(center=(0, 0), length=20, width=0.5, angle=turn)
    detector = Waveguide(center=(90, 40 * math.copysign(1.0, turn)), length=20, width=0.5)
    route = route_ports((aperture, "o2"), (detector, "o1"), path_type="smooth")
    assert _sharpest_turn_deg(route) < 12.0
    assert _tightest_radius(route) >= route.bend_radius - 1e-6, "and it keeps its bend radius on the way"


def _tightest_radius(route) -> float:
    points = [(p.x, p.y) for p in route.points]
    radii = [math.inf]
    for a, b, c in zip(points, points[1:], points[2:]):
        twice_area = abs((b[0] - a[0]) * (c[1] - a[1]) - (c[0] - a[0]) * (b[1] - a[1]))
        if twice_area > 1e-9:
            radii.append(math.dist(a, b) * math.dist(b, c) * math.dist(a, c) / (2.0 * twice_area))
    return min(radii)


def test_the_awg_input_meets_its_port_head_on():
    """i1 faces -x, but the drawn input ran on along its aperture's tilt to the port: every bus met it at a corner."""

    from optodraw import AWG

    awg = AWG(channel_count=4, array_count=8)
    port = awg.ports()["i1"]
    (x0, y0), (x1, y1) = awg.optical_paths("i1")[0]["pts"][:2]
    assert (x0, y0) == pytest.approx((port.center.x, port.center.y))
    leaving = math.degrees(math.atan2(y1 - y0, x1 - x0))       # into the part: opposite the port's outward face
    assert abs((leaving - (port.orientation_deg + 180.0) + 180.0) % 360.0 - 180.0) < 5.0   # a chord: half a step off
