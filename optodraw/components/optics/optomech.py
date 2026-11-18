"""Optomech free-space optics."""

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
    _kinematic_mount,
    _optical_metadata,
    _post_boss,
    _ring_along_x,
    _set_common_free_space_fields,
    _through_ports,
    _rim_along_x,
    _transparent_material,
    _tube_clamp,
)

# The optical axis above the table in 3D: 3 in, a usual bench height (1 in = 10 units, the Ø1in optic).
# At 16 units the larger optics reached down to their post holders and the posts read as stubs.
BEAM_HEIGHT = 30.0


@dataclass
class OpticalTable(Component):
    """Optical table or breadboard base with hole-grid metadata."""

    component_type = "OpticalTable"
    length: float = 120.0
    width: float = 75.0
    thickness: float = 4.0
    hole_pitch: float = 10.0

    def __init__(self, center=(0, 0), angle=0, length=120.0, width=75.0, thickness=4.0, hole_pitch=10.0, **kwargs):
        self.length = length
        self.width = width
        self.thickness = thickness
        self.hole_pitch = hole_pitch
        self.edge_margin = kwargs.get("edge_margin", hole_pitch * 0.75)
        self.include_holes = kwargs.get("include_holes", True)
        _set_common_free_space_fields(self, center, angle, kwargs, color="#b9bfc6", opacity=1.0, material_preset="steel", label=kwargs.get("label", "Optical Table"))   # stainless top

    # Hole ⌀/pitch ≈ 0.25 (a 1/4-20 tap on a 1" grid) — the real Thorlabs/Newport ratio.
    _HOLE_R_FACTOR = 0.125

    def _hole_r(self) -> float:
        return self.hole_pitch * self._HOLE_R_FACTOR

    def _hole_grid(self) -> tuple[int, int, float, float, int]:
        """(cols, rows, x0, y0, stride): the full tapped-hole grid, centered.

        The grid always spans the whole plate (edge margin excluded) — no more
        arbitrary 18×12 caps that left big boards mostly blank. ``stride`` only
        thins the *drawn* 2D grid for absurd pitch/size combinations so an SVG
        can't explode into hundreds of thousands of nodes.
        """

        if not self.include_holes or self.hole_pitch <= 0:
            return 0, 0, 0.0, 0.0, 1
        cols = max(int((self.length - 2.0 * self.edge_margin) / self.hole_pitch) + 1, 0)
        rows = max(int((self.width - 2.0 * self.edge_margin) / self.hole_pitch) + 1, 0)
        x0 = -((cols - 1) * self.hole_pitch) / 2.0
        y0 = -((rows - 1) * self.hole_pitch) / 2.0
        total = cols * rows
        stride = 1
        if total > 6000:
            stride = int(math.ceil(math.sqrt(total / 6000.0)))
        return cols, rows, x0, y0, stride

    def _edge_stroke(self) -> str:
        return "#27272a"

    # In 2D a plate is a light ground for the black line art of the parts on it; 3D keeps the metal colour.
    PLATE_2D = "#eceef1"
    HOLE_2D = "#aeb4bc"

    def geometry_2d(self) -> dict[str, Any]:
        children: list[dict[str, Any]] = [
            {"type": "rect", "cx": 0.0, "cy": 0.0, "w": self.length, "h": self.width, "fill": self.PLATE_2D, "stroke": self._edge_stroke(), "stroke_width": 0.12, "opacity": 0.97},
            {"type": "rect", "cx": 0.0, "cy": 0.0, "w": self.length * 0.985, "h": self.width * 0.975, "fill": "none", "stroke": "#c8ccd2", "stroke_width": 0.05, "opacity": 0.45},
        ]
        cols, rows, x0, y0, stride = self._hole_grid()
        hole_r = self._hole_r()
        for col in range(0, cols, stride):
            for row in range(0, rows, stride):
                children.append(
                    {
                        "type": "circle",
                        "cx": x0 + col * self.hole_pitch,
                        "cy": y0 + row * self.hole_pitch,
                        "r": hole_r,
                        "fill": self.HOLE_2D,
                        # light chamfer ring so each hole reads as countersunk, not painted-on
                        "stroke": "#d4d8dd",
                        "stroke_width": hole_r * 0.35,
                        "opacity": 0.9,
                    }
                )
        return {"type": "group", "children": children}

    def geometry_3d(self) -> dict[str, Any]:
        box: dict[str, Any] = {
            "shape": "box",
            "width": self.length,
            "height": self.thickness,
            "depth": self.width,
            "material": {"color": self.color, "metalness": 0.52, "roughness": 0.38, "preset": self.material_preset},
        }
        # The tapped-hole grid is a baked top-face texture (counterbored circles over a
        # brushed finish), rendered by the JS side — real recessed *look* at any hole
        # count for the cost of one canvas, instead of the old raised stud cylinders.
        if self.include_holes and self.hole_pitch > 0:
            box["top_texture"] = {
                "kind": "hole_grid",
                "length": self.length,
                "width": self.width,
                "pitch": self.hole_pitch,
                "margin": self.edge_margin,
                "hole_r": self._hole_r(),
                "base": self.color,
                "side": self._side_color(),
                "brushed": True,
            }
        return box

    def _side_color(self) -> str:
        # honeycomb-core tables have dark steel skirts; plates read as one metal
        return "#33383f"

    def ports(self) -> dict[str, Port]:
        return _through_ports(self.length, self.width)

    def physics_metadata(self) -> dict[str, Any]:
        return _optical_metadata(
            "optical_table",
            size=(self.length, self.width, self.thickness),
            hole_pitch=self.hole_pitch,
            include_holes=self.include_holes,
        )

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["length"] = self.length
        data["width"] = self.width
        data["thickness"] = self.thickness
        data["hole_pitch"] = self.hole_pitch
        data["edge_margin"] = self.edge_margin
        data["include_holes"] = self.include_holes
        return data


@dataclass
class Breadboard(OpticalTable):
    """Compact optical breadboard specialization."""

    component_type = "Breadboard"

    def __init__(self, center=(0, 0), angle=0, **kwargs):
        kwargs.setdefault("length", 60.0)
        kwargs.setdefault("width", 45.0)
        kwargs.setdefault("thickness", 2.4)
        kwargs.setdefault("color", "#2a2e34")            # black anodised aluminium
        kwargs.setdefault("label", "Breadboard")
        super().__init__(center=center, angle=angle, **kwargs)


