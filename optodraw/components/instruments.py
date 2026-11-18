"""Bench instruments — the electronics that drive and read a setup.

First-class replacements for the legacy instrument drawings: each has a real
front-panel 2D face and a simple boxy 3D body, plus electrical ports so they
wire to modulator pads, TIAs, and drivers. Visualization only (no physics).
"""

from __future__ import annotations

import math

from dataclasses import dataclass
from typing import Any

from optodraw.core.component import Component
from optodraw.core.ports import Port
from optodraw.core.transform import Transform, Vec3

from optodraw.components.optics import _set_common_free_space_fields

_BODY = "#2b3038"      # dark instrument chassis
_FACE = "#3a4049"      # front-panel tone
_SCREEN = "#101720"    # display background
_DATA = "#FB923C"      # computed data on a screen: the trace colour of the 2D symbol art
_TRACE = "#39c6a5"     # phosphor / plot trace
_ACCENT = "#2f5cff"


def _connector(x: float, z: float, *, y: float = 2.2, r: float = 0.75, color: str = "#c8ccd2") -> dict[str, Any]:
    """A connector barrel on the panel at a port's (x, z) — where cables land."""

    return {"shape": "cylinder", "radius": r, "height": 1.8, "rotation": [1.5708, 0, 0],
            "position": [x, y, z], "material": {"color": color, "preset": "steel", "metalness": 0.8, "roughness": 0.25}}


# Front-panel pieces. The front face of a case is at z = depth / 2; each piece stands on it (+z).
_NICKEL = {"color": "#c9ced4", "preset": "steel", "metalness": 0.6, "roughness": 0.35}
_PANEL_DARK = "#3b4047"
_KEY = "#5a616b"


def _panel(w: float, h: float, z: float, color: str, *, y: float | None = None) -> dict[str, Any]:
    """A front-panel plate over most of the front face."""

    return _box3d(w, h, 0.12, color, pos=[0, h / 2.0 + 0.4 if y is None else y, z + 0.06])


def _display(x: float, y: float, w: float, h: float, z: float, glow: str, *, bezel: str = "#16191d",
             screen: str = _SCREEN, intensity: float = 0.22, trace: list[tuple[float, float]] | None = None) -> list[dict[str, Any]]:
    """A lit display in a dark bezel; ``trace`` draws a bright curve on it, from points in (-1..1, -1..1) of the
    screen's half width and half height."""

    lines = []
    for (u0, v0), (u1, v1) in zip(trace or [], (trace or [])[1:]):
        x0, y0, x1, y1 = x + u0 * w * 0.45, y + v0 * h * 0.4, x + u1 * w * 0.45, y + v1 * h * 0.4
        lines.append({**_box3d(math.hypot(x1 - x0, y1 - y0) + 0.08, 0.14, 0.04, glow, pos=[(x0 + x1) / 2.0, (y0 + y1) / 2.0, z + 0.27],
                               emissive=glow, emissiveIntensity=1.6), "rotation": [0, 0, math.atan2(y1 - y0, x1 - x0)]})
    return [*lines, _box3d(w + 0.8, h + 0.8, 0.15, bezel, pos=[x, y, z + 0.075]),
            {**_box3d(w, h, 0.1, screen, pos=[x, y, z + 0.2], preset="glass", emissive=glow, emissiveIntensity=intensity,
                      opacity=1.0, transparent=False, transmission=0.0), "role": "display"}]   # a lit panel, not clear glass


def _keys(x0: float, y0: float, cols: int, rows: int, pitch: float, size: float, z: float,
          color: str = _KEY) -> list[dict[str, Any]]:
    """A grid of square keys, the first at (x0, y0), rows going down."""

    return [{**_box3d(size, size * 0.75, 0.35, color, pos=[x0 + c * pitch, y0 - r * pitch * 0.8, z + 0.175]), "role": "key"}
            for r in range(rows) for c in range(cols)]


def _knob(x: float, y: float, r: float, z: float, color: str = "#2a2f36") -> list[dict[str, Any]]:
    """A rotary knob on its skirt."""

    return [{"shape": "cylinder", "radius": r * 1.15, "height": 0.25, "position": [x, y, z + 0.125], "rotation": [1.5708, 0, 0],
             "material": {"color": "#8d949c", "metalness": 0.5, "roughness": 0.4}},
            {"shape": "cylinder", "role": "knob", "radius": r, "height": r * 0.8, "position": [x, y, z + 0.25 + r * 0.4],
             "rotation": [1.5708, 0, 0], "material": {"color": color, "metalness": 0.3, "roughness": 0.5}}]


def _bnc(x: float, y: float, z: float, *, r: float = 0.55) -> list[dict[str, Any]]:
    """A BNC jack: its flange and barrel."""

    return [{"shape": "cylinder", "radius": r * 1.45, "height": 0.4, "position": [x, y, z + 0.2], "rotation": [1.5708, 0, 0], "material": _NICKEL},
            {"shape": "cylinder", "role": "bnc", "radius": r, "height": 1.3, "position": [x, y, z + 0.4 + 0.65], "rotation": [1.5708, 0, 0], "material": _NICKEL}]


def _banana(x: float, y: float, z: float, color: str) -> list[dict[str, Any]]:
    """A banana jack: the coloured insulator and its metal post."""

    return [{"shape": "cylinder", "radius": 0.7, "height": 0.9, "position": [x, y, z + 0.45], "rotation": [1.5708, 0, 0], "material": {"color": color, "roughness": 0.45}},
            {"shape": "cylinder", "radius": 0.3, "height": 0.6, "position": [x, y, z + 1.2], "rotation": [1.5708, 0, 0], "material": _NICKEL}]


def _led(x: float, y: float, z: float, color: str) -> dict[str, Any]:
    return {"shape": "sphere", "radius": 0.22, "position": [x, y, z + 0.1], "material": {"color": color, "emissive": color, "emissiveIntensity": 1.4}}


def _carry_handle(top: float, span: float) -> list[dict[str, Any]]:
    """A carry handle on a case top at ``top``: two feet on the case and a grip bar across them."""

    feet = [_box3d(0.98, 1.3, 2.352, "#9aa1ab", pos=[side * span / 2.0, top + 0.65, 0]) for side in (-1, 1)]  # 1 % inside the grip's faces
    return feet + [_box3d(span + 1.0, 0.8, 2.4, "#b9bec6", pos=[0, top + 1.6, 0])]


def _box3d(w: float, h: float, d: float, color: str, *, pos=None, preset: str = "aluminum", **mat) -> dict[str, Any]:
    out: dict[str, Any] = {
        "shape": "box", "width": w, "height": h, "depth": d,
        "material": {"color": color, "preset": preset, **mat},
    }
    if pos is not None:
        out["position"] = list(pos)
    return out


_SCREEN_POINTS = 400     # the most points a computed trace keeps, so a figure stays small


def screen_points(x, y) -> list[tuple[float, float]]:
    """``y`` against ``x`` as points on an instrument's screen: x from -1 to 1, y from -0.8 to 0.8 (a flat signal sits
    at 0). A long series keeps 400 points, evenly picked, the first and the last among them."""

    import numpy as np

    x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    if x.ndim != 1 or x.shape != y.shape:
        raise ValueError(f"screen points need two series of one length, got the shapes {x.shape} and {y.shape}")
    if len(x) > _SCREEN_POINTS:
        keep = np.linspace(0, len(x) - 1, _SCREEN_POINTS).round().astype(int)
        x, y = x[keep], y[keep]

    def scaled(values, half):
        span = values.max() - values.min() if len(values) else 0.0
        return half * (2.0 * (values - values.min()) / span - 1.0) if span > 0 else np.zeros_like(values)

    return [(float(u), float(v)) for u, v in zip(scaled(x, 1.0), scaled(y, 0.8))]


def _on_screen(points, cx: float, cy: float, w: float, h: float) -> list[tuple[float, float]]:
    """Screen points (``screen_points``) in the part's 2D frame, on a screen at (cx, cy) of size w x h, placed as
    ``_display`` places a 3D trace."""

    return [(cx + u * w * 0.45, cy + v * h * 0.4) for u, v in points]


