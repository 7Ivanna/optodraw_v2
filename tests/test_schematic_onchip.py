"""Tests for schematic-first on-chip component rendering."""

from __future__ import annotations

import pytest

from optodraw import AWG, BraggGrating, OpticalIOBank, StarCoupler, Waveguide, MMI1x2, VerticalGratingCoupler, MicroringResonator, route_ports
from optodraw.components.onchip import couplers, io, mmi, modulators, rings, splitters, system, waveguides
from optodraw.components.onchip.base import ChipComponent
from optodraw.components.onchip.couplers import EdgeCoupler, GratingCouplerArray
from optodraw.components.onchip.io import ADC, DACDriver, OnChipLaser, OnChipPhotodetector, SOA, TIA
from optodraw.components.onchip.modulators import MZI, MZM
from optodraw.components.onchip.rings import MicroringWeightBank, RacetrackModulator, RacetrackResonator
from optodraw.components.onchip.schematic_tables import SCHEMATIC_TABLES
from optodraw.components.onchip.splitters import DirectionalCoupler, YBranch
from optodraw.components.onchip.system import SagnacLoop


def _geometry_bounds(node):
    points: list[tuple[float, float]] = []

    def collect(current):
        if current.get("type") == "rect":
            half_w = current["w"] / 2.0
            half_h = current["h"] / 2.0
            points.extend(
                [
                    (current["cx"] - half_w, current["cy"] - half_h),
                    (current["cx"] + half_w, current["cy"] + half_h),
                ]
            )
        elif current.get("type") == "circle":
            radius = current["r"]
            points.extend(
                [
                    (current["cx"] - radius, current["cy"] - radius),
                    (current["cx"] + radius, current["cy"] + radius),
                ]
            )
        elif current.get("type") == "line":
            points.extend([(current["x1"], current["y1"]), (current["x2"], current["y2"])])
        elif "points" in current:
            points.extend((point[0], point[1]) for point in current["points"])
        for child in current.get("children", []):
            collect(child)

    collect(node)
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return min(xs), min(ys), max(xs), max(ys)


def _geometry_width(node):
    xmin, _, xmax, _ = _geometry_bounds(node)
    return xmax - xmin


def _geometry_height(node):
    _, ymin, _, ymax = _geometry_bounds(node)
    return ymax - ymin


