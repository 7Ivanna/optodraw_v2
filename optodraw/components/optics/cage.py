"""30 mm cage-system parts and a motorized steering mirror, for a fiber-coupled microscope over a cryostat.

Sizes come from the parts' data sheets (30 mm cage: rods 30 mm apart, 6 mm rods, 41.3 mm cubes; NEMA 17:
42.3 mm) at the bench scale, where a 1 inch optic is 10 units (one unit is 2.54 mm). The 3D local frame is x
along the beam, y up, z across (z = -y of the 2D plan); port z is the height above the bench beam plane, as on
``Periscope``.

Visualization only (clean-room parametric hardware; no machining geometry)."""

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
    _ring_along_x,
    _set_common_free_space_fields,
)
from .beamsplitters import NonPolarizingBeamSplitter
from .mirrors import Mirror
from .polarization_optics import WavePlate

UNIT_MM = 2.54                       # one scene unit
ROD_HALF = 15.0 / UNIT_MM            # rods sit 30 mm apart: +-15 mm from the axis
ROD_R = 3.0 / UNIT_MM                # 6 mm rods
CUBE_HALF = 41.3 / 2.0 / UNIT_MM     # a 30 mm cage cube is 41.3 mm on a side
WALL = 3.0 / UNIT_MM
BORE = 4.6                           # an SM1 bore, a hair under the 1 inch optic radius
GLASS_HALF = 5.0                     # a 1 inch beamsplitter cube
NEMA = 42.3 / UNIT_MM                # a NEMA 17 stepper: 42.3 mm square
NEMA_LEN = 40.0 / UNIT_MM



@dataclass(frozen=True)
class CageSize:
    """The sizes of one cage system, in scene units: where its rods sit, their radius, the cube, its walls, the
    bore of a face and the beamsplitter cube or optic it holds."""

    mm: int
    rod_half: float
    rod_r: float
    cube_half: float
    wall: float
    bore: float
    glass_half: float


# 30 mm: rods 30 mm apart, 41.3 mm cubes (CCM1, KCB1), SM1 bores, 1 inch optics.
# 60 mm: rods 60 mm apart, 76.2 mm cubes (LC6W, KCB2), SM2 bores, 2 inch optics.
CAGE_SIZES = {
    30: CageSize(30, ROD_HALF, ROD_R, CUBE_HALF, WALL, BORE, GLASS_HALF),
    60: CageSize(60, 30.0 / UNIT_MM, ROD_R, 76.2 / 2.0 / UNIT_MM, 4.0 / UNIT_MM, 9.6, 10.0),
}


def cage_size(mm: Any) -> CageSize:
    """The cage system of ``mm`` (30 or 60)."""

    try:
        return CAGE_SIZES[int(mm)]
    except (KeyError, TypeError, ValueError):
        raise ValueError(f"cage is 30 or 60 (mm), not {mm!r}") from None


GLASS = {"color": "#bcd7ea", "opacity": 0.4, "transparent": True, "preset": "glass"}
ROD = {"color": "#c9ced4", "metalness": 0.6, "roughness": 0.3, "preset": "steel"}
LABEL_BLUE = {"color": "#2f6fd1", "metalness": 0.2, "roughness": 0.5}
MOTOR_BLACK = {"color": "#1b1e22", "metalness": 0.35, "roughness": 0.55}
MOTOR_CAP = {"color": "#9aa1a9", "metalness": 0.6, "roughness": 0.35, "preset": "steel"}
RED = {"color": "#c0282f", "metalness": 0.3, "roughness": 0.5}
WHITE = {"color": "#eceae4", "metalness": 0.05, "roughness": 0.7}
GREY_CABINET = {"color": "#c9cdd2", "metalness": 0.3, "roughness": 0.5}
HOSE = {"color": "#202326", "metalness": 0.1, "roughness": 0.8}


# ---------------------------------------------------------------------------------------------- 3D maths
# Solids carry Euler angles (three.js order XYZ: R = Rx Ry Rz). To place a sub-assembly in another
# orientation, each solid's rotation and position are composed with the assembly's rotation here.

def _rx(a):
    c, s = math.cos(a), math.sin(a)
    return [[1, 0, 0], [0, c, -s], [0, s, c]]


def _ry(a):
    c, s = math.cos(a), math.sin(a)
    return [[c, 0, s], [0, 1, 0], [-s, 0, c]]


def _rz(a):
    c, s = math.cos(a), math.sin(a)
    return [[c, -s, 0], [s, c, 0], [0, 0, 1]]


def _mul(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]


def _apply(m, v):
    return [sum(m[i][k] * v[k] for k in range(3)) for i in range(3)]


def _euler_matrix(e):
    return _mul(_mul(_rx(e[0]), _ry(e[1])), _rz(e[2]))


def _matrix_euler(m):
    y = math.asin(max(-1.0, min(1.0, m[0][2])))
    if abs(m[0][2]) < 0.9999999:
        return [math.atan2(-m[1][2], m[2][2]), y, math.atan2(-m[0][1], m[0][0])]
    return [math.atan2(m[2][1], m[1][1]), y, 0.0]


def place(solids: list[dict[str, Any]], rotation=(0.0, 0.0, 0.0), offset=(0.0, 0.0, 0.0)) -> list[dict[str, Any]]:
    """The solids turned by ``rotation`` (Euler XYZ) about the origin, then moved by ``offset``."""

    r = _euler_matrix(rotation)
    out = []
    for solid in solids:
        moved = dict(solid)
        p = _apply(r, solid.get("position", [0.0, 0.0, 0.0]))
        moved["position"] = [p[i] + offset[i] for i in range(3)]
        moved["rotation"] = _matrix_euler(_mul(r, _euler_matrix(solid.get("rotation", [0.0, 0.0, 0.0]))))
        out.append(moved)
    return out


def _turn(travel_in, travel_out):
    """The Euler rotation that turns the canonical fold (travel +x in, -y out) into ``travel_in`` -> ``travel_out``."""

    a, b = list(travel_in), [-v for v in travel_out]               # images of +x and +y
    c = [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]
    m = [[a[i], b[i], c[i]] for i in range(3)]                     # columns: images of x, y, z
    return _matrix_euler(m)


