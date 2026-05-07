"""Extract mouse and keyboard cadence episodes from recorder NDJSON files."""

from __future__ import annotations

import math
from collections.abc import Iterable
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
from .constants import MOUSE_ACTIONS
from .keyboard_logic import terminal_edit_actions
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
    return True if screen_filter is None else screen_filter.allows(screen_size)


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
    )


def collect_focused_text_snapshot_segments(
    paths: list[Path],
    screen_filter: ScreenSizeFilter | None = None,
) -> list[list[FocusedTextSnapshot]]:
    segments: list[list[FocusedTextSnapshot]] = []
    for path in paths:
        current: list[FocusedTextSnapshot] = []
        current_identity: str | None = None
        current_screen_size: ScreenSize | None = None

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
                continue

            explicit_screen_size = event_screen_size(event)
            if explicit_screen_size is not None:
                current_screen_size = explicit_screen_size
            if not screen_filter_allows(screen_filter, current_screen_size):
                flush()
                continue

            snapshot = focused_text_snapshot_from_event(str(path), event)
            if snapshot is not None:
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
    screen_filter: ScreenSizeFilter | None = None,
) -> tuple[list[KeyboardEpisode], dict[str, Any]]:
    """Build keyboard episodes from contiguous focused accessibility text."""
    # Segment snapshots by source, screen eligibility, and focused field so a
    # revisit to the same field becomes a separate learnable edit episode.
    segments = collect_focused_text_snapshot_segments(paths, screen_filter=screen_filter)
    snapshots = [snapshot for segment in segments for snapshot in segment]
    identities = {snapshot.identity for snapshot in snapshots}

    requested = (accessibility_id or "auto").strip()
    metadata: dict[str, Any] = {
        "focused_text_snapshot_count": len(snapshots),
        "focused_text_identity_count": len(identities),
        "focused_text_segment_count": len(segments),
        "requested_accessibility_id": requested,
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
    for segment in selected_segments:
        # Each segment is already contiguous in a single field, so value changes
        # inside it can be converted into terminal edit actions directly.
        segment_episodes = build_focused_text_episodes(
            segment,
            gap_ms=gap_ms,
            max_snapshot_edit_actions=max_snapshot_edit_actions,
        )
        episodes.extend(segment_episodes)
        if segment_episodes:
            episode_identities.add(segment[0].identity)

    selected_snapshots = [snapshot for segment in selected_segments for snapshot in segment]
    raw_ids = sorted({snapshot.raw_accessibility_id for snapshot in selected_snapshots if snapshot.raw_accessibility_id})
    metadata["selected_accessibility_ids"] = raw_ids
    metadata["focused_text_segment_count"] = len(segments)
    metadata["selected_focused_text_segment_count"] = len(selected_segments)
    metadata["selected_focused_text_snapshots"] = len(selected_snapshots)
    metadata["focused_text_episode_identity_count"] = len(episode_identities)
    metadata["focused_text_episode_count"] = len(episodes)
    return episodes, metadata
