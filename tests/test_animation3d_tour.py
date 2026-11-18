"""The tour model: stops from the payload's own events, in the order the light arrives, and a time warp."""

import functools
import warnings

import pytest

from optodraw import Scene
from optodraw.animation3d.payload import build_light_payload
from optodraw.animation3d.tour import (CAPTION, DRIVE_CAPTION, DRIVEN_HOLD_MAX_S, DRIVEN_PERIODS, SLOWDOWN, WIDE_S, Stop,
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


def test_the_stops_follow_the_light_through_separate_parts():
    tour = auto_tour(*_built("far"))
    assert _sids(tour) == ["ybranch1", "phaseshifter1", "directionalcoupler1", "onchipphotodetector1",
                           "onchipphotodetector2"]
    assert {stop.sid: stop.drive for stop in tour.stops} == {
        "ybranch1": None, "phaseshifter1": "heater:phaseshifter1", "directionalcoupler1": None,
        "onchipphotodetector1": None, "onchipphotodetector2": None}


def test_detectors_within_40_um_are_one_stop():
    tour = auto_tour(*_built("near"))
    assert _sids(tour) == ["ybranch1", "phaseshifter1", "directionalcoupler1", "onchipphotodetector1"]


def test_an_mzm_part_is_one_stop_with_its_drive():
    tour = auto_tour(*_built("mzm"))
    assert _sids(tour) == ["mzm1", "onchipphotodetector1"]
    assert tour.stops[0].drive == "drive:mzm1"


def test_a_plain_waveguide_and_a_bend_get_no_stop():
    assert _sids(auto_tour(*_built("plain"))) == ["onchipphotodetector1"]


def test_the_mesh_chip_has_at_most_12_stops_in_arrival_order():
    scene, payload = _built("mzm_mesh_chip")
    tour = auto_tour(scene, payload)
    assert 1 <= len(tour.stops) <= 12
    arrivals = [min(p["t0"] for k, e in payload["pulse"]["edges"].items() if k.startswith(f"path:{s.sid}:")
                    for p in e["packets"]) for s in tour.stops]
    assert arrivals == sorted(arrivals)


@pytest.mark.parametrize("name", ["ring_resonator_chip", "coherent_receiver_chip"])
def test_other_presets_give_a_short_tour_with_a_ring_stop_where_there_is_a_ring(name):
    tour = auto_tour(*_built(name))
    assert 1 <= len(tour.stops) <= 12
    if name == "ring_resonator_chip":
        assert "coupledringfilter1" in _sids(tour)


def test_a_tour_survives_json():
    tour = Tour([Stop("ybranch1"), Stop("mzm1", hold_s=1.5, drive="drive:mzm1")], wide_s=1.0)
    assert Tour.from_json(tour.to_json()) == tour
    assert tour.to_json()["caption"] == CAPTION == "Time slows at each stop"


def test_a_saved_tour_wins_over_the_automatic_one():
    scene, payload = _built("far")
    assert scene_tour(scene, payload) == auto_tour(scene, payload)
    saved = Tour([Stop("directionalcoupler1", hold_s=5.0), Stop("ybranch1")], wide_s=1.0)
    scene.metadata["animation"] = {"tour": saved.to_json()}
    try:
        assert scene_tour(scene, payload) == saved
    finally:
        del scene.metadata["animation"]


def test_the_time_warp_is_monotonic_and_slows_at_each_stop():
    scene, payload = _built("far")
    tour = auto_tour(scene, payload)
    knots = time_warp(tour, payload)
    video, physics = zip(*knots, strict=True)
    assert video[0] == 0.0 and all(a < b for a, b in zip(video, video[1:]))
    assert all(a <= b for a, b in zip(physics, physics[1:]))
    assert physics[-1] > payload["pulse"]["duration_ps"]            # physics time is not clamped to one pass
    normal = 1.0 / payload["seconds_per_ps"]
    slopes = [(q1 - q0) / (v1 - v0) for (v0, q0), (v1, q1) in zip(knots, knots[1:])]
    holds = [slopes[1 + 2 * i] for i in range(len(tour.stops))]
    slow = SLOWDOWN * normal
    for stop, rate in zip(tour.stops, holds):                       # a driven stop runs at the normal rate (Ruling 46)
        assert rate == pytest.approx(normal if stop.drive else slow), stop.sid
    assert any(stop.drive for stop in tour.stops) and any(not stop.drive for stop in tour.stops)
    assert max(s for i, s in enumerate(slopes) if i not in range(1, 2 * len(tour.stops), 2)) > slow
    assert video[1] == pytest.approx(tour.wide_s) and video[-1] - video[-2] == pytest.approx(tour.wide_s)
    assert tour.wide_s == WIDE_S


def test_a_longer_hold_lengthens_that_stop_at_the_slow_rate():
    scene, payload = _built("far")
    tour = auto_tour(scene, payload)
    assert not tour.stops[2].drive
    longer = Tour([Stop(s.sid, 6.0 if i == 2 else s.hold_s, s.drive) for i, s in enumerate(tour.stops)], tour.wide_s)
    base, more = time_warp(tour, payload), time_warp(longer, payload)
    assert more[6][0] - more[5][0] == pytest.approx(6.0)                                        # the third hold
    assert more[6][1] - more[5][1] == pytest.approx(SLOWDOWN * 6.0 / payload["seconds_per_ps"])  # at the slow rate
    assert more[5] == base[5]                                                                   # earlier knots are unchanged


def test_a_tour_with_no_stops_is_one_wide_view():
    scene, payload = _built("far")
    knots = time_warp(Tour([]), payload)
    assert knots[0][0] == 0.0 and len(knots) == 2 and knots[-1][1] == pytest.approx(payload["pulse"]["duration_ps"])


def test_no_hold_freezes_on_the_mesh_chip_and_each_shows_moving_light():
    scene, payload = _built("mzm_mesh_chip")
    tour = auto_tour(scene, payload)
    knots = time_warp(tour, payload)
    holds = [(knots[2 + 2 * i], knots[1 + 2 * i]) for i in range(len(tour.stops))]
    assert all((b[1] - a[1]) / (b[0] - a[0]) > 0 and b[1] - a[1] >= payload["pulse_ps"] for b, a in holds)


def test_a_dark_detector_gets_no_stop_and_the_json_states_the_rates():
    scene, payload = _built("ring_resonator_chip")
    assert {a["part"] for a in payload["pulse"]["absorbed"]} == {"terminator1"}
    assert not [s for s in auto_tour(scene, payload).stops if "photodetector" in s.sid]
    rates = Tour().to_json()["rates"]
    assert rates["stop"] == SLOWDOWN and rates["driven_stop"] == 1.0 and rates["move"] > 1 and rates["last_wide"] == 1.0
    assert len(Tour().to_json()["captions"]) == 2 and Tour().to_json()["drive_caption"] == DRIVE_CAPTION


@pytest.mark.parametrize("name", ["mzm_mesh_chip", "ring_resonator_chip"])
def test_a_packet_front_reaches_the_part_during_every_hold(name):
    scene, payload = _built(name)
    tour = auto_tour(scene, payload)
    knots = time_warp(tour, payload)
    first, period = arrivals(payload), payload["train_period_ps"]
    for i, stop in enumerate(tour.stops):
        reach, end = knots[1 + 2 * i][1], knots[2 + 2 * i][1]
        fronts = [first[stop.sid] + k * period for k in range(200)]
        assert any(reach - 1e-9 <= f <= end - payload["pulse_ps"] for f in fronts), (stop.sid, reach, end)


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


def test_without_swinging_drives_a_driven_stop_holds_as_an_undriven_one():
    scene, payload = _built("mzm_mesh_chip")
    tour = auto_tour(scene, payload)
    plain, swung = time_warp(tour, payload, driven=False), time_warp(tour, payload)
    i = next(k for k, stop in enumerate(tour.stops) if stop.drive)
    (v0, p0), (v1, p1) = plain[1 + 2 * i], plain[2 + 2 * i]
    assert v1 - v0 == pytest.approx(tour.stops[i].hold_s)
    assert (p1 - p0) / (v1 - v0) == pytest.approx(SLOWDOWN / payload["seconds_per_ps"])
    assert swung[2 + 2 * i][0] - swung[1 + 2 * i][0] > v1 - v0


def test_a_page_without_drive_tables_holds_its_driven_stops_slowly():
    scene, payload = _built("mzm_mesh_chip")
    assert payload["tour_warp"] == [list(k) for k in time_warp(scene_tour(scene, payload), payload, driven=False)]
