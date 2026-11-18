"""Tutorial scene builders must render and keep layout gaps positive."""

from pathlib import Path


from examples.tutorial_scenes import TUTORIALS


ONCHIP_NOTEBOOKS = (
    "gc_ring_photodetector",
    "bogaerts_add_drop",
    "reed_mzm_probe",
    "smit_awg_demux",
    "tait_weight_bank",
)


def _notebook_source(path: Path) -> str:
    import json

    nb = json.loads(path.read_text())
    parts: list[str] = []
    for cell in nb["cells"]:
        parts.append("".join(cell.get("source", [])))
    return "\n".join(parts)


def test_notebooks_exist():
    root = Path(__file__).resolve().parents[1] / "examples"
    for name, _kind, _fn in TUTORIALS:
        path = root / f"{name}.ipynb"
        assert path.is_file(), path


def test_notebooks_teach_layout_skill():
    root = Path(__file__).resolve().parents[1] / "examples"
    for name, _kind, _fn in TUTORIALS:
        text = _notebook_source(root / f"{name}.ipynb")
        assert "from tutorial_scenes" not in text, name
        assert "scene.preview" in text, name
        if name in ONCHIP_NOTEBOOKS:
            assert "def half_size" in text, name
            assert "content_bounds()" in text, name
            assert 'path_type="smooth"' in text, name
            assert "dangling_optical" in text, name
            assert "chain_ports" in text, name


def _by_label(scene, label: str):
    for node in scene.walk():
        if getattr(node, "label", None) == label:
            return node
    raise AssertionError(f"missing {label}")


def test_layout_skill_teaches_electrical_and_io_keepout():
    root = Path(__file__).resolve().parents[1]
    claude = (root / ".claude/skills/optodraw-layout/SKILL.md").read_text()
    agents = (root / ".agents/skills/optodraw-layout/SKILL.md").read_text()
    assert claude == agents
    for needle in (
        'path_type="L"',
        "ElectricalPad",
        "GSGProbePad",
        "GratingCouplerArray",
        "V-groove",
        "bond pad",
        "steps=",
    ):
        assert needle in claude, needle


