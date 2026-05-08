"""Extract mouse and keyboard cadence episodes from recorder NDJSON files."""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import replace
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from ._generated_data_capture import (
    CaptureEvent,
    FocusedElementEvent,
    KeyboardEvent,
    MouseButtonOrNone,
    MouseClickEvent,
    MouseMoveEvent,
    SessionStartedEvent,
    SessionStoppedEvent,
)
from ._generated_data_capture import (
    FocusedElement as CapturedFocusedElement,
)
from .constants import KEY_BACKSPACE, MOUSE_ACTIONS
from .keyboard_logic import apply_keyboard_action, terminal_edit_actions
from .types import (
    FocusedTextSnapshot,
    KeyboardEpisode,
    KeyStep,
    MouseEpisode,
    MouseStep,
    ScreenSizeFilter,
)
from .utils import iter_events

ScreenSize = tuple[int, int]
CapturedEvent = (
    SessionStartedEvent
    | SessionStoppedEvent
    | MouseMoveEvent
    | MouseClickEvent
    | KeyboardEvent
    | FocusedElementEvent
)


def parse_capture_event(path: Path, line_no: int, raw_event: dict[str, Any]) -> CapturedEvent:
    """Validate one raw NDJSON event against the generated capture contract."""
    try:
        return CaptureEvent.model_validate(raw_event).root
    except ValidationError as exc:
        raise ValueError(f"{path}:{line_no}: invalid capture event: {exc}") from exc


def iter_capture_events(paths: Iterable[Path]):
    """Yield generated capture event models with source path and line number."""
    for path, line_no, raw_event in iter_events(paths):
        yield path, line_no, parse_capture_event(path, line_no, raw_event)


def event_screen_size(event: CapturedEvent) -> ScreenSize | None:
    """Read an optional screen size tuple from a recorder event."""
    if event.screen_width is None or event.screen_height is None:
        return None
    return event.screen_width, event.screen_height


def screen_filter_allows(
    screen_filter: ScreenSizeFilter | None,
    screen_size: ScreenSize | None,
) -> bool:
    """Return whether a screen filter permits the current event context."""
    # This screen-size filter is intentionally a pragmatic corpus hack. The
    # Ergodox EZ setup can emit mouse movement events, and those movements do
    # not reflect the real cursor dynamics we want the cadence models to learn.
    # The local training recordings were collected across distinct display
    # contexts, so we use the laptop/desktop screen envelope as a proxy for
    # "real mouse or trackpad" input and drop events from contexts likely to
    # include keyboard-driven pointer motion.
    return True if screen_filter is None else screen_filter.allows(screen_size)


def keyboard_action_from_event(event: KeyboardEvent) -> str | None:
    """Normalize a recorded physical key event into a model action token."""
    key_class = getattr(event.key_class, "value", event.key_class)
    key = event.key
    if key_class == "backspace" or key in {"Backspace", "Delete"}:
        return KEY_BACKSPACE
    if key in {"Enter", "Return"}:
        return "\n"
    if key == "Spacebar":
        return " "
    if isinstance(key, str) and len(key) == 1:
        return key
    return None


def apply_keyboard_action_to_string(value: str, action: str) -> str:
    """Apply one terminal keyboard action to a string."""
    chars = list(value)
    apply_keyboard_action(chars, action)
    return "".join(chars)


