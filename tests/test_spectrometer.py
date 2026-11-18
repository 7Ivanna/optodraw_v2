"""A spectrometer is a Czerny-Turner with its lid off: one plan for 1D, 2D and 3D, after a real instrument."""

import io
import math

import pytest

from optodraw import Beam, Laser, Scene, Spectrometer, check_part_3d
from optodraw.components.optics.optomech import BEAM_HEIGHT
from optodraw.symbols import lookup
from optodraw.symbols.art import fit_art

CM = 72.0 / 2.54                                # SVG points to the centimetre of a TikZ pic
PATH = Spectrometer.LIGHT_PATH


def turn(a, b, c):
    """The angle in degrees between the way back to ``a`` and the way on to ``c``, at ``b``."""

    back = math.atan2(a[1] - b[1], a[0] - b[0])
    on = math.atan2(c[1] - b[1], c[0] - b[0])
    return abs(math.degrees((back - on + math.pi) % (2 * math.pi) - math.pi))


def inside(point, polygon):
    x, y = point
    crossings = 0
    for (x0, y0), (x1, y1) in zip(polygon, polygon[1:] + polygon[:1]):
        if (y0 > y) != (y1 > y) and x < x0 + (y - y0) * (x1 - x0) / (y1 - y0):
            crossings += 1
    return crossings % 2 == 1


def painted(look="2d"):
    """The symbol as red, green, blue, alpha, with a function that takes a point of the plan to a pixel."""

    numpy = pytest.importorskip("numpy")
    from optodraw.raster import svg_to_png
    image = pytest.importorskip("PIL.Image")
    symbol = lookup(Spectrometer())
    drawn = svg_to_png(symbol.svg2d if look == "2d" else symbol.svg, zoom=10)
    rgba = numpy.asarray(image.open(io.BytesIO(drawn)).convert("RGBA")).astype(float)
    port = symbol.ports["in"]
    per_point = rgba.shape[1] / symbol.width

    def pixel(x, y):
        return rgba[int((port.y - y * CM) * per_point), int((port.x + (x + 0.75) * CM) * per_point)]

    return rgba, pixel


def solids(part, role=None):
    found = []

    def walk(node):
        for child in node.get("children", []):
            walk(child)
        if "shape" in node and node["shape"] != "group" and (role is None or node.get("role") == role):
            found.append(node)

    walk(part.geometry_3d())
    return found


# the plan


def test_the_light_draws_a_w_high_at_the_mirrors_and_low_at_the_grating_and_the_array():
    assert PATH["collimator"][1] == PATH["focuser"][1] > 0.0
    assert PATH["grating"][1] < 0.0 and PATH["array"][1] < 0.0
    assert PATH["collimator"][0] < PATH["grating"][0] < PATH["focuser"][0]
    assert PATH["slit"][1] == PATH["fold"][1] == 0.0
    assert PATH["fold"][0] == PATH["collimator"][0] and PATH["focuser"][0] == PATH["array"][0]


def test_the_fold_turns_the_light_a_right_angle_and_the_mirrors_work_close_to_their_axis():
    assert turn(PATH["slit"], PATH["fold"], PATH["collimator"]) == pytest.approx(90.0)
    assert turn(PATH["fold"], PATH["collimator"], PATH["grating"]) < 40.0          # 20 degrees off axis at most
    assert turn(PATH["grating"], PATH["focuser"], PATH["array"]) < 40.0


def test_the_two_mirrors_stand_either_side_of_the_grating_at_one_distance():
    assert math.dist(PATH["collimator"], PATH["grating"]) == pytest.approx(math.dist(PATH["focuser"], PATH["grating"]))


def test_every_stop_of_the_light_lies_inside_the_body():
    for name, point in PATH.items():
        if name != "slit":
            assert inside(point, list(Spectrometer.OUTLINE)), name


def test_the_body_has_the_chamfered_corner_of_the_real_instrument_and_it_is_empty():
    outline = list(Spectrometer.OUTLINE)
    assert len(outline) == 5
    assert not inside((-0.68, -0.49), outline)
    assert inside((-0.68, 0.0), outline)


def test_the_port_stays_on_the_slit_at_the_left_of_the_part():
    part = Spectrometer(box_size=10.0)
    port = part.ports()["in"]
    assert (port.center.x, port.center.y) == (-7.5, 0.0)
    assert port.orientation_deg == 180.0 and port.kind == "free_space"
    assert PATH["slit"][1] == port.center.y
    assert list(part.ports()) == ["in"]


