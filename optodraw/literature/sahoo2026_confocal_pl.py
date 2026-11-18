"""Micro-photoluminescence setup after Sahoo et al., 2D Materials (2026), arXiv:2605.23418, Fig. 5.

A 532 nm laser diode excites the sample in a closed-cycle cryostat through attenuation, polarisation control and
two beam splitters (a power meter and a white-light lamp on their side ports, a camera branch). The light the
sample emits returns through polarisation analysis to a grating monochromator and a CCD, or through a fibre to
an SNSPD whose counts a time correlator times against the laser's sync.
"""

from __future__ import annotations

import math

from optodraw import (Beam, CMOSCamera, Cryostat, EMCCD, FiberCollimator, FiberPort, Filter, FlipMirror,
                      HalfWavePlate, Lamp, Laser, Lens, Mirror, Monochromator, NonPolarizingBeamSplitter,
                      Objective, Polarizer, PowerMeter, QuarterWavePlate, Sample, Scene, SNSPD,
                      CoincidenceCounter)
from optodraw.layout import Vec3, aim, face

PAPER = {
    "citation": "B. S. Sahoo et al., Localized excitonic emission in large-area MOCVD-grown GaSe 2D nanosheets for "
                "classical and non-classical light sources, 2D Materials (2026); arXiv:2605.23418",
    "doi": "10.1088/2053-1583/aeb034",
    "figure": "Fig. 5 (arXiv version)",
}


