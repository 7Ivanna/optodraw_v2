"""A pulsed laser can have a sync output: an electrical port under its head, drawn in 1D and 2D."""

from __future__ import annotations

from optodraw import Laser, Scene
from optodraw.schema import scene_from_spec, scene_to_spec
from optodraw.symbols import lookup
from optodraw.symbols.art import symbol_for_2d


def test_a_laser_has_no_sync_port_unless_asked():
    assert set(Laser().ports()) == {"out", "e1"}               # e1: the drive input every laser has
    assert Laser(sync=True).ports()["sync"].kind == "electrical"


def test_the_sync_laser_has_an_exact_symbol_in_1d_and_in_2d():
    laser = Laser(sync=True)
    one, two = lookup(laser), symbol_for_2d(laser)
    assert one.exact and two.exact
    assert one.ports["sync"].side == "bottom" and two.ports["sync"].side == "bottom"


def test_the_sync_output_survives_a_save_and_reload():
    scene = Scene(title="", width=100, height=60, platform="free_space")
    scene.add(Laser(sync=True, label="pulsed"))
    (laser,) = [node for node in scene_from_spec(scene_to_spec(scene)).walk() if node.component_type == "Laser"]
    assert laser.sync and "sync" in laser.ports()
