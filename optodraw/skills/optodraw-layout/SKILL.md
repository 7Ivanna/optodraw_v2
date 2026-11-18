---
name: optodraw-layout
description: Use when placing optodraw components on a photonic chip, writing a floorplan, routing waveguides or electrical nets, laying out heater, GSG or bond pads, placing grating couplers or a GratingCouplerArray near probes, drawing an on-chip interferometer (MZI, MZM, ring), fixing routes that cross or dive, finding unwired ports, or previewing a scene in a notebook. Every rule here was learned from a layout that rendered without error and was wrong.
---

# optodraw-layout

Optodraw never refuses a bad layout. It places what you ask, routes what you
name, and returns a clean SVG, so a broken chip drawing looks exactly like a
correct one. **Look at the output before you call it done**, and run the
checks at the end of this file.

## A figure is compact, never to scale

A figure is read, not fabricated. Draw the topology of the source, not its
lengths: a 500 um heater is a short phase shifter, a 1 mm die is the box
round the parts. Long thin parts, empty bands and long wires hide the
circuit.

- Keep the schematic part sizes; never `render_physical=True` in a figure.
- Pads small (`ElectricalPad(width=12, height=12)`) and right beside the part
  they serve, on the side the wire leaves. A pad row far from its device is
  wrong.
- Parts as close as their drawn extents allow: a gap of about half a part, not
  several parts. Rows of the same parts share one pitch.
- One node, one line. When a circuit repeats a node (a weight bank, its
  detector, its laser and its modulator), put the node's parts side by side on
  one row: the rows then stack as close as the tallest part and its pads
  allow. Parts of one node stacked inside the row push every row apart.
- Wires short and Manhattan, parallel wires on tight tracks; a long loop
  (a feedback) runs in one lane round the outside, not across the figure.
- A coupler, splitter or combiner sits midway between the parts it joins, so
  its two routes are mirror images; never on one row with a forced route to
  the other.
- A part fed by one port lines up with it (a detector on the bank's through
  port, a pad straight under its contact): the link is straight in 2D and so
  in 1D.
- Use the part the function needs: a WDM multiplexer is an `AWG` (turned 180
  so its channels face the sources), not an echelle grating.
- `check_figure` reports a figure whose parts fill little of its box and a
  route far longer than the parts it joins.
- The 1D of a chip copies the 2D: get the 2D right and the 1D follows.

On a chip, scene units are **micrometres**. Every python block in this file
runs in order, as one script, in the optodraw test suite. For the figure
around a layout (the plan, the review, the export) load `optodraw-figure`.

## The parts you will use most

Ports are named for light (`o`), fibre (`f`) and wires (`e`, `h`, `sig`,
`gnd`). Positions are local, at `angle=0`; print `part.world_ports()` after
you place a part. To put a part where a port must land, use
`optodraw.layout.align_ports(source, "o2", target, "o1", gap=12)` (it moves
only the target) or `chain_ports([...])` for a whole chain.

| part | ports |
|---|---|
| `VerticalGratingCoupler` | `o1` on its west side, `f1` the fibre. On the west chip edge use `angle=180`; on the east edge `angle=0` |
| `MMI1x2` | `o1` in (west); `o2` lower out, `o3` upper out (east) |
| `MMI2x2` | `o1` lower in, `o2` upper in (west); `o3` lower out, `o4` upper out (east). Two in a switch: split `o4` to the upper arm, `o3` to the lower arm; the arms enter the second MMI at `o2` (upper) and `o1` (lower) |
| `PhaseShifter` | `o1` west, `o2` east; heater contacts `h1` (west), `h2` (east) face north. At `angle=180`: `o2` west, `o1` east, `h2` west, `h1` east, contacts facing south |
| `MZI` | an MZI with one heater, the internal phase: `o1`, `o2` west, `o3`, `o4` east, `h1`, `h2` north. The external phase of a mesh cell is a `PhaseShifter` on an input arm; give it the MZI's waveguide `width`, or the guide steps |
| `MZM` | `o1` west, `o3` east; `o2` north and `o4` south are extra optical ports; `sig`, `gnd` west (`drive_style="gsg"` gives `gnd1`, `sig`, `gnd2`) |
| `ElectricalPad` | `e1` on its west edge, facing west; `angle=90` puts it on the south edge |
| `GSGProbePad` | one probe's three pads. At `angle=90` the ports face south, `g1` on the west; at `angle=-90` they face north, `g1` on the east |
| `OnChipPhotodetector` | `o1` west; `e1` north, `e2` south are its own probe pads: a probe lands there, so they may stay unwired |
| `OnChipBalancedPhotodetector` | `o1`, `o2` west, the two inputs; `e1`, `out`, `e2` its own G-S-G probe pads |
| `Waveguide` | a straight lead: its ports are not at plus and minus half its `length`; read `world_ports()` |
| `Terminator` | `o1`: ends an unused optical port |
| `GratingAntennaArray` | an optical phased array's emitters: `o1` (lowest) to `o{count}`, all on the west ends; no outputs, the light leaves upward. Feed it from a splitter tree whose last outputs lie on its pitch |
| `PCMCell` | a GST film on a guide: `o1` west, `o2` east; `state="crystalline"` (dark) or `"amorphous"` (pale) |
| `EORacetrackModulator` | a Pockels racetrack (thin-film LN): the bus passes the west bend, `o1` at its north end, `o2` at its south end; `gnd1`, `sig`, `gnd2` on one line through the centre, where a G-S-G probe lands: they may stay unwired |

