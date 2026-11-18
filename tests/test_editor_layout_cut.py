"""Cuts from the Layout view's ruler: the cross-section panel's "Cut along ruler" posts the newest ruler in the
GDS file's frame, and the panel's cut is drawn back in the view as a ruler, again after the layout reloads."""

from __future__ import annotations


from gds_layout_fixtures import docs_device_gds
from test_editor_layout_view import editor, needs_chrome  # noqa: F401  (the module-scoped editor fixture)

pytestmark = needs_chrome


def _open_layout_and_panel(editor, tmp_path):
    editor.open_with(docs_device_gds(tmp_path))
    editor.js("document.getElementById('btn-view-layout').click()")
    editor.drawn()
    editor.js("[...document.querySelectorAll('#props-form button')].find(b => b.textContent.includes('Open cross-section')).click()")
    editor.wait("!document.getElementById('xs-panel').hidden && !!document.querySelector('#xs-cross svg')")


def test_without_a_ruler_the_status_says_how_to_draw_one(editor, tmp_path):
    _open_layout_and_panel(editor, tmp_path)
    before = editor.js("document.getElementById('xs-sub').textContent")
    editor.js("(async () => { await gdsLens.clearMeasurements(); })()")
    editor.js("document.getElementById('xs-cut-ruler').click()")
    editor.wait("document.body.textContent.includes('Draw a ruler first')")
    assert editor.js("document.getElementById('xs-sub').textContent") == before


