"""Portable definition tables and content-addressed workspace assets."""

from __future__ import annotations

import base64
import binascii
import hashlib
import os
from functools import lru_cache
from pathlib import Path
import re
import tempfile
from typing import Any

from .definition import PartDefinition, PartVariant, load_svg, parameter_specs, port_specs

_MAX_ASSET = 10 * 1024 * 1024
_MAX_TOTAL = 100 * 1024 * 1024


def _hash(value: Any) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError(f"Invalid asset or definition hash: {value!r}")
    return value


def encode_asset(data: bytes) -> dict[str, str]:
    return {"media_type": "image/svg+xml", "encoding": "base64",
            "data": base64.b64encode(data).decode("ascii")}


@lru_cache(maxsize=8)
def _asset_bytes(digest: str, encoded: str) -> bytes:
    if len(encoded) > ((_MAX_ASSET + 2) // 3) * 4:
        raise ValueError(f"asset {digest}: exceeds the 10 MiB limit")
    try:
        data = base64.b64decode(encoded, validate=True)
    except (binascii.Error, UnicodeError, ValueError) as error:
        raise ValueError(f"asset {digest}: invalid base64 bytes") from error
    if len(data) > _MAX_ASSET or hashlib.sha256(data).hexdigest() != digest:
        raise ValueError(f"asset {digest}: hash mismatch or size limit")
    return data


def decode_asset(digest: str, record: Any) -> bytes:
    _hash(digest)
    if not isinstance(record, dict) or set(record) != {"media_type", "encoding", "data"}:
        raise ValueError(f"asset {digest}: supply embedded bytes, not an external reference")
    if record["media_type"] != "image/svg+xml" or record["encoding"] != "base64":
        raise ValueError(f"asset {digest}: unsupported media type or encoding")
    if not isinstance(record["data"], str):
        raise ValueError(f"asset {digest}: base64 data must be a string")
    return _asset_bytes(digest, record["data"])


def read_definitions(payload: dict[str, Any]) -> dict[str, PartDefinition]:
    """Validate hashes and rebuild immutable definitions without executing code."""
    manifests = payload.get("part_definitions", {})
    records = payload.get("assets", {})
    if not isinstance(manifests, dict) or not isinstance(records, dict):
        raise ValueError("part definitions and assets must be hash-keyed objects")
    if len(manifests) > 1000 or len(records) > 1000:
        raise ValueError("Too many part definitions or assets")
    assets = {}
    total = 0
    for digest, record in records.items():
        data = decode_asset(digest, record)
        total += len(data)
        if total > _MAX_TOTAL:
            raise ValueError("Embedded assets exceed the 100 MiB scene limit")
        try:
            asset = load_svg(data)
        except ValueError as error:
            raise ValueError(f"asset {digest}: {error}") from error
        if asset.digest != digest:
            raise ValueError(f"asset {digest}: bytes are not canonical sanitized SVG")
        assets[digest] = asset

    def asset_ref(digest):
        if digest is None:
            return None
        _hash(digest)
        if digest not in assets:
            raise ValueError(f"Missing asset {digest}")
        return assets[digest]

    definitions = {}
    for digest, manifest in manifests.items():
        _hash(digest)
        try:
            if not isinstance(manifest, dict):
                raise ValueError("manifest must be an object")
            variants = tuple(
                PartVariant(name, port_specs(fields["ports"]),
                            asset_ref(fields.get("symbol_2d")), asset_ref(fields.get("symbol_1d")))
                for name, fields in sorted(manifest["variants"].items()))
            definition = PartDefinition(
                manifest["name"], manifest["platform"], parameter_specs(manifest["parameters"]),
                variants, manifest["default_variant"], manifest.get("description", ""))
            if definition.to_dict() != manifest or definition.digest != digest:
                raise ValueError("definition hash mismatch or unsupported fields")
        except (KeyError, TypeError, ValueError, AttributeError) as error:
            raise ValueError(f"definition {digest}: {error}") from error
        definitions[digest] = definition
    return definitions


def add_definition(definition: PartDefinition, manifests: dict, assets: dict) -> str:
    digest = definition.digest
    manifests.setdefault(digest, definition.to_dict())
    for asset_hash, data in definition.assets.items():
        if asset_hash not in assets:
            assets[asset_hash] = encode_asset(data)
    return digest


class AssetStore:
    """Write each immutable blob once. Workspace JSON contains hashes only."""

    def __init__(self, root: Path):
        self.root = root
        self._checked: dict[str, tuple[int, int, int]] = {}

    def _path(self, digest: str) -> Path:
        target = self.root / _hash(digest)
        if target.resolve().parent != self.root.resolve():
            raise ValueError(f"asset {digest}: reference leaves the asset folder")
        return target

    def _check(self, digest: str, path: Path) -> None:
        stat = path.stat()
        signature = (stat.st_ino, stat.st_size, stat.st_mtime_ns)
        if self._checked.get(digest) == signature:
            return
        if stat.st_size > _MAX_ASSET or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError(f"asset {digest}: workspace hash mismatch")
        self._checked[digest] = signature

    def externalize(self, spec: dict[str, Any]) -> dict[str, Any]:
        records = spec.get("assets", {})
        if not records:
            return spec
        if not isinstance(records, dict):
            raise ValueError("assets must be a hash-keyed object")
        portable = dict(spec)
        references = {}
        for digest, record in records.items():
            data = decode_asset(digest, record)
            self.root.mkdir(parents=True, exist_ok=True)
            target = self._path(digest)
            if not target.exists():
                handle = tempfile.NamedTemporaryFile("wb", dir=self.root, prefix=".blob-", delete=False)
                try:
                    with handle:
                        handle.write(data)
                        handle.flush()
                        os.fsync(handle.fileno())
                    try:
                        os.link(handle.name, target)  # atomic publication; never overwrite a blob
                    except FileExistsError:
                        pass
                finally:
                    Path(handle.name).unlink(missing_ok=True)
            self._check(digest, target)
            references[digest] = {"media_type": record["media_type"], "ref": digest}
        portable["assets"] = references
        return portable

    def hydrate(self, spec: dict[str, Any]) -> dict[str, Any]:
        records = spec.get("assets", {})
        if not records:
            return spec
        if not isinstance(records, dict):
            raise ValueError("assets must be a hash-keyed object")
        portable = dict(spec)
        embedded = {}
        for digest, record in records.items():
            if isinstance(record, dict) and "ref" in record:
                if record != {"media_type": "image/svg+xml", "ref": digest}:
                    raise ValueError(f"asset {digest}: invalid workspace reference")
                target = self._path(digest)
                self._check(digest, target)
                embedded[digest] = encode_asset(target.read_bytes())
            else:
                decode_asset(digest, record)
                embedded[digest] = record
        portable["assets"] = embedded
        return portable
