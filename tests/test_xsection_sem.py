"""Look B: the cross-section as an SEM-like image that never passes as a measured one."""

from __future__ import annotations

from pathlib import Path

import pytest

from optodraw.gds.layout import GDSLayerRecord, GDSLayout
from optodraw.gds.xsection.model import cross_section

pytest.importorskip("PIL")


def _record(spec, polygons):
    return GDSLayerRecord(spec=spec, name=f"L{spec[0]}", description="", color="#000000", opacity=1.0,
                          thickness=0.22, zmin=0.0, material_preset="silicon", polygons=polygons, matched_pdk=False)


def _rect(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def _modulator():
    layout = GDSLayout(source_path=Path("t.gds"), cell_name="T", bounds=(-50, -50, 50, 50), layer_records=[
        _record((1, 0), [_rect(-20, -0.25, 20, 0.25)]), _record((3, 0), [_rect(-20, -3, 20, 3)]),
        _record((20, 0), [_rect(-20, -3, 20, 0)]), _record((21, 0), [_rect(-20, 0, 20, 3)]),
        _record((40, 0), [_rect(-20, -2.8, 20, -2.2)]), _record((41, 0), [_rect(-20, -3.2, 20, -1.8)])])
    return cross_section(layout, "gdsfactory_generic", ((0, -6), (0, 6)))


def _pixels(png: bytes):
    import io

    import numpy as np
    from PIL import Image

    return np.asarray(Image.open(io.BytesIO(png)).convert("L"), dtype=float)


def test_only_the_sem_look_draws_a_png():
    with pytest.raises(ValueError, match="svg"):
        _modulator().png(look="schematic")


