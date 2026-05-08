from __future__ import annotations

from rotunda_models.training_utils import (
    filter_keyboard_training_episodes,
    keyboard_training_filter_counts,
)
from rotunda_models.types import KeyboardEpisode, KeyStep


def keyboard_episode(
    initial_string: str,
    final_string: str,
    actions: list[str],
) -> KeyboardEpisode:
    return KeyboardEpisode(
        source="/tmp/session.ndjson#bundle|pid=1|accessibilityID=field",
        initial_string=initial_string,
        final_string=final_string,
        steps=tuple(KeyStep(dt_ms=10.0, action=action) for action in actions),
    )


def test_keyboard_training_filter_limits_condition_and_step_lengths() -> None:
    short = keyboard_episode("", "hello", list("hello"))
    long_condition = keyboard_episode("x" * 20, "done", list("done"))
    long_steps = keyboard_episode("", "abc", list("abcdef"))

    episodes = [short, long_condition, long_steps]
    filtered = filter_keyboard_training_episodes(
        episodes,
        sequence_mode="raw",
        min_final_length=1,
        min_duration_ms=0.0,
        max_condition_length=16,
        max_steps=5,
    )
    counts = keyboard_training_filter_counts(
        episodes,
        sequence_mode="raw",
        min_final_length=1,
        min_duration_ms=0.0,
        max_condition_length=16,
        max_steps=5,
    )

    assert filtered == [short]
    assert counts["input"] == 3
    assert counts["output"] == 1
    assert counts["dropped_max_condition_length"] == 1
    assert counts["dropped_max_steps"] == 1
