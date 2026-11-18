"""One sample: a chip whose face looks toward its ``in`` port. ``angle`` turns it to the light, in every view."""

import math

import pytest

from optodraw import Beam, Cryostat, Laser, Lens, Objective, Sample, Scene, check_part_3d
from optodraw.app.validation import run_checks
from optodraw.core.transform import Vec3
from optodraw.schema import component_from_spec, component_to_spec, scene_from_spec, scene_to_spec
from optodraw.symbols import lookup
from optodraw.symbols.art import art_2d, art_bounds


def chip(sample):
    return sample.geometry_3d()["children"][1]


def in_can(part):
    return {solid.get("role"): solid for solid in part.geometry_3d()["children"]}


def facing(sample):
    """The way the face of the chip looks, in the plan of the bench."""

    turn = math.radians(sample.world_port("in").orientation_deg)
    return round(math.cos(turn), 9), round(math.sin(turn), 9)


@pytest.mark.parametrize("in_cryostat", [False, True])
@pytest.mark.parametrize(("angle", "looks"), [(0, (-1, 0)), (180, (1, 0)), (-90, (0, 1)), (90, (0, -1))])
def test_the_angle_turns_the_face_of_the_chip(angle, looks, in_cryostat):
    assert facing(Sample(angle=angle, in_cryostat=in_cryostat)) == pytest.approx(looks)


def test_the_chip_stands_face_on_to_the_in_port_in_3d():
    sample = Sample(aperture=20)
    solid = chip(sample)
    assert solid["width"] < solid["height"] == solid["depth"]            # thin along the beam, the face across it
    assert sample.ports()["in"].center.x == pytest.approx(solid["position"][0] - solid["width"] / 2)


def test_the_chip_in_a_cryostat_faces_the_window_and_not_the_wall_beside_it():
    """The beam came through the window and met the edge of the chip: the chip looked along z, the beam along x."""

    solid = in_can(Sample(aperture=20, in_cryostat=True))["sample"]
    assert solid["width"] < solid["depth"] and solid["width"] < solid["height"]


@pytest.mark.parametrize("part", [Sample(aperture=20, in_cryostat=True), Cryostat()], ids=["sample", "cryostat"])
def test_a_cold_block_holds_the_chip_from_behind(part):
    solids = in_can(part)
    chip_solid, block = solids["sample"], solids["stage"]
    assert chip_solid["position"][0] + chip_solid["width"] / 2 == pytest.approx(block["position"][0] - block["width"] / 2)
    finger = solids["finger"]
    assert finger["position"][0] == pytest.approx(block["position"][0])
    assert finger["position"][1] - finger["height"] / 2 == pytest.approx(block["position"][1] + block["height"] / 2)
    assert check_part_3d(part) == []


def test_a_beam_ends_on_the_chip_in_a_cryostat():
    sample = Sample(aperture=20, in_cryostat=True)
    solid = in_can(sample)["sample"]
    assert sample.ports()["in"].center.x == pytest.approx(solid["position"][0] - solid["width"] / 2)


@pytest.mark.parametrize("aperture", [10, 20, 30])
def test_the_can_in_3d_is_the_can_of_the_2d_drawing(aperture):
    sample = Sample(aperture=aperture, in_cryostat=True)
    can = next(solid for solid in sample.geometry_3d()["children"] if solid["shape"] == "cylinder")
    x0, y0, x1, y1 = art_bounds(sample)
    assert 2.0 * can["radius"] == pytest.approx(y1 - y0, rel=0.25)


def test_a_window_sits_on_its_port():
    cryostat = Cryostat(radius=14.0)
    glass = [solid for solid in cryostat.geometry_3d()["children"] if solid.get("role") == "window"]
    assert max(abs(solid["position"][0]) for solid in glass) == pytest.approx(cryostat.ports()["out"].center.x, rel=0.02)