def extract_mouse_episodes(
    paths: list[Path],
    rest_ms: int,
    max_duration_ms: int,
    min_distance: float,
    screen_filter: ScreenSizeFilter | None = None,
) -> list[MouseEpisode]:
    """Extract rest-to-click mouse episodes from recorder event streams."""
    episodes: list[MouseEpisode] = []

    for path in paths:
        # Track one candidate movement chain at a time. A chain starts after a
        # rest gap and is committed only if a qualifying click terminates it.
        pending_moves: list[MouseMoveEvent] = []
        pending_start: tuple[float, float] | None = None
        last_mouse_offset: int | None = None
        last_known_pos: tuple[float, float] | None = None
        current_screen_size: ScreenSize | None = None

        for _, _, event in iter_capture_events([path]):
            if isinstance(event, SessionStartedEvent | SessionStoppedEvent):
                # Session boundaries invalidate motion context, including the
                # last seen screen size used by laptop-only filtering.
                pending_moves = []
                pending_start = None
                last_mouse_offset = None
                last_known_pos = None
                current_screen_size = None
                continue

            explicit_screen_size = event_screen_size(event)
            if explicit_screen_size is not None:
                current_screen_size = explicit_screen_size
            if not screen_filter_allows(screen_filter, current_screen_size):
                # Once the stream leaves the accepted screen profile, drop the
                # partial chain so a later click cannot straddle filter states.
                pending_moves = []
                pending_start = None
                continue

            if isinstance(event, MouseMoveEvent):
                x = event.x
                y = event.y
                offset = event.offset_ms
                if event.drag_button not in {None, MouseButtonOrNone.none}:
                    # Drag gestures are not motivated click movements; keep the
                    # cursor position but reset the pending click path.
                    pending_moves = []
                    pending_start = None
                    last_mouse_offset = offset
                    last_known_pos = (x, y)
                    continue

                starts_from_rest = (
                    last_mouse_offset is None or offset - last_mouse_offset >= rest_ms
                )
                if starts_from_rest:
                    # The recorder reports move deltas, so reconstruct the
                    # resting start point when no previous absolute position is known.
                    delta_x = event.delta_x or 0.0
                    delta_y = event.delta_y or 0.0
                    pending_start = last_known_pos or (x - delta_x, y - delta_y)
                    pending_moves = [event]
                elif pending_moves:
                    pending_moves.append(event)

                last_mouse_offset = offset
                last_known_pos = (x, y)
                continue

            if isinstance(event, MouseClickEvent):
                x = event.x
                y = event.y
                offset = event.offset_ms
                click_count = event.click_count
                button = event.button.value if event.button is not None else "other"
                if (
                    click_count == 1
                    and pending_moves
                    and pending_start is not None
                ):
                    first_offset = pending_moves[0].offset_ms
                    duration = offset - first_offset
                    distance = math.hypot(x - pending_start[0], y - pending_start[1])
                    if 0 <= duration <= max_duration_ms and distance >= min_distance:
                        # Convert absolute move/click events into timed model
                        # steps that preserve the observed action labels.
                        steps: list[MouseStep] = []
                        previous_offset = first_offset
                        for move in pending_moves:
                            move_offset = move.offset_ms
                            dt_ms = move_offset - previous_offset
                            steps.append(MouseStep(dt_ms=dt_ms, x=move.x, y=move.y, action="move"))
                            previous_offset = move_offset

                        action = f"{button}_click" if f"{button}_click" in MOUSE_ACTIONS else "other_click"
                        dt_ms = offset - previous_offset
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
                last_known_pos = (x, y)
                continue

            if isinstance(event, KeyboardEvent) and pending_moves:
                # Keyboard activity means the pointer chain no longer cleanly
                # represents a single motivated mouse click.
                pending_moves = []
                pending_start = None

    return episodes


def focused_element_identity(
    focused_element: CapturedFocusedElement,
    require_value: bool = True,
) -> tuple[str, str | None] | None:
    if focused_element.is_password or focused_element.value_redacted:
        return None
    if require_value and focused_element.value is None:
        return None

    bundle_id = str(focused_element.bundle_id or "")
    accessibility_id = focused_element.accessibility_id
    dom_id = focused_element.dom_id
    role = focused_element.role
    subrole = focused_element.subrole
    process_id = focused_element.process_id

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


def focused_text_snapshot_from_event(source: str, event: CapturedEvent) -> FocusedTextSnapshot | None:
    if not isinstance(event, KeyboardEvent | FocusedElementEvent):
        return None
    focused_element = event.focused_element
    if focused_element is None:
        return None
    identity_result = focused_element_identity(focused_element)
    if identity_result is None:
        return None
    offset = event.offset_ms
    value = focused_element.value
    if not isinstance(value, str):
        return None
    identity, raw_accessibility_id = identity_result
    return FocusedTextSnapshot(
        source=source,
        offset_ms=offset,
        trigger_offset_ms=event.trigger_offset_ms,
        identity=identity,
        raw_accessibility_id=raw_accessibility_id,
        value=value,
        key_action=keyboard_action_from_event(event) if isinstance(event, KeyboardEvent) else None,
        key_code=event.key_code if isinstance(event, KeyboardEvent) else None,
        is_keyboard_event=isinstance(event, KeyboardEvent),
    )


