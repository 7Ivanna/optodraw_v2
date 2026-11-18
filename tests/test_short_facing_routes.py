"""Two ports that face each other in line, closer than their lead stubs, join with one straight run; two ports
at a right angle join with one bend; no route steps back on itself."""

import math

import pytest

from optodraw import ElectricalPad, Scene


@pytest.mark.parametrize("path_type", ["straight", "L", "manhattan"])
def test_a_short_wire_between_facing_ports_does_not_double_back(path_type):
    scene = Scene(title="", width=60, height=40, platform="on_chip")
    a = scene.add(ElectricalPad(center=(0, 0), width=4, height=4, angle=180, label=""))    # port faces east
    b = scene.add(ElectricalPad(center=(10, 0), width=4, height=4, angle=0, label=""))     # port faces west
    route = scene.route((a, "e1"), (b, "e1"), kind="electrical", path_type=path_type)
    points = [(float(p[0]), float(p[1])) for p in route.resolve_points()]
    length = sum(math.dist(p, q) for p, q in zip(points, points[1:]))
    assert length == pytest.approx(math.dist(points[0], points[-1]), abs=1e-6)


def _points(route):
    return [(float(p[0]), float(p[1])) for p in route.resolve_points()]


def _fibre_to_snspd(rise):
    from optodraw import FiberPort, SNSPD

    scene = Scene(title="", width=80, height=40, platform="free_space")
    fib = scene.add(FiberPort(center=(0, 0), angle=90, label=""))        # out faces up, at y = 4.5
    snspd = scene.add(SNSPD(center=(27, 4.5 + rise), length=24, label=""))   # in faces left, at x = 15
    return scene.route((fib, "out"), (snspd, "in"), kind="fiber", path_type="manhattan", width=0.4)


@pytest.mark.parametrize("rise", [4.0, 20.0])
def test_ports_at_a_right_angle_join_with_one_bend(rise):
    """Sahoo's fibre went up 5, back 0.5, right, down 0.5 and right: a jog where one bend is enough."""

    points = _points(_fibre_to_snspd(rise))
    assert points == [pytest.approx((0.0, 4.5)), pytest.approx((0.0, 4.5 + rise)), pytest.approx((15.0, 4.5 + rise))]


def test_a_route_with_steps_does_not_step_back_at_its_port():
    """Sahoo's sync cable ran down to the port's level 1 unit short of the port's lead, went back 1 and then
    forward 5 into the port."""

    scene = Scene(title="", width=60, height=40, platform="on_chip")
    a = scene.add(ElectricalPad(center=(0, 0), width=4, height=4, angle=180, label=""))    # port faces east
    b = scene.add(ElectricalPad(center=(30, -10), width=4, height=4, angle=0, label=""))   # port faces west
    xb = float(b.world_ports()["e1"].center.x)
    route = scene.route((a, "e1"), (b, "e1"), kind="electrical", path_type="manhattan",
                        steps=[{"x": 10.0}, {"y": 10.0}, {"x": xb - 4.0}, {"y": -10.0}])
    points = _points(route)
    turns = [(q[0] - p[0]) * (r[0] - q[0]) + (q[1] - p[1]) * (r[1] - q[1]) for p, q, r in zip(points, points[1:], points[2:])]
    lengths = [math.dist(p, q) * math.dist(q, r) for p, q, r in zip(points, points[1:], points[2:])]
    assert all(turn > -0.999 * length for turn, length in zip(turns, lengths)), points
