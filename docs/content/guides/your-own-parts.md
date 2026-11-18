A part is SVG art with marked ports, or a Python class. Either way it works like every other part: in
beams and routes, in the editor's palette, in 1D, 2D and 3D, and in saved scenes.

## From SVG art

Mark each port in the SVG with `id="port:<name>"` on a circle, a line or a group; `data-orientation` sets
its direction in SVG degrees. The importer removes the marks from the art.

```python
from optodraw import PartLibrary, import_svg_part, load_part, save_part

svg = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 20">
  <rect x="5" y="5" width="30" height="10" fill="none" stroke="black"/>
  <circle id="port:in" cx="5" cy="10" r="1" data-orientation="180"/>
  <circle id="port:out" cx="35" cy="10" r="1" data-orientation="0"/>
</svg>"""
Coupler = import_svg_part("user:lab/Coupler", svg)
part = Coupler(center=(0, 0), scale=2)
save_part(Coupler, "coupler.odpart")      # a checked file; loading it runs no code
again = load_part("coupler.odpart", library=PartLibrary())
```

The editor's new-part dialog does the same and keeps the part in My parts. A part with no 3D model
extrudes its outline, marked as schematic.

## 1. The class and its ports

Free-space optics go in `optodraw/components/optics/`, chip parts in `optodraw/components/onchip/`,
electrical parts in `optodraw/components/electronics/`. `ports()` returns named `Port` objects with a
kind (`free_space`, `optical`, `electrical` or `thermal`), a direction and a width. Every port the drawing
shows must exist here: routes attach to ports, never to the art.

## 2. The drawings

- **1D**: `symbol_1d()` names the part's symbol and its parameters. The symbols live in
  `optodraw/symbols/`. A symbol is a real line drawing in black on white; a labelled box is not a symbol.
  Every connection ends on a named port.
- **2D**: `geometry_2d()` returns shapes from the shared set (`rect`, `line`, `circle`, `path`,
  `polygon`, `text`, `group` and others).
- **3D**: `geometry_3d()` returns solids (`box`, `cylinder`, `sphere`, `torus`, `extruded_polygon`,
  `lathe_profile`, `tube_path`). An unknown shape shows as a magenta box and fails a strict export.

## 3. Save and load

`scene.to_spec()` and `scene_from_spec()` must rebuild the part with the same parameters.

## 4. The registry

Call `register()` in `optodraw/registry.py` with the name, the class, the category, the platform, a
description and the parameters. The catalogue, the editor's palette and the AI assistant read it.

## 5. Check it

Add the part to a family test: render SVG, TikZ and GLB, check that the capability report is empty, and
round-trip the spec. Then look at it: the 1D symbol, the ports and their directions at palette size and
at paper size. A passing test does not prove that a symbol reads well.
