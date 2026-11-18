"""Circuit parts: resistor, capacitor, inductor, op amp, ground, bias tee, RF mixer, amplifier and filter.

Each part is its IEC 60617 symbol. The class constants ``PORTS``, ``LINES`` and ``BODY`` hold that symbol in
symbol centimetres (y up): the ports, the 2D geometry and the TikZ pic of the part
(``optodraw/symbols/tikz/od-circuit.tex``) share these numbers. ``length`` is the width of the part between its
outer lead ends. ``value`` prints after the label: ``Resistor(label="R_f", value="10 kΩ")`` reads ``R_f = 10 kΩ``.

In 3D a resistor, a capacitor and an inductor are chip parts, an op amp is an SOIC-8, a bias tee, a mixer and an
amplifier are connectorised modules with an SMA jack at each port, and a filter is a coaxial tube. A ground is a
symbol and has no solid.
"""

from __future__ import annotations

import math
from typing import Any, ClassVar

from optodraw.components.electronics._shared import CHIP_BODY, INK, _init_component
from optodraw.core.component import Component
from optodraw.core.ports import Port
from optodraw.core.transform import Vec3

Point = tuple[float, float]
UNIT = 12.0          # scene units per symbol centimetre at the default length: every circuit part draws at one scale


def _arc(cx: float, cy: float, radius: float, start: float, end: float, steps: int = 8) -> tuple[Point, ...]:
    """Points on a circular arc, ``start`` to ``end`` in degrees counterclockwise from +x."""

    angles = (math.radians(start + (end - start) * i / steps) for i in range(steps + 1))
    return tuple((cx + radius * math.cos(a), cy + radius * math.sin(a)) for a in angles)


def _metal(name: str, metalness: float = 0.55, roughness: float = 0.38) -> dict[str, Any]:
    from optodraw.gds.palette import material_fill        # the one material table; lazy, as models.py does

    return {"color": material_fill(name), "metalness": metalness, "roughness": roughness}


def _chip_3d(length: float, width: float, height: float, body: dict[str, Any]) -> dict[str, Any]:
    """A chip part: a body between two tinned end caps. Each port lies on the outer face of its cap.

    A cap is 4 % wider and taller than the body, so no two faces share a plane.
    """

    cap = 0.16 * length
    return {"shape": "group", "children": [
        {"shape": "box", "width": length - 2.0 * cap, "height": height, "depth": width,
         "position": [0.0, height / 2.0, 0.0], "material": body, "role": "body"},
        *({"shape": "box", "width": cap, "height": 1.04 * height, "depth": 1.04 * width,
           "position": [side * (length - cap) / 2.0, 0.52 * height, 0.0], "material": _metal("metal"),
           "role": "terminal"} for side in (-1.0, 1.0)),
    ]}


def _module_3d(unit: float, case: tuple[float, float, float, float], height: float,
               ports: dict[str, tuple[float, float, float]]) -> dict[str, Any]:
    """A connectorised module: an aluminium case (``case`` = x0, y0, x1, y1 in plan units) and an SMA jack from the
    case wall out to each port. The tip of each jack is its port."""

    x0, y0, x1, y1 = (value * unit for value in case)
    axis = height / 2.0
    nut, radius = 0.06 * unit, 0.055 * unit
    gold = _metal("gold", 0.6, 0.35)
    children: list[dict[str, Any]] = [
        {"shape": "box", "width": x1 - x0, "height": height, "depth": y1 - y0,
         "position": [(x0 + x1) / 2.0, axis, -(y0 + y1) / 2.0], "material": _metal("aluminum", 0.5, 0.4),
         "role": "case"}]
    for px, py, facing in ports.values():
        px, py = px * unit, py * unit
        along_x = facing in (0.0, 180.0)
        sign = 1.0 if facing in (0.0, 90.0) else -1.0
        wall = {0.0: x1, 180.0: x0, 90.0: y1, -90.0: y0}[facing]
        barrel = abs((px if along_x else py) - wall) - nut
        nut_at, barrel_at = wall + sign * nut / 2.0, wall + sign * (nut + barrel / 2.0)
        if along_x:
            children += [
                {"shape": "box", "width": nut, "height": 0.16 * unit, "depth": 0.16 * unit,
                 "position": [nut_at, axis, -py], "material": gold, "role": "sma nut"},
                {"shape": "cylinder", "radius": radius, "height": barrel, "rotation": [0.0, 0.0, math.pi / 2],
                 "position": [barrel_at, axis, -py], "material": gold, "role": "sma jack"}]
        else:
            children += [
                {"shape": "box", "width": 0.16 * unit, "height": 0.16 * unit, "depth": nut,
                 "position": [px, axis, -nut_at], "material": gold, "role": "sma nut"},
                {"shape": "cylinder", "radius": radius, "height": barrel, "rotation": [math.pi / 2, 0.0, 0.0],
                 "position": [px, axis, -barrel_at], "material": gold, "role": "sma jack"}]
    return {"shape": "group", "children": children}


