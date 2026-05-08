from __future__ import annotations

from rotunda_models.constants import KEY_BACKSPACE
from rotunda_models.dataset_inspection import (
    format_keyboard_episode_block,
    format_keyboard_episode_report,
    keyboard_action_trace,
    keyboard_text_evolution,
)
from rotunda_models.diagnostics import KEYBOARD_EPOCH_INSPECTION_TABLE_KEY
from rotunda_models.types import KeyboardEpisode, KeyStep


def typo_episode() -> KeyboardEpisode:
    return KeyboardEpisode(
        source="/tmp/session.ndjson#bundle|pid=1|accessibilityID=field",
        initial_string="t",
        final_string="thanks",
        steps=(
            KeyStep(dt_ms=10.0, action="h"),
            KeyStep(dt_ms=20.0, action="a"),
            KeyStep(dt_ms=30.0, action="n"),
            KeyStep(dt_ms=40.0, action="s"),
            KeyStep(dt_ms=50.0, action="k"),
            KeyStep(dt_ms=60.0, action=KEY_BACKSPACE),
            KeyStep(dt_ms=70.0, action=KEY_BACKSPACE),
            KeyStep(dt_ms=80.0, action="k"),
            KeyStep(dt_ms=90.0, action="s"),
        ),
    )


def test_keyboard_action_trace_marks_insertions_and_deletions() -> None:
    trace = keyboard_action_trace(typo_episode())

    assert trace == "+h +a +n +s +k -k -s +k +s"


def test_keyboard_text_evolution_marks_deleted_characters() -> None:
    evolution = keyboard_text_evolution(typo_episode())

    assert evolution == "than~s~~k~ks"


def test_keyboard_episode_report_filters_and_summarizes() -> None:
    report = format_keyboard_episode_report(
        [typo_episode()],
        metadata={
            "selected_key_stream": {
                "raw_key_run_episode_count": 1,
                "raw_key_run_action_count": 9,
                "raw_key_run_reset_count": 0,
            }
        },
        limit=10,
        query="thanks",
    )

    assert "keyboard episodes: 1 total, 1 matched, showing 1" in report
    assert "raw_actions=9" in report
    assert "initial:  't'" in report
    assert "final:    'thanks'" in report
    assert "actions:  +h +a +n +s +k -k -s +k +s" in report
    assert "timeline: than~s~~k~ks" in report


def test_keyboard_episode_block_matches_inspect_detail_shape() -> None:
    block = format_keyboard_episode_block(typo_episode(), index=13)

    assert "[13] session.ndjson#bundle|pid=1|accessibilityID=field" in block
    assert "steps=9 backspaces=2 duration_ms=450.0 valid=True" in block
    assert "initial:  't'" in block
    assert "actions:  +h +a +n +s +k -k -s +k +s" in block


def test_keyboard_epoch_inspection_table_key_is_stable_across_epochs() -> None:
    assert KEYBOARD_EPOCH_INSPECTION_TABLE_KEY == "keyboard_inspect/examples_epoch"
