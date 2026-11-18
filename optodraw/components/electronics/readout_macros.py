"""Readout macros electronics components."""

from __future__ import annotations
import math
from typing import Any
from optodraw.core.component import Component
from optodraw.core.ports import Port
from optodraw.core.transform import Vec3

from optodraw.components.electronics._shared import (
    _ROLE_ACCENT,
    ANALOG_BLUE,
    CHIP_BODY,
    COPPER,
    DIGITAL_BLUE,
    GOLD,
    GOLD_DARK,
    IC_BODY_THICKNESS,
    INK,
    SIGNAL_COLORS,
    TIA_PURPLE,
    _box3d,
    _chip_label_3d,
    _circle,
    _converter_symbol_2d,
    _converter_trace_children,
    _cylinder3d,
    _ic_package_geometry_2d,
    _ic_package_geometry_3d,
    _init_component,
    _line,
    _normalize_tia_mode,
    _offset_geometry_2d,
    _ports_on_plan,
    _opamp_body_3d,
    _opamp_label,
    _opamp_label_position,
    _opamp_outline,
    _opamp_symbol_2d,
    _package_role_key,
    _package_style_key,
    _polygon,
    _polyline,
    _rect,
    _scaled,
    _style_key,
    _text,
)
from optodraw.components.electronics.blocks import ADCBlock, RFDriver

# ---------------------------------------------------------------- macros in 3D: a module and its dies
# A macro was a flat navy plate with pale shapes a few tenths high; it reads now as a module: a carrier,
# its dies standing on it with their labels, traces and guides between them, metal at its ports.
_MODULE_TOP = 1.0                      # the carrier's top face: the dies stand on it
_DIE_H = 1.1
_SILICON_3D = "#2b6cb0"                # a waveguide on a photonic die: the on-chip silicon blue
_PHOTONIC_DIE = "#dbe7ef"


def _module_3d(length: float, width: float, color: str) -> list[dict[str, Any]]:
    return [_box3d(length * 1.01, width * 1.01, 0.2, x=0.0, y=0.0, color="#111827", metalness=0.02, roughness=0.74),
            _box3d(length, width, _MODULE_TOP - 0.2, x=0.0, y=0.0, color=color, z_offset=0.2, metalness=0.05, roughness=0.7)]


def _die_3d(x: float, y: float, length: float, width: float, label: str, accent: str, *, body: str = CHIP_BODY,
            ink: str | None = None) -> list[dict[str, Any]]:
    """A die standing on the carrier: its body, an accent band and its label."""

    top = _MODULE_TOP + _DIE_H
    return [
        _box3d(length, width, _DIE_H, x=x, y=y, color=body, z_offset=_MODULE_TOP, metalness=0.04, roughness=0.62),
        _box3d(length * 0.6, max(width * 0.07, 0.3), 0.05, x=x, y=y + width * 0.32, color=accent, z_offset=top,
               metalness=0.12, roughness=0.5),
        {"shape": "text_decal", "text": label, "width": length * 0.8, "height": width * 0.45,
         "position": [x, top + 0.04, -y + width * 0.04], "rotation": [-math.pi / 2.0, 0.0, 0.0],
         "fontSize": max(int(min(length, width) * 9.0), 96), "color": ink or accent, "fontWeight": "800"},
    ]


def _pd_can_3d(x: float, y: float, radius: float) -> list[dict[str, Any]]:
    """A photodiode can on the carrier with its domed window."""

    return [_cylinder3d(radius, 0.9, x=x, y=y, color="#3a4a5a", z_offset=_MODULE_TOP, metalness=0.32, roughness=0.4),
            {"shape": "sphere", "radius": radius * 0.8, "scale": [1.0, 0.45, 1.0], "position": [x, _MODULE_TOP + 0.9, -y],
             "material": {"color": "#9fd9f5", "opacity": 0.75, "transparent": True, "metalness": 0.1, "roughness": 0.16}}]


def _trace_3d(x0: float, y0: float, x1: float, y1: float, color: str, width: float = 0.5) -> dict[str, Any]:
    """A trace or a waveguide on the carrier's top face, from (x0, y0) to (x1, y1) in the layout."""

    return _box3d(math.hypot(x1 - x0, y1 - y0), width, 0.08, x=(x0 + x1) / 2.0, y=(y0 + y1) / 2.0, color=color,
                  z_offset=_MODULE_TOP + 0.002, rotation_y=math.atan2(y1 - y0, x1 - x0), metalness=0.4, roughness=0.4)


def _port_metal_3d(ports: dict[str, Port], pad: float) -> list[dict[str, Any]]:
    """Gold tabs at the electrical ports, half out of the carrier's foot."""

    return [_box3d(pad * 1.6, pad * 1.6, 0.18, x=port.center.x, y=port.center.y, color=GOLD, z_offset=0.002, metalness=0.6, roughness=0.3)
            for port in ports.values() if port.kind == "electrical"]


