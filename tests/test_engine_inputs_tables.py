import copy

import pytest

import optodraw
from optodraw.animation_engine import AnimationError, compile_signal_state
from optodraw.animation_engine.inputs import InputSignal
from optodraw.animation_engine.solver import C_UM_PER_PS
from optodraw.animation_engine.tables import compile_table


def test_external_input_enters_the_coupler_without_changing_the_scene():
    scene = optodraw.Scene(width=260, height=80, platform="on_chip")
    coupler = scene.add(optodraw.VerticalGratingCoupler(center=(-90, 0), angle=180))
    detector = scene.add(optodraw.OnChipPhotodetector(center=(90, 0)))
    scene.route((coupler, "o1"), (detector, "o1"), kind="waveguide")
    before = copy.deepcopy(scene.to_spec())
    source = InputSignal("port:verticalgratingcoupler1:f1", wavelength_nm=1550.0)
    for mode in ("pulse", "cw"):
        table = compile_table(scene, mode=mode, inputs=[source])
        assert table["absorbed"][0]["power"] == pytest.approx(0.5)
        assert "path:verticalgratingcoupler1:f1->o1" in table["edges"]
    assert scene.to_spec() == before


def test_continuous_front_includes_internal_and_route_delays():
    scene = optodraw.Scene(width=300, height=100, platform="free_space")
    laser = scene.add(optodraw.Laser(center=(-100, 0)))
    lens = scene.add(optodraw.Lens(center=(0, 0)))
    detector = scene.add(optodraw.Photodiode(center=(100, 0)))
    scene.add(optodraw.Beam((laser, "out"), (lens, "in")))
    scene.add(optodraw.Beam((lens, "out"), (detector, "in")))
    table = compile_table(scene, mode="cw")
    first = table["edges"]["beam:beam1:0"]
    inside = table["edges"]["path:lens1:in->out"]
    last = table["edges"]["beam:beam2:0"]
    a, b, c = first["cw"][0], inside["cw"][0], last["cw"][0]
    assert a["t0"] == 0.0
    assert a["t1"] == pytest.approx(first["length_um"] / C_UM_PER_PS)
    assert b["t0"] == pytest.approx(a["t1"])
    assert c["t0"] == pytest.approx(b["t1"])
    assert table["absorbed"][0]["t_ps"] == pytest.approx(c["t1"])


def test_reverse_route_traversal_retains_canonical_geometry():
    scene = optodraw.Scene(width=300, height=80, platform="on_chip")
    laser = scene.add(optodraw.OnChipLaser(center=(-100, 0)))
    detector = scene.add(optodraw.OnChipPhotodetector(center=(100, 0)))
    route = scene.route((detector, "o1"), (laser, "o1"), kind="waveguide")
    table = compile_table(scene, mode="pulse")
    edge = table["edges"]["route:route1"]
    packet = edge["packets"][0]
    assert packet["reverse"] is True
    assert packet["from"] == "port:onchiplaser1:o1"
    assert edge["points"] == [list(point[:2]) for point in route.resolve_points()]
    assert packet["shape"] == "gauss"


def test_timeline_adaptation_does_not_change_m1_amplitudes():
    scene = optodraw.Scene(width=240, height=80, platform="on_chip")
    laser = scene.add(optodraw.OnChipLaser(center=(-90, 0)))
    detector = scene.add(optodraw.OnChipPhotodetector(center=(90, 0)))
    scene.route((laser, "o1"), (detector, "o1"), kind="waveguide")
    for mode, records in (("pulse", "packets"), ("cw", "cw")):
        original = compile_signal_state(scene, mode=mode).to_json()
        table = compile_table(scene, mode=mode)
        expected = original["edges"]["route:route1"][records][0]["jones"]
        assert table["edges"]["route:route1"][records][0]["jones"] == expected


