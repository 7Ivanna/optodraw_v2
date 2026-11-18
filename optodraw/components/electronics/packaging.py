"""Packaging electronics components."""

from __future__ import annotations
import math
from typing import Any
from optodraw.core.component import Component
from optodraw.core.ports import Port
from optodraw.core.schematic_geometry import PhysicalSpec, SchematicDims, resolve_schematic_dims
from optodraw.core.transform import Vec3, as_vec3 as _as_vec3

from optodraw.components.electronics._shared import (
    ELECTRONICS_SCHEMATIC_TABLES,
    BOARD_THICKNESS,
    COPPER,
    GOLD,
    GOLD_DARK,
    INK,
    _box3d,
    _init_component,
    _line,
    _polyline,
    _rect,
    _side_port,
    _style_key,
    _text,
)

# --- Packaging visual tokens -------------------------------------------------
# One place for colors and widths that packaging parts share. No component
# should introduce a new bare hex or stroke width for the same metal again.

# semantic fills
PAD_EDGE_FILL = GOLD_DARK
PAD_CORE_FILL = "#e7c069"
PAD_HIGHLIGHT = "#fff1bd"
PAD_SHEEN = "#fff7df"
PAD_OPENING_MASK = "#cfe3df"
HEATER_HIGHLIGHT = "#f0c087"

# stroke system
HAIRLINE = 0.08
OUTLINE_THIN = 0.12
OUTLINE = 0.16
OPENING_STROKE = 0.5
HIGHLIGHT_STROKE = 0.28

# 3D metal presets — metalness/roughness only, color stays explicit
METAL_GOLD = {"metalness": 0.74, "roughness": 0.24}
METAL_GOLD_EDGE = {"metalness": 0.70, "roughness": 0.30}
METAL_COPPER = {"metalness": 0.58, "roughness": 0.30}
METAL_PASSIVATION = {"metalness": 0.05, "roughness": 0.72}


class PackagingComponent(Component):
    """Schematic-first base for bond pads, wirebonds, and package stubs.

    **Two truths:** ``geometry_2d`` / ``geometry_3d`` default to legible diagram
    dimensions; ``ports()`` and routing stay at user physical sizes. Pass
    ``render_physical=True`` to draw true footprints. ``visual_style`` selects
    publication vs presentation detail.
    """

    schematic_family: str = "electrical_pad"
    render_physical: bool = False
    visual_scale: float = 1.0
    visual_style: str = "publication"

    def _init_packaging(
        self,
        center,
        angle: float,
        *,
        visual_scale: float = 1.0,
        render_physical: bool = False,
        visual_style: str = "publication",
        color: str,
        opacity: float,
        label: str,
    ) -> None:
        self.visual_scale = max(float(visual_scale), 0.05)
        self.render_physical = bool(render_physical)
        self.visual_style = _style_key(visual_style)
        _init_component(self, center, angle, color=color, opacity=opacity, label=label)

    def physical_spec(self) -> PhysicalSpec:
        return PhysicalSpec(device_family=self.schematic_family, values={})

    def schematic_dims(self) -> SchematicDims:
        overrides = dict(ELECTRONICS_SCHEMATIC_TABLES.get(self.schematic_family, {}))
        return resolve_schematic_dims(
            self.schematic_family,
            self.physical_spec(),
            visual_scale=self.visual_scale,
            overrides=overrides,
        )

    def _physical_value(self, key: str, default: float | None = None) -> float:
        if hasattr(self, key):
            return float(getattr(self, key))
        if default is not None:
            return float(default)
        raise KeyError(f"No physical dimension '{key}' for {self.component_type}")

    def _draw(self, key: str, default: float | None = None) -> float:
        """Dimension for 2D/3D art — schematic floor unless ``render_physical``."""

        physical = self._physical_value(key, default)
        if self.render_physical:
            return physical
        table = self.schematic_dims().get(key)
        if table is not None:
            return max(float(table), physical)
        return physical

    def _draw_sag(self, *, sag_min_key: str = "sag_min") -> float:
        physical = float(self.sag)
        if self.render_physical:
            return physical
        table_min = self.schematic_dims().get(sag_min_key)
        if table_min is not None:
            return max(float(table_min), physical)
        return physical

    def _draw_thickness(self) -> float:
        shared = ELECTRONICS_SCHEMATIC_TABLES.get("_shared", {})
        return self._draw("thickness", default=shared.get("thickness", 0.24))

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        if self.render_physical:
            data["render_physical"] = True
        if self.visual_scale != 1.0:
            data["visual_scale"] = self.visual_scale
        if getattr(self, "visual_style", "publication") != "publication":
            data["visual_style"] = self.visual_style
        return data


