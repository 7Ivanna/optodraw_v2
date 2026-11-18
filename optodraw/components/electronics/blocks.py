"""Blocks electronics components."""

from __future__ import annotations
import math
from collections import Counter
from typing import Any, Iterable
from optodraw.core.component import Component
from optodraw.core.ports import Port
from optodraw.core.transform import Vec3, as_vec3 as _as_vec3

from optodraw.components.electronics._shared import (
    BOARD_GREEN,
    BOARD_THICKNESS,
    CERAMIC,
    CHIP_BODY,
    CHIP_EDGE,
    COPPER,
    DIGITAL_BLUE,
    GOLD,
    GOLD_DARK,
    IC_BODY_THICKNESS,
    INK,
    MEMS_SILICON,
    SIGNAL_COLORS,
    _box3d,
    _circle,
    _converter_chip_2d,
    _converter_chip_3d,
    _converter_outline,
    _converter_symbol_2d,
    _converter_top_3d,
    _edge_positions,
    _grid_positions,
    _ic_package_geometry_2d,
    _ic_package_geometry_3d,
    _init_component,
    _line,
    _package_pins_2d,
    _package_style_key,
    _polygon,
    _polygon_centroid,
    _polyline,
    _ports_on_plan,
    _rect,
    _scaled,
    _style_key,
    _text,
)


class SignalArrow(Component):
    """Directional electrical signal annotation for drive and readout diagrams.

    Signal arrows are useful for indicating voltage, current, RF, clock, or
    digital flow without adding a physical component body.

    Parameters
    ----------
    start, end : tuple[float, float] | tuple[float, float, float] | Vec3
        Local start and end points for ports ``in`` and ``out``.
    center : tuple[float, float]
        Transform center applied to the whole arrow.
    angle : float
        Rotation angle in degrees.
    signal : str
        Signal family used to choose a default color. Common values include
        ``voltage``, ``current``, ``rf``, ``clock``, and ``digital``.
    width : float
        Line width for the arrow shaft.
    head_size : float
        Length of the triangular arrow head.
    color : str | None
        Optional explicit color. If omitted, ``signal`` chooses the color.
    opacity : float
        Arrow opacity used by 2D rendering.
    label : str
        Optional label stored on the component.
    """

    component_type = "SignalArrow"
    open_ports = ("in", "out")      # a mark: a route may meet its ends, and none has to

    def __init__(
        self,
        start=(-12.0, 0.0),
        end=(12.0, 0.0),
        *,
        center=(0, 0),
        angle: float = 0.0,
        signal: str = "voltage",
        width: float = 1.2,
        head_size: float = 4.0,
        color: str | None = None,
        opacity: float = 0.95,
        label: str = "",
    ):
        self.start = _as_vec3(start)
        self.end = _as_vec3(end)
        self.signal = signal
        self.width = width
        self.head_size = head_size
        _init_component(self, center, angle, color=color or SIGNAL_COLORS.get(signal, SIGNAL_COLORS["voltage"]), opacity=opacity, label=label)

    def ports(self) -> dict[str, Port]:
        angle = math.degrees(math.atan2(self.end.y - self.start.y, self.end.x - self.start.x))
        return {
            "in": Port("in", self.start, orientation_deg=angle + 180.0, width=self.width, kind="electrical"),
            "out": Port("out", self.end, orientation_deg=angle, width=self.width, kind="electrical"),
        }

    def geometry_2d(self) -> dict[str, Any]:
        dx = self.end.x - self.start.x
        dy = self.end.y - self.start.y
        length = math.hypot(dx, dy)
        if length <= 1e-9:
            return {"type": "group", "children": []}
        ux = dx / length
        uy = dy / length
        nx = -uy
        ny = ux
        head_size = min(max(self.head_size, 0.0), length * 0.45)
        base_x = self.end.x - ux * head_size
        base_y = self.end.y - uy * head_size
        half = head_size * 0.42
        head = [
            (self.end.x, self.end.y),
            (base_x + nx * half, base_y + ny * half),
            (base_x - nx * half, base_y - ny * half),
        ]
        return {
            "type": "group",
            "children": [
                _line(self.start.x, self.start.y, base_x, base_y, stroke=self.color, stroke_width=self.width, opacity=self.opacity),
                _polygon(head, fill=self.color, opacity=self.opacity),
            ],
        }


