# Changelog

All notable changes to Optodraw are documented here.

## [0.10.1] (2026-11-18)

### Added

- `scene.leave_open(part, "e1", "e2")` names the ports a figure leaves open as its paper does: a heater with no
  wires, the far end of a bus. The scene saves the list, and `check_figure` passes those ports.
- A `SignalArrow` at a chip port marks the light going in or out there, so `check_figure` counts the port as used.
- A docs example: the universal nine-mode interferometer of Clements et al. (2016), Fig. 1b, 36 MZIs in the
  rectangular mesh. Its 3D image is in the README.
- The site has its favicon (the app icon) and an Apple touch icon.

### Changed

- The test suite is cut from 8,243 tests to about 1,800. A coverage run with one context per test chose the
  smallest set that still runs every line the whole suite ran; the per-part families are one sweep each.
- The open-port message names the end for each kind of port: a coupler or a Terminator for light, a pad for a
  contact.
- `pip install optodraw` brings the editor, GDS files, 3D, every export, the MCP server and the notebook widgets.
  The old extra names still install. Only `desktop`, `manim` and `sax` stay optional: each needs system libraries
  or brings a large stack.
- PNG and GIF go through resvg, a wheel with no system library, so they work on Windows and on a Mac without
  cairo. PDF uses cairosvg where the cairo library loads, else Chrome or Edge, with the text kept as text.
  `optodraw.raster` has `svg_to_png` and `svg_to_pdf`.
- The 2D SVG names its font (Helvetica, Arial, sans-serif), as the 1D view does. A browser drew its labels serif.
- CI runs the tests on every core, the slow tests (6 % of the tests, 90 % of the time) on one leg only, installs a
  plain `pip install` on Linux, macOS and Windows, and no longer runs twice for a release tag.
- The README on PyPI links its images and files at the release tag, so the page shows that release.

### Fixed

- The editor loads on Windows. The 3D image module imported a Unix-only module as it loaded.
- Edge in `C:\Program Files` is found on 64-bit Windows.
- On Windows the editor starts on a free port. Its port probe could take a port that another server held.
- A Windows checkout no longer marks the symbol library as out of date: its hash reads Windows line ends as LF.
- Cross-section labels sit in the same place on every shapely release. Shapely 2.2 moved the label of a long flat
  layer to one end.
- The README images show the current part drawings. The quick start showed a gap in the beam at the small lens;
  the code draws none.
- The docs site build installs what its examples use.
- `check_figure` no longer counts a `SignalArrow`'s own ends as unwired ports: an arrow is a mark.
- The homodyne example wires its TIA output to a pad, where it ended in nothing.

### Removed

- The Optiland bridge (`LensPrescription`, `OpticalSurface`, `build_optic`, `optic_to_beams`,
  `optiland_available`, `trace_lens_beams`) and the `optiland` extra. No example or figure used it.

## [0.10.0] (2026-11-18, the first public release)

- A `Page` is a scene in mm that prints at its exact size. It letters the panels a, b, c in reading order.
  `page.row(items, top=None)` sets items side by side, and a row with `top=None` stacks under the last row.
  `page.zoom(small, region, big)` joins a closer view to its place, and `Page.from_template` lays out a template.
- An `Inset` is one movable 2D component that holds any item. The sources are `SceneView` (2D or 1D), `SectionView`,
  `Plot` (a matplotlib figure at its slot, with its text kept as text), `Image` (PNG, JPEG, TIFF or an array, such as a
  real SEM photo; `scale_um_per_px` gives the scale, and the scale bar is vector), `SemView` (optodraw's SEM-style
  render, marked as a render), `SvgFile`, `PdfFile` (through `pdftocairo`), `Text` and `Equation` (mathtext, or TeX
  through `dvisvgm`). A missing outside tool gives an error that names it.
- `inset.at(...)` gives a live place in the source's own units. `Callout`, `Note`, `DashedLink` and `Bracket` keep it
  and move with the inset. In the editor, dragging an inset brings its marks, and its width shows as a property.
- `ZoomLink` draws the box on one inset and the two grey lines to another, with a matching dashed grey frame on the big
  inset. It reads the live places of both insets.
- A saved page keeps each inset's source record and its last drawing inline in the JSON, so it opens and exports with
  the source files gone. A loaded inset never rebuilds by itself: `rebuild()` does. A saved page over 16 MB warns.
- `check_export` measures the label size per panel. The floor is the smaller of 1.65 % of the panel width and 8 pt, so
  the ceiling wins on a full-width panel. `figure_rasters` names each raster with its kind and resolution, and a raster
  in a drawn inset is a finding. `check_figure` reports overlapping insets (unless `over=`), covered targets, marks
  outside their inset and marks whose inset is gone.
- A new optional extra `figure` (shapely, matplotlib, pillow, cairosvg) is part of `all`.
- `Timing` draws a timing diagram as vector inside an inset: `Clock`, `Bits`, `Bus` and `Trace` rows, and dashed
  `TimeMark` lines. `inset.at(t, timing.row("DAC"))` places a mark on a time and a row. `illustrative=True` says so in
  the notes. `optodraw.plots` has `house_figure` and `eye_diagram`: plain matplotlib figures in the house style, for an
  inset. Neither makes up data.
- Sections work for any core and any stack. A stack may give `substrate`, `films` (blanket films, bottom up) and
  `fill` in place of the `oxide:` block, and `role: core` names the core at any height and in any material, so a
  LiNbO₃ ridge on its slab and an InP guide with no oxide cut as the stack says. Each entry may carry `source` and
  `provenance`. `cross_section(..., z=(z0, z1))` draws one band of the height. One material table gives every section
  its fill and label, and a stack's `materials:` adds or overrides one; a material the table lacks draws grey with a
  finding. Section text takes markup, so SiO₂ sets its subscript; the old stacks give the same sections apart from
  that label. Four new stacks: `lnoi400` and `ltoi300` from Luxtelligence's open PDK (MIT, its notice kept), and the
  literature stacks `inp_generic` (InP generic integration) and `bto_generic` (BaTiO₃ on silicon), each number with
  its source. `GdsView(gds, stack, region)` draws a GDS crop in an inset as vector: one path per layer, clipped and
  merged, in the table's colours, an etch white with an outline; more polygons than `limit` in the region raise an
  error. `inset.cut(a, b)` makes the section along that line as a new inset, and its `CutLink` marks A and A′ on both
  insets and follows either one when it moves. Both save as data.
- A 3D view can be vector. `scene.render_3d_svg("f.svg")` and the inset source `View3D(scene)` draw the viewer's own
  solids (boxes, prisms, cylinders, lathes, tori, tubes, text decals and hole grids, with the mounts, beams and the chip
  base) with their hidden parts cut away, in perspective or parallel, in studio light with soft shadows;
  `style="line"` gives flat figure colours. No Chrome is needed. `View3D.chip(gds, stack, region=...)` draws a GDS
  file on its stack's own wafer, heights `z_scale` times true. `inset.at(x, y, z)` places a mark on a true 3D point
  (file um and true z on a chip), and `check_figure` reports a target that a solid hides. `inset.show_cut(section)`
  draws A and A′ of a section's cut on a 3D chip inset. A view over `face_limit` front faces, or an external model
  file, raises `Vector3DError`, which names the way out. A test draws each of the 169 catalog parts with solids in both
  projections, vector and in the viewer, and compares them solid by solid. `View3D` saves as data.
- `export_panels` and `Panel` now run on `Page`: there is one page system. `Panel` takes `view` (`"2d"` or `"1d"`).
  A panel with `letter=""` takes no letter slot, so the others read a, b. They read a, c before. Rows with shares line
  up at the top; they sat centred before. The zoom region of a section panel is in um along the cut and z; it was in
  drawing units, which changed with the width. The zoom link draws the zoom panel's frame, dashed grey to match the
  box. `drop_text` on a scene panel now raises an error; it was ignored. The publication bundle also writes
  `<stem>_figure.svg` when a template has more than one panel, and the manifest names it under `"figure"`. Every page
  root names one font family: Helvetica, Arial, sans-serif.
- `FlipMirror`, `Glyph`, `Grid` and `ZoomLink` kept no label through a scene save. They keep it now.
- The editor has a Code tab beside the Inspector and the Outline: the scene as YAML text, read with the safe YAML loader
  only. A canvas edit changes the text, and Ctrl+Enter (Cmd+Enter) applies a text edit as one undo step. An error
  names its line. The text leaves out each inset's source and drawing, and the rays that Trace draws.
- In the editor, a double-click on a scene inset opens its scene. Every view and the Inspector work on its parts, and
  autosave keeps the whole page. Back draws the inset again from the changed scene. Save writes the whole page.
- The editor makes insets. The Figure group of the palette adds Text, Equation (mathtext), Picture, SVG file, PDF
  file, Scene inset, Copy of this scene, Timing and GDS view; Section and 3D view come from a selected GDS view. A
  picked file goes to the workspace's `files/` folder. A new inset lands in the middle of the view and builds once.
  The Inspector edits its source and has Rebuild; a corner handle resizes it, and it builds again at the new width,
  in one undo step. A large drawing goes to the browser once, by its key. A page over 16 MB names its size when it
  opens. The Code tab can write a Text, Equation, EmptyBox, Timing or SceneView inset; it refuses the other kinds at
  their line. A plot stays in Python.
- Circuit parts: `Resistor`, `Capacitor`, `Inductor`, `OpAmp`, `Ground`, `BiasTee` and `RFMixer`. Each is its IEC
  60617 line symbol in 1D and 2D, with an electrical port at the end of each lead, and a small package in 3D: a chip
  resistor, capacitor or inductor, an SOIC-8 op amp, a bias tee or a mixer with an SMA jack at each port. A ground has
  no solid. `value="10 kΩ"` prints after the label: `R_f = 10 kΩ`. The ports, the 2D lines and the TikZ pic read one
  plan, the class constants `PORTS`, `LINES` and `BODY`.
- Package parts. `scene.route(a, b, kind="wirebond")` draws a gold wire bond from pad to pad: an arc in 2D, a looped
  wire from pad top to pad top in 3D, an electrical link in 1D and in the checks. A save keeps it as a wire bond.
  `FiberArray` is a V-groove block with `count` fibres at a `pitch`, its ports `o1` to `oN` on the polished face.
  `SMAConnector` is an edge-launch SMA jack with its pin on the board top. `PCB(style="plain")` draws the outline in
  its own `color` and the edge pads only, in every view.
- Wires meet parts. `check_figure` reports a wire that ends more than 0.5 scene units from the drawn port, and a route
  that runs over a part, on every platform. The electrical ports of `MEMSActuator`, `RFDriver`, `DAC`, `ADCBlock` and
  `DAQ` now sit on their art. `Laser`, `Photodiode`, `Sample` and `Cryostat` have an electrical port `e1`, and
  `FPGABoard` has `io3` to `io10`. A beam enters and leaves a part by its light ports only, never by an electrical
  port. A die on a board draws over the board in any order; it went under the board before.
