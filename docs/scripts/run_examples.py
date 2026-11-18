"""Run every example cell of the site in CPython and save what each one shows.

A page's cells live in ``docs/examples/<page>/NN-name.py`` and run in order in one namespace, like a notebook.
The first comment line is the cell's title. A line ``# browser: no (why)`` marks a cell that cannot run in the
browser; the site then shows only its saved output. Outputs go to ``docs/public/examples/<page>/`` and the cell
table to ``docs/src/data/cells.json``. Run from anywhere: the cells run with the repository root as the folder.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

DOCS = Path(__file__).resolve().parents[1]
ROOT = DOCS.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

from cell_display import run_cell, views  # noqa: E402


def read_cell(path: Path) -> dict:
    lines = path.read_text(encoding="utf-8").splitlines()
    browser, why = True, ""
    if lines and lines[0].startswith("# browser: no"):
        browser, why = False, lines[0].split("(", 1)[-1].rstrip(")") if "(" in lines[0] else ""
        lines = lines[1:]
    title = lines[0].lstrip("# ").strip() if lines and lines[0].startswith("#") else path.stem
    return {"title": title, "code": "\n".join(lines).strip() + "\n", "browser": browser, "why": why}


def run(examples: Path = DOCS / "examples", public: Path = DOCS / "public" / "examples",
        table: Path = DOCS / "src" / "data" / "cells.json") -> dict:
    cells: dict[str, dict] = {}
    shutil.rmtree(public, ignore_errors=True)                     # outputs of cells that are gone, gone too
    here = os.getcwd()
    os.chdir(ROOT)
    try:
        for page in sorted(p for p in examples.iterdir() if p.is_dir()):
            namespace: dict = {"__name__": "__main__"}
            for path in sorted(page.glob("*.py")):
                cell = read_cell(path)
                key = f"{page.name}/{path.stem}"
                try:
                    shown = run_cell(cell["code"], namespace)
                except Exception as error:
                    raise RuntimeError(f"example {key} failed: {type(error).__name__}: {error}") from error
                cell.update(kind=shown["kind"], stdout=shown["stdout"], output=None, text="")
                if shown["kind"] in ("svg", "html"):
                    target = public / page.name / f"{path.stem}.{shown['kind']}"
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(shown["data"], encoding="utf-8")
                    cell["output"] = f"/examples/{page.name}/{target.name}"
                elif shown["kind"] == "png":
                    target = public / page.name / f"{path.stem}.png"
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(shown["data"])
                    cell["output"] = f"/examples/{page.name}/{target.name}"
                elif shown["kind"] == "text":
                    cell["text"] = shown["data"]
                variants = {}
                for mode, data in views(namespace.get("scene"), shown).items():
                    target = public / page.name / f"{path.stem}-{mode}.{'html' if mode == '3d' else 'svg'}"
                    target.write_text(data, encoding="utf-8")
                    variants[mode] = f"/examples/{page.name}/{target.name}"
                if variants:
                    cell["variants"] = variants
                cells[key] = cell
    finally:
        os.chdir(here)
    table.parent.mkdir(parents=True, exist_ok=True)
    table.write_text(json.dumps(cells, indent=1) + "\n", encoding="utf-8")
    return cells


if __name__ == "__main__":
    import warnings

    warnings.simplefilter("ignore")
    done = run()
    print(f"{len(done)} cells: " + ", ".join(f"{k} ({v['kind']})" for k, v in done.items()))
