"""The solvers: light from the sources, through the parts, to the detectors, with the physics."""

import cmath
import math

import numpy as np
import pytest

import optodraw
from optodraw.animation_engine import AnimationError, compile_signal_state
from optodraw.animation_engine.graph import build_graph
from optodraw.animation_engine.signals import power
from optodraw.animation_engine.solver import C_UM_PER_PS, check_passivity, propagate_pulses, steady_state


def _chip_line():
    scene = optodraw.Scene(width=300, height=80, platform="on_chip")
    laser = scene.add(optodraw.OnChipLaser(center=(-120, 0)))
    pd = scene.add(optodraw.OnChipPhotodetector(center=(120, 0)))
    route = scene.route((laser, "o1"), (pd, "o1"), kind="waveguide")
    return scene, route


def test_a_pulse_takes_length_times_index_over_c():
    scene, route = _chip_line()
    result = propagate_pulses(build_graph(scene))
    (packet,) = [p for p in result.packets if p.edge == "route:route1"]
    length = math.dist(*[(p[0], p[1]) for p in (route.resolve_points()[0], route.resolve_points()[-1])])
    assert packet.t1_ps - packet.t0_ps == pytest.approx(result.edges["route:route1"]["length_um"] * 4.2 / C_UM_PER_PS)
    assert result.edges["route:route1"]["length_um"] >= length - 1e-9
    (hit,) = result.absorbed
    assert hit["part"] == "onchipphotodetector1" and hit["power"] == pytest.approx(1.0)


def test_a_beam_splitter_sends_half_to_each_detector():
    scene = optodraw.Scene(width=200, height=160, platform="free_space")
    laser = scene.add(optodraw.Laser(center=(-60, 0)))
    bs = scene.add(optodraw.BeamSplitter(center=(0, 0)))
    pd1 = scene.add(optodraw.Photodiode(center=(60, 0)))
    pd2 = scene.add(optodraw.Photodiode(center=(0, -60), angle=90))
    scene.add(optodraw.Beam((laser, "out"), (bs, "in"), (bs, "trans"), (pd1, "in")))
    scene.add(optodraw.Beam((bs, "refl"), (pd2, "in")))
    result = propagate_pulses(build_graph(scene))
    assert sorted(h["power"] for h in result.absorbed) == pytest.approx([0.5, 0.5])


def test_a_focusing_beam_carries_the_light_like_a_beam():
    scene = optodraw.Scene(width=200, height=80, platform="free_space")
    laser = scene.add(optodraw.Laser(center=(-60, 0)))
    lens = scene.add(optodraw.Lens(center=(0, 0)))
    pd = scene.add(optodraw.Photodiode(center=(60, 0)))
    scene.add(optodraw.Beam(laser, lens))
    scene.add(optodraw.FocusingBeam(lens, pd))
    result = propagate_pulses(build_graph(scene))
    assert [h["part"] for h in result.absorbed] == ["photodiode1"] and not result.exits


def test_light_leaving_an_unconnected_port_exits_the_drawing():
    scene = optodraw.Scene(width=200, height=160, platform="free_space")
    laser = scene.add(optodraw.Laser(center=(-60, 0)))
    bs = scene.add(optodraw.BeamSplitter(center=(0, 0)))
    pd1 = scene.add(optodraw.Photodiode(center=(60, 0)))
    scene.add(optodraw.Beam((laser, "out"), (bs, "in"), (bs, "trans"), (pd1, "in")))
    result = propagate_pulses(build_graph(scene))
    assert [(e["part"], e["port"]) for e in result.exits] == [("beamsplitter1", "refl")]


def test_the_two_arms_of_an_mzi_interfere_at_its_output():
    scene = optodraw.Scene(width=360, height=160, platform="on_chip")
    laser = scene.add(optodraw.OnChipLaser(center=(-150, 0)))
    mzi = scene.add(optodraw.MZI(center=(0, 0)))
    d3 = scene.add(optodraw.OnChipPhotodetector(center=(160, 40)))
    d4 = scene.add(optodraw.OnChipPhotodetector(center=(160, -40)))
    scene.route((laser, "o1"), (mzi, "o1"), kind="waveguide")
    scene.route((mzi, "o3"), (d3, "o1"), kind="waveguide")
    scene.route((mzi, "o4"), (d4, "o1"), kind="waveguide")
    result = propagate_pulses(build_graph(scene), {"phase:mzi1:arm1": math.pi / 2})
    by = {h["part"]: h["power"] for h in result.absorbed}
    assert by["onchipphotodetector1"] + by["onchipphotodetector2"] == pytest.approx(1.0)
    assert by["onchipphotodetector1"] == pytest.approx(0.5)              # sin^2(pi/4) on o3