- `Route.legs()` gives the straight legs of a route, so `Note.on` and `Glyph.on` take a route as they take a beam.
  `part.anchor(name)` gives a named place on a part (a ring's coupling gap, a grating's teeth, a modulator's arm), and
  `part.anchors()` lists them; a mark takes one as its target. `part.drawn_box()` is the world box of the part's 2D
  drawing. `SectionMark(start, end, name="A")` draws a cut line with A and A′ on a 2D scene, and
  `Region(parts, label=...)` draws a dashed rounded box round a group, with its name.
- In 34 parts, two solids of different colours lay on one plane, and the 3D viewer flickered
  between them. The smaller or inner solid now stands about 1 % of its thickness off the shared face, and a bore is
  1.5 % larger. The 2D drawings did not change. On-chip parts keep each layer on its stack level; there, where two
  layers meet on one plane, one is cut out of the other in plan (a doped region out of its silicon, the silicon out of
  a laser mesa, a heater out of its metal), so each patch of the plane has one owner. This fixes 20 on-chip parts and
  AWG, EchelleGrating and the Cryostat's window tube. `shapely` is now a core dependency for that cut. Along the way:
  a doped strip fills the silicon it lies in to the top, the germanium of a photodetector stands on the waveguide top
  as the stack puts it, no via is drawn where the stack has none (zero-height vias drew as copper posts one unit
  tall), and a flip-chip die stands on its tabs.
- Fixed: the `Cryostat` in 3D had its wide window on the side, at 90 degrees to the chip's face, so a beam through it
  met the chip edge on. The wide window is now on the in side, which the chip faces, as the 1D and 2D views draw it.
- In the editor, a click anywhere in an inset's box selects it; before, only its ink did. The 1D and 3D views name
  the insets they leave out. The 1D view lost its own Export button (the Export menu has it). The right panel folds.
- The 2D light no longer shows the click area of a beam as black dashes over the light.
- A scene inset whose scene has no parts draws a blank of the scene frame's shape. It raised a division by zero.
- `uv.lock` holds the `figure` extra, and no longer the MkDocs packages that left `pyproject.toml`.
- There is one `Sample`: a chip in a copper holder whose face looks toward its `in` port, and `angle` turns it to the
  light in every view. An objective above it on the page takes `angle=-90`; on a 3D bench the same angle turns it on the
  table, so the chip stands face on to the objective. `mount_orientation` is gone, and a saved flat sample loads turned
  to the same side. `in` now lies on the face of the chip and `out` on the back of the holder, in 2D and 3D; a sample
  outside a cryostat keeps `side_in` and `side_out` on the edges of the chip. A beam that passes a sample at the side
  draws a warning. In a `Cryostat` the chip stands on a copper block and faces the window: the beam met its edge before.
- The 2D look of the bench parts is new, and each part agrees with its own 3D model. Shared materials give metal a real
  highlight, a mirror a silver face on a dark mount, a post a steel rod in a dark holder, and copper its own colour; the
  hard highlight band and the strip shadows are gone. What stops light is dark in 2D.
- The laser in 2D is the dark head of the 3D model, twice as long as it is wide, with its fins, face plate and nose, and
  it keeps its spectrum and its diode. The periscope shows two pale mounts, a band across each beam, and a mark for light
  that runs up or down.
- A `Telescope` is two lenses at their true spacing in 2D and 3D: a short barrel round each lens, joined by four thin rods
  and held by one clamp, so the light stays in view. It was a closed tube in 3D, and in 2D a small sketch at the in port
  with no beam along the rest of the part. In 2D the two rays cross at the focus, and a galilean telescope has a concave
  first lens. The 1D symbol stays.
- A `Spectrometer` is a Czerny-Turner seen from above with its lid off, in 1D, 2D and 3D: a chamfered body, the slit, a fold
  mirror, the collimating mirror, the grating on its turret, the focusing mirror and a cooled CCD head on the exit port,
  with the light in a W and the colours spreading after the grating. It was a pale box with a lens layout in 2D and a closed
  black box in 3D, and the two views disagreed. The body keeps the size of `box_size`, and the head now hangs below it. In 3D
  it stands on a plate and four pillars of its own; `base_mount="post"` puts it on one post.
- A beam runs to the middle of a lens, under the glass, so no gap shows where the faces curve away. A cone nests among
  the bands by its width, so a beam keeps its colours through a lens, and a focus lies its true focal length from the
  middle of the lens.
- Redrawn in 1D and 2D with the numbers of the part's 3D model: `BeamDump` (a section with ring fins round the back half
  and rays that trace the cone), `Block` (a black flag on a post and a base), `Razor` (a solid wedge with its tip on the
  beam axis, as a Foucault diagram draws it). Also redrawn: the Glan-Laser polarizer, polarizers, wave plates and filters
  in a dark ring, the SLM, the iris, the pinhole, the kinematic mount, the flip mirror's hinge and, in 2D, the lamp.
- An `Objective` and a `Pinhole` no longer draw light in the air beside them: the part ends at its last surface, and its
  port sits there. A `Lamp` in 2D is a lamp house with its reflector and bulb.
- `Razor` has `in` and `out` ports, so a beam can run past it, and passes half of the power in an animation. Its cutting
  edge now faces up at `blade_pos` in every view: the 3D post stood in the beam before. In 3D it is a blade in a clamp.
- `Block` ends the light in an animation, and in 3D it stands on the bench post alone: it had a second post and base.
- `Glyph.on(beam, "pulse", leg=2)` draws what the light carries at that place, beside the beam and in its colour: a
  pulse, a pulse train, a spectrum, a steady wave or a spot. `check_figure` names a glyph on a label or a part.
- `Panel(zoom=(panel, region))` says a panel is a closer view of a place on another. A dashed box marks the place, a
  frame marks the panel, and two lines join them on the sides that face. `region` is a part or `(x0, y0, x1, y1)`.
- Labels and notes take markup: `f_p`, `T_{ij}`, `cm^2`, `*k*` and `**bold**`, in 2D, 1D, TikZ, PDF and PNG. A name such
  as `beam_splitter` stays as written. A backslash keeps the next character.
- `Callout`, `Bracket` and `DashedLink`: text with a line to what it names, a square bracket beside a span, and a thin
  line that ties two places. Each takes a point, a part or `(part, "port")`. `check_figure` names a leader that crosses
  a label or another part, and a label on a link.
- `check_export("fig.svg")` measures the finished file at its print size: the page against the column widths, text
  in points through every panel and scale, the median label against the width, fonts, overlaps, text that leaves the
  page or crosses the art, words per square centimetre, hairlines outside the symbols, panel letters and image
  resolution. The limits come from published figures. The art check needs `optodraw[gif]` and says so when it is off.
- Beams on a shared path stay visible and on the axis. Give each beam its own width and they nest: drawn widest
  first, with infrared the widest, and each shows round the next. `check_figure` names two beams that hide each other
  and gives the `width` that nests them. `Beam` and `FocusingBeam` also take named `opacity` and `offset` parameters.
  `offset` gives a beam a lane beside its path for the whole path; at a mirror the lane meets the mirror face and
  swaps sides, as real light does. The TikZ output now carries both opacities and the width by wavelength, and a
  saved scene keeps them.
- A beam that folds at a mirror is cut on the mirror line. Its edges are rays that stop on the mirror and leave on the
  other side of the light, so no corner stands behind the mirror. A thin plate no longer splits a beam in two.
- `Scene(beam_style=BeamStyle(opacity=0.4, scale=1.5, by_wavelength=2))` sets the look of all the light of a figure
  in one place, and a beam's own value still wins. The default opacity of beams and cones is now 0.5, where a lower
  beam shows the most it can (25% of its colour; it was 13% at 0.85): every 2D figure gets paler. The editor has the
  three values in Scene settings, and opacity and lane for one beam in the inspector.
- `Note` is free text on a figure. `Note.on(beam, "880 mW", leg=3)` places it beside one leg of a beam.
  `check_figure` and `fit_frame` read a note as they read a label.
- `scene.export_figure("fig", width_mm=89)` writes SVG, PDF and PNG at their size on the page, framed on the
  content and the labels (800 dpi and 7 pt by default).
- `NDFilter` is a neutral density filter or an ND wheel, with `optical_density`. `Objective.focus_point()` gives
  the place of the focus for a sample.
- `FlipMirror` stands in the beam (`state="up"`) or out of it (`"down"`), and draws a dashed outline where it is not.
  `state="both"` is a figure of the two routes: a beam folds at `io` or runs straight on through `pass`. The checks,
  the tracer and the animation all follow the state.
- `scene.lens_beam(laser, l1, l2, dump, width=1, mm_per_unit=6.25)` lets the lenses set the drawn width: the first
  width is the display scale, the focal lengths give the ratios and the focus. A telescope drawn too short warns
  with the `mm_per_unit` that fixes it.
- `export_panels("fig", [[bench, "plot.svg"]], width_mm=183)` lays out scenes, cross-sections and SVG files as one
  figure with panel letters, in SVG, PDF and PNG. Each panel keeps its own ids and style rules. `Panel` sets a
  panel's width share, its letter, and old text to drop from an imported SVG.
- `stack_section(stack, layer, width=0.5)` gives the cross-section of one waveguide from a stack, for a chip figure
  with no GDS. `xs.beam(wavelength=450)` draws a beam entering any cross-section.
- Fixed: `check_figure` crashed on a scene with a `FocusingBeam` that a label touched, and it said a beam stops at
  a lens when a `FocusingBeam` carries the light on. A label on a focusing beam is now found.
- Fixed: a `Periscope` drew its own amber or blue bar over the beam. The beam now shows in its own colour up to
  both mirrors.

- A Layout view of an imported GDS, as KLayout shows it: the wheel zooms at the cursor, a drag pans, with the
  cell tree, the layers in the part's own colours (a `.lyp` written from its stack), a ruler and a click to
  inspect a shape. It runs GDS Lens 1.7.0 (MIT), vendored in `optodraw/renderers/js/vendor/gds-lens/` with its
  licences, so it needs no internet. In the editor a Layout button sits beside 1D, 2D and 3D; in a notebook
  `GDSModel.layout_view()` shows it; `optodraw.gds.layout_html` writes it as one HTML page, which opens from
  disk with no web server (Chrome starts no worker from a blob URL on such a page, so the page's host starts
  GDS Lens's parse worker from a data: URL). Cross-section cuts are
  drawn with its ruler (Cut along ruler); the 2D canvas cut tool is gone. `GDSModel.file_to_local` and
  `local_to_file` convert between the GDS file's frame and the part's; a cut can be posted with `frame="file"`.
- KLayout technologies load as layer stacks. `load_layer_stack` takes a `.lyt` (the colours and names of the
  `.lyp` it names, the heights of its `d25/*.lyd25` script) or a `.lyd25` alone (heights only); a layer the
  script derives from others is skipped with a warning. In the editor, Attach technology folder picks the folder
  and sends only its `.lyt`, `.lyp` and `.lyd25` files; a `.zip` of the folder works too, and a lone `.lyt` now
  says which files it needs. Before, a `.lyt` was read as a `.lyp` and gave no layers. The status line keeps
  the applied count, and says when a folder gave colours only.
- A GDS layer with no height in its stack shows "No height assigned" in the inspector, with empty th and z
  fields, where it showed the part's default thickness at z 0. `GDSModel.layer_records()` gives `None` for
  that thickness and z. Changing the layer's visibility, colour or material no longer writes the default as a
  real height; a height is written once both th and z are typed. A layer with no material says "No material
  assigned" (its material box reads "none"), where it showed the part's own `material_preset`; its record's
  `material` is `None`.
- A GDS layer with no height (no thickness or no z) is left out of the 3D view, the GLB and the oxide that
  process context builds round the device. Before, it was a slab at a made-up height: the part's thickness,
  stacked above the other layers. A note in the 3D view names the layers it leaves out, and
  `GDSModel.layers_without_height()` lists them. A GDS with no heights at all draws nothing in 3D until it
  gets a stack.
- Cross-sections, the top view and the 3D model build one oxide. A passivation of the oxide's own material is
  the last oxide level, not a film laid on top: round a metal that stands above the oxide it is filled and
  planarised to the metal's top plus its thickness, and over a cladding that already buries the metal it goes
  on as the cladding did. A passivation of another material stays a film of its own. The pad opening is an etch
  through the cover down to the pads, and goes no deeper than the cover where no pad lies under it.
  `stack.oxide` now carries `passivation_material`, so `GDSModel(**stack.oxide)` draws the cover the cut draws.
  A layer of `material: air` is an etch, never a film (the cut deposited it): one that ends inside the device
  layer is etched before the oxide, and one that reaches up into the oxide is cut through the finished stack down
  to its `zmin`. An etch step takes `to_z`, a floor height.
  A label search no longer steps over a narrow band between two metals, and a label in the column no longer
  crosses another leader when a free slot lies between two rows.
- The 1D router drops the steps a 2D route picks up on the 1D page: a guided link also tries one dogleg at the
  2D route's first turn, and the 2D route itself with its lane unmoved, and keeps one only when it turns fewer
  times and crosses no more routes. In 2D, beams draw under the parts they meet and over the carriers and the
  housings they enter (a cryostat, a vacuum chamber).
- The 3D page draws its light from the physics engine (`optodraw.animation_engine`) with a new player. The old
  3D engine is gone. The Light menu has two looks. Light shows glowing pulses inside the drawn guides: brightness
  is power, and speed follows the group index. Field shows the steady-state field with crests, mode shape and
  interference. It also shows heat maps from driven heaters and the RF field between modulator electrodes. Light
  starts off (`render_threejs(animate=True)` starts it), and captions state every scaled quantity. Light never
  crosses a device body or jumps a coupling gap. Each chip device draws its own internal paths, multimode bodies
  are regions, and a coupler draws one field per guide. A heater delays the light and shifts its phase.
  `render_threejs` takes `look`, `params`, `inputs` and `tour_drives`. The editor's Light section stores values in
  `metadata.animation.params`. Play tour moves the camera from device to device where something happens
  (`optodraw.animation3d.tour`: `Stop`, `Tour`, `auto_tour`). A tour saved in `metadata.animation.tour` wins.
  `tour_drives=True` puts the drive tables of the tour's driven stops in the page, so Play tour swings them. By
  default a saved page's Play tour keeps the drives as set, and the video always swings them.
  `Scene.render_tour_video(path)` saves the tour as an MP4 with ffmpeg, frame by frame, so the same scene gives
  the same video. Without ffmpeg it saves a WebM. The editor and the page each have Record video (the page's
  records a WebM in real time).
- `optodraw.gds.cross_section(gds, stack, cut)` cuts a layout along any straight line and makes the stack's
  process along it: the etch that leaves each slab (with a sidewall angle), implants through the silicon,
  growth on silicon, vias etched through the oxide and filled, metal patterned on flat oxide, and a conformal
  top oxide. `xs.svg()` draws it with labels, dimensions, a break in a thick BOX and a scale bar; z stays
  true unless the thinnest layer would be under 2 pt tall, and then the figure prints "z × N" and adds a z
  scale bar. `xs.steps_svg()` draws the process step by step; `xs.check()` names the faults. The process
  engine fixes: a grown layer no longer vanishes into the layer it grew on (Metal1 was empty), and CMP
  removes material above its height instead of filling a box up to it. A process YAML takes the steps
  `deposit` (with a conformality), `fill`, `implant` and a `caption`; `grow` still reads, as a directional
  deposit.
- `xs.png(path, look="sem")` draws the same cross-section as an SEM-like image: a grey per material, bright
  edge rims, a beam blur, seeded noise and an info bar with a scale bar. It is marked "optodraw render" in the
  info bar and across the image (`mark=False` removes both marks), and its PNG metadata says "rendered, not
  measured" always. The schematic now cuts a thick top oxide short with a break, keeps each scale value on
  the outer side of its own bar, and names the heavy implants N++ and P++ in the step captions too. A leader
  no longer crosses another leader or runs through metal, and a label in the side column points at the piece
  nearest it.
- `optodraw.gds.top_view(gds, stack, region, stage=...)` draws a chip region from above as an SEM-like image:
  `view.png(path, tilt=..., rotation=...)`. The cross-section process runs on a cut along each pixel row and
  each pixel column, and each pixel takes the cut that changes nearest to it, so a tapered wall shows in both
  directions. `stage="device"` stops before the first oxide, `stage="chip"` is the finished chip (a device
  under the oxide shows faintly, metal hides what lies under it), and a step id stops after that step. The
  shading, the marks and the metadata follow look B.
- The top view rounds a conformal film's outside corners as the 3D film does (a half ellipsoid grown from the
  surface under it), where no cut crosses the corner; `top_view(..., see_through=...)` sets how deep a buried
  device shows. A film's pattern etch now reaches one picometre past the film, so a film whose top tilts by a
  float step leaves no zero-thickness sheet behind.
