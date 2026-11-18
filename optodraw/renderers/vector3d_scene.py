"""The solids of a scene, read from the 3D viewer's own scene data and placed as the viewer page places them.

The page JS of ThreeJsRenderer builds the mounts, the beams, the routes and the chip base itself, from the scene
data. This module copies those functions line for line: the odBuildAll branches, odAddPost, odRiser, odAddStage,
odAddXYZStage, odAddRotationStage, liftToTable, odFillet, odCableRise, odFootprintEntry, odDieFootprint,
odChipStack, odBuildOnChipBase, and odFrameToContent with odPoseForBox and odFitDistance. The viewer comparison
(tests/test_vector3d_viewer.py) guards both copies. Each copy keeps the JS order of operations, so the numbers agree
to the last bits."""

from __future__ import annotations

import math
from dataclasses import replace

import numpy as np

from optodraw.renderers.threejs_renderer import PageConstants, ThreeJsRenderer
from optodraw.renderers.vector3d_hidden import Camera, _direction
from optodraw.renderers.vector3d_solids import (
    KINDS, Band, Box, SolidSet, Vector3DError, add_solid, box, box_union, cylinder, look_of, nodes, solids_from_tree,
    three_box, tree_box, trs, tube_path)

# The page's mount hardware, against the 1 in optic it draws at 10 units (OPTIC_UNIT and the radii below it)
OPTIC_UNIT = 10.0
POST_R = OPTIC_UNIT * 0.25
HOLDER_R = OPTIC_UNIT * 0.374
PED_BASE_R = OPTIC_UNIT * 0.75
PED_BASE_T = OPTIC_UNIT * 0.374
HOLDER_H = OPTIC_UNIT * 0.6
ALU = {"color": "#c4c9cf", "metalness": 0.88, "roughness": 0.22}       # _POST_ALU
ANOD = {"color": "#22272d", "metalness": 0.45, "roughness": 0.55}      # _POST_ANOD
BODY = {"color": "#2b3037", "metalness": 0.5, "roughness": 0.5}        # _STAGE_BODY
PLATE = {"color": "#3b424b", "metalness": 0.55, "roughness": 0.42}     # _STAGE_TOP
DIE = {"color": "#9aa4b0", "roughness": 0.5, "metalness": 0.45}        # __odDieMat
CARRIER = {"color": "#2f353d", "roughness": 0.62, "metalness": 0.35}
# A beam's glow band over its width: 5.5 units on the default 633 nm beam (display width 0.868), as the spike drew it
GLOW = 5.5 / 0.868
TURN_Z = (0.0, 0.0, math.pi / 2)
TURN_X = (math.pi / 2, 0.0, 0.0)
REFUSED = {"external_model": "an external model file (external_model)"}


def _board_top(k: PageConstants) -> float:
    return float(f"{k.board_top:.2f}")          # the page writes BOARD_TOP with two decimals


def _length(v) -> float:
    return math.sqrt(float(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]))   # Vector3.length


def _cyl(top: float, bottom: float, height: float, sides: int, material: dict, at, rotation=None) -> dict:
    return {"shape": "cylinder", "radiusTop": top, "radiusBottom": bottom, "height": height, "radialSegments": sides,
            "position": list(at), "rotation": rotation, "material": material}


def _box(width: float, height: float, depth: float, material: dict, at, rotation=None) -> dict:
    return {"shape": "box", "width": width, "height": height, "depth": depth, "position": list(at),
            "rotation": rotation, "material": material}


def _mount(x: float, z: float, k: PageConstants, children: list[dict]) -> dict:
    return {"shape": "group", "position": [x, _board_top(k), z], "children": children}


