"""A racetrack's 1D symbol follows its options: with or without a drop bus, a heater, or a PN junction, the 1D view
draws the racetrack with the ports the part has, never a labelled block."""

from __future__ import annotations

import pytest

from optodraw import RacetrackModulator, RacetrackResonator
from optodraw.symbols import lookup

_OPTIONS = [(RacetrackResonator, {}), (RacetrackResonator, {"add_drop": True}),
            (RacetrackResonator, {"with_heater": True}), (RacetrackResonator, {"add_drop": True, "with_heater": True}),
            (RacetrackModulator, {}), (RacetrackModulator, {"add_drop": False}),
            (RacetrackModulator, {"add_drop": False, "with_heater": False}), (RacetrackModulator, {"with_heater": False})]


@pytest.mark.parametrize("cls, options", _OPTIONS, ids=[f"{c.__name__}-{'-'.join(o) or 'default'}" for c, o in _OPTIONS])
def test_every_racetrack_option_has_its_exact_symbol(cls, options):
    # mutant: delete RacetrackResonator.symbol_1d: the class row serves every option, and five fall back to a block
    part = cls(**options)
    symbol = lookup(part)
    assert symbol.exact, f"{cls.__name__}({options}) draws {symbol.source}"
    assert {n: p.kind for n, p in symbol.ports.items()} == {n: p.kind for n, p in part.ports().items()}
