# A simple ODMR microscope, after Babashah et al., SciPost Phys. Core 6, 065 (2023), Fig. 4
from optodraw import Beam, BeamSplitter, Filter, Laser, Lens, Objective, Photodiode, Sample, Scene
from optodraw.layout import aim

scene = Scene(title="ODMR setup", platform="free_space")
scene.set_view_layout({"3d": {"spacing": "auto"}})   # 3D: room for every post; 1D and 2D stay compact
pump = scene.add(Laser(center=(-38, 0), wavelength=532, label="Laser (dichroic pumping)"))
side = scene.add(Laser(center=(-38, -25.8), wavelength=532, label="Laser (side pumping)"))
dichroic = scene.add(BeamSplitter(center=(0, 0), dichroic=True, cutoff_wavelength=600,
                                  label="Dichroic mirror"))
objective = scene.add(Objective(center=(0, -13), angle=-90, label="Microscope objective"))
# turned to face the objective, on the XYZ micro positioner: a motion mark in 1D and 2D, the stages in 3D
sample = scene.add(Sample(center=(0, -26), angle=-90, label="Sample on XYZ stage", base_mount="xyz_stage"))
filt = scene.add(Filter(center=(0, 10), angle=90, label="IF filter"))
lens = scene.add(Lens(center=(0, 20), angle=90, label="Lens"))
pd = scene.add(Photodiode(center=(0, 31), angle=90, label="Photodetector"))
aim(dichroic, pump, objective)
for part in (dichroic, objective, sample, filt, lens, pd):
    part.label_side = "right"
pump.label_side = side.label_side = "bottom"
# the green pump goes down and the red photoluminescence comes back up the same axis (drawn narrower)
scene.add(Beam.through(pump, dichroic, objective, (sample, "in"), wavelength=532, width=1.0))
scene.add(Beam.through(side, (sample, "side_in"), wavelength=532, width=1.0, opacity=0.45))   # the side-pumping option
scene.add(Beam.through((sample, "in"), objective, dichroic, filt, lens, pd, wavelength=690, width=0.45))
scene.fit_frame(margin=8)
scene
