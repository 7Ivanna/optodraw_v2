"""3D mockup of the cryostat microscope bench on the attocube breadboard (500 x 475 mm, drawing 1011879-2), laid out
from the annotated top view: positions are the photo mapped onto the board through its four corners (``PHOTO``),
good to about a hole. The cage systems over the cryostat come from the front photos (cage_systems.py): the KCB2C
(the large right-angle mount) stands over the board's Ø31 hole, 75 mm from its far edge, on 60 mm rods, with the
excitation line's right cube under it and the objective under that, down into the cryostat.

Each stepper mirror sends its fiber's light one of two ways (the colours of the annotated photo):

    003 (left):     the fiber in a KM100 -> CXY1A -> CP33 -> SM1PM10 with a GT10 Glan-Taylor, on the
                    collection cube's axis line at its height (from the photo of the arm), then
                    MM1 in the beam -> KM100 in front of the cube -> wave plate 3 -> its front face      orange
                    MM1 turned away -> rods with a wave plate -> the cube's left side                    light blue
                    and along the collection line to the KCB2C and down to the sample
    Olaf E (right): filter -> MM2 in the beam -> KM100 F -> KM100 G -> into the left cube's side       red
                    filter -> MM2 turned away -> KM100 I -> KCB1 -> Glan-Taylor in a CRM1T -> its back  dark blue

The excitation line at beam height, toward the far edge: three CCM1-4ER cubes, two wave plates between the first two;
the right cube sends the light down through the objective to the sample. From the sample: up through the right cube,
on up into the KCB2C and along the collection line (LCP33, two wave plates, DFM1BS, a wave plate), and across to the
middle cube and up the imaging rods to the imaging cube, the KCB1C pair and the camera. The LED arm drops into the
imaging cube and its light goes the other way down to the sample. Every post has a CF125 clamping fork, turned the
way the fork beside it in the photo points.

Heights are scene units (2.54 mm) above the bench beam plane. Run:
    python3 mockups/cryo_setup/bench.py            (bench.optodraw.json, bench_3d.html, bench_3d_*.png)
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

from optodraw import (
    Beam,
    Breadboard,
    CageRightAngleMirror,
    CageRods,
    CageWavePlate,
    CryostatCabinet,
    FiberCollimator,
    Filter,
    Mirror,
    MotorizedMirror,
    Objective,
    Photodiode,
    Scene,
)
from optodraw.components.optics.cage import CUBE_HALF as H
from optodraw.components.vendor import CatalogCageMount, CatalogGlanPolarizer, CatalogLensTube, CatalogTableClamp
from optodraw.components.vendor.data import CLAMPS
from optodraw.layout import aim

sys.path.insert(0, str(Path(__file__).parent))
from cage_systems import Y_KCB2, Z_EXC, add_light, add_systems  # noqa: E402

HERE = Path(__file__).parent
BEAM = 30.0                  # the renderer's beam plane above the table
BOARD_PART = "attocube 1011879-2"
BOARD_T = 10.0 / 2.54        # breadboard thickness (10 mm): its top is BEAM - BOARD_T below the beam plane
HALF = (250.0 / 2.54, 237.5 / 2.54)      # the board's half length and half width


def mm(x: float, y: float) -> tuple[float, float]:
    """A board position in mm (from the board's middle, the Ø31 hole on +y) in scene units."""

    return x / 2.54, y / 2.54


AX, AY = mm(0.0, 237.5 - 75.0)   # the tower's axis, over the Ø31 hole
MM_U = 1 / 2.54              # scene units per mm (the cage systems are laid out in mm)
CUBE_CCM1 = 38.1 / 2 * MM_U  # the CCM1-4ER's half width
FIBER_FRONT = FiberCollimator().ports()["out"].center.x     # a fiber collimator's centre to its front
# the annotated photo's colours for the four routes
ORANGE, LIGHT_BLUE, RED, DARK_BLUE = "#f39c12", "#8ecdf5", "#d62828", "#1f4fd6"

# the forks in the photo, mapped onto the board: (x, y) of the U round the post base in mm, and the way the fork
# points from there, in degrees
PHOTO_FORKS = [(-89, 201, -174), (114, 223, -108), (175, 119, -136), (90, 55, -79), (228, 39, -116), (221, -63, 179),
               (180, -193, 179), (5, -199, 14), (40, -59, 52), (-178, 42, 60), (-101, -17, -109), (-249, -23, -43),
               (-231, -76, -35), (-208, -151, 27), (-220, -194, 8), (-24, -180, 152)]


def hrods(scene, a, b, z):
    """Horizontal cage rods between plan points a and b (along x or y) at height z."""
    (x0, y0), (x1, y1) = a, b
    along_y = abs(x1 - x0) < 1e-9
    length = abs(y1 - y0) if along_y else abs(x1 - x0)
    return scene.add(CageRods(center=((x0 + x1) / 2, (y0 + y1) / 2), z=z, length=length, angle=90 if along_y else 0,
                              end_plates=False, base_mount="none"))


def post_spots(scene: Scene) -> dict[str, tuple[float, float]]:
    """Where each part's post meets the board, in plan, keyed by the part's label: the post stands under the middle of
    the mount (behind a mirror's glass, under a KCB1's tap), so it is read from the 3D renderer's own placement."""

    from optodraw.renderers import vector3d_scene

    spots: dict[str, tuple[float, float]] = {}
    place = vector3d_scene._mount_for

    def record(item, k, root):
        mount = place(item, k, root)
        if mount is not None:
            x, _, z = mount["position"]
            spots[item.get("label") or ""] = (float(x), -float(z))      # the 3D z is minus the plan's y
        return mount

    vector3d_scene._mount_for = record
    try:
        scene.render_3d_svg(str(HERE / ".post_spots.svg"))
    finally:
        vector3d_scene._mount_for = place
        (HERE / ".post_spots.svg").unlink(missing_ok=True)
    return spots


def clamp_posts(scene: Scene, part: str = "CF125") -> None:
    """A clamping fork on each post base, its U round the base, pointing as the photo's fork there does; with no fork
    near in the photo, behind a mirror or beside a part the light goes through."""

    spec = CLAMPS[part]
    reach = (spec["l"] / 2 - spec["post_from_tip"]) / 2.54         # fork middle to the pedestal in its bore
    far = (spec["l"] - spec["post_from_tip"]) / 2.54               # the pedestal to the fork's far end

    def on_board(px, py, heading, length):
        x, y = px + length * math.cos(heading), py + length * math.sin(heading)
        return abs(x) < HALF[0] - 2 and abs(y) < HALF[1] - 2

    parts = {n.label: n for n in scene.walk() if n.label and getattr(n, "base_mount", "") == "post"
             and hasattr(n, "transform")}
    for label, (px, py) in post_spots(scene).items():
        node = parts.get(label)
        if node is None:
            continue
        cx, cy = node.transform.position.x, node.transform.position.y
        turn = math.radians(node.transform.rotation_deg.z)
        near = min(PHOTO_FORKS, key=lambda f: math.hypot(f[0] / 2.54 - px, f[1] / 2.54 - py))
        if math.hypot(near[0] / 2.54 - px, near[1] / 2.54 - py) < 60 / 2.54:
            options = [math.radians(near[2]), math.radians(near[2] + 30), math.radians(near[2] - 30)]
        elif "Mirror" in type(node).__name__ and math.hypot(px - cx, py - cy) > 0.5:
            back = math.atan2(py - cy, px - cx)                    # behind the glass, the way the post sits
            options = [back, back + math.pi / 2, back - math.pi / 2]
        else:                                                      # light goes through: beside its beam
            options = [turn + math.pi / 2, turn - math.pi / 2, turn + math.pi]
        heading = next((h for h in options if on_board(px, py, h, far)), options[0])
        scene.add(CatalogTableClamp(part=part, center=(px + reach * math.cos(heading), py + reach * math.sin(heading)),
                                    angle=math.degrees(heading), label=f"{node.label} fork"))


def build() -> Scene:
    scene = Scene(title="Cryostat microscope bench", width=300, height=300, platform="free_space")
    scene.add(Breadboard(center=(0, 0), angle=180, part=BOARD_PART, label="Breadboard"))
    cryo = scene.add(CryostatCabinet(center=(AX, AY), board_bottom=-BEAM, sample_depth=55.0, size=(175.0, 165.0, 110.0),
                                     cabinet_offset=(-AX, -AY), label="Cryostat"))
    board_top = -(BEAM - BOARD_T)

    # ---- the cage systems (cage_systems.py, from the front photos): the KCB2C stands over the window, the
    # excitation line runs at beam height from Olaf E's side to the cube under it, collection at the KCB2C's level,
    # imaging on top. The module's frame turns onto the board as it is: its +y is the board's +y.
    origin = (AX, AY - Y_KCB2 * MM_U, -Z_EXC * MM_U)
    cages = add_systems(scene, origin=origin, z_board=Z_EXC + board_top / MM_U)
    ex = cages["ex"]
    # the objective under the right excitation cube, down through the window into the cryostat
    objective = scene.add(Objective(center=(AX, AY), z=-H - 7.5, rotation_y=90, label="Objective", base_mount="none"))

    # ---- 003's arm, from the photo of it: on the collection cube's axis line at its height, coming in from the left
    # edge (-x). The fiber in a KM100 -> CXY1A on its face -> short rods -> CP33 -> SM1PM10 holding a GT10
    # Glan-Taylor -> MM1 -> rods with a wave plate into the cube's left side. MM1 in the beam sends 003 instead to
    # a KM100 in front of the cube (on its axis, past wave plate 3), which turns it into the cube's front face.
    col = cages["col"]
    join = col["dfm"].world_port("refl").center                 # the collection cube's left side port
    z_col, y_arm = float(join.z), float(join.y)
    x_face = float(join.x)                                      # its left face
    x_rods = x_face - 50.0 * MM_U                               # the rods' far end
    x_wp = x_face - 29.0 * MM_U
    x_mm1 = x_face - 80.0 * MM_U
    x_tube1 = x_mm1 - 30.0 * MM_U                               # the SM1PM10's front
    tube_len = 35.0 * MM_U                                      # SM1PM10, estimated from the photo
    x_tube0 = x_tube1 - tube_len
    x_cp = x_tube0 - 8.9 / 2 * MM_U                             # the CP33 it screws into
    x_cxy = x_cp - (8.9 / 2 + 10.0 + 15.2 / 2) * MM_U           # 10 mm of rod between CP33 and CXY1A
    x_launch = x_cxy - 15.2 / 2 * MM_U - FIBER_FRONT            # the fiber's front at the CXY1A
    arm = {"z": z_col}
    hang = {"z": z_col, "base_mount": "none"}
    f003 = scene.add(FiberCollimator(center=(x_launch, y_arm), angle=0, label="003 (in a KM100)", **arm))
    scene.add(CatalogCageMount(part="CXY1A", center=(x_cxy, y_arm), label="CXY1A (003)", **hang))
    scene.add(CageRods(center=((x_cxy + x_cp) / 2, y_arm), length=x_cp - x_cxy, end_plates=False,
                       label="Rods CXY1A-CP33", **hang))
    scene.add(CatalogCageMount(part="CP33", center=(x_cp, y_arm), label="CP33 (003)", **hang))
    sm1pm10 = scene.add(CatalogLensTube(part="SM1L10", length_mm=35.0, center=((x_tube0 + x_tube1) / 2, y_arm),
                                        label="SM1PM10 (003)", **hang))
    glan = scene.add(CatalogGlanPolarizer(part="GT10", center=((x_tube0 + x_tube1) / 2, y_arm),
                                          label="Glan-Taylor GT10 (in the SM1PM10)", **hang))
    mm1 = scene.add(MotorizedMirror(center=(x_mm1, y_arm), label="MM1", **arm))
    wp003 = scene.add(CageWavePlate(plate="half", center=(x_wp, y_arm), label="Wave plate (003)", **hang))
    hrods(scene, (x_rods, y_arm), (x_face, y_arm), z_col)
    km_front = scene.add(Mirror(center=(AX, mm(0, -230)[1]), label="KM100 (in front of the DFM1BS)", **arm))
    aim(mm1, f003, km_front)
    aim(km_front, mm1, col["dfm"].world_port("trans").center.as_2d())

    # ---- Olaf E down from the far right corner, a filter, and its two routes
    olaf_e = scene.add(FiberCollimator(center=mm(188, 175), angle=-90, label="Olaf E"))
    filt = scene.add(Filter(center=mm(188, 140), angle=-90, label="Filter"))
    mm2 = scene.add(MotorizedMirror(center=mm(188, 75), label="MM2"))
    km_f = scene.add(Mirror(center=mm(116, 70), label="KM100 F"))
    km_g = scene.add(Mirror(center=mm(226, -53), label="KM100 G"))
    km_i = scene.add(Mirror(center=mm(188, -194), label="KM100 I"))
    # Olaf E's way into the excitation line at beam height: a KCB1 turns the dark-blue route into the left cube's
    # back, the red route comes into its side; a CRM1T between them
    kcb_in = scene.add(CageRightAngleMirror(center=(AX, mm(0, -194)[1]), rotation_y=180, label="Olaf E in (KCB1)"))
    y_left = ex["left"].transform.position.y
    hrods(scene, (AX, mm(0, -194)[1] + H), (AX, y_left - CUBE_CCM1), 0.0)
    scene.add(CatalogCageMount(part="CRM1T", center=(AX, mm(0, -120)[1]), angle=90, label="CRM1T (Olaf E)",
                               base_mount="none"))
    olaf_glan = scene.add(CatalogGlanPolarizer(part="GT10", center=(AX, mm(0, -120)[1]), angle=90,
                                               label="Glan-Taylor GT10 (Olaf E)", base_mount="none"))
    aim(mm2, filt, km_f)
    aim(km_f, mm2, km_g)
    aim(km_g, km_f, ex["left"].world_port("tap").center.as_2d())
    aim(km_i, filt, kcb_in.world_port("in").center.as_2d())

    # ---- the other parts on the board, off the traced routes
    scene.add(FiberCollimator(center=mm(-98, 215), angle=-90, label="Olaf 1"))
    scene.add(Photodiode(center=mm(114, 215), angle=-90, label="PD"))

    # ---- light: 003 up to its lift; Olaf E's two routes into the excitation line and down to the sample; the sample's
    # light up to the collection line and the camera; the LED down to the sample
    # 003: through the SM1PM10's Glan-Taylor; MM1 in the beam -> the KM100 in front -> wave plate 3 -> the cube's
    # front face; MM1 turned away -> straight on through the wave plate into the cube's left side. Either way the
    # collection line takes it on to the KCB2C and down to the sample.
    launch = [(f003, "out"), (sm1pm10, "in"), (glan, "in"), (glan, "out"), (sm1pm10, "out")]
    to_sample = [(col["dfm"], "in"), (col["wp_b"], "in"), (col["wp_b"], "out"), (col["wp_a"], "in"),
                 (col["wp_a"], "out"), (col["lcp"], "in"), (col["lcp"], "out"), (col["kcb2"], "in"), (col["kcb2"], "out"),
                 (ex["right"], "tap"), (ex["right"], "refl"), (objective, "in"), (objective, "out"), (cryo, "sample")]
    scene.add(Beam.through(*launch, mm1, km_front, (col["wp_c"], "in"), (col["wp_c"], "out"), (col["dfm"], "trans"),
                           *to_sample, color=ORANGE, width=1.4, label="003, MM1 in the beam"))
    scene.add(Beam.through(*launch, (wp003, "in"), (wp003, "out"), (col["dfm"], "refl"), *to_sample,
                           color=LIGHT_BLUE, width=1.4, label="003, MM1 turned away"))
    olaf = [(olaf_e, "out"), (filt, "in"), (filt, "out")]
    add_light(scene, cages, [(cryo, "sample"), (objective, "out"), (objective, "in"), (ex["right"], "refl")],
              excitation_in=[
                  ([*olaf, mm2, km_f, km_g, (ex["left"], "tap")],
                   {"color": RED, "width": 1.4, "label": "Olaf E, MM2 in the beam"}),
                  ([*olaf, km_i, (kcb_in, "in"), (kcb_in, "out"), (olaf_glan, "in"), (olaf_glan, "out"),
                    (ex["left"], "in")],
                   {"color": DARK_BLUE, "width": 1.4, "label": "Olaf E, MM2 turned away"}),
              ])
    clamp_posts(scene)
    return scene


if __name__ == "__main__":
    scene = build()
    (HERE / "bench.optodraw.json").write_text(json.dumps(scene.to_spec(), indent=1))
    scene.render_threejs(str(HERE / "bench_3d.html"), show_grid=False)
    if "--no-png" not in sys.argv:
        for name, cam in (("side", (1.0, 0.0, 0.12)), ("front", (0.0, -1.0, 0.25)), ("top", "top"),
                          ("iso", (0.9, -1.0, 0.7)), ("near", (-0.35, -1.0, 0.35))):
            scene.render_3d_image(str(HERE / f"bench_3d_{name}.png"), background="none", engine="viewer",
                                  camera=cam, scale=1.0)
    print("wrote", *(p.name for p in sorted(HERE.glob("bench*"))))
