"""Behaviours: each part type does to the light what the physics says."""

import math

import numpy as np
import pytest

import optodraw
from optodraw.animation_engine.behaviours import behaviour_for
from optodraw.animation_engine.behaviours.passive import TwoPort
from optodraw.animation_engine.behaviours.sources import SINK_TYPES
from optodraw.animation_engine.signals import jones, power
from optodraw.registry import build_component


def _out(part, in_port, wl=1550.0, params=None, sid="x1"):
    return behaviour_for(part, sid).transfers(part, sid, in_port, wl, params or {})


def test_a_laser_emits_at_its_wavelength_from_its_output():
    (e,) = behaviour_for(optodraw.Laser(wavelength=532.0), "laser1").emissions(optodraw.Laser(wavelength=532.0), "laser1", {})
    assert (e.port, e.wavelength_nm) == ("out", 532.0) and power(e.jones) == pytest.approx(1.0)
    (c,) = behaviour_for(optodraw.OnChipLaser(), "onchiplaser1").emissions(optodraw.OnChipLaser(), "onchiplaser1", {})
    assert (c.port, c.wavelength_nm) == ("_active", 1550.0)      # the light starts in the drawn active region


@pytest.mark.parametrize("name", SINK_TYPES)
def test_a_detector_absorbs_at_its_optical_ports(name):
    part = build_component(name)
    optical = [p for p, port in part.ports().items() if port.kind != "electrical"]
    assert optical and all(behaviour_for(part, "s1").sinks(part, p) for p in optical)


def test_two_port_types_have_two_optical_ports():
    from optodraw.animation_engine.behaviours import _REGISTRY
    for name, behaviour in _REGISTRY.items():
        if isinstance(behaviour, TwoPort) and not name.startswith("TestPart"):
            part = build_component(name)
            a, b = behaviour.pair(part)
            assert a in part.ports() and b in part.ports() and a != b, name


def test_a_lens_passes_light_both_ways_through_its_centre():
    lens = optodraw.Lens(center=(10, 5))
    (t,) = _out(lens, "in")
    assert t.out_port == "out" and np.allclose(t.matrix, np.eye(2)) and t.points[1] == pytest.approx((10, 5))
    assert _out(lens, "out")[0].out_port == "in"


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


def test_a_grating_coupler_joins_its_fibre_port_and_its_waveguide():
    gc = optodraw.VerticalGratingCoupler()
    (t,) = _out(gc, "f1")
    assert t.out_port == "o1" and power(t.matrix @ jones(1)) == pytest.approx(0.5)


def test_a_fold_mirror_reflects_at_its_one_port():
    mirror = optodraw.Mirror()
    behaviour = behaviour_for(mirror, "m1")
    (t,) = _out(mirror, "io")
    assert t.out_port == "io" and "io" in behaviour.fold_ports
    assert power(t.matrix @ jones(1, 1)) == pytest.approx(2 * 0.99)


@pytest.mark.parametrize("angle", [0.0, 30.0, 60.0, 90.0])
def test_malus_law_through_a_polarizer(angle):
    pol = optodraw.Polarizer()
    (t,) = _out(pol, "in", 633.0, {"angle:p1": angle}, sid="p1")
    assert power(t.matrix @ jones(1, 0)) == pytest.approx(math.cos(math.radians(angle)) ** 2, abs=2e-3)


def test_a_half_wave_plate_at_45_degrees_turns_horizontal_into_vertical():
    hwp = optodraw.HalfWavePlate()
    (t,) = _out(hwp, "in", 633.0, {"angle:h1": 45.0}, sid="h1")
    out = t.matrix @ jones(1, 0)
    assert abs(out[1]) ** 2 == pytest.approx(1.0, abs=1e-9) and abs(out[0]) ** 2 == pytest.approx(0.0, abs=1e-9)


def test_a_pbs_sends_horizontal_through_and_vertical_down():
    pbs = optodraw.PBS()
    by_port = {t.out_port: t for t in _out(pbs, "in", 633.0)}
    assert power(by_port["trans"].matrix @ jones(1, 0)) == pytest.approx(1.0)
    assert power(by_port["refl"].matrix @ jones(1, 0)) == pytest.approx(0.0)
    assert power(by_port["refl"].matrix @ jones(0, 1)) == pytest.approx(1.0)


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