@dataclass
class Baseplate(OpticalTable):
    """Modular optical **baseplate** (PyOpticL-style concept): a machined sub-plate with a
    mount-hole grid that anchors a free-space subsystem at a fixed beam (``optical_height``)
    above the optical table. Reusable building block — drop a beam path + optics onto it.

    Visualization only: optodraw renders the plate for diagrams/figures and does NOT
    generate machining geometry (use a code-to-CAD tool for that)."""

    component_type = "Baseplate"
    optical_height: float = 12.7

    def __init__(self, center=(0, 0), angle=0, optical_height=12.7, **kwargs):
        self.optical_height = float(optical_height)
        kwargs.setdefault("length", 90.0)
        kwargs.setdefault("width", 60.0)
        kwargs.setdefault("thickness", 6.0)
        kwargs.setdefault("hole_pitch", 10.0)  # 25 mm / 1 in, same as the boards
        kwargs.setdefault("color", "#9aa3ad")           # machined anodized aluminium
        kwargs.setdefault("material_preset", "aluminum")
        kwargs.setdefault("label", "Baseplate")
        super().__init__(center=center, angle=angle, **kwargs)

    def _chamfer(self) -> float:
        return min(self.length, self.width) * 0.06

    def geometry_2d(self) -> dict[str, Any]:
        geo = super().geometry_2d()
        hl, hw, c = self.length / 2.0, self.width / 2.0, self._chamfer()
        # machined chamfered-corner outline in place of the plain rectangle
        geo["children"][0] = {
            "type": "path",
            "d": (
                f"M {-hl + c},{-hw} L {hl - c},{-hw} L {hl},{-hw + c} L {hl},{hw - c} "
                f"L {hl - c},{hw} L {-hl + c},{hw} L {-hl},{hw - c} L {-hl},{-hw + c} Z"
            ),
            "fill": self.PLATE_2D,
            "stroke": self._edge_stroke(),
            "stroke_width": 0.12,
            "opacity": 0.97,
        }
        # an inset module border so it reads as a discrete baseplate, not the full table
        geo["children"].insert(2, {
            "type": "rect", "cx": 0.0, "cy": 0.0, "w": self.length * 0.93, "h": self.width * 0.9,
            "fill": "none", "stroke": "#6b7480", "stroke_width": 0.1, "opacity": 0.5,
        })
        return geo

    def _edge_stroke(self) -> str:
        return "#5d6570"

    def _side_color(self) -> str:
        return "#828b96"  # machined aluminium edge, lighter than a steel skirt

    def physics_metadata(self) -> dict[str, Any]:
        meta = super().physics_metadata()
        meta["role"] = "baseplate"
        meta["optical_height"] = self.optical_height
        return meta

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["optical_height"] = self.optical_height
        return data


