"""The amplifier and the electrical filter of a block diagram: a Pound-Drever-Hall loop or an optoelectronic
oscillator needs both. The shared circuit contract (catalog, ports, exact 1D symbol, leads that end on their ports,
3D package, save and load) is in test_circuit_parts.py; this file holds what is their own."""

from __future__ import annotations

import pytest

from optodraw import Amplifier, Laser, RFFilter, RFMixer, Scene, check_figure
from optodraw.components.electronics.circuit import _wave
from optodraw.symbols import lookup


def test_an_amplifier_points_the_way_the_signal_runs():
    # mutant: BODY = ((0.3, -0.3), (0.3, 0.3), (-0.3, 0.0)) in Amplifier: the triangle points back at its input
    amp = Amplifier()
    apex = max(Amplifier.BODY, key=lambda point: point[0])
    assert apex == (0.3, 0.0)
    assert amp.ports()["out"].center.x > 0 > amp.ports()["in"].center.x


@pytest.mark.parametrize("response, struck", [("lowpass", (0.15,)), ("highpass", (-0.15,)),
                                              ("bandpass", (0.15, -0.15)), ("bandstop", (0.0,))])
def test_a_filter_strikes_the_bands_it_stops(response, struck):
    """Low frequency is the bottom wave: a low-pass filter strikes the top one (IEC 60617)."""

    # mutant: "lowpass": (-0.15,) in RFFilter.STRUCK: the low-pass mark stops the low band
    part = RFFilter(response=response)
    strokes = [line for line in part.LINES if len(line) == 2 and line[0][1] != line[1][1]]
    assert sorted(round((a[1] + b[1]) / 2.0, 6) for a, b in strokes) == sorted(struck)
    symbol = lookup(part)
    assert symbol.exact and symbol.params == {"response": response}


def test_the_wave_of_the_plan_is_the_wave_of_the_pic():
    """The pic draws sin(x*1000) in degrees: down first from the left end. The 2D plan must draw the same wave."""

    # mutant: y + 0.04 * math.sin(math.radians(-x * 1000.0)) in _wave: the 2D wave is the mirror of the 1D one
    xs = [x for x, _ in _wave(0.0)]
    assert (xs[0], xs[-1]) == pytest.approx((-0.18, 0.18))
    assert _wave(0.0)[6] == pytest.approx((-0.09, -0.04))


def test_an_unknown_response_is_refused():
    with pytest.raises(ValueError, match="response"):
        RFFilter(response="notch")


def test_the_response_saves_and_loads():
    # mutant: drop "response" from the RFFilter row of _BUILTIN_METADATA: a band-pass filter loads as low-pass
    scene = Scene(width=60, height=30)
    scene.add(RFFilter(center=(5, 0), response="bandpass", label="BPF"))
    again = next(item for item in Scene.from_spec(scene.to_spec()).walk() if isinstance(item, RFFilter))
    assert (again.response, again.label) == ("bandpass", "BPF")


def test_a_lock_loop_of_mixer_filter_and_servo_amplifier_draws_clean():
    """The electronics half of a Pound-Drever-Hall lock: mixer, low-pass filter, servo amplifier, laser."""

    # mutant: PORTS "out": (0.5, 0.0, 180.0) in Amplifier: the wire to the laser leaves the output backwards
    scene = Scene(width=120, height=50, platform="free_space")
    laser = scene.add(Laser(center=(-40, 12), wavelength=1064, label="Laser"))
    mixer = scene.add(RFMixer(center=(30, -12), angle=180, label="Mixer"))
    lpf = scene.add(RFFilter(center=(8, -12), angle=180, label="Low-pass"))
    servo = scene.add(Amplifier(center=(-14, -12), angle=180, label="Servo"))
    for a, b in (((mixer, "if"), (lpf, "in")), ((lpf, "out"), (servo, "in")), ((servo, "out"), (laser, "e1"))):
        scene.route(a, b, kind="electrical", width=0.3)
    scene.fit_frame(margin=6)
    assert check_figure(scene, preset="single_column") == []