# ---------------------------------------------------------------------------------------------- 3D helpers

def _square(half: float) -> list[tuple[float, float]]:
    return [(-half, -half), (half, -half), (half, half), (-half, half)]


def _circle(r: float, n: int = 32, cx: float = 0.0, cy: float = 0.0) -> list[tuple[float, float]]:
    return [(cx + r * math.cos(2 * math.pi * k / n), cy + r * math.sin(2 * math.pi * k / n)) for k in range(n)]


def _plate(axis: str, at: float, half: float, thick: float, bore: float | None, material=_MOUNT_BLACK,
           centre=(0.0, 0.0, 0.0)) -> dict[str, Any]:
    """A square plate across ``axis`` centred at ``at`` on that axis, with a round bore (or none)."""

    cx, cy, cz = centre
    plate: dict[str, Any] = {"shape": "extruded_polygon", "points": _square(half), "height": thick,
                             "holes": [_circle(bore)] if bore else [], "material": material, "role": "plate"}
    if axis == "y":         # extrudes up from its position
        plate["position"] = [cx, cy + at - thick / 2.0, cz]
    elif axis == "x":       # turned about z: extrudes toward -x from its position
        plate["position"] = [cx + at + thick / 2.0, cy, cz]
        plate["rotation"] = [0.0, 0.0, math.pi / 2.0]
    else:                   # turned about x: extrudes toward +z
        plate["position"] = [cx, cy, cz + at - thick / 2.0]
        plate["rotation"] = [math.pi / 2.0, 0.0, 0.0]
    return plate


def cage_cube(centre=(0.0, 0.0, 0.0), coating_rotation=(0.0, math.pi / 4, 0.0), coating_color="#ffffff",
              glass=True, tab=True, size: CageSize = CAGE_SIZES[30]) -> list[dict[str, Any]]:
    """A cage cube (CCM1 kind for 30 mm, LC6W for 60 mm: black, a bore in each face) holding a beamsplitter cube.

    ``coating_rotation`` turns the diagonal coating; ``coating_color`` tints a dichroic; ``glass=False`` leaves
    the cube empty (a KCB1C holding a plate optic instead)."""

    h, t, g = size.cube_half, size.wall, size.glass_half
    cx, cy, cz = centre
    out: list[dict[str, Any]] = []
    for axis in ("x", "y", "z"):
        for sign in (-1, 1):
            out.append(_plate(axis, sign * (h - t / 2.0), h, t, size.bore, centre=centre))
    for sy in (-1, 1):
        for sz in (-1, 1):
            out.append({"shape": "box", "width": 2 * h, "height": t, "depth": t, "material": _MOUNT_BLACK,
                        "position": [cx, cy + sy * (h - t / 2), cz + sz * (h - t / 2)], "role": "edge"})
    if glass:
        out.append({"shape": "box", "width": 2 * g, "height": 2 * g, "depth": 2 * g,
                    "position": [cx, cy, cz], "material": GLASS, "role": "glass"})
        out.append({"shape": "box", "width": 2.8 * g, "height": 0.12, "depth": 2 * g * 0.98,
                    "position": [cx, cy, cz], "rotation": list(coating_rotation),
                    "material": {"color": coating_color, "opacity": 0.6, "transparent": True}, "role": "coating"})
    if tab:
        out.append({"shape": "box", "width": h, "height": t, "depth": h, "position": [cx, cy - h - t / 2.0, cz],
                    "material": _MOUNT_BLACK, "role": "tab"})
    return out


def kcb1(travel_in, travel_out, centre=(0.0, 0.0, 0.0), size: CageSize = CAGE_SIZES[30]) -> list[dict[str, Any]]:
    """A right-angle kinematic cage block (KCB1C for 30 mm, KCB2 for 60 mm), from the KCB1C drawing: a triangular
    prism one cube on a side. Light enters one square face, turns on the 45 degree mirror behind the hypotenuse
    and leaves the other square face; each square face has its SM1 port and four blind cage-rod bores. The
    kinematic plate on the hypotenuse is 66.1 / 48.3 of a side wide and carries three actuators: the pitch and yaw
    knobs at opposite corners and the Z screw at a third. The triangular ends are solid, each with a mounting
    tap 17.8 / 48.3 of a side from both square faces. Built for travel +x in, -y out, then turned."""

    h, t = size.cube_half, size.wall
    side = 2 * h
    # the square faces x = -h (in) and y = -h (out); counter-clockwise, so the extruded faces point outward
    tri = [(-h, -h), (h, -h), (-h, h)]
    dark = {"color": "#121417", "metalness": 0.3, "roughness": 0.6}
    k = 1 / math.sqrt(2)
    solids: list[dict[str, Any]] = [
        # the solid triangular ends: an outline in (x, y) extruded along z (turned about x, the outline's v is y)
        *[{"shape": "extruded_polygon", "points": tri, "height": t * 1.6,
           "position": [0.0, 0.0, (h - t * 1.6) if s > 0 else -h], "rotation": [math.pi / 2, 0.0, 0.0],
           "material": _MOUNT_BLACK, "role": "end"} for s in (-1, 1)],
        _plate("x", -h + t / 2, h, t, size.bore),            # entrance face, its port
        _plate("y", -h + t / 2, h, t, size.bore),            # exit face, its port
    ]
    # the four blind rod bores on each square face
    for sa in (-1, 1):
        for sb in (-1, 1):
            solids.append({**_cylinder_along_x(size.rod_r, 0.12, dark, position=[-h - 0.05, sa * size.rod_half, sb * size.rod_half]), "role": "rod bore"})
            solids.append({"shape": "cylinder", "radius": size.rod_r, "height": 0.12, "material": dark, "role": "rod bore",
                           "position": [sa * size.rod_half, -h - 0.05, sb * size.rod_half]})
    # the mounting tap on each triangular end, 17.8/48.3 of a side from both square faces
    tap = -h + side * 17.8 / 48.3
    for sz in (-1, 1):
        solids.append({"shape": "cylinder", "radius": side * 0.07, "height": 0.12, "material": dark, "role": "mounting tap",
                       "position": [tap, tap, sz * (h + 0.05)], "rotation": [math.pi / 2, 0.0, 0.0]})
    # the kinematic plate on the hypotenuse and the mirror behind it
    plate_w, plate_t = side * 66.1 / 48.3, side * 0.12
    off = plate_t / 2 + 0.05
    solids.append({"shape": "box", "width": plate_w, "height": plate_t, "depth": side * 0.94, "role": "kinematic plate",
                   "position": [off * k, off * k, 0.0], "rotation": [0.0, 0.0, -math.pi / 4], "material": _MOUNT_BLACK})
    solids.append({"shape": "cylinder", "radius": size.glass_half, "height": 0.8, "position": [-0.35, -0.35, 0.0],
                   "rotation": [0.0, 0.0, -math.pi / 4], "material": {"color": "#e8eef3", "metalness": 0.9, "roughness": 0.08},
                   "role": "mirror"})
    # actuators, 33.1/48.3 of a side apart along the plate and across it: knobs at two opposite corners, the Z screw
    a = side * 33.1 / 48.3 / 2
    face = plate_t + 0.05
    # seen from the plate side as the drawing's auxiliary view: knobs top right and bottom left, the Z screw bottom right
    for along, across, role in ((a, -a, "pitch knob"), (-a, a, "yaw knob"), (a, a, "Z actuator")):
        knob = role != "Z actuator"
        r, l = (side * 0.085, side * 0.2) if knob else (side * 0.04, side * 0.08)
        cx = along * k + k * (face + l / 2)
        cy = -along * k + k * (face + l / 2)
        solids.append({"shape": "cylinder", "radius": r, "height": l, "position": [cx, cy, across],
                       "rotation": [0.0, 0.0, -math.pi / 4], "material": _MOUNT_BLACK if knob else _KNOB_STEEL, "role": role})
        if knob:                                            # the steel actuator between the plate and its knob
            solids.append({"shape": "cylinder", "radius": side * 0.03, "height": face + 0.1, "role": "actuator",
                           "position": [along * k + k * (face / 2), -along * k + k * (face / 2), across],
                           "rotation": [0.0, 0.0, -math.pi / 4], "material": _KNOB_STEEL})
    return place(solids, _turn(travel_in, travel_out), centre)


