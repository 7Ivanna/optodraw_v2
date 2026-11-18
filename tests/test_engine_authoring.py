import pytest

import optodraw
from optodraw.animation_engine import AnimationError, compile_signal_state
from optodraw.animation_engine.authoring import Animation
from optodraw.animation_engine.primitives import Flow, Indicate, Morph, Write
from optodraw.animation_engine.styles import Style


def test_auto_is_a_normal_track_with_one_global_scale():
    scene = optodraw.Scene(width=300, height=80, platform="on_chip")
    laser = scene.add(optodraw.OnChipLaser(center=(-120, 0)))
    detector = scene.add(optodraw.OnChipPhotodetector(center=(120, 0)))
    scene.route((laser, "o1"), (detector, "o1"), kind="waveguide")
    original = compile_signal_state(scene).to_json()
    animation = Animation(scene, mode="pulse").auto().click()
    track = animation.timeline.tracks[0]
    assert track.type == "Flow"
    assert track.args["paths"] == [          # the light runs inside the laser, along the route, and into the detector
        "path:onchiplaser1:_active->o1#emission", "route:route1", "path:onchipphotodetector1:o1->_absorb_o1#absorb"]
    assert track.duration == pytest.approx(2.5)
    track.args["style"] = Style("packets").to_json()
    data = animation.to_json()
    assert data["tracks"][0]["args"]["style"]["name"] == "packets"
    scale = data["signal_state"]["time_scale_s_per_ps"]
    physical_end = original["edges"]["path:onchipphotodetector1:o1->_absorb_o1#absorb"]["packets"][0]["t1"]
    assert physical_end * scale == pytest.approx(2.5)


def test_scene_targets_assets_and_future_view_actions_bind_to_ids():
    scene = optodraw.Scene(width=120, height=80, platform="free_space")
    laser = scene.add(optodraw.Laser())
    animation = Animation(scene)
    animation.play(Indicate(laser), Write(r"E_x", near=laser)).click()
    animation.play(Morph(to="1d")).click()
    data = animation.to_json()
    assert data["tracks"][0]["target"] == "part:laser1"
    assert data["tracks"][1]["target"] == "text:1"
    assert data["assets"]["text:1"] == {
        "kind": "text", "text": r"E_x", "near": "part:laser1",
    }
    assert data["tracks"][2]["args"]["to"] == "1d"
    assert data["view"] == "2d"


def test_foreign_parts_and_unknown_paths_fail_without_partial_tracks():
    scene = optodraw.Scene(width=240, height=80, platform="on_chip")
    laser = scene.add(optodraw.OnChipLaser(center=(-90, 0)))
    detector = scene.add(optodraw.OnChipPhotodetector(center=(90, 0)))
    scene.route((laser, "o1"), (detector, "o1"), kind="waveguide")
    animation = Animation(scene)
    with pytest.raises(ValueError, match="scene"):
        animation.play(Indicate(optodraw.Lens()))
    with pytest.raises(ValueError, match="route:missing"):
        animation.play(Flow(paths=["route:missing"]))
    assert animation.timeline.tracks == []


def test_style_changes_do_not_rewrite_earlier_flows():
    scene = optodraw.Scene(width=240, height=80, platform="on_chip")
    laser = scene.add(optodraw.OnChipLaser(center=(-90, 0)))
    detector = scene.add(optodraw.OnChipPhotodetector(center=(90, 0)))
    scene.route((laser, "o1"), (detector, "o1"), kind="waveguide")
    animation = Animation(scene, mode="pulse", style="photons").auto().click()
    animation.set_style("packets").auto().click()
    data = animation.to_json()
    assert [track["args"]["style"]["name"] for track in data["tracks"]] == ["photons", "packets"]
    scales = {data["signal_state"]["time_scale_s_per_ps"]}
    scales.update(state["time_scale_s_per_ps"] for state in data["signal_states"].values())
    assert len(scales) == 1


def test_missing_source_remains_the_m1_error():
    scene = optodraw.Scene(width=120, height=80, platform="free_space")
    scene.add(optodraw.Lens())
    with pytest.raises(AnimationError, match="^the scene has no light source$"):
        Animation(scene).auto()


def test_explicit_scale_preserves_scene_and_controls_flow_time():
    scene = optodraw.Scene(width=300, height=80, platform="on_chip")
    laser = scene.add(optodraw.OnChipLaser(center=(-100, 0)))
    detector = scene.add(optodraw.OnChipPhotodetector(center=(100, 0)))
    scene.route((laser, "o1"), (detector, "o1"), kind="waveguide")
    original = scene.to_spec()
    animation = Animation(scene, time_scale_s_per_ps=0.01).auto()
    assert animation.to_json()["signal_state"]["time_scale_s_per_ps"] == 0.01
    assert scene.to_spec() == original


def test_bits_rejects_an_optical_table_with_a_named_error():
    scene = optodraw.Scene(width=120, height=80, platform="free_space")
    scene.add(optodraw.Laser())
    with pytest.warns(RuntimeWarning, match="laser1.*out"):
        with pytest.raises(AnimationError, match="laser1.*electrical"):
            Animation(scene, style="bits").auto()


@pytest.mark.parametrize("mode", ["pulse", "cw"])
def test_open_output_is_bound_as_visible_departure_data(mode):
    scene = optodraw.Scene(width=120, height=80, platform="on_chip")
    scene.add(optodraw.OnChipLaser(angle=90))
    with pytest.warns(RuntimeWarning, match="onchiplaser1.*o1"):
        data = Animation(scene, mode=mode).auto().to_json()
    assert data["signal_state"]["exits"][0]["visual_only"] is True
    assert data["tracks"][0]["args"]["exits"] == ["exit:port:onchiplaser1:o1"]
    assert data["tracks"][0]["duration"] > 0
    with pytest.raises(AnimationError, match="onchiplaser1.*o1"):
        Animation(scene, mode=mode, strict=True).auto()


def test_failed_play_does_not_allocate_assets_or_states():
    scene = optodraw.Scene(width=120, height=80, platform="free_space")
    scene.add(optodraw.Laser())
    animation = Animation(scene)
    with pytest.raises(ValueError, match="scene"):
        animation.play(Write("not retained"), Indicate(optodraw.Lens()))
    assert animation.timeline.assets == {}
    assert animation.timeline.tracks == []
    animation.play(Write("retained"))
    assert animation.timeline.tracks[0].target == "text:1"


def test_scene_changes_after_binding_are_rejected():
    scene = optodraw.Scene(width=120, height=80, platform="free_space")
    scene.add(optodraw.Laser())
    animation = Animation(scene)
    scene.add(optodraw.Lens())
    with pytest.raises(ValueError, match="scene.*changed"):
        animation.play(Write("reject"))