- One 3D view everywhere. A saved 3D page (`render_threejs`, the notebook preview, the site) has one slim bar at
  the bottom (Camera, World and table colour, Labels, Light, Save, Fullscreen, More: GLB, JSON, Photoreal),
  in place of the five foldable panels over the view; its title sits small at the top left. Inside the editor
  the view draws no controls: a View menu next to Animate holds the camera, the world, the table colour, the
  labels, fullscreen and the photoreal render, and the Export menu holds the 3D image, transparent image,
  model and page. Labels and light start off everywhere; `render_threejs(animate=True)` starts the light.
  3D labels have their own scene setting, apart from the 2D labels. A click in the 3D view closes the
  editor's open menus.
- The editor's 3D animation is off until the Animate button is clicked (it started on, so the first click
  turned it off), and a 3D view that reloads with the animation off shows no light before the editor sends
  its state. Pause in the Animate menu still freezes the light in place; the button removes it.
- The editor's cross-section panel is wider and holds the cut controls (draw a cut, scan a vertical cut),
  four looks (Schematic, SEM, 3D slab and Top) with an option row each (z scale; marks and noise; slab depth
  and cutaway; stage, tilt and rotation), a large view, and a progress line. Images render at the panel's
  size; Save renders the full size. Fixed: the editor's cut dropped the stack's passivation and its material,
  and a cut whose oxide outline folded at a height break failed in the label placement.
- `xs.slab(path)` draws the cut as a 3D slab (look C): a block of the layout behind the cut whose face is the
  cross-section, made by the same process run on parallel cuts, with the oxide and the wiring above each step
  cut away so the lowest metal and then the rib and its implants show. `.glb` writes a named mesh and
  material per region, `.png` renders the viewer headless, `.html` the interactive view; no path gives the
  scene. `render_3d_image(camera=(x, y, z))` takes a view direction as well as a preset name.
- The editor's cross-section tool runs `cross_section` on the stack the GDS part carries and has a look
  picker: the schematic, the 3D slab, and the SEM-like image when this version draws it. It lists the
  findings under the figure. The old flat-band section renderer is gone.
- The presets are figures of the literature (`optodraw.literature`): each module draws one published figure as
  a compact schematic and cites it (`PAPER`). `confocal_pl` is Sahoo et al. 2026 (Fig. 5), `raman` McNairn et
  al. 2021 (Fig. 2a), `ftir` Ni et al. 2020 (Fig. 1), `free_space_breadboard` Wirthl et al. 2021 (Fig. 3a; also
  `self_calibrating_polarimeter`), `qwp_circular_lab` Schaefer et al. 2007 (Fig. 3), `ring_resonator_chip` Mak
  et al. 2015 (Fig. 1a, 7), `wdm_delay_weight_bank_chip` Tait et al. 2017 (Fig. 1a, the multiplexer an AWG; also
  `broadcast_weight_network_chip`) and `coherent_receiver_chip` Faralli et al. 2015 (Fig. 1). `mzm_mesh_chip`
  is unchanged. The Conchello confocal tutorial keeps its own scene.
- A free-space bench with fibres and cables (a fibre-fed spectrometer, a sync line to a counter) keeps its bench
  1D view: its cables route as on a chip and follow their 2D path, and its labels sit on the side the 2D
  drawing gives them. In 1D a part with no label keeps no room for one; a large part no longer stretches round
  the small parts beside it (the plan map grows the inner bands first); a pad wired straight to a contact
  inside its part (a ring filter's heater) lines up with it, with the other pad of its row; the pad symbol is
  smaller (11 pt). The symbol library has the heater variants of the 4th and 5th order ring filters. The
  no-light check counts a detector at the end of a fibre as lit, and a long route round the outside of the
  other parts (a feedback bus) is no longer a "long route" finding.
- More 1D fixes: a part sits where its straight 2D links are straight (a weight bank's through port runs
  straight into its detector); a pad whose 2D port faces its contact keeps that side; a label goes off the page
  only when no spot on it is free, and the page then grows; a route with a repeated point no longer writes
  "nan" into the SVG (a rasteriser drew it as a line to the page corner); the source-plan bench layout meets
  every beam at a plate splitter's centre; a part in a chain lines up with its one straight link, and its own
  terminators move with it; a ring filter's bus ports face left and right on a tall stack too (they read as
  top and bottom, so its buses left it vertically). A chip's 1D label takes a side the 2D gives it other than the default top.
  The bench walk follows a beam back as well, so a second source's arm sits by the part it joins (the
  Raman LED arm, the ODMR side laser: that 1D was 1826 pt tall, now 303).
- Review fixes to the literature figures: the Raman setup is 108 x 89 mm (was 154 x 139); the Sahoo objective
  stands outside the cryostat and focuses through its window, and its detection block sits beside the
  excitation column (234 x 160 mm, was 242 x 219); the FTIR beams enter and leave each splitter by the face
  they meet, and the setup is 50 x 58 mm (was 77 x 84); the Faralli receiver is 383 um wide (was 398); the
  Tait lanes fan into the AWG with visible bends. The figure check reports a chip route drawn across a part it
  does not join, and a 1D route that crosses more links than its 2D route. The cross-sections docs device uses
  the PDK's default `via_stack_slab_m3`, so the cut shows M1, M2 and the M3 pad metal.
- One waveguide width and colour: the ring-family parts draw their waveguides at 1.2 (was 2.6), as every
  other part does, and a waveguide route takes the parts' silicon colour (#2b6cb0, was #2d6cdf).
- Skills: `optodraw-figure` teaches space checks against the column (and prints the sizes), every part's
  ports in use, the objective outside a cryostat, fibres as routes and cables round the outside, and a table of
  review comments and their faults; `optodraw-layout` one waveguide width and colour, bends you can see, lanes
  that never double back, leads that fan into a tilted face, one node per line, and the new checks;
  `optodraw-gds-3d` walls, passivation and pad openings copied from the PDK's stack, the stack deciding the look,
  and a full metal stack in a device cut; `optodraw-component` `beam_passes` and `open_ports`.
- A beam runs through a part the light crosses on one straight line: in 1D under its symbol (an iris or a
  waveplate with a rotation mark showed a gap), and in 2D through an `Iris`, whose aperture is open
  (`beam_passes`). A film's pattern etch in a cross-section takes the whole film under its mask (`through`):
  the SiN and heater films, deposited over germanium or M1, were left as sheets across the cut. The FTIR
  figure has every part's port in use: a photodiode at the focal plane, and no virtual mirror M2'.
- A chip's 1D closes up: one height map for the page let a tall symbol in one column (a splitter, an AWG)
  stretch its band in every column. Now each row of parts rises until it meets the part over it in its own
  column, with a track for each route between them; it never rises past a part it links to or a part wholly over
  it in a column close by, and the 2D routes move with it. Pads sit right under their contacts. The label of a
  part decides its side from its linked ports only. Tait 1D 648 x 344 pt (was 652 x 444), Faralli 397 x 232
  (was 397 x 265).
- Routes: two ports at a right angle join with one bend (the lead stubs stepped back and made a jog); a lead
  that steps back over a route's last step is dropped (the steps a caller gives stay). The 1D router follows a
  2D cable that runs left of or above every part (it went the other way, across a beam). A bench's 1D label
  keeps the side the 2D gives it, also at the page edge. `Scene.fit_frame` holds every label in the frame.
- The generic stack carries what gdsfactory gives and it left out: the sidewall angles of its LayerStack (core
  10 degrees, the contact via 10 degrees wider at the top) and of its KLayout process script (VIA1, VIA2 and the
  metals 4, the pad opening 5), and the script's passivation, 0.5 um of oxide over M3, opened on PADOPEN
  (46/0). A stack names its pad-opening layer with `role: pad_open` and its passivation material with
  `oxide.passivation.material` (it was always nitride). A cross-section's etches each take all but the thicker
  layers to the next level and stay vertical where their mask meets the window edge, so a sloped wall leaves no
  wedge. Look A sizes its label column for the longest label, never leaves a label out, and keeps leaders
  from crossing each other.
- The animation engine animates a `DichroicMirror` (by its edge and pass band), an `AWG` (each channel passes
  its own band to the common port and back) and an `MMI1x4`; a dichroic sends no light down its blocked path.
  `Filter` and `DichroicMirror` refuse a `pass_band` other than "longpass" or "shortpass" (the ray tracer read
  any other word as longpass and the animation as shortpass). Two ports that face each other in line join with
  one straight run: lead stubs longer than the gap no longer double back. `show_polarization_overlay` traces
  the state after each polarizing part along the beams when the scene sets none, starting unpolarized.
