"""The signal chain: the drawn electronics compute their signals from the light, and drive the light."""

from __future__ import annotations

import math

import numpy as np
import pytest

import optodraw
from optodraw import Scene
from optodraw.animation_engine import AnimationError, Waveform, build_graph, signal_chain
from optodraw.animation_engine.chain import ELECTRICAL_NOTE
from optodraw.animation_engine.ids import scene_ids
from optodraw.animation_engine.solver import steady_state


def _wire(scene, *pairs):
    for a, b in pairs:
        scene.route(a, b, kind="electrical", width=0.25)


def _lit(scene, *, power_mw=None):
    """A free-space laser and a photodiode in its beam (1 A/W)."""

    laser = scene.add(optodraw.Laser(center=(-100, 0), wavelength=1550, power_mw=power_mw))
    pd = scene.add(optodraw.Photodiode(center=(-40, 0), responsivity_a_per_w=1.0))
    scene.add(optodraw.Beam.through(laser, pd, wavelength=1550))
    return pd


def _receiver():
    """Laser, photodiode, TIA and ADC in a line; a scope on the TIA output (ch1) and on the codes (ch2)."""

    scene = Scene(width=300, height=160, platform="free_space")
    pd = _lit(scene, power_mw=0.05)
    tia = scene.add(optodraw.TIABlock(center=(10, 0), gain_ohm=1e4))
    adc = scene.add(optodraw.ADCBlock(center=(70, 0), bit_count=12, full_scale_v=1.0, sample_rate_hz=100e6))
    scope = scene.add(optodraw.Oscilloscope(center=(70, -60)))
    _wire(scene, ((pd, "e2"), (tia, "in")), ((tia, "out"), (adc, "in")), ((tia, "out"), (scope, "ch1")),
          ((adc, "dout"), (scope, "ch2")))
    return scene, tia, adc, scope


def test_a_receiver_turns_light_into_codes():
    scene, tia, adc, _ = _receiver()
    chain = signal_chain(scene, t_ns=np.arange(101) * 1.0)
    assert np.allclose(chain.at(tia, "out").values, 0.5, rtol=0, atol=1e-12)    # 0.05 mW x 1 A/W x 10 kOhm
    codes = chain.at(adc, "dout")
    assert codes.unit == "code" and len(codes.values) == 11 and np.all(codes.values == 2048)
    assert ELECTRICAL_NOTE in chain.notes and "Photodiode: dark_current_a (default, model)" in chain.notes
    with pytest.raises(KeyError, match="no signal at"):
        chain.at(adc, "clk")


def _tia_circuit():
    """The circuit of docs/examples/electronics/02-tia.py, lit by a chip laser in place of its grating coupler."""

    scene = Scene(title="Transimpedance amplifier", platform="on_chip")
    amp = scene.add(optodraw.OpAmp(center=(0, 0), label="TIA"))
    r_f = scene.add(optodraw.Resistor(center=(0, 10), label="R_f", value="10 kΩ"))
    c_f = scene.add(optodraw.Capacitor(center=(0, 24), label="C_f", value="0.2 pF"))
    ground = scene.add(optodraw.Ground(center=(-9, -8)))
    pd = scene.add(optodraw.OnChipPhotodetector(center=(-62, 0), label="PD", responsivity_a_per_w=1.0))
    laser = scene.add(optodraw.OnChipLaser(center=(-320, 0)))
    bias = scene.add(optodraw.ElectricalPad(center=(-42.2, 22), width=6, height=6, port_side="bottom",
                                            label="V_{bias}"))
    out = scene.add(optodraw.ElectricalPad(center=(28, 0), width=6, height=6, label="V_{out}"))
    scene.route((laser, "o1"), (pd, "o1"))
    _wire(scene, ((pd, "e1"), (bias, "e1")), ((pd, "e2"), (amp, "in_n")), ((r_f, "e1"), (amp, "in_n")),
          ((c_f, "e1"), (r_f, "e1")), ((r_f, "e2"), (amp, "out")), ((c_f, "e2"), (r_f, "e2")),
          ((amp, "in_p"), (ground, "e1")), ((amp, "out"), (out, "e1")))
    return scene, laser, amp, out


