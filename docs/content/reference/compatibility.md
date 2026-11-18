optodraw needs Python 3.10 or newer, on Windows, macOS or Linux. `pip install optodraw` brings the editor, GDS
import with 3D and cross-sections, PNG, GIF and PDF export, interactive 3D, the AI assistant server and the
notebook widgets. PNG and GIF need no system library. PDF uses the Cairo library where it is installed, else
Chrome or Edge. gdsfactory needs Python 3.11 or newer.

## Extras

| Extra | Adds |
|---|---|
| `desktop` | The editor in its own window |
| `manim` | MP4 video (needs Cairo, Pango and FFmpeg) |
| `sax` | Circuit models for SAX (brings JAX) |
| `all` | Everything above |

## What stays stable

The names listed in `optodraw.__all__` are the public API. A test keeps a snapshot of them and of their
arguments: removing a name or an argument fails the test; adding one does not.

- **Stable**: `Scene`, `Component`, `Group`, `Port`, `Beam`, `Route`, the render functions, scene save and
  load, and the part catalogue functions. Their names and arguments do not change.
- **Evolving**: every part class and physics helper. Arguments may gain defaults. A renamed name keeps
  working, with a warning, until the release its notice names.

## Other tools

- **gdsfactory** parts and PDKs import as GDS.
- **Blender**: export a GLB and a render script from the 3D view.