- `Scene.fit_frame` frames the content where it is: a drawing far from the origin gets a frame its own size,
  not twice its reach from the origin. The scene keeps a `frame_center`, which the SVG view box, the figure
  gate, the editor's frame warning and save and reload follow. A drawing round the origin keeps its centred
  frame.
- `GlanLaserPolarizer`: a prism polarizer that passes p straight from `in` to `out` and sends s out of the side
  window `reject`, at `reject_angle_deg` below the beam (set it for the prism you draw); with its 1D symbol and
  2D art, a 3D body and an animation behaviour. `Laser(sync=True)` has a sync output, an electrical port under
  the head, drawn in 1D and 2D, for a pulsed laser that triggers a counter. `OnChipLaser(wavelength_nm=...)`
  keeps the wavelength it emits (the animation uses it). `Vec3` is exported from `optodraw`. The layout skill
  says plainly that a chip part's arguments set its physical values while the drawing and the ports keep the
  schematic size (a coupler's `port_spacing`, a waveguide's `length`).
- A `GSGProbePad` draws its pads at their own size and pitch, so each port sits on its drawn pad (the
  default drew 32 um squares round 12 um pads). A painted free-space part (a stage, a filter, an iris, a lamp,
  a camera) takes as its box what is drawn plus the ports where beams attach, not a larger plan: labels sit
  by the drawing and frames close up. A 1D cable to an electrode inside a part (a modulator's bars) meets it
  the way its 2D route does and may cross the part, along its own lane; the Reed probe's 1D no longer crosses
  its input. A test holds every part to its empty label (no default text), also after a save and reload.
- A chip's 1D view is its 2D plan, closed up (`optodraw/symbols/plan.py`): each axis maps through a rising
  function that grows every part's span to its symbol and shrinks empty bands to a few points, so the parts
  keep their 2D arrangement. Each link is routed square along its own 2D route, so a loop that runs round
  the parts in 2D runs round them in 1D, and a mesh coupler sits midway between the rows it joins. A part
  fed by one port lines up with that port where the two line up in 2D; pads under a part hang straight
  under their contacts, in two staggered rows when one row does not fit. A chip whose parts overlap in 2D
  keeps the automatic 1D. The MZM mesh preset is tighter (rows 32 um, columns 68 um: 636 x 117 um, was
  744 x 189), and an on-chip laser draws 80 um long, not 144 (shorter than an MZM). A 1D label keeps a point
  clear of the symbols. Routes keep their 2D lanes in order (each lane gets its own track), and two routes
  that cross only because of the order they were routed in are routed again the other way round. A test
  holds every chip tutorial and preset to a 1D with no crossing its 2D does not have.
- A 1D schematic routes its waveguides and cables as on a chip: each link leaves its port square, runs on a
  grid round the symbols and their labels with rounded bends, and keeps off the tracks of the other links;
  a link crosses another only where it must. Free-space beams stay straight. The SVG, the notebook view,
  the TikZ export (`rounded corners`) and the editor draw the same routes (`Schematic.routes`,
  `link_path`); the editor routes again after a part is dragged. A chip's plan view closes up: a part slides
  under a row that leaves it room (the Tait broadcast-and-weight network: 12 % narrower, 21 % shorter).
  A pad in the row under the part it serves turns to face its contact, so its wire runs straight.
- A figure is compact, never to scale. `check_figure` reports a chip whose parts fill less than a fifth of
  the figure, and a route that runs more than three times the size of the parts it joins across the figure.
  An `ElectricalPad` draws its own size, so its port sits on its drawn edge and a small pad sits beside its
  device (a 12 um pad drew as a 32 um square with its port inside). A weight bank's drop ports and a
  balanced MZM's second input and output may stay open without a loose-end finding. A chip's 1D plan view
  keeps each part's pads with it, in a tight row centred under the contacts they serve. The figure and
  layout skills now ask for schematic sizes, small pads beside their part and short square wires, and no
  longer advise `render_physical=True` for a figure. The Reed tutorial's pads sit west of its cable lanes.
- `RingAssistedMZI`: a Mach-Zehnder interferometer with microrings side-coupled to its arms, the
  flat-top filter of C. K. Madsen and J. H. Zhao. `rings_per_arm=(top, bottom)` puts the rings above the top
  arm and below the bottom arm, `coupler` is `"dc"` or `"mmi"`, and `with_heaters` adds an arm phase shifter
  (`h1`, `h2`) and one heater per ring (`rh<k>a`, `rh<k>b`). Its animation behaviour makes each ring an
  all-pass loop on its arm, so the spectrum shows the ring resonance and a pulse rings down. The 1D symbol
  rows are in `variants.toml`; run `python -m optodraw.symbols.build` to add them to the library.
- A part on a stage shows a small motion mark in 2D (a double arrow for `base_mount="stage"`, crossed arrows
  for the new `"xyz_stage"`, a curved arrow for `"rotation_stage"`), on the side away from its label; the 3D
  view draws the stage under it, as it draws posts, now with a three-axis stage too. The editor offers the
  stages for samples as well. `Cryostat(with_sample=False)` no longer draws a second sample and a red axis
  through its windows. `run_checks` reports a beam that runs along a lens or a filter instead of through it.
- Fixed: the ring tutorials, their notebooks and the ring preset put the detector on the ring's add port
  (`o4`), which gets no light; the drop leaves at `o3`, top west (Bogaerts 2012, Fig. 1).
- A chip's 1D view keeps the 2D order of its parts (left to right, top to bottom, each part turned as in
  2D) when the compact arrangement would cross more links: a receiver whose signal enters from the right,
  or a network with feedback, reads as its plan. `build_schematic(..., arrangement="auto" | "plan")`
  chooses one; `link_crossings(schematic)` counts crossings. `check_figure` accepts a detector, a sample
  or a power meter at the end of a beam, a label on the part that holds its part (an objective in a
  cryostat), and checks a chip's labels at the size the `fit="width"` export prints them. The skills learned
  from agents that rebuilt nine presets: the faces of every splitter, lens and filter angles, the parts
  that end a beam, real size on a chip (`render_physical=True`), probe pads, U-turn routes, and gaps in
  the plan.
- `check_figure` finds a beam that stops in a part light leaves again (a splitter, a lens) or leaves its
  last part into nothing, and a detector off the focus of the lens in front of it. It no longer calls a
  part's own probe pads (a detector's two pads) loose ends. `check_part_3d` no longer checks chip parts like
  parts on posts: their films sit in a layer stack. In 1D, a part with one link to a port on the left of a
  part sits left of it: the terminator on a ring's add port no longer loops its wire back across the ring.
  The skills say `engine="viewer"` gives a 3D look in seconds; the default engine is the final render.
- A cube beam splitter (`NonPolarizingBeamSplitter`, `PolarizingBeamSplitter`) has a fourth port, `tap`, on
  its bottom face, so a cube can recombine two beams (a cube Mach-Zehnder keeps its power). The polarizing
  cube routes light from every face, and the 1D symbol names the port.
