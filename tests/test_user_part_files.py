"""Portable parts load without a Python provider or an original asset path."""

import hashlib
import json
import os
import stat
import zipfile

import pytest

from optodraw import PartLibrary, define_part, load_part, save_part

SVG = '<svg viewBox="-10 -5 20 10"><rect x="-10" y="-5" width="20" height="10"/></svg>'


def factory():
    return define_part("user:demo/Tap", platform="on_chip", ports=[
        {"name": "in", "center": [-10, 0], "orientation_deg": 180},
        {"name": "out", "center": [10, 0]},
    ], symbol_2d=SVG, parameters={"weight": {"type": "float", "default": 0.5}},
        library=PartLibrary())


@pytest.mark.parametrize("name", ["../evil.svg", "/evil.svg", "C:/evil.svg", pytest.param(
    "assets\\evil.svg", marks=pytest.mark.skipif(os.name == "nt", reason="zipfile on Windows stores a backslash as /"))])
def test_archive_rejects_unsafe_paths(tmp_path, name):
    path = tmp_path / "unsafe.odpart"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("part.json", "{}")
        archive.writestr(name, SVG)
    with pytest.raises(ValueError, match="path"):
        load_part(path, library=PartLibrary())


def test_archive_rejects_symlinks_and_duplicates(tmp_path):
    path = tmp_path / "unsafe.odpart"
    entry = zipfile.ZipInfo("part.json")
    entry.create_system = 3
    entry.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(entry, "elsewhere")
    with pytest.raises(ValueError, match="symlink"):
        load_part(path)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("part.json", "{}")
        with pytest.warns(UserWarning):
            archive.writestr("part.json", "{}")
    with pytest.raises(ValueError, match="duplicate"):
        load_part(path)


def test_folder_rejects_symlink_and_tampered_asset(tmp_path):
    folder = tmp_path / "part"
    save_part(factory(), folder)
    manifest = json.loads((folder / "part.json").read_text())
    digest, record = next(iter(manifest["assets"].items()))
    asset = folder / record["file"]
    data = asset.read_bytes()
    assert hashlib.sha256(data).hexdigest() == digest
    asset.write_bytes(data + b" ")
    with pytest.raises(ValueError, match="hash"):
        load_part(folder)
    asset.unlink()
    outside = tmp_path / "outside.svg"
    outside.write_bytes(data)
    asset.symlink_to(outside)
    with pytest.raises(ValueError, match="symlink"):
        load_part(folder)


def test_archive_header_size_and_unknown_fields_are_rejected(tmp_path, monkeypatch):
    import optodraw.parts.files as files

    path = tmp_path / "part.odpart"
    save_part(factory(), path)
    monkeypatch.setattr(files, "MAX_PART_BYTES", 20)
    with pytest.raises(ValueError, match="limit"):
        load_part(path)
