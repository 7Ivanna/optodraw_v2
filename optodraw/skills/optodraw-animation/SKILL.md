---
name: optodraw-animation
description: Use when asked to animate light in an optical setup, a fiber link or a photonic chip with optodraw (pulses travelling through a circuit, a wavelength, angle or heater sweep with a live plot, a step-by-step explanation for a talk or a lecture), or when an animation must stay physically consistent. Covers the physics-first animation engine for 1D and 2D views (light follows the drawn beams and routes, with real delays, polarization and interference), its Manim-style actions, sweeps and plots checked against the expected formula, the strict checks, the presets, the 3D page with its two looks and its tour, the tour video, and what to give the user today.
---

# optodraw-animation

Optodraw's animation engine computes the light first and draws it second.
Light follows the beams and routes of the scene, with the delay of each path
(length times group index), a Jones vector for its polarization, and coherent
sums where paths meet. So an animation is only as right as its scene: an
output port with nothing on it, a part with no behaviour, or a loop with gain
stops the build.

Every python block in this file runs in order, as one script, in the optodraw
test suite. Build and check the scene first with `optodraw-figure` (free
space) or `optodraw-layout` (chip).

## The three ways optodraw animates

| path | gives | use it for |
|---|---|---|
| the engine, `optodraw.animation_engine` | a physics-checked timeline in 1D or 2D, with sweeps and live plots, as JSON (`anim.dumps()`) | the physics, the story, the numbers |
| `scene.render_threejs("f.html")` | a 3D page with a bottom bar; its Light menu (or `animate=True`) plays the light from the engine, in two looks, with a tour | something to show today, in 3D |
| `scene.render_tour_video("t.mp4")` | the tour of the 3D page as MP4 (ffmpeg) or WebM | a talk, a slide, a social post |
| `scene.render_video(...)` (needs Manim), `scene.render_gif(...)` | a video, or a GIF of the beams being drawn | a slide or a social post |

The 3D page and the tour video now come from the engine, so their light is
the engine's light. The engine's sweeps and plots stay data (`anim.dumps()`);
the page does not draw them. Tell the user which output they have.
`optodraw.animation` is the older timeline; do not import it for the engine.
`scene.render_video` is the Manim method; the tour video is
`render_tour_video`.

## The method

1. **The scene is final and checked**: every optical output ends on a
   detector, a `BeamDump` or a `Terminator`; unused inputs may stay open.
   Binding an animation and then editing the scene raises "the scene changed
   after animation binding".
2. **Every part has a behaviour**: the engine models about 90 part types.
   `behaviours.registered_types()` lists them; a part you made needs one
   (`optodraw-component`, "Make it act on light").
3. **Write the story as sections**, one idea each, ended by `click()`.
4. **Build with `strict=True`**: an open output or a missing behaviour stops
   the build and names the part.
5. **Check every plot against the formula you expect**, and say which formula.

## A worked lecture: an on-chip Mach-Zehnder