def collect_focused_text_snapshot_segments(
    paths: list[Path],
    screen_filter: ScreenSizeFilter | None = None,
    stats: dict[str, int] | None = None,
) -> list[list[FocusedTextSnapshot]]:
    segments: list[list[FocusedTextSnapshot]] = []
    for path in paths:
        current: list[FocusedTextSnapshot] = []
        current_identity: str | None = None
        current_screen_size: ScreenSize | None = None
        key_actions_by_offset: dict[int, tuple[str | None, int | None]] = {}

        def flush() -> None:
            nonlocal current, current_identity
            if current:
                segments.append(current)
            current = []
            current_identity = None

        for _, _, event in iter_capture_events([path]):
            if isinstance(event, SessionStartedEvent | SessionStoppedEvent):
                flush()
                current_screen_size = None
                key_actions_by_offset.clear()
                continue

            explicit_screen_size = event_screen_size(event)
            if explicit_screen_size is not None:
                current_screen_size = explicit_screen_size
            if not screen_filter_allows(screen_filter, current_screen_size):
                flush()
                continue

            if isinstance(event, KeyboardEvent):
                if event.key is not None and stats is not None:
                    stats["keyboard_events_with_key"] = stats.get("keyboard_events_with_key", 0) + 1
                if event.key_code is not None and stats is not None:
                    stats["keyboard_events_with_key_code"] = stats.get("keyboard_events_with_key_code", 0) + 1
                key_action = keyboard_action_from_event(event)
                if key_action is not None:
                    key_actions_by_offset[event.offset_ms] = (key_action, event.key_code)
                    if stats is not None:
                        stats["keyboard_events_with_supported_key_action"] = (
                            stats.get("keyboard_events_with_supported_key_action", 0) + 1
                        )
                elif event.key is not None:
                    key_actions_by_offset[event.offset_ms] = (None, event.key_code)
                    if stats is not None:
                        stats["keyboard_events_with_unsupported_key"] = (
                            stats.get("keyboard_events_with_unsupported_key", 0) + 1
                        )

            snapshot = focused_text_snapshot_from_event(str(path), event)
            if snapshot is not None:
                if snapshot.key_action is None and snapshot.trigger_offset_ms is not None:
                    key_info = key_actions_by_offset.get(snapshot.trigger_offset_ms)
                    if key_info is not None:
                        snapshot = replace(snapshot, key_action=key_info[0], key_code=key_info[1])
                if snapshot.key_action is not None and stats is not None:
                    stats["focused_text_snapshots_with_key_action"] = (
                        stats.get("focused_text_snapshots_with_key_action", 0) + 1
                    )
                if current and current_identity is not None and snapshot.identity != current_identity:
                    flush()
                current_identity = snapshot.identity
                current.append(snapshot)
                continue

            if isinstance(event, KeyboardEvent | FocusedElementEvent) and event.focused_element is not None:
                focused_element = event.focused_element
                identity_result = focused_element_identity(focused_element, require_value=False)
                if identity_result is None or (
                    current and current_identity is not None and identity_result[0] != current_identity
                ):
                    flush()

        flush()
    return segments


def _append_keyboard_episode(
    episodes: list[KeyboardEpisode],
    source: str,
    identity: str,
    initial_string: str,
    final_string: str,
    steps: list[KeyStep],
) -> None:
    if steps and final_string != initial_string:
        episodes.append(
            KeyboardEpisode(
                source=f"{source}#{identity}",
                initial_string=initial_string,
                final_string=final_string,
                steps=tuple(steps),
            )
        )


