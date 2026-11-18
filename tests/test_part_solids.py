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

import warnings


from optodraw import check_part_3d
from optodraw.catalog import list_components
from optodraw.registry import build_component

from sweep import sweep

# Parts that do not build without an argument, so they have no default solids to check.
NOT_CHECKED = {
    "CustomModel": "needs its model file",
    "GDSModel": "needs its GDS file",
}


def _check_no_catalog_part_has_a_3d_finding(name):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        part = build_component(name)
    assert check_part_3d(part) == []


def test_no_catalog_part_has_a_3d_finding():
    sweep(_check_no_catalog_part_has_a_3d_finding, [name for name in list_components() if name not in NOT_CHECKED])