class RFDriver(Component):
    """RF amplifier or driver block for modulators and package launches.

    The driver exposes one input, two differential outputs, bias, and ground
    ports. It supports a schematic triangle in ``symbolic`` view and a compact
    package-like drawing in ``publication`` or ``physical`` views.

    Parameters
    ----------
    center : tuple[float, float]
        Component center in local scene coordinates.
    angle : float
        Rotation angle in degrees.
    length, width : float
        Body dimensions before ``visual_scale`` is applied.
    pad_size : float
        Size of electrical pads and default port width.
    output_gap : float | None
        Vertical spacing between ``out_p`` and ``out_n``. By default a fifth of ``length``: the outputs
        of the 2D art.
    visual_style : str
        One of ``symbolic``, ``publication``, or ``physical``.
    visual_scale : float
        Uniform scale factor applied to component geometry.
    color : str
        Driver body color.
    opacity : float
        Driver opacity used by 2D rendering.
    label : str
        Optional label stored on the component.
    """

    component_type = "RFDriver"
    _art_scale_from_ports = True        # the art spans in to out; bias and gnd sit on its leads (in units of length)

    def __init__(
        self,
        center=(0, 0),
        angle: float = 0.0,
        length: float = 38.0,
        width: float = 18.0,
        pad_size: float = 2.4,
        output_gap: float | None = None,
        visual_style: str = "publication",
        visual_scale: float = 1.0,
        color: str = CERAMIC,
        opacity: float = 0.95,
        label: str = "",
    ):
        self.visual_style = _style_key(visual_style)
        self.visual_scale = max(float(visual_scale), 0.05)
        self.length = _scaled(length, self.visual_scale)
        self.width = _scaled(width, self.visual_scale)
        self.pad_size = _scaled(pad_size, self.visual_scale)
        self.output_gap = self.length * 0.2 if output_gap is None else _scaled(output_gap, self.visual_scale)
        _init_component(self, center, angle, color=color, opacity=opacity, label=label)

    def ports(self) -> dict[str, Port]:
        return {
            "in": Port("in", Vec3(-self.length / 2.0, 0.0, 0.0), orientation_deg=180.0, width=self.pad_size, kind="electrical"),
            "out_p": Port("out_p", Vec3(self.length / 2.0, self.output_gap / 2.0, 0.0), orientation_deg=0.0, width=self.pad_size, kind="electrical"),
            "out_n": Port("out_n", Vec3(self.length / 2.0, -self.output_gap / 2.0, 0.0), orientation_deg=0.0, width=self.pad_size, kind="electrical"),
            "bias": Port("bias", Vec3(-self.length / 12.0, self.length * 5.0 / 12.0, 0.0), orientation_deg=90.0, width=self.pad_size, kind="electrical"),
            "gnd": Port("gnd", Vec3(-self.length / 12.0, -self.length * 5.0 / 12.0, 0.0), orientation_deg=-90.0, width=self.pad_size, kind="electrical"),
        }

    def _pad_children(self) -> list[dict[str, Any]]:
        """Return the RF driver's visible electrical pad rectangles."""

        return [
            _rect(-self.length / 2.0 + self.pad_size * 0.55, 0.0, self.pad_size, self.pad_size, fill=GOLD, opacity=self.opacity, stroke=GOLD_DARK, stroke_width=0.08),
            _rect(self.length / 2.0 - self.pad_size * 0.55, self.output_gap / 2.0, self.pad_size, self.pad_size, fill=GOLD, opacity=self.opacity, stroke=GOLD_DARK, stroke_width=0.08),
            _rect(self.length / 2.0 - self.pad_size * 0.55, -self.output_gap / 2.0, self.pad_size, self.pad_size, fill=GOLD, opacity=self.opacity, stroke=GOLD_DARK, stroke_width=0.08),
            _rect(0.0, self.width / 2.0 - self.pad_size * 0.55, self.pad_size, self.pad_size, fill=GOLD, opacity=self.opacity, stroke=GOLD_DARK, stroke_width=0.08),
            _rect(0.0, -self.width / 2.0 + self.pad_size * 0.55, self.pad_size, self.pad_size, fill=GOLD, opacity=self.opacity, stroke=GOLD_DARK, stroke_width=0.08),
        ]

    def _symbolic_2d(self) -> dict[str, Any]:
        length, width, gap = self.length, self.width, self.output_gap
        return {
            "type": "group",
            "children": [
                _line(-length / 2.0, 0.0, -length * 0.2, 0.0,
                      stroke="#000000", stroke_width=0.42),
                _polygon(
                    [(-length * 0.2, -width * 0.27),
                     (-length * 0.2, width * 0.27),
                     (length * 0.22, 0.0)],
                    fill="#ffffff", stroke="#000000", stroke_width=0.5,
                ),
                *[
                    _polyline(
                        [(length * 0.22, 0.0),
                         (length * 0.38, side * gap / 2.0),
                         (length / 2.0, side * gap / 2.0)],
                        stroke="#000000", stroke_width=0.42,
                    )
                    for side in (-1, 1)
                ],
                _line(0.0, width * 0.16, 0.0, width / 2.0,
                      stroke="#000000", stroke_width=0.34),
                _line(0.0, -width * 0.16, 0.0, -width / 2.0,
                      stroke="#000000", stroke_width=0.34),
                _text("RF", -length * 0.035, 0.0,
                      size=max(width * 0.2, 3.0), fill="#000000"),
            ],
        }

    def geometry_2d(self) -> dict[str, Any]:
        if self.visual_style == "symbolic":
            return self._symbolic_2d()
        rf_accent = SIGNAL_COLORS["rf"]
        body_fill = "#39414f"
        og = self.output_gap
        L, W = self.length, self.width
        tri = [(-L * 0.3, -W * 0.34), (-L * 0.3, W * 0.34), (L * 0.26, 0.0)]
        lw = max(W * 0.05, 0.5)
        return {
            "type": "group",
            "children": [
                _line(-L / 2.0, 0.0, -L * 0.3, 0.0, stroke=INK, stroke_width=lw, opacity=1.0),  # input
                _polygon(tri, fill=body_fill, opacity=self.opacity, stroke=rf_accent, stroke_width=lw),  # gain block
                # differential output fork (the defining feature of a driver)
                _line(L * 0.26, 0.0, L * 0.4, og / 2.0, stroke=INK, stroke_width=lw, opacity=1.0),
                _line(L * 0.26, 0.0, L * 0.4, -og / 2.0, stroke=INK, stroke_width=lw, opacity=1.0),
                _line(L * 0.4, og / 2.0, L / 2.0, og / 2.0, stroke=INK, stroke_width=lw, opacity=1.0),
                _line(L * 0.4, -og / 2.0, L / 2.0, -og / 2.0, stroke=INK, stroke_width=lw, opacity=1.0),
                # bias / gnd rails
                _line(0.0, W * 0.16, 0.0, W / 2.0, stroke=GOLD, stroke_width=lw * 0.7, opacity=0.85),
                _line(0.0, -W * 0.16, 0.0, -W / 2.0, stroke=GOLD_DARK, stroke_width=lw * 0.7, opacity=0.85),
                _text("RF", -L * 0.05, 0.0, size=max(W * 0.26, 4.5), fill="#ffffff", opacity=1.0, font_weight="bold"),
            ],
        }

    def geometry_3d(self) -> dict[str, Any]:
        L, W = self.length, self.width
        rf_accent = SIGNAL_COLORS["rf"]
        body_fill = "#39414f"
        og = self.output_gap
        tri = [(-L * 0.3, -W * 0.34), (-L * 0.3, W * 0.34), (L * 0.26, 0.0)]
        # the gold leads of the 2D art: the input into the base, and the fork from the tip out to both outputs
        lead_w = max(W * 0.07, 0.5)
        # each lead ends on the edge of the base plate (the body x 1.05), so lead and plate share no face; only the
        # fork's two runs overlap, at their bend
        runs = [((-L / 2.0, 0.0), (-L * 0.315, 0.0), 0.0, 0.0)]
        runs += [run for side in (1.0, -1.0) for run in (((L * 0.273, 0.0), (L * 0.4, side * og / 2.0), 0.0, lead_w / 4.0),
                                                         ((L * 0.4, side * og / 2.0), (L / 2.0, side * og / 2.0), lead_w / 4.0, 0.0))]
        leads = []
        for (x0, y0), (x1, y1), back, ahead in runs:
            length = math.hypot(x1 - x0, y1 - y0)
            shift = (ahead - back) / 2.0 / length
            leads.append(_box3d(length + back + ahead, lead_w, 0.18, x=(x0 + x1) / 2.0 + (x1 - x0) * shift,
                                y=(y0 + y1) / 2.0 + (y1 - y0) * shift, color=GOLD,
                                rotation_y=math.atan2(y1 - y0, x1 - x0), metalness=0.6, roughness=0.3))
        return {
            "shape": "group",
            "children": [
                {"shape": "extruded_polygon", "points": [(p[0] * 1.05, p[1] * 1.05) for p in tri], "height": 0.22, "position": [0.0, 0.0, 0.0], "material": {"color": CHIP_EDGE, "metalness": 0.04, "roughness": 0.7}},
                {"shape": "extruded_polygon", "points": tri, "height": 1.3, "position": [0.0, 0.013, 0.0], "material": {"color": body_fill, "metalness": 0.12, "roughness": 0.5}},
                *leads,
                # accent edge stripe along the input face
                {"shape": "box", "width": 0.08, "height": 0.4, "depth": W * 0.5, "position": [-L * 0.29, 1.0, 0.0], "material": {"color": rf_accent, "metalness": 0.2, "roughness": 0.5}},
                {"shape": "text_decal", "text": "RF", "width": L * 0.28, "height": W * 0.3, "position": [-L * 0.04, 1.34, 0.0], "rotation": [-math.pi / 2.0, 0.0, 0.0], "fontSize": max(int(W * 7.0), 90), "color": "#ffffff", "fontWeight": "800"},
            ],
        }


