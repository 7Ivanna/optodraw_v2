"""A heater raises the index: the light in the heated section lags in phase and arrives later, from one index change.

A heated transfer's delay is ``phase * wavelength / (2 pi c)``; the solver adds it to the arrival only, never to the
phase (the phase already holds the heater's shift). A ring's heater adds to its ``phase`` key."""

import cmath
import math

import pytest

import optodraw
from optodraw.animation_engine import compile_signal_state
from optodraw.animation_engine.behaviours import find_behaviour
from optodraw.animation_engine.behaviours.interferometers import heater_phase
from optodraw.animation_engine.tables import compile_table
from optodraw.components.onchip.rings import CoupledRingFilter, MicroringResonator
from optodraw.registry import build_component

# The engine's speed of light, 299.792458 um per ps. The brief's check value uses 3e8 m/s: pi at 1550 nm is then
# 0.0025833 ps, against 0.0025851 ps with the engine's c (1.8e-6 ps apart, 0.07 %; the brief's tolerance is 1e-9 ps).
C_UM_PER_PS = 299.792458


def delay_ps(phase: float, nm: float = 1550.0) -> float:
    return phase * nm * 1e-3 / (2.0 * math.pi * C_UM_PER_PS)


def _mzi_scene():
    scene = optodraw.Scene(width=360, height=160, platform="on_chip")
    laser = scene.add(optodraw.OnChipLaser(center=(-150, 0)))
    mzi = scene.add(optodraw.MZI(center=(0, 0)))
    det = scene.add(optodraw.OnChipPhotodetector(center=(160, 40)))
    scene.route((laser, "o1"), (mzi, "o1"), kind="waveguide")
    scene.route((mzi, "o3"), (det, "o1"), kind="waveguide")
    return scene


def _arm1(state):
    return {eid for eid in state["edges"] if eid.startswith("path:mzi1:") and eid.endswith("#arm1")}


def test_the_check_value_is_the_briefs_with_the_engines_speed_of_light():
    assert delay_ps(math.pi) == pytest.approx(math.pi * 1.55e-6 / (2 * math.pi * 3e8) * 1e12, rel=1e-3)
    assert delay_ps(math.pi) == pytest.approx(0.00258512, abs=1e-8)


@pytest.mark.filterwarnings("ignore:.*unconnected port:RuntimeWarning")
def test_a_heated_arm_arrives_later_by_the_heaters_delay_and_keeps_its_phase():
    scene = _mzi_scene()
    heated = compile_signal_state(scene, params={"heater:mzi1": 20.0}).to_json()           # 20 mW is pi
    shifted = compile_signal_state(scene, params={"phase:mzi1:arm1": math.pi}).to_json()   # the same phase, no heater
    assert heated["edges"].keys() == shifted["edges"].keys() and _arm1(heated)
    for eid, edge in heated["edges"].items():
        for a, b in zip(edge["packets"], shifted["edges"][eid]["packets"], strict=True):
            assert a["jones"] == pytest.approx(b["jones"], abs=1e-12)                     # the phase is unchanged
            assert a["t0"] == pytest.approx(b["t0"], abs=1e-12)
            lag = delay_ps(math.pi) if eid in _arm1(heated) else 0.0
            assert a["t1"] - b["t1"] == pytest.approx(lag, abs=1e-9)


@pytest.mark.filterwarnings("ignore:.*unconnected port:RuntimeWarning")
def test_the_steady_state_fronts_carry_the_same_delay():
    scene = _mzi_scene()
    heated = compile_table(scene, mode="cw", params={"heater:mzi1": 20.0})
    shifted = compile_table(scene, mode="cw", params={"phase:mzi1:arm1": math.pi})
    for eid in _arm1(heated):
        for a, b in zip(heated["edges"][eid]["cw"], shifted["edges"][eid]["cw"], strict=True):
            assert a["t1"] - b["t1"] == pytest.approx(delay_ps(math.pi), abs=1e-9)
            assert a["jones"] == pytest.approx(b["jones"], abs=1e-12)


@pytest.mark.filterwarnings("ignore:.*unconnected port:RuntimeWarning")
def test_a_display_scale_multiplies_the_delay_and_not_the_phase():
    scene = _mzi_scene()
    true = compile_signal_state(scene, params={"heater:mzi1": 20.0}).to_json()
    shown = compile_signal_state(scene, params={"heater:mzi1": 20.0}, heater_delay_scale=100.0).to_json()
    for eid in _arm1(true):
        for a, b in zip(shown["edges"][eid]["packets"], true["edges"][eid]["packets"], strict=True):
            assert a["t1"] - b["t1"] == pytest.approx(99.0 * delay_ps(math.pi), abs=1e-9)
            assert a["jones"] == pytest.approx(b["jones"], abs=1e-12)


def _transfers(part, sid, params, nm=1550.0):
    """Every transfer of a part, by (in port, out port, name): from each optical port and each internal port reached."""

    behaviour = find_behaviour(part)
    todo = [name for name, spec in part.ports().items() if spec.kind != "electrical"]
    seen, found = set(), {}
    while todo:
        port = todo.pop()
        if port in seen:
            continue
        seen.add(port)
        for t in behaviour.transfers(part, sid, port, nm, params):
            found[(t.in_port, t.out_port, t.name)] = t
            if t.out_port.startswith("_"):
                todo.append(t.out_port)
    return found


