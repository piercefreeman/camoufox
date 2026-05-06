"""Extract mouse and keyboard cadence episodes from recorder NDJSON files."""

from __future__ import annotations

import math
import random
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from .constants import BACKSPACE_POS, KEY_BACKSPACE, KEY_LAYOUT, MOUSE_ACTIONS
from .keyboard_logic import apply_key_actions, terminal_edit_actions
from .types import (
    FocusedTextSnapshot,
    KeyboardEpisode,
    KeyDef,
    KeyStep,
    MouseEpisode,
    MouseStep,
)
from .utils import as_float, as_int, iter_events


def extract_mouse_episodes(
    paths: list[Path],
    rest_ms: int,
    max_duration_ms: int,
    min_distance: float,
) -> list[MouseEpisode]:
    episodes: list[MouseEpisode] = []

    for path in paths:
        pending_moves: list[dict] = []
        pending_start: tuple[float, float] | None = None
        last_mouse_offset: int | None = None
        last_known_pos: tuple[float, float] | None = None

        for _, _, event in iter_events([path]):
            event_type = event.get("type")
            offset = as_int(event.get("offsetMs"))

            if event_type in {"session_started", "session_stopped"}:
                pending_moves = []
                pending_start = None
                last_mouse_offset = None
                last_known_pos = None
                continue

            if event_type == "mouse_move":
                x = as_float(event.get("x"))
                y = as_float(event.get("y"))
                if offset is None or x is None or y is None:
                    continue

                if event.get("dragButton", "none") != "none":
                    pending_moves = []
                    pending_start = None
                    last_mouse_offset = offset
                    last_known_pos = (x, y)
                    continue

                starts_from_rest = (
                    last_mouse_offset is None or offset - last_mouse_offset >= rest_ms
                )
                if starts_from_rest:
                    delta_x = as_float(event.get("deltaX"), 0.0) or 0.0
                    delta_y = as_float(event.get("deltaY"), 0.0) or 0.0
                    pending_start = last_known_pos or (x - delta_x, y - delta_y)
                    pending_moves = [event]
                elif pending_moves:
                    pending_moves.append(event)

                last_mouse_offset = offset
                last_known_pos = (x, y)
                continue

            if event_type == "mouse_click":
                x = as_float(event.get("x"))
                y = as_float(event.get("y"))
                click_count = as_int(event.get("clickCount"))
                button = str(event.get("button", "other"))
                if (
                    offset is not None
                    and x is not None
                    and y is not None
                    and click_count == 1
                    and pending_moves
                    and pending_start is not None
                ):
                    first_offset = as_int(pending_moves[0].get("offsetMs"))
                    duration = offset - first_offset if first_offset is not None else max_duration_ms + 1
                    distance = math.hypot(x - pending_start[0], y - pending_start[1])
                    if 0 <= duration <= max_duration_ms and distance >= min_distance:
                        steps: list[MouseStep] = []
                        previous_offset = first_offset
                        for move in pending_moves:
                            move_offset = as_int(move.get("offsetMs"))
                            move_x = as_float(move.get("x"))
                            move_y = as_float(move.get("y"))
                            if move_offset is None or move_x is None or move_y is None:
                                continue
                            dt_ms = 0.0 if previous_offset is None else move_offset - previous_offset
                            steps.append(MouseStep(dt_ms=dt_ms, x=move_x, y=move_y, action="move"))
                            previous_offset = move_offset

                        action = f"{button}_click" if f"{button}_click" in MOUSE_ACTIONS else "other_click"
                        dt_ms = 0.0 if previous_offset is None else offset - previous_offset
                        steps.append(MouseStep(dt_ms=dt_ms, x=x, y=y, action=action))
                        episodes.append(
                            MouseEpisode(
                                source=str(path),
                                start_x=pending_start[0],
                                start_y=pending_start[1],
                                dst_x=x,
                                dst_y=y,
                                steps=tuple(steps),
                            )
                        )

                pending_moves = []
                pending_start = None
                last_mouse_offset = offset
                if x is not None and y is not None:
                    last_known_pos = (x, y)
                continue

            if event_type == "keyboard" and pending_moves:
                pending_moves = []
                pending_start = None

    return episodes