class CircuitPart(Component):
    """The common part of the circuit set: a symbol plan, a length, a value printed after the label."""

    PORTS: ClassVar[dict[str, tuple[float, float, float]]] = {}    # name: (x, y, outward angle in degrees)
    LINES: ClassVar[tuple[tuple[Point, ...], ...]] = ()             # the leads and the strokes of the symbol
    BODY: ClassVar[tuple[Point, ...]] = ()                          # a closed outline, filled white
    SPAN: ClassVar[float] = 1.0                                     # the plan's width between its outer leads
    _art_scale_from_ports = True     # the 2D art takes its size from the ports, so each lead ends on its port

    def __init__(self, center=(0, 0), angle: float = 0.0, length: float | None = None, value: str = "",
                 label: str = "", color: str = INK, opacity: float = 1.0):
        self.value = str(value)
        self.length = float(round(UNIT * self.SPAN, 6) if length is None else length)
        _init_component(self, center, angle, color=color, opacity=opacity, label=label)

    @property
    def label(self) -> str:
        """The name and the value as the drawings print them, each with its markup: ``R_f = 10 kΩ``."""

        return " = ".join(text for text in (self.designator, self.value) if text)

    @label.setter
    def label(self, text: str) -> None:
        self.designator = str(text)

    def _saved_params(self) -> dict[str, Any]:
        return {"label": self.designator}     # the value is saved on its own: a load must not print it twice

    @property
    def unit(self) -> float:
        """Scene units per symbol centimetre."""

        return self.length / self.SPAN

    _art_unit = unit                         # a one-port part (a ground) sizes its art by this

    def ports(self) -> dict[str, Port]:
        u = self.unit
        return {name: Port(name, Vec3(x * u, y * u, 0.0), orientation_deg=facing, width=0.04 * u, kind="electrical")
                for name, (x, y, facing) in self.PORTS.items()}

    def geometry_2d(self) -> dict[str, Any]:
        u = self.unit
        stroke = {"stroke": self.color, "stroke_width": 0.02 * u, "opacity": self.opacity}
        body = [{"type": "polygon", "points": [(x * u, y * u) for x, y in self.BODY], "fill": "#ffffff", **stroke}]
        lines = [{"type": "polyline", "points": [(x * u, y * u) for x, y in points], "fill": "none", **stroke}
                 for points in self.LINES]
        return {"type": "group", "children": (body if self.BODY else []) + lines}


class Resistor(CircuitPart):
    """Resistor: the IEC rectangle between two leads. A thick-film chip resistor in 3D."""

    PORTS = {"e1": (-0.5, 0.0, 180.0), "e2": (0.5, 0.0, 0.0)}
    LINES = (((-0.5, 0.0), (-0.3, 0.0)), ((0.3, 0.0), (0.5, 0.0)))
    BODY = ((-0.3, -0.1), (0.3, -0.1), (0.3, 0.1), (-0.3, 0.1))

    def geometry_3d(self) -> dict[str, Any]:
        return _chip_3d(self.length, 0.5 * self.length, 0.28 * self.length,
                        {"color": "#1f2328", "metalness": 0.1, "roughness": 0.7})     # the black overcoat


class Capacitor(CircuitPart):
    """Capacitor: two plates between two leads. A multilayer ceramic chip in 3D."""

    PORTS = {"e1": (-0.5, 0.0, 180.0), "e2": (0.5, 0.0, 0.0)}
    LINES = (((-0.5, 0.0), (-0.06, 0.0)), ((0.06, 0.0), (0.5, 0.0)),
             ((-0.06, -0.2), (-0.06, 0.2)), ((0.06, -0.2), (0.06, 0.2)))

    def geometry_3d(self) -> dict[str, Any]:
        return _chip_3d(self.length, 0.5 * self.length, 0.45 * self.length,
                        {"color": "#c9a27e", "metalness": 0.05, "roughness": 0.8})    # tan ceramic


