"""The 30 mm cage parts, the stepper-motor mirror, the cryostat cabinet and a breadboard with through-holes."""

from __future__ import annotations

import pytest

from optodraw import (
    Beam,
    Breadboard,
    CageCube,
    CageRightAngleMirror,
    CageRods,
    CageTower,
    CryostatCabinet,
    FiberCollimator,
    MotorizedMirror,
    Scene,
    check_part_3d,
)
from optodraw.components.optics.cage import CUBE_HALF
from optodraw.symbols import lookup

from optodraw import CageWavePlate  # noqa: E402

PARTS = (CageCube, CageRods, CageRightAngleMirror, MotorizedMirror, CageTower, CryostatCabinet, CageWavePlate)


@pytest.mark.parametrize("cls", PARTS, ids=lambda c: c.__name__)
def test_a_cage_part_stands_whole_and_has_its_symbol(cls):
    part = cls()
    assert check_part_3d(part) == []
    symbol = lookup(part)
    assert symbol.exact and symbol.source == "prebuilt"


def test_cage_parts_keep_their_values_through_a_saved_scene():
    scene = Scene()
    scene.add(CageCube(center=(0, 0), coating_color="#7fd6d0"))
    scene.add(CageRods(center=(20, 0), length=12.0, end_plates=False))
    scene.add(CageTower(center=(40, 0), upper=40.0, led_len=50.0))
    scene.add(CryostatCabinet(center=(40, 0), sample_depth=60.0, cabinet_offset=(0.0, -10.0)))
    again = {type(n).__name__: n for n in Scene.from_spec(scene.to_spec()).walk()}
    assert again["CageCube"].coating_color == "#7fd6d0"
    assert (again["CageRods"].length, again["CageRods"].end_plates) == (12.0, False)
    assert (again["CageTower"].upper, again["CageTower"].led_len) == (40.0, 50.0)
    assert again["CryostatCabinet"].sample_depth == 60.0


def test_a_beam_goes_down_the_tower_to_the_sample_and_up_to_the_camera():
    scene = Scene()
    tower = scene.add(CageTower(center=(0, 0), sample_depth=55.0))
    fiber = scene.add(FiberCollimator(center=(-40, 0)))
    down = scene.add(Beam.through((fiber, "out"), (tower, "in"), (tower, "sample")))
    up = scene.add(Beam.through((tower, "sample"), (tower, "camera")))
    points = down.resolve_points()
    assert points[-2] == pytest.approx((0.0, 0.0, 0.0))            # turned down at the lower cube
    assert points[-1] == pytest.approx((0.0, 0.0, -55.0))          # at the sample
    camera = up.resolve_points()
    assert camera[-1][2] == pytest.approx(tower.camera_z)          # out of the top, one cube over
    assert camera[-1][0] == pytest.approx(-2 * CUBE_HALF)


def test_the_motor_port_sits_where_the_symbol_draws_the_motor():
    mirror = MotorizedMirror()
    ports = mirror.ports()
    assert ports["motor"].kind == "electrical"
    reach = (ports["motor"].center.x - ports["io"].center.x) / mirror.aperture
    assert reach == pytest.approx(MotorizedMirror.MOTOR_REACH)
    assert set(lookup(mirror).ports) == {"io", "motor"}


def test_a_breadboard_takes_through_holes_as_a_list_or_as_text():
    assert Breadboard(through_holes=[(0, 30, 8)]).through_holes == [(0.0, 30.0, 8.0)]
    assert Breadboard(through_holes="0 30 8; 20 0 4").through_holes == [(0.0, 30.0, 8.0), (20.0, 0.0, 4.0)]
    assert Breadboard(through_holes="[[0, 30, 8]]").through_holes == [(0.0, 30.0, 8.0)]
    with pytest.raises(ValueError):
        Breadboard(through_holes=[(0, 0, -1)])
    board = Breadboard(through_holes=[(0, 30, 8)])
    geometry = board.geometry_3d()
    assert geometry["shape"] == "extruded_polygon" and len(geometry["holes"]) == 1
    assert Breadboard().geometry_3d()["shape"] == "box"           # without holes it keeps the hole-grid plate
    scene = Scene()
    scene.add(board)
    again = next(n for n in Scene.from_spec(scene.to_spec()).walk() if isinstance(n, Breadboard))
    assert again.through_holes == [(0.0, 30.0, 8.0)]


def test_a_turn_about_x_sends_a_fold_up_off_the_table():
    scene = Scene()
    fold = scene.add(CageRightAngleMirror(center=(0, 0), rotation_x=90))
    out = fold.world_ports()["out"].center
    assert (out.x, out.y, out.z) == pytest.approx((0.0, 0.0, CUBE_HALF))      # up, not up the plan
    again = next(n for n in Scene.from_spec(scene.to_spec()).walk() if isinstance(n, CageRightAngleMirror))
    assert again.rotation_x == 90.0
    flat = Scene()
    flat.add(CageRightAngleMirror(center=(0, 0)))
    assert "rotation_x" not in flat.to_spec()["components"][0]                # a flat part saves no turn


