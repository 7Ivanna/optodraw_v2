"""Two beams on one path stay readable: the lower one shows through, or each keeps a lane of its own."""

from __future__ import annotations

import inspect


from optodraw import Beam, FocusingBeam, Laser, Mirror, Photodiode, Scene
from optodraw.layout import aim, face
from optodraw.schema import scene_from_spec, scene_to_spec


def _fold():
    scene = Scene(title="fold", width=100, height=80, platform="free_space")
    laser = scene.add(Laser(center=(-30, 0), label="Laser"))
    mirror = scene.add(Mirror(center=(0, 0), label="M", label_side="bottom-right"))
    pd = scene.add(Photodiode(center=(0, 30), label="PD"))
    aim(mirror, laser, pd)
    face(pd, mirror)
    return scene, laser, mirror, pd


def test_opacity_and_offset_are_named_parameters():
    for cls in (Beam, FocusingBeam):
        names = inspect.signature(cls.__init__).parameters
        assert "opacity" in names and "offset" in names


def test_opacity_and_offset_survive_a_save():
    scene, laser, mirror, pd = _fold()
    scene.add(Beam.through(laser, mirror, pd, wavelength=450, opacity=0.4, offset=0.6, label="lane"))
    scene.add(FocusingBeam((mirror, "io"), (pd, "in"), width1=3.0, opacity=0.3, offset=-0.2))
    loaded = scene_from_spec(scene_to_spec(scene))
    beams = [n for n in loaded.walk() if isinstance(n, Beam)]
    cones = [n for n in loaded.walk() if isinstance(n, FocusingBeam)]
    assert (beams[0].opacity, beams[0].offset) == (0.4, 0.6)
    assert (cones[0].opacity, cones[0].offset) == (0.3, -0.2)


