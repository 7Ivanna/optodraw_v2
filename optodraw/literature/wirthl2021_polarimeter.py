"""Self-calibrating polarimeter after Wirthl et al., OSA Continuum 4(11), 2949 (2021), Fig. 3a.

The beam enters through iris 1 and a near quarter-wave plate on rotation stage 1. Rotation stage 2 carries a
Glan-Laser polarizer and both detectors as one package: the transmitted beam goes straight through iris 2 to
PD 1, and the rejected beam leaves the polarizer's side window about 30 degrees below the beam, through iris 3
to PD 2.

A compact schematic, not to scale: the parts keep the figure's order and the side arm its angle.
"""

from __future__ import annotations

import math

from optodraw import AmplifiedPhotodetector, Beam, GlanLaserPolarizer, Iris, QuarterWavePlate, Scene

PAPER = {
    "citation": "V. Wirthl, C. D. Panda, P. W. Hess, G. Gabrielse, Simple self-calibrating polarimeter for "
                "measuring the Stokes parameters of light, OSA Continuum 4(11), 2949 (2021)",
    "doi": "10.1364/OSAC.444102",
    "figure": "Fig. 3(a)",
}

WAVELENGTH = 1090          # nm, from the text
SIDE_ANGLE = 30.0          # degrees: the rejected beam below the straight one


def build(title: str = "Self-calibrating polarimeter (after Wirthl 2021)") -> Scene:
    scene = Scene(title=title, width=120, height=50, platform="free_space")
    iris1 = scene.add(Iris(center=(-48, 0), outer_diameter=8, aperture_diameter=1, label="Iris 1", label_side="top"))
    qwp = scene.add(QuarterWavePlate(center=(-32, 0), aperture=8, label="QWP", label_side="top"))
    qwp.base_mount = "rotation_stage"                       # rotation stage 1
    glan = scene.add(GlanLaserPolarizer(center=(-12, 0), length=10, aperture=6, reject_angle_deg=SIDE_ANGLE,
                                        label="Glan-Laser", label_side="top"))
    glan.base_mount = "rotation_stage"                      # rotation stage 2 carries it and both detectors
    iris2 = scene.add(Iris(center=(10, 0), outer_diameter=8, aperture_diameter=1, label="Iris 2", label_side="top"))
    pd1 = scene.add(AmplifiedPhotodetector(center=(28, 0), box_size=5, label="PD 1", label_side="top"))
    window = glan.world_ports()["reject"].center
    c, s = math.cos(math.radians(SIDE_ANGLE)), -math.sin(math.radians(SIDE_ANGLE))
    def along(distance: float) -> tuple[float, float]:        # a point on the side arm, read to 0.01 um
        return round(window.x + distance * c, 2), round(window.y + distance * s, 2)

    iris3 = scene.add(Iris(center=along(16), outer_diameter=8, aperture_diameter=1, angle=-SIDE_ANGLE, label="Iris 3",
                           label_side="right"))
    # turned to the side arm itself, so the beam runs straight through iris 3 into PD 2
    pd2 = scene.add(AmplifiedPhotodetector(center=along(32), box_size=5, angle=-SIDE_ANGLE, label="PD 2",
                                           label_side="right"))
    scene.add(Beam((-60, 0), (iris1, "in"), (iris1, "out"), (qwp, "in"), (qwp, "out"), (glan, "in"), (glan, "out"),
                   (iris2, "in"), (iris2, "out"), (pd1, "in"), wavelength=WAVELENGTH, width=0.6, label=""))
    scene.add(Beam((glan, "reject"), (iris3, "in"), (iris3, "out"), (pd2, "in"), wavelength=WAVELENGTH, width=0.6,
                   label=""))
    scene.metadata["paper"] = dict(PAPER)
    scene.set_view_layout({"1d": {"spacing": 1}})       # the 1D copies the 2D: the side arm, the label room
    scene.fit_frame(margin=6)
    return scene
