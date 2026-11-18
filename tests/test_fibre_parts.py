"""Fibre parts that papers show: an amplifier, a circulator, a 2x2 coupler, a spool, a variable attenuator."""

from __future__ import annotations

import pytest

import optodraw
from optodraw.registry import build_component

FIBRE_PARTS = {
    "FiberAmplifier": {"in", "out"},
    "FiberCirculator": {"p1", "p2", "p3"},
    "FiberCoupler": {"in1", "in2", "out1", "out2"},
    "FiberSpool": {"in", "out"},
    "VariableAttenuator": {"in", "out"},
}


def test_the_coupler_and_the_spool_keep_their_numbers():
    coupler = optodraw.FiberCoupler(ratio=0.9)
    spool = optodraw.FiberSpool(fiber_length_km=25.0)
    assert coupler.physics_metadata()["ratio"] == pytest.approx(0.9)
    assert spool.physics_metadata()["fiber_length_km"] == pytest.approx(25.0)
    with pytest.raises(ValueError):
        optodraw.FiberCoupler(ratio=1.5)


# ---------------------------------------------------------------- 3D: fibre parts lie on the table
FIBRE_3D = ["FiberAmplifier", "FiberCirculator", "FiberCoupler", "FiberSpool", "VariableAttenuator",
            "PolarizationController", "SNSPD"]


def _shapes(node):
    yield node
    for child in node.get("children", []):
        yield from _shapes(child)


def _lowest(geometry) -> float:
    import math

    lows = []
    for shape in _shapes(geometry):
        x, y, z = shape.get("position", [0.0, 0.0, 0.0])
        kind = shape.get("shape")
        if kind == "box":
            lows.append(y - shape["height"] / 2.0)
        elif kind == "cylinder":
            rotation = shape.get("rotation") or [0.0, 0.0, 0.0]
            lying = abs(rotation[0] - math.pi / 2.0) < 1e-6 or abs(rotation[2] - math.pi / 2.0) < 1e-6
            lows.append(y - (shape["radius"] if lying else shape["height"] / 2.0))
        elif kind == "extruded_polygon":
            lows.append(y)
        elif kind == "tube_path":
            lows.append(min(p[1] for p in shape["points"]) - shape.get("radius", 0.2))
    return min(lows)


@pytest.mark.parametrize("name", FIBRE_3D)
def test_a_fibre_part_lies_on_the_table_not_on_a_post(name):
    """A post lifted the parts to the beam height, while their fibre cables ran on the table."""

    from optodraw.renderers.threejs_renderer import ThreeJsRenderer

    scene = optodraw.Scene(width=120, height=60, platform="free_space")
    part = scene.add(build_component(name, label=""))
    assert not ThreeJsRenderer(scene)._is_beam_plane_optic(part)
    assert _lowest(part.geometry_3d()) == pytest.approx(0.0, abs=1e-6)      # its base is the table


# ---------------------------------------------------------------- 3D: a cable rises to a connector on a post


