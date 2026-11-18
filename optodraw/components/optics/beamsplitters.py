"""Beamsplitters free-space optics."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from optodraw.core.component import Component
from optodraw.core.ports import Port
from optodraw.core.transform import Vec3

from ._shared import (
    _kinematic_mount,
    _KNOB_STEEL,
    _MOUNT_ALU,
    _MOUNT_BLACK,
    _beam_splitter_cube_ports,
    _cylinder_along_x,
    _optical_metadata,
    _ring_along_x,
    _set_common_free_space_fields,
    _transparent_material,
)


@dataclass
class BeamSplitter(Component):
    """A coated plate: a beam splitter at 45 degrees, a partial reflector at normal incidence (a recycling or input
    mirror, an output coupler), or a dichroic. ``transmission`` is the percent that passes; the rest reflects."""

    component_type = "BeamSplitter"
    aperture: float = 10.0
    dichroic: bool = False
    thickness: float = 0.7

    def __init__(self, center=(0, 0), angle=0, aperture=10.0, dichroic=False, thickness=0.7, transmission=50.0, cutoff_wavelength=None, **kwargs):
        self.aperture = aperture
        self.dichroic = dichroic
        self.thickness = thickness
        # Percent of power transmitted (rest reflects) — 50 = 50/50, 90 = 90/10.
        self.transmission = float(transmission)
        # Dichroic plates: edge wavelength (nm, longpass) used by physical tracing.
        self.cutoff_wavelength = cutoff_wavelength
        _set_common_free_space_fields(self, center, angle, kwargs, color="#88aacc" if dichroic else "#888888", opacity=0.7, material_preset="sio2")

    def physics_metadata(self) -> dict[str, Any]:
        # free_space domain so the ray engine includes it; flagged as a splitter so
        # tracing branches into transmitted + reflected beams.
        return _optical_metadata(
            "beam_splitter",
            aperture=self.aperture,
            thickness=self.thickness,
            dichroic=self.dichroic,
            splitter=True,
            reflective=True,
        )

    def symbol_1d(self) -> tuple[str, dict[str, Any]] | None:
        return ("platesplitter", {"kind": "dichroic"}) if self.dichroic else None

    def _coating(self) -> dict[str, Any]:
        """The coating on the front (-x) face. A plain one looks more like a mirror as the reflectance rises, but
        even a 97 % coating stays clearer than a full mirror's face; a dichroic one is amber, the colour the 1D
        and 2D views give it."""

        if self.dichroic:
            return {"color": "#e69f00", "opacity": 0.72, "transparent": True, "metalness": 0.35, "roughness": 0.08,
                    "clearcoat": 0.9}
        reflectance = min(max(1.0 - self.transmission / 100.0, 0.0), 1.0)
        # capped below a full mirror's opaque face, so the glass of a partial mirror always shows
        return {"color": "#eef6fb", "opacity": 0.15 + 0.45 * reflectance, "transparent": True,
                "metalness": 0.15 + 0.55 * reflectance, "roughness": 0.06, "clearcoat": 0.8}

    def geometry_2d(self) -> dict[str, Any]:
        w, th = self.aperture, self.thickness
        return {
            "type": "group",
            "children": [
                {"type": "rect", "cx": 0.0, "cy": 0.0, "w": th, "h": w, "fill": "#d6ecf7", "opacity": 0.85,
                 "stroke": "#7aa7bf", "stroke_width": 0.06},
                {"type": "line", "x1": -th / 2.0, "y1": -w * 0.48, "x2": -th / 2.0, "y2": w * 0.48,
                 "stroke": self._coating()["color"] if self.dichroic else "#9aa8b2", "stroke_width": max(th * 0.3, 0.12)},
            ],
        }

    def geometry_3d(self) -> dict[str, Any]:
        """A round glass plate in the bore of a kinematic mount; the bore and the open middle of the L back
        plate let the transmitted beam pass. The coating sits on the front face."""

        ap, th = self.aperture, self.thickness
        glass = {"color": "#d6ecf7", "opacity": 0.32, "transparent": True, "transmission": 0.6, "ior": 1.5,
                 "roughness": 0.03, "preset": "glass"}
        children = [
            _cylinder_along_x(ap * 0.5, th, glass),
            _cylinder_along_x(ap * 0.48, max(th * 0.06, 0.03), self._coating(), position=[-th / 2.0, 0.0, 0.0]),
            *_kinematic_mount(-th / 2.0, ap * 1.4, ap * 0.5),
        ]
        return {"shape": "group", "children": children}

    def beam_point(self, port: str) -> Vec3 | None:
        """Where a drawn beam meets the plate. A thin plate meets the beam at one point, on its coating at the
        centre, for all four beam ports; the face ports keep their own points."""

        return Vec3(0.0, 0.0, 0.0) if port in ("in", "refl", "trans", "tap") else None

    def ports(self) -> dict[str, Port]:
        """Beam-splitter ports consistent with the ray engine's 45deg reflection.

        Local orientations are chosen so that after the component rotation the
        three beams land on the real optical axes: at the conventional 45deg the
        pump enters from the left (``in``), passes straight through to the right
        (``trans``), and reflects 90deg downward (``refl``) — matching
        ``_reflect`` used by the tracer."""

        # The four diagonal local axes meet the plate at its x faces. Port
        # centers belong on those faces, not at an aperture-scaled distance
        # beyond a thin plate where connected beams would stop in empty space.
        face = min(max(self.thickness * 0.5, 0.0), max(self.aperture * 0.5, 0.0))
        half = face * math.sqrt(2.0)

        def _port(name: str, angle_deg: float) -> Port:
            rad = math.radians(angle_deg)
            return Port(
                name,
                Vec3(half * math.cos(rad), half * math.sin(rad), 0.0),
                orientation_deg=angle_deg,
                width=self.aperture,
                kind="free_space",
            )

        return {
            "in": _port("in", 135.0),     # +45deg -> world 180 (faces the incoming beam)
            "trans": _port("trans", -45.0),  # +45deg -> world 0   (straight through)
            "refl": _port("refl", -135.0),   # +45deg -> world -90 (90deg reflection)
            "tap": _port("tap", 45.0),       # +45deg -> world +90 (4th face: 2nd output /
            # interferometer recombination port, opposite the reflected arm)
            # at normal incidence (a recycling or input mirror, an output coupler): the two faces
            "front": Port("front", Vec3(-face, 0.0, 0.0), orientation_deg=180.0, width=self.aperture, kind="free_space"),
            "back": Port("back", Vec3(face, 0.0, 0.0), orientation_deg=0.0, width=self.aperture, kind="free_space"),
        }


class PartialMirror(BeamSplitter):
    """A partially reflecting mirror: a laser output coupler, the input or recycling mirror of a cavity. The coated
    plate of ``BeamSplitter`` used at normal incidence: the coated front face reflects, ``transmission`` percent
    passes out of the back (ports ``front`` and ``back``)."""

    component_type = "PartialMirror"

    def __init__(self, center=(0, 0), angle=0, aperture=10.0, thickness=0.7, transmission=10.0, **kwargs):
        kwargs.pop("dichroic", None)
        super().__init__(center, angle, aperture=aperture, dichroic=False, thickness=thickness,
                         transmission=transmission, **kwargs)

    def symbol_1d(self) -> tuple[str, dict[str, Any]]:
        return "partialmirror", {}


@dataclass
class PBS(Component):
    """Polarizing beam splitter cube."""

    component_type = "PBS"
    aperture: float = 10.0
    split_ratio: tuple[float, float] = (0.5, 0.5)

    def __init__(self, center=(0, 0), angle=0, aperture=10.0, split_ratio=(0.5, 0.5), **kwargs):
        self.aperture = aperture
        self.split_ratio = split_ratio
        self.polarization_selective = kwargs.get("polarization_selective", True)
        _set_common_free_space_fields(self, center, angle, kwargs, color="#8dc5ff", opacity=0.36, material_preset="glass")

    def geometry_2d(self) -> dict[str, Any]:
        edge = self.aperture * 0.72
        coating = "#ffffff" if self.polarization_selective else "#e6edf2"
        return {
            "type": "group",
            "children": [
                {"type": "rect", "cx": 0, "cy": 0, "w": edge, "h": edge, "fill": self.color, "opacity": self.opacity, "stroke": "#4a7fa8", "stroke_width": 0.1},
                {"type": "line", "x1": -edge / 2.0, "y1": -edge / 2.0, "x2": edge / 2.0, "y2": edge / 2.0, "stroke": coating, "stroke_width": 0.16, "opacity": 0.9},
                {"type": "line", "x1": -edge / 2.0, "y1": 0.0, "x2": edge / 2.0, "y2": 0.0, "stroke": "#2f5f82", "stroke_width": 0.05, "opacity": 0.45},
            ],
        }

    def geometry_3d(self) -> dict[str, Any]:
        edge = self.aperture * 0.72
        # Cube on a bracket-style beamsplitter mount (Polaris B05G silhouette): a machined
        # base platform with chamfered look, a short back wall off the beam axis, and two
        # steel cap screws. The renderer adds the post to the beam plane.
        return {
            "shape": "group",
            "children": [
                {"shape": "box", "width": edge, "height": edge, "depth": edge, "material": _transparent_material(self.color, self.opacity, self.material_preset)},
                {"shape": "box", "width": edge * 1.36, "height": edge * 0.035, "depth": edge * 1.36, "rotation": [0.0, 0.0, math.radians(45.0)], "material": {"color": "#ffffff", "opacity": 0.32, "transparent": True}},
                # base platform (two stacked plates read as a machined bracket)
                {"shape": "box", "width": edge * 1.3, "height": edge * 0.14, "depth": edge * 1.3, "position": [0.0, -edge * 0.58, 0.0], "material": _MOUNT_BLACK},
                {"shape": "box", "width": edge * 1.06, "height": edge * 0.1, "depth": edge * 1.06, "position": [0.0, -edge * 0.47, 0.0], "material": _MOUNT_ALU},
                # short back wall on the -z side (clear of the beam axis) with the B05G's
                # signature circular through-bore (a real hole)
                {"shape": "box", "width": edge * 1.3, "height": edge * 0.24, "depth": edge * 0.16, "position": [0.0, -edge * 0.46, -edge * 0.62], "material": _MOUNT_BLACK},
                _ring_along_x(edge * 0.28, edge * 0.5, edge * 0.16, _MOUNT_BLACK, rotation=[math.pi / 2.0, 0.0, 0.0], position=[0.0, edge * 0.02, -edge * 0.62]),
                {"shape": "box", "width": edge * 0.15, "height": edge * 0.56, "depth": edge * 0.16, "position": [-edge * 0.575, -edge * 0.06, -edge * 0.62], "material": _MOUNT_BLACK},
                {"shape": "box", "width": edge * 0.15, "height": edge * 0.56, "depth": edge * 0.16, "position": [edge * 0.575, -edge * 0.06, -edge * 0.62], "material": _MOUNT_BLACK},
                # steel cap screws on the base corners
                {"shape": "cylinder", "radius": edge * 0.06, "height": edge * 0.1, "position": [edge * 0.52, -edge * 0.49, edge * 0.52], "material": _KNOB_STEEL},
                {"shape": "cylinder", "radius": edge * 0.06, "height": edge * 0.1, "position": [-edge * 0.52, -edge * 0.49, edge * 0.52], "material": _KNOB_STEEL},
            ],
        }

    def ports(self) -> dict[str, Port]:
        return _beam_splitter_cube_ports(self.aperture)

    def physics_metadata(self) -> dict[str, Any]:
        return _optical_metadata("polarizing_beam_splitter", split_ratio=self.split_ratio, polarization_selective=self.polarization_selective)

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["aperture"] = self.aperture
        data["split_ratio"] = self.split_ratio
        data["polarization_selective"] = self.polarization_selective
        return data


@dataclass
class NonPolarizingBeamSplitter(PBS):
    """Non-polarizing beam splitter cube with explicit split-ratio metadata."""

    component_type = "NonPolarizingBeamSplitter"

    def __init__(self, center=(0, 0), angle=0, aperture=10.0, split_ratio=(0.5, 0.5), **kwargs):
        kwargs.setdefault("color", "#aeb8c2")
        kwargs.setdefault("polarization_selective", False)
        super().__init__(center=center, angle=angle, aperture=aperture, split_ratio=split_ratio, **kwargs)

    def physics_metadata(self) -> dict[str, Any]:
        return _optical_metadata("non_polarizing_beam_splitter", split_ratio=self.split_ratio, polarization_selective=False)

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["aperture"] = self.aperture
        data["split_ratio"] = self.split_ratio
        return data