class ElectricalPad(PackagingComponent):
    """Metal bond or probe pad with one electrical port.

    Use this component for simple wirebond pads, RF probe contact points,
    package landing pads, or labeled electrical endpoints in a layout sketch.

    Parameters
    ----------
    center : tuple[float, float]
        Pad center in local scene coordinates.
    angle : float
        Rotation angle in degrees.
    width, height : float
        Pad body dimensions.
    port_side : str
        Side where port ``e1`` is placed. One of ``left``, ``right``, ``top``,
        ``bottom``, or ``center``.
    port_width : float | None
        Electrical port width. Defaults to the smaller pad dimension.
    layer : str | None
        Optional electrical layer name stored on the port.
    pad_opening : bool
        Draw a lighter inner opening outline when ``True``.
    color : str
        Pad metal color.
    opacity : float
        Pad opacity used by 2D rendering.
    label : str
        Optional label stored on the component.
    """

    component_type = "ElectricalPad"
    schematic_family = "electrical_pad"

    def __init__(
        self,
        center=(0, 0),
        angle: float = 0.0,
        width: float = 28.0,
        height: float = 28.0,
        port_side: str = "left",
        port_width: float | None = None,
        layer: str | None = "M1",
        pad_opening: bool = True,
        color: str = GOLD,
        opacity: float = 0.92,
        label: str = "",
        visual_style: str = "publication",
        visual_scale: float = 1.0,
        render_physical: bool = False,
    ):
        self.width = float(width)
        self.height = float(height)
        self.port_side = port_side
        self.port_width = float(port_width if port_width is not None else min(self.width, self.height))
        self.layer = layer
        self.pad_opening = pad_opening
        _side_port(port_side, self.width, self.height, self.port_width, layer)
        self._init_packaging(
            center,
            angle,
            visual_style=visual_style,
            visual_scale=visual_scale,
            render_physical=render_physical,
            color=color,
            opacity=opacity,
            label=label,
        )

    def physical_spec(self) -> PhysicalSpec:
        return PhysicalSpec(
            device_family=self.schematic_family,
            values={
                "width": self.width,
                "height": self.height,
                "port_width": self.port_width,
                "thickness": 0.24,
            },
        )

    def ports(self) -> dict[str, Port]:
        return {"e1": _side_port(self.port_side, self.width, self.height, self.port_width, self.layer)}

    def _draw(self, key: str, default: float | None = None) -> float:
        # a pad is already a visible size: it draws at the width and height it is given, so its port sits on
        # its drawn edge and a compact figure can use small pads
        if key in ("width", "height"):
            return self._physical_value(key, default)
        return super()._draw(key, default)

    def geometry_2d(self) -> dict[str, Any]:
        w = self._draw("width")
        h = self._draw("height")
        if self.visual_style == "symbolic":
            return {
                "type": "group",
                "children": [
                    _rect(0.0, 0.0, w, h, fill="none", opacity=1.0, stroke=INK, stroke_width=OUTLINE),
                ],
            }
        children = [
            _rect(0.0, 0.0, w, h, fill=PAD_EDGE_FILL, opacity=self.opacity, stroke=PAD_EDGE_FILL, stroke_width=OUTLINE_THIN),
            _rect(0.0, 0.0, w * 0.94, h * 0.94, fill=self.color, opacity=self.opacity, stroke="#7a5a14", stroke_width=HAIRLINE),
            # single bright core with highlight stroke — was two rects
            _rect(0.0, 0.0, w * 0.7, h * 0.7, fill=PAD_CORE_FILL, opacity=min(self.opacity, 0.96), stroke=PAD_HIGHLIGHT, stroke_width=HIGHLIGHT_STROKE),
        ]
        if self.visual_style == "presentation":
            children.append(_line(-w * 0.34, h * 0.12, w * 0.02, h * 0.32, stroke=PAD_SHEEN, stroke_width=0.5, opacity=0.5))
        if self.pad_opening:
            children.append(_rect(0.0, 0.0, w * 0.82, h * 0.82, fill="none", opacity=1.0, stroke=PAD_OPENING_MASK, stroke_width=OPENING_STROKE))
        return {"type": "group", "children": children}

    def geometry_3d(self) -> dict[str, Any]:
        w = self._draw("width")
        h = self._draw("height")
        t = self._draw_thickness()
        # discrete z levels to avoid coplanar flicker
        z0 = 0.04
        z1 = z0 + t * 0.6
        z2 = z0 + t + 0.02
        children = [
            _box3d(w, h, t, x=0.0, y=0.0, color=PAD_EDGE_FILL, z_offset=z0, **METAL_GOLD_EDGE),
            _box3d(w * 0.9, h * 0.9, t * 0.7, x=0.0, y=0.0, color=self.color, z_offset=z1, **METAL_GOLD),
            _box3d(w * 0.66, h * 0.66, t * 0.5, x=0.0, y=0.0, color=PAD_CORE_FILL, z_offset=z2, metalness=0.82, roughness=0.16),
        ]
        if self.pad_opening:
            fw = max(w, h) * 0.07
            for bx, by, bw, bh in ((0.0, h * 0.5 - fw * 0.5, w, fw), (0.0, -h * 0.5 + fw * 0.5, w, fw),
                                   (-w * 0.5 + fw * 0.5, 0.0, fw, h), (w * 0.5 - fw * 0.5, 0.0, fw, h)):
                children.append(_box3d(bw, bh, t * 0.9, x=bx, y=by, color=PAD_OPENING_MASK, z_offset=z2, **METAL_PASSIVATION))
        return {"shape": "group", "children": children}


