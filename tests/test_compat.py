"""Deprecation helper contract: aliases warn, keep working, name a sunset."""

from __future__ import annotations

import warnings

import pytest

from optodraw._compat import deprecated


def _old_function(value: int = 1) -> int:
    return value * 2


def test_deprecated_alias_still_works():
    wrapped = deprecated("old_function", replacement="new_function", sunset="9.9")( _old_function)
    with pytest.warns(DeprecationWarning, match="old_function.*9.9.*new_function"):
        assert wrapped() == 2
        assert wrapped(value=3) == 6


def test_deprecated_keeps_name_and_doc():
    def documented() -> str:
        """Original doc."""
        return "x"

    wrapped = deprecated("documented", replacement="other", sunset="9.9")(documented)
    assert wrapped.__name__ == "documented"
    assert wrapped.__doc__ == "Original doc."
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        assert wrapped() == "x"


def test_compiler_and_renderer_helpers_stay_off_the_root():
    import optodraw

    hidden = (
        "compile_physics_animation",
        "UnsupportedGeometryError",
        "bundle_offline_assets",
    )
    leaked = [name for name in hidden if name in optodraw.__all__]
    assert not leaked, f"keep these in their modules until a changelog promotes them: {leaked}"


def test_deprecated_points_at_caller():
    wrapped = deprecated("traced", replacement="other", sunset="9.9")(_old_function)
    with warnings.catch_warnings(record=True) as records:
        warnings.simplefilter("always", DeprecationWarning)
        wrapped()
    assert records
    assert "test_compat" in str(records[0].filename)
