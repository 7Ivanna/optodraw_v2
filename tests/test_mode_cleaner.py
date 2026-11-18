"""A triangular ring mode cleaner: its ring obeys the law of reflection, and its beams leave where the ring sends them."""

from __future__ import annotations

import math

import pytest

from optodraw import Beam, Laser, ModeCleaner, Photodiode, Scene, check_part_3d
from optodraw.animation_engine import Animation
from optodraw.layout import face
from optodraw.schema import scene_from_spec, scene_to_spec


def _unit(a, b):
    length = math.dist(a, b)
    return (b[0] - a[0]) / length, (b[1] - a[1]) / length


def _bench(**options):
    scene = Scene(title="", platform="free_space")
    laser = scene.add(Laser(center=(-34, 0), wavelength=1064, label="Laser"))
    mc = scene.add(ModeCleaner(center=(0, 0), label="MC", label_side="top", **options))
    trans = scene.add(Photodiode(center=(24, 0), label="Trans"))
    dx, dy = mc.refl_direction()
    lock = scene.add(Photodiode(center=(-7.5 + 12 * dx, -3 + 12 * dy), label="Lock", label_side="left"))
    face(trans, mc)
    face(lock, mc)
    scene.add(Beam.through(laser, (mc, "in"), wavelength=1064))
    scene.add(Beam.through((mc, "out"), trans, wavelength=1064))
    scene.add(Beam.through((mc, "refl"), lock, wavelength=1064))
    return scene


def test_locked_it_passes_its_transmission_and_reflects_the_rest():
    absorbed = Animation(_bench(transmission=80.0), mode="cw", strict=True).auto().click().to_json()
    power = {r["part"]: r["power"] for r in absorbed["signal_state"]["absorbed"]}
    assert power == pytest.approx({"photodiode1": 0.8, "photodiode2": 0.2})


def test_it_keeps_its_values_through_a_save_and_stands_on_its_post():
    scene = _bench(piezo=True, size=24.0, transmission=85.0)
    (again,) = [n for n in scene_from_spec(scene_to_spec(scene)).walk() if n.component_type == "ModeCleaner"]
    assert (again.piezo, again.size, again.transmission) == (True, 24.0, 85.0)
    assert check_part_3d(ModeCleaner()) == [] and check_part_3d(ModeCleaner(piezo=True)) == []


