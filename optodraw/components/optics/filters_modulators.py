"""Filters modulators free-space optics."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from optodraw.core.component import Component
from optodraw.core.ports import Port
from optodraw.core.transform import Vec3

from ._shared import (
    _pass_band,
    _KNOB_STEEL,
    _MOUNT_ALU,
    _MOUNT_BLACK,
    _cylinder_along_x,
    _frame_holder,
    _optical_metadata,
    _ring_along_x,
    _round_optic_2d,
    _round_optic_3d,
    _set_common_free_space_fields,
    _through_ports,
    _rim_along_x,
    _transparent_material,
    _tube_clamp,
)


@dataclass
class Filter(Component):
    """An optical filter (thin slab)."""

    component_type = "Filter"
    aperture: float = 8.0
    thickness: float = 0.9

    def __init__(self, center=(0, 0), angle=0, aperture=8.0, thickness=0.9,
                 cutoff_wavelength=None, pass_band="longpass", **kwargs):
        self.aperture = aperture
        self.thickness = thickness
        # The edge of the coating, in nm. Left unset, the filter is plain glass
        # in the drawing: light passes. Set it and tracing enforces it, which is
        # the point of putting a filter in the path in the first place.
        self.cutoff_wavelength = cutoff_wavelength
        self.pass_band = _pass_band(pass_band)
        _set_common_free_space_fields(self, center, angle, kwargs, color="#ff4444", opacity=0.5, material_preset="glass")

    def physics_metadata(self) -> dict[str, Any]:
        return _optical_metadata(
            "filter",
            aperture=self.aperture,
            thickness=self.thickness,
            cutoff_wavelength=self.cutoff_wavelength,
            pass_band=self.pass_band,
            material_preset=self.material_preset,
        )

    def optical_interfaces(self):
        """Pass in band, stop out of band — nothing at all without an edge.

        A filter differs from a dichroic in where the rejected light goes: a
        dichroic sends it off at 90 degrees, a filter absorbs it. Rays that meet
        the band carry straight on."""

        if not self.cutoff_wavelength:
            return []
        from optodraw.core.raytrace import OpticalInterface

        half = self.aperture / 2.0
        return [OpticalInterface(
            p1=(0.0, -half), p2=(0.0, half), kind="filter",
            cutoff_nm=float(self.cutoff_wavelength), pass_type=self.pass_band, name="coating",
        )]

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data.update(
            aperture=self.aperture, thickness=self.thickness,
            cutoff_wavelength=self.cutoff_wavelength, pass_band=self.pass_band,
        )
        return data

    def ports(self) -> dict[str, Port]:
        """Collinear input/output ports on the optical axis."""

        return _through_ports(self.thickness, self.aperture)

    def geometry_2d(self) -> dict[str, Any]:
        return {
            "type": "group",
            "children": [
                *_round_optic_2d(self.aperture, self.color, self.opacity, stroke="#8b2c2c", label_line="#ffd1d1"),
                {"type": "rect", "cx": 0.0, "cy": -self.aperture * 0.57, "w": self.aperture * 0.45, "h": self.aperture * 0.14, "fill": "#474d55", "stroke": "#232931", "stroke_width": 0.06, "opacity": 0.9},
            ],
        }

    def geometry_3d(self) -> dict[str, Any]:
        return {
            "shape": "group",
            "children": [
                *_round_optic_3d(self.aperture, self.thickness, self.color, self.opacity, self.material_preset, frame_color="#3f4650"),
                {"shape": "box", "width": self.aperture * 0.5, "height": self.thickness * 0.75, "depth": self.aperture * 0.18, "position": [0.0, -self.aperture * 0.56, 0.0], "material": {"color": "#495057", "preset": "steel"}},
            ],
        }


@dataclass
class NDFilter(Filter):
    """A neutral density filter: it passes every wavelength and takes the same share of each. It keeps
    ``10 ** -optical_density`` of the power, so an open ND wheel is ``optical_density=0``."""

    component_type = "NDFilter"
    optical_density: float = 1.0

    def __init__(self, center=(0, 0), angle=0, aperture=8.0, thickness=0.9, optical_density=1.0, **kwargs):
        if float(optical_density) < 0.0:
            raise ValueError(f"optical_density must be 0 or more, got {optical_density!r}")
        self.optical_density = float(optical_density)
        kwargs.setdefault("color", "#6b7280")
        kwargs.setdefault("opacity", 0.6)
        super().__init__(center, angle, aperture, thickness, **kwargs)

    def physics_metadata(self) -> dict[str, Any]:
        return _optical_metadata("nd_filter", aperture=self.aperture, thickness=self.thickness,
                                 optical_density=self.optical_density, material_preset=self.material_preset)

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data.update(optical_density=self.optical_density)
        return data

    def geometry_2d(self) -> dict[str, Any]:
        return {"type": "group", "children": _round_optic_2d(self.aperture, self.color, self.opacity,
                                                             stroke="#3f4650", label_line="#d1d5db")}


@dataclass
class Grating(Component):
    """A diffraction grating (mirror-like with dashed face lines)."""

    component_type = "Grating"
    aperture: float = 10.0
    pitch: float = 1.0
    thickness: float = 1.0

    def __init__(self, center=(0, 0), angle=0, aperture=10.0, pitch=1.0, thickness=1.0, **kwargs):
        self.aperture = aperture
        self.pitch = pitch
        self.thickness = thickness
        _set_common_free_space_fields(self, center, angle, kwargs, color="#444444", opacity=0.9, material_preset="titanium")

    def physics_metadata(self) -> dict[str, Any]:
        return _optical_metadata(
            "grating",
            aperture=self.aperture,
            pitch=self.pitch,
            thickness=self.thickness,
            material_preset=self.material_preset,
        )

    def geometry_2d(self) -> dict[str, Any]:
        children: list[dict[str, Any]] = [
            {"type": "rect", "cx": -self.thickness * 0.18, "cy": 0, "w": self.thickness * 1.2, "h": self.aperture, "fill": "#30363d", "stroke": "#222", "stroke_width": 0.08, "opacity": self.opacity},
            {"type": "rect", "cx": self.thickness * 0.48, "cy": 0, "w": self.thickness * 0.12, "h": self.aperture * 0.94, "fill": self.color, "stroke": "#cfd7df", "stroke_width": 0.05, "opacity": 0.95},
        ]
        groove_count = max(3, int(self.aperture / max(self.pitch, 0.2)))
        groove_step = self.aperture / groove_count
        for index in range(groove_count):
            y = -self.aperture / 2 + groove_step * (index + 0.5)
            children.append({"type": "line", "x1": self.thickness * 0.48, "y1": y, "x2": self.thickness * 0.92, "y2": y + groove_step * 0.45, "stroke": "#dbe4ec", "stroke_width": 0.08, "opacity": 0.9})
        children.append({"type": "rect", "cx": -self.thickness * 0.55, "cy": -self.aperture * 0.56, "w": self.thickness * 1.4, "h": self.aperture * 0.12, "fill": "#454b53", "stroke": "#222", "stroke_width": 0.06})
        return {"type": "group", "children": children}

    def geometry_3d(self) -> dict[str, Any]:
        # A ruled grating: a dark blank with a metal ruled face toward +x, fine low-contrast rulings (the true
        # pitch is far too fine to draw, so the count is fixed), in a rectangular holder.
        a, t = self.aperture, self.thickness
        children: list[dict[str, Any]] = [
            {"shape": "box", "width": t * 1.15, "height": a, "depth": a * 0.82, "position": [-t * 0.12, 0.0, 0.0],
             "material": {"color": "#30363d", "metalness": 0.5, "roughness": 0.38, "preset": self.material_preset}},
            {"shape": "box", "width": t * 0.06, "height": a * 0.96, "depth": a * 0.78, "position": [t * 0.485, 0.0, 0.0],
             "material": {"color": "#c9d3dd", "metalness": 0.9, "roughness": 0.14, "clearcoat": 0.55}},
        ]
        count = 40
        step = a * 0.96 / count
        for index in range(count):
            children.append({"shape": "box", "role": "groove", "width": t * 0.04, "height": step * 0.35, "depth": a * 0.78,
                             "position": [t * 0.535, -a * 0.48 + step * (index + 0.5), 0.0],
                             "material": {"color": "#8b97a5", "metalness": 0.9, "roughness": 0.25}})
        children += _frame_holder(a * 0.82, a, t * 1.3)
        return {"shape": "group", "children": children}


@dataclass
class AOM(Component):
    """Acousto-optic modulator with center-frequency and efficiency metadata."""

    component_type = "AOM"
    # The optical ports mark the package faces; keep their fitted separation.
    _art_scale_from_ports = True
    aperture: float = 7.0
    interaction_length: float = 11.0
    center_frequency_mhz: float = 80.0
    diffraction_efficiency: float = 0.75

    def __init__(self, center=(0, 0), angle=0, aperture=7.0, interaction_length=11.0, center_frequency_mhz=80.0, diffraction_efficiency=0.75, **kwargs):
        self.aperture = aperture
        self.interaction_length = interaction_length
        self.center_frequency_mhz = center_frequency_mhz
        self.diffraction_efficiency = diffraction_efficiency
        self.acoustic_velocity_m_per_s = kwargs.get("acoustic_velocity_m_per_s", 4200.0)
        _set_common_free_space_fields(self, center, angle, kwargs, color="#93c5fd", opacity=0.62, material_preset="glass", label=kwargs.get("label", "AOM"))

    def geometry_2d(self) -> dict[str, Any]:
        half = self.interaction_length / 2.0
        return {
            "type": "group",
            "children": [
                {"type": "rect", "cx": 0.0, "cy": 0.0, "w": self.interaction_length, "h": self.aperture, "fill": self.color, "stroke": "#1d4ed8", "stroke_width": 0.08, "opacity": self.opacity},
                {"type": "rect", "cx": -half * 0.78, "cy": 0.0, "w": self.interaction_length * 0.18, "h": self.aperture * 0.7, "fill": "#374151", "stroke": "#111827", "stroke_width": 0.06},
                {"type": "line", "x1": -half, "y1": 0.0, "x2": half, "y2": 0.0, "stroke": "#eff6ff", "stroke_width": 0.14, "opacity": 0.72},
                {"type": "line", "x1": -half * 0.12, "y1": 0.0, "x2": half * 0.58, "y2": -self.aperture * 0.32, "stroke": "#fbbf24", "stroke_width": 0.1, "opacity": 0.8},
            ],
        }

    def geometry_3d(self) -> dict[str, Any]:
        L, a = self.interaction_length, self.aperture
        # Closed AOM package (Isomet 1205C silhouette): a machined rectangular body with
        # small round optical windows on the beam faces, a top SMA drive connector, and a
        # mounting foot — the crystal is inside the housing, as in the real device.
        return {
            "shape": "group",
            "children": [
                # machined body
                {"shape": "box", "width": L * 1.08, "height": a * 0.9, "depth": a * 1.25, "material": {"color": "#3a4048", "metalness": 0.6, "roughness": 0.35, "preset": "steel"}},
                # chamfered top plate
                {"shape": "box", "width": L * 0.96, "height": a * 0.08, "depth": a * 1.1, "position": [0.0, a * 0.49, 0.0], "material": _MOUNT_ALU},
                # round optical windows (slightly proud) on the ±x beam faces
                _cylinder_along_x(a * 0.24, L * 1.14, {**_transparent_material(self.color, 0.85, "glass"), "transmission": 0.5, "ior": 1.48}),
                _rim_along_x(a * 0.27, a * 0.045, _MOUNT_ALU, position=[-L * 0.57, 0.0, 0.0]),
                _rim_along_x(a * 0.27, a * 0.045, _MOUNT_ALU, position=[L * 0.57, 0.0, 0.0]),
                # SMA drive connector on top (brass barrel + steel nut)
                {"shape": "cylinder", "radius": a * 0.11, "height": a * 0.34, "position": [-L * 0.3, a * 0.6234, 0.0], "material": {"color": "#b8a24a", "metalness": 0.72, "roughness": 0.28, "preset": "brass"}},
                {"shape": "cylinder", "radius": a * 0.16, "height": a * 0.1, "position": [-L * 0.3, a * 0.52, 0.0], "material": _KNOB_STEEL},
                # mounting foot with two screw bosses
                {"shape": "box", "width": L * 1.08, "height": a * 0.16, "depth": a * 1.45, "position": [0.0, -a * 0.53, 0.0], "material": _MOUNT_BLACK},
                {"shape": "cylinder", "radius": a * 0.09, "height": a * 0.05, "position": [-L * 0.42, -a * 0.44, a * 0.58], "material": _KNOB_STEEL},
                {"shape": "cylinder", "radius": a * 0.09, "height": a * 0.05, "position": [L * 0.42, -a * 0.44, -a * 0.58], "material": _KNOB_STEEL},
            ],
        }

    def ports(self) -> dict[str, Port]:
        return _through_ports(self.interaction_length, self.aperture)

    def physics_metadata(self) -> dict[str, Any]:
        return _optical_metadata(
            "acousto_optic_modulator",
            center_frequency_mhz=self.center_frequency_mhz,
            diffraction_efficiency=self.diffraction_efficiency,
            acoustic_velocity_m_per_s=self.acoustic_velocity_m_per_s,
        )


@dataclass
class EOM(Component):
    """Electro-optic modulator crystal with Vpi and bandwidth metadata."""

    component_type = "EOM"
    # The optical ports mark the crystal faces and the drive lead ends on ``rf``: keep the fitted scale. Sized to
    # the aperture, the art covered the first half of the crystal and left a gap in the beam.
    _art_scale_from_ports = True
    LEAD = 0.32 / 0.72         # the pic od eom: the drive lead ends 0.32 above the axis of a crystal 0.72 long
    aperture: float = 6.0
    crystal_length: float = 13.0
    half_wave_voltage_v: float = 4.8
    bandwidth_ghz: float = 25.0

    def __init__(self, center=(0, 0), angle=0, aperture=6.0, crystal_length=13.0, half_wave_voltage_v=4.8, bandwidth_ghz=25.0, **kwargs):
        self.aperture = aperture
        self.crystal_length = crystal_length
        self.half_wave_voltage_v = half_wave_voltage_v
        self.bandwidth_ghz = bandwidth_ghz
        self.modulation_axis = kwargs.get("modulation_axis", "z")
        _set_common_free_space_fields(self, center, angle, kwargs, color="#c4b5fd", opacity=0.58, material_preset="glass", label=kwargs.get("label", "EOM"))

    def geometry_2d(self) -> dict[str, Any]:
        return {
            "type": "group",
            "children": [
                {"type": "rect", "cx": 0.0, "cy": 0.0, "w": self.crystal_length, "h": self.aperture, "fill": self.color, "stroke": "#6d28d9", "stroke_width": 0.08, "opacity": self.opacity},
                {"type": "line", "x1": -self.crystal_length * 0.34, "y1": -self.aperture * 0.28, "x2": self.crystal_length * 0.34, "y2": self.aperture * 0.28, "stroke": "#ddd6fe", "stroke_width": 0.11, "opacity": 0.9},
                {"type": "line", "x1": -self.crystal_length * 0.34, "y1": self.aperture * 0.28, "x2": self.crystal_length * 0.34, "y2": -self.aperture * 0.28, "stroke": "#ddd6fe", "stroke_width": 0.11, "opacity": 0.9},
                {"type": "rect", "cx": 0.0, "cy": self.aperture * 0.56, "w": self.crystal_length * 0.78, "h": self.aperture * 0.18, "fill": "#374151", "stroke": "#111827", "stroke_width": 0.05},
            ],
        }

    def geometry_3d(self) -> dict[str, Any]:
        # A housed electro-optic modulator: the crystal sits inside a brushed-aluminium cylinder, behind a
        # window in a black end cap at each end; the RF drive enters through an SMA connector on top; a clamp
        # with a boss holds it on its post. It was a bare purple crystal between two electrode plates.
        L, a = self.crystal_length, self.aperture
        r = a * 0.75
        alu = {"color": "#c3c8ce", "metalness": 0.75, "roughness": 0.3, "preset": "aluminum"}
        crystal = {"color": "#6d5bb5", "metalness": 0.2, "roughness": 0.15, "clearcoat": 0.8}
        clamp, post_at = _tube_clamp(r, L * 0.18)
        children: list[dict[str, Any]] = [
            {**_cylinder_along_x(r, L * 0.88, alu), "role": "housing"},
            {"shape": "cylinder", "role": "sma", "radius": a * 0.1, "height": a * 0.3, "position": [0.0, r + a * 0.15, 0.0], "material": {"color": "#d4af37", "metalness": 1.0, "roughness": 0.25}},
            {"shape": "cylinder", "radius": a * 0.16, "height": a * 0.08, "position": [0.0, r + a * 0.02, 0.0], "material": {"color": "#d4af37", "metalness": 1.0, "roughness": 0.25}},
            *clamp,
        ]
        for side in (-1.0, 1.0):
            end_x = side * (L * 0.44 + L * 0.03)
            children += [
                _ring_along_x(a * 0.2, r * 1.02, L * 0.06, _MOUNT_BLACK, x=end_x),
                {**_cylinder_along_x(a * 0.19, L * 0.01, {"color": "#bcd4ea", "opacity": 0.35, "transparent": True, "clearcoat": 0.9}, position=[end_x, 0.0, 0.0]), "role": "window"},
                _cylinder_along_x(a * 0.17, L * 0.02, crystal, position=[side * L * 0.4, 0.0, 0.0]),
            ]
        return {"shape": "group", "children": children, "post_at": post_at}

    def ports(self) -> dict[str, Port]:
        ports = _through_ports(self.crystal_length, self.aperture)
        ports["rf"] = Port("rf", Vec3(0.0, self.crystal_length * self.LEAD, 0.0), orientation_deg=90.0, width=1.0,
                           kind="electrical")                      # the drive: a cable from the oscillator
        return ports

    def physics_metadata(self) -> dict[str, Any]:
        return _optical_metadata(
            "electro_optic_modulator",
            half_wave_voltage_v=self.half_wave_voltage_v,
            bandwidth_ghz=self.bandwidth_ghz,
            modulation_axis=self.modulation_axis,
        )


@dataclass
class NonlinearCrystal(Component):
    """A nonlinear crystal on the beam: BBO or LBO for a harmonic, BBO or PPKTP for photon pairs, a CaF2 or
    sapphire plate for white light. Light runs along local +x from ``in`` to ``out``.

    ``poled`` draws the domains of a periodically poled chip (PPKTP, PPLN), 12 long unless ``length`` says
    otherwise, and holds it in an oven, as a poled crystal is phase matched by its temperature; a bulk crystal
    is 5 long and sits in a black ring holder. ``material``
    and ``process`` are what the figure names. The animation passes the light: it does not convert the colour.
    """

    component_type = "NonlinearCrystal"
    length: float = 5.0
    aperture: float = 5.0
    material: str = "BBO"
    process: str = "SHG"
    poled: bool = False
    # One plan for the 2D art, the 3D solids and the pic `od crystal` in od-freespace.tex: the crystal is HEIGHT
    # of the aperture high, the optic axis runs corner to corner, a poled chip shows DOMAINS stripes. The pic
    # keeps the default shapes (5 by 4, 12 by 4) and stretches with the length. A schematic, not a data sheet.
    HEIGHT = 0.8
    DOMAINS = 8
    POLED_LENGTH = 12.0
    _art_scale_from_ports = True        # the art spans in to out: sized to the box, a poled chip stopped 3.5 short of out

    def __init__(self, center=(0, 0), angle=0, length=None, aperture=5.0, material="BBO", process="SHG",
                 poled=False, **kwargs):
        self.length = float(length if length is not None else (self.POLED_LENGTH if poled else 5.0))
        self.aperture = float(aperture)
        self.material = str(material)
        self.process = str(process)
        self.poled = bool(poled)
        _set_common_free_space_fields(self, center, angle, kwargs, color="#f2dc8c", opacity=0.6, material_preset="glass",
                                      label=kwargs.get("label", self.material))

    def symbol_1d(self) -> tuple[str, dict[str, Any]] | None:
        return ("crystal", {"kind": "poled"}) if self.poled else None

    def ports(self) -> dict[str, Port]:
        return _through_ports(self.length, self.aperture * self.HEIGHT)

    def geometry_2d(self) -> dict[str, Any]:
        half_l, half_h = self.length / 2.0, self.aperture * self.HEIGHT / 2.0
        children: list[dict[str, Any]] = [
            {"type": "rect", "cx": 0.0, "cy": 0.0, "w": self.length, "h": 2.0 * half_h, "fill": self.color,
             "opacity": self.opacity, "stroke": "#9a7a1f", "stroke_width": 0.1},
        ]
        if self.poled:
            step = self.length / self.DOMAINS
            children += [{"type": "rect", "cx": -half_l + step * (k + 0.5), "cy": 0.0, "w": step, "h": 2.0 * half_h,
                          "fill": "#b8962e", "opacity": 0.55} for k in range(0, self.DOMAINS, 2)]
        else:
            children.append({"type": "line", "x1": -half_l, "y1": -half_h, "x2": half_l, "y2": half_h,
                             "stroke": "#9a7a1f", "stroke_width": 0.08})
        return {"type": "group", "children": children}

    def geometry_3d(self) -> dict[str, Any]:
        L, a = self.length, self.aperture
        h = a * self.HEIGHT
        crystal = {**_transparent_material(self.color, self.opacity, "glass"), "clearcoat": 0.8, "role": "crystal"}
        children: list[dict[str, Any]] = [
            {"shape": "box", "role": "crystal", "width": L, "height": h, "depth": h, "material": crystal},
        ]
        if self.poled:
            # an oven: a block under the crystal and two walls beside it, so it is held at its matching temperature
            wall, base = h * 0.3, h * 0.5
            children += [
                {"shape": "box", "role": "oven", "width": L * 1.2, "height": base, "depth": h + 2.0 * wall,
                 "position": [0.0, -(h + base) / 2.0, 0.0], "material": _MOUNT_BLACK},
                *[{"shape": "box", "role": "oven", "width": L * 1.2, "height": h, "depth": wall,
                   "position": [0.0, 0.0, side * (h + wall) / 2.0], "material": _MOUNT_BLACK} for side in (-1.0, 1.0)],
            ]
            return {"shape": "group", "children": children, "post_at": [0.0, -h / 2.0 - base, 0.0]}
        # a bulk crystal in a black ring holder: the ring round it and a boss for the post under the ring
        ring = h * 0.75
        children += [
            {**_ring_along_x(h * 0.71, ring + h * 0.25, L * 1.1, _MOUNT_BLACK), "role": "holder"},
            {"shape": "box", "role": "boss", "width": L * 0.9, "height": h * 0.2, "depth": h * 0.5,
             "position": [0.0, -(ring + h * 0.25) - h * 0.08, 0.0], "material": _MOUNT_BLACK},
        ]
        return {"shape": "group", "children": children, "post_at": [0.0, -(ring + h * 0.25) - h * 0.18, 0.0]}

    def physics_metadata(self) -> dict[str, Any]:
        return _optical_metadata("nonlinear_crystal", material=self.material, process=self.process, poled=self.poled)


@dataclass
class OpticalIsolator(Component):
    """Free-space optical (Faraday) isolator — one-way light valve (IO-3D silhouette):
    a fat magnet barrel with brushed polarizer caps at both ends."""

    component_type = "OpticalIsolator"
    aperture: float = 6.0
    length: float = 12.0
    isolation_db: float = 35.0

    def __init__(self, center=(0, 0), angle=0, aperture=6.0, length=12.0, isolation_db=35.0, **kwargs):
        self.aperture = aperture
        self.length = length
        self.isolation_db = isolation_db
        _set_common_free_space_fields(self, center, angle, kwargs, color="#30353c", opacity=1.0, material_preset="steel", label=kwargs.get("label", "Isolator"))

    def geometry_2d(self) -> dict[str, Any]:
        L, a = self.length, self.aperture
        return {
            "type": "group",
            "children": [
                {"type": "rect", "cx": 0, "cy": 0, "w": L * 0.72, "h": a * 1.15, "fill": self.color, "stroke": "#1b1f24", "stroke_width": 0.1},
                {"type": "rect", "cx": -L * 0.42, "cy": 0, "w": L * 0.12, "h": a * 0.9, "fill": "#c6cbd1", "stroke": "#5b6570", "stroke_width": 0.06},
                {"type": "rect", "cx": L * 0.42, "cy": 0, "w": L * 0.12, "h": a * 0.9, "fill": "#c6cbd1", "stroke": "#5b6570", "stroke_width": 0.06},
                # one-way arrow (the isolator symbol)
                {"type": "line", "x1": -L * 0.22, "y1": 0.0, "x2": L * 0.18, "y2": 0.0, "stroke": "#f8fafc", "stroke_width": 0.22, "opacity": 0.95},
                {"type": "polygon", "points": [(L * 0.18, a * 0.18), (L * 0.3, 0.0), (L * 0.18, -a * 0.18)], "fill": "#f8fafc", "opacity": 0.95},
            ],
        }

    def geometry_3d(self) -> dict[str, Any]:
        L, a = self.length, self.aperture
        return {
            "shape": "group",
            "children": [
                # magnet barrel
                _ring_along_x(a * 0.22, a * 0.78, L * 0.7, {"color": self.color, "metalness": 0.55, "roughness": 0.4, "preset": self.material_preset}),
                # clamp ring round the barrel with a boss for the post
                *_tube_clamp(a * 0.78, L * 0.16)[0],
                # red pass-direction band (common on commercial isolators)
                _rim_along_x(a * 0.78, a * 0.06, {"color": "#b3373c", "metalness": 0.4, "roughness": 0.45}, position=[L * 0.2, 0.0, 0.0]),
                # input / output polarizer caps with REAL entrance bores
                _ring_along_x(a * 0.22, a * 0.58, L * 0.14, _MOUNT_ALU, x=-L * 0.42),
                _ring_along_x(a * 0.22, a * 0.58, L * 0.14, _MOUNT_ALU, x=L * 0.42),
                # dark interior tube seen through the bores (open-ended, recessed)
                _ring_along_x(a * 0.2, a * 0.22, L * 0.86, {"color": "#0d0e12", "metalness": 0.7, "roughness": 0.3}),
                # the polarizer element visible inside, set back from the entrance
                _cylinder_along_x(a * 0.21, L * 0.02, {"color": "#20262e", "metalness": 0.3, "roughness": 0.25, "clearcoat": 0.6}, position=[-L * 0.28, 0.0, 0.0]),
            ],
        }

    def ports(self) -> dict[str, Port]:
        return _through_ports(self.length, self.aperture)

    def physics_metadata(self) -> dict[str, Any]:
        return _optical_metadata("optical_isolator", isolation_db=self.isolation_db, aperture=self.aperture)

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["aperture"] = self.aperture
        data["length"] = self.length
        data["isolation_db"] = self.isolation_db
        return data


@dataclass
class OpticalChopper(Component):
    """Rotating slotted-wheel optical chopper — periodically blocks the beam for lock-in
    detection. The beam passes through the open slots of the spinning blade. The default wheel is drawn a little
    taller than a lens: a figure is compact, not to scale."""

    component_type = "OpticalChopper"
    wheel_diameter: float = 12.0
    blades: int = 6

    def __init__(self, center=(0, 0), angle=0, wheel_diameter=12.0, blades=6, **kwargs):
        self.wheel_diameter = wheel_diameter
        self.blades = max(int(blades), 2)
        _set_common_free_space_fields(self, center, angle, kwargs, color="#2b3037", opacity=1.0, material_preset="steel", label=kwargs.get("label", "Chopper"))

    def geometry_2d(self) -> dict[str, Any]:
        r = self.wheel_diameter * 0.5
        children: list[dict[str, Any]] = [{"type": "circle", "cx": 0, "cy": 0, "r": r, "fill": self.color, "stroke": "#14171b", "stroke_width": 0.1, "opacity": 0.9}]
        # open slots (white sectors) between the blades
        for k in range(self.blades):
            a0 = 2 * math.pi * k / self.blades
            a1 = a0 + math.pi / self.blades
            pts = [(0, 0), (math.cos(a0) * r * 0.96, math.sin(a0) * r * 0.96), (math.cos((a0 + a1) / 2) * r * 0.96, math.sin((a0 + a1) / 2) * r * 0.96), (math.cos(a1) * r * 0.96, math.sin(a1) * r * 0.96)]
            children.append({"type": "polygon", "points": pts, "fill": "#f4f7fa", "opacity": 0.9})
        children.append({"type": "circle", "cx": 0, "cy": 0, "r": r * 0.16, "fill": "#4b5560"})
        return {"type": "group", "children": children}

    def geometry_3d(self) -> dict[str, Any]:
        # A slotted wheel on its motor head. The hub sits below the beam, so the beam crosses the ring of slots
        # near the rim (a slot is centred on the beam); the head stands behind the wheel and reaches below its
        # rim, so the post carries the head and never touches the wheel.
        r = self.wheel_diameter * 0.5
        hub_y = -r * 0.72
        plate = max(r * 0.012, 0.12)
        blade_mat = {"color": self.color, "metalness": 0.5, "roughness": 0.45, "preset": "steel"}
        children: list[dict[str, Any]] = [
            _cylinder_along_x(r * 0.47, plate, blade_mat, position=[0.0, hub_y, 0.0]),
            {**_cylinder_along_x(r * 0.12, r * 0.06, _KNOB_STEEL, position=[-plate / 2.0 - r * 0.03, hub_y, 0.0]), "role": "hub"},
            _cylinder_along_x(r * 0.06, plate / 2.0 + r * 0.03, _KNOB_STEEL, position=[(plate / 2.0 + r * 0.03) / 2.0, hub_y, 0.0]),
            {"shape": "box", "width": r * 0.28, "height": r * 1.35, "depth": r * 0.6,
             "position": [plate / 2.0 + r * 0.16, hub_y - r * 0.375, 0.0], "material": _MOUNT_BLACK},
        ]
        n = self.blades
        for k in range(n):
            a0 = 2.0 * math.pi * k / n + math.pi / (2.0 * n)
            arc = [a0 + (math.pi / n) * i / 8.0 for i in range(9)]
            points = [(r * math.cos(a), r * math.sin(a)) for a in arc]
            points += [(r * 0.45 * math.cos(a), r * 0.45 * math.sin(a)) for a in reversed(arc)]
            children.append({"shape": "extruded_polygon", "role": "tooth", "points": points, "height": plate,
                             "position": [plate / 2.0, hub_y, 0.0], "rotation": [0.0, 0.0, math.pi / 2.0], "material": blade_mat})
        return {"shape": "group", "children": children}

    def ports(self) -> dict[str, Port]:
        return _through_ports(2.0, self.wheel_diameter * 0.3)

    def physics_metadata(self) -> dict[str, Any]:
        return _optical_metadata("optical_chopper", wheel_diameter=self.wheel_diameter, blades=self.blades)

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["wheel_diameter"] = self.wheel_diameter
        data["blades"] = self.blades
        return data


@dataclass
class FaradayRotator(Component):
    """A Faraday rotator: a terbium gallium garnet (TGG) rod in the bore of a ring magnet. Light runs along local
    +x from ``in`` to ``out``.

    The rod turns the plane of polarization by ``rotation_deg`` in the sense the magnet sets, whichever way the light
    runs, so a second pass adds to the first (90 degrees for two passes at 45) where a wave plate's second pass
    undoes it. With a polarizer at each end it is an ``OpticalIsolator``; with one polarizer beside it (a ``PBS``)
    it sends a returning beam out of the side, as where squeezed light enters an interferometer.
    """

    component_type = "FaradayRotator"
    length: float = 10.0
    aperture: float = 5.0
    rotation_deg: float = 45.0
    # One plan for the 2D art, the 3D solids and the pic `od faraday` in od-freespace.tex, in units of the length:
    # the magnet is BODY high (the barrel's diameter) and the rod ROD high in its bore. Schematic proportions, near a
    # 5 mm rotator for 1064 nm (a barrel about 40 mm across and 60 mm long).
    BODY = 0.56
    ROD = 0.18

    def __init__(self, center=(0, 0), angle=0, length=10.0, aperture=5.0, rotation_deg=45.0, **kwargs):
        self.length = float(length)
        self.aperture = float(aperture)
        self.rotation_deg = float(rotation_deg)
        _set_common_free_space_fields(self, center, angle, kwargs, color="#2f3439", opacity=1.0, material_preset="steel",
                                      label=kwargs.get("label", "Faraday rotator"))

    def ports(self) -> dict[str, Port]:
        return _through_ports(self.length, self.aperture)

    def geometry_2d(self) -> dict[str, Any]:
        L = self.length
        return {"type": "group", "children": [
            {"type": "rect", "cx": 0.0, "cy": 0.0, "w": L, "h": L * self.BODY, "fill": "#cbd5e1", "stroke": "#64748b",
             "stroke_width": 0.1},
            {"type": "rect", "cx": 0.0, "cy": 0.0, "w": L, "h": L * self.ROD, "fill": "#d9ecf7", "stroke": "#7fb2cf",
             "stroke_width": 0.06},
        ]}

    def geometry_3d(self) -> dict[str, Any]:
        L = self.length
        outer, rod = L * self.BODY / 2.0, L * self.ROD / 2.0
        bore = rod * 1.015                                   # a hair wider than the rod: equal walls flicker
        magnet = {"color": self.color, "metalness": 0.5, "roughness": 0.4, "preset": "steel"}
        crystal = {**_transparent_material("#e8f0d8", 0.55, "glass"), "clearcoat": 0.6}
        clamp, post_at = _tube_clamp(outer * 1.015, L * 0.3)
        return {"shape": "group", "post_at": post_at, "children": [
            {**_ring_along_x(bore, outer, L * 0.84, magnet), "role": "magnet"},
            *[{**_ring_along_x(bore, outer * 0.86, L * 0.08, _MOUNT_ALU, x=side * L * 0.46), "role": "end cap"}
              for side in (-1.0, 1.0)],
            {**_cylinder_along_x(rod, L * 0.9, crystal), "role": "rod"},
            *clamp,
        ]}

    def physics_metadata(self) -> dict[str, Any]:
        return _optical_metadata("faraday_rotator", rotation_deg=self.rotation_deg, aperture=self.aperture)
