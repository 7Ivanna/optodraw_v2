"""User parts retain their artwork, ports, and validated definitions."""

import dataclasses
import xml.etree.ElementTree as ET

import pytest

import optodraw
from optodraw.registry import build_component, get_component_class
from optodraw.symbols import lookup


SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="-10 -5 20 10"><path d="M-10 0L0 -5L10 0L0 5Z" fill="red" stroke="blue"/></svg>'
LINE_SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="-10 -5 20 10"><circle cx="0" cy="0" r="4" fill="none" stroke="black"/></svg>'
PORTS = [
    {"name": "in", "center": [-10, 0], "orientation_deg": 180, "width": 0.5},
    {"name": "out", "center": [10, 0], "orientation_deg": 0, "width": 0.5},
]


def make_part(**kwargs):
    library = kwargs.pop("library", optodraw.PartLibrary())
    fields = {"ports": PORTS, "symbol_2d": SVG}
    fields.update(kwargs)
    return optodraw.define_part("user:example/Tap", platform="on_chip", library=library, **fields)


def test_asset_bytes_survive_source_deletion_and_definition_cannot_change(tmp_path):
    source = tmp_path / "tap.svg"
    source.write_text(SVG)
    ports = [dict(port) for port in PORTS]
    factory = make_part(symbol_2d=source, ports=ports)
    source.unlink()
    ports[0]["name"] = "changed"
    instance = factory()
    assert set(instance.ports()) == {"in", "out"}
    assert "M-10 0L0 -5" in instance.geometry_2d()["svg"]
    with pytest.raises(dataclasses.FrozenInstanceError):
        factory.definition.name = "user:example/Changed"
    snapshot = factory.definition.to_dict()
    snapshot["name"] = "changed"
    assert factory.definition.to_dict()["name"] == "user:example/Tap"


def test_explicit_symbol_wins_and_ports_use_the_svg_frame():
    part = make_part(symbol_1d=LINE_SVG)()
    symbol = lookup(part)
    assert "circle" in symbol.svg
    assert "path" not in symbol.svg
    assert symbol.ports["in"].x == 0
    assert symbol.ports["out"].x == 20
    assert symbol.ports["in"].y == 5
    assert symbol.ports["in"].side == "left"
    assert symbol.ports["out"].side == "right"


def test_missing_1d_draws_2d_art_as_black_lines_in_real_scene():
    part = make_part()()
    symbol = lookup(part)
    path = next(node for node in ET.fromstring(symbol.svg).iter() if node.tag.endswith("path"))
    assert path.attrib["fill"] == "none"
    assert path.attrib["stroke"] == "#000"
    scene = optodraw.Scene()
    scene.add(part)
    drawing = scene.render_svg().as_svg()
    assert "M-10 0L0 -5" in drawing
    assert sum(node.tag.endswith("svg") for node in ET.fromstring(drawing).iter()) == 1
    schematic = scene.render_svg(onchip_view="1d").as_svg()
    assert "M-10 0L0 -5" in schematic
    assert "red" not in schematic


def test_missing_both_symbols_asks_for_1d_instead_of_a_model_projection():
    with pytest.raises(ValueError, match="1D symbol"):
        make_part(symbol_2d=None)


def test_filled_svg_with_zero_stroke_still_has_visible_monochrome_lines():
    symbol = lookup(make_part(symbol_2d=SVG.replace('stroke="blue"', 'stroke="none" stroke-width="0"'))())
    path = next(node for node in ET.fromstring(symbol.svg).iter() if node.tag.endswith("path"))
    assert path.attrib["stroke"] == "#000"
    assert float(path.attrib["stroke-width"]) > 0


def test_uniform_scale_and_rotation_keep_ports_widths_and_art_aligned():
    part = make_part()(center=(100, 20), angle=90, scale=2)
    first = part.world_port("in")
    last = part.world_port("out")
    assert first.center.x == pytest.approx(100)
    assert first.center.y == pytest.approx(0)
    assert last.center.y == pytest.approx(40)
    assert first.width == 1
    assert first.orientation_deg == pytest.approx(-90)
    assert part.geometry_2d()["matrix"] == (2, 0, 0, 2, 0, 0)
    assert lookup(part).width == 40