@pytest.mark.parametrize("wavelength", [1549.0, 1549.6, 1550.0, 1550.3])
def test_two_couplers_in_a_row_keep_all_the_power(wavelength):
    """Two lossless couplers make an MZI: whatever the phases, the detectors get all the light."""

    scene = optodraw.Scene(width=500, height=160, platform="on_chip")
    laser = scene.add(optodraw.OnChipLaser(center=(-140, 7)))
    dc1 = scene.add(optodraw.DirectionalCoupler(center=(0, 0)))
    dc2 = scene.add(optodraw.DirectionalCoupler(center=(200, 0)))
    d3 = scene.add(optodraw.OnChipPhotodetector(center=(340, 50)))
    d4 = scene.add(optodraw.OnChipPhotodetector(center=(340, -50)))
    scene.route((laser, "o1"), (dc1, "o1"), kind="waveguide")
    scene.route((dc1, "o3"), (dc2, "o1"), kind="waveguide")
    scene.route((dc1, "o4"), (dc2, "o2"), kind="waveguide")
    scene.route((dc2, "o3"), (d3, "o1"), kind="waveguide")
    scene.route((dc2, "o4"), (d4, "o1"), kind="waveguide")
    data = compile_signal_state(scene, mode="cw", params={"wavelength": wavelength}).to_json()
    assert sum(hit["power"] for hit in data["absorbed"]) == pytest.approx(1.0)


def test_a_ring_rings_down_round_trip_by_round_trip():
    scene = optodraw.Scene(width=300, height=120, platform="on_chip")
    laser = scene.add(optodraw.OnChipLaser(center=(-120, 0)))
    ring = scene.add(optodraw.MicroringResonator(center=(0, 0)))
    pd = scene.add(optodraw.OnChipPhotodetector(center=(120, 0)))
    scene.route((laser, "o1"), (ring, "o1"), kind="waveguide")
    scene.route((ring, "o2"), (pd, "o1"), kind="waveguide")
    result = propagate_pulses(build_graph(scene))
    loops = sorted((p for p in result.packets if p.edge == "path:microringresonator1:_ring->_ring"), key=lambda p: p.t0_ps)
    assert len(loops) > 3
    powers = [power(p.jones) for p in loops]
    assert all(b < a for a, b in zip(powers, powers[1:]))                # each trip fades


def test_no_source_is_a_named_error():                                       # Review Focus 1
    scene = optodraw.Scene(width=100, height=60, platform="free_space")
    scene.add(optodraw.Lens(center=(0, 0)))
    with pytest.raises(AnimationError, match="^the scene has no light source$"):
        propagate_pulses(build_graph(scene))


def test_light_that_comes_back_into_an_isolator_is_absorbed():
    scene = optodraw.Scene(width=200, height=80, platform="free_space")
    laser = scene.add(optodraw.Laser(center=(-60, 0)))
    iso = scene.add(optodraw.OpticalIsolator(center=(0, 0), angle=180))   # mounted backwards
    scene.add(optodraw.Beam((laser, "out"), (iso, "out")))
    result = propagate_pulses(build_graph(scene))
    assert result.absorbed[0]["part"] == "opticalisolator1"


def test_light_arriving_where_a_part_does_nothing_is_a_named_error():
    from optodraw.animation_engine.behaviours import Behaviour

    scene = optodraw.Scene(width=200, height=80, platform="free_space")
    laser = scene.add(optodraw.Laser(center=(-60, 0)))
    lens = scene.add(optodraw.Lens(center=(0, 0)))
    scene.add(optodraw.Beam((laser, "out"), (lens, "in")))
    lens.animation_behaviour = lambda: Behaviour()                         # transmits nothing, absorbs nothing
    with pytest.raises(AnimationError, match=r"^lens1: light arrives at in and has nowhere to go$"):
        propagate_pulses(build_graph(scene))


def test_light_that_leaves_before_it_enters_is_a_named_error():
    import numpy as np

    from optodraw.animation_engine.solver import Packet, Propagation, check_causality

    bad = Propagation(packets=[Packet("route:route1", ("laser1", "out"), ("lens1", "in"), 2.0, 1.0,
                                      np.array([1, 0], dtype=complex), 633.0, 0.2, "laser1")])
    with pytest.raises(AnimationError, match=r"^laser1: light leaves route:route1 before it enters$"):
        check_causality(bad)


def _loop_scene(gain_db):
    scene = optodraw.Scene(width=300, height=200, platform="free_space")
    laser = scene.add(optodraw.Laser(center=(-100, 0)))
    c1 = scene.add(optodraw.FiberCoupler(center=(0, 0)))
    amp = scene.add(optodraw.FiberAmplifier(center=(0, 80), gain_db=gain_db))
    scene.add(optodraw.Beam((laser, "out"), (c1, "in1")))
    scene.route((c1, "out1"), (amp, "in"), kind="fiber")
    scene.route((amp, "out"), (c1, "in2"), kind="fiber")
    return scene