- The presets and tutorials pass `check_figure`'s label checks: labels that sat on a beam (confocal PL,
  Raman, FTIR, the breadboard PBS, the fold mirror) or on a neighbour (the AWG demux detectors, the ring
  chip's terminator) moved to a free side. A beam through an upright `Sample` meets both faces of the drawn
  plate; it stopped short of the back face and left a gap.
- The bundled stacks note where a pad stands: on VIA2 in the gdsfactory generic stack, on the heater in the
  CornerStone stacks. `check_stack` reports a pad drawn without it.
- The TikZ export draws a part made from SVG art as TikZ paths, in 1D and 2D, with its ports named for the
  links. It wrote a pic that no library defines (LaTeX stopped), and the 2D export raised a KeyError.
- `export_paper_figures(..., fit="width")` puts a scene of any units into a journal column: the SVG is
  framed on its content and labels, sized to the preset width in millimetres, with labels at the preset's
  point size. The clip warning is no longer swallowed by its own error handling.
- `optodraw.check_figure(scene, preset=..., view=...)` is a figure gate: labels that overlap, sit on a beam,
  a route or another part, float far from their part, run off the frame, read like a sentence, or print
  too small at the preset width, in 2D and in 1D; on a chip, ports nothing connects and routes that
  cross. The labels of a part turned off the right angles are placed from its own shapes, so a 45 degree
  plate's label sits next to the plate, not past the square frame of its art. In 1D, a plate splitter
  meets its beams at its centre, and a label never sits on a beam or a wire.
- Straight beams: `aim` puts a mirror's face, or a plate splitter's centre, on the point given, and a beam
  meets a plate splitter at its centre (a thin plate meets the beam at one point; the ports keep their names).
  `run_checks` reports a beam that leans a little off a straight run. The breadboard preset's mirror sat
  off its beam line. `register` refuses a name the catalog already has unless `replace=True` (a user part
  named `AOM` replaced the built-in one).
- Checks found by agents that used the skills: `run_checks` reports a beam that enters a part from behind or
  leaves it backwards; `optodraw.layout.face(part, toward)` turns a detector to its beam;
  `optodraw.check_part_3d(part)` finds loose solids and a post that meets no flat face; `check_stack` finds
  a layer floating above the oxide. The 1D bench closes interferometer loops with straight beams. Every
  part keeps the `label_side` it is given (149 constructors dropped it). `import_svg_part` reads the
  `<path>` port marks that drawsvg writes and refuses a mark it cannot place. `render_svg` and
  `render_tikz` both take `view=` and `onchip_view=`.
- `optodraw.gds.check_stack(gds, stack, cell_name=...)` names every fault between a GDS file and a layer
  stack that would render silently: several top cells, a guessed oxide, unread stack entries, values in
  nm, layers drawn but not in the stack (with a datatype hint) and floorplan layer numbers.
  `load_gds_layout` and `GDSModel` warn when a drawn layer gets a made-up height, and
  `load_layer_stack` takes a bundled stack by name (`bundled_stack_names()` lists them).
- `scene.render_gif` frames sit on white; they were black, with dark labels that could not be read.
- Agent skills ship in the package: `optodraw-figure`, `optodraw-layout`, `optodraw-component`,
  `optodraw-gds-3d` (with a preflight for the silent layer-stack faults) and `optodraw-animation` in
  `optodraw/skills/`. `optodraw-skills install` copies them where Claude Code and Codex
  read skills (`--project` for one project, `--dir` for any folder). Every python block in them runs in the
  test suite.
- The documentation is an Astro site in `docs/` (the MkDocs site and its pages are removed). Every example
  redraws a cited published figure, and each example cell runs in the reader's browser: Run starts Python
  (Pyodide) with the site's own optodraw wheel, the cells above run first, and the 1D, 2D and 3D tabs show
  the result. The README is short and its images come from the site's cells (`scripts/make_media.py`).
- `PhotonCounter(channels=...)`, a fibre-coupled single-photon counting module (a fibre in and a pulse out
  per channel), and `CoincidenceCounter(channels=..., window_ns=...)`, with their 1D symbols, 2D art and
  3D bodies.
- `PartialMirror(transmission=...)`: a coated plate used at normal incidence (an input, recycling or output
  coupler mirror), with its own 1D symbol. `BeamSplitter` is one coated plate with `front` and `back` face
  ports for normal incidence; its 3D coating looks more like a mirror as the reflectance rises, and a
  dichroic coating has its own colour. `DichroicMirror` is now the dichroic `BeamSplitter`.
- Every on-chip part follows one open process stack, the GDSFactory generic stack, unless its scene sets a
  foundry stack. Schematic parts keep the layer order with a compressed oxide; pads sit on top on vias.
  Fixed onto the stack: phase shifters, EAM, polarisation rotators, edge coupler cladding, heaters, p-n ring
  and racetrack modulator pads.
- `scene.set_view_layout({"3d": {"spacing": "auto"}})` spreads only the 3D view; routes follow in the spread
  copy, and only a `"1d"` setting changes the 1D view.
- 3D free-space parts redrawn after a review: prisms (their glass sat wholly above the beam axis) stand
  centred on the axis on a prism table; a 4f relay is a cage with its Fourier mask one f1 behind lens 1
  (it sat at the midpoint when f1 and f2 differ; the `fourier` port and `fourier_plane_offset` follow); a
  chopper's hub sits below the beam so the beam crosses its slots; a beam dump's cone opens toward the beam.
  The aperture stop and pinhole are thin plates in ring holders, the spectrometer slit is a plate with two
  jaws and a micrometer. Mirrors, beam splitters, partial mirrors, dichroics and `KinematicMount` share one
  kinematic mount: a square front plate holds the optic, an L back plate runs along one side and the bottom,
  the two knobs thread through the ends of the L and the pivot sits at its corner (the knobs hung behind a
  ring, and a mirror's face hung in front of its substrate). Bare optics (asphere, cylindrical lens, wedge
  plate, grating) sit in holders; round mounts have a flat boss for the post, tubes a clamp. Nothing hangs in
  the air: a test joins every solid of every free-space part. A part can name the point its post holds
  (`post_at` in its 3D geometry). The vacuum chamber stands on its feet on the table; the DMD array stays
  flat (each micromirror tilts, not the array). The periscope mirrors sit on kinematic plates tilted by two
  knobs in an L; the photodiode is a mounted photodiode, the PMT sits in its housing, and the spectrometer
  stands on a mounting plate. Parts drawn after real products: the power meter is a slim photodiode head
  with a viewing target (Thorlabs S120C), every camera uses a compact scientific camera housing (grooved
  body, end caps, C-mount, cage holes; the EMCCD larger and cooled, with a fan), the amplified detector is
  a slim upright housing (PDA36A2), the lamp a lamp house with a chimney and condenser, the EOM a housed
  modulator with an SMA input, the post stainless steel. Instrument screens are lit; source meters,
  network analysers and DAQ boxes have grey cases. Rings are flat satin rings: the viewer creases lathe normals (a flat
  retaining ring shaded like a rounded chrome donut) and rims are flat rings, not tori. Instruments have real
  front panels (laser diode controller after the LDC205C, the PM100D console in its red boot, a BNC DAQ with
  its connectors in a grid, source meter, network analyser, scope, generator and spectrum analyser with
  traces on their screens). The translation stage drives its carriage with a micrometer on a bracket, the
  monochromator sits on the table with its slits at the beam, the objective shows its open back aperture,
  the lamp house carries a finned heat sink, and the optical table is stainless steel.
- The 1D schematic leaves out an annotation arrow that no link reaches, links the parts a traced ray
  crosses, and puts a label beside its part on a tight vertical run instead of across the beam.
- A ring with a heater gets its heater symbol in 1D (it got a p-n ring symbol: the heater contacts had
  other names). A layer stack resolves layers given by `from`/`to` endpoints when it loads.
- User parts: a part of your own from SVG art or from Python, with no subclass. `define_part` and
  `import_svg_part` (ports marked in the SVG as `id="port:<name>"`) build a part factory; `register_part`
  admits a trusted Python class; a `PartLibrary` scopes user parts, whose names start with `user:` and
  never replace a built-in. `save_part` and `load_part` write and check part files (`.odpart`, a ZIP with
  `part.json` and hashed SVG assets). The editor has a new-part dialog and a My parts library. A part with
  no 3D model extrudes its SVG outline, marked schematic; a strict render rejects it. Scene schema 3
  embeds user definitions and their assets; schemas 1 and 2 still load.
- 3D beam heights link along each beam. A periscope's entry mirror meets the
  arriving beam and its exit mirror sits `rise` above it; every part after it
  rides at the new height on a taller post. A part with its own
  `beam_height` (a new attribute on every part, and a field in the editor's
  3D mount section) sets the height of its run, and the exit mirror before it
  follows. Traced beams do the same, and a lens after a periscope now focuses
  round the raised axis: it bent the raised beam down to the table before. A
  beam through a periscope draws in 2D again (`Beam.segments` raised
  `IndexError` after the periscope gained its mirror points).
- A new animation engine core (`optodraw.animation_engine`, renamed in a later
  step): it compiles a scene into a signal state, the paths the light takes
  through every part with arrival times, Jones amplitudes and wavelengths, for
  pulses and for continuous light. Parts declare behaviours in a registry; the
  solver checks causality and passivity and names the part when a scene
  cannot be animated. The old animation code is unchanged until it is
  replaced.
- `Scene.render_3d_image(path, background="none")` saves the 3D view as a PNG:
  the viewer's own three.js scene, rendered once in a headless Chrome,
  Chromium or Edge (`OPTODRAW_CHROME` names one) at the size and scale asked
  for. `background="none"` (the default) is transparent with no floor;
  `"light"` and `"dark"` are the viewer's studio worlds. The image is framed
  tight on the parts (a chip with its die), as a still: solid devices, no
  animation pulses.
- `render_3d_image()` renders with optodraw's own studio renderer by default
  (`engine="studio"`): studio softboxes that follow the camera, soft shadows,
  ambient occlusion, reflections, glass that refracts, glowing beams, a
  denoiser, a shadow catcher for `background="none"` and a studio floor under
  a chip. It runs on the CPU in Web Workers inside the headless browser, so it
  needs no GPU and no other program, and the same scene always gives the same
  PNG. `samples` is the samples per pixel; `quality="draft"` is a quick look.
  `engine="viewer"` saves the viewer's real-time render.
- The live 3D viewer takes its light from the studio renderer: the same
  softboxes as an environment map, the key softbox and the overhead diffuser
  as shadow-casting lights, and ambient occlusion at `quality="high"` (the
  default; `quality="fast"` leaves it out for weak GPUs). Its Photoreal
  button renders with the studio renderer and shows the image over the view;
  the GPU path tracer (`three-gpu-pathtracer`, `three-mesh-bvh`) is gone, from
  the page and from the offline bundle.
- `export_blender_script(..., camera_from_scene=True)` uses a camera stored in
  the GLB.
- The 3D framing fits the box of each part, not one box round the scene: an
  L-shaped bench fills the frame instead of framing its empty corner. The
  camera position is solved exactly for the view direction and the parts are
  centred on screen, so a long column of pads is no longer cut off.
- The 3D viewer keeps colours true: Khronos PBR Neutral tone mapping, softer
  fill light and a softer room map (metals keep the full map). On-chip
  silicon renders as the 2D blue `#2b6cb0`, not a pale sky blue, and gold
  stays gold.
- The on-chip die is as thick as its footprint calls for (a small part no
  longer sits on a brick), and the dark carrier is a narrow rim that stays in
  the frame. "X-ray devices" is off by default.
- The key light's shadow box fits the content (it was 10 units round the
  origin, with no bias): every part casts a soft shadow, and large flat tops
  no longer show shadow stripes.
- OpticalIOBank draws real couplers: grating couplers with a taper and
  teeth, or edge couplers with an inverse taper under oxide, in 2D and 3D
  (each coupler was a plain box). PresetWDMInput's 3D is its 2D funnel and
  three guides with their wavelength strips (it was one opaque block).
- Fibre parts in 3D lie on the table, where their fibre cables run
  (`lies_on_table`; the posts lifted them above their own cables), with their
  leads at the cable height `LEAD_HEIGHT`. Each follows its symbol: the
  amplifier module with its triangle and doped-fibre coil, the circulator
  with its arrow, the fused coupler in a glass sleeve, the flanged spool, the
  attenuator with its filter and arrow, the polarization controller on its
  clamps, and the SNSPD's cryostat can with fibre in and coax out. Fibre is
  amber in every view.
- A `Sample(in_cryostat=True)` in 3D stands in the `Cryostat` part (can on
  the table, window snouts on the beam axis, viewport, cold finger and copper
  stage) with no post; it was a glass tube lying on its side, on a post.
- Electronics in 3D: the on-chip TIA, ADC and DAC driver are dark dies with
  their label, their symbol mark in the role colour and gold tabs at their
  ports (they were light grey slabs at chip height). `CoherentReceiver`,
  `ReceiverMacro` and `TransmitterMacro` are modules: a carrier with its dies
  standing on it (90 degree hybrid, photodiode cans, TIA, ADC, DAC, driver,
  modulator), traces and guides between them, gold at the ports (they were
  flat plates with pale shapes).
- A fibre or bench cable to a part on a post rises to its connector: it
  leaves the connector level and eases down to the table along its route (it
  ended at the foot of the post). Cables lie on the board top when there is
  a breadboard.
- Fibres over gratings: `OpticalIOBank` puts each fibre over its grating
  teeth (it sat beyond the grating; at the facet for edge couplers);
  `VerticalGratingCoupler` gets the fibre port `f1` over its teeth, so a
  routed fibre lands on the grating; `TwoDGratingCoupler` shows its hole grid
  in 3D; `EdgeCoupler(with_fiber=True)` draws a round fibre at the facet.
- On-chip 3D is taller: schematic chip parts are drawn `chip_height_scale`
  times their height (2.5 for a part, rising with the chip size to 4.5; a
  number given wins; true-size parts and GDS keep their heights). Chip routes
  take the height, level and material of the parts they join, so a waveguide
  or a metal route runs into its part without a step or a colour band.
- On-chip 3D: the detectors, lasers and SOA build their 3D layers from their
  2D footprints; the ring and racetrack modulators get heavy doping bands,
  contacts and vias; heaters are titanium nitride; TIA, DAC driver and ADC
  carry their 2D marks on the package faces.
- The 3D viewer drops the grid of tile lines on its floor (`floor_grid=True`
  brings it back), adds a "None" world (no background, no floor) and a
  "Download PNG (transparent)" button, and frames the camera on the real
  meshes instead of the parts' centres.
- Fibre routes are amber (`#f59e0b`), the colour the fibre parts give their
  leads; they were green.
