# A Mach-Zehnder modulator with G-S-G electrodes, after Wolf et al., Sci. Rep. 8, 2598 (2018), Fig. 1a
from optodraw import MZM, Scene, SignalArrow

scene = Scene(title="SOH Mach-Zehnder modulator", platform="on_chip")
# the library modulator: two arms in the gaps of a ground-signal-ground line
mzm = scene.add(MZM(center=(0, 0), drive_style="gsg", label="SOH MZM"))
for x, name in ((-65, "In"), (65, "Out")):            # the light in and out, at the ports
    arrow = scene.add(SignalArrow((-8, 0), (8, 0), center=(x, 0), color="#333333", label=name))
scene.fit_frame(margin=8)
scene
