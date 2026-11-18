---
name: optodraw-figure
description: Use when asked to draw a figure of an optical setup, a free-space bench, an interferometer, a fiber link or a photonic chip for a paper, a talk, a thesis or a website, or to reproduce a schematic from a published paper. Covers the plan (takeaway, light path, parts), the build with real parts and beams, aiming mirrors and splitters, turning detectors to their beams, the 1D symbol schematic, the 2D figure and the 3D render, the checks, a faithfulness review, and the export of paper figures at journal width with a caption.
---

# optodraw-figure

Optodraw draws optical figures from real parts: a lens is a `Lens` with a
focal length, a beam is a `Beam` that runs through the ports of the parts it
meets, and one scene gives the 1D symbol schematic, the 2D figure and the 3D
render. Your job is to put the right parts on the right light path and check
the result. A figure that looks polished and shows the wrong physics is worse
than no figure.

Every python block in this file runs in order, as one script, in the optodraw
test suite. Related skills: `optodraw-layout` (chip layouts), `optodraw-component`
(a part optodraw lacks), `optodraw-gds-3d` (a GDS file), `optodraw-animation`
(moving light).

## Your first message: the assumptions line

Before any code, state what you chose and why, in one line, for example:

`Assumptions: setup=free-space Mach-Zehnder, views=2D+1D, size=single column 89 mm, depth=standard, source=none (textbook layout)`

Repeat the line, updated, at the top of your final report.

## Depth

| depth | when | what you do |
|---|---|---|
| draft | a quick look | build, run the checks, look at the PNG |
| standard | the default | the plan, the build, the checks, the faithfulness review, a look at the 2D and the 1D view |
| full | a figure for a paper | standard, plus two arrangements and a choice between them, the written critique and the cold read |

## Compact, never to scale

A figure is read, not built. Draw the source's parts, order and wiring, but
not its lengths: a figure at true scale has long thin parts, empty space and
long wires. Keep the default part sizes (`render_physical` is for a to-scale
layout the user asks for), put parts as close as their drawn extents allow,
and make every beam, route and wire as short as the topology permits. State
in the caption what the figure does not draw to scale.

