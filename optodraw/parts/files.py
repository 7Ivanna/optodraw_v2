"""Data-only, checked part bundles. Loading never imports Python providers."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tempfile
import zipfile

from .definition import PartDefinition
from .serialization import encode_asset, read_definitions

MAX_PART_BYTES = 100 * 1024 * 1024
MAX_ASSET_BYTES = 10 * 1024 * 1024
MAX_MANIFEST_BYTES = 2 * 1024 * 1024
FORMAT = "optodraw.part.v1"


def _relative(name):
    if (not isinstance(name, str) or not name or "\\" in name or
            re.match(r"^[A-Za-z]:", name)):
        raise ValueError(f"Invalid part asset path: {name!r}")
    path = PurePosixPath(name)
    if path.is_absolute() or any(p in {"..", "."} for p in name.split("/")):
        raise ValueError(f"Unsafe part asset path: {name!r}")
    return path


def _unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"Duplicate manifest key: {key}")
        value[key] = item
    return value


def _definition(part):
    definition = part if isinstance(part, PartDefinition) else getattr(part, "definition", None)
    if definition is None:
        definition = getattr(part, "_part_definition", None)
    if not isinstance(definition, PartDefinition):
        raise TypeError("save_part needs a factory, portable instance or PartDefinition")
    return definition


def save_part(part, path):
    """Save an immutable definition as an .odpart zip or a new folder."""
    definition = _definition(part)
    target = Path(path)
    records = {digest: {"file": f"assets/{digest}.svg", "sha256": digest,
                        "media_type": "image/svg+xml"} for digest in definition.assets}
    manifest = {"format": FORMAT, "units": "um", "definition_hash": definition.digest,
                "definition": definition.to_dict(), "assets": records}
    files = {"part.json": (json.dumps(manifest, sort_keys=True, separators=(",", ":"),
                                      allow_nan=False) + "\n").encode("utf-8")}
    files.update({records[digest]["file"]: data for digest, data in definition.assets.items()})
    if sum(map(len, files.values())) > MAX_PART_BYTES:
        raise ValueError("Part exceeds the 100 MiB limit")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.suffix.lower() in {".odpart", ".zip"}:
        handle = tempfile.NamedTemporaryFile(dir=target.parent, suffix=".odpart", delete=False)
        temporary = Path(handle.name)
        handle.close()
        try:
            with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for name, data in sorted(files.items()):
                    info = zipfile.ZipInfo(name)  # fixed timestamp: reproducible bundles
                    info.compress_type = zipfile.ZIP_DEFLATED
                    archive.writestr(info, data)
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
    else:
        # Refuse an existing folder rather than partially replacing its contents.
        if target.exists() or target.is_symlink():
            raise FileExistsError(target)
        with tempfile.TemporaryDirectory(dir=target.parent) as temporary:
            folder = Path(temporary) / "part"
            folder.mkdir()
            for name, data in files.items():
                output = folder / name
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_bytes(data)
            os.replace(folder, target)
    return target


def _read_files(path):
    if path.is_symlink():
        raise ValueError("Part bundle cannot be a symlink")
    if path.is_dir():
        result = {}
        total = 0
        for entry in path.rglob("*"):
            if entry.is_symlink():
                raise ValueError(f"Part folder contains a symlink: {entry.name}")
            if not entry.is_file():
                continue
            name = entry.relative_to(path).as_posix()
            _relative(name)
            size = entry.stat().st_size
            total += size
            if size > MAX_ASSET_BYTES or total > MAX_PART_BYTES or len(result) >= 1001:
                raise ValueError("Part folder exceeds a size or file-count limit")
            result[name] = entry.read_bytes()
        return result
    try:
        if path.stat().st_size > MAX_PART_BYTES:
            raise ValueError("Part archive exceeds the size limit")
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            if len(entries) > 1001 or sum(e.file_size for e in entries) > MAX_PART_BYTES:
                raise ValueError("Part archive exceeds a size or file-count limit")
            result = {}
            names = set()
            for entry in entries:
                _relative(entry.filename.rstrip("/"))
                if entry.filename in names:
                    raise ValueError(f"Part archive has a duplicate path: {entry.filename}")
                names.add(entry.filename)
                if stat.S_ISLNK(entry.external_attr >> 16):
                    raise ValueError(f"Part archive contains a symlink: {entry.filename}")
                if entry.flag_bits & 1 or entry.file_size > MAX_ASSET_BYTES:
                    raise ValueError("Encrypted asset or asset size limit exceeded")
                if not entry.is_dir():
                    result[entry.filename] = archive.read(entry)
            return result
    except (zipfile.BadZipFile, RuntimeError) as error:
        raise ValueError(f"Invalid part archive: {error}") from error


def load_part(path, *, library=None):
    """Load checked SVG bytes and return the usual immutable part factory."""
    from . import default_library

    files = _read_files(Path(path))
    if "part.json" not in files or len(files["part.json"]) > MAX_MANIFEST_BYTES:
        raise ValueError("Part needs part.json within the manifest size limit")
    try:
        manifest = json.loads(files["part.json"], object_pairs_hook=_unique)
        if (set(manifest) != {"format", "units", "definition_hash", "definition", "assets"} or
                manifest["format"] != FORMAT or manifest["units"] != "um"):
            raise ValueError("Unsupported part manifest format or fields")
        assets = {}
        used = {"part.json"}
        for digest, record in manifest["assets"].items():
            if set(record) != {"file", "sha256", "media_type"} or record["sha256"] != digest:
                raise ValueError("Invalid asset checksum record")
            _relative(record["file"])
            if record["media_type"] != "image/svg+xml":
                raise ValueError("Unsupported part asset type")
            data = files[record["file"]]
            if hashlib.sha256(data).hexdigest() != digest:
                raise ValueError(f"Part asset {digest}: hash mismatch")
            assets[digest] = encode_asset(data)
            used.add(record["file"])
        if set(files) != used:
            raise ValueError("Part contains undeclared asset files")
        digest = manifest["definition_hash"]
        definitions = read_definitions({"part_definitions": {digest: manifest["definition"]},
                                        "assets": assets})
    except (KeyError, TypeError, AttributeError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"Invalid part manifest: {error}") from error
    return (library if library is not None else default_library()).add(definitions[digest])
