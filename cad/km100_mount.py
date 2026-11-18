"""A Ø1in kinematic mirror mount, modelled to catalogue dimensions.

Reference figures for a Thorlabs KM100-class mount (mm):
  front plate      25.4 optic bore, 38.1 square, 8.2 thick
  back plate       38.1 square, 6.4 thick
  plate separation 12.7 nominal (springs + adjusters between them)
  adjusters        3, on a 25.4 bolt circle, 100 TPI, Ø9.5 knurled knob
  post bore        M4 / 8-32 tapped, on the back plate's bottom face

Purpose here is measurement, not manufacture: optodraw needs the RATIOS
(bore vs plate, plate vs stack depth, adjuster spacing) to draw a mount that
reads correctly, and eyeballing those is what put its parts inside each other.
"""

from build123d import (
    Axis, Box, BuildPart, Cylinder, GridLocations, Location, Locations,
    Mode, PolarLocations, export_step,
)

OPTIC_BORE = 25.4
PLATE = 38.1
FRONT_T = 8.2
BACK_T = 6.4
GAP = 12.7
ADJ_CIRCLE = 25.4
KNOB_D = 9.5
KNOB_T = 6.0

with BuildPart() as mount:
    # front plate, bored for the Ø1in optic
    with Locations((0, 0, GAP / 2 + FRONT_T / 2)):
        Box(PLATE, PLATE, FRONT_T)
    with Locations((0, 0, GAP / 2 + FRONT_T / 2)):
        Cylinder(OPTIC_BORE / 2, FRONT_T * 2, mode=Mode.SUBTRACT)

    # back plate
    with Locations((0, 0, -GAP / 2 - BACK_T / 2)):
        Box(PLATE, PLATE, BACK_T)

    # three adjusters on the bolt circle: shank through the gap, knob behind
    with Locations((0, 0, -GAP / 2 - BACK_T)):
        with PolarLocations(ADJ_CIRCLE / 2, 3, start_angle=90):
            Cylinder(KNOB_D / 2, KNOB_T, align=(None, None, None))

with BuildPart() as stack:
    Box(PLATE, PLATE, FRONT_T + GAP + BACK_T)

part = mount.part
bb = part.bounding_box()
print(f"overall bbox   : {bb.size.X:.1f} x {bb.size.Y:.1f} x {bb.size.Z:.1f} mm")
print(f"optic bore     : {OPTIC_BORE:.1f}  (Ø1in optic)")
print(f"plate face     : {PLATE:.1f} square")
print(f"stack depth    : {FRONT_T + GAP + BACK_T:.1f}  (front + gap + back, before knobs)")
print()
print("--- ratios optodraw needs (everything relative to the optic diameter) ---")
print(f"plate  / optic : {PLATE / OPTIC_BORE:.3f}")
print(f"depth  / optic : {(FRONT_T + GAP + BACK_T) / OPTIC_BORE:.3f}")
print(f"front  / optic : {FRONT_T / OPTIC_BORE:.3f}")
print(f"adj circle/optic: {ADJ_CIRCLE / OPTIC_BORE:.3f}")
print(f"knob D / optic : {KNOB_D / OPTIC_BORE:.3f}")
print(f"knob T / optic : {KNOB_T / OPTIC_BORE:.3f}")

export_step(part, "km100_mount.step")
print("\nwrote km100_mount.step")
