from __future__ import annotations

import json
from pathlib import Path

from rotunda_models.constants import KEY_BACKSPACE
from rotunda_models.data import (
    extract_keyboard_episodes,
    extract_mouse_episodes,
)
from rotunda_models.types import ScreenSizeFilter


def write_events(tmp_path: Path, events: list[dict]) -> Path:
    path = tmp_path / "events.ndjson"
    with path.open("w", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event) + "\n")
    return path


def test_mouse_episodes_are_filtered_to_laptop_screen_sizes(tmp_path: Path) -> None:
    path = write_events(
        tmp_path,
        [
            {"type": "session_started"},
            {"type": "mouse_move", "offsetMs": 0, "x": 10, "y": 10, "deltaX": 0, "deltaY": 0, "dragButton": "none", "screenWidth": 1512, "screenHeight": 982},
            {"type": "mouse_move", "offsetMs": 200, "x": 40, "y": 40, "deltaX": 30, "deltaY": 30, "dragButton": "none", "screenWidth": 1512, "screenHeight": 982},
            {"type": "mouse_click", "offsetMs": 260, "x": 50, "y": 50, "button": "left", "clickCount": 1, "screenWidth": 1512, "screenHeight": 982},
            {"type": "mouse_move", "offsetMs": 1000, "x": 100, "y": 100, "deltaX": 0, "deltaY": 0, "dragButton": "none", "screenWidth": 2560, "screenHeight": 1440},
            {"type": "mouse_move", "offsetMs": 1200, "x": 150, "y": 150, "deltaX": 50, "deltaY": 50, "dragButton": "none", "screenWidth": 2560, "screenHeight": 1440},
            {"type": "mouse_click", "offsetMs": 1260, "x": 160, "y": 160, "button": "left", "clickCount": 1, "screenWidth": 2560, "screenHeight": 1440},
        ],
    )
    episodes = extract_mouse_episodes(
        [path],
        rest_ms=150,
        max_duration_ms=2000,
        min_distance=8.0,
        screen_filter=ScreenSizeFilter(),
    )

    assert len(episodes) == 1
    assert (episodes[0].dst_x, episodes[0].dst_y) == (50, 50)


def test_keyboard_extractor_requires_key_level_events(tmp_path: Path) -> None:
    field_a = {
        "bundleID": "com.example",
        "processID": 1,
        "accessibilityID": "field-a",
        "role": "AXTextArea",
        "isPassword": False,
        "valueRedacted": False,
    }
    field_b = {
        "bundleID": "com.example",
        "processID": 1,
        "accessibilityID": "field-b",
        "role": "AXTextArea",
        "isPassword": False,
        "valueRedacted": False,
    }
    path = write_events(
        tmp_path,
        [
            {"type": "session_started"},
            {"type": "mouse_move", "offsetMs": 0, "x": 1, "y": 1, "deltaX": 0, "deltaY": 0, "dragButton": "none", "screenWidth": 1512, "screenHeight": 982},
            {"type": "focused_element", "offsetMs": 10, "focusedElement": {**field_a, "value": ""}},
            {"type": "focused_element", "offsetMs": 20, "focusedElement": {**field_a, "value": "h"}},
            {"type": "focused_element", "offsetMs": 30, "focusedElement": {**field_a, "value": "hi"}},
            {"type": "focused_element", "offsetMs": 40, "focusedElement": {**field_b, "value": "x"}},
            {"type": "focused_element", "offsetMs": 50, "focusedElement": {**field_a, "value": "hi"}},
            {"type": "focused_element", "offsetMs": 60, "focusedElement": {**field_a, "value": "hit"}},
        ],
    )
    episodes, metadata = extract_keyboard_episodes(
        [path],
        gap_ms=1000,
        accessibility_id="field-a",
        screen_filter=ScreenSizeFilter(),
    )

    assert metadata["selected_focused_text_segment_count"] == 2
    assert episodes == []
    assert metadata["focused_text_episode_identity_count"] == 0


