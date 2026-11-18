"""A heater raises the index: the light in the heated section lags in phase and arrives later, from one index change.

A heated transfer's delay is ``phase * wavelength / (2 pi c)``; the solver adds it to the arrival only, never to the
phase (the phase already holds the heater's shift). A ring's heater adds to its ``phase`` key."""

import math

import pytest

import optodraw
from optodraw.animation_engine.behaviours import find_behaviour
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


def test_the_check_value_is_the_briefs_with_the_engines_speed_of_light():
    assert delay_ps(math.pi) == pytest.approx(math.pi * 1.55e-6 / (2 * math.pi * 3e8) * 1e12, rel=1e-3)
    assert delay_ps(math.pi) == pytest.approx(0.00258512, abs=1e-8)


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