def _rods_x(x0: float, x1: float, centre=(0.0, 0.0, 0.0), size: CageSize = CAGE_SIZES[30]) -> list[dict[str, Any]]:
    cx, cy, cz = centre
    r, a = size.rod_r, size.rod_half
    return [{**_cylinder_along_x(r, x1 - x0, ROD, position=[cx + (x0 + x1) / 2, cy + sy * a, cz + sz * a]),
             "role": "rod"} for sy in (-1, 1) for sz in (-1, 1)]


def _rods_y(y0: float, y1: float, x: float = 0.0, z: float = 0.0) -> list[dict[str, Any]]:
    return [{"shape": "cylinder", "radius": ROD_R, "height": y1 - y0, "material": ROD, "role": "rod",
             "position": [x + sx * ROD_HALF, (y0 + y1) / 2, z + sz * ROD_HALF]} for sx in (-1, 1) for sz in (-1, 1)]


def _rods_z(z0: float, z1: float, y: float = 0.0) -> list[dict[str, Any]]:
    return [{"shape": "cylinder", "radius": ROD_R, "height": z1 - z0, "material": ROD, "role": "rod",
             "rotation": [math.pi / 2, 0.0, 0.0], "position": [sx * ROD_HALF, y + sy * ROD_HALF, (z0 + z1) / 2]}
            for sx in (-1, 1) for sy in (-1, 1)]


def nema17(front_x: float, y: float = 0.0, z: float = 0.0) -> list[dict[str, Any]]:
    """A NEMA 17 stepper whose shaft points to -x, its front flange at ``front_x``: a black body between two
    grey end caps, the blue round maker's label on its +z side, the shaft and a red coupler in front."""

    s, length = NEMA, NEMA_LEN
    cap = length * 0.18
    x_mid = front_x + length / 2
    return [
        {"shape": "box", "width": cap, "height": s, "depth": s, "position": [front_x + cap / 2, y, z], "material": MOTOR_CAP, "role": "motor cap"},
        {"shape": "box", "width": length - 2 * cap, "height": s * 0.97, "depth": s * 0.97, "position": [x_mid, y, z], "material": MOTOR_BLACK, "role": "motor"},
        {"shape": "box", "width": cap, "height": s, "depth": s, "position": [front_x + length - cap / 2, y, z], "material": MOTOR_CAP, "role": "motor cap"},
        {"shape": "cylinder", "radius": s * 0.3, "height": 0.2, "rotation": [math.pi / 2, 0, 0],
         "position": [x_mid, y, z + s * 0.49], "material": LABEL_BLUE, "role": "label"},
        {**_cylinder_along_x(0.95, 3.0, _KNOB_STEEL, position=[front_x - 1.5, y, z]), "role": "shaft"},
        {**_cylinder_along_x(1.9, 4.0, RED, position=[front_x - 4.5, y, z]), "role": "coupler"},
    ]


# ---------------------------------------------------------------------------------------------- bench parts

