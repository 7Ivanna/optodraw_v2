"""The emitters of an optical phased array (Van Acoleyen et al., Opt. Lett. 34, 1477 (2009), Fig. 1): one shallow
grating per channel on a pitch, light in at the west ends, teeth on a floor the etch thins."""

from __future__ import annotations

import pytest

from optodraw import GratingAntennaArray, MMI1x2, Scene, VerticalGratingCoupler, check_figure, check_part_3d
from optodraw.symbols import lookup


def test_one_port_per_channel_at_the_west_end_lowest_first_on_the_pitch():
    array = GratingAntennaArray(count=16, pitch=2.0, length=31.5, render_physical=True)
    ports = array.ports()
    assert list(ports) == [f"o{k}" for k in range(1, 17)]
    ys = [port.center.y for port in ports.values()]
    assert all(b - a == pytest.approx(2.0) for a, b in zip(ys, ys[1:]))         # o1 lowest, 2 um apart
    assert {round(port.center.x, 6) for port in ports.values()} == {-15.75}     # the west end of 31.5 um gratings
    assert {port.orientation_deg for port in ports.values()} == {180}


def test_the_teeth_stand_at_core_height_on_a_floor_the_etch_thins():
    array = GratingAntennaArray(count=1, etch_depth=0.07)                       # 70 nm of 220 nm, as in the paper
    floor, tooth = sorted({round(solid["height"], 9) for solid in array.geometry_3d()["children"]})
    assert tooth == pytest.approx(array._draw_thickness())
    assert floor == pytest.approx(tooth * (1 - 0.07 / 0.22))
    assert check_part_3d(array) == []


def test_the_first_grating_lobe_is_the_papers():
    assert GratingAntennaArray(pitch=2.0).physics_metadata()["grating_lobe_deg"] == pytest.approx(50.8, abs=0.1)
    assert GratingAntennaArray(pitch=0.7).physics_metadata()["grating_lobe_deg"] is None   # under one wavelength


def test_an_etch_through_the_core_is_refused():
    with pytest.raises(ValueError, match="etch_depth"):
        GratingAntennaArray(etch_depth=0.22)


def test_a_splitter_tree_into_the_array_passes_the_figure_checks_in_2d_and_1d():
    route = {"kind": "waveguide", "path_type": "smooth"}
    chip = Scene(title="OPA", platform="on_chip")
    source = chip.add(VerticalGratingCoupler(center=(-50, 0), angle=180, label="In"))
    root = chip.add(MMI1x2(center=(0, 0)))
    pair = [chip.add(MMI1x2(center=(50, y))) for y in (-12, 12)]
    array = chip.add(GratingAntennaArray(center=(110, 0), count=4, label="Antennas", label_side="right"))
    chip.route((source, "o1"), (root, "o1"), **route)
    chip.route((root, "o2"), (pair[0], "o1"), **route)
    chip.route((root, "o3"), (pair[1], "o1"), **route)
    for k, (mmi, port) in enumerate((m, p) for m in pair for p in ("o2", "o3")):
        chip.route((mmi, port), (array, f"o{k + 1}"), **route)
    chip.fit_frame(margin=8)
    assert check_figure(chip, view="both") == []


def test_the_array_has_its_own_1d_symbol():
    array = GratingAntennaArray()
    symbol = lookup(array)
    assert symbol.exact and sorted(symbol.ports) == sorted(array.ports())       # mutant: drop symbol_1d: a block
