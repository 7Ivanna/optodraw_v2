"""Trace kwarg hygiene: aliases must agree, unknown kwargs must not vanish.

``trace_ray`` / ``trace_paraxial_beam`` accept both ``wavelength`` and
``wavelength_nm`` (the same quantity in nm). Conflicting values used to lose
one silently, and any misspelled kwarg disappeared into a whitelist.
"""

from __future__ import annotations

import pytest

from optodraw import Scene
from optodraw.components.optics import Lens


def _scene_with_lens() -> tuple[Scene, Lens]:
    scene = Scene(platform="free_space")
    lens = scene.add(Lens(center=(20, 0), focal_length=30))
    return scene, lens


class TestWavelengthAliases:
    def test_wavelength_alias_reaches_trace_and_beam(self):
        import warnings as _warnings

        _, lens = _scene_with_lens()
        with _warnings.catch_warnings():
            _warnings.simplefilter("error")
            beam = Scene().trace_ray((-10, 0), 0, [lens], wavelength=532)
        assert beam.wavelength == 532

    def test_matching_aliases_are_accepted(self):
        _, lens = _scene_with_lens()
        beam = Scene().trace_ray((-10, 0), 0, [lens], wavelength=633, wavelength_nm=633.0)
        assert beam.wavelength == 633

    def test_conflicting_aliases_raise(self):
        _, lens = _scene_with_lens()
        with pytest.raises(ValueError, match="conflicting 'wavelength'"):
            Scene().trace_ray((-10, 0), 0, [lens], wavelength=633, wavelength_nm=1550)

    def test_paraxial_conflicting_aliases_raise(self):
        _, lens = _scene_with_lens()
        with pytest.raises(ValueError, match="conflicting 'wavelength'"):
            Scene().trace_paraxial_beam((-10, 0), 0, [lens], wavelength=633, wavelength_nm=1550)


class TestUnknownKwargs:
    def test_trace_ray_warns_on_unknown_kwarg(self):
        _, lens = _scene_with_lens()
        with pytest.warns(UserWarning, match="unknown argument.*wavelenght"):
            Scene().trace_ray((-10, 0), 0, [lens], wavelenght=532)

    def test_trace_paraxial_warns_on_unknown_kwarg(self):
        _, lens = _scene_with_lens()
        with pytest.warns(UserWarning, match="unknown argument.*divergense"):
            Scene().trace_paraxial_beam((-10, 0), 0, [lens], divergense=3)

    def test_known_kwargs_stay_silent(self):
        _, lens = _scene_with_lens()
        import warnings as _warnings

        with _warnings.catch_warnings():
            _warnings.simplefilter("error")
            Scene().trace_ray(
                (-10, 0),
                0,
                [lens],
                exit_length=40,
                label="probe",
                width=1.2,
            )


class TestPolarizationBranches:
    def test_unpolarized_reaches_the_tracer_and_is_refused_there(self):
        """``unpolarized`` is a known keyword: it passes through, and the Jones
        tracer answers with the function that handles it, not with a warning
        about an unknown argument."""
        from optodraw.components.optics import Polarizer

        polarizer = Polarizer(center=(0, 0))
        with pytest.raises(ValueError, match="trace_stokes_through"):
            Scene().trace_polarization([polarizer], jones_in=(1, 0), unpolarized=True)

    def test_none_jones_input_is_accepted(self):
        from optodraw.components.optics import Polarizer

        polarizer = Polarizer(center=(0, 0))
        result = Scene().trace_polarization([polarizer], jones_in=None)
        assert result is not None
