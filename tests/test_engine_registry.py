"""The behaviour registry: a part type maps to one behaviour; an unknown type is a named error."""


from optodraw.animation_engine.behaviours import (
    Behaviour, find_behaviour, register,
)


def test_register_maps_every_name_to_one_instance():
    @register("TestPartA", "TestPartB")
    class Both(Behaviour):
        pass
    assert find_behaviour(type("P", (), {"component_type": "TestPartA"})()) is find_behaviour(
        type("Q", (), {"component_type": "TestPartB"})())


