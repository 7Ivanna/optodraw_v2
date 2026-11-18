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
)


class TestPorts:


    def test_mzm_thermo_optic_uses_heater_ports(self):
        mod = MZM(mechanism="thermo_optic")
        ports = mod.ports()
        # thermo-optic phase shift exposes heater pads (like the MZI), no RF pads
        assert {"h1", "h2"}.issubset(ports)
        assert ports["h1"].kind == "electrical"
        assert "sig" not in ports and "gnd" not in ports


    def test_pn_microring_add_drop_excludes_coupler_arcs(self):
        ring = PNMicroringModulator(add_drop=True)
        for start, end in ring._active_arc_ranges():
            assert (-90.0 < start and end < 90.0) or (90.0 < start and end < 270.0)


    def test_generic_electronics_primitives_expose_electrical_ports(self):
        pad = ElectricalPad(port_side="right", width=30, height=24)
        gsg = GSGProbePad(port_side="left")
        arrow = SignalArrow(signal="rf")

        assert pad.ports()["e1"].kind == "electrical"
        assert pad.ports()["e1"].orientation_deg == pytest.approx(0.0)
        assert set(gsg.ports()) == {"g1", "s", "g2"}
        assert arrow.ports()["out"].kind == "electrical"


    def test_system_electronics_components_have_1d_2d_3d_visuals(self):
        components = [RFDriver, Microcontroller, MEMSActuator, PCB]
        for component_cls in components:
            assert component_cls(visual_style="symbolic").geometry_2d()["type"] == "group"
            assert component_cls().geometry_2d()["type"] == "group"
            assert component_cls().geometry_3d()["shape"] == "group"
        assert RFDriver(visual_scale=2.0).ports()["in"].center.x == pytest.approx(-38.0)


class TestRouting:


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


class TestOnChipComponents:

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


    def test_thermo_optic_mzm_heater_is_one_unified_metal_polygon(self):
        gold = [c for c in MZM(mechanism="thermo_optic").geometry_2d()["children"] if c.get("fill") == "#d4af37"]
        assert len(gold) == 1


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


    def test_pn_microring_contacts_carry_vias(self):
        ring = PNMicroringModulator(add_drop=True)
        vias = [c for c in ring.geometry_2d()["children"] if c.get("fill") == "#f08c6d"]
        assert len(vias) >= 6


    def test_racetrack_modulator_adds_active_and_metal_layers(self):
        geo2d = RacetrackModulator().geometry_2d()
        fills = {child.get("fill") for child in geo2d["children"]}
        assert {"#f4b4b4", "#b7cdf2", "#d4af37", "#c8964a"} <= fills     # p, n, gold, TiN heater


class TestOnChipRendering:


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


