optodraw imports a GDS layout and shows it in 2D, in 3D with a layer stack, and in cross-section.

## Import

```python
from optodraw import GDSModel, Scene

scene = Scene(platform="on_chip")
chip = scene.add(GDSModel("my_chip.gds", cell_name="TOP", material_preset="silicon"))
scene.render_svg("chip.svg")
scene.render_threejs("chip.html")
```

GDS import needs the `gds` extra. It does not run in the browser, so this page has no live cell.

## Layout view

In the editor, the Layout button shows an imported GDS as KLayout does: the wheel zooms at the cursor, a drag
pans, and the panel holds the cell tree and the layers in the part's colours. M draws a ruler. The view runs
[GDS Lens](https://github.com/EthanLowenthal/GDS-Lens) (MIT), which optodraw carries, so it needs no internet.

In a notebook, `chip.layout_view()` shows the same view. `layout_html` writes it as one HTML file:

```python
from optodraw.gds import layout_html

layout_html("my_chip.gds", cell="TOP", stack="gdsfactory_generic", filename="my_chip_layout.html")
```

The file opens from disk, with no web server (tested in Chrome). If another browser does not draw it, run
`python -m http.server` in its folder.

## Layer stacks

A layer stack gives each GDS layer a height (`zmin`) and a thickness, so the 3D view and the cross-section
are physical. optodraw bundles stacks for open PDKs (SiEPIC EBeam, gdsfactory generic, Cornerstone, LiNbO₃
`lnoi400`, LiTaO₃ `ltoi300`) and from papers (InP `inp_generic`, BaTiO₃ `bto_generic`). A stack with no oxide
(InP) gives `substrate`, `films` and `fill` in place of `oxide:`. For a
foundry PDK under NDA, fill in a copy of `_template.yaml` and load it privately.

```python
from optodraw.gds.parsers import load_layer_stack

stack = load_layer_stack("my_process.yaml")
```

Layers with `material: air` are openings, carved out of the oxide. A layer with no height shows "No height
assigned" in the inspector until you type its th and z; the 3D view and the GLB leave it out, and a note in the
3D view names it. A layer with no material says so too.

`load_layer_stack("klayout/tech.lyt")` reads a KLayout technology: colours and names from the `.lyp` that the
`.lyt` names, heights from the plain input layers of `d25/*.lyd25`. A layer that the script derives from other
layers is skipped with a warning. In the editor, Attach technology folder sends only those three kinds of file;
a `.zip` of the folder also works.

## Cross-sections

`cross_section(gds, stack, cut)` cuts along any straight line and runs the process the stack implies, drawn as
a schematic or a cut 3D slab. See [Cross-sections](/guides/cross-sections/). In the editor, draw the cut with
the Layout view's ruler and press Cut along ruler, or scan a vertical cut.

## Export

`scene_to_glb(scene)` in `optodraw.exporters.glb` returns a GLB for other 3D tools;
`export_blender_script` writes a Blender scene and a render script.
