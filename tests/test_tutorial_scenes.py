"""Tutorial scene builders must render and keep layout gaps positive."""

from pathlib import Path

import pytest

from examples.tutorial_scenes import TUTORIALS, bogaerts_add_drop, gc_ring_photodetector, half_size, measure_extent


@pytest.mark.parametrize("name,kind,builder", TUTORIALS)
def test_tutorial_scene_renders(name, kind, builder, tmp_path):
    scene = builder()
    assert scene is not None
    svg = scene.render_svg((tmp_path / f"{name}.svg").as_posix())
    assert svg is not None
    x0, y0, x1, y1 = scene.content_bounds()
    assert x1 > x0
    assert y1 > y0
    if kind == "paper":
        paper = scene.metadata.get("paper")
        assert paper is not None
        assert "doi" in paper


def test_measure_extent_is_finite():
    from optodraw import AWG

    x0, y0, x1, y1 = measure_extent(AWG(channel_count=4, array_count=8))
    assert x1 - x0 > 10
    assert y1 - y0 > 10


def test_bogaerts_drop_port_is_wired():
    scene = bogaerts_add_drop()
    dangling = scene.metadata["dangling"]
    assert not any(item.endswith(":o4") for item in dangling)
    assert not any(item.endswith(":o3") for item in dangling)


def test_gc_ring_add_port_is_wired():
    scene = gc_ring_photodetector()
    dangling = scene.metadata["dangling"]
    assert not any(item.endswith(":o3") for item in dangling)


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


def test_notebook_cells_run(tmp_path):
    import json

    root = Path(__file__).resolve().parents[1] / "examples"
    for name, _kind, _fn in TUTORIALS:
        nb = json.loads((root / f"{name}.ipynb").read_text())
        ns: dict = {}
        for cell in nb["cells"]:
            if cell.get("cell_type") != "code":
                continue
            src = "".join(cell.get("source", []))
            if "scene.preview" in src:
                continue
            exec(src, ns)
        scene = ns["scene"]
        x0, y0, x1, y1 = scene.content_bounds()
        assert x1 > x0
        assert y1 > y0
        svg = tmp_path / f"{name}.svg"
        scene.render_svg(svg.as_posix())
        assert svg.exists()


def _ccw(ax, ay, bx, by, cx, cy) -> float:
    return (cy - ay) * (bx - ax) - (by - ay) * (cx - ax)


def _segments_cross(a, b, c, d) -> bool:
    ax, ay = a
    bx, by = b
    cx, cy = c
    dx, dy = d
    d1 = _ccw(ax, ay, bx, by, cx, cy)
    d2 = _ccw(ax, ay, bx, by, dx, dy)
    d3 = _ccw(cx, cy, dx, dy, ax, ay)
    d4 = _ccw(cx, cy, dx, dy, bx, by)
    if d1 * d2 >= 0 or d3 * d4 >= 0:
        return False
    return True


def _route_polylines(scene):
    from optodraw.core.routing import Route

    lines = []
    for node in scene.walk():
        if isinstance(node, Route) and node.points:
            lines.append([(float(p.x), float(p.y)) for p in node.points])
    return lines


def _crossing_count(scene) -> int:
    lines = _route_polylines(scene)
    hits = 0
    for i, left in enumerate(lines):
        for right in lines[i + 1 :]:
            for a, b in zip(left, left[1:]):
                for c, d in zip(right, right[1:]):
                    if _segments_cross(a, b, c, d):
                        hits += 1
    return hits


def _by_label(scene, label: str):
    for node in scene.walk():
        if getattr(node, "label", None) == label:
            return node
    raise AssertionError(f"missing {label}")


@pytest.mark.parametrize("name,kind,builder", TUTORIALS)
def test_onchip_tutorials_have_no_route_crossings(name, kind, builder):
    if name in {"fold_and_focus", "polarization_bench", "four_f_relay", "conchello_confocal"}:
        return
    scene = builder()
    assert _crossing_count(scene) == 0, name


