"""The cross-section panel: the cut controls, four looks (the schematic, the SEM-like image and the top view
when the server draws them, the 3D slab), an option row per look, a large view, a progress line. Static checks
on the editor source, as the other editor tests do."""

from __future__ import annotations

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "optodraw" / "app" / "static"


def _panel() -> str:
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    found = re.search(r'<div class="route-panel xs-panel" id="xs-panel".*?<!-- /xs-panel -->', html, re.S)
    assert found, "the cross-section panel is missing (or its end marker)"
    return found.group(0)


def _panel_script() -> str:
    source = (STATIC / "js" / "app.js").read_text(encoding="utf-8")
    found = re.search(r"// -- GDS cross-section panel.*?// -- Simulate panel", source, re.S)
    assert found, "the cross-section block of app.js is missing"
    return found.group(0)


def test_the_panel_has_four_looks_with_sem_and_top_hidden_until_the_server_lists_them():
    picker = re.search(r'<div class="segmented xs-looks" id="xs-looks".*?</div>', _panel(), re.S)
    assert picker, "the cross-section panel has no look picker"
    assert re.findall(r'data-look="(\w+)"', picker.group(0)) == ["schematic", "sem", "slab", "top"]
    for look in ("sem", "top"):
        assert re.search(rf'data-look="{look}"[^>]*\bhidden\b', picker.group(0))
    assert 'id="xs-findings"' in _panel()


def test_each_look_has_its_own_option_row():
    panel = _panel()
    rows = re.findall(r'class="xs-opt" data-for="(\w+)"', panel)
    assert rows == ["schematic", "sem", "slab", "top"]
    for control in ("xs-zscale", "xs-sem-mark", "xs-sem-noise", "xs-depth", "xs-cutaway", "xs-stage", "xs-tilt",
                    "xs-rot", "xs-top-mark"):
        assert f'id="{control}"' in panel, control


def test_the_cut_controls_live_in_the_panel():
    panel = _panel()
    for control in ("xs-cut-ruler", "xs-scan", "xs-expand", "xs-busy", "xs-top", "xs-cross"):
        assert f'id="{control}"' in panel, control
    inspector = (STATIC / "js" / "properties.js").read_text(encoding="utf-8")
    section = re.search(r"function gdsCrossSectionSection.*?\n  }\n", inspector, re.S).group(0)
    assert "Open cross-section" in section and 'type = "range"' not in section     # the scan moved to the panel


def test_the_panel_asks_for_each_look_with_its_options_and_shows_each_format():
    source = _panel_script()
    assert "look: xsLook" in source and "...xsLookOptions(" in source
    assert 'res.looks.includes("sem")' in source and 'res.looks.includes("top")' in source
    assert 'frame.sandbox = "allow-scripts"' in source and "frame.srcdoc = res.cross_section" in source
    assert "img.src = res.cross_section" in source
    assert "xsFindings" in source
    assert "xsFigure.clientWidth" in source                     # images rendered at the panel's size
    assert "xsLookOptions(xsLook, true)" in source              # saving renders the full size


def test_the_panel_shows_large_and_reports_progress():
    source = _panel_script()
    assert 'classList.toggle("expanded")' in source and '"Escape"' in source
    assert "xsBusy" in source and "xsFigure.classList" in source
    css = (STATIC / "css" / "app.css").read_text(encoding="utf-8")
    assert ".xs-panel.expanded" in css and "resize:" in css


def test_the_panel_text_has_no_dashes():
    inspector = (STATIC / "js" / "properties.js").read_text(encoding="utf-8")
    section = re.search(r"function gdsCrossSectionSection.*?\n  }\n", inspector, re.S).group(0)
    for text in (_panel(), _panel_script(), section):
        assert "—" not in text and "–" not in text
