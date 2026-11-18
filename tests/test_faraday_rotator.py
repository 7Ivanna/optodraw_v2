"""A Faraday rotator: a rod in a ring magnet that turns the polarization the same way in both directions."""

from __future__ import annotations


from optodraw import PBS, Beam, FaradayRotator, Laser, Mirror, Photodiode, Scene
from optodraw.animation_engine import Animation
from optodraw.registry import build_component
from optodraw.schema import scene_from_spec, scene_to_spec


def _double_pass(middle):
    """Light passes the cube, the part, a mirror, the part again and comes back to the cube."""

    scene = Scene(title="", platform="free_space")
    laser = scene.add(Laser(center=(-40, 0), wavelength=1064, label="Laser"))
    pbs = scene.add(PBS(center=(-15, 0), label="PBS"))
    part = scene.add(middle)
    mirror = scene.add(Mirror(center=(25, 0), label="M"))
    pd = scene.add(Photodiode(center=(-15, -20), angle=90, label="PD", label_side="right"))
    scene.add(Beam.through(laser, (pbs, "in"), (pbs, "trans"), part, mirror, part, (pbs, "trans"), (pbs, "tap"), pd,
                           wavelength=1064))
    absorbed = Animation(scene, mode="cw", strict=True).auto().click().to_json()["signal_state"]["absorbed"]
    return {record["part"]: record["power"] for record in absorbed}, scene


def test_it_is_in_the_catalog_and_keeps_its_values_through_a_save():
    assert build_component("FaradayRotator", rotation_deg=22.5).rotation_deg == 22.5
    _, scene = _double_pass(FaradayRotator(center=(5, 0), length=14.0, rotation_deg=40.0))
    (again,) = [n for n in scene_from_spec(scene_to_spec(scene)).walk() if n.component_type == "FaradayRotator"]
    assert (again.length, again.rotation_deg) == (14.0, 40.0)


