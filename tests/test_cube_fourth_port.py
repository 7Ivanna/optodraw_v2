"""A cube beam splitter has four faces: light that enters by the fourth (tap) can recombine two beams."""

from __future__ import annotations


from optodraw import (PBS)


def test_a_polarizing_cube_routes_light_from_its_tap_face():
    from optodraw.animation_engine.behaviours import find_behaviour

    behaviour = find_behaviour(PBS())
    routes = {(t.in_port, t.out_port) for port in ("tap", "trans", "refl")
              for t in behaviour.transfers(PBS(), "pbs1", port, 1550.0, {})}
    assert {("tap", "refl"), ("tap", "trans"), ("trans", "tap"), ("refl", "tap")} <= routes


