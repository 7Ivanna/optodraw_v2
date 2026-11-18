"""Light leaves a port along its outward direction and enters the next port against it."""

from __future__ import annotations

from optodraw import Beam, Laser, Photodiode, Scene
from optodraw.app.validation import run_checks


def _bench(laser_angle=0.0, pd_angle=0.0):
    scene = Scene(title="bench", width=100, height=40, platform="free_space")
    laser = scene.add(Laser(center=(-30, 0), angle=laser_angle, label="Laser"))
    pd = scene.add(Photodiode(center=(30, 0), angle=pd_angle, label="PD"))
    scene.add(Beam.through(laser, pd))
    return scene


def test_a_lens_turned_along_its_beam_is_reported():
    """A lens at angle=90 on a level beam lies flat along it: the light must pass through its faces."""

    from optodraw import Lens

    def bench(angle):
        scene = Scene(title="lens", width=120, height=40, platform="free_space")
        laser = scene.add(Laser(center=(-40, 0), label="Laser"))
        lens = scene.add(Lens(center=(0, 0), angle=angle, focal_length=40, label="L"))
        pd = scene.add(Photodiode(center=(40, 0), label="PD"))
        scene.add(Beam.through(laser, lens, pd))
        return [i["message"] for i in run_checks(scene)]

    assert any("runs along L" in m for m in bench(90))
    assert not [m for m in bench(0) if "runs along" in m]
