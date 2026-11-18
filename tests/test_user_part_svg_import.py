"""SVG port marks follow artwork transforms and disappear from visible art."""


import pytest

from optodraw import PartLibrary, import_svg_part


def source(mark, transform=""):
    return ('<svg viewBox="-20 -20 40 40"><rect x="-10" y="-5" width="20" height="10"/>'
            f'<g transform="{transform}">{mark}</g></svg>')


def test_nested_transform_maps_position_angle_and_width():
    svg = source('<g transform="rotate(90)"><circle id="port:in" cx="2" cy="0" '
                 'data-orientation="0" data-width="0.5" data-kind="optical"/></g>',
                 "translate(3 4) scale(2)")
    factory = import_svg_part("user:demo/Marked", svg, library=PartLibrary())
    port = factory().ports()["in"]
    assert port.center.as_2d() == pytest.approx((3, -8))
    assert port.orientation_deg == pytest.approx(270)
    assert port.width == pytest.approx(1)
    assert b"port:in" not in factory.definition.variant().symbol_2d.data
    assert b"data-orientation" not in factory.definition.variant().symbol_2d.data


@pytest.mark.parametrize("mark,message", [
    ('<circle id="port:"/>', "name"),
    ('<circle id="port:a" data-width="0"/>', "width"),
    ('<circle id="port:a" data-kind="banana"/>', "kind"),
    ('<circle id="port:a"/><circle id="port:a"/>', "Duplicate"),
    ('<circle id="port:a" data-orientation="nan"/>', "finite"),
])
def test_invalid_marker_metadata_has_named_error(mark, message):
    with pytest.raises(ValueError, match=message):
        import_svg_part("user:demo/Invalid", source(mark), library=PartLibrary())


def test_unsafe_art_is_rejected_after_marker_removal():
    with pytest.raises(ValueError, match="Unsupported"):
        import_svg_part("user:demo/Unsafe", source('<circle id="port:a"/><script/>'),
                        library=PartLibrary())


def test_unmarked_art_needs_explicit_ports_including_an_empty_list():
    with pytest.raises(ValueError, match="port marks"):
        import_svg_part("user:demo/Unmarked", source(""), library=PartLibrary())
    factory = import_svg_part("user:demo/Unmarked", source(""), ports=[], library=PartLibrary())
    assert factory().ports() == {}


@pytest.mark.parametrize("mark", ['<rect id="port:in" x="1" y="1" width="2" height="2"/>',
                                  '<g id="port:in"/>'])
def test_a_mark_whose_position_cannot_be_read_is_an_error_not_the_origin(mark):
    with pytest.raises(ValueError, match="port:in"):
        import_svg_part("user:test/BadMark", source(mark), library=PartLibrary())
