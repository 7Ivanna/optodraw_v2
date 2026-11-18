---
name: optodraw-gds-3d
description: Use when turning a GDS file (a photonic or electronic chip layout) into a 3D view, a 3D image, a GLB mesh, a cross-section or an SEM-like top view (flat or tilted) with optodraw; when choosing, writing or debugging a layer stack (layer/datatype to z, thickness and material); or when a GDS renders flat, with layers in the wrong order, floating, missing, with no oxide, or with etches drawn as blocks. Covers the bundled open stacks, the stack YAML format, a preflight check that finds the silent stack faults, the failure modes and their fixes, z exaggeration, cropping, cross-sections and top views.
---

# optodraw-gds-3d

A GDS file is flat: polygons on numbered `layer/datatype` pairs and nothing
about height. The 3D view comes from a **layer stack**, a table that gives
each pair a bottom height `zmin`, a `thickness` and a `material`. Most stack
faults never stop a render: a layer the stack does not name renders as a 0.22
um slab floating above the chip; a stack written in nanometres renders 220 um
thick; a datatype that differs by one makes a layer fall back. Optodraw warns
about an undeclared layer; the other faults stay silent. **Run `check_stack`
before every render, and fix every finding.**

Install the GDS tools with `pip install "optodraw[gds]"`. Every python block
in this file runs in order, as one script, in the optodraw test suite.

## 1. Choose a layer stack

Optodraw ships the stacks of open PDKs (SiEPIC EBeam, gdsfactory generic,
Cornerstone, and `lnoi400` and `ltoi300` for thin-film lithium niobate and
lithium tantalate) and two literature stacks: `inp_generic` (InP generic
integration, no oxide) and `bto_generic` (BaTiO3 on silicon). Use the one that
matches the PDK the layout was drawn with:

```python
from pathlib import Path

from optodraw.gds import bundled_stack_names, load_layer_stack

print(bundled_stack_names())
stack = load_layer_stack("gdsfactory_generic")       # a bundled name, or the path of a YAML file
print(stack.oxide_source, stack.oxide, stack.warnings)
```

For any other process, write your own stack: copy
`optodraw/gds/stacks/_template.yaml` and fill in the numbers from the
foundry's cross-section. Microns, with `z = 0` at the bottom of the device
layer:

```python
Path("my_stack.yaml").write_text("""\
name: My process
units: um
oxide:
  box:    {thickness: 2.0, material: sio2}
  tox:    {thickness: 2.0, material: sio2}
  handle: {thickness: 2.0, material: silicon}
  passivation: {thickness: 0.5, material: sio2}
layers:
  "1/0":  {name: Waveguide, zmin: 0.00, thickness: 0.220, material: silicon, sidewall_deg: 80, color: "#c0392b"}
  "2/0":  {name: Shallow etch, zmin: 0.15, thickness: 1.850, material: air, color: "#ffffff"}
  "41/0": {name: Metal 1, zmin: 1.20, thickness: 0.700, material: aluminum, sidewall_deg: 86, role: pad, color: "#d4a017"}
  "46/0": {name: Pad open, role: pad_open, sidewall_deg: 85, visible: false}
  "68/0": {name: Device outline, visible: false}
""")
mine = load_layer_stack("my_stack.yaml")
print(sorted(mine.styles), mine.oxide_source)
```

- **Units.** Values, the `oxide:` block included, are microns unless the file
  says `units: nm`. In nm: `units: nm`, then `tox: {thickness: 2000, material:
  sio2}` and `"1/0": {name: Waveguide, zmin: 0, thickness: 220, ...}`.
- **One layer, two datatypes.** A GDS can draw one process layer on two
  datatypes (`2/0` and `2/1`). Each drawn pair needs its own entry; ask the
  user which is meant before you copy one entry to the other.
- **Layers with no height.** Outline, text, pin and floorplan layers (a
  rectangle round the whole device, for example) get `{name: ..., visible:
  false}`: they stay in the file and out of the 3D view.
- **Layer numbers.** Take them from the PDK's own layer files (its `.lyp`, its
  layer map), never from memory or from an automatic extract: extracts have
  produced layers that do not exist.
- **KLayout technology.** Load a KLayout technology with
  `load_layer_stack("tech.lyt")`; keep the folder together. The `.lyt` names its
  `.lyp` (colours and names); the heights come from its `d25/*.lyd25`. In the
  editor, use Attach technology folder. A layer that the d25 script builds from
  other layers gets no height: read `stack.warnings`.
- **Oxide.** Always write the `oxide:` block, or the wafer blocks below.
  Without either, optodraw guesses the cladding and the buried oxide and says
  so only in `stack.warnings`.
