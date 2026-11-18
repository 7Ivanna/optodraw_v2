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


@pytest.mark.parametrize("other", [optodraw.PhaseShifter(center=(200, 0)), optodraw.HeaterPad(center=(200, 0))])
def test_chip_metal_keeps_its_port_width_and_colour(other):
    """A pad and a heater pad have no chip thickness: the registry names them chip parts."""

    pad = optodraw.ElectricalPad(center=(0, 0))
    metal = _wire(pad, other)
    widths = [p.width for p in (*pad.ports().values(), *other.ports().values()) if p.kind == "electrical"]
    assert metal.width in widths and metal.width != CABLE_WIDTH and metal.color != CABLE_COLOR


def test_a_cable_keeps_the_width_and_colour_it_is_given():
    cable = _wire(optodraw.WaveformGenerator(center=(0, 0)), optodraw.Oscilloscope(center=(120, 40)),
                  width=1.2, color="#cc0000")
    assert (cable.width, cable.color) == (1.2, "#cc0000")


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


def test_a_bench_cable_runs_round_every_part_and_label():
    """A cable ran up through the generator and the modulator, and down through the scope."""

    from optodraw.check import _label_box

    _, parts, cables = _bench()
    for cable in cables:
        points = [(float(p.x), float(p.y)) for p in cable.points]
        ends = (cable.start_component, cable.end_component)
        for part in parts:
            run = points[1:-1] if part in ends else points          # a cable reaches into its own part's port
            assert not _inside(run, part.drawn_box()), (cable.start_port, cable.end_port, part.label)
            if part.label != "EOM":                     # its RF port faces its label: check_figure reports that one
                assert not _inside(points, _label_box(part, 8.0)), (cable.start_port, part.label)


def test_a_bench_cable_leaves_and_meets_each_port_square():
    """The modulator's RF port faces up: the cable met it from below, through the crystal."""

    _, _, cables = _bench()
    for cable in cables:
        for port, (a, b) in ((cable.start_component.world_port(cable.start_port), cable.points[:2]),
                             (cable.end_component.world_port(cable.end_port), cable.points[-1:-3:-1])):
            facing = (round(math.cos(math.radians(port.orientation_deg))), round(math.sin(math.radians(port.orientation_deg))))
            run = (float(b.x - a.x), float(b.y - a.y))
            assert run[0] * facing[0] + run[1] * facing[1] > 0 and abs(run[0] * facing[1] - run[1] * facing[0]) < 1e-9


def test_two_bench_cables_keep_a_track_apart():
    _, _, cables = _bench()
    runs = [[(float(a.x), float(a.y), float(b.x), float(b.y)) for a, b in zip(c.points, c.points[1:])] for c in cables]
    for i, mine in enumerate(runs):
        for theirs in runs[i + 1:]:
            for ax, ay, bx, by in mine:
                for cx, cy, dx, dy in theirs:
                    if ay == by and cy == dy:                       # two horizontal runs over one stretch
                        overlap = min(max(ax, bx), max(cx, dx)) - max(min(ax, bx), min(cx, dx))
                        assert overlap <= 0 or abs(ay - cy) >= 1.5
                    if ax == bx and cx == dx:
                        overlap = min(max(ay, by), max(cy, dy)) - max(min(ay, by), min(cy, dy))
                        assert overlap <= 0 or abs(ax - cx) >= 1.5


def test_bench_cables_draw_under_the_parts():
    """A cable drawn over the parts hid their connectors; under them, its end goes under the jack."""

    scene, _, _ = _bench()
    svg = scene.render_svg()
    svg = svg if isinstance(svg, str) else svg.as_svg()
    last_cable = svg.rindex(f'stroke="{CABLE_COLOR}" fill="none" stroke-width="{CABLE_WIDTH}"')
    assert last_cable < svg.index('data-art="')
    lines = scene.render_tikz().split("\\begin{tikzpicture}[x=1pt", 1)[1].splitlines()
    cables = [i for i, line in enumerate(lines) if line.startswith(f"\\draw[line width={CABLE_WIDTH:.3f}pt")]
    parts = [i for i, line in enumerate(lines) if "\\pic[" in line]
    assert len(cables) == 3 and max(cables) < min(parts)


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