- The PN ring and racetrack modulators follow their 1D symbols: p inside
  and n outside the guide on one cleanly cut sector (the ring: -35 to 125
  degrees, -35 to 35 with a drop bus; the racetrack: its left bend), the
  heater on its own sector across the guide (the ring's left side, the
  racetrack's right bend), p++ and n++ strips with gold contacts and vias,
  and the bus coupling regions left free. Pads sit beside the region they
  serve, so no lead crosses a bus (ports `e1`, `e2`, `h1`, `h2` moved). The
  junction animation runs on the doped sector. Rings draw their edges as two
  circles, which removes a seam line where the ring outline closed.
- The SOA is a light tapered III-V gain mesa with its MQW on the silicon
  guide, a contact with vias and two pads; the preset WDM input brings three
  wavelengths (the 1D colours) on their own guides into a light silicon
  combiner.
- On-chip silicon is drawn in the AWGR blue (`#2b6cb0`, edge `#1a4373`;
  `SILICON` and `SILICON_EDGE` in `optodraw/components/onchip/base.py`).
  Germanium, doped silicon, III-V, MQW and TiN have light colours of their
  own, so no on-chip part is a dark block.
- Redrawn as their real layouts: the on-chip photodetector, balanced and
  avalanche detectors (silicon taper, p+ and n+ strips, Ge mesa, contacts
  with vias; the balanced pair wired in series, no metal over the Ge; the
  avalanche diode with its charge layer), the EAM (lateral PIN with a Ge
  stripe; its pads moved out to make room), the on-chip and DBR lasers
  (Bragg mirrors as teeth on the silicon guide, a tapered III-V mesa with its
  MQW, a heated phase section), the frequency comb (the laser pumps a
  microring on its output bus), the Sagnac loop (one waveguide through a
  coupler and round a loop), the echelle grating (access waveguides and a
  toothed reflector; its ports moved to the guide ends), the polarization
  rotator (a strip over a one-sided slab) and the thermal phase shifter (air
  trenches, a TiN heater, vias). The tap coupler bends gently (defaults:
  port spacing 8, transition 16, coupling 8).
- New system parts that papers show: `IQModulator` (an I and a Q `MZM` in
  an outer interferometer, built from the catalog's `YBranch`, `MZM` and
  `PhaseShifter`, with a heater for the 90 degree bias), `FrequencyComb`
  (the on-chip laser with the comb symbol; `line_spacing_ghz`,
  `line_count`) and `SNSPD` (fibre in, electrical pulse out; the meander chip
  in its cold housing).
- New fibre parts that papers show: `FiberAmplifier` (an EDFA, with
  `gain_db` and `doping`), `FiberCirculator` (ports `p1`, `p2`, `p3`),
  `FiberCoupler` (fused 2x2, `ratio`), `FiberSpool` (`fiber_length_km`) and
  `VariableAttenuator` (`attenuation_db`). Each has fibre ports, a 1D symbol
  and a painted 2D drawing from the same TikZ picture, and a 3D body.
- Removed parts that papers do not show as symbols. Duplicates:
  `Transposer` (an `Interposer` under another name), `ElectricalPadArray`
  (use `ElectricalIOBank`), `ThermalPhaseShifter` (use `PhaseShifter`) and
  `IntegratorTIA` (use `TIABlock(mode="integrator")`, which now draws the
  capacitor mark). Package parts seen only in cross-sections: `Interposer`,
  `SolderBumpGrid`, `ViaGrid`, `ViaStack`, `PadOpening`, `Wirebond` and
  `RFLaunch`. `GSGProbePad` takes the RF fields of `RFLaunch`
  (`impedance_ohms`, `bandwidth_ghz`, `insertion_loss_db`), so the RF chain
  checks still have a part to read.
- 2D drawings of the free-space optics come from the symbol library: each
  part is painted with the same TikZ drawing as its 1D symbol, fitted to the
  part's real ports and size (`optodraw/symbols/art.py`). The SVG, PNG and
  editor views and the 2D TikZ export use it; the ray tracer, the bounds and
  3D still use `geometry_2d()`. Thin plates fill their aperture, line weights
  shrink with a small part and are capped in a large one, a mount, a post, a
  platform and a periscope are drawn from above, and the table, breadboard and
  baseplate are light plates in 2D (3D keeps the metal colour).
- The symbol library has two looks. 1D is line art; 2D paints the same drawing
  in the style of modern interface illustration: light slate surfaces with
  soft gradients, hairline edges in a tint of each fill (no black line), a
  soft two-layer shadow and a highlight band, slate screens with a warm
  trace, glass, chrome, brass and gold, circuit boards. The objective in 2D
  keeps the look of its earlier drawing. The build compiles each
  symbol in both looks (`svg` and `svg2d` in `symbols.json`, one frame for
  both), and the 2D art and the 2D TikZ export use the painted look.
- The polarization controller is drawn as a paddle controller (a base, round
  paddles standing on it, the fibre wound in loops inside each paddle; a
  turned paddle looks shorter), and the translation stage from above (base
  plate, carriage with tapped holes, micrometer on the side), in 1D and 2D.
- In 2D a beamsplitter sits on the point where its beams cross. It was drawn
  away from its ports when its size came from its aperture.
- 2D drawings of the instruments, sources, detectors and samples come from the
  symbol library too. On a bench, a laser is a laser head seen from above, a
  photodiode is its housing with a window toward the beam, a cryostat is a
  round can with two windows, and a sample with `in_cryostat=True` sits on
  its cold finger inside a small can (also in 1D).
- 2D drawings of the electronic blocks come from the symbol library: the
  converters, amplifiers, chips, receiver and transmitter macros, the PCB,
  the interposer, the signal arrow and the IO bank, and the on-chip TIA, ADC
  and DAC driver (blocks, not layout). A digital mark is indigo and an analog
  mark is teal; a chip is a slate package with light pins. The coherent
  receiver and the balanced photodetector have 2D drawings with their ports
  where the parts have them, and the MEMS actuator is the comb drive of its
  1D symbol (a fixed comb and a lighter moving comb). Physical layout (pads,
  vias, bumps, metal routes, wire bonds, the on-chip heater, the RF launch)
  keeps its true geometry.
- `free_space_breadboard`: M1 faces down and right (`angle=135`), so it folds
  the beam from the PBS into the reflected arm. At 45 degrees it faced the
  other way.
- The WDM delay-weight preset is drawn with the full parts and follows the
  microring weight bank of the literature. The delays are curved `Spiral`s
  with 1, 2 and 3 turns. Each `MicroringWeightBank` has its own
  `OnChipBalancedPhotodetector`: the straight bus under the rings feeds the
  lower diode, and the drop bus, which passes over the rings and turns round
  at the input end, feeds the upper diode. The Y-branches keep their own
  size, and an S-bend after each output carries the light to its row. The
  drawing is centred in its frame.
- Removed the old stand-in parts of that preset, so nobody uses them by
  mistake: `PresetDelaySpiral` (a square spiral; use `Spiral`),
  `PresetMRRWeightBank` (use `MicroringWeightBank`), `PresetStarCoupler` (use
  `StarCoupler`) and `PresetBalancedPhotodetector` (use
  `OnChipBalancedPhotodetector`). A scene file that names one of them no
  longer loads. `PresetWDMInput` stays: it has no full part.
- `scripts/make_component_sheets.py` draws every part of the catalog on review
  sheets, one for each family, with each part scaled to its cell, and the
  sheet of the 1D symbols.
- A component's label clears art that is not centred on the part. The gap is
  measured from the top of the drawing, not from half its height.
- On-chip photodetectors keep the default ``angle=0`` so ``o1`` faces west
  (180°). Copying a grating coupler's ``angle=180`` onto a detector puts the
  port on the east face and the waveguide loops around the body.
- GSG probe pads default to squares with a gap between them. The schematic
  drawing uses the same square face as ``ElectricalPad``.
- The Reed MZM tutorial gives each GSG net its own square pad. Traces leave
  as L routes of different width, then jog on stacked rails to the pads
  above so they do not cross the optical input.
- The layout skill records GSG L-then-rail electrical routing, separate
  square pads, and a keep-out between grating couplers (or a
  ``GratingCouplerArray``) and bond pads so V-grooves stay off the probe
  edge.
- The modulator-drive recipe and the coherent-receiver preset use L-then-rail
  electrical traces of different first-leg lengths so GSG and I/Q nets do not
  stack on one x. Coherent I/Q pads are separate squares. The ring-resonator
  preset dumps the unused MMI output. Add-drop tutorials terminate the add
  port. The WDM delay-weight preset keeps manhattan waveguides on the local
  backend so gdsfactory collision warnings do not fire.

### Added

- `optodraw.animation_engine.spectrum(scene, start_nm=..., stop_nm=..., points=...)` gives the steady power at each
  port where light ends, against wavelength. `Spectrum.of(part, port)` gives one curve. Its notes name each physics number the light met
  that has no source, and say that the resonance position is a model value.
- `Source(kind, ref, note)` and `Sourced`: a number with its source (measured, literature, simulated or model). It
  stays with the number through a saved scene. `optodraw.provenance.model_numbers(scene)` lists the numbers with no
  source.
- `optodraw.sparameters.SParameters.load` reads an imported table: SAX keys in `.npz` (as `fieldrt.sax` writes them) or Touchstone
  `.sNp` (conjugated to the `exp(-iωt)` convention). `part.model = table` replaces the part's closed form. A table
  above a largest singular value of 1.05 is refused, and above 1 + 1e-6 it warns. A wavelength outside the table is
  refused, and a phase step above π/4 between table points warns. Tables carry TE only.
- `optodraw.animation_engine.signal_chain(scene, t_ns=..., inputs=...)`: the drawn electronics compute their signals.
  Optical power at a detector becomes a current, a voltage through a TIA (a `TIABlock`, or an `OpAmp` with its drawn
  `Rf` and `Cf`) and ADC codes; DAC codes become a voltage that drives a modulator, a laser or a heater. The light is
  solved once per time sample. Bandwidths are first-order poles, and there is no noise. `Chain.at(part, port)` gives
  a `Waveform`, and `Chain.show(scope)` draws it on the scope's screen. Its notes name each default number.
- Datasheet numbers on parts, each saved with the scene and each able to carry a source: responsivity, dark current
  and bandwidth on the photodiodes; gain and bandwidth on `TIABlock`, `Amplifier` and `AmplifiedPhotodetector`;
  sample rate and full scale on `ADCBlock` and `DAC`; bias and gain on `LaserDriver`; power, threshold and slope on
  `Laser` and `OnChipLaser`; heater resistance on `MicroringResonator`. A laser's `power_mw` sets the power the
  animation and the spectrum carry (1 mW when unset, as before).
- Instruments show computed data on their own symbol screen, in SVG and TikZ: `Oscilloscope(traces=...)`,
  `OSA(trace=...)` (`Spectrum.show(osa)`), and a `reading` on `OpticalPowerMeter` and `LockInAmplifier`.
- `optodraw.sax_export.to_sax(scene, wavelengths_nm=...)` writes the scene as a SAX netlist with one model per
  part, so SAX computes the same spectrum (to 1e-9 on the worked examples). The extra `sax` installs SAX.
- Free-space parts: `FaradayRotator` (a TGG rod in a ring magnet; two passes
  add), `ModeCleaner` (a triangular ring cavity; `refl` leaves by the law of
  reflection), `RoofMirror` (a delay line on a stage: the beam returns beside
  itself), `BalancedDetector`, and `Mirror(piezo="stack" | "3axis")` with a
  `pzt` drive port on every mirror kind.
- Circuit and instrument parts: `PIDController`, `SignalSource`,
  `SummingJunction` (signs "++" or "+-"), `RFSplitter`, `RFCoupler`,
  `RFPhaseShifter` and `RFSpectrumAnalyzer`; `LaserDriver` gains `mod` and
  `tec`, `WaveformGenerator` `sync`, `Oscilloscope` `usb`.
- 30 more parts act on light in an animation (AOM, EOM, SLM, chopper, 4f
  system, slit, prisms, periscope, cryostat, monochromator, partial mirror,
  photon counter, balanced detectors, fibre array, Bragg grating, Sagnac
  loop, AWGR and more), each with a physics test.
- The 1D view (SVG, TikZ, notebook, editor) draws a `Region` box, a `Bracket`
  and the motion mark of a part on a stage, and a dot at each join of a node.

- Free-space parts: `NonlinearCrystal` (BBO, LBO, PPKTP, PPLN; `poled=True`
  draws a poled chip in its oven), `QuadrantPhotodiode` (x, y and sum
  outputs) and `WollastonPrism` (H to o, V to e). Each draws in 2D, 1D and
  3D and acts on light.
- On-chip parts: `GratingAntennaArray` (an optical phased array's emitters),
  `PCMCell` (a GST cell, crystalline or amorphous, as a conformal film in 3D)
  and `EORacetrackModulator` (a Pockels racetrack with G-S-G electrodes, as on
  thin-film lithium niobate).
- Circuit and instrument parts: `Amplifier`, `RFFilter` (low-pass,
  high-pass, band-pass, band-stop) and `LockInAmplifier`.

- `PolarizationController`: a fibre polarization controller (a fibre wound on
  paddles), with fibre ports `in` and `out`, in 2D, 3D and as a 1D symbol.
  `paddles` sets the number of paddles (3 by default).
- Python classifiers for 3.10 through 3.14. CI runs Ubuntu on each of those,
  plus macOS 3.12 and Windows 3.12. The coverage job also installs the `mcp`
  and `optiland` extras so those tests run. A separate job installs `manim`.
  A `mypy` job type-checks the root exports and `_compat`.
- `optodraw/py.typed` so type checkers treat the wheel as typed.
- Renderer capability tables (`optodraw.renderers.capabilities`): every
  geometry type maps to full, approximate, or skip per renderer. Each renderer
  accepts `strict=False`; strict mode raises `UnsupportedGeometryError`
  instead of dropping content, default mode records a shared-shape report.
  The GLB exporter report now uses that shape, with a new
  `scene_to_glb_with_report` entry point.
- Cross-renderer acceptance fixtures (`tests/fixtures/acceptance/`): rotated
  optics, stage arc, and chip route scenes with structural assertions across
  SVG, TikZ, and GLB instead of golden files.
- Offline 3D bundling: `render_threejs(path, offline=True)` writes a sibling
  assets dir with pinned three.js, mesh-bvh, pathtracer, and addon tree plus
  licenses, and rewrites the page to relative paths. All three packages are
  MIT; fonts fall back to system stacks offline.
- Single-figure export writes `{stem}.manifest.json` with document hash,
  version, preset, and renderer settings.
- Contributor checklist (`docs/new_part.md`) plus a registry meta-test that
  checks every registered part for ports, geometry, and spec round trip.
- Compatibility policy (`docs/compatibility.md`): stable, evolving, and
  legacy tiers with a `deprecated` helper in `optodraw._compat`; the public
  API snapshot is refreshed to 330 names.
- `docs/compatibility.md` now states that new physics solvers stay in their
  modules until a changelog entry promotes them to `optodraw.__all__`.

### Security

- Three.js HTML export escapes scene data, titles, and layer legend fields, so a
  component label containing `</script>` can no longer inject markup into the
  exported page.
- The editor escapes component ids, port names, palette display names, layer
  names from uploaded techfiles, and workspace/preset labels in the command
  palette before any `innerHTML` use.
- MCP tools clamp every output path to the working directory, the user's home,
  and the system temp directory (extend with `OPTODRAW_MCP_ALLOWED_ROOTS`), and
  an unknown tool now surfaces as a protocol error instead of a text reply.
- `optodraw-gui --hosted` requires a shared editor token (`--auth-token`, else
  `OPTODRAW_AUTH_TOKEN`, else a generated one printed at startup); browsers log
  in once via `/auth/login`. `--allow-anonymous-hosted` opts out explicitly.
  Local use is unchanged.

### Changed

- Beams of other colours on one path draw nested on the axis in 2D and TikZ: the lower beam, the one with the longer
  wavelength, draws wide enough to show round the next. A beam already wide enough, or in a lane of its own, keeps
  its width. `check_figure` no longer reports beams that hide each other, as they no longer can; it reported 9 in
  the iSIM docs example and the confocal, Raman and bench confocal scenes. TikZ draws beams widest first, as the SVG
  does.
- A 4f relay and a circuit board draw at their own size in the look of their
  symbols. The relay's planes are dashed slate and its rays are the symbol's
  red. The board is emerald, with gold pads and gold traces that drop one row
  through a via.
- A bench cable takes one width (0.5) and slate grey, unless you give it its
  own. It took the narrower port's width and red, so an instrument cable drew
  four times a circuit wire, in the hue of red light. Chip metal keeps its
  port widths.
- A bench cable routes round every part and label, as the 1D view routes its
  wires. It leaves each port along the port's facing, keeps a free track from
  the cables drawn before it, and draws under the parts. It ran up through an
  instrument and into a modulator from the wrong side.
- The EOM draws one lead, its RF port. A second lead under the crystal read
  as another connector.
- The 1D terminator is an open taper into an absorber block, and the 1D edge
  coupler's taper is open. The filled triangles read as arrows on the light.
- On a foundry stack, on-chip parts draw their core at the stack's core
  level, in its material and colour, as the cross-section does: on lnoi400 a
  waveguide is an LN ridge on its LN slab (it stood on the oxide, in silicon
  blue). Parts drawn through a copy keep the scene's stack.
- 14 on-chip parts draw their guide at the schematic width, as the others do.
- Every catalog part's ports lie on its 2D art: 35 parts missed it by up to
  61 units. The art size rule compares the real size with what the symbol
  draws; `FourFSystem` and `PCB` draw their true geometry.
- `OpticalChopper` draws a 12 unit wheel by default (was 26).
- 22 more legacy icons are removed: native parts now draw them (Faraday
  rotator, piezo mirrors, mode cleaner, servo, oscillator, spectrum analyser,
  sum and difference, crystals, QPD, amplifiers, filters). 15 icons stay.

- `EOM` has an `rf` drive port, and its art spans the whole crystal (it drew
  half of it). `AmplifiedPhotodetector` has an `out` port. A lock loop can now
  be wired end to end.
- Every racetrack option (drop bus, heater, PN) has its exact 1D symbol.

- In 3D a bare metal (gold, aluminium, copper, steel, titanium preset with
  metalness 0.9 or more) reflects with its measured base colour (the preset's
  new `physical` key). The painted 2D fill does not change.
- In 3D the bench beam runs 30 units (3 in) over the table, up from 16. At 16
  the larger optics reached down to their post holders and the posts read as
  stubs. Every pedestal now has the same base and holder, and the brushed post
  takes the rest of the height. `optodraw.components.optics.optomech.BEAM_HEIGHT`
  is the one value the viewer, the cryostat and the editor share; a scene can
  still set its own `beam_height`.
- The AWG and the AWGR draw one arrayed waveguide array between them, built so
  that arms cannot cross rather than so that they usually do not. Each arm
  climbs at its own aperture's x, caps over the whole aperture fan, and keeps
  every control point inside the corridor it crosses. Measured: zero crossings
  and zero doublings back, both devices, 4 to 48 arms, every tilt from 30 to 68
  degrees. Before, a 24 arm router crossed 14 arm pairs and a 32 arm one crossed
  292, at every angle. The AWG is now the router with one channel on its input
  horn, which is what makes a 1xN multiplexer and, rotated, an Nx1 demultiplexer.
- A star coupler grows its focal radius to keep its aperture fan inside a 22
  degree half angle, and the two couplers separate far enough to clear their own
  tilted faces. 32 arms at a fixed radius opened the mouth to 124 degrees and
  pushed the array face across the mirror plane. Both changes warn when they
  move a size you asked for.
- `AWG`/`AWGR` tilt now defaults to 45 degrees and is held inside [30, 68]. Below
  that the two couplers face each other and no ladder of nested arms exists;
  above it the flank apertures point back over the horn.
- A smooth route between two ports that face each other picks its S-bend axis
  from the line between them, not from each port's own quadrant. The old test
  asked whether a port was "horizontal" (`|nx| >= |ny|`); on an AWGR whose
  channel apertures run from -143 to -127 degrees that boundary falls in the
  middle of the arc, so two of four identical arms took the S-bend and the other
  two fell through to a Manhattan backbone and reached the same device through a
  square corner.
- A star coupler's mouth is now capped as a fraction of the room its tilt leaves
  it, rather than at a fixed 22 degrees, and the channel fan is capped the same
  way as the array fan. The fixed cap grew horns that did not need to grow: it
  nearly doubled a 16 arm router, which moved every port on it.
- `Scene.content_bounds` reads each component's own drawn box and moves it
  through the world transform, instead of centring an estimated size on the
  component's position. A part that draws itself off centre on purpose, such as
  an AWG anchored on its input port, no longer falls outside its own frame.

- `optodraw.components.optics` is now a package of family modules (lenses,
  mirrors, beamsplitters, polarization optics, filters and modulators,
  objectives and displays, sensors, fibers, apertures and spectroscopy, prisms,
  optomech) instead of one 4563-line file. Every import path is unchanged: the
  package `__init__` re-exports all 65 public names plus the
  `SpatialLightModulator` alias and the shared drawing helpers.
- `optodraw.components.electronics` gets the same treatment: packaging pads and
  routes, driver/control blocks, and readout macros replace one 4554-line
  file, with identical import paths and the `ElectronicIntegratedCircuit`
  alias preserved.
- GIF and Manim automatic animations now share one frame builder
  (`optodraw.renderers.frame_states`): identical build-up/beam-trace frame
  states, one beam-trace step count (12), and the Grid background is no longer
  treated as an animated component in Manim. Manim frame temp files use unique
  names instead of a process-global counter; the unused `_SCALE` constant is
  gone.
- Packaging visuals gain `visual_style="symbolic"` outlines on every pad, via,
  heater, launcher, wirebond, and metal route, and a new `presentation` style
  that restores gloss highlights. 2D golds and stroke widths move to shared
  palette tokens, duplicate highlight layers are removed, `MetalRoute` renders
  dashed in publication for grayscale, and 3D solder bumps and wirebonds drop
  from 36 to 24 and 42 to 32 segments at schematic scale.
- Free-space 3D mounts now sit on the board top instead of sinking into it
  (posts and flat mounts lift to `BOARD_TOP`, the tallest table/breadboard/
  baseplate in the scene). `KinematicMount` is now correctly treated as a
  flat mount. A new `base_mount="post_beam"` draws uniform-height posts to the
  beam axis, `"none"` suppresses the post entirely, and `mount_height` (alias
  `post_height`) lets any free-space optic pick a real post from the drawer so
  mixed apertures still share one beam height.
- `trace_ray` / `trace_paraxial_beam` warn on unknown keyword arguments instead
  of dropping them silently, and reject conflicting `wavelength` /
  `wavelength_nm` values instead of letting one win.
- GDS import failures (bounds, geometry, gdsfactory handoff) now log a warning;
  a malformed file is no longer indistinguishable from an empty one.
- Test coverage is enforced in CI on the fullest matrix leg; the floor moved
  from 55% to 80% (the suite sits near 85%).
- The `gds` extra installs gdsfactory 9 on Python 3.12 and newer, and 8.x on
  3.11. Generic PDK lookup prefers `gdsfactory.gpdk`.
- Three.js HTML export pins `three@0.186.0` / r186, `three-mesh-bvh@0.9.15`,
  and `three-gpu-pathtracer@0.0.24`. The offline bundler follows the same pins.
- `ruff` stays on `>=0.15,<0.16`. pre-commit matches at `v0.15.22`.
- Project metadata uses SPDX `license = "BSD-3-Clause"`. The `all` extra now
  includes `desktop`. CI installs extras instead of a hand-written pip list.
- Import SVG drawing in the editor now places the file as an inset.

### Docs

- A Spectra and models page: two rings from sourced numbers, a heater sweep, and an MZI of two directional couplers
  from a Meep simulation on fieldrt (the table and its script are in `docs/examples/models/data/`), a receiver from
  the drop light to ADC codes on a scope, and a transmitter from DAC codes through an MZM.
- A 3D Images page (`docs/studio_rendering.md`): the studio renderer's options,
  what it supports, measured times and where it falls short. The 3D images on
  the home page and in the README are studio renders (`scripts/make_media_3d.py`).

- Stale internal "3.x" references replaced across docs and nav; the migration
  page is now titled "On-chip Schematic API Notes".
- Examples: the ODMR sample stands on an XYZ stage (`base_mount`), not beside
  a loose single-axis stage; the coupled rings' signal arrows end on their
  buses, each with a label; the package's fibre-array label sits beside the
  array; the page of insets shows an SEM-like render, not a gradient.

### Removed

- 29 bundled gwoptics legacy icons that a native part now draws (mirrors,
  lenses, beam splitters, wave plates, lasers, AOM, EOM, isolator, fibre,
  photodiodes, mixer, computer). Use the native part. The 37 icons with no
  native part yet stay.
- The alias parts `FlatMirror` (use `Mirror`), `DiconcaveMirror` (use
  `BiconcaveMirror`) and `PolarizingBeamSplitter` (use `PBS`).
- The 15 bundled gwoptics icons and `LegacySVG`, `legacy_catalog` and `list_legacy`. Place your own SVG drawing as an
  `Inset("drawing.svg", ...)`, or with the editor's Figure palette (SVG file).
- `legacy_component_catalog` and the `include_legacy` argument of `component_catalog`, `list_components` and
  `list_on_chip_components`. They only listed the icons.

### Fixed

- A 1D bench keeps apart the beams that leave one part at different angles. Rounded to the axes, the two arms out
  of a crystal ran on one line through each other's parts, and a mirror fold ran back over its own beam: they now
  turn apart in 45 degree steps. An instrument on fibres or cables that lands between beams moves out past the light,
  and a fibre that closes a loop no longer stretches a beam to run straight. The Bell example of the docs drew 35 1D
  findings and now draws none.
- A 1D link whose lead ended in a corner of its own label's margin ran straight over the bench: the search now
  tries again from one grid cell further out.
- A flip mirror stands in a 1D bench as a mirror does. The outline of its other place made its symbol tall, so its
  face read as the bottom edge and the symbol stood a quarter turn round; its straight route now also meets it at
  its face, as in 2D. The confocal PL preset's removable mirror is a flip mirror that shows both routes, so the
  main beam no longer runs across a plain mirror in 1D.
- The 1D photodiode symbol (`detector`) has its `in` port on the diode body and no thin stub, so a free-space beam
  meets the diode instead of ending in a wire.
- The editor's layer list cut thickness and z numbers such as 0.20000000000000018, and the
  toolbar ran Trace, Simulate and Check together at laptop widths. Numbers now show to six digits
  in wider fields, and toolbar buttons keep their labels and drop their icons below 1600 px.
  The selection name in the toolbar stays on one line, whole on hover.
- On a foundry stack the 3D of a chip drew no upper cladding, so a heater on the cladding (the MZI on
  `cornerstone_si500`) hung in the air. The viewer and `View3D` now draw the stack's cladding as one clear body over
  the parts and their routes, from the top of the lower cladding to the top of the fill, in the fill's material: it
  fills round the cores, a metal that rises through it leaves its hole, and each pad is etched open. A stack can give
  its waveguide width (`waveguide: {width: ...}`); the parts then draw their 1.2 unit guide at that width and every
  height at the same scale, so an InP ridge is no longer a fence 4.4 times as tall as it is wide. `lnoi400`,
  `cornerstone_si500`, `cornerstone_sin300` and `inp_generic` give it, with its source. The vector view draws a
  clear body built in bands with no seam. On a stack that names no metal or heater level (`inp_generic`), a
  heater rests on the top of the cladding.
- A cross-section drew a deep substrate in full under a BOX too thin to cut (the InP stack's 2 um model
  substrate under its 0.5 um buffer): stretched five times, it stood twice as tall as wide. The substrate is
  now the stub under the break, as on silicon.
- A ring heater ran round the outside of its ring, along both buses of an add-drop ring, and its leads crossed the
  through bus to pads under it. The heater of `MicroringResonator`, `MicroringWeightBank` and `RacetrackResonator`
  now lies on the ring. It opens on one side, and its leads run out to pads in the part's cell: east, between the
  buses, on an add-drop ring and on a racetrack; north, away from the bus, on an all-pass ring. No heater metal, pad
  or via lies on a waveguide. The ports `e1` and `e2` move with the pads and face out. A weight bank's heater pads lie
  between its rings and may stay unwired. The 1D all-pass ring has its heater contacts on top. The Tait 2017 figure
  drops its 32 heater pads, which needed wires across a bus, and its rows sit 80 um apart.
  In 2D the heater draws translucent, so the ring under it shows.
- A page shown in a notebook or in the docs drew 0 tall, because both called
  the page's editor canvas. It now shows at its own size, as it prints.
- A part on a stage (`base_mount="stage"`, `"xyz_stage"`, `"rotation_stage"`)
  showed its 2D motion mark cut by a fitted frame: `content_bounds` and
  `fit_frame` now count the mark.
- A smooth route from a port off the S-bend axis, such as an AWG aperture on
  its arc, turned a corner of up to 60 degrees at the end of its lead. It now
  leaves and enters along each port: two arcs of its bend radius with a
  straight run between them (the AWG demux routes: 10.0 um, was a corner).
  Ports closer than that radius allows halve it until the path no longer
  loops, as a Manhattan route fits its radius to the gap.
- In 1D, the squared 2D guides of a fan that leaves a part at an angle could
  cross. A crossing pair is now routed again without its guides when that
  crosses less.
- The AWG input guide ran on at its aperture's tilt to a port that faces -x,
  so every bus met it at a corner. It now bends into the bus direction with a
  10 um bend; `i1` stays on y = 0.
- A beam that crosses one span twice, such as a double pass through a wave
  plate, drew that span twice as strong. A beam is now one translucent layer.
- In an animation, light that crossed a wave plate, met a mirror and crossed
  it again got the forward matrix twice: a half-wave plate passed twice sent
  the light to the cube's tap, and the quarter-wave isolator sent it back to
  the laser. The pass from `out` now sees the plate from behind
  (F J^T F, F the mirror's frame flip).
- A saved scene lost every part's stage: `base_mount` was read but never
  written. It is written when it is not the class default.
- `check_figure` finds a 1D link drawn across a part it does not join, a
  flip mirror's own label on its outline, and a fibre or waveguide route that
  ends off its port; light that goes on in a fibre is no dead end.
- `check_part_3d` applies the post rule only to optics the 3D view stands on
  a post. An RF driver's leads, a heater pad's filament and a comb drive's bus
  bar and springs now join their parts, and the comb's fingers no longer
  touch the other comb.
- A diagonal metal route, macro trace or package wire ran mirrored in 3D.
- A foundry stack with a metal and no contact layer left vias floating.
- `check_figure` measured a lens's focus to the next part, so a flat fold
  mirror after a lens read as "off its focus". It now measures along flat
  fold mirrors.
- The 1D view dropped the beam between two lenses where `lens_beam` makes a
  focus in the air. The two cones now join into one link.
- The 1D view of a bench with a feedback cable walked the cable like a beam:
  the oscillator became the root and the loop pushed the bench away (a lock
  figure was 868 points tall, with a bent beam). The light is laid out first,
  and the cable-only parts hang on it.
- A scene with a legacy icon exported an SVG that was not valid XML: the
  embedded Illustrator metadata kept prefixes whose namespaces it had lost.
  The export now drops them, so browsers and the PNG export read the file.
- `View3D.chip` left the etched trenches of an InP chip open, while the section
  fills them with the stack's polyimide. Each trench now holds the fill, opaque
  up to the top of the wafer, and the fill over the wafer is clear, so the
  guide tops still show.
- `OpAmp` had no supply pins. It now has `v_pos` above and `v_neg` below, in 2D
  and on its 1D symbol; a figure may leave them open.
- Off a chip, the 1D view always took the automatic arrangement, so a placed
  circuit crossed its own wires. It now keeps the 2D plan when the automatic
  arrangement crosses links and the plan crosses fewer, as a chip already did.
- The bench `Photodiode` had one contact. `e1` stays the anode, and the new
  `e2` is the cathode, so a circuit can use the bench detector. Its 1D symbol
  no longer tilts in a bench layout.
- A short straight, L, smooth or manhattan route between parts close together
  ran past a port and folded back over its own lead, up to 5 um. The lead now
  ends where the path can turn, so the route leaves and enters each port
  face-on.
- The docs circuit (`02-tia.py`) reads in 2D as well as in 1D: labels clear of
  the parts, no wire over Ground, and light fed to the photodiode by a grating
  coupler. The coupler faces the photodiode (`angle=180`); it pointed away, and
  its waveguide ran back through it.
- `check_figure` names a waveguide that meets an optical port from behind,
  which means the part faces away from its route.
- In the 1D view, a wire turns square at each corner, as in a circuit drawing;
  a waveguide keeps its bend. This holds in the SVG, the TikZ export and the
  editor.
- The 1D view lines a circuit up as a circuit drawing does. A part moves up to
  25 points so that its wire runs straight or turns once, where nothing is in
  its way; the optical line and parts placed by hand stay. A wire in line drops
  the steps of its 2D route unless it would then cross a link. Two wires on one
  port may share a run, as one node. A driver's own contact sits over the port
  it serves. In the test scenes, wire corners past the fewest fell from 51 to
  22 and sideways jogs from 38 to 13, with no new crossing.
- A dot marks each join of a node in the 1D view, as in KiCad: where three or
  more branches of one node meet (a T, or two wires that leave one pin
  apart). Wires that only cross carry no dot. `junctions(schematic)` gives the
  points; the SVG, the TikZ export and the editor draw them.
- The Inspector offered an inset a colour and an opacity, and the server
  refused both. An inset now takes `opacity`, which fades it as one layer, and
  the Inspector shows no colour for it.
- The editor kept large inset drawings in memory, so a server restart broke
  undo and the drawings of older steps. They are now files in the workspace
  folder (`.fragments/`); the server removes one unused for 14 days, then the
  oldest past 256 MiB.
- After a restart the editor opened the default workspace, and an undo from a
  tab that still showed another workspace wrote over it. The editor now opens
  the newest workspace, and each change from a tab names its workspace
  (header `X-Optodraw-Workspace`); a change for another workspace gets 409 and
  writes nothing. A request without the header (a script, a test) passes.
- The periscope in 3D is built like the hardware: a post beside the beam with
  a right-angle cube mount at each fold, the mirror on the cube's 45 deg
  diagonal and the body behind it, clamped to the post. A beam through a
  periscope now turns on both mirror centres (it ran straight from port to
  port), and the mirrors sit at the scene's beam height.
- `MZM(splitter="branch_coupler")` animation paths start at its `o1` port and
  run through the drawn input Y-branch. They used to start 8 µm away, at the
  input coupler of the two-coupler variant, which this variant does not draw.
- `BeamSplitter`, `Filter`, `Grating`, and `Objective` constructors now share
  the common free-space initializer, so they honor `base_mount` and
  `mount_height` like the rest of the optics family. No signature changes.

## [0.9.0] — 2026-08-10 (internal, never published)

First public release. The version resets to 0.9.0: the 3.x numbering described an
internal API generation that was never published, and a first public release
should say plainly that it is pre-1.0.

### Added

- **Free-space ray tracing**: physical mode traces real interface segments, so
  apertures clip, misses fly on, and lenses focus by hit height. Sources emit ray
  bundles, with `divergence_deg` for a fan and `show_envelope` for the beam cone.
- **Prisms and gratings as real surfaces**: vector Snell with dispersion at every
  drawn face, and the grating equation at any incidence.
- **Instruments**: oscilloscope, SMU, OSA, DAQ, VNA, FPGA board, laser driver,
  power meter, waveform generator, vacuum pump, computer — wired to chips with
  round cables in 3D.
- **Periscope** and a **cryostat** with optical-access windows and a cold-finger
  sample stage.
- **Editor**: simulation panels, layout generators, animation and publication
  export, design checks, a command palette, and free click-to-click routing.
- `layout.align_ports` / `chain_ports` — place a part in front of the port that
  feeds it, the way you would by clicking.

### Changed

- Mounting hardware is proportioned from measured parts: a breadboard hole sits
  under one Ø1in optic, and posts, holders and stage risers scale with the optics
  they carry. All of it had been about 4x too small.
- Routes serialize as the two PORTS they join, so links follow their components
  the way editor-drawn ones always did.
- Dragging snaps the MOVEMENT rather than the absolute position, so a part keeps
  the alignment it was placed with.
- Beams are drawn BETWEEN parts: the span inside a component is a gap, not a line
  across its art.

### Fixed

- Scenes without a `trace_mode` (presets, saved files) traced as schematic and
  collapsed ray bundles to a single line.
- Manhattan routes could emit diagonal legs when pushed clear of a device.
- Rotated optics stood off their own posts.
- A falling periscope used a rising one's mirror angles and hung its exit below
  the table.

### Also in this release

- `animate_fiber_alignment` teaching recipe with Gaussian-overlap coupling-loss captions.
- Structural xsection bundle validation tests and stricter optional open-PDK integration env handling.
- Three.js lighting presets, publication render quality, and optional post-processing for HTML exports.
- MCP `optodraw_compile_physics_animation` now dispatches through `optodraw.core.physics_compiler` and returns a timeline summary.
- On-chip IO, active, and compact electronics components now draw from schematic dimension tables by default while keeping ports and `physical_spec()` physical.
- Paper publication presets now render HTML with the Three.js publication lighting/quality pipeline.

## [3.0.0a1] — 2026-05-22 (internal, never published)

### Added

- Schematic-first on-chip rendering: physical µm constructors, `schematic_dims()`,
  `physical_spec()`, and `render_physical` toggle.
- `optodraw.gds.xsection` process engine with YAML stacks, strip layouts, and bundle export.
- Multi-format publication bundles (`build_publication_bundle`) with captions, manifests,
  and optional cross-section attachment.
- Teaching animation recipes (`animate_mzm_mechanism`, `animate_ring_coupling`, and related
  helpers in `animation_recipes`).
- Blender and Three.js named camera/material presets and layer legends for chip renders.
- `optodraw.layout.chip_builder` helpers (`build_ring_filter`, `build_mzm_mesh`).

### Changed

- On-chip constructor args are always physical µm; schematic exaggeration is draw-only.
- Registry/catalog metadata includes `schematic_default`, `supports_render_physical`,
  and `supports_physical_spec`.

### Migration

- See `docs/migration_3.0.md` (removed with the MkDocs site) for upgrade notes from 2.x alphas.