def test_gc_ring_drop_and_through_are_collinear():
    scene = gc_ring_photodetector()
    gc = _by_label(scene, "GC")
    ring = _by_label(scene, "Ring")
    pd = _by_label(scene, "PD")
    term = _by_label(scene, "term")
    assert abs(gc.world_ports()["o1"].center.y - ring.world_ports()["o1"].center.y) < 1.0
    assert abs(ring.world_ports()["o4"].center.y - pd.world_ports()["o1"].center.y) < 1.0
    assert abs(ring.world_ports()["o2"].center.y - term.world_ports()["o1"].center.y) < 1.0


def test_bogaerts_drop_pd_sits_on_the_drop_bus():
    scene = bogaerts_add_drop()
    ring = _by_label(scene, "ring")
    pd = _by_label(scene, "drop PD")
    drop_y = float(ring.world_ports()["o4"].center.y)
    pd_y = float(pd.world_ports()["o1"].center.y)
    assert drop_y > 0
    assert abs(drop_y - pd_y) < 1.0


def test_gsg_probe_pads_default_to_separated_squares():
    from optodraw import GSGProbePad

    gsg = GSGProbePad()
    assert gsg.pad_width == pytest.approx(gsg.pad_height)
    assert gsg.gap > 0
    rects = [child for child in gsg.geometry_2d()["children"] if child["type"] == "rect"]
    faces = [rect for rect in rects if rect["w"] == pytest.approx(gsg.pad_width) and rect["h"] == pytest.approx(gsg.pad_height)]
    assert len(faces) == 3                                     # drawn at their own size, where the ports are
    ys = sorted(rect["cy"] for rect in faces)
    assert ys[1] - ys[0] == pytest.approx(ys[2] - ys[1]) == pytest.approx(gsg.pitch)
    assert ys[1] - ys[0] > gsg.pad_height


def test_reed_gsg_sits_above_the_mzm_pads():
    from examples.tutorial_scenes import reed_mzm_probe
    from optodraw import MZM
    from optodraw.core.routing import Route

    scene = reed_mzm_probe()
    mzm = _by_label(scene, "MZM")
    pads = [_by_label(scene, name) for name in ("G2", "S", "G1")]
    mzm_hh = half_size(MZM(drive_style="gsg", label="MZM"))[1]
    mzm_top = float(mzm.transform.position.y) + mzm_hh
    for pad in pads:
        assert pad.width == pytest.approx(pad.height)
        pad_bot = float(pad.transform.position.y) - half_size(pad)[1]
        assert pad_bot > mzm_top
    for left, right in zip(pads, pads[1:]):
        dx = abs(float(left.transform.position.x) - float(right.transform.position.x))
        gap = dx - half_size(left)[0] - half_size(right)[0]
        assert gap >= 6.0
    routes = [node for node in scene.walk() if isinstance(node, Route) and node.kind == "electrical"]
    assert len(routes) == 3
    assert {round(route.width, 2) for route in routes} == {2.4, 1.4}
    assert all(route.path_type == "L" for route in routes)
    west_lengths = []
    o1x = float(mzm.world_ports()["o1"].center.x)
    for route in routes:
        pts = route.points
        assert float(pts[1].x) < float(pts[0].x)
        west_lengths.append(round(float(pts[0].x) - float(pts[1].x), 1))
        assert min(float(p.x) for p in pts) >= o1x
    assert len(set(west_lengths)) == 3


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


def test_a_detector_on_a_ring_sits_on_its_drop_port():
    """Light that enters a ring at o1 leaves the drop at o3 (top west), as the animation engine computes it."""

    from optodraw import presets
    from optodraw.core.routing import Route

    scenes = [fn() for _, _, fn in TUTORIALS] + [presets.build_preset(name) for name in presets.list_presets()]
    for scene in scenes:
        for route in (n for n in scene.walk() if isinstance(n, Route)):
            ends = [(route.start_component, route.start_port), (route.end_component, route.end_port)]
            for (ring, port), (other, _) in (ends, ends[::-1]):
                if getattr(ring, "component_type", "") == "MicroringResonator" and "Photodetector" in type(other).__name__:
                    assert port == "o3", f"{scene.title}: the detector is on the ring's {port}"
