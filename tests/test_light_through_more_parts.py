"""More parts act on the light: each behaviour against the physics it models, and a strict animation that runs
through the part instead of stopping at it.

Mutants (each one fails a test here):
- ``AcoustoOptic.amplitude`` returns 1: the first order carries all of the power.
- ``BraggReflector.coefficients`` without the ``1j`` in ``below``: r and t no longer keep the power off the peak.
- ``LoopMirror`` with ``bar * bar - cross * cross``: a 3 dB loop mirror lets the light through.
- ``CyclicRouter`` sends ``oK`` back with ``(k + j)``: the light does not return to the input it came from.
- ``SlitBandpass`` with a square passband: half a bandpass off the centre passes all, not half.
- ``PeriscopeRelay`` without the rotation: horizontal light stays horizontal through a 90 degree periscope.
- ``TotalInternalFold.fresnel`` with ``cos_out`` real (``abs``): glass of index 1.515 stops reflecting all.
"""

from __future__ import annotations

import math
import warnings

import pytest

from optodraw import Beam, Laser, OnChipLaser, OnChipPhotodetector, Photodiode, Scene
from optodraw.animation_engine import Animation
from optodraw.animation_engine.behaviours import behaviour_for
from optodraw.animation_engine.behaviours.passive import BraggReflector
from optodraw.animation_engine.behaviours.sources import Sink
from optodraw.animation_engine.signals import jones, power
from optodraw.registry import build_component


def _powers(part, in_port, wl, params=None, field=(1, 0), sid="x1"):
    totals = {}
    for t in behaviour_for(part, sid).transfers(part, sid, in_port, wl, params or {}):
        totals[t.out_port] = totals.get(t.out_port, 0) + t.matrix @ jones(*field)
    return {port: power(v) for port, v in totals.items()}


@pytest.mark.parametrize("name, in_port, out_port", [
    ("FourFSystem", "object", "image"), ("SpectrometerSlit", "in", "out"), ("VacuumChamber", "in", "out"),
    ("Prism", "in", "out"), ("Pentaprism", "in", "out"),
])
def test_a_clear_optic_passes_all_the_light_both_ways(name, in_port, out_port):
    part = build_component(name)
    assert _powers(part, in_port, 633.0) == pytest.approx({out_port: 1.0})
    assert _powers(part, out_port, 633.0) == pytest.approx({in_port: 1.0})


def test_a_chopper_passes_half_the_power_on_average_and_an_aom_its_diffraction_efficiency():
    assert _powers(build_component("OpticalChopper"), "in", 633.0) == pytest.approx({"out": 0.5})
    assert _powers(build_component("AOM", diffraction_efficiency=0.6), "in", 633.0) == pytest.approx({"out": 0.6})


def test_an_eom_driven_at_its_half_wave_voltage_turns_the_phase_by_pi_and_keeps_the_power():
    eom = build_component("EOM", half_wave_voltage_v=4.8)
    (t,) = behaviour_for(eom, "e1").transfers(eom, "e1", "in", 1064.0, {"drive:e1": 4.8})
    assert t.matrix[0, 0] == pytest.approx(-1.0) and power(t.matrix @ jones(1, 1)) == pytest.approx(2.0)


def test_an_slm_keeps_its_fill_factor_and_adds_its_phase():
    slm = build_component("SLM")
    (t,) = behaviour_for(slm, "s1").transfers(slm, "s1", "in", 633.0, {"phase:s1": math.pi / 2})
    assert power(t.matrix @ jones(1)) == pytest.approx(slm.fill_factor)
    assert t.matrix[0, 0] / abs(t.matrix[0, 0]) == pytest.approx(1j)


@pytest.mark.parametrize("turn, vertical_share", [(0.0, 0.0), (90.0, 1.0), (45.0, 0.5)])
def test_a_periscope_turns_the_polarisation_by_its_turn(turn, vertical_share):
    """Two 45 degree folds make a rotation: a 90 degree periscope makes horizontal light vertical."""

    periscope = build_component("Periscope", output_angle_deg=turn)
    (t,) = behaviour_for(periscope, "p1").transfers(periscope, "p1", "in", 633.0, {})
    out = t.matrix @ jones(1, 0)
    assert power(out) == pytest.approx(0.99 ** 2)
    assert abs(out[1]) ** 2 / power(out) == pytest.approx(vertical_share, abs=1e-12)