@dataclass
class Periscope(Component):
    """Two 45 deg mirrors on a vertical rail, moving the beam between heights.

    A bench uses one to lift the beam off the table into a microscope, or drop it
    onto a sample. The mirrors sit on different axes: the lower one turns the
    incoming horizontal beam vertical, the upper one turns it back into the plane
    along ``output_angle_deg`` (0 leaves it travelling the way it arrived, 90
    turns it across). The top plate carries whatever rides up there -- usually an
    objective -- on its ``mount`` port.

    Visualization only (clean-room parametric hardware; no machining geometry)."""

    component_type = "Periscope"
    lifts_beam = True        # the beam changes height inside it: core.beam_heights links the runs on each side
    beam_passes = True       # the 2D plan shows the beam itself up to the mirrors: the part knows no wavelength
    rise: float = 30.0
    entry_height: float | None = None   # the arriving beam's height above the bench (3D); None: see _port_heights
    output_angle_deg: float = 0.0
    aperture: float = 10.0

    def __init__(self, center=(0, 0), angle=0, rise=30.0, output_angle_deg=0.0, aperture=10.0, **kwargs):
        self.rise = float(rise)  # signed: positive lifts the beam, negative drops it
        self.output_angle_deg = float(output_angle_deg) % 360.0
        self.aperture = max(float(aperture), 2.0)
        # The post is slimmer than the optics it carries: the mounts have to
        # DOMINATE the post for the assembly to read like the hardware, where a
        # Ø1in post disappears behind ~2in mount blocks.
        self.post_diameter = float(kwargs.get("post_diameter", aperture * 0.6))
        # how high the lower port sits above the table: the bench beam height. Left unset, the 3D view gives
        # it the scene's own beam height, so the mirrors are where the beam runs.
        self._scene_beam = "beam_height" not in kwargs
        self.beam_height = float(kwargs.get("beam_height", BEAM_HEIGHT))
        _set_common_free_space_fields(
            self, center, angle, kwargs, color="#3f4650", opacity=1.0,
            material_preset="steel", label=kwargs.get("label", "Periscope"),
        )

    def symbol_2d(self) -> tuple[str, dict[str, Any]]:
        return "periscope", {"view": "top"}          # the 1D symbol is a side view; 2D is seen from above

    @property
    def _reach(self) -> float:
        """How far the ports stand out from the rail."""

        return self.aperture * 0.75

    @property
    def _port_heights(self) -> tuple[float, float]:
        """(entry, exit) heights above the bench beam plane.

        Both mounts slide on the post. In a scene, the entry mirror sits where the arriving beam runs
        (``entry_height``, set by the 3D view from the beam). On its own, the LOWER end sits at the beam
        plane: a rising periscope takes the bench beam up, and a falling one takes a raised beam back
        down to it."""

        if self.entry_height is not None:
            return (self.entry_height, self.entry_height + self.rise)
        return (0.0, self.rise) if self.rise >= 0 else (-self.rise, 0.0)

    def beam_path_between(self, start: str, end: str) -> list[tuple[float, float, float]] | None:
        """Where a beam from port ``start`` to port ``end`` runs inside: the two mirror centres, in local
        coordinates (z is the height above the bench beam). A straight line from port to port would cut
        through the air past both mirrors."""

        entry_z, exit_z = self._port_heights
        path = [(0.0, 0.0, entry_z), (0.0, 0.0, exit_z)]
        if (start, end) == ("in", "out"):
            return path
        if (start, end) == ("out", "in"):
            return path[::-1]
        return None

    def ports(self) -> dict[str, Port]:
        exit_rad = math.radians(self.output_angle_deg)
        reach = self._reach
        entry_z, exit_z = self._port_heights
        return {
            "in": Port("in", Vec3(-reach, 0.0, entry_z), orientation_deg=180.0,
                       width=self.aperture, kind="free_space"),
            "out": Port(
                "out",
                Vec3(reach * math.cos(exit_rad), reach * math.sin(exit_rad), exit_z),
                orientation_deg=self.output_angle_deg,
                width=self.aperture,
                kind="free_space",
            ),
            # the top plate: place an objective (or anything) here
            "mount": Port("mount", Vec3(0.0, 0.0, max(entry_z, exit_z)),
                          orientation_deg=self.output_angle_deg, width=self.aperture, kind="free_space"),
        }

    def geometry_2d(self) -> dict[str, Any]:
        """Two mirror mounts, drawn so you can see there are two of them.

        A true plan view would hide the lower mount completely under the upper
        one -- honest, and useless on a layout. So they are offset the way an
        optomech drawing shows a stacked assembly: the lower mount set back along
        the beam and paler, the upper one on the part's centre. Each mirror folds the light up or down, so
        from above it shows as a band across its beam, and the mark on the lower
        one says which way the light runs between them: a dot for up, a cross for down."""

        a = self.aperture
        half = a * 0.24
        exit_rad = math.radians(self.output_angle_deg)
        back = (-a * 0.64, 0.0)                   # the lower mount sits back along the input
        plate = a * 0.62
        across = (-math.sin(exit_rad), math.cos(exit_rad))
        mark = [{"type": "circle", "cx": back[0], "cy": back[1], "r": a * 0.1, "fill": "#f8fafc", "stroke": "#475569", "stroke_width": a * 0.02}]
        if self.rise >= 0:
            mark.append({"type": "circle", "cx": back[0], "cy": back[1], "r": a * 0.03, "fill": "#475569"})
        else:
            tip = a * 0.07
            mark += [{"type": "line", "x1": back[0] - tip, "y1": back[1] + side * tip, "x2": back[0] + tip, "y2": back[1] - side * tip,
                      "stroke": "#475569", "stroke_width": a * 0.02} for side in (-1.0, 1.0)]
        return {
            "type": "group",
            "children": [
                # lower mount: set back, paler -- it lives under the upper one
                {"type": "rect", "cx": back[0], "cy": back[1], "w": plate, "h": plate, "rx": a * 0.05,
                 "fill": "#e2e8f0", "stroke": "#94a3b8", "stroke_width": a * 0.015, "opacity": 0.9},
                {"type": "polyline", "points": [(back[0], back[1] - half), (back[0], back[1] + half)], "stroke": "#94a3b8",
                 "stroke_width": a * 0.1, "fill": "none", "linecap": "round"},
                *mark,
                # upper mount: on top
                {"type": "rect", "cx": 0.0, "cy": 0.0, "w": plate, "h": plate, "rx": a * 0.05,
                 "fill": "#f1f5f9", "stroke": "#64748b", "stroke_width": a * 0.015, "opacity": 1.0},
                {"type": "polyline", "points": [(-half * across[0], -half * across[1]), (half * across[0], half * across[1])], "stroke": "#475569",
                 "stroke_width": a * 0.1, "fill": "none", "linecap": "round"},
            ],
        }

    # A right-angle mirror mount: a cube with the mirror on its internal 45 deg diagonal. The beam enters
    # one face and leaves an adjacent one; the body is the half behind the mirror. Ø1in cube mounts are
    # about 1.5in across.
    _CUBE = 1.4

    def _fold(self, which: str):
        """(fold point, a, b) for one mirror, in the part's 3D frame (x along the input, y up, z = -plan y):
        ``a`` points back along the arriving beam, ``b`` along the leaving one."""

        entry_z, exit_z = self._port_heights
        climb = 1.0 if self.rise >= 0 else -1.0
        turn = math.radians(self.output_angle_deg)
        if which == "entry":
            return (0.0, self.beam_height + entry_z, 0.0), (-1.0, 0.0, 0.0), (0.0, climb, 0.0)
        return ((0.0, self.beam_height + exit_z, 0.0), (0.0, -climb, 0.0),
                (math.cos(turn), 0.0, -math.sin(turn)))

    @staticmethod
    def _unit(v):
        length = math.sqrt(sum(c * c for c in v)) or 1.0
        return tuple(c / length for c in v)

    @staticmethod
    def _cross(p, q):
        return (p[1] * q[2] - p[2] * q[1], p[2] * q[0] - p[0] * q[2], p[0] * q[1] - p[1] * q[0])

    @staticmethod
    def _euler(x_axis, y_axis, z_axis) -> list[float]:
        """The XYZ Euler angles (three.js order) of the turn that takes x, y, z onto these axes."""

        m13 = max(-1.0, min(1.0, z_axis[0]))
        if abs(m13) < 0.9999999:
            return [math.atan2(-z_axis[1], z_axis[2]), math.asin(m13), math.atan2(-y_axis[0], x_axis[0])]
        return [math.atan2(y_axis[2], y_axis[1]), math.asin(m13), 0.0]

    def mirror_normals(self) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
        """Which way each mirror face looks, in 3D: halfway between where the light comes from and where it goes."""

        normals = []
        for which in ("entry", "exit"):
            _, a, b = self._fold(which)
            normals.append(self._unit(tuple(a[i] + b[i] for i in range(3))))
        return tuple(normals)

    @property
    def _post_side(self) -> float:
        """The post stands beside the beam at +z, or at -z when the exit beam would run into it."""

        return -1.0 if -math.sin(math.radians(self.output_angle_deg)) > 0.2 else 1.0

    @property
    def _post_z(self) -> float:
        """How far the post stands from the beam axis: clear of the cube mounts it carries."""

        return self.aperture * (self._CUBE / 2.0 + 0.35) + self.post_diameter / 2.0

    def _mount(self, which: str) -> list[dict[str, Any]]:
        """One right-angle mount (a cage-cube kind): the block behind the mirror with its back corner cut flat,
        parallel to the mirror; the mirror on the diagonal; two adjusters on that flat face, pointing straight
        back; and a clamp to the post."""

        a_len = self.aperture
        cube = a_len * self._CUBE
        chamfer = cube * 0.3                                     # how much of each leg the cut takes
        point, a, b = self._fold(which)
        n = self._unit(tuple(a[i] + b[i] for i in range(3)))
        w = self._cross(a, b)
        facing = self._euler(w, n, self._cross(w, n))          # a cylinder's axis (y) along the mirror normal

        def at(*terms):
            return [point[i] + sum(k * v[i] for k, v in terms) for i in range(3)]

        mirror_t = a_len * 0.08
        half = cube / 2.0
        plate_t, gap = a_len * 0.12, a_len * 0.03
        back = mirror_t / 2.0 + plate_t + gap                  # the block's diagonal face sits this far behind
        across = self._unit(tuple(a[i] - b[i] for i in range(3)))   # along the diagonal, in the fold plane
        plate_half = a_len * 0.56
        pieces: list[dict[str, Any]] = [
            # the block behind the mirror: its diagonal face carries the kinematic plate, its back corner is cut
            {"shape": "extruded_polygon", "role": "mount", "mirror": which,
             "points": [[half, -half], [-half, half], [-half, -half + chamfer], [-half + chamfer, -half]],
             "height": cube, "position": at((-half, w), (-back, n)), "rotation": self._euler(a, w, tuple(-c for c in b)),
             "material": _MOUNT_BLACK},
            # the kinematic plate on the diagonal: it holds the mirror and the two adjusters tilt it
            {"shape": "box", "role": "plate", "mirror": which, "width": plate_half * 2.0, "height": plate_t,
             "depth": plate_half * 2.0, "position": at((-mirror_t / 2.0 - plate_t / 2.0, n)),
             "rotation": self._euler(across, n, self._cross(across, n)), "material": _MOUNT_BLACK},
            # the mirror on the plate, its face where the beam folds
            {"shape": "cylinder", "role": "mirror", "mirror": which, "radius": a_len * 0.48, "height": mirror_t,
             "position": at(), "rotation": facing,
             "material": {"color": "#f1f8fc", "metalness": 0.96, "roughness": 0.015,
                          "clearcoat": 1.0, "envMapIntensity": 2.4}},
            # its retaining ring, so the bright face reads as a mounted mirror, not a hole in the block
            {"shape": "lathe_profile", "role": "ring", "mirror": which, "segments": 40,
             "points": [[a_len * 0.465, -a_len * 0.03], [a_len * 0.535, -a_len * 0.03], [a_len * 0.535, a_len * 0.03],
                        [a_len * 0.465, a_len * 0.03], [a_len * 0.465, -a_len * 0.03]],
             "position": at((mirror_t / 2.0, n)), "rotation": facing, "material": _MOUNT_ALU},
        ]
        # the cut back face is parallel to the mirror; the adjusters stand on it in an L with the pivot (one
        # beside it across the face, one along the block), point straight back and push through to the plate
        face = -half + chamfer / 2.0
        reach_e, reach_w = chamfer * math.sqrt(2.0) * 0.25, cube * 0.3
        for e, along_w in ((-reach_e, reach_w), (reach_e, -reach_w)):
            base = ((face, a), (face, b), (-back, n), (e, across), (along_w, w))
            pieces += [
                {"shape": "cylinder", "role": "screw", "mirror": which, "radius": a_len * 0.035,
                 "height": a_len * 0.1, "position": at(*base, (-a_len * 0.05, n)), "rotation": facing,
                 "material": _KNOB_STEEL},
                {"shape": "cylinder", "role": "knob", "mirror": which, "radius": a_len * 0.09,
                 "height": a_len * 0.12, "position": at(*base, (-a_len * 0.16, n)), "rotation": facing,
                 "material": _MOUNT_BLACK},
            ]
        # the clamp: from inside the block to a collar on the post, level
        centre = at((-cube / 6.0, a), (-cube / 6.0, b), (-back, n))
        post = (0.0, centre[1], self._post_side * self._post_z)
        dx, dz = post[0] - centre[0], post[2] - centre[2]
        run = math.hypot(dx, dz) or 1e-6
        pieces += [
            {"shape": "box", "role": "clamp", "mirror": which, "width": run, "height": a_len * 0.3,
             "depth": a_len * 0.36, "position": [(centre[0] + post[0]) / 2.0, centre[1], (centre[2] + post[2]) / 2.0],
             "rotation": [0.0, math.atan2(-dz, dx), 0.0], "material": _MOUNT_BLACK},
            {"shape": "cylinder", "role": "collar", "mirror": which, "radius": self.post_diameter * 0.8,
             "height": a_len * 0.36, "position": list(post), "material": _MOUNT_BLACK},
        ]
        return pieces

    def geometry_3d(self) -> dict[str, Any]:
        """A post beside the beam on a translation stage, with a right-angle mirror mount clamped at each
        fold. The beam runs vertically between the two mirrors, parallel to the post."""

        a = self.aperture
        post_z = self._post_side * self._post_z
        post_r = self.post_diameter / 2.0
        stage_h = a * 0.5
        post_bottom = stage_h * 0.8
        clamps = [piece for which in ("entry", "exit") for piece in self._mount(which)]
        collar_tops = [c["position"][1] + c["height"] / 2.0 for c in clamps if c["role"] == "collar"]
        post_top = max(collar_tops) + a * 0.15
        steel = {"color": "#c9ced4", "metalness": 0.82, "roughness": 0.22, "preset": self.material_preset}
        stage_w, stage_d = a * 1.9, a * 1.0
        children: list[dict[str, Any]] = [
            # translation stage under the post: fixed rail, carriage, micrometer
            {"shape": "box", "width": stage_w, "height": stage_h * 0.5, "depth": stage_d,
             "position": [0.0, stage_h * 0.25, post_z], "material": _MOUNT_BLACK},
            {"shape": "box", "width": stage_w * 0.6, "height": stage_h * 0.42, "depth": stage_d * 0.86,
             "position": [0.0, stage_h * 0.66, post_z], "material": _MOUNT_ALU},
            {"shape": "cylinder", "radius": stage_h * 0.2, "height": a * 0.66,
             "position": [-stage_w * 0.52, stage_h * 0.5, post_z],
             "rotation": [0.0, 0.0, math.pi / 2.0], "material": _KNOB_STEEL},
            {"shape": "cylinder", "radius": stage_h * 0.32, "height": a * 0.28,
             "position": [-stage_w * 0.76, stage_h * 0.5, post_z],
             "rotation": [0.0, 0.0, math.pi / 2.0], "material": _MOUNT_BLACK},
            # the post both mounts clamp to
            {"shape": "cylinder", "role": "post", "radius": post_r, "height": post_top - post_bottom,
             "position": [0.0, (post_top + post_bottom) / 2.0, post_z], "material": steel},
        ]
        return {"shape": "group", "children": children + clamps}

    def optical_interfaces(self):
        """What the beam meets, in the drawing plane.

        A periscope's work is out of plane: the beam arrives at one height and
        leaves at another, having barely moved in plan. So the surface it meets
        is a ``relay`` -- the ray keeps its heading (or turns by
        ``output_angle_deg``) and gains ``rise`` in height. A plan view collapses
        that climb to a point, which is what a plan view of a periscope is.

        The face is the entrance aperture, running across the input; a turning
        periscope keeps the same entrance, because the light still arrives at the
        lower mirror before anything folds it."""

        from optodraw.core.raytrace import OpticalInterface

        half = self.aperture / 2.0
        return [OpticalInterface(
            p1=(0.0, -half),
            p2=(0.0, half),
            kind="relay",
            rise=self.rise,
            turn_deg=self.output_angle_deg,
            name="periscope",
        )]

    def physics_metadata(self) -> dict[str, Any]:
        return _optical_metadata(
            "periscope", rise=self.rise, output_angle_deg=self.output_angle_deg, aperture=self.aperture,
        )

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data.update(rise=self.rise, output_angle_deg=self.output_angle_deg, aperture=self.aperture)
        return data


