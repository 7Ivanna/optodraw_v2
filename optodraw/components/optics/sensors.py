"""Sensors free-space optics."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from optodraw.core.component import Component
from optodraw.core.ports import Port
from optodraw.core.transform import Vec3

from ._shared import (
    _MOUNT_ALU,
    _cylinder_along_x,
    _optical_metadata,
    _post_boss,
    _ring_along_x,
    _set_common_free_space_fields,
    _through_ports,
)


def _camera_housing(H: float, sensor_w: float, sensor_h: float, front: float, color: str,
                    *, fan: bool = False) -> dict[str, Any]:
    """A compact scientific camera of height ``H`` (the Thorlabs CS-series housing, 70.4 x 60.3 x 47.6 mm at
    H = 47.6 mm): a grooved aluminium body between two black end caps with cut corners, a knurled C-mount ring
    on the front cap round the sensor, four cage-rod holes, and the USB 3.0 port, I/O jack and status LED on
    the back. The C-mount's front is at x = ``front``; the post screws into the flat bottom. A cooled camera
    (``fan``) has a fan behind a guard in its back cap."""

    W, L = H * 60.3 / 47.6, H * 70.4 / 47.6
    cap_t, mount_len, cut = L * 0.1, H * 5.5 / 47.6, H * 0.16
    x0 = front + mount_len                                   # the front cap's front face
    body = {"color": color, "metalness": 0.6, "roughness": 0.38, "preset": "aluminum"}
    black = {"color": "#1d2126", "metalness": 0.4, "roughness": 0.55, "preset": "aluminum"}
    dark = {"color": "#2b3036", "metalness": 0.45, "roughness": 0.5}
    outline = [(-H / 2 + cut, -W / 2), (H / 2 - cut, -W / 2), (H / 2, -W / 2 + cut), (H / 2, W / 2 - cut),
               (H / 2 - cut, W / 2), (-H / 2 + cut, W / 2), (-H / 2, W / 2 - cut), (-H / 2, -W / 2 + cut)]

    def cap(x: float) -> dict[str, Any]:
        return {"shape": "extruded_polygon", "role": "cap", "points": outline, "height": cap_t,
                "position": [x + cap_t, 0.0, 0.0], "rotation": [0.0, 0.0, math.pi / 2.0], "material": black}

    mid = x0 + L / 2.0
    span = L - 2.0 * cap_t
    bore = H * 12.7 / 47.6                                   # the 1 in C-mount thread
    scale = min(1.0, 0.9 * bore / max(math.hypot(sensor_w, sensor_h) / 2.0, 1e-9))
    children: list[dict[str, Any]] = [
        cap(x0),
        cap(x0 + L - cap_t),
        {"shape": "box", "role": "body", "width": span, "height": H * 0.95, "depth": W * 0.95, "position": [mid, 0.0, 0.0], "material": body},
        {**_ring_along_x(bore, H * 0.36, mount_len, black, x=front + mount_len / 2.0), "role": "c_mount"},
        # the collar's bore 1.5 % larger and its face 1 % back: it shared both with the mount
        {**_ring_along_x(bore * 1.015, H * 0.37, mount_len * 0.3, {"color": "#9aa1a9", "metalness": 0.8, "roughness": 0.3}, x=front + mount_len * 0.153), "role": "c_mount"},
        # the sensor under its cover glass, 9.5 mm behind the front of the mount
        {"shape": "box", "width": 0.12, "height": sensor_h * scale, "depth": sensor_w * scale, "position": [front + H * 0.2, 0.0, 0.0], "material": {"color": "#2a3a55", "roughness": 0.12, "metalness": 0.3, "clearcoat": 0.8}},
        {"shape": "box", "width": 0.06, "height": sensor_h * scale * 1.1, "depth": sensor_w * scale * 1.1, "position": [front + H * 0.19, 0.0, 0.0], "material": {"color": "#bcd4ea", "opacity": 0.18, "transparent": True, "clearcoat": 0.8}},
    ]
    children += [_cylinder_along_x(H * 0.03, H * 0.02, dark, position=[x0 - H * 0.005, y, z])
                 for y in (-H * 0.315, H * 0.315) for z in (-H * 0.315, H * 0.315)]           # cage-rod holes
    children += [{"shape": "box", "role": "groove", "width": span * 0.96, "height": H * 0.025, "depth": H * 0.01,
                  "position": [mid, y, side * (W * 0.475 + H * 0.004)], "material": dark}
                 for side in (-1.0, 1.0) for y in (-H * 0.27, -H * 0.09, H * 0.09, H * 0.27)]
    rear = x0 + L
    usb_z, led_z = (W * 0.36, -W * 0.38) if fan else (W * 0.26, -W * 0.22)
    children += [
        {"shape": "box", "role": "rear", "width": H * 0.04, "height": H * 0.26, "depth": H * 0.1, "position": [rear + H * 0.02, -H * 0.02, usb_z], "material": {"color": "#1f4fb4", "roughness": 0.5}},
        {"shape": "sphere", "role": "rear", "radius": H * 0.025, "position": [rear + H * 0.01, -H * 0.02, led_z], "material": {"color": "#3fae5a", "emissive": "#3fae5a", "emissiveIntensity": 1.4}},
    ]
    if fan:                                                  # a fan behind its guard: ring, hub and spokes
        children += [
            {**_ring_along_x(H * 0.26, H * 0.3, H * 0.03, dark, x=rear + H * 0.015), "role": "fan"},
            _cylinder_along_x(H * 0.08, H * 0.03, dark, position=[rear + H * 0.015, 0.0, 0.0]),
            *[{"shape": "box", "width": H * 0.02, "height": H * 0.5, "depth": H * 0.02, "position": [rear + H * 0.015, 0.0, 0.0],
               "rotation": [k * math.pi / 4.0, 0.0, 0.0], "material": dark} for k in range(4)],
        ]
    else:
        children += [
            {**_cylinder_along_x(H * 0.08, H * 0.08, _MOUNT_ALU, position=[rear + H * 0.04, -H * 0.02, 0.0]), "role": "rear"},
            {"shape": "box", "width": H * 0.01, "height": H * 0.16, "depth": W * 0.42, "position": [rear + H * 0.005, H * 0.26, 0.0], "material": {"color": "#d9dde3", "roughness": 0.6}},
        ]
    return {"shape": "group", "children": children, "post_at": [mid, -H * 0.475, 0.0]}   # the 1/4-20 hole under the body


@dataclass
class CameraSensor(Component):
    """Generic free-space camera sensor face with detector metadata."""

    component_type = "CameraSensor"
    sensor_width: float = 8.8
    sensor_height: float = 6.6
    pixel_pitch_um: float = 4.8
    resolution: tuple[int, int] = (1920, 1080)

    def __init__(self, center=(0, 0), angle=0, sensor_width=8.8, sensor_height=6.6, pixel_pitch_um=4.8, resolution=(1920, 1080), **kwargs):
        self.sensor_width = sensor_width
        self.sensor_height = sensor_height
        self.pixel_pitch_um = pixel_pitch_um
        self.resolution = resolution
        self.quantum_efficiency = kwargs.get("quantum_efficiency", 0.72)
        self.read_noise_e = kwargs.get("read_noise_e", 2.1)
        self.sensor_kind = kwargs.get("sensor_kind", "generic")
        _set_common_free_space_fields(self, center, angle, kwargs, color="#5b626b", opacity=1.0, material_preset="steel", label=kwargs.get("label", self.component_type))

    def geometry_2d(self) -> dict[str, Any]:
        frame_w = self.sensor_width + 3.0
        frame_h = self.sensor_height + 3.0
        return {
            "type": "group",
            "children": [
                {"type": "rect", "cx": 0.0, "cy": 0.0, "w": frame_w, "h": frame_h, "fill": "#0f172a", "stroke": "#020617", "stroke_width": 0.08},
                {"type": "rect", "cx": 0.0, "cy": 0.0, "w": self.sensor_width, "h": self.sensor_height, "fill": "#1e293b", "stroke": "#94a3b8", "stroke_width": 0.07},
                {"type": "rect", "cx": 0.0, "cy": 0.0, "w": self.sensor_width * 0.78, "h": self.sensor_height * 0.78, "fill": "#0ea5e9", "stroke": "#38bdf8", "stroke_width": 0.05, "opacity": 0.25},
            ],
        }

    housing_scale = 1.0          # the camera housing's size against the CS-series housing for this sensor
    cooled = False               # a cooled camera has a fan in its back cap
    # How far behind the face the 2D art ends its sync lead, in units of the frame's height: the art is sized to
    # that height. The pic od sensor draws a bare sensor: 0.34 cm from its face to the end of the lead in 0.68 cm.
    sync_depth = 0.5

    def geometry_3d(self) -> dict[str, Any]:
        return _camera_housing(self.sensor_height * 2.83 * self.housing_scale, self.sensor_width, self.sensor_height,
                               self.ports()["in"].center.x, self.color, fan=self.cooled)

    def ports(self) -> dict[str, Port]:
        half = (self.sensor_width + 3.0) / 2.0
        sync = -half + self.sync_depth * (self.sensor_height + 3.0)
        return {
            "in": Port("in", Vec3(-half, 0.0, 0.0), orientation_deg=180.0, width=self.sensor_height, kind="free_space"),
            "sync": Port("sync", Vec3(sync, 0.0, 0.0), orientation_deg=0.0, width=1.0, kind="electrical"),
        }

    def physics_metadata(self) -> dict[str, Any]:
        return _optical_metadata(
            "camera_sensor",
            sensor_kind=self.sensor_kind,
            resolution=self.resolution,
            pixel_pitch_um=self.pixel_pitch_um,
            quantum_efficiency=self.quantum_efficiency,
            read_noise_e=self.read_noise_e,
        )


@dataclass
class CMOSCamera(CameraSensor):
    """CMOS camera sensor specialization."""

    component_type = "CMOSCamera"
    sync_depth = 0.76 / 0.68     # the pic od sensor (kind=cmos): window to the back of the housing

    def __init__(self, center=(0, 0), angle=0, **kwargs):
        kwargs.setdefault("sensor_kind", "cmos")
        kwargs.setdefault("pixel_pitch_um", 3.45)
        kwargs.setdefault("read_noise_e", 1.3)
        kwargs.setdefault("label", "CMOS")
        super().__init__(center=center, angle=angle, **kwargs)

    def physics_metadata(self) -> dict[str, Any]:
        metadata = super().physics_metadata()
        metadata["component"] = "cmos_camera"
        metadata["rolling_shutter"] = True
        return metadata


@dataclass
class EMCCD(CameraSensor):
    """EMCCD camera sensor specialization."""

    component_type = "EMCCD"
    sync_depth = 0.86 / 0.74     # the pic od sensor (kind=emccd): window to the back, in its height with the fins
    housing_scale = 1.6          # an EMCCD is a cooled camera, larger than a compact CMOS camera
    cooled = True

    def __init__(self, center=(0, 0), angle=0, **kwargs):
        kwargs.setdefault("sensor_kind", "emccd")
        kwargs.setdefault("pixel_pitch_um", 13.0)
        kwargs.setdefault("read_noise_e", 0.1)
        kwargs.setdefault("label", "EMCCD")
        super().__init__(center=center, angle=angle, **kwargs)
        self.em_gain = kwargs.get("em_gain", 300.0)

    def physics_metadata(self) -> dict[str, Any]:
        metadata = super().physics_metadata()
        metadata["component"] = "emccd_camera"
        metadata["em_gain"] = self.em_gain
        return metadata


@dataclass
class SPADArray(CameraSensor):
    """Single-photon avalanche diode array detector specialization."""

    component_type = "SPADArray"
    sync_depth = 1.0             # the pic od sensor (kind=spad): a square housing

    def __init__(self, center=(0, 0), angle=0, **kwargs):
        kwargs.setdefault("sensor_kind", "spad_array")
        kwargs.setdefault("pixel_pitch_um", 16.0)
        kwargs.setdefault("read_noise_e", 0.0)
        kwargs.setdefault("label", "SPAD")
        super().__init__(center=center, angle=angle, **kwargs)
        self.dead_time_ns = kwargs.get("dead_time_ns", 35.0)
        self.max_count_rate_mhz = kwargs.get("max_count_rate_mhz", 28.0)

    def physics_metadata(self) -> dict[str, Any]:
        metadata = super().physics_metadata()
        metadata["component"] = "spad_array"
        metadata["dead_time_ns"] = self.dead_time_ns
        metadata["max_count_rate_mhz"] = self.max_count_rate_mhz
        return metadata


@dataclass
class PowerMeter(Component):
    """Inline optical power meter stub with responsivity metadata."""

    component_type = "PowerMeter"
    aperture: float = 8.0
    length: float = 10.0
    spectral_min_nm: float = 400.0
    spectral_max_nm: float = 1700.0

    def __init__(self, center=(0, 0), angle=0, aperture=8.0, length=10.0, spectral_min_nm=400.0, spectral_max_nm=1700.0, **kwargs):
        self.aperture = aperture
        self.length = length
        self.spectral_min_nm = spectral_min_nm
        self.spectral_max_nm = spectral_max_nm
        self.responsivity_a_per_w = kwargs.get("responsivity_a_per_w", 0.55)
        _set_common_free_space_fields(self, center, angle, kwargs, color="#1f2937", opacity=1.0, material_preset="steel", label=kwargs.get("label", "Power Meter"))

    def geometry_2d(self) -> dict[str, Any]:
        a, L = self.aperture, self.length
        return {
            "type": "group",
            "children": [
                # sensor-head body
                {"type": "rect", "cx": L * 0.06, "cy": 0.0, "w": L, "h": a, "fill": self.color, "stroke": "#020617", "stroke_width": 0.08},
                # circular detector aperture + active area on the front face (−x)
                {"type": "circle", "cx": -L * 0.4, "cy": 0.0, "r": a * 0.37, "fill": "#0b1220", "stroke": "#475569", "stroke_width": 0.08},
                {"type": "circle", "cx": -L * 0.4, "cy": 0.0, "r": a * 0.23, "fill": "#0ea5e9", "stroke": "#38bdf8", "stroke_width": 0.05, "opacity": 0.55},
                # readout label strip
                {"type": "rect", "cx": L * 0.22, "cy": -a * 0.3, "w": L * 0.4, "h": a * 0.14, "fill": "#0c4a6e", "opacity": 0.85},
                # cable out the back
                {"type": "line", "x1": L * 0.55, "y1": a * 0.22, "x2": L * 0.95, "y2": a * 0.34, "stroke": "#111111", "stroke_width": a * 0.1},
            ],
        }

    def geometry_3d(self) -> dict[str, Any]:
        # A photodiode power head (Thorlabs S120C): a black puck 30.5 mm across and 12.7 mm thick, the light from
        # -x. The face carries a salmon annular viewing target round the 9.5 mm aperture with its grey
        # diffuser, on a boss with an outer SM1 thread; the cable leaves the back; the post screws in below.
        a = self.aperture
        r = a * 0.75
        t, boss = 2.0 * r * 12.7 / 30.5, a * 0.15
        front = -self.length / 2.0
        body_x = front + boss + t / 2.0
        back = front + boss + t
        black = {"color": self.color, "metalness": 0.42, "roughness": 0.5, "preset": "aluminum"}
        return {
            "shape": "group",
            "children": [
                {**_cylinder_along_x(r, t, black, position=[body_x, 0.0, 0.0]), "role": "head"},
                _cylinder_along_x(r * 0.8, boss, black, position=[front + boss / 2.0, 0.0, 0.0]),
                {**_ring_along_x(r * 0.8, r * 0.86, boss * 0.8, _MOUNT_ALU, x=front + boss * 0.608), "role": "thread"},
                {**_ring_along_x(r * 0.33, r * 0.66, a * 0.02, {"color": "#f2836b", "roughness": 0.7}, x=front), "role": "target"},
                {**_cylinder_along_x(r * 0.31, a * 0.02, {"color": "#a3a9b0", "roughness": 0.85}, position=[front - a * 0.002, 0.0, 0.0]), "role": "aperture"},
                _cylinder_along_x(a * 0.12, a * 0.35, {"color": "#1b1f24", "roughness": 0.6}, position=[back + a * 0.175, 0.0, 0.0]),
                _cylinder_along_x(a * 0.06, a * 0.9, {"color": "#30353b", "roughness": 0.6}, position=[back + a * 0.8, 0.0, 0.0]),
                _post_boss(r, a * 0.3, x=body_x),
            ],
            "post_at": [body_x, -r * 1.12, 0.0],
        }

    def ports(self) -> dict[str, Port]:
        return _through_ports(self.length, self.aperture)

    def physics_metadata(self) -> dict[str, Any]:
        return _optical_metadata(
            "power_meter",
            spectral_range_nm=(self.spectral_min_nm, self.spectral_max_nm),
            responsivity_a_per_w=self.responsivity_a_per_w,
        )