class Inductor(CircuitPart):
    """Inductor: four half turns between two leads (IEC 60617). A moulded ferrite chip in 3D."""

    PORTS = {"e1": (-0.5, 0.0, 180.0), "e2": (0.5, 0.0, 0.0)}
    LINES = (((-0.5, 0.0), *(point for c in (-0.24, -0.08, 0.08, 0.24) for point in _arc(c, 0.0, 0.08, 180.0, 0.0)),
              (0.5, 0.0)),)

    def geometry_3d(self) -> dict[str, Any]:
        return _chip_3d(self.length, 0.6 * self.length, 0.5 * self.length,
                        {"color": "#5b6168", "metalness": 0.2, "roughness": 0.6})     # grey ferrite


class OpAmp(CircuitPart):
    """Operational amplifier: a triangle with its inverting (-) and non-inverting (+) inputs, and its supply pins
    V+ (``v_pos``) above and V- (``v_neg``) below. An SOIC-8 in 3D."""

    PORTS = {"in_n": (-0.6, 0.2, 180.0), "in_p": (-0.6, -0.2, 180.0), "out": (0.6, 0.0, 0.0),
             "v_pos": (0.0, 0.4, 90.0), "v_neg": (0.0, -0.4, -90.0)}
    LINES = (((-0.6, 0.2), (-0.4, 0.2)), ((-0.6, -0.2), (-0.4, -0.2)), ((0.4, 0.0), (0.6, 0.0)),
             ((0.0, 0.2), (0.0, 0.4)), ((0.0, -0.2), (0.0, -0.4)),                # the supply leads, from the edges
             ((-0.34, 0.2), (-0.22, 0.2)),                                          # the minus sign
             ((-0.34, -0.2), (-0.22, -0.2)), ((-0.28, -0.26), (-0.28, -0.14)))     # the plus sign
    BODY = ((-0.4, -0.4), (-0.4, 0.4), (0.4, 0.0))
    SPAN = 1.2
    open_ports = ("v_pos", "v_neg")          # a schematic may leave the supply implicit

    def geometry_3d(self) -> dict[str, Any]:
        """A JEDEC SOIC-8 to its proportions: 3.9 mm body, 4.9 mm long, 6.0 mm over the lead tips (the lead span
        here), 1.27 mm pitch. Gull-wing leads: a shoulder, a leg and a foot."""

        u = self.unit
        tin = _metal("metal")
        half_body, tip, lead, thick = 0.39 * u, 0.6 * u, 0.082 * u, 0.04 * u
        shoulder_y, bend = 0.13 * u, 0.5 * u
        children: list[dict[str, Any]] = [
            {"shape": "box", "width": 2 * half_body, "height": 0.3 * u, "depth": 0.98 * u,
             "position": [0.0, 0.15 * u, 0.0], "material": {"color": CHIP_BODY, "metalness": 0.1, "roughness": 0.65},
             "role": "body"},
            {"shape": "cylinder", "radius": 0.05 * u, "height": 0.01 * u, "position": [-0.25 * u, 0.305 * u, -0.33 * u],
             "material": {"color": "#4b5563", "metalness": 0.1, "roughness": 0.8}, "role": "pin 1"}]
        for side in (-1.0, 1.0):
            for row in (-0.381, -0.127, 0.127, 0.381):
                z = row * u
                children += [
                    {"shape": "box", "width": bend - half_body, "height": thick, "depth": lead,
                     "position": [side * (half_body + bend) / 2, shoulder_y + thick / 2, z], "material": tin,
                     "role": "lead"},
                    {"shape": "box", "width": thick, "height": shoulder_y - thick, "depth": lead,
                     "position": [side * (bend - thick / 2), (shoulder_y + thick) / 2, z], "material": tin,
                     "role": "lead"},
                    {"shape": "box", "width": tip - bend + thick, "height": thick, "depth": lead,
                     "position": [side * (bend - thick + tip) / 2, thick / 2, z], "material": tin, "role": "lead"}]
        return {"shape": "group", "children": children}