- **Etches.** `material: air` cuts the layers it overlaps: it is an etch,
  never a film. Give an etch an explicit `zmin` (the etch floor) and a
  `thickness` up to the oxide surface. One that ends inside the device layer
  (a shelf etch) is etched before the oxide; one that reaches up into the oxide
  (an oxide open, a trench, a metal open) is cut through the finished stack.
- **The oxide top.** The top oxide must reach at least the bottom of the
  highest layer that sits on it, or that layer floats. Ask the user for the
  real thickness; a guess is a guess, and you say so.
- **Waveguide width.** `waveguide: {width: 0.45, provenance: pdk, source:
  "..."}` gives the PDK's waveguide width, from its cross-section. On-chip
  parts on the stack (`scene.set_foundry_stack`) draw their guide as that width
  and every height at the same scale; a stack with no width keeps the default
  scale. Their 3D draws the stack's cladding over them, pads etched open.
- **Walls, passivation, pad openings.** `sidewall_deg` is a wall's angle from
  the wafer plane (90 is vertical). Copy it from the PDK's own layer stack:
  gdsfactory gives `LAYER_STACK.layers[name].sidewall_angle` from the
  vertical, so `sidewall_deg = 90 - angle`; a negative angle there is a hole
  wider at the top (a contact etched through oxide), which is
  `sidewall_deg = 90 - abs(angle)` on the via layer. Write the passivation
  under `oxide:` with its thickness and material, and name the layer that opens
  it over the pads with `role: pad_open` (the pad metal has `role: pad`). A
  passivation of the oxide's own material is the oxide's last level, one body
  with it; one of another material is its own film. Pads are always etched
  open: draw the pad-opening layer inside every pad.
  Take these numbers from the PDK (gdsfactory's KLayout cross-section script,
  `gdsfactory/gpdk/get_klayout_pyxs.py`, holds its passivation and tapers); a
  value missing from the stack is drawn vertical, or not at all.
- **The stack decides the look.** Every region, material, colour and angle in a
  cut comes from the stack and the GDS. If a true value does not show (a 4
  degree taper on a 0.5 um film), say so and offer a declared drawing option;
  never change the data to make it show, and never pick a material in code.
- **Confidential stacks.** A foundry's process data is usually under NDA.
  Keep its stack file out of git, out of shared notebooks and out of anything
  you publish; name the file, never paste its numbers.

### A wafer the oxide block cannot describe

A lithium niobate ridge on its own slab, or InP films grown on an InP
substrate with no oxide at all, do not fit `oxide:`. Write the wafer instead,
bottom up (a shortened `inp_generic`; the numbers show the shape only):

```yaml
substrate: {material: indium_phosphide, provenance: model, source: "..."}
films:                         # blanket films before any mask, bottom up
  - {name: N-InP buffer, material: indium_phosphide, thickness: 0.5, provenance: literature, source: "..."}
  - {name: Q(1.25), role: core, material: ingaasp, thickness: 0.5, provenance: literature, source: "..."}
  - {name: P-InP, material: indium_phosphide, thickness: 1.5, provenance: literature, source: "..."}
fill: {material: polyimide, top: flush, planarized: true}   # what fills the etched space
materials:                     # optional, this stack only: a fill colour and a label
  polyimide: {fill: "#efc27f", label: "PI"}
layers:
  "1/0": {name: Deep etch, material: air, zmin: -0.15, thickness: 2.15}
```

- A file has `oxide:` or these blocks, never both: that is a ValueError.
- A film with `role: core` is the core, at z = 0 up to its thickness. The
  films before it lie under it and the films after it lie over it. With no
  core film, `role: core` on a layer names the core at any z and in any
  material: the `lnoi400` ridge has it at z = 0.2, on its slab. With neither,
  the old rule holds: silicon or SiN at z = 0.
- `substrate.thickness` is optional: 2 um, a drawing depth, at most 6 um.
  `fill.top` is a height in um, or `flush` for the top of the wafer.
- An etch is still a layer with `material: air`: it removes what lies in its
  z band, films included.
- `source:` and `provenance:` (`pdk`, `literature` or `model`) go on any
  layer, film, substrate or fill. A PDK or literature stack sets both on every
  entry with a number. A literature stack starts with `# literature stack` and says
  in its header which values are model.
- A material outside the table draws grey, and `xs.check()` names it.
- The 3D view does not read these blocks yet: `GDSModel(process_context=True)`
  still draws a silicon handle and an oxide. Show an InP or BTO chip in a
  section or a `GdsView` until then, and say so.

