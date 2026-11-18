# A 1x4 AWG demultiplexer, after Smit and van Dam, IEEE J. Sel. Top. Quantum Electron. 2, 236-250 (1996)
from optodraw import AWG, OnChipPhotodetector, Scene, VerticalGratingCoupler
from optodraw.layout import chain_ports

scene = Scene(title="1x4 AWG demultiplexer", platform="on_chip")
gc = scene.add(VerticalGratingCoupler(center=(-195, -35), angle=180, label="in"))  # centred on the frame
awg = scene.add(AWG(channel_count=4, array_count=8, label="AWG"))
chain_ports([(gc, "o1", awg, "i1")], gap=40.0, grid=0.0)          # the AWG one gap after the coupler
# one detector per channel, on the pitch of a detector, with room for the fan-out
outputs = [awg.world_ports()[f"o{i}"].center for i in range(1, 5)]
pitch = 32.0
x = max(p.x for p in outputs) + 60.0 - OnChipPhotodetector().ports()["o1"].center.x
detectors = [scene.add(OnChipPhotodetector(center=(x, -35 + (i - 1.5) * pitch), label=f"PD{i + 1}"))
             for i in range(4)]
scene.route((gc, "o1"), (awg, "i1"), kind="waveguide", path_type="smooth")
for i, pd in enumerate(detectors, start=1):
    scene.route((awg, f"o{i}"), (pd, "o1"), kind="waveguide", path_type="smooth")
    pd.label_side = "right"
scene.fit_frame(margin=10)
scene
