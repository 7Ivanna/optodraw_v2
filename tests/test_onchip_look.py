"""The on-chip look: silicon in the AWGR blue, and the parts drawn as their real layouts."""

from __future__ import annotations

import pytest

import optodraw
from optodraw.registry import build_component, component_registry

OLD_TEAL = ("#0b7285", "#083c47")


def _on_chip_parts() -> list[str]:
    return sorted(name for name, spec in component_registry().items()
                  if spec.category == "on_chip" and name != "ChipSubstrate")


def _svg(part) -> str:
    scene = optodraw.Scene(width=200, height=120, platform="on_chip")
    scene.add(part)
    return scene.render_svg().as_svg().lower()


@pytest.mark.parametrize("name", _on_chip_parts())
def test_silicon_is_the_awgr_blue(name):
    """Every on-chip part draws its silicon in the AWGR blue; no old teal is left."""

    svg = _svg(build_component(name, label=""))
    assert not any(colour in svg for colour in OLD_TEAL), name


def test_a_waveguide_is_drawn_in_the_awgr_blue():
    svg = _svg(optodraw.Waveguide(label=""))
    assert "#2b6cb0" in svg and "#1a4373" in svg


def _steepest(points) -> float:
    return max(abs((y1 - y0) / (x1 - x0)) for (x0, y0), (x1, y1) in zip(points, points[1:]) if x1 - x0 > 1e-9)


def test_the_tap_coupler_bends_gently():
    """The tap arm rose 11 units over 6 (slope 2.9); its bends must be gentle."""

    assert _steepest(optodraw.TapCoupler()._tap()) < 1.1


