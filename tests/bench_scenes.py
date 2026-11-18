"""Plain benches the 1D bench tests draw: an epi confocal path, a Michelson FTIR, a polarisation breadboard
and a laser sync cable round the outside. The first three were the first presets; the presets now draw
published figures, and these stay as fixtures."""

from __future__ import annotations

from optodraw import (Baseplate, Beam, BeamSplitter, Camera, CoincidenceCounter, Filter, HalfWavePlate, Iris,
                      Laser, Lens, Mirror, Objective, OpticalIsolator, PBS, Photodiode, QuarterWavePlate, Sample, Scene, Spectrometer)
from optodraw.components.misc import Grid
from optodraw.layout import aim, face
from optodraw.presets import _objective_focus


def confocal_pl_setup(title: str = "Confocal PL Setup") -> Scene:
    """Build a confocal photoluminescence microscope preset scene."""

    # Epi-illumination confocal PL on a collinear vertical axis through the dichroic
    # so the manual beams coincide with the real physics: the pump (from the left)
    # REFLECTS down off the dichroic (45 deg) into the objective onto the cryostat
    # sample; the PL returns up and TRANSMITS straight through the dichroic to the
    # LP filter / spectrometer / CCD above. (Dichroic ports: in=left, trans=right,
    # refl=down — see BeamSplitter.ports.)
    scene = Scene(title=title, width=240, height=240, platform="free_space")
    scene.add(Grid(width=240, height=240, pitch=20))
    laser = scene.add(Laser(center=(-70, 0), wavelength=532, label="532 nm Pump"))
    # The edge sits between the 532 pump and the 650 emission, so tracing sends
    # the pump down to the sample and lets the photoluminescence through.
    dichroic = scene.add(BeamSplitter(center=(0, 0), angle=45, dichroic=True,
                                      cutoff_wavelength=550, label="Dichroic", label_side="right"))
    # A sample in a cryostat needs a long-working-distance objective: it has to
    # focus through a window, from outside the cold shroud. The sample is then
    # placed AT that focus rather than at a hand-picked distance, so the drawing
    # and the ray trace agree about where the light lands.
    objective = scene.add(Objective(center=(0, -45), angle=-90, working_distance=29.5, label="100x LWD Obj",
                                         label_side="right"))
    focus = _objective_focus(objective)
    sample = scene.add(Sample(center=focus, angle=-90, in_cryostat=True, label="Sample", label_side="right"))
    # Longpass at the same edge as the dichroic: whatever pump leaks through the
    # dichroic stops here instead of reaching the spectrometer.
    emission_filter = scene.add(Filter(center=(0, 38), angle=90, cutoff_wavelength=550,
                                       pass_band="longpass", label="LP Filter", label_side="right"))
    # 50/50 split: spectroscopy arm (straight up) + imaging arm (to the CCD)
    detect_bs = scene.add(BeamSplitter(center=(0, 64), angle=135, label="Detect BS", label_side="left"))
    spectrometer = scene.add(Spectrometer(center=(0, 96), angle=90, label="Spectrometer"))
    camera = scene.add(Camera(center=(36, 64), angle=0, label="CCD"))
    # Pump: enters the dichroic, reflects 90deg down through the objective onto the sample.
    scene.add(Beam((laser, "out"), (dichroic, "in"), (dichroic, "refl"),
                   (objective, "in"), (objective, "out"), (sample, "in"),
                   wavelength=532, label="Pump"))
    # PL: returns up through the objective, transmits through the dichroic + LP filter,
    # then the detection BS sends it straight to the spectrometer (trans).
    scene.add(Beam((sample, "in"), (objective, "out"), (objective, "in"),
                   (dichroic, "refl"), (dichroic, "tap"),
                   (emission_filter, "in"), (emission_filter, "out"),
                   (detect_bs, "in"), (detect_bs, "trans"), (spectrometer, "in"),
                   wavelength=650, width=1.0, label="PL"))
    # Imaging arm: the detection BS reflects part of the PL to the CCD.
    scene.add(Beam((detect_bs, "in"), (detect_bs, "refl"), (camera, "in"),
                   wavelength=650, width=1.0, label="Image"))
    return scene


