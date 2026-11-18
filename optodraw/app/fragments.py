"""The drawings of insets, kept by the SHA-256 of their SVG text. The editor's scene payload names a large drawing by
its key, and the browser fetches it once per change (``GET /api/fragment/<key>``), so a page with a large picture
does not send the picture with every edit. A spec sent back with keys gets its drawings again from here.

Each drawing is a file ``<key>.svg`` in a folder of the workspace root, so an undo step from before a server restart
still finds its drawing. A saved workspace holds every drawing inline, so a file here only serves undo steps and the
browser: :meth:`Fragments.sweep` may remove it.

No FastAPI dependency lives here, so this module is import-safe on its own."""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Any

INLINE = 32_000             # characters: a smaller drawing rides in the payload, a larger one goes by its key
KEEP_S = 14 * 24 * 3600     # a drawing no payload named for two weeks goes at the next server start
LIMIT = 256 * 2 ** 20       # bytes kept; past it, the drawing named longest ago goes first


def _swap(record: dict[str, Any], old: str, new: str, value: Any) -> dict[str, Any]:
    """``record`` with the key ``old`` renamed ``new`` and given ``value``, in its place."""

    return {(new if key == old else key): (value if key == old else item) for key, item in record.items()}


class Fragments:
    """A content-addressed store of SVG text in the folder ``root``: a key names one drawing for ever, so a payload or
    a browser may keep it."""

    def __init__(self, root: str | os.PathLike[str]) -> None:
        self.root = Path(root)

    def _path(self, key: str) -> Path:
        if re.fullmatch(r"[0-9a-f]{64}", str(key)) is None:      # a key from the URL or the page: never a path
            raise KeyError(key)
        return self.root / f"{key}.svg"

    def put(self, svg: str) -> str:
        data = svg.encode("utf-8")
        key = hashlib.sha256(data).hexdigest()
        path = self._path(key)
        try:
            os.utime(path)                                        # named again: the sweep keeps it
            return key
        except FileNotFoundError:
            pass
        self.root.mkdir(parents=True, exist_ok=True)
        handle = tempfile.NamedTemporaryFile("wb", dir=self.root, prefix=".", suffix=".tmp", delete=False)
        try:
            with handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(handle.name, path)                         # a reader sees the whole drawing or none
        except BaseException:
            Path(handle.name).unlink(missing_ok=True)
            raise
        return key

    def get(self, key: str) -> str:
        """The SVG of ``key``. An unknown key (one that went in a sweep, or not a key at all) raises KeyError."""

        path = self._path(key)
        try:
            data = path.read_bytes()
            os.utime(path)
        except OSError as error:
            raise KeyError(key) from error
        return data.decode("utf-8")

    def sweep(self, keep_s: float = KEEP_S, limit: int = LIMIT) -> list[str]:
        """Remove each file that no payload named for ``keep_s`` seconds, then the oldest past ``limit`` bytes in all.
        The server start calls this. Returns the names removed."""

        if not self.root.is_dir():
            return []
        now, total, gone = time.time(), 0, []
        files = [(path, path.stat()) for path in self.root.iterdir() if path.is_file()]
        for path, stat in sorted(files, key=lambda item: item[1].st_mtime, reverse=True):   # newest first
            total += stat.st_size
            if now - stat.st_mtime > keep_s or total > limit:
                path.unlink(missing_ok=True)
                gone.append(path.name)
        return gone

    def key(self, svg: str) -> str | None:
        """The key of a drawing of :data:`INLINE` characters or more; None for a smaller one, which stays inline."""

        return self.put(svg) if len(svg) >= INLINE else None

    def keyed(self, value: Any) -> Any:
        """``value`` (a spec, or any part of one) with the SVG of each large ``fragment`` record, also in the scene
        of a scene inset, replaced by its ``svg_key``."""

        if isinstance(value, list):
            return [self.keyed(item) for item in value]
        if not isinstance(value, dict):
            return value
        out = {name: self.keyed(item) for name, item in value.items()}
        kept = out.get("fragment")
        key = self.key(kept["svg"]) if isinstance(kept, dict) and isinstance(kept.get("svg"), str) else None
        if key is not None:
            out["fragment"] = _swap(kept, "svg", "svg_key", key)
        return out

    def unkeyed(self, value: Any) -> Any:
        """The reverse of :meth:`keyed`: each ``svg_key`` back to its SVG. An unknown key raises KeyError."""

        if isinstance(value, list):
            return [self.unkeyed(item) for item in value]
        if not isinstance(value, dict):
            return value
        out = {name: self.unkeyed(item) for name, item in value.items()}
        kept = out.get("fragment")
        if isinstance(kept, dict) and "svg_key" in kept and "svg" not in kept:
            out["fragment"] = _swap(kept, "svg_key", "svg", self.get(kept["svg_key"]))
        return out
