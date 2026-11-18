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


@pytest.mark.parametrize("splitter", ["coupler", "branch_coupler"])
def test_the_modulator_symbol_follows_its_splitter(splitter):
    part = optodraw.MZM(splitter=splitter)
    symbol = lookup(part)
    assert symbol.exact and symbol.params["splitter"] == splitter
    assert set(symbol.ports) == set(part.ports())


def test_port_counts_follow_the_part():
    assert len(lookup(optodraw.AWG(channel_count=4)).ports) == 5
    router = lookup(optodraw.AWGR(channel_count=8))
    assert router.exact and router.params == {"inputs": 8, "outputs": 8, "arms": 7, "pitch": 0.3}
    assert lookup(optodraw.StarCoupler(input_count=4, output_count=4)).exact


def test_a_subclass_uses_the_symbol_of_its_parent():
    class MyRing(optodraw.MicroringResonator):
        pass

    assert lookup(MyRing()).name == "ring"


def test_a_parameter_that_is_not_prebuilt_gives_the_nearest_variant_without_latex():
    class LongGuide(optodraw.Waveguide):
        def symbol_1d(self):
            return "waveguide", {"length": 9}

    symbol = lookup(LongGuide())                    # conftest turns compiling off
    assert (symbol.name, symbol.source, symbol.exact) == ("waveguide", "nearest", False)


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


@pytest.mark.parametrize("order", [1, 2, 3, 4, 5])
def test_a_coupled_ring_filter_s_buses_leave_by_the_sides(order):
    """The buses of a ring filter run left to right: their ports face left and right, also on a tall stack of
    rings, where the corner of the box is nearer the top or bottom in proportion."""

    from optodraw import CoupledRingFilter

    for heaters in (False, True):
        ports = lookup(CoupledRingFilter(order=order, with_heaters=heaters)).ports
        assert [ports[name].side for name in ("o1", "o2", "o3", "o4")] == ["left", "right", "left", "right"]
