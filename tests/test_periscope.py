"""The periscope: two 45 deg mirrors on a vertical rail.

A periscope is how a bench moves its beam between heights -- up from the table
to a microscope's input port, down onto a sample -- and the optic it carries
(usually an objective) rides on its top plate. The mirrors sit on different
axes: the lower one turns the horizontal beam vertical, the upper one turns it
back into the plane, along whichever direction the periscope is set to exit.
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from optodraw import Periscope, Scene  # noqa: E402


class TestPeriscopeGeometry:
    def test_it_moves_the_beam_between_two_heights(self):
        scope = Periscope(rise=60.0)
        assert scope.ports()["in"].center.z == pytest.approx(0.0)
        assert scope.ports()["out"].center.z == pytest.approx(60.0)

    def test_a_negative_rise_takes_a_raised_beam_back_down(self):
        """The assembly stands on the table, so the LOWER end is the one at the
        bench beam plane: a falling periscope enters high and exits at the plane.
        Hanging the exit below it would bury the mirror under the table."""

        scope = Periscope(rise=-40.0)
        assert scope.ports()["in"].center.z == pytest.approx(40.0)
        assert scope.ports()["out"].center.z == pytest.approx(0.0)

    def test_by_default_the_beam_leaves_the_way_it_arrived(self):
        scope = Periscope()
        assert scope.ports()["out"].orientation_deg == pytest.approx(0.0)
        assert scope.ports()["in"].orientation_deg == pytest.approx(180.0)

    def test_it_can_turn_the_beam_in_plan(self):
        scope = Periscope(output_angle_deg=90.0)
        assert scope.ports()["out"].orientation_deg == pytest.approx(90.0)

    def test_the_top_plate_carries_a_mount_for_an_objective(self):
        for rise in (60.0, -60.0):
            mount = Periscope(rise=rise).ports()["mount"]
            assert mount.kind == "free_space"
            assert mount.center.z == pytest.approx(60.0)  # always the raised end

    def test_both_mirrors_are_drawn_at_their_own_heights(self):
        scope = Periscope(rise=60.0)
        mirrors = [
            child for child in scope.geometry_3d()["children"]
            if child.get("role") == "mirror"
        ]
        assert len(mirrors) == 2
        heights = sorted(round(float(m["position"][1]), 3) for m in mirrors)
        assert heights[1] - heights[0] == pytest.approx(60.0)


class TestPeriscopeInSetups:
    def test_it_places_and_renders_in_a_scene(self):
        scene = Scene(width=200, height=120)
        scene.add(Periscope(center=(0, 0), rise=50.0, label="Periscope"))
        svg = scene.render_svg().as_svg()
        assert "Periscope" in svg

    def test_an_objective_sits_on_the_mount_in_plan_and_at_height(self):
        """Mounting is not an in-plane hop: the optic sits ON the top plate, so it
        shares the periscope's plan position and rides at the raised height."""

        from optodraw.components.optics import Objective

        scene = Scene(width=200, height=120)
        scope = scene.add(Periscope(center=(20, -10), rise=50.0))
        mount = scope.world_port("mount")
        objective = scene.add(Objective(center=(mount.center.x, mount.center.y), angle=90, label="100x"))

        assert objective.world_position.x == pytest.approx(20.0)
        assert objective.world_position.y == pytest.approx(-10.0)
        assert mount.center.z == pytest.approx(50.0)  # the height it is carried at
        assert "100x" in scene.render_svg().as_svg()


class TestPeriscopeRayTracing:
    """In plan view a periscope either passes the beam along or folds it. The
    height change is real hardware, but it is out of the drawing plane -- the
    2D trace shows the fold, the 3D view shows the climb."""

    def _trace(self, **kwargs):
        from optodraw.components.devices import Laser
        from optodraw.core.raytrace import trace_branched

        scene = Scene(width=240, height=140)
        laser = scene.add(Laser(center=(-60, 0)))
        scene.add(Periscope(center=(0, 0), aperture=16.0, **kwargs))
        (result,) = trace_branched(scene, (laser, "out"), mode="physical", exit_length=60)
        return result

    def _out_angle(self, **kwargs):
        return self._trace(**kwargs).direction_deg

    def test_a_straight_through_periscope_leaves_the_beam_alone(self):
        assert self._out_angle(rise=50.0) == pytest.approx(0.0, abs=1e-6)

    def test_a_turning_periscope_folds_the_beam_in_plan(self):
        assert self._out_angle(rise=50.0, output_angle_deg=90.0) == pytest.approx(90.0, abs=0.5)

    def test_the_beam_leaves_at_the_height_the_periscope_lifts_it_to(self):
        # The whole point of the part: the ray that leaves is 50 units higher
        # than the one that arrived, and it climbs in one vertical step.
        result = self._trace(rise=50.0)
        assert result.points[0].z == pytest.approx(0.0)
        assert result.points[-1].z == pytest.approx(50.0)
        climb = [(a, b) for a, b in zip(result.points, result.points[1:]) if a.z != b.z]
        assert len(climb) == 1
        start, end = climb[0]
        assert (start.x, start.y) == (end.x, end.y)  # straight up, not a ramp

    def test_a_falling_periscope_brings_the_beam_back_down(self):
        assert self._trace(rise=-50.0).points[-1].z == pytest.approx(-50.0)

    def test_a_turning_periscope_climbs_as_well_as_folds(self):
        result = self._trace(rise=50.0, output_angle_deg=90.0)
        assert result.points[-1].z == pytest.approx(50.0)


