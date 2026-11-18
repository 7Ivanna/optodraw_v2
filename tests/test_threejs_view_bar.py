"""The 3D page's controls: one slim bar at the bottom of a standalone page, nothing inside the editor's view,
nothing in a capture. Light starts off; labels start off."""

from __future__ import annotations

import re
from pathlib import Path

from optodraw import Beam, Laser, Lens, Photodiode, Scene

PLAYER = Path(__file__).resolve().parents[1] / "optodraw" / "renderers" / "js" / "light_player.js"


def _scene() -> Scene:
    scene = Scene(title="Bench", width=200, height=100)
    laser = scene.add(Laser(center=(0, 0)))
    lens = scene.add(Lens(center=(60, 0)))
    pd = scene.add(Photodiode(center=(120, 0)))
    scene.add(Beam(laser, lens, pd))
    return scene


def _bar(html: str) -> str:
    found = re.search(r'<div id="od-bar".*?<!-- /od-bar -->', html, re.S)
    assert found, "the page has no bar"
    return found.group(0)


def test_a_standalone_page_has_one_bar_and_no_panel_stack():
    html = _scene().render_threejs()
    bar = _bar(html)
    assert 'id="export-toolbar"' not in html and "section-label" not in html
    assert "<summary>Controls</summary>" not in html
    for control in ('id="btn-export-png"', 'id="btn-export-png-clear"', 'id="btn-export-glb"', 'id="btn-export-json"',
                    'data-camera-preset="isometric"', 'data-world="light"', 'data-world="dark"', 'data-world="none"',
                    'id="world-table-color"', 'id="btn-labels"', 'id="btn-fullscreen"', 'id="btn-pathtrace"',
                    'id="anim-section"', 'id="anim-toggle"', 'id="light-look"', 'id="anim-play"', 'id="anim-speed"',
                    'id="anim-scrub"', 'id="light-tour"', 'id="light-record"'):
        assert control in bar, control
    assert len(re.findall(r'aria-haspopup="true"', bar)) >= 5      # camera, world, light, save, more
    assert "—" not in bar and "–" not in bar
    assert re.search(r'<div id="info">\s*<h3>Bench</h3>\s*</div>', html)   # the title alone


def test_the_editor_view_has_no_chrome_but_keeps_the_functions():
    html = _scene().render_threejs(editable=True)
    assert 'id="od-bar"' not in html and 'id="export-toolbar"' not in html and 'id="info"' not in html
    for function in ("function applyCameraPreset", "function applyWorld", "function downloadPngScreenshot",
                     "function downloadGlb", "function downloadSceneJson", "function odStartRender",
                     "function odToggleFullscreen", "function setLabels"):
        assert function in html, function
    assert 'id="render-overlay"' in html                            # the Photoreal progress and Save


def test_a_capture_and_a_page_without_controls_draw_no_bar():
    from optodraw.renderers.threejs_renderer import ThreeJsRenderer

    assert 'id="od-bar"' not in ThreeJsRenderer(_scene(), capture={"width": 400, "height": 300}).render()
    plain = _scene().render_threejs(show_export_controls=False)
    assert 'id="od-bar"' not in plain and "function downloadPngScreenshot" not in plain


def test_light_starts_off_and_animate_turns_it_on():
    player = PLAYER.read_text(encoding="utf-8")
    state = re.search(r"const S = \{.*?\};", player, re.S).group(0)
    assert "enabled: false" in state and "playing: false" in state
    assert "odLight.setEnabled(true)" not in _scene().render_threejs()
    assert "odLight.setEnabled(true)" in _scene().render_threejs(animate=True)


def test_labels_start_off():
    bar = _bar(_scene().render_threejs())
    labels = re.search(r'<button[^>]*id="btn-labels"[^>]*>', bar).group(0)
    assert 'aria-pressed="false"' in labels
    on = _bar(_scene().render_threejs(show_labels=True))
    assert 'aria-pressed="true"' in re.search(r'<button[^>]*id="btn-labels"[^>]*>', on).group(0)


def test_the_light_menu_has_the_new_controls_and_none_of_the_old():
    bar = _bar(_scene().render_threejs())
    for gone in ("anim-field", "anim-lambda", "anim-heat", "anim-rf", "anim-xray", "anim-record"):
        assert f'id="{gone}"' not in bar, gone
    look = re.search(r'<select[^>]*id="light-look".*?</select>', bar, re.S).group(0)
    assert re.search(r'<option value="light"[^>]*>Light</option>', look)
    field = re.search(r'<option value="field"[^>]*>Field</option>', look.replace("\n", " "))
    assert field and "disabled" not in field.group(0) and "coming next" not in look     # the Field look is ready
    assert "selected" in re.search(r'<option value="light"[^>]*>', look).group(0)
    chosen = re.search(r'<select[^>]*id="light-look".*?</select>', _bar(_scene().render_threejs(look="field")), re.S).group(0)
    assert "selected" in re.search(r'<option value="field"[^>]*>', chosen).group(0)
    assert "selected" not in re.search(r'<option value="light"[^>]*>', chosen).group(0)
    tour = re.search(r'<button[^>]*id="light-tour"[^>]*>', bar).group(0)
    record = re.search(r'<button[^>]*id="light-record"[^>]*>', bar).group(0)
    assert "disabled" not in tour and 'title="Play tour: the camera follows the light from device to device"' in tour
    assert "coming next" not in record and "has no part labels" in record and "MP4" in record
    assert "—" not in bar and "–" not in bar
