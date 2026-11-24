"""3D mockup of the cryostat microscope bench: fibers, steering mirrors and two stepper-motor mirrors, a row of
30 mm cage cubes, and a vertical cage tower (LED arm, KCB1 pair, camera) over the cryostat cabinet the
breadboard sits on.

Run:  python3 mockups/cryo_setup/setup.py            (writes setup_3d.html, setup_2d.svg, a quick setup_3d.png)
      python3 mockups/cryo_setup/setup.py --final    (the studio PNG: minutes)
      python3 mockups/cryo_setup/setup.py --no-png   (skip the PNG, which needs Chrome)

Not to scale. The fiber each motorized mirror points at is set by EXCITATION and COLLECTION below.
"""

from __future__ import annotations

import sys
from pathlib import Path

from optodraw import (
    Beam,
    Breadboard,
    CageCube,
    CageRods,
    CageTower,
    CryostatCabinet,
    FiberCollimator,
    Filter,
    LaserDriver,
    Mirror,
    MotorizedMirror,
    Scene,
)
from optodraw.components.optics.cage import CUBE_HALF
from optodraw.layout import aim

HERE = Path(__file__).parent
EXCITATION = "003"            # "003" (below MM1) or "Olaf 1" (above MM1)
COLLECTION = "Olaf E"         # "Olaf E" (via M3, M4) or "004" (beside MM2)
EXC_NM, COL_NM, LED_NM = 532, 700, 590    # beam colours only (placeholders)

BEAM = 30.0                   # the renderer's bench beam plane above the table
BOARD_T = 5.0                 # a 1/2 inch breadboard; posts stand on it
SAMPLE_DEPTH = 55.0           # the sample in the cryostat, below the beam plane
TOWER = (0.0, 30.0)
BOARD = (177.0, 236.0)        # 450 x 600 mm


def rods_between(scene, a, b):
    """Cage rods from the face of cube ``a`` to the face of cube ``b`` (both on y = TOWER y)."""
    x0, x1 = a + CUBE_HALF, b - CUBE_HALF
    return scene.add(CageRods(center=((x0 + x1) / 2, TOWER[1]), length=x1 - x0, end_plates=False))


def build() -> Scene:
    scene = Scene(title="Cryostat microscope bench", width=260, height=300, platform="free_space")
    board_top = BEAM - BOARD_T
    scene.add(Breadboard(center=(0, 0), length=BOARD[0], width=BOARD[1], thickness=BOARD_T,
                         through_holes=[(TOWER[0], TOWER[1], 8.0)], label="Breadboard"))
    scene.add(CryostatCabinet(center=TOWER, board_bottom=-BEAM, sample_depth=SAMPLE_DEPTH,
                              cabinet_offset=(0.0, -TOWER[1]), label="Cryostat"))
    tower = scene.add(CageTower(center=TOWER, board=board_top, sample_depth=SAMPLE_DEPTH, label="Cage tower"))
    scene.add(LaserDriver(center=(-68, -105), label="LED driver"))

    # the row of cage cubes at beam height, left of the tower: dichroic beamsplitters, rods between
    y = TOWER[1]
    xs = (-21.0, -40.0, -59.0)
    cubes = [scene.add(CageCube(center=(x, y), coating_color=c, label=n))
             for x, c, n in zip(xs, ("#7fd6d0", "#f2a65a", "#ffffff"), ("BS A", "BS B", "BS C"))]
    rods = [rods_between(scene, xs[0], TOWER[0])] + [rods_between(scene, xs[i + 1], xs[i]) for i in range(2)]

    # excitation side: MM1 turns to fiber 003 (below, through M1 and M2) or Olaf 1 (above)
    mm1 = scene.add(MotorizedMirror(center=(-80, y), label="MM1"))
    m1 = scene.add(Mirror(center=(-80, -75), label="M1"))
    m2 = scene.add(Mirror(center=(-45, -75), label="M2"))
    f003 = scene.add(FiberCollimator(center=(-45, -100), angle=90, label="003"))
    folaf1 = scene.add(FiberCollimator(center=(-80, 100), angle=-90, label="Olaf 1"))

    # collection side: MM2 under BS A turns to Olaf E (through M3, M4 and a filter) or to 004 (left)
    mm2 = scene.add(MotorizedMirror(center=(xs[0], -45), label="MM2"))
    m3 = scene.add(Mirror(center=(55, -45), label="M3"))
    m4 = scene.add(Mirror(center=(55, 80), label="M4"))
    filt = scene.add(Filter(center=(68, 80), label="Filter"))
    folafe = scene.add(FiberCollimator(center=(80, 80), angle=180, label="Olaf E"))
    f004 = scene.add(FiberCollimator(center=(-60, -45), angle=0, label="004"))

    aim(m2, f003, m1)
    aim(m1, m2, mm1)
    exc_from = m1 if EXCITATION == "003" else folaf1
    aim(mm1, exc_from, cubes[2])
    tap = cubes[0].world_port("tap").center.as_2d()
    col_to = m3 if COLLECTION == "Olaf E" else f004
    aim(mm2, tap, col_to)
    aim(m3, mm2, m4)
    aim(m4, m3, filt)

    # the cage line from MM1 to the tower, as stops
    line = [(cubes[2], "in"), (cubes[2], "trans"), (rods[2], "in"), (rods[2], "out"),
            (cubes[1], "in"), (cubes[1], "trans"), (rods[1], "in"), (rods[1], "out"),
            (cubes[0], "in"), (cubes[0], "trans"), (rods[0], "in"), (rods[0], "out"), (tower, "in"), (tower, "sample")]
    exc_head = [(f003, "out"), m2, m1, mm1] if EXCITATION == "003" else [(folaf1, "out"), mm1]
    scene.add(Beam.through(*exc_head, *line, wavelength=EXC_NM, width=1.6, label="Excitation"))

    back = [(tower, "sample"), (tower, "in"), (rods[0], "out"), (rods[0], "in"), (cubes[0], "trans"), (cubes[0], "tap"), mm2]
    col_tail = [m3, m4, (filt, "in"), (filt, "out"), (folafe, "out")] if COLLECTION == "Olaf E" else [(f004, "out")]
    scene.add(Beam.through(*back, *col_tail, wavelength=COL_NM, width=1.6, offset=1.8, label="Collection"))

    scene.add(Beam.through((tower, "led"), (tower, "sample"), wavelength=LED_NM, opacity=0.5, label="LED"))
    scene.add(Beam.through((tower, "sample"), (tower, "camera"), wavelength=LED_NM, opacity=0.5, label="Imaging"))
    return scene


if __name__ == "__main__":
    scene = build()
    scene.render_svg(str(HERE / "setup_2d.svg"))
    scene.render_threejs(str(HERE / "setup_3d.html"), show_grid=False)
    if "--no-png" not in sys.argv:
        final = "--final" in sys.argv
        scene.render_3d_image(str(HERE / "setup_3d.png"), background="none", engine="studio" if final else "viewer",
                              camera=(-0.35, -1.0, 0.4), scale=1.0)
    (HERE / "setup.optodraw.json").write_text(__import__("json").dumps(scene.to_spec(), indent=1))
    print("wrote", *(p.name for p in sorted(HERE.glob("setup*"))))
