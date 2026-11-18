"""On-chip I/O and support components (detectors, lasers, amplifiers, drivers)."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from optodraw.core.ports import Port
from optodraw.core.schematic_geometry import PhysicalSpec
from optodraw.core.transform import Vec3

from optodraw.components.onchip.base import ChipComponent, _generic_pdk_defaults, SILICON_EDGE
from optodraw.components.onchip.geometry import (
    INP,
    INP_EDGE,
    MQW,
    MQW_EDGE,
    TIN,
    TIN_EDGE,
    CHARGE,
    CHARGE_EDGE,
    GERMANIUM,
    GERMANIUM_EDGE,
    GOLD,
    GOLD_EDGE,
    N_DOPED,
    N_EDGE,
    P_DOPED,
    P_EDGE,
    _contact_children,
    _pad_children,
    _chip_box,
    _chip_circle,
    _chip_path_slab,
    _chip_line,
    _chip_polygon,
    _chip_polyline,
    _chip_segment_polygon,
    _chip_process_3d,
    _chip_slab,
    _polyline_outline,
    _segment_outline,
)

def _ge_cell_2d(x0: float, x1: float, taper_length: float, width: float, waveguide_width: float, y: float,
                opacity: float, color: str, *, multiplication: float = 0.0, p_top: bool = True) -> list[dict[str, Any]]:
    """One Ge-on-Si detector from x0 to x1 on the line y.

    A silicon taper, the doped silicon region (p+ and n+ strips along its edges),
    an optional charge layer (avalanche diode), the Ge mesa, gold contacts with vias.
    """

    taper_end = x0 + taper_length
    region = x1 - taper_end
    centre, h = taper_end + region / 2.0, width               # the region is the drawn width: it clears the pads
    top, bottom = ((P_DOPED, P_EDGE), (N_DOPED, N_EDGE)) if p_top else ((N_DOPED, N_EDGE), (P_DOPED, P_EDGE))
    children = [
        _chip_segment_polygon((x0, y), (taper_end, y), waveguide_width, h * 0.5, fill=color, opacity=opacity,
                              stroke=SILICON_EDGE, stroke_width=0.08),
        _chip_box(centre, y, region, h, color, opacity * 0.4, stroke=SILICON_EDGE, stroke_width=0.06),
        _chip_box(centre, y + h * 0.36, region * 0.94, h * 0.24, top[0], opacity, stroke=top[1], stroke_width=0.05, layer="implant"),
        _chip_box(centre, y - h * 0.36, region * 0.94, h * 0.24, bottom[0], opacity, stroke=bottom[1], stroke_width=0.05, layer="implant"),
    ]
    ge_start = taper_end + multiplication
    if multiplication > 0.0:
        children.append(_chip_box(taper_end + multiplication / 2.0, y, multiplication * 0.9, h * 0.4, CHARGE, opacity,
                                  stroke=CHARGE_EDGE, stroke_width=0.05, layer="charge"))
    children.append(_chip_box(ge_start + (x1 - ge_start) / 2.0, y, (x1 - ge_start) * 0.9, h * 0.4, GERMANIUM, opacity,
                              stroke=GERMANIUM_EDGE, stroke_width=0.06, layer="germanium"))
    for sign in (1.0, -1.0):
        children += _contact_children(centre, y + sign * h * 0.36, region * 0.84, h * 0.1, opacity)
    return children


def _lead(x: float, y0: float, y1: float, width: float, opacity: float) -> dict[str, Any]:
    """A vertical gold lead from a contact strip to its pad."""

    return _chip_box(x, (y0 + y1) / 2.0, width, abs(y1 - y0), GOLD, opacity, stroke=GOLD_EDGE, stroke_width=0.05, layer="metal")


def _absorber_points(x0: float, x1: float, taper_length: float, y: float) -> list[list[float]]:
    """The light in a Ge detector from its input face: along the silicon taper, to the middle of the Ge mesa."""

    taper_end = x0 + taper_length
    return [[x0, y], [taper_end, y], [(taper_end + x1) / 2.0, y]]


@dataclass
class OnChipPhotodetector(ChipComponent):
    """Waveguide Ge-on-Si photodetector.

    At the default ``angle=0`` the optical input ``o1`` sits on the west face
    and points at 180°. A waveguide arriving from the left meets that port
    head-on. ``angle=180`` is the grating-coupler input convention; on a
    detector it puts ``o1`` on the east face and the route loops around the
    body. Leave the default unless the detector truly faces the other way.
    """

    component_type = "OnChipPhotodetector"
    schematic_family = "photodetector"
    length: float = 40.0
    width: float = 4.0
    taper_length: float = 20.0
    pad_width: float = 10.0
    pad_length: float = 20.0
    waveguide_width: float = 0.5
    contact_finger_count: int = 3
    contact_finger_width: float = 0.45

    def __init__(
        self,
        center=(0, 0),
        angle=0,
        length: float | None = None,
        width=4.0,
        taper_length: float | None = None,
        pad_width: float | None = None,
        pad_length: float | None = None,
        waveguide_width: float | None = None,
        contact_finger_count: int = 3,
        contact_finger_width: float | None = None,
        responsivity_a_per_w: float | None = None,
        dark_current_a: float | None = None,
        bandwidth_hz: float | None = None,
        **kwargs,
    ):
        # the datasheet numbers for the signal chain; None is the chain's model default
        self.responsivity_a_per_w, self.dark_current_a = responsivity_a_per_w, dark_current_a
        self.bandwidth_hz = bandwidth_hz
        defaults = _generic_pdk_defaults()
        detector = defaults["detector"]
        strip = defaults["strip"]
        self.length = float(detector["absorber_length"] if length is None else length)
        self.width = width
        self.taper_length = float(detector["taper_length"] if taper_length is None else taper_length)
        self.pad_width = float(detector["pad_width"] if pad_width is None else pad_width)
        self.pad_length = float(detector["pad_length"] if pad_length is None else pad_length)
        self.waveguide_width = float(strip["width"] if waveguide_width is None else waveguide_width)
        self.contact_finger_count = max(1, contact_finger_count)
        self.contact_finger_width = max(contact_finger_width if contact_finger_width is not None else self.width * 0.1, 0.35)
        self._init_chip(center=center, angle=angle, **kwargs)

    @property
    def total_length(self) -> float:
        return self.length + self.taper_length

    def physical_spec(self) -> PhysicalSpec:
        return PhysicalSpec(
            device_family=self.schematic_family,
            values={
                "length": self.length,
                "width": self.width,
                "taper_length": self.taper_length,
                "pad_width": self.pad_width,
                "pad_length": self.pad_length,
                "waveguide_width": self.waveguide_width,
                "contact_finger_width": self.contact_finger_width,
                "thickness": self.chip_thickness,
            },
        )

    def ports(self) -> dict[str, Port]:
        length = self._draw("length", self.length)
        taper_length = self._draw("taper_length", self.taper_length)
        pad_width = self._draw("pad_width", self.pad_width)
        half = (length + taper_length) / 2.0
        pad_x = -taper_length / 2.0 + length * 0.7
        return {
            "o1": Port("o1", Vec3(-half, 0, 0), orientation_deg=180, width=self._draw("waveguide_width", self.waveguide_width)),
            "e1": Port("e1", Vec3(pad_x, pad_width * 0.75, 0), orientation_deg=90, width=pad_width, kind="electrical"),
            "e2": Port("e2", Vec3(pad_x, -pad_width * 0.75, 0), orientation_deg=270, width=pad_width, kind="electrical"),
        }

    def optical_paths(self, in_port: str) -> list[dict[str, Any]]:
        """From the input face along the taper into the drawn Ge mesa, where the light ends (internal port ``_absorb_o1``)."""

        if in_port != "o1":
            return []
        half = (self._draw("length", self.length) + self._draw("taper_length", self.taper_length)) / 2.0
        return [{"port": "_absorb_o1", "pts": _absorber_points(-half, half, self._draw("taper_length", self.taper_length), 0.0)}]

    def geometry_2d(self) -> dict[str, Any]:
        length = self._draw("length", self.length)
        width = self._draw("width", self.width)
        taper_length = self._draw("taper_length", self.taper_length)
        pad_width = self._draw("pad_width", self.pad_width)
        pad_length = self._draw("pad_length", self.pad_length)
        waveguide_width = self._draw("waveguide_width", self.waveguide_width)
        half = (length + taper_length) / 2.0
        pad_x = -taper_length / 2.0 + length * 0.7
        children = _ge_cell_2d(-half, half, taper_length, width, waveguide_width, 0.0, self.opacity, self.color)
        contact, pad_y = width * 0.36, pad_width * 0.75
        for sign in (1.0, -1.0):
            children.append(_lead(pad_x, sign * contact, sign * (pad_y - pad_width / 2.0), pad_length * 0.16, self.opacity))
            children += _pad_children(pad_x, sign * pad_y, pad_length, pad_width, self.opacity)
        return {"type": "group", "children": children}

    def geometry_3d(self) -> dict[str, Any]:
        return self._on_the_stack(_chip_process_3d(
            OnChipPhotodetector.geometry_2d(self),
            self._draw_thickness(),
            self._draw_layer_stack(),
            core=self._core(),
            doped_preset=self._draw_material_preset(),
            opacity=self.opacity,
            schematic=not self.render_physical,
        ))

    def physics_metadata(self) -> dict[str, Any]:
        return {
            "domain": "on_chip",
            "component": "on_chip_photodetector",
            "length": self.length,
            "responsivity_a_per_w": 0.8,
            "bandwidth_ghz": None,
        }


@dataclass
class OnChipBalancedPhotodetector(ChipComponent):
    """Two waveguide-fed photodetectors wired in series at a balanced node.

    Built from two ``OnChipPhotodetector`` absorbers (one per optical input)
    whose inner contacts meet at a shared node; the difference photocurrent
    leaves on a single electrical output — the on-chip analogue of the
    free-space balanced photodetector.
    """

    component_type = "OnChipBalancedPhotodetector"
    schematic_family = "photodetector"
    detector_gap: float = 16.0

    def __init__(self, center=(0, 0), angle=0, detector_gap: float = 16.0, **kwargs):
        self.detector_gap = float(detector_gap)
        self._pd = OnChipPhotodetector()
        self._init_chip(center=center, angle=angle, **kwargs)
        self._pd.render_physical = self.render_physical
        self._pd.visual_scale = self.visual_scale
        self._pd.width_exaggeration = self.width_exaggeration
        self._pd.length_exaggeration = self.length_exaggeration
        self._pd.z_exaggeration = self.z_exaggeration

    @property
    def total_length(self) -> float:
        return self._pd.total_length

    def _node_x(self) -> float:
        absorber_center = -self._pd.taper_length / 2.0 + self._pd.length / 2.0
        return absorber_center + self._pd.length * 0.2

    def physical_spec(self) -> PhysicalSpec:
        return PhysicalSpec(
            device_family=self.schematic_family,
            values={
                "length": self._pd.length,
                "detector_gap": self.detector_gap,
                "taper_length": self._pd.taper_length,
                "thickness": self.chip_thickness,
            },
        )

    def ports(self) -> dict[str, Port]:
        pd = self._pd
        length = pd._draw("length", pd.length)
        width = pd._draw("width", pd.width)
        taper_length = pd._draw("taper_length", pd.taper_length)
        pw = pd._draw("pad_width", pd.pad_width)
        pad_length = pd._draw("pad_length", pd.pad_length)
        half = (length + taper_length) / 2.0
        g = self.detector_gap / 2.0
        pad_x = -taper_length / 2.0 + length * 0.7
        outer_pad_offset = max(width / 2.0 + pw / 2.0 + 1.0, pw * 0.75)
        return {
            "o1": Port("o1", Vec3(-half, g, 0), orientation_deg=180, width=pd._draw("waveguide_width", pd.waveguide_width)),
            "o2": Port("o2", Vec3(-half, -g, 0), orientation_deg=180, width=pd._draw("waveguide_width", pd.waveguide_width)),
            "out": Port("out", Vec3(pad_x + pad_length / 2.0, 0, 0), orientation_deg=0, width=pw, kind="electrical"),
            "e1": Port("e1", Vec3(pad_x, g + outer_pad_offset, 0), orientation_deg=90, width=pw, kind="electrical"),
            "e2": Port("e2", Vec3(pad_x, -(g + outer_pad_offset), 0), orientation_deg=270, width=pw, kind="electrical"),
        }

    def optical_paths(self, in_port: str) -> list[dict[str, Any]]:
        """From each input face along its taper into its own Ge mesa, where the light ends (``_absorb_o1``, ``_absorb_o2``)."""

        if in_port not in ("o1", "o2"):
            return []
        pd = self._pd
        taper_length = pd._draw("taper_length", pd.taper_length)
        half = (pd._draw("length", pd.length) + taper_length) / 2.0
        y = self.detector_gap / 2.0 * (1.0 if in_port == "o1" else -1.0)
        return [{"port": f"_absorb_{in_port}", "pts": _absorber_points(-half, half, taper_length, y)}]

    def geometry_2d(self) -> dict[str, Any]:
        """Two Ge detectors in series: e1, top diode, the shared node (out), bottom diode, e2.

        Both diodes have n+ on top, so the node joins the top diode's p+ to the bottom
        diode's n+; leads run beside the Ge, never over it.
        """

        pd = self._pd
        length = pd._draw("length", pd.length)
        width = pd._draw("width", pd.width)
        taper_length = pd._draw("taper_length", pd.taper_length)
        pad_width = pd._draw("pad_width", pd.pad_width)
        pad_length = pd._draw("pad_length", pd.pad_length)
        waveguide_width = pd._draw("waveguide_width", pd.waveguide_width)
        half = (length + taper_length) / 2.0
        pad_x = -taper_length / 2.0 + length * 0.7
        g = self.detector_gap / 2.0
        outer = max(width / 2.0 + pad_width / 2.0 + 1.0, pad_width * 0.75)
        node = max(1.5, min(pad_width, (2.0 * g - width) * 0.75))
        contact, lead_w = width * 0.36, pad_length * 0.16
        children: list[dict[str, Any]] = []
        for y in (g, -g):
            children += _ge_cell_2d(-half, half, taper_length, width, waveguide_width, y, self.opacity, self.color, p_top=False)
        children += [
            _lead(pad_x, g + contact, g + outer - pad_width / 2.0, lead_w, self.opacity),      # top n+ to e1
            _lead(pad_x, g - contact, node / 2.0, lead_w, self.opacity),                       # top p+ to the node
            _lead(pad_x, -g + contact, -node / 2.0, lead_w, self.opacity),                     # bottom n+ to the node
            _lead(pad_x, -g - contact, -(g + outer - pad_width / 2.0), lead_w, self.opacity),  # bottom p+ to e2
        ]
        children += _pad_children(pad_x, g + outer, pad_length, pad_width, self.opacity)
        children += _pad_children(pad_x, -(g + outer), pad_length, pad_width, self.opacity)
        children += _pad_children(pad_x, 0.0, pad_length, node, self.opacity)
        return {"type": "group", "children": children}

    def geometry_3d(self) -> dict[str, Any]:
        return self._on_the_stack(_chip_process_3d(
            OnChipBalancedPhotodetector.geometry_2d(self),
            self._draw_thickness(),
            self._draw_layer_stack(),
            core=self._core(),
            doped_preset=self._draw_material_preset(),
            opacity=self.opacity,
            schematic=not self.render_physical,
        ))

    def physics_metadata(self) -> dict[str, Any]:
        return {
            "domain": "on_chip",
            "component": "on_chip_balanced_photodetector",
            "detector_gap": self.detector_gap,
            "responsivity_a_per_w": 0.8,
        }


def _gain_2d(x0: float, x1: float, mesa_half: float, si_half: float, ridge: float, opacity: float) -> list[dict[str, Any]]:
    """The III-V gain mesa on the silicon guide: tapered at both ends (the mode moves up and back down), MQW in it."""

    taper = (x1 - x0) * 0.14
    mesa = [(x0, si_half), (x0 + taper, mesa_half), (x1 - taper, mesa_half), (x1, si_half),
            (x1, -si_half), (x1 - taper, -mesa_half), (x0 + taper, -mesa_half), (x0, -si_half)]
    return [_chip_polygon(mesa, fill=INP, opacity=opacity, stroke=INP_EDGE, stroke_width=0.08, layer="mesa"),
            _chip_box((x0 + x1) / 2.0, 0.0, (x1 - x0 - 2.0 * taper) * 0.96, ridge * 0.5, MQW, opacity, stroke=MQW_EDGE, stroke_width=0.06, layer="active")]


def _bragg_teeth(x0: float, x1: float, count: int, si_half: float, height: float, color: str, opacity: float) -> list[dict[str, Any]]:
    """A Bragg mirror: teeth on both sides of the silicon guide."""

    step = (x1 - x0) / max(count, 1)
    return [_chip_box(x0 + step * (i + 0.5), sign * (si_half + height / 2.0), step * 0.45, height, color, opacity,
                      stroke=SILICON_EDGE, stroke_width=0.05)
            for i in range(max(count, 1)) for sign in (1.0, -1.0)]


@dataclass
class OnChipLaser(ChipComponent):
    component_type = "OnChipLaser"
    schematic_family = "laser"
    cavity_length: float = 180.0
    ridge_width: float = 2.5
    output_taper_length: float = 22.0
    grating_period: float = 0.24
    grating_count: int = 36
    waveguide_width: float = 0.5
    pad_length: float = 26.0
    pad_width: float = 12.0
    wavelength_nm: float = 1550.0

    def __init__(self, center=(0, 0), angle=0, cavity_length=180.0, ridge_width=2.5, output_taper_length=22.0, grating_period=0.24, grating_count=36, waveguide_width: float | None = None, pad_length=26.0, pad_width=12.0, wavelength_nm: float = 1550.0,
                 power_mw: float | None = None, threshold_a: float | None = None,
                 slope_w_per_a: float | None = None, **kwargs):
        strip = _generic_pdk_defaults()["strip"]
        self.wavelength_nm = float(wavelength_nm)          # what it emits: the animation and the spectrum read it
        # the optical power when nothing drives e1 (None: 1 mW); threshold and slope (W/A) when a driver does
        self.power_mw, self.threshold_a, self.slope_w_per_a = power_mw, threshold_a, slope_w_per_a
        self.cavity_length = cavity_length
        self.ridge_width = ridge_width
        self.output_taper_length = output_taper_length
        self.grating_period = grating_period
        self.grating_count = grating_count
        self.waveguide_width = float(strip["width"] if waveguide_width is None else waveguide_width)
        self.pad_length = pad_length
        self.pad_width = pad_width
        self._init_chip(center=center, angle=angle, **kwargs)

    @property
    def total_length(self) -> float:
        return self.cavity_length + self.output_taper_length

    def anim_behaviors(self) -> list[dict]:
        return [{"key": "emission", "label": "Emission", "options": [
            ["auto", "CW (continuous wave)"], ["pulsed", "Pulsed (single packet)"],
            ["off", "Off (dark)"]]}]

    @property
    def cavity_start_x(self) -> float:
        return -self.total_length / 2.0

    @property
    def cavity_end_x(self) -> float:
        return self.total_length / 2.0 - self.output_taper_length

    @property
    def cavity_center_x(self) -> float:
        return (self.cavity_start_x + self.cavity_end_x) / 2.0

    @property
    def mesa_width(self) -> float:
        return max(self.ridge_width * 1.9, self.waveguide_width * 3.2)

    @property
    def dbr_length(self) -> float:
        return self.cavity_length * 0.24

    @property
    def gain_length(self) -> float:
        return self.cavity_length * 0.58

    @property
    def phase_length(self) -> float:
        return self.cavity_length - self.dbr_length - self.gain_length

    @property
    def dbr_center_x(self) -> float:
        return self.cavity_start_x + self.dbr_length / 2.0

    @property
    def gain_center_x(self) -> float:
        return self.cavity_start_x + self.dbr_length + self.gain_length / 2.0

    @property
    def phase_center_x(self) -> float:
        return self.cavity_end_x - self.phase_length / 2.0

    @property
    def contact_width(self) -> float:
        return max(self.ridge_width * 0.34, 0.6)

    @property
    def pad_y(self) -> float:
        return self.mesa_width * 0.55 + self.pad_width * 0.9

    @property
    def left_pad_x(self) -> float:
        return self.gain_center_x - self.gain_length * 0.18

    @property
    def right_pad_x(self) -> float:
        return self.phase_center_x + self.phase_length * 0.18

    def physical_spec(self) -> PhysicalSpec:
        return PhysicalSpec(
            device_family=self.schematic_family,
            values={
                "cavity_length": self.cavity_length,
                "ridge_width": self.ridge_width,
                "output_taper_length": self.output_taper_length,
                "pad_length": self.pad_length,
                "pad_width": self.pad_width,
                "waveguide_width": self.waveguide_width,
                "thickness": self.chip_thickness,
            },
        )

    def _laser_metrics(self, *, draw: bool = False) -> dict[str, float]:
        cavity_length = self._draw("cavity_length", self.cavity_length) if draw else float(self.cavity_length)
        ridge_width = self._draw("ridge_width", self.ridge_width) if draw else float(self.ridge_width)
        output_taper_length = self._draw("output_taper_length", self.output_taper_length) if draw else float(self.output_taper_length)
        waveguide_width = self._draw("waveguide_width", self.waveguide_width) if draw else float(self.waveguide_width)
        pad_length = self._draw("pad_length", self.pad_length) if draw else float(self.pad_length)
        pad_width = self._draw("pad_width", self.pad_width) if draw else float(self.pad_width)
        total_length = cavity_length + output_taper_length
        cavity_start_x = -total_length / 2.0
        cavity_end_x = total_length / 2.0 - output_taper_length
        dbr_length = cavity_length * 0.24
        gain_length = cavity_length * 0.58
        phase_length = cavity_length - dbr_length - gain_length
        cavity_center_x = (cavity_start_x + cavity_end_x) / 2.0
        dbr_center_x = cavity_start_x + dbr_length / 2.0
        gain_center_x = cavity_start_x + dbr_length + gain_length / 2.0
        phase_center_x = cavity_end_x - phase_length / 2.0
        mesa_width = max(ridge_width * 1.9, waveguide_width * 3.2)
        contact_width = max(ridge_width * 0.34, 0.6)
        pad_y = mesa_width * 0.55 + pad_width * 0.9
        left_pad_x = gain_center_x - gain_length * 0.18
        right_pad_x = phase_center_x + phase_length * 0.18
        return {
            "cavity_length": cavity_length,
            "ridge_width": ridge_width,
            "output_taper_length": output_taper_length,
            "waveguide_width": waveguide_width,
            "pad_length": pad_length,
            "pad_width": pad_width,
            "total_length": total_length,
            "cavity_start_x": cavity_start_x,
            "cavity_end_x": cavity_end_x,
            "cavity_center_x": cavity_center_x,
            "mesa_width": mesa_width,
            "dbr_length": dbr_length,
            "gain_length": gain_length,
            "phase_length": phase_length,
            "dbr_center_x": dbr_center_x,
            "gain_center_x": gain_center_x,
            "phase_center_x": phase_center_x,
            "contact_width": contact_width,
            "pad_y": pad_y,
            "left_pad_x": left_pad_x,
            "right_pad_x": right_pad_x,
        }

    def _silicon_taper_polygon(self, metrics: dict[str, float] | None = None) -> list[tuple[float, float]]:
        m = metrics or self._laser_metrics(draw=False)
        return _segment_outline((m["cavity_end_x"], 0.0), (m["total_length"] / 2.0, 0.0), m["ridge_width"] * 0.82, m["waveguide_width"])

    def _lead_polygons(self, metrics: dict[str, float] | None = None) -> list[list[tuple[float, float]]]:
        m = metrics or self._laser_metrics(draw=False)
        left_start = (m["left_pad_x"], 0.0)
        right_start = (m["right_pad_x"], 0.0)
        left_end = (m["left_pad_x"], m["pad_y"] - m["pad_width"] * 0.4)
        right_end = (m["right_pad_x"], m["pad_y"] - m["pad_width"] * 0.4)
        return [
            _segment_outline(left_start, left_end, m["contact_width"], m["contact_width"]),
            _segment_outline(right_start, right_end, m["contact_width"], m["contact_width"]),
        ]

    def ports(self) -> dict[str, Port]:
        # Ports track the drawn laser body (compacted cavity); render_physical restores µm.
        m = self._laser_metrics(draw=True)
        return {
            "o1": Port("o1", Vec3(m["total_length"] / 2.0, 0, 0), orientation_deg=0, width=m["waveguide_width"]),
            "e1": Port("e1", Vec3(m["left_pad_x"], m["pad_y"], 0), orientation_deg=90, width=m["pad_width"], kind="electrical"),
            "e2": Port("e2", Vec3(m["right_pad_x"], m["pad_y"], 0), orientation_deg=90, width=m["pad_width"], kind="electrical"),
        }

    def optical_paths(self, in_port: str) -> list[dict[str, Any]]:
        """The emission path: from the middle of the drawn gain region, along the guide, to the output port."""

        if in_port != "o1":
            return []
        m = self._laser_metrics(draw=True)
        return [{"port": "o1", "pts": [[m["gain_center_x"], 0.0], [m["cavity_end_x"], 0.0], [m["total_length"] / 2.0, 0.0]]}]

    def geometry_2d(self) -> dict[str, Any]:
        """A heterogeneous III-V on silicon laser: Bragg mirror, gain mesa, heated phase section, output taper."""

        m = self._laser_metrics(draw=True)
        x0, x1 = m["cavity_start_x"], m["cavity_end_x"]
        dbr_end, ridge = x0 + m["dbr_length"], m["ridge_width"]
        si = max(m["waveguide_width"], ridge * 0.45) / 2.0
        gain_end = dbr_end + m["gain_length"]
        children: list[dict[str, Any]] = [
            _chip_box((x0 + x1) / 2.0, 0.0, x1 - x0, 2.0 * si, self.color, self.opacity, stroke=SILICON_EDGE, stroke_width=0.08),
            *_bragg_teeth(x0 + m["dbr_length"] * 0.06, dbr_end - m["dbr_length"] * 0.06, 12, si, ridge * 0.35, self.color, self.opacity),
            *_gain_2d(dbr_end, gain_end, m["mesa_width"] / 2.0, si, ridge, self.opacity),
            _chip_box(m["phase_center_x"], 0.0, m["phase_length"] * 0.8, ridge * 0.45, TIN, self.opacity, stroke=TIN_EDGE, stroke_width=0.06, layer="heater"),
            _chip_polygon(self._silicon_taper_polygon(m), fill=self.color, opacity=self.opacity, stroke=SILICON_EDGE, stroke_width=0.08),
            *_contact_children(m["gain_center_x"], 0.0, m["gain_length"] * 0.62, m["contact_width"], self.opacity, vias=5),
            *[_chip_polygon(points, fill=GOLD, opacity=self.opacity, stroke=GOLD_EDGE, stroke_width=0.08, layer="metal") for points in self._lead_polygons(m)],
            *_pad_children(m["left_pad_x"], m["pad_y"], m["pad_length"], m["pad_width"], self.opacity),
            *_pad_children(m["right_pad_x"], m["pad_y"], m["pad_length"], m["pad_width"], self.opacity),
        ]
        return {"type": "group", "children": children}

    def geometry_3d(self) -> dict[str, Any]:
        return self._on_the_stack(_chip_process_3d(
            OnChipLaser.geometry_2d(self),
            self._draw_thickness(),
            self._draw_layer_stack(),
            core=self._core(),
            doped_preset=self._draw_material_preset(),
            opacity=self.opacity,
            schematic=not self.render_physical,
        ))
@dataclass
class FrequencyComb(OnChipLaser):
    """On-chip frequency comb source: a laser whose output carries ``line_count`` lines ``line_spacing_ghz`` apart.

    The layout is the on-chip laser's (same ports); the 1D symbol shows the comb lines.
    """

    component_type = "FrequencyComb"

    def __init__(self, center=(0, 0), angle=0, line_spacing_ghz=100.0, line_count=20, **kwargs):
        self.line_spacing_ghz = float(line_spacing_ghz)
        self.line_count = int(line_count)
        super().__init__(center=center, angle=angle, **kwargs)

    def symbol_1d(self) -> tuple[str, dict[str, Any]]:
        return "comb", {}

    def _ring_layout(self) -> dict[str, float]:
        """A Kerr microcomb: the laser output runs on a bus past a microring that turns the pump into a comb."""

        m = self._laser_metrics(draw=True)
        w = m["waveguide_width"]
        radius = max(m["mesa_width"] * 2.2, 10.0)
        start = m["total_length"] / 2.0
        return {"w": w, "radius": radius, "start": start, "cx": start + radius + 6.0, "cy": radius + w * 1.6,
                "end": start + 2.0 * radius + 12.0}

    def ports(self) -> dict[str, Port]:
        ports = dict(super().ports())
        ring = self._ring_layout()
        ports["o1"] = Port("o1", Vec3(ring["end"], 0, 0), orientation_deg=0, width=ring["w"])
        return ports

    def geometry_2d(self) -> dict[str, Any]:
        ring = self._ring_layout()
        children = list(super().geometry_2d()["children"])
        children += [
            _chip_box((ring["start"] + ring["end"]) / 2.0, 0.0, ring["end"] - ring["start"], ring["w"], self.color, self.opacity,
                      stroke=SILICON_EDGE, stroke_width=0.08),
            _chip_circle(ring["cx"], ring["cy"], ring["radius"], stroke=SILICON_EDGE, stroke_width=ring["w"] + 0.16, fill="none", opacity=self.opacity),
            _chip_circle(ring["cx"], ring["cy"], ring["radius"], stroke=self.color, stroke_width=ring["w"], fill="none", opacity=self.opacity),
        ]
        return {"type": "group", "children": children}

    def geometry_3d(self) -> dict[str, Any]:
        import math

        ring = self._ring_layout()
        laser = list(super().geometry_3d()["children"])          # on the stack already
        points = [(ring["cx"] + ring["radius"] * math.cos(math.radians(a)), ring["cy"] + ring["radius"] * math.sin(math.radians(a)))
                  for a in range(0, 360, 5)]
        children = [
            _chip_slab(ring["end"] - ring["start"], ring["w"], self._draw_thickness(), x=(ring["start"] + ring["end"]) / 2.0,
                       **self._core()),
            _chip_path_slab(points, ring["w"], self._draw_thickness(), **self._core(), closed=True),
        ]
        return {"shape": "group", "children": [*laser, *self._on_the_stack(children)["children"]]}

    def physics_metadata(self) -> dict[str, Any]:
        return {"domain": "on_chip", "component": "frequency_comb", "mode": "source",
                "line_spacing_ghz": self.line_spacing_ghz, "line_count": self.line_count}


class SOA(ChipComponent):
    component_type = "SOA"
    schematic_family = "soa"
    amplifier_length: float = 70.0
    taper_length: float = 10.0
    ridge_width: float = 1.8
    waveguide_width: float = 0.5
    pad_length: float = 16.0
    pad_width: float = 7.0

    def __init__(
        self,
        center=(0, 0),
        angle=0,
        amplifier_length: float = 70.0,
        taper_length: float = 10.0,
        ridge_width: float = 1.8,
        waveguide_width: float | None = None,
        pad_length: float = 16.0,
        pad_width: float = 7.0,
        **kwargs,
    ):
        strip = _generic_pdk_defaults()["strip"]
        self.amplifier_length = float(amplifier_length)
        self.taper_length = float(taper_length)
        self.ridge_width = float(ridge_width)
        self.waveguide_width = float(strip["width"] if waveguide_width is None else waveguide_width)
        self.pad_length = float(pad_length)
        self.pad_width = float(pad_width)
        self._init_chip(center=center, angle=angle, **kwargs)

    @property
    def total_length(self) -> float:
        return self.amplifier_length + 2.0 * self.taper_length

    @property
    def pad_y(self) -> float:
        return self.ridge_width * 0.68 + self.pad_width * 0.9

    @property
    def left_pad_x(self) -> float:
        return -self.amplifier_length * 0.22

    @property
    def right_pad_x(self) -> float:
        return self.amplifier_length * 0.22

    def physical_spec(self) -> PhysicalSpec:
        return PhysicalSpec(
            device_family=self.schematic_family,
            values={
                "amplifier_length": self.amplifier_length,
                "taper_length": self.taper_length,
                "ridge_width": self.ridge_width,
                "pad_length": self.pad_length,
                "pad_width": self.pad_width,
                "waveguide_width": self.waveguide_width,
                "thickness": self.chip_thickness,
            },
        )

    def _soa_metrics(self, *, draw: bool = False) -> dict[str, float]:
        amplifier_length = self._draw("amplifier_length", self.amplifier_length) if draw else float(self.amplifier_length)
        taper_length = self._draw("taper_length", self.taper_length) if draw else float(self.taper_length)
        ridge_width = self._draw("ridge_width", self.ridge_width) if draw else float(self.ridge_width)
        waveguide_width = self._draw("waveguide_width", self.waveguide_width) if draw else float(self.waveguide_width)
        pad_length = self._draw("pad_length", self.pad_length) if draw else float(self.pad_length)
        pad_width = self._draw("pad_width", self.pad_width) if draw else float(self.pad_width)
        pad_y = ridge_width * 0.68 + pad_width * 0.9
        left_pad_x = -amplifier_length * 0.22
        right_pad_x = amplifier_length * 0.22
        return {
            "amplifier_length": amplifier_length,
            "taper_length": taper_length,
            "ridge_width": ridge_width,
            "waveguide_width": waveguide_width,
            "pad_length": pad_length,
            "pad_width": pad_width,
            "total_length": amplifier_length + 2.0 * taper_length,
            "pad_y": pad_y,
            "left_pad_x": left_pad_x,
            "right_pad_x": right_pad_x,
            "contact_width": max(ridge_width * 0.3, 0.3),
        }

    def _lead_polygons(self, metrics: dict[str, float] | None = None) -> list[list[tuple[float, float]]]:
        m = metrics or self._soa_metrics(draw=False)
        left_end = (m["left_pad_x"], m["pad_y"] - m["pad_width"] * 0.4)
        right_end = (m["right_pad_x"], m["pad_y"] - m["pad_width"] * 0.4)
        return [
            _segment_outline((m["left_pad_x"], 0.0), left_end, m["contact_width"], m["contact_width"]),
            _segment_outline((m["right_pad_x"], 0.0), right_end, m["contact_width"], m["contact_width"]),
        ]

    def ports(self) -> dict[str, Port]:
        return {
            "o1": Port("o1", Vec3(-self.total_length / 2.0, 0.0, 0.0), orientation_deg=180, width=self._draw("waveguide_width", self.waveguide_width)),
            "o2": Port("o2", Vec3(self.total_length / 2.0, 0.0, 0.0), orientation_deg=0, width=self._draw("waveguide_width", self.waveguide_width)),
            "e1": Port("e1", Vec3(self.left_pad_x, self.pad_y, 0.0), orientation_deg=90, width=self.pad_width, kind="electrical"),
            "e2": Port("e2", Vec3(self.right_pad_x, self.pad_y, 0.0), orientation_deg=90, width=self.pad_width, kind="electrical"),
        }

    def geometry_2d(self) -> dict[str, Any]:
        """A III-V gain mesa on the silicon guide (tapered ends, MQW), its contact with vias, two pads."""

        m, op = self._soa_metrics(draw=True), self.opacity
        half_a, half_t, ridge = m["amplifier_length"] / 2.0, m["total_length"] / 2.0, m["ridge_width"]
        si = max(m["waveguide_width"], ridge * 0.45) / 2.0
        children = [
            _chip_segment_polygon((-half_t, 0.0), (-half_a, 0.0), m["waveguide_width"], 2.0 * si, fill=self.color, opacity=op,
                                  stroke=SILICON_EDGE, stroke_width=0.08),
            _chip_box(0.0, 0.0, m["amplifier_length"], 2.0 * si, self.color, op, stroke=SILICON_EDGE, stroke_width=0.08),
            _chip_segment_polygon((half_a, 0.0), (half_t, 0.0), 2.0 * si, m["waveguide_width"], fill=self.color, opacity=op,
                                  stroke=SILICON_EDGE, stroke_width=0.08),
            *_gain_2d(-half_a, half_a, ridge * 0.75, si, ridge, op),
            *_contact_children(0.0, 0.0, m["amplifier_length"] * 0.62, m["contact_width"], op, vias=6),
            *[_chip_polygon(points, fill=GOLD, opacity=op, stroke=GOLD_EDGE, stroke_width=0.08, layer="metal") for points in self._lead_polygons(m)],
            *_pad_children(m["left_pad_x"], m["pad_y"], m["pad_length"], m["pad_width"], op),
            *_pad_children(m["right_pad_x"], m["pad_y"], m["pad_length"], m["pad_width"], op),
        ]
        return {"type": "group", "children": children}

    def physics_metadata(self) -> dict[str, Any]:
        return {
            "domain": "on_chip",
            "component": "soa",
            "amplifier_length": self.amplifier_length,
            "gain_db": 20.0,
            "saturation_power_mw": None,
        }

    def geometry_3d(self) -> dict[str, Any]:
        return self._on_the_stack(_chip_process_3d(
            SOA.geometry_2d(self),
            self._draw_thickness(),
            self._draw_layer_stack(),
            core=self._core(),
            doped_preset=self._draw_material_preset(),
            opacity=self.opacity,
            schematic=not self.render_physical,
        ))



def _ic_die_3d(part: ChipComponent, role: str, label: str, mark: list[tuple[float, float]], *, line: bool) -> dict[str, Any]:
    """An electronic IC flip-chipped on the photonic die, read like the EIC part: a dark die, its label, its
    symbol ``mark`` (a filled polygon, or a polyline when ``line``) in the role colour, gold tabs at its ports.

    The light grey slab at chip height with hairline marks read as a ghost on the die.
    """

    from optodraw.components.electronics._shared import CHIP_BODY, CHIP_EDGE, CHIP_FACE, IC_BODY_THICKNESS, _ROLE_ACCENT

    length, width = part._draw("length", part.length), part._draw("width", part.width)
    pad = part._draw("pad_size", part.pad_size)
    tab = 0.2                                             # the die stands on its gold tabs, as a flip-chip die on its bumps
    accent, top = _ROLE_ACCENT[role], tab + IC_BODY_THICKNESS
    shape = _polyline_outline(mark, max(width * 0.035, 0.35)) if line else mark
    rim = [(sx * length * 0.51, sy * width * 0.51) for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
    body = [(sx * length * 0.5, sy * width * 0.5) for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
    children: list[dict[str, Any]] = [
        # the edge, a ring round the body: one solid on each patch of the base
        {"shape": "extruded_polygon", "points": rim, "holes": [body], "height": 0.24, "position": [0.0, tab, 0.0],
         "material": {"color": CHIP_EDGE, "metalness": 0.02, "roughness": 0.74}},
        {"shape": "box", "width": length, "height": IC_BODY_THICKNESS, "depth": width,
         "position": [0.0, tab + IC_BODY_THICKNESS / 2.0, 0.0],
         "material": {"color": CHIP_BODY, "metalness": 0.04, "roughness": 0.66}},
        {"shape": "box", "width": length * 0.86, "height": 0.12, "depth": width * 0.8, "position": [0.0, top + 0.06, 0.0],
         "material": {"color": CHIP_FACE, "metalness": 0.05, "roughness": 0.58}},
        {"shape": "extruded_polygon", "points": shape, "height": 0.08, "position": [0.0, top + 0.12, 0.0],
         "material": {"color": accent, "metalness": 0.12, "roughness": 0.5}},
        {"shape": "text_decal", "text": label, "width": length * 0.4, "height": width * 0.36,
         "position": [-length * 0.2, top + 0.14, 0.0], "rotation": [-math.pi / 2.0, 0.0, 0.0],
         "fontSize": max(int(width * 7.0), 96), "color": accent, "fontWeight": "800"},
    ]
    for port in part.ports().values():                    # half under the die, half out: the pad you bond to
        children.append({"shape": "box", "width": pad, "height": tab, "depth": pad,
                         "position": [port.center.x, tab / 2.0, -port.center.y],
                         "material": {"color": GOLD, "metalness": 1.0, "roughness": 0.25}})
    return {"shape": "group", "children": children}


@dataclass
class TIA(ChipComponent):
    component_type = "TIA"
    schematic_family = "tia"
    length: float = 28.0
    width: float = 14.0
    pad_size: float = 2.6

    def __init__(self, center=(0, 0), angle=0, length: float = 28.0, width: float = 14.0, pad_size: float = 2.6, **kwargs):
        self.length = float(length)
        self.width = float(width)
        self.pad_size = float(pad_size)
        self._init_chip(center=center, angle=angle, **kwargs)

    def ports(self) -> dict[str, Port]:
        return {
            "e1": Port("e1", Vec3(-self.length / 2.0, 0.0, 0.0), orientation_deg=180, width=self.pad_size, kind="electrical"),
            "e2": Port("e2", Vec3(self.length / 2.0, 0.0, 0.0), orientation_deg=0, width=self.pad_size, kind="electrical"),
        }

    def physical_spec(self) -> PhysicalSpec:
        return PhysicalSpec(
            device_family=self.schematic_family,
            values={
                "length": self.length,
                "width": self.width,
                "pad_size": self.pad_size,
                "thickness": self.chip_thickness,
            },
        )

    def geometry_2d(self) -> dict[str, Any]:
        length = self._draw("length", self.length)
        width = self._draw("width", self.width)
        pad_size = self._draw("pad_size", self.pad_size)
        triangle = [(-length * 0.14, -width * 0.18), (-length * 0.14, width * 0.18), (length * 0.14, 0.0)]
        return {
            "type": "group",
            "children": [
                _chip_box(0.0, 0.0, length, width, "#bcc4d2", self.opacity, stroke="#6b7280", stroke_width=0.08, layer="package"),
                _chip_polygon(triangle, fill="#eef2f7", opacity=self.opacity, stroke="#6b7280", stroke_width=0.08, layer="legend"),
                _chip_line(-length / 2.0, 0.0, -length * 0.18, 0.0, stroke="#6b7280", stroke_width=0.34, opacity=self.opacity),
                _chip_line(length * 0.14, 0.0, length / 2.0, 0.0, stroke="#6b7280", stroke_width=0.34, opacity=self.opacity),
                _chip_box(-length / 2.0 + pad_size * 0.54, 0.0, pad_size, pad_size, "#d4af37", self.opacity, stroke="#8e7611", stroke_width=0.08, layer="pad"),
                _chip_box(length / 2.0 - pad_size * 0.54, 0.0, pad_size, pad_size, "#d4af37", self.opacity, stroke="#8e7611", stroke_width=0.08, layer="pad"),
            ],
        }

    def geometry_3d(self) -> dict[str, Any]:
        length, width = self._draw("length", self.length), self._draw("width", self.width)
        cx = length * 0.2
        return _ic_die_3d(self, "tia", "TIA", [(cx - length * 0.1, -width * 0.22), (cx + length * 0.12, 0.0),
                                                (cx - length * 0.1, width * 0.22)], line=False)


@dataclass
class DACDriver(ChipComponent):
    component_type = "DACDriver"
    schematic_family = "dac_driver"
    length: float = 34.0
    width: float = 16.0
    pad_size: float = 2.4
    output_gap: float | None = None

    def __init__(self, center=(0, 0), angle=0, length: float = 34.0, width: float = 16.0, pad_size: float = 2.4, output_gap: float | None = None, **kwargs):
        self.length = float(length)
        self.width = float(width)
        self.pad_size = float(pad_size)
        # by default the gap of the pic od converter (kind=dac, ports=chip): 0.32 cm in its 1.3 cm from e1 to e3
        self.output_gap = self.length * 0.32 / 1.3 if output_gap is None else float(output_gap)
        self._init_chip(center=center, angle=angle, **kwargs)

    def ports(self) -> dict[str, Port]:
        return {
            "e1": Port("e1", Vec3(-self.length / 2.0, self.output_gap / 2.0, 0.0), orientation_deg=180, width=self.pad_size, kind="electrical"),
            "e2": Port("e2", Vec3(-self.length / 2.0, -self.output_gap / 2.0, 0.0), orientation_deg=180, width=self.pad_size, kind="electrical"),
            "e3": Port("e3", Vec3(self.length / 2.0, self.output_gap / 2.0, 0.0), orientation_deg=0, width=self.pad_size, kind="electrical"),
            "e4": Port("e4", Vec3(self.length / 2.0, -self.output_gap / 2.0, 0.0), orientation_deg=0, width=self.pad_size, kind="electrical"),
        }

    def physical_spec(self) -> PhysicalSpec:
        return PhysicalSpec(
            device_family=self.schematic_family,
            values={
                "length": self.length,
                "width": self.width,
                "pad_size": self.pad_size,
                "output_gap": self.output_gap,
                "thickness": self.chip_thickness,
            },
        )

    def geometry_2d(self) -> dict[str, Any]:
        length = self._draw("length", self.length)
        width = self._draw("width", self.width)
        pad_size = self._draw("pad_size", self.pad_size)
        output_gap = self._draw("output_gap", self.output_gap)
        return {
            "type": "group",
            "children": [
                _chip_box(0.0, 0.0, length, width, "#c8ced9", self.opacity, stroke="#6b7280", stroke_width=0.08, layer="package"),
                _chip_line(-length * 0.2, output_gap / 2.0, length * 0.18, output_gap / 2.0, stroke="#6b7280", stroke_width=0.28, opacity=self.opacity),
                _chip_line(-length * 0.2, -output_gap / 2.0, length * 0.18, -output_gap / 2.0, stroke="#6b7280", stroke_width=0.28, opacity=self.opacity),
                _chip_polyline([(-length * 0.04, -width * 0.18), (0.0, 0.0), (length * 0.04, width * 0.18), (length * 0.1, -width * 0.08), (length * 0.16, width * 0.22)], stroke="#6b7280", stroke_width=0.24, opacity=self.opacity),
                _chip_box(-length / 2.0 + pad_size * 0.54, output_gap / 2.0, pad_size, pad_size, "#d4af37", self.opacity, stroke="#8e7611", stroke_width=0.08, layer="pad"),
                _chip_box(-length / 2.0 + pad_size * 0.54, -output_gap / 2.0, pad_size, pad_size, "#d4af37", self.opacity, stroke="#8e7611", stroke_width=0.08, layer="pad"),
                _chip_box(length / 2.0 - pad_size * 0.54, output_gap / 2.0, pad_size, pad_size, "#d4af37", self.opacity, stroke="#8e7611", stroke_width=0.08, layer="pad"),
                _chip_box(length / 2.0 - pad_size * 0.54, -output_gap / 2.0, pad_size, pad_size, "#d4af37", self.opacity, stroke="#8e7611", stroke_width=0.08, layer="pad"),
            ],
        }

    def geometry_3d(self) -> dict[str, Any]:
        length, width = self._draw("length", self.length), self._draw("width", self.width)
        zigzag = [(length * (0.12 + x), width * y) for x, y in
                  ((-0.04, -0.18), (0.0, 0.0), (0.04, 0.18), (0.1, -0.08), (0.16, 0.22))]   # the 2D mark
        return _ic_die_3d(self, "dac", "DAC", zigzag, line=True)


@dataclass
class ADC(ChipComponent):
    component_type = "ADC"
    schematic_family = "adc"
    length: float = 32.0
    width: float = 16.0
    pad_size: float = 2.4

    def __init__(self, center=(0, 0), angle=0, length: float = 32.0, width: float = 16.0, pad_size: float = 2.4, **kwargs):
        self.length = float(length)
        self.width = float(width)
        self.pad_size = float(pad_size)
        self._init_chip(center=center, angle=angle, **kwargs)

    def ports(self) -> dict[str, Port]:
        unit = self.length / 1.3          # the pic od converter (kind=adc, ports=chip): 1.3 cm from e1 to e3
        return {
            "e1": Port("e1", Vec3(-self.length / 2.0, 0.0, 0.0), orientation_deg=180, width=self.pad_size, kind="electrical"),
            "e2": Port("e2", Vec3(-0.15 * unit, -0.52 * unit, 0.0), orientation_deg=270, width=self.pad_size, kind="electrical"),
            "e3": Port("e3", Vec3(self.length / 2.0, 0.0, 0.0), orientation_deg=0, width=self.pad_size, kind="electrical"),
        }

    def physical_spec(self) -> PhysicalSpec:
        return PhysicalSpec(
            device_family=self.schematic_family,
            values={
                "length": self.length,
                "width": self.width,
                "pad_size": self.pad_size,
                "thickness": self.chip_thickness,
            },
        )

    def geometry_2d(self) -> dict[str, Any]:
        length = self._draw("length", self.length)
        width = self._draw("width", self.width)
        pad_size = self._draw("pad_size", self.pad_size)
        ladder = [
            (-length * 0.12, width * 0.18),
            (-length * 0.04, width * 0.18),
            (-length * 0.04, width * 0.04),
            (length * 0.04, width * 0.04),
            (length * 0.04, -width * 0.1),
            (length * 0.12, -width * 0.1),
        ]
        return {
            "type": "group",
            "children": [
                _chip_box(0.0, 0.0, length, width, "#c8ced9", self.opacity, stroke="#6b7280", stroke_width=0.08, layer="package"),
                _chip_polyline(ladder, stroke="#6b7280", stroke_width=0.26, opacity=self.opacity),
                _chip_line(-length / 2.0, 0.0, -length * 0.16, 0.0, stroke="#6b7280", stroke_width=0.3, opacity=self.opacity),
                _chip_line(length * 0.12, 0.0, length / 2.0, 0.0, stroke="#6b7280", stroke_width=0.3, opacity=self.opacity),
                _chip_box(-length / 2.0 + pad_size * 0.54, 0.0, pad_size, pad_size, "#d4af37", self.opacity, stroke="#8e7611", stroke_width=0.08, layer="pad"),
                _chip_box(0.0, -width / 2.0 + pad_size * 0.54, pad_size, pad_size, "#d4af37", self.opacity, stroke="#8e7611", stroke_width=0.08, layer="pad"),
                _chip_box(length / 2.0 - pad_size * 0.54, 0.0, pad_size, pad_size, "#d4af37", self.opacity, stroke="#8e7611", stroke_width=0.08, layer="pad"),
            ],
        }

    def geometry_3d(self) -> dict[str, Any]:
        length, width = self._draw("length", self.length), self._draw("width", self.width)
        stairs = [(length * (0.22 + x), width * y) for x, y in
                  ((-0.12, 0.18), (-0.04, 0.18), (-0.04, 0.04), (0.04, 0.04), (0.04, -0.1), (0.12, -0.1))]  # the 2D mark
        return _ic_die_3d(self, "adc", "ADC", stairs, line=True)

@dataclass
class DBRLaser(ChipComponent):
    """Distributed-Bragg-reflector (DBR) laser — a gain ridge bounded by two grating
    mirror sections, with an output taper and top metal contacts."""

    component_type = "DBRLaser"
    schematic_family = "dbr_laser"
    gain_length: float = 120.0
    dbr_length: float = 60.0
    ridge_width: float = 2.5
    output_taper_length: float = 22.0
    waveguide_width: float = 0.5
    pad_size: float = 16.0
    tooth_count: int = 8

    def __init__(self, center=(0, 0), angle=0, gain_length=120.0, dbr_length=60.0, ridge_width=2.5, output_taper_length=22.0, waveguide_width: float | None = None, pad_size=16.0, tooth_count=8, **kwargs):
        strip = _generic_pdk_defaults()["strip"]
        self.gain_length = float(gain_length)
        self.dbr_length = float(dbr_length)
        self.ridge_width = float(ridge_width)
        self.output_taper_length = float(output_taper_length)
        self.waveguide_width = float(strip["width"] if waveguide_width is None else waveguide_width)
        self.pad_size = float(pad_size)
        self.tooth_count = int(tooth_count)
        self._init_chip(center=center, angle=angle, **kwargs)

    @property
    def cavity_length(self) -> float:
        return self.gain_length + 2.0 * self.dbr_length

    def anim_behaviors(self) -> list[dict]:
        return [{"key": "emission", "label": "Emission", "options": [
            ["auto", "CW (continuous wave)"], ["pulsed", "Pulsed (single packet)"],
            ["off", "Off (dark)"]]}]

    @property
    def _pad_y(self) -> float:
        return self.ridge_width * 1.5 + self.pad_size * 0.5 + 1.5       # room for the mesa and the n contact

    def physical_spec(self) -> PhysicalSpec:
        return PhysicalSpec(
            device_family=self.schematic_family,
            values={"gain_length": self.gain_length, "dbr_length": self.dbr_length, "cavity_length": self.cavity_length, "ridge_width": self.ridge_width, "thickness": self.chip_thickness},
        )

    def ports(self) -> dict[str, Port]:
        out_x = self.cavity_length / 2.0 + self.output_taper_length
        return {
            "o1": Port("o1", Vec3(out_x, 0, 0), orientation_deg=0, width=self._draw("waveguide_width", self.waveguide_width)),
            "e1": Port("e1", Vec3(0, self._pad_y, 0), orientation_deg=90, width=self.pad_size, kind="electrical"),
            "e2": Port("e2", Vec3(0, -self._pad_y, 0), orientation_deg=270, width=self.pad_size, kind="electrical"),
        }

    def optical_paths(self, in_port: str) -> list[dict[str, Any]]:
        """The emission path: from the middle of the drawn gain mesa, through the far mirror and the taper, to the output port."""

        if in_port != "o1":
            return []
        half = self.cavity_length / 2.0
        return [{"port": "o1", "pts": [[0.0, 0.0], [half, 0.0], [half + self.output_taper_length, 0.0]]}]

    def geometry_2d(self) -> dict[str, Any]:
        """A gain mesa between two Bragg mirrors on the silicon guide; p contact up to e1, n contact down to e2."""

        half, ridge, op = self.cavity_length / 2.0, self.ridge_width, self.opacity
        out_x = half + self.output_taper_length
        si = max(self._draw("waveguide_width", self.waveguide_width), ridge * 0.45) / 2.0
        mesa, py, pad = ridge * 1.5, self._pad_y, self.pad_size     # a long thin cavity: the mesa drawn wide enough to read
        n_y = -(mesa + 0.6)
        children: list[dict[str, Any]] = [
            _chip_box(0.0, 0.0, self.cavity_length, 2.0 * si, self.color, op, stroke=SILICON_EDGE, stroke_width=0.08),
            _chip_segment_polygon((half, 0.0), (out_x, 0.0), 2.0 * si, self._draw("waveguide_width", self.waveguide_width),
                                  fill=self.color, opacity=op, stroke=SILICON_EDGE, stroke_width=0.08),
            *_bragg_teeth(-half, -half + self.dbr_length, self.tooth_count, si, ridge * 0.6, self.color, op),
            *_bragg_teeth(half - self.dbr_length, half, self.tooth_count, si, ridge * 0.6, self.color, op),
            *_gain_2d(-self.gain_length / 2.0, self.gain_length / 2.0, mesa, si, ridge, op),
            *_contact_children(0.0, 0.0, self.gain_length * 0.6, max(ridge * 0.24, 0.5), op, vias=6),
            *_contact_children(0.0, n_y, self.gain_length * 0.5, 0.6, op, vias=6),
            _lead(0.0, 0.0, py - pad / 2.0, pad * 0.2, op),
            _lead(0.0, n_y, -(py - pad / 2.0), pad * 0.2, op),
            *_pad_children(0.0, py, pad, pad, op),
            *_pad_children(0.0, -py, pad, pad, op),
        ]
        return {"type": "group", "children": children}

    def geometry_3d(self) -> dict[str, Any]:
        return self._on_the_stack(_chip_process_3d(
            DBRLaser.geometry_2d(self),
            self._draw_thickness(),
            self._draw_layer_stack(),
            core=self._core(),
            doped_preset=self._draw_material_preset(),
            opacity=self.opacity,
            schematic=not self.render_physical,
        ))

    def physics_metadata(self) -> dict[str, Any]:
        return {"domain": "on_chip", "component": "dbr_laser", "mode": "source", "cavity_length": self.cavity_length}


@dataclass
class AvalanchePhotodetector(ChipComponent):
    """Waveguide avalanche photodiode (APD). Default ``angle=0`` puts ``o1``
    on the west face at 180°, same as :class:`OnChipPhotodetector`."""

    component_type = "AvalanchePhotodetector"
    schematic_family = "avalanche_photodetector"
    length: float = 28.0
    width: float = 4.0
    multiplication_length: float = 8.0
    taper_length: float = 18.0
    pad_width: float = 10.0
    pad_length: float = 18.0
    waveguide_width: float = 0.5
    gain: float = 10.0

    _ABSORB = GERMANIUM
    _MULT = CHARGE

    def __init__(self, center=(0, 0), angle=0, length=28.0, width=4.0, multiplication_length=8.0, taper_length=18.0, pad_width=10.0, pad_length=18.0, waveguide_width: float | None = None, gain=10.0, **kwargs):
        strip = _generic_pdk_defaults()["strip"]
        self.length = float(length)
        self.width = float(width)
        self.multiplication_length = float(multiplication_length)
        self.taper_length = float(taper_length)
        self.pad_width = float(pad_width)
        self.pad_length = float(pad_length)
        self.waveguide_width = float(strip["width"] if waveguide_width is None else waveguide_width)
        self.gain = float(gain)
        self._init_chip(center=center, angle=angle, **kwargs)

    @property
    def total_length(self) -> float:
        return self.length + self.multiplication_length + self.taper_length

    def physical_spec(self) -> PhysicalSpec:
        return PhysicalSpec(
            device_family=self.schematic_family,
            values={"length": self.length, "width": self.width, "multiplication_length": self.multiplication_length, "taper_length": self.taper_length, "gain": self.gain, "waveguide_width": self.waveguide_width, "thickness": self.chip_thickness},
        )

    def ports(self) -> dict[str, Port]:
        half = self.total_length / 2.0
        pad_x = half - self.length / 2.0
        return {
            "o1": Port("o1", Vec3(-half, 0, 0), orientation_deg=180, width=self._draw("waveguide_width", self.waveguide_width)),
            "e1": Port("e1", Vec3(pad_x, self.pad_width * 0.78, 0), orientation_deg=90, width=self.pad_width, kind="electrical"),
            "e2": Port("e2", Vec3(pad_x, -self.pad_width * 0.78, 0), orientation_deg=270, width=self.pad_width, kind="electrical"),
        }

    def geometry_2d(self) -> dict[str, Any]:
        half = self.total_length / 2.0
        pad_x = half - self.length / 2.0
        waveguide_width = self._draw("waveguide_width", self.waveguide_width)
        children = _ge_cell_2d(-half, half, self.taper_length, self.width, waveguide_width, 0.0, self.opacity, self.color,
                               multiplication=self.multiplication_length)
        contact, pad_y = self.width * 0.36, self.pad_width * 0.78
        for sign in (1.0, -1.0):
            children.append(_lead(pad_x, sign * contact, sign * (pad_y - self.pad_width / 2.0), self.pad_length * 0.16, self.opacity))
            children += _pad_children(pad_x, sign * pad_y, self.pad_length, self.pad_width, self.opacity)
        return {"type": "group", "children": children}

    def geometry_3d(self) -> dict[str, Any]:
        return self._on_the_stack(_chip_process_3d(
            AvalanchePhotodetector.geometry_2d(self),
            self._draw_thickness(),
            self._draw_layer_stack(),
            core=self._core(),
            doped_preset=self._draw_material_preset(),
            opacity=self.opacity,
            schematic=not self.render_physical,
        ))

    def physics_metadata(self) -> dict[str, Any]:
        return {"domain": "on_chip", "component": "avalanche_photodetector", "mode": "detection", "gain": self.gain}
