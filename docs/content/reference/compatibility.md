optodraw needs Python 3.10 or newer. The core needs only NumPy and drawsvg; everything else is an extra.

## Extras

| Extra | Adds |
|---|---|
| `gui` | The editor |
| `desktop` | The editor in its own window |
| `three` | Interactive 3D in notebooks |
| `gds` | GDS import, 3D export and cross-sections |
| `gif` | Animated GIFs (needs the Cairo library) |
| `manim` | MP4 video |
| `mcp` | The AI assistant server |
| `notebook` | Notebook widgets |
| `optiland` | Optiland as a ray tracing engine |
| `all` | Everything above |

## What stays stable

The names listed in `optodraw.__all__` are the public API. A test keeps a snapshot of them and of their
arguments: removing a name or an argument fails the test; adding one does not.

- **Stable**: `Scene`, `Component`, `Group`, `Port`, `Beam`, `Route`, the render functions, scene save and
  load, and the part catalogue functions. Their names and arguments do not change.
- **Evolving**: every part class and physics helper. Arguments may gain defaults. A renamed name keeps
  working, with a warning, until the release its notice names.

## Other tools

- **Optiland** can trace the rays; optodraw draws them. Install the `optiland` extra.
- **gdsfactory** parts and PDKs import as GDS.
- **Blender**: export a GLB and a render script from the 3D view.
