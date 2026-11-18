"""A cable on a bench has one width and a neutral colour; chip metal keeps its design widths."""

import math

import pytest

import optodraw
from optodraw.core.routing import CABLE_COLOR, CABLE_WIDTH, route_ports


def _wire(a, b, **options):
    port_a = next(name for name, port in a.ports().items() if port.kind == "electrical")
    port_b = next(name for name, port in b.ports().items() if port.kind == "electrical")
    return route_ports((a, port_a), (b, port_b), kind="electrical", **options)


@pytest.mark.parametrize("a, b", [
    (optodraw.WaveformGenerator(center=(0, 0)), optodraw.Oscilloscope(center=(120, 40))),   # 1.8-wide jacks
    (optodraw.Resistor(center=(0, 0)), optodraw.Capacitor(center=(60, 30))),                # 0.48-wide leads
    (optodraw.PCB(center=(0, 0)), optodraw.Oscilloscope(center=(150, 0))),                 # 4.0-wide edge pads
])
def test_a_bench_cable_takes_one_width_and_a_neutral_colour(a, b):
    """A cable took the narrower port's width, so instrument cables drew four times a circuit wire, and drew in the
    red of red light."""

    cable = _wire(a, b)
    assert (cable.width, cable.width2, cable.color) == (CABLE_WIDTH, None, CABLE_COLOR)
    assert CABLE_COLOR.lower() not in ("#b24b4b", "#e79d1a")


def _bench():
    """A modulator driven by a generator and a detector read by a scope: the instruments' jacks face down."""

    scene = optodraw.Scene(title="", width=200, height=110, platform="free_space")
    laser = scene.add(optodraw.Laser(center=(-80, 25), label="Laser"))
    eom = scene.add(optodraw.EOM(center=(-30, 25), label="EOM"))
    pd = scene.add(optodraw.Photodiode(center=(40, 25), label="PD"))
    scene.add(optodraw.Beam.through(laser, eom, pd))
    gen = scene.add(optodraw.WaveformGenerator(center=(-30, -28), label="Generator"))
    scope = scene.add(optodraw.Oscilloscope(center=(50, -28), label="Scope"))
    cables = [scene.route((gen, "sync"), (eom, "rf"), kind="electrical"),
              scene.route((pd, "e1"), (scope, "ch1"), kind="electrical"),
              scene.route((gen, "out2"), (scope, "usb"), kind="electrical")]
    return scene, [laser, eom, pd, gen, scope], cables


def _inside(points, box, step=0.25):
    """The points along a polyline that lie strictly inside ``box``."""

    x0, y0, x1, y1 = box
    out = []
    for (ax, ay), (bx, by) in zip(points, points[1:]):
        n = max(1, int(((bx - ax) ** 2 + (by - ay) ** 2) ** 0.5 / step))
        out += [(ax + (bx - ax) * k / n, ay + (by - ay) * k / n) for k in range(n + 1)]
    return [(x, y) for x, y in out if x0 < x < x1 and y0 < y < y1]


def test_a_bench_cable_has_no_short_jog():
    """Between an instrument's corner and a modulator, a gap narrower than the grid pitch made a cable step two
    units sideways and on: a jog that reads as a mistake."""

    scene = optodraw.Scene(title="", width=320, height=200, platform="free_space")
    eoms = [scene.add(optodraw.EOM(center=(-120 + 60 * i, 50), label=f"EOM{i}")) for i in range(4)]
    kinds = (optodraw.Oscilloscope, optodraw.WaveformGenerator)
    instruments = [scene.add(kinds[i % 2](center=(-130 + 52 * i, -60), label=f"I{i}")) for i in range(6)]

    def jack(part, k=0):
        names = [name for name, port in part.ports().items() if port.kind == "electrical"]
        return names[k % len(names)]

    cables = []
    for i in range(10):
        far = (eoms[i % 4], "rf") if i < 4 else (instruments[(i + 2) % 6], jack(instruments[(i + 2) % 6], 1))
        cables.append(scene.route((instruments[i % 6], jack(instruments[i % 6], i // 6)), far, kind="electrical"))
    for cable in cables:
        p = [(float(q.x), float(q.y)) for q in cable.points]
        for a, b, c, d in zip(p, p[1:], p[2:], p[3:]):
            same_way = ((b[0] - a[0]) * (d[0] - c[0]) > 0 and a[1] == b[1] and c[1] == d[1]
                        or (b[1] - a[1]) * (d[1] - c[1]) > 0 and a[0] == b[0] and c[0] == d[0])
            assert not (same_way and math.dist(b, c) < 3.0), (cable.end_port, p)