class OpticalPost(Component):
    """Optical post / pedestal (Thorlabs-style): a base clamp + post-holder + post that
    raises an optic to the beam (optical) height above the table — the standing hardware
    that gives a free-space breadboard layout its real look. Place under/near an optic.

    Visualization only (clean-room parametric hardware; no machining geometry)."""

    component_type = "OpticalPost"
    height: float = 20.0
    post_diameter: float = 6.35

    def __init__(self, center=(0, 0), angle=0, height=20.0, post_diameter=6.35, **kwargs):
        self.height = max(float(height), 4.0)
        self.post_diameter = max(float(post_diameter), 1.0)
        self.base_size = float(kwargs.get("base_size", 16.0))
        _set_common_free_space_fields(self, center, angle, kwargs, color="#2b2f36", opacity=1.0, material_preset="steel", label=kwargs.get("label", "Post"))

    def symbol_2d(self) -> tuple[str, dict[str, Any]]:
        return "post", {"view": "top"}          # the 1D symbol is a side view; 2D is seen from above

    def geometry_2d(self) -> dict[str, Any]:
        b = self.base_size
        return {
            "type": "group",
            "children": [
                {"type": "rect", "cx": 0.0, "cy": 0.0, "w": b, "h": b * 0.72, "fill": "#3f4650", "stroke": "#1f242b", "stroke_width": 0.1, "opacity": 0.95},
                {"type": "circle", "cx": 0.0, "cy": 0.0, "r": self.post_diameter / 2.0, "fill": "#22262c", "stroke": "#0f1216", "stroke_width": 0.05, "opacity": 1.0},
            ],
        }

    def geometry_3d(self) -> dict[str, Any]:
        h = self.height
        base_t = min(3.0, h * 0.18)
        holder_h = (h - base_t) * 0.5
        post_h = h - base_t - holder_h
        post_r = self.post_diameter / 2.0
        anod = {"color": "#1f242b", "metalness": 0.5, "roughness": 0.5, "preset": self.material_preset}
        steel = {"color": "#c4c9cf", "metalness": 0.82, "roughness": 0.22, "preset": self.material_preset}   # stainless post
        return {
            "shape": "group",
            "children": [
                {"shape": "box", "width": self.base_size, "height": base_t, "depth": self.base_size * 0.72, "position": [0.0, base_t / 2.0, 0.0], "material": anod},
                {"shape": "cylinder", "radius": self.post_diameter * 0.9, "height": holder_h, "position": [0.0, base_t + holder_h / 2.0, 0.0], "material": anod},
                # the holder's thumbscrew that locks the post
                {"shape": "cylinder", "radius": self.post_diameter * 0.18, "height": self.post_diameter * 0.7, "rotation": [math.pi / 2.0, 0.0, 0.0],
                 "position": [0.0, base_t + holder_h * 0.8, self.post_diameter * 1.15], "material": anod},
                {"shape": "cylinder", "role": "post", "radius": post_r, "height": post_h + 1.0, "position": [0.0, base_t + holder_h + post_h / 2.0, 0.0], "material": steel},
                {"shape": "cylinder", "radius": post_r * 1.5, "height": base_t * 0.6, "position": [0.0, h, 0.0], "material": steel},  # top mount cap (optic sits here)
            ],
        }

    def ports(self) -> dict[str, Port]:
        return {"mount": Port("mount", Vec3(0.0, 0.0, 0.0), orientation_deg=0.0, width=self.base_size, kind="free_space")}

    def physics_metadata(self) -> dict[str, Any]:
        return _optical_metadata("optical_post", height=self.height, post_diameter=self.post_diameter)

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["height"] = self.height
        data["post_diameter"] = self.post_diameter
        data["base_size"] = self.base_size
        return data


