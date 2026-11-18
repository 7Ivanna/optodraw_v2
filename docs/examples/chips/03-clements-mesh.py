# A universal 9-mode interferometer: the rectangular mesh of 36 MZIs, after Clements et al., Optica 3, 1460 (2016), Fig. 1b
from optodraw import MZI, EdgeCoupler, Scene

N, PITCH, STEP = 9, 32.0, 150.0                      # modes; mode spacing and column spacing, in um
scene = Scene(title="Clements mesh", platform="on_chip")


def y(mode):
    return (mode - (N - 1) / 2) * PITCH


# column k holds the MZIs on the mode pairs (k % 2, k % 2 + 1), (k % 2 + 2, ...): N (N - 1) / 2 in all
last = {}                                            # mode -> the part and port the light leaves by
for mode in range(N):
    coupler = scene.add(EdgeCoupler(center=(-0.9 * STEP, y(mode)), label=str(mode + 1)))
    last[mode] = (coupler, "o1")
for column in range(N):
    for low in range(column % 2, N - 1, 2):
        mzi = scene.add(MZI(center=(column * STEP, (y(low) + y(low + 1)) / 2), label=""))
        scene.leave_open(mzi, "h1", "h2")           # the paper draws the phase shifters with no wires
        for mode, port_in, port_out in ((low, "o2", "o4"), (low + 1, "o1", "o3")):
            scene.route(last[mode], (mzi, port_in), kind="waveguide", path_type="smooth")
            last[mode] = (mzi, port_out)
for mode in range(N):
    coupler = scene.add(EdgeCoupler(center=(N * STEP - 0.1 * STEP, y(mode)), angle=180, label=str(mode + 1)))
    scene.route(last[mode], (coupler, "o1"), kind="waveguide", path_type="smooth")
scene.fit_frame(margin=10)
scene