class Ground(CircuitPart):
    """Ground (earth): a lead down to three bars that get shorter (IEC 60617). A symbol: it has no solid."""

    PORTS = {"e1": (0.0, 0.3, 90.0)}
    LINES = (((0.0, 0.3), (0.0, 0.0)), ((-0.2, 0.0), (0.2, 0.0)), ((-0.13, -0.08), (0.13, -0.08)),
             ((-0.06, -0.16), (0.06, -0.16)))
    SPAN = 0.4

    def geometry_3d(self) -> dict[str, Any]:
        return {}


class BiasTee(CircuitPart):
    """Bias tee: RF passes a series capacitor, DC enters through an inductor to the RF+DC port. A connectorised
    module with three SMA jacks in 3D."""

    PORTS = {"rf": (-0.7, 0.0, 180.0), "rf_dc": (0.7, 0.0, 0.0), "dc": (0.2, 0.62, 90.0)}
    LINES = (((-0.7, 0.0), (-0.24, 0.0)), ((-0.16, 0.0), (0.7, 0.0)),
             ((-0.24, -0.12), (-0.24, 0.12)), ((-0.16, -0.12), (-0.16, 0.12)),
             ((0.2, 0.0), *(point for c in (0.11, 0.21, 0.31) for point in _arc(0.2, c, 0.05, -90.0, 90.0)),
              (0.2, 0.62)))
    BODY = ((-0.45, -0.2), (0.45, -0.2), (0.45, 0.42), (-0.45, 0.42))    # the case
    SPAN = 1.4

    def geometry_3d(self) -> dict[str, Any]:
        return _module_3d(self.unit, (-0.45, -0.2, 0.45, 0.42), 0.36 * self.unit, self.PORTS)


class RFMixer(CircuitPart):
    """RF mixer: a circle with a cross, RF in at the left, LO from below, IF out at the right. A connectorised
    module with three SMA jacks in 3D."""

    PORTS = {"rf": (-0.55, 0.0, 180.0), "if": (0.55, 0.0, 0.0), "lo": (0.0, -0.55, -90.0)}
    LINES = (((-0.55, 0.0), (-0.3, 0.0)), ((0.3, 0.0), (0.55, 0.0)), ((0.0, -0.3), (0.0, -0.55)),
             ((-0.212, -0.212), (0.212, 0.212)), ((-0.212, 0.212), (0.212, -0.212)))
    BODY = _arc(0.0, 0.0, 0.3, 0.0, 360.0, 48)
    SPAN = 1.1

    def geometry_3d(self) -> dict[str, Any]:
        return _module_3d(self.unit, (-0.32, -0.32, 0.32, 0.32), 0.32 * self.unit, self.PORTS)


class Amplifier(CircuitPart):
    """Amplifier: the IEC 60617 triangle, pointing the way the signal runs, input at the left, output at the right.
    An RF amplifier, a servo amplifier or a preamplifier in a block diagram. A connectorised module (an SMA jack at
    each end, a DC feedthrough pin on top) in 3D. ``value`` prints the gain: ``Amplifier(label="LNA", value="20 dB")``.
    """

    PORTS = {"in": (-0.5, 0.0, 180.0), "out": (0.5, 0.0, 0.0)}
    LINES = (((-0.5, 0.0), (-0.3, 0.0)), ((0.3, 0.0), (0.5, 0.0)))
    BODY = ((-0.3, -0.3), (-0.3, 0.3), (0.3, 0.0))

    def __init__(self, center=(0, 0), angle: float = 0.0, length: float | None = None, value: str = "",
                 label: str = "", color: str = INK, opacity: float = 1.0, gain: float | None = None,
                 bandwidth_hz: float | None = None):
        """``gain`` (V/V) and ``bandwidth_hz`` (a first-order pole) are the signal chain's numbers; None is its model
        default. ``value`` is only the printed text."""

        self.gain, self.bandwidth_hz = gain, bandwidth_hz
        super().__init__(center, angle, length, value, label, color, opacity)

    def geometry_3d(self) -> dict[str, Any]:
        u, height = self.unit, 0.3 * self.unit
        module = _module_3d(u, (-0.3, -0.2, 0.3, 0.2), height, self.PORTS)
        pin = 0.08 * u                             # the +DC feedthrough: a short pin standing on the case top
        module["children"].append({"shape": "cylinder", "radius": 0.025 * u, "height": pin,
                                   "position": [0.0, height + pin / 2.0, 0.0], "material": _metal("gold", 0.6, 0.35),
                                   "role": "dc pin"})
        return module


