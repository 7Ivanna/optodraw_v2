"""A spectrometer is a Czerny-Turner with its lid off: one plan for 1D, 2D and 3D, after a real instrument."""

import io
import math

import pytest

from optodraw import Spectrometer
from optodraw.symbols import lookup

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


# 2D and 1D


# 3D


def test_each_optic_of_the_model_stands_where_the_plan_puts_it():
    part = Spectrometer(box_size=10.0)
    for name in ("fold", "collimator", "grating", "focuser", "array"):
        optic = solids(part, name)[0]
        assert optic["position"][0] == pytest.approx(PATH[name][0] * 10.0), name
        assert optic["position"][2] == pytest.approx(-PATH[name][1] * 10.0), name
        assert optic["position"][1] == pytest.approx(0.0), name


# a scene


