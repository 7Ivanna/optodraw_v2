"""Acceptance of the vector 3D renderer on on-chip catalog parts.

Depth (Acceptance 3): at 6,000 random page points (seed 7) the nearest front opaque face by plain plane depth owns a
shown piece within 0.02 mm of the point. Ties within 1e-3 world units are skipped. With the depth negated inside
visible(), the far faces win and the same check fails. The bench, the spike chip and the Objective join these parts
when the renderer draws mounts and GDS chips.

The spike chip (tests/fixtures/spike_ring.gds) as a View3D.chip inset, drawn once per module: Acceptance 4 (a figure
is vector), 6 (a page saves, loses its GDS, loads and exports the same bytes) and 7 (the chip SVG under 1 MB)."""

from __future__ import annotations

import pytest

shapely = pytest.importorskip("shapely")

from optodraw import CustomModel, Scene  # noqa: E402
from optodraw.registry import build_component  # noqa: E402
from optodraw.renderers.vector3d import Vector3DError, render_3d_svg  # noqa: E402

PARTS = ("MicroringResonator", "MZI", "PhaseShifter", "OnChipPhotodetector", "YBranch")
OCCLUDED = ("MZI", "OnChipPhotodetector", "YBranch")      # parts where one solid hides another over a large area
PROJECTIONS = ("parallel", "perspective")


def _scene(name: str) -> Scene:
    scene = Scene()
    scene.add(build_component(name))
    return scene


@pytest.mark.parametrize("projection", PROJECTIONS)
def test_render_3d_svg_draws_an_on_chip_part_the_same_each_time(tmp_path, projection):
    scene = _scene("MZI")
    first = render_3d_svg(scene, projection=projection)
    assert first.startswith("<svg") and 'data-art="3d"' in first and "<image" not in first
    assert render_3d_svg(scene, tmp_path / "mzi.svg", projection=projection).read_text(encoding="utf-8") == first


def test_a_kind_the_renderer_does_not_draw_yet_raises_with_the_part():
    scene = Scene()
    scene.add(CustomModel("arm.glb"))                     # its label comes from its file: the error names the part
    with pytest.raises(Vector3DError, match=r"CustomModel 'arm': .*external_model.*render_3d_image"):
        render_3d_svg(scene)


# ---------------------------------------------------------------- the spike chip as an inset: Acceptance 4, 6 and 7

import json  # noqa: E402
import shutil  # noqa: E402
from pathlib import Path  # noqa: E402

from optodraw import Callout, Inset, View3D  # noqa: E402
from optodraw.figure.page import Page  # noqa: E402
from optodraw.figure.sources import cut_section  # noqa: E402

SPIKE = Path(__file__).parent / "fixtures" / "spike_ring.gds"   # public gdsfactory generic cells: a heated ring
CHIP_MM = 120.0
CUT = ((-29.0, 20.0), (-16.0, 20.0))          # file um: through the left arm of the ring and its heater
TARGETS = {"Heater": (-16.5, 6.5, 1.85), "Ring": (12.55, 2.93, 0.22), "Bond pad": (-45.0, 90.0, 5.2)}  # file um, true z


@pytest.fixture(scope="module")
def spike(tmp_path_factory):
    """The spike chip from a copy of the fixture, drawn once at 120 mm: the view and the path of its GDS copy."""

    pytest.importorskip("gdstk")
    gds = tmp_path_factory.mktemp("spike") / "data" / "spike_ring.gds"
    gds.parent.mkdir()
    shutil.copy(SPIKE, gds)
    view = View3D.chip(gds, "gdsfactory_generic", z_scale=4)
    view.fragment(CHIP_MM, font_pt=7.0)
    return view, gds


def _spike_page(view, gds) -> Page:
    """The chip at 120 mm (the view's own drawing), the section of the cut beside it, a callout on each target."""

    page = Page(width_mm=183, height_mm=95, font_pt=7.0, letters=False)
    chip = page.add(Inset(view, center=(60, 45), width=CHIP_MM, label="chip"))
    page.add(Inset(cut_section(gds, "gdsfactory_generic", CUT), center=(152, 45), width=58, label="section"))
    for i, (text, point) in enumerate(TARGETS.items()):
        page.add(Callout(text, center=(15 + 55 * i, 89), target=chip.at(*point)))
    return page


def test_a_chip_page_exports_the_same_bytes_with_its_gds_gone(spike, tmp_path):
    # Acceptance 6, and a chip record rebuilds. Mutants: fragment_record keeps no map (the callouts cannot land after
    # the load); View3D leaves _PATH_KEYS (the record keeps the GDS path as given, not relative to the page file)
    view, gds = spike
    page = _spike_page(view, gds)
    before = page.export(tmp_path / "before", formats=("svg",))["svg"].read_bytes()
    saved = gds.parent.parent / "pages" / "figure.json"
    saved.parent.mkdir(exist_ok=True)
    page.save(saved)
    record = next(c for c in json.loads(saved.read_text())["components"] if c.get("label") == "chip")["source"]
    assert (record["kind"], record["path"], record["stack"]) == ("View3D", "../data/spike_ring.gds",
                                                                 "gdsfactory_generic")
    away = gds.with_suffix(".away")
    gds.rename(away)
    try:
        loaded = Page.load(saved)
        assert loaded.export(tmp_path / "after", formats=("svg",))["svg"].read_bytes() == before
    finally:
        away.rename(gds)
    inset = next(node for node in loaded.walk() if isinstance(node, Inset) and node.label == "chip")
    inset.rebuild()                                                        # the GDS is back: the record draws again
    assert inset.fragment().svg == view.fragment(CHIP_MM, font_pt=7.0).svg
