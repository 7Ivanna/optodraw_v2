"""The editor at laptop widths: the layer list shows every number whole and the toolbar labels keep a gap."""

from __future__ import annotations

import time

import pytest

from gds_layout_fixtures import docs_device_gds
from test_editor_layout_view import editor, needs_chrome  # noqa: F401  (the module-scoped editor fixture)

CHECK = """(() => {
  const nums = [...document.querySelectorAll('.gds-layer-card input.gds-num')];
  const bar = [...document.querySelectorAll('#btn-trace, #btn-simulate, #btn-check')].map(b => b.getBoundingClientRect());
  return {nums: nums.length, cut: nums.filter(i => i.scrollWidth > i.clientWidth).map(i => i.value),
          gaps: [bar[1].left - bar[0].right, bar[2].left - bar[1].right],
          squeezed: [...document.querySelectorAll('#btn-trace, #btn-simulate, #btn-check')].filter(b => b.scrollWidth > b.clientWidth).length,
          tagLines: [...document.querySelectorAll('.ctx-count')].map(s => {     // the text's line boxes
            const r = document.createRange(); r.selectNodeContents(s);
            return new Set([...r.getClientRects()].map(b => Math.round(b.top))).size; })};
})()"""


@needs_chrome
@pytest.mark.parametrize("size", [(1200, 800), (1440, 900)])
def test_layer_numbers_show_whole_and_toolbar_labels_keep_a_gap(editor, tmp_path, size):  # noqa: F811
    editor.open_with(docs_device_gds(tmp_path))
    editor.js("document.getElementById('btn-view-layout').click()")
    editor.wait("document.querySelectorAll('.gds-layer-card input.gds-num').length > 0")
    editor.pipe.call("Emulation.setDeviceMetricsOverride", {"width": size[0], "height": size[1], "deviceScaleFactor": 1,
                                                            "mobile": False}, editor.session)
    time.sleep(0.5)
    seen = editor.js(CHECK)
    assert seen["nums"] > 0
    assert seen["cut"] == [], f"cut numbers: {seen['cut']}"
    assert seen["squeezed"] == 0
    assert min(seen["gaps"]) >= 2, f"toolbar buttons touch: {seen['gaps']}"
    editor.js("document.querySelector('#outline-list .ol-row, .ol-row')?.click()")   # select the GDS: its name in the bar
    time.sleep(0.3)
    seen = editor.js(CHECK)
    assert seen["tagLines"] and all(lines <= 1 for lines in seen["tagLines"]), f"the selection name wraps: {seen['tagLines']}"
