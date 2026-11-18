"""Animation behaviours of a dichroic mirror, an AWG multiplexer and a 1 x 4 MMI."""

import pytest

from optodraw import DichroicMirror, MMI1x4
from optodraw.animation_engine.behaviours import find_behaviour


def _ports(part, port, wavelength):
    """The ports the light leaves by: a transfer of no power is no way out."""

    return sorted(t.out_port for t in find_behaviour(part).transfers(part, "p1", port, wavelength, {}) if t.matrix.any())


@pytest.mark.parametrize("band, short, long", [("longpass", "refl", "trans"), ("shortpass", "trans", "refl")])
def test_a_dichroic_mirror_splits_by_its_edge(band, short, long):
    mirror = DichroicMirror(cutoff_wavelength=700, pass_band=band)
    assert _ports(mirror, "in", 532) == [short]
    assert _ports(mirror, "in", 785) == [long]


def test_a_1x4_mmi_splits_evenly():
    mmi = MMI1x4()
    assert _ports(mmi, "o1", 1550) == ["o2", "o3", "o4", "o5"]
    assert _ports(mmi, "o3", 1550) == ["o1"]