class CageCube(NonPolarizingBeamSplitter):
    """A cage cube holding a beamsplitter cube: ``cage=30`` (CCM1 kind, a 1 inch cube) or ``cage=60`` (LC6W kind,
    a 2 inch cube). Ports sit on the cube's outer faces (``in`` left, ``trans`` right, ``refl`` up the plan,
    ``tap`` down the plan), so cage rods start there. ``coating_color`` tints the coating (a dichroic)."""

    component_type = "CageCube"

    def __init__(self, center=(0, 0), angle=0, split_ratio=(0.5, 0.5), coating_color="#ffffff", cage=30, **kwargs):
        kwargs.setdefault("label", "Cage cube BS")
        self.coating_color = coating_color
        self.cage = cage_size(cage).mm
        size = cage_size(cage)
        super().__init__(center=center, angle=angle, aperture=2 * size.glass_half / 0.72, split_ratio=split_ratio, **kwargs)

    @property
    def size(self) -> CageSize:
        return cage_size(self.cage)

    def ports(self) -> dict[str, Port]:
        h, w = self.size.cube_half, 2 * self.size.glass_half
        return {
            "in": Port("in", Vec3(-h, 0, 0), orientation_deg=180.0, width=w, kind="free_space"),
            "trans": Port("trans", Vec3(h, 0, 0), orientation_deg=0.0, width=w, kind="free_space"),
            "refl": Port("refl", Vec3(0, h, 0), orientation_deg=90.0, width=w, kind="free_space"),
            "tap": Port("tap", Vec3(0, -h, 0), orientation_deg=270.0, width=w, kind="free_space"),
        }

    def geometry_2d(self) -> dict[str, Any]:
        z = self.size
        h, g = z.cube_half, z.glass_half
        return {"type": "group", "children": [
            {"type": "rect", "cx": 0, "cy": 0, "w": 2 * h, "h": 2 * h, "fill": "#2b3036", "stroke": "#111827", "stroke_width": 0.15},
            {"type": "rect", "cx": 0, "cy": 0, "w": 2 * g, "h": 2 * g, "fill": "#bcd7ea", "opacity": 0.9},
            {"type": "line", "x1": -g, "y1": -g, "x2": g, "y2": g, "stroke": self.coating_color, "stroke_width": 0.3},
            *[{"type": "circle", "cx": sx * z.rod_half, "cy": sy * z.rod_half, "r": z.rod_r, "fill": "#c9ced4"}
              for sx in (-1, 1) for sy in (-1, 1)],
        ]}

    def geometry_3d(self) -> dict[str, Any]:
        # the 2D in -> refl fold (refl up the plan, -z in 3D) needs the coating plane along (1, 0, -1) and y
        z = self.size
        return {"shape": "group", "children": cage_cube(coating_rotation=(0.0, -math.pi / 4, 0.0),
                                                         coating_color=self.coating_color, size=z),
                "post_at": [0.0, -z.cube_half - z.wall, 0.0]}

    def animation_behaviour(self):
        from optodraw.animation_engine.behaviours import find_behaviour
        return find_behaviour(NonPolarizingBeamSplitter(split_ratio=self.split_ratio))

    def beam_path_between(self, start: str, end: str) -> list[tuple[float, float, float]] | None:
        """Light between two faces turns at the middle of the block (a fold, or a straight pass)."""

        return [(0.0, 0.0, 0.0)] if start != end else None

    def to_dict(self) -> dict[str, Any]:
        return {**super().to_dict(), "coating_color": self.coating_color, "cage": self.cage}


class CageRods(Component):
    """Four 6 mm rods of a cage between two cage parts, 30 or 60 mm apart (``cage``). The light runs along the
    axis between them."""

    component_type = "CageRods"
    beam_passes = True

    def __init__(self, center=(0, 0), angle=0, length=30.0, end_plates=True, cage=30, **kwargs):
        self.length = float(length)
        self.cage = cage_size(cage).mm
        # between two cubes the cubes hold the rods (end_plates=False); on their own, two cage plates join them
        self.end_plates = bool(end_plates)
        kwargs.setdefault("base_mount", "none")
        _set_common_free_space_fields(self, center, angle, kwargs, color="#c9ced4", opacity=1.0,
                                      material_preset="steel", label=kwargs.get("label", ""))

    def ports(self) -> dict[str, Port]:
        h = self.length / 2.0
        return {"in": Port("in", Vec3(-h, 0, 0), orientation_deg=180.0, width=10.0, kind="free_space"),
                "out": Port("out", Vec3(h, 0, 0), orientation_deg=0.0, width=10.0, kind="free_space")}

    def geometry_2d(self) -> dict[str, Any]:
        z = cage_size(self.cage)
        return {"type": "group", "children": [
            {"type": "rect", "cx": 0, "cy": s * z.rod_half, "w": self.length, "h": 2 * z.rod_r, "fill": "#c9ced4",
             "stroke": "#7b838c", "stroke_width": 0.08} for s in (-1, 1)]}

    def geometry_3d(self) -> dict[str, Any]:
        z = cage_size(self.cage)
        h = self.length / 2.0
        if not self.end_plates:
            return {"shape": "group", "children": _rods_x(-h - 1.0, h + 1.0, size=z)}   # into each cube's rod holes
        t = 1.6 * z.wall / WALL                          # a cage plate at each end, a bore in it
        return {"shape": "group", "children": _rods_x(-h + t, h - t, size=z)
                + [_plate("x", s * (h - t / 2), z.cube_half * 0.95, t, z.bore) for s in (-1, 1)]}

    def to_dict(self) -> dict[str, Any]:
        return {**super().to_dict(), "length": self.length, "end_plates": self.end_plates, "cage": self.cage}


class CageRightAngleMirror(Component):
    """A right-angle kinematic cage mount, ``cage=30`` (KCB1, a 1 inch mirror) or ``cage=60`` (KCB2, a 2 inch
    mirror): a triangular block one cube on a side with a 45 degree mirror on its hypotenuse. Light enters ``in``
    (the left face) and leaves ``out`` (the face up the plan); ``angle`` turns the whole mount. Cage rods start
    on either face."""

    component_type = "CageRightAngleMirror"

    def __init__(self, center=(0, 0), angle=0, cage=30, **kwargs):
        self.cage = cage_size(cage).mm
        _set_common_free_space_fields(self, center, angle, kwargs, color="#23282e", opacity=1.0,
                                      material_preset="steel", label=kwargs.get("label", "Cage mirror"))

    def to_dict(self) -> dict[str, Any]:
        return {**super().to_dict(), "cage": self.cage}

    @property
    def size(self) -> CageSize:
        return cage_size(self.cage)

    def ports(self) -> dict[str, Port]:
        h = self.size.cube_half
        return {"in": Port("in", Vec3(-h, 0, 0), orientation_deg=180.0, width=10.0, kind="free_space"),
                "out": Port("out", Vec3(0, h, 0), orientation_deg=90.0, width=10.0, kind="free_space")}

    def physics_metadata(self) -> dict[str, Any]:
        return {"domain": "free_space", "component": "right_angle_mirror", "reflective": True}

    def geometry_2d(self) -> dict[str, Any]:
        h = self.size.cube_half
        return {"type": "group", "children": [
            {"type": "polygon", "points": [(-h, -h), (-h, h), (h, h)], "fill": "#2b3036", "stroke": "#111827", "stroke_width": 0.15},
            {"type": "line", "x1": -h * 0.8, "y1": -h * 0.8, "x2": h * 0.8, "y2": h * 0.8, "stroke": "#e8eef3", "stroke_width": 0.6},
        ]}

    def geometry_3d(self) -> dict[str, Any]:
        z = self.size
        h = z.cube_half
        # in the plan the light runs +x in and leaves up the plan (3D -z); the triangle lies flat, so its lower
        # side plate is the face the post holds, under the triangle's centroid
        tap = -h + 2 * h * 17.8 / 48.3                  # the drawing's mounting tap, under the lower end
        return {"shape": "group", "children": kcb1((1, 0, 0), (0, 0, -1), size=z), "post_at": [tap, -h, tap]}

    def animation_behaviour(self):
        from optodraw.animation_engine.behaviours import find_behaviour
        return find_behaviour(Mirror())

    def beam_path_between(self, start: str, end: str) -> list[tuple[float, float, float]] | None:
        """Light between two faces turns at the middle of the block (a fold, or a straight pass)."""

        return [(0.0, 0.0, 0.0)] if start != end else None