class GSGProbePad(PackagingComponent):
    """Ground-signal-ground RF probe pad group.

    This draws three aligned pads and exposes ports named ``g1``, ``s``, and
    ``g2`` for RF launch diagrams and electro-optic modulator drive layouts.

    Parameters
    ----------
    center : tuple[float, float]
        Center of the three-pad group.
    angle : float
        Rotation angle in degrees.
    pad_width, pad_height : float
        Dimensions of each individual pad. Defaults are square, and ``gap``
        keeps neighbouring pads from touching.
    gap : float
        Clear space between adjacent pad edges.
    port_side : str
        Side where all three ports sit; must be ``left`` or ``right``.
    layer : str | None
        Optional electrical layer name stored on each port.
    color : str
        Pad metal color.
    opacity : float
        Pad opacity used by 2D rendering.
    label : str
        Optional label stored on the component.
    impedance_ohms, bandwidth_ghz, insertion_loss_db : float | None
        RF metadata read by the electrical chain checks (impedance mismatch,
        bandwidth bottleneck). Left out when ``None``.
    """

    component_type = "GSGProbePad"
    schematic_family = "gsg_probe_pad"
    lies_on_table = True       # three separate pads on the die surface: each rests on it, none touches another

    def __init__(
        self,
        center=(0, 0),
        angle: float = 0.0,
        pad_width: float = 12.0,
        pad_height: float = 12.0,
        gap: float = 8.0,
        port_side: str = "left",
        layer: str | None = "M1",
        color: str = GOLD,
        opacity: float = 0.92,
        label: str = "",
        visual_style: str = "publication",
        visual_scale: float = 1.0,
        render_physical: bool = False,
        impedance_ohms: float | None = None,
        bandwidth_ghz: float | None = None,
        insertion_loss_db: float | None = None,
    ):
        if port_side.lower() not in {"left", "right"}:
            raise ValueError("GSGProbePad port_side must be 'left' or 'right'")
        self.impedance_ohms = impedance_ohms
        self.bandwidth_ghz = bandwidth_ghz
        self.insertion_loss_db = insertion_loss_db
        self.pad_width = float(pad_width)
        self.pad_height = float(pad_height)
        self.gap = float(gap)
        self.port_side = port_side.lower()
        self.layer = layer
        self._init_packaging(
            center,
            angle,
            visual_style=visual_style,
            visual_scale=visual_scale,
            render_physical=render_physical,
            color=color,
            opacity=opacity,
            label=label,
        )

    def physical_spec(self) -> PhysicalSpec:
        return PhysicalSpec(
            device_family=self.schematic_family,
            values={
                "pad_width": self.pad_width,
                "pad_height": self.pad_height,
                "gap": self.gap,
                "pitch": self.pitch,
            },
        )

    def _draw(self, key, default=None):
        if key in ("pad_width", "pad_height", "gap"):        # its own size: each port sits on its drawn pad
            return self._physical_value(key, default)
        return super()._draw(key, default)

    @property
    def pitch(self) -> float:
        return self.pad_height + self.gap

    @property
    def total_height(self) -> float:
        return 3.0 * self.pad_height + 2.0 * self.gap

    def physics_metadata(self) -> dict[str, Any]:
        rf = {"impedance_ohms": self.impedance_ohms, "bandwidth_ghz": self.bandwidth_ghz,
              "insertion_loss_db": self.insertion_loss_db}
        return {"component": "gsg_probe_pad", "layer": self.layer, **{k: v for k, v in rf.items() if v is not None}}

    def ports(self) -> dict[str, Port]:
        x = -self.pad_width / 2.0 if self.port_side == "left" else self.pad_width / 2.0
        orientation = 180.0 if self.port_side == "left" else 0.0
        return {
            "g1": Port("g1", Vec3(x, self.pitch, 0.0), orientation_deg=orientation, width=self.pad_height, kind="electrical", layer=self.layer),
            "s": Port("s", Vec3(x, 0.0, 0.0), orientation_deg=orientation, width=self.pad_height, kind="electrical", layer=self.layer),
            "g2": Port("g2", Vec3(x, -self.pitch, 0.0), orientation_deg=orientation, width=self.pad_height, kind="electrical", layer=self.layer),
        }

    def geometry_2d(self) -> dict[str, Any]:
        w = self._draw("pad_width")
        h = self._draw("pad_height")
        pitch = self._draw("pad_height") + self._draw("gap")
        if self.visual_style == "symbolic":
            children: list[dict[str, Any]] = []
            for y in (pitch, 0.0, -pitch):
                children.append(_rect(0.0, y, w, h, fill="none", opacity=1.0, stroke=INK, stroke_width=OUTLINE))
            return {"type": "group", "children": children}
        children = []
        for label, y in (("G", pitch), ("S", 0.0), ("G", -pitch)):
            children += [
                _rect(0.0, y, w, h, fill=PAD_EDGE_FILL, opacity=self.opacity, stroke=PAD_EDGE_FILL, stroke_width=OUTLINE_THIN),
                _rect(0.0, y, w * 0.94, h * 0.94, fill=self.color, opacity=self.opacity, stroke="#7a5a14", stroke_width=HAIRLINE),
                _rect(0.0, y, w * 0.7, h * 0.7, fill=PAD_CORE_FILL, opacity=min(self.opacity, 0.95), stroke=PAD_HIGHLIGHT, stroke_width=HAIRLINE),
            ]
            if self.visual_style == "presentation":
                children.append(_rect(w * 0.28, y, w * 0.16, h * 0.46, fill="#cdd6dd", opacity=0.6, stroke="#9aa6ae", stroke_width=HAIRLINE))
                children.append(_text(label, -w * 0.34, y + h * 0.18, size=h * 0.5, fill=INK, opacity=0.75))
        return {"type": "group", "children": children}

    def geometry_3d(self) -> dict[str, Any]:
        w = self._draw("pad_width")
        h = self._draw("pad_height")
        pitch = self._draw("pad_height") + self._draw("gap")
        t = self._draw_thickness()
        z0, z1 = 0.04, 0.04 + t * 0.6
        children: list[dict[str, Any]] = []
        for y in (pitch, 0.0, -pitch):
            children += [
                _box3d(w, h, t, x=0.0, y=y, color=PAD_EDGE_FILL, z_offset=z0, **METAL_GOLD_EDGE),
                _box3d(w * 0.94, h * 0.94, t * 0.6, x=0.0, y=y, color=self.color, z_offset=z1, **METAL_GOLD),
            ]
            if self.visual_style == "presentation":
                children.append(_box3d(w * 0.16, h * 0.46, t * 0.3, x=w * 0.28, y=y, color="#aeb8bf", z_offset=z1, metalness=0.5, roughness=0.5))
        return {"shape": "group", "children": children}