def test_the_3d_view_turns_a_part_the_way_its_ports_turn():
    import math

    import numpy as np

    from optodraw.core.transform import Vec3
    from optodraw.renderers.threejs_renderer import three_euler
    from optodraw.renderers.vector3d_solids import trs

    assert three_euler(Vec3(0, 0, 30)) == pytest.approx([0.0, math.radians(30), 0.0])   # a yaw stays a yaw
    for turn in (Vec3(90, 0, 0), Vec3(90, 0, 90), Vec3(30, 0, -45), Vec3(15, 20, 60)):
        part = CageRightAngleMirror(center=(0, 0))
        part.transform.rotation_deg = turn
        port = part.world_ports()["out"].center                                  # table frame, z up
        local = CageRightAngleMirror().ports()["out"].center
        m = trs(rotation=three_euler(turn))                                      # the viewer's frame, y up
        x, y, z, _ = m @ np.array([local.x, local.z, -local.y, 1.0])
        assert (x, y, z) == pytest.approx((port.x, port.z, -port.y), abs=1e-9)


def test_a_tilt_about_y_turns_a_mirror_face_up():
    from optodraw import Mirror

    scene = Scene()
    mirror = scene.add(Mirror(center=(0, 0), rotation_y=45))
    normal = mirror.transform.rotate_vector(mirror.ports()["io"].normal())
    assert (normal.x, normal.y, normal.z) == pytest.approx((-(0.5 ** 0.5), 0.0, 0.5 ** 0.5))   # the face looks up
    again = next(n for n in Scene.from_spec(scene.to_spec()).walk() if isinstance(n, Mirror))
    assert (again.rotation_x, again.rotation_y) == (0.0, 45.0)


def test_a_part_keeps_its_height_through_a_save_and_a_2d_move():
    from optodraw import Mirror
    from optodraw.app.session import EditorSession

    scene = Scene()
    mirror = scene.add(Mirror(center=(0, 0), z=12.0, label="M"))
    assert mirror.world_ports()["io"].center.z == pytest.approx(12.0)          # beams meet it up there
    spec = scene.to_spec()
    entry = spec["components"][0]
    assert entry["z"] == 12.0 and len(entry["center"]) == 2
    assert next(n for n in Scene.from_spec(spec).walk() if isinstance(n, Mirror)).z == 12.0
    assert Mirror(center=(1, 2, 7)).z == 7.0                                    # a centre with a height

    session = EditorSession()
    session.load(spec)
    session.move_component(entry["id"], center=[30.0, 5.0])
    moved = next(c for c in session.spec["components"] if c["id"] == entry["id"])
    assert moved["center"] == [30.0, 5.0] and moved["z"] == 12.0


def test_every_part_takes_a_height_and_tilts_whatever_its_constructor_reads():
    from optodraw import Camera, Lamp

    lamp = Lamp(center=(0, 0), z=40, rotation_y=-90, base_mount="none", label_side="left")
    assert (lamp.z, lamp.rotation_y, lamp.base_mount, lamp.label_side) == (40.0, -90.0, "none", "left")
    camera = Camera(center=(0, 0), z=5, rotation_x=30)
    assert (camera.z, camera.rotation_x) == (5.0, 30.0)
    assert CageRods().base_mount == "none"                          # a part's own default base stays


def test_a_beam_turns_in_the_middle_of_a_cube_turned_out_of_the_plan():
    scene = Scene()
    cube = scene.add(CageCube(center=(0, 0), rotation_x=-90))
    fiber = scene.add(FiberCollimator(center=(-30, 0)))
    beam = scene.add(Beam.through((fiber, "out"), (cube, "in"), (cube, "refl"), (0.0, 0.0, -30.0)))
    points = beam.resolve_points()
    assert points[2] == pytest.approx((0.0, 0.0, 0.0))             # the turn, in the middle
    assert points[3] == pytest.approx((0.0, 0.0, -CUBE_HALF))       # out of the bottom face


def test_a_60_mm_cage_part_is_the_bigger_size_and_keeps_it_through_a_save():
    from optodraw import CageWavePlate
    from optodraw.components.optics.cage import CAGE_SIZES

    big, small = CAGE_SIZES[60], CAGE_SIZES[30]
    assert big.rod_half == pytest.approx(2 * small.rod_half)              # rods 60 mm apart, not 30
    cube = CageCube(cage=60)
    assert cube.ports()["in"].center.x == pytest.approx(-big.cube_half)
    assert CageRightAngleMirror(cage=60).ports()["out"].center.y == pytest.approx(big.cube_half)
    with pytest.raises(ValueError):
        CageCube(cage=45)
    scene = Scene()
    scene.add(CageCube(center=(0, 0), cage=60))
    scene.add(CageRods(center=(30, 0), cage=60, length=10, end_plates=False))
    scene.add(CageRightAngleMirror(center=(60, 0), cage=60))
    scene.add(CageWavePlate(center=(90, 0), cage=60, plate="quarter"))
    again = Scene.from_spec(scene.to_spec())
    assert [n.cage for n in again.walk() if hasattr(n, "cage")] == [60, 60, 60, 60]


def test_a_cage_wave_plate_is_a_half_or_quarter_wave_retarder():
    import math

    from optodraw import CageWavePlate

    half, quarter = CageWavePlate(), CageWavePlate(plate="quarter", fast_axis_angle=45)
    assert half.retardance == pytest.approx(math.pi) and quarter.retardance == pytest.approx(math.pi / 2)
    assert quarter.fast_axis_angle == 45 and quarter.physics_metadata()["retardance"] == pytest.approx(math.pi / 2)
    assert half.symbol_1d() == ("waveplate", {"kind": "half"})
    assert quarter.symbol_1d() == ("waveplate", {"kind": "quarter"})
    with pytest.raises(ValueError):
        CageWavePlate(plate="full")
