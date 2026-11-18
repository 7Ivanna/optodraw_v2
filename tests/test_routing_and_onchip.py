"""Tests for port-based routing and on-chip photonic components."""

import math

import pytest

from optodraw import (
    Scene,
    Waveguide,
    GratingCouplerArray,
    VerticalGratingCoupler,
    FocusedApodizedGratingCoupler,
    EdgeCoupler,
    MMI1x2,
    MMI1x3,
    MMI1x4,
    MMI2x2,
    MMI2x2PowerSplitter,
    YBranch,
    DirectionalCoupler,
    MicroringResonator,
    PNMicroringModulator,
    MicroringWeightBank,
    RacetrackResonator,
    RacetrackModulator,
    MZI,
    MZM,
    OnChipPhotodetector,
    OnChipLaser,
    SOA,
    TIA,
    DACDriver,
    ADC,
    ElectricalPad,
    GSGProbePad,
    SignalArrow,
    RFDriver,
    Microcontroller,
    MEMSActuator,
    PCB,
    route_ports,
    route_bundle,
    WaveguideRoute,
)


class TestPorts:
    def test_waveguide_uses_generic_pdk_defaults(self):
        wg = Waveguide()
        assert wg.width == pytest.approx(0.5)
        assert wg.bend_radius == pytest.approx(10.0)

    def test_world_port_rotation(self):
        # render_physical: this test is about the transform, so it uses the
        # physical port (10 from the centre); a schematic port sits at 12
        wg = Waveguide(center=(10, 0), angle=90, length=20, width=0.6, render_physical=True)
        port = wg.world_port("o2")
        assert port.center.x == pytest.approx(10.0)
        assert port.center.y == pytest.approx(10.0)
        assert port.orientation_deg == pytest.approx(90.0)

    def test_horizontal_flip_mirrors_world_ports(self):
        wg = Waveguide(length=20, flip_horizontal=True, render_physical=True)
        assert wg.world_port("o1").center.x == pytest.approx(10.0)
        assert wg.world_port("o1").orientation_deg == pytest.approx(0.0)
        assert wg.world_port("o2").center.x == pytest.approx(-10.0)


    def test_microring_add_drop_ports(self):
        ring = MicroringResonator(add_drop=True)
        ports = ring.ports()
        assert set(ports) == {"o1", "o2", "o3", "o4"}

    def test_mzm_has_electrical_ports(self):
        mod = MZM()
        ports = mod.ports()
        # GS: one signal + one ground probe pad (kind="electrical", off the bars)
        assert "sig" in ports and "gnd" in ports
        assert ports["sig"].kind == "electrical"

    def test_mzm_gsg_has_dual_arm_electrical_ports(self):
        mod = MZM(drive_style="gsg")
        ports = mod.ports()
        # GSG: ground-signal-ground probe pads
        assert {"gnd1", "sig", "gnd2"}.issubset(ports)
        assert ports["sig"].center.y == pytest.approx(0.0)
        assert ports["gnd2"].kind == "electrical"

    def test_mzm_thermo_optic_uses_heater_ports(self):
        mod = MZM(mechanism="thermo_optic")
        ports = mod.ports()
        # thermo-optic phase shift exposes heater pads (like the MZI), no RF pads
        assert {"h1", "h2"}.issubset(ports)
        assert ports["h1"].kind == "electrical"
        assert "sig" not in ports and "gnd" not in ports

    def test_ybranch_has_three_ports(self):
        splitter = YBranch()
        assert set(splitter.ports()) == {"o1", "o2", "o3"}

    def test_directional_coupler_has_four_ports(self):
        coupler = DirectionalCoupler()
        assert set(coupler.ports()) == {"o1", "o2", "o3", "o4"}

    def test_ybranch_matches_segmented_design_default_offset(self):
        splitter = YBranch(branch_length=9.0, stem_length=1.0, branch_gap=None)
        ports = splitter.ports()
        assert ports["o2"].center.y == pytest.approx(2.35, rel=1e-3)
        assert ports["o3"].center.y == pytest.approx(-2.35, rel=1e-3)

    def test_mzm_preserves_centerline_io_ports(self):
        mod = MZM()
        ports = mod.ports()
        assert ports["o1"].center.y == pytest.approx(0.0)
        assert ports["o3"].center.y == pytest.approx(0.0)

    def test_onchip_laser_has_optical_and_electrical_ports(self):
        laser = OnChipLaser()
        ports = laser.ports()
        assert "o1" in ports
        assert ports["e1"].kind == "electrical"

    def test_new_mmi_variants_have_expected_port_counts(self):
        assert set(MMI1x3().ports()) == {"o1", "o2", "o3", "o4"}
        assert set(MMI1x4().ports()) == {"o1", "o2", "o3", "o4", "o5"}
        assert set(MMI2x2PowerSplitter().ports()) == {"o1", "o2", "o3", "o4"}

    def test_pn_microring_exposes_electrical_ports(self):
        ring = PNMicroringModulator()
        ports = ring.ports()
        assert ports["e1"].kind == "electrical"
        assert ports["e2"].kind == "electrical"
        assert ports["h1"].kind == "electrical"
        assert ports["h2"].kind == "electrical"

    def test_pn_microring_add_drop_excludes_coupler_arcs(self):
        ring = PNMicroringModulator(add_drop=True)
        for start, end in ring._active_arc_ranges():
            assert (-90.0 < start and end < 90.0) or (90.0 < start and end < 270.0)

    def test_edge_coupler_has_fiber_and_optical_ports(self):
        coupler = EdgeCoupler(with_fiber=True)
        ports = coupler.ports()
        assert ports["f1"].kind == "fiber"
        assert ports["o1"].kind == "optical"

    def test_weight_bank_has_drop_and_heater_ports(self):
        bank = MicroringWeightBank(ring_count=3, with_heaters=True)
        ports = bank.ports()
        assert {"o1", "o2", "d1", "d2", "d3"}.issubset(ports)
        assert {"e1", "e2", "e3", "e4", "e5", "e6"}.issubset(ports)

    def test_racetrack_modulator_has_drop_and_electrical_ports(self):
        mod = RacetrackModulator()
        ports = mod.ports()
        assert {"o1", "o2", "o3", "o4", "e1", "e2"}.issubset(ports)

    def test_soa_has_optical_and_electrical_ports(self):
        soa = SOA()
        ports = soa.ports()
        assert ports["o1"].kind == "optical"
        assert ports["e1"].kind == "electrical"

    def test_mixed_signal_blocks_expose_electrical_ports(self):
        assert set(TIA().ports()) == {"e1", "e2"}
        assert set(DACDriver().ports()) == {"e1", "e2", "e3", "e4"}
        assert set(ADC().ports()) == {"e1", "e2", "e3"}

    def test_generic_electronics_primitives_expose_electrical_ports(self):
        pad = ElectricalPad(port_side="right", width=30, height=24)
        gsg = GSGProbePad(port_side="left")
        arrow = SignalArrow(signal="rf")

        assert pad.ports()["e1"].kind == "electrical"
        assert pad.ports()["e1"].orientation_deg == pytest.approx(0.0)
        assert set(gsg.ports()) == {"g1", "s", "g2"}
        assert arrow.ports()["out"].kind == "electrical"

    def test_generic_electronics_primitives_have_renderable_geometry(self):
        assert ElectricalPad().geometry_2d()["type"] == "group"
        assert GSGProbePad().geometry_3d()["shape"] == "group"
        assert SignalArrow().geometry_2d()["type"] == "group"

    def test_system_electronics_components_expose_ports(self):
        assert {"in", "out_p", "out_n", "bias", "gnd"}.issubset(RFDriver().ports())
        assert Microcontroller().ports()["gpio1"].kind == "electrical"
        assert MEMSActuator().ports()["e1"].kind == "electrical"
        assert set(PCB(pad_count=2).ports()) == {"e1", "e2", "e3", "e4"}

    def test_system_electronics_components_have_1d_2d_3d_visuals(self):
        components = [RFDriver, Microcontroller, MEMSActuator, PCB]
        for component_cls in components:
            assert component_cls(visual_style="symbolic").geometry_2d()["type"] == "group"
            assert component_cls().geometry_2d()["type"] == "group"
            assert component_cls().geometry_3d()["shape"] == "group"
        assert RFDriver(visual_scale=2.0).ports()["in"].center.x == pytest.approx(-38.0)


