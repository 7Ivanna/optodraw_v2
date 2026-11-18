"""The JavaScript optodraw ships is code, and gets checked like code.

The 3D runtime used to be thousand-line string literals inside
``threejs_renderer.py``, where no linter or editor could see it. Now that it
lives in ``.js`` files, a syntax error can be caught before it reaches a
browser — which for a renderer means before it reaches a blank page with a
console message nobody is reading.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parents[1] / "optodraw"
BUNDLED_JS = sorted(PACKAGE.rglob("*.js"))


def test_there_is_javascript_to_check():
    assert len(BUNDLED_JS) >= 10, "the front end and the 3D runtime both ship .js"


@pytest.mark.parametrize("path", BUNDLED_JS, ids=lambda p: p.name)
def test_every_shipped_script_parses(path: Path):
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed; cannot parse-check JavaScript")
    result = subprocess.run([node, "--check", str(path)], capture_output=True, text=True)
    assert result.returncode == 0, f"{path.name} does not parse:\n{result.stderr}"


def test_the_renderer_still_finds_its_runtime():
    """The files are read at import time; a rename would be silent otherwise."""

    from optodraw.renderers.threejs_renderer import _EDITOR_BRIDGE_JS, _LIGHT_PLAYER_JS

    assert "window.odLight" in _LIGHT_PLAYER_JS
    assert "optodraw-select" in _EDITOR_BRIDGE_JS


