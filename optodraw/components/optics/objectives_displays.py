"""Objectives displays free-space optics."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

from optodraw.core.component import Component
from optodraw.core.ports import Port

from ._shared import (
    _MOUNT_BLACK,
    _cylinder_along_x,
    _knurl_teeth,
    _optical_metadata,
    _post_boss,
    _ring_along_x,
    _set_common_free_space_fields,
    _through_ports,
    _rim_along_x,
)


@dataclass
class Objective(Component):
    """A microscope objective lens, designed with premium high-fidelity details matching
    a physical Mitutoyo M Plan Apo series long working distance objective lens.
    """

    component_type = "Objective"
    aperture: float = 10.0
    length: float = 15.0

    def __init__(self, center=(0, 0), angle=0, aperture=10.0, length=15.0,
                 working_distance=None, **kwargs):
        self.aperture = aperture
        self.length = length
        self.accent_color = kwargs.get("accent_color", "#d7dce2")
        _set_common_free_space_fields(self, center, angle, kwargs, color="#b43b4b", opacity=1.0, material_preset="titanium")

        # Dynamically deduce magnification from the label if not explicitly provided
        self.magnification = kwargs.get("magnification", kwargs.get("mag", None))
        if self.magnification is None:
            self.magnification = 10  # default
            for mag_val in [100, 50, 20, 10, 5, 2]:
                if f"{mag_val}x" in self.label.lower():
                    self.magnification = mag_val
                    break

        # Standard Mitutoyo & optical catalog color bands
        mag_colors = {
            2: "#808000",   # Olive / Dark Green
            5: "#f59e0b",   # Yellow-Orange / Gold
            10: "#fbbf24",  # Yellow (Mitutoyo 10x Apo standard)
            20: "#10b981",  # Green
            50: "#ec4899",  # Magenta / Rose
            100: "#f8fafc", # White
        }
        self.magnification_color = kwargs.get("magnification_color", mag_colors.get(self.magnification, "#fbbf24"))

        # How far in front of the nose the focus sits. A catalogue objective
        # trades working distance for magnification -- a Mitutoyo M Plan Apo
        # goes 34 mm at 10x down to 6 mm at 100x, against a barrel of roughly
        # the same length throughout. The default follows that trend as a
        # fraction of the drawn body, clamped so neither end goes absurd; set it
        # explicitly for a specific part.
        self.working_distance = (
            float(working_distance) if working_distance
            else min(max(self.length * 6.0 / max(self.magnification, 1), self.length * 0.12), self.length * 0.9)
        )

    def physics_metadata(self) -> dict[str, Any]:
        return _optical_metadata(
            "objective",
            aperture=self.aperture,
            length=self.length,
            magnification=self.magnification,
            working_distance=self.working_distance,
            material_preset=self.material_preset,
        )

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data.update(
            aperture=self.aperture, length=self.length,
            magnification=self.magnification, working_distance=self.working_distance,
        )
        return data

    def optical_interfaces(self):
        """The focusing surface, at the nose, one working distance from focus.

        An objective is a strong lens, and it used to be invisible here: a
        bundle crossed a 100x objective without converging at all. The whole
        assembly collapses to one surface at the front element, so the focus
        lands a working distance in front of the nose -- which is where the
        sample goes, and where the catalogue measures it from."""

        from optodraw.core.raytrace import OpticalInterface

        half = self.aperture / 2.0
        front = self.length / 2.0
        return [OpticalInterface(
            p1=(front, -half), p2=(front, half),
            kind="lens", efl=self.working_distance, name="front element",
        )]

    def focus_point(self) -> tuple[float, float]:
        """Where the focus lands in the scene: one working distance in front of the nose. A sample placed here
        keeps a figure honest: trace it and the beam converges onto the sample instead of above it."""

        nose = self.world_port("out")
        heading = math.radians(float(nose.orientation_deg))
        distance = float(self.working_distance)
        return (round(float(nose.center.x) + math.cos(heading) * distance, 3),
                round(float(nose.center.y) + math.sin(heading) * distance, 3))

    def geometry_2d(self) -> dict[str, Any]:
        ln = self.length
        w = self.aperture
        mag_color = self.magnification_color
        
        # Highly-realistic vector rendering of a metallurgical objective lens
        children = [
            # 1. Brass mounting thread shoulder M26
            {"type": "rect", "cx": -ln * 0.42, "cy": 0.0, "w": ln * 0.16, "h": w * 0.7, "fill": "#cca025", "stroke": "#9a7817", "stroke_width": 0.06},
            # 5 precise vertical thread ridges
            *([{"type": "rect", "cx": -ln * 0.49 + i * (ln * 0.14 / 4.0), "cy": 0.0, "w": ln * 0.015, "h": w * 0.74, "fill": "#cca025", "stroke": "none"} for i in range(5)]),
            
            # 2. Polished chrome base collar sleeve
            {"type": "rect", "cx": -ln * 0.24, "cy": 0.0, "w": ln * 0.2, "h": w * 0.96, "fill": "#f1f5f9", "stroke": "#64748b", "stroke_width": 0.08},
            # Fine knurling indicators (10 vertical lines)
            *([{"type": "line", "x1": -ln * 0.32 + i * (ln * 0.16 / 9.0), "y1": -w * 0.45, "x2": -ln * 0.32 + i * (ln * 0.16 / 9.0), "y2": w * 0.45, "stroke": "#94a3b8", "stroke_width": 0.05} for i in range(10)]),
            
            # 3. Main polished silver barrel base
            {"type": "rect", "cx": ln * 0.08, "cy": 0.0, "w": ln * 0.28, "h": w * 1.0, "fill": "#e2e8f0", "stroke": "#475569", "stroke_width": 0.08},
            # Reflections for glossy cylindrical highlight
            {"type": "rect", "cx": ln * 0.08, "cy": 0.0, "w": ln * 0.28, "h": w * 0.24, "fill": "#ffffff", "opacity": 0.52},
            # Ambient occlusion shadows on the top and bottom edges of the cylinder
            {"type": "rect", "cx": ln * 0.08, "cy": -w * 0.42, "w": ln * 0.28, "h": w * 0.16, "fill": "#1e293b", "opacity": 0.12},
            {"type": "rect", "cx": ln * 0.08, "cy": w * 0.42, "w": ln * 0.28, "h": w * 0.16, "fill": "#1e293b", "opacity": 0.12},
            
            # 4. Premium gold label collar (Mitutoyo logo/specs zone)
            {"type": "rect", "cx": -ln * 0.06, "cy": 0.0, "w": ln * 0.14, "h": w * 0.98, "fill": "#d4af37", "stroke": "#b8860b", "stroke_width": 0.06},
            # Dual simulated engraving lines
            {"type": "line", "x1": -ln * 0.12, "y1": -w * 0.38, "x2": 0.0, "y2": -w * 0.38, "stroke": "#5c4008", "stroke_width": 0.05, "opacity": 0.75},
            {"type": "line", "x1": -ln * 0.12, "y1": w * 0.38, "x2": 0.0, "y2": w * 0.38, "stroke": "#5c4008", "stroke_width": 0.05, "opacity": 0.75},

            # 5. Magnification color band (e.g. Yellow for M Plan Apo 10x)
            {"type": "rect", "cx": ln * 0.24, "cy": 0.0, "w": ln * 0.06, "h": w * 0.96, "fill": mag_color, "stroke": "#1e293b", "stroke_width": 0.06},

            # 6. Stepped nosecone section 1 (medium dark anodized steel)
            {"type": "rect", "cx": ln * 0.33, "cy": 0.0, "w": ln * 0.12, "h": w * 0.72, "fill": "#334155", "stroke": "#1e293b", "stroke_width": 0.08},
            {"type": "rect", "cx": ln * 0.33, "cy": 0.0, "w": ln * 0.12, "h": w * 0.18, "fill": "#ffffff", "opacity": 0.22},
            
            # Polish stainless steel border spacer
            {"type": "rect", "cx": ln * 0.395, "cy": 0.0, "w": ln * 0.02, "h": w * 0.74, "fill": "#e2e8f0", "stroke": "#475569", "stroke_width": 0.04},

            # 7. Stepped nosecone section 2 (matte black protective lens tip)
            {"type": "rect", "cx": ln * 0.45, "cy": 0.0, "w": ln * 0.1, "h": w * 0.48, "fill": "#0f172a", "stroke": "#020617", "stroke_width": 0.06},
            {"type": "rect", "cx": ln * 0.45, "cy": 0.0, "w": ln * 0.1, "h": w * 0.12, "fill": "#ffffff", "opacity": 0.18},

            # 8. Deep-recessed plan-apochromatic front lens group — drawn as a real
            # biconvex glass element (edge-on lens profile), not a flat disc.
            # Lens barrel inner cavity (black shade)
            {"type": "rect", "cx": ln * 0.485, "cy": 0.0, "w": ln * 0.03, "h": w * 0.36, "fill": "#020617", "stroke": "none"},
            # Convex glass element: a thin vertical lens silhouette with apochromatic coating
            {"type": "ellipse", "cx": ln * 0.487, "cy": 0.0, "rx": ln * 0.022, "ry": w * 0.16, "fill": "#60a5fa", "stroke": "#2563eb", "stroke_width": 0.04, "opacity": 0.82},
            {"type": "ellipse", "cx": ln * 0.485, "cy": 0.0, "rx": ln * 0.012, "ry": w * 0.1, "fill": "#c084fc", "stroke": "none", "opacity": 0.45},  # purple coat shift glow
            {"type": "ellipse", "cx": ln * 0.490, "cy": -w * 0.04, "rx": ln * 0.006, "ry": w * 0.05, "fill": "#ffffff", "stroke": "none", "opacity": 0.6},  # specular highlight
        ]

        return {"type": "group", "children": children}

    def geometry_3d(self) -> dict[str, Any]:
        ln = self.length
        w = self.aperture
        
        # Premium physically-plausible materials representing Mitutoyo construction
        mat_thread = {"color": "#cca025", "preset": "brass", "metalness": 0.7, "roughness": 0.35}
        mat_chrome = {"color": "#e2e8f0", "preset": "steel", "metalness": 0.86, "roughness": 0.12}
        mat_barrel = {"color": "#cbd5e1", "preset": "steel", "metalness": 0.82, "roughness": 0.15}
        mat_gold_band = {"color": "#d4af37", "preset": "gold", "metalness": 0.88, "roughness": 0.11}
        mat_mag_band = {"color": self.magnification_color, "preset": "matte", "roughness": 0.5}
        mat_nose = {"color": "#334155", "preset": "steel", "metalness": 0.48, "roughness": 0.32}
        mat_tip = {"color": "#0f172a", "preset": "matte", "roughness": 0.78}
        
        # Apochromatic double-glass element materials for ultra-deep refraction
        mat_lens = {"color": "#93c5fd", "opacity": 0.65, "transparent": True, "roughness": 0.01, "transmission": 0.68, "ior": 1.517, "preset": "glass"}
        mat_lens_inner = {"color": "#c084fc", "opacity": 0.45, "transparent": True, "roughness": 0.01, "transmission": 0.75, "ior": 1.620, "preset": "glass"}

        children = [
            # 0. The mount: a ring round the thread (an RMS adapter in a fixed mount) with a boss for the post
            _ring_along_x(w * 0.34, w * 0.6, ln * 0.12, _MOUNT_BLACK, x=-ln * 0.42),
            _post_boss(w * 0.6, ln * 0.12, x=-ln * 0.42),
            # 1. Brass mounting threads on the back (base cylinder + 4 precise thread toruses)
            # the thread is a ring round the open back aperture, where the light enters; the rear lens shows in it
            {**_ring_along_x(w * 0.24, w * 0.34, ln * 0.16, mat_thread, x=-ln * 0.42), "role": "thread"},
            {**_cylinder_along_x(w * 0.24, ln * 0.01, {"color": "#2c4a66", "metalness": 0.2, "roughness": 0.08, "clearcoat": 1.0}, position=[-ln * 0.3452, 0.0, 0.0]), "role": "rear_lens"},
            *([_rim_along_x(w * 0.34, w * 0.018, mat_thread, position=[-ln * 0.49 + i * (ln * 0.14 / 3.0), 0.0, 0.0]) for i in range(4)]),
            
            # 2. Chrome base collar with beveled shoulders and knurled sleeve
            _cylinder_along_x(w * 0.46, ln * 0.2, mat_chrome, position=[-ln * 0.24, 0.0, 0.0]),
            _rim_along_x(w * 0.46, w * 0.02, mat_chrome, position=[-ln * 0.34, 0.0, 0.0]),
            _rim_along_x(w * 0.46, w * 0.02, mat_chrome, position=[-ln * 0.14, 0.0, 0.0]),
            *_knurl_teeth(w * 0.465, 24, x=-ln * 0.24, width=ln * 0.18, color="#cbd5e1"),
            
            # 3. Polished silver main barrel
            _cylinder_along_x(w * 0.48, ln * 0.28, mat_barrel, position=[ln * 0.08, 0.0, 0.0]),
            
            # 4. Premium gold specs band (Mitutoyo gold label brand)
            _cylinder_along_x(w * 0.486, ln * 0.14, mat_gold_band, position=[-ln * 0.06, 0.0, 0.0]),
            _rim_along_x(w * 0.486, w * 0.015, mat_gold_band, position=[-ln * 0.13, 0.0, 0.0]),
            _rim_along_x(w * 0.486, w * 0.015, mat_gold_band, position=[ln * 0.01, 0.0, 0.0]),
            
            # 5. Magnification color identifier band with high-end steel border rings
            _cylinder_along_x(w * 0.465, ln * 0.06, mat_mag_band, position=[ln * 0.24, 0.0, 0.0]),
            _rim_along_x(w * 0.47, w * 0.015, mat_chrome, position=[ln * 0.21 + w * 0.0003, 0.0, 0.0]),
            _rim_along_x(w * 0.47, w * 0.015, mat_chrome, position=[ln * 0.27, 0.0, 0.0]),
            
            # 6. Stepped down nosecone 1
            _cylinder_along_x(w * 0.35, ln * 0.12, mat_nose, position=[ln * 0.33, 0.0, 0.0]),
            _rim_along_x(w * 0.35, w * 0.02, mat_chrome, position=[ln * 0.39, 0.0, 0.0]),
            
            # 7. Stepped down nosecone 2 (black front collar protective tip)
            _cylinder_along_x(w * 0.24, ln * 0.1, mat_tip, position=[ln * 0.45, 0.0, 0.0]),
            
            # 8. Dual front lens elements recessed deep in the dark nose barrel
            {"shape": "sphere", "radius": w * 0.13, "scale": [0.15, 1.0, 1.0], "position": [ln * 0.5, 0.0, 0.0], "material": mat_lens},
            {"shape": "sphere", "radius": w * 0.1, "scale": [0.2, 1.0, 1.0], "position": [ln * 0.46, 0.0, 0.0], "material": mat_lens_inner},
        ]

        return {
            "shape": "group",
            "children": children,
            "post_at": [-ln * 0.42, -w * 0.6 * 1.12, 0.0],
        }


@dataclass
class SLM(Component):
    """Spatial light modulator with active-area and pixel metadata."""

    component_type = "SLM"
    active_width: float = 14.0
    active_height: float = 10.0
    pixel_pitch: float = 0.008
    resolution: tuple[int, int] = (1920, 1080)
    fill_factor: float = 0.92
    mode: str = "phase"

    def __init__(
        self,
        center=(0, 0),
        angle=0,
        active_width=14.0,
        active_height=10.0,
        pixel_pitch=0.008,
        resolution=(1920, 1080),
        fill_factor=0.92,
        mode="phase",
        **kwargs,
    ):
        self.active_width = active_width
        self.active_height = active_height
        self.pixel_pitch = pixel_pitch
        self.resolution = resolution
        self.fill_factor = fill_factor
        self.mode = mode
        self.phase_pattern = kwargs.get("phase_pattern", None)
        _set_common_free_space_fields(self, center, angle, kwargs, color="#223047", opacity=1.0, material_preset="glass", label="SLM")

    def geometry_2d(self) -> dict[str, Any]:
        frame_width = self.active_width + 2.0
        frame_height = self.active_height + 2.0
        children: list[dict[str, Any]] = [
            {"type": "rect", "cx": 0, "cy": 0, "w": frame_width, "h": frame_height, "fill": "#1f2937", "stroke": "#111827", "stroke_width": 0.08},
            {"type": "rect", "cx": 0, "cy": 0, "w": self.active_width, "h": self.active_height, "fill": "#334155", "stroke": "#93c5fd", "stroke_width": 0.08, "opacity": 0.95},
        ]
        for grid_index in range(1, 4):
            x_position = -self.active_width / 2.0 + self.active_width * grid_index / 4.0
            y_position = -self.active_height / 2.0 + self.active_height * grid_index / 4.0
            children.append({"type": "line", "x1": x_position, "y1": -self.active_height / 2.0, "x2": x_position, "y2": self.active_height / 2.0, "stroke": "#94a3b8", "stroke_width": 0.035, "opacity": 0.55})
            children.append({"type": "line", "x1": -self.active_width / 2.0, "y1": y_position, "x2": self.active_width / 2.0, "y2": y_position, "stroke": "#94a3b8", "stroke_width": 0.035, "opacity": 0.55})
        return {"type": "group", "children": children}

    def geometry_3d(self) -> dict[str, Any]:
        fw = self.active_width + 2.0
        fh = self.active_height + 2.0
        return {
            "shape": "group",
            "children": [
                # driver board / chassis behind the panel, up to the bezel's back face: inside it, they shared faces
                {"shape": "box", "width": 1.35, "height": fh, "depth": fw, "position": [-1.025, 0.0, 0.0], "material": {"color": "#16202c", "roughness": 0.5, "metalness": 0.2}},
                # bezel frame
                {"shape": "box", "width": 0.7, "height": fh, "depth": fw, "material": {"color": "#1f2937", "roughness": 0.42, "metalness": 0.22}},
                # active LCOS panel (emissive phase map, faces +x)
                {"shape": "box", "width": 0.16, "height": self.active_height, "depth": self.active_width, "position": [0.42, 0.0, 0.0], "material": {"color": "#334155", "roughness": 0.14, "metalness": 0.05, "emissive": "#1d4ed8", "emissiveIntensity": 0.12, "clearcoat": 0.5}},
                # cover glass
                {"shape": "box", "width": 0.05, "height": self.active_height * 1.02, "depth": self.active_width * 1.02, "position": [0.52, 0.0, 0.0], "material": {"color": "#bcd4ea", "opacity": 0.22, "transparent": True, "clearcoat": 0.8}},
                # ribbon cable + connector out the back of the chassis
                {"shape": "box", "width": 0.5, "height": fh * 0.3, "depth": fw * 0.3, "position": [-1.95, -fh * 0.2, 0.0], "material": {"color": "#3a3f47", "roughness": 0.6}},
            ],
        }

    def physics_metadata(self) -> dict[str, Any]:
        return _optical_metadata(
            "spatial_light_modulator",
            active_area=(self.active_width, self.active_height),
            pixel_pitch=self.pixel_pitch,
            resolution=self.resolution,
            fill_factor=self.fill_factor,
            mode=self.mode,
            phase_pattern=self.phase_pattern,
        )


SpatialLightModulator = SLM


@dataclass
class DMD(Component):
    """Digital micromirror device with active-area and tilt metadata."""

    component_type = "DMD"
    active_width: float = 14.0
    active_height: float = 10.0
    resolution: tuple[int, int] = (1024, 768)
    tilt_angle_deg: float = 12.0
    fill_factor: float = 0.9

    def __init__(self, center=(0, 0), angle=0, active_width=14.0, active_height=10.0, resolution=(1024, 768), tilt_angle_deg=12.0, fill_factor=0.9, **kwargs):
        self.active_width = active_width
        self.active_height = active_height
        self.resolution = resolution
        self.tilt_angle_deg = tilt_angle_deg
        self.fill_factor = fill_factor
        self.mirror_pitch_um = kwargs.get("mirror_pitch_um", 13.7)
        _set_common_free_space_fields(self, center, angle, kwargs, color="#334155", opacity=1.0, material_preset="steel", label=kwargs.get("label", "DMD"))

    def geometry_2d(self) -> dict[str, Any]:
        frame_w = self.active_width + 2.4
        frame_h = self.active_height + 2.4
        children = [
            {"type": "rect", "cx": 0.0, "cy": 0.0, "w": frame_w, "h": frame_h, "fill": "#111827", "stroke": "#020617", "stroke_width": 0.09},
            {"type": "rect", "cx": 0.0, "cy": 0.0, "w": self.active_width, "h": self.active_height, "fill": "#334155", "stroke": "#94a3b8", "stroke_width": 0.08},
        ]
        for idx in range(1, 5):
            x_pos = -self.active_width / 2.0 + self.active_width * idx / 5.0
            y_pos = -self.active_height / 2.0 + self.active_height * idx / 5.0
            children.append({"type": "line", "x1": x_pos, "y1": -self.active_height / 2.0, "x2": x_pos, "y2": self.active_height / 2.0, "stroke": "#64748b", "stroke_width": 0.03, "opacity": 0.65})
            children.append({"type": "line", "x1": -self.active_width / 2.0, "y1": y_pos, "x2": self.active_width / 2.0, "y2": y_pos, "stroke": "#64748b", "stroke_width": 0.03, "opacity": 0.65})
        return {"type": "group", "children": children}

    def geometry_3d(self) -> dict[str, Any]:
        fh, fw = self.active_height + 2.4, self.active_width + 2.4
        return {
            "shape": "group",
            "children": [
                # ceramic package body
                {"shape": "box", "width": 1.3, "height": fh, "depth": fw, "material": {"color": "#1a2230", "roughness": 0.42, "metalness": 0.2}},
                # micromirror array (the active surface): each mirror tilts by tilt_angle_deg, the array stays flat
                {"shape": "box", "width": 0.16, "height": self.active_height, "depth": self.active_width, "position": [0.7, 0.0, 0.0], "material": {"color": "#94a3b8", "roughness": 0.16, "metalness": 0.7, "clearcoat": 0.5}},
                # window frame on the package, round the tilted array, carrying the cover glass
                *[{"shape": "box", "width": 0.24, "height": h, "depth": d, "position": [0.75, y, z], "material": {"color": "#1a2230", "roughness": 0.42, "metalness": 0.2}}
                  for h, d, y, z in ((self.active_height * 1.06 + 1.0, 0.5, 0.0, self.active_width * 0.53 + 0.25),
                                     (self.active_height * 1.06 + 1.0, 0.5, 0.0, -self.active_width * 0.53 - 0.25),
                                     (0.5, self.active_width * 1.06, self.active_height * 0.53 + 0.25, 0.0),
                                     (0.5, self.active_width * 1.06, -self.active_height * 0.53 - 0.25, 0.0))],
                # sealed cover-glass window over the array
                {"shape": "box", "width": 0.06, "height": self.active_height * 1.06, "depth": self.active_width * 1.06, "position": [0.86, 0.0, 0.0], "material": {"color": "#bcd4ea", "opacity": 0.2, "transparent": True, "clearcoat": 0.8}},
                # driver board / heatsink behind
                {"shape": "box", "width": 0.7, "height": fh * 0.78, "depth": fw * 0.78, "position": [-0.85, 0.0, 0.0], "material": {"color": "#3a3f47", "roughness": 0.6, "metalness": 0.3}},
            ],
        }

    def ports(self) -> dict[str, Port]:
        return _through_ports(self.active_width + 2.4, self.active_height)

    def physics_metadata(self) -> dict[str, Any]:
        return _optical_metadata(
            "digital_micromirror_device",
            active_area=(self.active_width, self.active_height),
            resolution=self.resolution,
            tilt_angle_deg=self.tilt_angle_deg,
            fill_factor=self.fill_factor,
            mirror_pitch_um=self.mirror_pitch_um,
        )
