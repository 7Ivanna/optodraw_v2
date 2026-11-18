"""A note is free text on a figure: a power, a beam size, a key. The figure checks read it as they read a label."""

from __future__ import annotations

import re

import pytest

from optodraw import Beam, Laser, Mirror, Note, Objective, Photodiode, Scene, check_figure
from optodraw.app.validation import run_checks
from optodraw.layout import aim, face
from optodraw.registry import build_component
from optodraw.schema import scene_from_spec, scene_to_spec
from optodraw.symbols.schematic import build_schematic


def _bench():
    scene = Scene(title="bench", width=100, height=40, platform="free_space")
    laser = scene.add(Laser(center=(-30, 0), label="Laser"))
    pd = scene.add(Photodiode(center=(30, 0), label="PD"))
    beam = scene.add(Beam.through(laser, pd, wavelength=450))
    return scene, beam


def _fold():
    scene = Scene(title="fold", width=120, height=90, platform="free_space")
    laser = scene.add(Laser(center=(-40, 0), label="Laser"))
    mirror = scene.add(Mirror(center=(0, 0), label="M", label_side="bottom-right"))
    pd = scene.add(Photodiode(center=(0, 35), label="PD"))
    aim(mirror, laser, pd)
    face(pd, mirror)
    return scene, scene.add(Beam.through(laser, mirror, pd, wavelength=450))


def test_a_note_draws_its_text_at_its_place():
    scene = Scene(title="note", width=100, height=40, platform="free_space")
    scene.add(Note("880 mW", center=(10, 5), color="#2f6fd0", anchor="start", bold=True))
    svg = scene.render_svg().as_svg()
    assert re.search(r'translate\(10(\.0+)?,\s*-5(\.0+)?\)', svg)
    text = re.search(r"<text[^>]*>[^<]*880 mW", svg).group(0)
    assert 'fill="#2f6fd0"' in text and 'text-anchor="start"' in text and 'font-weight="bold"' in text


def test_a_note_draws_nothing_but_its_text():
    scene = Scene(title="note", width=100, height=40, platform="free_space")
    plain = scene.render_svg().as_svg()
    scene.add(Note("880 mW", center=(10, 5)))
    assert scene.render_svg().as_svg().count("<rect") == plain.count("<rect")


def test_a_note_reaches_the_tikz():
    scene = Scene(title="note", width=100, height=40, platform="free_space")
    scene.add(Note("880 mW", center=(10, 5), anchor="end"))
    assert re.search(r"\\node\[anchor=east[^\]]*\] at \(10[.0]*,\s*5[.0]*\) \{880 mW\}", scene.render_tikz())


def test_a_bad_anchor_is_refused():
    with pytest.raises(ValueError, match="anchor"):
        Note("x", anchor="centre")


def test_a_note_survives_a_save():
    scene = Scene(title="note", width=100, height=40, platform="free_space")
    scene.add(Note("880 mW", center=(10, 5), color="#2f6fd0", anchor="start", bold=True))
    note = next(n for n in scene_from_spec(scene_to_spec(scene)).walk() if isinstance(n, Note))
    assert (note.text, note.color, note.anchor, note.bold) == ("880 mW", "#2f6fd0", "start", True)
    assert tuple(note.world_position.as_tuple()[:2]) == (10, 5)


def test_a_note_comes_from_the_registry():
    assert build_component("Note", text="key", center=(1, 2)).text == "key"


def test_a_note_is_no_part_of_the_bench():
    scene, _ = _bench()
    scene.add(Note("880 mW", center=(0, 8)))
    assert not any(isinstance(n, Note) for n in scene._parts())
    assert not [i for i in run_checks(scene) if "880 mW" in i["message"] or "Note" in i["message"]]
    assert len(build_schematic(scene).items) == 2
    assert Note("880 mW").geometry_3d() == {}               # the 3D page skips a node with no solid


def test_fit_frame_holds_a_note():
    scene, _ = _bench()
    scene.add(Note("a long note at the edge of the figure", center=(60, 0), anchor="start"))
    scene.fit_frame(margin=4)
    assert not any("cut off" in f for f in check_figure(scene, view="2d"))


