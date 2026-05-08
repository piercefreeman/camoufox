"""Human-readable dataset inspection helpers."""

from __future__ import annotations

from .constants import KEY_BACKSPACE
from .keyboard_logic import apply_keyboard_steps, keyboard_episode_transforms_to_final
from .types import KeyboardEpisode

ANSI_STRIKE = "\x1b[9m"
ANSI_RESET = "\x1b[0m"


def display_key(action: str) -> str:
    """Return a compact printable label for a keyboard action."""
    if action == KEY_BACKSPACE:
        return "<BS>"
    if action == " ":
        return "<SPACE>"
    if action == "\n":
        return "<ENTER>"
    if action == "\t":
        return "<TAB>"
    return action


def display_text(text: str) -> str:
    """Escape control characters while keeping normal text readable."""
    return text.replace("\\", "\\\\").replace("\n", "\\n").replace("\t", "\\t")


def deleted_text(text: str, ansi: bool) -> str:
    """Format deleted text for terminal output."""
    if ansi:
        return f"{ANSI_STRIKE}{text}{ANSI_RESET}"
    return f"~{text}~"


def keyboard_action_trace(episode: KeyboardEpisode) -> str:
    """Return raw key actions with inserted/deleted character labels."""
    live_chars: list[tuple[str, bool]] = [(char, False) for char in episode.initial_string]
    tokens: list[str] = []
    for step in episode.steps:
        if step.action == KEY_BACKSPACE:
            deleted = ""
            for index in range(len(live_chars) - 1, -1, -1):
                char, is_deleted = live_chars[index]
                if not is_deleted:
                    live_chars[index] = (char, True)
                    deleted = char
                    break
            tokens.append(f"-{display_key(deleted)}" if deleted else "-<EMPTY>")
        else:
            live_chars.append((step.action, False))
            tokens.append(f"+{display_key(step.action)}")
    return " ".join(tokens)


def keyboard_text_evolution(episode: KeyboardEpisode, ansi: bool = False) -> str:
    """Render the typed text stream with deleted characters marked inline."""
    live_chars: list[tuple[str, bool]] = [(char, False) for char in episode.initial_string]
    for step in episode.steps:
        if step.action == KEY_BACKSPACE:
            for index in range(len(live_chars) - 1, -1, -1):
                char, is_deleted = live_chars[index]
                if not is_deleted:
                    live_chars[index] = (char, True)
                    break
        else:
            live_chars.append((step.action, False))

    parts: list[str] = []
    for char, is_deleted in live_chars:
        rendered = display_text(char)
        parts.append(deleted_text(rendered, ansi=ansi) if is_deleted else rendered)
    return "".join(parts)


def source_label(source: str) -> str:
    """Shorten episode source while keeping the focused-field identity visible."""
    path, separator, identity = source.partition("#")
    filename = path.rsplit("/", 1)[-1]
    return f"{filename}{separator}{identity}" if separator else filename


def episode_matches_query(episode: KeyboardEpisode, query: str) -> bool:
    """Return whether a keyboard episode matches a case-insensitive query."""
    lowered = query.lower()
    haystack = "\n".join(
        [
            episode.source,
            episode.initial_string,
            episode.final_string,
            keyboard_action_trace(episode),
        ]
    ).lower()
    return lowered in haystack


def format_keyboard_episode_report(
    episodes: list[KeyboardEpisode],
    metadata: dict,
    limit: int,
    query: str | None = None,
    ansi: bool = False,
) -> str:
    """Build a human-readable keyboard dataset report."""
    filtered = [
        (index, episode)
        for index, episode in enumerate(episodes, start=1)
        if not query or episode_matches_query(episode, query)
    ]
    selected = filtered[: max(0, limit)]
    key_stream = metadata.get("selected_key_stream", {})
    lines = [
        f"keyboard episodes: {len(episodes)} total, {len(filtered)} matched, showing {len(selected)}",
        (
            "key stream: "
            f"confirmed_actions={key_stream.get('key_level_action_count', 0)} "
            f"candidates={key_stream.get('key_level_candidate_action_count', 0)} "
            f"bridged={key_stream.get('key_level_bridge_action_count', 0)} "
            f"dropped={key_stream.get('key_level_dropped_action_count', 0)} "
            f"mismatches={key_stream.get('key_level_mismatch_count', 0)}"
        ),
    ]
    if query:
        lines.append(f"query: {query!r}")

    for index, episode in selected:
        duration_ms = sum(step.dt_ms for step in episode.steps)
        backspaces = sum(1 for step in episode.steps if step.action == KEY_BACKSPACE)
        result = apply_keyboard_steps(episode.initial_string, episode.steps)
        valid = keyboard_episode_transforms_to_final(episode)
        lines.extend(
            [
                "",
                f"[{index}] {source_label(episode.source)}",
                (
                    f"    steps={len(episode.steps)} backspaces={backspaces} "
                    f"duration_ms={duration_ms:.1f} valid={valid}"
                ),
                f"    initial:  {display_text(episode.initial_string)!r}",
                f"    final:    {display_text(episode.final_string)!r}",
                f"    result:   {display_text(result)!r}",
                f"    actions:  {keyboard_action_trace(episode)}",
                f"    timeline: {keyboard_text_evolution(episode, ansi=ansi)}",
            ]
        )

    if len(filtered) > len(selected):
        lines.append("")
        lines.append(f"... {len(filtered) - len(selected)} more matched episodes hidden by --keyboard-detail-limit")
    return "\n".join(lines)