def post(x: float, z: float, top: float, k: PageConstants) -> dict:
    """odAddPost: a pedestal base, an anodised holder, a collar and the brushed post up to ``top``."""

    rise = max(top - _board_top(k), 2.4)
    base_h = min(PED_BASE_T, rise * 0.22)
    holder_h = min(HOLDER_H, (rise - base_h) * 0.6)
    post_h = rise - base_h - holder_h * 0.7
    return _mount(x, z, k, [
        _cyl(PED_BASE_R * 0.92, PED_BASE_R, base_h, 28, ANOD, (0, base_h / 2, 0)),
        _cyl(HOLDER_R, HOLDER_R, holder_h, 22, ANOD, (0, base_h + holder_h / 2, 0)),
        _cyl(HOLDER_R * 0.82, HOLDER_R * 0.82, 0.5, 22, ALU, (0, base_h + holder_h, 0)),
        _cyl(POST_R, POST_R, post_h, 20, ALU, (0, base_h + holder_h * 0.7 + post_h / 2, 0))])


def riser(from_y: float, to_y: float) -> list[dict]:
    """odRiser: the holder, collar and post from ``from_y`` up to ``to_y``; none for a rise of 0.6 or less."""

    rise = to_y - from_y
    if rise <= 0.6:
        return []
    holder_h = min(rise * 0.4, 5.5)
    post_h = max(rise - holder_h * 0.7, 0.4)
    return [_cyl(HOLDER_R, HOLDER_R, holder_h, 22, ANOD, (0, from_y + holder_h / 2, 0)),
            _cyl(POST_R * 1.3, POST_R * 1.3, 0.5, 22, ALU, (0, from_y + holder_h, 0)),
            _cyl(POST_R, POST_R, post_h, 20, ALU, (0, from_y + holder_h * 0.7 + post_h / 2, 0))]


def stage(x: float, z: float, top: float, k: PageConstants) -> dict:
    """odAddStage: a translation stage with its micrometer on +x, then the riser up to ``top``."""

    rise = max(top - _board_top(k), 4.0)
    base_h, top_h, sw, sd = OPTIC_UNIT * 0.22, OPTIC_UNIT * 0.14, OPTIC_UNIT * 2.0, OPTIC_UNIT * 1.5
    return _mount(x, z, k, [
        _box(sw, base_h, sd, BODY, (0, base_h / 2, 0)),
        _box(sw * 0.8, top_h, sd * 0.92, PLATE, (0, base_h + top_h / 2, 0)),
        _cyl(0.5, 0.5, sw * 0.42, 16, ALU, (sw * 0.6, base_h + top_h * 0.3, 0), TURN_Z),
        _cyl(0.66, 0.66, sw * 0.16, 16, ANOD, (sw * 0.88, base_h + top_h * 0.3, 0), TURN_Z),
        *riser(base_h + top_h, rise)])


def xyz_stage(x: float, z: float, top: float, k: PageConstants) -> dict:
    """odAddXYZStage: an x stage, a crossed y stage and a z lift, a micrometer on each, then the riser."""

    rise = max(top - _board_top(k), 4.0)
    base_h, sw, sd, z_h = OPTIC_UNIT * 0.2, OPTIC_UNIT * 2.0, OPTIC_UNIT * 1.5, OPTIC_UNIT * 0.6
    return _mount(x, z, k, [
        _box(sw, base_h, sd, BODY, (0, base_h / 2, 0)),
        _box(sd, base_h, sw, PLATE, (0, base_h * 1.5, 0)),
        _box(sd * 0.7, z_h, sd * 0.7, BODY, (0, base_h * 2 + z_h / 2, 0)),
        _cyl(0.5, 0.5, sw * 0.4, 16, ALU, (sw * 0.6, base_h * 0.5, 0), TURN_Z),
        _cyl(0.5, 0.5, sw * 0.4, 16, ALU, (0, base_h * 1.5, sw * 0.6), TURN_X),
        _cyl(0.45, 0.45, z_h * 0.8, 16, ANOD, (sd * 0.48, base_h * 2 + z_h / 2, 0)),
        *riser(base_h * 2 + z_h, rise)])


