"""The tour model: stops from the payload's own events, in the order the light arrives, and a time warp."""

import functools
import warnings

import pytest

from optodraw import Scene
from optodraw.animation3d.payload import build_light_payload
from optodraw.animation3d.tour import (DRIVE_CAPTION, DRIVEN_HOLD_MAX_S, DRIVEN_PERIODS, SLOWDOWN, Stop,
                                       Tour, arrivals, auto_tour, driven_passes, hold_of, scene_tour, time_warp)
from optodraw.presets import build_preset
from optodraw.registry import build_component

pytestmark = pytest.mark.filterwarnings("ignore")


def _wire(scene, *pairs):
    for a, b in pairs:
        scene.route(a, b, kind="waveguide")


def _interferometer(detector_y):
    """Laser, Y-branch, two arms (one through a driven phase shifter), coupler, two detectors."""

    scene = Scene(width=500, height=200, platform="on_chip")
    laser = scene.add(build_component("OnChipLaser", center=(-200, 0)))
    split = scene.add(build_component("YBranch", center=(-120, 0)))
    shifter = scene.add(build_component("PhaseShifter", center=(-20, 30)))
    coupler = scene.add(build_component("DirectionalCoupler", center=(80, 0)))
    first = scene.add(build_component("OnChipPhotodetector", center=(180, detector_y[0])))
    second = scene.add(build_component("OnChipPhotodetector", center=(180, detector_y[1])))
    _wire(scene, ((laser, "o1"), (split, "o1")), ((split, "o2"), (coupler, "o1")), ((split, "o3"), (shifter, "o1")),
          ((shifter, "o2"), (coupler, "o2")), ((coupler, "o3"), (first, "o1")), ((coupler, "o4"), (second, "o1")))
    return scene


def _mzm_between_laser_and_detector():
    scene = Scene(width=400, height=160, platform="on_chip")
    laser = scene.add(build_component("OnChipLaser", center=(-150, 0)))
    mzm = scene.add(build_component("MZM", center=(0, 0)))
    det = scene.add(build_component("OnChipPhotodetector", center=(160, 0)))
    _wire(scene, ((laser, "o1"), (mzm, "o1")), ((mzm, "o3"), (det, "o1")))
    return scene


def _plain_guides():
    scene = Scene(width=500, height=200, platform="on_chip")
    laser = scene.add(build_component("OnChipLaser", center=(-200, 0)))
    guide = scene.add(build_component("Waveguide", center=(-100, 0)))
    bend = scene.add(build_component("WaveguideBend", center=(0, 0)))
    det = scene.add(build_component("OnChipPhotodetector", center=(120, 40)))
    _wire(scene, ((laser, "o1"), (guide, "o1")), ((guide, "o2"), (bend, "o1")), ((bend, "o2"), (det, "o1")))
    return scene


@functools.cache
def _built(name):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        scene = {"far": lambda: _interferometer((-20, 40)), "near": lambda: _interferometer((-10, 10)),
                 "mzm": _mzm_between_laser_and_detector, "plain": _plain_guides}[name]() if name in (
                     "far", "near", "mzm", "plain") else build_preset(name)
        return scene, build_light_payload(scene)


def _sids(tour):
    return [stop.sid for stop in tour.stops]


@pytest.mark.parametrize("name", ["ring_resonator_chip", "coherent_receiver_chip"])
def test_other_presets_give_a_short_tour_with_a_ring_stop_where_there_is_a_ring(name):
    tour = auto_tour(*_built(name))
    assert 1 <= len(tour.stops) <= 12
    if name == "ring_resonator_chip":
        assert "coupledringfilter1" in _sids(tour)


def test_a_saved_tour_wins_over_the_automatic_one():
    scene, payload = _built("far")
    assert scene_tour(scene, payload) == auto_tour(scene, payload)
    saved = Tour([Stop("directionalcoupler1", hold_s=5.0), Stop("ybranch1")], wide_s=1.0)
    scene.metadata["animation"] = {"tour": saved.to_json()}
    try:
        assert scene_tour(scene, payload) == saved
    finally:
        del scene.metadata["animation"]


def test_a_dark_detector_gets_no_stop_and_the_json_states_the_rates():
    scene, payload = _built("ring_resonator_chip")
    assert {a["part"] for a in payload["pulse"]["absorbed"]} == {"terminator1"}
    assert not [s for s in auto_tour(scene, payload).stops if "photodetector" in s.sid]
    rates = Tour().to_json()["rates"]
    assert rates["stop"] == SLOWDOWN and rates["driven_stop"] == 1.0 and rates["move"] > 1 and rates["last_wide"] == 1.0
    assert len(Tour().to_json()["captions"]) == 2 and Tour().to_json()["drive_caption"] == DRIVE_CAPTION


def test_a_driven_stop_runs_at_the_normal_rate_for_at_least_four_train_periods_up_to_12_s():
    """Ruling 46: a driven stop's hold spans DRIVEN_PERIODS train periods of physics at the normal rate, its hold grown
    for that up to DRIVEN_HOLD_MAX_S; on the mesh chip each driven stop has four pulses that cross its modulator."""

    scene, payload = _built("mzm_mesh_chip")
    tour = auto_tour(scene, payload)
    knots, period, per_ps = time_warp(tour, payload), payload["train_period_ps"], payload["seconds_per_ps"]
    passes = driven_passes(tour, payload, knots)
    driven = [i for i, stop in enumerate(tour.stops) if stop.drive]
    assert driven and sorted(passes) == driven
    for i in driven:
        (v0, p0), (v1, p1) = knots[1 + 2 * i], knots[2 + 2 * i]
        assert (p1 - p0) / (v1 - v0) == pytest.approx(1.0 / per_ps)                    # the normal rate
        assert p1 - p0 >= DRIVEN_PERIODS * period - 1e-6 or v1 - v0 == pytest.approx(DRIVEN_HOLD_MAX_S)
        assert len(passes[i]) >= 3 and passes[i] == list(range(passes[i][0], passes[i][0] + len(passes[i])))
        first = arrivals(payload)[tour.stops[i].sid]
        assert all(p0 - 1e-9 <= first + n * period <= p1 for n in passes[i])
    capped, rate = hold_of(Stop("mzm1", drive="drive:mzm1"), {**payload, "train_period_ps": 100 * period})
    assert capped == DRIVEN_HOLD_MAX_S and rate == 1.0


