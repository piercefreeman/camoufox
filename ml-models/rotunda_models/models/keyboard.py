"""Keyboard action dataset, model, and objective."""

from __future__ import annotations

import math

import torch
from torch import nn
from torch.nn import functional as F
from torch.utils.data import Dataset

from ..constants import CHAR_EOS, CHAR_SEP, CHAR_UNK, KEY_STOP
from ..keyboard_logic import (
    apply_keyboard_action,
    canonical_keyboard_steps,
    keyboard_next_char,
)
from ..types import KeyboardEpisode
from ..utils import dt_to_log
from .common import masked_smooth_l1


class KeyboardTrajectoryDataset(Dataset):
    """Tensor view of reconstructed keyboard edit episodes.

    A sample encodes the optional initial string, a separator, the target final
    string, and EOS as the condition sequence for the encoder. Decoder targets
    can either use the raw focused-text edits or a constrained canonical path,
    depending on the source. For every decoder step the dataset also provides
    the next desired target character, giving the model timing freedom while
    keeping generation anchored to text that can still reach the requested
    final string.
    """

    def __init__(
        self,
        episodes: list[KeyboardEpisode],
        char_to_id: dict[str, int],
        action_to_id: dict[str, int],
        sequence_mode: str = "constrained",
    ):
        self.episodes = episodes
        self.char_to_id = char_to_id
        self.action_to_id = action_to_id
        self.sequence_mode = sequence_mode

    def __len__(self) -> int:
        return len(self.episodes)

    def __getitem__(self, index: int) -> dict:
        episode = self.episodes[index]
        condition_tokens = [*episode.initial_string, CHAR_SEP, *episode.final_string, CHAR_EOS]
        final_ids = [self.char_to_id.get(char, self.char_to_id[CHAR_UNK]) for char in condition_tokens]
        if self.sequence_mode == "constrained":
            steps = canonical_keyboard_steps(episode)
        elif self.sequence_mode == "raw":
            steps = episode.steps
        else:
            raise ValueError(f"Unknown keyboard sequence mode: {self.sequence_mode!r}")
        action_tokens = [step.action for step in steps] + [KEY_STOP]
        actions = [self.action_to_id[action] for action in action_tokens]
        dt = [dt_to_log(step.dt_ms) for step in steps] + [0.0]
        next_char_ids: list[int] = []
        current_text: list[str] = list(episode.initial_string)
        for action in action_tokens:
            next_char = keyboard_next_char(episode.final_string, current_text)
            next_char_ids.append(self.char_to_id.get(next_char, self.char_to_id[CHAR_UNK]))
            if action == KEY_STOP:
                continue
            apply_keyboard_action(current_text, action)

        return {
            "final_ids": torch.tensor(final_ids, dtype=torch.long),
            "dt": torch.tensor(dt, dtype=torch.float32),
            "actions": torch.tensor(actions, dtype=torch.long),
            "next_char_ids": torch.tensor(next_char_ids, dtype=torch.long),
        }


def collate_keyboard(batch: list[dict], action_vocab_size: int) -> dict:
    batch_size = len(batch)
    max_final = max(item["final_ids"].shape[0] for item in batch)
    max_steps = max(item["dt"].shape[0] for item in batch)
    bos_index = action_vocab_size

    final_ids = torch.zeros(batch_size, max_final, dtype=torch.long)
    final_lengths = torch.zeros(batch_size, dtype=torch.long)
    dt = torch.zeros(batch_size, max_steps, dtype=torch.float32)
    actions = torch.full((batch_size, max_steps), -100, dtype=torch.long)
    previous_actions = torch.full((batch_size, max_steps), bos_index, dtype=torch.long)
    previous_dt = torch.zeros(batch_size, max_steps, dtype=torch.float32)
    next_char_ids = torch.zeros(batch_size, max_steps, dtype=torch.long)
    mask = torch.zeros(batch_size, max_steps, dtype=torch.bool)

    for row, item in enumerate(batch):
        final_len = item["final_ids"].shape[0]
        step_len = item["dt"].shape[0]
        final_ids[row, :final_len] = item["final_ids"]
        final_lengths[row] = final_len
        dt[row, :step_len] = item["dt"]
        actions[row, :step_len] = item["actions"]
        next_char_ids[row, :step_len] = item["next_char_ids"]
        mask[row, :step_len] = True
        for step in range(1, step_len):
            previous_actions[row, step] = item["actions"][step - 1]
            previous_dt[row, step] = item["dt"][step - 1]

    return {
        "final_ids": final_ids,
        "final_lengths": final_lengths,
        "dt": dt,
        "actions": actions,
        "previous_actions": previous_actions,
        "previous_dt": previous_dt,
        "next_char_ids": next_char_ids,
        "mask": mask,
    }