def test_a_right_angle_prism_reflects_all_by_total_internal_reflection_and_less_below_the_critical_index():
    """At 45 degrees inside, glass of index 1.515 is past the critical angle (41.3 degrees). Glass of index 1.3 is
    not: its hypotenuse reflects the Fresnel share, 0.160 for s (vertical) and 0.0256 for p (horizontal),
    worked by hand from cos(theta_t) = 0.394."""

    glass = build_component("RightAnglePrism", refractive_index=1.515)
    assert _powers(glass, "in", 633.0, field=(1, 0)) == pytest.approx({"out": 1.0})
    assert _powers(glass, "in", 633.0, field=(0, 1)) == pytest.approx({"out": 1.0})
    low = build_component("RightAnglePrism", refractive_index=1.3)
    assert _powers(low, "in", 633.0, field=(1, 0))["out"] == pytest.approx(0.0256, abs=2e-4)
    assert _powers(low, "in", 633.0, field=(0, 1))["out"] == pytest.approx(0.160, abs=2e-3)


def test_a_monochromator_passes_a_triangle_one_bandpass_wide():
    """1200 lines per mm, f = 300 mm: 2.78 nm per mm; a 100 µm slit passes 0.278 nm (FWHM)."""

    mono = build_component("Monochromator", groove_density_l_mm=1200.0, focal_length_mm=300.0, center_wavelength_nm=633.0)
    band = 0.1 * 1e6 / (1200.0 * 300.0)
    assert _powers(mono, "in", 633.0) == pytest.approx({"out": 1.0})
    assert _powers(mono, "in", 633.0 + band / 2) == pytest.approx({"out": 0.5})
    assert _powers(mono, "in", 633.0 - band) == pytest.approx({"out": 0.0})
    assert _powers(mono, "in", 633.0 + band / 2, {"slit:x1": 200.0}) == pytest.approx({"out": 0.75})


def test_a_partial_mirror_at_normal_incidence_reflects_back_and_transmits_its_percentage():
    mirror = build_component("PartialMirror", transmission=10.0)
    assert _powers(mirror, "front", 1064.0) == pytest.approx({"back": 0.1, "front": 0.9})
    assert _powers(mirror, "back", 1064.0) == pytest.approx({"front": 0.1, "back": 0.9})
    assert {"front", "back"} <= behaviour_for(mirror, "m1").fold_ports


def test_a_bragg_grating_reflects_its_peak_reflectivity_at_the_bragg_wavelength_and_none_at_the_first_null():
    """Coupled-mode theory of a uniform grating: R = tanh^2(kappa L) at the Bragg wavelength, and the first zero
    of R where delta L = sqrt((kappa L)^2 + pi^2)."""

    grating = build_component("BraggGrating", reflectivity=0.9, length=240.0, center_wavelength_nm=1550.0)
    assert _powers(grating, "o1", 1550.0) == pytest.approx({"o1": 0.9, "o2": 0.1})
    kappa_l = math.atanh(math.sqrt(0.9))
    delta = math.sqrt(kappa_l ** 2 + math.pi ** 2) / 240.0
    n_g = 4.2                                                   # the silicon guide's group index (geometry.N_SILICON)
    null = 1e3 / (1e3 / 1550.0 + delta / (2 * math.pi * n_g))
    assert _powers(grating, "o1", null)["o1"] == pytest.approx(0.0, abs=1e-12)
    for wl in (1540.0, 1549.0, 1550.3, 1551.7, 1560.0):
        r, t = BraggReflector.coefficients(grating, wl)
        assert abs(r) ** 2 + abs(t) ** 2 == pytest.approx(1.0)


@pytest.mark.parametrize("k, back", [(0.5, 1.0), (0.2, 4 * 0.2 * 0.8), (0.0, 0.0)])
def test_a_sagnac_loop_returns_4k_1_minus_k_and_passes_the_rest(k, back):
    loop = build_component("SagnacLoop")
    loop.coupling_ratio = k
    got = _powers(loop, "o1", 1550.0)
    assert got["o1"] == pytest.approx(back) and got["o2"] == pytest.approx((1 - 2 * k) ** 2)


