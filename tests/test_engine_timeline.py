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


def test_nested_click_failure_is_atomic():
    timeline = Timeline()
    before = timeline.to_json()
    with pytest.raises(ValueError, match="Click"):
        timeline.play(Sequence(Create("part:laser1"), Click()))
    assert timeline.to_json() == before
    assert timeline.cursor == 0.0