# 2D and 1D


@pytest.mark.parametrize("size", [10.0, 24.0])
def test_the_art_keeps_the_scale_of_the_plan_so_2d_and_3d_are_one_size(size):
    part = Spectrometer(box_size=size)
    art = fit_art(part)
    assert art.scale * CM == pytest.approx(size)
    symbol = lookup(part)
    x, y = art.local(symbol.ports["in"].x, symbol.ports["in"].y)
    assert (x, y) == pytest.approx((-0.75 * size, 0.0), abs=1e-6)
    for name in ("collimator", "focuser", "array"):                             # a point of the plan lands on itself
        px, py = PATH[name]
        assert art.local(symbol.ports["in"].x + (px + 0.75) * CM, symbol.ports["in"].y - py * CM) == pytest.approx((px * size, py * size), abs=1e-6)


def test_the_part_takes_its_bounds_from_the_body_and_the_camera():
    b = 10.0
    children = Spectrometer(box_size=b).geometry_2d()["children"]
    head = next(c for c in children if c["type"] == "rect" and c["cy"] < 0)
    assert head["cy"] - head["h"] / 2.0 == pytest.approx(-0.78 * b)
    assert head["cy"] + head["h"] / 2.0 == pytest.approx(-0.54 * b)
    assert [tuple(p) for p in children[0]["points"]] == [(x * b, y * b) for x, y in Spectrometer.OUTLINE]


def test_the_2d_art_is_a_dark_body_with_the_lid_off():
    _, pixel = painted()
    wall = pixel(0.72, 0.1)
    assert wall[3] > 200 and wall[:3].mean() < 110
    floor = pixel(-0.2, 0.4)
    assert floor[3] > 200 and floor[:3].mean() < 70


def test_the_2d_art_cuts_the_corner_of_the_body():
    _, pixel = painted()
    assert pixel(-0.66, -0.47)[3] < 30


def test_the_2d_art_has_bright_mirrors_where_the_light_turns():
    _, pixel = painted()
    for name in ("collimator", "focuser"):
        assert pixel(*PATH[name])[:3].mean() > 140, name


def test_the_2d_art_spreads_the_colours_in_order_between_the_grating_and_the_focusing_mirror():
    _, pixel = painted()
    u = 0.72
    x, y = (PATH["grating"][0] + 0.03 + u * (PATH["focuser"][0] - PATH["grating"][0] - 0.03),
            PATH["grating"][1] + u * (PATH["focuser"][1] - PATH["grating"][1]))
    seen = []
    for step in range(-16, 17):
        red, green, blue = pixel(x + step * 0.01, y)[:3]
        if max(red, green, blue) - min(red, green, blue) > 60:
            seen.append("red" if red > max(green, blue) else "blue" if blue > max(red, green) else "green")
    assert seen[0] == "blue" and seen[-1] == "red" and "green" in seen


def test_the_camera_hangs_from_the_exit_port_under_the_array():
    _, pixel = painted()
    assert pixel(PATH["array"][0], -0.66)[3] > 200
    assert pixel(0.0, -0.66)[3] < 30
    assert pixel(0.72, -0.66)[3] < 30


def test_the_1d_symbol_is_line_art_of_the_same_plan():
    numpy = pytest.importorskip("numpy")
    rgba, pixel = painted("1d")
    assert pixel(-0.2, 0.4)[:3].mean() > 240                                    # a white body, no floor
    assert pixel(-0.66, -0.47)[3] < 30                                          # the same corner cut
    assert pixel(PATH["array"][0], -0.66)[3] > 200                              # the same camera
    colours = rgba[..., :3].max(axis=-1) - rgba[..., :3].min(axis=-1)
    assert numpy.count_nonzero((colours > 80) & (rgba[..., 3] > 200)) > 200     # wavelengths keep their colours


def test_the_symbol_holds_no_text():
    symbol = lookup(Spectrometer())
    assert "<text" not in symbol.svg and "<text" not in symbol.svg2d
    assert symbol.exact


# 3D


def test_the_model_has_no_loose_solid():
    assert check_part_3d(Spectrometer()) == []


