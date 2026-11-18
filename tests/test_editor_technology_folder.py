"""Attach technology folder in a real editor page (headless Chrome): the browser's folder dialog picks a KLayout
technology folder, the editor sends only its .lyt, .lyp and .lyd25 files, and the part gets the .lyp's colours and
the d25 heights. The status line says what was applied."""

from __future__ import annotations

import shutil
import time
from pathlib import Path

import pytest

from gds_layout_fixtures import docs_device_gds
from test_editor_layout_view import editor, needs_chrome  # noqa: F401  (the module-scoped editor fixture)

TECH = Path(__import__("gdsfactory").__file__).parent / "generic_tech" / "klayout"

RECORD_UPLOADS = """(() => {
  window.__sent = [];
  const send = window.fetch;
  window.fetch = (url, options) => {
    if (String(url).includes("/technology_folder")) window.__sent.push(...JSON.parse(options.body).files.map((f) => f.path));
    return send(url, options);
  };
})()"""


@needs_chrome
def test_a_folder_picked_in_the_folder_dialog_gives_colours_and_heights(editor, tmp_path):
    folder = tmp_path / "klayout"
    shutil.copytree(TECH, folder)                         # with its DRC, LVS, macros and xsection scripts
    (folder / "library.gds").write_bytes(b"\0" * 4096)    # a GDS library stays on disk
    gid = editor.open_with(docs_device_gds(tmp_path))
    editor.js("document.getElementById('btn-view-layout').click()")          # opening it selects the part
    link = "[...document.querySelectorAll('.gds-stack-links a')].find((a) => a.textContent === 'Attach technology folder')"
    editor.wait(f"!!{link}")
    editor.js(RECORD_UPLOADS)
    editor.js(f"{link}.click()")
    root = editor.pipe.call("DOM.getDocument", {}, editor.session)["root"]["nodeId"]
    node = editor.pipe.call("DOM.querySelector", {"nodeId": root, "selector": "#folder-tech"}, editor.session)["nodeId"]
    editor.pipe.call("DOM.setFileInputFiles", {"nodeId": node, "files": [str(folder)]}, editor.session)
    status = editor.wait("(() => { const t = document.getElementById('status').textContent;"
                         " return t.startsWith('Applied') ? t : null; })()")
    assert "tech layer" in status                          # the Layout view's reload does not write over it
    sent = editor.js("window.__sent")
    assert {"klayout/tech.lyt", "klayout/layers.lyp", "klayout/d25/generic_tech.lyd25"} <= set(sent)
    assert all(path.endswith((".lyt", ".lyp", ".lyd25")) for path in sent)
    metal3 = next(r for r in editor.api("GET", f"/api/gds/{gid}/layers")["layers"] if r["key"] == "49/0")
    assert metal3["z"] == pytest.approx(3.2) and metal3["thickness"] == pytest.approx(2.0)


@needs_chrome
def test_the_inspector_says_no_height_assigned_and_keeps_it_unassigned(editor, tmp_path):
    """A layer with no height shows "No height assigned" and empty th and z fields, not the part's default; hiding
    it writes the visibility only, so no made-up height becomes a real one."""

    gid = editor.open_with(docs_device_gds(tmp_path))
    editor.js("document.getElementById('btn-view-layout').click()")          # opening it selects the part
    card = ("[...document.querySelectorAll('.gds-layer-card')]"
            ".find((c) => c.querySelector('.gds-layer-label').textContent.endsWith('20/0'))")
    editor.wait(f"!!{card}")
    shown = editor.js(f"(() => {{ const c = {card}; const m = c.querySelector('.gds-mat');"
                      f" return {{ fields: [...c.querySelectorAll('.gds-num')].map((i) => i.value),"
                      f" material: m.options[m.selectedIndex].textContent,"
                      f" note: (c.querySelector('.gds-layer-note') || {{}}).textContent || '' }}; }})()")
    assert shown["fields"] == ["", ""] and "No height assigned" in shown["note"]
    assert shown["material"] == "none" and "No material assigned" in shown["note"]
    editor.js(f"{card}.querySelector('input[type=checkbox]').click()")

    def written():
        entry = next(c for c in editor.api("GET", "/api/scene")["components"] if c["id"] == gid)
        return (entry.get("layer_stack") or {}).get("20/0")

    end = time.monotonic() + 30
    while time.monotonic() < end and not written():
        time.sleep(0.3)
    assert written()["visible"] is False and "thickness" not in written() and "z_offset" not in written()
