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


class TestPeriscopeInSetups:

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


class TestPeriscopeMirrorsFaceTheBeam:
    """A mirror face has to look AT the light. The normal bisects where the beam
    comes from and where it leaves: the lower mirror faces back along the input
    and upward, the upper one faces down and out along the exit."""

    @staticmethod
    def _unit(vector):
        import math

        length = math.sqrt(sum(v * v for v in vector))
        return tuple(v / length for v in vector)


    def test_a_falling_periscope_folds_the_beam_down_first(self):
        """With the exit mirror BELOW, the entry mirror has to turn the beam down
        toward it. Using the rising angles points both mirrors at nothing."""

        entry, exit_ = Periscope(rise=-30.0).mirror_normals()
        assert entry == pytest.approx(self._unit((-1.0, -1.0, 0.0)), abs=1e-6)
        assert exit_ == pytest.approx(self._unit((1.0, 1.0, 0.0)), abs=1e-6)


FOLDS = ({}, {"rise": -30.0}, {"output_angle_deg": 90.0}, {"rise": -30.0, "output_angle_deg": 270.0})


