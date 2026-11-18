---
name: optodraw-component
description: Use when an optical, photonic or electronic part is missing from optodraw, or when a built-in part looks wrong, and you must make your own component that draws in 1D (symbol), 2D and 3D, has ports that beams, waveguides and wires connect to, appears in the catalog, saves and loads with a scene, sits on a post on the optical table, and acts on light in an animation. Covers parts from SVG art (drawsvg or a vector editor) with marked ports and part files, the component contract, a complete worked part, registration, the 3D checks (nothing floats, posts on flat faces), the animation behaviour, and how to contribute a part to optodraw.
---

# optodraw-component

A part made from SVG art takes minutes (the fast way below). A full
component is a Python class with four answers: where its ports are, what it
draws in 2D, what solids it builds in 3D, and which 1D symbol stands for it.
Get the ports right first: beams, routes and the 1D view all hang on them.

Every python block in this file runs in order, as one script, in the optodraw
test suite. `reference/contribute.md` holds a 1D symbol of your own and the
steps to add a part to optodraw itself.

## Before you build one

Search the catalog by what the part does, not by one guessed name:

```python
from optodraw.catalog import describe_component, list_components

for word in ("Isolator", "Filter", "Attenuator"):
    print(word, [name for name in list_components() if word in name])
print(describe_component("OpticalIsolator")["description"])
```

If a near match exists, use it with its parameters or extend it. A second class
for a part that exists under another name splits the library. When the user
wants their own version of a part that exists, give it a new name
(`CrystalAOM`, not `AOM`).

## The fast way: a part from SVG art

Draw the art with drawsvg (or export an SVG from any vector editor), mark each
port, and import it. No class, no registration, and a part file that others
load without running code:

```python
import drawsvg as dw

from optodraw import PartLibrary, import_svg_part, load_part, save_part

art = dw.Drawing(12, 24)                                         # SVG units; y runs down
art.append(dw.Rectangle(4, 0, 4, 24, rx=1, fill="#3b4148"))
art.append(dw.Rectangle(4.6, 9, 2.8, 6, fill="#ffffff"))
art.append(dw.Line(4, 12, 0, 12, id="port:in", data_kind="free_space", data_width=6))
art.append(dw.Line(8, 12, 12, 12, id="port:out", data_kind="free_space", data_width=6))
mine = PartLibrary()
Slit = import_svg_part("user:mylab/Slit", art.as_svg(), platform="free_space", origin=(6, 12),
                       parameters={"width_um": {"type": "float", "default": 50.0, "min": 1.0, "max": 500.0}},
                       description="Adjustable slit", library=mine)
slit = Slit(center=(0, 0), width_um=25.0, label="Slit")
print({name: (round(p.center.x, 2), round(p.center.y, 2), round(p.orientation_deg) % 360)
       for name, p in slit.ports().items()})                     # in at -2 facing 180, out at +2 facing 0
save_part(Slit, "slit.odpart")                                   # a checked ZIP: part.json and the SVG
again = load_part("slit.odpart", library=PartLibrary())
assert again.definition.digest == Slit.definition.digest
```

- A port mark is an element with `id="port:<name>"`: a `line` or a `path`
  drawn from the part's edge outward (its first point, on the edge, is the
  port; the second point, outside, gives the outward direction; drawsvg
  writes a line as a path), a `circle` or `ellipse`, or a group with
  `data-x` and `data-y`. `data-orientation` overrides the direction, in SVG
  degrees (clockwise). `data-kind` (default `optical`) and `data-width`
  (default 0.5) set the kind and the width. Any other element is an error.
- SVG coordinates run y down; the part's ports run y up. `origin` is the SVG
  point that becomes the part's centre: put it on the beam axis or the
  waveguide centre line. Always print the ports and compare them with the art.
- `platform` is `"free_space"`, `"on_chip"` (the default) or `"electronics"`.
- Names are `user:<namespace>/<Name>` and never replace a built-in part. A
  `PartLibrary` keeps one project's parts apart from another's.
- The 1D view uses `symbol_1d=` (an SVG) if you give one, else the 2D art as
  black lines. The 3D view extrudes the closed outlines a little and marks
  the part as schematic; for a real 3D body, write a Python class.
- The editor's new-part dialog does the same without code and keeps the part
  in My parts.

## A part as a Python class: the contract

All coordinates are **local**: the part sits at the origin and the scene moves
and turns it.

| piece | method | convention |
|---|---|---|
| ports | `ports() -> dict[str, Port]` | light travels along local +x; `in` at -x faces 180 degrees, `out` at +x faces 0 |
| 2D | `geometry_2d() -> dict` | a tree of primitives, y up |
| 3D | `geometry_3d() -> dict` | origin on the beam axis; x along the beam, y up, z across |
| 1D | `symbol_1d()` | `None` for the default, or `(symbol_name, params)` from the symbol library |
| light | `animation_behaviour()` | how the part acts on light in an animation (below) |

