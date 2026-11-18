"""A pad draws at the size it is given: its port sits on its drawn edge, and a figure can use small pads."""

from __future__ import annotations

import pytest

from optodraw import ElectricalPad
from optodraw.layout import estimate_component_bounds


@pytest.mark.parametrize("size", [8.0, 12.0, 28.0, 60.0])
def test_a_pad_draws_at_its_width_and_height(size):
    pad = ElectricalPad(width=size, height=size)
    x0, y0, x1, y1 = estimate_component_bounds(pad)
    assert (x1 - x0, y1 - y0) == pytest.approx((size, size), abs=1e-6)
    assert pad.ports()["e1"].center.x == pytest.approx(x0)              # the wire ends on the drawn edge


@pytest.mark.parametrize("width,height,gap", [(20.0, 5.0, 3.0), (12.0, 12.0, 8.0), (40.0, 40.0, 10.0)])
def test_a_gsg_probe_pad_draws_its_pads_where_its_ports_are(width, height, gap):
    from optodraw import GSGProbePad

    gsg = GSGProbePad(pad_width=width, pad_height=height, gap=gap)
    x0, y0, x1, y1 = estimate_component_bounds(gsg)
    assert (x1 - x0, y1 - y0) == pytest.approx((width, 3 * height + 2 * gap), abs=1e-6)
    ports = gsg.ports()
    assert [ports[name].center.y for name in ("g1", "s", "g2")] == pytest.approx([height + gap, 0.0, -height - gap])
    assert ports["s"].center.x == pytest.approx(x0)                      # on the drawn edge


@pytest.mark.parametrize("name", ["TranslationStage", "Filter", "Iris", "Lamp", "CameraSensor"])
def test_a_painted_part_s_box_is_its_drawing_and_its_ports(name):
    """The box a layout and a label use is what is drawn (the art) plus where beams attach, not a larger plan."""

    import optodraw
    from optodraw.symbols.art import art_bounds

    part = getattr(optodraw, name)(label="")
    art = art_bounds(part)
    xs = [art[0], art[2]] + [float(p.center.x) for p in part.ports().values()]
    ys = [art[1], art[3]] + [float(p.center.y) for p in part.ports().values()]
    assert estimate_component_bounds(part) == pytest.approx((min(xs), min(ys), max(xs), max(ys)), abs=1e-6)
