import pytest

from optodraw.animation_engine.primitives import Click, Create, FadeIn, Lagged, Sequence
from optodraw.animation_engine.timeline import Timeline


def test_parallel_sequence_and_lagged_schedule_exact_starts():
    timeline = Timeline()
    timeline.play(Create("part:laser1", seconds=1), FadeIn("part:lens1", seconds=2))
    timeline.play(Sequence(
        Create("part:mirror1", seconds=1),
        Lagged(
            FadeIn("part:photodiode1", seconds=1),
            FadeIn("part:photodiode2", seconds=2),
            lag=0.25,
        ),
    ))
    assert [track.start for track in timeline.tracks] == [0, 0, 2, 3, 3.25]
    assert [track.id for track in timeline.tracks] == ["t1", "t2", "t3", "t4", "t5"]
    assert timeline.cursor == 5.25


def test_empty_clicks_and_a_trailing_section_are_stable():
    timeline = Timeline()
    timeline.click().click()
    timeline.wait(1).click().click().wait(0.5)
    before = list(timeline.sections)
    data = timeline.to_json()
    assert data["sections"] == [
        {"id": "s1", "start": 0.0, "end": 1.0},
        {"id": "s2", "start": 1.0, "end": 1.5},
    ]
    assert timeline.sections == before
    assert timeline.to_json() == data


def test_nested_click_failure_is_atomic():
    timeline = Timeline()
    before = timeline.to_json()
    with pytest.raises(ValueError, match="Click"):
        timeline.play(Sequence(Create("part:laser1"), Click()))
    assert timeline.to_json() == before
    assert timeline.cursor == 0.0


def test_ordinary_tracks_are_editable_and_json_round_trips():
    timeline = Timeline(view="1d")
    timeline.play(FadeIn("part:laser1", seconds=0.5))
    timeline.tracks[0].easing = "linear"
    timeline.click()
    data = timeline.to_json()
    assert data["tracks"][0]["easing"] == "linear"
    restored = Timeline.from_json(data)
    assert restored.to_json() == data
    restored.wait(0.25)
    assert restored.tracks[-1].id == "t2"
    assert restored.cursor == 0.75
