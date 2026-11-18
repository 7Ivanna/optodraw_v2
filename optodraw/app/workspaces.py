"""Persistent named workspaces for the editor.

Each workspace is a scene spec stored as JSON on disk so work survives browser
reloads and server restarts. The directory defaults to ``~/.optodraw/workspaces``
and can be overridden with ``OPTODRAW_WORKSPACE_DIR``.

No FastAPI dependency lives here, so this module is import-safe on its own.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

#: The folder in the store's root that keeps the files picked in the editor, one folder per workspace. An inset record
#: names such a file relative to the root, and the editor builds only from files in here.
FILES = "files"


def _default_root() -> Path:
    override = os.environ.get("OPTODRAW_WORKSPACE_DIR")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".optodraw" / "workspaces"


def safe_name(name: str) -> str:
    """Sanitize a workspace name into a filesystem-safe stem."""

    cleaned = re.sub(r"[^A-Za-z0-9 _-]", "", str(name)).strip()
    return cleaned or "Untitled"


class WorkspaceStore:
    """Disk-backed store of scene specs keyed by workspace name."""

    def __init__(self, root: str | os.PathLike[str] | None = None) -> None:
        self.root = Path(root).expanduser() if root else _default_root()
        from optodraw.parts.serialization import AssetStore

        self._assets = AssetStore(self.root / ".assets")

    def _path(self, name: str) -> Path:
        return self.root / f"{safe_name(name)}.json"

    def list(self) -> list[str]:
        if not self.root.is_dir():
            return []
        return sorted(p.stem for p in self.root.glob("*.json"))

    def exists(self, name: str) -> bool:
        return self._path(name).is_file()

    def newest(self) -> str | None:
        """The workspace saved last, or None when the store holds none."""

        names = [name for name in self.list() if self.exists(name)]
        return max(names, key=lambda name: self._path(name).stat().st_mtime, default=None)

    def save(self, name: str, spec: dict[str, Any]) -> str:
        """Write the spec, atomically.

        The editor autosaves on every edit and reads the same file on every
        reload, so writing in place leaves a window where a reader sees half a
        file — which is how a real workspace was lost, and with it the server,
        since it loads the default workspace at boot. Serializing first and
        swapping the finished file into place closes it: a reader sees either
        the old spec or the new one.
        """

        self.root.mkdir(parents=True, exist_ok=True)
        stem = safe_name(name)
        payload = json.dumps(self._assets.externalize(spec), indent=2) + "\n"
        target = self.root / f"{stem}.json"
        handle = tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=self.root, prefix=f".{stem}.", suffix=".tmp", delete=False,
        )
        try:
            with handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(handle.name, target)
        except BaseException:
            Path(handle.name).unlink(missing_ok=True)
            raise
        return stem

    def load(self, name: str) -> dict[str, Any] | None:
        path = self._path(name)
        if not path.is_file():
            return None
        try:
            spec = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(spec, dict):
                raise ValueError("workspace root must be a JSON object")
            return self._assets.hydrate(spec)
        except (OSError, ValueError) as error:
            import logging

            logging.getLogger("optodraw").warning("workspace %r is corrupt (%s); ignoring", name, error)
            # Preserve every damaged version for manual recovery.
            try:
                backup = path.with_suffix(".json.bak")
                suffix = 1
                while os.path.lexists(backup):
                    backup = path.with_suffix(f".json.bak.{suffix}")
                    suffix += 1
                path.rename(backup)
            except OSError:
                pass
            return None

    def keep_file(self, name: str, filename: str, data: bytes) -> str:
        """Keep ``data``, a file picked in the editor, as ``filename`` in the files folder of the workspace ``name``,
        and give its path relative to :attr:`root`, as an inset record names it. When that name holds other bytes
        already, the new file's name gets the start of their hash, so a kept file never changes under an inset."""

        folder = self.root / FILES / safe_name(name)
        clean = Path(re.sub(r"[^A-Za-z0-9._-]", "_", Path(filename).name).lstrip(".") or "file")
        target = folder / clean
        if target.is_file() and target.read_bytes() != data:
            target = folder / f"{clean.stem}-{hashlib.sha256(data).hexdigest()[:12]}{clean.suffix}"
        if not target.is_file():
            folder.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        return target.relative_to(self.root).as_posix()

    def delete(self, name: str) -> None:
        self._path(name).unlink(missing_ok=True)

    def rename(self, old: str, new: str) -> str:
        spec = self.load(old)
        if spec is None:
            raise KeyError(old)
        if safe_name(old) != safe_name(new) and self.exists(new):
            raise ValueError(f"Workspace {safe_name(new)!r} already exists")
        stem = self.save(new, spec)
        if safe_name(old) != stem:
            self.delete(old)
        return stem
