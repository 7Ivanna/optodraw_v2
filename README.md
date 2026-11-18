<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/Acceluma/optodraw/main/docs/assets/branding/optodraw-lockup-dark.svg">
  <img src="https://raw.githubusercontent.com/Acceluma/optodraw/main/docs/assets/branding/optodraw-lockup.svg" width="320" alt="optodraw">
</picture>

**Draw a bench or a chip once, in Python or in the editor. Get the paper figure, the 1D schematic, the 3D scene
with moving light, and the chip's layout and cross-sections.**

</div>

| Figures | Light and chips | Tools |
|---|---|---|
| ![Advanced LIGO, 2D](https://raw.githubusercontent.com/Acceluma/optodraw/main/docs/public/media/ligo-2d.png) | ![A light pulse in coupled rings, the 3D light player, time slowed and illustrative](https://raw.githubusercontent.com/Acceluma/optodraw/main/docs/public/media/rings-light.gif) | ![The editor, with the inspector](https://raw.githubusercontent.com/Acceluma/optodraw/main/docs/public/media/editor-2d.png) |
| ![Homodyne receiver, 1D](https://raw.githubusercontent.com/Acceluma/optodraw/main/docs/public/media/homodyne-1d.png) | ![Cross-section of a PN phase shifter](https://raw.githubusercontent.com/Acceluma/optodraw/main/docs/public/media/xsection.png) | ![A GDS file in the editor's Layout view](https://raw.githubusercontent.com/Acceluma/optodraw/main/docs/public/media/editor-layout.png) |
| ![A universal nine-mode interferometer: 36 MZIs on a chip, 3D](https://raw.githubusercontent.com/Acceluma/optodraw/main/docs/public/media/mesh-3d.png) | ![The same cut as an SEM-like image, marked as a render](https://raw.githubusercontent.com/Acceluma/optodraw/main/docs/public/media/xsection-sem.png) | ![Beam expander, traced rays](https://raw.githubusercontent.com/Acceluma/optodraw/main/docs/public/media/expander-rays.png) |

Each figure redraws a published one. The [example cells](https://github.com/Acceluma/optodraw/blob/main/docs/examples/) name the papers.

## What it does

| Area | What you get |
|---|---|
| **Figures** | Benches and chips in 1D, 2D and 3D, with plots and pictures as insets: SVG, TikZ or a studio 3D image. |
| **Editor** | The same scenes without code, in the 1D, 2D, 3D and Layout views. |
| **Light** | Light moves through the bench or the chip, live in 3D or in a video of a camera tour. |
| **Chips** | Rings, modulators, couplers and pads on a die, with waveguide routes that bend like real ones. |
| **GDS** | A GDS file with its layer stack or KLayout technology, in 3D and in cross-sections. |
| **Agents** | Skills and an MCP server for Claude Code, Codex and other agents. |

## Install

```bash
pip install optodraw   # the editor, GDS files, 3D and every export
optodraw-gui           # open the editor
```

It runs on Windows, macOS and Linux. `[all]` adds video, a native window and SAX.

## Quick start

```python
# The 8.9 times beam expander of Curd et al., Methods 88, 37-47 (2015), Fig. 1A (1 unit = 4 mm)
from optodraw import Beam, Laser, Lens, Scene

scene = Scene(title="Beam expander", platform="free_space")
laser = scene.add(Laser(center=(-78, 0), wavelength=488, label="488 nm laser"))
lens1 = scene.add(Lens(center=(-58, 0), focal_length=45 / 4, aperture=6, label="f = 45 mm"))
lens2 = scene.add(Lens(center=(53, 0), focal_length=400 / 4, aperture=24, label="f = 400 mm"))
scene.add(Beam.through(laser, lens1, lens2, wavelength=488))
scene.fit_frame(margin=8)
scene.render_svg("expander.svg")      # the 2D figure; render_threejs("expander.html") gives 3D
```

![The beam expander](https://raw.githubusercontent.com/Acceluma/optodraw/main/docs/public/media/quickstart.png)

## Use it with an AI agent

The package ships agent skills: instructions that Claude Code, Codex and other agents read first.

| skill | use it for |
|---|---|
| `optodraw-figure` | a paper figure of a bench or a chip |
| `optodraw-layout` | chip floorplans and routes that are right, not only clean |
| `optodraw-component` | a part of your own, in 1D, 2D and 3D |
| `optodraw-gds-3d` | a GDS file in 3D, with a layer stack and cross-sections |
| `optodraw-animation` | light that moves through a setup or a chip |

```bash
optodraw-skills install             # into ~/.claude/skills and ~/.agents/skills
optodraw-skills install --project   # into ./.claude/skills and ./.agents/skills
```

Agents that speak MCP can use the `optodraw-mcp` server.

## Learn more

- [The editor](https://github.com/Acceluma/optodraw/blob/main/docs/content/guides/editor.md): every view, menu and export.
- [GDS files](https://github.com/Acceluma/optodraw/blob/main/docs/content/gds.md): layer stacks, KLayout technologies and the Layout view.
- [Moving light](https://github.com/Acceluma/optodraw/blob/main/docs/content/animation.md): GIFs, videos and the live 3D player.
- [AI agents](https://github.com/Acceluma/optodraw/blob/main/docs/content/guides/ai.md): the skills and the MCP server.
- [API reference](https://github.com/Acceluma/optodraw/blob/main/docs/content/reference/api.md): every public name.

## Cite and license

Please cite optodraw with [`CITATION.cff`](https://github.com/Acceluma/optodraw/blob/main/CITATION.cff).
optodraw is free and open source under the [BSD 3-Clause License](https://github.com/Acceluma/optodraw/blob/main/LICENSE).
It grew from Alex Tait's first drawsvg package.