def test_a_lossy_loop_ends_and_a_gain_loop_is_a_named_error():              # Review Focus 3
    assert propagate_pulses(build_graph(_loop_scene(-3.0))).packets          # it ends
    with pytest.raises(AnimationError, match=r"^(fibercoupler1|fiberamplifier1): light keeps circulating"):
        propagate_pulses(build_graph(_loop_scene(10.0)), max_events=5_000)


def test_continuous_light_in_a_gain_loop_has_no_steady_state_and_says_so():
    assert steady_state(build_graph(_loop_scene(-3.0))).exits                # a lossy loop settles
    with pytest.raises(AnimationError, match=r"^(fibercoupler1|fiberamplifier1): the light has no steady state"):
        steady_state(build_graph(_loop_scene(10.0)))


def _ring_scene():
    scene = optodraw.Scene(width=300, height=120, platform="on_chip")
    laser = scene.add(optodraw.OnChipLaser(center=(-120, 0)))
    ring = scene.add(optodraw.MicroringResonator(center=(0, 0)))
    pd = scene.add(optodraw.OnChipPhotodetector(center=(120, 0)))
    scene.route((laser, "o1"), (ring, "o1"), kind="waveguide")
    scene.route((ring, "o2"), (pd, "o1"), kind="waveguide")
    return scene, ring


@pytest.mark.parametrize("wavelength", [1549.0, 1549.5, 1550.0, 1550.5])
def test_the_steady_ring_matches_the_all_pass_formula(wavelength):
    scene, ring = _ring_scene()
    result = steady_state(build_graph(scene), {"wavelength": wavelength})
    loop = result.edges["path:microringresonator1:_ring->_ring"]["length_um"]
    theta = 2 * math.pi * 4.2 * loop / (wavelength / 1000.0)
    t, a = math.sqrt(0.9), 0.99
    expected = abs((t - a * cmath.exp(1j * theta)) / (1 - t * a * cmath.exp(1j * theta))) ** 2
    (hit,) = result.absorbed
    assert hit["power"] == pytest.approx(expected, rel=1e-6)


@pytest.mark.parametrize("angle", [0.0, 45.0, 75.0])
def test_steady_malus_through_a_polarizer(angle):
    scene = optodraw.Scene(width=200, height=80, platform="free_space")
    laser = scene.add(optodraw.Laser(center=(-60, 0)))
    pol = scene.add(optodraw.Polarizer(center=(0, 0)))
    pd = scene.add(optodraw.Photodiode(center=(60, 0)))
    scene.add(optodraw.Beam(laser, pol, pd))
    result = steady_state(build_graph(scene), {"angle:polarizer1": angle})
    assert result.absorbed[0]["power"] == pytest.approx(math.cos(math.radians(angle)) ** 2, abs=2e-3)


def test_passive_parts_pass_the_passivity_check_and_a_bad_one_fails():
    scene, ring = _ring_scene()
    graph = build_graph(scene)
    check_passivity(graph, steady_state(graph))                                # no error
    from optodraw.animation_engine.behaviours import Behaviour, Transfer
    from optodraw.animation_engine.signals import scalar

    class Doubler(Behaviour):
        def transfers(self, part, sid, in_port, wavelength_nm, params):
            other = "o2" if in_port == "o1" else "o1"
            return [Transfer(in_port, other, scalar(2.0), ((0, 0), (1, 0)))]
    ring.animation_behaviour = lambda: Doubler()
    with pytest.raises(AnimationError, match=r"^microringresonator1: a passive part gives out more power"):
        check_passivity(graph, steady_state(graph))


@pytest.mark.parametrize("together", ["two inputs", "two polarisations"])
def test_passivity_sees_power_made_by_inputs_added_together(together):
    """Each input alone gives out at most its power; two inputs in phase give out double."""

    from optodraw.animation_engine.behaviours import Behaviour, Transfer
    from optodraw.animation_engine.signals import scalar

    class Combiner(Behaviour):
        def transfers(self, part, sid, in_port, wavelength_nm, params):
            if together == "two inputs":
                return [Transfer(in_port, "o3", scalar(1.0), ((0, 0), (1, 0)))] if in_port in ("o1", "o2") else []
            both = np.array([[1, 1], [0, 0]], dtype=complex)                  # H and V both into H
            return [Transfer(in_port, "o3", both, ((0, 0), (1, 0)))] if in_port == "o1" else []

    scene = optodraw.Scene(width=300, height=120, platform="on_chip")
    laser = scene.add(optodraw.OnChipLaser(center=(-120, 0)))
    dc = scene.add(optodraw.DirectionalCoupler(center=(0, 0)))
    pd = scene.add(optodraw.OnChipPhotodetector(center=(120, 0)))
    scene.route((laser, "o1"), (dc, "o1"), kind="waveguide")
    scene.route((dc, "o3"), (pd, "o1"), kind="waveguide")
    dc.animation_behaviour = lambda: Combiner()
    graph = build_graph(scene)
    with pytest.raises(AnimationError, match=r"^directionalcoupler1: a passive part gives out more power"):
        check_passivity(graph, steady_state(graph))


