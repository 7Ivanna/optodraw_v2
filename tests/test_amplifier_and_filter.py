"""The amplifier and the electrical filter of a block diagram: a Pound-Drever-Hall loop or an optoelectronic
oscillator needs both. The shared circuit contract (catalog, ports, exact 1D symbol, leads that end on their ports,
3D package, save and load) is in test_circuit_parts.py; this file holds what is their own."""

from __future__ import annotations

import pytest

from optodraw import RFFilter


def test_an_unknown_response_is_refused():
    with pytest.raises(ValueError, match="response"):
        RFFilter(response="notch")