@dataclass
class Computer(Component):
    """Workstation: monitor on a stand with a keyboard, screen showing a plot."""

    component_type = "Computer"
    lies_on_table = True       # the monitor, the keyboard and the PC stand on the bench apart, as on a desk

    def __init__(self, center=(0, 0), angle=0, **kwargs):
        _set_common_free_space_fields(self, center, angle, kwargs, color=_BODY, opacity=1.0, material_preset="aluminum", label=kwargs.get("label", "Computer"))

    def ports(self) -> dict[str, Port]:
        return {"e1": Port("e1", Vec3(-10.0, 0.0, 0), orientation_deg=180, width=2.0, kind="electrical")}

    def geometry_2d(self) -> dict[str, Any]:
        return {"type": "group", "children": [
            {"type": "rect", "cx": 0, "cy": 3.2, "w": 20, "h": 13, "fill": self.color, "stroke": "#14181e", "stroke_width": 0.14, "opacity": self.opacity},
            {"type": "rect", "cx": 0, "cy": 3.2, "w": 17.8, "h": 10.8, "fill": _SCREEN, "opacity": self.opacity},
            {"type": "polyline", "points": [(-7.6, 1.4), (-5.2, 4.6), (-2.6, 2.2), (0.4, 6.4), (3.2, 3.4), (5.8, 5.2), (7.6, 4.0)], "stroke": _TRACE, "stroke_width": 0.5, "opacity": self.opacity},
            {"type": "rect", "cx": 0, "cy": -4.4, "w": 2.6, "h": 2.4, "fill": _FACE, "opacity": self.opacity},
            {"type": "rect", "cx": 0, "cy": -6.0, "w": 8.5, "h": 1.1, "fill": self.color, "opacity": self.opacity},
            {"type": "rect", "cx": 0, "cy": -8.4, "w": 14, "h": 3.2, "fill": _FACE, "stroke": "#14181e", "stroke_width": 0.1, "opacity": self.opacity},
            {"type": "rect", "cx": -0.8, "cy": -8.0, "w": 10.5, "h": 1.6, "fill": "#262b32", "opacity": self.opacity},
            {"type": "circle", "cx": 8.6, "cy": -2.2, "r": 0.42, "fill": _TRACE, "opacity": self.opacity},
        ]}

    def geometry_3d(self) -> dict[str, Any]:
        return {"shape": "group", "children": [
            _box3d(20, 13, 1.2, self.color, pos=[0, 11.0, 0]),
            _box3d(17.8, 10.8, 0.3, _SCREEN, pos=[0, 11.0, 0.7], preset="glass", emissive=_TRACE, emissiveIntensity=0.3, opacity=1.0, transparent=False, transmission=0.0),
            _box3d(6.5, 8.0, 1.4, "#22262c", pos=[0, 11.0, -1.2]),        # monitor back bulge
            _box3d(2.6, 3.4, 1.6, _FACE, pos=[0, 2.8, 0]),
            _box3d(8.5, 1.1, 4.5, self.color, pos=[0, 0.55, 0]),
            _box3d(14, 0.9, 5.2, _FACE, pos=[0, 0.45, 6.2]),
            _box3d(12.4, 0.35, 3.8, "#262b32", pos=[-0.6, 0.95, 6.0]),    # key field
            _box3d(3.8, 4.4, 4.5, "#2a2f36", pos=[-7.4, 2.2, 0]),        # a small PC under the monitor
            {"shape": "cylinder", "radius": 0.75, "height": 1.8, "rotation": [0, 0, 1.5708], "position": [-10.2, 2.2, 0], "material": {"color": "#c8ccd2", "preset": "steel", "metalness": 0.8, "roughness": 0.25}},
        ]}


@dataclass
class Oscilloscope(Component):
    """Bench oscilloscope: screen with a waveform, knob column, the BNC inputs ``ch1`` and ``ch2`` and the ``usb``
    data port to a computer under the panel. ``JACKS`` (symbol centimetres along the bottom edge) is the plan of the
    ports and of the TikZ pic ``od oscilloscope``; ``UNIT`` scene units are one centimetre of it.

    ``traces`` (``{"ch1": points, "ch2": points}``, points from ``screen_points``) puts computed data on the 2D screen
    in place of the demo wave, each channel in its ``CHANNEL_COLOURS`` colour. The 3D screen keeps its demo wave."""

    component_type = "Oscilloscope"
    UNIT = 15.0
    JACKS = {"ch1": -0.4, "ch2": 0.0, "usb": 0.58}
    CHANNEL_COLOURS = {"ch1": _DATA, "ch2": "#56B4E9"}
    SCREEN = (-0.68, -0.33, 0.36, 0.33)                  # the screen of the pic, in symbol centimetres
    _art_scale_from_ports = True

    def __init__(self, center=(0, 0), angle=0, traces=None, **kwargs):
        _set_common_free_space_fields(self, center, angle, kwargs, color="#e8eaee", opacity=1.0, material_preset="aluminum", label=kwargs.get("label", "Oscilloscope"))
        if traces is not None and set(traces) - set(self.CHANNEL_COLOURS):
            raise ValueError(f"an oscilloscope shows ch1 and ch2, not {sorted(set(traces) - set(self.CHANNEL_COLOURS))}")
        self.traces = None if traces is None else {name: [(float(u), float(v)) for u, v in points]
                                                   for name, points in traces.items()}

    def screen_data(self) -> list[tuple[str, Any, str]]:
        """What the 2D art shows on its screen in place of its demo wave: ``(kind, value, colour)``."""

        return [("trace", points, self.CHANNEL_COLOURS[name]) for name, points in (self.traces or {}).items()]

    def ports(self) -> dict[str, Port]:
        u = self.UNIT
        return {name: Port(name, Vec3(x * u, -0.6 * u, 0), orientation_deg=270, width=1.8, kind="electrical")
                for name, x in self.JACKS.items()}

    def geometry_2d(self) -> dict[str, Any]:
        knobs = [{"type": "circle", "cx": 8.6, "cy": y, "r": 1.0, "fill": _FACE, "stroke": "#14181e", "stroke_width": 0.12, "opacity": self.opacity} for y in (4.6, 1.6, -1.4)]
        grid = [{"type": "line", "x1": -10.2, "y1": y, "x2": 4.6, "y2": y, "stroke": "#233040", "stroke_width": 0.08, "opacity": self.opacity} for y in (0.6, 3.4)]
        grid += [{"type": "line", "x1": x, "y1": -2.6, "x2": x, "y2": 6.6, "stroke": "#233040", "stroke_width": 0.08, "opacity": self.opacity} for x in (-5.6, -0.8)]
        cx, cy, w, h = -2.8, 2.0, 14.8, 9.2
        curves = ({"ch1": [(-9.6, 2.0), (-7.8, 5.4), (-6.0, -1.0), (-4.2, 5.4), (-2.4, -1.0), (-0.6, 5.4), (1.2, -1.0), (3.0, 2.0), (4.2, 2.0)]}
                  if self.traces is None else
                  {name: _on_screen(points, cx, cy, w, h) for name, points in self.traces.items()})
        return {"type": "group", "children": [
            {"type": "rect", "cx": 0, "cy": 0, "w": 24, "h": 16, "fill": self.color, "stroke": "#9aa1ab", "stroke_width": 0.16, "opacity": self.opacity},
            {"type": "rect", "cx": cx, "cy": cy, "w": w, "h": h, "fill": _SCREEN, "opacity": self.opacity},
            *grid,
            *[{"type": "polyline", "points": points, "stroke": self.CHANNEL_COLOURS[name], "stroke_width": 0.42, "opacity": self.opacity}
              for name, points in curves.items()],
            *knobs,
            {"type": "rect", "cx": 8.6, "cy": -4.6, "w": 4.6, "h": 2.6, "fill": _FACE, "opacity": self.opacity},
            *[{"type": "circle", "cx": self.JACKS[name] * self.UNIT, "cy": -0.525 * self.UNIT, "r": 0.075 * self.UNIT,
               "fill": "#c8ccd2", "stroke": "#14181e", "stroke_width": 0.14, "opacity": self.opacity} for name in ("ch1", "ch2")],
            {"type": "rect", "cx": self.JACKS["usb"] * self.UNIT, "cy": -0.525 * self.UNIT, "w": 0.1 * self.UNIT,
             "h": 0.15 * self.UNIT, "fill": "#c8ccd2", "stroke": "#14181e", "stroke_width": 0.14, "opacity": self.opacity},
        ]}

    def geometry_3d(self) -> dict[str, Any]:
        # A two-channel bench scope: a dark front panel in a light case, the screen on the left, the vertical
        # and horizontal knobs in two columns on the right with a row of keys under them, the channel BNCs and
        # the power key along the bottom, a carry handle on top.
        z = 7.0
        return {"shape": "group", "children": [
            _box3d(24, 16, 14, self.color, pos=[0, 8.0, 0]),
            _panel(23.2, 15.2, z, _PANEL_DARK, y=8.0),
            *_display(-3.5, 9.6, 14.0, 8.6, z + 0.12, _TRACE, trace=[(u / 10.0, 0.6 * math.sin(u / 10.0 * 3.0 * math.pi)) for u in range(-10, 11)]),
            *[piece for x in (6.6, 9.6) for y in (13.0, 10.4, 7.8) for piece in _knob(x, y, 0.75, z + 0.12)],
            *_keys(5.6, 5.4, 4, 1, 1.5, 1.1, z + 0.12),
            *_bnc(self.JACKS["ch1"] * self.UNIT, 2.2, z + 0.12), *_bnc(self.JACKS["ch2"] * self.UNIT, 2.2, z + 0.12),
            {**_box3d(1.2, 0.6, 0.5, "#2b3036", pos=[self.JACKS["usb"] * self.UNIT, 2.2, z + 0.37]), "role": "usb"},
            _box3d(1.2, 0.9, 0.3, "#8d949c", pos=[-10.4, 2.2, z + 0.27]),       # power key
            _box3d(0.5, 1.2, 0.5, "#c9ced4", pos=[10.6, 2.4, z + 0.37]),        # probe compensation terminal
            *_carry_handle(16.0, 9.0),
        ]}


