"""The site's facts, from the package itself: every number a page shows comes from here (rule D5).

Writes ``docs/src/data/site-data.json``: ``values`` (single numbers for ``<!-- value: id -->`` markers),
``blocks`` (Markdown tables for ``<!-- data: id -->`` markers) and ``parts`` (the part catalogue, also read
by the landing-page picker).
"""

from __future__ import annotations

import json
import warnings
from collections import Counter
from pathlib import Path

DOCS = Path(__file__).resolve().parents[1]
PLATFORMS = {"free_space": "Free space", "on_chip": "On chip", "mixed": "Both"}


def collect() -> dict:
    warnings.simplefilter("ignore")
    import optodraw
    from optodraw.presets import list_presets
    from optodraw.registry import component_registry

    registry = component_registry()
    parts = sorted(
        ({"name": name, "platform": PLATFORMS.get(spec.platform, spec.platform), "category": spec.category,
          "description": spec.description.strip().rstrip(".")}
         for name, spec in registry.items() if spec.creatable),
        key=lambda p: (p["platform"], p["category"], p["name"]))
    by_platform = Counter(p["platform"] for p in parts)
    by_category = Counter(p["category"] for p in parts)
    cells = json.loads((DOCS / "src" / "data" / "cells.json").read_text()) if (DOCS / "src" / "data" / "cells.json").exists() else {}
    values = {
        "version": optodraw.__version__,
        "part-count": str(len(parts)),
        "free-space-count": str(by_platform.get("Free space", 0)),
        "on-chip-count": str(by_platform.get("On chip", 0)),
        "both-count": str(by_platform.get("Both", 0)),
        "preset-count": str(len(list_presets())),
        "example-count": str(len(cells)),
    }
    rows = "\n".join(f"| {cat.replace('_', ' ').capitalize()} | {n} |" for cat, n in by_category.most_common())
    blocks = {"part-categories": "| Kind of part | Parts |\n|---|---:|\n" + rows}
    return {"values": values, "blocks": blocks, "parts": parts}


if __name__ == "__main__":
    data = collect()
    out = DOCS / "src" / "data" / "site-data.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
    print(f"{len(data['parts'])} parts, values: {data['values']}")
