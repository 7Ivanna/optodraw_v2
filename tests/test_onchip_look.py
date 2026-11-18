"""The on-chip look: silicon in the AWGR blue, and the parts drawn as their real layouts."""

from __future__ import annotations

import pytest

import optodraw
from optodraw.registry import build_component, component_registry

from sweep import sweep

OLD_TEAL = ("#0b7285", "#083c47")


def _on_chip_parts() -> list[str]:
    return sorted(name for name, spec in component_registry().items()
                  if spec.category == "on_chip" and name != "ChipSubstrate")


def _svg(part) -> str:
    scene = optodraw.Scene(width=200, height=120, platform="on_chip")
    scene.add(part)
    return scene.render_svg().as_svg().lower()


def _check_silicon_is_the_awgr_blue(name):
    """Every on-chip part draws its silicon in the AWGR blue; no old teal is left."""

    svg = _svg(build_component(name, label=""))
    assert not any(colour in svg for colour in OLD_TEAL), name


def test_silicon_is_the_awgr_blue():
    sweep(_check_silicon_is_the_awgr_blue, _on_chip_parts())


def _steepest(points) -> float:
    return max(abs((y1 - y0) / (x1 - x0)) for (x0, y0), (x1, y1) in zip(points, points[1:]) if x1 - x0 > 1e-9)


def test_the_sagnac_loop_is_one_waveguide_through_a_coupler_and_round_a_loop():
    """A Sagnac mirror: o1 goes through the coupler, round the loop, back through the coupler to o2."""

    loop = optodraw.SagnacLoop()
    path, ports = loop._loop_path(), loop.ports()
    start, end = path[0], path[-1]
    assert (start[0], start[1]) == pytest.approx((ports["o1"].center.x, ports["o1"].center.y))
    assert (end[0], end[1]) == pytest.approx((ports["o2"].center.x, ports["o2"].center.y))
    assert _steepest(path[:len(path) // 4]) < 1.1                      # gentle bends into the coupler
    assert max(x for x, _ in path) > 0 > min(x for x, _ in path)


DARK_GE = "#4b5967"                                                  # the old near-black germanium


OLD_LASER = ("#5f5256", "#7d4e57", "#a96a79", "#8c5c67", "#0a2c34")      # dark mesa, dark grating bars


def test_the_frequency_comb_pumps_a_microring_on_its_output_bus():
    comb, laser = optodraw.FrequencyComb(), optodraw.OnChipLaser()
    assert comb.ports()["o1"].center.x > laser.ports()["o1"].center.x + 10.0         # the bus runs past the ring
    assert any(c.get("type") == "circle" for c in comb.geometry_2d()["children"])


def test_the_pn_ring_with_a_drop_bus_keeps_its_pads_between_the_buses():
    ring = optodraw.PNMicroringModulator(add_drop=True)
    ports = ring.ports()
    for name in ("e1", "e2", "h1", "h2"):
        assert ring.through_bus_y < ports[name].center.y < ring.drop_bus_y, name


def test_the_wdm_input_brings_three_wavelengths_into_a_silicon_combiner():
    svg = _svg(build_component("PresetWDMInput", label=""))
    assert "#525f69" not in svg                                             # the old dark grey block
    assert all(colour in svg for colour in ("#2b6cb0", "#0072b2", "#009e73", "#e69f00"))


def _materials(part) -> list[dict]:
    return [child.get("material") or {} for child in part.geometry_3d()["children"]]


def test_an_edge_io_bank_draws_inverse_tapers_under_oxide():
    bank = optodraw.OpticalIOBank(count=3, coupler_kind="edge", label="")
    assert sum(m.get("preset") == "sio2" for m in _materials(bank)) == 3       # one cladding block per channel
    assert not any(m.get("color") == "#83b7c1" for m in _materials(bank))


@pytest.mark.parametrize("side", ["left", "right", "top", "bottom"])
def test_a_grating_bank_puts_each_fibre_over_its_grating_teeth(side):
    """The fibre discs and ports sat beyond each grating, off the chip feature that couples the light."""

    bank = optodraw.OpticalIOBank(count=3, with_fibers=True, side=side, label="")
    stub, length = bank._draw("stub_length", bank.stub_length), bank._draw("coupler_length", 24.0)
    for index in (1, 2, 3):
        fibre = bank.ports()[f"f{index}"].center
        out = abs(fibre.x) if side in ("left", "right") else abs(fibre.y)   # distance out from the bank
        assert stub / 2.0 + 0.4 * length < out < stub / 2.0 + length          # over the teeth
    circles = [c for c in bank.geometry_2d()["children"] if c.get("type") == "circle"]
    fibres = [bank.ports()[f"f{i}"].center for i in (1, 2, 3)]
    assert all(any(abs(c["cx"] - f.x) < 1e-6 and abs(c["cy"] - f.y) < 1e-6 for c in circles) for f in fibres)


def test_an_edge_bank_puts_each_fibre_at_the_facet_beyond_the_tip():
    bank = optodraw.OpticalIOBank(count=2, coupler_kind="edge", with_fibers=True, side="left", label="")
    stub, length = bank._draw("stub_length", bank.stub_length), bank._draw("coupler_length", 24.0)
    assert all(abs(bank.ports()[f"f{i}"].center.x) > stub / 2.0 + length for i in (1, 2))


def test_the_2d_grating_coupler_shows_its_hole_grid_in_3d():
    """Its 3D body was a plain slab: the fibre stood over nothing that couples light."""

    gc = optodraw.TwoDGratingCoupler(with_fiber=True)
    bodies = [c for c in gc.geometry_3d()["children"] if c.get("holes")]
    assert len(bodies) == 1 and len(bodies[0]["holes"]) == gc.hole_rows ** 2


def test_an_edge_coupler_fibre_is_a_round_fibre_at_the_facet():
    """Its fibre was a glass sheet a tenth of a unit thick: in 3D it did not show."""

    import math

    ec = optodraw.EdgeCoupler(with_fiber=True)
    fibres = [c for c in ec.geometry_3d()["children"] if c.get("shape") == "cylinder"
              and c.get("rotation") and abs(c["rotation"][2] - math.pi / 2.0) < 1e-6]
    assert fibres
    fibre = max(fibres, key=lambda c: c["radius"])
    assert fibre["position"][0] + fibre["height"] / 2.0 == pytest.approx(ec.ports()["f1"].center.x)  # at the facet
    assert fibre["position"][1] == pytest.approx(fibre["radius"])                          # it rests on the chip
