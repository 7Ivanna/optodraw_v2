"""A mirror on piezo actuators: a stack that moves it along its normal, or a mount that tips, tilts and pushes it."""

from __future__ import annotations

import pytest

from optodraw import Beam, ConcaveMirror, Laser, Mirror, Scene, check_figure, check_part_3d
from optodraw.registry import build_component
from optodraw.schema import scene_from_spec, scene_to_spec
from optodraw.symbols import lookup
from optodraw.symbols.art import art_2d


@pytest.mark.parametrize("make", [Mirror, ConcaveMirror])
@pytest.mark.parametrize("piezo", ["stack", "3axis"])
def test_the_drive_enters_at_the_back_of_the_piezo(make, piezo):
    part = make(aperture=12.0, piezo=piezo)
    ports = part.ports()
    assert set(ports) == {"io", "pzt"}
    assert ports["pzt"].kind == "electrical" and ports["pzt"].orientation_deg == pytest.approx(0.0)
    reach = Mirror.PIEZO_REACH[part.surface_type] * 12.0                  # the pic's distance behind the face
    assert ports["pzt"].center.x - ports["io"].center.x == pytest.approx(reach)


def test_without_a_piezo_a_mirror_keeps_its_one_port_and_symbol():
    assert set(Mirror().ports()) == {"io"} and Mirror().symbol_1d() is None
    assert ConcaveMirror().symbol_1d() == ("mirror", {"kind": "concave"})


def test_true_means_a_stack_and_an_unknown_mount_is_refused():
    assert Mirror(piezo=True).piezo == "stack" and Mirror(piezo=False).piezo is None
    with pytest.raises(ValueError, match="piezo"):
        Mirror(piezo="ring")


def test_the_piezo_survives_a_save_and_a_catalog_build():
    assert build_component("ConcaveMirror", piezo="stack").piezo == "stack"
    scene = Scene(title="", platform="free_space")
    scene.add(Mirror(piezo="3axis", label="M1"))
    scene.add(ConcaveMirror(center=(20, 0), piezo="stack", label="M2"))
    kept = {n.label: n.piezo for n in scene_from_spec(scene_to_spec(scene)).walk() if hasattr(n, "piezo")}
    assert kept == {"M1": "3axis", "M2": "stack"}


def test_a_stack_holds_the_mirror_out_of_its_mount_and_a_3axis_mount_has_three_actuators():
    def solids(part, role):
        return [c for c in part.geometry_3d()["children"] if c.get("role") == role]

    assert len(solids(Mirror(piezo="stack"), "piezo")) == 1
    assert len(solids(Mirror(piezo="3axis"), "piezo")) == 3 and not solids(Mirror(piezo="3axis"), "knob")
    assert solids(Mirror(), "knob") and not solids(Mirror(), "piezo")
    for part in (Mirror(piezo="stack"), Mirror(piezo="3axis"), ConcaveMirror(piezo="stack"), ConcaveMirror(piezo="3axis")):
        assert check_part_3d(part) == []


@pytest.mark.parametrize("part", [Mirror(piezo="stack"), Mirror(piezo="3axis"), ConcaveMirror(piezo="stack"),
                                  ConcaveMirror(piezo="3axis")], ids=lambda p: f"{p.component_type}-{p.piezo}")
def test_its_symbol_draws_the_piezo_and_its_art_fits_both_ports(part):
    # needs the symbol library rebuilt with the rows of variants.toml (python -m optodraw.symbols.build)
    symbol = lookup(part)
    assert symbol.exact and symbol.params.get("pzt") == part.piezo and set(symbol.ports) == {"io", "pzt"}
    art = art_2d(part)
    assert art is not None and art["residual"] < 0.02                  # the plan and the pic agree


def test_a_cavity_end_mirror_on_a_stack_passes_the_figure_checks():
    scene = Scene(title="", platform="free_space")
    laser = scene.add(Laser(center=(-30, 0), wavelength=1064, label="Laser"))
    end = scene.add(ConcaveMirror(center=(0, 0), piezo="stack", label="PZT"))
    scene.add(Beam.through(laser, end, wavelength=1064))
    scene.fit_frame(margin=4)
    assert check_figure(scene, preset="single_column") == []
