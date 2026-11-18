"""The 3D animation is off until the Animate button is clicked, and the 3D page shows no light before the
editor says so. Static checks on the editor source, as the other editor tests do."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "optodraw"
STATIC = ROOT / "app" / "static"


def test_the_animate_button_starts_off():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    button = re.search(r'<button[^>]*id="btn-animate"[^>]*>', html).group(0)
    assert 'aria-pressed="false"' in button
    assert not re.search(r'class="[^"]*\bactive\b', button)
    assert "—" not in button and "–" not in button


def test_the_editor_animation_state_starts_off():
    source = (STATIC / "js" / "app.js").read_text(encoding="utf-8")
    state = re.search(r"const animState = \{[^}]*\}", source).group(0)
    assert "enabled: false" in state


def test_the_3d_page_holds_the_animation_until_the_editor_sends_its_state():
    bridge = (ROOT / "renderers" / "js" / "editor_bridge.js").read_text(encoding="utf-8")
    hold = bridge.find("odLight.setEnabled(false)")
    ready = bridge.find("type: 'optodraw-ready'")
    assert 0 <= hold < ready, "the bridge must hold the engine before it tells the editor it is ready"


def test_the_bridge_drives_odlight_and_the_animate_menu_lists_the_new_items():
    bridge = (ROOT / "renderers" / "js" / "editor_bridge.js").read_text(encoding="utf-8")
    assert "odLight" in bridge and "odAnim" not in bridge
    source = (STATIC / "js" / "app.js").read_text(encoding="utf-8")
    start = source.index("function buildAnimMenu()")
    menu = source[start:source.index("function toggleAnimMenu", start)]
    for label in ('<span>Look</span>', '"Pause" : "Play"', '"Speed"', '"Time"', '"Play tour"', '"Record video"', "Export GIF"):
        assert label in menu, label
    for gone in ("Heat", "RF", "X-ray", "Field style", "λ scale", "lambda", "xray"):
        assert gone not in menu, gone
    state = re.search(r"const animState = \{[^}]*\}", source).group(0)
    for gone in ("field:", "lambda", "heat", "rf:", "xray"):
        assert gone not in state, gone


def test_the_ready_handler_sets_the_world_before_the_light_takes_it():
    source = (STATIC / "js" / "app.js").read_text(encoding="utf-8")
    ready = source[source.index('data.type === "optodraw-ready"'):]
    ready = ready[:ready.index('data.type === "optodraw-camera"')]
    assert 0 <= ready.index("syncViewTo3d()") < ready.index("syncAnimTo3d()")


def test_the_time_slider_keeps_its_value():
    source = (STATIC / "js" / "app.js").read_text(encoding="utf-8")
    assert re.search(r"const animState = \{[^}]*time: 0", source)
    assert 'slider("Time", 0, 1000, 1, animState.time' in source


def test_the_editor_fetches_the_light_only_while_it_is_on():
    source = (STATIC / "js" / "app.js").read_text(encoding="utf-8")
    api = (STATIC / "js" / "api.js").read_text(encoding="utf-8")
    assert "/api/scene3d?light=1" in api
    refresh = source[source.index("async function refresh3D"):source.index("let savedTimer")]
    assert "withLight = animState.enabled || withTour" in refresh
    # the items first (no light), then the light only while it is on
    assert refresh.index("api.scene3d(false)") < refresh.index("if (!withLight) return true;") < refresh.index(
        "api.scene3d(true, withTour)")
    sync = source[source.index("async function syncAnimTo3d"):source.index("function syncAnimButton")]
    assert sync.index("await refresh3D()") < sync.index('postAnim("enabled"')


def test_the_bridge_hands_the_light_payload_to_the_rebuild():
    """The items may come with no light and the light pending; the light then comes alone, for the last items."""

    bridge = (ROOT / "renderers" / "js" / "editor_bridge.js").read_text(encoding="utf-8")
    assert "__odRebuild(d.items, d.light || null, !!d.pending)" in bridge
    assert "d.type === 'optodraw-light' && lastItems" in bridge and "odLight.build(d.light || null, lastItems" in bridge


def test_a_slow_older_refresh_cannot_draw_over_a_newer_one():
    source = (STATIC / "js" / "app.js").read_text(encoding="utf-8")
    refresh = source[source.index("async function refresh3D"):source.index("let savedTimer")]
    assert "const seq = ++refreshSeq" in refresh
    assert refresh.count("if (seq !== refreshSeq) return;") >= 3
    assert refresh.index("if (seq !== refreshSeq) return;") < refresh.index('postMessage({ type: "optodraw-rebuild"')


def test_a_failed_light_fetch_turns_the_toolbar_light_off():
    source = (STATIC / "js" / "app.js").read_text(encoding="utf-8")
    refresh = source[source.index("async function refresh3D"):source.index("let savedTimer")]
    assert refresh.index("animState.enabled = false") < refresh.index("syncAnimButton()") < refresh.index("No light:")


def test_the_animate_menu_offers_the_field_look():
    source = (STATIC / "js" / "app.js").read_text(encoding="utf-8")
    start = source.index("function buildAnimMenu()")
    menu = source[start:source.index("function toggleAnimMenu", start)]
    assert '["field", "Field"]' in menu
    assert "Field look: coming next" not in menu and "o.disabled = true" not in menu


def test_the_animate_menu_plays_the_tour_with_its_drive_tables():
    source = (STATIC / "js" / "app.js").read_text(encoding="utf-8")
    api = (STATIC / "js" / "api.js").read_text(encoding="utf-8")
    start = source.index("function buildAnimMenu()")
    menu = source[start:source.index("function toggleAnimMenu", start)]
    assert 'soon("Play tour")' not in menu and 'item("Play tour"' in menu and 'item("Record video"' in menu and 'soon(' not in menu
    play = source[source.index("async function playTour"):]
    play = play[:play.index("\n}\n") + 2]
    assert play.index("await refresh3D(true)") < play.index('postAnim("tour", true)')     # the drives come first
    assert "/api/scene3d?light=1&tour=1" in api


def test_a_failed_tour_fetch_has_its_own_message_and_keeps_the_light():
    source = (STATIC / "js" / "app.js").read_text(encoding="utf-8")
    refresh = source[source.index("async function refresh3D"):source.index("let savedTimer")]
    tour = refresh[refresh.index("if (withTour) {"):refresh.index("animState.enabled = false")]
    assert "No tour:" in tour and "return false" in tour and "animState.enabled" not in tour


def test_the_toolbar_shows_the_light_the_tour_turns_on():
    source = (STATIC / "js" / "app.js").read_text(encoding="utf-8")
    bridge = (ROOT / "renderers" / "js" / "editor_bridge.js").read_text(encoding="utf-8")
    assert "addEventListener('odtour'" in bridge and "type: 'optodraw-tour'" in bridge
    sync = source[source.index("function syncAnimButton"):source.index('animBtn.addEventListener("click"')]
    assert "animState.enabled || tourOn" in sync
    handler = source[source.index('data.type === "optodraw-tour"'):]
    assert handler.index("tourOn = !!data.playing") < handler.index("syncAnimButton()") < handler.index("optodraw-camera")
    click = source[source.index('animBtn.addEventListener("click"'):source.index("function buildAnimMenu")]
    assert click.index('if (tourOn) { postAnim("tour", false); return; }') < click.index("animState.enabled = !animState.enabled")


def test_record_video_in_the_animate_menu_starts_the_job_and_shows_its_progress():
    source = (STATIC / "js" / "app.js").read_text(encoding="utf-8")
    start = source.index("function buildAnimMenu()")
    menu = source[start:source.index("function toggleAnimMenu", start)]
    assert 'soon("Record video")' not in menu and 'item("Record video"' in menu
    job = source[source.index("async function recordVideo"):]
    job = job[:job.index("\n}\n")]
    assert "/api/render/video" in job and "Recording video: " in job and "setStatus(" in job
    assert "download" in job
    assert "start.status === 409" in job and 'fetch("/api/render/video")' in job      # a running job is followed
    assert "—" not in job and "–" not in job


def test_the_progress_text_is_a_percent_of_the_frames():
    import json
    import subprocess

    source = (STATIC / "js" / "app.js").read_text(encoding="utf-8")
    start = source.index("function videoProgressText")
    func = source[start:source.index("\n}\n", start) + 3]
    script = func + "\nconsole.log(JSON.stringify([videoProgressText({done: 4, total: 10}), videoProgressText({done: 0, total: 0})]));"
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True).stdout
    assert json.loads(out) == ["Recording video: 40 %", "Recording video: starting"]
