"""Lenses free-space optics."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from optodraw.core.component import Component
from optodraw.core.ports import Port
from optodraw.core.transform import Vec3

from ._shared import (
    _KNOB_STEEL,
    _MOUNT_ALU,
    _MOUNT_BLACK,
    _cylinder_along_x,
    _frame_holder,
    _optical_metadata,
    _post_boss,
    _ring_along_x,
    _set_common_free_space_fields,
    _signed_nonzero,
    _square_plate,
    _through_ports,
    _rim_along_x,
    _transparent_material,
    _tube_clamp,
)


@dataclass
class Lens(Component):
    """A thin lens (biconvex profile in 2D, cylinder+sphere in 3D).

    Parameters
    ----------
    center : tuple
        (x, y) or (x, y, z).
    angle : float
        Rotation in degrees.
    radius : float
        Curvature radius of the lens profile.
    aperture : float
        Clear aperture diameter.
    focal_length : float | None
        Optional focal length for ray-tracing hints.
    """

    component_type = "Lens"
    radius: float = 2.0
    aperture: float = 10.0
    # A lens focuses out of the box (ray tracing bends at f); None = passive visual.
    focal_length: float | None = 30.0
    center_thickness: float = 3.0
    edge_thickness: float = 1.0

    def __init__(self, center=(0, 0), angle=0, radius=2.0, aperture=10.0,
                 focal_length=30.0, center_thickness: float | None = None, edge_thickness: float | None = None, **kwargs):
        self.radius = radius
        self.aperture = aperture
        self.focal_length = focal_length
        self.center_thickness = max(center_thickness if center_thickness is not None else max(radius * 1.2, aperture * 0.22), 0.6)
        self.edge_thickness = max(edge_thickness if edge_thickness is not None else self.center_thickness * 0.35, 0.25)
        _set_common_free_space_fields(self, center, angle, kwargs, color="#4488ff", opacity=0.5, material_preset="glass")

    def physics_metadata(self) -> dict[str, Any]:
        return _optical_metadata(
            "lens",
            focal_length=self.focal_length,
            aperture=self.aperture,
            diameter=self.aperture,
            curvature_radius=self.radius,
            material_preset=self.material_preset,
        )

    def ports(self) -> dict[str, Port]:
        """Collinear input/output ports on the optical axis."""

        return _through_ports(self.center_thickness, self.aperture)

    def symbol_1d(self) -> tuple[str, dict[str, Any]] | None:
        return ("lens", {"kind": "concave"}) if (self.focal_length or 0.0) < 0.0 else None

    def geometry_2d(self) -> dict[str, Any]:
        w = self.aperture
        bulge = max(self.radius, w * 0.3)  # classic biconvex silhouette, never a sliver
        return {
            "type": "group",
            "children": [
                {"type": "path", "d": f"M 0 {w/2} Q {bulge} 0 0 {-w/2} Q {-bulge} 0 0 {w/2} Z",
                 "fill": self.color, "stroke": "#33638a", "stroke_width": 0.22, "opacity": max(self.opacity, 0.85)},
                {"type": "line", "x1": 0.0, "y1": -w * 0.42, "x2": 0.0, "y2": w * 0.42, "stroke": "#ffffff", "stroke_width": 0.1, "opacity": 0.45},
            ],
        }

    def geometry_3d(self) -> dict[str, Any]:
        material = {"color": self.color, "opacity": self.opacity, "transparent": True, "preset": self.material_preset, "roughness": 0.02, "transmission": 0.58, "ior": 1.52}

        # Optic body seated in a machined cell (mounted-asphere / lens-cell look): a fat
        # black ring wraps the glass rim, with a brushed retaining ring on the front.
        # The renderer adds a uniform post to the beam plane.
        children = [
            _cylinder_along_x(self.aperture / 2.0, self.center_thickness * 0.55, material),
            {
                "shape": "sphere",
                "radius": self.aperture / 2.0,
                "scale": [max(self.center_thickness / max(self.aperture, 1e-9), 0.14), 1.0, 1.0],
                "position": [self.center_thickness * 0.16, 0.0, 0.0],
                "material": material,
            },
            {
                "shape": "sphere",
                "radius": self.aperture / 2.0,
                "scale": [max(self.center_thickness / max(self.aperture, 1e-9), 0.14), 1.0, 1.0],
                "position": [-self.center_thickness * 0.16, 0.0, 0.0],
                "material": material,
            },
            # machined cell: a TRUE ring — the lens edge is seated in its bore, and the
            # glass is visible from both sides through the opening
            _ring_along_x(self.aperture * 0.485, self.aperture * 0.6, max(self.center_thickness * 0.8, self.aperture * 0.12), _MOUNT_BLACK),
            _post_boss(self.aperture * 0.6, max(self.center_thickness * 0.8, self.aperture * 0.12)),
            # brushed retaining ring threaded into the front of the cell
            _ring_along_x(self.aperture * 0.44, self.aperture * 0.52, max(self.center_thickness * 0.14, 0.1), _MOUNT_ALU, x=-max(self.center_thickness * 0.42, self.aperture * 0.065)),
        ]
        return {
            "shape": "group",
            "children": children,
            "surface_profile": {
                "type": "biconvex",
                "curvature_radius": self.radius,
                "edge_thickness": self.edge_thickness,
            },
        }


@dataclass
class AsphericLens(Component):
    """Aspheric singlet lens with solver-facing surface metadata.

    Parameters
    ----------
    center : tuple
        ``(x, y)`` or ``(x, y, z)`` position of the lens center.
    angle : float
        Rotation in degrees about the diagram z-axis.
    aperture : float
        Clear aperture diameter used for 1D, 2D, 3D, and port width.
    focal_length : float | None
        Optional paraxial focal-length hint for solver and annotation layers.
    radius : float
        Vertex radius of curvature for the modeled aspheric face.
    conic_constant : float
        Conic constant for the aspheric face; ``0`` is spherical, ``-1`` is parabolic.
    asphere_coefficients : tuple[float, ...]
        Even-order asphere coefficients, stored for future physics backends.
    center_thickness : float
        Center thickness of the singlet body.
    edge_thickness : float
        Edge thickness metadata for profile-aware renderers.
    numerical_aperture : float | None
        Optional NA metadata for microscope and collimation diagrams.
    """

    component_type = "AsphericLens"
    aperture: float = 10.0
    focal_length: float | None = 8.0
    radius: float = 12.0
    conic_constant: float = -1.0
    asphere_coefficients: tuple[float, ...] = ()
    center_thickness: float = 3.0
    edge_thickness: float = 0.8
    numerical_aperture: float | None = None

    def __init__(
        self,
        center=(0, 0),
        angle=0,
        aperture=10.0,
        focal_length=8.0,
        radius=12.0,
        conic_constant=-1.0,
        asphere_coefficients: tuple[float, ...] | list[float] = (),
        center_thickness: float | None = None,
        edge_thickness: float = 0.8,
        numerical_aperture: float | None = None,
        **kwargs,
    ):
        self.aperture = aperture
        self.focal_length = focal_length
        self.radius = radius
        self.conic_constant = conic_constant
        self.asphere_coefficients = tuple(asphere_coefficients)
        self.center_thickness = max(center_thickness if center_thickness is not None else aperture * 0.32, 0.6)
        self.edge_thickness = max(edge_thickness, 0.15)
        self.numerical_aperture = numerical_aperture
        _set_common_free_space_fields(self, center, angle, kwargs, color="#8ecaff", opacity=0.52, material_preset="glass")

    def geometry_2d(self) -> dict[str, Any]:
        half_height = self.aperture / 2.0
        # plano-convex D with a STRONG front bow + an inner contour line — the
        # aspheric signature, clearly different from the symmetric Lens
        body_half = max(self.edge_thickness, self.aperture * 0.1) / 2.0
        front_bulge = max(self.center_thickness - self.edge_thickness, self.aperture * 0.3)
        back_x, front_x = -body_half, body_half
        return {
            "type": "group",
            "children": [
                {
                    "type": "path",
                    "d": (
                        f"M {back_x} {-half_height} L {back_x} {half_height} "
                        f"Q {front_x + front_bulge} 0 {front_x} {-half_height} Z"
                    ),
                    "fill": self.color,
                    "stroke": "#33638a",
                    "stroke_width": 0.2,
                    "opacity": max(self.opacity, 0.85),
                },
                {
                    "type": "path",
                    "d": (
                        f"M {back_x + 0.2} {-half_height * 0.72} "
                        f"Q {front_x + front_bulge * 0.62} 0 {back_x + 0.2} {half_height * 0.72}"
                    ),
                    "fill": "none",
                    "stroke": "#ffffff",
                    "stroke_width": 0.1,
                    "opacity": 0.5,
                },
            ],
        }

    def geometry_3d(self) -> dict[str, Any]:
        material = {**_transparent_material(self.color, self.opacity, self.material_preset), "roughness": 0.025, "transmission": 0.62, "ior": 1.52}
        profile_scale = max(self.center_thickness / max(self.aperture, 1e-9), 0.12)
        return {
            "shape": "group",
            "children": [
                _cylinder_along_x(self.aperture / 2.0, self.edge_thickness, material, position=[-self.center_thickness * 0.12, 0.0, 0.0]),
                {
                    "shape": "sphere",
                    "radius": self.aperture / 2.0,
                    "scale": [profile_scale, 1.0, 1.0],
                    "position": [self.center_thickness * 0.18, 0.0, 0.0],
                    "material": material,
                },
                # the lens cell the asphere is bonded in, and its retaining ring
                {**_ring_along_x(self.aperture * 0.485, self.aperture * 0.6, max(self.center_thickness * 0.8, self.aperture * 0.12), _MOUNT_BLACK), "role": "holder"},
                _post_boss(self.aperture * 0.6, max(self.center_thickness * 0.8, self.aperture * 0.12)),
                _ring_along_x(self.aperture * 0.44, self.aperture * 0.52, max(self.center_thickness * 0.14, 0.1), _MOUNT_ALU, x=-max(self.center_thickness * 0.42, self.aperture * 0.065)),
            ],
            "surface_profile": {
                "type": "aspheric",
                "radius": self.radius,
                "conic_constant": self.conic_constant,
                "asphere_coefficients": list(self.asphere_coefficients),
            },
        }

    def ports(self) -> dict[str, Port]:
        return _through_ports(self.center_thickness, self.aperture)

    def physics_metadata(self) -> dict[str, Any]:
        return _optical_metadata(
            "aspheric_lens",
            aperture=self.aperture,
            focal_length=self.focal_length,
            radius=self.radius,
            conic_constant=self.conic_constant,
            asphere_coefficients=list(self.asphere_coefficients),
            numerical_aperture=self.numerical_aperture,
            material_preset=self.material_preset,
        )

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data.update(
            {
                "aperture": self.aperture,
                "focal_length": self.focal_length,
                "radius": self.radius,
                "conic_constant": self.conic_constant,
                "asphere_coefficients": list(self.asphere_coefficients),
                "center_thickness": self.center_thickness,
                "edge_thickness": self.edge_thickness,
                "numerical_aperture": self.numerical_aperture,
            }
        )
        return data


@dataclass
class CylindricalLens(Component):
    """Cylindrical lens that focuses along one transverse axis.

    Parameters
    ----------
    center : tuple
        ``(x, y)`` or ``(x, y, z)`` position of the lens center.
    angle : float
        Rotation in degrees about the diagram z-axis.
    aperture : float
        Clear aperture along the focusing axis.
    length : float
        Physical extent along the cylinder axis.
    focal_length : float | None
        Optional focal length in the focusing axis.
    cylinder_axis : str
        Local cylinder axis, usually ``"y"`` or ``"z"`` for lab diagrams.
    thickness : float
        Center thickness of the optical element.
    """

    component_type = "CylindricalLens"
    aperture: float = 10.0
    length: float = 16.0
    focal_length: float | None = None
    cylinder_axis: str = "y"
    thickness: float = 2.0

    def __init__(self, center=(0, 0), angle=0, aperture=10.0, length=16.0, focal_length=30.0, cylinder_axis="y", thickness=2.0, **kwargs):
        self.aperture = aperture
        self.length = length
        self.focal_length = focal_length
        self.cylinder_axis = str(cylinder_axis).lower()
        self.thickness = thickness
        _set_common_free_space_fields(self, center, angle, kwargs, color="#79b8e8", opacity=0.8, material_preset="glass")

    def geometry_2d(self) -> dict[str, Any]:
        ha = self.aperture / 2.0
        ht = max(self.thickness / 2.0, self.aperture * 0.06)
        bulge = ht * 3.2
        return {
            "type": "group",
            "children": [
                # plano-cylinder cross-section: flat back + squared ends + bulged front face
                {"type": "path", "d": (
                    f"M {-ht} {-ha} L {-ht} {ha} L {ht} {ha} "
                    f"Q {ht + bulge} 0 {ht} {-ha} Z"
                ), "fill": self.color, "stroke": "#33638a", "stroke_width": 0.22, "opacity": max(self.opacity, 0.85)},
                # cylinder-axis ticks past the squared ends (the "this axis is straight" cue)
                {"type": "line", "x1": -ht, "y1": ha, "x2": ht + bulge * 0.3, "y2": ha, "stroke": "#28577a", "stroke_width": 0.18, "opacity": 0.9},
                {"type": "line", "x1": -ht, "y1": -ha, "x2": ht + bulge * 0.3, "y2": -ha, "stroke": "#28577a", "stroke_width": 0.18, "opacity": 0.9},
            ],
        }

    def geometry_3d(self) -> dict[str, Any]:
        material = {**_transparent_material(self.color, self.opacity, self.material_preset), "roughness": 0.03, "transmission": 0.58, "ior": 1.52}
        return {
            "shape": "group",
            "children": [
                {"shape": "box", "width": self.thickness * 0.5, "height": self.aperture, "depth": self.length, "position": [-self.thickness * 0.18, 0.0, 0.0], "material": material},
                {"shape": "cylinder", "radius": self.aperture / 2.0, "height": self.length, "rotation": [math.pi / 2.0, 0.0, 0.0], "position": [self.thickness * 0.18, 0.0, 0.0], "scale": [max(self.thickness / max(self.aperture, 1e-9), 0.14), 1.0, 1.0], "material": material},
                *_frame_holder(self.length, self.aperture, max(self.thickness * 0.8, 0.6)),
            ],
            "surface_profile": {"type": "cylindrical", "axis": self.cylinder_axis},
        }

    def ports(self) -> dict[str, Port]:
        return _through_ports(self.thickness, self.aperture)

    def physics_metadata(self) -> dict[str, Any]:
        return _optical_metadata(
            "cylindrical_lens",
            aperture=self.aperture,
            length=self.length,
            focal_length=self.focal_length,
            cylinder_axis=self.cylinder_axis,
            focusing_axis="x" if self.cylinder_axis in {"y", "vertical"} else "y",
            material_preset=self.material_preset,
        )

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data.update({"aperture": self.aperture, "length": self.length, "focal_length": self.focal_length, "cylinder_axis": self.cylinder_axis, "thickness": self.thickness})
        return data


@dataclass
class Telescope(Component):
    """Two-lens telescope or beam relay with explicit lens spacing.

    Parameters
    ----------
    center : tuple
        ``(x, y)`` or ``(x, y, z)`` position at the midpoint between the lenses.
    angle : float
        Rotation in degrees about the diagram z-axis.
    focal_length_1 : float
        Focal length of the input/object-side lens.
    focal_length_2 : float
        Focal length of the output/image-side lens.
    input_aperture : float
        Input lens clear aperture and input port width.
    output_aperture : float
        Output lens clear aperture and output port width.
    spacing : float | None
        Lens-to-lens spacing. Defaults to ``focal_length_1 + focal_length_2``.
    telescope_type : str
        Descriptive model label, for example ``"keplerian"`` or ``"galilean"``.
    """

    component_type = "Telescope"
    focal_length_1: float = 20.0
    focal_length_2: float = 40.0
    input_aperture: float = 6.0
    output_aperture: float = 12.0
    spacing: float = 60.0
    telescope_type: str = "keplerian"

    def __init__(
        self,
        center=(0, 0),
        angle=0,
        focal_length_1=20.0,
        focal_length_2=40.0,
        input_aperture=6.0,
        output_aperture=12.0,
        spacing=None,
        telescope_type="keplerian",
        **kwargs,
    ):
        self.focal_length_1 = focal_length_1
        self.focal_length_2 = focal_length_2
        self.input_aperture = input_aperture
        self.output_aperture = output_aperture
        self.spacing = spacing if spacing is not None else abs(focal_length_1) + abs(focal_length_2)
        self.telescope_type = telescope_type
        _set_common_free_space_fields(self, center, angle, kwargs, color="#44515f", opacity=1.0, material_preset="steel", label=kwargs.get("label", "Telescope"))

    @property
    def magnification(self) -> float:
        return -self.focal_length_2 / _signed_nonzero(self.focal_length_1)

    @property
    def housing_margin(self) -> float:
        return max(self.input_aperture, self.output_aperture) * 0.2

    @property
    def housing_length(self) -> float:
        return self.spacing + 2.0 * self.housing_margin

    def symbol_1d(self) -> tuple[str, dict[str, Any]] | None:
        return ("telescope", {"kind": "galilean"}) if self.telescope_type == "galilean" else None

    @property
    def _barrel_radius(self) -> float:
        return max(self.input_aperture, self.output_aperture) * 0.57

    @property
    def _bore(self) -> float:
        """The bore of the wider barrel: about 1.5 % larger than its lens. The rods run in the wall outside it."""

        return max(self.input_aperture, self.output_aperture) * 0.5075

    @property
    def _rod_offset(self) -> float:
        """How far each rod lies from the axis, up and across: on the middle of the barrel wall, at 45 degrees."""

        return (self._bore + self._barrel_radius) / 2.0 * math.sqrt(0.5)

    @staticmethod
    def _lens(aperture: float, focal_length: float) -> Lens:
        """A lens as thick as its symbol, so the drawing fits both ports and stands centred where it is placed."""

        return Lens(aperture=aperture, focal_length=focal_length, center_thickness=aperture * (0.111 if focal_length < 0.0 else 0.27))

    def geometry_2d(self) -> dict[str, Any]:
        """From above, as in 3D: each lens in its short barrel at the true spacing, the rods between them, and two rays.

        A symbol has one fixed length, so a telescope draws its own spacing: the symbol stayed a small sketch at the
        in port, and the light vanished for the rest of the part."""

        from optodraw.symbols.art import art_piece

        half = self.spacing / 2.0
        galilean = self.telescope_type == "galilean"
        near = self.input_aperture * 0.35
        far = min(near * abs(self.focal_length_2 / _signed_nonzero(self.focal_length_1)), self.output_aperture * 0.36)
        radius = self._barrel_radius

        def metal(cx: float, width: float) -> list[dict[str, Any]]:
            """A round body from above: dark metal with a soft highlight and a darker lower edge. Rects that overlap
            build each one up, because a geometry rect takes one flat colour and a single band reads as a hard stripe."""

            return [{"type": "rect", "cx": cx, "cy": 0.0, "w": width, "h": 2.0 * radius, "fill": "#3a4654", "stroke": "#111827", "stroke_width": 0.08},
                    *[{"type": "rect", "cx": cx, "cy": radius * 0.42, "w": width, "h": radius * 0.14 * k, "fill": "#ffffff", "opacity": 0.035} for k in range(1, 7)],
                    *[{"type": "rect", "cx": cx, "cy": radius * (0.08 * k - 1.0), "w": width, "h": radius * 0.16 * k, "fill": "#0b1220", "opacity": 0.07} for k in range(1, 6)]]

        flange = [{"type": "rect", "cx": side * (self.housing_length / 2.0 - 0.35), "cy": 0.0, "w": 0.7, "h": 2.2 * radius, "fill": "#1b2430",
                   "stroke": "#111827", "stroke_width": 0.08} for side in (-1.0, 1.0)]
        first = self._lens(self.input_aperture, -abs(self.focal_length_1) if galilean else abs(self.focal_length_1))
        second = self._lens(self.output_aperture, abs(self.focal_length_2))
        return {
            "type": "group",
            "children": [
                *[{"type": "line", "x1": -half, "y1": side * self._rod_offset, "x2": half, "y2": side * self._rod_offset,
                   "stroke": "#94a3b8", "stroke_width": 0.4} for side in (-1.0, 1.0)],
                *metal(0.0, self.housing_margin),
                *[{"type": "line", "role": "ray", "x1": -half, "y1": side * near, "x2": half, "y2": side * far * (1.0 if galilean else -1.0),
                   "stroke": "#ef4444", "stroke_width": 0.14} for side in (-1.0, 1.0)],
                *metal(-half, 2.0 * self.housing_margin),
                *metal(half, 2.0 * self.housing_margin),
                *flange,
                art_piece(first, -half),
                art_piece(second, half),
            ],
        }

    def geometry_3d(self) -> dict[str, Any]:
        """A lens in a short barrel at each end of the true spacing, joined by four thin rods, so the light stays in
        view as in 2D. A closed tube hid both lenses and read as a refractor on a post."""

        half = self.spacing / 2.0
        outer_half = self.housing_length / 2.0
        outer, bore, offset = self._barrel_radius, self._bore, self._rod_offset
        clamp, post_at = _tube_clamp(bore, self.housing_margin)
        lens_material = {**_transparent_material("#a5d8ff", 0.5, "glass"), "transmission": 0.54, "ior": 1.52}
        barrel = {"color": self.color, "metalness": 0.3, "roughness": 0.45, "preset": self.material_preset}
        ring = {"color": "#2f3942", "metalness": 0.5, "roughness": 0.32, "preset": "steel"}
        rod = {"color": "#b8bdc3", "metalness": 0.5, "roughness": 0.4, "preset": "steel"}
        return {
            "shape": "group",
            "children": [
                _ring_along_x(self.input_aperture * 0.5075, outer, 2.0 * self.housing_margin, barrel, x=-half, role="barrel"),
                _ring_along_x(self.output_aperture * 0.5075, outer, 2.0 * self.housing_margin, barrel, x=half, role="barrel"),
                _cylinder_along_x(self.input_aperture / 2.0, self.input_aperture * 0.22, lens_material, position=[-half, 0.0, 0.0], role="lens"),
                _cylinder_along_x(self.output_aperture / 2.0, self.output_aperture * 0.22, lens_material, position=[half, 0.0, 0.0], role="lens"),
                *[_cylinder_along_x((outer - bore) * 0.4, self.spacing, rod, position=[0.0, up * offset, across * offset], role="rod")
                  for up in (-1.0, 1.0) for across in (-1.0, 1.0)],
                _rim_along_x(outer * 1.04, outer * 0.1, ring, position=[-outer_half, 0.0, 0.0]),
                _rim_along_x(outer * 1.04, outer * 0.1, ring, position=[outer_half, 0.0, 0.0]),
                *clamp,
            ],
            "post_at": post_at,
        }

    def ports(self) -> dict[str, Port]:
        half = self.housing_length / 2.0
        return {
            "in": Port("in", Vec3(-half, 0.0, 0.0), orientation_deg=180.0, width=self.input_aperture, kind="free_space"),
            "out": Port("out", Vec3(half, 0.0, 0.0), orientation_deg=0.0, width=self.output_aperture, kind="free_space"),
        }

    def physics_metadata(self) -> dict[str, Any]:
        return _optical_metadata(
            "telescope",
            focal_length_1=self.focal_length_1,
            focal_length_2=self.focal_length_2,
            spacing=self.spacing,
            magnification=self.magnification,
            telescope_type=self.telescope_type,
        )

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data.update({"focal_length_1": self.focal_length_1, "focal_length_2": self.focal_length_2, "input_aperture": self.input_aperture, "output_aperture": self.output_aperture, "spacing": self.spacing, "magnification": self.magnification, "telescope_type": self.telescope_type})
        return data


@dataclass
class FourFSystem(Component):
    """Two-lens 4f relay with object, Fourier, and image plane metadata.

    Parameters
    ----------
    center : tuple
        ``(x, y)`` or ``(x, y, z)`` position of the Fourier plane midpoint.
    angle : float
        Rotation in degrees about the diagram z-axis.
    focal_length_1 : float
        Focal length of the object-side lens.
    focal_length_2 : float
        Focal length of the image-side lens.
    aperture : float
        Lens clear aperture and port width.
    lens_spacing : float | None
        Lens separation. Defaults to ``focal_length_1 + focal_length_2``.
    include_planes : bool
        Whether 2D/3D visuals include object, Fourier, and image plane markers.
    """

    component_type = "FourFSystem"
    focal_length_1: float = 20.0
    focal_length_2: float = 20.0
    aperture: float = 10.0
    lens_spacing: float = 40.0
    include_planes: bool = True

    def __init__(self, center=(0, 0), angle=0, focal_length_1=20.0, focal_length_2=20.0, aperture=10.0, lens_spacing=None, include_planes=True, **kwargs):
        self.focal_length_1 = focal_length_1
        self.focal_length_2 = focal_length_2
        self.aperture = aperture
        self.lens_spacing = lens_spacing if lens_spacing is not None else abs(focal_length_1) + abs(focal_length_2)
        self.include_planes = include_planes
        _set_common_free_space_fields(self, center, angle, kwargs, color="#3f4b59", opacity=1.0, material_preset="steel", label=kwargs.get("label", "4f relay"))

    @property
    def magnification(self) -> float:
        return -self.focal_length_2 / _signed_nonzero(self.focal_length_1)

    @property
    def system_length(self) -> float:
        return abs(self.focal_length_1) + self.lens_spacing + abs(self.focal_length_2)

    def symbol_1d(self) -> tuple[str, dict[str, Any]] | None:
        """The 4f symbol with its Fourier plane one f1 behind the first lens: split = f1 / (f1 + f2)."""

        f1, f2 = abs(self.focal_length_1), abs(self.focal_length_2)
        split = round(f1 / max(f1 + f2, 1e-9), 2)
        return None if abs(split - 0.5) < 0.005 else ("fourf", {"split": split})

    def _stations(self) -> tuple[float, float, float]:
        """x of lens 1, of the Fourier plane (one f1 behind lens 1) and of lens 2; the object plane is at
        -system_length/2 and the image plane at +system_length/2."""

        lens_1 = -self.system_length / 2.0 + abs(self.focal_length_1)
        return lens_1, lens_1 + abs(self.focal_length_1), lens_1 + self.lens_spacing

    def geometry_2d(self) -> dict[str, Any]:
        """From above: each lens (its 2D art) at its true station, the rays from the axial object point, collimated
        between the lenses and focused on the image plane, and the Fourier plane between.

        A symbol has one fixed length, so the relay draws its own spacing, as a telescope does: the 4f symbol stayed
        a sketch at the object port, and the image port lay 57 units past it."""

        from optodraw.symbols.art import LINE_SCALE, art_piece

        half_system = self.system_length / 2.0
        lens_1, fourier, lens_2 = self._stations()
        ray = self.aperture * 0.35
        lenses = [art_piece(Telescope._lens(self.aperture, abs(self.focal_length_1)), lens_1),
                  art_piece(Telescope._lens(self.aperture, abs(self.focal_length_2)), lens_2)]
        line = min(lenses[0]["pic"]["scale"], LINE_SCALE)        # the symbol's pt in scene units, as the lens art

        def plane(x: float, half: float) -> dict[str, Any]:       # od plane: a dashed slate line, not a beam
            return {"type": "line", "role": "plane", "x1": x, "y1": -half, "x2": x, "y2": half, "stroke": "#64748b",
                    "stroke_width": 0.3 * line, "stroke_dasharray": f"{1.2 * line:.4g} {1.2 * line:.4g}"}

        children: list[dict[str, Any]] = [
            *[{"type": "polyline", "role": "ray", "points": [(-half_system, 0.0), (lens_1, side * ray), (lens_2, side * ray), (half_system, 0.0)],
               "fill": "none", "stroke": "#ef4444", "stroke_width": 0.3 * line} for side in (-1.0, 1.0)],
            plane(fourier, self.aperture * 0.62),
            *lenses,
        ]
        if self.include_planes:
            children += [plane(x, self.aperture * 0.48) for x in (-half_system, half_system)]
        return {"type": "group", "children": children}

    def geometry_3d(self) -> dict[str, Any]:
        # A cage relay: four rods carry a plate with each lens and a plate with the Fourier mask (a pinhole)
        # between them; a bracket under the rods takes the post. The object and image planes are not parts,
        # so the 3D does not draw them.
        a = self.aperture
        lens_1, fourier, lens_2 = self._stations()
        glass = {**_transparent_material("#a5d8ff", 0.5, "glass"), "transmission": 0.56, "ior": 1.52}
        mask_material = {"color": "#3a414a", "metalness": 0.6, "roughness": 0.3, "preset": "steel"}
        children: list[dict[str, Any]] = []
        for x in (lens_1, lens_2):
            children += [
                _square_plate(x, a * 0.6, a * 0.48, a * 0.12, _MOUNT_BLACK),
                {**_cylinder_along_x(a * 0.48, a * 0.12, glass, position=[x, 0.0, 0.0]), "role": "lens"},
                {"shape": "sphere", "radius": a * 0.48, "scale": [0.16, 1.0, 1.0], "position": [x, 0.0, 0.0], "material": glass},
            ]
        children += [_square_plate(fourier, a * 0.6, a * 0.3, a * 0.12, _MOUNT_BLACK), {**_ring_along_x(a * 0.04, a * 0.3, a * 0.02, mask_material, x=fourier), "role": "mask"}]
        start, end = lens_1 - a * 0.15, lens_2 + a * 0.15
        for y, z in ((a * 0.45, a * 0.45), (a * 0.45, -a * 0.45), (-a * 0.45, a * 0.45), (-a * 0.45, -a * 0.45)):
            children.append({**_cylinder_along_x(a * 0.03, end - start, _KNOB_STEEL, position=[(start + end) / 2.0, y, z]), "role": "rod"})
        children.append({"shape": "box", "width": a * 0.18, "height": a * 0.22, "depth": a * 0.9,
                         "position": [(start + end) / 2.0, -a * 0.5, 0.0], "material": _MOUNT_BLACK})
        return {"shape": "group", "children": children}

    def ports(self) -> dict[str, Port]:
        half = self.system_length / 2.0
        return {
            "object": Port("object", Vec3(-half, 0.0, 0.0), orientation_deg=180.0, width=self.aperture, kind="free_space"),
            "image": Port("image", Vec3(half, 0.0, 0.0), orientation_deg=0.0, width=self.aperture, kind="free_space"),
            "fourier": Port("fourier", Vec3(self._stations()[1], 0.0, 0.0), orientation_deg=0.0, width=self.aperture, kind="free_space"),
        }

    def physics_metadata(self) -> dict[str, Any]:
        return _optical_metadata(
            "four_f_system",
            focal_length_1=self.focal_length_1,
            focal_length_2=self.focal_length_2,
            lens_spacing=self.lens_spacing,
            system_length=self.system_length,
            magnification=self.magnification,
            fourier_plane_offset=self._stations()[1],
        )

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data.update({"focal_length_1": self.focal_length_1, "focal_length_2": self.focal_length_2, "aperture": self.aperture, "lens_spacing": self.lens_spacing, "system_length": self.system_length, "magnification": self.magnification, "include_planes": self.include_planes})
        return data


@dataclass
class BeamExpanderTelescope(Component):
    """Keplerian beam-expander stub with magnification and port metadata."""

    component_type = "BeamExpanderTelescope"
    input_aperture: float = 4.0
    output_aperture: float = 12.0
    length: float = 24.0
    magnification: float | None = None

    def __init__(
        self,
        center=(0, 0),
        angle=0,
        input_aperture=4.0,
        output_aperture=12.0,
        length=24.0,
        magnification=None,
        **kwargs,
    ):
        self.input_aperture = input_aperture
        self.output_aperture = output_aperture
        self.length = length
        self.magnification = magnification if magnification is not None else output_aperture / max(input_aperture, 1e-9)
        self.telescope_type = kwargs.get("telescope_type", "keplerian")
        _set_common_free_space_fields(self, center, angle, kwargs, color="#4b5563", opacity=1.0, material_preset="steel", label=kwargs.get("label", "Beam Expander"))

    def geometry_2d(self) -> dict[str, Any]:
        half = self.length / 2.0
        lens_x = half * 0.72
        return {
            "type": "group",
            "children": [
                {"type": "polygon", "points": [(-half, -self.input_aperture * 0.55),
                                                (half, -self.output_aperture * 0.55),
                                                (half, self.output_aperture * 0.55),
                                                (-half, self.input_aperture * 0.55)],
                 "fill": "#374151", "stroke": "#111827", "stroke_width": 0.08, "opacity": 0.92},
                {"type": "circle", "cx": -lens_x, "cy": 0.0, "r": self.input_aperture / 2.0, "fill": "#9fd3ff", "opacity": 0.5, "stroke": "#5d8fb2", "stroke_width": 0.08},
                {"type": "circle", "cx": lens_x, "cy": 0.0, "r": self.output_aperture / 2.0, "fill": "#9fd3ff", "opacity": 0.5, "stroke": "#5d8fb2", "stroke_width": 0.08},
                {"type": "line", "x1": -half, "y1": 0.0, "x2": half, "y2": 0.0, "stroke": "#e9f6ff", "stroke_width": 0.16, "opacity": 0.65},
            ],
        }

    def geometry_3d(self) -> dict[str, Any]:
        half = self.length / 2.0
        lens_x = half * 0.72
        lens_material = {**_transparent_material("#9fd3ff", 0.48, "glass"), "transmission": 0.5, "ior": 1.52}
        ring_material = {"color": "#2f3942", "metalness": 0.5, "roughness": 0.32, "preset": "steel"}
        clamp, post_at = _tube_clamp(0.55 * (self.input_aperture + self.output_aperture) / 2.0, self.length * 0.12)
        return {
            "shape": "group",
            "children": [
                {"shape": "lathe_profile",
                 "points": [[self.input_aperture * 0.5, -half],
                            [self.input_aperture * 0.55, -half],
                            [self.output_aperture * 0.55, half],
                            [self.output_aperture * 0.5, half],
                            [self.input_aperture * 0.5, -half]],
                 "segments": 48, "rotation": [0.0, 0.0, -math.pi / 2.0],
                 "material": {"color": self.color, "metalness": 0.28, "roughness": 0.48, "preset": self.material_preset}},
                _cylinder_along_x(self.input_aperture / 2.0, self.input_aperture * 0.28, lens_material, position=[-lens_x, 0.0, 0.0]),
                _cylinder_along_x(self.output_aperture / 2.0, self.output_aperture * 0.28, lens_material, position=[lens_x, 0.0, 0.0]),
                _rim_along_x(self.input_aperture * 0.5, self.input_aperture * 0.04, ring_material, position=[-lens_x, 0.0, 0.0]),
                _rim_along_x(self.output_aperture * 0.5, self.output_aperture * 0.04, ring_material, position=[lens_x, 0.0, 0.0]),
                *clamp,
            ],
            "post_at": post_at,
        }

    def ports(self) -> dict[str, Port]:
        half = self.length / 2.0
        return {
            "in": Port("in", Vec3(-half, 0.0, 0.0), orientation_deg=180.0, width=self.input_aperture, kind="free_space"),
            "out": Port("out", Vec3(half, 0.0, 0.0), orientation_deg=0.0, width=self.output_aperture, kind="free_space"),
        }

    def physics_metadata(self) -> dict[str, Any]:
        return _optical_metadata(
            "beam_expander_telescope",
            input_aperture=self.input_aperture,
            output_aperture=self.output_aperture,
            magnification=self.magnification,
            telescope_type=self.telescope_type,
            stub=True,
        )

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["input_aperture"] = self.input_aperture
        data["output_aperture"] = self.output_aperture
        data["length"] = self.length
        data["magnification"] = self.magnification
        data["telescope_type"] = self.telescope_type
        return data