class TestRouting:
    def test_route_ports_between_waveguides(self):
        left = Waveguide(center=(0, 0), length=20, width=0.5)
        right = Waveguide(center=(50, 10), length=20, width=0.5)
        route = route_ports((left, "o2"), (right, "o1"), path_type="manhattan")
        pts = route.resolve_points()
        assert isinstance(route, WaveguideRoute)
        assert pts[0][0] == pytest.approx(left.world_port("o2").center.x)
        assert pts[-1][0] == pytest.approx(right.world_port("o1").center.x)
        assert len(pts) >= 4

    def test_optical_routes_use_gdsfactory_backend(self):
        pytest.importorskip("gdsfactory")
        left = Waveguide(center=(0, 0), length=20, width=0.5)
        right = Waveguide(center=(50, 10), length=20, width=0.5)
        route = route_ports((left, "o2"), (right, "o1"), path_type="manhattan")
        assert route.backend == "gdsfactory"
        assert route.smooth is True

    def test_route_ports_with_steps(self):
        left = Waveguide(center=(0, 0), length=20)
        right = Waveguide(center=(60, 20), length=20)
        route = route_ports(
            (left, "o2"),
            (right, "o1"),
            steps=[{"x": 25, "dy": 5}, {"y": 30}],
        )
        pts = route.resolve_points()
        assert any(point[0] == pytest.approx(25.0) for point in pts)
        assert any(point[1] == pytest.approx(30.0) for point in pts)

    def test_electrical_routes_stay_local(self):
        left = MZM(center=(0, 0))
        right = MZM(center=(90, 0))
        route = route_ports((left, "gnd"), (right, "sig"), kind="electrical")
        assert route.backend == "local"
        assert route.smooth is False

    def test_waypoint_route_runs_orthogonally(self):
        from optodraw.core.ports import Port
        from optodraw.core.transform import Vec3

        p1 = Port("a", Vec3(0, 0, 0), orientation_deg=0)
        p2 = Port("b", Vec3(100, 40, 0), orientation_deg=180)
        # a loosely placed (diagonal) waypoint must still route in pure L/R/U/D segments
        route = route_ports(p1, p2, path_type="manhattan", steps=[{"x": 50.0, "y": 20.0}])
        for a, b in zip(route.points, route.points[1:]):
            assert abs(a.x - b.x) < 1e-6 or abs(a.y - b.y) < 1e-6
        # 'manual' is the escape hatch that keeps the exact (possibly diagonal) points
        manual = route_ports(p1, p2, path_type="manual", steps=[{"x": 50.0, "y": 20.0}])
        assert any(abs(a.x - b.x) > 1e-6 and abs(a.y - b.y) > 1e-6 for a, b in zip(manual.points, manual.points[1:]))

    def test_electrical_routes_connect_generic_pads(self):
        driver = GSGProbePad(center=(-30, 0), port_side="right")
        pad = ElectricalPad(center=(30, 0), port_side="left")
        route = route_ports((driver, "s"), (pad, "e1"), kind="electrical", width=2.0)
        assert route.kind == "electrical"
        assert route.backend == "local"
        assert route.width == pytest.approx(2.0)

    def test_electrical_routes_connect_system_blocks(self):
        controller = Microcontroller(center=(-50, 0))
        driver = RFDriver(center=(0, 0))
        mems = MEMSActuator(center=(50, 0))
        pcb = PCB(center=(0, -45), pad_count=2)
        routes = [
            route_ports((controller, "gpio2"), (driver, "in"), kind="electrical"),
            route_ports((driver, "out_p"), (mems, "e1"), kind="electrical"),
            route_ports((pcb, "e3"), (controller, "usb"), kind="electrical"),
        ]
        assert all(route.kind == "electrical" for route in routes)

    def test_route_bundle_sorts_ports(self):
        left = MMI2x2(center=(0, 0))
        right = MMI2x2(center=(80, 20))
        routes = route_bundle(
            [(left, "o3"), (left, "o4")],
            [(right, "o2"), (right, "o1")],
            separation=4.0,
            sort_ports=True,
        )
        assert len(routes) == 2
        end_points = [route.resolve_points()[-1][1] for route in routes]
        assert end_points[0] < end_points[1]

    def test_scene_route_helpers(self):
        scene = Scene(title="On-chip", platform="on_chip", width=200, height=120)
        left = scene.add(Waveguide(center=(-40, 0), length=20))
        right = scene.add(Waveguide(center=(40, 15), length=20))
        route = scene.route((left, "o2"), (right, "o1"), path_type="smooth")
        assert route in list(scene.walk())
        assert getattr(route, "smooth", False) is True

    def test_facing_ports_enter_face_on_not_from_behind(self):
        from optodraw.core.ports import Port
        from optodraw.core.transform import Vec3

        # ports facing each other, aligned → straight line that never overshoots port2
        p1 = Port("a", Vec3(0, 0, 0), orientation_deg=0)
        p2 = Port("b", Vec3(60, 0, 0), orientation_deg=180)
        pts = route_ports(p1, p2, path_type="manhattan", kind="waveguide", backend="local").points
        assert max(p.x for p in pts) <= 60 + 1e-6  # no overshoot/back-entry

    def test_smooth_path_is_sbend_not_manhattan_zigzag(self):
        from optodraw.core.ports import Port
        from optodraw.core.transform import Vec3

        p1 = Port("a", Vec3(0, 0, 0), orientation_deg=0)
        p2 = Port("b", Vec3(80, 30, 0), orientation_deg=180)
        pts = route_ports(p1, p2, path_type="smooth", kind="waveguide", backend="local").points
        # a real S-bend has slanted (curved) segments, not a pure right-angle zig-zag
        assert any(abs(pts[i + 1].x - pts[i].x) > 1e-6 and abs(pts[i + 1].y - pts[i].y) > 1e-6 for i in range(len(pts) - 1))