def rotation_stage(x: float, z: float, top: float, k: PageConstants) -> dict:
    """odAddRotationStage: a round base, a dial with 24 ticks round its rim, a thumbscrew, then the riser."""

    rise = max(top - _board_top(k), 4.0)
    base_h, r = OPTIC_UNIT * 0.24, OPTIC_UNIT * 1.0
    ticks = [_box(0.1, 0.55, 0.5, BODY, (math.cos(a) * r * 0.88, base_h + 0.25, math.sin(a) * r * 0.88), (0, -a, 0))
             for a in (i * math.pi / 12 for i in range(24))]
    return _mount(x, z, k, [
        _cyl(r, r * 1.06, base_h, 36, BODY, (0, base_h / 2, 0)),
        _cyl(r * 0.9, r * 0.9, 0.5, 36, ALU, (0, base_h + 0.25, 0)),
        *ticks,
        _cyl(0.5, 0.5, 1.4, 14, ALU, (r + 0.5, base_h * 0.55, 0), TURN_Z),
        *riser(base_h + 0.5, rise)])


STAGES = {"stage": stage, "xyz_stage": xyz_stage, "rotation_stage": rotation_stage}


def _mount_for(item: dict, k: PageConstants, root: dict) -> dict | None:
    """The mount the mesh branch puts under a part on the beam plane, in world units."""

    if item.get("baseMount") == "none":
        return None
    x, _, z = item["position"]
    axis = k.beam_plane + (item.get("lift") or 0)      # a part after a periscope rides at its exit height
    rotation = item.get("rotation")
    local = tree_box(root, np.eye(4), item.get("sid") or "")
    world = tree_box(root, trs((x, axis, z), rotation), item.get("sid") or "")
    bottom = world[0][1] if world is not None else axis
    held = root.get("post_at")                          # a JS array is true even when empty
    yaw = rotation[1] if rotation else 0
    lx = held[0] if held is not None else ((local[0][0] + local[1][0]) / 2 if local is not None else 0)
    lz = held[2] if held is not None else ((local[0][2] + local[1][2]) / 2 if local is not None else 0)
    px = x + lx * math.cos(yaw) + lz * math.sin(yaw)
    pz = z - lx * math.sin(yaw) + lz * math.cos(yaw)
    given = item.get("mountHeight")
    post_top = given if given is not None else (axis + held[1] if held is not None else bottom) + 0.15
    if item.get("baseMount") in STAGES:
        return STAGES[item["baseMount"]](px, pz, post_top, k)
    if item.get("baseMount") == "post_beam":
        return post(px, pz, given if given is not None else axis, k)
    return post(px, pz, post_top, k)


def place_mesh(item: dict, k: PageConstants, catalog: dict, out: SolidSet) -> list[Box | None]:
    """The odBuildAll mesh branch. A part on the beam plane rides at the beam axis on its mount, which the page adds
    first. Any other part takes zScale, liftToTable, the position and CHIP_LIFT. localScale goes on the anchor.
    Returns the boxes of the groups it adds: the mount, then the part."""

    root = dict(item["geometry"])
    sid = item.get("sid") or ""
    x, y, z = item["position"]
    mount = None
    if item.get("beamPlane"):
        mount = _mount_for(item, k, root)
        y = k.beam_plane + (item.get("lift") or 0)
    else:
        if item.get("zScale"):
            sx, sy, sz = root.get("scale") or (1.0, 1.0, 1.0)
            root["scale"] = [sx, sy * k.chip_z, sz]
        if k.lift_meshes:
            # the page measures the mesh before its anchor has a world matrix: the box is in the mesh's parent frame
            lifted = tree_box(root, np.eye(4), sid)
            floor = 0.0 if item.get("board") else _board_top(k)
            if lifted is not None and lifted[0][1] < floor:
                rx, ry, rz = root.get("position") or (0.0, 0.0, 0.0)
                root["position"] = [rx, ry + (floor - lifted[0][1]), rz]
        if k.chip_lift > 0 and item.get("chip"):
            y += k.chip_lift
    boxes = []
    if mount is not None:
        boxes.append(solids_from_tree(mount, np.eye(4), part=f"mount:{sid}", chip=False, catalog=catalog, out=out))
    anchor = trs((x, y, z), item.get("rotation"), item.get("localScale"))
    boxes.append(solids_from_tree(root, anchor, part=sid, chip=bool(item.get("chip")), catalog=catalog, out=out))
    return boxes


