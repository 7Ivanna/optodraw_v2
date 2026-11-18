"""Agent skills that ship with optodraw.

Each skill is a folder with a ``SKILL.md`` in the open Agent Skills format: an AI coding agent
(Claude Code, Codex and others) reads it and then uses optodraw the way its authors do.

    optodraw-skills list
    optodraw-skills install                 # ~/.claude/skills and ~/.agents/skills
    optodraw-skills install --project       # ./.claude/skills and ./.agents/skills
    optodraw-skills install --dir PATH      # any other folder
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_TARGETS = {"claude": ".claude", "agents": ".agents"}


def names() -> list[str]:
    """The skills in this package, by folder name."""

    return sorted(p.name for p in _HERE.iterdir() if (p / "SKILL.md").is_file())


def path(name: str) -> Path:
    """The folder of one packaged skill."""

    if name not in names():
        raise KeyError(f"no optodraw skill named {name!r}; there are: {', '.join(names())}")
    return _HERE / name


def target_dir(target: str, *, project: bool = False) -> Path:
    """Where an agent looks for skills: ``claude`` (Claude Code) or ``agents`` (Codex and the open
    Agent Skills layout), in the home folder or, with ``project``, in the current folder."""

    base = Path.cwd() if project else Path.home()
    return base / _TARGETS[target] / "skills"


def install(folder: str | Path, *, force: bool = False) -> list[Path]:
    """Copy every packaged skill into ``folder``. An existing copy that differs stays, and the call
    raises ``FileExistsError``, unless ``force`` replaces it."""

    folder = Path(folder).expanduser()
    folder.mkdir(parents=True, exist_ok=True)
    clashes = [n for n in names() if (folder / n).exists() and not _same(path(n), folder / n)]
    if clashes and not force:
        raise FileExistsError(f"{folder} already holds changed copies of {', '.join(clashes)}; use force")
    written = []
    for n in names():
        dest = folder / n
        if dest.is_symlink() or dest.is_file():
            dest.unlink()
        elif dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(path(n), dest, ignore=shutil.ignore_patterns("__pycache__"))
        written.append(dest)
    return written


def _same(a: Path, b: Path) -> bool:
    files = [f.relative_to(a) for f in a.rglob("*") if f.is_file() and "__pycache__" not in f.parts]
    return all((b / f).is_file() and (b / f).read_bytes() == (a / f).read_bytes() for f in files)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="optodraw-skills", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="list the packaged skills")
    inst = sub.add_parser("install", help="copy the skills where agents read them")
    inst.add_argument("--project", action="store_true", help="the current folder, not the home folder")
    inst.add_argument("--dir", help="copy into this folder only")
    inst.add_argument("--for", dest="agents", choices=sorted(_TARGETS), action="append",
                      help="only this agent's folder (default: all)")
    inst.add_argument("--force", action="store_true", help="replace changed copies")
    args = parser.parse_args(argv)

    if args.command == "list":
        for n in names():
            print(n)
        return 0
    folders = [Path(args.dir)] if args.dir else [target_dir(t, project=args.project)
                                                 for t in (args.agents or sorted(_TARGETS))]
    for folder in folders:
        try:
            install(folder, force=args.force)
        except FileExistsError as err:
            print(f"{err.args[0].removesuffix('; use force')}; --force replaces them")
            return 1
        print(f"installed {len(names())} skills in {folder}")
    return 0