class TestOnChipComponents:
    def test_two_input_mzm_uses_coupler_io(self):
        from optodraw.components.onchip.modulators import MZM

        m = MZM(splitter="coupler", drive_style="gsg")
        p = m.ports()
        # a 2×2 coupler exposes two left inputs (both facing left, off-axis), not one
        assert p["o1"].orientation_deg == 180 and p["o2"].orientation_deg == 180
        assert abs(p["o1"].center.y) > 1e-6 and abs(p["o2"].center.y) > 1e-6
        assert MZM(splitter="ybranch").ports()["o2"].orientation_deg == 90  # tap, not an input

    def test_spiral_delay_line(self):
        from optodraw import Spiral

        sp = Spiral(turns=2.0, spacing=6.0)
        assert set(sp.ports()) == {"o1", "o2"}
        o1, o2 = sp.ports()["o1"], sp.ports()["o2"]
        assert o1.center.x != o2.center.x  # leads routed to opposite sides
        assert o1.orientation_deg == 0 and o2.orientation_deg == 180  # o1 exits right, o2 left
        assert sp.physical_spec()["delay_length"] > 80.0  # winds into a long path

    def test_phase_shifter_thermo_and_electro(self):
        from optodraw import PhaseShifter

        thermo = PhaseShifter(mechanism="thermo_optic")
        electro = PhaseShifter(mechanism="electro_optic")
        assert {"o1", "o2", "h1", "h2"} == set(thermo.ports())
        assert {"o1", "o2", "e1", "e2"} == set(electro.ports())
        assert electro.ports()["e1"].kind == "electrical"

    def test_component_geometries(self):
        assert Waveguide().geometry_2d()["type"] == "rect"
        assert VerticalGratingCoupler().geometry_2d()["type"] == "group"
        assert FocusedApodizedGratingCoupler().geometry_2d()["type"] == "group"
        assert EdgeCoupler().geometry_2d()["type"] == "group"
        assert MMI1x2().geometry_2d()["type"] == "group"
        assert MMI1x3().geometry_2d()["type"] == "group"
        assert MMI1x4().geometry_2d()["type"] == "group"
        assert MMI2x2PowerSplitter().geometry_2d()["type"] == "group"
        assert YBranch().geometry_2d()["type"] == "group"
        assert DirectionalCoupler().geometry_3d()["shape"] == "group"
        assert MicroringResonator().geometry_3d()["shape"] == "group"
        assert PNMicroringModulator().geometry_3d()["shape"] == "group"
        assert MicroringWeightBank().geometry_3d()["shape"] == "group"
        assert RacetrackResonator().geometry_3d()["shape"] == "group"
        assert RacetrackModulator().geometry_3d()["shape"] == "group"
        assert MZI().geometry_3d()["shape"] == "group"
        assert MZM(drive_style="gsg").geometry_3d()["shape"] == "group"
        assert OnChipPhotodetector().geometry_3d()["shape"] == "group"
        assert OnChipLaser().geometry_3d()["shape"] == "group"
        assert SOA().geometry_3d()["shape"] == "group"
        assert TIA().geometry_3d()["shape"] == "group"
        assert DACDriver().geometry_3d()["shape"] == "group"
        assert ADC().geometry_3d()["shape"] == "group"

    def test_ybranch_uses_segmented_junction_polygon_and_3d_extrusion(self):
        splitter = YBranch()
        geo2d = splitter.geometry_2d()
        geo3d = splitter.geometry_3d()
        assert geo2d["children"][1]["type"] == "polygon"
        assert geo3d["children"][1]["shape"] == "extruded_polygon"

    def test_directional_coupler_uses_s_bend_polygons(self):
        coupler = DirectionalCoupler()
        geo2d = coupler.geometry_2d()
        geo3d = coupler.geometry_3d()
        assert sum(child.get("type") == "polygon" for child in geo2d["children"]) == 2
        assert all(child.get("shape") == "extruded_polygon" for child in geo3d["children"])

    def test_mzi_uses_extruded_directional_coupler_geometry(self):
        geo3d = MZI().geometry_3d()
        assert any(child.get("shape") == "extruded_polygon" for child in geo3d["children"])

    def test_mzm_uses_ybranch_splitters_and_pin_section(self):
        mod = MZM()
        geo2d = mod.geometry_2d()
        fills = {child.get("fill") for child in geo2d["children"]}
        assert "#4f94c6" in fills
        assert "#d4af37" in fills
        assert any(child.get("type") == "polygon" for child in geo2d["children"])

    def test_mzm_gs_rails_clear_the_active_slab(self):
        mod = MZM()
        metrics = mod._active_metrics()
        upper_y = mod.arm_gap / 2.0
        assert mod.ports()["sig"].center.y > upper_y + metrics["slab_width"] / 2.0
        assert mod.ports()["gnd"].center.y < upper_y - metrics["slab_width"] / 2.0

    def test_mzm_gsg_uses_dual_active_arms_and_center_signal_rail(self):
        mod = MZM(drive_style="gsg")
        geo2d = mod.geometry_2d()
        slab_boxes = [child for child in geo2d["children"] if child.get("type") == "rect" and child.get("fill") == "#4f94c6"]
        gold_polygons = [child for child in geo2d["children"] if child.get("fill") == "#d4af37" and child.get("points")]
        draw_arm_gap = mod.schematic_dims()["arm_gap"]
        assert any(child.get("cy") == pytest.approx(draw_arm_gap / 2.0) for child in slab_boxes)
        assert any(child.get("cy") == pytest.approx(-draw_arm_gap / 2.0) for child in slab_boxes)
        assert len(gold_polygons) == 3  # G-S-G: one metal polygon per terminal
        straddling = [  # the centre signal conductor bridges UP and DOWN to both arms
            poly for poly in gold_polygons
            if min(pt[1] for pt in poly["points"]) < 0.0 < max(pt[1] for pt in poly["points"])
        ]
        assert len(straddling) == 1

    def test_microring_heater_is_one_unified_metal_polygon(self):
        # arc + leads + pads trace ONE closed outline (a single fabricated part),
        # not a pile of butted pieces; the copper vias stay separate
        ring = MicroringResonator(add_drop=True, with_heater=True)
        children = ring.geometry_2d()["children"]
        gold_shapes = [child for child in children if child.get("fill") == "#d4af37"]
        assert len(gold_shapes) == 1
        assert len(gold_shapes[0]["points"]) > 100  # both arcs + both pads in one loop
        vias = [child for child in children if child.get("fill") == "#f08c6d"]
        assert len(vias) == 2

    def test_mzi_heater_is_one_unified_metal_polygon(self):
        # same rule as the rings: bar + full-width leads + both pads trace ONE
        # closed outline, with the copper vias sitting separately on the pads
        gold = [c for c in MZI().geometry_2d()["children"] if c.get("fill") == "#d4af37"]
        assert len(gold) == 1
        vias = [c for c in MZI().geometry_2d()["children"] if c.get("fill") == "#f08c6d"]
        assert len(vias) == 2

    def test_thermo_optic_mzm_heater_is_one_unified_metal_polygon(self):
        gold = [c for c in MZM(mechanism="thermo_optic").geometry_2d()["children"] if c.get("fill") == "#d4af37"]
        assert len(gold) == 1

    def test_mzi_heater_pads_carry_the_electrical_ports(self):
        mzi = MZI()
        polygon = next(c for c in mzi.geometry_2d()["children"] if c.get("fill") == "#d4af37")
        xs = [p[0] for p in polygon["points"]]
        ys = [p[1] for p in polygon["points"]]
        for name in ("h1", "h2"):
            port = mzi.ports()[name]
            assert min(xs) <= port.center.x <= max(xs)  # the pad the port lands on
            assert min(ys) <= port.center.y <= max(ys)  # is part of the same metal

    def test_rf_electrodes_are_one_polygon_per_terminal(self):
        # signal and ground stay SEPARATE nets (merging them would short the
        # modulator), but each terminal's rail + bridges + feed + pad is one part
        for style, terminals in (("gs", 2), ("gsg", 3)):
            mod = MZM(drive_style=style)
            gold = [c for c in mod.geometry_2d()["children"] if c.get("fill") == "#d4af37"]
            assert len(gold) == terminals, style

    def test_photodetector_has_three_top_contact_fingers(self):
        detector = OnChipPhotodetector()
        gold_shapes = [child for child in detector.geometry_2d()["children"] if child.get("fill") == "#d4af37"]
        assert len(gold_shapes) >= 5

    def test_default_photodetector_takes_the_waveguide_from_the_west(self):
        # angle=0 is the detector convention: o1 on the west face at 180°.
        # angle=180 is the *grating coupler input* convention; copying it onto
        # a PD puts o1 on the east face and the route loops around the body.
        detector = OnChipPhotodetector(center=(80.0, 0.0))
        port = detector.world_port("o1")
        assert port.orientation_deg == pytest.approx(180.0)
        assert port.center.x < detector.transform.position.x

        scene = Scene(title="", width=400, height=200, platform="on_chip")
        gc = scene.add(VerticalGratingCoupler(center=(0.0, 0.0), angle=180, label="GC"))
        pd = scene.add(OnChipPhotodetector(center=(120.0, 0.0), label="PD"))
        route = scene.route((gc, "o1"), (pd, "o1"), kind="waveguide", path_type="smooth")
        xs = [point.x for point in route.points]
        pd_port_x = pd.world_port("o1").center.x
        assert max(xs) <= pd_port_x + 1.0

    def test_grating_coupler_has_one_waveguide_port_and_a_fibre_port_over_its_teeth(self):
        # The chip-side waveguide, and the fibre port where the light leaves the chip: without it a
        # fibre routed to the coupler landed at the taper end, not on the grating.
        gc = VerticalGratingCoupler()
        assert set(gc.ports()) == {"o1", "f1"}
        assert gc.ports()["o1"].kind == "optical" and gc.ports()["f1"].kind == "fiber"

    def test_grating_coupler_array_exposes_ordered_ports(self):
        # Upright orientation: one waveguide port per coupler, exits downward (270°),
        # and one fibre port above the same coupler, so a FiberRoute has a place to land.
        gc_array = GratingCouplerArray(count=6, pitch=127.0)
        ports = gc_array.ports()
        assert {name for name, port in ports.items() if port.kind == "optical"} == {f"o{i}" for i in range(1, 7)}
        assert {name for name, port in ports.items() if port.kind == "fiber"} == {f"f{i}" for i in range(1, 7)}
        for i in range(1, 7):                    # fibre i sits over waveguide port i and faces up
            assert ports[f"f{i}"].center.x == pytest.approx(ports[f"o{i}"].center.x)
            assert ports[f"f{i}"].center.y > ports[f"o{i}"].center.y
            assert ports[f"f{i}"].orientation_deg == pytest.approx(90.0)
        # Drawn pitch is compacted for legibility; render_physical restores the 127µm fiber pitch.
        assert ports["o2"].center.x - ports["o1"].center.x == pytest.approx(45.0)
        phys = GratingCouplerArray(count=6, pitch=127.0, render_physical=True).ports()
        assert phys["o2"].center.x - phys["o1"].center.x == pytest.approx(127.0)
        # Array is centered: leftmost + rightmost X sum to zero
        assert ports["o1"].center.x + ports["o6"].center.x == pytest.approx(0.0)
        assert ports["o1"].orientation_deg == pytest.approx(270.0)

    def test_grating_coupler_array_stub_exits_downward_before_bend(self):
        # Each o-port sits at the tip of a downward stub below the coupler body.
        gc_array = GratingCouplerArray(count=2, pitch=127.0, stub_length=12.0)
        ports = gc_array.ports()
        geo2d = gc_array.geometry_2d()
        stubs = [c for c in geo2d["children"] if c.get("type") == "line"]
        assert len(stubs) == 2
        for stub in stubs:
            assert stub["x1"] == pytest.approx(stub["x2"])  # vertical
            assert stub["y2"] < stub["y1"]                  # downward
        # o-port sits at the bottom (tip) of its stub
        assert ports["o1"].center.y == pytest.approx(min(stubs[0]["y1"], stubs[0]["y2"]))

    def test_grating_coupler_array_adds_end_alignment_loop_when_enabled(self):
        gc_array = GratingCouplerArray(count=4, pitch=100.0, align_ends=True, alignment_drop=28.0)
        geo2d = gc_array.geometry_2d()
        polylines = [child for child in geo2d["children"] if child.get("type") == "polyline"]
        assert polylines
        loop = polylines[-1]
        assert len(loop.get("points", [])) == 4

        draw_pitch = gc_array.schematic_dims()["pitch"]
        left = -1.5 * draw_pitch
        right = 1.5 * draw_pitch
        # U-loop starts one stub below the coupler's REAL o1 port (stubs anchor
        # to the port, not an assumed centered body length — the focused coupler
        # has no `length` and the old fallback opened a gap).
        stub_y = VerticalGratingCoupler().ports()["o1"].center.x - gc_array.schematic_dims()["stub_length"]
        pts = loop["points"]
        assert pts[0][0] == pytest.approx(left)
        assert pts[-1][0] == pytest.approx(right)
        assert pts[0][1] == pytest.approx(stub_y)
        # Bottom of the U is alignment_drop below the stub tip
        assert pts[1][1] == pytest.approx(stub_y - 28.0)

    def test_grating_coupler_array_rejects_invalid_configuration(self):
        with pytest.raises(ValueError):
            GratingCouplerArray(count=0).ports()
        with pytest.raises(ValueError):
            GratingCouplerArray(count=1, align_ends=True).ports()

    def test_focused_grating_coupler_has_single_waveguide_port(self):
        gc = FocusedApodizedGratingCoupler()
        ports = gc.ports()
        assert [name for name, port in ports.items() if port.kind == "optical"] == ["o1"]
        # the fibre side is a port too, of its own kind, so it cannot be wired as a waveguide
        assert [name for name, port in ports.items() if port.kind == "fiber"] == ["f1"]
        assert set(ports) == {"o1", "f1"}

    def test_optional_fiber_visuals_are_rendered(self):
        vertical = VerticalGratingCoupler(with_fiber=True).geometry_2d()
        focused = FocusedApodizedGratingCoupler(with_fiber=True).geometry_2d()
        edge = EdgeCoupler(with_fiber=True).geometry_2d()
        edge_default = EdgeCoupler(with_fiber=False).geometry_2d()
        vertical_circles = [child for child in vertical["children"] if child.get("type") == "circle"]
        focused_circles = [child for child in focused["children"] if child.get("type") == "circle"]
        assert len(vertical_circles) == 2
        assert len(focused_circles) == 2
        assert len(edge["children"]) == len(edge_default["children"]) + 1
        assert edge["children"][-1].get("type") == "rect"

    def test_grating_fiber_visuals_have_core_and_cladding_in_3d(self):
        vertical = VerticalGratingCoupler(with_fiber=True).geometry_3d()
        focused = FocusedApodizedGratingCoupler(with_fiber=True).geometry_3d()
        assert sum(child.get("shape") == "cylinder" for child in vertical["children"]) == 2
        assert sum(child.get("shape") == "cylinder" for child in focused["children"]) == 2

    def test_microring_heater_uses_elevated_metal_stack(self):
        ring = MicroringResonator(with_heater=True)
        gold_children = [child for child in ring.geometry_3d()["children"] if child.get("material", {}).get("preset") == "gold"]
        assert gold_children
        assert all(child["position"][1] > ring.chip_thickness for child in gold_children if "position" in child)

    def test_pn_microring_has_implant_and_contact_colors(self):
        ring = PNMicroringModulator(add_drop=True)
        fills = {child.get("fill") for child in ring.geometry_2d()["children"]}
        assert {"#f4b4b4", "#b7cdf2", "#d4af37", "#f08c6d"} <= fills     # p, n, gold, vias (2026-10-04 redesign)

    def test_pn_microring_contacts_carry_vias(self):
        ring = PNMicroringModulator(add_drop=True)
        vias = [c for c in ring.geometry_2d()["children"] if c.get("fill") == "#f08c6d"]
        assert len(vias) >= 6

    def test_weight_bank_bends_drop_outputs_to_shared_bus(self):
        bank = MicroringWeightBank(ring_count=3)
        ports = bank.ports()
        # Per-ring drop ports are distributed left→right on the drop bus (NOT stacked at
        # one point), all at the same drop-bus height.
        assert ports["d1"].center.x < ports["d2"].center.x < ports["d3"].center.x
        assert ports["d1"].center.y == pytest.approx(ports["d2"].center.y) == pytest.approx(ports["d3"].center.y)
        # ...and the summed output is read to the right, on the raised output bus.
        assert ports["drop"].center.x > ports["d3"].center.x
        assert ports["drop"].center.y > ports["d1"].center.y
        drop_bus = bank._serial_drop_bus_path()
        output_bus = bank._output_bus_path()
        left_link = bank._left_serial_link_path()
        assert drop_bus[0][0] < bank._ring_centers()[0]
        assert drop_bus[-1][0] == pytest.approx(bank.shared_bus_right_x)
        assert output_bus[0][1] == pytest.approx(bank.output_bus_y)
        assert output_bus[-1][0] == pytest.approx(bank.output_right_x)
        assert left_link[0][1] == pytest.approx(bank.drop_bus_y)
        assert left_link[-1][1] == pytest.approx(bank.output_bus_y)
        assert bank.left_link_vertical_length == pytest.approx(0.0)
        assert not any(abs(p1[0] - p0[0]) < 1e-9 and abs(p1[1] - p0[1]) > 1e-9 for p0, p1 in zip(left_link, left_link[1:]))

    def test_racetrack_modulator_adds_active_and_metal_layers(self):
        geo2d = RacetrackModulator().geometry_2d()
        fills = {child.get("fill") for child in geo2d["children"]}
        assert {"#f4b4b4", "#b7cdf2", "#d4af37", "#c8964a"} <= fills     # p, n, gold, TiN heater

    def test_racetrack_modulator_keeps_its_pn_regions_off_the_coupling_straights(self):
        for add_drop in (True, False):
            mod = RacetrackModulator(coupling_length=24.0, add_drop=add_drop)._draw_variant()
            p_doping, n_doping = mod._doping_polygons()
            assert p_doping and n_doping
            for polygon in p_doping + n_doping:
                assert all(x <= -mod.coupling_length / 2.0 + 1e-6 for x, _ in polygon)

    def test_mzm_uses_slab_backed_metal_routes(self):
        mod = MZM(drive_style="gsg")
        fills = {child.get("fill") for child in mod.geometry_2d()["children"]}
        assert "#9bc5dd" in fills
        assert "#d4af37" in fills

    def test_racetrack_defaults_to_no_side_straights(self):
        ring = RacetrackResonator()
        assert ring.length_y == pytest.approx(0.0)
        assert ring.ring_top_y == pytest.approx(ring.ring_bottom_y + 2.0 * ring.bend_radius)

    def test_racetrack_resonator_uses_piecewise_bends(self):
        ring = RacetrackResonator(coupling_length=24.0, length_y=6.0)
        geo2d = ring.geometry_2d()
        polylines = [child for child in geo2d["children"] if child.get("type") == "polyline"]
        assert len(polylines) == 1
        assert polylines[0].get("closed") is True
        assert len(polylines[0].get("points", [])) > 20
        assert any(point[0] > ring.coupling_length / 2.0 for point in polylines[0]["points"])

    def test_support_blocks_render_expected_materials(self):
        soa_fills = {child.get("fill") for child in SOA().geometry_2d()["children"]}
        assert "#d4af37" in soa_fills
        assert "#f6c9d3" in soa_fills                  # the light III-V mesa (2026-10-04; was a dark #8c5c67 slab)
        assert any(child.get("fill") == "#bcc4d2" for child in TIA().geometry_2d()["children"])
        assert any(child.get("fill") == "#c8ced9" for child in DACDriver().geometry_2d()["children"])
        assert any(child.get("fill") == "#c8ced9" for child in ADC().geometry_2d()["children"])

    def test_onchip_laser_uses_segmented_cavity_and_elevated_metal(self):
        laser = OnChipLaser()
        geo2d = laser.geometry_2d()
        fills = {child.get("fill") for child in geo2d["children"]}
        assert "#f6c9d3" in fills                  # the III-V mesa (light, 2026-10-03; was a dark #5f5256 slab)
        assert "#e893a8" in fills                  # its MQW stripe
        assert "#d4af37" in fills
        gold_children = [child for child in laser.geometry_3d()["children"] if child.get("material", {}).get("preset") == "gold"]
        assert gold_children
        assert any(child["position"][1] > laser.chip_thickness for child in gold_children if "position" in child)


