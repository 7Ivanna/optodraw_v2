"""A Glan-Laser polarizer: p goes straight on, s leaves through the side window at the angle the prism sets."""

from __future__ import annotations

import numpy as np
import pytest

from optodraw import GlanLaserPolarizer, Scene
from optodraw.animation_engine.behaviours.polarisation import GlanPrism
from optodraw.schema import scene_from_spec, scene_to_spec
from optodraw.symbols import lookup
from optodraw.symbols.art import symbol_for_2d


def test_its_ports_are_in_out_and_the_side_window():
    glan = GlanLaserPolarizer(reject_angle_deg=30.0)
    ports = glan.ports()
    assert set(ports) == {"in", "out", "reject"}
    assert ports["out"].orientation_deg == pytest.approx(0.0)
    assert ports["reject"].orientation_deg == pytest.approx(-30.0)
    assert ports["reject"].center.y < 0                      # on the lower face


def test_p_goes_straight_and_s_leaves_by_the_side():
    routes = {t.out_port: t.matrix for t in GlanPrism().transfers(GlanLaserPolarizer(), "g", "in", 1064.0, {})}
    assert set(routes) == {"out", "reject"}
    assert np.allclose(routes["out"] @ [1, 0], [1, 0]) and np.allclose(routes["out"] @ [0, 1], [0, 0])
    assert np.allclose(routes["reject"] @ [0, 1], [0, 1]) and np.allclose(routes["reject"] @ [1, 0], [0, 0])


def test_it_has_an_exact_symbol_in_1d_and_2d():
    glan = GlanLaserPolarizer()
    assert lookup(glan).exact and symbol_for_2d(glan).exact
    assert lookup(glan).ports["reject"].side == "bottom"


def test_it_survives_a_save_and_reload():
    scene = Scene(title="", width=100, height=60, platform="free_space")
    scene.add(GlanLaserPolarizer(reject_angle_deg=30.0, label="Glan-Laser"))
    (glan,) = [n for n in scene_from_spec(scene_to_spec(scene)).walk() if n.component_type == "GlanLaserPolarizer"]
    assert glan.reject_angle_deg == pytest.approx(30.0)