def split_keyboard_sequences(
    paths: list[Path],
    gap_ms: int,
    include_repeats: bool,
) -> list[tuple[str, list[dict]]]:
    sequences: list[tuple[str, list[dict]]] = []
    for path in paths:
        current: list[dict] = []
        last_offset: int | None = None
        for _, _, event in iter_events([path]):
            if event.get("type") in {"session_started", "session_stopped"}:
                if current:
                    sequences.append((str(path), current))
                current = []
                last_offset = None
                continue

            if event.get("type") != "keyboard":
                continue
            if event.get("isRepeat") and not include_repeats:
                continue

            offset = as_int(event.get("offsetMs"))
            if offset is None:
                continue
            if last_offset is not None and offset - last_offset >= gap_ms and current:
                sequences.append((str(path), current))
                current = []
            current.append(event)
            last_offset = offset

        if current:
            sequences.append((str(path), current))
    return sequences


def focused_element_identity(focused_element: dict[str, Any]) -> tuple[str, str | None] | None:
    if focused_element.get("isPassword") or focused_element.get("valueRedacted"):
        return None
    if focused_element.get("value") is None:
        return None

    bundle_id = str(focused_element.get("bundleID") or "")
    accessibility_id = focused_element.get("accessibilityID")
    dom_id = focused_element.get("domID")
    role = focused_element.get("role")
    subrole = focused_element.get("subrole")
    process_id = focused_element.get("processID")

    raw_id = None
    if accessibility_id:
        raw_id = str(accessibility_id)
        element_key = f"accessibilityID={raw_id}"
    elif dom_id:
        raw_id = str(dom_id)
        element_key = f"domID={raw_id}"
    else:
        role_bits = [str(item) for item in (role, subrole) if item]
        if not role_bits:
            return None
        element_key = "role=" + "/".join(role_bits)

    bundle_key = bundle_id or "unknown_bundle"
    process_key = f"pid={process_id}" if process_id is not None else "pid=unknown"
    return f"{bundle_key}|{process_key}|{element_key}", raw_id


def focused_text_snapshot_from_event(source: str, event: dict[str, Any]) -> FocusedTextSnapshot | None:
    event_type = event.get("type")
    if event_type not in {"keyboard", "focused_element"}:
        return None
    focused_element = event.get("focusedElement")
    if not isinstance(focused_element, dict):
        return None
    identity_result = focused_element_identity(focused_element)
    if identity_result is None:
        return None
    offset = as_int(event.get("offsetMs"))
    if offset is None:
        return None
    value = focused_element.get("value")
    if not isinstance(value, str):
        return None
    identity, raw_accessibility_id = identity_result
    return FocusedTextSnapshot(
        source=source,
        offset_ms=offset,
        trigger_offset_ms=as_int(event.get("triggerOffsetMs")),
        identity=identity,
        raw_accessibility_id=raw_accessibility_id,
        value=value,
    )


def collect_focused_text_snapshots(paths: list[Path]) -> list[FocusedTextSnapshot]:
    snapshots: list[FocusedTextSnapshot] = []
    for path, _, event in iter_events(paths):
        snapshot = focused_text_snapshot_from_event(str(path), event)
        if snapshot is not None:
            snapshots.append(snapshot)
    return snapshots


def focused_text_snapshot_groups(snapshots: Iterable[FocusedTextSnapshot]) -> dict[str, list[FocusedTextSnapshot]]:
    groups: dict[str, list[FocusedTextSnapshot]] = {}
    for snapshot in snapshots:
        groups.setdefault(snapshot.identity, []).append(snapshot)
    return groups