def test_the_op_amp_circuit_has_the_pole_of_its_rf_and_cf():
    scene, laser, amp, out = _tia_circuit()
    t = np.arange(6001) * 0.01                                        # 60 ns: 30 time constants of 2 ns
    step = Waveform(t, np.where(np.arange(t.size) >= 1, 1.0, 0.0), "mW")
    chain = signal_chain(scene, t_ns=t, inputs={f"power:{scene_ids(scene)[id(laser)]}": step})
    v = chain.at(amp, "out").values
    assert chain.at(out, "e1") is chain.at(amp, "out")              # the net carries one signal
    assert v[-1] == pytest.approx(10.0, rel=1e-9)                     # 1 mW x 1 A/W x 10 kOhm
    k = 201                                                           # 2 ns after the step
    tau_ns = (t[k] - t[1]) / -math.log(1.0 - v[k] / v[-1])
    assert 1e9 / (2 * math.pi * tau_ns) == pytest.approx(79.577e6, rel=1e-4)


def _modulator(*, loop=False):
    """A chip laser, an MZM and a detector into a TIA. The DAC ramp drives the MZM through an amplifier; with
    ``loop`` the TIA drives the amplifier instead."""

    scene = Scene(width=900, height=400, platform="on_chip")
    mzm = scene.add(optodraw.MZM(center=(0, 0), label="MZM"))
    x_in, x_out = mzm.ports()["o1"].center.x, mzm.ports()["o3"].center.x
    laser = scene.add(optodraw.OnChipLaser(center=(x_in - 200, 0)))
    pd = scene.add(optodraw.OnChipPhotodetector(center=(x_out + 120, 0), responsivity_a_per_w=1.0))
    tia = scene.add(optodraw.TIABlock(center=(x_out + 200, -80), gain_ohm=1e4))
    amp = scene.add(optodraw.Amplifier(center=(x_in, -120), gain=4.0))
    dac = scene.add(optodraw.DAC(center=(x_in - 80, -120), bit_count=8, full_scale_v=1.0, sample_rate_hz=1e9))
    scene.route((laser, "o1"), (mzm, "o1"))
    scene.route((mzm, "o3"), (pd, "o1"))
    _wire(scene, ((pd, "e2"), (tia, "in")), ((amp, "out"), (mzm, "sig")),
          ((tia, "out"), (amp, "in")) if loop else ((dac, "out"), (amp, "in")))
    return scene, mzm, pd, dac, tia


def test_a_dac_ramp_through_an_mzm_follows_the_steady_state_at_each_drive():
    scene, mzm, pd, dac, tia = _modulator()
    codes = np.arange(0, 256, 16)                                     # 16 codes at 1 GS/s
    t = np.arange(32) * 0.5
    chain = signal_chain(scene, t_ns=t, inputs=[((dac, "din"), Waveform(np.arange(16) * 1.0, codes, "code"))])
    drive = 4.0 * (np.repeat(codes, 2) * (1.0 / 256))                 # each code held 1 ns, then x4
    graph, ids = build_graph(scene), scene_ids(scene)
    expected = []
    for d in drive:
        result = steady_state(graph, {f"drive:{ids[id(mzm)]}": float(d)}, floor=0.0)
        p = sum(r["power"] for r in result.absorbed if r["part"] == ids[id(pd)])
        expected.append(1e4 * (1.0 * p * 1e-3 + 0.0))
    got = chain.at(tia, "out").values
    assert np.max(np.abs(got - np.array(expected))) < 1e-12
    assert got.max() > 2 * got.min()                                  # the drive swings the light


def test_a_grid_that_is_not_uniform_or_coarser_than_the_dac_is_refused():
    scene, _, _, dac, _ = _modulator()
    codes = [((dac, "din"), Waveform(np.arange(16) * 1.0, np.arange(16), "code"))]
    with pytest.raises(ValueError, match="not uniform: steps from 1 ns to 2 ns"):
        signal_chain(scene, t_ns=[0.0, 1.0, 3.0], inputs=codes)
    with pytest.raises(ValueError, match="2 ns is coarser than the code period 1 ns"):
        signal_chain(scene, t_ns=np.arange(8) * 2.0, inputs=codes)


def test_a_current_into_a_voltage_input_names_both_parts():
    scene = Scene(width=300, height=160, platform="free_space")
    pd = _lit(scene)
    scope = scene.add(optodraw.Oscilloscope(center=(40, -60)))
    _wire(scene, ((pd, "e2"), (scope, "ch1")))
    with pytest.raises(AnimationError, match="photodiode1: a current reaches oscilloscope1:ch1.*add a TIA or a load"):
        signal_chain(scene, t_ns=np.arange(10) * 1.0)


