"""SVG port marks follow artwork transforms and disappear from visible art."""

import math

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


def test_line_mark_and_frame_origin_are_explicit():
    factory = import_svg_part("user:demo/LineMark", source(
        '<line id="port:out" x1="5" y1="2" x2="8" y2="6" data-width="1"/>'),
        origin=(1, 2), scale=2, library=PartLibrary())
    port = factory().ports()["out"]
    assert port.center.as_2d() == pytest.approx((8, 0))
    assert port.orientation_deg == pytest.approx((-math.degrees(math.atan2(4, 3))) % 360)
    assert port.width == pytest.approx(2)


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


def test_percentage_positions_use_the_declared_viewbox():
    factory = import_svg_part("user:demo/Percent", source(
        '<circle id="port:a" cx="50%" cy="50%" data-orientation="90"/>'),
        library=PartLibrary())
    assert factory().ports()["a"].center.as_2d() == pytest.approx((20, -20))


def test_a_path_mark_from_drawsvg_gives_its_first_point_and_direction():
    """drawsvg writes a Line as <path d="M x,y L x,y">: the first point is the port, the second its direction."""

    marks = ('<path id="port:in" d="M-10,0 L-14,0" data-kind="free_space"/>'
             '<path id="port:out" d="M10,0 l4,0" data-kind="free_space"/>')
    part = import_svg_part("user:test/PathMarks", source(marks), library=PartLibrary())(center=(0, 0))
    ports = part.ports()
    assert (round(ports["in"].center.x, 6), round(ports["in"].orientation_deg)) == (-10.0, 180)
    assert (round(ports["out"].center.x, 6), round(ports["out"].orientation_deg % 360)) == (10.0, 0)


@pytest.mark.parametrize("mark", ['<rect id="port:in" x="1" y="1" width="2" height="2"/>',
                                  '<g id="port:in"/>'])
def test_a_mark_whose_position_cannot_be_read_is_an_error_not_the_origin(mark):
    with pytest.raises(ValueError, match="port:in"):
        import_svg_part("user:test/BadMark", source(mark), library=PartLibrary())