class TestOnChipRendering:
    def test_flipped_component_renders_in_svg_and_threejs(self):
        scene = Scene(title="Flip", platform="on_chip", width=120, height=80)
        scene.add(Waveguide(flip_horizontal=True, flip_vertical=True, length=20))
        svg_text = scene.render_svg().as_svg()
        html = scene.render_threejs()
        assert "scale(-1,-1)" in svg_text
        assert "localScale" in html

    def test_svg_render_with_onchip_components(self):
        scene = Scene(title="Chip", platform="on_chip", width=240, height=120)
        src = scene.add(VerticalGratingCoupler(center=(-80, 0), label="GC_IN"))
        splitter = scene.add(MMI1x2(center=(-30, 0), label="SPL"))
        ring = scene.add(MicroringResonator(center=(30, 0), add_drop=True, label="RING"))
        pd = scene.add(OnChipPhotodetector(center=(90, 15), label="PD"))
        scene.route((src, "o1"), (splitter, "o1"))
        scene.route((splitter, "o2"), (ring, "o1"))
        scene.route((ring, "o2"), (pd, "o1"))
        drawing = scene.render_svg()
        svg_text = drawing.as_svg()
        assert "GC_IN" in svg_text
        assert "RING" in svg_text
        assert "PD" in svg_text

    def test_threejs_render_with_routes(self):
        scene = Scene(title="Chip 3D", platform="on_chip", width=240, height=120)
        left = scene.add(Waveguide(center=(-50, 0), length=20, label="WG1"))
        right = scene.add(MMI2x2(center=(40, 10), label="MMI"))
        scene.route((left, "o2"), (right, "o1"), path_type="manhattan")
        html = scene.render_threejs()
        assert "route" in html
        assert "WG1" in html
        assert "MMI" in html

    def test_threejs_render_with_segmented_ybranch(self):
        scene = Scene(title="YBranch 3D", platform="on_chip", width=120, height=80)
        scene.add(YBranch(center=(0, 0), label="YB"))
        html = scene.render_threejs()
        assert "extruded_polygon" in html
        assert "YB" in html

