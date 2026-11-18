import copy
import json

import pytest

import optodraw
from optodraw.animation_engine.authoring import Animation
from optodraw.animation_engine.primitives import Plot, Quantity, Sweep, Write
from optodraw.animation_engine.timeline import Timeline


def test_full_authoring_document_is_deterministic_and_lossless():
    outputs = []
    for _ in range(2):
        scene = optodraw.Scene(width=240, height=80, platform="on_chip")
        laser = scene.add(optodraw.OnChipLaser(center=(-90, 0)))
        detector = scene.add(optodraw.OnChipPhotodetector(center=(90, 0)))
        scene.route((laser, "o1"), (detector, "o1"), kind="waveguide")
        animation = Animation(scene).auto().click()
        animation.play(Write(r"P_{out}", near=detector)).click()
        animation.play(
            Sweep("wavelength", 1549, 1551, seconds=1, samples=3),
            Plot(Quantity(detector), against="wavelength"),
        ).click()
        outputs.append(animation.dumps())
    assert outputs[0] == outputs[1]
    restored = Timeline.from_json(outputs[0])
    assert restored.dumps() == outputs[0]
    assert restored.to_json() == json.loads(outputs[0])


def test_import_and_export_do_not_share_mutable_data():
    timeline = Timeline()
    timeline.wait(0.5).click()
    original = timeline.to_json()
    restored = Timeline.from_json(original)
    original["tracks"][0]["args"]["external"] = [1]
    assert "external" not in restored.tracks[0].args
    exported = restored.to_json()
    exported["tracks"][0]["args"]["external"] = [2]
    assert "external" not in restored.tracks[0].args


@pytest.mark.parametrize("mutation, message", [
    (lambda d: d.update(version=2), "version"),
    (lambda d: d.update(duration=float("nan")), "finite"),
    (lambda d: d["tracks"][0].update(duration=-1), "duration"),
    (lambda d: d["tracks"][0].update(type="Unknown"), "primitive"),
    (lambda d: d["sections"][0].update(end=-1), "section"),
    (lambda d: d["tracks"].append(copy.deepcopy(d["tracks"][0])), "duplicate"),
    (lambda d: d.update(unknown_field=1), "field"),
])
def test_invalid_documents_raise_specific_errors(mutation, message):
    timeline = Timeline().wait(0.5).click()
    data = timeline.to_json()
    mutation(data)
    with pytest.raises(ValueError, match=message):
        Timeline.from_json(data)


def test_duplicate_json_keys_are_rejected():
    with pytest.raises(ValueError, match="duplicate"):
        Timeline.from_json('{"version":1,"version":2}')


def test_a_missing_signal_state_reference_is_rejected():
    timeline = Timeline().wait(0.5).click()
    data = timeline.to_json()
    data["tracks"][0].update(type="Flow")
    data["tracks"][0]["args"] = {
        "state": "q99", "paths": ["route:route1"], "mode": "cw",
        "style": data["style"], "settled": False,
    }
    with pytest.raises(ValueError, match="q99"):
        Timeline.from_json(data)


@pytest.fixture
def light_document():
    scene = optodraw.Scene(width=240, height=80, platform="on_chip")
    laser = scene.add(optodraw.OnChipLaser(center=(-90, 0)))
    detector = scene.add(optodraw.OnChipPhotodetector(center=(90, 0)))
    scene.route((laser, "o1"), (detector, "o1"), kind="waveguide")
    animation = Animation(scene).auto().click()
    animation.play(Sweep("wavelength", 1549, 1551, 1, samples=3),
                   Plot(Quantity(detector), against="wavelength"))
    return animation.to_json()


@pytest.mark.parametrize("mutation, message", [
    (lambda d: d["tracks"][0].update(extra=1), "field"),
    (lambda d: d.update(duration="2.5"), "number"),
    (lambda d: d.update(version=True), "version"),
    (lambda d: d["sections"][1].update(start=0), "section"),
    (lambda d: d["tracks"][0].update(id=""), "id"),
    (lambda d: d["tracks"][0]["args"].update(paths=["route:absent"]), "route:absent"),
    (lambda d: d["signal_state"].update(time_scale_s_per_ps=0), "scale"),
    (lambda d: d["signal_states"]["q2"].update(time_scale_s_per_ps=999), "scale"),
    (lambda d: d["signal_state"]["edges"]["route:route1"]["cw"][0].update(jones=[1, 0]), "Jones"),
    (lambda d: d["signal_states"]["q2"]["edges"]["route:route1"]["cw"][0].update(t1=[0]), "sample"),
    (lambda d: d["signal_states"]["q2"]["absorbed"][0].update(power=[1]), "sample"),
    (lambda d: d["assets"]["plot:1"].update(y=[1]), "plot"),
    (lambda d: d["assets"].clear(), "plot:1"),
    (lambda d: d["signal_states"].update(base=copy.deepcopy(d["signal_state"])), "reserved"),
    (lambda d: d["assets"]["plot:1"]["quantity"].update(target="route:unknown"), "route:unknown"),
    (lambda d: d["signal_state"]["edges"]["route:route1"]["cw"][0].update(**{"from": None}), "reference"),
    (lambda d: d["tracks"][0]["args"].update(exits=["exit:port:unknown:o1"]), "exit:port:unknown:o1"),
    (lambda d: d["tracks"][0]["args"].update(style={**d["style"], "other": 1}), "style"),
])
def test_full_document_rejects_invalid_fields_and_physical_arrays(light_document, mutation, message):
    mutation(light_document)
    with pytest.raises(ValueError, match=message):
        Timeline.from_json(light_document)


