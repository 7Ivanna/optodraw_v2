"""Tests for paraxial Gaussian beam propagation."""

from __future__ import annotations

import math

import pytest

from optodraw import (
    GaussianBeamState,
    Lens,
    Mirror,
    Scene,
    free_space_matrix,
    thin_lens_matrix,
    trace_paraxial_beam,
)


def test_gaussian_beam_free_space_reaches_expected_radius():
    beam = GaussianBeamState(wavelength=1.0, waist_radius=1.0)

    propagated = beam.propagate_free_space(beam.rayleigh_range)

    assert propagated.z_from_waist == pytest.approx(math.pi)
    assert propagated.beam_radius == pytest.approx(math.sqrt(2.0))
    assert propagated.wavefront_radius == pytest.approx(2.0 * math.pi)


def test_abcd_matrices_apply_to_q_parameter():
    beam = GaussianBeamState(wavelength=0.5, waist_radius=1.2)
    system = thin_lens_matrix(12.0) @ free_space_matrix(8.0)

    propagated = beam.propagate(system)
    expected_q = system.apply_q(beam.q_parameter)

    assert propagated.q_parameter.real == pytest.approx(expected_q.real)
    assert propagated.q_parameter.imag == pytest.approx(expected_q.imag)


def test_trace_paraxial_beam_applies_lens_and_exit_space():
    lens = Lens(center=(10, 0), focal_length=20.0, label="L1")
    input_beam = GaussianBeamState(wavelength=0.633, waist_radius=1.5)

    result = trace_paraxial_beam((0, 0), 0.0, [lens], input_beam=input_beam, exit_length=5.0)

    assert [sample.event for sample in result.samples] == ["start", "thin_lens", "exit"]
    assert result.samples[1].element_type == "Lens"
    assert result.samples[1].element_label == "L1"
    assert result.points[-1].x == pytest.approx(15.0)
    assert result.samples[-1].distance == pytest.approx(15.0)
    assert result.final_state.q_parameter != input_beam.q_parameter


def test_trace_paraxial_beam_reflects_mirror_path_direction():
    mirror = Mirror(center=(10, 0), angle=0)

    result = trace_paraxial_beam((0, 0), 0.0, [mirror], exit_length=5.0)

    assert result.samples[1].event == "reflect"
    assert result.points[-1].x == pytest.approx(5.0)
    assert result.points[-1].y == pytest.approx(0.0)


def test_scene_trace_paraxial_beam_adds_visible_beam_path():
    scene = Scene()
    lens = scene.add(Lens(center=(10, 0), focal_length=20.0))

    result = scene.trace_paraxial_beam(
        (0, 0),
        0.0,
        [lens],
        input_beam=GaussianBeamState(wavelength=0.633, waist_radius=1.0),
        exit_length=5.0,
        label="Gaussian path",
    )

    assert result.samples[-1].event == "exit"
    assert any(component.component_type == "Beam" for component in scene.walk())