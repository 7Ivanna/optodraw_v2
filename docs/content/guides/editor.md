The editor draws the same scenes without code. It runs in your browser, or in its own window as a desktop
app. A scene made in the editor is the same scene the Python package makes: you can open it in either.

## Start it

```bash
pip install "optodraw[gui]"
optodraw-gui                 # opens your browser
optodraw-gui --desktop       # its own window (needs the "desktop" extra)
optodraw-gui --port 9000     # another port
```

It serves on port 8000, or on the next free port. It is a local app for one user. Do not expose it to a
public network.

## Draw

- **Palette** (left): search a part and click it to add it. Presets start a whole scene.
- **Canvas**: drag to move, the round handle to rotate, Shift+click to add to a selection, Space+drag to
  pan, the wheel to zoom. The dashed frame is the export frame.
- **Route**: click a port, then another port. Free-space ports give a beam; chip ports give a waveguide
  with real bends. Routes follow the parts when you move them.
- **Trace**: every source sends a live bundle of rays. Mirrors fold it, lenses focus it, splitters branch
  it, detectors stop it. Move an optic and the light follows.
- **Links**: type connections as text, for example `laser.out -> lens.in -> pd.in`.
- **Inspector** (right): every parameter of the selected part, its ports, its look and its 3D mount,
  including its beam height.
- **Code** (right): the scene as YAML text, with the keys of the saved file. A canvas edit changes the
  text. Ctrl+Enter (Cmd+Enter) applies a text edit, and an error names its line. The right panel folds.
- **Insets**: double-click a scene inset, or click Open scene, to edit its scene. Back draws the inset
  again.
- **Figure** (palette): adds an inset. A corner handle resizes it.
- **Command palette**: press Ctrl+K (Cmd+K on a Mac) to find any action or part.

## Views

The view switch shows the scene as a 1D schematic, a 2D layout or a 3D scene. All three use the same
parts, ports and links. A selected GDS part shows its layers, a layer stack and a cross-section tool.

## Save and export

Save writes the scene as JSON; Open reads it back. Export gives an SVG, TikZ for LaTeX, a figure bundle
for a paper, a 3D image, model or page, or a GLB with a Blender script. In 3D, the View menu sets the camera,
the world, the labels and fullscreen, and its Photoreal render draws a studio image.
