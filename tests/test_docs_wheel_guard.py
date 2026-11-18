"""The wheel guard of the docs build (docs/scripts/build_wheel.py, rule D12) stops on a private word in any text
file of the wheel. A vendored engine (GDS Lens) carries its WebAssembly inline as escaped bytes, which read as
text hold "E:\\0" and the like: the drive-letter pattern does not apply there, every other pattern does."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _guard():
    spec = importlib.util.spec_from_file_location("build_wheel", ROOT / "docs" / "scripts" / "build_wheel.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_vendored_viewer_passes_the_guard():
    guard = _guard()
    name = "optodraw/renderers/js/vendor/gds-lens/gds-lens.js"
    text = (ROOT / name).read_text(encoding="utf-8", errors="ignore")
    assert guard.private_hit(name, text, guard.private_patterns()) is None


def test_a_drive_path_in_optodraw_itself_still_stops_the_build():
    guard = _guard()
    hit = guard.private_hit("optodraw/gds/layout.py", 'SOURCE = "C:\\Users\\someone\\chip.gds"', guard.private_patterns())
    assert hit is not None and "[A-Z]" in hit


def test_a_home_folder_in_a_vendored_file_still_stops_the_build():
    guard = _guard()
    hit = guard.private_hit("optodraw/renderers/js/vendor/gds-lens/gds-lens.js", "//# built in /Users/someone/src",
                            guard.private_patterns())
    assert hit == "/Users/"