WAVE_PLATES = {"half": math.pi, "quarter": math.pi / 2.0}


class CageWavePlate(WavePlate):
    """A half- or quarter-wave plate (``plate``) in a cage rotation mount (CRM1 kind for ``cage=30``, LCRM2 for
    60): a square cage plate with a rod hole at each corner, a rotating ring with its scale and a lock screw, and
    the retarder in the ring. ``fast_axis_angle`` (degrees) turns the ring and the mark that shows the fast axis.
    The light passes along the axis, ``in`` to ``out``, as through a ``WavePlate``."""

    component_type = "CageWavePlate"

    def __init__(self, center=(0, 0), angle=0, plate="half", fast_axis_angle=0.0, cage=30, **kwargs):
        if plate not in WAVE_PLATES:
            raise ValueError(f"plate is 'half' or 'quarter', not {plate!r}")
        self.plate = plate
        self.cage = cage_size(cage).mm
        size = cage_size(cage)
        kwargs.setdefault("label", "λ/2" if plate == "half" else "λ/4")
        kwargs.setdefault("color", "#b9a7f5" if plate == "half" else "#8fd3c4")
        super().__init__(center=center, angle=angle, aperture=2 * size.glass_half, thickness=0.7,
                         retardance=WAVE_PLATES[plate], fast_axis_angle=fast_axis_angle, **kwargs)

    def geometry_3d(self) -> dict[str, Any]:
        z = cage_size(self.cage)
        h, t = z.cube_half * 0.95, z.wall * 3.2               # the plate: a cube's face across, half an inch thick
        ring_r, glass_r = z.glass_half * 1.35, z.glass_half * 0.98
        dark = {"color": "#1b1e22", "metalness": 0.4, "roughness": 0.5}
        fast = math.radians(float(self.fast_axis_angle))
        children: list[dict[str, Any]] = [
            {**_plate("x", 0.0, h, t, ring_r * 1.02), "role": "cage plate"},
            # the rotating ring through the plate, its front flange with the scale, and the retarder in it
            _ring_along_x(glass_r * 1.015, ring_r, t * 1.25, _MOUNT_BLACK, x=-t * 0.1),
            _ring_along_x(glass_r * 1.015, ring_r * 1.12, t * 0.25, _MOUNT_ALU, x=-t * 0.72),
            {**_cylinder_along_x(glass_r, 0.6, {"color": self.color, "opacity": 0.55, "transparent": True,
                                                "preset": "glass"}, position=[-t * 0.2, 0.0, 0.0]), "role": "retarder"},
            # the fast axis: a white line across the retarder at its angle
            {"shape": "box", "width": 0.12, "height": glass_r * 1.8, "depth": 0.25, "role": "fast axis",
             "rotation": [fast, 0.0, 0.0], "position": [-t * 0.2 - 0.36, 0.0, 0.0],
             "material": {"color": "#ffffff", "opacity": 0.9, "transparent": True}},
            # the lock screw on top and the rod holes (dark through the plate's corners)
            {"shape": "cylinder", "radius": z.rod_r * 0.9, "height": h * 0.35, "position": [0.0, h + h * 0.15, 0.0],
             "material": _KNOB_STEEL, "role": "lock screw"},
            *[{**_cylinder_along_x(z.rod_r * 1.05, t * 1.02, dark, position=[0.0, sy * z.rod_half, sz * z.rod_half]),
               "role": "rod hole"} for sy in (-1, 1) for sz in (-1, 1)],
        ]
        for k in range(24):                                   # the scale: a tick every 15 degrees on the flange
            a = 2.0 * math.pi * k / 24.0
            r = ring_r * 1.05
            children.append({"shape": "box", "width": 0.1, "height": ring_r * (0.12 if k % 6 else 0.2), "depth": 0.08,
                             "rotation": [a, 0.0, 0.0], "position": [-t * 0.86, math.sin(a) * r, math.cos(a) * r],
                             "material": {"color": "#ffffff", "metalness": 0.1, "roughness": 0.6}, "role": "tick"})
        return {"shape": "group", "children": children, "post_at": [0.0, -h, 0.0]}

    def animation_behaviour(self):
        from optodraw.animation_engine.behaviours import find_behaviour
        return find_behaviour(WavePlate(retardance=self.retardance, fast_axis_angle=self.fast_axis_angle))

    def to_dict(self) -> dict[str, Any]:
        return {**super().to_dict(), "plate": self.plate, "cage": self.cage}


