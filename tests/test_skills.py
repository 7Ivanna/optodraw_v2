"""The agent skills that ship inside the package.

Each skill is a folder ``optodraw/skills/<name>/`` with a ``SKILL.md`` in the open Agent Skills
format. ``optodraw-skills install`` copies them where Claude Code and Codex look for skills. Every
python block in a skill runs here, so a skill cannot teach an API that does not exist.
"""

from __future__ import annotations

import os
import re
import sys
import tomllib
import types
import warnings
from pathlib import Path

import pytest

from optodraw import registry, skills

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = {"optodraw-figure", "optodraw-layout", "optodraw-component", "optodraw-gds-3d", "optodraw-animation"}


def _frontmatter(text: str) -> dict[str, str]:
    match = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    assert match, "SKILL.md must start with a --- frontmatter block"
    fields = {}
    for line in match.group(1).splitlines():
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip()
    return fields


def _python_blocks(text: str) -> list[str]:
    return re.findall(r"^```python\n(.*?)^```", text, re.S | re.M)


def _documents() -> list[tuple[str, str]]:
    """(skill, file) for each skill's SKILL.md and each reference/*.md it carries."""

    out = []
    for name in sorted(EXPECTED):
        out.append((name, "SKILL.md"))
        out += [(name, f"reference/{p.name}") for p in sorted((skills.path(name) / "reference").glob("*.md"))]
    return out


def _is_a_defect(w) -> bool:
    """A user or runtime warning from anywhere, or a deprecation from optodraw or a skill: a skill tells the
    agent to read every warning as a defect, so its own examples raise none, and a deprecation is what
    makes a skill go stale."""

    if issubclass(w.category, (UserWarning, RuntimeWarning)):
        return True
    source = str(w.filename)
    return (issubclass(w.category, (DeprecationWarning, PendingDeprecationWarning, FutureWarning))
            and ("optodraw" in source or ".md block" in source))


def test_the_package_ships_the_skills():
    assert EXPECTED <= set(skills.names())


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_each_skill_has_valid_frontmatter(name):
    text = (skills.path(name) / "SKILL.md").read_text()
    fields = _frontmatter(text)
    assert fields["name"] == name
    assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", name) and len(name) <= 64
    assert 40 <= len(fields["description"]) <= 1024


@pytest.mark.parametrize("name, document", _documents())
def test_every_python_block_in_a_skill_runs(name, document, tmp_path, monkeypatch):
    """Blocks of one file run in order in one namespace, like a notebook. A block that starts with
    ``# not run`` (it needs Chrome, LaTeX or a file the reader brings) is compiled, not run."""

    import matplotlib

    matplotlib.use("Agg", force=True)                                       # files only, never a window
    blocks = _python_blocks((skills.path(name) / document).read_text())
    if document == "SKILL.md":
        assert blocks, f"{name} has no python example"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(registry, "_REGISTRY", dict(registry._REGISTRY))  # a skill may register a part
    module = types.ModuleType("skill_blocks")                               # dataclasses look the module up
    monkeypatch.setitem(sys.modules, "skill_blocks", module)
    namespace = module.__dict__
    with warnings.catch_warnings(record=True) as caught:  # recorded, so no try/except can hide one
        warnings.simplefilter("always")
        for i, block in enumerate(blocks):
            code = compile(block, f"{name}/{document} .md block {i + 1}", "exec")
            if not block.lstrip().startswith("# not run"):
                exec(code, namespace)
    raised = [f"{w.category.__name__}: {w.message}" for w in caught if _is_a_defect(w)]
    assert not raised, raised


def test_install_copies_every_skill_into_a_folder(tmp_path):
    written = skills.install(tmp_path)
    assert {p.name for p in written} == set(skills.names())
    for p in written:
        assert (p / "SKILL.md").read_text() == (skills.path(p.name) / "SKILL.md").read_text()


def test_install_keeps_an_edited_copy_unless_forced(tmp_path):
    skills.install(tmp_path)
    mine = tmp_path / "optodraw-figure" / "SKILL.md"
    mine.write_text("my notes")
    with pytest.raises(FileExistsError):
        skills.install(tmp_path)
    skills.install(tmp_path, force=True)
    assert mine.read_text() != "my notes"


def test_named_targets_resolve_to_the_agent_skill_folders(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    assert skills.target_dir("claude") == tmp_path / ".claude" / "skills"
    assert skills.target_dir("agents") == tmp_path / ".agents" / "skills"
    project = tmp_path / "proj"
    project.mkdir()
    monkeypatch.chdir(project)
    assert skills.target_dir("claude", project=True) == project / ".claude" / "skills"


def test_the_command_lists_and_installs(tmp_path, capsys):
    assert skills.main(["list"]) == 0
    listed = capsys.readouterr().out
    assert all(name in listed for name in EXPECTED)
    assert skills.main(["install", "--dir", str(tmp_path)]) == 0
    assert (tmp_path / "optodraw-gds-3d" / "SKILL.md").exists()


def test_the_command_is_a_console_script():
    scripts = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["scripts"]
    assert scripts["optodraw-skills"] == "optodraw.skills:main"


@pytest.mark.parametrize("agent", [".claude", ".agents"])
def test_the_repo_agent_folders_link_to_the_packaged_skills(agent):
    folder = ROOT / agent / "skills"
    for name in EXPECTED:
        link = folder / name
        assert link.is_symlink(), f"{link} should link to optodraw/skills/{name}"
        assert link.resolve() == skills.path(name).resolve()
    assert os.path.isfile(folder / "optodraw-layout" / "SKILL.md")
