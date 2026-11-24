"""3D mockup of the cryostat microscope bench on the attocube breadboard (500 x 475 mm, drawing 1011879-2), laid out
from the annotated top view: positions are the photo mapped onto the board through its four corners (``PHOTO``),
good to about a hole. The KCB2 (the large right-angle mount) stands over the board's Ø31 hole, 75 mm from its far
edge, one cube up: it turns every beam from the near side down through the objective into the cryostat, and the light
from the sample back out.

Each stepper mirror sends its fiber's light one of two ways (the colours of the annotated photo):

    003 (left):     MM1 in the beam -> KM100 B -> D mirror -> KCB1 P1 (up)                            orange
                    MM1 turned away -> KM100 A -> KM100 C -> KM100 E -> P1                            light blue
                    then the cage line one cube high: DFM1BS -> CRM1Ts -> KCB1 P2 -> cube C1
    Olaf E (right): filter -> MM2 in the beam -> KM100 F -> KM100 G -> CCM1 (folds it into the line)  red
                    filter -> MM2 turned away -> KM100 I -> KCB1 -> through the CCM1                  dark blue
                    the cage line at beam height toward the far edge, then a KCB1 pair lifts it into C1

The line into the KCB2, one cube up, from the near side: the Olaf E lift -> C1 (003 joins) -> U1 -> KCB2 -> down
through the objective to the sample. The tower stands on U1: the LED, on the near side one cube above C LED and
facing the tower, drops into it through a KCB1 pair, and C LED sends it down into U1. Imaging: sample -> KCB2 -> U1
-> up through C LED -> KCB1 pair J1, J2 (one cube toward the far edge) -> two tubes -> camera. Every post has a CF125
clamping fork, turned the way the fork beside it in the photo points.

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
    CageCube,
    CageRightAngleMirror,
    CageRods,
    Camera,
    CryostatCabinet,
    FiberCollimator,
    Filter,
    Lamp,
    LensTube,
    Mirror,
    MotorizedMirror,
    Objective,
    Photodiode,
    Scene,
)
from optodraw.components.optics.cage import CUBE_HALF as H
from optodraw.components.vendor import CatalogCageCube, CatalogCageMount, CatalogTableClamp
from optodraw.components.vendor.data import CLAMPS
from optodraw.layout import aim

HERE = Path(__file__).parent
BEAM = 30.0                  # the renderer's beam plane above the table
BOARD_PART = "attocube 1011879-2"
BOARD_T = 10.0 / 2.54        # breadboard thickness (10 mm): its top is BEAM - BOARD_T below the beam plane
HALF = (250.0 / 2.54, 237.5 / 2.54)      # the board's half length and half width


def mm(x: float, y: float) -> tuple[float, float]:
    """A board position in mm (from the board's middle, the Ø31 hole on +y) in scene units."""

    return x / 2.54, y / 2.54


AX, AY = mm(0.0, 237.5 - 75.0)   # the tower's axis, over the Ø31 hole
Z_UP, Z_LED = 38.0, 87.0     # the upper cage level and the LED arm
Z_JOG = Z_LED + 2 * H        # the KCB1 pair under the camera
LED_NM = 590
# the annotated photo's colours for the four routes
ORANGE, LIGHT_BLUE, RED, DARK_BLUE = "#f39c12", "#8ecdf5", "#d62828", "#1f4fd6"

# the forks in the photo, mapped onto the board: (x, y) of the U round the post base in mm, and the way the fork
# points from there, in degrees
PHOTO_FORKS = [(-89, 201, -174), (114, 223, -108), (175, 119, -136), (90, 55, -79), (228, 39, -116), (221, -63, 179),
               (180, -193, 179), (5, -199, 14), (40, -59, 52), (-178, 42, 60), (-101, -17, -109), (-249, -23, -43),
               (-231, -76, -35), (-208, -151, 27), (-220, -194, 8), (-24, -180, 152)]


def vrods(scene, z0, z1, x=AX, y=AY, plates=False, cage=30):
    """Vertical cage rods from height z0 to z1 on the axis at (x, y)."""
    return scene.add(CageRods(center=(x, y), z=(z0 + z1) / 2, length=z1 - z0, rotation_y=90, end_plates=plates,
                              cage=cage, base_mount="none"))


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

    # ---- the KCB2 over the window, one cube up: it takes every beam from the near side (-y) and turns it down
    # through the objective into the cryostat, and turns the light from the sample back toward the near side
    kcb2_half = 15.0                                          # the 60 mm cage mount's half width
    kcb2 = scene.add(CageRightAngleMirror(cage=60, center=(AX, AY), z=Z_UP, angle=90, rotation_x=-90, label="KCB2",
                                          base_mount="none"))
    objective = scene.add(Objective(center=(AX, AY), z=-H - 7.5, rotation_y=90, label="Objective", base_mount="none"))
    vrods(scene, board_top, Z_UP - kcb2_half, cage=60, plates=True)  # the KCB2 on rods round the objective

    # ---- the line into the KCB2 at the upper level, from the near side: Olaf E lifted up, C1 (003 joins from the
    # left), U1 under the tower (the LED comes down into it, the image goes up out of it)
    y_u1 = AY - kcb2_half - H - 3.0
    y_c1 = y_u1 - 2 * H - 4.0
    y_lift = y_c1 - 2 * H - 4.0
    u1 = scene.add(CageCube(center=(AX, y_u1), z=Z_UP, rotation_y=90, coating_color="#f2a65a", label="U1 (CCM1)",
                            base_mount="none"))
    c1 = scene.add(CageCube(center=(AX, y_c1), z=Z_UP, coating_color="#7fd6d0", label="C1 (CCM1)", base_mount="none"))
    lift_lo = scene.add(CageRightAngleMirror(center=(AX, y_lift), angle=90, rotation_x=90, label="Olaf E lift (KCB1)"))
    lift_hi = scene.add(CageRightAngleMirror(center=(AX, y_lift), z=Z_UP, rotation_y=-90,
                                             label="Olaf E lift (upper KCB1)", base_mount="none"))
    vrods(scene, H, Z_UP - H, y=y_lift)
    vrods(scene, board_top, Z_UP - H, y=y_u1, plates=True)
    hrods(scene, (AX, y_lift - H), (AX, AY - kcb2_half), Z_UP)

    # ---- the tower over U1: C LED (CCM1), the LED arm, the camera
    cled = scene.add(CageCube(center=(AX, y_u1), z=Z_LED, angle=90, rotation_x=-90, label="C LED (CCM1)",
                              base_mount="none"))
    vrods(scene, Z_UP + H, Z_LED - H, y=y_u1)
    vrods(scene, Z_LED + H, Z_JOG - H, y=y_u1)

    # the camera: a KCB1 pair over C LED steps the image one cube toward the far edge (+y), two tubes, camera
    y_cam = y_u1 + 2 * H
    j1 = scene.add(CageRightAngleMirror(center=(AX, y_u1), z=Z_JOG, rotation_y=-90, label="J1 (KCB1)", base_mount="none"))
    j2 = scene.add(CageRightAngleMirror(center=(AX, y_cam), z=Z_JOG, angle=90, rotation_x=90, label="J2 (KCB1)",
                                        base_mount="none"))
    tube_z0, tube_mid, tube_z1 = Z_JOG + H, Z_JOG + H + 45.0, Z_JOG + H + 63.0
    tube = scene.add(LensTube(center=(AX, y_cam), z=(tube_z0 + tube_mid) / 2, length=tube_mid - tube_z0,
                              rotation_y=-90, label="Tube", base_mount="none"))
    tube2 = scene.add(LensTube(center=(AX, y_cam), z=(tube_mid + tube_z1) / 2, length=tube_z1 - tube_mid,
                               rotation_y=-90, label="Tube (upper)", base_mount="none"))
    camera = scene.add(Camera(center=(AX, y_cam), z=tube_z1 + 3.0, rotation_y=-90, label="Camera", base_mount="none"))

    # the LED on the near side (-y), one cube above C LED and facing the tower: a KCB1 pair drops it into C LED
    y_led = y_u1 - 2 * H
    k_a = scene.add(CageRightAngleMirror(center=(AX, y_led), z=Z_JOG, angle=90, rotation_x=-90,
                                         label="LED KCB1 (upper)", base_mount="none"))
    k_b = scene.add(CageRightAngleMirror(center=(AX, y_led), z=Z_LED, rotation_y=90, label="LED KCB1 (lower)",
                                         base_mount="none"))
    vrods(scene, Z_LED + H, Z_JOG - H, y=y_led)
    led_y = y_led - 45.0
    led = scene.add(Lamp(center=(AX, led_y), z=Z_JOG, angle=90, label="LED", base_mount="none"))
    led_tube = scene.add(LensTube(center=(AX, y_led - 20.0), z=Z_JOG, angle=90, length=20.0, label="LED lens",
                                  base_mount="none"))
    hrods(scene, (AX, led_y + 6.0), (AX, y_led - H), Z_JOG)

    # ---- 003's cage line, one cube up: KCB1 P1 lifts it, the DFM1BS turns it toward the far edge, a CRM1T, KCB1 P2
    # turns it into C1
    left, y_up = AX - 2 * H, mm(0, -40)[1]
    p1 = scene.add(CageRightAngleMirror(center=(left, y_up), angle=90, rotation_x=90, label="P1 (KCB1)"))
    dfm = scene.add(CatalogCageCube(part="DFM1BS", center=(left, y_up), z=Z_UP, rotation_y=-90, label="DFM1BS",
                                    base_mount="none"))
    p2 = scene.add(CageRightAngleMirror(center=(left, y_c1), z=Z_UP, angle=90, rotation_x=180, label="P2 (KCB1)",
                                        base_mount="none"))
    vrods(scene, H, Z_UP - H, x=left, y=y_up)
    hrods(scene, (left, y_up - 3 * H), (left, y_c1 - H), Z_UP)
    for y in (y_up - 2 * H - 2.0, y_up + 2 * H + 6.0):
        scene.add(CatalogCageMount(part="CRM1T", center=(left, y), z=Z_UP, angle=90, label="CRM1T",
                                   base_mount="none"))

    # ---- 003 on the left edge and its two routes
    f003 = scene.add(FiberCollimator(center=mm(-232, -4), angle=0, label="003"))
    mm1 = scene.add(MotorizedMirror(center=mm(-200, -4), label="MM1"))
    km_a = scene.add(Mirror(center=mm(-122, -4), label="KM100 A"))
    km_b = scene.add(Mirror(center=mm(-245, -84), label="KM100 B"))
    km_c = scene.add(Mirror(center=mm(-232, -213), label="KM100 C"))
    d_left = scene.add(Mirror(center=(left, mm(0, -96)[1]), label="D mirror (003)"))
    km_e = scene.add(Mirror(center=(left, mm(0, -228)[1]), label="KM100 E"))
    into_p1 = p1.world_port("in").center.as_2d()
    aim(mm1, f003, km_b)
    aim(km_b, mm1, d_left)
    aim(d_left, km_b, into_p1)
    aim(km_a, f003, km_c)
    aim(km_c, km_a, km_e)
    aim(km_e, km_c, into_p1)

    # ---- Olaf E down from the far right corner, a filter, and its two routes
    olaf_e = scene.add(FiberCollimator(center=mm(188, 175), angle=-90, label="Olaf E"))
    filt = scene.add(Filter(center=mm(188, 140), angle=-90, label="Filter"))
    mm2 = scene.add(MotorizedMirror(center=mm(188, 75), label="MM2"))
    km_f = scene.add(Mirror(center=mm(116, 70), label="KM100 F"))
    km_g = scene.add(Mirror(center=mm(226, -53), label="KM100 G"))
    km_i = scene.add(Mirror(center=mm(188, -194), label="KM100 I"))
    # Olaf E's cage line at beam height, toward the far edge: a KCB1 turns the dark-blue route into it, the CCM1 folds
    # the red route in and passes the dark blue, a CRM1T, then the lift up to the KCB2's level
    kcb_in = scene.add(CageRightAngleMirror(center=(AX, mm(0, -194)[1]), rotation_y=180, label="Olaf E in (KCB1)"))
    ccm1 = scene.add(CageCube(center=(AX, mm(0, -53)[1]), rotation_y=180, label="CCM1", base_mount="none"))
    hrods(scene, (AX, mm(0, -194)[1] + 3 * H), (AX, y_lift - H), 0.0)
    scene.add(CatalogCageMount(part="CRM1T", center=(AX, mm(0, -120)[1]), angle=90, label="CRM1T", base_mount="none"))
    aim(mm2, filt, km_f)
    aim(km_f, mm2, km_g)
    aim(km_g, km_f, ccm1.world_port("in").center.as_2d())
    aim(km_i, filt, kcb_in.world_port("in").center.as_2d())

    # ---- the other parts on the board, off the traced routes
    scene.add(FiberCollimator(center=mm(-98, 215), angle=-90, label="Olaf 1"))
    scene.add(Photodiode(center=mm(114, 215), angle=-90, label="PD"))

    # ---- light: each route into the line, along it to the KCB2, then down to the sample
    to_sample = [(kcb2, "in"), (kcb2, "out"), (objective, "in"), (objective, "out"), (cryo, "sample")]
    via_c1 = [(c1, "refl"), (u1, "tap"), (u1, "refl"), *to_sample]
    up_003 = [(p1, "in"), (p1, "out"), (dfm, "in"), (dfm, "refl"), (p2, "in"), (p2, "out"), (c1, "in"), *via_c1]
    lift = [(ccm1, "refl"), (lift_lo, "in"), (lift_lo, "out"), (lift_hi, "in"), (lift_hi, "out"), (c1, "tap"), *via_c1]
    scene.add(Beam.through((f003, "out"), mm1, km_b, d_left, *up_003, color=ORANGE, width=1.4,
                           label="003, MM1 in the beam"))
    scene.add(Beam.through((f003, "out"), km_a, km_c, km_e, *up_003, color=LIGHT_BLUE, width=1.4,
                           label="003, MM1 turned away"))
    scene.add(Beam.through((olaf_e, "out"), (filt, "in"), (filt, "out"), mm2, km_f, km_g, (ccm1, "in"), *lift,
                           color=RED, width=1.4, label="Olaf E, MM2 in the beam"))
    scene.add(Beam.through((olaf_e, "out"), (filt, "in"), (filt, "out"), km_i, (kcb_in, "in"), (kcb_in, "out"),
                           (ccm1, "tap"), *lift, color=DARK_BLUE, width=1.4, label="Olaf E, MM2 turned away"))
    scene.add(Beam.through((led, "out"), (led_tube, "in"), (led_tube, "out"), (k_a, "in"), (k_a, "out"), (k_b, "in"),
                           (k_b, "out"), (cled, "in"), (cled, "refl"), (u1, "in"), (u1, "refl"), *to_sample,
                           wavelength=LED_NM, opacity=0.5, label="LED"))
    scene.add(Beam.through((cryo, "sample"), (objective, "out"), (objective, "in"), (kcb2, "out"), (kcb2, "in"),
                           (u1, "refl"), (u1, "in"), (cled, "refl"), (cled, "tap"), (j1, "in"), (j1, "out"),
                           (j2, "in"), (j2, "out"), (tube, "in"), (tube, "out"), (tube2, "in"), (tube2, "out"),
                           (camera, "in"),
                           wavelength=LED_NM, opacity=0.5, label="Imaging"))
    clamp_posts(scene)
    return scene


if __name__ == "__main__":
    scene = build()
    (HERE / "bench.optodraw.json").write_text(json.dumps(scene.to_spec(), indent=1))
    scene.render_threejs(str(HERE / "bench_3d.html"), show_grid=False)
    if "--no-png" not in sys.argv:
        for name, cam in (("side", (1.0, 0.0, 0.12)), ("front", (0.0, -1.0, 0.25)), ("top", "top"),
                          ("iso", (0.9, -1.0, 0.7))):
            scene.render_3d_image(str(HERE / f"bench_3d_{name}.png"), background="none", engine="viewer",
                                  camera=cam, scale=1.0)
    print("wrote", *(p.name for p in sorted(HERE.glob("bench*"))))
