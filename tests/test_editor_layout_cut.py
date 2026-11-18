"""Cuts from the Layout view's ruler: the cross-section panel's "Cut along ruler" posts the newest ruler in the
GDS file's frame, and the panel's cut is drawn back in the view as a ruler, again after the layout reloads."""

from __future__ import annotations

import pytest

from gds_layout_fixtures import docs_device_gds
from test_editor_layout_view import editor, needs_chrome  # noqa: F401  (the module-scoped editor fixture)

pytestmark = needs_chrome


def _open_layout_and_panel(editor, tmp_path):
    editor.open_with(docs_device_gds(tmp_path))
    editor.js("document.getElementById('btn-view-layout').click()")
    editor.drawn()
    editor.js("[...document.querySelectorAll('#props-form button')].find(b => b.textContent.includes('Open cross-section')).click()")
    editor.wait("!document.getElementById('xs-panel').hidden && !!document.querySelector('#xs-cross svg')")


def test_the_cut_button_shows_only_in_the_layout_view(editor, tmp_path):
    _open_layout_and_panel(editor, tmp_path)
    assert editor.js("!document.getElementById('xs-cut-ruler').hidden")
    editor.js("document.getElementById('btn-view-2d').click()")
    assert editor.js("document.getElementById('xs-cut-ruler').hidden")


def test_a_ruler_in_the_layout_view_makes_the_cut(editor, tmp_path):
    _open_layout_and_panel(editor, tmp_path)
    editor.js("(async () => { await gdsLens.clearMeasurements(); await gdsLens.addMeasurement(11, 11, 11, -11); })()")
    editor.js("document.getElementById('xs-cut-ruler').click()")
    editor.wait("document.getElementById('xs-sub').textContent.startsWith('Ruler')")
    assert "M3" in editor.js("document.getElementById('xs-cross').innerHTML")
    rulers = editor.wait("(async () => { const r = await gdsLens.getMeasurements(); return r.length ? r : null; })()")
    assert len(rulers) == 1 and rulers[0]["x0"] == pytest.approx(11.0, abs=1e-6)


def test_without_a_ruler_the_status_says_how_to_draw_one(editor, tmp_path):
    _open_layout_and_panel(editor, tmp_path)
    before = editor.js("document.getElementById('xs-sub').textContent")
    editor.js("(async () => { await gdsLens.clearMeasurements(); })()")
    editor.js("document.getElementById('xs-cut-ruler').click()")
    editor.wait("document.body.textContent.includes('Draw a ruler first')")
    assert editor.js("document.getElementById('xs-sub').textContent") == before


def test_the_cut_is_drawn_again_after_the_layout_reloads(editor, tmp_path):
    _open_layout_and_panel(editor, tmp_path)
    editor.js("(async () => { await gdsLens.clearMeasurements(); await gdsLens.addMeasurement(11, 11, 11, -11); })()")
    editor.js("document.getElementById('xs-cut-ruler').click()")
    editor.wait("document.getElementById('xs-sub').textContent.startsWith('Ruler')")
    editor.js("document.getElementById('btn-view-2d').click()")
    editor.js("document.getElementById('btn-view-layout').click()")
    rulers = editor.wait("(async () => { const r = await gdsLens.getMeasurements(); return r.length ? r : null; })()")
    assert len(rulers) == 1 and rulers[0]["y0"] == pytest.approx(11.0, abs=1e-6)
