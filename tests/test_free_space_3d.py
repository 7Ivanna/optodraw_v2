"""Free-space parts in 3D: what stands on the table, what sits on a post, and what a figure shows."""

from __future__ import annotations




def _shapes(node):
    yield node
    for child in node.get("children", []):
        yield from _shapes(child)


