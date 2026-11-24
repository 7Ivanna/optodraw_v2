"""The cage systems on top of the cryostat bench, from the annotated front photos. Each system is a function; they
share one frame and one vertical plane (x = 0), and meet where the photos show them meeting.

Imaging (30 mm cage, top): a CCM1-4ER cube with the LED arm on one side and the camera tower on the other.

    LED arm (left in the photo, -y):  M660L4 LED -> SM1L30 tube in a CP33 plate, on four rods -> KCB1C (upper)
                                      -> KCB1C (lower, beside the cube) -> into the cube, which sends it down
    camera tower (right, +y):         light from below -> up through the cube -> KCB1C J1 over the cube -> KCB1C J2
                                      one mount over -> two SM1L40 tubes in a CP33 plate, on four rods -> camera
    below the cube:                   four rods down to the excitation line's middle cube (the orange rods)

Collection (60 mm, then 30 mm cage, middle level): its rods pass round the imaging rods.

    KCB2C (60 mm right-angle mount) takes the light from below and turns it toward -y -> 60 mm rods -> LCP33
    (60 to 30 mm adapter) -> two cage wave plates on 30 mm rods -> DFM1BS (magnetic kinematic cube) -> wave plate

Excitation (30 mm cage, bottom level): three CCM1-4ER beamsplitter cubes in a row.

    left cube -> two cage wave plates -> middle cube (under the imaging rods) -> right cube (under the KCB2C), which
    sends the light down to the sample. The KCB2C stands on 60 mm rods round the right cube, down to the board.

Light from the sample comes up into the right cube: part goes on up into the KCB2C (collection), part turns toward
-y to the middle cube and up the imaging rods to the camera. The LED goes the other way, down to the sample.

Sizes are the parts' drawings; spacings are the photos scaled by the imaging cube (38.1 mm across). The photos are the
view from +x: +y (the camera side) is on the right, z is up. The imaging cube's centre is the origin. Nothing stands
on a post: the modules hang on their rods until they join the bench.

    python3 mockups/cryo_setup/cage_systems.py      (cage_systems.optodraw.json, cage_systems_3d.html, *_3d_*.png)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from optodraw import Beam, CageRods, CageWavePlate, Scene
from optodraw.components.vendor import (
    CatalogCageCube,
    CatalogCageMount,
    CatalogCamera,
    CatalogLED,
    CatalogLensTube,
    CatalogRightAngleMount,
)

HERE = Path(__file__).parent
MM = 1 / 2.54                       # scene units per mm
LED_NM = 660

# ---- imaging
CUBE = 38.1 / 2                     # CCM1-4ER half width (mm)
KCB = 48.3 / 2                      # KCB1C half width (mm)
Z_JOG = CUBE + 8.0 + KCB            # J1 over the cube: 8 mm of rod between them in the photo
Y_CAM = 2 * KCB + 1.0               # J2 sits one mount over from J1, the camera tower over it
Y_LED = -(CUBE + 20.0 + KCB)        # the LED pair: 20 mm of rod between the cube and the lower KCB1C
L30 = CatalogLensTube.part_sizes("SM1L30")["length_mm"]     # overall, with the thread
L40 = CatalogLensTube.part_sizes("SM1L40")["length_mm"]
STUB = CatalogLensTube.part_sizes("SM1L30")["stub_mm"]      # the thread that screws into the next part
LED_FRONT = CatalogLED(part="M660L4").ports()["out"].center.x * 2.54   # LED centre to its front, mm

# ---- collection: positions along y are the photo's, from the imaging axis
Z_COL = -73.0                       # the collection axis, below the imaging cube's centre
KCB2 = 76.2 / 2                     # KCB2C half width
Y_KCB2 = 53.8 + KCB2                # its near face 54 mm right of the imaging axis
Y_LCP = -69.0                       # LCP33 adapter
LCP_HALF = 12.7 / 2
Y_WP = (-102.0, -128.0)             # the two wave plates between the adapter and the beamsplitter
DFM = 50.8 / 2                      # DFM1BS half width
Y_DFM = -165.0
Y_WP_OUT = -211.0                   # the wave plate on the far side of the beamsplitter

# ---- excitation
Z_EXC = -144.0                      # the excitation axis; its right cube's top is 14 mm under the KCB2C
Y_EXC_LEFT = -142.0                 # the left cube; the middle one is on the imaging axis, the right under the KCB2C
Y_EXC_WP = (-102.0, -73.0)
Z_BOARD = -233.0                    # where the KCB2C's rods reach the breadboard in the photo

# where the module's origin (the imaging cube's centre) sits in the scene, in scene units: set by add_systems
_ORIGIN = [0.0, 0.0, 0.0]


def at(y_mm: float, z_mm: float = 0.0, x_mm: float = 0.0) -> dict:
    """Placement at the module's (x, y, z) in mm, on no post."""
    x0, y0, z0 = _ORIGIN
    return {"center": (x0 + x_mm * MM, y0 + y_mm * MM), "z": z0 + z_mm * MM, "base_mount": "none"}