def test_light_that_comes_back_to_a_laser_is_absorbed_there():
    """A Michelson sends light back to its source: the ftir preset raised 'nowhere to go' at the laser."""

    scene = optodraw.Scene(width=200, height=80, platform="free_space")
    laser = scene.add(optodraw.Laser(center=(-60, 0)))
    retro = scene.add(optodraw.Retroreflector(center=(60, 0)))
    scene.add(optodraw.Beam((laser, "out"), (retro, "io")))
    result = propagate_pulses(build_graph(scene))
    assert [h["part"] for h in result.absorbed] == ["laser1"]
    assert result.absorbed[0]["power"] == pytest.approx(0.99)


def test_a_plot_target_on_a_chip_detector_port_gives_its_received_power():
    """The detector absorbs on an internal port, so ``port:<detector>:o1`` must still read the power that arrives."""

    from optodraw.animation_engine.parameters import compile_sweep, plot_values

    scene = optodraw.Scene(width=300, height=80, platform="on_chip")
    laser = scene.add(optodraw.OnChipLaser(center=(-120, 0)))
    detector = scene.add(optodraw.OnChipPhotodetector(center=(120, 0)))
    scene.route((laser, "o1"), (detector, "o1"), kind="waveguide")
    table = compile_sweep(scene, "angle:onchiplaser1", [0.0, 45.0, 90.0])
    assert table["absorbed"], "the detector absorbs"
    by_part = plot_values(table, {"name": "power", "target": "part:onchipphotodetector1"})
    by_port = plot_values(table, {"name": "power", "target": "port:onchipphotodetector1:o1"})
    assert by_part == pytest.approx([1.0, 1.0, 1.0])               # from the absorbed records
    assert by_port == pytest.approx(by_part)


def _carried_scene():
    """A laser, a lens whose matrix holds its whole phase (1j from in to out at every wavelength), a detector."""

    from optodraw.animation_engine.behaviours import Behaviour, Transfer
    from optodraw.animation_engine.behaviours.geometry import through_anchor
    from optodraw.animation_engine.signals import scalar

    class Carried(Behaviour):
        def transfers(self, part, sid, in_port, wavelength_nm, params):
            if in_port != "in":
                return []
            return [Transfer("in", "out", scalar(1j), through_anchor(part, "in", "out"), group_index=4.0,
                             phase_included=True)]

    scene = optodraw.Scene(width=200, height=80, platform="free_space")
    laser = scene.add(optodraw.Laser(center=(-60, 0)))
    lens = scene.add(optodraw.Lens(center=(0, 0)))
    pd = scene.add(optodraw.Photodiode(center=(60, 0)))
    scene.add(optodraw.Beam((laser, "out"), (lens, "in"), (lens, "out"), (pd, "in")))
    lens.animation_behaviour = lambda: Carried()
    return scene


@pytest.mark.parametrize("wavelength", [1550.0, 1551.0])
def test_a_transfer_that_carries_its_phase_gets_no_length_phase(wavelength):
    from optodraw.animation_engine.solver import phase_factor

    result = steady_state(build_graph(_carried_scene()), {"wavelength": wavelength})
    (into,) = [s for s in result.steady if s.start == ("laser1", "out")]
    (out,) = [s for s in result.steady if s.start == ("lens1", "out")]
    link = result.edges[into.edge]
    arrived = into.jones[0] * phase_factor(link["length_um"], link["group_index"], wavelength)
    ratio = out.jones[0] / arrived                                  # what the lens itself does to the field
    assert abs(ratio) == pytest.approx(1.0) and cmath.phase(ratio) == pytest.approx(math.pi / 2, abs=1e-12)
    (hit,) = result.absorbed
    assert hit["part"] == "photodiode1" and hit["power"] == pytest.approx(1.0)


def test_a_transfer_that_carries_its_phase_keeps_its_delay():
    result = propagate_pulses(build_graph(_carried_scene()), {"wavelength": 1550.0})
    (packet,) = [p for p in result.packets if p.edge == "path:lens1:in->out"]
    length = result.edges[packet.edge]["length_um"]
    assert length > 0 and packet.t1_ps - packet.t0_ps == pytest.approx(length * 4.0 / C_UM_PER_PS)
