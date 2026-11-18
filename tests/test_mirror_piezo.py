"""A mirror on piezo actuators: a stack that moves it along its normal, or a mount that tips, tilts and pushes it."""

from __future__ import annotations

import pytest

from optodraw import ConcaveMirror, Mirror, check_part_3d
from optodraw.symbols import lookup
from optodraw.symbols.art import art_2d


def test_true_means_a_stack_and_an_unknown_mount_is_refused():
    assert Mirror(piezo=True).piezo == "stack" and Mirror(piezo=False).piezo is None
    with pytest.raises(ValueError, match="piezo"):
        Mirror(piezo="ring")


def test_a_stack_holds_the_mirror_out_of_its_mount_and_a_3axis_mount_has_three_actuators():
    def solids(part, role):
        return [c for c in part.geometry_3d()["children"] if c.get("role") == role]

    assert len(solids(Mirror(piezo="stack"), "piezo")) == 1
    assert len(solids(Mirror(piezo="3axis"), "piezo")) == 3 and not solids(Mirror(piezo="3axis"), "knob")
    assert solids(Mirror(), "knob") and not solids(Mirror(), "piezo")
    for part in (Mirror(piezo="stack"), Mirror(piezo="3axis"), ConcaveMirror(piezo="stack"), ConcaveMirror(piezo="3axis")):
        assert check_part_3d(part) == []


@pytest.mark.parametrize("part", [Mirror(piezo="stack"), Mirror(piezo="3axis"), ConcaveMirror(piezo="stack"),
                                  ConcaveMirror(piezo="3axis")], ids=lambda p: f"{p.component_type}-{p.piezo}")
def test_its_symbol_draws_the_piezo_and_its_art_fits_both_ports(part):
    # needs the symbol library rebuilt with the rows of variants.toml (python -m optodraw.symbols.build)
    symbol = lookup(part)
    assert symbol.exact and symbol.params.get("pzt") == part.piezo and set(symbol.ports) == {"io", "pzt"}
    art = art_2d(part)
    assert art is not None and art["residual"] < 0.02                  # the plan and the pic agree