```python
from optodraw.gds.parsers import stack_wafer

wafer = stack_wafer(load_layer_stack("inp_generic"))   # an oxide: stack maps onto the same shape
print([(film.name, film.zmin, film.thickness) for film in wafer.films], wafer.fill.material)
```

## 2. The preflight

`check_stack` returns one sentence per fault between a GDS and a stack, and
an empty list when they agree. It finds: several top cells and no
`cell_name`; the stack's own warnings; a guessed oxide; stack entries it
could not read; values in nm without `units: nm`; layers drawn but not in the
stack (with a hint when only the datatype differs); a drawn layer that starts
above the oxide top with no drawn layer under it (it floats); and real
geometry on the floorplan layers 99/0 and 290/0, which `GDSModel` reads as the
die outline. `load_gds_layout` and `GDSModel` also warn by themselves when a
drawn layer has no style; a model built from a file warns once for each of
them, so two warnings for one layer is normal.

```python
import gdstk

from optodraw.gds import check_stack
```

Try it on a clean file and on a broken one:

```python
lib = gdstk.Library()
cell = lib.new_cell("DEVICE")
cell.add(gdstk.rectangle((0, 0), (60, 0.5), layer=1, datatype=0))                # bus waveguide
cell.add(gdstk.ellipse((30, 6.0), 5.0, inner_radius=4.5, layer=1, datatype=0,
                       tolerance=0.01))                                           # ring
cell.add(gdstk.rectangle((70, -20), (110, 20), layer=41, datatype=0))             # metal pad
lib.write_gds("device.gds")
print("clean:", check_stack("device.gds", "gdsfactory_generic", cell_name="DEVICE"))

broken = gdstk.Library()
for name in ("A", "B"):
    top = broken.new_cell(name)
    top.add(gdstk.rectangle((0, 0), (10, 1), layer=1, datatype=2))      # datatype 2, stack has 1/0
    top.add(gdstk.rectangle((20, 0), (30, 5), layer=77, datatype=0))    # a layer no stack names
broken.write_gds("broken.gds")
problems = check_stack("broken.gds", "gdsfactory_generic")
print(*problems, sep="\n")
assert problems and not check_stack("device.gds", "gdsfactory_generic", cell_name="DEVICE")
```

A finding is a defect until you fix it or decide on purpose: text, label,
pin and floorplan layers often have no height, and you may leave them out.
Tell the user every finding and what you did with it.

## 3. The failure modes

| symptom | cause | fix |
|---|---|---|
| every layer the same height, stacked like pancakes | no stack given, or every datatype differs from the stack | pass the stack; correct the datatypes |
| one thin slab floating over the chip | a layer missing from the stack | add it, or leave it out on purpose |
| a chip hundreds of microns thick | stack values in nm without `units: nm` | add `units: nm` |
| no oxide, or the oxide at the wrong height | no `oxide:` block; the guess used the wrong layer | write the `oxide:` block |
| an etch drawn as a solid block | `process_context=False`, or the etch has no depth | `process_context=True`; give the etch `zmin` and `thickness` |
| an etch hole with no device in it | the etch layer has no device layer under it | check the layer numbers |
| the oxide vanishes above the device | real geometry on 99/0 or 290/0, read as the die outline | move it to another layer |
| the wrong device | several top cells and no `cell_name` | pass `cell_name` |
| the right colours, wrong heights | a `.lyp` gives colours and names only, never z | pair the `.lyp` with a stack YAML, or load the `.lyt` with its `d25` script |
| the cut and the 3D view disagree | two sources of heights | load one stack and use it for both |
| nothing renders | a `crop_region` outside the geometry | crop around the device you want |
| the chip looks flat | `z_exaggeration=1.0` on a sub-micron stack | raise it and say so in the caption |
| a metal hanging in the air | its `zmin` above the oxide top, no via drawn | raise the top oxide, or draw the via |
| a slab covering the whole device | an outline layer with a height | `visible: false` |
| vias and ribs with straight walls, no V | the stack lacks the PDK's sidewall angles | copy `sidewall_deg` from the PDK's stack |
| the pad metal covered, no opening | no pad-opening layer drawn, or none in the stack | draw it inside the pads; `role: pad_open` |
| a passivation in another colour than the PDK says | the passivation material missing from the stack | `passivation: {thickness, material}` |
| no M2 or M3 in a device cut | only the lowest metal drawn | draw every via and metal up to the pads |

## 4. Render the chip in 3D

Only after `check_stack` is empty (or every finding is decided):