@dataclass
class SMU(Component):
    """Source-measure unit: rack box with a readout display and HI/LO jacks."""

    component_type = "SMU"

    def __init__(self, center=(0, 0), angle=0, **kwargs):
        _set_common_free_space_fields(self, center, angle, kwargs, color="#c3c8ce", opacity=1.0, material_preset="aluminum", label=kwargs.get("label", "SMU"))

    # The plan of the pic od smu, in its cm: the jacks and the ends of their leads. One cm is UNIT scene units, so
    # the pic's 1.6 cm panel is the 28-unit case and each wire ends on the lead the 2D art draws.
    JACKS = {"hi": 0.4, "lo": 0.64}
    LEAD_END = -0.6
    UNIT = 28.0 / 1.6

    def ports(self) -> dict[str, Port]:
        return {name: Port(name, Vec3(x * self.UNIT, self.LEAD_END * self.UNIT, 0), orientation_deg=270, width=1.8,
                           kind="electrical") for name, x in self.JACKS.items()}

    def geometry_2d(self) -> dict[str, Any]:
        buttons = [{"type": "rect", "cx": -1.6 + col * 2.4, "cy": -2.6, "w": 1.7, "h": 1.3, "fill": "#4a5059", "opacity": self.opacity} for col in range(4)]
        hi, lo = (x * self.UNIT for x in self.JACKS.values())
        return {"type": "group", "children": [
            {"type": "rect", "cx": 0, "cy": 0, "w": 28, "h": 12, "fill": self.color, "stroke": "#14181e", "stroke_width": 0.16, "opacity": self.opacity},
            {"type": "rect", "cx": -6.4, "cy": 1.6, "w": 12.5, "h": 4.6, "fill": _SCREEN, "opacity": self.opacity},
            {"type": "rect", "cx": -9.4, "cy": 1.6, "w": 4.6, "h": 2.2, "fill": "#1d4436", "opacity": self.opacity},
            {"type": "rect", "cx": -3.2, "cy": 1.6, "w": 5.0, "h": 2.2, "fill": "#1d4436", "opacity": self.opacity},
            *buttons,
            {"type": "circle", "cx": hi, "cy": -3.4, "r": 1.05, "fill": "#c0392b", "stroke": "#14181e", "stroke_width": 0.14, "opacity": self.opacity},
            {"type": "circle", "cx": lo, "cy": -3.4, "r": 1.05, "fill": "#14181e", "stroke": "#3a4049", "stroke_width": 0.14, "opacity": self.opacity},
            *[{"type": "line", "x1": x, "y1": -4.45, "x2": x, "y2": -6.0, "stroke": "#c8ccd2", "stroke_width": 0.3} for x in (hi, lo)],
            {"type": "rect", "cx": 9.0, "cy": 3.2, "w": 6.4, "h": 2.6, "fill": _FACE, "opacity": self.opacity},
        ]}

    def geometry_3d(self) -> dict[str, Any]:
        # A source meter (Keithley 2400 kind): a grey case and panel, a green display at the top left with two
        # rows of keys under it, the rotary knob and range keys in the middle, the sense and HI / LO terminals
        # on the right (HI and LO at the ports), the line switch at the bottom left.
        z = 8.0
        hi, lo = (x * self.UNIT for x in self.JACKS.values())
        vents = [_box3d(0.5, 6.5, 10, "#8d949c", pos=[x, 6.0, 0]) for x in (-14.05, 14.05)]
        return {"shape": "group", "children": [
            _box3d(28, 12, 16, self.color, pos=[0, 6.0, 0]),
            _panel(27.2, 11.2, z, "#aeb4ba", y=6.0),
            *_display(-7.0, 8.6, 12.0, 3.0, z + 0.12, "#4fe0b0"),
            *_keys(-12.0, 5.2, 6, 2, 2.0, 1.4, z + 0.12),
            *_knob(3.4, 7.4, 1.6, z + 0.12),
            *_keys(1.6, 3.6, 3, 1, 1.8, 1.3, z + 0.12),
            *_banana(hi, 6.2, z + 0.12, "#c0392b"), *_banana(lo, 6.2, z + 0.12, "#14181e"),
            *_banana(hi, 2.6, z + 0.12, "#c0392b"), *_banana(lo, 2.6, z + 0.12, "#14181e"),
            {**_box3d(1.6, 1.0, 0.4, "#f2f2f2", pos=[-12.4, 1.6, z + 0.32]), "role": "switch"},
            *vents,
        ]}


@dataclass
class FPGABoard(Component):
    """FPGA development board: PCB with the big chip, headers, and mounting holes."""

    component_type = "FPGABoard"

    def __init__(self, center=(0, 0), angle=0, **kwargs):
        _set_common_free_space_fields(self, center, angle, kwargs, color="#1e6b47", opacity=1.0, material_preset="aluminum", label=kwargs.get("label", "FPGA"))

    def ports(self) -> dict[str, Port]:
        return {
            "io1": Port("io1", Vec3(-10.0, 0.0, 0), orientation_deg=180, width=2.0, kind="electrical"),
            "io2": Port("io2", Vec3(10.0, 0.0, 0), orientation_deg=0, width=2.0, kind="electrical"),
            # one beside each other header pin the 2D art draws: io3 to io6 on the left, io7 to io10 on the right
            **{f"io{index}": Port(f"io{index}", Vec3(side * 10.0, y, 0), orientation_deg=90 - 90 * side, width=2.0,
                                  kind="electrical")
               for index, (side, y) in enumerate([(side, row * 10.0 / 0.7) for side in (-1, 1)
                                                  for row in (0.3, 0.15, -0.15, -0.3)], start=3)},
        }

    def geometry_2d(self) -> dict[str, Any]:
        pins = [{"type": "line", "x1": x, "y1": 3.4, "x2": x, "y2": 4.3, "stroke": "#c8a24b", "stroke_width": 0.22, "opacity": self.opacity} for x in (-2.1, -0.7, 0.7, 2.1)]
        pins += [{"type": "line", "x1": x, "y1": -3.4, "x2": x, "y2": -4.3, "stroke": "#c8a24b", "stroke_width": 0.22, "opacity": self.opacity} for x in (-2.1, -0.7, 0.7, 2.1)]
        holes = [{"type": "circle", "cx": sx * 8.8, "cy": sy * 5.8, "r": 0.55, "fill": "#f2f4f6", "stroke": "#c8a24b", "stroke_width": 0.16, "opacity": self.opacity} for sx in (-1, 1) for sy in (-1, 1)]
        return {"type": "group", "children": [
            {"type": "rect", "cx": 0, "cy": 0, "w": 20, "h": 14, "fill": self.color, "stroke": "#124430", "stroke_width": 0.16, "opacity": self.opacity},
            {"type": "rect", "cx": 0, "cy": 0, "w": 6.4, "h": 6.4, "fill": "#14181e", "opacity": self.opacity},
            {"type": "rect", "cx": 0, "cy": 0, "w": 4.2, "h": 4.2, "fill": "#2b3038", "opacity": self.opacity},
            *pins,
            {"type": "rect", "cx": 0, "cy": 5.9, "w": 12, "h": 1.2, "fill": "#14181e", "opacity": self.opacity},
            {"type": "rect", "cx": 0, "cy": -5.9, "w": 12, "h": 1.2, "fill": "#14181e", "opacity": self.opacity},
            {"type": "rect", "cx": -6.6, "cy": 2.4, "w": 3.0, "h": 2.0, "fill": "#2b3038", "opacity": self.opacity},
            {"type": "rect", "cx": 6.4, "cy": -2.2, "w": 2.4, "h": 3.0, "fill": "#c8ccd2", "opacity": self.opacity},
            *holes,
        ]}

    def geometry_3d(self) -> dict[str, Any]:
        standoffs = [{"shape": "cylinder", "radius": 0.5, "height": 1.6, "position": [sx * 8.8, 0.8, sz * 5.8], "material": {"color": "#c8a24b", "preset": "gold", "metalness": 0.7, "roughness": 0.35}} for sx in (-1, 1) for sz in (-1, 1)]
        return {"shape": "group", "children": [
            *standoffs,
            _box3d(20, 0.6, 14, self.color, pos=[0, 1.9, 0]),
            _box3d(6.4, 1.1, 6.4, "#14181e", pos=[0, 2.7, 0]),
            _box3d(4.2, 0.5, 4.2, "#2b3038", pos=[0, 3.5, 0]),            # die cap
            _box3d(12, 1.4, 1.2, "#14181e", pos=[0, 2.9, -5.9]),
            _box3d(12, 1.4, 1.2, "#14181e", pos=[0, 2.9, 5.9]),
            _box3d(2.4, 1.6, 3.0, "#c8ccd2", pos=[6.4, 2.7, 2.2]),        # USB shell
            _box3d(3.0, 0.8, 2.0, "#2b3038", pos=[-6.6, 2.5, -2.4]),      # companion IC
            _box3d(1.2, 1.2, 2.6, "#c8ccd2", pos=[-9.6, 2.6, 0]),         # io1 edge connector
            _box3d(1.2, 1.2, 2.6, "#c8ccd2", pos=[9.6, 2.6, 0]),          # io2 edge connector
        ]}


