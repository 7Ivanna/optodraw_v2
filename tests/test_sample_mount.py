"""One sample: a chip whose face looks toward its ``in`` port. ``angle`` turns it to the light, in every view."""

import math

import pytest

from optodraw import Objective, Sample, Scene
from optodraw.app.validation import run_checks
from optodraw.schema import component_from_spec


def chip(sample):
    return sample.geometry_3d()["children"][1]


def in_can(part):
    return {solid.get("role"): solid for solid in part.geometry_3d()["children"]}


def facing(sample):
    """The way the face of the chip looks, in the plan of the bench."""

    turn = math.radians(sample.world_port("in").orientation_deg)
    return round(math.cos(turn), 9), round(math.sin(turn), 9)


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


@pytest.mark.parametrize("in_cryostat", [False, True])
def test_a_flat_sample_of_a_saved_scene_comes_back_with_its_face_up_the_page(in_cryostat):
    saved = {"type": "Sample", "center": [0, 0], "angle": 0, "aperture": 20, "in_cryostat": in_cryostat,
             "mount_orientation": "flat"}
    assert facing(component_from_spec(saved)) == pytest.approx((0, 1))