class TestSchematicOnChipDefaults:
    def test_public_onchip_classes_have_schematic_metadata(self):
        modules = [couplers, io, mmi, modulators, rings, splitters, system, waveguides]
        failures: list[str] = []
        for module in modules:
            for value in vars(module).values():
                if (
                    isinstance(value, type)
                    and issubclass(value, ChipComponent)
                    and value is not ChipComponent
                    and value.__module__ == module.__name__
                    and not value.__name__.startswith("_")
                ):
                    family = getattr(value, "schematic_family", None)
                    has_spec = value.physical_spec is not ChipComponent.physical_spec
                    if family not in SCHEMATIC_TABLES or not has_spec or (family == "waveguide" and value is not Waveguide):
                        failures.append(f"{module.__name__}.{value.__name__}: family={family!r}, has_spec={has_spec}")

        assert failures == []

    @pytest.mark.parametrize(
        ("component", "family", "key", "expected"),
        [
            (EdgeCoupler(taper_length=72.0), "edge_coupler", "taper_length", 72.0),
            (GratingCouplerArray(count=4, pitch=125.0), "grating_coupler_array", "array_width", 375.0),
            (YBranch(branch_length=36.0), "y_branch", "branch_length", 36.0),
            (DirectionalCoupler(coupling_length=18.0), "directional_coupler", "coupling_length", 18.0),
            (MZI(arm_length=180.0), "mzi", "arm_length", 180.0),
            (MZM(electrode_width=8.0, drive_style="gsg"), "mzm", "electrode_width", 8.0),
            (RacetrackResonator(bend_radius=12.0), "racetrack", "bend_radius", 12.0),
            (RacetrackModulator(coupling_length=60.0, electrode_length=44.0, add_drop=False), "racetrack_modulator", "active_length", 44.0),
            (MicroringWeightBank(ring_count=3), "microring_weight_bank", "ring_count", 3),
            (OpticalIOBank(count=4, pitch=127.0), "optical_io_bank", "count", 4),
            (StarCoupler(input_count=2, output_count=6), "star_coupler", "output_count", 6),
            (AWG(channel_count=8, array_count=24), "awg", "array_count", 24),
            (BraggGrating(length=320.0, period=0.32), "bragg_grating", "length", 320.0),
            (SagnacLoop(loop_radius=40.0), "sagnac_loop", "loop_radius", 40.0),
        ],
    )
    def test_expanded_onchip_components_record_physical_specs(self, component, family, key, expected):
        spec = component.physical_spec()
        assert component.schematic_family == family
        assert spec.device_family == family
        assert spec[key] == pytest.approx(expected)

    @pytest.mark.parametrize(
        ("component", "physical_component", "schematic_extent", "physical_extent"),
        [
            (EdgeCoupler(taper_length=72.0, cladding_length=24.0), EdgeCoupler(taper_length=72.0, cladding_length=24.0, render_physical=True), 48.0, 96.0),
            (YBranch(branch_length=36.0, stem_length=4.0), YBranch(branch_length=36.0, stem_length=4.0, render_physical=True), 12.4, 40.0),
            (RacetrackResonator(bend_radius=30.0, coupling_length=80.0), RacetrackResonator(bend_radius=30.0, coupling_length=80.0, render_physical=True), 62.0, 146.0),
        ],
    )
    def test_expanded_onchip_components_draw_from_schematic_tables(self, component, physical_component, schematic_extent, physical_extent):
        assert _geometry_width(component.geometry_2d()) == pytest.approx(schematic_extent)
        assert _geometry_width(physical_component.geometry_2d()) == pytest.approx(physical_extent)

    def test_composite_onchip_components_draw_from_schematic_tables(self):
        dc = DirectionalCoupler(coupling_length=60.0, transition_length=12.0)
        # schematic coupling region shortened to ~70%; freed length became straight access stubs
        assert dc.geometry_2d()["children"][0]["w"] == pytest.approx(20.0)
        assert DirectionalCoupler(coupling_length=60.0, transition_length=12.0, render_physical=True).geometry_2d()["children"][0]["w"] == pytest.approx(60.0)

    def test_mzi_coupler_ends_match_directional_coupler(self):
        # the MZI composes the DirectionalCoupler and now splits its coupler with the
        # same proportions, so its coupler ends carry matching straight access stubs
        dc = MZI(arm_length=40.0, coupler_length=30.0)._directional_coupler()
        assert dc.straight_length == pytest.approx(30.0 * 4.0 / 44.0)
        assert dc.transition_length == pytest.approx(30.0 * 8.0 / 44.0)
        assert dc.coupling_length == pytest.approx(30.0 * 20.0 / 44.0)
        assert dc.total_length == pytest.approx(30.0)  # footprint unchanged

    def test_directional_coupler_has_straight_access_stubs(self):
        dc = DirectionalCoupler(coupling_length=10.0, transition_length=5.0, port_spacing=40.0)
        drawn = dc._draw_variant()
        assert drawn.straight_length > 0
        line = drawn._centerline(1.0)
        # the centerline begins/ends with a flat (constant-y) straight section before the bend
        assert line[1][1] == pytest.approx(line[0][1])
        assert line[1][0] > line[0][0]
        assert line[-2][1] == pytest.approx(line[-1][1])
        # the footprint / ports are unchanged (the freed coupling length stays inside)
        xs = [p.center.x for p in dc.ports().values()]
        assert max(xs) - min(xs) == pytest.approx(44.0)

        mzi = MZI(arm_length=180.0, coupler_length=60.0)
        assert mzi.geometry_2d()["children"][0]["w"] == pytest.approx(28.0)
        assert MZI(arm_length=180.0, coupler_length=60.0, render_physical=True).geometry_2d()["children"][0]["w"] == pytest.approx(60.0)

        bank = MicroringWeightBank(ring_count=3, ring_pitch=75.0, ring_radius=20.0)
        assert _geometry_width(bank.geometry_2d()["children"][0]) == pytest.approx(140.4)   # bus drawn 1.2 wide
        physical_bank = MicroringWeightBank(ring_count=3, ring_pitch=75.0, ring_radius=20.0, render_physical=True)
        assert _geometry_width(physical_bank.geometry_2d()["children"][0]) == pytest.approx(247.4)

    def test_array_and_mzm_default_draws_are_schematic_scaled(self):
        array = GratingCouplerArray(count=3, pitch=250.0)
        stub_xs = [child["x1"] for child in array.geometry_2d()["children"] if child.get("type") == "line"]
        # Drawn pitch is the compacted schematic pitch (45µm), not the 250µm physical pitch.
        assert sorted(stub_xs) == pytest.approx([-45.0, 0.0, 45.0])
        physical_array = GratingCouplerArray(count=3, pitch=250.0, render_physical=True)
        physical_stub_xs = [child["x1"] for child in physical_array.geometry_2d()["children"] if child.get("type") == "line"]
        assert sorted(physical_stub_xs) == pytest.approx([-250.0, 0.0, 250.0])

        mzm = MZM(arm_length=180.0, coupler_length=60.0, electrode_width=8.0)
        physical_mzm = MZM(arm_length=180.0, coupler_length=60.0, electrode_width=8.0, render_physical=True)
        assert _geometry_width(mzm.geometry_2d()) < _geometry_width(physical_mzm.geometry_2d()) * 0.5

    def test_waveguide_ports_sit_on_the_drawn_ends(self):
        """A port is where the drawing ends, so a route always meets the part.

        The ports used to stay at the physical length (+/-10) while the part
        was drawn 24 long, so a route ended 2 units inside the drawing. They
        follow the drawing now; ``render_physical=True`` gives both back.
        """
        wg = Waveguide(length=20.0, width=0.5)
        geo = wg.geometry_2d()
        assert geo["w"] == pytest.approx(24.0)
        assert geo["h"] == pytest.approx(1.2)
        assert wg.ports()["o2"].center.x == pytest.approx(geo["w"] / 2.0)
        assert wg.ports()["o1"].center.x == pytest.approx(-geo["w"] / 2.0)
        assert wg.ports()["o2"].width == pytest.approx(geo["h"])
        assert wg.physical_spec()["length"] == pytest.approx(20.0)   # the physical value is still recorded

        physical = Waveguide(length=20.0, width=0.5, render_physical=True)
        assert physical.ports()["o2"].center.x == pytest.approx(10.0)
        assert physical.ports()["o2"].width == pytest.approx(0.5)

    def test_render_physical_uses_true_footprint(self):
        wg = Waveguide(length=20.0, width=0.5, render_physical=True)
        geo = wg.geometry_2d()
        assert geo["w"] == pytest.approx(20.0)
        assert geo["h"] == pytest.approx(0.5)

    def test_physical_spec_records_pdk_values(self):
        wg = Waveguide(length=33.0, width=0.48)
        spec = wg.physical_spec()
        assert spec["length"] == pytest.approx(33.0)
        assert spec["width"] == pytest.approx(0.48)

    def test_mmi_body_draw_dims_from_table(self):
        mmi = MMI1x2(body_length=5.5, body_width=2.5, taper_length=10.0)
        assert mmi.body_length == pytest.approx(5.5)
        assert mmi.total_length == pytest.approx(25.5)
        dims = mmi.schematic_dims()
        assert dims["body_length"] == pytest.approx(12.0)

    def test_grating_coupler_port_sits_on_the_drawn_end(self):
        gc = VerticalGratingCoupler(length=40.0, width=26.0, taper_length=16.0)
        assert gc.length == pytest.approx(40.0)
        assert gc.schematic_dims()["length"] == pytest.approx(42.0)
        assert gc.schematic_dims()["width"] == pytest.approx(28.0)
        # the waveguide port is at the end of the 42 long drawing, not of the 40 long device
        assert gc.ports()["o1"].center.x == pytest.approx(-gc.schematic_dims()["length"] / 2.0)

        physical = VerticalGratingCoupler(length=40.0, width=26.0, taper_length=16.0, render_physical=True)
        assert physical.ports()["o1"].center.x == pytest.approx(-physical.length / 2.0)

    def test_microring_ports_use_physical_radius(self):
        ring = MicroringResonator(ring_radius=10.0, gap=0.2)
        assert ring.ring_radius == pytest.approx(10.0)
        # radius stays physical; the bus sits just outside the drawn (fattened) track.
        assert ring.bus_offset_y == pytest.approx(10.0 + ring._geom_gap() + ring._geom_waveguide_width())

    def test_routes_expose_physical_length_metadata(self):
        left = Waveguide(center=(0, 0), length=20, width=0.5)
        right = Waveguide(center=(50, 0), length=20, width=0.5)
        route = route_ports((left, "o2"), (right, "o1"), path_type="manhattan")
        assert route.physical_length_um > 20.0
        assert route.to_dict()["physical_length_um"] == pytest.approx(route.physical_length_um)

    def test_waveguide_3d_uses_schematic_thickness(self):
        wg = Waveguide(length=20.0)
        child = wg.geometry_3d()["children"][0]
        assert child["height"] == pytest.approx(0.55)

    def test_photodetector_port_sits_on_the_drawn_end(self):
        from optodraw.layout import _bounds_from_geometry

        detector = OnChipPhotodetector(length=40.0, width=4.0, taper_length=20.0)

        # the input port is on the left edge of what is drawn (-33), not at the
        # physical start of the taper (-30)
        left_edge = _bounds_from_geometry(detector.geometry_2d())[0]
        assert detector.ports()["o1"].center.x == pytest.approx(left_edge)
        assert detector.ports()["o1"].center.x == pytest.approx(-33.0)
        physical = OnChipPhotodetector(length=40.0, width=4.0, taper_length=20.0, render_physical=True)
        assert physical.ports()["o1"].center.x == pytest.approx(-30.0)
        assert detector.physical_spec()["length"] == pytest.approx(40.0)
        absorber = detector.geometry_2d()["children"][1]
        assert absorber["w"] == pytest.approx(44.0)
        assert absorber["h"] == pytest.approx(5.0)

        physical_absorber = OnChipPhotodetector(
            length=40.0,
            width=4.0,
            taper_length=20.0,
            render_physical=True,
        ).geometry_2d()["children"][1]
        assert physical_absorber["w"] == pytest.approx(40.0)
        assert physical_absorber["h"] == pytest.approx(4.0)

    def test_laser_and_soa_draw_from_schematic_tables(self):
        laser = OnChipLaser(cavity_length=180.0, ridge_width=2.5, output_taper_length=22.0)
        # Port sits on the drawn (compacted) output; render_physical restores physical µm.
        assert laser.ports()["o1"].center.x == pytest.approx(40.0)      # a compact figure: shorter than an MZM
        laser_phys = OnChipLaser(cavity_length=180.0, ridge_width=2.5, output_taper_length=22.0, render_physical=True)
        assert laser_phys.ports()["o1"].center.x == pytest.approx(laser.total_length / 2.0)
        assert laser.geometry_2d()["children"][0]["w"] == pytest.approx(64.0)
        assert OnChipLaser(cavity_length=180.0, render_physical=True).geometry_2d()["children"][0]["w"] == pytest.approx(180.0)

        soa = SOA(amplifier_length=70.0, taper_length=10.0, ridge_width=1.8)
        assert soa.ports()["o1"].center.x == pytest.approx(-45.0)
        assert soa.geometry_2d()["children"][1]["w"] == pytest.approx(180.0)
        assert SOA(amplifier_length=70.0, render_physical=True).geometry_2d()["children"][1]["w"] == pytest.approx(70.0)

    @pytest.mark.parametrize(
        ("component", "physical_length", "schematic_length"),
        [
            (TIA(), 28.0, 36.0),
            (DACDriver(), 34.0, 42.0),
            (ADC(), 32.0, 42.0),
        ],
    )
    def test_electronic_io_draw_from_schematic_tables(self, component, physical_length, schematic_length):
        assert component.geometry_2d()["children"][0]["w"] == pytest.approx(schematic_length)
        assert component.physical_spec()["length"] == pytest.approx(physical_length)
        assert component.__class__(render_physical=True).geometry_2d()["children"][0]["w"] == pytest.approx(physical_length)

    def test_onchip_system_primitives_have_ports_and_metadata(self):
        bank = OpticalIOBank(count=4, pitch=127.0, with_fibers=True, side="left")
        # Ports track the drawn (schematic-pitch) bank; render_physical restores the 127µm pitch.
        assert bank.ports()["o4"].center.y == pytest.approx(45.0)
        assert OpticalIOBank(count=4, pitch=127.0, side="left", render_physical=True).ports()["o4"].center.y == pytest.approx(190.5)
        assert bank.ports()["f1"].kind == "fiber"
        assert bank.geometry_2d()["children"]

        awg = AWG(channel_count=5, array_count=12, center_wavelength_nm=1310.0)
        ports = awg.ports()
        assert ports["i1"].orientation_deg == pytest.approx(180.0)
        # o5 topmost, o1 bottom, o3 on the optical axis with the input. The fan
        # is NOT mirror symmetric about that axis and cannot be: the AWG is
        # built from the router's tilted star couplers now, so the channels are
        # evenly spaced along a tilted arc and their projection onto y is not.
        channel_y = [ports[f"o{i}"].center.y for i in range(1, 6)]
        assert channel_y == sorted(channel_y), "o1 at the bottom through o5 at the top"
        # o3 on the optical axis of the input aperture; the input guide then bends into i1 (one 10 um bend), so i1
        # sits less than a bend radius below that axis
        assert 0.0 <= ports["o3"].center.y - ports["i1"].center.y < 10.0
        assert channel_y[0] < 0.0 < channel_y[-1]
        # y=0 is the input aperture, not the middle of the part: the arm bundle
        # climbs above both horns, so the drawn box is not centred on the
        # placement point. Scene.content_bounds reads that box rather than
        # assuming a centred one, which is what keeps the part in frame.
        from optodraw.layout import _bounds_from_geometry
        box = _bounds_from_geometry(awg.geometry_2d())
        assert box[1] < channel_y[0] and channel_y[-1] < box[3]
        assert box[3] > -box[1], "the arms sit above the couplers"
        # Each channel launches along its own arc normal, never a flat 0.
        assert len({round(ports[f"o{i}"].orientation_deg, 3) for i in range(1, 6)}) == 5
        assert awg.physics_metadata()["center_wavelength_nm"] == pytest.approx(1310.0)

        grating = BraggGrating(length=240.0, period=0.3, reflectivity=0.72)
        assert grating.grating_count == 800
        assert grating.physics_metadata()["reflectivity"] == pytest.approx(0.72)

    def test_system_primitives_draw_schematic_not_physical_by_default(self):
        bank = OpticalIOBank(count=3, pitch=250.0)
        physical_bank = OpticalIOBank(count=3, pitch=250.0, render_physical=True)
        assert _geometry_height(bank.geometry_2d()) == pytest.approx(72.0)
        assert _geometry_height(physical_bank.geometry_2d()) > 500.0

        # Compressed by DEFAULT is the claim, so the default is what to compare:
        # 181 units schematic against 420 physical. Asking for a dimension
        # explicitly is a different question, and the answer changed: the
        # schematic table is a family default now, not an override, so a caller
        # who passes slab_length sees it. Two AWGs given different dimensions
        # used to draw identically, which is what this assertion was accepting.
        assert _geometry_width(AWG().geometry_2d()) < _geometry_width(
            AWG(render_physical=True).geometry_2d()) * 0.7
        # The regression that matters: two AWGs given different dimensions must
        # not draw the same picture. A mux and a demux asking for different
        # slabs used to come out identical, because the table replaced both.
        mux = AWG(channel_spacing=10.0, slab_length=18.0, slab_width=32.0, array_length=32.0)
        demux = AWG(channel_spacing=7.0, slab_length=16.0, slab_width=26.0, array_length=30.0)
        assert _geometry_width(mux.geometry_2d()) != _geometry_width(demux.geometry_2d())
        assert _geometry_width(mux.geometry_2d()) != _geometry_width(AWG().geometry_2d())