def test_auto_keyboard_selection_still_reports_accessibility_fields(tmp_path: Path) -> None:
    field_a = {
        "bundleID": "com.example",
        "processID": 1,
        "accessibilityID": "field-a",
        "role": "AXTextArea",
        "isPassword": False,
        "valueRedacted": False,
    }
    field_b = {
        "bundleID": "com.example",
        "processID": 1,
        "accessibilityID": "field-b",
        "role": "AXTextArea",
        "isPassword": False,
        "valueRedacted": False,
    }
    path = write_events(
        tmp_path,
        [
            {"type": "session_started"},
            {"type": "mouse_move", "offsetMs": 0, "x": 1, "y": 1, "deltaX": 0, "deltaY": 0, "dragButton": "none", "screenWidth": 1512, "screenHeight": 982},
            {"type": "focused_element", "offsetMs": 10, "focusedElement": {**field_a, "value": ""}},
            {"type": "focused_element", "offsetMs": 20, "focusedElement": {**field_a, "value": "a"}},
            {"type": "focused_element", "offsetMs": 30, "focusedElement": {**field_b, "value": ""}},
            {"type": "focused_element", "offsetMs": 40, "focusedElement": {**field_b, "value": "b"}},
        ],
    )
    episodes, metadata = extract_keyboard_episodes(
        [path],
        gap_ms=1000,
        accessibility_id="auto",
        screen_filter=ScreenSizeFilter(),
    )

    assert metadata["selected_focused_text_identity"] == "all"
    assert metadata["selected_focused_text_segment_count"] == 2
    assert episodes == []


def test_keyboard_episodes_prefer_recorded_key_stream(tmp_path: Path) -> None:
    field = {
        "bundleID": "com.example",
        "processID": 1,
        "accessibilityID": "field-a",
        "role": "AXTextArea",
        "isPassword": False,
        "valueRedacted": False,
    }
    path = write_events(
        tmp_path,
        [
            {"type": "session_started"},
            {"type": "mouse_move", "offsetMs": 0, "x": 1, "y": 1, "deltaX": 0, "deltaY": 0, "dragButton": "none", "screenWidth": 1512, "screenHeight": 982},
            {"type": "focused_element", "offsetMs": 10, "focusedElement": {**field, "value": ""}},
            {"type": "keyboard", "offsetMs": 20, "key": "w", "keyCode": 13, "keyClass": "regular", "isRepeat": False, "focusedElement": {**field, "value": ""}},
            {"type": "focused_element", "offsetMs": 60, "triggerOffsetMs": 20, "focusedElement": {**field, "value": "w"}},
            {"type": "keyboard", "offsetMs": 80, "key": "Backspace", "keyCode": 51, "keyClass": "backspace", "isRepeat": False, "focusedElement": {**field, "value": "w"}},
            {"type": "focused_element", "offsetMs": 120, "triggerOffsetMs": 80, "focusedElement": {**field, "value": ""}},
            {"type": "keyboard", "offsetMs": 140, "key": "f", "keyCode": 3, "keyClass": "regular", "isRepeat": False, "focusedElement": {**field, "value": ""}},
            {"type": "focused_element", "offsetMs": 180, "triggerOffsetMs": 140, "focusedElement": {**field, "value": "f"}},
        ],
    )

    episodes, metadata = extract_keyboard_episodes(
        [path],
        gap_ms=1000,
        accessibility_id="field-a",
        screen_filter=ScreenSizeFilter(),
    )

    assert len(episodes) == 1
    assert episodes[0].initial_string == ""
    assert episodes[0].final_string == "f"
    assert [step.action for step in episodes[0].steps] == ["w", KEY_BACKSPACE, "f"]
    assert metadata["selected_key_stream"]["raw_key_run_action_count"] == 3


