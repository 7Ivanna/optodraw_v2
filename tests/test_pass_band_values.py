"""A filter or a dichroic takes "longpass" or "shortpass": any other band is refused, not read as one of them."""

import pytest

from optodraw import DichroicMirror, Filter


@pytest.mark.parametrize("make", [Filter, DichroicMirror])
def test_an_unknown_pass_band_is_refused(make):
    with pytest.raises(ValueError, match="longpass"):
        make(cutoff_wavelength=700, pass_band="bandpass")


@pytest.mark.parametrize("make", [Filter, DichroicMirror])
@pytest.mark.parametrize("band", ["longpass", "shortpass"])
def test_the_two_bands_are_taken(make, band):
    assert make(cutoff_wavelength=700, pass_band=band).pass_band == band