class MetalRoute(PackagingComponent):
    """Electrical metal route with physical endpoint ports and resistance metadata.

    Use ``MetalRoute`` when a diagram needs an explicit metal trace instead of
    the generic scene router. The path coordinates and ports stay physical;
    schematic rendering only boosts stroke width and metal thickness for
    visibility.

    Parameters
    ----------
    points : Iterable[tuple[float, float] | tuple[float, float, float] | Vec3]
        Ordered route vertices. The first and last points expose ports ``e1``
        and ``e2``.
    center : tuple[float, float]
        Transform center applied to the whole route.
    angle : float
        Rotation angle in degrees.
    width : float
        Physical metal width used by ports and resistance estimate.
    thickness : float
        Physical metal thickness used by ``physical_spec`` and 3D drawing.
    layer : str | None
        Optional metal layer name stored on ports and metadata.
    sheet_resistance_ohm_per_sq : float
        Sheet resistance used for the route resistance estimate.
    color : str
        Route metal color.
    opacity : float
        Route opacity used by 2D rendering.
    label : str
        Optional label stored on the component.
    """

    component_type = "MetalRoute"
    schematic_family = "metal_route"

    def __init__(
        self,
        points=((-20.0, 0.0), (20.0, 0.0)),
        *,
        center=(0, 0),
        angle: float = 0.0,
        width: float = 0.8,
        thickness: float = 0.12,
        layer: str | None = "M1",
        sheet_resistance_ohm_per_sq: float = 0.08,
        color: str = COPPER,
        opacity: float = 0.95,
        label: str = "",
        visual_style: str = "publication",
        visual_scale: float = 1.0,
        render_physical: bool = False,
    ):
        self.points = [_as_vec3(point) for point in points]
        if len(self.points) < 2:
            raise ValueError("MetalRoute requires at least two points")
        self.width = float(width)
        self.thickness = float(thickness)
        self.layer = layer
        self.sheet_resistance_ohm_per_sq = float(sheet_resistance_ohm_per_sq)
        _init_component(self, center, angle, color=color, opacity=opacity, label=label)
        self.visual_scale = max(float(visual_scale), 0.05)
        self.render_physical = bool(render_physical)
        self.visual_style = _style_key(visual_style)

    @property
    def route_length(self) -> float:
        return sum((end_point - start_point).length() for start_point, end_point in zip(self.points, self.points[1:]))

    def anim_behaviors(self) -> list[dict]:
        return [{"key": "drive", "label": "Drive", "options": [
            ["auto", "On (signal animates)"], ["off", "Off (static)"]]}]

    @property
    def resistance_ohms(self) -> float:
        return self.sheet_resistance_ohm_per_sq * self.route_length / max(self.width, 1e-9)

    def physical_spec(self) -> PhysicalSpec:
        return PhysicalSpec(
            device_family=self.schematic_family,
            values={
                "width": self.width,
                "thickness": self.thickness,
                "route_length": self.route_length,
                "sheet_resistance_ohm_per_sq": self.sheet_resistance_ohm_per_sq,
                "resistance_ohms": self.resistance_ohms,
            },
        )

    def _endpoint_angle(self, start_point: Vec3, end_point: Vec3) -> float:
        return math.degrees(math.atan2(end_point.y - start_point.y, end_point.x - start_point.x))

    def ports(self) -> dict[str, Port]:
        start_angle = self._endpoint_angle(self.points[0], self.points[1]) + 180.0
        end_angle = self._endpoint_angle(self.points[-2], self.points[-1])
        return {
            "e1": Port("e1", self.points[0], orientation_deg=start_angle, width=self.width, kind="electrical", layer=self.layer),
            "e2": Port("e2", self.points[-1], orientation_deg=end_angle, width=self.width, kind="electrical", layer=self.layer),
        }

    def geometry_2d(self) -> dict[str, Any]:
        if self.visual_style == "symbolic":
            return _polyline([(point.x, point.y) for point in self.points], stroke=INK, stroke_width=self._draw("width"), opacity=1.0)
        if self.visual_style == "publication":
            return _polyline(
                [(point.x, point.y) for point in self.points],
                stroke=self.color,
                stroke_width=self._draw("width"),
                opacity=self.opacity,
                stroke_dasharray="6 4",
            )
        return _polyline([(point.x, point.y) for point in self.points], stroke=self.color, stroke_width=self._draw("width"), opacity=self.opacity)

    def geometry_3d(self) -> dict[str, Any]:
        draw_width = self._draw("width")
        draw_thickness = self._draw_thickness()
        children: list[dict[str, Any]] = []
        for start_point, end_point in zip(self.points, self.points[1:]):
            segment_dx = end_point.x - start_point.x
            segment_dy = end_point.y - start_point.y
            segment_length = math.hypot(segment_dx, segment_dy)
            if segment_length <= 1e-9:
                continue
            children.append(
                _box3d(
                    segment_length,
                    draw_width,
                    draw_thickness,
                    x=(start_point.x + end_point.x) / 2.0,
                    y=(start_point.y + end_point.y) / 2.0,
                    color=self.color,
                    z_offset=0.04,
                    rotation_y=math.atan2(segment_dy, segment_dx),
                    **METAL_COPPER,
                )
            )
        return {"shape": "group", "children": children}

    def physics_metadata(self) -> dict[str, Any]:
        return {"component": "metal_route", "layer": self.layer, "route_length": self.route_length, "resistance_ohms": self.resistance_ohms}


