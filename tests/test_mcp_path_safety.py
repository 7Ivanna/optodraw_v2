"""MCP tools must not write outside allowed directories.

The server runs with user privileges; a prompt-injected argument that points
at /etc or another user's home must fail loudly. Roots: cwd, home, system
temp, plus OPTODRAW_MCP_ALLOWED_ROOTS.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from optodraw.mcp_server import _safe_output_path, dispatch_tool

SPEC = {
    "title": "Path safety",
    "components": [{"type": "Laser", "center": [0, 0], "id": "l1"}],
    "beams": [],
}


class TestSafeOutputPath:
    def test_relative_paths_stay_under_cwd(self):
        resolved = _safe_output_path("figures/setup.svg", "output_svg")
        assert resolved == (Path.cwd() / "figures" / "setup.svg").resolve()


    def test_outside_roots_is_rejected(self):
        with pytest.raises(ValueError, match="outside the directories"):
            _safe_output_path("/optodraw-denied/evil.svg", "output_svg")

    def test_extra_root_via_env(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OPTODRAW_MCP_ALLOWED_ROOTS", str(tmp_path))
        resolved = _safe_output_path(tmp_path / "ok.svg", "output_svg")
        assert resolved.name == "ok.svg"


class TestToolSurface:
    def test_unknown_tool_raises_instead_of_replying_text(self):
        with pytest.raises(ValueError, match="Unknown tool 'nope'"):
            dispatch_tool("nope", {})

    def test_render_3d_inside_tmp_succeeds(self, tmp_path):
        target = tmp_path / "scene3d" / "out.html"
        payload = json.loads(
            dispatch_tool("optodraw_render_3d", {"spec": SPEC, "output_path": str(target)})
        )
        assert Path(payload["output_path"]).is_file()


