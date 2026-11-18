"""Build the optodraw wheel that the runnable cells install in the reader's browser (Pyodide).

optodraw is not on PyPI, so the site serves its own wheel from ``docs/public/wheels/``. The script removes the
older wheels, stops on a private word in any text file of the new one (rule D12), copies the display rule the
cells share (``cell_display.py``) next to it, and writes the wheel's address to ``docs/src/data/wheel.json``.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

DOCS = Path(__file__).resolve().parents[1]
ROOT = DOCS.parent


def private_patterns() -> list[re.Pattern]:
    """The patterns the page guard uses (``private-patterns.json``), plus the local words (``.private-words``)."""

    patterns = [re.compile(p) for p in json.loads((DOCS / "scripts" / "private-patterns.json").read_text())]
    local = DOCS / ".private-words"
    words = [w.strip() for w in local.read_text().splitlines() if w.strip()] if local.exists() else []
    return patterns + [re.compile(rf"\b{re.escape(w)}\b", re.IGNORECASE) for w in words]


# Vendored engines (GDS Lens) carry their WebAssembly inline as escaped bytes; read as text they hold "E:\0" and
# the like, so the drive-letter pattern does not apply to them. Every other pattern does.
VENDORED = "optodraw/renderers/js/vendor/"
DRIVE = r"\b[A-Z]:\\"


def private_hit(name: str, text: str, patterns: list[re.Pattern]) -> str | None:
    """The first private pattern a wheel file's text matches, or None."""

    text = re.sub(r"[A-Z]:\\Program Files", "", text)      # where a browser installs: not personal
    for pattern in patterns:
        if pattern.pattern == DRIVE and name.startswith(VENDORED):
            continue
        if pattern.search(text):
            return pattern.pattern
    return None


def build(public: Path = DOCS / "public", table: Path = DOCS / "src" / "data" / "wheel.json") -> Path:
    with tempfile.TemporaryDirectory() as out:
        subprocess.run(["uv", "build", "--wheel", "--out-dir", out], cwd=ROOT, check=True, capture_output=True)
        built = next(Path(out).glob("optodraw-*.whl"))
        patterns = private_patterns()
        with zipfile.ZipFile(built) as wheel:
            for name in wheel.namelist():
                if name.endswith((".png", ".jpg", ".whl", ".glb", ".woff2")):
                    continue
                hit = private_hit(name, wheel.read(name).decode("utf-8", errors="ignore"), patterns)
                if hit:
                    raise SystemExit(f"private content in the wheel: {name}: {hit}")
        wheels = public / "wheels"
        shutil.rmtree(wheels, ignore_errors=True)
        wheels.mkdir(parents=True)
        target = wheels / built.name
        shutil.copy2(built, target)
    (public / "py").mkdir(exist_ok=True)
    shutil.copy2(DOCS / "scripts" / "cell_display.py", public / "py" / "cell_display.py")
    table.write_text(json.dumps({"wheel": f"/wheels/{target.name}", "display": "/py/cell_display.py"}) + "\n")
    return target


if __name__ == "__main__":
    wheel = build()
    print(f"{wheel.name}: {wheel.stat().st_size / 1e6:.1f} MB", file=sys.stdout)