Find the rest with `optodraw.catalog.list_components(platform="on_chip")`.

## The rule that prevents most of the damage

**Measure a component's drawn extent. Never infer it from its ports.**

```python
from optodraw import AWG, Scene


def drawn_box(component):
    """The box (x0, y0, x1, y1) a component draws; build it with center=(0, 0) to get its own size."""
    probe = Scene(title="", width=2000, height=2000, platform="on_chip")
    probe.add(component)
    return probe.content_bounds()


def half_size(component):
    x0, y0, x1, y1 = drawn_box(component)
    return 0.5 * (x1 - x0), 0.5 * (y1 - y0)


awg = AWG(channel_count=4, array_count=8)
x0, y0, x1, y1 = drawn_box(awg)
port_y = [p.center.y for p in awg.ports().values()]
print(f"AWG ports span {max(port_y) - min(port_y):.1f} um in y; the AWG draws {y1 - y0:.1f} um tall")
```

Chip parts draw at a schematic size: `MZM(arm_length=500)` draws 108 um long.
The arguments set the physical values the part reports; the drawing and the
ports follow the schematic table. So `DirectionalCoupler(port_spacing=56)`
still has its ports about 10 um apart, and `Waveguide(length=2.5)` draws 24 um
long: route to where the ports are (`ports()`), not to the spacing you asked
for. Keep it that way for a figure (see "A figure is compact" above);
`render_physical=True` is for a to-scale layout the user asks for.

An `AWG` keeps its ports within a few micrometres in y and draws its array
far taller. An `SOA` extends its own waveguides past its ports. A `Spiral` is
mostly empty space. Keep the measured half widths as named constants and
derive each stage's centre from the one before, so a change to one gap moves
everything downstream.

## A worked layout: a thermo-optic MZI switch

```python
from optodraw import ElectricalPad, MMI1x2, MMI2x2, PhaseShifter, Scene, VerticalGratingCoupler

ARM = 25.0                                        # each arm 25 um off the axis: the arms are equal
assert ARM > half_size(PhaseShifter())[1] + 3.0    # the arm pitch clears the phase shifter it carries
chip = Scene(title="Thermo-optic MZI switch", width=400, height=200, platform="on_chip")
split = chip.add(MMI1x2(center=(-70, 0), label="1x2 MMI"))
join = chip.add(MMI2x2(center=(70, 0), label="2x2 MMI"))
top = chip.add(PhaseShifter(center=(0, ARM), label="PS top"))
bottom = chip.add(PhaseShifter(center=(0, -ARM), angle=180, label="PS bottom"))   # contacts face south
gc_in = chip.add(VerticalGratingCoupler(center=(-140, 0), angle=180, label="In"))
gc_1 = chip.add(VerticalGratingCoupler(center=(140, 20), label="Out 1"))
gc_2 = chip.add(VerticalGratingCoupler(center=(140, -20), label="Out 2"))
pads = {name: chip.add(ElectricalPad(center=(x, y), angle=90 if y > 0 else -90, label=name,
                                     label_side="top" if y > 0 else "bottom"))
        for name, (x, y) in {"T1": (-22, 70), "T2": (22, 70), "B1": (-22, -70), "B2": (22, -70)}.items()}

optical = [((gc_in, "o1"), (split, "o1")), ((split, "o3"), (top, "o1")), ((split, "o2"), (bottom, "o2")),
           ((top, "o2"), (join, "o2")), ((bottom, "o1"), (join, "o1")),
           ((join, "o4"), (gc_1, "o1")), ((join, "o3"), (gc_2, "o1"))]
electrical = [((top, "h1"), (pads["T1"], "e1")), ((top, "h2"), (pads["T2"], "e1")),
              ((bottom, "h2"), (pads["B1"], "e1")), ((bottom, "h1"), (pads["B2"], "e1"))]
for a, b in optical:
    chip.route(a, b, kind="waveguide", path_type="smooth")
for a, b in electrical:
    chip.route(a, b, kind="electrical", path_type="L", width=1.4)
chip.fit_frame(margin=12)
chip.render_svg("mzi_switch.svg")
```