def _points(item: dict, lift: float = 0.0) -> list[np.ndarray]:
    return [np.array([float(p[0]), float(p[1]) + lift, float(p[2])]) for p in item["points"]]


def beam_solids(item: dict, k: PageConstants, catalog: dict, out: SolidSet) -> Box | None:
    """The beam branch: an 8-sided tube per segment on the beam plane, emissive, at opacity 0.7, and one glow Band
    per segment. The page's centre Line is no solid."""

    points = _points(item, k.beam_plane)
    color = item.get("color") or "#ff0000"
    width = item.get("width") or 0.8
    look = replace(look_of({"color": color, "opacity": 0.7}, catalog), unlit=True)
    boxes = []
    for start, end in zip(points, points[1:]):
        mid = (start + end) * 0.5
        # Object3D.lookAt points the tube's +z at the end (the Matrix4.lookAt rule of the camera), then rotateX(pi/2)
        aim = np.eye(4)
        aim[:3, :3] = Camera(eye=end, target=mid, perspective=False).basis.T
        aim[:3, 3] = mid
        matrix = aim @ trs(rotation=TURN_X)
        faces = cylinder({"radius": width * 0.3, "height": _length(end - start), "radialSegments": 8})
        add_solid(out, faces, matrix, part=item.get("sid") or "", kind="beam", look=look)
        boxes.append(three_box(faces, matrix))
        out.bands.append(Band(item.get("sid") or "", start, end, (width * GLOW, width * GLOW), look.color))
    return box_union(boxes)


def focus_band(item: dict, k: PageConstants, part, out: SolidSet) -> None:
    """A focusing beam: the static viewer draws no mesh for it. The renderer draws its cone as a clear Band from
    width1 to width2 on the beam plane (Part B, open question 1)."""

    start, end = _points(item, k.beam_plane)
    wide = float(item.get("width") or 0.0)
    widths = (float(getattr(part, "width1", wide)), float(getattr(part, "width2", wide)))
    out.bands.append(Band(item.get("sid") or "", start, end, widths, look_of({"color": item.get("color") or "#ff0000"},
                                                                             {}).color))


def fillet(points: list[np.ndarray], radius: float) -> list[np.ndarray]:
    """odFillet: each inner corner becomes a quadratic arc of 8 steps, its radius held under 0.49 of either side."""

    if len(points) < 3 or not radius > 0:
        return points
    out = [points[0]]
    for a, p, b in zip(points, points[1:], points[2:]):
        da, db = p - a, b - p
        la, lb = _length(da), _length(db)
        rr = min(radius, la * 0.49, lb * 0.49)
        if rr < 0.05 or la < 1e-6 or lb < 1e-6:
            out.append(p.copy())
            continue
        da, db = da * (1 / la), db * (1 / lb)
        if abs(float(da @ db)) > 0.999:            # collinear
            out.append(p.copy())
            continue
        pa, pb = p + da * -rr, p + db * rr
        out.append(pa)
        for step in range(1, 8):
            t = step / 8
            out.append(pa * ((1 - t) * (1 - t)) + p * (2 * t * (1 - t)) + pb * (t * t))
        out.append(pb)
    out.append(points[-1])
    return out


def _angle(a: np.ndarray, b: np.ndarray) -> float:
    """Vector3.angleTo."""

    denominator = math.sqrt(float(a @ a) * float(b @ b))
    if denominator == 0:
        return math.pi / 2
    return math.acos(min(max(float(a @ b) / denominator, -1.0), 1.0))


