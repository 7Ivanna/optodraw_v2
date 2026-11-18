"""innerHTML sinks in the editor must escape user-controlled text.

Component ids come from user edits and layer names from uploaded techfiles,
so any template that interpolates them into HTML is an injection sink. These
tests pin the escaping at each known sink, following the same static-source
style as test_editor_feedback_links.py.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "optodraw" / "app" / "static" / "js"


def _source(name: str) -> str:
    return (JS / name).read_text(encoding="utf-8")


def test_properties_title_row_escapes_component_id():
    source = _source("properties.js")
    assert "esc(id)" in source
    # the raw interpolation must be gone
    assert not re.search(r"pt-id\">\$\{id\}", source)


def test_gds_layer_names_never_reach_innerHTML_raw():
    source = _source("properties.js")
    assert "${ly.name}" not in source
    # the layer label is built with textContent instead
    assert 'nameEl.textContent = ly.name' in source


def test_palette_display_names_are_escaped():
    source = _source("palette.js")
    assert "esc(shown)" in source
    assert "${shown}" not in source


def test_command_palette_escapes_workspace_and_preset_labels():
    source = _source("app.js")
    assert "label: escHtml(presetTitle(name))" in source
    assert "label: escHtml(w)" in source


def test_escape_helpers_cover_the_full_dangerous_set():
    for name in ("properties.js", "palette.js"):
        helper = re.search(r"replace\(/\[&<>\"]+/g", _source(name))
        assert helper, f"{name}: escape helper missing & < > handling"
