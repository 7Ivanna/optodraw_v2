"""A chip's 1D view routes its links as on a chip: square turns round the symbols, never two on one track."""

from __future__ import annotations


from optodraw import presets
from optodraw.symbols.router import route_links
from optodraw.symbols.schematic import build_schematic, link_path

CHIPS = ["coherent_receiver_chip", "wdm_delay_weight_bank_chip", "ring_resonator_chip", "mzm_mesh_chip"]


def _schematic(name):
    return build_schematic(getattr(presets, name)())


def _segments(route):
    return list(zip(route, route[1:]))


def test_a_bench_keeps_its_straight_beams():
    schematic = build_schematic(presets.confocal_pl_setup())
    assert not any(link.kind == "free_space" and i in schematic.routes for i, link in enumerate(schematic.links))


def test_link_path_gives_the_route_or_the_curve():
    schematic = _schematic("coherent_receiver_chip")
    index = next(iter(schematic.routes))
    assert link_path(schematic, index) == list(schematic.routes[index])


def _corners(route):
    return sum(1 for a, b, c in zip(route, route[1:], route[2:])
               if abs((b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])) > 1e-6)


FAR = ((-90, -90, -80, -80), (300, 300, 310, 310))     # the link's own two parts, out of the way


def test_the_guided_dogleg_and_the_guide_as_drawn():
    from optodraw.symbols.router import _as_drawn, _guided

    guide = [(0, 0), (20, 0), (20, 10), (40, 10), (40, 50), (100, 50)]
    assert _guided((0, 0), (1, 0), (100, 50), (-1, 0), guide, [], FAR, []) == [(0, 0), (20, 0), (20, 50), (100, 50)]
    assert _guided((0, 0), (1, 0), (100, 50), (-1, 0), guide, [(15, 20, 25, 30)], FAR, []) is None   # a part in the way
    assert _guided((0, 0), (1, 0), (100, 50), (0, -1), guide, [], FAR, []) is None   # the ports do not face each other
    assert _guided((0, 0), (1, 0), (100, 50), (-1, 0), guide, [], FAR, [[(20, -10), (20, 60)]]) is None   # on a track
    detour = [(0, 0), (20, 0), (20, -40), (80, -40), (80, 50), (100, 50)]          # the 2D route goes away first
    assert _guided((0, 0), (1, 0), (100, 50), (-1, 0), detour, [], FAR, []) is None
    assert _as_drawn((0, 0), (1, 0), (100, 50), (-1, 0), guide, [], FAR, []) == guide
    assert _as_drawn((0, 0), (1, 0), (100, 50), (-1, 0), guide, [], (FAR[0], (30, 5, 50, 15)), []) is None
    assert _as_drawn((0, 0), (1, 0), (100, 50), (-1, 0), [(0, 0), (20, 0), (30, 50), (100, 50)], [], FAR, []) is None
    assert _as_drawn((0, 0), (1, 0), (100, 50), (-1, 0), guide, [], FAR, [[(60, 40), (60, 60)], [(-5, 50), (200, 50)]]) is None


def _fake_item(x, y, w, h, ports):
    from types import SimpleNamespace

    symbol = SimpleNamespace(width=w, height=h, ports={name: SimpleNamespace(x=px, y=py, side=side)
                                                       for name, (px, py, side) in ports.items()})
    item = SimpleNamespace(x=x, y=y, symbol=symbol, label="", label_at=None)
    item.port = lambda name: ((x + symbol.ports[name].x, y + symbol.ports[name].y, symbol.ports[name].side)
                              if name in symbol.ports else None)
    return item


def test_a_simpler_route_that_crosses_a_drawn_link_is_refused():
    """B sits under and to the right of A, and a short link P-Q runs across the way. The 2D route goes round Q;
    its first turn would give a dogleg straight across P-Q. The route keeps to the guide and crosses nothing."""

    from types import SimpleNamespace

    from optodraw.check import _crosses

    items = [_fake_item(0, 0, 20, 20, {"o": (20, 10, "right")}), _fake_item(100, 60, 20, 20, {"i": (0, 10, "left")}),
             _fake_item(25, 35, 7, 10, {"o": (7, 5, "right")}), _fake_item(48, 35, 7, 10, {"i": (0, 5, "left")})]
    links = [SimpleNamespace(start=0, end=1, start_port="o", end_port="i", kind="waveguide", electrical=False),
             SimpleNamespace(start=2, end=3, start_port="o", end_port="i", kind="waveguide", electrical=False)]
    schematic = SimpleNamespace(items=items, links=links, width=140, height=100)
    guide = [(20, 10), (40, 10), (40, 25), (70, 25), (70, 70), (100, 70)]
    routes = route_links(schematic, {0: guide})
    assert routes[1] == [(32, 40), (48, 40)]
    assert not any(_crosses(p, q) for p in _segments(routes[0]) for q in _segments(routes[1])), routes[0]