def strip_solids(item: dict, k: PageConstants, catalog: dict, out: SolidSet) -> Box | None:
    """A fabricated route: flat boxes along the (filleted, for light) path, one per segment, its width tapered by
    arc length, and a square filler at each corner over 0.26 rad. CHIP_LIFT lifts a chip route's group."""

    elec = item.get("kind") == "electrical"
    raw = _points(item)
    points = raw if elec else fillet(raw, item.get("bendRadius") or 6)
    width = max(item.get("width") or 0.5, 0.2)
    width2 = max(item["width2"], 0.2) if item.get("width2") else None
    if "stripThick" in item:
        scale = k.chip_z if item.get("stripScale") else 1
    else:
        scale = k.chip_z if item.get("chip") else 1
    thick = (item["stripThick"] if "stripThick" in item else (0.35 if elec else 0.22)) * scale
    level = (item.get("stripZ") or 0) * scale
    material = item.get("stripMaterial") or {"color": item.get("color") or "#2d6cdf",
                                             "roughness": 0.32 if elec else 0.5, "metalness": 0.74 if elec else 0.12}
    look = look_of(material, catalog)
    group = trs((0.0, k.chip_lift if k.chip_lift > 0 and item.get("chip") else 0.0, 0.0))
    lengths = [_length(b - a) for a, b in zip(points, points[1:])]
    total = sum(lengths)
    pieces, run = [], 0.0
    for a, b, length in zip(points, points[1:], lengths):
        d = b - a
        span = _length(d)
        if span < 1e-4:
            run += length
            continue
        mid = (a + b) * 0.5
        mid[1] += level + thick / 2
        t = (run + length / 2) / total if total > 0 else 0
        w = width if width2 is None else width + (width2 - width) * t
        pieces.append(((span, thick, w), mid, math.atan2(-d[2], d[0])))
        run += length
    for a, p, b in zip(points, points[1:], points[2:]):
        u, v = p - a, b - p
        if _length(u) < 1e-4 or _length(v) < 1e-4 or _angle(u, v) < 0.26:
            continue
        at = p.copy()
        at[1] += level + thick / 2
        pieces.append(((width, thick, width), at, 0.0))
    boxes = []
    for (sx, sy, sz), at, yaw in pieces:
        faces = box({"width": sx, "height": sy, "depth": sz})
        matrix = group @ trs(list(at), (0.0, yaw, 0.0))
        add_solid(out, faces, matrix, part=item.get("sid") or "", kind="strip", look=look, chip=bool(item.get("chip")))
        boxes.append(three_box(faces, matrix))
    return box_union(boxes)


def die_footprint(content: Box | None) -> tuple[float, float, float, float] | None:
    """odDieFootprint: the die's centre x and z and half sizes x and z round a content box."""

    if content is None:
        return None
    lo, hi = content
    c, s = (lo + hi) * 0.5, hi - lo
    return (float(c[0]), float(c[2]), max(s[0] * 0.5 + max(s[0] * 0.05, 5), 8),
            max(s[2] * 0.5 + max(s[2] * 0.05, 5), 8))


def footprint_entry(a, b, foot) -> tuple[float, float] | None:
    """odFootprintEntry: where the segment a to b first crosses into the die footprint (x, z), if it does."""

    cx, cz, hx, hz = foot
    dx, dz = b[0] - a[0], b[2] - a[2]
    t = 0
    if abs(dx) > 1e-6:
        t = max(t, min(((cx - hx) - a[0]) / dx, ((cx + hx) - a[0]) / dx))
    if abs(dz) > 1e-6:
        t = max(t, min(((cz - hz) - a[2]) / dz, ((cz + hz) - a[2]) / dz))
    return (a[0] + dx * t, a[2] + dz * t) if 0 < t < 1 else None