class TIABlock(Component):
    """Standalone transimpedance amplifier or integrator drawn as an op-amp.

    ``mode="tia"`` places ``TIA`` inside the triangle. ``mode="integrator"``
    places the integral mark (a capacitor in the feedback of the 1D symbol).

    Parameters
    ----------
    center : tuple[float, float]
        Component center in local scene coordinates.
    angle : float
        Rotation angle in degrees.
    length, width : float
        Op-amp symbol footprint before ``visual_scale`` is applied.
    pad_size : float
        Electrical port width.
    mode : str
        ``tia`` for transimpedance amplifier, or ``integrator`` for integral
        symbol labeling.
    visual_style : str
        One of ``symbolic``, ``publication``, or ``physical``. The component is
        intentionally symbolic in 2D for all styles because an op-amp symbol is
        more recognizable than a square chip for this block.
    visual_scale : float
        Uniform scale factor applied to component geometry.
    color : str
        3D op-amp body color.
    opacity : float
        Symbol opacity used by 2D rendering.
    label : str
        Optional label stored on the component.
    gain_ohm, bandwidth_hz : float
        Datasheet numbers for the signal chain: the transimpedance ``V = gain I`` (the sign of an inverting stage is
        not modelled) and a first-order pole. None is the chain's model default.
    """

    component_type = "TIABlock"

    def __init__(
        self,
        center=(0, 0),
        angle: float = 0.0,
        length: float = 30.0,
        width: float = 20.0,
        pad_size: float = 2.0,
        mode: str = "tia",
        visual_style: str = "publication",
        visual_scale: float = 1.0,
        color: str = CHIP_BODY,
        opacity: float = 0.97,
        label: str = "",
        gain_ohm: float | None = None,
        bandwidth_hz: float | None = None,
    ):
        self.gain_ohm, self.bandwidth_hz = gain_ohm, bandwidth_hz   # for the signal chain; None: its model default
        self.visual_style = _style_key(visual_style)
        self.visual_scale = max(float(visual_scale), 0.05)
        self.length = _scaled(length, self.visual_scale)
        self.width = _scaled(width, self.visual_scale)
        self.pad_size = _scaled(pad_size, self.visual_scale)
        self.mode = _normalize_tia_mode(mode)
        _init_component(self, center, angle, color=color, opacity=opacity, label=label)

    def symbol_1d(self) -> tuple[str, dict[str, Any]] | None:
        return ("amplifier", {"mark": "capacitor"}) if self.mode == "integrator" else None

    # The pic od amplifier (ports=block), in its cm; its 1.2 cm from in to out is ``length``.
    PLAN = {"in": (-0.6, 0.0, 180.0), "out": (0.6, 0.0, 0.0), "vdd": (-0.1, 0.5, 90.0), "gnd": (-0.1, -0.5, -90.0)}

    def ports(self) -> dict[str, Port]:
        return _ports_on_plan(self.PLAN, self.length / 1.2, self.pad_size)

    @staticmethod
    def normalize_mode(mode: str) -> str:
        return _normalize_tia_mode(mode)

    def _symbol_label(self) -> str:
        """Return the text drawn inside the TIA/integrator triangle."""

        return _opamp_label(self.mode)

    def _symbol_outline(self) -> tuple[list[tuple[float, float]], float, float]:
        """Return the local op-amp triangle used by 1D/2D views."""

        return _opamp_outline(self.length, self.width)

    def _symbol_label_position(self) -> tuple[float, float]:
        """Return the local text position inside the op-amp triangle."""

        return _opamp_label_position(self.length, self.width)

    def _symbol_geometry_2d(self, *, line_width: float = 1.0, opacity: float = 1.0) -> list[dict[str, Any]]:
        """Return the complete 2D TIA/integrator symbol children."""

        return _opamp_symbol_2d(self.length, self.width, self.mode, line_width=line_width, opacity=opacity)

    def _body_3d(self) -> list[dict[str, Any]]:
        """Return the 3D op-amp body children."""

        return _opamp_body_3d(self.length, self.width, self.mode, body_color=self.color)

    def _symbolic_2d(self) -> dict[str, Any]:
        return {"type": "group", "children": self._symbol_geometry_2d(line_width=1.0, opacity=1.0)}

    def _amp_triangle(self) -> tuple[list[tuple[float, float]], float, float, float]:
        """A LARGE op-amp triangle that fills most of the footprint (so the label fits)."""

        L, W = self.length, self.width
        base_x, apex_x, half_h = -L * 0.34, L * 0.4, W * 0.46
        return [(base_x, -half_h), (base_x, half_h), (apex_x, 0.0)], base_x, apex_x, half_h

    def geometry_2d(self) -> dict[str, Any]:
        # An amplifier is a large triangular op-amp (not a rectangular chip):
        # filled triangle + differential inputs + bold TIA / ∫ label that fits.
        if self.visual_style == "symbolic":
            return self._symbolic_2d()
        accent = _ROLE_ACCENT["tia"]
        points, base_x, apex_x, half_h = self._amp_triangle()
        lead_w = max(self.width * 0.06, 0.5)
        return {
            "type": "group",
            "children": [
                _line(-self.length / 2.0, 0.0, base_x, 0.0, stroke=INK, stroke_width=lead_w, opacity=1.0),
                _line(apex_x, 0.0, self.length / 2.0, 0.0, stroke=INK, stroke_width=lead_w, opacity=1.0),
                _polygon(points, fill=self.color, opacity=self.opacity, stroke=accent, stroke_width=max(self.width * 0.05, 0.6)),
                # differential input stubs
                _line(base_x, half_h * 0.42, base_x + self.length * 0.08, half_h * 0.42, stroke="#cfd8e0", stroke_width=lead_w * 0.5, opacity=0.85),
                _line(base_x, -half_h * 0.42, base_x + self.length * 0.08, -half_h * 0.42, stroke="#cfd8e0", stroke_width=lead_w * 0.5, opacity=0.85),
                _text(self._symbol_label(), -self.length * 0.14, 0.0, size=max(self.width * 0.34, 5.5), fill=accent, opacity=1.0, font_weight="bold"),
            ],
        }

    def geometry_3d(self) -> dict[str, Any]:
        # Large triangular op-amp prism (not a chip block) + leads + flat TIA/∫ label.
        accent = _ROLE_ACCENT["tia"]
        points, base_x, apex_x, half_h = self._amp_triangle()
        L, W = self.length, self.width
        return {
            "shape": "group",
            "children": [
                {"shape": "extruded_polygon", "points": [(p[0] * 1.04, p[1] * 1.04) for p in points], "height": 0.2, "position": [0.0, -0.01, 0.0], "material": {"color": "#1b2129", "metalness": 0.1, "roughness": 0.62}},
                {"shape": "extruded_polygon", "points": points, "height": 1.3, "position": [0.0, 0.0, 0.0], "material": {"color": self.color, "metalness": 0.16, "roughness": 0.5}},
                _box3d(L * 0.16, max(W * 0.08, 0.6), 0.18, x=-L * 0.42, y=0.0, color=GOLD, z_offset=0.002, metalness=0.6, roughness=0.3),
                _box3d(L * 0.16, max(W * 0.08, 0.6), 0.18, x=L * 0.46, y=0.0, color=GOLD, z_offset=0.002, metalness=0.6, roughness=0.3),
                {"shape": "text_decal", "text": self._symbol_label(), "width": L * 0.36, "height": W * 0.44, "position": [-L * 0.12, 1.34, 0.0], "rotation": [-math.pi / 2.0, 0.0, 0.0], "fontSize": max(int(W * 8.0), 110), "color": accent, "fontWeight": "800"},
            ],
        }


