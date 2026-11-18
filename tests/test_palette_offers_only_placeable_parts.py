"""Anything the editor offers must be placeable by clicking it.

Three catalog entries need a file or points before they can exist: GDSModel,
CustomModel and Route. The palette hides them and the import flows
create them instead. The command palette hid its own copy of that list and left
"models" off it, so ⌘K offered GDS Model as a thing to add and the server
answered 400.

Both now read the same two sets out of palette.js, and this test reads them too:
every other catalog entry has to place and render for real.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from fastapi.testclient import TestClient

from optodraw.app.server import create_app

PALETTE_JS = Path(__file__).resolve().parents[1] / "optodraw" / "app" / "static" / "js" / "palette.js"


def _hidden(name: str) -> set[str]:
    """Read one of the exported Sets out of the front end."""

    match = re.search(rf"export const {name} = new Set\((\[[^\]]*\])\)", PALETTE_JS.read_text())
    assert match, f"{name} is no longer exported from palette.js"
    return set(json.loads(match.group(1)))


@pytest.fixture(scope="module")
def catalog() -> dict:
    client = TestClient(create_app())
    return client.get("/api/catalog").json()["components"]


def test_the_front_end_still_declares_what_it_hides():
    assert _hidden("HIDDEN_CATEGORIES") == {"light_paths", "routing", "models"}
    assert _hidden("HIDDEN_COMPONENTS") == {"Grid"}


def test_every_offered_component_can_be_placed(catalog):
    client = TestClient(create_app())
    hidden_names, hidden_categories = _hidden("HIDDEN_COMPONENTS"), _hidden("HIDDEN_CATEGORIES")

    offered = [
        name for name, info in catalog.items()
        if name not in hidden_names and (info.get("category") or "other") not in hidden_categories
    ]
    assert len(offered) > 200, "the palette should be offering most of the catalog"

    broken = []
    for name in sorted(offered):
        client.post("/api/scene/new", json={})
        added = client.post("/api/component", json={"name": name, "params": {}})
        if added.status_code != 200:
            broken.append(f"{name}: {added.json().get('detail', added.status_code)}")
            continue
        if client.get("/api/render/svg").status_code != 200:
            broken.append(f"{name}: placed but the scene will not render")
    assert not broken, "offered but not placeable:\n  " + "\n  ".join(broken[:10])