class Microcontroller(Component):
    """Digital controller or MCU block for experiment control diagrams.

    This component is a package-backed logic block with power, ground, clock,
    USB, and GPIO ports. Change ``package_style`` to switch between QFP, QFN,
    BGA, and bare-die package visuals.

    Parameters
    ----------
    center : tuple[float, float]
        Component center in local scene coordinates.
    angle : float
        Rotation angle in degrees.
    length, width : float
        Package body dimensions before ``visual_scale`` is applied.
    pad_size : float
        Lead/pad size and default port width.
    pin_count : int
        Approximate package pin count used to place edge pins or BGA balls.
    package_style : str
        One of ``qfp``, ``qfn``, ``bga``, or ``die``.
    visual_style : str
        One of ``symbolic``, ``publication``, or ``physical``.
    visual_scale : float
        Uniform scale factor applied to component geometry.
    color : str
        Package body color.
    opacity : float
        Package opacity used by 2D rendering.
    label : str
        Optional label stored on the component.
    """

    component_type = "Microcontroller"

    def __init__(
        self,
        center=(0, 0),
        angle: float = 0.0,
        length: float = 42.0,
        width: float = 30.0,
        pad_size: float = 2.0,
        pin_count: int = 8,
        package_style: str = "qfp",
        visual_style: str = "publication",
        visual_scale: float = 1.0,
        color: str = "#3f4856",
        opacity: float = 0.96,
        label: str = "",
    ):
        self.visual_style = _style_key(visual_style)
        self.visual_scale = max(float(visual_scale), 0.05)
        self.length = _scaled(length, self.visual_scale)
        self.width = _scaled(width, self.visual_scale)
        self.pad_size = _scaled(pad_size, self.visual_scale)
        self.pin_count = max(int(pin_count), 4)
        self.package_style = _package_style_key(package_style)
        _init_component(self, center, angle, color=color, opacity=opacity, label=label)

    # The pic od mcu, in its cm: a square package whose 0.96 cm from pin tip to pin tip is ``length``.
    PLAN = {"pwr": (-0.48, 0.2, 180.0), "gnd": (-0.48, -0.2, 180.0), "clk": (0.0, 0.48, 90.0), "usb": (0.0, -0.48, -90.0),
            "gpio1": (0.48, 0.2, 0.0), "gpio2": (0.48, 0.0, 0.0), "gpio3": (0.48, -0.2, 0.0)}

    def ports(self) -> dict[str, Port]:
        return _ports_on_plan(self.PLAN, self.length / 0.96, self.pad_size)

    def _pin_children(self, fill: str = GOLD, stroke: str = GOLD_DARK) -> list[dict[str, Any]]:
        """Return MCU package pins for contributors customizing pin colors."""

        return _package_pins_2d(self.length, self.width, self.pin_count, self.pad_size, self.opacity, self.package_style, fill=fill, stroke=stroke)

    def _package_geometry_2d(self) -> list[dict[str, Any]]:
        """Return the MCU package body, pins, and top-side details in 2D."""

        return _ic_package_geometry_2d(self.length, self.width, self.pin_count, self.pad_size, self.opacity, self.package_style, self.color, "mcu")

    def _package_geometry_3d(self) -> list[dict[str, Any]]:
        """Return the MCU package body, pins, and top-side details in 3D."""

        return _ic_package_geometry_3d(self.length, self.width, self.pin_count, self.pad_size, self.package_style, self.color, "mcu")

    def geometry_2d(self) -> dict[str, Any]:
        if self.visual_style == "symbolic":
            return {
                "type": "group",
                "children": [
                    _rect(0.0, 0.0, self.length, self.width, fill="none", opacity=1.0, stroke=INK, stroke_width=1.0),
                    _line(-self.length / 2.0, self.width * 0.25, self.length / 2.0, self.width * 0.25, stroke=INK, stroke_width=0.8, opacity=1.0),
                    _line(-self.length / 2.0, -self.width * 0.25, self.length / 2.0, -self.width * 0.25, stroke=INK, stroke_width=0.8, opacity=1.0),
                    _line(0.0, -self.width / 2.0, 0.0, self.width / 2.0, stroke=INK, stroke_width=0.8, opacity=1.0),
                ],
            }
        return {
            "type": "group",
            "children": [
                *self._package_geometry_2d(),
                _polyline([(-self.length * 0.12, 0.0), (-self.length * 0.04, self.width * 0.12), (self.length * 0.04, -self.width * 0.12), (self.length * 0.12, 0.0)], stroke="#d9e0ea", stroke_width=0.2, opacity=0.9),
            ],
        }

    def geometry_3d(self) -> dict[str, Any]:
        children = self._package_geometry_3d()
        children.append(_box3d(self.length * 0.28, self.pad_size * 0.16, 0.06, x=0.0, y=0.0, color="#d9e0ea", z_offset=1.84, metalness=0.18, roughness=0.36))
        return {"shape": "group", "children": children}


