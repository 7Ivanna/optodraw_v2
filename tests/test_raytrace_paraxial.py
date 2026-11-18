"""Tests for port-aware paraxial ray tracing and component beam helpers."""

from __future__ import annotations

import math

import pytest

from optodraw import Prism, Scene, trace_beam_through_component, trace_paraxial_ray, trace_ray
from optodraw.components.optics import Grating, RightAnglePrism, WedgePlate


class TestTraceBeamThroughComponent:
    def test_prism_applies_snell_refraction(self):
        prism = Prism(center=(0, 0), angle=0, refractive_index=1.5)

        result = trace_beam_through_component(prism, 633.0, direction_deg=30.0)

        assert result.interaction == "refract"
        assert result.output_direction_deg == pytest.approx(19.47, abs=0.1)
        assert result.deflection_deg == pytest.approx(-10.53, abs=0.2)

    def test_right_angle_prism_folds_beam(self):
        prism = RightAnglePrism(center=(0, 0), angle=0)

        result = trace_beam_through_component(prism, 633.0, direction_deg=0.0)

        assert result.interaction == "fold"
        assert result.metadata["deflection_angle_deg"] == pytest.approx(90.0)
        assert result.output_direction_deg == pytest.approx(90.0, abs=0.1)

    def test_wedge_plate_deviation_from_metadata(self):
        wedge = WedgePlate(wedge_angle_deg=2.0, refractive_index=1.52)

        result = trace_beam_through_component(wedge, 633.0, direction_deg=0.0)

        expected_deflection = (1.52 - 1.0) * 2.0
        assert result.metadata["deflection_angle_deg"] == pytest.approx(expected_deflection, abs=1e-9)
        assert result.interaction == "wedge"
        assert result.output_direction_deg == pytest.approx(-expected_deflection, abs=0.1)

    def test_grating_deflection_depends_on_wavelength(self):
        grating = Grating(center=(0, 0), angle=0, pitch=1.0)

        red = trace_beam_through_component(grating, 633.0, direction_deg=0.0)
        blue = trace_beam_through_component(grating, 450.0, direction_deg=0.0)

        assert red.interaction == "grating"
        assert blue.interaction == "grating"
        assert red.output_direction_deg == pytest.approx(39.29, abs=0.1)
        assert blue.output_direction_deg == pytest.approx(26.74, abs=0.1)
        assert blue.output_direction_deg < red.output_direction_deg


class TestTraceParaxialRay:
    def test_traces_from_port_through_scene_optics(self):
        scene = Scene()
        wedge = scene.add(WedgePlate(center=(20, 0), angle=0, wedge_angle_deg=2.0))
        _ = wedge

        result = trace_paraxial_ray(
            scene,
            (wedge, "in"),
            direction=0.0,
            exit_length=5.0,
        )

        expected_deflection = (1.52 - 1.0) * 2.0
        assert result.direction_deg == pytest.approx(-expected_deflection, abs=0.1)
        assert len(result.points) >= 3

    def test_scene_trace_includes_prism_snell(self):
        scene = Scene()
        source = scene.add(RightAnglePrism(center=(-10, 0), angle=0))
        prism = scene.add(Prism(center=(10, 0), angle=0, refractive_index=1.5))

        result = trace_paraxial_ray(
            scene,
            (source, "in"),
            direction=30.0,
            optics=[prism],
            exit_length=5.0,
        )

        assert result.direction_deg == pytest.approx(19.47, abs=0.1)

    def test_right_angle_prism_in_ray_chain(self):
        prism = RightAnglePrism(center=(0, 0), angle=0)

        result = trace_ray(start=(-10, 0), direction_deg=0.0, optics=[prism], exit_length=5.0)

        assert result.direction_deg == pytest.approx(90.0, abs=0.1)
        exit_point = result.points[-1]
        assert exit_point.x == pytest.approx(0.0, abs=0.1)
        assert exit_point.y == pytest.approx(5.0, abs=0.1)

    def test_wedge_in_ray_chain(self):
        wedge = WedgePlate(wedge_angle_deg=2.0, refractive_index=1.52)

        result = trace_ray(start=(-10, 0), direction_deg=0.0, optics=[wedge], exit_length=10.0)

        delta = (1.52 - 1.0) * 2.0
        assert result.direction_deg == pytest.approx(-delta, abs=0.1)
        exit_point = result.points[-1]
        expected_y = -math.tan(math.radians(delta)) * 10.0
        assert exit_point.y == pytest.approx(expected_y, abs=0.2)
