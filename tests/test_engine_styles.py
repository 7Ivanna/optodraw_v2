import json

import pytest

from optodraw.animation_engine.styles import STYLE_NAMES, Style, resolve_style
from optodraw.core.beam import wavelength_to_hex


@pytest.mark.parametrize("name", ["photons", "packets", "beam", "wave", "bits"])
def test_each_spec_style_is_json_data(name):
    style = resolve_style(name)
    assert style.name == name
    assert Style.from_json(json.loads(json.dumps(style.to_json()))) == style


def test_visible_colour_and_fixed_infrared_palette():
    style = Style("photons")
    assert style.colour(532.0) == wavelength_to_hex(532.0)
    assert style.colour(1310.0) == "#009e73"
    assert style.colour(1550.0) == "#e69f00"
    assert set(STYLE_NAMES) == {"photons", "packets", "beam", "wave", "bits"}


def test_wave_scale_and_overlays_survive_serialization():
    style = Style("wave", wave_scale=2500.0, polarisation=True, power_labels=True)
    data = style.to_json()
    assert data["wave_scale"] == 2500.0
    assert data["polarisation"] is True
    assert data["power_labels"] is True
    assert "jones" not in data and "power" not in data


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