class TestPeriscopeMirrorsFaceTheBeam:
    """A mirror face has to look AT the light. The normal bisects where the beam
    comes from and where it leaves: the lower mirror faces back along the input
    and upward, the upper one faces down and out along the exit."""

    @staticmethod
    def _unit(vector):
        import math

        length = math.sqrt(sum(v * v for v in vector))
        return tuple(v / length for v in vector)

    def test_the_entry_mirror_faces_the_incoming_beam_and_up(self):
        lower, _ = Periscope().mirror_normals()
        assert lower == pytest.approx(self._unit((-1.0, 1.0, 0.0)), abs=1e-6)

    def test_the_upper_mirror_faces_down_and_out(self):
        _, upper = Periscope().mirror_normals()
        assert upper == pytest.approx(self._unit((1.0, -1.0, 0.0)), abs=1e-6)

    def test_turning_the_exit_swings_the_upper_mirror(self):
        # 2D +y is 3D -z, so a 90 deg plan turn sends the beam along -z
        _, upper = Periscope(output_angle_deg=90.0).mirror_normals()
        assert upper == pytest.approx(self._unit((0.0, -1.0, -1.0)), abs=1e-6)

    def test_a_falling_periscope_folds_the_beam_down_first(self):
        """With the exit mirror BELOW, the entry mirror has to turn the beam down
        toward it. Using the rising angles points both mirrors at nothing."""

        entry, exit_ = Periscope(rise=-30.0).mirror_normals()
        assert entry == pytest.approx(self._unit((-1.0, -1.0, 0.0)), abs=1e-6)
        assert exit_ == pytest.approx(self._unit((1.0, 1.0, 0.0)), abs=1e-6)


def test_a_periscope_stands_on_the_table_not_on_a_post():
    """It carries its own stage and rails, so the renderer must not lift it to the
    beam plane on a pedestal the way it does a bare optic."""

    from optodraw.renderers.threejs_renderer import ThreeJsRenderer

    scene = Scene(width=200, height=120)
    scope = scene.add(Periscope(center=(0, 0)))
    assert not ThreeJsRenderer(scene)._is_beam_plane_optic(scope)


def test_the_plan_view_shows_both_mounts():
    """A true top view hides the lower mount under the upper one, so a placed
    periscope read as a single box -- it looked like only one mount arrived."""

    scope = Periscope()
    plates = [c for c in scope.geometry_2d()["children"] if c.get("type") == "rect"]
    assert len(plates) == 2  # two mounts, drawn offset so both are visible
    assert plates[0]["cx"] != plates[1]["cx"]
    assert plates[0]["opacity"] < plates[1]["opacity"]  # the lower one reads as underneath


def test_the_post_stands_clear_of_the_beam():
    """The input and output both run through the mirror centres, so a post behind
    the mirror sits squarely in the incoming beam. It belongs beside it."""

    scope = Periscope()
    posts = [c for c in scope.geometry_3d()["children"] if c.get("role") == "post"]
    assert posts, "there should be a post"
    for post in posts:
        x, _, z = post["position"]
        assert abs(z) > scope.aperture * 0.6, "the post must stand off the beam axis"
        assert abs(x) < 1e-9  # ... and not along the beam either


FOLDS = ({}, {"rise": -30.0}, {"output_angle_deg": 90.0}, {"rise": -30.0, "output_angle_deg": 270.0})


def _euler_xyz(v, rotation):
    """three.js Euler order XYZ: v' = Rx(a) Ry(b) Rz(c) v."""

    import math

    a, b, c = rotation
    x, y, z = v
    x, y = x * math.cos(c) - y * math.sin(c), x * math.sin(c) + y * math.cos(c)
    x, z = x * math.cos(b) + z * math.sin(b), -x * math.sin(b) + z * math.cos(b)
    y, z = y * math.cos(a) - z * math.sin(a), y * math.sin(a) + z * math.cos(a)
    return (x, y, z)