def test_a_beam_splitter_halves_the_power_and_keeps_the_sum():
    got = _unit_power_out(optodraw.BeamSplitter(), "in", 633.0)
    assert got == pytest.approx({"trans": 0.5, "refl": 0.5})


@pytest.mark.parametrize("make, expected", [
    (lambda: optodraw.NonPolarizingBeamSplitter(), {"trans": 0.5, "refl": 0.5}),
    (lambda: optodraw.NonPolarizingBeamSplitter(split_ratio=(0.7, 0.3)), {"trans": 0.7, "refl": 0.3}),
    (lambda: optodraw.BeamSplitter(transmission=90.0), {"trans": 0.9, "refl": 0.1}),
], ids=["npbs", "npbs-70-30", "bs-90-10"])
def test_a_beam_splitter_takes_its_ratio_from_the_part(make, expected):
    assert _unit_power_out(make(), "in", 633.0) == pytest.approx(expected)


def test_a_dichroic_reflects_below_its_edge_and_transmits_above():
    d = optodraw.BeamSplitter(dichroic=True, cutoff_wavelength=550.0)
    assert _unit_power_out(d, "in", 532.0) == pytest.approx({"trans": 0.0, "refl": 1.0})
    assert _unit_power_out(d, "refl", 650.0) == pytest.approx({"tap": 1.0, "in": 0.0})


@pytest.mark.parametrize("name, in_port, expected", [
    ("YBranch", "o1", {"o2": 0.5, "o3": 0.5}),
    ("MMI1x2", "o1", {"o2": 0.5, "o3": 0.5}),
    ("DirectionalCoupler", "o1", None),
    ("MMI2x2", "o1", None),
    ("FiberCoupler", "in1", {"out1": 0.5, "out2": 0.5}),
])
def test_splitters_divide_the_power_without_creating_any(name, in_port, expected):
    got = _unit_power_out(build_component(name), in_port)
    assert sum(got.values()) == pytest.approx(1.0)
    if expected:
        assert got == pytest.approx(expected)


def test_a_tap_coupler_taps_its_ratio():
    got = _unit_power_out(optodraw.TapCoupler(tap_ratio=0.01), "o1")
    assert sorted(got.values()) == pytest.approx([0.01, 0.99])


def test_a_2x2_coupler_matrix_is_unitary():
    dc = optodraw.DirectionalCoupler()
    rows = {}
    for p in ("o1", "o2"):
        for t in _out(dc, p):
            rows[(t.out_port, p)] = t.matrix[0, 0]
    outs = sorted({k[0] for k in rows})
    m = np.array([[rows[(o, p)] for p in ("o1", "o2")] for o in outs])
    assert np.allclose(m.conj().T @ m, np.eye(2))


def _distance_to_segment(p, a, b):
    ab = (b[0] - a[0], b[1] - a[1])
    span = ab[0] ** 2 + ab[1] ** 2
    s = 0.0 if span == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * ab[0] + (p[1] - a[1]) * ab[1]) / span))
    return math.dist(p, (a[0] + s * ab[0], a[1] + s * ab[1]))


@pytest.mark.parametrize("make", [
    optodraw.DirectionalCoupler, optodraw.TapCoupler, optodraw.MZI, lambda: optodraw.MZI(angle=90),
    optodraw.MZM, lambda: optodraw.MZM(splitter="coupler"), lambda: optodraw.MZM(splitter="branch_coupler"),
], ids=["dc", "tap", "mzi", "mzi-turned", "mzm", "mzm-coupler", "mzm-branch-coupler"])
def test_every_path_inside_a_coupler_runs_on_its_drawn_guides_from_port_to_port(make):
    """The light stays on the drawn guides; it leaves them only to hop a coupling gap (2 µm centre to centre)."""

    from optodraw.animation_engine.behaviours.geometry import optical_path_points, port_xy

    part = make()
    optical = [n for n, p in part.ports().items() if p.kind != "electrical"]
    guides = [(a, b) for n in optical for paths in optical_path_points(part, n).values()
              for pts in paths for a, b in zip(pts, pts[1:])]
    transfers = [t for n in optical for t in _out(part, n, sid="c1")]
    assert transfers
    for t in transfers:
        assert t.points[0] == pytest.approx(port_xy(part, t.in_port)) and t.points[-1] == pytest.approx(port_xy(part, t.out_port))
        hops = []
        for a, b in zip(t.points, t.points[1:]):
            middle = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
            if min(_distance_to_segment(middle, *g) for g in guides) >= 0.5:
                hops.append(math.dist(a, b))
        assert len(hops) <= 1 and all(h < 2.5 for h in hops), (t.in_port, t.out_port, t.name, hops)


