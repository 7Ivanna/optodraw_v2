"""lookup(component) returns the 1D symbol: prebuilt, compiled, nearest, or the labeled block."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET

import pytest

import optodraw
from optodraw import symbols
from optodraw.core.component import Component
from optodraw.core.ports import Port
from optodraw.core.transform import Vec3
from optodraw.symbols import build, lookup


def _kinds(component) -> dict[str, str]:
    return {name: port.kind for name, port in component.ports().items()}


class _NoSymbolPart(Component):
    """A part that no table row names: it must fall back to the block."""

    def ports(self):
        return {
            "a": Port("a", Vec3(-5, 0, 0), orientation_deg=180),
            "b": Port("b", Vec3(5, 2, 0), orientation_deg=0),
            "c": Port("c", Vec3(5, -2, 0), orientation_deg=0),
            "bias": Port("bias", Vec3(0, 3, 0), orientation_deg=90, kind="electrical"),
        }

    def geometry_2d(self):
        return {"type": "group", "children": []}


def test_a_default_part_gets_its_prebuilt_symbol():
    symbol = lookup(optodraw.MicroringResonator())
    assert (symbol.name, symbol.source, symbol.exact) == ("ring", "prebuilt", True)
    assert set(symbol.ports) == {"o1", "o2"}
    assert symbol.svg.startswith("<svg") and " id=" not in symbol.svg
    ET.fromstring(symbol.svg)


@pytest.mark.parametrize(
    "arguments, drive",
    [({}, "gs"), ({"drive_style": "gsg"}, "gsg"), ({"mechanism": "thermo_optic"}, "heater")],
)
def test_the_modulator_symbol_follows_its_arguments(arguments, drive):
    part = optodraw.MZM(**arguments)
    symbol = lookup(part)
    assert symbol.exact and symbol.source == "prebuilt"
    assert symbol.params["drive"] == drive
    assert {name: port.kind for name, port in symbol.ports.items()} == _kinds(part)


@pytest.mark.parametrize("splitter", ["coupler", "branch_coupler"])
def test_the_modulator_symbol_follows_its_splitter(splitter):
    part = optodraw.MZM(splitter=splitter)
    symbol = lookup(part)
    assert symbol.exact and symbol.params["splitter"] == splitter
    assert set(symbol.ports) == set(part.ports())


def test_the_phase_shifter_symbol_follows_its_mechanism():
    heater = lookup(optodraw.PhaseShifter())
    junction = lookup(optodraw.PhaseShifter(mechanism="electro_optic"))
    assert heater.exact and junction.exact
    assert set(heater.ports) == {"o1", "o2", "h1", "h2"} and set(junction.ports) == {"o1", "o2", "e1", "e2"}
    assert junction.params == {"kind": "pn"} and heater.svg != junction.svg


def test_port_counts_follow_the_part():
    assert len(lookup(optodraw.AWG(channel_count=4)).ports) == 5
    router = lookup(optodraw.AWGR(channel_count=8))
    assert router.exact and router.params == {"inputs": 8, "outputs": 8, "arms": 7, "pitch": 0.3}
    assert lookup(optodraw.StarCoupler(input_count=4, output_count=4)).exact


def test_a_subclass_uses_the_symbol_of_its_parent():
    class MyRing(optodraw.MicroringResonator):
        pass

    assert lookup(MyRing()).name == "ring"


def test_a_part_with_no_symbol_gets_the_labeled_block():
    part = _NoSymbolPart()
    symbol = lookup(part)
    assert (symbol.name, symbol.source, symbol.exact) == ("block", "block", False)
    assert {name: port.kind for name, port in symbol.ports.items()} == _kinds(part)
    assert symbol.ports["a"].side == "left" and symbol.ports["a"].x == 0.0
    assert symbol.ports["b"].side == symbol.ports["c"].side == "right"
    assert symbol.ports["b"].x == symbol.ports["c"].x == symbol.width
    assert symbol.ports["b"].y < symbol.ports["c"].y            # b is the upper port: local y is up
    assert symbol.ports["bias"].side == "top" and symbol.ports["bias"].y == 0.0
    assert "_NoSymbolPart" in symbol.svg
    ET.fromstring(symbol.svg)


def test_a_block_escapes_its_label():
    class Odd(_NoSymbolPart):
        component_type = "A<B & C"

    ET.fromstring(lookup(Odd()).svg)


def test_a_block_has_room_for_no_ports_and_for_many_ports():
    class Bare(_NoSymbolPart):
        def ports(self):
            return {}

    class Many(_NoSymbolPart):
        def ports(self):
            return {f"p{k}": Port(f"p{k}", Vec3(5, k, 0), orientation_deg=0, kind="electrical") for k in range(24)}

    bare = lookup(Bare())
    assert bare.ports == {} and bare.width > 0 and bare.height > 0
    many = lookup(Many())
    heights = sorted(port.y for port in many.ports.values())
    assert len(heights) == 24
    assert min(b - a for a, b in zip(heights, heights[1:])) >= 10.0     # ports stay apart


def test_a_symbol_that_lacks_a_port_of_the_part_is_not_used():
    class TappedGuide(optodraw.Waveguide):
        def ports(self):
            ports = dict(super().ports())
            ports["tap"] = Port("tap", Vec3(0, 2, 0), orientation_deg=90)
            return ports

    symbol = lookup(TappedGuide())
    assert symbol.source == "block" and "tap" in symbol.ports


def test_a_parameter_that_is_not_prebuilt_gives_the_nearest_variant_without_latex():
    class LongGuide(optodraw.Waveguide):
        def symbol_1d(self):
            return "waveguide", {"length": 9}

    symbol = lookup(LongGuide())                    # conftest turns compiling off
    assert (symbol.name, symbol.source, symbol.exact) == ("waveguide", "nearest", False)


def test_an_unknown_pic_gives_the_block():
    class Stranger(optodraw.Waveguide):
        def symbol_1d(self):
            return "no such pic", {}

    assert lookup(Stranger()).source == "block"


def test_a_mirrored_symbol_swaps_left_and_right():
    symbol = lookup(optodraw.MMI1x2())
    mirror = symbol.mirrored()
    assert mirror.flipped and not symbol.flipped
    assert symbol.ports["o1"].side == "left" and mirror.ports["o1"].side == "right"
    assert mirror.ports["o1"].x == pytest.approx(symbol.width - symbol.ports["o1"].x, abs=1e-3)   # ports keep 3 decimals
    assert mirror.ports["o1"].y == symbol.ports["o1"].y
    assert mirror.mirrored().ports == symbol.ports
    ET.fromstring(mirror.svg)
    block = lookup(_NoSymbolPart()).mirrored()
    assert block.ports["a"].side == "right" and block.svg.count("scale(-1 1)") == 1
    assert "<text" in block.svg and "scale(-1 1)" not in block.svg.split("<text")[1]   # the label is not reversed


def test_to_dict_is_what_the_editor_needs():
    data = lookup(optodraw.MZM()).to_dict()
    assert set(data) == {"name", "params", "svg", "width", "height", "exact", "source", "flipped", "rotation", "hub", "ports"}
    assert {"name", "x", "y", "kind", "side"} == set(data["ports"][0])
    json.dumps(data)


@pytest.mark.skipif(not build.latex_available(), reason="needs latex and dvisvgm")
def test_a_variant_that_is_not_prebuilt_is_compiled_once(tmp_path, monkeypatch):
    monkeypatch.setenv("OPTODRAW_SYMBOL_COMPILE", "1")
    monkeypatch.setenv("OPTODRAW_SYMBOL_CACHE", str(tmp_path / "symbol cache"))
    part = optodraw.AWG(channel_count=6)
    first = lookup(part)
    assert (first.source, first.exact) == ("compiled", True)
    assert set(first.ports) == set(part.ports())

    def no_second_compile(*args, **kwargs):
        raise AssertionError("the cache was not used")

    monkeypatch.setattr(build, "compile_symbol", no_second_compile)
    assert lookup(part).source == "compiled"


def test_a_damaged_or_unwritable_cache_falls_back(tmp_path, monkeypatch):
    monkeypatch.setenv("OPTODRAW_SYMBOL_COMPILE", "1")
    monkeypatch.setattr(build, "latex_available", lambda: False)
    cache = tmp_path / "cache"
    monkeypatch.setenv("OPTODRAW_SYMBOL_CACHE", str(cache))
    record = cache / symbols._cache_key() / (build.slug("awg", {"inputs": 1, "outputs": 6, "arms": 7, "pitch": 0.3}) + ".json")
    record.parent.mkdir(parents=True)
    record.write_text("{ not json", encoding="utf-8")
    assert lookup(optodraw.AWG(channel_count=6)).source == "block"       # ports differ from every prebuilt AWG

    blocker = tmp_path / "a file"
    blocker.write_text("x", encoding="utf-8")
    monkeypatch.setenv("OPTODRAW_SYMBOL_CACHE", str(blocker / "under a file"))
    monkeypatch.setattr(build, "latex_available", lambda: True)
    monkeypatch.setattr(build, "compile_symbol", lambda *a, **k: (_ for _ in ()).throw(OSError("read-only")))
    assert lookup(optodraw.AWG(channel_count=6)).source == "block"


def test_add_library_makes_a_users_symbol_available(tmp_path):
    folder = tmp_path / "my_symbols"
    (folder / "svg").mkdir(parents=True)
    (folder / "svg" / "mypart.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 10" width="20pt" height="10pt">'
        '<path d="M0 5H20" stroke="#000"/></svg>', encoding="utf-8")
    (folder / "symbols.json").write_text(json.dumps({"version": 1, "source_hash": "", "symbols": {"mypart": {
        "symbol": "mypart", "params": {}, "svg": "mypart.svg", "width": 20.0, "height": 10.0, "origin": [10.0, 5.0],
        "ports": {"a": {"x": 0.0, "y": 5.0, "kind": "optical"}, "b": {"x": 20.0, "y": 5.0, "kind": "optical"}},
    }}}), encoding="utf-8")

    class MyPart(Component):
        def ports(self):
            return {"a": Port("a", Vec3(-1, 0, 0), orientation_deg=180), "b": Port("b", Vec3(1, 0, 0))}

        def symbol_1d(self):
            return "mypart", {}

        def geometry_2d(self):
            return {"type": "group", "children": []}

    assert lookup(MyPart()).source == "block"
    with pytest.raises(FileNotFoundError):
        symbols.add_library(tmp_path / "nothing here")
    symbols.add_library(folder)
    try:
        symbol = lookup(MyPart())
        assert (symbol.name, symbol.source, symbol.exact) == ("mypart", "prebuilt", True)
    finally:
        symbols._LIBRARIES.remove(folder)
        symbols._index.cache_clear()


def test_a_turned_symbol_keeps_its_art_and_moves_its_ports():
    """A free-space bench turns a part to face its beam: a quarter turn swaps width and height."""

    import optodraw
    from optodraw.symbols import lookup

    lens = lookup(optodraw.Lens())
    turned = lens.rotated(90)                                  # a quarter turn, counterclockwise on paper
    assert turned.rotation == 90 and lens.rotated(0) is lens
    assert abs(turned.width - lens.height) < 0.01 and abs(turned.height - lens.width) < 0.01
    assert turned.ports["in"].side == "bottom" and turned.ports["out"].side == "top"
    assert turned.ports["in"].y > turned.ports["out"].y      # in at the bottom, y grows downward
    assert 'viewBox="0 0 ' + f"{turned.width:g}" in turned.svg and "rotate(-90" in turned.svg
    half = lens.rotated(45)
    assert abs(half.width - (lens.width + lens.height) / 2 ** 0.5) < 0.01
    assert lens.rotated(360) is lens and lens.rotated(-90).ports["in"].side == "top"


@pytest.mark.parametrize("arguments, params", [
    ({"with_heater": True}, {"heater": True}),
    ({"add_drop": True, "with_heater": True}, {"drop": True, "heater": True}),
])
def test_a_ring_with_a_heater_gets_its_heater_symbol_not_a_junction(arguments, params):
    """A passive ring names its heater contacts e1 and e2; the symbol must carry the same names, or the lookup
    falls back to a p-n modulator ring."""

    part = optodraw.MicroringResonator(**arguments)
    symbol = lookup(part)
    assert (symbol.source, symbol.params) == ("prebuilt", params)
    assert {name: port.kind for name, port in symbol.ports.items()} == _kinds(part)


@pytest.mark.parametrize("order", [1, 2, 3, 4, 5])
def test_a_coupled_ring_filter_s_buses_leave_by_the_sides(order):
    """The buses of a ring filter run left to right: their ports face left and right, also on a tall stack of
    rings, where the corner of the box is nearer the top or bottom in proportion."""

    from optodraw import CoupledRingFilter

    for heaters in (False, True):
        ports = lookup(CoupledRingFilter(order=order, with_heaters=heaters)).ports
        assert [ports[name].side for name in ("o1", "o2", "o3", "o4")] == ["left", "right", "left", "right"]
