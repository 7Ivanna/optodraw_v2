"""A telescope is two lenses at their true spacing, in every view, with the light open between them."""

import pytest

from optodraw import Beam, Laser, Lens, Photodiode, Scene, Telescope, check_part_3d
from optodraw.layout import estimate_component_bounds
from optodraw.symbols.art import art_2d, art_piece


def with_role(part, role):
    return [solid for solid in part.geometry_3d()["children"] if solid.get("role") == role]


def along_x(solid):
    """The start and the end of a solid along the beam."""

    x = solid["position"][0]
    if solid["shape"] == "lathe_profile":
        heights = [point[1] for point in solid["points"]]
        return x + min(heights), x + max(heights)
    half = solid.get("height", solid.get("width", 0.0)) / 2.0 if solid.get("rotation") else solid.get("width", 0.0) / 2.0
    return x - half, x + half


def lens_places(part):
    return sorted(child["pic"]["origin"][0] for child in part.geometry_2d()["children"] if child["type"] == "art")


@pytest.mark.parametrize("spacing", [None, 30.0, 90.0])
def test_the_lenses_sit_at_their_true_spacing_in_3d(spacing):
    part = Telescope(spacing=spacing)
    assert sorted(solid["position"][0] for solid in with_role(part, "lens")) == pytest.approx([-part.spacing / 2.0, part.spacing / 2.0])


def test_each_lens_keeps_its_own_aperture_in_3d():
    part = Telescope(input_aperture=6.0, output_aperture=12.0)
    assert sorted(solid["radius"] for solid in with_role(part, "lens")) == pytest.approx([3.0, 6.0])


def test_no_solid_closes_the_space_between_the_lenses():
    """The tube hid both lenses and the light: a closed refractor, where the 2D drew two lenses."""

    part = Telescope()
    for solid in part.geometry_3d()["children"]:
        if solid.get("role") != "rod":
            start, end = along_x(solid)
            assert end - start < 0.2 * part.spacing, solid.get("role")


def test_a_short_barrel_holds_each_lens():
    part = Telescope()
    barrels = with_role(part, "barrel")
    assert len(barrels) == 2
    for barrel, lens in zip(sorted(barrels, key=along_x), sorted(with_role(part, "lens"), key=along_x)):
        start, end = along_x(barrel)
        assert start < lens["position"][0] < end


def test_four_thin_rods_join_the_barrels_outside_the_light():
    part = Telescope()
    rods = with_role(part, "rod")
    assert len(rods) == 4 and all(rod["height"] == pytest.approx(part.spacing) for rod in rods)
    assert sorted({(y > 0, z > 0) for _, y, z in (rod["position"] for rod in rods)}) == [(False, False), (False, True), (True, False), (True, True)]
    clear = part.output_aperture / 2.0
    for rod in rods:
        assert (rod["position"][1] ** 2 + rod["position"][2] ** 2) ** 0.5 - rod["radius"] > clear


@pytest.mark.parametrize("kwargs", [{}, {"input_aperture": 12.0, "output_aperture": 6.0}, {"input_aperture": 10.0, "output_aperture": 10.0}, {"telescope_type": "galilean"}])
def test_no_solid_floats_and_the_post_meets_a_flat_face(kwargs):
    assert check_part_3d(Telescope(**kwargs)) == []


@pytest.mark.parametrize("kwargs", [{}, {"telescope_type": "galilean"}, {"input_aperture": 3.0, "spacing": 20.0}])
def test_the_2d_lenses_sit_where_the_3d_lenses_sit(kwargs):
    part = Telescope(**kwargs)
    assert lens_places(part) == pytest.approx(sorted(solid["position"][0] for solid in with_role(part, "lens")), abs=0.01)


