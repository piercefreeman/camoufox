"""Keyboard action dataset, model, and objective."""

from __future__ import annotations

import math
from typing import Literal, TypedDict

import torch
from torch import nn
from torch.nn import functional as F
from torch.utils.data import Dataset

from ..constants import CHAR_EOS, CHAR_SEP, CHAR_UNK, KEY_BACKSPACE, KEY_STOP
from ..keyboard_logic import (
    apply_keyboard_action,
    canonical_keyboard_steps,
    constrained_keyboard_action,
    keyboard_next_char,
)
from ..types import KeyboardEpisode
from ..utils import dt_to_log
from .common import masked_timing_loss, timing_log_mu

KeyboardSequenceMode = Literal["constrained", "raw"]
MAX_PREDICTED_PRESS_COUNT = 1024.0


def repaired_wrong_character_action(
    final_string: str,
    current_text: list[str],
    action_tokens: list[str],
    action_index: int,
) -> bool:
    """Return whether a raw action is a wrong character later repaired by deletion."""
    action = action_tokens[action_index]
    current = "".join(current_text)
    preferred_action = constrained_keyboard_action(final_string, current_text)
    if (
        not final_string.startswith(current)
        or current == final_string
        or action in {preferred_action, KEY_BACKSPACE, KEY_STOP}
    ):
        return False

    future_text = list(current_text)
    apply_keyboard_action(future_text, action)
    if final_string.startswith("".join(future_text)):
        return False

    saw_backspace = False
    for future_action in action_tokens[action_index + 1:]:
        if future_action == KEY_STOP:
            break
        if future_action == KEY_BACKSPACE and future_text:
            saw_backspace = True
        apply_keyboard_action(future_text, future_action)
        if final_string.startswith("".join(future_text)):
            return saw_backspace
    return False


class KeyboardSample(TypedDict):
    """Unbatched tensors emitted by KeyboardTrajectoryDataset.

    Shapes:
    - `final_ids`: `[condition_len]` token ids for initial text, separator,
      target text, and EOS.
    - `dt`: `[steps]` log1p millisecond delays, including the terminal stop row.
    - `actions`: `[steps]` action token ids, including `KEY_STOP`.
    - `next_char_ids`: `[steps]` target-character token ids visible to the decoder.
    - `typo_labels`: `[steps]` binary labels for learned wrong-character proposals.
    - `typo_action_ids`: `[steps]` wrong-character action ids, ignored when no typo occurs.
    """

    final_ids: torch.Tensor
    dt: torch.Tensor
    actions: torch.Tensor
    next_char_ids: torch.Tensor
    press_count: torch.Tensor
    typo_labels: torch.Tensor
    typo_action_ids: torch.Tensor


class KeyboardBatch(TypedDict):
    """Padded keyboard tensors consumed by KeyboardActionGRU and keyboard_loss."""

    final_ids: torch.Tensor
    final_lengths: torch.Tensor
    dt: torch.Tensor
    actions: torch.Tensor
    previous_actions: torch.Tensor
    previous_dt: torch.Tensor
    next_char_ids: torch.Tensor
    press_count: torch.Tensor
    typo_labels: torch.Tensor
    typo_action_ids: torch.Tensor
    mask: torch.Tensor


class KeyboardLossMetrics(TypedDict):
    """Scalar keyboard loss components logged per batch."""

    loss: float
    dt_loss: float
    weighted_dt_loss: float
    action_loss: float
    weighted_action_loss: float
    duration_loss: float
    weighted_duration_loss: float
    press_count_loss: float
    weighted_press_count_loss: float
    typo_loss: float
    weighted_typo_loss: float
    typo_action_loss: float
    weighted_typo_action_loss: float


