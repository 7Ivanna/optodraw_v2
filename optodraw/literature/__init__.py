"""Figures of the literature, rebuilt with optodraw: each module draws one published figure and cites it.

Every module has ``build(title=...) -> Scene`` and a ``PAPER`` dict (citation, DOI, figure). The figures are
compact schematics, not to scale: the topology and the wiring follow the paper, the sizes are optodraw's
schematic sizes. The presets in :mod:`optodraw.presets` are built from these modules.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

FIGURES = {
    # chips
    "faralli2015_receiver": "Coherent receiver without waveguide crossing (Faralli et al. 2015, Fig. 1)",
    "tait2017_broadcast_weight": "Broadcast-and-weight network (Tait et al. 2017, Fig. 1a)",
    "mak2015_ring_filter": "Fifth-order microring filter (Mak et al. 2015, Fig. 1a and 7)",
    # free-space benches
    "sahoo2026_confocal_pl": "Micro-photoluminescence setup (Sahoo et al. 2026, Fig. 5)",
    "mcnairn2021_raman": "Raman micro-spectroscopy setup (McNairn et al. 2021, Fig. 2a)",
    "ni2020_ftir": "Michelson FTIR interferometer (Ni et al. 2020, Fig. 1)",
    "wirthl2021_polarimeter": "Self-calibrating polarimeter (Wirthl et al. 2021, Fig. 3a)",
    "schaefer2007_qwp_polarimeter": "Rotating quarter-wave plate polarimeter (Schaefer et al. 2007, Fig. 3)",
}


def build(name: str, **kwargs: Any):
    """The scene of one figure by its module name (see ``FIGURES``)."""

    if name not in FIGURES:
        raise KeyError(f"Unknown figure '{name}'. Available: {', '.join(FIGURES)}")
    return import_module(f"{__name__}.{name}").build(**kwargs)