class MotorizedMirror(Mirror):
    """A 1 inch mirror in a kinematic mount, turned by a NEMA 17 stepper motor through a red shaft coupler: the
    motor stands behind the mount on a black bracket that shares the mirror's post. Turning the mirror picks
    which fiber the beam goes to. Light ports are the mirror's; ``motor`` is the drive cable."""

    component_type = "MotorizedMirror"
    # where the motor's drive port sits behind the mirror face, in mirror heights: `od motormirror` draws the
    # mirror 0.68 tall and the back of the motor at 1.67
    MOTOR_REACH = 1.67 / 0.68

    def __init__(self, center=(0, 0), angle=0, **kwargs):
        kwargs.setdefault("label", "Motorized mirror")
        kwargs.pop("piezo", None)
        super().__init__(center=center, angle=angle, **kwargs)

    def ports(self) -> dict[str, Port]:
        ports = super().ports()
        io = ports["io"].center.x
        ports["motor"] = Port("motor", Vec3(io + self.MOTOR_REACH * self.aperture, 0, 0), orientation_deg=0.0,
                              width=1.0, kind="electrical")
        return ports

    def geometry_2d(self) -> dict[str, Any]:
        # the mirror, then the shaft and the motor behind it, on the plan of `od motormirror` (cm over 0.68
        # mirror heights): the 2D art is sized from these bounds
        geo = super().geometry_2d()
        io, u = super().ports()["io"].center.x, self.aperture / 0.68
        children = list(geo.get("children", [geo]))
        children += [
            {"type": "rect", "cx": io + 0.365 * u, "cy": 0.0, "w": 0.47 * u, "h": 0.1 * u, "fill": "#c6cbd1"},
            {"type": "rect", "cx": io + 1.135 * u, "cy": 0.0, "w": 1.07 * u, "h": 1.14 * u, "fill": "#1b1e22",
             "stroke": "#9aa1a9", "stroke_width": 0.2},
        ]
        return {"type": "group", "children": children}

    def geometry_3d(self) -> dict[str, Any]:
        geo = super().geometry_3d()
        side = self.aperture * 1.4
        rear =max(s["position"][0] for s in geo["children"] if s.get("role") == "knob") + side * 0.05
        front = rear + 6.0                                     # the coupler and the shaft fill the gap
        bottom = -side / 2.0
        geo["children"] = list(geo["children"]) + [
            # the bracket: a plate under the mount and the motor, and the motor's foot plate
            {"shape": "box", "width": front + NEMA_LEN - 1.0, "height": 1.2, "depth": NEMA,
             "position": [(front + NEMA_LEN - 1.0) / 2.0, bottom - 0.6, 0.0], "material": _MOUNT_BLACK, "role": "bracket"},
            {"shape": "box", "width": 1.2, "height": NEMA * 0.5 + 0.6, "depth": NEMA,
             "position": [front - 0.6, bottom + NEMA * 0.25 - 0.3, 0.0], "material": _MOUNT_BLACK, "role": "bracket"},
            *nema17(front, y=bottom + NEMA / 2.0 + 0.05),
        ]
        geo["post_at"] = [2.88 * self.aperture / 10.0, bottom - 1.2, 0.0]   # the bracket's underside
        return geo

    def animation_behaviour(self):
        from optodraw.animation_engine.behaviours import find_behaviour
        return find_behaviour(Mirror(aperture=self.aperture))