def ftir_setup(title: str = "FTIR Layout") -> Scene:
    """Build a simple Michelson-style FTIR layout preset scene."""

    # Michelson interferometer (verified geometry): source from the left hits the
    # 45 deg BS, which TRANSMITS to the moving mirror (right, normal incidence) and
    # REFLECTS down to the fixed mirror (below). Both retro-reflect to the BS and
    # recombine UPWARD through the sample to the detector.
    scene = Scene(title=title, width=200, height=220, platform="free_space")
    scene.add(Grid(width=200, height=220, pitch=20))
    source = scene.add(Laser(center=(-75, 0), wavelength=1550, label="IR Source"))
    beamsplitter = scene.add(BeamSplitter(center=(0, 0), angle=45, label="Interferometer BS", label_side="top-left"))
    moving = scene.add(Mirror(center=(60, 0), angle=0, label="Moving Mirror"))
    fixed = scene.add(Mirror(center=(0, -55), angle=-90, label="Fixed Mirror", label_side="right"))
    sample = scene.add(Sample(center=(0, 40), angle=90, label="Sample", label_side="right"))
    detector = scene.add(Camera(center=(0, 70), angle=90, label="Detector"))
    # Arm A transmits to the moving mirror (right) and retro-reflects; Arm B reflects to
    # the fixed mirror (below). Both recombine out the BS 'tap' port up to the detector.
    scene.add(Beam((source, "out"), (beamsplitter, "in"), (beamsplitter, "trans"),
                   (moving, "io"), (beamsplitter, "trans"), (beamsplitter, "tap"),
                   (sample, "in"), (sample, "out"), (detector, "in"),
                   wavelength=1550, label="Arm A"))
    scene.add(Beam((source, "out"), (beamsplitter, "in"), (beamsplitter, "refl"),
                   (fixed, "io"), (beamsplitter, "refl"), (beamsplitter, "tap"),
                   (sample, "in"), (sample, "out"), (detector, "in"),
                   wavelength=1550, width=0.7, label="Arm B"))
    return scene


def free_space_breadboard(title: str = "Free-space breadboard") -> Scene:
    """A polarisation-analysis bench on a modular baseplate — showcases the free-space
    optic library and the three 3D base mounts (post, translation stage, rotation stage).
    633 nm → isolator → λ/2 → PBS; transmitted arm to a lens + detector, reflected arm
    folded by a mirror through a λ/4 to a second detector."""

    scene = Scene(title=title, width=240, height=150, platform="free_space")
    scene.add(Baseplate(center=(0, 0), length=210, width=120))
    laser = scene.add(Laser(center=(-92, -20), wavelength=633, label="633 nm"))
    iso = scene.add(OpticalIsolator(center=(-64, -20), label="Isolator"))
    hwp = scene.add(HalfWavePlate(center=(-38, -20), label="λ/2"))
    hwp.base_mount = "rotation_stage"                        # a real rotation mount in 3D
    pbs = scene.add(PBS(center=(-8, -20), label="PBS", label_side="bottom"))   # the reflected arm leaves upward
    # transmitted arm: iris → lens (on a translation stage) → signal detector
    iris = scene.add(Iris(center=(22, -20), label="Iris"))
    lens = scene.add(Lens(center=(48, -20), focal_length=75, label="f=75"))
    lens.base_mount = "stage"
    pd_t = scene.add(Photodiode(center=(76, -20), label="Signal PD"))
    # reflected arm: mirror folds it up, through a λ/4 to the reference detector
    mir = scene.add(Mirror(center=(-8, 26), angle=135, label="M1"))   # face down and right: from the PBS to the arm
    qwp = scene.add(QuarterWavePlate(center=(34, 26), label="λ/4"))
    qwp.base_mount = "rotation_stage"
    aim(mir, pbs, qwp)                                     # its reflecting face on the corner of the two beams
    pd_r = scene.add(Photodiode(center=(64, 26), label="Ref PD"))
    scene.add(Beam((laser, "out"), (iso, "in"), (iso, "out"), (hwp, "in"), (hwp, "out"),
                   (pbs, "in"), (pbs, "trans"), (iris, "in"), (iris, "out"),
                   (lens, "in"), (lens, "out"), (pd_t, "in"), wavelength=633, label="Signal"))
    scene.add(Beam((pbs, "refl"), (mir, "io"), (qwp, "in"), (qwp, "out"), (pd_r, "in"),
                   wavelength=633, width=0.8, label="Reflected"))
    return scene


def sync_bench() -> Scene:
    """A laser whose sync cable runs round the outside, left of the laser and over the top, as in Sahoo 2026."""

    s = Scene(title="sync", width=120, height=80, platform="free_space")
    laser = s.add(Laser(center=(-40, 20), wavelength=532, sync=True, label="Laser", label_side="top"))
    mirror = s.add(Mirror(center=(0, 20), label="M", label_side="right"))
    pd = s.add(Photodiode(center=(0, -20), label="PD", label_side="right"))
    corr = s.add(CoincidenceCounter(center=(40, 0), channels=2, label="Correlator", label_side="bottom"))
    aim(mirror, laser, pd)
    face(pd, mirror)
    s.add(Beam.through(laser, mirror, pd))
    s.route((laser, "sync"), (corr, "in1"), kind="electrical", path_type="manhattan", width=0.5,
            steps=[{"y": 14.0}, {"x": -56.0}, {"y": 34.0}, {"x": 20.0}, {"y": 3.0}])
    s.set_view_layout({"1d": {"spacing": 1}})                   # the 1D copies the 2D, cables on their 2D paths
    return s