def cable_rise(pts: list[np.ndarray], at_start: bool, beam_y: float, bench_y: float) -> list[np.ndarray]:
    """odCableRise: the cable leaves a connector at the beam height level, then eases down to the table along its
    own path, the way a patch cord hangs."""

    p = list(pts) if at_start else list(pts)[::-1]
    if len(p) < 2:
        return pts
    cum = [0.0]
    for a, b in zip(p, p[1:]):
        cum.append(cum[-1] + math.hypot(b[0] - a[0], b[2] - a[2]))
    total, drop = cum[-1], max(beam_y - bench_y, 0)
    lead = min(total * 0.15, max(drop * 0.25, 2.0))
    reach = min(total * 0.6, lead + drop * 1.4)

    def height(d: float) -> float:
        if d <= lead:
            return beam_y
        if d >= reach:
            return bench_y
        return bench_y + drop * 0.5 * (1 + math.cos(math.pi * (d - lead) / (reach - lead)))

    def plan_at(d: float) -> tuple[float, float]:
        i = 0
        while i < len(cum) - 2 and cum[i + 1] < d:
            i += 1
        t = (d - cum[i]) / (cum[i + 1] - cum[i]) if cum[i + 1] > cum[i] else 0
        return p[i][0] + (p[i + 1][0] - p[i][0]) * t, p[i][2] + (p[i + 1][2] - p[i][2]) * t

    path = []
    for step in range(13):
        d = reach * step / 12
        x, z = plan_at(d)
        path.append(np.array([x, height(d), z]))
    path += [q for q, length in zip(p, cum) if length > reach + 1e-6]
    return path if at_start else path[::-1]


def cable_solids(item: dict, k: PageConstants, chip_box: Box | None, catalog: dict, out: SolidSet) -> Box | None:
    """A bench cable: the path filleted by 4, at CABLE_Y over the board top; a chip end climbs at the die edge and
    drops onto its pad; an end on a beam-plane part rises to its connector. One centripetal Catmull-Rom tube,
    10 sides, FrontSide. ``chip_box`` is the die box the page holds when it builds this cable."""

    pts = fillet(_points(item), 4)
    radius = min(max((item.get("width") or 1) * 0.22, 0.4), 0.5 if item.get("kind") == "fiber" else 0.75)
    bench = _board_top(k) + k.lead_height
    run = [np.array([p[0], p[1] + bench, p[2]]) for p in pts]
    drop = item.get("cableDrop")
    if drop:
        end = 0 if drop == "start" else len(run) - 1
        pad = pts[end].copy()
        pad[1] += 0.4 * k.chip_z + k.chip_lift
        bench_y = pts[end][1] + _board_top(k) + k.lead_height
        foot = die_footprint(chip_box)

        def on_die(p) -> bool:
            return foot is not None and abs(p[0] - foot[0]) <= foot[2] and abs(p[2] - foot[1]) <= foot[3]

        path = run[::-1] if drop == "start" else list(run)
        path[-1] = pad                              # walk from the bench end to the pad, so the climb reads forwards
        climbed, walk = False, []
        for p in path:
            if not climbed and on_die(p):
                climbed = True
                edge = footprint_entry(walk[-1], p, foot) if walk else (p[0], p[2])
                if edge is not None:
                    walk += [np.array([edge[0], bench_y, edge[1]]), np.array([edge[0], pad[1], edge[1]])]
            walk.append(np.array([p[0], max(p[1], pad[1]), p[2]]) if climbed else p)
        run = walk[::-1] if drop == "start" else walk
    for index, rises in enumerate(item.get("cableRise") or []):
        if rises:
            run = cable_rise(run, index == 0, k.beam_plane, bench)
    spine = [p for i, p in enumerate(run) if i == 0 or _length(p - run[i - 1]) > 1e-3]
    if len(spine) < 2:
        return None
    faces = tube_path({"points": spine, "segments": min(400, max(32, len(spine) * 12)), "radius": radius,
                       "radialSegments": 10}, double_sided=False)
    look = look_of({"color": item.get("color") or "#2a2d33", "roughness": 0.62, "metalness": 0.08}, catalog)
    add_solid(out, faces, np.eye(4), part=item.get("sid") or "", kind="cable", look=look, closed=False)
    return three_box(faces, np.eye(4))