@dataclass
class BeamDump(Component):
    """Beam dump / block — a horned cavity absorber that safely terminates a laser beam."""

    component_type = "BeamDump"
    aperture: float = 10.0

    def __init__(self, center=(0, 0), angle=0, aperture=10.0, **kwargs):
        self.aperture = aperture
        _set_common_free_space_fields(self, center, angle, kwargs, color="#15171b", opacity=1.0, material_preset="matte", label=kwargs.get("label", "Beam dump"))

    def geometry_2d(self) -> dict[str, Any]:
        # The section of the body in geometry_3d: ring fins round the back half, a cone that opens toward the beam (-x).
        a = self.aperture
        return {
            "type": "group",
            "children": [
                *[{"type": "rect", "cx": a * (0.08 + 0.1 * i), "cy": 0.0, "w": a * 0.045, "h": a * 1.16, "fill": self.color} for i in range(4)],
                {"type": "rect", "cx": a * 0.05, "cy": 0.0, "w": a * 0.8, "h": a * 0.84, "fill": self.color, "stroke": "#000", "stroke_width": 0.1},
                {"type": "polygon", "points": [(-a * 0.35, -a * 0.34), (a * 0.33, 0.0), (-a * 0.35, a * 0.34)], "fill": "#000000"},
            ],
        }

    def geometry_3d(self) -> dict[str, Any]:
        # A round absorber: a black body bored with a cone that opens toward the beam (-x) and ends in an apex
        # near the back, ring fins round the back half, and a stem down to the post.
        a = self.aperture
        black = {"color": self.color, "metalness": 0.15, "roughness": 0.85, "preset": "matte"}
        half = a * 0.4
        profile = [[a * 0.34, half], [0.001, -half + a * 0.12], [0.001, -half], [a * 0.42, -half], [a * 0.42, half], [a * 0.34, half]]
        return {
            "shape": "group",
            "children": [
                {"shape": "lathe_profile", "role": "body", "points": profile, "segments": 40, "rotation": [0.0, 0.0, math.pi / 2.0],
                 "position": [a * 0.05, 0.0, 0.0], "material": black},
                _ring_along_x(a * 0.34, a * 0.45, a * 0.04, _MOUNT_ALU, x=-a * 0.3304),
                *[{**_ring_along_x(a * 0.42, a * 0.58, a * 0.045, black, x=a * (0.08 + 0.1 * i)), "role": "fin"} for i in range(4)],
                _post_boss(a * 0.58, a * 0.3, x=a * 0.2),
            ],
        }

    def ports(self) -> dict[str, Port]:
        return {"in": Port("in", Vec3(-self.aperture * 0.35, 0.0, 0.0), orientation_deg=180.0, width=self.aperture * 0.6, kind="free_space")}

    def physics_metadata(self) -> dict[str, Any]:
        return _optical_metadata("beam_dump", aperture=self.aperture)

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["aperture"] = self.aperture
        return data


@dataclass
class LensTube(Component):
    """Threaded lens tube (SM-series silhouette) for stacking optics into an assembly."""

    component_type = "LensTube"
    diameter: float = 8.0
    length: float = 10.0

    def __init__(self, center=(0, 0), angle=0, diameter=8.0, length=10.0, **kwargs):
        self.diameter = diameter
        self.length = length
        _set_common_free_space_fields(self, center, angle, kwargs, color="#9aa1a9", opacity=1.0, material_preset="steel", label=kwargs.get("label", "Lens tube"))

    def geometry_2d(self) -> dict[str, Any]:
        L, d = self.length, self.diameter
        return {
            "type": "group",
            "children": [
                {"type": "rect", "cx": 0, "cy": 0, "w": L, "h": d, "fill": self.color, "stroke": "#4b5259", "stroke_width": 0.1},
                {"type": "rect", "cx": 0, "cy": 0, "w": L, "h": d * 0.62, "fill": "#6b7178", "stroke": "none", "opacity": 0.55},
                {"type": "line", "x1": -L * 0.34, "y1": -d * 0.5, "x2": -L * 0.34, "y2": d * 0.5, "stroke": "#4b5259", "stroke_width": 0.06},
                {"type": "line", "x1": L * 0.34, "y1": -d * 0.5, "x2": L * 0.34, "y2": d * 0.5, "stroke": "#4b5259", "stroke_width": 0.06},
            ],
        }

    def geometry_3d(self) -> dict[str, Any]:
        L, r = self.length, self.diameter / 2.0
        clamp, post_at = _tube_clamp(r, L * 0.2)
        return {
            "shape": "group",
            "children": [
                # a TRUE open tube (annular wall — you can see through the bore)
                _ring_along_x(r * 0.78, r, L, _MOUNT_ALU),
                # slim recessed thread reliefs + a wider front lip (clean SM-tube look)
                _rim_along_x(r * 0.99, r * 0.025, {"color": "#7c838b", "metalness": 0.7, "roughness": 0.35}, position=[-L * 0.28, 0.0, 0.0]),
                _rim_along_x(r * 0.99, r * 0.025, {"color": "#7c838b", "metalness": 0.7, "roughness": 0.35}, position=[L * 0.28, 0.0, 0.0]),
                _ring_along_x(r * 0.78, r * 1.06, L * 0.14, _MOUNT_ALU, x=-L * 0.43),
                # dark inner bore wall (a slightly smaller open tube, so the inside reads dark)
                _ring_along_x(r * 0.76, r * 0.78, L * 0.98, {"color": "#14171b", "metalness": 0.5, "roughness": 0.4}),
                *clamp,
            ],
            "post_at": post_at,
        }

    def ports(self) -> dict[str, Port]:
        return _through_ports(self.length, self.diameter * 0.78)

    def physics_metadata(self) -> dict[str, Any]:
        return _optical_metadata("lens_tube", diameter=self.diameter, length=self.length)

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["diameter"] = self.diameter
        data["length"] = self.length
        return data


