# A balanced homodyne receiver and its TIA, after Yang et al., Micromachines 16, 1416 (2025), Fig. 3
from optodraw import TIA, EdgeCoupler, ElectricalPad, MMI2x2, OnChipPhotodetector, PhaseShifter, Scene

scene = Scene(title="Balanced homodyne receiver", platform="on_chip")
signal = scene.add(EdgeCoupler(center=(-150, 22), label="Signal"))
lo = scene.add(EdgeCoupler(center=(-150, -22), label="LO"))
shifter = scene.add(PhaseShifter(center=(-88, 22), label="Phase shifter"))
mmi = scene.add(MMI2x2(center=(-10, 0), label="2x2 MMI"))
pd_top = scene.add(OnChipPhotodetector(center=(88, 16), label="PD"))
pd_bottom = scene.add(OnChipPhotodetector(center=(88, -16), label="PD"))
tia = scene.add(TIA(center=(175, 0), label="TIA"))
pads = {name: scene.add(ElectricalPad(center=xy, width=14, height=14, port_side=side, label=name))
        for name, xy, side in (("V+", (108, 52), "bottom"), ("V-", (108, -52), "top"),
                               ("H1", (-106, 50), "bottom"), ("H2", (-70, 50), "bottom"),
                               ("Out", (215, 0), "left"))}
for a, ap, b, bp in ((signal, "o1", shifter, "o1"), (shifter, "o2", mmi, "o2"), (lo, "o1", mmi, "o1"),
                     (mmi, "o4", pd_top, "o1"), (mmi, "o3", pd_bottom, "o1")):
    scene.route((a, ap), (b, bp), kind="waveguide", path_type="smooth")
# each detector has two contacts: the shared middle node goes to the TIA, the outer ones to the bias pads
for a, ap, b, bp in ((pd_top, "e1", pads["V+"], "e1"), (pd_bottom, "e2", pads["V-"], "e1"),
                     (pd_top, "e2", tia, "e1"), (pd_bottom, "e1", tia, "e1"),
                     (shifter, "h1", pads["H1"], "e1"), (shifter, "h2", pads["H2"], "e1"),
                     (tia, "e2", pads["Out"], "e1")):
    scene.route((a, ap), (b, bp), kind="electrical", width=1.2)
for part in (signal, lo):
    part.label_side = "left"
pd_top.label_side = pd_bottom.label_side = "right"
pads["V-"].label_side = "bottom"
scene.fit_frame(margin=8)
scene