class TestNewOnChipComponents:
    """Registry round-trip + scene integration for the newly-added on-chip library."""

    NEW = [
        "Taper",
        "WaveguideBend",
        "WaveguideCrossing",
        "Terminator",
        "TapCoupler",
        "AdiabaticCoupler",
        "PolarizationRotator",
        "PolarizationSplitterRotator",
        "TwoDGratingCoupler",
        "ElectroAbsorptionModulator",
        "DBRLaser",
        "AvalanchePhotodetector",
        "EchelleGrating",
    ]

    @pytest.mark.parametrize("name", NEW)
    def test_build_ports_spec_and_geometry(self, name):
        from optodraw.registry import build_component

        comp = build_component(name)
        ports = comp.ports()
        assert ports, f"{name} has no ports"
        assert all(p.center is not None for p in ports.values())
        spec = comp.physical_spec()
        assert spec.device_family == comp.schematic_family
        assert spec["thickness"] > 0
        assert comp.geometry_2d()["type"] == "group"
        assert comp.geometry_3d()["shape"] == "group"

    @pytest.mark.parametrize("name", NEW)
    def test_scene_spec_round_trip(self, name):
        from optodraw.core.scene import Scene
        from optodraw.registry import build_component

        scene = Scene(title=name, platform="on_chip", width=160, height=120)
        scene.add(build_component(name, label="DUT"))
        svg = scene.render_svg().as_svg()
        assert "DUT" in svg
        # round-trips through the editor spec without raising
        assert scene.to_spec()["components"]

    def test_polarization_and_electrical_port_kinds(self):
        from optodraw.registry import build_component

        psr = build_component("PolarizationSplitterRotator")
        assert {"o1", "o2", "o3"} <= set(psr.ports())
        eam = build_component("ElectroAbsorptionModulator")
        kinds = {n: p.kind for n, p in eam.ports().items()}
        assert kinds["e1"] == "electrical" and kinds["o1"] == "optical"