class EIC(Component):
    """Electronic integrated-circuit package with selectable package visuals.

    ``EIC`` is the generic chip package component. Use ``role`` to add role
    specific top marks and internal traces for electronics such as logic, DAC,
    ADC, TIA, or general EIC blocks.

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
        Approximate package pin count used to place QFP/QFN leads or BGA balls.
    package_style : str
        One of ``qfp``, ``qfn``, ``bga``, or ``die``.
    role : str
        Role used for visual accents. Common values are ``eic``, ``logic``,
        ``mcu``, ``dac``, ``adc``, and ``tia``.
    visual_style : str
        One of ``symbolic``, ``publication``, or ``physical``.
    visual_scale : float
        Uniform scale factor applied to component geometry.
    color : str
        Package body color.
    opacity : float
        Package opacity used by 2D rendering.
    label : str
        Optional top label. DAC/ADC roles use it for the 3D top symbol when set.
    """

    component_type = "EIC"

    def __init__(
        self,
        center=(0, 0),
        angle: float = 0.0,
        length: float = 36.0,
        width: float = 28.0,
        pad_size: float = 2.0,
        pin_count: int = 12,
        package_style: str = "qfp",
        role: str = "eic",
        visual_style: str = "publication",
        visual_scale: float = 1.0,
        color: str = CHIP_BODY,
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
        self.role = role
        _init_component(self, center, angle, color=color, opacity=opacity, label=label)

    # The pic od eic, in its cm: a square package whose 0.96 cm from pin tip to pin tip is ``length``.
    PLAN = {"in": (-0.48, 0.0, 180.0), "out": (0.48, 0.0, 0.0), "ctrl": (-0.48, 0.2, 180.0),
            "sense": (0.48, -0.2, 0.0), "vdd": (0.0, 0.48, 90.0), "gnd": (0.0, -0.48, -90.0)}

    def ports(self) -> dict[str, Port]:
        return _ports_on_plan(self.PLAN, self.length / 0.96, self.pad_size)

    def _symbolic_2d(self) -> dict[str, Any]:
        return {
            "type": "group",
            "children": [
                _line(-self.length / 2.0, 0.0, -self.length * 0.22, 0.0, stroke=INK, stroke_width=1.0, opacity=1.0),
                _line(-self.length / 2.0, self.width * 0.28, -self.length * 0.22, self.width * 0.28, stroke=INK, stroke_width=1.0, opacity=1.0),
                _rect(0.0, 0.0, self.length * 0.44, self.width * 0.64, fill="none", opacity=1.0, stroke=INK, stroke_width=1.0),
                _line(self.length * 0.22, 0.0, self.length / 2.0, 0.0, stroke=INK, stroke_width=1.0, opacity=1.0),
                _line(self.length * 0.22, -self.width * 0.28, self.length / 2.0, -self.width * 0.28, stroke=INK, stroke_width=1.0, opacity=1.0),
                _line(0.0, self.width * 0.32, 0.0, self.width / 2.0, stroke=INK, stroke_width=0.8, opacity=1.0),
                _line(0.0, -self.width * 0.32, 0.0, -self.width / 2.0, stroke=INK, stroke_width=0.8, opacity=1.0),
                _text(self.role.upper()[:6], 0.0, 0.0, size=max(self.width * 0.14, 4.0), fill=INK, opacity=1.0, font_weight="bold"),
            ],
        }

    def _role_trace_children(self) -> list[dict[str, Any]]:
        """Return package top traces that visually explain the selected EIC role."""

        role_key = self.role.strip().lower()
        if role_key == "dac":
            return _converter_trace_children(self.length, self.width, self.pad_size, kind="dac", opacity=self.opacity)
        if role_key == "adc":
            return _converter_trace_children(self.length, self.width, self.pad_size, kind="adc", opacity=self.opacity)
        if role_key == "tia":
            triangle = [(-self.length * 0.18, -self.width * 0.18), (-self.length * 0.18, self.width * 0.18), (self.length * 0.18, 0.0)]
            return [
                _polygon(triangle, fill="none", opacity=0.9, stroke="#dce5eb", stroke_width=self.pad_size * 0.18),
                _circle(-self.length * 0.26, 0.0, self.pad_size * 0.24, fill=TIA_PURPLE, opacity=0.88),
                _polyline([(self.length * 0.18, 0.0), (self.length * 0.32, self.width * 0.12), (self.length * 0.32, -self.width * 0.12), (self.length * 0.18, 0.0)], stroke=TIA_PURPLE, stroke_width=self.pad_size * 0.14, opacity=0.82),
            ]
        return [
            _polyline([(-self.length * 0.22, 0.0), (-self.length * 0.08, self.width * 0.12), (self.length * 0.08, -self.width * 0.12), (self.length * 0.22, 0.0)], stroke="#d9e0ea", stroke_width=self.pad_size * 0.14, opacity=0.86),
            _line(-self.length * 0.34, self.width * 0.24, self.length * 0.34, self.width * 0.24, stroke=DIGITAL_BLUE, stroke_width=self.pad_size * 0.12, opacity=0.7),
        ]

    def _package_geometry_2d(self) -> list[dict[str, Any]]:
        """Return the EIC package body and package-specific 2D details."""

        return _ic_package_geometry_2d(self.length, self.width, self.pin_count, self.pad_size, self.opacity, self.package_style, self.color, self.role)

    def _package_geometry_3d(self) -> list[dict[str, Any]]:
        """Return the EIC package body and package-specific 3D details."""

        children = _ic_package_geometry_3d(self.length, self.width, self.pin_count, self.pad_size, self.package_style, self.color, self.role)
        role_key = _package_role_key(self.role)
        accent = _ROLE_ACCENT.get(role_key, "#8fa4e0")
        children.extend(_chip_label_3d(accent, self.label or role_key.upper(), self.length, self.width, IC_BODY_THICKNESS + 0.16))
        return children

    def geometry_2d(self) -> dict[str, Any]:
        if self.visual_style == "symbolic":
            return self._symbolic_2d()
        role_key = _package_role_key(self.role)
        accent = _ROLE_ACCENT.get(role_key, "#8fa4e0")
        return {
            "type": "group",
            "children": [
                *self._package_geometry_2d(),
                *self._role_trace_children(),
                _text(self.label or role_key.upper(), 0.0, -self.width * 0.2, size=max(self.width * 0.26, 4.2), fill=accent, opacity=1.0, font_weight="bold"),
            ],
        }

    def geometry_3d(self) -> dict[str, Any]:
        children = self._package_geometry_3d()
        return {"shape": "group", "children": children}

    def physics_metadata(self) -> dict[str, Any]:
        return {"component": "electronic_integrated_circuit", "role": self.role, "package_style": self.package_style, "pin_count": self.pin_count}


ElectronicIntegratedCircuit = EIC


class BalancedPhotodetector(Component):
    """Balanced photodetector block with optical inputs and differential outputs.

    This component represents the common pair of matched photodiodes used for
    balanced detection, homodyne/heterodyne receivers, and noise-rejecting lab
    diagrams. It is a schematic/readout primitive rather than a foundry PDK cell.

    Parameters
    ----------
    center : tuple[float, float]
        Component center in local scene coordinates.
    angle : float
        Rotation angle in degrees.
    length, width : float
        Body dimensions before ``visual_scale`` is applied.
    optical_gap : float
        Vertical spacing between the two optical input ports.
    output_gap : float
        Vertical spacing between the differential electrical output ports.
    pad_size : float
        Electrical port width and package pad size.
    responsivity_a_per_w : float
        Detector responsivity metadata placeholder.
    bandwidth_ghz : float
        Detector electrical bandwidth metadata placeholder.
    dark_current_na : float
        Dark-current metadata placeholder.
    cmrr_db : float
        Common-mode rejection metadata placeholder.
    visual_style : str
        One of ``symbolic``, ``publication``, or ``physical``.
    visual_scale : float
        Uniform scale factor applied to component geometry.
    color : str
        Body color used by publication and 3D views.
    opacity : float
        Component opacity used by 2D rendering.
    label : str
        Optional label stored on the component.
    """

    component_type = "BalancedPhotodetector"

    def __init__(
        self,
        center=(0, 0),
        angle: float = 0.0,
        length: float = 44.0,
        width: float = 28.0,
        optical_gap: float = 12.0,
        output_gap: float = 10.0,
        pad_size: float = 2.0,
        responsivity_a_per_w: float = 0.85,
        bandwidth_ghz: float = 25.0,
        dark_current_na: float = 5.0,
        cmrr_db: float = 28.0,
        visual_style: str = "publication",
        visual_scale: float = 1.0,
        color: str = "#24364a",
        opacity: float = 0.95,
        label: str = "",
    ):
        self.visual_style = _style_key(visual_style)
        self.visual_scale = max(float(visual_scale), 0.05)
        self.length = _scaled(length, self.visual_scale)
        self.width = _scaled(width, self.visual_scale)
        self.optical_gap = _scaled(optical_gap, self.visual_scale)
        self.output_gap = _scaled(output_gap, self.visual_scale)
        self.pad_size = _scaled(pad_size, self.visual_scale)
        self.responsivity_a_per_w = float(responsivity_a_per_w)
        self.bandwidth_ghz = float(bandwidth_ghz)
        self.dark_current_na = float(dark_current_na)
        self.cmrr_db = float(cmrr_db)
        _init_component(self, center, angle, color=color, opacity=opacity, label=label)

    def symbol_2d(self) -> tuple[str, dict[str, Any]]:
        return "photodiode", {"balanced": True, "ports": "block", "view": "top"}  # short inputs, long output

    def _bpd_layout(self) -> tuple[float, float, float]:
        """Shared geometry anchors: (diode column x, optical-input x, output x)."""

        col_x = -self.length * 0.04
        return col_x, col_x - self.pad_size * 1.6 * 2.6, self.length * 0.34

    def ports(self) -> dict[str, Port]:
        # Ports sit close to the actual device (short leads), not at the far edges.
        # The difference current is a SINGLE output tapped at the shared node.
        col_x, opt_x, out_x = self._bpd_layout()
        og2 = self.optical_gap / 2.0
        return {
            "opt_p": Port("opt_p", Vec3(opt_x, og2, 0.0), orientation_deg=180.0, width=self.pad_size * 1.4, kind="optical"),
            "opt_n": Port("opt_n", Vec3(opt_x, -og2, 0.0), orientation_deg=180.0, width=self.pad_size * 1.4, kind="optical"),
            "out": Port("out", Vec3(out_x, 0.0, 0.0), orientation_deg=0.0, width=self.pad_size, kind="electrical"),
            "bias": Port("bias", Vec3(col_x, self.width / 2.0, 0.0), orientation_deg=90.0, width=self.pad_size, kind="electrical"),
            "gnd": Port("gnd", Vec3(col_x, -self.width / 2.0, 0.0), orientation_deg=-90.0, width=self.pad_size, kind="electrical"),
        }

    def _photodiode_up(self, cx: float, cy: float, s: float, fill: str, lw: float) -> list[dict[str, Any]]:
        """An up-pointing photodiode symbol (triangle + cathode bar at the top apex)."""

        apex_y, base_y = cy + s, cy - s
        return [
            _polygon([(cx - s, base_y), (cx + s, base_y), (cx, apex_y)], fill=fill, opacity=1.0, stroke=INK, stroke_width=lw * 0.5),
            _line(cx - s * 1.1, apex_y, cx + s * 1.1, apex_y, stroke=INK, stroke_width=lw * 1.2, opacity=1.0),
        ]

    def _optical_in(self, x: float, y: float, s: float) -> list[dict[str, Any]]:
        """Two incident-light arrows pointing into a photodiode from the upper-left."""

        out: list[dict[str, Any]] = []
        aw = max(self.width * 0.035, 0.35)
        for off in (0.0, s * 0.7):
            ax1, ay1 = x - off * 0.2, y + off * 0.2
            out.append(_line(ax1 - s * 1.2, ay1 + s * 1.2, ax1, ay1, stroke=ANALOG_BLUE, stroke_width=aw, opacity=0.92))
            out.append(_polyline([(ax1 - s * 0.45, ay1 + s * 0.12), (ax1, ay1), (ax1 - s * 0.12, ay1 + s * 0.45)], stroke=ANALOG_BLUE, stroke_width=aw, opacity=0.92))
        return out

    def _detector_children_2d(self) -> list[dict[str, Any]]:
        # A balanced photodetector is two photodiodes in SERIES (both same direction),
        # with the shared centre node tapped as the difference output. No TIA.
        W = self.width
        og = self.optical_gap
        s = self.pad_size * 1.6
        col_x, _, out_x = self._bpd_layout()
        diode_fill = "#26303a"
        lead_w = max(W * 0.05, 0.5)
        ty, by = og / 2.0, -og / 2.0
        children: list[dict[str, Any]] = []
        # TOP photodiode: cathode (top) → +bias ; anode (bottom) → centre node
        children += self._photodiode_up(col_x, ty, s, diode_fill, lead_w)
        children.append(_line(col_x, ty + s, col_x, W / 2.0, stroke=GOLD, stroke_width=lead_w, opacity=0.95))
        children.append(_line(col_x, ty - s, col_x, 0.0, stroke=INK, stroke_width=lead_w, opacity=1.0))
        children += self._optical_in(col_x - s * 1.3, ty, s)
        # BOTTOM photodiode: cathode (top) → centre node ; anode (bottom) → −bias
        children += self._photodiode_up(col_x, by, s, diode_fill, lead_w)
        children.append(_line(col_x, by + s, col_x, 0.0, stroke=INK, stroke_width=lead_w, opacity=1.0))
        children.append(_line(col_x, by - s, col_x, -W / 2.0, stroke=GOLD_DARK, stroke_width=lead_w, opacity=0.95))
        children += self._optical_in(col_x - s * 1.3, by, s)
        # centre-tap node → SINGLE difference output line (already merged at the node)
        children.append(_circle(col_x, 0.0, max(s * 0.24, 0.7), fill=INK, opacity=1.0, stroke=INK, stroke_width=0.12))
        children.append(_line(col_x, 0.0, out_x, 0.0, stroke=INK, stroke_width=lead_w, opacity=1.0))
        children.append(_text("BPD", out_x * 0.62, W * 0.4, size=max(W * 0.2, 4.0), fill="#5d8fb2", opacity=1.0, font_weight="bold"))
        return children

    def geometry_2d(self) -> dict[str, Any]:
        # The free-space balanced detector is a clean schematic (two photodiodes in
        # series + centre tap); no chip substrate is drawn.
        return {"type": "group", "children": self._detector_children_2d()}

    def geometry_3d(self) -> dict[str, Any]:
        # Two photodiode cans (with domed optical windows + incident light beams)
        # wired in series at a balanced node — the difference output. No TIA.
        L, W = self.length, self.width
        og = self.optical_gap
        s = self.pad_size * 1.6
        col_x = -L * 0.04
        children: list[dict[str, Any]] = [
            _box3d(L * 0.9, W, 0.5, x=col_x * 0.5, y=0.0, color="#222c36", metalness=0.1, roughness=0.62),
        ]
        for sign, rail_color in ((1.0, GOLD), (-1.0, GOLD_DARK)):
            cy = sign * og / 2.0
            # photodiode can (mesa) + domed optical window (active area)
            children.append(_cylinder3d(s * 0.9, 0.95, x=col_x, y=cy, color="#3a4a5a", z_offset=0.5, metalness=0.32, roughness=0.4))
            children.append({"shape": "sphere", "radius": s * 0.75, "scale": [1.0, 0.5, 1.0], "position": [col_x, 1.55, -cy], "material": {"color": "#9fd9f5", "opacity": 0.72, "transparent": True, "metalness": 0.1, "roughness": 0.16}})
            # incident optical input beam from the left (glowing)
            children.append({"shape": "tube_path", "points": [[col_x - L * 0.32, 1.3, -cy], [col_x - s * 0.55, 1.3, -cy]], "radius": max(s * 0.16, 0.3), "segments": 12, "radialSegments": 10, "material": {"color": "#7fd4f0", "emissive": "#3aa0d0", "emissiveIntensity": 0.5, "opacity": 0.82, "transparent": True}})
            # bias / gnd rail lead
            children.append(_box3d(max(W * 0.05, 0.5), W / 2.0 - abs(cy), 0.16, x=col_x, y=(sign * W / 2.0 + cy) / 2.0, color=rail_color, z_offset=0.502, metalness=0.6, roughness=0.3))
        # series-connection node bus + difference output to the right
        children.append(_box3d(max(W * 0.06, 0.6), og * 0.92, 0.16, x=col_x, y=0.0, color="#cfd8e0", z_offset=0.502, metalness=0.5, roughness=0.3))
        children.append(_box3d(L * 0.34, max(W * 0.05, 0.5), 0.16, x=L * 0.18, y=0.0, color=COPPER, z_offset=0.5, metalness=0.6, roughness=0.3))
        return {"shape": "group", "children": children}

    def physics_metadata(self) -> dict[str, Any]:
        return {
            "component": "balanced_photodetector",
            "responsivity_a_per_w": self.responsivity_a_per_w,
            "bandwidth_ghz": self.bandwidth_ghz,
            "dark_current_na": self.dark_current_na,
            "cmrr_db": self.cmrr_db,
        }


class CoherentReceiver(Component):
    """Coherent optical receiver macro with hybrid, balanced detectors, and I/Q outputs.

    The macro is intended for architecture figures and teaching diagrams: it
    exposes optical signal/LO ports, electrical I/Q outputs, clock, power, and
    ground while carrying receiver metadata such as responsivity and bandwidth.

    Parameters
    ----------
    center : tuple[float, float]
        Component center in local scene coordinates.
    angle : float
        Rotation angle in degrees.
    length, width : float
        Macro footprint before ``visual_scale`` is applied.
    pad_size : float
        Electrical port width and trace size basis.
    optical_gap : float
        Vertical spacing between signal and LO optical inputs.
    output_gap : float
        Vertical spacing between I/Q differential output lanes.
    responsivity_a_per_w, bandwidth_ghz : float
        Metadata placeholders propagated to ``physics_metadata``.
    polarization_diverse : bool
        Marks whether the macro represents a polarization-diverse receiver.
    visual_style : str
        One of ``symbolic``, ``publication``, or ``physical``.
    visual_scale : float
        Uniform scale factor applied to component geometry.
    color : str
        Substrate/body color used by publication and 3D views.
    opacity : float
        Component opacity used by 2D rendering.
    label : str
        Optional label stored on the component.
    """

    component_type = "CoherentReceiver"

    def __init__(
        self,
        center=(0, 0),
        angle: float = 0.0,
        length: float = 78.0,
        width: float = 44.0,
        pad_size: float = 2.0,
        optical_gap: float = 14.0,
        output_gap: float = 9.0,
        responsivity_a_per_w: float = 0.85,
        bandwidth_ghz: float = 40.0,
        polarization_diverse: bool = False,
        visual_style: str = "publication",
        visual_scale: float = 1.0,
        color: str = "#1f3345",
        opacity: float = 0.94,
        label: str = "",
    ):
        self.visual_style = _style_key(visual_style)
        self.visual_scale = max(float(visual_scale), 0.05)
        self.length = _scaled(length, self.visual_scale)
        self.width = _scaled(width, self.visual_scale)
        self.pad_size = _scaled(pad_size, self.visual_scale)
        self.optical_gap = _scaled(optical_gap, self.visual_scale)
        self.output_gap = _scaled(output_gap, self.visual_scale)
        self.responsivity_a_per_w = float(responsivity_a_per_w)
        self.bandwidth_ghz = float(bandwidth_ghz)
        self.polarization_diverse = bool(polarization_diverse)
        _init_component(self, center, angle, color=color, opacity=opacity, label=label)

    def symbol_2d(self) -> tuple[str, dict[str, Any]]:
        return "coherentreceiver", {"view": "top"}  # in 2D the wide body with its ports on the edges

    def ports(self) -> dict[str, Port]:
        return {
            "signal": Port("signal", Vec3(-self.length / 2.0, self.optical_gap / 2.0, 0.0), orientation_deg=180.0, width=self.pad_size * 1.5, kind="optical"),
            "lo": Port("lo", Vec3(-self.length / 2.0, -self.optical_gap / 2.0, 0.0), orientation_deg=180.0, width=self.pad_size * 1.5, kind="optical"),
            "i_p": Port("i_p", Vec3(self.length / 2.0, self.output_gap * 1.5, 0.0), orientation_deg=0.0, width=self.pad_size, kind="electrical"),
            "i_n": Port("i_n", Vec3(self.length / 2.0, self.output_gap * 0.5, 0.0), orientation_deg=0.0, width=self.pad_size, kind="electrical"),
            "q_p": Port("q_p", Vec3(self.length / 2.0, -self.output_gap * 0.5, 0.0), orientation_deg=0.0, width=self.pad_size, kind="electrical"),
            "q_n": Port("q_n", Vec3(self.length / 2.0, -self.output_gap * 1.5, 0.0), orientation_deg=0.0, width=self.pad_size, kind="electrical"),
            "clk": Port("clk", Vec3(self.length * 0.22, self.width / 2.0, 0.0), orientation_deg=90.0, width=self.pad_size, kind="electrical"),
            "vdd": Port("vdd", Vec3(-self.length * 0.12, self.width / 2.0, 0.0), orientation_deg=90.0, width=self.pad_size, kind="electrical"),
            "gnd": Port("gnd", Vec3(0.0, -self.width / 2.0, 0.0), orientation_deg=-90.0, width=self.pad_size, kind="electrical"),
        }

    def _hybrid_outline(self) -> list[tuple[float, float]]:
        """The 90 degree hybrid body: a diamond, its tips on the axis."""

        hybrid_x = -self.length * 0.24
        return [(hybrid_x - self.pad_size * 2.2, 0.0), (hybrid_x, self.width * 0.22),
                (hybrid_x + self.pad_size * 2.2, 0.0), (hybrid_x, -self.width * 0.22)]

    def _hybrid_half_width(self, y: float) -> float:
        """Half the width of the hybrid body at height ``y`` (0 at and beyond its top and bottom tips)."""

        return max(self.pad_size * 2.2 * (1.0 - abs(y) / (self.width * 0.22)), 0.0)

    def _diode_entry(self, lane_y: float, sign: float) -> tuple[float, float]:
        """Where the lane's branch to the diode above (``sign`` 1) or below (-1) the lane ends: 0.15 inside its circle."""

        radius = self.pad_size * 1.05
        centre = (self.length * 0.06, lane_y + sign * self.output_gap * 0.28)
        tip = (self.length * 0.06 - self.pad_size * 2.0, lane_y)
        reach = math.dist(tip, centre)
        back = radius - 0.15
        return (centre[0] + (tip[0] - centre[0]) / reach * back, centre[1] + (tip[1] - centre[1]) / reach * back)

    def geometry_2d(self) -> dict[str, Any]:
        hybrid_x = -self.length * 0.24
        detector_x = self.length * 0.06
        output_x = self.length * 0.28
        lanes = [("I", self.output_gap), ("Q", -self.output_gap)]
        children: list[dict[str, Any]] = []
        if self.visual_style != "symbolic":
            children.append(_rect(0.0, 0.0, self.length, self.width, fill=self.color, opacity=0.2, stroke="#66788c", stroke_width=0.12))
        # The input lines and the lane lines end on the hybrid's edge, so the drawn guides meet the body.
        children.extend([
            _line(-self.length / 2.0, self.optical_gap / 2.0, hybrid_x - self._hybrid_half_width(self.optical_gap / 2.0), self.optical_gap / 2.0, stroke=ANALOG_BLUE, stroke_width=0.8, opacity=0.9),
            _line(-self.length / 2.0, -self.optical_gap / 2.0, hybrid_x - self._hybrid_half_width(self.optical_gap / 2.0), -self.optical_gap / 2.0, stroke=ANALOG_BLUE, stroke_width=0.8, opacity=0.9),
            _polygon(self._hybrid_outline(), fill="#dbe7ef", opacity=0.94, stroke="#4e6c7e", stroke_width=0.12),
            _text("90", hybrid_x, 0.0, size=max(self.pad_size * 1.35, 3.2), fill="#29485a", opacity=0.9),
        ])
        for label, lane_y in lanes:
            children.extend([
                _line(hybrid_x + self._hybrid_half_width(lane_y), lane_y, detector_x - self.pad_size * 2.0, lane_y, stroke=ANALOG_BLUE, stroke_width=0.62, opacity=0.86),
                # the lane forks to its two diodes: each branch ends just inside the circle drawn over it
                *[_line(detector_x - self.pad_size * 2.0, lane_y, *self._diode_entry(lane_y, sign), stroke=ANALOG_BLUE, stroke_width=0.62, opacity=0.86)
                  for sign in (1.0, -1.0)],
                _circle(detector_x, lane_y + self.output_gap * 0.28, self.pad_size * 1.05, fill="#81a9bb", opacity=0.92, stroke="#24495a", stroke_width=0.07),
                _circle(detector_x, lane_y - self.output_gap * 0.28, self.pad_size * 1.05, fill="#81a9bb", opacity=0.92, stroke="#24495a", stroke_width=0.07),
                _rect(output_x, lane_y, self.length * 0.16, self.output_gap * 0.62, fill="#f1f3f5", opacity=0.94, stroke="#a5adba", stroke_width=0.08),
                _text(label, output_x, lane_y, size=max(self.pad_size * 1.45, 3.2), fill=INK, opacity=0.9),
                _line(output_x + self.length * 0.08, lane_y + self.output_gap * 0.25, self.length / 2.0, lane_y + self.output_gap * 0.5, stroke=DIGITAL_BLUE, stroke_width=0.42, opacity=0.88),
                _line(output_x + self.length * 0.08, lane_y - self.output_gap * 0.25, self.length / 2.0, lane_y - self.output_gap * 0.5, stroke=DIGITAL_BLUE, stroke_width=0.42, opacity=0.88),
            ])
        return {"type": "group", "children": children}

    DETECTORS = ("_detector_ip", "_detector_in", "_detector_qp", "_detector_qn")

    def optical_paths(self, in_port: str) -> list[dict[str, Any]]:
        """Along the drawn guides: the input line to the hybrid, across the hybrid body, along the lane.

        The hybrid is a multimode region (its outline is the path's region). The light crosses it through its
        centre, so all four paths have the same length. The lane forks to its two diodes and each path ends
        just inside its diode circle, where the drawn branch stroke ends. The port of each path is the
        internal detector port that the engine absorbs the light in.
        """

        if in_port not in ("signal", "lo"):
            return []
        hybrid_x, detector_x = -self.length * 0.24, self.length * 0.06
        start = self.ports()[in_port].center
        region = {"kind": "mmi", "outline": [list(point) for point in self._hybrid_outline()]}
        paths = []
        for j, target in enumerate(self.DETECTORS):
            lane = self.output_gap if j < 2 else -self.output_gap
            paths.append({"port": target, "power": 0.25, "region": region, "pts": [
                [start.x, start.y], [hybrid_x - self._hybrid_half_width(start.y), start.y],
                [hybrid_x, 0.0], [hybrid_x + self._hybrid_half_width(lane), lane],
                [detector_x - self.pad_size * 2.0, lane],
                list(self._diode_entry(lane, 1.0 if j % 2 == 0 else -1.0))]})
        return paths

    def geometry_3d(self) -> dict[str, Any]:
        """The module: the 90 degree hybrid die, a balanced pair of photodiodes per lane, the I and Q TIA dies."""

        L, W, pad, og = self.length, self.width, self.pad_size, self.output_gap
        hybrid_x, detector_x, output_x = -L * 0.24, L * 0.06, L * 0.28
        children = _module_3d(L, W, self.color)
        children += _die_3d(hybrid_x, 0.0, pad * 4.4, W * 0.44, "90°", _SILICON_3D, body=_PHOTONIC_DIE, ink="#1a4373")
        for y in (self.optical_gap / 2.0, -self.optical_gap / 2.0):
            children.append(_trace_3d(-L / 2.0, y, hybrid_x - pad * 2.2, y, _SILICON_3D, 0.8))
        for label, lane in (("I", og), ("Q", -og)):
            for sign in (1.0, -1.0):
                pd_y = lane + sign * og * 0.28
                children.append(_trace_3d(hybrid_x + pad * 2.2, lane * 0.4, detector_x - pad, pd_y, _SILICON_3D, 0.6))
                children += _pd_can_3d(detector_x, pd_y, pad * 1.05)
                children.append(_trace_3d(detector_x + pad, pd_y, output_x - L * 0.08, lane + sign * og * 0.2, COPPER, 0.45))
                children.append(_trace_3d(output_x + L * 0.08, lane + sign * og * 0.25, L / 2.0, lane + sign * og * 0.5,
                                          DIGITAL_BLUE, 0.42))
            children += _die_3d(output_x, lane, L * 0.16, og * 0.62, label, _ROLE_ACCENT["tia"])
        children += _port_metal_3d(self.ports(), pad)
        return {"shape": "group", "children": children}

    def physics_metadata(self) -> dict[str, Any]:
        return {"component": "coherent_receiver", "responsivity_a_per_w": self.responsivity_a_per_w, "bandwidth_ghz": self.bandwidth_ghz, "polarization_diverse": self.polarization_diverse}


class TransmitterMacro(Component):
    """PIC transmitter macro combining control, driver, modulator, and optical output.

    The macro is a compact system block for figures that need to show a digital
    drive path becoming a modulated optical output. It does not replace detailed
    on-chip modulator components; it gives block diagrams a routeable endpoint.

    Parameters
    ----------
    center : tuple[float, float]
        Component center in local scene coordinates.
    angle : float
        Rotation angle in degrees.
    length, width : float
        Macro footprint before ``visual_scale`` is applied. By default the width is the plan's: the bias and
        ground ports sit on the module's edges, as the data and optical ports do.
    pad_size : float
        Electrical port width and trace size basis.
    data_rate_gbps : float
        Data-rate metadata placeholder.
    wavelength_nm : float
        Optical carrier wavelength metadata placeholder.
    extinction_ratio_db : float
        Extinction-ratio metadata placeholder.
    visual_style : str
        One of ``symbolic``, ``publication``, or ``physical``.
    visual_scale : float
        Uniform scale factor applied to component geometry.
    color : str
        Body/substrate color used by publication and 3D views.
    opacity : float
        Component opacity used by 2D rendering.
    label : str
        Optional label stored on the component.
    """

    component_type = "TransmitterMacro"

    def __init__(
        self,
        center=(0, 0),
        angle: float = 0.0,
        length: float = 82.0,
        width: float | None = None,
        pad_size: float = 2.0,
        data_rate_gbps: float = 50.0,
        wavelength_nm: float = 1550.0,
        extinction_ratio_db: float = 6.0,
        visual_style: str = "publication",
        visual_scale: float = 1.0,
        color: str = "#273746",
        opacity: float = 0.94,
        label: str = "",
    ):
        self.visual_style = _style_key(visual_style)
        self.visual_scale = max(float(visual_scale), 0.05)
        self.length = _scaled(length, self.visual_scale)
        self.width = self.length / 1.9 if width is None else _scaled(width, self.visual_scale)   # the plan's 1 cm
        self.pad_size = _scaled(pad_size, self.visual_scale)
        self.data_rate_gbps = float(data_rate_gbps)
        self.wavelength_nm = float(wavelength_nm)
        self.extinction_ratio_db = float(extinction_ratio_db)
        _init_component(self, center, angle, color=color, opacity=opacity, label=label)

    # The pic od transmitter, in its cm; its 1.9 cm from the data leads to the optical output is ``length``.
    PLAN = {"data": (-0.95, 0.14, 180.0), "clk": (-0.95, -0.14, 180.0), "bias": (0.0, 0.5, 90.0), "gnd": (0.0, -0.5, -90.0)}

    def ports(self) -> dict[str, Port]:
        return {**_ports_on_plan(self.PLAN, self.length / 1.9, self.pad_size),
                "opt_out": Port("opt_out", Vec3(self.length / 2.0, 0.0, 0.0), orientation_deg=0.0, width=self.pad_size * 1.5, kind="optical")}

    def geometry_2d(self) -> dict[str, Any]:
        dac_x = -self.length * 0.28
        driver_x = 0.0
        mod_x = self.length * 0.28
        children: list[dict[str, Any]] = []
        if self.visual_style != "symbolic":
            children.append(_rect(0.0, 0.0, self.length, self.width, fill=self.color, opacity=0.2, stroke="#697789", stroke_width=0.12))
        children.extend(_offset_geometry_2d(child, dac_x, 0.0) for child in _converter_symbol_2d("dac", self.length * 0.22, self.width * 0.42, "DAC", line_width=0.8, opacity=0.95))
        children.extend(_offset_geometry_2d(child, driver_x, 0.0) for child in RFDriver(length=self.length * 0.2, width=self.width * 0.42, output_gap=self.pad_size * 3.2, visual_style="symbolic", opacity=self.opacity).geometry_2d()["children"])
        children.extend([
            _line(-self.length / 2.0, self.width * 0.2, dac_x - self.length * 0.11, self.width * 0.08, stroke=DIGITAL_BLUE, stroke_width=0.45, opacity=0.88),
            _line(-self.length / 2.0, -self.width * 0.2, dac_x - self.length * 0.11, -self.width * 0.08, stroke=DIGITAL_BLUE, stroke_width=0.45, opacity=0.88),
            _line(dac_x + self.length * 0.11, 0.0, driver_x - self.length * 0.1, 0.0, stroke=SIGNAL_COLORS["rf"], stroke_width=0.48, opacity=0.88),
            _line(driver_x + self.length * 0.1, self.pad_size * 1.6, mod_x - self.length * 0.1, self.pad_size * 1.6, stroke=SIGNAL_COLORS["rf"], stroke_width=0.45, opacity=0.88),
            _line(driver_x + self.length * 0.1, -self.pad_size * 1.6, mod_x - self.length * 0.1, -self.pad_size * 1.6, stroke=SIGNAL_COLORS["rf"], stroke_width=0.45, opacity=0.88),
            _rect(mod_x, 0.0, self.length * 0.2, self.width * 0.36, fill="#dce5eb", opacity=0.92, stroke="#677b8b", stroke_width=0.1),
            _polyline([(mod_x - self.length * 0.08, 0.0), (mod_x, self.width * 0.08), (mod_x + self.length * 0.08, 0.0)], stroke=ANALOG_BLUE, stroke_width=0.55, opacity=0.9),
            _line(mod_x + self.length * 0.1, 0.0, self.length / 2.0, 0.0, stroke=ANALOG_BLUE, stroke_width=0.75, opacity=0.9),
            _line(0.0, self.width * 0.21, 0.0, self.width / 2.0, stroke=COPPER, stroke_width=0.4, opacity=0.9),
            _line(0.0, -self.width * 0.21, 0.0, -self.width / 2.0, stroke=COPPER, stroke_width=0.4, opacity=0.9),
        ])
        return {"type": "group", "children": children}

    def geometry_3d(self) -> dict[str, Any]:
        """The module: the DAC die, the RF driver die, the modulator's photonic die and its optical output."""

        L, W, pad = self.length, self.width, self.pad_size
        dac_x, driver_x, mod_x = -L * 0.28, 0.0, L * 0.28
        rf = SIGNAL_COLORS["rf"]
        ports = self.ports()
        children = _module_3d(L, W, self.color)
        children += [*[_trace_3d(-L / 2.0, ports[name].center.y, dac_x - L * 0.11, s * W * 0.08, DIGITAL_BLUE, 0.45)
                       for name, s in (("data", 1.0), ("clk", -1.0))],
                     _trace_3d(dac_x + L * 0.11, 0.0, driver_x - L * 0.1, 0.0, rf, 0.48),
                     *[_trace_3d(driver_x + L * 0.1, s * pad * 1.6, mod_x - L * 0.1, s * pad * 1.6, rf, 0.45) for s in (1.0, -1.0)],
                     _trace_3d(mod_x + L * 0.1, 0.0, L / 2.0, 0.0, _SILICON_3D, 0.8),
                     *[_trace_3d(0.0, s * W * 0.21, 0.0, ports[name].center.y, COPPER, 0.4) for name, s in (("bias", 1.0), ("gnd", -1.0))]]
        children += _die_3d(dac_x, 0.0, L * 0.22, W * 0.42, "DAC", _ROLE_ACCENT["dac"])
        children += _die_3d(driver_x, 0.0, L * 0.2, W * 0.42, "DRV", rf)
        children += _die_3d(mod_x, 0.0, L * 0.2, W * 0.36, "MOD", _SILICON_3D, body=_PHOTONIC_DIE, ink="#1a4373")
        children += _port_metal_3d(ports, pad)
        return {"shape": "group", "children": children}

    def physics_metadata(self) -> dict[str, Any]:
        return {"component": "transmitter_macro", "data_rate_gbps": self.data_rate_gbps, "wavelength_nm": self.wavelength_nm, "extinction_ratio_db": self.extinction_ratio_db}


class ReceiverMacro(Component):
    """Detector-to-digital receiver macro with photodetector, TIA, and ADC stages.

    ``ReceiverMacro`` is the single-ended complement to ``CoherentReceiver`` for
    quick system figures. It keeps the optical input and digital output ports
    explicit while showing the readout chain inside one compact block.

    Parameters
    ----------
    center : tuple[float, float]
        Component center in local scene coordinates.
    angle : float
        Rotation angle in degrees.
    length, width : float
        Macro footprint before ``visual_scale`` is applied. By default the width is the plan's: the bias, clock
        and ground ports sit on the module's edges, as the optical and digital ports do.
    pad_size : float
        Electrical port width and trace size basis.
    responsivity_a_per_w, bandwidth_ghz, adc_bits : float | int
        Readout metadata placeholders propagated to ``physics_metadata``.
    visual_style : str
        One of ``symbolic``, ``publication``, or ``physical``.
    visual_scale : float
        Uniform scale factor applied to component geometry.
    color : str
        Body/substrate color used by publication and 3D views.
    opacity : float
        Component opacity used by 2D rendering.
    label : str
        Optional label stored on the component.
    """

    component_type = "ReceiverMacro"

    def __init__(
        self,
        center=(0, 0),
        angle: float = 0.0,
        length: float = 76.0,
        width: float | None = None,
        pad_size: float = 2.0,
        responsivity_a_per_w: float = 0.85,
        bandwidth_ghz: float = 25.0,
        adc_bits: int = 8,
        visual_style: str = "publication",
        visual_scale: float = 1.0,
        color: str = "#26384a",
        opacity: float = 0.94,
        label: str = "",
    ):
        self.visual_style = _style_key(visual_style)
        self.visual_scale = max(float(visual_scale), 0.05)
        self.length = _scaled(length, self.visual_scale)
        self.width = self.length / 1.9 if width is None else _scaled(width, self.visual_scale)   # the plan's 1 cm
        self.pad_size = _scaled(pad_size, self.visual_scale)
        self.responsivity_a_per_w = float(responsivity_a_per_w)
        self.bandwidth_ghz = float(bandwidth_ghz)
        self.adc_bits = max(int(adc_bits), 1)
        _init_component(self, center, angle, color=color, opacity=opacity, label=label)

    # The pic od receiver, in its cm; its 1.9 cm from the optical input to the digital output is ``length``.
    PLAN = {"digital_out": (0.95, 0.0, 0.0), "clk": (0.35, 0.5, 90.0), "bias": (-0.3, 0.5, 90.0), "gnd": (0.0, -0.5, -90.0)}

    def ports(self) -> dict[str, Port]:
        return {"opt_in": Port("opt_in", Vec3(-self.length / 2.0, 0.0, 0.0), orientation_deg=180.0, width=self.pad_size * 1.5, kind="optical"),
                **_ports_on_plan(self.PLAN, self.length / 1.9, self.pad_size)}

    def geometry_2d(self) -> dict[str, Any]:
        pd_x = -self.length * 0.27
        tia_x = 0.0
        adc_x = self.length * 0.28
        children: list[dict[str, Any]] = []
        if self.visual_style != "symbolic":
            children.append(_rect(0.0, 0.0, self.length, self.width, fill=self.color, opacity=0.2, stroke="#657587", stroke_width=0.12))
        children.extend([
            _line(-self.length / 2.0, 0.0, pd_x - self.pad_size * 1.4, 0.0, stroke=ANALOG_BLUE, stroke_width=0.75, opacity=0.9),
            _circle(pd_x, 0.0, self.pad_size * 1.55, fill="#81a9bb", opacity=0.94, stroke="#24495a", stroke_width=0.08),
            _line(pd_x + self.pad_size * 1.55, 0.0, tia_x - self.length * 0.1, 0.0, stroke=COPPER, stroke_width=0.4, opacity=0.9),
            *_offset_geometry_2d(TIABlock(length=self.length * 0.22, width=self.width * 0.42, pad_size=self.pad_size, opacity=self.opacity).geometry_2d(), tia_x, 0.0)["children"],
            _line(tia_x + self.length * 0.11, 0.0, adc_x - self.length * 0.11, 0.0, stroke=TIA_PURPLE, stroke_width=0.46, opacity=0.88),
            *_offset_geometry_2d(ADCBlock(length=self.length * 0.22, width=self.width * 0.45, pad_size=self.pad_size, bit_count=self.adc_bits, visual_style="symbolic", opacity=self.opacity).geometry_2d(), adc_x, 0.0)["children"],
            _line(adc_x + self.length * 0.11, 0.0, self.length / 2.0, 0.0, stroke=DIGITAL_BLUE, stroke_width=0.5, opacity=0.88),
            _line(self.length * 0.24, self.width * 0.225, self.length * 0.24, self.width / 2.0, stroke=DIGITAL_BLUE, stroke_width=0.4, opacity=0.9),
            _line(-self.length * 0.2, self.width * 0.21, -self.length * 0.2, self.width / 2.0, stroke=COPPER, stroke_width=0.4, opacity=0.9),
            _line(0.0, -self.width * 0.21, 0.0, -self.width / 2.0, stroke=COPPER, stroke_width=0.4, opacity=0.9),
        ])
        return {"type": "group", "children": children}

    def geometry_3d(self) -> dict[str, Any]:
        """The module: the photodiode on its input guide, the TIA die, the ADC die and the digital output."""

        L, W, pad = self.length, self.width, self.pad_size
        pd_x, tia_x, adc_x = -L * 0.27, 0.0, L * 0.28
        ports = self.ports()
        children = _module_3d(L, W, self.color)
        children += [_trace_3d(-L / 2.0, 0.0, pd_x - pad * 1.55, 0.0, _SILICON_3D, 0.8),
                     _trace_3d(pd_x + pad * 1.55, 0.0, tia_x - L * 0.1, 0.0, COPPER, 0.45),
                     _trace_3d(tia_x + L * 0.1, 0.0, adc_x - L * 0.1, 0.0, TIA_PURPLE, 0.45),
                     _trace_3d(adc_x + L * 0.1, 0.0, L / 2.0, 0.0, DIGITAL_BLUE, 0.5),
                     *[_trace_3d(ports[name].center.x, s * W * 0.21, ports[name].center.x, ports[name].center.y, color, 0.4)
                       for name, s, color in (("clk", 1.0, DIGITAL_BLUE), ("bias", 1.0, COPPER), ("gnd", -1.0, COPPER))]]
        children += _pd_can_3d(pd_x, 0.0, pad * 1.55)
        children += _die_3d(tia_x, 0.0, L * 0.2, W * 0.4, "TIA", _ROLE_ACCENT["tia"])
        children += _die_3d(adc_x, 0.0, L * 0.2, W * 0.42, "ADC", _ROLE_ACCENT["adc"])
        children += _port_metal_3d(ports, pad)
        return {"shape": "group", "children": children}

    def physics_metadata(self) -> dict[str, Any]:
        return {"component": "receiver_macro", "responsivity_a_per_w": self.responsivity_a_per_w, "bandwidth_ghz": self.bandwidth_ghz, "adc_bits": self.adc_bits}
