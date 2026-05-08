from __future__ import annotations

import torch
from rotunda_models.constants import MOUSE_ACTIONS
from rotunda_models.models.keyboard import (
    KeyboardActionGRU,
    KeyboardTrajectoryDataset,
    collate_keyboard,
    keyboard_loss,
)
from rotunda_models.models.mouse import (
    MouseTrajectoryDataset,
    MouseTrajectoryGRU,
    collate_mouse,
    mouse_loss,
)
from rotunda_models.training_utils import build_keyboard_vocabs
from rotunda_models.types import KeyboardEpisode, KeyStep, MouseEpisode, MouseStep


def tiny_mouse_episodes() -> list[MouseEpisode]:
    return [
        MouseEpisode(
            source="fixture-a",
            start_x=10.0,
            start_y=10.0,
            dst_x=40.0,
            dst_y=30.0,
            steps=(
                MouseStep(dt_ms=16.0, x=20.0, y=16.0, action="move"),
                MouseStep(dt_ms=18.0, x=32.0, y=24.0, action="move"),
                MouseStep(dt_ms=12.0, x=40.0, y=30.0, action="left_click"),
            ),
        ),
        MouseEpisode(
            source="fixture-b",
            start_x=60.0,
            start_y=40.0,
            dst_x=25.0,
            dst_y=22.0,
            steps=(
                MouseStep(dt_ms=20.0, x=48.0, y=34.0, action="move"),
                MouseStep(dt_ms=14.0, x=25.0, y=22.0, action="right_click"),
            ),
        ),
    ]


def tiny_keyboard_episodes() -> list[KeyboardEpisode]:
    return [
        KeyboardEpisode(
            source="fixture-a",
            initial_string="",
            final_string="ab",
            steps=(
                KeyStep(dt_ms=30.0, action="a"),
                KeyStep(dt_ms=45.0, action="b"),
            ),
        ),
        KeyboardEpisode(
            source="fixture-b",
            initial_string="a",
            final_string="ac",
            steps=(KeyStep(dt_ms=25.0, action="c"),),
        ),
    ]


def has_nonzero_gradient(model: torch.nn.Module) -> bool:
    return any(
        parameter.grad is not None and bool(parameter.grad.detach().abs().sum() > 0)
        for parameter in model.parameters()
    )


def test_mouse_model_forward_backward_step_on_tiny_dataset() -> None:
    torch.manual_seed(0)
    dataset = MouseTrajectoryDataset(tiny_mouse_episodes(), coordinate_scale=100.0)
    batch = collate_mouse([dataset[0], dataset[1]])
    model = MouseTrajectoryGRU(
        condition_dim=7,
        previous_dim=3 + len(MOUSE_ACTIONS) + 1,
        hidden_size=12,
        action_count=len(MOUSE_ACTIONS),
        layers=1,
        dropout=0.0,
    )

    dt_pred, pos_pred, action_logits = model(batch["condition"], batch["previous"])

    assert dt_pred.shape == batch["dt"].shape
    assert pos_pred.shape == batch["pos"].shape
    assert action_logits.shape[:2] == batch["actions"].shape
    assert action_logits.shape[-1] == len(MOUSE_ACTIONS)

    loss, metrics = mouse_loss(batch, model, duration_weight=0.5)
    assert torch.isfinite(loss)
    assert metrics["loss"] > 0.0

    optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3)
    optimizer.zero_grad(set_to_none=True)
    loss.backward()

    assert has_nonzero_gradient(model)

    optimizer.step()


def test_keyboard_model_forward_backward_step_on_tiny_dataset() -> None:
    torch.manual_seed(0)
    episodes = tiny_keyboard_episodes()
    char_to_id, action_to_id = build_keyboard_vocabs(episodes)
    dataset = KeyboardTrajectoryDataset(
        episodes,
        char_to_id=char_to_id,
        action_to_id=action_to_id,
        sequence_mode="raw",
    )
    batch = collate_keyboard([dataset[0], dataset[1]], len(action_to_id))
    model = KeyboardActionGRU(
        char_vocab_size=len(char_to_id),
        action_vocab_size=len(action_to_id),
        hidden_size=12,
        char_embed_size=8,
        action_embed_size=8,
        layers=1,
        dropout=0.0,
    )

    dt_pred, action_logits = model(
        batch["final_ids"],
        batch["final_lengths"],
        batch["previous_actions"],
        batch["previous_dt"],
        batch["next_char_ids"],
    )

    assert dt_pred.shape == batch["dt"].shape
    assert action_logits.shape[:2] == batch["actions"].shape
    assert action_logits.shape[-1] == len(action_to_id)

    loss, metrics = keyboard_loss(batch, model, duration_weight=0.5)
    assert torch.isfinite(loss)
    assert metrics["loss"] > 0.0

    optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3)
    optimizer.zero_grad(set_to_none=True)
    loss.backward()

    assert has_nonzero_gradient(model)

    optimizer.step()
