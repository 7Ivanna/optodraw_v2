# The receiver's amplifier as a circuit
from optodraw import (Capacitor, ElectricalPad, Ground, OnChipPhotodetector, OpAmp, Resistor, Scene,
                      VerticalGratingCoupler)

# on a chip scene the 1D view keeps the 2D plan: each symbol where its part stands
scene = Scene(title="Transimpedance amplifier", platform="on_chip")
amp = scene.add(OpAmp(center=(0, 0), label="TIA", label_side="bottom"))
r_f = scene.add(Resistor(center=(0, 10), label="R_f", value="10 kΩ"))
c_f = scene.add(Capacitor(center=(0, 24), label="C_f", value="0.2 pF"))
ground = scene.add(Ground(center=(-9, -8)))
pd = scene.add(OnChipPhotodetector(center=(-62, 0), label="PD"))
light = scene.add(VerticalGratingCoupler(center=(-136, 0), angle=180, label="light in"))   # o1 faces the PD
bias = scene.add(ElectricalPad(center=(-42.2, 22), width=6, height=6, port_side="bottom", label="V_{bias}"))
out = scene.add(ElectricalPad(center=(28, 0), width=6, height=6, label="V_{out}"))
scene.route((light, "o1"), (pd, "o1"))
for a, b in (((pd, "e1"), (bias, "e1")), ((pd, "e2"), (amp, "in_n")), ((r_f, "e1"), (amp, "in_n")),
             ((c_f, "e1"), (r_f, "e1")), ((r_f, "e2"), (amp, "out")), ((c_f, "e2"), (r_f, "e2")),
             ((amp, "in_p"), (ground, "e1")), ((amp, "out"), (out, "e1"))):
    scene.route(a, b, kind="electrical", width=0.25)
scene.fit_frame(margin=4)
scene
