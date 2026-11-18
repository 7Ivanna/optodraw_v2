"""Behaviours: each part type does to the light what the physics says."""


import pytest

import optodraw
from optodraw.animation_engine.behaviours import behaviour_for
from optodraw.animation_engine.signals import jones, power


def _out(part, in_port, wl=1550.0, params=None, sid="x1"):
    return behaviour_for(part, sid).transfers(part, sid, in_port, wl, params or {})


def test_a_longpass_filter_blocks_below_its_edge():
    f = optodraw.Filter(cutoff_wavelength=550.0, pass_band="longpass")
    assert power(_out(f, "in", 650.0)[0].matrix @ jones(1)) == pytest.approx(1.0)
    assert power(_out(f, "in", 532.0)[0].matrix @ jones(1)) == pytest.approx(0.0)


def test_attenuator_amplifier_and_spool():
    voa = optodraw.VariableAttenuator(attenuation_db=3.0)
    assert power(_out(voa, "in")[0].matrix @ jones(1)) == pytest.approx(10 ** -0.3)
    amp = optodraw.FiberAmplifier(gain_db=20.0)
    assert power(_out(amp, "in")[0].matrix @ jones(1)) == pytest.approx(100.0)
    assert behaviour_for(amp, "a").passive is False
    spool = optodraw.FiberSpool(fiber_length_km=2.0)
    (t,) = _out(spool, "in")
    assert t.length == pytest.approx(2.0e9) and t.group_index == pytest.approx(1.468)


def test_a_waveguide_bend_follows_its_drawn_path():
    bend = optodraw.WaveguideBend()
    (t,) = _out(bend, "o1")
    assert t.out_port == "o2" and len(t.points) > 2 and t.group_index == pytest.approx(4.2)


def test_a_half_wave_plate_at_45_degrees_turns_horizontal_into_vertical():
    hwp = optodraw.HalfWavePlate()
    (t,) = _out(hwp, "in", 633.0, {"angle:h1": 45.0}, sid="h1")
    out = t.matrix @ jones(1, 0)
    assert abs(out[1]) ** 2 == pytest.approx(1.0, abs=1e-9) and abs(out[0]) ** 2 == pytest.approx(0.0, abs=1e-9)


def test_a_2d_grating_splits_the_two_polarisations_into_two_guides():
    gc = optodraw.TwoDGratingCoupler()
    by_port = {t.out_port: t for t in _out(gc, "f1")}
    assert set(by_port) == {"o1", "o2"}
    assert power(by_port["o1"].matrix @ jones(1, 0)) > 0 and power(by_port["o1"].matrix @ jones(0, 1)) == pytest.approx(0)
    assert power(by_port["o2"].matrix @ jones(0, 1)) > 0 and power(by_port["o2"].matrix @ jones(1, 0)) == pytest.approx(0)


def _unit_power_out(part, in_port, wl=1550.0, params=None):
    totals = {}
    for t in _out(part, in_port, wl, params):
        totals[t.out_port] = totals.get(t.out_port, 0) + t.matrix @ jones(1, 0)
    return {port: power(v) for port, v in totals.items()}


@pytest.mark.parametrize("make, expected", [
    (lambda: optodraw.NonPolarizingBeamSplitter(), {"trans": 0.5, "refl": 0.5}),
    (lambda: optodraw.NonPolarizingBeamSplitter(split_ratio=(0.7, 0.3)), {"trans": 0.7, "refl": 0.3}),
    (lambda: optodraw.BeamSplitter(transmission=90.0), {"trans": 0.9, "refl": 0.1}),
], ids=["npbs", "npbs-70-30", "bs-90-10"])
def test_a_beam_splitter_takes_its_ratio_from_the_part(make, expected):
    assert _unit_power_out(make(), "in", 633.0) == pytest.approx(expected)


def test_a_tap_coupler_taps_its_ratio():
    got = _unit_power_out(optodraw.TapCoupler(tap_ratio=0.01), "o1")
    assert sorted(got.values()) == pytest.approx([0.01, 0.99])


def test_the_circulator_goes_round_and_the_crossing_goes_straight():
    circ = optodraw.FiberCirculator()
    assert [t.out_port for t in _out(circ, "p1")] == ["p2"] and [t.out_port for t in _out(circ, "p2")] == ["p3"]
    crossing = optodraw.WaveguideCrossing()
    (t,) = _out(crossing, "o1")
    opposite = crossing.ports()[t.out_port].orientation_deg - crossing.ports()["o1"].orientation_deg
    assert abs(abs(opposite) - 180.0) < 1e-6


def _mzm_power(mzm, volts):
    totals = {}
    for t in _out(mzm, "o1", params={"drive:mzm1": volts}, sid="mzm1"):
        totals[t.out_port] = totals.get(t.out_port, 0) + t.matrix @ jones(1, 0)
    return {k: power(v) for k, v in totals.items()}


def test_an_mzm_drive_of_v_pi_swaps_the_outputs():
    mzm = optodraw.MZM(splitter="coupler")                            # a 2 x 2 coupler at each end
    assert _mzm_power(mzm, 0.0)["o4"] == pytest.approx(1.0)
    assert _mzm_power(mzm, 2.0)["o3"] == pytest.approx(1.0)           # v_pi defaults to 2 V