class KeyboardMetricObservations(TypedDict, total=False):
    """Raw per-step/per-sequence values collapsed into epoch-level summaries."""

    target_wait_ms_median_values: list[float]
    pred_wait_ms_median_values: list[float]
    wait_abs_error_ms_median_values: list[float]
    target_edit_duration_ms_median_values: list[float]
    pred_edit_duration_ms_median_values: list[float]
    duration_abs_error_ms_median_values: list[float]
    target_press_count_median_values: list[float]
    pred_press_count_median_values: list[float]
    press_count_abs_error_median_values: list[float]
    key_action_error_rate_mean_values: list[float]
    target_typo_rate_mean_values: list[float]
    predicted_typo_rate_mean_values: list[float]
    typo_precision_mean_values: list[float]
    typo_recall_mean_values: list[float]


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
        sequence_mode: KeyboardSequenceMode = "constrained",
    ):
        self.episodes = episodes
        self.char_to_id = char_to_id
        self.action_to_id = action_to_id
        self.sequence_mode = sequence_mode

    def __len__(self) -> int:
        return len(self.episodes)

    def __getitem__(self, index: int) -> KeyboardSample:
        """Encode one keyboard episode into condition and decoder target tensors."""
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
        typo_labels: list[float] = []
        typo_action_ids: list[int] = []
        current_text: list[str] = list(episode.initial_string)

        for action_index, action in enumerate(action_tokens):
            next_char = keyboard_next_char(episode.final_string, current_text)
            next_char_ids.append(self.char_to_id.get(next_char, self.char_to_id[CHAR_UNK]))
            typo_action = repaired_wrong_character_action(
                episode.final_string,
                current_text,
                action_tokens,
                action_index,
            )
            typo_labels.append(1.0 if typo_action else 0.0)
            typo_action_ids.append(self.action_to_id[action] if typo_action else -100)

            if action == KEY_STOP:
                continue

            apply_keyboard_action(current_text, action)

        return {
            "final_ids": torch.tensor(final_ids, dtype=torch.long),
            "dt": torch.tensor(dt, dtype=torch.float32),
            "actions": torch.tensor(actions, dtype=torch.long),
            "next_char_ids": torch.tensor(next_char_ids, dtype=torch.long),
            "press_count": torch.tensor(float(len(steps)), dtype=torch.float32),
            "typo_labels": torch.tensor(typo_labels, dtype=torch.float32),
            "typo_action_ids": torch.tensor(typo_action_ids, dtype=torch.long),
        }


def collate_keyboard(batch: list[KeyboardSample], action_vocab_size: int) -> KeyboardBatch:
    """Pad keyboard samples and assemble previous-action decoder inputs."""
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
    press_count = torch.zeros(batch_size, dtype=torch.float32)
    typo_labels = torch.zeros(batch_size, max_steps, dtype=torch.float32)
    typo_action_ids = torch.full((batch_size, max_steps), -100, dtype=torch.long)
    mask = torch.zeros(batch_size, max_steps, dtype=torch.bool)

    for row, item in enumerate(batch):
        # Conditions and decoder targets have independent lengths, so pad each
        # side separately and retain masks for the loss functions.
        final_len = item["final_ids"].shape[0]
        step_len = item["dt"].shape[0]
        final_ids[row, :final_len] = item["final_ids"]
        final_lengths[row] = final_len
        dt[row, :step_len] = item["dt"]
        actions[row, :step_len] = item["actions"]
        next_char_ids[row, :step_len] = item["next_char_ids"]
        press_count[row] = item["press_count"]
        typo_labels[row, :step_len] = item["typo_labels"]
        typo_action_ids[row, :step_len] = item["typo_action_ids"]
        mask[row, :step_len] = True

        for step in range(1, step_len):
            # Step zero uses the BOS action index initialized above; later
            # steps condition on the previous true action and delay.
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
        "press_count": press_count,
        "typo_labels": typo_labels,
        "typo_action_ids": typo_action_ids,
        "mask": mask,
    }


