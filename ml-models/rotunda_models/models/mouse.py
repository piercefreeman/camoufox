"""Mouse click trajectory dataset, model, and objective."""

from __future__ import annotations

import math
from typing import TypedDict

import torch
from torch import nn
from torch.nn import functional as F
from torch.utils.data import Dataset

from ..constants import MOUSE_ACTIONS
from ..types import MouseEpisode
from ..utils import dt_to_log, goal_relative_position
from .common import masked_smooth_l1


class MouseSample(TypedDict):
    """Unbatched tensors emitted by MouseTrajectoryDataset.

    Shapes:
    - `condition`: `[7]` normalized start/destination/delta/distance values.
    - `dt`: `[steps]` log1p millisecond delays.
    - `pos`: `[steps, 2]` goal-relative movement deltas.
    - `state`: `[steps, 2]` previous goal-relative absolute positions.
    - `actions`: `[steps]` mouse action class ids.
    """

    condition: torch.Tensor
    dt: torch.Tensor
    pos: torch.Tensor
    state: torch.Tensor
    actions: torch.Tensor


class MouseBatch(TypedDict):
    """Padded mouse tensors consumed by MouseTrajectoryGRU and mouse_loss."""

    condition: torch.Tensor
    dt: torch.Tensor
    pos: torch.Tensor
    actions: torch.Tensor
    mask: torch.Tensor
    previous: torch.Tensor


class MouseLossMetrics(TypedDict):
    """Scalar mouse loss components logged per batch."""

    loss: float
    dt_loss: float
    weighted_dt_loss: float
    pos_loss: float
    weighted_pos_loss: float
    action_loss: float
    duration_loss: float
    weighted_duration_loss: float


class MouseTrajectoryDataset(Dataset):
    """Tensor view of motivated mouse movement-to-click episodes.

    Each sample conditions the model on the start point, destination, raw delta,
    and scalar distance, all normalized by the largest observed coordinate.
    Targets are per-step log delays, action labels, and goal-relative position
    deltas. The goal-relative frame is intentionally used instead of raw screen
    deltas so the GRU learns a trajectory shape toward the destination rather
    than memorizing absolute monitor coordinates.
    """

    def __init__(self, episodes: list[MouseEpisode], coordinate_scale: float):
        self.episodes = episodes
        self.coordinate_scale = max(1.0, float(coordinate_scale))
        self.action_to_id = {action: index for index, action in enumerate(MOUSE_ACTIONS)}

    def __len__(self) -> int:
        return len(self.episodes)

    def __getitem__(self, index: int) -> MouseSample:
        """Encode one click episode into condition and decoder target tensors."""
        episode = self.episodes[index]
        scale = self.coordinate_scale
        dx = episode.dst_x - episode.start_x
        dy = episode.dst_y - episode.start_y
        distance = math.hypot(dx, dy)
        condition = torch.tensor(
            [
                episode.start_x / scale,
                episode.start_y / scale,
                episode.dst_x / scale,
                episode.dst_y / scale,
                dx / scale,
                dy / scale,
                distance / scale,
            ],
            dtype=torch.float32,
        )
        dt = torch.tensor([dt_to_log(step.dt_ms) for step in episode.steps], dtype=torch.float32)
        absolute_positions = [
            goal_relative_position(
                episode.start_x,
                episode.start_y,
                episode.dst_x,
                episode.dst_y,
                step.x,
                step.y,
            )
            for step in episode.steps
        ]
        previous_positions = [(0.0, 0.0), *absolute_positions[:-1]]
        deltas = [
            (position[0] - previous[0], position[1] - previous[1])
            for previous, position in zip(previous_positions, absolute_positions, strict=True)
        ]
        pos = torch.tensor(deltas, dtype=torch.float32)
        state = torch.tensor(previous_positions, dtype=torch.float32)
        actions = torch.tensor([self.action_to_id[step.action] for step in episode.steps], dtype=torch.long)
        return {"condition": condition, "dt": dt, "pos": pos, "state": state, "actions": actions}


def collate_mouse(batch: list[MouseSample]) -> MouseBatch:
    """Pad mouse trajectory samples and build autoregressive decoder inputs."""
    batch_size = len(batch)
    max_len = max(item["dt"].shape[0] for item in batch)
    num_prev_actions = len(MOUSE_ACTIONS) + 1
    bos_index = len(MOUSE_ACTIONS)

    condition = torch.stack([item["condition"] for item in batch])
    dt = torch.zeros(batch_size, max_len, dtype=torch.float32)
    pos = torch.zeros(batch_size, max_len, 2, dtype=torch.float32)
    actions = torch.full((batch_size, max_len), -100, dtype=torch.long)
    mask = torch.zeros(batch_size, max_len, dtype=torch.bool)
    previous = torch.zeros(batch_size, max_len, 3 + num_prev_actions, dtype=torch.float32)

    for row, item in enumerate(batch):
        # Copy variable-length targets into padded tensors and mark the valid
        # positions that should contribute to losses.
        length = item["dt"].shape[0]
        dt[row, :length] = item["dt"]
        pos[row, :length] = item["pos"]
        actions[row, :length] = item["actions"]
        mask[row, :length] = True

        for step in range(length):
            # Decoder inputs describe the previous timestep. Step zero gets an
            # explicit BOS action instead of a previous model target.
            previous[row, step, 1:3] = item["state"][step]
            if step == 0:
                previous[row, step, 3 + bos_index] = 1.0
            else:
                previous[row, step, 0] = item["dt"][step - 1]
                previous[row, step, 3 + int(item["actions"][step - 1])] = 1.0

    return {"condition": condition, "dt": dt, "pos": pos, "actions": actions, "mask": mask, "previous": previous}