```python
import math

import optodraw
from optodraw.animation_engine import Animation, Fit, Flow, Indicate, Plot, Quantity, Sweep, Timeline, Write, Zoom
from optodraw.animation_engine.behaviours import registered_types

chip = optodraw.Scene(title="Thermo-optic MZI", width=360, height=160, platform="on_chip")
laser = chip.add(optodraw.OnChipLaser(center=(-170, 7), label="Laser"))
mzi = chip.add(optodraw.MZI(center=(0, 0), label="MZI"))             # o1, o2 west; o3, o4 east; heater
bar = chip.add(optodraw.OnChipPhotodetector(center=(140, 40), label="PD o3"))
cross = chip.add(optodraw.OnChipPhotodetector(center=(140, -40), label="PD o4"))
chip.route((laser, "o1"), (mzi, "o1"), kind="waveguide", path_type="smooth")
chip.route((mzi, "o3"), (bar, "o1"), kind="waveguide", path_type="smooth")
chip.route((mzi, "o4"), (cross, "o1"), kind="waveguide", path_type="smooth")
chip.fit_frame(margin=12)                             # the scene is final before the animation binds
assert {"MZI", "OnChipLaser", "OnChipPhotodetector"} <= set(registered_types())

anim = Animation(chip, view="2d", mode="pulse", strict=True)
anim.play(Indicate(laser), Write("1550 nm pulse", near=laser)).click()
anim.auto().click()                                   # a pulse through both arms, each at its own delay
anim.play(Zoom(mzi, factor=1.5), Fit()).click()
anim.play(Flow(mode="cw")).click()                    # steady light before the sweep
anim.play(Sweep("heater:mzi1", 0, 40, seconds=4, samples=17),
          Plot(Quantity(bar), against="heater:mzi1"))
data = anim.to_json()
assert Timeline.from_json(data).to_json() == data

plot = data["assets"]["plot:1"]
expected = [math.sin(math.pi * p / 40) ** 2 for p in plot["x"]]     # pi phase at 20 mW
assert max(abs(a - b) for a, b in zip(plot["y"], expected)) < 1e-6
print([track["type"] for track in data["tracks"]], round(data["duration"], 1), "s")
```

- With no heater power the MZI sends all light to the cross port `o4`; the
  heater adds a phase of pi P / 20 mW, so `o3` takes sin^2(pi P / 40) and `o4`
  takes cos^2(pi P / 40).
- The two outputs are 14 um apart: fan them out before their detectors, or the
  two detectors overlap (`optodraw-layout`, routing rule 5).
- The heater and detector pads stay unwired here because the animation is
  about light; wire them (`optodraw-layout`) when the chip is also a figure.
- `to_json()` returns the timeline as a dict; `dumps()` returns the same as a
  string for a file.

## Something to show today

```python
import matplotlib

matplotlib.use("Agg")                                 # files only, never a window
import matplotlib.pyplot as plt

chip.render_svg("mzi_chip.svg")                       # the device
fig, ax = plt.subplots(figsize=(3.4, 2.4))
ax.plot(plot["x"], plot["y"], color="#0072B2")
ax.spines[["top", "right"]].set_visible(False)
ax.set_xlabel("Heater power (mW)")
ax.set_ylabel("Power at o3 (norm.)")
fig.tight_layout()
fig.savefig("mzi_sweep.svg")
fig.savefig("mzi_sweep.png", dpi=300)
chip.render_threejs("mzi_3d.html", animate=True)      # the 3D page, its light on from the start
chip.render_threejs("mzi_field.html", look="field", animate=True)   # the steady-state field
```

The device SVG and the sweep plot make a correct slide now. The device SVG is
a still picture with no light on it. The 3D page plays the light in the
browser: it shows neither the sweep nor the plot. The GIF (`render_gif(..., mode="beam_trace")`)
only draws the beams step by step: it shows no delay, power or sweep.

## The 3D page: looks, tour, video

- **Light look**: glowing pulses inside the drawn guides. Brightness is
  power. Speed follows the group index. This is the default.
- **Field look**: the steady-state field, with crests, mode shape and
  interference. It also shows heat maps from driven heaters and the RF field
  between modulator electrodes.
- **Colour**: one wavelength that is not visible is white (Light) or red,
  white and blue (Field). Several wavelengths each take a colour. A visible
  laser takes its true colour.
- **Start**: the light is off until the user presses Light or you pass
  `animate=True`. The world turns navy while it plays. Captions on the page
  state every scaled quantity: read them to the user.
- **Device bodies**: light never crosses a device body or jumps a coupling
  gap. Every chip device draws its own internal paths. MMI, star and AWG slabs
  are regions. A coupler draws one field per guide.
- **Heaters and rings**: a heater delays the light and shifts its phase. Rings
  start on resonance (captioned).