def rods(scene: Scene, a: tuple[float, float], b: tuple[float, float], label: str, cage: int = 30) -> CageRods:
    """Four cage rods between (y, z) points a and b in mm, along y or along z."""
    (y0, z0), (y1, z1) = a, b
    if abs(y1 - y0) < 1e-9:                                   # vertical
        return scene.add(CageRods(**at(y0, (z0 + z1) / 2), length=abs(z1 - z0) * MM, rotation_y=90,
                                  end_plates=False, cage=cage, label=label))
    return scene.add(CageRods(**at((y0 + y1) / 2, z0), length=abs(y1 - y0) * MM, angle=90, end_plates=False,
                              cage=cage, label=label))


def imaging(scene: Scene) -> dict:
    # ---- the cube: the vertical line passes through it, the LED comes in from -y and goes down
    cube = scene.add(CatalogCageCube(part="CCM1-4ER", angle=90, rotation_x=-90, label="CCM1-4ER (imaging)", **at(0.0)))
    rods(scene, (0.0, -CUBE), (0.0, Z_EXC + CUBE), "Rods imaging-excitation")

    # ---- camera tower: J1 over the cube, J2 one mount toward +y, tubes and camera above J2
    j1 = scene.add(CatalogRightAngleMount(part="KCB1C", rotation_y=-90, label="J1 (KCB1C)", **at(0.0, Z_JOG)))
    j2 = scene.add(CatalogRightAngleMount(part="KCB1C", angle=90, rotation_x=90, label="J2 (KCB1C)",
                                          **at(Y_CAM, Z_JOG)))
    rods(scene, (0.0, CUBE), (0.0, Z_JOG - KCB), "Rods cube-J1")
    # two SM1L40s: each one's 3 mm thread goes into the part below it
    t0 = Z_JOG + KCB - STUB                                   # the lower tube's thread end, in J2's top bore
    t1 = t0 + L40 - STUB
    t2 = t1 + L40
    tube_lo = scene.add(CatalogLensTube(part="SM1L40", rotation_y=-90, label="SM1L40 (lower)",
                                        **at(Y_CAM, t0 + L40 / 2)))
    tube_hi = scene.add(CatalogLensTube(part="SM1L40", rotation_y=-90, label="SM1L40 (upper)",
                                        **at(Y_CAM, t1 + L40 / 2)))
    scene.add(CatalogCageMount(part="CP33", rotation_y=90, label="CP33 (camera)", **at(Y_CAM, Z_JOG + KCB + 142.0)))
    rods(scene, (Y_CAM, Z_JOG + KCB), (Y_CAM, t2), "Rods camera")
    camera = scene.add(CatalogCamera(part="CS165MU", rotation_y=-90, label="Camera (CS165MU)",
                                     **at(Y_CAM, t2 + 10.0)))

    # ---- LED arm: the lower KCB1C beside the cube, the upper one over it, the LED out toward -y
    k_lo = scene.add(CatalogRightAngleMount(part="KCB1C", rotation_y=90, label="LED KCB1C (lower)", **at(Y_LED)))
    k_hi = scene.add(CatalogRightAngleMount(part="KCB1C", angle=90, rotation_x=-90, label="LED KCB1C (upper)",
                                            **at(Y_LED, Z_JOG)))
    rods(scene, (Y_LED + KCB, 0.0), (-CUBE, 0.0), "Rods cube-LED")
    face = Y_LED - KCB                                        # the upper KCB1C's outer face
    led_tube = scene.add(CatalogLensTube(part="SM1L30", angle=90, label="SM1L30 (LED)",
                                         **at(face + STUB - L30 / 2, Z_JOG)))
    # the LED's front at the tube's far end
    led = scene.add(CatalogLED(part="M660L4", angle=90, label="LED (M660L4)",
                               **at(face + STUB - L30 - LED_FRONT, Z_JOG)))
    scene.add(CatalogCageMount(part="CP33", angle=90, label="CP33 (LED)", **at(face - 70.0, Z_JOG)))
    rods(scene, (face, Z_JOG), (face - 98.0, Z_JOG), "Rods LED")
    return {"cube": cube, "j1": j1, "j2": j2, "tube_lo": tube_lo, "tube_hi": tube_hi, "camera": camera,
            "k_lo": k_lo, "k_hi": k_hi, "led_tube": led_tube, "led": led}