def select_focused_text_identity(
    groups: dict[str, list[FocusedTextSnapshot]],
    requested_accessibility_id: str | None,
) -> tuple[str | None, dict[str, Any]]:
    if not groups:
        return None, {"focused_text_snapshot_count": 0, "focused_text_identity_count": 0}

    candidates = list(groups.items())
    if requested_accessibility_id and requested_accessibility_id != "auto":
        requested = requested_accessibility_id.strip()
        candidates = [
            (identity, snapshots)
            for identity, snapshots in candidates
            if identity == requested
            or any(snapshot.raw_accessibility_id == requested for snapshot in snapshots)
        ]
        if not candidates:
            return None, {
                "focused_text_snapshot_count": sum(len(items) for items in groups.values()),
                "focused_text_identity_count": len(groups),
                "requested_accessibility_id": requested,
                "selected_accessibility_id_found": False,
            }

    def score(item: tuple[str, list[FocusedTextSnapshot]]) -> tuple[int, int]:
        _, snapshots = item
        changed_values = 0
        previous_value: str | None = None
        for snapshot in sorted(snapshots, key=lambda item: (item.effective_offset_ms, item.offset_ms)):
            if previous_value is not None and snapshot.value != previous_value:
                changed_values += 1
            previous_value = snapshot.value
        return changed_values, len(snapshots)

    selected_identity, selected_snapshots = max(candidates, key=score)
    raw_ids = sorted({snapshot.raw_accessibility_id for snapshot in selected_snapshots if snapshot.raw_accessibility_id})
    return selected_identity, {
        "focused_text_snapshot_count": sum(len(items) for items in groups.values()),
        "focused_text_identity_count": len(groups),
        "selected_focused_text_identity": selected_identity,
        "selected_accessibility_ids": raw_ids,
        "selected_focused_text_snapshots": len(selected_snapshots),
        "selected_accessibility_id_found": True,
    }


def build_focused_text_episodes(
    snapshots: list[FocusedTextSnapshot],
    gap_ms: int,
    max_snapshot_edit_actions: int,
) -> list[KeyboardEpisode]:
    if len(snapshots) < 2:
        return []

    ordered = sorted(snapshots, key=lambda item: (item.effective_offset_ms, item.offset_ms))
    episodes: list[KeyboardEpisode] = []
    initial_value = ordered[0].value
    current_value = initial_value
    last_seen_offset = ordered[0].effective_offset_ms
    last_change_offset = ordered[0].effective_offset_ms
    current_source = ordered[0].source
    steps: list[KeyStep] = []

    def flush() -> None:
        nonlocal steps, initial_value, current_value
        if steps and current_value != initial_value:
            episodes.append(
                KeyboardEpisode(
                    source=f"{current_source}#{ordered[0].identity}",
                    initial_string=initial_value,
                    final_string=current_value,
                    steps=tuple(steps),
                )
            )
        steps = []

    for snapshot in ordered[1:]:
        effective_offset = snapshot.effective_offset_ms
        if effective_offset - last_seen_offset >= gap_ms:
            flush()
            initial_value = snapshot.value
            current_value = snapshot.value
            current_source = snapshot.source
            last_seen_offset = effective_offset
            last_change_offset = effective_offset
            continue

        actions = terminal_edit_actions(current_value, snapshot.value)
        if not actions:
            last_seen_offset = effective_offset
            continue

        if len(actions) > max_snapshot_edit_actions:
            flush()
            initial_value = snapshot.value
            current_value = snapshot.value
            current_source = snapshot.source
            last_seen_offset = effective_offset
            last_change_offset = effective_offset
            continue

        total_dt_ms = max(0.0, float(effective_offset - last_change_offset))
        dt_ms = total_dt_ms / len(actions)
        steps.extend(KeyStep(dt_ms=dt_ms, action=action) for action in actions)
        current_value = snapshot.value
        current_source = snapshot.source
        last_seen_offset = effective_offset
        last_change_offset = effective_offset

    flush()
    return episodes