@dataclass
class OSA(Component):
    """Optical spectrum analyzer: big screen with spectral peaks, fiber input. ``trace`` (points from
    ``screen_points``, as ``Spectrum.show`` sets them) puts a computed spectrum on the 2D screen in place of the demo
    peaks; the 3D screen keeps its demo peak."""

    component_type = "OSA"
    SCREEN = (-0.68, -0.33, 0.36, 0.33)                  # the screen of the pic, in symbol centimetres

    def __init__(self, center=(0, 0), angle=0, trace=None, **kwargs):
        _set_common_free_space_fields(self, center, angle, kwargs, color="#e8eaee", opacity=1.0, material_preset="aluminum", label=kwargs.get("label", "OSA"))
        self.trace = None if trace is None else [(float(u), float(v)) for u, v in trace]

    def screen_data(self) -> list[tuple[str, Any, str]]:
        """What the 2D art shows on its screen in place of its demo peaks: ``(kind, value, colour)``."""

        return [] if self.trace is None else [("trace", self.trace, _DATA)]

    def ports(self) -> dict[str, Port]:
        return {"in": Port("in", Vec3(-10.0, -9.0, 0), orientation_deg=270, width=1.8, kind="fiber")}

    def geometry_2d(self) -> dict[str, Any]:
        spectrum = ([(-12.6, -2.0), (-10.8, -2.0), (-10.2, 4.6), (-9.6, -2.0), (-7.4, -2.0), (-6.9, 2.2), (-6.4, -2.0), (-3.6, -2.0), (-3.1, 6.2), (-2.6, -2.0), (0.4, -2.0), (0.9, 1.4), (1.4, -2.0), (3.4, -2.0)]
                    if self.trace is None else _on_screen(self.trace, -4.6, 2.2, 17.6, 11.2))
        buttons = [{"type": "rect", "cx": 8.2 + c * 2.5, "cy": y, "w": 1.8, "h": 1.3, "fill": "#3a4049", "opacity": self.opacity} for c in range(2) for y in (4.2, 1.8, -0.6)]
        return {"type": "group", "children": [
            {"type": "rect", "cx": 0, "cy": 0, "w": 30, "h": 18, "fill": self.color, "stroke": "#9aa1ab", "stroke_width": 0.16, "opacity": self.opacity},
            {"type": "rect", "cx": -4.6, "cy": 2.2, "w": 17.6, "h": 11.2, "fill": _SCREEN, "opacity": self.opacity},
            {"type": "line", "x1": -12.6, "y1": -2.0, "x2": 3.4, "y2": -2.0, "stroke": "#233040", "stroke_width": 0.1, "opacity": self.opacity},
            {"type": "polyline", "points": spectrum, "stroke": _TRACE, "stroke_width": 0.4, "opacity": self.opacity},
            *buttons,
            {"type": "circle", "cx": 9.4, "cy": -4.4, "r": 1.5, "fill": _FACE, "stroke": "#14181e", "stroke_width": 0.14, "opacity": self.opacity},
            {"type": "circle", "cx": -10.0, "cy": -6.6, "r": 1.0, "fill": "#2e7d4f", "stroke": "#14181e", "stroke_width": 0.14, "opacity": self.opacity},
            {"type": "line", "x1": -10.0, "y1": -7.6, "x2": -10.0, "y2": -9.0, "stroke": "#2e7d4f", "stroke_width": 0.32},
        ]}

    def geometry_3d(self) -> dict[str, Any]:
        # An optical spectrum analyser: a large screen on the left of a dark panel, two columns of soft keys
        # beside it and the keypad and knob on the right, the fibre input at the bottom left, a carry handle.
        z = 8.0
        return {"shape": "group", "children": [
            _box3d(30, 18, 16, self.color, pos=[0, 9.0, 0]),
            _panel(29.2, 17.2, z, _PANEL_DARK, y=9.0),
            *_display(-4.6, 11.0, 17.0, 10.6, z + 0.12, _TRACE, trace=[(-1, -0.8), (-0.3, -0.7), (-0.1, 0.0), (0.0, 0.8), (0.1, 0.0), (0.3, -0.7), (1, -0.8)]),
            *_keys(5.8, 15.0, 1, 6, 1.9, 1.3, z + 0.12),
            *_keys(8.6, 15.0, 3, 3, 1.7, 1.2, z + 0.12),
            *_knob(10.6, 7.0, 1.5, z + 0.12),
            _box3d(1.2, 0.9, 0.3, "#8d949c", pos=[-13.0, 2.2, z + 0.27]),
            _connector(-10.0, 8.9, color="#2e7d4f"),                       # fiber input on the front panel (port)
            *_carry_handle(18.0, 10.0),
        ]}


@dataclass
class OpticalPowerMeter(Component):
    """Optical power meter: big numeric readout, fiber input on top. ``reading`` (a short text, such as ``"1.20 mW"``)
    is drawn on the 2D display in place of the demo readout."""

    component_type = "OpticalPowerMeter"
    SCREEN = (-0.26, 0.05, 0.26, 0.43)                   # the display of the pic, in symbol centimetres

    def __init__(self, center=(0, 0), angle=0, reading=None, **kwargs):
        _set_common_free_space_fields(self, center, angle, kwargs, color=_BODY, opacity=1.0, material_preset="aluminum", label=kwargs.get("label", "Power Meter"))
        self.reading = None if reading is None else str(reading)

    def screen_data(self) -> list[tuple[str, Any, str]]:
        """What the 2D art shows on its display in place of its demo digits: ``(kind, value, colour)``."""

        return [] if self.reading is None else [("text", self.reading, _DATA)]

    def ports(self) -> dict[str, Port]:
        return {"in": Port("in", Vec3(0.0, 9.0, 0), orientation_deg=90, width=1.8, kind="fiber")}

    def geometry_2d(self) -> dict[str, Any]:
        buttons = [{"type": "rect", "cx": -3.4 + c * 3.4, "cy": -5.2, "w": 2.4, "h": 1.5, "fill": "#4a5059", "opacity": self.opacity} for c in range(3)]
        readout = ([{"type": "rect", "cx": -0.8, "cy": 2.4, "w": 6.6, "h": 2.2, "fill": "#1d4436", "opacity": self.opacity},
                    {"type": "rect", "cx": 2.6, "cy": -0.4, "w": 3.0, "h": 1.2, "fill": "#1d4436", "opacity": self.opacity}]
                   if self.reading is None else
                   [{"type": "text", "text": self.reading, "x": 0.0, "y": 1.6, "size": 1.8, "fill": _DATA, "opacity": self.opacity}])
        return {"type": "group", "children": [
            {"type": "rect", "cx": 0, "cy": 0, "w": 13, "h": 18, "fill": self.color, "stroke": "#14181e", "stroke_width": 0.16, "opacity": self.opacity},
            {"type": "rect", "cx": 0, "cy": 7.6, "w": 3.2, "h": 1.6, "fill": "#2e7d4f", "opacity": self.opacity},
            {"type": "line", "x1": 0.0, "y1": 8.4, "x2": 0.0, "y2": 9.0, "stroke": "#2e7d4f", "stroke_width": 0.32},
            {"type": "rect", "cx": 0, "cy": 1.6, "w": 10.2, "h": 6.6, "fill": _SCREEN, "opacity": self.opacity},
            *readout,
            *buttons,
        ]}

    def geometry_3d(self) -> dict[str, Any]:
        # A handheld power meter console (Thorlabs PM100D, 183 x 109 x 40 mm): a red rubber boot round a light
        # grey front, a black bezel round the backlit LCD with the reading, the navigation cross round OK and
        # the wavelength, relative and backlight keys on the right; the sensor DB9, USB, SMA output and power
        # key along the top edge; it stands on its kickstand.
        W, H, D = 17.0, 17.0 * 109 / 183, 17.0 * 40 / 183
        y, z = H / 2.0 + 0.3, D / 2.0
        boot = {"color": "#c8312b", "roughness": 0.75, "preset": "plastic"}
        grey = "#d8dbdf"
        return {"shape": "group", "children": [
            {**_box3d(W, H, D, boot["color"], pos=[0, y, 0], preset="plastic", roughness=0.75), "role": "boot"},
            _box3d(W - 1.4, H - 1.4, 0.12, grey, pos=[0, y, z + 0.06]),
            *_display(-2.6, y + 0.2, 8.6, 6.0, z + 0.12, "#cfd8cc", bezel="#1b1e22", screen="#e8ece6", intensity=1.3),
            _box3d(5.0, 1.5, 0.05, "#2b3036", pos=[-2.6, y + 0.6, z + 0.4]),                  # the reading
            {"shape": "cylinder", "role": "key", "radius": 0.7, "height": 0.35, "position": [4.9, y + 1.3, z + 0.3], "rotation": [1.5708, 0, 0], "material": {"color": "#8d949c"}},
            *[{"shape": "cylinder", "role": "key", "radius": 0.5, "height": 0.35, "position": [4.9 + dx, y + 1.3 + dy, z + 0.3], "rotation": [1.5708, 0, 0], "material": {"color": "#b4bac1"}}
              for dx, dy in ((1.4, 0.0), (-1.4, 0.0), (0.0, 1.4), (0.0, -1.4))],
            *_keys(4.2, y - 1.4, 2, 1, 1.4, 1.0, z + 0.12, color="#b4bac1"),
            *_keys(4.9, y - 2.7, 1, 1, 1.4, 1.0, z + 0.12, color="#b4bac1"),
            _box3d(2.4, 0.7, 1.0, "#2b3036", pos=[4.0, H + 0.65, 0]),                          # sensor DB9
            _box3d(0.9, 0.4, 0.6, "#c9ced4", pos=[-1.6, H + 0.5, 0]),                          # USB
            {"shape": "cylinder", "radius": 0.35, "height": 0.7, "position": [0.6, H + 0.65, 0], "material": {"color": "#d4af37", "metalness": 0.8, "roughness": 0.35}},
            {"shape": "cylinder", "radius": 0.45, "height": 0.4, "position": [-5.5, H + 0.5, 0], "material": {"color": "#1b1e22"}},
            {**_box3d(W * 0.6, H * 0.75, 0.35, "#1b1e22", pos=[0, H * 0.4, -z - 1.0], preset="plastic"), "rotation": [-0.35, 0, 0], "role": "stand"},
        ]}


