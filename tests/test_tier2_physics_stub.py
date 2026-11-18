"""Tests for Tier 2 physics depth stubs (Snell, thin lens, paraxial validation)."""

from __future__ import annotations

import math

import pytest

from optodraw import Lens, Prism, Scene, Waveguide, snell_refract, trace_ray, validate_paraxial_chain
from optodraw.components.onchip.mmi import MMI1x2
from optodraw.registry import component_registry


class TestSnellRefractionStub:
    def test_snell_normal_incidence_air_to_glass(self):
        assert snell_refract(0.0, n1=1.0, n2=1.5) == pytest.approx(0.0, abs=1e-9)

    def test_snell_oblique_incidence_air_to_glass(self):
        refracted = snell_refract(30.0, n1=1.0, n2=1.5)
        expected = math.degrees(math.asin(math.sin(math.radians(30.0)) / 1.5))
        assert refracted == pytest.approx(expected, abs=0.1)
        assert refracted == pytest.approx(19.47, abs=0.1)

    def test_trace_ray_prism_applies_snell_refraction(self):
        prism = Prism(center=(0, 0), angle=0, refractive_index=1.5)

        normal = trace_ray(start=(-10, 0), direction_deg=0.0, optics=[prism], exit_length=5.0)
        oblique = trace_ray(start=(-10, 0), direction_deg=30.0, optics=[prism], exit_length=5.0)

        assert normal.direction_deg == pytest.approx(0.0, abs=0.1)
        assert oblique.direction_deg == pytest.approx(19.47, abs=0.1)

    def test_trace_ray_prism_without_index_is_pass_through(self):
        prism = Prism(center=(0, 0), angle=0)
        prism.refractive_index = None  # type: ignore[assignment]

        result = trace_ray(start=(-10, 0), direction_deg=30.0, optics=[prism], exit_length=5.0)

        assert result.direction_deg == pytest.approx(30.0)


class TestThinLensRayTrace:
    def test_lens_with_focal_length_redirects_off_axis_ray(self):
        lens = Lens(center=(0, 0), angle=0, focal_length=10.0)

        # a lens now focuses by default; the pass-straight control opts out explicitly
        without_focal = trace_ray(start=(-10, 5), direction_deg=0.0, optics=[Lens(center=(0, 0), focal_length=None)], exit_length=5.0)
        with_focal = trace_ray(start=(-10, 5), direction_deg=0.0, optics=[lens], exit_length=5.0)

        assert without_focal.direction_deg == pytest.approx(0.0)
        assert with_focal.direction_deg == pytest.approx(-28.65, abs=0.1)
        assert with_focal.direction_deg != pytest.approx(without_focal.direction_deg)


class TestParaxialValidation:
    def test_validate_paraxial_chain_warns_on_waveguide(self):
        warnings = validate_paraxial_chain([Waveguide(length=10.0)])

        assert len(warnings) == 1
        assert "Waveguide" in warnings[0]
        assert "paraxial" in warnings[0]

    def test_scene_validate_physics_paraxial_wrapper(self):
        scene = Scene()
        scene.add(Waveguide(length=10.0))
        scene.add(Lens(focal_length=20.0))

        warnings = scene.validate_physics(mode="paraxial")

        assert any("Waveguide" in message for message in warnings)
        assert not any("Lens" in message for message in warnings)


class TestRegistryPhysicsModes:
    def test_filter_and_objective_declare_paraxial(self):
        assert "paraxial" in component_registry()["Filter"].physics_modes
        assert "paraxial" in component_registry()["Objective"].physics_modes

    def test_grating_and_prism_remain_ray_only(self):
        assert component_registry()["Grating"].physics_modes == ("diagram", "ray")
        assert "paraxial" not in component_registry()["Prism"].physics_modes


class TestSymbolicMMI:
    def test_mmi1x2_symbolic_geometry_is_schematic(self):
        symbolic = MMI1x2(visual_style="symbolic")
        publication = MMI1x2(visual_style="publication")

        symbolic_geo = symbolic.geometry_2d()
        publication_geo = publication.geometry_2d()

        assert symbolic_geo["type"] == "group"
        assert any(child["type"] == "rect" for child in symbolic_geo["children"])
        assert any(child["type"] == "line" for child in symbolic_geo["children"])
        assert len(symbolic_geo["children"]) == 4
        assert not any(child["type"] == "line" for child in publication_geo["children"])
