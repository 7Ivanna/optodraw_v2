"""Photon counting parts: a fibre-coupled single-photon counting module and a coincidence counter."""

from __future__ import annotations

import pytest

import optodraw


def _kinds(part) -> dict[str, str]:
    return {name: port.kind for name, port in part.ports().items()}


@pytest.mark.parametrize("cls", [optodraw.PhotonCounter, optodraw.CoincidenceCounter])
def test_a_counter_has_one_to_eight_channels(cls):
    with pytest.raises(ValueError):
        cls(channels=0)
    with pytest.raises(ValueError):
        cls(channels=9)