Space is the first thing a reviewer checks. After the first render, look for
empty bands in the 2D and in the 1D, and close each one: move a whole block
(an arm, a detection branch, a row of instruments) into the space beside it,
shorten long free-space runs, and put a shorter row beside a longer one, not
under it. Print the size before and after (`scene.content_bounds()` in the
scene's units, `build_schematic(scene).width`/`.height` in points for the 1D)
and compare it with the column it must fit: 89 mm (246 pt) single, 183 mm
(510 pt) double. Report both sizes. A setup a reviewer has to ask you to
tighten was not finished.

## 1. Plan before you build

Write `figure_plan.md` beside your script (the template is in
`reference/plan.md`). In a published test of a figure skill, removing this
step cost more quality than removing any check. The plan holds:

1. **Takeaway**: the one sentence a reader must take from the figure, and
   what the figure must not imply.
2. **Skeleton**: the form of the figure, named before any part is placed: one
   principle with its cases, a pipeline, a controlled comparison, a setup with
   its signal, or a zoom from system to part. Say why in one line.
3. **Light path**: one line per beam, part by part, with the port it enters
   and leaves, the wavelength and the polarization where they matter, and the
   source of each item.
4. **Parts**: the catalog class of each part and its label, exact text, 2 to
   4 words.
5. **Unknowns**: anything the source does not say. Ask the user; never draw
   a guess as a fact.

### Rules of a good figure

These rules come from 76 published figures and a blind test on 28 more (the
open `schematic-figure` skill, MIT). A rule is a reason, not a quota: where its
exception holds, do the other thing and say why in the report.

| rule | in optodraw | not when |
|---|---|---|
| The signal's state sits on the beam, so a reader can follow it from input to output | `Glyph.on(beam, "pulse", leg=2)` where the signal changes | the state is trivial, or is not what the figure is about |
| Draw the source's instance, not the textbook one: every count, polarity, direction, order, and shared or one each | the printed stop lists of step 6 | the source is silent: keep it vague, an ellipsis or "N", never a wrong number |
| Draw only what you know: a glyph reads as data | a shape from the source, or a textbook form that the caption calls illustrative | never: no invented value on a figure |
| An inset names its source: converging lines, never closeness alone | `Panel(detail, zoom=(bench, part))`; the link is grey, never the beam's colour | the panels are peers, or the inset shows another kind of object |
| Past about eight parts, name each group for its role, not its parts | `Bracket("Detection", first, last)` | one subsystem, or space already groups them; a wire across the group breaks it |
| 3D for the hero only, with a flat view that carries the labels and numbers | one object in `render_3d_image`, a flat panel beside it in the same orientation | the arrangement in space is the claim |
| Spend the colour on the light: grey parts, one strong hue, one colour for one role in every panel and label | `Scene(beam_style=...)` for the look of all light | colour codes a many-valued quantity, such as wavelength channels |
| Real evidence sits beside the drawing: a measured picture or plot next to the schematic, as an inset | `Inset(Image(path, scale_um_per_px=...))` or `Inset(Plot(fig, kind="measured"))` in a `page.row` | no measurement exists: never draw one |
| One panel has air round one idea, and it is where the eye starts | give it the largest `share` | a reference or methods figure |
| Compare on one template: same layout, scale and view, one change | copy the scene and change one part | the systems differ in kind |
| A repeat is two or three copies and dots | a `Note("...")` after the last copy | the count is the result |
| Feedback is one loop in its own style | one `DashedLink`; number steps only for a real sequence | a housekeeping path nobody needs |
| The key relation sits where it acts, in the drawing's symbols, once or twice | a `Note` beside the part | an overview or a teaser |
| Panel headings are noun phrases, and every mark touches what it names | "Readout chain", not a sentence; delete a line or an arrow that points at nothing | a cover image whose heading is the claim |

## 2. Find the parts

```python
from optodraw.catalog import describe_component, list_component_categories, list_components

print(list_component_categories())
print([name for name in list_components() if "Splitter" in name or "Mirror" in name])
print(describe_component("BeamSplitter")["description"])
```

Search by function words (`Splitter`, `Isolator`, `Detector`, `Fiber`), not
by one guessed class name. Parts that end a beam: `Photodiode`,
`AmplifiedPhotodetector`, `Camera`, `CMOSCamera`, `EMCCD`, `CameraSensor`,
`SNSPD`, `PhotonCounter`, `QuadrantPhotodiode`, `Spectrometer`, `PowerMeter` and
`BeamDump`. A broadband source (white light, a globar, an LED) is a `Lamp`. A
nonlinear crystal (BBO for a harmonic, PPKTP for photon pairs, a CaF2 plate for
white light) is a `NonlinearCrystal`, with `poled=True` for a poled chip; a
Wollaston prism is a `WollastonPrism` (`o` and `e` leave apart); a beam-position
detector (optical tweezers, pointing) is a `QuadrantPhotodiode`.
`VariableAttenuator` has fiber ports only; in free space use a `Filter` and
name it. If a part does not exist, build it with `optodraw-component` rather
than drawing a box; if you only replicate a figure, use the nearest part and
list the gap in the plan.
Print a part's ports before you wire it: `part.ports()` (local) or
`part.world_ports()` (after placing).

## 3. Build: a worked interferometer

```python
from optodraw import Beam, BeamSplitter, Laser, Mirror, Photodiode, Sample, Scene
from optodraw.layout import aim, face

scene = Scene(title="Mach-Zehnder interferometer", width=89, height=70, platform="free_space")
laser = scene.add(Laser(center=(-35, -22), wavelength=633, label="HeNe laser"))
bs1 = scene.add(BeamSplitter(center=(-14, -22), transmission=50, label="BS1", label_side="bottom"))
sample = scene.add(Sample(center=(2, -22), label="Sample"))
m2 = scene.add(Mirror(center=(18, -22), label="M2", label_side="bottom"))
m1 = scene.add(Mirror(center=(-14, 6), label="M1"))
bs2 = scene.add(BeamSplitter(center=(18, 6), transmission=50, label="BS2", label_side="top-right"))
pd1 = scene.add(Photodiode(center=(38, 6), label="PD1"))
pd2 = scene.add(Photodiode(center=(18, 24), label="PD2", label_side="right"))

aim(bs1, laser, m1)          # a splitter is aimed at the beam it REFLECTS
aim(m1, bs1, bs2)
aim(m2, bs1, bs2)
aim(bs2, m2, pd1)
face(pd1, bs2)               # every detector looks at its beam
face(pd2, bs2)
scene.add(Beam.through(laser, bs1, sample, m2, bs2, pd1, wavelength=633))
scene.add(Beam.through((bs1, "refl"), m1, bs2, pd2, wavelength=633))
scene.fit_frame(margin=6)
scene.render_svg("mzi.svg")
```

- `Beam.through(*parts)` attaches the beam at the ports that face the next
  stop. A stop can be `(part, "port")` to name the port.
- The source's `wavelength` is the physics; a beam's `wavelength` only sets
  its colour. Give both the same value.
- `aim(part, source, target)` turns a mirror or a plate splitter so light
  from `source` reflects to `target`. For a splitter, `target` is where the
  REFLECTED beam goes; the transmitted beam needs no aim. Never aim a cube
  splitter: it stays square.
- Every splitter has four faces: `in`, `trans`, `refl`, `tap`. Where light
  goes from each face:

  | light arrives at | passes to | reflects to |
  |---|---|---|
  | `in` | `trans` | `refl` |
  | `refl` | `tap` | `in` |
  | `trans` | `in` | `tap` |
  | `tap` | `refl` | `trans` |

  A plate `BeamSplitter` (or a dichroic) is aimed. A cube
  (`NonPolarizingBeamSplitter`, `PBS`) stays square: at
  `angle=0`, `in` faces left, `trans` right, `refl` up and `tap` down, and
  `angle` turns the whole set. Two beams recombine in a cube when one enters
  `in` and the other `tap`.
- A part the light meets twice (the splitter of a Michelson) is named twice:
  `Beam.through(source, (bs, "in"), (bs, "trans"), mirror, (bs, "trans"), (bs, "tap"), detector)`.
  A second plate parallel to the first (a compensator) takes the first one's
  angle: `BeamSplitter(..., angle=bs.transform.rotation_deg.z)`.
- A `Lens` or a `Filter` at `angle=0` stands across a horizontal beam, with
  `in` on the left; `angle=90` stands across a vertical beam with `in` at the
  bottom, `angle=-90` with `in` at the top (a beam that runs down).
- `face(part, source)` turns a detector, a camera or a fiber port so its
  input looks at its beam. A detector lit from behind is a physics error;
  `run_checks` reports it.
- **Interferometers are symmetric.** Equal arms, the parts of the two arms at
  matching positions, beams straight between them: a horizontal run shares
  one y, a vertical run one x. `aim` puts each mirror's face and each plate's
  centre on the point you give, so parts on one line give a straight beam;
  `run_checks` reports a beam that leans.
- The plate's ratio is `transmission` (percent); a plate splitter does not
  split by polarization. State the ratio in the caption.
- `scene.fit_frame()` sizes the frame symmetrically about the origin: build
  around `(0, 0)`. Sketch the layout, then shift every centre by minus the
  middle of its bounding box, or half the figure stays empty.
- `label_side` (`"top"`, `"bottom"`, `"left"`, `"right"`, or a corner such as
  `"top-left"`) keeps a label off the beams: put it on the side no beam
  leaves from. A corner sits past both edges of the part, so it lands farther
  away; use it only where every side carries a beam.
- A lens focuses: put the detector's input port (not its centre) at the focal
  plane, or draw the cone with `FocusingBeam(start, end, width1=..., width2=0.0)`.
  A constant-width beam past a lens says the lens does nothing; `check_figure`
  reports a detector off the focus of the lens before it.
- Every beam ends on a detector, a beam dump, a sample, or a part that sends
  the light on in another beam. `check_figure` reports a beam that stops in a
  splitter or a lens, or that leaves its last part into nothing.
- **Every part drawn has its light ports in use.** Leave out a part no light
  reaches (the virtual image a paper draws dashed); a single detector at a
  focal plane is a `Photodiode`, not a camera, whose wire stub would sit in
  line with the beam and read as light passing through it.
- **A cryostat holds the sample, not the optics.** The objective stays
  outside and focuses through the window; inside sit only the sample or
  chip, its contacts, thermometers and positioners. When a separate label for
  the part inside would sit on the cryostat's wall, give the container one
  label that names both ("Sample in cryostat").
- **A sample faces its light.** There is one `Sample`: its face looks toward
  `in`, and `angle` turns it. Give an objective above it on the page
  `angle=-90`; a 3D bench then stands the chip face on to the objective.
  `run_checks` names a sample that the beam passes at the side.
- **A fibre is a route, a cable goes round the outside.** Join a fibre port to
  a detector with `scene.route(a, b, kind="fiber", path_type="manhattan")`:
  it bends once in both views, where a `Beam` from a port's top to a side
  input draws a slant in 1D. A cable that must not cross the beams (a laser's
  sync to a counter) takes `steps` round the outside; the 1D follows them.
- A part on a stage sets its mount: `part.base_mount = "stage"` (translation),
  `"xyz_stage"` or `"rotation_stage"`. The 2D and 1D views show a small motion
  arrow beside the part and the 3D view draws the stage under it, as it draws posts.
  Do not add `TranslationStage` parts to a figure: a stage drawn in 2D crowds
  the part it carries.
- **Two beams on one path nest on the axis by themselves.** In 2D and TikZ the
  lower beam, the one with the longer wavelength, draws wide enough to show
  round the next; a beam already wide enough keeps its `width`.
  `Scene(beam_style=BeamStyle(opacity=0.7))` sets the look of all the light. Use
  a lane only when beams must read apart: give one `offset=` (a little over the
  mean of their drawn widths) so both show side by side, on a `FocusingBeam`
  too. A mirror swaps a lane's side, as it does for real light. Lower
  `opacity=` only to see one beam through another.
- **Text that is not a part name is a `Note`.** Use
  `scene.add(Note.on(beam, "880 mW", leg=3))` after the parts are in place, or
  `Note("key", center=(x, y))`. `leg` counts the straight spans the beam draws,
  and `check_figure` treats a note as a label. Any label or note takes `f_p`,
  `T_{ij}`, `cm^2`, `*k*` and `**bold**`.
- `Callout("Focus", center=(20, 18), target=lens)` names a place with a line and
  a dot; `Bracket("Telescope", lens1, lens2)` names a span; `DashedLink(a, b,
  text="trigger")` ties two places that no light joins. Make them last: each end
  is worked out when the mark is made. A bracket's `clear` runs from the edge of
  each part it spans.
- `Glyph.on(beam, "pulse", leg=2)` draws the state of the signal beside a leg:
  `pulse`, `train`, `spectrum`, `wave` or `spot`, in the beam's colour.
- An ND filter or wheel is `NDFilter(optical_density=...)`, not a `Filter`. Put
  a sample on `objective.focus_point()`.
- **A flip mirror is a `FlipMirror`, not a `Mirror`.** `state="up"` folds at
  `io`, `"down"` runs straight through `pass`, and `"both"` is a figure of the
  two routes. Give each beam the port of its route, so the checks can read it.
  A negative `out_offset` puts the dashed outline on the other side.
- **Let the lenses set the width.** Use `scene.lens_beam(laser, l1, l2, dump,
  width=1, mm_per_unit=6.25)` after the parts are in place, not a width and a
  focus by hand. `width` is the display scale. On a drawing that is not to
  scale, `mm_per_unit` is focal length over drawn length: its warning gives the
  value for a telescope.
- **Cavities, locks and delays.** `ModeCleaner` is a triangular ring cavity: the
  light it passes leaves on its input line (`out`), and `refl`, the lock beam,
  leaves along `mc.refl_direction()`. `Mirror(piezo="stack")` or `"3axis"` puts
  a mirror on piezo actuators with a `pzt` drive port. `FaradayRotator` turns the
  polarization the same way in both directions; with a `PBS` beside it, a
  returning beam leaves by the side. `RoofMirror` sends the beam back beside
  itself (`in` and `out` side by side) and rides a stage: a delay line. Aim the
  next mirror from `roof.world_port("out")`, not from the roof's centre.
  `BalancedDetector` takes two beams on one face, `in1` and `in2`.

**Marks on a chip or a board.** A mark takes a named place on a part as its
target: `ring.anchor("gap")`, and `part.anchors()` lists the names. `Note.on`
and `Glyph.on` take a route as they take a beam: `route.legs()` gives its
straight spans. `SectionMark(a, b, name="A")` draws where a section is cut.
`Region(parts, label=...)` draws a dashed box round a group, with its name,
from each part's `drawn_box()`. A wire bond is a route kind:
`scene.route(a, b, kind="wirebond")`. Make each mark after its parts are in
place.

```python
from optodraw import Callout, ElectricalPad, MicroringResonator, Note, Region, Scene, SectionMark

chip = Scene(title="Ring and pads", platform="on_chip")
ring = chip.add(MicroringResonator(center=(0, 0), label="Ring", label_side="top"))
pads = [chip.add(ElectricalPad(center=(x, 40), width=12, height=12, port_side="center")) for x in (-25, 25)]
bond = chip.route((pads[0], "e1"), (pads[1], "e1"), kind="wirebond")
print(sorted(ring.anchors()))                                    # ['center', 'gap', 'ring']
x0, _, x1, _ = ring.drawn_box()
_, y = ring.anchor("ring")
chip.add(Callout("Gap", center=(30, -30), target=ring.anchor("gap")))
chip.add(Note.on(bond, "Wire bond", leg=len(bond.legs()) // 2, side="right"))   # under the arc
chip.add(SectionMark((x0 - 4, y), (x1 + 4, y), name="A"))      # the cut across the ring, A to A′
chip.add(Region(pads, label="Bond pads"))
chip.fit_frame(margin=6)
chip.render_svg("marks.svg")
```

## 4. The views

| view | call | output |
|---|---|---|
| 2D figure | `scene.render_svg("f.svg")` | SVG |
| 2D for LaTeX | `scene.render_tikz("f.tex")` | TikZ |
| 1D symbol schematic | `scene.render_svg("f.svg", view="1d")` (or `render_tikz(..., view="1d")`) | SVG or TikZ |
| interactive 3D | `scene.render_threejs("f.html")` | HTML |
| notebook viewer | `scene.preview()` | 2D and 3D tabs |
| 3D image | `scene.render_3d_image("f.png")` | PNG, needs Chrome |
| 3D as vector | `scene.render_3d_svg("f.svg")` | SVG, no Chrome |

```python
import cairosvg

scene.render_svg("mzi_1d.svg", view="1d")
scene.render_tikz("mzi.tex")
for name in ("mzi", "mzi_1d"):                       # look at every view as a picture
    cairosvg.svg2png(url=f"{name}.svg", write_to=f"{name}.png", output_width=1200)
```

The 1D view places its symbols itself. Look at it on its own: every beam that
runs straight in 2D must run straight in 1D, and every arm must reach the part
it reaches in 2D. A part with no 1D symbol of its own shows the nearest
prebuilt variant or a labeled block. A chip's 1D is its 2D plan, closed up:
the same arrangement, each part as its symbol, each waveguide and cable routed
square along its 2D route, and a part lined up with the port that feeds it
where the two ports line up in 2D. So a fault in a chip's 1D is a fault in its
2D: fix the 2D (a chip whose parts overlap in 2D falls back to the automatic
1D). On a bench with many branches, if the
1D crosses beams or scatters parts, make it follow the 2D positions:
`scene.set_view_layout({"1d": {"spacing": 1}})` (a number; `"auto"` fails on
parts that touch). The 1D then keeps each label on the side its `label_side`
gives in 2D, and each cable on its 2D path. A beam runs on through a part the
light crosses on one straight line (an iris, a plate), so a gap in a 1D beam is
a fault to report, not a style. The 1D view draws a `Region` box, a `Bracket`
and a stage's motion arrow round the symbols of their parts; a note, a callout,
a link and a glyph stay in 2D. `set_view_layout` places a bench joined only by
fibres too.

```python
# not run: needs Chrome, Chromium or Edge (OPTODRAW_CHROME names one)
scene.render_3d_image("mzi_3d_look.png", background="light", engine="viewer", scale=1.0)   # a look: seconds
scene.render_3d_image("mzi_3d.png", background="none", camera="isometric")                # final: minutes
```

Look at the 3D view with `engine="viewer"` while you work. The default studio
engine traces light on the CPU: one final image can take many minutes, so make
it once, at the end.

## 5. Check

```python
from optodraw import check_export, check_figure
from optodraw.app.validation import run_checks

for issue in run_checks(scene):
    print(issue["level"], issue["kind"], issue["message"])
print(check_figure(scene, preset="single_column"))
print(scene.validate_physics("ray"))
print(check_export(scene.export_figure("fig", width_mm=89, formats=("svg",))["svg"]))   # the file, at its print size

from optodraw.symbols.schematic import build_schematic

x0, y0, x1, y1 = scene.content_bounds()
one_d = build_schematic(scene)
print(f"2D {x1 - x0:.0f} x {y1 - y0:.0f} mm, 1D {one_d.width:.0f} x {one_d.height:.0f} pt")   # against the column
```

`run_checks` finds the physics faults: a beam that enters a part from behind,
leaves it backwards or leans off a straight run, a detector that no beam
reaches, parts outside the frame, a dichroic with no edge, a part without an
exact 1D symbol, and electrical and coupler faults. `check_figure` finds the
figure faults, in 2D and in 1D: labels that overlap, sit on a beam or another
part, float far from their part, run off the frame, read like a sentence, or
print too small at the preset's width; a beam that stops short, a detector
off focus and a beam hidden by another; on a chip, ports nothing connects, routes that cross and a route
drawn across a part it does not join; in 1D, a beam or a link drawn across a
part it does not join, and a route that crosses more links than its 2D route
does. `check_export` reads the finished SVG: text in points on paper, one
font, overlaps, text on the art, words per square centimetre and hairlines. A label may sit on a part that holds its part (a
sample inside a cryostat). Two empty lists are necessary, not sufficient: they
cannot tell that the sample sits in the wrong arm, that the objective is inside
the cryostat, or that half the figure is empty. That is what the review is for.

## 6. Review: faithfulness first

Agents score their own figures too high. Write each problem into the plan
file before you fix anything.

```python
for beam in (node for node in scene.walk() if isinstance(node, Beam)):
    print(" -> ".join(f"{part.label}:{port}" for part, port in beam.anchors))
```

1. **Faithful**: compare each printed stop list with the light path in the
   plan: every count, polarity, order, direction and arm, and whether a part or
   a beam is shared or one each. On a plate splitter the entry
   and the reflected beam share the front face, so the stops can read
   `BS1:refl -> BS1:tap` for light that passes straight through. A textbook version where the
   source differs is an error, not a simplification.
2. **Physics**: each splitter sends the right arm to the right place; every
   detector faces its beam and gets light; focal planes, wavelengths and
   polarization optics match the source.
3. **Layout**: no part overlaps another; no route crosses; interferometer arms
   are symmetric; no empty band is left, in 2D or in 1D, and rows of the same
   parts sit evenly apart; every part's light ports are in use and every beam
   is drawn through the parts it crosses.
4. **Labels**: each label names its part in 2 to 4 words and sits next to it;
   no label sits on a beam or another label, in 2D or in 1D; no sentence on
   the figure. List every label over four words and every mark that points at
   nothing, then shorten it, move it to the caption, or delete it.
5. **Cold read**: look at the PNG at its final size, write down what it
   claims, then compare with the takeaway.

Fix, render, look again. `reference/plan.md` holds the scoring rubric for a
full-depth review.

What a reviewer said, and what it was:

| reviewer | fault |
|---|---|
| "this whole space has to go" | an empty band: move a block into it, shorten the runs round it |
| "the 1D is compact but the 2D isn't" | long free-space runs in 2D that the 1D drops |
| "ports are not being used" | a part with no light (a virtual image), or a wire stub in line with the beam |
| "should connect better" | a gap in a beam at a part it passes through, or a part turned off the beam line |
| "the objective cannot go in the cryo" | optics drawn inside a cryostat |
| "this will not fit in a paper" | a figure wider than its column: put each row's parts on one line, close the gaps |

## 7. Export for a paper

`scene.export_figure("mzi", width_mm=89, font_size_pt=7)` writes `mzi.svg`,
`mzi.pdf` and `mzi.png` (800 dpi) framed on the content and the labels. Use it
for one figure. Use the calls below for a preset or a bundle.

`export_panels("fig", [[Panel(bench, share=0.72), section]], width_mm=183)`
writes one figure of lettered panels from scenes, cross-sections and SVG files.
A panel with no `share` splits what the row leaves. For a chip panel, a beam
goes on a section from the stack: `section = stack_section(stack, (1, 0))`,
then `section.beam(wavelength=450, label="450 nm")`. `Panel(section, zoom=(bench,
chip))` links a panel to the place it shows on another. Run `check_export` on
the file: `check_figure` measures labels at 8 pt, the file at their true size.

```python
from optodraw.publication import build_publication_bundle, list_paper_figure_presets

print(list_paper_figure_presets())
paths = scene.export_paper_figures("paper", preset="single_column", formats=("svg",))
cairosvg.svg2pdf(url=str(paths["svg"]), write_to="paper/mzi.pdf")           # vector PDF, live text
bundle = build_publication_bundle(scene, "bundle", template="single_figure", formats=("svg",),
                                  caption="Mach-Zehnder interferometer with the sample in the lower arm.")
print(bundle.caption_path)
```

| preset | width x height (mm) | text |
|---|---|---|
| `single_column` | 89 x 70 | 8 pt |
| `nature_single` | 89 x 60 | 7 pt |
| `double_column` | 183 x 120 | 8 pt |
| `full_width` | 183 x 140 | 9 pt |
| `ieee_double` | 178 x 110 | 8 pt |
| `presentation` | 240 x 135 | 12 pt |

- Free-space scene units are millimetres on the page: build the setup to fit
  the preset (`single_column`: within 89 x 70). The export warns when the
  frame clips the content.
- A chip scene is in micrometres: pass `fit="width"` to `export_paper_figures`.
  The SVG then spans the preset's width in millimetres, framed on the content
  and its labels, with the labels at the preset's point size on the page.
- Put the takeaway and the source in the caption (`caption=`);
  `scene.metadata` does not reach the figure.
- Templates with several panels (`two_panel_horizontal`, `four_panel_grid`,
  `device_plus_xsection`) write one file per panel, and the bundle also writes
  one lettered `<stem>_figure.svg` of all panels, named under `"figure"` in the
  manifest.
- `export_paper_figures(..., include_polarization=True)` draws the
  polarization state on the beams.

Optodraw draws optics, chips and instruments. Make plots with matplotlib and
put them on the page through the inset call (next section). Draw band diagrams
and molecules with matplotlib or TikZ, in the same font, at the same width.

## A page of insets

A `Page` is a scene in mm that prints at its exact size. An `Inset` holds one
item: a scene (2D or 1D), a section, a matplotlib figure, a picture, an SVG or
PDF file, text or an equation. `page.row` sets the items at one height and
`page` letters them a, b, c. A picture stays pixels in a vector frame, and a plot
keeps its text as text. Give a plot a figure size and font that print near the
slot width, because a plot keeps its own text sizes.

```python
import matplotlib.pyplot as plt
import numpy as np
from optodraw import Callout, Image, Inset, Laser, Lens, Page, Plot, Scene

bench = Scene(width=100, height=60)
bench.add(Laser(center=(10, 0)))
bench.add(Lens(center=(40, 0)))
fig, ax = plt.subplots(figsize=(1.8, 1.4), layout="constrained")
ax.plot([0, 1, 2, 3], [0, 1, 4, 9])
page = Page(width_mm=120)
scene_inset, plot_inset, photo = page.row([bench, Plot(fig), Image(np.ones((8, 8)) * 0.5, kind="drawn")])
page.add(Callout("Lens", center=scene_inset.at(40, 12), target=scene_inset.at(40, 0)))
page.export("page", formats=("svg",))
```

`inset.at(x, y)` gives a place in the units of the item, and a callout that uses
it moves with the inset. Set `kind="measured"` only for real data and a real
photo. A render or a sketch says `"render"` or `"drawn"`. Then run
`check_export("page.svg")`. Here it reports the stand-in picture as a drawn
raster at low ppi, as it should for a stand-in.

A timing panel is a `Timing` inset, never a hand-made plot: rows of `Clock`,
`Bits`, `Bus` and `Trace` (the author's samples), with `TimeMark` lines. Mark a
time on a row with `inset.at(t, timing.row("DAC"))`. Timing values that are not
measured take `illustrative=True`. An eye diagram is `eye_diagram(samples,
samples_per_ui)` from `optodraw.plots`, set in an inset as any plot.

A circuit panel (a TIA, a bias network) is circuit parts (`Resistor`,
`Capacitor`, `OpAmp`, `Ground`, ...) joined by `kind="electrical"` routes, set
in the page as `SceneView(circuit, view="1d")`: each part is its IEC symbol.
The 1D view keeps the 2D plan, each symbol where its part stands, while no two
parts overlap in 2D: always on a `platform="on_chip"` scene, and on any other
platform when its own arrangement would cross wires. Wires turn square, and the
1D view moves a part up to 25 points so each wire runs straight or turns once:
place connected ports near one line in 2D and the 1D finishes the job. A dot
marks each join of a node; wires that only cross have none. An
input grating coupler faces its route (`angle=180` when it sits left of it);
`check_figure` names one that faces away. An `OpAmp` has the supply
pins `v_pos` (top) and `v_neg` (bottom); they may stay unwired. On
`OnChipPhotodetector`, `e1` is the lead at the bar (the cathode) and `e2` the
anode. On the bench `Photodiode`, `e1` is the anode (the bottom lead in 1D)
and `e2` the cathode (the top lead); in 2D both leave at its connector. A
chip on its board is a 2D scene: `PCB(style="plain")`, a `ChipSubstrate` over
it, die pads joined to board pads by wire bonds, a `FiberArray` at the die's
edge and an `SMAConnector` at the board's edge.

A chip crop is a `GdsView(gds, stack, region)` inset, never a screenshot or a
hand-drawn copy: each layer clipped to `region` (file um) and merged into one
vector path in the stack's colours, an etch white with an outline. More
polygons than `limit` raise an error: take a smaller region or fewer `layers`.
`inset.cut(a, b, z=(z0, z1))` on it makes the section along that line, from the
same file and stack, as a new inset; `page.row` or `page.add` adds its
`CutLink`, which marks A and A′ on both insets and follows either one.

A 3D panel is a `View3D` inset, never a PNG: `View3D(scene)` or
`View3D.chip(gds, stack, region=...)` draws the viewer's own solids as vector
paths, in studio light, `projection="perspective"` or `"parallel"`.
`inset.at(x, y, z)` marks a true 3D point: scene units with z above the table,
or file um and true z on a chip. `check_figure` reports a target that a solid
hides. `chip3d.show_cut(section)` returns the dashed A-A′ of the section's cut
on the 3D chip; add it to the page. Give the height scale (`z_scale`, 4 by
default) in the caption.

## 8. Report

Start with the assumptions line. Then the takeaway, the files, the size of
each view against its column, the checks you ran and the ones you could not
run (for example no Chrome for the 3D image), and every finding you left open,
with the reason. Give the figures as files the user can open, at their final
size; a path in a temporary folder of yours is not a figure handed over. Agent tools over MCP are
in `reference/mcp.md`.
