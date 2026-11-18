"""Light that crosses a wave plate, meets a mirror and crosses it again: the second pass sees the plate from behind.

A half-wave plate passed twice is a full-wave plate, so H comes back H and the cube sends it back to the laser. A
quarter-wave plate at 45 degrees passed twice is a half-wave plate, so H comes back V and the cube sends it to its
tap: the optical isolator of every pump-probe and lock bench. The engine used the forward matrix on the way back too,
which swapped the two results.
"""

import pytest

from optodraw import PBS, Beam, HalfWavePlate, Laser, Mirror, Photodiode, Polarizer, QuarterWavePlate, Scene
from optodraw.animation_engine import Animation


def _double_pass(middle):
    scene = Scene(platform="free_space")
    laser = scene.add(Laser(center=(-40, 0), wavelength=1064))
    pbs = scene.add(PBS(center=(-15, 0)))
    part = scene.add(middle)
    mirror = scene.add(Mirror(center=(25, 0)))
    pd = scene.add(Photodiode(center=(-15, -20), angle=90))
    scene.add(Beam.through(laser, (pbs, "in"), (pbs, "trans"), part, mirror, part, (pbs, "trans"), (pbs, "tap"), pd))
    absorbed = Animation(scene, mode="cw", strict=True).auto().click().to_json()["signal_state"]["absorbed"]
    power = {record["part"]: record["power"] for record in absorbed}
    return power.get("photodiode1", 0.0), power.get("laser1", 0.0)


@pytest.mark.parametrize("angle", [22.5, 10.0, 67.5])
def test_a_half_wave_plate_passed_twice_sends_the_light_home(angle):
    tap, home = _double_pass(HalfWavePlate(center=(5, 0), fast_axis_angle=angle))
    assert tap < 1e-6 and home > 0.98


def test_a_quarter_wave_plate_at_45_degrees_passed_twice_isolates_the_laser():
    tap, home = _double_pass(QuarterWavePlate(center=(5, 0), fast_axis_angle=45.0))
    assert tap > 0.98 and home < 1e-6


def test_a_quarter_wave_plate_at_22_5_degrees_passed_twice_splits_the_light_in_half():
    tap, home = _double_pass(QuarterWavePlate(center=(5, 0), fast_axis_angle=22.5))
    assert tap == pytest.approx(home, abs=0.02) and tap + home > 0.97


def test_a_polarizer_passed_twice_passes_what_it_passed_once():
    tap, home = _double_pass(Polarizer(center=(5, 0), angle=0.0))
    assert home > 0.95 and tap < 1e-3