def collection(scene: Scene, z_board: float = Z_BOARD) -> dict:
    def put(y: float) -> dict:
        return at(y, Z_COL)

    # light comes up from below into the KCB2C, which sends it toward -y
    kcb2 = scene.add(CatalogRightAngleMount(part="KCB2C", angle=90, rotation_x=-90, label="KCB2C",
                                            **put(Y_KCB2)))
    lcp = scene.add(CatalogCageMount(part="LCP33", angle=90, label="LCP33 (60 to 30 mm)", **put(Y_LCP)))
    rods(scene, (Y_LCP + LCP_HALF, Z_COL), (Y_KCB2 - KCB2, Z_COL), "Rods 60 mm (collection)", cage=60)
    rods(scene, (Y_KCB2, Z_COL - KCB2), (Y_KCB2, z_board), "Rods KCB2C to board", cage=60)

    wp_a = scene.add(CageWavePlate(plate="half", angle=90, label="Collection wave plate 1", **put(Y_WP[0])))
    wp_b = scene.add(CageWavePlate(plate="quarter", angle=90, label="Collection wave plate 2", **put(Y_WP[1])))
    rods(scene, (Y_DFM + DFM, Z_COL), (Y_LCP - LCP_HALF, Z_COL), "Rods DFM1BS-LCP33")

    # the light arrives from +y: the cube's "in" faces +y, it goes straight on toward -y
    dfm = scene.add(CatalogCageCube(part="DFM1BS", angle=-90, label="DFM1BS (magnetic BS)", **put(Y_DFM)))
    wp_c = scene.add(CageWavePlate(plate="half", angle=90, label="Collection wave plate 3", **put(Y_WP_OUT)))
    rods(scene, (Y_WP_OUT - 10.0, Z_COL), (Y_DFM - DFM, Z_COL), "Rods DFM1BS out")
    return {"kcb2": kcb2, "lcp": lcp, "wp_a": wp_a, "wp_b": wp_b, "dfm": dfm, "wp_c": wp_c}


def excitation(scene: Scene) -> dict:
    def cube(y: float, label: str) -> CatalogCageCube:
        # "in" faces -y, "trans" +y; turned so "refl" faces down and "tap" up
        return scene.add(CatalogCageCube(part="CCM1-4ER", angle=90, rotation_x=-90, label=label, **at(y, Z_EXC)))

    # the left cube's side ports face +-x: a second beam can join the line from the side
    left = scene.add(CatalogCageCube(part="CCM1-4ER", angle=90, label="CCM1-4ER (excitation, left)",
                                     **at(Y_EXC_LEFT, Z_EXC)))
    mid = cube(0.0, "CCM1-4ER (excitation, middle)")
    right = cube(Y_KCB2, "CCM1-4ER (excitation, right)")
    wp_a = scene.add(CageWavePlate(plate="half", angle=90, label="Excitation wave plate 1", **at(Y_EXC_WP[0], Z_EXC)))
    wp_b = scene.add(CageWavePlate(plate="quarter", angle=90, label="Excitation wave plate 2",
                                   **at(Y_EXC_WP[1], Z_EXC)))
    rods(scene, (Y_EXC_LEFT + CUBE, Z_EXC), (-CUBE, Z_EXC), "Rods excitation left-middle")
    rods(scene, (CUBE, Z_EXC), (Y_KCB2 - CUBE, Z_EXC), "Rods excitation middle-right")
    return {"left": left, "mid": mid, "right": right, "wp_a": wp_a, "wp_b": wp_b}