def test_each_lens_in_2d_is_as_tall_as_its_aperture():
    part = Telescope(input_aperture=6.0, output_aperture=12.0)
    points = 0.72 * 72.27 / 2.54                                            # the lens of the symbol is 0.72 cm tall
    tall = [child["pic"]["scale"] * points for child in part.geometry_2d()["children"] if child["type"] == "art"]
    assert tall == pytest.approx([6.0, 12.0], rel=0.1)


def test_the_2d_drawing_reaches_both_ports_so_the_beam_shows_no_gap():
    """The drawing was a small sketch at the in port, and the light vanished for most of the part."""

    part = Telescope()
    x0, _, x1, _ = estimate_component_bounds(part)
    assert (x0, x1) == pytest.approx((part.ports()["in"].center.x, part.ports()["out"].center.x), abs=0.5)


def test_the_telescope_keeps_its_1d_symbol():
    from optodraw.symbols import lookup

    assert lookup(Telescope()).source == "prebuilt" and art_2d(Telescope()) is None


def rays(part):
    return [child for child in part.geometry_2d()["children"] if child["type"] == "line" and child.get("role") == "ray"]


def test_the_rays_of_a_keplerian_telescope_cross_at_the_focus():
    part = Telescope(focal_length_1=20.0, focal_length_2=40.0)
    first, second = rays(part)
    assert first["y1"] * first["y2"] < 0 and abs(first["y2"]) == pytest.approx(2.0 * abs(first["y1"]))
    cross = first["x1"] + (first["x2"] - first["x1"]) * abs(first["y1"]) / (abs(first["y1"]) + abs(first["y2"]))
    assert cross == pytest.approx(-part.spacing / 2.0 + 20.0)
    assert second["y1"] == pytest.approx(-first["y1"])


def test_the_rays_of_a_galilean_telescope_never_cross():
    first, _ = rays(Telescope(telescope_type="galilean"))
    assert first["y1"] * first["y2"] > 0


def test_a_galilean_telescope_has_a_concave_first_lens_in_2d():
    lens = next(child for child in Telescope(telescope_type="galilean").geometry_2d()["children"] if child["type"] == "art")
    assert lens["params"] == {"kind": "concave"}


def test_the_rays_stay_inside_the_lenses():
    part = Telescope(focal_length_1=10.0, focal_length_2=200.0)
    for ray in rays(part):
        assert abs(ray["y2"]) <= part.output_aperture / 2.0


def test_the_rays_stay_clear_of_the_rods():
    part = Telescope()
    assert all(abs(ray["y2"]) < part._rod_offset - 0.2 for ray in rays(part))


def test_a_bench_draws_it_in_2d_and_in_tikz():
    scene = Scene(title="Telescope", width=170, height=60, platform="free_space")
    laser = scene.add(Laser(center=(-62, 0), wavelength=633, label="Laser"))
    part = scene.add(Telescope(center=(0, 0), label="Telescope"))
    detector = scene.add(Photodiode(center=(62, 0), label="Detector"))
    scene.add(Beam.through(laser, part, detector, wavelength=633))
    assert scene.render_svg().as_svg().count('data-art="lens"') == 2
    assert scene.render_tikz().count("{od lens=") == 2


def test_a_piece_of_art_moves_in_the_drawing_and_in_the_tikz_pic_alike():
    plain, moved = art_2d(Lens()), art_piece(Lens(), 5.0)
    assert moved["matrix"][4] == pytest.approx(plain["matrix"][4] + 5.0)
    assert moved["pic"]["origin"][0] == pytest.approx(plain["pic"]["origin"][0] + 5.0)
    assert moved["matrix"][5] == plain["matrix"][5]


def test_the_clamp_holds_the_rods():
    part = Telescope()
    clamp = next(solid for solid in part.geometry_3d()["children"] if solid["shape"] == "lathe_profile" and solid["position"][0] == 0.0)
    wall = [point[0] for point in clamp["points"]]
    rod = with_role(part, "rod")[0]
    assert min(wall) < (rod["position"][1] ** 2 + rod["position"][2] ** 2) ** 0.5 < max(wall)