@dataclass
class WaveformGenerator(Component):
    """Arbitrary waveform generator: synthesized wave on screen, two outputs.

    Named WaveformGenerator because AWG already means arrayed waveguide
    grating (on-chip) in this package. ``sync`` is the trigger output that a scope or a counter takes; ``JACKS``
    (symbol centimetres along the bottom edge) is the plan of the ports and of the TikZ pic ``od awginstrument``."""

    component_type = "WaveformGenerator"
    UNIT = 16.25
    JACKS = {"sync": -0.4, "out1": 0.05, "out2": 0.5}
    _art_scale_from_ports = True

    def __init__(self, center=(0, 0), angle=0, **kwargs):
        _set_common_free_space_fields(self, center, angle, kwargs, color="#e8eaee", opacity=1.0, material_preset="aluminum", label=kwargs.get("label", "AWG"))

    def ports(self) -> dict[str, Port]:
        u = self.UNIT
        return {name: Port(name, Vec3(x * u, -0.6 * u, 0), orientation_deg=270, width=1.8, kind="electrical")
                for name, x in self.JACKS.items()}

    def geometry_2d(self) -> dict[str, Any]:
        # half sine, half square: the "arbitrary" giveaway
        wave = [(-10.6, 0.8), (-9.6, 3.6), (-8.6, 0.8), (-7.6, -2.0), (-6.6, 0.8), (-5.6, 0.8), (-5.6, 3.6), (-3.6, 3.6), (-3.6, -2.0), (-1.6, -2.0), (-1.6, 3.6), (-0.2, 3.6)]
        return {"type": "group", "children": [
            {"type": "rect", "cx": 0, "cy": 0, "w": 26, "h": 14, "fill": self.color, "stroke": "#9aa1ab", "stroke_width": 0.16, "opacity": self.opacity},
            {"type": "rect", "cx": -5.4, "cy": 1.2, "w": 12.4, "h": 8.2, "fill": _SCREEN, "opacity": self.opacity},
            {"type": "polyline", "points": wave, "stroke": _TRACE, "stroke_width": 0.4, "opacity": self.opacity},
            {"type": "circle", "cx": 9.4, "cy": 2.6, "r": 1.4, "fill": _FACE, "stroke": "#14181e", "stroke_width": 0.12, "opacity": self.opacity},
            {"type": "rect", "cx": 9.4, "cy": -1.4, "w": 4.6, "h": 1.4, "fill": _FACE, "opacity": self.opacity},
            *[{"type": "circle", "cx": x * self.UNIT, "cy": -0.525 * self.UNIT, "r": 0.075 * self.UNIT, "fill": "#c8ccd2",
               "stroke": "#14181e", "stroke_width": 0.14, "opacity": self.opacity} for x in self.JACKS.values()],
        ]}

    def geometry_3d(self) -> dict[str, Any]:
        # A waveform generator: a dark panel in a silver case, the screen on the left with soft keys under it,
        # the keypad and the knob on the right, the two channel outputs along the bottom (at the ports).
        z = 6.5
        return {"shape": "group", "children": [
            _box3d(26, 14, 13, self.color, pos=[0, 7.0, 0]),
            _panel(25.2, 13.2, z, _PANEL_DARK, y=7.0),
            *_display(-5.4, 8.6, 12.0, 7.2, z + 0.12, _TRACE),
            *_keys(-10.0, 4.0, 6, 1, 1.85, 1.3, z + 0.12),
            *_keys(3.2, 12.0, 3, 4, 1.6, 1.15, z + 0.12),
            *_knob(9.8, 9.6, 1.5, z + 0.12),
            *[piece for x in self.JACKS.values() for piece in _bnc(x * self.UNIT, 2.2, z + 0.12)],
            _box3d(1.2, 0.9, 0.3, "#8d949c", pos=[-11.2, 2.2, z + 0.27]),
        ]}


@dataclass
class LaserDriver(Component):
    """Laser diode controller: current/TEC readouts, big adjust knob, key switch. Under the panel: ``mod`` (the
    modulation input a servo drives), ``tec`` (the TEC output to the laser mount) and ``out`` (the laser current).

    ``JACKS`` (in symbol centimetres, along the bottom edge) is the plan of the ports and of the TikZ pic
    ``od laserdriver``; ``UNIT`` scene units are one centimetre of it.
    """

    component_type = "LaserDriver"
    UNIT = 16.25                                           # the case is 1.6 cm wide in the pic and 26 units here
    JACKS = {"mod": -0.5, "tec": 0.0, "out": 0.42}
    _art_scale_from_ports = True                           # the plan sets both: the art keeps its size

    def __init__(self, center=(0, 0), angle=0, bias_a: float | None = None, gain_a_per_v: float | None = None,
                 **kwargs):
        # the signal chain's numbers: out = bias_a + gain_a_per_v x mod; None is its model default
        self.bias_a, self.gain_a_per_v = bias_a, gain_a_per_v
        _set_common_free_space_fields(self, center, angle, kwargs, color="#d9dcdf", opacity=1.0, material_preset="aluminum", label=kwargs.get("label", "Laser Driver"))

    def ports(self) -> dict[str, Port]:
        u = self.UNIT
        return {name: Port(name, Vec3(x * u, -0.6 * u, 0), orientation_deg=270, width=1.8, kind="electrical")
                for name, x in self.JACKS.items()}

    def geometry_2d(self) -> dict[str, Any]:
        u = self.UNIT
        jacks = [{"type": "circle", "cx": x * u, "cy": -0.525 * u, "r": 0.075 * u, "fill": "#c8ccd2", "stroke": "#14181e",
                  "stroke_width": 0.14, "opacity": self.opacity} for x in self.JACKS.values()]
        return {"type": "group", "children": [
            {"type": "rect", "cx": 0, "cy": 0, "w": 1.6 * u, "h": 0.9 * u, "fill": self.color, "stroke": "#14181e", "stroke_width": 0.16, "opacity": self.opacity},
            {"type": "rect", "cx": -7.0, "cy": 1.8, "w": 9.6, "h": 3.6, "fill": _SCREEN, "opacity": self.opacity},
            {"type": "rect", "cx": -8.4, "cy": 1.8, "w": 4.6, "h": 1.8, "fill": "#1d4436", "opacity": self.opacity},
            {"type": "rect", "cx": -7.0, "cy": -2.6, "w": 9.6, "h": 2.6, "fill": _SCREEN, "opacity": self.opacity},
            {"type": "rect", "cx": -8.6, "cy": -2.6, "w": 4.0, "h": 1.3, "fill": "#6b4a1d", "opacity": self.opacity},
            {"type": "circle", "cx": 5.2, "cy": 0.4, "r": 2.6, "fill": _FACE, "stroke": "#14181e", "stroke_width": 0.16, "opacity": self.opacity},
            {"type": "line", "x1": 5.2, "y1": 0.4, "x2": 5.2, "y2": 2.6, "stroke": "#c8ccd2", "stroke_width": 0.3, "opacity": self.opacity},
            {"type": "circle", "cx": 10.4, "cy": 2.2, "r": 1.0, "fill": "#c0392b", "stroke": "#14181e", "stroke_width": 0.14, "opacity": self.opacity},
            *jacks,
        ]}

    def geometry_3d(self) -> dict[str, Any]:
        # A benchtop laser diode controller (Thorlabs LDC205C): a light grey case with a darker band across the
        # top of the front, a yellow-green five-digit LED display with its unit and status LEDs, the DISPLAY and
        # MODE keys in two groups, LASER ON with its LED, the large current knob, the white line switch, and the
        # modulation BNC, the TEC and the laser outputs at the ports along the bottom.
        z = 7.5
        band = "#5b6168"
        return {"shape": "group", "children": [
            _box3d(26, 12, 15, self.color, pos=[0, 6.0, 0]),
            _box3d(25.2, 1.8, 0.12, band, pos=[0, 11.0, z + 0.06]),
            *_display(-6.6, 7.6, 10.0, 2.8, z, "#c8f03c", bezel="#141619", intensity=1.9),
            _led(-0.6, 8.4, z, "#3fae5a"), _led(-0.6, 7.0, z, "#3a4049"),
            _led(2.4, 8.8, z, "#c0392b"), _led(2.4, 7.8, z, "#c0392b"), _led(2.4, 6.8, z, "#c0392b"),
            _box3d(6.0, 3.6, 0.06, "#c9ccd0", pos=[-1.4, 4.2, z + 0.032]), _box3d(4.6, 3.6, 0.06, "#c9ccd0", pos=[4.7, 4.2, z + 0.032]),
            *_keys(0.4, 5.0, 1, 2, 2.0, 1.6, z + 0.06), *_keys(5.4, 5.0, 1, 2, 2.0, 1.6, z + 0.06),
            *_keys(9.2, 8.4, 1, 1, 2.0, 1.8, z),
            _led(7.4, 8.4, z, "#3fae5a"),
            *_knob(9.6, 4.6, 1.8, z),
            {**_box3d(2.4, 1.6, 0.5, "#f4f4f4", pos=[-9.8, 4.2, z + 0.25]), "role": "switch"},
            *_bnc(self.JACKS["mod"] * self.UNIT, 1.4, z, r=0.45),                               # modulation input
            *[_box3d(2.4, 1.1, 0.6, "#2b3036", pos=[self.JACKS[name] * self.UNIT, 1.4, z + 0.3])
              for name in ("tec", "out")],                                                      # TEC and laser outputs
            *[_box3d(2.4, 0.6, 3.0, "#8d949c", pos=[sx * 10.5, 0.306, z - 1.6]) for sx in (-1, 1)],
        ]}