def test_the_model_stands_on_the_table_on_its_own_pillars():
    part = Spectrometer(box_size=10.0)
    assert part.base_mount == "none"
    pillars = solids(part, "pillar")
    assert len(pillars) == 4
    assert {(p["position"][0] > 0, p["position"][2] > 0) for p in pillars} == {(True, True), (True, False), (False, True), (False, False)}
    plate = solids(part, "plate")[0]
    bases = solids(part, "base")
    assert all(base["position"][1] - base["height"] / 2.0 == pytest.approx(-BEAM_HEIGHT) for base in bases)
    for pillar, base in zip(pillars, bases):
        assert pillar["position"][1] - pillar["height"] / 2.0 == pytest.approx(base["position"][1] + base["height"] / 2.0)
        assert pillar["position"][1] + pillar["height"] / 2.0 == pytest.approx(plate["position"][1])


def test_the_pillars_stand_under_the_body_not_under_the_cut_corner():
    part = Spectrometer(box_size=10.0)
    for pillar in solids(part, "pillar"):
        x, _, z = pillar["position"]
        assert inside((x / 10.0, -z / 10.0), list(Spectrometer.OUTLINE))


def test_the_walls_and_the_floor_follow_the_plan():
    part = Spectrometer(box_size=10.0)
    walls = solids(part, "wall")[0]
    assert [tuple(p) for p in walls["points"]] == [(x * 10.0, y * 10.0) for x, y in Spectrometer.OUTLINE]
    assert walls["holes"] and solids(part, "floor")[0]["points"] == walls["points"]


def test_the_body_has_no_lid_so_the_optics_show():
    part = Spectrometer(box_size=10.0)
    assert not solids(part, "lid")
    wall = solids(part, "wall")[0]
    top = wall["position"][1] + wall["height"]
    for solid in solids(part):
        if solid["position"][1] > top and solid.get("role") not in ("micrometer", "screw"):
            raise AssertionError(solid.get("role"))
    for name in ("collimator", "focuser", "grating"):
        assert top > 1.0                                    # the walls stand clear of the middle of each optic


def test_the_walls_stop_short_of_a_tall_box_so_a_camera_above_the_bench_sees_in():
    part = Spectrometer(box_size=10.0)
    wall = solids(part, "wall")[0]
    assert wall["position"][1] + wall["height"] <= 2.5


def test_the_camera_lies_on_the_same_side_of_the_part_as_in_2d():
    part = Spectrometer(box_size=10.0)
    head = solids(part, "camera")[0]
    assert head["position"][2] > 5.0                        # the 2D head hangs below the page's y = -5: 3D +z
    assert head["position"][0] == pytest.approx(PATH["array"][0] * 10.0)


def test_each_optic_of_the_model_stands_where_the_plan_puts_it():
    part = Spectrometer(box_size=10.0)
    for name in ("fold", "collimator", "grating", "focuser", "array"):
        optic = solids(part, name)[0]
        assert optic["position"][0] == pytest.approx(PATH[name][0] * 10.0), name
        assert optic["position"][2] == pytest.approx(-PATH[name][1] * 10.0), name
        assert optic["position"][1] == pytest.approx(0.0), name


def test_the_colours_of_the_model_run_at_the_height_of_the_beam_from_the_grating_to_the_array():
    part = Spectrometer(box_size=10.0)
    fans = solids(part, "spectrum")
    assert len(fans) == 10                                  # five colours, two legs each
    assert len({fan["material"]["color"] for fan in fans}) == 5
    for fan in fans:
        assert abs(fan["position"][1]) < 0.1


def test_the_turret_and_the_slit_micrometer_of_the_real_instrument_are_there():
    part = Spectrometer()
    assert solids(part, "turret") and solids(part, "micrometer")


# a scene


def test_a_beam_ends_on_the_slit():
    scene = Scene(title="s", width=80, height=40, platform="free_space")
    laser = scene.add(Laser(center=(-30, 0), wavelength=633))
    part = scene.add(Spectrometer(center=(10, 0)))
    beam = scene.add(Beam.through(laser, part, wavelength=633))
    assert beam.resolve_points()[-1][0] == pytest.approx(2.5)


def test_a_saved_scene_keeps_the_stand():
    scene = Scene(title="s", width=80, height=40, platform="free_space")
    scene.add(Spectrometer(center=(0, 0), angle=90, label="S"))
    again = Scene.from_spec(scene.to_spec())
    part = next(p for p in again.walk() if isinstance(p, Spectrometer))
    assert part.base_mount == "none"


def test_a_post_can_still_be_asked_for_and_then_the_pillars_go():
    part = Spectrometer(base_mount="post")
    assert part.base_mount == "post"
    assert solids(part, "pillar") == []
