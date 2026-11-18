"""Tests for the optional Optiland physics bridge.

The pure-python prescription model and ray-path conversion are tested without
Optiland installed. Tests that need the real backend are guarded with
``pytest.importorskip("optiland")``.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from optodraw import Lens
from optodraw.core.beam import Beam
from optodraw.optiland_bridge import (
    INSTALL_HINT,
    LensPrescription,
    OpticalSurface,
    build_optic,
    optiland_available,
    place_ray_paths,
    ray_paths_from_arrays,
    rays_to_beams,
    require_optiland,
    trace_lens_beams,
)

HAS_OPTILAND = optiland_available()


# --------------------------------------------------------------------------- #
# Prescription model
# --------------------------------------------------------------------------- #


def test_optical_surface_defaults_to_flat_air():
    surface = OpticalSurface()
    assert surface.radius == math.inf
    assert surface.material is None
    assert surface.is_stop is False


def test_prescription_validates_aperture_and_wavelength():
    with pytest.raises(ValueError):
        LensPrescription(aperture_epd=0.0)
    with pytest.raises(ValueError):
        LensPrescription(aperture_epd=10.0, wavelengths_um=())
    with pytest.raises(ValueError):
        LensPrescription(aperture_epd=10.0, wavelengths_um=(-0.5,))


def test_from_thin_lens_uses_lensmaker_equiconvex():
    f = 50.0
    aperture = 20.0
    index = 1.5168
    rx = LensPrescription.from_thin_lens(f, aperture, index=index)

    assert len(rx.surfaces) == 2
    front, back = rx.surfaces
    expected_radius = 2.0 * (index - 1.0) * f
    assert front.radius == pytest.approx(expected_radius)
    assert back.radius == pytest.approx(-expected_radius)
    # Front face is glass, carries the stop; back face exits to air at ~f.
    assert front.material == "N-BK7"
    assert front.is_stop is True
    assert back.material is None
    assert back.thickness == pytest.approx(f)
    assert rx.aperture_epd == aperture
    assert rx.has_stop is True


def test_from_optodraw_lens_maps_symmetric_biconvex():
    lens = Lens(center=(0, 0), radius=12.0, aperture=20.0, focal_length=40.0)
    rx = LensPrescription.from_optodraw_lens(lens)

    front, back = rx.surfaces
    assert front.radius == pytest.approx(12.0)
    assert back.radius == pytest.approx(-12.0)
    assert front.thickness == pytest.approx(lens.center_thickness)
    assert back.thickness == pytest.approx(40.0)  # image distance == |focal_length|
    assert rx.aperture_epd == pytest.approx(20.0)


def test_from_optodraw_lens_requires_geometry():
    bare = Lens(center=(0, 0), radius=0.0, aperture=10.0)
    bare.radius = 0.0
    bare.focal_length = None
    with pytest.raises(ValueError):
        LensPrescription.from_optodraw_lens(bare)


def test_with_stop_moves_aperture_stop():
    rx = LensPrescription(
        surfaces=[OpticalSurface(radius=10.0, thickness=2.0), OpticalSurface(radius=-10.0)],
        aperture_epd=8.0,
    )
    assert rx.has_stop is False
    moved = rx.with_stop(1)
    assert moved.surfaces[1].is_stop is True
    assert moved.surfaces[0].is_stop is False
    # original is untouched
    assert rx.has_stop is False


# --------------------------------------------------------------------------- #
# Pure ray-path geometry
# --------------------------------------------------------------------------- #


def test_ray_paths_from_arrays_builds_one_polyline_per_ray():
    # 3 surfaces, 2 rays. axial=z increases, transverse=y converges to 0.
    z = np.array([[0.0, 0.0], [5.0, 5.0], [10.0, 10.0]])
    y = np.array([[2.0, -2.0], [1.0, -1.0], [0.0, 0.0]])
    paths = ray_paths_from_arrays(z, y)

    assert len(paths) == 2
    assert paths[0] == [(0.0, 2.0), (5.0, 1.0), (10.0, 0.0)]
    assert paths[1] == [(0.0, -2.0), (5.0, -1.0), (10.0, 0.0)]


def test_ray_paths_from_arrays_drops_nonfinite_points():
    # First surface (object at infinity) is non-finite and must be dropped.
    z = np.array([[-np.inf, -np.inf], [0.0, 0.0], [10.0, 10.0]])
    y = np.array([[np.nan, np.nan], [2.0, -2.0], [0.0, 0.0]])
    paths = ray_paths_from_arrays(z, y)

    assert len(paths) == 2
    assert paths[0] == [(0.0, 2.0), (10.0, 0.0)]


def test_ray_paths_from_arrays_omits_degenerate_rays():
    z = np.array([[np.inf], [0.0]])
    y = np.array([[np.nan], [1.0]])
    # Only one finite point remains -> ray omitted.
    assert ray_paths_from_arrays(z, y) == []


def test_ray_paths_from_arrays_shape_mismatch_raises():
    with pytest.raises(ValueError):
        ray_paths_from_arrays(np.zeros((2, 2)), np.zeros((2, 3)))


def test_place_ray_paths_identity_keeps_axis_as_x():
    paths = [[(0.0, 1.0), (10.0, 0.0)]]
    placed = place_ray_paths(paths)
    assert placed[0][0] == pytest.approx((0.0, 1.0))
    assert placed[0][1] == pytest.approx((10.0, 0.0))


def test_place_ray_paths_origin_offset_and_axial_offset():
    paths = [[(5.0, 2.0)]]
    placed = place_ray_paths(paths, origin=(100.0, -3.0), axial_offset=5.0)
    # axial 5 - offset 5 = 0 -> sits at origin x; transverse 2 -> origin y + 2
    assert placed[0][0] == pytest.approx((100.0, -1.0))


def test_place_ray_paths_rotation_90_degrees():
    paths = [[(10.0, 0.0)]]
    placed = place_ray_paths(paths, direction_deg=90.0)
    # axial +x rotates to +y
    assert placed[0][0][0] == pytest.approx(0.0, abs=1e-9)
    assert placed[0][0][1] == pytest.approx(10.0)


def test_place_ray_paths_scales_independently():
    paths = [[(2.0, 3.0)]]
    placed = place_ray_paths(paths, axial_scale=2.0, transverse_scale=0.5)
    assert placed[0][0] == pytest.approx((4.0, 1.5))


# --------------------------------------------------------------------------- #
# Beam conversion
# --------------------------------------------------------------------------- #


def test_rays_to_beams_emits_beams_with_resolved_points():
    paths = [[(0.0, 1.0), (10.0, 0.0)], [(0.0, -1.0), (10.0, 0.0)]]
    beams = rays_to_beams(paths, wavelength_nm=532.0, label="fan")

    assert len(beams) == 2
    assert all(isinstance(beam, Beam) for beam in beams)
    assert beams[0].wavelength == 532.0
    # Only the first beam carries the label, to avoid label spam in renderers.
    assert beams[0].label == "fan"
    assert beams[1].label == ""
    assert beams[0].resolve_points() == [(0.0, 1.0, 0.0), (10.0, 0.0, 0.0)]


def test_rays_to_beams_skips_short_paths():
    assert rays_to_beams([[(0.0, 0.0)]]) == []


def test_beam_color_tracks_wavelength():
    green = rays_to_beams([[(0.0, 0.0), (1.0, 0.0)]], wavelength_nm=532.0)[0]
    red = rays_to_beams([[(0.0, 0.0), (1.0, 0.0)]], wavelength_nm=633.0)[0]
    assert green.color != red.color


# --------------------------------------------------------------------------- #
# Graceful degradation without Optiland
# --------------------------------------------------------------------------- #


@pytest.mark.skipif(HAS_OPTILAND, reason="optiland is installed")
def test_require_optiland_raises_install_hint_when_missing():
    with pytest.raises(ImportError) as excinfo:
        require_optiland()
    assert "optiland" in str(excinfo.value).lower()
    assert INSTALL_HINT in str(excinfo.value)


@pytest.mark.skipif(HAS_OPTILAND, reason="optiland is installed")
def test_build_optic_raises_when_optiland_missing():
    rx = LensPrescription.from_thin_lens(50.0, 20.0)
    with pytest.raises(ImportError):
        build_optic(rx)


@pytest.mark.skipif(HAS_OPTILAND, reason="optiland is installed")
def test_trace_lens_beams_raises_when_optiland_missing():
    rx = LensPrescription.from_thin_lens(50.0, 20.0)
    with pytest.raises(ImportError):
        trace_lens_beams(rx)


# --------------------------------------------------------------------------- #
# Real trace (only when Optiland is available)
# --------------------------------------------------------------------------- #


@pytest.mark.skipif(not HAS_OPTILAND, reason="optiland not installed")
def test_trace_lens_beams_produces_converging_fan():
    pytest.importorskip("optiland")
    rx = LensPrescription.from_thin_lens(50.0, 20.0, wavelengths_um=(0.55,))
    beams = trace_lens_beams(rx, origin=(0.0, 0.0), num_rays=9)

    assert beams, "expected at least one traced beam"
    assert all(isinstance(beam, Beam) for beam in beams)
    # A collimated fan through a positive singlet should converge: the spread of
    # final-point heights should be smaller than the spread of entry heights.
    entry = [beam.resolve_points()[0][1] for beam in beams]
    exit_ = [beam.resolve_points()[-1][1] for beam in beams]
    assert (max(exit_) - min(exit_)) < (max(entry) - min(entry))


@pytest.mark.skipif(not HAS_OPTILAND, reason="optiland not installed")
def test_trace_lens_beams_adds_to_scene_when_given():
    pytest.importorskip("optiland")
    from optodraw import Scene

    scene = Scene(title="optiland", platform="free_space")
    before = len(list(scene.walk()))
    rx = LensPrescription.from_thin_lens(40.0, 16.0)
    beams = trace_lens_beams(rx, scene=scene, num_rays=5)
    after = len(list(scene.walk()))
    assert after - before == len(beams)
