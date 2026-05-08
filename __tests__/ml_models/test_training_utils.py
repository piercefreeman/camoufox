from __future__ import annotations

from rotunda_models.training_utils import (
    filter_keyboard_training_episodes,
    keyboard_sweep_score_metrics,
    keyboard_training_filter_counts,
    summarize_metric_observations,
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


def test_summarize_metric_observations_combines_epoch_values_exactly() -> None:
    summary = summarize_metric_observations(
        [
            {
                "target_wait_ms_median_values": [10.0, 50.0],
                "key_action_error_rate_mean_values": [0.0, 1.0],
            },
            {
                "target_wait_ms_median_values": [30.0],
                "key_action_error_rate_mean_values": [1.0],
            },
        ]
    )

    assert summary["target_wait_ms_median"] == 30.0
    assert summary["key_action_error_rate"] == 2.0 / 3.0


def test_keyboard_sweep_score_metrics_blends_behavior_terms() -> None:
    scores = keyboard_sweep_score_metrics(
        train_metrics={},
        val_metrics={
            "target_wait_ms_median": 50.0,
            "pred_wait_ms_median": 60.0,
            "target_edit_duration_ms_median": 200.0,
            "pred_edit_duration_ms_median": 250.0,
            "target_press_count_median": 4.0,
            "pred_press_count_median": 5.0,
            "key_action_error_rate": 0.2,
            "target_typo_rate": 0.1,
            "predicted_typo_rate": 0.2,
            "typo_precision": 0.75,
            "typo_recall": 0.5,
        },
    )

    assert scores["score/keyboard_wait_timing_error"] == 10.0 / 60.0
    assert scores["score/keyboard_duration_timing_error"] == 50.0 / 250.0
    assert scores["score/keyboard_press_budget_error"] == 1.0 / 5.0
    assert scores["score/keyboard_action_error"] == 0.2
    assert scores["score/keyboard_typo_behavior_error"] == (0.1 + 0.25 + 0.5) / 3.0
    assert scores["score/composite"] == (
        (10.0 / 60.0) + (50.0 / 250.0) + (1.0 / 5.0) + 0.2 + ((0.1 + 0.25 + 0.5) / 3.0)
    ) / 5.0