def test_an_mmi_1x3_and_an_adiabatic_coupler_split_evenly_and_keep_the_power():
    assert _powers(build_component("MMI1x3"), "o1", 1550.0) == pytest.approx({"o2": 1 / 3, "o3": 1 / 3, "o4": 1 / 3})
    assert _powers(build_component("AdiabaticCoupler"), "o1", 1550.0) == pytest.approx({"o3": 0.5, "o4": 0.5})


def test_an_echelle_grating_sends_each_channel_colour_to_its_own_port():
    echelle = build_component("EchelleGrating", channel_count=8, channel_spacing_nm=0.8, center_wavelength_nm=1550.0)
    for k in range(1, 9):
        wl = 1550.0 + (k - 4.5) * 0.8
        assert _powers(echelle, "in", wl) == pytest.approx({f"o{k}": 1.0})
        assert _powers(echelle, f"o{k}", wl) == pytest.approx({"in": 1.0})


def test_an_awgr_routes_every_input_to_every_output_once_and_back():
    """A cyclic router: on each colour the inputs go to different outputs, each input meets every output on one
    colour only, and the light from an output goes back to the input it came from."""

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        router = build_component("AWGR")
    n = router.channel_count
    colours = [router.center_wavelength_nm + (j - (n + 1) / 2) * router.channel_spacing_nm for j in range(1, n + 1)]
    seen = set()
    for wl in colours:
        outs = []
        for k in range(1, n + 1):
            (out, share), = _powers(router, f"i{k}", wl).items()
            assert share == pytest.approx(1.0)
            assert _powers(router, out, wl) == pytest.approx({f"i{k}": 1.0})
            outs.append(out)
            seen.add((k, out))
        assert len(set(outs)) == n
    assert len(seen) == n * n


def test_a_grating_coupler_array_joins_each_fibre_to_its_own_guide():
    array = build_component("GratingCouplerArray", count=4)
    for k in range(1, 5):
        assert _powers(array, f"f{k}", 1550.0) == pytest.approx({f"o{k}": 0.5})
        assert _powers(array, f"o{k}", 1550.0) == pytest.approx({f"f{k}": 0.5})


def test_an_electro_absorption_modulator_loses_in_db_in_proportion_to_its_drive():
    eam = build_component("ElectroAbsorptionModulator")
    assert _powers(eam, "o1", 1550.0) == pytest.approx({"o2": 1.0})
    assert _powers(eam, "o1", 1550.0, {"drive:x1": 1.0}) == pytest.approx({"o2": 10 ** -0.5})      # 5 dB at 1 V
    assert _powers(eam, "o1", 1550.0, {"drive:x1": 4.0}) == pytest.approx({"o2": 0.1})             # 10 dB at most


def test_an_iq_modulator_keeps_half_at_rest_and_nulls_with_both_arms_at_v_pi():
    iq = build_component("IQModulator")
    assert _powers(iq, "o1", 1550.0) == pytest.approx({"o2": 0.5})
    assert _powers(iq, "o1", 1550.0, {"drive:x1:i": 2.0, "drive:x1:q": 2.0}) == pytest.approx({"o2": 0.0}, abs=1e-20)
    (t,) = behaviour_for(iq, "x1").transfers(iq, "x1", "o1", 1550.0, {"drive:x1:i": 2.0})
    assert t.matrix[0, 0] == pytest.approx(0.5j)                # the I arm at null: the Q arm's field, 90 degrees on


def test_a_racetrack_modulator_carries_light_as_a_ring_and_keeps_the_power_at_its_coupler():
    ring = build_component("RacetrackModulator")
    got = _powers(ring, "o1", 1550.0, sid="r1")
    assert set(got) == {"o2", "_ring_top"} and got["o2"] == pytest.approx(0.9)


@pytest.mark.parametrize("name", ["PhotonCounter", "BalancedPhotodetector", "ReceiverMacro", "FiberArray",
                                  "OpticalIOBank"])
def test_a_part_where_the_light_ends_absorbs_at_every_optical_port(name):
    part = build_component(name)
    optical = [p for p, port in part.ports().items() if port.kind != "electrical"]
    assert optical and isinstance(behaviour_for(part, "s1"), Sink)
    assert all(behaviour_for(part, "s1").sinks(part, p) for p in optical)