class MEMSActuator(Component):
    """Comb-drive MEMS actuator visual for tunable photonic devices.

    The drawing includes opposing anchors, interdigitated fingers, and two
    electrical ports. ``symbolic`` view reduces it to a compact actuator symbol.

    Parameters
    ----------
    center : tuple[float, float]
        Component center in local scene coordinates.
    angle : float
        Rotation angle in degrees.
    length, width : float
        Overall actuator footprint before ``visual_scale`` is applied.
    finger_count : int
        Number of interdigitated finger rows.
    pad_size : float
        Anchor/pad size and default port width.
    visual_style : str
        One of ``symbolic``, ``publication``, or ``physical``.
    visual_scale : float
        Uniform scale factor applied to component geometry.
    color : str
        Silicon or MEMS structure color.
    opacity : float
        Actuator opacity used by 2D rendering.
    label : str
        Optional label stored on the component.
    """

    component_type = "MEMSActuator"
    _art_scale_from_ports = True        # the art spans e1 to e2: sized to the body, it stopped 22 units short of e2
    lies_on_table = True                # the stator and the rotor are two bodies, each anchored to the die apart

    def __init__(
        self,
        center=(0, 0),
        angle: float = 0.0,
        length: float = 46.0,
        width: float = 20.0,
        finger_count: int = 6,
        pad_size: float = 3.0,
        visual_style: str = "publication",
        visual_scale: float = 1.0,
        color: str = MEMS_SILICON,
        opacity: float = 0.94,
        label: str = "",
    ):
        self.visual_style = _style_key(visual_style)
        self.visual_scale = max(float(visual_scale), 0.05)
        self.length = _scaled(length, self.visual_scale)
        self.width = _scaled(width, self.visual_scale)
        self.finger_count = max(int(finger_count), 3)
        self.pad_size = _scaled(pad_size, self.visual_scale)
        _init_component(self, center, angle, color=color, opacity=opacity, label=label)

    def ports(self) -> dict[str, Port]:
        return {
            "e1": Port("e1", Vec3(-self.length / 2.0, 0.0, 0.0), orientation_deg=180.0, width=self.pad_size, kind="electrical"),
            "e2": Port("e2", Vec3(self.length / 2.0, 0.0, 0.0), orientation_deg=0.0, width=self.pad_size, kind="electrical"),
        }

    # Comb-drive element colors: fixed stator (silicon), movable rotor (lighter),
    # bond anchors (metal).
    _COMB_COLORS = {"stator": MEMS_SILICON, "rotor": "#9aa9b6", "anchor": "#8798a8"}

    def _comb_elements(self) -> list[tuple[float, float, float, float, str]]:
        """Rects ``(cx, cy, w, h, role)`` for the comb drive: spines, fingers, anchors."""

        L, W = self.length, self.width
        n = self.finger_count
        pitch = (W * 0.62) / max(n, 1)
        fw = min(max(W * 0.045, 0.4), pitch * 0.45)             # a rotor finger sits pitch / 2 off a stator finger: a gap
        stator_x, rotor_x = -L * 0.14, L * 0.14
        spine_w = fw * 1.9
        flen = rotor_x - stator_x - spine_w * 0.8 - fw          # a finger stops one finger width short of the other spine
        bus_x0, bus_x1 = -L * 0.44 + self.pad_size * 0.85, stator_x - spine_w / 2.0   # from the left pad to the spine
        els: list[tuple[float, float, float, float, str]] = [
            # electrical anchor pads (left = stator drive, right = rotor frame)
            (-L * 0.44, 0.0, self.pad_size * 1.7, W * 0.52, "anchor"),
            (L * 0.45, 0.0, self.pad_size * 1.5, W * 0.9, "anchor"),
            # stator spine + bus bar to the left pad
            (stator_x, 0.0, spine_w, W * 0.84, "stator"),
            ((bus_x0 + bus_x1) / 2.0, 0.0, bus_x1 - bus_x0, fw * 1.6, "stator"),
            # rotor spine (the movable shuttle)
            (rotor_x, 0.0, spine_w, W * 0.84, "rotor"),
        ]
        for i in range(n):
            y = -W * 0.31 + i * pitch
            els.append((stator_x + flen / 2.0 + spine_w * 0.3, y, flen, fw, "stator"))               # stator finger →
            els.append((rotor_x - flen / 2.0 - spine_w * 0.3, y + pitch / 2.0, flen, fw, "rotor"))     # rotor finger ←
        return els

    def _spring_segments(self) -> list[tuple[tuple[float, float], tuple[float, float]]]:
        """Folded suspension springs linking the rotor spine to the right anchor frame: out, back, and out again
        to the anchor's inner face."""

        L, W = self.length, self.width
        rotor_x = L * 0.14
        anchor_x = L * 0.45 - self.pad_size * 0.75
        segments: list[tuple[tuple[float, float], tuple[float, float]]] = []
        for sy in (1.0, -1.0):
            yb = sy * W * 0.42
            yi = yb - sy * W * 0.1
            yo = yi - sy * W * 0.1
            path = [(rotor_x, sy * W * 0.36), (rotor_x, yb), (L * 0.37, yb), (L * 0.37, yi), (rotor_x + L * 0.08, yi),
                    (rotor_x + L * 0.08, yo), (anchor_x, yo)]
            segments += list(zip(path, path[1:]))
        return segments

    def geometry_2d(self) -> dict[str, Any]:
        if self.visual_style == "symbolic":
            return {
                "type": "group",
                "children": [
                    _line(-self.length / 2.0, 0.0, -self.length * 0.08, 0.0, stroke=INK, stroke_width=1.0, opacity=1.0),
                    _line(self.length * 0.08, 0.0, self.length / 2.0, 0.0, stroke=INK, stroke_width=1.0, opacity=1.0),
                    _line(-self.length * 0.08, -self.width * 0.25, -self.length * 0.08, self.width * 0.25, stroke=INK, stroke_width=1.0, opacity=1.0),
                    _line(self.length * 0.08, -self.width * 0.25, self.length * 0.08, self.width * 0.25, stroke=INK, stroke_width=1.0, opacity=1.0),
                    _line(self.length * 0.12, 0.0, self.length * 0.23, 0.0, stroke=INK, stroke_width=0.8, opacity=1.0),
                    _polygon([(self.length * 0.23, 0.0), (self.length * 0.18, self.width * 0.08), (self.length * 0.18, -self.width * 0.08)], fill=INK, opacity=1.0),
                ],
            }
        spring_w = max(self.width * 0.035, 0.25)
        children = [
            _rect(cx, cy, w, h, fill=self._COMB_COLORS[role], opacity=self.opacity, stroke="#3c4b59", stroke_width=0.08)
            for cx, cy, w, h, role in self._comb_elements()
        ]
        for (x0, y0), (x1, y1) in self._spring_segments():
            children.append(_line(x0, y0, x1, y1, stroke="#5b6f7e", stroke_width=spring_w, opacity=self.opacity))
        return {"type": "group", "children": children}

    def geometry_3d(self) -> dict[str, Any]:
        spring_w = max(self.width * 0.035, 0.25)
        thick = {"stator": 0.4, "rotor": 0.4, "anchor": 0.55}
        children = [
            # the released rotor 1 % above the stator: their faces shared planes
            _box3d(w, h, thick[role], x=cx, y=cy, color=self._COMB_COLORS[role], z_offset=thick[role] * 0.01 if role == "rotor" else 0.0,
                   metalness=0.18, roughness=0.46)
            for cx, cy, w, h, role in self._comb_elements()
        ]
        segments = self._spring_segments()
        key = lambda p: (round(p[0], 6), round(p[1], 6))                                   # noqa: E731
        joints = Counter(key(p) for segment in segments for p in segment)
        for (x0, y0), (x1, y1) in segments:
            seg_dx, seg_dy = x1 - x0, y1 - y0
            seg_len = math.hypot(seg_dx, seg_dy)
            if seg_len <= 1e-9:
                continue
            # a bend overlaps its neighbour; an end stops where it meets the anchor or the rotor, sharing no face
            back = spring_w * 0.25 if joints[key((x0, y0))] > 1 else 0.0
            ahead = spring_w * 0.25 if joints[key((x1, y1))] > 1 else 0.0
            shift = (ahead - back) / 2.0 / seg_len
            children.append(_box3d(seg_len + back + ahead, spring_w, 0.3, x=(x0 + x1) / 2.0 + seg_dx * shift,
                                   y=(y0 + y1) / 2.0 + seg_dy * shift, color="#5b6f7e",
                                   rotation_y=math.atan2(seg_dy, seg_dx), metalness=0.18, roughness=0.46))
        return {"shape": "group", "children": children}