class KeyboardActionGRU(nn.Module):
    """Encoder-decoder GRU for keyboard action timing and edit selection.

    The encoder reads the initial/final text condition as character embeddings
    and uses the final hidden state as a compact target representation. The
    decoder receives that representation at every timestep along with the
    previous action embedding, previous log delay, and embedding of the next
    desired target character. It predicts the next log delay and action token,
    plus optional heads for wrong-character likelihood and wrong-character
    choice. Constrained decoding lives outside this module, so the network stays
    focused on cadence and local edit preference rather than owning the full
    text-edit search problem.
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
        learned_typo_head: bool = False,
        predict_press_count_head: bool = False,
        timing_distribution: str = "point",
    ):
        super().__init__()
        if timing_distribution not in {"point", "lognormal"}:
            raise ValueError(f"Unsupported timing_distribution: {timing_distribution!r}")
        self.timing_distribution = timing_distribution
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
        self.dt_head = nn.Linear(hidden_size, 2 if timing_distribution == "lognormal" else 1)
        self.action_head = nn.Linear(hidden_size, action_vocab_size)
        self.predict_press_count_head = predict_press_count_head
        self.press_count_head = nn.Linear(hidden_size, 1) if predict_press_count_head else None
        self.learned_typo_head = learned_typo_head
        if learned_typo_head:
            self.typo_head = nn.Linear(hidden_size, 1)
            self.typo_action_head = nn.Linear(hidden_size, action_vocab_size)
        else:
            self.typo_head = None
            self.typo_action_head = None
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
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor | None, torch.Tensor | None, torch.Tensor | None]:
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
        press_count_logits = self.press_count_head(condition).squeeze(-1) if self.press_count_head is not None else None
        typo_logits = self.typo_head(output).squeeze(-1) if self.typo_head is not None else None
        typo_action_logits = self.typo_action_head(output) if self.typo_action_head is not None else None
        dt = self.dt_head(output)
        if self.timing_distribution == "point":
            dt = dt.squeeze(-1)
        return dt, self.action_head(output), typo_logits, typo_action_logits, press_count_logits


def decode_press_count_logits(press_count_logits: torch.Tensor) -> torch.Tensor:
    """Map raw press-count logits onto the non-negative press-count domain."""
    pred_press_count_log = torch.clamp(F.softplus(press_count_logits), max=math.log1p(MAX_PREDICTED_PRESS_COUNT))
    return torch.expm1(pred_press_count_log)


def keyboard_metric_observations(
    batch: KeyboardBatch,
    dt_pred: torch.Tensor,
    action_logits: torch.Tensor,
    typo_logits: torch.Tensor | None,
    press_count_logits: torch.Tensor | None,
) -> KeyboardMetricObservations:
    """Collect interpretable timing and typo observations for epoch summaries."""
    stop_action_id = action_logits.shape[-1] - 1
    action_mask = batch["mask"] & (batch["actions"] != -100) & (batch["actions"] != stop_action_id)
    if not bool(action_mask.any()):
        return {}

    dt_log_mu = timing_log_mu(dt_pred)
    pred_dt_ms = torch.expm1(torch.clamp(dt_log_mu, min=0.0, max=math.log1p(5000.0)))
    target_dt_ms = torch.expm1(torch.clamp(batch["dt"], min=0.0, max=math.log1p(5000.0)))
    pred_action_ids = action_logits.argmax(dim=-1)

    action_mask_float = action_mask.float()
    pred_duration_ms = (pred_dt_ms * action_mask_float).sum(dim=1)
    target_duration_ms = (target_dt_ms * action_mask_float).sum(dim=1)

    observations: KeyboardMetricObservations = {
        "target_wait_ms_median_values": target_dt_ms[action_mask].detach().cpu().tolist(),
        "pred_wait_ms_median_values": pred_dt_ms[action_mask].detach().cpu().tolist(),
        "wait_abs_error_ms_median_values": (pred_dt_ms - target_dt_ms).abs()[action_mask].detach().cpu().tolist(),
        "target_edit_duration_ms_median_values": target_duration_ms.detach().cpu().tolist(),
        "pred_edit_duration_ms_median_values": pred_duration_ms.detach().cpu().tolist(),
        "duration_abs_error_ms_median_values": (pred_duration_ms - target_duration_ms).abs().detach().cpu().tolist(),
        "key_action_error_rate_mean_values": (
            (pred_action_ids != batch["actions"])[action_mask].float().detach().cpu().tolist()
        ),
        "target_typo_rate_mean_values": batch["typo_labels"][action_mask].detach().cpu().tolist(),
    }

    if press_count_logits is not None:
        pred_press_count = decode_press_count_logits(press_count_logits)
        observations["target_press_count_median_values"] = batch["press_count"].detach().cpu().tolist()
        observations["pred_press_count_median_values"] = pred_press_count.detach().cpu().tolist()
        observations["press_count_abs_error_median_values"] = (
            (pred_press_count - batch["press_count"]).abs().detach().cpu().tolist()
        )

    if typo_logits is None:
        return observations

    predicted_typo = torch.sigmoid(typo_logits) >= 0.5
    observations["predicted_typo_rate_mean_values"] = (
        predicted_typo[action_mask].float().detach().cpu().tolist()
    )

    typo_positive_mask = action_mask & (batch["typo_labels"] > 0.5)
    if bool(typo_positive_mask.any()):
        observations["typo_recall_mean_values"] = (
            predicted_typo[typo_positive_mask].float().detach().cpu().tolist()
        )

    predicted_positive_mask = action_mask & predicted_typo
    if bool(predicted_positive_mask.any()):
        observations["typo_precision_mean_values"] = (
            batch["typo_labels"][predicted_positive_mask].detach().cpu().tolist()
        )

    return observations


def keyboard_loss(
    batch: KeyboardBatch,
    model: KeyboardActionGRU,
    dt_weight: float = 1.0,
    action_weight: float = 1.0,
    duration_weight: float = 0.0,
    press_count_weight: float = 1.0,
    backspace_action_weight: float = 4.0,
    stop_action_weight: float = 8.0,
    typo_weight: float = 1.0,
    typo_action_weight: float = 1.0,
    typo_positive_weight: float = 8.0,
) -> tuple[torch.Tensor, KeyboardLossMetrics, KeyboardMetricObservations]:
    """Compute the weighted keyboard action objective and scalar metrics.

    The optimized objective is:

    `L = w_dt * SmoothL1(dt_hat, dt) + w_action * CE(action_logits, action)
       + w_duration * SmoothL1(log1p(sum(exp(dt_hat)-1)), log1p(sum(exp(dt)-1)))
       + w_press * SmoothL1(log1p(press_count_hat), log1p(press_count))
       + w_typo * BCE(typo_logit, is_wrong_char)
       + w_typo_action * CE(typo_action_logits, wrong_char_action)`

    Padding is masked out of all sequence terms. Backspace and stop receive
    larger cross-entropy weights because they are sparse but determine whether
    generated edits can terminate cleanly or repair mistakes.
    """
    dt_pred, action_logits, typo_logits, typo_action_logits, press_count_logits = model(
        batch["final_ids"],
        batch["final_lengths"],
        batch["previous_actions"],
        batch["previous_dt"],
        batch["next_char_ids"],
    )
    mask = batch["mask"]

    # Timing is trained over valid decoder positions while padding is ignored.
    dt_loss = masked_timing_loss(dt_pred, batch["dt"], mask)

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

    dt_log_mu = timing_log_mu(dt_pred)
    duration_loss = dt_log_mu.sum() * 0.0
    press_count_loss = dt_log_mu.sum() * 0.0
    typo_loss = dt_log_mu.sum() * 0.0
    typo_action_loss = dt_log_mu.sum() * 0.0

    if duration_weight > 0:
        # Match full edit duration in addition to per-key delays; this helps
        # avoid plausible-looking sequences that are globally too fast or slow.
        pred_dt_ms = torch.expm1(torch.clamp(dt_log_mu, min=0.0, max=math.log1p(5000.0)))
        target_dt_ms = torch.expm1(torch.clamp(batch["dt"], min=0.0, max=math.log1p(5000.0)))
        pred_duration = (pred_dt_ms * mask.float()).sum(dim=1)
        target_duration = (target_dt_ms * mask.float()).sum(dim=1)
        duration_loss = F.smooth_l1_loss(torch.log1p(pred_duration), torch.log1p(target_duration))

    if press_count_logits is not None:
        pred_press_count_log = torch.log1p(decode_press_count_logits(press_count_logits))
        target_press_count_log = torch.log1p(batch["press_count"])
        press_count_loss = F.smooth_l1_loss(pred_press_count_log, target_press_count_log)

    if typo_logits is not None:
        pos_weight = torch.tensor(float(typo_positive_weight), device=typo_logits.device)
        typo_loss = F.binary_cross_entropy_with_logits(
            typo_logits[mask],
            batch["typo_labels"][mask],
            pos_weight=pos_weight,
        )
    if typo_action_logits is not None and bool((batch["typo_action_ids"] != -100).any()):
        typo_action_loss = F.cross_entropy(
            typo_action_logits.reshape(-1, typo_action_logits.shape[-1]),
            batch["typo_action_ids"].reshape(-1),
            ignore_index=-100,
        )

    total = (
        (dt_weight * dt_loss)
        + (action_weight * action_loss)
        + (duration_weight * duration_loss)
        + (press_count_weight * press_count_loss)
        + (typo_weight * typo_loss)
        + (typo_action_weight * typo_action_loss)
    )

    return (
        total,
        {
            "loss": float(total.detach().cpu()),
            "dt_loss": float(dt_loss.detach().cpu()),
            "weighted_dt_loss": float((dt_weight * dt_loss).detach().cpu()),
            "action_loss": float(action_loss.detach().cpu()),
            "weighted_action_loss": float((action_weight * action_loss).detach().cpu()),
            "duration_loss": float(duration_loss.detach().cpu()),
            "weighted_duration_loss": float((duration_weight * duration_loss).detach().cpu()),
            "press_count_loss": float(press_count_loss.detach().cpu()),
            "weighted_press_count_loss": float((press_count_weight * press_count_loss).detach().cpu()),
            "typo_loss": float(typo_loss.detach().cpu()),
            "weighted_typo_loss": float((typo_weight * typo_loss).detach().cpu()),
            "typo_action_loss": float(typo_action_loss.detach().cpu()),
            "weighted_typo_action_loss": float((typo_action_weight * typo_action_loss).detach().cpu()),
        },
        keyboard_metric_observations(
            batch=batch,
            dt_pred=dt_pred,
            action_logits=action_logits,
            typo_logits=typo_logits,
            press_count_logits=press_count_logits,
        ),
    )