@dataclass
class PlatformMount(Component):
    """Kinematic platform / prism mount (KM100PM silhouette): an L-bracket whose tilting
    platform carries an AOM, prism, or grating. Sits flat on the table; place the carried
    component on top of it."""

    component_type = "PlatformMount"
    platform: float = 14.0
    height: float = 12.0

    def __init__(self, center=(0, 0), angle=0, platform=14.0, height=12.0, **kwargs):
        self.platform = platform
        self.height = height
        _set_common_free_space_fields(self, center, angle, kwargs, color="#23282e", opacity=1.0, material_preset="steel", label=kwargs.get("label", "Platform mount"))

    def symbol_2d(self) -> tuple[str, dict[str, Any]]:
        return "platform", {"view": "top"}          # the 1D symbol is a side view; 2D is seen from above

    def geometry_2d(self) -> dict[str, Any]:
        p = self.platform
        return {
            "type": "group",
            "children": [
                {"type": "rect", "cx": 0, "cy": 0, "w": p, "h": p * 0.82, "fill": "#3f4650", "stroke": "#1b1f24", "stroke_width": 0.1},
                {"type": "rect", "cx": -p * 0.42, "cy": 0, "w": p * 0.16, "h": p * 0.82, "fill": self.color, "stroke": "#14171b", "stroke_width": 0.08},
                {"type": "circle", "cx": p * 0.28, "cy": p * 0.24, "r": p * 0.045, "fill": "#b9bfc6", "stroke": "#5b6570", "stroke_width": 0.04},
                {"type": "circle", "cx": p * 0.28, "cy": -p * 0.24, "r": p * 0.045, "fill": "#b9bfc6", "stroke": "#5b6570", "stroke_width": 0.04},
            ],
        }

    def geometry_3d(self) -> dict[str, Any]:
        p, h = self.platform, self.height
        return {
            "shape": "group",
            "children": [
                # vertical arm of the L-bracket
                {"shape": "box", "width": p * 0.2, "height": h, "depth": p * 0.82, "position": [-p * 0.4, h * 0.5, 0.0], "material": _MOUNT_BLACK},
                # kinematic platform plate cantilevered from the arm
                {"shape": "box", "width": p * 0.99, "height": p * 0.07, "depth": p * 0.8, "position": [p * 0.005, h * 0.92, 0.0], "material": {"color": "#3f4650", "metalness": 0.55, "roughness": 0.4, "preset": "steel"}},
                # base foot
                {"shape": "box", "width": p * 0.55, "height": p * 0.08, "depth": p * 0.82, "position": [-p * 0.28, p * 0.04, 0.0], "material": _MOUNT_BLACK},
                # fixed lower arm under the free corners: the adjusters push up from it through the platform
                {"shape": "box", "width": p * 0.85, "height": p * 0.08, "depth": p * 0.82, "position": [p * 0.025, h * 0.47 - p * 0.04, 0.0], "material": _MOUNT_BLACK},
                # two adjuster barrels from the lower arm through the platform's free corners, knurled caps above
                *[c for sz in (p * 0.26, -p * 0.26) for c in (
                    {"shape": "cylinder", "radius": p * 0.05, "height": h * 0.5, "position": [p * 0.34, h * 0.72, sz], "material": _KNOB_STEEL},
                    {"shape": "cylinder", "radius": p * 0.09, "height": h * 0.22, "position": [p * 0.34, h * 1.08, sz], "material": _MOUNT_BLACK},
                )],
                # pivot boss on the arm, under the platform
                {"shape": "cylinder", "radius": p * 0.07, "height": h * 0.14, "position": [-p * 0.26, h * 0.83, 0.0], "material": _KNOB_STEEL},
            ],
        }

    def ports(self) -> dict[str, Port]:
        return {}

    def physics_metadata(self) -> dict[str, Any]:
        return _optical_metadata("platform_mount", platform=self.platform, height=self.height)

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["platform"] = self.platform
        data["height"] = self.height
        return data


@dataclass
class TranslationStage(Component):
    """Linear translation stage with travel-range metadata."""

    component_type = "TranslationStage"
    # The mechanical body stays at its origin when its artwork is resized.
    _art_anchor_at_origin = True
    length: float = 28.0
    width: float = 18.0
    travel_range_mm: float = 25.0
    axis: str = "x"

    def __init__(self, center=(0, 0), angle=0, length=28.0, width=18.0, travel_range_mm=25.0, axis="x", **kwargs):
        self.length = length
        self.width = width
        self.travel_range_mm = travel_range_mm
        self.axis = axis
        self.lead_pitch_mm = kwargs.get("lead_pitch_mm", 1.0)
        _set_common_free_space_fields(self, center, angle, kwargs, color="#52525b", opacity=1.0, material_preset="steel", label=kwargs.get("label", "Stage"))

    def geometry_2d(self) -> dict[str, Any]:
        return {
            "type": "group",
            "children": [
                {"type": "rect", "cx": 0.0, "cy": 0.0, "w": self.length, "h": self.width, "fill": self.color, "stroke": "#27272a", "stroke_width": 0.08},
                {"type": "rect", "cx": 0.0, "cy": 0.0, "w": self.length * 0.78, "h": self.width * 0.52, "fill": "#71717a", "stroke": "#3f3f46", "stroke_width": 0.06},
                {"type": "line", "x1": -self.length * 0.34, "y1": 0.0, "x2": self.length * 0.34, "y2": 0.0, "stroke": "#d4d4d8", "stroke_width": 0.11, "opacity": 0.9},
                {"type": "circle", "cx": self.length * 0.4, "cy": 0.0, "r": self.width * 0.1, "fill": "#e4e4e7", "stroke": "#52525b", "stroke_width": 0.04},
            ],
        }

    def geometry_3d(self) -> dict[str, Any]:
        # A linear stage: a black base, a satin aluminium carriage on it with a grid of tapped holes, and at the
        # -x end a bracket on the base holding the micrometer along the travel axis, level with the carriage it
        # pushes (sleeve, then the thimble with its ratchet).
        L, W = self.length, self.width
        base_h, top_h = W * 0.2, W * 0.18
        black = {"color": "#24282e", "metalness": 0.42, "roughness": 0.5, "preset": "aluminum"}
        alu = {"color": "#c3c8ce", "metalness": 0.55, "roughness": 0.4, "preset": "aluminum"}
        steel = {"color": "#d0d4d9", "metalness": 0.6, "roughness": 0.35, "preset": "steel"}
        c_len, c_x = L * 0.82, L * 0.09
        axis_y = base_h + top_h / 2.0
        bracket_x = -L / 2.0 + L * 0.04
        sleeve, thimble = L * 0.22, L * 0.13
        children: list[dict[str, Any]] = [
            {"shape": "box", "role": "base", "width": L, "height": base_h, "depth": W, "position": [0.0, base_h / 2.0, 0.0], "material": black},
            {"shape": "box", "role": "carriage", "width": c_len, "height": top_h, "depth": W * 0.92, "position": [c_x, base_h + top_h / 2.0, 0.0], "material": alu},
            {"shape": "box", "role": "bracket", "width": L * 0.08, "height": top_h * 1.5, "depth": W * 0.36, "position": [bracket_x, base_h + top_h * 0.75, 0.0], "material": black},
            {**_cylinder_along_x(W * 0.06, sleeve, steel, position=[bracket_x - L * 0.04 - sleeve / 2.0, axis_y, 0.0]), "role": "micrometer"},
            {**_cylinder_along_x(W * 0.1, thimble, black, position=[bracket_x - L * 0.04 - sleeve - thimble / 2.0, axis_y, 0.0]), "role": "micrometer"},
            {**_cylinder_along_x(W * 0.05, L * 0.04, steel, position=[bracket_x - L * 0.04 - sleeve - thimble - L * 0.02, axis_y, 0.0]), "role": "micrometer"},
        ]
        top = base_h + top_h
        children += [{"shape": "cylinder", "radius": W * 0.025, "height": 0.06, "position": [c_x + i * c_len * 0.25, top, j * W * 0.28],
                      "material": {"color": "#33383f", "roughness": 0.6}} for i in (-1, 0, 1) for j in (-1, 0, 1)]
        return {"shape": "group", "children": children}

    def ports(self) -> dict[str, Port]:
        # The edges of the stage the 2D art draws: 0.84 cm wide in the 1.08 cm height of the pic od translation
        # (stage and micrometer), which is the stage's width.
        return _through_ports(self.width * 0.84 / 1.08, self.width)

    def physics_metadata(self) -> dict[str, Any]:
        return _optical_metadata("translation_stage", axis=self.axis, travel_range_mm=self.travel_range_mm, lead_pitch_mm=self.lead_pitch_mm)