`Port(name, center, orientation_deg, width, kind)`: `center` is a `Vec3`,
`orientation_deg` points outward, `kind` is `"free_space"`, `"optical"`
(waveguide), `"electrical"`, `"fiber"` or `"thermal"`.

2D primitives (`"type"`): `group` (`children`), `rect` (`cx, cy, w, h`),
`circle` (`cx, cy, r`), `ellipse`, `line` (`x1, y1, x2, y2`), `polygon` and
`polyline` (`points`), `path` (`d`), `text`. Style keys: `fill`, `stroke`,
`stroke_width`, `opacity`.

3D solids (`"shape"`): `box` (`width` along x, `height` along y, `depth`
along z; centred), `cylinder` (`radius`, `height`; centred, axis along y, so
turn it with `rotation: [0, 0, pi/2]` to lie along the beam), `sphere`,
`extruded_polygon` (`points` as `(u, v)`, `height`; it rises from y = 0, and
v maps to -z), `lathe_profile` (`points` as `(radius, height)`, turned about
y), `tube_path` (`points`, `radius`) and `group` (`children`). Every solid
takes `position`, `rotation` (radians), `material` (`color`, `metalness`,
`roughness`, `opacity`, `transparent`) and a free `role` tag. A shape the
renderer does not know draws as a magenta box.

`post_at: [x, y, z]` on the top group is the point the post holds. The
renderer builds the post and its base from `base_mount` (`"post"`, `"stage"`,
`"post_beam"`, `"rotation_stage"` or `"none"`); never draw the post yourself.