@dataclass
class DAQ(Component):
    """Data-acquisition module: screw-terminal strip along the front, status LEDs."""

    component_type = "DAQ"
    _art_scale_from_ports = True        # the art spans ch1 to ch2: sized to the box, it missed ch2 by 6 units

    def __init__(self, center=(0, 0), angle=0, **kwargs):
        _set_common_free_space_fields(self, center, angle, kwargs, color="#b9bfc6", opacity=1.0, material_preset="aluminum", label=kwargs.get("label", "DAQ"))

    def ports(self) -> dict[str, Port]:
        return {
            "ch1": Port("ch1", Vec3(-7.5, -6.0, 0), orientation_deg=270, width=1.8, kind="electrical"),
            "ch2": Port("ch2", Vec3(7.5, -6.0, 0), orientation_deg=270, width=1.8, kind="electrical"),
        }

    def geometry_2d(self) -> dict[str, Any]:
        terminals = [{"type": "rect", "cx": -8.8 + i * 2.2, "cy": -3.2, "w": 1.5, "h": 1.8, "fill": "#c8ccd2", "stroke": "#14181e", "stroke_width": 0.1, "opacity": self.opacity} for i in range(9)]
        return {"type": "group", "children": [
            {"type": "rect", "cx": 0, "cy": 0, "w": 22, "h": 12, "fill": self.color, "stroke": "#2b3038", "stroke_width": 0.16, "opacity": self.opacity},
            {"type": "rect", "cx": 0, "cy": -3.2, "w": 21, "h": 2.8, "fill": "#2b3038", "opacity": self.opacity},
            *terminals,
            *[{"type": "line", "x1": x, "y1": -4.6, "x2": x, "y2": -6.0, "stroke": "#c8ccd2", "stroke_width": 0.3} for x in (-7.5, 7.5)],
            {"type": "rect", "cx": -4.6, "cy": 2.6, "w": 11.5, "h": 3.4, "fill": "#3a4049", "opacity": self.opacity},
            {"type": "circle", "cx": 5.4, "cy": 2.6, "r": 0.55, "fill": _TRACE, "opacity": self.opacity},
            {"type": "circle", "cx": 7.6, "cy": 2.6, "r": 0.55, "fill": "#e0a83a", "opacity": self.opacity},
        ]}

    def geometry_3d(self) -> dict[str, Any]:
        # A BNC data-acquisition box: a silver case, a dark front panel with a black name band, the analogue
        # BNCs in a grid of two rows of four with a label over each (channels 1 and 2 at the ports, bottom row),
        # and the power and status LEDs at the top right.
        z = 5.0
        cols = (-7.5, -2.5, 2.5, 7.5)
        children: list[dict[str, Any]] = [
            _box3d(22, 12, 10, self.color, pos=[0, 6.0, 0]),
            _panel(21.2, 11.2, z, _PANEL_DARK, y=6.0),
            _box3d(21.2, 1.6, 0.06, "#14171b", pos=[0, 10.8, z + 0.15]),
            _led(8.2, 10.8, z + 0.18, "#3fae5a"), _led(9.4, 10.8, z + 0.18, "#e0a52c"),
        ]
        for y in (2.2, 6.4):
            for x in cols:
                children += _bnc(x, y, z + 0.12)
                children.append(_box3d(2.0, 0.5, 0.05, "#e5e7eb", pos=[x, y + 1.7, z + 0.15]))
        return {"shape": "group", "children": children}


@dataclass
class VNA(Component):
    """Vector network analyzer: S-parameter dip on screen, two RF ports."""

    component_type = "VNA"

    def __init__(self, center=(0, 0), angle=0, **kwargs):
        _set_common_free_space_fields(self, center, angle, kwargs, color="#c9cdd2", opacity=1.0, material_preset="aluminum", label=kwargs.get("label", "VNA"))

    def ports(self) -> dict[str, Port]:
        return {
            "p1": Port("p1", Vec3(-5.5, -8.0, 0), orientation_deg=270, width=1.8, kind="electrical"),
            "p2": Port("p2", Vec3(2.5, -8.0, 0), orientation_deg=270, width=1.8, kind="electrical"),
        }

    def geometry_2d(self) -> dict[str, Any]:
        # a classic S21 resonance notch
        dip = [(-10.6, 4.8), (-6.6, 4.6), (-4.8, 4.0), (-3.8, 0.2), (-3.2, -1.8), (-2.6, 0.2), (-1.6, 4.0), (0.2, 4.6), (3.6, 4.8)]
        return {"type": "group", "children": [
            {"type": "rect", "cx": 0, "cy": 0, "w": 25, "h": 16, "fill": self.color, "stroke": "#14181e", "stroke_width": 0.16, "opacity": self.opacity},
            {"type": "rect", "cx": -3.4, "cy": 2.0, "w": 15.4, "h": 9.4, "fill": _SCREEN, "opacity": self.opacity},
            {"type": "line", "x1": -10.6, "y1": -2.4, "x2": 3.6, "y2": -2.4, "stroke": "#233040", "stroke_width": 0.1, "opacity": self.opacity},
            {"type": "polyline", "points": dip, "stroke": "#e0a83a", "stroke_width": 0.4, "opacity": self.opacity},
            {"type": "circle", "cx": 9.0, "cy": 3.4, "r": 1.3, "fill": _FACE, "stroke": "#14181e", "stroke_width": 0.12, "opacity": self.opacity},
            {"type": "rect", "cx": 9.0, "cy": -0.6, "w": 4.4, "h": 2.8, "fill": _FACE, "opacity": self.opacity},
            {"type": "circle", "cx": -5.5, "cy": -6.2, "r": 1.0, "fill": "#c8a24b", "stroke": "#14181e", "stroke_width": 0.14, "opacity": self.opacity},
            {"type": "circle", "cx": 2.5, "cy": -6.2, "r": 1.0, "fill": "#c8a24b", "stroke": "#14181e", "stroke_width": 0.14, "opacity": self.opacity},
            *[{"type": "line", "x1": x, "y1": -7.2, "x2": x, "y2": -8.0, "stroke": "#c8a24b", "stroke_width": 0.3} for x in (-5.5, 2.5)],
        ]}

    def geometry_3d(self) -> dict[str, Any]:
        # A vector network analyser: a light grey case, a large screen on the left, the keypad and knob on the
        # right, and the two test ports (N connectors) along the bottom at the ports.
        z = 7.5
        return {"shape": "group", "children": [
            _box3d(25, 16, 15, self.color, pos=[0, 8.0, 0]),
            _panel(24.2, 15.2, z, "#aeb4ba", y=8.0),
            *_display(-3.6, 9.8, 14.6, 9.0, z + 0.12, "#6fa8dc", trace=[(-1, 0.6), (-0.4, 0.55), (-0.15, 0.3), (0.0, -0.8), (0.15, 0.3), (0.4, 0.55), (1, 0.6)]),
            *_keys(6.4, 14.6, 3, 4, 1.6, 1.15, z + 0.12),
            *_knob(8.0, 6.6, 1.4, z + 0.12),
            *_bnc(-5.5, 2.2, z + 0.12, r=0.85), *_bnc(2.5, 2.2, z + 0.12, r=0.85),
            _box3d(1.2, 0.9, 0.3, "#8d949c", pos=[-10.8, 2.2, z + 0.27]),
        ]}