- **Settings**: `render_threejs(look=, params=, inputs=, tour_drives=)`. The
  editor's Light section (heater mW, drive V, ring tuning in linewidths)
  stores values in `metadata.animation.params`.
- **Tour drives**: `tour_drives=True` puts the drive tables of the tour's
  driven stops in the page. Play tour then swings each drive at its stop.
  The tables are slow to build, so the default is `False`: a saved page's
  Play tour keeps the drives as set and says so. The video and the editor's
  Play tour always swing them.
- **Tour**: stops at each device where something happens, in the order the
  light arrives. Time slows at a stop. At a driven stop the drive steps once
  per pulse. Press Play tour in the Light menu. A tour saved in
  `metadata.animation.tour` wins over the automatic one
  (`optodraw.animation3d.tour`: `Stop`, `Tour`, `auto_tour`).
- **Video**: the tour as a file. It needs Chrome, Chromium or Edge.

```text
scene.render_tour_video("tour.mp4", look="light", tour="auto", width=1920, height=1080, fps=30)
```

MP4 needs ffmpeg and is rendered frame by frame, so the same scene gives the
same video. Without ffmpeg the video is WebM, recorded in real time. The video
takes a while: start with a small `width` and `height`. The editor has Record
video (a job with progress) and the page has Record video (WebM, in real time).

## A ring: find the resonance, then sweep it

A ring's resonance is narrow (about 0.4 nm here): scan coarsely to find a dip,
then sweep a window around it with at least 20 samples across the dip.

```python
ring_chip = optodraw.Scene(title="All-pass ring", width=300, height=120, platform="on_chip")
ring_laser = ring_chip.add(optodraw.OnChipLaser(center=(-140, -13.6), label="Laser"))
ring = ring_chip.add(optodraw.MicroringResonator(center=(0, 0), label="Ring"))   # all-pass: o1 in, o2 out
ring_pd = ring_chip.add(optodraw.OnChipPhotodetector(center=(120, -13.6), label="PD"))
ring_chip.route((ring_laser, "o1"), (ring, "o1"), kind="waveguide", path_type="smooth")
ring_chip.route((ring, "o2"), (ring_pd, "o1"), kind="waveguide", path_type="smooth")
ring_chip.fit_frame(margin=12)

coarse = Animation(ring_chip, mode="cw", strict=True).auto().click()
coarse.play(Sweep("wavelength", 1545, 1555, seconds=2, samples=401), Plot(Quantity(ring_pd), against="wavelength"))
scan = coarse.to_json()["assets"]["plot:1"]
dip = scan["x"][min(range(len(scan["y"])), key=scan["y"].__getitem__)]
fine = Animation(ring_chip, mode="cw", strict=True).auto().click()
fine.play(Sweep("wavelength", dip - 0.4, dip + 0.4, seconds=4, samples=161),
          Plot(Quantity(ring_pd), against="wavelength"))
window = fine.to_json()["assets"]["plot:1"]
a, r = 0.99, math.sqrt(1 - 0.1)                       # round-trip amplitude and self-coupling (defaults)
deepest = ((a - r) / (1 - a * r)) ** 2                # the all-pass dip depth
assert abs(min(window["y"]) - deepest) < 0.01
print(f"resonance near {dip:.2f} nm, dip {min(window['y']):.3f}, expected {deepest:.3f}")
```

`MicroringResonator` is an all-pass ring (`o1` in, `o2` out on the bus);
`build_ring_filter()` gives an add-drop ring with grating couplers. The
full transmission is T = (a^2 - 2ar cos phi + r^2) / (1 - 2ar cos phi + (ar)^2)
with phi = 2 pi (lambda - lambda0) / FSR; read lambda0 and the FSR from two
dips of the coarse scan.

## Sweeps, parameters and actions

Parameters are named `<kind>:<part id>`. A part id is the lower-case type
name plus a counter in scene order (`mzi1`, `polarizer1`).

