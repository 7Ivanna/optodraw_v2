# Two coupled add-drop rings with heaters, after Borghi et al., Sci. Rep. 9, 408 (2019), Fig. 1
from optodraw import MicroringResonator, Scene, SignalArrow

scene = Scene(title="Photonic molecule", platform="on_chip")
ring1 = scene.add(MicroringResonator(center=(-26, 0), add_drop=True, with_heater=True, label="1"))
ring2 = scene.add(MicroringResonator(center=(26, 0), add_drop=True, with_heater=True, label="2"))
scene.route((ring1, "o2"), (ring2, "o1"), kind="waveguide", color="#2b6cb0")   # In bus
scene.route((ring1, "o4"), (ring2, "o3"), kind="waveguide", color="#2b6cb0")   # Drop bus
# light in at the lower left, out of the drop port at the upper left, in the paper's colours: each arrow ends on
# its bus (the ring's o1 and o3 ports), stacked 3 um apart round the bus line
arrows = [("o1", "#e0302a", "Pump", True, 1.5), ("o1", "#2a5de0", "Idler", True, -1.5),
          ("o3", "#2aa84a", "Signal", False, 3.0), ("o3", "#2a5de0", "Idler", False, 0.0),
          ("o3", "#e0302a", "Pump", False, -3.0)]
for port, colour, name, inward, dy in arrows:
    end = ring1.world_port(port).center
    ends = ((-14, 0), (-1, 0)) if inward else ((-1, 0), (-14, 0))
    arrow = scene.add(SignalArrow(*ends, center=(end.x, end.y + dy), color=colour, label=name, width=1.0,
                                  head_size=2.5))
    arrow.label_side = "left"
scene.fit_frame(margin=8)
scene
