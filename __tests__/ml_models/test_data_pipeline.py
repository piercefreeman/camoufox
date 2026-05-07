from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from rotunda_models.data import (
    extract_focused_text_keyboard_episodes,
    extract_mouse_episodes,
)
from rotunda_models.types import ScreenSizeFilter


def write_events(events: list[dict]) -> Path:
    with tempfile.NamedTemporaryFile("w", suffix=".ndjson", delete=False) as handle:
        path = Path(handle.name)
        for event in events:
            handle.write(json.dumps(event) + "\n")
    return path


class DataPipelineTests(unittest.TestCase):
    def test_mouse_episodes_are_filtered_to_laptop_screen_sizes(self) -> None:
        path = write_events(
            [
                {"type": "session_started"},
                {"type": "mouse_move", "offsetMs": 0, "x": 10, "y": 10, "deltaX": 0, "deltaY": 0, "dragButton": "none", "screenWidth": 1512, "screenHeight": 982},
                {"type": "mouse_move", "offsetMs": 200, "x": 40, "y": 40, "deltaX": 30, "deltaY": 30, "dragButton": "none", "screenWidth": 1512, "screenHeight": 982},
                {"type": "mouse_click", "offsetMs": 260, "x": 50, "y": 50, "button": "left", "clickCount": 1, "screenWidth": 1512, "screenHeight": 982},
                {"type": "mouse_move", "offsetMs": 1000, "x": 100, "y": 100, "deltaX": 0, "deltaY": 0, "dragButton": "none", "screenWidth": 2560, "screenHeight": 1440},
                {"type": "mouse_move", "offsetMs": 1200, "x": 150, "y": 150, "deltaX": 50, "deltaY": 50, "dragButton": "none", "screenWidth": 2560, "screenHeight": 1440},
                {"type": "mouse_click", "offsetMs": 1260, "x": 160, "y": 160, "button": "left", "clickCount": 1, "screenWidth": 2560, "screenHeight": 1440},
            ]
        )
        try:
            episodes = extract_mouse_episodes(
                [path],
                rest_ms=150,
                max_duration_ms=2000,
                min_distance=8.0,
                screen_filter=ScreenSizeFilter(),
            )
        finally:
            path.unlink()

        self.assertEqual(len(episodes), 1)
        self.assertEqual((episodes[0].dst_x, episodes[0].dst_y), (50, 50))

    def test_focused_text_revisits_are_separate_keyboard_episodes(self) -> None:
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
            [
                {"type": "session_started"},
                {"type": "mouse_move", "offsetMs": 0, "x": 1, "y": 1, "deltaX": 0, "deltaY": 0, "dragButton": "none", "screenWidth": 1512, "screenHeight": 982},
                {"type": "focused_element", "offsetMs": 10, "focusedElement": {**field_a, "value": ""}},
                {"type": "focused_element", "offsetMs": 20, "focusedElement": {**field_a, "value": "h"}},
                {"type": "focused_element", "offsetMs": 30, "focusedElement": {**field_a, "value": "hi"}},
                {"type": "focused_element", "offsetMs": 40, "focusedElement": {**field_b, "value": "x"}},
                {"type": "focused_element", "offsetMs": 50, "focusedElement": {**field_a, "value": "hi"}},
                {"type": "focused_element", "offsetMs": 60, "focusedElement": {**field_a, "value": "hit"}},
            ]
        )
        try:
            episodes, metadata = extract_focused_text_keyboard_episodes(
                [path],
                gap_ms=1000,
                accessibility_id="field-a",
                max_snapshot_edit_actions=12,
                screen_filter=ScreenSizeFilter(),
            )
        finally:
            path.unlink()

        self.assertEqual(metadata["selected_focused_text_segment_count"], 2)
        self.assertEqual([(episode.initial_string, episode.final_string) for episode in episodes], [("", "hi"), ("hi", "hit")])

    def test_auto_focused_text_uses_all_accessibility_fields(self) -> None:
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
            [
                {"type": "session_started"},
                {"type": "mouse_move", "offsetMs": 0, "x": 1, "y": 1, "deltaX": 0, "deltaY": 0, "dragButton": "none", "screenWidth": 1512, "screenHeight": 982},
                {"type": "focused_element", "offsetMs": 10, "focusedElement": {**field_a, "value": ""}},
                {"type": "focused_element", "offsetMs": 20, "focusedElement": {**field_a, "value": "a"}},
                {"type": "focused_element", "offsetMs": 30, "focusedElement": {**field_b, "value": ""}},
                {"type": "focused_element", "offsetMs": 40, "focusedElement": {**field_b, "value": "b"}},
            ]
        )
        try:
            episodes, metadata = extract_focused_text_keyboard_episodes(
                [path],
                gap_ms=1000,
                accessibility_id="auto",
                max_snapshot_edit_actions=12,
                screen_filter=ScreenSizeFilter(),
            )
        finally:
            path.unlink()

        self.assertEqual(metadata["selected_focused_text_identity"], "all")
        self.assertEqual(metadata["focused_text_episode_identity_count"], 2)
        self.assertEqual(sorted(episode.final_string for episode in episodes), ["a", "b"])


if __name__ == "__main__":
    unittest.main()