def _ramzi():
    from optodraw.components.onchip.modulators import RingAssistedMZI

    return RingAssistedMZI(center=(0, 0), rings_per_arm=(1, 1), with_heaters=True)


def _bank():
    from optodraw.components.onchip.rings import MicroringWeightBank

    return MicroringWeightBank(ring_count=3)


HEATED = {                           # label: (part, sid, heater parameters)
    "phase shifter": (lambda: build_component("PhaseShifter"), "ps", {"heater:ps": 10.0}),
    "MZI arm": (lambda: optodraw.MZI(center=(0, 0)), "mzi", {"heater:mzi": 10.0}),
    "ring-assisted MZI arm": (_ramzi, "ramzi", {"heater:ramzi": 10.0}),
    "ring-assisted MZI ring": (_ramzi, "ramzi", {"heater:ramzi:ring2": 10.0}),
    "all-pass ring": (lambda: MicroringResonator(with_heater=True), "ring", {"heater:ring": 10.0}),
    "add-drop ring": (lambda: MicroringResonator(add_drop=True, with_heater=True), "ring", {"heater:ring": 10.0}),
    "coupled ring filter": (lambda: CoupledRingFilter(order=3), "crf", {"heater:crf:ring2": 10.0}),
    "weight bank ring": (_bank, "bank", {"heater:bank:ring2": 10.0}),
}


@pytest.mark.parametrize("make,sid,params", [pytest.param(*case, id=label) for label, case in HEATED.items()])
def test_every_heated_section_gets_the_delay_of_the_phase_its_heater_adds(make, sid, params):
    """On every transfer the delay is the heater's share of the phase over 2 pi c: a whole trip or a half trip of a
    ring, a whole arm; a transfer the heater does not reach has none."""

    part = make()
    cold, hot = _transfers(part, sid, {}), _transfers(part, sid, params)
    assert cold.keys() == hot.keys()
    delayed = 0
    for key, t in hot.items():
        assert cold[key].extra_delay_ps == 0.0
        before, after = complex(cold[key].matrix[0, 0]), complex(t.matrix[0, 0])
        added = cmath.phase(after / before) if abs(before) > 1e-12 else 0.0
        assert t.extra_delay_ps == pytest.approx(delay_ps(added), abs=1e-12), key
        delayed += t.extra_delay_ps > 0
    assert delayed


@pytest.mark.parametrize("params", [{"drive:mzm": 1.0}, {"phase:mzi:arm1": 1.0, "heater:mzi": 10.0}, {"phase:ps": 1.0, "heater:ps": 10.0}],
                         ids=["MZM drive", "MZI phase key", "phase shifter phase key"])
def test_a_drive_or_a_phase_key_adds_no_delay(params):
    parts = {"mzm": build_component("MZM"), "mzi": optodraw.MZI(center=(0, 0)), "ps": build_component("PhaseShifter")}
    sid = next(iter(params)).split(":")[1]
    assert all(t.extra_delay_ps == 0.0 for t in _transfers(parts[sid], sid, params).values())
    thermal = build_component("MZM", mechanism="thermo_optic")
    assert all(t.extra_delay_ps == 0.0 for t in _transfers(thermal, "mzm", {"drive:mzm": 1.0}).values())


RINGS = {                            # label: (part, sid, phase key, heater key)
    "all-pass ring": (lambda: MicroringResonator(with_heater=True), "ring", "phase:ring", "heater:ring"),
    "add-drop ring": (lambda: MicroringResonator(add_drop=True, with_heater=True), "ring", "phase:ring", "heater:ring"),
    "coupled ring filter": (lambda: CoupledRingFilter(order=3), "crf", "phase:crf:ring2", "heater:crf:ring2"),
    "coupled ring filter, common phase": (lambda: CoupledRingFilter(order=3), "crf", "phase:crf", "heater:crf:ring2"),
    "ring-assisted MZI ring": (_ramzi, "ramzi", "phase:ramzi:ring2", "heater:ramzi:ring2"),
    "weight bank ring": (_bank, "bank", "phase:bank:ring2", "heater:bank:ring2"),
}


@pytest.mark.parametrize("make,sid,phase_key,heater_key", [pytest.param(*case, id=label) for label, case in RINGS.items()])
def test_a_ring_heater_adds_to_the_rings_phase_key(make, sid, phase_key, heater_key):
    part = make()
    both = _transfers(part, sid, {phase_key: 0.7, heater_key: 10.0})
    own = heater_key.replace("heater:", "phase:", 1)                    # the heated ring's own phase key
    summed = _transfers(part, sid, {phase_key: 0.7, own: 0.7 + heater_phase(heater_key.split(":", 1)[1], {heater_key: 10.0})})
    assert both.keys() == summed.keys()
    for key, t in both.items():
        assert t.matrix == pytest.approx(summed[key].matrix, abs=1e-12), key
        assert summed[key].extra_delay_ps == 0.0                       # a phase key adds no delay; the heater does
    assert any(t.extra_delay_ps > 0 for t in both.values())