def test_a_default_objective_stays_outside_the_window_of_a_default_sample():
    """The objective focused on the chip with its nose inside the can: the window lay twice as far out as the nose."""

    objective = Objective(center=(0, 0))
    sample = Sample(center=objective.focus_point(), in_cryostat=True)
    nose = objective.world_port("out").center
    assert math.dist((nose.x, nose.y), (sample.world_position.x, sample.world_position.y)) > sample.window_reach


def test_an_objective_inside_the_window_is_told_to_stand_back():
    scene = Scene(title="Inside", width=120, height=80, platform="free_space")
    objective = scene.add(Objective(center=(0, 0), working_distance=4.0, label="Objective"))
    scene.add(Sample(center=objective.focus_point(), in_cryostat=True, label="Chip"))
    assert [issue for issue in run_checks(scene) if "inside the window" in issue["message"]]


def test_an_objective_outside_the_window_draws_no_warning():
    scene = Scene(title="Outside", width=120, height=80, platform="free_space")
    objective = scene.add(Objective(center=(0, 0), label="Objective"))
    scene.add(Sample(center=objective.focus_point(), in_cryostat=True, label="Chip"))
    assert not [issue for issue in run_checks(scene) if "inside the window" in issue["message"]]


def test_there_is_one_drawing_and_the_scene_turns_it():
    upright, turned = Sample(), Sample(angle=-90)
    assert lookup(upright).params == lookup(turned).params == {}
    assert art_2d(upright)["matrix"] == art_2d(turned)["matrix"]
    assert lookup(Sample(in_cryostat=True)).params == {"kind": "cryostat"}


@pytest.mark.parametrize("aperture", [10, 20, 30])
@pytest.mark.parametrize("in_cryostat", [False, True])
def test_the_art_matches_every_port(aperture, in_cryostat):
    sample = Sample(aperture=aperture, in_cryostat=in_cryostat)
    symbol = lookup(sample)
    assert symbol.source == "prebuilt" and symbol.exact
    assert set(symbol.ports) == set(sample.ports())
    art = art_2d(sample)
    assert art is not None and art["residual"] < 0.001
    a, b, c, d, e, f = art["matrix"]
    for name, port in sample.ports().items():
        mark = symbol.ports[name]
        assert (a * mark.x + c * mark.y + e, -(b * mark.x + d * mark.y + f)) == pytest.approx(
            (port.center.x, port.center.y), abs=0.003)


def test_the_side_ports_are_the_edges_of_the_chip():
    sample = Sample(aperture=20)
    solid, ports = chip(sample), sample.ports()
    for name, sign in (("side_in", -1), ("side_out", 1)):
        assert ports[name].center.y == pytest.approx(sign * solid["depth"] / 2)
        assert ports[name].center.x == pytest.approx(solid["position"][0])
    assert "side_in" not in Sample(in_cryostat=True).ports()            # in the can, only the window reaches the chip


def test_a_chip_turned_up_the_page_keeps_its_left_edge_on_the_left():
    sample = Sample(center=(0, -26), angle=-90)
    assert sample.world_port("side_in").center.x < sample.world_port("side_out").center.x


def test_the_holder_stands_behind_the_chip():
    plate, solid, *_, stem = Sample().geometry_3d()["children"]
    assert solid["width"] < solid["height"] == solid["depth"] < plate["height"]
    assert solid["position"][0] + solid["width"] / 2 == pytest.approx(plate["position"][0] - plate["width"] / 2)
    assert stem["position"][1] + stem["height"] / 2 == pytest.approx(-plate["height"] / 2)


@pytest.mark.parametrize("in_cryostat", [False, True])
def test_a_turned_sample_survives_a_saved_scene(in_cryostat):
    sample = Sample(center=(3, 7), angle=-90, in_cryostat=in_cryostat)
    restored = component_from_spec(component_to_spec(sample))
    assert restored.world_ports() == sample.world_ports()
    assert restored.in_cryostat == in_cryostat


