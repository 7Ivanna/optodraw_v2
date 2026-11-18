"""A phase-change (GST) cell on a waveguide (Feldmann et al., Nature 589, 52 (2021)): light from o1 to o2, a film
twice the guide's width over the core top and sides, dark when crystalline and pale when amorphous."""

from __future__ import annotations

import pytest

from optodraw import PCMCell, Scene, VerticalGratingCoupler, check_figure
from optodraw.symbols import lookup


def _luminance(hex_colour: str) -> float:
    r, g, b = (int(hex_colour[i:i + 2], 16) for i in (1, 3, 5))
    return 0.299 * r + 0.587 * g + 0.114 * b


def _film(part: PCMCell) -> list[dict]:
    return [solid for solid in part.geometry_3d()["children"] if solid["material"].get("preset") == "gst"]


def test_light_runs_from_the_west_port_to_the_east_port():
    ports = PCMCell().ports()
    assert ports["o1"].center.x < 0 < ports["o2"].center.x
    assert (ports["o1"].orientation_deg, ports["o2"].orientation_deg) == (180, 0)


def test_a_crystalline_cell_is_drawn_darker_than_an_amorphous_one():
    def fill(state):
        return next(n["fill"] for n in PCMCell(state=state).geometry_2d()["children"] if n.get("chip_layer") == "pcm")

    assert _luminance(fill("crystalline")) < _luminance(fill("amorphous"))
    with pytest.raises(ValueError, match="state"):
        PCMCell(state="molten")


def test_a_cell_between_two_couplers_passes_the_figure_checks_in_2d_and_1d():
    route = {"kind": "waveguide", "path_type": "smooth"}
    chip = Scene(title="PCM", platform="on_chip")
    cell = chip.add(PCMCell(center=(0, 0), label="GST cell", label_side="top"))
    a = chip.add(VerticalGratingCoupler(center=(-45, 0), angle=180, label="In"))
    b = chip.add(VerticalGratingCoupler(center=(45, 0), label="Out"))
    chip.route((a, "o1"), (cell, "o1"), **route)
    chip.route((cell, "o2"), (b, "o1"), **route)
    chip.fit_frame(margin=8)
    assert check_figure(chip, view="both") == []
    symbol = lookup(cell)
    assert symbol.exact and sorted(symbol.ports) == ["o1", "o2"]


def test_the_gst_film_follows_the_core_onto_a_ridge_stack():
    """On lnoi400 the ridge stands on its slab: the film wraps the ridge, so no GST solid starts under the core."""

    def leaves(node, out):
        if node.get("shape") == "group":
            for child in node.get("children", []):
                leaves(child, out)
        else:
            out.append(node)
        return out

    scene = Scene(title="ridge", platform="on_chip")
    scene.set_foundry_stack("lnoi400")
    cell = scene.add(PCMCell())
    core = cell._core()["z_offset"]
    films = [s for s in leaves(cell.geometry_3d(), []) if (s.get("material") or {}).get("preset") == "gst"]
    bottoms = [s["position"][1] - s["height"] / 2.0 for s in films]
    assert core > 0.0 and films and min(bottoms) >= core - 1e-9, (core, bottoms)