class MouseTrajectoryGRU(nn.Module):
    """Conditioned GRU decoder for mouse click trajectories.

    The model embeds a seven-value click condition with a small tanh MLP, then
    repeats that embedding across decoder timesteps. At each step the GRU sees
    the click condition plus the previous predicted state: previous log delay,
    previous goal-relative position, and a one-hot previous action token with a
    BOS slot. Three independent heads predict the next log delay, the next
    goal-relative movement delta, and the mouse action class. Generation keeps
    the architecture simple and adds endpoint guidance outside the network so
    the checkpoint remains a compact cadence model rather than a general path
    planner.
    """

    def __init__(self, condition_dim: int, previous_dim: int, hidden_size: int, action_count: int, layers: int, dropout: float):
        super().__init__()
        self.condition = nn.Sequential(
            nn.Linear(condition_dim, hidden_size),
            nn.Tanh(),
            nn.Linear(hidden_size, hidden_size),
            nn.Tanh(),
        )
        self.gru = nn.GRU(
            input_size=hidden_size + previous_dim,
            hidden_size=hidden_size,
            num_layers=layers,
            dropout=dropout if layers > 1 else 0.0,
            batch_first=True,
        )
        self.dt_head = nn.Linear(hidden_size, 1)
        self.pos_head = nn.Linear(hidden_size, 2)
        self.action_head = nn.Linear(hidden_size, action_count)
        self.layers = layers

    def forward(self, condition: torch.Tensor, previous: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        condition_embedding = self.condition(condition)
        repeated = condition_embedding.unsqueeze(1).expand(-1, previous.shape[1], -1)
        decoder_input = torch.cat([repeated, previous], dim=-1)
        h0 = condition_embedding.unsqueeze(0).expand(self.layers, -1, -1).contiguous()
        output, _ = self.gru(decoder_input, h0)
        return self.dt_head(output).squeeze(-1), self.pos_head(output), self.action_head(output)


def mouse_loss(
    batch: MouseBatch,
    model: MouseTrajectoryGRU,
    dt_weight: float = 1.0,
    pos_weight: float = 1.0,
    click_action_weight: float = 8.0,
    duration_weight: float = 0.0,
) -> tuple[torch.Tensor, MouseLossMetrics]:
    """Compute the weighted mouse trajectory objective and scalar metrics.

    The optimized objective is:

    `L = w_dt * SmoothL1(dt_hat, dt) + w_pos * SmoothL1(delta_pos_hat, delta_pos)
       + CE(action_logits, action)
       + w_duration * SmoothL1(log1p(total_dt_hat), log1p(total_dt))`

    Padding is masked out of timing and position terms. Click classes are
    upweighted in cross entropy because move rows dominate each trajectory but
    the terminal click action is the behavior that makes the rollout complete.
    """
    dt_pred, pos_pred, action_logits = model(batch["condition"], batch["previous"])
    mask = batch["mask"]

    # Fit timing and goal-relative movement only on real sequence positions.
    dt_loss = masked_smooth_l1(dt_pred, batch["dt"], mask)
    pos_loss = masked_smooth_l1(pos_pred, batch["pos"], mask)

    # Click actions are sparse compared with move actions, so give them an
    # explicit weight instead of relying on the model to discover the imbalance.
    action_weights = torch.ones(action_logits.shape[-1], device=action_logits.device)
    action_weights[1:] = click_action_weight
    action_loss = F.cross_entropy(
        action_logits.reshape(-1, action_logits.shape[-1]),
        batch["actions"].reshape(-1),
        ignore_index=-100,
        weight=action_weights,
    )
    duration_loss = dt_pred.sum() * 0.0
    if duration_weight > 0:
        # Compare full episode durations in log space to avoid tiny movements
        # dominating the timing objective.
        pred_log_dt = torch.clamp(F.softplus(dt_pred), max=math.log1p(5000.0))
        target_log_dt = torch.clamp(batch["dt"], min=0.0, max=math.log1p(5000.0))
        pred_duration = (torch.expm1(pred_log_dt) * mask.float()).sum(dim=1)
        target_duration = (torch.expm1(target_log_dt) * mask.float()).sum(dim=1)
        duration_loss = F.smooth_l1_loss(torch.log1p(pred_duration), torch.log1p(target_duration))
    total = (dt_weight * dt_loss) + (pos_weight * pos_loss) + action_loss + (duration_weight * duration_loss)
    return total, {
        "loss": float(total.detach().cpu()),
        "dt_loss": float(dt_loss.detach().cpu()),
        "weighted_dt_loss": float((dt_weight * dt_loss).detach().cpu()),
        "pos_loss": float(pos_loss.detach().cpu()),
        "weighted_pos_loss": float((pos_weight * pos_loss).detach().cpu()),
        "action_loss": float(action_loss.detach().cpu()),
        "duration_loss": float(duration_loss.detach().cpu()),
        "weighted_duration_loss": float((duration_weight * duration_loss).detach().cpu()),
    }