class HeaterPad(PackagingComponent):
    """Thermo-optic heater stripe with contact pads and electrical ports.

    The component is intentionally primitive: it draws a heater bar plus two
    contact pads and records resistance/tuning metadata so rings, MZIs, and
    phase-shifter sketches can share a reusable thermal control visual.

    Parameters
    ----------
    center : tuple[float, float]
        Heater center in local scene coordinates.
    angle : float
        Rotation angle in degrees.
    heater_length, heater_width : float
        Physical heater stripe dimensions between the contact pads.
    contact_width, contact_height : float
        Physical dimensions of each electrical contact pad.
    layer : str | None
        Optional heater metal layer name stored on ports and metadata.
    sheet_resistance_ohm_per_sq : float
        Sheet resistance used when ``resistance_ohms`` is not provided.
    resistance_ohms : float | None
        Optional explicit heater resistance estimate.
    tuning_efficiency_pm_per_mw : float
        Optional thermal tuning coefficient stored in metadata.
    max_power_mw : float
        Optional maximum safe power placeholder stored in metadata.
    color : str
        Heater stripe color.
    opacity : float
        Heater opacity used by 2D rendering.
    label : str
        Optional label stored on the component.
    """

    component_type = "HeaterPad"
    schematic_family = "heater_pad"

    def __init__(
        self,
        center=(0, 0),
        angle: float = 0.0,
        heater_length: float = 30.0,
        heater_width: float = 1.2,
        contact_width: float = 6.0,
        contact_height: float = 10.0,
        layer: str | None = "HTR",
        sheet_resistance_ohm_per_sq: float = 18.0,
        resistance_ohms: float | None = None,
        tuning_efficiency_pm_per_mw: float = 80.0,
        max_power_mw: float = 35.0,
        color: str = "#b87946",
        opacity: float = 0.94,
        label: str = "",
        visual_style: str = "publication",
        visual_scale: float = 1.0,
        render_physical: bool = False,
    ):
        self.heater_length = float(heater_length)
        self.heater_width = float(heater_width)
        self.contact_width = float(contact_width)
        self.contact_height = float(contact_height)
        self.layer = layer
        self.sheet_resistance_ohm_per_sq = float(sheet_resistance_ohm_per_sq)
        estimated_resistance = self.sheet_resistance_ohm_per_sq * self.heater_length / max(self.heater_width, 1e-9)
        self.resistance_ohms = float(resistance_ohms if resistance_ohms is not None else estimated_resistance)
        self.tuning_efficiency_pm_per_mw = float(tuning_efficiency_pm_per_mw)
        self.max_power_mw = float(max_power_mw)
        self.thickness = 0.12
        self._init_packaging(
            center,
            angle,
            visual_style=visual_style,
            visual_scale=visual_scale,
            render_physical=render_physical,
            color=color,
            opacity=opacity,
            label=label,
        )

    @property
    def total_length(self) -> float:
        return self.heater_length + 2.0 * self.contact_width

    def anim_behaviors(self) -> list[dict]:
        return [{"key": "heater", "label": "Heater", "options": [
            ["auto", "On (warms each loop)"], ["off", "Off"]]}]

    def physical_spec(self) -> PhysicalSpec:
        return PhysicalSpec(
            device_family=self.schematic_family,
            values={
                "heater_length": self.heater_length,
                "heater_width": self.heater_width,
                "contact_width": self.contact_width,
                "contact_height": self.contact_height,
                "sheet_resistance_ohm_per_sq": self.sheet_resistance_ohm_per_sq,
                "resistance_ohms": self.resistance_ohms,
                "tuning_efficiency_pm_per_mw": self.tuning_efficiency_pm_per_mw,
                "max_power_mw": self.max_power_mw,
            },
        )

    def ports(self) -> dict[str, Port]:
        return {
            "e1": Port("e1", Vec3(-self.total_length / 2.0, 0.0, 0.0), orientation_deg=180.0, width=self.contact_height, kind="electrical", layer=self.layer),
            "e2": Port("e2", Vec3(self.total_length / 2.0, 0.0, 0.0), orientation_deg=0.0, width=self.contact_height, kind="electrical", layer=self.layer),
        }

    def _serpentine_points(self, length: float, band: float, n: int) -> list[tuple[float, float]]:
        """Square-wave serpentine path of ``n`` filaments across ``length`` (height ``band``)."""

        pts: list[tuple[float, float]] = []
        step = length / max(n - 1, 1)
        for i in range(n):
            x = -length / 2.0 + i * step
            if i % 2 == 0:
                pts += [(x, -band / 2.0), (x, band / 2.0)]
            else:
                pts += [(x, band / 2.0), (x, -band / 2.0)]
        return pts

    def _serpentine_params(self) -> tuple[float, float, int]:
        heater_length = self._draw("heater_length")
        heater_width = self._draw("heater_width")
        n = min(max(int(heater_length / max(heater_width * 1.6, 1.0)), 4), 14)
        return heater_length, heater_width, n

    def _heater_path(self) -> list[tuple[float, float]]:
        """The filament: a serpentine over 92 % of the stripe, and a lead at each end out to its contact pad."""

        heater_length, heater_width, n = self._serpentine_params()
        serp = self._serpentine_points(heater_length * 0.92, heater_width * 0.78, n)
        return [(-heater_length / 2.0, serp[0][1]), *serp, (heater_length / 2.0, serp[-1][1])]

    def geometry_2d(self) -> dict[str, Any]:
        heater_length = self._draw("heater_length")
        heater_width = self._draw("heater_width")
        contact_width = self._draw("contact_width")
        contact_height = self._draw("contact_height")
        if self.visual_style == "symbolic":
            return {
                "type": "group",
                "children": [
                    _rect(0.0, 0.0, heater_length, heater_width, fill="none", opacity=1.0, stroke=INK, stroke_width=OUTLINE),
                    _rect(-heater_length / 2.0 - contact_width / 2.0, 0.0, contact_width, contact_height, fill="none", opacity=1.0, stroke=INK, stroke_width=OUTLINE_THIN),
                    _rect(heater_length / 2.0 + contact_width / 2.0, 0.0, contact_width, contact_height, fill="none", opacity=1.0, stroke=INK, stroke_width=OUTLINE_THIN),
                ],
            }
        contact_offset = heater_length / 2.0 + contact_width / 2.0
        serp = self._heater_path()
        children = [
            _rect(0.0, 0.0, heater_length, heater_width, fill=self.color, opacity=self.opacity * 0.5, stroke="#7a4a2a", stroke_width=HAIRLINE),
            _polyline(serp, stroke=self.color, stroke_width=max(heater_width * 0.16, 0.18), opacity=self.opacity),
        ]
        if self.visual_style == "presentation":
            children.append(_polyline(serp, stroke=HEATER_HIGHLIGHT, stroke_width=max(heater_width * 0.07, 0.1), opacity=0.72))
        # metallic stepped contact pads
        for cx in (-contact_offset, contact_offset):
            children += [
                _rect(cx, 0.0, contact_width, contact_height, fill=GOLD_DARK, opacity=self.opacity, stroke=GOLD_DARK, stroke_width=0.12),
                _rect(cx, 0.0, contact_width * 0.9, contact_height * 0.9, fill=GOLD, opacity=self.opacity, stroke="#7a5a14", stroke_width=0.12),
                _rect(cx, 0.0, contact_width * 0.58, contact_height * 0.58, fill="#e7c069", opacity=min(self.opacity, 0.95)),
            ]
        return {"type": "group", "children": children}

    def geometry_3d(self) -> dict[str, Any]:
        heater_length = self._draw("heater_length")
        heater_width = self._draw("heater_width")
        contact_width = self._draw("contact_width")
        contact_height = self._draw("contact_height")
        contact_offset = heater_length / 2.0 + contact_width / 2.0
        thickness = self._draw_thickness()
        serp = self._heater_path()
        children: list[dict[str, Any]] = []
        # serpentine TiN heater filaments as connected thin bars (overlapped at corners)
        fil_w = max(heater_width * 0.18, 0.25)
        last = len(serp) - 2
        for k, ((x0, y0), (x1, y1)) in enumerate(zip(serp, serp[1:])):
            seg_dx, seg_dy = x1 - x0, y1 - y0
            seg_len = math.hypot(seg_dx, seg_dy)
            if seg_len <= 1e-9:
                continue
            # a corner overlaps its neighbour; an end stops at the pad edge, so filament and pad share no face
            back, ahead = (fil_w * 0.25 if k > 0 else 0.0), (fil_w * 0.25 if k < last else 0.0)
            shift = (ahead - back) / 2.0 / seg_len
            children.append(_box3d(seg_len + back + ahead, fil_w, thickness, x=(x0 + x1) / 2.0 + seg_dx * shift,
                                   y=(y0 + y1) / 2.0 + seg_dy * shift, color=self.color, z_offset=0.05,
                                   rotation_y=math.atan2(seg_dy, seg_dx), metalness=0.42, roughness=0.4))
        for cx in (-contact_offset, contact_offset):
            children += [
                _box3d(contact_width, contact_height, thickness, x=cx, y=0.0, color=PAD_EDGE_FILL, z_offset=0.05, **METAL_GOLD_EDGE),
                _box3d(contact_width * 0.9, contact_height * 0.9, thickness * 0.7, x=cx, y=0.0, color=GOLD, z_offset=0.05 + thickness * 0.6, **METAL_GOLD),
            ]
        return {"shape": "group", "children": children}

    def physics_metadata(self) -> dict[str, Any]:
        return {
            "component": "heater_pad",
            "layer": self.layer,
            "resistance_ohms": self.resistance_ohms,
            "tuning_efficiency_pm_per_mw": self.tuning_efficiency_pm_per_mw,
            "max_power_mw": self.max_power_mw,
        }




