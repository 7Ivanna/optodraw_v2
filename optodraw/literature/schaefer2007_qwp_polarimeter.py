"""Rotating quarter-wave plate Stokes polarimeter after Schaefer et al., Am. J. Phys. 75, 163 (2007), Fig. 3.

Units: millimetres on the page. Fig. 3 is a block diagram. It gives no distance and no wavelength.
Choices (not facts): 633 nm HeNe wavelength, parts on one line, 22 mm pitch.
"""

from __future__ import annotations
from optodraw import Beam, Laser, Photodiode, Polarizer, QuarterWavePlate, Scene
from optodraw.layout import face

WAVELENGTH = 633  # nm, a teaching choice
PITCH = 22        # mm, a choice


PAPER = {
    "citation": "B. Schaefer, E. Collett, R. Smyth, D. Barrett, B. Fraher, Measuring the Stokes "
                "polarization parameters, Am. J. Phys. 75(2), 163-168 (2007)",
    "doi": "10.1119/1.2386162",
    "figure": "Figure 3",
}


def build(title: str = "Stokes polarimetry with a rotating quarter-wave plate (after Schaefer 2007)") -> Scene:
    scene = Scene(title=title, width=89, height=70, platform="free_space")
    scene.metadata["paper"] = dict(PAPER)
    x = [-2 * PITCH + i * PITCH for i in range(5)]       # one straight line, y = 0
    laser = scene.add(Laser(center=(x[0] - 4, 0), wavelength=WAVELENGTH, label="Laser", label_side="bottom"))
    state = scene.add(Polarizer(center=(x[1], 0), axis_angle=0.0, label="Polarizing element", label_side="top"))
    # The analyser is a group of two parts, as the dashed box in the figure.
    box = scene.group(label="Analyzer")
    # the plate turns; the drawing shows it at 30 degrees, so the polarization overlay shows an elliptical state
    qwp = box.add(QuarterWavePlate(center=(x[2], 0), fast_axis_angle=30.0, design_wavelength_nm=WAVELENGTH,
                                   label="Rotating QWP", label_side="bottom"))
    # base_mount="rotation_stage" draws the plate in a rotation mount in 3D: it shows that it rotates
    qwp.base_mount = "rotation_stage"
    pol = box.add(Polarizer(center=(x[3], 0), axis_angle=0.0, label="Fixed H polariser", label_side="top"))
    det = scene.add(Photodiode(center=(x[4] + 4, 0), label="Optical detector", label_side="bottom"))
    face(det, pol)
    scene.add(Beam.through(laser, state, qwp, pol, det, wavelength=WAVELENGTH))
    scene.set_view_layout({"1d": {"spacing": 1}})       # the 1D copies the 2D: the side arm, the label room
    scene.fit_frame(margin=8)
    return scene