# The PCB symbol's colours (od-core.tex: odpcbA/B/E, odgoldA/B/E), one flat colour where the symbol has a gradient.
PCB_BOARD, PCB_BOARD_EDGE = "#10b981", "#047857"
PCB_PAD, PCB_PAD_EDGE, PCB_TRACE, PCB_VIA = "#e7cb6c", "#a8841f", "#d4af37", "#fbe7a1"


class PCB(Component):
    """Printed circuit board context with edge pads, vias, and copper traces.

    Use this as a board-level context layer around electronic chips, pads, and
    routes. Ports are generated on the left and right board edges.

    Parameters
    ----------
    center : tuple[float, float]
        Board center in local scene coordinates.
    angle : float
        Rotation angle in degrees.
    length, width : float
        Board outline dimensions before ``visual_scale`` is applied.
    pad_count : int
        Number of edge pads per side. Total ports are ``2 * pad_count``.
    pad_size : float
        Edge pad size and default port width.
    visual_style : str
        One of ``symbolic``, ``publication``, or ``physical``.
    visual_scale : float
        Uniform scale factor applied to component geometry.
    color : str
        Board substrate color.
    opacity : float
        Board opacity used by 2D rendering.
    label : str
        Optional label stored on the component.
    style : str
        ``traces`` (the default) draws decorative copper traces and vias; ``plain`` draws the outline in ``color``
        and the edge pads only, in every view.
    """

    component_type = "PCB"
    STYLES = ("traces", "plain")

    def __init__(
        self,
        center=(0, 0),
        angle: float = 0.0,
        length: float = 90.0,
        width: float = 52.0,
        pad_count: int = 6,
        pad_size: float = 4.0,
        visual_style: str = "publication",
        visual_scale: float = 1.0,
        color: str = BOARD_GREEN,
        opacity: float = 0.92,
        label: str = "",
        style: str = "traces",
    ):
        if style not in self.STYLES:
            raise ValueError(f"PCB style is one of {', '.join(self.STYLES)}, got {style!r}")
        self.style = style
        self.visual_style = _style_key(visual_style)
        self.visual_scale = max(float(visual_scale), 0.05)
        self.length = _scaled(length, self.visual_scale)
        self.width = _scaled(width, self.visual_scale)
        self.pad_count = max(int(pad_count), 1)
        self.pad_size = _scaled(pad_size, self.visual_scale)
        _init_component(self, center, angle, color=color, opacity=opacity, label=label)

    def symbol_1d(self) -> tuple[str, dict[str, Any]] | None:
        return ("pcb", {"kind": "plain"}) if self.style == "plain" else None

    def ports(self) -> dict[str, Port]:
        ports: dict[str, Port] = {}
        for index, y in enumerate(_edge_positions(self.pad_count, self.width, self.pad_size * 1.2), start=1):
            ports[f"e{index}"] = Port(f"e{index}", Vec3(-self.length / 2.0, y, 0.0), orientation_deg=180.0, width=self.pad_size, kind="electrical", layer="PCB")
            right_index = index + self.pad_count
            ports[f"e{right_index}"] = Port(f"e{right_index}", Vec3(self.length / 2.0, y, 0.0), orientation_deg=0.0, width=self.pad_size, kind="electrical", layer="PCB")
        return ports

    def _pad_children(self, line: float = 0.16) -> list[dict[str, Any]]:
        """Return PCB edge pads shared by the 2D and 3D views: gold, as the symbol's pads (3D reads only their size)."""

        children: list[dict[str, Any]] = []
        for y in _edge_positions(self.pad_count, self.width, self.pad_size * 1.2):
            for x in (-self.length / 2.0 + self.pad_size * 0.55, self.length / 2.0 - self.pad_size * 0.55):
                children.append({**_rect(x, y, self.pad_size, self.pad_size, fill=PCB_PAD, opacity=self.opacity,
                                         stroke=PCB_PAD_EDGE, stroke_width=0.3 * line), "role": "pad"})
        return children

    def geometry_2d(self) -> dict[str, Any]:
        """The board at its own size in the look of its symbol: an emerald board, gold edge pads, and gold traces that
        each run from a left pad through a via down one row to a right pad. Lines take the symbol's weight in pt."""

        if self.visual_style == "symbolic":
            return {
                "type": "group",
                "children": [
                    _rect(0.0, 0.0, self.length, self.width, fill="none", opacity=1.0, stroke=INK, stroke_width=1.0),
                    *[_line(-self.length / 2.0, y, self.length / 2.0, y, stroke=INK, stroke_width=0.75, opacity=1.0) for y in _edge_positions(min(self.pad_count, 4), self.width, self.pad_size * 1.4)],
                ],
            }
        from optodraw.symbols.art import LINE_SCALE

        line = min(self.length / 45.5, self.width / 29.6, LINE_SCALE)     # the symbol is 1.6 cm x 1.04 cm: pt in units
        fill = PCB_BOARD if self.color == BOARD_GREEN else self.color         # the 3D keeps the darker board green
        children = [_rect(0.0, 0.0, self.length, self.width, fill=fill, opacity=self.opacity, stroke=PCB_BOARD_EDGE,
                          stroke_width=0.3 * line)]
        if self.style != "plain":
            rows = _edge_positions(self.pad_count, self.width, self.pad_size * 1.2)
            inner = self.length / 2.0 - self.pad_size * 1.05
            for k in range(self.pad_count // 2):
                top, low = rows[2 * k], rows[2 * k + 1]
                via = self.length / 2.0 * (-0.25, 0.31, -0.375)[k % 3]            # the symbol's via stations
                drop = (top - low) * 1.4
                children.append({**_polyline([(-inner, top), (via, top), (via + drop, low), (inner, low)], stroke=PCB_TRACE,
                                             stroke_width=0.45 * line), "role": "trace"})
                children.append({**_circle(via, top, max(self.pad_size * 0.2, 0.9 * line), fill=PCB_VIA), "role": "via"})
        return {"type": "group", "children": [*children, *self._pad_children(line)]}

    def geometry_3d(self) -> dict[str, Any]:
        children = [_box3d(self.length, self.width, BOARD_THICKNESS, x=0.0, y=0.0, color=self.color, metalness=0.05, roughness=0.72)]
        plain = self.style == "plain"
        # shortcut: the traced board keeps its copper at 0.64 to 0.78, inside the 1.2 board, as before; a plain
        # board puts its pads on the top so they show. Lift the traced board's copper too if its 3D look may change.
        for pad in self._pad_children():
            children.append(_box3d(pad["w"], pad["h"], 0.12, x=pad["cx"], y=pad["cy"], color=COPPER,
                                   z_offset=BOARD_THICKNESS if plain else 0.64))
        if plain:
            return {"shape": "group", "children": children}
        for y in _edge_positions(min(self.pad_count, 4), self.width, self.pad_size * 1.6):
            children.append(_box3d(self.length * 0.66, max(self.pad_size * 0.16, 0.35), 0.08, x=0.0, y=y * 0.72, color=COPPER, z_offset=0.7))
        return {"shape": "group", "children": children}


class DAC(Component):
    """Digital-to-analog converter block for drive and control diagrams.

    The 1D and publication 2D views use the standard DAC trapezoid symbol. The
    physical 2D/3D views use the same package helpers as ``EIC`` with DAC trace
    accents and a DAC symbol on the 3D chip top.

    Parameters
    ----------
    center : tuple[float, float]
        Component center in local scene coordinates.
    angle : float
        Rotation angle in degrees.
    length, width : float
        Converter footprint before ``visual_scale`` is applied.
    pad_size : float
        Lead/pad size and default port width.
    bit_count : int
        Number of digital input bits. Physical views use this to add bit-line
        hints and estimate package pin count.
    differential : bool
        When ``True``, add complementary output port ``out_n``.
    package_style : str
        One of ``qfp``, ``qfn``, ``bga``, or ``die`` for physical package views.
    visual_style : str
        One of ``symbolic``, ``publication``, or ``physical``.
    visual_scale : float
        Uniform scale factor applied to component geometry.
    color : str
        Package body color used in physical views.
    opacity : float
        Component opacity used by 2D rendering.
    label : str
        Optional 3D top label. Defaults to ``DAC`` when empty.
    sample_rate_hz, full_scale_v : float
        Datasheet numbers for the signal chain: the clock rate, and the full scale of a unipolar range 0 to
        ``full_scale_v``. None is the chain's model default.
    """

    component_type = "DAC"
    _art_scale_from_ports = True        # the art spans the ports; sized to the body it missed them by 15 units

    def __init__(
        self,
        center=(0, 0),
        angle: float = 0.0,
        length: float = 34.0,
        width: float = 22.0,
        pad_size: float = 2.0,
        bit_count: int = 8,
        differential: bool = True,
        package_style: str = "qfn",
        visual_style: str = "publication",
        visual_scale: float = 1.0,
        color: str = CHIP_BODY,
        opacity: float = 0.96,
        label: str = "",
        sample_rate_hz: float | None = None,
        full_scale_v: float | None = None,
    ):
        self.sample_rate_hz, self.full_scale_v = sample_rate_hz, full_scale_v   # the signal chain's; None: its default
        self.visual_style = _style_key(visual_style)
        self.visual_scale = max(float(visual_scale), 0.05)
        self.length = _scaled(length, self.visual_scale)
        self.width = _scaled(width, self.visual_scale)
        self.pad_size = _scaled(pad_size, self.visual_scale)
        self.bit_count = max(int(bit_count), 1)
        self.differential = bool(differential)
        self.package_style = _package_style_key(package_style)
        _init_component(self, center, angle, color=color, opacity=opacity, label=label)

    def ports(self) -> dict[str, Port]:
        # On the lead ends of the converter symbol, in units of length: the art spans din to out.
        L, pair = self.length, self.length * 8.0 / 65.0
        ports = {
            "din": Port("din", Vec3(-L / 2.0, pair, 0.0), orientation_deg=180.0, width=self.pad_size, kind="electrical"),
            "clk": Port("clk", Vec3(-L / 2.0, -pair, 0.0), orientation_deg=180.0, width=self.pad_size, kind="electrical"),
            "ref": Port("ref", Vec3(-L * 3.0 / 26.0, L * 0.4, 0.0), orientation_deg=90.0, width=self.pad_size, kind="electrical"),
            "out": Port("out", Vec3(L / 2.0, pair if self.differential else 0.0, 0.0), orientation_deg=0.0, width=self.pad_size, kind="electrical"),
            "gnd": Port("gnd", Vec3(-L * 3.0 / 26.0, -L * 0.4, 0.0), orientation_deg=-90.0, width=self.pad_size, kind="electrical"),
        }
        if self.differential:
            ports["out_n"] = Port("out_n", Vec3(L / 2.0, -pair, 0.0), orientation_deg=0.0, width=self.pad_size, kind="electrical")
        return ports

    def _symbol_outline(self) -> tuple[list[tuple[float, float]], tuple[float, float], tuple[float, float]]:
        """Return the local DAC polygon and its connection endpoints."""

        return _converter_outline("dac", self.length, self.width)

    def _symbol_label_position(self) -> tuple[float, float]:
        """Return the local text position inside the DAC symbol."""

        points, _, _ = self._symbol_outline()
        return _polygon_centroid(points)

    def _symbol_geometry_2d(self, *, line_width: float = 1.0, opacity: float = 1.0) -> list[dict[str, Any]]:
        """Return the complete 2D DAC symbol children."""

        return _converter_symbol_2d("dac", self.length, self.width, "DAC", line_width=line_width, opacity=opacity)

    def _package_geometry_2d(self) -> list[dict[str, Any]]:
        """Return the DAC package body and package-specific 2D details."""

        return _ic_package_geometry_2d(self.length, self.width, max(self.bit_count + 4, 8), self.pad_size, self.opacity, self.package_style, self.color, "dac")

    def _package_geometry_3d(self) -> list[dict[str, Any]]:
        """Return the DAC package body and package-specific 3D details."""

        return _ic_package_geometry_3d(self.length, self.width, max(self.bit_count + 4, 8), self.pad_size, self.package_style, self.color, "dac")

    def _top_symbol_3d(self) -> list[dict[str, Any]]:
        """Return the raised DAC symbol placed on top of the 3D package."""

        return _converter_top_3d("dac", self.length, self.width, self.label or "DAC", z_offset=IC_BODY_THICKNESS + 0.16)

    def _symbolic_2d(self) -> dict[str, Any]:
        children = self._symbol_geometry_2d()
        for child in children:
            if child.get("type") == "polygon":
                child["fill"] = "#ffffff"
            elif child.get("type") == "text":
                child["fill"] = "#000000"
            if "stroke" in child:
                child["stroke"] = "#000000"
        return {"type": "group", "children": children}

    def geometry_2d(self) -> dict[str, Any]:
        # The DAC uses the literature PENTAGON converter-symbol body (not a rectangle).
        if self.visual_style == "symbolic":
            return self._symbolic_2d()
        return {"type": "group", "children": _converter_chip_2d("dac", self.length, self.width, self.opacity, self.color, "DAC")}

    def geometry_3d(self) -> dict[str, Any]:
        return {"shape": "group", "children": _converter_chip_3d("dac", self.length, self.width, self.color, "DAC")}


class ADCBlock(Component):
    """Analog-to-digital converter block for electronic readout diagrams.

    The name avoids shadowing the existing on-chip photonic ``ADC`` export. The
    1D and publication 2D views use the standard ADC trapezoid symbol; physical
    views use package details, ADC trace accents, and a 3D ADC top mark.

    Parameters
    ----------
    center : tuple[float, float]
        Component center in local scene coordinates.
    angle : float
        Rotation angle in degrees.
    length, width : float
        Converter footprint before ``visual_scale`` is applied.
    pad_size : float
        Lead/pad size and default port width.
    bit_count : int
        Number of digital output bits. Physical views use this to add bit-line
        hints and estimate package pin count.
    package_style : str
        One of ``qfp``, ``qfn``, ``bga``, or ``die`` for physical package views.
    visual_style : str
        One of ``symbolic``, ``publication``, or ``physical``.
    visual_scale : float
        Uniform scale factor applied to component geometry.
    color : str
        Package body color used in physical views.
    opacity : float
        Component opacity used by 2D rendering.
    label : str
        Optional 3D top label. Defaults to ``ADC`` when empty.
    sample_rate_hz, full_scale_v : float
        Datasheet numbers for the signal chain: the clock rate, and the full scale of a unipolar range 0 to
        ``full_scale_v``. None is the chain's model default.
    """

    component_type = "ADCBlock"
    _art_scale_from_ports = True        # the art spans the ports; sized to the body it missed them by 15 units

    def __init__(
        self,
        center=(0, 0),
        angle: float = 0.0,
        length: float = 34.0,
        width: float = 22.0,
        pad_size: float = 2.0,
        bit_count: int = 8,
        package_style: str = "qfn",
        visual_style: str = "publication",
        visual_scale: float = 1.0,
        color: str = CHIP_BODY,
        opacity: float = 0.96,
        label: str = "",
        sample_rate_hz: float | None = None,
        full_scale_v: float | None = None,
    ):
        self.sample_rate_hz, self.full_scale_v = sample_rate_hz, full_scale_v   # the signal chain's; None: its default
        self.visual_style = _style_key(visual_style)
        self.visual_scale = max(float(visual_scale), 0.05)
        self.length = _scaled(length, self.visual_scale)
        self.width = _scaled(width, self.visual_scale)
        self.pad_size = _scaled(pad_size, self.visual_scale)
        self.bit_count = max(int(bit_count), 1)
        self.package_style = _package_style_key(package_style)
        _init_component(self, center, angle, color=color, opacity=opacity, label=label)

    def ports(self) -> dict[str, Port]:
        return {
            "in": Port("in", Vec3(-self.length / 2.0, 0.0, 0.0), orientation_deg=180.0, width=self.pad_size, kind="electrical"),
            # On the lead ends of the converter symbol, in units of length: the art spans in to dout.
            "clk": Port("clk", Vec3(-self.length * 3.0 / 26.0, self.length * 0.4, 0.0), orientation_deg=90.0, width=self.pad_size, kind="electrical"),
            "ref": Port("ref", Vec3(-self.length * 3.0 / 13.0, -self.length * 0.4, 0.0), orientation_deg=-90.0, width=self.pad_size, kind="electrical"),
            "dout": Port("dout", Vec3(self.length / 2.0, 0.0, 0.0), orientation_deg=0.0, width=self.pad_size, kind="electrical"),
            "gnd": Port("gnd", Vec3(0.0, -self.length * 0.4, 0.0), orientation_deg=-90.0, width=self.pad_size, kind="electrical"),
        }

    def _symbol_outline(self) -> tuple[list[tuple[float, float]], tuple[float, float], tuple[float, float]]:
        """Return the local ADC polygon and its connection endpoints."""

        return _converter_outline("adc", self.length, self.width)

    def _symbol_label_position(self) -> tuple[float, float]:
        """Return the local text position inside the ADC symbol."""

        points, _, _ = self._symbol_outline()
        return _polygon_centroid(points)

    def _symbol_geometry_2d(self, *, line_width: float = 1.0, opacity: float = 1.0) -> list[dict[str, Any]]:
        """Return the complete 2D ADC symbol children."""

        return _converter_symbol_2d("adc", self.length, self.width, "ADC", line_width=line_width, opacity=opacity)

    def _package_geometry_2d(self) -> list[dict[str, Any]]:
        """Return the ADC package body and package-specific 2D details."""

        return _ic_package_geometry_2d(self.length, self.width, max(self.bit_count + 4, 8), self.pad_size, self.opacity, self.package_style, self.color, "adc")

    def _package_geometry_3d(self) -> list[dict[str, Any]]:
        """Return the ADC package body and package-specific 3D details."""

        return _ic_package_geometry_3d(self.length, self.width, max(self.bit_count + 4, 8), self.pad_size, self.package_style, self.color, "adc")

    def _top_symbol_3d(self) -> list[dict[str, Any]]:
        """Return the raised ADC symbol placed on top of the 3D package."""

        return _converter_top_3d("adc", self.length, self.width, self.label or "ADC", z_offset=IC_BODY_THICKNESS + 0.16)

    def _symbolic_2d(self) -> dict[str, Any]:
        children = self._symbol_geometry_2d()
        for child in children:
            if child.get("type") == "polygon":
                child["fill"] = "#ffffff"
            elif child.get("type") == "text":
                child["fill"] = "#000000"
            if "stroke" in child:
                child["stroke"] = "#000000"
        return {"type": "group", "children": children}

    def geometry_2d(self) -> dict[str, Any]:
        # The ADC uses the literature PENTAGON converter-symbol body (not a rectangle).
        if self.visual_style == "symbolic":
            return self._symbolic_2d()
        return {"type": "group", "children": _converter_chip_2d("adc", self.length, self.width, self.opacity, self.color, "ADC")}

    def geometry_3d(self) -> dict[str, Any]:
        return {"shape": "group", "children": _converter_chip_3d("adc", self.length, self.width, self.color, "ADC")}


class ElectricalIOBank(Component):
    """Repeated electrical pad bank for DC, RF, clock, and digital interfaces.

    ``ElectricalIOBank`` is a higher-level companion to ``ElectricalPad`` and
    ``GSGProbePad``. It gives dense chip/package figures a compact bank of
    routeable electrical ports without forcing users to place many individual
    pads by hand.

    Parameters
    ----------
    center : tuple[float, float]
        Bank center in local scene coordinates.
    angle : float
        Rotation angle in degrees.
    count : int
        Number of pads and electrical ports. Ports are named ``e1``, ``e2``, ...
        in geometric order.
    pitch : float
        Center-to-center pad spacing before ``visual_scale`` is applied.
    pad_width, pad_height : float
        Pad dimensions before ``visual_scale`` is applied.
    side : str
        Edge where ports face: ``left``, ``right``, ``top``, or ``bottom``.
    bank_kind : str
        Primary signal family for metadata and default pad coloring. Common
        values are ``dc``, ``rf``, ``digital``, ``clock``, and ``mixed``.
    signal_kinds : Iterable[str] | None
        Optional per-port signal labels stored in metadata. Missing entries are
        filled with ``bank_kind``.
    layer : str | None
        Optional electrical layer name stored on each port.
    visual_style : str
        One of ``symbolic``, ``publication``, or ``physical``.
    visual_scale : float
        Uniform scale factor applied to component geometry and port spacing.
    color : str
        Substrate/body color used by publication and 3D views.
    opacity : float
        Component opacity used by 2D rendering.
    label : str
        Optional label stored on the component.
    """

    component_type = "ElectricalIOBank"

    def __init__(
        self,
        center=(0, 0),
        angle: float = 0.0,
        count: int = 8,
        pitch: float = 8.0,
        pad_width: float = 5.0,
        pad_height: float = 4.0,
        side: str = "right",
        bank_kind: str = "dc",
        signal_kinds: Iterable[str] | None = None,
        layer: str | None = "M1",
        visual_style: str = "publication",
        visual_scale: float = 1.0,
        color: str = CERAMIC,
        opacity: float = 0.94,
        label: str = "",
    ):
        self.visual_style = _style_key(visual_style)
        self.visual_scale = max(float(visual_scale), 0.05)
        self.count = max(int(count), 1)
        self.pitch = _scaled(pitch, self.visual_scale)
        self.pad_width = _scaled(pad_width, self.visual_scale)
        self.pad_height = _scaled(pad_height, self.visual_scale)
        self.side = side.lower()
        if self.side not in {"left", "right", "top", "bottom"}:
            raise ValueError("side must be one of: left, right, top, bottom")
        self.bank_kind = (bank_kind or "dc").strip().lower()
        raw_signal_kinds = tuple(str(kind).strip().lower() for kind in signal_kinds) if signal_kinds is not None else ()
        if len(raw_signal_kinds) >= self.count:
            self.signal_kinds = raw_signal_kinds[: self.count]
        else:
            self.signal_kinds = raw_signal_kinds + (self.bank_kind,) * (self.count - len(raw_signal_kinds))
        self.layer = layer
        span = max((self.count - 1) * self.pitch, 0.0)
        if self.side in {"left", "right"}:
            self.length = self.pad_width * 2.6
            self.width = span + self.pad_height * 3.0
        else:
            self.length = span + self.pad_width * 3.0
            self.width = self.pad_height * 2.6
        _init_component(self, center, angle, color=color, opacity=opacity, label=label)

    def symbol_1d(self) -> tuple[str, dict[str, Any]]:
        return "iopads", {"count": self.count}

    def _pad_color(self, signal_kind: str) -> str:
        if signal_kind == "rf":
            return SIGNAL_COLORS["rf"]
        if signal_kind == "clock":
            return SIGNAL_COLORS["clock"]
        if signal_kind == "digital":
            return DIGITAL_BLUE
        return GOLD

    def _pad_centers(self) -> list[tuple[float, float]]:
        positions = _grid_positions(self.count, self.pitch)
        if self.side == "left":
            return [(-self.length / 2.0, y) for y in positions]
        if self.side == "right":
            return [(self.length / 2.0, y) for y in positions]
        if self.side == "top":
            return [(x, self.width / 2.0) for x in positions]
        return [(x, -self.width / 2.0) for x in positions]

    def _port_orientation(self) -> float:
        return {"left": 180.0, "right": 0.0, "top": 90.0, "bottom": -90.0}[self.side]

    def ports(self) -> dict[str, Port]:
        port_width = self.pad_height if self.side in {"left", "right"} else self.pad_width
        orientation = self._port_orientation()
        return {
            f"e{index}": Port(f"e{index}", Vec3(x, y, 0.0), orientation_deg=orientation, width=port_width, kind="electrical", layer=self.layer)
            for index, (x, y) in enumerate(self._pad_centers(), start=1)
        }

    def geometry_2d(self) -> dict[str, Any]:
        if self.visual_style == "symbolic":
            centers = self._pad_centers()
            if self.side in {"left", "right"}:
                bus_x = centers[0][0] - self.pad_width * 0.8 if self.side == "right" else centers[0][0] + self.pad_width * 0.8
                return {"type": "group", "children": [_line(bus_x, -self.width * 0.38, bus_x, self.width * 0.38, stroke=INK, stroke_width=0.9, opacity=1.0), *[_line(bus_x, y, x, y, stroke=INK, stroke_width=0.8, opacity=1.0) for x, y in centers]]}
            bus_y = centers[0][1] - self.pad_height * 0.8 if self.side == "top" else centers[0][1] + self.pad_height * 0.8
            return {"type": "group", "children": [_line(-self.length * 0.38, bus_y, self.length * 0.38, bus_y, stroke=INK, stroke_width=0.9, opacity=1.0), *[_line(x, bus_y, x, y, stroke=INK, stroke_width=0.8, opacity=1.0) for x, y in centers]]}

        pad_w = self.pad_width if self.side in {"left", "right"} else self.pad_height
        pad_h = self.pad_height if self.side in {"left", "right"} else self.pad_width
        children = [_rect(0.0, 0.0, self.length, self.width, fill=self.color, opacity=0.26, stroke="#8b96a3", stroke_width=0.1)]
        for index, ((x, y), signal_kind) in enumerate(zip(self._pad_centers(), self.signal_kinds), start=1):
            pad_color = self._pad_color(signal_kind)
            children.append(_rect(x, y, pad_w, pad_h, fill="#5d5126", opacity=self.opacity, stroke=GOLD_DARK, stroke_width=0.08))
            children.append(_rect(x, y, pad_w * 0.86, pad_h * 0.86, fill=pad_color, opacity=self.opacity))
            # metallic top sheen
            children.append(_rect(x, y - pad_h * 0.22, pad_w * 0.82, pad_h * 0.26, fill="#ffffff", opacity=0.22))
            if self.count <= 8:
                children.append(_text(str(index), x, y, size=max(min(pad_w, pad_h) * 0.42, 1.8), fill="#ffffff", opacity=0.9, font_weight="600"))
        return {"type": "group", "children": children}

    def geometry_3d(self) -> dict[str, Any]:
        pad_w = self.pad_width if self.side in {"left", "right"} else self.pad_height
        pad_h = self.pad_height if self.side in {"left", "right"} else self.pad_width
        children = [_box3d(self.length, self.width, 0.5, x=0.0, y=0.0, color=self.color, metalness=0.04, roughness=0.7)]
        for (x, y), signal_kind in zip(self._pad_centers(), self.signal_kinds):
            pad_color = self._pad_color(signal_kind)
            # stepped metallic pad: base + raised bright bond surface
            children.append(_box3d(pad_w, pad_h, 0.16, x=x, y=y, color="#5d5126", z_offset=0.28, metalness=0.5, roughness=0.32))
            children.append(_box3d(pad_w * 0.82, pad_h * 0.82, 0.12, x=x, y=y, color=pad_color, z_offset=0.42, metalness=0.72, roughness=0.2))
        return {"shape": "group", "children": children}

    def physics_metadata(self) -> dict[str, Any]:
        return {"component": "electrical_io_bank", "bank_kind": self.bank_kind, "signal_kinds": list(self.signal_kinds), "layer": self.layer, "count": self.count}