def _block_vertices(block):
    """The world corners of an extruded_polygon: shape (s1, s2) at height e lands at (s1, e, -s2), then turned."""

    corners = []
    for e in (0.0, block["height"]):
        for s1, s2 in block["points"]:
            x, y, z = _euler_xyz((s1, e, -s2), block["rotation"])
            corners.append((x + block["position"][0], y + block["position"][1], z + block["position"][2]))
    return corners


def _mirror_points(scope):
    """(fold point, face normal) per mirror, in the part's own 3D frame."""

    entry_z, exit_z = scope._port_heights
    normals = scope.mirror_normals()
    return {"entry": ((0.0, scope.beam_height + entry_z, 0.0), normals[0]),
            "exit": ((0.0, scope.beam_height + exit_z, 0.0), normals[1])}


@pytest.mark.parametrize("kwargs", FOLDS)
def test_each_mount_is_a_right_angle_block_wholly_behind_its_mirror(kwargs):
    """A right-angle mount holds the mirror on its 45 deg diagonal (on a kinematic plate); the body is the half
    behind it, so the light meets only the mirror (the old plates read as reflecting toward the post)."""

    scope = Periscope(**kwargs)
    children = scope.geometry_3d()["children"]
    for which, (point, normal) in _mirror_points(scope).items():
        block = next(c for c in children if c.get("role") == "mount" and c.get("mirror") == which
                     and c.get("shape") == "extruded_polygon")
        depths = [sum((v[i] - point[i]) * normal[i] for i in range(3)) for v in _block_vertices(block)]
        assert -scope.aperture * 0.25 <= max(depths) <= 1e-6, (kwargs, which)      # the diagonal face, close behind the mirror
        assert min(depths) < -scope.aperture * 0.4, (kwargs, which)                # and the body is behind it
        disc = next(c for c in children if c.get("role") == "mirror" and c.get("mirror") == which)
        axis = _euler_xyz((0.0, 1.0, 0.0), disc["rotation"])
        assert abs(sum(axis[i] * normal[i] for i in range(3))) == pytest.approx(1.0, abs=1e-9)


def _beam_path(scope):
    """The beam inside the part: input port, the two mirrors, output port (3D, y up)."""

    ports = scope.ports()
    bh = scope.beam_height

    def at(port):
        c = ports[port].center
        return (c.x, bh + c.z, -c.y)

    (p1, _), (p2, _) = _mirror_points(scope).values()
    return [at("in"), p1, p2, at("out")]


def _inside_block(point, block, margin):
    """True when ``point`` lies inside the block, more than ``margin`` from every face."""

    import numpy as np

    corners = np.array(_block_vertices(block))
    n = len(block["points"])
    bottom, top = corners[:n], corners[n:]
    axis = top[0] - bottom[0]
    height = np.linalg.norm(axis)
    axis = axis / height
    p = np.asarray(point) - bottom[0]
    along = p @ axis
    if not (margin < along < height - margin):
        return False
    centre = bottom.mean(axis=0)
    for i in range(n):
        edge_a, edge_b = bottom[i], bottom[(i + 1) % n]
        outward = np.cross(edge_b - edge_a, axis)
        if (centre - edge_a) @ outward > 0:
            outward = -outward
        if (np.asarray(point) - along * axis - edge_a) @ outward / np.linalg.norm(outward) > -margin:
            return False
    return True


@pytest.mark.parametrize("kwargs", FOLDS)
def test_the_beam_meets_only_the_mirrors_on_its_way(kwargs):
    import math

    scope = Periscope(**kwargs)
    children = scope.geometry_3d()["children"]
    blocks = [c for c in children if c.get("shape") == "extruded_polygon"]
    post = next(c for c in children if c.get("role") == "post")
    path = _beam_path(scope)
    for start, end in zip(path, path[1:]):
        for k in range(1, 40):
            t = k / 40
            point = tuple(start[i] + (end[i] - start[i]) * t for i in range(3))
            assert not any(_inside_block(point, b, scope.aperture * 0.02) for b in blocks), (kwargs, point)
            radial = math.hypot(point[0] - post["position"][0], point[2] - post["position"][2])
            assert radial > post["radius"] + scope.aperture * 0.1, (kwargs, point)


@pytest.mark.parametrize("kwargs", FOLDS)
def test_each_mount_is_clamped_to_the_post(kwargs):
    import math

    scope = Periscope(**kwargs)
    children = scope.geometry_3d()["children"]
    post = next(c for c in children if c.get("role") == "post")
    for which in ("entry", "exit"):
        clamp = next(c for c in children if c.get("role") == "clamp" and c.get("mirror") == which)
        half = clamp["width"] / 2.0
        yaw = clamp["rotation"][1]
        direction = (math.cos(yaw), 0.0, -math.sin(yaw))
        ends = [tuple(clamp["position"][i] + sign * half * direction[i] for i in range(3)) for sign in (1, -1)]
        root = min(ends, key=lambda e: math.hypot(e[0] - post["position"][0], e[2] - post["position"][2]))
        assert math.hypot(root[0] - post["position"][0], root[2] - post["position"][2]) < 1e-6, (kwargs, which)
        low, high = post["position"][1] - post["height"] / 2, post["position"][1] + post["height"] / 2
        assert low < clamp["position"][1] < high, (kwargs, which)                    # on the post, not above it