def test_a_clean_note_passes():
    scene, _ = _bench()
    scene.add(Note("880 mW", center=(0, 8)))
    assert check_figure(scene, view="2d") == []


def test_a_note_cut_off_by_the_frame_is_found():
    scene, _ = _bench()
    scene.add(Note("880 mW", center=(48, 8), anchor="start"))
    assert any("880 mW" in f and "cut off" in f for f in check_figure(scene, view="2d"))


def test_a_note_on_a_beam_is_found():
    scene, _ = _bench()
    scene.add(Note("880 mW", center=(0, 0)))
    assert any("880 mW" in f and "beam" in f for f in check_figure(scene, view="2d"))


def test_a_note_on_a_part_is_found():
    scene, _ = _bench()
    scene.add(Note("880 mW", center=(30, 0)))
    assert any("880 mW" in f and "sits on" in f for f in check_figure(scene, view="2d"))


def test_a_label_over_a_note_is_named_once():
    scene, _ = _bench()
    scene.add(Note("880 mW", center=(-30, 8)))
    found = [f for f in check_figure(scene, view="2d") if "880 mW" in f]
    assert len(found) == 1 and "overlap" in found[0]


def test_legs_are_the_straight_spans_the_beam_draws():
    scene = Scene(title="legs", width=120, height=40, platform="free_space")
    laser = scene.add(Laser(center=(-40, 0), label="Laser"))
    objective = scene.add(Objective(center=(0, 0), label="Objective"))
    pd = scene.add(Photodiode(center=(40, 0), label="PD"))
    legs = Beam.through(laser, objective, pd).legs()
    assert len(legs) == 2 and legs[0][1][0] < 0.0 < legs[1][0][0]        # none across the objective


def test_a_note_on_a_flat_leg_sits_above_or_below_it():
    scene, beam = _bench()
    above = Note.on(beam, "880 mW")
    below = Note.on(beam, "880 mW", side="right")
    assert above.world_position.y > 0.0 > below.world_position.y
    assert above.world_position.x == pytest.approx(below.world_position.x)
    assert above.anchor == "middle" and above.color == beam.color


def test_a_note_on_a_steep_leg_sits_beside_it():
    scene, beam = _fold()
    left = Note.on(beam, "340 mW", leg=1)                                # the light runs up: left is -x
    right = Note.on(beam, "340 mW", leg=1, side="right")
    assert left.anchor == "end" and left.world_position.x < 0.0
    assert right.anchor == "start" and right.world_position.x > 0.0


def test_at_slides_a_note_along_its_leg():
    scene, beam = _bench()
    start, end = beam.legs()[0]
    assert Note.on(beam, "x", at=0.25).world_position.x == pytest.approx(start[0] + 0.25 * (end[0] - start[0]))


def test_a_leg_the_beam_does_not_have_is_refused():
    scene, beam = _bench()
    with pytest.raises(ValueError, match="1 straight leg"):
        Note.on(beam, "x", leg=4)


def test_a_bad_side_is_refused():
    scene, beam = _bench()
    with pytest.raises(ValueError, match="side"):
        Note.on(beam, "x", side="top")


def test_a_note_on_a_beam_passes_the_checks():
    scene, beam = _fold()
    scene.add(Note.on(beam, "880 mW", leg=0))
    scene.add(Note.on(beam, "340 mW", leg=1, side="left"))
    assert not [f for f in check_figure(scene, view="2d") if "mW" in f]


def test_a_note_works_in_the_editor():
    from optodraw.app.session import EditorSession

    session = EditorSession()
    note = session.add_component("Note", {"text": "880 mW", "center": [10.0, 5.0]})
    session.update(note, {"label": "790 mW", "angle": 90.0, "color": "#2f6fd0"})
    placed = next(n for n in session.scene().walk() if isinstance(n, Note))
    assert (placed.text, placed.color) == ("790 mW", "#2f6fd0")
    assert float(placed.transform.rotation_deg.z) == 90.0


def test_a_new_note_from_the_palette_has_text():
    from optodraw.app.session import EditorSession

    session = EditorSession()
    session.add_component("Note")
    assert next(n for n in session.scene().walk() if isinstance(n, Note)).text
