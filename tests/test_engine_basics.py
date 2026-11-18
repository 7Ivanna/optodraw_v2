"""The engine's foundation: one error type, stable ids, Jones amplitudes."""



import optodraw
from optodraw.animation_engine import AnimationError
from optodraw.animation_engine.ids import part_id, path_id, port_id, route_id


def _scene():
    scene = optodraw.Scene(width=120, height=60, platform="free_space")
    laser = scene.add(optodraw.Laser(center=(-40, 0)))
    lens = scene.add(optodraw.Lens(center=(0, 0)))
    pd = scene.add(optodraw.Photodiode(center=(40, 0)))
    scene.add(optodraw.Beam(laser, lens, pd))
    return scene, laser, lens, pd


def test_id_strings():
    assert part_id("laser1") == "part:laser1"
    assert port_id("lens1", "in") == "port:lens1:in"
    assert route_id("route1") == "route:route1"
    assert path_id("mzi1", "o1", "o3") == "path:mzi1:o1->o3"
    assert path_id("mzi1", "o1", "o3", "arm1") == "path:mzi1:o1->o3#arm1"


def test_the_error_is_a_value_error():
    assert issubclass(AnimationError, ValueError)
