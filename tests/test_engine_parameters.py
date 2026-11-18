import math

import pytest

import optodraw
from optodraw.animation_engine.authoring import Animation
from optodraw.animation_engine.parameters import sample_values
from optodraw.animation_engine.primitives import Flow, Plot, Quantity, Set, Sweep


def test_sweep_samples_include_endpoints_and_respect_easing():
    linear = sample_values(1549.0, 1551.0)
    assert len(linear) == 120
    assert linear[0] == 1549.0 and linear[-1] == 1551.0
    assert sample_values(0, 1, samples=3, easing="ease_in") == [0, 0.25, 1]
    assert sample_values(0, 1, samples=3, easing="there_and_back") == [0, 1, 0]


def test_sweep_zero_fills_dark_edges_and_plot_samples_match_malus():
    scene = optodraw.Scene(width=300, height=100, platform="free_space")
    laser = scene.add(optodraw.Laser(center=(-100, 0)))
    polarizer = scene.add(optodraw.Polarizer(center=(0, 0)))
    detector = scene.add(optodraw.Photodiode(center=(100, 0)))
    scene.add(optodraw.Beam((laser, "out"), (polarizer, "in")))
    scene.add(optodraw.Beam((polarizer, "out"), (detector, "in")))
    animation = Animation(scene).auto().click()
    animation.play(
        Sweep("angle:polarizer1", 0, 90, seconds=4, samples=3),
        Plot(Quantity(detector), against="angle:polarizer1"),
    ).click()
    data = animation.to_json()
    sweep = next(track for track in data["tracks"] if track["type"] == "Sweep")
    table = data["signal_states"][sweep["args"]["state"]]
    edge = table["edges"]["beam:beam2:0"]
    assert table["samples"] == [0.0, 45.0, 90.0]
    assert len(edge["cw"][0]["jones"]) == 3
    plot = data["assets"]["plot:1"]
    assert plot["x"] == table["samples"]
    assert plot["y"] == pytest.approx([1.0, 0.5, 0.0], abs=2e-3)
    assert data["signal_state"]["params"] == {}


def test_set_at_a_click_preserves_earlier_parameter_snapshots():
    scene = optodraw.Scene(width=240, height=80, platform="on_chip")
    laser = scene.add(optodraw.OnChipLaser(center=(-90, 0)))
    detector = scene.add(optodraw.OnChipPhotodetector(center=(90, 0)))
    scene.route((laser, "o1"), (detector, "o1"), kind="waveguide")
    animation = Animation(scene).play(Set("wavelength", 1549.0)).auto().click()
    animation.play(Set("wavelength", 1551.0)).auto().click()
    data = animation.to_json()
    assert data["signal_state"]["params"]["wavelength"] == 1549.0
    later = next(iter(data["signal_states"].values()))
    assert later["params"]["wavelength"] == 1551.0


def test_parameter_conflicts_fail_before_any_tracks_are_added():
    animation = Animation(optodraw.Scene(width=120, height=80, platform="free_space"))
    with pytest.raises(ValueError, match="wavelength"):
        animation.play(Set("wavelength", 1549), Set("wavelength", 1551))
    assert animation.timeline.tracks == []


def test_pulse_sweep_overlap_is_rejected_and_midsection_set_is_rejected():
    scene = optodraw.Scene(width=240, height=80, platform="on_chip")
    laser = scene.add(optodraw.OnChipLaser(center=(-90, 0)))
    detector = scene.add(optodraw.OnChipPhotodetector(center=(90, 0)))
    scene.route((laser, "o1"), (detector, "o1"), kind="waveguide")
    animation = Animation(scene, mode="pulse")
    with pytest.raises(ValueError, match="pulse"):
        animation.play(Flow(mode="pulse"), Sweep("wavelength", 1549, 1551, seconds=4))
    assert animation.timeline.tracks == []
    animation.auto()
    with pytest.raises(ValueError, match="boundary"):
        animation.play(Set("wavelength", 1551))


