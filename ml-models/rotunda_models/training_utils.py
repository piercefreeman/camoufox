"""Small training helpers that are shared outside the main train command."""

from __future__ import annotations

import math
import random
from collections import defaultdict

import torch

from .constants import (
    CHAR_EOS,
    CHAR_PAD,
    CHAR_SEP,
    CHAR_UNK,
    KEY_BACKSPACE,
    KEY_LAYOUT,
    KEY_STOP,
)
from .keyboard_logic import canonical_keyboard_steps
from .types import KeyboardEpisode, MouseEpisode
from .utils import mean, median


def move_batch_to_device(batch: dict, device: torch.device) -> dict:
    """Move tensor values in a dataloader batch onto the training device."""
    return {key: value.to(device) if torch.is_tensor(value) else value for key, value in batch.items()}


def aggregate_metrics(records: list[dict[str, float]]) -> dict[str, float]:
    """Average a list of per-batch metric dictionaries by key."""
    if not records:
        return {}
    keys = records[0].keys()
    return {key: sum(record[key] for record in records) / len(records) for key in keys}


def summarize_metric_observations(records: list[dict[str, list[float]]]) -> dict[str, float]:
    """Collapse per-batch observation lists into exact epoch-level metrics."""
    if not records:
        return {}
    merged: dict[str, list[float]] = defaultdict(list)
    for record in records:
        for key, values in record.items():
            merged[key].extend(values)

    summary: dict[str, float] = {}
    for key, values in merged.items():
        if key.endswith("_median_values"):
            summary[f"{key.removesuffix('_median_values')}_median"] = median(values)
        elif key.endswith("_mean_values"):
            summary[key.removesuffix("_mean_values")] = mean(values)
        else:
            raise ValueError(
                f"Unknown metric observation key {key!r}. "
                "Expected suffix '_median_values' or '_mean_values'."
            )
    return summary


def _finite_metric(metrics: dict[str, float], key: str) -> float | None:
    """Read one scalar metric and drop missing or non-finite values."""
    value = metrics.get(key)
    if value is None:
        return None
    numeric = float(value)
    if not math.isfinite(numeric):
        return None
    return numeric


def _bounded_relative_error(predicted: float | None, target: float | None, floor: float) -> float | None:
    """Normalize an absolute error into a bounded [0, 1] penalty."""
    if predicted is None or target is None:
        return None
    scale = max(abs(predicted), abs(target), float(floor))
    if scale <= 0.0:
        return 0.0
    return min(abs(predicted - target) / scale, 1.0)


def keyboard_sweep_score_metrics(
    train_metrics: dict[str, float],
    val_metrics: dict[str, float],
) -> dict[str, float]:
    """Build behavior-facing keyboard sweep scores from train/val metrics."""
    source = val_metrics if val_metrics else train_metrics
    wait_timing_error = _bounded_relative_error(
        _finite_metric(source, "pred_wait_ms_median"),
        _finite_metric(source, "target_wait_ms_median"),
        floor=25.0,
    )
    duration_timing_error = _bounded_relative_error(
        _finite_metric(source, "pred_edit_duration_ms_median"),
        _finite_metric(source, "target_edit_duration_ms_median"),
        floor=100.0,
    )
    press_budget_error = _bounded_relative_error(
        _finite_metric(source, "pred_press_count_median"),
        _finite_metric(source, "target_press_count_median"),
        floor=1.0,
    )
    action_error = _finite_metric(source, "key_action_error_rate")

    typo_terms: list[float] = []
    target_typo_rate = _finite_metric(source, "target_typo_rate")
    predicted_typo_rate = _finite_metric(source, "predicted_typo_rate")
    if target_typo_rate is not None and predicted_typo_rate is not None:
        typo_terms.append(abs(predicted_typo_rate - target_typo_rate))
    typo_precision = _finite_metric(source, "typo_precision")
    if typo_precision is not None:
        typo_terms.append(1.0 - typo_precision)
    typo_recall = _finite_metric(source, "typo_recall")
    if typo_recall is not None:
        typo_terms.append(1.0 - typo_recall)
    typo_behavior_error = mean(typo_terms) if typo_terms else None

    scores: dict[str, float] = {}
    if wait_timing_error is not None:
        scores["score/keyboard_wait_timing_error"] = wait_timing_error
    if duration_timing_error is not None:
        scores["score/keyboard_duration_timing_error"] = duration_timing_error
    if press_budget_error is not None:
        scores["score/keyboard_press_budget_error"] = press_budget_error
    if action_error is not None:
        scores["score/keyboard_action_error"] = action_error
    if typo_behavior_error is not None:
        scores["score/keyboard_typo_behavior_error"] = typo_behavior_error

    components = [
        wait_timing_error,
        duration_timing_error,
        press_budget_error,
        action_error,
        typo_behavior_error,
    ]
    valid_components = [value for value in components if value is not None]
    if valid_components:
        scores["score/composite"] = mean(valid_components)
    return scores


def sweep_score_metrics(
    task: str | None,
    train_metrics: dict[str, float],
    val_metrics: dict[str, float],
) -> dict[str, float]:
    """Return task-specific sweep score metrics."""
    if task == "keyboard":
        return keyboard_sweep_score_metrics(train_metrics, val_metrics)
    return {}