class TestCryostat:
    """A cryostat you can actually see into, that carries its own sample."""

    def test_its_windows_sit_at_the_bench_beam_height(self):
        """It stands on the table on its own feet, so the beam has to meet the
        windows where the bench beam runs -- not at the can's mid-height."""

        from optodraw.components.samples import Cryostat

        scope = Cryostat(beam_height=16.0)
        windows = [c for c in scope.geometry_3d()["children"] if c.get("role") == "window"]
        assert len(windows) == 2  # in and out
        for window in windows:
            assert window["position"][1] == pytest.approx(16.0)

    def test_the_windows_are_transparent(self):
        from optodraw.components.samples import Cryostat

        for window in [c for c in Cryostat().geometry_3d()["children"] if c.get("role") == "window"]:
            assert window["material"].get("transparent") is True

    def test_it_carries_its_own_sample_on_a_stage(self):
        from optodraw.components.samples import Cryostat

        scope = Cryostat()
        children = scope.geometry_3d()["children"]
        stage = next(c for c in children if c.get("role") == "stage")
        sample = next(c for c in children if c.get("role") == "sample")
        assert sample["position"][0] < stage["position"][0]  # the sample stands on the face of the block, toward the window
        assert "sample" in scope.ports()

    def test_the_stage_can_be_left_bare_for_your_own_sample(self):
        from optodraw.components.samples import Cryostat

        children = Cryostat(with_sample=False).geometry_3d()["children"]
        assert not [c for c in children if c.get("role") == "sample"]
        assert [c for c in children if c.get("role") == "stage"]

    def test_a_cryostat_does_not_stand_on_a_post(self):
        from optodraw.components.samples import Cryostat
        from optodraw.renderers.threejs_renderer import ThreeJsRenderer

        scene = Scene(width=200, height=120)
        cryo = scene.add(Cryostat(center=(0, 0)))
        assert not ThreeJsRenderer(scene)._is_beam_plane_optic(cryo)


def test_the_cryostat_sample_faces_its_wide_window():
    """The wide window sat on the side at +z, at 90 degrees to the chip's face: a beam through it met the chip edge on."""

    from optodraw.components.samples import Cryostat

    cryo = Cryostat()
    children = cryo.geometry_3d()["children"]
    sample = next(c for c in children if c.get("role") == "sample")
    wide = max((c for c in children if c.get("role") == "window"), key=lambda c: c["radius"])
    assert sample["width"] < min(sample["height"], sample["depth"])          # a thin chip whose face looks along x
    assert wide["position"][0] < sample["position"][0] < 0                  # in front of its face, on the in side
    assert wide["position"][1:] == pytest.approx(sample["position"][1:])     # on the line through the chip's centre
    assert cryo.ports()["in"].center.x < wide["position"][0]                 # the light comes in through it


def test_a_beam_through_a_periscope_still_draws_in_2d():
    """The mirror points inside the periscope shifted the beam's points against its anchors: IndexError in 2D."""

    import optodraw

    scene = optodraw.Scene(width=200, height=80, platform="free_space")
    laser = scene.add(optodraw.Laser(center=(-70, 0)))
    periscope = scene.add(Periscope(center=(0, 0), rise=25.0))
    pd = scene.add(optodraw.Photodiode(center=(70, 0)))
    beam = scene.add(optodraw.Beam((laser, "out"), (periscope, "in"), (periscope, "out"), (pd, "in")))
    runs = beam.segments()
    assert len(runs) == 2, runs                                 # the climb between the two mirrors is a gap
    assert [round(run[-1][0]) for run in runs][0] == 0 and round(runs[1][0][0]) == 0     # each side meets its mirror
    assert "<svg" in scene.render_svg().as_svg()


def test_a_beam_keeps_its_colour_through_a_periscope():
    from optodraw import Beam, Laser, Photodiode

    scene = Scene(title="scope", width=120, height=40, platform="free_space")
    laser = scene.add(Laser(center=(-45, 0), wavelength=450, label="Laser"))
    scope = scene.add(Periscope(center=(0, 0), label="Periscope"))
    pd = scene.add(Photodiode(center=(45, 0), label="PD"))
    beam = scene.add(Beam.through(laser, scope, pd, wavelength=450))
    svg = scene.render_svg().as_svg()
    assert "#f0a800" not in svg and "#5aa9e6" not in svg       # the part knows no wavelength: it draws no light
    assert beam.segments()[0][-1][0] == 0.0 == beam.segments()[1][0][0]     # the beam reaches both mirrors