@dataclass
class RotationStage(Component):
    """Rotary stage with angular-range metadata."""

    component_type = "RotationStage"
    diameter: float = 26.0
    thickness: float = 6.0
    rotation_range_deg: float = 360.0
    angular_resolution_deg: float = 0.1

    def __init__(self, center=(0, 0), angle=0, diameter=26.0, thickness=6.0, rotation_range_deg=360.0, angular_resolution_deg=0.1, **kwargs):
        self.diameter = diameter
        self.thickness = thickness
        self.rotation_range_deg = rotation_range_deg
        self.angular_resolution_deg = angular_resolution_deg
        _set_common_free_space_fields(self, center, angle, kwargs, color="#52525b", opacity=1.0, material_preset="steel", label=kwargs.get("label", "Rot Stage"))

    def geometry_2d(self) -> dict[str, Any]:
        ring_r = self.diameter * 0.36
        return {
            "type": "group",
            "children": [
                {"type": "circle", "cx": 0.0, "cy": 0.0, "r": self.diameter / 2.0, "fill": self.color, "stroke": "#27272a", "stroke_width": 0.08},
                {"type": "circle", "cx": 0.0, "cy": 0.0, "r": ring_r, "fill": "#71717a", "stroke": "#3f3f46", "stroke_width": 0.06},
                {"type": "path", "d": f"M {ring_r * 0.1} {-ring_r * 0.95} A {ring_r} {ring_r} 0 1 1 {ring_r * 0.1} {ring_r * 0.95}", "fill": "none", "stroke": "#e4e4e7", "stroke_width": 0.08, "opacity": 0.85},
                {"type": "polyline", "points": [(ring_r * 0.95, 0.0), (ring_r * 1.2, 0.12), (ring_r * 1.2, -0.12)], "closed": True, "fill": "#e4e4e7", "stroke": "#d4d4d8", "stroke_width": 0.03},
            ],
        }

    def geometry_3d(self) -> dict[str, Any]:
        # A rotary stage sits FLAT on the table (rotation axis vertical), like the
        # translation stage — a base puck with a rotating top platform you mount onto.
        R, T = self.diameter / 2.0, self.thickness
        children = [
            # fixed base housing (axis vertical = default cylinder along y)
            {"shape": "cylinder", "radius": R, "height": T, "material": {"color": self.color, "metalness": 0.55, "roughness": 0.35, "preset": self.material_preset}},
            # rotating top platform (proud of the top face)
            {"shape": "cylinder", "radius": R * 0.8, "height": T * 0.5, "position": [0.0, T * 0.72, 0.0], "material": {"color": "#a1a1aa", "metalness": 0.6, "roughness": 0.26}},
            # central mounting bore
            {"shape": "cylinder", "radius": R * 0.3, "height": T * 1.3, "material": {"color": "#3f3f46", "metalness": 0.5, "roughness": 0.42}},
        ]
        # graduation ticks around the top edge (x-z plane)
        for i in range(24):
            a = i * math.pi / 12.0
            children.append({"shape": "box", "width": R * 0.05, "height": T * 0.22, "depth": R * 0.12,
                             "position": [R * 0.9 * math.cos(a), T * 0.5, R * 0.9 * math.sin(a)],
                             "rotation": [0.0, -a, 0.0], "material": {"color": "#e4e4e7", "metalness": 0.4, "roughness": 0.4}})
        # side micrometer / lock knob sticking out
        children.append(_cylinder_along_x(R * 0.16, R * 0.5, {"color": "#71717a", "metalness": 0.55, "roughness": 0.3}, position=[R * 1.05, T * 0.25, 0.0]))
        return {"shape": "group", "children": children}

    def ports(self) -> dict[str, Port]:
        return _through_ports(self.diameter, self.diameter)

    def physics_metadata(self) -> dict[str, Any]:
        return _optical_metadata("rotation_stage", rotation_range_deg=self.rotation_range_deg, angular_resolution_deg=self.angular_resolution_deg)


@dataclass
class KinematicMount(Component):
    """Adjustable kinematic optic mount."""

    component_type = "KinematicMount"
    optic_diameter: float = 12.7
    base_width: float = 20.0
    adjustment_range_deg: float = 4.0

    def __init__(self, center=(0, 0), angle=0, optic_diameter=12.7, base_width=20.0, adjustment_range_deg=4.0, **kwargs):
        self.optic_diameter = optic_diameter
        self.base_width = base_width
        self.adjustment_range_deg = adjustment_range_deg
        _set_common_free_space_fields(self, center, angle, kwargs, color="#4b5563", opacity=1.0, material_preset="steel", label=kwargs.get("label", "Mount"))

    def geometry_2d(self) -> dict[str, Any]:
        return {
            "type": "group",
            "children": [
                {"type": "rect", "cx": 0.0, "cy": -self.base_width * 0.12, "w": self.base_width, "h": self.base_width * 0.24, "fill": self.color, "stroke": "#1f2937", "stroke_width": 0.08},
                {"type": "circle", "cx": 0.0, "cy": self.base_width * 0.24, "r": self.optic_diameter / 2.0, "fill": "#9ca3af", "stroke": "#374151", "stroke_width": 0.07},
                {"type": "circle", "cx": 0.0, "cy": self.base_width * 0.24, "r": self.optic_diameter * 0.31, "fill": "#d1d5db", "stroke": "#6b7280", "stroke_width": 0.05},
                {"type": "line", "x1": -self.base_width * 0.35, "y1": -self.base_width * 0.12, "x2": self.base_width * 0.35, "y2": -self.base_width * 0.12, "stroke": "#e5e7eb", "stroke_width": 0.09, "opacity": 0.82},
            ],
        }

    def geometry_3d(self) -> dict[str, Any]:
        """A square kinematic mount (KM100 silhouette, the shared mount of the mirrors): the optic in the bore
        of the front plate, an L back plate, two adjusters through the ends of the L and the pivot at its
        corner. Optic axis along x like all optics."""

        w = self.base_width
        opt_r = min(self.optic_diameter / 2.0, w * (0.5 - 1.0 / 7.0))
        front = -w * 0.1
        return {
            "shape": "group",
            "children": [
                _cylinder_along_x(opt_r, w / 7.0, {"color": "#dbe4ec", "metalness": 0.85, "roughness": 0.08, "preset": "glass"}, position=[front + w / 14.0 - w * 0.01, 0.0, 0.0]),
                *_kinematic_mount(front, w, opt_r),
            ],
        }

    def ports(self) -> dict[str, Port]:
        # The light enters the optic at the front plate and leaves through the open back plate: their outer faces
        # as geometry_3d builds them (front plate w/7, gap w/35, back plate 0.114 w, from x = -0.1 w).
        w = self.base_width
        front, rear = -w * 0.1, w * (-0.1 + 1.0 / 7.0 + 1.0 / 35.0 + 0.114)
        span = max(self.base_width, self.optic_diameter)
        return {
            "in": Port("in", Vec3(front, 0.0, 0.0), orientation_deg=180.0, width=span, kind="free_space"),
            "out": Port("out", Vec3(rear, 0.0, 0.0), orientation_deg=0.0, width=span, kind="free_space"),
        }

    def physics_metadata(self) -> dict[str, Any]:
        return _optical_metadata("kinematic_mount", optic_diameter=self.optic_diameter, adjustment_range_deg=self.adjustment_range_deg)


