"""Tests for Tier 2 visual scale, symbolic style, and optics metadata."""

from __future__ import annotations

import pytest

from optodraw import Waveguide
from optodraw.components.onchip.couplers import EdgeCoupler, VerticalGratingCoupler
from optodraw.components.onchip.mmi import MMI1x2
from optodraw.components.onchip.rings import MicroringResonator, RacetrackResonator
from optodraw.components.optics import Lens, Mirror, Prism


class TestVisualScaleOnChip:
    def test_waveguide_schematic_geometry_with_visual_scale(self):
        baseline = Waveguide(length=10.0, width=0.5, visual_scale=1.0)
        scaled = Waveguide(length=10.0, width=0.5, visual_scale=2.0)

        baseline_geo = baseline.geometry_2d()
        scaled_geo = scaled.geometry_2d()

        assert baseline_geo["w"] == pytest.approx(24.0)
        assert baseline_geo["h"] == pytest.approx(1.2)
        assert scaled_geo["w"] == pytest.approx(48.0)
        assert scaled_geo["h"] == pytest.approx(2.4)
        assert baseline.length == pytest.approx(10.0)

    def test_mmi_physical_dims_unchanged_schematic_scaled(self):
        mmi = MMI1x2(body_length=5.5, body_width=2.5, taper_length=10.0, visual_scale=2.0)

        assert mmi.body_length == pytest.approx(5.5)
        assert mmi.body_width == pytest.approx(2.5)
        assert mmi.taper_length == pytest.approx(10.0)
        assert mmi.total_length == pytest.approx(25.5)
        assert mmi.schematic_dims()["body_length"] == pytest.approx(24.0)

    def test_microring_physical_radius_ports(self):
        ring = MicroringResonator(ring_radius=10.0, gap=0.2, visual_scale=2.0)

        assert ring.ring_radius == pytest.approx(10.0)
        assert ring.gap == pytest.approx(0.2)
        # radius/gap attrs stay physical; bus_offset_y reflects the drawn cross-section.
        assert ring.bus_offset_y == pytest.approx(ring.ring_radius + ring._geom_gap() + ring._geom_waveguide_width())

    def test_racetrack_physical_bend_radius(self):
        racetrack = RacetrackResonator(bend_radius=10.0, gap=0.2, visual_scale=2.0)

        assert racetrack.bend_radius == pytest.approx(10.0)
        assert racetrack.gap == pytest.approx(0.2)

    def test_grating_coupler_physical_footprint(self):
        gc = VerticalGratingCoupler(length=40.0, width=26.0, taper_length=16.0, visual_scale=2.0)

        assert gc.length == pytest.approx(40.0)
        assert gc.width == pytest.approx(26.0)
        assert gc.taper_length == pytest.approx(16.0)
        assert gc.schematic_dims()["length"] == pytest.approx(84.0)

    def test_edge_coupler_physical_dims(self):
        ec = EdgeCoupler(taper_length=28.0, cladding_length=16.0, cladding_width=4.6, visual_scale=2.0)

        assert ec.taper_length == pytest.approx(28.0)
        assert ec.cladding_length == pytest.approx(16.0)
        assert ec.cladding_width == pytest.approx(4.6)
        assert ec.total_length == pytest.approx(44.0)


class TestSymbolicVisualStyle:
    def test_waveguide_symbolic_geometry_is_line_group(self):
        symbolic = Waveguide(length=20.0, visual_style="symbolic")
        publication = Waveguide(length=20.0, visual_style="publication")

        symbolic_geo = symbolic.geometry_2d()
        publication_geo = publication.geometry_2d()

        assert symbolic_geo["type"] == "group"
        assert symbolic_geo["children"][0]["type"] == "line"
        assert publication_geo["type"] == "rect"


class TestFreeSpacePhysicsMetadata:
    def test_lens_physics_metadata_keys(self):
        lens = Lens(focal_length=50.0, aperture=10.0, material_preset="glass")
        metadata = lens.physics_metadata()

        assert metadata["domain"] == "free_space"
        assert metadata["component"] == "lens"
        assert metadata["focal_length"] == pytest.approx(50.0)
        assert metadata["aperture"] == pytest.approx(10.0)
        assert metadata["diameter"] == pytest.approx(10.0)
        assert metadata["material_preset"] == "glass"

    def test_mirror_physics_metadata_keys(self):
        mirror = Mirror(aperture=8.0, surface_type="flat", center=(0, 0), angle=45.0)
        metadata = mirror.physics_metadata()

        assert metadata["domain"] == "free_space"
        assert metadata["component"] == "mirror"
        assert metadata["surface_type"] == "flat"
        assert metadata["aperture"] == pytest.approx(8.0)
        assert metadata["angle"] == pytest.approx(45.0)
        assert metadata["reflective"] is True

    def test_prism_physics_metadata_keys(self):
        prism = Prism(apex_angle=60.0, refractive_index=1.515)
        metadata = prism.physics_metadata()

        assert metadata["domain"] == "free_space"
        assert metadata["component"] == "prism"
        assert metadata["apex_angle"] == pytest.approx(60.0)
        assert metadata["refractive_index"] == pytest.approx(1.515)