class TestNearCollinearPorts:
    """A hair of misalignment must not cost a dog-leg. Rounding placements onto a
    grid leaves ports a fraction of a unit apart, and the router used to answer a
    0.09 um offset with a path six times longer than the hop itself."""

    def _hop(self, offset):
        from optodraw import MMI1x2, Scene, VerticalGratingCoupler
        from optodraw.core.transform import Vec3
        from optodraw.layout import align_ports

        scene = Scene(width=220, height=120, platform="on_chip")
        gc = scene.add(VerticalGratingCoupler(center=(-70, 0), angle=180))
        mmi = scene.add(MMI1x2())
        align_ports(gc, "o1", mmi, "o1", gap=14.0)
        mmi.transform.position = Vec3(mmi.transform.position.x, mmi.transform.position.y + offset, 0.0)
        route = scene.route((gc, "o1"), (mmi, "o1"), kind="waveguide")
        points = [(float(p[0]), float(p[1])) for p in route.resolve_points()]
        span = math.dist(points[0], points[-1])
        length = sum(math.dist(a, b) for a, b in zip(points, points[1:]))
        return length / span, points

    def test_a_sub_unit_offset_still_routes_straight(self):
        ratio, points = self._hop(0.09)
        assert ratio < 1.05, f"a 0.09 um offset produced a {ratio:.1f}x detour"
        ys = {round(y, 6) for _, y in points[:-1]}
        assert len(ys) == 1  # snapped onto one axis, so the approach stays a straight run

    def test_snapped_route_still_lands_on_the_true_port(self):
        from optodraw.core.ports import Port
        from optodraw.core.routing import route_ports
        from optodraw.core.transform import Vec3

        start = Port("o1", Vec3(0, 0, 0), orientation_deg=0, width=0.5)
        end = Port("o2", Vec3(20, 0.4, 0), orientation_deg=0, width=0.5)
        route = route_ports(start, end, kind="waveguide")
        points = route.resolve_points()
        assert points[-1][1] == end.center.y == 0.4

    def test_a_real_offset_still_gets_a_proper_jog(self):
        ratio, _ = self._hop(6.0)
        assert ratio > 1.2  # a genuine step is still routed as a step


