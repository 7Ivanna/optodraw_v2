# The die on its board: wire bonds, a fibre array and an SMA jack
from optodraw import ChipSubstrate, ElectricalPad, FiberArray, PCB, SMAConnector, Scene

scene = Scene(title="Die on a board", platform="mixed")
scene.add(PCB(center=(-6, 0), length=40, width=24, pad_count=2, style="plain", color="#b9d8c3", label="Test board",
              label_side="bottom"))
die = scene.add(ChipSubstrate(center=(-5, -1), length=18, width=13, chamfer=3, opacity=1.0, label="PIC die",
                              label_side="top"))
edge = die.drawn_box()[0]                                   # the array's polished face meets the die's left edge
scene.add(FiberArray(center=(edge - 3.6, 0.3), count=4, pitch=0.6, label="Fibre array", label_side="left"))
sma = scene.add(SMAConnector(center=(11.5, 12), angle=90, label="SMA jack", label_side="top"))
for y in (-4.5, -1.5, 1.5, 4.5):
    pads = [scene.add(ElectricalPad(center=xy, width=1.8, height=1.8, port_side="center", pad_opening=False))
            for xy in ((1.5, y - 1.25), (6.5, 1.3 * y - 1.25))]
    scene.route((pads[0], "e1"), (pads[1], "e1"), kind="wirebond")
scene.route((pads[1], "e1"), (sma, "e1"), kind="electrical", path_type="L", width=0.5)
scene.fit_frame(margin=2)
scene
