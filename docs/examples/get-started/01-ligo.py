# Advanced LIGO, after Abbott et al., Phys. Rev. Lett. 116, 061102 (2016), Fig. 3
from optodraw import Beam, BeamSplitter, Laser, Mirror, PartialMirror, Photodiode, Scene
from optodraw.layout import aim

scene = Scene(title="Advanced LIGO", platform="free_space")
scene.set_view_layout({"1d": {"spacing": 1}, "3d": {"spacing": "auto"}})   # 1D as drawn; 3D makes room for posts
laser = scene.add(Laser(center=(-43, -10), wavelength=1064, label="Laser source"))
# partial mirrors pass their transmission in percent, from Aasi et al., Class. Quantum Grav. 32,
# 074001 (2015); only the end mirrors reflect all
prm = scene.add(PartialMirror(center=(-17, -10), transmission=3, label="Power recycling"))
bs = scene.add(BeamSplitter(center=(-1, -10), angle=-45, label="Beam splitter"))
itm_x = scene.add(PartialMirror(center=(17, -10), aperture=10, transmission=1.4, label="Test mass"))
etm_x = scene.add(Mirror(center=(47, -10), aperture=10, label="Test mass"))
itm_y = scene.add(PartialMirror(center=(-1, 8), angle=90, aperture=10, transmission=1.4, label="Test mass"))
etm_y = scene.add(Mirror(center=(-1, 36), angle=90, aperture=10, label="Test mass"))
srm = scene.add(PartialMirror(center=(-1, -26), angle=90, transmission=20, label="Signal recycling"))
pd = scene.add(Photodiode(center=(-1, -38), angle=-90, label="Photodetector"))
# the coated faces of the partial mirrors face into their cavities
for mirror, cavity in ((prm, bs), (itm_x, etm_x), (etm_x, itm_x),
                       (itm_y, etm_y), (etm_y, itm_y), (srm, bs)):
    aim(mirror, cavity, cavity)
aim(bs, prm, itm_y)
for part, side in ((laser, "top"), (prm, "bottom"), (bs, "top-right"), (itm_x, "bottom"), (etm_x, "top"),
                   (itm_y, "left"), (etm_y, "left"), (srm, "left"), (pd, "right")):
    part.label_side = side
# Beam.through attaches the light at each part's faces: it starts at the laser's edge and bends on mirrors
scene.add(Beam.through(laser, prm, bs, itm_x, etm_x, wavelength=1064, width=0.5))
scene.add(Beam.through(bs, itm_y, etm_y, wavelength=1064, width=0.5))
scene.add(Beam.through(bs, srm, pd, wavelength=1064, width=0.5))
scene.fit_frame(margin=12)
scene
