"""Editor-owned parts share the workspace content-addressed asset store."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile

from optodraw.parts import PartDefinition
from optodraw.parts.serialization import AssetStore, add_definition, read_definitions


class EditorParts:
    def __init__(self, workspace_root):
        self.root = Path(workspace_root) / ".parts"
        self.assets = AssetStore(Path(workspace_root) / ".assets")

    @staticmethod
    def _filename(name):
        return hashlib.sha256(name.encode("utf-8")).hexdigest() + ".json"

    def definitions(self):
        if self.root.is_symlink():
            raise ValueError("My parts folder cannot be a symlink")
        result = {}
        for path in sorted(self.root.glob("*.json")):
            if len(result) >= 1000 or path.is_symlink() or path.stat().st_size > 2*1024*1024:
                raise ValueError(f"Invalid My parts file or size limit: {path.name}")
            payload = self.assets.hydrate(json.loads(path.read_text(encoding="utf-8")))
            definitions = read_definitions(payload)
            if len(definitions) != 1:
                raise ValueError(f"My parts file needs one definition: {path.name}")
            definition = next(iter(definitions.values()))
            if path.name != self._filename(definition.name):
                raise ValueError(f"My parts filename does not match {definition.name}")
            result[definition.name] = definition
        return result

    def get(self, name):
        try:
            return self.definitions()[name]
        except KeyError:
            raise KeyError(f"Unknown My part: {name}") from None

    def save(self, definition: PartDefinition):
        previous = self.definitions().get(definition.name)
        if previous is not None:
            if previous.digest != definition.digest:
                raise ValueError(f"{definition.name}: already registered; use a new name for the changed definition")
            return definition
        manifests, assets = {}, {}
        add_definition(definition, manifests, assets)
        payload = self.assets.externalize({"part_definitions": manifests, "assets": assets})
        self.root.mkdir(parents=True, exist_ok=True)
        handle = tempfile.NamedTemporaryFile("w", dir=self.root, encoding="utf-8", delete=False)
        try:
            with handle:
                json.dump(payload, handle, sort_keys=True, separators=(",", ":"), allow_nan=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(handle.name, self.root / self._filename(definition.name))
        finally:
            Path(handle.name).unlink(missing_ok=True)
        return definition


def describe_part(definition):
    metadata = {p.name: {**p.to_dict(), "type": ("number" if p.type in {"int", "float"} else
                                                "text" if p.type == "string" else p.type),
                         "options": list(p.choices)} for p in definition.parameters}
    metadata.update(scale={"type": "number", "default": 1., "min": 1e-12},
                    variant={"type": "enum", "default": definition.default_variant,
                             "choices": [v.name for v in definition.variants]})
    return {"name": definition.name, "display_name": definition.name.split("/", 1)[1],
            "category": "my_parts", "platform": definition.platform,
            "description": definition.description, "definition_hash": definition.digest,
            "parameters": ["scale", "variant", *[p.name for p in definition.parameters]],
            "param_meta": metadata}