def test_a_cryostat_passes_its_windows_and_its_own_sample_takes_the_light():
    bare = build_component("Cryostat", with_sample=False)
    assert _powers(bare, "in", 633.0) == pytest.approx({"out": 1.0})
    assert behaviour_for(bare, "c1").sinks(bare, "sample") and not behaviour_for(bare, "c1").sinks(bare, "in")
    full = build_component("Cryostat", with_sample=True)
    assert behaviour_for(full, "c1").sinks(full, "in")


def _strict(part, in_port, wl, chip):
    """A strict cw animation: a laser on ``in_port``, a detector on every other optical port. Returns the power
    absorbed behind each port of the part, by port name (the laser absorbs what comes back to ``in_port``)."""

    from optodraw.animation_engine.ids import scene_ids

    scene = Scene(platform="on_chip" if chip else "free_space")
    scene.add(part)
    behind = {}
    for name, port in part.world_ports().items():
        if port.kind == "electrical" or name == "mount":
            continue
        a = math.radians(port.orientation_deg)
        at = (port.center.x + 60 * math.cos(a), port.center.y + 60 * math.sin(a))
        source = name == in_port
        if chip:
            far = (OnChipLaser(center=at, angle=port.orientation_deg + 180, wavelength_nm=wl) if source
                   else OnChipPhotodetector(center=at, angle=port.orientation_deg))
            scene.add(far)
            scene.route((part, name), (far, "o1"), kind="waveguide", path_type="smooth")
        else:
            far = scene.add(Laser(center=at, angle=port.orientation_deg + 180, wavelength=wl) if source
                            else Photodiode(center=at, angle=port.orientation_deg))
            scene.add(Beam((part, name), (far, "out" if source else "in")))
        behind[id(far)] = name
    sids = {sid: behind[key] for key, sid in scene_ids(scene).items() if key in behind}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        data = Animation(scene, mode="cw", strict=True).auto().click().to_json()
    got = {}
    for record in data["signal_state"]["absorbed"]:
        got[sids[record["part"]]] = got.get(sids[record["part"]], 0.0) + record["power"]
    return got


@pytest.mark.parametrize("name, in_port, wl, chip, total", [
    ("AOM", "in", 633.0, False, 0.75), ("FourFSystem", "object", 633.0, False, 1.0),
    ("Monochromator", "in", 633.0, False, 1.0), ("Periscope", "in", 633.0, False, 0.99 ** 2),
    ("PartialMirror", "front", 1064.0, False, 1.0), ("BraggGrating", "o1", 1550.0, True, 1.0),
    ("SagnacLoop", "o1", 1550.0, True, 1.0), ("MMI1x3", "o1", 1550.0, True, 1.0),
    ("EchelleGrating", "in", 1550.4, True, 1.0), ("AdiabaticCoupler", "o1", 1550.0, True, 1.0),
])
def test_a_strict_animation_runs_through_the_part(name, in_port, wl, chip, total):
    """Before these behaviours a strict animation stopped at each of these parts ("no behaviour yet")."""

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        part = build_component(name)
    got = _strict(part, in_port, wl, chip)
    assert sum(got.values()) == pytest.approx(total)


def test_light_a_reflector_sends_back_ends_in_its_laser():
    mirror = _strict(build_component("PartialMirror", transmission=10.0), "front", 1064.0, False)
    assert mirror == pytest.approx({"front": 0.9, "back": 0.1})
    grating = _strict(build_component("BraggGrating", reflectivity=0.9), "o1", 1550.0, True)
    assert grating == pytest.approx({"o1": 0.9, "o2": 0.1})
    assert _strict(build_component("EchelleGrating"), "in", 1550.4, True) == pytest.approx({"o5": 1.0})


def test_a_transmitter_macro_emits_from_its_optical_output():
    tx = build_component("TransmitterMacro", wavelength_nm=1310.0)
    (emission,) = behaviour_for(tx, "t1").emissions(tx, "t1", {})
    assert (emission.port, emission.wavelength_nm) == ("opt_out", 1310.0) and power(emission.jones) == pytest.approx(1.0)
