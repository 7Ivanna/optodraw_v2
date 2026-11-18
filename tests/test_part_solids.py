"""Every catalog part stands in 3D: no solid hangs in the air, and a part the viewer stands on a post meets the post
with a flat face. A part made of separate pieces says so (``lies_on_table``), and then each piece rests on the
table or the die.

Mutants (each one fails a test here):
- the RFDriver input lead back at x = -0.42 L, 0.18 L long: it ends short of the body.
- ``HeaterPad._heater_path`` without its two leads: the serpentine ends short of both pads.
- the MEMS bus bar back at x = -0.29 L, 0.18 L long: it touches neither the pad nor the stator spine.
- ``check_part_3d`` without its ``is_beam_plane_optic`` test: a periscope, an FPGA board and a computer, which
  stand on the table, are asked for a post.
- ``rotation_y=math.atan2(-segment_dy, segment_dx)`` back in ``MetalRoute.geometry_3d``: a diagonal bar runs
  mirrored.
"""

from __future__ import annotations

import math
import warnings

import pytest

from optodraw import MEMSActuator, MetalRoute, check_part_3d
from optodraw.catalog import list_components
from optodraw.check import solid_boxes
from optodraw.registry import build_component

# Parts that do not build without an argument, so they have no default solids to check.
NOT_CHECKED = {
    "CustomModel": "needs its model file",
    "GDSModel": "needs its GDS file",
}


@pytest.mark.parametrize("name", [name for name in list_components() if name not in NOT_CHECKED])
def test_no_catalog_part_has_a_3d_finding(name):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        part = build_component(name)
    assert check_part_3d(part) == []


@pytest.mark.parametrize("name", sorted(NOT_CHECKED))
def test_a_part_left_unchecked_still_needs_its_argument(name):
    with pytest.raises(TypeError):
        build_component(name)


def _bodies(part) -> list[set[str]]:
    """The colours of each set of solids that touch one another."""

    solids = list(solid_boxes(part.geometry_3d()))
    tol = 1e-6

    def touching(p, q):
        return all(p[k][0] <= q[k][1] + tol and q[k][0] <= p[k][1] + tol for k in range(3))

    left, bodies = set(range(len(solids))), []
    while left:
        body, grew = {left.pop()}, True
        while grew:
            grew = False
            for j in list(left):
                if any(touching(solids[i][1], solids[j][1]) for i in body):
                    body.add(j)
                    left.discard(j)
                    grew = True
        bodies.append({solids[i][0]["material"]["color"] for i in body})
    return bodies


@pytest.mark.parametrize("fingers", [3, 6, 10, 20])
def test_a_comb_drive_is_two_bodies_the_stator_and_the_rotor(fingers):
    """Each finger stops short of the other comb: a stator that touches the rotor is a short circuit. The bus bar
    joins the left pad to the stator, and the springs join the rotor to the right pad."""

    stator, rotor = MEMSActuator._COMB_COLORS["stator"], MEMSActuator._COMB_COLORS["rotor"]
    bodies = _bodies(MEMSActuator(finger_count=fingers))
    assert sorted((stator in body, rotor in body) for body in bodies) == [(False, True), (True, False)]


def test_a_diagonal_metal_route_runs_along_its_segment_in_3d():
    """A turn about y carries 3D +x to (cos, 0, -sin), and the layout's +y is 3D -z: a bar from (0, 0) to (10, 10)
    runs to (+x, -z)."""

    (bar,) = MetalRoute(points=[(0, 0), (10, 10)]).geometry_3d()["children"]
    turn = bar["rotation"][1]
    assert (math.cos(turn), -math.sin(turn)) == pytest.approx((math.sqrt(0.5), -math.sqrt(0.5)))
