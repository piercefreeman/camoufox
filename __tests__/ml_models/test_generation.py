from __future__ import annotations

import pytest
import torch
from rotunda_models.constants import KEY_BACKSPACE, KEY_STOP
from rotunda_models.generation import (
    decode_keyboard_rows,
    require_keyboard_target_supported,
    structured_keyboard_action_ids,
)
from rotunda_models.models.keyboard import KeyboardActionGRU


def test_structured_decode_does_not_backspace_valid_prefix() -> None:
    action_to_id = {"a": 0, "b": 1, "c": 2, KEY_BACKSPACE: 3, KEY_STOP: 4}

    valid_from_empty = structured_keyboard_action_ids(
        final_string="abc",
        text=[],
        action_to_id=action_to_id,
        remaining_steps_after_action=4,
    )
    valid_from_prefix = structured_keyboard_action_ids(
        final_string="abc",
        text=["a"],
        action_to_id=action_to_id,
        remaining_steps_after_action=3,
    )
    valid_from_mismatch = structured_keyboard_action_ids(
        final_string="abc",
        text=["a", "x"],
        action_to_id={**action_to_id, "x": 5},
        remaining_steps_after_action=2,
    )

    assert action_to_id[KEY_BACKSPACE] not in valid_from_empty
    assert action_to_id[KEY_BACKSPACE] not in valid_from_prefix
    assert action_to_id[KEY_BACKSPACE] in valid_from_mismatch


def test_keyboard_target_support_only_checks_required_insertions() -> None:
    action_to_id = {"a": 0, "t": 1, KEY_BACKSPACE: 2, KEY_STOP: 3}

    require_keyboard_target_supported("@C", "@Cat", action_to_id)

    with pytest.raises(SystemExit, match="'n'"):
        require_keyboard_target_supported("@C", "@Can", action_to_id)


def test_learned_typo_head_can_choose_reachable_wrong_character() -> None:
    char_to_id = {"<PAD>": 0, "<UNK>": 1, "<EOS>": 2, "<SEP>": 3, "a": 4, "x": 5}
    action_to_id = {"a": 0, "x": 1, KEY_BACKSPACE: 2, KEY_STOP: 3}
    id_to_action = {index: action for action, index in action_to_id.items()}
    model_config = {
        "char_vocab_size": len(char_to_id),
        "action_vocab_size": len(action_to_id),
        "hidden_size": 6,
        "char_embed_size": 4,
        "action_embed_size": 4,
        "layers": 1,
        "dropout": 0.0,
        "learned_typo_head": True,
    }
    model = KeyboardActionGRU(**model_config)
    with torch.no_grad():
        for parameter in model.parameters():
            parameter.zero_()
        model.action_head.bias[action_to_id["a"]] = 4.0
        model.action_head.bias[action_to_id[KEY_BACKSPACE]] = 3.0
        model.action_head.bias[action_to_id[KEY_STOP]] = -4.0
        model.typo_head.bias.fill_(8.0)
        model.typo_action_head.bias[action_to_id["x"]] = 6.0
    checkpoint = {
        "kind": "keyboard_action_gru",
        "model_config": model_config,
        "char_to_id": char_to_id,
        "action_to_id": action_to_id,
        "id_to_action": id_to_action,
    }

    rows = decode_keyboard_rows(
        checkpoint=checkpoint,
        model=model,
        final_string="a",
        device=torch.device("cpu"),
        max_steps=4,
        structured_extra_steps=2,
        max_typos=1,
        learned_typo_threshold=0.5,
    )

    assert [row["action"] for row in rows] == ["x", KEY_BACKSPACE, "a"]
    assert rows[0]["stepKind"] == "learned_typo"
    assert rows[-1]["textAfter"] == "a"


def test_constrained_decode_blocks_learned_typo_without_extra_budget() -> None:
    char_to_id = {"<PAD>": 0, "<UNK>": 1, "<EOS>": 2, "<SEP>": 3, "a": 4, "x": 5}
    action_to_id = {"a": 0, "x": 1, KEY_BACKSPACE: 2, KEY_STOP: 3}
    id_to_action = {index: action for action, index in action_to_id.items()}
    model_config = {
        "char_vocab_size": len(char_to_id),
        "action_vocab_size": len(action_to_id),
        "hidden_size": 6,
        "char_embed_size": 4,
        "action_embed_size": 4,
        "layers": 1,
        "dropout": 0.0,
        "learned_typo_head": True,
    }
    model = KeyboardActionGRU(**model_config)
    with torch.no_grad():
        for parameter in model.parameters():
            parameter.zero_()
        model.action_head.bias[action_to_id["x"]] = 5.0
        model.action_head.bias[action_to_id["a"]] = 1.0
        model.typo_head.bias.fill_(8.0)
        model.typo_action_head.bias[action_to_id["x"]] = 6.0
    checkpoint = {
        "kind": "keyboard_action_gru",
        "model_config": model_config,
        "char_to_id": char_to_id,
        "action_to_id": action_to_id,
        "id_to_action": id_to_action,
    }

    rows = decode_keyboard_rows(
        checkpoint=checkpoint,
        model=model,
        final_string="a",
        device=torch.device("cpu"),
        max_steps=1,
        structured_extra_steps=0,
        max_typos=1,
        learned_typo_threshold=0.5,
    )

    assert [row["action"] for row in rows] == ["a"]
    assert rows[0]["stepKind"] == "model_target"