```python
from optodraw import GDSModel, Scene
from optodraw.gds import normalize_layer_stack

scene = Scene(title="Ring and pad", width=200, height=100, platform="on_chip")
chip = scene.add(GDSModel("device.gds", cell_name="DEVICE",
                          layer_stack=normalize_layer_stack(stack.styles),
                          process_context=True, z_exaggeration=4.0, **stack.oxide))
scene.render_threejs("device_3d.html")              # interactive viewer, one file
```

- One stack, two forms: `GDSModel` takes `layer_stack=normalize_layer_stack(stack.styles)`
  and the oxide as `**stack.oxide`; `load_gds_layout` takes `layer_styles=stack.styles`.
  `GDSModel(path)` with no stack guesses every layer.
- `process_context=True` adds the buried oxide, the top cladding and the
  handle wafer and carves the etches; `**stack.oxide` passes their
  thicknesses.
- `z_exaggeration` scales every height (a value of 0 is replaced by 1).
- `crop_region=(xmin, ymin, xmax, ymax)` clips a large layout to one device.

A mesh for Blender or another 3D tool, and a still image:

```python
from optodraw.gds import load_gds_layout

layout = load_gds_layout("device.gds", cell_name="DEVICE", layer_styles=stack.styles)
result = layout.export_mesh("mesh", formats=("glb",))
print(result["glb"], result["layers"], "layers")
```

```python
# not run: needs Chrome, Chromium or Edge (OPTODRAW_CHROME names one)
scene.render_3d_image("device_3d.png", background="light", engine="viewer", scale=1.0)   # a look: seconds;
# the default studio engine is the final image and can take many minutes
```

For a paper figure, use the vector route next to the studio image:
`View3D.chip` draws the same chip as vector paths in seconds, with no
browser, on the stack's own wafer. The buried oxide is opaque, so it hides the
handle; `box="clear"` draws it clear, as the viewer does. `region=` crops it,
in file um. Put it on a `Page` (skill `optodraw-figure`); `inset.show_cut`
marks a section's cut on it.

```python
from optodraw import Page, View3D

page = Page(width_mm=89)
page.row([View3D.chip("device.gds", "gdsfactory_generic", cell="DEVICE", z_scale=4.0)])
page.export("device_vector", formats=("svg",))
```

## 5. Cut a cross-section

Look at an imported GDS in the Layout view or with `layout_html`; draw cuts with
its ruler (M, then two clicks; Cut along ruler in the editor).

```python
import matplotlib

matplotlib.use("Agg")                  # draw to files only: no window, no screen backend

from optodraw.gds import GDSSection, plot_gds_cross_section

cut = GDSSection(label="A-A'", x=30.0, window=2.0, mode="section")   # across the bus and both ring walls
ax = plot_gds_cross_section(layout, cut, z_exaggeration=28.0)
ax.figure.savefig("xsection.png", dpi=150, bbox_inches="tight")
```

A cut runs along y at one x: put x through the middle of the device (a ring's
centre crosses the bus and both ring walls), and cut again through the metal
if it lies elsewhere. `mode="section"` shows only what the line crosses;
`mode="projection"` (the default) shows everything within `window` of it.
This plot is a check of layer order and heights. It draws an etch as an
outlined box, not as a hole; it does not draw the buried oxide, the cladding
or the handle; and it carries a title inside the axes: it is not a paper
figure. A heater or a metal beside the device needs its own cut through it.

For a paper figure, use `cross_section`. It cuts the layout along any straight
line and runs the process the stack implies along it: the device etches (each
takes all but the thicker layers down to the next level), the implants through
the silicon, germanium grown on silicon, each via etched through the oxide with
its layer's wall and filled, each film (SiN, a heater, a metal) deposited and
patterned to its drawn shape, the top oxide with an oxide passivation as its
last level, and the pads etched open on the pad-opening layer. A wall slopes as
the stack says.

```python
from pathlib import Path

from optodraw.gds import GDSLayerRecord, GDSLayout, cross_section


def rect(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def layer(spec, *shapes):
    return GDSLayerRecord(spec=spec, name="", description="", color="#000000", opacity=1.0, thickness=0.22,
                          zmin=0.0, material_preset="silicon", polygons=list(shapes), matched_pdk=False)


rib = GDSLayout(source_path=Path("rib.gds"), cell_name="RIB", bounds=(-20, -5, 20, 5),
                layer_records=[layer((1, 0), rect(-20, -0.25, 20, 0.25)), layer((3, 0), rect(-20, -3, 20, 3))])
xs = cross_section(rib, "gdsfactory_generic", ((0, -5), (0, 5)))
assert xs.check() == [], xs.check()
xs.svg("rib_xs.svg")                       # labels, dimensions, scale bar
xs.steps_svg("rib_steps.svg")              # the process, one panel per step
xs.png("rib_sem.png")                      # an SEM-like image, marked as a render
xs.slab("rib_slab.glb", depth=6.0)         # the cut 3D slab; .png renders it headless, .html is interactive
```

