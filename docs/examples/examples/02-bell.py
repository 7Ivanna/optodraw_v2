# A Bell-test bench for students, after Lahoz Sanz et al., EPJ Quantum Technol. 11, 86 (2024), Fig. 4
import math

from optodraw import (PBS, Beam, BeamDump, CoincidenceCounter, Computer, Filter, FiberCollimator,
                      HalfWavePlate, Laser, Lens, Mirror, PhotonCounter, Polarizer, QuarterWavePlate,
                      Scene, WedgePlate)
from optodraw.layout import aim

scene = Scene(title="Bell inequalities", platform="free_space")
scene.set_view_layout({"3d": {"spacing": "auto"}})   # 3D: room for every post; 1D and 2D stay compact

# photon production: the 405 nm pump folds on two mirrors into the BBO crystals (CR); the rest stops in BS
ld = scene.add(Laser(center=(-92, 33), wavelength=405, label="LD"))
fl = scene.add(Lens(center=(-77, 33), label="FL"))
bf = scene.add(Filter(center=(-69, 33), label="BF"))
hwp1 = scene.add(HalfWavePlate(center=(-57, 33), label="HWP(1)"))
lp = scene.add(Polarizer(center=(-45, 33), label="LP"))
mi1 = scene.add(Mirror(center=(-22, 33), label="MI"))
mi2 = scene.add(Mirror(center=(-63, 0), label="MI"))
hwp2 = scene.add(HalfWavePlate(center=(-33, 0), label="HWP(2)"))
cr = scene.add(WedgePlate(center=(-12, 0), label="CR"))
stop = scene.add(BeamDump(center=(100, 0), label="BS"))
aim(mi1, lp, mi2)
aim(mi2, mi1, hwp2)
scene.add(Beam.through(ld, fl, bf, hwp1, lp, mi1, mi2, hwp2, cr, stop, wavelength=405, width=0.5))

# photon detection: each 810 nm photon of a pair leaves CR at 13 degrees and meets wave plates and a PBS
# the four-channel detector (4CD) and the coincidence counter (CC) face left: the fibres come from the right
detector = scene.add(PhotonCounter(center=(37, 64), angle=180, channels=4, label="4CD"))
counter = scene.add(CoincidenceCounter(center=(-13, 64), angle=180, channels=4, label="CC"))
computer = scene.add(Computer(center=(-50, 70), label="Computer"))
for channel in range(1, 5):
    scene.route((detector, f"pulse{channel}"), (counter, f"in{channel}"), kind="electrical", width=0.6)
scene.route((counter, "data"), (computer, "e1"), kind="electrical", width=1.0,
            steps=[{"y": 52}, {"x": -72}, {"y": 70}])
for sign, arm in ((1, "a"), (-1, "b")):
    tilt = sign * 13.0
    along = lambda d: (-12 + d * math.cos(math.radians(tilt)), d * math.sin(math.radians(tilt)))  # noqa: E731
    plates = [scene.add(HalfWavePlate(center=along(29), angle=tilt, label="HWP(s)"))] if arm == "a" else []
    plates += [scene.add(QuarterWavePlate(center=along(52), angle=tilt, label=f"QWP({arm})")),
               scene.add(HalfWavePlate(center=along(65), angle=tilt, label=f"HWP({arm})")),
               scene.add(Filter(center=along(77), angle=tilt, label="IR"))]
    pbs = scene.add(PBS(center=along(90), angle=tilt, label="PBS"))
    pbs.flip_vertical = arm == "b"                      # the lower PBS reflects down
    p = pbs.transform.position
    out = math.radians(tilt + sign * 90.0)
    fc_t = scene.add(FiberCollimator(center=along(112), angle=180 + tilt, label="FC"))
    fc_r = scene.add(FiberCollimator(center=(p.x + 20 * math.cos(out), p.y + 20 * math.sin(out)),
                                     angle=math.degrees(out) + 180, label="FC"))
    for part in plates + [pbs, fc_t, fc_r]:
        part.label_side = "top" if arm == "a" else "bottom"
    scene.add(Beam.through(cr, *plates, pbs, fc_t, wavelength=810, width=0.4))
    scene.add(Beam.through(pbs, fc_r, wavelength=810, width=0.4))
    # fibres loop round the outside to the detector, each in its own lane, as in the paper; none crosses
    channels = {("a", "r"): 1, ("a", "t"): 2, ("b", "t"): 3, ("b", "r"): 4}   # turned: 1 is the lowest
    lanes = {("a", "r"): [{"y": 55}], ("a", "t"): [{"x": 122}, {"y": 61}],
             ("b", "t"): [{"x": 128}, {"y": 67}], ("b", "r"): [{"y": -62}, {"x": 134}, {"y": 73}]}
    for fc, which in ((fc_t, "t"), (fc_r, "r")):
        scene.route((fc, "in"), (detector, f"fiber{channels[arm, which]}"), kind="fiber", width=0.6,
                    path_type="smooth", steps=lanes[arm, which])
scene.fit_frame(margin=10)
scene