class KeyboardActionGRU(nn.Module):
    """Encoder-decoder GRU for keyboard action timing and edit selection.

    The encoder reads the initial/final text condition as character embeddings
    and uses the final hidden state as a compact target representation. The
    decoder receives that representation at every timestep along with the
    previous action embedding, previous log delay, and embedding of the next
    desired target character. It predicts two heads: the next log delay and the
    next action token. Constrained decoding lives outside this module, so the
    network stays focused on cadence and local edit preference rather than
    owning the full text-edit search problem.
    """

    def __init__(
        self,
        char_vocab_size: int,
        action_vocab_size: int,
        hidden_size: int,
        char_embed_size: int,
        action_embed_size: int,
        layers: int,
        dropout: float,
    ):
        super().__init__()
        self.char_embed = nn.Embedding(char_vocab_size, char_embed_size, padding_idx=0)
        self.encoder = nn.GRU(char_embed_size, hidden_size, batch_first=True)
        self.action_embed = nn.Embedding(action_vocab_size + 1, action_embed_size)
        self.decoder = nn.GRU(
            input_size=hidden_size + action_embed_size + char_embed_size + 1,
            hidden_size=hidden_size,
            num_layers=layers,
            dropout=dropout if layers > 1 else 0.0,
            batch_first=True,
        )
        self.dt_head = nn.Linear(hidden_size, 1)
        self.action_head = nn.Linear(hidden_size, action_vocab_size)
        self.layers = layers

    def encode(self, final_ids: torch.Tensor, final_lengths: torch.Tensor) -> torch.Tensor:
        embedded = self.char_embed(final_ids)
        packed = nn.utils.rnn.pack_padded_sequence(
            embedded,
            final_lengths.cpu(),
            batch_first=True,
            enforce_sorted=False,
        )
        _, h_n = self.encoder(packed)
        return h_n[-1]

    def forward(
        self,
        final_ids: torch.Tensor,
        final_lengths: torch.Tensor,
        previous_actions: torch.Tensor,
        previous_dt: torch.Tensor,
        next_char_ids: torch.Tensor,
    ) -> tuple[torch.Tensor, torch.Tensor]:
        condition = self.encode(final_ids, final_lengths)
        repeated = condition.unsqueeze(1).expand(-1, previous_actions.shape[1], -1)
        previous_action_embedding = self.action_embed(previous_actions)
        next_char_embedding = self.char_embed(next_char_ids)
        decoder_input = torch.cat(
            [repeated, previous_action_embedding, next_char_embedding, previous_dt.unsqueeze(-1)],
            dim=-1,
        )
        h0 = condition.unsqueeze(0).expand(self.layers, -1, -1).contiguous()
        output, _ = self.decoder(decoder_input, h0)
        return self.dt_head(output).squeeze(-1), self.action_head(output)


def keyboard_loss(
    batch: dict,
    model: KeyboardActionGRU,
    dt_weight: float = 1.0,
    action_weight: float = 1.0,
    duration_weight: float = 0.0,
    backspace_action_weight: float = 4.0,
    stop_action_weight: float = 8.0,
) -> tuple[torch.Tensor, dict[str, float]]:
    dt_pred, action_logits = model(
        batch["final_ids"],
        batch["final_lengths"],
        batch["previous_actions"],
        batch["previous_dt"],
        batch["next_char_ids"],
    )
    mask = batch["mask"]

    # Timing is trained over valid decoder positions while padding is ignored.
    dt_loss = masked_smooth_l1(dt_pred, batch["dt"], mask)

    # Backspace and stop are rare but behaviorally important, so expose their
    # weights as training knobs instead of hiding them in the dataset.
    action_weights = torch.ones(action_logits.shape[-1], device=action_logits.device)
    if action_logits.shape[-1] >= 2:
        action_weights[-2] = backspace_action_weight
        action_weights[-1] = stop_action_weight
    action_loss = F.cross_entropy(
        action_logits.reshape(-1, action_logits.shape[-1]),
        batch["actions"].reshape(-1),
        ignore_index=-100,
        weight=action_weights,
    )
    duration_loss = dt_pred.sum() * 0.0
    if duration_weight > 0:
        # Match full edit duration in addition to per-key delays; this helps
        # avoid plausible-looking sequences that are globally too fast or slow.
        pred_dt_ms = torch.expm1(torch.clamp(dt_pred, min=0.0, max=math.log1p(5000.0)))
        target_dt_ms = torch.expm1(torch.clamp(batch["dt"], min=0.0, max=math.log1p(5000.0)))
        pred_duration = (pred_dt_ms * mask.float()).sum(dim=1)
        target_duration = (target_dt_ms * mask.float()).sum(dim=1)
        duration_loss = F.smooth_l1_loss(torch.log1p(pred_duration), torch.log1p(target_duration))
    total = (dt_weight * dt_loss) + (action_weight * action_loss) + (duration_weight * duration_loss)
    return total, {
        "loss": float(total.detach().cpu()),
        "dt_loss": float(dt_loss.detach().cpu()),
        "weighted_dt_loss": float((dt_weight * dt_loss).detach().cpu()),
        "action_loss": float(action_loss.detach().cpu()),
        "weighted_action_loss": float((action_weight * action_loss).detach().cpu()),
        "duration_loss": float(duration_loss.detach().cpu()),
        "weighted_duration_loss": float((duration_weight * duration_loss).detach().cpu()),
    }
