"""Run the documented portable-part example, not a separate example copy."""
from pathlib import Path


def test_documented_import_save_and_load(tmp_path, monkeypatch):
    source = Path(__file__).parents[1] / "docs" / "content" / "guides" / "your-own-parts.md"
    blocks = source.read_text().split("```python\n")[1:]
    code = next(block.split("```", 1)[0] for block in blocks if "import_svg_part" in block)
    monkeypatch.chdir(tmp_path)
    values = {}
    exec(compile(code, str(source), "exec"), values)
    assert values["part"].definition.digest == values["again"].definition.digest
    assert (tmp_path / "coupler.odpart").is_file()
