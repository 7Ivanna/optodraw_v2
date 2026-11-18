Most work needs only `import optodraw`. The [part catalogue](/reference/parts/) lists every part.

## Scenes

| Name | What it is |
|---|---|
| `Scene` | The drawing: parts, beams, routes and their positions |
| `Component` | The base class of every part |
| `Group` | Parts that move together |
| `Port` | A named place where a beam, waveguide or wire attaches |
| `Beam` | Free-space light through a list of parts or ports |
| `Note` | Free text on a figure, or beside a beam with `Note.on` |
| `FlipMirror` | A mirror up in the beam, down out of it, or `both` for the two routes |
| `Route`, `WaveguideRoute`, `FiberRoute` | Guided light between two ports |

## Scene methods

| Method | Does |
|---|---|
| `add(part)` | Places a part and returns it |
| `route((a, "o1"), (b, "o1"), kind=...)` | Routes a waveguide, fibre or wire between ports |
| `route_bundle(ports1, ports2)` | Routes many links side by side |
| `arrange_line(...)`, `arrange_grid(...)` | Places parts in a row or a grid |
| `render_svg(path)` | 2D drawing as SVG |
| `render_tikz(path)` | 2D drawing as TikZ for LaTeX |
| `export_figure(path, width_mm=...)` | 2D drawing as SVG, PDF and PNG |
| `lens_beam(*stops, width=..., mm_per_unit=...)` | A beam whose drawn width follows its lenses |
| `render_threejs(path)` | Interactive 3D page |
| `render_3d_image(path)` | 3D image as PNG |
| `render_gif(path)`, `render_video(path)` | Animation |
| `preview()` | 2D and 3D view in a notebook |
| `save(path)`, `load(path)` | The scene as JSON |

## Find parts

```python
from optodraw import describe_component, list_components

list_components(platform="on_chip")
describe_component("MicroringResonator")
```

`component_catalog()`, `list_component_categories()` and `list_material_presets()` answer the same kind
of question.

## Build larger layouts

`build_mzm_mesh(...)` builds a grid of modulators with its routes; `build_microring_weight_mesh(...)` a
grid of weight banks; `build_ring_filter(...)` a ring filter. Each returns the scene and its parts by name.
`build_preset(name)` returns one of the <!-- value: preset-count --> ready scenes.

## Trace light

`trace_bundle(scene, (laser, "out"))` and `trace_branched(...)` in `optodraw.core.raytrace` trace rays
through the optics. `scene.trace_paraxial_beam(...)` propagates a Gaussian beam with ABCD matrices.
See [Ray tracing](/ray-tracing/).
