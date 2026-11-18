"""gdsfactory 8 and 9 both resolve a generic PDK for layer styles."""

from __future__ import annotations

import importlib.util

import pytest

from optodraw.gds.styles import _load_generic_gdsfactory_pdk, get_generic_pdk_layer_styles

HAS_GDSFACTORY = importlib.util.find_spec("gdsfactory") is not None


def test_generic_layer_styles_always_return_a_dict():
    styles = get_generic_pdk_layer_styles()
    assert isinstance(styles, dict)


@pytest.mark.skipif(not HAS_GDSFACTORY, reason="gdsfactory not installed")
def test_generic_pdk_loads_on_gdsfactory_8_or_9():
    pdk = _load_generic_gdsfactory_pdk()
    assert pdk is not None
    activate = getattr(pdk, "activate", None)
    if callable(activate):
        activate()
    getter = getattr(pdk, "get_layer_stack", None)
    if callable(getter):
        stack = getter()
        assert getattr(stack, "layers", None) is not None