@pytest.mark.parametrize("in_cryostat", [False, True])
def test_a_flat_sample_of_a_saved_scene_comes_back_with_its_face_up_the_page(in_cryostat):
    saved = {"type": "Sample", "center": [0, 0], "angle": 0, "aperture": 20, "in_cryostat": in_cryostat,
             "mount_orientation": "flat"}
    assert facing(component_from_spec(saved)) == pytest.approx((0, 1))


def test_an_upright_sample_of_a_saved_scene_stays_as_it_was():
    saved = {"type": "Sample", "aperture": 20, "mount_orientation": "upright"}
    assert facing(component_from_spec(saved)) == pytest.approx((-1, 0))


def test_a_side_pump_survives_a_saved_scene_on_its_edge():
    scene = Scene(platform="free_space")
    sample = scene.add(Sample(center=(0, -26), angle=-90))
    laser = scene.add(Laser(center=(-38, sample.world_port("side_in").center.y)))
    beam = scene.add(Beam((laser, "out"), (sample, "side_in"), wavelength=532))
    restored = scene_from_spec(scene_to_spec(scene))
    restored_beam = next(part for part in restored.walk() if isinstance(part, Beam))
    assert beam.resolve_points()[-1][0] == pytest.approx(-5)
    assert restored_beam.resolve_points() == beam.resolve_points()


@pytest.mark.parametrize("pair_type", [tuple, list])
@pytest.mark.parametrize("named_first", [False, True])
def test_through_uses_the_named_port_position_not_the_part_center(pair_type, named_first):
    lens = Lens(center=(0, 40))
    sample = Sample(center=(20, 0), aperture=200, angle=-90)
    named = pair_type((sample, "side_in"))                 # the sample centre lies right of the lens; this edge lies left
    stops = (named, lens) if named_first else (lens, named)
    beam = Beam.through(*stops)
    lens_anchor = beam.anchors[-1] if named_first else beam.anchors[0]
    assert lens_anchor == (lens, "in")
    point = beam.resolve_points()[0] if named_first else beam.resolve_points()[-1]
    assert point[:2] == pytest.approx((-30, 2))


@pytest.mark.parametrize("in_cryostat", [False, True])
def test_an_objective_above_a_sample_turned_to_it_draws_no_warning(in_cryostat):
    scene = Scene(title="Above", width=80, height=90, platform="free_space")
    objective = scene.add(Objective(center=(0, 30), angle=-90, label="Objective"))
    sample = scene.add(Sample(center=objective.focus_point(), angle=-90, in_cryostat=in_cryostat, label="Sample"))
    scene.add(Beam((objective, "out"), (sample, "in"), wavelength=633))
    assert not [issue for issue in run_checks(scene) if "Sample" in issue["message"] and issue["kind"] == "beam"]


def test_a_sample_that_looks_past_its_beam_is_told_to_turn():
    scene = Scene(title="Past", width=80, height=90, platform="free_space")
    objective = scene.add(Objective(center=(0, 30), angle=-90, label="Objective"))
    sample = scene.add(Sample(center=objective.focus_point(), label="Sample"))
    scene.add(Beam((objective, "out"), (sample, "in"), wavelength=633))
    assert [issue for issue in run_checks(scene) if "turn it to face the beam" in issue["message"]]


@pytest.mark.parametrize("aperture", [10, 20, 30])
def test_a_beam_through_a_sample_meets_the_face_of_the_chip_and_the_back_of_the_holder(aperture):
    from optodraw.core.beam import beam_point

    sample = Sample(aperture=aperture, center=(5, -3), angle=90)
    plate, solid, *_ = sample.geometry_3d()["children"]
    front, back = sample.world_transform.apply_to_point(Vec3(solid["position"][0] - solid["width"] / 2, 0, 0)), \
        sample.world_transform.apply_to_point(Vec3(plate["position"][0] + plate["width"] / 2, 0, 0))
    assert beam_point(sample, "in").as_tuple() == pytest.approx(front.as_tuple())
    assert beam_point(sample, "out").as_tuple() == pytest.approx(back.as_tuple())