Read every finding of `xs.check()`: a layer drawn on the cut that the stack
does not know, an implant on etched silicon, a via that lands on nothing. A
real GDS file takes the path: `cross_section("chip.gds", ...)`. The figure
keeps z true unless the thinnest layer would be under 2 pt tall; then it
stretches z by 2, 3, 5, 10, 20 or 50, prints "z × N" and adds a z scale bar.
`z_scale=1` forces true aspect. A process YAML in place of the stack name runs
its own steps (expert mode). `xs.png()` is a render, not a micrograph: it says
"optodraw render" on the image and "rendered, not measured" in its metadata;
never present it as a measured SEM image.

To show a full device, draw what the cut must cross: each via layer over the
contacts and each metal up to the pad metal (`VIAC`, `M1`, `VIA1`, `M2`, `VIA2`,
`M3` in the generic stack), the pad-opening layer inside the pads, and put the
cut through a row of contacts. A heater's contacts sit at its ends, so a cut
across its waveguide shows the heater alone; say so in the caption. A busy cut
(a germanium detector, a heated rib and a SiN guide side by side) tests the
stack far better than a single rib: build one before you trust a new stack.
In the generic stack the cladding ends at 3.0 um and M3 spans 3.2 to 5.2 um;
the oxide passivation fills round M3 and planarises 0.5 um over it, and PADOPEN
etches the pads open. When someone asks why M3 is so thick, answer with those
numbers: gdsfactory's stack and its KLayout script both give 2 um.

The slab's face is the cut itself; behind it the same process runs on parallel
cuts, so a via shows only where it is drawn. Toward the back the oxide and the
wiring above each step are cut away: first the lowest metal shows, then the
rib and its implants. Look at the slab before you use it: a tall pad in front
can still hide a step; pass a larger `depth`.

### The top view

`top_view` shows a region of the chip from above as an SEM-like image. The
same process runs on a cut along each pixel row and each pixel column, so the
heights, walls and films are the stack's, as in the cut.

```python
from optodraw.gds import top_view

wafer = top_view(rib, "gdsfactory_generic", (-3, -2, 3, 2), stage="device")
assert wafer.check() == [], wafer.check()
wafer.png("rib_top.png", tilt=40.0, rotation=-25.0, width_px=300)
```

- `stage`: "device" is the wafer before the first oxide (bright silicon on
  dark oxide, as published waveguide SEMs show it); "chip" is the finished
  chip; a step id from the process stops after that step. In a chip view a
  device under the oxide shows faintly, and metal and silicon hide what lies
  under them, so a device shows unless a pad covers it. That fade is a model
  (`see_through=2.5`, in um), not a beam range. A conformal film's outside
  corners come round, from the 3D film itself, not from the cuts.
- `tilt` leans the view toward its bottom edge, in degrees; `rotation` turns
  it so the image's horizontal runs along that layout direction. The image
  ends at the far edge of the region.
- Time: each different cut runs the process once. A view along the layout's
  edges reuses most cuts (seconds); turned to them, every cut differs: a chip
  view at 2000 px takes a minute or more. Try angles at `width_px=600`, then
  render the final image once.
- Pick the region round the device you want to show; a region of pads only
  shows pads. Like `xs.png()`, the image is a render: "optodraw render" on the
  image and "rendered, not measured" in its metadata.
- In the editor, the cross-section panel's Top look shows the square round the
  cut (its side the cut's length). A tilt, marks or noise change reuses the
  cuts and is instant; a rotation or a stage change cuts again.

## 6. Before you call it done

1. `check_stack` is empty, or you told the user each finding you kept.
2. You looked at the cut: layer order and heights match the stack.
3. You looked at the 3D view (a draft image or the HTML): nothing floats,
   nothing sinks into its neighbour, no layer sits at a made-up height.
   Without a browser, print what the model holds instead:
   `for record in layout.layer_records: print(record.name, record.zmin, record.thickness)`.
4. The geometry makes sense as a device: a heater over the waveguide it
   tunes, a via between layers that must connect, an etch window no larger
   than the device. `check_stack` cannot judge this; you can.
5. The cut agrees with the PDK's own cross-section, layer by layer: the same
   films, the same walls, the same passivation and openings.
6. The caption or the report names the stack and the z exaggeration.
7. No confidential stack value left the user's machine.