def add_systems(scene: Scene, origin: tuple[float, float, float] = (0.0, 0.0, 0.0),
                z_board: float = Z_BOARD) -> dict:
    """The three systems with the module's origin at ``origin`` (scene units) and the KCB2C's rods down to
    ``z_board`` (mm, module frame); returns every part the light paths name, keyed by system."""

    _ORIGIN[:] = origin
    try:
        return {"im": imaging(scene), "col": collection(scene, z_board), "ex": excitation(scene)}
    finally:
        _ORIGIN[:] = [0.0, 0.0, 0.0]


def add_light(scene: Scene, parts: dict, from_sample: list, led_nm: float = LED_NM,
              excitation_in: list[tuple[list, dict]] | None = None) -> None:
    """Excitation down to the sample; the sample's light (``from_sample``: the hops up to the right excitation
    cube's bottom port) up to the collection line and the camera; the LED down to the sample. ``excitation_in``:
    (hops ending at a port of the left excitation cube, beam style) per beam that feeds the line; by default one
    beam from the cube's back port."""

    im, col, ex = parts["im"], parts["col"], parts["ex"]
    to_sample = [(ex["right"], "in"), (ex["right"], "refl"), *reversed(from_sample[:-1])]
    along = [(ex["left"], "trans"), (ex["wp_a"], "in"), (ex["wp_a"], "out"), (ex["wp_b"], "in"), (ex["wp_b"], "out"),
             (ex["mid"], "in"), (ex["mid"], "trans"), *to_sample]
    for hops, style in excitation_in or [([(ex["left"], "in")], {"color": "#2e86de", "opacity": 0.6,
                                                                   "label": "Excitation"})]:
        scene.add(Beam.through(*hops, *along, **style))
    scene.add(Beam.through(*from_sample, (ex["right"], "tap"), (col["kcb2"], "out"), (col["kcb2"], "in"),
                           (col["lcp"], "out"), (col["lcp"], "in"), (col["wp_a"], "out"), (col["wp_a"], "in"),
                           (col["wp_b"], "out"), (col["wp_b"], "in"), (col["dfm"], "in"), (col["dfm"], "trans"),
                           (col["wp_c"], "out"), (col["wp_c"], "in"), color="#d35400", opacity=0.6,
                           label="Collection"))
    scene.add(Beam.through(*from_sample, (ex["right"], "in"), (ex["mid"], "trans"), (ex["mid"], "tap"),
                           (im["cube"], "refl"), (im["cube"], "tap"), (im["j1"], "in"), (im["j1"], "out"),
                           (im["j2"], "in"), (im["j2"], "out"), (im["tube_lo"], "in"), (im["tube_lo"], "out"),
                           (im["tube_hi"], "in"), (im["tube_hi"], "out"), (im["camera"], "in"),
                           wavelength=led_nm, opacity=0.5, label="Imaging"))
    scene.add(Beam.through((im["led"], "out"), (im["led_tube"], "out"), (im["led_tube"], "in"), (im["k_hi"], "in"),
                           (im["k_hi"], "out"), (im["k_lo"], "in"), (im["k_lo"], "out"), (im["cube"], "in"),
                           (im["cube"], "refl"), (ex["mid"], "tap"), (ex["mid"], "trans"), *to_sample,
                           wavelength=led_nm, opacity=0.5, label="LED"))


def build() -> Scene:
    scene = Scene(title="Cage systems", width=160, height=160, platform="free_space")
    parts = add_systems(scene)
    add_light(scene, parts, [(parts["ex"]["right"], "refl")])     # below the right cube: the objective
    return scene


if __name__ == "__main__":
    scene = build()
    (HERE / "cage_systems.optodraw.json").write_text(json.dumps(scene.to_spec(), indent=1))
    scene.render_threejs(str(HERE / "cage_systems_3d.html"), show_grid=False)
    if "--no-png" not in sys.argv:
        for name, cam in (("front", (1.0, 0.0, 0.0)), ("iso", (1.0, -0.6, 0.5)), ("top", "top")):
            scene.render_3d_image(str(HERE / f"cage_systems_3d_{name}.png"), background="none", engine="viewer",
                                  camera=cam, scale=1.0)
    print("wrote", *(p.name for p in sorted(HERE.glob("cage_systems*"))))
