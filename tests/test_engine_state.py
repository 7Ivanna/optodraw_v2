"""The signal state: one object per animation, written as plain JSON for the timeline and the player."""

import json

import pytest

import optodraw
import optodraw.presets as presets
from optodraw.animation_engine import AnimationError, compile_signal_state, sweep_steady_state


def _line():
    scene = optodraw.Scene(width=300, height=80, platform="on_chip")
    laser = scene.add(optodraw.OnChipLaser(center=(-120, 0)))
    pd = scene.add(optodraw.OnChipPhotodetector(center=(120, 0)))
    scene.route((laser, "o1"), (pd, "o1"), kind="waveguide")
    return scene


def test_the_state_json_has_the_schema_and_is_plain_json():
    data = compile_signal_state(_line()).to_json()
    assert data["version"] == 1 and data["mode"] == "pulse" and data["duration_ps"] > 0
    edge = data["edges"]["route:route1"]
    assert edge["packets"][0]["from"] == "port:onchiplaser1:o1" and len(edge["packets"][0]["jones"]) == 4
    assert json.loads(json.dumps(data)) == data                                  # nothing but JSON types


def test_the_same_scene_gives_the_same_json():
    assert compile_signal_state(_line()).to_json() == compile_signal_state(_line()).to_json()


def test_continuous_mode_and_a_sweep():
    data = compile_signal_state(_line(), mode="cw").to_json()
    assert data["edges"]["route:route1"]["cw"] and data["absorbed"][0]["power"] == pytest.approx(1.0)
    states = sweep_steady_state(_line(), "wavelength", [1549.0, 1550.0, 1551.0])
    assert [s.to_json()["edges"]["route:route1"]["cw"][0]["wavelength_nm"] for s in states] == [1549.0, 1550.0, 1551.0]
    with pytest.raises(ValueError, match="mode"):
        compile_signal_state(_line(), mode="other")


def test_an_mzm_scene_compiles_and_its_drive_sets_the_detected_power():
    scene = optodraw.Scene(width=360, height=80, platform="on_chip")
    laser = scene.add(optodraw.OnChipLaser(center=(-150, 0)))
    mzm = scene.add(optodraw.MZM(center=(0, 0)))
    pd = scene.add(optodraw.OnChipPhotodetector(center=(150, 0)))
    scene.route((laser, "o1"), (mzm, "o1"), kind="waveguide")
    scene.route((mzm, "o3"), (pd, "o1"), kind="waveguide")
    assert compile_signal_state(scene).to_json()["absorbed"][0]["power"] == pytest.approx(1.0)
    on = compile_signal_state(scene, mode="cw").to_json()
    off = compile_signal_state(scene, mode="cw", params={"drive:mzm1": 2.0}).to_json()
    assert sum(h["power"] for h in on["absorbed"]) == pytest.approx(1.0)
    assert sum(h["power"] for h in off["absorbed"]) == pytest.approx(0.0, abs=1e-9)


@pytest.mark.parametrize("name", sorted(presets.PRESETS))
def test_every_preset_compiles_or_names_the_part_it_cannot_animate(name):
    scene = presets.PRESETS[name]()
    try:
        state = compile_signal_state(scene)
    except AnimationError as error:
        assert str(error) == "the scene has no light source" or str(error).split(":")[0].isidentifier(), str(error)
    else:
        assert state.to_json()["edges"], name