def _wave(y: float) -> tuple[Point, ...]:
    """One period of a sine across the filter box, on the line ``y``: the IEC mark of a frequency band."""

    xs = (-0.18 + 0.36 * i / 24 for i in range(25))
    return tuple((x, y + 0.04 * math.sin(math.radians(x * 1000.0))) for x in xs)    # the pic's sin(\x*1000)


class RFFilter(CircuitPart):
    """Electrical filter: the IEC 60617 box with three waves, low frequency at the bottom, high at the top. A stroke
    through a wave marks the band the filter stops: ``response`` is ``"lowpass"`` (the top wave struck),
    ``"highpass"`` (the bottom), ``"bandpass"`` (top and bottom) or ``"bandstop"`` (the middle). A coaxial filter
    with an SMA jack at each end in 3D. The optical filter is ``Filter``."""

    PORTS = {"in": (-0.5, 0.0, 180.0), "out": (0.5, 0.0, 0.0)}
    BODY = ((-0.3, -0.3), (0.3, -0.3), (0.3, 0.3), (-0.3, 0.3))
    WAVES = (0.15, 0.0, -0.15)                    # the three bands, top (high frequency) to bottom
    STRUCK = {"lowpass": (0.15,), "highpass": (-0.15,), "bandpass": (0.15, -0.15), "bandstop": (0.0,)}

    def __init__(self, center=(0, 0), angle: float = 0.0, length: float | None = None, value: str = "",
                 label: str = "", response: str = "lowpass", color: str = INK, opacity: float = 1.0):
        if response not in self.STRUCK:
            raise ValueError(f"response must be one of {sorted(self.STRUCK)}, not {response!r}")
        self.response = response
        super().__init__(center, angle, length, value, label, color, opacity)

    @property
    def LINES(self) -> tuple[tuple[Point, ...], ...]:  # noqa: N802 - the plan's name in every circuit part
        strokes = tuple(((-0.07, y - 0.07), (0.07, y + 0.07)) for y in self.STRUCK[self.response])
        return (((-0.5, 0.0), (-0.3, 0.0)), ((0.3, 0.0), (0.5, 0.0)), *(_wave(y) for y in self.WAVES), *strokes)

    def symbol_1d(self) -> tuple[str, dict[str, Any]]:
        return "rffilter", {"response": self.response}

    def geometry_3d(self) -> dict[str, Any]:
        """A coaxial filter (a metal tube, as Mini-Circuits SLP and SBP) between its two SMA jacks, on a flat
        saddle: the post meets the saddle's bottom face."""

        u, radius, saddle = self.unit, 0.16 * self.unit, 0.04 * self.unit
        module = _module_3d(u, (-0.3, -radius / u, 0.3, radius / u), 2.0 * (radius + saddle), self.PORTS)
        module["children"][0] = {"shape": "cylinder", "radius": radius, "height": 0.6 * u,
                                 "rotation": [0.0, 0.0, math.pi / 2], "position": [0.0, saddle + radius, 0.0],
                                 "material": _metal("aluminum", 0.5, 0.4), "role": "case"}
        module["children"].append({"shape": "box", "width": 0.4 * u, "height": saddle, "depth": 1.6 * radius,
                                   "position": [0.0, saddle / 2.0, 0.0], "material": _metal("aluminum", 0.5, 0.4),
                                   "role": "saddle"})
        return module