def chip_stack(hx: float, hz: float) -> tuple[float, float, float]:
    """odChipStack: the die thickness, the carrier thickness and the carrier rim, from the footprint."""

    side = 2 * min(hx, hz)
    die_t = min(max(side * 0.08, 1.0), 5.0)
    return die_t, die_t * 0.64, min(max(side * 0.06, 0.8), 6.0)


def chip_base(content: Box | None, k: PageConstants, catalog: dict, out: SolidSet) -> list[Box | None]:
    """odBuildOnChipBase: a die with one cut corner on a dark carrier, round the content box. No die under a user
    ChipSubstrate. A chip on a bench stands its stack on the table, under the devices CHIP_LIFT lifted."""

    if not (k.show_grid and (k.on_chip or k.mixed) and k.show_chip_base) or content is None:
        return []
    lo, hi = content
    c = (lo + hi) * 0.5
    _, _, hx, hz = die_footprint(content)
    die_t, car_t, rim = chip_stack(hx, hz)
    ch = min(hx, hz) * 0.24
    if k.mixed:
        die_t, car_t = 5.0, 3.2
    top = k.chip_lift if k.mixed else min(0, lo[1])
    boxes = []
    if not k.has_user_die:
        outline = [(-hx, hz - ch), (-hx, -hz), (hx, -hz), (hx, hz), (-hx + ch, hz)]
        # the page extrudes the shape by dieT and turns it by rotateX(+pi/2): shape (x, y) at depth d goes to
        # (x, -d, y); extruded_polygon maps (x, y) at height h to (x, h, -y), so the shape goes in mirrored in y
        die = {"shape": "extruded_polygon", "points": [(px, -py) for px, py in outline], "height": die_t,
               "position": [c[0], top - die_t, c[2]], "material": DIE}
        boxes.append(solids_from_tree(die, np.eye(4), part="base:die", chip=False, catalog=catalog, out=out))
    carrier_y = top - car_t / 2 if k.has_user_die else top - die_t - car_t / 2
    carrier = _box(hx * 2 + rim * 2, car_t, hz * 2 + rim * 2, CARRIER, (c[0], carrier_y, c[2]))
    boxes.append(solids_from_tree(carrier, np.eye(4), part="base:carrier", chip=False, catalog=catalog, out=out))
    return boxes


def _refusal(item: dict) -> str | None:
    """What the vector view cannot draw in an entry, or None."""

    kind = item.get("type")
    if kind in REFUSED:
        return REFUSED[kind]
    if kind not in ("mesh", "beam", "route", "fbeam"):
        return f"an entry of type {kind!r}"
    if kind == "mesh" and item.get("geometry"):
        shapes = {geo.get("shape") for geo, _ in nodes(item["geometry"], np.eye(4))} - {"group", *KINDS}
        if shapes:
            return f"the shape {sorted(map(str, shapes))[0]!r}"
    return None