@dataclass
class CryostatWindow(Component):
    """Cryostat optical window with coating and thermal metadata."""

    component_type = "CryostatWindow"
    aperture: float = 14.0
    thickness: float = 4.0
    material: str = "sapphire"
    temperature_k: float = 77.0

    def __init__(self, center=(0, 0), angle=0, aperture=14.0, thickness=4.0, material="sapphire", temperature_k=77.0, **kwargs):
        self.aperture = aperture
        self.thickness = thickness
        self.material = material
        self.temperature_k = temperature_k
        self.coating = kwargs.get("coating", "ar")
        _set_common_free_space_fields(self, center, angle, kwargs, color="#bae6fd", opacity=0.5, material_preset="glass", label=kwargs.get("label", "Cryo Window"))

    def geometry_2d(self) -> dict[str, Any]:
        a = self.aperture
        bolts = [{"type": "circle", "cx": a * 0.46 * math.cos(i * math.pi / 3), "cy": a * 0.46 * math.sin(i * math.pi / 3), "r": a * 0.045, "fill": "#1f2937", "stroke": "#0b1b2b", "stroke_width": 0.03} for i in range(6)]
        return {
            "type": "group",
            "children": [
                # mounting flange ring
                {"type": "circle", "cx": 0.0, "cy": 0.0, "r": a * 0.55, "fill": "#3a5566", "stroke": "#1f2d38", "stroke_width": 0.08},
                # AR-coated window glass
                {"type": "circle", "cx": 0.0, "cy": 0.0, "r": a * 0.4, "fill": self.color, "stroke": "#0891b2", "stroke_width": 0.07, "opacity": self.opacity},
                {"type": "line", "x1": -a * 0.26, "y1": -a * 0.1, "x2": a * 0.28, "y2": a * 0.12, "stroke": "#ecfeff", "stroke_width": 0.08, "opacity": 0.5},
                *bolts,
            ],
        }

    def geometry_3d(self) -> dict[str, Any]:
        a, t = self.aperture, self.thickness
        bolts = [{"shape": "cylinder", "radius": a * 0.045, "height": t * 1.2, "rotation": [0.0, 0.0, math.pi / 2.0],
                  "position": [0.0, a * 0.46 * math.cos(i * math.pi / 3), a * 0.46 * math.sin(i * math.pi / 3)],
                  "material": {"color": "#1f2937", "metalness": 0.6, "roughness": 0.3}} for i in range(6)]
        return {
            "shape": "group",
            "children": [
                # mounting flange (steel ring)
                _ring_along_x(a * 0.4, a * 0.55, t * 0.7, {"color": "#3a5566", "metalness": 0.55, "roughness": 0.35, "preset": "steel"}, x=-t * 0.1),
                _post_boss(a * 0.55, t * 0.68, x=-t * 0.1),
                # AR-coated window glass
                _cylinder_along_x(a * 0.4, t, {**_transparent_material(self.color, self.opacity, self.material_preset), "transmission": 0.6, "ior": 1.75, "clearcoat": 0.8}),
                *bolts,
            ],
        }

    def ports(self) -> dict[str, Port]:
        # The faces of the glass the 2D art draws: 0.07 cm in the 0.72 cm of the pic od window, the flange's 1.1 a.
        return _through_ports(self.aperture * 1.1 * 0.07 / 0.72, self.aperture)

    def physics_metadata(self) -> dict[str, Any]:
        return _optical_metadata("cryostat_window", material=self.material, temperature_k=self.temperature_k, coating=self.coating)


@dataclass
class VacuumChamber(Component):
    """Cylindrical vacuum chamber with optical ports and pressure metadata."""

    component_type = "VacuumChamber"
    diameter: float = 46.0
    length: float = 56.0
    viewport_diameter: float = 16.0
    pressure_mbar: float = 1e-6

    def __init__(self, center=(0, 0), angle=0, diameter=46.0, length=56.0, viewport_diameter=16.0, pressure_mbar=1e-6, **kwargs):
        self.diameter = diameter
        self.length = length
        self.viewport_diameter = viewport_diameter
        self.pressure_mbar = pressure_mbar
        self.window_count = kwargs.get("window_count", 4)
        _set_common_free_space_fields(self, center, angle, kwargs, color="#374151", opacity=1.0, material_preset="steel", label=kwargs.get("label", "Vacuum Chamber"))
        self.base_mount = str(kwargs.get("base_mount", "none"))      # it stands on its feet on the table

    def geometry_2d(self) -> dict[str, Any]:
        children = [
            {"type": "rect", "cx": 0.0, "cy": 0.0, "w": self.length, "h": self.diameter, "fill": self.color, "stroke": "#111827", "stroke_width": 0.1},
            {"type": "rect", "cx": 0.0, "cy": 0.0, "w": self.length * 0.9, "h": self.diameter * 0.82, "fill": "#4b5563", "stroke": "#1f2937", "stroke_width": 0.07, "opacity": 0.9},
        ]
        radius = self.diameter * 0.38
        for idx in range(max(self.window_count, 0)):
            theta = 2.0 * math.pi * idx / max(self.window_count, 1)
            children.append(
                {
                    "type": "circle",
                    "cx": math.cos(theta) * radius,
                    "cy": math.sin(theta) * radius,
                    "r": self.viewport_diameter * 0.19,
                    "fill": "#bae6fd",
                    "stroke": "#0369a1",
                    "stroke_width": 0.05,
                    "opacity": 0.55,
                }
            )
        return {"type": "group", "children": children}

    def geometry_3d(self) -> dict[str, Any]:
        R, L = self.diameter / 2.0, self.length
        steel = {"color": "#475563", "metalness": 0.6, "roughness": 0.34, "preset": "steel"}
        flange_thickness = min(L * 0.06, R * 0.25)
        window_thickness = max(L * 0.015, 0.3)
        viewport_radius = self.viewport_diameter / 2.0
        feet = max(BEAM_HEIGHT - R * 0.97, R * 0.22)
        return {
            "shape": "group",
            "children": [
                # hollow vessel and end plates leave a clear optical channel
                _ring_along_x(R * 0.8, R, L, {"color": self.color, "metalness": 0.62, "roughness": 0.36, "preset": self.material_preset}),
                # the end plates 1 % inside the vessel's wall and 1 % proud of its ends
                _ring_along_x(viewport_radius, R * 0.99, flange_thickness, steel, x=-L * 0.5 + flange_thickness * 0.49),
                _ring_along_x(viewport_radius, R * 0.99, flange_thickness, steel, x=L * 0.5 - flange_thickness * 0.49),
                # CF flange rings at both ends
                _rim_along_x(R * 1.02, R * 0.07, steel, position=[L * 0.5, 0.0, 0.0]),
                _rim_along_x(R * 1.02, R * 0.07, steel, position=[-L * 0.5, 0.0, 0.0]),
                # glass seals both optical ports without blocking the vessel bore
                _cylinder_along_x(viewport_radius, window_thickness, {**_transparent_material("#bae6fd", 0.45, "glass"), "transmission": 0.5, "ior": 1.46}, position=[-L * 0.5 - window_thickness * 0.5, 0.0, 0.0]),
                _cylinder_along_x(viewport_radius, window_thickness, {**_transparent_material("#bae6fd", 0.45, "glass"), "transmission": 0.5, "ior": 1.46}, position=[L * 0.5 + window_thickness * 0.5, 0.0, 0.0]),
                # top pump / feedthrough port
                {"shape": "cylinder", "radius": R * 0.2, "height": R * 0.55, "position": [L * 0.05, R * 1.05, 0.0], "material": steel},
                {"shape": "torus", "radius": R * 0.22, "tube": R * 0.05, "rotation": [math.pi / 2.0, 0.0, 0.0], "position": [L * 0.05, R * 1.32, 0.0], "material": steel},
                # support feet from the vessel down to the table: the chamber stands on them, not on a post
                *[{"shape": "box", "width": L * 0.1, "height": feet, "depth": R * 0.3, "position": [sx * L * 0.3, -BEAM_HEIGHT + feet / 2.0, 0.0], "material": {"color": "#3f3f46", "metalness": 0.5, "roughness": 0.4, "preset": "steel"}} for sx in (-1, 1)],
            ],
        }

    def ports(self) -> dict[str, Port]:
        return _through_ports(self.length, self.viewport_diameter)

    def physics_metadata(self) -> dict[str, Any]:
        return _optical_metadata("vacuum_chamber", pressure_mbar=self.pressure_mbar, window_count=self.window_count, viewport_diameter=self.viewport_diameter)