class PIDController(CircuitPart):
    """PID controller (servo, loop filter): an amplifier triangle with a resistor and a capacitor in series in
    its feedback path, as the op-amp PI integrator draws it; the input at the left, the output at the right. The
    servo of a laser lock or a phase-locked loop. A servo module (BNC at each end, gain and corner knobs on top) in
    3D. ``value`` prints the setting: ``PIDController(label="Servo", value="PI")``."""

    PORTS = {"in": (-0.5, 0.0, 180.0), "out": (0.5, 0.0, 0.0)}
    LOOP_Y = 0.44                                  # the feedback path runs over the triangle at this height
    LINES = (((-0.5, 0.0), (-0.3, 0.0)), ((0.3, 0.0), (0.5, 0.0)),
             ((-0.4, 0.0), (-0.4, LOOP_Y), (-0.2, LOOP_Y)),                                    # to the resistor
             ((-0.2, LOOP_Y - 0.05), (0.0, LOOP_Y - 0.05), (0.0, LOOP_Y + 0.05), (-0.2, LOOP_Y + 0.05),
              (-0.2, LOOP_Y - 0.05)),                                                           # the resistor
             ((0.0, LOOP_Y), (0.12, LOOP_Y)),
             ((0.12, LOOP_Y - 0.1), (0.12, LOOP_Y + 0.1)), ((0.18, LOOP_Y - 0.1), (0.18, LOOP_Y + 0.1)),  # the capacitor
             ((0.18, LOOP_Y), (0.4, LOOP_Y), (0.4, 0.0)))
    BODY = ((-0.3, -0.3), (-0.3, 0.3), (0.3, 0.0))
    KNOBS = (-0.12, 0.12)                          # the gain and corner knobs on the case top, along x

    def geometry_3d(self) -> dict[str, Any]:
        """A servo box (a loop filter module, LB1005 kind): an aluminium case, a BNC-sized jack at each port and
        the two gain knobs standing on the case top."""

        u, height = self.unit, 0.32 * self.unit
        module = _module_3d(u, (-0.3, -0.22, 0.3, 0.22), height, self.PORTS)
        for x in self.KNOBS:
            module["children"] += [
                {"shape": "cylinder", "radius": 0.07 * u, "height": 0.03 * u, "position": [x * u, height + 0.015 * u, 0.0],
                 "material": _metal("aluminum", 0.5, 0.4), "role": "knob skirt"},
                {"shape": "cylinder", "radius": 0.05 * u, "height": 0.08 * u, "position": [x * u, height + 0.07 * u, 0.0],
                 "material": {"color": "#2a2f36", "metalness": 0.3, "roughness": 0.5}, "role": "knob"}]
        return module


def _sine(radius: float, amplitude: float) -> tuple[Point, ...]:
    """One period of a sine across ``radius`` either side of the centre: the pic's sin((x + r) * 180 / r)."""

    return tuple((x, amplitude * math.sin(math.pi * (x + radius) / radius))
                 for x in (-radius + 2.0 * radius * i / 24 for i in range(25)))


class SignalSource(CircuitPart):
    """Signal source (local oscillator, RF source, synthesizer): the IEC circle with a sine, its output lead at the
    right. ``value`` prints the frequency: ``SignalSource(label="LO", value="20 MHz")``. A bench instrument is
    ``WaveformGenerator``; this is its symbol in a block diagram. An oscillator module with one SMA jack in 3D."""

    PORTS = {"out": (0.55, 0.0, 0.0)}
    LINES = (((0.3, 0.0), (0.55, 0.0)), _sine(0.18, 0.1))
    BODY = _arc(0.0, 0.0, 0.3, 0.0, 360.0, 48)
    SPAN = 0.85                                    # from the left of the circle to the output

    def geometry_3d(self) -> dict[str, Any]:
        return _module_3d(self.unit, (-0.3, -0.3, 0.3, 0.3), 0.32 * self.unit, self.PORTS)


