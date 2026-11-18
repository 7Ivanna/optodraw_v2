"""The engine's foundation: one error type, stable ids, Jones amplitudes."""

import math

import numpy as np
import pytest

import optodraw
from optodraw.animation_engine import AnimationError
from optodraw.animation_engine.ids import part_id, path_id, port_id, route_id, scene_ids
from optodraw.animation_engine.signals import from_json, jones, linear, power, scalar, to_json


def _scene():
    scene = optodraw.Scene(width=120, height=60, platform="free_space")
    laser = scene.add(optodraw.Laser(center=(-40, 0)))
    lens = scene.add(optodraw.Lens(center=(0, 0)))
    pd = scene.add(optodraw.Photodiode(center=(40, 0)))
    scene.add(optodraw.Beam(laser, lens, pd))
    return scene, laser, lens, pd


def test_ids_are_per_type_in_walk_order_and_stable():
    scene, laser, lens, pd = _scene()
    ids = scene_ids(scene)
    assert (ids[id(laser)], ids[id(lens)], ids[id(pd)]) == ("laser1", "lens1", "photodiode1")
    assert scene_ids(scene) == ids                                            # the same every time
    assert len(set(ids.values())) == len(ids)


def test_every_kind_of_route_counts_as_a_route():
    scene = optodraw.Scene(width=200, height=80, platform="on_chip")
    a = scene.add(optodraw.Waveguide(center=(-60, 0)))
    b = scene.add(optodraw.Waveguide(center=(60, 0)))
    wg = scene.route((a, "o2"), (b, "o1"), kind="waveguide")
    amp = scene.add(optodraw.FiberAmplifier(center=(-60, 40)))
    spool = scene.add(optodraw.FiberSpool(center=(60, 40)))
    fibre = scene.route((amp, "out"), (spool, "in"), kind="fiber")
    ids = scene_ids(scene)
    assert (ids[id(wg)], ids[id(fibre)]) == ("route1", "route2")


def test_id_strings():
    assert part_id("laser1") == "part:laser1"
    assert port_id("lens1", "in") == "port:lens1:in"
    assert route_id("route1") == "route:route1"
    assert path_id("mzi1", "o1", "o3") == "path:mzi1:o1->o3"
    assert path_id("mzi1", "o1", "o3", "arm1") == "path:mzi1:o1->o3#arm1"


def test_jones_power_and_json_round_trip():
    v = linear(30.0, amplitude=2.0)
    assert power(v) == pytest.approx(4.0)
    assert v[1] / v[0] == pytest.approx(math.tan(math.radians(30.0)))
    w = jones(1 + 2j, -0.5j)
    assert np.allclose(from_json(to_json(w)), w)
    assert np.allclose(scalar(0.5) @ w, 0.5 * w)


def test_the_error_is_a_value_error():
    assert issubclass(AnimationError, ValueError)