def _build_focused_text_diff_episodes(
    snapshots: list[FocusedTextSnapshot],
    gap_ms: int,
    max_snapshot_edit_actions: int,
    stats: dict[str, int] | None = None,
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

        if snapshot.key_action is not None:
            raw_next_value = apply_keyboard_action_to_string(current_value, snapshot.key_action)
            if raw_next_value == snapshot.value:
                actions = [snapshot.key_action]
                if stats is not None:
                    stats["key_level_transition_count"] = stats.get("key_level_transition_count", 0) + 1
                    stats["key_level_action_count"] = stats.get("key_level_action_count", 0) + 1
            else:
                if stats is not None:
                    stats["key_level_mismatch_count"] = stats.get("key_level_mismatch_count", 0) + 1
                flush()
                initial_value = snapshot.value
                current_value = snapshot.value
                current_source = snapshot.source
                last_seen_offset = effective_offset
                last_change_offset = effective_offset
                continue
        elif snapshot.key_code is not None:
            if stats is not None:
                stats["unsupported_key_transition_count"] = stats.get("unsupported_key_transition_count", 0) + 1
            flush()
            initial_value = snapshot.value
            current_value = snapshot.value
            current_source = snapshot.source
            last_seen_offset = effective_offset
            last_change_offset = effective_offset
            continue
        elif stats is not None:
            stats["diff_fallback_transition_count"] = stats.get("diff_fallback_transition_count", 0) + 1
            stats["diff_fallback_action_count"] = stats.get("diff_fallback_action_count", 0) + len(actions)

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


def _build_focused_text_key_stream_episodes(
    snapshots: list[FocusedTextSnapshot],
    gap_ms: int,
    stats: dict[str, int] | None = None,
) -> list[KeyboardEpisode]:
    if not snapshots:
        return []

    # Keyboard events carry the immediate text observation around that physical
    # key, while delayed focused_element snapshots can arrive after later keys
    # and therefore may represent multiple effects.
    ordered = sorted(snapshots, key=lambda item: (item.offset_ms, 0 if item.is_keyboard_event else 1))
    episodes: list[KeyboardEpisode] = []

    initial_value = ordered[0].value
    confirmed_value = initial_value
    current_value = initial_value
    current_source = ordered[0].source
    identity = ordered[0].identity
    committed_steps: list[KeyStep] = []
    pending_steps: list[KeyStep] = []
    last_seen_offset = ordered[0].offset_ms
    last_action_offset = ordered[0].offset_ms

    def increment(name: str, amount: int = 1) -> None:
        if stats is not None:
            stats[name] = stats.get(name, 0) + amount

    def commit_pending() -> None:
        nonlocal confirmed_value, pending_steps
        if not pending_steps:
            return
        committed_steps.extend(pending_steps)
        increment("key_level_transition_count", len(pending_steps))
        increment("key_level_action_count", len(pending_steps))
        pending_steps = []
        confirmed_value = current_value

    def drop_pending() -> None:
        nonlocal current_value, pending_steps
        if pending_steps:
            increment("key_level_dropped_action_count", len(pending_steps))
        pending_steps = []
        current_value = confirmed_value

    def flush_committed() -> None:
        nonlocal committed_steps
        _append_keyboard_episode(
            episodes=episodes,
            source=current_source,
            identity=identity,
            initial_string=initial_value,
            final_string=confirmed_value,
            steps=committed_steps,
        )
        committed_steps = []

    def reset_to(snapshot: FocusedTextSnapshot) -> None:
        nonlocal initial_value, confirmed_value, current_value, current_source, identity, last_action_offset
        flush_committed()
        drop_pending()
        initial_value = snapshot.value
        confirmed_value = snapshot.value
        current_value = snapshot.value
        current_source = snapshot.source
        identity = snapshot.identity
        last_action_offset = snapshot.offset_ms

    def observe(snapshot: FocusedTextSnapshot) -> None:
        nonlocal current_value, confirmed_value
        observed_value = snapshot.value
        if observed_value == current_value:
            commit_pending()
            return
        if observed_value == confirmed_value:
            # A key candidate was observed but the accessible text did not
            # change. Treat it as a shortcut/no-op for text modeling.
            drop_pending()
            return
        increment("key_level_mismatch_count")
        reset_to(snapshot)

    def append_pending_key(snapshot: FocusedTextSnapshot) -> None:
        nonlocal current_value, last_action_offset
        if snapshot.key_action is None:
            return
        dt_ms = max(0.0, float(snapshot.offset_ms - last_action_offset))
        pending_steps.append(KeyStep(dt_ms=dt_ms, action=snapshot.key_action))
        current_value = apply_keyboard_action_to_string(current_value, snapshot.key_action)
        last_action_offset = snapshot.offset_ms
        increment("key_level_candidate_action_count")

    def process_keyboard_action(snapshot: FocusedTextSnapshot) -> None:
        nonlocal current_value
        if snapshot.key_action is None:
            return

        observed_value = snapshot.value
        post_from_current = apply_keyboard_action_to_string(current_value, snapshot.key_action)
        post_from_confirmed = apply_keyboard_action_to_string(confirmed_value, snapshot.key_action)

        if observed_value == current_value:
            # The event carries a pre-key text snapshot.
            commit_pending()
            append_pending_key(snapshot)
            return
        if observed_value == post_from_current:
            # The event already reflects this key and confirms any pending keys.
            append_pending_key(snapshot)
            current_value = observed_value
            commit_pending()
            return
        if observed_value == confirmed_value:
            # Pending candidate actions were not visible in the text stream.
            drop_pending()
            append_pending_key(snapshot)
            return
        if observed_value == post_from_confirmed:
            # Drop stale candidates, but keep the current physical key because
            # the observed value is exactly its terminal effect.
            drop_pending()
            append_pending_key(snapshot)
            current_value = observed_value
            commit_pending()
            return

        increment("key_level_mismatch_count")
        increment("key_level_unmodeled_action_count")
        reset_to(snapshot)

    def process_keyboard_without_text_action(snapshot: FocusedTextSnapshot) -> None:
        observe(snapshot)
        increment("unsupported_key_transition_count")
        reset_to(snapshot)

    started = False
    for snapshot in ordered:
        if started and snapshot.offset_ms - last_seen_offset >= gap_ms:
            reset_to(snapshot)

        if not started:
            started = True
        elif not snapshot.is_keyboard_event:
            observe(snapshot)

        if snapshot.is_keyboard_event and snapshot.key_action is not None:
            process_keyboard_action(snapshot)
        elif snapshot.is_keyboard_event and snapshot.key_code is not None:
            process_keyboard_without_text_action(snapshot)

        last_seen_offset = snapshot.offset_ms

    if pending_steps:
        # The final key in a segment normally has a delayed focused snapshot.
        # Without a confirming observation, keep the corpus conservative.
        drop_pending()
    flush_committed()
    return episodes


def build_focused_text_episodes(
    snapshots: list[FocusedTextSnapshot],
    gap_ms: int,
    max_snapshot_edit_actions: int,
    stats: dict[str, int] | None = None,
) -> list[KeyboardEpisode]:
    if any(snapshot.is_keyboard_event for snapshot in snapshots):
        return _build_focused_text_key_stream_episodes(snapshots, gap_ms=gap_ms, stats=stats)
    return _build_focused_text_diff_episodes(
        snapshots,
        gap_ms=gap_ms,
        max_snapshot_edit_actions=max_snapshot_edit_actions,
        stats=stats,
    )


def extract_focused_text_keyboard_episodes(
    paths: list[Path],
    gap_ms: int,
    accessibility_id: str | None,
    max_snapshot_edit_actions: int,
    screen_filter: ScreenSizeFilter | None = None,
) -> tuple[list[KeyboardEpisode], dict[str, Any]]:
    """Build keyboard episodes from contiguous focused accessibility text."""
    # Segment snapshots by source, screen eligibility, and focused field so a
    # revisit to the same field becomes a separate learnable edit episode.
    key_stream_stats: dict[str, int] = {}
    segments = collect_focused_text_snapshot_segments(paths, screen_filter=screen_filter, stats=key_stream_stats)
    snapshots = [snapshot for segment in segments for snapshot in segment]
    identities = {snapshot.identity for snapshot in snapshots}

    requested = (accessibility_id or "auto").strip()
    metadata: dict[str, Any] = {
        "focused_text_snapshot_count": len(snapshots),
        "focused_text_identity_count": len(identities),
        "focused_text_segment_count": len(segments),
        "requested_accessibility_id": requested,
        "key_stream": key_stream_stats,
    }
    if not snapshots:
        return [], metadata

    # The default now trains over all contiguous focused-text fields. A concrete
    # accessibility id still narrows the corpus for targeted experiments.
    if requested and requested not in {"auto", "all"}:
        selected_segments = [
            segment
            for segment in segments
            if segment
            and (
                segment[0].identity == requested
                or any(snapshot.raw_accessibility_id == requested for snapshot in segment)
            )
        ]
        metadata["selected_accessibility_id_found"] = bool(selected_segments)
        metadata["selected_focused_text_identity"] = requested
    else:
        selected_segments = [segment for segment in segments if segment]
        metadata["selected_accessibility_id_found"] = True
        metadata["selected_focused_text_identity"] = "all"

    episodes: list[KeyboardEpisode] = []
    episode_identities: set[str] = set()
    selected_key_stream_stats: dict[str, int] = {}
    for segment in selected_segments:
        # Each segment is already contiguous in a single field, so value changes
        # inside it can be validated against raw key actions when available, or
        # converted into terminal edit actions for older recordings.
        segment_episodes = build_focused_text_episodes(
            segment,
            gap_ms=gap_ms,
            max_snapshot_edit_actions=max_snapshot_edit_actions,
            stats=selected_key_stream_stats,
        )
        episodes.extend(segment_episodes)
        if segment_episodes:
            episode_identities.add(segment[0].identity)

    selected_snapshots = [snapshot for segment in selected_segments for snapshot in segment]
    raw_ids = sorted({snapshot.raw_accessibility_id for snapshot in selected_snapshots if snapshot.raw_accessibility_id})
    metadata["selected_accessibility_ids"] = raw_ids
    metadata["selected_key_stream"] = selected_key_stream_stats
    metadata["focused_text_segment_count"] = len(segments)
    metadata["selected_focused_text_segment_count"] = len(selected_segments)
    metadata["selected_focused_text_snapshots"] = len(selected_snapshots)
    metadata["focused_text_episode_identity_count"] = len(episode_identities)
    metadata["focused_text_episode_count"] = len(episodes)
    return episodes, metadata