def test_completed_pulse_section_can_start_a_continuous_sweep():
    scene = optodraw.Scene(width=240, height=80, platform="on_chip")
    laser = scene.add(optodraw.OnChipLaser(center=(-90, 0)))
    detector = scene.add(optodraw.OnChipPhotodetector(center=(90, 0)))
    scene.route((laser, "o1"), (detector, "o1"), kind="waveguide")
    animation = Animation(scene, mode="pulse").auto().click()
    animation.play(Sweep("wavelength", 1549, 1551, seconds=1, samples=2)).click()
    flows = [track for track in animation.to_json()["tracks"] if track["type"] == "Flow"]
    assert flows[0]["args"]["mode"] == "pulse"
    assert flows[1]["args"]["mode"] == "cw"
    assert flows[1]["args"]["settled"] is True


def test_ring_plot_uses_the_solved_all_pass_response():
    scene = optodraw.Scene(width=300, height=100, platform="on_chip")
    laser = scene.add(optodraw.OnChipLaser(center=(-100, 0)))
    ring = scene.add(optodraw.MicroringResonator(center=(0, 0)))
    detector = scene.add(optodraw.OnChipPhotodetector(center=(100, 0)))
    scene.route((laser, "o1"), (ring, "o1"), kind="waveguide")
    scene.route((ring, "o2"), (detector, "o1"), kind="waveguide")
    animation = Animation(scene).auto().click()
    animation.play(
        Sweep("wavelength", 1549, 1551, seconds=1, samples=3),
        Plot(Quantity(detector), against="wavelength"),
    )
    data = animation.to_json()
    sweep = next(track for track in data["tracks"] if track["type"] == "Sweep")
    table = data["signal_states"][sweep["args"]["state"]]
    loop_length = table["edges"]["path:microringresonator1:_ring->_ring"]["length_um"]
    t, a = math.sqrt(0.9), 0.99
    expected = []
    for wavelength in table["samples"]:
        theta = 2 * math.pi * 4.2 * loop_length / (wavelength / 1000.0)
        z = complex(math.cos(theta), math.sin(theta))
        expected.append(abs((t - a * z) / (1 - t * a * z)) ** 2)
    assert data["assets"]["plot:1"]["y"] == pytest.approx(expected, rel=1e-6)
def test_an_extinguished_sample_remains_in_the_series():
    scene = optodraw.Scene(width=300, height=100, platform="on_chip")
    laser = scene.add(optodraw.OnChipLaser(center=(-100, 0)))
    modulator = scene.add(optodraw.MZM(center=(0, 0)))
    detector = scene.add(optodraw.OnChipPhotodetector(center=(100, 0)))
    scene.route((laser, "o1"), (modulator, "o1"), kind="waveguide")
    scene.route((modulator, "o3"), (detector, "o1"), kind="waveguide")
    animation = Animation(scene).auto().click()
    animation.play(
        Sweep("drive:mzm1", 0, 2, seconds=1, samples=3),
        Plot(Quantity(detector), against="drive:mzm1"),
    )
    data = animation.to_json()
    sweep = next(track for track in data["tracks"] if track["type"] == "Sweep")
    table = data["signal_states"][sweep["args"]["state"]]
    samples = table["edges"]["route:route2"]["cw"][0]["jones"]
    assert len(samples) == 3
    assert samples[-1] == [0.0, 0.0, 0.0, 0.0]
    assert table["edges"]["route:route2"]["cw"][0]["wavelength_nm"] == [1550.0] * 3
    assert data["assets"]["plot:1"]["y"] == pytest.approx([1, 0.5, 0], abs=1e-9)


def test_nested_writers_and_multiple_parameter_sweeps_fail_before_physics():
    from optodraw.animation_engine.primitives import Sequence
    animation = Animation(optodraw.Scene(width=120, height=80, platform="free_space"))
    with pytest.raises(ValueError, match="wavelength"):
        animation.play(Sequence(Set("wavelength", 1)), Set("wavelength", 2))
    with pytest.raises(ValueError, match="overlapping sweeps"):
        animation.play(Sweep("wavelength", 1549, 1551, 4), Sweep("angle:polarizer1", 0, 90, 4))
    assert animation.timeline.tracks == []


def test_plot_without_matching_sweep_fails_without_allocating_assets():
    scene = optodraw.Scene(width=120, height=80, platform="free_space")
    laser = scene.add(optodraw.Laser())
    animation = Animation(scene)
    with pytest.raises(ValueError, match="matching sweep"):
        animation.play(Plot(Quantity(laser), against="wavelength"))
    assert animation.timeline.assets == {}
    assert animation.timeline.tracks == []