class CageTower(Component):
    """The vertical 30 mm cage tower over the cryostat, built round one axis.

    From the bottom: the objective, looking down through the breadboard into the cryostat; cube BS1 at the bench
    beam height, which turns the horizontal beam (``in``) down to the sample; cube BS2 at ``upper`` with the LED
    arm on the plan's -y side (a cage with a KCB1C cube holding a CXY1A translator, a lens tube and a mounted
    LED: ``led``); above, two KCB1 right-angle mounts that step the image sideways by one cube; the tube lens
    tube and the camera (``camera``). Four rods run from a base plate on the breadboard up through both cubes.
    ``sample`` is the focus in the cryostat. Heights are units above the bench beam plane."""

    component_type = "CageTower"
    beam_passes = True
    lifts_beam = False

    def __init__(self, center=(0, 0), angle=0, board=25.0, upper=34.0, led_len=70.0, sample_depth=55.0,
                 camera_tube=34.0, **kwargs):
        self.board, self.upper, self.led_len = float(board), float(upper), float(led_len)
        self.sample_depth, self.camera_tube = float(sample_depth), float(camera_tube)
        kwargs.setdefault("base_mount", "none")          # it stands on its own rods and base plate
        _set_common_free_space_fields(self, center, angle, kwargs, color="#2b3036", opacity=1.0,
                                      material_preset="steel", label=kwargs.get("label", "Cage tower"))

    @property
    def jog_z(self) -> float:                            # the KCB1 pair
        return self.upper + 2 * CUBE_HALF

    @property
    def camera_x(self) -> float:                         # the camera's axis, one cube to -x
        return -2 * CUBE_HALF

    @property
    def camera_z(self) -> float:
        return self.jog_z + CUBE_HALF + self.camera_tube

    def ports(self) -> dict[str, Port]:
        return {
            "in": Port("in", Vec3(-CUBE_HALF, 0, 0), orientation_deg=180.0, width=10.0, kind="free_space"),
            "led": Port("led", Vec3(0, -self.led_len, self.upper), orientation_deg=270.0, width=10.0, kind="free_space"),
            "camera": Port("camera", Vec3(self.camera_x, 0, self.camera_z), orientation_deg=90.0, width=10.0, kind="free_space"),
            "sample": Port("sample", Vec3(0, 0, -self.sample_depth), orientation_deg=270.0, width=2.0, kind="free_space"),
        }

    def beam_path_between(self, start: str, end: str) -> list[tuple[float, float, float]] | None:
        paths = {
            ("in", "sample"): [(0.0, 0.0, 0.0)],
            ("led", "sample"): [(0.0, 0.0, self.upper)],
            ("sample", "camera"): [(0.0, 0.0, self.jog_z), (self.camera_x, 0.0, self.jog_z)],
        }
        if (start, end) in paths:
            return paths[(start, end)]
        if (end, start) in paths:
            return paths[(end, start)][::-1]
        return None

    def geometry_2d(self) -> dict[str, Any]:
        h = CUBE_HALF
        return {"type": "group", "children": [
            {"type": "rect", "cx": 0, "cy": 0, "w": 2 * h, "h": 2 * h, "fill": "#2b3036", "stroke": "#111827", "stroke_width": 0.15},
            {"type": "rect", "cx": self.camera_x, "cy": 0, "w": 2 * h, "h": 2 * h, "fill": "#2b3036", "stroke": "#111827", "stroke_width": 0.15},
            {"type": "circle", "cx": 0, "cy": 0, "r": 4.0, "fill": "#bcd7ea"},
            {"type": "rect", "cx": 0, "cy": -(h + self.led_len) / 2, "w": 2 * ROD_HALF, "h": self.led_len - h, "fill": "#3a3f45"},
            *[{"type": "circle", "cx": sx * ROD_HALF, "cy": sy * ROD_HALF, "r": ROD_R, "fill": "#c9ced4"}
              for sx in (-1, 1) for sy in (-1, 1)],
        ]}

    def geometry_3d(self) -> dict[str, Any]:
        h, t = CUBE_HALF, WALL
        up, jog = self.upper, self.jog_z
        base_y = -self.board                             # the breadboard top
        out: list[dict[str, Any]] = []
        # BS1 at the beam: in from -x, reflected down. Coating plane along (1, -1, 0) and z.
        out += cage_cube((0, 0, 0), coating_rotation=(0.0, 0.0, -math.pi / 4), tab=False)
        # BS2 above: the LED arrives travelling -z (from the plan's -y side, 3D +z) and reflects down.
        # Coating plane along x and (0, 1, 1).
        out += cage_cube((0, up, 0), coating_rotation=(-math.pi / 4, 0.0, 0.0), tab=False)
        # the KCB1 pair: up -> -x, then -x -> up, one cube over
        out += kcb1((0, 1, 0), (-1, 0, 0), centre=(0.0, jog, 0.0))
        out += kcb1((-1, 0, 0), (0, 1, 0), centre=(self.camera_x, jog, 0.0))
        # rods: base plate to the KCB1 pair
        out += _rods_y(base_y + t, jog - h)
        out.append(_plate("y", base_y + t / 2, h, t, 7.0))
        # the objective: an SM1-to-RMS adapter under BS1, then the barrel down through the board and its nose
        top = -h
        out += [
            {"shape": "cylinder", "radius": 4.4, "height": 3.0, "position": [0, top - 1.5, 0], "material": _MOUNT_BLACK, "role": "adapter"},
            {"shape": "cylinder", "radius": 3.6, "height": 18.0, "position": [0, top - 12.0, 0], "material": _MOUNT_ALU, "role": "objective"},
            {"shape": "cylinder", "radius": 3.65, "height": 1.2, "position": [0, top - 9.0, 0], "material": RED, "role": "objective band"},
            {"shape": "lathe_profile", "points": [[0.0, 0.0], [3.6, 0.0], [3.6, -3.0], [1.6, -7.0], [0.0, -7.0]],
             "position": [0, top - 21.0, 0], "material": _MOUNT_ALU, "role": "objective nose"},
        ]
        # the LED arm toward +z: rods, a KCB1C cube with a CXY1A translator (a white diffuser in it), a lens
        # tube, and the mounted LED with its ribbed heat sink
        reach = self.led_len
        k_z = h + 6.0 + h                                # the KCB1C cube, a little out from BS2
        out += _rods_z(h, reach - 9.0, y=up)
        out += cage_cube((0, up, k_z), glass=False, tab=False)
        out += [
            {"shape": "box", "width": 2 * h + 3.0, "height": 2 * h + 3.0, "depth": 1.6, "position": [0, up, k_z + h + 0.8],
             "material": _MOUNT_BLACK, "role": "CXY1A plate"},
            {"shape": "cylinder", "radius": 4.2, "height": 1.8, "rotation": [math.pi / 2, 0, 0],
             "position": [0, up, k_z + h + 0.8], "material": WHITE, "role": "diffuser"},
            *[{"shape": "cylinder", "radius": 1.1, "height": 3.0, "position": [x, up + y, k_z + h + 0.8],
               "rotation": r, "material": _KNOB_STEEL, "role": "knob"}
              for x, y, r in ((h + 2.4, 0.0, [0, 0, math.pi / 2]), (0.0, h + 2.4, [0, 0, 0]))],
        ]
        tube_z0, tube_z1 = k_z + h + 1.6, reach - 12.0
        out += [
            {"shape": "cylinder", "radius": 4.6, "height": tube_z1 - tube_z0, "rotation": [math.pi / 2, 0, 0],
             "position": [0, up, (tube_z0 + tube_z1) / 2], "material": _MOUNT_BLACK, "role": "lens tube"},
            _plate("z", reach - 10.0, h * 0.95, 1.6, BORE, centre=(0.0, up, 0.0)),   # CP08 plate holding the LED
            {"shape": "cylinder", "radius": 4.8, "height": 4.5, "rotation": [math.pi / 2, 0, 0],
             "position": [0, up, reach - 7.7], "material": _MOUNT_BLACK, "role": "LED body"},
            *[{"shape": "cylinder", "radius": 5.6, "height": 0.7, "rotation": [math.pi / 2, 0, 0],
               "position": [0, up, reach - 4.8 + 1.1 * k], "material": MOTOR_BLACK, "role": "heat sink"} for k in range(5)],
            {"shape": "cylinder", "radius": 4.0, "height": 7.0, "rotation": [math.pi / 2, 0, 0],
             "position": [0, up, reach - 2.5], "material": MOTOR_BLACK, "role": "heat sink core"},
        ]
        # the camera's tube up from the second KCB1 and the camera: a black body on a red C-mount ring
        cx = self.camera_x
        tube = self.camera_tube
        out += _rods_y(jog + h, jog + h + tube * 0.6, x=cx)
        out += [
            {"shape": "cylinder", "radius": 4.6, "height": tube, "position": [cx, jog + h + tube / 2, 0],
             "material": _MOUNT_BLACK, "role": "tube lens tube"},
            {"shape": "cylinder", "radius": 5.0, "height": 1.6, "position": [cx, jog + h + tube + 0.8, 0], "material": RED, "role": "C-mount ring"},
            {"shape": "box", "width": 11.5, "height": 11.5, "depth": 11.5, "position": [cx, jog + h + tube + 1.6 + 5.75, 0],
             "material": MOTOR_BLACK, "role": "camera"},
        ]
        return {"shape": "group", "children": out}

    def to_dict(self) -> dict[str, Any]:
        return {**super().to_dict(), "board": self.board, "upper": self.upper, "led_len": self.led_len,
                "sample_depth": self.sample_depth, "camera_tube": self.camera_tube}


