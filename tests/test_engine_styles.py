
import pytest

from optodraw.animation_engine.styles import STYLE_NAMES, Style
from optodraw.core.beam import wavelength_to_hex


def test_visible_colour_and_fixed_infrared_palette():
    style = Style("photons")
    assert style.colour(532.0) == wavelength_to_hex(532.0)
    assert style.colour(1310.0) == "#009e73"
    assert style.colour(1550.0) == "#e69f00"
    assert set(STYLE_NAMES) == {"photons", "packets", "beam", "wave", "bits"}


@pytest.mark.parametrize("kwargs", [
    {"name": "unknown"},
    {"wave_scale": 0.0},
    {"dot_radius": -1.0},
    {"brightness": float("nan")},
    {"photons_per_power": float("inf")},
    {"infrared_palette": ((1550.0, "red"),)},
])
def test_invalid_style_data_is_rejected(kwargs):
    with pytest.raises(ValueError):
        Style(**kwargs)