def test_import_preserves_json_number_types_and_nested_arguments():
    data = Timeline().wait(1).click().to_json()
    data["duration"] = 1
    data["sections"][0].update(start=0, end=1)
    data["tracks"][0].update(start=0, duration=1)
    data["style"]["brightness"] = 1
    data["tracks"][0]["args"]["extra"] = {"value": 1, "text": "plain"}
    encoded = json.dumps(data, sort_keys=True, separators=(",", ":"))
    assert Timeline.from_json(encoded).dumps() == encoded


@pytest.mark.parametrize("mode", ["cw", "pulse"])
def test_open_departures_round_trip_with_warning_and_outward_geometry(mode):
    scene = optodraw.Scene(width=120, height=80, platform="on_chip")
    scene.add(optodraw.OnChipLaser(angle=90))
    with pytest.warns(RuntimeWarning, match="onchiplaser1.*o1"):
        encoded = Animation(scene, mode=mode).auto().dumps()
    restored = Timeline.from_json(encoded)
    assert restored.dumps() == encoded
    assert restored.signal_state["warnings"][0]["port"] == "o1"
    assert restored.signal_state["exits"][0]["points"][1][1] > restored.signal_state["exits"][0]["points"][0][1]


def test_an_explicit_dark_route_carries_geometry_without_signal_records():
    from optodraw.animation_engine.primitives import Flow, Set
    scene = optodraw.Scene(width=300, height=80, platform="on_chip")
    laser = scene.add(optodraw.OnChipLaser(center=(-100, 0)))
    modulator = scene.add(optodraw.MZM())
    detector = scene.add(optodraw.OnChipPhotodetector(center=(100, 0)))
    scene.route((laser, "o1"), (modulator, "o1"), kind="waveguide")
    scene.route((modulator, "o3"), (detector, "o1"), kind="waveguide")
    animation = Animation(scene).play(Set("drive:mzm1", 2))
    animation.play(Flow(paths=["route:route2"]))
    data = animation.to_json()
    assert data["signal_state"]["edges"]["route:route2"]["cw"] == []
    assert len(data["signal_state"]["edges"]["route:route2"]["points"]) >= 2
    assert Timeline.from_json(animation.dumps()).dumps() == animation.dumps()


def test_default_120_sample_sweep_round_trips_authentic_states():
    scene = optodraw.Scene(width=240, height=80, platform="on_chip")
    laser = scene.add(optodraw.OnChipLaser(center=(-90, 0)))
    detector = scene.add(optodraw.OnChipPhotodetector(center=(90, 0)))
    scene.route((laser, "o1"), (detector, "o1"), kind="waveguide")
    animation = Animation(scene).auto().click()
    animation.play(Sweep("wavelength", 1549, 1551, 1), Plot(Quantity(detector), against="wavelength"))
    data = animation.to_json()
    state = data["signal_states"]["q2"]
    assert len(state["samples"]) == 120
    assert state["samples"][0] == 1549 and state["samples"][-1] == 1551
    assert len(state["edges"]["route:route1"]["cw"][0]["jones"]) == 120
    assert data["assets"]["plot:1"]["y"] == pytest.approx([1] * 120)
    assert Timeline.from_json(animation.dumps()).dumps() == animation.dumps()


def test_nested_duplicate_json_keys_and_missing_text_assets_fail():
    with pytest.raises(ValueError, match="duplicate"):
        Timeline.from_json('{"version":1,"assets":{"x":1,"x":2}}')
    scene = optodraw.Scene(width=120, height=80, platform="free_space")
    laser = scene.add(optodraw.Laser())
    data = Animation(scene).play(Write("label", near=laser)).to_json()
    data["assets"].clear()
    with pytest.raises(ValueError, match="text:1"):
        Timeline.from_json(data)
