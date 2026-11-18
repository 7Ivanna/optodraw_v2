"""Deprecation helper contract: aliases warn, keep working, name a sunset."""

from __future__ import annotations


import pytest

from optodraw._compat import deprecated


def _old_function(value: int = 1) -> int:
    return value * 2


def test_deprecated_alias_still_works():
    wrapped = deprecated("old_function", replacement="new_function", sunset="9.9")( _old_function)
    with pytest.warns(DeprecationWarning, match="old_function.*9.9.*new_function"):
        assert wrapped() == 2
        assert wrapped(value=3) == 6


def test_compiler_and_renderer_helpers_stay_off_the_root():
    import optodraw

    hidden = (
        "compile_physics_animation",
        "UnsupportedGeometryError",
        "bundle_offline_assets",
    )
    leaked = [name for name in hidden if name in optodraw.__all__]
    assert not leaked, f"keep these in their modules until a changelog promotes them: {leaked}"