def split_items(items: list, val_fraction: float, seed: int) -> tuple[list, list]:
    """Return deterministic train/validation splits while keeping one train item."""
    shuffled = list(items)
    random.Random(seed).shuffle(shuffled)
    if len(shuffled) < 2:
        return shuffled, []
    val_size = max(1, round(len(shuffled) * val_fraction))
    val_size = min(val_size, len(shuffled) - 1)
    return shuffled[val_size:], shuffled[:val_size]


def coordinate_scale_for(episodes: list[MouseEpisode]) -> float:
    """Find a stable coordinate normalization scale for mouse episodes."""
    magnitudes: list[float] = []
    for episode in episodes:
        # Include starts, destinations, and all observed positions so both the
        # model condition and decoder targets share the same normalization.
        magnitudes.extend([abs(episode.start_x), abs(episode.start_y), abs(episode.dst_x), abs(episode.dst_y)])
        for step in episode.steps:
            magnitudes.extend([abs(step.x), abs(step.y)])
    if not magnitudes:
        return 1.0
    magnitudes.sort()
    index = min(len(magnitudes) - 1, max(0, round((len(magnitudes) - 1) * 0.95)))
    return max(1.0, magnitudes[index])


def build_keyboard_vocabs(episodes: list[KeyboardEpisode]) -> tuple[dict[str, int], dict[str, int]]:
    """Build character and action vocabularies from keyboard training episodes."""
    chars = set()
    action_chars = {item.token for item in KEY_LAYOUT}
    for episode in episodes:
        # Text conditions need initial/final characters, while action targets
        # need physical edits plus the explicit terminal tokens.
        chars.update(episode.initial_string)
        chars.update(episode.final_string)
        for step in episode.steps:
            if step.action not in {KEY_BACKSPACE, KEY_STOP}:
                chars.add(step.action)
                action_chars.add(step.action)
    char_tokens = [CHAR_PAD, CHAR_UNK, CHAR_EOS, CHAR_SEP, *sorted(chars | {item.token for item in KEY_LAYOUT})]
    action_tokens = [*sorted(action_chars), KEY_BACKSPACE, KEY_STOP]
    return (
        {token: index for index, token in enumerate(char_tokens)},
        {token: index for index, token in enumerate(action_tokens)},
    )


def keyboard_episode_duration_ms(episode: KeyboardEpisode, sequence_mode: str) -> float:
    """Return the duration used for keyboard filtering and diagnostics."""
    steps = canonical_keyboard_steps(episode) if sequence_mode == "constrained" else episode.steps
    return sum(step.dt_ms for step in steps)


def keyboard_step_count(episode: KeyboardEpisode, sequence_mode: str) -> int:
    """Return the decoder action count used for keyboard length filtering."""
    steps = canonical_keyboard_steps(episode) if sequence_mode == "constrained" else episode.steps
    return len(steps)


def keyboard_condition_length(episode: KeyboardEpisode) -> int:
    """Return encoded initial/final text length including separator and EOS."""
    return len(episode.initial_string) + 1 + len(episode.final_string) + 1


def keyboard_training_filter_reason(
    episode: KeyboardEpisode,
    sequence_mode: str,
    min_final_length: int,
    min_duration_ms: float,
    max_condition_length: int | None,
    max_steps: int | None,
) -> str | None:
    """Return the first training filter reason that rejects a keyboard episode."""
    if len(episode.final_string) < min_final_length:
        return "min_final_length"
    if keyboard_episode_duration_ms(episode, sequence_mode) < min_duration_ms:
        return "min_duration_ms"
    if max_condition_length is not None and keyboard_condition_length(episode) > max_condition_length:
        return "max_condition_length"
    if max_steps is not None and keyboard_step_count(episode, sequence_mode) > max_steps:
        return "max_steps"
    return None


def keyboard_training_filter_counts(
    episodes: list[KeyboardEpisode],
    sequence_mode: str,
    min_final_length: int,
    min_duration_ms: float,
    max_condition_length: int | None,
    max_steps: int | None,
) -> dict[str, int]:
    """Count keyboard episodes kept and rejected by preprocessing filters."""
    counts = {
        "input": len(episodes),
        "output": 0,
        "dropped": 0,
        "dropped_min_final_length": 0,
        "dropped_min_duration_ms": 0,
        "dropped_max_condition_length": 0,
        "dropped_max_steps": 0,
    }
    for episode in episodes:
        reason = keyboard_training_filter_reason(
            episode,
            sequence_mode=sequence_mode,
            min_final_length=min_final_length,
            min_duration_ms=min_duration_ms,
            max_condition_length=max_condition_length,
            max_steps=max_steps,
        )
        if reason is None:
            counts["output"] += 1
        else:
            counts["dropped"] += 1
            counts[f"dropped_{reason}"] += 1
    return counts


def filter_keyboard_training_episodes(
    episodes: list[KeyboardEpisode],
    sequence_mode: str,
    min_final_length: int,
    min_duration_ms: float,
    max_condition_length: int | None,
    max_steps: int | None,
) -> list[KeyboardEpisode]:
    """Drop keyboard episodes with targets or text conditions outside training bounds."""
    filtered = []
    for episode in episodes:
        reason = keyboard_training_filter_reason(
            episode,
            sequence_mode=sequence_mode,
            min_final_length=min_final_length,
            min_duration_ms=min_duration_ms,
            max_condition_length=max_condition_length,
            max_steps=max_steps,
        )
        if reason is not None:
            continue
        filtered.append(episode)
    return filtered