- **An interferometer is symmetric.** Equal arms, the parts on the two arms at
  the same x, the arms parallel and only as far apart as the widest arm part
  needs. Unequal arms draw a path difference the device does not have. When
  the circuit is a standard MZI, the `MZI` part draws it whole.
- **The arms form a closed loop.** A heater on the lower arm cannot reach a
  pad on the north edge without crossing the upper arm. Give each arm the
  pads on its own side (north and south here), and tell the user if the
  request forces a crossing.
- **A pad's port faces the trace.** `ElectricalPad`'s `e1` is on its west
  edge; turned 90 degrees it sits on the south edge, so a trace from below
  enters it straight. A trace that runs into a pad and hooks back to the far
  edge is wrong.
- Optical I/O on the west and east edges, pads north and south: a fibre array
  and a probe card do not collide.

## Routing

**1. A route needs horizontal room in proportion to its vertical rise.** Aim
for a gap of about 1.5 times the rise: a fan-out from `y = 0` to `y = ±200`
wants about 300 um of clear x. Starve it and the router produces a near
vertical dive.

**2. Optical routes use `path_type="smooth"`.** Waveguides bend; they do not
turn square corners. Electrical routes use `path_type="L"`.

**2a. One width, one colour, bends you can see.** Every part draws its
waveguides 1.2 um wide in the parts' silicon colour, and so does a waveguide
route by default: give a route `width=` only to match a part that differs (an
MMI's 1.7 um access, which then tapers). A bend radius under about 1 % of the
figure's width reads as a square corner: 6 to 8 um on a 700 um figure. An
explicit `Route(points, smooth=True)` is never rounded; when you need exact
waypoints, route between the ports with `steps=`, `smooth=True` and
`bend_radius=`. A manhattan route with steps is nudged off the port boxes of
the parts it joins; for lanes that must stay exactly where you put them, use
`path_type="manual"`.

**3. No route crosses another**: waveguide, wire or both. If two want the
same space, the parts are too close or the port order is wrong (rule 4).

**4. A rotated component reverses its port order in world coordinates.**

```python
mux = AWG(center=(0, 0), angle=180, channel_count=4, array_count=8)
for name in ("o1", "o4"):
    local_y = mux.ports()[name].center.y
    world_y = mux.world_ports()[name].center.y
    print(f"{name}: local y {local_y:+.1f}, world y {world_y:+.1f}")
```

At `angle=180` the order flips, so `laser[i] -> f"o{i+1}"` crosses every
route. Count down (`f"o{4-i}"`), or keep the part at `angle=0`.

**5. Match the port pitch.** Give a detector array the spacing of the source
that feeds it, and fan out two close outputs (an MZI's are 14 um apart)
before their detectors: two detectors on a 14 um pitch overlap.

**6. Waypoints.** `steps=[...]` lists points the route passes, in order, each
`{"x": ...}`, `{"y": ...}` (absolute) or `{"dx": ...}`, `{"dy": ...}`
(relative to the point before); the router then turns into the end port.
Give a full chain, for example `[{"y": rail_y}, {"x": leg_x}, {"y": pad_y}]`
with `end_straight_length=0`, not a lone `{"y": ...}`: a lone rail runs the
trace along the pad row and through the next pad. A route that turns back
(light leaves west and enters a port that faces west) takes a lane past both
ports: `steps=[{"x": lane_x}, {"y": port_y}]`. The outer turn takes the outer
lane, so two U-turns do not cross.

**7. A lattice (a mesh) needs no bends.** Make the row pitch equal to the
parts' port spacing and the column step equal for every column: the routes
between columns then run straight.

**7a. Fan-outs and fan-ins.** From a splitter's stacked outputs, a route that
turns down turns before the ones over it (the lowest output first) and a route
that turns up turns after them; every lane lies beyond the outputs' x, or the
route leaves its port and doubles back. Into a tilted face (an `AWG`'s channel
ports), end every lead at one x: the leads then form a parallel fan into the
face, and the 1D, which stacks those ports in a column, needs no jog. Two ports
at a right angle need no steps: the router joins them with one bend.

**8. A route that fails is missing.** A route whose end lies behind its start
warns "Routing failed" and draws nothing. Read every warning, and look at the
PNG for a missing link.

## Electrical routing

Each electrical port is its own net with its own `ElectricalPad`. One
`GSGProbePad` is right when the three nets land on one probe (the G-S-G of a
balanced detector or a travelling-wave modulator); use separate pads when the
nets route on their own. Pads must not overlap:
pitch at least the drawn pad width plus 6 um. Give each net its own
`start_straight_length` and `width` (grounds wider than signal, for example
2.4 and 1.4 um) so the traces fan instead of stacking on one x.
`MZM(drive_style="gsg")` puts `gnd1`, `sig`, `gnd2` on its west side, facing
west: the first leg of each trace goes west, then a rail per net, then the
pad. Order the rails so no trace crosses another: the port lowest on the part
takes the westmost leg.

## Grating couplers and bond pads

A fibre array in a V-groove and a probe card cannot sit on the same chip edge.
Put the grating couplers on the opposite edge from the bond pads, or the
optical I/O west and east with the pads north and south. One coupler, or two
on opposite ends, can stay a `VerticalGratingCoupler`; several on one edge
become a `GratingCouplerArray` (pitch often 127 um). Measure the array box and
every pad box, and keep a keep-out between them wide enough for the V-groove
fixture and the probe card.

## Check before you look

```python
from optodraw import check_figure
from optodraw.app.validation import run_checks

for finding in check_figure(chip):
    print(finding)
for issue in run_checks(chip):
    print(issue["level"], issue["kind"], issue["message"])
```

`check_figure` lists, on a chip, every optical and electrical port that no
route connects (a photodetector's two pads count; a fibre port faces off the
chip and does not), every pair of routes that cross, and the label faults of
the figure. End an unused optical port on a `Terminator`, unless the source
figure draws a free end (the input leads of a theory mesh): then say so. With
`preset=`, a chip's labels are checked at the size the `fit="width"` export
prints them. It also reports a route drawn across a part it does not join (a
pad row on top of a waveguide), and, in 1D, a route that crosses more links
than its 2D route does. `run_checks` adds the coupler checks and suggests a
`ChipSubstrate` to fix the die in 3D.

The 1D closes each column on its own: a row rises until it meets the part
over it in its column, never past a part it links to, and pads sit right under
their contacts. If the 1D still shows uneven rows or long pad wires, look for
the cause in the 2D (a part of one node stacked inside its row, a splitter
placed between two rows) and say what you changed.

## Components with geometry that can be requested and not delivered

**`AWGR`: `channel_spacing` is an aperture pitch on the focal arc.** The
constructor clamps a pitch that opens the fan beyond 60 degrees and warns.
`fpr_width` is physical metadata, not the drawing. Measure the actual ports:

```python
from optodraw import AWGR

awgr_chip = Scene(title="AWGR", width=400, height=300, platform="on_chip")
fpr_length = 60.0
awgr = awgr_chip.add(AWGR(center=(0, 0), channel_count=4, array_count=12,
                          channel_spacing=14.0, fpr_length=fpr_length,
                          fpr_separation=AWGR.min_fpr_separation(fpr_length)))
print({name: round(float(port.center.y), 1) for name, port in awgr.world_ports().items()})
```

Treat an AWGR spacing or separation warning as a layout defect.

## Previewing

```python
viewer = chip.preview(width=1100, height=600)    # fixed pane, 2D and 3D tabs
light = chip.preview(show_3d=False)              # smaller notebook output
viewer.save("viewer.html")
```

`render_svg()` in a notebook cell grows to the size of the layout;
`preview()` keeps the pane the size you asked for.

## Before you call a layout finished

1. **Render it and look.** Convert the SVG to a PNG (`cairosvg.svg2png`) and
   open it; then crop the input stage, the output stage and every junction.
2. **`check_figure` is empty**, or you told the user why each finding stays.
3. **Check both axes.** Parts on parallel arms overlap vertically when the
   arm pitch is smaller than the tallest part on an arm.
4. **Read every warning as a defect.**
5. **Labels sit beside their parts**: an on-chip label is small next to a pad,
   so check it at the final figure size (`optodraw-figure`).
6. **Couplers and pads sit on different edges**, with a keep-out between.

## Red flags

| what you see | what it usually is |
|---|---|
| arms of different shapes or lengths | an interferometer drawn asymmetric |
| routes leaving a part almost vertically | not enough x between stages, rule 1 |
| an X of crossing routes at one stage | rotated part, port order reversed, rule 4 |
| a part sitting inside another | placed on port spacing, not drawn extent |
| an empty half of the figure | layout not built around the origin |
| two detectors drawn on top of each other | outputs not fanned out, rule 5 |
| a trace that runs into a pad and hooks back | the pad's port faces away; turn the pad |
| a metal trace across a waveguide | a heater's pads on the far side of a loop |
| a short stub ending in mid air | an unconnected port: run `check_figure` |
| grating couplers on the same edge as pads | fibre array and probe card collide |
| routes thinner or another blue than the parts' waveguides | a `width=` or `color=` set on the route, rule 2a |
| square corners on an optical route | an explicit-point `Route`, or a bend radius too small to see, rule 2a |
| a lane that leaves its port and comes back | the lane's x lies behind the port, rule 7a |
| leads into an AWG that jog in 1D | the leads do not end at one x, rule 7a |
| rows far apart, the bands between them empty | a node's parts stacked inside its row: one node, one line |