def _material(name: str) -> str:
    from optodraw.gds.palette import material_fill        # the one material table; lazy, as circuit.py reads it

    return material_fill(name)


class FiberArray(Component):
    """Fibre array: a silicon V-groove base under a glass lid, with ``count`` fibres at ``pitch`` leaving its back
    face. The ports ``o1``..``oN`` lie on the polished front face (local +x), which butts a chip edge; ``o1`` is the
    lowest.

    The plan is in pitches (the class constants), so the 1D symbol and the 2D art (``pics/od fiberarray`` in
    ``optodraw/symbols/tikz/od-package.tex``, 0.12 cm per pitch) and the 3D solids keep one shape at any pitch. Sizes
    are in mm: the default pitch is 0.127 (127 µm, a data sheet value); the proportions of the block are schematic.
    """

    component_type = "FiberArray"
    _art_scale_from_ports = True       # the art spans the ports, so each port sits on the drawn front face
    LENGTH = 12.0                      # the block along the fibres; its width is count + 2 pitches
    LID = 0.65                         # the share of the length the lid covers, from the front face
    BASE_HEIGHT = 4.0
    LID_HEIGHT = 3.0
    STUB = 4.0                         # the fibres drawn behind the block
    FIBRE_RADIUS = 0.45                # a 125 µm fibre at a 127 µm pitch, kept clear of its neighbour

    def __init__(self, center=(0, 0), angle: float = 0.0, count: int = 8, pitch: float = 0.127, label: str = "",
                 opacity: float = 1.0):
        if int(count) < 1 or float(pitch) <= 0.0:
            raise ValueError(f"a fibre array needs count >= 1 and pitch > 0, got {count} and {pitch}")
        self.count, self.pitch = int(count), float(pitch)
        _init_component(self, center, angle, color=_material("silicon"), opacity=opacity, label=label)

    def _rows(self) -> list[float]:
        """The y of each fibre, o1 first."""

        return [(i - (self.count - 1) / 2.0) * self.pitch for i in range(self.count)]

    def ports(self) -> dict[str, Port]:
        x = self.LENGTH * self.pitch / 2.0
        return {f"o{i + 1}": Port(f"o{i + 1}", Vec3(x, y, 0.0), orientation_deg=0.0, width=self.pitch, kind="fiber")
                for i, y in enumerate(self._rows())}

    def symbol_1d(self) -> tuple[str, dict[str, Any]]:
        return "fiberarray", {"count": self.count}

    def geometry_2d(self) -> dict[str, Any]:
        from optodraw.core.routing import _route_color

        p = self.pitch
        half_length, half_width, lid = self.LENGTH * p / 2.0, (self.count + 2) * p / 2.0, self.LID * self.LENGTH * p
        fibres = [_line(-half_length - self.STUB * p, y, -half_length, y, stroke=_route_color("fiber"),
                        stroke_width=2.0 * self.FIBRE_RADIUS * p, opacity=self.opacity) for y in self._rows()]
        return {"type": "group", "children": [
            *fibres,
            _rect(0.0, 0.0, 2.0 * half_length, 2.0 * half_width, fill=self.color, opacity=self.opacity,
                  stroke="#6b7a8f", stroke_width=0.08 * p),
            _rect(half_length - lid / 2.0, 0.0, lid, 2.0 * half_width - p, fill=_material("silica"),
                  opacity=self.opacity, stroke="#7fb2cf", stroke_width=0.08 * p),
        ]}

    def geometry_3d(self) -> dict[str, Any]:
        from optodraw.core.routing import _route_color

        p = self.pitch
        length, width, lid = self.LENGTH * p, (self.count + 2) * p, self.LID * self.LENGTH * p
        base_h, lid_h, stub = self.BASE_HEIGHT * p, self.LID_HEIGHT * p, self.STUB * p
        fibre = {"color": _route_color("fiber"), "metalness": 0.05, "roughness": 0.6}
        return {"shape": "group", "children": [
            {"shape": "box", "width": length, "height": base_h, "depth": width, "position": [0.0, base_h / 2.0, 0.0],
             "material": {"color": self.color, "metalness": 0.3, "roughness": 0.4}, "role": "v-groove base"},
            # one pitch narrower than the base, so no side of the lid lies in a side of the base
            {"shape": "box", "width": lid, "height": lid_h, "depth": width - p,
             "position": [(length - lid) / 2.0, base_h + lid_h / 2.0, 0.0], "role": "glass lid",
             "material": {"color": _material("silica"), "metalness": 0.0, "roughness": 0.1, "opacity": 0.6,
                          "transparent": True}},
            # each fibre lies in its groove: its axis on the top of the base
            *({"shape": "cylinder", "radius": self.FIBRE_RADIUS * p, "height": stub, "rotation": [0.0, 0.0, math.pi / 2],
               "position": [-(length + stub) / 2.0, base_h, -y], "material": fibre, "role": "fibre"}
              for y in self._rows()),
        ]}


