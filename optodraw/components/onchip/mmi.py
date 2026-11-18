"""Multimode interferometer components."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from optodraw.core.ports import Port
from optodraw.core.schematic_geometry import PhysicalSpec

from optodraw.components.onchip.base import ChipComponent, _generic_pdk_defaults
from optodraw.components.onchip.geometry import (
    _chip_box,
    _chip_line,
    _mmi_children,
    _mmi_port_offsets,
    _mmi_ports,
    _mmi_slab_children,
)

class _MMIBase(ChipComponent):
    """Shared in-file layout builder for the MMI family."""

    schematic_family = "mmi"
    input_port_count = 1
    output_port_count = 1
    input_gap_attr: str | None = None
    output_gap_attr: str | None = None

    def _init_mmi(
        self,
        *,
        center,
        angle,
        body_length: float,
        body_width: float,
        taper_length: float,
        waveguide_width: float | None,
        width_taper: float,
        gap_name: str | None = None,
        gap_value: float | None = None,
        **kwargs,
    ) -> None:
        strip = _generic_pdk_defaults()["strip"]
        self._init_chip(center=center, angle=angle, **kwargs)
        self.body_length = float(body_length)
        self.body_width = float(body_width)
        self.taper_length = float(taper_length)
        self.waveguide_width = float(strip["width"] if waveguide_width is None else waveguide_width)
        self.width_taper = float(width_taper)
        if gap_name is not None:
            setattr(self, gap_name, 0.0 if gap_value is None else float(gap_value))

    @property
    def total_length(self) -> float:
        return self.body_length + 2.0 * self.taper_length

    def physical_spec(self) -> PhysicalSpec:
        values: dict[str, float | int | bool] = {
            "body_length": self.body_length,
            "body_width": self.body_width,
            "taper_length": self.taper_length,
            "waveguide_width": self.waveguide_width,
            "width_taper": self.width_taper,
            "thickness": self.chip_thickness,
        }
        if self.output_gap_attr:
            values[self.output_gap_attr] = float(getattr(self, self.output_gap_attr))
        if self.input_gap_attr and self.input_gap_attr != self.output_gap_attr:
            values[self.input_gap_attr] = float(getattr(self, self.input_gap_attr))
        return PhysicalSpec(device_family=self.schematic_family, values=values)

    def _effective_body_width(self) -> float:
        """Multimode-region width, widened so all ports fan out without overlapping.

        The schematic ``body_width`` is a floor; for higher port counts the body
        grows to fit ``port_count`` fattened legs plus the taper mouths.
        """

        base = self._draw("body_width")
        if self.render_physical:
            return base
        wg = self._draw("waveguide_width", self.waveguide_width)
        taper = self._draw("width_taper", self.width_taper)
        ports = max(self.input_port_count, self.output_port_count)
        needed = ports * wg * 1.7 + taper
        return max(base, needed)

    def _draw_geometry(self) -> tuple[float, float, float, float, float]:
        return (
            self._draw("body_length"),
            self._effective_body_width(),
            self._draw("taper_length"),
            self._draw("waveguide_width", self.waveguide_width),
            self._draw("width_taper", self.width_taper),
        )

    def _mmi_offsets(self, port_count: int, gap_attr: str | None) -> list[float]:
        # Fan ports evenly across the (drawn) multimode body so they stay separated
        # and inside the body regardless of port count — the physical gap_attr stays
        # the routing/metadata truth, but the schematic legs need to be legible.
        if port_count <= 1:
            return [0.0]
        if self.render_physical and gap_attr is not None:
            return _mmi_port_offsets(port_count, float(getattr(self, gap_attr)))
        spread = self._effective_body_width() * 0.66
        return _mmi_port_offsets(port_count, spread / (port_count - 1))

    def _port_offsets(self) -> tuple[list[float], list[float]]:
        return (
            self._mmi_offsets(self.input_port_count, self.input_gap_attr),
            self._mmi_offsets(self.output_port_count, self.output_gap_attr),
        )

    def ports(self) -> dict[str, Port]:
        # Ports sit on the DRAWN taper tips (body + tapers), so routes connect at the
        # visible waveguide ends. ``_draw`` returns physical dims in render_physical
        # mode, so GDS/physical export keeps true positions.
        input_offsets, output_offsets = self._port_offsets()
        drawn_total = self._draw("body_length") + 2.0 * self._draw("taper_length")
        return _mmi_ports(drawn_total, input_offsets, output_offsets, self._draw("waveguide_width", self.waveguide_width))

    def _symbolic_2d(self) -> dict[str, Any]:
        input_offsets, output_offsets = self._port_offsets()
        body_length, body_width, taper_length, _, _ = self._draw_geometry()
        half_body = body_length / 2.0
        half_total = half_body + taper_length
        children = [
            _chip_box(0.0, 0.0, body_length, body_width, "none", 1.0, stroke="#111111", stroke_width=0.8),
        ]
        for y in input_offsets:
            children.append(_chip_line(-half_total, y, -half_body, y, stroke="#111111", stroke_width=0.8, opacity=1.0))
        for y in output_offsets:
            children.append(_chip_line(half_body, y, half_total, y, stroke="#111111", stroke_width=0.8, opacity=1.0))
        return {"type": "group", "children": children}

    def geometry_2d(self) -> dict[str, Any]:
        if self.visual_style == "symbolic":
            return self._symbolic_2d()
        input_offsets, output_offsets = self._port_offsets()
        body_length, body_width, taper_length, waveguide_width, width_taper = self._draw_geometry()
        return {
            "type": "group",
            "children": _mmi_children(
                body_length,
                body_width,
                taper_length,
                waveguide_width,
                width_taper,
                input_offsets,
                output_offsets,
                color=self.color,
                opacity=self.opacity,
            ),
        }

    def optical_paths(self, in_port: str) -> list[dict[str, Any]]:
        """Animation paths on the drawn geometry: the input taper, a fan across the body, the output taper.

        The light enters the body at its face, crosses it in a straight line and leaves at the face of
        each port on the far side. Every point between the faces lies inside the body outline, which each
        path carries as its multimode region. The power splits equally over the far ports."""

        ports = self.ports()
        if in_port not in ports:
            return []
        body_length, body_width, _taper, _wg, _wt = self._draw_geometry()
        half_body, half_width = body_length / 2.0, body_width / 2.0
        outline = [[-half_body, -half_width], [half_body, -half_width], [half_body, half_width], [-half_body, half_width]]
        side = -1.0 if ports[in_port].center.x < 0.0 else 1.0
        start = ports[in_port].center
        targets = [name for name, port in ports.items() if (port.center.x < 0.0) != (side < 0.0)]
        # This weighting changes only the "power" key, which the old 2D compiler reads. The engine never does.
        override = (getattr(self, "anim_params", None) or {}).get("transmissions")
        weights = {name: float(override.get(name, 0.0)) for name in targets} if isinstance(override, dict) else {}
        share = {name: weights[name] / sum(weights.values()) for name in targets} if sum(weights.values()) > 0 else {
            name: 1.0 / len(targets) for name in targets}
        return [{"port": name, "power": share[name], "region": {"kind": "mmi", "outline": outline},
                 "pts": [[start.x, start.y], [side * half_body, start.y], [-side * half_body, ports[name].center.y],
                         [ports[name].center.x, ports[name].center.y]]}
                for name in targets]

    def geometry_3d(self) -> dict[str, Any]:
        input_offsets, output_offsets = self._port_offsets()
        body_length, body_width, taper_length, waveguide_width, width_taper = self._draw_geometry()
        return self._on_the_stack(_mmi_slab_children(
                body_length,
                body_width,
                taper_length,
                waveguide_width,
                width_taper,
                input_offsets,
                output_offsets,
                self._draw_thickness(),
                **self._core(),
            ))

    def physics_metadata(self) -> dict[str, Any]:
        total_ports = self.input_port_count + self.output_port_count
        split_ratio = 1.0 / max(self.output_port_count, 1) if self.input_port_count <= 1 else 0.5
        return {
            "domain": "on_chip",
            "component": "mmi",
            "mmi_type": self.component_type,
            "split_ratio": split_ratio,
            "input_port_count": self.input_port_count,
            "output_port_count": self.output_port_count,
            "port_count": total_ports,
        }


@dataclass
class MMI1x2(_MMIBase):
    component_type = "MMI1x2"
    input_port_count = 1
    output_port_count = 2
    output_gap_attr = "output_gap"
    body_length: float = 5.5
    body_width: float = 2.5
    taper_length: float = 10.0
    waveguide_width: float = 0.5
    width_taper: float = 1.0
    output_gap: float = 1.25

    def __init__(
        self,
        center=(0, 0),
        angle=0,
        body_length: float | None = None,
        body_width: float | None = None,
        taper_length: float | None = None,
        waveguide_width: float | None = None,
        width_taper: float | None = None,
        output_gap: float | None = None,
        **kwargs,
    ):
        defaults = _generic_pdk_defaults()
        mmi = defaults["mmi"]
        default_gap = float(mmi["width_taper"] + mmi["gap_mmi"])
        self._init_mmi(
            center=center,
            angle=angle,
            body_length=mmi["length_mmi"] if body_length is None else body_length,
            body_width=mmi["width_mmi"] if body_width is None else body_width,
            taper_length=mmi["length_taper"] if taper_length is None else taper_length,
            waveguide_width=waveguide_width,
            width_taper=mmi["width_taper"] if width_taper is None else width_taper,
            gap_name="output_gap",
            gap_value=default_gap if output_gap is None else output_gap,
            **kwargs,
        )

@dataclass
class MMI2x2(_MMIBase):
    component_type = "MMI2x2"
    input_port_count = 2
    output_port_count = 2
    input_gap_attr = "port_gap"
    output_gap_attr = "port_gap"
    body_length: float = 5.5
    body_width: float = 2.5
    taper_length: float = 10.0
    waveguide_width: float = 0.5
    width_taper: float = 1.0
    port_gap: float = 1.25

    def __init__(
        self,
        center=(0, 0),
        angle=0,
        body_length: float | None = None,
        body_width: float | None = None,
        taper_length: float | None = None,
        waveguide_width: float | None = None,
        width_taper: float | None = None,
        port_gap: float | None = None,
        **kwargs,
    ):
        defaults = _generic_pdk_defaults()
        mmi = defaults["mmi"]
        default_gap = float(mmi["width_taper"] + mmi["gap_mmi"])
        self._init_mmi(
            center=center,
            angle=angle,
            body_length=mmi["length_mmi"] if body_length is None else body_length,
            body_width=mmi["width_mmi"] if body_width is None else body_width,
            taper_length=mmi["length_taper"] if taper_length is None else taper_length,
            waveguide_width=waveguide_width,
            width_taper=mmi["width_taper"] if width_taper is None else width_taper,
            gap_name="port_gap",
            gap_value=default_gap if port_gap is None else port_gap,
            **kwargs,
        )


@dataclass
class MMI1x3(_MMIBase):
    component_type = "MMI1x3"
    input_port_count = 1
    output_port_count = 3
    output_gap_attr = "output_gap"
    body_length: float = 7.8
    body_width: float = 4.4
    taper_length: float = 12.0
    waveguide_width: float = 0.5
    width_taper: float = 1.1
    output_gap: float = 1.55

    def __init__(
        self,
        center=(0, 0),
        angle=0,
        body_length: float = 7.8,
        body_width: float = 4.4,
        taper_length: float = 12.0,
        waveguide_width: float | None = None,
        width_taper: float = 1.1,
        output_gap: float = 1.55,
        **kwargs,
    ):
        self._init_mmi(
            center=center,
            angle=angle,
            body_length=body_length,
            body_width=body_width,
            taper_length=taper_length,
            waveguide_width=waveguide_width,
            width_taper=width_taper,
            gap_name="output_gap",
            gap_value=output_gap,
            **kwargs,
        )


@dataclass
class MMI1x4(_MMIBase):
    component_type = "MMI1x4"
    input_port_count = 1
    output_port_count = 4
    output_gap_attr = "output_gap"
    body_length: float = 9.6
    body_width: float = 6.0
    taper_length: float = 12.0
    waveguide_width: float = 0.5
    width_taper: float = 1.15
    output_gap: float = 1.45

    def __init__(
        self,
        center=(0, 0),
        angle=0,
        body_length: float = 9.6,
        body_width: float = 6.0,
        taper_length: float = 12.0,
        waveguide_width: float | None = None,
        width_taper: float = 1.15,
        output_gap: float = 1.45,
        **kwargs,
    ):
        self._init_mmi(
            center=center,
            angle=angle,
            body_length=body_length,
            body_width=body_width,
            taper_length=taper_length,
            waveguide_width=waveguide_width,
            width_taper=width_taper,
            gap_name="output_gap",
            gap_value=output_gap,
            **kwargs,
        )


@dataclass
class MMI2x2PowerSplitter(_MMIBase):
    component_type = "MMI2x2PowerSplitter"
    input_port_count = 2
    output_port_count = 2
    input_gap_attr = "port_gap"
    output_gap_attr = "port_gap"
    body_length: float = 8.6
    body_width: float = 4.8
    taper_length: float = 12.0
    waveguide_width: float = 0.5
    width_taper: float = 1.2
    port_gap: float = 1.7

    def __init__(
        self,
        center=(0, 0),
        angle=0,
        body_length: float = 8.6,
        body_width: float = 4.8,
        taper_length: float = 12.0,
        waveguide_width: float | None = None,
        width_taper: float = 1.2,
        port_gap: float = 1.7,
        **kwargs,
    ):
        self._init_mmi(
            center=center,
            angle=angle,
            body_length=body_length,
            body_width=body_width,
            taper_length=taper_length,
            waveguide_width=waveguide_width,
            width_taper=width_taper,
            gap_name="port_gap",
            gap_value=port_gap,
            **kwargs,
        )
