"""Ø1/2in post, post holder and base — the pedestal under every bench optic.

Catalogue figures (mm), Thorlabs TR/PH/BA series:
  post          Ø12.7 (1/2in), 50-150 long
  post holder   Ø19.0 OD, 12.7 bore, 50 tall, thumbscrew on the side
  base (BA1)    38.1 x 58.4 x 9.5, slotted for a 1/4in-20 or M6 screw
  optic         Ø25.4 (1in) — the reference everything is scaled against
"""

from build123d import BuildPart, Box, Cylinder, Locations, Mode, export_step

OPTIC = 25.4
POST_D = 12.7
HOLDER_OD = 19.0
HOLDER_H = 50.0
BASE_L, BASE_W, BASE_T = 58.4, 38.1, 9.5

with BuildPart() as pedestal:
    with Locations((0, 0, BASE_T / 2)):
        Box(BASE_L, BASE_W, BASE_T)
    with Locations((0, 0, BASE_T + HOLDER_H / 2)):
        Cylinder(HOLDER_OD / 2, HOLDER_H)
    with Locations((0, 0, BASE_T + HOLDER_H + 40)):
        Cylinder(POST_D / 2, 80)
    with Locations((0, 0, BASE_T + HOLDER_H)):
        Cylinder(POST_D / 2, HOLDER_H, mode=Mode.SUBTRACT)

print("--- pedestal proportions, per Ø1in optic diameter ---")
print(f"post Ø        : {POST_D / OPTIC:.3f}a   ({POST_D} mm)")
print(f"holder OD     : {HOLDER_OD / OPTIC:.3f}a   ({HOLDER_OD} mm)")
print(f"base width    : {BASE_W / OPTIC:.3f}a   ({BASE_W} mm)")
print(f"base length   : {BASE_L / OPTIC:.3f}a   ({BASE_L} mm)")
print(f"base thickness: {BASE_T / OPTIC:.3f}a   ({BASE_T} mm)")
print(f"breadboard pitch: {25.0 / OPTIC:.3f}a  (25 mm metric / 1in imperial)")

export_step(pedestal.part, "post_assembly.step")
print("\nwrote post_assembly.step")