| parameter | meaning |
|---|---|
| `wavelength`, `wavelength:<id>` | source wavelength in nm |
| `angle:<id>` | source polarization, polarizer or wave plate angle in degrees |
| `width:<id>` | pulse width in ps |
| `heater:<id>` | heater power in mW on a phase shifter, ring or MZI (pi at 20 mW) |
| `phase:<id>`, `phase:<id>:arm1` | phase in radians |
| `drive:<id>` | MZM drive |
| `attenuation:<id>` | attenuator loss in dB |
| `power_coupling:<id>`, `round_trip_amplitude:<id>` | ring coupling and round-trip amplitude (defaults 0.1 and 0.99) |

- `Set(param, value)` changes a parameter at a section boundary; `Sweep`
  moves it over time. A sweep cannot overlap a pulse `Flow`: put
  `Flow(mode="cw")` in its own section first, as above. One sweep feeds one
  `Plot`.
- There is no laser on/off switch: dim the light with `attenuation:` or
  detune a ring with `heater:`.
- Actions: `Flow`, `Create`, `FadeIn`, `FadeOut`, `Indicate`, `Dim`, `Label`,
  `Arrow`, `Write(text, near=part)`, `Transform`, `MoveAlong`; camera `Zoom`,
  `Pan`, `Fit`, `Morph(to="1d")`; timing `Wait`, `Click`, `Sequence`,
  `Lagged`. Each takes `seconds` and `easing` (`smooth`, `linear`,
  `there_and_back`, `ease_in`, `ease_out`). Light styles: `photons`,
  `packets`, `beam`, `wave`, `bits` (`bits` needs an electrical signal).

## Free space and presets

```python
from optodraw import Beam, Laser, Photodiode, Polarizer, Scene

bench = Scene(title="Malus", width=200, height=60, platform="free_space")
source = bench.add(Laser(center=(-60, 0), wavelength=633, label="Laser"))
polarizer = bench.add(Polarizer(center=(0, 0), label="Polarizer"))
detector = bench.add(Photodiode(center=(60, 0), label="PD"))
bench.add(Beam.through(source, polarizer, detector, wavelength=633))
malus = Animation(bench, mode="cw", strict=True).auto().click()
malus.play(Sweep("angle:polarizer1", 0, 90, seconds=3, samples=7),
           Plot(Quantity(detector), against="angle:polarizer1"))
power = malus.to_json()["assets"]["plot:1"]["y"]
assert abs(power[0] - 1.0) < 1e-3 and power[-1] < 1e-2          # cos^2 from 1 to 0
print(sorted(optodraw.presets.PRESETS))
```

A preset may leave an output open on purpose (`mzm_mesh_chip` does): add a
detector there before a strict build. A chip preset fed
by a fibre needs `anim.input(part, port, wavelength_nm=...)` on each input.

## When the build stops

| message | what it means |
|---|---|
| `light leaves unconnected port <p>` | an output with nothing on it: add a detector or a `Terminator` |
| `no behaviour yet for <type>` | the engine cannot model that part: pick another or give it one |
| `the scene has no light source` | add a source or an `anim.input(...)` |
| `port has N connections; light cannot choose one` | two routes on one port: use a splitter |
| `light arrives at X and has nowhere to go` | a part with no output path for that input |
| `light keeps circulating ... gain of 1 or more` | a loop with gain: check the ring amplitude |
| `a passive part gives out more power than it takes in` | a transfer error in a part: report it |
| `the scene changed after animation binding` | build the scene completely, then the animation |

The MCP tool `optodraw_compile_physics_animation` compiles to the older
timeline (the editor's 2D animation and Export GIF), not to the 3D page.

## Before you call it done

1. The scene passes `run_checks`, and every output ends on a detector.
2. The build ran with `strict=True` and raised no warning.
3. Every plot matches the formula you expected; you named the formula.
4. Each section tells one idea, in order.
5. You told the user which outputs they have and which path made each.
