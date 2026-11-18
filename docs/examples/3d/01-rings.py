# The coupled rings of Borghi et al., Sci. Rep. 9, 408 (2019), Fig. 1
from optodraw import MicroringResonator, Scene

scene = Scene(title="Photonic molecule", platform="on_chip")
ring1 = scene.add(MicroringResonator(center=(-26, 0), add_drop=True, with_heater=True, label="1"))
ring2 = scene.add(MicroringResonator(center=(26, 0), add_drop=True, with_heater=True, label="2"))
scene.route((ring1, "o2"), (ring2, "o1"), kind="waveguide")
scene.route((ring1, "o4"), (ring2, "o3"), kind="waveguide")
# as the paper's figure: heaters with no contacts, and the bus ends where the light enters and leaves left open
for ring in (ring1, ring2):
    scene.leave_open(ring, "e1", "e2")
scene.leave_open(ring1, "o1", "o3")
scene.leave_open(ring2, "o2", "o4")
scene