def test_two_outputs_on_one_net_name_the_net():
    scene = Scene(width=300, height=160)
    one = scene.add(optodraw.DAC(center=(0, 0)))
    two = scene.add(optodraw.DAC(center=(0, 60)))
    amp = scene.add(optodraw.Amplifier(center=(80, 30)))
    _wire(scene, ((one, "out"), (amp, "in")), ((two, "out"), (amp, "in")))
    with pytest.raises(AnimationError, match="2 outputs.*amplifier1, dac1, dac2"):
        signal_chain(scene, t_ns=np.arange(10) * 1.0)


def test_an_op_amp_with_no_resistor_names_its_input_net():
    scene = Scene(width=300, height=160, platform="free_space")
    pd = _lit(scene)
    amp = scene.add(optodraw.OpAmp(center=(20, -40)))
    _wire(scene, ((pd, "e2"), (amp, "in_n")))
    with pytest.raises(AnimationError, match="opamp1: an op amp needs one resistor.*opamp1, photodiode1"):
        signal_chain(scene, t_ns=np.arange(10) * 1.0)


def test_a_detector_that_drives_its_own_modulator_is_a_loop():
    scene = _modulator(loop=True)[0]
    with pytest.raises(AnimationError, match="loop"):
        signal_chain(scene, t_ns=np.arange(10) * 1.0)


def test_a_part_with_no_electrical_model_stops_a_strict_chain_and_is_noted_otherwise():
    scene, tia, _, _ = _receiver()
    tee = scene.add(optodraw.BiasTee(center=(10, -60)))
    _wire(scene, ((tia, "out"), (tee, "rf")))
    with pytest.raises(AnimationError, match="biastee1: no electrical model yet for BiasTee"):
        signal_chain(scene, t_ns=np.arange(10) * 1.0)
    chain = signal_chain(scene, t_ns=np.arange(10) * 1.0, strict=False)
    assert any(n.startswith("biastee1: no electrical model yet") for n in chain.notes)


def test_show_puts_two_traces_on_a_scope():
    scene, _, _, scope = _receiver()
    signal_chain(scene, t_ns=np.arange(101) * 1.0).show(scope)
    assert set(scope.traces) == {"ch1", "ch2"} and all(len(points) > 1 for points in scope.traces.values())


def test_a_part_and_its_solver_param_name_an_input_over_time():
    # mutant: self.optical[f"{port}:{sid}"] -> self.optical[f"{sid}:{port}"] in _sources: the heater never moves
    from optodraw.animation_engine.spectrum import ended_power

    scene = Scene(width=300, height=160, platform="on_chip")
    laser = scene.add(optodraw.OnChipLaser(center=(-90, 0)))
    ring = scene.add(optodraw.MicroringResonator(center=(0, 0), add_drop=True, with_heater=True))
    pd = scene.add(optodraw.OnChipPhotodetector(center=(90, 0), responsivity_a_per_w=0.8))
    tia = scene.add(optodraw.TIABlock(center=(150, 0), gain_ohm=1e4))
    scene.route((laser, "o1"), (ring, "o1"), kind="waveguide")
    scene.route((ring, "o2"), (pd, "o1"), kind="waveguide")
    _wire(scene, ((pd, "e2"), (tia, "in")))
    t = np.arange(81) * 1.0
    heat = Waveform(t, np.linspace(0.0, 40.0, 81), "mW")     # a phase of 2 pi: one free spectral range
    got = signal_chain(scene, t_ns=t, inputs=[((ring, "heater"), heat)]).at(tia, "out").values
    sid, graph = scene_ids(scene), build_graph(scene)
    expected = [1e4 * 0.8e-3 * ended_power(steady_state(graph, {f"heater:{sid[id(ring)]}": mw}, floor=0.0))
                [f"{sid[id(pd)]}:o1"] for mw in heat.values]
    assert np.max(np.abs(got - np.array(expected))) < 1e-12
    assert np.ptp(got) > 0.5 * got.max()                     # the resonance crosses the laser line
    with pytest.raises(AnimationError, match="no port or solver param nope"):
        signal_chain(scene, t_ns=t, inputs=[((ring, "nope"), heat)])


def test_a_result_through_an_mzm_names_its_v_pi():
    # mutant: parameter_names returns () for the MZM: the notes hide the 2 V default the drive rests on
    scene, *_ = _modulator()
    codes = [((scene_dac(scene), "din"), Waveform(np.arange(4) * 1.0, np.array([0, 85, 170, 255]), "code"))]
    notes = signal_chain(scene, t_ns=np.arange(16) * 0.25, inputs=codes).notes
    assert any(note.endswith("v_pi (default, model)") for note in notes)


def scene_dac(scene):
    return next(part for part in scene.walk() if type(part).__name__ == "DAC")