def test_keyboard_episodes_confirm_rapid_keys_with_delayed_snapshot(tmp_path: Path) -> None:
    field = {
        "bundleID": "com.example",
        "processID": 1,
        "accessibilityID": "field-a",
        "role": "AXTextArea",
        "isPassword": False,
        "valueRedacted": False,
    }
    path = write_events(
        tmp_path,
        [
            {"type": "session_started"},
            {"type": "mouse_move", "offsetMs": 0, "x": 1, "y": 1, "deltaX": 0, "deltaY": 0, "dragButton": "none", "screenWidth": 1512, "screenHeight": 982},
            {"type": "keyboard", "offsetMs": 20, "key": "h", "keyCode": 4, "keyClass": "regular", "isRepeat": False, "focusedElement": {**field, "value": ""}},
            {"type": "keyboard", "offsetMs": 50, "key": "i", "keyCode": 34, "keyClass": "regular", "isRepeat": False, "focusedElement": {**field, "value": "h"}},
            {"type": "focused_element", "offsetMs": 70, "triggerOffsetMs": 20, "focusedElement": {**field, "value": "hi"}},
        ],
    )

    episodes, metadata = extract_keyboard_episodes(
        [path],
        gap_ms=1000,
        accessibility_id="field-a",
        screen_filter=ScreenSizeFilter(),
    )

    assert len(episodes) == 1
    assert episodes[0].final_string == "hi"
    assert [step.action for step in episodes[0].steps] == ["h", "i"]
    assert metadata["selected_key_stream"]["raw_key_run_action_count"] == 2


def test_keyboard_episodes_use_raw_key_runs(tmp_path: Path) -> None:
    field = {
        "bundleID": "com.example",
        "processID": 1,
        "accessibilityID": "field-a",
        "role": "AXTextArea",
        "isPassword": False,
        "valueRedacted": False,
    }
    path = write_events(
        tmp_path,
        [
            {"type": "session_started"},
            {"type": "mouse_move", "offsetMs": 0, "x": 1, "y": 1, "deltaX": 0, "deltaY": 0, "dragButton": "none", "screenWidth": 1512, "screenHeight": 982},
            {"type": "focused_element", "offsetMs": 10, "focusedElement": {**field, "value": "selected text"}},
            {"type": "keyboard", "offsetMs": 40, "key": "h", "keyCode": 4, "keyClass": "regular", "isRepeat": False, "focusedElement": {**field, "value": "selected text"}},
            {"type": "keyboard", "offsetMs": 90, "key": "i", "keyCode": 34, "keyClass": "regular", "isRepeat": False, "focusedElement": {**field, "value": "selected text"}},
        ],
    )

    episodes, metadata = extract_keyboard_episodes(
        [path],
        gap_ms=1000,
        accessibility_id="field-a",
        screen_filter=ScreenSizeFilter(),
    )

    raw_episodes = [episode for episode in episodes if episode.source.endswith("#raw-key-stream")]
    assert len(raw_episodes) == 1
    assert raw_episodes[0].initial_string == ""
    assert raw_episodes[0].final_string == "hi"
    assert [step.dt_ms for step in raw_episodes[0].steps] == [30.0, 50.0]
    assert [step.action for step in raw_episodes[0].steps] == ["h", "i"]
    assert metadata["selected_key_stream"]["raw_key_run_action_count"] == 2