class CryostatCabinet(Component):
    """The closed-cycle cryostat the breadboard sits on: a grey cabinet (drawn see-through so the sample shows),
    a round adapter plate on six standoffs under the board, the sample insert under the board's hole with the
    sample on its cold finger, two black helium hoses, and the stepper controller (an Arduino on a solderless
    breadboard) on the cabinet top. Placed at the objective's axis; ``cabinet_offset`` moves the cabinet in the
    plan. Heights are units above the bench beam plane (negative: below)."""

    component_type = "CryostatCabinet"

    def __init__(self, center=(0, 0), angle=0, board_bottom=-30.0, sample_depth=55.0, size=(170.0, 200.0, 110.0),
                 cabinet_offset=(0.0, -30.0), **kwargs):
        self.board_bottom, self.sample_depth = float(board_bottom), float(sample_depth)
        self.size, self.cabinet_offset = tuple(size), tuple(cabinet_offset)
        kwargs.setdefault("base_mount", "none")          # it stands on the floor
        _set_common_free_space_fields(self, center, angle, kwargs, color="#c9cdd2", opacity=1.0,
                                      material_preset="steel", label=kwargs.get("label", "Cryostat"))

    @property
    def top(self) -> float:                              # the cabinet top, under the standoffs
        return self.board_bottom - 14.0

    def ports(self) -> dict[str, Port]:
        return {"sample": Port("sample", Vec3(0, 0, -self.sample_depth), orientation_deg=90.0, width=2.0, kind="free_space")}

    def geometry_2d(self) -> dict[str, Any]:
        sx, sy, _ = self.size
        ox, oy = self.cabinet_offset
        return {"type": "rect", "cx": ox, "cy": oy, "w": sx, "h": sy, "fill": "none", "stroke": "#7b838c",
                "stroke_width": 0.3, "opacity": 0.5}

    def geometry_3d(self) -> dict[str, Any]:
        sx, sy, sz = self.size
        ox, oz = self.cabinet_offset[0], -self.cabinet_offset[1]
        top, bb = self.top, self.board_bottom
        shell = {**GREY_CABINET, "opacity": 0.5, "transparent": True}
        steel = {"color": "#aeb7c2", "metalness": 0.5, "roughness": 0.4, "preset": "steel"}
        copper = {"color": "#b87333", "metalness": 0.6, "roughness": 0.35}
        s = -self.sample_depth
        out: list[dict[str, Any]] = [
            {"shape": "box", "width": sx, "height": sz, "depth": sy, "position": [ox, top - sz / 2, oz], "material": shell, "role": "cabinet"},
            {"shape": "box", "width": sx, "height": 1.5, "depth": sy, "position": [ox, top - 0.75, oz], "material": GREY_CABINET, "role": "cabinet top"},
            # the round adapter plate under the board and its standoffs
            {"shape": "cylinder", "radius": 62.0, "height": 2.5, "position": [ox, bb - 1.25, oz], "material": MOTOR_BLACK, "role": "adapter plate"},
            *[{"shape": "cylinder", "radius": 2.2, "height": bb - 2.5 - top, "material": MOTOR_BLACK, "role": "standoff",
               "position": [ox + 52 * math.cos(a), (bb - 2.5 + top) / 2, oz + 52 * math.sin(a)]}
              for a in (math.radians(30 + 60 * k) for k in range(6))],
            # the sample insert under the hole: a flange, a see-through tube, the cold finger and the sample
            {**_ring_along_x(4.0, 12.0, 2.0, steel), "rotation": [0, 0, 0], "position": [0, top + 1.0, 0], "role": "insert flange"},
            {"shape": "cylinder", "radius": 9.0, "height": top - (s - 6.0), "position": [0, (top + s - 6.0) / 2, 0],
             "material": {**steel, "opacity": 0.45, "transparent": True}, "role": "insert"},
            {"shape": "cylinder", "radius": 3.0, "height": (s - 1.0) - (top - sz + 2.0), "position": [0, (s - 1.0 + top - sz + 2.0) / 2, 0],
             "material": copper, "role": "cold finger"},
            {"shape": "box", "width": 6.0, "height": 1.0, "depth": 6.0, "position": [0, s - 0.5, 0], "material": copper, "role": "stage"},
            {"shape": "box", "width": 3.0, "height": 0.4, "depth": 3.0, "position": [0, s + 0.2, 0],
             "material": {"color": "#4b5563", "metalness": 0.2, "roughness": 0.5}, "role": "sample"},
            # the stepper controller on the cabinet top, at the front
            {"shape": "box", "width": 22.0, "height": 1.2, "depth": 14.0, "position": [ox - 20, top + 0.6, oz + sy / 2 - 12], "material": WHITE, "role": "breadboard"},
            {"shape": "box", "width": 7.0, "height": 1.0, "depth": 3.0, "position": [ox - 20, top + 1.7, oz + sy / 2 - 12], "material": LABEL_BLUE, "role": "Arduino"},
        ]
        # two helium hoses: loops out of the cabinet's +x side
        x0 = ox + sx / 2
        for dz, y in ((-25.0, top - 25.0), (-5.0, top - 45.0)):
            pts = [[x0 - 2, y, oz + dz], [x0 + 18, y + 10, oz + dz], [x0 + 30, y + 30, oz + dz + 5],
                   [x0 + 22, y + 50, oz + dz + 15], [x0 + 4, y + 52, oz + dz + 25], [x0 - 2, y + 38, oz + dz + 30]]
            out.append({"shape": "tube_path", "points": pts, "radius": 3.0, "material": HOSE, "role": "helium hose"})
        return {"shape": "group", "children": out}

    def to_dict(self) -> dict[str, Any]:
        return {**super().to_dict(), "board_bottom": self.board_bottom, "sample_depth": self.sample_depth,
                "size": list(self.size), "cabinet_offset": list(self.cabinet_offset)}