class SMAConnector(Component):
    """Edge-launch SMA jack at a board edge: the centre pin lies on the board's top trace and carries the port
    ``e1`` at its tip; two ground legs lie on the board beside it; the flange stands at the board edge, then the hex
    and the threaded barrel run outward along local +x.

    The plan is in mm (the class constants, x from the board edge): ``pics/od sma`` (view=top) in
    ``optodraw/symbols/tikz/od-package.tex`` draws the same numbers at 1 cm to 10 mm. The 0.76 mm pin is a data sheet
    size. The axis sits one pin radius over the top of the board PCB draws, so the pin lies on its trace; the body is
    sized to that height, about half a real SMA, whose 6.35 mm thread would reach below the board.
    """

    component_type = "SMAConnector"
    _art_unit = 10.0                   # scene units (mm) per centimetre of the pic
    PIN = (-2.4, 0.0)                  # x from and to; the board edge is x = 0
    PIN_RADIUS = 0.38
    LEGS = (-2.0, 1.6, 0.8, 0.4)       # x from, the distance of each leg from the pin, its width, its thickness
    FLANGE = (0.0, 1.4)
    FLANGE_WIDTH = 4.4
    HEX = (1.4, 2.6)
    HEX_FLATS = 0.9                    # across its flats, as a share of the flange height
    BARREL = (2.6, 5.8)
    BARREL_RADIUS = 0.7                # as a share of the axis height

    def __init__(self, center=(0, 0), angle: float = 0.0, label: str = "", opacity: float = 1.0):
        _init_component(self, center, angle, color=_material("gold"), opacity=opacity, label=label)

    @property
    def axis(self) -> float:
        """The height of the coaxial axis over the table: on the board top, one pin radius up."""

        return BOARD_THICKNESS + self.PIN_RADIUS

    def ports(self) -> dict[str, Port]:
        return {"e1": Port("e1", Vec3(self.PIN[0], 0.0, 0.0), orientation_deg=180.0, width=2.0 * self.PIN_RADIUS,
                           kind="electrical")}

    def symbol_2d(self) -> tuple[str, dict[str, Any]]:
        return "sma", {"view": "top"}            # in 2D the jack seen from above, not the circuit symbol

    def geometry_2d(self) -> dict[str, Any]:
        flats = self.HEX_FLATS * 2.0 * self.axis
        x0, _, width, _ = self.LEGS
        style = {"fill": self.color, "opacity": self.opacity, "stroke": GOLD_DARK, "stroke_width": HAIRLINE}

        def span(x: tuple[float, float], height: float, y: float = 0.0) -> dict[str, Any]:
            return _rect((x[0] + x[1]) / 2.0, y, x[1] - x[0], height, **style)

        return {"type": "group", "children": [
            *(span((x0, 0.0), width, side * self.LEGS[1]) for side in (-1.0, 1.0)),
            span(self.PIN, 2.0 * self.PIN_RADIUS),
            span(self.FLANGE, self.FLANGE_WIDTH),
            span(self.HEX, 2.0 * flats / math.sqrt(3.0)),             # seen from above: across its corners
            span(self.BARREL, 2.0 * self.BARREL_RADIUS * self.axis),
        ]}

    def geometry_3d(self) -> dict[str, Any]:
        from optodraw.components.electronics.circuit import _metal

        a, gold = self.axis, _metal("gold", 0.6, 0.35)
        along_x = [0.0, 0.0, math.pi / 2]
        flats = self.HEX_FLATS * 2.0 * a
        corner = flats / math.sqrt(3.0)
        x0, offset, width, thick = self.LEGS
        return {"shape": "group", "post_at": [sum(self.FLANGE) / 2.0, 0.0, 0.0], "children": [
            {"shape": "box", "width": self.FLANGE[1] - self.FLANGE[0], "height": 2.0 * a, "depth": self.FLANGE_WIDTH,
             "position": [sum(self.FLANGE) / 2.0, a, 0.0], "material": gold, "role": "flange"},
            *({"shape": "box", "width": -x0, "height": thick, "depth": width,
               "position": [x0 / 2.0, BOARD_THICKNESS + thick / 2.0, side * offset], "material": gold,
               "role": "ground leg"} for side in (-1.0, 1.0)),
            {"shape": "cylinder", "radius": self.PIN_RADIUS, "height": self.PIN[1] - self.PIN[0], "rotation": along_x,
             "position": [sum(self.PIN) / 2.0, a, 0.0], "material": _metal("gold", 0.7, 0.3), "role": "centre pin"},
            # a hexagon with flats up and down, extruded along +x from the flange
            {"shape": "extruded_polygon", "height": self.HEX[1] - self.HEX[0], "rotation": [0.0, 0.0, -math.pi / 2],
             "points": [(flats / 2.0, corner / 2.0), (0.0, corner), (-flats / 2.0, corner / 2.0),
                        (-flats / 2.0, -corner / 2.0), (0.0, -corner), (flats / 2.0, -corner / 2.0)],
             "position": [self.HEX[0], a, 0.0], "material": gold, "role": "hex"},
            {"shape": "cylinder", "radius": self.BARREL_RADIUS * a, "height": self.BARREL[1] - self.BARREL[0],
             "rotation": along_x, "position": [sum(self.BARREL) / 2.0, a, 0.0], "material": gold, "role": "barrel"},
        ]}
