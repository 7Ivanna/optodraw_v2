"""The look of the light in the editor: one row of Scene settings for the whole figure, and two fields for one beam."""

from __future__ import annotations

from test_editor_layout_view import editor, needs_chrome  # noqa: F401  (the module-scoped editor fixture)

pytestmark = needs_chrome


def _open_with_a_beam(editor) -> str:
    editor.api("POST", "/api/scene/new", {})
    laser = editor.api("POST", "/api/component", {"name": "Laser", "params": {"center": [-40, 0]}})["id"]
    pd = editor.api("POST", "/api/component", {"name": "Photodiode", "params": {"center": [40, 0], "angle": 180}})["id"]
    beam = editor.api("POST", "/api/beam", {"path": [laser, pd]})["id"]
    editor.pipe.call("Page.navigate", {"url": editor.base + "/"}, editor.session)
    editor.wait("(() => { const tab = document.getElementById('tab-outline'); if (tab) tab.click();"
                f" return !!document.querySelector('.ol-row[data-id=\"{beam}\"]'); }})()")   # the page may still be loading
    editor.js("document.getElementById('welcome').hidden = true")
    return beam


def _field(editor, label: str):
    return (f"[...document.querySelectorAll('#props-form .field, #props-form label, #props-form div')]"
            f".find(e => e.textContent.trim().startsWith('{label}')).querySelector('input')")


def test_a_beam_shows_its_opacity_and_its_lane(editor):
    beam = _open_with_a_beam(editor)
    editor.js(f"document.querySelector('.ol-row[data-id=\"{beam}\"]').click()")
    editor.wait("document.getElementById('props-form').textContent.includes('lane')")
    assert editor.js(f"{_field(editor, 'opacity')}.placeholder") == "from Scene settings"


def test_the_opacity_field_reaches_the_beam(editor):
    beam = _open_with_a_beam(editor)
    editor.js(f"document.querySelector('.ol-row[data-id=\"{beam}\"]').click()")
    editor.wait("document.getElementById('props-form').textContent.includes('lane')")
    editor.js(f"(() => {{ const i = {_field(editor, 'opacity')}; i.value = '0.3';"
              " i.dispatchEvent(new Event('change', {bubbles: true})); })()")
    end = editor.wait(f"fetch('/api/scene').then(r => r.json()).then(s => "
                      f"s.beams.find(b => b.id === '{beam}').opacity === 0.3)")
    assert end is True


def test_scene_settings_set_the_style_of_every_beam(editor):
    _open_with_a_beam(editor)
    editor.js("document.getElementById('btn-scene').click()")
    editor.wait("[...document.querySelectorAll('label')].some(l => l.textContent.startsWith('Beam opacity'))")
    editor.js("(() => { const l = [...document.querySelectorAll('label')].find(x => x.textContent.startsWith('Beam opacity'));"
              " const i = document.getElementById(l.htmlFor); i.value = '0.35'; })()")
    editor.js("[...document.querySelectorAll('.od-primary')].filter(b => b.textContent.trim() === 'Apply').at(-1).click()")
    assert editor.wait("fetch('/api/scene').then(r => r.json()).then(s => s.beam_style && s.beam_style.opacity === 0.35)")
