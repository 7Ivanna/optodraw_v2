"""The behaviour registry: a part type maps to one behaviour; an unknown type is a named error."""

import pytest

import optodraw
from optodraw.animation_engine import AnimationError
from optodraw.animation_engine.behaviours import (
    Behaviour, Transfer, behaviour_for, find_behaviour, polyline_length, register, registered_types,
)
from optodraw.animation_engine.behaviours.geometry import local_to_world, port_xy, through_anchor
from optodraw.animation_engine.signals import scalar
from optodraw.registry import component_registry


def test_an_unregistered_part_is_a_named_error():
    part = optodraw.Laser()
    part.component_type = "NoSuchPart"
    assert find_behaviour(part) is None
    with pytest.raises(AnimationError, match=r"^laser7: no behaviour yet for NoSuchPart"):
        behaviour_for(part, "laser7")


def test_a_part_may_bring_its_own_behaviour():
    class Own(Behaviour):
        pass
    part = optodraw.Lens()
    part.animation_behaviour = lambda: Own()
    assert isinstance(behaviour_for(part, "lens1"), Own)


def test_register_maps_every_name_to_one_instance():
    @register("TestPartA", "TestPartB")
    class Both(Behaviour):
        pass
    assert find_behaviour(type("P", (), {"component_type": "TestPartA"})()) is find_behaviour(
        type("Q", (), {"component_type": "TestPartB"})())


def test_every_registered_type_is_a_real_component():
    real = set(component_registry())
    assert [name for name in registered_types() if name not in real and not name.startswith("TestPart")] == []


def test_transfer_length_and_override():
    t = Transfer("in", "out", scalar(1.0), ((0.0, 0.0), (3.0, 4.0)))
    assert t.length == pytest.approx(5.0) and polyline_length(((0, 0), (0, 2), (2, 2))) == pytest.approx(4.0)
    assert Transfer("in", "out", scalar(1.0), ((0.0, 0.0), (1.0, 0.0)), physical_length=7.0).length == 7.0


def test_geometry_is_in_world_coordinates():
    from optodraw.core.transform import Vec3

    scene = optodraw.Scene(width=100, height=60, platform="free_space")
    group = scene.group(position=Vec3(50.0, 10.0, 0.0))
    lens = group.add(optodraw.Lens(center=(0, 0)))
    x, y = port_xy(lens, "in")
    assert x == pytest.approx(lens.world_port("in").center.x) and x > 30.0       # the group moved it
    assert through_anchor(lens, "in", "out")[1] == pytest.approx((50.0, 10.0), abs=1e-6)
    assert local_to_world(lens, [(0.0, 0.0)])[0] == pytest.approx((50.0, 10.0), abs=1e-6)