def test_the_sagnac_loop_is_one_waveguide_through_a_coupler_and_round_a_loop():
    """A Sagnac mirror: o1 goes through the coupler, round the loop, back through the coupler to o2."""

    loop = optodraw.SagnacLoop()
    path, ports = loop._loop_path(), loop.ports()
    start, end = path[0], path[-1]
    assert (start[0], start[1]) == pytest.approx((ports["o1"].center.x, ports["o1"].center.y))
    assert (end[0], end[1]) == pytest.approx((ports["o2"].center.x, ports["o2"].center.y))
    assert _steepest(path[:len(path) // 4]) < 1.1                      # gentle bends into the coupler
    assert max(x for x, _ in path) > 0 > min(x for x, _ in path)


def test_the_echelle_grating_has_access_waveguides_and_a_toothed_reflector():
    grating = optodraw.EchelleGrating()
    svg = _svg(grating)
    left = -grating.slab_length / 2.0
    assert all(port.center.x < left for port in grating.ports().values())      # the guides reach the slab
    assert svg.count("<path") > grating.facet_count                            # one tooth per facet


def test_the_polarization_rotator_shows_its_asymmetric_slab():
    svg = _svg(optodraw.PolarizationRotator(label=""))
    assert "#2f6f7d" not in svg and svg.count("<path") >= 2


def test_the_thermal_phase_shifter_has_trenches_a_heater_and_vias():
    shifter = optodraw.PhaseShifter()
    colours = {child.get("fill") for child in shifter.geometry_2d()["children"]}
    assert {"#eef4fb", "#c8964a", "#f08c6d"} <= colours                       # trench, TiN heater, via


def test_a_coupler_arm_has_no_repeated_end_point():
    """A repeated end point gave the tap arm a small flag at its end."""

    arm = optodraw.TapCoupler()._tap()
    assert all(abs(x1 - x0) + abs(y1 - y0) > 1e-9 for (x0, y0), (x1, y1) in zip(arm, arm[1:]))


DARK_GE = "#4b5967"                                                  # the old near-black germanium


@pytest.mark.parametrize("name", ["OnChipPhotodetector", "OnChipBalancedPhotodetector", "AvalanchePhotodetector",
                                  "ElectroAbsorptionModulator"])
def test_a_ge_device_shows_its_doped_regions_ge_and_vias_in_light_colours(name):
    svg = _svg(build_component(name, label=""))
    assert DARK_GE not in svg, name
    assert all(colour in svg for colour in ("#a8b4c4", "#f4b4b4", "#b7cdf2", "#f08c6d")), name   # Ge, p+, n+, via


def test_the_balanced_detector_wires_its_diodes_in_series_without_metal_over_the_ge():
    """The old drawing ran a gold bridge across both absorbers and stacked its pads."""

    from optodraw.layout import estimate_component_bounds

    bpd = optodraw.OnChipBalancedPhotodetector()
    gold = [c for c in bpd.geometry_2d()["children"] if c.get("fill") == "#d4af37"]
    ge = [c for c in bpd.geometry_2d()["children"] if c.get("fill") == "#a8b4c4"]
    for metal in gold:
        for mesa in ge:
            overlap_x = abs(metal["cx"] - mesa["cx"]) < (metal["w"] + mesa["w"]) / 2.0
            overlap_y = abs(metal["cy"] - mesa["cy"]) < (metal["h"] + mesa["h"]) / 2.0
            assert not (overlap_x and overlap_y)
    assert estimate_component_bounds(bpd)


def test_the_avalanche_detector_taper_is_silicon_and_it_has_a_charge_layer():
    children = optodraw.AvalanchePhotodetector().geometry_2d()["children"]
    assert children[0]["fill"] == "#2b6cb0"                                    # the taper is silicon, not Ge
    assert any(c.get("fill") == "#d6c6ee" for c in children)                   # the charge (multiplication) layer


OLD_LASER = ("#5f5256", "#7d4e57", "#a96a79", "#8c5c67", "#0a2c34")      # dark mesa, dark grating bars


@pytest.mark.parametrize("name", ["OnChipLaser", "DBRLaser", "FrequencyComb"])
def test_a_laser_shows_its_silicon_guide_mirrors_iii_v_mesa_and_mqw_in_light_colours(name):
    svg = _svg(build_component(name, label=""))
    assert not any(colour in svg for colour in OLD_LASER), name
    assert all(colour in svg for colour in ("#2b6cb0", "#f6c9d3", "#e893a8")), name    # silicon, InP, MQW


def test_the_frequency_comb_pumps_a_microring_on_its_output_bus():
    comb, laser = optodraw.FrequencyComb(), optodraw.OnChipLaser()
    assert comb.ports()["o1"].center.x > laser.ports()["o1"].center.x + 10.0         # the bus runs past the ring
    assert any(c.get("type") == "circle" for c in comb.geometry_2d()["children"])


def _angles(points, cy=0.0):
    import math
    return [math.degrees(math.atan2(y - cy, x)) % 360.0 for x, y in points]


def test_the_pn_ring_bands_are_cut_sectors_that_leave_the_bus_free():
    """As in the 1D symbol the bands are cut sectors; the old 2D drew full overlapping rings."""

    ring = optodraw.PNMicroringModulator()
    p_bands, n_bands = ring._doping_polygons()
    for band in p_bands + n_bands:
        assert not any(240.0 < a < 300.0 for a in _angles(band))           # nothing under the bus coupler
    heater = ring._heater_band()
    assert all(x < 0.0 for x, _ in heater)                                  # the heater has its own sector, left
    ports = ring.ports()
    assert ports["h1"].center.x < -ring.ring_radius and ports["h2"].center.x < -ring.ring_radius
    assert ports["e1"].center.y > ring.ring_radius and ports["e2"].center.y > ring.ring_radius


def test_the_pn_ring_with_a_drop_bus_keeps_its_pads_between_the_buses():
    ring = optodraw.PNMicroringModulator(add_drop=True)
    ports = ring.ports()
    for name in ("e1", "e2", "h1", "h2"):
        assert ring.through_bus_y < ports[name].center.y < ring.drop_bus_y, name


def test_the_racetrack_modulator_has_pn_on_its_left_bend_and_the_heater_on_its_right():
    mod = optodraw.RacetrackModulator()
    draw = mod._draw_variant()
    assert all(x > draw.coupling_length / 2.0 - 1e-6 for x, _ in draw._heater_band())
    ports = mod.ports()
    assert ports["e1"].center.x < 0 and ports["e2"].center.x < 0
    assert ports["h1"].center.x > 0 and ports["h2"].center.x > 0


def test_the_soa_is_a_light_tapered_gain_mesa_on_its_silicon_guide():
    svg = _svg(optodraw.SOA(label=""))
    assert "#8c5c67" not in svg                                             # the old dark mauve slab
    assert all(colour in svg for colour in ("#2b6cb0", "#f6c9d3", "#e893a8", "#f08c6d"))


def test_the_wdm_input_brings_three_wavelengths_into_a_silicon_combiner():
    svg = _svg(build_component("PresetWDMInput", label=""))
    assert "#525f69" not in svg                                             # the old dark grey block
    assert all(colour in svg for colour in ("#2b6cb0", "#0072b2", "#009e73", "#e69f00"))


def test_the_pn_ring_junction_animation_runs_on_the_doped_sector():
    """The carriers animate where the p and n bands are drawn, not on the bus side of the ring."""

    import math

    from optodraw.core.timeline3d import anim_payload_map

    scene = optodraw.Scene(platform="on_chip")
    ring = scene.add(optodraw.PNMicroringModulator(center=(0, 0)))
    (path,) = anim_payload_map(scene)[id(ring)]["junction"]["paths"]
    start, end = ring._pn_sectors()[0]
    for x, y in path["pts"]:
        angle = math.degrees(math.atan2(y, x))
        assert start - 1.0 <= angle <= end + 1.0


def _materials(part) -> list[dict]:
    return [child.get("material") or {} for child in part.geometry_3d()["children"]]


def test_a_grating_io_bank_draws_toothed_grating_couplers():
    """Each coupler was a plain box (a teal oxide slab in 3D); a bank of grating couplers shows its teeth."""

    bank = optodraw.OpticalIOBank(count=4, label="")
    svg = _svg(bank)
    assert svg.count("<path") + svg.count("<rect") >= 4 * 8                    # taper, grating, teeth per channel
    assert not any(m.get("color") == "#83b7c1" for m in _materials(bank))
    assert sum(m.get("color") == "#2b6cb0" for m in _materials(bank)) >= 4 * 8


def test_an_edge_io_bank_draws_inverse_tapers_under_oxide():
    bank = optodraw.OpticalIOBank(count=3, coupler_kind="edge", label="")
    assert sum(m.get("preset") == "sio2" for m in _materials(bank)) == 3       # one cladding block per channel
    assert not any(m.get("color") == "#83b7c1" for m in _materials(bank))


def test_the_wdm_input_in_3d_is_its_2d_funnel_and_three_guides():
    """3D drew the combiner as one opaque silicon block; it is the 2D funnel, fed by three silicon guides."""

    part = build_component("PresetWDMInput", label="")
    children = part.geometry_3d()["children"]
    funnels = [c for c in children if c.get("shape") == "extruded_polygon" and len(c["points"]) == 6]
    guides = [c for c in children if c.get("shape") == "extruded_polygon" and len(c["points"]) == 4
              and (c.get("material") or {}).get("color") == "#2b6cb0"]
    assert len(funnels) == 1 and len(guides) >= 3
    assert funnels[0]["height"] < min(g["height"] for g in guides)              # a shallow slab, not a block
    assert not any(c.get("shape") == "box" and c.get("width") == pytest.approx(part.body_length) for c in children)
    colours = {(c.get("material") or {}).get("color") for c in children}
    assert {"#0072b2", "#009e73", "#e69f00"} <= colours


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


def test_a_vertical_grating_coupler_has_a_fibre_port_over_its_teeth():
    """It had only its waveguide port, so a fibre routed to it landed at the taper end."""

    gc = optodraw.VerticalGratingCoupler()
    port = gc.ports()["f1"]
    assert port.kind == "fiber" and (port.center.x, port.center.y) == pytest.approx(gc._fiber_port_center())


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