def scene_solids(scene, *, renderer_options: dict | None = None) -> SolidSet:
    """Every solid the viewer draws for ``scene``, in the viewer's build order: each entry of the scene data as
    odBuildAll adds it (a mount before its part), then the chip base.

    The view matches a transparent capture of the viewer: no auto table, no floor grid. ``renderer_options`` go to
    the viewer's ThreeJsRenderer, such as ``show_chip_base=False``. An external model or a user part from an SVG
    raises Vector3DError, which names the part."""

    from optodraw.core.view_layout import display_scene

    renderer = ThreeJsRenderer(display_scene(scene, "3d"), capture={"background": "none"}, world="light",
                               **(renderer_options or {}))
    items = renderer._collect_scene_data()
    k = renderer.page_constants(items)
    catalog = renderer._resolved_material_catalog()
    parts = {renderer._sids.get(id(node)): node for node in renderer.scene.walk()}
    for item in items:
        what = _refusal(item)
        if what:
            node = parts.get(item.get("sid"))
            name = getattr(node, "component_type", "") or "part"
            name += f" {item['label']!r}" if item.get("label") else f" {item.get('sid')}"
            raise Vector3DError(f"{name}: the vector 3D view does not draw {what}. Use scene.render_3d_image for "
                                "this scene.")
    # chipRoughBounds: the die a cable climbs before any chip mesh exists
    rough = box_union((p, p) for item in items if item.get("chip")
                      for p in [np.asarray(item["position"], float)] + [np.asarray(q, float) for q in
                                                                       item.get("points") or []])
    out = SolidSet(constants=k)
    chip_box = None
    for item in items:
        kind, groups = item["type"], []
        if kind == "mesh" and item.get("geometry"):
            groups = place_mesh(item, k, catalog, out)
        elif kind == "beam" and len(item.get("points") or []) >= 2:
            groups = [beam_solids(item, k, catalog, out)]
        elif kind == "route" and len(item.get("points") or []) >= 2:
            if item.get("cable"):
                groups = [cable_solids(item, k, chip_box if chip_box is not None else rough, catalog, out)]
            else:
                groups = [strip_solids(item, k, catalog, out)]
        elif kind == "fbeam" and len(item.get("points") or []) == 2:
            focus_band(item, k, parts.get(item.get("sid")), out)
        if item.get("chip") and groups and not item.get("cable"):
            chip_box = box_union([chip_box, groups[-1]])       # __odChipBox grows by each chip part and chip route
        out.boxes += [b for b in groups if b is not None]
    content = chip_box if k.mixed else box_union(out.boxes)
    out.boxes += [b for b in chip_base(content, k, catalog, out) if b is not None]
    if any(item.get("zScale") for item in items):
        out.notes = (f"chip heights {k.chip_z:g} times true",)
    return out


def home_pose(solids: SolidSet, direction, *, aspect: float = 1.6, fill: float = 0.8) -> tuple[np.ndarray,
                                                                                                np.ndarray]:
    """The viewer's framed camera (odFrameToContent, odPoseForBox, odFitDistance): the eye and the target that fit
    the corners of each content group and of the chip base into ``fill`` of a frame of ``aspect``, seen from
    ``direction``. The page frames with fill 0.8 on load and 0.9 in a capture."""

    if not solids.boxes:
        raise Vector3DError("the scene has no solids to frame")
    lo, hi = box_union(solids.boxes)
    corners = np.array([(x, y, z) for b0, b1 in solids.boxes for x in (b0[0], b1[0]) for y in (b0[1], b1[1])
                        for z in (b0[2], b1[2])])
    target = (lo + hi) * 0.5
    vfov = math.radians(Camera.fov_deg)
    hfov = 2 * math.atan(math.tan(vfov / 2) * aspect)
    dist = max(_length(hi - lo) * 0.5, 1e-3) / math.sin(min(vfov, hfov) / 2)
    right, up, back = Camera(eye=target + _direction(direction) * dist, target=target, perspective=True).basis
    forward = -back
    tv = math.tan(vfov / 2) * fill
    th = tv * aspect
    x, y, z = corners @ right, corners @ up, corners @ forward
    reach_r, reach_l = float(np.max(x - th * z)), float(np.max(-x - th * z))
    reach_u, reach_d = float(np.max(y - tv * z)), float(np.max(-y - tv * z))
    away = min(-(reach_r + reach_l) / (2 * th), -(reach_u + reach_d) / (2 * tv))

    def centre_on(axis: np.ndarray) -> float:
        """Centre one axis on screen: the near and far extreme corners sit at different depths."""

        values, depths = corners @ axis, np.maximum(corners @ forward - away, 1e-6)
        low, high = float(values.min()), float(values.max())
        for _ in range(60):
            mid = (low + high) / 2
            q = (values - mid) / depths
            if q.max() + q.min() > 0:
                low = mid
            else:
                high = mid
        return (low + high) / 2

    eye = right * centre_on(right) + up * centre_on(up) + forward * away
    dist = max(float((target - eye) @ forward), 1e-3)
    return eye, eye + forward * dist