@dataclass
class LockInAmplifier(Component):
    """Lock-in amplifier: the signal input, the demodulated output (X) and the reference input on the front panel.

    One plan in symbol centimetres gives the ports, the 2D bounds and the TikZ pic ``od lockin``
    (od-instruments.tex): ``BODY`` is the half width and half height of the case, ``JACKS`` the place of each BNC
    along the bottom edge, ``SCREEN`` the display (x0, y0, x1, y1). The 3D case is a dual-phase DSP lock-in
    (SR830 kind, 432 x 133 mm front) at the same width: two readouts and the reference readout along the top, the
    phase knob, the BNCs at the ports.

    ``reading`` (a short text, such as ``"X = 1.2 mV"``) is drawn on the 2D display in place of the flat output line.
    """

    component_type = "LockInAmplifier"
    UNIT = 14.0                                            # scene units per symbol centimetre
    BODY = (0.95, 0.35)
    JACKS = {"in": -0.6, "out": -0.15, "ref": 0.65}         # signal in, X out, reference in: SR830 order
    SCREEN = (-0.85, -0.2, 0.1, 0.25)
    KNOB = (0.42, 0.06, 0.13)                              # the phase knob: x, y, radius
    READING_V = 0.6                                        # a reading sits above the input trace on the display
    _art_scale_from_ports = True                           # the plan sets both: the art keeps its size

    def __init__(self, center=(0, 0), angle=0, reading=None, **kwargs):
        _set_common_free_space_fields(self, center, angle, kwargs, color="#e8eaee", opacity=1.0,
                                      material_preset="aluminum", label=kwargs.get("label", "Lock-in amplifier"))
        self.reading = None if reading is None else str(reading)

    def screen_data(self) -> list[tuple[str, Any, str]]:
        """What the 2D art shows on its display in place of its flat output line: ``(kind, value, colour)``."""

        return [] if self.reading is None else [("text", self.reading, _DATA)]

    def ports(self) -> dict[str, Port]:
        u, y = self.UNIT, -(self.BODY[1] + 0.15) * self.UNIT       # the lowest point of each jack
        return {name: Port(name, Vec3(x * u, y, 0), orientation_deg=270, width=1.8, kind="electrical")
                for name, x in self.JACKS.items()}

    def geometry_2d(self) -> dict[str, Any]:
        u, (w, h), o = self.UNIT, self.BODY, self.opacity
        x0, y0, x1, y1 = (value * u for value in self.SCREEN)
        kx, ky, kr = (value * u for value in self.KNOB)
        noisy = [(x0 + (x1 - x0) * i / 40, (-0.06 + 0.07 * math.sin(i * 1.3) + 0.04 * math.sin(i * 4.1)) * u)
                 for i in range(41)]                       # the pic's input: a small signal in noise
        children = [
            {"type": "rect", "cx": 0, "cy": 0, "w": 2 * w * u, "h": 2 * h * u, "fill": self.color, "stroke": "#9aa1ab",
             "stroke_width": 0.16, "opacity": o},
            {"type": "rect", "cx": (x0 + x1) / 2, "cy": (y0 + y1) / 2, "w": x1 - x0, "h": y1 - y0, "fill": _SCREEN, "opacity": o},
            {"type": "polyline", "points": noisy, "stroke": "#64748b", "stroke_width": 0.25, "opacity": o},
            {"type": "line", "x1": -0.8 * u, "y1": 0.12 * u, "x2": 0.05 * u, "y2": 0.12 * u, "stroke": _TRACE,
             "stroke_width": 0.42, "opacity": o} if self.reading is None else
            {"type": "text", "text": self.reading, "x": (x0 + x1) / 2, "y": 0.12 * u, "size": 1.6, "fill": _DATA, "opacity": o},
            {"type": "circle", "cx": kx, "cy": ky, "r": kr, "fill": _FACE, "stroke": "#14181e", "stroke_width": 0.12, "opacity": o},
        ]
        for x in self.JACKS.values():
            children += [{"type": "circle", "cx": x * u, "cy": -(h + 0.075) * u, "r": 0.075 * u, "fill": "#c8ccd2",
                          "stroke": "#14181e", "stroke_width": 0.12, "opacity": o}]
        return {"type": "group", "children": children}

    def geometry_3d(self) -> dict[str, Any]:
        u, (w, h) = self.UNIT, self.BODY
        width, height, depth, z = 2 * w * u, 2 * h * u, 20.0, 6.0      # the front face at z, near the ports
        lcd = "#c8f03c"
        return {"shape": "group", "children": [
            _box3d(width, height, depth, self.color, pos=[0, height / 2.0, z - depth / 2.0]),
            _panel(width - 0.8, height - 0.8, z, "#b9bec6", y=height / 2.0),
            *_display(-8.6, 7.4, 6.4, 2.0, z + 0.12, lcd, bezel="#141619", intensity=1.6),    # channel 1 (X)
            *_display(-1.4, 7.4, 6.4, 2.0, z + 0.12, lcd, bezel="#141619", intensity=1.6),    # channel 2 (Y)
            *_display(8.6, 7.4, 5.6, 2.0, z + 0.12, lcd, bezel="#141619", intensity=1.6),     # reference
            *_keys(-11.6, 4.6, 6, 1, 1.6, 1.1, z + 0.12),
            *_keys(7.0, 4.6, 3, 1, 1.6, 1.1, z + 0.12),
            *_knob(self.KNOB[0] * u, 4.2, 1.2, z + 0.12),
            *[piece for x in self.JACKS.values() for piece in _bnc(x * u, 2.0, z + 0.12)],
            {**_box3d(1.4, 1.0, 0.4, "#f2f2f2", pos=[-12.0, 2.0, z + 0.32]), "role": "switch"},
        ]}


@dataclass
class VacuumPump(Component):
    """Vacuum pump: motor body, pump cylinder, inlet flange, feet. Hoses are
    drawn with free routes — no ports."""

    component_type = "VacuumPump"

    def __init__(self, center=(0, 0), angle=0, **kwargs):
        _set_common_free_space_fields(self, center, angle, kwargs, color="#3a4049", opacity=1.0, material_preset="steel", label=kwargs.get("label", "Vacuum Pump"))

    def ports(self) -> dict[str, Port]:
        return {}

    def geometry_2d(self) -> dict[str, Any]:
        return {"type": "group", "children": [
            {"type": "rect", "cx": 0, "cy": -5.6, "w": 16, "h": 1.4, "fill": "#1f242b", "opacity": self.opacity},
            {"type": "rect", "cx": -3.4, "cy": -0.6, "w": 9.0, "h": 8.6, "fill": self.color, "stroke": "#1f242b", "stroke_width": 0.16, "opacity": self.opacity},
            {"type": "circle", "cx": -3.4, "cy": -0.6, "r": 2.6, "fill": "#2b3038", "stroke": "#14181e", "stroke_width": 0.14, "opacity": self.opacity},
            {"type": "circle", "cx": -3.4, "cy": -0.6, "r": 0.7, "fill": "#71717a", "opacity": self.opacity},
            {"type": "rect", "cx": 4.6, "cy": -1.4, "w": 6.2, "h": 6.9, "fill": "#4a5059", "stroke": "#1f242b", "stroke_width": 0.14, "opacity": self.opacity},
            *[{"type": "line", "x1": 1.8, "y1": -3.6 + i * 1.5, "x2": 7.4, "y2": -3.6 + i * 1.5, "stroke": "#2b3038", "stroke_width": 0.16, "opacity": self.opacity} for i in range(4)],
            {"type": "rect", "cx": -3.4, "cy": 4.9, "w": 2.2, "h": 2.4, "fill": "#71717a", "stroke": "#1f242b", "stroke_width": 0.12, "opacity": self.opacity},
            {"type": "rect", "cx": -3.4, "cy": 6.5, "w": 3.6, "h": 0.9, "fill": "#9aa0a6", "stroke": "#1f242b", "stroke_width": 0.12, "opacity": self.opacity},
        ]}

    def geometry_3d(self) -> dict[str, Any]:
        return {"shape": "group", "children": [
            _box3d(16, 1.4, 9, "#1f242b", pos=[0, 0.7, 0]),
            {"shape": "cylinder", "radius": 4.4, "height": 8.6, "rotation": [0, 0, 1.5708], "position": [-3.4, 5.8, 0], "material": {"color": "#3a4049", "preset": "steel", "metalness": 0.6, "roughness": 0.35}},
            _box3d(6.2, 6.9, 7.2, "#4a5059", pos=[4.6, 4.85, 0]),
            {"shape": "cylinder", "radius": 1.1, "height": 2.4, "position": [-3.4, 11.3, 0], "material": {"color": "#71717a", "preset": "steel"}},
            {"shape": "cylinder", "radius": 1.8, "height": 0.9, "position": [-3.4, 12.9, 0], "material": {"color": "#9aa0a6", "preset": "steel"}},
        ]}


