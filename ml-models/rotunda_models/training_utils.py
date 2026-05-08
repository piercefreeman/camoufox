"""Small training helpers that are shared outside the main train command."""

from __future__ import annotations

import random

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


def move_batch_to_device(batch: dict, device: torch.device) -> dict:
    """Move tensor values in a dataloader batch onto the training device."""
    return {key: value.to(device) if torch.is_tensor(value) else value for key, value in batch.items()}


def aggregate_metrics(records: list[dict[str, float]]) -> dict[str, float]:
    """Average a list of per-batch metric dictionaries by key."""
    if not records:
        return {}
    keys = records[0].keys()
    return {key: sum(record[key] for record in records) / len(records) for key in keys}


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
    max_coord = 1.0
    for episode in episodes:
        # Include starts, destinations, and all observed positions so both the
        # model condition and decoder targets share the same normalization.
        max_coord = max(max_coord, abs(episode.start_x), abs(episode.start_y), abs(episode.dst_x), abs(episode.dst_y))
        for step in episode.steps:
            max_coord = max(max_coord, abs(step.x), abs(step.y))
    return max_coord


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
