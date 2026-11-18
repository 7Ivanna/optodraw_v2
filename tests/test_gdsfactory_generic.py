"""gdsfactory 8 and 9 both resolve a generic PDK for layer styles."""

from __future__ import annotations

import importlib.util


from optodraw.gds.styles import get_generic_pdk_layer_styles

HAS_GDSFACTORY = importlib.util.find_spec("gdsfactory") is not None


def test_generic_layer_styles_always_return_a_dict():
    styles = get_generic_pdk_layer_styles()
    assert isinstance(styles, dict)