class SummingJunction(CircuitPart):
    """Summing junction (adder, subtractor): a circle with a plus, the inputs ``in1`` (left) and ``in2`` (below),
    the output at the right, and the sign of each input beside its lead. ``signs`` is ``"++"`` (the sum) or ``"+-"``
    (in1 minus in2: a setpoint less the measured signal). A summing amplifier module with three SMA jacks in 3D."""

    PORTS = {"in1": (-0.55, 0.0, 180.0), "in2": (0.0, -0.55, -90.0), "out": (0.55, 0.0, 0.0)}
    BODY = _arc(0.0, 0.0, 0.3, 0.0, 360.0, 48)
    SPAN = 1.1
    SIGN_AT = {"in1": (-0.44, 0.16), "in2": (-0.14, -0.44)}     # beside each input lead
    SIGNS = ("++", "+-")

    def __init__(self, center=(0, 0), angle: float = 0.0, length: float | None = None, value: str = "",
                 label: str = "", signs: str = "++", color: str = INK, opacity: float = 1.0):
        if signs not in self.SIGNS:
            raise ValueError(f"signs must be one of {list(self.SIGNS)}, not {signs!r}")
        self.signs = signs
        super().__init__(center, angle, length, value, label, color, opacity)

    @property
    def LINES(self) -> tuple[tuple[Point, ...], ...]:  # noqa: N802 - the plan's name in every circuit part
        marks: list[tuple[Point, ...]] = []
        for (x, y), sign in zip(self.SIGN_AT.values(), self.signs):
            marks.append(((x - 0.05, y), (x + 0.05, y)))
            if sign == "+":
                marks.append(((x, y - 0.05), (x, y + 0.05)))
        return (((-0.55, 0.0), (-0.3, 0.0)), ((0.3, 0.0), (0.55, 0.0)), ((0.0, -0.55), (0.0, -0.3)),
                ((-0.16, 0.0), (0.16, 0.0)), ((0.0, -0.16), (0.0, 0.16)), *marks)

    def symbol_1d(self) -> tuple[str, dict[str, Any]]:
        return "sumjunction", ({"minus": True} if self.signs == "+-" else {})

    def geometry_3d(self) -> dict[str, Any]:
        return _module_3d(self.unit, (-0.32, -0.32, 0.32, 0.32), 0.32 * self.unit, self.PORTS)


_BOX = ((-0.3, -0.3), (0.3, -0.3), (0.3, 0.3), (-0.3, 0.3))     # the case of a two-port RF block


class RFSplitter(CircuitPart):
    """RF power splitter (a Wilkinson divider): one input at the left, two equal outputs at the right, a box with the
    fork inside. Joined backwards it is a combiner. A connectorised module with three SMA jacks in 3D."""

    PORTS = {"in": (-0.5, 0.0, 180.0), "out1": (0.5, 0.15, 0.0), "out2": (0.5, -0.15, 0.0)}
    LINES = (((-0.5, 0.0), (-0.05, 0.0)), ((-0.05, -0.15), (-0.05, 0.15)),
             ((-0.05, 0.15), (0.5, 0.15)), ((-0.05, -0.15), (0.5, -0.15)))
    BODY = _BOX

    def geometry_3d(self) -> dict[str, Any]:
        return _module_3d(self.unit, (-0.3, -0.3, 0.3, 0.3), 0.3 * self.unit, self.PORTS)


class RFCoupler(CircuitPart):
    """RF directional coupler: the main line runs through from ``in`` to ``out``, a coupled line beside it takes a
    sample to ``cpl`` above (a monitor output, toward the instruments over the chain). ``value`` prints the coupling: ``RFCoupler(label="Tap", value="-10 dB")``. A
    connectorised module with three SMA jacks in 3D. An optical coupler is ``FiberCoupler`` or
    ``DirectionalCoupler``."""

    PORTS = {"in": (-0.5, 0.0, 180.0), "out": (0.5, 0.0, 0.0), "cpl": (0.2, 0.5, 90.0)}
    LINES = (((-0.5, 0.0), (0.5, 0.0)), ((-0.2, 0.13), (0.2, 0.13), (0.2, 0.5)))
    BODY = _BOX

    def geometry_3d(self) -> dict[str, Any]:
        return _module_3d(self.unit, (-0.3, -0.3, 0.3, 0.3), 0.3 * self.unit, self.PORTS)


class RFPhaseShifter(CircuitPart):
    """RF (electrical) phase shifter: a box with the letter phi drawn as a ring and a stroke, so it reads the same
    turned or mirrored. The phase of a local oscillator before a mixer or a modulator. A connectorised module with
    two SMA jacks in 3D. The phase shifter on a chip is ``PhaseShifter``."""

    PORTS = {"in": (-0.5, 0.0, 180.0), "out": (0.5, 0.0, 0.0)}
    LINES = (((-0.5, 0.0), (-0.3, 0.0)), ((0.3, 0.0), (0.5, 0.0)), _arc(0.0, 0.0, 0.1, 0.0, 360.0, 24),
             ((0.0, -0.19), (0.0, 0.19)))
    BODY = _BOX

    def geometry_3d(self) -> dict[str, Any]:
        return _module_3d(self.unit, (-0.3, -0.25, 0.3, 0.25), 0.3 * self.unit, self.PORTS)