def test_user_ports_connect_with_existing_scene_routes():
    scene = optodraw.Scene()
    factory = make_part()
    a = scene.add(factory())
    b = scene.add(factory(center=(50, 0)))
    link = scene.route((a, "out"), (b, "in"), backend="local")
    assert link.points[0].x == pytest.approx(10)
    assert link.points[-1].x == pytest.approx(40)


def test_typed_parameters_keep_defaults_and_do_not_deform_art():
    factory = make_part(parameters={
        "gain": {"type": "float", "default": 0.5, "min": 0, "max": 1, "unit": "dB"},
        "channels": {"type": "int", "default": 2, "min": 1},
        "enabled": {"type": "bool", "default": True},
        "mode": {"type": "enum", "default": "a", "choices": ["a", "b"]},
        "note": {"type": "string", "default": ""},
    })
    part = factory(gain=0.8, mode="b")
    assert dict(part.parameters) == {"gain": 0.8, "channels": 2, "enabled": True, "mode": "b", "note": ""}
    assert part.ports()["out"].center.x == 10
    with pytest.raises(ValueError, match="gain"):
        factory(gain=1.1)
    with pytest.raises(ValueError, match="channels"):
        factory(channels=True)
    with pytest.raises(ValueError, match="enabled"):
        factory(enabled=1)
    with pytest.raises(ValueError, match="mode"):
        factory(mode="c")
    with pytest.raises(ValueError, match="Unknown parameter"):
        factory(unlisted=2)


@pytest.mark.parametrize("value", [0, -1, float("nan"), float("inf"), True])
def test_bad_scale_is_rejected_before_ports_or_art_change(value):
    with pytest.raises(ValueError, match="scale"):
        make_part()(scale=value)


def test_scale_edits_cannot_create_invalid_geometry_or_ports():
    part = make_part()()
    with pytest.raises(ValueError, match="scale"):
        part.scale = float("nan")
    assert part.world_port("out").center.x == 10
    assert part.scale == 1


def test_artwork_bounds_are_available_to_existing_layout_helpers():
    from optodraw.layout import estimate_component_bounds

    assert estimate_component_bounds(make_part()(scale=2)) == (-20, -10, 20, 10)


def test_default_library_resolves_user_parts_without_changing_builtin_lookup():
    factory = optodraw.define_part("user:example/DefaultTap", platform="on_chip",
                                  ports=PORTS, symbol_2d=SVG)
    part = build_component("user:example/DefaultTap")
    assert part.definition.digest == factory.definition.digest
    assert get_component_class("user:example/DefaultTap") is optodraw.UserPart
    assert get_component_class("Lens") is optodraw.Lens


def test_complete_variant_changes_both_ports_and_art():
    wide_ports = [dict(PORTS[0]), {**PORTS[1], "center": [20, 0]}]
    factory = make_part(ports=None, symbol_2d=None, variants={
        "small": {"ports": PORTS, "symbol_2d": SVG},
        "wide": {"ports": wide_ports, "symbol_1d": LINE_SVG},
    }, default_variant="small")
    wide = factory(variant="wide")
    assert wide.ports()["out"].center.x == 20
    assert "circle" in lookup(wide).svg
    with pytest.raises(ValueError, match="variant"):
        factory(variant="unknown")
    with pytest.raises(ValueError, match="ports"):
        make_part(ports=None, symbol_2d=None, variants={"incomplete": {"symbol_2d": SVG}})