class CoincidenceCounter(Component):
    """Coincidence counter: a pulse input for each channel, a timing window, the counts out to a computer.

    Its screen shows two pulses inside one window. Channel 1 is the top input.
    """

    component_type = "CoincidenceCounter"
    PITCH = 6.0          # between two inputs
    HALF = 14.0          # the ports stand this far either side of the centre

    def __init__(self, center=(0, 0), angle=0, channels=4, window_ns=10.0, **kwargs):
        from optodraw.components.devices import _channel_count

        self.channels = _channel_count(channels)
        self.window_ns = float(window_ns)
        self.material_preset = kwargs.get("material_preset", "aluminum")
        self.color = kwargs.get("color", "#e8eaee")
        self.opacity = kwargs.get("opacity", 1.0)
        self.label = kwargs.get("label", "Coincidence counter")
        self.transform = Transform.from_2d(*self._parse_center(center).as_2d(), angle)
        self._parent = None
        self._id = ""

    def _heights(self) -> list[float]:
        from optodraw.components.devices import _channel_heights

        return _channel_heights(self.channels, self.PITCH)

    def ports(self) -> dict[str, Port]:
        ports = {f"in{index}": Port(f"in{index}", Vec3(-self.HALF, y, 0.0), orientation_deg=180.0, width=0.9,
                                    kind="electrical")
                 for index, y in enumerate(self._heights(), start=1)}
        ports["data"] = Port("data", Vec3(self.HALF, 0.0, 0.0), orientation_deg=0.0, width=1.2, kind="electrical")
        return ports

    def symbol_1d(self) -> tuple[str, dict[str, Any]]:
        return "coincidence", {"count": self.channels}

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data.update(channels=self.channels, window_ns=self.window_ns)
        return data

    def _case(self) -> tuple[float, float]:
        """Half the width and half the height of the case: the symbol's proportions."""

        return self.HALF * 5.0 / 7.0, max(self.channels * 3.0 + 1.6, 7.6)

    def geometry_2d(self) -> dict[str, Any]:
        w, h = self._case()
        children = [
            {"type": "rect", "cx": 0.0, "cy": 0.0, "w": 2 * w, "h": 2 * h, "fill": self.color, "stroke": "#9aa1ab",
             "stroke_width": 0.16, "opacity": self.opacity},
            {"type": "rect", "cx": 0.0, "cy": 0.0, "w": 12.0, "h": 10.0, "fill": _SCREEN, "opacity": self.opacity},
            {"type": "line", "x1": w, "y1": 0.0, "x2": self.HALF, "y2": 0.0, "stroke": "#475569", "stroke_width": 0.5},
        ]
        for y in (2.0, -2.0):
            children.append({"type": "polyline", "points": [(-5.0, y - 1.0), (-0.6, y - 1.0), (-0.6, y + 1.0), (0.8, y + 1.0),
                                                             (0.8, y - 1.0), (5.0, y - 1.0)],
                             "stroke": _TRACE, "stroke_width": 0.4, "fill": "none", "opacity": self.opacity})
        for y in self._heights():
            children.append({"type": "line", "x1": -self.HALF, "y1": y, "x2": -w, "y2": y, "stroke": "#475569",
                             "stroke_width": 0.5})
        return {"type": "group", "children": children}

    def geometry_3d(self) -> dict[str, Any]:
        """A bench case with its screen on the front, a BNC input for each channel and the data port at the back."""

        w, h = self._case()
        height = 9.0
        children = [
            _box3d(2 * w, height, 2 * h, self.color, pos=[0, height / 2.0, 0]),
            _box3d(12.0, 6.0, 0.4, _SCREEN, pos=[0, height / 2.0 + 0.6, h + 0.2], preset="glass", emissive=_TRACE,
                   emissiveIntensity=0.7, opacity=1.0, transparent=False, transmission=0.0),
            _box3d(2.2, 1.2, 1.6, "#9aa1ab", pos=[w + 0.8, 2.2, 0]),                        # the data port
        ]
        children += [_connector(-w - 0.9, -y, r=0.7) | {"rotation": [0, 0, 1.5708]} for y in self._heights()]
        return {"shape": "group", "children": children}

    def physics_metadata(self) -> dict[str, Any]:
        return {"domain": "free_space", "component": "coincidence_counter", "channels": self.channels,
                "window_ns": self.window_ns}


def _beat_note(x: float, centre: float, floor: float) -> float:
    """A locked beat note as an RF spectrum analyser shows it: a narrow carrier on a noise pedestal, a servo bump
    either side, a ragged noise floor. The pic ``od esa`` draws the same function (x and the result in cm)."""

    d = x - centre
    return (floor + 0.012 * math.sin(math.radians(x * 7300.0)) + 0.008 * math.sin(math.radians(x * 11900.0))
            + 0.12 * math.exp(-(d / 0.12) ** 2) + 0.06 * math.exp(-((abs(d) - 0.2) / 0.03) ** 2)
            + 0.42 * math.exp(-(d / 0.012) ** 2))


@dataclass
class RFSpectrumAnalyzer(Component):
    """RF (electrical) spectrum analyser, the ESA: a screen with a beat note and the RF input under the panel. The
    optical one is ``OSA``.

    One plan in symbol centimetres gives the ports, the 2D bounds and the TikZ pic ``od esa`` (od-instruments.tex):
    ``BODY`` is the half width and half height of the case, ``SCREEN`` the display (x0, y0, x1, y1), ``KNOBS`` the
    two knobs and ``JACK`` the place of the RF input along the bottom edge. The 3D case is a bench analyser at the
    same width: the screen with the trace, the soft keys and the knobs, an N connector at the port.
    """

    component_type = "RFSpectrumAnalyzer"
    UNIT = 15.0                                            # scene units per symbol centimetre
    BODY = (0.8, 0.45)
    SCREEN = (-0.68, -0.33, 0.36, 0.33)
    KNOBS = ((0.58, 0.2), (0.58, -0.05))
    JACK = 0.58                                            # the RF input, under the knobs
    _art_unit = UNIT                                       # one port: the plan sets the size of the art

    def __init__(self, center=(0, 0), angle=0, **kwargs):
        _set_common_free_space_fields(self, center, angle, kwargs, color="#e8eaee", opacity=1.0,
                                      material_preset="aluminum", label=kwargs.get("label", "RF spectrum analyser"))

    def ports(self) -> dict[str, Port]:
        u = self.UNIT
        return {"in": Port("in", Vec3(self.JACK * u, -(self.BODY[1] + 0.15) * u, 0), orientation_deg=270, width=1.8,
                           kind="electrical")}

    def _trace(self) -> list[tuple[float, float]]:
        x0, y0, x1, _ = self.SCREEN
        centre, floor = (x0 + x1) / 2.0, y0 + 0.09
        xs = [x0 + 0.06 + (x1 - x0 - 0.12) * i / 160 for i in range(161)]
        return [(x, _beat_note(x, centre, floor)) for x in xs]

    def geometry_2d(self) -> dict[str, Any]:
        u, (w, h), o = self.UNIT, self.BODY, self.opacity
        x0, y0, x1, y1 = (value * u for value in self.SCREEN)
        children = [
            {"type": "rect", "cx": 0, "cy": 0, "w": 2 * w * u, "h": 2 * h * u, "fill": self.color, "stroke": "#9aa1ab",
             "stroke_width": 0.16, "opacity": o},
            {"type": "rect", "cx": (x0 + x1) / 2, "cy": (y0 + y1) / 2, "w": x1 - x0, "h": y1 - y0, "fill": _SCREEN,
             "opacity": o},
            {"type": "polyline", "points": [(x * u, y * u) for x, y in self._trace()], "stroke": _TRACE,
             "stroke_width": 0.4, "opacity": o},
            *[{"type": "circle", "cx": x * u, "cy": y * u, "r": 0.065 * u, "fill": _FACE, "stroke": "#14181e",
               "stroke_width": 0.12, "opacity": o} for x, y in self.KNOBS],
            {"type": "circle", "cx": self.JACK * u, "cy": -(h + 0.075) * u, "r": 0.075 * u, "fill": "#c8ccd2",
             "stroke": "#14181e", "stroke_width": 0.12, "opacity": o},
        ]
        return {"type": "group", "children": children}

    def geometry_3d(self) -> dict[str, Any]:
        # A bench spectrum analyser: a light case, a dark panel, the screen with the beat note at the left, two
        # columns of soft keys beside it, the knobs on the right and the N-type RF input at the port.
        u, (w, h) = self.UNIT, self.BODY
        width, height, depth = 2 * w * u, 2 * h * u, 15.0
        z, mid = depth / 2.0, height / 2.0
        x0, y0, x1, y1 = (value * u for value in self.SCREEN)
        spectrum = [(-1, -0.75), (-0.55, -0.7), (-0.4, -0.45), (-0.33, -0.7), (-0.15, -0.5), (-0.03, -0.35), (0.0, 0.85),
                    (0.03, -0.35), (0.15, -0.5), (0.33, -0.7), (0.4, -0.45), (0.55, -0.7), (1, -0.75)]
        return {"shape": "group", "children": [
            _box3d(width, height, depth, self.color, pos=[0, mid, 0]),
            _panel(width - 0.8, height - 0.8, z, _PANEL_DARK, y=mid),
            *_display((x0 + x1) / 2.0, mid + (y0 + y1) / 2.0, x1 - x0 - 0.8, y1 - y0 - 0.8, z + 0.12, "#6fa8dc",
                      trace=spectrum),
            *_keys(6.2, mid + 4.4, 1, 4, 1.8, 1.2, z + 0.12),
            *[piece for x, y in self.KNOBS for piece in _knob(x * u, mid + y * u, 1.0, z + 0.12)],
            *_bnc(self.JACK * u, 2.2, z + 0.12, r=0.85),
            _box3d(1.2, 0.9, 0.3, "#8d949c", pos=[-10.6, 1.2, z + 0.27]),          # the power key
        ]}