def test_the_circulator_goes_round_and_the_crossing_goes_straight():
    circ = optodraw.FiberCirculator()
    assert [t.out_port for t in _out(circ, "p1")] == ["p2"] and [t.out_port for t in _out(circ, "p2")] == ["p3"]
    crossing = optodraw.WaveguideCrossing()
    (t,) = _out(crossing, "o1")
    opposite = crossing.ports()[t.out_port].orientation_deg - crossing.ports()["o1"].orientation_deg
    assert abs(abs(opposite) - 180.0) < 1e-6


def test_a_phase_shifter_adds_its_phase():
    ps = optodraw.PhaseShifter()
    (t,) = _out(ps, "o1", params={"phase:ps1": math.pi / 2}, sid="ps1")
    assert t.matrix[0, 0] == pytest.approx(1j)


@pytest.mark.parametrize("delta", [0.0, math.pi / 3, math.pi / 2, math.pi])
def test_an_mzi_splits_by_the_cosine_squared_of_half_its_phase_difference(delta):
    mzi = optodraw.MZI()
    totals = {}
    for t in _out(mzi, "o1", params={"phase:mzi1:arm1": delta}, sid="mzi1"):
        totals[t.out_port] = totals.get(t.out_port, 0) + t.matrix @ jones(1, 0)
    assert power(totals["o4"]) == pytest.approx(math.cos(delta / 2) ** 2)
    assert power(totals["o3"]) == pytest.approx(math.sin(delta / 2) ** 2)


def test_the_mzi_arms_are_balanced_and_follow_the_drawing():
    transfers = _out(optodraw.MZI(), "o1", sid="mzi1")
    lengths = {t.length for t in transfers}
    assert len(lengths) == 1                                       # the same physical length on every arm
    assert {t.name for t in transfers} == {"arm1", "arm2"} and all(len(t.points) > 2 for t in transfers)


def _mzm_power(mzm, volts):
    totals = {}
    for t in _out(mzm, "o1", params={"drive:mzm1": volts}, sid="mzm1"):
        totals[t.out_port] = totals.get(t.out_port, 0) + t.matrix @ jones(1, 0)
    return {k: power(v) for k, v in totals.items()}


def test_an_mzm_drive_of_v_pi_swaps_the_outputs():
    mzm = optodraw.MZM(splitter="coupler")                            # a 2 x 2 coupler at each end
    assert _mzm_power(mzm, 0.0)["o4"] == pytest.approx(1.0)
    assert _mzm_power(mzm, 2.0)["o3"] == pytest.approx(1.0)           # v_pi defaults to 2 V


@pytest.mark.parametrize("volts, expected", [(0.0, 1.0), (1.0, 0.5), (2.0, 0.0)])
def test_a_y_branch_mzm_has_one_output_that_follows_cosine_squared(volts, expected):
    mzm = optodraw.MZM()                                              # Y junctions; o2 and o4 are arm taps
    got = _mzm_power(mzm, volts)
    assert set(got) == {"o3"} and got["o3"] == pytest.approx(expected, abs=1e-12)
    assert _out(mzm, "o2", sid="mzm1") == [] and _out(mzm, "o4", sid="mzm1") == []


def test_a_ring_has_a_bus_a_coupler_and_a_loop():
    ring = optodraw.MicroringResonator()
    names = {(t.in_port, t.out_port) for t in _out(ring, "o1", sid="r1")}
    assert names == {("o1", "o2"), ("o1", "_ring")}
    loop = {(t.in_port, t.out_port): t for t in _out(ring, "_ring", sid="r1")}
    assert set(loop) == {("_ring", "_ring"), ("_ring", "o2")}
    circumference = 2 * math.pi * ring.ring_radius
    assert loop[("_ring", "_ring")].length == pytest.approx(circumference, rel=0.05)


def test_a_ring_conserves_power_at_its_coupler():
    ring = optodraw.MicroringResonator()
    by = {t.out_port: t for t in _out(ring, "o1", sid="r1")}
    assert power(by["o2"].matrix @ jones(1)) + power(by["_ring"].matrix @ jones(1)) == pytest.approx(1.0)
