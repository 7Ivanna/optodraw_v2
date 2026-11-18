"""A wire, a fibre or a beam ends where the part's 2D art draws its port, for every part in the catalog.

The 2D art of a part is its symbol, fitted to the part's ports (optodraw/symbols/art.py). Where the ports and the
pic disagree, the drawing misses a port and the wire or the light ends in the air. On main at b3701d1 35 parts
missed: CameraSensor sync by 7.9 units, SMU lo 3.2, ReceiverMacro clk 4.8, PolarizationController out 20.5,
FourFSystem image 61.

Mutants (each one fails a test here):
- in ``fit_art``, size the art by the symbol's frame with its border again: PolarizationController, Pentaprism
  and BeamExpanderTelescope miss their last port, and a fibre that meets the controller is reported.
- drop the test in ``fit_art`` that keeps a part with only wires out of the size rule: the SMUs here miss lo.
- count the whole distance for a beam port in ``port_gaps``: every thin plate (Polarizer out 2.8) is reported.
- put back any port moved to its pic (EIC vdd at width / 2, Prism ports at size / 2, CameraSensor sync at the back
  of its frame): the catalog test names the part. SMU jacks at 6.6 and 12.2: its panel is drawn 41 units wide.
- take "FourFSystem" out of ``NO_ART``: its image port lies 57 units past its art.
- give TransmitterMacro its old width of 36: check_part_3d finds its bias and gnd tabs in the air.
"""

from __future__ import annotations

import pytest

import optodraw
from optodraw import Scene, check_figure
from optodraw.core.ports import Port
from optodraw.core.transform import Vec3
from optodraw.registry import build_component, component_registry
from optodraw.symbols.art import PORT_TOLERANCE, port_gaps

from sweep import sweep

NEEDS_A_SOURCE = {"CustomModel", "GDSModel"}     # built from a file, not from defaults
# The parts whose art still misses a port, each with its reason. The list only shrinks: a listed part that meets
# its ports fails the test, so it comes off the list.
STILL_MISSES: dict[str, str] = {}


def _catalog() -> list[str]:
    return sorted(set(component_registry()) - NEEDS_A_SOURCE)


def _check_every_port_ends_where_the_art_draws_it(name):
    over = {port: round(gap, 2) for port, gap in port_gaps(build_component(name)).items() if gap > PORT_TOLERANCE}
    if name in STILL_MISSES:
        assert over, f"{name} meets its ports now: take it off STILL_MISSES"
    else:
        assert not over, f"{name}: the art misses {over} (scene units)"


def test_every_port_ends_where_the_art_draws_it():
    sweep(_check_every_port_ends_where_the_art_draws_it, _catalog())


class _HolderPinhole(optodraw.Pinhole):
    """A pinhole whose ports sit on its 3D holder, past the foil its 2D art draws (as on main)."""

    component_type = "Pinhole"

    def ports(self):
        half = self.outer_diameter * 0.09
        return {"in": Port("in", Vec3(-half, 0.0, 0.0), orientation_deg=180.0, width=8.0, kind="free_space"),
                "out": Port("out", Vec3(half, 0.0, 0.0), orientation_deg=0.0, width=8.0, kind="free_space")}


class _WideJacks(optodraw.SMU):
    """An SMU whose jacks lie twice as far apart as its pic draws them."""

    component_type = "SMU"
    JACKS = {"hi": 0.4, "lo": 0.88}


class _MovedFibre(optodraw.PolarizationController):
    """A polarization controller whose fibre output moved 3 units off the end its art draws."""

    component_type = "PolarizationController"

    def ports(self):
        ports = super().ports()
        out = ports["out"]
        ports["out"] = Port("out", Vec3(float(out.center.x), float(out.center.y) + 3.0, 0.0), orientation_deg=0.0,
                            width=out.width, kind=out.kind)
        return ports


@pytest.mark.parametrize("cls, found", [(optodraw.PolarizationController, False), (_MovedFibre, True)],
                         ids=["meets", "moved"])
def test_a_fibre_that_ends_off_the_drawn_port_is_found(cls, found):
    scene = Scene(title="x", width=200, height=80, platform="free_space")
    controller = scene.add(cls(center=(0, 0)))
    collimator = scene.add(optodraw.FiberCollimator(center=(60, 3)))
    scene.route((controller, "out"), (collimator, "in"), kind="fiber")
    findings = [f for f in check_figure(scene, view="2d") if "ends in the air" in f and "PolarizationController:out" in f]
    assert bool(findings) == found, findings


