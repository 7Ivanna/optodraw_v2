"""The signal state: one object per animation, written as plain JSON for the timeline and the player."""


import pytest

import optodraw
from optodraw.animation_engine import compile_signal_state, sweep_steady_state


def _line():
    scene = optodraw.Scene(width=300, height=80, platform="on_chip")
    laser = scene.add(optodraw.OnChipLaser(center=(-120, 0)))
    pd = scene.add(optodraw.OnChipPhotodetector(center=(120, 0)))
    scene.route((laser, "o1"), (pd, "o1"), kind="waveguide")
    return scene


def test_continuous_mode_and_a_sweep():
    data = compile_signal_state(_line(), mode="cw").to_json()
    assert data["edges"]["route:route1"]["cw"] and data["absorbed"][0]["power"] == pytest.approx(1.0)
    states = sweep_steady_state(_line(), "wavelength", [1549.0, 1550.0, 1551.0])
    assert [s.to_json()["edges"]["route:route1"]["cw"][0]["wavelength_nm"] for s in states] == [1549.0, 1550.0, 1551.0]
    with pytest.raises(ValueError, match="mode"):
        compile_signal_state(_line(), mode="other")


