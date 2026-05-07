"""Keyboard edit helpers shared by data extraction, training, and decoding."""

from __future__ import annotations

from collections.abc import Iterable

from .constants import CHAR_EOS, KEY_BACKSPACE, KEY_STOP
from .types import KeyboardEpisode, KeyStep


def apply_keyboard_steps(initial_string: str, steps: Iterable[KeyStep]) -> str:
    chars = list(initial_string)
    for step in steps:
        if step.action == KEY_BACKSPACE:
            if chars:
                chars.pop()
        else:
            chars.append(step.action)
    return "".join(chars)


def common_prefix_length(left: str, right: str) -> int:
    limit = min(len(left), len(right))
    for index in range(limit):
        if left[index] != right[index]:
            return index
    return limit


def terminal_edit_actions(previous: str, current: str) -> list[str]:
    """Return the shortest terminal edit path from previous text to current text."""
    prefix_len = common_prefix_length(previous, current)
    return [KEY_BACKSPACE] * (len(previous) - prefix_len) + list(current[prefix_len:])


def keyboard_episode_transforms_to_final(episode: KeyboardEpisode) -> bool:
    """Validate that an episode's steps actually produce its final string."""
    return apply_keyboard_steps(episode.initial_string, episode.steps) == episode.final_string


def canonical_keyboard_steps(episode: KeyboardEpisode) -> tuple[KeyStep, ...]:
    """Collapse an episode into the timed actions that survive in the final text."""
    if episode.initial_string:
        # Focused-text episodes can start from non-empty text. Convert them to
        # the shortest terminal edit path while preserving the observed duration.
        actions = terminal_edit_actions(episode.initial_string, episode.final_string)
        if not actions:
            return ()
        duration = sum(step.dt_ms for step in episode.steps)
        dt_ms = duration / len(actions) if actions else 0.0
        return tuple(KeyStep(dt_ms=dt_ms, action=action) for action in actions)

    offset = 0.0
    surviving: list[tuple[str, float]] = []
    for step in episode.steps:
        # For raw key streams, keep only characters that survive later
        # backspaces so constrained training learns the target-producing path.
        offset += step.dt_ms
        if step.action == KEY_BACKSPACE:
            if surviving:
                surviving.pop()
        else:
            surviving.append((step.action, offset))

    if "".join(action for action, _ in surviving) != episode.final_string:
        # This should not happen for reconstructed episodes, but keep the
        # constrained training path total-duration aware if the source is noisy.
        if not episode.final_string:
            return ()
        dt_ms = offset / len(episode.final_string) if episode.final_string else 0.0
        return tuple(KeyStep(dt_ms=dt_ms, action=char) for char in episode.final_string)

    previous_offset = 0.0
    steps: list[KeyStep] = []
    for action, action_offset in surviving:
        steps.append(KeyStep(dt_ms=max(0.0, action_offset - previous_offset), action=action))
        previous_offset = action_offset
    return tuple(steps)


def apply_keyboard_action(text: list[str], action: str) -> None:
    """Mutate text by applying one generated keyboard action."""
    if action == KEY_BACKSPACE:
        if text:
            text.pop()
    elif action != KEY_STOP:
        text.append(action)


def keyboard_next_char(final_string: str, text: list[str]) -> str:
    """Return the next target character if text is still on the target prefix."""
    current = "".join(text)
    if final_string.startswith(current) and len(current) < len(final_string):
        return final_string[len(current)]
    return CHAR_EOS


def constrained_keyboard_action(final_string: str, text: list[str]) -> str:
    """Return the shortest valid next action that can still reach final_string."""
    current = "".join(text)
    if current == final_string:
        return KEY_STOP
    if final_string.startswith(current):
        return final_string[len(current)]
    return KEY_BACKSPACE


def minimum_terminal_edit_steps(final_string: str, text: list[str]) -> int:
    """Count the minimum actions needed to transform current text to target text."""
    current = "".join(text)
    return len(terminal_edit_actions(current, final_string))