def test_invalid_input_and_missing_behaviour_are_named_errors():
    scene = optodraw.Scene(width=240, height=80, platform="on_chip")
    part = scene.add(optodraw.VerticalGratingCoupler())
    with pytest.raises(AnimationError, match="verticalgratingcoupler1.*missing"):
        compile_table(scene, mode="cw", inputs=[InputSignal("port:verticalgratingcoupler1:missing")])
    part.component_type = "UnknownInput"
    with pytest.raises(AnimationError, match="unknowninput1.*no behaviour"):
        compile_table(scene, mode="cw", inputs=[InputSignal("port:unknowninput1:f1")])


def test_equal_wavelength_inputs_add_coherently():
    scene = optodraw.Scene(width=240, height=80, platform="on_chip")
    inlet = scene.add(optodraw.VerticalGratingCoupler(center=(-90, 0), angle=180))
    detector = scene.add(optodraw.OnChipPhotodetector(center=(90, 0)))
    scene.route((inlet, "o1"), (detector, "o1"), kind="waveguide")
    source = InputSignal("port:verticalgratingcoupler1:f1")
    result = compile_table(scene, mode="cw", inputs=[source, source])
    assert result["absorbed"][0]["power"] == pytest.approx(2.0)


def test_continuous_ring_front_finishes_without_unrolling_the_loop():
    scene = optodraw.Scene(width=300, height=100, platform="on_chip")
    laser = scene.add(optodraw.OnChipLaser(center=(-100, 0)))
    ring = scene.add(optodraw.MicroringResonator(center=(0, 0)))
    detector = scene.add(optodraw.OnChipPhotodetector(center=(100, 0)))
    scene.route((laser, "o1"), (ring, "o1"), kind="waveguide")
    scene.route((ring, "o2"), (detector, "o1"), kind="waveguide")
    table = compile_table(scene, mode="cw")
    loop = table["edges"]["path:microringresonator1:_ring->_ring"]["cw"][0]
    assert loop["t1"] > loop["t0"] >= 0.0
    assert table["duration_ps"] > 0.0


@pytest.mark.parametrize("mode", ["pulse", "cw"])
def test_open_port_has_outward_geometry_and_a_named_warning(mode):
    scene = optodraw.Scene(width=120, height=80, platform="on_chip")
    laser = scene.add(optodraw.OnChipLaser(angle=90))
    with pytest.warns(RuntimeWarning, match="onchiplaser1.*o1"):
        table = compile_table(scene, mode=mode)
    departure = table["exits"][0]
    origin, end = departure["points"]
    port = laser.world_port("o1")
    assert origin == pytest.approx([port.center.x, port.center.y])
    assert end[0] == pytest.approx(origin[0], abs=1e-9)
    assert end[1] > origin[1]
    assert departure["jones"][0] ** 2 + departure["jones"][1] ** 2 == pytest.approx(1.0)    # full power, the emission edge's phase
    assert departure["jones"][2:] == [0, 0]
    assert departure["visual_only"] is True
    assert table["warnings"][0]["port"] == "o1"


@pytest.mark.parametrize("mode", ["pulse", "cw"])
def test_strict_open_port_is_an_error_not_absorption(mode):
    scene = optodraw.Scene(width=120, height=80, platform="on_chip")
    scene.add(optodraw.OnChipLaser())
    with pytest.raises(AnimationError, match="onchiplaser1.*o1"):
        compile_signal_state(scene, mode=mode, strict=True)


def test_connected_detector_does_not_produce_an_exit_warning():
    scene = optodraw.Scene(width=240, height=80, platform="on_chip")
    laser = scene.add(optodraw.OnChipLaser(center=(-90, 0)))
    detector = scene.add(optodraw.OnChipPhotodetector(center=(90, 0)))
    scene.route((laser, "o1"), (detector, "o1"), kind="waveguide")
    table = compile_table(scene, mode="cw", strict=True)
    assert table["exits"] == [] and table["warnings"] == []