class TestRouteWidths:
    def test_a_wire_does_not_taper_into_its_bond_pad(self):
        """Port widths drive a waveguide taper, which is real photonics. A bond
        pad's port is the whole 28 um landing, so the same rule turned every
        escape wire into a giant metal wedge."""

        from optodraw import ElectricalPad, Scene
        from optodraw.components.electronics import CoherentReceiver

        scene = Scene(width=200, height=120, platform="on_chip")
        rx = scene.add(CoherentReceiver(center=(-40, 0)))
        pad = scene.add(ElectricalPad(center=(60, 13.5)))
        route = scene.route((rx, "i_p"), (pad, "e1"), kind="electrical")
        assert route.width2 is None  # uniform trace...
        assert route.width == pytest.approx(rx.ports()["i_p"].width)  # ... at trace width

    def test_waveguide_routes_still_taper_between_port_widths(self):
        from optodraw import Scene, Waveguide

        scene = Scene(width=200, height=120, platform="on_chip")
        # physical ports carry the physical widths, so the route tapers 0.5 -> 2.0
        narrow = scene.add(Waveguide(center=(-40, 0), width=0.5, render_physical=True))
        wide = scene.add(Waveguide(center=(40, 0), width=2.0, render_physical=True))
        route = scene.route((narrow, "o2"), (wide, "o1"), kind="waveguide")
        assert route.width == pytest.approx(0.5)
        assert route.width2 == pytest.approx(2.0)

    def test_schematic_waveguides_share_one_drawn_width(self):
        """Schematic ports carry the DRAWN width, so equal drawings join without a taper."""
        from optodraw import Scene, Waveguide

        scene = Scene(width=200, height=120, platform="on_chip")
        narrow = scene.add(Waveguide(center=(-40, 0), width=0.5))
        wide = scene.add(Waveguide(center=(40, 0), width=2.0))
        assert narrow.ports()["o2"].width == pytest.approx(wide.ports()["o1"].width)
        route = scene.route((narrow, "o2"), (wide, "o1"), kind="waveguide")
        assert route.width2 is None or route.width2 == pytest.approx(route.width)


