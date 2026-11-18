"""Retain editor nodes without changing schema reconstruction rules."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from optodraw.core.scene import Scene
from optodraw.figure.inset import LINK_ENDS
from optodraw.schema import (
    _add_beam_from_spec,
    _add_route_from_spec,
    _build_route_component,
    scene_from_spec,
)

_LISTS = ("components", "beams", "routes")


def _references(value: Any, changed: set[str]) -> bool:
    if isinstance(value, str):
        return value in changed
    if isinstance(value, dict):
        return any(_references(item, changed) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_references(item, changed) for item in value)
    return False


def _links(entry: Any) -> set[str]:
    """The ids a component entry holds as live links to other parts: an anchor in an inset (``{"anchor": id}``,
    anywhere in the entry), the two insets of a zoom or a cut (``LINK_ENDS``), an inset's ``over``."""

    keys = ("over", *LINK_ENDS.get(entry.get("type"), ())) if isinstance(entry, dict) else ()
    found = {entry[key] for key in keys if isinstance(entry.get(key), str)}

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            if isinstance(value.get("anchor"), str) and "point" in value:
                found.add(value["anchor"])
            for item in value.values():
                walk(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                walk(item)

    walk(entry)
    return found


class RetainedScene:
    def __init__(self) -> None:
        self._spec: dict[str, Any] | None = None
        self._scene: Scene | None = None

    def get(self, spec: dict[str, Any]) -> Scene:
        if self._spec == spec and self._scene is not None:
            return self._scene
        if not self._can_update(spec) or not self._update(spec):
            self._scene = scene_from_spec(deepcopy(spec))
        self._spec = deepcopy(spec)
        return self._scene

    def _can_update(self, spec: dict[str, Any]) -> bool:
        old = self._spec
        if old is None or self._scene is None:
            return False
        if {k: v for k, v in old.items() if k not in _LISTS} != (
            {k: v for k, v in spec.items() if k not in _LISTS}
        ):
            return False
        for key in _LISTS:
            ids = [entry.get("id") for entry in spec.get(key, [])]
            if not all(ids) or len(ids) != len(set(ids)):
                return False
            if ids != [entry.get("id") for entry in old.get(key, [])]:
                return False
        return True

    def _update(self, spec: dict[str, Any]) -> bool:
        scene = self._scene
        old = self._spec
        assert scene is not None and old is not None
        previous = list(scene.root.children)
        nodes = {getattr(node, "_id", ""): node for node in previous}
        changed_entries = [
            entry for entry, before in zip(spec.get("components", []), old.get("components", []))
            if entry != before
        ]
        changed = {entry["id"] for entry in changed_entries}
        named = changed | {entry["label"] for entry in changed_entries if entry.get("label")}
        if any(_links(entry) & named for entry, before in zip(spec.get("components", []), old.get("components", []))
               if entry == before):
            return False                    # a mark or a zoom of a changed inset would keep the old inset: rebuild all
        try:
            if changed_entries:
                # Keep all schema tables and context for custom component records.
                partial = {k: deepcopy(v) for k, v in spec.items() if k not in _LISTS}
                partial.update(components=deepcopy(changed_entries), routes=[], beams=[])
                rebuilt = scene_from_spec(partial)
                replacements = {getattr(node, "_id", ""): node for node in rebuilt.root.children}
                if set(replacements) != changed:
                    return False
                nodes.update(replacements)
            scene.root.children = [nodes[getattr(node, "_id", "")] for node in previous]
            for node in scene.root.children:
                node._parent = scene.root
            refs = {entry["id"]: nodes[entry["id"]] for entry in spec.get("components", [])}
            for entry in spec.get("components", []):
                if entry.get("label"):
                    refs.setdefault(entry["label"], nodes[entry["id"]])
            changed_refs = changed | {
                entry["label"] for entry in changed_entries if entry.get("label")
            }
            for key in ("beams", "routes"):
                for entry, before in zip(spec.get(key, []), old.get(key, [])):
                    affected = entry != before or _references(entry, changed_refs)
                    if key == "routes" and changed and "points" not in entry:
                        affected |= entry.get("path_type", "manhattan") not in {"straight", "L"}
                    if not affected:
                        continue
                    if key == "beams":
                        node = _add_beam_from_spec(scene, deepcopy(entry), refs)
                    elif "points" in entry or entry.get("type") in {
                        "Route", "WaveguideRoute", "FiberRoute", "MetalRoute"
                    }:
                        node = _build_route_component(deepcopy(entry))
                        scene.add(node)
                    else:
                        node = _add_route_from_spec(scene, deepcopy(entry), refs)
                    node._id = entry["id"]
                    nodes[entry["id"]] = node
            scene.root.children = [nodes[getattr(node, "_id", "")] for node in previous]
            for node in scene.root.children:
                node._parent = scene.root
            return True
        except Exception:
            # Unsupported edits use the full schema builder.
            scene.root.children = previous
            for node in previous:
                node._parent = scene.root
            return False
