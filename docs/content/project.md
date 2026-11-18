optodraw is free and open source under the BSD-3-Clause license, for research, teaching and commercial
work.

## Cite it

If optodraw helps with published or public work, please cite it. The repository has a `CITATION.cff`
file, so GitHub shows a "Cite this repository" button. A paper about the design is in preparation.

The [examples](/examples/) redraw figures from published papers. Cite those papers for the science and
optodraw for the drawing.

## How it is built

- One Python package holds the scene graph, the parts, the renderers, the GDS tools and the editor's
  server. The core needs only NumPy and drawsvg.
- The editor is a web front end over a small FastAPI server. The desktop app is the same editor in a
  native window. The core never imports the editor.
- The scene is a JSON spec. The editor, the Python API and the AI assistant all read and write it.

## Contribute

Report a problem or propose a change on GitHub. Adding a part to optodraw follows
[Your own parts](/guides/your-own-parts/). Changes are listed in the changelog.