Two class attributes change how beams and checks treat a part.
`beam_passes = True` marks a part the light visibly crosses (an open
aperture, like `Iris`): the 2D draws a beam through it, where it otherwise
leaves the span between the part's own `in` and `out` blank so the beam does
not cross the part's art. `open_ports = ("e1", "e2")` names ports that may
stay unwired on a chip (a detector's own probe pads). In 1D, a part whose `in`
and `out` lie on one line through its centre gets the beam drawn under its
symbol: fill the symbol where the beam must not show, leave it open where the
light shows (an aperture).

## A complete part

```python
import math
from dataclasses import dataclass
from typing import Any

from optodraw import Component, Port, Transform
from optodraw.animation_engine.behaviours.passive import TwoPort
from optodraw.core import Vec3


class NDLight(TwoPort):
    """Light passes from one port to the other and keeps 10^(-OD/2) of its field amplitude."""

    def amplitude(self, part, sid, wavelength_nm, params):
        return 10 ** (-part.optical_density / 2)


@dataclass
class ShadePlate(Component):
    """A round neutral-density filter in a black ring. Light runs along local +x."""

    aperture: float = 12.0
    thickness: float = 3.0
    optical_density: float = 1.0

    def __init__(self, center=(0, 0), angle=0, aperture=12.0, thickness=3.0, optical_density=1.0,
                 label="ND", **kwargs):
        super().__init__(label=label, color=kwargs.get("color", "#6b7280"),
                         opacity=kwargs.get("opacity", 1.0), base_mount=kwargs.get("base_mount", "post"),
                         mount_height=kwargs.get("mount_height"))
        self.aperture, self.thickness, self.optical_density = aperture, thickness, optical_density
        self.transform = Transform.from_2d(*self._parse_center(center).as_2d(), angle)

    def ports(self) -> dict[str, Port]:
        h = self.thickness / 2.0
        return {
            "in": Port("in", Vec3(-h, 0, 0), orientation_deg=180, width=self.aperture, kind="free_space"),
            "out": Port("out", Vec3(h, 0, 0), orientation_deg=0, width=self.aperture, kind="free_space"),
        }

    def geometry_2d(self) -> dict[str, Any]:
        a, t = self.aperture, self.thickness
        return {"type": "group", "children": [
            {"type": "rect", "cx": 0, "cy": 0, "w": t * 1.4, "h": a,
             "fill": "#2f3439", "stroke": "#111827", "stroke_width": 0.1},
            {"type": "rect", "cx": 0, "cy": 0, "w": t, "h": a * 0.8, "fill": self.color, "opacity": 0.9},
        ]}

    def geometry_3d(self) -> dict[str, Any]:
        r, t = self.aperture / 2.0, self.thickness
        along_x = [0.0, 0.0, math.pi / 2]
        satin = {"color": "#2f3439", "metalness": 0.45, "roughness": 0.4}
        boss_y, boss_h = -r, 0.24 * r                    # a flat boss under the round ring
        return {"shape": "group", "post_at": [0.0, boss_y - boss_h / 2, 0.0], "children": [   # its bottom face
            {"shape": "cylinder", "radius": r, "height": t * 1.4, "rotation": along_x,
             "position": [0, 0, 0], "material": satin, "role": "ring"},
            {"shape": "cylinder", "radius": 0.8 * r, "height": t * 1.5, "rotation": along_x,
             "position": [0, 0, 0], "role": "glass",
             "material": {"color": self.color, "opacity": 0.6, "transparent": True}},
            {"shape": "box", "width": t * 1.4, "height": boss_h, "depth": 0.8 * r,
             "position": [0, boss_y, 0], "material": satin, "role": "boss"},
        ]}

    def animation_behaviour(self):
        return NDLight()
```

- `super().__init__(...)` takes the common fields (`label`, `color`,
  `opacity`, `base_mount`, `mount_height`); `label_side` is applied for every
  part, so a caller can always move the label.
- Keep every size a parameter, so the part scales and the catalog lists it.
- `amplitude()` scales the field: a power transmission T needs
  `amplitude = sqrt(T)` (80 % power: `math.sqrt(0.8)`).

## Check the part

```python
from optodraw import check_part_3d

nd = ShadePlate(center=(0, 0), label="ND 1.0")
print(nd.ports())
print("3D findings:", check_part_3d(nd))
```

`check_part_3d` finds solids that touch nothing (a knob behind a ring, a
wheel with no shaft) and a post that meets no flat face. The post rule holds
for a part the 3D view stands on a post (an optic at the beam plane); an
instrument, a stage or a periscope stands on the table. A part made of
separate pieces (three probe pads, a monitor and its keyboard) sets
`lies_on_table = True`, and then each piece rests on the table. It works on boxes
round the solids, so it cannot see two solids that sink into each other or a
transparent part hiding a bad joint: an empty list means those checks passed.
Look at the part in 3D too (the HTML from `render_threejs`, or a draft
`render_3d_image` where Chrome is installed).

## Register it

Registration puts the part in the catalog, the editor palette and the MCP
tools, and lets a saved scene load it again:

```python
from optodraw.registry import build_component, register

register("ShadePlate", ShadePlate, category="optics", platform="free_space",
         description="Neutral-density filter", parameters=["aperture", "thickness", "optical_density"])
print(describe_component("ShadePlate")["description"])
nd_from_catalog = build_component("ShadePlate", center=(0, 0), optical_density=2.0)
```

Register at import time of your own module, so every process that loads a
scene with the part knows it. Give it a name the catalog does not have yet
(check `list_components()`): a built-in name is refused.

## Use it

```python
from optodraw import Beam, Laser, Photodiode, Scene
from optodraw.app.validation import run_checks
from optodraw.symbols import lookup

scene = Scene(title="ND filter", width=120, height=40, platform="free_space")
laser = scene.add(Laser(center=(-40, 0), wavelength=633, label="Laser"))
nd = scene.add(ShadePlate(center=(0, 0), label="ND 1.0"))
pd = scene.add(Photodiode(center=(40, 0), label="PD"))
scene.add(Beam.through(laser, nd, pd, wavelength=633))
scene.render_svg("nd.svg")
scene.render_svg("nd_1d.svg", view="1d")
scene.render_threejs("nd_3d.html")

again = Scene.from_spec(scene.to_spec())          # save and load keep the part and its values
print([type(part).__name__ for part in again.walk()])
symbol = lookup(nd)
print("1D symbol:", symbol.source, "exact" if symbol.exact else "fallback", sorted(symbol.ports))
for issue in run_checks(scene):
    print(issue["level"], issue["message"])
```

With no symbol of its own, the 1D view draws a labeled block with the part's
ports; `run_checks` says so, and that is fine for a draft, not for a paper
(`reference/contribute.md` builds a real symbol). "does not declare ray
physics support" is expected for a part the ray tracer does not model.

## Make it act on light

The animation engine moves light only through parts that have a behaviour:

```python
from optodraw.animation_engine import Animation

light = Animation(scene, mode="cw", strict=True).auto().click()
absorbed = light.to_json()["signal_state"]["absorbed"]          # one record per detector port that light reaches
print({record["part"]: round(record["power"], 3) for record in absorbed})   # photodiode1: 0.1 for OD 1
```

`animation_behaviour()` returns the behaviour; a `TwoPort` passes light from
one port to the other and `amplitude()` scales the field (the square root of
the power ratio). Without it, a strict animation stops with "no behaviour yet
for ShadePlate". `optodraw.animation_engine.behaviours.registered_types()` lists
the built-in parts that already have one.

## Drawing rules that reviews keep finding

These apply to a 1D symbol and to 2D art. The first, second and fourth come from
the open `schematic-figure` skill (MIT): in its blind test, the reason a judge
gave most often for a generated figure was a set of identical flat shapes.

1. **Look the object up first.** Find two or three photos or drawings of the
   real part. Write down what makes it recognisable: its parts, its proportions
   and its colour. Draw from that list, never from memory of the word.
2. **Draw it as its field draws it.** A knife edge in a Foucault diagram is a
   solid wedge with its tip on the axis. A specialist checks this at once.
3. **One object in every view.** The symbol, the 2D art and the 3D solids show
   one part. Take the numbers of the art from `geometry_3d`, in units of the
   part's aperture, and name that method in a comment at the pic. Fins that
   stand on the back face in 2D and round the body in 3D are a fault.
4. **No two parts share one outline.** A plain bar says nothing. Give each part
   the feature that names it: a flag on a post, a chip on a copper plate.
5. **The material carries the meaning.** What stops light is dark
   (`od absorber`), glass is pale, metal is satin, and the light is the only
   strong colour.
6. **A ray inside a part is a true path.** Trace it through the part's own
   geometry and draw what it does, then pin the law of reflection in a test.
   Light in the air outside the body belongs to the beam, not to the drawing: a
   part ends at its last surface, and its port sits there.
7. **A part that a beam meets has ports.** Without `in` and `out` no beam can
   reach it, and `beam_passes = True` draws the light that runs on past it.
8. **A part with an inside keeps one plan.** Put the outline and the light path
   in class constants, in units of the part's size. The 3D solids read those
   constants and the pic repeats the same numbers, so pin them in a test. Set
   `_art_unit` so that the art keeps the scale of the plan. A comment says which
   numbers come from a data sheet and which are your schematic.
   `Spectrometer.OUTLINE` and `LIGHT_PATH` are the model.

## 3D rules that reviews keep finding

1. **Nothing floats.** Every solid touches the rest of the part.
   `check_part_3d` finds the ones that do not.
2. **The post meets a flat face.** A post under a round body needs a flat
   boss or a clamp; `post_at` sits on the boss's bottom face:
   y = boss centre y - boss height / 2.
3. **Model a real product.** Look at the maker's photo and drawing and copy
   the proportions, the colour and the connectors.
4. **Metal is satin, glass is transparent.** `metalness` about 0.5 and
   `roughness` about 0.4 for anodized aluminium; no shiny chrome rings.
5. **No two faces in one place.** Two surfaces at the same radius flicker:
   make a bore about 1.5 % larger than the optic in it.
6. **Light enters where the part has an opening**, on the beam axis
   (y = 0, z = 0).

## On-chip parts

A chip part uses the same base class with `kind="optical"` ports (`o1`, `o2`,
...) and `kind="electrical"` ports (`e1`, ...), `platform="on_chip"` in
`register`, and `extruded_polygon` solids for its layers. Load
`optodraw-layout` before you place it, and `optodraw-gds-3d` to compare it
with a real GDS.

The stack, not the part, sets each level and core material. Draw every core
solid with `**self._core()` (the stack's core level, colour and material), a
slab solid with `**self._slab(colour)`, and a metal at its key of
`self._draw_layer_stack()`. Return `self._on_the_stack(children)`: on a ridge
stack (lnoi400) it adds the slab under the core, and on a film stack (InP) the
films over it. A part that builds another part to draw passes it
`**self._stack_kwargs()`. Draw a waveguide at `self._draw("waveguide_width",
...)`, never the raw width, so its ports meet the guides of the other parts.
`tests/test_stack_true_cores.py` checks every part on four stacks.

## Circuit and package parts

A circuit part (`Resistor`, `Capacitor`, `Inductor`, `OpAmp`, `Ground`,
`BiasTee`, `RFMixer`, `Amplifier`, `RFFilter`) is its IEC symbol. Its class keeps one plan in symbol
centimetres, y up: `PORTS` (name: x, y, outward angle), `LINES` (the leads and
strokes) and `BODY` (a closed outline, filled white). The ports, the 2D lines
and the TikZ pic in `optodraw/symbols/tikz/od-circuit.tex` read the same
numbers, so each lead ends on its port. Change the plan and the pic together,
and pin both in a test. `value=` prints after the label. A package part
(`FiberArray`, `SMAConnector`) keeps its plan in class constants too, in
pitches or in mm, and its 3D solids read them. A wire bond is not a part: it is
a route kind, `scene.route(a, b, kind="wirebond")`.

```python
from optodraw import FiberArray, OpAmp, Resistor

r_f = Resistor(label="R_f", value="10 kΩ")
print(r_f.label, sorted(r_f.ports()))                       # R_f = 10 kΩ ['e1', 'e2']
amp = OpAmp()
x, y, facing = OpAmp.PORTS["in_n"]                          # the plan, in symbol cm
port = amp.ports()["in_n"]                                  # the same place, in scene units
assert (port.center.x, port.center.y) == (x * amp.unit, y * amp.unit) and port.orientation_deg == facing
print("3D findings:", check_part_3d(amp), check_part_3d(FiberArray(count=4)))
```