def build(title: str = "Micro-photoluminescence setup (after Sahoo 2026)") -> Scene:
    scene = Scene(title=title, width=240, height=210, platform="free_space")
    add = scene.add
    lam = 532

    # Excitation arm: laser top left, runs right, M1 turns it down the vertical axis x = 0.
    laser = add(Laser(center=(-90, 36), wavelength=lam, sync=True, label="Laser diode 532 nm", label_side="top"))
    coll = add(FiberCollimator(center=(-70, 36), label="Fibre collimator", label_side="bottom"))
    m1 = add(Mirror(center=(-47, 36), label="Silver mirror", label_side="right"))
    atten = add(Filter(center=(-47, 23), angle=-90, label="Attenuator", label_side="right"))
    hwp = add(HalfWavePlate(center=(-47, 13), angle=-90, label="HWP", label_side="right"))
    qwp = add(QuarterWavePlate(center=(-47, 7), angle=-90, label="QWP", label_side="right"))
    pol = add(Polarizer(center=(-47, 1), angle=-90, label="Linear polariser", label_side="right"))
    # Cube angle 0: light entering the top port ("refl") goes straight down and is reflected left ("in").
    bs1 = add(NonPolarizingBeamSplitter(center=(-47, -15), angle=0, label="BS1", label_side="bottom-right"))
    pm = add(PowerMeter(center=(-73, -15), angle=180, label="Power meter", label_side="top"))
    # Cube angle 90: top port ("trans") goes straight down; the lamp enters the left port ("refl") and goes down.
    bs2 = add(NonPolarizingBeamSplitter(center=(-47, -37), angle=90, label="BS2", label_side="bottom-right"))
    lamp = add(Lamp(center=(-77, -37), label="White light", label_side="bottom"))
    # Camera branch to the right of BS2: a removable mirror turns the beam down, a mirror sends it right.
    mcam1 = add(Mirror(center=(-23, -37), label="Removable mirror", label_side="right"))
    mcam2 = add(Mirror(center=(-23, -53), label="Silver mirror", label_side="bottom-right"))
    cam = add(CMOSCamera(center=(-1, -52.88), angle=0, label="CMOS camera", label_side="right"))

    # The objective stays outside the cryostat and focuses through its window (facing up, angle -90) onto the
    # sample, which sits in the cryostat on the X, Y, Z positioners.
    obj = add(Objective(center=(-47, -58), angle=-90, working_distance=21.5, label="Objective NA 0.81",
                        label_side="left"))
    # one label names both: a "Sample" label of its own sat on the cryostat wall
    add(Cryostat(center=(-47, -89), angle=-90, radius=14, with_sample=False,
                 label="Sample in closed-cycle cryostat", label_side="right"))
    sample = add(Sample(center=(-47, -89), angle=-90, label=""))
    sample.base_mount = "xyz_stage"      # the X, Y, Z positioners: a motion mark in 2D, the stages in 3D

    # Collection arm: BS1 sends the return to the right; polarisation control; two mirrors turn it up and then
    # right, into the detection row beside the excitation column (the space the paper leaves empty there).
    hwp2 = add(HalfWavePlate(center=(-17, -15), angle=0, label="HWP", label_side="top"))
    qwp2 = add(QuarterWavePlate(center=(-7, -15), angle=0, label="QWP", label_side="bottom"))
    pol2 = add(Polarizer(center=(3, -15), angle=0, label="Polariser", label_side="top"))
    mc1 = add(Mirror(center=(28, -15), label="Silver mirror", label_side="right"))
    mc2 = add(Mirror(center=(28, 2), label="Silver mirror", label_side="left"))
    # a flip mount: down, the light runs on to the monochromator; up, it folds to the fibre. The figure shows both
    mrem = add(FlipMirror(center=(44, 2), aperture=8.0, state="both", label="Removable mirror", label_side="bottom"))
    # the lens at x = 60 and an 8 mm removable mirror keep the lens label clear of the dashed outline, in 2D and 1D
    lens = add(Lens(center=(60, 2), angle=0, focal_length=30, label="Lens", label_side="top"))
    mono = add(Monochromator(center=(85, 2), angle=0, groove_density_l_mm=300, label="Grating monochromator",
                             label_side="bottom"))
    ccd = add(EMCCD(center=(113, -6), angle=0, label="CCD", label_side="bottom"))     # put on the exit ray below
    # Fibre branch, up from the removable mirror.
    lens2 = add(Lens(center=(44, 15), angle=90, focal_length=7, label="Lens", label_side="left"))
    fib = add(FiberPort(center=(44, 27), angle=90, label="Fibre coupler", label_side="left"))
    snspd = add(SNSPD(center=(71, 35.5), length=24, label="SNSPD", label_side="bottom"))
    corr = add(CoincidenceCounter(center=(105, 38.5), channels=2, label="Time correlator", label_side="bottom"))

    aim(m1, coll, atten)
    aim(mc1, pol2, mc2)
    aim(mc2, mc1, mrem)
    aim(mrem, mc2, lens2)
    aim(mcam1, bs2, mcam2)
    aim(mcam2, mcam1, cam)
    face(pm, bs1)
    face(cam, mcam2)
    # the monochromator's exit leaves at its own angle (-18 degrees): the CCD sits on that ray, facing back along it
    exit_ = mono.world_ports()["out"]
    ccd.transform.rotation_deg.z += float(exit_.orientation_deg) - 180.0 - float(ccd.world_ports()["in"].orientation_deg)
    heading = math.radians(float(exit_.orientation_deg))
    want = (float(exit_.center.x) + 8.0 * math.cos(heading), float(exit_.center.y) + 8.0 * math.sin(heading))
    at = ccd.world_ports()["in"].center
    ccd.transform.position = Vec3(round(float(ccd.transform.position.x + want[0] - at.x), 2),
                                  round(float(ccd.transform.position.y + want[1] - at.y), 2), 0.0)

    add(Beam.through(laser, coll, m1, atten, hwp, qwp, pol, (bs1, "refl"), (bs1, "tap"), (bs2, "trans"),
                     (bs2, "in"), obj, sample, wavelength=lam, label=""))
    add(Beam.through((bs1, "in"), pm, wavelength=lam))
    add(Beam.through(lamp, (bs2, "refl"), (bs2, "in"), obj, sample, wavelength=640, color="#8c8c8c"))   # white light: grey
    add(Beam.through((bs2, "tap"), mcam1, mcam2, cam, wavelength=lam))
    add(Beam((obj, "out"), (obj, "in"), (bs2, "in"), (bs2, "trans"), (bs1, "tap"), (bs1, "trans"), (hwp2, "in"), (hwp2, "out"), (qwp2, "in"), (qwp2, "out"), (pol2, "in"), (pol2, "out"),
                     (mc1, "io"), (mc2, "io"), (mrem, "pass"), (lens, "in"), (lens, "out"), (mono, "in"), (mono, "out"), (ccd, "in"), wavelength=640))
    add(Beam.through(mc2, mrem, lens2, (fib, "in"), wavelength=640))

    # The fibre to the SNSPD bends once, up and right, in both views.
    scene.route((fib, "out"), (snspd, "in"), kind="fiber", path_type="manhattan", width=0.4)
    # The laser's sync and the SNSPD's counts, as cables to the time correlator.
    scene.route((laser, "sync"), (corr, "in1"), kind="electrical", path_type="manhattan", width=0.5,
                steps=[{"y": 28.0}, {"x": -110.0}, {"y": 52.0}, {"x": 87.0}, {"y": 41.5}])
    scene.route((snspd, "out"), (corr, "in2"), kind="electrical", path_type="manhattan", width=0.5)

    # Without a view layout the 1D view places the parts by graph search and runs 3600 units tall.
    # With one it follows the source positions.
    scene.set_view_layout({"1d": {"spacing": 1}, "3d": {"spacing": 2}})
    scene.fit_frame(margin=8)
    scene.metadata["paper"] = dict(PAPER)
    return scene

