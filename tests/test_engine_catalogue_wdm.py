"""Wavelength-division input values come from numbers, not drawing colours."""
import pytest

from optodraw.components.preset_chip import WDMInput
from optodraw.animation_engine.behaviours import behaviour_for
from optodraw.animation_engine.signals import power


def test_wdm_default_channels_and_explicit_powers():
    default = WDMInput()
    channels = behaviour_for(default, "input").emissions(default, "input", {})
    assert [item.wavelength_nm for item in channels] == [1549, 1550, 1551]
    assert [power(item.jones) for item in channels] == [1, 1, 1]
    explicit = WDMInput(wavelengths_nm=(1300, 1310), channel_powers=(0.25, 4))
    channels = behaviour_for(explicit, "input").emissions(explicit, "input", {})
    assert [item.wavelength_nm for item in channels] == [1300, 1310]
    assert [power(item.jones) for item in channels] == [0.25, 4]


@pytest.mark.parametrize("wavelengths,powers", [([0], [1]), ([1550], [-1]), ([1550], [1, 2])])
def test_wdm_rejects_invalid_values(wavelengths, powers):
    from optodraw.animation_engine.errors import AnimationError
    part = WDMInput(wavelengths_nm=wavelengths, channel_powers=powers)
    with pytest.raises(AnimationError, match="input"):
        behaviour_for(part, "input").emissions(part, "input", {})


