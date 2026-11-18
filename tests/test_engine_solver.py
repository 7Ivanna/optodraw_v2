"""The solvers: light from the sources, through the parts, to the detectors, with the physics."""


import numpy as np
import pytest

import optodraw
from optodraw.animation_engine import AnimationError
from optodraw.animation_engine.graph import build_graph
from optodraw.animation_engine.solver import propagate_pulses, steady_state


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