class TestPortToPortPlacement:
    """Chips are built by clicking one port to the next; placement should be able
    to say the same thing, so routes come out as straight hops."""

    def test_align_ports_puts_the_target_port_in_front_of_the_source(self):
        from optodraw import MMI1x2, Scene, VerticalGratingCoupler
        from optodraw.layout import align_ports

        scene = Scene(width=200, height=100, platform="on_chip")
        # a grating coupler at 180 deg sends its waveguide out to the RIGHT
        gc = scene.add(VerticalGratingCoupler(center=(-70, 0), angle=180))
        mmi = scene.add(MMI1x2())
        align_ports(gc, "o1", mmi, "o1", gap=14.0)

        src, dst = gc.world_port("o1"), mmi.world_port("o1")
        # placement lands on whole units, so the gap and the alignment are exact
        # to within half a unit -- close enough that the router reads the two
        # ports as collinear and draws one straight run
        assert dst.center.x - src.center.x == pytest.approx(14.0, abs=0.5)
        assert dst.center.y == pytest.approx(src.center.y, abs=0.5)
        assert mmi.transform.position.x == round(mmi.transform.position.x)

    def test_aligned_ports_route_as_a_straight_hop(self):
        from optodraw import MMI1x2, Scene, VerticalGratingCoupler
        from optodraw.layout import align_ports

        scene = Scene(width=200, height=100, platform="on_chip")
        gc = scene.add(VerticalGratingCoupler(center=(-70, 0), angle=180))
        mmi = scene.add(MMI1x2())
        align_ports(gc, "o1", mmi, "o1", gap=14.0)
        route = scene.route((gc, "o1"), (mmi, "o1"), kind="waveguide")

        points = route.resolve_points()
        ys = {round(float(p[1]), 6) for p in points}
        assert len(ys) == 1  # one straight run, not a detour around the part


class TestObstacleAwareRouting:
    """A link should go AROUND the parts it passes, not through them. The router
    kept clear of the two devices it connected and knew nothing about the rest of
    the scene, so a waveguide would run straight over whatever sat between."""

    def _scene_with_obstacle(self, obstacle_y: float = 0.0):
        from optodraw import MMI1x2, MicroringResonator, Scene, VerticalGratingCoupler

        scene = Scene(width=400, height=200, platform="on_chip")
        source = scene.add(VerticalGratingCoupler(center=(-140, 0), angle=180))
        target = scene.add(MMI1x2(center=(140, 0)))
        blocker = scene.add(MicroringResonator(center=(0, obstacle_y), add_drop=False, label="in the way"))
        return scene, source, target, blocker

    @staticmethod
    def _box(component, pad=0.0):
        # the DRAWN footprint: a ring's ports sit on its bus, so a port-hull box
        # would leave most of the part (and all of the loop) unguarded
        from optodraw.layout import estimate_component_size

        width, height = estimate_component_size(component)
        cx, cy = float(component.world_position.x), float(component.world_position.y)
        return (cx - width / 2 - pad, cy - height / 2 - pad, cx + width / 2 + pad, cy + height / 2 + pad)

    @staticmethod
    def _crossings(route, box):
        """Sample ALONG the path: a two-point straight line has no vertex inside
        the part it drives through."""

        x0, y0, x1, y1 = box
        hits = []
        points = [(float(p[0]), float(p[1])) for p in route.resolve_points()]
        for (ax, ay), (bx, by) in zip(points, points[1:]):
            steps = max(int(math.dist((ax, ay), (bx, by)) / 2.0), 1)
            for k in range(steps + 1):
                t = k / steps
                x, y = ax + (bx - ax) * t, ay + (by - ay) * t
                if x0 < x < x1 and y0 < y < y1:
                    hits.append((round(x, 1), round(y, 1)))
        return hits

    def test_route_detours_around_a_part_in_its_path(self):
        scene, source, target, blocker = self._scene_with_obstacle()
        route = scene.route((source, "o1"), (target, "o1"), kind="waveguide")
        hits = self._crossings(route, self._box(blocker))
        assert not hits, f"route runs through the blocker at {hits[:3]}"

    def test_a_clear_path_stays_straight(self):
        # the same link with the blocker moved well aside must NOT grow a detour
        scene, source, target, _ = self._scene_with_obstacle(obstacle_y=80.0)
        route = scene.route((source, "o1"), (target, "o1"), kind="waveguide")
        points = [(float(p[0]), float(p[1])) for p in route.resolve_points()]
        span = math.dist(points[0], points[-1])
        length = sum(math.dist(a, b) for a, b in zip(points, points[1:]))
        assert length <= span * 1.05


def test_an_array_of_arc_ports_routes_the_same_way_throughout():
    """One S-bend rule for a whole port arc, not two split at 45 degrees.

    The AWGR channel apertures sit on a Rowland arc spanning -143 to -127
    degrees. The old smooth router asked each port whether it was "horizontal"
    (|nx| >= |ny|), and that boundary falls in the middle of this arc, so two of
    the four arms took a cosine S-bend and the other two fell through to the
    Manhattan backbone and arrived through a square corner.
    """

    import warnings

    from optodraw import MZM, AWGR, Scene

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        scene = Scene(title="", width=1200, height=800, platform="on_chip")
        router = scene.add(AWGR(center=(300.0, 67.3), array_count=16, channel_count=4,
                                channel_spacing=7.5, fpr_length=36.0, array_height=65.0,
                                tilt_deg=45.0))
        sources = [scene.add(MZM(center=(-250.0, y), arm_length=28.0, arm_gap=12.0,
                                 splitter="ybranch")) for y in (210.0, 70.0, -70.0, -210.0)]
        routes = [scene.route((sources[i], "o3"), (router, f"i{i+1}"),
                              kind="waveguide", path_type="smooth") for i in range(4)]

    # A curve is sampled densely; a Manhattan backbone is a handful of corners.
    # Every arm of one array must get the curve (its count of samples follows
    # its length, so the counts differ).
    counts = [len(route.points) for route in routes]
    assert min(counts) > 8, f"an arm fell back to corners: {counts}"

    for route in routes:                      # and none of them turns a corner
        turns = 0
        for a, b, c in zip(route.points, route.points[1:], route.points[2:]):
            first = math.atan2(b.y - a.y, b.x - a.x)
            second = math.atan2(c.y - b.y, c.x - b.x)
            if abs(math.degrees(second - first)) > 60.0:
                turns += 1
        assert turns == 0, "a smooth route should not contain a square corner"
