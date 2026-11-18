"""Michelson FTIR interferometer after Ni et al., Sensors 20(7), 1833 (2020), Fig. 1.

Units: millimetres on the page. The paper gives no dimensions, so the distances are chosen to keep the figure compact.
"""

from __future__ import annotations
from optodraw import Beam, BeamSplitter, Lamp, Lens, Mirror, Photodiode, Scene
from optodraw.layout import aim, face

WAVELENGTH = 3000  # nm; the paper states none. Only sets the beam colour and the source metadata.


PAPER = {
    "citation": "Z. Ni, Q. Lu, Y. Xu, H. Huo, Intensity Simulation of a Fourier Transform Infrared "
                "Spectrometer, Sensors 20(7), 1833 (2020)",
    "doi": "10.3390/s20071833",
    "figure": "Figure 1",
}


def build(title: str = "Michelson FTIR interferometer (after Ni 2020)") -> Scene:
    scene = Scene(title=title, width=89, height=70, platform="free_space")
    scene.metadata["paper"] = dict(PAPER)
    # G1 sits at the origin. Arm M1 goes up, arm M2 goes right, the output goes down.
    source = scene.add(Lamp(center=(-20, 0), label="Light source", label_side="top"))
    g1 = scene.add(BeamSplitter(center=(0, 0), transmission=50, label="G1", label_side="bottom-left"))
    g2 = scene.add(BeamSplitter(center=(11, 0), transmission=100, label="G2", label_side="top"))
    m1 = scene.add(Mirror(center=(0, 14), label="M1", label_side="right"))
    # the paper also draws M2', the virtual image of M2 in G1, dashed over M1: no light reaches it, so it is left
    # out and every part drawn has its ports in use
    # base_mount="stage" draws the mirror on a translation stage in 3D: it shows that M2 moves
    m2 = scene.add(Mirror(center=(23, 0), label="M2", label_side="top", base_mount="stage"))
    lens = scene.add(Lens(center=(0, -12), angle=-90, focal_length=10, aperture=10, label="L", label_side="right"))
    # one detector at the lens's focal plane: a photodiode has only its light input, so no wire stub sits in line
    # with the beam as a camera's would
    plane = scene.add(Photodiode(center=(0, -22 - 3.0), label="Focal plane", label_side="right"))

    aim(g1, source, m1)        # G1 reflects the source beam up to M1
    g2.transform.rotation_deg.z = g1.transform.rotation_deg.z   # G2 parallel to G1 (same tilt)
    aim(m1, g1, g1)
    aim(m2, g1, g1)
    face(plane, lens)
    # aim() turns G1 so that "refl" faces the source (left), "in" faces M1 (up), "tap" faces G2 and M2 (right)
    # and "trans" faces the lens (down); G2 has the same turn. Each beam enters and leaves by the face it meets.
    # Beam A: through G1 to the moving mirror and back, then reflected down through the lens
    scene.add(Beam.through(source, (g1, "refl"), (g1, "tap"), (g2, "refl"), (g2, "tap"), m2, (g2, "tap"),
                           (g2, "refl"), (g1, "tap"), (g1, "trans"), lens, plane, wavelength=WAVELENGTH, label=""))
    # Beam B: reflected up to the fixed mirror, back through G1 and down
    scene.add(Beam.through((g1, "in"), m1, (g1, "in"), (g1, "trans"), lens, plane, wavelength=WAVELENGTH))
    scene.set_view_layout({"1d": {"spacing": 1}})       # the 1D copies the 2D
    scene.fit_frame(margin=8)
    return scene