def test_library_hashes_are_stable_and_updates_do_not_mutate_placed_parts():
    library = optodraw.PartLibrary()
    old = make_part(library=library)
    same = make_part(library=library, ports=list(reversed(PORTS)))
    assert same.definition.digest == old.definition.digest
    placed = old()
    changed = make_part(symbol_2d=LINE_SVG)
    with pytest.raises(ValueError, match="already registered"):
        library.add(changed.definition)
    library.add(changed.definition, replace=True)
    assert library.get("user:example/Tap").definition.digest == changed.definition.digest
    assert placed.definition.digest == old.definition.digest
    assert "path" in placed.geometry_2d()["svg"]
    assert len(old.definition.assets) == 1
    shared = make_part(symbol_1d=SVG).definition
    assert len(shared.assets) == 1
    with pytest.raises(TypeError):
        shared.assets["changed"] = b"changed"


def test_scoped_registry_never_replaces_a_builtin():
    library = optodraw.PartLibrary()
    factory = make_part(library=library)
    part = build_component("user:example/Tap", part_library=library, center=[5, 6])
    assert part.definition.digest == factory.definition.digest
    assert part.world_position.x == 5
    assert get_component_class("Lens") is optodraw.Lens
    with pytest.raises(ValueError, match="qualified"):
        optodraw.define_part("Lens", platform="on_chip", ports=PORTS, symbol_2d=SVG, library=library)


def test_trusted_subclass_registration_validates_values_without_replacing_its_geometry():
    library = optodraw.PartLibrary()

    @optodraw.register_part("user:example/Procedural", library=library,
                           parameters={"length": {"type": "float", "default": 10, "min": 1}})
    class Procedural(optodraw.Component):
        def __init__(self, *, length=10, center=(0, 0), angle=0, label=""):
            super().__init__(label=label, transform=optodraw.Transform.from_2d(*center, angle))
            self.length = length

        def geometry_2d(self):
            return {"type": "line", "x1": 0, "y1": 0, "x2": self.length, "y2": 0}

        def ports(self):
            from optodraw.core.transform import Vec3

            return {"in": optodraw.Port("in", Vec3(0, 0), orientation_deg=180),
                    "out": optodraw.Port("out", Vec3(self.length, 0))}

        def portable_definition(self, parameters):
            svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 -2 {parameters["length"]} 4">'
                   f'<path d="M0 0H{parameters["length"]}" stroke="black"/></svg>')
            return optodraw.define_part("user:example/Procedural", platform="on_chip",
                                       ports=[port.to_dict() for port in self.ports().values()],
                                       symbol_2d=svg, library=optodraw.PartLibrary()).definition

    part = build_component("user:example/Procedural", part_library=library, length=12)
    assert isinstance(part, Procedural)
    assert part.geometry_2d()["x2"] == 12
    symbol = lookup(part)
    assert symbol.source == "user"
    assert "M0 0H12" in symbol.svg
    assert symbol.ports["out"].x == 12
    with pytest.raises(ValueError, match="length"):
        build_component("user:example/Procedural", part_library=library, length=0)
    with pytest.raises(TypeError, match="Component"):
        optodraw.register_part("user:example/NotPart", library=library)(dict)


@pytest.mark.parametrize("markup", [
    '<script>alert(1)</script>',
    '<path d="M0 0" onclick="alert(1)"/>',
    '<image href="https://example.invalid/image.png"/>',
    '<foreignObject><div/></foreignObject>',
    '<path d="M0 0" style="fill:url(https://example.invalid/a)"/>',
])
def test_active_or_external_svg_is_rejected(markup):
    with pytest.raises(ValueError, match="SVG"):
        make_part(symbol_2d=f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 10">{markup}</svg>')


@pytest.mark.parametrize("ports", [
    [PORTS[0], PORTS[0]],
    [{**PORTS[0], "center": [float("nan"), 0]}],
    [{**PORTS[0], "width": 0}],
    [{**PORTS[0], "orientation_deg": float("inf")}],
    [{**PORTS[0], "kind": "unknown"}],
])
def test_invalid_ports_cannot_enter_a_definition(ports):
    with pytest.raises(ValueError, match="port"):
        make_part(ports=ports)
