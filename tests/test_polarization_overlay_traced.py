"""The polarization overlay traces the states along the beams when the scene gives none."""

import re

from optodraw import Beam, Laser, Photodiode, Polarizer, QuarterWavePlate, Scene


def _bench(**qwp):
    scene = Scene(title="", width=160, height=60, platform="free_space")
    laser = scene.add(Laser(center=(-60, 0), wavelength=633))
    pol = scene.add(Polarizer(center=(-20, 0), axis_angle=0.0))
    plate = scene.add(QuarterWavePlate(center=(10, 0), design_wavelength_nm=633.0, **qwp))
    det = scene.add(Photodiode(center=(50, 0)))
    scene.add(Beam.through(laser, pol, plate, det, wavelength=633))
    return scene


def test_the_overlay_draws_the_state_after_each_polarizing_part():
    svg = _bench(fast_axis_angle=45.0).render_svg(show_polarization_overlay=True).as_svg()
    assert len(re.findall(r"<ellipse", svg)) == 2                    # linear after the polariser, circular after


