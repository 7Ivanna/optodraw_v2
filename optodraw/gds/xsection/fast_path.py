"""Fast flat z/thickness preview using matplotlib (debug only)."""

from __future__ import annotations

from typing import Any

from optodraw.gds.layout import GDSLayout, GDSSection
from optodraw.gds.plotting import plot_gds_cross_section


def plot_flat_cross_section_preview(
    layout: GDSLayout,
    section: GDSSection | dict[str, Any],
    *,
    ax=None,
    z_exaggeration: float = 28.0,
):
    """Matplotlib preview for BlenderGDS-style flat depth stacks (not publication output)."""
    return plot_gds_cross_section(
        layout,
        section,
        ax=ax,
        z_exaggeration=z_exaggeration,
    )
