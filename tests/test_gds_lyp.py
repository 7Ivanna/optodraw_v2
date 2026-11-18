"""A KLayout .lyp from a layer stack: the colours and names the layout view takes, from the one stack."""

from __future__ import annotations


from optodraw.gds.lyp import stack_to_lyp
from optodraw.gds.parsers import parse_klayout_lyp


def _parse(tmp_path, text):
    path = tmp_path / "t.lyp"
    path.write_text(text, encoding="utf-8")
    return parse_klayout_lyp(path, include_hidden=True)


def test_a_stack_round_trips_through_the_lyp(tmp_path):
    styles = {(1, 0): {"name": "WG", "color": "#ff9d9d"},
              "49/0": {"name": "M3", "color": "#7d6608", "stroke": "#333333"}}
    back = _parse(tmp_path, stack_to_lyp(styles))
    assert back[(1, 0)]["name"] == "WG" and back[(1, 0)]["color"] == "#ff9d9d"
    assert back[(49, 0)]["stroke"] == "#333333"


def test_a_hidden_layer_stays_hidden_and_a_layer_without_colour_is_left_out():
    text = stack_to_lyp({(46, 0): {"name": "PADOPEN", "visible": False, "color": "#000000"}, (99, 0): {"name": "X"}})
    assert "<visible>false</visible>" in text and "99/0" not in text