def test_keyboard_episodes_do_not_infer_bridge_actions(tmp_path: Path) -> None:
    field = {
        "bundleID": "com.example",
        "processID": 1,
        "accessibilityID": "field-a",
        "role": "AXTextArea",
        "isPassword": False,
        "valueRedacted": False,
    }
    path = write_events(
        tmp_path,
        [
            {"type": "session_started"},
            {"type": "mouse_move", "offsetMs": 0, "x": 1, "y": 1, "deltaX": 0, "deltaY": 0, "dragButton": "none", "screenWidth": 1512, "screenHeight": 982},
            {"type": "focused_element", "offsetMs": 10, "focusedElement": {**field, "value": "stor"}},
            {"type": "keyboard", "offsetMs": 20, "key": "t", "keyCode": 17, "keyClass": "regular", "isRepeat": False, "focusedElement": {**field, "value": "storty"}},
            {"type": "keyboard", "offsetMs": 30, "key": "y", "keyCode": 16, "keyClass": "regular", "isRepeat": False, "focusedElement": {**field, "value": "storty"}},
            {"type": "keyboard", "offsetMs": 40, "key": " ", "keyCode": 49, "keyClass": "regular", "isRepeat": False, "focusedElement": {**field, "value": "storty "}},
            {"type": "keyboard", "offsetMs": 100, "key": "Backspace", "keyCode": 51, "keyClass": "backspace", "isRepeat": False, "focusedElement": {**field, "value": "storty"}},
            {"type": "keyboard", "offsetMs": 120, "key": "Backspace", "keyCode": 51, "keyClass": "backspace", "isRepeat": False, "focusedElement": {**field, "value": "stort"}},
            {"type": "focused_element", "offsetMs": 130, "triggerOffsetMs": 120, "focusedElement": {**field, "value": "stor"}},
            {"type": "keyboard", "offsetMs": 140, "key": "Backspace", "keyCode": 51, "keyClass": "backspace", "isRepeat": False, "focusedElement": {**field, "value": "stor"}},
            {"type": "keyboard", "offsetMs": 150, "key": "y", "keyCode": 16, "keyClass": "regular", "isRepeat": False, "focusedElement": {**field, "value": "story"}},
            {"type": "keyboard", "offsetMs": 160, "key": " ", "keyCode": 49, "keyClass": "regular", "isRepeat": False, "focusedElement": {**field, "value": "story "}},
        ],
    )

    episodes, metadata = extract_keyboard_episodes(
        [path],
        gap_ms=1000,
        accessibility_id="field-a",
        screen_filter=ScreenSizeFilter(),
    )

    assert len(episodes) == 1
    assert episodes[0].initial_string == ""
    assert episodes[0].final_string == "y "
    assert [step.action for step in episodes[0].steps] == [
        "t",
        "y",
        " ",
        KEY_BACKSPACE,
        KEY_BACKSPACE,
        KEY_BACKSPACE,
        "y",
        " ",
    ]
    assert metadata["selected_key_stream"]["raw_key_run_action_count"] == 8


def test_keyboard_episodes_split_on_observed_field_resets(tmp_path: Path) -> None:
    field = {
        "bundleID": "com.example",
        "processID": 1,
        "accessibilityID": "field-a",
        "role": "AXTextArea",
        "isPassword": False,
        "valueRedacted": False,
    }
    path = write_events(
        tmp_path,
        [
            {"type": "session_started"},
            {"type": "mouse_move", "offsetMs": 0, "x": 1, "y": 1, "deltaX": 0, "deltaY": 0, "dragButton": "none", "screenWidth": 1512, "screenHeight": 982},
            {"type": "focused_element", "offsetMs": 10, "focusedElement": {**field, "value": "p"}},
            {"type": "keyboard", "offsetMs": 20, "key": "h", "keyCode": 4, "keyClass": "regular", "isRepeat": False, "focusedElement": {**field, "value": "p"}},
            {"type": "keyboard", "offsetMs": 30, "key": "o", "keyCode": 31, "keyClass": "regular", "isRepeat": False, "focusedElement": {**field, "value": "ph"}},
            {"type": "keyboard", "offsetMs": 40, "key": "n", "keyCode": 45, "keyClass": "regular", "isRepeat": False, "focusedElement": {**field, "value": "pho"}},
            {"type": "keyboard", "offsetMs": 50, "key": "e", "keyCode": 14, "keyClass": "regular", "isRepeat": False, "focusedElement": {**field, "value": "phon"}},
            {"type": "focused_element", "offsetMs": 60, "triggerOffsetMs": 50, "focusedElement": {**field, "value": "phone"}},
            {"type": "keyboard", "offsetMs": 200, "key": "w", "keyCode": 13, "keyClass": "regular", "isRepeat": False, "focusedElement": {**field, "value": "w"}},
            {"type": "keyboard", "offsetMs": 220, "key": "e", "keyCode": 14, "keyClass": "regular", "isRepeat": False, "focusedElement": {**field, "value": "w"}},
            {"type": "focused_element", "offsetMs": 250, "triggerOffsetMs": 220, "focusedElement": {**field, "value": "we"}},
        ],
    )

    episodes, metadata = extract_keyboard_episodes(
        [path],
        gap_ms=1000,
        accessibility_id="field-a",
        screen_filter=ScreenSizeFilter(),
    )

    assert [(episode.initial_string, episode.final_string) for episode in episodes] == [
        ("", "hone"),
        ("", "we"),
    ]
    assert metadata["selected_key_stream"]["raw_key_run_reset_count"] == 1
