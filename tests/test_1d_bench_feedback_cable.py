"""A bench with a feedback cable: a lock sends the detector's signal through the electronics back to the laser.
The 1D view lays the light out first and hangs the instruments on it: the cable that closes the loop turns square
and moves no part of the bench."""

from __future__ import annotations

from optodraw import (EOM, Beam, Laser, OpAmp, OpticalIsolator, PBS, Photodiode, RFMixer, Scene,
                      WaveformGenerator)
from optodraw.layout import face
from optodraw.symbols.schematic import BENCH_GAP, build_schematic


def _lock(feedback: bool) -> Scene:
    """The Pound-Drever-Hall bench of Black, Am. J. Phys. 69, 79 (2001), Fig. 3, without its cavity."""

    scene = Scene(width=89, height=70, platform="free_space")
    laser = scene.add(Laser(center=(-38, 20), wavelength=1064, label="Laser"))
    iso = scene.add(OpticalIsolator(center=(-22, 20), label="Isolator"))
    eom = scene.add(EOM(center=(-6, 20), label="Pockels cell"))
    pbs = scene.add(PBS(center=(8, 20), label="PBS"))
    pd = scene.add(Photodiode(center=(8, 4), label="PD"))
    lo = scene.add(WaveformGenerator(center=(-6, 2), label="LO"))
    mixer = scene.add(RFMixer(center=(-6, -22), angle=180, label="Mixer"))
    servo = scene.add(OpAmp(center=(-38, -10), angle=90, label="Servo"))
    face(pd, pbs)
    scene.add(Beam.through(laser, iso, eom, (pbs, "in"), (pbs, "tap"), pd, wavelength=1064))
    cables = [((lo, "out2"), (mixer, "lo")), ((pd, "e2"), (mixer, "rf")), ((mixer, "if"), (servo, "in_n"))]
    if feedback:
        cables.append(((servo, "out"), (laser, "e1")))
    for a, b in cables:
        scene.route(a, b, kind="electrical", width=0.3)
    return scene


def test_a_feedback_cable_leaves_the_beam_straight_and_the_bench_compact():
    # mutant: _LIGHT_KINDS = {"free_space", "fiber", "electrical"} in schematic.py: the oscillator becomes the root,
    # the loop pushes the bench 750 pt down and the beam bends at the isolator
    schematic = build_schematic(_lock(feedback=True))
    by_label = {item.label: item for item in schematic.items}
    heights = {by_label[name].port(port)[1] for name, port in (("Laser", "out"), ("Isolator", "in"),
                                                              ("Isolator", "out"), ("Pockels cell", "in"),
                                                              ("Pockels cell", "out"), ("PBS", "in"))}
    assert max(heights) - min(heights) < 0.5, heights
    assert schematic.height < 300, schematic.height


def test_closing_the_loop_moves_no_part_of_the_bench():
    """The light parts sit where they sit without the feedback cable, and the servo stays one gap from its laser."""

    # mutant: drop "or edges[index][4] not in _LIGHT_KINDS" from the loop closing in _bench_positions: the closing
    # cable is made straight and the servo moves 60 pt away from its laser
    def places(scene: Scene) -> dict[str, tuple[float, float]]:
        items = build_schematic(scene).items
        laser = next(item for item in items if item.label == "Laser")
        return {item.label: (round(item.x - laser.x, 1), round(item.y - laser.y, 1)) for item in items
                if item.label in ("Laser", "Isolator", "Pockels cell", "PBS", "PD")}

    assert places(_lock(feedback=True)) == places(_lock(feedback=False))
    by_label = {item.label: item for item in build_schematic(_lock(feedback=True)).items}
    (_, servo_y, _), (_, laser_y, _) = by_label["Servo"].port("out"), by_label["Laser"].port("e1")
    assert servo_y - laser_y < 3 * BENCH_GAP, (servo_y, laser_y)
