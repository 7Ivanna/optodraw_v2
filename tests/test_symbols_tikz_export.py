"""The 1D TikZ export: the library, one pic per part, links between named ports."""

from __future__ import annotations




import optodraw
from optodraw.symbols.tikz_export import render_tikz_1d


def _scene() -> optodraw.Scene:
    scene = optodraw.Scene(width=300, height=120, platform="on_chip")
    laser = scene.add(optodraw.OnChipLaser(center=(-120, 0), label="Laser 50% & more_1"))
    lasers = [laser, scene.add(optodraw.OnChipLaser(center=(-120, 40), label="L2"))]
    mux = scene.add(optodraw.AWG(center=(-40, 0), channel_count=4, angle=180, label="mux"))
    mzm = scene.add(optodraw.MZM(center=(60, 0), label="MZM"))
    dac = scene.add(optodraw.DAC(center=(60, 60), label="DAC"))
    for k, source in enumerate(lasers):
        scene.route((source, "o1"), (mux, f"o{k + 1}"), kind="waveguide")
    scene.route((mux, "i1"), (mzm, "o1"), kind="waveguide")
    scene.route((dac, "out"), (mzm, "sig"), kind="electrical")
    return scene


def test_a_part_with_no_pic_is_a_labeled_box_with_named_ports():
    from optodraw.core.component import Component
    from optodraw.core.ports import Port
    from optodraw.core.transform import Vec3

    class Unknown(Component):
        def ports(self):
            return {"o1": Port("o1", Vec3(5, 0, 0), orientation_deg=0)}

        def geometry_2d(self):
            return {"type": "group", "children": []}

    scene = optodraw.Scene(width=200, height=80, platform="on_chip")
    part = scene.add(Unknown(label="new part"))
    guide = scene.add(optodraw.Waveguide(center=(60, 0), label="wg"))
    scene.add(optodraw.Beam((part, "o1"), (guide, "o1")))
    tikz = render_tikz_1d(scene)
    assert "{Unknown}" in tikz and "coordinate (n0-o1)" in tikz
    assert "(n0-o1) .. controls" in tikz


def test_scene_render_tikz_takes_the_1d_view(tmp_path):
    scene = _scene()
    assert scene.render_tikz(view="1d") == render_tikz_1d(scene)
    target = tmp_path / "figure.tex"
    scene.render_tikz(str(target), view="1d", include_library=False)
    assert target.read_text(encoding="utf-8") == render_tikz_1d(scene, include_library=False)
    assert "optodrawColor" in scene.render_tikz()               # the 2D export is as before


def test_a_label_is_written_where_the_layout_puts_it():
    from optodraw.symbols.schematic import build_schematic
    from optodraw.symbols.tikz_export import _cm

    scene = optodraw.Scene(width=300, height=200, platform="on_chip")
    mzm = scene.add(optodraw.MZM(center=(0, 0), label="MZM"))
    scope = scene.add(optodraw.Oscilloscope(center=(0, 80), label="Scope"))
    scene.route((scope, "ch1"), (mzm, "sig"), kind="electrical")
    text = render_tikz_1d(scene, include_library=False)
    for item in build_schematic(scene).items:
        x, baseline, anchor = item.label_at
        corner = {"middle": "base", "start": "base west", "end": "base east"}[anchor]
        assert f"anchor={corner}] at {_cm(x, baseline)} {{{item.label}}}" in text
        if item.label == "Scope":
            assert baseline < item.y                           # over the instrument, clear of its cables