def test_global_wavelength_sweep_retains_separate_fixed_source_channels():
    from optodraw.animation_engine.parameters import compile_sweep
    scene = optodraw.Scene(width=120, height=80, platform="on_chip")
    laser = scene.add(optodraw.OnChipLaser())
    animation = Animation(scene).input(laser, "o1", wavelength_nm=1310, direction="out")
    with pytest.warns(RuntimeWarning, match="onchiplaser1.*o1"):
        table = compile_sweep(scene, "wavelength", [1549, 1551], inputs=animation._inputs)
    assert len(table["exits"]) == 2
    assert {item["channel"] for item in table["exits"]} == {"source:1", "source:2"}
    wavelengths = [item["wavelength_nm"] for item in table["exits"]]
    assert [1549.0, 1551.0] in wavelengths
    assert [1310.0, 1310.0] in wavelengths


def test_sweep_rejects_changing_coherent_wavelength_groups():
    from optodraw.animation_engine import AnimationError
    from optodraw.animation_engine.parameters import compile_sweep
    scene = optodraw.Scene(width=120, height=80, platform="on_chip")
    laser = scene.add(optodraw.OnChipLaser())
    animation = Animation(scene).input(laser, "o1", wavelength_nm=1551, direction="out")
    with pytest.warns(RuntimeWarning, match="onchiplaser1.*o1"):
        with pytest.raises(AnimationError, match="onchiplaser1.*wavelength.*coherent"):
            compile_sweep(scene, "wavelength", [1549, 1551], inputs=animation._inputs)


def test_strict_sweep_rejects_an_open_output():
    from optodraw.animation_engine import AnimationError
    from optodraw.animation_engine.parameters import compile_sweep
    scene = optodraw.Scene(width=120, height=80, platform="on_chip")
    scene.add(optodraw.OnChipLaser())
    with pytest.raises(AnimationError, match="onchiplaser1.*o1"):
        compile_sweep(scene, "wavelength", [1549, 1551], strict=True)


@pytest.mark.parametrize("change_points", [False, True])
def test_sweep_preserves_sampled_lengths_but_rejects_changed_points(monkeypatch, change_points):
    from optodraw.animation_engine import AnimationError
    from optodraw.animation_engine import parameters
    scene = optodraw.Scene(width=240, height=80, platform="on_chip")
    laser = scene.add(optodraw.OnChipLaser(center=(-90, 0)))
    detector = scene.add(optodraw.OnChipPhotodetector(center=(90, 0)))
    scene.route((laser, "o1"), (detector, "o1"), kind="waveguide")
    compile_table = parameters.compile_table

    def varying_table(*args, **kwargs):
        state = compile_table(*args, **kwargs)
        edge = state["edges"]["route:route1"]
        value = kwargs["params"]["wavelength"]
        edge["length_um"] = value
        if change_points and value == 1551:
            edge["points"][0][0] += 1
        return state

    monkeypatch.setattr(parameters, "compile_table", varying_table)
    if change_points:
        with pytest.raises(AnimationError, match="route:route1.*wavelength.*geometry"):
            parameters.compile_sweep(scene, "wavelength", [1549, 1551])
    else:
        table = parameters.compile_sweep(scene, "wavelength", [1549, 1551])
        assert table["edges"]["route:route1"]["length_um"] == [1549, 1551]


def test_sweep_respects_explicit_continuous_path_selection():
    scene = optodraw.Scene(width=300, height=80, platform="free_space")
    laser = scene.add(optodraw.Laser(center=(-100, 0)))
    lens = scene.add(optodraw.Lens())
    detector = scene.add(optodraw.Photodiode(center=(100, 0)))
    scene.add(optodraw.Beam((laser, "out"), (lens, "in")))
    scene.add(optodraw.Beam((lens, "out"), (detector, "in")))
    animation = Animation(scene).play(Flow(paths=["beam:beam1:0"])).click()
    animation.play(Sweep("wavelength", 1549, 1551, 1, samples=2))
    sweep = next(track for track in animation.timeline.tracks if track.type == "Sweep")
    assert sweep.args["paths"] == ["beam:beam1:0"]
