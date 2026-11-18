"""Every part has a 1D symbol, or is on the list of parts that still wait for one.

The list only shrinks: a part that gets its symbol must leave the list, and a
part that loses its symbol fails here.
"""

from __future__ import annotations

from pathlib import Path

import optodraw  # noqa: F401  (fills the registry)
from optodraw.core.component import ANNOTATION_TYPES
from optodraw.registry import build_component, component_registry
from optodraw.symbols import lookup

# In the registry, but not a part: light paths, routes, the grid, the chip
# substrate, and the wrappers that draw a file the user supplies.
NOT_PARTS = {"Beam", "Route", "Grid", "ChipSubstrate", "CustomModel", "GDSModel"} | ANNOTATION_TYPES
WAITING = Path(__file__).with_name("symbols_waiting.txt")


def _waiting() -> set[str]:
    return {line.strip() for line in WAITING.read_text(encoding="utf-8").splitlines() if line.strip()}


def _sources() -> dict[str, str]:
    return {name: lookup(build_component(name)).source for name in sorted(component_registry()) if name not in NOT_PARTS}


def test_every_part_has_a_symbol_that_carries_its_ports():
    for name in sorted(component_registry()):
        if name in NOT_PARTS:
            continue
        part = build_component(name)
        symbol = lookup(part)
        assert symbol.svg.startswith("<svg") and symbol.width > 0 and symbol.height > 0, name
        assert set(symbol.ports) == set(part.ports()), name


def test_the_waiting_list_is_exact():
    blocks = {name for name, source in _sources().items() if source == "block"}
    waiting = _waiting()
    assert blocks - waiting == set(), "these parts lost their 1D symbol (or are new and need one)"
    assert waiting - blocks == set(), "these parts have a symbol now: remove them from tests/symbols_waiting.txt"


def test_the_first_symbols_are_exact():
    sources = _sources()
    for name in ("Waveguide", "MZM", "MicroringResonator", "PNMicroringModulator", "OnChipPhotodetector",
                 "OnChipBalancedPhotodetector", "MMI1x2", "MMI2x2", "StarCoupler", "AWG", "AWGR",
                 "OnChipLaser", "DBRLaser", "SOA", "YBranch", "DirectionalCoupler", "MZI", "PhaseShifter",
                 "VerticalGratingCoupler", "EdgeCoupler", "DAC", "ADCBlock", "TIA", "RFDriver"):
        assert sources[name] == "prebuilt", name