def extract_focused_text_keyboard_episodes(
    paths: list[Path],
    gap_ms: int,
    accessibility_id: str | None,
    max_snapshot_edit_actions: int,
) -> tuple[list[KeyboardEpisode], dict[str, Any]]:
    snapshots = collect_focused_text_snapshots(paths)
    groups = focused_text_snapshot_groups(snapshots)
    selected_identity, metadata = select_focused_text_identity(groups, accessibility_id)
    if selected_identity is None:
        return [], metadata
    episodes = build_focused_text_episodes(
        groups[selected_identity],
        gap_ms=gap_ms,
        max_snapshot_edit_actions=max_snapshot_edit_actions,
    )
    metadata["focused_text_episode_count"] = len(episodes)
    return episodes, metadata


def snap_regular_key(x: float, y: float, tolerance: float) -> str | None:
    best_token: str | None = None
    best_distance = float("inf")
    for key_def in KEY_LAYOUT:
        distance = math.hypot(x - key_def.x, y - key_def.y)
        if distance < best_distance:
            best_distance = distance
            best_token = key_def.token
    return best_token if best_distance <= tolerance else None


def snap_backspace(x: float, y: float, tolerance: float) -> str | None:
    return KEY_BACKSPACE if math.hypot(x - BACKSPACE_POS[0], y - BACKSPACE_POS[1]) <= tolerance else None


def reconstruct_keyboard_episode(
    source: str,
    sequence: list[dict],
    start: KeyDef | str,
    tolerance: float,
) -> KeyboardEpisode | None:
    if not sequence:
        return None

    first = sequence[0]
    first_offset = as_int(first.get("offsetMs"))
    if first_offset is None:
        return None

    if start == KEY_BACKSPACE:
        prev_x, prev_y = BACKSPACE_POS
        actions = [KEY_BACKSPACE]
    else:
        prev_x, prev_y = start.x, start.y
        actions = [start.token]

    steps = [KeyStep(dt_ms=0.0, action=actions[0])]
    previous_offset = first_offset

    for event in sequence[1:]:
        offset = as_int(event.get("offsetMs"))
        dx = as_float(event.get("keyDeltaX"))
        dy = as_float(event.get("keyDeltaY"))
        if offset is None or dx is None or dy is None:
            return None

        x = prev_x + dx
        y = prev_y + dy
        if event.get("keyClass") == "backspace":
            action = snap_backspace(x, y, tolerance)
        else:
            action = snap_regular_key(x, y, tolerance)
        if action is None:
            return None

        steps.append(KeyStep(dt_ms=offset - previous_offset, action=action))
        actions.append(action)
        previous_offset = offset
        if action == KEY_BACKSPACE:
            prev_x, prev_y = BACKSPACE_POS
        else:
            key_def = next(item for item in KEY_LAYOUT if item.token == action)
            prev_x, prev_y = key_def.x, key_def.y

    return KeyboardEpisode(
        source=source,
        final_string=apply_key_actions(actions),
        steps=tuple(steps),
    )


def extract_keyboard_episodes(
    paths: list[Path],
    gap_ms: int,
    synthetic_per_sequence: int,
    include_repeats: bool,
    tolerance: float,
    seed: int,
) -> list[KeyboardEpisode]:
    rng = random.Random(seed)
    episodes: list[KeyboardEpisode] = []
    sequences = split_keyboard_sequences(paths, gap_ms=gap_ms, include_repeats=include_repeats)

    for source, sequence in sequences:
        if sequence[0].get("keyClass") == "backspace":
            starts: list[KeyDef | str] = [KEY_BACKSPACE]
        else:
            starts = list(KEY_LAYOUT)
            rng.shuffle(starts)

        accepted = 0
        seen_final: set[tuple[str, tuple[str, ...]]] = set()
        for start in starts:
            episode = reconstruct_keyboard_episode(source, sequence, start, tolerance=tolerance)
            if episode is None:
                continue
            key = (episode.final_string, tuple(step.action for step in episode.steps))
            if key in seen_final:
                continue
            seen_final.add(key)
            episodes.append(episode)
            accepted += 1
            if accepted >= synthetic_per_sequence:
                break

    return episodes
