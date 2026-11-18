"""Raman micro-spectroscopy setup after McNairn et al., Med. Phys. 2021, Fig. 2a.

Units are millimetres on the page. y points up. The 785 nm line runs left to
right at y = 0. DM2 turns it down into the objective. The Raman light returns
up, turns left at the top mirror and goes to the spectrometer fibre.
"""
from __future__ import annotations

from optodraw import (Beam, BeamSplitter, Camera, DichroicMirror, FiberCollimator, FiberRoute, Filter, Lamp, Laser,
                      Lens, Mirror, Objective, Sample, Scene, Spectrometer)
from optodraw.layout import aim, face
from optodraw.presets import _objective_focus

GREEN = 532.0   # colour of the LED light only; the figure draws it green
RAMAN = 850.0   # colour of the Raman return; the figure draws it red


def P(x: float, y: float) -> tuple[float, float]:
    """The drawing's place on the page (kept from the build; fit_frame frames it where it is)."""
    return (x + 17.0, y + 23.0)


PAPER = {
    "citation": "McNairn C, Mansour I, Muir B, Thomson RM, Murugkar S. High spatial resolution dosimetry "
                "with uncertainty analysis using Raman micro-spectroscopy readout of radiochromic films. "
                "Med Phys 48(8):4610-4620, 2021 (arXiv:2105.01752)",
    "doi": "10.1002/mp.15000",
    "figure": "Fig. 2(a) of the arXiv version",
}


def build(title: str = "Raman micro-spectroscopy setup (after McNairn 2021)") -> Scene:
    scene = Scene(title=title, width=190, height=170, platform="free_space")
    scene.metadata["paper"] = dict(PAPER)

    # Excitation line, one y.
    laser = scene.add(Laser(center=P(-66, 0), wavelength=785, label="785 nm laser", label_side="top"))
    l1 = scene.add(FiberCollimator(center=P(-46, 0), label="L1", label_side="top"))
    # the 785 nm clean-up filter: optodraw filters have one edge, so it carries none and passes the line
    bpf = scene.add(Filter(center=P(-32, 0), angle=0, label="BPF", label_side="top"))
    ndf = scene.add(Filter(center=P(-20, 0), angle=0, label="NDF", label_side="top"))
    dm1 = scene.add(DichroicMirror(center=P(0, 0), cutoff_wavelength=700, label="DM1", label_side="top"))
    dm2 = scene.add(DichroicMirror(center=P(26, 0), cutoff_wavelength=800, label="DM2", label_side="top-left"))

    # Objective under DM2, sample at its working distance, stage below the sample.
    obj = scene.add(Objective(center=P(26, -26), angle=-90, working_distance=12,
                              label="40x water objective", label_side="right"))
    focus = _objective_focus(obj)
    sample = scene.add(Sample(center=focus, angle=-90, label="RCF sample", label_side="left"))
    sample.base_mount = "xyz_stage"      # the automated three-axis stage: a motion mark in 2D, the stage in 3D

    # Raman return: up through DM2, EF1, a top mirror that turns it left, EF2, L2, fibre.
    ef1 = scene.add(Filter(center=P(26, 15), angle=90, cutoff_wavelength=800, pass_band="longpass",
                           label="EF1", label_side="right"))
    top = scene.add(Mirror(center=P(26, 30), label="M3", label_side="right"))
    ef2 = scene.add(Filter(center=P(12, 30), angle=0, cutoff_wavelength=800, pass_band="longpass",
                           label="EF2", label_side="bottom"))
    l2 = scene.add(FiberCollimator(center=P(-2, 30), angle=0, label="L2", label_side="bottom"))
    spec = scene.add(Spectrometer(center=P(-28, 30), angle=0, label="Spectrometer", label_side="top"))

    # Imaging arm, lower left: LED, L5, L4, beam splitter, M1 up to DM1; BS down to M2, L3, camera.
    led = scene.add(Lamp(center=P(-70, -26), label="LED", label_side="top"))
    l5 = scene.add(Lens(center=P(-56, -26), angle=0, focal_length=20, label="L5", label_side="top"))
    l4 = scene.add(Lens(center=P(-42, -26), angle=0, focal_length=20, label="L4", label_side="top"))
    bs = scene.add(BeamSplitter(center=P(-22, -26), label="BS", label_side="top-right"))
    m1 = scene.add(Mirror(center=P(0, -26), label="M1", label_side="right"))
    m2 = scene.add(Mirror(center=P(-22, -46), label="M2", label_side="right"))
    l3 = scene.add(Lens(center=P(-40, -46), angle=0, focal_length=20, label="L3", label_side="bottom"))
    cam = scene.add(Camera(center=P(-58, -46), label="Camera", label_side="bottom"))

    # Turns: DM2 sends the 785 nm line and the green light down. The BS returns the image light down.
    aim(dm2, ndf, obj)
    aim(dm1, m1, dm2)
    aim(top, ef1, ef2)
    aim(m1, bs, dm1)
    aim(bs, m1, m2)
    aim(m2, bs, cam)
    face(cam, l3)
    face(spec, l2)

    # The fibre links of the figure are dashed lines; here they are fibre routes.
    scene.add(FiberRoute([P(-66, 0), P(-46, 0)], start_component=laser, start_port="out",
                         end_component=l1, end_port="in", label=""))
    scene.add(FiberRoute([P(-2, 30), P(-28, 30)], start_component=l2, start_port="in",
                         end_component=spec, end_port="in", label=""))

    # DM1 faces M1 with "in" (down) and DM2 with "refl": the 785 nm line enters from the left ("tap") and passes
    scene.add(Beam.through(l1, bpf, ndf, (dm1, "tap"), (dm1, "refl"), (dm2, "in"), (dm2, "refl"),
                           obj, sample, wavelength=785, label="785 nm"))
    # the Raman light ends at L2: the fibre carries it on to the spectrometer
    scene.add(Beam.through(sample, obj, (dm2, "refl"), (dm2, "tap"), ef1, top, ef2, (l2, "out"),
                           wavelength=RAMAN, width=0.7, label="Raman"))
    scene.add(Beam.through(led, l5, l4, (bs, "tap"), (bs, "refl"), m1, (dm1, "in"), (dm1, "refl"),
                           (dm2, "in"), (dm2, "refl"), obj, sample, wavelength=GREEN, width=0.7, label="LED"))
    # the image light comes back along the LED path; drawn from the beam splitter, where the two paths part
    scene.add(Beam.through((bs, "in"), m2, l3, cam, wavelength=GREEN, width=0.7, label="Image"))
    scene.fit_frame(margin=10)
    return scene
